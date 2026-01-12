import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.database import get_session
from app.main import app

TEST_DATABASE_URL = "sqlite:///:memory:"

# ============================================================================
# CRITICAL: Test Database Setup with StaticPool
# ============================================================================
# 1. Use sqlite:///:memory: with StaticPool so ALL sessions share same DB
# 2. check_same_thread=False required for TestClient/threaded access
# 3. All models MUST be imported before create_all() (see session_fixture)
# 4. App dependency overridden to use test_engine (see client_fixture)
# 5. Tables created explicitly, not relying on app startup
test_engine = create_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)


def override_get_session():
    """Override session to use test engine"""
    with Session(test_engine) as session:
        yield session


@pytest.fixture(name="session", scope="function")
def session_fixture():
    """Provide a test database session

    With StaticPool + :memory:, all sessions share the same database.
    Tables persist across tests within a session but are isolated per test run.
    """
    # Import all models to ensure they're registered BEFORE create_all
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

    # Create all tables on test engine (explicit, don't rely on app startup)
    SQLModel.metadata.create_all(test_engine)

    with Session(test_engine) as session:
        yield session

    # Note: With StaticPool + :memory:, data persists across tests in same run
    # but is isolated per pytest invocation. This matches previous behavior.


@pytest.fixture(name="client")
def client_fixture(session: Session):
    """Provide a test client with overridden database session

    CRITICAL: Override MUST be set BEFORE TestClient() and stay in place
    for the entire duration. This ensures the app never uses its own engine.
    """
    # Override dependency BEFORE creating TestClient (prevents production engine use)
    app.dependency_overrides[get_session] = override_get_session

    # Create TestClient with context manager (keeps override active throughout)
    with TestClient(app) as client:
        yield client

    # Clear overrides only AFTER TestClient context exits
    app.dependency_overrides.clear()
