"""
Auto-Assign V1: Deterministic match-to-slot assignment

This module implements a deterministic first-fit algorithm that assigns
pre-generated matches to pre-generated schedule slots.

Non-goals (V1):
- Team assignment / team injection
- Home/away logic
- Rest rules or match spacing
- Day targeting / time preferences
- Court balancing heuristics
- "Best fit" optimization
- Any randomness
"""

from datetime import datetime, time
from typing import Any, Dict, List, Optional, Tuple

from sqlmodel import Session, select

from app.models.match import Match
from app.models.match_assignment import MatchAssignment
from app.models.schedule_slot import ScheduleSlot
from app.models.schedule_version import ScheduleVersion

# Stage precedence mapping (hard-coded, authoritative)
# WF=1, RR=2 (pools), MAIN=3 (brackets), CONSOLATION=4, PLACEMENT=5
STAGE_PRECEDENCE = {"WF": 1, "RR": 2, "MAIN": 3, "CONSOLATION": 4, "PLACEMENT": 5}

VALID_STAGES = set(STAGE_PRECEDENCE.keys())


class AutoAssignError(Exception):
    """Base exception for auto-assign errors"""

    pass


class AutoAssignValidationError(AutoAssignError):
    """Validation failed before assignment"""

    pass


class AutoAssignResult:
    """Structured result from auto-assign operation"""

    def __init__(self):
        self.assigned_count = 0
        self.unassigned_count = 0
        self.unassigned_matches: List[Dict[str, Any]] = []
        self.assigned_examples: List[Dict[str, Any]] = []
        self.total_matches = 0
        self.total_slots = 0
        self.duration_ms: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "assigned_count": self.assigned_count,
            "unassigned_count": self.unassigned_count,
            "total_matches": self.total_matches,
            "total_slots": self.total_slots,
            "success_rate": round(self.assigned_count / self.total_matches * 100, 1) if self.total_matches > 0 else 0,
            "unassigned_matches": self.unassigned_matches,
            "assigned_examples": self.assigned_examples[:10],  # First 10 for sanity
            "duration_ms": self.duration_ms,
        }


def get_match_sort_key(match: Match) -> Tuple:
    """
    Generate deterministic sort key for matches.

    Order: stage_order → round_index → sequence_in_round → id

    This ensures:
    - WF matches process first
    - Then MAIN (QF → SF → Final)
    - Then CONSOLATION (Tier 1 → Tier 2)
    - Then PLACEMENT
    """
    stage_order = STAGE_PRECEDENCE.get(match.match_type, 999)

    return (stage_order, match.round_index or 999, match.sequence_in_round or 999, match.id or 999)


def get_slot_sort_key(slot: ScheduleSlot) -> Tuple:
    """
    Generate deterministic sort key for slots.

    Order: start_time → court_label → id

    This ensures slots are filled chronologically, court-by-court.
    """
    # Convert time to minutes from midnight for sorting
    start_minutes = slot.start_time.hour * 60 + slot.start_time.minute if slot.start_time else 0

    return (slot.day_date, start_minutes, slot.court_label or "", slot.id or 999)


def validate_inputs(matches: List[Match], slots: List[ScheduleSlot], schedule_version_id: int) -> None:
    """
    Perform sanity checks before auto-assign.

    Raises AutoAssignValidationError if validation fails.
    """
    # Check non-empty
    if not matches:
        raise AutoAssignValidationError("Match list is empty")

    if not slots:
        raise AutoAssignValidationError("Slot list is empty")

    # Check for duplicate slot IDs
    slot_ids = [s.id for s in slots if s.id is not None]
    if len(slot_ids) != len(set(slot_ids)):
        raise AutoAssignValidationError("Duplicate slot IDs detected")

    # Validate match metadata
    for match in matches:
        # Check stage is valid
        if match.match_type not in VALID_STAGES:
            raise AutoAssignValidationError(
                f"Match {match.id} ({match.match_code}) has invalid stage: {match.match_type}"
            )

        # Check round_index and sequence_in_round are non-null
        if match.round_index is None:
            raise AutoAssignValidationError(f"Match {match.id} ({match.match_code}) has null round_index")

        if match.sequence_in_round is None:
            raise AutoAssignValidationError(f"Match {match.id} ({match.match_code}) has null sequence_in_round")

        # Check schedule_version_id matches
        if match.schedule_version_id != schedule_version_id:
            raise AutoAssignValidationError(
                f"Match {match.id} belongs to version {match.schedule_version_id}, expected {schedule_version_id}"
            )

    # Validate slot metadata
    for slot in slots:
        if slot.schedule_version_id != schedule_version_id:
            raise AutoAssignValidationError(
                f"Slot {slot.id} belongs to version {slot.schedule_version_id}, expected {schedule_version_id}"
            )


def is_slot_compatible(slot: ScheduleSlot, match: Match, occupied_slot_ids: set) -> Tuple[bool, Optional[str]]:
    """
    Check if a slot is compatible for a match.

    Returns: (is_compatible, reason_if_not)

    V1 compatibility rules:
    1. Slot is unassigned (not in occupied_slot_ids)
    2. Slot duration >= match duration
    3. Same schedule_version_id (already validated in validate_inputs)
    """
    # Check if slot is already occupied
    if slot.id in occupied_slot_ids:
        return False, "SLOT_OCCUPIED"

    # Check duration compatibility
    # For V1, we use block_minutes as the slot capacity
    slot_duration = slot.block_minutes or 0
    if slot_duration < match.duration_minutes:
        return False, "DURATION_TOO_LONG"

    return True, None


def check_round_dependencies_for_auto_assign(
    session: Session,
    match: Match,
    slot: ScheduleSlot,
    schedule_version_id: int,
    assigned_match_ids: set
) -> Tuple[bool, Optional[str]]:
    """
    Check round dependencies for auto-assign.
    
    Only checks assigned prerequisites - doesn't block Round N matches if Round N-1 matches
    haven't been assigned yet (they'll be assigned in order).
    
    Returns: (is_valid, reason_if_not)
    """
    # Round 1 matches have no dependencies
    if match.round_index is None or match.round_index <= 1:
        return True, None
    
    # Find all prerequisite matches (Round N-1 in same event and stage)
    prerequisite_round = match.round_index - 1
    
    prerequisite_matches = session.exec(
        select(Match).where(
            Match.schedule_version_id == schedule_version_id,
            Match.event_id == match.event_id,
            Match.match_type == match.match_type,
            Match.round_index == prerequisite_round
        )
    ).all()
    
    if not prerequisite_matches:
        # No prerequisites found - allow assignment
        return True, None
    
    # Calculate target slot start time in minutes
    slot_start_minutes = slot.start_time.hour * 60 + slot.start_time.minute if slot.start_time else 0
    
    # Check each prerequisite match - ALL must be assigned and finished
    # (Auto-assign processes matches in order, so this should normally be satisfied)
    for prereq_match in prerequisite_matches:
        if prereq_match.id not in assigned_match_ids:
            # ALL Round N-1 matches must be assigned before ANY Round N match can be scheduled
            return False, (
                f"Cannot place Match: Round {match.round_index} cannot start before a Round {prerequisite_round} Match"
            )
        
        # Get prerequisite assignment
        prereq_assignment = session.exec(
            select(MatchAssignment).where(
                MatchAssignment.schedule_version_id == schedule_version_id,
                MatchAssignment.match_id == prereq_match.id
            )
        ).first()
        
        if not prereq_assignment:
            continue
        
        prereq_slot = session.get(ScheduleSlot, prereq_assignment.slot_id)
        if not prereq_slot or not prereq_slot.start_time:
            continue
        
        # Calculate prerequisite match end time
        prereq_start_minutes = prereq_slot.start_time.hour * 60 + prereq_slot.start_time.minute
        prereq_end_minutes = prereq_start_minutes + prereq_match.duration_minutes
        
        # Check if prerequisite ends before target start
        if prereq_end_minutes > slot_start_minutes:
            return False, (
                f"Cannot place Match: Round {match.round_index} cannot start before a Round {prerequisite_round} Match"
            )
    
    return True, None


def auto_assign_v1(session: Session, schedule_version_id: int, clear_existing: bool = True) -> AutoAssignResult:
    """
    Auto-Assign V1: Deterministic first-fit match-to-slot assignment.

    Args:
        session: Database session (must be in a transaction)
        schedule_version_id: Schedule version to assign
        clear_existing: If True, clear existing auto-assign assignments first (Option A)

    Returns:
        AutoAssignResult with assigned/unassigned counts and details

    Raises:
        AutoAssignValidationError: If input validation fails
        AutoAssignError: If assignment fails
    """
    start_time = datetime.utcnow()
    result = AutoAssignResult()

    # Verify schedule version exists
    version = session.get(ScheduleVersion, schedule_version_id)
    if not version:
        raise AutoAssignValidationError(f"Schedule version {schedule_version_id} not found")

    # Step 1: Clear existing assignments if requested (Option A)
    if clear_existing:
        existing_assignments = session.exec(
            select(MatchAssignment)
            .where(MatchAssignment.schedule_version_id == schedule_version_id)
            .where(MatchAssignment.assigned_by == "AUTO_ASSIGN_V1")
        ).all()

        for assignment in existing_assignments:
            session.delete(assignment)

        session.flush()

    # Step 2: Load matches in deterministic order
    matches = session.exec(
        select(Match)
        .where(Match.schedule_version_id == schedule_version_id)
        .order_by(Match.id)  # Initial fetch, will sort in Python
    ).all()

    # Sort matches deterministically
    matches_sorted = sorted(matches, key=get_match_sort_key)
    result.total_matches = len(matches_sorted)

    # Step 3: Load slots in deterministic order
    slots = session.exec(
        select(ScheduleSlot)
        .where(ScheduleSlot.schedule_version_id == schedule_version_id)
        .order_by(ScheduleSlot.id)  # Initial fetch, will sort in Python
    ).all()

    # Sort slots deterministically
    slots_sorted = sorted(slots, key=get_slot_sort_key)
    result.total_slots = len(slots_sorted)

    # Step 4: Validate inputs
    validate_inputs(matches_sorted, slots_sorted, schedule_version_id)

    # Step 5: Load existing assignments to track occupied slots
    existing_assignments = session.exec(
        select(MatchAssignment).where(MatchAssignment.schedule_version_id == schedule_version_id)
    ).all()

    occupied_slot_ids = {a.slot_id for a in existing_assignments}

    # Step 6: First-fit assignment loop
    assigned_match_ids = set()

    for match in matches_sorted:
        assigned = False
        failure_reason = "NO_COMPATIBLE_SLOT"

        # Scan slots in order
        for slot in slots_sorted:
            compatible, reason = is_slot_compatible(slot, match, occupied_slot_ids)

            if compatible:
                # Check round dependencies
                round_deps_ok, round_deps_reason = check_round_dependencies_for_auto_assign(
                    session, match, slot, schedule_version_id, assigned_match_ids
                )
                if not round_deps_ok:
                    # Track the failure reason
                    if failure_reason == "NO_COMPATIBLE_SLOT":
                        failure_reason = round_deps_reason or "ROUND_DEPENDENCY_VIOLATION"
                    continue
                # Create assignment
                assignment = MatchAssignment(
                    schedule_version_id=schedule_version_id,
                    match_id=match.id,
                    slot_id=slot.id,
                    assigned_by="AUTO_ASSIGN_V1",
                    assigned_at=datetime.utcnow(),
                )
                session.add(assignment)

                # Mark slot as occupied
                occupied_slot_ids.add(slot.id)
                assigned_match_ids.add(match.id)

                # Track for reporting
                result.assigned_count += 1
                if len(result.assigned_examples) < 10:
                    result.assigned_examples.append(
                        {
                            "match_id": match.id,
                            "match_code": match.match_code,
                            "stage": match.match_type,
                            "slot_id": slot.id,
                            "day": str(slot.day_date),
                            "start_time": str(slot.start_time),
                            "court": slot.court_label,
                        }
                    )

                assigned = True
                break
            else:
                # Track the first failure reason
                if failure_reason == "NO_COMPATIBLE_SLOT":
                    failure_reason = reason or "NO_COMPATIBLE_SLOT"

        # If not assigned, record as unassigned
        if not assigned:
            result.unassigned_count += 1
            result.unassigned_matches.append(
                {
                    "match_id": match.id,
                    "match_code": match.match_code,
                    "stage": match.match_type,
                    "round_index": match.round_index,
                    "sequence_in_round": match.sequence_in_round,
                    "duration_minutes": match.duration_minutes,
                    "reason": failure_reason,
                }
            )

    # Step 7: Flush assignments to DB
    session.flush()

    # Calculate duration
    end_time = datetime.utcnow()
    result.duration_ms = int((end_time - start_time).total_seconds() * 1000)

    return result


# Scope mapping for phased placement (Phase Flow V1)
SCOPE_FILTERS = {
    "WF_R1": lambda m: m.match_type == "WF" and m.round_number == 1,
    "WF_R2": lambda m: m.match_type == "WF" and m.round_number == 2,
    "RR_POOL": lambda m: m.match_type == "RR",
    "BRACKET_MAIN": lambda m: m.match_type == "MAIN",
    "ALL": lambda m: True,
}


def assign_with_scope(
    session: Session,
    schedule_version_id: int,
    scope: str,
    event_id: Optional[int] = None,
    clear_existing_assignments_in_scope: bool = False,
) -> AutoAssignResult:
    """
    Assign matches within a scope (WF_R1, WF_R2, RR_POOL, BRACKET_MAIN, ALL).

    Only assigns matches that are currently unassigned.
    Deterministic ordering: event_id, stage, round_index, sequence_in_round, match_code.
    """
    if scope not in SCOPE_FILTERS:
        raise AutoAssignValidationError(f"Invalid scope: {scope}. Must be one of {list(SCOPE_FILTERS.keys())}")

    filter_fn = SCOPE_FILTERS[scope]
    start_time = datetime.utcnow()
    result = AutoAssignResult()

    version = session.get(ScheduleVersion, schedule_version_id)
    if not version:
        raise AutoAssignValidationError(f"Schedule version {schedule_version_id} not found")

    # Load slots
    slots = session.exec(
        select(ScheduleSlot).where(ScheduleSlot.schedule_version_id == schedule_version_id)
    ).all()
    slots_sorted = sorted(slots, key=get_slot_sort_key)
    result.total_slots = len(slots_sorted)
    if not slots_sorted:
        raise AutoAssignValidationError("No slots exist. Generate slots first.")

    # Load all matches for version
    matches = session.exec(
        select(Match).where(Match.schedule_version_id == schedule_version_id)
    ).all()

    # Filter by scope and event_id
    scope_matches = [m for m in matches if filter_fn(m) and (event_id is None or m.event_id == event_id)]
    scope_matches_sorted = sorted(
        scope_matches,
        key=lambda m: (m.event_id, STAGE_PRECEDENCE.get(m.match_type, 999), m.round_index or 999, m.sequence_in_round or 999, m.match_code or ""),
    )

    # Load existing assignments
    existing_assignments = session.exec(
        select(MatchAssignment).where(MatchAssignment.schedule_version_id == schedule_version_id)
    ).all()
    assigned_match_ids = {a.match_id for a in existing_assignments}

    # Optionally clear assignments for matches in scope
    if clear_existing_assignments_in_scope:
        scope_match_ids = {m.id for m in scope_matches_sorted}
        for a in existing_assignments:
            if a.match_id in scope_match_ids:
                session.delete(a)
        session.flush()
        remaining = session.exec(
            select(MatchAssignment).where(MatchAssignment.schedule_version_id == schedule_version_id)
        ).all()
        assigned_match_ids = {a.match_id for a in remaining}
        existing_assignments = remaining

    # Only process unassigned matches in scope
    to_assign = [m for m in scope_matches_sorted if m.id not in assigned_match_ids]
    result.total_matches = len(to_assign)

    if not to_assign:
        result.assigned_count = 0
        result.unassigned_count = 0
        result.duration_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)
        return result

    validate_inputs(to_assign, slots_sorted, schedule_version_id)
    occupied_slot_ids = {a.slot_id for a in session.exec(
        select(MatchAssignment).where(MatchAssignment.schedule_version_id == schedule_version_id)
    ).all()}

    assigned_match_ids = set(assigned_match_ids)

    for match in to_assign:
        assigned = False
        failure_reason = "NO_COMPATIBLE_SLOT"
        for slot in slots_sorted:
            compatible, reason = is_slot_compatible(slot, match, occupied_slot_ids)
            if compatible:
                round_deps_ok, round_deps_reason = check_round_dependencies_for_auto_assign(
                    session, match, slot, schedule_version_id, assigned_match_ids
                )
                if not round_deps_ok:
                    if failure_reason == "NO_COMPATIBLE_SLOT":
                        failure_reason = round_deps_reason or "ROUND_DEPENDENCY_VIOLATION"
                    continue
                assignment = MatchAssignment(
                    schedule_version_id=schedule_version_id,
                    match_id=match.id,
                    slot_id=slot.id,
                    assigned_by="ASSIGN_SCOPE_V1",
                    assigned_at=datetime.utcnow(),
                )
                session.add(assignment)
                occupied_slot_ids.add(slot.id)
                assigned_match_ids.add(match.id)
                result.assigned_count += 1
                if len(result.assigned_examples) < 10:
                    result.assigned_examples.append({
                        "match_id": match.id, "match_code": match.match_code, "stage": match.match_type,
                        "slot_id": slot.id, "day": str(slot.day_date), "start_time": str(slot.start_time),
                        "court": slot.court_label,
                    })
                assigned = True
                break
            else:
                if failure_reason == "NO_COMPATIBLE_SLOT":
                    failure_reason = reason or "NO_COMPATIBLE_SLOT"
        if not assigned:
            result.unassigned_count += 1
            result.unassigned_matches.append({
                "match_id": match.id, "match_code": match.match_code, "stage": match.match_type,
                "round_index": match.round_index, "sequence_in_round": match.sequence_in_round,
                "duration_minutes": match.duration_minutes, "reason": failure_reason,
            })

    session.flush()
    result.duration_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)
    return result
