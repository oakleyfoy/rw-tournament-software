"""Tournament SMS settings model for auto-text toggles."""

from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Field, SQLModel


class TournamentSmsSettings(SQLModel, table=True):
    """Per-tournament settings controlling which auto-texts are enabled."""

    __tablename__ = "tournament_sms_settings"

    id: Optional[int] = Field(default=None, primary_key=True)
    tournament_id: int = Field(foreign_key="tournament.id", unique=True, index=True)

    # Auto-text toggles (all default OFF until admin enables)
    auto_first_match: bool = Field(default=False)
    auto_post_match_next: bool = Field(default=False)
    auto_on_deck: bool = Field(default=False)
    auto_up_next: bool = Field(default=False)
    auto_court_change: bool = Field(default=True)  # Court changes default ON

    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
