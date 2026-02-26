from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Column, Field, SQLModel, Text


class PolicyRun(SQLModel, table=True):
    __tablename__ = "policyrun"

    id: Optional[int] = Field(default=None, primary_key=True)
    tournament_id: int = Field(foreign_key="tournament.id", index=True)
    schedule_version_id: int = Field(foreign_key="scheduleversion.id", index=True)
    day_date: Optional[str] = Field(default=None)
    policy_version: str = Field(default="sequence_v1")
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    input_hash: str = Field(max_length=16)
    output_hash: str = Field(max_length=16)
    ok: bool = Field(default=True)
    total_assigned: int = Field(default=0)
    total_failed: int = Field(default=0)
    total_reserved_spares: int = Field(default=0)
    duration_ms: int = Field(default=0)
    snapshot_json: Optional[str] = Field(default=None, sa_column=Column(Text))
