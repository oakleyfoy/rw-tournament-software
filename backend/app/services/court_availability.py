"""Operational court openings layered on top of the configured schedule."""

from __future__ import annotations

from datetime import date, time
from typing import Optional

from sqlmodel import Session, select

from app.models.court_availability_override import CourtAvailabilityOverride
from app.models.match import Match
from app.models.match_assignment import MatchAssignment
from app.models.schedule_slot import ScheduleSlot


class CourtAvailabilityConflict(Exception):
    """Restoring the original schedule would interrupt an assigned match."""


def covered_slot_ids(session: Session, version_id: int, day: Optional[date] = None) -> set[int]:
    """Inactive slots that an override has opened for this version."""
    query = select(CourtAvailabilityOverride).where(
        CourtAvailabilityOverride.schedule_version_id == version_id
    )
    if day is not None:
        query = query.where(CourtAvailabilityOverride.day_date == day)
    overrides = list(session.exec(query).all())
    if not overrides:
        return set()
    slots = list(
        session.exec(select(ScheduleSlot).where(ScheduleSlot.schedule_version_id == version_id)).all()
    )
    covered: set[int] = set()
    for slot in slots:
        if slot.id is None or slot.is_active or slot.start_time is None:
            continue
        if day is not None and slot.day_date != day:
            continue
        for override in overrides:
            if override.day_date != slot.day_date or override.court_number != slot.court_number:
                continue
            if override.start_time <= slot.start_time < override.end_time:
                covered.add(slot.id)
                break
    return covered


def slot_effectively_active(session: Session, slot: Optional[ScheduleSlot]) -> bool:
    if slot is None:
        return False
    if slot.is_active is not False:
        return True
    if slot.id is None:
        return False
    return slot.id in covered_slot_ids(session, slot.schedule_version_id, slot.day_date)


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


def restore_court(
    session: Session,
    *,
    version_id: int,
    day: date,
    court_number: int,
) -> int:
    """Remove overrides for one court and day unless a match still occupies them."""
    overrides = list(
        session.exec(
            select(CourtAvailabilityOverride).where(
                CourtAvailabilityOverride.schedule_version_id == version_id,
                CourtAvailabilityOverride.day_date == day,
                CourtAvailabilityOverride.court_number == court_number,
            )
        ).all()
    )
    if not overrides:
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
    for row in overrides:
        session.delete(row)
    session.flush()
    return len(overrides)
