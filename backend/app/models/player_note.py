"""Staff notes attached to a tournament player.

Notes follow the player, not a match or team tile. They are internal and are
not included on public pages or in text messages.
"""

from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Field, SQLModel


class PlayerNote(SQLModel, table=True):
    __tablename__ = "player_note"

    id: Optional[int] = Field(default=None, primary_key=True)
    tournament_id: int = Field(foreign_key="tournament.id", index=True)
    player_id: int = Field(foreign_key="player.id", index=True)
    body: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), index=True)
    created_by_user_id: Optional[int] = Field(default=None, foreign_key="user_account.id")
    created_by_name: Optional[str] = Field(default=None, max_length=150)
    updated_at: Optional[datetime] = Field(default=None)
    updated_by_user_id: Optional[int] = Field(default=None, foreign_key="user_account.id")
    updated_by_name: Optional[str] = Field(default=None, max_length=150)
