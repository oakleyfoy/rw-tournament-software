"""Tournament SMS settings model for auto-text toggles."""

from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Field, SQLModel

# Mutually exclusive outbound delivery modes.
SMS_DELIVERY_MODE_LIVE = "live"
SMS_DELIVERY_MODE_ALLOWLIST = "allowlist"
SMS_DELIVERY_MODE_REDIRECT = "redirect"
SMS_DELIVERY_MODES = frozenset(
    {
        SMS_DELIVERY_MODE_LIVE,
        SMS_DELIVERY_MODE_ALLOWLIST,
        SMS_DELIVERY_MODE_REDIRECT,
    }
)


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
    # Check-in management auto-text toggles
    auto_checkin_first_match: bool = Field(default=False)
    auto_checkin_slot_checkin: bool = Field(default=False)
    auto_checkin_post_match_next: bool = Field(default=False)
    auto_checkin_court_assigned: bool = Field(default=False)

    # Master emergency switch — when False, no outbound tournament SMS is sent.
    texts_enabled: bool = Field(default=True)

    # Delivery mode: live | allowlist | redirect (mutually exclusive).
    # Legacy test_mode is kept in sync for older clients (True <=> allowlist).
    delivery_mode: str = Field(default=SMS_DELIVERY_MODE_LIVE)
    test_mode: bool = Field(default=False)
    test_allowlist: Optional[str] = Field(default=None)
    # Single E.164 destination used when delivery_mode == redirect.
    redirect_phone: Optional[str] = Field(default=None)

    # Optional deprecation path:
    # when enabled, team/event/division/match texting resolves recipients from
    # Player/TeamPlayer records only (no direct legacy Team phone-field fallback).
    player_contacts_only: bool = Field(default=False)

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
