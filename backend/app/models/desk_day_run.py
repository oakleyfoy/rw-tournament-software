"""Per-day Dashboard start and pause state for designated-court tournaments."""

from datetime import date, datetime
from typing import Optional

from sqlalchemy import UniqueConstraint as SAUniqueConstraint
from sqlmodel import Field, SQLModel


class DeskDayRun(SQLModel, table=True):
    __tablename__ = "deskdayrun"
    __table_args__ = (
        SAUniqueConstraint("schedule_version_id", "day_date", name="uq_deskdayrun_version_day"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    tournament_id: int = Field(foreign_key="tournament.id", index=True)
    schedule_version_id: int = Field(foreign_key="scheduleversion.id", index=True)
    day_date: date = Field(index=True)
    started_at: datetime = Field(default_factory=datetime.utcnow)
    paused: bool = Field(default=False)
