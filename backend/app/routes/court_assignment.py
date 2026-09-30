"""Staff configuration for per-event, per-date court assignment mode."""

from datetime import date, timedelta
from typing import Dict, List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from app.database import get_session
from app.models.event import Event
from app.models.tournament import Tournament
from app.models.tournament_day import TournamentDay
from app.services.court_assignment_mode import (
    ALLOWED_COURT_ASSIGNMENT_MODES,
    replace_court_assignment_modes,
    resolve_court_assignment_mode,
)

router = APIRouter()


class CourtAssignmentDay(BaseModel):
    date: str
    label: str


class CourtAssignmentEventModes(BaseModel):
    event_id: int
    event_name: str
    modes: Dict[str, str]


class CourtAssignmentModesResponse(BaseModel):
    tournament_id: int
    days: List[CourtAssignmentDay]
    events: List[CourtAssignmentEventModes]


class CourtAssignmentEventUpdate(BaseModel):
    event_id: int
    modes: Dict[str, str] = Field(default_factory=dict)


class CourtAssignmentModesUpdate(BaseModel):
    events: List[CourtAssignmentEventUpdate]


def _day_label(day: date) -> str:
    weekday = day.strftime("%A")
    month_day = day.strftime("%B %d").replace(" 0", " ")
    return f"{weekday}, {month_day}"


def _tournament_dates(session: Session, tournament: Tournament) -> List[date]:
    rows = session.exec(
        select(TournamentDay)
        .where(TournamentDay.tournament_id == tournament.id, TournamentDay.is_active == True)  # noqa: E712
        .order_by(TournamentDay.date)
    ).all()
    if rows:
        return [row.date for row in rows]
    if tournament.start_date and tournament.end_date and tournament.end_date >= tournament.start_date:
        span = (tournament.end_date - tournament.start_date).days
        return [tournament.start_date + timedelta(days=offset) for offset in range(span + 1)]
    return []


@router.get(
    "/tournaments/{tournament_id}/court-assignment-modes",
    response_model=CourtAssignmentModesResponse,
)
def get_court_assignment_modes(
    tournament_id: int,
    session: Session = Depends(get_session),
):
    tournament = session.get(Tournament, tournament_id)
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")
    days = _tournament_dates(session, tournament)
    events = session.exec(
        select(Event).where(Event.tournament_id == tournament_id).order_by(Event.name, Event.id)
    ).all()
    return CourtAssignmentModesResponse(
        tournament_id=tournament_id,
        days=[CourtAssignmentDay(date=day.isoformat(), label=_day_label(day)) for day in days],
        events=[
            CourtAssignmentEventModes(
                event_id=event.id,
                event_name=event.name,
                modes={day.isoformat(): resolve_court_assignment_mode(event, day) for day in days},
            )
            for event in events
            if event.id is not None
        ],
    )


@router.put(
    "/tournaments/{tournament_id}/court-assignment-modes",
    response_model=CourtAssignmentModesResponse,
)
def put_court_assignment_modes(
    tournament_id: int,
    payload: CourtAssignmentModesUpdate,
    session: Session = Depends(get_session),
):
    tournament = session.get(Tournament, tournament_id)
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")
    allowed_days = set(_tournament_dates(session, tournament))
    for update in payload.events:
        event = session.get(Event, update.event_id)
        if not event or event.tournament_id != tournament_id:
            raise HTTPException(status_code=404, detail=f"Event {update.event_id} not found")
        for raw_day, mode in update.modes.items():
            normalized = str(mode or "").strip().upper()
            if normalized not in ALLOWED_COURT_ASSIGNMENT_MODES:
                raise HTTPException(status_code=400, detail=f"Invalid court assignment mode: {mode}")
            try:
                day = date.fromisoformat(raw_day[:10])
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=f"Invalid date: {raw_day}") from exc
            if allowed_days and day not in allowed_days:
                raise HTTPException(status_code=400, detail=f"{day.isoformat()} is not an active tournament day")
        try:
            replace_court_assignment_modes(event, update.modes)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        session.add(event)
    session.commit()
    return get_court_assignment_modes(tournament_id, session)
