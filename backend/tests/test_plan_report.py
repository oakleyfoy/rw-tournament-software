"""
Tests for the Schedule Plan Report (authoritative contract).

Test scenarios:
1. Happy path: multiple events, WF + RR + brackets → ok=true, no blocking errors
2. Inventory mismatch: force remove one RR match → E_INVENTORY_MISMATCH
3. RR wiring: missing placeholder → E_RR_MATCH_MISSING_PLACEHOLDER
4. RR constraint: shuffle round numbers so 1v2 not last → E_RR_TOP2_NOT_LAST_ROUND
5. Determinism: same inputs return identical JSON ordering (snapshot test)
"""

import json
from datetime import date, time

import pytest
from sqlmodel import Session, select

from app.models.event import Event
from app.models.match import Match
from app.models.schedule_version import ScheduleVersion
from app.models.tournament import Tournament
from app.models.tournament_day import TournamentDay
from app.models.tournament_time_window import TournamentTimeWindow
from app.models.team import Team
from app.services.plan_report import (
    SchedulePlanReport,
    build_schedule_plan_report,
)
from app.services.draw_plan_engine import (
    build_spec_from_event,
    compute_inventory,
    generate_matches_for_event,
)


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def tournament_with_events(session: Session):
    """
    Create a tournament with:
      - Event A: 8 teams, WF_TO_POOLS_DYNAMIC (1 WF round + RR pools)
      - Event B: 4 teams, RR_ONLY
    Also create a draft schedule version and generate matches.
    """
    # Tournament
    t = Tournament(
        name="Plan Report Test Tournament",
        location="Test Venue",
        timezone="US/Eastern",
        start_date=date(2025, 6, 20),
        end_date=date(2025, 6, 22),
        use_time_windows=True,
        court_names=["Court 1", "Court 2"],
    )
    session.add(t)
    session.commit()
    session.refresh(t)

    # Day + Time Window (needed for slot generation, but we just need events/matches)
    day = TournamentDay(
        tournament_id=t.id,
        date=date(2025, 6, 20),
        is_active=True,
        start_time=time(8, 0),
        end_time=time(18, 0),
        courts_available=2,
    )
    session.add(day)
    session.commit()

    tw = TournamentTimeWindow(
        tournament_id=t.id,
        day_date=date(2025, 6, 20),
        start_time=time(8, 0),
        end_time=time(18, 0),
        courts_available=2,
        block_minutes=120,
        is_active=True,
    )
    session.add(tw)
    session.commit()

    # Schedule Version
    sv = ScheduleVersion(
        tournament_id=t.id,
        version_number=1,
        status="draft",
    )
    session.add(sv)
    session.commit()
    session.refresh(sv)

    # Event A: 8 teams, WF_TO_POOLS_DYNAMIC, 1 WF round
    event_a = Event(
        tournament_id=t.id,
        category="mixed",
        name="Mixed 8",
        team_count=8,
        draw_plan_json=json.dumps({
            "template_type": "WF_TO_POOLS_DYNAMIC",
            "wf_rounds": 1,
            "timing": {
                "wf_block_minutes": 60,
                "standard_block_minutes": 120,
            },
        }),
        draw_status="final",
        guarantee_selected=5,
        wf_block_minutes=60,
        standard_block_minutes=120,
    )
    session.add(event_a)
    session.commit()
    session.refresh(event_a)

    # Event B: 4 teams, RR_ONLY
    event_b = Event(
        tournament_id=t.id,
        category="womens",
        name="Womens 4",
        team_count=4,
        draw_plan_json=json.dumps({
            "template_type": "RR_ONLY",
            "wf_rounds": 0,
            "timing": {
                "wf_block_minutes": 60,
                "standard_block_minutes": 120,
            },
        }),
        draw_status="final",
        guarantee_selected=5,
        wf_block_minutes=60,
        standard_block_minutes=120,
    )
    session.add(event_b)
    session.commit()
    session.refresh(event_b)

    # Create teams for both events
    for i in range(1, 9):
        session.add(Team(
            event_id=event_a.id,
            name=f"Team A{i}",
            seed=i,
            rating=100 - i,
        ))
    for i in range(1, 5):
        session.add(Team(
            event_id=event_b.id,
            name=f"Team B{i}",
            seed=i,
            rating=100 - i,
        ))
    session.commit()

    # Generate matches for both events using the engine
    teams_a = session.exec(
        select(Team).where(Team.event_id == event_a.id).order_by(Team.seed)
    ).all()
    teams_b = session.exec(
        select(Team).where(Team.event_id == event_b.id).order_by(Team.seed)
    ).all()

    spec_a = build_spec_from_event(event_a)
    spec_b = build_spec_from_event(event_b)

    existing_codes: set = set()

    # Allow match generation
    session._allow_match_generation = True  # type: ignore[attr-defined]

    matches_a, _ = generate_matches_for_event(
        session, sv.id, spec_a, [tm.id for tm in teams_a], existing_codes
    )
    session.add_all(matches_a)
    session.commit()

    matches_b, _ = generate_matches_for_event(
        session, sv.id, spec_b, [tm.id for tm in teams_b], existing_codes
    )
    session.add_all(matches_b)
    session.commit()

    session._allow_match_generation = False  # type: ignore[attr-defined]

    return {
        "tournament": t,
        "version": sv,
        "event_a": event_a,
        "event_b": event_b,
        "teams_a": teams_a,
        "teams_b": teams_b,
    }


# ============================================================================
# Test 1: Happy Path — ok=true, no blocking errors
# ============================================================================


def test_happy_path_no_blocking_errors(session: Session, tournament_with_events):
    """Multiple events with valid draw plans and correct match inventory → ok=true."""
    t = tournament_with_events["tournament"]
    sv = tournament_with_events["version"]

    report = build_schedule_plan_report(session, t.id, sv.id)

    assert report.ok is True
    assert len(report.blocking_errors) == 0
    assert report.tournament_id == t.id
    assert report.schedule_version_id == sv.id
    assert report.version_status == "draft"
    assert report.totals.events == 2
    assert report.totals.matches_total > 0

    # Event A: 8 teams, WF_TO_POOLS_DYNAMIC, 1 WF round
    event_a_report = next(e for e in report.events if e.name == "Mixed 8")
    assert event_a_report.teams_count == 8
    assert event_a_report.template_code == "WF_TO_POOLS_DYNAMIC"
    assert event_a_report.waterfall.rounds == 1
    assert event_a_report.waterfall.r1_matches == 4
    assert event_a_report.waterfall.r2_matches == 0
    assert event_a_report.pools.pool_count == 2
    assert event_a_report.pools.pool_size == 4
    assert event_a_report.pools.rr_rounds == 3
    assert event_a_report.pools.rr_matches == 12  # 2 pools × C(4,2) = 2×6
    assert event_a_report.inventory.expected_total == event_a_report.inventory.actual_total

    # Event B: 4 teams, RR_ONLY
    event_b_report = next(e for e in report.events if e.name == "Womens 4")
    assert event_b_report.teams_count == 4
    assert event_b_report.template_code == "RR_ONLY"
    assert event_b_report.waterfall.rounds == 0
    assert event_b_report.pools.pool_count == 1
    assert event_b_report.pools.pool_size == 4
    assert event_b_report.pools.rr_matches == 6  # C(4,2) = 6
    assert event_b_report.inventory.expected_total == 6
    assert event_b_report.inventory.actual_total == 6


def test_happy_path_no_version(session: Session, tournament_with_events):
    """Draw-plan-only validation (no version) → ok=true when plans are valid."""
    t = tournament_with_events["tournament"]

    report = build_schedule_plan_report(session, t.id)

    assert report.ok is True
    assert len(report.blocking_errors) == 0
    assert report.schedule_version_id is None
    assert report.version_status is None
    assert report.totals.events == 2
    # Without a version, actual_total is 0 for all events
    for ev in report.events:
        assert ev.inventory.actual_total == 0


# ============================================================================
# Test 2: Inventory Mismatch — E_INVENTORY_MISMATCH
# ============================================================================


def test_inventory_mismatch_triggers_error(session: Session, tournament_with_events):
    """Force remove one RR match → E_INVENTORY_MISMATCH."""
    t = tournament_with_events["tournament"]
    sv = tournament_with_events["version"]
    event_b = tournament_with_events["event_b"]

    # Delete one RR match from event B
    matches_b = session.exec(
        select(Match).where(
            Match.event_id == event_b.id,
            Match.schedule_version_id == sv.id,
            Match.match_type == "RR",
        )
    ).all()
    assert len(matches_b) > 0
    session.delete(matches_b[0])
    session.flush()

    report = build_schedule_plan_report(session, t.id, sv.id)

    assert report.ok is False
    mismatch_errors = [e for e in report.blocking_errors if e.code == "E_INVENTORY_MISMATCH"]
    assert len(mismatch_errors) >= 1

    # The mismatch should be for event B
    event_b_error = next(e for e in mismatch_errors if e.event_id == event_b.id)
    assert "expected 6" in event_b_error.message
    assert "found 5" in event_b_error.message


# ============================================================================
# Test 3: RR Wiring — E_RR_MATCH_MISSING_PLACEHOLDER
# ============================================================================


def test_rr_missing_placeholder_triggers_error(session: Session, tournament_with_events):
    """Corrupt an RR match placeholder → E_RR_MATCH_MISSING_PLACEHOLDER."""
    t = tournament_with_events["tournament"]
    sv = tournament_with_events["version"]
    event_b = tournament_with_events["event_b"]

    # Corrupt one RR match placeholder
    matches_b = session.exec(
        select(Match).where(
            Match.event_id == event_b.id,
            Match.schedule_version_id == sv.id,
            Match.match_type == "RR",
        )
    ).all()
    assert len(matches_b) > 0
    match_to_corrupt = matches_b[0]
    match_to_corrupt.placeholder_side_a = "INVALID_PLACEHOLDER"
    session.add(match_to_corrupt)
    session.flush()

    report = build_schedule_plan_report(session, t.id, sv.id)

    assert report.ok is False
    placeholder_errors = [e for e in report.blocking_errors if e.code == "E_RR_MATCH_MISSING_PLACEHOLDER"]
    assert len(placeholder_errors) >= 1
    assert placeholder_errors[0].event_id == event_b.id


# ============================================================================
# Test 4: RR Constraint — E_RR_TOP2_NOT_LAST_ROUND
# ============================================================================


def test_rr_top2_not_last_round_triggers_error(session: Session, tournament_with_events):
    """Shuffle round numbers so seeds 1,2 are NOT in the last round → E_RR_TOP2_NOT_LAST_ROUND."""
    t = tournament_with_events["tournament"]
    sv = tournament_with_events["version"]
    event_b = tournament_with_events["event_b"]

    # For RR_ONLY with 4 teams:
    # Round 3 should have seeds 1 vs 2.
    # Move seeds 1v2 match to round 1 and the round 1 match to round 3.
    matches_b = session.exec(
        select(Match).where(
            Match.event_id == event_b.id,
            Match.schedule_version_id == sv.id,
            Match.match_type == "RR",
        ).order_by(Match.round_index, Match.sequence_in_round)
    ).all()

    # Find the 1v2 match (should be in round 3)
    match_1v2 = None
    match_first_round = None
    for m in matches_b:
        seed_a = None
        seed_b = None
        if m.placeholder_side_a and m.placeholder_side_a.startswith("SEED_"):
            seed_a = int(m.placeholder_side_a[5:])
        if m.placeholder_side_b and m.placeholder_side_b.startswith("SEED_"):
            seed_b = int(m.placeholder_side_b[5:])
        if seed_a is not None and seed_b is not None:
            if {seed_a, seed_b} == {1, 2}:
                match_1v2 = m
            elif m.round_index == 1 and match_first_round is None:
                match_first_round = m

    assert match_1v2 is not None, "Could not find 1v2 match"
    assert match_first_round is not None, "Could not find a round 1 match"

    # Swap round indices
    original_round_1v2 = match_1v2.round_index
    original_round_first = match_first_round.round_index
    match_1v2.round_index = original_round_first
    match_1v2.round_number = original_round_first
    match_first_round.round_index = original_round_1v2
    match_first_round.round_number = original_round_1v2
    session.add(match_1v2)
    session.add(match_first_round)
    session.flush()

    report = build_schedule_plan_report(session, t.id, sv.id)

    assert report.ok is False
    top2_errors = [e for e in report.blocking_errors if e.code == "E_RR_TOP2_NOT_LAST_ROUND"]
    assert len(top2_errors) >= 1
    assert top2_errors[0].event_id == event_b.id


# ============================================================================
# Test 5: Determinism — Same inputs → identical JSON ordering
# ============================================================================


def test_determinism_stable_ordering(session: Session, tournament_with_events):
    """Same inputs return identical JSON ordering across runs."""
    t = tournament_with_events["tournament"]
    sv = tournament_with_events["version"]

    report_1 = build_schedule_plan_report(session, t.id, sv.id)
    report_2 = build_schedule_plan_report(session, t.id, sv.id)

    # Convert to dict for comparison
    json_1 = report_1.model_dump()
    json_2 = report_2.model_dump()

    assert json_1 == json_2, "Reports differ between runs with same inputs"

    # Also verify events are sorted by event_id
    event_ids = [e.event_id for e in report_1.events]
    assert event_ids == sorted(event_ids), "Events not sorted by event_id"

    # Verify errors are sorted by (code, event_id, message)
    if report_1.blocking_errors:
        error_keys = [(e.code, e.event_id, e.message) for e in report_1.blocking_errors]
        assert error_keys == sorted(error_keys), "Blocking errors not in stable order"

    if report_1.warnings:
        warning_keys = [(e.code, e.event_id, e.message) for e in report_1.warnings]
        assert warning_keys == sorted(warning_keys), "Warnings not in stable order"

    # Verify JSON serialization round-trips identically
    json_str_1 = report_1.model_dump_json(indent=2)
    json_str_2 = report_2.model_dump_json(indent=2)
    assert json_str_1 == json_str_2, "JSON serialization differs"


# ============================================================================
# Test 6: API Endpoint Tests
# ============================================================================


def test_plan_report_endpoint_no_version(client, session: Session, tournament_with_events):
    """GET /api/tournaments/{id}/schedule/plan-report returns valid report."""
    t = tournament_with_events["tournament"]

    response = client.get(f"/api/tournaments/{t.id}/schedule/plan-report")
    assert response.status_code == 200

    data = response.json()
    assert data["tournament_id"] == t.id
    assert data["ok"] is True
    assert data["schedule_version_id"] is None
    assert len(data["events"]) == 2
    assert data["totals"]["events"] == 2
    assert data["totals"]["matches_total"] > 0


def test_plan_report_endpoint_with_version(client, session: Session, tournament_with_events):
    """GET /api/tournaments/{id}/schedule/versions/{vid}/plan-report returns full report."""
    t = tournament_with_events["tournament"]
    sv = tournament_with_events["version"]

    response = client.get(f"/api/tournaments/{t.id}/schedule/versions/{sv.id}/plan-report")
    assert response.status_code == 200

    data = response.json()
    assert data["tournament_id"] == t.id
    assert data["schedule_version_id"] == sv.id
    assert data["version_status"] == "draft"
    assert data["ok"] is True
    assert len(data["blocking_errors"]) == 0
    assert len(data["events"]) == 2

    # Verify event structure
    event_a = next(e for e in data["events"] if e["name"] == "Mixed 8")
    assert event_a["waterfall"]["rounds"] == 1
    assert event_a["waterfall"]["r1_matches"] == 4
    assert event_a["pools"]["pool_count"] == 2
    assert event_a["pools"]["pool_size"] == 4
    assert event_a["inventory"]["expected_total"] == event_a["inventory"]["actual_total"]


def test_plan_report_endpoint_version_not_found(client, session: Session, tournament_with_events):
    """Plan report with non-existent version → E_VERSION_NOT_FOUND."""
    t = tournament_with_events["tournament"]

    response = client.get(f"/api/tournaments/{t.id}/schedule/versions/99999/plan-report")
    assert response.status_code == 200

    data = response.json()
    assert data["ok"] is False
    error_codes = [e["code"] for e in data["blocking_errors"]]
    assert "E_VERSION_NOT_FOUND" in error_codes


def test_plan_report_endpoint_tournament_not_found(client, session: Session):
    """Plan report for non-existent tournament."""
    response = client.get("/api/tournaments/99999/schedule/plan-report")
    assert response.status_code == 200

    data = response.json()
    assert data["ok"] is False
    error_codes = [e["code"] for e in data["blocking_errors"]]
    assert "E_TOURNAMENT_NOT_FOUND" in error_codes
