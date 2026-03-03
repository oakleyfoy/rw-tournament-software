"""Audit log for inbound/outbound SMS consent transitions."""

from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Field, SQLModel, UniqueConstraint


class SmsConsentEvent(SQLModel, table=True):
    """Normalized consent event stream (STOP/START/HELP/manual updates)."""

    __tablename__ = "sms_consent_event"
    __table_args__ = (
        UniqueConstraint(
            "tournament_id",
            "dedupe_key",
            name="uq_sms_consent_dedupe",
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    tournament_id: int = Field(foreign_key="tournament.id", index=True)
    player_id: Optional[int] = Field(default=None, foreign_key="player.id", index=True)

    phone_number: str = Field(index=True)  # E.164 normalized
    event_type: str = Field(index=True)  # opted_in|opted_out|help|other
    source: str = Field(default="manual")  # manual|import|twilio_webhook|api
    message_text: Optional[str] = Field(default=None)
    provider_message_sid: Optional[str] = Field(default=None, index=True)
    dedupe_key: Optional[str] = Field(default=None)

    occurred_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        index=True,
    )
