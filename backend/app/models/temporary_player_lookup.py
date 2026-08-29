"""Temporary per-player towel/report lookup for check-in workflows."""

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Index, text
from sqlmodel import Field, SQLModel


class TemporaryPlayerLookup(SQLModel, table=True):
    """Tournament-scoped imported player metadata used by check-in."""

    __tablename__ = "temporary_player_lookup"
    __table_args__ = (
        Index(
            "uq_rwos_lookup_source_identity",
            "tournament_id",
            "source",
            "source_team_key",
            "lineup_slot",
            unique=True,
            sqlite_where=text("source IS NOT NULL"),
            postgresql_where=text("source IS NOT NULL"),
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    tournament_id: int = Field(foreign_key="tournament.id", index=True)
    player_id: Optional[int] = Field(default=None, foreign_key="player.id", index=True)

    source_name: str
    normalized_name: str = Field(index=True)
    source_phone: Optional[str] = Field(default=None)
    normalized_phone: Optional[str] = Field(default=None, index=True)
    source_email: Optional[str] = Field(default=None)
    normalized_email: Optional[str] = Field(default=None, index=True)

    towel_color: str
    report_url: Optional[str] = Field(default=None)
    source: Optional[str] = Field(default=None, index=True)
    source_team_key: Optional[str] = Field(default=None, index=True)
    lineup_slot: Optional[int] = Field(default=None)

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
