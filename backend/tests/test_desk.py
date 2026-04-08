"""
Phase C — Desk Runtime Console tests.

Validates:
- Working draft clones from published version
- Working draft is idempotent
- Finalize rejects FINAL version
- Finalize sets match FINAL and advances downstream
- Finalize idempotent with same payload
- Finalize warns on downstream conflict
- Snapshot returns court grouping
"""

from datetime import date, time

import pytest
from sqlmodel import Session, select
from typing import List

from app.models.event import Event
from app.models.match import Match
from app.models.match_assignment import MatchAssignment
from app.models.match_lock import MatchLock
from app.models.schedule_slot import ScheduleSlot
from app.models.schedule_version import ScheduleVersion
from app.models.sms_log import SmsLog
from app.models.player import Player
from app.models.team import Team
from app.models.team_player import TeamPlayer
from app.models.tournament import Tournament
from app.models.tournament_sms_settings import TournamentSmsSettings


def _setup_tournament_with_matches(session: Session):
    """Create a published tournament with WF R1 matches wired to R2."""
    t = Tournament(
        name="Desk Test",
        location="Test Beach",
        timezone="America/New_York",
        start_date=date(2026, 6, 5),
        end_date=date(2026, 6, 7),
    )
    session.add(t)
    session.flush()

    v = ScheduleVersion(
        tournament_id=t.id,
        version_number=1,
        status="final",
    )
    session.add(v)
    session.flush()

    ev = Event(
        tournament_id=t.id,
        category="womens",
        name="Women's A",
        team_count=4,
    )
    session.add(ev)
    session.flush()

    team1 = Team(event_id=ev.id, name="Alpha - VA", seed=1, display_name="Alpha")
    team2 = Team(event_id=ev.id, name="Bravo - NC", seed=2, display_name="Bravo")
    team3 = Team(event_id=ev.id, name="Charlie - FL", seed=3, display_name="Charlie")
    team4 = Team(event_id=ev.id, name="Delta - TX", seed=4, display_name="Delta")
    session.add_all([team1, team2, team3, team4])
    session.flush()

    # R1 Match 1: Alpha vs Delta
    m1 = Match(
        tournament_id=t.id,
        event_id=ev.id,
        schedule_version_id=v.id,
        match_code="WOM_E1_WF_R1_M01",
        match_type="WF",
        round_number=1,
        round_index=1,
        sequence_in_round=1,
        duration_minutes=60,
        team_a_id=team1.id,
        team_b_id=team4.id,
        placeholder_side_a="Seed 1",
        placeholder_side_b="Seed 4",
    )
    # R1 Match 2: Bravo vs Charlie
    m2 = Match(
        tournament_id=t.id,
        event_id=ev.id,
        schedule_version_id=v.id,
        match_code="WOM_E1_WF_R1_M02",
        match_type="WF",
        round_number=1,
        round_index=1,
        sequence_in_round=2,
        duration_minutes=60,
        team_a_id=team2.id,
        team_b_id=team3.id,
        placeholder_side_a="Seed 2",
        placeholder_side_b="Seed 3",
    )
    session.add_all([m1, m2])
    session.flush()

    # R2 Match: Winner of M1 vs Winner of M2
    m3 = Match(
        tournament_id=t.id,
        event_id=ev.id,
        schedule_version_id=v.id,
        match_code="WOM_E1_WF_R2_M01",
        match_type="WF",
        round_number=2,
        round_index=1,
        sequence_in_round=1,
        duration_minutes=60,
        placeholder_side_a="Winner M1",
        placeholder_side_b="Winner M2",
        source_match_a_id=m1.id,
        source_match_b_id=m2.id,
        source_a_role="WINNER",
        source_b_role="WINNER",
    )
    session.add(m3)
    session.flush()

    # Create slots and assignments
    slot1 = ScheduleSlot(
        tournament_id=t.id,
        schedule_version_id=v.id,
        day_date=date(2026, 6, 5),
        start_time=time(9, 0),
        end_time=time(10, 0),
        court_number=1,
        court_label="1",
        block_minutes=60,
    )
    slot2 = ScheduleSlot(
        tournament_id=t.id,
        schedule_version_id=v.id,
        day_date=date(2026, 6, 5),
        start_time=time(9, 0),
        end_time=time(10, 0),
        court_number=2,
        court_label="2",
        block_minutes=60,
    )
    slot3 = ScheduleSlot(
        tournament_id=t.id,
        schedule_version_id=v.id,
        day_date=date(2026, 6, 5),
        start_time=time(11, 0),
        end_time=time(12, 0),
        court_number=1,
        court_label="1",
        block_minutes=60,
    )
    session.add_all([slot1, slot2, slot3])
    session.flush()

    a1 = MatchAssignment(schedule_version_id=v.id, match_id=m1.id, slot_id=slot1.id)
    a2 = MatchAssignment(schedule_version_id=v.id, match_id=m2.id, slot_id=slot2.id)
    a3 = MatchAssignment(schedule_version_id=v.id, match_id=m3.id, slot_id=slot3.id)
    session.add_all([a1, a2, a3])
    session.flush()

    # Publish
    t.public_schedule_version_id = v.id
    session.add(t)
    session.commit()

    return t, v, ev, [team1, team2, team3, team4], [m1, m2, m3]


def _set_team_test_phones(session: Session, teams: List[Team]) -> None:
    """Attach a single valid phone to each team for SMS-trigger tests."""
    for idx, team in enumerate(teams, start=1):
        team.player1_cellphone = f"9015550{idx:03d}"
        team.player2_cellphone = None
        team.p1_cell = None
        team.p2_cell = None
        session.add(team)
    session.commit()


def test_working_draft_clones_from_published(client, session):
    """Working draft clones from published version and has same match count."""
    t, v, ev, teams, matches = _setup_tournament_with_matches(session)

    resp = client.post(f"/api/desk/tournaments/{t.id}/working-draft")
    assert resp.status_code == 200
    body = resp.json()
    assert body["created"] is True
    assert body["status"] == "draft"
    assert body["notes"] == "Desk Draft"

    draft_id = body["version_id"]
    assert draft_id != v.id

    # Verify match count matches source
    snap_resp = client.get(f"/api/desk/tournaments/{t.id}/snapshot?version_id={draft_id}")
    assert snap_resp.status_code == 200
    snap = snap_resp.json()
    assert len(snap["matches"]) == len(matches)


def test_working_draft_idempotent(client, session):
    """Calling working-draft twice returns the same version."""
    t, v, ev, teams, matches = _setup_tournament_with_matches(session)

    resp1 = client.post(f"/api/desk/tournaments/{t.id}/working-draft")
    assert resp1.status_code == 200
    vid1 = resp1.json()["version_id"]
    assert resp1.json()["created"] is True

    resp2 = client.post(f"/api/desk/tournaments/{t.id}/working-draft")
    assert resp2.status_code == 200
    vid2 = resp2.json()["version_id"]
    assert resp2.json()["created"] is False

    assert vid1 == vid2


def test_finalize_rejects_final_version(client, session):
    """Cannot finalize a match in a FINAL version."""
    t, v, ev, teams, matches = _setup_tournament_with_matches(session)

    resp = client.patch(
        f"/api/desk/tournaments/{t.id}/matches/{matches[0].id}/finalize",
        json={
            "version_id": v.id,
            "score": "8-4",
            "winner_team_id": teams[0].id,
        },
    )
    assert resp.status_code == 400
    assert "FINAL" in resp.json()["detail"]


def test_finalize_sets_match_final_and_advances(client, session):
    """Finalizing an R1 match populates team in downstream R2."""
    t, v, ev, teams, matches = _setup_tournament_with_matches(session)

    # Create desk draft
    draft_resp = client.post(f"/api/desk/tournaments/{t.id}/working-draft")
    draft_id = draft_resp.json()["version_id"]

    # Find draft's M1 match (cloned)
    snap = client.get(f"/api/desk/tournaments/{t.id}/snapshot?version_id={draft_id}").json()
    draft_m1 = [m for m in snap["matches"] if m["match_code"] == "WOM_E1_WF_R1_M01"][0]
    draft_m3 = [m for m in snap["matches"] if m["match_code"] == "WOM_E1_WF_R2_M01"][0]

    # M3 should have no teams initially
    assert draft_m3["team1_id"] is None
    assert draft_m3["team2_id"] is None

    # Finalize M1 with team1 (Alpha) as winner
    fin_resp = client.patch(
        f"/api/desk/tournaments/{t.id}/matches/{draft_m1['match_id']}/finalize",
        json={
            "version_id": draft_id,
            "score": "8-4",
            "winner_team_id": draft_m1["team1_id"],
        },
    )
    assert fin_resp.status_code == 200
    fin_body = fin_resp.json()
    assert fin_body["match"]["status"] == "FINAL"
    assert fin_body["match"]["score_display"] == "8-4"

    # Downstream should be populated
    assert len(fin_body["downstream_updates"]) >= 1
    updated_match_ids = [u["match_id"] for u in fin_body["downstream_updates"]]
    assert draft_m3["match_id"] in updated_match_ids

    # Verify via snapshot
    snap2 = client.get(f"/api/desk/tournaments/{t.id}/snapshot?version_id={draft_id}").json()
    m3_after = [m for m in snap2["matches"] if m["match_code"] == "WOM_E1_WF_R2_M01"][0]
    assert m3_after["team1_id"] == draft_m1["team1_id"]


def test_finalize_idempotent_same_payload(client, session):
    """Finalizing the same match twice with same payload is a no-op."""
    t, v, ev, teams, matches = _setup_tournament_with_matches(session)

    draft_resp = client.post(f"/api/desk/tournaments/{t.id}/working-draft")
    draft_id = draft_resp.json()["version_id"]

    snap = client.get(f"/api/desk/tournaments/{t.id}/snapshot?version_id={draft_id}").json()
    draft_m1 = [m for m in snap["matches"] if m["match_code"] == "WOM_E1_WF_R1_M01"][0]

    payload = {
        "version_id": draft_id,
        "score": "8-4",
        "winner_team_id": draft_m1["team1_id"],
    }

    resp1 = client.patch(
        f"/api/desk/tournaments/{t.id}/matches/{draft_m1['match_id']}/finalize",
        json=payload,
    )
    assert resp1.status_code == 200

    resp2 = client.patch(
        f"/api/desk/tournaments/{t.id}/matches/{draft_m1['match_id']}/finalize",
        json=payload,
    )
    assert resp2.status_code == 200
    assert resp2.json()["match"]["status"] == "FINAL"


def test_finalize_warns_on_downstream_conflict(client, session):
    """Returns warning if downstream slot already has a different team."""
    t, v, ev, teams, matches = _setup_tournament_with_matches(session)

    draft_resp = client.post(f"/api/desk/tournaments/{t.id}/working-draft")
    draft_id = draft_resp.json()["version_id"]

    snap = client.get(f"/api/desk/tournaments/{t.id}/snapshot?version_id={draft_id}").json()
    draft_m1 = [m for m in snap["matches"] if m["match_code"] == "WOM_E1_WF_R1_M01"][0]
    draft_m3 = [m for m in snap["matches"] if m["match_code"] == "WOM_E1_WF_R2_M01"][0]

    # Manually set M3.team_a to a different team to create conflict
    m3_obj = session.get(Match, draft_m3["match_id"])
    m3_obj.team_a_id = draft_m1["team2_id"]  # Set to losing team
    session.add(m3_obj)
    session.commit()

    # Finalize M1 - winner should conflict with already-set team_a
    fin_resp = client.patch(
        f"/api/desk/tournaments/{t.id}/matches/{draft_m1['match_id']}/finalize",
        json={
            "version_id": draft_id,
            "score": "8-4",
            "winner_team_id": draft_m1["team1_id"],
        },
    )
    assert fin_resp.status_code == 200
    body = fin_resp.json()
    assert len(body["warnings"]) >= 1
    assert body["warnings"][0]["reason"] == "CONFLICT_EXISTING_TEAM"


def test_finalize_rejects_invalid_score_for_match_format(client, session):
    """Desk finalize rejects scores that don't match the match duration format."""
    t, v, ev, teams, matches = _setup_tournament_with_matches(session)

    draft_resp = client.post(f"/api/desk/tournaments/{t.id}/working-draft")
    draft_id = draft_resp.json()["version_id"]
    snap = client.get(f"/api/desk/tournaments/{t.id}/snapshot?version_id={draft_id}").json()
    draft_m1 = [m for m in snap["matches"] if m["match_code"] == "WOM_E1_WF_R1_M01"][0]

    # This match is 60-min duration => 8-game pro set scoring.
    resp = client.patch(
        f"/api/desk/tournaments/{t.id}/matches/{draft_m1['match_id']}/finalize",
        json={"version_id": draft_id, "score": "5-3", "winner_team_id": draft_m1["team1_id"]},
    )
    assert resp.status_code == 400
    assert "8-game pro set" in resp.json()["detail"]


def test_correct_rejects_invalid_score_for_match_format(client, session):
    """Desk correct endpoint enforces the same score validation rules."""
    t, v, ev, teams, matches = _setup_tournament_with_matches(session)

    draft_resp = client.post(f"/api/desk/tournaments/{t.id}/working-draft")
    draft_id = draft_resp.json()["version_id"]
    snap = client.get(f"/api/desk/tournaments/{t.id}/snapshot?version_id={draft_id}").json()
    draft_m1 = [m for m in snap["matches"] if m["match_code"] == "WOM_E1_WF_R1_M01"][0]

    # Valid initial finalize
    ok_resp = client.patch(
        f"/api/desk/tournaments/{t.id}/matches/{draft_m1['match_id']}/finalize",
        json={"version_id": draft_id, "score": "8-4", "winner_team_id": draft_m1["team1_id"]},
    )
    assert ok_resp.status_code == 200

    # Invalid correction for 60-min match
    bad_resp = client.patch(
        f"/api/desk/tournaments/{t.id}/matches/{draft_m1['match_id']}/correct",
        json={"version_id": draft_id, "score": "5-3", "winner_team_id": draft_m1["team1_id"]},
    )
    assert bad_resp.status_code == 400
    assert "8-game pro set" in bad_resp.json()["detail"]


def test_snapshot_returns_court_grouping(client, session):
    """Snapshot includes now_playing and up_next per court."""
    t, v, ev, teams, matches = _setup_tournament_with_matches(session)

    # Create desk draft and set a match IN_PROGRESS
    draft_resp = client.post(f"/api/desk/tournaments/{t.id}/working-draft")
    draft_id = draft_resp.json()["version_id"]

    snap = client.get(f"/api/desk/tournaments/{t.id}/snapshot?version_id={draft_id}").json()
    draft_m1 = [m for m in snap["matches"] if m["match_code"] == "WOM_E1_WF_R1_M01"][0]

    # Set M1 in progress
    status_resp = client.patch(
        f"/api/desk/tournaments/{t.id}/matches/{draft_m1['match_id']}/status",
        json={"version_id": draft_id, "status": "IN_PROGRESS"},
    )
    assert status_resp.status_code == 200

    # Get snapshot again
    snap2 = client.get(f"/api/desk/tournaments/{t.id}/snapshot?version_id={draft_id}").json()

    assert "courts" in snap2
    assert len(snap2["courts"]) >= 1
    assert "now_playing_by_court" in snap2
    assert "up_next_by_court" in snap2

    # Court 1 should have M1 as now_playing
    assert "Court 1" in snap2["now_playing_by_court"]
    assert snap2["now_playing_by_court"]["Court 1"]["match_id"] == draft_m1["match_id"]

    # Court 1 should have M3 (11:00 AM) as up_next
    assert "Court 1" in snap2["up_next_by_court"]


def test_sms_automation_status_triggers_up_next_on_deck_and_first_match(client, session):
    """Starting a match triggers up_next + on_deck + first_match automation sends."""
    t, v, ev, teams, matches = _setup_tournament_with_matches(session)
    _set_team_test_phones(session, teams)

    draft_resp = client.post(f"/api/desk/tournaments/{t.id}/working-draft")
    draft_id = draft_resp.json()["version_id"]

    snap = client.get(f"/api/desk/tournaments/{t.id}/snapshot?version_id={draft_id}").json()
    draft_m1 = [m for m in snap["matches"] if m["match_code"] == "WOM_E1_WF_R1_M01"][0]
    draft_m3 = [m for m in snap["matches"] if m["match_code"] == "WOM_E1_WF_R2_M01"][0]

    # Ensure up-next match has teams, then add a third scheduled match for on-deck.
    m3_obj = session.get(Match, draft_m3["match_id"])
    m3_obj.team_a_id = teams[2].id
    m3_obj.team_b_id = teams[3].id
    session.add(m3_obj)
    session.flush()

    m4 = Match(
        tournament_id=t.id,
        event_id=ev.id,
        schedule_version_id=draft_id,
        match_code="WOM_E1_WF_R3_M01",
        match_type="WF",
        round_number=3,
        round_index=1,
        sequence_in_round=1,
        duration_minutes=60,
        team_a_id=teams[0].id,
        team_b_id=teams[1].id,
        placeholder_side_a="TBD",
        placeholder_side_b="TBD",
    )
    session.add(m4)
    session.flush()
    slot4 = ScheduleSlot(
        tournament_id=t.id,
        schedule_version_id=draft_id,
        day_date=date(2026, 6, 5),
        start_time=time(13, 0),
        end_time=time(14, 0),
        court_number=1,
        court_label="1",
        block_minutes=60,
    )
    session.add(slot4)
    session.flush()
    session.add(
        MatchAssignment(
            schedule_version_id=draft_id,
            match_id=m4.id,
            slot_id=slot4.id,
        )
    )
    session.add(
        TournamentSmsSettings(
            tournament_id=t.id,
            auto_first_match=True,
            auto_post_match_next=False,
            auto_on_deck=True,
            auto_up_next=True,
            auto_court_change=False,
            test_mode=False,
        )
    )
    session.commit()

    status_resp = client.patch(
        f"/api/desk/tournaments/{t.id}/matches/{draft_m1['match_id']}/status",
        json={"version_id": draft_id, "status": "IN_PROGRESS"},
    )
    assert status_resp.status_code == 200

    logs = session.exec(
        select(SmsLog).where(
            SmsLog.tournament_id == t.id,
            SmsLog.trigger == "auto",
        )
    ).all()
    by_type = {}
    for row in logs:
        by_type[row.message_type] = by_type.get(row.message_type, 0) + 1

    assert by_type.get("up_next", 0) == 2
    assert by_type.get("first_match", 0) == 2
    assert by_type.get("on_deck", 0) == 2


def test_sms_automation_finalize_triggers_post_match_next(client, session):
    """Finalizing a match triggers post_match_next for teams with upcoming matches."""
    t, v, ev, teams, matches = _setup_tournament_with_matches(session)
    _set_team_test_phones(session, teams)

    draft_resp = client.post(f"/api/desk/tournaments/{t.id}/working-draft")
    draft_id = draft_resp.json()["version_id"]

    snap = client.get(f"/api/desk/tournaments/{t.id}/snapshot?version_id={draft_id}").json()
    draft_m1 = [m for m in snap["matches"] if m["match_code"] == "WOM_E1_WF_R1_M01"][0]

    session.add(
        TournamentSmsSettings(
            tournament_id=t.id,
            auto_first_match=False,
            auto_post_match_next=True,
            auto_on_deck=False,
            auto_up_next=False,
            auto_court_change=False,
            test_mode=False,
        )
    )
    session.commit()

    fin_resp = client.patch(
        f"/api/desk/tournaments/{t.id}/matches/{draft_m1['match_id']}/finalize",
        json={
            "version_id": draft_id,
            "score": "8-4",
            "winner_team_id": draft_m1["team1_id"],
        },
    )
    assert fin_resp.status_code == 200

    post_logs = session.exec(
        select(SmsLog).where(
            SmsLog.tournament_id == t.id,
            SmsLog.trigger == "auto",
            SmsLog.message_type == "post_match_next",
        )
    ).all()
    assert len(post_logs) >= 1
    assert all(not (row.message_body or "").rstrip().endswith(")") for row in post_logs)


def test_sms_automation_move_triggers_court_change(client, session):
    """Moving a match to a new slot triggers court_change automation sends."""
    t, v, ev, teams, matches = _setup_tournament_with_matches(session)
    _set_team_test_phones(session, teams)

    draft_resp = client.post(f"/api/desk/tournaments/{t.id}/working-draft")
    draft_id = draft_resp.json()["version_id"]
    snap = client.get(f"/api/desk/tournaments/{t.id}/snapshot?version_id={draft_id}").json()
    draft_m1 = [m for m in snap["matches"] if m["match_code"] == "WOM_E1_WF_R1_M01"][0]

    new_slot = ScheduleSlot(
        tournament_id=t.id,
        schedule_version_id=draft_id,
        day_date=date(2026, 6, 5),
        start_time=time(15, 0),
        end_time=time(16, 0),
        court_number=3,
        court_label="3",
        block_minutes=60,
    )
    session.add(new_slot)
    session.add(
        TournamentSmsSettings(
            tournament_id=t.id,
            auto_first_match=False,
            auto_post_match_next=False,
            auto_on_deck=False,
            auto_up_next=False,
            auto_court_change=True,
            test_mode=False,
        )
    )
    session.commit()

    move_resp = client.patch(
        f"/api/desk/tournaments/{t.id}/matches/{draft_m1['match_id']}/move",
        json={"version_id": draft_id, "target_slot_id": new_slot.id},
    )
    assert move_resp.status_code == 200

    court_change_logs = session.exec(
        select(SmsLog).where(
            SmsLog.tournament_id == t.id,
            SmsLog.trigger == "auto",
            SmsLog.message_type == "court_change",
        )
    ).all()
    assert len(court_change_logs) == 2


def test_board_excludes_finals(client, session):
    """Board slots should not include FINAL matches."""
    t, v, ev, teams, matches = _setup_tournament_with_matches(session)

    draft_resp = client.post(f"/api/desk/tournaments/{t.id}/working-draft")
    draft_id = draft_resp.json()["version_id"]

    snap = client.get(f"/api/desk/tournaments/{t.id}/snapshot?version_id={draft_id}").json()
    draft_m1 = [m for m in snap["matches"] if m["match_code"] == "WOM_E1_WF_R1_M01"][0]

    # Finalize M1
    client.patch(
        f"/api/desk/tournaments/{t.id}/matches/{draft_m1['match_id']}/finalize",
        json={"version_id": draft_id, "score": "8-4", "winner_team_id": draft_m1["team1_id"]},
    )

    snap2 = client.get(f"/api/desk/tournaments/{t.id}/snapshot?version_id={draft_id}").json()
    board = snap2["board_by_court"]
    court1 = [c for c in board if c["court_name"] == "Court 1"][0]

    # M1 is now FINAL, so it should NOT appear in any board slot
    if court1["now_playing"]:
        assert court1["now_playing"]["match_id"] != draft_m1["match_id"]
    if court1["up_next"]:
        assert court1["up_next"]["match_id"] != draft_m1["match_id"]
    if court1["on_deck"]:
        assert court1["on_deck"]["match_id"] != draft_m1["match_id"]


def test_board_shows_in_progress_as_now_playing(client, session):
    """Board now_playing should show the IN_PROGRESS match."""
    t, v, ev, teams, matches = _setup_tournament_with_matches(session)

    draft_resp = client.post(f"/api/desk/tournaments/{t.id}/working-draft")
    draft_id = draft_resp.json()["version_id"]

    snap = client.get(f"/api/desk/tournaments/{t.id}/snapshot?version_id={draft_id}").json()
    draft_m1 = [m for m in snap["matches"] if m["match_code"] == "WOM_E1_WF_R1_M01"][0]

    # Set M1 in progress
    client.patch(
        f"/api/desk/tournaments/{t.id}/matches/{draft_m1['match_id']}/status",
        json={"version_id": draft_id, "status": "IN_PROGRESS"},
    )

    snap2 = client.get(f"/api/desk/tournaments/{t.id}/snapshot?version_id={draft_id}").json()
    board = snap2["board_by_court"]
    court1 = [c for c in board if c["court_name"] == "Court 1"][0]

    assert court1["now_playing"] is not None
    assert court1["now_playing"]["match_id"] == draft_m1["match_id"]
    assert court1["now_playing"]["status"] == "IN_PROGRESS"

    # up_next should be M3 (the 11:00 AM match on Court 1)
    assert court1["up_next"] is not None
    assert court1["up_next"]["match_id"] != draft_m1["match_id"]


def test_board_empty_court(client, session):
    """Courts with no non-final matches show all null board slots."""
    t, v, ev, teams, matches = _setup_tournament_with_matches(session)

    draft_resp = client.post(f"/api/desk/tournaments/{t.id}/working-draft")
    draft_id = draft_resp.json()["version_id"]

    snap = client.get(f"/api/desk/tournaments/{t.id}/snapshot?version_id={draft_id}").json()
    board = snap["board_by_court"]

    # All courts should have board entries
    assert len(board) == len(snap["courts"])
    for entry in board:
        assert "court_name" in entry
        assert "now_playing" in entry
        assert "up_next" in entry
        assert "on_deck" in entry


# ── On Deck tests ──────────────────────────────────────────────────────

def test_on_deck_three_scheduled_matches(client, session):
    """Court with 3 scheduled matches: up_next = earliest, on_deck = second earliest."""
    t, v, ev, teams, matches = _setup_tournament_with_matches(session)

    draft_resp = client.post(f"/api/desk/tournaments/{t.id}/working-draft")
    draft_id = draft_resp.json()["version_id"]

    # Add a 4th match on Court 1 at 13:00 so Court 1 now has: M1 (9:00), M3 (11:00), M4 (13:00)
    m4 = Match(
        tournament_id=t.id,
        event_id=ev.id,
        schedule_version_id=draft_id,
        match_code="WOM_E1_WF_R3_M01",
        match_type="WF",
        round_number=3,
        round_index=1,
        sequence_in_round=1,
        duration_minutes=60,
        team_a_id=teams[0].id,
        team_b_id=teams[1].id,
        placeholder_side_a="TBD",
        placeholder_side_b="TBD",
    )
    session.add(m4)
    session.flush()

    slot4 = ScheduleSlot(
        tournament_id=t.id,
        schedule_version_id=draft_id,
        day_date=date(2026, 6, 5),
        start_time=time(13, 0),
        end_time=time(14, 0),
        court_number=1,
        court_label="1",
        block_minutes=60,
    )
    session.add(slot4)
    session.flush()
    session.add(MatchAssignment(schedule_version_id=draft_id, match_id=m4.id, slot_id=slot4.id))
    session.commit()

    snap = client.get(f"/api/desk/tournaments/{t.id}/snapshot?version_id={draft_id}").json()

    # Court 1 on_deck_by_court should be M3 (11:00) — M1 (9:00) is up_next
    assert "on_deck_by_court" in snap
    court1_on_deck = snap["on_deck_by_court"].get("Court 1")
    court1_up_next = snap["up_next_by_court"].get("Court 1")

    assert court1_up_next is not None
    assert court1_on_deck is not None
    # up_next should be earliest (9:00), on_deck should be next (11:00)
    assert court1_up_next["sort_time"] <= court1_on_deck["sort_time"]


def test_on_deck_with_in_progress(client, session):
    """Court with IN_PROGRESS match: now_playing set, up_next and on_deck shift."""
    t, v, ev, teams, matches = _setup_tournament_with_matches(session)

    draft_resp = client.post(f"/api/desk/tournaments/{t.id}/working-draft")
    draft_id = draft_resp.json()["version_id"]

    # Add a 4th match on Court 1 at 13:00
    m4 = Match(
        tournament_id=t.id,
        event_id=ev.id,
        schedule_version_id=draft_id,
        match_code="WOM_E1_WF_R3_M01",
        match_type="WF",
        round_number=3,
        round_index=1,
        sequence_in_round=1,
        duration_minutes=60,
        team_a_id=teams[0].id,
        team_b_id=teams[1].id,
        placeholder_side_a="TBD",
        placeholder_side_b="TBD",
    )
    session.add(m4)
    session.flush()

    slot4 = ScheduleSlot(
        tournament_id=t.id,
        schedule_version_id=draft_id,
        day_date=date(2026, 6, 5),
        start_time=time(13, 0),
        end_time=time(14, 0),
        court_number=1,
        court_label="1",
        block_minutes=60,
    )
    session.add(slot4)
    session.flush()
    session.add(MatchAssignment(schedule_version_id=draft_id, match_id=m4.id, slot_id=slot4.id))
    session.commit()

    # Set M1 (9:00 Court 1) to IN_PROGRESS
    snap = client.get(f"/api/desk/tournaments/{t.id}/snapshot?version_id={draft_id}").json()
    m1 = [m for m in snap["matches"] if m["match_code"] == "WOM_E1_WF_R1_M01"][0]
    client.patch(
        f"/api/desk/tournaments/{t.id}/matches/{m1['match_id']}/status",
        json={"version_id": draft_id, "status": "IN_PROGRESS"},
    )

    snap2 = client.get(f"/api/desk/tournaments/{t.id}/snapshot?version_id={draft_id}").json()

    assert snap2["now_playing_by_court"].get("Court 1") is not None
    assert snap2["now_playing_by_court"]["Court 1"]["match_id"] == m1["match_id"]

    # up_next should be M3 (11:00), on_deck should be M4 (13:00)
    assert snap2["up_next_by_court"].get("Court 1") is not None
    assert snap2["on_deck_by_court"].get("Court 1") is not None
    assert snap2["up_next_by_court"]["Court 1"]["sort_time"] < snap2["on_deck_by_court"]["Court 1"]["sort_time"]


def test_courts_board_hides_next_day_matches_when_today_is_active(client, session):
    """If the next scheduled match is on a different day, don't show it as up-next/on-deck."""
    t, v, ev, teams, matches = _setup_tournament_with_matches(session)

    draft_resp = client.post(f"/api/desk/tournaments/{t.id}/working-draft")
    draft_id = draft_resp.json()["version_id"]

    snap = client.get(f"/api/desk/tournaments/{t.id}/snapshot?version_id={draft_id}").json()
    m1 = [m for m in snap["matches"] if m["match_code"] == "WOM_E1_WF_R1_M01"][0]
    m3 = [m for m in snap["matches"] if m["match_code"] == "WOM_E1_WF_R2_M01"][0]

    a3 = session.exec(
        select(MatchAssignment).where(
            MatchAssignment.schedule_version_id == draft_id,
            MatchAssignment.match_id == m3["match_id"],
        )
    ).first()
    assert a3 is not None
    slot3 = session.get(ScheduleSlot, a3.slot_id)
    assert slot3 is not None
    slot3.day_date = date(2026, 6, 6)
    session.add(slot3)
    session.commit()

    client.patch(
        f"/api/desk/tournaments/{t.id}/matches/{m1['match_id']}/status",
        json={"version_id": draft_id, "status": "IN_PROGRESS"},
    )

    snap2 = client.get(f"/api/desk/tournaments/{t.id}/snapshot?version_id={draft_id}").json()
    assert snap2["now_playing_by_court"].get("Court 1") is not None
    assert snap2["up_next_by_court"].get("Court 1") is None
    assert snap2["on_deck_by_court"].get("Court 1") is None

    court1 = [c for c in snap2["board_by_court"] if c["court_name"] == "Court 1"][0]
    assert court1["up_next"] is None
    assert court1["on_deck"] is None


def test_finalize_does_not_auto_start_next_day_match(client, session):
    """Finalizing today's match must not auto-start tomorrow's first slot."""
    t, v, ev, teams, matches = _setup_tournament_with_matches(session)

    draft_resp = client.post(f"/api/desk/tournaments/{t.id}/working-draft")
    draft_id = draft_resp.json()["version_id"]

    snap = client.get(f"/api/desk/tournaments/{t.id}/snapshot?version_id={draft_id}").json()
    m1 = [m for m in snap["matches"] if m["match_code"] == "WOM_E1_WF_R1_M01"][0]
    m3 = [m for m in snap["matches"] if m["match_code"] == "WOM_E1_WF_R2_M01"][0]

    a3 = session.exec(
        select(MatchAssignment).where(
            MatchAssignment.schedule_version_id == draft_id,
            MatchAssignment.match_id == m3["match_id"],
        )
    ).first()
    assert a3 is not None
    slot3 = session.get(ScheduleSlot, a3.slot_id)
    assert slot3 is not None
    slot3.day_date = date(2026, 6, 6)
    session.add(slot3)
    session.commit()

    fin_resp = client.patch(
        f"/api/desk/tournaments/{t.id}/matches/{m1['match_id']}/finalize",
        json={"version_id": draft_id, "score": "8-4", "winner_team_id": m1["team1_id"]},
    )
    assert fin_resp.status_code == 200
    body = fin_resp.json()
    assert body["auto_started"] is None

    m3_obj = session.get(Match, m3["match_id"])
    assert m3_obj is not None
    assert (m3_obj.runtime_status or "SCHEDULED") == "SCHEDULED"


def test_finalize_does_not_auto_start_future_same_day_match(client, session):
    """Finalizing a match should not auto-start a same-day match whose slot is in the future."""
    t, v, ev, teams, matches = _setup_tournament_with_matches(session)

    draft_resp = client.post(f"/api/desk/tournaments/{t.id}/working-draft")
    draft_id = draft_resp.json()["version_id"]

    snap = client.get(f"/api/desk/tournaments/{t.id}/snapshot?version_id={draft_id}").json()
    m1 = [m for m in snap["matches"] if m["match_code"] == "WOM_E1_WF_R1_M01"][0]
    m3 = [m for m in snap["matches"] if m["match_code"] == "WOM_E1_WF_R2_M01"][0]

    a1 = session.exec(
        select(MatchAssignment).where(
            MatchAssignment.schedule_version_id == draft_id,
            MatchAssignment.match_id == m1["match_id"],
        )
    ).first()
    a3 = session.exec(
        select(MatchAssignment).where(
            MatchAssignment.schedule_version_id == draft_id,
            MatchAssignment.match_id == m3["match_id"],
        )
    ).first()
    assert a1 is not None
    assert a3 is not None

    slot1 = session.get(ScheduleSlot, a1.slot_id)
    slot3 = session.get(ScheduleSlot, a3.slot_id)
    assert slot1 is not None
    assert slot3 is not None

    # Force both slots into a far-future day to ensure slot start has not arrived.
    future_day = date(2099, 1, 1)
    slot1.day_date = future_day
    slot1.start_time = time(9, 0)
    slot1.end_time = time(10, 0)
    slot3.day_date = future_day
    slot3.start_time = time(11, 0)
    slot3.end_time = time(12, 0)
    session.add(slot1)
    session.add(slot3)

    # Give the downstream match concrete teams so only the time guard prevents auto-start.
    m3_obj = session.get(Match, m3["match_id"])
    assert m3_obj is not None
    m3_obj.team_a_id = teams[0].id
    m3_obj.team_b_id = teams[1].id
    session.add(m3_obj)
    session.commit()

    fin_resp = client.patch(
        f"/api/desk/tournaments/{t.id}/matches/{m1['match_id']}/finalize",
        json={"version_id": draft_id, "score": "8-4", "winner_team_id": m1["team1_id"]},
    )
    assert fin_resp.status_code == 200
    body = fin_resp.json()
    assert body["auto_started"] is None

    session.refresh(m3_obj)
    assert (m3_obj.runtime_status or "SCHEDULED") == "SCHEDULED"


def test_finalize_does_not_auto_start_in_checkin_management_mode(client, session):
    """Check-in mode should never auto-start downstream matches on finalize."""
    t, _v, _ev, teams, _matches = _setup_tournament_with_matches(session)

    draft_resp = client.post(f"/api/desk/tournaments/{t.id}/working-draft")
    draft_id = draft_resp.json()["version_id"]

    mode_resp = client.patch(
        f"/api/desk/tournaments/{t.id}/management-mode",
        json={"version_id": draft_id, "management_mode": "checkin_management"},
    )
    assert mode_resp.status_code == 200

    snap = client.get(f"/api/desk/tournaments/{t.id}/snapshot?version_id={draft_id}").json()
    m1 = [m for m in snap["matches"] if m["match_code"] == "WOM_E1_WF_R1_M01"][0]
    m3 = [m for m in snap["matches"] if m["match_code"] == "WOM_E1_WF_R2_M01"][0]

    a1 = session.exec(
        select(MatchAssignment).where(
            MatchAssignment.schedule_version_id == draft_id,
            MatchAssignment.match_id == m1["match_id"],
        )
    ).first()
    a3 = session.exec(
        select(MatchAssignment).where(
            MatchAssignment.schedule_version_id == draft_id,
            MatchAssignment.match_id == m3["match_id"],
        )
    ).first()
    assert a1 is not None
    assert a3 is not None

    # Force slot-start guard to pass (past day/times) and ensure both teams exist.
    slot1 = session.get(ScheduleSlot, a1.slot_id)
    slot3 = session.get(ScheduleSlot, a3.slot_id)
    assert slot1 is not None
    assert slot3 is not None
    past_day = date(2000, 1, 1)
    slot1.day_date = past_day
    slot1.start_time = time(9, 0)
    slot1.end_time = time(10, 0)
    slot3.day_date = past_day
    slot3.start_time = time(10, 0)
    slot3.end_time = time(11, 0)
    session.add(slot1)
    session.add(slot3)

    m3_obj = session.get(Match, m3["match_id"])
    assert m3_obj is not None
    m3_obj.team_a_id = teams[0].id
    m3_obj.team_b_id = teams[1].id
    session.add(m3_obj)
    session.commit()

    fin_resp = client.patch(
        f"/api/desk/tournaments/{t.id}/matches/{m1['match_id']}/finalize",
        json={"version_id": draft_id, "score": "8-4", "winner_team_id": m1["team1_id"]},
    )
    assert fin_resp.status_code == 200
    body = fin_resp.json()
    assert body["auto_started"] is None

    session.refresh(m3_obj)
    assert (m3_obj.runtime_status or "SCHEDULED") == "SCHEDULED"


# ── Impact endpoint tests ──────────────────────────────────────────────

def test_impact_terminal_match_null_targets(client, session):
    """R2 match (no downstream) returns null winner/loser targets."""
    t, v, ev, teams, matches = _setup_tournament_with_matches(session)

    draft_resp = client.post(f"/api/desk/tournaments/{t.id}/working-draft")
    draft_id = draft_resp.json()["version_id"]

    snap = client.get(f"/api/desk/tournaments/{t.id}/snapshot?version_id={draft_id}").json()
    r2 = [m for m in snap["matches"] if m["match_code"] == "WOM_E1_WF_R2_M01"][0]

    resp = client.get(
        f"/api/desk/tournaments/{t.id}/impact?version_id={draft_id}&match_id={r2['match_id']}"
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["impacts"]) == 1
    imp = body["impacts"][0]
    assert imp["winner_target"] is None
    assert imp["loser_target"] is None
    assert imp["winner_terminal_label"] == "Champion"
    assert imp["loser_terminal_label"] == "Runner-up"


def test_impact_normal_match_shows_both_targets(client, session):
    """R1 matches that feed R2 show winner targets with correct slot mapping."""
    t, v, ev, teams, matches = _setup_tournament_with_matches(session)

    draft_resp = client.post(f"/api/desk/tournaments/{t.id}/working-draft")
    draft_id = draft_resp.json()["version_id"]

    resp = client.get(f"/api/desk/tournaments/{t.id}/impact?version_id={draft_id}")
    assert resp.status_code == 200
    body = resp.json()

    # Find R1 M1 impact
    m1_imp = [i for i in body["impacts"] if i["match_code"] == "WOM_E1_WF_R1_M01"][0]
    assert m1_imp["winner_target"] is not None
    assert m1_imp["winner_target"]["target_slot"] == "team_a"
    assert m1_imp["winner_target"]["blocked_reason"] is None
    assert m1_imp["winner_target"]["target_court"] == "Court 1"
    assert m1_imp["winner_target"]["target_time"] == "11:00 AM"
    assert m1_imp["winner_target"]["waiting_on_match_number"] is not None
    assert m1_imp["winner_target"]["waiting_on_role"] == "WINNER"
    assert m1_imp["winner_target"]["waiting_on_court"] == "Court 2"
    assert m1_imp["winner_target"]["waiting_on_time"] == "9:00 AM"

    # Find R1 M2 impact
    m2_imp = [i for i in body["impacts"] if i["match_code"] == "WOM_E1_WF_R1_M02"][0]
    assert m2_imp["winner_target"] is not None
    assert m2_imp["winner_target"]["target_slot"] == "team_b"
    assert m2_imp["winner_target"]["blocked_reason"] is None

    # R2 has no downstream
    r2_imp = [i for i in body["impacts"] if i["match_code"] == "WOM_E1_WF_R2_M01"][0]
    assert r2_imp["winner_target"] is None


def test_impact_locked_slot_shows_blocked(client, session):
    """If downstream match is locked, impact shows SLOT_LOCKED."""
    t, v, ev, teams, matches = _setup_tournament_with_matches(session)

    draft_resp = client.post(f"/api/desk/tournaments/{t.id}/working-draft")
    draft_id = draft_resp.json()["version_id"]

    # Find the draft R2 match and its slot
    snap = client.get(f"/api/desk/tournaments/{t.id}/snapshot?version_id={draft_id}").json()
    r2 = [m for m in snap["matches"] if m["match_code"] == "WOM_E1_WF_R2_M01"][0]

    # Find the slot for R2
    draft_version_matches = session.exec(
        select(Match).where(Match.schedule_version_id == draft_id)
    ).all()
    r2_match = [m for m in draft_version_matches if m.match_code == "WOM_E1_WF_R2_M01"][0]
    assignment = session.exec(
        select(MatchAssignment).where(
            MatchAssignment.schedule_version_id == draft_id,
            MatchAssignment.match_id == r2_match.id,
        )
    ).first()

    # Lock the R2 match
    lock = MatchLock(
        schedule_version_id=draft_id,
        match_id=r2_match.id,
        slot_id=assignment.slot_id,
    )
    session.add(lock)
    session.commit()

    # Check impact for R1 M1 — its winner target (R2) should be SLOT_LOCKED
    resp = client.get(
        f"/api/desk/tournaments/{t.id}/impact?version_id={draft_id}"
    )
    assert resp.status_code == 200
    body = resp.json()

    m1_imp = [i for i in body["impacts"] if i["match_code"] == "WOM_E1_WF_R1_M01"][0]
    assert m1_imp["winner_target"] is not None
    assert m1_imp["winner_target"]["blocked_reason"] == "SLOT_LOCKED"


# ── Conflict check tests ──────────────────────────────────────────────

def test_conflict_team_already_playing(client, session):
    """If a team is IN_PROGRESS in another match, warn TEAM_ALREADY_PLAYING."""
    t, v, ev, teams, matches = _setup_tournament_with_matches(session)

    draft_resp = client.post(f"/api/desk/tournaments/{t.id}/working-draft")
    draft_id = draft_resp.json()["version_id"]

    snap = client.get(f"/api/desk/tournaments/{t.id}/snapshot?version_id={draft_id}").json()
    m1 = [m for m in snap["matches"] if m["match_code"] == "WOM_E1_WF_R1_M01"][0]
    m3 = [m for m in snap["matches"] if m["match_code"] == "WOM_E1_WF_R2_M01"][0]

    # Finalize M1 so winner (Alpha) advances to M3's team_a slot
    client.patch(
        f"/api/desk/tournaments/{t.id}/matches/{m1['match_id']}/finalize",
        json={"version_id": draft_id, "score": "8-4", "winner_team_id": m1["team1_id"]},
    )

    # Set M3 (which now has Alpha in team_a) to IN_PROGRESS
    client.patch(
        f"/api/desk/tournaments/{t.id}/matches/{m3['match_id']}/status",
        json={"version_id": draft_id, "status": "IN_PROGRESS"},
    )

    # Now check M1 again (Alpha is still in M1's team_a and M3 is IN_PROGRESS for Alpha)
    # Use a fresh match that also has the same team — but our test setup only has Alpha in M1 and M3.
    # Check conflicts for setting M1 IN_PROGRESS (Alpha is already playing M3)
    # M1 is already FINAL so let's check M3 first scenario differently.

    # Actually: Alpha is in both M1 (FINAL) and M3 (IN_PROGRESS).
    # We need a scenario where a team is IN_PROGRESS in one match and we try to start another.
    # M2 has teams Bravo and Charlie. Let's make another match with Bravo.
    # Easier: set M2 IN_PROGRESS (Bravo/Charlie), then check conflicts for M3 which
    # doesn't have Bravo. Let's instead check M1-based scenario:

    # Reload snap to see updated state
    snap2 = client.get(f"/api/desk/tournaments/{t.id}/snapshot?version_id={draft_id}").json()
    m2 = [m for m in snap2["matches"] if m["match_code"] == "WOM_E1_WF_R1_M02"][0]

    # Set M2 IN_PROGRESS (Bravo vs Charlie)
    client.patch(
        f"/api/desk/tournaments/{t.id}/matches/{m2['match_id']}/status",
        json={"version_id": draft_id, "status": "IN_PROGRESS"},
    )

    # M3 now has Alpha (from advancement) — but M3 also has source_b from M2.
    # After M2 finalize, winner goes to M3 team_b. But M2 is only IN_PROGRESS, not finalized.
    # So M3 still has no team_b. But checking conflicts for M3: Alpha is in M3 and M3 is already IN_PROGRESS.
    # Let's check conflicts for M2 to see if Bravo or Charlie are in another IN_PROGRESS match.
    # They aren't. So let's use a different approach:

    # Simplest: M3 is IN_PROGRESS (Alpha). Check conflicts for M1 with Alpha.
    # But M1 is FINAL. Check conflicts for a SCHEDULED match with Alpha would work if one existed.

    # The cleanest test: just add another match with Alpha/Delta scheduled on same version.
    draft_matches = session.exec(
        select(Match).where(Match.schedule_version_id == draft_id)
    ).all()
    # Find Alpha's team ID (team1 of M1)
    alpha_id = m1["team1_id"]

    # Create a new match in the draft with Alpha
    new_match = Match(
        tournament_id=t.id,
        event_id=ev.id,
        schedule_version_id=draft_id,
        match_code="WOM_E1_TEST_EXTRA",
        match_type="WF",
        round_number=1,
        round_index=1,
        sequence_in_round=99,
        duration_minutes=60,
        team_a_id=alpha_id,
        placeholder_side_a="Alpha",
        placeholder_side_b="TBD",
    )
    session.add(new_match)
    session.flush()

    # Create a slot and assignment for the new match
    new_slot = ScheduleSlot(
        tournament_id=t.id,
        schedule_version_id=draft_id,
        day_date=date(2026, 6, 5),
        start_time=time(11, 0),
        end_time=time(12, 0),
        court_number=3,
        court_label="3",
        block_minutes=60,
    )
    session.add(new_slot)
    session.flush()
    session.add(MatchAssignment(schedule_version_id=draft_id, match_id=new_match.id, slot_id=new_slot.id))
    session.commit()

    # Alpha is IN_PROGRESS in M3. Check conflicts for new_match (also has Alpha).
    resp = client.post(
        f"/api/desk/tournaments/{t.id}/conflicts/check",
        json={"version_id": draft_id, "action_type": "SET_IN_PROGRESS", "match_id": new_match.id},
    )
    assert resp.status_code == 200
    body = resp.json()
    codes = [c["code"] for c in body["conflicts"]]
    assert "TEAM_ALREADY_PLAYING" in codes


def test_conflict_day_cap_exceeded(client, session):
    """If a team already has 2 FINAL/IN_PROGRESS matches on same day, warn DAY_CAP_EXCEEDED."""
    t, v, ev, teams, matches = _setup_tournament_with_matches(session)

    draft_resp = client.post(f"/api/desk/tournaments/{t.id}/working-draft")
    draft_id = draft_resp.json()["version_id"]

    snap = client.get(f"/api/desk/tournaments/{t.id}/snapshot?version_id={draft_id}").json()
    m1 = [m for m in snap["matches"] if m["match_code"] == "WOM_E1_WF_R1_M01"][0]
    m2 = [m for m in snap["matches"] if m["match_code"] == "WOM_E1_WF_R1_M02"][0]
    alpha_id = m1["team1_id"]

    # Finalize M1 (Alpha wins) — Alpha has 1 FINAL match on Day 1
    client.patch(
        f"/api/desk/tournaments/{t.id}/matches/{m1['match_id']}/finalize",
        json={"version_id": draft_id, "score": "8-4", "winner_team_id": alpha_id},
    )

    # M3 has Alpha advanced. Set M3 IN_PROGRESS — Alpha now has 1 FINAL + 1 IN_PROGRESS = 2 on Day 1
    snap2 = client.get(f"/api/desk/tournaments/{t.id}/snapshot?version_id={draft_id}").json()
    m3 = [m for m in snap2["matches"] if m["match_code"] == "WOM_E1_WF_R2_M01"][0]

    client.patch(
        f"/api/desk/tournaments/{t.id}/matches/{m3['match_id']}/status",
        json={"version_id": draft_id, "status": "IN_PROGRESS"},
    )

    # Now add a 3rd match for Alpha on the same day
    new_match = Match(
        tournament_id=t.id,
        event_id=ev.id,
        schedule_version_id=draft_id,
        match_code="WOM_E1_DAY_CAP_TEST",
        match_type="WF",
        round_number=1,
        round_index=1,
        sequence_in_round=99,
        duration_minutes=60,
        team_a_id=alpha_id,
        placeholder_side_a="Alpha",
        placeholder_side_b="TBD",
    )
    session.add(new_match)
    session.flush()

    new_slot = ScheduleSlot(
        tournament_id=t.id,
        schedule_version_id=draft_id,
        day_date=date(2026, 6, 5),
        start_time=time(14, 0),
        end_time=time(15, 0),
        court_number=3,
        court_label="3",
        block_minutes=60,
    )
    session.add(new_slot)
    session.flush()
    session.add(MatchAssignment(schedule_version_id=draft_id, match_id=new_match.id, slot_id=new_slot.id))
    session.commit()

    resp = client.post(
        f"/api/desk/tournaments/{t.id}/conflicts/check",
        json={"version_id": draft_id, "action_type": "SET_IN_PROGRESS", "match_id": new_match.id},
    )
    assert resp.status_code == 200
    body = resp.json()
    codes = [c["code"] for c in body["conflicts"]]
    assert "DAY_CAP_EXCEEDED" in codes
    cap_warning = [c for c in body["conflicts"] if c["code"] == "DAY_CAP_EXCEEDED"][0]
    assert cap_warning["details"]["count"] == 3


def test_conflict_rest_too_short(client, session):
    """If rest time between matches < MIN_REST_MINUTES, warn REST_TOO_SHORT."""
    t, v, ev, teams, matches = _setup_tournament_with_matches(session)

    draft_resp = client.post(f"/api/desk/tournaments/{t.id}/working-draft")
    draft_id = draft_resp.json()["version_id"]

    snap = client.get(f"/api/desk/tournaments/{t.id}/snapshot?version_id={draft_id}").json()
    m1 = [m for m in snap["matches"] if m["match_code"] == "WOM_E1_WF_R1_M01"][0]
    alpha_id = m1["team1_id"]

    # Finalize M1 at 9:00 (Alpha wins). M1 slot: 9:00-10:00 (60 min block)
    client.patch(
        f"/api/desk/tournaments/{t.id}/matches/{m1['match_id']}/finalize",
        json={"version_id": draft_id, "score": "8-4", "winner_team_id": alpha_id},
    )

    # Create a match for Alpha starting at 10:15 — only 15 min rest after 10:00 end
    new_match = Match(
        tournament_id=t.id,
        event_id=ev.id,
        schedule_version_id=draft_id,
        match_code="WOM_E1_REST_TEST",
        match_type="WF",
        round_number=1,
        round_index=1,
        sequence_in_round=99,
        duration_minutes=60,
        team_a_id=alpha_id,
        placeholder_side_a="Alpha",
        placeholder_side_b="TBD",
    )
    session.add(new_match)
    session.flush()

    new_slot = ScheduleSlot(
        tournament_id=t.id,
        schedule_version_id=draft_id,
        day_date=date(2026, 6, 5),
        start_time=time(10, 15),
        end_time=time(11, 15),
        court_number=3,
        court_label="3",
        block_minutes=60,
    )
    session.add(new_slot)
    session.flush()
    session.add(MatchAssignment(schedule_version_id=draft_id, match_id=new_match.id, slot_id=new_slot.id))
    session.commit()

    resp = client.post(
        f"/api/desk/tournaments/{t.id}/conflicts/check",
        json={"version_id": draft_id, "action_type": "SET_IN_PROGRESS", "match_id": new_match.id},
    )
    assert resp.status_code == 200
    body = resp.json()
    codes = [c["code"] for c in body["conflicts"]]
    assert "REST_TOO_SHORT" in codes
    rest_warning = [c for c in body["conflicts"] if c["code"] == "REST_TOO_SHORT"][0]
    assert rest_warning["details"]["rest_minutes"] == 15


# ── Timeline tests ──────────────────────────────────────────────────────

def test_timeline_created_at_present(client, session):
    """Every match in snapshot has created_at timestamp."""
    t, v, ev, teams, matches = _setup_tournament_with_matches(session)

    draft_resp = client.post(f"/api/desk/tournaments/{t.id}/working-draft")
    draft_id = draft_resp.json()["version_id"]

    snap = client.get(f"/api/desk/tournaments/{t.id}/snapshot?version_id={draft_id}").json()
    for m in snap["matches"]:
        assert m["created_at"] is not None
        assert m["started_at"] is None
        assert m["completed_at"] is None
        assert m["winner_display"] is None


def test_timeline_in_progress_sets_started_at(client, session):
    """Setting IN_PROGRESS sets started_at and preserves it on re-call."""
    t, v, ev, teams, matches = _setup_tournament_with_matches(session)

    draft_resp = client.post(f"/api/desk/tournaments/{t.id}/working-draft")
    draft_id = draft_resp.json()["version_id"]

    snap = client.get(f"/api/desk/tournaments/{t.id}/snapshot?version_id={draft_id}").json()
    m1 = [m for m in snap["matches"] if m["match_code"] == "WOM_E1_WF_R1_M01"][0]

    client.patch(
        f"/api/desk/tournaments/{t.id}/matches/{m1['match_id']}/status",
        json={"version_id": draft_id, "status": "IN_PROGRESS"},
    )

    snap2 = client.get(f"/api/desk/tournaments/{t.id}/snapshot?version_id={draft_id}").json()
    m1_after = [m for m in snap2["matches"] if m["match_code"] == "WOM_E1_WF_R1_M01"][0]
    assert m1_after["started_at"] is not None
    first_started = m1_after["started_at"]

    # Set IN_PROGRESS again — started_at should not change
    client.patch(
        f"/api/desk/tournaments/{t.id}/matches/{m1['match_id']}/status",
        json={"version_id": draft_id, "status": "IN_PROGRESS"},
    )

    snap3 = client.get(f"/api/desk/tournaments/{t.id}/snapshot?version_id={draft_id}").json()
    m1_again = [m for m in snap3["matches"] if m["match_code"] == "WOM_E1_WF_R1_M01"][0]
    assert m1_again["started_at"] == first_started


def test_timeline_finalize_sets_completed_at_and_winner(client, session):
    """Finalizing sets completed_at and winner_display. Re-finalize preserves timestamps."""
    t, v, ev, teams, matches = _setup_tournament_with_matches(session)

    draft_resp = client.post(f"/api/desk/tournaments/{t.id}/working-draft")
    draft_id = draft_resp.json()["version_id"]

    snap = client.get(f"/api/desk/tournaments/{t.id}/snapshot?version_id={draft_id}").json()
    m1 = [m for m in snap["matches"] if m["match_code"] == "WOM_E1_WF_R1_M01"][0]

    client.patch(
        f"/api/desk/tournaments/{t.id}/matches/{m1['match_id']}/finalize",
        json={"version_id": draft_id, "score": "8-4", "winner_team_id": m1["team1_id"]},
    )

    snap2 = client.get(f"/api/desk/tournaments/{t.id}/snapshot?version_id={draft_id}").json()
    m1_after = [m for m in snap2["matches"] if m["match_code"] == "WOM_E1_WF_R1_M01"][0]
    assert m1_after["completed_at"] is not None
    assert m1_after["winner_display"] is not None
    assert m1_after["status"] == "FINAL"
    first_completed = m1_after["completed_at"]

    # Re-finalize same payload — completed_at should not change
    client.patch(
        f"/api/desk/tournaments/{t.id}/matches/{m1['match_id']}/finalize",
        json={"version_id": draft_id, "score": "8-4", "winner_team_id": m1["team1_id"]},
    )

    snap3 = client.get(f"/api/desk/tournaments/{t.id}/snapshot?version_id={draft_id}").json()
    m1_again = [m for m in snap3["matches"] if m["match_code"] == "WOM_E1_WF_R1_M01"][0]
    assert m1_again["completed_at"] == first_completed


# ── Bulk Status tests ──────────────────────────────────────────────────

def test_bulk_pause_updates_in_progress_only(client, session):
    """Bulk pause sets only IN_PROGRESS matches to PAUSED, rejects FINAL version."""
    t, v, ev, teams, matches = _setup_tournament_with_matches(session)

    draft_resp = client.post(f"/api/desk/tournaments/{t.id}/working-draft")
    draft_id = draft_resp.json()["version_id"]

    snap = client.get(f"/api/desk/tournaments/{t.id}/snapshot?version_id={draft_id}").json()
    m1 = [m for m in snap["matches"] if m["match_code"] == "WOM_E1_WF_R1_M01"][0]
    m2 = [m for m in snap["matches"] if m["match_code"] == "WOM_E1_WF_R1_M02"][0]

    # Set m1 to IN_PROGRESS
    client.patch(
        f"/api/desk/tournaments/{t.id}/matches/{m1['match_id']}/status",
        json={"version_id": draft_id, "status": "IN_PROGRESS"},
    )

    # Bulk pause
    resp = client.post(
        f"/api/desk/tournaments/{t.id}/bulk/pause-in-progress",
        json={"version_id": draft_id},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["updated_count"] == 1
    assert m1["match_id"] in body["updated_match_numbers"]

    # Verify m1 is PAUSED, m2 still SCHEDULED
    snap2 = client.get(f"/api/desk/tournaments/{t.id}/snapshot?version_id={draft_id}").json()
    m1_after = [m for m in snap2["matches"] if m["match_code"] == "WOM_E1_WF_R1_M01"][0]
    m2_after = [m for m in snap2["matches"] if m["match_code"] == "WOM_E1_WF_R1_M02"][0]
    assert m1_after["status"] == "PAUSED"
    assert m2_after["status"] == "SCHEDULED"

    # Reject FINAL version
    resp2 = client.post(
        f"/api/desk/tournaments/{t.id}/bulk/pause-in-progress",
        json={"version_id": v.id},
    )
    assert resp2.status_code == 400


def test_bulk_delay_after_updates_scheduled_only(client, session):
    """Bulk delay-after sets SCHEDULED matches at or after threshold to DELAYED."""
    t, v, ev, teams, matches = _setup_tournament_with_matches(session)

    draft_resp = client.post(f"/api/desk/tournaments/{t.id}/working-draft")
    draft_id = draft_resp.json()["version_id"]

    snap = client.get(f"/api/desk/tournaments/{t.id}/snapshot?version_id={draft_id}").json()
    m1 = [m for m in snap["matches"] if m["match_code"] == "WOM_E1_WF_R1_M01"][0]

    # Set m1 to IN_PROGRESS so it won't be delayed
    client.patch(
        f"/api/desk/tournaments/{t.id}/matches/{m1['match_id']}/status",
        json={"version_id": draft_id, "status": "IN_PROGRESS"},
    )

    # Delay all scheduled matches after 10:00 — m2 (9:00) should NOT be delayed, m3 (11:00) should be
    resp = client.post(
        f"/api/desk/tournaments/{t.id}/bulk/delay-after",
        json={"version_id": draft_id, "after_time": "10:00"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["updated_count"] >= 1

    snap2 = client.get(f"/api/desk/tournaments/{t.id}/snapshot?version_id={draft_id}").json()
    m2_after = [m for m in snap2["matches"] if m["match_code"] == "WOM_E1_WF_R1_M02"][0]
    m3_after = [m for m in snap2["matches"] if m["match_code"] == "WOM_E1_WF_R2_M01"][0]
    assert m2_after["status"] == "SCHEDULED"  # 9:00 AM, before threshold
    assert m3_after["status"] == "DELAYED"  # 11:00 AM, at or after threshold

    # Reject FINAL version
    resp2 = client.post(
        f"/api/desk/tournaments/{t.id}/bulk/delay-after",
        json={"version_id": v.id, "after_time": "10:00"},
    )
    assert resp2.status_code == 400


def test_bulk_delay_respects_day_index(client, session):
    """Delay-after with day_index filter only affects matches on that day."""
    t, v, ev, teams, matches = _setup_tournament_with_matches(session)

    draft_resp = client.post(f"/api/desk/tournaments/{t.id}/working-draft")
    draft_id = draft_resp.json()["version_id"]

    # All test matches are on day 1, so day_index=2 should affect nothing
    resp = client.post(
        f"/api/desk/tournaments/{t.id}/bulk/delay-after",
        json={"version_id": draft_id, "after_time": "08:00", "day_index": 2},
    )
    assert resp.status_code == 200
    assert resp.json()["updated_count"] == 0


def test_paused_delayed_status_via_status_endpoint(client, session):
    """The status endpoint accepts PAUSED and DELAYED as valid statuses."""
    t, v, ev, teams, matches = _setup_tournament_with_matches(session)

    draft_resp = client.post(f"/api/desk/tournaments/{t.id}/working-draft")
    draft_id = draft_resp.json()["version_id"]

    snap = client.get(f"/api/desk/tournaments/{t.id}/snapshot?version_id={draft_id}").json()
    m1 = [m for m in snap["matches"] if m["match_code"] == "WOM_E1_WF_R1_M01"][0]

    # Set PAUSED
    resp = client.patch(
        f"/api/desk/tournaments/{t.id}/matches/{m1['match_id']}/status",
        json={"version_id": draft_id, "status": "PAUSED"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "PAUSED"

    # Set DELAYED
    resp2 = client.patch(
        f"/api/desk/tournaments/{t.id}/matches/{m1['match_id']}/status",
        json={"version_id": draft_id, "status": "DELAYED"},
    )
    assert resp2.status_code == 200
    assert resp2.json()["status"] == "DELAYED"


# ── Court State tests ──────────────────────────────────────────────────

def test_court_state_upsert_and_get(client, session):
    """Patching court state creates row, subsequent GET returns it."""
    t, v, ev, teams, matches = _setup_tournament_with_matches(session)

    # Patch court "1" to closed
    resp = client.patch(
        f"/api/desk/tournaments/{t.id}/courts/1/state",
        json={"is_closed": True, "note": "Wet court"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["is_closed"] is True
    assert body["note"] == "Wet court"
    assert body["court_label"] == "1"

    # GET all court states
    resp2 = client.get(f"/api/desk/tournaments/{t.id}/courts/state")
    assert resp2.status_code == 200
    states = resp2.json()
    assert len(states) >= 1
    court1 = [s for s in states if s["court_label"] == "1"][0]
    assert court1["is_closed"] is True
    assert court1["note"] == "Wet court"


def test_court_state_update_preserves_fields(client, session):
    """Updating only note preserves is_closed, and vice versa."""
    t, v, ev, teams, matches = _setup_tournament_with_matches(session)

    client.patch(
        f"/api/desk/tournaments/{t.id}/courts/1/state",
        json={"is_closed": True, "note": "Rain"},
    )

    # Update only note
    resp = client.patch(
        f"/api/desk/tournaments/{t.id}/courts/1/state",
        json={"note": "Drying off"},
    )
    assert resp.status_code == 200
    assert resp.json()["is_closed"] is True
    assert resp.json()["note"] == "Drying off"

    # Update only is_closed
    resp2 = client.patch(
        f"/api/desk/tournaments/{t.id}/courts/1/state",
        json={"is_closed": False},
    )
    assert resp2.status_code == 200
    assert resp2.json()["is_closed"] is False
    assert resp2.json()["note"] == "Drying off"


def test_court_state_rejects_empty_patch(client, session):
    """Patching with no fields returns 400."""
    t, v, ev, teams, matches = _setup_tournament_with_matches(session)

    resp = client.patch(
        f"/api/desk/tournaments/{t.id}/courts/1/state",
        json={},
    )
    assert resp.status_code == 400


# ── Score parser unit tests ──────────────────────────────────────────────

def test_score_parser_simple():
    """Parse a simple one-set score like '8-4'."""
    from app.services.score_parser import parse_score

    result = parse_score({"display": "8-4"})
    assert result is not None
    assert len(result.sets) == 1
    assert result.team_a_sets_won == 1
    assert result.team_b_sets_won == 0
    assert result.team_a_games == 8
    assert result.team_b_games == 4


def test_score_parser_three_sets():
    """Parse a three-set score like '6-3 4-6 10-7'."""
    from app.services.score_parser import parse_score

    result = parse_score({"display": "6-3 4-6 10-7"})
    assert result is not None
    assert len(result.sets) == 3
    assert result.team_a_sets_won == 2
    assert result.team_b_sets_won == 1
    assert result.team_a_games == 20  # 6+4+10
    assert result.team_b_games == 16  # 3+6+7


def test_score_parser_match_tiebreak_set_counts_no_games():
    """A 1-0 third-set tiebreak counts as a set, not as games."""
    from app.services.score_parser import parse_score

    result = parse_score({"display": "7-6 4-6 1-0"})
    assert result is not None
    assert result.team_a_sets_won == 2
    assert result.team_b_sets_won == 1
    assert result.team_a_games == 11  # 7 + 4 (+0 for 1-0 tiebreak set)
    assert result.team_b_games == 12  # 6 + 6 (+0 for 0-1 tiebreak set)


def test_score_parser_none():
    """Parsing None returns None."""
    from app.services.score_parser import parse_score

    assert parse_score(None) is None
    assert parse_score({}) is None
    assert parse_score({"display": ""}) is None


def test_score_validation_by_duration_rules():
    """Score validator enforces PRO_SET_8 / PRO_SET_4 / REGULAR rules."""
    from app.services.score_parser import validate_score_for_duration

    # 8-game pro set (60 min)
    assert validate_score_for_duration("8-6", 60)[0] is True
    assert validate_score_for_duration("9-8", 60)[0] is True
    assert validate_score_for_duration("6-3, 6-2", 60)[0] is True  # regular also allowed at 60
    assert validate_score_for_duration("5-3", 60)[0] is False

    # 4-game pro set (35 min)
    assert validate_score_for_duration("5-4", 35)[0] is True
    assert validate_score_for_duration("4-1", 35)[0] is True
    assert validate_score_for_duration("8-6", 35)[0] is False

    # Regular (105 min)
    assert validate_score_for_duration("6-4, 7-5", 105)[0] is True
    assert validate_score_for_duration("7-6 4-6 1-0", 105)[0] is True
    assert validate_score_for_duration("5-3", 105)[0] is False
    assert validate_score_for_duration("6-4 4-6", 105)[0] is False  # split sets require 3rd set


# ── Standings endpoint tests ─────────────────────────────────────────────

def _setup_rr_tournament(session: Session):
    """Create a tournament with an RR event, 4 teams, and 3 RR matches."""
    t = Tournament(
        name="RR Test",
        location="Test Beach",
        timezone="America/New_York",
        start_date=date(2026, 6, 5),
        end_date=date(2026, 6, 7),
    )
    session.add(t)
    session.flush()

    v = ScheduleVersion(
        tournament_id=t.id,
        version_number=1,
        status="final",
    )
    session.add(v)
    session.flush()

    ev = Event(
        tournament_id=t.id,
        category="womens",
        name="Women's A",
        team_count=4,
    )
    session.add(ev)
    session.flush()

    team1 = Team(event_id=ev.id, name="Alpha - VA", seed=1, display_name="Alpha")
    team2 = Team(event_id=ev.id, name="Bravo - NC", seed=2, display_name="Bravo")
    team3 = Team(event_id=ev.id, name="Charlie - FL", seed=3, display_name="Charlie")
    session.add_all([team1, team2, team3])
    session.flush()

    # RR Match 1: Alpha vs Bravo (in POOLA)
    m1 = Match(
        tournament_id=t.id,
        event_id=ev.id,
        schedule_version_id=v.id,
        match_code="WOM_E1_RR_POOLA_M01",
        match_type="RR",
        round_number=1,
        round_index=1,
        sequence_in_round=1,
        duration_minutes=60,
        team_a_id=team1.id,
        team_b_id=team2.id,
        placeholder_side_a="Seed 1",
        placeholder_side_b="Seed 2",
    )
    # RR Match 2: Alpha vs Charlie (in POOLA)
    m2 = Match(
        tournament_id=t.id,
        event_id=ev.id,
        schedule_version_id=v.id,
        match_code="WOM_E1_RR_POOLA_M02",
        match_type="RR",
        round_number=1,
        round_index=1,
        sequence_in_round=2,
        duration_minutes=60,
        team_a_id=team1.id,
        team_b_id=team3.id,
        placeholder_side_a="Seed 1",
        placeholder_side_b="Seed 3",
    )
    # RR Match 3: Bravo vs Charlie (in POOLA)
    m3 = Match(
        tournament_id=t.id,
        event_id=ev.id,
        schedule_version_id=v.id,
        match_code="WOM_E1_RR_POOLA_M03",
        match_type="RR",
        round_number=1,
        round_index=1,
        sequence_in_round=3,
        duration_minutes=60,
        team_a_id=team2.id,
        team_b_id=team3.id,
        placeholder_side_a="Seed 2",
        placeholder_side_b="Seed 3",
    )
    session.add_all([m1, m2, m3])
    session.flush()

    # Create slots + assignments
    for i, m in enumerate([m1, m2, m3]):
        slot = ScheduleSlot(
            tournament_id=t.id,
            schedule_version_id=v.id,
            day_date=date(2026, 6, 5),
            start_time=time(9 + i, 0),
            end_time=time(10 + i, 0),
            court_number=1,
            court_label="1",
            block_minutes=60,
        )
        session.add(slot)
        session.flush()
        session.add(MatchAssignment(schedule_version_id=v.id, match_id=m.id, slot_id=slot.id))

    t.public_schedule_version_id = v.id
    session.add(t)
    session.commit()

    return t, v, ev, [team1, team2, team3], [m1, m2, m3]


def test_standings_no_rr_matches(client, session):
    """No RR matches returns empty events list."""
    t, v, ev, teams, matches = _setup_tournament_with_matches(session)

    resp = client.get(f"/api/desk/tournaments/{t.id}/standings?version_id={v.id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["events"] == []


def test_standings_with_finalized_rr(client, session):
    """Finalized RR matches produce correct standings."""
    t, v, ev, teams, matches = _setup_rr_tournament(session)

    # Create draft
    draft_resp = client.post(f"/api/desk/tournaments/{t.id}/working-draft")
    draft_id = draft_resp.json()["version_id"]

    snap = client.get(f"/api/desk/tournaments/{t.id}/snapshot?version_id={draft_id}").json()
    rr_matches = [m for m in snap["matches"] if m["stage"] == "RR"]
    assert len(rr_matches) == 3

    # Finalize M1: Alpha beats Bravo 8-4
    m1 = rr_matches[0]
    client.patch(
        f"/api/desk/tournaments/{t.id}/matches/{m1['match_id']}/finalize",
        json={"version_id": draft_id, "score": "8-4", "winner_team_id": m1["team1_id"]},
    )

    # Finalize M2: Alpha beats Charlie 6-3 6-2
    m2 = rr_matches[1]
    client.patch(
        f"/api/desk/tournaments/{t.id}/matches/{m2['match_id']}/finalize",
        json={"version_id": draft_id, "score": "6-3 6-2", "winner_team_id": m2["team1_id"]},
    )

    resp = client.get(f"/api/desk/tournaments/{t.id}/standings?version_id={draft_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["events"]) >= 1

    ev_standings = body["events"][0]
    rows = ev_standings["rows"]
    assert len(rows) == 3  # all 3 teams

    # Alpha should be first with 2 wins
    assert rows[0]["team_display"] == "Alpha"
    assert rows[0]["rank"] == 1
    assert rows[0]["wins"] == 2
    assert rows[0]["losses"] == 0
    assert rows[0]["played"] == 2
    assert rows[0]["set_diff"] == rows[0]["sets_won"] - rows[0]["sets_lost"]
    assert rows[0]["game_diff"] == rows[0]["games_won"] - rows[0]["games_lost"]
    assert "W:" in rows[0]["rank_explanation"]

    # Bravo and Charlie each have 0 wins, 1 loss
    non_alpha = [r for r in rows if r["team_display"] != "Alpha"]
    for r in non_alpha:
        assert r["wins"] == 0
        assert r["losses"] == 1
        assert isinstance(r["rank"], int)
        assert "SetDiff" in r["rank_explanation"]


def test_standings_sorting_by_set_diff(client, session):
    """When wins are tied, set diff determines order."""
    t, v, ev, teams, matches = _setup_rr_tournament(session)

    draft_resp = client.post(f"/api/desk/tournaments/{t.id}/working-draft")
    draft_id = draft_resp.json()["version_id"]

    snap = client.get(f"/api/desk/tournaments/{t.id}/snapshot?version_id={draft_id}").json()
    rr_matches = sorted([m for m in snap["matches"] if m["stage"] == "RR"], key=lambda m: m["match_id"])

    # M1: Alpha beats Bravo 6-1 6-1 (dominant win)
    client.patch(
        f"/api/desk/tournaments/{t.id}/matches/{rr_matches[0]['match_id']}/finalize",
        json={"version_id": draft_id, "score": "6-1 6-1", "winner_team_id": rr_matches[0]["team1_id"]},
    )

    # M2: Charlie beats Alpha 4-6 4-6 (team_a=Alpha loses, team_b=Charlie wins)
    client.patch(
        f"/api/desk/tournaments/{t.id}/matches/{rr_matches[1]['match_id']}/finalize",
        json={"version_id": draft_id, "score": "4-6 4-6", "winner_team_id": rr_matches[1]["team2_id"]},
    )

    # M3: Bravo beats Charlie 7-5 7-5
    client.patch(
        f"/api/desk/tournaments/{t.id}/matches/{rr_matches[2]['match_id']}/finalize",
        json={"version_id": draft_id, "score": "7-5 7-5", "winner_team_id": rr_matches[2]["team1_id"]},
    )

    resp = client.get(f"/api/desk/tournaments/{t.id}/standings?version_id={draft_id}")
    body = resp.json()
    rows = body["events"][0]["rows"]

    # All 3 teams have 1 win, 1 loss — sort by set diff (all 0 from 2 sets each),
    # then game diff
    # Alpha: won 12-2 (games +10), lost 8-12 (games -4) => total games diff +6
    # Bravo: lost 2-12 (games -10), won 14-10 (games +4) => total games diff -6
    # Charlie: won 12-8 (games +4), lost 10-14 (games -4) => total games diff 0
    assert rows[0]["wins"] == 1
    assert rows[1]["wins"] == 1
    assert rows[2]["wins"] == 1
    # Alpha should be first (game diff +6), Charlie second (+2), Bravo last (-8)
    assert rows[0]["team_display"] == "Alpha"
    assert rows[1]["team_display"] == "Charlie"
    assert rows[2]["team_display"] == "Bravo"
    assert [rows[0]["rank"], rows[1]["rank"], rows[2]["rank"]] == [1, 2, 3]
    assert "GameDiff" in rows[0]["rank_explanation"]


def test_standings_score_orientation_follows_selected_winner(client, session):
    """If score is entered winner-first, standings should still credit selected winner."""
    t, v, ev, teams, matches = _setup_rr_tournament(session)

    draft_resp = client.post(f"/api/desk/tournaments/{t.id}/working-draft")
    draft_id = draft_resp.json()["version_id"]

    snap = client.get(f"/api/desk/tournaments/{t.id}/snapshot?version_id={draft_id}").json()
    rr_matches = [m for m in snap["matches"] if m["stage"] == "RR"]
    m1 = rr_matches[0]  # Alpha vs Bravo

    # Team2 selected as winner, score entered winner-first.
    client.patch(
        f"/api/desk/tournaments/{t.id}/matches/{m1['match_id']}/finalize",
        json={"version_id": draft_id, "score": "6-4 7-5", "winner_team_id": m1["team2_id"]},
    )

    resp = client.get(f"/api/desk/tournaments/{t.id}/standings?version_id={draft_id}")
    assert resp.status_code == 200
    rows = resp.json()["events"][0]["rows"]
    alpha = [r for r in rows if r["team_display"] == "Alpha"][0]
    bravo = [r for r in rows if r["team_display"] == "Bravo"][0]

    assert bravo["wins"] == 1
    assert bravo["sets_won"] == 2
    assert bravo["sets_lost"] == 0
    assert alpha["losses"] == 1
    assert alpha["sets_won"] == 0
    assert alpha["sets_lost"] == 2


def test_standings_retired_uses_literal_score_orientation(client, session):
    """Retired RR keeps entered set/game orientation even if winner is opposite side."""
    t, v, ev, teams, matches = _setup_rr_tournament(session)

    draft_resp = client.post(f"/api/desk/tournaments/{t.id}/working-draft")
    draft_id = draft_resp.json()["version_id"]

    snap = client.get(f"/api/desk/tournaments/{t.id}/snapshot?version_id={draft_id}").json()
    rr_matches = [m for m in snap["matches"] if m["stage"] == "RR"]
    m1 = rr_matches[0]  # Alpha vs Bravo

    client.patch(
        f"/api/desk/tournaments/{t.id}/matches/{m1['match_id']}/finalize",
        json={
            "version_id": draft_id,
            "score": "6-7",
            "winner_team_id": m1["team1_id"],
            "is_retired": True,
        },
    )

    resp = client.get(f"/api/desk/tournaments/{t.id}/standings?version_id={draft_id}")
    assert resp.status_code == 200
    rows = resp.json()["events"][0]["rows"]
    alpha = [r for r in rows if r["team_display"] == "Alpha"][0]
    bravo = [r for r in rows if r["team_display"] == "Bravo"][0]

    assert alpha["wins"] == 1
    assert bravo["losses"] == 1
    assert alpha["sets_won"] == 0 and alpha["sets_lost"] == 1
    assert bravo["sets_won"] == 1 and bravo["sets_lost"] == 0
    assert alpha["games_won"] == 6 and alpha["games_lost"] == 7
    assert bravo["games_won"] == 7 and bravo["games_lost"] == 6


def test_standings_ignores_non_rr_match_codes(client, session):
    """Standings should ignore finalized matches that are not true RR pool codes."""
    t, v, ev, teams, matches = _setup_rr_tournament(session)

    draft_resp = client.post(f"/api/desk/tournaments/{t.id}/working-draft")
    draft_id = draft_resp.json()["version_id"]

    snap = client.get(f"/api/desk/tournaments/{t.id}/snapshot?version_id={draft_id}").json()
    rr_matches = [m for m in snap["matches"] if m["stage"] == "RR"]
    assert len(rr_matches) == 3

    # Finalize one real RR match.
    m1 = rr_matches[0]
    client.patch(
        f"/api/desk/tournaments/{t.id}/matches/{m1['match_id']}/finalize",
        json={"version_id": draft_id, "score": "6-3 6-4", "winner_team_id": m1["team1_id"]},
    )

    # Inject a bad legacy record: code is WF but match_type is RR.
    bad = Match(
        tournament_id=t.id,
        event_id=ev.id,
        schedule_version_id=draft_id,
        match_code="WOM_E1_WF_R1_M99",
        match_type="RR",
        round_number=1,
        round_index=1,
        sequence_in_round=99,
        duration_minutes=60,
        team_a_id=teams[0].id,
        team_b_id=teams[1].id,
        placeholder_side_a="Seed 1",
        placeholder_side_b="Seed 2",
        runtime_status="FINAL",
        winner_team_id=teams[0].id,
        score_json={"display": "6-0 6-0"},
    )
    session.add(bad)
    session.commit()

    resp = client.get(f"/api/desk/tournaments/{t.id}/standings?version_id={draft_id}")
    assert resp.status_code == 200
    body = resp.json()
    rows = body["events"][0]["rows"]
    alpha = [r for r in rows if r["team_display"] == "Alpha"][0]

    # Should reflect only the real RR result above, not the injected WF-coded row.
    assert alpha["played"] == 1
    assert alpha["wins"] == 1
    assert alpha["sets_won"] == 2
    assert alpha["games_won"] == 12


def test_standings_supports_fifth_pool_division(client, session):
    """Standings should handle POOLE / Division V without crashing."""
    t = Tournament(
        name="RR Five Pool Test",
        location="Test Beach",
        timezone="America/New_York",
        start_date=date(2026, 6, 5),
        end_date=date(2026, 6, 7),
    )
    session.add(t)
    session.flush()

    v = ScheduleVersion(
        tournament_id=t.id,
        version_number=1,
        status="draft",
    )
    session.add(v)
    session.flush()

    ev = Event(
        tournament_id=t.id,
        category="mixed",
        name="Mixed A",
        team_count=4,
    )
    session.add(ev)
    session.flush()

    team1 = Team(event_id=ev.id, name="Alpha", seed=1, display_name="Alpha")
    team2 = Team(event_id=ev.id, name="Bravo", seed=2, display_name="Bravo")
    team3 = Team(event_id=ev.id, name="Echo", seed=3, display_name="Echo")
    team4 = Team(event_id=ev.id, name="Foxtrot", seed=4, display_name="Foxtrot")
    session.add_all([team1, team2, team3, team4])
    session.flush()

    session.add_all([
        Match(
            tournament_id=t.id,
            event_id=ev.id,
            schedule_version_id=v.id,
            match_code="MIX_E1_RR_POOLA_M01",
            match_type="RR",
            round_number=1,
            round_index=1,
            sequence_in_round=1,
            duration_minutes=60,
            team_a_id=team1.id,
            team_b_id=team2.id,
            placeholder_side_a="Seed 1",
            placeholder_side_b="Seed 2",
            runtime_status="FINAL",
            winner_team_id=team1.id,
            score_json={"display": "6-4 6-4"},
        ),
        Match(
            tournament_id=t.id,
            event_id=ev.id,
            schedule_version_id=v.id,
            match_code="MIX_E1_RR_POOLE_M01",
            match_type="RR",
            round_number=1,
            round_index=1,
            sequence_in_round=2,
            duration_minutes=60,
            team_a_id=team3.id,
            team_b_id=team4.id,
            placeholder_side_a="Seed 3",
            placeholder_side_b="Seed 4",
            runtime_status="FINAL",
            winner_team_id=team3.id,
            score_json={"display": "6-3 6-2"},
        ),
    ])
    session.commit()

    resp = client.get(f"/api/desk/tournaments/{t.id}/standings?version_id={v.id}")
    assert resp.status_code == 200, resp.text

    body = resp.json()
    division_names = [event["division_name"] for event in body["events"]]
    assert "Division I" in division_names
    assert "Division V" in division_names


# ── Pool Projection + Placement tests ────────────────────────────────────

def _setup_wf_pool_tournament(session: Session):
    """Create a tournament with WF_TO_POOLS_DYNAMIC (8 teams, 1 WF round, 2 pools of 4)."""
    import json

    t = Tournament(
        name="WF Pool Test",
        location="Test Beach",
        timezone="America/New_York",
        start_date=date(2026, 6, 5),
        end_date=date(2026, 6, 7),
    )
    session.add(t)
    session.flush()

    v = ScheduleVersion(
        tournament_id=t.id,
        version_number=1,
        status="final",
    )
    session.add(v)
    session.flush()

    ev = Event(
        tournament_id=t.id,
        category="mixed",
        name="Mixed A",
        team_count=8,
        draw_plan_json=json.dumps({"template_type": "WF_TO_POOLS_DYNAMIC", "wf_rounds": 1}),
    )
    session.add(ev)
    session.flush()

    # 8 teams
    teams = []
    for i in range(1, 9):
        t_obj = Team(event_id=ev.id, name=f"Team{i} - ST", seed=i, display_name=f"Team{i}")
        session.add(t_obj)
        teams.append(t_obj)
    session.flush()

    # 4 WF R1 matches: 1v5, 2v6, 3v7, 4v8 (half-split)
    wf_matches = []
    pairings = [(0, 4), (1, 5), (2, 6), (3, 7)]
    for idx, (a, b) in enumerate(pairings):
        m = Match(
            tournament_id=t.id,
            event_id=ev.id,
            schedule_version_id=v.id,
            match_code=f"MIX_E1_WF_R1_{idx+1:02d}",
            match_type="WF",
            round_number=1,
            round_index=1,
            sequence_in_round=idx + 1,
            duration_minutes=60,
            team_a_id=teams[a].id,
            team_b_id=teams[b].id,
            placeholder_side_a=f"Seed {a+1}",
            placeholder_side_b=f"Seed {b+1}",
        )
        session.add(m)
        wf_matches.append(m)
    session.flush()

    # 6 RR matches per pool (2 pools of 4, C(4,2)=6 each)
    # Pool A: SEED_1..4, Pool B: SEED_5..8
    rr_matches = []
    pool_pairings = [(1, 2), (3, 4), (1, 3), (2, 4), (1, 4), (2, 3)]
    for pool_idx in range(2):
        pool_label = chr(ord('A') + pool_idx)
        for rr_idx, (pa, pb) in enumerate(pool_pairings):
            seed_a = pool_idx * 4 + pa
            seed_b = pool_idx * 4 + pb
            m = Match(
                tournament_id=t.id,
                event_id=ev.id,
                schedule_version_id=v.id,
                match_code=f"MIX_E1_POOL{pool_label}_RR_{rr_idx+1:02d}",
                match_type="RR",
                round_number=1,
                round_index=1,
                sequence_in_round=rr_idx + 1,
                duration_minutes=120,
                team_a_id=None,
                team_b_id=None,
                placeholder_side_a=f"SEED_{seed_a}",
                placeholder_side_b=f"SEED_{seed_b}",
            )
            session.add(m)
            rr_matches.append(m)
    session.flush()

    # Create slots + assignments for WF matches
    for i, m in enumerate(wf_matches):
        slot = ScheduleSlot(
            tournament_id=t.id,
            schedule_version_id=v.id,
            day_date=date(2026, 6, 5),
            start_time=time(9 + i, 0),
            end_time=time(10 + i, 0),
            court_number=i + 1,
            court_label=str(i + 1),
            block_minutes=60,
        )
        session.add(slot)
        session.flush()
        session.add(MatchAssignment(schedule_version_id=v.id, match_id=m.id, slot_id=slot.id))

    t.public_schedule_version_id = v.id
    session.add(t)
    session.commit()

    return t, v, ev, teams, wf_matches, rr_matches


def test_pool_projection_no_wf_finalized(client, session):
    """All teams pending when no WF matches finalized."""
    t, v, ev, teams, wf_matches, rr_matches = _setup_wf_pool_tournament(session)

    resp = client.get(f"/api/desk/tournaments/{t.id}/pool-projection?version_id={v.id}")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["events"]) == 1

    proj = body["events"][0]
    assert proj["wf_complete"] is False
    assert proj["finalized_wf_matches"] == 0
    assert proj["total_wf_matches"] == 4

    # All teams should be pending
    all_teams_in_pools = []
    for pool in proj["pools"]:
        for team in pool["teams"]:
            all_teams_in_pools.append(team)
    assert all(t["status"] == "pending" for t in all_teams_in_pools)


def test_pool_projection_partial_wf(client, session):
    """Partial WF results show mix of projected and pending."""
    t, v, ev, teams, wf_matches, rr_matches = _setup_wf_pool_tournament(session)

    draft_resp = client.post(f"/api/desk/tournaments/{t.id}/working-draft")
    draft_id = draft_resp.json()["version_id"]

    snap = client.get(f"/api/desk/tournaments/{t.id}/snapshot?version_id={draft_id}").json()
    wf = [m for m in snap["matches"] if m["stage"] == "WF"]
    wf.sort(key=lambda m: m["match_id"])

    # Finalize only first 2 WF matches
    client.patch(
        f"/api/desk/tournaments/{t.id}/matches/{wf[0]['match_id']}/finalize",
        json={"version_id": draft_id, "score": "8-2", "winner_team_id": wf[0]["team1_id"]},
    )
    client.patch(
        f"/api/desk/tournaments/{t.id}/matches/{wf[1]['match_id']}/finalize",
        json={"version_id": draft_id, "score": "8-4", "winner_team_id": wf[1]["team1_id"]},
    )

    resp = client.get(f"/api/desk/tournaments/{t.id}/pool-projection?version_id={draft_id}")
    assert resp.status_code == 200
    proj = resp.json()["events"][0]
    assert proj["wf_complete"] is False
    assert proj["finalized_wf_matches"] == 2

    # Should have a mix of projected and pending
    statuses = set()
    for pool in proj["pools"]:
        for team in pool["teams"]:
            statuses.add(team["status"])
    assert "projected" in statuses or "pending" in statuses


def test_pool_projection_all_wf_complete(client, session):
    """All WF done returns confirmed with correct pool assignments."""
    t, v, ev, teams, wf_matches, rr_matches = _setup_wf_pool_tournament(session)

    draft_resp = client.post(f"/api/desk/tournaments/{t.id}/working-draft")
    draft_id = draft_resp.json()["version_id"]

    snap = client.get(f"/api/desk/tournaments/{t.id}/snapshot?version_id={draft_id}").json()
    wf = sorted([m for m in snap["matches"] if m["stage"] == "WF"], key=lambda m: m["match_id"])

    # Finalize all 4 WF matches (team1 = higher seed wins each)
    for m in wf:
        client.patch(
            f"/api/desk/tournaments/{t.id}/matches/{m['match_id']}/finalize",
            json={"version_id": draft_id, "score": "8-3", "winner_team_id": m["team1_id"]},
        )

    resp = client.get(f"/api/desk/tournaments/{t.id}/pool-projection?version_id={draft_id}")
    assert resp.status_code == 200
    proj = resp.json()["events"][0]
    assert proj["wf_complete"] is True
    assert proj["finalized_wf_matches"] == 4

    # All teams should be confirmed
    for pool in proj["pools"]:
        for team in pool["teams"]:
            assert team["status"] == "confirmed"
            assert "placement_reason" in team
            assert team["placement_reason"]
            assert isinstance(team["wf_wins"], int)
            assert isinstance(team["wf_losses"], int)
            assert isinstance(team["wf_game_diff"], int)

    # Winners (bucket W) should be in first pool, losers (bucket L) in second
    pool_a = proj["pools"][0]
    pool_b = proj["pools"][1]
    for team in pool_a["teams"]:
        assert team["bucket"] == "W"
        assert team["wf_wins"] == 1
    for team in pool_b["teams"]:
        assert team["bucket"] == "L"
        assert team["wf_wins"] == 0


def test_pool_placement_rejects_incomplete_wf(client, session):
    """Placement fails if WF is not complete."""
    t, v, ev, teams, wf_matches, rr_matches = _setup_wf_pool_tournament(session)

    draft_resp = client.post(f"/api/desk/tournaments/{t.id}/working-draft")
    draft_id = draft_resp.json()["version_id"]

    resp = client.post(
        f"/api/desk/tournaments/{t.id}/pool-placement",
        json={
            "version_id": draft_id,
            "event_id": ev.id,
            "pools": [
                {"pool_label": "POOLA", "team_ids": [teams[0].id, teams[1].id, teams[2].id, teams[3].id]},
                {"pool_label": "POOLB", "team_ids": [teams[4].id, teams[5].id, teams[6].id, teams[7].id]},
            ],
        },
    )
    assert resp.status_code == 400
    assert "WF not complete" in resp.json()["detail"]


def test_pool_placement_resolves_seeds(client, session):
    """After all WF complete, placement resolves SEED_N on RR matches."""
    t, v, ev, teams, wf_matches, rr_matches = _setup_wf_pool_tournament(session)

    draft_resp = client.post(f"/api/desk/tournaments/{t.id}/working-draft")
    draft_id = draft_resp.json()["version_id"]

    snap = client.get(f"/api/desk/tournaments/{t.id}/snapshot?version_id={draft_id}").json()
    wf = sorted([m for m in snap["matches"] if m["stage"] == "WF"], key=lambda m: m["match_id"])

    # Finalize all WF: higher seed wins
    for m in wf:
        client.patch(
            f"/api/desk/tournaments/{t.id}/matches/{m['match_id']}/finalize",
            json={"version_id": draft_id, "score": "8-3", "winner_team_id": m["team1_id"]},
        )

    # Get projection to know pool assignments
    proj_resp = client.get(f"/api/desk/tournaments/{t.id}/pool-projection?version_id={draft_id}")
    proj = proj_resp.json()["events"][0]

    # Build placement payload from projection
    placement_pools = []
    for pool in proj["pools"]:
        placement_pools.append({
            "pool_label": pool["pool_label"],
            "team_ids": [t["team_id"] for t in pool["teams"]],
        })

    resp = client.post(
        f"/api/desk/tournaments/{t.id}/pool-placement",
        json={
            "version_id": draft_id,
            "event_id": ev.id,
            "pools": placement_pools,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["updated_matches"] > 0

    # Verify RR matches now have team assignments
    rr_in_snap = client.get(f"/api/desk/tournaments/{t.id}/snapshot?version_id={draft_id}").json()
    rr_matches_after = [m for m in rr_in_snap["matches"] if m["stage"] == "RR"]
    for m in rr_matches_after:
        assert m["team1_id"] is not None, f"RR match {m['match_code']} team1_id still null"
        assert m["team2_id"] is not None, f"RR match {m['match_code']} team2_id still null"


def test_pool_placement_sends_rr_first_match_sms(client, session):
    """Confirming pool placement sends each team's first RR match details."""
    t, v, ev, teams, wf_matches, rr_matches = _setup_wf_pool_tournament(session)

    for idx, team in enumerate(teams, start=1):
        team.player1_cellphone = f"9015552{idx:03d}"
        team.player2_cellphone = None
        team.p1_cell = None
        team.p2_cell = None
        session.add(team)

    session.add(
        TournamentSmsSettings(
            tournament_id=t.id,
            auto_first_match=True,
            auto_post_match_next=False,
            auto_on_deck=False,
            auto_up_next=False,
            auto_court_change=False,
            test_mode=False,
        )
    )
    session.commit()

    draft_resp = client.post(f"/api/desk/tournaments/{t.id}/working-draft")
    draft_id = draft_resp.json()["version_id"]

    snap = client.get(f"/api/desk/tournaments/{t.id}/snapshot?version_id={draft_id}").json()
    wf = sorted([m for m in snap["matches"] if m["stage"] == "WF"], key=lambda m: m["match_id"])
    rr_first_round = sorted(
        [
            m for m in snap["matches"]
            if m["stage"] == "RR"
            and (
                m["match_code"].endswith("_RR_01")
                or m["match_code"].endswith("_RR_02")
            )
        ],
        key=lambda m: m["match_code"],
    )
    assert len(rr_first_round) == 4

    # Give first-round RR matches scheduled slots so message can include day/time/court.
    for i, rr in enumerate(rr_first_round):
        slot = ScheduleSlot(
            tournament_id=t.id,
            schedule_version_id=draft_id,
            day_date=date(2026, 6, 6),
            start_time=time(12 + i, 0),
            end_time=time(13 + i, 0),
            court_number=(i % 2) + 1,
            court_label=str((i % 2) + 1),
            block_minutes=60,
        )
        session.add(slot)
        session.flush()
        session.add(
            MatchAssignment(
                schedule_version_id=draft_id,
                match_id=rr["match_id"],
                slot_id=slot.id,
            )
        )
    session.commit()

    # Finalize all WF matches so pool placement is allowed.
    for m in wf:
        client.patch(
            f"/api/desk/tournaments/{t.id}/matches/{m['match_id']}/finalize",
            json={"version_id": draft_id, "score": "8-3", "winner_team_id": m["team1_id"]},
        )

    proj_resp = client.get(f"/api/desk/tournaments/{t.id}/pool-projection?version_id={draft_id}")
    proj = proj_resp.json()["events"][0]
    placement_pools = [
        {"pool_label": pool["pool_label"], "team_ids": [row["team_id"] for row in pool["teams"]]}
        for pool in proj["pools"]
    ]

    place = client.post(
        f"/api/desk/tournaments/{t.id}/pool-placement",
        json={
            "version_id": draft_id,
            "event_id": ev.id,
            "pools": placement_pools,
        },
    )
    assert place.status_code == 200

    rr_logs = session.exec(
        select(SmsLog).where(
            SmsLog.tournament_id == t.id,
            SmsLog.trigger == "auto",
            SmsLog.message_type == "rr_first_match",
        )
    ).all()
    # 8 teams, one phone each => 8 sends
    assert len(rr_logs) == 8
    assert all("Round Robin" in (row.message_body or "") for row in rr_logs)
    assert all("Court" in (row.message_body or "") for row in rr_logs)


# ── Move / Swap / Add Slot / Add Court tests ─────────────────────────────

def _setup_draft_for_move(session: Session):
    """Create a draft version with 2 courts, 2 time slots, and 2 matches."""
    t = Tournament(
        name="Move Test",
        location="Beach",
        timezone="America/New_York",
        start_date=date(2026, 7, 1),
        end_date=date(2026, 7, 2),
        court_names=["1", "2"],
    )
    session.add(t)
    session.flush()

    v = ScheduleVersion(
        tournament_id=t.id,
        version_number=1,
        status="draft",
        notes="Desk Draft",
    )
    session.add(v)
    session.flush()

    ev = Event(
        tournament_id=t.id,
        category="mixed",
        name="Mixed A",
        team_count=4,
    )
    session.add(ev)
    session.flush()

    teams = []
    for i, name in enumerate(["Alpha", "Bravo", "Charlie", "Delta"], start=1):
        t_ = Team(event_id=ev.id, name=name, seed=i, display_name=name)
        session.add(t_)
        session.flush()
        teams.append(t_)

    m1 = Match(
        tournament_id=t.id, event_id=ev.id, schedule_version_id=v.id,
        match_code="MIX_WF_R1_M01", match_type="WF",
        round_number=1, round_index=1, sequence_in_round=1, duration_minutes=60,
        team_a_id=teams[0].id, team_b_id=teams[3].id,
        placeholder_side_a="SEED_1", placeholder_side_b="SEED_4",
    )
    m2 = Match(
        tournament_id=t.id, event_id=ev.id, schedule_version_id=v.id,
        match_code="MIX_WF_R1_M02", match_type="WF",
        round_number=1, round_index=1, sequence_in_round=2, duration_minutes=60,
        team_a_id=teams[1].id, team_b_id=teams[2].id,
        placeholder_side_a="SEED_2", placeholder_side_b="SEED_3",
    )
    session.add_all([m1, m2])
    session.flush()

    # 2 courts x 2 time slots = 4 slots total
    slot_c1_t1 = ScheduleSlot(
        tournament_id=t.id, schedule_version_id=v.id,
        day_date=date(2026, 7, 1), start_time=time(9, 0), end_time=time(10, 0),
        court_number=1, court_label="1", block_minutes=60,
    )
    slot_c2_t1 = ScheduleSlot(
        tournament_id=t.id, schedule_version_id=v.id,
        day_date=date(2026, 7, 1), start_time=time(9, 0), end_time=time(10, 0),
        court_number=2, court_label="2", block_minutes=60,
    )
    slot_c1_t2 = ScheduleSlot(
        tournament_id=t.id, schedule_version_id=v.id,
        day_date=date(2026, 7, 1), start_time=time(10, 30), end_time=time(11, 30),
        court_number=1, court_label="1", block_minutes=60,
    )
    slot_c2_t2 = ScheduleSlot(
        tournament_id=t.id, schedule_version_id=v.id,
        day_date=date(2026, 7, 1), start_time=time(10, 30), end_time=time(11, 30),
        court_number=2, court_label="2", block_minutes=60,
    )
    session.add_all([slot_c1_t1, slot_c2_t1, slot_c1_t2, slot_c2_t2])
    session.flush()

    a1 = MatchAssignment(schedule_version_id=v.id, match_id=m1.id, slot_id=slot_c1_t1.id)
    a2 = MatchAssignment(schedule_version_id=v.id, match_id=m2.id, slot_id=slot_c2_t1.id)
    session.add_all([a1, a2])
    session.commit()

    return t, v, ev, teams, [m1, m2], [slot_c1_t1, slot_c2_t1, slot_c1_t2, slot_c2_t2]


def _add_two_players_for_team(session: Session, tournament_id: int, team_id: int, prefix: str) -> List[Player]:
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
    session.commit()
    return [p1, p2]


def test_management_mode_toggle_defaults_and_persists(client, session):
    t, v, _ev, _teams, _matches, _slots = _setup_draft_for_move(session)

    mode_resp = client.get(f"/api/desk/tournaments/{t.id}/management-mode", params={"version_id": v.id})
    assert mode_resp.status_code == 200
    assert mode_resp.json()["management_mode"] == "court_management"

    set_resp = client.patch(
        f"/api/desk/tournaments/{t.id}/management-mode",
        json={"version_id": v.id, "management_mode": "checkin_management"},
    )
    assert set_resp.status_code == 200
    assert set_resp.json()["management_mode"] == "checkin_management"

    snap = client.get(f"/api/desk/tournaments/{t.id}/snapshot", params={"version_id": v.id}).json()
    assert snap["management_mode"] == "checkin_management"


def test_checkin_queue_inclusion_and_team_ready_flow(client, session):
    t, v, _ev, teams, matches, _slots = _setup_draft_for_move(session)
    m1 = matches[0]

    _add_two_players_for_team(session, t.id, teams[0].id, "Alpha")
    _add_two_players_for_team(session, t.id, teams[3].id, "Delta")

    mode_resp = client.patch(
        f"/api/desk/tournaments/{t.id}/management-mode",
        json={"version_id": v.id, "management_mode": "checkin_management"},
    )
    assert mode_resp.status_code == 200

    queue0 = client.get(f"/api/desk/tournaments/{t.id}/checkin/queue", params={"version_id": v.id})
    assert queue0.status_code == 200
    body0 = queue0.json()
    assert len(body0["checkin_matches"]) >= 1
    assert len(body0["ready_queue"]) == 0

    a_resp = client.patch(
        f"/api/desk/tournaments/{t.id}/matches/{m1.id}/checkin/team",
        json={"version_id": v.id, "side": "A", "checked_in": True},
    )
    assert a_resp.status_code == 200
    assert len(a_resp.json()["ready_queue"]) == 0

    b_resp = client.patch(
        f"/api/desk/tournaments/{t.id}/matches/{m1.id}/checkin/team",
        json={"version_id": v.id, "side": "B", "checked_in": True},
    )
    assert b_resp.status_code == 200
    ready_ids = {r["match_id"] for r in b_resp.json()["ready_queue"]}
    assert m1.id in ready_ids


def test_snapshot_checkin_slot_contract_includes_options_and_rows(client, session):
    t, v, _ev, _teams, matches, _slots = _setup_draft_for_move(session)
    m2 = matches[1]
    m2.team_b_id = None
    session.add(m2)
    session.commit()

    mode_resp = client.patch(
        f"/api/desk/tournaments/{t.id}/management-mode",
        json={"version_id": v.id, "management_mode": "checkin_management"},
    )
    assert mode_resp.status_code == 200

    snap = client.get(f"/api/desk/tournaments/{t.id}/snapshot", params={"version_id": v.id})
    assert snap.status_code == 200
    body = snap.json()

    options = body["checkin_slot_options"]
    labels = {o["label"] for o in options}
    assert "2026-07-01 9:00 AM" in labels
    assert "2026-07-01 10:30 AM" in labels

    nine_key = next(o["slot_key"] for o in options if o["label"] == "2026-07-01 9:00 AM")
    ten_thirty_key = next(o["slot_key"] for o in options if o["label"] == "2026-07-01 10:30 AM")

    nine_rows = body["checkin_slot_rows"][nine_key]
    assert len(nine_rows) == 2
    m2_row = next(r for r in nine_rows if r["match_id"] == m2.id)
    assert m2_row["checkin_enabled"] is False

    assert body["checkin_slot_rows"][ten_thirty_key] == []


def test_snapshot_checkin_slot_options_present_even_without_candidates(client, session):
    t, v, _ev, _teams, matches, _slots = _setup_draft_for_move(session)
    for m in matches:
        m.runtime_status = "FINAL"
        session.add(m)
    session.commit()

    mode_resp = client.patch(
        f"/api/desk/tournaments/{t.id}/management-mode",
        json={"version_id": v.id, "management_mode": "checkin_management"},
    )
    assert mode_resp.status_code == 200

    snap = client.get(f"/api/desk/tournaments/{t.id}/snapshot", params={"version_id": v.id})
    assert snap.status_code == 200
    body = snap.json()

    labels = {o["label"] for o in body["checkin_slot_options"]}
    assert "2026-07-01 9:00 AM" in labels
    assert "2026-07-01 10:30 AM" in labels
    assert len(body["checkin_matches"]) == 0
    assert all(len(rows) == 0 for rows in body["checkin_slot_rows"].values())


def test_checkin_player_rollup_and_assign_ready_match(client, session):
    t, v, _ev, teams, matches, _slots = _setup_draft_for_move(session)
    m1 = matches[0]

    alpha_players = _add_two_players_for_team(session, t.id, teams[0].id, "Alpha")
    delta_players = _add_two_players_for_team(session, t.id, teams[3].id, "Delta")

    mode_resp = client.patch(
        f"/api/desk/tournaments/{t.id}/management-mode",
        json={"version_id": v.id, "management_mode": "checkin_management"},
    )
    assert mode_resp.status_code == 200

    # Side A player check-in: not ready until both players are checked in
    p1a = client.patch(
        f"/api/desk/tournaments/{t.id}/matches/{m1.id}/checkin/player",
        json={"version_id": v.id, "side": "A", "player_id": alpha_players[0].id, "checked_in": True},
    )
    assert p1a.status_code == 200
    match_state = [m for m in p1a.json()["checkin_matches"] if m["match_id"] == m1.id][0]
    assert match_state["side_a"]["side_ready"] is False

    p2a = client.patch(
        f"/api/desk/tournaments/{t.id}/matches/{m1.id}/checkin/player",
        json={"version_id": v.id, "side": "A", "player_id": alpha_players[1].id, "checked_in": True},
    )
    assert p2a.status_code == 200
    match_state = [m for m in p2a.json()["checkin_matches"] if m["match_id"] == m1.id][0]
    assert match_state["side_a"]["side_ready"] is True

    # Complete side B as well to make match ready
    client.patch(
        f"/api/desk/tournaments/{t.id}/matches/{m1.id}/checkin/player",
        json={"version_id": v.id, "side": "B", "player_id": delta_players[0].id, "checked_in": True},
    )
    p2b = client.patch(
        f"/api/desk/tournaments/{t.id}/matches/{m1.id}/checkin/player",
        json={"version_id": v.id, "side": "B", "player_id": delta_players[1].id, "checked_in": True},
    )
    assert p2b.status_code == 200
    queue_body = p2b.json()
    ready_ids = {r["match_id"] for r in queue_body["ready_queue"]}
    assert m1.id in ready_ids
    assert len(queue_body["available_slots"]) >= 1

    target_slot_id = queue_body["available_slots"][0]["slot_id"]
    assign = client.post(
        f"/api/desk/tournaments/{t.id}/checkin/assign",
        json={"version_id": v.id, "match_id": m1.id, "slot_id": target_slot_id},
    )
    assert assign.status_code == 200
    snap = assign.json()
    moved = [m for m in snap["matches"] if m["match_id"] == m1.id][0]
    assert moved["assignment_id"] is not None
    assert moved["court_name"] is not None
    assert moved["status"] == "IN_PROGRESS"
    assert all(cm["match_id"] != m1.id for cm in snap["checkin_matches"])


def test_checkin_assign_accepts_noncanonical_slot_id_for_available_court(client, session):
    """Assign should accept a different slot id on the same available court."""
    t, v, _ev, teams, matches, slots = _setup_draft_for_move(session)
    m1 = matches[0]

    alpha_players = _add_two_players_for_team(session, t.id, teams[0].id, "Alpha")
    delta_players = _add_two_players_for_team(session, t.id, teams[3].id, "Delta")

    mode_resp = client.patch(
        f"/api/desk/tournaments/{t.id}/management-mode",
        json={"version_id": v.id, "management_mode": "checkin_management"},
    )
    assert mode_resp.status_code == 200

    # Make match ready.
    client.patch(
        f"/api/desk/tournaments/{t.id}/matches/{m1.id}/checkin/player",
        json={"version_id": v.id, "side": "A", "player_id": alpha_players[0].id, "checked_in": True},
    )
    client.patch(
        f"/api/desk/tournaments/{t.id}/matches/{m1.id}/checkin/player",
        json={"version_id": v.id, "side": "A", "player_id": alpha_players[1].id, "checked_in": True},
    )
    client.patch(
        f"/api/desk/tournaments/{t.id}/matches/{m1.id}/checkin/player",
        json={"version_id": v.id, "side": "B", "player_id": delta_players[0].id, "checked_in": True},
    )
    ready_resp = client.patch(
        f"/api/desk/tournaments/{t.id}/matches/{m1.id}/checkin/player",
        json={"version_id": v.id, "side": "B", "player_id": delta_players[1].id, "checked_in": True},
    )
    assert ready_resp.status_code == 200

    # Use Court 2's currently occupied slot; assign should still succeed.
    slot_c2_t1_occupied = slots[1]
    assign = client.post(
        f"/api/desk/tournaments/{t.id}/checkin/assign",
        json={"version_id": v.id, "match_id": m1.id, "slot_id": slot_c2_t1_occupied.id},
    )
    assert assign.status_code == 200
    snap = assign.json()
    moved = [m for m in snap["matches"] if m["match_id"] == m1.id][0]
    assert moved["court_name"] == "Court 2"
    assert moved["status"] == "IN_PROGRESS"


def test_temporary_player_lookup_import_enriches_checkin_snapshot(client, session):
    t, v, _ev, teams, matches, _slots = _setup_draft_for_move(session)
    m1 = matches[0]

    alpha_players = _add_two_players_for_team(session, t.id, teams[0].id, "Alpha")
    _add_two_players_for_team(session, t.id, teams[3].id, "Delta")

    mode_resp = client.patch(
        f"/api/desk/tournaments/{t.id}/management-mode",
        json={"version_id": v.id, "management_mode": "checkin_management"},
    )
    assert mode_resp.status_code == 200

    import_resp = client.post(
        f"/api/desk/tournaments/{t.id}/temporary-player-lookups/import",
        json={
            "raw_text": (
                "Player Name\tTowel Color\tReport URL\n"
                "Alpha Player 1\tBlue\thttps://example.com/reports/alpha-1\n"
                "Unknown Player\tGreen\t\n"
            )
        },
    )
    assert import_resp.status_code == 200
    imported = import_resp.json()
    assert imported["imported_count"] == 2
    assert imported["matched_count"] == 1

    list_resp = client.get(f"/api/desk/tournaments/{t.id}/temporary-player-lookups")
    assert list_resp.status_code == 200
    assert len(list_resp.json()["items"]) == 2

    snap = client.get(f"/api/desk/tournaments/{t.id}/snapshot", params={"version_id": v.id})
    assert snap.status_code == 200
    match_state = next(m for m in snap.json()["checkin_matches"] if m["match_id"] == m1.id)
    player_state = next(p for p in match_state["side_a"]["players"] if p["player_id"] == alpha_players[0].id)
    assert player_state["towel_color"] == "Blue"
    assert player_state["report_url"] == "https://example.com/reports/alpha-1"


def test_temporary_player_lookup_crud_updates_checkin_snapshot(client, session):
    t, v, _ev, teams, matches, _slots = _setup_draft_for_move(session)
    m1 = matches[0]
    alpha_players = _add_two_players_for_team(session, t.id, teams[0].id, "Alpha")

    mode_resp = client.patch(
        f"/api/desk/tournaments/{t.id}/management-mode",
        json={"version_id": v.id, "management_mode": "checkin_management"},
    )
    assert mode_resp.status_code == 200

    create_resp = client.post(
        f"/api/desk/tournaments/{t.id}/temporary-player-lookups",
        json={
            "source_name": "Alpha Player 1",
            "towel_color": "Blue",
            "report_url": "https://example.com/reports/alpha-1",
        },
    )
    assert create_resp.status_code == 200
    created = create_resp.json()
    assert created["matched"] is True
    assert created["towel_color"] == "Blue"

    snap = client.get(f"/api/desk/tournaments/{t.id}/snapshot", params={"version_id": v.id})
    assert snap.status_code == 200
    match_state = next(m for m in snap.json()["checkin_matches"] if m["match_id"] == m1.id)
    player_state = next(p for p in match_state["side_a"]["players"] if p["player_id"] == alpha_players[0].id)
    assert player_state["towel_color"] == "Blue"

    update_resp = client.patch(
        f"/api/desk/tournaments/{t.id}/temporary-player-lookups/{created['id']}",
        json={
            "source_name": "Alpha Player 1",
            "towel_color": "Red",
            "report_url": "",
        },
    )
    assert update_resp.status_code == 200
    updated = update_resp.json()
    assert updated["matched"] is True
    assert updated["towel_color"] == "Red"
    assert updated["report_url"] is None

    snap = client.get(f"/api/desk/tournaments/{t.id}/snapshot", params={"version_id": v.id})
    assert snap.status_code == 200
    match_state = next(m for m in snap.json()["checkin_matches"] if m["match_id"] == m1.id)
    player_state = next(p for p in match_state["side_a"]["players"] if p["player_id"] == alpha_players[0].id)
    assert player_state["towel_color"] == "Red"
    assert player_state["report_url"] is None

    delete_resp = client.delete(
        f"/api/desk/tournaments/{t.id}/temporary-player-lookups/{created['id']}"
    )
    assert delete_resp.status_code == 200

    list_resp = client.get(f"/api/desk/tournaments/{t.id}/temporary-player-lookups")
    assert list_resp.status_code == 200
    assert list_resp.json()["items"] == []

    snap = client.get(f"/api/desk/tournaments/{t.id}/snapshot", params={"version_id": v.id})
    assert snap.status_code == 200
    match_state = next(m for m in snap.json()["checkin_matches"] if m["match_id"] == m1.id)
    player_state = next(p for p in match_state["side_a"]["players"] if p["player_id"] == alpha_players[0].id)
    assert player_state["towel_color"] is None
    assert player_state["report_url"] is None


def test_temporary_player_lookup_matches_team_roster_names_without_player_rows(client, session):
    t, v, ev, teams, matches, _slots = _setup_draft_for_move(session)
    teams[0].name = "Venitta Reeves / Partner One"
    teams[0].display_name = "Venitta Reeves / Partner One"
    teams[3].name = "Wayne Steed / Wladimir E Chacon"
    teams[3].display_name = "Wayne Steed / Wladimir E Chacon"
    session.add(teams[0])
    session.add(teams[3])
    session.commit()

    mode_resp = client.patch(
        f"/api/desk/tournaments/{t.id}/management-mode",
        json={"version_id": v.id, "management_mode": "checkin_management"},
    )
    assert mode_resp.status_code == 200

    import_resp = client.post(
        f"/api/desk/tournaments/{t.id}/temporary-player-lookups/import",
        json={
            "raw_text": (
                "Player Name\tTowel Color\tReport URL\n"
                "Venitta Reeves\tBlack\thttps://example.com/reports/venitta\n"
                "Wayne Steed\tRoyal\thttps://example.com/reports/wayne\n"
                "Wladimir E Chacon\tLime\t\n"
            )
        },
    )
    assert import_resp.status_code == 200
    imported = import_resp.json()
    assert imported["imported_count"] == 3
    assert imported["matched_count"] == 3
    assert all(item["matched"] is True for item in imported["items"])

    snap = client.get(f"/api/desk/tournaments/{t.id}/snapshot", params={"version_id": v.id})
    assert snap.status_code == 200
    match_state = next(m for m in snap.json()["checkin_matches"] if m["match_id"] == matches[0].id)

    side_a_players = match_state["side_a"]["players"]
    assert side_a_players[0]["player_display"] == "Venitta Reeves"
    assert side_a_players[0]["towel_color"] == "Black"
    assert side_a_players[0]["report_url"] == "https://example.com/reports/venitta"

    side_b_players = match_state["side_b"]["players"]
    assert side_b_players[0]["player_display"] == "Wayne Steed"
    assert side_b_players[0]["towel_color"] == "Royal"
    assert side_b_players[1]["player_display"] == "Wladimir E Chacon"
    assert side_b_players[1]["towel_color"] == "Lime"


def test_temporary_player_lookup_matches_last_first_roster_names(client, session):
    t, v, ev, teams, matches, _slots = _setup_draft_for_move(session)
    teams[0].name = "Reeves, Venitta / Partner, Sample"
    teams[0].display_name = "Reeves / Partner"
    teams[3].name = "Steed, Wayne / Chacon, Wladimir E"
    teams[3].display_name = "Steed / Chacon"
    session.add(teams[0])
    session.add(teams[3])
    session.commit()

    mode_resp = client.patch(
        f"/api/desk/tournaments/{t.id}/management-mode",
        json={"version_id": v.id, "management_mode": "checkin_management"},
    )
    assert mode_resp.status_code == 200

    import_resp = client.post(
        f"/api/desk/tournaments/{t.id}/temporary-player-lookups/import",
        json={
            "raw_text": (
                "Player Name\tTowel Color\tReport URL\n"
                "Venitta Reeves\tBlack\thttps://example.com/reports/venitta\n"
                "Wayne Steed\tRoyal\thttps://example.com/reports/wayne\n"
                "Wladimir E Chacon\tLime\t\n"
            )
        },
    )
    assert import_resp.status_code == 200
    imported = import_resp.json()
    assert imported["matched_count"] == 3
    assert all(item["matched"] is True for item in imported["items"])

    lookup_list = client.get(f"/api/desk/tournaments/{t.id}/temporary-player-lookups")
    assert lookup_list.status_code == 200
    assert all(item["matched"] is True for item in lookup_list.json()["items"])

    snap = client.get(f"/api/desk/tournaments/{t.id}/snapshot", params={"version_id": v.id})
    assert snap.status_code == 200
    match_state = next(m for m in snap.json()["checkin_matches"] if m["match_id"] == matches[0].id)

    side_a_players = match_state["side_a"]["players"]
    assert side_a_players[0]["player_display"] == "Reeves, Venitta"
    assert side_a_players[0]["towel_color"] == "Black"

    side_b_players = match_state["side_b"]["players"]
    assert side_b_players[0]["player_display"] == "Steed, Wayne"
    assert side_b_players[0]["towel_color"] == "Royal"
    assert side_b_players[1]["player_display"] == "Chacon, Wladimir E"
    assert side_b_players[1]["towel_color"] == "Lime"


def test_temporary_player_lookup_matches_roster_names_with_location_suffixes(client, session):
    t, v, ev, teams, matches, _slots = _setup_draft_for_move(session)
    teams[0].name = "Venitta Reeves, Beaufort, SC / Partner One, City, ST"
    teams[0].display_name = "Venitta / Partner"
    teams[3].name = "Wayne Steed, Beaufort, SC / Wladimir E Chacon, Miami, FL"
    teams[3].display_name = "Wayne / Wladimir"
    session.add(teams[0])
    session.add(teams[3])
    session.commit()

    mode_resp = client.patch(
        f"/api/desk/tournaments/{t.id}/management-mode",
        json={"version_id": v.id, "management_mode": "checkin_management"},
    )
    assert mode_resp.status_code == 200

    import_resp = client.post(
        f"/api/desk/tournaments/{t.id}/temporary-player-lookups/import",
        json={
            "raw_text": (
                "Player Name\tTowel Color\tReport URL\n"
                "Venitta Reeves\tBlack\thttps://example.com/reports/venitta\n"
                "Wayne Steed\tRoyal\thttps://example.com/reports/wayne\n"
                "Wladimir E Chacon\tLime\t\n"
            )
        },
    )
    assert import_resp.status_code == 200
    imported = import_resp.json()
    assert imported["matched_count"] == 3
    assert all(item["matched"] is True for item in imported["items"])

    snap = client.get(f"/api/desk/tournaments/{t.id}/snapshot", params={"version_id": v.id})
    assert snap.status_code == 200
    match_state = next(m for m in snap.json()["checkin_matches"] if m["match_id"] == matches[0].id)

    side_a_players = match_state["side_a"]["players"]
    assert side_a_players[0]["player_display"] == "Venitta Reeves, Beaufort, SC"
    assert side_a_players[0]["towel_color"] == "Black"

    side_b_players = match_state["side_b"]["players"]
    assert side_b_players[0]["player_display"] == "Wayne Steed, Beaufort, SC"
    assert side_b_players[0]["towel_color"] == "Royal"
    assert side_b_players[1]["player_display"] == "Wladimir E Chacon, Miami, FL"
    assert side_b_players[1]["towel_color"] == "Lime"


def test_temporary_player_lookup_enriches_linked_players_by_name_fallback(client, session):
    t, v, _ev, teams, matches, _slots = _setup_draft_for_move(session)
    alpha_p1 = Player(tournament_id=t.id, full_name="Mayada Innenberg", display_name="Mayada")
    alpha_p2 = Player(tournament_id=t.id, full_name="Lisa Sample", display_name="Lisa")
    delta_p1 = Player(tournament_id=t.id, full_name="Kristin Rosenbaum", display_name="Kristin")
    delta_p2 = Player(tournament_id=t.id, full_name="Jennifer Sample", display_name="Jennifer")
    session.add_all([alpha_p1, alpha_p2, delta_p1, delta_p2])
    session.flush()
    session.add_all(
        [
            TeamPlayer(team_id=teams[0].id, player_id=alpha_p1.id, lineup_slot=1),
            TeamPlayer(team_id=teams[0].id, player_id=alpha_p2.id, lineup_slot=2),
            TeamPlayer(team_id=teams[3].id, player_id=delta_p1.id, lineup_slot=1),
            TeamPlayer(team_id=teams[3].id, player_id=delta_p2.id, lineup_slot=2),
        ]
    )
    session.commit()

    mode_resp = client.patch(
        f"/api/desk/tournaments/{t.id}/management-mode",
        json={"version_id": v.id, "management_mode": "checkin_management"},
    )
    assert mode_resp.status_code == 200

    import_resp = client.post(
        f"/api/desk/tournaments/{t.id}/temporary-player-lookups/import",
        json={
            "raw_text": (
                "Player Name\tTowel Color\tReport URL\n"
                "Mayada Innenberg\tLime\t\n"
                "Kristin Rosenbaum\tPurple\thttps://example.com/reports/kristin\n"
            )
        },
    )
    assert import_resp.status_code == 200
    assert import_resp.json()["matched_count"] == 2

    snap = client.get(f"/api/desk/tournaments/{t.id}/snapshot", params={"version_id": v.id})
    assert snap.status_code == 200
    match_state = next(m for m in snap.json()["checkin_matches"] if m["match_id"] == matches[0].id)

    side_a_player = next(p for p in match_state["side_a"]["players"] if p["player_display"] == "Mayada")
    assert side_a_player["towel_color"] == "Lime"

    side_b_player = next(p for p in match_state["side_b"]["players"] if p["player_display"] == "Kristin")
    assert side_b_player["towel_color"] == "Purple"
    assert side_b_player["report_url"] == "https://example.com/reports/kristin"


def test_temporary_player_lookup_uses_lineup_slot_to_match_visible_short_names(client, session):
    t, v, _ev, teams, matches, _slots = _setup_draft_for_move(session)
    teams[0].display_name = "Mayada / Kristin"
    teams[0].name = "Mayada Innenberg / Kristin Rosenbaum"
    session.add(teams[0])
    session.commit()

    p1 = Player(tournament_id=t.id, full_name="Mayada Innenberg", display_name="Mayada")
    p2 = Player(tournament_id=t.id, full_name="Kristin Rosenbaum", display_name="Kristin")
    session.add_all([p1, p2])
    session.flush()
    session.add_all(
        [
            TeamPlayer(team_id=teams[0].id, player_id=p2.id, lineup_slot=2),
            TeamPlayer(team_id=teams[0].id, player_id=p1.id, lineup_slot=1),
        ]
    )
    session.commit()

    mode_resp = client.patch(
        f"/api/desk/tournaments/{t.id}/management-mode",
        json={"version_id": v.id, "management_mode": "checkin_management"},
    )
    assert mode_resp.status_code == 200

    import_resp = client.post(
        f"/api/desk/tournaments/{t.id}/temporary-player-lookups/import",
        json={
            "raw_text": (
                "Player Name\tTowel Color\tReport URL\n"
                "Mayada Innenberg\tLime\t\n"
                "Kristin Rosenbaum\tPurple\thttps://example.com/reports/kristin\n"
            )
        },
    )
    assert import_resp.status_code == 200

    snap = client.get(f"/api/desk/tournaments/{t.id}/snapshot", params={"version_id": v.id})
    assert snap.status_code == 200
    match_state = next(m for m in snap.json()["checkin_matches"] if m["match_id"] == matches[0].id)

    side_a_players = match_state["side_a"]["players"]
    assert side_a_players[0]["player_display"] == "Mayada"
    assert side_a_players[0]["towel_color"] == "Lime"
    assert side_a_players[1]["player_display"] == "Kristin"
    assert side_a_players[1]["towel_color"] == "Purple"


def test_checkin_snapshot_prefers_short_names_from_team_name_over_stale_display_name(client, session):
    t, v, _ev, teams, matches, _slots = _setup_draft_for_move(session)
    teams[0].name = "Jon Miller, Ocala, FL / Lisa Steed, Ocala, FL"
    teams[0].display_name = "venitta / Ed"
    teams[3].name = "Eric Tatum, Marietta, GA / Leana Tatum, Marietta, GA"
    teams[3].display_name = "Eric / Leana"
    session.add(teams[0])
    session.add(teams[3])
    session.commit()

    mode_resp = client.patch(
        f"/api/desk/tournaments/{t.id}/management-mode",
        json={"version_id": v.id, "management_mode": "checkin_management"},
    )
    assert mode_resp.status_code == 200

    snap = client.get(f"/api/desk/tournaments/{t.id}/snapshot", params={"version_id": v.id})
    assert snap.status_code == 200
    match_state = next(m for m in snap.json()["checkin_matches"] if m["match_id"] == matches[0].id)

    assert match_state["side_a"]["team_display"] == "Jon / Lisa"
    assert match_state["side_b"]["team_display"] == "Eric / Leana"

def test_move_match_to_empty_slot(client, session):
    """Moving a match to an empty slot succeeds."""
    t, v, ev, teams, matches, slots = _setup_draft_for_move(session)
    m1 = matches[0]
    empty_slot = slots[2]  # slot_c1_t2 (empty)

    resp = client.patch(
        f"/api/desk/tournaments/{t.id}/matches/{m1.id}/move",
        json={"version_id": v.id, "target_slot_id": empty_slot.id},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["match"]["match_id"] == m1.id


def test_move_match_to_occupied_slot_returns_409(client, session):
    """Moving a match to a slot occupied by another match returns 409."""
    t, v, ev, teams, matches, slots = _setup_draft_for_move(session)
    m1 = matches[0]
    occupied_slot = slots[1]  # slot_c2_t1 holds m2

    resp = client.patch(
        f"/api/desk/tournaments/{t.id}/matches/{m1.id}/move",
        json={"version_id": v.id, "target_slot_id": occupied_slot.id},
    )
    assert resp.status_code == 409
    detail = resp.json()["detail"]
    assert detail["occupant_match_id"] == matches[1].id


def test_move_rejected_on_final_version(client, session):
    """Move is rejected on a FINAL version."""
    t, v, ev, teams, matches = _setup_tournament_with_matches(session)
    m1 = matches[0]

    resp = client.patch(
        f"/api/desk/tournaments/{t.id}/matches/{m1.id}/move",
        json={"version_id": v.id, "target_slot_id": 999},
    )
    assert resp.status_code == 400
    assert "DRAFT" in resp.json()["detail"]


def test_swap_two_matches(client, session):
    """Swapping two matches exchanges their slot assignments."""
    t, v, ev, teams, matches, slots = _setup_draft_for_move(session)
    m1, m2 = matches

    resp = client.post(
        f"/api/desk/tournaments/{t.id}/matches/swap",
        json={"version_id": v.id, "match_a_id": m1.id, "match_b_id": m2.id},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True

    # Verify assignments are swapped
    a1 = session.exec(
        select(MatchAssignment).where(
            MatchAssignment.schedule_version_id == v.id,
            MatchAssignment.match_id == m1.id,
        )
    ).first()
    a2 = session.exec(
        select(MatchAssignment).where(
            MatchAssignment.schedule_version_id == v.id,
            MatchAssignment.match_id == m2.id,
        )
    ).first()
    assert a1.slot_id == slots[1].id  # m1 now on court 2
    assert a2.slot_id == slots[0].id  # m2 now on court 1


def test_add_time_slot(client, session):
    """Adding a time slot creates new ScheduleSlot records."""
    t, v, ev, teams, matches, slots = _setup_draft_for_move(session)

    resp = client.post(
        f"/api/desk/tournaments/{t.id}/slots",
        json={
            "version_id": v.id,
            "day_date": "2026-07-01",
            "start_time": "14:00",
            "end_time": "15:00",
            "court_numbers": [1, 2],
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert len(body["created_slots"]) == 2
    assert body["created_slots"][0]["start_time"] == "14:00"


def test_delete_time_slot_unassigned(client, session):
    """Deleting an unassigned time slot removes matching slots."""
    t, v, ev, teams, matches, slots = _setup_draft_for_move(session)

    # Create a fresh row to delete.
    add_resp = client.post(
        f"/api/desk/tournaments/{t.id}/slots",
        json={
            "version_id": v.id,
            "day_date": "2026-07-01",
            "start_time": "14:00",
            "end_time": "15:00",
            "court_numbers": [1, 2],
        },
    )
    assert add_resp.status_code == 200
    assert len(add_resp.json()["created_slots"]) == 2

    del_resp = client.post(
        f"/api/desk/tournaments/{t.id}/slots/delete",
        json={
            "version_id": v.id,
            "day_date": "2026-07-01",
            "start_time": "14:00",
            "court_numbers": [1, 2],
        },
    )
    assert del_resp.status_code == 200
    body = del_resp.json()
    assert body["success"] is True
    assert len(body["deleted_slots"]) == 2
    assert len(body["blocked_slots"]) == 0

    remaining = session.exec(
        select(ScheduleSlot).where(
            ScheduleSlot.schedule_version_id == v.id,
            ScheduleSlot.day_date == date(2026, 7, 1),
            ScheduleSlot.start_time == time(14, 0),
        )
    ).all()
    assert len(remaining) == 0


def test_delete_time_slot_assigned_is_blocked(client, session):
    """Deleting a slot with an assigned match should be blocked."""
    t, v, ev, teams, matches, slots = _setup_draft_for_move(session)
    assigned_slot = slots[0]  # 9:00 court 1 has m1 assigned
    assigned_match = matches[0]

    del_resp = client.post(
        f"/api/desk/tournaments/{t.id}/slots/delete",
        json={
            "version_id": v.id,
            "day_date": "2026-07-01",
            "start_time": "09:00",
            "court_numbers": [1],
        },
    )
    assert del_resp.status_code == 200
    body = del_resp.json()
    assert body["success"] is True
    assert len(body["deleted_slots"]) == 0
    assert len(body["blocked_slots"]) == 1
    blocked = body["blocked_slots"][0]
    assert blocked["slot_id"] == assigned_slot.id
    assert blocked["match_id"] == assigned_match.id
    assert blocked["match_code"] == assigned_match.match_code

    still_exists = session.get(ScheduleSlot, assigned_slot.id)
    assert still_exists is not None


def test_delete_time_slot_rejected_on_final_version(client, session):
    """Deleting slots is rejected on a FINAL version."""
    t, v, ev, teams, matches = _setup_tournament_with_matches(session)
    resp = client.post(
        f"/api/desk/tournaments/{t.id}/slots/delete",
        json={
            "version_id": v.id,
            "day_date": "2026-06-05",
            "start_time": "09:00",
            "court_numbers": [1],
        },
    )
    assert resp.status_code == 400
    assert "DRAFT" in resp.json()["detail"]


def test_add_court(client, session):
    """Adding a court appends to tournament.court_names."""
    t, v, ev, teams, matches, slots = _setup_draft_for_move(session)

    resp = client.post(
        f"/api/desk/tournaments/{t.id}/courts",
        json={
            "version_id": v.id,
            "court_label": "3",
            "create_matching_slots": True,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert "3" in body["courts"]
    assert body["created_slots"] > 0

    session.refresh(t)
    assert "3" in t.court_names


def test_update_court_renames_label_and_slots(client, session):
    """Renaming a court updates tournament.court_names and slot labels."""
    t, v, ev, teams, matches, slots = _setup_draft_for_move(session)

    resp = client.patch(
        f"/api/desk/tournaments/{t.id}/courts/2",
        json={
            "version_id": v.id,
            "new_court_label": "Stadium",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["court_number"] == 2
    assert body["new_court_label"] == "Stadium"
    assert body["updated_slots"] >= 1

    session.refresh(t)
    assert t.court_names == ["1", "Stadium"]

    c2_slots = session.exec(
        select(ScheduleSlot).where(
            ScheduleSlot.schedule_version_id == v.id,
            ScheduleSlot.court_number == 2,
        )
    ).all()
    assert len(c2_slots) > 0
    assert all(s.court_label == "Stadium" for s in c2_slots)


def test_delete_newest_court_requires_slot_opt_in_then_deletes(client, session):
    """Deleting newest court with slots requires opt-in; with opt-in it succeeds."""
    t, v, ev, teams, matches, slots = _setup_draft_for_move(session)

    add_resp = client.post(
        f"/api/desk/tournaments/{t.id}/courts",
        json={
            "version_id": v.id,
            "court_label": "3",
            "create_matching_slots": True,
        },
    )
    assert add_resp.status_code == 200

    # First attempt without deleting slots should be rejected.
    reject = client.request(
        "DELETE",
        f"/api/desk/tournaments/{t.id}/courts/3",
        json={
            "version_id": v.id,
            "delete_matching_slots": False,
        },
    )
    assert reject.status_code == 400
    assert "delete_matching_slots" in reject.json()["detail"]

    ok = client.request(
        "DELETE",
        f"/api/desk/tournaments/{t.id}/courts/3",
        json={
            "version_id": v.id,
            "delete_matching_slots": True,
        },
    )
    assert ok.status_code == 200
    body = ok.json()
    assert body["success"] is True
    assert body["court_label"] == "3"
    assert body["removed_slots"] > 0

    session.refresh(t)
    assert t.court_names == ["1", "2"]


def test_fill_court_slots_creates_missing_open_slots(client, session):
    """Fill endpoint backfills missing open slots for an existing court."""
    t, v, ev, teams, matches, slots = _setup_draft_for_move(session)

    add_resp = client.post(
        f"/api/desk/tournaments/{t.id}/courts",
        json={
            "version_id": v.id,
            "court_label": "3",
            "create_matching_slots": False,
        },
    )
    assert add_resp.status_code == 200
    assert add_resp.json()["created_slots"] == 0

    fill_resp = client.post(
        f"/api/desk/tournaments/{t.id}/courts/3/slots/fill",
        json={"version_id": v.id},
    )
    assert fill_resp.status_code == 200
    body = fill_resp.json()
    assert body["success"] is True
    assert body["court_label"] == "3"
    assert body["created_slots"] > 0

    c3_slots = session.exec(
        select(ScheduleSlot).where(
            ScheduleSlot.schedule_version_id == v.id,
            ScheduleSlot.court_number == 3,
        )
    ).all()
    assert len(c3_slots) == body["created_slots"]


def test_remap_courts_updates_slot_numbers_and_labels(client, session):
    """Global remap updates slot court_number/court_label only (assignments stay attached to same slots)."""
    t, v, ev, teams, matches, slots = _setup_draft_for_move(session)

    pre_assignments = session.exec(
        select(MatchAssignment).where(MatchAssignment.schedule_version_id == v.id)
    ).all()
    pre_by_slot = {a.match_id: a.slot_id for a in pre_assignments}

    resp = client.post(
        f"/api/desk/tournaments/{t.id}/courts/remap",
        json={
            "version_id": v.id,
            "mapping": {"1": 15, "2": 16},
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["remapped_slots"] >= 1

    updated_slots = session.exec(
        select(ScheduleSlot).where(ScheduleSlot.schedule_version_id == v.id)
    ).all()
    assert len(updated_slots) > 0
    assert all(s.court_number in (15, 16) for s in updated_slots)
    assert all((s.court_label or "") in ("15", "16") for s in updated_slots)

    post_assignments = session.exec(
        select(MatchAssignment).where(MatchAssignment.schedule_version_id == v.id)
    ).all()
    post_by_slot = {a.match_id: a.slot_id for a in post_assignments}
    assert post_by_slot == pre_by_slot


def test_remap_courts_rejects_duplicate_targets(client, session):
    """Remap fails when multiple sources point to the same target number."""
    t, v, ev, teams, matches, slots = _setup_draft_for_move(session)

    resp = client.post(
        f"/api/desk/tournaments/{t.id}/courts/remap",
        json={
            "version_id": v.id,
            "mapping": {"1": 15, "2": 15},
        },
    )
    assert resp.status_code == 400
    assert "duplicate target" in resp.json()["detail"].lower()


def test_conflict_check_move_day_cap(client, session):
    """Conflict check for MOVE detects day cap exceeded at target slot."""
    t, v, ev, teams, matches, slots = _setup_draft_for_move(session)
    m1, m2 = matches
    slot_c1_t2 = slots[2]

    # Mark m1 as IN_PROGRESS (counts toward daily cap)
    m1.runtime_status = "IN_PROGRESS"
    session.add(m1)
    # Mark m2 as FINAL (also counts)
    m2.runtime_status = "FINAL"
    m2.winner_team_id = teams[1].id
    session.add(m2)
    session.flush()

    # Create a third match for Bravo (also FINAL) to give Bravo 2 FINAL/IP matches
    m3_extra = Match(
        tournament_id=t.id, event_id=ev.id, schedule_version_id=v.id,
        match_code="MIX_WF_R1_M03", match_type="WF",
        round_number=1, round_index=1, sequence_in_round=3, duration_minutes=60,
        team_a_id=teams[1].id, team_b_id=teams[3].id,
        placeholder_side_a="SEED_2", placeholder_side_b="SEED_4",
        runtime_status="FINAL", winner_team_id=teams[1].id,
    )
    session.add(m3_extra)
    session.flush()
    slot_c2_t2 = slots[3]
    a3x = MatchAssignment(schedule_version_id=v.id, match_id=m3_extra.id, slot_id=slot_c2_t2.id)
    session.add(a3x)
    session.flush()

    # Create a fourth match for Bravo (the one we'll check)
    m4 = Match(
        tournament_id=t.id, event_id=ev.id, schedule_version_id=v.id,
        match_code="MIX_WF_R2_M01", match_type="WF",
        round_number=2, round_index=1, sequence_in_round=1, duration_minutes=60,
        team_a_id=teams[1].id, team_b_id=teams[0].id,
        placeholder_side_a="W1", placeholder_side_b="W2",
    )
    session.add(m4)
    session.flush()

    # Need a 5th slot for m4
    extra_slot = ScheduleSlot(
        tournament_id=t.id, schedule_version_id=v.id,
        day_date=date(2026, 7, 1), start_time=time(12, 0), end_time=time(13, 0),
        court_number=1, court_label="1", block_minutes=60,
    )
    session.add(extra_slot)
    session.flush()

    a4 = MatchAssignment(schedule_version_id=v.id, match_id=m4.id, slot_id=extra_slot.id)
    session.add(a4)
    session.commit()

    # Check conflicts for setting m4 IN_PROGRESS — Bravo already has 2 matches today (m2 FINAL + m3_extra FINAL)
    resp = client.post(
        f"/api/desk/tournaments/{t.id}/conflicts/check",
        json={
            "version_id": v.id,
            "action_type": "SET_IN_PROGRESS",
            "match_id": m4.id,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    day_cap_conflicts = [c for c in body["conflicts"] if c["code"] == "DAY_CAP_EXCEEDED"]
    assert len(day_cap_conflicts) > 0


def test_conflict_check_move_with_target_slot(client, session):
    """Conflict check with target_slot_id uses the target slot for evaluation."""
    t, v, ev, teams, matches, slots = _setup_draft_for_move(session)
    m1 = matches[0]

    # target slot is on same day, same team — should run without error
    resp = client.post(
        f"/api/desk/tournaments/{t.id}/conflicts/check",
        json={
            "version_id": v.id,
            "action_type": "MOVE",
            "match_id": m1.id,
            "target_slot_id": slots[2].id,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body["conflicts"], list)


def test_snapshot_includes_slots_and_grid_fields(client, session):
    """Snapshot response includes slots array and grid fields per match."""
    t, v, ev, teams, matches, slots = _setup_draft_for_move(session)

    resp = client.get(f"/api/desk/tournaments/{t.id}/snapshot?version_id={v.id}")
    assert resp.status_code == 200
    body = resp.json()

    assert "slots" in body
    assert len(body["slots"]) == 4  # 2 courts x 2 times

    m1_data = next(m for m in body["matches"] if m["match_id"] == matches[0].id)
    assert m1_data["slot_id"] is not None
    assert m1_data["assignment_id"] is not None
    assert m1_data["court_number"] is not None
    assert m1_data["day_date"] is not None


# ── Reschedule Engine tests ──────────────────────────────────────────────

def _setup_reschedule(session: Session, *, num_matches=4):
    """
    Set up a two-day, 2-court tournament with matches assigned on Day 1.
    Returns (tournament, version, event, teams, matches, slots).
    Day 1 slots: 09:00, 10:30 on courts 1,2  (4 slots)
    Day 2 slots: 09:00, 10:30 on courts 1,2  (4 slots)
    """
    t = Tournament(
        name="Rain Test",
        location="Beach",
        timezone="America/New_York",
        start_date=date(2026, 7, 1),
        end_date=date(2026, 7, 2),
        court_names=["1", "2"],
    )
    session.add(t)
    session.flush()

    v = ScheduleVersion(
        tournament_id=t.id, version_number=1, status="draft", notes="Desk Draft",
    )
    session.add(v)
    session.flush()

    ev = Event(tournament_id=t.id, category="mixed", name="Mixed A", team_count=8)
    session.add(ev)
    session.flush()

    teams = []
    for i in range(1, num_matches * 2 + 1):
        team = Team(event_id=ev.id, name=f"Team{i}", seed=i, display_name=f"Team {i}")
        session.add(team)
        session.flush()
        teams.append(team)

    matches = []
    for i in range(num_matches):
        m = Match(
            tournament_id=t.id, event_id=ev.id, schedule_version_id=v.id,
            match_code=f"MIX_WF_R1_M{i+1:02d}", match_type="WF",
            round_number=1, round_index=1, sequence_in_round=i + 1, duration_minutes=60,
            team_a_id=teams[i * 2].id, team_b_id=teams[i * 2 + 1].id,
            placeholder_side_a=f"SEED_{i*2+1}", placeholder_side_b=f"SEED_{i*2+2}",
        )
        session.add(m)
        session.flush()
        matches.append(m)

    # Day 1: 4 slots
    d1_slots = []
    for ct in [1, 2]:
        for h, m in [(9, 0), (10, 30)]:
            s = ScheduleSlot(
                tournament_id=t.id, schedule_version_id=v.id,
                day_date=date(2026, 7, 1), start_time=time(h, m), end_time=time(h + 1, m),
                court_number=ct, court_label=str(ct), block_minutes=60,
            )
            session.add(s)
            session.flush()
            d1_slots.append(s)

    # Day 2: 4 slots
    d2_slots = []
    for ct in [1, 2]:
        for h, m in [(9, 0), (10, 30)]:
            s = ScheduleSlot(
                tournament_id=t.id, schedule_version_id=v.id,
                day_date=date(2026, 7, 2), start_time=time(h, m), end_time=time(h + 1, m),
                court_number=ct, court_label=str(ct), block_minutes=60,
            )
            session.add(s)
            session.flush()
            d2_slots.append(s)

    # Assign matches to Day 1 slots
    for i, m in enumerate(matches[:len(d1_slots)]):
        a = MatchAssignment(schedule_version_id=v.id, match_id=m.id, slot_id=d1_slots[i].id)
        session.add(a)

    session.commit()

    return t, v, ev, teams, matches, d1_slots + d2_slots


def test_reschedule_partial_day(client, session):
    """Partial day: matches after cutoff are moved to available slots."""
    t, v, ev, teams, matches, slots = _setup_reschedule(session)

    resp = client.post(f"/api/desk/tournaments/{t.id}/reschedule/preview", json={
        "version_id": v.id,
        "mode": "PARTIAL_DAY",
        "affected_day": "2026-07-01",
        "unavailable_from": "10:00",
        "available_from": "14:00",
        "add_time_slots": False,
    })
    assert resp.status_code == 200
    body = resp.json()

    assert body["stats"]["total_affected"] > 0
    assert body["stats"]["total_moved"] > 0
    for move in body["proposed_moves"]:
        assert move["new_slot_id"] is not None
        assert move["match_id"] in [m.id for m in matches]


def test_reschedule_full_washout(client, session):
    """Full washout: all Day 1 unplayed matches move to Day 2."""
    t, v, ev, teams, matches, slots = _setup_reschedule(session)

    resp = client.post(f"/api/desk/tournaments/{t.id}/reschedule/preview", json={
        "version_id": v.id,
        "mode": "FULL_WASHOUT",
        "affected_day": "2026-07-01",
        "add_time_slots": False,
    })
    assert resp.status_code == 200
    body = resp.json()

    assert body["stats"]["total_affected"] == 4
    for move in body["proposed_moves"]:
        assert move["new_day"] == "2026-07-02"


def test_reschedule_court_loss(client, session):
    """Court loss: matches on court 2 redistributed away from affected slots."""
    t, v, ev, teams, matches, slots = _setup_reschedule(session)

    resp = client.post(f"/api/desk/tournaments/{t.id}/reschedule/preview", json={
        "version_id": v.id,
        "mode": "COURT_LOSS",
        "affected_day": "2026-07-01",
        "unavailable_courts": [2],
        "add_time_slots": False,
    })
    assert resp.status_code == 200
    body = resp.json()

    affected = body["stats"]["total_affected"]
    assert affected > 0
    for move in body["proposed_moves"]:
        # Moved matches should not land on court 2 on the affected day
        if move["new_day"] == "2026-07-01":
            assert "Court 2" not in move["new_court"]


def test_reschedule_locked_matches_excluded(client, session):
    """Locked matches are not moved by the reschedule engine."""
    t, v, ev, teams, matches, slots = _setup_reschedule(session)

    # Lock the first match
    assignment = session.exec(
        select(MatchAssignment).where(
            MatchAssignment.schedule_version_id == v.id,
            MatchAssignment.match_id == matches[0].id,
        )
    ).first()
    assignment.locked = True
    session.add(assignment)
    session.commit()

    resp = client.post(f"/api/desk/tournaments/{t.id}/reschedule/preview", json={
        "version_id": v.id,
        "mode": "FULL_WASHOUT",
        "affected_day": "2026-07-01",
        "add_time_slots": False,
    })
    assert resp.status_code == 200
    body = resp.json()

    moved_ids = [m["match_id"] for m in body["proposed_moves"]]
    assert matches[0].id not in moved_ids


def test_reschedule_final_matches_excluded(client, session):
    """FINAL matches are not moved by the reschedule engine."""
    t, v, ev, teams, matches, slots = _setup_reschedule(session)

    # Mark first match as FINAL
    matches[0].runtime_status = "FINAL"
    session.add(matches[0])
    session.commit()

    resp = client.post(f"/api/desk/tournaments/{t.id}/reschedule/preview", json={
        "version_id": v.id,
        "mode": "FULL_WASHOUT",
        "affected_day": "2026-07-01",
        "add_time_slots": False,
    })
    assert resp.status_code == 200
    body = resp.json()

    moved_ids = [m["match_id"] for m in body["proposed_moves"]]
    assert matches[0].id not in moved_ids
    assert body["stats"]["total_kept"] >= 1


def test_reschedule_unplaceable_when_no_slots(client, session):
    """When no slots are available and add_time_slots is off, matches are unplaceable."""
    t, v, ev, teams, matches, slots = _setup_reschedule(session, num_matches=4)

    # Mark ALL Day 2 slots as inactive so nothing is available
    for s in slots:
        if s.day_date == date(2026, 7, 2):
            s.is_active = False
            session.add(s)
    session.commit()

    resp = client.post(f"/api/desk/tournaments/{t.id}/reschedule/preview", json={
        "version_id": v.id,
        "mode": "FULL_WASHOUT",
        "affected_day": "2026-07-01",
        "add_time_slots": False,
    })
    assert resp.status_code == 200
    body = resp.json()

    assert body["stats"]["total_unplaceable"] > 0
    assert len(body["unplaceable"]) > 0


def test_reschedule_apply(client, session):
    """Apply reschedule updates match assignments."""
    t, v, ev, teams, matches, slots = _setup_reschedule(session)

    # Preview
    resp = client.post(f"/api/desk/tournaments/{t.id}/reschedule/preview", json={
        "version_id": v.id,
        "mode": "FULL_WASHOUT",
        "affected_day": "2026-07-01",
        "add_time_slots": False,
    })
    assert resp.status_code == 200
    preview = resp.json()

    # Apply
    moves = [{"match_id": m["match_id"], "new_slot_id": m["new_slot_id"]} for m in preview["proposed_moves"]]
    resp2 = client.post(f"/api/desk/tournaments/{t.id}/reschedule/apply", json={
        "version_id": v.id,
        "moves": moves,
    })
    assert resp2.status_code == 200
    body = resp2.json()
    assert body["applied_moves"] == len(moves)

    # Verify assignments are updated
    for m in preview["proposed_moves"]:
        assign = session.exec(
            select(MatchAssignment).where(
                MatchAssignment.schedule_version_id == v.id,
                MatchAssignment.match_id == m["match_id"],
            )
        ).first()
        assert assign is not None
        assert assign.slot_id == m["new_slot_id"]
        assert assign.locked is True


def test_reschedule_rejects_final_version(client, session):
    """Reschedule preview rejects non-draft versions."""
    t, v, ev, teams, matches, slots = _setup_reschedule(session)

    v.status = "final"
    session.add(v)
    session.commit()

    resp = client.post(f"/api/desk/tournaments/{t.id}/reschedule/preview", json={
        "version_id": v.id,
        "mode": "FULL_WASHOUT",
        "affected_day": "2026-07-01",
    })
    assert resp.status_code == 400


def test_reschedule_feasibility(client, session):
    """Feasibility endpoint returns correct fits/utilization for each format."""
    t, v, ev, teams, matches, slots = _setup_reschedule(session)

    resp = client.post(f"/api/desk/tournaments/{t.id}/reschedule/feasibility", json={
        "version_id": v.id,
        "mode": "FULL_WASHOUT",
        "affected_day": "2026-07-01",
    })
    assert resp.status_code == 200
    body = resp.json()

    assert body["affected_count"] == 4
    assert len(body["formats"]) == 3

    fmt_by_key = {f["format"]: f for f in body["formats"]}
    assert "REGULAR" in fmt_by_key
    assert "PRO_SET_8" in fmt_by_key
    assert "PRO_SET_4" in fmt_by_key

    assert fmt_by_key["REGULAR"]["duration"] == 105
    assert fmt_by_key["PRO_SET_8"]["duration"] == 60
    assert fmt_by_key["PRO_SET_4"]["duration"] == 35

    # 4 Day 2 slots x 60 min = 240 available minutes
    # Regular: 4 * 105 = 420 needed -> won't fit
    assert fmt_by_key["REGULAR"]["fits"] is False
    # Pro Set 8: 4 * 60 = 240 needed -> exactly fits
    assert fmt_by_key["PRO_SET_8"]["fits"] is True
    # Pro Set 4: 4 * 35 = 140 needed -> fits easily
    assert fmt_by_key["PRO_SET_4"]["fits"] is True

    for f in body["formats"]:
        assert isinstance(f["utilization"], int)
        assert "label" in f


def test_reschedule_preview_with_scoring_format(client, session):
    """Preview with scoring_format uses compressed durations for placement."""
    t, v, ev, teams, matches, slots = _setup_reschedule(session)

    resp = client.post(f"/api/desk/tournaments/{t.id}/reschedule/preview", json={
        "version_id": v.id,
        "mode": "FULL_WASHOUT",
        "affected_day": "2026-07-01",
        "scoring_format": "PRO_SET_4",
        "add_time_slots": False,
    })
    assert resp.status_code == 200
    body = resp.json()

    assert body["format_applied"] == "PRO_SET_4"
    assert body["duration_updates"] is not None
    assert len(body["duration_updates"]) > 0

    for match_id_str, new_dur in body["duration_updates"].items():
        assert new_dur == 35

    assert body["stats"]["total_moved"] > 0
    assert body["stats"]["total_affected"] == 4


def test_reschedule_apply_with_duration_updates(client, session):
    """Apply with duration_updates persists new match durations."""
    t, v, ev, teams, matches, slots = _setup_reschedule(session)

    # Preview with compressed format
    resp = client.post(f"/api/desk/tournaments/{t.id}/reschedule/preview", json={
        "version_id": v.id,
        "mode": "FULL_WASHOUT",
        "affected_day": "2026-07-01",
        "scoring_format": "PRO_SET_4",
        "add_time_slots": False,
    })
    assert resp.status_code == 200
    preview = resp.json()

    moves = [{"match_id": m["match_id"], "new_slot_id": m["new_slot_id"]} for m in preview["proposed_moves"]]

    # Apply with duration_updates
    resp2 = client.post(f"/api/desk/tournaments/{t.id}/reschedule/apply", json={
        "version_id": v.id,
        "moves": moves,
        "duration_updates": preview["duration_updates"],
    })
    assert resp2.status_code == 200
    body = resp2.json()
    assert body["applied_moves"] == len(moves)

    # Verify match durations updated in DB
    for match_id_str in preview["duration_updates"]:
        match = session.get(Match, int(match_id_str))
        assert match is not None
        assert match.duration_minutes == 35
