from datetime import datetime
from typing import Optional

from sqlalchemy import UniqueConstraint as SAUniqueConstraint
from sqlmodel import Field, SQLModel


class SlotLock(SQLModel, table=True):
    __table_args__ = (
        SAUniqueConstraint("schedule_version_id", "slot_id", name="uq_slotlock_version_slot"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    schedule_version_id: int = Field(foreign_key="scheduleversion.id", index=True)
    slot_id: int = Field(foreign_key="scheduleslot.id")
    status: str = Field(default="BLOCKED", max_length=10)
    created_at: datetime = Field(default_factory=datetime.utcnow)
