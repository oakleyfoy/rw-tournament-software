"""
Single source of truth for tournament capacity (court-minutes).

Exactly one return path:
- ADVANCED (use_time_windows=True): sum of (end_time - start_time) * courts_available for each ACTIVE time window.
- SIMPLE: sum of (end_time - start_time) * courts_available for each active tournament day.

No adding, no averaging, no fallback, no cached override.
When Advanced: days/courts/hours_per_day are ignored.
"""
from dataclasses import dataclass
from typing import List

from sqlmodel import Session, select

from app.models.tournament import Tournament
from app.models.tournament_day import TournamentDay
from app.models.tournament_time_window import TournamentTimeWindow


@dataclass
class ResolvedCapacity:
    total_court_minutes: int
    active_days_count: int
    errors: List[str]


def _minutes_between(start_time, end_time) -> int:
    """Minutes from start_time to end_time (same-day)."""
    start_min = start_time.hour * 60 + start_time.minute
    end_min = end_time.hour * 60 + end_time.minute
    return end_min - start_min if end_min > start_min else 0


def resolve_tournament_capacity(session: Session, tournament_id: int) -> ResolvedCapacity:
    """
    Single capacity resolver. One return path only.

    ADVANCED: capacity = sum of (window duration * courts) for active time windows.
    SIMPLE: capacity = sum of (day duration * courts) for active tournament days.

    Guard: Advanced mode with zero active time windows raises an error (no silent fallback).
    """
    use_time_windows = session.exec(
        select(Tournament.use_time_windows).where(Tournament.id == tournament_id)
    ).one()

    errors: List[str] = []
    total_court_minutes = 0
    active_days_count = 0

    if use_time_windows:
        # ADVANCED: only active time windows; Simple fields are fully ignored
        active_windows = session.exec(
            select(TournamentTimeWindow)
            .where(
                TournamentTimeWindow.tournament_id == tournament_id,
                TournamentTimeWindow.is_active == True,
            )
            .order_by(TournamentTimeWindow.day_date, TournamentTimeWindow.start_time)
        ).all()

        if len(active_windows) == 0:
            errors.append("Advanced mode requires at least one active time window")
            return ResolvedCapacity(
                total_court_minutes=0,
                active_days_count=0,
                errors=errors,
            )

        seen_dates = set()
        for w in active_windows:
            if not w.start_time or not w.end_time:
                errors.append(f"Start/end time not set on time window (day {w.day_date})")
                continue
            if w.courts_available < 1:
                errors.append(f"Courts not set on time window (day {w.day_date})")
                continue
            mins = _minutes_between(w.start_time, w.end_time)
            if mins <= 0:
                errors.append(f"End time must be after start time on time window (day {w.day_date})")
                continue
            total_court_minutes += mins * w.courts_available
            seen_dates.add(w.day_date)
        active_days_count = len(seen_dates)
    else:
        # SIMPLE: only active tournament days; time windows are ignored
        active_days = session.exec(
            select(TournamentDay)
            .where(TournamentDay.tournament_id == tournament_id, TournamentDay.is_active)
            .order_by(TournamentDay.date)
        ).all()
        active_days_count = len(active_days)

        for day in active_days:
            if not day.start_time or not day.end_time:
                errors.append(f"Start time or end time not set on active day {day.date}")
                continue
            if day.courts_available < 1:
                errors.append(f"Courts not set on active day {day.date}")
                continue
            mins = _minutes_between(day.start_time, day.end_time)
            if mins <= 0:
                errors.append(f"End time must be greater than start time on active day {day.date}")
                continue
            total_court_minutes += mins * day.courts_available

    if active_days_count == 0:
        errors.append(
            "At least one active time window is required"
            if use_time_windows
            else "At least one active day is required"
        )
    if total_court_minutes == 0:
        errors.append("Total court minutes must be greater than 0")

    return ResolvedCapacity(
        total_court_minutes=total_court_minutes,
        active_days_count=active_days_count,
        errors=errors,
    )
