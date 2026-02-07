"""
Court label must be a scalar string per slot, never a list.
Regression: time_windows path was not unpacking get_court_labels() tuple, so court_label could be the warnings list.
"""
from datetime import date, time

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine, select
from sqlmodel.pool import StaticPool

from app.database import get_session
from app.main import app
from app.models import ScheduleSlot, ScheduleVersion, Tournament, TournamentTimeWindow


@pytest.fixture(name="session")
def session_fixture():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


@pytest.fixture(name="client")
def client_fixture(session: Session):
    def get_session_override():
        return session

    app.dependency_overrides[get_session] = get_session_override
    client = TestClient(app)
    yield client
    app.dependency_overrides.clear()


def test_slot_generation_court_label_is_string_not_list(client: TestClient, session: Session):
    """
    Slot generation with tournament.court_names (e.g. non-contiguous "1,5,6,...,18").
    Each inserted ScheduleSlot.court_label must be a scalar string, never a list.
    """
    # Create tournament with custom court names (non-contiguous like Kiawah)
    court_names = ["1", "5", "6", "7", "8", "9", "10", "11", "12", "13", "14", "15", "16", "17", "18"]
    tournament = Tournament(
        name="Court Label Test",
        location="Test",
        timezone="America/New_York",
        start_date=date(2026, 2, 20),
        end_date=date(2026, 2, 22),
        use_time_windows=True,
        court_names=court_names,
    )
    session.add(tournament)
    session.commit()
    session.refresh(tournament)
    tid = tournament.id

    # One active time window, 3 courts (use first 3 labels: "1", "5", "6")
    window = TournamentTimeWindow(
        tournament_id=tid,
        day_date=date(2026, 2, 20),
        start_time=time(9, 0),
        end_time=time(12, 0),
        courts_available=3,
        block_minutes=60,
        is_active=True,
    )
    session.add(window)
    session.commit()

    # Draft version
    version = ScheduleVersion(tournament_id=tid, version_number=1, status="draft")
    session.add(version)
    session.commit()
    session.refresh(version)
    version_id = version.id

    # Generate slots (time_windows path)
    resp = client.post(
        f"/api/tournaments/{tid}/schedule/slots/generate",
        json={"source": "time_windows", "schedule_version_id": version_id, "wipe_existing": True},
    )
    assert resp.status_code in (200, 201), resp.text

    slots = session.exec(select(ScheduleSlot).where(ScheduleSlot.schedule_version_id == version_id)).all()
    assert len(slots) > 0

    allowed_labels = {"1", "5", "6"}  # First 3 from court_names
    for slot in slots:
        assert isinstance(slot.court_label, str), f"court_label must be str, got {type(slot.court_label)}"
        assert slot.court_label in allowed_labels, f"court_label must be in {allowed_labels}, got {slot.court_label!r}"


def test_generate_slots_respects_window_block_minutes(client: TestClient, session: Session):
    """
    Slots generated from time windows must respect window.block_minutes.
    - 60-minute window → 60-minute slots
    - 105-minute window → 105-minute slots
    - No 15-minute micro-slots
    """
    # Create tournament
    tournament = Tournament(
        name="Block Minutes Test",
        location="Test",
        timezone="America/New_York",
        start_date=date(2026, 2, 20),
        end_date=date(2026, 2, 22),
        use_time_windows=True,
    )
    session.add(tournament)
    session.commit()
    session.refresh(tournament)
    tid = tournament.id

    # Window 1: 9:00-12:00 (3 hours), 2 courts, 60-minute blocks
    # Expected: 3 slots per court (9:00-10:00, 10:00-11:00, 11:00-12:00)
    window1 = TournamentTimeWindow(
        tournament_id=tid,
        day_date=date(2026, 2, 20),
        start_time=time(9, 0),
        end_time=time(12, 0),
        courts_available=2,
        block_minutes=60,
        is_active=True,
    )
    session.add(window1)

    # Window 2: 8:00-11:30 (210 minutes), 1 court, 105-minute blocks
    # Expected: 2 slots (8:00-9:45, 9:45-11:30)
    window2 = TournamentTimeWindow(
        tournament_id=tid,
        day_date=date(2026, 2, 21),
        start_time=time(8, 0),
        end_time=time(11, 30),
        courts_available=1,
        block_minutes=105,
        is_active=True,
    )
    session.add(window2)
    session.commit()

    # Draft version
    version = ScheduleVersion(tournament_id=tid, version_number=1, status="draft")
    session.add(version)
    session.commit()
    session.refresh(version)
    version_id = version.id

    # Generate slots
    resp = client.post(
        f"/api/tournaments/{tid}/schedule/slots/generate",
        json={"source": "time_windows", "schedule_version_id": version_id, "wipe_existing": True},
    )
    assert resp.status_code in (200, 201), resp.text
    result = resp.json()

    # Expected: (3 slots × 2 courts) + (2 slots × 1 court) = 8 slots total
    assert result["slots_created"] == 8, f"Expected 8 slots, got {result['slots_created']}"

    # Verify slots in database
    slots = session.exec(
        select(ScheduleSlot).where(ScheduleSlot.schedule_version_id == version_id).order_by(ScheduleSlot.day_date, ScheduleSlot.start_time, ScheduleSlot.court_number)
    ).all()
    assert len(slots) == 8

    # Check window 1 slots (60-minute blocks)
    day1_slots = [s for s in slots if s.day_date == date(2026, 2, 20)]
    assert len(day1_slots) == 6  # 3 slots × 2 courts
    for slot in day1_slots:
        assert slot.block_minutes == 60, f"Window 1 slots must be 60 minutes, got {slot.block_minutes}"
    
    # Verify start times for court 1 on day 1
    court1_day1 = [s for s in day1_slots if s.court_number == 1]
    assert len(court1_day1) == 3
    assert court1_day1[0].start_time == time(9, 0)
    assert court1_day1[0].end_time == time(10, 0)
    assert court1_day1[1].start_time == time(10, 0)
    assert court1_day1[1].end_time == time(11, 0)
    assert court1_day1[2].start_time == time(11, 0)
    assert court1_day1[2].end_time == time(12, 0)

    # Check window 2 slots (105-minute blocks)
    day2_slots = [s for s in slots if s.day_date == date(2026, 2, 21)]
    assert len(day2_slots) == 2  # 2 slots × 1 court
    for slot in day2_slots:
        assert slot.block_minutes == 105, f"Window 2 slots must be 105 minutes, got {slot.block_minutes}"
    
    # Verify start times for court 1 on day 2
    assert day2_slots[0].start_time == time(8, 0)
    assert day2_slots[0].end_time == time(9, 45)
    assert day2_slots[1].start_time == time(9, 45)
    assert day2_slots[1].end_time == time(11, 30)

    # Critical: NO slots should have block_minutes=15
    fifteen_min_slots = [s for s in slots if s.block_minutes == 15]
    assert len(fifteen_min_slots) == 0, f"Found {len(fifteen_min_slots)} 15-minute slots (should be 0)"

