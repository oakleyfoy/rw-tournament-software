"""
Manual testing script for RW Tournament Software API
Run this after starting the server with: uvicorn app.main:app --reload

Note: This file is NOT meant to be run with pytest. Run it directly: python test_manual.py
"""

import json

import pytest
import requests

pytest.skip("This is a manual test script, not a pytest test", allow_module_level=True)

BASE_URL = "http://localhost:8000/api"


def print_response(title, response):
    """Pretty print API response"""
    print(f"\n{'=' * 60}")
    print(f"{title}")
    print(f"{'=' * 60}")
    print(f"Status: {response.status_code}")
    try:
        print(json.dumps(response.json(), indent=2))
    except (json.JSONDecodeError, ValueError):
        print(response.text)
    print()


def test_tournament_crud():
    """Test Tournament CRUD operations"""
    print("\n" + "=" * 60)
    print("TESTING TOURNAMENT CRUD")
    print("=" * 60)

    # Create tournament
    print("\n1. Creating tournament...")
    response = requests.post(
        f"{BASE_URL}/tournaments",
        json={
            "name": "Summer Championship 2026",
            "location": "Grand Tennis Club",
            "timezone": "America/New_York",
            "start_date": "2026-07-15",
            "end_date": "2026-07-17",
            "notes": "Annual summer championship tournament",
        },
    )
    print_response("Create Tournament", response)

    if response.status_code != 201:
        print("❌ Failed to create tournament")
        return None

    tournament = response.json()
    tournament_id = tournament["id"]
    print(f"✅ Tournament created with ID: {tournament_id}")

    # List tournaments
    print("\n2. Listing all tournaments...")
    response = requests.get(f"{BASE_URL}/tournaments")
    print_response("List Tournaments", response)

    # Get tournament
    print("\n3. Getting tournament by ID...")
    response = requests.get(f"{BASE_URL}/tournaments/{tournament_id}")
    print_response("Get Tournament", response)

    return tournament_id


def test_tournament_days(tournament_id):
    """Test Tournament Days endpoints"""
    print("\n" + "=" * 60)
    print("TESTING TOURNAMENT DAYS")
    print("=" * 60)

    # Get days (should be auto-created)
    print("\n1. Getting tournament days (auto-created)...")
    response = requests.get(f"{BASE_URL}/tournaments/{tournament_id}/days")
    print_response("Get Tournament Days", response)

    if response.status_code != 200:
        print("❌ Failed to get days")
        return

    days = response.json()
    print(f"✅ Found {len(days)} days (should be 3 for July 15-17)")

    # Bulk update days
    print("\n2. Bulk updating days...")
    update_data = {
        "days": [
            {
                "date": days[0]["date"],
                "is_active": True,
                "start_time": "08:00:00",
                "end_time": "18:00:00",
                "courts_available": 4,
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
    response = requests.put(f"{BASE_URL}/tournaments/{tournament_id}/days", json=update_data)
    print_response("Bulk Update Days", response)

    if response.status_code == 200:
        print("✅ Days updated successfully")
    else:
        print("❌ Failed to update days")


def test_events(tournament_id):
    """Test Events CRUD"""
    print("\n" + "=" * 60)
    print("TESTING EVENTS")
    print("=" * 60)

    # Create events
    print("\n1. Creating events...")
    events_data = [
        {"category": "mixed", "name": "Mixed Doubles", "team_count": 16, "notes": "Main mixed doubles event"},
        {"category": "womens", "name": "Women's Doubles", "team_count": 12, "notes": "Women's doubles championship"},
    ]

    event_ids = []
    for event_data in events_data:
        response = requests.post(f"{BASE_URL}/tournaments/{tournament_id}/events", json=event_data)
        print_response(f"Create Event: {event_data['name']}", response)
        if response.status_code == 201:
            event_ids.append(response.json()["id"])
            print(f"✅ Event created: {event_data['name']}")
        else:
            print(f"❌ Failed to create event: {event_data['name']}")

    # List events
    print("\n2. Listing all events...")
    response = requests.get(f"{BASE_URL}/tournaments/{tournament_id}/events")
    print_response("List Events", response)

    # Update event
    if event_ids:
        print("\n3. Updating event...")
        response = requests.put(f"{BASE_URL}/events/{event_ids[0]}", json={"team_count": 20})
        print_response("Update Event", response)

    return event_ids


def test_phase1_status(tournament_id):
    """Test Phase 1 Status endpoint"""
    print("\n" + "=" * 60)
    print("TESTING PHASE 1 STATUS")
    print("=" * 60)

    # Check initial status (should not be ready)
    print("\n1. Checking initial status (should not be ready)...")
    response = requests.get(f"{BASE_URL}/tournaments/{tournament_id}/phase1-status")
    print_response("Phase 1 Status (Initial)", response)

    # After setting up days and events, check again
    print("\n2. After setup, checking status again...")
    response = requests.get(f"{BASE_URL}/tournaments/{tournament_id}/phase1-status")
    status = response.json()
    print_response("Phase 1 Status (After Setup)", response)

    if status["is_ready"]:
        print("✅ Tournament is ready for Phase 2!")
        print(f"   - Active days: {status['summary']['active_days']}")
        print(f"   - Total court minutes: {status['summary']['total_court_minutes']}")
        print(f"   - Events: {status['summary']['events_count']}")
    else:
        print("⚠️  Tournament is not ready yet:")
        for error in status["errors"]:
            print(f"   - {error}")


def test_validation_errors():
    """Test validation error handling"""
    print("\n" + "=" * 60)
    print("TESTING VALIDATION ERRORS")
    print("=" * 60)

    # Test: end_date < start_date
    print("\n1. Testing invalid date range...")
    response = requests.post(
        f"{BASE_URL}/tournaments",
        json={
            "name": "Invalid Tournament",
            "location": "Test",
            "timezone": "America/New_York",
            "start_date": "2026-07-17",
            "end_date": "2026-07-15",  # Invalid: end before start
        },
    )
    print_response("Create Tournament (Invalid Date Range)", response)
    if response.status_code == 422:
        print("✅ Correctly rejected invalid date range")

    # Test: team_count < 2
    print("\n2. Testing invalid team_count...")
    # First create a tournament
    tournament_response = requests.post(
        f"{BASE_URL}/tournaments",
        json={
            "name": "Test Tournament",
            "location": "Test",
            "timezone": "America/New_York",
            "start_date": "2026-07-15",
            "end_date": "2026-07-17",
        },
    )
    if tournament_response.status_code == 201:
        tournament_id = tournament_response.json()["id"]
        response = requests.post(
            f"{BASE_URL}/tournaments/{tournament_id}/events",
            json={
                "category": "mixed",
                "name": "Test Event",
                "team_count": 1,  # Invalid: must be >= 2
            },
        )
        print_response("Create Event (Invalid team_count)", response)
        if response.status_code == 422:
            print("✅ Correctly rejected invalid team_count")


def main():
    """Run all tests"""
    print("\n" + "=" * 60)
    print("RW TOURNAMENT SOFTWARE - MANUAL API TESTING")
    print("=" * 60)
    print("\nMake sure the server is running: uvicorn app.main:app --reload")
    print("Server should be at: http://localhost:8000")

    try:
        # Test server is running
        response = requests.get("http://localhost:8000/")
        if response.status_code != 200:
            print("\n❌ Server is not running or not accessible")
            return
        print("\n✅ Server is running")
    except requests.exceptions.ConnectionError:
        print("\n❌ Cannot connect to server. Make sure it's running at http://localhost:8000")
        return

    # Run tests
    tournament_id = test_tournament_crud()
    if tournament_id:
        test_tournament_days(tournament_id)
        test_events(tournament_id)
        test_phase1_status(tournament_id)

    test_validation_errors()

    print("\n" + "=" * 60)
    print("TESTING COMPLETE")
    print("=" * 60)
    print("\nVisit http://localhost:8000/docs for interactive API documentation")


if __name__ == "__main__":
    main()
