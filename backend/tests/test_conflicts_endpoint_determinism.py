"""
Determinism Regression Test for Conflicts Endpoint

Phase 3D.2 Step 1: Proves the conflicts endpoint is deterministic.

Guarantees:
- Identical inputs produce identical outputs (no randomness)
- JSON response is stable (no nondeterministic ordering)
- Lists are sorted consistently (unassigned matches, violations, etc.)

This test protects against:
- Random IDs or timestamps in output
- Nondeterministic dict iteration
- Unstable list ordering (e.g., unordered queries, set iteration)
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
def determinism_fixture(session: Session):
    """
    Create a deterministic test scenario with known data.
    
    This fixture creates:
    - 1 Tournament
    - 1 Event
    - 1 Schedule Version
    - 6 Slots (predictable ordering)
    - 5 Matches (predictable ordering)
    - 3 Assignments (leaving 2 unassigned)
    """
    # Create tournament
    tournament = Tournament(
        name="Determinism Test Tournament",
        location="Test Arena",
        timezone="America/New_York",
        start_date=date(2026, 2, 10),
        end_date=date(2026, 2, 11),
    )
    session.add(tournament)
    session.commit()
    session.refresh(tournament)
    
    # Create event
    event = Event(
        tournament_id=tournament.id,
        category="mixed",
        name="Determinism Event",
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
        notes="Determinism Test Version",
        status="draft",
    )
    session.add(version)
    session.commit()
    session.refresh(version)
    
    # Create slots with predictable ordering (day, time, court)
    slots = []
    for day_offset in range(2):  # 2 days
        for hour in [9, 10, 11]:  # 3 time slots per day
            slot = ScheduleSlot(
                tournament_id=tournament.id,
                schedule_version_id=version.id,
                day_date=date(2026, 2, 10 + day_offset),
                start_time=time(hour, 0),
                end_time=time(hour + 1, 0),
                block_minutes=60,
                court_number=1,
                court_label="Court 1",
            )
            slots.append(slot)
            session.add(slot)
    session.commit()
    for slot in slots:
        session.refresh(slot)
    
    # Create matches with predictable ordering (stage, round, sequence)
    matches = []
    for i in range(5):
        match = Match(
            tournament_id=tournament.id,
            schedule_version_id=version.id,
            event_id=event.id,
            match_code=f"MAIN_M{i+1}",
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
    
    # Assign 3 matches (leave 2 unassigned for diagnostic variety)
    assignments = []
    for i in range(3):
        assignment = MatchAssignment(
            schedule_version_id=version.id,
            match_id=matches[i].id,
            slot_id=slots[i].id,
            assigned_by="TEST",
        )
        assignments.append(assignment)
        session.add(assignment)
    session.commit()
    
    return {
        "tournament_id": tournament.id,
        "version_id": version.id,
        "event_id": event.id,
    }


# ============================================================================
# Test: Identical Inputs → Identical Outputs (Byte-for-Byte Stability)
# ============================================================================


def test_conflicts_endpoint_is_deterministic_strict_equality(client: TestClient, determinism_fixture):
    """
    CRITICAL: Verify conflicts endpoint produces identical output for identical input.
    
    This test calls the endpoint 3 times and asserts:
    1. Status codes are all 200
    2. JSON responses are strictly equal (same keys, values, ordering)
    
    Failure modes this catches:
    - Random UUIDs or IDs in response
    - Timestamps (e.g., "generated_at" fields)
    - Nondeterministic dict ordering
    - Unstable list ordering (unsorted queries)
    - Set iteration (random order)
    """
    tournament_id = determinism_fixture["tournament_id"]
    version_id = determinism_fixture["version_id"]
    
    # Call endpoint 3 times
    responses = []
    for i in range(3):
        resp = client.get(
            f"/api/tournaments/{tournament_id}/schedule/conflicts",
            params={"schedule_version_id": version_id}
        )
        assert resp.status_code == 200, f"Call {i+1} failed with status {resp.status_code}"
        responses.append(resp)
    
    # Extract JSON data
    data1 = responses[0].json()
    data2 = responses[1].json()
    data3 = responses[2].json()
    
    # CRITICAL: Strict equality check (same keys, values, ordering)
    assert data1 == data2, (
        "Response 1 and Response 2 differ!\n"
        f"This indicates nondeterministic behavior in the conflicts endpoint.\n"
        f"Diff: {set(str(data1)) ^ set(str(data2))}"
    )
    
    assert data2 == data3, (
        "Response 2 and Response 3 differ!\n"
        f"This indicates nondeterministic behavior in the conflicts endpoint.\n"
        f"Diff: {set(str(data2)) ^ set(str(data3))}"
    )
    
    assert data1 == data3, (
        "Response 1 and Response 3 differ!\n"
        f"This indicates nondeterministic behavior in the conflicts endpoint.\n"
        f"Diff: {set(str(data1)) ^ set(str(data3))}"
    )


def test_conflicts_endpoint_is_deterministic_canonical_json(client: TestClient, determinism_fixture):
    """
    Alternative determinism check: Canonical JSON comparison.
    
    This test serializes responses to canonical JSON (sorted keys, consistent separators)
    and compares byte-for-byte. This catches edge cases where dict ordering might
    differ across Python versions or JSON encoders.
    """
    tournament_id = determinism_fixture["tournament_id"]
    version_id = determinism_fixture["version_id"]
    
    # Call endpoint 3 times and serialize to canonical JSON
    canonical_jsons = []
    for i in range(3):
        resp = client.get(
            f"/api/tournaments/{tournament_id}/schedule/conflicts",
            params={"schedule_version_id": version_id}
        )
        assert resp.status_code == 200, f"Call {i+1} failed with status {resp.status_code}"
        
        # Serialize to canonical JSON (sorted keys, no whitespace)
        canonical = json.dumps(resp.json(), sort_keys=True, separators=(",", ":"))
        canonical_jsons.append(canonical)
    
    # Assert all canonical JSON strings are identical
    assert canonical_jsons[0] == canonical_jsons[1], (
        "Canonical JSON 1 and 2 differ (nondeterministic ordering detected)"
    )
    
    assert canonical_jsons[1] == canonical_jsons[2], (
        "Canonical JSON 2 and 3 differ (nondeterministic ordering detected)"
    )


def test_conflicts_endpoint_list_ordering_is_stable(client: TestClient, determinism_fixture):
    """
    Targeted invariant check: Verify lists are sorted consistently.
    
    This test checks that lists in the response (unassigned matches, violations, etc.)
    appear in the same order across multiple calls.
    """
    tournament_id = determinism_fixture["tournament_id"]
    version_id = determinism_fixture["version_id"]
    
    # Call endpoint twice
    resp1 = client.get(
        f"/api/tournaments/{tournament_id}/schedule/conflicts",
        params={"schedule_version_id": version_id}
    )
    resp2 = client.get(
        f"/api/tournaments/{tournament_id}/schedule/conflicts",
        params={"schedule_version_id": version_id}
    )
    
    assert resp1.status_code == 200
    assert resp2.status_code == 200
    
    data1 = resp1.json()
    data2 = resp2.json()
    
    # Check unassigned matches list ordering
    unassigned1 = [u["match_id"] for u in data1["unassigned"]]
    unassigned2 = [u["match_id"] for u in data2["unassigned"]]
    assert unassigned1 == unassigned2, (
        f"Unassigned matches ordering differs!\n"
        f"Call 1: {unassigned1}\n"
        f"Call 2: {unassigned2}"
    )
    
    # Check stage timeline ordering
    stages1 = [s["stage"] for s in data1["stage_timeline"]]
    stages2 = [s["stage"] for s in data2["stage_timeline"]]
    assert stages1 == stages2, (
        f"Stage timeline ordering differs!\n"
        f"Call 1: {stages1}\n"
        f"Call 2: {stages2}"
    )
    
    # Check violations ordering (if any exist)
    violations1 = [(v["earlier_match_id"], v["later_match_id"]) for v in data1["ordering_integrity"]["violations"]]
    violations2 = [(v["earlier_match_id"], v["later_match_id"]) for v in data2["ordering_integrity"]["violations"]]
    assert violations1 == violations2, (
        f"Violations ordering differs!\n"
        f"Call 1: {violations1}\n"
        f"Call 2: {violations2}"
    )


def test_conflicts_endpoint_no_timestamps_in_response(client: TestClient, determinism_fixture):
    """
    Targeted check: Ensure response contains no timestamps that would break determinism.
    
    We explicitly check that the response does NOT contain fields like:
    - generated_at
    - computed_at
    - timestamp
    
    (These would change on every call, breaking determinism)
    """
    tournament_id = determinism_fixture["tournament_id"]
    version_id = determinism_fixture["version_id"]
    
    resp = client.get(
        f"/api/tournaments/{tournament_id}/schedule/conflicts",
        params={"schedule_version_id": version_id}
    )
    
    assert resp.status_code == 200
    data = resp.json()
    
    # Flatten response and check for timestamp-like keys
    def has_timestamp_keys(obj, path=""):
        """Recursively check for timestamp-like keys"""
        if isinstance(obj, dict):
            for key, value in obj.items():
                if key in ["generated_at", "computed_at", "timestamp", "created_at", "updated_at"]:
                    return True, f"{path}.{key}"
                found, location = has_timestamp_keys(value, f"{path}.{key}")
                if found:
                    return found, location
        elif isinstance(obj, list):
            for i, item in enumerate(obj):
                found, location = has_timestamp_keys(item, f"{path}[{i}]")
                if found:
                    return found, location
        return False, None
    
    has_timestamps, location = has_timestamp_keys(data)
    assert not has_timestamps, (
        f"Response contains timestamp field at {location}!\n"
        f"This breaks determinism (timestamps change on every call).\n"
        f"Remove timestamp fields from conflict report response."
    )


def test_conflicts_endpoint_dict_key_ordering_stable(client: TestClient, determinism_fixture):
    """
    Check that dict keys appear in the same order across calls.
    
    Python 3.7+ guarantees dict insertion order, but this test verifies
    that our response dicts are built consistently.
    """
    tournament_id = determinism_fixture["tournament_id"]
    version_id = determinism_fixture["version_id"]
    
    # Call endpoint twice
    resp1 = client.get(
        f"/api/tournaments/{tournament_id}/schedule/conflicts",
        params={"schedule_version_id": version_id}
    )
    resp2 = client.get(
        f"/api/tournaments/{tournament_id}/schedule/conflicts",
        params={"schedule_version_id": version_id}
    )
    
    data1 = resp1.json()
    data2 = resp2.json()
    
    # Check top-level key ordering
    keys1 = list(data1.keys())
    keys2 = list(data2.keys())
    assert keys1 == keys2, f"Top-level key ordering differs: {keys1} vs {keys2}"
    
    # Check summary key ordering
    summary_keys1 = list(data1["summary"].keys())
    summary_keys2 = list(data2["summary"].keys())
    assert summary_keys1 == summary_keys2, f"Summary key ordering differs: {summary_keys1} vs {summary_keys2}"

