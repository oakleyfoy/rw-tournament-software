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
from app.models import Event, Match, MatchAssignment, ScheduleSlot, ScheduleVersion, Tournament, TournamentTimeWindow


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
        select(ScheduleSlot)
        .where(ScheduleSlot.schedule_version_id == version_id)
        .order_by(ScheduleSlot.day_date, ScheduleSlot.start_time, ScheduleSlot.court_number)
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


def test_generate_slots_marks_extra_courts_manual_only(client: TestClient, session: Session):
    tournament = Tournament(
        name="Extra Courts Test",
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

    window = TournamentTimeWindow(
        tournament_id=tid,
        day_date=date(2026, 2, 20),
        start_time=time(9, 0),
        end_time=time(11, 0),
        courts_available=2,
        extra_courts=2,
        block_minutes=60,
        is_active=True,
    )
    session.add(window)
    session.commit()

    version = ScheduleVersion(tournament_id=tid, version_number=1, status="draft")
    session.add(version)
    session.commit()
    session.refresh(version)

    resp = client.post(
        f"/api/tournaments/{tid}/schedule/slots/generate",
        json={"source": "time_windows", "schedule_version_id": version.id, "wipe_existing": True},
    )
    assert resp.status_code in (200, 201), resp.text
    result = resp.json()
    assert result["slots_created"] == 8

    slots = session.exec(
        select(ScheduleSlot)
        .where(ScheduleSlot.schedule_version_id == version.id)
        .order_by(ScheduleSlot.court_number, ScheduleSlot.start_time)
    ).all()
    assert len(slots) == 8

    regular_slots = [s for s in slots if s.court_number in (1, 2)]
    extra_slots = [s for s in slots if s.court_number in (3, 4)]
    assert len(regular_slots) == 4
    assert len(extra_slots) == 4
    assert all(not s.is_manual_only for s in regular_slots)
    assert all(s.is_manual_only for s in extra_slots)


def test_run_sequence_schedule_skips_manual_only_slots(session: Session):
    from app.services.schedule_sequence import run_sequence_schedule

    tournament = Tournament(
        name="Manual Only Sequence Test",
        location="Test",
        timezone="America/New_York",
        start_date=date(2026, 2, 20),
        end_date=date(2026, 2, 20),
        use_time_windows=True,
    )
    session.add(tournament)
    session.commit()
    session.refresh(tournament)

    event = Event(
        tournament_id=tournament.id,
        name="Mixed",
        category="mixed",
        team_count=8,
    )
    session.add(event)
    session.commit()
    session.refresh(event)

    version = ScheduleVersion(tournament_id=tournament.id, version_number=1, status="draft")
    session.add(version)
    session.commit()
    session.refresh(version)

    regular_slots = []
    manual_only_slots = []
    for court_num in [1, 2]:
        regular_slots.append(
            ScheduleSlot(
                tournament_id=tournament.id,
                schedule_version_id=version.id,
                day_date=date(2026, 2, 20),
                start_time=time(9, 0),
                end_time=time(10, 0),
                court_number=court_num,
                court_label=f"Court {court_num}",
                block_minutes=60,
                is_active=True,
                is_manual_only=False,
            )
        )
    for court_num in [3, 4]:
        manual_only_slots.append(
            ScheduleSlot(
                tournament_id=tournament.id,
                schedule_version_id=version.id,
                day_date=date(2026, 2, 20),
                start_time=time(9, 0),
                end_time=time(10, 0),
                court_number=court_num,
                court_label=f"Court {court_num}",
                block_minutes=60,
                is_active=True,
                is_manual_only=True,
            )
        )
    session.add_all(regular_slots + manual_only_slots)
    session.commit()

    matches = []
    for idx in range(1, 5):
        matches.append(
            Match(
                tournament_id=tournament.id,
                event_id=event.id,
                schedule_version_id=version.id,
                match_code=f"MIX_SEQ_{idx:02d}",
                match_type="WF",
                round_number=1,
                round_index=1,
                sequence_in_round=idx,
                duration_minutes=60,
                placeholder_side_a=f"Team A{idx}",
                placeholder_side_b=f"Team B{idx}",
                status="unscheduled",
            )
        )
    session.add_all(matches)
    session.commit()

    result = run_sequence_schedule(session, tournament.id, version.id)
    session.flush()

    assignments = session.exec(select(MatchAssignment).where(MatchAssignment.schedule_version_id == version.id)).all()
    assigned_slot_ids = {a.slot_id for a in assignments}
    regular_slot_ids = {s.id for s in regular_slots}
    manual_only_slot_ids = {s.id for s in manual_only_slots}

    assert result.total_assigned == 2
    assert len(assignments) == 2
    assert assigned_slot_ids <= regular_slot_ids
    assert assigned_slot_ids.isdisjoint(manual_only_slot_ids)
