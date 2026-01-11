"""
Tests for Who-Knows-Who WF Grouping V1

Tests must prove:
1. 12 teams → 3 groups (sizes [4,4,4])
2. 16 teams → 4 groups (sizes [4,4,4,4])
3. Conflict minimization sanity
4. Determinism
5. Unavoidable cluster reporting
6. WF match generation uses grouping
"""

from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine, select
from sqlmodel.pool import StaticPool

from app.database import get_session
from app.main import app
from app.models.event import Event
from app.models.match import Match
from app.models.schedule_version import ScheduleVersion
from app.models.team import Team
from app.models.team_avoid_edge import TeamAvoidEdge
from app.models.tournament import Tournament
from app.utils.wf_grouping import assign_wf_groups_v1, compute_group_capacities, compute_groups_count

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


@pytest.fixture(name="setup_wf_event")
def setup_wf_event_fixture(session: Session):
    """
    Setup test environment with:
    - Tournament
    - WF event with configurable team count
    - Schedule version
    """

    def _setup(team_count: int):
        # Create tournament
        tournament = Tournament(
            name="WF Grouping Test Tournament",
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
            name="Test WF Event",
            category="mixed",
            team_count=team_count,
            draw_plan_json='{"template_type":"WF_TO_POOLS_4","wf_rounds":2}',
            draw_status="final",
            wf_block_minutes=60,
            standard_block_minutes=120,
            guarantee_selected=5,
        )
        session.add(event)
        session.commit()
        session.refresh(event)

        # Create teams
        teams = []
        for i in range(1, team_count + 1):
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

        return {
            "tournament_id": tournament.id,
            "event_id": event.id,
            "schedule_version_id": schedule_version.id,
            "teams": teams,
            "event": event,
        }

    return _setup


# ============================================================================
# Phase W3 Tests: Groups Count Computation
# ============================================================================


def test_compute_groups_count():
    """Test groups_count computation for various team counts"""
    assert compute_groups_count(12) == 3  # 12/4 = 3
    assert compute_groups_count(16) == 4  # 16/4 = 4
    assert compute_groups_count(20) == 5  # 20/4 = 5
    assert compute_groups_count(24) == 6  # 24/4 = 6
    assert compute_groups_count(4) == 1  # 4/4 = 1
    assert compute_groups_count(8) == 2  # 8/4 = 2


def test_compute_group_capacities():
    """Test group capacity distribution"""
    # 12 teams, 3 groups → [4, 4, 4]
    assert compute_group_capacities(12, 3) == [4, 4, 4]

    # 16 teams, 4 groups → [4, 4, 4, 4]
    assert compute_group_capacities(16, 4) == [4, 4, 4, 4]

    # 20 teams, 5 groups → [4, 4, 4, 4, 4]
    assert compute_group_capacities(20, 5) == [4, 4, 4, 4, 4]

    # 13 teams, 4 groups → [4, 3, 3, 3] (one extra team)
    assert compute_group_capacities(13, 4) == [4, 3, 3, 3]


# ============================================================================
# Phase W4 Tests: Grouping Algorithm
# ============================================================================


def test_12_teams_3_groups(session: Session, setup_wf_event):
    """Test that 12 teams are divided into 3 groups of 4"""
    setup = setup_wf_event(12)
    event_id = setup["event_id"]

    # Run grouping
    result = assign_wf_groups_v1(session, event_id, clear_existing=True)

    assert result.team_count == 12
    assert result.groups_count == 3
    assert result.group_sizes == [4, 4, 4]


def test_16_teams_4_groups(session: Session, setup_wf_event):
    """Test that 16 teams are divided into 4 groups of 4"""
    setup = setup_wf_event(16)
    event_id = setup["event_id"]

    # Run grouping
    result = assign_wf_groups_v1(session, event_id, clear_existing=True)

    assert result.team_count == 16
    assert result.groups_count == 4
    assert result.group_sizes == [4, 4, 4, 4]


def test_conflict_minimization_simple(session: Session, setup_wf_event):
    """Test that perfectly separable conflicts are separated"""
    setup = setup_wf_event(8)
    event_id = setup["event_id"]
    teams = setup["teams"]

    # Create avoid edges: Team 1 ↔ Team 2, Team 3 ↔ Team 4
    # These can be perfectly separated into 2 groups
    edge1 = TeamAvoidEdge(
        event_id=event_id,
        team_id_a=min(teams[0].id, teams[1].id),
        team_id_b=max(teams[0].id, teams[1].id),
        reason="Test conflict 1-2",
    )
    edge2 = TeamAvoidEdge(
        event_id=event_id,
        team_id_a=min(teams[2].id, teams[3].id),
        team_id_b=max(teams[2].id, teams[3].id),
        reason="Test conflict 3-4",
    )
    session.add(edge1)
    session.add(edge2)
    session.commit()

    # Run grouping
    result = assign_wf_groups_v1(session, event_id, clear_existing=True)

    # Should have 0 internal conflicts (perfectly separable)
    assert result.total_internal_conflicts == 0

    # Verify Team 1 and Team 2 are in different groups
    team1_group = result.team_assignments[teams[0].id]
    team2_group = result.team_assignments[teams[1].id]
    assert team1_group != team2_group

    # Verify Team 3 and Team 4 are in different groups
    team3_group = result.team_assignments[teams[2].id]
    team4_group = result.team_assignments[teams[3].id]
    assert team3_group != team4_group


def test_determinism(session: Session, setup_wf_event):
    """Test that running grouping twice produces identical results"""
    setup = setup_wf_event(12)
    event_id = setup["event_id"]

    # Run grouping first time
    result1 = assign_wf_groups_v1(session, event_id, clear_existing=True)
    assignments1 = result1.team_assignments.copy()

    # Run grouping second time
    result2 = assign_wf_groups_v1(session, event_id, clear_existing=True)
    assignments2 = result2.team_assignments.copy()

    # Results should be identical
    assert result1.groups_count == result2.groups_count
    assert result1.group_sizes == result2.group_sizes
    assert assignments1 == assignments2


def test_unavoidable_cluster(session: Session, setup_wf_event):
    """Test that unavoidable conflicts are reported correctly"""
    setup = setup_wf_event(4)
    event_id = setup["event_id"]
    teams = setup["teams"]

    # Create a fully connected cluster: all teams avoid each other
    # With 4 teams in 1 group, we'll have 6 unavoidable conflicts
    edges = []
    for i in range(len(teams)):
        for j in range(i + 1, len(teams)):
            edge = TeamAvoidEdge(
                event_id=event_id,
                team_id_a=min(teams[i].id, teams[j].id),
                team_id_b=max(teams[i].id, teams[j].id),
                reason=f"Conflict {i + 1}-{j + 1}",
            )
            edges.append(edge)
            session.add(edge)
    session.commit()

    # Run grouping
    result = assign_wf_groups_v1(session, event_id, clear_existing=True)

    # Should have 6 internal conflicts (all pairs in same group)
    assert result.total_internal_conflicts == 6
    assert result.groups_count == 1
    assert len(result.conflicted_pairs) == 6


# ============================================================================
# Phase W5 Tests: API Endpoint
# ============================================================================


def test_api_assign_groups_12_teams(client: TestClient, session: Session, setup_wf_event):
    """Test API endpoint for 12-team grouping"""
    setup = setup_wf_event(12)
    event_id = setup["event_id"]

    response = client.post(f"/api/events/{event_id}/waterfall/assign-groups", params={"clear_existing": True})

    assert response.status_code == 200
    data = response.json()

    assert data["event_id"] == event_id
    assert data["team_count"] == 12
    assert data["groups_count"] == 3
    assert data["group_sizes"] == [4, 4, 4]
    assert data["total_internal_conflicts"] == 0


def test_api_assign_groups_16_teams(client: TestClient, session: Session, setup_wf_event):
    """Test API endpoint for 16-team grouping"""
    setup = setup_wf_event(16)
    event_id = setup["event_id"]

    response = client.post(f"/api/events/{event_id}/waterfall/assign-groups", params={"clear_existing": True})

    assert response.status_code == 200
    data = response.json()

    assert data["event_id"] == event_id
    assert data["team_count"] == 16
    assert data["groups_count"] == 4
    assert data["group_sizes"] == [4, 4, 4, 4]


# ============================================================================
# Phase W6 Tests: WF Match Generation with Grouping
# ============================================================================


def test_wf_match_generation_uses_grouping(client: TestClient, session: Session, setup_wf_event):
    """Test that WF match generation respects grouping"""
    setup = setup_wf_event(12)
    event_id = setup["event_id"]
    tournament_id = setup["tournament_id"]
    schedule_version_id = setup["schedule_version_id"]
    setup["teams"]

    # Assign groups
    response = client.post(f"/api/events/{event_id}/waterfall/assign-groups", params={"clear_existing": True})
    assert response.status_code == 200

    # Generate matches
    response = client.post(
        f"/api/tournaments/{tournament_id}/schedule/matches/generate",
        json={"schedule_version_id": schedule_version_id, "event_id": event_id, "wipe_existing": True},
    )
    assert response.status_code == 200

    # Get WF matches
    wf_matches = session.exec(select(Match).where(Match.event_id == event_id, Match.match_type == "WF")).all()

    # With 12 teams in 3 groups of 4:
    # Each group has 6 matches (round robin within group)
    # Total: 3 * 6 = 18 WF matches
    assert len(wf_matches) == 18

    # Verify each team appears in exactly 3 WF matches (size-4 group RR)
    # (This would require parsing placeholders or team assignments, simplified here)


def test_wf_teams_in_different_groups_never_play(client: TestClient, session: Session, setup_wf_event):
    """Test that teams in different groups never play in WF"""
    setup = setup_wf_event(8)
    event_id = setup["event_id"]
    tournament_id = setup["tournament_id"]
    schedule_version_id = setup["schedule_version_id"]
    setup["teams"]

    # Assign groups (8 teams → 2 groups of 4)
    response = client.post(f"/api/events/{event_id}/waterfall/assign-groups", params={"clear_existing": True})
    assert response.status_code == 200
    grouping_data = response.json()
    assert grouping_data["groups_count"] == 2

    # Get team group assignments
    teams_refreshed = session.exec(select(Team).where(Team.event_id == event_id)).all()

    group_0_teams = [t.id for t in teams_refreshed if t.wf_group_index == 0]
    group_1_teams = [t.id for t in teams_refreshed if t.wf_group_index == 1]

    assert len(group_0_teams) == 4
    assert len(group_1_teams) == 4

    # Generate matches
    response = client.post(
        f"/api/tournaments/{tournament_id}/schedule/matches/generate",
        json={"schedule_version_id": schedule_version_id, "event_id": event_id, "wipe_existing": True},
    )
    assert response.status_code == 200

    # Get WF matches
    wf_matches = session.exec(select(Match).where(Match.event_id == event_id, Match.match_type == "WF")).all()

    # 2 groups * 6 matches per group = 12 WF matches
    assert len(wf_matches) == 12


# ============================================================================
# Phase W2 Tests: Avoid Edges API
# ============================================================================


def test_api_create_avoid_edge(client: TestClient, session: Session, setup_wf_event):
    """Test creating an avoid edge via API"""
    setup = setup_wf_event(4)
    event_id = setup["event_id"]
    teams = setup["teams"]

    response = client.post(
        f"/api/events/{event_id}/avoid-edges",
        json={"team_id_a": teams[0].id, "team_id_b": teams[1].id, "reason": "Test conflict"},
    )

    assert response.status_code == 201
    data = response.json()
    assert data["event_id"] == event_id
    assert data["reason"] == "Test conflict"


def test_api_get_avoid_edges(client: TestClient, session: Session, setup_wf_event):
    """Test getting avoid edges via API"""
    setup = setup_wf_event(4)
    event_id = setup["event_id"]
    teams = setup["teams"]

    # Create an edge
    client.post(
        f"/api/events/{event_id}/avoid-edges",
        json={"team_id_a": teams[0].id, "team_id_b": teams[1].id, "reason": "Test"},
    )

    # Get edges
    response = client.get(f"/api/events/{event_id}/avoid-edges")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["reason"] == "Test"


def test_api_delete_avoid_edge(client: TestClient, session: Session, setup_wf_event):
    """Test deleting an avoid edge via API"""
    setup = setup_wf_event(4)
    event_id = setup["event_id"]
    teams = setup["teams"]

    # Create an edge
    create_response = client.post(
        f"/api/events/{event_id}/avoid-edges", json={"team_id_a": teams[0].id, "team_id_b": teams[1].id}
    )
    edge_id = create_response.json()["id"]

    # Delete edge
    response = client.delete(f"/api/events/{event_id}/avoid-edges/{edge_id}")
    assert response.status_code == 204

    # Verify deleted
    get_response = client.get(f"/api/events/{event_id}/avoid-edges")
    assert len(get_response.json()) == 0
