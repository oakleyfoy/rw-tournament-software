from datetime import date, time

import pytest

from app.models.schedule_slot import ScheduleSlot
from app.services.schedule_slot_availability import (
    CourtSlotUnavailableError,
    board_courts_for_slot_key,
    format_slot_time_label,
    slot_key,
    validate_checkin_court_assignment,
)


def _slot(*, start: time, court_number: int, is_active: bool = True, day: date = date(2026, 7, 10)) -> ScheduleSlot:
    return ScheduleSlot(
        tournament_id=1,
        schedule_version_id=1,
        day_date=day,
        start_time=start,
        end_time=time(start.hour + 1, start.minute),
        court_number=court_number,
        court_label=str(court_number),
        block_minutes=60,
        is_active=is_active,
    )


def test_board_courts_ignore_inactive_and_other_times():
    slots = [
        _slot(start=time(9, 30), court_number=1),
        _slot(start=time(9, 30), court_number=9, is_active=False),
        _slot(start=time(12, 30), court_number=9),
    ]
    courts = board_courts_for_slot_key(slots, slot_key(date(2026, 7, 10), time(9, 30)))
    assert courts == ["Court 1"]


def test_validate_rejects_court_missing_from_active_board():
    slots = [
        _slot(start=time(10, 30), court_number=1),
        _slot(start=time(12, 30), court_number=9),
    ]
    match_slot = slots[0]
    target = slots[1]
    with pytest.raises(CourtSlotUnavailableError, match="Court 9 is not available for the 10:30 AM schedule slot."):
        validate_checkin_court_assignment(
            slots=slots,
            target_slot=target,
            match_slot=match_slot,
            active_slot_key=slot_key(date(2026, 7, 10), time(10, 30)),
        )


def test_validate_allows_earlier_match_onto_court_at_active_block():
    slots = [
        _slot(start=time(10, 30), court_number=1),
        _slot(start=time(12, 30), court_number=1),
        _slot(start=time(12, 30), court_number=9),
    ]
    validate_checkin_court_assignment(
        slots=slots,
        target_slot=slots[2],
        match_slot=slots[0],
        active_slot_key=slot_key(date(2026, 7, 10), time(12, 30)),
    )


def test_format_slot_time_label_matches_desk_copy():
    assert format_slot_time_label(time(10, 30)) == "10:30 AM"
    assert format_slot_time_label(time(8, 30)) == "8:30 AM"
    assert format_slot_time_label(time(12, 30)) == "12:30 PM"
