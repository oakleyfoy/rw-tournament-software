from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class TournamentImport(SQLModel, table=True):
    __tablename__ = "tournament_import"

    id: Optional[int] = Field(default=None, primary_key=True)
    tournament_id: int = Field(foreign_key="tournament.id", index=True)
    organization_slug: str = Field(default="rw")
    source_tournament_id: int = Field(index=True)
    event_name: str
    event_date: str
    imported_at: datetime = Field(default_factory=datetime.utcnow)
    source_updated_at: Optional[str] = None
    source_version: Optional[str] = None
    source_team_count: int = 0
    source_hash: str
    snapshot_json: str
    waitlist_json: str = "[]"
    validation_status: str = "ok"
    validation_issues_json: str = "[]"
    refresh_diff_json: Optional[str] = None
    plan_status: str = "imported"
    approved_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class TournamentDrawPlan(SQLModel, table=True):
    __tablename__ = "tournament_draw_plan"

    id: Optional[int] = Field(default=None, primary_key=True)
    import_id: int = Field(foreign_key="tournament_import.id", index=True)
    tournament_id: int = Field(foreign_key="tournament.id", index=True)
    draw_kind: str
    draw_label: str
    team_count: int
    option_key: str
    is_recommended: bool = False
    approved: bool = False
    option_json: str
    brackets_json: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
