from datetime import date, time
from typing import TYPE_CHECKING, Optional

from sqlalchemy import UniqueConstraint as SAUniqueConstraint
from sqlmodel import Field, Relationship, SQLModel

if TYPE_CHECKING:
    from app.models.tournament import Tournament


class TournamentTimeWindow(SQLModel, table=True):
    __table_args__ = (
        SAUniqueConstraint("tournament_id", "day_date", "start_time", "end_time", name="uq_tournament_time_window"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    tournament_id: int = Field(foreign_key="tournament.id")
    day_date: date
    start_time: time
    end_time: time
    courts_available: int = Field(default=1)
    block_minutes: int = Field(default=120)  # Must be one of [60, 90, 105, 120]
    label: Optional[str] = Field(default=None)
    is_active: bool = Field(default=True)

    # Relationship
    tournament: "Tournament" = Relationship(back_populates="time_windows")
