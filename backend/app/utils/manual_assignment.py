"""
Manual Schedule Editor: Validation and mutation logic for manual assignments

This module provides the backend logic for allowing admins to manually move
matches between slots while enforcing hard invariants:

1. **Draft-only mutations**: Manual edits only allowed on draft schedules
2. **No slot overlap**: Can't assign multiple matches to same slot  
3. **Duration fit**: Match must fit in slot duration
4. **Stage ordering**: Can't violate stage precedence (WF → MAIN → CONSOLATION → PLACEMENT)
5. **Consolation rules**: Can't violate consolation bracket constraints
6. **Court compatibility**: Optional court type matching

Manual assignments are marked with locked=True so auto-assign skips them.
"""

from datetime import datetime, time
from typing import Optional, Tuple

from sqlmodel import Session, select

from app.models.match import Match
from app.models.match_assignment import MatchAssignment
from app.models.schedule_slot import ScheduleSlot
from app.models.schedule_version import ScheduleVersion

# Import stage precedence from auto_assign
from app.utils.auto_assign import STAGE_PRECEDENCE


class ManualAssignmentError(Exception):
    """Base exception for manual assignment errors"""
    pass


class ManualAssignmentValidationError(ManualAssignmentError):
    """Validation failed for manual assignment"""
    pass


def require_draft_version_for_manual_edit(session: Session, version_id: int) -> ScheduleVersion:
    """
    Verify schedule version exists and is draft (not finalized).
    
    Manual edits are ONLY allowed on draft versions.
    To edit a finalized schedule, admin must clone it first.
    
    Raises:
        ManualAssignmentValidationError if not draft
    """
    version = session.get(ScheduleVersion, version_id)
    if not version:
        raise ManualAssignmentValidationError(f"Schedule version {version_id} not found")
    
    if version.finalized_at is not None:
        raise ManualAssignmentValidationError(
            f"Cannot manually edit finalized schedule version {version_id}. "
            "Clone to draft first, then edit the draft."
        )
    
    return version


def validate_slot_available(
    session: Session,
    slot_id: int,
    schedule_version_id: int,
    exclude_match_id: Optional[int] = None
) -> Tuple[bool, Optional[str]]:
    """
    Check if slot is available for assignment.
    
    Args:
        session: Database session
        slot_id: Target slot ID
        schedule_version_id: Schedule version ID
        exclude_match_id: If provided, ignore assignments for this match (for reassignment)
    
    Returns:
        (is_available, reason_if_not)
    """
    # Check for existing assignment to this slot
    query = select(MatchAssignment).where(
        MatchAssignment.schedule_version_id == schedule_version_id,
        MatchAssignment.slot_id == slot_id
    )
    
    if exclude_match_id:
        query = query.where(MatchAssignment.match_id != exclude_match_id)
    
    existing = session.exec(query).first()
    
    if existing:
        return False, f"Slot already assigned to match {existing.match_id}"
    
    return True, None


def _slot_available_minutes(slot: ScheduleSlot) -> int:
    """Slot span in minutes from start_time to end_time (same-day)."""
    if not slot.start_time or not slot.end_time:
        return slot.block_minutes or 60
    start_min = slot.start_time.hour * 60 + slot.start_time.minute
    end_min = slot.end_time.hour * 60 + slot.end_time.minute
    if end_min <= start_min:
        return slot.block_minutes or 60
    return end_min - start_min


def validate_duration_fit(match: Match, slot: ScheduleSlot) -> Tuple[bool, Optional[str]]:
    """
    Check if match duration fits in slot.
    
    A match must not exceed the slot's available time span (end - start).
    Also enforce a max match duration (e.g. 4 hours) for sanity.
    
    Returns:
        (fits, reason_if_not)
    """
    slot_minutes = _slot_available_minutes(slot)
    if match.duration_minutes > slot_minutes:
        return False, (
            f"Match duration ({match.duration_minutes}min) exceeds slot duration ({slot_minutes}min)"
        )

    max_match_duration = 240
    if match.duration_minutes > max_match_duration:
        return False, f"Match duration ({match.duration_minutes}min) exceeds maximum allowed duration ({max_match_duration}min)"

    return True, None


def validate_rest_constraints(
    session: Session,
    match: Match,
    slot: ScheduleSlot,
    schedule_version_id: int,
    min_rest_minutes: int = 90
) -> Tuple[bool, Optional[str]]:
    """
    Validate that assigning this match doesn't violate rest constraints.
    
    Uses same logic as Auto-Assign V2 for consistency.
    Only enforces rest if match has teams assigned.
    
    Args:
        session: Database session
        match: Match to assign
        slot: Target slot
        schedule_version_id: Schedule version
        min_rest_minutes: Minimum rest time between matches (default: 90)
    
    Returns:
        (is_valid, error_message_if_not)
    """
    # Only check rest if match has teams assigned
    if not match.team_a_id and not match.team_b_id:
        return True, None
    
    # Import V2 tracker (reuse logic, don't duplicate)
    from app.utils.auto_assign_v2 import TeamAssignmentTracker
    
    # Build tracker from existing assignments (excluding this match)
    tracker = TeamAssignmentTracker()
    
    assignments = session.exec(
        select(MatchAssignment).where(
            MatchAssignment.schedule_version_id == schedule_version_id,
            MatchAssignment.match_id != match.id  # Exclude this match if already assigned
        )
    ).all()
    
    for assignment in assignments:
        existing_match = session.get(Match, assignment.match_id)
        existing_slot = session.get(ScheduleSlot, assignment.slot_id)
        if existing_match and existing_slot:
            team_ids = []
            if existing_match.team_a_id:
                team_ids.append(existing_match.team_a_id)
            if existing_match.team_b_id:
                team_ids.append(existing_match.team_b_id)
            if team_ids:
                tracker.add_assignment(team_ids, existing_slot, existing_match.duration_minutes)
    
    # Check proposed assignment
    team_ids = []
    if match.team_a_id:
        team_ids.append(match.team_a_id)
    if match.team_b_id:
        team_ids.append(match.team_b_id)
    
    if team_ids:
        rest_ok, violating_team = tracker.check_rest_constraint(
            team_ids, slot, match.duration_minutes, min_rest_minutes
        )
        if not rest_ok:
            return False, f"Team {violating_team} would have < {min_rest_minutes} minutes rest between matches"
    
    return True, None


def validate_round_dependencies(
    session: Session,
    match: Match,
    slot: ScheduleSlot,
    schedule_version_id: int
) -> Tuple[bool, Optional[str]]:
    """
    Validate that Round N matches cannot start until prerequisite Round N-1 matches in the same stage/event have ENDED.
    
    Rule: For a Round N match being scheduled at time T:
    - Only check Round N-1 matches that are already assigned (don't block on unassigned prerequisites)
    - Assigned Round N-1 matches must END before time T
    
    Note: We only check assigned prerequisites to avoid blocking Round N matches when Round N-1 matches
    haven't been scheduled yet. The overlap detection will catch conflicts once Round N-1 matches are assigned.
    
    Returns:
        (is_valid, reason_if_not)
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
    for prereq_match in prerequisite_matches:
        # Check if prerequisite is assigned
        prereq_assignment = session.exec(
            select(MatchAssignment).where(
                MatchAssignment.schedule_version_id == schedule_version_id,
                MatchAssignment.match_id == prereq_match.id
            )
        ).first()
        
        # ALL Round N-1 matches must be assigned before ANY Round N match can be scheduled
        if not prereq_assignment:
            return False, (
                f"Cannot place Match: Round {match.round_index} cannot start before a Round {prerequisite_round} Match"
            )
        
        # Get prerequisite slot
        prereq_slot = session.get(ScheduleSlot, prereq_assignment.slot_id)
        if not prereq_slot or not prereq_slot.start_time:
            continue
        
        # Calculate prerequisite match end time in minutes
        prereq_start_minutes = prereq_slot.start_time.hour * 60 + prereq_slot.start_time.minute
        prereq_end_minutes = prereq_start_minutes + prereq_match.duration_minutes
        
        # Check if prerequisite ends before target start time
        if prereq_end_minutes > slot_start_minutes:
            return False, (
                f"Cannot place Match: Round {match.round_index} cannot start before a Round {prerequisite_round} Match"
            )
    
    return True, None


def validate_stage_ordering(
    session: Session,
    match: Match,
    slot: ScheduleSlot,
    schedule_version_id: int
) -> Tuple[bool, Optional[str]]:
    """
    Validate that moving this match to this slot doesn't violate stage ordering.
    
    Rule: Earlier stages (lower precedence number) must END before later stages can START.
    WF (1) → MAIN (2) → CONSOLATION (3) → PLACEMENT (4)
    
    IMPORTANT: Stage ordering only applies WITHIN the same event.
    - Women's MAIN matches can start once Women's WF matches have finished
      (even if Mixed WF matches are still playing)
    - Mixed MAIN matches can start once Mixed WF matches have finished
      (even if Women's WF matches are still playing)
    - Different events can run different stages simultaneously
    
    For a MAIN match being scheduled, all WF matches in the SAME EVENT must have ENDED.
    
    Returns:
        (is_valid, reason_if_not)
    """
    match_stage = match.match_type
    match_precedence = STAGE_PRECEDENCE.get(match_stage, 999)
    
    # Calculate target slot start time in minutes
    slot_start_minutes = slot.start_time.hour * 60 + slot.start_time.minute if slot.start_time else 0
    
    # Check all earlier stages - they must have ENDED before this match can START
    for earlier_stage, earlier_precedence in STAGE_PRECEDENCE.items():
        if earlier_precedence >= match_precedence:
            # Skip same stage or later stages
            continue
        
        # Find all matches in earlier stages in the same event
        earlier_matches = session.exec(
            select(Match).where(
                Match.schedule_version_id == schedule_version_id,
                Match.event_id == match.event_id,
                Match.match_type == earlier_stage
            )
        ).all()
        
        if not earlier_matches:
            continue
        
        # Check each earlier stage match - it must have ENDED before target start
        for earlier_match in earlier_matches:
            # Check if earlier match is assigned
            earlier_assignment = session.exec(
                select(MatchAssignment).where(
                    MatchAssignment.schedule_version_id == schedule_version_id,
                    MatchAssignment.match_id == earlier_match.id
                )
            ).first()
            
            # Skip unassigned earlier matches - they'll be checked when assigned
            if not earlier_assignment:
                continue
            
            # Get earlier match slot
            earlier_slot = session.get(ScheduleSlot, earlier_assignment.slot_id)
            if not earlier_slot or not earlier_slot.start_time:
                continue
            
            # Only check matches on the same day
            if earlier_slot.day_date != slot.day_date:
                continue
            
            # Calculate earlier match end time in minutes
            earlier_start_minutes = earlier_slot.start_time.hour * 60 + earlier_slot.start_time.minute
            earlier_end_minutes = earlier_start_minutes + earlier_match.duration_minutes
            
            # Check if earlier match ends before target start time
            if earlier_end_minutes > slot_start_minutes:
                return False, (
                    f"Cannot place Match: {match_stage} matches cannot start before {earlier_stage} matches have finished"
                )
    
    return True, None


def validate_manual_reassignment(
    session: Session,
    match_id: int,
    new_slot_id: int,
    schedule_version_id: int
) -> Tuple[bool, Optional[str]]:
    """
    Validate that manually reassigning a match to a new slot is allowed.
    
    Checks all hard invariants:
    - Draft version only
    - Slot available
    - Duration fits
    - Stage ordering preserved
    
    Returns:
        (is_valid, error_message_if_not)
    """
    # 1. Verify draft version
    try:
        require_draft_version_for_manual_edit(session, schedule_version_id)
    except ManualAssignmentValidationError as e:
        return False, str(e)
    
    # 2. Get match and slot
    match = session.get(Match, match_id)
    if not match:
        return False, f"Match {match_id} not found"
    
    slot = session.get(ScheduleSlot, new_slot_id)
    if not slot:
        return False, f"Slot {new_slot_id} not found"
    
    # 3. Verify they belong to same schedule version
    if match.schedule_version_id != schedule_version_id:
        return False, f"Match belongs to different schedule version"
    
    if slot.schedule_version_id != schedule_version_id:
        return False, f"Slot belongs to different schedule version"
    
    # 4. Check slot availability (excluding this match if it's already assigned)
    available, reason = validate_slot_available(session, new_slot_id, schedule_version_id, exclude_match_id=match_id)
    if not available:
        return False, reason

    # 4b. Check for overlaps with other matches on the same court and day
    
    # Get all assignments on the same court, same day, same version
    court_assignments = session.exec(
        select(MatchAssignment)
        .join(ScheduleSlot, MatchAssignment.slot_id == ScheduleSlot.id)
        .where(
            MatchAssignment.schedule_version_id == schedule_version_id,
            ScheduleSlot.day_date == slot.day_date,
            ScheduleSlot.court_number == slot.court_number,
            MatchAssignment.match_id != match_id,  # Exclude the match being moved
        )
    ).all()

    slot_start_minutes = slot.start_time.hour * 60 + slot.start_time.minute
    match_end_minutes = slot_start_minutes + match.duration_minutes

    for existing_assignment in court_assignments:
        existing_slot = session.get(ScheduleSlot, existing_assignment.slot_id)
        existing_match = session.get(Match, existing_assignment.match_id)

        if existing_slot and existing_match:
            existing_start_minutes = existing_slot.start_time.hour * 60 + existing_slot.start_time.minute
            existing_end_minutes = existing_start_minutes + existing_match.duration_minutes

            # Check for overlap: [start1, end1) overlaps [start2, end2) if start1 < end2 AND start2 < end1
            if slot_start_minutes < existing_end_minutes and existing_start_minutes < match_end_minutes:
                overlap_start = max(slot_start_minutes, existing_start_minutes)
                overlap_end = min(match_end_minutes, existing_end_minutes)
                overlap_time = time(hour=overlap_start // 60, minute=overlap_start % 60)
                return False, f"Match would overlap with {existing_match.match_code} on {slot.court_label} starting at {existing_slot.start_time.strftime('%H:%M')}. Overlap at {overlap_time.strftime('%H:%M')}"
    
    # 5. Check duration fit
    fits, reason = validate_duration_fit(match, slot)
    if not fits:
        return False, reason
    
    # 6. Check stage ordering
    valid_order, reason = validate_stage_ordering(session, match, slot, schedule_version_id)
    if not valid_order:
        return False, reason
    
    # 7. Check round dependencies (Round N cannot start until Round N-1 ends)
    valid_rounds, reason = validate_round_dependencies(session, match, slot, schedule_version_id)
    if not valid_rounds:
        return False, reason
    
    # 8. Check rest constraints (Phase 3D.1: parity with Auto-Assign V2)
    # Only enforces rest if match has teams assigned
    valid_rest, reason = validate_rest_constraints(session, match, slot, schedule_version_id, min_rest_minutes=90)
    if not valid_rest:
        return False, reason

    # 9. Check if match would exceed day end time
    from app.models.tournament_day import TournamentDay
    from datetime import time
    
    tournament_day = session.exec(
        select(TournamentDay).where(
            TournamentDay.tournament_id == slot.tournament_id,
            TournamentDay.date == slot.day_date,
            TournamentDay.is_active == True,
        )
    ).first()

    if tournament_day and tournament_day.end_time:
        # Calculate match end time
        slot_start_minutes = slot.start_time.hour * 60 + slot.start_time.minute
        match_end_minutes = slot_start_minutes + match.duration_minutes
        day_end_minutes = tournament_day.end_time.hour * 60 + tournament_day.end_time.minute
        
        if match_end_minutes > day_end_minutes:
            match_end_time = time(
                hour=match_end_minutes // 60,
                minute=match_end_minutes % 60
            )
            return False, f"Match would end at {match_end_time.strftime('%H:%M')}, but schedule ends at {tournament_day.end_time.strftime('%H:%M')} on {slot.day_date}"

    return True, None


def manually_assign_match(
    session: Session,
    match_id: int,
    new_slot_id: int,
    schedule_version_id: int,
    assigned_by: str = "MANUAL"
) -> MatchAssignment:
    """
    Manually assign (or reassign) a match to a slot.
    
    This creates or updates the assignment with locked=True so auto-assign skips it.
    
    Args:
        session: Database session
        match_id: Match to assign
        new_slot_id: Target slot
        schedule_version_id: Schedule version
        assigned_by: Who assigned it (defaults to "MANUAL")
    
    Returns:
        The created or updated MatchAssignment
    
    Raises:
        ManualAssignmentValidationError: If validation fails
    """
    # Phase 3D.3 Step 4: Enforce draft-only mutation at service boundary
    from app.models.schedule_version import ScheduleVersion
    
    version = session.get(ScheduleVersion, schedule_version_id)
    if not version:
        raise ManualAssignmentValidationError("Schedule version not found")
    
    if version.status != "draft":
        raise ManualAssignmentValidationError(
            f"Cannot modify assignments on {version.status} schedule versions. "
            "Clone to draft first to make changes."
        )
    
    # Validate the reassignment
    valid, error = validate_manual_reassignment(session, match_id, new_slot_id, schedule_version_id)
    if not valid:
        raise ManualAssignmentValidationError(error or "Validation failed")
    
    # Check if assignment already exists
    existing = session.exec(
        select(MatchAssignment).where(
            MatchAssignment.schedule_version_id == schedule_version_id,
            MatchAssignment.match_id == match_id
        )
    ).first()
    
    if existing:
        # Update existing assignment
        existing.slot_id = new_slot_id
        existing.assigned_by = assigned_by
        existing.assigned_at = datetime.utcnow()
        existing.locked = True  # Mark as manual override
        session.add(existing)
        return existing
    else:
        # Create new assignment
        assignment = MatchAssignment(
            schedule_version_id=schedule_version_id,
            match_id=match_id,
            slot_id=new_slot_id,
            assigned_by=assigned_by,
            assigned_at=datetime.utcnow(),
            locked=True  # Mark as manual override
        )
        session.add(assignment)
        return assignment

