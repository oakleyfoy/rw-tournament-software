from typing import List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from app.database import get_session
from app.models.event import Event
from app.models.tournament import Tournament
from app.models.tournament_day import TournamentDay

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
    """Get Phase 1 readiness status for a tournament"""
    tournament = session.get(Tournament, tournament_id)
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")

    errors = []

    # Get all active days
    active_days = session.exec(
        select(TournamentDay)
        .where(TournamentDay.tournament_id == tournament_id, TournamentDay.is_active)
        .order_by(TournamentDay.date)
    ).all()

    # Get all events
    events = session.exec(select(Event).where(Event.tournament_id == tournament_id)).all()

    # Calculate total court minutes
    total_court_minutes = 0
    for day in active_days:
        if not day.start_time or not day.end_time:
            errors.append(f"Start time or end time not set on active day {day.date}")
            continue

        if day.courts_available < 1:
            errors.append(f"Courts not set on active day {day.date}")
            continue

        # Calculate minutes between start and end time
        start_datetime = day.start_time
        end_datetime = day.end_time

        # Convert time to minutes since midnight
        start_minutes = start_datetime.hour * 60 + start_datetime.minute
        end_minutes = end_datetime.hour * 60 + end_datetime.minute

        if end_minutes <= start_minutes:
            errors.append(f"End time must be greater than start time on active day {day.date}")
            continue

        day_minutes = end_minutes - start_minutes
        total_court_minutes += day_minutes * day.courts_available

    # Check requirements
    if len(active_days) == 0:
        errors.append("At least one active day is required")

    if total_court_minutes == 0:
        errors.append("Total court minutes must be greater than 0")

    if len(events) == 0:
        errors.append("At least one event is required")

    is_ready = len(errors) == 0

    summary = Phase1Summary(
        active_days=len(active_days), total_court_minutes=total_court_minutes, events_count=len(events)
    )

    return Phase1StatusResponse(is_ready=is_ready, errors=errors, summary=summary)
