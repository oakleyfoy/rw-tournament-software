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
    import app.models  # noqa: F401

    # Create all tables on test engine (explicit, don't rely on app startup)
    SQLModel.metadata.create_all(test_engine)

    with Session(test_engine) as session:
        yield session

    # Shared in-memory DB: wipe rows so tests do not leak data (TeamPlayer, auth, etc.).
    from sqlalchemy import text

    with Session(test_engine) as cleanup:
        conn = cleanup.connection()
        conn.execute(text("PRAGMA foreign_keys=OFF"))
        for table in reversed(SQLModel.metadata.sorted_tables):
            conn.execute(table.delete())
        conn.execute(text("PRAGMA foreign_keys=ON"))
        cleanup.commit()

    # Note: With StaticPool + :memory:, schema persists across tests in same run
    # but row data is cleared after each test function.


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
