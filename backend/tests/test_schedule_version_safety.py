"""
Test schedule version safety features (finalize, clone)
"""

from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine

from app.database import get_session
from app.main import app

# Import all models to ensure tables are registered
from app.models.event import Event  # noqa: F401
from app.models.match import Match  # noqa: F401
from app.models.match_assignment import MatchAssignment  # noqa: F401
from app.models.schedule_slot import ScheduleSlot  # noqa: F401
from app.models.schedule_version import ScheduleVersion  # noqa: F401
from app.models.team import Team  # noqa: F401
from app.models.team_avoid_edge import TeamAvoidEdge  # noqa: F401
from app.models.tournament import Tournament
from app.models.tournament_day import TournamentDay  # noqa: F401
from app.models.tournament_time_window import TournamentTimeWindow  # noqa: F401

# Use test database
TEST_DATABASE_URL = "sqlite:///./test_version_safety.db"
engine = create_engine(TEST_DATABASE_URL, echo=False)

# Debug: Print registered tables (CI diagnostic)
table_names = [t.name for t in SQLModel.metadata.sorted_tables]
print(f"[test_schedule_version_safety DEBUG] Registered tables: {table_names}")


def get_test_session():
    with Session(engine) as session:
        yield session


app.dependency_overrides[get_session] = get_test_session
client = TestClient(app)


@pytest.fixture(scope="function", autouse=True)
def setup_database():
    """Create tables before each test and drop after"""
    # Ensure all tables are created for each test
    SQLModel.metadata.create_all(engine)
    yield
    SQLModel.metadata.drop_all(engine)


def create_tournament():
    """Helper to create a test tournament"""
    with Session(engine) as session:
        tournament = Tournament(
            name="Test Tournament",
            location="Test Location",
            timezone="UTC",
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 3),
        )
        session.add(tournament)
        session.commit()
        session.refresh(tournament)
        return tournament.id


def test_finalize_draft_version():
    """Test that finalize sets checksum and locks version"""
    tid = create_tournament()

    # Create a draft version
    resp = client.post(f"/api/tournaments/{tid}/schedule/versions", json={"notes": "Test"})
    assert resp.status_code == 201
    version_id = resp.json()["id"]

    # Finalize it
    resp = client.post(f"/api/tournaments/{tid}/schedule/versions/{version_id}/finalize")
    assert resp.status_code == 200
    data = resp.json()

    assert data["status"] == "final"
    assert data["finalized_at"] is not None
    assert data["finalized_checksum"] is not None
    assert len(data["finalized_checksum"]) == 64  # SHA-256 hex is 64 chars


def test_mutation_rejected_on_final_version():
    """Test that write operations reject final versions"""
    tid = create_tournament()

    # Create and finalize a version
    resp = client.post(f"/api/tournaments/{tid}/schedule/versions", json={"notes": "Test"})
    version_id = resp.json()["id"]
    client.post(f"/api/tournaments/{tid}/schedule/versions/{version_id}/finalize")

    # Try to build on finalized version
    resp = client.post(f"/api/tournaments/{tid}/schedule/versions/{version_id}/build")
    assert resp.status_code == 400
    assert "SCHEDULE_VERSION_NOT_DRAFT" in resp.json()["detail"]


def test_clone_final_to_draft():
    """Test that clone creates a new draft from final"""
    tid = create_tournament()

    # Create and finalize a version
    resp = client.post(f"/api/tournaments/{tid}/schedule/versions", json={"notes": "Test"})
    final_id = resp.json()["id"]
    client.post(f"/api/tournaments/{tid}/schedule/versions/{final_id}/finalize")

    # Clone it
    resp = client.post(f"/api/tournaments/{tid}/schedule/versions/{final_id}/clone")
    assert resp.status_code == 201
    data = resp.json()

    assert data["status"] == "draft"
    assert data["finalized_at"] is None
    assert data["finalized_checksum"] is None
    assert data["id"] != final_id
    assert data["version_number"] > 1


def test_checksum_determinism():
    """Test that identical schedules produce identical checksums"""
    # Create two tournaments via API to ensure proper visibility
    t1_resp = client.post(
        "/api/tournaments",
        json={
            "name": "Test Tournament 1",
            "location": "Test Location",
            "timezone": "UTC",
            "start_date": "2026-01-01",
            "end_date": "2026-01-03",
        },
    )
    assert t1_resp.status_code == 201, f"Failed to create tournament 1: {t1_resp.status_code} {t1_resp.text}"
    tid1 = t1_resp.json()["id"]

    t2_resp = client.post(
        "/api/tournaments",
        json={
            "name": "Test Tournament 2",
            "location": "Test Location",
            "timezone": "UTC",
            "start_date": "2026-01-01",
            "end_date": "2026-01-03",
        },
    )
    assert t2_resp.status_code == 201, f"Failed to create tournament 2: {t2_resp.status_code} {t2_resp.text}"
    tid2 = t2_resp.json()["id"]

    # Create two versions in different tournaments with identical (empty) data
    resp1 = client.post(f"/api/tournaments/{tid1}/schedule/versions", json={"notes": "V1"})
    assert resp1.status_code == 201, f"Failed to create version 1: {resp1.status_code} {resp1.text}"
    v1_id = resp1.json()["id"]

    resp2 = client.post(f"/api/tournaments/{tid2}/schedule/versions", json={"notes": "V2"})
    assert resp2.status_code == 201, f"Failed to create version 2: {resp2.status_code} {resp2.text}"
    v2_id = resp2.json()["id"]

    # Finalize both (they're both empty, so checksums should match)
    resp1_final = client.post(f"/api/tournaments/{tid1}/schedule/versions/{v1_id}/finalize")
    assert resp1_final.status_code == 200
    checksum1 = resp1_final.json()["finalized_checksum"]

    resp2_final = client.post(f"/api/tournaments/{tid2}/schedule/versions/{v2_id}/finalize")
    assert resp2_final.status_code == 200
    checksum2 = resp2_final.json()["finalized_checksum"]

    assert checksum1 == checksum2, "Identical schedules should have identical checksums"


def test_clone_only_works_on_final():
    """Test that clone rejects draft versions"""
    tid = create_tournament()

    # Create a draft version
    resp = client.post(f"/api/tournaments/{tid}/schedule/versions", json={"notes": "Test"})
    draft_id = resp.json()["id"]

    # Try to clone it (should fail)
    resp = client.post(f"/api/tournaments/{tid}/schedule/versions/{draft_id}/clone")
    assert resp.status_code == 400
    assert "SOURCE_VERSION_NOT_FINAL" in resp.json()["detail"]


def test_clone_to_draft_alias_route():
    """Test that /clone-to-draft alias works identically to /clone"""
    tid = create_tournament()

    # Create and finalize a version
    resp = client.post(f"/api/tournaments/{tid}/schedule/versions", json={"notes": "Test"})
    final_id = resp.json()["id"]
    client.post(f"/api/tournaments/{tid}/schedule/versions/{final_id}/finalize")

    # Clone using the alias route
    resp = client.post(f"/api/tournaments/{tid}/schedule/versions/{final_id}/clone-to-draft")
    assert resp.status_code == 201
    data = resp.json()

    assert data["status"] == "draft"
    assert data["finalized_at"] is None
    assert data["finalized_checksum"] is None
    assert data["id"] != final_id
    assert data["version_number"] > 1


def test_reset_draft_version():
    """Test that reset clears all artifacts from a draft version"""
    tid = create_tournament()

    # Create a draft version
    resp = client.post(f"/api/tournaments/{tid}/schedule/versions", json={"notes": "Test"})
    draft_id = resp.json()["id"]

    # Note: In a real scenario, we'd add slots/matches/assignments here
    # For now, we test with empty version

    # Reset the draft
    resp = client.post(f"/api/tournaments/{tid}/schedule/versions/{draft_id}/reset")
    assert resp.status_code == 200
    data = resp.json()

    assert data["schedule_version_id"] == draft_id
    assert "cleared_assignments_count" in data
    assert "cleared_matches_count" in data
    assert "cleared_slots_count" in data
    # All should be 0 since we didn't add any data
    assert data["cleared_assignments_count"] == 0
    assert data["cleared_matches_count"] == 0
    assert data["cleared_slots_count"] == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
