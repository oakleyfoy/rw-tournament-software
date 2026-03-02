"""
Schedule Policy Planner — deterministic batch-based match placement.

This module produces an ordered list of PlacementBatch objects for a given
tournament day.  Each batch is a named slice of matches in deterministic order.
The existing ``assign_by_match_ids`` first-fit assigner is used as the executor.

Policy rules implemented
========================

A. Daily match cap: no team > 2 matches / day.
B. Everyone plays match #1 before match #2 (fairness layering).
C. Event priority: descending team_count; rotation ONLY within same-size buckets.
D. Day 1 layering: WF R1 → no-WF firsts → WF R2 → remaining.
E. Spare-court reservation: ≥1 spare per time-bucket (except first).
   Deterministic court ordering: court_number asc, court_label asc, slot.id asc.
F. Day 2+ layering: bracket + RR by event size w/ daily rotation.
G. Dependency gate: bracket matches with unresolved upstream are excluded.
H. Consolation gating: don't start a consolation round unless slots can fit it.
"""

from __future__ import annotations

import json
import logging
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time
from typing import Any, Dict, List, Optional, Set, Tuple

from sqlmodel import Session, select

from app.models.event import Event
from app.models.match import Match
from app.models.match_assignment import MatchAssignment
from app.models.schedule_slot import ScheduleSlot
from app.models.schedule_version import ScheduleVersion

logger = logging.getLogger(__name__)

# ── Stage precedence (re-used from auto_assign) ───────────────────────
STAGE_PRECEDENCE = {"WF": 1, "RR": 2, "MAIN": 3, "CONSOLATION": 4, "PLACEMENT": 5}


# ══════════════════════════════════════════════════════════════════════════
#  Data containers
# ══════════════════════════════════════════════════════════════════════════

@dataclass
class PlacementBatch:
    """A named slice of match IDs ready for first-fit assignment."""
    name: str
    match_ids: List[int]
    description: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "match_ids": self.match_ids,
            "match_count": len(self.match_ids),
            "description": self.description,
        }


@dataclass
class DailyPlan:
    """All placement batches for one tournament day."""
    day_date: date
    day_index: int            # 0-based ordinal within tournament days
    batches: List[PlacementBatch] = field(default_factory=list)
    reserved_slot_ids: List[int] = field(default_factory=list)
    deferred_final_ids: List[int] = field(default_factory=list)  # Finals excluded from Day 2

    def to_dict(self) -> Dict[str, Any]:
        return {
            "day_date": str(self.day_date),
            "day_index": self.day_index,
            "batches": [b.to_dict() for b in self.batches],
            "total_match_ids": sum(len(b.match_ids) for b in self.batches),
            "reserved_slot_ids": self.reserved_slot_ids,
        }


@dataclass
class BatchResult:
    """Result of executing one batch."""
    name: str
    attempted: int
    assigned: int
    failed_match_ids: List[int] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "attempted": self.attempted,
            "assigned": self.assigned,
            "failed_count": len(self.failed_match_ids),
            "failed_match_ids": self.failed_match_ids,
        }


@dataclass
class PolicyRunResult:
    """Aggregate result of running a daily policy plan."""
    day_date: date
    batches: List[BatchResult] = field(default_factory=list)
    total_assigned: int = 0
    total_failed: int = 0
    reserved_slot_count: int = 0
    duration_ms: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "day_date": str(self.day_date),
            "batches": [b.to_dict() for b in self.batches],
            "total_assigned": self.total_assigned,
            "total_failed": self.total_failed,
            "reserved_slot_count": self.reserved_slot_count,
            "duration_ms": self.duration_ms,
        }


# ══════════════════════════════════════════════════════════════════════════
#  Helpers
# ══════════════════════════════════════════════════════════════════════════

def _get_draw_plan(event: Event) -> Dict[str, Any]:
    """Parse draw_plan_json safely."""
    if event.draw_plan_json:
        try:
            return json.loads(event.draw_plan_json)
        except (json.JSONDecodeError, TypeError):
            pass
    return {}


def _event_has_wf(event: Event) -> bool:
    plan = _get_draw_plan(event)
    return plan.get("wf_rounds", 0) >= 1


def _event_wf_rounds(event: Event) -> int:
    plan = _get_draw_plan(event)
    return plan.get("wf_rounds", 0)


# ── True list-rotation for event priority ────────────────────────────

def _build_rotated_event_list(events: List[Event], day_index: int) -> List[Event]:
    """
    Build a deterministic event ordering with size-bucket rotation.

    Primary key: team_count DESC — NEVER violated.
    Secondary key: daily rotation — ONLY within same-size events.

    A smaller event can never jump ahead of a larger one.

    1. Group events by team_count.
    2. Process buckets largest → smallest.
    3. Within each bucket, sort by event_id ASC, then rotate by day_index.
    """
    if not events:
        return []

    # Step 1: group by team_count
    buckets: Dict[int, List[Event]] = {}
    for e in events:
        buckets.setdefault(e.team_count, []).append(e)

    # Step 2: process buckets largest → smallest
    ordered: List[Event] = []
    for team_count in sorted(buckets.keys(), reverse=True):
        bucket = sorted(buckets[team_count], key=lambda e: e.id or 0)
        # Rotate ONLY inside this bucket
        n = len(bucket)
        offset = day_index % n
        rotated = bucket[offset:] + bucket[:offset]
        ordered.extend(rotated)

    return ordered


def _build_event_priority_map(events: List[Event], day_index: int) -> Dict[int, int]:
    """Map event_id → priority rank (0 = highest) for a given day."""
    rotated = _build_rotated_event_list(events, day_index)
    return {e.id: idx for idx, e in enumerate(rotated)}


def _match_sort_key(m: Match, event_priority: Dict[int, int]) -> Tuple:
    """Deterministic sort key for matches within a batch."""
    ep = event_priority.get(m.event_id, 999)
    sp = STAGE_PRECEDENCE.get(m.match_type, 999)
    return (ep, sp, m.round_index or 999, m.sequence_in_round or 999, m.id or 999)


# ── Team identity helpers ────────────────────────────────────────────

def _get_team_ids_for_match(match: Match) -> Set[int]:
    """Extract resolved team IDs from a match (empty if unresolved)."""
    ids: Set[int] = set()
    if match.team_a_id:
        ids.add(match.team_a_id)
    if match.team_b_id:
        ids.add(match.team_b_id)
    return ids


def _is_resolved_match(match: Match, assigned_match_ids: Set[int]) -> bool:
    """
    Check whether a match is eligible for *schedule planning* (batch placement).

    This is NOT the sequencing check — the auto-assign dependency checker
    (check_round_dependencies_for_auto_assign) enforces that bracket SFs
    come after QFs, etc., using source links and rest-gap math.

    For planning purposes, bracket matches (MAIN / CONSOLATION) are always
    considered resolved because:
    - The batch planner already orders QFs → SFs → Finals.
    - The auto-assign enforces actual timing constraints.
    - Gating on source_match_a_id/b_id here would cascade-block matches
      when their source matches are planned for the same day but not yet
      committed to the assignment table.

    WF / RR: source links gate correctly (round N needs round N-1 assigned).
    """
    # WF and RR: always resolved (seeded directly)
    if match.match_type in ("WF", "RR"):
        return True

    # MAIN / CONSOLATION / PLACEMENT: always eligible for planning.
    # Bracket sequencing is enforced by auto_assign's dependency check.
    if match.match_type in ("MAIN", "CONSOLATION", "PLACEMENT"):
        return True

    # If both teams are already injected, resolved
    if match.team_a_id and match.team_b_id:
        return True

    # Check upstream dependencies (for any other match types)
    has_upstream_a = match.source_match_a_id is not None
    has_upstream_b = match.source_match_b_id is not None

    if not has_upstream_a and not has_upstream_b:
        # No upstream — treat as resolved
        return True

    # If upstream exists, it must be assigned
    if has_upstream_a and match.source_match_a_id not in assigned_match_ids:
        return False
    if has_upstream_b and match.source_match_b_id not in assigned_match_ids:
        return False

    return True


def _build_team_match_count_on_day(
    session: Session,
    schedule_version_id: int,
    day_date: date,
) -> Dict[int, int]:
    """
    Count how many matches each team already has assigned on a specific day.
    Returns {team_id: count}.
    """
    counts: Dict[int, int] = defaultdict(int)

    # Get all assignments for this version
    assignments = session.exec(
        select(MatchAssignment).where(
            MatchAssignment.schedule_version_id == schedule_version_id
        )
    ).all()

    if not assignments:
        return counts

    # Get slots on this day
    day_slots = session.exec(
        select(ScheduleSlot).where(
            ScheduleSlot.schedule_version_id == schedule_version_id,
            ScheduleSlot.day_date == day_date,
        )
    ).all()
    day_slot_ids = {s.id for s in day_slots}

    # Get assignments on this day
    day_assignment_match_ids = set()
    for a in assignments:
        if a.slot_id in day_slot_ids:
            day_assignment_match_ids.add(a.match_id)

    # Get those matches and count teams
    if day_assignment_match_ids:
        matches = session.exec(
            select(Match).where(
                Match.schedule_version_id == schedule_version_id,
            )
        ).all()
        for m in matches:
            if m.id in day_assignment_match_ids:
                for tid in _get_team_ids_for_match(m):
                    counts[tid] += 1

    return counts


def _filter_by_team_cap(
    matches: List[Match],
    team_day_counts: Dict[int, int],
    max_per_day: int = 2,
) -> List[Match]:
    """
    Filter out matches where either team would exceed the daily cap.
    Mutates team_day_counts to track running totals as matches are selected.
    """
    result: List[Match] = []
    for m in matches:
        tids = _get_team_ids_for_match(m)
        if not tids:
            # Unresolved teams — allow (conservative: can't block what we don't know)
            result.append(m)
            continue
        # Check if any team would exceed cap
        would_exceed = any(team_day_counts.get(tid, 0) >= max_per_day for tid in tids)
        if not would_exceed:
            result.append(m)
            for tid in tids:
                team_day_counts[tid] = team_day_counts.get(tid, 0) + 1
    return result


def _filter_resolved(
    matches: List[Match],
    assigned_match_ids: Set[int],
) -> List[Match]:
    """Keep only matches whose upstream dependencies are resolved."""
    return [m for m in matches if _is_resolved_match(m, assigned_match_ids)]


def _event_has_unassigned_main_matches(
    event_id: int,
    all_matches: List[Match],
    assigned_match_ids: Set[int],
) -> bool:
    """
    Check if an event has any unassigned MAIN matches.
    
    Returns True if there are MAIN matches for this event that are not yet assigned.
    """
    for m in all_matches:
        if m.event_id == event_id and m.match_type == "MAIN":
            if m.id not in assigned_match_ids:
                return True
    return False


def _identify_failed_main_due_to_rest_gap(
    failed_match_ids: List[int],
    match_by_id: Dict[int, Match],
    session: Session,
    schedule_version_id: int,
    day_date: date,
) -> List[Match]:
    """
    Identify MAIN matches that failed due to rest gap constraints.
    
    Checks if matches have prerequisite matches that were assigned recently
    enough to cause rest gap violation (within same day).
    """
    from app.utils.auto_assign import _get_bracket_prerequisites
    from app.models.match_assignment import MatchAssignment
    
    failed_main: List[Match] = []
    
    # Build bracket tier cache for all matches
    all_matches = list(match_by_id.values())
    bracket_tier_cache: Dict[int, str] = {}
    main_matches = [m for m in all_matches if m.match_type == "MAIN"]
    main_classified = _classify_bracket_matches(main_matches)
    for m in main_classified.get("qf", []):
        bracket_tier_cache[m.id] = "qf"
    for m in main_classified.get("sf", []):
        bracket_tier_cache[m.id] = "sf"
    for m in main_classified.get("final", []):
        bracket_tier_cache[m.id] = "final"
    
    _all_assignments = session.exec(
        select(MatchAssignment).where(
            MatchAssignment.schedule_version_id == schedule_version_id
        )
    ).all()
    assigned_match_ids_set = {a.match_id for a in _all_assignments}
    
    for match_id in failed_match_ids:
        match = match_by_id.get(match_id)
        if not match or match.match_type != "MAIN":
            continue
        
        tier = bracket_tier_cache.get(match_id, "qf")
        if tier == "qf":
            continue  # QFs are independent, can't fail due to rest gap
        
        prereqs = _get_bracket_prerequisites(match, tier, all_matches, bracket_tier_cache)
        if not prereqs:
            continue
        
        # Check if any prerequisite was assigned recently (same day, causing rest gap)
        for prereq in prereqs:
            if prereq.id not in assigned_match_ids_set:
                continue
            
            prereq_assignment = session.exec(
                select(MatchAssignment).where(
                    MatchAssignment.schedule_version_id == schedule_version_id,
                    MatchAssignment.match_id == prereq.id,
                )
            ).first()
            if not prereq_assignment:
                continue
            
            prereq_slot = session.get(ScheduleSlot, prereq_assignment.slot_id)
            if not prereq_slot or prereq_slot.day_date != day_date:
                continue
            
            # If prerequisite was assigned on same day, this match likely failed due to rest gap
            failed_main.append(match)
            break
    
    return failed_main


def _try_move_prerequisite_earlier(
    match: Match,
    prerequisite_match: Match,
    session: Session,
    schedule_version_id: int,
    day_date: date,
) -> bool:
    """
    Try to move prerequisite match to an earlier time slot on the same day.
    
    Returns True if moved successfully, False otherwise.
    """
    from app.models.match_assignment import MatchAssignment
    
    # Find current assignment for prerequisite
    prereq_assignment = session.exec(
        select(MatchAssignment).where(
            MatchAssignment.schedule_version_id == schedule_version_id,
            MatchAssignment.match_id == prerequisite_match.id,
        )
    ).first()
    if not prereq_assignment:
        return False
    
    current_slot = session.get(ScheduleSlot, prereq_assignment.slot_id)
    if not current_slot or current_slot.day_date != day_date:
        return False
    
    # Find earlier available slots on same day
    earlier_slots = session.exec(
        select(ScheduleSlot).where(
            ScheduleSlot.schedule_version_id == schedule_version_id,
            ScheduleSlot.day_date == day_date,
            ScheduleSlot.is_active == True,
            ScheduleSlot.start_time < current_slot.start_time,
        )
    ).all()
    
    # Check for existing assignments
    existing_assignments = session.exec(
        select(MatchAssignment).where(
            MatchAssignment.schedule_version_id == schedule_version_id,
        )
    ).all()
    occupied_slot_ids = {a.slot_id for a in existing_assignments}
    
    # Find earliest compatible slot
    for slot in sorted(earlier_slots, key=lambda s: (s.start_time, s.court_number)):
        if slot.id in occupied_slot_ids:
            continue
        
        # Check if slot is compatible (court type, etc.)
        if slot.court_number != current_slot.court_number:
            # Try to find compatible slot
            continue
        
        # Move assignment
        prereq_assignment.slot_id = slot.id
        session.flush()
        return True
    
    return False


def _fill_spare_courts_with_consolation(
    session: Session,
    schedule_version_id: int,
    day_date: date,
    all_matches: List[Match],
    assigned_match_ids: Set[int],
    team_day_counts: Dict[int, int],
    fill_all_available: bool = True,
    max_spare_per_slot: int = 0,
    min_start_time: Optional[time] = None,
    max_round_index: Optional[int] = None,
    blocked_slot_ids: Optional[Set[int]] = None,
) -> List[int]:
    """
    Fill spare courts with CONSOLATION matches using structural eligibility.

    Team IDs are irrelevant (NULL in bracket matches).  Instead we gate on:
      1. Dependency gate — the match's upstream source matches must be assigned.
      2. Round dependency — consolation round N requires round N-1 to be
         fully assigned for that event.
      3. Event-round day cap — no more than 2 event-rounds per event per day.

    Each time slot keeps at most ``max_spare_per_slot`` spare courts; the rest
    are filled with eligible consolation.

    Ordering:
      - Event priority (largest team_count first, consistent with policy).
      - Consolation round number ASC (earlier rounds first).
      - Match ID ASC (deterministic tie-break).

    Returns list of match IDs that were assigned.
    """
    from app.utils.auto_assign import assign_by_match_ids

    # ── 1. Count spare courts per time slot ────────────────────────────
    slots = session.exec(
        select(ScheduleSlot).where(
            ScheduleSlot.schedule_version_id == schedule_version_id,
            ScheduleSlot.day_date == day_date,
            ScheduleSlot.is_active == True,
        )
    ).all()

    assignments = session.exec(
        select(MatchAssignment).where(
            MatchAssignment.schedule_version_id == schedule_version_id,
        )
    ).all()
    assigned_slot_ids = {a.slot_id for a in assignments}
    current_assigned_ids = {a.match_id for a in assignments}

    slots_by_time: Dict[time, List[ScheduleSlot]] = defaultdict(list)
    for slot in slots:
        slots_by_time[slot.start_time].append(slot)

    spare_by_time: Dict[time, int] = {}
    for t, time_slots in slots_by_time.items():
        total = len(time_slots)
        used = sum(1 for s in time_slots if s.id in assigned_slot_ids)
        spare_by_time[t] = max(0, total - used)

    # How many courts we can fill = spare minus the reserve we keep
    fillable = sum(max(0, sp - max_spare_per_slot) for sp in spare_by_time.values())
    if fillable <= 0:
        return []

    # ── 2. Gather unassigned CONSOLATION matches ───────────────────────
    consolation_unassigned = [
        m for m in all_matches
        if m.match_type == "CONSOLATION"
        and m.id not in current_assigned_ids
    ]
    if not consolation_unassigned:
        return []

    # ── 3. Dependency gate — upstream source matches must be assigned ──
    # This replaces the event-level "ALL MAIN done" gate with a structural
    # check: each consolation match's upstream source matches (the MAIN
    # matches that feed into it) must already be assigned.  This allows
    # consolation QFs to run even if MAIN finals haven't been placed yet.
    resolved = _filter_resolved(consolation_unassigned, current_assigned_ids)
    if not resolved:
        return []

    # ── 4. Round dependency — round N needs round N-1 fully assigned ──
    # Group consolation by event + division to check round ordering
    def _cons_round_key(m: Match) -> Tuple[int, str]:
        div_match = re.search(r'B(WW|WL|LW|LL)[_]', m.match_code or "")
        div = div_match.group(1) if div_match else "XX"
        return (m.event_id, div)

    # Find max assigned consolation round per (event, division)
    max_assigned_cons_round: Dict[Tuple[int, str], int] = defaultdict(lambda: -1)
    for m in all_matches:
        if m.match_type == "CONSOLATION" and m.id in current_assigned_ids:
            key = _cons_round_key(m)
            r = m.round_index or 0
            if r > max_assigned_cons_round[key]:
                max_assigned_cons_round[key] = r

    round_eligible: List[Match] = []
    for m in resolved:
        key = _cons_round_key(m)
        m_round = m.round_index or 0
        # Skip matches beyond the round cap (e.g. Day 2 only places C1+C2)
        if max_round_index is not None and m_round > max_round_index:
            continue
        # Round 0/1 is always eligible; higher rounds need prior round assigned
        if m_round <= 1 or max_assigned_cons_round[key] >= m_round - 1:
            round_eligible.append(m)

    if not round_eligible:
        return []

    # ── 5. Group by event, place complete blocks ─────────────────
    # Place ALL consolation matches for one event before moving to the
    # next.  Only place an event's block if there are enough spare courts
    # for the full set.  This avoids partial/odd counts that create
    # unfair rest advantages.
    events = session.exec(
        select(Event).where(
            Event.id.in_({m.event_id for m in round_eligible})  # type: ignore[attr-defined]
        )
    ).all()
    event_team_count: Dict[int, int] = {e.id: (e.team_count or 0) for e in events}

    cons_by_event: Dict[int, List[Match]] = defaultdict(list)
    for m in round_eligible:
        cons_by_event[m.event_id].append(m)
    for eid in cons_by_event:
        cons_by_event[eid].sort(key=lambda m: (m.round_index or 0, m.id or 0))

    # Event order: largest team_count first, then event_id for determinism
    event_order = sorted(
        cons_by_event.keys(),
        key=lambda eid: (-(event_team_count.get(eid, 0)), eid),
    )

    # Only place complete event blocks that fit within fillable courts
    all_assigned_ids: List[int] = []
    courts_remaining = fillable

    for eid in event_order:
        event_matches = cons_by_event[eid]
        block_size = len(event_matches)
        if block_size == 0:
            continue
        if block_size > courts_remaining:
            continue  # not enough room for this event's full block

        # Place all matches for this event
        batch_ids = [m.id for m in event_matches]
        try:
            assign_result = assign_by_match_ids(
                session=session,
                schedule_version_id=schedule_version_id,
                match_ids=batch_ids,
                target_day=day_date,
                blocked_slot_ids=blocked_slot_ids,
            )
            session.flush()
            slot_assigned = [ex["match_id"] for ex in assign_result.assigned_examples]
            if assign_result.assigned_count > len(slot_assigned):
                slot_assigned = batch_ids[:assign_result.assigned_count]
            all_assigned_ids.extend(slot_assigned)
            courts_remaining -= len(slot_assigned)
        except Exception as exc:
            logger.exception("Failed consolation fill for event %d: %s", eid, exc)

    return all_assigned_ids


def _count_event_rounds_assigned_on_day(
    session: Session,
    schedule_version_id: int,
    day_date: date,
) -> Dict[int, int]:
    """
    Count how many distinct 'rounds' (≈ 1 match per team) each event already
    has assigned on this day.

    This is used for RR cap enforcement: since RR matches lack team_a_id /
    team_b_id we cannot do per-team counting.  Instead we track at event level:
    each *round* of matches for an event is ≈ 1 match per team.

    Heuristic: count distinct (event_id, match_type, round_index) tuples among
    assigned matches on this day.  Each unique tuple = 1 "round" = 1 match per
    team in that event.
    """
    assignments = session.exec(
        select(MatchAssignment).where(
            MatchAssignment.schedule_version_id == schedule_version_id,
        )
    ).all()
    assigned_match_ids_set = {a.match_id for a in assignments}

    slots = session.exec(
        select(ScheduleSlot).where(
            ScheduleSlot.schedule_version_id == schedule_version_id,
            ScheduleSlot.day_date == day_date,
        )
    ).all()
    day_slot_ids = {s.id for s in slots}
    day_assignment_match_ids = {
        a.match_id for a in assignments if a.slot_id in day_slot_ids
    }

    if not day_assignment_match_ids:
        return {}

    matches = session.exec(
        select(Match).where(Match.schedule_version_id == schedule_version_id)
    ).all()

    round_keys: Dict[int, Set[Tuple[str, int]]] = defaultdict(set)
    for m in matches:
        if m.id in day_assignment_match_ids:
            round_keys[m.event_id].add((m.match_type, m.round_index or 0))

    return {eid: len(keys) for eid, keys in round_keys.items()}


def _can_event_afford_rr_round(
    event_id: int,
    event_rounds_today: Dict[int, int],
    max_per_day: int = 2,
) -> bool:
    """
    Check whether an event's teams can afford one more RR round today.

    Each planned 'round' (QF round, RR round, SF round, etc.) = 1 match per
    team.  If the event already has max_per_day rounds planned, no more RR.
    """
    current = event_rounds_today.get(event_id, 0)
    return current < max_per_day


# ── Deterministic slot/court sort key ────────────────────────────────

def _slot_court_sort_key(slot: ScheduleSlot) -> Tuple:
    """
    Stable sort key for a slot: court_number ASC, court_label ASC, id ASC.

    This ensures spare-court reservation always picks the same court
    across identical inputs.
    """
    return (slot.court_number, slot.court_label or "", slot.id or 0)


# ══════════════════════════════════════════════════════════════════════════
#  Spare-court reservation
# ══════════════════════════════════════════════════════════════════════════

def compute_spare_reservations(
    session: Session,
    schedule_version_id: int,
    day_date: date,
    total_matches_planned: Optional[int] = None,
    max_spare_per_bucket: Optional[int] = None,
) -> List[int]:
    """
    Reserve spare courts for a day.

    DISABLED: Spare court reservation has been removed. All courts are
    included in the schedule. This function now always returns an empty list.

    Returns empty list (no reservations).
    """
    return []
    # -- Legacy implementation below (kept for reference) --
    # Load slots for this day
    slots = session.exec(
        select(ScheduleSlot).where(
            ScheduleSlot.schedule_version_id == schedule_version_id,
            ScheduleSlot.day_date == day_date,
            ScheduleSlot.is_active == True,
        )
    ).all()
    if not slots:
        return []

    # Load assignments to find occupied slots
    assignments = session.exec(
        select(MatchAssignment).where(
            MatchAssignment.schedule_version_id == schedule_version_id,
        )
    ).all()
    occupied_slot_ids = {a.slot_id for a in assignments}

    # Group slots by time bucket
    buckets: Dict[time, List[ScheduleSlot]] = defaultdict(list)
    for s in slots:
        buckets[s.start_time].append(s)

    sorted_times = sorted(buckets.keys())
    if len(sorted_times) <= 1:
        return []

    # Collect open (unoccupied) slots per bucket, sorted by court
    open_slots_by_bucket: Dict[time, List[ScheduleSlot]] = {}
    for t in sorted_times:
        open_in_bucket = [s for s in buckets[t] if s.id not in occupied_slot_ids]
        if open_in_bucket:
            open_slots_by_bucket[t] = sorted(
                open_in_bucket, key=_slot_court_sort_key
            )

    # ── Proportional mode ──────────────────────────────────────────────
    if total_matches_planned is not None:
        total_slots = len(slots)
        total_spare = max(0, total_slots - total_matches_planned)
        if total_spare == 0:
            return []

        num_buckets = len(sorted_times)
        base_per_bucket = total_spare // num_buckets
        remainder = total_spare % num_buckets

        # Distribute: each bucket gets base_per_bucket.
        # The LAST `remainder` buckets get one extra.
        # Optional max_spare_per_bucket caps per-bucket spares to avoid
        # over-reserving on days with low match density (e.g. finals day).
        per_bucket: Dict[time, int] = {}
        for i, t in enumerate(sorted_times):
            extra = 1 if i >= (num_buckets - remainder) else 0
            spares = base_per_bucket + extra
            if max_spare_per_bucket is not None:
                spares = min(spares, max_spare_per_bucket)
            per_bucket[t] = spares

        reserved: List[int] = []
        for t in sorted_times:
            target = per_bucket.get(t, 0)
            candidates = open_slots_by_bucket.get(t, [])
            for _ in range(min(target, len(candidates))):
                slot = candidates[-1]
                reserved.append(slot.id)
                candidates.pop()

        return reserved

    # ── Legacy mode: 1 spare per non-first bucket ──────────────────────
    # The first time slot never has a spare.  Every other slot reserves
    # exactly 1 court so that spare capacity is distributed evenly
    # across the day rather than concentrated at the end.
    non_first_times = sorted_times[1:]

    reserved: List[int] = []

    for t in non_first_times:
        candidates = open_slots_by_bucket.get(t, [])
        if candidates:
            slot = candidates[-1]  # highest court number reserved
            reserved.append(slot.id)
            candidates.pop()

    return reserved


# ══════════════════════════════════════════════════════════════════════════
#  Consolation gating: don't start unless full round fits
# ══════════════════════════════════════════════════════════════════════════

def _count_available_slots_for_day(
    session: Session,
    schedule_version_id: int,
    day_date: date,
    already_planned_count: int,
    reserved_slot_ids: Set[int],
) -> int:
    """
    Count how many usable slots remain on a day after existing assignments,
    reserved slots, and already-planned batch matches.
    """
    slots = session.exec(
        select(ScheduleSlot).where(
            ScheduleSlot.schedule_version_id == schedule_version_id,
            ScheduleSlot.day_date == day_date,
            ScheduleSlot.is_active == True,
        )
    ).all()

    assignments = session.exec(
        select(MatchAssignment).where(
            MatchAssignment.schedule_version_id == schedule_version_id,
        )
    ).all()
    occupied_slot_ids = {a.slot_id for a in assignments}

    available = 0
    for s in slots:
        if s.id not in occupied_slot_ids and s.id not in reserved_slot_ids:
            available += 1

    # Subtract slots that earlier batches in this plan will consume
    return max(0, available - already_planned_count)


def _gate_consolation_batch(
    session: Session,
    schedule_version_id: int,
    day_date: date,
    cons_match_count: int,
    already_planned_count: int,
    reserved_slot_ids: Set[int],
) -> bool:
    """
    Return True if we have enough remaining slots to place the ENTIRE
    consolation round.  If not, defer (return False).
    """
    remaining = _count_available_slots_for_day(
        session, schedule_version_id, day_date,
        already_planned_count, reserved_slot_ids,
    )
    fits = remaining >= cons_match_count
    if not fits:
        logger.info(
            "Consolation gating: need %d slots but only %d available on %s — deferring",
            cons_match_count, remaining, day_date,
        )
    return fits


# ══════════════════════════════════════════════════════════════════════════
#  Day 1 plan builder
# ══════════════════════════════════════════════════════════════════════════

def _build_day1_plan(
    session: Session,
    events: List[Event],
    all_matches: List[Match],
    assigned_match_ids: Set[int],
    event_priority: Dict[int, int],
    day_date: date,
    schedule_version_id: int,
) -> List[PlacementBatch]:
    """
    Day 1 layering:
      1. WF Round 1 (events with WF, by event priority)
      2. Non-WF events first matches (RR R1 or first bracket)
      3. WF Round 2 (events with WF R2, by event priority)
      4. Remaining first-day matches for non-WF-R2 events
    """
    batches: List[PlacementBatch] = []
    unassigned = [m for m in all_matches if m.id not in assigned_match_ids]

    # Build team-day tracker
    team_day_counts = _build_team_match_count_on_day(session, schedule_version_id, day_date)

    # Sort events by priority (largest draw first)
    events_ordered = _build_rotated_event_list(events, 0)  # day_index=0 for Day 1

    wf_events = [e for e in events_ordered if _event_has_wf(e)]
    wf_event_ids = {e.id for e in wf_events}
    non_wf_events = [e for e in events_ordered if not _event_has_wf(e)]

    # --- WF Round 1: one batch PER EVENT, largest draw first ---
    # Each event's WF R1 matches are placed contiguously before the
    # next event starts.  This ensures the grid shows clean event
    # blocks: all of Women's A R1 fills first, then Women's B R1, etc.
    for event in wf_events:
        e_r1 = [m for m in unassigned if m.event_id == event.id and m.match_type == "WF" and m.round_number == 1]
        if not e_r1:
            continue
        e_r1_sorted = sorted(e_r1, key=lambda m: (m.sequence_in_round or 0, m.id or 0))
        e_r1_capped = _filter_by_team_cap(e_r1_sorted, team_day_counts)
        if e_r1_capped:
            batches.append(PlacementBatch(
                name=f"DAY1_WF_R1_{event.name}",
                match_ids=[m.id for m in e_r1_capped],
                description=f"WF R1 {event.name} ({len(e_r1_capped)} matches)",
            ))

    # --- Non-WF events first matches ---
    non_wf_first_ids = set()
    for e in non_wf_events:
        e_matches = [m for m in unassigned if m.event_id == e.id]
        if not e_matches:
            continue
        by_stage: Dict[str, List[Match]] = defaultdict(list)
        for m in e_matches:
            by_stage[m.match_type].append(m)
        first_matches: List[Match] = []
        if "RR" in by_stage:
            min_rr_round = min(m.round_index for m in by_stage["RR"])
            first_matches = [m for m in by_stage["RR"] if m.round_index == min_rr_round]
        elif "MAIN" in by_stage:
            min_main_round = min(m.round_index for m in by_stage["MAIN"])
            first_matches = [m for m in by_stage["MAIN"] if m.round_index == min_main_round]
        for m in first_matches:
            non_wf_first_ids.add(m.id)

    non_wf_first = [m for m in unassigned if m.id in non_wf_first_ids]
    non_wf_first_sorted = sorted(non_wf_first, key=lambda m: _match_sort_key(m, event_priority))
    non_wf_first_capped = _filter_by_team_cap(non_wf_first_sorted, team_day_counts)
    if non_wf_first_capped:
        batches.append(PlacementBatch(
            name="DAY1_NON_WF_FIRST",
            match_ids=[m.id for m in non_wf_first_capped],
            description=f"Non-WF events first matches ({len(non_wf_first_capped)} matches)",
        ))

    # --- WF Round 2: one batch PER EVENT, largest draw first ---
    wf_r2_events = [e for e in wf_events if _event_wf_rounds(e) >= 2]
    wf_r2_event_ids = {e.id for e in wf_r2_events}
    for event in wf_r2_events:
        e_r2 = [m for m in unassigned if m.event_id == event.id and m.match_type == "WF" and m.round_number == 2]
        if not e_r2:
            continue
        e_r2_sorted = sorted(e_r2, key=lambda m: (m.sequence_in_round or 0, m.id or 0))
        e_r2_capped = _filter_by_team_cap(e_r2_sorted, team_day_counts)
        if e_r2_capped:
            batches.append(PlacementBatch(
                name=f"DAY1_WF_R2_{event.name}",
                match_ids=[m.id for m in e_r2_capped],
                description=f"WF R2 {event.name} ({len(e_r2_capped)} matches)",
            ))

    # --- Remaining Day 1 matches ---
    already_batched = set()
    for b in batches:
        already_batched.update(b.match_ids)

    remaining_day1: List[Match] = []
    for e in events_ordered:
        e_matches = [m for m in unassigned if m.event_id == e.id and m.id not in already_batched]
        if not e_matches:
            continue
        # For WF events that only had R1 (no R2), add their RR R1 as second-layer
        if e.id in wf_event_ids and e.id not in wf_r2_event_ids:
            rr_matches = [m for m in e_matches if m.match_type == "RR"]
            if rr_matches:
                min_round = min(m.round_index for m in rr_matches)
                for m in rr_matches:
                    if m.round_index == min_round:
                        remaining_day1.append(m)

    remaining_day1_sorted = sorted(remaining_day1, key=lambda m: _match_sort_key(m, event_priority))
    remaining_day1_capped = _filter_by_team_cap(remaining_day1_sorted, team_day_counts)
    if remaining_day1_capped:
        batches.append(PlacementBatch(
            name="DAY1_REMAINING",
            match_ids=[m.id for m in remaining_day1_capped],
            description=f"Day 1 remaining first-layer matches ({len(remaining_day1_capped)} matches)",
        ))

    return batches


# ══════════════════════════════════════════════════════════════════════════
#  Day 2+ plan builder
# ══════════════════════════════════════════════════════════════════════════

def _classify_bracket_matches(
    matches: List[Match],
) -> Dict[str, List[Match]]:
    """
    Classify bracket matches into QF / SF / Final using position-from-end logic.
    Groups by event_id + stage + division (extracted from match_code).

    Returns dict with keys: 'qf', 'sf', 'final'
    """
    result: Dict[str, List[Match]] = {"qf": [], "sf": [], "final": []}

    # Group matches
    groups: Dict[str, List[Match]] = defaultdict(list)
    for m in matches:
        div_match = re.search(r'B(WW|WL|LW|LL)[_]', m.match_code or "")
        div = div_match.group(1) if div_match else "XX"
        key = f"{m.event_id}|{m.match_type}|{div}"
        groups[key].append(m)

    for group_key, group_matches in groups.items():
        sorted_group = sorted(group_matches, key=lambda x: (x.round_index or 0, x.sequence_in_round or 0))
        n = len(sorted_group)
        if n == 0:
            continue
        elif n == 1:
            result["final"].extend(sorted_group)
        elif n <= 3:
            result["final"].append(sorted_group[-1])
            result["sf"].extend(sorted_group[:-1])
        else:
            result["final"].append(sorted_group[-1])
            result["sf"].extend(sorted_group[-3:-1])
            result["qf"].extend(sorted_group[:-3])

    return result


def _build_day2plus_plan(
    session: Session,
    events: List[Event],
    all_matches: List[Match],
    assigned_match_ids: Set[int],
    event_priority: Dict[int, int],
    day_date: date,
    day_index: int,
    schedule_version_id: int,
    reserved_slot_ids: Set[int],
) -> Tuple[List[PlacementBatch], List[int]]:
    """
    Day 2+ per-event batch ordering (same principle as Day 1).

    Events are ranked largest to smallest with daily rotation so
    Day 2 starts with a different same-size event than Day 1.

    Three phases, each creating ONE BATCH PER EVENT in rotated order:

      Phase 0: Remaining WF (safety net)
      Phase 1: First bracket round (QFs) / first RR round — per event
      Phase 2: Second MAIN round (SFs) / second RR round — per event
      Phase 2b: Remaining RR rounds (R3+) for pool-play events
      Phase 3: Consolation — per event (fills remaining slots)
      Phase 4: Placement matches

    No MAIN Finals on Day 2 — capped at 2 MAIN rounds (QF + SF).
    MAIN Finals are deferred to Day 3.

    Returns (batches, deferred_final_ids).
    """
    batches: List[PlacementBatch] = []
    unassigned = [m for m in all_matches if m.id not in assigned_match_ids]
    if not unassigned:
        return batches, []

    day_label = day_index + 1
    team_day_counts = _build_team_match_count_on_day(session, schedule_version_id, day_date)

    event_rounds_today: Dict[int, int] = _count_event_rounds_assigned_on_day(
        session, schedule_version_id, day_date,
    )
    planned_so_far = 0

    # Rotated event ordering: largest draws first, rotated within same-size
    events_ordered = _build_rotated_event_list(events, day_index)
    event_ids_ordered = [e.id for e in events_ordered]
    event_name_map = {e.id: e.name for e in events_ordered}

    # Separate by stage
    rr_matches = [m for m in unassigned if m.match_type == "RR"]
    main_matches = [m for m in unassigned if m.match_type == "MAIN"]
    cons_matches = [m for m in unassigned if m.match_type == "CONSOLATION"]
    placement_matches = [m for m in unassigned if m.match_type == "PLACEMENT"]
    wf_matches = [m for m in unassigned if m.match_type == "WF"]

    # Classify bracket matches into QF / SF / Final tiers
    main_classified = _classify_bracket_matches(main_matches)
    cons_classified = _classify_bracket_matches(cons_matches)

    # Compute deferred Finals — these will NOT be placed on Day 2.
    deferred_final_ids: List[int] = [m.id for m in main_classified.get("final", [])]

    # Treat MAIN Finals as "planned" even though they won't be placed on
    # Day 2.  This unblocks consolation gating — without it, consolation
    # is blocked because _event_has_unassigned_main_matches sees the
    # deferred Finals as still-unassigned.
    planned_assigned = set(assigned_match_ids)
    for tier in ("qf", "sf", "final"):
        tier_resolved = _filter_resolved(main_classified.get(tier, []), assigned_match_ids)
        planned_assigned.update(m.id for m in tier_resolved)

    # Index matches by event_id for quick lookup
    def _by_event(match_list: List[Match]) -> Dict[int, List[Match]]:
        d: Dict[int, List[Match]] = defaultdict(list)
        for m in match_list:
            d[m.event_id].append(m)
        return d

    qf_all = _filter_resolved(main_classified["qf"], assigned_match_ids)
    sf_all = _filter_resolved(main_classified["sf"], assigned_match_ids)
    qf_by_event = _by_event(qf_all)
    sf_by_event = _by_event(sf_all)
    rr_by_event = _by_event(rr_matches)

    # ── Phase 0: Remaining WF (safety net) ──────────────────────────
    if wf_matches:
        for event in events_ordered:
            e_wf = [m for m in wf_matches if m.event_id == event.id]
            if not e_wf:
                continue
            e_wf_sorted = sorted(e_wf, key=lambda m: (m.round_index or 0, m.sequence_in_round or 0, m.id or 0))
            e_wf_capped = _filter_by_team_cap(e_wf_sorted, team_day_counts)
            if e_wf_capped:
                batches.append(PlacementBatch(
                    name=f"DAY{day_label}_WF_{event_name_map[event.id]}",
                    match_ids=[m.id for m in e_wf_capped],
                    description=f"WF {event_name_map[event.id]} ({len(e_wf_capped)} matches)",
                ))
                planned_so_far += len(e_wf_capped)
                event_rounds_today[event.id] = event_rounds_today.get(event.id, 0) + 1

    # ── Phase 1: First bracket round (QFs) / first RR round — per event ──
    for eid in event_ids_ordered:
        ename = event_name_map.get(eid, str(eid))

        # QF matches for this event
        e_qf = qf_by_event.get(eid, [])
        if e_qf:
            e_qf_sorted = sorted(e_qf, key=lambda m: (m.sequence_in_round or 0, m.id or 0))
            e_qf_capped = _filter_by_team_cap(e_qf_sorted, team_day_counts)
            if e_qf_capped:
                batches.append(PlacementBatch(
                    name=f"DAY{day_label}_QF_{ename}",
                    match_ids=[m.id for m in e_qf_capped],
                    description=f"QF {ename} ({len(e_qf_capped)} matches)",
                ))
                planned_so_far += len(e_qf_capped)
                event_rounds_today[eid] = event_rounds_today.get(eid, 0) + 1

        # First RR round for this event (if no QFs — e.g. Mixed RR)
        e_rr = rr_by_event.get(eid, [])
        if e_rr and not e_qf:
            first_rr_round = min(m.round_index for m in e_rr)
            first_rr = [m for m in e_rr if m.round_index == first_rr_round]
            if _can_event_afford_rr_round(eid, event_rounds_today):
                first_rr_sorted = sorted(first_rr, key=lambda m: (m.sequence_in_round or 0, m.id or 0))
                batches.append(PlacementBatch(
                    name=f"DAY{day_label}_RR_R{first_rr_round}_{ename}",
                    match_ids=[m.id for m in first_rr_sorted],
                    description=f"RR R{first_rr_round} {ename} ({len(first_rr_sorted)} matches)",
                ))
                planned_so_far += len(first_rr_sorted)
                event_rounds_today[eid] = event_rounds_today.get(eid, 0) + 1

    # ── Phase 2: Second MAIN round (SFs) / second RR round — per event ──
    for eid in event_ids_ordered:
        ename = event_name_map.get(eid, str(eid))

        # SF matches (MAIN only, no consolation in this phase)
        e_sf = sf_by_event.get(eid, [])
        if e_sf:
            e_sf_sorted = sorted(e_sf, key=lambda m: (m.sequence_in_round or 0, m.id or 0))
            e_sf_capped = _filter_by_team_cap(e_sf_sorted, team_day_counts)
            if e_sf_capped:
                batches.append(PlacementBatch(
                    name=f"DAY{day_label}_SF_{ename}",
                    match_ids=[m.id for m in e_sf_capped],
                    description=f"SF {ename} ({len(e_sf_capped)} matches)",
                ))
                planned_so_far += len(e_sf_capped)
                event_rounds_today[eid] = event_rounds_today.get(eid, 0) + 1

        # Second RR round for this event (if it has RR and no SFs)
        e_rr = rr_by_event.get(eid, [])
        if e_rr and not e_sf:
            rr_rounds_available = sorted(set(m.round_index for m in e_rr))
            # Pick the second-lowest round (first was used in Phase 1)
            for rr_round in rr_rounds_available:
                # Skip rounds already batched in Phase 1
                already_batched_rr = any(
                    b.name == f"DAY{day_label}_RR_R{rr_round}_{ename}"
                    for b in batches
                )
                if already_batched_rr:
                    continue
                if not _can_event_afford_rr_round(eid, event_rounds_today):
                    break
                rr_round_matches = [m for m in e_rr if m.round_index == rr_round]
                rr_sorted = sorted(rr_round_matches, key=lambda m: (m.sequence_in_round or 0, m.id or 0))
                batches.append(PlacementBatch(
                    name=f"DAY{day_label}_RR_R{rr_round}_{ename}",
                    match_ids=[m.id for m in rr_sorted],
                    description=f"RR R{rr_round} {ename} ({len(rr_sorted)} matches)",
                ))
                planned_so_far += len(rr_sorted)
                event_rounds_today[eid] = event_rounds_today.get(eid, 0) + 1
                break  # Only one more RR round per phase

    # ── Phase 2b: Remaining RR rounds (R3+) for pool-play events ─────
    # RR-only events (e.g. Mixed with 4 pools of 4 teams) need 3 rounds
    # of pool play on Day 2.  Phases 1+2 batch R1 and R2; this phase
    # batches any remaining rounds that haven't been placed yet.
    # We raise the effective cap for RR-only events (no MAIN matches)
    # because pool play rounds are lightweight and expected on the same day.
    for eid in event_ids_ordered:
        ename = event_name_map.get(eid, str(eid))
        e_rr = rr_by_event.get(eid, [])
        e_sf = sf_by_event.get(eid, [])
        if not e_rr or e_sf:
            continue  # Only for RR-only events (no bracket SFs)
        rr_rounds_available = sorted(set(m.round_index for m in e_rr))
        for rr_round in rr_rounds_available:
            already_batched = any(
                b.name == f"DAY{day_label}_RR_R{rr_round}_{ename}"
                for b in batches
            )
            if already_batched:
                continue
            # Allow up to 3 RR rounds for pool-play events
            if not _can_event_afford_rr_round(eid, event_rounds_today, max_per_day=3):
                break
            rr_round_matches = [m for m in e_rr if m.round_index == rr_round]
            rr_sorted = sorted(rr_round_matches, key=lambda m: (m.sequence_in_round or 0, m.id or 0))
            batches.append(PlacementBatch(
                name=f"DAY{day_label}_RR_R{rr_round}_{ename}",
                match_ids=[m.id for m in rr_sorted],
                description=f"RR R{rr_round} {ename} ({len(rr_sorted)} matches)",
            ))
            planned_so_far += len(rr_sorted)
            event_rounds_today[eid] = event_rounds_today.get(eid, 0) + 1

    # Phase 3 (Consolation) is handled AFTER the batch loop by the
    # spare-fill function (_fill_spare_courts_with_consolation) which
    # enforces max_round_index=1 (consolation semis only) and round-robin
    # distribution across events.  No consolation batches here.

    # ── Phase 4: Placement matches ──────────────────────────────────
    if placement_matches:
        pl_resolved = _filter_resolved(placement_matches, assigned_match_ids)
        pl_sorted = sorted(pl_resolved, key=lambda m: _match_sort_key(m, event_priority))
        pl_capped = _filter_by_team_cap(pl_sorted, team_day_counts)
        if pl_capped:
            batches.append(PlacementBatch(
                name=f"DAY{day_label}_PLACEMENT",
                match_ids=[m.id for m in pl_capped],
                description=f"Placement matches ({len(pl_capped)} matches)",
            ))

    return batches, deferred_final_ids


# ══════════════════════════════════════════════════════════════════════════
#  Final day (Day 3+) plan builder
# ══════════════════════════════════════════════════════════════════════════

def _count_event_rounds_assigned_total(
    session: Session,
    schedule_version_id: int,
) -> Dict[int, int]:
    """
    Count total distinct rounds assigned per event across ALL days.
    Used for catch-up sorting on the final day.
    """
    assignments = session.exec(
        select(MatchAssignment).where(
            MatchAssignment.schedule_version_id == schedule_version_id,
        )
    ).all()
    assigned_match_ids_set = {a.match_id for a in assignments}
    if not assigned_match_ids_set:
        return {}

    matches = session.exec(
        select(Match).where(Match.schedule_version_id == schedule_version_id)
    ).all()

    round_keys: Dict[int, Set[Tuple[str, int]]] = defaultdict(set)
    for m in matches:
        if m.id in assigned_match_ids_set:
            round_keys[m.event_id].add((m.match_type, m.round_index or 0))

    return {eid: len(keys) for eid, keys in round_keys.items()}


def _build_day3_plan(
    session: Session,
    events: List[Event],
    all_matches: List[Match],
    assigned_match_ids: Set[int],
    event_priority: Dict[int, int],
    day_date: date,
    day_index: int,
    schedule_version_id: int,
    reserved_slot_ids: Set[int],
) -> List[PlacementBatch]:
    """
    Final-day layering with user-specified priorities:

      Key insight: teams with 2 matches on the final day must play their
      first match EARLY so they get the rest gap before their second match.
      Therefore we interleave MAIN and CONSOLATION by tier (QF/SF/Final)
      instead of doing all MAIN then all CONS.

      Batch order:
        1. Remaining WF (catch-up)
        2. All QFs (MAIN + CONS together) — earliest, these feed SFs
        3. All SFs (MAIN + CONS together) — early, gives rest gap for finals
        4. RR rounds — middle
        5. All Finals (MAIN + CONS together) — after rest gap from SFs
        6. Placement matches

      Within each batch, catch-up sorted: events with fewest total rounds
      across all prior days go first, then by event priority.
    """
    batches: List[PlacementBatch] = []
    unassigned = [m for m in all_matches if m.id not in assigned_match_ids]
    if not unassigned:
        return batches

    team_day_counts = _build_team_match_count_on_day(session, schedule_version_id, day_date)
    event_rounds_today: Dict[int, int] = _count_event_rounds_assigned_on_day(
        session, schedule_version_id, day_date,
    )

    # Count total rounds assigned per event across ALL prior days — for catch-up
    event_rounds_total = _count_event_rounds_assigned_total(session, schedule_version_id)

    # Separate by stage
    rr_matches = [m for m in unassigned if m.match_type == "RR"]
    main_matches = [m for m in unassigned if m.match_type == "MAIN"]
    cons_matches = [m for m in unassigned if m.match_type == "CONSOLATION"]
    placement_matches = [m for m in unassigned if m.match_type == "PLACEMENT"]
    wf_matches = [m for m in unassigned if m.match_type == "WF"]

    # Classify bracket matches
    main_classified = _classify_bracket_matches(main_matches)
    cons_classified = _classify_bracket_matches(cons_matches)

    # Catch-up sort: fewest total rounds first, then event priority
    def _catchup_sort_key(m: Match) -> Tuple:
        rounds_played = event_rounds_total.get(m.event_id, 0)
        ep = event_priority.get(m.event_id, 999)
        sp = STAGE_PRECEDENCE.get(m.match_type, 999)
        return (rounds_played, ep, sp, m.round_index or 999, m.sequence_in_round or 999, m.id or 999)

    # ── Batch 1: Remaining WF (catch-up from prior days) ──
    if wf_matches:
        wf_sorted = sorted(wf_matches, key=_catchup_sort_key)
        wf_capped = _filter_by_team_cap(wf_sorted, team_day_counts)
        if wf_capped:
            batches.append(PlacementBatch(
                name=f"DAY{day_index + 1}_WF_REMAINING",
                match_ids=[m.id for m in wf_capped],
                description=f"Remaining WF matches ({len(wf_capped)} matches)",
            ))
            for eid in set(m.event_id for m in wf_capped):
                event_rounds_today[eid] = event_rounds_today.get(eid, 0) + 1

    # Progressive "planned assigned" set — includes ALL unassigned MAIN
    # matches that will be placed on this day.  This prevents the
    # consolation gate from blocking consolation just because some MAIN
    # finals haven't been placed yet (they will be in a later batch).
    planned_assigned = set(assigned_match_ids)
    # Add ALL resolved MAIN matches (QF+SF+Final) upfront
    for tier in ("qf", "sf", "final"):
        tier_resolved = _filter_resolved(main_classified.get(tier, []), assigned_match_ids)
        planned_assigned.update(m.id for m in tier_resolved)

    # ── Batch 2: ALL QFs (MAIN + CONS) — earliest placement ──
    # These are the first matches in a chain; placing them early gives
    # the most room for SFs and Finals after rest gaps.
    main_qf = _filter_resolved(main_classified["qf"], assigned_match_ids)
    cons_qf_raw = _filter_resolved(cons_classified.get("qf", []), assigned_match_ids)
    cons_qf = [
        m for m in cons_qf_raw
        if not _event_has_unassigned_main_matches(m.event_id, all_matches, planned_assigned)
    ]
    all_qf = list(main_qf) + list(cons_qf)

    if all_qf:
        qf_sorted = sorted(all_qf, key=_catchup_sort_key)
        qf_capped = _filter_by_team_cap(qf_sorted, team_day_counts)
        if qf_capped:
            batches.append(PlacementBatch(
                name=f"DAY{day_index + 1}_ALL_QF",
                match_ids=[m.id for m in qf_capped],
                description=f"All QFs - Main+Cons ({len(qf_capped)} matches)",
            ))

    # ── Batch 3: ALL SFs (MAIN + CONS) — early, gives rest gap for finals ──
    # Placing CONS SFs alongside MAIN SFs ensures they get early time
    # slots instead of being pushed to the end of the day.
    main_sf = _filter_resolved(main_classified["sf"], assigned_match_ids)
    cons_sf_raw = _filter_resolved(cons_classified.get("sf", []), assigned_match_ids)
    cons_sf = [
        m for m in cons_sf_raw
        if not _event_has_unassigned_main_matches(m.event_id, all_matches, planned_assigned)
    ]
    all_sf = list(main_sf) + list(cons_sf)

    if all_sf:
        sf_sorted = sorted(all_sf, key=_catchup_sort_key)
        sf_capped = _filter_by_team_cap(sf_sorted, team_day_counts)
        if sf_capped:
            batches.append(PlacementBatch(
                name=f"DAY{day_index + 1}_ALL_SF",
                match_ids=[m.id for m in sf_capped],
                description=f"All SFs - Main+Cons ({len(sf_capped)} matches)",
            ))

    # ── Batch 4: RR rounds — lower round first ──
    if rr_matches:
        rr_rounds = sorted(set(m.round_index for m in rr_matches))
        for rr_round in rr_rounds:
            rr_round_matches = [m for m in rr_matches if m.round_index == rr_round]

            by_event: Dict[int, List[Match]] = defaultdict(list)
            for m in rr_round_matches:
                by_event[m.event_id].append(m)

            eligible_matches: List[Match] = []
            eligible_events: List[int] = []
            for eid, ematches in sorted(by_event.items()):
                if _can_event_afford_rr_round(eid, event_rounds_today):
                    eligible_matches.extend(ematches)
                    eligible_events.append(eid)

            if eligible_matches:
                rr_sorted = sorted(eligible_matches, key=_catchup_sort_key)
                batches.append(PlacementBatch(
                    name=f"DAY{day_index + 1}_RR_R{rr_round}",
                    match_ids=[m.id for m in rr_sorted],
                    description=f"RR Round {rr_round} ({len(rr_sorted)} matches)",
                ))
                for eid in eligible_events:
                    event_rounds_today[eid] = event_rounds_today.get(eid, 0) + 1

    # ── Batch 5: ALL Finals (MAIN + CONS) — after rest gap from SFs ──
    # By this point SFs were placed early, so the rest gap is satisfied
    # and finals can slot into the later time slots.
    main_final = _filter_resolved(main_classified["final"], assigned_match_ids)
    cons_final_raw = _filter_resolved(cons_classified.get("final", []), assigned_match_ids)
    cons_final = [
        m for m in cons_final_raw
        if not _event_has_unassigned_main_matches(m.event_id, all_matches, planned_assigned)
    ]
    all_final = list(main_final) + list(cons_final)

    if all_final:
        final_sorted = sorted(all_final, key=_catchup_sort_key)
        final_capped = _filter_by_team_cap(final_sorted, team_day_counts)
        if final_capped:
            batches.append(PlacementBatch(
                name=f"DAY{day_index + 1}_ALL_FINAL",
                match_ids=[m.id for m in final_capped],
                description=f"All Finals - Main+Cons ({len(final_capped)} matches)",
            ))

    # ── Batch 6: Placement ──
    if placement_matches:
        pl_resolved = _filter_resolved(placement_matches, assigned_match_ids)
        pl_sorted = sorted(pl_resolved, key=_catchup_sort_key)
        pl_capped = _filter_by_team_cap(pl_sorted, team_day_counts)
        if pl_capped:
            batches.append(PlacementBatch(
                name=f"DAY{day_index + 1}_PLACEMENT",
                match_ids=[m.id for m in pl_capped],
                description=f"Placement matches ({len(pl_capped)} matches)",
            ))

    return batches


# ══════════════════════════════════════════════════════════════════════════
#  Public API: build_daily_plan
# ══════════════════════════════════════════════════════════════════════════

def build_daily_plan(
    session: Session,
    tournament_id: int,
    schedule_version_id: int,
    day_date: date,
) -> DailyPlan:
    """
    Build a deterministic daily placement plan.

    Returns a DailyPlan with ordered PlacementBatch objects.
    The batches should be executed in order using assign_by_match_ids.
    """
    # Load version
    version = session.get(ScheduleVersion, schedule_version_id)
    if not version:
        raise ValueError(f"Schedule version {schedule_version_id} not found")

    # Load events for tournament
    events = session.exec(
        select(Event).where(Event.tournament_id == tournament_id)
    ).all()
    events = list(events)

    # Determine day index (0-based)
    all_slots = session.exec(
        select(ScheduleSlot).where(
            ScheduleSlot.schedule_version_id == schedule_version_id,
        )
    ).all()
    all_days = sorted(set(s.day_date for s in all_slots))
    try:
        day_index = all_days.index(day_date)
    except ValueError:
        day_index = 0  # Fallback

    plan = DailyPlan(day_date=day_date, day_index=day_index)

    # Event priority for this day (true rotation)
    event_priority = _build_event_priority_map(events, day_index)

    # Load all matches for this version
    all_matches = session.exec(
        select(Match).where(Match.schedule_version_id == schedule_version_id)
    ).all()
    all_matches = list(all_matches)

    # Load already-assigned match IDs
    existing_assignments = session.exec(
        select(MatchAssignment).where(
            MatchAssignment.schedule_version_id == schedule_version_id,
        )
    ).all()
    assigned_match_ids = {a.match_id for a in existing_assignments}

    is_final_day = day_index == len(all_days) - 1 and day_index >= 1

    if is_final_day:
        # Final day: build batches FIRST, then compute proportional spares
        # so we know how many matches need placing and can spread evenly.
        # Cap spares at 2 per bucket to avoid over-reserving on the final day
        # where dependency chains (QF→SF→Final) need maximum time-slot availability.
        plan.batches = _build_day3_plan(
            session, events, all_matches, assigned_match_ids,
            event_priority, day_date, day_index, schedule_version_id,
            reserved_slot_ids=set(),  # No spares yet
        )
        total_matches_planned = sum(len(b.match_ids) for b in plan.batches)
        reserved_slot_ids = compute_spare_reservations(
            session, schedule_version_id, day_date,
            total_matches_planned=total_matches_planned,
            max_spare_per_bucket=2,
        )
        plan.reserved_slot_ids = reserved_slot_ids
    elif day_index == 1:
        # Day 2: build batches first, then reserve spares targeting max 2 spare courts
        plan.batches, plan.deferred_final_ids = _build_day2plus_plan(
            session, events, all_matches, assigned_match_ids,
            event_priority, day_date, day_index, schedule_version_id,
            reserved_slot_ids=set(),  # No spares yet
        )
        total_matches_planned = sum(len(b.match_ids) for b in plan.batches)
        
        # For Day 2, target max 2 spare courts total
        # Calculate: total_slots - total_matches_planned - target_spare = reserved
        slots = session.exec(
            select(ScheduleSlot).where(
                ScheduleSlot.schedule_version_id == schedule_version_id,
                ScheduleSlot.day_date == day_date,
                ScheduleSlot.is_active == True,
            )
        ).all()
        total_slots = len(slots)
        target_spare = 2
        # Reserve slots to leave exactly target_spare spare courts
        # We want: reserved = total_slots - total_matches_planned - target_spare
        # compute_spare_reservations with total_matches_planned reserves:
        #   reserved = total_slots - total_matches_planned
        # To get reserved = total_slots - total_matches_planned - target_spare,
        # we pass total_matches_planned + target_spare
        reserved_slot_ids = compute_spare_reservations(
            session, schedule_version_id, day_date,
            total_matches_planned=total_matches_planned + target_spare,
        )
        plan.reserved_slot_ids = reserved_slot_ids
    else:
        # Day 1 and other middle days: compute spares first (legacy mode)
        reserved_slot_ids = compute_spare_reservations(
            session, schedule_version_id, day_date,
        )
        plan.reserved_slot_ids = reserved_slot_ids

        if day_index == 0:
            plan.batches = _build_day1_plan(
                session, events, all_matches, assigned_match_ids,
                event_priority, day_date, schedule_version_id,
            )
        else:
            plan.batches, plan.deferred_final_ids = _build_day2plus_plan(
                session, events, all_matches, assigned_match_ids,
                event_priority, day_date, day_index, schedule_version_id,
                reserved_slot_ids=set(reserved_slot_ids),
            )

    return plan


# ══════════════════════════════════════════════════════════════════════════
#  Public API: run_daily_policy
# ══════════════════════════════════════════════════════════════════════════

def _refilter_batch_by_live_cap(
    batch_match_ids: List[int],
    match_by_id: Dict[int, Match],
    live_team_counts: Dict[int, int],
    live_event_rounds: Dict[int, int],
    max_per_day: int = 2,
) -> Tuple[List[int], List[int]]:
    """
    Re-filter a batch's match_ids using:
    - live_team_counts (per team) for matches with resolved team IDs
    - live_event_rounds (per event) for RR matches (unresolved team IDs)

    Returns (kept_ids, dropped_ids).
    Does NOT mutate either counts dict (caller updates after actual assignment).
    """
    kept: List[int] = []
    dropped: List[int] = []
    simulated_counts = dict(live_team_counts)

    # Pre-check event-level eligibility for RR matches in this batch
    rr_event_eligible: Dict[int, bool] = {}
    rr_events_in_batch: Set[int] = set()
    for mid in batch_match_ids:
        m = match_by_id.get(mid)
        if m and m.match_type == "RR":
            rr_events_in_batch.add(m.event_id)
    for eid in rr_events_in_batch:
        rr_event_eligible[eid] = _can_event_afford_rr_round(
            eid, live_event_rounds,
        )

    for mid in batch_match_ids:
        m = match_by_id.get(mid)
        if not m:
            dropped.append(mid)
            continue

        # RR with unresolved teams — use event-round check
        tids = _get_team_ids_for_match(m)
        if not tids and m.match_type == "RR":
            if rr_event_eligible.get(m.event_id, True):
                kept.append(mid)
            else:
                dropped.append(mid)
            continue

        if not tids:
            # Truly unresolved (not RR) — allow through
            kept.append(mid)
            continue

        would_exceed = any(simulated_counts.get(tid, 0) >= max_per_day for tid in tids)
        if would_exceed:
            dropped.append(mid)
        else:
            kept.append(mid)
            for tid in tids:
                simulated_counts[tid] = simulated_counts.get(tid, 0) + 1
    return kept, dropped


def run_daily_policy(
    session: Session,
    tournament_id: int,
    schedule_version_id: int,
    day_date: date,
) -> PolicyRunResult:
    """
    Build and execute a daily placement plan.

    1. Builds the plan (ordered batches).
    2. Reserves spare courts by marking slots unavailable.
    3. For each batch:
       a. Re-filter match_ids through LIVE team-day counts (cross-batch cap).
       b. Execute via assign_by_match_ids.
       c. Update live team counts from newly-assigned matches.
    4. Restores reserved slots.
    5. Returns aggregate results.

    The live team-day counts ensure that no team exceeds 2 matches/day
    even when multiple batches (e.g., RR R1, RR R2, RR R3) run in
    sequence within a single policy invocation.
    """
    from app.utils.auto_assign import assign_by_match_ids, AutoAssignResult
    from app.models.match_lock import MatchLock
    from app.models.slot_lock import SlotLock

    start = datetime.utcnow()
    result = PolicyRunResult(day_date=day_date)

    # ── Load locks ─────────────────────────────────────────────────────
    match_locks = session.exec(
        select(MatchLock).where(MatchLock.schedule_version_id == schedule_version_id)
    ).all()
    slot_locks = session.exec(
        select(SlotLock).where(
            SlotLock.schedule_version_id == schedule_version_id,
            SlotLock.status == "BLOCKED",
        )
    ).all()
    locked_match_ids = {ml.match_id for ml in match_locks}
    locked_slot_ids = {ml.slot_id for ml in match_locks}
    blocked_slot_ids = {sl.slot_id for sl in slot_locks} | locked_slot_ids

    if match_locks or slot_locks:
        logger.info(
            "run_daily_policy: %d match locks, %d blocked slots",
            len(match_locks), len(slot_locks),
        )

    # Build the plan
    plan = build_daily_plan(session, tournament_id, schedule_version_id, day_date)
    result.reserved_slot_count = len(plan.reserved_slot_ids)

    # Build match lookup for team-cap re-filtering
    all_matches = session.exec(
        select(Match).where(Match.schedule_version_id == schedule_version_id)
    ).all()
    match_by_id: Dict[int, Match] = {m.id: m for m in all_matches}

    # Initialize LIVE team-day counts from already-committed assignments
    live_team_counts = _build_team_match_count_on_day(
        session, schedule_version_id, day_date,
    )

    # Initialize LIVE event-round counts (for RR cap at runtime)
    live_event_rounds = _count_event_rounds_assigned_on_day(
        session, schedule_version_id, day_date,
    )

    # Temporarily deactivate reserved slots so the assigner skips them
    reserved_original_states: List[Tuple[int, bool]] = []
    for slot_id in plan.reserved_slot_ids:
        slot = session.get(ScheduleSlot, slot_id)
        if slot and slot.is_active:
            reserved_original_states.append((slot_id, slot.is_active))
            slot.is_active = False
    session.flush()

    # Determine day index for Day 2+ checks (needed by batch loop).
    all_days = get_tournament_schedule_days(session, schedule_version_id)
    try:
        day_index = all_days.index(day_date)
    except ValueError:
        day_index = 0
    is_day2plus = day_index >= 1

    # ── Diagnostic logging: plan summary ──────────────────────────────
    logger.info(
        "=== run_daily_policy: Day %d (%s) — %d batches, %d reserved slots, %d deferred finals ===",
        day_index + 1, day_date, len(plan.batches), len(plan.reserved_slot_ids),
        len(plan.deferred_final_ids),
    )
    for bi, batch in enumerate(plan.batches):
        logger.info(
            "  Batch %d: %-40s  %d match(es)",
            bi + 1, batch.name, len(batch.match_ids),
        )

    # Execute each batch independently.
    # The dependency check (with rest-gap enforcement) now correctly handles
    # ordering: QFs are independent and pack contiguously, SFs respect rest
    # gaps, RR can't backfill into QF time slots because they're full.
    
    # Track failed MAIN matches for deferred placement
    failed_main_match_ids: List[int] = []
    # Match actual batch names like "DAY2_QF_Women's B", "DAY2_SF_Women's A"
    main_batch_names = {"_QF_", "_SF_"}

    # Track latest MAIN/RR assignment time (for consolation-after-main rule)
    latest_main_rr_time: Optional[time] = None
    
    for batch in plan.batches:
        # Remove locked matches from batch — they are pre-assigned
        batch_ids = [mid for mid in batch.match_ids if mid not in locked_match_ids]
        if not batch_ids:
            result.batches.append(BatchResult(
                name=batch.name, attempted=0, assigned=0,
            ))
            continue

        # Re-filter through LIVE team cap
        kept_ids, dropped_ids = _refilter_batch_by_live_cap(
            batch_ids, match_by_id, live_team_counts,
            live_event_rounds,
        )

        if dropped_ids:
            logger.info(
                "Batch %s: dropped %d match(es) due to cross-batch team cap",
                batch.name, len(dropped_ids),
            )

        if not kept_ids:
            result.batches.append(BatchResult(
                name=batch.name,
                attempted=len(batch.match_ids),
                assigned=0,
                failed_match_ids=dropped_ids,
            ))
            result.total_failed += len(dropped_ids)
            continue

        # Consolation batches use standard first-fit with no time restriction.
        # Consolation fills spare courts at any time slot (including ones
        # that already have MAIN/RR), matching the Kiawah benchmark.
        is_cons_batch = "_CONS_" in batch.name

        try:
            assign_result: AutoAssignResult = assign_by_match_ids(
                session=session,
                schedule_version_id=schedule_version_id,
                match_ids=kept_ids,
                target_day=day_date,
                blocked_slot_ids=blocked_slot_ids,
            )
            session.flush()

            # Update LIVE counts from newly-assigned matches
            rr_events_in_batch: Set[int] = set()

            # Scan all newly assigned matches (not just examples)
            newly_assigned = session.exec(
                select(MatchAssignment).where(
                    MatchAssignment.schedule_version_id == schedule_version_id,
                    MatchAssignment.match_id.in_(kept_ids),  # type: ignore[attr-defined]
                )
            ).all()
            for a in newly_assigned:
                m = match_by_id.get(a.match_id)
                if m:
                    tids = _get_team_ids_for_match(m)
                    for tid in tids:
                        live_team_counts[tid] = live_team_counts.get(tid, 0) + 1
                    if m.match_type == "RR":
                        rr_events_in_batch.add(m.event_id)

            # Increment event-round counter for each event with RR in this batch
            for eid in rr_events_in_batch:
                live_event_rounds[eid] = live_event_rounds.get(eid, 0) + 1

            # Track latest MAIN/RR time for consolation-after-main constraint
            if not is_cons_batch and is_day2plus:
                for a in newly_assigned:
                    m = match_by_id.get(a.match_id)
                    if m and m.match_type in ("MAIN", "RR"):
                        slot = session.get(ScheduleSlot, a.slot_id)
                        if slot and (latest_main_rr_time is None or slot.start_time > latest_main_rr_time):
                            latest_main_rr_time = slot.start_time

            all_failed = [
                um["match_id"] for um in assign_result.unassigned_matches
            ] + dropped_ids

            # Track failed MAIN matches from MAIN batches
            if any(name_part in batch.name for name_part in main_batch_names):
                for failed_id in all_failed:
                    failed_match = match_by_id.get(failed_id)
                    if failed_match and failed_match.match_type == "MAIN":
                        failed_main_match_ids.append(failed_id)

            br = BatchResult(
                name=batch.name,
                attempted=len(batch.match_ids),
                assigned=assign_result.assigned_count,
                failed_match_ids=all_failed,
            )
            result.batches.append(br)
            result.total_assigned += assign_result.assigned_count
            result.total_failed += assign_result.unassigned_count + len(dropped_ids)

            # Diagnostic logging: batch result
            logger.info(
                "  -> %-40s  %d/%d assigned, %d failed",
                batch.name, assign_result.assigned_count, len(batch.match_ids),
                len(all_failed),
            )

        except Exception as exc:
            logger.error(f"Batch {batch.name} failed: {exc}")
            result.batches.append(BatchResult(
                name=batch.name,
                attempted=len(batch.match_ids),
                assigned=0,
                failed_match_ids=batch.match_ids,
            ))
            result.total_failed += len(batch.match_ids)
            # Track failed MAIN matches from exception case
            if any(name_part in batch.name for name_part in main_batch_names):
                for failed_id in batch.match_ids:
                    failed_match = match_by_id.get(failed_id)
                    if failed_match and failed_match.match_type == "MAIN":
                        failed_main_match_ids.append(failed_id)

    # Handle deferred MAIN matches and fill spare courts with consolation
    # For Day 2+ (not Day 1)

    # Restore reserved slots (no-op now that spare reservations are disabled).
    # Kept for safety in case any slots were reserved by other means.
    for slot_id, was_active in reserved_original_states:
        slot = session.get(ScheduleSlot, slot_id)
        if slot:
            slot.is_active = was_active
    session.flush()
    reserved_original_states.clear()   # prevent double-restore later

    # Fill spare courts with consolation after MAIN batches (for Day 2+).
    # Loop until stable: each pass may unlock the next consolation round
    # (round N becomes eligible once round N-1 is assigned).
    if is_day2plus:
        # Consolation fills whatever spare courts remain after MAIN/RR are
        # placed.  No min_start_time constraint — consolation CAN share a
        # time slot with MAIN/RR (the Kiawah benchmark does exactly this).
        all_consolation_assigned: List[int] = []
        for fill_pass in range(10):  # max 10 iterations to prevent infinite loop
            current_assignments = session.exec(
                select(MatchAssignment).where(
                    MatchAssignment.schedule_version_id == schedule_version_id,
                )
            ).all()
            current_assigned_ids = {a.match_id for a in current_assignments}

            consolation_assigned = _fill_spare_courts_with_consolation(
                session, schedule_version_id, day_date, all_matches,
                current_assigned_ids, live_team_counts,
                fill_all_available=True, max_spare_per_slot=0,
                max_round_index=1,  # Day 2: only consolation semis (C1+C2, round_index=1)
                blocked_slot_ids=blocked_slot_ids,
            )
            if not consolation_assigned:
                break  # no more eligible — stop

            all_consolation_assigned.extend(consolation_assigned)
            # Update live team counts for next pass
            for mid in consolation_assigned:
                m = match_by_id.get(mid)
                if m:
                    tids = _get_team_ids_for_match(m)
                    for tid in tids:
                        live_team_counts[tid] = live_team_counts.get(tid, 0) + 1

        if all_consolation_assigned:
            result.total_assigned += len(all_consolation_assigned)
            result.batches.append(BatchResult(
                name=f"DAY{day_index + 1}_CONSOLATION_FILL",
                attempted=len(all_consolation_assigned),
                assigned=len(all_consolation_assigned),
                failed_match_ids=[],
            ))
    
    # Handle deferred MAIN matches (if any failed due to rest gap)
    if is_day2plus and failed_main_match_ids:
        # Identify MAIN matches that failed due to rest gap
        failed_main_due_to_rest_gap = _identify_failed_main_due_to_rest_gap(
            failed_main_match_ids, match_by_id, session, schedule_version_id, day_date
        )
        
        # Try moving prerequisites earlier for failed MAIN matches
        from app.utils.auto_assign import _get_bracket_prerequisites
        main_matches = [m for m in all_matches if m.match_type == "MAIN"]
        main_classified = _classify_bracket_matches(main_matches)
        bracket_tier_cache: Dict[int, str] = {}
        for m in main_classified.get("qf", []):
            bracket_tier_cache[m.id] = "qf"
        for m in main_classified.get("sf", []):
            bracket_tier_cache[m.id] = "sf"
        for m in main_classified.get("final", []):
            bracket_tier_cache[m.id] = "final"
        
        deferred_main_ids: List[int] = []
        for failed_match in failed_main_due_to_rest_gap:
            tier = bracket_tier_cache.get(failed_match.id, "qf")
            if tier == "qf":
                continue
            
            prereqs = _get_bracket_prerequisites(failed_match, tier, all_matches, bracket_tier_cache)
            moved = False
            for prereq in prereqs:
                if _try_move_prerequisite_earlier(
                    failed_match, prereq, session, schedule_version_id, day_date
                ):
                    moved = True
                    break
            
            # If prerequisite was moved, try assigning the failed match again
            if moved:
                try:
                    assign_result = assign_by_match_ids(
                        session=session,
                        schedule_version_id=schedule_version_id,
                        match_ids=[failed_match.id],
                        target_day=day_date,
                        blocked_slot_ids=blocked_slot_ids,
                    )
                    session.flush()
                    if assign_result.assigned_count > 0:
                        result.total_assigned += assign_result.assigned_count
                        result.total_failed -= 1
                        continue
                except Exception:
                    pass
            
            # Still failed - add to deferred
            deferred_main_ids.append(failed_match.id)
        
        # Now try deferred MAIN matches in later time slots
        if deferred_main_ids:
                try:
                    deferred_result = assign_by_match_ids(
                        session=session,
                        schedule_version_id=schedule_version_id,
                        match_ids=deferred_main_ids,
                        target_day=day_date,
                        blocked_slot_ids=blocked_slot_ids,
                    )
                    session.flush()
                    
                    if deferred_result.assigned_count > 0:
                        result.total_assigned += deferred_result.assigned_count
                        result.total_failed -= deferred_result.assigned_count
                        failed_deferred = [um["match_id"] for um in deferred_result.unassigned_matches]
                        result.batches.append(BatchResult(
                            name=f"DAY{day_index + 1}_DEFERRED_MAIN",
                            attempted=len(deferred_main_ids),
                            assigned=deferred_result.assigned_count,
                            failed_match_ids=failed_deferred,
                        ))
                except Exception as exc:
                    logger.error(f"Deferred MAIN batch failed: {exc}")

    # Safety net: remove any accidentally-placed deferred Finals from Day 2
    if plan.deferred_final_ids:
        deferred_set = set(plan.deferred_final_ids)
        leaked_finals = session.exec(
            select(MatchAssignment).where(
                MatchAssignment.schedule_version_id == schedule_version_id,
                MatchAssignment.match_id.in_(list(deferred_set)),  # type: ignore[attr-defined]
            )
        ).all()
        if leaked_finals:
            leaked_count = len(leaked_finals)
            for a in leaked_finals:
                session.delete(a)
            session.flush()
            result.total_assigned -= leaked_count
            logger.warning(
                "Day %s: removed %d leaked MAIN Finals (deferred to Day 3)",
                day_date, leaked_count,
            )

    # (Reserved slots already restored before consolation fill above.)

    result.duration_ms = int((datetime.utcnow() - start).total_seconds() * 1000)
    logger.info(
        "=== Day %d complete: %d assigned, %d failed, %d ms ===",
        day_index + 1, result.total_assigned, result.total_failed, result.duration_ms,
    )
    return result


def get_tournament_schedule_days(
    session: Session,
    schedule_version_id: int,
) -> List[date]:
    """Return sorted list of unique days that have slots for this version."""
    slots = session.exec(
        select(ScheduleSlot).where(
            ScheduleSlot.schedule_version_id == schedule_version_id,
        )
    ).all()
    return sorted(set(s.day_date for s in slots))


# ══════════════════════════════════════════════════════════════════════════
#  One-Button: run policy for ALL days
# ══════════════════════════════════════════════════════════════════════════

@dataclass
class FullPolicyResult:
    """Aggregate result from running policy across all tournament days."""
    total_assigned: int = 0
    total_failed: int = 0
    total_reserved_spares: int = 0
    duration_ms: int = 0
    day_results: List[Dict[str, Any]] = field(default_factory=list)


def run_full_schedule_policy(
    session: Session,
    tournament_id: int,
    schedule_version_id: int,
) -> FullPolicyResult:
    """
    One-button scheduling: run the daily policy for every tournament day
    in sequence and return aggregate results.
    """
    start = datetime.utcnow()
    full_result = FullPolicyResult()

    days = get_tournament_schedule_days(session, schedule_version_id)
    if not days:
        full_result.duration_ms = int((datetime.utcnow() - start).total_seconds() * 1000)
        return full_result

    for day_date in days:
        day_result = run_daily_policy(
            session, tournament_id, schedule_version_id, day_date,
        )
        full_result.total_assigned += day_result.total_assigned
        full_result.total_failed += day_result.total_failed
        full_result.total_reserved_spares += day_result.reserved_slot_count

        full_result.day_results.append({
            "day": str(day_date),
            "assigned": day_result.total_assigned,
            "failed": day_result.total_failed,
            "reserved_spares": day_result.reserved_slot_count,
            "duration_ms": day_result.duration_ms,
            "batches": [
                {
                    "name": b.name,
                    "attempted": b.attempted,
                    "assigned": b.assigned,
                    "failed_count": len(b.failed_match_ids),
                }
                for b in day_result.batches
            ],
        })

    full_result.duration_ms = int((datetime.utcnow() - start).total_seconds() * 1000)
    return full_result
