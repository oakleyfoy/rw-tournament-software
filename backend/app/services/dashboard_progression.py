"""Server-side automatic match starts for a started Dashboard day.

Designated-court matches stay on their assigned court. This service only
activates the earliest unfinished match on that court when the day has been
started and every eligibility rule is already satisfied.
"""

from __future__ import annotations

import logging
import os
import sys
import threading
import time as time_module
from datetime import date, datetime, time, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from sqlmodel import Session, select

from app.models.court_state import TournamentCourtState
from app.models.desk_day_run import DeskDayRun
from app.models.event import Event
from app.models.match import Match
from app.models.match_assignment import MatchAssignment
from app.models.match_checkin import MatchCheckIn
from app.models.match_player_checkin import MatchPlayerCheckIn
from app.models.schedule_slot import ScheduleSlot
from app.models.schedule_version import ScheduleVersion
from app.models.team_player import TeamPlayer
from app.models.tournament import Tournament
from app.services.court_assignment_mode import is_preassigned
from app.services.preassigned_dispatch import _feeders_final, court_dispatch_lock

logger = logging.getLogger(__name__)

EARLY_MINUTES = 15
LIVE = {"IN_PROGRESS", "PAUSED"}
_runner_started = False


def auto_start_decision(
    *,
    day_started: bool,
    paused: bool,
    court_closed: bool,
    slot_active: bool,
    status: str,
    teams_known: bool,
    feeders_final: bool,
    participant_busy: bool,
    scheduled_minutes: Optional[int],
    now_minutes: Optional[int],
) -> tuple[bool, str]:
    """Return whether this one match may start, and the staff-facing reason."""
    if not day_started:
        return False, "Day has not started"
    if paused:
        return False, "Automatic progression is paused"
    current = (status or "SCHEDULED").upper()
    if current in {"FINAL", "IN_PROGRESS", "PAUSED"}:
        return False, current
    if court_closed:
        return False, "Court is closed"
    if not slot_active:
        return False, "Court is unavailable"
    if not teams_known or not feeders_final:
        return False, "Awaiting result"
    if participant_busy:
        return False, "Player is on another court"
    if scheduled_minutes is None or now_minutes is None:
        return False, "Scheduled time is missing"
    if now_minutes < scheduled_minutes - EARLY_MINUTES:
        return False, "Not yet in the release window"
    return True, "Eligible to start"


def _minutes(value: time) -> int:
    return value.hour * 60 + value.minute


def is_tournament_copy(tournament: Tournament) -> bool:
    """Copies keep the published dates and must not text the original players."""
    return "(Copy)" in (tournament.name or "")


def tournament_local_now(tournament: Tournament, now: Optional[datetime] = None) -> datetime:
    zone_name = tournament.timezone or "UTC"
    try:
        zone = ZoneInfo(zone_name)
    except Exception:
        zone = ZoneInfo("UTC")
    current = now or datetime.now(zone)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc).astimezone(zone)
    else:
        current = current.astimezone(zone)
    return current


def _day_run(session: Session, version_id: int, day: date) -> Optional[DeskDayRun]:
    return session.exec(
        select(DeskDayRun).where(
            DeskDayRun.schedule_version_id == version_id,
            DeskDayRun.day_date == day,
        )
    ).first()


def day_states(session: Session, version_id: int) -> list[DeskDayRun]:
    return list(
        session.exec(select(DeskDayRun).where(DeskDayRun.schedule_version_id == version_id)).all()
    )


def arrived_team_ids(session: Session, version_id: int) -> list[int]:
    """Teams whose players have checked in anywhere in this schedule version."""
    arrived: set[int] = set()
    team_rows = session.exec(
        select(MatchCheckIn).where(
            MatchCheckIn.schedule_version_id == version_id,
            MatchCheckIn.team_checked_in == True,  # noqa: E712
        )
    ).all()
    for row in team_rows:
        if row.team_id:
            arrived.add(row.team_id)

    checked = session.exec(
        select(MatchPlayerCheckIn).where(
            MatchPlayerCheckIn.schedule_version_id == version_id,
            MatchPlayerCheckIn.checked_in == True,  # noqa: E712
        )
    ).all()
    players_by_team: dict[int, set[int]] = {}
    for row in checked:
        if row.team_id and row.player_id:
            players_by_team.setdefault(row.team_id, set()).add(row.player_id)
    for team_id, player_ids in players_by_team.items():
        roster = session.exec(select(TeamPlayer).where(TeamPlayer.team_id == team_id)).all()
        needed = {row.player_id for row in roster if row.player_id}
        if needed and needed <= player_ids:
            arrived.add(team_id)
    return sorted(arrived)


def _closed_labels(session: Session, tournament_id: int) -> set[str]:
    rows = session.exec(
        select(TournamentCourtState).where(
            TournamentCourtState.tournament_id == tournament_id,
            TournamentCourtState.is_closed == True,  # noqa: E712
        )
    ).all()
    return {row.court_label.strip().lower() for row in rows if row.court_label}


def _court_closed(labels: set[str], slot: ScheduleSlot) -> bool:
    candidates = {slot.court_label.strip().lower(), str(slot.court_number).strip().lower()}
    return bool(candidates & labels)


def _assignment_rows(session: Session, version_id: int, day: date) -> list[tuple[Match, ScheduleSlot]]:
    slots = session.exec(
        select(ScheduleSlot).where(
            ScheduleSlot.schedule_version_id == version_id,
            ScheduleSlot.day_date == day,
        )
    ).all()
    slot_by_id = {slot.id: slot for slot in slots if slot.id is not None}
    if not slot_by_id:
        return []
    assignments = session.exec(
        select(MatchAssignment).where(
            MatchAssignment.schedule_version_id == version_id,
            MatchAssignment.slot_id.in_(list(slot_by_id)),  # type: ignore[arg-type]
        )
    ).all()
    rows: list[tuple[Match, ScheduleSlot]] = []
    for assignment in assignments:
        match = session.get(Match, assignment.match_id)
        slot = slot_by_id.get(assignment.slot_id)
        if match is None or slot is None:
            continue
        rows.append((match, slot))
    rows.sort(key=lambda pair: (pair[1].start_time or time.min, pair[1].court_number or 0, pair[0].id or 0))
    return rows


def _team_busy(session: Session, version_id: int, team_ids: set[int], ignore_match_id: int) -> bool:
    if not team_ids:
        return False
    live = [
        match
        for match in session.exec(select(Match).where(Match.schedule_version_id == version_id)).all()
        if (match.runtime_status or "").upper() in LIVE
    ]
    for match in live:
        if match.id == ignore_match_id:
            continue
        if match.team_a_id in team_ids or match.team_b_id in team_ids:
            return True
    return False


def _naive_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def operational_simulated_at(run: DeskDayRun, real_now: Optional[datetime] = None) -> Optional[datetime]:
    """The copy's current test time. A frozen clock stays on its anchor."""
    anchor = run.simulated_at
    if anchor is None:
        return None
    anchor = _naive_utc(anchor)
    if bool(getattr(run, "clock_frozen", False)):
        return anchor
    real_anchor = getattr(run, "clock_anchor_at", None)
    if real_anchor is None:
        return anchor
    current = _naive_utc(real_now or datetime.utcnow())
    real_anchor = _naive_utc(real_anchor)
    return anchor + (current - real_anchor)


def ensure_clock_anchor(run: DeskDayRun, real_now: Optional[datetime] = None) -> bool:
    """A running copy clock needs one real anchor.

    Without it the server keeps returning the original simulated time while
    each refresh carries a new real timestamp, and every open dashboard snaps
    backward to that original time.
    """
    if run.simulated_at is None or bool(getattr(run, "clock_frozen", False)):
        return False
    if getattr(run, "clock_anchor_at", None) is not None:
        return False
    run.clock_anchor_at = _naive_utc(real_now or datetime.utcnow())
    return True


def clock_reading(run: DeskDayRun, real_now: Optional[datetime] = None) -> tuple[Optional[datetime], datetime]:
    """Operational simulated time and the real UTC instant it was measured."""
    current = _naive_utc(real_now or datetime.utcnow())
    return operational_simulated_at(run, current), current


def activation_time(session: Session, tournament: Tournament, match: Match) -> datetime:
    """Copy activations use the simulated clock. Real tournaments use UTC now."""
    run = None
    if match.schedule_version_id and match.id:
        assignment = session.exec(
            select(MatchAssignment).where(
                MatchAssignment.schedule_version_id == match.schedule_version_id,
                MatchAssignment.match_id == match.id,
            )
        ).first()
        slot = session.get(ScheduleSlot, assignment.slot_id) if assignment and assignment.slot_id else None
        if slot is not None:
            run = _day_run(session, match.schedule_version_id, slot.day_date)
    return _activation_stamp(tournament, run)


def _court_open_at(
    slots: list[ScheduleSlot],
    court_number: int,
    now_minutes: int,
    open_slots: Optional[set[int]] = None,
) -> bool:
    """A court is open only when the slot covering the operational time is active."""
    court_slots = sorted(
        (slot for slot in slots if slot.court_number == court_number and slot.start_time is not None),
        key=lambda slot: slot.start_time or time.min,
    )
    if not court_slots or now_minutes < 0:
        return False
    cover = court_slots[0]
    for slot in court_slots:
        if _minutes(slot.start_time) <= now_minutes:
            cover = slot
        else:
            break
    if now_minutes < _minutes(cover.start_time):
        return False
    if open_slots is not None:
        return cover.id in open_slots
    return cover.is_active is not False


def progress_version_day(
    session: Session,
    tournament: Tournament,
    version: ScheduleVersion,
    day: date,
    now: Optional[datetime] = None,
) -> list[int]:
    """Start every eligible earliest match on this day. Never skips or moves courts."""
    if version.id is None or version.status != "draft":
        return []
    run = _day_run(session, version.id, day)
    if run is None or run.paused:
        return []
    if ensure_clock_anchor(run):
        session.add(run)
        session.flush()
    simulated = operational_simulated_at(run)
    if simulated is not None:
        local_now = tournament_local_now(tournament, _as_aware(tournament, simulated))
    else:
        local_now = tournament_local_now(tournament, now)
    if local_now.date() > day:
        now_minutes = 24 * 60
    elif local_now.date() < day:
        now_minutes = -1
    else:
        now_minutes = _minutes(local_now.time())

    from app.services.court_availability import effectively_open_slot_ids

    closed = _closed_labels(session, tournament.id or 0)
    open_slots = effectively_open_slot_ids(session, version.id, day)
    day_slots = list(
        session.exec(
            select(ScheduleSlot).where(
                ScheduleSlot.schedule_version_id == version.id,
                ScheduleSlot.day_date == day,
            )
        ).all()
    )
    by_court: dict[int, list[tuple[Match, ScheduleSlot]]] = {}
    for match, slot in _assignment_rows(session, version.id, day):
        by_court.setdefault(slot.court_number, []).append((match, slot))

    started: list[int] = []
    for court_number, rows in by_court.items():
        rows.sort(key=lambda pair: (pair[1].start_time or time.min, pair[0].id or 0))
        candidate: Optional[tuple[Match, ScheduleSlot]] = None
        for match, slot in rows:
            if (match.runtime_status or "SCHEDULED").upper() == "FINAL":
                continue
            candidate = (match, slot)
            break
        if candidate is None:
            continue
        match, slot = candidate
        status = (match.runtime_status or "SCHEDULED").upper()
        if status in LIVE:
            continue
        if bool(getattr(match, "start_held", False)):
            continue
        event = session.get(Event, match.event_id) if match.event_id else None
        if not is_preassigned(event, day):
            continue
        team_ids = {team_id for team_id in (match.team_a_id, match.team_b_id) if team_id}
        if not _court_open_at(day_slots, court_number, now_minutes, open_slots):
            continue
        allowed, _reason = auto_start_decision(
            day_started=True,
            paused=False,
            court_closed=_court_closed(closed, slot),
            slot_active=slot.id in open_slots,
            status=status,
            teams_known=match.team_a_id is not None and match.team_b_id is not None,
            feeders_final=_feeders_final(session, match),
            participant_busy=_team_busy(session, version.id, team_ids, match.id or 0),
            scheduled_minutes=_minutes(slot.start_time) if slot.start_time else None,
            now_minutes=now_minutes,
        )
        if not allowed:
            continue
        if _activate(session, match, slot, _activation_stamp(tournament, run)):
            started.append(match.id or 0)
    return started


def _activation_stamp(tournament: Tournament, run: Optional[DeskDayRun]) -> datetime:
    simulated = operational_simulated_at(run) if run is not None else None
    if simulated is not None and is_tournament_copy(tournament):
        return simulated
    return datetime.utcnow()


def _activate(session: Session, match: Match, slot: ScheduleSlot, started_at: datetime) -> bool:
    if match.schedule_version_id is None or match.id is None:
        return False
    with court_dispatch_lock(
        session,
        version_id=match.schedule_version_id,
        day_date=slot.day_date,
        court_number=slot.court_number,
    ) as acquired:
        if not acquired:
            return False
        session.refresh(match)
        status = (match.runtime_status or "SCHEDULED").upper()
        if status in LIVE or status == "FINAL":
            return False
        match.runtime_status = "IN_PROGRESS"
        if match.started_at is None:
            match.started_at = started_at
        session.add(match)
        session.flush()
    return True


def start_day(
    session: Session,
    tournament: Tournament,
    version: ScheduleVersion,
    day: date,
    now: Optional[datetime] = None,
) -> DeskDayRun:
    if version.id is None:
        raise ValueError("Schedule version is missing")
    run = _day_run(session, version.id, day)
    if run is None:
        run = DeskDayRun(
            tournament_id=tournament.id or 0,
            schedule_version_id=version.id,
            day_date=day,
            started_at=datetime.utcnow(),
            paused=False,
        )
        session.add(run)
        session.flush()
    real_now = tournament_local_now(tournament, now)
    if run.simulated_at is None and is_tournament_copy(tournament) and real_now.date() != day:
        run.simulated_at = datetime.combine(day, _opening_time(session, version.id, day))
        run.clock_anchor_at = datetime.utcnow()
        run.clock_frozen = False
        session.add(run)
        session.flush()
    if is_tournament_copy(tournament) and ensure_clock_anchor(run):
        session.add(run)
        session.flush()
    progress_version_day(session, tournament, version, day, now=now)
    return run


def set_paused(
    session: Session,
    tournament: Tournament,
    version: ScheduleVersion,
    day: date,
    paused: bool,
    now: Optional[datetime] = None,
) -> DeskDayRun:
    if version.id is None:
        raise ValueError("Schedule version is missing")
    run = _day_run(session, version.id, day)
    if run is None:
        raise ValueError("Day has not been started")
    run.paused = paused
    session.add(run)
    session.flush()
    if not paused:
        progress_version_day(session, tournament, version, day, now=now)
    return run


def staff_activate(
    session: Session,
    tournament: Tournament,
    match: Match,
    *,
    allow_early: bool,
    allow_skip_earlier: bool,
    now: Optional[datetime] = None,
) -> tuple[bool, str]:
    """Explicit staff activation from a drop onto Currently Playing. No SMS."""
    if match.schedule_version_id is None or match.id is None:
        return False, "Match is not on a schedule"
    assignment = session.exec(
        select(MatchAssignment).where(
            MatchAssignment.schedule_version_id == match.schedule_version_id,
            MatchAssignment.match_id == match.id,
        )
    ).first()
    slot = session.get(ScheduleSlot, assignment.slot_id) if assignment else None
    if slot is None:
        return False, "Assigned slot missing"
    version = session.get(ScheduleVersion, match.schedule_version_id)
    if version is None or version.status != "draft":
        return False, "Schedule is not editable"
    run = _day_run(session, version.id or 0, slot.day_date)
    if run is None:
        return False, "Start the day before activating a match"
    status = (match.runtime_status or "SCHEDULED").upper()
    if status == "FINAL":
        return False, "Match is already complete"
    if status in LIVE:
        return False, "Match is already playing"
    closed = _closed_labels(session, tournament.id or 0)
    from app.services.court_availability import slot_effectively_active

    if _court_closed(closed, slot) or not slot_effectively_active(session, slot):
        return False, "That court is not available"
    rows = [
        pair for pair in _assignment_rows(session, version.id or 0, slot.day_date) if pair[1].court_number == slot.court_number
    ]
    earlier = None
    for other, other_slot in rows:
        if other.id == match.id:
            break
        if (other.runtime_status or "SCHEDULED").upper() != "FINAL":
            earlier = other
            break
    if earlier is not None and not allow_skip_earlier:
        return False, f"Match #{earlier.id} is still assigned earlier on this court"
    simulated = operational_simulated_at(run)
    if simulated is not None:
        local_now = tournament_local_now(tournament, _as_aware(tournament, simulated))
        now_minutes = _minutes(local_now.time())
    else:
        local_now = tournament_local_now(tournament, now)
        if local_now.date() < slot.day_date:
            now_minutes = -1
        elif local_now.date() > slot.day_date:
            now_minutes = 24 * 60
        else:
            now_minutes = _minutes(local_now.time())
    scheduled = _minutes(slot.start_time) if slot.start_time else None
    if scheduled is not None and now_minutes < scheduled - EARLY_MINUTES and not allow_early:
        return False, "This match is before its 15-minute release window"
    occupant = next(
        (
            other
            for other, _other_slot in rows
            if other.id != match.id and (other.runtime_status or "").upper() in LIVE
        ),
        None,
    )
    if occupant is not None:
        return False, "That court already has a match playing"
    match.start_held = False
    session.add(match)
    session.flush()
    if not _activate(session, match, slot, _activation_stamp(tournament, run)):
        return False, "Could not start the match"
    return True, "started"


def set_test_clock(
    session: Session,
    tournament: Tournament,
    version: ScheduleVersion,
    day: date,
    clock_time: Optional[time] = None,
    *,
    advance_minutes: Optional[int] = None,
    frozen: Optional[bool] = None,
    now: Optional[datetime] = None,
) -> DeskDayRun:
    """Move or freeze a copy's operational clock. The published dates stay unchanged."""
    if not is_tournament_copy(tournament):
        raise ValueError("The test clock is only available on a tournament copy")
    if version.id is None:
        raise ValueError("Schedule version is missing")
    run = _day_run(session, version.id, day)
    if run is None:
        raise ValueError("Day has not been started")
    current = operational_simulated_at(run) or datetime.combine(day, _opening_time(session, version.id, day))
    if advance_minutes is not None:
        target = current + timedelta(minutes=advance_minutes)
    elif clock_time is not None:
        target = datetime.combine(day, clock_time)
    else:
        target = current
    current_minute = current.replace(second=0, microsecond=0)
    target_minute = target.replace(second=0, microsecond=0)
    if target_minute < current_minute:
        raise ValueError("The test clock cannot move backward. Duplicate a fresh copy to rehearse an earlier time.")
    run.simulated_at = target
    run.clock_anchor_at = datetime.utcnow()
    if frozen is not None:
        run.clock_frozen = frozen
    session.add(run)
    session.flush()
    if not run.paused:
        progress_version_day(session, tournament, version, day, now=now)
    return run


def _opening_time(session: Session, version_id: int, day: date) -> time:
    from app.services.court_availability import effectively_open_slot_ids

    open_slots = effectively_open_slot_ids(session, version_id, day)
    starts = [
        slot.start_time
        for _match, slot in _assignment_rows(session, version_id, day)
        if slot.start_time is not None and slot.id in open_slots
    ]
    return min(starts) if starts else time(9, 0)


def _as_aware(tournament: Tournament, value: datetime) -> datetime:
    if value.tzinfo is not None:
        return value
    zone_name = tournament.timezone or "UTC"
    try:
        zone = ZoneInfo(zone_name)
    except Exception:
        zone = ZoneInfo("UTC")
    return value.replace(tzinfo=zone)


def send_resolved_next_texts(session: Session, tournament: Tournament, version_id: int, match_ids: list[int]) -> None:
    """Send one next-match text per team once the next match has both teams, a time, and a court."""
    if is_tournament_copy(tournament):
        return
    from app.services.sms_automation import SmsAutomationEngine

    engine = SmsAutomationEngine(session, tournament, version_id)
    if not engine._texts_enabled():
        return
    message_type = "checkin_post_match_next" if engine._is_checkin_management() else "post_match_next"
    seen: set[tuple[int, int]] = set()
    for match_id in match_ids:
        match = session.get(Match, match_id)
        if match is None or match.team_a_id is None or match.team_b_id is None:
            continue
        slot = engine._slot_for_match(match.id or 0)
        if slot is None or slot.start_time is None or slot.court_number is None:
            continue
        active, template_body = engine._template_for(message_type)
        if not active:
            return
        template_body = engine._preassigned_court_template(message_type, match, slot, template_body)
        for team in engine._teams_for_match(match):
            if team.id is None or (team.id, match.id or 0) in seen:
                continue
            seen.add((team.id, match.id or 0))
            engine._send_message_to_team(
                team=team,
                message=engine._render_template_message(
                    team=team,
                    template_body=template_body,
                    match=match,
                    slot=slot,
                    opponent=engine._opponent_display(match, team.id),
                ),
                message_type=message_type,
                dedupe_key=engine._dedupe_key(message_type, f"v{version_id}", f"t{team.id}", f"m{match.id}"),
                trigger="auto",
            )


def progress_running_days(session: Session, now: Optional[datetime] = None) -> list[int]:
    runs = session.exec(select(DeskDayRun).where(DeskDayRun.paused == False)).all()  # noqa: E712
    started: list[int] = []
    for run in runs:
        tournament = session.get(Tournament, run.tournament_id)
        version = session.get(ScheduleVersion, run.schedule_version_id)
        if tournament is None or version is None:
            continue
        started.extend(progress_version_day(session, tournament, version, run.day_date, now=now))
    return started


def _runner_loop(interval_seconds: int) -> None:
    from app.database import engine

    while True:
        started_at = time_module.time()
        try:
            with Session(engine) as session:
                started = progress_running_days(session)
                session.commit()
            if started:
                from app.routes.desk import _bump_desk_snapshot

                _bump_desk_snapshot()
                logger.info("Dashboard progression started matches %s", started)
        except Exception:
            logger.exception("Dashboard progression cycle failed")
        elapsed = time_module.time() - started_at
        time_module.sleep(max(1.0, interval_seconds - elapsed))


def start_dashboard_progression_runner() -> None:
    """Reevaluate started days without requiring a browser to stay open."""
    global _runner_started
    if _runner_started or os.environ.get("PYTEST_CURRENT_TEST") or "pytest" in sys.modules:
        return
    interval = int(os.environ.get("DASHBOARD_PROGRESS_INTERVAL_SECONDS", "20"))
    if interval <= 0:
        return
    threading.Thread(target=_runner_loop, args=(interval,), name="dashboard-progression", daemon=True).start()
    _runner_started = True
    logger.info("Dashboard progression runner started interval=%ss", interval)


def release_clock(start: time) -> time:
    raw = datetime.combine(date.today(), start) - timedelta(minutes=EARLY_MINUTES)
    return raw.time()
