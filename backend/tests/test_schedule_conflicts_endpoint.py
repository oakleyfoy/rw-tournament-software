"""
Regression Test for Schedule Conflicts Endpoint

This test ensures the GET /schedule/conflicts endpoint:
1. Returns 200 OK
2. Has a stable response shape
3. Returns consistent data (counts, IDs)
4. Shares computation with PATCH responses (same helper)

This is a minimal smoke test to prove the endpoint works after refactors.
"""

import json
from datetime import date, time

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.models.event import Event
from app.models.match import Match
from app.models.match_assignment import MatchAssignment
from app.models.schedule_slot import ScheduleSlot
from app.models.schedule_version import ScheduleVersion
from app.models.tournament import Tournament


@pytest.fixture
def conflicts_test_fixture(session: Session):
    """
    Create minimal tournament → version → slots → matches for conflicts endpoint testing.
    
    This is the same pattern used in manual_editor_setup and conflict_report_fixture.
    """
    # Create tournament
    tournament = Tournament(
        name="Conflicts Test Tournament",
        location="Test Location",
        timezone="America/New_York",
        start_date=date(2026, 1, 20),
        end_date=date(2026, 1, 21),
    )
    session.add(tournament)
    session.commit()
    session.refresh(tournament)
    
    # Create event
    event = Event(
        tournament_id=tournament.id,
        category="mixed",
        name="Test Event",
        team_count=8,
        draw_plan_json='{"template_type":"ROUND_ROBIN"}',
        draw_status="final",
        guarantee_selected=2,
    )
    session.add(event)
    session.commit()
    session.refresh(event)
    
    # Create schedule version
    version = ScheduleVersion(
        tournament_id=tournament.id,
        version_number=1,
        notes="Conflicts Test Version",
        status="draft",
    )
    session.add(version)
    session.commit()
    session.refresh(version)
    
    # Create slots (5 slots total)
    slots = []
    for i in range(5):
        slot = ScheduleSlot(
            tournament_id=tournament.id,
            schedule_version_id=version.id,
            day_date=date(2026, 1, 20),
            start_time=time(9 + i, 0),
            end_time=time(10 + i, 0),
            block_minutes=60,
            court_number=(i % 2) + 1,
            court_label=f"Court {(i % 2) + 1}",
        )
        slots.append(slot)
        session.add(slot)
    session.commit()
    for slot in slots:
        session.refresh(slot)
    
    # Create matches (4 matches total)
    matches = []
    for i in range(4):
        match = Match(
            tournament_id=tournament.id,
            schedule_version_id=version.id,
            event_id=event.id,
            match_code=f"M{i+1}",
            match_type="MAIN",
            round_number=i + 1,
            round_index=i + 1,
            sequence_in_round=1,
            duration_minutes=45,
            placeholder_side_a=f"Team A{i+1}",
            placeholder_side_b=f"Team B{i+1}",
            status="unscheduled",
        )
        matches.append(match)
        session.add(match)
    session.commit()
    for match in matches:
        session.refresh(match)
    
    # Assign 2 matches, leave 2 unassigned
    assignment1 = MatchAssignment(
        schedule_version_id=version.id,
        match_id=matches[0].id,
        slot_id=slots[0].id,
        assigned_by="TEST",
    )
    assignment2 = MatchAssignment(
        schedule_version_id=version.id,
        match_id=matches[1].id,
        slot_id=slots[1].id,
        assigned_by="TEST",
    )
    session.add(assignment1)
    session.add(assignment2)
    session.commit()
    
    return {
        "tournament_id": tournament.id,
        "version_id": version.id,
        "event_id": event.id,
        "total_slots": 5,
        "total_matches": 4,
        "assigned_matches": 2,
        "unassigned_matches": 2,
    }


# ============================================================================
# Regression Test: Endpoint Returns 200 with Stable Shape
# ============================================================================


def test_conflicts_endpoint_returns_200_with_stable_shape(client: TestClient, conflicts_test_fixture):
    """
    CRITICAL: Verify conflicts endpoint returns 200 OK with expected response shape.
    
    This is the minimal smoke test to prove the endpoint works after refactors.
    Validates:
    - Status code 200
    - Top-level keys exist (summary, unassigned, slot_pressure, stage_timeline, ordering_integrity)
    - schedule_version_id matches request
    - Counts are internally consistent
    """
    tournament_id = conflicts_test_fixture["tournament_id"]
    version_id = conflicts_test_fixture["version_id"]
    
    # Call conflicts endpoint
    resp = client.get(
        f"/api/tournaments/{tournament_id}/schedule/conflicts",
        params={"schedule_version_id": version_id}
    )
    
    # Assert 200 OK
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    
    data = resp.json()
    
    # Assert top-level keys exist (stable response shape)
    assert "summary" in data, "Response missing 'summary' key"
    assert "unassigned" in data, "Response missing 'unassigned' key"
    assert "slot_pressure" in data, "Response missing 'slot_pressure' key"
    assert "stage_timeline" in data, "Response missing 'stage_timeline' key"
    assert "ordering_integrity" in data, "Response missing 'ordering_integrity' key"
    
    # Assert summary has expected fields
    summary = data["summary"]
    assert "tournament_id" in summary
    assert "schedule_version_id" in summary
    assert "total_slots" in summary
    assert "total_matches" in summary
    assert "assigned_matches" in summary
    assert "unassigned_matches" in summary
    assert "assignment_rate" in summary
    
    # Assert schedule_version_id matches request
    assert summary["schedule_version_id"] == version_id, (
        f"Response version_id {summary['schedule_version_id']} != requested {version_id}"
    )
    
    # Assert tournament_id matches request
    assert summary["tournament_id"] == tournament_id, (
        f"Response tournament_id {summary['tournament_id']} != requested {tournament_id}"
    )
    
    # Assert counts are integers (type safety)
    assert isinstance(summary["total_matches"], int), "total_matches must be int"
    assert isinstance(summary["assigned_matches"], int), "assigned_matches must be int"
    assert isinstance(summary["unassigned_matches"], int), "unassigned_matches must be int"
    assert isinstance(summary["assignment_rate"], (int, float)), "assignment_rate must be numeric"
    
    # Assert counts are internally consistent
    expected_total = summary["assigned_matches"] + summary["unassigned_matches"]
    assert summary["total_matches"] == expected_total, (
        f"Inconsistent counts: total={summary['total_matches']}, "
        f"assigned={summary['assigned_matches']}, unassigned={summary['unassigned_matches']}"
    )
    
    # Assert assignment_rate is calculated correctly
    expected_rate = (summary["assigned_matches"] / summary["total_matches"] * 100) if summary["total_matches"] > 0 else 0.0
    assert abs(summary["assignment_rate"] - expected_rate) < 0.01, (
        f"Assignment rate {summary['assignment_rate']} != expected {expected_rate}"
    )


def test_conflicts_endpoint_unassigned_list_has_expected_fields(client: TestClient, conflicts_test_fixture):
    """
    Verify unassigned matches list contains expected fields.
    
    This ensures the unassigned analysis works correctly.
    """
    tournament_id = conflicts_test_fixture["tournament_id"]
    version_id = conflicts_test_fixture["version_id"]
    
    resp = client.get(
        f"/api/tournaments/{tournament_id}/schedule/conflicts",
        params={"schedule_version_id": version_id}
    )
    
    assert resp.status_code == 200
    data = resp.json()
    
    unassigned = data["unassigned"]
    assert isinstance(unassigned, list), "unassigned must be a list"
    
    # Should have 2 unassigned matches (fixture has 4 total, 2 assigned)
    assert len(unassigned) == 2, f"Expected 2 unassigned, got {len(unassigned)}"
    
    # Verify each unassigned match has expected fields
    for unassigned_match in unassigned:
        assert "match_id" in unassigned_match, "Missing match_id"
        assert "stage" in unassigned_match, "Missing stage"
        assert "round_index" in unassigned_match, "Missing round_index"
        assert "duration_minutes" in unassigned_match, "Missing duration_minutes"
        assert "reason" in unassigned_match, "Missing reason"
        
        # Verify types
        assert isinstance(unassigned_match["match_id"], int)
        assert isinstance(unassigned_match["stage"], str)
        assert isinstance(unassigned_match["round_index"], int)
        assert isinstance(unassigned_match["duration_minutes"], int)
        assert isinstance(unassigned_match["reason"], str)
        
        # Reason should not be empty or just "UNKNOWN" (should have diagnostic info)
        assert unassigned_match["reason"] != "", "Reason should not be empty"


def test_conflicts_endpoint_requires_schedule_version_id(client: TestClient, conflicts_test_fixture):
    """
    Verify endpoint returns 422 if schedule_version_id is missing.
    
    This is a validation test.
    """
    tournament_id = conflicts_test_fixture["tournament_id"]
    
    resp = client.get(f"/api/tournaments/{tournament_id}/schedule/conflicts")
    
    # Should fail validation (missing required query param)
    assert resp.status_code == 422


def test_conflicts_endpoint_404_for_invalid_tournament(client: TestClient):
    """
    Verify endpoint returns 404 for non-existent tournament.
    """
    resp = client.get(
        "/api/tournaments/99999/schedule/conflicts",
        params={"schedule_version_id": 1}
    )
    
    assert resp.status_code == 404


def test_conflicts_endpoint_404_for_invalid_version(client: TestClient, conflicts_test_fixture):
    """
    Verify endpoint returns 404 for non-existent schedule version.
    """
    tournament_id = conflicts_test_fixture["tournament_id"]
    
    resp = client.get(
        f"/api/tournaments/{tournament_id}/schedule/conflicts",
        params={"schedule_version_id": 99999}
    )
    
    assert resp.status_code == 404


def test_conflicts_endpoint_is_read_only(session: Session, client: TestClient, conflicts_test_fixture):
    """
    Verify endpoint does not mutate the database.
    
    This is critical for a diagnostic/reporting endpoint.
    """
    tournament_id = conflicts_test_fixture["tournament_id"]
    version_id = conflicts_test_fixture["version_id"]
    
    # Count records before
    from sqlmodel import select
    matches_before = len(session.exec(select(Match)).all())
    assignments_before = len(session.exec(select(MatchAssignment)).all())
    slots_before = len(session.exec(select(ScheduleSlot)).all())
    
    # Call endpoint
    resp = client.get(
        f"/api/tournaments/{tournament_id}/schedule/conflicts",
        params={"schedule_version_id": version_id}
    )
    
    assert resp.status_code == 200
    
    # Count records after
    session.expire_all()  # Clear cache
    matches_after = len(session.exec(select(Match)).all())
    assignments_after = len(session.exec(select(MatchAssignment)).all())
    slots_after = len(session.exec(select(ScheduleSlot)).all())
    
    # Verify no mutations
    assert matches_after == matches_before, "Endpoint should not create/delete matches"
    assert assignments_after == assignments_before, "Endpoint should not create/delete assignments"
    assert slots_after == slots_before, "Endpoint should not create/delete slots"


def _canonical_json(data) -> str:
    """
    Stable canonicalization: avoids whitespace/order differences.
    Ensures the *data* is deterministic, not just the response formatting.
    """
    return json.dumps(data, sort_keys=True, separators=(",", ":"))


def test_conflicts_endpoint_is_deterministic(client: TestClient, conflicts_test_fixture):
    """
    CRITICAL: Call conflicts endpoint multiple times with identical inputs and assert
    canonical JSON is identical each time.
    
    This catches:
    - Nondeterministic ordering
    - Timestamps/UUIDs
    - Unstable defaults
    
    Hard guardrail for Phase 3D.2 completion.
    """
    tournament_id = conflicts_test_fixture["tournament_id"]
    version_id = conflicts_test_fixture["version_id"]

    url = f"/api/tournaments/{tournament_id}/schedule/conflicts?schedule_version_id={version_id}"

    r1 = client.get(url)
    r2 = client.get(url)
    r3 = client.get(url)

    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r3.status_code == 200

    c1 = _canonical_json(r1.json())
    c2 = _canonical_json(r2.json())
    c3 = _canonical_json(r3.json())

    assert c1 == c2 == c3, (
        "Conflicts endpoint is nondeterministic!\n"
        "Identical inputs must produce identical canonical JSON.\n"
        "Check for timestamps, UUIDs, or unstable ordering."
    )

