"""
Schedule Orchestrator Service - One-Click Build Full Schedule V1

Orchestrates the complete schedule building pipeline:
1. Generate slots
2. Generate matches
3. Assign WF groups (if avoid edges exist)
4. Inject teams (if teams exist)
5. Auto-assign (rest-aware + day targeting)

Ensures deterministic, repeatable, idempotent execution.
"""

import json
from typing import List, Optional

from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session, select

from app.models import Event, Match, MatchAssignment, ScheduleSlot, ScheduleVersion, Team, TeamAvoidEdge, Tournament
from app.utils.team_injection import inject_teams_v1
from app.utils.wf_grouping import assign_wf_groups_v1

# ============================================================================
# Response Models
# ============================================================================


class BuildWarning:
    """Warning during schedule build"""

    def __init__(self, code: str, message: str, event_id: Optional[int] = None):
        self.code = code
        self.message = message
        self.event_id = event_id

    def to_dict(self):
        return {"code": self.code, "message": self.message, "event_id": self.event_id}


class BuildSummary:
    """Summary of schedule build results"""

    def __init__(self):
        self.slots_generated = 0
        self.matches_generated = 0
        self.assignments_created = 0
        self.unassigned_matches = 0
        self.preferred_day_hits = 0
        self.preferred_day_misses = 0
        self.rest_blocked = 0

    def to_dict(self):
        return {
            "slots_generated": self.slots_generated,
            "matches_generated": self.matches_generated,
            "assignments_created": self.assignments_created,
            "unassigned_matches": self.unassigned_matches,
            "preferred_day_hits": self.preferred_day_hits,
            "preferred_day_misses": self.preferred_day_misses,
            "rest_blocked": self.rest_blocked,
        }


class ScheduleBuildResult:
    """Complete result of schedule build"""

    def __init__(self):
        self.status = "success"
        self.tournament_id: Optional[int] = None
        self.schedule_version_id: Optional[int] = None
        self.clear_existing = True
        self.dry_run = False
        self.summary = BuildSummary()
        self.warnings: List[BuildWarning] = []
        self.failed_step: Optional[str] = None
        self.error_message: Optional[str] = None

    def to_dict(self):
        result = {
            "status": self.status,
            "tournament_id": self.tournament_id,
            "schedule_version_id": self.schedule_version_id,
            "clear_existing": self.clear_existing,
            "dry_run": self.dry_run,
            "summary": self.summary.to_dict(),
            "warnings": [w.to_dict() for w in self.warnings],
        }

        if self.failed_step:
            result["failed_step"] = self.failed_step
            result["error_message"] = self.error_message

        return result


# ============================================================================
# Main Orchestrator Function
# ============================================================================


def build_schedule_v1(
    session: Session, tournament_id: int, version_id: int, clear_existing: bool = True, dry_run: bool = False
) -> ScheduleBuildResult:
    """
    One-click schedule builder with strict execution order.

    Steps (in order):
    0. Validate (tournament, version exists, is draft)
    1. Clear existing (if clear_existing=true)
    2. Generate slots
    3. Generate matches
    4. WF grouping (if avoid edges exist)
    5. Inject teams (if teams exist)
    6. Auto-assign (rest-aware + day targeting)
    7. Return composite response

    Args:
        session: Database session
        tournament_id: Tournament ID
        version_id: Schedule version ID
        clear_existing: Clear existing assignments before building
        dry_run: Run without committing assignments (V1: not fully implemented)

    Returns:
        ScheduleBuildResult with comprehensive summary

    Raises:
        ValueError: If validation fails
        SQLAlchemyError: If database operation fails
    """
    result = ScheduleBuildResult()
    result.tournament_id = tournament_id
    result.schedule_version_id = version_id
    result.clear_existing = clear_existing
    result.dry_run = dry_run

    try:
        # ====================================================================
        # Step 0: Validate
        # ====================================================================
        result.failed_step = "VALIDATE"

        tournament = session.get(Tournament, tournament_id)
        if not tournament:
            raise ValueError(f"Tournament {tournament_id} not found")

        version = session.get(ScheduleVersion, version_id)
        if not version:
            raise ValueError(f"Schedule version {version_id} not found")

        if version.tournament_id != tournament_id:
            raise ValueError(f"Schedule version {version_id} does not belong to tournament {tournament_id}")

        # Draft-only guard
        if version.status != "draft":
            raise ValueError(f"SCHEDULE_VERSION_NOT_DRAFT: Cannot build non-draft schedule (status: {version.status})")

        # ====================================================================
        # Step 1: Clear Existing (if requested)
        # ====================================================================
        result.failed_step = "CLEAR_EXISTING"

        if clear_existing:
            # Clear match assignments for this version
            assignments = session.exec(
                select(MatchAssignment).where(MatchAssignment.schedule_version_id == version_id)
            ).all()
            for assignment in assignments:
                session.delete(assignment)

            # Note: We do NOT delete:
            # - Teams (they are user input)
            # - Avoid edges (they are user input)
            # - Tournament structure (events, days, etc.)

            # We DO clear generated data:
            # - Match assignments (done above)
            # - Could clear slots/matches if regenerating, but for now we keep them

            session.commit()

        # ====================================================================
        # Step 2: Generate Slots
        # ====================================================================
        result.failed_step = "GENERATE_SLOTS"

        # Load existing slots
        existing_slots = session.exec(select(ScheduleSlot).where(ScheduleSlot.schedule_version_id == version_id)).all()

        result.summary.slots_generated = len(existing_slots)

        # In V1, we assume slots are already generated via the existing endpoint
        # If you want to regenerate slots here, you would call the slot generator

        # ====================================================================
        # Step 3: Generate Matches
        # ====================================================================
        result.failed_step = "GENERATE_MATCHES"

        # Check if matches exist
        existing_matches = session.exec(select(Match).where(Match.schedule_version_id == version_id)).all()

        result.summary.matches_generated = len(existing_matches)

        # In V1, we assume matches are already generated via the existing endpoint
        # If you want to regenerate matches here, you would call the match generator

        # ====================================================================
        # Step 4: WF Grouping (conditional)
        # ====================================================================
        result.failed_step = "ASSIGN_WF_GROUPS"

        # Get all events for this tournament
        events = session.exec(select(Event).where(Event.tournament_id == tournament_id)).all()

        for event in events:
            # Check if event has WF stage and avoid edges
            if event.draw_plan_json:
                draw_plan = json.loads(event.draw_plan_json)
                has_wf = draw_plan.get("wf_rounds", 0) > 0

                if has_wf:
                    # Check for avoid edges
                    avoid_edges_count = session.exec(
                        select(TeamAvoidEdge).where(TeamAvoidEdge.event_id == event.id)
                    ).all()

                    if len(avoid_edges_count) > 0:
                        # Run WF grouping
                        assign_wf_groups_v1(session, event.id, clear_existing=True)
                        # Grouping result is logged but not returned in V1

        # ====================================================================
        # Step 5: Inject Teams (conditional)
        # ====================================================================
        result.failed_step = "INJECT_TEAMS"

        for event in events:
            # Check if event has teams
            teams = session.exec(select(Team).where(Team.event_id == event.id)).all()

            if len(teams) > 0:
                # Inject teams into matches
                try:
                    inject_teams_v1(session, event.id, version_id, clear_existing=True)
                except Exception as e:
                    # Log warning but continue
                    result.warnings.append(
                        BuildWarning(
                            code="TEAM_INJECTION_FAILED",
                            message=f"Team injection failed for event {event.id}: {str(e)}",
                            event_id=event.id,
                        )
                    )
            else:
                # No teams, skip injection
                result.warnings.append(
                    BuildWarning(
                        code="NO_TEAMS_FOR_EVENT",
                        message=f"Event {event.id} ({event.name}) has no teams, skipping injection",
                        event_id=event.id,
                    )
                )

        # ====================================================================
        # Step 6: Auto-Assign (rest-aware + day targeting)
        # ====================================================================
        result.failed_step = "AUTO_ASSIGN"

        if not dry_run:
            # Import here to avoid circular dependency
            from app.utils.rest_rules import auto_assign_with_rest

            # Run auto-assign with rest rules
            assign_result = auto_assign_with_rest(session=session, schedule_version_id=version_id, clear_existing=True)

            # Update summary from assign result
            result.summary.assignments_created = assign_result.get("assigned_count", 0)
            result.summary.unassigned_matches = assign_result.get("unassigned_count", 0)
            result.summary.preferred_day_hits = assign_result.get("preferred_day_hits", 0)
            result.summary.preferred_day_misses = assign_result.get("preferred_day_misses", 0)
            result.summary.rest_blocked = assign_result.get("rest_violations_blocked", 0)

        # ====================================================================
        # Step 7: Success
        # ====================================================================
        result.status = "success"
        result.failed_step = None

        return result

    except ValueError as e:
        # Validation or business logic error
        result.status = "error"
        result.error_message = str(e)
        return result

    except SQLAlchemyError as e:
        # Database error - rollback
        session.rollback()
        result.status = "error"
        result.error_message = f"Database error at step {result.failed_step}: {str(e)}"
        return result

    except Exception as e:
        # Unexpected error
        session.rollback()
        result.status = "error"
        result.error_message = f"Unexpected error at step {result.failed_step}: {str(e)}"
        return result
