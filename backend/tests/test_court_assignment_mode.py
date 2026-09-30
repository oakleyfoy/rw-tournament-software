"""Hybrid court assignment: dynamic check-in by default, preassigned per event date."""

from datetime import date, datetime, time

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, func, select

from app.models.event import Event
from app.models.match import Match
from app.models.match_assignment import MatchAssignment
from app.models.match_checkin import MatchCheckIn
from app.models.schedule_slot import ScheduleSlot
from app.models.schedule_version import ScheduleVersion
from app.models.team import Team
from app.models.tournament import Tournament
from app.models.tournament_day import TournamentDay
from app.models.tournament_sms_settings import TournamentSmsSettings
from app.services.advancement_service import apply_advancement_for_final_match
from app.services.court_assignment_mode import (
    MODE_DYNAMIC_CHECKIN,
    MODE_PREASSIGNED,
    is_preassigned,
    preassigned_court_block_reason,
    replace_court_assignment_modes,
    resolve_court_assignment_mode,
    slots_overlap,
)
from app.services.sms_automation import SmsAutomationEngine
from app.utils.auto_assign import assign_by_match_ids
from app.utils.manual_assignment import validate_manual_reassignment


def test_missing_config_stays_dynamic_checkin():
    event = Event(tournament_id=1, category="mixed", name="Mixed A", team_count=8)
    assert resolve_court_assignment_mode(event, date(2026, 10, 2)) == MODE_DYNAMIC_CHECKIN
    assert is_preassigned(event, date(2026, 10, 2)) is False

    replace_court_assignment_modes(event, {"2026-10-02": MODE_PREASSIGNED, "2026-10-03": MODE_DYNAMIC_CHECKIN})
    assert is_preassigned(event, date(2026, 10, 2)) is True
    assert is_preassigned(event, date(2026, 10, 3)) is False
    assert "2026-10-03" not in (event.court_assignment_by_date_json or "")


def _team(session: Session, event_id: int, name: str, seed: int) -> Team:
    team = Team(event_id=event_id, name=name, seed=seed, display_name=name)
    session.add(team)
    session.flush()
    return team


def _match(
    session: Session,
    *,
    tournament: Tournament,
    event: Event,
    version: ScheduleVersion,
    code: str,
    slot: ScheduleSlot,
    team_a: Team,
    team_b: Team,
) -> Match:
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
        team_a_id=team_a.id,
        team_b_id=team_b.id,
        placeholder_side_a="A",
        placeholder_side_b="B",
        runtime_status="SCHEDULED",
    )
    session.add(match)
    session.flush()
    session.add(
        MatchAssignment(
            schedule_version_id=version.id,
            match_id=match.id,
            slot_id=slot.id,
            assigned_by="MANUAL",
        )
    )
    session.flush()
    return match


def _check_in(session: Session, tournament_id: int, version_id: int, match: Match) -> None:
    for side, team_id in (("A", match.team_a_id), ("B", match.team_b_id)):
        session.add(
            MatchCheckIn(
                tournament_id=tournament_id,
                schedule_version_id=version_id,
                match_id=match.id,
                team_id=team_id,
                side=side,
                team_checked_in=True,
                checked_in_at=datetime(2026, 10, 2, 8, 0),
            )
        )
    session.flush()


def _setup(session: Session):
    tournament = Tournament(
        name="Hybrid Courts",
        location="Beach",
        timezone="America/New_York",
        start_date=date(2026, 10, 2),
        end_date=date(2026, 10, 4),
        desk_management_mode="checkin_management",
    )
    session.add(tournament)
    session.flush()
    for day in (date(2026, 10, 2), date(2026, 10, 3), date(2026, 10, 4)):
        session.add(
            TournamentDay(
                tournament_id=tournament.id,
                date=day,
                is_active=True,
                courts_available=4,
            )
        )
    version = ScheduleVersion(tournament_id=tournament.id, version_number=1, status="final")
    session.add(version)
    session.flush()
    womens = Event(tournament_id=tournament.id, category="womens", name="Women's A", team_count=8)
    mixed = Event(tournament_id=tournament.id, category="mixed", name="Mixed A", team_count=8)
    session.add_all([womens, mixed])
    session.flush()
    replace_court_assignment_modes(womens, {"2026-10-02": MODE_PREASSIGNED})
    session.add(womens)

    friday = ScheduleSlot(
        tournament_id=tournament.id,
        schedule_version_id=version.id,
        day_date=date(2026, 10, 2),
        start_time=time(9, 0),
        end_time=time(10, 0),
        court_number=14,
        court_label="14",
        block_minutes=60,
    )
    friday_mixed = ScheduleSlot(
        tournament_id=tournament.id,
        schedule_version_id=version.id,
        day_date=date(2026, 10, 2),
        start_time=time(9, 0),
        end_time=time(10, 0),
        court_number=3,
        court_label="3",
        block_minutes=60,
    )
    saturday = ScheduleSlot(
        tournament_id=tournament.id,
        schedule_version_id=version.id,
        day_date=date(2026, 10, 3),
        start_time=time(11, 0),
        end_time=time(12, 0),
        court_number=8,
        court_label="8",
        block_minutes=60,
    )
    session.add_all([friday, friday_mixed, saturday])
    session.flush()

    friday_match = _match(
        session,
        tournament=tournament,
        event=womens,
        version=version,
        code="WOM_WF_R1_01",
        slot=friday,
        team_a=_team(session, womens.id, "Ada / Bea", 1),
        team_b=_team(session, womens.id, "Cara / Dee", 2),
    )
    mixed_match = _match(
        session,
        tournament=tournament,
        event=mixed,
        version=version,
        code="MIX_WF_R1_01",
        slot=friday_mixed,
        team_a=_team(session, mixed.id, "Eli / Finn", 1),
        team_b=_team(session, mixed.id, "Gus / Hal", 2),
    )
    saturday_match = _match(
        session,
        tournament=tournament,
        event=womens,
        version=version,
        code="WOM_WF_R1_02",
        slot=saturday,
        team_a=_team(session, womens.id, "Ivy / Jo", 3),
        team_b=_team(session, womens.id, "Kim / Lea", 4),
    )
    _check_in(session, tournament.id, version.id, friday_match)
    _check_in(session, tournament.id, version.id, mixed_match)
    tournament.public_schedule_version_id = version.id
    session.add(tournament)
    session.commit()
    return {
        "tournament": tournament,
        "version": version,
        "womens": womens,
        "mixed": mixed,
        "friday": friday_match,
        "mixed_match": mixed_match,
        "saturday": saturday_match,
    }


def test_modes_api_defaults_to_dynamic_and_saves_one_date(client, session: Session):
    data = _setup(session)
    tournament_id = data["tournament"].id
    resp = client.get(f"/api/tournaments/{tournament_id}/court-assignment-modes")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    womens = next(event for event in body["events"] if event["event_id"] == data["womens"].id)
    mixed = next(event for event in body["events"] if event["event_id"] == data["mixed"].id)
    assert womens["modes"]["2026-10-02"] == "PREASSIGNED"
    assert womens["modes"]["2026-10-03"] == "DYNAMIC_CHECKIN"
    assert mixed["modes"]["2026-10-02"] == "DYNAMIC_CHECKIN"

    mixed["modes"]["2026-10-04"] = "PREASSIGNED"
    saved = client.put(
        f"/api/tournaments/{tournament_id}/court-assignment-modes",
        json={"events": [{"event_id": mixed["event_id"], "modes": mixed["modes"]}]},
    )
    assert saved.status_code == 200, saved.text
    updated = next(event for event in saved.json()["events"] if event["event_id"] == data["mixed"].id)
    assert updated["modes"]["2026-10-04"] == "PREASSIGNED"
    assert updated["modes"]["2026-10-02"] == "DYNAMIC_CHECKIN"


def test_public_schedule_shows_only_preassigned_courts(client, session: Session):
    data = _setup(session)
    resp = client.get(f"/api/public/tournaments/{data['tournament'].id}/schedule")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["show_court_info"] is True
    by_id = {match["match_id"]: match for match in body["matches"]}
    assert by_id[data["friday"].id]["court_name"] == "Court 14"
    assert by_id[data["mixed_match"].id]["court_name"] is None
    assert by_id[data["saturday"].id]["court_name"] is None

    waterfall = client.get(f"/api/public/tournaments/{data['tournament'].id}/events/{data['womens'].id}/waterfall")
    assert waterfall.status_code == 200, waterfall.text
    rows = waterfall.json()["rows"]
    friday_line = next(
        row["center_box"]["top_line"] for row in rows if row["center_box"]["match_id"] == data["friday"].id
    )
    saturday_line = next(
        row["center_box"]["top_line"] for row in rows if row["center_box"]["match_id"] == data["saturday"].id
    )
    assert "Court 14" in friday_line
    assert "9:00 AM" in friday_line
    assert "Court" not in saturday_line


def test_desk_keeps_preassigned_court_out_of_ready_queue(client, session: Session):
    data = _setup(session)
    resp = client.get(f"/api/desk/tournaments/{data['tournament'].id}/snapshot")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    by_id = {match["match_id"]: match for match in body["matches"]}
    assert by_id[data["friday"].id]["court_name"] == "Court 14"
    assert by_id[data["friday"].id]["court_assignment_mode"] == "PREASSIGNED"
    assert by_id[data["mixed_match"].id]["court_name"] is None
    assert by_id[data["saturday"].id]["court_name"] is None
    ready_ids = {item["match_id"] for item in body["ready_queue"]}
    assert data["friday"].id not in ready_ids
    assert data["mixed_match"].id in ready_ids


def test_display_board_shows_preassigned_court_without_waiting_queue(client, session, monkeypatch):
    monkeypatch.setattr(
        "app.services.display_board.now_in_timezone",
        lambda tz: datetime(2026, 10, 2, 8, 30, tzinfo=tz),
    )
    data = _setup(session)
    resp = client.get(f"/api/tournaments/{data['tournament'].id}/display-board")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    upcoming_ids = {match["match_id"]: match for match in body["upcoming"]}
    waiting_ids = {match["match_id"] for match in body["waiting_for_court"]}
    assert data["friday"].id in upcoming_ids
    assert upcoming_ids[data["friday"].id]["court"] == "Court 14"
    assert data["friday"].id not in waiting_ids
    assert data["mixed_match"].id in waiting_ids
    mixed = next(match for match in body["waiting_for_court"] if match["match_id"] == data["mixed_match"].id)
    assert "court" not in mixed


def _freeze_friday_morning(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.display_board.now_in_timezone",
        lambda tz: datetime(2026, 10, 2, 8, 30, tzinfo=tz),
    )


def _clear_checkins(session: Session, tournament_id: int) -> None:
    rows = session.exec(select(MatchCheckIn).where(MatchCheckIn.tournament_id == tournament_id)).all()
    for row in rows:
        session.delete(row)
    session.commit()


def _check_in_side(session: Session, tournament_id: int, version_id: int, match: Match, side: str) -> None:
    session.add(
        MatchCheckIn(
            tournament_id=tournament_id,
            schedule_version_id=version_id,
            match_id=match.id,
            team_id=match.team_a_id if side == "A" else match.team_b_id,
            side=side,
            team_checked_in=True,
            checked_in_at=datetime(2026, 10, 2, 8, 0),
        )
    )
    session.commit()


def _friday_court(client, session: Session, data) -> str:
    schedule = client.get(f"/api/public/tournaments/{data['tournament'].id}/schedule")
    assert schedule.status_code == 200, schedule.text
    public_match = next(match for match in schedule.json()["matches"] if match["match_id"] == data["friday"].id)
    desk = client.get(f"/api/desk/tournaments/{data['tournament'].id}/snapshot")
    assert desk.status_code == 200, desk.text
    desk_body = desk.json()
    desk_match = next(match for match in desk_body["matches"] if match["match_id"] == data["friday"].id)
    ready_ids = {item["match_id"] for item in desk_body["ready_queue"]}
    board = client.get(f"/api/tournaments/{data['tournament'].id}/display-board")
    assert board.status_code == 200, board.text
    board_body = board.json()
    upcoming = {match["match_id"]: match for match in board_body["upcoming"]}
    waiting = {match["match_id"] for match in board_body["waiting_for_court"]}
    assert data["friday"].id not in ready_ids
    assert data["friday"].id not in waiting
    assert upcoming[data["friday"].id]["court"] == public_match["court_name"] == desk_match["court_name"]
    assignment = session.exec(select(MatchAssignment).where(MatchAssignment.match_id == data["friday"].id)).one()
    slot = session.get(ScheduleSlot, assignment.slot_id)
    assert slot is not None and slot.court_label == "14" and slot.start_time == time(9, 0)
    return desk_match["court_name"]


def test_preassigned_court_stays_visible_through_checkin_and_dynamic_does_not(client, session, monkeypatch):
    _freeze_friday_morning(monkeypatch)
    data = _setup(session)
    _clear_checkins(session, data["tournament"].id)

    assert _friday_court(client, session, data) == "Court 14"
    mixed_hidden = client.get(f"/api/public/tournaments/{data['tournament'].id}/schedule").json()
    mixed_row = next(match for match in mixed_hidden["matches"] if match["match_id"] == data["mixed_match"].id)
    assert mixed_row["court_name"] is None

    _check_in_side(session, data["tournament"].id, data["version"].id, data["friday"], "A")
    assert _friday_court(client, session, data) == "Court 14"

    _check_in_side(session, data["tournament"].id, data["version"].id, data["friday"], "B")
    assert _friday_court(client, session, data) == "Court 14"

    _check_in(session, data["tournament"].id, data["version"].id, data["mixed_match"])
    session.commit()
    desk = client.get(f"/api/desk/tournaments/{data['tournament'].id}/snapshot").json()
    ready_ids = {item["match_id"] for item in desk["ready_queue"]}
    assert data["friday"].id not in ready_ids
    assert data["mixed_match"].id in ready_ids
    mixed_desk = next(match for match in desk["matches"] if match["match_id"] == data["mixed_match"].id)
    assert mixed_desk["court_name"] is None
    board = client.get(f"/api/tournaments/{data['tournament'].id}/display-board").json()
    waiting = next(match for match in board["waiting_for_court"] if match["match_id"] == data["mixed_match"].id)
    assert "court" not in waiting


def test_message_rendering_includes_preassigned_court_and_hides_dynamic_slot_court(session: Session, monkeypatch):
    data = _setup(session)
    session.add(
        TournamentSmsSettings(
            tournament_id=data["tournament"].id,
            texts_enabled=True,
            auto_checkin_post_match_next=True,
            auto_court_change=True,
            auto_checkin_court_assigned=True,
        )
    )
    early = ScheduleSlot(
        tournament_id=data["tournament"].id,
        schedule_version_id=data["version"].id,
        day_date=date(2026, 10, 2),
        start_time=time(8, 0),
        end_time=time(9, 0),
        court_number=1,
        court_label="1",
        block_minutes=60,
    )
    session.add(early)
    session.flush()
    finished = Match(
        tournament_id=data["tournament"].id,
        event_id=data["womens"].id,
        schedule_version_id=data["version"].id,
        match_code="WOM_WF_R1_00",
        match_type="WF",
        round_number=1,
        round_index=1,
        sequence_in_round=9,
        duration_minutes=60,
        team_a_id=data["friday"].team_a_id,
        team_b_id=data["friday"].team_b_id,
        placeholder_side_a="A",
        placeholder_side_b="B",
        runtime_status="FINAL",
        winner_team_id=data["friday"].team_a_id,
    )
    session.add(finished)
    session.flush()
    session.add(
        MatchAssignment(
            schedule_version_id=data["version"].id,
            match_id=finished.id,
            slot_id=early.id,
            assigned_by="MANUAL",
        )
    )
    dynamic_finished = Match(
        tournament_id=data["tournament"].id,
        event_id=data["mixed"].id,
        schedule_version_id=data["version"].id,
        match_code="MIX_WF_R1_00",
        match_type="WF",
        round_number=1,
        round_index=1,
        sequence_in_round=9,
        duration_minutes=60,
        team_a_id=data["mixed_match"].team_a_id,
        team_b_id=data["mixed_match"].team_b_id,
        placeholder_side_a="A",
        placeholder_side_b="B",
        runtime_status="FINAL",
        winner_team_id=data["mixed_match"].team_a_id,
    )
    session.add(dynamic_finished)
    session.flush()
    dynamic_early = ScheduleSlot(
        tournament_id=data["tournament"].id,
        schedule_version_id=data["version"].id,
        day_date=date(2026, 10, 2),
        start_time=time(8, 0),
        end_time=time(9, 0),
        court_number=4,
        court_label="4",
        block_minutes=60,
    )
    session.add(dynamic_early)
    session.flush()
    session.add(
        MatchAssignment(
            schedule_version_id=data["version"].id,
            match_id=dynamic_finished.id,
            slot_id=dynamic_early.id,
            assigned_by="MANUAL",
        )
    )
    session.commit()

    engine = SmsAutomationEngine(session, data["tournament"], data["version"].id)
    preassigned_plan = engine._match_finalized_sms_plan(finished)
    dynamic_plan = engine._match_finalized_sms_plan(dynamic_finished)
    assert preassigned_plan["message_type"] == "checkin_post_match_next"
    assert dynamic_plan["message_type"] == "checkin_post_match_next"
    preassigned_messages = [job["message"] for job in preassigned_plan["jobs"]]
    dynamic_messages = [job["message"] for job in dynamic_plan["jobs"]]
    assert preassigned_messages
    assert dynamic_messages
    assert all(
        "Court 14" in message and "9:00 AM" in message and "Friday" in message for message in preassigned_messages
    )
    assert all("check in at the desk" not in message.lower() for message in preassigned_messages)
    assert all("Court" not in message for message in dynamic_messages)

    team = session.get(Team, data["friday"].team_a_id)
    first_match_body = engine._render_template_message(
        team=team,
        template_body="{team_name}: Your first match is {date} at {time}. Please arrive at least 30 mins early and check in at the desk.",
        match=data["friday"],
        slot=session.exec(select(ScheduleSlot).where(ScheduleSlot.court_number == 14)).one(),
        opponent=None,
    )
    assert "Court 14" in first_match_body
    dynamic_team = session.get(Team, data["mixed_match"].team_a_id)
    dynamic_body = engine._render_template_message(
        team=dynamic_team,
        template_body="{team_name}: Your first match is {date} at {time}. Please arrive at least 30 mins early and check in at the desk.",
        match=data["mixed_match"],
        slot=session.get(
            ScheduleSlot,
            session.exec(select(MatchAssignment).where(MatchAssignment.match_id == data["mixed_match"].id))
            .one()
            .slot_id,
        ),
        opponent=None,
    )
    assert "Court" not in dynamic_body

    mixed_assignment = session.exec(
        select(MatchAssignment).where(MatchAssignment.match_id == data["mixed_match"].id)
    ).one()
    mixed_assignment.assigned_by = "CHECKIN_DESK"
    session.add(mixed_assignment)
    session.commit()
    assigned_engine = SmsAutomationEngine(session, data["tournament"], data["version"].id)
    assigned_body = assigned_engine._render_template_message(
        team=dynamic_team,
        template_body="{team_name}: Court assigned. Please go to {court}.",
        match=data["mixed_match"],
        slot=session.get(ScheduleSlot, mixed_assignment.slot_id),
        opponent=None,
    )
    assert "Court 3" in assigned_body

    court_18 = ScheduleSlot(
        tournament_id=data["tournament"].id,
        schedule_version_id=data["version"].id,
        day_date=date(2026, 10, 2),
        start_time=time(9, 0),
        end_time=time(10, 0),
        court_number=18,
        court_label="18",
        block_minutes=60,
    )
    session.add(court_18)
    session.commit()
    sent: list[str] = []

    def _capture_message(**kwargs):
        sent.append(kwargs["message"])

        class _Result:
            total = sent_count = failed = 0
            skipped_no_phone = skipped_consent = skipped_dedupe = skipped_test_mode = 0
            results: list = []

        _Result.sent = 0
        return _Result()

    monkeypatch.setattr(engine, "_send_message_to_team", _capture_message)
    old_slot_id = (
        session.exec(select(MatchAssignment).where(MatchAssignment.match_id == data["friday"].id)).one().slot_id
    )
    engine.handle_court_change(data["friday"], old_slot_id, court_18.id)
    assert sent
    assert "Court 18" in sent[0]
    assert "Court 14" not in sent[0]
    assert "9:00 AM" in sent[0]


def test_preassigned_court_change_updates_player_and_staff_surfaces(client, session, monkeypatch):
    _freeze_friday_morning(monkeypatch)
    data = _setup(session)
    court_18 = ScheduleSlot(
        tournament_id=data["tournament"].id,
        schedule_version_id=data["version"].id,
        day_date=date(2026, 10, 2),
        start_time=time(9, 0),
        end_time=time(10, 0),
        court_number=18,
        court_label="18",
        block_minutes=60,
    )
    session.add(court_18)
    session.flush()
    assignment = session.exec(select(MatchAssignment).where(MatchAssignment.match_id == data["friday"].id)).one()
    assignment.slot_id = court_18.id
    session.add(assignment)
    session.commit()

    schedule = client.get(f"/api/public/tournaments/{data['tournament'].id}/schedule").json()
    public_match = next(match for match in schedule["matches"] if match["match_id"] == data["friday"].id)
    assert public_match["court_name"] == "Court 18"
    assert "14" not in (public_match["court_name"] or "")

    waterfall = client.get(
        f"/api/public/tournaments/{data['tournament'].id}/events/{data['womens'].id}/waterfall"
    ).json()
    friday_line = next(
        row["center_box"]["top_line"] for row in waterfall["rows"] if row["center_box"]["match_id"] == data["friday"].id
    )
    assert "Court 18" in friday_line
    assert "Court 14" not in friday_line

    desk = client.get(f"/api/desk/tournaments/{data['tournament'].id}/snapshot").json()
    desk_match = next(match for match in desk["matches"] if match["match_id"] == data["friday"].id)
    assert desk_match["court_name"] == "Court 18"

    board = client.get(f"/api/tournaments/{data['tournament'].id}/display-board").json()
    upcoming = next(match for match in board["upcoming"] if match["match_id"] == data["friday"].id)
    assert upcoming["court"] == "Court 18"
    assert all(
        match.get("court") != "Court 14"
        for match in board["upcoming"] + board["waiting_for_court"] + board["currently_playing"]
    )


def test_waterfall_advancement_keeps_existing_preassigned_court(client, session: Session):
    tournament = Tournament(
        name="Waterfall Advance",
        location="Beach",
        timezone="America/New_York",
        start_date=date(2026, 10, 2),
        end_date=date(2026, 10, 2),
        desk_management_mode="checkin_management",
    )
    session.add(tournament)
    session.flush()
    version = ScheduleVersion(tournament_id=tournament.id, version_number=1, status="final")
    session.add(version)
    session.flush()
    event = Event(tournament_id=tournament.id, category="womens", name="Women's A", team_count=4)
    session.add(event)
    session.flush()
    replace_court_assignment_modes(event, {"2026-10-02": MODE_PREASSIGNED})
    session.add(event)
    teams = []
    for seed, name in ((1, "Ada / Bea"), (2, "Cara / Dee"), (3, "Eve / Fay"), (4, "Gia / Hope")):
        team = Team(event_id=event.id, name=name, seed=seed, display_name=name)
        session.add(team)
        teams.append(team)
    session.flush()
    slot = ScheduleSlot(
        tournament_id=tournament.id,
        schedule_version_id=version.id,
        day_date=date(2026, 10, 2),
        start_time=time(9, 0),
        end_time=time(10, 0),
        court_number=14,
        court_label="14",
        block_minutes=60,
    )
    session.add(slot)
    session.flush()
    first = Match(
        tournament_id=tournament.id,
        event_id=event.id,
        schedule_version_id=version.id,
        match_code="WOM_WF_R1_01",
        match_type="WF",
        round_number=1,
        round_index=1,
        sequence_in_round=1,
        duration_minutes=60,
        team_a_id=teams[0].id,
        team_b_id=teams[1].id,
        placeholder_side_a="Seed 1",
        placeholder_side_b="Seed 2",
        runtime_status="FINAL",
        winner_team_id=teams[0].id,
    )
    second = Match(
        tournament_id=tournament.id,
        event_id=event.id,
        schedule_version_id=version.id,
        match_code="WOM_WF_R1_02",
        match_type="WF",
        round_number=1,
        round_index=1,
        sequence_in_round=2,
        duration_minutes=60,
        team_a_id=teams[2].id,
        team_b_id=teams[3].id,
        placeholder_side_a="Seed 3",
        placeholder_side_b="Seed 4",
        runtime_status="FINAL",
        winner_team_id=teams[2].id,
    )
    session.add_all([first, second])
    session.flush()
    future = Match(
        tournament_id=tournament.id,
        event_id=event.id,
        schedule_version_id=version.id,
        match_code="WOM_WF_R2_W01",
        match_type="WF",
        round_number=2,
        round_index=2,
        sequence_in_round=1,
        duration_minutes=60,
        team_a_id=None,
        team_b_id=None,
        placeholder_side_a="Winner Match 1",
        placeholder_side_b="Winner Match 2",
        source_match_a_id=first.id,
        source_match_b_id=second.id,
        source_a_role="WINNER",
        source_b_role="WINNER",
        runtime_status="SCHEDULED",
    )
    session.add(future)
    session.flush()
    future_assignment = MatchAssignment(
        schedule_version_id=version.id,
        match_id=future.id,
        slot_id=slot.id,
        assigned_by="MANUAL",
    )
    session.add(future_assignment)
    session.flush()
    match_count = session.exec(
        select(func.count()).select_from(Match).where(Match.schedule_version_id == version.id)
    ).one()
    assignment_count = session.exec(
        select(func.count()).select_from(MatchAssignment).where(MatchAssignment.schedule_version_id == version.id)
    ).one()
    assert future.team_a_id is None and future.team_b_id is None
    tournament.public_schedule_version_id = version.id
    session.add(tournament)
    session.commit()
    future_id = future.id
    slot_id = slot.id
    assignment_id = future_assignment.id

    apply_advancement_for_final_match(session, first.id)
    apply_advancement_for_final_match(session, second.id)
    session.expire_all()

    advanced = session.get(Match, future_id)
    kept_slot = session.get(ScheduleSlot, slot_id)
    kept_assignment = session.get(MatchAssignment, assignment_id)
    assert advanced is not None
    assert advanced.team_a_id == teams[0].id
    assert advanced.team_b_id == teams[2].id
    assert kept_assignment is not None and kept_assignment.slot_id == slot_id and kept_assignment.match_id == future_id
    assert kept_slot is not None
    assert kept_slot.start_time == time(9, 0)
    assert kept_slot.court_number == 14
    assert kept_slot.court_label == "14"
    assert (
        session.exec(select(func.count()).select_from(Match).where(Match.schedule_version_id == version.id)).one()
        == match_count
    )
    assert (
        session.exec(
            select(func.count()).select_from(MatchAssignment).where(MatchAssignment.schedule_version_id == version.id)
        ).one()
        == assignment_count
    )

    waterfall = client.get(f"/api/public/tournaments/{tournament.id}/events/{event.id}/waterfall")
    assert waterfall.status_code == 200, waterfall.text
    body = waterfall.json()
    winner = next(
        row["winner_box"] for row in body["rows"] if row["winner_box"] and row["winner_box"]["match_id"] == future_id
    )
    assert "Ada / Bea" in winner["line1"]
    assert "Eve / Fay" in winner["line2"]
    assert "Court 14" in winner["top_line"]
    assert "9:00 AM" in winner["top_line"]


def test_preassigned_court_is_not_offered_until_the_reservation_ends(client, session: Session):
    tournament = Tournament(
        name="Court Block",
        location="Beach",
        timezone="America/New_York",
        start_date=date(2026, 10, 2),
        end_date=date(2026, 10, 2),
        desk_management_mode="checkin_management",
    )
    session.add(tournament)
    session.flush()
    version = ScheduleVersion(tournament_id=tournament.id, version_number=1, status="draft")
    session.add(version)
    session.flush()
    womens = Event(tournament_id=tournament.id, category="womens", name="Women's A", team_count=4)
    mixed = Event(tournament_id=tournament.id, category="mixed", name="Mixed A", team_count=4)
    session.add_all([womens, mixed])
    session.flush()
    replace_court_assignment_modes(womens, {"2026-10-02": MODE_PREASSIGNED})
    session.add(womens)

    def add_slot(court: int, start_hour: int, start_minute: int = 0):
        end_hour = start_hour + 1 if start_minute == 0 else start_hour + 1
        end_minute = start_minute
        slot = ScheduleSlot(
            tournament_id=tournament.id,
            schedule_version_id=version.id,
            day_date=date(2026, 10, 2),
            start_time=time(start_hour, start_minute),
            end_time=time(end_hour % 24, end_minute),
            court_number=court,
            court_label=str(court),
            block_minutes=60,
        )
        session.add(slot)
        session.flush()
        return slot

    reserved = add_slot(14, 9)
    overlap = add_slot(14, 9, 30)
    open_court = add_slot(15, 9)
    dynamic_slot = add_slot(2, 9)
    team_a = Team(event_id=womens.id, name="Ada / Bea", seed=1, display_name="Ada / Bea")
    team_b = Team(event_id=womens.id, name="Cara / Dee", seed=2, display_name="Cara / Dee")
    team_c = Team(event_id=mixed.id, name="Eli / Finn", seed=1, display_name="Eli / Finn")
    team_d = Team(event_id=mixed.id, name="Gus / Hal", seed=2, display_name="Gus / Hal")
    session.add_all([team_a, team_b, team_c, team_d])
    session.flush()
    reserved_match = Match(
        tournament_id=tournament.id,
        event_id=womens.id,
        schedule_version_id=version.id,
        match_code="WOM_WF_R2_W01",
        match_type="WF",
        round_number=2,
        round_index=2,
        sequence_in_round=1,
        duration_minutes=60,
        placeholder_side_a="Winner Match 1",
        placeholder_side_b="Winner Match 2",
        runtime_status="SCHEDULED",
    )
    dynamic_match = Match(
        tournament_id=tournament.id,
        event_id=mixed.id,
        schedule_version_id=version.id,
        match_code="MIX_WF_R1_01",
        match_type="WF",
        round_number=1,
        round_index=1,
        sequence_in_round=1,
        duration_minutes=60,
        team_a_id=team_c.id,
        team_b_id=team_d.id,
        placeholder_side_a="A",
        placeholder_side_b="B",
        runtime_status="SCHEDULED",
    )
    session.add_all([reserved_match, dynamic_match])
    session.flush()
    session.add(
        MatchAssignment(
            schedule_version_id=version.id, match_id=reserved_match.id, slot_id=reserved.id, assigned_by="MANUAL"
        )
    )
    session.add(
        MatchAssignment(
            schedule_version_id=version.id, match_id=dynamic_match.id, slot_id=dynamic_slot.id, assigned_by="MANUAL"
        )
    )
    _check_in(session, tournament.id, version.id, dynamic_match)
    session.commit()

    assert slots_overlap(reserved, overlap) is True
    assert preassigned_court_block_reason(overlap, [(reserved_match, reserved)])

    snap = client.get(f"/api/desk/tournaments/{tournament.id}/snapshot?version_id={version.id}")
    assert snap.status_code == 200, snap.text
    body = snap.json()
    offered_ids = {slot["slot_id"] for slot in body["available_slots"]}
    assert reserved.id not in offered_ids
    assert overlap.id not in offered_ids
    assert open_court.id in offered_ids
    assert dynamic_match.id in {item["match_id"] for item in body["ready_queue"]}

    blocked = client.post(
        f"/api/desk/tournaments/{tournament.id}/checkin/assign",
        json={"version_id": version.id, "match_id": dynamic_match.id, "slot_id": reserved.id},
    )
    assert blocked.status_code == 409, blocked.text
    overlapping = client.post(
        f"/api/desk/tournaments/{tournament.id}/checkin/assign",
        json={"version_id": version.id, "match_id": dynamic_match.id, "slot_id": overlap.id},
    )
    assert overlapping.status_code == 409, overlapping.text

    reserved_match.runtime_status = "FINAL"
    session.add(reserved_match)
    session.commit()
    released = client.get(f"/api/desk/tournaments/{tournament.id}/snapshot?version_id={version.id}").json()
    assert reserved.id in {slot["slot_id"] for slot in released["available_slots"]}


def test_identical_court_time_cannot_be_double_booked_and_overlap_is_rejected(session: Session):
    tournament = Tournament(
        name="Double Book",
        location="Beach",
        timezone="America/New_York",
        start_date=date(2026, 10, 2),
        end_date=date(2026, 10, 2),
    )
    session.add(tournament)
    session.flush()
    version = ScheduleVersion(tournament_id=tournament.id, version_number=1, status="draft")
    session.add(version)
    session.flush()
    event = Event(tournament_id=tournament.id, category="mixed", name="Mixed A", team_count=4)
    session.add(event)
    session.flush()
    first = ScheduleSlot(
        tournament_id=tournament.id,
        schedule_version_id=version.id,
        day_date=date(2026, 10, 2),
        start_time=time(9, 0),
        end_time=time(10, 0),
        court_number=14,
        court_label="14",
        block_minutes=60,
    )
    session.add(first)
    session.commit()
    duplicate = ScheduleSlot(
        tournament_id=tournament.id,
        schedule_version_id=version.id,
        day_date=date(2026, 10, 2),
        start_time=time(9, 0),
        end_time=time(10, 0),
        court_number=14,
        court_label="14",
        block_minutes=60,
    )
    session.add(duplicate)
    try:
        session.commit()
        raised = False
    except IntegrityError:
        session.rollback()
        raised = True
    assert raised is True

    version = session.exec(select(ScheduleVersion).where(ScheduleVersion.tournament_id == tournament.id)).one()
    event = session.exec(select(Event).where(Event.tournament_id == tournament.id)).one()
    first = session.exec(select(ScheduleSlot).where(ScheduleSlot.schedule_version_id == version.id)).one()
    later = ScheduleSlot(
        tournament_id=tournament.id,
        schedule_version_id=version.id,
        day_date=date(2026, 10, 2),
        start_time=time(9, 30),
        end_time=time(10, 30),
        court_number=14,
        court_label="14",
        block_minutes=60,
    )
    session.add(later)
    session.flush()
    team_a = Team(event_id=event.id, name="Ada / Bea", seed=1, display_name="Ada / Bea")
    team_b = Team(event_id=event.id, name="Cara / Dee", seed=2, display_name="Cara / Dee")
    team_c = Team(event_id=event.id, name="Eve / Fay", seed=3, display_name="Eve / Fay")
    team_d = Team(event_id=event.id, name="Gia / Hope", seed=4, display_name="Gia / Hope")
    session.add_all([team_a, team_b, team_c, team_d])
    session.flush()
    match_a = Match(
        tournament_id=tournament.id,
        event_id=event.id,
        schedule_version_id=version.id,
        match_code="MIX_A",
        match_type="WF",
        round_number=1,
        round_index=1,
        sequence_in_round=1,
        duration_minutes=60,
        team_a_id=team_a.id,
        team_b_id=team_b.id,
        placeholder_side_a="A",
        placeholder_side_b="B",
    )
    match_b = Match(
        tournament_id=tournament.id,
        event_id=event.id,
        schedule_version_id=version.id,
        match_code="MIX_B",
        match_type="WF",
        round_number=1,
        round_index=1,
        sequence_in_round=2,
        duration_minutes=60,
        team_a_id=team_c.id,
        team_b_id=team_d.id,
        placeholder_side_a="C",
        placeholder_side_b="D",
    )
    session.add_all([match_a, match_b])
    session.flush()
    session.add(
        MatchAssignment(schedule_version_id=version.id, match_id=match_a.id, slot_id=first.id, assigned_by="MANUAL")
    )
    session.commit()
    allowed, reason = validate_manual_reassignment(session, match_b.id, later.id, version.id)
    assert allowed is False
    assert reason and "overlap" in reason.lower()


def test_auto_assign_respects_preassigned_window_and_final_releases_early(client, session: Session):
    tournament = Tournament(
        name="Auto Reserve",
        location="Beach",
        timezone="America/New_York",
        start_date=date(2026, 10, 2),
        end_date=date(2026, 10, 2),
        desk_management_mode="checkin_management",
    )
    session.add(tournament)
    session.flush()
    version = ScheduleVersion(tournament_id=tournament.id, version_number=1, status="draft")
    session.add(version)
    session.flush()
    womens = Event(tournament_id=tournament.id, category="womens", name="Women's A", team_count=4)
    mixed = Event(tournament_id=tournament.id, category="mixed", name="Mixed A", team_count=8)
    session.add_all([womens, mixed])
    session.flush()
    replace_court_assignment_modes(womens, {"2026-10-02": MODE_PREASSIGNED})
    session.add(womens)

    def add_slot(court: int, start_hour: int, start_minute: int = 0):
        slot = ScheduleSlot(
            tournament_id=tournament.id,
            schedule_version_id=version.id,
            day_date=date(2026, 10, 2),
            start_time=time(start_hour, start_minute),
            end_time=time(start_hour + 1, start_minute),
            court_number=court,
            court_label=str(court),
            block_minutes=60,
        )
        session.add(slot)
        session.flush()
        return slot

    at_nine = add_slot(14, 9)
    at_nine_thirty = add_slot(14, 9, 30)
    other_court = add_slot(15, 9, 30)
    at_ten = add_slot(14, 10)
    assert slots_overlap(at_nine, at_nine_thirty) is True
    assert slots_overlap(at_nine, at_ten) is False

    names = (
        (1, "Ada / Bea"),
        (2, "Cara / Dee"),
        (3, "Eli / Finn"),
        (4, "Gus / Hal"),
        (5, "Ivy / Jo"),
        (6, "Kim / Lee"),
        (7, "Mia / Noe"),
        (8, "Ora / Pia"),
    )
    teams = []
    for seed, name in names:
        team = Team(event_id=mixed.id, name=name, seed=seed, display_name=name)
        session.add(team)
        teams.append(team)
    session.flush()
    reserved_match = Match(
        tournament_id=tournament.id,
        event_id=womens.id,
        schedule_version_id=version.id,
        match_code="WOM_WF_R2_W01",
        match_type="WF",
        round_number=2,
        round_index=2,
        sequence_in_round=1,
        duration_minutes=60,
        placeholder_side_a="Winner Match 1",
        placeholder_side_b="Winner Match 2",
        runtime_status="SCHEDULED",
    )
    session.add(reserved_match)
    session.flush()
    session.add(
        MatchAssignment(
            schedule_version_id=version.id,
            match_id=reserved_match.id,
            slot_id=at_nine.id,
            assigned_by="MANUAL",
        )
    )

    def dynamic_match(code: str, sequence: int, team_a: Team, team_b: Team, duration_minutes: int = 60) -> Match:
        match = Match(
            tournament_id=tournament.id,
            event_id=mixed.id,
            schedule_version_id=version.id,
            match_code=code,
            match_type="WF",
            round_number=1,
            round_index=1,
            sequence_in_round=sequence,
            duration_minutes=duration_minutes,
            team_a_id=team_a.id,
            team_b_id=team_b.id,
            placeholder_side_a="A",
            placeholder_side_b="B",
            runtime_status="SCHEDULED",
        )
        session.add(match)
        session.flush()
        return match

    first = dynamic_match("MIX_WF_R1_01", 1, teams[0], teams[1])
    second = dynamic_match("MIX_WF_R1_02", 2, teams[2], teams[3])
    third = dynamic_match("MIX_WF_R1_03", 3, teams[4], teams[5], duration_minutes=30)
    session.commit()

    from app.services.court_assignment_mode import preassigned_reservations

    reservations = preassigned_reservations(session, version.id)
    assert preassigned_court_block_reason(at_nine, reservations)
    assert preassigned_court_block_reason(at_nine_thirty, reservations)
    assert preassigned_court_block_reason(at_ten, reservations) is None

    overlap_allowed, overlap_reason = validate_manual_reassignment(session, first.id, at_nine_thirty.id, version.id)
    next_block_allowed, next_block_reason = validate_manual_reassignment(session, first.id, at_ten.id, version.id)
    assert overlap_allowed is False
    assert overlap_reason and "reserved" in overlap_reason.lower()
    assert next_block_allowed is True, next_block_reason

    same_time = client.post(
        f"/api/desk/tournaments/{tournament.id}/checkin/assign",
        json={"version_id": version.id, "match_id": first.id, "slot_id": at_nine.id},
    )
    overlapping = client.post(
        f"/api/desk/tournaments/{tournament.id}/checkin/assign",
        json={"version_id": version.id, "match_id": first.id, "slot_id": at_nine_thirty.id},
    )
    next_block = client.post(
        f"/api/desk/tournaments/{tournament.id}/checkin/assign",
        json={"version_id": version.id, "match_id": first.id, "slot_id": at_ten.id},
    )
    assert same_time.status_code == 409
    assert overlapping.status_code == 409
    assert next_block.status_code != 409
    assert "reserved" not in next_block.text.lower()

    first_result = assign_by_match_ids(session, version.id, [first.id])
    assert first_result.assigned_count == 1
    first_assignment = session.exec(select(MatchAssignment).where(MatchAssignment.match_id == first.id)).one()
    assert first_assignment.slot_id == other_court.id

    second_result = assign_by_match_ids(session, version.id, [second.id])
    assert second_result.assigned_count == 1
    second_assignment = session.exec(select(MatchAssignment).where(MatchAssignment.match_id == second.id)).one()
    assert second_assignment.slot_id == at_ten.id

    reserved_match.runtime_status = "FINAL"
    session.add(reserved_match)
    session.commit()
    released = preassigned_reservations(session, version.id)
    assert preassigned_court_block_reason(at_nine_thirty, released) is None
    early_allowed, early_reason = validate_manual_reassignment(session, third.id, at_nine_thirty.id, version.id)
    assert early_allowed is True, early_reason
    third_result = assign_by_match_ids(session, version.id, [third.id])
    assert third_result.assigned_count == 1
    third_assignment = session.exec(select(MatchAssignment).where(MatchAssignment.match_id == third.id)).one()
    assert third_assignment.slot_id == at_nine_thirty.id
