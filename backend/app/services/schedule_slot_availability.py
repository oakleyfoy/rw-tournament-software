"""
Canonical Schedule Grid slot availability.

A court/time cell exists when an is_active ScheduleSlot row exists for
(schedule_version, day_date, start_time, court). Deleted Grid slots are
hard-deleted rows; inactive rows are hidden from the Grid and from Desk.
"""

from __future__ import annotations

from datetime import date
from typing import Iterable, Optional

from app.models.schedule_slot import ScheduleSlot


class CourtSlotUnavailableError(Exception):
    def __init__(self, court_name: str, time_label: str):
        self.court_name = court_name
        self.time_label = time_label
        super().__init__(f"{court_name} is not available for the {time_label} schedule slot.")


def slot_start_hhmm(start_time) -> str:
    if hasattr(start_time, "strftime"):
        return start_time.strftime("%H:%M")
    text = str(start_time or "")
    return text[:5] if len(text) >= 5 else text


def slot_key(day_date: date, start_time) -> str:
    day = day_date.isoformat() if hasattr(day_date, "isoformat") else str(day_date)
    return f"{day}|{slot_start_hhmm(start_time)}"


def slot_key_for_slot(slot: ScheduleSlot) -> str:
    return slot_key(slot.day_date, slot.start_time)


def format_slot_time_label(start_time) -> str:
    hhmm = slot_start_hhmm(start_time)
    parts = hhmm.split(":")
    hour = int(parts[0]) if parts and parts[0].isdigit() else 0
    minute = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
    return f"{(hour % 12) or 12}:{minute:02d} {'AM' if hour < 12 else 'PM'}"


def format_slot_key_time_label(key: str) -> str:
    _, _, hhmm = key.partition("|")
    return format_slot_time_label(hhmm)


def court_display_name(court_label: Optional[str], court_number: Optional[int] = None) -> str:
    label = (court_label or "").strip() or (str(court_number) if court_number is not None else "")
    if not label:
        return "Court"
    if label.lower().startswith("court"):
        return label
    return f"Court {label}"


def court_display_for_slot(slot: ScheduleSlot) -> str:
    return court_display_name(slot.court_label, slot.court_number)


def is_grid_active_slot(slot: ScheduleSlot) -> bool:
    return bool(getattr(slot, "is_active", True))


def iter_grid_slots(slots: Iterable[ScheduleSlot]) -> list[ScheduleSlot]:
    return [slot for slot in slots if is_grid_active_slot(slot)]


def slots_for_key(slots: Iterable[ScheduleSlot], key: Optional[str]) -> list[ScheduleSlot]:
    if not key:
        return []
    return [slot for slot in iter_grid_slots(slots) if slot_key_for_slot(slot) == key]


def find_court_slot(
    slots: Iterable[ScheduleSlot],
    court_name: str,
    day_date: date,
    start_time,
) -> Optional[ScheduleSlot]:
    expected = court_display_name(court_name)
    for slot in slots_for_key(slots, slot_key(day_date, start_time)):
        if court_display_for_slot(slot) == expected:
            return slot
    return None


def board_courts_for_slot_key(slots: Iterable[ScheduleSlot], key: Optional[str]) -> list[str]:
    courts = {court_display_for_slot(slot) for slot in slots_for_key(slots, key)}
    return sorted(
        courts,
        key=lambda name: (int("".join(ch for ch in name if ch.isdigit()) or "0"), name),
    )


def board_courts_for_slot_keys(slots: Iterable[ScheduleSlot], keys: Iterable[str]) -> list[str]:
    courts: set[str] = set()
    for key in keys:
        courts.update(board_courts_for_slot_key(slots, key))
    return sorted(
        courts,
        key=lambda name: (int("".join(ch for ch in name if ch.isdigit()) or "0"), name),
    )


def ordered_activity_slot_keys(ordered_keys: Iterable[str], *key_sets: Iterable[str]) -> list[str]:
    activity: set[str] = set()
    for key_set in key_sets:
        activity.update(key for key in key_set if key)
    return [key for key in ordered_keys if key in activity]


def desk_operational_slot_keys(
    ordered_keys: Iterable[str],
    *,
    playing_keys: Iterable[str],
    ready_keys: Iterable[str],
    waiting_keys: Iterable[str],
    grid_slots: Iterable[ScheduleSlot],
) -> list[str]:
    """
    Desk board keys for Open Courts / assign remaps.

    Playing and ready blocks stay visible, including leftover earlier
    matches. Later waiting-only blocks (8:00 playing + 9:00 waiting) do
    not open next-hour courts. Later-only courts such as 9/10 at 12:30
    still appear when a ready match has no cell at its own time.
    """
    ordered = list(ordered_keys)
    playing = {key for key in playing_keys if key}
    ready = {key for key in ready_keys if key}
    waiting = {key for key in waiting_keys if key}
    operational = ordered_activity_slot_keys(ordered, playing, ready)
    if not operational:
        return [key for key in ordered if key in waiting][:1]

    slot_list = list(grid_slots)
    operational_courts = set(board_courts_for_slot_keys(slot_list, operational))
    later_keys = [key for key in ordered if key not in operational and key in waiting]
    if not ready or not later_keys:
        return operational

    ready_courts = set(board_courts_for_slot_keys(slot_list, ready))
    for later in later_keys:
        later_only = set(board_courts_for_slot_key(slot_list, later)) - operational_courts
        if later_only and later_only - ready_courts:
            return ordered_activity_slot_keys(ordered, operational, [later])
    return operational


def desk_board_courts(
    grid_slots: Iterable[ScheduleSlot],
    *,
    operational_keys: Iterable[str],
    playing_courts: Iterable[str],
    ready_keys: Iterable[str],
) -> list[str]:
    """
    Courts on the Check-In board.

    Use the earliest playing/ready block, plus leftover in-progress
    courts. Empty later-block courts (11/12/19-22 at 12:30) stay hidden
    unless a ready match actually needs that later time.
    """
    slot_list = list(grid_slots)
    keys = [key for key in operational_keys if key]
    if not keys:
        return []

    courts = set(board_courts_for_slot_key(slot_list, keys[0]))
    courts.update(court_display_name(name) for name in playing_courts if name)

    ready = {key for key in ready_keys if key}
    if ready:
        ready_key_set = ready
        for key in keys[1:]:
            if key in ready_key_set:
                courts.update(board_courts_for_slot_key(slot_list, key))
        ready_courts = set(board_courts_for_slot_keys(slot_list, ready))
        for later in keys[1:]:
            later_only = set(board_courts_for_slot_key(slot_list, later)) - courts
            if later_only and later_only - ready_courts:
                courts.update(later_only)
                break

    return sorted(
        courts,
        key=lambda name: (int("".join(ch for ch in name if ch.isdigit()) or "0"), name),
    )


def court_has_slot_at_key(slots: Iterable[ScheduleSlot], court_name: str, key: Optional[str]) -> bool:
    expected = court_display_name(court_name)
    return any(court_display_for_slot(slot) == expected for slot in slots_for_key(slots, key))


def validate_checkin_court_assignment(
    *,
    slots: Iterable[ScheduleSlot],
    target_slot: ScheduleSlot,
    match_slot: Optional[ScheduleSlot],
    active_slot_key: Optional[str],
    allowed_slot_keys: Optional[Iterable[str]] = None,
) -> None:
    """
    Reject a check-in drop when the target court/time is not an active
    Desk board block (or the match's own scheduled time).

    Leftover earlier matches may still be playing; later Grid cells such as
    Courts 9/10/19/20 at 12:30 stay assignable when those keys are allowed.
    """
    slot_list = list(slots)
    court_name = court_display_for_slot(target_slot)
    if not is_grid_active_slot(target_slot):
        raise CourtSlotUnavailableError(court_name, format_slot_time_label(target_slot.start_time))

    allowed = {key for key in (allowed_slot_keys or []) if key}
    if active_slot_key:
        allowed.add(active_slot_key)
    match_key = slot_key_for_slot(match_slot) if match_slot is not None else None
    if match_key:
        allowed.add(match_key)

    target_key = slot_key_for_slot(target_slot)
    if allowed and target_key not in allowed:
        raise CourtSlotUnavailableError(court_name, format_slot_time_label(target_slot.start_time))
    if not court_has_slot_at_key(slot_list, court_name, target_key):
        raise CourtSlotUnavailableError(court_name, format_slot_time_label(target_slot.start_time))
