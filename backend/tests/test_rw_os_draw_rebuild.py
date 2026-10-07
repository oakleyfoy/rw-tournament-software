"""Refresh RW-OS + Rebuild Draws replaces draw content and leaves match numbers scheduled."""

import json
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
from app.services.rw_os_draw_rebuild import DrawRebuildError, _ordered_events
from app.services.wf_pairing import TeamSeed, build_wf_r1_pairings
from tests.test_desk_rw_os_refresh import _generate_wf24_draw, _patch_refresh
from tests.test_rw_os_roster_projection import (
    _approve,
    _approve_amelia,
    _import_payload,
    _mixed_field,
    _payload,
    _teams_by_key,
    _womens_field,
)

ANCHOR_ID = 5612
HISTORICAL_ANCHOR_ID = 5357


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
    detail = response.json()["detail"]
    assert detail["code"] == "roster_count_mismatch"
    assert detail["eventName"] == ready["event"].name
    assert "roster does not fit the approved structure" in detail["message"]
    assert "Active teams: 24" in detail["message"]
    assert "Approved capacity: 16" in detail["message"]
    assert detail["activeTeams"] == 24
    assert detail["approvedCapacity"] == 16
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
    detail = response.json()["detail"]
    assert detail["code"] == "seed_metadata_mismatch"
    assert "seed metadata is incomplete" in detail["message"]
    assert "Expected seeds: 1–24" in detail["message"]
    assert "Missing:" in detail["message"]
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
    detail = response.json()["detail"]
    assert detail["code"] == "match_code_mismatch"
    assert "does not match the generated structure" in detail["message"]
    assert "Existing matches:" in detail["message"]
    assert "Generated matches:" in detail["message"]
    assert "NOT_A_CANONICAL_CODE" not in detail["message"]
    assert "NOT_A_CANONICAL_CODE" in detail["liveOnlyMatchCodes"]
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


def _generate_wf_brackets(
    session: Session,
    event: Event,
    placed: list[Team],
    *,
    team_count: int,
    guarantee: int,
    stored_guarantee: int | None,
) -> list[Match]:
    from app.services.draw_plan_engine import DrawPlanSpec, _generate_wf_to_brackets_8

    event.team_count = team_count
    event.guarantee_selected = stored_guarantee
    event.draw_plan_json = json.dumps({"version": "1.0", "template_type": "WF_TO_BRACKETS_8", "wf_rounds": 2})
    event.draw_status = "generated"
    session.add(event)
    session.commit()
    session.refresh(event)
    version = ScheduleVersion(tournament_id=event.tournament_id, version_number=1, status="draft")
    session.add(version)
    session.commit()
    session.refresh(version)
    category = event.category.value if hasattr(event.category, "value") else str(event.category)
    spec = DrawPlanSpec(
        event_id=event.id,
        event_name=event.name,
        division="Mixed" if category == "mixed" else "Women's",
        team_count=team_count,
        template_type="WF_TO_BRACKETS_8",
        template_key="WF_TO_BRACKETS_8",
        guarantee=guarantee,
        waterfall_rounds=2,
        waterfall_minutes=60,
        standard_minutes=105,
        tournament_id=event.tournament_id,
        event_category=category,
    )
    session._allow_match_generation = True
    try:
        matches, _warnings = _generate_wf_to_brackets_8(session, version.id, spec, [team.id for team in placed])
    finally:
        session._allow_match_generation = False
    session.add_all(matches)
    session.commit()
    event.guarantee_selected = stored_guarantee
    session.add(event)
    session.commit()
    return matches


def _scheduled_brackets(
    client: TestClient,
    session: Session,
    source_id: int,
    *,
    draw: str,
    count: int,
    guarantee: int,
    stored_guarantee: int | None,
):
    field = _mixed_field(count) if draw == "mixed" else _womens_field(count)
    imported = _import_payload(session, source_id, field)
    _approve(client, imported.id, {draw: str(count)})
    session.expire_all()
    imported = session.get(TournamentImport, imported.id)
    event = session.exec(select(Event).where(Event.tournament_id == imported.tournament_id)).one()
    placed = sorted(
        [team for team in _teams_by_key(session, imported.tournament_id).values() if not team.is_defaulted],
        key=lambda team: (team.seed is None, team.seed or 0, team.id or 0),
    )
    _generate_wf_brackets(
        session,
        event,
        placed,
        team_count=count,
        guarantee=guarantee,
        stored_guarantee=stored_guarantee,
    )
    session.expire_all()
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


def test_null_guarantee_mixed_infers_4_and_rebuilds_51_matches(client: TestClient, session: Session, monkeypatch):
    ready = _scheduled_brackets(client, session, 1001, draw="mixed", count=24, guarantee=4, stored_guarantee=None)
    assert ready["event"].guarantee_selected is None
    matches = list(session.exec(select(Match).where(Match.event_id == ready["event"].id)).all())
    assert len(matches) == 51
    assert not any((match.match_code or "").endswith("_C3") for match in matches)
    before_anchors = _anchors(session, ready["tournament"].id)
    before_ids = {match.id for match in matches}
    _patch_refresh(monkeypatch, [_payload(1001, ready["field"], version="null-g4")])

    response = _post_rebuild(client, ready["imported"].id)

    assert response.status_code == 200, response.text
    session.expire_all()
    rebuilt = list(session.exec(select(Match).where(Match.event_id == ready["event"].id)).all())
    assert {match.id for match in rebuilt} == before_ids
    assert len(rebuilt) == 51
    assert {match.match_code for match in rebuilt} == {match.match_code for match in matches}
    assert not any((match.match_code or "").endswith("_C3") for match in rebuilt)
    assert _anchors(session, ready["tournament"].id) == before_anchors
    assert session.get(Event, ready["event"].id).guarantee_selected is None
    versions = session.exec(
        select(ScheduleVersion).where(ScheduleVersion.tournament_id == ready["tournament"].id)
    ).all()
    assert len(versions) == 1


def test_null_guarantee_womens_32_infers_4_and_rebuilds_68_matches(client: TestClient, session: Session, monkeypatch):
    ready = _scheduled_brackets(client, session, 1002, draw="womens", count=32, guarantee=4, stored_guarantee=None)
    assert ready["event"].guarantee_selected is None
    matches = list(session.exec(select(Match).where(Match.event_id == ready["event"].id)).all())
    assert len(matches) == 68
    assert not any((match.match_code or "").endswith("_C3") for match in matches)
    before_anchors = _anchors(session, ready["tournament"].id)
    before_ids = {match.id for match in matches}
    _patch_refresh(monkeypatch, [_payload(1002, ready["field"], version="womens-null-g4")])

    response = _post_rebuild(client, ready["imported"].id)

    assert response.status_code == 200, response.text
    session.expire_all()
    rebuilt = list(session.exec(select(Match).where(Match.event_id == ready["event"].id)).all())
    assert {match.id for match in rebuilt} == before_ids
    assert len(rebuilt) == 68
    assert {match.match_code for match in rebuilt} == {match.match_code for match in matches}
    assert _anchors(session, ready["tournament"].id) == before_anchors
    assert session.get(Event, ready["event"].id).guarantee_selected is None


def test_explicit_guarantee_4_rebuilds(client: TestClient, session: Session, monkeypatch):
    ready = _scheduled_brackets(client, session, 1003, draw="mixed", count=24, guarantee=4, stored_guarantee=4)
    before_anchors = _anchors(session, ready["tournament"].id)
    _patch_refresh(monkeypatch, [_payload(1003, ready["field"], version="explicit-4")])

    response = _post_rebuild(client, ready["imported"].id)

    assert response.status_code == 200, response.text
    session.expire_all()
    assert session.get(Event, ready["event"].id).guarantee_selected == 4
    assert len(session.exec(select(Match).where(Match.event_id == ready["event"].id)).all()) == 51
    assert _anchors(session, ready["tournament"].id) == before_anchors


def test_explicit_guarantee_5_does_not_override_live_guarantee_4(client: TestClient, session: Session, monkeypatch):
    ready = _scheduled_brackets(client, session, 1004, draw="mixed", count=24, guarantee=4, stored_guarantee=5)
    draw_before = _draw_rows(session, ready["event"].id)
    anchors_before = _anchors(session, ready["tournament"].id)
    _patch_refresh(monkeypatch, [_payload(1004, ready["field"], version="conflict-5")])

    response = _post_rebuild(client, ready["imported"].id)

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["code"] == "guarantee_conflict"
    assert detail["eventName"] == ready["event"].name
    assert "does not match its stored guarantee" in detail["message"]
    assert "Stored guarantee: 5" in detail["message"]
    assert "Existing draw topology: guarantee 4" in detail["message"]
    assert "Bracket structure requires review" in detail["message"]
    assert detail["storedGuarantee"] == 5
    assert detail["liveGuarantee"] == 4
    assert "B1_C3" not in detail["message"]
    _assert_unchanged(session, ready, draw_before, anchors_before)
    assert session.get(Event, ready["event"].id).guarantee_selected == 5


def test_null_guarantee_with_ambiguous_topology_does_not_default_to_5(
    client: TestClient, session: Session, monkeypatch
):
    ready = _scheduled_brackets(client, session, 1005, draw="mixed", count=24, guarantee=4, stored_guarantee=None)
    consolation = next(
        match
        for match in session.exec(select(Match).where(Match.event_id == ready["event"].id)).all()
        if (match.match_code or "").endswith("B1_C2")
    )
    consolation.match_code = consolation.match_code.replace("B1_C2", "B1_C9")
    session.add(consolation)
    session.commit()
    draw_before = _draw_rows(session, ready["event"].id)
    anchors_before = _anchors(session, ready["tournament"].id)
    _patch_refresh(monkeypatch, [_payload(1005, ready["field"], version="ambiguous")])

    response = _post_rebuild(client, ready["imported"].id)

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["code"] == "structure_review"
    assert "does not establish a supported guarantee" in detail["message"]
    assert "Bracket structure requires review" in detail["message"]
    assert "Generated matches" not in detail["message"]
    assert detail.get("generatedMatchCount") is None
    _assert_unchanged(session, ready, draw_before, anchors_before)
    assert session.get(Event, ready["event"].id).guarantee_selected is None


def test_rebuild_reports_womens_events_before_mixed():
    ordered = _ordered_events(
        [
            Event(id=4, tournament_id=1, category="mixed", name="Mixed", team_count=24),
            Event(id=3, tournament_id=1, category="womens", name="Women's C", team_count=32),
            Event(id=1, tournament_id=1, category="womens", name="Women's A", team_count=32),
            Event(id=2, tournament_id=1, category="womens", name="Women's B", team_count=32),
        ]
    )
    assert [event.name for event in ordered] == ["Women's A", "Women's B", "Women's C", "Mixed"]


def _version_snapshot(session: Session, version_id: int) -> list[tuple]:
    matches = session.exec(select(Match).where(Match.schedule_version_id == version_id)).all()
    rows = []
    for match in matches:
        assignment = session.exec(select(MatchAssignment).where(MatchAssignment.match_id == match.id)).one()
        slot = session.get(ScheduleSlot, assignment.slot_id)
        assert slot is not None
        rows.append(
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
                assignment.id,
                assignment.slot_id,
                assignment.locked,
                assignment.schedule_version_id,
                slot.id,
                slot.schedule_version_id,
                slot.day_date.isoformat(),
                slot.start_time.isoformat(),
                slot.end_time.isoformat(),
                slot.court_number,
                slot.court_label,
            )
        )
    return sorted(rows)


def _wf_r1_matches(session: Session, event_id: int, version_id: int) -> list[Match]:
    return sorted(
        (
            match
            for match in session.exec(
                select(Match).where(Match.event_id == event_id, Match.schedule_version_id == version_id)
            ).all()
            if match.match_type == "WF" and match.round_index == 1
        ),
        key=lambda match: match.sequence_in_round,
    )


def _r1_pairs_on_version(session: Session, event_id: int, version_id: int) -> list[tuple[int, int]]:
    return [(match.team_a_id, match.team_b_id) for match in _wf_r1_matches(session, event_id, version_id)]


def _schedule_version_matches(session: Session, tournament: Tournament, matches: list[Match]) -> None:
    tournament.court_names = [f"Court {number}" for number in range(1, 9)]
    session.add(tournament)
    ordered = sorted(matches, key=lambda match: (match.match_code or "", match.id or 0))
    special = next(
        match
        for match in ordered
        if match.match_type == "WF" and match.round_index == 1 and match.sequence_in_round == 2
    )
    pending = []
    for index, match in enumerate(ordered):
        if match.id in {ANCHOR_ID, HISTORICAL_ANCHOR_ID}:
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
        pending.append((match, slot, manual))
    session.flush()
    for match, slot, manual in pending:
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


def _point_public(session: Session, tournament: Tournament, version: ScheduleVersion) -> None:
    tournament.public_schedule_version_id = version.id
    session.add(tournament)
    session.commit()


def _mark_desk_draft(session: Session, tournament: Tournament, version: ScheduleVersion) -> None:
    version.status = "draft"
    version.notes = "Desk Draft"
    session.add(version)
    _point_public(session, tournament, version)


def _assigned_clone(client: TestClient, session: Session, source_id: int) -> dict:
    from app.routes.schedule import _clone_final_to_draft

    ready = _scheduled_mixed(client, session, source_id)
    historical = session.exec(
        select(ScheduleVersion).where(ScheduleVersion.tournament_id == ready["tournament"].id)
    ).one()
    historical.status = "final"
    session.add(historical)
    session.commit()
    current = _clone_final_to_draft(ready["tournament"].id, historical.id, session)
    session.expire_all()
    ready["historical"] = session.get(ScheduleVersion, historical.id)
    ready["current"] = session.get(ScheduleVersion, current.id)
    ready["tournament"] = session.get(Tournament, ready["tournament"].id)
    return ready


def _generate_g4_on_version(session: Session, event: Event, version: ScheduleVersion, placed: list[Team]) -> None:
    from app.services.draw_plan_engine import DrawPlanSpec, _generate_wf_to_brackets_8

    event.guarantee_selected = None
    event.draw_plan_json = json.dumps({"version": "1.0", "template_type": "WF_TO_BRACKETS_8", "wf_rounds": 2})
    event.draw_status = "generated"
    session.add(event)
    session.commit()
    session.refresh(event)
    category = event.category.value if hasattr(event.category, "value") else str(event.category)
    spec = DrawPlanSpec(
        event_id=event.id,
        event_name=event.name,
        division="Mixed" if category == "mixed" else "Women's",
        team_count=event.team_count,
        template_type="WF_TO_BRACKETS_8",
        template_key="WF_TO_BRACKETS_8",
        guarantee=4,
        waterfall_rounds=2,
        waterfall_minutes=60,
        standard_minutes=105,
        tournament_id=event.tournament_id,
        event_category=category,
    )
    session._allow_match_generation = True
    try:
        matches, _warnings = _generate_wf_to_brackets_8(
            session, version.id, spec, [team.id for team in placed if team.id is not None]
        )
    finally:
        session._allow_match_generation = False
    session.add_all(matches)
    session.commit()
    event.guarantee_selected = None
    session.add(event)
    session.commit()


def _wild_dunes_clone(client: TestClient, session: Session, source_id: int) -> dict:
    """Two complete assigned copies: historical source, and the desk draft that is also published."""
    from app.routes.schedule import _clone_final_to_draft

    womens = _womens_field(96)
    mixed = _mixed_field(24)
    imported = _import_payload(session, source_id, womens + mixed)
    _approve_amelia(client, imported.id, womens=[32, 32, 32], mixed=[24])
    session.expire_all()
    imported = session.get(TournamentImport, imported.id)
    tournament = session.get(Tournament, imported.tournament_id)
    events = list(session.exec(select(Event).where(Event.tournament_id == tournament.id)).all())
    historical = ScheduleVersion(tournament_id=tournament.id, version_number=1, status="draft")
    session.add(historical)
    session.commit()
    session.refresh(historical)
    for event in events:
        placed = sorted(
            (
                team
                for team in session.exec(select(Team).where(Team.event_id == event.id)).all()
                if not team.is_defaulted
            ),
            key=lambda team: (team.seed is None, team.seed or 0, team.id or 0),
        )
        assert len(placed) == event.team_count
        _generate_g4_on_version(session, event, historical, placed)
    session.expire_all()
    mixed_event = next(
        event
        for event in session.exec(select(Event).where(Event.tournament_id == tournament.id)).all()
        if (event.category.value if hasattr(event.category, "value") else str(event.category)) == "mixed"
    )
    historical_r1 = _wf_r1_matches(session, mixed_event.id, historical.id)
    anchor = next(match for match in historical_r1 if (match.match_code or "").endswith("WF_R1_01"))
    _pin_match_id(session, anchor, HISTORICAL_ANCHOR_ID)
    historical = session.get(ScheduleVersion, historical.id)
    historical.status = "final"
    session.add(historical)
    session.commit()
    current = _clone_final_to_draft(tournament.id, historical.id, session)
    session.expire_all()
    historical_anchor = session.get(Match, HISTORICAL_ANCHOR_ID)
    current_anchor = session.exec(
        select(Match).where(
            Match.schedule_version_id == current.id,
            Match.match_code == historical_anchor.match_code,
        )
    ).one()
    _pin_match_id(session, current_anchor, ANCHOR_ID)
    tournament = session.get(Tournament, tournament.id)
    for version_id in (historical.id, current.id):
        matches = list(session.exec(select(Match).where(Match.schedule_version_id == version_id)).all())
        _schedule_version_matches(session, tournament, matches)
    session.expire_all()
    historical_r1 = _wf_r1_matches(session, mixed_event.id, historical.id)
    historical_r1[1].team_b_id, historical_r1[2].team_b_id = historical_r1[2].team_b_id, historical_r1[1].team_b_id
    historical_r1[1].placeholder_side_b, historical_r1[2].placeholder_side_b = (
        historical_r1[2].placeholder_side_b,
        historical_r1[1].placeholder_side_b,
    )
    session.add(historical_r1[1])
    session.add(historical_r1[2])
    current_r1 = _wf_r1_matches(session, mixed_event.id, current.id)
    current_anchor = next(match for match in current_r1 if match.id == ANCHOR_ID)
    displaced = next(match for match in current_r1 if match.sequence_in_round == 2)
    current_anchor.team_a_id = displaced.team_a_id
    current_anchor.team_b_id = displaced.team_b_id
    current_anchor.placeholder_side_a = "Old A"
    current_anchor.placeholder_side_b = "Old B"
    displaced.team_a_id = None
    displaced.team_b_id = None
    displaced.placeholder_side_a = "TBD"
    displaced.placeholder_side_b = "Seed 23"
    session.add(current_anchor)
    session.add(displaced)
    current = session.get(ScheduleVersion, current.id)
    _mark_desk_draft(session, tournament, current)
    session.expire_all()
    return {
        "field": womens + mixed,
        "womens": womens,
        "mixed": mixed,
        "imported": session.get(TournamentImport, imported.id),
        "tournament": session.get(Tournament, tournament.id),
        "mixed_event": session.get(Event, mixed_event.id),
        "historical": session.get(ScheduleVersion, historical.id),
        "current": session.get(ScheduleVersion, current.id),
    }


def test_historical_assigned_clone_rebuilds_only_the_desk_draft(client: TestClient, session: Session, monkeypatch):
    ready = _wild_dunes_clone(client, session, 1100)
    historical = ready["historical"]
    current = ready["current"]
    assert historical.id < current.id
    assert current.notes == "Desk Draft"
    assert current.status == "draft"
    assert ready["tournament"].public_schedule_version_id == current.id
    historical_matches = list(session.exec(select(Match).where(Match.schedule_version_id == historical.id)).all())
    current_matches = list(session.exec(select(Match).where(Match.schedule_version_id == current.id)).all())
    assert len(historical_matches) == 255
    assert len(current_matches) == 255
    assert len({match.event_id for match in current_matches}) == 4
    assert sum(1 for match in current_matches if match.event_id == ready["mixed_event"].id) == 51
    assert (
        len(session.exec(select(MatchAssignment).where(MatchAssignment.schedule_version_id == historical.id)).all())
        == 255
    )
    assert (
        len(session.exec(select(MatchAssignment).where(MatchAssignment.schedule_version_id == current.id)).all()) == 255
    )
    historical_before = _version_snapshot(session, historical.id)
    current_before = _version_snapshot(session, current.id)
    anchor = session.get(Match, ANCHOR_ID)
    historical_anchor = session.get(Match, HISTORICAL_ANCHOR_ID)
    anchor_assignment = session.exec(select(MatchAssignment).where(MatchAssignment.match_id == ANCHOR_ID)).one()
    anchor_slot = session.get(ScheduleSlot, anchor_assignment.slot_id)
    assert anchor.schedule_version_id == current.id
    assert (anchor.match_code or "").endswith("WF_R1_01")
    assert anchor.event_id == ready["mixed_event"].id
    assert anchor_slot.day_date == date(2026, 11, 6)
    assert anchor_slot.start_time == time(11, 0)
    assert anchor_slot.court_number == 1
    assert anchor_slot.court_label == "Court 1"
    assert historical_anchor.schedule_version_id == historical.id
    assert historical_anchor.match_code == anchor.match_code
    stale_sides = (anchor.team_a_id, anchor.team_b_id)
    assert all(
        event.guarantee_selected is None
        for event in session.exec(select(Event).where(Event.tournament_id == ready["tournament"].id))
    )
    _patch_refresh(
        monkeypatch, [_payload(1100, ready["womens"] + _avoid_payload(ready["mixed"]), version="wild-dunes")]
    )

    response = _post_rebuild(client, ready["imported"].id)

    assert response.status_code == 200, response.text
    session.expire_all()
    assert _version_snapshot(session, historical.id) == historical_before
    assert session.get(Match, HISTORICAL_ANCHOR_ID).team_a_id == historical_anchor.team_a_id
    assert session.get(Match, HISTORICAL_ANCHOR_ID).team_b_id == historical_anchor.team_b_id
    assert session.get(Match, HISTORICAL_ANCHOR_ID).schedule_version_id == historical.id
    rebuilt_anchor = session.get(Match, ANCHOR_ID)
    rebuilt_assignment = session.exec(select(MatchAssignment).where(MatchAssignment.match_id == ANCHOR_ID)).one()
    rebuilt_slot = session.get(ScheduleSlot, rebuilt_assignment.slot_id)
    assert rebuilt_anchor.schedule_version_id == current.id
    assert rebuilt_anchor.match_code == anchor.match_code
    assert rebuilt_assignment.id == anchor_assignment.id
    assert rebuilt_assignment.slot_id == anchor_slot.id
    assert rebuilt_slot.day_date == date(2026, 11, 6)
    assert rebuilt_slot.start_time == time(11, 0)
    assert rebuilt_slot.end_time == time(12, 0)
    assert rebuilt_slot.court_number == 1
    assert rebuilt_slot.court_label == "Court 1"
    assert (rebuilt_anchor.team_a_id, rebuilt_anchor.team_b_id) != stale_sides
    assert _r1_pairs_on_version(session, ready["mixed_event"].id, current.id) == _canonical_r1_pairs(
        session, ready["mixed_event"].id
    )
    assert _r1_pairs_on_version(session, ready["mixed_event"].id, historical.id) != _canonical_r1_pairs(
        session, ready["mixed_event"].id
    )
    current_after = list(session.exec(select(Match).where(Match.schedule_version_id == current.id)).all())
    assert {match.id for match in current_after} == {match.id for match in current_matches}
    assert len(current_after) == 255
    assert sum(1 for match in current_after if match.event_id == ready["mixed_event"].id) == 51
    assert all(
        session.get(Event, event_id).guarantee_selected is None
        for event_id in {match.event_id for match in current_after}
    )
    versions = session.exec(
        select(ScheduleVersion).where(ScheduleVersion.tournament_id == ready["tournament"].id)
    ).all()
    assert {version.id for version in versions} == {historical.id, current.id}
    assert all(version.notes != "rw-os-draw-rebuild-temp" for version in versions)
    current_codes = {row[1] for row in _version_snapshot(session, current.id)}
    historical_codes = {row[1] for row in historical_before}
    assert current_codes == historical_codes
    assert len(current_before) == 255


def test_desk_draft_and_published_mismatch_blocks_both_versions(client: TestClient, session: Session, monkeypatch):
    ready = _assigned_clone(client, session, 1101)
    ready["current"].notes = "Desk Draft"
    ready["current"].status = "draft"
    session.add(ready["current"])
    _point_public(session, ready["tournament"], ready["historical"])
    session.expire_all()
    historical_before = _version_snapshot(session, ready["historical"].id)
    current_before = _version_snapshot(session, ready["current"].id)
    _patch_refresh(monkeypatch, [_payload(1101, _avoid_payload(ready["field"]), version="ambiguous")])

    response = _post_rebuild(client, ready["imported"].id)

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["code"] == "schedule_version_ambiguous"
    assert "do not match" in detail["message"]
    assert f"Desk version: {ready['current'].id}" in detail["message"]
    assert f"Published version: {ready['historical'].id}" in detail["message"]
    assert "Select/publish the intended schedule" in detail["message"]
    assert "More than one schedule version" not in detail["message"]
    session.expire_all()
    assert _version_snapshot(session, ready["historical"].id) == historical_before
    assert _version_snapshot(session, ready["current"].id) == current_before


def test_published_version_is_used_when_there_is_no_desk_draft(client: TestClient, session: Session, monkeypatch):
    ready = _assigned_clone(client, session, 1102)
    assert ready["current"].notes != "Desk Draft"
    assert ready["historical"].status == "final"
    assert ready["current"].id > ready["historical"].id
    _point_public(session, ready["tournament"], ready["current"])
    historical_before = _version_snapshot(session, ready["historical"].id)
    _patch_refresh(monkeypatch, [_payload(1102, _avoid_payload(ready["field"]), version="published")])

    response = _post_rebuild(client, ready["imported"].id)

    assert response.status_code == 200, response.text
    session.expire_all()
    assert _version_snapshot(session, ready["historical"].id) == historical_before
    assert _r1_pairs_on_version(session, ready["event"].id, ready["current"].id) == _canonical_r1_pairs(
        session, ready["event"].id
    )


def test_latest_final_is_used_when_desk_and_published_are_absent(client: TestClient, session: Session, monkeypatch):
    ready = _assigned_clone(client, session, 1103)
    assert ready["tournament"].public_schedule_version_id is None
    assert ready["current"].notes != "Desk Draft"
    assert ready["current"].version_number > ready["historical"].version_number
    current_before = _version_snapshot(session, ready["current"].id)
    _patch_refresh(monkeypatch, [_payload(1103, _avoid_payload(ready["field"]), version="final")])

    response = _post_rebuild(client, ready["imported"].id)

    assert response.status_code == 200, response.text
    session.expire_all()
    assert _version_snapshot(session, ready["current"].id) == current_before
    assert _r1_pairs_on_version(session, ready["event"].id, ready["historical"].id) == _canonical_r1_pairs(
        session, ready["event"].id
    )


def test_tied_final_versions_block_instead_of_using_the_higher_id(client: TestClient, session: Session, monkeypatch):
    ready = _assigned_clone(client, session, 1104)
    ready["current"].status = "final"
    ready["current"].notes = None
    ready["current"].version_number = ready["historical"].version_number
    session.add(ready["current"])
    ready["tournament"].public_schedule_version_id = None
    session.add(ready["tournament"])
    session.commit()
    historical_before = _version_snapshot(session, ready["historical"].id)
    current_before = _version_snapshot(session, ready["current"].id)
    _patch_refresh(monkeypatch, [_payload(1104, ready["field"], version="tied-finals")])

    response = _post_rebuild(client, ready["imported"].id)

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["code"] == "schedule_version_ambiguous"
    assert "could not be determined safely" in detail["message"]
    assert "Desk schedule: none" in detail["message"]
    assert "Published schedule: none" in detail["message"]
    session.expire_all()
    assert _version_snapshot(session, ready["historical"].id) == historical_before
    assert _version_snapshot(session, ready["current"].id) == current_before


def test_lower_desk_draft_id_wins_over_a_newer_assigned_clone(client: TestClient, session: Session, monkeypatch):
    ready = _assigned_clone(client, session, 1105)
    assert ready["historical"].id < ready["current"].id
    _mark_desk_draft(session, ready["tournament"], ready["historical"])
    current_before = _version_snapshot(session, ready["current"].id)
    _patch_refresh(monkeypatch, [_payload(1105, _avoid_payload(ready["field"]), version="lower-id")])

    response = _post_rebuild(client, ready["imported"].id)

    assert response.status_code == 200, response.text
    session.expire_all()
    assert _version_snapshot(session, ready["current"].id) == current_before
    assert _r1_pairs_on_version(session, ready["event"].id, ready["historical"].id) == _canonical_r1_pairs(
        session, ready["event"].id
    )


def test_two_desk_drafts_are_ambiguous(client: TestClient, session: Session, monkeypatch):
    ready = _assigned_clone(client, session, 1106)
    ready["historical"].status = "draft"
    ready["historical"].notes = "Desk Draft"
    ready["current"].notes = "Desk Draft"
    session.add(ready["historical"])
    session.add(ready["current"])
    _point_public(session, ready["tournament"], ready["current"])
    historical_before = _version_snapshot(session, ready["historical"].id)
    current_before = _version_snapshot(session, ready["current"].id)
    _patch_refresh(monkeypatch, [_payload(1106, ready["field"], version="two-drafts")])

    response = _post_rebuild(client, ready["imported"].id)

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["code"] == "schedule_version_ambiguous"
    assert "could not be determined safely" in detail["message"]
    assert str(ready["historical"].id) in detail["message"]
    assert str(ready["current"].id) in detail["message"]
    session.expire_all()
    assert _version_snapshot(session, ready["historical"].id) == historical_before
    assert _version_snapshot(session, ready["current"].id) == current_before


def test_guarantee_and_match_codes_ignore_the_historical_version(client: TestClient, session: Session, monkeypatch):
    from app.routes.schedule import _clone_final_to_draft

    ready = _scheduled_brackets(client, session, 1107, draw="mixed", count=24, guarantee=4, stored_guarantee=None)
    historical = session.exec(
        select(ScheduleVersion).where(ScheduleVersion.tournament_id == ready["tournament"].id)
    ).one()
    historical.status = "final"
    session.add(historical)
    session.commit()
    current = _clone_final_to_draft(ready["tournament"].id, historical.id, session)
    session.expire_all()
    consolation = next(
        match
        for match in session.exec(select(Match).where(Match.schedule_version_id == historical.id)).all()
        if (match.match_code or "").endswith("B1_C2")
    )
    consolation.match_code = consolation.match_code.replace("B1_C2", "B1_C9")
    session.add(consolation)
    _mark_desk_draft(session, ready["tournament"], current)
    historical_before = _version_snapshot(session, historical.id)
    _patch_refresh(monkeypatch, [_payload(1107, ready["field"], version="historical-code")])

    response = _post_rebuild(client, ready["imported"].id)

    assert response.status_code == 200, response.text
    session.expire_all()
    assert _version_snapshot(session, historical.id) == historical_before
    assert session.get(Match, consolation.id).match_code.endswith("B1_C9")
    current_matches = list(session.exec(select(Match).where(Match.schedule_version_id == current.id)).all())
    assert len(current_matches) == 51
    assert not any((match.match_code or "").endswith("B1_C9") for match in current_matches)
    assert any((match.match_code or "").endswith("B1_C2") for match in current_matches)
    assert session.get(Event, ready["event"].id).guarantee_selected is None


def test_protected_play_ignores_historical_runtime_and_still_blocks_the_current_version(
    client: TestClient, session: Session, monkeypatch
):
    ready = _assigned_clone(client, session, 1108)
    _mark_desk_draft(session, ready["tournament"], ready["current"])
    historical_matches = list(
        session.exec(select(Match).where(Match.schedule_version_id == ready["historical"].id)).all()
    )
    started = next(match for match in historical_matches if match.match_type == "WF" and match.round_index == 1)
    started.started_at = datetime(2026, 11, 6, 11, 5)
    session.add(started)
    current_r1 = _wf_r1_matches(session, ready["event"].id, ready["current"].id)
    feeder = next(match for match in historical_matches if match.match_type == "WF" and match.round_index == 2)
    feeder.source_match_a_id = current_r1[0].id
    feeder.team_a_id = started.team_a_id
    session.add(feeder)
    session.commit()
    historical_before = _version_snapshot(session, ready["historical"].id)
    _patch_refresh(monkeypatch, [_payload(1108, _avoid_payload(ready["field"]), version="historical-runtime")])

    response = _post_rebuild(client, ready["imported"].id)

    assert response.status_code == 200, response.text
    session.expire_all()
    assert _version_snapshot(session, ready["historical"].id) == historical_before
    assert session.get(Match, started.id).started_at is not None
    current_r1 = _wf_r1_matches(session, ready["event"].id, ready["current"].id)
    current_r1[0].started_at = datetime(2026, 11, 6, 11, 5)
    session.add(current_r1[0])
    session.commit()
    current_before = _version_snapshot(session, ready["current"].id)
    _patch_refresh(monkeypatch, [_payload(1108, _avoid_payload(ready["field"]), version="current-runtime")])

    blocked = _post_rebuild(client, ready["imported"].id)

    assert blocked.status_code == 409
    detail = blocked.json()["detail"]
    assert detail["code"] == "protected_play"
    assert current_r1[0].id in detail["matchNumbers"]
    session.expire_all()
    assert _version_snapshot(session, ready["current"].id) == current_before
    assert _version_snapshot(session, ready["historical"].id) == historical_before
