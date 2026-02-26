from datetime import datetime
from typing import Optional

from sqlalchemy import UniqueConstraint as SAUniqueConstraint
from sqlmodel import Field, SQLModel


class MatchLock(SQLModel, table=True):
    __table_args__ = (
        SAUniqueConstraint("schedule_version_id", "match_id", name="uq_matchlock_version_match"),
        SAUniqueConstraint("schedule_version_id", "slot_id", name="uq_matchlock_version_slot"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    schedule_version_id: int = Field(foreign_key="scheduleversion.id", index=True)
    match_id: int = Field(foreign_key="match.id")
    slot_id: int = Field(foreign_key="scheduleslot.id")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    created_by: Optional[str] = None
