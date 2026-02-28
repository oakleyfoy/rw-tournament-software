from datetime import datetime
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import UniqueConstraint as SAUniqueConstraint
from sqlmodel import Field, Relationship, SQLModel

if TYPE_CHECKING:
    from app.models.event import Event
    from app.models.match import Match


class Team(SQLModel, table=True):
    __table_args__ = (
        SAUniqueConstraint("event_id", "seed", name="uq_event_seed"),
        SAUniqueConstraint("event_id", "name", name="uq_event_team_name"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    event_id: int = Field(foreign_key="event.id", index=True)
    name: str
    seed: Optional[int] = Field(default=None)
    rating: Optional[float] = Field(default=None)
    registration_timestamp: Optional[datetime] = Field(default=None)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    wf_group_index: Optional[int] = Field(default=None, index=True)
    avoid_group: Optional[str] = Field(default=None, max_length=4)
    display_name: Optional[str] = Field(default=None)
    player1_cellphone: Optional[str] = Field(default=None)
    player1_email: Optional[str] = Field(default=None)
    player2_cellphone: Optional[str] = Field(default=None)
    player2_email: Optional[str] = Field(default=None)
    p1_cell: Optional[str] = Field(default=None)
    p1_email: Optional[str] = Field(default=None)
    p2_cell: Optional[str] = Field(default=None)
    p2_email: Optional[str] = Field(default=None)
    is_defaulted: bool = Field(default=False)
    notes: Optional[str] = Field(default=None)

    # Relationships
    event: "Event" = Relationship(back_populates="teams")
    matches_as_team_a: List["Match"] = Relationship(
        back_populates="team_a", sa_relationship_kwargs={"foreign_keys": "Match.team_a_id"}
    )
    matches_as_team_b: List["Match"] = Relationship(
        back_populates="team_b", sa_relationship_kwargs={"foreign_keys": "Match.team_b_id"}
    )
