"""Tournament Desk Open Courts must follow Schedule Grid slot existence."""

from datetime import date, time, timedelta
from typing import Iterable, List, Optional

from sqlmodel import Session, select

from app.models.event import Event
from app.models.match import Match
from app.models.match_assignment import MatchAssignment
from app.models.player import Player
from app.models.schedule_slot import ScheduleSlot
from app.models.schedule_version import ScheduleVersion
from app.models.team import Team
from app.models.team_player import TeamPlayer
from app.models.tournament import Tournament

FRIDAY = date(2026, 7, 10)
SATURDAY = date(2026, 7, 11)
SLOT_TIMES = (
    time(8, 30),
    time(9, 30),
    time(10, 30),
    time(11, 30),
    time(12, 30),
)


def _end_time(start: time) -> time:
    start_dt = date(2026, 1, 1)
    return (datetime_combine(start_dt, start) + timedelta(hours=1)).time()


def datetime_combine(day: date, start: time):
    from datetime import datetime

    return datetime.combine(day, start)


def _add_slot(
    session: Session,
    tournament: Tournament,
    version: ScheduleVersion,
    day: date,
    start: time,
    court_number: int,
    court_label: Optional[str] = None,
    *,
    is_active: bool = True,
) -> ScheduleSlot:
    slot = ScheduleSlot(
        tournament_id=tournament.id,
        schedule_version_id=version.id,
        day_date=day,
        start_time=start,
        end_time=_end_time(start),
        court_number=court_number,
        court_label=court_label or str(court_number),
        block_minutes=60,
        is_active=is_active,
    )
    session.add(slot)
    session.flush()
    return slot


def _add_players(session: Session, tournament_id: int, team_id: int, prefix: str) -> List[Player]:
    p1 = Player(tournament_id=tournament_id, full_name=f"{prefix} Player 1")
    p2 = Player(tournament_id=tournament_id, full_name=f"{prefix} Player 2")
    session.add_all([p1, p2])
    session.flush()
    session.add_all(
        [
            TeamPlayer(team_id=team_id, player_id=p1.id, lineup_slot=1),
            TeamPlayer(team_id=team_id, player_id=p2.id, lineup_slot=2),
        ]
    )
    session.flush()
    return [p1, p2]


def _setup_open_courts_tournament(
    session: Session,
    *,
    court1_times: Iterable[time] = SLOT_TIMES,
    court9_times: Iterable[time] = (time(8, 30), time(12, 30)),
    activity_time: time = time(8, 30),
    activity_day: date = FRIDAY,
    extra_saturday_court9: bool = False,
    name: str = "Open Courts Slot Test",
):
    tournament = Tournament(
        name=name,
        location="Amelia Island",
        timezone="America/New_York",
        start_date=FRIDAY,
        end_date=SATURDAY,
        court_names=["1", "9"],
        desk_management_mode="checkin_management",
    )
    session.add(tournament)
    session.flush()

    version = ScheduleVersion(
        tournament_id=tournament.id,
        version_number=1,
        status="draft",
        notes="Desk Draft",
    )
    session.add(version)
    session.flush()

    event = Event(
        tournament_id=tournament.id,
        category="womens",
        name="Women's A",
        team_count=4,
    )
    session.add(event)
    session.flush()

    teams = []
    for index, label in enumerate(["Alpha", "Bravo", "Charlie", "Delta"], start=1):
        team = Team(event_id=event.id, name=label, seed=index, display_name=label)
        session.add(team)
        session.flush()
        teams.append(team)

    slots_by_key: dict[tuple, ScheduleSlot] = {}
    for start in court1_times:
        slots_by_key[(FRIDAY, start, 1)] = _add_slot(session, tournament, version, FRIDAY, start, 1)
    for start in court9_times:
        slots_by_key[(FRIDAY, start, 9)] = _add_slot(session, tournament, version, FRIDAY, start, 9)
    if extra_saturday_court9:
        slots_by_key[(SATURDAY, time(10, 30), 9)] = _add_slot(session, tournament, version, SATURDAY, time(10, 30), 9)

    match = Match(
        tournament_id=tournament.id,
        event_id=event.id,
        schedule_version_id=version.id,
        match_code="WOM_WF_R1_M01",
        match_type="WF",
        round_number=1,
        round_index=1,
        sequence_in_round=1,
        duration_minutes=60,
        team_a_id=teams[0].id,
        team_b_id=teams[3].id,
        placeholder_side_a="SEED_1",
        placeholder_side_b="SEED_4",
    )
    session.add(match)
    session.flush()

    activity_slot = slots_by_key[(activity_day, activity_time, 1)]
    session.add(MatchAssignment(schedule_version_id=version.id, match_id=match.id, slot_id=activity_slot.id))
    session.commit()
    return tournament, version, teams, match, slots_by_key


def _enable_checkin(client, tournament_id: int, version_id: int) -> None:
    resp = client.patch(
        f"/api/desk/tournaments/{tournament_id}/management-mode",
        json={"version_id": version_id, "management_mode": "checkin_management"},
    )
    assert resp.status_code == 200


def _snapshot(client, tournament_id: int, version_id: int) -> dict:
    resp = client.get(
        f"/api/desk/tournaments/{tournament_id}/snapshot",
        params={"version_id": version_id},
    )
    assert resp.status_code == 200
    return resp.json()


def _board_and_open_courts(body: dict) -> tuple[set[str], set[str]]:
    board = set(body.get("checkin_board_courts") or [])
    open_courts = {slot["court_name"] for slot in body.get("available_slots") or []}
    return board, open_courts


def test_court_9_visible_when_slot_exists_at_830(client, session):
    t, v, _teams, _match, _slots = _setup_open_courts_tournament(session, activity_time=time(8, 30))
    _enable_checkin(client, t.id, v.id)
    body = _snapshot(client, t.id, v.id)

    assert body["active_checkin_slot_key"] == f"{FRIDAY.isoformat()}|08:30"
    board, open_courts = _board_and_open_courts(body)
    assert "Court 9" in board
    assert "Court 9" in open_courts
    assert "Court 1" in board


def test_court_9_hidden_when_slot_deleted_at_930(client, session):
    t, v, _teams, _match, _slots = _setup_open_courts_tournament(session, activity_time=time(9, 30))
    _enable_checkin(client, t.id, v.id)
    body = _snapshot(client, t.id, v.id)

    assert body["active_checkin_slot_key"] == f"{FRIDAY.isoformat()}|09:30"
    board, open_courts = _board_and_open_courts(body)
    assert "Court 9" not in board
    assert "Court 9" not in open_courts
    assert "Court 1" in board
    assert "Court 1" in open_courts


def test_court_9_hidden_when_slot_deleted_at_1030(client, session):
    t, v, _teams, _match, _slots = _setup_open_courts_tournament(session, activity_time=time(10, 30))
    _enable_checkin(client, t.id, v.id)
    body = _snapshot(client, t.id, v.id)

    assert body["active_checkin_slot_key"] == f"{FRIDAY.isoformat()}|10:30"
    board, open_courts = _board_and_open_courts(body)
    assert "Court 9" not in board
    assert "Court 9" not in open_courts


def test_court_9_hidden_when_slot_deleted_at_1130(client, session):
    t, v, _teams, _match, _slots = _setup_open_courts_tournament(session, activity_time=time(11, 30))
    _enable_checkin(client, t.id, v.id)
    body = _snapshot(client, t.id, v.id)

    assert body["active_checkin_slot_key"] == f"{FRIDAY.isoformat()}|11:30"
    board, open_courts = _board_and_open_courts(body)
    assert "Court 9" not in board
    assert "Court 9" not in open_courts


def test_court_9_visible_when_slot_exists_at_1230(client, session):
    t, v, _teams, _match, _slots = _setup_open_courts_tournament(session, activity_time=time(12, 30))
    _enable_checkin(client, t.id, v.id)
    body = _snapshot(client, t.id, v.id)

    assert body["active_checkin_slot_key"] == f"{FRIDAY.isoformat()}|12:30"
    board, open_courts = _board_and_open_courts(body)
    assert "Court 9" in board
    assert "Court 9" in open_courts


def test_all_day_court_stays_visible_when_open(client, session):
    t, v, _teams, _match, _slots = _setup_open_courts_tournament(session, activity_time=time(10, 30))
    _enable_checkin(client, t.id, v.id)
    body = _snapshot(client, t.id, v.id)
    board, open_courts = _board_and_open_courts(body)
    assert "Court 1" in board
    assert "Court 1" in open_courts
    assert all(slot["scheduled_time"] == "10:30 AM" for slot in body["available_slots"])


def test_occupied_available_court_is_currently_playing_not_open(client, session):
    t, v, _teams, match, _slots = _setup_open_courts_tournament(session, activity_time=time(8, 30))
    match.runtime_status = "IN_PROGRESS"
    session.add(match)
    session.commit()
    _enable_checkin(client, t.id, v.id)
    body = _snapshot(client, t.id, v.id)

    board, open_courts = _board_and_open_courts(body)
    assert "Court 1" in board
    assert "Court 1" not in open_courts
    assert "Court 1" in body["now_playing_by_court"]
    assert "Court 9" in open_courts
    assert "Court 9" not in body["now_playing_by_court"]


def test_unavailable_court_appears_in_neither_section(client, session):
    t, v, _teams, _match, _slots = _setup_open_courts_tournament(session, activity_time=time(9, 30))
    _enable_checkin(client, t.id, v.id)
    body = _snapshot(client, t.id, v.id)
    board, open_courts = _board_and_open_courts(body)
    assert "Court 9" not in board
    assert "Court 9" not in open_courts
    assert "Court 9" not in body["now_playing_by_court"]


def test_assign_rejects_drop_onto_unavailable_court(client, session):
    t, v, teams, match, slots = _setup_open_courts_tournament(session, activity_time=time(10, 30))
    alpha = _add_players(session, t.id, teams[0].id, "Alpha")
    delta = _add_players(session, t.id, teams[3].id, "Delta")
    session.commit()
    _enable_checkin(client, t.id, v.id)

    for side, players in (("A", alpha), ("B", delta)):
        for player in players:
            resp = client.patch(
                f"/api/desk/tournaments/{t.id}/matches/{match.id}/checkin/player",
                json={"version_id": v.id, "side": side, "player_id": player.id, "checked_in": True},
            )
            assert resp.status_code == 200

    court9_1230 = slots[(FRIDAY, time(12, 30), 9)]
    assign = client.post(
        f"/api/desk/tournaments/{t.id}/checkin/assign",
        json={"version_id": v.id, "match_id": match.id, "slot_id": court9_1230.id},
    )
    assert assign.status_code == 400
    assert assign.json()["detail"] == "Court 9 is not available for the 10:30 AM schedule slot."

    session.refresh(match)
    assignment = session.exec(
        select(MatchAssignment).where(
            MatchAssignment.schedule_version_id == v.id,
            MatchAssignment.match_id == match.id,
        )
    ).first()
    assert match.runtime_status != "IN_PROGRESS"
    assert assignment is not None
    assert assignment.slot_id != court9_1230.id


def test_court_availability_is_isolated_by_tournament(client, session):
    t_a, v_a, _teams_a, _match_a, _slots_a = _setup_open_courts_tournament(
        session,
        activity_time=time(10, 30),
        name="Tournament A",
    )
    t_b, v_b, _teams_b, _match_b, _slots_b = _setup_open_courts_tournament(
        session,
        court9_times=SLOT_TIMES,
        activity_time=time(10, 30),
        name="Tournament B",
    )
    _enable_checkin(client, t_a.id, v_a.id)
    _enable_checkin(client, t_b.id, v_b.id)

    body_a = _snapshot(client, t_a.id, v_a.id)
    body_b = _snapshot(client, t_b.id, v_b.id)
    board_a, open_a = _board_and_open_courts(body_a)
    board_b, open_b = _board_and_open_courts(body_b)

    assert "Court 9" not in board_a
    assert "Court 9" not in open_a
    assert "Court 9" in board_b
    assert "Court 9" in open_b


def test_court_availability_is_isolated_by_tournament_day(client, session):
    t, v, _teams, _match, _slots = _setup_open_courts_tournament(
        session,
        activity_time=time(10, 30),
        extra_saturday_court9=True,
    )
    _enable_checkin(client, t.id, v.id)
    body = _snapshot(client, t.id, v.id)
    board, open_courts = _board_and_open_courts(body)
    assert body["active_checkin_slot_key"] == f"{FRIDAY.isoformat()}|10:30"
    assert "Court 9" not in board
    assert "Court 9" not in open_courts


def test_in_progress_match_on_removed_slot_is_warning_not_rewritten(client, session):
    t, v, teams, early_match, slots = _setup_open_courts_tournament(session, activity_time=time(9, 30))
    later = Match(
        tournament_id=t.id,
        event_id=early_match.event_id,
        schedule_version_id=v.id,
        match_code="WOM_WF_R1_M02",
        match_type="WF",
        round_number=1,
        round_index=1,
        sequence_in_round=2,
        duration_minutes=60,
        team_a_id=teams[1].id,
        team_b_id=teams[2].id,
        placeholder_side_a="SEED_2",
        placeholder_side_b="SEED_3",
        runtime_status="IN_PROGRESS",
    )
    session.add(later)
    session.flush()
    court9_1230 = slots[(FRIDAY, time(12, 30), 9)]
    session.add(MatchAssignment(schedule_version_id=v.id, match_id=later.id, slot_id=court9_1230.id))
    session.commit()

    _enable_checkin(client, t.id, v.id)
    body = _snapshot(client, t.id, v.id)
    board, open_courts = _board_and_open_courts(body)
    assert "Court 9" not in board
    assert "Court 9" not in open_courts
    warning_text = " ".join(w["message"] for w in body["checkin_court_warnings"])
    assert "Court 9" in warning_text
    assert "9:30 AM" in warning_text

    session.refresh(later)
    later_assignment = session.exec(
        select(MatchAssignment).where(
            MatchAssignment.schedule_version_id == v.id,
            MatchAssignment.match_id == later.id,
        )
    ).first()
    assert later.runtime_status == "IN_PROGRESS"
    assert later_assignment is not None
    assert later_assignment.slot_id == court9_1230.id
