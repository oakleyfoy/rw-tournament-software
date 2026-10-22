"""Durable photo-saved SMS notices and unguessable photo links.

One row is the team's share link. One row per recipient is the delivery record.
The share token is not a storage key, a player id, or a phone number.
"""

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import UniqueConstraint as SAUniqueConstraint
from sqlmodel import Field, SQLModel

NOTICE_READY = "team_photo_ready"
NOTICE_DUPLICATE = "team_photo_ready_duplicate"
NOTICE_NO_PHONE = "team_photo_ready_no_phone"

STATUS_PENDING = "PENDING"
STATUS_QUEUED = "QUEUED"
STATUS_SENT = "SENT"
STATUS_DELIVERED = "DELIVERED"
STATUS_FAILED = "FAILED"
STATUS_SKIPPED_NO_CONSENT = "SKIPPED_NO_CONSENT"
STATUS_SKIPPED_OPT_OUT = "SKIPPED_OPT_OUT"
STATUS_SKIPPED_INVALID_NUMBER = "SKIPPED_INVALID_NUMBER"
STATUS_SKIPPED_DUPLICATE = "SKIPPED_DUPLICATE"
STATUS_SKIPPED_TEST_MODE = "SKIPPED_TEST_MODE"
STATUS_SKIPPED_DISABLED = "SKIPPED_DISABLED"
STATUS_SKIPPED_TEXTS_OFF = "SKIPPED_TEXTS_OFF"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TeamPhotoShare(SQLModel, table=True):
    """One private link for a team's official photograph.

    Replacing the photograph keeps this token. The page shows the current
    official JPEG. Deleting the photograph revokes the token. The link expires
    one year after it is issued so players have time to save the picture.
    """

    __tablename__ = "team_photo_share"
    __table_args__ = (SAUniqueConstraint("team_id", name="uq_team_photo_share_team"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    tournament_id: int = Field(foreign_key="tournament.id", index=True)
    team_id: int = Field(foreign_key="team.id", index=True)
    # Not a foreign key: the official photo row can be deleted while this link
    # stays revoked for audit. The page reads the current photo, not this id.
    photo_id: int = Field(index=True)
    token: str = Field(max_length=128, unique=True, index=True)
    expires_at: datetime
    revoked_at: Optional[datetime] = Field(default=None)
    created_at: datetime = Field(default_factory=_utcnow)


class TeamPhotoSmsNotice(SQLModel, table=True):
    """One recipient of one team's first official-photo text.

    Uniqueness is the team, the notification type, and the normalized phone
    (or the player, when there is no phone). A later retake does not insert
    another sendable row.
    """

    __tablename__ = "team_photo_sms_notice"
    __table_args__ = (SAUniqueConstraint("idempotency_key", name="uq_team_photo_sms_idempotency"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    tournament_id: int = Field(foreign_key="tournament.id", index=True)
    team_id: int = Field(foreign_key="team.id", index=True)
    photo_id: int = Field(index=True)
    player_id: Optional[int] = Field(default=None, foreign_key="player.id", index=True)
    phone_e164: Optional[str] = Field(default=None, index=True)
    notice_type: str = Field(default=NOTICE_READY, max_length=64, index=True)
    idempotency_key: str = Field(max_length=200)
    status: str = Field(default=STATUS_PENDING, max_length=40, index=True)
    provider_sid: Optional[str] = Field(default=None, index=True)
    consent_status: Optional[str] = Field(default=None, max_length=40)
    consent_source: Optional[str] = Field(default=None, max_length=80)
    failure_code: Optional[str] = Field(default=None, max_length=80)
    failure_reason: Optional[str] = Field(default=None, max_length=300)
    retry_count: int = Field(default=0)
    next_attempt_at: datetime = Field(default_factory=_utcnow, index=True)
    last_attempt_at: Optional[datetime] = Field(default=None)
    created_at: datetime = Field(default_factory=_utcnow)
    sent_at: Optional[datetime] = Field(default=None)
    delivered_at: Optional[datetime] = Field(default=None)
