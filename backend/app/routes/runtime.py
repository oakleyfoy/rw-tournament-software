"""
Phase 4 Runtime: Match status + scoring. No schedule mutation.
Allowed on draft and final schedule versions; assignments/slots remain immutable.
When a match is finalized, advancement service fills downstream team slots (WF/MAIN).
"""
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from app.database import get_session
from app.models.match import Match
from app.models.tournament import Tournament
from app.services.advancement_service import apply_advancement_for_final_match

router = APIRouter()

# Allowed runtime status transitions
RUNTIME_SCHEDULED = "SCHEDULED"
RUNTIME_IN_PROGRESS = "IN_PROGRESS"
RUNTIME_FINAL = "FINAL"


class MatchRuntimeUpdate(BaseModel):
    status: Optional[str] = None
    score: Optional[Dict[str, Any]] = None
    winner_team_id: Optional[int] = None


class MatchRuntimeState(BaseModel):
    id: int
    tournament_id: int
    schedule_version_id: int
    event_id: int
    match_code: str
    match_type: str
    round_index: int
    sequence_in_round: int
    runtime_status: str
    score_json: Optional[Dict[str, Any]] = None
    winner_team_id: Optional[int] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class MatchRuntimeUpdateResponse(BaseModel):
    match: MatchRuntimeState
    advanced_count: int = 0


def _match_to_runtime_state(m: Match) -> MatchRuntimeState:
    return MatchRuntimeState(
        id=m.id,
        tournament_id=m.tournament_id,
        schedule_version_id=m.schedule_version_id,
        event_id=m.event_id,
        match_code=m.match_code,
        match_type=m.match_type,
        round_index=m.round_index,
        sequence_in_round=m.sequence_in_round,
        runtime_status=m.runtime_status,
        score_json=m.score_json,
        winner_team_id=m.winner_team_id,
        started_at=m.started_at,
        completed_at=m.completed_at,
    )


def _validate_status_transition(current: str, new: str) -> None:
    if new not in (RUNTIME_SCHEDULED, RUNTIME_IN_PROGRESS, RUNTIME_FINAL):
        raise HTTPException(status_code=422, detail=f"Invalid runtime_status: {new}")
    if current == RUNTIME_FINAL:
        raise HTTPException(status_code=422, detail="FINAL is terminal; cannot revert")
    if new == RUNTIME_SCHEDULED and current != RUNTIME_SCHEDULED:
        raise HTTPException(status_code=422, detail="Cannot revert to SCHEDULED")
    if current == RUNTIME_SCHEDULED and new == RUNTIME_FINAL:
        # Allowed only if score/winner provided (validated in handler)
        pass
    if current == RUNTIME_SCHEDULED and new == RUNTIME_IN_PROGRESS:
        pass
    if current == RUNTIME_IN_PROGRESS and new == RUNTIME_FINAL:
        pass


@router.patch(
    "/tournaments/{tournament_id}/runtime/matches/{match_id}",
    response_model=MatchRuntimeUpdateResponse,
)
def update_match_runtime(
    tournament_id: int,
    match_id: int,
    payload: MatchRuntimeUpdate,
    session: Session = Depends(get_session),
) -> MatchRuntimeUpdateResponse:
    """Update match runtime status/score/winner. Match must belong to tournament.
    When status becomes FINAL, advancement fills downstream match team slots (WF/MAIN)."""
    tournament = session.get(Tournament, tournament_id)
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")

    match = session.get(Match, match_id)
    if not match or match.tournament_id != tournament_id:
        raise HTTPException(status_code=404, detail="Match not found")

    current = match.runtime_status or RUNTIME_SCHEDULED

    if payload.status is not None:
        _validate_status_transition(current, payload.status)
        if payload.status == RUNTIME_FINAL:
            if payload.winner_team_id is None and not match.winner_team_id:
                raise HTTPException(
                    status_code=422,
                    detail="winner_team_id required when setting status to FINAL",
                )
            match.runtime_status = RUNTIME_FINAL
            match.completed_at = datetime.utcnow()
            if payload.winner_team_id is not None:
                match.winner_team_id = payload.winner_team_id
        elif payload.status == RUNTIME_IN_PROGRESS:
            match.runtime_status = RUNTIME_IN_PROGRESS
            if match.started_at is None:
                match.started_at = datetime.utcnow()
        else:
            match.runtime_status = payload.status

    if payload.score is not None:
        match.score_json = payload.score

    if payload.winner_team_id is not None:
        match.winner_team_id = payload.winner_team_id

    session.add(match)
    session.commit()
    session.refresh(match)

    advanced_count = 0
    if (match.runtime_status or "") == RUNTIME_FINAL and match.winner_team_id is not None:
        advanced_count = apply_advancement_for_final_match(session, match_id)

    return MatchRuntimeUpdateResponse(
        match=_match_to_runtime_state(match),
        advanced_count=advanced_count,
    )


@router.post(
    "/tournaments/{tournament_id}/runtime/matches/{match_id}/advance",
    response_model=Dict[str, int],
)
def advance_match(
    tournament_id: int,
    match_id: int,
    session: Session = Depends(get_session),
) -> Dict[str, int]:
    """Manually run advancement for a finalized match (repair/testing). Requires match is FINAL with winner."""
    tournament = session.get(Tournament, tournament_id)
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")

    match = session.get(Match, match_id)
    if not match or match.tournament_id != tournament_id:
        raise HTTPException(status_code=404, detail="Match not found")

    if (match.runtime_status or "") != RUNTIME_FINAL:
        raise HTTPException(status_code=422, detail="Match must be FINAL to run advancement")
    if match.winner_team_id is None:
        raise HTTPException(status_code=422, detail="Match must have winner_team_id to run advancement")

    advanced_count = apply_advancement_for_final_match(session, match_id)
    return {"advanced_count": advanced_count}


@router.get(
    "/tournaments/{tournament_id}/runtime/versions/{schedule_version_id}/matches",
    response_model=List[MatchRuntimeState],
)
def get_version_runtime_matches(
    tournament_id: int,
    schedule_version_id: int,
    session: Session = Depends(get_session),
) -> List[MatchRuntimeState]:
    """List match runtime states for a schedule version. Stable order: match_type, round_index, sequence_in_round."""
    tournament = session.get(Tournament, tournament_id)
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")

    matches = session.exec(
        select(Match)
        .where(
            Match.tournament_id == tournament_id,
            Match.schedule_version_id == schedule_version_id,
        )
        .order_by(Match.match_type, Match.round_index, Match.sequence_in_round)
    ).all()

    return [_match_to_runtime_state(m) for m in matches]


# ============================================================================
# Bulk Dependency Resolution
# ============================================================================

class ResolveDependenciesResponse(BaseModel):
    """Response for bulk dependency resolution"""
    matches_processed: int
    teams_advanced: int
    unknown_before: int
    unknown_after: int


@router.post(
    "/tournaments/{tournament_id}/runtime/versions/{schedule_version_id}/resolve-dependencies",
    response_model=ResolveDependenciesResponse,
)
def resolve_dependencies(
    tournament_id: int,
    schedule_version_id: int,
    session: Session = Depends(get_session),
) -> ResolveDependenciesResponse:
    """
    Bulk resolve dependencies for all finalized matches in a schedule version.
    
    Iterates through all FINAL matches with winner_team_id and applies advancement
    to populate downstream match team slots. This is useful after:
    - Batch importing match results
    - Recovering from interrupted advancement
    - Verifying advancement state
    
    Guarantees:
    - Idempotent (safe to call multiple times)
    - Deterministic ordering (processes by match_id)
    - No slot/assignment mutations
    
    Returns:
        - matches_processed: number of finalized matches processed
        - teams_advanced: total downstream team slots filled
        - unknown_before: count of matches with null teams before
        - unknown_after: count of matches with null teams after
    """
    from app.services.advancement_service import resolve_all_dependencies
    
    tournament = session.get(Tournament, tournament_id)
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")
    
    from app.models.schedule_version import ScheduleVersion
    version = session.get(ScheduleVersion, schedule_version_id)
    if not version or version.tournament_id != tournament_id:
        raise HTTPException(status_code=404, detail="Schedule version not found")
    
    result = resolve_all_dependencies(session, schedule_version_id)
    return ResolveDependenciesResponse(**result)


class SimulateAdvancementResponse(BaseModel):
    """Response for simulate advancement (dev-only)"""
    matches_simulated: int
    teams_advanced: int
    unknown_before: int
    unknown_after: int


@router.post(
    "/tournaments/{tournament_id}/runtime/versions/{schedule_version_id}/simulate-advancement",
    response_model=SimulateAdvancementResponse,
)
def simulate_advancement(
    tournament_id: int,
    schedule_version_id: int,
    session: Session = Depends(get_session),
) -> SimulateAdvancementResponse:
    """
    DEV-ONLY: Simulate advancement by assuming higher seed (lower team_id) wins.
    
    For each WF/dependency-source match that has both teams assigned but no winner:
    - Set winner_team_id = min(team_a_id, team_b_id)
    - Set runtime_status = "FINAL"
    - Run advancement to fill downstream slots
    
    This is for testing the advancement pipeline without manual match result entry.
    
    WARNING: This will modify match results! Use only in development/testing.
    
    Returns:
        - matches_simulated: number of matches auto-finalized
        - teams_advanced: total downstream slots filled
        - unknown_before: count of unknown-team matches before
        - unknown_after: count of unknown-team matches after
    """
    from app.services.advancement_service import simulate_advancement_higher_seed_wins
    
    tournament = session.get(Tournament, tournament_id)
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")
    
    from app.models.schedule_version import ScheduleVersion
    version = session.get(ScheduleVersion, schedule_version_id)
    if not version or version.tournament_id != tournament_id:
        raise HTTPException(status_code=404, detail="Schedule version not found")
    
    result = simulate_advancement_higher_seed_wins(session, schedule_version_id)
    return SimulateAdvancementResponse(**result)
