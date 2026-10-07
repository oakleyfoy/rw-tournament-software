"""Desk check/apply uses the existing RW-OS refresh endpoint. Preview does not mutate play data."""

import json
from datetime import date, datetime
from types import SimpleNamespace

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.models.event import Event
from app.models.match import Match
from app.models.match_assignment import MatchAssignment
from app.models.schedule_version import ScheduleVersion
from app.models.team import Team
from app.models.team_avoid_edge import TeamAvoidEdge
from app.models.temporary_player_lookup import TemporaryPlayerLookup
from app.models.tournament import Tournament
from app.models.tournament_import import TournamentDrawPlan, TournamentImport
from app.services.canonical_teams import SnapshotTeam, sort_teams_for_planning
from app.services.rw_os_import import snapshot_hash
from tests.test_rw_os_roster_projection import (
    _approve,
    _assign_unplayed_wf_slot,
    _draw_participant_ids,
    _import_payload,
    _mixed_field,
    _payload,
    _schedule_match,
    _team,
    _teams_by_key,
    _torrie_nancy,
    _wf_r1_match,
    _womens_field,
)


def _patch_refresh(monkeypatch, payloads: list[dict]):
    calls = {"n": 0, "payloads": []}

    def refresh_event(self, tournament_id, previous=None):
        index = min(calls["n"], len(payloads) - 1)
        calls["n"] += 1
        calls["payloads"].append(payloads[index])
        return payloads[index]

    monkeypatch.setattr("app.services.rw_os_import.RwOsClient.refresh_event", refresh_event)
    return calls


def _place_remaining_round(
    session: Session,
    tournament_id: int,
    event: Event,
    anchor: Match,
    placed_ids: set[int],
) -> None:
    """The desk 'current' check requires every active team to occupy the draw when a draw exists."""
    remaining = [
        team
        for team in session.exec(select(Team).where(Team.event_id == event.id)).all()
        if team.id not in placed_ids and not team.is_defaulted
    ]
    remaining.sort(key=lambda team: (team.seed is None, team.seed or 0, team.id or 0))
    sequence = 2
    for index in range(0, len(remaining) - 1, 2):
        left = remaining[index]
        right = remaining[index + 1]
        session.add(
            Match(
                tournament_id=tournament_id,
                event_id=event.id,
                schedule_version_id=anchor.schedule_version_id,
                match_code=f"WF_R1_{sequence:02d}",
                match_type="WF",
                round_number=1,
                round_index=1,
                sequence_in_round=sequence,
                duration_minutes=60,
                team_a_id=left.id,
                team_b_id=right.id,
                placeholder_side_a=left.name,
                placeholder_side_b=right.name,
            )
        )
        sequence += 1
    session.commit()


def _ready(client: TestClient, session: Session, source_id: int):
    teams = _womens_field(8)
    imported = _import_payload(session, source_id, teams)
    _approve(client, imported.id, {"womens": "8"})
    session.expire_all()
    live = _teams_by_key(session, imported.tournament_id)
    withdrawn = live[teams[0].team_key]
    partner = live[teams[1].team_key]
    event = session.get(Event, withdrawn.event_id)
    match = _assign_unplayed_wf_slot(session, imported.tournament_id, event, withdrawn, partner)
    _place_remaining_round(session, imported.tournament_id, event, match, {withdrawn.id, partner.id})
    tournament = session.get(Tournament, imported.tournament_id)
    _schedule_match(session, tournament, match)
    session.expire_all()
    return SimpleNamespace(
        teams=teams,
        imported=session.get(type(imported), imported.id),
        withdrawn=session.get(Team, withdrawn.id),
        partner=session.get(Team, partner.id),
        event=session.get(Event, event.id),
        match=session.get(Match, match.id),
        tournament=session.get(Tournament, tournament.id),
    )


def _fingerprint(session: Session, tournament_id: int) -> dict:
    teams = session.exec(select(Team).join(Event).where(Event.tournament_id == tournament_id)).all()
    matches = session.exec(select(Match).where(Match.tournament_id == tournament_id)).all()
    towels = session.exec(
        select(TemporaryPlayerLookup).where(TemporaryPlayerLookup.tournament_id == tournament_id)
    ).all()
    return {
        "teams": sorted(
            (team.id, team.source_team_key, bool(team.is_defaulted), team.player1_cellphone, team.name)
            for team in teams
        ),
        "matches": sorted(
            (match.id, match.team_a_id, match.team_b_id, match.match_code, match.winner_team_id, match.runtime_status)
            for match in matches
        ),
        "towels": sorted((row.id, row.source_team_key, row.lineup_slot, row.towel_color) for row in towels),
    }


def _post_refresh(client: TestClient, import_id: int, *, apply: bool, extra: dict | None = None):
    body = {"apply": apply}
    if extra:
        body.update(extra)
    response = client.post(f"/api/rw-os/imports/{import_id}/refresh", json=body)
    assert response.status_code == 200, response.text
    return response.json()


def test_preview_with_no_changes_does_not_mutate_operational_data(client: TestClient, session: Session, monkeypatch):
    ready = _ready(client, session, 950)
    before = _fingerprint(session, ready.imported.tournament_id)
    _patch_refresh(monkeypatch, [_payload(950, ready.teams)])

    result = _post_refresh(client, ready.imported.id, apply=False)

    assert result["applied"] is False
    assert result["diff"]["changed"] is False
    assert result["rosterProjection"] is None
    session.expire_all()
    assert _fingerprint(session, ready.imported.tournament_id) == before


def test_preview_lists_new_team_withdrawal_and_field_changes_without_writing_them(
    client: TestClient, session: Session, monkeypatch
):
    ready = _ready(client, session, 951)
    before = _fingerprint(session, ready.imported.tournament_id)
    replacement = _torrie_nancy()
    survivor = SnapshotTeam.from_dict(ready.teams[1].to_dict())
    survivor.player1.cellphone = "9015552222"
    survivor.player1.name = "John Smith"
    survivor.player1.towel_color = "Pink"
    survivor.avoid_group = "C"
    refreshed = [survivor] + [SnapshotTeam.from_dict(team.to_dict()) for team in ready.teams[2:]]
    refreshed.append(replacement)
    _patch_refresh(monkeypatch, [_payload(951, refreshed, version="preview")])

    result = _post_refresh(client, ready.imported.id, apply=False)

    assert result["applied"] is False
    diff = result["diff"]
    assert diff["changed"] is True
    assert {team["teamKey"] for team in diff["addedTeams"]} == {replacement.team_key}
    assert diff["addedTeams"][0]["displayName"] == "Torrie / Nancy"
    assert {team["teamKey"] for team in diff["withdrawnTeams"]} == {ready.teams[0].team_key}
    assert any(change["field"] == "cellphone" and change["after"] == "9015552222" for change in diff["contactChanges"])
    assert any(change["field"] == "towel" and change["after"] == "Pink" for change in diff["towelChanges"])
    assert any(change["after"] == "C" for change in diff["avoidGroupChanges"])
    session.expire_all()
    assert _fingerprint(session, ready.imported.tournament_id) == before
    assert replacement.team_key not in _teams_by_key(session, ready.imported.tournament_id)


def test_apply_reconciles_against_a_fresh_snapshot_and_ignores_client_diff(
    client: TestClient, session: Session, monkeypatch
):
    ready = _ready(client, session, 952)
    replacement = _torrie_nancy()
    unchanged = _payload(952, ready.teams)
    refreshed = [SnapshotTeam.from_dict(team.to_dict()) for team in ready.teams[1:]]
    refreshed.append(replacement)
    latest = _payload(952, refreshed, version="latest")
    calls = _patch_refresh(monkeypatch, [unchanged, latest])

    preview = _post_refresh(client, ready.imported.id, apply=False)
    assert preview["diff"]["changed"] is False
    session.expire_all()
    assert ready.withdrawn.source_team_key in _teams_by_key(session, ready.imported.tournament_id)
    assert replacement.team_key not in _teams_by_key(session, ready.imported.tournament_id)

    applied = _post_refresh(
        client,
        ready.imported.id,
        apply=True,
        extra={"diff": {"addedTeams": [{"teamKey": "client-invented", "displayName": "Do Not Trust"}]}},
    )
    assert calls["n"] == 2
    assert applied["applied"] is True
    projection = applied["rosterProjection"]
    assert projection["created"]["teams"] == 1
    assert projection["reconciled"]["withdrawnTeams"] == 1
    assert projection["reconciled"]["drawSlotsReplaced"] == 1
    assert not any(item["code"] == "roster_reconciliation_blocked" for item in projection["conflicts"])
    assert not any(item["code"] == "draw_slot_left_open" for item in projection["warnings"])

    session.expire_all()
    after = _teams_by_key(session, ready.imported.tournament_id)
    assert "client-invented" not in after
    new_team = after[replacement.team_key]
    old = session.get(Team, ready.withdrawn.id)
    match = session.get(Match, ready.match.id)
    assert old.is_defaulted is True
    assert match.team_a_id == new_team.id
    assert match.team_b_id == ready.partner.id
    assert match.match_code == "WF_R1_01"
    assert match.id == ready.match.id

    towels = session.exec(
        select(TemporaryPlayerLookup).where(TemporaryPlayerLookup.tournament_id == ready.imported.tournament_id)
    ).all()
    colors = {(row.source_team_key, row.lineup_slot): row.towel_color for row in towels if row.source == "rwos-import"}
    assert colors[(replacement.team_key, 1)] == "Purple"
    assert colors[(replacement.team_key, 2)] == "Gold"
    assert all(row.source_team_key != old.source_team_key for row in towels)
    edges = session.exec(select(TeamAvoidEdge).where(TeamAvoidEdge.event_id == ready.event.id)).all()
    assert any(edge.team_id_a == new_team.id or edge.team_id_b == new_team.id for edge in edges)
    assert all(edge.team_id_a != old.id and edge.team_id_b != old.id for edge in edges)

    desk = client.get(f"/api/desk/tournaments/{ready.imported.tournament_id}/teams")
    assert new_team.id in {row["team_id"] for row in desk.json()}
    assert old.id not in {row["team_id"] for row in desk.json()}
    sms = client.post(
        f"/api/tournaments/{ready.imported.tournament_id}/sms/preview/event/{ready.event.id}",
        json={"message": "Roster check"},
    )
    assert sms.status_code == 200, sms.text
    sms_ids = {row["team_id"] for row in sms.json()["recipients"]}
    assert new_team.id in sms_ids
    assert old.id not in sms_ids

    again = _post_refresh(client, ready.imported.id, apply=True)
    assert again["rosterProjection"]["created"]["teams"] == 0
    assert again["rosterProjection"]["reconciled"]["withdrawnTeams"] == 0
    session.expire_all()
    assert list(_teams_by_key(session, ready.imported.tournament_id)).count(replacement.team_key) == 1


def test_apply_reports_protected_match_without_rewriting_it(client: TestClient, session: Session, monkeypatch):
    ready = _ready(client, session, 953)
    match = session.get(Match, ready.match.id)
    match.started_at = datetime.utcnow()
    match.runtime_status = "FINAL"
    match.score_json = {"display": "4-2"}
    match.winner_team_id = ready.withdrawn.id
    session.add(match)
    session.commit()
    replacement = _torrie_nancy()
    refreshed = [SnapshotTeam.from_dict(team.to_dict()) for team in ready.teams[1:]]
    refreshed.append(replacement)
    _patch_refresh(monkeypatch, [_payload(953, refreshed, version="protected")])

    applied = _post_refresh(client, ready.imported.id, apply=True)
    blocked = [
        item for item in applied["rosterProjection"]["conflicts"] if item["code"] == "roster_reconciliation_blocked"
    ]
    assert len(blocked) == 1
    assert "Torrie / Nancy" in blocked[0]["message"]
    assert ready.event.name in blocked[0]["message"]
    session.expire_all()
    match = session.get(Match, ready.match.id)
    old = session.get(Team, ready.withdrawn.id)
    assert match.team_a_id == old.id
    assert match.winner_team_id == old.id
    assert match.score_json == {"display": "4-2"}
    assert old.is_defaulted is False


def test_apply_warns_when_a_withdrawal_has_no_replacement(client: TestClient, session: Session, monkeypatch):
    ready = _ready(client, session, 954)
    refreshed = [SnapshotTeam.from_dict(team.to_dict()) for team in ready.teams[1:]]
    _patch_refresh(monkeypatch, [_payload(954, refreshed, version="withdraw-only")])

    applied = _post_refresh(client, ready.imported.id, apply=True)
    warnings = applied["rosterProjection"]["warnings"]
    open_slots = [item for item in warnings if item["code"] == "draw_slot_left_open"]
    assert len(open_slots) == 1
    assert "W1" in open_slots[0]["message"]
    assert "Seed " not in open_slots[0]["message"]
    assert "TBD" not in open_slots[0]["message"]
    session.expire_all()
    match = session.get(Match, ready.match.id)
    old = session.get(Team, ready.withdrawn.id)
    assert old.is_defaulted is True
    assert match.team_a_id is None
    assert match.team_b_id == ready.partner.id
    assert match.match_code == "WF_R1_01"


def test_apply_warns_when_a_new_team_has_no_open_draw_slot(client: TestClient, session: Session, monkeypatch):
    ready = _ready(client, session, 955)
    replacement = _torrie_nancy()
    refreshed = [SnapshotTeam.from_dict(team.to_dict()) for team in ready.teams]
    refreshed.append(replacement)
    _patch_refresh(monkeypatch, [_payload(955, refreshed, version="extra-team")])

    applied = _post_refresh(client, ready.imported.id, apply=True)
    conflicts = applied["rosterProjection"]["conflicts"]
    assert any(item["code"] == "roster_draw_placement_unresolved" for item in conflicts)
    session.expire_all()
    match = session.get(Match, ready.match.id)
    after = _teams_by_key(session, ready.imported.tournament_id)
    assert replacement.team_key in after
    assert match.team_a_id == ready.withdrawn.id
    assert match.team_b_id == ready.partner.id
    assert after[replacement.team_key].id not in {match.team_a_id, match.team_b_id}


def test_tournament_without_an_rw_os_import_has_no_linked_source(client: TestClient, session: Session):
    tournament = Tournament(
        name="Manual Desk",
        location="KC",
        timezone="America/Chicago",
        start_date=date(2026, 8, 23),
        end_date=date(2026, 8, 23),
    )
    session.add(tournament)
    session.commit()
    session.refresh(tournament)
    missing = client.get(f"/api/rw-os/tournaments/{tournament.id}/import")
    assert missing.status_code == 404

    ready = _ready(client, session, 956)
    linked = client.get(f"/api/tournaments/{ready.imported.tournament_id}")
    assert linked.status_code == 200
    assert linked.json()["rw_os_import_id"] == ready.imported.id
    assert linked.json()["source_rw_os_tournament_id"] == 956
    found = client.get(f"/api/rw-os/tournaments/{ready.imported.tournament_id}/import")
    assert found.status_code == 200
    assert found.json()["import"]["id"] == ready.imported.id


def _active_keys(session: Session, event_id: int) -> set[str]:
    return {
        team.source_team_key
        for team in session.exec(select(Team).where(Team.event_id == event_id)).all()
        if team.source_team_key and not team.is_defaulted
    }


def _mixed_draw(
    client: TestClient,
    session: Session,
    source_id: int,
    *,
    roster_count: int,
    placed_count: int,
) -> SimpleNamespace:
    """Approved Mixed roster with a 24-side draw. placed_count teams occupy entry sides."""
    field = _mixed_field(roster_count)
    imported = _import_payload(session, source_id, field)
    _approve(client, imported.id, {"mixed": str(roster_count)})
    session.expire_all()
    imported = session.get(TournamentImport, imported.id)
    event = session.exec(select(Event).where(Event.tournament_id == imported.tournament_id)).one()
    plan = session.exec(select(TournamentDrawPlan).where(TournamentDrawPlan.import_id == imported.id)).one()
    brackets = json.loads(plan.brackets_json)
    brackets[0]["size"] = 24
    brackets[0]["rankEnd"] = 24
    plan.brackets_json = json.dumps(brackets)
    event.team_count = 24
    event.draw_status = "generated"
    session.add(plan)
    session.add(event)
    session.commit()

    live = _teams_by_key(session, imported.tournament_id)
    ordered = sorted(live.values(), key=lambda team: (team.seed is None, team.seed or 0, team.id or 0))
    version = ScheduleVersion(tournament_id=imported.tournament_id, version_number=1, status="draft")
    session.add(version)
    session.commit()
    session.refresh(version)
    filled = []
    for index in range(placed_count // 2):
        filled.append(
            _wf_r1_match(
                session,
                tournament_id=imported.tournament_id,
                event=event,
                version=version,
                sequence=index + 1,
                team_a=ordered[index * 2],
                team_b=ordered[index * 2 + 1],
            )
        )
    open_matches = []
    for index in range(placed_count // 2, 12):
        open_matches.append(
            _wf_r1_match(
                session,
                tournament_id=imported.tournament_id,
                event=event,
                version=version,
                sequence=index + 1,
                team_a=None,
                team_b=None,
            )
        )
    return SimpleNamespace(
        field=field,
        imported=session.get(TournamentImport, imported.id),
        event=session.get(Event, event.id),
        ordered=ordered,
        filled=filled,
        open_matches=open_matches,
    )


def _store_snapshot(session: Session, imported: TournamentImport, source_id: int, teams: list[SnapshotTeam]) -> None:
    payload = _payload(source_id, teams)
    row = session.get(TournamentImport, imported.id)
    row.snapshot_json = json.dumps(payload["teams"])
    row.source_hash = snapshot_hash(payload)
    row.source_team_count = len(payload["teams"])
    row.source_version = payload["version"]
    session.add(row)
    session.commit()


def test_case_a_stale_draw_reconciles_on_check_without_a_new_rw_os_change(
    client: TestClient, session: Session, monkeypatch
):
    ready = _mixed_draw(client, session, 960, roster_count=24, placed_count=20)
    assert len(_active_keys(session, ready.event.id)) == 24
    assert len(_draw_participant_ids(session, ready.event.id)) == 20
    before_filled = {match.id: (match.team_a_id, match.team_b_id) for match in ready.filled}
    _patch_refresh(monkeypatch, [_payload(960, ready.field)])

    result = _post_refresh(client, ready.imported.id, apply=False)

    assert result["diff"]["changed"] is True
    assert result["diff"]["addedTeams"] == []
    assert result["diff"]["withdrawnTeams"] == []
    assert result["diff"]["operationalDrift"]["reconciliationNeeded"] is True
    assert len(result["diff"]["operationalDrift"]["missingFromDraw"]) == 4
    assert result["applied"] is True
    assert result["rosterProjection"]["created"]["teams"] == 0
    assert result["rosterProjection"]["reconciled"]["drawSlotsReplaced"] == 4
    session.expire_all()
    active = [team for team in _teams_by_key(session, ready.imported.tournament_id).values() if not team.is_defaulted]
    assert len(active) == 24
    assert _draw_participant_ids(session, ready.event.id) == {team.id for team in active}
    for match in ready.filled:
        session.refresh(match)
        assert (match.team_a_id, match.team_b_id) == before_filled[match.id]


def test_case_b_stale_event_and_draw_reconcile_on_check(client: TestClient, session: Session, monkeypatch):
    ready = _mixed_draw(client, session, 961, roster_count=20, placed_count=20)
    additions = _mixed_field(4, start_id=1900, start_rating=6.0)
    current = [SnapshotTeam.from_dict(team.to_dict()) for team in ready.field] + additions
    _store_snapshot(session, ready.imported, 961, current)
    assert len(_active_keys(session, ready.event.id)) == 20
    assert len(_draw_participant_ids(session, ready.event.id)) == 20
    _patch_refresh(monkeypatch, [_payload(961, current)])

    result = _post_refresh(client, ready.imported.id, apply=False)

    assert result["diff"]["changed"] is True
    assert result["diff"]["addedTeams"] == []
    assert result["applied"] is True
    assert result["rosterProjection"]["created"]["teams"] == 4
    assert result["rosterProjection"]["reconciled"]["drawSlotsReplaced"] == 4
    session.expire_all()
    active = [team for team in _teams_by_key(session, ready.imported.tournament_id).values() if not team.is_defaulted]
    assert len(active) == 24
    assert _draw_participant_ids(session, ready.event.id) == {team.id for team in active}
    desk = client.get(f"/api/desk/tournaments/{ready.imported.tournament_id}/teams")
    mixed = [row for row in desk.json() if row["event_id"] == ready.event.id]
    assert len(mixed) == 24


def test_case_c_withdrawn_team_still_in_the_draw_is_not_current(client: TestClient, session: Session, monkeypatch):
    ready = _mixed_draw(client, session, 962, roster_count=24, placed_count=24)
    withdrawn = ready.ordered[0]
    remaining = [
        SnapshotTeam.from_dict(team.to_dict()) for team in ready.field if team.team_key != withdrawn.source_team_key
    ]
    _store_snapshot(session, ready.imported, 962, remaining)
    _patch_refresh(monkeypatch, [_payload(962, remaining)])

    result = _post_refresh(client, ready.imported.id, apply=False)

    assert result["diff"]["changed"] is True
    assert result["diff"]["withdrawnTeams"] == []
    assert withdrawn.source_team_key in result["diff"]["operationalDrift"]["extraInDraw"]
    assert result["applied"] is True
    assert result["rosterProjection"]["reconciled"]["withdrawnTeams"] == 1
    session.expire_all()
    old = session.get(Team, withdrawn.id)
    assert old.is_defaulted is True
    assert old.id not in _draw_participant_ids(session, ready.event.id)
    desk = client.get(f"/api/desk/tournaments/{ready.imported.tournament_id}/teams")
    assert old.id not in {row["team_id"] for row in desk.json()}


def test_case_c_protected_withdrawal_returns_a_conflict_instead_of_current(
    client: TestClient, session: Session, monkeypatch
):
    ready = _mixed_draw(client, session, 963, roster_count=24, placed_count=24)
    withdrawn = ready.ordered[0]
    match = next(item for item in ready.filled if item.team_a_id == withdrawn.id or item.team_b_id == withdrawn.id)
    match.started_at = datetime.utcnow()
    match.runtime_status = "FINAL"
    match.score_json = {"display": "4-2"}
    match.winner_team_id = withdrawn.id
    session.add(match)
    session.commit()
    remaining = [
        SnapshotTeam.from_dict(team.to_dict()) for team in ready.field if team.team_key != withdrawn.source_team_key
    ]
    _store_snapshot(session, ready.imported, 963, remaining)
    _patch_refresh(monkeypatch, [_payload(963, remaining)])

    result = _post_refresh(client, ready.imported.id, apply=False)

    assert result["diff"]["changed"] is True
    assert result["applied"] is True
    blocked = [
        item for item in result["rosterProjection"]["conflicts"] if item["code"] == "roster_reconciliation_blocked"
    ]
    assert len(blocked) == 1
    session.expire_all()
    old = session.get(Team, withdrawn.id)
    saved = session.get(Match, match.id)
    assert old.is_defaulted is False
    assert saved.winner_team_id == old.id
    assert saved.score_json == {"display": "4-2"}


def test_case_d_fully_reconciled_roster_is_current_and_does_not_write(
    client: TestClient, session: Session, monkeypatch
):
    ready = _mixed_draw(client, session, 964, roster_count=24, placed_count=24)
    before = _fingerprint(session, ready.imported.tournament_id)
    _patch_refresh(monkeypatch, [_payload(964, ready.field)])

    result = _post_refresh(client, ready.imported.id, apply=False)

    assert result["diff"]["changed"] is False
    assert result["diff"]["operationalDrift"]["reconciliationNeeded"] is False
    assert result["applied"] is False
    assert result["rosterProjection"] is None
    session.expire_all()
    assert _fingerprint(session, ready.imported.tournament_id) == before


def test_case_e_second_check_after_reconciliation_is_a_noop(client: TestClient, session: Session, monkeypatch):
    ready = _mixed_draw(client, session, 965, roster_count=24, placed_count=20)
    _patch_refresh(monkeypatch, [_payload(965, ready.field)])

    first = _post_refresh(client, ready.imported.id, apply=False)
    assert first["applied"] is True
    assert first["rosterProjection"]["reconciled"]["drawSlotsReplaced"] == 4
    session.expire_all()
    after = _fingerprint(session, ready.imported.tournament_id)
    participants = _draw_participant_ids(session, ready.event.id)
    assert len(participants) == 24

    second = _post_refresh(client, ready.imported.id, apply=False)

    assert second["diff"]["changed"] is False
    assert second["applied"] is False
    assert second["rosterProjection"] is None
    session.expire_all()
    assert _fingerprint(session, ready.imported.tournament_id) == after
    assert _draw_participant_ids(session, ready.event.id) == participants
    assert len(_teams_by_key(session, ready.imported.tournament_id)) == 24


def _generate_wf24_draw(session: Session, event: Event, placed: list[Team]) -> list[Match]:
    """Canonical 24-team Mixed waterfall: 12 entry matches, then winner/loser feeders."""
    from app.services.draw_plan_engine import DrawPlanSpec, _generate_wf_to_brackets_8

    event.team_count = 24
    event.guarantee_selected = event.guarantee_selected or 5
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
        division="Mixed",
        team_count=24,
        template_type="WF_TO_BRACKETS_8",
        template_key="WF_TO_BRACKETS_8",
        guarantee=5,
        waterfall_rounds=2,
        waterfall_minutes=60,
        standard_minutes=105,
        tournament_id=event.tournament_id,
        event_category=category,
    )
    session._allow_match_generation = True
    matches, _warnings = _generate_wf_to_brackets_8(session, version.id, spec, [team.id for team in placed])
    session.add_all(matches)
    session.commit()
    return matches


def _set_rank_end(session: Session, import_id: int, rank_end: int) -> None:
    plan = session.exec(select(TournamentDrawPlan).where(TournamentDrawPlan.import_id == import_id)).one()
    brackets = json.loads(plan.brackets_json)
    brackets[0]["size"] = rank_end
    brackets[0]["rankEnd"] = rank_end
    plan.brackets_json = json.dumps(brackets)
    session.add(plan)
    session.commit()


def _incomplete(result: dict) -> list[dict]:
    return [
        item for item in result["rosterProjection"]["conflicts"] if item["code"] == "roster_reconciliation_incomplete"
    ]


def test_real_wf24_draw_materializes_four_missing_teams(client: TestClient, session: Session, monkeypatch):
    """Production draw shape: WF R1 uses Seed N sides, later rounds are feeders. Snapshot has 24, rows have 20."""
    field = _mixed_field(24)
    present = field[:20]
    missing = field[20:]
    imported = _import_payload(session, 970, present)
    _approve(client, imported.id, {"mixed": "20"})
    session.expire_all()
    imported = session.get(TournamentImport, imported.id)
    event = session.exec(select(Event).where(Event.tournament_id == imported.tournament_id)).one()
    _set_rank_end(session, imported.id, 24)
    ordered = sorted(
        _teams_by_key(session, imported.tournament_id).values(),
        key=lambda team: (team.seed is None, team.seed or 0, team.id or 0),
    )
    matches = _generate_wf24_draw(session, event, ordered)
    r1 = [match for match in matches if match.match_type == "WF" and (match.round_index or 0) == 1]
    empty = []
    for match in r1:
        if match.team_a_id is None:
            empty.append(match.placeholder_side_a)
        if match.team_b_id is None:
            empty.append(match.placeholder_side_b)
    assert empty == ["Seed 21", "Seed 22", "Seed 23", "Seed 24"]
    assert any(match.source_match_a_id is not None for match in matches)
    assert len(_draw_participant_ids(session, event.id)) == 20
    _store_snapshot(session, imported, 970, field)
    _patch_refresh(monkeypatch, [_payload(970, field)])

    result = _post_refresh(client, imported.id, apply=False)

    assert result["applied"] is True
    assert result["rosterProjection"]["created"]["teams"] == 4
    assert result["rosterProjection"]["reconciled"]["drawSlotsReplaced"] == 4
    assert result["rosterProjection"]["updated"]["towelRows"] == 0
    assert result["rosterProjection"]["updated"]["contactFields"] == 0
    assert _incomplete(result) == []
    session.expire_all()
    active = [team for team in _teams_by_key(session, imported.tournament_id).values() if not team.is_defaulted]
    assert len(active) == 24
    assert {team.source_team_key for team in active} >= {team.team_key for team in missing}
    assert _draw_participant_ids(session, event.id) == {team.id for team in active}
    desk = client.get(f"/api/desk/tournaments/{imported.tournament_id}/teams")
    assert len([row for row in desk.json() if row["event_id"] == event.id]) == 24

    again = _post_refresh(client, imported.id, apply=False)
    assert again["diff"]["changed"] is False
    assert again["applied"] is False
    assert again["rosterProjection"] is None


def test_defaulted_teams_outside_rank_are_reactivated_into_wf24_seed_sides(
    client: TestClient, session: Session, monkeypatch
):
    field = _mixed_field(24)
    imported = _import_payload(session, 971, field)
    _approve(client, imported.id, {"mixed": "24"})
    session.expire_all()
    imported = session.get(TournamentImport, imported.id)
    event = session.exec(select(Event).where(Event.tournament_id == imported.tournament_id)).one()
    live = _teams_by_key(session, imported.tournament_id)
    ordered = sorted(live.values(), key=lambda team: (team.seed is None, team.seed or 0, team.id or 0))
    hidden = ordered[20:]
    for team in hidden:
        team.is_defaulted = True
        team.seed = None
        session.add(team)
    session.commit()
    _set_rank_end(session, imported.id, 20)
    matches = _generate_wf24_draw(session, event, ordered[:20])
    r1_empty = [
        match.placeholder_side_a
        for match in matches
        if match.match_type == "WF" and (match.round_index or 0) == 1 and match.team_a_id is None
    ]
    r1_empty += [
        match.placeholder_side_b
        for match in matches
        if match.match_type == "WF" and (match.round_index or 0) == 1 and match.team_b_id is None
    ]
    assert r1_empty == ["Seed 21", "Seed 22", "Seed 23", "Seed 24"]
    assert len(_active_keys(session, event.id)) == 20
    _patch_refresh(monkeypatch, [_payload(971, field)])

    result = _post_refresh(client, imported.id, apply=False)

    assert result["rosterProjection"]["created"]["teams"] == 0
    assert result["rosterProjection"]["reconciled"]["drawSlotsReplaced"] == 4
    assert _incomplete(result) == []
    session.expire_all()
    active = [team for team in _teams_by_key(session, imported.tournament_id).values() if not team.is_defaulted]
    assert len(active) == 24
    assert {team.source_team_key for team in hidden} <= {team.source_team_key for team in active}
    assert _draw_participant_ids(session, event.id) == {team.id for team in active}


def test_active_unplaced_teams_fill_real_wf24_seed_sides(client: TestClient, session: Session, monkeypatch):
    field = _mixed_field(24)
    imported = _import_payload(session, 972, field)
    _approve(client, imported.id, {"mixed": "24"})
    session.expire_all()
    imported = session.get(TournamentImport, imported.id)
    event = session.exec(select(Event).where(Event.tournament_id == imported.tournament_id)).one()
    ordered = sorted(
        _teams_by_key(session, imported.tournament_id).values(),
        key=lambda team: (team.seed is None, team.seed or 0, team.id or 0),
    )
    for team in ordered[20:]:
        team.seed = None
        session.add(team)
    session.commit()
    _generate_wf24_draw(session, event, ordered[:20])
    assert len(_active_keys(session, event.id)) == 24
    assert len(_draw_participant_ids(session, event.id)) == 20
    _patch_refresh(monkeypatch, [_payload(972, field)])

    result = _post_refresh(client, imported.id, apply=False)

    assert result["rosterProjection"]["created"]["teams"] == 0
    assert result["rosterProjection"]["reconciled"]["drawSlotsReplaced"] == 4
    assert _incomplete(result) == []
    session.expire_all()
    active = [team for team in _teams_by_key(session, imported.tournament_id).values() if not team.is_defaulted]
    assert _draw_participant_ids(session, event.id) == {team.id for team in active}


def test_full_wf24_draw_without_open_sides_does_not_claim_success(client: TestClient, session: Session, monkeypatch):
    field = _mixed_field(24)
    present = field[:20]
    imported = _import_payload(session, 973, present)
    _approve(client, imported.id, {"mixed": "20"})
    session.expire_all()
    imported = session.get(TournamentImport, imported.id)
    event = session.exec(select(Event).where(Event.tournament_id == imported.tournament_id)).one()
    ordered = sorted(
        _teams_by_key(session, imported.tournament_id).values(),
        key=lambda team: (team.seed is None, team.seed or 0, team.id or 0),
    )
    version = ScheduleVersion(tournament_id=imported.tournament_id, version_number=1, status="draft")
    session.add(version)
    session.commit()
    session.refresh(version)
    for index in range(10):
        _wf_r1_match(
            session,
            tournament_id=imported.tournament_id,
            event=event,
            version=version,
            sequence=index + 1,
            team_a=ordered[index],
            team_b=ordered[index + 10],
        )
    _store_snapshot(session, imported, 973, field)
    assert len(_draw_participant_ids(session, event.id)) == 20
    _patch_refresh(monkeypatch, [_payload(973, field)])

    result = _post_refresh(client, imported.id, apply=False)

    failed = _incomplete(result)
    assert len(failed) == 1
    assert failed[0]["stage"] == "draw"
    assert "Draw could not be reconciled" in failed[0]["message"]
    assert "Tournament teams: 24" in failed[0]["message"]
    assert "Draw participants: 20" in failed[0]["message"]
    assert "M21" in failed[0]["message"]
    assert "Event roster could not be reconciled" not in failed[0]["message"]
    session.expire_all()
    active = [team for team in _teams_by_key(session, imported.tournament_id).values() if not team.is_defaulted]
    assert len(active) == 24
    assert len(_draw_participant_ids(session, event.id)) == 20


PRODUCTION_MIXED = (
    ("12884/15825", "Lauri / Marc"),
    ("15875/15876", "Amy / Andre"),
    ("13511/14084", "Darlene / Tony"),
    ("14380/15874", "Min / Steven"),
    ("15691/15692", "Geoff / Ana"),
)


def _production_mixed_field() -> list[SnapshotTeam]:
    field = _mixed_field(19)
    for index, (key, display) in enumerate(PRODUCTION_MIXED):
        field.append(_team(key, round(1.0 - index * 0.01, 4), draw="mixed", display=display, full=display))
    return field


def _empty_entry_labels(matches: list[Match]) -> list[str]:
    labels: list[str] = []
    for match in matches:
        if (match.match_type or "").upper() != "WF" or (match.round_index or 0) != 1:
            continue
        if match.team_a_id is None:
            labels.append(match.placeholder_side_a or "")
        if match.team_b_id is None:
            labels.append(match.placeholder_side_b or "")
    return labels


def _production_nineteen_draw(
    client: TestClient,
    session: Session,
    source_id: int,
    *,
    reverse_keys: bool = False,
) -> SimpleNamespace:
    """24-team Mixed structure, stale rank 1–19, event renamed off the bracket label, five identities absent.

    The stored plan still says Mixed A ranks 1–19. The only Mixed event is named Mixed and already
    has a 24-side waterfall. The five production keys are not active rows.
    """
    field = _production_mixed_field()
    imported = _import_payload(session, source_id, field)
    _approve(client, imported.id, {"mixed": "24"})
    session.expire_all()
    imported = session.get(TournamentImport, imported.id)
    event = session.exec(select(Event).where(Event.tournament_id == imported.tournament_id)).one()
    assert event.name == "Mixed A"
    live = _teams_by_key(session, imported.tournament_id)
    for key, _display in PRODUCTION_MIXED:
        team = live[key]
        if reverse_keys:
            left, right = key.split("/")
            team.source_team_key = f"{right}/{left}"
        else:
            team.source_team_key = f"stale-{key}"
        team.is_defaulted = True
        team.seed = None
        session.add(team)
    session.commit()
    _set_rank_end(session, imported.id, 19)
    present = [
        team for team in session.exec(select(Team).where(Team.event_id == event.id)).all() if not team.is_defaulted
    ]
    present.sort(key=lambda team: (team.seed is None, team.seed or 0, team.id or 0))
    matches = _generate_wf24_draw(session, event, present)
    event = session.get(Event, event.id)
    event.name = "Mixed"
    session.add(event)
    session.commit()
    return SimpleNamespace(
        field=field,
        imported=session.get(TournamentImport, imported.id),
        event=session.get(Event, event.id),
        matches=matches,
    )


def test_production_mixed_identities_reconcile_onto_the_24_team_event(
    client: TestClient, session: Session, monkeypatch
):
    ready = _production_nineteen_draw(client, session, 980)
    empty = _empty_entry_labels(ready.matches)
    assert sorted(empty) == ["Seed 20", "Seed 21", "Seed 22", "Seed 23", "Seed 24"]
    assert len(_active_keys(session, ready.event.id)) == 19
    assert len(_draw_participant_ids(session, ready.event.id)) == 19
    _patch_refresh(monkeypatch, [_payload(980, ready.field)])

    result = _post_refresh(client, ready.imported.id, apply=False)

    projection = result["rosterProjection"]
    assert projection["created"]["teams"] == 5
    assert projection["reconciled"]["withdrawnTeams"] == 0
    assert projection["reconciled"]["drawSlotsReplaced"] == 5
    assert _incomplete(result) == []
    session.expire_all()
    active = [team for team in _teams_by_key(session, ready.imported.tournament_id).values() if not team.is_defaulted]
    assert {key for key, _display in PRODUCTION_MIXED} <= {team.source_team_key for team in active}
    assert len([team for team in active if team.event_id == ready.event.id]) == 24
    expected_seeds = {team.team_key: index for index, team in enumerate(sort_teams_for_planning(ready.field), start=1)}
    assert {team.seed for team in active if team.event_id == ready.event.id} == set(range(1, 25))
    assert _teams_by_key(session, ready.imported.tournament_id)["13511/14084"].seed == expected_seeds["13511/14084"]
    assert _draw_participant_ids(session, ready.event.id) == {
        team.id for team in active if team.event_id == ready.event.id
    }
    assert _empty_entry_labels(session.exec(select(Match).where(Match.event_id == ready.event.id)).all()) == []

    again = _post_refresh(client, ready.imported.id, apply=False)
    assert again["diff"]["changed"] is False
    assert again["applied"] is False
    assert again["rosterProjection"] is None


def test_production_mixed_identities_match_when_partner_order_is_reversed(
    client: TestClient, session: Session, monkeypatch
):
    ready = _production_nineteen_draw(client, session, 981, reverse_keys=True)
    assert len(_active_keys(session, ready.event.id)) == 19
    _patch_refresh(monkeypatch, [_payload(981, ready.field)])

    result = _post_refresh(client, ready.imported.id, apply=False)

    projection = result["rosterProjection"]
    assert projection["created"]["teams"] == 0
    assert projection["reconciled"]["drawSlotsReplaced"] == 5
    assert _incomplete(result) == []
    session.expire_all()
    live = _teams_by_key(session, ready.imported.tournament_id)
    for key, _display in PRODUCTION_MIXED:
        left, right = key.split("/")
        assert key in live
        assert f"{right}/{left}" not in live
        assert live[key].is_defaulted is False
        assert live[key].event_id == ready.event.id
    active = [team for team in live.values() if not team.is_defaulted and team.event_id == ready.event.id]
    assert len(active) == 24
    assert _draw_participant_ids(session, ready.event.id) == {team.id for team in active}


def test_production_mixed_event_stays_complete_when_entry_sides_are_protected(
    client: TestClient, session: Session, monkeypatch
):
    ready = _production_nineteen_draw(client, session, 982)
    for match in ready.matches:
        if (match.match_type or "").upper() != "WF" or (match.round_index or 0) != 1:
            continue
        if match.team_a_id is None or match.team_b_id is None:
            match.runtime_status = "FINAL"
            match.started_at = datetime.utcnow()
            session.add(match)
    session.commit()
    _patch_refresh(monkeypatch, [_payload(982, ready.field)])

    result = _post_refresh(client, ready.imported.id, apply=False)

    assert result["rosterProjection"]["created"]["teams"] == 5
    assert result["rosterProjection"]["reconciled"]["drawSlotsReplaced"] == 0
    failed = _incomplete(result)
    assert len(failed) == 1
    assert failed[0]["stage"] == "draw"
    assert "Draw could not be reconciled" in failed[0]["message"]
    assert "Tournament teams: 24" in failed[0]["message"]
    assert "Draw participants: 19" in failed[0]["message"]
    assert "Event roster could not be reconciled" not in failed[0]["message"]
    for _key, display in PRODUCTION_MIXED:
        assert display in failed[0]["message"]
    session.expire_all()
    active = [
        team
        for team in _teams_by_key(session, ready.imported.tournament_id).values()
        if not team.is_defaulted and team.event_id == ready.event.id
    ]
    assert len(active) == 24
    assert len(_draw_participant_ids(session, ready.event.id)) == 19


def _match_sides(session: Session, event_id: int) -> list[tuple]:
    matches = session.exec(select(Match).where(Match.event_id == event_id)).all()
    return sorted(
        (
            match.id,
            match.match_code,
            match.team_a_id,
            match.team_b_id,
            match.placeholder_side_a,
            match.placeholder_side_b,
        )
        for match in matches
    )


def _assignment_ids(session: Session, tournament_id: int) -> list[int]:
    rows = session.exec(select(MatchAssignment).join(Match).where(Match.tournament_id == tournament_id)).all()
    return sorted(row.id for row in rows if row.id is not None)


def _full_mixed_draw(client: TestClient, session: Session, source_id: int) -> SimpleNamespace:
    field = _production_mixed_field()
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
    return SimpleNamespace(
        field=field,
        imported=session.get(TournamentImport, imported.id),
        event=session.get(Event, event.id),
    )


def test_refresh_repairs_darlene_seed_without_moving_the_draw(client: TestClient, session: Session, monkeypatch):
    ready = _full_mixed_draw(client, session, 983)
    live = _teams_by_key(session, ready.imported.tournament_id)
    darlene = live["13511/14084"]
    others = sorted(
        (team for team in live.values() if team.id != darlene.id and not team.is_defaulted),
        key=lambda team: team.id or 0,
    )
    stale = list(range(1, 13)) + list(range(14, 25))
    for team in list(others) + [darlene]:
        team.seed = None
        session.add(team)
    session.commit()
    for team, seed in zip(others, stale):
        team.seed = seed
        session.add(team)
    session.commit()
    expected = {team.team_key: index for index, team in enumerate(sort_teams_for_planning(ready.field), start=1)}
    assert expected["13511/14084"] != 13
    before_sides = _match_sides(session, ready.event.id)
    before_assignments = _assignment_ids(session, ready.imported.tournament_id)
    _patch_refresh(monkeypatch, [_payload(983, ready.field)])

    result = _post_refresh(client, ready.imported.id, apply=False)

    projection = result["rosterProjection"]
    assert projection["created"]["teams"] == 0
    assert projection["reconciled"]["withdrawnTeams"] == 0
    assert projection["reconciled"]["drawSlotsReplaced"] == 0
    assert projection["updated"]["seeds"] >= 1
    assert _incomplete(result) == []
    session.expire_all()
    repaired = _teams_by_key(session, ready.imported.tournament_id)
    assert repaired["13511/14084"].seed == expected["13511/14084"]
    active = [team for team in repaired.values() if not team.is_defaulted]
    assert {team.seed for team in active} == set(range(1, 25))
    assert {team.source_team_key: team.seed for team in active} == expected
    assert _match_sides(session, ready.event.id) == before_sides
    assert _assignment_ids(session, ready.imported.tournament_id) == before_assignments

    again = _post_refresh(client, ready.imported.id, apply=False)
    assert again["diff"]["changed"] is False
    assert again["applied"] is False
    assert again["rosterProjection"] is None


def test_refresh_reorders_seeds_without_moving_draw_positions(client: TestClient, session: Session, monkeypatch):
    ready = _full_mixed_draw(client, session, 984)
    active = [team for team in _teams_by_key(session, ready.imported.tournament_id).values() if not team.is_defaulted]
    by_seed = sorted(active, key=lambda team: (team.seed is None, team.seed or 0, team.id or 0))
    for team in by_seed:
        team.seed = None
        session.add(team)
    session.commit()
    for team, seed in zip(by_seed, range(len(by_seed), 0, -1)):
        team.seed = seed
        session.add(team)
    session.commit()
    before_sides = _match_sides(session, ready.event.id)
    _patch_refresh(monkeypatch, [_payload(984, ready.field)])

    result = _post_refresh(client, ready.imported.id, apply=False)

    assert result["rosterProjection"]["created"]["teams"] == 0
    assert result["rosterProjection"]["reconciled"]["drawSlotsReplaced"] == 0
    assert result["rosterProjection"]["updated"]["seeds"] == 24
    expected = {team.team_key: index for index, team in enumerate(sort_teams_for_planning(ready.field), start=1)}
    session.expire_all()
    repaired = [team for team in _teams_by_key(session, ready.imported.tournament_id).values() if not team.is_defaulted]
    assert {team.source_team_key: team.seed for team in repaired} == expected
    assert _match_sides(session, ready.event.id) == before_sides

    again = _post_refresh(client, ready.imported.id, apply=False)
    assert again["diff"]["changed"] is False
    assert again["rosterProjection"] is None


def test_structural_placeholders_are_not_withdrawal_warnings(client: TestClient, session: Session, monkeypatch):
    ready = _ready(client, session, 985)
    for sequence, left, right in (
        (40, "Seed 23", "Seed 24"),
        (41, "TBD", "W(R1_01)"),
        (42, "WFSEED:01", "L(R1_02)"),
    ):
        session.add(
            Match(
                tournament_id=ready.imported.tournament_id,
                event_id=ready.event.id,
                schedule_version_id=ready.match.schedule_version_id,
                match_code=f"WF_R1_{sequence:02d}",
                match_type="WF",
                round_number=1,
                round_index=1,
                sequence_in_round=sequence,
                duration_minutes=60,
                placeholder_side_a=left,
                placeholder_side_b=right,
            )
        )
    session.commit()
    replacement = _torrie_nancy()
    refreshed = [SnapshotTeam.from_dict(team.to_dict()) for team in ready.teams[1:]]
    refreshed.append(replacement)
    _store_snapshot(session, ready.imported, 985, refreshed)
    _patch_refresh(monkeypatch, [_payload(985, refreshed)])

    result = _post_refresh(client, ready.imported.id, apply=False)

    warnings = result["rosterProjection"]["warnings"]
    messages = " ".join(item["message"] for item in warnings)
    assert not any(item["code"] == "draw_slot_left_open" for item in warnings)
    for label in ("Seed 23", "Seed 24", "TBD", "WFSEED:", "W(", "L("):
        assert label not in messages
    session.expire_all()
    match = session.get(Match, ready.match.id)
    assert match.team_a_id == _teams_by_key(session, ready.imported.tournament_id)[replacement.team_key].id
    assert match.match_code == "WF_R1_01"
