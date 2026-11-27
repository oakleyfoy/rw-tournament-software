"""Temporary court openings that do not change the configured schedule."""

from datetime import date, datetime, time
from typing import Optional

from sqlmodel import Field, SQLModel


class CourtAvailabilityOverride(SQLModel, table=True):
    """One court, one tournament day, one time range.

    The original ScheduleSlot.is_active flag stays untouched so staff can
    restore the configured schedule. A fresh tournament copy does not copy
    these rows.
    """

    __tablename__ = "courtavailabilityoverride"

    id: Optional[int] = Field(default=None, primary_key=True)
    tournament_id: int = Field(foreign_key="tournament.id", index=True)
    schedule_version_id: int = Field(foreign_key="scheduleversion.id", index=True)
    day_date: date = Field(index=True)
    court_number: int
    start_time: time
    end_time: time
    created_at: datetime = Field(default_factory=datetime.utcnow)


class CourtAvailabilityClosure(SQLModel, table=True):
    """A temporary closure of a court that the schedule says is available.

    Closing does not change ScheduleSlot.is_active. Restore deletes these
    rows and the court returns to its configured schedule.
    """

    __tablename__ = "courtavailabilityclosure"

    id: Optional[int] = Field(default=None, primary_key=True)
    tournament_id: int = Field(foreign_key="tournament.id", index=True)
    schedule_version_id: int = Field(foreign_key="scheduleversion.id", index=True)
    day_date: date = Field(index=True)
    court_number: int
    start_time: time
    end_time: time
    created_at: datetime = Field(default_factory=datetime.utcnow)
