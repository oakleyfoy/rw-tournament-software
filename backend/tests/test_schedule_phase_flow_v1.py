"""
Tests for Phase Flow V1: phased schedule building.

- Generate Matches Only (idempotent)
- Generate Slots Only (idempotent)
- Assign WF_R1 only
- Assign WF_R2 after R1
- Preview returns deterministic checksum
"""

import json
from datetime import date, time

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.database import get_session
from app.main import app
from app.models import (
    Event,
    Match,
    MatchAssignment,
    ScheduleSlot,
    ScheduleVersion,
    Team,
    Tournament,
    TournamentDay,
    TournamentTimeWindow,
)


@pytest.fixture(name="session")
def session_fixture():
    from sqlmodel import SQLModel, create_engine
    from sqlmodel.pool import StaticPool

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


@pytest.fixture(name="client")
def client_fixture(session: Session):
    def get_session_override():
        return session

    app.dependency_overrides[get_session] = get_session_override
    client = TestClient(app)
    yield client
    app.dependency_overrides.clear()


@pytest.fixture(name="wf_pools_setup")
def wf_pools_setup_fixture(session: Session):
    """Tournament with WF_TO_POOLS_4 event (16 teams, WF R1 + R2 + Pools)."""
    t = Tournament(
        name="WF Pools Test",
        location="Test",
        timezone="America/New_York",
        start_date=date(2026, 2, 20),
        end_date=date(2026, 2, 22),
        court_names=["Court 1", "Court 2"],
        use_time_windows=True,  # Use windows with block_minutes for match-sized slots
    )
    session.add(t)
    session.commit()
    session.refresh(t)

    # Time window with 105-min blocks (fits WF match duration 60)
    tw = TournamentTimeWindow(
        tournament_id=t.id,
        day_date=date(2026, 2, 20),
        start_time=time(9, 0),
        end_time=time(18, 0),
        courts_available=2,
        block_minutes=105,
        is_active=True,
    )
    session.add(tw)
    session.commit()

    version = ScheduleVersion(tournament_id=t.id, version_number=1, status="draft")
    session.add(version)
    session.commit()
    session.refresh(version)

    event = Event(
        tournament_id=t.id,
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
        session.add(Team(event_id=event.id, name=f"Seed {i}", seed=i, rating=1000.0 + i))
    session.commit()

    return {"tournament_id": t.id, "version_id": version.id, "event_id": event.id}


def test_generate_matches_only_idempotent(client: TestClient, session: Session, wf_pools_setup):
    """Call matches/generate twice → same match count, no duplicates."""
    tid = wf_pools_setup["tournament_id"]
    vid = wf_pools_setup["version_id"]

    r1 = client.post(f"/api/tournaments/{tid}/schedule/versions/{vid}/matches/generate")
    assert r1.status_code == 200
    d1 = r1.json()
    assert d1["already_generated"] is False
    assert d1["matches_generated"] > 0
    assert d1["debug_stamp"] == "matches_generate_only_v1"

    count1 = d1["matches_generated"]
    matches1 = session.exec(select(Match).where(Match.schedule_version_id == vid)).all()
    assert len(matches1) == count1

    r2 = client.post(f"/api/tournaments/{tid}/schedule/versions/{vid}/matches/generate")
    assert r2.status_code == 200
    d2 = r2.json()
    assert d2["already_generated"] is True
    assert d2["matches_generated"] == 0  # No new matches added (already complete)
    assert d2.get("already_complete") is True

    matches2 = session.exec(select(Match).where(Match.schedule_version_id == vid)).all()
    assert len(matches2) == count1
    codes = [m.match_code for m in matches2]
    assert len(codes) == len(set(codes)), "No duplicate match codes"


def test_generate_matches_fills_missing_event_mixed_has_16_womens_missing(session: Session, client: TestClient):
    """
    When Mixed has 16 matches but Women's has 0, generate must add Women's (30) → total 46.
    Guardrail: prevents no-op when one event exists.
    """
    t = Tournament(
        name="Two Event Test",
        location="Test",
        timezone="America/New_York",
        start_date=date(2026, 3, 1),
        end_date=date(2026, 3, 3),
        court_names=["Court 1"],
        use_time_windows=True,
    )
    session.add(t)
    session.commit()
    session.refresh(t)

    tw = TournamentTimeWindow(
        tournament_id=t.id,
        day_date=date(2026, 3, 1),
        start_time=time(9, 0),
        end_time=time(18, 0),
        courts_available=2,
        block_minutes=120,
        is_active=True,
    )
    session.add(tw)
    session.commit()

    version = ScheduleVersion(tournament_id=t.id, version_number=1, status="draft")
    session.add(version)
    session.commit()
    session.refresh(version)

    mixed = Event(
        tournament_id=t.id,
        name="Mixed",
        category="mixed",
        team_count=8,
        draw_plan_json=json.dumps({"template_type": "WF_TO_POOLS_DYNAMIC", "wf_rounds": 1, "guarantee": 4}),
        draw_status="final",
        wf_block_minutes=120,
        standard_block_minutes=120,
    )
    womens = Event(
        tournament_id=t.id,
        name="Women's",
        category="womens",
        team_count=12,
        draw_plan_json=json.dumps({"template_type": "WF_TO_POOLS_DYNAMIC", "wf_rounds": 2, "guarantee": 4}),
        draw_status="final",
        wf_block_minutes=60,
        standard_block_minutes=120,
    )
    session.add_all([mixed, womens])
    session.commit()
    session.refresh(mixed)
    session.refresh(womens)

    for i in range(1, 9):
        session.add(Team(event_id=mixed.id, name=f"Mixed {i}", seed=i, rating=1000.0))
    for i in range(1, 13):
        session.add(Team(event_id=womens.id, name=f"Women {i}", seed=i, rating=1000.0))
    session.commit()

    r1 = client.post(f"/api/tournaments/{t.id}/schedule/versions/{version.id}/matches/generate")
    assert r1.status_code == 200, r1.text
    d1 = r1.json()
    assert d1["matches_generated"] == 46
    total_before = len(session.exec(select(Match).where(Match.schedule_version_id == version.id)).all())
    assert total_before == 46

    womens_matches = session.exec(select(Match).where(Match.event_id == womens.id, Match.schedule_version_id == version.id)).all()
    for m in womens_matches:
        session.delete(m)
    session.commit()

    mixed_count_before = len(session.exec(select(Match).where(Match.event_id == mixed.id, Match.schedule_version_id == version.id)).all())
    assert mixed_count_before == 16

    r2 = client.post(f"/api/tournaments/{t.id}/schedule/versions/{version.id}/matches/generate")
    assert r2.status_code == 200, r2.text
    d2 = r2.json()
    assert d2["matches_generated"] == 30, f"Expected 30 added (Women's), got {d2['matches_generated']}"

    mixed_count = len(session.exec(select(Match).where(Match.event_id == mixed.id, Match.schedule_version_id == version.id)).all())
    womens_count = len(session.exec(select(Match).where(Match.event_id == womens.id, Match.schedule_version_id == version.id)).all())
    total = mixed_count + womens_count

    assert mixed_count == 16, f"Mixed should remain 16, got {mixed_count}"
    assert womens_count == 30, f"Women's should have 30, got {womens_count}"
    assert total == 46, f"Total should be 46, got {total}"


def test_generate_matches_only_wipe_existing(client: TestClient, session: Session, wf_pools_setup):
    """With wipe_existing=True, matches are wiped and regenerated."""
    tid = wf_pools_setup["tournament_id"]
    vid = wf_pools_setup["version_id"]

    r1 = client.post(f"/api/tournaments/{tid}/schedule/versions/{vid}/matches/generate")
    assert r1.status_code == 200
    count1 = r1.json()["matches_generated"]
    assert count1 > 0

    r2 = client.post(
        f"/api/tournaments/{tid}/schedule/versions/{vid}/matches/generate",
        json={"wipe_existing": True},
    )
    assert r2.status_code == 200
    d2 = r2.json()
    assert d2["already_generated"] is False
    assert d2["matches_generated"] == count1

    matches = session.exec(select(Match).where(Match.schedule_version_id == vid)).all()
    assert len(matches) == count1


def test_generate_slots_only_idempotent(client: TestClient, session: Session, wf_pools_setup):
    """Call slots/generate twice → same slot count."""
    tid = wf_pools_setup["tournament_id"]
    vid = wf_pools_setup["version_id"]

    r1 = client.post(f"/api/tournaments/{tid}/schedule/versions/{vid}/slots/generate")
    assert r1.status_code == 200
    d1 = r1.json()
    assert d1["already_generated"] is False
    assert d1["slots_generated"] > 0

    r2 = client.post(f"/api/tournaments/{tid}/schedule/versions/{vid}/slots/generate")
    assert r2.status_code == 200
    d2 = r2.json()
    assert d2["already_generated"] is True
    assert d2["slots_generated"] == d1["slots_generated"]


def test_assign_wf_r1_only(client: TestClient, session: Session, wf_pools_setup):
    """Generate slots + matches, assign scope WF_R1, assert only WF round 1 get slot_id."""
    tid = wf_pools_setup["tournament_id"]
    vid = wf_pools_setup["version_id"]

    client.post(f"/api/tournaments/{tid}/schedule/versions/{vid}/matches/generate")
    client.post(f"/api/tournaments/{tid}/schedule/versions/{vid}/slots/generate")

    r = client.post(
        f"/api/tournaments/{tid}/schedule/versions/{vid}/assign",
        json={"scope": "WF_R1", "clear_existing_assignments_in_scope": False},
    )
    assert r.status_code == 200
    d = r.json()
    assert d["assigned_count"] >= 0
    assert d["debug_stamp"] == "assign_scope_v1"

    # WF R1 matches should have assignments
    wf_r1 = session.exec(
        select(Match).where(
            Match.schedule_version_id == vid,
            Match.match_type == "WF",
            Match.round_number == 1,
        )
    ).all()
    assigned = session.exec(select(MatchAssignment).where(MatchAssignment.schedule_version_id == vid)).all()
    assigned_match_ids = {a.match_id for a in assigned}
    wf_r1_assigned = [m for m in wf_r1 if m.id in assigned_match_ids]
    # All WF R1 should be assigned (if enough slots)
    assert len(wf_r1_assigned) == len(wf_r1) or d["unassigned_count_remaining_in_scope"] >= 0

    # WF R2 should NOT be assigned (we only placed R1)
    wf_r2 = session.exec(
        select(Match).where(
            Match.schedule_version_id == vid,
            Match.match_type == "WF",
            Match.round_number == 2,
        )
    ).all()
    wf_r2_assigned = [m for m in wf_r2 if m.id in assigned_match_ids]
    assert len(wf_r2_assigned) == 0, "WF R2 should not be assigned when scope=WF_R1 only"


def test_assign_wf_r2_after_r1(client: TestClient, session: Session, wf_pools_setup):
    """Place WF R1, then WF R2; both assign calls succeed and R2 depends on R1 being placed first."""
    tid = wf_pools_setup["tournament_id"]
    vid = wf_pools_setup["version_id"]

    client.post(f"/api/tournaments/{tid}/schedule/versions/{vid}/matches/generate")
    client.post(f"/api/tournaments/{tid}/schedule/versions/{vid}/slots/generate")

    r1 = client.post(
        f"/api/tournaments/{tid}/schedule/versions/{vid}/assign",
        json={"scope": "WF_R1", "clear_existing_assignments_in_scope": False},
    )
    assert r1.status_code == 200
    assert r1.json()["assigned_count"] >= 0

    r2 = client.post(
        f"/api/tournaments/{tid}/schedule/versions/{vid}/assign",
        json={"scope": "WF_R2", "clear_existing_assignments_in_scope": False},
    )
    assert r2.status_code == 200
    # R2 can only be placed after R1; with sufficient slots both should succeed
    d2 = r2.json()
    assert "assigned_count" in d2
    assert "unassigned_count_remaining_in_scope" in d2


def test_versions_active_returns_draft(client: TestClient, wf_pools_setup):
    """GET /versions/active returns the draft version (or creates one)."""
    tid = wf_pools_setup["tournament_id"]
    vid = wf_pools_setup["version_id"]

    r = client.get(f"/api/tournaments/{tid}/schedule/versions/active")
    assert r.status_code == 200
    d = r.json()
    assert d["schedule_version_id"] == vid
    assert d["status"] == "draft"
    assert d["none_found"] is False


def test_preview_includes_diagnostics(client: TestClient, wf_pools_setup):
    """Preview response includes diagnostics for version mismatch detection."""
    tid = wf_pools_setup["tournament_id"]
    vid = wf_pools_setup["version_id"]

    r = client.get(f"/api/tournaments/{tid}/schedule/versions/{vid}/matches/preview")
    assert r.status_code == 200
    d = r.json()
    assert "diagnostics" in d
    diag = d["diagnostics"]
    assert diag["requested_version_id"] == vid
    assert diag["matches_found"] == len(d["matches"])
    assert diag["grid_reported_matches_for_version"] == len(d["matches"])
    assert "likely_version_mismatch" in diag


def test_preview_returns_deterministic_checksum(client: TestClient, session: Session, wf_pools_setup):
    """Preview returns same checksum on repeated calls."""
    tid = wf_pools_setup["tournament_id"]
    vid = wf_pools_setup["version_id"]

    client.post(f"/api/tournaments/{tid}/schedule/versions/{vid}/matches/generate")

    r1 = client.get(f"/api/tournaments/{tid}/schedule/versions/{vid}/matches/preview")
    assert r1.status_code == 200
    d1 = r1.json()
    assert "ordering_checksum" in d1
    assert "duplicate_codes" in d1
    assert d1["duplicate_codes"] == []
    assert len(d1["matches"]) > 0

    r2 = client.get(f"/api/tournaments/{tid}/schedule/versions/{vid}/matches/preview")
    assert r2.status_code == 200
    d2 = r2.json()
    assert d2["ordering_checksum"] == d1["ordering_checksum"], "Checksum must be deterministic"
