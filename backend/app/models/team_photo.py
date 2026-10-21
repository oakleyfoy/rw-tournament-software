"""Official tournament-team photographs and short-lived capture sessions.

Photos belong to the canonical team row (`team.id`) for one tournament event.
A later registration creates a new team row, so historical tournament photos
stay on the original team.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import UniqueConstraint as SAUniqueConstraint
from sqlmodel import Field, SQLModel


class TeamOfficialPhoto(SQLModel, table=True):
    """The single current official photograph for a tournament team."""

    __tablename__ = "team_official_photo"
    __table_args__ = (SAUniqueConstraint("team_id", name="uq_team_official_photo_team"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    team_id: int = Field(foreign_key="team.id", index=True)
    tournament_id: int = Field(foreign_key="tournament.id", index=True)
    storage_key: str = Field(max_length=300)
    content_type: str = Field(default="image/jpeg", max_length=40)
    byte_size: int = Field(default=0)
    photographer_user_id: Optional[int] = Field(default=None, foreign_key="user_account.id")
    last_client_upload_id: Optional[str] = Field(default=None, max_length=80, index=True)
    captured_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class TeamPhotoCapture(SQLModel, table=True):
    """A session photograph that is not the official team photo.

    Unselected captures are deleted when an official photo is chosen or the
    session is discarded.
    """

    __tablename__ = "team_photo_capture"
    __table_args__ = (SAUniqueConstraint("client_upload_id", name="uq_team_photo_capture_client_upload"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    team_id: int = Field(foreign_key="team.id", index=True)
    tournament_id: int = Field(foreign_key="tournament.id", index=True)
    session_id: str = Field(max_length=80, index=True)
    client_upload_id: str = Field(max_length=80)
    storage_key: str = Field(max_length=300)
    content_type: str = Field(default="image/jpeg", max_length=40)
    byte_size: int = Field(default=0)
    photographer_user_id: Optional[int] = Field(default=None, foreign_key="user_account.id")
    created_at: datetime = Field(default_factory=datetime.utcnow)


class PhotographerTournamentAccess(SQLModel, table=True):
    """Tournaments a photographer is allowed to photograph."""

    __tablename__ = "photographer_tournament_access"
    __table_args__ = (
        SAUniqueConstraint("user_id", "tournament_id", name="uq_photographer_tournament_access"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user_account.id", index=True)
    tournament_id: int = Field(foreign_key="tournament.id", index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
