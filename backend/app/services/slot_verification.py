"""Read-only court-slot verification against persisted config and generated slots."""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import date, time
from typing import Any, Optional

from sqlmodel import Session, select

from app.models.event import Event
from app.models.schedule_slot import ScheduleSlot
from app.models.schedule_version import ScheduleVersion
from app.models.tournament import Tournament
from app.models.tournament_day import TournamentDay
from app.models.tournament_time_window import TournamentTimeWindow


def slot_start_times(start: time, end: time, block_minutes: int) -> list[time]:
    """Mirror generate_slots: t = start; while t + block <= end; t += block."""
    if start is None or end is None or not block_minutes or block_minutes <= 0:
        return []
    start_minutes = start.hour * 60 + start.minute
    end_minutes = end.hour * 60 + end.minute
    if end_minutes <= start_minutes:
        return []
    starts: list[time] = []
    current = start_minutes
    while current + block_minutes <= end_minutes:
        starts.append(time(current // 60, current % 60))
        current += block_minutes
    return starts


def _event_slot_durations(event: Event) -> tuple[int, int]:
    wf_minutes = event.wf_block_minutes or 60
    standard_minutes = event.standard_block_minutes or 120
    if event.draw_plan_json:
        try:
            draw_plan = json.loads(event.draw_plan_json)
        except (TypeError, json.JSONDecodeError):
            draw_plan = {}
        timing = draw_plan.get("timing") if isinstance(draw_plan, dict) else {}
        if isinstance(timing, dict):
            candidate_wf = timing.get("wf_block_minutes")
            if isinstance(candidate_wf, int) and candidate_wf > 0:
                wf_minutes = candidate_wf
            candidate_standard = timing.get("standard_block_minutes")
            if isinstance(candidate_standard, int) and candidate_standard > 0:
                standard_minutes = candidate_standard
    return wf_minutes, standard_minutes


def _days_courts_block_minutes(session: Session, tournament_id: int, ordered_days: list[TournamentDay]) -> list[int]:
    events = session.exec(select(Event).where(Event.tournament_id == tournament_id)).all()
    wf_candidates: list[int] = []
    standard_candidates: list[int] = []
    for event in events:
        wf, std = _event_slot_durations(event)
        if wf > 0:
            wf_candidates.append(wf)
        if std > 0:
            standard_candidates.append(std)

    wf_block_minutes = min(wf_candidates) if wf_candidates else 60
    standard_block_minutes = max(standard_candidates) if standard_candidates else 120
    has_both = bool(wf_candidates and standard_candidates)

    blocks: list[int] = []
    for day_idx, _day in enumerate(ordered_days):
        if has_both and len(ordered_days) > 1:
            blocks.append(wf_block_minutes if day_idx == 0 else standard_block_minutes)
        elif standard_candidates:
            blocks.append(standard_block_minutes)
        else:
            blocks.append(wf_block_minutes)
    return blocks


def _period_payload(
    *,
    source_id: int,
    source_kind: str,
    day_date: date,
    start: time,
    end: time,
    courts: int,
    extra_courts: int,
    block_minutes: int,
    label: Optional[str],
    slots: list[ScheduleSlot],
) -> dict[str, Any]:
    starts = slot_start_times(start, end, block_minutes)
    total_courts = courts + extra_courts
    expected = len(starts) * total_courts
    start_set = set(starts)
    generated = 0
    for slot in slots:
        if not slot.is_active:
            continue
        if slot.day_date != day_date:
            continue
        if slot.start_time not in start_set:
            continue
        if slot.block_minutes != block_minutes:
            continue
        if slot.court_number < 1 or slot.court_number > total_courts:
            continue
        generated += 1
    return {
        "source_id": source_id,
        "source_kind": source_kind,
        "day_date": day_date,
        "start_time": start,
        "end_time": end,
        "courts": total_courts,
        "extra_courts": extra_courts,
        "block_minutes": block_minutes,
        "blocks_per_court": len(starts),
        "label": label,
        "expected_slots": expected,
        "generated_slots": generated,
        "status": "verified" if expected == generated else "mismatch",
    }


def build_slot_verification(session: Session, tournament_id: int, version_id: int) -> dict[str, Any]:
    tournament = session.get(Tournament, tournament_id)
    if not tournament:
        raise ValueError("Tournament not found")
    version = session.get(ScheduleVersion, version_id)
    if not version or version.tournament_id != tournament_id:
        raise ValueError("Schedule version not found")

    source = "time_windows" if tournament.use_time_windows else "days_courts"
    slots = session.exec(select(ScheduleSlot).where(ScheduleSlot.schedule_version_id == version_id)).all()
    periods: list[dict[str, Any]] = []

    if source == "time_windows":
        windows = session.exec(
            select(TournamentTimeWindow)
            .where(TournamentTimeWindow.tournament_id == tournament_id, TournamentTimeWindow.is_active)
            .order_by(TournamentTimeWindow.day_date, TournamentTimeWindow.start_time, TournamentTimeWindow.end_time)
        ).all()
        for window in windows:
            if window.id is None:
                continue
            periods.append(
                _period_payload(
                    source_id=window.id,
                    source_kind="time_window",
                    day_date=window.day_date,
                    start=window.start_time,
                    end=window.end_time,
                    courts=window.courts_available,
                    extra_courts=window.extra_courts or 0,
                    block_minutes=window.block_minutes,
                    label=window.label,
                    slots=slots,
                )
            )
    else:
        active_days = session.exec(
            select(TournamentDay)
            .where(TournamentDay.tournament_id == tournament_id, TournamentDay.is_active)
            .order_by(TournamentDay.date)
        ).all()
        ordered = sorted(active_days, key=lambda day: day.date)
        block_minutes_list = _days_courts_block_minutes(session, tournament_id, ordered)
        for day, block_minutes in zip(ordered, block_minutes_list, strict=True):
            if day.id is None or not day.start_time or not day.end_time or day.courts_available < 1:
                continue
            periods.append(
                _period_payload(
                    source_id=day.id,
                    source_kind="tournament_day",
                    day_date=day.date,
                    start=day.start_time,
                    end=day.end_time,
                    courts=day.courts_available,
                    extra_courts=0,
                    block_minutes=block_minutes,
                    label=None,
                    slots=slots,
                )
            )

    by_day: dict[date, list[dict[str, Any]]] = defaultdict(list)
    for period in periods:
        by_day[period["day_date"]].append(period)

    days = []
    for day_date in sorted(by_day):
        day_periods = by_day[day_date]
        expected = sum(period["expected_slots"] for period in day_periods)
        generated = sum(period["generated_slots"] for period in day_periods)
        days.append(
            {
                "day_date": day_date,
                "expected_slots": expected,
                "generated_slots": generated,
                "status": "verified" if expected == generated else "mismatch",
                "periods": day_periods,
            }
        )

    expected_total = sum(day["expected_slots"] for day in days)
    generated_total = sum(day["generated_slots"] for day in days)
    return {
        "source": source,
        "expected_slots": expected_total,
        "generated_slots": generated_total,
        "status": "verified" if expected_total == generated_total else "mismatch",
        "days": days,
    }
