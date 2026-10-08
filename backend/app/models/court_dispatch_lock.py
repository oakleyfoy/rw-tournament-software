"""Short-lived mutex row serializing PREASSIGNED starts per court/day/version."""

from datetime import date, datetime
from typing import Optional

from sqlalchemy import UniqueConstraint as SAUniqueConstraint
from sqlmodel import Field, SQLModel


class CourtDispatchLock(SQLModel, table=True):
    __tablename__ = "courtdispatchlock"
    __table_args__ = (
        SAUniqueConstraint(
            "schedule_version_id",
            "day_date",
            "court_number",
            name="uq_court_dispatch_lock_version_day_court",
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    schedule_version_id: int = Field(foreign_key="scheduleversion.id", index=True)
    day_date: date
    court_number: int
    holder: Optional[str] = Field(default=None, max_length=64)
    created_at: datetime = Field(default_factory=datetime.utcnow)
