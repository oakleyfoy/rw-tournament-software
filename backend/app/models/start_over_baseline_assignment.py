from datetime import datetime
from typing import Optional

from sqlalchemy import UniqueConstraint as SAUniqueConstraint
from sqlmodel import Field, SQLModel


class StartOverBaselineAssignment(SQLModel, table=True):
    __table_args__ = (
        SAUniqueConstraint(
            "schedule_version_id",
            "match_id",
            name="uq_startover_baseline_version_match",
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    tournament_id: int = Field(foreign_key="tournament.id", index=True)
    schedule_version_id: int = Field(foreign_key="scheduleversion.id", index=True)
    match_id: int = Field(foreign_key="match.id")
    slot_id: int = Field(foreign_key="scheduleslot.id")
    assigned_at: datetime = Field(default_factory=datetime.utcnow)
    assigned_by: Optional[str] = None
    locked: bool = Field(default=False)
