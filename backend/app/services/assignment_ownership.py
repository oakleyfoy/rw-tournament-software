"""Cross-tournament ownership checks for MatchAssignment writes and reads."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import List, Optional, Tuple

from sqlmodel import Session, select

from app.models.event import Event
from app.models.match import Match
from app.models.match_assignment import MatchAssignment
from app.models.schedule_slot import ScheduleSlot
from app.models.schedule_version import ScheduleVersion

logger = logging.getLogger(__name__)


class AssignmentOwnershipError(ValueError):
    """Raised when an assignment would cross tournament or version ownership."""


def _missing(label: str, object_id: int) -> AssignmentOwnershipError:
    return AssignmentOwnershipError(f"Cannot assign: {label} {object_id} not found")


def validate_assignment_ownership(
    session: Session,
    *,
    schedule_version_id: int,
    match_id: int,
    slot_id: int,
    tournament_id: Optional[int] = None,
) -> None:
    """
    Require a single tournament owns the version, slot, match, and event.

    Also require the slot and match belong to the intended schedule version.
    Does not mutate any rows.
    """
    version = session.get(ScheduleVersion, schedule_version_id)
    if version is None:
        raise _missing("schedule version", schedule_version_id)

    expected_tid = tournament_id if tournament_id is not None else version.tournament_id
    if expected_tid is None:
        raise AssignmentOwnershipError("Cannot assign: tournament_id is required")

    slot = session.get(ScheduleSlot, slot_id)
    if slot is None:
        raise _missing("slot", slot_id)

    match = session.get(Match, match_id)
    if match is None:
        raise _missing("match", match_id)

    event = session.get(Event, match.event_id)
    if event is None:
        raise _missing("event", match.event_id)

    version_ok = version.tournament_id == expected_tid
    slot_ok = slot.tournament_id == expected_tid
    match_ok = match.tournament_id == expected_tid
    event_ok = event.tournament_id == expected_tid
    slot_version_ok = slot.schedule_version_id == schedule_version_id
    match_version_ok = match.schedule_version_id == schedule_version_id

    if version_ok and slot_ok and match_ok and event_ok and slot_version_ok and match_version_ok:
        return

    raise AssignmentOwnershipError(
        "Cannot assign match "
        f"{match_id} to slot {slot_id} on schedule version {schedule_version_id}: "
        "ownership mismatch "
        f"(version.tournament_id={version.tournament_id}, "
        f"slot.tournament_id={slot.tournament_id}, "
        f"match.tournament_id={match.tournament_id}, "
        f"event.tournament_id={event.tournament_id}; "
        f"expected tournament_id={expected_tid}; "
        f"slot.schedule_version_id={slot.schedule_version_id}, "
        f"match.schedule_version_id={match.schedule_version_id}). "
        "Cross-tournament assignments are not allowed."
    )


def create_owned_assignment(
    session: Session,
    *,
    schedule_version_id: int,
    match_id: int,
    slot_id: int,
    tournament_id: Optional[int] = None,
    assigned_by: Optional[str] = None,
    locked: bool = False,
    assigned_at: Optional[datetime] = None,
) -> MatchAssignment:
    """Validate ownership, construct a MatchAssignment, and session.add it. Does not commit."""
    validate_assignment_ownership(
        session,
        schedule_version_id=schedule_version_id,
        match_id=match_id,
        slot_id=slot_id,
        tournament_id=tournament_id,
    )
    assignment = MatchAssignment(
        schedule_version_id=schedule_version_id,
        match_id=match_id,
        slot_id=slot_id,
        assigned_by=assigned_by,
        locked=locked,
        assigned_at=assigned_at if assigned_at is not None else datetime.utcnow(),
    )
    session.add(assignment)
    return assignment


def try_create_owned_assignment(
    session: Session,
    *,
    schedule_version_id: int,
    match_id: int,
    slot_id: int,
    tournament_id: Optional[int] = None,
    assigned_by: Optional[str] = None,
    locked: bool = False,
    assigned_at: Optional[datetime] = None,
) -> Optional[MatchAssignment]:
    """Like create_owned_assignment, but logs and returns None on ownership failure."""
    try:
        return create_owned_assignment(
            session,
            schedule_version_id=schedule_version_id,
            match_id=match_id,
            slot_id=slot_id,
            tournament_id=tournament_id,
            assigned_by=assigned_by,
            locked=locked,
            assigned_at=assigned_at,
        )
    except AssignmentOwnershipError as exc:
        logger.error("Rejected cross-tournament assignment: %s", exc)
        return None


def load_owned_matches_for_version(
    session: Session,
    *,
    tournament_id: int,
    schedule_version_id: int,
) -> List[Match]:
    """
    Matches on this version that belong to this tournament, including Event ownership.

    Rows with a matching schedule_version_id but a foreign Match.tournament_id
    or Event.tournament_id are omitted and logged. Never auto-corrects ownership.
    """
    matches = session.exec(
        select(Match).where(
            Match.schedule_version_id == schedule_version_id,
            Match.tournament_id == tournament_id,
        )
    ).all()
    if not matches:
        return []

    event_ids = {m.event_id for m in matches}
    events = session.exec(select(Event).where(Event.id.in_(event_ids))).all()
    event_by_id = {e.id: e for e in events if e.id is not None}

    owned: List[Match] = []
    for match in matches:
        event = event_by_id.get(match.event_id)
        if event is None or event.tournament_id != tournament_id:
            logger.warning(
                "Skipping match %s on version %s: event ownership mismatch "
                "(match.tournament_id=%s event_id=%s event.tournament_id=%s requested_tournament_id=%s)",
                match.id,
                schedule_version_id,
                match.tournament_id,
                match.event_id,
                getattr(event, "tournament_id", None),
                tournament_id,
            )
            continue
        owned.append(match)
    return owned


def assignment_ownership_issue(
    session: Session,
    assignment: MatchAssignment,
    tournament_id: int,
) -> Optional[str]:
    """Return a diagnostic string if this assignment is not owned by tournament_id."""
    try:
        validate_assignment_ownership(
            session,
            schedule_version_id=assignment.schedule_version_id,
            match_id=assignment.match_id,
            slot_id=assignment.slot_id,
            tournament_id=tournament_id,
        )
    except AssignmentOwnershipError as exc:
        return str(exc)
    return None


def partition_owned_assignments(
    session: Session,
    assignments: List[MatchAssignment],
    tournament_id: int,
) -> Tuple[List[MatchAssignment], List[str]]:
    """Split assignments into owned rows and ownership-issue messages."""
    owned: List[MatchAssignment] = []
    issues: List[str] = []
    for assignment in assignments:
        issue = assignment_ownership_issue(session, assignment, tournament_id)
        if issue is None:
            owned.append(assignment)
            continue
        logger.error(
            "Excluding cross-tournament assignment id=%s match_id=%s slot_id=%s version=%s: %s",
            assignment.id,
            assignment.match_id,
            assignment.slot_id,
            assignment.schedule_version_id,
            issue,
        )
        issues.append(issue)
    return owned, issues
