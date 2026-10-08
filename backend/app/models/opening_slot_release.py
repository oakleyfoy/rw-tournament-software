"""Durable staff authorization to release opening WF Round-1 time slots."""

from datetime import date, datetime
from typing import Optional

from sqlalchemy import UniqueConstraint as SAUniqueConstraint
from sqlmodel import Field, SQLModel


class OpeningSlotRelease(SQLModel, table=True):
    __tablename__ = "openingslotrelease"
    __table_args__ = (
        SAUniqueConstraint(
            "schedule_version_id",
            "day_date",
            "slot_key",
            name="uq_opening_slot_release_version_day_slot",
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    tournament_id: int = Field(foreign_key="tournament.id", index=True)
    schedule_version_id: int = Field(foreign_key="scheduleversion.id", index=True)
    day_date: date
    # Same key format as schedule_slot_availability.slot_key: "YYYY-MM-DD|HH:MM"
    slot_key: str = Field(max_length=32)
    released_at: datetime = Field(default_factory=datetime.utcnow)
    released_by: Optional[str] = Field(default=None, max_length=64)
