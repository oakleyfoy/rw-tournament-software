"""Tournament-wide Women's WKW graph classification and bracket reassignment."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.models.event import Event
from app.models.match import Match
from app.models.match_assignment import MatchAssignment
from app.models.schedule_slot import ScheduleSlot
from app.models.team_avoid_edge import TeamAvoidEdge
from app.models.tournament_import import TournamentImport
from app.services.canonical_teams import sort_teams_for_planning
from app.services.post_draw_corrections import move_team_between_events
from app.services.rw_os_import import persist_snapshot
from app.services.rw_os_wkw import (
    RW_OS_WKW_REASON,
    TeamLocation,
    build_tournament_wkw_graph_report,
    canonicalize_who_knows_who_connections,
    classify_snapshot_connections,
    load_snapshot_connections,
)
from tests.test_desk_rw_os_refresh import _generate_wf24_draw, _patch_refresh
from tests.test_rw_os_pairwise_wkw import _connections_for_keys, _payload_with_wkw
from tests.test_rw_os_roster_projection import (
    _approve,
    _mixed_field,
    _teams_by_key,
    _womens_field,
)


def _locations_for_abc(keys: list[str], sizes: tuple[int, int, int] = (32, 32, 32)) -> dict[str, TeamLocation]:
    """Assign keys in order to Women's A/B/C by planner rank."""
    a_n, b_n, c_n = sizes
    assert len(keys) == a_n + b_n + c_n
    locations: dict[str, TeamLocation] = {}
    for index, key in enumerate(keys):
        if index < a_n:
            name, event_id = "Women's A", 1
        elif index < a_n + b_n:
            name, event_id = "Women's B", 2
        else:
            name, event_id = "Women's C", 3
        locations[key] = TeamLocation(
            team_id=index + 1,
            event_id=event_id,
            event_name=name,
            draw_kind="womens",
        )
    return locations


def test_classify_149_womens_edges_partition_without_inventing_bc():
    """Complete 149-edge source graph with known same/cross bracket split."""
    keys = [f"{i}/{i + 1}" for i in range(1, 193, 2)]  # 96 keys
    assert len(keys) == 96
    locations = _locations_for_abc(keys)

    a_keys = keys[:32]
    b_keys = keys[32:64]
    c_keys = keys[64:]

    pairs: list[tuple[str, str]] = []
    # Same-bracket: 30 + 28 + 30 = 88
    for i in range(30):
        pairs.append((a_keys[i], a_keys[i + 1]))
    for i in range(28):
        pairs.append((b_keys[i], b_keys[i + 1]))
    for i in range(30):
        pairs.append((c_keys[i], c_keys[i + 1]))
    # Cross-bracket: 25 + 20 + 16 = 61
    for i in range(25):
        pairs.append((a_keys[i], b_keys[i]))
    for i in range(20):
        pairs.append((a_keys[i], c_keys[i]))
    for i in range(16):
        pairs.append((b_keys[i], c_keys[i]))
    assert len(pairs) == 149

    # A–B and A–C must not imply B–C for pairs that were not listed.
    listed = {(min(a, b), max(a, b)) for a, b in pairs}
    assert (b_keys[20], c_keys[20]) not in listed  # only 16 B–C pairs (0..15)

    connections = canonicalize_who_knows_who_connections(
        [{"drawKind": "womens", "teamAKey": a, "teamBKey": b} for a, b in pairs]
    )
    assert len(connections) == 149

    reports = classify_snapshot_connections(connections, locations, draw_kind="womens")
    womens = reports["womens"]
    assert womens.total == 149
    assert womens.within_bracket == 88
    assert womens.across_brackets == 61
    assert womens.unresolved == 0
    assert womens.inactive == 0
    assert womens.within_bracket + womens.across_brackets == 149
    assert womens.partition["Women's A | Women's A"] == 30
    assert womens.partition["Women's B | Women's B"] == 28
    assert womens.partition["Women's C | Women's C"] == 30
    assert womens.partition["Women's A | Women's B"] == 25
    assert womens.partition["Women's A | Women's C"] == 20
    assert womens.partition["Women's B | Women's C"] == 16


def test_unresolved_and_inactive_classified_separately():
    connections = canonicalize_who_knows_who_connections(
        [
            {"drawKind": "womens", "teamAKey": "1/2", "teamBKey": "3/4"},
            {"drawKind": "womens", "teamAKey": "5/6", "teamBKey": "7/8"},
            {"drawKind": "womens", "teamAKey": "1/2", "teamBKey": "9/10"},
        ]
    )
    locations = {
        "1/2": TeamLocation(1, 1, "Women's A", "womens"),
        "3/4": TeamLocation(2, 1, "Women's A", "womens"),
        "5/6": TeamLocation(3, 1, "Women's A", "womens", is_defaulted=True),
        "7/8": TeamLocation(4, 2, "Women's B", "womens"),
        # 9/10 missing → unresolved
    }
    report = classify_snapshot_connections(connections, locations, draw_kind="womens")["womens"]
    assert report.total == 3
    assert report.within_bracket == 1
    assert report.inactive == 1
    assert report.unresolved == 1


def test_womens_abc_live_sync_keeps_snapshot_and_stores_same_bracket_only(client: TestClient, session: Session):
    womens = _womens_field(24)
    ordered = sort_teams_for_planning(womens)
    a_keys = [team.team_key for team in ordered[:8]]
    b_keys = [team.team_key for team in ordered[8:16]]
    c_keys = [team.team_key for team in ordered[16:]]

    pairs = [
        (a_keys[0], a_keys[1]),
        (a_keys[2], a_keys[3]),
        (b_keys[0], b_keys[1]),
        (c_keys[0], c_keys[1]),
        (a_keys[0], b_keys[0]),  # cross
        (a_keys[1], c_keys[1]),  # cross
        (b_keys[2], c_keys[2]),  # cross
        # A–B and A–C without B–C for these keys
        (a_keys[4], b_keys[4]),
        (a_keys[4], c_keys[4]),
    ]
    connections = _connections_for_keys(pairs, draw_kind="womens")
    assert len(connections) == 9
    assert not any({row["teamAKey"], row["teamBKey"]} == {b_keys[4], c_keys[4]} for row in connections)

    imported = persist_snapshot(session, _payload_with_wkw(9601, womens, connections))
    _approve(client, imported.id, {"womens": "8-8-8"})

    snapshot = load_snapshot_connections(session.get(TournamentImport, imported.id))
    assert snapshot is not None
    assert len([edge for edge in snapshot if edge.draw_kind == "womens"]) == 9

    report = build_tournament_wkw_graph_report(session, imported.tournament_id)
    womens_report = report["byDrawKind"]["womens"]
    assert womens_report["total"] == 9
    assert womens_report["withinBracket"] == 4
    assert womens_report["acrossBrackets"] == 5
    assert womens_report["unresolved"] == 0

    api = client.get(f"/api/tournaments/{imported.tournament_id}/who-knows-who-summary")
    assert api.status_code == 200
    assert api.json()["byDrawKind"]["womens"]["total"] == 9

    events = {
        event.name: event
        for event in session.exec(select(Event).where(Event.tournament_id == imported.tournament_id)).all()
    }
    for name in ("Women's A", "Women's B", "Women's C"):
        edges = session.exec(
            select(TeamAvoidEdge).where(
                TeamAvoidEdge.event_id == events[name].id,
                TeamAvoidEdge.reason == RW_OS_WKW_REASON,
            )
        ).all()
        # Only same-bracket edges materialize.
        assert len(edges) == (2 if name == "Women's A" else 1)

    # No artificial B–C edge stored anywhere for a_keys[4]'s neighbors.
    live = _teams_by_key(session, imported.tournament_id)
    b4, c4 = live[b_keys[4]].id, live[c_keys[4]].id
    all_edges = session.exec(select(TeamAvoidEdge).where(TeamAvoidEdge.reason == RW_OS_WKW_REASON)).all()
    pairs_stored = {(min(e.team_id_a, e.team_id_b), max(e.team_id_a, e.team_id_b)) for e in all_edges}
    assert (min(b4, c4), max(b4, c4)) not in pairs_stored


def test_bracket_reassignment_reevaluates_event_constraints(client: TestClient, session: Session):
    womens = _womens_field(24)
    ordered = sort_teams_for_planning(womens)
    a0, a1 = ordered[0].team_key, ordered[1].team_key
    b0 = ordered[8].team_key
    # Same-bracket A edge + cross A–B edge involving a0.
    connections = _connections_for_keys([(a0, a1), (a0, b0)], draw_kind="womens")
    imported = persist_snapshot(session, _payload_with_wkw(9602, womens, connections))
    _approve(client, imported.id, {"womens": "8-8-8"})
    live = _teams_by_key(session, imported.tournament_id)
    events = {
        event.name: event
        for event in session.exec(select(Event).where(Event.tournament_id == imported.tournament_id)).all()
    }

    edges_a = session.exec(
        select(TeamAvoidEdge).where(
            TeamAvoidEdge.event_id == events["Women's A"].id,
            TeamAvoidEdge.reason == RW_OS_WKW_REASON,
        )
    ).all()
    assert len(edges_a) == 1  # only a0–a1

    # Move a0 into Women's B → a0–b0 becomes same-bracket; a0–a1 becomes cross (dropped from A).
    move_team_between_events(
        session,
        team_id=live[a0].id,
        destination_event_id=events["Women's B"].id,
        confirm_existing_draws=True,
    )
    session.commit()
    session.expire_all()

    edges_a_after = session.exec(
        select(TeamAvoidEdge).where(
            TeamAvoidEdge.event_id == events["Women's A"].id,
            TeamAvoidEdge.reason == RW_OS_WKW_REASON,
        )
    ).all()
    edges_b_after = session.exec(
        select(TeamAvoidEdge).where(
            TeamAvoidEdge.event_id == events["Women's B"].id,
            TeamAvoidEdge.reason == RW_OS_WKW_REASON,
        )
    ).all()
    assert edges_a_after == []
    assert len(edges_b_after) == 1
    pair = {edges_b_after[0].team_id_a, edges_b_after[0].team_id_b}
    assert live[a0].id in pair
    assert live[b0].id in pair

    report = build_tournament_wkw_graph_report(session, imported.tournament_id)["byDrawKind"]["womens"]
    assert report["total"] == 2
    assert report["withinBracket"] == 1
    assert report["acrossBrackets"] == 1


def test_withdrawn_team_excluded_from_event_constraints(client: TestClient, session: Session, monkeypatch):
    womens = _womens_field(8)
    a_key, b_key = womens[0].team_key, womens[1].team_key
    connections = _connections_for_keys([(a_key, b_key)], draw_kind="womens")
    imported = persist_snapshot(session, _payload_with_wkw(9603, womens, connections))
    _approve(client, imported.id, {"womens": "8"})

    remaining = womens[1:]
    next_payload = _payload_with_wkw(9603, remaining, [], version="2")
    _patch_refresh(monkeypatch, [next_payload])
    resp = client.post(f"/api/rw-os/imports/{imported.id}/refresh", json={"apply": True})
    assert resp.status_code == 200, resp.text
    session.expire_all()

    event = session.exec(select(Event).where(Event.tournament_id == imported.tournament_id)).first()
    edges = session.exec(
        select(TeamAvoidEdge).where(
            TeamAvoidEdge.event_id == event.id,
            TeamAvoidEdge.reason == RW_OS_WKW_REASON,
        )
    ).all()
    assert edges == []
    report = build_tournament_wkw_graph_report(session, imported.tournament_id)
    # Snapshot now empty after refresh payload.
    assert report["byDrawKind"].get("womens", {}).get("total", 0) == 0


def test_normal_refresh_does_not_move_matchups(client: TestClient, session: Session, monkeypatch):
    teams = _mixed_field(24)
    pairs = [(teams[i].team_key, teams[i + 1].team_key) for i in range(0, 10)]
    connections = _connections_for_keys(pairs)
    imported = persist_snapshot(session, _payload_with_wkw(9604, teams, connections))
    _approve(client, imported.id, {"mixed": "24"})
    event = session.exec(select(Event).where(Event.tournament_id == imported.tournament_id)).first()
    placed = sorted(
        _teams_by_key(session, imported.tournament_id).values(),
        key=lambda team: (team.seed is None, team.seed or 0, team.id or 0),
    )
    _generate_wf24_draw(session, event, placed)
    before = {
        m.id: (m.team_a_id, m.team_b_id, m.match_code, m.schedule_version_id)
        for m in session.exec(select(Match).where(Match.event_id == event.id)).all()
    }
    assignments_before = {
        (a.match_id, a.slot_id, a.locked) for a in session.exec(select(MatchAssignment)).all() if a.match_id in before
    }
    slots_before = {
        s.id: (s.day_date, s.start_time, s.end_time, s.court_label) for s in session.exec(select(ScheduleSlot)).all()
    }

    _patch_refresh(monkeypatch, [_payload_with_wkw(9604, teams, connections, version="2")])
    resp = client.post(f"/api/rw-os/imports/{imported.id}/refresh", json={"apply": True})
    assert resp.status_code == 200
    session.expire_all()
    after = {
        m.id: (m.team_a_id, m.team_b_id, m.match_code, m.schedule_version_id)
        for m in session.exec(select(Match).where(Match.event_id == event.id)).all()
    }
    assert after == before
    assignments_after = {
        (a.match_id, a.slot_id, a.locked) for a in session.exec(select(MatchAssignment)).all() if a.match_id in after
    }
    assert assignments_after == assignments_before
    slots_after = {
        s.id: (s.day_date, s.start_time, s.end_time, s.court_label) for s in session.exec(select(ScheduleSlot)).all()
    }
    assert slots_after == slots_before


def test_rebuild_preserves_match_ids_and_schedule(client: TestClient, session: Session, monkeypatch):
    teams = _mixed_field(24)
    connections = _connections_for_keys([(teams[0].team_key, teams[1].team_key)])
    imported = persist_snapshot(session, _payload_with_wkw(9605, teams, connections))
    _approve(client, imported.id, {"mixed": "24"})
    event = session.exec(select(Event).where(Event.tournament_id == imported.tournament_id)).first()
    placed = sorted(
        _teams_by_key(session, imported.tournament_id).values(),
        key=lambda team: (team.seed is None, team.seed or 0, team.id or 0),
    )
    _generate_wf24_draw(session, event, placed)
    before_codes = {m.id: m.match_code for m in session.exec(select(Match).where(Match.event_id == event.id)).all()}
    before_assign = {
        a.match_id: (a.slot_id, a.locked)
        for a in session.exec(select(MatchAssignment)).all()
        if a.match_id in before_codes
    }
    before_slots = {
        s.id: (str(s.day_date), str(s.start_time), str(s.end_time), s.court_label)
        for s in session.exec(select(ScheduleSlot)).all()
    }

    _patch_refresh(monkeypatch, [_payload_with_wkw(9605, teams, connections, version="2")])
    rebuild = client.post(f"/api/rw-os/imports/{imported.id}/refresh-rebuild-draws")
    assert rebuild.status_code == 200, rebuild.text
    session.expire_all()
    after_codes = {m.id: m.match_code for m in session.exec(select(Match).where(Match.event_id == event.id)).all()}
    assert after_codes == before_codes
    after_assign = {
        a.match_id: (a.slot_id, a.locked)
        for a in session.exec(select(MatchAssignment)).all()
        if a.match_id in after_codes
    }
    assert after_assign == before_assign
    after_slots = {
        s.id: (str(s.day_date), str(s.start_time), str(s.end_time), s.court_label)
        for s in session.exec(select(ScheduleSlot)).all()
    }
    assert after_slots == before_slots
