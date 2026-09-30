"""Per-event, per-date court assignment mode.

DYNAMIC_CHECKIN is the default and matches the existing check-in desk:
teams check in, then staff assigns a court.

PREASSIGNED keeps the match on its scheduled time and court. Check-in can
still be recorded, but it does not decide whether the match has a court.
"""

from __future__ import annotations

import json
from datetime import date, datetime, time
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from sqlmodel import Session, select

from app.models.event import Event
from app.models.match import Match
from app.models.match_assignment import MatchAssignment
from app.models.schedule_slot import ScheduleSlot

MODE_DYNAMIC_CHECKIN = "DYNAMIC_CHECKIN"
MODE_PREASSIGNED = "PREASSIGNED"
ALLOWED_COURT_ASSIGNMENT_MODES = {MODE_DYNAMIC_CHECKIN, MODE_PREASSIGNED}


def _as_date(value: object) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return None
        try:
            return date.fromisoformat(raw[:10])
        except ValueError:
            return None
    return None


def parse_court_assignment_modes(raw: Optional[str]) -> Dict[date, str]:
    """Return explicit date overrides. Unknown or invalid entries are ignored."""
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    modes: Dict[date, str] = {}
    for key, value in payload.items():
        day = _as_date(key)
        mode = str(value or "").strip().upper()
        if day is None or mode not in ALLOWED_COURT_ASSIGNMENT_MODES:
            continue
        if mode == MODE_DYNAMIC_CHECKIN:
            continue
        modes[day] = mode
    return modes


def resolve_court_assignment_mode(event: Optional[Event], day_value: object) -> str:
    """Mode for one event on one calendar date. Missing config is dynamic check-in."""
    day = _as_date(day_value)
    if event is None or day is None:
        return MODE_DYNAMIC_CHECKIN
    modes = parse_court_assignment_modes(getattr(event, "court_assignment_by_date_json", None))
    return modes.get(day, MODE_DYNAMIC_CHECKIN)


def is_preassigned(event: Optional[Event], day_value: object) -> bool:
    return resolve_court_assignment_mode(event, day_value) == MODE_PREASSIGNED


def modes_as_iso(event: Optional[Event]) -> Dict[str, str]:
    modes = parse_court_assignment_modes(getattr(event, "court_assignment_by_date_json", None) if event else None)
    return {day.isoformat(): mode for day, mode in sorted(modes.items())}


def replace_court_assignment_modes(event: Event, modes: Mapping[object, str]) -> None:
    """Replace this event's date overrides. DYNAMIC_CHECKIN dates are stored by omission."""
    stored: Dict[str, str] = {}
    for key, value in modes.items():
        day = _as_date(key)
        mode = str(value or "").strip().upper()
        if day is None:
            raise ValueError(f"Invalid court assignment date: {key}")
        if mode not in ALLOWED_COURT_ASSIGNMENT_MODES:
            raise ValueError(f"Invalid court assignment mode: {value}")
        if mode == MODE_PREASSIGNED:
            stored[day.isoformat()] = MODE_PREASSIGNED
    event.court_assignment_by_date_json = json.dumps(stored, sort_keys=True) if stored else None


def _clock_minutes(value: object) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, datetime):
        value = value.time()
    if isinstance(value, time):
        return value.hour * 60 + value.minute
    if isinstance(value, str):
        parts = value.split(":")
        if len(parts) < 2:
            return None
        try:
            return int(parts[0]) * 60 + int(parts[1])
        except ValueError:
            return None
    return None


def _slot_window_minutes(slot: ScheduleSlot) -> Optional[Tuple[int, int]]:
    start = _clock_minutes(slot.start_time)
    if start is None:
        return None
    end = _clock_minutes(slot.end_time)
    if end is None or end <= start:
        end = start + int(slot.block_minutes or 0)
    if end <= start:
        end = start + 60
    return start, end


def slots_overlap(left: ScheduleSlot, right: ScheduleSlot) -> bool:
    """True when two slots reserve the same court on the same day at the same time."""
    if left.day_date != right.day_date or left.court_number != right.court_number:
        return False
    if left.id is not None and left.id == right.id:
        return True
    left_window = _slot_window_minutes(left)
    right_window = _slot_window_minutes(right)
    if left_window is None or right_window is None:
        return False
    left_start, left_end = left_window
    right_start, right_end = right_window
    return left_start < right_end and right_start < left_end


def preassigned_reservations(
    session: Session,
    schedule_version_id: int,
) -> List[Tuple[Match, ScheduleSlot]]:
    """Preassigned matches that still reserve their scheduled court window.

    A match reserves only its slot's half-open window, [start, end). The next
    block that starts at the previous end is free. FINAL drops the reservation
    immediately, including before that end time. A result that was never
    entered does not keep the court after the window.

    While a match is IN_PROGRESS or PAUSED, the desk already withholds that
    court from live check-in assignment. That live state is separate from
    this scheduled window.
    """
    assignments = session.exec(
        select(MatchAssignment).where(MatchAssignment.schedule_version_id == schedule_version_id)
    ).all()
    reserved: List[Tuple[Match, ScheduleSlot]] = []
    for assignment in assignments:
        match = session.get(Match, assignment.match_id)
        slot = session.get(ScheduleSlot, assignment.slot_id)
        if match is None or slot is None:
            continue
        if (match.runtime_status or "SCHEDULED").upper() == "FINAL":
            continue
        event = session.get(Event, match.event_id)
        if is_preassigned(event, slot.day_date):
            reserved.append((match, slot))
    return reserved


def preassigned_court_block_reason(
    slot: ScheduleSlot,
    reservations: Sequence[Tuple[Match, ScheduleSlot]],
    *,
    ignore_match_id: Optional[int] = None,
) -> Optional[str]:
    """Why this slot cannot be offered, or None when the court is free."""
    for match, occupied in reservations:
        if ignore_match_id is not None and match.id == ignore_match_id:
            continue
        if not slots_overlap(slot, occupied):
            continue
        label = (occupied.court_label or str(occupied.court_number)).strip()
        court_name = label if label.lower().startswith("court") else f"Court {label}"
        return f"{court_name} is reserved for a preassigned match."
    return None


def note_preassigned_reservation(
    reservations: List[Tuple[Match, ScheduleSlot]],
    session: Session,
    match: Match,
    slot: ScheduleSlot,
) -> None:
    """Replace this match's reservation after an automatic placement."""
    match_id = match.id
    reservations[:] = [item for item in reservations if item[0].id != match_id]
    if (match.runtime_status or "SCHEDULED").upper() == "FINAL":
        return
    event = session.get(Event, match.event_id) if match.event_id else None
    if is_preassigned(event, slot.day_date):
        reservations.append((match, slot))
