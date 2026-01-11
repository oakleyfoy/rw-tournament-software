from enum import Enum
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import String
from sqlalchemy import UniqueConstraint as SAUniqueConstraint
from sqlmodel import Column, Field, Relationship, SQLModel

if TYPE_CHECKING:
    from app.models.match import Match
    from app.models.team import Team
    from app.models.team_avoid_edge import TeamAvoidEdge
    from app.models.tournament import Tournament


class EventCategory(str, Enum):
    mixed = "mixed"
    womens = "womens"


class Event(SQLModel, table=True):
    __table_args__ = (SAUniqueConstraint("tournament_id", "category", "name", name="uq_tournament_event"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    tournament_id: int = Field(foreign_key="tournament.id")
    category: EventCategory = Field(sa_column=Column(String))
    name: str
    team_count: int
    notes: Optional[str] = None

    # Phase 2 fields
    draw_plan_json: Optional[str] = Field(default=None)
    draw_plan_version: str = Field(default="1.0")
    draw_status: str = Field(default="not_started")
    wf_block_minutes: int = Field(default=60)
    standard_block_minutes: int = Field(default=120)
    guarantee_selected: Optional[int] = Field(default=None)
    schedule_profile_json: Optional[str] = Field(default=None)

    # Relationships
    tournament: "Tournament" = Relationship(back_populates="events")
    matches: List["Match"] = Relationship(back_populates="event")
    teams: List["Team"] = Relationship(back_populates="event")
    avoid_edges: List["TeamAvoidEdge"] = Relationship(back_populates="event")
