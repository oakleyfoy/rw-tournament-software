"""Tests for Grid Population V1 endpoint"""

from datetime import date, time

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.models.event import Event, EventCategory
from app.models.match import Match
from app.models.match_assignment import MatchAssignment
from app.models.schedule_slot import ScheduleSlot
from app.models.schedule_version import ScheduleVersion
from app.models.tournament import Tournament


@pytest.fixture
def grid_fixture(session: Session):
    """
    Create a fixture for grid testing with slots, matches, and some assignments.
    """
    # Create tournament
    tournament = Tournament(
        name="Grid Test Tournament",
        location="Test Venue",
        timezone="UTC",
        start_date=date(2026, 5, 1),
        end_date=date(2026, 5, 2),
        court_names=["Court A", "Court B"],
    )
    session.add(tournament)
    session.commit()
    session.refresh(tournament)

    # Create event
    event = Event(tournament_id=tournament.id, category=EventCategory.mixed, name="Test Event", team_count=4)
    session.add(event)
    session.commit()
    session.refresh(event)

    # Create schedule version
    version = ScheduleVersion(tournament_id=tournament.id, version_number=1, status="draft")
    session.add(version)
    session.commit()
    session.refresh(version)

    # Create slots (2 days x 2 courts x 2 time slots = 8 slots)
    slots = []
    for day_offset in [0, 1]:
        for court_num in [1, 2]:
            for hour in [9, 10]:
                slot = ScheduleSlot(
                    tournament_id=tournament.id,
                    schedule_version_id=version.id,
                    day_date=date(2026, 5, 1 + day_offset),
                    start_time=time(hour, 0),
                    end_time=time(hour + 1, 0),
                    court_number=court_num,
                    court_label=f"Court {chr(64 + court_num)}",  # Court A, Court B
                    block_minutes=60,
                    is_active=True,
                )
                slots.append(slot)
                session.add(slot)

    session.commit()
    for slot in slots:
        session.refresh(slot)

    # Create matches (3 WF matches)
    matches = []
    for i in range(3):
        match = Match(
            tournament_id=tournament.id,
            event_id=event.id,
            schedule_version_id=version.id,
            match_code=f"WF_M{i + 1}",
            match_type="WF",
            round_number=1,
            round_index=1,
            sequence_in_round=i + 1,
            duration_minutes=45,
            placeholder_side_a=f"Team {i * 2 + 1}",
            placeholder_side_b=f"Team {i * 2 + 2}",
            status="unscheduled",
        )
        matches.append(match)
        session.add(match)

    session.commit()
    for match in matches:
        session.refresh(match)

    # Create assignments (assign 2 matches, leave 1 unassigned)
    assignment1 = MatchAssignment(
        schedule_version_id=version.id,
        match_id=matches[0].id,
        slot_id=slots[0].id,  # Day 1, Court A, 09:00
        assigned_by="test",
    )
    assignment2 = MatchAssignment(
        schedule_version_id=version.id,
        match_id=matches[1].id,
        slot_id=slots[1].id,  # Day 1, Court B, 09:00
        assigned_by="test",
    )
    session.add(assignment1)
    session.add(assignment2)
    session.commit()

    return {
        "tournament": tournament,
        "event": event,
        "version": version,
        "slots": slots,
        "matches": matches,
        "assigned_count": 2,
        "unassigned_count": 1,
    }


def test_grid_endpoint_returns_200(client: TestClient, grid_fixture):
    """Test that grid endpoint returns 200"""
    fixture = grid_fixture
    tournament_id = fixture["tournament"].id
    version_id = fixture["version"].id

    response = client.get(f"/api/tournaments/{tournament_id}/schedule/grid", params={"schedule_version_id": version_id})

    assert response.status_code == 200


def test_grid_endpoint_structure(client: TestClient, grid_fixture):
    """Test that grid endpoint returns correct structure"""
    fixture = grid_fixture
    tournament_id = fixture["tournament"].id
    version_id = fixture["version"].id

    response = client.get(f"/api/tournaments/{tournament_id}/schedule/grid", params={"schedule_version_id": version_id})

    assert response.status_code == 200
    data = response.json()

    # Verify top-level structure
    assert "slots" in data
    assert "assignments" in data
    assert "matches" in data
    assert "conflicts_summary" in data

    # Verify it's lists/arrays
    assert isinstance(data["slots"], list)
    assert isinstance(data["assignments"], list)
    assert isinstance(data["matches"], list)


def test_grid_slots_format(client: TestClient, grid_fixture):
    """Test that slots have correct format"""
    fixture = grid_fixture
    tournament_id = fixture["tournament"].id
    version_id = fixture["version"].id

    response = client.get(f"/api/tournaments/{tournament_id}/schedule/grid", params={"schedule_version_id": version_id})

    data = response.json()
    slots = data["slots"]

    assert len(slots) == 8  # 2 days x 2 courts x 2 times

    # Check first slot structure
    slot = slots[0]
    assert "slot_id" in slot
    assert "start_time" in slot
    assert "duration_minutes" in slot
    assert "court_id" in slot
    assert "court_label" in slot
    assert "day_date" in slot


def test_grid_assignments_format(client: TestClient, grid_fixture):
    """Test that assignments have correct format"""
    fixture = grid_fixture
    tournament_id = fixture["tournament"].id
    version_id = fixture["version"].id

    response = client.get(f"/api/tournaments/{tournament_id}/schedule/grid", params={"schedule_version_id": version_id})

    data = response.json()
    assignments = data["assignments"]

    assert len(assignments) == 2  # 2 assigned matches

    # Check first assignment structure
    assignment = assignments[0]
    assert "slot_id" in assignment
    assert "match_id" in assignment


def test_grid_matches_format(client: TestClient, grid_fixture):
    """Test that matches have correct format"""
    fixture = grid_fixture
    tournament_id = fixture["tournament"].id
    version_id = fixture["version"].id

    response = client.get(f"/api/tournaments/{tournament_id}/schedule/grid", params={"schedule_version_id": version_id})

    data = response.json()
    matches = data["matches"]

    assert len(matches) == 3  # 3 total matches

    # Check first match structure
    match = matches[0]
    assert "match_id" in match
    assert "stage" in match
    assert "round_index" in match
    assert "sequence_in_round" in match
    assert "duration_minutes" in match
    assert "match_code" in match
    assert "event_id" in match


def test_grid_conflicts_summary(client: TestClient, grid_fixture):
    """Test that conflicts summary is included and correct"""
    fixture = grid_fixture
    tournament_id = fixture["tournament"].id
    version_id = fixture["version"].id

    response = client.get(f"/api/tournaments/{tournament_id}/schedule/grid", params={"schedule_version_id": version_id})

    data = response.json()
    summary = data["conflicts_summary"]

    assert summary is not None
    assert summary["tournament_id"] == tournament_id
    assert summary["schedule_version_id"] == version_id
    assert summary["total_slots"] == 8
    assert summary["total_matches"] == 3
    assert summary["assigned_matches"] == 2
    assert summary["unassigned_matches"] == 1
    assert summary["assignment_rate"] == pytest.approx(66.7, rel=0.1)


def test_grid_returns_200_with_no_assignments(client: TestClient, session: Session):
    """Test that grid returns 200 even with zero assignments"""
    # Create minimal fixture with no assignments
    tournament = Tournament(
        name="Empty Grid Test",
        location="Test",
        timezone="UTC",
        start_date=date(2026, 6, 1),
        end_date=date(2026, 6, 1),
        court_names=["Court 1"],
    )
    session.add(tournament)
    session.commit()
    session.refresh(tournament)

    version = ScheduleVersion(tournament_id=tournament.id, version_number=1, status="draft")
    session.add(version)
    session.commit()
    session.refresh(version)

    # Create one slot but no matches or assignments
    slot = ScheduleSlot(
        tournament_id=tournament.id,
        schedule_version_id=version.id,
        day_date=date(2026, 6, 1),
        start_time=time(9, 0),
        end_time=time(10, 0),
        court_number=1,
        court_label="Court 1",
        block_minutes=60,
        is_active=True,
    )
    session.add(slot)
    session.commit()

    response = client.get(f"/api/tournaments/{tournament.id}/schedule/grid", params={"schedule_version_id": version.id})

    assert response.status_code == 200
    data = response.json()

    assert len(data["slots"]) == 1
    assert len(data["assignments"]) == 0
    assert len(data["matches"]) == 0
    assert data["conflicts_summary"]["assigned_matches"] == 0


def test_grid_returns_200_with_zero_matches_generated(client: TestClient, session: Session):
    """Test that grid returns 200 even when no matches are generated yet"""
    tournament = Tournament(
        name="No Matches Test",
        location="Test",
        timezone="UTC",
        start_date=date(2026, 7, 1),
        end_date=date(2026, 7, 1),
        court_names=["Court 1"],
    )
    session.add(tournament)
    session.commit()
    session.refresh(tournament)

    version = ScheduleVersion(tournament_id=tournament.id, version_number=1, status="draft")
    session.add(version)
    session.commit()
    session.refresh(version)

    # No slots, no matches, no assignments
    response = client.get(f"/api/tournaments/{tournament.id}/schedule/grid", params={"schedule_version_id": version.id})

    assert response.status_code == 200
    data = response.json()

    assert len(data["slots"]) == 0
    assert len(data["assignments"]) == 0
    assert len(data["matches"]) == 0


def test_grid_requires_schedule_version_id(client: TestClient, grid_fixture):
    """Test that schedule_version_id is required"""
    fixture = grid_fixture
    tournament_id = fixture["tournament"].id

    response = client.get(f"/api/tournaments/{tournament_id}/schedule/grid")

    # Should return 422 (validation error)
    assert response.status_code == 422


def test_grid_invalid_tournament(client: TestClient):
    """Test 404 for invalid tournament"""
    response = client.get("/api/tournaments/99999/schedule/grid", params={"schedule_version_id": 1})

    assert response.status_code == 404


def test_grid_sorting_is_deterministic(client: TestClient, grid_fixture):
    """Test that grid data is sorted consistently"""
    fixture = grid_fixture
    tournament_id = fixture["tournament"].id
    version_id = fixture["version"].id

    # Make multiple requests
    responses = []
    for _ in range(3):
        response = client.get(
            f"/api/tournaments/{tournament_id}/schedule/grid", params={"schedule_version_id": version_id}
        )
        assert response.status_code == 200
        responses.append(response.json())

    # Verify slots are in same order across all responses
    slots1 = responses[0]["slots"]
    slots2 = responses[1]["slots"]
    slots3 = responses[2]["slots"]

    assert len(slots1) == len(slots2) == len(slots3)

    for i in range(len(slots1)):
        # Check slot IDs are in same order
        assert slots1[i]["slot_id"] == slots2[i]["slot_id"] == slots3[i]["slot_id"]

        # Slots should be sorted by day_date, start_time, court_id
        if i > 0:
            prev_slot = slots1[i - 1]
            curr_slot = slots1[i]

            # Compare day dates
            prev_day = prev_slot["day_date"]
            curr_day = curr_slot["day_date"]

            if curr_day > prev_day:
                continue  # Next day, time can be anything
            elif curr_day == prev_day:
                # Same day, check time
                prev_time = prev_slot["start_time"]
                curr_time = curr_slot["start_time"]

                assert curr_time >= prev_time, "Times should be ascending within same day"


def test_grid_read_only(session: Session, client: TestClient, grid_fixture):
    """Test that grid endpoint does not modify database"""
    fixture = grid_fixture
    tournament_id = fixture["tournament"].id
    version_id = fixture["version"].id

    # Count records before
    slots_before = len(session.exec(select(ScheduleSlot)).all())
    matches_before = len(session.exec(select(Match)).all())
    assignments_before = len(session.exec(select(MatchAssignment)).all())

    # Call endpoint
    response = client.get(f"/api/tournaments/{tournament_id}/schedule/grid", params={"schedule_version_id": version_id})

    assert response.status_code == 200

    # Count records after
    session.expire_all()  # Clear cache
    slots_after = len(session.exec(select(ScheduleSlot)).all())
    matches_after = len(session.exec(select(Match)).all())
    assignments_after = len(session.exec(select(MatchAssignment)).all())

    # Verify no changes
    assert slots_after == slots_before
    assert matches_after == matches_before
    assert assignments_after == assignments_before


def test_grid_team_fields_are_optional_and_null_when_not_injected(client: TestClient, grid_fixture):
    """
    Test that grid API includes team_a_id and team_b_id fields for backward compatibility,
    but they are None when team injection has not been run.
    """
    fixture = grid_fixture
    tournament_id = fixture["tournament"].id
    version_id = fixture["version"].id

    response = client.get(f"/api/tournaments/{tournament_id}/schedule/grid", params={"schedule_version_id": version_id})

    # Assert response is 200
    assert response.status_code == 200

    data = response.json()

    # Assert matches include team_a_id and team_b_id keys (backward compatible schema)
    if data["matches"]:
        match_keys = set(data["matches"][0].keys())
        assert "team_a_id" in match_keys, "Match schema should include team_a_id for backward compatibility"
        assert "team_b_id" in match_keys, "Match schema should include team_b_id for backward compatibility"

        # Assert all team_a_id and team_b_id are None (since no team injection has been run)
        for match in data["matches"]:
            assert match["team_a_id"] is None, f"Match {match['id']} should have team_a_id=None when not injected"
            assert match["team_b_id"] is None, f"Match {match['id']} should have team_b_id=None when not injected"

    # Assert teams list is empty (or only contains teams for injected events, if any)
    # Since this fixture has not run team injection, teams should be empty
    assert "teams" in data
    assert data["teams"] == [], "Teams list should be empty when no team injection has been run"
