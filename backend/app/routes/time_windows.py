from datetime import date, time, timedelta
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator, model_validator
from sqlmodel import Session, select

from app.database import get_session
from app.models.tournament import Tournament
from app.models.tournament_time_window import TournamentTimeWindow

router = APIRouter()

ALLOWED_BLOCK_MINUTES = [60, 90, 105, 120]


class TimeWindowCreate(BaseModel):
    day_date: date
    start_time: time
    end_time: time
    courts_available: int
    block_minutes: int
    label: Optional[str] = None
    is_active: bool = True

    @field_validator("block_minutes")
    @classmethod
    def validate_block_minutes(cls, v):
        if v not in ALLOWED_BLOCK_MINUTES:
            raise ValueError(f"block_minutes must be one of {ALLOWED_BLOCK_MINUTES}")
        return v

    @model_validator(mode="after")
    def validate_times(self):
        if self.end_time <= self.start_time:
            raise ValueError("end_time must be greater than start_time")
        if self.courts_available < 1:
            raise ValueError("courts_available must be >= 1")
        return self


class TimeWindowUpdate(BaseModel):
    day_date: Optional[date] = None
    start_time: Optional[time] = None
    end_time: Optional[time] = None
    courts_available: Optional[int] = None
    block_minutes: Optional[int] = None
    label: Optional[str] = None
    is_active: Optional[bool] = None

    @field_validator("block_minutes")
    @classmethod
    def validate_block_minutes(cls, v):
        if v is not None and v not in ALLOWED_BLOCK_MINUTES:
            raise ValueError(f"block_minutes must be one of {ALLOWED_BLOCK_MINUTES}")
        return v

    @model_validator(mode="after")
    def validate_times(self):
        # If updating times, validate they make sense
        if self.start_time is not None and self.end_time is not None:
            if self.end_time <= self.start_time:
                raise ValueError("end_time must be greater than start_time")
        return self


class TimeWindowResponse(BaseModel):
    id: int
    tournament_id: int
    day_date: date
    start_time: time
    end_time: time
    courts_available: int
    block_minutes: int
    label: Optional[str]
    is_active: bool

    class Config:
        from_attributes = True


class TimeWindowSummary(BaseModel):
    total_capacity_minutes: int
    slot_capacity_by_block: Dict[int, int]
    total_slots_all_blocks: int


def calculate_window_duration_minutes(start: time, end: time) -> int:
    """Calculate duration in minutes between two times"""
    start_dt = timedelta(hours=start.hour, minutes=start.minute, seconds=start.second)
    end_dt = timedelta(hours=end.hour, minutes=end.minute, seconds=end.second)
    if end_dt < start_dt:
        # Handle wrap-around (end is next day)
        end_dt += timedelta(days=1)
    duration = end_dt - start_dt
    return int(duration.total_seconds() / 60)


@router.get("/tournaments/{tournament_id}/time-windows", response_model=List[TimeWindowResponse])
def get_time_windows(tournament_id: int, session: Session = Depends(get_session)):
    """Get all time windows for a tournament"""
    tournament = session.get(Tournament, tournament_id)
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")

    windows = session.exec(
        select(TournamentTimeWindow)
        .where(TournamentTimeWindow.tournament_id == tournament_id)
        .order_by(TournamentTimeWindow.day_date, TournamentTimeWindow.start_time)
    ).all()

    return windows


@router.post("/tournaments/{tournament_id}/time-windows", response_model=TimeWindowResponse)
def create_time_window(tournament_id: int, window_data: TimeWindowCreate, session: Session = Depends(get_session)):
    """Create a new time window for a tournament"""
    tournament = session.get(Tournament, tournament_id)
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")

    # Check for overlapping windows (optional validation - could be allowed)
    # For now, we'll allow overlaps and let the user manage them

    window = TournamentTimeWindow(tournament_id=tournament_id, **window_data.model_dump())

    session.add(window)
    session.commit()
    session.refresh(window)

    return window


@router.put("/time-windows/{window_id}", response_model=TimeWindowResponse)
def update_time_window(window_id: int, window_data: TimeWindowUpdate, session: Session = Depends(get_session)):
    """Update a time window"""
    window = session.get(TournamentTimeWindow, window_id)
    if not window:
        raise HTTPException(status_code=404, detail="Time window not found")

    update_dict = window_data.model_dump(exclude_unset=True)
    for field, value in update_dict.items():
        setattr(window, field, value)

    session.add(window)
    session.commit()
    session.refresh(window)

    return window


@router.delete("/time-windows/{window_id}")
def delete_time_window(window_id: int, session: Session = Depends(get_session)):
    """Delete a time window"""
    window = session.get(TournamentTimeWindow, window_id)
    if not window:
        raise HTTPException(status_code=404, detail="Time window not found")

    session.delete(window)
    session.commit()

    return {"message": "Time window deleted successfully"}


@router.get("/tournaments/{tournament_id}/time-windows/summary", response_model=TimeWindowSummary)
def get_time_windows_summary(tournament_id: int, session: Session = Depends(get_session)):
    """Get summary of time windows capacity"""
    tournament = session.get(Tournament, tournament_id)
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")

    windows = session.exec(
        select(TournamentTimeWindow).where(
            TournamentTimeWindow.tournament_id == tournament_id, TournamentTimeWindow.is_active
        )
    ).all()

    total_capacity_minutes = 0
    slot_capacity_by_block: Dict[int, int] = {60: 0, 90: 0, 105: 0, 120: 0}

    for window in windows:
        duration_minutes = calculate_window_duration_minutes(window.start_time, window.end_time)
        window_capacity_minutes = duration_minutes * window.courts_available
        total_capacity_minutes += window_capacity_minutes

        # Calculate slots in this window
        slots_in_window = (duration_minutes // window.block_minutes) * window.courts_available
        if window.block_minutes in slot_capacity_by_block:
            slot_capacity_by_block[window.block_minutes] += slots_in_window

    total_slots_all_blocks = sum(slot_capacity_by_block.values())

    return TimeWindowSummary(
        total_capacity_minutes=total_capacity_minutes,
        slot_capacity_by_block=slot_capacity_by_block,
        total_slots_all_blocks=total_slots_all_blocks,
    )
