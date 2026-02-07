"""
Auto-Assign V2: Constraint-based match-to-slot assignment

V2 extends V1 with hard constraints:
- Minimum rest minutes between a team's consecutive matches
- Court-type eligibility (if courts have types and matches require them)
- Enhanced deterministic tie-breaking

V2 is ADDITIVE on V1:
- Preserves V1's match ordering (WF → MAIN → CONSOLATION → PLACEMENT)
- Never violates consolation rules
- Same inputs → same outputs (fully deterministic)
- Returns structured conflict reasons when constraints block assignment

Key differences from V1:
1. **Rest constraints**: Tracks team assignments and enforces minimum rest time
2. **Court typing**: Supports optional court types (e.g., "feature", "standard")
3. **Richer conflicts**: Reports WHY assignments failed (rest violation, court mismatch)
4. **Partial assignments**: Can assign some matches even if others are blocked
"""

from datetime import datetime, timedelta, time
from typing import Any, Dict, List, Optional, Set, Tuple

from sqlmodel import Session, select

from app.models.match import Match
from app.models.match_assignment import MatchAssignment
from app.models.schedule_slot import ScheduleSlot
from app.models.schedule_version import ScheduleVersion

# Import V1 utilities that we reuse
from app.utils.auto_assign import (
    STAGE_PRECEDENCE,
    VALID_STAGES,
    AutoAssignError,
    AutoAssignValidationError,
    get_match_sort_key,
    get_slot_sort_key,
    validate_inputs,
)


# ============================================================================
# V2-specific configuration
# ============================================================================

# Default minimum rest time between matches for the same team (in minutes)
DEFAULT_MIN_REST_MINUTES = 90

# Conflict reason codes
CONFLICT_REST_VIOLATION = "REST_VIOLATION"
CONFLICT_COURT_TYPE_MISMATCH = "COURT_TYPE_MISMATCH"
CONFLICT_SLOT_OCCUPIED = "SLOT_OCCUPIED"
CONFLICT_DURATION_TOO_LONG = "DURATION_TOO_LONG"
CONFLICT_ROUND_DEPENDENCY = "ROUND_DEPENDENCY"
CONFLICT_NO_COMPATIBLE_SLOT = "NO_COMPATIBLE_SLOT"


# ============================================================================
# V2 Result Class
# ============================================================================


class AutoAssignV2Result:
    """Enhanced result from V2 auto-assign operation"""

    def __init__(self):
        self.assigned_count = 0
        self.unassigned_count = 0
        self.total_matches = 0
        self.total_slots = 0
        self.duration_ms: Optional[int] = None

        # V2-specific: detailed conflict tracking
        self.conflicts: List[Dict[str, Any]] = []
        self.assigned_examples: List[Dict[str, Any]] = []

        # Statistics
        self.rest_violations = 0
        self.court_type_mismatches = 0
        self.slot_occupied_count = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "assigned_count": self.assigned_count,
            "unassigned_count": self.unassigned_count,
            "total_matches": self.total_matches,
            "total_slots": self.total_slots,
            "success_rate": round(self.assigned_count / self.total_matches * 100, 1) if self.total_matches > 0 else 0,
            "duration_ms": self.duration_ms,
            # V2-specific fields
            "conflicts": self.conflicts,
            "assigned_examples": self.assigned_examples[:10],
            "conflict_summary": {
                "rest_violations": self.rest_violations,
                "court_type_mismatches": self.court_type_mismatches,
                "slot_occupied": self.slot_occupied_count,
            },
        }


# ============================================================================
# V2 Constraint Checking
# ============================================================================


class TeamAssignmentTracker:
    """
    Tracks team assignments to enforce rest constraints.

    Maps team_id -> List[Tuple[slot_start_datetime, slot_end_datetime]]
    """

    def __init__(self):
        # team_id -> list of (start_datetime, end_datetime) tuples
        self._assignments: Dict[int, List[Tuple[datetime, datetime]]] = {}

    def add_assignment(self, team_ids: List[Optional[int]], slot: ScheduleSlot, match_duration: int) -> None:
        """
        Record that these teams are assigned to this slot.

        Args:
            team_ids: List of team IDs (may contain None for unassigned positions)
            slot: The schedule slot
            match_duration: Match duration in minutes
        """
        if not slot.day_date or not slot.start_time:
            return

        # Calculate start and end datetime
        start_dt = datetime.combine(slot.day_date, slot.start_time)
        end_dt = start_dt + timedelta(minutes=match_duration)

        for team_id in team_ids:
            if team_id is not None:
                if team_id not in self._assignments:
                    self._assignments[team_id] = []
                self._assignments[team_id].append((start_dt, end_dt))

    def check_rest_constraint(
        self, team_ids: List[Optional[int]], slot: ScheduleSlot, match_duration: int, min_rest_minutes: int
    ) -> Tuple[bool, Optional[int]]:
        """
        Check if assigning these teams to this slot violates rest constraints.

        Returns: (is_valid, violating_team_id)
        - (True, None) if no violation
        - (False, team_id) if team_id would violate rest constraint
        """
        if not slot.day_date or not slot.start_time:
            return True, None

        proposed_start = datetime.combine(slot.day_date, slot.start_time)
        proposed_end = proposed_start + timedelta(minutes=match_duration)

        for team_id in team_ids:
            if team_id is None:
                continue

            if team_id not in self._assignments:
                continue

            # Check all existing assignments for this team
            for existing_start, existing_end in self._assignments[team_id]:
                # Calculate rest time between matches
                # Rest is the gap between end of one match and start of the next

                if proposed_start >= existing_end:
                    # New match starts after existing match ends
                    rest_minutes = (proposed_start - existing_end).total_seconds() / 60
                elif proposed_end <= existing_start:
                    # New match ends before existing match starts
                    rest_minutes = (existing_start - proposed_end).total_seconds() / 60
                else:
                    # Matches overlap - invalid (should be caught by slot occupied check)
                    return False, team_id

                if rest_minutes < min_rest_minutes:
                    return False, team_id

        return True, None


def is_slot_compatible_v2(
    slot: ScheduleSlot,
    match: Match,
    occupied_slot_ids: Set[int],
    team_tracker: TeamAssignmentTracker,
    min_rest_minutes: int = DEFAULT_MIN_REST_MINUTES,
    require_court_type_match: bool = False,
) -> Tuple[bool, Optional[str], Optional[Dict[str, Any]]]:
    """
    V2 compatibility check with enhanced constraints.

    Args:
        slot: Candidate slot
        match: Match to assign
        occupied_slot_ids: Set of already-occupied slot IDs
        team_tracker: Tracks team assignments for rest checking
        min_rest_minutes: Minimum rest time between matches for same team
        require_court_type_match: If True, enforce court_type compatibility

    Returns:
        (is_compatible, conflict_reason, conflict_details)
    """
    # V1 checks first
    if slot.id in occupied_slot_ids:
        return False, CONFLICT_SLOT_OCCUPIED, {"slot_id": slot.id}

    slot_duration = slot.block_minutes or 0
    if slot_duration < match.duration_minutes:
        return (
            False,
            CONFLICT_DURATION_TOO_LONG,
            {"slot_duration": slot_duration, "match_duration": match.duration_minutes},
        )

    # V2 check: Court type compatibility
    if require_court_type_match:
        # If match requires a specific court type, check slot has it
        # (This is a placeholder - actual implementation depends on schema)
        match_court_type = getattr(match, "required_court_type", None)
        slot_court_type = getattr(slot, "court_type", None)

        if match_court_type and slot_court_type:
            if match_court_type != slot_court_type:
                return (
                    False,
                    CONFLICT_COURT_TYPE_MISMATCH,
                    {"required": match_court_type, "available": slot_court_type},
                )

    # V2 check: Rest constraints
    # Get team IDs from match (if teams are assigned)
    team_ids = []
    if hasattr(match, "team_a_id") and match.team_a_id:
        team_ids.append(match.team_a_id)
    if hasattr(match, "team_b_id") and match.team_b_id:
        team_ids.append(match.team_b_id)

    if team_ids:
        rest_ok, violating_team = team_tracker.check_rest_constraint(
            team_ids, slot, match.duration_minutes, min_rest_minutes
        )
        if not rest_ok:
            return (
                False,
                CONFLICT_REST_VIOLATION,
                {"team_id": violating_team, "min_rest_minutes": min_rest_minutes},
            )

    return True, None, None


def check_round_dependencies_for_auto_assign_v2(
    session: Session,
    match: Match,
    slot: ScheduleSlot,
    schedule_version_id: int,
    assigned_match_ids: set
) -> Tuple[bool, Optional[str], Optional[Dict[str, Any]]]:
    """
    Check round dependencies for auto-assign V2.
    
    Only checks assigned prerequisites - doesn't block Round N matches if Round N-1 matches
    haven't been assigned yet (they'll be assigned in order).
    
    Returns: (is_valid, conflict_reason, conflict_details)
    """
    # Round 1 matches have no dependencies
    if match.round_index is None or match.round_index <= 1:
        return True, None, None
    
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
        return True, None, None
    
    # Calculate target slot start time in minutes
    slot_start_minutes = slot.start_time.hour * 60 + slot.start_time.minute if slot.start_time else 0
    
    # Check each prerequisite match - ALL must be assigned and finished
    # (Auto-assign processes matches in order, so this should normally be satisfied)
    for prereq_match in prerequisite_matches:
        if prereq_match.id not in assigned_match_ids:
            # ALL Round N-1 matches must be assigned before ANY Round N match can be scheduled
            return False, CONFLICT_ROUND_DEPENDENCY, {
                "prerequisite_match": prereq_match.match_code,
                "prerequisite_round": prerequisite_round,
                "reason": f"Cannot place Match: Round {match.round_index} cannot start before a Round {prerequisite_round} Match"
            }
        
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
            return False, CONFLICT_ROUND_DEPENDENCY, {
                "prerequisite_match": prereq_match.match_code,
                "prerequisite_round": prerequisite_round,
                "reason": f"Cannot place Match: Round {match.round_index} cannot start before a Round {prerequisite_round} Match"
            }
    
    return True, None, None


# ============================================================================
# V2 Main Algorithm
# ============================================================================


def auto_assign_v2(
    session: Session,
    schedule_version_id: int,
    clear_existing: bool = True,
    min_rest_minutes: int = DEFAULT_MIN_REST_MINUTES,
    require_court_type_match: bool = False,
) -> AutoAssignV2Result:
    """
    Auto-Assign V2: Constraint-based deterministic match-to-slot assignment.

    This is ADDITIVE on V1:
    - Uses same match ordering (stage precedence)
    - Uses same slot ordering (time → court → id)
    - Adds rest constraints and court type constraints
    - Returns structured conflicts

    Args:
        session: Database session (must be in a transaction)
        schedule_version_id: Schedule version to assign
        clear_existing: If True, clear existing auto-assign assignments first
        min_rest_minutes: Minimum rest time between matches for same team
        require_court_type_match: If True, enforce court type compatibility

    Returns:
        AutoAssignV2Result with detailed conflict information

    Raises:
        AutoAssignValidationError: If input validation fails
        AutoAssignError: If assignment fails catastrophically
    """
    start_time = datetime.utcnow()
    result = AutoAssignV2Result()

    # Verify schedule version exists
    version = session.get(ScheduleVersion, schedule_version_id)
    if not version:
        raise AutoAssignValidationError(f"Schedule version {schedule_version_id} not found")

    # Step 1: Clear existing V2 assignments if requested
    if clear_existing:
        existing_assignments_to_clear = session.exec(
            select(MatchAssignment)
            .where(MatchAssignment.schedule_version_id == schedule_version_id)
            .where(MatchAssignment.assigned_by == "AUTO_ASSIGN_V2")
        ).all()

        for assignment in existing_assignments_to_clear:
            session.delete(assignment)

        session.flush()

    # Step 2: Load and sort matches (same as V1 - deterministic ordering)
    matches = session.exec(
        select(Match).where(Match.schedule_version_id == schedule_version_id).order_by(Match.id)
    ).all()

    matches_sorted = sorted(matches, key=get_match_sort_key)
    result.total_matches = len(matches_sorted)

    # Step 3: Load and sort slots (same as V1 - deterministic ordering)
    slots = session.exec(
        select(ScheduleSlot).where(ScheduleSlot.schedule_version_id == schedule_version_id).order_by(ScheduleSlot.id)
    ).all()

    slots_sorted = sorted(slots, key=get_slot_sort_key)
    result.total_slots = len(slots_sorted)

    # Step 4: Validate inputs (reuse V1 validation)
    validate_inputs(matches_sorted, slots_sorted, schedule_version_id)

    # Step 5: Load existing assignments to track occupied slots and locked matches
    existing_assignments = session.exec(
        select(MatchAssignment).where(MatchAssignment.schedule_version_id == schedule_version_id)
    ).all()

    occupied_slot_ids = {a.slot_id for a in existing_assignments}
    
    # Manual Schedule Editor: Track locked assignments
    # Locked matches should NOT be reassigned by auto-assign (admin overrides)
    locked_match_ids = {a.match_id for a in existing_assignments if a.locked}

    # Step 6: Initialize V2 team tracker
    team_tracker = TeamAssignmentTracker()

    # Pre-populate tracker with existing assignments (not from V2)
    for assignment in existing_assignments:
        if assignment.assigned_by != "AUTO_ASSIGN_V2":
            # Get match to extract team IDs and duration
            match_for_tracking = session.get(Match, assignment.match_id)
            slot_for_tracking = session.get(ScheduleSlot, assignment.slot_id)

            if match_for_tracking and slot_for_tracking:
                team_ids = []
                if hasattr(match_for_tracking, "team_a_id") and match_for_tracking.team_a_id:
                    team_ids.append(match_for_tracking.team_a_id)
                if hasattr(match_for_tracking, "team_b_id") and match_for_tracking.team_b_id:
                    team_ids.append(match_for_tracking.team_b_id)

                if team_ids:
                    team_tracker.add_assignment(team_ids, slot_for_tracking, match_for_tracking.duration_minutes)

    # Step 7: V2 assignment loop with constraint checking
    assigned_match_ids = set()
    for match in matches_sorted:
        # Manual Schedule Editor: Skip locked matches (admin has manually assigned them)
        if match.id in locked_match_ids:
            continue
        
        assigned = False
        conflicts_for_match = []

        # Scan slots in deterministic order (same as V1)
        for slot in slots_sorted:
            compatible, reason, details = is_slot_compatible_v2(
                slot, match, occupied_slot_ids, team_tracker, min_rest_minutes, require_court_type_match
            )

            if compatible:
                # Check round dependencies
                round_deps_ok, round_deps_reason, round_deps_details = check_round_dependencies_for_auto_assign_v2(
                    session, match, slot, schedule_version_id, assigned_match_ids
                )
                if not round_deps_ok:
                    # Track conflict for reporting
                    conflict_record = {
                        "slot_id": slot.id,
                        "slot_time": f"{slot.day_date} {slot.start_time}" if slot.day_date and slot.start_time else "N/A",
                        "reason": round_deps_reason,
                        "details": round_deps_details or {},
                    }
                    conflicts_for_match.append(conflict_record)
                    continue
                # Create assignment
                assignment = MatchAssignment(
                    schedule_version_id=schedule_version_id,
                    match_id=match.id,
                    slot_id=slot.id,
                    assigned_by="AUTO_ASSIGN_V2",
                    assigned_at=datetime.utcnow(),
                )
                session.add(assignment)

                # Mark slot as occupied
                occupied_slot_ids.add(slot.id)
                assigned_match_ids.add(match.id)

                # Update team tracker
                team_ids = []
                if hasattr(match, "team_a_id") and match.team_a_id:
                    team_ids.append(match.team_a_id)
                if hasattr(match, "team_b_id") and match.team_b_id:
                    team_ids.append(match.team_b_id)

                if team_ids:
                    team_tracker.add_assignment(team_ids, slot, match.duration_minutes)

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
                # Track conflict for reporting
                conflict_record = {
                    "slot_id": slot.id,
                    "slot_time": f"{slot.day_date} {slot.start_time}" if slot.day_date and slot.start_time else "N/A",
                    "reason": reason,
                    "details": details or {},
                }
                conflicts_for_match.append(conflict_record)

                # Update statistics
                if reason == CONFLICT_REST_VIOLATION:
                    result.rest_violations += 1
                elif reason == CONFLICT_COURT_TYPE_MISMATCH:
                    result.court_type_mismatches += 1
                elif reason == CONFLICT_SLOT_OCCUPIED:
                    result.slot_occupied_count += 1

        # If not assigned, record detailed conflict
        if not assigned:
            result.unassigned_count += 1
            result.conflicts.append(
                {
                    "match_id": match.id,
                    "match_code": match.match_code,
                    "stage": match.match_type,
                    "round_index": match.round_index,
                    "sequence_in_round": match.sequence_in_round,
                    "duration_minutes": match.duration_minutes,
                    "slots_checked": len(conflicts_for_match),
                    "sample_conflicts": conflicts_for_match[:5],  # First 5 conflicts for this match
                }
            )

    # Step 8: Flush assignments to DB
    session.flush()

    # Calculate duration
    end_time = datetime.utcnow()
    result.duration_ms = int((end_time - start_time).total_seconds() * 1000)

    return result

