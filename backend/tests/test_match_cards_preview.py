"""
Smoke tests for Match Cards preview endpoint.

- Preview returns 200 with matches: [] when no matches
- Preview returns matches when present
- Never 404 for "no matches" case
"""

from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.database import get_session
from app.main import app
from app.models import Event, Match, ScheduleVersion, Tournament


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


@pytest.fixture(name="tournament_version_no_matches")
def tournament_version_no_matches_fixture(session: Session):
    """Tournament + schedule version with zero matches."""
    t = Tournament(
        name="Preview Test",
        location="Test",
        timezone="America/New_York",
        start_date=date(2026, 3, 1),
        end_date=date(2026, 3, 3),
        court_names=["Court 1"],
    )
    session.add(t)
    session.commit()
    session.refresh(t)

    v = ScheduleVersion(tournament_id=t.id, version_number=1, status="draft")
    session.add(v)
    session.commit()
    session.refresh(v)

    return {"tournament_id": t.id, "version_id": v.id}


def test_preview_returns_200_empty_when_no_matches(client: TestClient, tournament_version_no_matches):
    """Preview returns 200 with matches: [] when version has no matches."""
    tid = tournament_version_no_matches["tournament_id"]
    vid = tournament_version_no_matches["version_id"]

    r = client.get(f"/api/tournaments/{tid}/schedule/versions/{vid}/matches/preview")
    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
    d = r.json()
    assert "matches" in d
    assert d["matches"] == []
    assert "diagnostics" in d
    assert d["diagnostics"]["matches_found"] == 0
    assert d["diagnostics"]["requested_version_id"] == vid


@pytest.fixture(name="tournament_version_with_matches")
def tournament_version_with_matches_fixture(session: Session):
    """Tournament + schedule version + event + 2 matches."""
    t = Tournament(
        name="Preview With Matches",
        location="Test",
        timezone="America/New_York",
        start_date=date(2026, 3, 1),
        end_date=date(2026, 3, 3),
        court_names=["Court 1"],
    )
    session.add(t)
    session.commit()
    session.refresh(t)

    e = Event(
        tournament_id=t.id,
        name="Mens Doubles",
        category="mixed",
        team_count=4,
        draw_status="final",
    )
    session.add(e)
    session.commit()
    session.refresh(e)

    v = ScheduleVersion(tournament_id=t.id, version_number=1, status="draft")
    session.add(v)
    session.commit()
    session.refresh(v)

    m1 = Match(
        tournament_id=t.id,
        event_id=e.id,
        schedule_version_id=v.id,
        match_code="MD_MENS_E1_RR_01",
        match_type="RR",
        round_number=1,
        round_index=1,
        sequence_in_round=1,
        duration_minutes=60,
        placeholder_side_a="A1",
        placeholder_side_b="B1",
    )
    m2 = Match(
        tournament_id=t.id,
        event_id=e.id,
        schedule_version_id=v.id,
        match_code="MD_MENS_E1_RR_02",
        match_type="RR",
        round_number=1,
        round_index=1,
        sequence_in_round=2,
        duration_minutes=60,
        placeholder_side_a="A2",
        placeholder_side_b="B2",
    )
    session.add(m1)
    session.add(m2)
    session.commit()

    return {"tournament_id": t.id, "version_id": v.id, "event_id": e.id}


def test_preview_returns_matches_when_present(client: TestClient, tournament_version_with_matches):
    """Preview returns 200 with 2 matches when they exist."""
    tid = tournament_version_with_matches["tournament_id"]
    vid = tournament_version_with_matches["version_id"]
    eid = tournament_version_with_matches["event_id"]

    r = client.get(f"/api/tournaments/{tid}/schedule/versions/{vid}/matches/preview")
    assert r.status_code == 200
    d = r.json()
    assert "matches" in d
    assert len(d["matches"]) == 2
    assert d["diagnostics"]["matches_found"] == 2
    codes = [m["match_code"] for m in d["matches"]]
    assert "MD_MENS_E1_RR_01" in codes
    assert "MD_MENS_E1_RR_02" in codes
    assert "event_ids_present" in d["diagnostics"]
    assert d["diagnostics"]["event_ids_present"] == [eid]
    assert "event_counts_by_id" in d["diagnostics"]
    assert d["diagnostics"]["event_counts_by_id"][str(eid)] == 2


def test_preview_diagnostics_multiple_events(client: TestClient, session: Session):
    """Preview diagnostics include all event IDs when matches span multiple events."""
    from app.models.event import Event
    from app.models.match import Match
    from app.models.schedule_version import ScheduleVersion
    from app.models.tournament import Tournament

    t = Tournament(
        name="Multi Event",
        location="Test",
        timezone="America/New_York",
        start_date=date(2026, 3, 1),
        end_date=date(2026, 3, 3),
        court_names=["Court 1"],
    )
    session.add(t)
    session.commit()
    session.refresh(t)

    e1 = Event(tournament_id=t.id, name="Mixed", category="mixed", team_count=4, draw_status="final")
    e2 = Event(tournament_id=t.id, name="Women's A", category="women", team_count=4, draw_status="final")
    e3 = Event(tournament_id=t.id, name="Women's B", category="women", team_count=4, draw_status="final")
    session.add_all([e1, e2, e3])
    session.commit()
    for ev in [e1, e2, e3]:
        session.refresh(ev)

    v = ScheduleVersion(tournament_id=t.id, version_number=1, status="draft")
    session.add(v)
    session.commit()
    session.refresh(v)

    for i, ev in enumerate([e1, e2, e3]):
        session.add(
            Match(
                tournament_id=t.id,
                event_id=ev.id,
                schedule_version_id=v.id,
                match_code=f"EV{ev.id}_RR_{i+1:02d}",
                match_type="RR",
                round_number=1,
                round_index=1,
                sequence_in_round=1,
                duration_minutes=60,
                placeholder_side_a="A",
                placeholder_side_b="B",
            )
        )
    session.commit()

    r = client.get(f"/api/tournaments/{t.id}/schedule/versions/{v.id}/matches/preview")
    assert r.status_code == 200
    d = r.json()
    assert d["diagnostics"]["event_ids_present"] == sorted([e1.id, e2.id, e3.id])
    ec = d["diagnostics"]["event_counts_by_id"]
    assert ec[str(e1.id)] == 1
    assert ec[str(e2.id)] == 1
    assert ec[str(e3.id)] == 1
