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

    # Safety mode for live testing:
    # if enabled, sends are restricted to numbers in test_allowlist.
    test_mode: bool = Field(default=False)
    test_allowlist: Optional[str] = Field(default=None)

    # Optional deprecation path:
    # when enabled, team/event/division/match texting resolves recipients from
    # Player/TeamPlayer records only (no direct legacy Team phone-field fallback).
    player_contacts_only: bool = Field(default=False)

    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
