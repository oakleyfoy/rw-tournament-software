"""SMS log model for tracking sent messages."""

from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Field, SQLModel


class SmsLog(SQLModel, table=True):
    """Log of every SMS sent through the system."""

    __tablename__ = "sms_log"

    id: Optional[int] = Field(default=None, primary_key=True)
    tournament_id: int = Field(foreign_key="tournament.id", index=True)
    team_id: Optional[int] = Field(default=None, foreign_key="team.id")
    phone_number: str  # Recipient phone in E.164 format
    message_body: str  # The actual message text sent
    message_type: str  # tournament_blast|first_match|post_match_next|on_deck|up_next|court_change|time_slot_blast|match_specific|team_direct
    twilio_sid: Optional[str] = Field(default=None)  # Twilio message SID for tracking
    status: str = Field(default="queued")  # queued|sent|delivered|failed|undelivered
    error_message: Optional[str] = Field(default=None)  # Error details if failed
    trigger: str = Field(default="manual")  # manual|auto
    sent_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
