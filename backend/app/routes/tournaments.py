from datetime import date, datetime, time, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, field_validator, model_validator
from sqlmodel import Session, func, select, text

from app.database import get_session
from app.models.tournament import Tournament
from app.models.tournament_day import TournamentDay
from app.utils.courts import parse_court_names

router = APIRouter()


class TournamentCreate(BaseModel):
    name: str
    location: str
    timezone: str
    start_date: date
    end_date: date
    notes: Optional[str] = None

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, v):
        if not v or not v.strip():
            raise ValueError("timezone is required")
        return v.strip()

    @model_validator(mode="after")
    def validate_date_range(self):
        if self.end_date < self.start_date:
            raise ValueError("end_date must be >= start_date")
        return self


class TournamentUpdate(BaseModel):
    name: Optional[str] = None
    location: Optional[str] = None
    timezone: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    notes: Optional[str] = None
    use_time_windows: Optional[bool] = None
    court_names: Optional[List[str]] = None

    @model_validator(mode="after")
    def validate_date_range(self):
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValueError("end_date must be >= start_date")
        return self


class TournamentResponse(BaseModel):
    id: int
    name: str
    location: str
    timezone: str
    start_date: date
    end_date: date
    notes: Optional[str]
    use_time_windows: bool
    court_names: Optional[List[str]] = None
    created_at: datetime
    updated_at: datetime

    @field_validator("court_names", mode="before")
    @classmethod
    def normalize_court_names(cls, v):
        """Handle legacy DB storage: court_names may be string '1,2,3' instead of list."""
        if v is None:
            return None
        return parse_court_names(v)  # handles str and list, returns List[str]

    class Config:
        from_attributes = True


def generate_tournament_days(session: Session, tournament_id: int, start_date: date, end_date: date):
    """Generate tournament days for the date range"""
    current_date = start_date
    while current_date <= end_date:
        # Check if day already exists
        existing = session.exec(
            select(TournamentDay).where(
                TournamentDay.tournament_id == tournament_id, TournamentDay.date == current_date
            )
        ).first()

        if not existing:
            day = TournamentDay(
                tournament_id=tournament_id,
                date=current_date,
                is_active=True,
                start_time=time(8, 0),
                end_time=time(18, 0),
                courts_available=0,
            )
            session.add(day)
        current_date += timedelta(days=1)
    session.commit()


@router.get("/tournaments", response_model=List[TournamentResponse])
def list_tournaments(session: Session = Depends(get_session)):
    """List all tournaments"""
    tournaments = session.exec(select(Tournament)).all()
    return tournaments


@router.post("/tournaments", response_model=TournamentResponse, status_code=201)
def create_tournament(tournament_data: TournamentCreate, session: Session = Depends(get_session)):
    """Create a new tournament and auto-generate days"""
    tournament = Tournament(**tournament_data.model_dump())
    session.add(tournament)
    session.commit()
    session.refresh(tournament)

    # Auto-generate days
    generate_tournament_days(session, tournament.id, tournament.start_date, tournament.end_date)

    return tournament


@router.get("/tournaments/{tournament_id}", response_model=TournamentResponse)
def get_tournament(tournament_id: int, session: Session = Depends(get_session)):
    """Get a tournament by ID"""
    tournament = session.get(Tournament, tournament_id)
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")
    return tournament


@router.put("/tournaments/{tournament_id}", response_model=TournamentResponse)
def update_tournament(tournament_id: int, tournament_data: TournamentUpdate, session: Session = Depends(get_session)):
    """Update a tournament and manage days based on date range changes"""
    tournament = session.get(Tournament, tournament_id)
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")

    old_start = tournament.start_date
    old_end = tournament.end_date

    # Update tournament fields
    update_data = tournament_data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(tournament, field, value)

    tournament.updated_at = datetime.utcnow()
    session.add(tournament)
    session.commit()

    # Handle date range changes
    new_start = tournament.start_date
    new_end = tournament.end_date

    if old_start != new_start or old_end != new_end:
        # Remove days outside the new range
        session.exec(
            select(TournamentDay)
            .where(TournamentDay.tournament_id == tournament_id)
            .where((TournamentDay.date < new_start) | (TournamentDay.date > new_end))
        )
        days_to_remove = session.exec(
            select(TournamentDay).where(
                TournamentDay.tournament_id == tournament_id,
                (TournamentDay.date < new_start) | (TournamentDay.date > new_end),
            )
        ).all()
        for day in days_to_remove:
            session.delete(day)

        # Add missing days for new range
        generate_tournament_days(session, tournament_id, new_start, new_end)

    session.refresh(tournament)
    return tournament


@router.post("/tournaments/{tournament_id}/duplicate", response_model=TournamentResponse, status_code=201)
def duplicate_tournament(tournament_id: int, session: Session = Depends(get_session)):
    """Duplicate a tournament with its days and time windows"""
    try:
        source_tournament = session.get(Tournament, tournament_id)
        if not source_tournament:
            raise HTTPException(status_code=404, detail="Tournament not found")

        # Create new tournament
        new_tournament = Tournament(
            name=f"{source_tournament.name} (Copy)",
            location=source_tournament.location,
            timezone=source_tournament.timezone,
            start_date=source_tournament.start_date,
            end_date=source_tournament.end_date,
            notes=source_tournament.notes,
            use_time_windows=source_tournament.use_time_windows,
        )
        session.add(new_tournament)
        session.flush()  # Get the ID

        # Copy days
        source_days = session.exec(select(TournamentDay).where(TournamentDay.tournament_id == tournament_id)).all()

        for day in source_days:
            new_day = TournamentDay(
                tournament_id=new_tournament.id,
                date=day.date,
                is_active=day.is_active,
                start_time=day.start_time,
                end_time=day.end_time,
                courts_available=day.courts_available,
            )
            session.add(new_day)

        # Copy time windows
        from app.models.tournament_time_window import TournamentTimeWindow

        source_windows = session.exec(
            select(TournamentTimeWindow).where(TournamentTimeWindow.tournament_id == tournament_id)
        ).all()

        for window in source_windows:
            new_window = TournamentTimeWindow(
                tournament_id=new_tournament.id,
                day_date=window.day_date,
                start_time=window.start_time,
                end_time=window.end_time,
                courts_available=window.courts_available,
                block_minutes=window.block_minutes,
                label=window.label,
                is_active=window.is_active,
            )
            session.add(new_window)

        session.commit()
        session.refresh(new_tournament)

        return new_tournament
    except HTTPException:
        raise
    except Exception as e:
        session.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to duplicate tournament: {str(e)}")


@router.delete("/tournaments/{tournament_id}", status_code=204)
def delete_tournament(tournament_id: int, session: Session = Depends(get_session)):
    """Delete a tournament and all its related data (events, days, time windows, etc.)"""
    try:
        # Check if tournament exists (without loading it into session to avoid relationship handling)
        tournament_exists = session.exec(select(func.count(Tournament.id)).where(Tournament.id == tournament_id)).one()

        if tournament_exists == 0:
            raise HTTPException(status_code=404, detail="Tournament not found")

        # Delete related records using raw SQL to completely bypass SQLAlchemy ORM
        # This prevents any relationship handling or tracking
        # Using parameterized queries to prevent SQL injection
        # Order matters: delete child records before parent records

        # 1. Delete events (and their related data will be cascade deleted if configured)
        session.execute(
            text("DELETE FROM event WHERE tournament_id = :tournament_id"), {"tournament_id": tournament_id}
        )

        # 2. Delete time windows using raw SQL
        session.execute(
            text("DELETE FROM tournamenttimewindow WHERE tournament_id = :tournament_id"),
            {"tournament_id": tournament_id},
        )

        # 3. Delete tournament days using raw SQL
        session.execute(
            text("DELETE FROM tournamentday WHERE tournament_id = :tournament_id"), {"tournament_id": tournament_id}
        )

        # 4. Delete schedule-related data (if any exists)
        # Schedule versions, slots, matches, assignments
        session.execute(
            text(
                "DELETE FROM matchassignment WHERE schedule_version_id IN (SELECT id FROM scheduleversion WHERE tournament_id = :tournament_id)"
            ),
            {"tournament_id": tournament_id},
        )
        session.execute(
            text("DELETE FROM match WHERE tournament_id = :tournament_id"), {"tournament_id": tournament_id}
        )
        session.execute(
            text("DELETE FROM scheduleslot WHERE tournament_id = :tournament_id"), {"tournament_id": tournament_id}
        )
        session.execute(
            text("DELETE FROM scheduleversion WHERE tournament_id = :tournament_id"), {"tournament_id": tournament_id}
        )

        # 5. Delete the tournament itself using raw SQL
        session.execute(text("DELETE FROM tournament WHERE id = :tournament_id"), {"tournament_id": tournament_id})

        session.commit()

        return Response(status_code=204)
    except HTTPException:
        raise
    except Exception as e:
        session.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to delete tournament: {str(e)}")
