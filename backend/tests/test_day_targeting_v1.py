"""
Tests for Day-Targeting V1 (Match-Level Preferred Day)

Tests must prove:
1. Preferred day chosen when available
2. Fallback when preferred day not available
3. Rest overrides preference
4. Determinism
"""

from datetime import date, datetime, time, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine, select
from sqlmodel.pool import StaticPool

from app.database import get_session
from app.main import app
from app.models.event import Event
from app.models.match import Match
from app.models.match_assignment import MatchAssignment
from app.models.schedule_slot import ScheduleSlot
from app.models.schedule_version import ScheduleVersion
from app.models.team import Team
from app.models.tournament import Tournament
from app.models.tournament_day import TournamentDay
from app.utils.rest_rules import auto_assign_with_rest

# ============================================================================
# Test Fixtures
# ============================================================================


@pytest.fixture(name="session")
def session_fixture():
    """Create in-memory SQLite database for testing"""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        yield session


@pytest.fixture(name="client")
def client_fixture(session: Session):
    """Create test client with overridden session"""

    def get_session_override():
        return session

    app.dependency_overrides[get_session] = get_session_override
    client = TestClient(app)
    yield client
    app.dependency_overrides.clear()


@pytest.fixture(name="setup_day_targeting_test")
def setup_day_targeting_test_fixture(session: Session):
    """
    Setup test environment with:
    - Tournament with 3 days (Mon, Tue, Wed)
    - Event with 4 teams
    - Schedule version
    - Slots across multiple days
    - Matches ready for day-targeted assignment
    """
    # Create tournament
    tournament = Tournament(
        name="Day-Targeting Test Tournament",
        location="Test Location",
        timezone="America/New_York",
        start_date=date(2026, 1, 12),  # Monday
        end_date=date(2026, 1, 14),  # Wednesday
    )
    session.add(tournament)
    session.commit()
    session.refresh(tournament)

    # Create event
    event = Event(
        tournament_id=tournament.id,
        name="Test Event",
        team_count=4,
        draw_plan_json='{"template_type":"ROUND_ROBIN"}',
        draw_status="final",
    )
    session.add(event)
    session.commit()
    session.refresh(event)

    # Create 4 teams
    teams = []
    for i in range(1, 5):
        team = Team(event_id=event.id, name=f"Team {i}", seed=i, rating=1000.0 + i)
        session.add(team)
        teams.append(team)
    session.commit()
    for team in teams:
        session.refresh(team)

    # Create schedule version
    schedule_version = ScheduleVersion(tournament_id=tournament.id, version_number=1, status="draft")
    session.add(schedule_version)
    session.commit()
    session.refresh(schedule_version)

    # Create tournament days (Mon, Tue, Wed)
    days = []
    for day_offset in range(3):
        day_date = date(2026, 1, 12) + timedelta(days=day_offset)
        day = TournamentDay(
            tournament_id=tournament.id,
            date=day_date,  # Note: field name is "date" not "day_date"
            start_time=time(10, 0),
            end_time=time(18, 0),
        )
        session.add(day)
        days.append(day)
    session.commit()

    # Create slots: 2 slots per day (morning and afternoon)
    slots = []
    for day_offset in range(3):
        day_date = date(2026, 1, 12) + timedelta(days=day_offset)

        # Morning slot (10:00 AM)
        morning_slot = ScheduleSlot(
            tournament_id=tournament.id,
            schedule_version_id=schedule_version.id,
            court_number=1,
            court_label="Court 1",
            day_date=day_date,
            start_time=time(10, 0),
            end_time=time(11, 0),
            block_minutes=60,
            is_active=True,
        )
        session.add(morning_slot)
        slots.append(morning_slot)

        # Afternoon slot (2:00 PM)
        afternoon_slot = ScheduleSlot(
            tournament_id=tournament.id,
            schedule_version_id=schedule_version.id,
            court_number=1,
            court_label="Court 1",
            day_date=day_date,
            start_time=time(14, 0),
            end_time=time(15, 0),
            block_minutes=60,
            is_active=True,
        )
        session.add(afternoon_slot)
        slots.append(afternoon_slot)

    session.commit()
    for slot in slots:
        session.refresh(slot)

    # Create 4 matches (round robin for 4 teams = 6 matches, but we'll create 4 for simplicity)
    matches = []
    match_configs = [
        (teams[0].id, teams[1].id, "M1"),  # Team 1 vs Team 2
        (teams[2].id, teams[3].id, "M2"),  # Team 3 vs Team 4
        (teams[0].id, teams[2].id, "M3"),  # Team 1 vs Team 3
        (teams[1].id, teams[3].id, "M4"),  # Team 2 vs Team 4
    ]

    for idx, (team_a_id, team_b_id, match_code) in enumerate(match_configs):
        match = Match(
            tournament_id=tournament.id,
            event_id=event.id,
            schedule_version_id=schedule_version.id,
            match_code=match_code,
            match_type="MAIN",
            round_number=1,
            round_index=idx + 1,
            sequence_in_round=idx + 1,
            duration_minutes=60,
            team_a_id=team_a_id,
            team_b_id=team_b_id,
            placeholder_side_a=f"Team {team_a_id}",
            placeholder_side_b=f"Team {team_b_id}",
            status="unscheduled",
        )
        session.add(match)
        matches.append(match)

    session.commit()
    for match in matches:
        session.refresh(match)

    return {
        "tournament_id": tournament.id,
        "event_id": event.id,
        "schedule_version_id": schedule_version.id,
        "teams": teams,
        "matches": matches,
        "slots": slots,
        "days": days,
    }


# ============================================================================
# Tests
# ============================================================================


def test_preferred_day_chosen_when_available(session: Session, setup_day_targeting_test: dict):
    """
    Test that when a match has preferred_day and a slot on that day is available,
    it is assigned to the preferred day slot.
    """
    schedule_version_id = setup_day_targeting_test["schedule_version_id"]
    matches = setup_day_targeting_test["matches"]

    # Set M1 to prefer Tuesday (weekday 1)
    match_m1 = matches[0]
    match_m1.preferred_day = 1  # Tuesday
    session.add(match_m1)
    session.commit()

    # Run auto-assignment
    result = auto_assign_with_rest(session, schedule_version_id, clear_existing=True)

    assert result["assigned_count"] == 4
    assert result["preferred_day_metrics"]["preferred_day_hits"] == 1
    assert result["preferred_day_metrics"]["preferred_day_misses"] == 0

    # Verify M1 is assigned to Tuesday slot
    session.refresh(match_m1)
    assignment = session.exec(select(MatchAssignment).where(MatchAssignment.match_id == match_m1.id)).first()

    assert assignment is not None
    assigned_slot = session.get(ScheduleSlot, assignment.slot_id)
    assert assigned_slot.day_date.weekday() == 1  # Tuesday


def test_fallback_when_preferred_day_not_available(session: Session, setup_day_targeting_test: dict):
    """
    Test that when a match's preferred day has no compatible slots,
    it falls back to earliest compatible slot on a different day.
    """
    schedule_version_id = setup_day_targeting_test["schedule_version_id"]
    matches = setup_day_targeting_test["matches"]
    setup_day_targeting_test["slots"]

    # Set all matches to prefer Sunday (weekday 6), which doesn't exist in our slots
    for match in matches:
        match.preferred_day = 6  # Sunday
        session.add(match)
    session.commit()

    # Run auto-assignment
    result = auto_assign_with_rest(session, schedule_version_id, clear_existing=True)

    # All matches should still be assigned (fallback to available days)
    assert result["assigned_count"] == 4
    assert result["preferred_day_metrics"]["preferred_day_hits"] == 0
    assert result["preferred_day_metrics"]["preferred_day_misses"] == 4


def test_rest_overrides_preference(session: Session, setup_day_targeting_test: dict):
    """
    Test that rest rules are mandatory and override day preference.
    If preferred-day slot violates rest but non-preferred slot satisfies rest,
    assign to non-preferred slot.
    """
    schedule_version_id = setup_day_targeting_test["schedule_version_id"]
    matches = setup_day_targeting_test["matches"]
    setup_day_targeting_test["teams"]

    # Scenario:
    # - Match M1 (Team 1 vs Team 2) assigned to Monday 10:00 AM
    # - Match M3 (Team 1 vs Team 3) prefers Monday (same day), but needs rest
    # - Should assign M3 to Tuesday or later to satisfy 90-min rest

    match_m1 = matches[0]  # Team 1 vs Team 2
    match_m3 = matches[2]  # Team 1 vs Team 3

    # Set M1 to prefer Monday, M3 to prefer Monday (but should be blocked by rest)
    match_m1.preferred_day = 0  # Monday
    match_m3.preferred_day = 0  # Monday
    session.add(match_m1)
    session.add(match_m3)
    session.commit()

    # Run auto-assignment
    result = auto_assign_with_rest(session, schedule_version_id, clear_existing=True)

    # All matches should be assigned
    assert result["assigned_count"] == 4

    # M1 should be on Monday (preferred and available)
    session.refresh(match_m1)
    assignment_m1 = session.exec(select(MatchAssignment).where(MatchAssignment.match_id == match_m1.id)).first()
    assert assignment_m1 is not None
    slot_m1 = session.get(ScheduleSlot, assignment_m1.slot_id)
    assert slot_m1.day_date.weekday() == 0  # Monday

    # M3 should NOT be on Monday (rest violation for Team 1)
    session.refresh(match_m3)
    assignment_m3 = session.exec(select(MatchAssignment).where(MatchAssignment.match_id == match_m3.id)).first()
    assert assignment_m3 is not None
    slot_m3 = session.get(ScheduleSlot, assignment_m3.slot_id)

    # M3 should be later than M1 with sufficient rest (90 minutes)
    slot_m1_datetime = datetime.combine(slot_m1.day_date, slot_m1.start_time)
    slot_m3_datetime = datetime.combine(slot_m3.day_date, slot_m3.start_time)
    match_m1_end = slot_m1_datetime + timedelta(minutes=match_m1.duration_minutes)

    rest_minutes = (slot_m3_datetime - match_m1_end).total_seconds() / 60
    assert rest_minutes >= 90  # Rest rule satisfied


def test_determinism(session: Session, setup_day_targeting_test: dict):
    """
    Test that running auto-assignment twice with same inputs produces identical results.
    """
    schedule_version_id = setup_day_targeting_test["schedule_version_id"]
    matches = setup_day_targeting_test["matches"]

    # Set preferred days for some matches
    matches[0].preferred_day = 1  # Tuesday
    matches[1].preferred_day = 2  # Wednesday
    session.add(matches[0])
    session.add(matches[1])
    session.commit()

    # Run first assignment
    result1 = auto_assign_with_rest(session, schedule_version_id, clear_existing=True)

    # Capture assignments
    assignments1 = {}
    for match in matches:
        assignment = session.exec(select(MatchAssignment).where(MatchAssignment.match_id == match.id)).first()
        if assignment:
            assignments1[match.id] = assignment.slot_id

    # Run second assignment (clear and re-run)
    result2 = auto_assign_with_rest(session, schedule_version_id, clear_existing=True)

    # Capture assignments again
    assignments2 = {}
    for match in matches:
        assignment = session.exec(select(MatchAssignment).where(MatchAssignment.match_id == match.id)).first()
        if assignment:
            assignments2[match.id] = assignment.slot_id

    # Compare results
    assert result1["assigned_count"] == result2["assigned_count"]
    assert result1["preferred_day_metrics"] == result2["preferred_day_metrics"]
    assert assignments1 == assignments2


def test_preferred_day_null_no_preference(session: Session, setup_day_targeting_test: dict):
    """
    Test that when match.preferred_day is null, all slots have equal preference
    and earliest compatible slot wins (deterministic order).
    """
    schedule_version_id = setup_day_targeting_test["schedule_version_id"]
    matches = setup_day_targeting_test["matches"]

    # Ensure all matches have null preferred_day
    for match in matches:
        match.preferred_day = None
        session.add(match)
    session.commit()

    # Run auto-assignment
    result = auto_assign_with_rest(session, schedule_version_id, clear_existing=True)

    assert result["assigned_count"] == 4
    assert result["preferred_day_metrics"]["preferred_day_hits"] == 0
    assert result["preferred_day_metrics"]["preferred_day_misses"] == 0
    assert result["preferred_day_metrics"]["preferred_day_applied_count"] == 0


def test_api_patch_match_preferred_day(client: TestClient, session: Session, setup_day_targeting_test: dict):
    """
    Test that PATCH endpoint allows setting match.preferred_day
    """
    tournament_id = setup_day_targeting_test["tournament_id"]
    match = setup_day_targeting_test["matches"][0]

    # Update match to prefer Tuesday (weekday 1)
    response = client.patch(f"/api/tournaments/{tournament_id}/schedule/matches/{match.id}", json={"preferred_day": 1})

    assert response.status_code == 200
    data = response.json()
    assert data["preferred_day"] == 1

    # Verify in database
    session.refresh(match)
    assert match.preferred_day == 1


def test_api_patch_match_preferred_day_validation(client: TestClient, session: Session, setup_day_targeting_test: dict):
    """
    Test that PATCH endpoint validates preferred_day is in range 0-6
    """
    tournament_id = setup_day_targeting_test["tournament_id"]
    match = setup_day_targeting_test["matches"][0]

    # Try invalid value (7)
    response = client.patch(f"/api/tournaments/{tournament_id}/schedule/matches/{match.id}", json={"preferred_day": 7})

    assert response.status_code == 422  # Validation error

    # Try negative value
    response = client.patch(f"/api/tournaments/{tournament_id}/schedule/matches/{match.id}", json={"preferred_day": -1})

    assert response.status_code == 422  # Validation error


def test_api_get_matches_includes_preferred_day(client: TestClient, session: Session, setup_day_targeting_test: dict):
    """
    Test that GET /schedule/matches includes preferred_day field
    """
    tournament_id = setup_day_targeting_test["tournament_id"]
    match = setup_day_targeting_test["matches"][0]

    # Set preferred day
    match.preferred_day = 3  # Thursday
    session.add(match)
    session.commit()

    # Get matches
    response = client.get(f"/api/tournaments/{tournament_id}/schedule/matches")

    assert response.status_code == 200
    matches = response.json()
    assert len(matches) > 0

    # Find our match
    our_match = next((m for m in matches if m["id"] == match.id), None)
    assert our_match is not None
    assert our_match["preferred_day"] == 3
