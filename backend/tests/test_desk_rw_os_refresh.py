"""Desk check/apply uses the existing RW-OS refresh endpoint. Preview does not mutate play data."""

from datetime import date, datetime
from types import SimpleNamespace

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.models.event import Event
from app.models.match import Match
from app.models.team import Team
from app.models.team_avoid_edge import TeamAvoidEdge
from app.models.temporary_player_lookup import TemporaryPlayerLookup
from app.models.tournament import Tournament
from app.services.canonical_teams import SnapshotTeam
from tests.test_rw_os_roster_projection import (
    _approve,
    _assign_unplayed_wf_slot,
    _import_payload,
    _payload,
    _schedule_match,
    _teams_by_key,
    _torrie_nancy,
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
    assert any(item["code"] == "draw_slot_left_open" for item in warnings)
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
