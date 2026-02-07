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
import logging
from typing import List, Optional

from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session, select

from app.models import Event, Match, MatchAssignment, ScheduleSlot, ScheduleVersion, Team, TeamAvoidEdge, Tournament
from app.utils.sql import scalar_int
from app.utils.team_injection import inject_teams_v1
from app.utils.wf_grouping import assign_wf_groups_v1

logger = logging.getLogger(__name__)

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
        self.unknown_team_matches = 0  # Matches assigned without known teams (Policy B)
        self.preferred_day_hits = 0
        self.preferred_day_misses = 0
        self.rest_blocked = 0
        self.assign_debug = None  # Optional diagnostics from auto-assign
        self.event_summaries = None  # Per-event breakdown: teams_count, matches_generated, matches_with_null_teams
        self.debug_build_stamp = "build_v1_atomic_2026-02-02_a"

    def to_dict(self):
        result = {
            "slots_generated": self.slots_generated,
            "matches_generated": self.matches_generated,
            "assignments_created": self.assignments_created,
            "unassigned_matches": self.unassigned_matches,
            "unknown_team_matches": self.unknown_team_matches,
            "preferred_day_hits": self.preferred_day_hits,
            "preferred_day_misses": self.preferred_day_misses,
            "rest_blocked": self.rest_blocked,
            "debug_build_stamp": self.debug_build_stamp,
        }
        if self.assign_debug is not None:
            result["assign_debug"] = self.assign_debug
        if self.event_summaries is not None:
            result["event_summaries"] = self.event_summaries
        return result


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
    session: Session,
    tournament_id: int,
    version_id: int,
    clear_existing: bool = True,
    dry_run: bool = False,
    inject_teams: bool = False,
) -> ScheduleBuildResult:
    """
    One-click schedule builder with strict execution order.

    Steps (in order):
    0. Validate (tournament, version exists, is draft)
    1. Clear existing (if clear_existing=true)
    2. Generate slots
    3. Generate matches
    4. WF grouping (if avoid edges exist)
    5. Inject teams (if inject_teams=true AND teams exist)
    6. Auto-assign (rest-aware + day targeting)
    7. Return composite response

    Args:
        session: Database session
        tournament_id: Tournament ID
        version_id: Schedule version ID
        clear_existing: Clear existing assignments before building
        dry_run: Run without committing assignments (V1: not fully implemented)
        inject_teams: Run team injection step (default: false)

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
            # No commit here - single transaction boundary

        # ====================================================================
        # Step 2: Generate Slots
        # ====================================================================
        result.failed_step = "GENERATE_SLOTS"

        # TEMP DEBUG: Log tournament mode and active windows/days
        import logging
        from sqlmodel import func
        from app.models.tournament_time_window import TournamentTimeWindow
        from app.models.tournament_day import TournamentDay
        
        logger = logging.getLogger(__name__)
        logger.error(
            "BUILD DEBUG: use_time_windows=%s clear_existing=%s tournament_id=%s",
            tournament.use_time_windows,
            clear_existing,
            tournament_id,
        )

        active_windows = scalar_int(
            session.exec(
                select(func.count())
                .select_from(TournamentTimeWindow)
                .where(
                    TournamentTimeWindow.tournament_id == tournament_id,
                    TournamentTimeWindow.is_active == True,
                )
            ).one()
        )

        active_days = scalar_int(
            session.exec(
                select(func.count())
                .select_from(TournamentDay)
                .where(
                    TournamentDay.tournament_id == tournament_id,
                    TournamentDay.is_active == True,
                )
            ).one()
        )

        logger.error(
            "BUILD DEBUG: active_windows=%s active_days=%s",
            active_windows,
            active_days,
        )

        # Load existing slots
        existing_slots = session.exec(select(ScheduleSlot).where(ScheduleSlot.schedule_version_id == version_id)).all()

        # If no slots exist OR clear_existing=True (regenerate), generate them
        if len(existing_slots) == 0 or clear_existing:
            from app.routes.schedule import generate_slots, SlotGenerateRequest

            slot_request = SlotGenerateRequest(source="auto", schedule_version_id=version_id, wipe_existing=clear_existing)
            slots_result = generate_slots(tournament_id, slot_request, session, _transactional=True)
            slots_created = slots_result.get("slots_created", 0)
            result.summary.slots_generated = slots_created

        session.flush()  # Force DB validation after slots

        # Fail-fast tripwire: court_label must never be a list (ORM path)
        bad = []
        for obj in list(session.new):
            if obj.__class__.__name__ == "ScheduleSlot" and isinstance(getattr(obj, "court_label", None), list):
                bad.append((getattr(obj, "court_number", None), getattr(obj, "court_label", None)))
        if bad:
            raise ValueError(f"court_label list detected in session.new (before GENERATE_MATCHES): {bad[:3]}")

        # ====================================================================
        # Step 3: Generate Matches (IDEMPOTENT - only if missing)
        # ====================================================================
        result.failed_step = "GENERATE_MATCHES"

        # Check if matches already exist for this version
        # IMPORTANT: Matches are generated ONCE per schedule version and persist.
        # Subsequent Build Schedule calls should NOT regenerate matches.
        # Only slots and assignments are refreshed on rebuild.
        from sqlmodel import func

        existing_match_count = scalar_int(
            session.exec(
                select(func.count(Match.id))
                .where(Match.schedule_version_id == version_id)
            ).one()
        )

        if existing_match_count > 0:
            # Matches already exist - skip generation (idempotent)
            result.summary.matches_generated = existing_match_count
            logger.info(
                f"BUILD: Matches already exist for version {version_id} ({existing_match_count} matches). "
                "Skipping generation (idempotent)."
            )
        else:
            # Generate matches from finalized events (exactly once per version)
            from app.routes.schedule import generate_matches, MatchGenerateRequest

            match_request = MatchGenerateRequest(schedule_version_id=version_id, wipe_existing=False)
            session._allow_match_generation = True
            try:
                matches_result = generate_matches(tournament_id, match_request, session, _transactional=True)
                matches_created = matches_result.get("total_matches_created", 0)
                result.summary.matches_generated = matches_created
                for w in matches_result.get("warnings", []):
                    result.warnings.append(
                        BuildWarning(
                            code="MATCH_GENERATION_WARNING",
                            message=w.get("message", str(w)),
                            event_id=w.get("event_id"),
                        )
                    )
                logger.info(f"BUILD: Generated {matches_created} matches for version {version_id}")
            finally:
                session._allow_match_generation = False

        session.flush()  # Force DB validation after matches

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
                        assign_wf_groups_v1(session, event.id, clear_existing=True, _transactional=True)

        session.flush()  # Force DB validation after WF assignment

        # ====================================================================
        # Step 5: Inject Teams (only if inject_teams=True)
        # ====================================================================
        result.failed_step = "INJECT_TEAMS"

        if inject_teams:
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
                    # No teams for this event, warn
                    result.warnings.append(
                        BuildWarning(
                            code="NO_TEAMS_FOR_EVENT",
                            message=f"Event {event.id} ({event.name}) has no teams, skipping injection",
                            event_id=event.id,
                        )
                    )
        # If inject_teams=False, skip team injection silently (no warnings)

        # ====================================================================
        # Step 6: Auto-Assign (rest-aware + day targeting)
        # ====================================================================
        result.failed_step = "AUTO_ASSIGN"

        if not dry_run:
            from app.utils.rest_rules import auto_assign_with_rest

            assign_result = auto_assign_with_rest(
                session=session,
                schedule_version_id=version_id,
                clear_existing=True,
                allow_teamless=True,
                _transactional=True,
            )

            # Update summary from assign result
            result.summary.assignments_created = assign_result.get("assigned_count", 0)
            result.summary.unassigned_matches = assign_result.get("unassigned_count", 0)
            result.summary.unknown_team_matches = assign_result.get("unknown_team_matches_count", 0)
            result.summary.preferred_day_hits = assign_result.get("preferred_day_hits", 0)
            result.summary.preferred_day_misses = assign_result.get("preferred_day_misses", 0)
            result.summary.rest_blocked = assign_result.get("rest_violations_blocked", 0)
            result.summary.assign_debug = assign_result.get("assign_debug")  # Capture diagnostics

        # ====================================================================
        # Step 7: Build event_summaries (per-event breakdown)
        # ====================================================================
        events = session.exec(select(Event).where(Event.tournament_id == tournament_id)).all()
        all_matches_for_version = session.exec(
            select(Match).where(Match.schedule_version_id == version_id)
        ).all()
        event_summaries = []
        for event in events:
            # teams_linked = actual Team rows linked to this event (real DB links)
            teams_linked = len(session.exec(select(Team).where(Team.event_id == event.id)).all())
            event_matches = [m for m in all_matches_for_version if m.event_id == event.id]
            matches_generated = len(event_matches)
            matches_with_null_teams = sum(
                1 for m in event_matches if m.team_a_id is None or m.team_b_id is None
            )
            event_summaries.append({
                "event_id": event.id,
                "event_name": event.name,
                "teams_count": event.team_count,  # config: event.team_count
                "teams_linked": teams_linked,  # actual DB Team rows for this event
                "matches_generated": matches_generated,
                "matches_with_null_teams": matches_with_null_teams,
            })
        result.summary.event_summaries = event_summaries

        # ====================================================================
        # Step 8: Success - single commit
        # ====================================================================
        result.status = "success"
        result.failed_step = None
        session.commit()
        return result

    except Exception as e:
        session.rollback()
        logger.exception("Build schedule failed, transaction rolled back")
        result.status = "error"
        result.error_message = f"Schedule build failed at step {result.failed_step}: {str(e)}"
        raise RuntimeError(f"Schedule build failed: {result.error_message}") from e
