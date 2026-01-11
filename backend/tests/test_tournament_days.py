import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def tournament(client: TestClient):
    """Create a tournament with days for testing"""
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


def test_get_tournament_days(tournament, client: TestClient):
    """Test getting tournament days"""
    response = client.get(f"/api/tournaments/{tournament['id']}/days")
    assert response.status_code == 200
    days = response.json()
    assert len(days) == 3


def test_bulk_update_days_rejects_active_day_with_courts_less_than_1(tournament, client: TestClient):
    """Test that bulk update rejects active day with courts < 1"""
    # Get days first
    days_response = client.get(f"/api/tournaments/{tournament['id']}/days")
    days = days_response.json()

    # Try to update a day to active with 0 courts
    update_data = {
        "days": [
            {
                "date": days[0]["date"],
                "is_active": True,
                "start_time": "08:00:00",
                "end_time": "18:00:00",
                "courts_available": 0,  # Invalid: active day needs >= 1 court
            }
        ]
    }

    response = client.put(f"/api/tournaments/{tournament['id']}/days", json=update_data)

    assert response.status_code == 422
    error_detail = response.json()["detail"]
    # Pydantic v2 returns list of errors
    if isinstance(error_detail, list):
        error_msg = str(error_detail[0].get("msg", ""))
        assert "courts_available must be >= 1" in error_msg
    else:
        assert "courts_available must be >= 1" in str(error_detail)


def test_bulk_update_days_rejects_invalid_time_range(tournament, client: TestClient):
    """Test that bulk update rejects active day with end_time <= start_time"""
    days_response = client.get(f"/api/tournaments/{tournament['id']}/days")
    days = days_response.json()

    # Try to update a day with end_time <= start_time
    update_data = {
        "days": [
            {
                "date": days[0]["date"],
                "is_active": True,
                "start_time": "18:00:00",
                "end_time": "08:00:00",  # Invalid: end <= start
                "courts_available": 2,
            }
        ]
    }

    response = client.put(f"/api/tournaments/{tournament['id']}/days", json=update_data)

    assert response.status_code == 422
    error_detail = response.json()["detail"]
    # Pydantic v2 returns list of errors
    if isinstance(error_detail, list):
        error_msg = str(error_detail[0].get("msg", ""))
        assert "end_time must be greater than start_time" in error_msg
    else:
        assert "end_time must be greater than start_time" in str(error_detail)


def test_bulk_update_days_allows_inactive_day_without_times(tournament, client: TestClient):
    """Test that inactive days can have no times and 0 courts"""
    days_response = client.get(f"/api/tournaments/{tournament['id']}/days")
    days = days_response.json()

    update_data = {
        "days": [
            {"date": days[0]["date"], "is_active": False, "start_time": None, "end_time": None, "courts_available": 0}
        ]
    }

    response = client.put(f"/api/tournaments/{tournament['id']}/days", json=update_data)

    assert response.status_code == 200
    updated_day = response.json()[0]
    assert updated_day["is_active"] is False
    assert updated_day["courts_available"] == 0


def test_bulk_update_multiple_days(tournament, client: TestClient):
    """Test updating multiple days at once"""
    days_response = client.get(f"/api/tournaments/{tournament['id']}/days")
    days = days_response.json()

    update_data = {
        "days": [
            {
                "date": days[0]["date"],
                "is_active": True,
                "start_time": "09:00:00",
                "end_time": "17:00:00",
                "courts_available": 4,
            },
            {
                "date": days[1]["date"],
                "is_active": True,
                "start_time": "10:00:00",
                "end_time": "16:00:00",
                "courts_available": 2,
            },
        ]
    }

    response = client.put(f"/api/tournaments/{tournament['id']}/days", json=update_data)

    assert response.status_code == 200
    updated_days = response.json()
    assert len(updated_days) == 2
    assert updated_days[0]["courts_available"] == 4
    assert updated_days[1]["courts_available"] == 2
