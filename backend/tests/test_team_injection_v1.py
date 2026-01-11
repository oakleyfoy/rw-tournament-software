"""
Comprehensive test suite for Team Injection V1

Tests all phases:
- Phase 1: Data Model (Team and Match FK fields)
- Phase 2: Team CRUD API
- Phase 3 & 4: Team Injection Logic and Endpoint
- Phase 5: Grid endpoint with teams dictionary
"""

import json
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.models.event import Event
from app.models.match import Match
from app.models.schedule_version import ScheduleVersion
from app.models.team import Team
from app.models.tournament import Tournament


@pytest.fixture
def setup_test_tournament(client: TestClient, session: Session):
    """Create a test tournament with an 8-team bracket event"""
    # Create tournament
    tournament_data = {
        "name": "Test Tournament",
        "location": "Test Location",
        "timezone": "America/New_York",
        "start_date": date(2026, 1, 15).isoformat(),
        "end_date": date(2026, 1, 17).isoformat(),
    }
    t_response = client.post("/api/tournaments", json=tournament_data)
    tournament = t_response.json()

    # Create an 8-team bracket event
    event_data = {
        "category": "mixed",
        "name": "8-Team Bracket",
        "team_count": 8,
        "draw_plan_json": json.dumps({"template_type": "CANONICAL_32", "wf_rounds": 2, "guarantee": 4}),
        "draw_status": "final",
        "wf_block_minutes": 60,
        "standard_block_minutes": 120,
        "guarantee_selected": 4,
    }
    e_response = client.post(f"/api/tournaments/{tournament['id']}/events", json=event_data)
    event = e_response.json()

    # Generate matches
    client.post(
        f"/api/tournaments/{tournament['id']}/schedule/matches/generate",
        json={"event_id": event["id"], "wipe_existing": True},
    )

    # Get the schedule version
    version = session.exec(select(ScheduleVersion).where(ScheduleVersion.tournament_id == tournament["id"])).first()

    return {"tournament": tournament, "event": event, "version": version}


# ============================================================================
# Phase 2 Tests: Team CRUD API
# ============================================================================


def test_create_team(client: TestClient, setup_test_tournament):
    """Test creating a team"""
    event = setup_test_tournament["event"]

    team_data = {"name": "Test Team", "seed": 1, "rating": 1500.0}

    response = client.post(f"/api/events/{event['id']}/teams", json=team_data)
    assert response.status_code == 201

    team = response.json()
    assert team["name"] == "Test Team"
    assert team["seed"] == 1
    assert team["rating"] == 1500.0
    assert team["event_id"] == event["id"]


def test_get_teams_deterministic_order(client: TestClient, session: Session, setup_test_tournament):
    """Test teams are returned in deterministic order"""
    event = session.exec(select(Event)).first()
    assert event is not None

    # Clean up existing teams
    existing_teams = session.exec(select(Team).where(Team.event_id == event.id)).all()
    for team in existing_teams:
        session.delete(team)
    session.commit()

    # Create teams with different seeds
    teams_data = [
        {"name": "Seed 2", "seed": 2, "rating": 1400.0},
        {"name": "Seed 1", "seed": 1, "rating": 1500.0},
        {"name": "Seed 3", "seed": 3, "rating": 1300.0},
    ]

    for team_data in teams_data:
        client.post(f"/api/events/{event.id}/teams", json=team_data)

    # Get teams
    response = client.get(f"/api/events/{event.id}/teams")
    assert response.status_code == 200

    teams = response.json()
    assert len(teams) == 3

    # Verify ordering: seed ascending
    assert teams[0]["seed"] == 1
    assert teams[1]["seed"] == 2
    assert teams[2]["seed"] == 3


def test_update_team(client: TestClient, session: Session, setup_test_tournament):
    """Test updating a team"""
    event = session.exec(select(Event)).first()
    assert event is not None

    # Create a team
    team_data = {"name": "Original Name", "seed": 1, "rating": 1500.0}
    create_response = client.post(f"/api/events/{event.id}/teams", json=team_data)
    team = create_response.json()

    # Update it
    update_data = {"name": "Updated Name", "rating": 1600.0}
    response = client.patch(f"/api/events/{event.id}/teams/{team['id']}", json=update_data)
    assert response.status_code == 200

    updated_team = response.json()
    assert updated_team["name"] == "Updated Name"
    assert updated_team["rating"] == 1600.0
    assert updated_team["seed"] == 1  # Unchanged


def test_delete_team(client: TestClient, session: Session, setup_test_tournament):
    """Test deleting a team"""
    event = session.exec(select(Event)).first()
    assert event is not None

    # Create a team
    team_data = {"name": "To Delete", "seed": 99}
    create_response = client.post(f"/api/events/{event.id}/teams", json=team_data)
    team = create_response.json()

    # Delete it
    response = client.delete(f"/api/events/{event.id}/teams/{team['id']}")
    assert response.status_code == 204

    # Verify it's gone
    get_response = client.get(f"/api/events/{event.id}/teams")
    teams = get_response.json()
    assert not any(t["id"] == team["id"] for t in teams)


def test_unique_constraints(client: TestClient, session: Session, setup_test_tournament):
    """Test unique constraints on seed and name"""
    event = session.exec(select(Event)).first()
    assert event is not None

    # Clean up
    existing_teams = session.exec(select(Team).where(Team.event_id == event.id)).all()
    for team in existing_teams:
        session.delete(team)
    session.commit()

    # Create first team
    team1 = {"name": "Team A", "seed": 1}
    client.post(f"/api/events/{event.id}/teams", json=team1)

    # Try duplicate seed
    team2 = {"name": "Team B", "seed": 1}
    response = client.post(f"/api/events/{event.id}/teams", json=team2)
    assert response.status_code == 409

    # Try duplicate name
    team3 = {"name": "Team A", "seed": 2}
    response = client.post(f"/api/events/{event.id}/teams", json=team3)
    assert response.status_code == 409


# ============================================================================
# Phase 3 & 4 Tests: Team Injection Logic and Endpoint
# ============================================================================


def test_bracket_injection_8_teams(client: TestClient, session: Session, setup_test_tournament):
    """Test 8-team bracket injection assigns QFs correctly"""
    # Find or create bracket event
    event = session.exec(select(Event).where(Event.team_count == 8)).first()

    if not event or not event.draw_plan_json or "CANONICAL_32" not in event.draw_plan_json:
        pytest.skip("No 8-team bracket event available")

    version = session.exec(select(ScheduleVersion).where(ScheduleVersion.tournament_id == event.tournament_id)).first()

    if not version:
        pytest.skip("No schedule version available")

    # Clean up and create 8 teams
    existing_teams = session.exec(select(Team).where(Team.event_id == event.id)).all()
    for team in existing_teams:
        session.delete(team)
    session.commit()

    for i in range(1, 9):
        team_data = {"name": f"Seed {i} Team", "seed": i, "rating": 2000.0 - i * 100}
        client.post(f"/api/events/{event.id}/teams", json=team_data)

    # Inject teams
    response = client.post(
        f"/api/events/{event.id}/schedule/versions/{version.id}/inject-teams", params={"clear_existing": True}
    )

    assert response.status_code == 200
    result = response.json()
    assert result["teams_count"] == 8
    assert result["matches_updated_count"] == 4
    assert result["injection_type"] == "bracket"

    # Verify QF assignments
    matches = session.exec(
        select(Match).where(Match.event_id == event.id, Match.schedule_version_id == version.id)
    ).all()

    qf_matches = [m for m in matches if "QF" in m.match_code]
    qf_matches.sort(key=lambda m: m.match_code)

    teams = session.exec(select(Team).where(Team.event_id == event.id)).all()
    teams_by_id = {t.id: t for t in teams}

    # Expected: QF1=1v8, QF2=4v5, QF3=3v6, QF4=2v7
    expected = [(1, 8), (4, 5), (3, 6), (2, 7)]

    for i, match in enumerate(qf_matches):
        team_a = teams_by_id[match.team_a_id]
        team_b = teams_by_id[match.team_b_id]
        expected_a, expected_b = expected[i]

        assert team_a.seed == expected_a
        assert team_b.seed == expected_b

    # Verify SF/Final have no assignments
    sf_final = [m for m in matches if "SF" in m.match_code or "FINAL" in m.match_code]
    for match in sf_final:
        assert match.team_a_id is None
        assert match.team_b_id is None


def test_idempotency(client: TestClient, session: Session, setup_test_tournament):
    """Test injection is idempotent"""
    event = session.exec(select(Event).where(Event.team_count == 8)).first()

    if not event or not event.draw_plan_json or "CANONICAL_32" not in event.draw_plan_json:
        pytest.skip("No 8-team bracket event available")

    version = session.exec(select(ScheduleVersion).where(ScheduleVersion.tournament_id == event.tournament_id)).first()

    if not version:
        pytest.skip("No schedule version available")

    # Run injection twice
    response1 = client.post(
        f"/api/events/{event.id}/schedule/versions/{version.id}/inject-teams", params={"clear_existing": True}
    )

    response2 = client.post(
        f"/api/events/{event.id}/schedule/versions/{version.id}/inject-teams", params={"clear_existing": True}
    )

    assert response1.status_code == 200
    assert response2.status_code == 200
    assert response1.json() == response2.json()


def test_reject_more_than_8_teams(client: TestClient, session: Session, setup_test_tournament):
    """Test that >8 teams is rejected"""
    # Create an event with 9 teams (should be rejected)
    tournament = session.exec(select(Tournament)).first()
    assert tournament is not None

    # Create event with team_count = 9
    event_data = {
        "category": "mixed",
        "name": "9 Team Test Event",
        "team_count": 9,
        "notes": "Test rejection of >8 teams",
    }

    event_response = client.post(f"/api/tournaments/{tournament.id}/events", json=event_data)
    if event_response.status_code != 201:
        pytest.skip("Could not create 9-team event")

    event = event_response.json()

    # Create 9 teams
    for i in range(1, 10):
        team_data = {"name": f"Team {i}", "seed": i, "rating": 2000.0 - i * 50}
        client.post(f"/api/events/{event['id']}/teams", json=team_data)

    # Get schedule version
    version = session.exec(select(ScheduleVersion).where(ScheduleVersion.tournament_id == tournament.id)).first()

    if not version:
        pytest.skip("No schedule version available")

    # Try to inject teams - should fail with 400
    response = client.post(
        f"/api/events/{event['id']}/schedule/versions/{version.id}/inject-teams", params={"clear_existing": True}
    )

    assert response.status_code == 400
    error_detail = response.json().get("detail", "")
    assert "8 teams" in error_detail.lower() or "up to 8" in error_detail.lower()

    # Clean up
    client.delete(f"/api/tournaments/{tournament.id}/events/{event['id']}")


def test_no_premature_resolution(client: TestClient, session: Session, setup_test_tournament):
    """Test that SF/Final don't get team IDs prematurely"""
    event = session.exec(select(Event).where(Event.team_count == 8)).first()

    if not event or not event.draw_plan_json or "CANONICAL_32" not in event.draw_plan_json:
        pytest.skip("No 8-team bracket event available")

    version = session.exec(select(ScheduleVersion).where(ScheduleVersion.tournament_id == event.tournament_id)).first()

    if not version:
        pytest.skip("No schedule version available")

    # Inject teams
    client.post(f"/api/events/{event.id}/schedule/versions/{version.id}/inject-teams", params={"clear_existing": True})

    # Check SF/Final
    matches = session.exec(
        select(Match).where(Match.event_id == event.id, Match.schedule_version_id == version.id)
    ).all()

    sf_final = [m for m in matches if "SF" in m.match_code or "FINAL" in m.match_code]

    for match in sf_final:
        assert match.team_a_id is None, f"{match.match_code} should not have team_a_id"
        assert match.team_b_id is None, f"{match.match_code} should not have team_b_id"


# ============================================================================
# Phase 5 Tests: Grid Endpoint with Teams
# ============================================================================


def test_grid_includes_teams_dictionary(client: TestClient, session: Session, setup_test_tournament):
    """Test that grid endpoint returns teams dictionary"""
    tournament = session.exec(select(Tournament)).first()
    version = session.exec(select(ScheduleVersion)).first()

    assert tournament is not None
    assert version is not None

    response = client.get(f"/api/tournaments/{tournament.id}/schedule/grid", params={"schedule_version_id": version.id})

    assert response.status_code == 200
    grid = response.json()

    assert "teams" in grid
    assert isinstance(grid["teams"], list)

    # If there are any teams, verify structure
    if grid["teams"]:
        team = grid["teams"][0]
        assert "id" in team
        assert "name" in team
        assert "seed" in team
        assert "event_id" in team


def test_grid_matches_include_team_ids(client: TestClient, session: Session, setup_test_tournament):
    """Test that grid matches include team_a_id and team_b_id"""
    tournament = session.exec(select(Tournament)).first()
    version = session.exec(select(ScheduleVersion)).first()

    assert tournament is not None
    assert version is not None

    response = client.get(f"/api/tournaments/{tournament.id}/schedule/grid", params={"schedule_version_id": version.id})

    assert response.status_code == 200
    grid = response.json()

    assert "matches" in grid

    if grid["matches"]:
        match = grid["matches"][0]
        # These fields should exist (can be null)
        assert "team_a_id" in match
        assert "team_b_id" in match
        assert "placeholder_side_a" in match
        assert "placeholder_side_b" in match


# ============================================================================
# Integration Test
# ============================================================================


def test_full_workflow(client: TestClient, session: Session, setup_test_tournament):
    """Test complete workflow: create teams → inject → verify grid"""
    # This is a high-level integration test
    # Find suitable event
    event = session.exec(select(Event).where(Event.team_count == 8)).first()

    if not event or not event.draw_plan_json or "CANONICAL_32" not in event.draw_plan_json:
        pytest.skip("No 8-team bracket event available")

    version = session.exec(select(ScheduleVersion).where(ScheduleVersion.tournament_id == event.tournament_id)).first()

    if not version:
        pytest.skip("No schedule version available")

    # 1. Create 8 teams
    existing_teams = session.exec(select(Team).where(Team.event_id == event.id)).all()
    for team in existing_teams:
        session.delete(team)
    session.commit()

    for i in range(1, 9):
        client.post(f"/api/events/{event.id}/teams", json={"name": f"Team {i}", "seed": i, "rating": 2000.0 - i * 50})

    # 2. Inject teams
    inject_response = client.post(
        f"/api/events/{event.id}/schedule/versions/{version.id}/inject-teams", params={"clear_existing": True}
    )
    assert inject_response.status_code == 200

    # 3. Get grid and verify
    grid_response = client.get(
        f"/api/tournaments/{event.tournament_id}/schedule/grid", params={"schedule_version_id": version.id}
    )
    assert grid_response.status_code == 200

    grid = grid_response.json()

    # Verify teams are in grid
    assert len(grid["teams"]) >= 8

    # Verify matches have team IDs
    qf_matches = [m for m in grid["matches"] if "QF" in m.get("match_code", "")]
    assert len(qf_matches) == 4

    for qf in qf_matches:
        assert qf["team_a_id"] is not None
        assert qf["team_b_id"] is not None
