"""Player identity and SMS consent state."""

from datetime import datetime, timezone
from typing import TYPE_CHECKING, List, Optional

from sqlmodel import Field, Relationship, SQLModel, UniqueConstraint

if TYPE_CHECKING:
    from app.models.team_player import TeamPlayer


class Player(SQLModel, table=True):
    """Tournament-scoped player record used for SMS targeting and consent."""

    __tablename__ = "player"
    __table_args__ = (
        UniqueConstraint(
            "tournament_id",
            "phone_e164",
            name="uq_player_tournament_phone",
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    tournament_id: int = Field(foreign_key="tournament.id", index=True)

    full_name: str
    display_name: Optional[str] = Field(default=None)
    phone_e164: Optional[str] = Field(default=None, index=True)
    email: Optional[str] = Field(default=None, index=True)

    # Consent model:
    # - unknown: imported or created without explicit SMS consent action
    # - opted_in: explicit consent captured
    # - opted_out: explicit STOP/opt-out captured
    sms_consent_status: str = Field(default="unknown", index=True)
    sms_consent_source: Optional[str] = Field(default=None)
    sms_consent_updated_at: Optional[datetime] = Field(default=None)
    sms_consented_at: Optional[datetime] = Field(default=None)
    sms_opted_out_at: Optional[datetime] = Field(default=None)

    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    team_links: List["TeamPlayer"] = Relationship(back_populates="player")
