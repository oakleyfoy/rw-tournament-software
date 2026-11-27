"""Finish one scheduled time slot on a duplicated test tournament.

Every saved result goes through the desk finalize route. Real tournaments are
rejected even when their name contains "(Copy)".
"""

from __future__ import annotations

import random
import threading
from datetime import date, datetime, time
from typing import Optional

from fastapi import HTTPException
from sqlmodel import Session, select

from app.models.match import Match
from app.models.schedule_version import ScheduleVersion
from app.models.team import Team
from app.models.tournament import Tournament
from app.services.dashboard_progression import (
    _assignment_rows,
    _closed_labels,
    _court_closed,
    _day_run,
    _minutes,
    _team_busy,
    is_tournament_copy,
    operational_simulated_at,
    set_test_clock,
)
from app.services.preassigned_dispatch import _feeders_final
from app.services.score_parser import random_valid_score_for_match_type, validate_score_for_match_type

_locks: dict[int, threading.Lock] = {}
_locks_guard = threading.Lock()


def simulation_allowed(tournament: Tournament) -> bool:
    """A duplicate identified by the copy marker and the source tournament id."""
    return bool(
        is_tournament_copy(tournament)
        and getattr(tournament, "duplicated_from_tournament_id", None) is not None
    )


def _require_simulation(tournament: Tournament) -> None:
    if simulation_allowed(tournament):
        return
    raise ValueError("Result simulation is only available on a duplicated test tournament")


def _lock(tournament_id: int) -> threading.Lock:
    with _locks_guard:
        lock = _locks.get(tournament_id)
        if lock is None:
            lock = threading.Lock()
            _locks[tournament_id] = lock
        return lock


def _parse_clock(value: str) -> time:
    parts = value.strip().split(":")
    if len(parts) < 2:
        raise ValueError("Time slot must be HH:MM")
    return time(int(parts[0]), int(parts[1]), int(parts[2]) if len(parts) > 2 else 0)


def _clock_label(value: time) -> str:
    hour = value.hour % 12 or 12
    suffix = "AM" if value.hour < 12 else "PM"
    return f"{hour}:{value.minute:02d} {suffix}"


def _team_name(session: Session, team_id: Optional[int]) -> str:
    if team_id is None:
        return "Unresolved"
    team = session.get(Team, team_id)
    if team is None:
        return f"Team {team_id}"
    return team.display_name or team.name or f"Team {team_id}"


def _local_minutes(tournament: Tournament, day: date, simulated: Optional[datetime]) -> int:
    from app.services.dashboard_progression import tournament_local_now, _as_aware

    if simulated is not None:
        local_now = tournament_local_now(tournament, _as_aware(tournament, simulated))
    else:
        local_now = tournament_local_now(tournament)
    if local_now.date() > day:
        return 24 * 60
    if local_now.date() < day:
        return -1
    return _minutes(local_now.time())


def slot_board(session: Session, tournament: Tournament, version: ScheduleVersion, day: date) -> dict:
    _require_simulation(tournament)
    if version.id is None:
        raise ValueError("Schedule version is missing")
    rows = _assignment_rows(session, version.id, day)
    grouped: dict[time, list[tuple[Match, object]]] = {}
    for match, slot in rows:
        if slot.start_time is None:
            continue
        grouped.setdefault(slot.start_time, []).append((match, slot))
    slots = []
    for start in sorted(grouped):
        matches = grouped[start]
        completed = sum(1 for match, _slot in matches if (match.runtime_status or "").upper() == "FINAL")
        active = sum(1 for match, _slot in matches if (match.runtime_status or "").upper() in {"IN_PROGRESS", "PAUSED"})
        slots.append({
            "start_time": start.isoformat(),
            "label": _clock_label(start),
            "match_count": len(matches),
            "completed": completed,
            "active": active,
            "remaining": len(matches) - completed,
        })
    run = _day_run(session, version.id, day)
    return {
        "day_date": day.isoformat(),
        "day_started": run is not None,
        "slots": slots,
    }


def _block_reason(
    session: Session,
    version_id: int,
    match: Match,
    slot,
    court_rows: list[tuple[Match, object]],
    *,
    day_started: bool,
    now_minutes: int,
    closed: set[str],
) -> Optional[str]:
    status = (match.runtime_status or "SCHEDULED").upper()
    if status == "FINAL":
        return None
    if not day_started:
        return "Tournament day not started"
    if match.team_a_id is None or match.team_b_id is None:
        return "Both teams not resolved"
    if not _feeders_final(session, match):
        return "Awaiting previous match result"
    earlier = [
        other
        for other, other_slot in court_rows
        if other.id != match.id
        and (other_slot.start_time or time.min) < (slot.start_time or time.min)
        and (other.runtime_status or "SCHEDULED").upper() != "FINAL"
    ]
    if earlier:
        return "Earlier match still unfinished"
    playing = status in {"IN_PROGRESS", "PAUSED"}
    from app.services.court_availability import slot_effectively_active

    if not playing and (_court_closed(closed, slot) or not slot_effectively_active(session, slot)):
        return "Assigned court unavailable"
    team_ids = {team_id for team_id in (match.team_a_id, match.team_b_id) if team_id}
    if _team_busy(session, version_id, team_ids, match.id or 0):
        return "Player already playing another match"
    scheduled = _minutes(slot.start_time) if slot.start_time else None
    if not playing and (scheduled is None or now_minutes < scheduled - 15):
        return "Match not yet active"
    return None


def simulate_time_slot(
    session: Session,
    tournament: Tournament,
    version: ScheduleVersion,
    day: date,
    slot_time: str,
    *,
    rng: Optional[random.Random] = None,
) -> dict:
    _require_simulation(tournament)
    if tournament.id is None or version.id is None:
        raise ValueError("Tournament is missing")
    start = _parse_clock(slot_time)
    lock = _lock(tournament.id)
    if not lock.acquire(blocking=False):
        raise ValueError("A simulation is already running for this tournament")
    try:
        return _simulate_locked(session, tournament, version, day, start, rng or random.Random())
    finally:
        lock.release()


def _simulate_locked(session, tournament, version, day, start: time, rng: random.Random) -> dict:
    from app.routes.desk import FinalizeRequest, finalize_match

    rows = [
        (match, slot)
        for match, slot in _assignment_rows(session, version.id, day)
        if slot.start_time == start
    ]
    rows.sort(key=lambda pair: (pair[1].court_number or 0, pair[0].id or 0))
    by_court: dict[int, list] = {}
    for match, slot in _assignment_rows(session, version.id, day):
        by_court.setdefault(slot.court_number, []).append((match, slot))
    run = _day_run(session, version.id, day)
    day_started = run is not None
    simulated = operational_simulated_at(run) if run is not None else None
    now_minutes = _local_minutes(tournament, day, simulated)
    closed = _closed_labels(session, tournament.id or 0)
    completed = skipped = blocked = failed = 0
    notifications = []
    results = []
    for match, slot in rows:
        session.refresh(match)
        status = (match.runtime_status or "SCHEDULED").upper()
        court = slot.court_label or str(slot.court_number)
        team1 = _team_name(session, match.team_a_id)
        team2 = _team_name(session, match.team_b_id)
        base = {
            "match_id": match.id,
            "match_code": match.match_code,
            "court": court,
            "team1": team1,
            "team2": team2,
            "winner": None,
            "score": None,
            "reason": None,
        }
        if status == "FINAL":
            skipped += 1
            results.append({**base, "status": "skipped", "score": _existing_score(match), "reason": "Match already completed"})
            continue
        reason = _block_reason(
            session,
            version.id,
            match,
            slot,
            by_court.get(slot.court_number, []),
            day_started=day_started,
            now_minutes=now_minutes,
            closed=closed,
        )
        if reason:
            blocked += 1
            results.append({**base, "status": "blocked", "reason": reason})
            continue
        team_a_wins = rng.random() < 0.5
        winner_id = match.team_a_id if team_a_wins else match.team_b_id
        score = random_valid_score_for_match_type(
            match.match_type,
            team_a_wins=True,
            rng=rng,
            match_code=match.match_code,
        )
        ok, message = validate_score_for_match_type(score, match.match_type, match.match_code)
        if not ok or winner_id is None:
            failed += 1
            results.append({**base, "status": "failed", "reason": message or "Could not build a valid score"})
            continue
        try:
            response = finalize_match(
                tournament.id,
                match.id,
                FinalizeRequest(
                    version_id=version.id,
                    score=score,
                    winner_team_id=winner_id,
                    send_automation_texts=False,
                    include_sms_preview=True,
                ),
                session,
            )
        except HTTPException as exc:
            detail = exc.detail if isinstance(exc.detail, str) else "Score save failed"
            if exc.status_code == 409:
                skipped += 1
                results.append({**base, "status": "skipped", "reason": detail})
            else:
                failed += 1
                results.append({**base, "status": "failed", "reason": detail})
            continue
        except Exception as exc:
            failed += 1
            results.append({**base, "status": "failed", "reason": str(exc) or "Score save failed"})
            continue
        completed += 1
        preview = getattr(response, "sms_preview", None)
        prepared = []
        if preview is not None:
            for recipient in list(preview.recipients or []):
                prepared.append({
                    "team_name": recipient.team_name,
                    "player_name": recipient.player_name,
                    "message": recipient.message,
                })
        notifications.extend(prepared)
        results.append({
            **base,
            "status": "completed",
            "winner": team1 if team_a_wins else team2,
            "score": score,
            "notifications": prepared,
        })
    return {
        "day_date": day.isoformat(),
        "slot_label": _clock_label(start),
        "completed": completed,
        "skipped": skipped,
        "blocked": blocked,
        "failed": failed,
        "notification_count": len(notifications),
        "results": results,
    }


def _existing_score(match: Match) -> Optional[str]:
    raw = match.score_json or {}
    if isinstance(raw, dict):
        return raw.get("display") or raw.get("actual")
    return str(raw) if raw else None


def advance_to_next_slot(
    session: Session,
    tournament: Tournament,
    version: ScheduleVersion,
    day: date,
    slot_time: str,
) -> dict:
    _require_simulation(tournament)
    if version.id is None:
        raise ValueError("Schedule version is missing")
    selected = _parse_clock(slot_time)
    from app.services.court_availability import effectively_open_slot_ids

    open_slots = effectively_open_slot_ids(session, version.id, day)
    starts = sorted({
        slot.start_time
        for _match, slot in _assignment_rows(session, version.id, day)
        if slot.start_time is not None and slot.id in open_slots
    })
    later = [start for start in starts if start > selected]
    if not later:
        raise ValueError("There is no later time slot on this day")
    nxt = later[0]
    run = set_test_clock(session, tournament, version, day, clock_time=nxt)
    session.commit()
    return {
        "day_date": day.isoformat(),
        "slot_label": _clock_label(nxt),
        "simulated_at": run.simulated_at.isoformat() if run.simulated_at else None,
    }
