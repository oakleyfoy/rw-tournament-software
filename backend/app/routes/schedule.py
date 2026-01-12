import hashlib
import json
from datetime import date, datetime, time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, model_validator
from sqlmodel import Session, func, select

from app.database import get_session
from app.models.event import Event
from app.models.match import Match
from app.models.match_assignment import MatchAssignment
from app.models.schedule_slot import ScheduleSlot
from app.models.schedule_version import ScheduleVersion
from app.models.tournament import Tournament
from app.models.tournament_day import TournamentDay
from app.models.tournament_time_window import TournamentTimeWindow
from app.services.schedule_orchestrator import build_schedule_v1
from app.utils.rest_rules import auto_assign_with_rest
from app.utils.version_guards import require_draft_version, require_final_version

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
        new_slot = ScheduleSlot(
            tournament_id=slot.tournament_id,
            schedule_version_id=new_version.id,
            day_date=slot.day_date,
            start_time=slot.start_time,
            end_time=slot.end_time,
            court_number=slot.court_number,
            court_label=slot.court_label,
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
    source_assignments = session.exec(
        select(MatchAssignment).where(MatchAssignment.schedule_version_id == version_id)
    ).all()

    for assignment in source_assignments:
        new_assignment = MatchAssignment(
            schedule_version_id=new_version.id,
            slot_id=slot_id_map[assignment.slot_id],
            match_id=match_id_map[assignment.match_id],
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
    tournament_id: int, request: Optional[SlotGenerateRequest] = None, session: Session = Depends(get_session)
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

    # Get tournament to access court_names
    tournament = session.get(Tournament, tournament_id)
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")

    # Derive effective court labels
    # Rules: If tournament.court_names exists and has length > 0, use that list in exact order
    # Else: generate default labels: ["1","2","3",...,"N"]
    def get_court_labels(max_courts: int) -> tuple[list[str], list[str]]:
        """
        Returns: (labels, warnings)
        """
        warnings = []

        if tournament.court_names and len(tournament.court_names) > 0:
            labels = list(tournament.court_names)

            # Check for duplicates
            seen = set()
            duplicates = []
            for label in labels:
                if label in seen:
                    duplicates.append(label)
                seen.add(label)

            if duplicates:
                warnings.append(f"Court labels must be unique. Duplicate label found: '{duplicates[0]}'.")

            # Check count mismatch
            if len(labels) != max_courts:
                warnings.append(
                    f"Court labels count ({len(labels)}) does not match court count ({max_courts}). "
                    f"Missing labels will be auto-filled."
                )

            # Extend if needed
            while len(labels) < max_courts:
                labels.append(str(len(labels) + 1))

            return labels[:max_courts], warnings  # Trim if too many
        else:
            # Generate defaults
            return [str(i) for i in range(1, max_courts + 1)], warnings

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
            # Calculate start and end minutes
            start_minutes = window.start_time.hour * 60 + window.start_time.minute
            end_minutes = window.end_time.hour * 60 + window.end_time.minute

            if end_minutes <= start_minutes:
                continue  # Skip invalid time ranges

            print(
                f"[DEBUG] Processing window: {window.day_date} {window.start_time}-{window.end_time}, courts={window.courts_available}"
            )

            # Get court labels for this window
            court_labels = get_court_labels(window.courts_available)

            # Generate 15-minute start-time slots for each court
            # Slots are start opportunities, not fixed blocks
            # Assignment determines actual occupation duration based on match.duration_minutes
            for court_num in range(1, window.courts_available + 1):
                court_label = court_labels[court_num - 1]  # 0-based index
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

                    # Don't exceed the window's end time
                    # If this would exceed, make it a shorter slot (but still create it)
                    if slot_end_minutes > end_minutes:
                        slot_end_time = window.end_time
                        # Calculate actual duration for this last slot
                        actual_duration = end_minutes - current_minutes
                    else:
                        actual_duration = 15

                    slot = ScheduleSlot(
                        tournament_id=tournament_id,
                        schedule_version_id=version.id,
                        day_date=window.day_date,
                        start_time=slot_start_time,
                        end_time=slot_end_time,
                        court_number=court_num,
                        court_label=court_label,  # Immutable label for this version
                        block_minutes=actual_duration,  # 15 for most, less for last slot if needed
                        label=window.label,  # Preserve window label if any
                        is_active=True,
                    )
                    session.add(slot)
                    slots_created += 1
                    court_slots += 1
                    current_minutes += 15  # 15-minute tick interval

                    # If we've reached the end, break
                    if slot_end_minutes >= end_minutes:
                        break
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

            # Get court labels for this day
            court_labels, label_warnings = get_court_labels(day.courts_available)
            if label_warnings:
                for warning in label_warnings:
                    print(f"[WARNING] {warning}")

            # Generate 15-minute start-time slots for each court
            # Slots are start opportunities, not fixed blocks
            # Assignment determines actual occupation duration based on match.duration_minutes
            for court_num in range(1, day.courts_available + 1):
                court_label = court_labels[court_num - 1]  # 0-based index
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

                    slot = ScheduleSlot(
                        tournament_id=tournament_id,
                        schedule_version_id=version.id,
                        day_date=day.date,
                        start_time=slot_start_time,
                        end_time=slot_end_time,
                        court_number=court_num,
                        court_label=court_label,  # Immutable label for this version
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
    tournament_id: int, request: Optional[MatchGenerateRequest] = None, session: Session = Depends(get_session)
):
    """Generate placeholder matches from finalized events

    If request body is empty or schedule_version_id is None, uses the active draft version.
    Returns 422 for validation errors, 409 for ambiguous draft selection, 404/400 for other errors.
    All responses include CORS headers via CORSMiddleware.
    """
    # Validate tournament exists
    tournament = session.get(Tournament, tournament_id)
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")

    # Handle empty request body - FastAPI will validate the model if provided
    if request is None:
        request = MatchGenerateRequest()

    # Get or create draft version (handles ambiguity)
    version = get_or_create_draft_version(session, tournament_id, request.schedule_version_id)

    # Get events to process
    if request.event_id:
        event = session.get(Event, request.event_id)
        if not event or event.tournament_id != tournament_id:
            raise HTTPException(status_code=404, detail="Event not found")
        if event.draw_status != "final":
            raise HTTPException(status_code=400, detail="Event must be finalized to generate matches")
        events = [event]
    else:
        # Get all finalized events
        events = session.exec(
            select(Event).where(Event.tournament_id == tournament_id, Event.draw_status == "final")
        ).all()

    if not events:
        raise HTTPException(status_code=400, detail="No finalized events found")

    total_matches = 0
    per_event_breakdown = {}

    for event in events:
        # Wipe existing matches for this event if requested (uses helper for correct order)
        if request.wipe_existing:
            wipe_matches_for_version(session, version.id, event_id=event.id)

        # Parse draw plan to get template info
        draw_plan = None
        if event.draw_plan_json:
            try:
                draw_plan = json.loads(event.draw_plan_json)
            except (json.JSONDecodeError, TypeError, AttributeError):
                pass

        template_type = draw_plan.get("template_type", "RR_ONLY") if draw_plan else "RR_ONLY"
        wf_rounds = draw_plan.get("wf_rounds", 0) if draw_plan else 0

        # Get match counts using same logic as frontend
        from app.utils.match_generation import (
            calculate_match_counts,
            generate_consolation_matches,
            generate_placement_matches,
            generate_standard_matches,
            generate_wf_matches,
        )

        match_counts = calculate_match_counts(template_type, event.team_count, wf_rounds, event.guarantee_selected or 5)

        # Generate event prefix for match codes
        event_prefix = f"{event.category.upper()[:3]}_{event.name.upper()[:3]}"
        if len(event_prefix) < 6:
            event_prefix = f"{event.category.upper()}_{event.id}"

        matches_for_event = 0

        # Generate WF matches (with grouping support)
        if match_counts["wf_matches"] > 0:
            wf_matches = generate_wf_matches(
                event,
                version.id,
                tournament_id,
                match_counts["wf_rounds"],
                event.wf_block_minutes or 60,
                event_prefix,
                session=session,  # Pass session for WF grouping support
            )
            for match in wf_matches:
                session.add(match)
                matches_for_event += 1

        # Generate standard matches (MAIN)
        standard_matches = generate_standard_matches(
            event,
            version.id,
            tournament_id,
            match_counts["standard_matches"],
            event.standard_block_minutes or 120,
            event_prefix,
            template_type,
        )
        for match in standard_matches:
            session.add(match)
            matches_for_event += 1

        # Generate consolation and placement matches for bracket templates only
        # Round Robin templates never generate consolation or placement
        if template_type == "CANONICAL_32":
            # CANONICAL_32 is now an 8-team bracket event
            guarantee = event.guarantee_selected or 5

            # Generate consolation matches (Tier 1 always, Tier 2 if guarantee==5)
            consolation_matches = generate_consolation_matches(
                event, version.id, tournament_id, event.standard_block_minutes or 120, event_prefix, guarantee
            )
            for match in consolation_matches:
                session.add(match)
                matches_for_event += 1

            # Generate placement matches (only if guarantee==5)
            if guarantee == 5:
                placement_matches = generate_placement_matches(
                    event, version.id, tournament_id, event.standard_block_minutes or 120, event_prefix
                )
                for match in placement_matches:
                    session.add(match)
                    matches_for_event += 1
        # Note: RR_ONLY and WF_TO_POOLS_4 do NOT generate consolation or placement

        total_matches += matches_for_event
        per_event_breakdown[event.id] = {"event_name": event.name, "matches": matches_for_event}

    session.commit()

    return {"schedule_version_id": version.id, "total_matches_created": total_matches, "per_event": per_event_breakdown}


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
    """
    from app.utils.auto_assign import STAGE_PRECEDENCE, get_match_sort_key, get_slot_sort_key

    # Validate tournament
    tournament = session.get(Tournament, tournament_id)
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")

    # Validate schedule version
    version = session.get(ScheduleVersion, schedule_version_id)
    if not version or version.tournament_id != tournament_id:
        raise HTTPException(status_code=404, detail="Schedule version not found")

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
    # Build final report
    # ========================================================================
    return ConflictReportV1(
        summary=summary,
        unassigned=unassigned_details,
        slot_pressure=slot_pressure,
        stage_timeline=stage_timeline_list,
        ordering_integrity=ordering_integrity,
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
        grid_assignments.append(GridAssignment(slot_id=assignment.slot_id, match_id=assignment.match_id))

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
    6. Inject teams (if teams exist)
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

    # CHUNK 2B: Draft-only guard
    require_draft_version(session, version_id, tournament_id)

    # Run orchestrator
    result = build_schedule_v1(
        session=session,
        tournament_id=tournament_id,
        version_id=version_id,
        clear_existing=clear_existing,
        dry_run=dry_run,
    )

    # If failed, return error response
    if result.status == "error":
        if "SCHEDULE_VERSION_NOT_DRAFT" in (result.error_message or ""):
            raise HTTPException(status_code=400, detail=result.error_message)
        else:
            raise HTTPException(status_code=500, detail=result.error_message)

    # Build composite response
    response_data = result.to_dict()

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
