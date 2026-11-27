"""Staff confirmation that a championship or runner-up trophy was handed out.

Rows belong to one tournament. A duplicated copy does not receive them, and
deleting the tournament removes them.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import UniqueConstraint as SAUniqueConstraint
from sqlmodel import Field, SQLModel


class TrophyDistribution(SQLModel, table=True):
    __tablename__ = "trophydistribution"
    __table_args__ = (SAUniqueConstraint("tournament_id", "award_key", name="uq_trophy_tournament_award"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    tournament_id: int = Field(foreign_key="tournament.id", index=True)
    award_key: str = Field(index=True)
    team_id: int = Field(foreign_key="team.id", index=True)
    role: str
    distributed_at: datetime = Field(default_factory=datetime.utcnow)
