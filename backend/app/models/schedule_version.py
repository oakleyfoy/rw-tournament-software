from datetime import datetime, timezone
from typing import TYPE_CHECKING, List, Optional

from sqlmodel import Field, Relationship, SQLModel

if TYPE_CHECKING:
    from app.models.match import Match
    from app.models.schedule_slot import ScheduleSlot
    from app.models.tournament import Tournament


class ScheduleVersion(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    tournament_id: int = Field(foreign_key="tournament.id")
    version_number: int
    status: str = Field(default="draft")  # "draft" | "final"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    created_by: Optional[str] = None
    notes: Optional[str] = None
    finalized_at: Optional[datetime] = Field(default=None)
    finalized_checksum: Optional[str] = Field(default=None, max_length=64)

    # Relationships
    tournament: "Tournament" = Relationship(back_populates="schedule_versions")
    slots: List["ScheduleSlot"] = Relationship(back_populates="schedule_version")
    matches: List["Match"] = Relationship(back_populates="schedule_version")
