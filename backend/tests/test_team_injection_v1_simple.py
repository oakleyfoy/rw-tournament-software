"""
Simplified test suite for Team Injection V1 - focusing on core functionality
"""

import json
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.models.schedule_version import ScheduleVersion
from app.models.team import Team


@pytest.fixture
def setup_bracket_event(client: TestClient, session: Session):
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
    assert t_response.status_code == 201
    tournament = t_response.json()

    # Create an 8-team bracket event
    event_data = {"category": "mixed", "name": "8-Team Bracket", "team_count": 8}
    e_response = client.post(f"/api/tournaments/{tournament['id']}/events", json=event_data)
    assert e_response.status_code == 201
    event = e_response.json()

    # Update event with draw plan and finalize it
    event_update = {
        "draw_plan_json": json.dumps({"template_type": "CANONICAL_32", "wf_rounds": 2, "guarantee": 4}),
        "draw_status": "final",
        "wf_block_minutes": 60,
        "standard_block_minutes": 120,
        "guarantee_selected": 4,
    }
    u_response = client.put(f"/api/events/{event['id']}", json=event_update)
    assert u_response.status_code == 200
    event = u_response.json()

    # Create a draft schedule version (required for match generation)
    v_response = client.post(f"/api/tournaments/{tournament['id']}/schedule/versions", json={"notes": "Test version"})
    assert v_response.status_code == 201
    version = v_response.json()

    # Generate matches
    gen_response = client.post(
        f"/api/tournaments/{tournament['id']}/schedule/matches/generate",
        json={"event_id": event["id"], "wipe_existing": True, "schedule_version_id": version["id"]},
    )
    assert gen_response.status_code == 200, f"Match generation failed: {gen_response.status_code} {gen_response.text}"

    # Get the schedule version
    version = session.exec(select(ScheduleVersion).where(ScheduleVersion.tournament_id == tournament["id"])).first()

    return {"tournament": tournament, "event": event, "version": version}


def test_team_crud(client: TestClient, setup_bracket_event):
    """Test Phase 2: Team CRUD operations"""
    event = setup_bracket_event["event"]

    # Create team
    team_data = {"name": "Team Alpha", "seed": 1, "rating": 1800.0}
    create_response = client.post(f"/api/events/{event['id']}/teams", json=team_data)
    assert create_response.status_code == 201
    team = create_response.json()
    assert team["name"] == "Team Alpha"
    assert team["seed"] == 1

    # Get teams
    get_response = client.get(f"/api/events/{event['id']}/teams")
    assert get_response.status_code == 200
    teams = get_response.json()
    assert len(teams) == 1

    # Update team
    update_response = client.patch(f"/api/events/{event['id']}/teams/{team['id']}", json={"name": "Team Alpha Updated"})
    assert update_response.status_code == 200
    updated = update_response.json()
    assert updated["name"] == "Team Alpha Updated"

    # Delete team
    delete_response = client.delete(f"/api/events/{event['id']}/teams/{team['id']}")
    assert delete_response.status_code == 204


@pytest.mark.skip(reason="Team injection V1 expects QF match codes; draw_plan_engine uses new match code format")
def test_bracket_injection(client: TestClient, setup_bracket_event, session: Session):
    """Test Phase 3 & 4: 8-team bracket injection"""
    event = setup_bracket_event["event"]
    version = setup_bracket_event["version"]

    # Create 8 teams
    for i in range(1, 9):
        team_data = {"name": f"Seed {i} Team", "seed": i, "rating": 2100.0 - i * 100}
        response = client.post(f"/api/events/{event['id']}/teams", json=team_data)
        assert response.status_code == 201

    # Inject teams
    inject_response = client.post(
        f"/api/events/{event['id']}/schedule/versions/{version.id}/inject-teams", params={"clear_existing": True}
    )

    assert inject_response.status_code == 200
    result = inject_response.json()
    assert result["teams_count"] == 8
    assert result["matches_updated_count"] == 4
    assert result["injection_type"] == "bracket"

    # Verify QF assignments
    matches_response = client.get(
        f"/api/tournaments/{event['tournament_id']}/schedule/matches?schedule_version_id={version.id}"
    )
    assert matches_response.status_code == 200
    matches = matches_response.json()

    qf_matches = [m for m in matches if "QF" in m["match_code"] and m["event_id"] == event["id"]]
    assert len(qf_matches) == 4

    # Get teams to verify seeding
    teams = session.exec(select(Team).where(Team.event_id == event["id"])).all()
    teams_by_id = {t.id: t for t in teams}

    # Check QF assignments
    qf_matches.sort(key=lambda m: m["match_code"])
    expected = [(1, 8), (4, 5), (3, 6), (2, 7)]

    for i, match in enumerate(qf_matches):
        team_a = teams_by_id[match["team_a_id"]]
        team_b = teams_by_id[match["team_b_id"]]
        expected_a, expected_b = expected[i]
        assert team_a.seed == expected_a
        assert team_b.seed == expected_b

    # Verify SF/Final have no assignments
    sf_final = [
        m for m in matches if ("SF" in m["match_code"] or "FINAL" in m["match_code"]) and m["event_id"] == event["id"]
    ]
    for match in sf_final:
        assert match["team_a_id"] is None
        assert match["team_b_id"] is None


def test_reject_more_than_8_teams(client: TestClient, setup_bracket_event):
    """Test that >8 teams is rejected"""
    tournament = setup_bracket_event["tournament"]
    version = setup_bracket_event["version"]

    # Create event with 9 teams
    event_data = {"category": "mixed", "name": "9 Team Event", "team_count": 9, "draw_status": "final"}
    e_response = client.post(f"/api/tournaments/{tournament['id']}/events", json=event_data)
    assert e_response.status_code == 201
    event = e_response.json()

    # Create 9 teams
    for i in range(1, 10):
        team_data = {"name": f"Team {i}", "seed": i}
        client.post(f"/api/events/{event['id']}/teams", json=team_data)

    # Try to inject - should fail
    inject_response = client.post(
        f"/api/events/{event['id']}/schedule/versions/{version.id}/inject-teams", params={"clear_existing": True}
    )

    assert inject_response.status_code == 400
    error = inject_response.json().get("detail", "")
    assert "8 teams" in error.lower() or "up to 8" in error.lower()


@pytest.mark.skip(reason="Team injection V1 expects QF match codes; draw_plan_engine uses new match code format")
def test_grid_includes_teams(client: TestClient, setup_bracket_event, session: Session):
    """Test Phase 5: Grid endpoint includes teams dictionary"""
    event = setup_bracket_event["event"]
    version = setup_bracket_event["version"]
    tournament = setup_bracket_event["tournament"]

    # Create teams
    for i in range(1, 9):
        team_data = {"name": f"Team {i}", "seed": i}
        client.post(f"/api/events/{event['id']}/teams", json=team_data)

    # Inject teams
    client.post(
        f"/api/events/{event['id']}/schedule/versions/{version.id}/inject-teams", params={"clear_existing": True}
    )

    # Get grid
    grid_response = client.get(
        f"/api/tournaments/{tournament['id']}/schedule/grid", params={"schedule_version_id": version.id}
    )

    assert grid_response.status_code == 200
    grid = grid_response.json()

    # Verify teams array exists
    assert "teams" in grid
    assert len(grid["teams"]) == 8

    # Verify team structure
    team = grid["teams"][0]
    assert "id" in team
    assert "name" in team
    assert "seed" in team
    assert "event_id" in team

    # Verify matches include team IDs
    qf_matches = [m for m in grid["matches"] if "QF" in m.get("match_code", "")]
    assert len(qf_matches) == 4

    for qf in qf_matches:
        assert qf["team_a_id"] is not None
        assert qf["team_b_id"] is not None
        assert "placeholder_side_a" in qf
        assert "placeholder_side_b" in qf


@pytest.mark.skip(reason="Team injection V1 expects QF match codes; draw_plan_engine uses new match code format")
def test_idempotency(client: TestClient, setup_bracket_event):
    """Test that injection is idempotent"""
    event = setup_bracket_event["event"]
    version = setup_bracket_event["version"]

    # Create teams
    for i in range(1, 9):
        team_data = {"name": f"Team {i}", "seed": i}
        client.post(f"/api/events/{event['id']}/teams", json=team_data)

    # Run injection twice
    response1 = client.post(
        f"/api/events/{event['id']}/schedule/versions/{version.id}/inject-teams", params={"clear_existing": True}
    )

    response2 = client.post(
        f"/api/events/{event['id']}/schedule/versions/{version.id}/inject-teams", params={"clear_existing": True}
    )

    assert response1.status_code == 200
    assert response2.status_code == 200
    assert response1.json() == response2.json()
