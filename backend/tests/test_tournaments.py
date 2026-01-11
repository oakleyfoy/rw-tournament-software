from datetime import date, timedelta

from fastapi.testclient import TestClient


def test_create_tournament_auto_creates_days(client: TestClient):
    """Test that creating a tournament auto-creates correct number of days"""
    start_date = date(2026, 1, 15)
    end_date = date(2026, 1, 17)

    response = client.post(
        "/api/tournaments",
        json={
            "name": "Test Tournament",
            "location": "Test Location",
            "timezone": "America/New_York",
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "notes": "Test notes",
        },
    )

    assert response.status_code == 201
    tournament_data = response.json()
    assert tournament_data["name"] == "Test Tournament"
    assert tournament_data["start_date"] == start_date.isoformat()
    assert tournament_data["end_date"] == end_date.isoformat()

    # Check that days were created
    days_response = client.get(f"/api/tournaments/{tournament_data['id']}/days")
    assert days_response.status_code == 200
    days = days_response.json()

    # Should have 3 days (15, 16, 17)
    assert len(days) == 3

    # Check default values
    for day in days:
        assert day["is_active"] is True
        assert day["start_time"] == "08:00:00"
        assert day["end_time"] == "18:00:00"
        assert day["courts_available"] == 0

    # Check dates are correct
    dates = sorted([day["date"] for day in days])
    assert dates == [start_date.isoformat(), (start_date + timedelta(days=1)).isoformat(), end_date.isoformat()]


def test_tournament_validation_fails_if_end_before_start(client: TestClient):
    """Test that tournament validation fails if end_date < start_date"""
    response = client.post(
        "/api/tournaments",
        json={
            "name": "Test Tournament",
            "location": "Test Location",
            "timezone": "America/New_York",
            "start_date": "2026-01-17",
            "end_date": "2026-01-15",  # End before start
        },
    )

    assert response.status_code == 422
    error_detail = response.json()["detail"]
    assert any("end_date must be >= start_date" in str(err) for err in error_detail)


def test_tournament_timezone_required(client: TestClient):
    """Test that timezone is required"""
    response = client.post(
        "/api/tournaments",
        json={
            "name": "Test Tournament",
            "location": "Test Location",
            "timezone": "",  # Empty timezone
            "start_date": "2026-01-15",
            "end_date": "2026-01-17",
        },
    )

    assert response.status_code == 422


def test_get_tournament(client: TestClient):
    """Test getting a tournament by ID"""
    # Create tournament
    create_response = client.post(
        "/api/tournaments",
        json={
            "name": "Test Tournament",
            "location": "Test Location",
            "timezone": "America/New_York",
            "start_date": "2026-01-15",
            "end_date": "2026-01-17",
        },
    )
    tournament_id = create_response.json()["id"]

    # Get tournament
    response = client.get(f"/api/tournaments/{tournament_id}")
    assert response.status_code == 200
    assert response.json()["id"] == tournament_id


def test_update_tournament_date_range_manages_days(client: TestClient):
    """Test that updating tournament date range adds/removes days correctly"""
    # Create tournament
    create_response = client.post(
        "/api/tournaments",
        json={
            "name": "Test Tournament",
            "location": "Test Location",
            "timezone": "America/New_York",
            "start_date": "2026-01-15",
            "end_date": "2026-01-17",
        },
    )
    tournament_id = create_response.json()["id"]

    # Verify initial days
    days_response = client.get(f"/api/tournaments/{tournament_id}/days")
    assert len(days_response.json()) == 3

    # Update date range to extend it
    update_response = client.put(
        f"/api/tournaments/{tournament_id}",
        json={
            "start_date": "2026-01-14",
            "end_date": "2026-01-18",
        },
    )
    assert update_response.status_code == 200

    # Check days were updated (should have 5 days now: 14-18)
    days_response = client.get(f"/api/tournaments/{tournament_id}/days")
    assert len(days_response.json()) == 5

    # Update date range to shrink it
    update_response = client.put(
        f"/api/tournaments/{tournament_id}",
        json={
            "start_date": "2026-01-15",
            "end_date": "2026-01-16",
        },
    )
    assert update_response.status_code == 200

    # Check days were updated (should have 2 days now: 15-16)
    days_response = client.get(f"/api/tournaments/{tournament_id}/days")
    assert len(days_response.json()) == 2
