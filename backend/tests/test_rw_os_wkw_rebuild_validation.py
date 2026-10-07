"""Rebuild WKW post-condition: same-event constraints only; cross-bracket retained."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.models.event import Event
from app.models.match import Match
from app.models.match_assignment import MatchAssignment
from app.models.schedule_slot import ScheduleSlot
from app.models.schedule_version import ScheduleVersion
from app.models.team import Team
from app.models.team_avoid_edge import TeamAvoidEdge
from app.models.tournament import Tournament
from app.models.tournament_import import TournamentImport
from app.services.canonical_teams import sort_teams_for_planning
from app.services.rw_os_draw_rebuild import DrawRebuildError, _require_capacity_and_seeds
from app.services.rw_os_import import persist_snapshot
from app.services.rw_os_wkw import (
    RW_OS_WKW_REASON,
    TeamLocation,
    applicable_rw_os_wkw_pairs_for_event,
    build_tournament_wkw_graph_report,
    canonicalize_who_knows_who_connections,
    classify_snapshot_connections,
)
from app.services.wf_pairing import TeamSeed, _pair_conflict_label
from tests.test_desk_rw_os_refresh import _generate_wf24_draw, _patch_refresh
from tests.test_rw_os_draw_rebuild import (
    ANCHOR_ID,
    _mark_desk_draft,
    _pin_match_id,
    _post_rebuild,
    _schedule_draw,
)
from tests.test_rw_os_pairwise_wkw import _connections_for_keys, _payload_with_wkw
from tests.test_rw_os_roster_projection import (
    _approve,
    _mixed_field,
    _teams_by_key,
    _womens_field,
)


def _abc_keys(womens_field):
    ordered = sort_teams_for_planning(womens_field)
    return (
        [t.team_key for t in ordered[:8]],
        [t.team_key for t in ordered[8:16]],
        [t.team_key for t in ordered[16:]],
    )


def _production_shaped_connections(a, b, c, mixed_field):
    """Scaled 149/88/61-style graph on 24 Women's + 10 Mixed edges."""
    # Same-bracket: 2+1+1 = 4 within on this 8-8-8 field (scaled); add denser pairs
    pairs = []
    for i in range(6):
        pairs.append((a[i], a[i + 1]))
    for i in range(5):
        pairs.append((b[i], b[i + 1]))
    for i in range(5):
        pairs.append((c[i], c[i + 1]))
    # Cross-bracket
    for i in range(4):
        pairs.append((a[i], b[i]))
    for i in range(3):
        pairs.append((a[i], c[i]))
    for i in range(3):
        pairs.append((b[i], c[i]))
    # A–B and A–C without B–C for index 4
    pairs.append((a[4], b[4]))
    pairs.append((a[4], c[4]))
    w_conn = _connections_for_keys(pairs, draw_kind="womens")
    m_pairs = [(mixed_field[i].team_key, mixed_field[i + 1].team_key) for i in range(10)]
    m_conn = _connections_for_keys(m_pairs, draw_kind="mixed")
    return w_conn + m_conn, pairs


def _generate_wf8_brackets(session: Session, event: Event, placed: list[Team], version: ScheduleVersion) -> list[Match]:
    """8-team Women's WF→brackets on an existing schedule version (same topology rebuild uses)."""
    from app.services.draw_plan_engine import DrawPlanSpec, _generate_wf_to_brackets_8

    event.team_count = 8
    event.guarantee_selected = event.guarantee_selected or 4
    event.draw_plan_json = json.dumps({"version": "1.0", "template_type": "WF_TO_BRACKETS_8", "wf_rounds": 2})
    event.draw_status = "generated"
    session.add(event)
    session.commit()
    category = event.category.value if hasattr(event.category, "value") else str(event.category)
    spec = DrawPlanSpec(
        event_id=event.id,
        event_name=event.name,
        division="Women's",
        team_count=8,
        template_type="WF_TO_BRACKETS_8",
        template_key="WF_TO_BRACKETS_8",
        guarantee=int(event.guarantee_selected or 4),
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
    return matches


def _setup_abc_tournament(client: TestClient, session: Session, source_id: int = 9801):
    womens = _womens_field(24)
    mixed = _mixed_field(24)
    a, b, c = _abc_keys(womens)
    connections, raw_pairs = _production_shaped_connections(a, b, c, mixed)
    teams = [*womens, *mixed]
    imported = persist_snapshot(session, _payload_with_wkw(source_id, teams, connections))
    _approve(client, imported.id, {"womens": "8-8-8", "mixed": "24"})
    session.expire_all()
    events = {e.name: e for e in session.exec(select(Event).where(Event.tournament_id == imported.tournament_id)).all()}
    return {
        "imported": session.get(TournamentImport, imported.id),
        "events": events,
        "a": a,
        "b": b,
        "c": c,
        "mixed": mixed,
        "womens": womens,
        "connections": connections,
        "raw_pairs": raw_pairs,
        "teams": teams,
    }


def test_applicable_pairs_skip_cross_bracket_and_other_events():
    connections = canonicalize_who_knows_who_connections(
        [
            {"drawKind": "womens", "teamAKey": "1/2", "teamBKey": "3/4"},  # A-A
            {"drawKind": "womens", "teamAKey": "5/6", "teamBKey": "7/8"},  # B-B
            {"drawKind": "womens", "teamAKey": "1/2", "teamBKey": "5/6"},  # A-B
            {"drawKind": "mixed", "teamAKey": "9/10", "teamBKey": "11/12"},
        ]
    )
    locations = {
        "1/2": TeamLocation(1, 10, "Women's A", "womens"),
        "3/4": TeamLocation(2, 10, "Women's A", "womens"),
        "5/6": TeamLocation(3, 11, "Women's B", "womens"),
        "7/8": TeamLocation(4, 11, "Women's B", "womens"),
        "9/10": TeamLocation(5, 20, "Mixed", "mixed"),
        "11/12": TeamLocation(6, 20, "Mixed", "mixed"),
    }
    app_a = applicable_rw_os_wkw_pairs_for_event(connections, locations, event_id=10, draw_kind="womens")
    assert app_a.desired_pairs == {(1, 2)}
    assert app_a.skipped_non_applicable == 2
    assert app_a.unresolved == []
    app_b = applicable_rw_os_wkw_pairs_for_event(connections, locations, event_id=11, draw_kind="womens")
    assert app_b.desired_pairs == {(3, 4)}
    assert app_b.skipped_non_applicable == 2


def test_applicable_pairs_marks_genuine_unresolved():
    connections = canonicalize_who_knows_who_connections(
        [{"drawKind": "womens", "teamAKey": "1/2", "teamBKey": "99/100"}]
    )
    locations = {"1/2": TeamLocation(1, 10, "Women's A", "womens")}
    result = applicable_rw_os_wkw_pairs_for_event(connections, locations, event_id=10, draw_kind="womens")
    assert result.desired_pairs == set()
    assert len(result.unresolved) == 1
    assert result.unresolved[0]["reason"] == "unresolved_identity"


def test_require_capacity_accepts_cross_bracket_womens_graph(client: TestClient, session: Session):
    ctx = _setup_abc_tournament(client, session, 9802)
    imported = ctx["imported"]
    events = ctx["events"]
    report = build_tournament_wkw_graph_report(session, imported.tournament_id)["byDrawKind"]["womens"]
    assert report["total"] == len([c for c in ctx["connections"] if c["drawKind"] == "womens"])
    assert report["withinBracket"] + report["acrossBrackets"] == report["total"]
    assert report["acrossBrackets"] > 0

    for name in ("Women's A", "Women's B", "Women's C"):
        _require_capacity_and_seeds(session, imported, events[name])

    mixed_event = next(e for e in events.values() if "Mixed" in (e.name or ""))
    _require_capacity_and_seeds(session, imported, mixed_event)

    # All applicable stored edges match classification totals
    stored = 0
    for name in ("Women's A", "Women's B", "Women's C"):
        stored += len(
            session.exec(
                select(TeamAvoidEdge).where(
                    TeamAvoidEdge.event_id == events[name].id,
                    TeamAvoidEdge.reason == RW_OS_WKW_REASON,
                )
            ).all()
        )
    assert stored == report["withinBracket"]


def test_require_capacity_blocks_genuine_unresolved(client: TestClient, session: Session):
    ctx = _setup_abc_tournament(client, session, 9803)
    imported = ctx["imported"]
    events = ctx["events"]
    # Inject a snapshot edge to a missing key
    doc = json.loads(imported.snapshot_json)
    doc["whoKnowsWhoConnections"].append({"drawKind": "womens", "teamAKey": ctx["a"][0], "teamBKey": "99999/99998"})
    imported.snapshot_json = json.dumps(doc)
    session.add(imported)
    session.commit()
    session.refresh(imported)

    with pytest.raises(DrawRebuildError) as exc:
        _require_capacity_and_seeds(session, imported, events["Women's A"])
    assert "Unresolved connection" in str(exc.value)
    assert exc.value.details.get("unresolvedCount", 0) >= 1


def test_require_capacity_blocks_missing_same_event_edge(client: TestClient, session: Session):
    ctx = _setup_abc_tournament(client, session, 9804)
    events = ctx["events"]
    imported = ctx["imported"]
    edge = session.exec(
        select(TeamAvoidEdge).where(
            TeamAvoidEdge.event_id == events["Women's A"].id,
            TeamAvoidEdge.reason == RW_OS_WKW_REASON,
        )
    ).first()
    assert edge is not None
    session.delete(edge)
    session.commit()

    with pytest.raises(DrawRebuildError) as exc:
        _require_capacity_and_seeds(session, session.get(TournamentImport, imported.id), events["Women's A"])
    assert exc.value.details.get("missingPairs")


def test_require_capacity_blocks_extra_obsolete_edge(client: TestClient, session: Session):
    ctx = _setup_abc_tournament(client, session, 9805)
    events = ctx["events"]
    imported = ctx["imported"]
    live = _teams_by_key(session, imported.tournament_id)
    # Two Women's A teams that are NOT connected in the snapshot
    a_keys = ctx["a"]
    left = live[a_keys[6]].id
    right = live[a_keys[7]].id
    session.add(
        TeamAvoidEdge(
            event_id=events["Women's A"].id,
            team_id_a=min(left, right),
            team_id_b=max(left, right),
            reason=RW_OS_WKW_REASON,
        )
    )
    session.commit()

    with pytest.raises(DrawRebuildError) as exc:
        _require_capacity_and_seeds(session, session.get(TournamentImport, imported.id), events["Women's A"])
    assert exc.value.details.get("extraPairs")


def test_ab_ac_does_not_imply_bc(client: TestClient, session: Session):
    ctx = _setup_abc_tournament(client, session, 9806)
    live = _teams_by_key(session, ctx["imported"].tournament_id)
    a4, b4, c4 = live[ctx["a"][4]].id, live[ctx["b"][4]].id, live[ctx["c"][4]].id
    all_edges = session.exec(select(TeamAvoidEdge).where(TeamAvoidEdge.reason == RW_OS_WKW_REASON)).all()
    pairs = {(min(e.team_id_a, e.team_id_b), max(e.team_id_a, e.team_id_b)) for e in all_edges}
    assert (min(a4, b4), max(a4, b4)) not in pairs  # cross — not stored
    assert (min(a4, c4), max(a4, c4)) not in pairs
    assert (min(b4, c4), max(b4, c4)) not in pairs
    # Generator pairwise conflict: empty avoid for those ids within one event
    seeds = [
        TeamSeed(1, a4),
        TeamSeed(2, b4),
        TeamSeed(3, c4),
    ]
    # When only event A pairs are loaded, B–C is never a conflict
    from app.services.rw_os_wkw import avoid_pairs_for_generator

    avoid = avoid_pairs_for_generator(session, ctx["events"]["Women's A"].id) or set()
    assert _pair_conflict_label(seeds[1], seeds[2], avoid) is None


def test_full_rebuild_succeeds_with_cross_bracket_womens(client: TestClient, session: Session, monkeypatch):
    ctx = _setup_abc_tournament(client, session, 9807)
    imported = ctx["imported"]
    events = ctx["events"]
    tournament = session.get(Tournament, imported.tournament_id)

    # Shared operational version: generate Mixed + all Women's draws
    mixed_event = next(e for e in events.values() if "Mixed" in (e.name or ""))
    mixed_placed = sorted(
        [t for t in _teams_by_key(session, tournament.id).values() if t.event_id == mixed_event.id],
        key=lambda team: (team.seed is None, team.seed or 0, team.id or 0),
    )
    mixed_matches = _generate_wf24_draw(session, mixed_event, mixed_placed)
    version = session.exec(select(ScheduleVersion).where(ScheduleVersion.tournament_id == tournament.id)).first()
    assert version is not None

    for name in ("Women's A", "Women's B", "Women's C"):
        placed = sorted(
            [t for t in _teams_by_key(session, tournament.id).values() if t.event_id == events[name].id],
            key=lambda team: (team.seed is None, team.seed or 0, team.id or 0),
        )
        _generate_wf8_brackets(session, events[name], placed, version)

    session.expire_all()
    # Pin Mixed anchor + schedule on the operational desk draft
    mixed_matches = list(session.exec(select(Match).where(Match.event_id == mixed_event.id)).all())
    first = min(
        (m for m in mixed_matches if m.match_type == "WF" and m.round_index == 1),
        key=lambda m: m.sequence_in_round,
    )
    _pin_match_id(session, first, ANCHOR_ID)
    all_matches = list(session.exec(select(Match).where(Match.schedule_version_id == version.id)).all())
    tournament = session.get(Tournament, tournament.id)
    _schedule_draw(session, tournament, all_matches)
    version = session.exec(
        select(ScheduleVersion).where(
            ScheduleVersion.tournament_id == tournament.id,
            ScheduleVersion.status == "draft",
        )
    ).first()
    assert version is not None
    _mark_desk_draft(session, tournament, version)

    # Historical clone with assignments (must remain untouched; not authoritative)
    hist = ScheduleVersion(
        tournament_id=tournament.id,
        version_number=version.version_number + 1,
        status="final",
        label="historical-clone",
    )
    session.add(hist)
    session.commit()
    session.refresh(hist)
    # Copy one assignment fingerprint onto historical by cloning a slot+assignment for ANCHOR
    live_anchor = session.get(Match, ANCHOR_ID)
    live_assign = session.exec(select(MatchAssignment).where(MatchAssignment.match_id == ANCHOR_ID)).first()
    live_slot = session.get(ScheduleSlot, live_assign.slot_id)
    hist_match = Match(
        tournament_id=tournament.id,
        event_id=live_anchor.event_id,
        schedule_version_id=hist.id,
        match_code=live_anchor.match_code,
        match_type=live_anchor.match_type,
        round_number=live_anchor.round_number,
        round_index=live_anchor.round_index,
        sequence_in_round=live_anchor.sequence_in_round,
        duration_minutes=live_anchor.duration_minutes,
        team_a_id=live_anchor.team_a_id,
        team_b_id=live_anchor.team_b_id,
        placeholder_side_a=live_anchor.placeholder_side_a,
        placeholder_side_b=live_anchor.placeholder_side_b,
    )
    session.add(hist_match)
    session.commit()
    session.refresh(hist_match)
    hist_slot = ScheduleSlot(
        tournament_id=tournament.id,
        schedule_version_id=hist.id,
        day_date=live_slot.day_date,
        start_time=live_slot.start_time,
        end_time=live_slot.end_time,
        court_number=live_slot.court_number,
        court_label=live_slot.court_label,
        block_minutes=live_slot.block_minutes,
        is_manual_only=live_slot.is_manual_only,
    )
    session.add(hist_slot)
    session.commit()
    session.refresh(hist_slot)
    session.add(
        MatchAssignment(
            schedule_version_id=hist.id,
            match_id=hist_match.id,
            slot_id=hist_slot.id,
            assigned_by="DESK",
            locked=True,
        )
    )
    session.commit()
    hist_match_id = hist_match.id
    hist_slot_id = hist_slot.id

    before_assign = {
        a.match_id: (a.slot_id, a.locked)
        for a in session.exec(select(MatchAssignment).where(MatchAssignment.schedule_version_id == version.id)).all()
    }
    before_slots = {
        s.id: (str(s.day_date), str(s.start_time), str(s.end_time), s.court_label)
        for s in session.exec(select(ScheduleSlot).where(ScheduleSlot.schedule_version_id == version.id)).all()
    }
    before_ids = {m.id for m in session.exec(select(Match).where(Match.schedule_version_id == version.id)).all()}
    assert ANCHOR_ID in before_ids

    _patch_refresh(
        monkeypatch,
        [_payload_with_wkw(9807, ctx["teams"], ctx["connections"], version="2")],
    )
    resp = _post_rebuild(client, imported.id)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is True
    by_name = {item["name"]: item for item in body["events"]}
    assert by_name["Women's A"]["whoKnowsWhoConnections"] > 0
    assert by_name["Women's B"]["whoKnowsWhoConnections"] > 0
    assert by_name["Women's C"]["whoKnowsWhoConnections"] > 0
    mixed_name = next(name for name in by_name if "Mixed" in name)
    assert by_name[mixed_name]["whoKnowsWhoConnections"] == 10

    session.expire_all()
    after_ids = {m.id for m in session.exec(select(Match).where(Match.schedule_version_id == version.id)).all()}
    assert after_ids == before_ids
    assert ANCHOR_ID in after_ids
    after_assign = {
        a.match_id: (a.slot_id, a.locked)
        for a in session.exec(select(MatchAssignment).where(MatchAssignment.schedule_version_id == version.id)).all()
    }
    assert after_assign == before_assign
    after_slots = {
        s.id: (str(s.day_date), str(s.start_time), str(s.end_time), s.court_label)
        for s in session.exec(select(ScheduleSlot).where(ScheduleSlot.schedule_version_id == version.id)).all()
    }
    assert after_slots == before_slots

    # Historical untouched
    hist_match_after = session.get(Match, hist_match_id)
    hist_assign = session.exec(select(MatchAssignment).where(MatchAssignment.match_id == hist_match_id)).first()
    assert hist_match_after is not None
    assert hist_assign is not None
    assert hist_assign.slot_id == hist_slot_id
    assert hist_assign.locked is True


def test_failed_rebuild_rolls_back_wkw_and_draws(client: TestClient, session: Session, monkeypatch):
    ctx = _setup_abc_tournament(client, session, 9808)
    imported = ctx["imported"]
    events = ctx["events"]
    mixed_event = next(e for e in events.values() if "Mixed" in (e.name or ""))
    placed = sorted(
        [t for t in _teams_by_key(session, imported.tournament_id).values() if t.event_id == mixed_event.id],
        key=lambda team: (team.seed is None, team.seed or 0, team.id or 0),
    )
    _generate_wf24_draw(session, mixed_event, placed)
    version = session.exec(
        select(ScheduleVersion).where(ScheduleVersion.tournament_id == imported.tournament_id)
    ).first()
    for name in ("Women's A", "Women's B", "Women's C"):
        wplaced = sorted(
            [t for t in _teams_by_key(session, imported.tournament_id).values() if t.event_id == events[name].id],
            key=lambda team: (team.seed is None, team.seed or 0, team.id or 0),
        )
        _generate_wf8_brackets(session, events[name], wplaced, version)

    edge_count_before = len(session.exec(select(TeamAvoidEdge).where(TeamAvoidEdge.reason == RW_OS_WKW_REASON)).all())
    match_codes_before = {
        m.id: m.match_code for m in session.exec(select(Match).where(Match.schedule_version_id == version.id)).all()
    }

    # Poison snapshot with unresolved WKW so rebuild fails after refresh sync attempt
    bad_connections = list(ctx["connections"]) + [
        {"drawKind": "womens", "teamAKey": ctx["a"][0], "teamBKey": "88888/88887"}
    ]
    _patch_refresh(
        monkeypatch,
        [_payload_with_wkw(9808, ctx["teams"], bad_connections, version="2")],
    )
    resp = _post_rebuild(client, imported.id)
    assert resp.status_code == 409, resp.text
    detail = resp.json().get("detail") or {}
    assert detail.get("code") == "roster_reconciliation_incomplete"

    session.expire_all()
    edge_count_after = len(session.exec(select(TeamAvoidEdge).where(TeamAvoidEdge.reason == RW_OS_WKW_REASON)).all())
    assert edge_count_after == edge_count_before
    match_codes_after = {
        m.id: m.match_code for m in session.exec(select(Match).where(Match.schedule_version_id == version.id)).all()
    }
    assert match_codes_after == match_codes_before


def test_production_shaped_149_fixture_classifies_and_validates(client: TestClient, session: Session):
    """Full 96 Women's / 149 connections / 88 within / 61 across (synthetic partition)."""
    keys = [f"{i}/{i + 1}" for i in range(1, 193, 2)]
    assert len(keys) == 96
    a, b, c = keys[:32], keys[32:64], keys[64:]
    pairs = []
    for i in range(30):
        pairs.append((a[i], a[i + 1]))
    for i in range(28):
        pairs.append((b[i], b[i + 1]))
    for i in range(30):
        pairs.append((c[i], c[i + 1]))
    for i in range(25):
        pairs.append((a[i], b[i]))
    for i in range(20):
        pairs.append((a[i], c[i]))
    for i in range(16):
        pairs.append((b[i], c[i]))
    assert len(pairs) == 149
    connections = canonicalize_who_knows_who_connections(
        [{"drawKind": "womens", "teamAKey": x, "teamBKey": y} for x, y in pairs]
    )
    locations = {}
    for index, key in enumerate(keys):
        if index < 32:
            eid, name = 1, "Women's A"
        elif index < 64:
            eid, name = 2, "Women's B"
        else:
            eid, name = 3, "Women's C"
        locations[key] = TeamLocation(index + 1, eid, name, "womens")

    app_a = applicable_rw_os_wkw_pairs_for_event(connections, locations, event_id=1, draw_kind="womens")
    app_b = applicable_rw_os_wkw_pairs_for_event(connections, locations, event_id=2, draw_kind="womens")
    app_c = applicable_rw_os_wkw_pairs_for_event(connections, locations, event_id=3, draw_kind="womens")
    assert len(app_a.desired_pairs) == 30
    assert len(app_b.desired_pairs) == 28
    assert len(app_c.desired_pairs) == 30
    assert app_a.skipped_non_applicable == 119
    assert app_a.unresolved == []
    within = len(app_a.desired_pairs) + len(app_b.desired_pairs) + len(app_c.desired_pairs)
    assert within == 88
    # Same partition as tournament classification: 149 total / 88 within / 61 across
    report = classify_snapshot_connections(connections, locations)["womens"]
    assert report.total == 149
    assert report.within_bracket == 88
    assert report.across_brackets == 61
    # Production applicable total is Women's within + Mixed 10 = 98
    mixed_keys = [f"m{i}/m{i + 1}" for i in range(1, 41, 2)]
    assert len(mixed_keys) == 20
    mixed_pairs = [(mixed_keys[i], mixed_keys[i + 1]) for i in range(0, 20, 2)]
    assert len(mixed_pairs) == 10
    mixed_conn = canonicalize_who_knows_who_connections(
        [{"drawKind": "mixed", "teamAKey": x, "teamBKey": y} for x, y in mixed_pairs]
    )
    mixed_locs = {key: TeamLocation(200 + i, 20, "Mixed", "mixed") for i, key in enumerate(mixed_keys)}
    app_m = applicable_rw_os_wkw_pairs_for_event(mixed_conn, mixed_locs, event_id=20, draw_kind="mixed")
    assert len(app_m.desired_pairs) == 10
    assert within + len(app_m.desired_pairs) == 98
