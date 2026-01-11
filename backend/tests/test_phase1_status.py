import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def tournament(client: TestClient):
    """Create a tournament for testing"""
    response = client.post(
        "/api/tournaments",
        json={
            "name": "Test Tournament",
            "location": "Test Location",
            "timezone": "America/New_York",
            "start_date": "2026-01-15",
            "end_date": "2026-01-17",
        },
    )
    return response.json()


def test_phase1_status_returns_is_ready_false_until_days_and_events_valid(tournament, client: TestClient):
    """Test that phase1-status returns is_ready=false until days + events are valid"""
    # Initially should not be ready (no events, no courts set)
    response = client.get(f"/api/tournaments/{tournament['id']}/phase1-status")
    assert response.status_code == 200
    status = response.json()
    assert status["is_ready"] is False
    assert len(status["errors"]) > 0
    assert "At least one event is required" in status["errors"]
    assert "Total court minutes must be greater than 0" in status["errors"]

    # Add events but no courts
    client.post(
        f"/api/tournaments/{tournament['id']}/events",
        json={
            "category": "mixed",
            "name": "Mixed Doubles",
            "team_count": 8,
        },
    )

    response = client.get(f"/api/tournaments/{tournament['id']}/phase1-status")
    status = response.json()
    assert status["is_ready"] is False
    assert "Total court minutes must be greater than 0" in status["errors"]

    # Set up courts on days
    days_response = client.get(f"/api/tournaments/{tournament['id']}/days")
    days = days_response.json()

    # Update all days to have courts (deactivate others, activate one with courts)
    update_data = {
        "days": [
            {
                "date": days[0]["date"],
                "is_active": True,
                "start_time": "08:00:00",
                "end_time": "18:00:00",
                "courts_available": 2,
            },
            {"date": days[1]["date"], "is_active": False, "start_time": None, "end_time": None, "courts_available": 0},
            {"date": days[2]["date"], "is_active": False, "start_time": None, "end_time": None, "courts_available": 0},
        ]
    }
    client.put(f"/api/tournaments/{tournament['id']}/days", json=update_data)

    # Now should be ready
    response = client.get(f"/api/tournaments/{tournament['id']}/phase1-status")
    status = response.json()
    assert status["is_ready"] is True
    assert len(status["errors"]) == 0
    assert status["summary"]["active_days"] == 1
    assert status["summary"]["total_court_minutes"] > 0
    assert status["summary"]["events_count"] == 1


def test_phase1_status_calculates_court_minutes_correctly(tournament, client: TestClient):
    """Test that phase1-status calculates total court minutes correctly"""
    # Set up days with courts
    days_response = client.get(f"/api/tournaments/{tournament['id']}/days")
    days = days_response.json()

    # Day 1: 8:00-18:00 (10 hours = 600 min) * 2 courts = 1200 minutes
    # Day 2: 9:00-17:00 (8 hours = 480 min) * 3 courts = 1440 minutes
    # Total: 2640 minutes
    # Update only 2 days to be active with courts, deactivate the third
    update_data = {
        "days": [
            {
                "date": days[0]["date"],
                "is_active": True,
                "start_time": "08:00:00",
                "end_time": "18:00:00",
                "courts_available": 2,
            },
            {
                "date": days[1]["date"],
                "is_active": True,
                "start_time": "09:00:00",
                "end_time": "17:00:00",
                "courts_available": 3,
            },
            {"date": days[2]["date"], "is_active": False, "start_time": None, "end_time": None, "courts_available": 0},
        ]
    }
    client.put(f"/api/tournaments/{tournament['id']}/days", json=update_data)

    # Add event
    client.post(
        f"/api/tournaments/{tournament['id']}/events",
        json={
            "category": "mixed",
            "name": "Mixed Doubles",
            "team_count": 8,
        },
    )

    response = client.get(f"/api/tournaments/{tournament['id']}/phase1-status")
    status = response.json()

    # Calculate expected: (10 * 60) * 2 + (8 * 60) * 3 = 1200 + 1440 = 2640
    expected_minutes = (10 * 60) * 2 + (8 * 60) * 3
    assert status["summary"]["total_court_minutes"] == expected_minutes
    assert status["summary"]["active_days"] == 2
    assert status["is_ready"] is True


def test_phase1_status_includes_specific_errors(tournament, client: TestClient):
    """Test that phase1-status includes specific error messages"""
    # Set a day to active but without courts
    days_response = client.get(f"/api/tournaments/{tournament['id']}/days")
    days = days_response.json()

    update_data = {
        "days": [
            {
                "date": days[0]["date"],
                "is_active": True,
                "start_time": "08:00:00",
                "end_time": "18:00:00",
                "courts_available": 0,  # Active but no courts
            }
        ]
    }
    client.put(f"/api/tournaments/{tournament['id']}/days", json=update_data)

    response = client.get(f"/api/tournaments/{tournament['id']}/phase1-status")
    status = response.json()

    assert status["is_ready"] is False
    assert any("Courts not set on active day" in err for err in status["errors"])
