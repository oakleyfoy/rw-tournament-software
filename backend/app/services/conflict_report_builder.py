"""
Conflict Report Builder Service - Phase 3D.1 Extraction

Pure deterministic service layer for conflict computation.
This service:
- Takes only IDs + Session as input (no request context)
- Returns identical output to the original helper
- Does NOT mutate the database
- Uses explicit sorting for deterministic output

Extracted from: app/utils/conflict_report.compute_conflict_report
"""

from datetime import datetime
from typing import List, Optional

from sqlmodel import Session, select

from app.models.match import Match
from app.models.match_assignment import MatchAssignment
from app.models.schedule_slot import ScheduleSlot
from app.utils.auto_assign import STAGE_PRECEDENCE, get_match_sort_key, get_slot_sort_key
from app.utils.conflict_report import (
    ConflictReportSummary,
    ConflictReportV1,
    OrderingIntegrity,
    OrderingViolation,
    SlotPressure,
    StageTimeline,
    TeamConflictDetail,
    TeamConflictsSummary,
    UnassignedMatchDetail,
)

# Phase 3D.1: Pydantic models remain in conflict_report.py (shared by multiple modules)


class ConflictReportBuilder:
    """
    Pure deterministic computation of conflict reports.
    
    Phase 3D.1 Step B: Contains full computation logic (moved from helper).
    """
    
    def compute(
        self,
        session: Session,
        *,
        tournament_id: int,
        schedule_version_id: int,
        event_id: Optional[int] = None,
    ) -> ConflictReportV1:
        """
        Compute deterministic conflict report for a schedule version.
        
        Phase 3D.1 Step B: Full computation logic (verbatim copy from helper).
        
        Args:
            session: Database session (read-only)
            tournament_id: Tournament ID
            schedule_version_id: Schedule version ID
            event_id: Optional event filter
        
        Returns:
            ConflictReportV1 with all conflict details
        
        Guarantees:
            - No database mutations (no add/commit/delete)
            - Deterministic output (same input → same output)
            - Locked assignments treated as immutable facts
        """
        # ====================================================================
        # Phase 3D.1 Step B: Verbatim copy of compute_conflict_report logic
        # ====================================================================
        
        # Build match query
        match_query = select(Match).where(
            Match.tournament_id == tournament_id, Match.schedule_version_id == schedule_version_id
        )
        if event_id:
            match_query = match_query.where(Match.event_id == event_id)

        matches = session.exec(match_query).all()

        # Get all slots
        slot_query = select(ScheduleSlot).where(
            ScheduleSlot.tournament_id == tournament_id,
            ScheduleSlot.schedule_version_id == schedule_version_id,
            ScheduleSlot.is_active,
        )
        slots = session.exec(slot_query).all()

        # Get all assignments
        assignment_query = select(MatchAssignment).where(MatchAssignment.schedule_version_id == schedule_version_id)
        assignments = session.exec(assignment_query).all()

        # Build assignment maps
        match_to_assignment = {a.match_id: a for a in assignments}
        slot_to_assignment = {a.slot_id: a for a in assignments}

        # Separate assigned and unassigned matches
        assigned_matches = [m for m in matches if m.id in match_to_assignment]
        unassigned_matches = [m for m in matches if m.id not in match_to_assignment]

        # ========================================================================
        # SECTION 1: Summary
        # ========================================================================
        total_matches = len(matches)
        total_slots = len(slots)
        assigned_count = len(assigned_matches)
        unassigned_count = len(unassigned_matches)
        assignment_rate = round((assigned_count / total_matches * 100), 1) if total_matches > 0 else 0.0

        summary = ConflictReportSummary(
            tournament_id=tournament_id,
            schedule_version_id=schedule_version_id,
            total_slots=total_slots,
            total_matches=total_matches,
            assigned_matches=assigned_count,
            unassigned_matches=unassigned_count,
            assignment_rate=assignment_rate,
        )

        # ========================================================================
        # SECTION 2: Unassigned matches with reasons
        # ========================================================================
        unassigned_details = []

        for match in unassigned_matches:
            # Compute best-effort reason
            reason = "UNKNOWN"

            # Check if there are any free slots with sufficient duration
            free_slots = [s for s in slots if s.id not in slot_to_assignment]
            compatible_slots = [s for s in free_slots if s.block_minutes >= match.duration_minutes]

            if len(free_slots) == 0:
                reason = "SLOTS_EXHAUSTED"
            elif len(compatible_slots) == 0:
                reason = "DURATION_TOO_LONG"
            else:
                reason = "NO_COMPATIBLE_SLOT"

            unassigned_details.append(
                UnassignedMatchDetail(
                    match_id=match.id,
                    stage=match.match_type,
                    round_index=match.round_index,
                    sequence_in_round=match.sequence_in_round,
                    duration_minutes=match.duration_minutes,
                    reason=reason,
                    notes=None,
                )
            )

        # ========================================================================
        # SECTION 3: Slot Pressure
        # ========================================================================
        unused_slots = [s for s in slots if s.id not in slot_to_assignment]

        # Group by day
        unused_by_day: dict[str, int] = {}
        for slot in unused_slots:
            day_str = slot.day_date.isoformat()
            unused_by_day[day_str] = unused_by_day.get(day_str, 0) + 1

        # Group by court
        unused_by_court: dict[str, int] = {}
        for slot in unused_slots:
            unused_by_court[slot.court_label] = unused_by_court.get(slot.court_label, 0) + 1

        # Find longest unassigned match duration
        longest_match_duration = max([m.duration_minutes for m in unassigned_matches], default=0)

        # Find max slot duration
        max_slot_duration = max([s.block_minutes for s in slots], default=0)

        # Count insufficient duration slots
        insufficient_duration_slots = [
            s for s in unused_slots if longest_match_duration > 0 and s.block_minutes < longest_match_duration
        ]

        slot_pressure = SlotPressure(
            unused_slots_count=len(unused_slots),
            unused_slots_by_day=unused_by_day,
            unused_slots_by_court=unused_by_court,
            insufficient_duration_slots_count=len(insufficient_duration_slots),
            longest_match_duration=longest_match_duration,
            max_slot_duration=max_slot_duration,
        )

        # ========================================================================
        # SECTION 4: Stage Timeline
        # ========================================================================
        # Build slot map for lookup
        slot_map = {s.id: s for s in slots}

        # Group matches by stage
        stage_groups: dict[str, List[Match]] = {}
        for match in matches:
            stage = match.match_type
            if stage not in stage_groups:
                stage_groups[stage] = []
            stage_groups[stage].append(match)

        stage_timeline_list = []

        # Track assigned match times by stage for spillover detection
        stage_time_ranges: dict[str, tuple[datetime, datetime]] = {}

        for stage in sorted(stage_groups.keys(), key=lambda s: STAGE_PRECEDENCE.get(s, 999)):
            stage_matches = stage_groups[stage]
            assigned_in_stage = [m for m in stage_matches if m.id in match_to_assignment]
            unassigned_in_stage = [m for m in stage_matches if m.id not in match_to_assignment]

            # Find first and last assigned times
            first_time = None
            last_time = None

            if assigned_in_stage:
                times = []
                for match in assigned_in_stage:
                    assignment = match_to_assignment[match.id]
                    slot = slot_map.get(assignment.slot_id)
                    if slot:
                        dt = datetime.combine(slot.day_date, slot.start_time)
                        times.append(dt)

                if times:
                    times.sort()
                    first_time = times[0].isoformat()
                    last_time = times[-1].isoformat()
                    stage_time_ranges[stage] = (times[0], times[-1])

            stage_timeline_list.append(
                StageTimeline(
                    stage=stage,
                    first_assigned_start_time=first_time,
                    last_assigned_start_time=last_time,
                    assigned_count=len(assigned_in_stage),
                    unassigned_count=len(unassigned_in_stage),
                    spillover_warning=False,  # Will compute in next pass
                )
            )

        # Detect spillover: earlier-priority stage starts after later-priority stage
        for i, timeline in enumerate(stage_timeline_list):
            stage = timeline.stage
            if stage not in stage_time_ranges:
                continue

            stage_order = STAGE_PRECEDENCE.get(stage, 999)
            stage_first, stage_last = stage_time_ranges[stage]

            # Check if any later-priority stage has matches that start before this stage
            for other_stage, (other_first, other_last) in stage_time_ranges.items():
                other_order = STAGE_PRECEDENCE.get(other_stage, 999)

                # If other stage has later priority (higher number) but starts earlier
                if other_order > stage_order and other_first < stage_first:
                    timeline.spillover_warning = True
                    break

        # ========================================================================
        # SECTION 5: Ordering Integrity
        # ========================================================================
        violations = []
        deterministic_order_ok = True

        # Get assigned matches sorted by their deterministic match order
        assigned_sorted_by_match_key = sorted(assigned_matches, key=get_match_sort_key)

        # Get assigned matches sorted by their slot time
        assigned_with_times = []
        for match in assigned_matches:
            assignment = match_to_assignment[match.id]
            slot = slot_map.get(assignment.slot_id)
            if slot:
                assigned_with_times.append((match, slot))

        assigned_sorted_by_slot = sorted(assigned_with_times, key=lambda x: get_slot_sort_key(x[1]))

        # Create match order lookup
        match_order_index = {m.id: idx for idx, m in enumerate(assigned_sorted_by_match_key)}

        # Check if slot-time order respects deterministic match order
        for i in range(len(assigned_sorted_by_slot) - 1):
            current_match, current_slot = assigned_sorted_by_slot[i]
            next_match, next_slot = assigned_sorted_by_slot[i + 1]

            current_order = match_order_index.get(current_match.id, -1)
            next_order = match_order_index.get(next_match.id, -1)

            # If next match comes before current match in deterministic order, violation
            if next_order < current_order:
                deterministic_order_ok = False

                # Determine violation type
                violation_type = "ORDERING_VIOLATION"
                if current_match.match_type != next_match.match_type:
                    stage_order_current = STAGE_PRECEDENCE.get(current_match.match_type, 999)
                    stage_order_next = STAGE_PRECEDENCE.get(next_match.match_type, 999)
                    if stage_order_next < stage_order_current:
                        violation_type = "STAGE_ORDER_INVERSION"
                elif current_match.round_index != next_match.round_index:
                    if next_match.round_index < current_match.round_index:
                        violation_type = "ROUND_ORDER_INVERSION"

                violations.append(
                    OrderingViolation(
                        type=violation_type,
                        earlier_match_id=next_match.id,
                        later_match_id=current_match.id,
                        details=f"{next_match.match_code} scheduled at {datetime.combine(next_slot.day_date, next_slot.start_time).isoformat()} comes after {current_match.match_code} at {datetime.combine(current_slot.day_date, current_slot.start_time).isoformat()} but should come before in deterministic order",
                    )
                )

        ordering_integrity = OrderingIntegrity(deterministic_order_ok=deterministic_order_ok, violations=violations)

        # ========================================================================
        # SECTION 6: Team Overlap Conflicts
        # ========================================================================
        team_conflicts = self._compute_team_conflicts(
            assigned_matches=assigned_matches,
            match_to_assignment=match_to_assignment,
            slot_map=slot_map,
            all_matches=matches,
        )

        # ========================================================================
        # Build final report
        # ========================================================================
        return ConflictReportV1(
            summary=summary,
            unassigned=unassigned_details,
            slot_pressure=slot_pressure,
            stage_timeline=stage_timeline_list,
            ordering_integrity=ordering_integrity,
            team_conflicts=team_conflicts,
        )

    def _compute_team_conflicts(
        self,
        assigned_matches: List[Match],
        match_to_assignment: dict,
        slot_map: dict,
        all_matches: List[Match],
    ) -> TeamConflictsSummary:
        """
        Compute team overlap conflicts for matches with known teams.
        
        Only evaluates overlaps for matches where both team_a_id and team_b_id are known.
        Matches with null teams are counted as unknown_team_matches.
        
        Returns:
            TeamConflictsSummary with conflict details and counts
        
        Guarantees:
            - Read-only (no mutations)
            - Deterministic ordering (sorted by match_id, team_id)
        """
        from datetime import timedelta
        
        conflicts: List[TeamConflictDetail] = []
        
        # Count matches with unknown teams (any null team_id)
        unknown_team_matches = [
            m for m in all_matches
            if m.team_a_id is None or m.team_b_id is None
        ]
        unknown_team_matches_count = len(unknown_team_matches)
        
        # Filter to matches with known teams (both teams present)
        known_team_matches = [
            m for m in assigned_matches
            if m.team_a_id is not None and m.team_b_id is not None
        ]
        
        # Build team -> [(match, start_dt, end_dt)] mapping
        team_schedule: dict[int, List[tuple]] = {}
        
        for match in known_team_matches:
            assignment = match_to_assignment.get(match.id)
            if not assignment:
                continue
            slot = slot_map.get(assignment.slot_id)
            if not slot:
                continue
            
            start_dt = datetime.combine(slot.day_date, slot.start_time)
            end_dt = start_dt + timedelta(minutes=match.duration_minutes)
            
            for team_id in (match.team_a_id, match.team_b_id):
                if team_id is not None:
                    if team_id not in team_schedule:
                        team_schedule[team_id] = []
                    team_schedule[team_id].append((match, assignment.slot_id, start_dt, end_dt))
        
        # Check for overlaps within each team's schedule
        seen_conflicts: set = set()  # (min(match_id, other_id), max(...), team_id)
        
        for team_id, schedule in team_schedule.items():
            # Sort by start time for deterministic processing
            schedule.sort(key=lambda x: (x[2], x[0].id))
            
            for i, (match, slot_id, start, end) in enumerate(schedule):
                for j in range(i + 1, len(schedule)):
                    other_match, other_slot_id, other_start, other_end = schedule[j]
                    
                    # Check overlap: [start, end) overlaps [other_start, other_end)
                    if start < other_end and other_start < end:
                        # Create a unique key to avoid duplicate conflicts
                        conflict_key = (min(match.id, other_match.id), max(match.id, other_match.id), team_id)
                        
                        if conflict_key not in seen_conflicts:
                            seen_conflicts.add(conflict_key)
                            
                            conflicts.append(TeamConflictDetail(
                                match_id=match.id,
                                match_code=match.match_code,
                                slot_id=slot_id,
                                team_id=team_id,
                                conflicting_match_id=other_match.id,
                                conflicting_match_code=other_match.match_code,
                                conflicting_slot_id=other_slot_id,
                                details=f"Team {team_id} has overlapping matches: {match.match_code} ({start.isoformat()}-{end.isoformat()}) and {other_match.match_code} ({other_start.isoformat()}-{other_end.isoformat()})",
                            ))
        
        # Sort conflicts deterministically
        conflicts.sort(key=lambda c: (c.match_id, c.team_id, c.conflicting_match_id))
        
        return TeamConflictsSummary(
            known_team_conflicts_count=len(conflicts),
            unknown_team_matches_count=unknown_team_matches_count,
            conflicts=conflicts,
        )

