from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import UniqueConstraint as SAUniqueConstraint
from sqlmodel import Field, Relationship, SQLModel

if TYPE_CHECKING:
    from app.models.match import Match
    from app.models.schedule_slot import ScheduleSlot
    from app.models.schedule_version import ScheduleVersion


class MatchAssignment(SQLModel, table=True):
    __table_args__ = (
        SAUniqueConstraint("schedule_version_id", "slot_id", name="uq_assignment_version_slot"),
        SAUniqueConstraint("schedule_version_id", "match_id", name="uq_assignment_version_match"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    schedule_version_id: int = Field(foreign_key="scheduleversion.id")
    match_id: int = Field(foreign_key="match.id")
    slot_id: int = Field(foreign_key="scheduleslot.id")
    assigned_at: datetime = Field(default_factory=datetime.utcnow)
    assigned_by: Optional[str] = None

    # Relationships
    schedule_version: "ScheduleVersion" = Relationship()
    match: "Match" = Relationship(back_populates="assignment")
    slot: "ScheduleSlot" = Relationship(back_populates="assignment")
