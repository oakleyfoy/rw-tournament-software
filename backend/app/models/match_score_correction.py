"""Staff corrections to a completed match score.

The original completion timestamp stays on the match. Each correction keeps
the previous score and winner beside the new ones.
"""

from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class MatchScoreCorrection(SQLModel, table=True):
    __tablename__ = "matchscorecorrection"

    id: Optional[int] = Field(default=None, primary_key=True)
    tournament_id: int = Field(foreign_key="tournament.id", index=True)
    schedule_version_id: int = Field(foreign_key="scheduleversion.id", index=True)
    match_id: int = Field(foreign_key="match.id", index=True)
    previous_score: Optional[str] = None
    corrected_score: Optional[str] = None
    previous_winner_team_id: Optional[int] = None
    corrected_winner_team_id: Optional[int] = None
    previous_winner_name: Optional[str] = None
    corrected_winner_name: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    created_by_user_id: Optional[int] = Field(default=None, foreign_key="user_account.id")
    created_by_name: Optional[str] = Field(default=None, max_length=150)
