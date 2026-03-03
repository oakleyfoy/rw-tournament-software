"""Team <-> Player join model."""

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

from sqlmodel import Field, Relationship, SQLModel, UniqueConstraint

if TYPE_CHECKING:
    from app.models.player import Player
    from app.models.team import Team


class TeamPlayer(SQLModel, table=True):
    """Maps players to a team roster slot."""

    __tablename__ = "team_player"
    __table_args__ = (
        UniqueConstraint("team_id", "player_id", name="uq_team_player"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    team_id: int = Field(foreign_key="team.id", index=True)
    player_id: int = Field(foreign_key="player.id", index=True)

    lineup_slot: Optional[int] = Field(default=None)  # 1|2 for doubles, null unknown
    role: Optional[str] = Field(default=None)  # player|sub|alternate (optional metadata)
    is_primary_contact: bool = Field(default=False)

    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    team: "Team" = Relationship(back_populates="player_links")
    player: "Player" = Relationship(back_populates="team_links")
