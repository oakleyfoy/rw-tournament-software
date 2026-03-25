"""SMS template model for customizable message templates."""

from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Field, SQLModel, UniqueConstraint


class SmsTemplate(SQLModel, table=True):
    """Customizable message templates per tournament and message type."""

    __tablename__ = "sms_template"
    __table_args__ = (
        UniqueConstraint(
            "tournament_id", "message_type", name="uq_tournament_message_type"
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    tournament_id: int = Field(foreign_key="tournament.id", index=True)
    message_type: str  # first_match|rr_first_match|post_match_next|on_deck|up_next|court_change|checkin_*
    template_body: str  # Message with {placeholders}
    is_active: bool = Field(default=True)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


# Default templates - used when no custom template exists
DEFAULT_SMS_TEMPLATES = {
    "first_match": (
        "{team_name}: Your first match is {date} at {time} on {court}."
    ),
    "rr_first_match": (
        "{team_name}: Your first match is {date} at {time} on {court}."
    ),
    "post_match_next": (
        "{team_name}: Your next match is {date} at {time} on {court}."
    ),
    "on_deck": (
        "{team_name}: You're ON DECK. Your match on {court} starts after "
        "the current game."
    ),
    "up_next": (
        "{team_name}: You're UP NEXT on {court}. Please head to your court now."
    ),
    "court_change": (
        "{team_name}: Court change! Your match has moved to {court} at {time}."
    ),
    "checkin_first_match": (
        "{team_name}: Your first match is {date} at {time}. "
        "Please arrive at least 30 mins early and check in at the desk."
    ),
    "checkin_rr_first_match": (
        "{team_name}: Your first match is {date} at {time}. "
        "Please arrive at least 30 mins early and check in at the desk."
    ),
    "checkin_slot_checkin": (
        "{team_name}: All matches in the prior time slot have started. "
        "Please come check in at the desk for your next match."
    ),
    "checkin_post_match_next": (
        "{team_name}: Your next match is {date} at {time}. "
        "Please check in at the desk for your next match."
    ),
    "checkin_court_assigned": (
        "{team_name}: Court assigned. Please go to your court."
    ),
}
