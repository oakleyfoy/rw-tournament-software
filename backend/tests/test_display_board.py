"""Read-only tournament display-board API tests."""

from datetime import date, datetime, time
from typing import List, Optional

from sqlmodel import Session, select

from app.models.event import Event
from app.models.match import Match
from app.models.match_assignment import MatchAssignment
from app.models.match_checkin import MatchCheckIn
from app.models.player import Player
from app.models.schedule_slot import ScheduleSlot
from app.models.schedule_version import ScheduleVersion
from app.models.team import Team
from app.models.team_player import TeamPlayer
from app.models.tournament import Tournament
from app.services.display_board import collect_forbidden_keys


def _freeze_now(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.display_board.now_in_timezone",
        lambda tz: datetime(2026, 6, 5, 14, 0, tzinfo=tz),
    )


def _add_slot(
    session: Session,
    *,
    tournament_id: int,
    version_id: int,
    start: time,
    court_number: int,
    day: date = date(2026, 6, 5),
    end: Optional[time] = None,
) -> ScheduleSlot:
    slot = ScheduleSlot(
        tournament_id=tournament_id,
        schedule_version_id=version_id,
        day_date=day,
        start_time=start,
        end_time=end or time((start.hour + 1) % 24, start.minute),
        court_number=court_number,
        court_label=str(court_number),
        block_minutes=60,
    )
    session.add(slot)
    session.flush()
    return slot


def _add_team(session: Session, event_id: int, name: str, seed: int) -> Team:
    team = Team(event_id=event_id, name=name, seed=seed, display_name=None)
    session.add(team)
    session.flush()
    return team


def _add_match(
    session: Session,
    *,
    tournament_id: int,
    event_id: int,
    version_id: int,
    code: str,
    team_a: Optional[Team],
    team_b: Optional[Team],
    slot: ScheduleSlot,
    runtime_status: str = "SCHEDULED",
    match_type: str = "WF",
    round_number: int = 1,
    sequence: int = 1,
    placeholder_a: str = "TBD",
    placeholder_b: str = "TBD",
) -> Match:
    match = Match(
        tournament_id=tournament_id,
        event_id=event_id,
        schedule_version_id=version_id,
        match_code=code,
        match_type=match_type,
        round_number=round_number,
        round_index=1,
        sequence_in_round=sequence,
        duration_minutes=60,
        team_a_id=team_a.id if team_a else None,
        team_b_id=team_b.id if team_b else None,
        placeholder_side_a=placeholder_a,
        placeholder_side_b=placeholder_b,
        status="scheduled",
        runtime_status=runtime_status,
    )
    session.add(match)
    session.flush()
    session.add(
        MatchAssignment(
            schedule_version_id=version_id,
            match_id=match.id,
            slot_id=slot.id,
        )
    )
    session.flush()
    return match


def _check_in(session: Session, tournament_id: int, version_id: int, match: Match, side: str) -> None:
    team_id = match.team_a_id if side == "A" else match.team_b_id
    session.add(
        MatchCheckIn(
            tournament_id=tournament_id,
            schedule_version_id=version_id,
            match_id=match.id,
            team_id=team_id,
            side=side,
            team_checked_in=True,
            checked_in_at=datetime.utcnow(),
        )
    )
    session.flush()


def _setup_board(session: Session):
    tournament = Tournament(
        name="Display Board Open",
        location="Test Beach",
        timezone="America/New_York",
        start_date=date(2026, 6, 5),
        end_date=date(2026, 6, 7),
        desk_management_mode="checkin_management",
    )
    session.add(tournament)
    session.flush()

    version = ScheduleVersion(
        tournament_id=tournament.id,
        version_number=1,
        status="final",
    )
    session.add(version)
    session.flush()
    tournament.public_schedule_version_id = version.id
    session.add(tournament)

    womens_b = Event(
        tournament_id=tournament.id,
        category="womens",
        name="Women's B",
        team_count=8,
    )
    womens_a = Event(
        tournament_id=tournament.id,
        category="womens",
        name="Women's A",
        team_count=8,
    )
    session.add_all([womens_b, womens_a])
    session.flush()

    helen = _add_team(session, womens_b.id, "Helen Robinson / Simone Lee", 1)
    amy = _add_team(session, womens_b.id, "Amy Carter / Terry Brooks", 2)
    kate = _add_team(session, womens_b.id, "Kate Miles / Nora Quinn", 3)
    ruth = _add_team(session, womens_b.id, "Ruth Adams / Ivy Stone", 4)
    jane = _add_team(session, womens_b.id, "Jane Cooper / Lily Grant", 5)
    pam = _add_team(session, womens_b.id, "Pam Walsh / Tess Young", 6)
    john_tbd = _add_team(session, womens_b.id, "John Smith / TBD", 7)
    mike = _add_team(session, womens_b.id, "Mike Jones / David Chen", 8)
    anna = _add_team(session, womens_a.id, "Anna Blake / Cara Diaz", 1)
    bella = _add_team(session, womens_a.id, "Bella Ford / Dana Hale", 2)

    playing_slot = _add_slot(
        session, tournament_id=tournament.id, version_id=version.id, start=time(13, 30), court_number=7
    )
    completed_slot = _add_slot(
        session, tournament_id=tournament.id, version_id=version.id, start=time(12, 0), court_number=1
    )
    waiting_slot = _add_slot(
        session, tournament_id=tournament.id, version_id=version.id, start=time(14, 30), court_number=3
    )
    one_check_slot = _add_slot(
        session, tournament_id=tournament.id, version_id=version.id, start=time(15, 30), court_number=4
    )
    upcoming_slot = _add_slot(
        session, tournament_id=tournament.id, version_id=version.id, start=time(16, 30), court_number=5
    )
    past_slot = _add_slot(
        session, tournament_id=tournament.id, version_id=version.id, start=time(11, 0), court_number=2
    )
    beyond_slot = _add_slot(
        session,
        tournament_id=tournament.id,
        version_id=version.id,
        start=time(3, 0),
        court_number=8,
        day=date(2026, 6, 6),
        end=time(4, 0),
    )
    same_time_slot_a = _add_slot(
        session, tournament_id=tournament.id, version_id=version.id, start=time(17, 30), court_number=9
    )
    same_time_slot_b = _add_slot(
        session, tournament_id=tournament.id, version_id=version.id, start=time(17, 30), court_number=10
    )
    tbd_slot = _add_slot(session, tournament_id=tournament.id, version_id=version.id, start=time(18, 0), court_number=6)

    playing = _add_match(
        session,
        tournament_id=tournament.id,
        event_id=womens_b.id,
        version_id=version.id,
        code="WOM_E1_WF_R1_M01",
        team_a=helen,
        team_b=amy,
        slot=playing_slot,
        runtime_status="IN_PROGRESS",
        sequence=1,
    )
    completed = _add_match(
        session,
        tournament_id=tournament.id,
        event_id=womens_b.id,
        version_id=version.id,
        code="WOM_E1_WF_R1_M02",
        team_a=kate,
        team_b=ruth,
        slot=completed_slot,
        runtime_status="FINAL",
        sequence=2,
    )
    waiting = _add_match(
        session,
        tournament_id=tournament.id,
        event_id=womens_b.id,
        version_id=version.id,
        code="WOM_E1_WF_R1_M03",
        team_a=jane,
        team_b=pam,
        slot=waiting_slot,
        sequence=3,
    )
    _check_in(session, tournament.id, version.id, waiting, "A")
    _check_in(session, tournament.id, version.id, waiting, "B")

    one_check = _add_match(
        session,
        tournament_id=tournament.id,
        event_id=womens_b.id,
        version_id=version.id,
        code="WOM_E1_WF_R1_M04",
        team_a=helen,
        team_b=kate,
        slot=one_check_slot,
        sequence=4,
    )
    _check_in(session, tournament.id, version.id, one_check, "A")

    upcoming = _add_match(
        session,
        tournament_id=tournament.id,
        event_id=womens_b.id,
        version_id=version.id,
        code="WOM_E1_WF_R1_M05",
        team_a=amy,
        team_b=ruth,
        slot=upcoming_slot,
        sequence=5,
    )
    past = _add_match(
        session,
        tournament_id=tournament.id,
        event_id=womens_b.id,
        version_id=version.id,
        code="WOM_E1_WF_R1_M06",
        team_a=kate,
        team_b=pam,
        slot=past_slot,
        sequence=6,
    )
    beyond = _add_match(
        session,
        tournament_id=tournament.id,
        event_id=womens_b.id,
        version_id=version.id,
        code="WOM_E1_WF_R1_M07",
        team_a=jane,
        team_b=ruth,
        slot=beyond_slot,
        sequence=7,
    )
    same_a = _add_match(
        session,
        tournament_id=tournament.id,
        event_id=womens_a.id,
        version_id=version.id,
        code="WOM_E2_WF_R1_M01",
        team_a=anna,
        team_b=bella,
        slot=same_time_slot_a,
        sequence=1,
    )
    same_b = _add_match(
        session,
        tournament_id=tournament.id,
        event_id=womens_b.id,
        version_id=version.id,
        code="WOM_E1_WF_R1_M08",
        team_a=mike,
        team_b=amy,
        slot=same_time_slot_b,
        sequence=8,
    )
    tbd_match = _add_match(
        session,
        tournament_id=tournament.id,
        event_id=womens_b.id,
        version_id=version.id,
        code="WOM_E1_WF_R1_M09",
        team_a=john_tbd,
        team_b=mike,
        slot=tbd_slot,
        sequence=9,
        placeholder_a="John / TBD",
        placeholder_b="Mike / David",
    )

    session.commit()
    return {
        "tournament": tournament,
        "version": version,
        "playing": playing,
        "completed": completed,
        "waiting": waiting,
        "one_check": one_check,
        "upcoming": upcoming,
        "past": past,
        "beyond": beyond,
        "same_a": same_a,
        "same_b": same_b,
        "tbd_match": tbd_match,
        "one_check_slot": one_check_slot,
        "womens_b": womens_b,
    }


def _ids(rows: List[dict]) -> List[int]:
    return [row["match_id"] for row in rows]


def _by_id(rows: List[dict], match_id: int) -> dict:
    return next(row for row in rows if row["match_id"] == match_id)


def test_currently_playing_match_appears_with_court_and_time(client, session, monkeypatch):
    _freeze_now(monkeypatch)
    data = _setup_board(session)
    resp = client.get(f"/api/tournaments/{data['tournament'].id}/display-board")
    assert resp.status_code == 200
    body = resp.json()
    playing_ids = _ids(body["currently_playing"])
    assert data["playing"].id in playing_ids
    playing = _by_id(body["currently_playing"], data["playing"].id)
    assert playing["court"] == "Court 7"
    assert playing["scheduled_time"] == "1:30 PM"
    assert playing["event_name"] == "Women's B"
    assert playing["team_a_names"] == "Helen / Simone"
    assert playing["team_b_names"] == "Amy / Terry"
    assert "Robinson" not in playing["team_a_names"]
    assert "Brooks" not in playing["team_b_names"]


def test_completed_match_absent_from_all_board_lists(client, session, monkeypatch):
    _freeze_now(monkeypatch)
    data = _setup_board(session)
    body = client.get(f"/api/tournaments/{data['tournament'].id}/display-board").json()
    all_ids = (
        _ids(body["currently_playing"])
        + _ids(body["waiting_for_court"])
        + _ids(body["upcoming"])
        + _ids(body["upcoming_12h"])
    )
    assert data["completed"].id not in all_ids


def test_one_team_checked_in_stays_upcoming_with_highlight(client, session, monkeypatch):
    _freeze_now(monkeypatch)
    data = _setup_board(session)
    body = client.get(f"/api/tournaments/{data['tournament'].id}/display-board").json()
    assert data["one_check"].id in _ids(body["upcoming"])
    assert data["one_check"].id not in _ids(body["waiting_for_court"])
    row = _by_id(body["upcoming"], data["one_check"].id)
    assert row["team_a_checked_in"] is True
    assert row["team_b_checked_in"] is False
    assert "court" not in row


def test_both_teams_checked_in_moves_to_waiting_without_court(client, session, monkeypatch):
    _freeze_now(monkeypatch)
    data = _setup_board(session)
    body = client.get(f"/api/tournaments/{data['tournament'].id}/display-board").json()
    assert data["waiting"].id in _ids(body["waiting_for_court"])
    assert data["waiting"].id not in _ids(body["upcoming"])
    row = _by_id(body["waiting_for_court"], data["waiting"].id)
    assert row["team_a_checked_in"] is True
    assert row["team_b_checked_in"] is True
    assert "court" not in row
    assert "Court" not in str(row)


def test_unstarted_not_both_checked_appears_upcoming_without_court(client, session, monkeypatch):
    _freeze_now(monkeypatch)
    data = _setup_board(session)
    body = client.get(f"/api/tournaments/{data['tournament'].id}/display-board").json()
    assert data["upcoming"].id in _ids(body["upcoming"])
    row = _by_id(body["upcoming"], data["upcoming"].id)
    assert row["team_a_checked_in"] is False
    assert row["team_b_checked_in"] is False
    assert "court" not in row


def test_starting_match_moves_to_currently_playing(client, session, monkeypatch):
    _freeze_now(monkeypatch)
    data = _setup_board(session)
    waiting = session.get(Match, data["waiting"].id)
    waiting.runtime_status = "IN_PROGRESS"
    session.add(waiting)
    session.commit()
    body = client.get(f"/api/tournaments/{data['tournament'].id}/display-board").json()
    assert data["waiting"].id in _ids(body["currently_playing"])
    assert data["waiting"].id not in _ids(body["waiting_for_court"])
    assert data["waiting"].id not in _ids(body["upcoming"])
    row = _by_id(body["currently_playing"], data["waiting"].id)
    assert row["court"] == "Court 3"


def test_completing_match_removes_it_from_display(client, session, monkeypatch):
    _freeze_now(monkeypatch)
    data = _setup_board(session)
    playing = session.get(Match, data["playing"].id)
    playing.runtime_status = "FINAL"
    session.add(playing)
    session.commit()
    body = client.get(f"/api/tournaments/{data['tournament'].id}/display-board").json()
    all_ids = (
        _ids(body["currently_playing"])
        + _ids(body["waiting_for_court"])
        + _ids(body["upcoming"])
        + _ids(body["upcoming_12h"])
    )
    assert data["playing"].id not in all_ids


def test_upcoming_12h_window_includes_and_excludes(client, session, monkeypatch):
    _freeze_now(monkeypatch)
    data = _setup_board(session)
    body = client.get(f"/api/tournaments/{data['tournament'].id}/display-board").json()
    ids_12h = _ids(body["upcoming_12h"])
    assert data["waiting"].id in ids_12h
    assert data["one_check"].id in ids_12h
    assert data["upcoming"].id in ids_12h
    assert data["tbd_match"].id in ids_12h
    assert data["same_a"].id in ids_12h
    assert data["beyond"].id not in ids_12h
    assert data["past"].id not in ids_12h
    assert data["playing"].id not in ids_12h
    assert data["completed"].id not in ids_12h


def test_upcoming_12h_sorted_and_grouped_by_scheduled_time(client, session, monkeypatch):
    _freeze_now(monkeypatch)
    data = _setup_board(session)
    body = client.get(f"/api/tournaments/{data['tournament'].id}/display-board").json()
    times = [row["scheduled_time"] for row in body["upcoming_12h"]]
    assert times == sorted(times, key=lambda label: datetime.strptime(label, "%I:%M %p"))
    group_labels = [group["scheduled_time"] for group in body["upcoming_12h_groups"]]
    assert group_labels == sorted(group_labels, key=lambda label: datetime.strptime(label, "%I:%M %p"))
    same_group = next(group for group in body["upcoming_12h_groups"] if group["scheduled_time"] == "5:30 PM")
    same_ids = _ids(same_group["matches"])
    assert same_ids == [data["same_a"].id, data["same_b"].id]


def test_upcoming_12h_names_event_and_no_court(client, session, monkeypatch):
    _freeze_now(monkeypatch)
    data = _setup_board(session)
    body = client.get(f"/api/tournaments/{data['tournament'].id}/display-board").json()
    for row in body["upcoming_12h"]:
        assert "court" not in row
        assert "Court" not in str(row)
        assert " / " in row["team_a_names"] or row["team_a_names"]
        assert row["team_b_names"]
        assert row["event_name"]
        assert "Robinson" not in row["team_a_names"]
        assert "Smith" not in row["team_a_names"]
        assert "Jones" not in row["team_b_names"]
    tbd_row = _by_id(body["upcoming_12h"], data["tbd_match"].id)
    assert tbd_row["team_a_names"] == "John / TBD"
    assert tbd_row["team_a_has_tbd"] is True
    assert tbd_row["team_b_names"] == "Mike / David"
    assert data["waiting"].id in _ids(body["upcoming_12h"])
    waiting_row = _by_id(body["upcoming_12h"], data["waiting"].id)
    assert waiting_row["team_a_names"] == "Jane / Lily"
    assert waiting_row["team_b_names"] == "Pam / Tess"


def test_rescheduled_match_appears_at_new_time(client, session, monkeypatch):
    _freeze_now(monkeypatch)
    data = _setup_board(session)
    new_slot = _add_slot(
        session,
        tournament_id=data["tournament"].id,
        version_id=data["version"].id,
        start=time(19, 45),
        court_number=11,
    )
    assignment = session.exec(select(MatchAssignment).where(MatchAssignment.match_id == data["upcoming"].id)).first()
    assignment.slot_id = new_slot.id
    session.add(assignment)
    session.commit()
    body = client.get(f"/api/tournaments/{data['tournament'].id}/display-board").json()
    row = _by_id(body["upcoming_12h"], data["upcoming"].id)
    assert row["scheduled_time"] == "7:45 PM"


def test_display_api_omits_private_and_financial_fields(client, session, monkeypatch):
    _freeze_now(monkeypatch)
    data = _setup_board(session)
    helen_player = Player(
        tournament_id=data["tournament"].id,
        full_name="Helen Robinson",
        email="helen@example.com",
        phone_e164="+15555550100",
    )
    session.add(helen_player)
    session.flush()
    session.add(TeamPlayer(team_id=data["playing"].team_a_id, player_id=helen_player.id, lineup_slot=1))
    session.commit()
    body = client.get(f"/api/tournaments/{data['tournament'].id}/display-board").json()
    leaked = collect_forbidden_keys(body)
    assert leaked == set()
    blob = str(body).lower()
    assert "helen@example.com" not in blob
    assert "+15555550100" not in blob
    assert "invoice" not in blob
    assert "payment" not in blob
    assert "refund" not in blob


def test_display_route_is_get_only(client, session, monkeypatch):
    _freeze_now(monkeypatch)
    data = _setup_board(session)
    url = f"/api/tournaments/{data['tournament'].id}/display-board"
    assert client.get(url).status_code == 200
    assert client.post(url, json={}).status_code == 405
    assert client.patch(url, json={}).status_code == 405
    assert client.put(url, json={}).status_code == 405
    assert client.delete(url).status_code == 405


def test_display_board_uses_player_first_names_when_linked(client, session, monkeypatch):
    _freeze_now(monkeypatch)
    data = _setup_board(session)
    p1 = Player(tournament_id=data["tournament"].id, full_name="Helen Robinson")
    p2 = Player(tournament_id=data["tournament"].id, full_name="Simone Lee")
    session.add_all([p1, p2])
    session.flush()
    session.add(TeamPlayer(team_id=data["playing"].team_a_id, player_id=p1.id, lineup_slot=1))
    session.add(TeamPlayer(team_id=data["playing"].team_a_id, player_id=p2.id, lineup_slot=2))
    session.commit()
    body = client.get(f"/api/tournaments/{data['tournament'].id}/display-board").json()
    playing = _by_id(body["currently_playing"], data["playing"].id)
    assert playing["team_a_names"] == "Helen / Simone"


def test_display_board_404_unknown_tournament(client, monkeypatch):
    _freeze_now(monkeypatch)
    resp = client.get("/api/tournaments/999999/display-board")
    assert resp.status_code == 404
