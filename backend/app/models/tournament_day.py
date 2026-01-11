from datetime import date, time
from typing import TYPE_CHECKING, Optional

from sqlalchemy import UniqueConstraint as SAUniqueConstraint
from sqlmodel import Field, Relationship, SQLModel

if TYPE_CHECKING:
    from app.models.tournament import Tournament


class TournamentDay(SQLModel, table=True):
    __table_args__ = (SAUniqueConstraint("tournament_id", "date", name="uq_tournament_day"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    tournament_id: int = Field(foreign_key="tournament.id")
    date: date
    is_active: bool = Field(default=True)
    start_time: Optional[time] = Field(default=None)
    end_time: Optional[time] = Field(default=None)
    courts_available: int = Field(default=0)

    # Relationship
    tournament: "Tournament" = Relationship(back_populates="days")
