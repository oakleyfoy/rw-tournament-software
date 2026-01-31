"""
Phase 4 Runtime: Match status + scoring. No schedule mutation.
Allowed on draft and final schedule versions; assignments/slots remain immutable.
"""
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from app.database import get_session
from app.models.match import Match
from app.models.tournament import Tournament

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
    response_model=MatchRuntimeState,
)
def update_match_runtime(
    tournament_id: int,
    match_id: int,
    payload: MatchRuntimeUpdate,
    session: Session = Depends(get_session),
) -> MatchRuntimeState:
    """Update match runtime status/score/winner. Match must belong to tournament."""
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
    return _match_to_runtime_state(match)


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
