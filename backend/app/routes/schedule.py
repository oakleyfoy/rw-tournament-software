import hashlib
import json
import logging
from datetime import date, datetime, time
from typing import Any, Dict, List, Optional
from uuid import uuid4

logger = logging.getLogger(__name__)

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, model_validator
from sqlmodel import Session, func, select

from app.database import get_session
from app.models.event import Event
from app.models.match import Match
from app.models.match_assignment import MatchAssignment
from app.models.schedule_slot import ScheduleSlot
from app.models.schedule_version import ScheduleVersion
from app.models.team import Team
from app.models.team_avoid_edge import TeamAvoidEdge
from app.models.tournament import Tournament
from app.models.tournament_day import TournamentDay
from app.models.tournament_time_window import TournamentTimeWindow
from app.services.schedule_orchestrator import build_schedule_v1
from app.utils.courts import court_label_for_index, parse_court_names


def _court_label_to_str(value: object) -> str:
    """Ensure court_label is always a string for DB (never a list)."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return ",".join(str(x) for x in value)
    return str(value)
from app.utils.rest_rules import auto_assign_with_rest
from app.utils.sql import scalar_int
from app.utils.version_guards import require_draft_version, require_final_version
# Phase 3D.1: Shared conflict computation
from app.utils.conflict_report import ConflictReportSummary, UnassignedMatchDetail

router = APIRouter()


# ============================================================================
# Helper Functions
# ============================================================================


def wipe_matches_for_version(session: Session, version_id: int, event_id: Optional[int] = None) -> None:
    """Wipe matches and assignments for a version in correct order (child→parent).

    Deletes in order: MatchAssignments → Matches
    If event_id is provided, only wipes matches for that event.
    """
    # Build query for matches
    match_query = select(Match).where(Match.schedule_version_id == version_id)
    if event_id:
        match_query = match_query.where(Match.event_id == event_id)

    existing_matches = session.exec(match_query).all()

    # Delete assignments first (child records) - must delete before matches due to FK
    for match in existing_matches:
        assignments = session.exec(select(MatchAssignment).where(MatchAssignment.match_id == match.id)).all()
        for assignment in assignments:
            session.delete(assignment)

    # Flush assignments before deleting matches to ensure FK constraints are satisfied
    session.flush()

    # Then delete matches (parent records)
    for match in existing_matches:
        session.delete(match)

    # Flush to ensure all deletions are processed
    session.flush()


def get_or_create_draft_version(
    session: Session, tournament_id: int, provided_version_id: Optional[int] = None
) -> ScheduleVersion:
    """Get or create a draft version, handling ambiguity with clear errors.

    Returns:
        ScheduleVersion: The draft version to use

    Raises:
        HTTPException: 404 if provided_version_id is invalid
        HTTPException: 400 if provided version is finalized
        HTTPException: 409 if multiple drafts exist (ambiguous)
        HTTPException: 409 if no draft exists and cannot be created
    """
    if provided_version_id:
        version = session.get(ScheduleVersion, provided_version_id)
        if not version or version.tournament_id != tournament_id:
            raise HTTPException(status_code=404, detail="Schedule version not found")
        if version.status == "final":
            raise HTTPException(status_code=400, detail="Cannot modify finalized version")
        return version

    # Check for existing drafts
    existing_drafts = session.exec(
        select(ScheduleVersion).where(ScheduleVersion.tournament_id == tournament_id, ScheduleVersion.status == "draft")
    ).all()

    if len(existing_drafts) > 1:
        raise HTTPException(
            status_code=409,
            detail=f"Multiple draft versions found ({len(existing_drafts)}). Please specify schedule_version_id explicitly.",
        )

    if len(existing_drafts) == 1:
        return existing_drafts[0]

    # No draft exists, create one
    max_version = session.exec(
        select(func.max(ScheduleVersion.version_number)).where(ScheduleVersion.tournament_id == tournament_id)
    ).first()
    next_version = (max_version or 0) + 1

    new_version = ScheduleVersion(tournament_id=tournament_id, version_number=next_version, status="draft")
    session.add(new_version)
    session.flush()
    return new_version


# ============================================================================
# Schedule Version Models & Endpoints
# ============================================================================


class ScheduleVersionResponse(BaseModel):
    id: int
    tournament_id: int
    version_number: int
    status: str
    created_at: datetime
    created_by: Optional[str]
    notes: Optional[str]
    finalized_at: Optional[datetime] = None
    finalized_checksum: Optional[str] = None

    class Config:
        from_attributes = True


class ScheduleVersionCreate(BaseModel):
    notes: Optional[str] = None


@router.get("/tournaments/{tournament_id}/schedule/versions", response_model=List[ScheduleVersionResponse])
def get_schedule_versions(tournament_id: int, session: Session = Depends(get_session)):
    """Get all schedule versions for a tournament"""
    try:
        tournament = session.get(Tournament, tournament_id)
        if not tournament:
            raise HTTPException(status_code=404, detail="Tournament not found")

        versions = session.exec(
            select(ScheduleVersion)
            .where(ScheduleVersion.tournament_id == tournament_id)
            .order_by(ScheduleVersion.version_number.desc())
        ).all()

        return versions
    except HTTPException:
        raise
    except Exception as e:
        import traceback

        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.post("/tournaments/{tournament_id}/schedule/versions", response_model=ScheduleVersionResponse, status_code=201)
def create_schedule_version(tournament_id: int, data: ScheduleVersionCreate, session: Session = Depends(get_session)):
    """Create or return existing current draft version"""
    try:
        tournament = session.get(Tournament, tournament_id)
        if not tournament:
            raise HTTPException(status_code=404, detail=f"Tournament {tournament_id} not found")

        # Check for existing draft version
        existing_draft = session.exec(
            select(ScheduleVersion)
            .where(ScheduleVersion.tournament_id == tournament_id)
            .where(ScheduleVersion.status == "draft")
        ).first()

        if existing_draft:
            return existing_draft

        # Get next version number
        max_version = session.exec(
            select(func.max(ScheduleVersion.version_number)).where(ScheduleVersion.tournament_id == tournament_id)
        ).first()

        next_version = (max_version or 0) + 1

        version = ScheduleVersion(
            tournament_id=tournament_id, version_number=next_version, status="draft", notes=data.notes
        )
        session.add(version)
        session.commit()
        session.refresh(version)

        return version
    except HTTPException:
        raise
    except Exception as e:
        import traceback

        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


class ActiveVersionResponse(BaseModel):
    """Canonical active draft version for a tournament"""
    schedule_version_id: int
    status: str
    created_at: Optional[str] = None
    none_found: bool = False


@router.get(
    "/tournaments/{tournament_id}/schedule/versions/active",
    response_model=ActiveVersionResponse,
)
def get_active_schedule_version(tournament_id: int, session: Session = Depends(get_session)):
    """
    Return the canonical active draft version for the tournament.
    Prefers the latest DRAFT version. If none exists, creates one.
    """
    tournament = session.get(Tournament, tournament_id)
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")

    draft = session.exec(
        select(ScheduleVersion)
        .where(
            ScheduleVersion.tournament_id == tournament_id,
            ScheduleVersion.status == "draft",
        )
        .order_by(ScheduleVersion.version_number.desc())
    ).first()

    if draft:
        created = getattr(draft, "created_at", None)
        return ActiveVersionResponse(
            schedule_version_id=draft.id,
            status=draft.status,
            created_at=created.isoformat() if created else None,
            none_found=False,
        )

    max_version = session.exec(
        select(func.max(ScheduleVersion.version_number)).where(
            ScheduleVersion.tournament_id == tournament_id
        )
    ).first()
    next_version = (max_version or 0) + 1
    new_version = ScheduleVersion(
        tournament_id=tournament_id,
        version_number=next_version,
        status="draft",
    )
    session.add(new_version)
    session.commit()
    session.refresh(new_version)
    created = getattr(new_version, "created_at", None)
    return ActiveVersionResponse(
        schedule_version_id=new_version.id,
        status=new_version.status,
        created_at=created.isoformat() if created else None,
        none_found=False,
    )


@router.post(
    "/tournaments/{tournament_id}/schedule/versions/{version_id}/finalize", response_model=ScheduleVersionResponse
)
def finalize_schedule_version(tournament_id: int, version_id: int, session: Session = Depends(get_session)):
    """
    Finalize a draft schedule version (locks it).

    Requirements:
    - Version must be draft
    - Sanity checks:
        - No slot double-booking (each slot used at most once)
        - All assignments reference valid match+slot in same version
    - Compute deterministic SHA-256 checksum over canonical ordering:
        - Slots: day_date, start_time, court_number, id
        - Matches: stage, round_index, sequence_in_round, id
        - Assignments: slot_id, match_id
    - Update: status=final, finalized_at, finalized_checksum

    Returns:
        Schedule version with status=final and checksum
    """
    # Ensure version is draft
    version = require_draft_version(session, version_id, tournament_id)

    # Sanity checks
    # 1. Check for slot double-booking
    assignments = session.exec(select(MatchAssignment).where(MatchAssignment.schedule_version_id == version_id)).all()

    slot_ids = [a.slot_id for a in assignments]
    if len(slot_ids) != len(set(slot_ids)):
        raise HTTPException(
            status_code=422, detail="Sanity check failed: Duplicate slot assignments found (double-booking)"
        )

    # 2. Verify all assignments reference valid match+slot in same version
    assignment_slot_ids = set(slot_ids)
    assignment_match_ids = set([a.match_id for a in assignments])

    # Get all slots for this version
    version_slots = session.exec(select(ScheduleSlot.id).where(ScheduleSlot.schedule_version_id == version_id)).all()
    version_slot_ids = set(version_slots)

    # Get all matches for this version
    version_matches = session.exec(select(Match.id).where(Match.schedule_version_id == version_id)).all()
    version_match_ids = set(version_matches)

    # Check if all assignment slot_ids are in version
    invalid_slots = assignment_slot_ids - version_slot_ids
    if invalid_slots:
        raise HTTPException(
            status_code=422,
            detail=f"Sanity check failed: Assignments reference slots not in this version: {invalid_slots}",
        )

    # Check if all assignment match_ids are in version
    invalid_matches = assignment_match_ids - version_match_ids
    if invalid_matches:
        raise HTTPException(
            status_code=422,
            detail=f"Sanity check failed: Assignments reference matches not in this version: {invalid_matches}",
        )

    # 3. Compute deterministic checksum
    # Canonical ordering:
    # - Slots: day_date, start_time, court_number, id
    slots = session.exec(
        select(ScheduleSlot)
        .where(ScheduleSlot.schedule_version_id == version_id)
        .order_by(ScheduleSlot.day_date, ScheduleSlot.start_time, ScheduleSlot.court_number, ScheduleSlot.id)
    ).all()

    # - Matches: stage, round_index, sequence_in_round, id
    matches = session.exec(
        select(Match)
        .where(Match.schedule_version_id == version_id)
        .order_by(Match.match_type, Match.round_index, Match.sequence_in_round, Match.id)
    ).all()

    # - Assignments: slot_id, match_id
    assignments_ordered = sorted(assignments, key=lambda a: (a.slot_id, a.match_id))

    # Build canonical JSON structure
    checksum_data = {
        "slots": [
            {
                "id": s.id,
                "day_date": s.day_date.isoformat(),
                "start_time": s.start_time.isoformat(),
                "end_time": s.end_time.isoformat(),
                "court_number": s.court_number,
                "court_label": s.court_label,
            }
            for s in slots
        ],
        "matches": [
            {
                "id": m.id,
                "match_code": m.match_code,
                "match_type": m.match_type,
                "round_index": m.round_index,
                "sequence_in_round": m.sequence_in_round,
                "duration_minutes": m.duration_minutes,
                "event_id": m.event_id,
            }
            for m in matches
        ],
        "assignments": [{"slot_id": a.slot_id, "match_id": a.match_id} for a in assignments_ordered],
    }

    # Compute SHA-256 checksum
    canonical_json = json.dumps(checksum_data, sort_keys=True, separators=(",", ":"))
    checksum = hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()

    # Update version
    version.status = "final"
    version.finalized_at = datetime.utcnow()
    version.finalized_checksum = checksum

    session.add(version)
    session.commit()
    session.refresh(version)

    return version


class ResetDraftResponse(BaseModel):
    schedule_version_id: int
    cleared_assignments_count: int
    cleared_matches_count: int
    cleared_slots_count: int


@router.post("/tournaments/{tournament_id}/schedule/versions/{version_id}/reset", response_model=ResetDraftResponse)
def reset_draft_version(tournament_id: int, version_id: int, session: Session = Depends(get_session)):
    """
    Reset a draft schedule version (wipe all artifacts).

    Requirements:
    - Version must be draft
    - Deletes (in order):
        1. match_assignments for version
        2. matches for version
        3. slots for version
    - Does NOT delete teams or avoid edges

    Returns:
        Counts of cleared artifacts
    """
    # Ensure version is draft
    require_draft_version(session, version_id, tournament_id)

    # Count before deletion
    assignments_count = len(
        session.exec(select(MatchAssignment).where(MatchAssignment.schedule_version_id == version_id)).all()
    )

    matches_count = len(session.exec(select(Match).where(Match.schedule_version_id == version_id)).all())

    slots_count = len(session.exec(select(ScheduleSlot).where(ScheduleSlot.schedule_version_id == version_id)).all())

    # Delete assignments
    assignments = session.exec(select(MatchAssignment).where(MatchAssignment.schedule_version_id == version_id)).all()
    for assignment in assignments:
        session.delete(assignment)

    # Delete matches
    matches = session.exec(select(Match).where(Match.schedule_version_id == version_id)).all()
    for match in matches:
        session.delete(match)

    # Delete slots
    slots = session.exec(select(ScheduleSlot).where(ScheduleSlot.schedule_version_id == version_id)).all()
    for slot in slots:
        session.delete(slot)

    session.commit()

    return ResetDraftResponse(
        schedule_version_id=version_id,
        cleared_assignments_count=assignments_count,
        cleared_matches_count=matches_count,
        cleared_slots_count=slots_count,
    )


# Wipe matches route - MUST come before general DELETE /versions/{version_id} route
@router.delete("/tournaments/{tournament_id}/schedule/versions/{version_id}/matches")
def wipe_schedule_version_matches(tournament_id: int, version_id: int, session: Session = Depends(get_session)):
    """Wipe all matches for a schedule version.
    
    Verifies version belongs to tournament and is not finalized.
    Deletes all Match and MatchAssignment rows for the version.
    """
    version = session.get(ScheduleVersion, version_id)
    if not version or version.tournament_id != tournament_id:
        raise HTTPException(status_code=404, detail="Schedule version not found")
    
    if version.status == "final":
        raise HTTPException(status_code=409, detail="Cannot wipe matches for a finalized schedule version")
    
    # Count matches before deletion
    match_count_before = scalar_int(
        session.exec(
            select(func.count(Match.id)).where(Match.schedule_version_id == version_id)
        ).one()
    )
    
    # Use existing helper to wipe matches (handles MatchAssignments correctly)
    wipe_matches_for_version(session, version_id)
    session.commit()
    
    return {"deleted_matches": match_count_before}


@router.delete("/tournaments/{tournament_id}/schedule/versions/{version_id}", status_code=204)
def delete_schedule_version(tournament_id: int, version_id: int, session: Session = Depends(get_session)):
    """Delete a schedule version and all its associated data"""
    print(f"=== DELETE schedule version called: tournament_id={tournament_id}, version_id={version_id} ===")
    import logging

    logger = logging.getLogger(__name__)
    logger.info(f"DELETE schedule version called: tournament_id={tournament_id}, version_id={version_id}")

    try:
        tournament = session.get(Tournament, tournament_id)
        if not tournament:
            logger.warning(f"Tournament {tournament_id} not found")
            raise HTTPException(status_code=404, detail=f"Tournament {tournament_id} not found")

        version = session.get(ScheduleVersion, version_id)
        if not version:
            logger.warning(f"Schedule version {version_id} not found in database")
            # Try to see if version exists but belongs to different tournament
            all_versions = session.exec(select(ScheduleVersion).where(ScheduleVersion.id == version_id)).first()
            if all_versions:
                logger.warning(
                    f"Schedule version {version_id} belongs to tournament {all_versions.tournament_id}, not {tournament_id}"
                )
                raise HTTPException(
                    status_code=404,
                    detail=f"Schedule version {version_id} belongs to tournament {all_versions.tournament_id}, not {tournament_id}",
                )
            raise HTTPException(status_code=404, detail=f"Schedule version {version_id} not found")

        if version.tournament_id != tournament_id:
            logger.warning(
                f"Schedule version {version_id} belongs to tournament {version.tournament_id}, not {tournament_id}"
            )
            raise HTTPException(
                status_code=404,
                detail=f"Schedule version {version_id} belongs to tournament {version.tournament_id}, not {tournament_id}",
            )

        logger.info(f"Deleting schedule version {version_id} for tournament {tournament_id}")

        # Delete all match assignments for this version
        assignments = session.exec(
            select(MatchAssignment).where(MatchAssignment.schedule_version_id == version_id)
        ).all()
        for assignment in assignments:
            session.delete(assignment)

        # Delete all matches for this version
        matches = session.exec(select(Match).where(Match.schedule_version_id == version_id)).all()
        for match in matches:
            session.delete(match)

        # Delete all slots for this version
        slots = session.exec(select(ScheduleSlot).where(ScheduleSlot.schedule_version_id == version_id)).all()
        for slot in slots:
            session.delete(slot)

        # Delete the version itself
        session.delete(version)
        session.commit()

        return None

    except HTTPException:
        raise
    except Exception as e:
        import traceback

        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.post(
    "/tournaments/{tournament_id}/schedule/versions/{version_id}/clone",
    response_model=ScheduleVersionResponse,
    status_code=201,
)
def clone_schedule_version(tournament_id: int, version_id: int, session: Session = Depends(get_session)):
    """
    Clone a final version into a new draft.

    Requirements:
    - Source version must be final
    - Creates new draft version with next version_number
    - Copies all slots, matches, and match_assignments
    - IDs are remapped consistently (new primary keys generated)
    - Assignment mapping preserves identical schedule structure

    Returns:
        New draft schedule version
    """
    return _clone_final_to_draft(tournament_id, version_id, session)


@router.post(
    "/tournaments/{tournament_id}/schedule/versions/{version_id}/clone-to-draft",
    response_model=ScheduleVersionResponse,
    status_code=201,
)
def clone_to_draft_alias(tournament_id: int, version_id: int, session: Session = Depends(get_session)):
    """
    Clone a final version into a new draft (spec-compliant route name).

    This is an alias for /clone route. Both routes have identical behavior.

    Requirements:
    - Source version must be final
    - Creates new draft version with next version_number
    - Copies all slots, matches, and match_assignments
    - IDs are remapped consistently (new primary keys generated)
    - Assignment mapping preserves identical schedule structure

    Returns:
        New draft schedule version
    """
    return _clone_final_to_draft(tournament_id, version_id, session)


def _clone_final_to_draft(tournament_id: int, version_id: int, session: Session) -> ScheduleVersion:
    """
    Shared implementation for clone endpoints.
    """
    # Ensure source version is final
    source_version = require_final_version(session, version_id, tournament_id)

    # Get next version number
    max_version = session.exec(
        select(func.max(ScheduleVersion.version_number)).where(ScheduleVersion.tournament_id == tournament_id)
    ).first()

    next_version = (max_version or 0) + 1

    # Create new draft version
    new_version = ScheduleVersion(
        tournament_id=tournament_id,
        version_number=next_version,
        status="draft",
        notes=f"Cloned from final version {source_version.version_number}",
        finalized_at=None,
        finalized_checksum=None,
    )
    session.add(new_version)
    session.flush()  # Get the ID

    # Clone slots with ID mapping
    source_slots = session.exec(
        select(ScheduleSlot).where(ScheduleSlot.schedule_version_id == version_id).order_by(ScheduleSlot.id)
    ).all()

    slot_id_map = {}  # old_id -> new_id
    for slot in source_slots:
        court_label = _court_label_to_str(getattr(slot, "court_label", None) or str(slot.court_number))
        new_slot = ScheduleSlot(
            tournament_id=slot.tournament_id,
            schedule_version_id=new_version.id,
            day_date=slot.day_date,
            start_time=slot.start_time,
            end_time=slot.end_time,
            court_number=slot.court_number,
            court_label=court_label,
            block_minutes=slot.block_minutes,
            label=slot.label,
            is_active=slot.is_active,
        )
        session.add(new_slot)
        session.flush()  # Get new ID
        slot_id_map[slot.id] = new_slot.id

    # Clone matches with ID mapping
    source_matches = session.exec(select(Match).where(Match.schedule_version_id == version_id).order_by(Match.id)).all()

    match_id_map = {}  # old_id -> new_id
    for match in source_matches:
        new_match = Match(
            tournament_id=match.tournament_id,
            event_id=match.event_id,
            schedule_version_id=new_version.id,
            match_code=match.match_code,
            match_type=match.match_type,
            round_number=match.round_number,
            round_index=match.round_index,
            sequence_in_round=match.sequence_in_round,
            duration_minutes=match.duration_minutes,
            team_a_id=match.team_a_id,
            team_b_id=match.team_b_id,
            placeholder_side_a=match.placeholder_side_a,
            placeholder_side_b=match.placeholder_side_b,
            preferred_day=match.preferred_day,
            status=match.status,
        )
        session.add(new_match)
        session.flush()  # Get new ID
        match_id_map[match.id] = new_match.id

    # Clone assignments using ID mappings
    # CRITICAL: Explicitly copy locked and assigned_by to preserve manual editor state
    source_assignments = session.exec(
        select(MatchAssignment).where(MatchAssignment.schedule_version_id == version_id)
    ).all()

    for assignment in source_assignments:
        new_assignment = MatchAssignment(
            schedule_version_id=new_version.id,
            slot_id=slot_id_map[assignment.slot_id],
            match_id=match_id_map[assignment.match_id],
            locked=assignment.locked,  # Preserve locked flag for manual editor
            assigned_by=assignment.assigned_by,  # Preserve assignment source
        )
        session.add(new_assignment)

    session.commit()
    session.refresh(new_version)

    return new_version


# ============================================================================
# Slots Models & Endpoints
# ============================================================================


class SlotGenerateRequest(BaseModel):
    source: str = "auto"  # "time_windows" or "days_courts" or "auto" (detects from tournament.use_time_windows)
    schedule_version_id: Optional[int] = None
    wipe_existing: bool = True


class SlotResponse(BaseModel):
    id: int
    tournament_id: int
    schedule_version_id: int
    day_date: str  # ISO date string
    start_time: str  # ISO time string
    end_time: str  # ISO time string
    court_number: int
    court_label: str  # Immutable label for this version
    block_minutes: int
    label: Optional[str] = None
    is_active: bool
    match_id: Optional[int] = None
    match_code: Optional[str] = None
    assignment_id: Optional[int] = None

    class Config:
        from_attributes = True


@router.post("/tournaments/{tournament_id}/schedule/slots/generate")
def generate_slots(
    tournament_id: int,
    request: Optional[SlotGenerateRequest] = None,
    session: Session = Depends(get_session),
    *,
    _transactional: bool = False,
):
    """Generate slots from time windows or days/courts (DRAFT-ONLY)

    If request body is empty or schedule_version_id is None, uses the active draft version.
    Returns 422 for validation errors, 409 for ambiguous draft selection, 404/400 for other errors.
    """
    # Validate tournament exists
    tournament = session.get(Tournament, tournament_id)
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")

    # Handle empty request body - FastAPI will validate the model if provided
    if request is None:
        request = SlotGenerateRequest()

    # Determine source: auto-detect from tournament settings, or use provided source
    if request.source == "auto":
        source = "time_windows" if tournament.use_time_windows else "days_courts"
    else:
        source = request.source

    if source not in ["time_windows", "days_courts"]:
        raise HTTPException(status_code=400, detail="Source must be 'time_windows' or 'days_courts'")

    # Get or create draft version (handles ambiguity)
    version = get_or_create_draft_version(session, tournament_id, request.schedule_version_id)

    # CHUNK 3: Draft-only guard
    require_draft_version(session, version.id, tournament_id)

    # Wipe existing slots if requested
    if request.wipe_existing:
        existing_slots = session.exec(select(ScheduleSlot).where(ScheduleSlot.schedule_version_id == version.id)).all()
        for slot in existing_slots:
            # Delete assignments first
            assignments = session.exec(select(MatchAssignment).where(MatchAssignment.slot_id == slot.id)).all()
            for assignment in assignments:
                # Update match status
                match = session.get(Match, assignment.match_id)
                if match:
                    match.status = "unscheduled"
                session.delete(assignment)
            session.delete(slot)

    slots_created = 0

    print(f"[DEBUG] Generating slots with source={source}, version_id={version.id}")

    # Get tournament to access court_names (used only via court_label_for_index — never pass labels list)
    tournament = session.get(Tournament, tournament_id)
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")

    if source == "time_windows":
        # Get active time windows
        time_windows = session.exec(
            select(TournamentTimeWindow)
            .where(TournamentTimeWindow.tournament_id == tournament_id, TournamentTimeWindow.is_active)
            .order_by(TournamentTimeWindow.day_date, TournamentTimeWindow.start_time)
        ).all()

        if not time_windows:
            raise HTTPException(status_code=400, detail="No active time windows found. Create time windows first.")

        # Generate slots for each time window
        for window in time_windows:
            # Validate window block_minutes
            if not window.block_minutes or window.block_minutes <= 0:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid block_minutes ({window.block_minutes}) for time window on {window.day_date}. Must be > 0.",
                )

            # Validate start/end times are on 15-minute increments
            if window.start_time.minute % 15 != 0:
                raise HTTPException(
                    status_code=400,
                    detail=f"Window start time {window.start_time} must be on 15-minute increment (e.g., 8:00, 8:15, 8:30, 8:45).",
                )
            if window.end_time.minute % 15 != 0:
                raise HTTPException(
                    status_code=400,
                    detail=f"Window end time {window.end_time} must be on 15-minute increment (e.g., 8:00, 8:15, 8:30, 8:45).",
                )

            # Calculate start and end minutes
            start_minutes = window.start_time.hour * 60 + window.start_time.minute
            end_minutes = window.end_time.hour * 60 + window.end_time.minute

            if end_minutes <= start_minutes:
                continue  # Skip invalid time ranges

            print(
                f"[DEBUG] Processing window: {window.day_date} {window.start_time}-{window.end_time}, courts={window.courts_available}, block_minutes={window.block_minutes}"
            )

            # Generate slots at block_minutes granularity (e.g., 60 or 105 minute slots)
            # Algorithm: t = start; while t + slot_len <= end: create slot; t += step
            for court_num in range(1, window.courts_available + 1):
                current_minutes = start_minutes
                court_slots = 0
                
                while current_minutes + window.block_minutes <= end_minutes:
                    # Calculate slot start time
                    slot_start_hour = current_minutes // 60
                    slot_start_min = current_minutes % 60
                    slot_start_time = time(slot_start_hour, slot_start_min)

                    # Calculate slot end time (block_minutes later)
                    slot_end_minutes = current_minutes + window.block_minutes
                    slot_end_hour = slot_end_minutes // 60
                    slot_end_min = slot_end_minutes % 60
                    slot_end_time = time(slot_end_hour, slot_end_min)

                    court_label = court_label_for_index(tournament.court_names, court_num)
                    slot = ScheduleSlot(
                        tournament_id=tournament_id,
                        schedule_version_id=version.id,
                        day_date=window.day_date,
                        start_time=slot_start_time,
                        end_time=slot_end_time,
                        court_number=court_num,
                        court_label=court_label,  # Scalar string only
                        block_minutes=window.block_minutes,  # Match the window's block duration
                        label=window.label,  # Preserve window label if any
                        is_active=True,
                    )
                    session.add(slot)
                    slots_created += 1
                    court_slots += 1
                    
                    # Increment by block_minutes (not 15)
                    current_minutes += window.block_minutes

                print(f"[DEBUG] Created {court_slots} slots for court {court_num} on {window.day_date}")
    else:  # days_courts
        # Get active tournament days
        active_days = session.exec(
            select(TournamentDay)
            .where(TournamentDay.tournament_id == tournament_id, TournamentDay.is_active)
            .order_by(TournamentDay.date)
        ).all()

        if not active_days:
            raise HTTPException(
                status_code=400, detail="No active tournament days found. Configure days and courts first."
            )

        # Generate slots for each active day
        for day in active_days:
            if not day.start_time or not day.end_time:
                continue  # Skip days without time range

            if day.courts_available < 1:
                continue  # Skip days with no courts

            # Calculate start and end minutes
            start_minutes = day.start_time.hour * 60 + day.start_time.minute
            end_minutes = day.end_time.hour * 60 + day.end_time.minute

            if end_minutes <= start_minutes:
                continue  # Skip invalid time ranges

            print(f"[DEBUG] Processing day: {day.date} {day.start_time}-{day.end_time}, courts={day.courts_available}")

            # Generate 15-minute start-time slots for each court (court_label via canonical fn only)
            for court_num in range(1, day.courts_available + 1):
                current_minutes = start_minutes
                court_slots = 0
                while current_minutes < end_minutes:
                    # Calculate slot start time
                    slot_start_hour = current_minutes // 60
                    slot_start_min = current_minutes % 60
                    slot_start_time = time(slot_start_hour, slot_start_min)

                    # Calculate slot end time (15 minutes later for grid display)
                    # Note: actual match occupation is determined by match.duration_minutes
                    slot_end_minutes = current_minutes + 15
                    slot_end_hour = slot_end_minutes // 60
                    slot_end_min = slot_end_minutes % 60
                    slot_end_time = time(slot_end_hour, slot_end_min)

                    # Don't exceed the day's end time
                    # If this would exceed, make it a shorter slot (but still create it)
                    if slot_end_minutes > end_minutes:
                        slot_end_time = day.end_time
                        # Calculate actual duration for this last slot
                        actual_duration = end_minutes - current_minutes
                    else:
                        actual_duration = 15

                    court_label = court_label_for_index(tournament.court_names, court_num)
                    slot = ScheduleSlot(
                        tournament_id=tournament_id,
                        schedule_version_id=version.id,
                        day_date=day.date,
                        start_time=slot_start_time,
                        end_time=slot_end_time,
                        court_number=court_num,
                        court_label=court_label,  # Scalar string only
                        block_minutes=actual_duration,  # 15 for most, less for last slot if needed
                        label=None,
                        is_active=True,
                    )
                    session.add(slot)
                    slots_created += 1
                    court_slots += 1
                    current_minutes += 15  # 15-minute tick interval

                    # If we've reached the end, break
                    if slot_end_minutes >= end_minutes:
                        break
                print(f"[DEBUG] Created {court_slots} slots for court {court_num} on {day.date}")

    # Fail-fast tripwire: court_label must never be a list before commit
    bad = []
    for obj in list(session.new):
        if obj.__class__.__name__ == "ScheduleSlot" and isinstance(getattr(obj, "court_label", None), list):
            bad.append((getattr(obj, "court_number", None), getattr(obj, "court_label", None)))
    if bad:
        raise ValueError(f"court_label list detected in session.new before commit: {bad[:3]}")

    if _transactional:
        session.flush()
    else:
        session.commit()

    print(f"[DEBUG] Total slots created: {slots_created}")

    # Verify slots were created
    created_slots = session.exec(select(ScheduleSlot).where(ScheduleSlot.schedule_version_id == version.id)).all()
    print(f"[DEBUG] Verified {len(created_slots)} slots in database")
    if len(created_slots) > 0:
        sample = created_slots[0]
        print(
            f"[DEBUG] Sample slot: day={sample.day_date}, time={sample.start_time}-{sample.end_time}, court={sample.court_number}"
        )

    return {"schedule_version_id": version.id, "slots_created": slots_created}


@router.get("/tournaments/{tournament_id}/schedule/slots", response_model=List[SlotResponse])
def get_slots(
    tournament_id: int,
    schedule_version_id: Optional[int] = Query(None),
    day_date: Optional[date] = Query(None),
    session: Session = Depends(get_session),
):
    """Get slots for a tournament"""
    tournament = session.get(Tournament, tournament_id)
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")

    # If no version specified, use current draft
    if not schedule_version_id:
        draft_version = session.exec(
            select(ScheduleVersion).where(
                ScheduleVersion.tournament_id == tournament_id, ScheduleVersion.status == "draft"
            )
        ).first()
        if not draft_version:
            return []
        schedule_version_id = draft_version.id

    query = select(ScheduleSlot).where(
        ScheduleSlot.tournament_id == tournament_id, ScheduleSlot.schedule_version_id == schedule_version_id
    )

    if day_date:
        query = query.where(ScheduleSlot.day_date == day_date)

    query = query.order_by(ScheduleSlot.day_date, ScheduleSlot.start_time, ScheduleSlot.court_number)

    slots = session.exec(query).all()

    # Build response with assignment info
    result = []
    for slot in slots:
        assignment = session.exec(select(MatchAssignment).where(MatchAssignment.slot_id == slot.id)).first()

        slot_data = {
            "id": slot.id,
            "tournament_id": slot.tournament_id,
            "schedule_version_id": slot.schedule_version_id,
            "day_date": str(slot.day_date),
            "start_time": str(slot.start_time),
            "end_time": str(slot.end_time),
            "court_number": slot.court_number,
            "court_label": slot.court_label,  # Include court label
            "block_minutes": slot.block_minutes,
            "label": slot.label,
            "is_active": slot.is_active,
            "match_id": None,
            "match_code": None,
            "assignment_id": None,
        }

        if assignment:
            match = session.get(Match, assignment.match_id)
            if match:
                slot_data["match_id"] = match.id
                slot_data["match_code"] = match.match_code
            slot_data["assignment_id"] = assignment.id

        result.append(slot_data)

    return result


# ============================================================================
# Matches Models & Endpoints
# ============================================================================


class MatchGenerateRequest(BaseModel):
    event_id: Optional[int] = None  # If None, generate for all FINAL events
    schedule_version_id: Optional[int] = None  # If None, use active draft version
    wipe_existing: bool = True

    @model_validator(mode="after")
    def validate_request(self):
        """Validate request parameters"""
        # FastAPI/Pydantic will handle type validation automatically
        # This is for any custom business logic validation
        return self


class MatchResponse(BaseModel):
    id: int
    tournament_id: int
    event_id: int
    schedule_version_id: int
    match_code: str
    match_type: str
    round_number: int
    round_index: int
    sequence_in_round: int
    duration_minutes: int
    placeholder_side_a: str
    placeholder_side_b: str
    status: str
    created_at: str
    slot_id: Optional[int] = None
    # Team injection fields (nullable - populated after team injection)
    team_a_id: Optional[int] = None
    team_b_id: Optional[int] = None
    # Day-Targeting V1: Preferred day of week (0=Monday, 6=Sunday)
    preferred_day: Optional[int] = None

    class Config:
        from_attributes = True


@router.post("/tournaments/{tournament_id}/schedule/matches/generate")
def generate_matches(
    tournament_id: int,
    request: Optional[MatchGenerateRequest] = None,
    session: Session = Depends(get_session),
    *,
    _transactional: bool = False,
):
    """Generate placeholder matches from finalized events using Draw Plan Engine.

    If request body is empty or schedule_version_id is None, uses the active draft version.
    Returns 422 for validation errors, 409 for ambiguous draft selection, 404/400 for other errors.
    All responses include CORS headers via CORSMiddleware.

    Match generation is now fully delegated to draw_plan_engine.generate_matches_for_event().
    """
    from app.services.draw_plan_engine import (
        build_spec_from_event,
        compute_inventory,
        generate_matches_for_event,
        resolve_event_family,
    )

    # Validate tournament exists
    tournament = session.get(Tournament, tournament_id)
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")

    # Handle empty request body - FastAPI will validate the model if provided
    if request is None:
        request = MatchGenerateRequest()

    # Get or create draft version (handles ambiguity)
    version = get_or_create_draft_version(session, tournament_id, request.schedule_version_id)

    seen_event_ids: List[int] = [
        e.id for e in session.exec(
            select(Event).where(Event.tournament_id == tournament_id).order_by(Event.id)
        ).all()
    ]

    # Get events to process
    if request.event_id:
        event = session.get(Event, request.event_id)
        if not event or event.tournament_id != tournament_id:
            raise HTTPException(status_code=404, detail="Event not found")
        if event.draw_status != "final":
            raise HTTPException(status_code=400, detail="Event must be finalized to generate matches")
        events = [event]
    else:
        # Get all finalized events - use pure Event query with deterministic ordering
        # IMPORTANT: Dedupe by event.id in case query returns duplicates
        events_raw = session.exec(
            select(Event)
            .where(Event.tournament_id == tournament_id)
            .where(Event.draw_status == "final")
            .order_by(Event.id)
        ).all()

        events_by_id: dict[int, Event] = {}
        for e in events_raw:
            if e.id not in events_by_id:
                events_by_id[e.id] = e
        events = list(events_by_id.values())

        # Diagnostic: log if dedupe made a difference
        if len(events_raw) != len(events):
            logger.warning(
                "DEDUPE: events_raw=%s events_unique=%s (query returned duplicates)",
                len(events_raw),
                len(events),
            )

    if not events:
        raise HTTPException(status_code=400, detail="No finalized events found")

    total_matches = 0
    per_event_breakdown = {}
    match_warnings: List[dict] = []
    generated_event_ids: set[int] = set()

    # Version-global existing_codes: built once, passed through so second pass skips in-memory
    existing_codes: set[str] = set(
        session.exec(
            select(Match.match_code).where(Match.schedule_version_id == version.id)
        ).all()
    )

    events_expected: List[dict] = []

    for event in events:
        if event.id in generated_event_ids:
            raise RuntimeError(f"Duplicate event in generation loop: event_id={event.id}")
        generated_event_ids.add(event.id)

        try:
            # Wipe existing matches for this event if requested (uses helper for correct order)
            if request.wipe_existing:
                wipe_matches_for_version(session, version.id, event_id=event.id)

            # Build spec from event using the engine
            spec = build_spec_from_event(event)

            # Validate spec via inventory computation
            inventory = compute_inventory(spec)
            if inventory.has_errors():
                raise ValueError("; ".join(inventory.errors))

            expected_count = inventory.total_matches
            existing_before = scalar_int(
                session.exec(
                    select(func.count(Match.id)).where(
                        Match.schedule_version_id == version.id,
                        Match.event_id == event.id,
                    )
                ).one()
            )

            # Check if event needs rebuild due to old placeholder format
            # Sample bracket matches to detect old format placeholders
            needs_rebuild = False
            if existing_before >= expected_count:
                # Check a sample of bracket matches for old placeholder format
                sample_bracket_matches = session.exec(
                    select(Match)
                    .where(
                        Match.schedule_version_id == version.id,
                        Match.event_id == event.id,
                        Match.match_type.in_(["MAIN", "BRACKET"]),
                    )
                    .limit(5)  # Sample a few matches
                ).all()
                
                if sample_bracket_matches:
                    # Check if any bracket match has old placeholder format
                    for match in sample_bracket_matches:
                        placeholder_a = match.placeholder_side_a or ""
                        placeholder_b = match.placeholder_side_b or ""
                        # Old format: "Division X TBD" or ends with " TBD" or starts with "Bracket"
                        if (
                            placeholder_a.startswith("Division ") or
                            placeholder_a.endswith(" TBD") or
                            placeholder_a.startswith("Bracket ") or
                            placeholder_b.startswith("Division ") or
                            placeholder_b.endswith(" TBD") or
                            placeholder_b.startswith("Bracket ")
                        ):
                            needs_rebuild = True
                            logger.info(
                                f"Event {event.id} ({event.name}): Detected old placeholder format "
                                f"('{placeholder_a}' / '{placeholder_b}'), marking for rebuild"
                            )
                            break

            # Event-scoped idempotency: skip if already complete AND placeholders are current
            if existing_before >= expected_count and not needs_rebuild:
                per_event_breakdown[event.id] = {"event_name": event.name, "matches": 0}
                events_expected.append({
                    "event_id": event.id,
                    "event_name": event.name,
                    "expected": expected_count,
                    "existing_before": existing_before,
                    "generated_added": 0,
                    "decision": "skip_complete",
                    "reason": "existing>=expected and placeholders current",
                })
                continue
            
            # If needs rebuild, wipe existing matches for this event
            if needs_rebuild:
                logger.info(
                    f"Event {event.id} ({event.name}): Wiping {existing_before} existing matches "
                    f"due to old placeholder format"
                )
                # Get match codes before wiping (for existing_codes cleanup)
                wiped_codes = set(
                    session.exec(
                        select(Match.match_code).where(
                            Match.schedule_version_id == version.id,
                            Match.event_id == event.id,
                        )
                    ).all()
                )
                # Wipe matches for this event
                wipe_matches_for_version(session, version.id, event_id=event.id)
                existing_before = 0
                # Remove wiped match codes from existing_codes set
                existing_codes.difference_update(wiped_codes)
                events_expected.append({
                    "event_id": event.id,
                    "event_name": event.name,
                    "expected": expected_count,
                    "existing_before": len(wiped_codes),
                    "generated_added": 0,
                    "decision": "rebuild_placeholders",
                    "reason": "old placeholder format detected",
                })

            family = resolve_event_family(spec)
            logger.info(
                "GENERATE_MATCHES: event_id=%s name=%s family=%s template_key=%s team_count=%s",
                event.id, event.name, family, spec.template_key, spec.team_count
            )

            # Get linked teams in seed order
            linked_teams = session.exec(
                select(Team).where(Team.event_id == event.id).order_by(Team.seed, Team.id)
            ).all()
            linked_team_ids = [t.id for t in linked_teams]

            # Generate matches via engine (existing_codes mutated in-place for idempotency)
            matches, warnings = generate_matches_for_event(
                session, version.id, spec, linked_team_ids, existing_codes
            )

            # Add matches to session
            for match in matches:
                session.add(match)

            matches_for_event = len(matches)
            total_matches += matches_for_event
            per_event_breakdown[event.id] = {"event_name": event.name, "matches": matches_for_event}
            events_expected.append({
                "event_id": event.id,
                "event_name": event.name,
                "expected": expected_count,
                "existing_before": existing_before,
                "generated_added": matches_for_event,
                "decision": "generate_missing",
                "reason": "existing<expected",
            })

            # Add any warnings from generation
            for w in warnings:
                match_warnings.append({"message": w, "event_id": event.id, "event_name": event.name})

            # Flush to persist matches
            session.flush()

            # Validate: when we have enough linked teams, non-dependency matches must have teams
            teams_linked = len(linked_team_ids)
            event_matches = session.exec(
                select(Match).where(Match.event_id == event.id, Match.schedule_version_id == version.id)
            ).all()

            def _has_deps(m: Match) -> bool:
                return (
                    getattr(m, "source_match_a_id", None) is not None
                    or getattr(m, "source_match_b_id", None) is not None
                )

            null_team_count = sum(
                1 for m in event_matches
                if (m.team_a_id is None or m.team_b_id is None) and not _has_deps(m)
            )

            # Only enforce null-team check for RR_ONLY (which requires all teams upfront)
            if family == "RR_ONLY" and teams_linked >= event.team_count and null_team_count > 0:
                raise ValueError(
                    f"generate_matches produced null teams for event_id={event.id} ({event.name}): "
                    f"{null_team_count} matches with null team_a_id or team_b_id "
                    f"(teams_linked={teams_linked}, event.team_count={event.team_count})"
                )

        except Exception as e:
            # Skip this event but continue with others
            logger.warning("generate_matches failed for event %s: %s", event.id, str(e))
            match_warnings.append({"message": str(e), "event_id": event.id, "event_name": event.name})
            per_event_breakdown[event.id] = {"event_name": event.name, "matches": 0}
            try:
                spec = build_spec_from_event(event)
                inv = compute_inventory(spec)
                exp = inv.total_matches if not inv.has_errors() else 0
            except Exception:
                exp = 0
            existing_before = scalar_int(
                session.exec(
                    select(func.count(Match.id)).where(
                        Match.schedule_version_id == version.id,
                        Match.event_id == event.id,
                    )
                ).one()
            )
            reason = str(e)[:80] if str(e) else "exception"
            events_expected.append({
                "event_id": event.id,
                "event_name": event.name,
                "expected": exp,
                "existing_before": existing_before,
                "generated_added": 0,
                "decision": "skipped_error",
                "reason": reason,
            })
            continue

    if _transactional:
        session.flush()
    else:
        session.commit()

    all_complete = len(events_expected) > 0 and all(
        ev.get("existing_before", 0) + ev.get("generated_added", 0) >= ev.get("expected", 0)
        for ev in events_expected
    )

    finalized_event_ids = [e.id for e in events]
    for eid in seen_event_ids:
        if eid not in {ev["event_id"] for ev in events_expected}:
            evt = session.get(Event, eid)
            if evt:
                events_expected.append({
                    "event_id": evt.id,
                    "event_name": evt.name,
                    "expected": 0,
                    "existing_before": 0,
                    "generated_added": 0,
                    "decision": "skipped_not_final",
                    "reason": f"draw_status={evt.draw_status or 'null'}",
                })
    events_expected.sort(key=lambda x: x["event_id"])
    out: dict = {
        "schedule_version_id": version.id,
        "total_matches_created": total_matches,
        "per_event": per_event_breakdown,
        "finalized_events_found": [e.name for e in events],
        "seen_event_ids": seen_event_ids,
        "finalized_event_ids": finalized_event_ids,
        "events_expected": events_expected,
        "already_complete": all_complete and total_matches == 0,
    }
    if match_warnings:
        out["warnings"] = match_warnings
    return out


@router.get("/tournaments/{tournament_id}/schedule/matches", response_model=List[MatchResponse])
def get_matches(
    tournament_id: int,
    schedule_version_id: Optional[int] = Query(None),
    event_id: Optional[int] = Query(None),
    status: Optional[str] = Query(None),
    session: Session = Depends(get_session),
):
    """Get matches for a tournament"""
    tournament = session.get(Tournament, tournament_id)
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")

    # If no version specified, use current draft
    if not schedule_version_id:
        draft_version = session.exec(
            select(ScheduleVersion).where(
                ScheduleVersion.tournament_id == tournament_id, ScheduleVersion.status == "draft"
            )
        ).first()
        if not draft_version:
            return []
        schedule_version_id = draft_version.id

    query = select(Match).where(Match.tournament_id == tournament_id, Match.schedule_version_id == schedule_version_id)

    if event_id:
        query = query.where(Match.event_id == event_id)

    if status:
        query = query.where(Match.status == status)

    query = query.order_by(Match.event_id, Match.round_number, Match.sequence_in_round)

    matches = session.exec(query).all()

    # Build response with assignment info
    result = []
    for match in matches:
        assignment = session.exec(select(MatchAssignment).where(MatchAssignment.match_id == match.id)).first()

        match_data = {
            "id": match.id,
            "tournament_id": match.tournament_id,
            "event_id": match.event_id,
            "schedule_version_id": match.schedule_version_id,
            "match_code": match.match_code,
            "match_type": match.match_type,
            "round_number": match.round_number,
            "round_index": match.round_index,
            "sequence_in_round": match.sequence_in_round,
            "duration_minutes": match.duration_minutes,
            "placeholder_side_a": match.placeholder_side_a,
            "placeholder_side_b": match.placeholder_side_b,
            "status": match.status,
            "created_at": match.created_at.isoformat(),
            "slot_id": assignment.slot_id if assignment else None,
            # Team injection fields (nullable)
            "team_a_id": match.team_a_id,
            "team_b_id": match.team_b_id,
            # Day-Targeting V1
            "preferred_day": match.preferred_day,
        }

        result.append(match_data)

    return result


class MatchUpdate(BaseModel):
    """Request model for updating match properties"""

    preferred_day: Optional[int] = None

    @model_validator(mode="after")
    def validate_preferred_day(self):
        if self.preferred_day is not None and not (0 <= self.preferred_day <= 6):
            raise ValueError("preferred_day must be between 0 (Monday) and 6 (Sunday), or null")
        return self


@router.patch("/tournaments/{tournament_id}/schedule/matches/{match_id}", response_model=MatchResponse)
def update_match(tournament_id: int, match_id: int, update_data: MatchUpdate, session: Session = Depends(get_session)):
    """Update match properties (currently only preferred_day)"""
    # Validate tournament exists
    tournament = session.get(Tournament, tournament_id)
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")

    # Get match
    match = session.get(Match, match_id)
    if not match or match.tournament_id != tournament_id:
        raise HTTPException(status_code=404, detail="Match not found")

    # Update preferred_day if provided
    if update_data.preferred_day is not None:
        match.preferred_day = update_data.preferred_day

    session.add(match)
    session.commit()
    session.refresh(match)

    # Get assignment info for response
    assignment = session.exec(select(MatchAssignment).where(MatchAssignment.match_id == match.id)).first()

    return MatchResponse(
        id=match.id,
        tournament_id=match.tournament_id,
        event_id=match.event_id,
        schedule_version_id=match.schedule_version_id,
        match_code=match.match_code,
        match_type=match.match_type,
        round_number=match.round_number,
        round_index=match.round_index,
        sequence_in_round=match.sequence_in_round,
        duration_minutes=match.duration_minutes,
        placeholder_side_a=match.placeholder_side_a,
        placeholder_side_b=match.placeholder_side_b,
        status=match.status,
        created_at=match.created_at.isoformat(),
        slot_id=assignment.slot_id if assignment else None,
        team_a_id=match.team_a_id,
        team_b_id=match.team_b_id,
        preferred_day=match.preferred_day,
    )


# ============================================================================
# Assignments Models & Endpoints
# ============================================================================


class AssignmentCreate(BaseModel):
    schedule_version_id: int
    match_id: int
    slot_id: int


@router.post("/tournaments/{tournament_id}/schedule/assignments", status_code=201)
def create_assignment(tournament_id: int, data: AssignmentCreate, session: Session = Depends(get_session)):
    """Assign a match to a slot"""
    tournament = session.get(Tournament, tournament_id)
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")

    # Validate version
    version = session.get(ScheduleVersion, data.schedule_version_id)
    if not version or version.tournament_id != tournament_id:
        raise HTTPException(status_code=404, detail="Schedule version not found")
    if version.status == "final":
        raise HTTPException(status_code=400, detail="Cannot modify finalized version")

    # Validate slot
    slot = session.get(ScheduleSlot, data.slot_id)
    if not slot or slot.schedule_version_id != data.schedule_version_id:
        raise HTTPException(status_code=404, detail="Slot not found")
    if not slot.is_active:
        raise HTTPException(status_code=400, detail="Slot is not active")

    # Validate match
    match = session.get(Match, data.match_id)
    if not match or match.schedule_version_id != data.schedule_version_id:
        raise HTTPException(status_code=404, detail="Match not found")

    # Check if match is already assigned
    existing_assignment = session.exec(
        select(MatchAssignment)
        .where(MatchAssignment.schedule_version_id == data.schedule_version_id)
        .where(MatchAssignment.match_id == data.match_id)
    ).first()

    if existing_assignment:
        raise HTTPException(status_code=400, detail="Match is already assigned")

    # Check if slot is already assigned (exact slot check)
    existing_slot_assignment = session.exec(
        select(MatchAssignment)
        .where(MatchAssignment.schedule_version_id == data.schedule_version_id)
        .where(MatchAssignment.slot_id == data.slot_id)
    ).first()

    if existing_slot_assignment:
        raise HTTPException(status_code=400, detail="Slot is already assigned")

    # Calculate match time range
    # Slots are start opportunities (15-min ticks), matches occupy [start, start + duration)
    slot_start_minutes = slot.start_time.hour * 60 + slot.start_time.minute
    match_end_minutes = slot_start_minutes + match.duration_minutes

    # Check for overlaps with other matches on the same court
    # Get all assignments on the same court, same day, same version
    court_assignments = session.exec(
        select(MatchAssignment)
        .join(ScheduleSlot, MatchAssignment.slot_id == ScheduleSlot.id)
        .join(Match, MatchAssignment.match_id == Match.id)
        .where(
            MatchAssignment.schedule_version_id == data.schedule_version_id,
            ScheduleSlot.day_date == slot.day_date,
            ScheduleSlot.court_number == slot.court_number,
        )
    ).all()

    for existing_assignment in court_assignments:
        existing_slot = session.get(ScheduleSlot, existing_assignment.slot_id)
        existing_match = session.get(Match, existing_assignment.match_id)

        if existing_slot and existing_match:
            existing_start_minutes = existing_slot.start_time.hour * 60 + existing_slot.start_time.minute
            existing_end_minutes = existing_start_minutes + existing_match.duration_minutes

            # Check for overlap: [start1, end1) overlaps [start2, end2) if start1 < end2 AND start2 < end1
            if slot_start_minutes < existing_end_minutes and existing_start_minutes < match_end_minutes:
                raise HTTPException(
                    status_code=409,
                    detail=f"Match would overlap with existing match on {slot.court_label} at {existing_slot.start_time}",
                )

    # Validate: Check if match would exceed day end time
    # Get the latest slot for this day to determine end time
    from app.models.tournament_day import TournamentDay
    tournament_day = session.exec(
        select(TournamentDay).where(
            TournamentDay.tournament_id == tournament_id,
            TournamentDay.date == slot.day_date,
            TournamentDay.is_active == True,
        )
    ).first()

    if tournament_day and tournament_day.end_time:
        # Calculate day end in minutes
        day_end_minutes = tournament_day.end_time.hour * 60 + tournament_day.end_time.minute
        
        # Check if match would exceed day end
        if match_end_minutes > day_end_minutes:
            match_end_time = time(
                hour=match_end_minutes // 60,
                minute=match_end_minutes % 60
            )
            raise HTTPException(
                status_code=400,
                detail=f"Match would end at {match_end_time.strftime('%H:%M')}, but schedule ends at {tournament_day.end_time.strftime('%H:%M')} on {slot.day_date}",
            )
    else:
        # Fallback: Calculate from slots if TournamentDay not available
        latest_slot = session.exec(
            select(ScheduleSlot)
            .where(
                ScheduleSlot.schedule_version_id == version.id,
                ScheduleSlot.day_date == slot.day_date,
            )
            .order_by(ScheduleSlot.start_time.desc())
        ).first()
        
        if latest_slot:
            latest_slot_end_minutes = latest_slot.start_time.hour * 60 + latest_slot.start_time.minute + latest_slot.block_minutes
            if match_end_minutes > latest_slot_end_minutes:
                match_end_time = time(
                    hour=match_end_minutes // 60,
                    minute=match_end_minutes % 60
                )
                latest_end_time = time(
                    hour=latest_slot_end_minutes // 60,
                    minute=latest_slot_end_minutes % 60
                )
                raise HTTPException(
                    status_code=400,
                    detail=f"Match would end at {match_end_time.strftime('%H:%M')}, but last slot ends at {latest_end_time.strftime('%H:%M')} on {slot.day_date}",
                )

    # Create assignment
    assignment = MatchAssignment(
        schedule_version_id=data.schedule_version_id, match_id=data.match_id, slot_id=data.slot_id
    )
    session.add(assignment)

    # Update match status
    match.status = "scheduled"
    session.add(match)

    session.commit()
    session.refresh(assignment)

    return {
        "id": assignment.id,
        "schedule_version_id": assignment.schedule_version_id,
        "match_id": assignment.match_id,
        "slot_id": assignment.slot_id,
        "assigned_at": assignment.assigned_at.isoformat(),
    }


@router.delete("/tournaments/{tournament_id}/schedule/assignments/{assignment_id}", status_code=204)
def delete_assignment(tournament_id: int, assignment_id: int, session: Session = Depends(get_session)):
    """Unassign a match from a slot"""
    tournament = session.get(Tournament, tournament_id)
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")

    assignment = session.get(MatchAssignment, assignment_id)
    if not assignment:
        raise HTTPException(status_code=404, detail="Assignment not found")

    # Verify version belongs to tournament
    version = session.get(ScheduleVersion, assignment.schedule_version_id)
    if not version or version.tournament_id != tournament_id:
        raise HTTPException(status_code=404, detail="Assignment not found")

    if version.status == "final":
        raise HTTPException(status_code=400, detail="Cannot modify finalized version")

    # Update match status
    match = session.get(Match, assignment.match_id)
    if match:
        match.status = "unscheduled"
        session.add(match)

    session.delete(assignment)
    session.commit()

    return None


# ============================================================================
# Manual Schedule Editor - Manual Assignment Endpoints
# ============================================================================


class ManualAssignmentRequest(BaseModel):
    """Request to manually assign/reassign a match to a slot"""
    
    new_slot_id: int


class SlotKey(BaseModel):
    """Stable slot identifier (UI doesn't need extra lookups)"""
    
    day_date: str
    start_time: str
    court_number: int
    court_label: str


class ManualAssignmentResponse(BaseModel):
    """Response from manual assignment operation"""
    
    assignment_id: int
    match_id: int
    slot_id: int
    locked: bool
    assigned_by: str
    assigned_at: str
    validation_passed: bool
    
    # Phase 3D.1: Enriched response (zero additional UI calls needed)
    slot_key: SlotKey
    conflicts_summary: ConflictReportSummary
    unassigned_matches: List[UnassignedMatchDetail]


@router.patch(
    "/tournaments/{tournament_id}/schedule/assignments/{assignment_id}",
    response_model=ManualAssignmentResponse
)
def manually_reassign_match(
    tournament_id: int,
    assignment_id: int,
    request: ManualAssignmentRequest,
    session: Session = Depends(get_session),
):
    """
    Manually reassign a match to a different slot (Manual Schedule Editor).
    
    **Manual Editor Rules:**
    - Only works on DRAFT schedules (not finalized)
    - Creates locked=True assignments so auto-assign skips them
    - Enforces hard invariants:
      * No slot overlap (one match per slot)
      * Duration fit (match must fit in slot)
      * Stage ordering preserved (WF → MAIN → CONSOLATION → PLACEMENT)
      * Consolation rules (no violations)
    
    **Workflow:**
    1. Admin drags match to new slot in UI
    2. UI calls this endpoint with new_slot_id
    3. Backend validates the move
    4. If valid: Updates assignment with locked=True
    5. If invalid: Returns 422 with validation error
    
    **Undo Support:**
    - Clone draft version before making changes
    - Restore by switching back to cloned version
    
    Args:
        tournament_id: Tournament ID
        assignment_id: Assignment ID to update
        request: New slot ID
    
    Returns:
        Updated assignment with locked=True
    
    Raises:
        404: Assignment/tournament/slot not found
        422: Validation failed (see error message for reason)
        400: Schedule is finalized (clone to draft first)
    """
    from app.utils.manual_assignment import (
        manually_assign_match,
        ManualAssignmentValidationError,
    )
    
    # Validate tournament
    tournament = session.get(Tournament, tournament_id)
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")
    
    # Get existing assignment
    assignment = session.get(MatchAssignment, assignment_id)
    if not assignment:
        raise HTTPException(status_code=404, detail="Assignment not found")
    
    # Verify assignment belongs to tournament
    version = session.get(ScheduleVersion, assignment.schedule_version_id)
    if not version or version.tournament_id != tournament_id:
        raise HTTPException(status_code=404, detail="Assignment not found in tournament")
    
    # Manually reassign (with validation)
    try:
        updated_assignment = manually_assign_match(
            session=session,
            match_id=assignment.match_id,
            new_slot_id=request.new_slot_id,
            schedule_version_id=assignment.schedule_version_id,
            assigned_by="MANUAL",
        )
        session.commit()
        
        # Phase 3D.1: Get slot for stable key
        slot = session.get(ScheduleSlot, updated_assignment.slot_id)
        if not slot:
            raise HTTPException(status_code=500, detail="Slot not found after assignment")
        
        # Phase 3D.2: Recompute conflicts deterministically (service layer)
        from app.services.conflict_report_builder import ConflictReportBuilder
        
        builder = ConflictReportBuilder()
        conflict_report = builder.compute(
            session=session,
            tournament_id=tournament_id,
            schedule_version_id=assignment.schedule_version_id,
            event_id=None,  # No event filter for PATCH (recompute all)
        )
        
        # Build enriched response
        return ManualAssignmentResponse(
            assignment_id=updated_assignment.id,
            match_id=updated_assignment.match_id,
            slot_id=updated_assignment.slot_id,
            locked=updated_assignment.locked,
            assigned_by=updated_assignment.assigned_by or "MANUAL",
            assigned_at=updated_assignment.assigned_at.isoformat(),
            validation_passed=True,
            # Phase 3D.1: Stable slot key (no UI lookups needed)
            slot_key=SlotKey(
                day_date=slot.day_date.isoformat() if slot.day_date else "",
                start_time=slot.start_time.isoformat() if slot.start_time else "",
                court_number=slot.court_number,
                court_label=slot.court_label,
            ),
            # Phase 3D.1: Deterministic conflicts (same as GET /conflicts)
            conflicts_summary=conflict_report.summary,
            unassigned_matches=conflict_report.unassigned,
        )
    except ManualAssignmentValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))


# ============================================================================
# Build Endpoint (One-Click Build)
# ============================================================================


class BuildScheduleResponse(BaseModel):
    schedule_version_id: int
    slots_created: int
    matches_created: int
    matches_assigned: int
    matches_unassigned: int
    conflicts: Optional[List[dict]] = None
    warnings: Optional[List[dict]] = None


@router.post(
    "/tournaments/{tournament_id}/schedule/versions/{version_id}/build-legacy", response_model=BuildScheduleResponse
)
def build_schedule_legacy(tournament_id: int, version_id: int, session: Session = Depends(get_session)):
    """LEGACY: One-click build (replaced by /build endpoint with orchestrator)"""
    tournament = session.get(Tournament, tournament_id)
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")

    # Validate version
    version = session.get(ScheduleVersion, version_id)
    if not version or version.tournament_id != tournament_id:
        raise HTTPException(status_code=404, detail="Schedule version not found")
    if version.status == "final":
        raise HTTPException(status_code=400, detail="Cannot modify finalized version")

    try:
        # Wipe existing data in correct order BEFORE generating new data
        # Order: MatchAssignments → Matches → Slots (child→parent)
        # This ensures FK constraints are satisfied

        # Step 0: Wipe all matches and assignments for this version (uses helper for correct order)
        wipe_matches_for_version(session, version_id)
        # Note: Slots will be wiped by generate_slots with wipe_existing=True

        # Step 1: Generate slots (will wipe existing slots internally)
        slot_request = SlotGenerateRequest(source="auto", schedule_version_id=version_id, wipe_existing=True)
        slots_result = generate_slots(tournament_id, slot_request, session)
        slots_created = slots_result.get("slots_created", 0)

        # Step 2: Generate matches (matches already wiped above, but wipe_existing=True ensures clean state)
        match_request = MatchGenerateRequest(
            schedule_version_id=version_id,
            wipe_existing=True,  # This will use the helper function internally
        )
        matches_result = generate_matches(tournament_id, match_request, session)
        matches_created = matches_result.get("total_matches_created", 0)

        # Step 3: Count assignments (auto-place would go here in future)
        # For now, just count existing assignments
        matches = session.exec(select(Match).where(Match.schedule_version_id == version_id)).all()

        assigned_count = sum(1 for m in matches if m.status == "scheduled")
        unassigned_count = sum(1 for m in matches if m.status == "unscheduled")

        return BuildScheduleResponse(
            schedule_version_id=version_id,
            slots_created=slots_created,
            matches_created=matches_created,
            matches_assigned=assigned_count,
            matches_unassigned=unassigned_count,
            conflicts=None,
            warnings=None,
        )
    except HTTPException:
        raise
    except Exception as e:
        # Parse error to provide structured error information
        error_str = str(e)
        error_type = "unknown"
        error_phase = "unknown"
        constraint_name = None

        # Detect constraint violations
        if "UNIQUE constraint" in error_str or "IntegrityError" in error_str:
            error_type = "constraint_violation"
            # Extract constraint name if possible
            import re

            constraint_match = re.search(r"UNIQUE constraint failed: (\w+\.\w+)", error_str)
            if constraint_match:
                constraint_name = constraint_match.group(1)

        # Detect table/column errors
        if "no such table" in error_str.lower() or "no such column" in error_str.lower():
            error_type = "schema_error"

        # Detect phase (which step failed)
        if "slots" in error_str.lower() or "slot" in error_str.lower():
            error_phase = "slot_generation"
        elif "match" in error_str.lower():
            error_phase = "match_generation"
        elif "assignment" in error_str.lower():
            error_phase = "assignment"
        else:
            error_phase = "build"

        # Return structured error
        error_detail = {
            "error": "Build failed",
            "message": error_str,
            "error_type": error_type,
            "error_phase": error_phase,
        }
        if constraint_name:
            error_detail["constraint"] = constraint_name

        raise HTTPException(status_code=500, detail=error_detail)


# ============================================================================
# Conflict Reporting V1
# ============================================================================


class UnassignedMatchDetail(BaseModel):
    match_id: int
    stage: str
    round_index: int
    sequence_in_round: int
    duration_minutes: int
    reason: str
    notes: Optional[str] = None


class SlotPressure(BaseModel):
    unused_slots_count: int
    unused_slots_by_day: dict[str, int]
    unused_slots_by_court: dict[str, int]
    insufficient_duration_slots_count: int
    longest_match_duration: int
    max_slot_duration: int


class StageTimeline(BaseModel):
    stage: str
    first_assigned_start_time: Optional[str] = None
    last_assigned_start_time: Optional[str] = None
    assigned_count: int
    unassigned_count: int
    spillover_warning: bool


class OrderingViolation(BaseModel):
    type: str
    earlier_match_id: int
    later_match_id: int
    details: str


class OrderingIntegrity(BaseModel):
    deterministic_order_ok: bool
    violations: List[OrderingViolation]


class ConflictReportSummary(BaseModel):
    tournament_id: int
    schedule_version_id: int
    total_slots: int
    total_matches: int
    assigned_matches: int
    unassigned_matches: int
    assignment_rate: float


class ConflictReportV1(BaseModel):
    summary: ConflictReportSummary
    unassigned: List[UnassignedMatchDetail]
    slot_pressure: SlotPressure
    stage_timeline: List[StageTimeline]
    ordering_integrity: OrderingIntegrity


# Phase 3D.1: ConflictReportBuilder extraction (behavior-preserving)
@router.get("/tournaments/{tournament_id}/schedule/conflicts", response_model=ConflictReportV1)
def get_schedule_conflicts(
    tournament_id: int,
    schedule_version_id: int = Query(..., description="Required schedule version ID"),
    event_id: Optional[int] = Query(None, description="Optional event filter"),
    session: Session = Depends(get_session),
):
    """
    Get comprehensive conflict report for a schedule version.

    This endpoint is read-only and provides diagnostic information about:
    - Assignment coverage (assigned vs unassigned matches)
    - Reasons for unassigned matches
    - Slot utilization pressure
    - Stage timeline and spillover warnings
    - Ordering integrity violations
    - Team overlap conflicts (for matches with known teams)
    
    Phase 3D.1: Uses ConflictReportBuilder service (pure deterministic computation).
    """
    from app.services.conflict_report_builder import ConflictReportBuilder

    # Validate tournament (HTTP concern, stays in route)
    tournament = session.get(Tournament, tournament_id)
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")

    # Validate schedule version (HTTP concern, stays in route)
    version = session.get(ScheduleVersion, schedule_version_id)
    if not version or version.tournament_id != tournament_id:
        raise HTTPException(status_code=404, detail="Schedule version not found")

    # Compute conflicts using service layer (pure computation)
    builder = ConflictReportBuilder()
    return builder.compute(
        session=session,
        tournament_id=tournament_id,
        schedule_version_id=schedule_version_id,
        event_id=event_id,
    )


# ============================================================================
# Team Conflicts Revalidation (Read-Only)
# ============================================================================

from app.utils.conflict_report import TeamConflictsSummary


@router.get(
    "/tournaments/{tournament_id}/schedule/team-conflicts",
    response_model=TeamConflictsSummary,
)
def get_team_conflicts(
    tournament_id: int,
    schedule_version_id: int = Query(..., description="Required schedule version ID"),
    session: Session = Depends(get_session),
):
    """
    Revalidate team overlap conflicts for a schedule version (read-only).
    
    This endpoint checks for team scheduling conflicts where the same team
    is scheduled in overlapping time slots. It only evaluates matches where
    both team_a_id and team_b_id are known (not null).
    
    Use this after:
    - Dependencies resolve and team IDs are populated
    - Manual edits to the schedule
    - Team assignments change
    
    Returns:
        TeamConflictsSummary with:
        - known_team_conflicts_count: Number of detected overlaps
        - unknown_team_matches_count: Matches still without teams
        - conflicts: List of specific conflict details
    
    Guarantees:
        - Read-only (does NOT mutate assignments)
        - Deterministic output ordering (sorted by match_id, team_id)
        - Same input → same output
    """
    from app.services.conflict_report_builder import ConflictReportBuilder

    # Validate tournament
    tournament = session.get(Tournament, tournament_id)
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")

    # Validate schedule version
    version = session.get(ScheduleVersion, schedule_version_id)
    if not version or version.tournament_id != tournament_id:
        raise HTTPException(status_code=404, detail="Schedule version not found")

    # Compute full report and extract team conflicts
    builder = ConflictReportBuilder()
    report = builder.compute(
        session=session,
        tournament_id=tournament_id,
        schedule_version_id=schedule_version_id,
        event_id=None,
    )
    
    # Return just the team conflicts summary
    if report.team_conflicts:
        return report.team_conflicts
    
    # Fallback if team_conflicts is None (shouldn't happen)
    return TeamConflictsSummary(
        known_team_conflicts_count=0,
        unknown_team_matches_count=0,
        conflicts=[],
    )


# ============================================================================
# Grid Population V1
# ============================================================================


class GridSlot(BaseModel):
    slot_id: int
    start_time: str
    duration_minutes: int
    court_id: int
    court_label: str
    day_date: str


class GridAssignment(BaseModel):
    id: int  # Assignment database ID (required for PATCH endpoint)
    slot_id: int
    match_id: int


class GridMatch(BaseModel):
    match_id: int
    stage: str
    round_index: int
    sequence_in_round: int
    duration_minutes: int
    match_code: str
    event_id: int
    # Team injection fields (nullable)
    team_a_id: Optional[int] = None
    team_b_id: Optional[int] = None
    placeholder_side_a: str
    placeholder_side_b: str
    # Day-Targeting V1
    preferred_day: Optional[int] = None


class TeamInfo(BaseModel):
    """Lightweight team info for grid display"""

    id: int
    name: str
    seed: Optional[int] = None
    event_id: int


class ScheduleGridV1(BaseModel):
    slots: List[GridSlot]
    assignments: List[GridAssignment]
    matches: List[GridMatch]
    teams: List[TeamInfo]  # Team dictionary for ID→name mapping
    conflicts_summary: Optional[ConflictReportSummary] = None


@router.get("/tournaments/{tournament_id}/schedule/grid", response_model=ScheduleGridV1)
def get_schedule_grid(
    tournament_id: int,
    schedule_version_id: int = Query(..., description="Required schedule version ID"),
    session: Session = Depends(get_session),
):
    """
    Get schedule grid payload with slots, assignments, and matches in one call.

    This endpoint provides a composite payload optimized for grid rendering.
    Returns all data needed to build a schedule grid without additional API calls.

    Read-only operation - returns 200 even if assignments are empty.
    """
    # Validate tournament
    tournament = session.get(Tournament, tournament_id)
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")

    # Validate schedule version
    version = session.get(ScheduleVersion, schedule_version_id)
    if not version or version.tournament_id != tournament_id:
        raise HTTPException(status_code=404, detail="Schedule version not found")

    # ========================================================================
    # Fetch slots
    # ========================================================================
    slot_query = (
        select(ScheduleSlot)
        .where(
            ScheduleSlot.tournament_id == tournament_id,
            ScheduleSlot.schedule_version_id == schedule_version_id,
            ScheduleSlot.is_active,
        )
        .order_by(ScheduleSlot.day_date, ScheduleSlot.start_time, ScheduleSlot.court_number)
    )
    slots = session.exec(slot_query).all()

    # Build grid slots
    grid_slots = []
    for slot in slots:
        grid_slots.append(
            GridSlot(
                slot_id=slot.id,
                start_time=slot.start_time.isoformat(),
                duration_minutes=slot.block_minutes,
                court_id=slot.court_number,
                court_label=slot.court_label,
                day_date=slot.day_date.isoformat(),
            )
        )

    # ========================================================================
    # Fetch assignments
    # ========================================================================
    assignment_query = select(MatchAssignment).where(MatchAssignment.schedule_version_id == schedule_version_id)
    assignments = session.exec(assignment_query).all()

    # Build grid assignments
    grid_assignments = []
    for assignment in assignments:
        grid_assignments.append(GridAssignment(id=assignment.id, slot_id=assignment.slot_id, match_id=assignment.match_id))

    # ========================================================================
    # Fetch matches
    # ========================================================================
    match_query = select(Match).where(
        Match.tournament_id == tournament_id, Match.schedule_version_id == schedule_version_id
    )
    matches = session.exec(match_query).all()

    # Build grid matches
    grid_matches = []
    for match in matches:
        grid_matches.append(
            GridMatch(
                match_id=match.id,
                stage=match.match_type,
                round_index=match.round_index,
                sequence_in_round=match.sequence_in_round,
                duration_minutes=match.duration_minutes,
                match_code=match.match_code,
                event_id=match.event_id,
                team_a_id=match.team_a_id,
                team_b_id=match.team_b_id,
                placeholder_side_a=match.placeholder_side_a,
                placeholder_side_b=match.placeholder_side_b,
                preferred_day=match.preferred_day,
            )
        )

    # ========================================================================
    # Build conflicts summary (optional)
    # ========================================================================
    total_matches = len(matches)
    assigned_count = len(assignments)
    unassigned_count = total_matches - assigned_count
    assignment_rate = round((assigned_count / total_matches * 100), 1) if total_matches > 0 else 0.0

    conflicts_summary = ConflictReportSummary(
        tournament_id=tournament_id,
        schedule_version_id=schedule_version_id,
        total_slots=len(slots),
        total_matches=total_matches,
        assigned_matches=assigned_count,
        unassigned_matches=unassigned_count,
        assignment_rate=assignment_rate,
    )

    # ========================================================================
    # Fetch teams for all events in this schedule
    # ========================================================================
    from app.models.team import Team

    # Get unique event IDs from matches
    event_ids = list(set(m.event_id for m in matches))

    # Fetch all teams for these events
    teams_query = select(Team).where(Team.event_id.in_(event_ids))
    teams = session.exec(teams_query).all()

    # Build team info list
    team_infos = [TeamInfo(id=team.id, name=team.name, seed=team.seed, event_id=team.event_id) for team in teams]

    # ========================================================================
    # Return grid payload
    # ========================================================================
    return ScheduleGridV1(
        slots=grid_slots,
        assignments=grid_assignments,
        matches=grid_matches,
        teams=team_infos,
        conflicts_summary=conflicts_summary,
    )


# ============================================================================
# Phase Flow V1 - Match Preview, Generate Matches/Slots Only, Assign by Scope
# ============================================================================


class MatchPreviewItem(BaseModel):
    """Single match in preview response"""
    id: int
    event_id: int
    match_code: str
    stage: str  # match_type as stage
    round_number: int
    round_index: int
    sequence_in_round: int
    match_type: str
    consolation_tier: Optional[int] = None  # 1 for Tier 1, 2 for Tier 2, None for non-consolation
    duration_minutes: int
    placeholder_side_a: str
    placeholder_side_b: str
    team_a_id: Optional[int] = None
    team_b_id: Optional[int] = None


class MatchPreviewDiagnostics(BaseModel):
    """Version mismatch detection for preview"""
    requested_version_id: int
    matches_found: int
    grid_reported_matches_for_version: int
    likely_version_mismatch: bool
    event_ids_present: List[int] = []
    event_counts_by_id: Dict[int, int] = {}


class MatchPreviewResponse(BaseModel):
    """Match preview for Schedule Builder review"""
    matches: List[MatchPreviewItem]
    counts_by_event: Dict[str, int]
    counts_by_stage: Dict[str, int]
    event_names_by_id: Dict[str, str]  # event_id (as str key) -> event name
    duplicate_codes: List[str]
    ordering_checksum: str
    diagnostics: MatchPreviewDiagnostics


@router.get(
    "/tournaments/{tournament_id}/schedule/versions/{version_id}/matches/preview",
    response_model=MatchPreviewResponse,
)
def get_matches_preview(
    tournament_id: int,
    version_id: int,
    session: Session = Depends(get_session),
):
    """Read-only match preview with deterministic ordering and duplicate detection."""
    tournament = session.get(Tournament, tournament_id)
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")
    version = session.get(ScheduleVersion, version_id)
    if not version or version.tournament_id != tournament_id:
        raise HTTPException(status_code=404, detail="Schedule version not found")

    matches = session.exec(
        select(Match)
        .where(Match.schedule_version_id == version_id, Match.tournament_id == tournament_id)
        .order_by(
            Match.event_id,
            Match.match_type,
            Match.round_index,
            Match.sequence_in_round,
            Match.match_code,
            Match.id,
        )
    ).all()

    matches_found = len(matches)
    grid_reported_matches_for_version = scalar_int(
        session.exec(
            select(func.count(Match.id)).where(
                Match.schedule_version_id == version_id,
                Match.tournament_id == tournament_id,
            )
        ).one()
    )
    total_matches_any_version = scalar_int(
        session.exec(
            select(func.count(Match.id)).where(Match.tournament_id == tournament_id)
        ).one()
    )
    likely_version_mismatch = total_matches_any_version > 0 and matches_found == 0

    codes = [m.match_code for m in matches]
    seen: Dict[str, int] = {}
    duplicate_codes: List[str] = []
    for c in codes:
        seen[c] = seen.get(c, 0) + 1
    for c, cnt in seen.items():
        if cnt > 1:
            duplicate_codes.extend([c] * (cnt - 1))

    checksum_str = ",".join(codes)
    ordering_checksum = hashlib.sha256(checksum_str.encode()).hexdigest()[:16]

    counts_by_event: Dict[str, int] = {}
    counts_by_stage: Dict[str, int] = {}
    event_counts_by_id: Dict[int, int] = {}
    event_names = {e.id: e.name for e in session.exec(select(Event).where(Event.tournament_id == tournament_id)).all()}
    for m in matches:
        key_e = event_names.get(m.event_id, str(m.event_id))
        counts_by_event[key_e] = counts_by_event.get(key_e, 0) + 1
        counts_by_stage[m.match_type] = counts_by_stage.get(m.match_type, 0) + 1
        event_counts_by_id[m.event_id] = event_counts_by_id.get(m.event_id, 0) + 1

    event_ids_present = sorted(set(m.event_id for m in matches))

    diagnostics = MatchPreviewDiagnostics(
        requested_version_id=version_id,
        matches_found=matches_found,
        grid_reported_matches_for_version=grid_reported_matches_for_version,
        likely_version_mismatch=likely_version_mismatch,
        event_ids_present=event_ids_present,
        event_counts_by_id=event_counts_by_id,
    )

    event_names_by_id = {str(eid): name for eid, name in event_names.items()}

    return MatchPreviewResponse(
        matches=[
            MatchPreviewItem(
                id=m.id,
                event_id=m.event_id,
                match_code=m.match_code,
                stage=m.match_type,
                round_number=m.round_number,
                round_index=m.round_index,
                sequence_in_round=m.sequence_in_round,
                match_type=m.match_type,
                consolation_tier=m.consolation_tier,
                duration_minutes=m.duration_minutes,
                placeholder_side_a=m.placeholder_side_a,
                placeholder_side_b=m.placeholder_side_b,
                team_a_id=m.team_a_id,
                team_b_id=m.team_b_id,
            )
            for m in matches
        ],
        counts_by_event=counts_by_event,
        counts_by_stage=counts_by_stage,
        event_names_by_id=event_names_by_id,
        duplicate_codes=sorted(set(duplicate_codes)),
        ordering_checksum=ordering_checksum,
        diagnostics=diagnostics,
    )


class MatchesGenerateOnlyRequest(BaseModel):
    """Optional body for generate matches only."""
    wipe_existing: bool = False


class EventExpectedItem(BaseModel):
    event_id: int
    event_name: str
    expected: int
    existing_before: int
    generated_added: int
    decision: str = "unknown"
    reason: str = ""


class MatchesGenerateOnlyResponse(BaseModel):
    matches_generated: int
    already_generated: bool
    debug_stamp: str = "matches_generate_only_v1"
    trace_id: str = ""
    seen_event_ids: List[int] = []
    finalized_event_ids: List[int] = []
    events_included: List[str] = []
    events_skipped: List[str] = []
    events_not_finalized: List[str] = []
    finalized_events_found: List[str] = []
    events_expected: List[EventExpectedItem] = []
    already_complete: bool = False


@router.post(
    "/tournaments/{tournament_id}/schedule/versions/{version_id}/matches/generate",
    response_model=MatchesGenerateOnlyResponse,
)
def generate_matches_only(
    tournament_id: int,
    version_id: int,
    session: Session = Depends(get_session),
    body: Optional[MatchesGenerateOnlyRequest] = None,
):
    """Generate matches only (no slots, no assignment). Idempotent unless wipe_existing=True."""
    trace_id = uuid4().hex[:8]
    wipe_existing = body.wipe_existing if body else False
    logger.info(
        "[GEN_MATCHES][%s] tournament=%s version=%s wipe=%s caller=ScheduleBuilder",
        trace_id, tournament_id, version_id, wipe_existing,
    )

    tournament = session.get(Tournament, tournament_id)
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")
    version = session.get(ScheduleVersion, version_id)
    if not version or version.tournament_id != tournament_id:
        raise HTTPException(status_code=404, detail="Schedule version not found")
    require_draft_version(session, version_id, tournament_id)

    if wipe_existing:
        existing_count = scalar_int(
            session.exec(
                select(func.count(Match.id)).where(Match.schedule_version_id == version_id)
            ).one()
        )
        if existing_count > 0:
            wipe_matches_for_version(session, version_id)
            session.flush()

    try:
        session._allow_match_generation = True
        match_request = MatchGenerateRequest(schedule_version_id=version_id, wipe_existing=False)
        result = generate_matches(tournament_id, match_request, session, _transactional=True)
        session.flush()
        session.commit()

        per_event = result.get("per_event", {}) or {}
        events_included = [p["event_name"] for p in per_event.values() if p.get("matches", 0) > 0]
        events_skipped = [p["event_name"] for p in per_event.values() if p.get("matches", 0) == 0]
        if result.get("warnings"):
            for w in result["warnings"]:
                if isinstance(w, dict) and w.get("event_name") and w["event_name"] not in events_skipped:
                    events_skipped.append(w["event_name"])

        events_not_finalized = [
            e.name for e in session.exec(
                select(Event).where(Event.tournament_id == tournament_id, Event.draw_status != "final")
            ).all()
        ]
        finalized_events_found = result.get("finalized_events_found", [])
        events_expected_raw = result.get("events_expected", [])
        events_expected = [EventExpectedItem(**e) for e in events_expected_raw]
        already_complete = result.get("already_complete", False)
        total_added = result.get("total_matches_created", 0)

        return MatchesGenerateOnlyResponse(
            matches_generated=total_added,
            already_generated=already_complete and total_added == 0,
            trace_id=trace_id,
            seen_event_ids=result.get("seen_event_ids", []),
            finalized_event_ids=result.get("finalized_event_ids", []),
            events_included=events_included,
            events_skipped=events_skipped,
            events_not_finalized=events_not_finalized,
            finalized_events_found=finalized_events_found,
            events_expected=events_expected,
            already_complete=already_complete,
        )
    except Exception as e:
        session.rollback()
        raise HTTPException(status_code=500, detail=f"Match generation failed: {e}") from e
    finally:
        session._allow_match_generation = False


class SlotsGenerateOnlyResponse(BaseModel):
    slots_generated: int
    already_generated: bool
    debug_stamp: str = "slots_generate_only_v1"


@router.post(
    "/tournaments/{tournament_id}/schedule/versions/{version_id}/slots/generate",
    response_model=SlotsGenerateOnlyResponse,
)
def generate_slots_only(
    tournament_id: int,
    version_id: int,
    session: Session = Depends(get_session),
):
    """Generate slots only (no matches, no assignment). Idempotent."""
    tournament = session.get(Tournament, tournament_id)
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")
    version = session.get(ScheduleVersion, version_id)
    if not version or version.tournament_id != tournament_id:
        raise HTTPException(status_code=404, detail="Schedule version not found")
    require_draft_version(session, version_id, tournament_id)

    existing_count = scalar_int(
        session.exec(
            select(func.count(ScheduleSlot.id)).where(ScheduleSlot.schedule_version_id == version_id)
        ).one()
    )
    if existing_count > 0:
        return SlotsGenerateOnlyResponse(
            slots_generated=existing_count,
            already_generated=True,
        )

    try:
        slot_request = SlotGenerateRequest(
            source="auto",
            schedule_version_id=version_id,
            wipe_existing=False,
        )
        result = generate_slots(tournament_id, slot_request, session, _transactional=True)
        session.flush()
        session.commit()
        return SlotsGenerateOnlyResponse(
            slots_generated=result.get("slots_created", 0),
            already_generated=False,
        )
    except Exception as e:
        session.rollback()
        raise RuntimeError(f"Slot generation failed: {e}") from e


class AssignScopeRequest(BaseModel):
    scope: str  # WF_R1 | WF_R2 | RR_POOL | BRACKET_MAIN | ALL
    event_id: Optional[int] = None
    clear_existing_assignments_in_scope: bool = False


class AssignScopeResponse(BaseModel):
    assigned_count: int
    unassigned_count_remaining_in_scope: int
    debug_stamp: str = "assign_scope_v1"


@router.post(
    "/tournaments/{tournament_id}/schedule/versions/{version_id}/assign",
    response_model=AssignScopeResponse,
)
def assign_matches_by_scope(
    tournament_id: int,
    version_id: int,
    body: AssignScopeRequest,
    session: Session = Depends(get_session),
):
    """Place matches for one round/scope. Requires slots exist. Only assigns unassigned matches."""
    tournament = session.get(Tournament, tournament_id)
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")
    version = session.get(ScheduleVersion, version_id)
    if not version or version.tournament_id != tournament_id:
        raise HTTPException(status_code=404, detail="Schedule version not found")
    require_draft_version(session, version_id, tournament_id)

    slot_count = scalar_int(
        session.exec(
            select(func.count(ScheduleSlot.id)).where(ScheduleSlot.schedule_version_id == version_id)
        ).one()
    )
    if slot_count == 0:
        raise HTTPException(status_code=400, detail="No slots exist. Generate slots first.")

    try:
        from app.utils.auto_assign import assign_with_scope

        result = assign_with_scope(
            session=session,
            schedule_version_id=version_id,
            scope=body.scope,
            event_id=body.event_id,
            clear_existing_assignments_in_scope=body.clear_existing_assignments_in_scope,
        )
        session.commit()
        return AssignScopeResponse(
            assigned_count=result.assigned_count,
            unassigned_count_remaining_in_scope=result.unassigned_count,
        )
    except Exception as e:
        session.rollback()
        raise RuntimeError(f"Assign failed: {e}") from e


# ============================================================================
# REST Rules V1 - Auto-Assign with Rest Enforcement
# ============================================================================


class AutoAssignRestResponse(BaseModel):
    """Response from rest-aware auto-assign"""

    assigned_count: int
    unassigned_count: int
    unassigned_reasons: dict
    rest_violations_summary: dict


@router.post(
    "/tournaments/{tournament_id}/schedule/versions/{version_id}/auto-assign-rest",
    response_model=AutoAssignRestResponse,
)
def auto_assign_with_rest_rules(
    tournament_id: int,
    version_id: int,
    clear_existing: bool = Query(True, description="Clear existing assignments before running"),
    v: int = Query(1, description="Algorithm version: 1 (default) or 2 (with enhanced constraints)", ge=1, le=2),
    min_rest_minutes: int = Query(90, description="V2 only: Minimum rest minutes between matches for same team", ge=0),
    require_court_type_match: bool = Query(
        False, description="V2 only: Require court type compatibility (if courts have types)"
    ),
    session: Session = Depends(get_session),
):
    """
    Auto-assign matches to slots with rest rules enforcement.

    **Version 1 (default)**: Basic rest rules
    - WF → Scoring matches: Minimum 60 minutes rest
    - Scoring → Scoring matches: Minimum 90 minutes rest
    - Matches with placeholder teams: Rest rules skipped for that side

    **Version 2**: Enhanced constraints
    - Configurable minimum rest time per team (default: 90 minutes)
    - Optional court-type eligibility (e.g., feature court vs standard)
    - Structured conflict reporting (rest violations, court mismatches)
    - Partial assignments with detailed conflict reasons

    Both versions:
    - Fully deterministic: Same input → same output
    - First-fit strategy: No backtracking or optimization
    - Preserve stage ordering (WF → MAIN → CONSOLATION → PLACEMENT)

    Args:
        tournament_id: Tournament ID
        version_id: Schedule version ID
        clear_existing: If true, clears all assignments before running
        v: Algorithm version (1 or 2)
        min_rest_minutes: V2 only - minimum rest between matches for same team
        require_court_type_match: V2 only - enforce court type compatibility

    Returns:
        AutoAssignRestResponse with assignment results and rest violation details
    """
    # Validate tournament
    tournament = session.get(Tournament, tournament_id)
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")

    # Validate schedule version
    version = session.get(ScheduleVersion, version_id)
    if not version or version.tournament_id != tournament_id:
        raise HTTPException(status_code=404, detail="Schedule version not found")

    # CHUNK 2B: Draft-only guard
    require_draft_version(session, version_id, tournament_id)

    # Run auto-assign (version selected by parameter)
    try:
        if v == 2:
            # Import V2 lazily to avoid circular dependencies
            from app.utils.auto_assign_v2 import auto_assign_v2

            result = auto_assign_v2(
                session=session,
                schedule_version_id=version_id,
                clear_existing=clear_existing,
                min_rest_minutes=min_rest_minutes,
                require_court_type_match=require_court_type_match,
            )
            
            # Commit the assignments
            session.commit()

            # Convert V2 result to response format
            return AutoAssignRestResponse(
                assigned_count=result.assigned_count,
                unassigned_count=result.unassigned_count,
                unassigned_reasons={
                    "conflicts": result.conflicts,
                    "conflict_summary": {
                        "rest_violations": result.rest_violations,
                        "court_type_mismatches": result.court_type_mismatches,
                        "slot_occupied": result.slot_occupied_count,
                    },
                },
                rest_violations_summary={
                    "total_rest_violations": result.rest_violations,
                    "min_rest_minutes": min_rest_minutes,
                },
            )
        else:
            # V1 (default)
            result = auto_assign_with_rest(
                session=session, schedule_version_id=version_id, clear_existing=clear_existing
            )
            return AutoAssignRestResponse(**result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Auto-assign failed: {str(e)}")


# ============================================================================
# P1: One-Click Build Full Schedule Endpoint
# ============================================================================


class BuildFullScheduleResponse(BaseModel):
    """Response for one-click schedule build"""

    model_config = ConfigDict(from_attributes=True)

    status: str
    tournament_id: int
    schedule_version_id: int
    clear_existing: bool
    dry_run: bool
    summary: Dict[str, Any]
    warnings: List[Dict[str, Any]]
    failed_step: Optional[str] = None
    error_message: Optional[str] = None
    grid: Optional[Dict[str, Any]] = None
    conflicts: Optional[Dict[str, Any]] = None
    wf_conflict_lens: Optional[List[Dict[str, Any]]] = None


@router.post(
    "/tournaments/{tournament_id}/schedule/versions/{version_id}/build", response_model=BuildFullScheduleResponse
)
def build_full_schedule(
    tournament_id: int,
    version_id: int,
    clear_existing: bool = Query(True, description="Clear existing assignments before building"),
    dry_run: bool = Query(False, description="Run without committing assignments (preview mode)"),
    inject_teams: bool = Query(False, description="Run team injection step (default: false)"),
    session: Session = Depends(get_session),
):
    """
    One-Click Build Full Schedule V1

    Orchestrates the complete schedule building pipeline:
    1. Validate (tournament, version exists, is draft)
    2. Clear existing (if clear_existing=true)
    3. Generate slots (assumes already generated)
    4. Generate matches (assumes already generated)
    5. Assign WF groups (if avoid edges exist)
    6. Inject teams (if inject_teams=true AND teams exist)
    7. Auto-assign (rest-aware + day targeting)
    8. Return composite response (grid + conflicts + WF lens)

    **Draft-Only Guard**: Only works on draft schedule versions.

    **Idempotent**: Running twice with same inputs produces identical results.

    **Deterministic**: Same input → same output.

    Args:
        tournament_id: Tournament ID
        version_id: Schedule version ID
        clear_existing: Clear existing assignments before building (default: true)
        dry_run: Preview mode - run without committing assignments (default: false)
        inject_teams: Run team injection step (default: false)

    Returns:
        BuildFullScheduleResponse with:
        - summary: Counts and statistics
        - warnings: Non-fatal issues (e.g., no teams for event)
        - grid: Schedule grid payload (if successful)
        - conflicts: Conflict report (if successful)
        - wf_conflict_lens: WF conflict analysis per event (if successful)

    Raises:
        400: If schedule version is not draft
        404: If tournament or version not found
        500: If pipeline step fails
    """
    # Validate tournament
    tournament = session.get(Tournament, tournament_id)
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")

    require_draft_version(session, version_id, tournament_id)

    # Convenience wrapper: phased flow (slots → matches → assign scope=ALL)
    # Does NOT use orchestrator all-in-one; calls phased endpoints' logic inline
    try:
        # 1. Generate slots (idempotent)
        slot_count = scalar_int(
            session.exec(select(func.count(ScheduleSlot.id)).where(ScheduleSlot.schedule_version_id == version_id)).one()
        )
        if slot_count == 0:
            slot_request = SlotGenerateRequest(source="auto", schedule_version_id=version_id, wipe_existing=False)
            slot_result = generate_slots(tournament_id, slot_request, session, _transactional=True)
            slots_generated = slot_result.get("slots_created", 0)
        else:
            slots_generated = slot_count

        # 2. Generate matches (idempotent)
        match_count = scalar_int(
            session.exec(select(func.count(Match.id)).where(Match.schedule_version_id == version_id)).one()
        )
        if match_count == 0:
            session._allow_match_generation = True
            try:
                match_request = MatchGenerateRequest(schedule_version_id=version_id, wipe_existing=False)
                match_result = generate_matches(tournament_id, match_request, session, _transactional=True)
                matches_generated = match_result.get("total_matches_created", 0)
            finally:
                session._allow_match_generation = False
        else:
            matches_generated = match_count

        # 2b. WF Grouping (conditional: events with WF + avoid edges)
        from app.utils.wf_grouping import assign_wf_groups_v1

        events = session.exec(select(Event).where(Event.tournament_id == tournament_id)).all()
        for event in events:
            if event.draw_plan_json:
                draw_plan = json.loads(event.draw_plan_json)
                if draw_plan.get("wf_rounds", 0) > 0:
                    avoid_count = len(
                        session.exec(
                            select(TeamAvoidEdge).where(TeamAvoidEdge.event_id == event.id)
                        ).all()
                    )
                    if avoid_count > 0:
                        assign_wf_groups_v1(session, event.id, clear_existing=True, _transactional=True)
        session.flush()

        # 3. Assign scope=ALL
        from app.utils.auto_assign import assign_with_scope

        assign_result = assign_with_scope(
            session=session,
            schedule_version_id=version_id,
            scope="ALL",
            clear_existing_assignments_in_scope=clear_existing,
        )
        assignments_created = assign_result.assigned_count
        unassigned_matches = assign_result.unassigned_count

        session.commit()

        response_data = {
            "status": "success",
            "tournament_id": tournament_id,
            "schedule_version_id": version_id,
            "clear_existing": clear_existing,
            "dry_run": dry_run,
            "summary": {
                "slots_generated": slots_generated,
                "matches_generated": matches_generated,
                "assignments_created": assignments_created,
                "unassigned_matches": unassigned_matches,
                "debug_build_stamp": "build_phased_wrapper_v1",
            },
            "warnings": [],
        }
    except Exception as e:
        session.rollback()
        logger.exception("Build (phased wrapper) failed")
        raise HTTPException(status_code=500, detail=str(e))

    # Add grid payload
    try:
        grid_response = get_schedule_grid(tournament_id=tournament_id, schedule_version_id=version_id, session=session)
        response_data["grid"] = grid_response.model_dump()
    except Exception as e:
        response_data["warnings"].append(
            {"code": "GRID_GENERATION_FAILED", "message": f"Failed to generate grid: {str(e)}", "event_id": None}
        )

    # Add conflicts payload (if grid was successful)
    if "grid" in response_data and response_data["grid"]:
        response_data["conflicts"] = response_data["grid"].get("conflicts", {})

    # Add WF conflict lens for each event
    try:
        from app.routes.wf_conflicts import get_wf_conflict_lens

        events = session.exec(select(Event).where(Event.tournament_id == tournament_id)).all()

        wf_lenses = []
        for event in events:
            try:
                lens = get_wf_conflict_lens(event_id=event.id, session=session)
                wf_lenses.append(lens.model_dump())
            except Exception:
                pass  # Skip events without WF or errors

        response_data["wf_conflict_lens"] = wf_lenses
    except Exception as e:
        response_data["warnings"].append(
            {
                "code": "WF_LENS_GENERATION_FAILED",
                "message": f"Failed to generate WF conflict lens: {str(e)}",
                "event_id": None,
            }
        )

    return BuildFullScheduleResponse(**response_data)
