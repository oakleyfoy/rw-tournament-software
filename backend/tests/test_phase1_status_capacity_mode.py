"""Regression: Phase 1 Total Court Hours Available must be computed from current mode.
Switching Simple <-> Advanced must not carry over stale capacity from the other mode."""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def tournament_one_day(client: TestClient):
    """Tournament with a single day for predictable capacity."""
    response = client.post(
        "/api/tournaments",
        json={
            "name": "Capacity Mode Test",
            "location": "Test",
            "timezone": "America/New_York",
            "start_date": "2026-01-15",
            "end_date": "2026-01-15",
        },
    )
    assert response.status_code in (200, 201)
    return response.json()


def test_phase1_status_switching_modes_changes_totals(tournament_one_day, client: TestClient):
    """Flip between Simple and Advanced; phase1-status must reflect current mode (no stale carryover)."""
    tid = tournament_one_day["id"]

    # Simple mode: 1 day, 10 courts × 10 hours = 6000 court-minutes
    days_resp = client.get(f"/api/tournaments/{tid}/days")
    assert days_resp.status_code == 200
    days = days_resp.json()
    assert len(days) >= 1
    client.put(
        f"/api/tournaments/{tid}/days",
        json={
            "days": [
                {
                    "date": days[0]["date"],
                    "is_active": True,
                    "start_time": "08:00:00",
                    "end_time": "18:00:00",
                    "courts_available": 10,
                },
            ]
        },
    )

    # Add event so is_ready can be true when capacity > 0
    client.post(
        f"/api/tournaments/{tid}/events",
        json={"category": "mixed", "name": "Mixed", "team_count": 8},
    )

    # Ensure Simple mode
    client.put(f"/api/tournaments/{tid}", json={"use_time_windows": False})

    # Simple total: 10 * (10*60) = 6000
    simple_expected = 10 * 10 * 60
    resp = client.get(f"/api/tournaments/{tid}/phase1-status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["summary"]["total_court_minutes"] == simple_expected, (
        f"Simple mode should be {simple_expected}, got {data['summary']['total_court_minutes']}"
    )

    # Add time window: 1 window, 10 courts × 5 hours = 3000 court-minutes (Advanced total)
    client.post(
        f"/api/tournaments/{tid}/time-windows",
        json={
            "day_date": days[0]["date"],
            "start_time": "09:00:00",
            "end_time": "14:00:00",
            "courts_available": 10,
            "block_minutes": 60,
            "is_active": True,
        },
    )

    # Switch to Advanced
    client.put(f"/api/tournaments/{tid}", json={"use_time_windows": True})

    # Advanced total: 10 * (5*60) = 3000
    advanced_expected = 10 * 5 * 60
    resp = client.get(f"/api/tournaments/{tid}/phase1-status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["summary"]["total_court_minutes"] == advanced_expected, (
        f"Advanced mode should be {advanced_expected}, got {data['summary']['total_court_minutes']}"
    )

    # Switch back to Simple → must show simple total again (no 3000 carryover)
    client.put(f"/api/tournaments/{tid}", json={"use_time_windows": False})
    resp = client.get(f"/api/tournaments/{tid}/phase1-status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["summary"]["total_court_minutes"] == simple_expected, (
        f"Back to Simple should be {simple_expected}, got {data['summary']['total_court_minutes']}"
    )


def test_advanced_capacity_ignores_simple_fields(client: TestClient):
    """
    Advanced mode: returned capacity == sum(time windows) only.
    Days/Courts are populated but must NOT be used (no Simple math).
    """
    # Create tournament with one day
    r = client.post(
        "/api/tournaments",
        json={
            "name": "Advanced Ignores Simple",
            "location": "Test",
            "timezone": "America/New_York",
            "start_date": "2026-02-01",
            "end_date": "2026-02-01",
        },
    )
    assert r.status_code in (200, 201)
    tid = r.json()["id"]

    # Populate Simple path: 1 day, 20 courts × 12 hours = 14400 court-minutes
    days_r = client.get(f"/api/tournaments/{tid}/days")
    assert days_r.status_code == 200
    days = days_r.json()
    assert len(days) >= 1
    client.put(
        f"/api/tournaments/{tid}/days",
        json={
            "days": [
                {
                    "date": days[0]["date"],
                    "is_active": True,
                    "start_time": "06:00:00",
                    "end_time": "18:00:00",
                    "courts_available": 20,
                },
            ]
        },
    )

    # Add event
    client.post(
        f"/api/tournaments/{tid}/events",
        json={"category": "mixed", "name": "Mixed", "team_count": 8},
    )

    # Define time windows: 2 windows, total = (3h*4 courts) + (2h*5 courts) = 720 + 600 = 1320
    client.post(
        f"/api/tournaments/{tid}/time-windows",
        json={
            "day_date": days[0]["date"],
            "start_time": "09:00:00",
            "end_time": "12:00:00",
            "courts_available": 4,
            "block_minutes": 60,
            "is_active": True,
        },
    )
    client.post(
        f"/api/tournaments/{tid}/time-windows",
        json={
            "day_date": days[0]["date"],
            "start_time": "13:00:00",
            "end_time": "15:00:00",
            "courts_available": 5,
            "block_minutes": 60,
            "is_active": True,
        },
    )

    # Enable Advanced mode
    client.put(f"/api/tournaments/{tid}", json={"use_time_windows": True})

    # Phase 1 must return sum(time windows) only, NOT Simple (14400)
    windows_total = (3 * 60 * 4) + (2 * 60 * 5)  # 720 + 600 = 1320
    resp = client.get(f"/api/tournaments/{tid}/phase1-status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["summary"]["total_court_minutes"] == windows_total, (
        f"Advanced must use time windows only: expected {windows_total}, got {data['summary']['total_court_minutes']}"
    )
    assert data["summary"]["total_court_minutes"] != 14400, (
        "Simple math (days × courts × hours) must NOT be used when Advanced"
    )


def test_advanced_mode_with_zero_windows_returns_error(client: TestClient):
    """Guard: Advanced mode with no active time windows must return error (no silent fallback)."""
    r = client.post(
        "/api/tournaments",
        json={
            "name": "Advanced No Windows",
            "location": "Test",
            "timezone": "America/New_York",
            "start_date": "2026-02-01",
            "end_date": "2026-02-01",
        },
    )
    assert r.status_code in (200, 201)
    tid = r.json()["id"]
    client.post(
        f"/api/tournaments/{tid}/events",
        json={"category": "mixed", "name": "Mixed", "team_count": 8},
    )
    client.put(f"/api/tournaments/{tid}", json={"use_time_windows": True})

    resp = client.get(f"/api/tournaments/{tid}/phase1-status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["is_ready"] is False
    assert any("active time window" in e.lower() for e in data["errors"])
