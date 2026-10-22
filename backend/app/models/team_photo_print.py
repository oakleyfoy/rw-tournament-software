"""Watermark settings and print-ready copies for official team photographs.

The official JPEG in `team_official_photo` is never replaced. Print files and
the optional custom logo live under a separate storage prefix.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import UniqueConstraint as SAUniqueConstraint
from sqlmodel import Field, SQLModel


class TournamentPhotoWatermark(SQLModel, table=True):
    """One default watermark design for every team photo in a tournament."""

    __tablename__ = "tournament_photo_watermark"
    __table_args__ = (
        SAUniqueConstraint("tournament_id", name="uq_tournament_photo_watermark"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    tournament_id: int = Field(foreign_key="tournament.id", index=True)
    settings_json: str
    custom_logo_key: Optional[str] = Field(default=None, max_length=300)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class TeamPhotoWatermark(SQLModel, table=True):
    """A per-photo override and review mark. Missing row means use the tournament default."""

    __tablename__ = "team_photo_watermark"
    __table_args__ = (
        SAUniqueConstraint("tournament_id", "team_id", name="uq_team_photo_watermark"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    tournament_id: int = Field(foreign_key="tournament.id", index=True)
    team_id: int = Field(foreign_key="team.id", index=True)
    settings_json: Optional[str] = Field(default=None)
    reviewed: bool = Field(default=False)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class TeamPhotoPrint(SQLModel, table=True):
    """The latest print-ready JPEG generated for one team and print size."""

    __tablename__ = "team_photo_print"
    __table_args__ = (
        SAUniqueConstraint("tournament_id", "team_id", "print_size", name="uq_team_photo_print"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    tournament_id: int = Field(foreign_key="tournament.id", index=True)
    team_id: int = Field(foreign_key="team.id", index=True)
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
