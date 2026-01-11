"""
Team Avoid Edge Model - Who-Knows-Who WF Grouping V1

Tracks pairs of teams that should avoid playing each other in WF rounds.
"""

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

from sqlalchemy import CheckConstraint
from sqlalchemy import UniqueConstraint as SAUniqueConstraint
from sqlmodel import Field, Relationship, SQLModel

if TYPE_CHECKING:
    from app.models.event import Event


class TeamAvoidEdge(SQLModel, table=True):
    """
    Represents an avoid relationship between two teams.

    Constraint: team_id_a < team_id_b to prevent duplicate edges (A→B and B→A)
    """

    __tablename__ = "team_avoid_edge"

    __table_args__ = (
        SAUniqueConstraint("event_id", "team_id_a", "team_id_b", name="uq_event_avoid_edge"),
        CheckConstraint("team_id_a < team_id_b", name="ck_team_order"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    event_id: int = Field(foreign_key="event.id", index=True)
    team_id_a: int = Field(foreign_key="team.id", index=True)
    team_id_b: int = Field(foreign_key="team.id", index=True)
    reason: Optional[str] = Field(default=None)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # Relationships
    event: "Event" = Relationship(back_populates="avoid_edges")
