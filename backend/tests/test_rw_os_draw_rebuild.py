"""Refresh RW-OS + Rebuild Draws replaces draw content and leaves match numbers scheduled."""

from datetime import date, datetime, time, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlmodel import Session, select

from app.models.event import Event
from app.models.match import Match
from app.models.match_assignment import MatchAssignment
from app.models.schedule_slot import ScheduleSlot
from app.models.schedule_version import ScheduleVersion
from app.models.team import Team
from app.models.tournament import Tournament
from app.models.tournament_import import TournamentImport
from app.services.canonical_teams import SnapshotTeam, sort_teams_for_planning
from app.services.rw_os_draw_rebuild import STRUCTURE_REVIEW_MESSAGE, DrawRebuildError
from app.services.wf_pairing import TeamSeed, build_wf_r1_pairings
from tests.test_desk_rw_os_refresh import _generate_wf24_draw, _patch_refresh
from tests.test_rw_os_roster_projection import _approve, _import_payload, _mixed_field, _payload, _teams_by_key

ANCHOR_ID = 5612


def _post_rebuild(client: TestClient, import_id: int):
    return client.post(f"/api/rw-os/imports/{import_id}/refresh-rebuild-draws")


def _pin_match_id(session: Session, match: Match, new_id: int) -> None:
    old_id = match.id
    if old_id == new_id:
        return
    table = Match.__table__.name
    connection = session.connection()
    connection.execute(text(f'UPDATE "{table}" SET id = :new WHERE id = :old'), {"new": new_id, "old": old_id})
    connection.execute(
        text(f'UPDATE "{table}" SET source_match_a_id = :new WHERE source_match_a_id = :old'),
        {"new": new_id, "old": old_id},
    )
    connection.execute(
        text(f'UPDATE "{table}" SET source_match_b_id = :new WHERE source_match_b_id = :old'),
        {"new": new_id, "old": old_id},
    )
    session.commit()
    session.expire_all()


def _schedule_draw(session: Session, tournament: Tournament, matches: list[Match]) -> None:
    tournament.court_names = [f"Court {number}" for number in range(1, 9)]
    session.add(tournament)
    ordered = sorted(matches, key=lambda match: (match.match_code, match.id or 0))
    special = next(
        match
        for match in ordered
        if match.match_type == "WF" and match.round_index == 1 and match.sequence_in_round == 2
    )
    for index, match in enumerate(ordered):
        if match.id == ANCHOR_ID:
            day = date(2026, 11, 6)
            start = time(11, 0)
            end = time(12, 0)
            court_number = 1
            court_label = "Court 1"
            manual = False
        elif match.id == special.id:
            day = date(2026, 11, 7)
            start = time(7, 15)
            end = time(8, 15)
            court_number = 8
            court_label = "Court 8"
            manual = True
        else:
            start_at = datetime(2026, 11, 8, 8, 0) + timedelta(minutes=index * 5)
            day = date(2026, 11, 8)
            start = start_at.time()
            end = (start_at + timedelta(minutes=45)).time()
            court_number = 3
            court_label = "Court 3"
            manual = False
        slot = ScheduleSlot(
            tournament_id=tournament.id,
            schedule_version_id=match.schedule_version_id,
            day_date=day,
            start_time=start,
            end_time=end,
            court_number=court_number,
            court_label=court_label,
            block_minutes=60,
            is_manual_only=manual,
        )
        session.add(slot)
        session.commit()
        session.refresh(slot)
        session.add(
            MatchAssignment(
                schedule_version_id=match.schedule_version_id,
                match_id=match.id,
                slot_id=slot.id,
                assigned_by="DESK",
                locked=manual,
            )
        )
        session.commit()


def _draw_rows(session: Session, event_id: int) -> list[tuple]:
    matches = session.exec(select(Match).where(Match.event_id == event_id)).all()
    return sorted(
        (
            match.id,
            match.match_code,
            match.team_a_id,
            match.team_b_id,
            match.placeholder_side_a,
            match.placeholder_side_b,
            match.source_match_a_id,
            match.source_match_b_id,
            match.source_a_role,
            match.source_b_role,
            match.schedule_version_id,
        )
        for match in matches
    )


def _anchors(session: Session, tournament_id: int) -> list[tuple]:
    matches = session.exec(select(Match).where(Match.tournament_id == tournament_id)).all()
    rows = []
    for match in matches:
        assignment = session.exec(select(MatchAssignment).where(MatchAssignment.match_id == match.id)).one()
        slot = session.get(ScheduleSlot, assignment.slot_id)
        assert slot is not None
        rows.append(
            (
                match.id,
                match.match_code,
                assignment.id,
                assignment.slot_id,
                assignment.locked,
                slot.day_date.isoformat(),
                slot.start_time.isoformat(),
                slot.end_time.isoformat(),
                slot.court_number,
                slot.court_label,
                slot.is_manual_only,
            )
        )
    return sorted(rows)


def _scheduled_mixed(client: TestClient, session: Session, source_id: int):
    field = _mixed_field(24)
    imported = _import_payload(session, source_id, field)
    _approve(client, imported.id, {"mixed": "24"})
    session.expire_all()
    imported = session.get(TournamentImport, imported.id)
    event = session.exec(select(Event).where(Event.tournament_id == imported.tournament_id)).one()
    placed = sorted(
        [team for team in _teams_by_key(session, imported.tournament_id).values() if not team.is_defaulted],
        key=lambda team: (team.seed is None, team.seed or 0, team.id or 0),
    )
    _generate_wf24_draw(session, event, placed)
    session.expire_all()
    matches = list(session.exec(select(Match).where(Match.event_id == event.id)).all())
    first = min(
        (match for match in matches if match.match_type == "WF" and match.round_index == 1),
        key=lambda match: match.sequence_in_round,
    )
    _pin_match_id(session, first, ANCHOR_ID)
    matches = list(session.exec(select(Match).where(Match.event_id == event.id)).all())
    tournament = session.get(Tournament, imported.tournament_id)
    _schedule_draw(session, tournament, matches)
    session.expire_all()
    return {
        "field": field,
        "imported": session.get(TournamentImport, imported.id),
        "event": session.get(Event, event.id),
        "tournament": session.get(Tournament, imported.tournament_id),
    }


def _stale_entry_draw(session: Session, event_id: int) -> tuple[int, int]:
    matches = list(session.exec(select(Match).where(Match.event_id == event_id)).all())
    anchor = session.get(Match, ANCHOR_ID)
    assert anchor is not None
    other = next(
        match
        for match in matches
        if match.match_type == "WF" and match.round_index == 1 and match.sequence_in_round == 2
    )
    stale_a = other.team_a_id
    stale_b = other.team_b_id
    anchor.team_a_id = stale_a
    anchor.team_b_id = stale_b
    anchor.placeholder_side_a = "Old A"
    anchor.placeholder_side_b = "Old B"
    other.team_a_id = None
    other.team_b_id = None
    other.placeholder_side_a = "TBD"
    other.placeholder_side_b = "Seed 23"
    session.add(anchor)
    session.add(other)
    session.commit()
    return stale_a, stale_b


def _avoid_payload(field: list[SnapshotTeam]) -> list[SnapshotTeam]:
    """Bottoms that the canonical rule may swap share one rating. Seed order stays on team_rating."""
    refreshed = [SnapshotTeam.from_dict(team.to_dict()) for team in field]
    ordered = sort_teams_for_planning(refreshed)
    ordered[0].avoid_group = "A"
    ordered[12].avoid_group = "A"
    ordered[13].avoid_group = None
    ordered[12].level = 1.0
    ordered[13].level = 1.0
    return refreshed


def _r1_pairs(session: Session, event_id: int) -> list[tuple[int, int]]:
    matches = [
        match
        for match in session.exec(select(Match).where(Match.event_id == event_id)).all()
        if match.match_type == "WF" and match.round_index == 1
    ]
    return [(match.team_a_id, match.team_b_id) for match in sorted(matches, key=lambda match: match.sequence_in_round)]


def _canonical_r1_pairs(session: Session, event_id: int) -> list[tuple[int, int]]:
    teams = [
        team
        for team in session.exec(select(Team).where(Team.event_id == event_id)).all()
        if not team.is_defaulted and team.seed is not None and team.id is not None
    ]
    seeded = [
        TeamSeed(
            seed=team.seed,
            team_id=team.id,
            avoid_group=team.avoid_group,
            rating=team.rating,
            name=team.name,
            display_name=team.display_name,
        )
        for team in teams
    ]
    return build_wf_r1_pairings(seeded, len(seeded)).team_id_pairs


def test_rebuild_refreshes_mixed_draw_and_keeps_match_5612_scheduled(client: TestClient, session: Session, monkeypatch):
    ready = _scheduled_mixed(client, session, 990)
    stale_a, stale_b = _stale_entry_draw(session, ready["event"].id)
    before_anchors = _anchors(session, ready["tournament"].id)
    before_anchor = session.get(Match, ANCHOR_ID)
    assert (before_anchor.team_a_id, before_anchor.team_b_id) == (stale_a, stale_b)
    courts_before = list(ready["tournament"].court_names)
    refreshed = _avoid_payload(ready["field"])
    _patch_refresh(monkeypatch, [_payload(990, refreshed, version="rebuild")])

    response = _post_rebuild(client, ready["imported"].id)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["heading"] == "RW-OS Refreshed + Draws Rebuilt"
    assert body["scheduleNote"] == "Match numbers, dates, times, courts, and grid assignments were preserved."
    assert body["events"][0]["teamCount"] == 24
    assert body["events"][0]["structure"] == "24-team waterfall"
    assert "Who-Knows-Who" in body["events"][0]["detail"]
    session.expire_all()
    assert _anchors(session, ready["tournament"].id) == before_anchors
    assert session.get(Tournament, ready["tournament"].id).court_names == courts_before
    anchor = session.get(Match, ANCHOR_ID)
    assignment = session.exec(select(MatchAssignment).where(MatchAssignment.match_id == ANCHOR_ID)).one()
    slot = session.get(ScheduleSlot, assignment.slot_id)
    assert anchor.schedule_version_id == before_anchor.schedule_version_id
    assert slot.day_date == date(2026, 11, 6)
    assert slot.start_time == time(11, 0)
    assert slot.end_time == time(12, 0)
    assert slot.court_number == 1
    assert slot.court_label == "Court 1"
    assert (anchor.team_a_id, anchor.team_b_id) != (stale_a, stale_b)
    assert _r1_pairs(session, ready["event"].id) == _canonical_r1_pairs(session, ready["event"].id)
    by_seed = {
        team.seed: team
        for team in session.exec(select(Team).where(Team.event_id == ready["event"].id)).all()
        if not team.is_defaulted
    }
    assert by_seed[13].rating == by_seed[14].rating
    assert (anchor.team_a_id, anchor.team_b_id) == (by_seed[1].id, by_seed[14].id)
    assert (anchor.team_a_id, anchor.team_b_id) != (by_seed[1].id, by_seed[13].id)
    matches = list(session.exec(select(Match).where(Match.event_id == ready["event"].id)).all())
    r1 = [match for match in matches if match.match_type == "WF" and match.round_index == 1]
    assert all(match.team_a_id and match.team_b_id for match in r1)
    assert not any(
        placeholder in {"TBD", "Seed 23", "Seed 24"}
        for match in r1
        for placeholder in (match.placeholder_side_a, match.placeholder_side_b)
    )
    assert len({match.team_a_id for match in r1} | {match.team_b_id for match in r1}) == 24
    quarterfinals = [match for match in matches if match.match_type == "MAIN" and match.round_index == 1]
    assert quarterfinals
    assert all(match.placeholder_side_a.startswith("WFSEED:") and match.team_a_id is None for match in quarterfinals)
    assert all(match.placeholder_side_b.startswith("WFSEED:") and match.team_b_id is None for match in quarterfinals)
    live_ids = {match.id for match in matches}
    feeders = [match for match in matches if match.match_type == "WF" and match.round_index == 2]
    assert feeders
    assert all(match.source_match_a_id in live_ids and match.source_match_b_id in live_ids for match in feeders)
    versions = session.exec(
        select(ScheduleVersion).where(ScheduleVersion.tournament_id == ready["tournament"].id)
    ).all()
    assert len(versions) == 1
    assert all(version.notes != "rw-os-draw-rebuild-temp" for version in versions)

    again = _post_rebuild(client, ready["imported"].id)
    assert again.status_code == 200, again.text
    session.expire_all()
    assert _anchors(session, ready["tournament"].id) == before_anchors
    assert _r1_pairs(session, ready["event"].id) == _canonical_r1_pairs(session, ready["event"].id)
    assert len(session.exec(select(Match).where(Match.event_id == ready["event"].id)).all()) == len(matches)


def test_normal_refresh_does_not_rebuild_an_occupied_draw(client: TestClient, session: Session, monkeypatch):
    ready = _scheduled_mixed(client, session, 991)
    matches = list(session.exec(select(Match).where(Match.event_id == ready["event"].id)).all())
    r1 = sorted(
        (match for match in matches if match.match_type == "WF" and match.round_index == 1),
        key=lambda match: match.sequence_in_round,
    )
    r1[0].team_a_id, r1[1].team_a_id = r1[1].team_a_id, r1[0].team_a_id
    session.add(r1[0])
    session.add(r1[1])
    session.commit()
    before_draw = _draw_rows(session, ready["event"].id)
    before_anchors = _anchors(session, ready["tournament"].id)
    _patch_refresh(monkeypatch, [_payload(991, _avoid_payload(ready["field"]), version="refresh-only")])

    response = client.post(f"/api/rw-os/imports/{ready['imported'].id}/refresh", json={"apply": True})

    assert response.status_code == 200, response.text
    session.expire_all()
    assert _draw_rows(session, ready["event"].id) == before_draw
    assert _anchors(session, ready["tournament"].id) == before_anchors
    assert _r1_pairs(session, ready["event"].id) != _canonical_r1_pairs(session, ready["event"].id)


def _assert_unchanged(session: Session, ready: dict, draw_before: list[tuple], anchors_before: list[tuple]) -> None:
    session.expire_all()
    assert _draw_rows(session, ready["event"].id) == draw_before
    assert _anchors(session, ready["tournament"].id) == anchors_before
    versions = session.exec(
        select(ScheduleVersion).where(ScheduleVersion.tournament_id == ready["tournament"].id)
    ).all()
    assert len(versions) == 1


def test_protected_play_blocks_rebuild_and_names_the_match(client: TestClient, session: Session, monkeypatch):
    ready = _scheduled_mixed(client, session, 992)
    anchor = session.get(Match, ANCHOR_ID)
    anchor.started_at = datetime(2026, 11, 6, 11, 5)
    session.add(anchor)
    session.commit()
    draw_before = _draw_rows(session, ready["event"].id)
    anchors_before = _anchors(session, ready["tournament"].id)
    _patch_refresh(monkeypatch, [_payload(992, ready["field"])])

    response = _post_rebuild(client, ready["imported"].id)

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["code"] == "protected_play"
    assert ANCHOR_ID in detail["matchNumbers"]
    assert f"#{ANCHOR_ID}" in detail["message"]
    assert ready["event"].name in detail["message"]
    _assert_unchanged(session, ready, draw_before, anchors_before)
    assert session.get(Match, ANCHOR_ID).started_at is not None


def test_capacity_mismatch_blocks_rebuild(client: TestClient, session: Session, monkeypatch):
    ready = _scheduled_mixed(client, session, 993)
    ready["event"].team_count = 16
    session.add(ready["event"])
    session.commit()
    draw_before = _draw_rows(session, ready["event"].id)
    anchors_before = _anchors(session, ready["tournament"].id)
    _patch_refresh(monkeypatch, [_payload(993, ready["field"])])

    response = _post_rebuild(client, ready["imported"].id)

    assert response.status_code == 409
    assert response.json()["detail"]["message"] == STRUCTURE_REVIEW_MESSAGE
    _assert_unchanged(session, ready, draw_before, anchors_before)
    assert session.get(Event, ready["event"].id).team_count == 16


def test_invalid_seeds_block_rebuild(client: TestClient, session: Session, monkeypatch):
    ready = _scheduled_mixed(client, session, 994)
    team = next(iter(_teams_by_key(session, ready["tournament"].id).values()))
    team.seed = None
    session.add(team)
    session.commit()
    draw_before = _draw_rows(session, ready["event"].id)
    anchors_before = _anchors(session, ready["tournament"].id)

    def _leave_seeds(session, plans, teams, result, failed_event_ids):
        return None

    monkeypatch.setattr("app.services.rw_os_roster_projection._reconcile_active_seeds", _leave_seeds)
    _patch_refresh(monkeypatch, [_payload(994, ready["field"])])

    response = _post_rebuild(client, ready["imported"].id)

    assert response.status_code == 409
    assert response.json()["detail"]["message"] == STRUCTURE_REVIEW_MESSAGE
    _assert_unchanged(session, ready, draw_before, anchors_before)
    assert session.get(Team, team.id).seed is None


def test_reconciliation_failure_does_not_rebuild(client: TestClient, session: Session, monkeypatch):
    ready = _scheduled_mixed(client, session, 995)
    live = _teams_by_key(session, ready["tournament"].id)
    dropped = ready["field"][-1]
    dropped_team = live[dropped.team_key]
    occupied = session.exec(
        select(Match).where(Match.event_id == ready["event"].id, Match.team_a_id == dropped_team.id)
    ).first()
    if occupied is None:
        occupied = session.exec(
            select(Match).where(Match.event_id == ready["event"].id, Match.team_b_id == dropped_team.id)
        ).one()
    occupied.started_at = datetime(2026, 11, 6, 12, 0)
    session.add(occupied)
    session.commit()
    draw_before = _draw_rows(session, ready["event"].id)
    anchors_before = _anchors(session, ready["tournament"].id)
    _patch_refresh(monkeypatch, [_payload(995, ready["field"][:-1], version="drop")])

    response = _post_rebuild(client, ready["imported"].id)

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["code"] in {"roster_reconciliation_blocked", "roster_reconciliation_incomplete"}
    assert "reconcil" in detail["message"].lower() or "blocked" in detail["message"].lower()
    _assert_unchanged(session, ready, draw_before, anchors_before)
    assert session.get(Team, dropped_team.id).is_defaulted is False


def test_generation_failure_leaves_the_draw(client: TestClient, session: Session, monkeypatch):
    ready = _scheduled_mixed(client, session, 996)
    draw_before = _draw_rows(session, ready["event"].id)
    anchors_before = _anchors(session, ready["tournament"].id)

    def _boom(*_args, **_kwargs):
        raise RuntimeError("generator failed")

    monkeypatch.setattr("app.services.rw_os_draw_rebuild.generate_matches_for_event", _boom)
    _patch_refresh(monkeypatch, [_payload(996, ready["field"])])

    response = _post_rebuild(client, ready["imported"].id)

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "generation_failed"
    _assert_unchanged(session, ready, draw_before, anchors_before)


def test_match_code_mismatch_leaves_the_draw(client: TestClient, session: Session, monkeypatch):
    ready = _scheduled_mixed(client, session, 997)
    anchor = session.get(Match, ANCHOR_ID)
    anchor.match_code = "NOT_A_CANONICAL_CODE"
    session.add(anchor)
    session.commit()
    draw_before = _draw_rows(session, ready["event"].id)
    anchors_before = _anchors(session, ready["tournament"].id)
    _patch_refresh(monkeypatch, [_payload(997, ready["field"])])

    response = _post_rebuild(client, ready["imported"].id)

    assert response.status_code == 409
    assert response.json()["detail"]["message"] == STRUCTURE_REVIEW_MESSAGE
    _assert_unchanged(session, ready, draw_before, anchors_before)
    assert session.get(Match, ANCHOR_ID).match_code == "NOT_A_CANONICAL_CODE"


def test_feeder_mapping_failure_leaves_the_draw(client: TestClient, session: Session, monkeypatch):
    ready = _scheduled_mixed(client, session, 998)
    draw_before = _draw_rows(session, ready["event"].id)
    anchors_before = _anchors(session, ready["tournament"].id)
    real = __import__(
        "app.services.draw_plan_engine", fromlist=["generate_matches_for_event"]
    ).generate_matches_for_event

    def _corrupt(session, version_id, spec, linked_team_ids, existing_codes):
        matches, warnings = real(session, version_id, spec, linked_team_ids, existing_codes)
        for match in matches:
            if (match.match_code or "").endswith("WF_R2_W01"):
                match.source_match_a_id = -1
        return matches, warnings

    monkeypatch.setattr("app.services.rw_os_draw_rebuild.generate_matches_for_event", _corrupt)
    _patch_refresh(monkeypatch, [_payload(998, ready["field"])])

    response = _post_rebuild(client, ready["imported"].id)

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "feeder_mapping"
    _assert_unchanged(session, ready, draw_before, anchors_before)


def test_validation_failure_leaves_the_draw(client: TestClient, session: Session, monkeypatch):
    ready = _scheduled_mixed(client, session, 999)
    draw_before = _draw_rows(session, ready["event"].id)
    anchors_before = _anchors(session, ready["tournament"].id)

    def _fail(*_args, **_kwargs):
        raise DrawRebuildError("forced validation failure", code="validation_failed")

    monkeypatch.setattr("app.services.rw_os_draw_rebuild._validate_rebuilt_event", _fail)
    _patch_refresh(monkeypatch, [_payload(999, ready["field"])])

    response = _post_rebuild(client, ready["imported"].id)

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "validation_failed"
    _assert_unchanged(session, ready, draw_before, anchors_before)
