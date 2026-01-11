from datetime import datetime
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import UniqueConstraint as SAUniqueConstraint
from sqlmodel import Field, Relationship, SQLModel

if TYPE_CHECKING:
    from app.models.event import Event
    from app.models.match import Match


class Team(SQLModel, table=True):
    __table_args__ = (
        # Enforce unique seeds within an event (where seed is not null)
        SAUniqueConstraint("event_id", "seed", name="uq_event_seed"),
        # Optional: Enforce unique team names within an event
        SAUniqueConstraint("event_id", "name", name="uq_event_team_name"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    event_id: int = Field(foreign_key="event.id", index=True)
    name: str  # Team name (required in practice)
    seed: Optional[int] = Field(default=None)  # 1-based seed (1=highest, 2=second, etc.)
    rating: Optional[float] = Field(default=None)  # For tie-breaking when seeds are equal
    registration_timestamp: Optional[datetime] = Field(default=None)  # For tie-breaking
    created_at: datetime = Field(default_factory=datetime.utcnow)

    # WF Grouping V1: Assigned group index for waterfall events (nullable)
    wf_group_index: Optional[int] = Field(default=None, index=True)

    # Relationships
    event: "Event" = Relationship(back_populates="teams")
    matches_as_team_a: List["Match"] = Relationship(
        back_populates="team_a", sa_relationship_kwargs={"foreign_keys": "Match.team_a_id"}
    )
    matches_as_team_b: List["Match"] = Relationship(
        back_populates="team_b", sa_relationship_kwargs={"foreign_keys": "Match.team_b_id"}
    )
