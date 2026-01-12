"""
Regression Tests for Test Infrastructure
==========================================

These tests lock in critical infrastructure invariants to prevent
CI failures from test harness issues (StaticPool, overrides, metadata).

DO NOT DELETE OR SKIP THESE TESTS - they catch infrastructure regressions
that can cause cryptic CI failures like "no such table" or wrong engine usage.
"""

from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.models.tournament import Tournament


# ============================================================================
# Test 1: CI Guardrail - Verify App Uses Overridden Test Session
# ============================================================================


def test_app_uses_overridden_test_session(client: TestClient, session: Session):
    """
    CRITICAL: Verify the app uses the overridden test session, not production engine.

    If this fails, it means:
    - Dependency override is not set correctly
    - Override timing is wrong (set after TestClient creation)
    - App is instantiating its own engine during requests

    Failure symptom: "App did not use overridden test session"
    """
    # Mark the test session with a sentinel
    session.info["test_engine_marker"] = True

    # Create a tournament via API (forces app to use get_session dependency)
    tournament_data = {
        "name": "Sentinel Test Tournament",
        "location": "Test Location",
        "timezone": "America/New_York",
        "start_date": date(2026, 1, 15).isoformat(),
        "end_date": date(2026, 1, 17).isoformat(),
    }
    response = client.post("/api/tournaments", json=tournament_data)
    assert response.status_code == 201, f"Failed to create tournament: {response.text}"

    # Verify the tournament exists in our test session (proves same engine)
    tournament = session.exec(select(Tournament).where(Tournament.name == "Sentinel Test Tournament")).first()
    assert tournament is not None, (
        "App did not use overridden test session - tournament not found in test DB. "
        "This means the app is using a different engine (likely production). "
        "Check conftest.py: ensure app.dependency_overrides is set BEFORE TestClient creation."
    )


# ============================================================================
# Test 2: Regression Test for "no such table: tournament" Failures
# ============================================================================


def test_no_such_table_regression(client: TestClient):
    """
    CRITICAL: Catch "no such table" errors that break CI.

    This test validates:
    - SQLModel.metadata.create_all() was called
    - All models were imported before create_all()
    - Tables exist in the test database
    - Engine/session setup is correct

    Failure symptom: "no such table: tournament" or similar
    """
    # Immediately hit an endpoint that queries Tournament table
    tournament_data = {
        "name": "Table Existence Test",
        "location": "Test Location",
        "timezone": "America/New_York",
        "start_date": date(2026, 1, 15).isoformat(),
        "end_date": date(2026, 1, 17).isoformat(),
    }
    response = client.post("/api/tournaments", json=tournament_data)

    # If tables don't exist, this will fail with "no such table"
    assert response.status_code == 201, (
        f"Failed to create tournament (likely 'no such table' error): {response.text}. "
        "This means tables were not created. Check conftest.py: "
        "- Ensure all models are imported before SQLModel.metadata.create_all() "
        "- Ensure create_all(test_engine) is called in session fixture"
    )

    # Verify response has expected structure
    data = response.json()
    assert "id" in data, f"Response missing 'id' field: {data}"
    assert data["name"] == "Table Existence Test"


# ============================================================================
# Test 3: Multi-Request Persistence Test (StaticPool Correctness)
# ============================================================================


def test_staticpool_persistence_across_requests(client: TestClient):
    """
    CRITICAL: Verify StaticPool keeps data persistent across multiple requests.

    With StaticPool, all sessions share the same in-memory database.
    Data created in one request MUST be visible in subsequent requests.

    If this fails:
    - StaticPool is not configured correctly
    - Each request is getting a different database
    - Test engine is being recreated per request

    Failure symptom: Second GET returns 404 (tournament doesn't exist)
    """
    # REQUEST 1: Create a tournament
    tournament_data = {
        "name": "Persistence Test Tournament",
        "location": "Test Location",
        "timezone": "America/New_York",
        "start_date": date(2026, 1, 15).isoformat(),
        "end_date": date(2026, 1, 17).isoformat(),
    }
    create_response = client.post("/api/tournaments", json=tournament_data)
    assert create_response.status_code == 201, f"Failed to create: {create_response.text}"
    created_data = create_response.json()
    tournament_id = created_data["id"]

    # REQUEST 2: Retrieve the same tournament (different request, same DB)
    get_response = client.get(f"/api/tournaments/{tournament_id}")
    assert get_response.status_code == 200, (
        f"Tournament not found in second request (ID: {tournament_id}). "
        "This means StaticPool is not working - each request gets a different database. "
        "Check conftest.py: ensure test_engine uses poolclass=StaticPool"
    )

    retrieved_data = get_response.json()
    assert retrieved_data["id"] == tournament_id
    assert retrieved_data["name"] == "Persistence Test Tournament"

    # REQUEST 3: List all tournaments (must include the one we created)
    list_response = client.get("/api/tournaments")
    assert list_response.status_code == 200
    tournaments = list_response.json()
    tournament_ids = [t["id"] for t in tournaments]
    assert tournament_id in tournament_ids, (
        f"Tournament {tournament_id} not in list. StaticPool persistence broken."
    )


# ============================================================================
# Test 4: Determinism Test for Auto-Assign Ordering
# ============================================================================


@pytest.fixture
def determinism_fixture(client: TestClient, session: Session):
    """Create a fixed tournament setup for determinism testing"""
    import json

    # Create tournament
    tournament_data = {
        "name": "Determinism Test Tournament",
        "location": "Test Location",
        "timezone": "America/New_York",
        "start_date": date(2026, 1, 15).isoformat(),
        "end_date": date(2026, 1, 17).isoformat(),
    }
    t_resp = client.post("/api/tournaments", json=tournament_data)
    assert t_resp.status_code == 201
    tournament = t_resp.json()

    # Create event
    event_data = {"category": "mixed", "name": "Test Event", "team_count": 4}
    e_resp = client.post(f"/api/tournaments/{tournament['id']}/events", json=event_data)
    assert e_resp.status_code == 201
    event = e_resp.json()

    # Finalize event (required for match generation)
    event_update = {
        "draw_plan_json": json.dumps({"template_type": "CANONICAL_4", "wf_rounds": 0, "guarantee": 2}),
        "draw_status": "final",
        "wf_block_minutes": 60,
        "standard_block_minutes": 120,
        "guarantee_selected": 2,
    }
    u_resp = client.put(f"/api/events/{event['id']}", json=event_update)
    assert u_resp.status_code == 200
    event = u_resp.json()

    # Create schedule version
    v_resp = client.post(f"/api/tournaments/{tournament['id']}/schedule/versions", json={"notes": "Test"})
    assert v_resp.status_code == 201
    version = v_resp.json()

    return {"tournament": tournament, "event": event, "version": version}


@pytest.mark.skip(reason="Requires full tournament setup - will be expanded in Phase 3C")
def test_auto_assign_determinism(client: TestClient, determinism_fixture):
    """
    CRITICAL: Verify auto-assign produces deterministic results.

    Same inputs MUST produce same outputs (same match → slot mappings).

    This test is skipped for now but serves as a template for Phase 3C testing.
    When implementing V2 constraints, uncomment and ensure:
    - Tournament days are properly configured
    - Events have teams
    - Full slot/match generation workflow is tested

    If this fails:
    - Assignment logic has non-deterministic behavior
    - Random number generation without seed
    - Dictionary/set iteration order issues
    - Timestamp-based sorting without stable tie-breaking

    Failure symptom: Different assignments between runs
    """
    # TODO: Implement full determinism test in Phase 3C
    pass


# ============================================================================
# Test 5: Bad Response Shape Helper (Prevents KeyError Regressions)
# ============================================================================


def assert_response_shape(response, expected_status, required_keys, endpoint_name):
    """
    Helper function to validate API response shape and provide actionable errors.

    Prevents KeyError regressions by checking:
    1. Status code is expected
    2. Response is valid JSON
    3. Required keys exist

    Usage:
        response = client.post("/api/tournaments", json=data)
        assert_response_shape(response, 201, ["id", "name"], "POST /api/tournaments")
    """
    # Check status code first
    assert response.status_code == expected_status, (
        f"{endpoint_name} returned {response.status_code} (expected {expected_status}). "
        f"Response: {response.text}"
    )

    # Parse JSON
    try:
        data = response.json()
    except Exception as e:
        pytest.fail(f"{endpoint_name} returned invalid JSON: {e}. Response: {response.text}")

    # Check required keys
    missing_keys = [key for key in required_keys if key not in data]
    if missing_keys:
        pytest.fail(
            f"{endpoint_name} response missing required keys: {missing_keys}. "
            f"Response: {data}. "
            "This causes KeyError in client code."
        )

    return data


def test_response_shape_helper_on_tournament_create(client: TestClient):
    """
    Demonstrate using assert_response_shape helper to prevent KeyError regressions.

    This pattern should be used in all endpoint tests to catch response shape issues.
    """
    tournament_data = {
        "name": "Shape Test Tournament",
        "location": "Test Location",
        "timezone": "America/New_York",
        "start_date": date(2026, 1, 15).isoformat(),
        "end_date": date(2026, 1, 17).isoformat(),
    }
    response = client.post("/api/tournaments", json=tournament_data)

    # Use helper - will fail with actionable message if shape is wrong
    data = assert_response_shape(
        response, expected_status=201, required_keys=["id", "name", "location"], endpoint_name="POST /api/tournaments"
    )

    # Now safe to access keys
    assert data["id"] is not None
    assert data["name"] == "Shape Test Tournament"


def test_response_shape_helper_on_team_create(client: TestClient):
    """
    Test the helper on team creation endpoint (which had KeyError: 'id' issues).
    """
    # Create a tournament and event first
    tournament_data = {
        "name": "Team Shape Test Tournament",
        "location": "Test Location",
        "timezone": "America/New_York",
        "start_date": date(2026, 1, 15).isoformat(),
        "end_date": date(2026, 1, 17).isoformat(),
    }
    t_resp = client.post("/api/tournaments", json=tournament_data)
    assert t_resp.status_code == 201
    tournament = t_resp.json()

    event_data = {"category": "mixed", "name": "Test Event", "team_count": 4}
    e_resp = client.post(f"/api/tournaments/{tournament['id']}/events", json=event_data)
    assert e_resp.status_code == 201
    event = e_resp.json()

    # Now test team creation with helper
    team_data = {"name": "Test Team", "seed": 1, "rating": 1500.0}
    response = client.post(f"/api/events/{event['id']}/teams", json=team_data)

    # Use helper - catches the KeyError: 'id' regression
    data = assert_response_shape(
        response,
        expected_status=201,
        required_keys=["id", "name", "event_id"],
        endpoint_name=f"POST /api/events/{event['id']}/teams",
    )

    # Now safe to use
    assert data["id"] is not None
    assert data["name"] == "Test Team"
    assert data["event_id"] == event["id"]

