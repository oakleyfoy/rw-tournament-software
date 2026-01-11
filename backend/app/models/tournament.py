from datetime import date, datetime
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import JSON
from sqlmodel import Column, Field, Relationship, SQLModel

if TYPE_CHECKING:
    from app.models.event import Event
    from app.models.match import Match
    from app.models.schedule_slot import ScheduleSlot
    from app.models.schedule_version import ScheduleVersion
    from app.models.tournament_day import TournamentDay
    from app.models.tournament_time_window import TournamentTimeWindow


class Tournament(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    location: str
    timezone: str
    start_date: date
    end_date: date
    notes: Optional[str] = None
    use_time_windows: bool = Field(default=False)
    court_names: Optional[List[str]] = Field(default=None, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow, sa_column_kwargs={"onupdate": datetime.utcnow})

    # Relationships
    days: List["TournamentDay"] = Relationship(back_populates="tournament")
    events: List["Event"] = Relationship(back_populates="tournament")
    time_windows: List["TournamentTimeWindow"] = Relationship(back_populates="tournament")
    schedule_versions: List["ScheduleVersion"] = Relationship(back_populates="tournament")
    schedule_slots: List["ScheduleSlot"] = Relationship(back_populates="tournament")
    matches: List["Match"] = Relationship(back_populates="tournament")
