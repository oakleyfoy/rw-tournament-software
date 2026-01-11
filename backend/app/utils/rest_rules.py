"""
Rest Rules V1 - Team rest time enforcement for match assignments

Hard-coded rest requirements:
- WF → Scoring: 60 minutes minimum rest
- Scoring → Scoring: 90 minutes minimum rest
"""

from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set, Tuple

from sqlalchemy import case
from sqlmodel import Session, select

from app.models.match import Match
from app.models.match_assignment import MatchAssignment
from app.models.schedule_slot import ScheduleSlot

# ============================================================================
# Stage Precedence (matches must be processed in this order)
# ============================================================================

STAGE_PRECEDENCE = {"WF": 1, "MAIN": 2, "CONSOLATION": 3, "PLACEMENT": 4}


# ============================================================================
# Phase R1: Configuration (Hard-coded for V1)
# ============================================================================

REST_WF_TO_SCORING_MINUTES = 60
REST_SCORING_TO_SCORING_MINUTES = 90


# ============================================================================
# Phase R2: Team Rest State Tracking
# ============================================================================


class TeamRestState:
    """Tracks rest state for a single team"""

    def __init__(self):
        self.last_match_end_time: Optional[datetime] = None
        self.last_match_stage: Optional[str] = None

    def update(self, end_time: datetime, stage: str):
        """Update team state after match assignment"""
        self.last_match_end_time = end_time
        self.last_match_stage = stage

    def has_previous_match(self) -> bool:
        """Check if team has been assigned any match yet"""
        return self.last_match_end_time is not None


class RestStateTracker:
    """Tracks rest state for all teams during assignment process"""

    def __init__(self):
        self.team_states: Dict[int, TeamRestState] = {}

    def get_or_create_state(self, team_id: int) -> TeamRestState:
        """Get existing state or create new one for team"""
        if team_id not in self.team_states:
            self.team_states[team_id] = TeamRestState()
        return self.team_states[team_id]

    def update_team_state(self, team_id: int, end_time: datetime, stage: str):
        """Update team state after match assignment"""
        state = self.get_or_create_state(team_id)
        state.update(end_time, stage)

    def get_team_state(self, team_id: int) -> Optional[TeamRestState]:
        """Get team state if exists"""
        return self.team_states.get(team_id)


# ============================================================================
# Phase R3: Rest Compatibility Check
# ============================================================================


class RestViolation:
    """Represents a rest rule violation"""

    def __init__(
        self,
        team_id: int,
        violation_type: str,  # "REST_WF_TO_SCORING" or "REST_SCORING_TO_SCORING"
        required_rest_minutes: int,
        actual_gap_minutes: float,
        slot_start_time: datetime,
        earliest_allowed_time: datetime,
    ):
        self.team_id = team_id
        self.violation_type = violation_type
        self.required_rest_minutes = required_rest_minutes
        self.actual_gap_minutes = actual_gap_minutes
        self.slot_start_time = slot_start_time
        self.earliest_allowed_time = earliest_allowed_time


def check_rest_compatibility(
    slot: ScheduleSlot, match: Match, rest_tracker: RestStateTracker
) -> Tuple[bool, List[RestViolation]]:
    """
    Check if slot is compatible with match regarding rest requirements.

    Rules:
    - If team has no prior match: Pass
    - If last_stage=WF and current!=WF: Require 60 min rest
    - Otherwise: Require 90 min rest
    - If team_id is null (placeholder): Skip rest check for that side

    Args:
        slot: Candidate slot
        match: Match to potentially assign
        rest_tracker: Current rest state tracker

    Returns:
        (is_compatible, violations)
        - is_compatible: True if both teams pass rest check
        - violations: List of RestViolation objects (empty if compatible)
    """
    violations = []

    # Parse slot start time
    slot_datetime = datetime.fromisoformat(f"{slot.day_date}T{slot.start_time}")

    # Check team A
    if match.team_a_id is not None:
        team_a_state = rest_tracker.get_team_state(match.team_a_id)

        if team_a_state and team_a_state.has_previous_match():
            # Determine required rest
            if team_a_state.last_match_stage == "WF" and match.match_type != "WF":
                required_rest_minutes = REST_WF_TO_SCORING_MINUTES
                violation_type = "REST_WF_TO_SCORING"
            else:
                required_rest_minutes = REST_SCORING_TO_SCORING_MINUTES
                violation_type = "REST_SCORING_TO_SCORING"

            # Calculate earliest allowed time
            earliest_allowed = team_a_state.last_match_end_time + timedelta(minutes=required_rest_minutes)

            # Check if slot violates rest requirement
            if slot_datetime < earliest_allowed:
                actual_gap = (slot_datetime - team_a_state.last_match_end_time).total_seconds() / 60
                violations.append(
                    RestViolation(
                        team_id=match.team_a_id,
                        violation_type=violation_type,
                        required_rest_minutes=required_rest_minutes,
                        actual_gap_minutes=actual_gap,
                        slot_start_time=slot_datetime,
                        earliest_allowed_time=earliest_allowed,
                    )
                )

    # Check team B
    if match.team_b_id is not None:
        team_b_state = rest_tracker.get_team_state(match.team_b_id)

        if team_b_state and team_b_state.has_previous_match():
            # Determine required rest
            if team_b_state.last_match_stage == "WF" and match.match_type != "WF":
                required_rest_minutes = REST_WF_TO_SCORING_MINUTES
                violation_type = "REST_WF_TO_SCORING"
            else:
                required_rest_minutes = REST_SCORING_TO_SCORING_MINUTES
                violation_type = "REST_SCORING_TO_SCORING"

            # Calculate earliest allowed time
            earliest_allowed = team_b_state.last_match_end_time + timedelta(minutes=required_rest_minutes)

            # Check if slot violates rest requirement
            if slot_datetime < earliest_allowed:
                actual_gap = (slot_datetime - team_b_state.last_match_end_time).total_seconds() / 60
                violations.append(
                    RestViolation(
                        team_id=match.team_b_id,
                        violation_type=violation_type,
                        required_rest_minutes=required_rest_minutes,
                        actual_gap_minutes=actual_gap,
                        slot_start_time=slot_datetime,
                        earliest_allowed_time=earliest_allowed,
                    )
                )

    is_compatible = len(violations) == 0
    return is_compatible, violations


# ============================================================================
# Phase R4: Assignment Strategy (Deterministic with Rest)
# ============================================================================


class AssignmentResult:
    """Result of attempting to assign a match"""

    def __init__(
        self,
        match_id: int,
        assigned: bool,
        slot_id: Optional[int] = None,
        failure_reason: Optional[str] = None,
        rest_violations: Optional[List[RestViolation]] = None,
    ):
        self.match_id = match_id
        self.assigned = assigned
        self.slot_id = slot_id
        self.failure_reason = failure_reason
        self.rest_violations = rest_violations or []


def auto_assign_with_rest(session: Session, schedule_version_id: int, clear_existing: bool = True) -> Dict:
    """
    Auto-assign matches to slots with rest rules and day-targeting enforcement.

    Strategy:
    1. Clear existing assignments if requested
    2. Load matches in deterministic order
    3. Load slots in deterministic order
    4. For each match, find compatible slots (duration + rest)
    5. Sort compatible slots by: preference_score, day_date, start_time, court_number, id
    6. Assign to first slot in sorted list
    7. Track team rest state as assignments are made
    8. Report unassigned matches with detailed reasons

    Day-Targeting (V1):
    - If match has preferred_day set: prefer slots on that weekday (0=Monday, 6=Sunday)
    - Preferred day acts as tie-breaker only; rest rules remain mandatory

    Args:
        session: Database session
        schedule_version_id: Schedule version ID
        clear_existing: If true, clear all assignments first

    Returns:
        Dictionary with:
        - assigned_count: int
        - unassigned_count: int
        - unassigned_reasons: Dict[str, List[match_info]]
        - rest_violations_summary: Dict
        - preferred_day_metrics: Dict with hits/misses/applied_count
    """
    # Handle existing assignments
    existing_assignments = []
    assigned_match_ids: Set[int] = set()

    if clear_existing:
        # Clear existing assignments
        existing_assignments_to_clear = session.exec(
            select(MatchAssignment).where(MatchAssignment.schedule_version_id == schedule_version_id)
        ).all()
        for assignment in existing_assignments_to_clear:
            session.delete(assignment)
        session.commit()
    else:
        # Load existing assignments to rebuild rest state
        existing_assignments = session.exec(
            select(MatchAssignment).where(MatchAssignment.schedule_version_id == schedule_version_id)
        ).all()

        # Track already-assigned match IDs
        for assignment in existing_assignments:
            assigned_match_ids.add(assignment.match_id)

    # Load matches in deterministic order (WF first, then MAIN, etc.)
    all_matches = session.exec(
        select(Match)
        .where(Match.schedule_version_id == schedule_version_id)
        .order_by(
            case(
                (Match.match_type == "WF", 1),
                (Match.match_type == "MAIN", 2),
                (Match.match_type == "CONSOLATION", 3),
                (Match.match_type == "PLACEMENT", 4),
                else_=999,
            ),
            Match.round_number,
            Match.sequence_in_round,
            Match.id,
        )
    ).all()

    # Filter to only unassigned matches when not clearing
    if clear_existing:
        matches = all_matches
    else:
        matches = [m for m in all_matches if m.id not in assigned_match_ids]

    # Load slots in deterministic order
    slots = session.exec(
        select(ScheduleSlot)
        .where(ScheduleSlot.schedule_version_id == schedule_version_id, ScheduleSlot.is_active)
        .order_by(ScheduleSlot.day_date, ScheduleSlot.start_time, ScheduleSlot.court_number, ScheduleSlot.id)
    ).all()

    # Track which slots are occupied
    occupied_slot_ids: Set[int] = set()

    # Rebuild rest state from existing assignments (if any)
    rest_tracker = RestStateTracker()

    if not clear_existing and existing_assignments:
        # Build lookup maps
        slot_map = {slot.id: slot for slot in slots}
        match_map = {match.id: match for match in all_matches}

        # Sort existing assignments chronologically by slot time
        assignments_with_time = []
        for assignment in existing_assignments:
            slot = slot_map.get(assignment.slot_id)
            match = match_map.get(assignment.match_id)
            if slot and match:
                occupied_slot_ids.add(assignment.slot_id)
                slot_datetime = datetime.fromisoformat(f"{slot.day_date}T{slot.start_time}")
                end_datetime = slot_datetime + timedelta(minutes=match.duration_minutes)
                assignments_with_time.append({"match": match, "end_time": end_datetime})

        # Sort by end time to process in chronological order
        assignments_with_time.sort(key=lambda x: x["end_time"])

        # Update rest tracker with existing assignments
        for item in assignments_with_time:
            match = item["match"]
            end_time = item["end_time"]
            # Update team rest state for both teams
            if match.team_a_id is not None:
                rest_tracker.update_team_state(match.team_a_id, end_time, match.match_type)
            if match.team_b_id is not None:
                rest_tracker.update_team_state(match.team_b_id, end_time, match.match_type)

    # Track assignment results
    results: List[AssignmentResult] = []
    assigned_count = 0
    unassigned_by_reason: Dict[str, List[dict]] = {}

    # Phase D6: Track preferred day metrics
    preferred_day_hits = 0
    preferred_day_misses = 0

    # Assign each match
    for match in matches:
        assigned = False

        # Phase D4: Build list of compatible slots with preference scoring
        compatible_slots = []

        for slot in slots:
            # Skip if slot already occupied
            if slot.id in occupied_slot_ids:
                continue

            # Check duration compatibility
            if slot.block_minutes < match.duration_minutes:
                continue

            # Check rest compatibility
            rest_compatible, rest_violations = check_rest_compatibility(slot, match, rest_tracker)

            if not rest_compatible:
                # This slot violates rest rules, skip it
                continue

            # Slot is compatible! Calculate preference score
            # Phase D3: Derive slot weekday from day_date (0=Monday, 6=Sunday)
            slot_date = datetime.fromisoformat(str(slot.day_date)).date()
            slot_weekday = slot_date.weekday()  # 0=Monday, 6=Sunday

            # Phase D4: Calculate preference score
            if match.preferred_day is None:
                preference_score = 0  # No preference
            else:
                preference_score = 0 if slot_weekday == match.preferred_day else 1

            compatible_slots.append({"slot": slot, "preference_score": preference_score, "slot_weekday": slot_weekday})

        # Sort compatible slots by preference score, then deterministic order
        compatible_slots.sort(
            key=lambda x: (
                x["preference_score"],  # Preferred day first
                x["slot"].day_date,  # Earlier date first
                x["slot"].start_time,  # Earlier time first
                x["slot"].court_number,  # Lower court number first
                x["slot"].id,  # Lower ID first (final tie-breaker)
            )
        )

        # Assign to first compatible slot (if any)
        if compatible_slots:
            best_slot_info = compatible_slots[0]
            slot = best_slot_info["slot"]

            # Phase D6: Track preferred day hits/misses
            if match.preferred_day is not None:
                if best_slot_info["preference_score"] == 0:
                    preferred_day_hits += 1
                else:
                    preferred_day_misses += 1

            # Create assignment
            assignment = MatchAssignment(schedule_version_id=schedule_version_id, match_id=match.id, slot_id=slot.id)
            session.add(assignment)
            occupied_slot_ids.add(slot.id)
            assigned = True
            assigned_count += 1

            # Update team rest states
            slot_datetime = datetime.fromisoformat(f"{slot.day_date}T{slot.start_time}")
            end_time = slot_datetime + timedelta(minutes=match.duration_minutes)

            if match.team_a_id is not None:
                rest_tracker.update_team_state(match.team_a_id, end_time, match.match_type)

            if match.team_b_id is not None:
                rest_tracker.update_team_state(match.team_b_id, end_time, match.match_type)

            results.append(AssignmentResult(match_id=match.id, assigned=True, slot_id=slot.id))

        # If not assigned, record failure reason

        if not assigned:
            # Determine failure reason
            # Check if any slot had sufficient duration
            duration_ok_slots = [
                s for s in slots if s.id not in occupied_slot_ids and s.block_minutes >= match.duration_minutes
            ]

            if not duration_ok_slots:
                failure_reason = "NO_SLOT_WITH_DURATION"
                rest_violations_list = []
            else:
                # Duration OK but rest failed - find violations from best candidate slot
                failure_reason = "NO_REST_COMPATIBLE_SLOT"
                # Check first available slot with correct duration for violation details
                best_slot = duration_ok_slots[0]
                _, rest_violations_list = check_rest_compatibility(best_slot, match, rest_tracker)

            results.append(
                AssignmentResult(
                    match_id=match.id,
                    assigned=False,
                    failure_reason=failure_reason,
                    rest_violations=rest_violations_list,
                )
            )

            # Add to unassigned reasons
            if failure_reason not in unassigned_by_reason:
                unassigned_by_reason[failure_reason] = []

            unassigned_by_reason[failure_reason].append(
                {
                    "match_id": match.id,
                    "match_code": match.match_code,
                    "duration_minutes": match.duration_minutes,
                    "team_a_id": match.team_a_id,
                    "team_b_id": match.team_b_id,
                    "rest_violations": [
                        {
                            "team_id": v.team_id,
                            "violation_type": v.violation_type,
                            "required_rest_minutes": v.required_rest_minutes,
                            "actual_gap_minutes": v.actual_gap_minutes,
                        }
                        for v in rest_violations_list
                    ],
                }
            )

    session.commit()

    # Build rest violations summary
    rest_blocked_wf_scoring = 0
    rest_blocked_scoring_scoring = 0

    for result in results:
        if not result.assigned and result.failure_reason == "NO_REST_COMPATIBLE_SLOT":
            for violation in result.rest_violations:
                if violation.violation_type == "REST_WF_TO_SCORING":
                    rest_blocked_wf_scoring += 1
                elif violation.violation_type == "REST_SCORING_TO_SCORING":
                    rest_blocked_scoring_scoring += 1

    unassigned_count = len(matches) - assigned_count

    return {
        "assigned_count": assigned_count,
        "unassigned_count": unassigned_count,
        "unassigned_reasons": unassigned_by_reason,
        "rest_violations_summary": {
            "wf_to_scoring_violations": rest_blocked_wf_scoring,
            "scoring_to_scoring_violations": rest_blocked_scoring_scoring,
            "total_rest_blocked": rest_blocked_wf_scoring + rest_blocked_scoring_scoring,
        },
        "preferred_day_metrics": {
            "preferred_day_hits": preferred_day_hits,
            "preferred_day_misses": preferred_day_misses,
            "preferred_day_applied_count": preferred_day_hits + preferred_day_misses,
        },
    }
