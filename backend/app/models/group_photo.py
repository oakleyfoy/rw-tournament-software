"""Tournament group photographs for the print center.

A group photograph belongs to the tournament only. It is not a team, player,
match, or division photograph, and it is not an official team photo.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import UniqueConstraint as SAUniqueConstraint
from sqlmodel import Field, SQLModel


class TournamentGroupPhoto(SQLModel, table=True):
    """One printable group photograph stored at full camera quality."""

    __tablename__ = "tournament_group_photo"
    __table_args__ = (
        SAUniqueConstraint("client_upload_id", name="uq_tournament_group_photo_upload"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    tournament_id: int = Field(foreign_key="tournament.id", index=True)
    storage_key: str = Field(max_length=300)
    content_type: str = Field(default="image/jpeg", max_length=40)
    byte_size: int = Field(default=0)
    photographer_user_id: Optional[int] = Field(default=None, foreign_key="user_account.id")
    client_upload_id: str = Field(max_length=80, index=True)
    captured_at: datetime = Field(default_factory=datetime.utcnow)
    settings_json: Optional[str] = Field(default=None)
    reviewed: bool = Field(default=False)


class TournamentGroupPhotoPrint(SQLModel, table=True):
    """The latest 4×6 print file for one group photograph."""

    __tablename__ = "tournament_group_photo_print"
    __table_args__ = (
        SAUniqueConstraint("group_photo_id", "print_size", name="uq_tournament_group_photo_print"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    tournament_id: int = Field(foreign_key="tournament.id", index=True)
    group_photo_id: int = Field(foreign_key="tournament_group_photo.id", index=True)
    print_size: str = Field(max_length=8)
    storage_key: str = Field(max_length=300)
    filename: str = Field(max_length=180)
    byte_size: int = Field(default=0)
    width: int = Field(default=0)
    height: int = Field(default=0)
    source_width: int = Field(default=0)
    source_height: int = Field(default=0)
    low_resolution: bool = Field(default=False)
    quantity: int = Field(default=1)
    settings_json: str = Field(default="")
    created_at: datetime = Field(default_factory=datetime.utcnow)
