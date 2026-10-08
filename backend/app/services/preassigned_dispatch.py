"""PREASSIGNED waterfall court dispatch.

Automation runs only when Event.court_assignment_by_date_json resolves to
PREASSIGNED for the match's event/date at execution time. DYNAMIC_CHECKIN days
are never auto-dispatched.
"""

from __future__ import annotations

import logging
import time as time_module
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, datetime, time
from typing import Dict, Iterator, List, Optional, Sequence, Set, Tuple
from zoneinfo import ZoneInfo

from sqlalchemy.exc import IntegrityError, OperationalError
from sqlmodel import Session, select

from app.db_schema_patch import is_preassigned_automation_schema_ready
from app.models.court_dispatch_lock import CourtDispatchLock
from app.models.court_state import TournamentCourtState
from app.models.event import Event
from app.models.match import Match
from app.models.match_assignment import MatchAssignment
from app.models.match_checkin import MatchCheckIn
from app.models.match_player_checkin import MatchPlayerCheckIn
from app.models.opening_slot_release import OpeningSlotRelease
from app.models.schedule_slot import ScheduleSlot
from app.models.schedule_version import ScheduleVersion
from app.models.team_player import TeamPlayer
from app.models.tournament import Tournament
from app.services.court_assignment_mode import is_preassigned
from app.services.schedule_slot_availability import (
    court_display_for_slot,
    slot_key_for_slot,
)
from app.services.sms_automation import SmsAutomationEngine

logger = logging.getLogger(__name__)

LIVE_STATUSES = frozenset({"IN_PROGRESS", "PAUSED"})
DONE_OR_LIVE = frozenset({"IN_PROGRESS", "PAUSED", "FINAL"})

OUTCOME_READY_TO_START = "ready_to_start"
OUTCOME_WAITING_COURT = "waiting_court"
OUTCOME_WAITING_CHECKIN = "waiting_checkin"
OUTCOME_WAITING_RELEASE = "waiting_release"
OUTCOME_WAITING_TIME = "waiting_time"
OUTCOME_WAITING_PARTICIPANTS = "waiting_participants"
OUTCOME_WAITING_PRIOR = "waiting_prior"
OUTCOME_SKIP = "skip"

SCHEMA_NOT_READY = "preassigned_automation_schema_not_ready"
COURT_LOCK_BUSY = "court_dispatch_lock_busy"

_LOCK_ACQUIRE_ATTEMPTS = 12
_LOCK_ACQUIRE_SLEEP_SEC = 0.05
_DISPATCH_BUSY_ATTEMPTS = 8
_DISPATCH_BUSY_SLEEP_SEC = 0.05
# Reclaim committed orphan rows left by a crashed process. Uncommitted crash
# rollbacks never leave a row; this covers the rare committed-orphan case.
_LOCK_STALE_SECONDS = 30


class PreassignedSchemaNotReady(RuntimeError):
    """Raised when required PREASSIGNED automation tables/constraints are missing."""


def _is_sqlite_locked(exc: BaseException) -> bool:
    """True only for SQLite writer contention, not unrelated OperationalErrors."""
    messages: List[str] = [str(exc).lower()]
    orig = getattr(exc, "orig", None)
    if orig is not None:
        messages.append(str(orig).lower())
    cause = getattr(exc, "__cause__", None)
    if cause is not None:
        messages.append(str(cause).lower())
    return any("database is locked" in msg or "database table is locked" in msg for msg in messages)


def _require_schema_ready(session: Session) -> Optional[str]:
    bind = session.get_bind()
    if bind is None:
        return SCHEMA_NOT_READY
    # Prefer process cache; on miss inspect via this session's connection so we
    # do not open a second SQLite connection during an active write txn.
    if is_preassigned_automation_schema_ready(
        bind,
        connection=session.connection(),
        use_cache=True,
    ):
        return None
    return SCHEMA_NOT_READY


@dataclass
class EligibilityResult:
    match_id: int
    outcome: str
    reason: str
    court_name: Optional[str] = None
    scheduled_time: Optional[str] = None
    day_date: Optional[date] = None
    slot_key: Optional[str] = None
    is_opening: bool = False
    occupying_match_id: Optional[int] = None


@dataclass
class DispatchResult:
    started_match_ids: List[int] = field(default_factory=list)
    waiting_match_ids: List[int] = field(default_factory=list)
    skipped: List[EligibilityResult] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


@dataclass
class OpeningReleaseEventSummary:
    event_id: int
    event_name: str
    ready_count: int
    awaiting_checkin_count: int
    match_ids: List[int] = field(default_factory=list)


@dataclass
class OpeningReleasePreview:
    slot_key: str
    day_date: date
    scheduled_time_label: str
    scheduled_count: int
    ready_count: int
    awaiting_checkin_count: int
    courts_available_count: int
    courts_occupied_count: int
    already_released: bool
    ready_match_ids: List[int] = field(default_factory=list)
    awaiting_checkin_match_ids: List[int] = field(default_factory=list)
    # Intentionally slot-scoped across PREASSIGNED WF R1 events sharing the time.
    events: List[OpeningReleaseEventSummary] = field(default_factory=list)
    scope_note: str = (
        "Releases all PREASSIGNED WF Round 1 matches in this tournament/version "
        "time slot. DYNAMIC_CHECKIN events in the same slot are not included."
    )


def is_opening_waterfall(match: Match) -> bool:
    """Opening round: WF with canonical round_index == 1 (see match_generation)."""
    return (match.match_type or "").upper() == "WF" and int(match.round_index or 0) == 1


def is_subsequent_waterfall(match: Match) -> bool:
    return (match.match_type or "").upper() == "WF" and int(match.round_index or 0) >= 2


def _coerce_slot_start_time(value: object) -> Optional[time]:
    if isinstance(value, time):
        return value
    if isinstance(value, datetime):
        return value.time()
    if isinstance(value, str):
        parts = value.strip().split(":")
        if len(parts) >= 2:
            try:
                return time(int(parts[0]), int(parts[1]))
            except ValueError:
                return None
    return None


def slot_start_has_arrived(tournament: Tournament, slot: ScheduleSlot) -> bool:
    slot_time = _coerce_slot_start_time(slot.start_time)
    if slot_time is None:
        return False
    tz_name = (tournament.timezone or "UTC").strip() or "UTC"
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = ZoneInfo("UTC")
    now_local = datetime.now(tz)
    slot_local = datetime.combine(slot.day_date, slot_time, tzinfo=tz)
    return slot_local <= now_local


def _format_time_label(start_time: object) -> str:
    coerced = _coerce_slot_start_time(start_time)
    if coerced is None:
        return ""
    h12 = (coerced.hour % 12) or 12
    ampm = "AM" if coerced.hour < 12 else "PM"
    return f"{h12}:{coerced.minute:02d} {ampm}"


def _side_ready(
    session: Session,
    *,
    version_id: int,
    match_id: int,
    side: str,
    team_id: Optional[int],
) -> bool:
    side_key = side.upper()
    team_row = session.exec(
        select(MatchCheckIn).where(
            MatchCheckIn.schedule_version_id == version_id,
            MatchCheckIn.match_id == match_id,
            MatchCheckIn.side == side_key,
        )
    ).first()
    if team_row and team_row.team_checked_in:
        return True
    if team_id is None:
        return False
    player_ids = [
        row.player_id
        for row in session.exec(
            select(TeamPlayer).where(TeamPlayer.team_id == team_id).order_by(TeamPlayer.lineup_slot, TeamPlayer.id)
        ).all()
    ]
    if not player_ids:
        return False
    checked = 0
    for pid in player_ids:
        row = session.exec(
            select(MatchPlayerCheckIn).where(
                MatchPlayerCheckIn.schedule_version_id == version_id,
                MatchPlayerCheckIn.match_id == match_id,
                MatchPlayerCheckIn.side == side_key,
                MatchPlayerCheckIn.player_id == pid,
            )
        ).first()
        if row and row.checked_in:
            checked += 1
    return checked == len(player_ids)


def match_fully_checked_in(session: Session, match: Match) -> bool:
    if match.id is None or match.schedule_version_id is None:
        return False
    if match.team_a_id is None or match.team_b_id is None:
        return False
    return _side_ready(
        session,
        version_id=match.schedule_version_id,
        match_id=match.id,
        side="A",
        team_id=match.team_a_id,
    ) and _side_ready(
        session,
        version_id=match.schedule_version_id,
        match_id=match.id,
        side="B",
        team_id=match.team_b_id,
    )


def _feeders_final(session: Session, match: Match) -> bool:
    for source_id in (match.source_match_a_id, match.source_match_b_id):
        if source_id is None:
            continue
        source = session.get(Match, source_id)
        if source is None:
            return False
        if (source.runtime_status or "SCHEDULED").upper() != "FINAL":
            return False
    return True


def _slot_released(
    session: Session,
    *,
    version_id: int,
    day_date: date,
    slot_key: str,
) -> bool:
    row = session.exec(
        select(OpeningSlotRelease).where(
            OpeningSlotRelease.schedule_version_id == version_id,
            OpeningSlotRelease.day_date == day_date,
            OpeningSlotRelease.slot_key == slot_key,
        )
    ).first()
    return row is not None


def _closed_court_labels(session: Session, tournament_id: int) -> Set[str]:
    rows = session.exec(
        select(TournamentCourtState).where(
            TournamentCourtState.tournament_id == tournament_id,
            TournamentCourtState.is_closed == True,  # noqa: E712
        )
    ).all()
    closed: Set[str] = set()
    for row in rows:
        label = (row.court_label or "").strip()
        if not label:
            continue
        closed.add(label if label.lower().startswith("court") else f"Court {label}")
    return closed


def live_occupant_on_court(
    session: Session,
    *,
    version_id: int,
    day_date: date,
    court_number: int,
    ignore_match_id: Optional[int] = None,
) -> Optional[Match]:
    for match in _ordered_matches_for_court(
        session,
        version_id=version_id,
        day_date=day_date,
        court_number=court_number,
    ):
        if ignore_match_id is not None and match.id == ignore_match_id:
            continue
        if (match.runtime_status or "SCHEDULED").upper() in LIVE_STATUSES:
            return match
    return None


def _ordered_matches_for_court(
    session: Session,
    *,
    version_id: int,
    day_date: date,
    court_number: int,
) -> List[Match]:
    slots = session.exec(
        select(ScheduleSlot)
        .where(
            ScheduleSlot.schedule_version_id == version_id,
            ScheduleSlot.day_date == day_date,
            ScheduleSlot.court_number == court_number,
        )
        .order_by(ScheduleSlot.start_time, ScheduleSlot.id)
    ).all()
    ordered: List[Match] = []
    for slot in slots:
        assignment = session.exec(
            select(MatchAssignment).where(
                MatchAssignment.schedule_version_id == version_id,
                MatchAssignment.slot_id == slot.id,
            )
        ).first()
        if assignment is None:
            continue
        match = session.get(Match, assignment.match_id)
        if match is not None:
            ordered.append(match)
    return ordered


def prior_blocking_match_on_court(
    session: Session,
    *,
    version_id: int,
    day_date: date,
    court_number: int,
    match_id: int,
) -> Optional[Match]:
    """Earlier non-FINAL match on this court blocks a later automatic start."""
    for match in _ordered_matches_for_court(
        session,
        version_id=version_id,
        day_date=day_date,
        court_number=court_number,
    ):
        if match.id == match_id:
            return None
        status = (match.runtime_status or "SCHEDULED").upper()
        if status == "FINAL":
            continue
        return match
    return None


def _reclaim_stale_court_lock(
    session: Session,
    *,
    version_id: int,
    day_date: date,
    court_number: int,
) -> bool:
    """Delete a committed orphan lock older than TTL. Returns True if deleted."""
    row = session.exec(
        select(CourtDispatchLock).where(
            CourtDispatchLock.schedule_version_id == version_id,
            CourtDispatchLock.day_date == day_date,
            CourtDispatchLock.court_number == court_number,
        )
    ).first()
    if row is None or row.created_at is None:
        return False
    age = (datetime.utcnow() - row.created_at).total_seconds()
    if age < _LOCK_STALE_SECONDS:
        return False
    logger.warning(
        "Reclaiming stale court dispatch lock v=%s day=%s court=%s age=%.1fs holder=%s",
        version_id,
        day_date,
        court_number,
        age,
        row.holder,
    )
    session.delete(row)
    session.flush()
    return True


def _try_acquire_court_lock(
    session: Session,
    *,
    version_id: int,
    day_date: date,
    court_number: int,
    holder: str,
) -> bool:
    """Insert mutex row in a savepoint. Row stays in the outer transaction until commit.

    Concurrent acquirers hit the unique constraint (PostgreSQL blocks until the
    holder commits/rolls back; SQLite reports IntegrityError or waits on the
    busy timeout then may raise OperationalError database is locked). Crash
    before the outer commit rolls the lock insert back — no durable stuck row.
    """
    nested = session.begin_nested()
    try:
        session.add(
            CourtDispatchLock(
                schedule_version_id=version_id,
                day_date=day_date,
                court_number=court_number,
                holder=holder,
                created_at=datetime.utcnow(),
            )
        )
        session.flush()
        nested.commit()
        return True
    except IntegrityError:
        nested.rollback()
        # Opportunistically clear committed orphans from a prior crash path.
        try:
            if _reclaim_stale_court_lock(
                session,
                version_id=version_id,
                day_date=day_date,
                court_number=court_number,
            ):
                return _try_acquire_court_lock(
                    session,
                    version_id=version_id,
                    day_date=day_date,
                    court_number=court_number,
                    holder=holder,
                )
        except Exception:
            logger.exception(
                "Stale court lock reclaim failed v=%s day=%s court=%s",
                version_id,
                day_date,
                court_number,
            )
        return False
    except OperationalError as exc:
        nested.rollback()
        if _is_sqlite_locked(exc):
            return False
        raise


def _release_court_lock(
    session: Session,
    *,
    version_id: int,
    day_date: date,
    court_number: int,
    holder: str,
) -> None:
    row = session.exec(
        select(CourtDispatchLock).where(
            CourtDispatchLock.schedule_version_id == version_id,
            CourtDispatchLock.day_date == day_date,
            CourtDispatchLock.court_number == court_number,
            CourtDispatchLock.holder == holder,
        )
    ).first()
    if row is not None:
        session.delete(row)
        session.flush()


@contextmanager
def court_dispatch_lock(
    session: Session,
    *,
    version_id: int,
    day_date: date,
    court_number: int,
) -> Iterator[bool]:
    """DB-backed mutex for one court/day/version. Yields True if acquired.

    Lifecycle: acquire (INSERT in outer txn) → critical section (flush only) →
    release (DELETE) → caller commits start+release together. SMS must run only
    after that commit. If release fails, the error propagates so the caller must
    not commit a durable orphan lock row.

    On SQLite, writer contention surfaces as OperationalError("database is locked")
    in addition to unique-constraint IntegrityError; both are treated as
    non-acquired so the caller can retry after re-reading eligibility.
    """
    holder = f"dispatch-{uuid.uuid4().hex[:12]}"
    acquired = False
    for attempt in range(_LOCK_ACQUIRE_ATTEMPTS):
        try:
            if _try_acquire_court_lock(
                session,
                version_id=version_id,
                day_date=day_date,
                court_number=court_number,
                holder=holder,
            ):
                acquired = True
                break
        except OperationalError as exc:
            if not _is_sqlite_locked(exc):
                raise
        time_module.sleep(_LOCK_ACQUIRE_SLEEP_SEC * (attempt + 1))
    release_error: Optional[BaseException] = None
    try:
        yield acquired
    except Exception:
        # Roll back lock insert + any partial IN_PROGRESS flush together.
        if acquired:
            try:
                session.rollback()
            except Exception:
                logger.exception(
                    "rollback after court dispatch critical-section failure v=%s day=%s court=%s",
                    version_id,
                    day_date,
                    court_number,
                )
            acquired = False
        raise
    finally:
        if acquired:
            try:
                _release_court_lock(
                    session,
                    version_id=version_id,
                    day_date=day_date,
                    court_number=court_number,
                    holder=holder,
                )
            except OperationalError as exc:
                if _is_sqlite_locked(exc):
                    release_error = exc
                    logger.warning(
                        "SQLite locked while releasing court dispatch lock v=%s day=%s court=%s",
                        version_id,
                        day_date,
                        court_number,
                    )
                else:
                    release_error = exc
                    logger.exception(
                        "Failed to release court dispatch lock v=%s day=%s court=%s",
                        version_id,
                        day_date,
                        court_number,
                    )
            except BaseException as exc:
                release_error = exc
                logger.exception(
                    "Failed to release court dispatch lock v=%s day=%s court=%s",
                    version_id,
                    day_date,
                    court_number,
                )
    if release_error is not None:
        try:
            session.rollback()
        except Exception:
            logger.exception("rollback after court dispatch lock release failure")
        # Prevent committing a durable orphan mutex row with a match start.
        raise RuntimeError(f"court dispatch lock release failed for court {court_number}") from release_error


def evaluate_eligibility(
    session: Session,
    tournament: Tournament,
    match: Match,
) -> EligibilityResult:
    """Re-read mode and state at call time. Safe for concurrent retries."""
    mid = match.id or 0
    status = (match.runtime_status or "SCHEDULED").upper()
    if status in DONE_OR_LIVE:
        return EligibilityResult(mid, OUTCOME_SKIP, f"Match already {status}")

    if (match.match_type or "").upper() != "WF":
        return EligibilityResult(mid, OUTCOME_SKIP, "Not a waterfall match")

    assignment = session.exec(
        select(MatchAssignment).where(
            MatchAssignment.schedule_version_id == match.schedule_version_id,
            MatchAssignment.match_id == match.id,
        )
    ).first()
    if assignment is None:
        return EligibilityResult(mid, OUTCOME_SKIP, "Match has no assignment")
    slot = session.get(ScheduleSlot, assignment.slot_id)
    if slot is None:
        return EligibilityResult(mid, OUTCOME_SKIP, "Assigned slot missing")

    event = session.get(Event, match.event_id) if match.event_id else None
    # Mode must be re-read at execution time — never cache across requests.
    if not is_preassigned(event, slot.day_date):
        return EligibilityResult(mid, OUTCOME_SKIP, "Event/date is DYNAMIC_CHECKIN")

    court_name = court_display_for_slot(slot)
    key = slot_key_for_slot(slot)
    opening = is_opening_waterfall(match)

    if match.team_a_id is None or match.team_b_id is None:
        return EligibilityResult(
            mid,
            OUTCOME_WAITING_PARTICIPANTS,
            "Both participants must be known",
            court_name=court_name,
            scheduled_time=_format_time_label(slot.start_time),
            day_date=slot.day_date,
            slot_key=key,
            is_opening=opening,
        )

    if is_subsequent_waterfall(match) and not _feeders_final(session, match):
        return EligibilityResult(
            mid,
            OUTCOME_WAITING_PARTICIPANTS,
            "Feeder matches are not all FINAL",
            court_name=court_name,
            scheduled_time=_format_time_label(slot.start_time),
            day_date=slot.day_date,
            slot_key=key,
            is_opening=False,
        )

    if opening:
        if not match_fully_checked_in(session, match):
            return EligibilityResult(
                mid,
                OUTCOME_WAITING_CHECKIN,
                "Opening match requires both teams checked in",
                court_name=court_name,
                scheduled_time=_format_time_label(slot.start_time),
                day_date=slot.day_date,
                slot_key=key,
                is_opening=True,
            )
        if not _slot_released(
            session,
            version_id=match.schedule_version_id,
            day_date=slot.day_date,
            slot_key=key,
        ):
            return EligibilityResult(
                mid,
                OUTCOME_WAITING_RELEASE,
                "Opening slot has not been released by staff",
                court_name=court_name,
                scheduled_time=_format_time_label(slot.start_time),
                day_date=slot.day_date,
                slot_key=key,
                is_opening=True,
            )
        # Opening release authorizes early start for this slot.
        time_ok = True
    else:
        time_ok = slot_start_has_arrived(tournament, slot)

    if not time_ok:
        return EligibilityResult(
            mid,
            OUTCOME_WAITING_TIME,
            "Scheduled start time has not arrived",
            court_name=court_name,
            scheduled_time=_format_time_label(slot.start_time),
            day_date=slot.day_date,
            slot_key=key,
            is_opening=opening,
        )

    closed = _closed_court_labels(session, tournament.id or 0)
    if court_name in closed:
        return EligibilityResult(
            mid,
            OUTCOME_WAITING_COURT,
            f"{court_name} is closed",
            court_name=court_name,
            scheduled_time=_format_time_label(slot.start_time),
            day_date=slot.day_date,
            slot_key=key,
            is_opening=opening,
        )

    prior = prior_blocking_match_on_court(
        session,
        version_id=match.schedule_version_id,  # type: ignore[arg-type]
        day_date=slot.day_date,
        court_number=slot.court_number,
        match_id=mid,
    )
    if prior is not None:
        prior_status = (prior.runtime_status or "SCHEDULED").upper()
        if prior_status in LIVE_STATUSES:
            return EligibilityResult(
                mid,
                OUTCOME_WAITING_COURT,
                f"{court_name} is occupied by match {prior.id}",
                court_name=court_name,
                scheduled_time=_format_time_label(slot.start_time),
                day_date=slot.day_date,
                slot_key=key,
                is_opening=opening,
                occupying_match_id=prior.id,
            )
        return EligibilityResult(
            mid,
            OUTCOME_WAITING_PRIOR,
            f"Earlier match {prior.id} on {court_name} must clear first",
            court_name=court_name,
            scheduled_time=_format_time_label(slot.start_time),
            day_date=slot.day_date,
            slot_key=key,
            is_opening=opening,
            occupying_match_id=prior.id,
        )

    occupant = live_occupant_on_court(
        session,
        version_id=match.schedule_version_id,
        day_date=slot.day_date,
        court_number=slot.court_number,
        ignore_match_id=match.id,
    )
    if occupant is not None:
        return EligibilityResult(
            mid,
            OUTCOME_WAITING_COURT,
            f"{court_name} is occupied by match {occupant.id}",
            court_name=court_name,
            scheduled_time=_format_time_label(slot.start_time),
            day_date=slot.day_date,
            slot_key=key,
            is_opening=opening,
            occupying_match_id=occupant.id,
        )

    return EligibilityResult(
        mid,
        OUTCOME_READY_TO_START,
        "Eligible to start",
        court_name=court_name,
        scheduled_time=_format_time_label(slot.start_time),
        day_date=slot.day_date,
        slot_key=key,
        is_opening=opening,
    )


def _assignment_slot(session: Session, match: Match) -> Optional[ScheduleSlot]:
    if match.schedule_version_id is None or match.id is None:
        return None
    assignment = session.exec(
        select(MatchAssignment).where(
            MatchAssignment.schedule_version_id == match.schedule_version_id,
            MatchAssignment.match_id == match.id,
        )
    ).first()
    if assignment is None:
        return None
    return session.get(ScheduleSlot, assignment.slot_id)


def _apply_in_progress(session: Session, match: Match) -> None:
    match.runtime_status = "IN_PROGRESS"
    if match.started_at is None:
        match.started_at = datetime.utcnow()
    match.completed_at = None
    session.add(match)
    session.flush()


def _send_start_sms(
    session: Session,
    tournament: Tournament,
    match: Match,
    previous_status: str,
) -> None:
    try:
        automation = SmsAutomationEngine(session, tournament, match.schedule_version_id)
        # Intentionally does NOT call handle_checkin_court_assigned —
        # preassigned courts were already communicated / reserved.
        automation.handle_match_status_change(
            match=match,
            previous_status=previous_status,
            new_status="IN_PROGRESS",
        )
    except Exception:
        logger.exception(
            "SMS automation failed after preassigned start tournament=%s match=%s",
            tournament.id,
            match.id,
        )


def start_match_canonical(
    session: Session,
    tournament: Tournament,
    match: Match,
    *,
    commit: bool = True,
    send_sms: bool = True,
    _court_lock_held: bool = False,
) -> Tuple[bool, str]:
    """Canonical IN_PROGRESS transition + SMS status change.

    Serializes per court via CourtDispatchLock so two different matches cannot
    both observe the court as free and both become IN_PROGRESS.
    """
    schema_err = _require_schema_ready(session)
    if schema_err:
        return False, schema_err

    session.refresh(match)
    previous = (match.runtime_status or "SCHEDULED").upper()
    if previous == "IN_PROGRESS":
        return False, "already_in_progress"
    if previous == "FINAL":
        return False, "already_final"
    if previous == "PAUSED":
        return False, "paused"

    slot = _assignment_slot(session, match)
    if slot is None or match.schedule_version_id is None:
        return False, "Assigned slot missing"

    def _perform_start() -> Tuple[bool, str]:
        # Always re-read after the effective DB lock is held.
        session.refresh(match)
        prev = (match.runtime_status or "SCHEDULED").upper()
        if prev == "IN_PROGRESS":
            return False, "already_in_progress"
        if prev in ("FINAL", "PAUSED"):
            return False, prev.lower()

        eligibility = evaluate_eligibility(session, tournament, match)
        if eligibility.outcome != OUTCOME_READY_TO_START:
            return False, eligibility.reason

        if (match.runtime_status or "SCHEDULED").upper() in DONE_OR_LIVE:
            return False, f"Match already {(match.runtime_status or '').upper()}"

        _apply_in_progress(session, match)
        return True, "started"

    # Nested call under an already-held court lock: no acquire/retry here.
    # Parent dispatch owns contention handling and the outer commit.
    if _court_lock_held:
        started, detail = _perform_start()
        if not started:
            return False, detail
        if commit:
            session.commit()
            session.refresh(match)
            if send_sms:
                _send_start_sms(session, tournament, match, previous)
        else:
            session.flush()
        return True, "started"

    last_detail = COURT_LOCK_BUSY
    for attempt in range(_DISPATCH_BUSY_ATTEMPTS):
        started = False
        detail = COURT_LOCK_BUSY
        try:
            with court_dispatch_lock(
                session,
                version_id=match.schedule_version_id,
                day_date=slot.day_date,
                court_number=slot.court_number,
            ) as acquired:
                if not acquired:
                    last_detail = COURT_LOCK_BUSY
                    time_module.sleep(_DISPATCH_BUSY_SLEEP_SEC * (attempt + 1))
                    continue
                started, detail = _perform_start()

            # Persist start (if any) and lock-row deletion together.
            if commit:
                session.commit()
                if started:
                    session.refresh(match)
            elif started:
                session.flush()

            if not started:
                return False, detail

            if send_sms and commit:
                _send_start_sms(session, tournament, match, previous)
            return True, "started"
        except OperationalError as exc:
            if not _is_sqlite_locked(exc):
                raise
            try:
                session.rollback()
            except Exception:
                logger.exception("rollback after SQLite lock during start_match_canonical")
            last_detail = COURT_LOCK_BUSY
            time_module.sleep(_DISPATCH_BUSY_SLEEP_SEC * (attempt + 1))
        except Exception:
            # Never leave a flushed-but-uncommitted IN_PROGRESS after failure.
            try:
                session.rollback()
            except Exception:
                logger.exception("rollback after start_match_canonical failure")
            raise

    return False, last_detail


def _dispatch_court_once(
    session: Session,
    tournament: Tournament,
    *,
    version_id: int,
    day_date: date,
    court_number: int,
) -> DispatchResult:
    """Single attempt: acquire court mutex, re-evaluate order, start earliest ready."""
    result = DispatchResult()
    started_match: Optional[Match] = None
    previous_status = "SCHEDULED"
    try:
        with court_dispatch_lock(
            session,
            version_id=version_id,
            day_date=day_date,
            court_number=court_number,
        ) as acquired:
            if not acquired:
                result.errors.append(COURT_LOCK_BUSY)
                return result

            for match in _ordered_matches_for_court(
                session,
                version_id=version_id,
                day_date=day_date,
                court_number=court_number,
            ):
                session.refresh(match)
                # Re-check mode / occupancy / reservation priority under the lock.
                eligibility = evaluate_eligibility(session, tournament, match)
                if eligibility.outcome == OUTCOME_READY_TO_START:
                    previous_status = (match.runtime_status or "SCHEDULED").upper()
                    started, detail = start_match_canonical(
                        session,
                        tournament,
                        match,
                        commit=False,
                        send_sms=False,
                        _court_lock_held=True,
                    )
                    if started and match.id is not None:
                        result.started_match_ids.append(match.id)
                        started_match = match
                    else:
                        result.errors.append(f"Match {match.id}: {detail}")
                    break
                if (
                    eligibility.outcome
                    in (
                        OUTCOME_WAITING_COURT,
                        OUTCOME_WAITING_PRIOR,
                    )
                    and match.id is not None
                ):
                    result.waiting_match_ids.append(match.id)
                    result.skipped.append(eligibility)
                    break
                result.skipped.append(eligibility)
                if eligibility.outcome in (
                    OUTCOME_WAITING_CHECKIN,
                    OUTCOME_WAITING_RELEASE,
                    OUTCOME_WAITING_TIME,
                    OUTCOME_WAITING_PARTICIPANTS,
                ):
                    if (match.runtime_status or "SCHEDULED").upper() == "SCHEDULED":
                        break

        # Persist start + lock release together after the mutex row is deleted.
        session.commit()
    except OperationalError as exc:
        if not _is_sqlite_locked(exc):
            raise
        try:
            session.rollback()
        except Exception:
            logger.exception("rollback after SQLite lock in _dispatch_court_once")
        result.errors.append(COURT_LOCK_BUSY)
        return result

    if started_match is not None:
        session.refresh(started_match)
        _send_start_sms(session, tournament, started_match, previous_status)
    return result


def dispatch_court(
    session: Session,
    tournament: Tournament,
    *,
    version_id: int,
    day_date: date,
    court_number: int,
) -> DispatchResult:
    """Start the earliest eligible PREASSIGNED match on this court, if any."""
    result = DispatchResult()
    schema_err = _require_schema_ready(session)
    if schema_err:
        result.errors.append(schema_err)
        return result

    for attempt in range(_DISPATCH_BUSY_ATTEMPTS):
        try:
            once = _dispatch_court_once(
                session,
                tournament,
                version_id=version_id,
                day_date=day_date,
                court_number=court_number,
            )
            if once.errors == [COURT_LOCK_BUSY] and not once.started_match_ids:
                time_module.sleep(_DISPATCH_BUSY_SLEEP_SEC * (attempt + 1))
                continue
            return once
        except OperationalError as exc:
            if not _is_sqlite_locked(exc):
                raise
            try:
                session.rollback()
            except Exception:
                logger.exception("rollback after SQLite lock during dispatch_court")
            time_module.sleep(_DISPATCH_BUSY_SLEEP_SEC * (attempt + 1))
        except Exception:
            try:
                session.rollback()
            except Exception:
                logger.exception("rollback after dispatch_court failure")
            raise

    result.errors.append(COURT_LOCK_BUSY)
    return result


def reevaluate_match(
    session: Session,
    tournament: Tournament,
    match: Match,
) -> DispatchResult:
    """Always dispatch through court order — never jump an earlier reservation."""
    slot = _assignment_slot(session, match)
    if slot is None or match.schedule_version_id is None:
        result = DispatchResult()
        result.errors.append("Assigned slot missing")
        return result
    return dispatch_court(
        session,
        tournament,
        version_id=match.schedule_version_id,
        day_date=slot.day_date,
        court_number=slot.court_number,
    )


def dispatch_after_court_freed(
    session: Session,
    tournament: Tournament,
    *,
    version_id: int,
    day_date: date,
    court_number: int,
) -> DispatchResult:
    return dispatch_court(
        session,
        tournament,
        version_id=version_id,
        day_date=day_date,
        court_number=court_number,
    )


def dispatch_after_finalize(
    session: Session,
    tournament: Tournament,
    finalized_match: Match,
    *,
    downstream_match_ids: Optional[Sequence[int]] = None,
) -> DispatchResult:
    """Court freed + Round-2 readiness after a finalized score.

    Callers must already have committed the FINAL result and advancement.
    Failures here are reported in the result and must not roll back the score.
    """
    aggregate = DispatchResult()
    try:
        assignment = session.exec(
            select(MatchAssignment).where(
                MatchAssignment.schedule_version_id == finalized_match.schedule_version_id,
                MatchAssignment.match_id == finalized_match.id,
            )
        ).first()
        if assignment is not None:
            slot = session.get(ScheduleSlot, assignment.slot_id)
            if slot is not None and finalized_match.schedule_version_id is not None:
                part = dispatch_after_court_freed(
                    session,
                    tournament,
                    version_id=finalized_match.schedule_version_id,
                    day_date=slot.day_date,
                    court_number=slot.court_number,
                )
                aggregate.started_match_ids.extend(part.started_match_ids)
                aggregate.waiting_match_ids.extend(part.waiting_match_ids)
                aggregate.skipped.extend(part.skipped)
                aggregate.errors.extend(part.errors)

        for mid in downstream_match_ids or ():
            if mid in aggregate.started_match_ids:
                continue
            downstream = session.get(Match, mid)
            if downstream is None:
                continue
            part = reevaluate_match(session, tournament, downstream)
            aggregate.started_match_ids.extend(part.started_match_ids)
            aggregate.waiting_match_ids.extend(part.waiting_match_ids)
            aggregate.skipped.extend(part.skipped)
            aggregate.errors.extend(part.errors)
    except Exception as exc:
        logger.exception(
            "preassigned dispatch_after_finalize failed tournament=%s match=%s",
            tournament.id,
            finalized_match.id,
        )
        aggregate.errors.append(str(exc))
    return aggregate


def preview_opening_release(
    session: Session,
    tournament: Tournament,
    version: ScheduleVersion,
    *,
    day_date: date,
    slot_key: str,
) -> OpeningReleasePreview:
    slots = session.exec(
        select(ScheduleSlot).where(
            ScheduleSlot.schedule_version_id == version.id,
            ScheduleSlot.day_date == day_date,
        )
    ).all()
    slot_ids = [s.id for s in slots if slot_key_for_slot(s) == slot_key]
    time_label = ""
    if slot_ids:
        sample = session.get(ScheduleSlot, slot_ids[0])
        if sample is not None:
            time_label = _format_time_label(sample.start_time)

    assignments = (
        session.exec(
            select(MatchAssignment).where(
                MatchAssignment.schedule_version_id == version.id,
                MatchAssignment.slot_id.in_(slot_ids),  # type: ignore[arg-type]
            )
        ).all()
        if slot_ids
        else []
    )

    ready_ids: List[int] = []
    awaiting_ids: List[int] = []
    available = 0
    occupied = 0
    by_event: Dict[int, OpeningReleaseEventSummary] = {}
    for assignment in assignments:
        match = session.get(Match, assignment.match_id)
        slot = session.get(ScheduleSlot, assignment.slot_id)
        if match is None or slot is None:
            continue
        if not is_opening_waterfall(match):
            continue
        event = session.get(Event, match.event_id) if match.event_id else None
        if not is_preassigned(event, slot.day_date):
            continue
        status = (match.runtime_status or "SCHEDULED").upper()
        if status in DONE_OR_LIVE:
            continue
        event_id = event.id if event and event.id is not None else 0
        summary = by_event.get(event_id)
        if summary is None:
            summary = OpeningReleaseEventSummary(
                event_id=event_id,
                event_name=(event.name if event else "Unknown"),
                ready_count=0,
                awaiting_checkin_count=0,
            )
            by_event[event_id] = summary
        if match.id is not None:
            summary.match_ids.append(match.id)
        if match_fully_checked_in(session, match):
            ready_ids.append(match.id)  # type: ignore[arg-type]
            summary.ready_count += 1
            occupant = live_occupant_on_court(
                session,
                version_id=version.id,
                day_date=slot.day_date,
                court_number=slot.court_number,
                ignore_match_id=match.id,
            )
            if occupant is None:
                available += 1
            else:
                occupied += 1
        else:
            awaiting_ids.append(match.id)  # type: ignore[arg-type]
            summary.awaiting_checkin_count += 1

    event_rows = sorted(by_event.values(), key=lambda row: (row.event_name, row.event_id))
    return OpeningReleasePreview(
        slot_key=slot_key,
        day_date=day_date,
        scheduled_time_label=time_label,
        scheduled_count=len(ready_ids) + len(awaiting_ids),
        ready_count=len(ready_ids),
        awaiting_checkin_count=len(awaiting_ids),
        courts_available_count=available,
        courts_occupied_count=occupied,
        already_released=_slot_released(session, version_id=version.id, day_date=day_date, slot_key=slot_key),
        ready_match_ids=ready_ids,
        awaiting_checkin_match_ids=awaiting_ids,
        events=event_rows,
    )


def release_opening_slot(
    session: Session,
    tournament: Tournament,
    version: ScheduleVersion,
    *,
    day_date: date,
    slot_key: str,
    released_by: Optional[str] = None,
) -> Tuple[OpeningSlotRelease, DispatchResult]:
    """Persist release authorization (idempotent) and dispatch ready matches."""
    schema_err = _require_schema_ready(session)
    if schema_err:
        raise PreassignedSchemaNotReady(schema_err)

    existing = session.exec(
        select(OpeningSlotRelease).where(
            OpeningSlotRelease.schedule_version_id == version.id,
            OpeningSlotRelease.day_date == day_date,
            OpeningSlotRelease.slot_key == slot_key,
        )
    ).first()
    if existing is None:
        existing = OpeningSlotRelease(
            tournament_id=tournament.id,  # type: ignore[arg-type]
            schedule_version_id=version.id,  # type: ignore[arg-type]
            day_date=day_date,
            slot_key=slot_key,
            released_at=datetime.utcnow(),
            released_by=released_by,
        )
        session.add(existing)
        session.commit()
        session.refresh(existing)
    else:
        # Idempotent: still re-dispatch in case courts freed / late check-ins.
        session.commit()

    preview = preview_opening_release(session, tournament, version, day_date=day_date, slot_key=slot_key)
    aggregate = DispatchResult()
    # Dispatch ready matches court-by-court in schedule order.
    court_seen: Set[int] = set()
    for match_id in preview.ready_match_ids:
        match = session.get(Match, match_id)
        if match is None:
            continue
        assignment = session.exec(
            select(MatchAssignment).where(
                MatchAssignment.schedule_version_id == version.id,
                MatchAssignment.match_id == match_id,
            )
        ).first()
        if assignment is None:
            continue
        slot = session.get(ScheduleSlot, assignment.slot_id)
        if slot is None:
            continue
        if slot.court_number in court_seen:
            # Already attempted this court in this release pass.
            eligibility = evaluate_eligibility(session, tournament, match)
            if eligibility.outcome == OUTCOME_WAITING_COURT:
                aggregate.waiting_match_ids.append(match_id)
            aggregate.skipped.append(eligibility)
            continue
        court_seen.add(slot.court_number)
        part = dispatch_court(
            session,
            tournament,
            version_id=version.id,  # type: ignore[arg-type]
            day_date=day_date,
            court_number=slot.court_number,
        )
        aggregate.started_match_ids.extend(part.started_match_ids)
        aggregate.waiting_match_ids.extend(part.waiting_match_ids)
        aggregate.skipped.extend(part.skipped)
        aggregate.errors.extend(part.errors)
    return existing, aggregate


def list_ready_assigned_matches(
    session: Session,
    tournament: Tournament,
    version: ScheduleVersion,
) -> List[EligibilityResult]:
    """PREASSIGNED WF matches waiting on court/time after check-in/release or R2 readiness."""
    matches = session.exec(select(Match).where(Match.schedule_version_id == version.id)).all()
    ready: List[EligibilityResult] = []
    for match in matches:
        if (match.match_type or "").upper() != "WF":
            continue
        if (match.runtime_status or "SCHEDULED").upper() in DONE_OR_LIVE:
            continue
        assignment = session.exec(
            select(MatchAssignment).where(
                MatchAssignment.schedule_version_id == version.id,
                MatchAssignment.match_id == match.id,
            )
        ).first()
        if assignment is None:
            continue
        slot = session.get(ScheduleSlot, assignment.slot_id)
        if slot is None:
            continue
        event = session.get(Event, match.event_id) if match.event_id else None
        if not is_preassigned(event, slot.day_date):
            continue

        if is_opening_waterfall(match):
            if not match_fully_checked_in(session, match):
                continue
        elif is_subsequent_waterfall(match):
            if match.team_a_id is None or match.team_b_id is None:
                continue
            if not _feeders_final(session, match):
                continue
        else:
            continue

        eligibility = evaluate_eligibility(session, tournament, match)
        if eligibility.outcome in (
            OUTCOME_WAITING_COURT,
            OUTCOME_WAITING_TIME,
            OUTCOME_WAITING_RELEASE,
            OUTCOME_WAITING_PRIOR,
            OUTCOME_READY_TO_START,
        ):
            ready.append(eligibility)
    ready.sort(
        key=lambda row: (
            row.day_date.isoformat() if row.day_date else "",
            row.slot_key or "",
            row.match_id,
        )
    )
    return ready
