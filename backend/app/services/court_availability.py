"""Operational court openings layered on top of the configured schedule."""

from __future__ import annotations

from datetime import date, datetime, time
from typing import Optional

from sqlmodel import Session, select

from app.models.court_availability_override import CourtAvailabilityClosure, CourtAvailabilityOverride
from app.models.match import Match
from app.models.match_assignment import MatchAssignment
from app.models.schedule_slot import ScheduleSlot


class CourtAvailabilityConflict(Exception):
    """Restoring the original schedule would interrupt an assigned match."""


def _ranges_covering(session: Session, model, version_id: int, day: Optional[date]):
    query = select(model).where(model.schedule_version_id == version_id)
    if day is not None:
        query = query.where(model.day_date == day)
    return list(session.exec(query).all())


def _slots_in_ranges(
    session: Session,
    version_id: int,
    day: Optional[date],
    ranges,
    *,
    inactive_only: bool,
    any_state: bool = False,
) -> set[int]:
    if not ranges:
        return set()
    slots = list(
        session.exec(select(ScheduleSlot).where(ScheduleSlot.schedule_version_id == version_id)).all()
    )
    covered: set[int] = set()
    for slot in slots:
        if slot.id is None or slot.start_time is None:
            continue
        if not any_state and inactive_only and slot.is_active:
            continue
        if not any_state and not inactive_only and not slot.is_active:
            continue
        if day is not None and slot.day_date != day:
            continue
        for row in ranges:
            if row.day_date != slot.day_date or row.court_number != slot.court_number:
                continue
            if row.start_time <= slot.start_time < row.end_time:
                covered.add(slot.id)
                break
    return covered


def covered_slot_ids(session: Session, version_id: int, day: Optional[date] = None) -> set[int]:
    """Inactive slots that an override has opened for this version."""
    ranges = _ranges_covering(session, CourtAvailabilityOverride, version_id, day)
    return _slots_in_ranges(session, version_id, day, ranges, inactive_only=True)


def closed_slot_ids(session: Session, version_id: int, day: Optional[date] = None) -> set[int]:
    """Slots staff have closed. A closure wins over both the schedule and an opening."""
    ranges = _ranges_covering(session, CourtAvailabilityClosure, version_id, day)
    return _slots_in_ranges(session, version_id, day, ranges, inactive_only=False, any_state=True)


def _covers(row, slot: ScheduleSlot) -> bool:
    return (
        slot.start_time is not None
        and row.day_date == slot.day_date
        and row.court_number == slot.court_number
        and row.start_time <= slot.start_time < row.end_time
    )


def _latest_effect(slot: ScheduleSlot, openings, closures) -> Optional[str]:
    """The newest staff action covering this slot. A later open undoes a close."""
    latest: Optional[str] = None
    latest_key = None
    for kind, rows in (("open", openings), ("close", closures)):
        for row in rows:
            if not _covers(row, slot):
                continue
            key = (row.created_at or datetime.min, row.id or 0)
            if latest_key is None or key >= latest_key:
                latest_key = key
                latest = kind
    return latest


def slot_is_open(slot: Optional[ScheduleSlot], openings, closures) -> bool:
    if slot is None:
        return False
    effect = _latest_effect(slot, openings, closures)
    if effect == "close":
        return False
    if effect == "open":
        return True
    return slot.is_active is not False


def effectively_open_slot_ids(session: Session, version_id: int, day: Optional[date] = None) -> set[int]:
    openings = _ranges_covering(session, CourtAvailabilityOverride, version_id, day)
    closures = _ranges_covering(session, CourtAvailabilityClosure, version_id, day)
    slots = list(
        session.exec(select(ScheduleSlot).where(ScheduleSlot.schedule_version_id == version_id)).all()
    )
    return {
        slot.id
        for slot in slots
        if slot.id is not None and (day is None or slot.day_date == day) and slot_is_open(slot, openings, closures)
    }


def slot_effectively_active(session: Session, slot: Optional[ScheduleSlot]) -> bool:
    if slot is None or slot.id is None:
        return False
    return slot.id in effectively_open_slot_ids(session, slot.schedule_version_id, slot.day_date)


def open_court(
    session: Session,
    *,
    tournament_id: int,
    version_id: int,
    day: date,
    court_number: int,
    start: time,
    end: time,
) -> CourtAvailabilityOverride:
    """Record an opening. A matching range is reused so repeats stay idempotent."""
    if end <= start:
        raise ValueError("The availability range must end after it starts.")
    existing = session.exec(
        select(CourtAvailabilityOverride).where(
            CourtAvailabilityOverride.schedule_version_id == version_id,
            CourtAvailabilityOverride.day_date == day,
            CourtAvailabilityOverride.court_number == court_number,
            CourtAvailabilityOverride.start_time == start,
            CourtAvailabilityOverride.end_time == end,
        )
    ).first()
    if existing:
        existing.created_at = datetime.utcnow()
        session.add(existing)
        session.flush()
        return existing
    row = CourtAvailabilityOverride(
        tournament_id=tournament_id,
        schedule_version_id=version_id,
        day_date=day,
        court_number=court_number,
        start_time=start,
        end_time=end,
    )
    session.add(row)
    session.flush()
    return row


def close_court(
    session: Session,
    *,
    tournament_id: int,
    version_id: int,
    day: date,
    court_number: int,
    start: time,
    end: time,
) -> CourtAvailabilityClosure:
    """Close a playable court. Refuse when a match is still assigned in that range."""
    if end <= start:
        raise ValueError("The availability range must end after it starts.")
    openings = _ranges_covering(session, CourtAvailabilityOverride, version_id, day)
    closures = _ranges_covering(session, CourtAvailabilityClosure, version_id, day)
    slots = list(
        session.exec(
            select(ScheduleSlot).where(
                ScheduleSlot.schedule_version_id == version_id,
                ScheduleSlot.day_date == day,
                ScheduleSlot.court_number == court_number,
            )
        ).all()
    )
    for slot in slots:
        if slot.start_time is None or not (start <= slot.start_time < end):
            continue
        if not slot_is_open(slot, openings, closures):
            continue
        assignment = session.exec(
            select(MatchAssignment).where(
                MatchAssignment.schedule_version_id == version_id,
                MatchAssignment.slot_id == slot.id,
            )
        ).first()
        if assignment is None:
            continue
        match = session.get(Match, assignment.match_id)
        status = (match.runtime_status or "SCHEDULED").upper() if match else "SCHEDULED"
        if status != "FINAL":
            label = f"Match #{match.id}" if match and match.id else "A match"
            state = status.replace("_", " ").lower()
            raise CourtAvailabilityConflict(
                f"{label} is {state} on this court. Move or finish it before closing the court."
            )
    existing = session.exec(
        select(CourtAvailabilityClosure).where(
            CourtAvailabilityClosure.schedule_version_id == version_id,
            CourtAvailabilityClosure.day_date == day,
            CourtAvailabilityClosure.court_number == court_number,
            CourtAvailabilityClosure.start_time == start,
            CourtAvailabilityClosure.end_time == end,
        )
    ).first()
    if existing:
        existing.created_at = datetime.utcnow()
        session.add(existing)
        session.flush()
        return existing
    row = CourtAvailabilityClosure(
        tournament_id=tournament_id,
        schedule_version_id=version_id,
        day_date=day,
        court_number=court_number,
        start_time=start,
        end_time=end,
    )
    session.add(row)
    session.flush()
    return row


def restore_court(
    session: Session,
    *,
    version_id: int,
    day: date,
    court_number: int,
) -> int:
    """Remove openings and closures for one court and day.

    An opening is kept when a match still occupies a slot that would turn
    unavailable again. Removing a closure only makes the court playable.
    """
    overrides = list(
        session.exec(
            select(CourtAvailabilityOverride).where(
                CourtAvailabilityOverride.schedule_version_id == version_id,
                CourtAvailabilityOverride.day_date == day,
                CourtAvailabilityOverride.court_number == court_number,
            )
        ).all()
    )
    closures = list(
        session.exec(
            select(CourtAvailabilityClosure).where(
                CourtAvailabilityClosure.schedule_version_id == version_id,
                CourtAvailabilityClosure.day_date == day,
                CourtAvailabilityClosure.court_number == court_number,
            )
        ).all()
    )
    if not overrides and not closures:
        return 0
    covered = covered_slot_ids(session, version_id, day)
    slots = list(
        session.exec(
            select(ScheduleSlot).where(
                ScheduleSlot.schedule_version_id == version_id,
                ScheduleSlot.day_date == day,
                ScheduleSlot.court_number == court_number,
            )
        ).all()
    )
    for slot in slots:
        if slot.id not in covered or slot.is_active:
            continue
        assignment = session.exec(
            select(MatchAssignment).where(
                MatchAssignment.schedule_version_id == version_id,
                MatchAssignment.slot_id == slot.id,
            )
        ).first()
        if assignment is None:
            continue
        match = session.get(Match, assignment.match_id)
        status = (match.runtime_status or "SCHEDULED").upper() if match else "SCHEDULED"
        if status != "FINAL":
            label = f"Match #{match.id}" if match and match.id else "A match"
            state = status.replace("_", " ").lower()
            raise CourtAvailabilityConflict(
                f"{label} is {state} on this court. Move or finish it before restoring the original schedule."
            )
    for row in overrides + closures:
        session.delete(row)
    session.flush()
    return len(overrides) + len(closures)
