"""
Tests for One-Click Build Full Schedule V1

Tests:
- Draft-only guard
- Orchestrator execution order
- Idempotency (run twice → identical results)
- WF grouping conditional execution
- Team injection conditional execution
- Composite response payload
"""

import json
from datetime import date, time

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine, select
from sqlmodel.pool import StaticPool

from app.database import get_session
from app.main import app
from app.models import (
    Event,
    Match,
    MatchAssignment,
    ScheduleSlot,
    ScheduleVersion,
    Team,
    TeamAvoidEdge,
    Tournament,
    TournamentDay,
)
from app.services.schedule_orchestrator import build_schedule_v1

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


@pytest.fixture(name="setup_tournament")
def setup_tournament_fixture(session: Session):
    """Setup tournament with draft schedule version"""
    # Create tournament
    tournament = Tournament(
        name="Build Test Tournament",
        location="Test Location",
        timezone="America/New_York",
        start_date=date(2026, 1, 15),
        end_date=date(2026, 1, 17),
        court_names=["Court 1", "Court 2"],
    )
    session.add(tournament)
    session.commit()
    session.refresh(tournament)

    # Create tournament day
    day = TournamentDay(
        tournament_id=tournament.id,
        date=date(2026, 1, 15),
        is_active=True,
        start_time=time(9, 0),
        end_time=time(18, 0),
        courts_available=2,
    )
    session.add(day)
    session.commit()

    # Create draft schedule version
    version = ScheduleVersion(tournament_id=tournament.id, version_number=1, status="draft")
    session.add(version)
    session.commit()
    session.refresh(version)

    # Create event
    event = Event(
        tournament_id=tournament.id,
        name="Test Event",
        category="mixed",
        team_count=8,
        draw_plan_json=json.dumps({"template_type": "WF_TO_POOLS_4", "wf_rounds": 2, "guarantee": 4}),
        draw_status="final",
        wf_block_minutes=60,
        standard_block_minutes=120,
    )
    session.add(event)
    session.commit()
    session.refresh(event)

    # Create teams
    teams = []
    for i in range(1, 9):
        team = Team(event_id=event.id, name=f"Team {i}", seed=i, rating=1000.0 + i)
        teams.append(team)
    session.add_all(teams)
    session.commit()
    for team in teams:
        session.refresh(team)

    # Create some slots
    slots = []
    for hour in [9, 10, 11, 12]:
        for court in [1, 2]:
            slot = ScheduleSlot(
                tournament_id=tournament.id,
                schedule_version_id=version.id,
                day_date=date(2026, 1, 15),
                start_time=time(hour, 0),
                end_time=time(hour + 1, 0),
                court_number=court,
                court_label=f"Court {court}",
                block_minutes=60,
                is_active=True,
            )
            slots.append(slot)
    session.add_all(slots)
    session.commit()
    for slot in slots:
        session.refresh(slot)

    # Create some matches
    matches = []
    for i in range(1, 5):
        match = Match(
            tournament_id=tournament.id,
            event_id=event.id,
            schedule_version_id=version.id,
            match_code=f"TEST_WF_01_{i:02d}",
            match_type="WF",
            round_number=1,
            round_index=1,
            sequence_in_round=i,
            duration_minutes=60,
            team_a_id=teams[i - 1].id if i <= len(teams) else None,
            team_b_id=teams[i].id if i < len(teams) else None,
            placeholder_side_a=teams[i - 1].name if i <= len(teams) else "TBD",
            placeholder_side_b=teams[i].name if i < len(teams) else "TBD",
            status="unscheduled",
        )
        matches.append(match)
    session.add_all(matches)
    session.commit()
    for match in matches:
        session.refresh(match)

    return {
        "tournament_id": tournament.id,
        "version_id": version.id,
        "event_id": event.id,
        "teams": teams,
        "slots": slots,
        "matches": matches,
    }


# ============================================================================
# P5: Tests
# ============================================================================


def test_draft_only_guard(client: TestClient, session: Session, setup_tournament):
    """Test that build endpoint rejects non-draft versions"""
    setup = setup_tournament
    tournament_id = setup["tournament_id"]
    version_id = setup["version_id"]

    # Finalize the version
    version = session.get(ScheduleVersion, version_id)
    version.status = "final"
    session.add(version)
    session.commit()

    # Try to build - should fail
    response = client.post(f"/api/tournaments/{tournament_id}/schedule/versions/{version_id}/build")

    assert response.status_code == 400
    assert "SCHEDULE_VERSION_NOT_DRAFT" in response.json()["detail"]


def test_build_schedule_success(client: TestClient, session: Session, setup_tournament):
    """Test successful schedule build"""
    setup = setup_tournament
    tournament_id = setup["tournament_id"]
    version_id = setup["version_id"]

    # Build schedule
    response = client.post(f"/api/tournaments/{tournament_id}/schedule/versions/{version_id}/build?clear_existing=true")

    assert response.status_code == 200
    data = response.json()

    # Check response structure
    assert data["status"] == "success"
    assert data["tournament_id"] == tournament_id
    assert data["schedule_version_id"] == version_id
    assert data["clear_existing"] is True
    assert data["dry_run"] is False

    # Check summary exists
    assert "summary" in data
    assert "slots_generated" in data["summary"]
    assert "matches_generated" in data["summary"]

    # Check warnings list exists
    assert "warnings" in data
    assert isinstance(data["warnings"], list)


def test_build_schedule_all_slot_court_labels_are_strings(client: TestClient, session: Session, setup_tournament):
    """Regression: full Build Schedule must never bind a list to court_label."""
    setup = setup_tournament
    tournament_id = setup["tournament_id"]
    version_id = setup["version_id"]

    response = client.post(
        f"/api/tournaments/{tournament_id}/schedule/versions/{version_id}/build?clear_existing=true"
    )
    assert response.status_code == 200, response.text

    slots = session.exec(select(ScheduleSlot).where(ScheduleSlot.schedule_version_id == version_id)).all()
    assert len(slots) > 0
    for slot in slots:
        assert isinstance(slot.court_label, str), (
            f"court_label must be str, got {type(slot.court_label).__name__} for slot id={slot.id}"
        )


def test_idempotency(client: TestClient, session: Session, setup_tournament):
    """Test that running build twice produces identical results"""
    setup = setup_tournament
    tournament_id = setup["tournament_id"]
    version_id = setup["version_id"]

    # First build
    response1 = client.post(
        f"/api/tournaments/{tournament_id}/schedule/versions/{version_id}/build?clear_existing=true"
    )
    assert response1.status_code == 200

    # Get assignment count after first build
    assignments1 = session.exec(select(MatchAssignment).where(MatchAssignment.schedule_version_id == version_id)).all()
    count1 = len(assignments1)
    sorted([a.id for a in assignments1])

    # Second build (should clear and rebuild identically)
    response2 = client.post(
        f"/api/tournaments/{tournament_id}/schedule/versions/{version_id}/build?clear_existing=true"
    )
    assert response2.status_code == 200

    # Get assignment count after second build
    assignments2 = session.exec(select(MatchAssignment).where(MatchAssignment.schedule_version_id == version_id)).all()
    count2 = len(assignments2)

    # Should have same number of assignments
    assert count1 == count2

    # Summaries should be identical
    assert response1.json()["summary"]["assignments_created"] == response2.json()["summary"]["assignments_created"]


def test_wf_grouping_conditional(client: TestClient, session: Session, setup_tournament):
    """Test that WF grouping runs when avoid edges exist"""
    setup = setup_tournament
    tournament_id = setup["tournament_id"]
    version_id = setup["version_id"]
    event_id = setup["event_id"]
    teams = setup["teams"]

    # Add avoid edges
    edge = TeamAvoidEdge(event_id=event_id, team_id_a=teams[0].id, team_id_b=teams[1].id, reason="test conflict")
    session.add(edge)
    session.commit()

    # Build schedule
    response = client.post(f"/api/tournaments/{tournament_id}/schedule/versions/{version_id}/build")

    assert response.status_code == 200

    # Check that teams have wf_group_index assigned
    team1 = session.get(Team, teams[0].id)
    team2 = session.get(Team, teams[1].id)

    assert team1.wf_group_index is not None
    assert team2.wf_group_index is not None


def test_inject_teams_is_ignored_by_route_guard(client: TestClient, session: Session):
    """Route forces inject_teams=False; even ?inject_teams=true must not produce injection warnings."""
    tournament = Tournament(
        name="No Teams Test", location="Test", timezone="UTC", start_date=date(2026, 1, 15), end_date=date(2026, 1, 15)
    )
    session.add(tournament)
    session.commit()
    session.refresh(tournament)

    day = TournamentDay(
        tournament_id=tournament.id,
        date=date(2026, 1, 15),
        is_active=True,
        start_time=time(9, 0),
        end_time=time(18, 0),
        courts_available=2,
    )
    session.add(day)
    session.commit()

    version = ScheduleVersion(tournament_id=tournament.id, version_number=1, status="draft")
    session.add(version)
    session.commit()
    session.refresh(version)

    event = Event(
        tournament_id=tournament.id,
        name="Empty Event",
        category="mixed",
        team_count=4,
        draw_plan_json='{"template_type":"RR_ONLY","wf_rounds":0}',
        draw_status="final",
    )
    session.add(event)
    session.commit()

    # Call build with ?inject_teams=true — route guard clamps to False
    response = client.post(f"/api/tournaments/{tournament.id}/schedule/versions/{version.id}/build?inject_teams=true")

    assert response.status_code == 200
    data = response.json()

    # Build must still succeed
    assert data.get("status") == "success"

    # No injection-related warnings (injection is disabled at route level)
    warnings = data.get("warnings", [])
    injection_warnings = [w for w in warnings if w.get("code") in ("NO_TEAMS_FOR_EVENT", "TEAM_INJECTION_FAILED")]
    assert not injection_warnings, f"Route guard should prevent injection; got: {injection_warnings}"


def test_no_teams_no_warning_with_inject_teams_false(client: TestClient, session: Session):
    """Test that inject_teams=False skips injection silently (no warning)"""
    tournament = Tournament(
        name="No Teams Test 2", location="Test", timezone="UTC", start_date=date(2026, 1, 16), end_date=date(2026, 1, 16)
    )
    session.add(tournament)
    session.commit()
    session.refresh(tournament)

    day = TournamentDay(
        tournament_id=tournament.id,
        date=date(2026, 1, 16),
        is_active=True,
        start_time=time(9, 0),
        end_time=time(18, 0),
        courts_available=2,
    )
    session.add(day)
    session.commit()

    version = ScheduleVersion(tournament_id=tournament.id, version_number=1, status="draft")
    session.add(version)
    session.commit()
    session.refresh(version)

    event = Event(
        tournament_id=tournament.id,
        name="Empty Event 2",
        category="mixed",
        team_count=4,
        draw_plan_json='{"template_type":"RR_ONLY","wf_rounds":0}',
        draw_status="final",
    )
    session.add(event)
    session.commit()

    # Build schedule with inject_teams=False (default)
    response = client.post(f"/api/tournaments/{tournament.id}/schedule/versions/{version.id}/build?inject_teams=false")

    assert response.status_code == 200
    data = response.json()

    # Should NOT have warning about no teams (inject_teams=False skips silently)
    warnings = data.get("warnings", [])
    has_no_teams_warning = any(w.get("code") == "NO_TEAMS_FOR_EVENT" for w in warnings)
    assert not has_no_teams_warning, "inject_teams=False should not produce NO_TEAMS_FOR_EVENT warning"


def test_composite_response_structure(client: TestClient, session: Session, setup_tournament):
    """Test that response includes all required sections"""
    setup = setup_tournament
    tournament_id = setup["tournament_id"]
    version_id = setup["version_id"]

    response = client.post(f"/api/tournaments/{tournament_id}/schedule/versions/{version_id}/build")

    assert response.status_code == 200
    data = response.json()

    # Required top-level fields
    assert "status" in data
    assert "tournament_id" in data
    assert "schedule_version_id" in data
    assert "clear_existing" in data
    assert "dry_run" in data
    assert "summary" in data
    assert "warnings" in data

    # Summary fields
    summary = data["summary"]
    assert "slots_generated" in summary
    assert "matches_generated" in summary
    assert "assignments_created" in summary
    assert "unassigned_matches" in summary

    # Optional sections (may or may not be present depending on data)
    # grid, conflicts, wf_conflict_lens


def test_service_function_directly(session: Session, setup_tournament):
    """Test build_schedule_v1 service function directly"""
    setup = setup_tournament
    tournament_id = setup["tournament_id"]
    version_id = setup["version_id"]

    # Call service function
    result = build_schedule_v1(
        session=session, tournament_id=tournament_id, version_id=version_id, clear_existing=True, dry_run=False
    )

    assert result.status == "success"
    assert result.tournament_id == tournament_id
    assert result.schedule_version_id == version_id
    assert result.failed_step is None
    assert result.error_message is None


def test_invalid_tournament(client: TestClient, session: Session):
    """Test that invalid tournament ID is handled"""
    response = client.post("/api/tournaments/99999/schedule/versions/99999/build")

    assert response.status_code == 404  # Invalid tournament returns 404


def test_clear_existing_flag(client: TestClient, session: Session, setup_tournament):
    """Test that clear_existing flag works correctly"""
    setup = setup_tournament
    tournament_id = setup["tournament_id"]
    version_id = setup["version_id"]
    matches = setup["matches"]
    slots = setup["slots"]

    # Manually create an assignment with a specific marker
    assignment = MatchAssignment(
        schedule_version_id=version_id,
        match_id=matches[0].id,
        slot_id=slots[0].id,
        assigned_by="TEST_MARKER",  # Marker to identify our manual assignment
    )
    session.add(assignment)
    session.commit()

    # Build with clear_existing=true
    response = client.post(f"/api/tournaments/{tournament_id}/schedule/versions/{version_id}/build?clear_existing=true")

    assert response.status_code == 200

    # Check that our manual assignment with TEST_MARKER is gone
    manual_assignments = session.exec(
        select(MatchAssignment).where(
            MatchAssignment.schedule_version_id == version_id, MatchAssignment.assigned_by == "TEST_MARKER"
        )
    ).all()

    assert len(manual_assignments) == 0  # Our manual assignment should be cleared


def test_endpoint_returns_grid(client: TestClient, session: Session, setup_tournament):
    """Test that endpoint returns grid payload"""
    setup = setup_tournament
    tournament_id = setup["tournament_id"]
    version_id = setup["version_id"]

    response = client.post(f"/api/tournaments/{tournament_id}/schedule/versions/{version_id}/build")

    assert response.status_code == 200
    data = response.json()

    # Grid should be present
    assert "grid" in data
    if data["grid"]:
        assert "slots" in data["grid"]
        assert "matches" in data["grid"]
        assert "assignments" in data["grid"]


def test_wf_to_pools_4_canonical_inventory_counts(client: TestClient, session: Session):
    """
    Canonical WF_TO_POOLS_4 inventory: 16 teams, 2 WF rounds, guarantee 5.
    Assert: 40 matches total, WF R1=8, WF R2=8, pool RR=24.
    Uses build_schedule (match generation only allowed via orchestrator).
    """
    tournament = Tournament(
        name="Canonical WF Test",
        location="Test",
        timezone="America/New_York",
        start_date=date(2026, 2, 20),
        end_date=date(2026, 2, 22),
        court_names=["Court 1", "Court 2"],
    )
    session.add(tournament)
    session.commit()
    session.refresh(tournament)

    day = TournamentDay(
        tournament_id=tournament.id,
        date=date(2026, 2, 20),
        is_active=True,
        start_time=time(9, 0),
        end_time=time(18, 0),
        courts_available=2,
    )
    session.add(day)
    session.commit()

    version = ScheduleVersion(tournament_id=tournament.id, version_number=1, status="draft")
    session.add(version)
    session.commit()
    session.refresh(version)

    event = Event(
        tournament_id=tournament.id,
        name="Mixed",
        category="mixed",
        team_count=16,
        draw_plan_json=json.dumps({"template_type": "WF_TO_POOLS_4", "wf_rounds": 2, "guarantee": 5}),
        draw_status="final",
        wf_block_minutes=60,
        standard_block_minutes=105,
    )
    session.add(event)
    session.commit()
    session.refresh(event)

    for i in range(1, 17):
        team = Team(event_id=event.id, name=f"Seed {i} Team", seed=i, rating=1000.0 + i)
        session.add(team)
    session.commit()

    resp = client.post(
        f"/api/tournaments/{tournament.id}/schedule/versions/{version.id}/build?clear_existing=true",
    )
    assert resp.status_code == 200, resp.text
    build_data = resp.json()
    data = build_data.get("summary", {})
    assert data.get("matches_generated") == 40, f"Expected 40 matches, got {data.get('matches_generated')}"

    matches = session.exec(
        select(Match).where(Match.schedule_version_id == version.id, Match.event_id == event.id)
    ).all()

    assert len(matches) == 40

    wf_r1 = [m for m in matches if m.match_type == "WF" and m.round_number == 1]
    wf_r2 = [m for m in matches if m.match_type == "WF" and m.round_number == 2]
    pool_rr = [m for m in matches if m.match_type == "RR" and "POOL" in m.match_code and "RR" in m.match_code]

    assert len(wf_r1) == 8, f"WF round 1: expected 8, got {len(wf_r1)}"
    assert len(wf_r2) == 8, f"WF round 2: expected 8, got {len(wf_r2)}"
    assert len(pool_rr) == 24, f"Pool RR: expected 24, got {len(pool_rr)}"

    # R2 matches have dependency pointers
    for m in wf_r2:
        assert m.source_match_a_id is not None or m.source_match_b_id is not None
        assert m.team_a_id is None and m.team_b_id is None
