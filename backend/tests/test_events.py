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


def test_create_event(tournament, client: TestClient):
    """Test creating an event"""
    response = client.post(
        f"/api/tournaments/{tournament['id']}/events",
        json={"category": "mixed", "name": "Mixed Doubles", "team_count": 8, "notes": "Test event"},
    )

    assert response.status_code == 201
    event_data = response.json()
    assert event_data["category"] == "mixed"
    assert event_data["name"] == "Mixed Doubles"
    assert event_data["team_count"] == 8


def test_events_rejects_team_count_less_than_2(tournament, client: TestClient):
    """Test that events reject team_count < 2"""
    response = client.post(
        f"/api/tournaments/{tournament['id']}/events",
        json={
            "category": "mixed",
            "name": "Mixed Doubles",
            "team_count": 1,  # Invalid: must be >= 2
        },
    )

    assert response.status_code == 422
    error_detail = response.json()["detail"]
    assert any("team_count must be >= 2" in str(err) for err in error_detail)


def test_events_rejects_empty_name(tournament, client: TestClient):
    """Test that events reject empty name"""
    response = client.post(
        f"/api/tournaments/{tournament['id']}/events",
        json={
            "category": "mixed",
            "name": "",  # Invalid: empty name
            "team_count": 8,
        },
    )

    assert response.status_code == 422


def test_events_unique_constraint_prevents_duplicates(tournament, client: TestClient):
    """Test that unique constraint prevents duplicate events"""
    # Create first event
    response1 = client.post(
        f"/api/tournaments/{tournament['id']}/events",
        json={
            "category": "mixed",
            "name": "Mixed Doubles",
            "team_count": 8,
        },
    )
    assert response1.status_code == 201

    # Try to create duplicate
    response2 = client.post(
        f"/api/tournaments/{tournament['id']}/events",
        json={
            "category": "mixed",
            "name": "Mixed Doubles",  # Same category and name
            "team_count": 8,
        },
    )

    assert response2.status_code == 409
    assert "already exists" in response2.json()["detail"]


def test_get_tournament_events(tournament, client: TestClient):
    """Test getting all events for a tournament"""
    # Create events
    client.post(
        f"/api/tournaments/{tournament['id']}/events",
        json={
            "category": "mixed",
            "name": "Mixed Doubles",
            "team_count": 8,
        },
    )
    client.post(
        f"/api/tournaments/{tournament['id']}/events",
        json={
            "category": "womens",
            "name": "Women's Doubles",
            "team_count": 6,
        },
    )

    # Get events
    response = client.get(f"/api/tournaments/{tournament['id']}/events")
    assert response.status_code == 200
    events = response.json()
    assert len(events) == 2


def test_update_event(tournament, client: TestClient):
    """Test updating an event"""
    # Create event
    create_response = client.post(
        f"/api/tournaments/{tournament['id']}/events",
        json={
            "category": "mixed",
            "name": "Mixed Doubles",
            "team_count": 8,
        },
    )
    event_id = create_response.json()["id"]

    # Update event
    update_response = client.put(
        f"/api/events/{event_id}",
        json={
            "team_count": 12,
        },
    )

    assert update_response.status_code == 200
    assert update_response.json()["team_count"] == 12


def test_delete_event(tournament, client: TestClient):
    """Test deleting an event"""
    # Create event
    create_response = client.post(
        f"/api/tournaments/{tournament['id']}/events",
        json={
            "category": "mixed",
            "name": "Mixed Doubles",
            "team_count": 8,
        },
    )
    event_id = create_response.json()["id"]

    # Delete event
    delete_response = client.delete(f"/api/events/{event_id}")
    assert delete_response.status_code == 204

    # Verify it's deleted
    get_response = client.get(f"/api/tournaments/{tournament['id']}/events")
    assert len(get_response.json()) == 0
