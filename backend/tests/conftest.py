import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.database import get_session
from app.main import app

TEST_DATABASE_URL = "sqlite:///:memory:"

# Create test engine with StaticPool - CRITICAL for :memory: across connections/threads
test_engine = create_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)


def override_get_session():
    """Override session to use test engine"""
    with Session(test_engine) as session:
        yield session


@pytest.fixture(name="session")
def session_fixture():
    """Provide a test database session"""
    # Import all models to ensure they're registered
    from app.models.event import Event  # noqa: F401
    from app.models.match import Match  # noqa: F401
    from app.models.match_assignment import MatchAssignment  # noqa: F401
    from app.models.schedule_slot import ScheduleSlot  # noqa: F401
    from app.models.schedule_version import ScheduleVersion  # noqa: F401
    from app.models.team import Team  # noqa: F401
    from app.models.team_avoid_edge import TeamAvoidEdge  # noqa: F401
    from app.models.tournament import Tournament  # noqa: F401
    from app.models.tournament_day import TournamentDay  # noqa: F401
    from app.models.tournament_time_window import TournamentTimeWindow  # noqa: F401

    # Create all tables on test engine
    SQLModel.metadata.create_all(test_engine)

    with Session(test_engine) as session:
        yield session


@pytest.fixture(name="client")
def client_fixture(session: Session):
    """Provide a test client with overridden database session"""
    # Override dependency to use test session
    app.dependency_overrides[get_session] = override_get_session

    # Use context manager to ensure lifespan/startup executes reliably
    with TestClient(app) as client:
        yield client

    # Clear overrides after test
    app.dependency_overrides.clear()
