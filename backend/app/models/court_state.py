from datetime import datetime
from typing import Optional

from sqlalchemy import UniqueConstraint as SAUniqueConstraint
from sqlmodel import Field, SQLModel


class TournamentCourtState(SQLModel, table=True):
    __tablename__ = "tournamentcourtstate"
    __table_args__ = (
        SAUniqueConstraint("tournament_id", "court_label", name="uq_courtstate_tournament_court"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    tournament_id: int = Field(foreign_key="tournament.id", index=True)
    court_label: str
    is_closed: bool = Field(default=False)
    note: Optional[str] = Field(default=None)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
