from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, Optional

from sqlalchemy import JSON, UniqueConstraint as SAUniqueConstraint
from sqlmodel import Column, Field, Relationship, SQLModel

if TYPE_CHECKING:
    from app.models.event import Event
    from app.models.match_assignment import MatchAssignment
    from app.models.schedule_version import ScheduleVersion
    from app.models.team import Team
    from app.models.tournament import Tournament


class Match(SQLModel, table=True):
    __table_args__ = (SAUniqueConstraint("schedule_version_id", "match_code", name="uq_match_version_code"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    tournament_id: int = Field(foreign_key="tournament.id")
    event_id: int = Field(foreign_key="event.id")
    schedule_version_id: int = Field(foreign_key="scheduleversion.id")
    match_code: str
    match_type: str  # "WF" | "MAIN" | "CONSOLATION" | "PLACEMENT"
    round_number: int
    round_index: int = Field(default=1)  # Index within match_type (1..N)
    sequence_in_round: int
    duration_minutes: int
    consolation_tier: Optional[int] = Field(default=None)  # 1 for Tier 1, 2 for Tier 2, None for non-consolation
    placement_type: Optional[str] = Field(default=None)  # "MAIN_SF_LOSERS" | "CONS_R1_WINNERS" | "CONS_R1_LOSERS"

    # Team assignments (nullable - populated by team injection)
    team_a_id: Optional[int] = Field(default=None, foreign_key="team.id")
    team_b_id: Optional[int] = Field(default=None, foreign_key="team.id")

    # Placeholder text (always present, used when team_ids are null or for display)
    placeholder_side_a: str
    placeholder_side_b: str

    # Day-Targeting V1: Preferred day of week (0=Monday, 6=Sunday)
    preferred_day: Optional[int] = Field(default=None)  # 0-6 or null

    # Phase 4 advancement: upstream match → team slot (deterministic; WF/MAIN bracket)
    source_match_a_id: Optional[int] = Field(default=None, foreign_key="match.id")
    source_match_b_id: Optional[int] = Field(default=None, foreign_key="match.id")
    source_a_role: Optional[str] = Field(default=None)  # "WINNER" | "LOSER" (MVP: WINNER only)
    source_b_role: Optional[str] = Field(default=None)

    status: str = Field(default="unscheduled")  # "unscheduled" | "scheduled" | "complete" | "cancelled"
    created_at: datetime = Field(default_factory=datetime.utcnow)

    # Phase 4 runtime (do not affect scheduling; immutable assignments respected)
    runtime_status: str = Field(default="SCHEDULED")  # SCHEDULED | IN_PROGRESS | FINAL
    score_json: Optional[Dict[str, Any]] = Field(default=None, sa_column=Column(JSON, nullable=True))
    winner_team_id: Optional[int] = Field(default=None, foreign_key="team.id")
    started_at: Optional[datetime] = Field(default=None)
    completed_at: Optional[datetime] = Field(default=None)

    # Relationships
    tournament: "Tournament" = Relationship(back_populates="matches")
    event: "Event" = Relationship(back_populates="matches")
    schedule_version: "ScheduleVersion" = Relationship(back_populates="matches")
    assignment: Optional["MatchAssignment"] = Relationship(
        back_populates="match", sa_relationship_kwargs={"uselist": False}
    )

    # Team relationships (nullable)
    team_a: Optional["Team"] = Relationship(
        back_populates="matches_as_team_a", sa_relationship_kwargs={"foreign_keys": "Match.team_a_id"}
    )
    team_b: Optional["Team"] = Relationship(
        back_populates="matches_as_team_b", sa_relationship_kwargs={"foreign_keys": "Match.team_b_id"}
    )
