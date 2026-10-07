"""Pairwise Who Knows Who — RW-OS graph fidelity through Tournament Software."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.models.event import Event
from app.models.match import Match
from app.models.team import Team
from app.models.team_avoid_edge import TeamAvoidEdge
from app.models.tournament_import import TournamentImport
from app.services.canonical_teams import SnapshotTeam
from app.services.rw_os_import import persist_snapshot, snapshot_hash
from app.services.rw_os_wkw import RW_OS_WKW_REASON, canonicalize_who_knows_who_connections
from app.services.wf_pairing import TeamSeed, build_wf_r1_pairings
from tests.test_desk_rw_os_refresh import _generate_wf24_draw, _patch_refresh
from tests.test_rw_os_roster_projection import (
    _approve,
    _mixed_field,
    _payload,
    _team,
    _teams_by_key,
)

# Shared cross-repo contract fixture (matches RW-OS whoKnowsWhoConnections export shape).
CROSS_REPO_WKW_CONTRACT = {
    "whoKnowsWhoConnections": [
        {"drawKind": "mixed", "teamAKey": "1/2", "teamBKey": "3/4"},
        {"drawKind": "mixed", "teamAKey": "1/2", "teamBKey": "5/6"},
    ]
}


def _connections_for_keys(pairs: list[tuple[str, str]], draw_kind: str = "mixed") -> list[dict]:
    rows = [{"drawKind": draw_kind, "teamAKey": a, "teamBKey": b} for a, b in pairs]
    return [edge.to_dict() for edge in canonicalize_who_knows_who_connections(rows)]


def _payload_with_wkw(
    source_id: int,
    teams: list[SnapshotTeam],
    connections: list[dict],
    *,
    version: str = "1",
) -> dict:
    payload = _payload(source_id, teams, version=version)
    payload["whoKnowsWhoConnections"] = connections
    return payload


def test_cross_repo_contract_field_names():
    parsed = canonicalize_who_knows_who_connections(CROSS_REPO_WKW_CONTRACT["whoKnowsWhoConnections"])
    assert [edge.to_dict() for edge in parsed] == CROSS_REPO_WKW_CONTRACT["whoKnowsWhoConnections"]


def test_critical_graph_is_not_a_clique(client: TestClient, session: Session):
    """A-B and A-C exist; B-C must not exist anywhere in the chain."""
    teams = [
        _team("1/2", 9.0, draw="mixed", display="A"),
        _team("3/4", 8.9, draw="mixed", display="B"),
        _team("5/6", 8.8, draw="mixed", display="C"),
        *[_team(f"{100 + i}/{200 + i}", 8.0 - i * 0.01, draw="mixed", display=f"T{i}") for i in range(5)],
    ]
    # Pad to 8 for approve structure.
    while len(teams) < 8:
        i = len(teams)
        teams.append(_team(f"{300 + i}/{400 + i}", 7.5 - i * 0.01, draw="mixed", display=f"P{i}"))
    connections = _connections_for_keys([("1/2", "3/4"), ("1/2", "5/6")])
    assert not any(row["teamAKey"] == "3/4" and row["teamBKey"] == "5/6" for row in connections)

    imported = persist_snapshot(session, _payload_with_wkw(9501, teams, connections))
    stored = json.loads(session.get(TournamentImport, imported.id).snapshot_json)
    assert stored["whoKnowsWhoConnections"] == connections

    _approve(client, imported.id, {"mixed": "8"})
    event = session.exec(select(Event).where(Event.tournament_id == imported.tournament_id)).first()
    edges = session.exec(
        select(TeamAvoidEdge).where(
            TeamAvoidEdge.event_id == event.id,
            TeamAvoidEdge.reason == RW_OS_WKW_REASON,
        )
    ).all()
    live = _teams_by_key(session, imported.tournament_id)
    a, b, c = live["1/2"].id, live["3/4"].id, live["5/6"].id
    pairs = {(min(e.team_id_a, e.team_id_b), max(e.team_id_a, e.team_id_b)) for e in edges}
    assert pairs == {(min(a, b), max(a, b)), (min(a, c), max(a, c))}
    assert (min(b, c), max(b, c)) not in pairs

    avoid = pairs
    seeds = [
        TeamSeed(seed=i + 1, team_id=tid, rating=9.0 - i * 0.1)
        for i, tid in enumerate(
            [
                a,
                b,
                c,
                live[teams[3].team_key].id,
                live[teams[4].team_key].id,
                live[teams[5].team_key].id,
                live[teams[6].team_key].id,
                live[teams[7].team_key].id,
            ]
        )
    ]
    # Direct conflict checks used by the generator.
    from app.services.wf_pairing import _pair_conflict_label

    assert _pair_conflict_label(seeds[0], seeds[1], avoid) == "wkw"
    assert _pair_conflict_label(seeds[0], seeds[2], avoid) == "wkw"
    assert _pair_conflict_label(seeds[1], seeds[2], avoid) is None


def test_reciprocal_claims_dedupe_to_one_edge(client: TestClient, session: Session):
    teams = _mixed_field(8)
    a_key, b_key = teams[0].team_key, teams[1].team_key
    # Payload already canonical; reciprocal order must still store one edge.
    connections = [
        {"drawKind": "mixed", "teamAKey": b_key, "teamBKey": a_key},
        {"drawKind": "mixed", "teamAKey": a_key, "teamBKey": b_key},
    ]
    imported = persist_snapshot(session, _payload_with_wkw(9502, teams, connections))
    stored = json.loads(session.get(TournamentImport, imported.id).snapshot_json)["whoKnowsWhoConnections"]
    assert len(stored) == 1
    _approve(client, imported.id, {"mixed": "8"})
    event = session.exec(select(Event).where(Event.tournament_id == imported.tournament_id)).first()
    edges = session.exec(
        select(TeamAvoidEdge).where(TeamAvoidEdge.event_id == event.id, TeamAvoidEdge.reason == RW_OS_WKW_REASON)
    ).all()
    assert len(edges) == 1


def test_removal_on_refresh_keeps_draw(client: TestClient, session: Session, monkeypatch):
    teams = _mixed_field(24)
    a_key, b_key = teams[0].team_key, teams[1].team_key
    connections = _connections_for_keys([(a_key, b_key)])
    imported = persist_snapshot(session, _payload_with_wkw(9503, teams, connections))
    _approve(client, imported.id, {"mixed": "24"})
    tournament_id = imported.tournament_id
    event = session.exec(select(Event).where(Event.tournament_id == tournament_id)).first()
    placed = sorted(
        _teams_by_key(session, tournament_id).values(),
        key=lambda team: (team.seed is None, team.seed or 0, team.id or 0),
    )
    _generate_wf24_draw(session, event, placed)
    before_matches = {
        m.id: (m.team_a_id, m.team_b_id, m.match_code)
        for m in session.exec(select(Match).where(Match.event_id == event.id)).all()
    }
    edges_before = session.exec(
        select(TeamAvoidEdge).where(TeamAvoidEdge.event_id == event.id, TeamAvoidEdge.reason == RW_OS_WKW_REASON)
    ).all()
    assert len(edges_before) == 1

    empty_payload = _payload_with_wkw(9503, teams, [], version="2")
    _patch_refresh(monkeypatch, [empty_payload])
    resp = client.post(f"/api/rw-os/imports/{imported.id}/refresh", json={"apply": True})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    wkw = (body.get("rosterProjection") or {}).get("whoKnowsWho") or {}
    assert wkw.get("current") == 0
    assert wkw.get("removed") == 1

    session.expire_all()
    edges_after = session.exec(
        select(TeamAvoidEdge).where(TeamAvoidEdge.event_id == event.id, TeamAvoidEdge.reason == RW_OS_WKW_REASON)
    ).all()
    assert edges_after == []
    after_matches = {
        m.id: (m.team_a_id, m.team_b_id, m.match_code)
        for m in session.exec(select(Match).where(Match.event_id == event.id)).all()
    }
    assert after_matches == before_matches


def test_withdrawal_drops_stale_edge(client: TestClient, session: Session, monkeypatch):
    teams = _mixed_field(8)
    a_key, b_key = teams[0].team_key, teams[1].team_key
    connections = _connections_for_keys([(a_key, b_key)])
    imported = persist_snapshot(session, _payload_with_wkw(9504, teams, connections))
    _approve(client, imported.id, {"mixed": "8"})
    event = session.exec(select(Event).where(Event.tournament_id == imported.tournament_id)).first()
    assert (
        len(
            session.exec(
                select(TeamAvoidEdge).where(
                    TeamAvoidEdge.event_id == event.id, TeamAvoidEdge.reason == RW_OS_WKW_REASON
                )
            ).all()
        )
        == 1
    )

    remaining = teams[1:]
    # Partner change for former B's neighbor graph — A withdrawn, new replacement team.
    replacement = _team("900/901", 8.7, draw="mixed", display="Replacement")
    next_teams = [replacement, *remaining]
    next_connections = _connections_for_keys([(replacement.team_key, b_key)])
    next_payload = _payload_with_wkw(9504, next_teams, next_connections, version="2")
    _patch_refresh(monkeypatch, [next_payload])
    resp = client.post(f"/api/rw-os/imports/{imported.id}/refresh", json={"apply": True})
    assert resp.status_code == 200, resp.text
    session.expire_all()
    live = _teams_by_key(session, imported.tournament_id)
    assert a_key not in live or live[a_key].is_defaulted
    edges = session.exec(
        select(TeamAvoidEdge).where(TeamAvoidEdge.event_id == event.id, TeamAvoidEdge.reason == RW_OS_WKW_REASON)
    ).all()
    assert len(edges) == 1
    pair = {edges[0].team_id_a, edges[0].team_id_b}
    assert live[a_key].id not in pair if a_key in live else True
    assert live[replacement.team_key].id in pair
    assert live[b_key].id in pair


def test_hash_changes_when_only_wkw_graph_changes():
    teams = _mixed_field(4)
    base = _payload_with_wkw(9505, teams, [])
    with_edge = _payload_with_wkw(
        9505,
        teams,
        _connections_for_keys([(teams[0].team_key, teams[1].team_key)]),
        version="1",
    )
    assert snapshot_hash(base) != snapshot_hash(with_edge)
    # Source order alone must not false-diff.
    shuffled = _payload_with_wkw(
        9505,
        teams,
        [
            {"drawKind": "mixed", "teamAKey": teams[1].team_key, "teamBKey": teams[0].team_key},
        ],
        version="1",
    )
    assert snapshot_hash(with_edge) == snapshot_hash(shuffled)


def test_production_shaped_mixed_10_connections(client: TestClient, session: Session, monkeypatch):
    teams = _mixed_field(24)
    pairs = [(teams[i].team_key, teams[i + 1].team_key) for i in range(0, 20, 2)][:10]
    assert len(pairs) == 10
    connections = _connections_for_keys(pairs)
    imported = persist_snapshot(session, _payload_with_wkw(9506, teams, connections))
    _approve(client, imported.id, {"mixed": "24"})
    event = session.exec(select(Event).where(Event.tournament_id == imported.tournament_id)).first()
    edges = session.exec(
        select(TeamAvoidEdge).where(TeamAvoidEdge.event_id == event.id, TeamAvoidEdge.reason == RW_OS_WKW_REASON)
    ).all()
    assert len(edges) == 10
    active = session.exec(select(Team).where(Team.event_id == event.id, Team.is_defaulted == False)).all()  # noqa: E712
    assert len(active) == 24

    summary = client.get(f"/api/events/{event.id}/who-knows-who-summary")
    assert summary.status_code == 200
    assert summary.json()["connections"] == 10

    placed = sorted(
        _teams_by_key(session, imported.tournament_id).values(),
        key=lambda team: (team.seed is None, team.seed or 0, team.id or 0),
    )
    _generate_wf24_draw(session, event, placed)
    before = {
        m.id: (m.team_a_id, m.team_b_id, m.match_code)
        for m in session.exec(select(Match).where(Match.event_id == event.id)).all()
    }

    # Normal refresh with same graph — draw unchanged.
    _patch_refresh(monkeypatch, [_payload_with_wkw(9506, teams, connections, version="2")])
    refresh = client.post(f"/api/rw-os/imports/{imported.id}/refresh", json={"apply": True})
    assert refresh.status_code == 200
    wkw = refresh.json()["rosterProjection"]["whoKnowsWho"]
    assert wkw["current"] == 10
    assert wkw["added"] == 0
    assert wkw["removed"] == 0
    session.expire_all()
    after = {
        m.id: (m.team_a_id, m.team_b_id, m.match_code)
        for m in session.exec(select(Match).where(Match.event_id == event.id)).all()
    }
    assert after == before

    _patch_refresh(monkeypatch, [_payload_with_wkw(9506, teams, connections, version="3")])
    rebuild = client.post(f"/api/rw-os/imports/{imported.id}/refresh-rebuild-draws")
    assert rebuild.status_code == 200, rebuild.text
    body = rebuild.json()
    assert body["events"][0]["whoKnowsWhoConnections"] == 10
    assert "Who-Knows-Who" in body["events"][0]["detail"]
    session.expire_all()
    rebuilt = {m.id: m.match_code for m in session.exec(select(Match).where(Match.event_id == event.id)).all()}
    assert set(rebuilt) == set(before)
    assert {mid: code for mid, code in rebuilt.items()} == {mid: before[mid][2] for mid in before}


def test_legacy_group_edges_ignored_in_pairwise_generator(client: TestClient, session: Session):
    teams = _mixed_field(8)
    # No pairwise edges; but plant a legacy clique edge that must not invent B-C style conflicts
    # when pairwise mode is on with an empty graph.
    connections: list[dict] = []
    imported = persist_snapshot(session, _payload_with_wkw(9507, teams, connections))
    _approve(client, imported.id, {"mixed": "8"})
    event = session.exec(select(Event).where(Event.tournament_id == imported.tournament_id)).first()
    live = _teams_by_key(session, imported.tournament_id)
    ids = [live[t.team_key].id for t in teams[:3]]
    session.add(
        TeamAvoidEdge(
            event_id=event.id,
            team_id_a=min(ids[1], ids[2]),
            team_id_b=max(ids[1], ids[2]),
            reason="group:A",
        )
    )
    session.commit()

    from app.services.rw_os_wkw import avoid_pairs_for_generator

    pairs = avoid_pairs_for_generator(session, event.id)
    assert pairs is not None
    assert (min(ids[1], ids[2]), max(ids[1], ids[2])) not in pairs

    seeds = [
        TeamSeed(seed=i + 1, team_id=live[t.team_key].id, rating=9.0 - i * 0.05, avoid_group="A")
        for i, t in enumerate(teams)
    ]
    result = build_wf_r1_pairings(seeds, 8, avoid_pairs=pairs)
    # Empty pairwise set ⇒ no WKW conflicts even if avoid_group letters would conflict.
    assert result.conflicts == []
