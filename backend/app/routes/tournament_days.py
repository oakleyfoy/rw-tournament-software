from datetime import date, time
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, model_validator
from sqlmodel import Session, select

from app.database import get_session
from app.models.tournament import Tournament
from app.models.tournament_day import TournamentDay

router = APIRouter()


class DayUpdate(BaseModel):
    date: date
    is_active: bool
    start_time: Optional[time] = None
    end_time: Optional[time] = None
    courts_available: int

    @model_validator(mode="after")
    def validate_day(self):
        if self.is_active:
            if not self.start_time or not self.end_time:
                raise ValueError("start_time and end_time are required when is_active is true")
            if self.end_time <= self.start_time:
                raise ValueError("end_time must be greater than start_time when is_active is true")
            if self.courts_available < 1:
                raise ValueError("courts_available must be >= 1 when is_active is true")
        return self


class DayResponse(BaseModel):
    id: int
    tournament_id: int
    date: date
    is_active: bool
    start_time: Optional[time]
    end_time: Optional[time]
    courts_available: int

    class Config:
        from_attributes = True


class BulkDaysUpdate(BaseModel):
    days: List[DayUpdate]


@router.get("/tournaments/{tournament_id}/days", response_model=List[DayResponse])
def get_tournament_days(tournament_id: int, session: Session = Depends(get_session)):
    """Get all days for a tournament"""
    tournament = session.get(Tournament, tournament_id)
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")

    days = session.exec(
        select(TournamentDay).where(TournamentDay.tournament_id == tournament_id).order_by(TournamentDay.date)
    ).all()

    return days


@router.put("/tournaments/{tournament_id}/days", response_model=List[DayResponse])
def bulk_update_days(tournament_id: int, update_data: BulkDaysUpdate, session: Session = Depends(get_session)):
    """Bulk update tournament days"""
    tournament = session.get(Tournament, tournament_id)
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")

    updated_days = []

    for day_update in update_data.days:
        # Find existing day
        day = session.exec(
            select(TournamentDay).where(
                TournamentDay.tournament_id == tournament_id, TournamentDay.date == day_update.date
            )
        ).first()

        if not day:
            raise HTTPException(
                status_code=404, detail=f"Day {day_update.date} not found for tournament {tournament_id}"
            )

        # Validate active day requirements
        if day_update.is_active:
            if not day_update.start_time or not day_update.end_time:
                raise HTTPException(
                    status_code=422,
                    detail=f"start_time and end_time are required when is_active is true for date {day_update.date}",
                )
            if day_update.end_time <= day_update.start_time:
                raise HTTPException(
                    status_code=422, detail=f"end_time must be greater than start_time for date {day_update.date}"
                )
            if day_update.courts_available < 1:
                raise HTTPException(
                    status_code=422,
                    detail=f"courts_available must be >= 1 when is_active is true for date {day_update.date}",
                )

        # Update day
        day.is_active = day_update.is_active
        day.start_time = day_update.start_time
        day.end_time = day_update.end_time
        day.courts_available = day_update.courts_available

        session.add(day)
        updated_days.append(day)

    session.commit()

    # Refresh all updated days
    for day in updated_days:
        session.refresh(day)

    return updated_days
