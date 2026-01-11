"""
Tests for Who-Knows-Who Admin Tooling V1

Tests:
- Bulk avoid-edges endpoint (pairs and link groups)
- Dry-run mode
- Teams endpoint with grouping
- WF conflict lens endpoint
"""

from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine, select
from sqlmodel.pool import StaticPool

from app.database import get_session
from app.main import app
from app.models.event import Event
from app.models.team import Team
from app.models.team_avoid_edge import TeamAvoidEdge
from app.models.tournament import Tournament
from app.utils.wf_grouping import assign_wf_groups_v1

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


@pytest.fixture(name="setup_event_with_teams")
def setup_event_with_teams_fixture(session: Session):
    """Setup event with 8 teams"""
    # Create tournament
    tournament = Tournament(
        name="Admin Tooling Test",
        location="Test Location",
        timezone="America/New_York",
        start_date=date(2026, 1, 12),
        end_date=date(2026, 1, 14),
    )
    session.add(tournament)
    session.commit()
    session.refresh(tournament)

    # Create event
    event = Event(
        tournament_id=tournament.id,
        name="Test Event",
        category="mixed",
        team_count=8,
        draw_plan_json='{"template_type":"WF_TO_POOLS_4","wf_rounds":2}',
        draw_status="final",
    )
    session.add(event)
    session.commit()
    session.refresh(event)

    # Create 8 teams
    teams = []
    for i in range(1, 9):
        team = Team(event_id=event.id, name=f"Team {i}", seed=i, rating=1000.0 + i)
        session.add(team)
        teams.append(team)
    session.commit()
    for team in teams:
        session.refresh(team)

    return {"tournament_id": tournament.id, "event_id": event.id, "teams": teams}


# ============================================================================
# A1: Bulk Avoid-Edges Tests
# ============================================================================


def test_bulk_create_pairs(client: TestClient, session: Session, setup_event_with_teams):
    """Test bulk creation with pairs format"""
    setup = setup_event_with_teams
    event_id = setup["event_id"]
    teams = setup["teams"]

    response = client.post(
        f"/api/events/{event_id}/avoid-edges/bulk",
        json={
            "pairs": [
                {"team_a_id": teams[0].id, "team_b_id": teams[1].id, "reason": "Same club"},
                {"team_a_id": teams[2].id, "team_b_id": teams[3].id, "reason": "Same facility"},
            ]
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["dry_run"] is False
    assert data["created_count"] == 2
    assert data["rejected_count"] == 0
    assert len(data["created_edges_sample"]) == 2


def test_bulk_create_link_groups(client: TestClient, session: Session, setup_event_with_teams):
    """Test bulk creation with link_groups format"""
    setup = setup_event_with_teams
    event_id = setup["event_id"]
    teams = setup["teams"]

    # Link group with 4 teams should create 6 edges (complete graph)
    response = client.post(
        f"/api/events/{event_id}/avoid-edges/bulk",
        json={
            "link_groups": [
                {
                    "code": "ESPLANADE",
                    "team_ids": [teams[0].id, teams[1].id, teams[2].id, teams[3].id],
                    "reason": "Same club",
                }
            ]
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["created_count"] == 6  # 4 choose 2 = 6
    assert data["rejected_count"] == 0


def test_bulk_dry_run_mode(client: TestClient, session: Session, setup_event_with_teams):
    """Test dry-run mode does not create database rows"""
    setup = setup_event_with_teams
    event_id = setup["event_id"]
    teams = setup["teams"]

    # Count edges before
    edges_before = session.exec(select(TeamAvoidEdge).where(TeamAvoidEdge.event_id == event_id)).all()
    count_before = len(edges_before)

    # Dry run
    response = client.post(
        f"/api/events/{event_id}/avoid-edges/bulk?dry_run=true",
        json={
            "link_groups": [
                {
                    "code": "ESPLANADE",
                    "team_ids": [teams[0].id, teams[1].id, teams[2].id, teams[3].id],
                    "reason": "Same club",
                }
            ]
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["dry_run"] is True
    assert data["would_create_count"] == 6
    assert "would_create_edges" in data
    assert len(data["would_create_edges"]) == 6

    # Count edges after
    edges_after = session.exec(select(TeamAvoidEdge).where(TeamAvoidEdge.event_id == event_id)).all()
    count_after = len(edges_after)

    # Should be unchanged
    assert count_after == count_before


def test_bulk_rejects_self_edges(client: TestClient, session: Session, setup_event_with_teams):
    """Test that self-edges are rejected"""
    setup = setup_event_with_teams
    event_id = setup["event_id"]
    teams = setup["teams"]

    response = client.post(
        f"/api/events/{event_id}/avoid-edges/bulk",
        json={
            "pairs": [
                {"team_a_id": teams[0].id, "team_b_id": teams[0].id}  # Self-edge
            ]
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["created_count"] == 0
    assert data["rejected_count"] == 1
    assert data["rejected_items"][0]["error"] == "SELF_EDGE"


def test_bulk_rejects_invalid_team_ids(client: TestClient, session: Session, setup_event_with_teams):
    """Test that invalid team IDs are rejected"""
    setup = setup_event_with_teams
    event_id = setup["event_id"]
    teams = setup["teams"]

    response = client.post(
        f"/api/events/{event_id}/avoid-edges/bulk",
        json={
            "pairs": [
                {"team_a_id": teams[0].id, "team_b_id": 99999}  # Invalid ID
            ]
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["created_count"] == 0
    assert data["rejected_count"] == 1
    assert data["rejected_items"][0]["error"] == "INVALID_TEAM_ID"


def test_bulk_idempotent_duplicates(client: TestClient, session: Session, setup_event_with_teams):
    """Test that duplicate edges are skipped (idempotent)"""
    setup = setup_event_with_teams
    event_id = setup["event_id"]
    teams = setup["teams"]

    # Create once
    response1 = client.post(
        f"/api/events/{event_id}/avoid-edges/bulk",
        json={"pairs": [{"team_a_id": teams[0].id, "team_b_id": teams[1].id}]},
    )
    assert response1.json()["created_count"] == 1

    # Create again (should skip)
    response2 = client.post(
        f"/api/events/{event_id}/avoid-edges/bulk",
        json={"pairs": [{"team_a_id": teams[0].id, "team_b_id": teams[1].id}]},
    )
    assert response2.json()["created_count"] == 0
    assert response2.json()["skipped_duplicates_count"] == 1


def test_bulk_deterministic_ordering(client: TestClient, session: Session, setup_event_with_teams):
    """Test that dry-run output is deterministically ordered"""
    setup = setup_event_with_teams
    event_id = setup["event_id"]
    teams = setup["teams"]

    # Run dry-run twice
    request_json = {
        "pairs": [
            {"team_a_id": teams[3].id, "team_b_id": teams[1].id},
            {"team_a_id": teams[0].id, "team_b_id": teams[2].id},
        ]
    }

    response1 = client.post(f"/api/events/{event_id}/avoid-edges/bulk?dry_run=true", json=request_json)
    response2 = client.post(f"/api/events/{event_id}/avoid-edges/bulk?dry_run=true", json=request_json)

    edges1 = response1.json()["would_create_edges"]
    edges2 = response2.json()["would_create_edges"]

    # Should be identical and sorted
    assert edges1 == edges2

    # Verify sorted by team_id_a, team_id_b
    for i in range(len(edges1) - 1):
        edge1 = edges1[i]
        edge2 = edges1[i + 1]
        assert (edge1["team_id_a"], edge1["team_id_b"]) <= (edge2["team_id_a"], edge2["team_id_b"])


# ============================================================================
# A2: Teams Endpoint with Grouping Tests
# ============================================================================


def test_teams_endpoint_includes_grouping(client: TestClient, session: Session, setup_event_with_teams):
    """Test that teams endpoint includes wf_group_index"""
    setup = setup_event_with_teams
    event_id = setup["event_id"]

    # Assign groups first
    assign_wf_groups_v1(session, event_id, clear_existing=True)

    # Get teams with grouping
    response = client.get(f"/api/events/{event_id}/teams?include_grouping=true")

    assert response.status_code == 200
    teams = response.json()
    assert len(teams) > 0

    # Check that wf_group_index is present
    for team in teams:
        assert "wf_group_index" in team
        assert team["wf_group_index"] is not None


# ============================================================================
# B1: WF Conflict Lens Tests
# ============================================================================


def test_wf_conflict_lens_graph_summary(client: TestClient, session: Session, setup_event_with_teams):
    """Test WF conflict lens graph summary"""
    setup = setup_event_with_teams
    event_id = setup["event_id"]
    teams = setup["teams"]

    # Create some avoid edges
    client.post(
        f"/api/events/{event_id}/avoid-edges/bulk",
        json={
            "pairs": [
                {"team_a_id": teams[0].id, "team_b_id": teams[1].id},
                {"team_a_id": teams[1].id, "team_b_id": teams[2].id},
                {"team_a_id": teams[3].id, "team_b_id": teams[4].id},
            ]
        },
    )

    # Get conflict lens
    response = client.get(f"/api/events/{event_id}/waterfall/conflicts")

    assert response.status_code == 200
    data = response.json()

    assert data["event_id"] == event_id
    assert "graph_summary" in data
    assert data["graph_summary"]["team_count"] == 8
    assert data["graph_summary"]["avoid_edges_count"] == 3
    assert len(data["graph_summary"]["top_degree_teams"]) > 0


def test_wf_conflict_lens_with_grouping(client: TestClient, session: Session, setup_event_with_teams):
    """Test WF conflict lens with grouping assigned"""
    setup = setup_event_with_teams
    event_id = setup["event_id"]
    teams = setup["teams"]

    # Create avoid edges
    client.post(
        f"/api/events/{event_id}/avoid-edges/bulk",
        json={
            "pairs": [
                {"team_a_id": teams[0].id, "team_b_id": teams[1].id},
                {"team_a_id": teams[2].id, "team_b_id": teams[3].id},
            ]
        },
    )

    # Assign groups
    assign_wf_groups_v1(session, event_id, clear_existing=True)

    # Get conflict lens
    response = client.get(f"/api/events/{event_id}/waterfall/conflicts")

    assert response.status_code == 200
    data = response.json()

    assert "grouping_summary" in data
    assert data["grouping_summary"] is not None
    assert data["grouping_summary"]["groups_count"] == 2  # 8 teams → 2 groups
    assert "separation_effectiveness" in data
    assert data["separation_effectiveness"] is not None


def test_wf_conflict_lens_separation_rate(client: TestClient, session: Session, setup_event_with_teams):
    """Test that separation rate is calculated correctly"""
    setup = setup_event_with_teams
    event_id = setup["event_id"]
    teams = setup["teams"]

    # Create 4 edges that can be perfectly separated (2 per group)
    client.post(
        f"/api/events/{event_id}/avoid-edges/bulk",
        json={
            "pairs": [
                {"team_a_id": teams[0].id, "team_b_id": teams[1].id},
                {"team_a_id": teams[2].id, "team_b_id": teams[3].id},
                {"team_a_id": teams[4].id, "team_b_id": teams[5].id},
                {"team_a_id": teams[6].id, "team_b_id": teams[7].id},
            ]
        },
    )

    # Assign groups
    assign_wf_groups_v1(session, event_id, clear_existing=True)

    # Get conflict lens
    response = client.get(f"/api/events/{event_id}/waterfall/conflicts")

    assert response.status_code == 200
    data = response.json()

    # With good grouping, should have 0 internal conflicts
    assert data["grouping_summary"]["total_internal_conflicts"] == 0
    assert data["separation_effectiveness"]["separation_rate"] == 1.0
    assert len(data["unavoidable_conflicts"]) == 0
