"""
Reschedule Engine — compute and apply match rescheduling for rain delays,
court loss, and day washouts.  Also: full schedule rebuild for remaining
matches after washouts.

Modes:
  PARTIAL_DAY  — courts lost for a time window on a specific day
  FULL_WASHOUT — entire day lost (replaced by REBUILD in UI)
  COURT_LOSS   — specific courts become unavailable
  REBUILD      — regenerate schedule from scratch for all remaining matches
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any, Dict, List, Optional, Set, Tuple

from sqlalchemy import case
from sqlmodel import Session, select

from app.models.event import Event
from app.models.match import Match
from app.models.match_assignment import MatchAssignment
from app.models.schedule_slot import ScheduleSlot
from app.models.schedule_version import ScheduleVersion
from app.models.tournament import Tournament
from app.utils.courts import court_label_for_index

DAILY_CAP = 2
MIN_REST_MINUTES = 45

SCORING_FORMATS = {
    "REGULAR": 105,
    "PRO_SET_8": 60,
    "PRO_SET_4": 35,
}

SCORING_FORMAT_LABELS = {
    "REGULAR": "Regular (1:45)",
    "PRO_SET_8": "8-Game Pro Set (1:00)",
    "PRO_SET_4": "4-Game Pro Set (0:35)",
}


@dataclass
class RescheduleParams:
    version_id: int
    mode: str  # PARTIAL_DAY | FULL_WASHOUT | COURT_LOSS
    affected_day: date
    unavailable_from: Optional[time] = None  # PARTIAL_DAY
    available_from: Optional[time] = None    # PARTIAL_DAY: when courts reopen
    unavailable_courts: Optional[List[int]] = None  # COURT_LOSS
    target_days: Optional[List[date]] = None  # FULL_WASHOUT overflow
    extend_day_end: Optional[time] = None
    add_time_slots: bool = True
    block_minutes: int = 60
    scoring_format: Optional[str] = None  # REGULAR | PRO_SET_8 | PRO_SET_4


@dataclass
class ProposedMove:
    match_id: int
    match_number: int
    match_code: str
    event_name: str
    stage: str
    old_slot_id: Optional[int]
    old_court: Optional[str]
    old_time: Optional[str]
    old_day: Optional[str]
    new_slot_id: int
    new_court: str
    new_time: str
    new_day: str


@dataclass
class UnplaceableMatch:
    match_id: int
    match_number: int
    match_code: str
    event_name: str
    stage: str
    reason: str


@dataclass
class ReschedulePreview:
    proposed_moves: List[ProposedMove]
    unplaceable: List[UnplaceableMatch]
    new_slots_created: int
    stats: Dict[str, int]
    created_slot_ids: List[int] = field(default_factory=list)
    format_applied: Optional[str] = None
    duration_updates: Dict[int, int] = field(default_factory=dict)  # match_id -> new duration


def _time_str(t) -> str:
    if t is None:
        return ""
    if isinstance(t, str):
        return t[:5]
    return t.strftime("%H:%M")


def _day_str(d) -> str:
    if d is None:
        return ""
    if isinstance(d, str):
        return d
    return d.isoformat()


def _slot_is_affected(
    slot: ScheduleSlot,
    params: RescheduleParams,
) -> bool:
    """Return True if this slot falls within the affected zone."""
    if params.mode == "FULL_WASHOUT":
        return slot.day_date == params.affected_day

    if params.mode == "PARTIAL_DAY":
        if slot.day_date != params.affected_day:
            return False
        if params.unavailable_from and slot.start_time >= params.unavailable_from:
            if params.available_from:
                return slot.start_time < params.available_from
            return True
        return False

    if params.mode == "COURT_LOSS":
        courts = params.unavailable_courts or []
        return slot.day_date == params.affected_day and slot.court_number in courts

    return False


@dataclass
class FormatFeasibility:
    format: str
    duration: int
    label: str
    fits: bool
    utilization: int  # percentage


@dataclass
class FeasibilityResult:
    affected_count: int
    formats: List[FormatFeasibility]


def compute_feasibility(
    session: Session,
    tournament_id: int,
    params: RescheduleParams,
) -> FeasibilityResult:
    """Compute feasibility for each scoring format without mutating anything."""
    all_matches = session.exec(
        select(Match).where(Match.schedule_version_id == params.version_id)
    ).all()

    all_assignments = session.exec(
        select(MatchAssignment).where(
            MatchAssignment.schedule_version_id == params.version_id,
        )
    ).all()

    all_slots = session.exec(
        select(ScheduleSlot).where(
            ScheduleSlot.schedule_version_id == params.version_id,
            ScheduleSlot.is_active == True,
        )
    ).all()

    assign_by_match = {a.match_id: a for a in all_assignments}
    slot_map = {s.id: s for s in all_slots}

    # Count affected (unplayed) matches
    affected_count = 0
    for m in all_matches:
        status = (m.runtime_status or "SCHEDULED").upper()
        if status == "FINAL":
            continue
        assign = assign_by_match.get(m.id)
        if not assign:
            affected_count += 1
            continue
        if assign.locked:
            continue
        slot = slot_map.get(assign.slot_id)
        if not slot:
            affected_count += 1
            continue
        if _slot_is_affected(slot, params):
            affected_count += 1

    # Compute available slot-minutes on non-affected days/slots
    kept_slot_ids: Set[int] = set()
    for m in all_matches:
        status = (m.runtime_status or "SCHEDULED").upper()
        assign = assign_by_match.get(m.id)
        if status == "FINAL" and assign:
            kept_slot_ids.add(assign.slot_id)
        elif assign and assign.locked:
            kept_slot_ids.add(assign.slot_id)
        elif assign:
            slot = slot_map.get(assign.slot_id)
            if slot and not _slot_is_affected(slot, params):
                kept_slot_ids.add(assign.slot_id)

    available_minutes = 0
    for s in all_slots:
        if s.id in kept_slot_ids:
            continue
        if _slot_is_affected(s, params):
            continue
        available_minutes += s.block_minutes

    formats: List[FormatFeasibility] = []
    for fmt_key in ["REGULAR", "PRO_SET_8", "PRO_SET_4"]:
        dur = SCORING_FORMATS[fmt_key]
        needed = affected_count * dur
        util = int(round(needed / available_minutes * 100)) if available_minutes > 0 else 999
        formats.append(FormatFeasibility(
            format=fmt_key,
            duration=dur,
            label=SCORING_FORMAT_LABELS[fmt_key],
            fits=needed <= available_minutes,
            utilization=util,
        ))

    return FeasibilityResult(affected_count=affected_count, formats=formats)


def compute_reschedule(
    session: Session,
    tournament_id: int,
    params: RescheduleParams,
) -> ReschedulePreview:
    """Compute a reschedule preview without mutating the database."""

    tournament = session.get(Tournament, tournament_id)
    if not tournament:
        raise ValueError("Tournament not found")

    version = session.get(ScheduleVersion, params.version_id)
    if not version or version.tournament_id != tournament_id:
        raise ValueError("Schedule version not found")

    # Load all matches, assignments, slots for this version
    all_matches = session.exec(
        select(Match)
        .where(Match.schedule_version_id == params.version_id)
        .order_by(
            case(
                (Match.match_type == "WF", 1),
                (Match.match_type == "RR", 2),
                (Match.match_type == "MAIN", 3),
                (Match.match_type == "CONSOLATION", 4),
                (Match.match_type == "PLACEMENT", 5),
                else_=99,
            ),
            Match.round_number,
            Match.sequence_in_round,
            Match.id,
        )
    ).all()

    all_assignments = session.exec(
        select(MatchAssignment).where(
            MatchAssignment.schedule_version_id == params.version_id,
        )
    ).all()

    all_slots = session.exec(
        select(ScheduleSlot).where(
            ScheduleSlot.schedule_version_id == params.version_id,
            ScheduleSlot.is_active == True,
        )
    ).all()

    # Build maps
    assign_by_match: Dict[int, MatchAssignment] = {a.match_id: a for a in all_assignments}
    slot_map: Dict[int, ScheduleSlot] = {s.id: s for s in all_slots}
    match_map: Dict[int, Match] = {m.id: m for m in all_matches}

    # Load event names
    event_ids = list({m.event_id for m in all_matches})
    events = session.exec(select(Event).where(Event.id.in_(event_ids))).all() if event_ids else []
    event_map = {e.id: e.name for e in events}

    # Identify affected matches: unplayed + in affected slots
    affected_matches: List[Match] = []
    kept_assignments: Dict[int, MatchAssignment] = {}  # match_id -> assignment (not moving)

    for m in all_matches:
        status = (m.runtime_status or "SCHEDULED").upper()
        if status == "FINAL":
            kept_assignments[m.id] = assign_by_match.get(m.id)  # type: ignore
            continue

        assign = assign_by_match.get(m.id)
        if not assign:
            affected_matches.append(m)
            continue

        if assign.locked:
            kept_assignments[m.id] = assign
            continue

        slot = slot_map.get(assign.slot_id)
        if not slot:
            affected_matches.append(m)
            continue

        if _slot_is_affected(slot, params):
            affected_matches.append(m)
        else:
            kept_assignments[m.id] = assign

    # Override match durations if a scoring format is specified.
    # Track original durations so apply can persist the changes.
    duration_updates: Dict[int, int] = {}
    format_applied: Optional[str] = None

    if params.scoring_format and params.scoring_format in SCORING_FORMATS:
        new_dur = SCORING_FORMATS[params.scoring_format]
        format_applied = params.scoring_format
        for m in affected_matches:
            if m.duration_minutes != new_dur:
                duration_updates[m.id] = new_dur
                m.duration_minutes = new_dur

    # Identify available slots (not affected, not occupied by kept matches)
    kept_slot_ids: Set[int] = set()
    for a in kept_assignments.values():
        if a:
            kept_slot_ids.add(a.slot_id)

    # When extend_day_end is set, proactively generate the full grid of
    # extended slots on the affected day across ALL courts so the engine has
    # room on the same day before spilling to later days.
    new_slot_ids: List[int] = []
    new_slots_created = 0

    if params.add_time_slots and params.extend_day_end:
        new_slots, new_ids = _generate_extended_day_slots(
            session, tournament, params, all_slots,
        )
        all_slots = list(all_slots) + new_slots
        for s in new_slots:
            slot_map[s.id] = s
        new_slot_ids = new_ids
        new_slots_created = len(new_ids)

    available_slots: List[ScheduleSlot] = []
    for s in all_slots:
        if s.id in kept_slot_ids:
            continue
        if _slot_is_affected(s, params):
            continue
        # For PARTIAL_DAY: don't backfill empty slots before the delay
        # window on the affected day. Only use slots at/after available_from
        # or on other days.
        if params.mode == "PARTIAL_DAY" and s.day_date == params.affected_day:
            resume_time = params.available_from or params.unavailable_from
            if resume_time and s.start_time < resume_time:
                continue
        available_slots.append(s)

    # If we still need more slots (no extend_day_end, or not enough room),
    # generate overflow on target days.
    if params.add_time_slots and len(affected_matches) > len(available_slots):
        overflow_needed = len(affected_matches) - len(available_slots)
        new_slots, new_ids = _generate_overflow_slots(
            session, tournament, params, all_slots, kept_slot_ids, overflow_needed,
        )
        available_slots.extend(new_slots)
        new_slot_ids.extend(new_ids)
        new_slots_created += len(new_ids)

    # Sort available slots: SAME DAY first (affected day), then other days.
    # Within each group: by time, then court.
    affected_day = params.affected_day

    def _slot_priority(s: ScheduleSlot):
        day_rank = 0 if s.day_date == affected_day else 1
        return (day_rank, s.day_date, s.start_time, s.court_number, s.id)

    available_slots.sort(key=_slot_priority)

    # Sort affected matches by their ORIGINAL slot time to preserve the
    # sequence the director built. Unassigned matches fall to the end,
    # sorted by match_type/round/sequence as a fallback.
    _type_order = {"WF": 1, "RR": 2, "MAIN": 3, "CONSOLATION": 4, "PLACEMENT": 5}

    def _original_sort_key(m: Match):
        assign = assign_by_match.get(m.id)
        slot = slot_map.get(assign.slot_id) if assign else None
        if slot:
            return (0, slot.day_date, slot.start_time, slot.court_number)
        return (1, date.max, time.max, _type_order.get(m.match_type, 99))

    affected_matches.sort(key=_original_sort_key)

    # Build dependency graph: match_id -> earliest allowed start
    # If match B has source_match_a_id = A, B must start after A ends.
    # Also enforce same-event round ordering: R2 after all R1 of that event.
    dep_sources: Dict[int, List[int]] = {}  # match_id -> [source match ids]
    for m in all_matches:
        deps: List[int] = []
        if m.source_match_a_id:
            deps.append(m.source_match_a_id)
        if m.source_match_b_id:
            deps.append(m.source_match_b_id)
        if deps:
            dep_sources[m.id] = deps

    # Build same-event round ordering: for each event, matches in round N
    # must come after all matches in round N-1 of the same event & type.
    event_type_round_matches: Dict[Tuple[int, str, int], List[int]] = {}
    for m in all_matches:
        key = (m.event_id, m.match_type, m.round_number)
        event_type_round_matches.setdefault(key, []).append(m.id)

    for m in all_matches:
        if m.round_number > 1:
            prev_key = (m.event_id, m.match_type, m.round_number - 1)
            prev_ids = event_type_round_matches.get(prev_key, [])
            existing_deps = dep_sources.get(m.id, [])
            for pid in prev_ids:
                if pid not in existing_deps:
                    dep_sources.setdefault(m.id, []).append(pid)

    # Build team state from kept assignments (for rest/overlap/cap tracking)
    team_busy: Dict[int, List[Tuple[datetime, datetime]]] = {}
    team_day_count: Dict[Tuple[int, date], int] = {}

    for mid, assign in kept_assignments.items():
        if not assign:
            continue
        m = match_map.get(mid)
        slot = slot_map.get(assign.slot_id)
        if not m or not slot:
            continue
        start_dt = datetime.combine(slot.day_date, slot.start_time)
        end_dt = start_dt + timedelta(minutes=m.duration_minutes)
        for tid in (m.team_a_id, m.team_b_id):
            if tid is not None:
                team_busy.setdefault(tid, []).append((start_dt, end_dt))
                key = (tid, slot.day_date)
                team_day_count[key] = team_day_count.get(key, 0) + 1

    # Track placed match end times for dependency ordering
    placed_end_times: Dict[int, datetime] = {}
    for mid, assign in kept_assignments.items():
        if not assign:
            continue
        m = match_map.get(mid)
        slot = slot_map.get(assign.slot_id)
        if m and slot:
            placed_end_times[mid] = datetime.combine(slot.day_date, slot.start_time) + timedelta(minutes=m.duration_minutes)

    # Auto-assign affected matches to available slots
    occupied_new: Set[int] = set()
    proposed_moves: List[ProposedMove] = []
    unplaceable: List[UnplaceableMatch] = []

    for m in affected_matches:
        old_assign = assign_by_match.get(m.id)
        old_slot = slot_map.get(old_assign.slot_id) if old_assign else None

        # Compute earliest allowed start from dependencies
        earliest_start: Optional[datetime] = None
        for dep_id in dep_sources.get(m.id, []):
            dep_end = placed_end_times.get(dep_id)
            if dep_end is not None:
                if earliest_start is None or dep_end > earliest_start:
                    earliest_start = dep_end

        placed = False
        for slot in available_slots:
            if slot.id in occupied_new:
                continue

            if slot.block_minutes < m.duration_minutes:
                continue

            slot_start = datetime.combine(slot.day_date, slot.start_time)
            slot_end = slot_start + timedelta(minutes=m.duration_minutes)

            # Ordering: slot must start at or after all dependencies end
            if earliest_start and slot_start < earliest_start:
                continue

            # Check team constraints
            ok = True
            for tid in (m.team_a_id, m.team_b_id):
                if tid is None:
                    continue

                # Concurrent play
                for busy_start, busy_end in team_busy.get(tid, []):
                    if slot_start < busy_end and slot_end > busy_start:
                        ok = False
                        break
                if not ok:
                    break

                # Daily cap
                day_key = (tid, slot.day_date)
                if team_day_count.get(day_key, 0) >= DAILY_CAP:
                    ok = False
                    break

                # Rest time
                for busy_start, busy_end in team_busy.get(tid, []):
                    if busy_end <= slot_start:
                        gap = (slot_start - busy_end).total_seconds() / 60
                        if gap < MIN_REST_MINUTES:
                            ok = False
                            break
                    if slot_end <= busy_start:
                        gap = (busy_start - slot_end).total_seconds() / 60
                        if gap < MIN_REST_MINUTES:
                            ok = False
                            break
                if not ok:
                    break

            if not ok:
                continue

            # Place match here
            occupied_new.add(slot.id)
            placed_end_times[m.id] = slot_end
            for tid in (m.team_a_id, m.team_b_id):
                if tid is not None:
                    team_busy.setdefault(tid, []).append((slot_start, slot_end))
                    day_key = (tid, slot.day_date)
                    team_day_count[day_key] = team_day_count.get(day_key, 0) + 1

            court_label = slot.court_label or str(slot.court_number)
            proposed_moves.append(ProposedMove(
                match_id=m.id,
                match_number=m.id,
                match_code=m.match_code,
                event_name=event_map.get(m.event_id, ""),
                stage=m.match_type,
                old_slot_id=old_assign.slot_id if old_assign else None,
                old_court=f"Court {old_slot.court_label}" if old_slot else None,
                old_time=_time_str(old_slot.start_time) if old_slot else None,
                old_day=_day_str(old_slot.day_date) if old_slot else None,
                new_slot_id=slot.id,
                new_court=f"Court {court_label}",
                new_time=_time_str(slot.start_time),
                new_day=_day_str(slot.day_date),
            ))
            placed = True
            break

        if not placed:
            unplaceable.append(UnplaceableMatch(
                match_id=m.id,
                match_number=m.id,
                match_code=m.match_code,
                event_name=event_map.get(m.event_id, ""),
                stage=m.match_type,
                reason="NO_AVAILABLE_SLOT",
            ))

    return ReschedulePreview(
        proposed_moves=proposed_moves,
        unplaceable=unplaceable,
        new_slots_created=new_slots_created,
        created_slot_ids=new_slot_ids,
        stats={
            "total_affected": len(affected_matches),
            "total_moved": len(proposed_moves),
            "total_unplaceable": len(unplaceable),
            "total_kept": len(kept_assignments),
        },
        format_applied=format_applied,
        duration_updates=duration_updates,
    )


def apply_reschedule(
    session: Session,
    tournament_id: int,
    version_id: int,
    moves: List[Dict[str, Any]],
    duration_updates: Optional[Dict[int, int]] = None,
) -> Dict[str, Any]:
    """Apply proposed moves by updating MatchAssignment rows and optionally
    persisting new match durations from a scoring format change."""
    version = session.get(ScheduleVersion, version_id)
    if not version or version.tournament_id != tournament_id:
        raise ValueError("Version not found")
    if version.status != "draft":
        raise ValueError("Reschedule only allowed on DRAFT versions")

    updated = 0
    for move in moves:
        match_id = move["match_id"]
        new_slot_id = move["new_slot_id"]

        existing = session.exec(
            select(MatchAssignment).where(
                MatchAssignment.schedule_version_id == version_id,
                MatchAssignment.match_id == match_id,
            )
        ).first()

        if existing:
            existing.slot_id = new_slot_id
            existing.assigned_by = "RESCHEDULE"
            existing.assigned_at = datetime.utcnow()
            existing.locked = True
            session.add(existing)
        else:
            new_assign = MatchAssignment(
                schedule_version_id=version_id,
                match_id=match_id,
                slot_id=new_slot_id,
                assigned_by="RESCHEDULE",
                assigned_at=datetime.utcnow(),
                locked=True,
            )
            session.add(new_assign)
        updated += 1

    # Persist duration changes from scoring format compression
    if duration_updates:
        for match_id, new_dur in duration_updates.items():
            match = session.get(Match, match_id)
            if match and match.schedule_version_id == version_id:
                match.duration_minutes = new_dur
                session.add(match)

    session.commit()
    return {"updated_matches": updated, "applied_moves": len(moves)}


def _generate_extended_day_slots(
    session: Session,
    tournament: Tournament,
    params: RescheduleParams,
    existing_slots: List[ScheduleSlot],
) -> Tuple[List[ScheduleSlot], List[int]]:
    """Generate slots for the extended window on the affected day across ALL courts.

    Unlike overflow (which creates minimum needed), this creates the full grid
    so the engine has maximum room on the same day.
    """
    if not params.extend_day_end:
        return [], []

    court_names = tournament.court_names or ["1"]
    court_numbers = list(range(1, len(court_names) + 1))
    if params.mode == "COURT_LOSS" and params.unavailable_courts:
        court_numbers = [c for c in court_numbers if c not in params.unavailable_courts]

    day = params.affected_day
    block = params.block_minutes
    end_limit = params.extend_day_end

    # Find the latest existing end time on this day
    max_end = time(0, 0)
    for s in existing_slots:
        if s.day_date == day and s.end_time > max_end:
            max_end = s.end_time

    # Collect existing slot keys to avoid duplicates
    existing_keys: Set[Tuple[int, date, time]] = set()
    for s in existing_slots:
        existing_keys.add((s.court_number, s.day_date, s.start_time))

    created: List[ScheduleSlot] = []
    created_ids: List[int] = []

    current_start = max_end
    while True:
        end_minutes = current_start.hour * 60 + current_start.minute + block
        if end_minutes > end_limit.hour * 60 + end_limit.minute:
            break
        end_t = time(end_minutes // 60, end_minutes % 60)

        for cn in court_numbers:
            key = (cn, day, current_start)
            if key in existing_keys:
                continue

            label = court_label_for_index(court_names, cn) if court_names else str(cn)
            new_slot = ScheduleSlot(
                tournament_id=tournament.id,
                schedule_version_id=params.version_id,
                day_date=day,
                start_time=current_start,
                end_time=end_t,
                court_number=cn,
                court_label=label,
                block_minutes=block,
            )
            session.add(new_slot)
            session.flush()
            created.append(new_slot)
            created_ids.append(new_slot.id)
            existing_keys.add(key)

        current_start = end_t

    return created, created_ids


def _generate_overflow_slots(
    session: Session,
    tournament: Tournament,
    params: RescheduleParams,
    existing_slots: List[ScheduleSlot],
    kept_slot_ids: Set[int],
    needed: int,
) -> Tuple[List[ScheduleSlot], List[int]]:
    """Generate new slots for overflow matches."""
    court_names = tournament.court_names or ["1"]
    court_numbers = list(range(1, len(court_names) + 1))

    # Determine which courts are available
    if params.mode == "COURT_LOSS" and params.unavailable_courts:
        court_numbers = [c for c in court_numbers if c not in params.unavailable_courts]

    # Determine target days
    target_days: List[date] = []
    if params.target_days:
        target_days = params.target_days
    elif params.extend_day_end:
        target_days = [params.affected_day]
    else:
        all_days = sorted({s.day_date for s in existing_slots})
        target_days = [d for d in all_days if d >= params.affected_day]
        if not target_days:
            target_days = [params.affected_day]

    # Find the latest existing time per target day
    day_max_time: Dict[date, time] = {}
    for s in existing_slots:
        if s.day_date in target_days:
            if s.day_date not in day_max_time or s.end_time > day_max_time[s.day_date]:
                day_max_time[s.day_date] = s.end_time

    # Existing slot keys to avoid duplicates
    existing_keys: Set[Tuple[int, date, time]] = set()
    for s in existing_slots:
        existing_keys.add((s.court_number, s.day_date, s.start_time))

    block = params.block_minutes
    created: List[ScheduleSlot] = []
    created_ids: List[int] = []

    for day in target_days:
        if len(created) >= needed:
            break

        start_after = day_max_time.get(day, time(17, 0))
        if params.extend_day_end and day == params.affected_day:
            end_limit = params.extend_day_end
        else:
            end_limit = time(21, 0)

        current_start = start_after
        while len(created) < needed:
            end_minutes = current_start.hour * 60 + current_start.minute + block
            if end_minutes > end_limit.hour * 60 + end_limit.minute:
                break

            end_t = time(end_minutes // 60, end_minutes % 60)

            for cn in court_numbers:
                if len(created) >= needed:
                    break
                key = (cn, day, current_start)
                if key in existing_keys:
                    continue

                label = court_label_for_index(court_names, cn) if court_names else str(cn)
                new_slot = ScheduleSlot(
                    tournament_id=tournament.id,
                    schedule_version_id=params.version_id,
                    day_date=day,
                    start_time=current_start,
                    end_time=end_t,
                    court_number=cn,
                    court_label=label,
                    block_minutes=block,
                )
                session.add(new_slot)
                session.flush()
                created.append(new_slot)
                created_ids.append(new_slot.id)
                existing_keys.add(key)

            current_start = end_t

    return created, created_ids


# ══════════════════════════════════════════════════════════════════════════
#  Rebuild Remaining Schedule
# ══════════════════════════════════════════════════════════════════════════

@dataclass
class RebuildDayConfig:
    day_date: date
    start_time: time
    end_time: time
    courts: int
    format: str  # REGULAR | PRO_SET_8 | PRO_SET_4
    block_minutes: int = 0  # resolved from format

    def __post_init__(self):
        if self.block_minutes == 0:
            self.block_minutes = SCORING_FORMATS.get(self.format, 105)


@dataclass
class RebuildMatchItem:
    match_id: int
    match_number: int
    match_code: str
    event_name: str
    stage: str
    team1: str
    team2: str
    status: str
    rank: int


@dataclass
class RebuildPreview:
    remaining_matches: int
    in_progress_matches: int
    total_slots: int
    fits: bool
    overflow: int
    matches: List[RebuildMatchItem]
    per_day: List[Dict[str, Any]]
    dropped_count: int = 0


@dataclass
class RebuildResult:
    assigned: int
    unplaceable: int
    slots_created: int
    duration_updates: int
    dropped_count: int = 0


def _should_drop_consolation(m: Match, drop_mode: str) -> bool:
    """Check if a match should be dropped based on consolation trimming mode."""
    if drop_mode == "none":
        return False
    if m.match_type != "CONSOLATION" and m.match_type != "PLACEMENT":
        return False
    if drop_mode == "all":
        return True
    if drop_mode == "finals":
        if m.match_type == "PLACEMENT":
            return True
        return m.round_index >= 2
    return False


def compute_rebuild_preview(
    session: Session,
    tournament_id: int,
    version_id: int,
    day_configs: List[RebuildDayConfig],
    drop_consolation: str = "none",
) -> RebuildPreview:
    """Dry-run: count remaining matches and compute slot capacity."""

    all_matches = session.exec(
        select(Match).where(Match.schedule_version_id == version_id)
    ).all()

    event_ids = list({m.event_id for m in all_matches})
    events = session.exec(select(Event).where(Event.id.in_(event_ids))).all() if event_ids else []
    event_map = {e.id: e.name for e in events}

    team_map: Dict[int, str] = {}
    def _team_name(tid: Optional[int], placeholder: str) -> str:
        if tid is None:
            return placeholder
        if tid not in team_map:
            from app.models.team import Team
            t = session.get(Team, tid)
            team_map[tid] = t.name if t else placeholder
        return team_map[tid]

    # Load current assignments and their slots to determine original order
    all_assignments = session.exec(
        select(MatchAssignment).where(
            MatchAssignment.schedule_version_id == version_id,
        )
    ).all()
    assign_by_match = {a.match_id: a for a in all_assignments}

    all_slots = session.exec(
        select(ScheduleSlot).where(
            ScheduleSlot.schedule_version_id == version_id,
        )
    ).all()
    slot_map = {s.id: s for s in all_slots}

    STAGE_PRECEDENCE = {"WF": 1, "RR": 2, "MAIN": 3, "CONSOLATION": 4, "PLACEMENT": 5}

    remaining: List[Match] = []
    dropped_count = 0
    in_progress_count = 0
    for m in all_matches:
        status = (m.runtime_status or "SCHEDULED").upper()
        if status == "FINAL":
            continue
        if status != "IN_PROGRESS" and _should_drop_consolation(m, drop_consolation):
            dropped_count += 1
            continue
        remaining.append(m)
        if status == "IN_PROGRESS":
            in_progress_count += 1

    def _original_order_key(m: Match) -> Tuple:
        """Sort by original slot assignment (day -> time -> court), unassigned at end."""
        status = (m.runtime_status or "SCHEDULED").upper()
        status_order = 0 if status == "IN_PROGRESS" else 1
        assign = assign_by_match.get(m.id)
        slot = slot_map.get(assign.slot_id) if assign else None
        if slot:
            return (status_order, 0, slot.day_date, slot.start_time, slot.court_number, m.id)
        # Unassigned: fall to end, sorted by stage precedence
        sp = STAGE_PRECEDENCE.get(m.match_type, 99)
        return (status_order, 1, date.max, time.max, sp, m.round_index or 999, m.sequence_in_round or 999, m.id)

    remaining.sort(key=_original_order_key)

    total_slots = 0
    per_day: List[Dict[str, Any]] = []
    for dc in day_configs:
        start_min = dc.start_time.hour * 60 + dc.start_time.minute
        end_min = dc.end_time.hour * 60 + dc.end_time.minute
        slots_per_court = max(0, (end_min - start_min) // dc.block_minutes)
        day_slots = slots_per_court * dc.courts
        total_slots += day_slots
        per_day.append({
            "date": dc.day_date.isoformat(),
            "slots": day_slots,
            "courts": dc.courts,
            "format": dc.format,
            "block_minutes": dc.block_minutes,
        })

    match_items = []
    for i, m in enumerate(remaining):
        status = (m.runtime_status or "SCHEDULED").upper()
        match_items.append(RebuildMatchItem(
            match_id=m.id,
            match_number=m.id,
            match_code=m.match_code,
            event_name=event_map.get(m.event_id, ""),
            stage=m.match_type,
            team1=_team_name(m.team_a_id, m.placeholder_side_a),
            team2=_team_name(m.team_b_id, m.placeholder_side_b),
            status=status,
            rank=i + 1,
        ))

    overflow = max(0, len(remaining) - total_slots)

    return RebuildPreview(
        remaining_matches=len(remaining),
        in_progress_matches=in_progress_count,
        total_slots=total_slots,
        fits=overflow == 0,
        overflow=overflow,
        matches=match_items,
        per_day=per_day,
        dropped_count=dropped_count,
    )


def apply_rebuild(
    session: Session,
    tournament_id: int,
    version_id: int,
    day_configs: List[RebuildDayConfig],
    drop_consolation: str = "none",
) -> RebuildResult:
    """Regenerate slots and reassign all remaining matches."""

    tournament = session.get(Tournament, tournament_id)
    if not tournament:
        raise ValueError("Tournament not found")

    version = session.get(ScheduleVersion, version_id)
    if not version or version.tournament_id != tournament_id:
        raise ValueError("Schedule version not found")
    if version.status != "draft":
        raise ValueError("Rebuild only allowed on DRAFT versions")

    court_names = tournament.court_names or ["1"]

    all_matches = session.exec(
        select(Match).where(Match.schedule_version_id == version_id)
    ).all()

    event_ids = list({m.event_id for m in all_matches})
    events = session.exec(select(Event).where(Event.id.in_(event_ids))).all() if event_ids else []
    event_map = {e.id: e.name for e in events}

    # Load current assignments and slots BEFORE deleting them, to determine original order
    pre_assignments = session.exec(
        select(MatchAssignment).where(
            MatchAssignment.schedule_version_id == version_id,
        )
    ).all()
    pre_assign_by_match = {a.match_id: a for a in pre_assignments}

    pre_slots = session.exec(
        select(ScheduleSlot).where(
            ScheduleSlot.schedule_version_id == version_id,
        )
    ).all()
    pre_slot_map = {s.id: s for s in pre_slots}

    STAGE_PRECEDENCE = {"WF": 1, "RR": 2, "MAIN": 3, "CONSOLATION": 4, "PLACEMENT": 5}

    remaining: List[Match] = []
    dropped_matches: List[Match] = []
    final_match_ids: Set[int] = set()
    for m in all_matches:
        status = (m.runtime_status or "SCHEDULED").upper()
        if status == "FINAL":
            final_match_ids.add(m.id)
        elif status != "IN_PROGRESS" and _should_drop_consolation(m, drop_consolation):
            dropped_matches.append(m)
        else:
            remaining.append(m)

    def _original_order_key(m: Match) -> Tuple:
        """Sort by original slot assignment (day -> time -> court), unassigned at end."""
        status = (m.runtime_status or "SCHEDULED").upper()
        status_order = 0 if status == "IN_PROGRESS" else 1
        assign = pre_assign_by_match.get(m.id)
        slot = pre_slot_map.get(assign.slot_id) if assign else None
        if slot:
            return (status_order, 0, slot.day_date, slot.start_time, slot.court_number, m.id)
        # Unassigned: fall to end, sorted by stage precedence
        sp = STAGE_PRECEDENCE.get(m.match_type, 99)
        return (status_order, 1, date.max, time.max, sp, m.round_index or 999, m.sequence_in_round or 999, m.id)

    remaining.sort(key=_original_order_key)

    # Mark dropped consolation matches as CANCELLED
    dropped_ids: Set[int] = set()
    for m in dropped_matches:
        m.runtime_status = "CANCELLED"
        session.add(m)
        dropped_ids.add(m.id)

    # Delete non-FINAL assignments (including dropped matches)
    existing_assignments = session.exec(
        select(MatchAssignment).where(
            MatchAssignment.schedule_version_id == version_id,
        )
    ).all()
    for a in existing_assignments:
        if a.match_id not in final_match_ids:
            session.delete(a)
    session.flush()

    # Delete slots on rebuild days (keep slots for days not in config)
    rebuild_dates = {dc.day_date for dc in day_configs}
    existing_slots = session.exec(
        select(ScheduleSlot).where(
            ScheduleSlot.schedule_version_id == version_id,
        )
    ).all()

    final_slot_ids: Set[int] = set()
    for a in existing_assignments:
        if a.match_id in final_match_ids:
            final_slot_ids.add(a.slot_id)

    for s in existing_slots:
        if s.day_date in rebuild_dates and s.id not in final_slot_ids:
            session.delete(s)
    session.flush()

    # Generate new slots from day configs
    new_slots: List[ScheduleSlot] = []
    for dc in day_configs:
        start_min = dc.start_time.hour * 60 + dc.start_time.minute
        end_min = dc.end_time.hour * 60 + dc.end_time.minute
        current = start_min
        while current + dc.block_minutes <= end_min:
            slot_start = time(current // 60, current % 60)
            slot_end_min = current + dc.block_minutes
            slot_end = time(slot_end_min // 60, slot_end_min % 60)
            for court_num in range(1, dc.courts + 1):
                label = court_label_for_index(court_names, court_num)
                slot = ScheduleSlot(
                    tournament_id=tournament_id,
                    schedule_version_id=version_id,
                    day_date=dc.day_date,
                    start_time=slot_start,
                    end_time=slot_end,
                    court_number=court_num,
                    court_label=label,
                    block_minutes=dc.block_minutes,
                    is_active=True,
                )
                session.add(slot)
                new_slots.append(slot)
            current += dc.block_minutes
    session.flush()

    # Update durations for remaining matches based on per-day format
    format_by_date = {dc.day_date: dc.format for dc in day_configs}
    global_format = day_configs[0].format if day_configs else "REGULAR"
    global_dur = SCORING_FORMATS.get(global_format, 105)
    duration_update_count = 0

    all_same_format = len(set(dc.format for dc in day_configs)) == 1
    if all_same_format:
        for m in remaining:
            if m.duration_minutes != global_dur:
                m.duration_minutes = global_dur
                session.add(m)
                duration_update_count += 1

    # Sort new slots chronologically
    new_slots.sort(key=lambda s: (s.day_date, s.start_time, s.court_number))

    # Build dependency graph
    match_map: Dict[int, Match] = {m.id: m for m in all_matches}
    dep_sources: Dict[int, List[int]] = {}
    for m in all_matches:
        deps: List[int] = []
        if m.source_match_a_id:
            deps.append(m.source_match_a_id)
        if m.source_match_b_id:
            deps.append(m.source_match_b_id)
        if deps:
            dep_sources[m.id] = deps

    event_type_round_matches: Dict[Tuple[int, str, int], List[int]] = {}
    for m in all_matches:
        key = (m.event_id, m.match_type, m.round_number)
        event_type_round_matches.setdefault(key, []).append(m.id)
    for m in all_matches:
        if m.round_number > 1:
            prev_key = (m.event_id, m.match_type, m.round_number - 1)
            prev_ids = event_type_round_matches.get(prev_key, [])
            existing_deps = dep_sources.get(m.id, [])
            for pid in prev_ids:
                if pid not in existing_deps:
                    dep_sources.setdefault(m.id, []).append(pid)

    # Track FINAL match end times for dependency ordering
    final_assignments_map: Dict[int, MatchAssignment] = {}
    for a in existing_assignments:
        if a.match_id in final_match_ids:
            final_assignments_map[a.match_id] = a

    all_slot_map: Dict[int, ScheduleSlot] = {}
    remaining_old_slots = session.exec(
        select(ScheduleSlot).where(ScheduleSlot.schedule_version_id == version_id)
    ).all()
    for s in remaining_old_slots:
        all_slot_map[s.id] = s
    for s in new_slots:
        all_slot_map[s.id] = s

    # Compute rest time from scoring format (rest = match duration)
    # If all days use the same format, use that duration. Otherwise use the minimum.
    rebuild_durations = [SCORING_FORMATS.get(dc.format, 105) for dc in day_configs]
    rebuild_rest_minutes = min(rebuild_durations) if rebuild_durations else 105

    placed_end_times: Dict[int, datetime] = {}
    team_busy: Dict[int, List[Tuple[datetime, datetime]]] = {}

    for mid in final_match_ids:
        m = match_map.get(mid)
        a = final_assignments_map.get(mid)
        if not m or not a:
            continue
        slot = all_slot_map.get(a.slot_id)
        if not slot:
            continue
        start_dt = datetime.combine(slot.day_date, slot.start_time)
        end_dt = start_dt + timedelta(minutes=m.duration_minutes)
        placed_end_times[mid] = end_dt
        for tid in (m.team_a_id, m.team_b_id):
            if tid is not None:
                team_busy.setdefault(tid, []).append((start_dt, end_dt))

    # First-fit assignment with constraints
    occupied: Set[int] = set()
    assigned_count = 0
    unplaceable_count = 0

    for m in remaining:
        if not all_same_format:
            pass

        earliest_start: Optional[datetime] = None
        for dep_id in dep_sources.get(m.id, []):
            dep_end = placed_end_times.get(dep_id)
            if dep_end is not None:
                if earliest_start is None or dep_end > earliest_start:
                    earliest_start = dep_end

        placed = False
        for slot in new_slots:
            if slot.id in occupied:
                continue
            if slot.block_minutes < m.duration_minutes:
                continue

            slot_start = datetime.combine(slot.day_date, slot.start_time)
            slot_end = slot_start + timedelta(minutes=m.duration_minutes)

            if earliest_start and slot_start < earliest_start:
                continue

            ok = True
            for tid in (m.team_a_id, m.team_b_id):
                if tid is None:
                    continue
                for busy_start, busy_end in team_busy.get(tid, []):
                    if slot_start < busy_end and slot_end > busy_start:
                        ok = False
                        break
                if not ok:
                    break
                for busy_start, busy_end in team_busy.get(tid, []):
                    if busy_end <= slot_start:
                        gap = (slot_start - busy_end).total_seconds() / 60
                        if gap < rebuild_rest_minutes:
                            ok = False
                            break
                    if slot_end <= busy_start:
                        gap = (busy_start - slot_end).total_seconds() / 60
                        if gap < rebuild_rest_minutes:
                            ok = False
                            break
                if not ok:
                    break

            if not ok:
                continue

            occupied.add(slot.id)
            placed_end_times[m.id] = slot_end
            for tid in (m.team_a_id, m.team_b_id):
                if tid is not None:
                    team_busy.setdefault(tid, []).append((slot_start, slot_end))

            assignment = MatchAssignment(
                schedule_version_id=version_id,
                match_id=m.id,
                slot_id=slot.id,
                assigned_by="REBUILD",
                assigned_at=datetime.utcnow(),
                locked=False,
            )
            session.add(assignment)
            assigned_count += 1
            placed = True
            break

        if not placed:
            unplaceable_count += 1

    session.commit()

    return RebuildResult(
        assigned=assigned_count,
        unplaceable=unplaceable_count,
        slots_created=len(new_slots),
        duration_updates=duration_update_count,
        dropped_count=len(dropped_matches),
    )
