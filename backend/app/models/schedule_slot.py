from datetime import date, time
from typing import TYPE_CHECKING, Optional

from sqlalchemy import UniqueConstraint as SAUniqueConstraint
from sqlalchemy.orm import validates
from sqlmodel import Field, Relationship, SQLModel

if TYPE_CHECKING:
    from app.models.match_assignment import MatchAssignment
    from app.models.schedule_version import ScheduleVersion
    from app.models.tournament import Tournament


class ScheduleSlot(SQLModel, table=True):
    __table_args__ = (
        SAUniqueConstraint(
            "schedule_version_id", "day_date", "start_time", "court_number", name="uq_slot_version_day_time_court"
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    tournament_id: int = Field(foreign_key="tournament.id")
    schedule_version_id: int = Field(foreign_key="scheduleversion.id")
    day_date: date
    start_time: time
    end_time: time
    court_number: int
    court_label: str  # Label from tournament.court_names (immutable per version)

    @validates("court_label")
    def validate_court_label(self, key: str, value: object) -> object:
        """Ensure court_label is always stored as a string (SQLite cannot bind list)."""
        if value is None:
            return ""
        if isinstance(value, str):
            return value
        if isinstance(value, list):
            return ",".join(str(x) for x in value)
        return str(value)
    block_minutes: int
    label: Optional[str] = None
    is_active: bool = Field(default=True)

    # Relationships
    tournament: "Tournament" = Relationship(back_populates="schedule_slots")
    schedule_version: "ScheduleVersion" = Relationship(back_populates="slots")
    assignment: Optional["MatchAssignment"] = Relationship(
        back_populates="slot", sa_relationship_kwargs={"uselist": False}
    )
