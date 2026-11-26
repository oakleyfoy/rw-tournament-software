"""Dashboard day start and designated-court automatic progression."""

from datetime import date, datetime, time, timedelta, timezone

import pytest

from sqlmodel import Session, select

from app.models.event import Event
from app.models.match import Match
from app.models.match_assignment import MatchAssignment
from app.models.match_checkin import MatchCheckIn
from app.models.schedule_slot import ScheduleSlot
from app.models.schedule_version import ScheduleVersion
from app.models.sms_log import SmsLog
from app.models.team import Team
from app.models.tournament import Tournament
from app.services.court_assignment_mode import MODE_PREASSIGNED, replace_court_assignment_modes
from app.models.desk_day_run import DeskDayRun
from app.services.dashboard_progression import ensure_clock_anchor, operational_simulated_at, progress_version_day, send_resolved_next_texts, set_paused, set_test_clock, start_day


def _build(session: Session):
    tournament = Tournament(
        name="Dashboard Day",
        location="Palm",
        timezone="America/Chicago",
        start_date=date(2026, 12, 4),
        end_date=date(2026, 12, 6),
        desk_management_mode="checkin_management",
    )
    session.add(tournament)
    session.flush()
    version = ScheduleVersion(tournament_id=tournament.id, version_number=1, status="draft")
    session.add(version)
    session.flush()
    event = Event(tournament_id=tournament.id, category="womens", name="Women's", team_count=4)
    session.add(event)
    session.flush()
    replace_court_assignment_modes(event, {"2026-12-04": MODE_PREASSIGNED, "2026-12-05": MODE_PREASSIGNED})
    session.add(event)
    session.flush()
    return tournament, version, event


_SEED = 1


def _pair(session: Session, event: Event, names: tuple[str, str]) -> tuple[Team, Team]:
    global _SEED
    teams = []
    for name in names:
        team = Team(event_id=event.id, name=name, display_name=name, seed=_SEED)
        _SEED += 1
        session.add(team)
        teams.append(team)
    session.flush()
    return teams[0], teams[1]


def _place(session, tournament, version, event, court, start, teams, code, checked=True):
    slot = ScheduleSlot(
        tournament_id=tournament.id,
        schedule_version_id=version.id,
        day_date=date(2026, 12, 4),
        start_time=start,
        end_time=time(start.hour + 1, 0),
        court_number=court,
        court_label=str(court),
        block_minutes=60,
        is_active=True,
    )
    session.add(slot)
    session.flush()
    match = Match(
        tournament_id=tournament.id,
        event_id=event.id,
        schedule_version_id=version.id,
        match_code=code,
        match_type="WF",
        round_number=1,
        round_index=1,
        sequence_in_round=1,
        duration_minutes=60,
        team_a_id=teams[0].id,
        team_b_id=teams[1].id,
        placeholder_side_a="A",
        placeholder_side_b="B",
        runtime_status="SCHEDULED",
    )
    session.add(match)
    session.flush()
    session.add(MatchAssignment(schedule_version_id=version.id, match_id=match.id, slot_id=slot.id, assigned_by="MANUAL"))
    if checked:
        for side, team in (("A", teams[0]), ("B", teams[1])):
            session.add(
                MatchCheckIn(
                    tournament_id=tournament.id,
                    schedule_version_id=version.id,
                    match_id=match.id,
                    team_id=team.id,
                    side=side,
                    team_checked_in=True,
                )
            )
    session.flush()
    return match


def _status(session: Session, match_id: int) -> str:
    session.expire_all()
    match = session.get(Match, match_id)
    return (match.runtime_status or "").upper()


def test_start_day_is_idempotent_and_does_not_text(session: Session):
    tournament, version, event = _build(session)
    nine = _place(session, tournament, version, event, 2, time(9, 0), _pair(session, event, ("Carol", "Olivia")), "M9")
    noon = _place(session, tournament, version, event, 2, time(12, 0), _pair(session, event, ("Amy", "Holly")), "M12")
    session.commit()

    before = progress_version_day(session, tournament, version, date(2026, 12, 4), now=datetime(2026, 12, 4, 9, 5, tzinfo=timezone.utc))
    assert before == []
    assert _status(session, nine.id) == "SCHEDULED"

    start_day(session, tournament, version, date(2026, 12, 4), now=datetime(2026, 12, 4, 15, 5, tzinfo=timezone.utc))
    start_day(session, tournament, version, date(2026, 12, 4), now=datetime(2026, 12, 4, 15, 5, tzinfo=timezone.utc))
    session.commit()
    assert _status(session, nine.id) == "IN_PROGRESS"
    assert _status(session, noon.id) == "SCHEDULED"
    assert session.exec(select(SmsLog).where(SmsLog.tournament_id == tournament.id)).all() == []


def test_open_court_holds_the_noon_match_until_its_release_window(session: Session):
    tournament, version, event = _build(session)
    nine = _place(session, tournament, version, event, 2, time(9, 0), _pair(session, event, ("Carol", "Olivia")), "M9")
    noon = _place(session, tournament, version, event, 2, time(12, 0), _pair(session, event, ("Amy", "Holly")), "M12")
    nine.runtime_status = "FINAL"
    session.add(nine)
    session.commit()

    start_day(session, tournament, version, date(2026, 12, 4), now=datetime(2026, 12, 4, 16, 45, tzinfo=timezone.utc))
    session.commit()
    assert _status(session, noon.id) == "SCHEDULED"

    progress_version_day(session, tournament, version, date(2026, 12, 4), now=datetime(2026, 12, 4, 17, 45, tzinfo=timezone.utc))
    session.commit()
    assert _status(session, noon.id) == "IN_PROGRESS"


def test_a_blocked_earlier_match_is_not_skipped_and_courts_are_not_reassigned(session: Session):
    tournament, version, event = _build(session)
    early = _place(session, tournament, version, event, 2, time(10, 30), _pair(session, event, ("Beth", "Jenn")), "M1030")
    later = _place(session, tournament, version, event, 2, time(12, 0), _pair(session, event, ("Amy", "Holly")), "M12")
    other = _place(session, tournament, version, event, 7, time(10, 30), _pair(session, event, ("Deana", "Katherine")), "M7")
    early.team_b_id = None
    session.add(early)
    session.commit()

    start_day(session, tournament, version, date(2026, 12, 4), now=datetime(2026, 12, 4, 17, 0, tzinfo=timezone.utc))
    session.commit()
    assert _status(session, early.id) == "SCHEDULED"
    assert _status(session, later.id) == "SCHEDULED"
    assert _status(session, other.id) == "IN_PROGRESS"
    assignment = session.exec(select(MatchAssignment).where(MatchAssignment.match_id == later.id)).one()
    slot = session.get(ScheduleSlot, assignment.slot_id)
    assert slot.court_number == 2


def test_saturday_does_not_start_when_friday_starts(session: Session):
    tournament, version, event = _build(session)
    friday = _place(session, tournament, version, event, 1, time(9, 0), _pair(session, event, ("Carol", "Olivia")), "FRI")
    slot = ScheduleSlot(
        tournament_id=tournament.id,
        schedule_version_id=version.id,
        day_date=date(2026, 12, 5),
        start_time=time(9, 0),
        end_time=time(10, 0),
        court_number=1,
        court_label="1",
        block_minutes=60,
    )
    session.add(slot)
    session.flush()
    teams = _pair(session, event, ("Sat A", "Sat B"))
    saturday = Match(
        tournament_id=tournament.id,
        event_id=event.id,
        schedule_version_id=version.id,
        match_code="SAT",
        match_type="WF",
        round_number=1,
        round_index=1,
        sequence_in_round=1,
        duration_minutes=60,
        team_a_id=teams[0].id,
        team_b_id=teams[1].id,
        placeholder_side_a="A",
        placeholder_side_b="B",
        runtime_status="SCHEDULED",
    )
    session.add(saturday)
    session.flush()
    session.add(MatchAssignment(schedule_version_id=version.id, match_id=saturday.id, slot_id=slot.id, assigned_by="MANUAL"))
    session.commit()

    start_day(session, tournament, version, date(2026, 12, 4), now=datetime(2026, 12, 4, 15, 0, tzinfo=timezone.utc))
    session.commit()
    assert _status(session, friday.id) == "IN_PROGRESS"
    assert _status(session, saturday.id) == "SCHEDULED"


def test_opening_matches_start_with_zero_check_ins(session: Session):
    tournament, version, event = _build(session)
    nine = _place(session, tournament, version, event, 2, time(9, 0), _pair(session, event, ("Carol", "Olivia")), "OPEN", checked=False)
    session.commit()

    start_day(session, tournament, version, date(2026, 12, 4), now=datetime(2026, 12, 4, 15, 5, tzinfo=timezone.utc))
    session.commit()
    assert _status(session, nine.id) == "IN_PROGRESS"
    assert session.exec(select(MatchCheckIn).where(MatchCheckIn.schedule_version_id == version.id)).all() == []


def test_a_future_calendar_date_does_not_start_a_published_tournament(session: Session):
    tournament, version, event = _build(session)
    nine = _place(session, tournament, version, event, 2, time(9, 0), _pair(session, event, ("Carol", "Olivia")), "FUTURE", checked=False)
    session.commit()

    start_day(session, tournament, version, date(2026, 12, 4), now=datetime(2026, 11, 26, 15, 5, tzinfo=timezone.utc))
    session.commit()
    assert _status(session, nine.id) == "SCHEDULED"
    run = session.exec(select(DeskDayRun).where(DeskDayRun.schedule_version_id == version.id)).one()
    assert run.simulated_at is None


def test_a_copy_uses_a_simulated_opening_clock_and_does_not_text(session: Session):
    tournament, version, event = _build(session)
    tournament.name = "Palm Springs 2026 (Copy)"
    session.add(tournament)
    nine = _place(session, tournament, version, event, 2, time(9, 0), _pair(session, event, ("Carol", "Olivia")), "COPY9", checked=False)
    noon = _place(session, tournament, version, event, 2, time(12, 0), _pair(session, event, ("Amy", "Holly")), "COPY12", checked=False)
    blocked = _place(session, tournament, version, event, 7, time(9, 0), _pair(session, event, ("Deana", "Katherine")), "COPY7", checked=False)
    blocked_slot = session.exec(
        select(ScheduleSlot).where(ScheduleSlot.schedule_version_id == version.id, ScheduleSlot.court_number == 7)
    ).one()
    blocked_slot.is_active = False
    session.add(blocked_slot)
    session.commit()

    start_day(session, tournament, version, date(2026, 12, 4), now=datetime(2026, 11, 26, 16, 0, tzinfo=timezone.utc))
    session.commit()
    assert _status(session, nine.id) == "IN_PROGRESS"
    assert _status(session, noon.id) == "SCHEDULED"
    assert _status(session, blocked.id) == "SCHEDULED"
    run = session.exec(select(DeskDayRun).where(DeskDayRun.schedule_version_id == version.id)).one()
    assert run.simulated_at is not None
    assert run.simulated_at.hour == 9

    nine.runtime_status = "FINAL"
    session.add(nine)
    set_test_clock(session, tournament, version, date(2026, 12, 4), time(10, 45))
    session.commit()
    assert _status(session, noon.id) == "SCHEDULED"

    set_test_clock(session, tournament, version, date(2026, 12, 4), time(11, 45))
    session.commit()
    assert _status(session, noon.id) == "IN_PROGRESS"
    send_resolved_next_texts(session, tournament, version.id, [noon.id])
    session.commit()
    assert session.exec(select(SmsLog).where(SmsLog.tournament_id == tournament.id)).all() == []
    started = session.get(Match, nine.id)
    assert started.started_at is not None
    assert started.started_at.date() == date(2026, 12, 4)
    assert started.started_at.hour == 9


def test_an_unavailable_court_holds_its_noon_match_through_the_early_window(session: Session):
    tournament, version, event = _build(session)
    for hour in (9, 10, 11):
        session.add(
            ScheduleSlot(
                tournament_id=tournament.id,
                schedule_version_id=version.id,
                day_date=date(2026, 12, 4),
                start_time=time(hour, 0),
                end_time=time(hour + 1, 0),
                court_number=10,
                court_label="10",
                block_minutes=60,
                is_active=False,
            )
        )
    noon = _place(session, tournament, version, event, 10, time(12, 0), _pair(session, event, ("Amy", "Holly")), "NOON")
    session.commit()

    start_day(session, tournament, version, date(2026, 12, 4), now=datetime(2026, 12, 4, 17, 45, tzinfo=timezone.utc))
    session.commit()
    assert _status(session, noon.id) == "SCHEDULED"

    progress_version_day(session, tournament, version, date(2026, 12, 4), now=datetime(2026, 12, 4, 18, 0, tzinfo=timezone.utc))
    session.commit()
    assert _status(session, noon.id) == "IN_PROGRESS"


def test_copy_clock_advances_freezes_independently_and_rejects_backward_time(session: Session):
    tournament, version, event = _build(session)
    tournament.name = "Palm Springs 2026 (Copy)"
    session.add(tournament)
    _place(session, tournament, version, event, 4, time(9, 0), _pair(session, event, ("Carol", "Olivia")), "CLOCK")
    session.commit()

    start_day(session, tournament, version, date(2026, 12, 4), now=datetime(2026, 11, 26, 16, 0, tzinfo=timezone.utc))
    run = session.exec(select(DeskDayRun).where(DeskDayRun.schedule_version_id == version.id)).one()
    run.clock_anchor_at = datetime.utcnow() - timedelta(minutes=5)
    session.add(run)
    session.flush()
    advanced = operational_simulated_at(run)
    assert advanced is not None
    assert advanced.hour == 9
    assert advanced.minute >= 4

    set_paused(session, tournament, version, date(2026, 12, 4), True)
    paused = session.exec(select(DeskDayRun).where(DeskDayRun.schedule_version_id == version.id)).one()
    assert paused.paused is True
    assert paused.clock_frozen is False
    still_moving = operational_simulated_at(paused)
    assert still_moving is not None
    assert still_moving >= advanced

    set_test_clock(session, tournament, version, date(2026, 12, 4), frozen=True)
    frozen = session.exec(select(DeskDayRun).where(DeskDayRun.schedule_version_id == version.id)).one()
    assert frozen.clock_frozen is True
    held = operational_simulated_at(frozen)
    assert held is not None
    assert held.minute == frozen.simulated_at.minute

    with pytest.raises(ValueError, match="cannot move backward"):
        set_test_clock(session, tournament, version, date(2026, 12, 4), time(8, 0))


def test_a_copy_clock_without_an_anchor_starts_running_without_moving_backward(session: Session):
    tournament, version, event = _build(session)
    tournament.name = "Palm Springs 2026 (Copy)"
    session.add(tournament)
    match = _place(session, tournament, version, event, 4, time(9, 0), _pair(session, event, ("Carol", "Olivia")), "ANCHOR")
    session.commit()

    start_day(session, tournament, version, date(2026, 12, 4), now=datetime(2026, 11, 26, 16, 0, tzinfo=timezone.utc))
    run = session.exec(select(DeskDayRun).where(DeskDayRun.schedule_version_id == version.id)).one()
    opening = run.simulated_at
    run.clock_anchor_at = None
    session.add(run)
    session.flush()
    assert ensure_clock_anchor(run) is True
    assert run.simulated_at == opening
    assert run.clock_anchor_at is not None
    assert operational_simulated_at(run, run.clock_anchor_at) == opening

    playing = session.get(Match, match.id)
    assert playing.started_at is not None
    assert playing.started_at.date() == date(2026, 12, 4)
    playing.started_at = datetime(2026, 11, 26, 17, 36)
    session.add(playing)
    session.flush()
    preserved = session.get(Match, match.id)
    assert preserved.started_at == datetime(2026, 11, 26, 17, 36)
