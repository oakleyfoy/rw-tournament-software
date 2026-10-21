"""Return an assigned or live match to Waiting for Check-In.

Back To Ready To Go keeps check-in. This action clears it and releases the live court.
"""

from datetime import time

from sqlmodel import Session, select

from app.models.match import Match
from app.models.schedule_slot import ScheduleSlot
from app.models.tournament import Tournament
from app.models.match_assignment import MatchAssignment
from app.models.match_checkin import MatchCheckIn
from app.models.match_player_checkin import MatchPlayerCheckIn
from app.models.team_photo import TeamOfficialPhoto
from app.services.preassigned_dispatch import (
    OUTCOME_READY_TO_START,
    OUTCOME_WAITING_CHECKIN,
    dispatch_court,
    evaluate_eligibility,
    start_match_canonical,
)
from app.services.schedule_slot_availability import slot_key_for_slot
from tests.test_desk import _add_two_players_for_team, _setup_draft_for_move
from tests.test_preassigned_court_automation import _check_in, _setup_automation


def _enable_checkin(client, tournament_id: int, version_id: int) -> None:
    resp = client.patch(
        f"/api/desk/tournaments/{tournament_id}/management-mode",
        json={"version_id": version_id, "management_mode": "checkin_management"},
    )
    assert resp.status_code == 200


def _check_in_side(client, tournament_id: int, version_id: int, match_id: int, side: str, players) -> None:
    team = client.patch(
        f"/api/desk/tournaments/{tournament_id}/matches/{match_id}/checkin/team",
        json={"version_id": version_id, "side": side, "checked_in": True},
    )
    assert team.status_code == 200
    for player in players:
        player_resp = client.patch(
            f"/api/desk/tournaments/{tournament_id}/matches/{match_id}/checkin/player",
            json={
                "version_id": version_id,
                "side": side,
                "player_id": player.id,
                "checked_in": True,
            },
        )
        assert player_resp.status_code == 200


def _snapshot(client, tournament_id: int, version_id: int) -> dict:
    resp = client.get(f"/api/desk/tournaments/{tournament_id}/snapshot", params={"version_id": version_id})
    assert resp.status_code == 200
    return resp.json()


def _return_to_waiting(client, tournament_id: int, version_id: int, match_id: int):
    return client.post(
        f"/api/desk/tournaments/{tournament_id}/matches/{match_id}/return-to-waiting-checkin",
        json={"version_id": version_id},
    )


def _match_row(body: dict, match_id: int) -> dict:
    return next(row for row in body["matches"] if row["match_id"] == match_id)


def _checkin_row(body: dict, match_id: int) -> dict:
    return next(row for row in body["checkin_matches"] if row["match_id"] == match_id)


def test_assigned_match_returns_to_waiting_for_checkin(client, session: Session):
    tournament, version, _event, teams, matches, _slots = _setup_draft_for_move(session)
    assigned, other = matches
    assigned.source_match_a_id = other.id
    session.add(assigned)
    session.commit()
    alpha = _add_two_players_for_team(session, tournament.id, teams[0].id, "Alpha")
    delta = _add_two_players_for_team(session, tournament.id, teams[3].id, "Delta")
    bravo = _add_two_players_for_team(session, tournament.id, teams[1].id, "Bravo")
    _enable_checkin(client, tournament.id, version.id)
    _check_in_side(client, tournament.id, version.id, assigned.id, "A", alpha)
    _check_in_side(client, tournament.id, version.id, assigned.id, "B", delta)
    _check_in_side(client, tournament.id, version.id, other.id, "A", bravo)

    before = _snapshot(client, tournament.id, version.id)
    assert assigned.id in {row["match_id"] for row in before["ready_queue"]}
    assert _match_row(before, assigned.id)["status"] == "SCHEDULED"
    assignment_before = session.exec(
        select(MatchAssignment).where(MatchAssignment.match_id == assigned.id)
    ).one()
    other_assignment_before = session.exec(
        select(MatchAssignment).where(MatchAssignment.match_id == other.id)
    ).one()
    other_slot_id = other_assignment_before.slot_id
    assignment_id = assignment_before.id
    slot_id = assignment_before.slot_id

    first = _return_to_waiting(client, tournament.id, version.id, assigned.id)
    assert first.status_code == 200
    assert first.json()["status"] == "SCHEDULED"
    second = _return_to_waiting(client, tournament.id, version.id, assigned.id)
    assert second.status_code == 200

    session.expire_all()
    after = _snapshot(client, tournament.id, version.id)
    assert assigned.id not in {row["match_id"] for row in after["ready_queue"]}
    assert assigned.id not in {row["match_id"] for row in after["ready_assigned_queue"]}
    waiting = _checkin_row(after, assigned.id)
    assert waiting["match_ready"] is False
    assert waiting["side_a"]["team_checked_in"] is False
    assert waiting["side_b"]["team_checked_in"] is False
    assert all(player["checked_in"] is False for player in waiting["side_a"]["players"])
    assert all(player["checked_in"] is False for player in waiting["side_b"]["players"])

    kept = session.get(Match, assigned.id)
    assert kept is not None
    assert kept.team_a_id == teams[0].id
    assert kept.team_b_id == teams[3].id
    assert kept.event_id == assigned.event_id
    assert kept.match_code == "MIX_WF_R1_M01"
    assert kept.source_match_a_id == other.id
    assert kept.runtime_status == "SCHEDULED"
    assert kept.score_json is None
    assignment_after = session.get(MatchAssignment, assignment_id)
    assert assignment_after is not None
    assert assignment_after.slot_id == slot_id
    assert assignment_after.match_id == assigned.id

    other_after = session.get(Match, other.id)
    assert other_after.runtime_status == "SCHEDULED"
    assert other_after.team_a_id == teams[1].id
    other_assignment_after = session.exec(
        select(MatchAssignment).where(MatchAssignment.match_id == other.id)
    ).one()
    assert other_assignment_after.slot_id == other_slot_id
    other_checkin = _checkin_row(after, other.id)
    assert other_checkin["side_a"]["team_checked_in"] is True
    assert other_checkin["side_b"]["team_checked_in"] is False


def test_in_progress_match_without_score_returns_to_waiting_and_frees_court(client, session: Session):
    tournament, version, _event, teams, matches, _slots = _setup_draft_for_move(session)
    playing = matches[0]
    alpha = _add_two_players_for_team(session, tournament.id, teams[0].id, "Alpha")
    delta = _add_two_players_for_team(session, tournament.id, teams[3].id, "Delta")
    photo = TeamOfficialPhoto(
        team_id=teams[0].id,
        tournament_id=tournament.id,
        storage_key=f"team-photos/{tournament.id}/{teams[0].id}/keep.jpg",
        byte_size=128,
    )
    session.add(photo)
    session.commit()
    photo_id = photo.id
    _enable_checkin(client, tournament.id, version.id)
    _check_in_side(client, tournament.id, version.id, playing.id, "A", alpha)
    ready = _check_in_side_ready(client, tournament.id, version.id, playing.id, "B", delta)
    slot_id = ready["available_slots"][0]["slot_id"]
    assign = client.post(
        f"/api/desk/tournaments/{tournament.id}/checkin/assign",
        json={"version_id": version.id, "match_id": playing.id, "slot_id": slot_id},
    )
    assert assign.status_code == 200
    assigned_body = assign.json()
    moved = _match_row(assigned_body, playing.id)
    assert moved["status"] == "IN_PROGRESS"
    court_name = moved["court_name"]
    assert court_name
    assert all(slot["court_name"] != court_name for slot in assigned_body["available_slots"])
    assert playing.id not in {row["match_id"] for row in assigned_body["checkin_matches"]}

    reset = _return_to_waiting(client, tournament.id, version.id, playing.id)
    assert reset.status_code == 200
    assert reset.json()["previous_status"] == "IN_PROGRESS"
    assert reset.json()["status"] == "SCHEDULED"

    session.expire_all()
    after = _snapshot(client, tournament.id, version.id)
    assert _match_row(after, playing.id)["status"] == "SCHEDULED"
    assert playing.id not in {row["match_id"] for row in after["ready_queue"]}
    assert playing.id not in {row["match_id"] for row in after["ready_assigned_queue"]}
    now_playing_ids = {row["match_id"] for row in after["now_playing_by_court"].values() if row}
    assert playing.id not in now_playing_ids
    waiting = _checkin_row(after, playing.id)
    assert waiting["match_ready"] is False
    assert waiting["side_a"]["team_checked_in"] is False
    assert waiting["side_b"]["team_checked_in"] is False
    assert court_name in {slot["court_name"] for slot in after["available_slots"]}

    kept = session.get(Match, playing.id)
    assert kept.started_at is None
    assert kept.score_json is None
    assert kept.winner_team_id is None
    kept_photo = session.get(TeamOfficialPhoto, photo_id)
    assert kept_photo is not None
    assert kept_photo.team_id == teams[0].id
    assert kept_photo.storage_key == f"team-photos/{tournament.id}/{teams[0].id}/keep.jpg"

    _check_in_side(client, tournament.id, version.id, playing.id, "A", alpha)
    _check_in_side(client, tournament.id, version.id, playing.id, "B", delta)
    checked_again = _snapshot(client, tournament.id, version.id)
    assert playing.id in {row["match_id"] for row in checked_again["ready_queue"]}
    assert _checkin_row(checked_again, playing.id)["match_ready"] is True


def _check_in_side_ready(client, tournament_id: int, version_id: int, match_id: int, side: str, players) -> dict:
    assert players
    last = None
    team = client.patch(
        f"/api/desk/tournaments/{tournament_id}/matches/{match_id}/checkin/team",
        json={"version_id": version_id, "side": side, "checked_in": True},
    )
    assert team.status_code == 200
    for player in players:
        last = client.patch(
            f"/api/desk/tournaments/{tournament_id}/matches/{match_id}/checkin/player",
            json={
                "version_id": version_id,
                "side": side,
                "player_id": player.id,
                "checked_in": True,
            },
        )
        assert last.status_code == 200
    return last.json()


def test_paused_match_without_score_can_return_to_waiting(client, session: Session):
    tournament, version, _event, teams, matches, _slots = _setup_draft_for_move(session)
    paused = matches[0]
    alpha = _add_two_players_for_team(session, tournament.id, teams[0].id, "Alpha")
    delta = _add_two_players_for_team(session, tournament.id, teams[3].id, "Delta")
    _enable_checkin(client, tournament.id, version.id)
    _check_in_side(client, tournament.id, version.id, paused.id, "A", alpha)
    _check_in_side(client, tournament.id, version.id, paused.id, "B", delta)
    paused.runtime_status = "PAUSED"
    session.add(paused)
    session.commit()

    reset = _return_to_waiting(client, tournament.id, version.id, paused.id)
    assert reset.status_code == 200
    session.expire_all()
    assert session.get(Match, paused.id).runtime_status == "SCHEDULED"
    body = _snapshot(client, tournament.id, version.id)
    assert _checkin_row(body, paused.id)["match_ready"] is False


def test_finalized_or_scored_matches_cannot_be_reset(client, session: Session):
    tournament, version, _event, teams, matches, _slots = _setup_draft_for_move(session)
    scored, finalized = matches
    alpha = _add_two_players_for_team(session, tournament.id, teams[0].id, "Alpha")
    delta = _add_two_players_for_team(session, tournament.id, teams[3].id, "Delta")
    _enable_checkin(client, tournament.id, version.id)
    _check_in_side(client, tournament.id, version.id, scored.id, "A", alpha)
    _check_in_side(client, tournament.id, version.id, scored.id, "B", delta)
    scored.runtime_status = "IN_PROGRESS"
    scored.score_json = {"display": "6-4"}
    session.add(scored)
    finalized.runtime_status = "FINAL"
    finalized.winner_team_id = teams[1].id
    finalized.score_json = {"display": "8-3"}
    session.add(finalized)
    session.commit()

    scored_resp = _return_to_waiting(client, tournament.id, version.id, scored.id)
    assert scored_resp.status_code == 409
    assert "recorded score" in scored_resp.json()["detail"]

    final_resp = _return_to_waiting(client, tournament.id, version.id, finalized.id)
    assert final_resp.status_code == 409
    assert "finalized result" in final_resp.json()["detail"]

    session.expire_all()
    scored_after = session.get(Match, scored.id)
    assert scored_after.runtime_status == "IN_PROGRESS"
    assert scored_after.score_json == {"display": "6-4"}
    assert session.exec(
        select(MatchCheckIn).where(MatchCheckIn.match_id == scored.id, MatchCheckIn.team_checked_in == True)  # noqa: E712
    ).all()
    final_after = session.get(Match, finalized.id)
    assert final_after.runtime_status == "FINAL"
    assert final_after.winner_team_id == teams[1].id
    assert final_after.score_json == {"display": "8-3"}
    assert session.exec(select(Match).where(Match.schedule_version_id == version.id)).all()


def test_reset_does_not_redispatch_and_keeps_waiting_off_assigned_court(client, session: Session):
    ctx = _setup_automation(session)
    tournament, version, match = ctx["tournament"], ctx["version"], ctx["m1"]
    slot_key = slot_key_for_slot(ctx["slot_a"])
    _check_in(session, tournament.id, version.id, match)
    session.commit()

    released = client.post(
        f"/api/desk/tournaments/{tournament.id}/opening-release",
        json={"version_id": version.id, "day_date": ctx["day"].isoformat(), "slot_key": slot_key},
    )
    assert released.status_code == 200
    assert match.id in released.json()["started_match_ids"]

    reset = _return_to_waiting(client, tournament.id, version.id, match.id)
    assert reset.status_code == 200
    assert reset.json()["status"] == "SCHEDULED"
    assert "started_match_ids" not in reset.json()

    tournament_id = tournament.id
    version_id = version.id
    match_id = match.id
    day = ctx["day"]
    court_number = ctx["slot_a"].court_number
    session.expire_all()
    court = dispatch_court(
        session,
        session.get(Tournament, tournament_id),
        version_id=version_id,
        day_date=day,
        court_number=court_number,
    )
    assert match_id not in court.started_match_ids
    session.expire_all()
    assert session.get(Match, match_id).runtime_status == "SCHEDULED"

    body = _snapshot(client, tournament_id, version_id)
    assert match_id not in {row["match_id"] for row in body["ready_assigned_queue"]}
    assert match_id not in {row["match_id"] for row in body["ready_queue"]}
    waiting = _checkin_row(body, match_id)
    assert waiting["match_ready"] is False
    desk_match = _match_row(body, match_id)
    assert desk_match["court_name"]
    assert desk_match["checkin_reset_pending"] is True
    assert desk_match["scheduled_time"]
    now_playing_ids = {row["match_id"] for row in body["now_playing_by_court"].values() if row}
    assert match_id not in now_playing_ids


def test_back_to_ready_keeps_checkin_while_waiting_reset_clears_it(client, session: Session):
    tournament, version, _event, teams, matches, _slots = _setup_draft_for_move(session)
    ready_match = matches[0]
    alpha = _add_two_players_for_team(session, tournament.id, teams[0].id, "Alpha")
    delta = _add_two_players_for_team(session, tournament.id, teams[3].id, "Delta")
    _enable_checkin(client, tournament.id, version.id)
    _check_in_side(client, tournament.id, version.id, ready_match.id, "A", alpha)
    _check_in_side(client, tournament.id, version.id, ready_match.id, "B", delta)
    started = client.patch(
        f"/api/desk/tournaments/{tournament.id}/matches/{ready_match.id}/status",
        json={"version_id": version.id, "status": "IN_PROGRESS"},
    )
    assert started.status_code == 200
    back = client.patch(
        f"/api/desk/tournaments/{tournament.id}/matches/{ready_match.id}/status",
        json={"version_id": version.id, "status": "SCHEDULED", "reset_started_at": True},
    )
    assert back.status_code == 200
    kept = _snapshot(client, tournament.id, version.id)
    assert ready_match.id in {row["match_id"] for row in kept["ready_queue"]}
    assert _checkin_row(kept, ready_match.id)["match_ready"] is True
    assert session.exec(
        select(MatchPlayerCheckIn).where(
            MatchPlayerCheckIn.match_id == ready_match.id,
            MatchPlayerCheckIn.checked_in == True,  # noqa: E712
        )
    ).all()


def _prepare_later_round(session: Session):
    ctx = _setup_automation(session)
    opening_a, opening_b, later = ctx["m1"], ctx["m2"], ctx["m_r2"]
    opening_a.runtime_status = "FINAL"
    opening_a.winner_team_id = opening_a.team_a_id
    opening_b.runtime_status = "FINAL"
    opening_b.winner_team_id = opening_b.team_a_id
    later.team_a_id = opening_a.team_a_id
    later.team_b_id = opening_b.team_a_id
    later.runtime_status = "IN_PROGRESS"
    session.add_all([opening_a, opening_b, later])
    session.commit()
    return ctx


def test_later_round_waterfall_reset_holds_until_both_teams_check_in(client, session: Session):
    ctx = _prepare_later_round(session)
    tournament, version, later = ctx["tournament"], ctx["version"], ctx["m_r2"]
    photo = TeamOfficialPhoto(
        team_id=later.team_a_id,
        tournament_id=tournament.id,
        storage_key=f"team-photos/{tournament.id}/{later.team_a_id}/keep.jpg",
        byte_size=64,
    )
    session.add(photo)
    session.commit()
    assignment = session.exec(select(MatchAssignment).where(MatchAssignment.match_id == later.id)).one()
    slot_id = assignment.slot_id
    source_a = later.source_match_a_id
    source_b = later.source_match_b_id
    team_a = later.team_a_id
    team_b = later.team_b_id

    reset = _return_to_waiting(client, tournament.id, version.id, later.id)
    assert reset.status_code == 200
    session.expire_all()
    held = session.get(Match, later.id)
    assert held.runtime_status == "SCHEDULED"
    assert held.started_at is None
    assert held.checkin_reset_pending is True
    assert held.team_a_id == team_a
    assert held.team_b_id == team_b
    assert held.source_match_a_id == source_a
    assert held.source_match_b_id == source_b
    assert session.get(MatchAssignment, assignment.id).slot_id == slot_id
    assert session.get(TeamOfficialPhoto, photo.id).storage_key.endswith("/keep.jpg")

    blocked = dispatch_court(
        session,
        session.get(Tournament, tournament.id),
        version_id=version.id,
        day_date=ctx["day"],
        court_number=ctx["slot_c"].court_number,
    )
    assert later.id not in blocked.started_match_ids
    session.expire_all()
    assert session.get(Match, later.id).runtime_status == "SCHEDULED"
    assert evaluate_eligibility(session, session.get(Tournament, tournament.id), session.get(Match, later.id)).outcome == (
        OUTCOME_WAITING_CHECKIN
    )

    manual = client.patch(
        f"/api/desk/tournaments/{tournament.id}/matches/{later.id}/status",
        json={"version_id": version.id, "status": "IN_PROGRESS"},
    )
    assert manual.status_code == 409

    one_side = client.patch(
        f"/api/desk/tournaments/{tournament.id}/matches/{later.id}/checkin/team",
        json={"version_id": version.id, "side": "A", "checked_in": True},
    )
    assert one_side.status_code == 200
    session.expire_all()
    assert session.get(Match, later.id).runtime_status == "SCHEDULED"
    assert session.get(Match, later.id).checkin_reset_pending is True
    partial = _snapshot(client, tournament.id, version.id)
    assert later.id not in {row["match_id"] for row in partial["ready_assigned_queue"]}
    assert later.id not in {row["match_id"] for row in partial["ready_queue"]}
    assert later.id not in {row["match_id"] for row in partial["now_playing_by_court"].values() if row}
    waiting = _checkin_row(partial, later.id)
    assert waiting["match_ready"] is False
    assert _match_row(partial, later.id)["checkin_reset_pending"] is True

    other_side = client.patch(
        f"/api/desk/tournaments/{tournament.id}/matches/{later.id}/checkin/team",
        json={"version_id": version.id, "side": "B", "checked_in": True},
    )
    assert other_side.status_code == 200
    session.expire_all()
    started = session.get(Match, later.id)
    assert started.checkin_reset_pending is False
    assert started.runtime_status == "IN_PROGRESS"
    available = _snapshot(client, tournament.id, version.id)
    assert later.id not in {row["match_id"] for row in available["checkin_matches"]}
    assert later.id not in {row["match_id"] for row in available["ready_assigned_queue"]}
    assert later.id not in {row["match_id"] for row in available["ready_queue"]}
    assert later.id in {row["match_id"] for row in available["now_playing_by_court"].values() if row}


def test_later_round_reset_waits_when_court_is_occupied(client, session: Session):
    ctx = _prepare_later_round(session)
    tournament, version, later = ctx["tournament"], ctx["version"], ctx["m_r2"]
    reset = _return_to_waiting(client, tournament.id, version.id, later.id)
    assert reset.status_code == 200
    session.expire_all()
    later = session.get(Match, later.id)
    early = ScheduleSlot(
        tournament_id=tournament.id,
        schedule_version_id=version.id,
        day_date=ctx["day"],
        start_time=time(8, 0),
        end_time=time(9, 0),
        court_number=ctx["slot_c"].court_number,
        court_label=str(ctx["slot_c"].court_number),
        block_minutes=60,
    )
    session.add(early)
    session.flush()
    live = Match(
        tournament_id=tournament.id,
        event_id=later.event_id,
        schedule_version_id=version.id,
        match_code="COURT_OCCUPANT",
        match_type="WF",
        round_number=1,
        round_index=1,
        sequence_in_round=2,
        duration_minutes=60,
        team_a_id=later.team_a_id,
        team_b_id=later.team_b_id,
        placeholder_side_a="A",
        placeholder_side_b="B",
        runtime_status="IN_PROGRESS",
    )
    session.add(live)
    session.flush()
    session.add(
        MatchAssignment(
            schedule_version_id=version.id,
            match_id=live.id,
            slot_id=early.id,
            assigned_by="MANUAL",
        )
    )
    session.commit()

    client.patch(
        f"/api/desk/tournaments/{tournament.id}/matches/{later.id}/checkin/team",
        json={"version_id": version.id, "side": "A", "checked_in": True},
    )
    both = client.patch(
        f"/api/desk/tournaments/{tournament.id}/matches/{later.id}/checkin/team",
        json={"version_id": version.id, "side": "B", "checked_in": True},
    )
    assert both.status_code == 200
    session.expire_all()
    held = session.get(Match, later.id)
    assert held.runtime_status == "SCHEDULED"
    assert held.checkin_reset_pending is False
    body = _snapshot(client, tournament.id, version.id)
    assert later.id in {row["match_id"] for row in body["ready_assigned_queue"]}
    assert later.id not in {row["match_id"] for row in body["now_playing_by_court"].values() if row}
    assert _match_row(body, later.id)["status"] == "SCHEDULED"


def test_unchecking_one_ready_side_returns_later_round_to_waiting(client, session: Session):
    ctx = _prepare_later_round(session)
    tournament, version, later = ctx["tournament"], ctx["version"], ctx["m_r2"]
    _enable_checkin(client, tournament.id, version.id)
    assignment = session.exec(select(MatchAssignment).where(MatchAssignment.match_id == later.id)).one()
    slot_id = assignment.slot_id
    team_a = later.team_a_id
    team_b = later.team_b_id
    early = ScheduleSlot(
        tournament_id=tournament.id,
        schedule_version_id=version.id,
        day_date=ctx["day"],
        start_time=time(8, 0),
        end_time=time(9, 0),
        court_number=ctx["slot_c"].court_number,
        court_label=str(ctx["slot_c"].court_number),
        block_minutes=60,
    )
    session.add(early)
    session.flush()
    live = Match(
        tournament_id=tournament.id,
        event_id=later.event_id,
        schedule_version_id=version.id,
        match_code="COURT_OCCUPANT_UNCHECK",
        match_type="WF",
        round_number=1,
        round_index=1,
        sequence_in_round=3,
        duration_minutes=60,
        team_a_id=later.team_a_id,
        team_b_id=later.team_b_id,
        placeholder_side_a="A",
        placeholder_side_b="B",
        runtime_status="IN_PROGRESS",
    )
    session.add(live)
    session.flush()
    session.add(
        MatchAssignment(
            schedule_version_id=version.id,
            match_id=live.id,
            slot_id=early.id,
            assigned_by="MANUAL",
        )
    )
    later.runtime_status = "SCHEDULED"
    later.started_at = None
    later.checkin_reset_pending = False
    session.add(later)
    session.commit()

    for side in ("A", "B"):
        checked = client.patch(
            f"/api/desk/tournaments/{tournament.id}/matches/{later.id}/checkin/team",
            json={"version_id": version.id, "side": side, "checked_in": True},
        )
        assert checked.status_code == 200
    session.expire_all()
    ready = session.get(Match, later.id)
    assert ready.runtime_status == "SCHEDULED"
    assert ready.checkin_reset_pending is False
    before = _snapshot(client, tournament.id, version.id)
    assert later.id in {row["match_id"] for row in before["ready_assigned_queue"]}

    unchecked = client.patch(
        f"/api/desk/tournaments/{tournament.id}/matches/{later.id}/checkin/team",
        json={"version_id": version.id, "side": "B", "checked_in": False},
    )
    assert unchecked.status_code == 200
    session.expire_all()
    held = session.get(Match, later.id)
    assert held.runtime_status == "SCHEDULED"
    assert held.checkin_reset_pending is True
    assert held.team_a_id == team_a
    assert held.team_b_id == team_b
    assert session.get(MatchAssignment, assignment.id).slot_id == slot_id
    body = _snapshot(client, tournament.id, version.id)
    assert later.id not in {row["match_id"] for row in body["ready_assigned_queue"]}
    assert later.id not in {row["match_id"] for row in body["ready_queue"]}
    assert later.id not in {row["match_id"] for row in body["now_playing_by_court"].values() if row}
    waiting = _checkin_row(body, later.id)
    assert waiting["match_ready"] is False
    assert waiting["checkin_reset_pending"] is True
    assert waiting["side_a"]["team_checked_in"] is True
    assert waiting["side_b"]["team_checked_in"] is False
    assert _match_row(body, later.id)["checkin_reset_pending"] is True
    assert evaluate_eligibility(session, session.get(Tournament, tournament.id), held).outcome == OUTCOME_WAITING_CHECKIN
    occupant = session.get(Match, live.id)
    occupant.runtime_status = "FINAL"
    occupant.winner_team_id = occupant.team_a_id
    session.add(occupant)
    session.commit()
    blocked = dispatch_court(
        session,
        session.get(Tournament, tournament.id),
        version_id=version.id,
        day_date=ctx["day"],
        court_number=ctx["slot_c"].court_number,
    )
    assert later.id not in blocked.started_match_ids
    session.expire_all()
    assert session.get(Match, later.id).runtime_status == "SCHEDULED"

    restored = client.patch(
        f"/api/desk/tournaments/{tournament.id}/matches/{later.id}/checkin/team",
        json={"version_id": version.id, "side": "B", "checked_in": True},
    )
    assert restored.status_code == 200
    session.expire_all()
    again = session.get(Match, later.id)
    assert again.checkin_reset_pending is False
    assert again.runtime_status == "IN_PROGRESS"
    assert again.team_a_id == team_a
    assert again.team_b_id == team_b
    assert session.get(MatchAssignment, assignment.id).slot_id == slot_id


def test_unreset_later_round_still_starts_without_checkin(session: Session):
    ctx = _prepare_later_round(session)
    tournament, later = ctx["tournament"], ctx["m_r2"]
    later = session.get(Match, later.id)
    later.runtime_status = "SCHEDULED"
    later.started_at = None
    later.checkin_reset_pending = False
    session.add(later)
    session.commit()

    eligibility = evaluate_eligibility(session, tournament, session.get(Match, later.id))
    assert eligibility.outcome == OUTCOME_READY_TO_START
    started, _detail = start_match_canonical(session, tournament, session.get(Match, later.id))
    assert started is True
    assert session.get(Match, later.id).runtime_status == "IN_PROGRESS"


def test_manual_assign_cannot_bypass_checkin_reset(client, session: Session):
    tournament, version, _event, teams, matches, _slots = _setup_draft_for_move(session)
    match = matches[0]
    match.runtime_status = "SCHEDULED"
    match.checkin_reset_pending = True
    session.add(match)
    session.commit()
    _enable_checkin(client, tournament.id, version.id)
    body = _snapshot(client, tournament.id, version.id)
    slot_id = body["available_slots"][0]["slot_id"]
    assign = client.post(
        f"/api/desk/tournaments/{tournament.id}/checkin/assign",
        json={"version_id": version.id, "match_id": match.id, "slot_id": slot_id},
    )
    assert assign.status_code == 409
    assert "check in again" in assign.json()["detail"]
    session.expire_all()
    assert session.get(Match, match.id).runtime_status == "SCHEDULED"
    assert teams[0].id == match.team_a_id
