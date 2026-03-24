from datetime import datetime
from typing import Optional

from sqlalchemy import UniqueConstraint as SAUniqueConstraint
from sqlmodel import Field, SQLModel


class MatchPlayerCheckIn(SQLModel, table=True):
    __table_args__ = (
        SAUniqueConstraint(
            "schedule_version_id",
            "match_id",
            "side",
            "player_id",
            name="uq_matchplayercheckin_version_match_side_player",
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    tournament_id: int = Field(foreign_key="tournament.id", index=True)
    schedule_version_id: int = Field(foreign_key="scheduleversion.id", index=True)
    match_id: int = Field(foreign_key="match.id", index=True)
    team_id: Optional[int] = Field(default=None, foreign_key="team.id", index=True)
    player_id: int = Field(foreign_key="player.id", index=True)
    side: str = Field(index=True, max_length=1)  # A | B
    checked_in: bool = Field(default=False)
    checked_in_at: Optional[datetime] = Field(default=None)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
