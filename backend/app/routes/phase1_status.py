from typing import List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from app.database import get_session
from app.models.event import Event
from app.models.tournament import Tournament
from app.services.capacity_resolver import resolve_tournament_capacity

router = APIRouter()


class Phase1Summary(BaseModel):
    active_days: int
    total_court_minutes: int
    events_count: int


class Phase1StatusResponse(BaseModel):
    is_ready: bool
    errors: List[str]
    summary: Phase1Summary


@router.get("/tournaments/{tournament_id}/phase1-status", response_model=Phase1StatusResponse)
def get_phase1_status(tournament_id: int, session: Session = Depends(get_session)):
    """
    Phase 1 readiness status. Capacity is a pure read from the single capacity resolver.
    No inline math; no reference to Days & Courts when mode is Advanced.
    """
    tournament = session.get(Tournament, tournament_id)
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")

    capacity = resolve_tournament_capacity(session, tournament_id)
    errors = list(capacity.errors)

    events = session.exec(select(Event).where(Event.tournament_id == tournament_id)).all()
    if len(events) == 0:
        errors.append("At least one event is required")

    is_ready = len(errors) == 0
    summary = Phase1Summary(
        active_days=capacity.active_days_count,
        total_court_minutes=capacity.total_court_minutes,
        events_count=len(events),
    )
    return Phase1StatusResponse(is_ready=is_ready, errors=errors, summary=summary)
