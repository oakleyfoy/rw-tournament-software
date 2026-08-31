"""Post-draw staff corrections: move team between events and edit WF R1 matchups."""

from datetime import date, datetime, time
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.models.event import Event
from app.models.match import Match
from app.models.match_assignment import MatchAssignment
from app.models.player import Player
from app.models.schedule_slot import ScheduleSlot
from app.models.schedule_version import ScheduleVersion
from app.models.team import Team
from app.models.team_avoid_edge import TeamAvoidEdge
from app.models.team_player import TeamPlayer
from app.models.tournament import Tournament
from app.services.post_draw_corrections import (
    DESTINATION_DRAW_EXISTS_MESSAGE,
    DRAWS_EXIST_WARNING,
    EMPTY_WF_PLACEHOLDER,
    MOVE_BLOCKED_PLAYED_SOURCE,
    SEED_CLEARED_WARNING,
    WHO_KNOWS_WHO_WARNING,
)


@pytest.fixture
def post_draw_fixture(session: Session):
    tournament = Tournament(
        name="Post Draw Corrections",
        location="Test",
        timezone="America/New_York",
        start_date=date(2026, 3, 1),
        end_date=date(2026, 3, 3),
    )
    session.add(tournament)
    session.commit()
    session.refresh(tournament)

    womens_b = Event(
        tournament_id=tournament.id,
        category="womens",
        name="Women's B",
        team_count=6,
        draw_plan_json='{"template_type":"WF_TO_POOLS_DYNAMIC"}',
        draw_status="final",
        guarantee_selected=5,
    )
    womens_c = Event(
        tournament_id=tournament.id,
        category="womens",
        name="Women's C",
        team_count=2,
        draw_plan_json='{"template_type":"WF_TO_POOLS_DYNAMIC"}',
        draw_status="final",
        guarantee_selected=5,
    )
    womens_a = Event(
        tournament_id=tournament.id,
        category="womens",
        name="Women's A",
        team_count=2,
        draw_plan_json='{"template_type":"WF_TO_POOLS_DYNAMIC"}',
        draw_status="final",
        guarantee_selected=5,
    )
    session.add(womens_b)
    session.add(womens_c)
    session.add(womens_a)
    session.commit()
    session.refresh(womens_b)
    session.refresh(womens_c)
    session.refresh(womens_a)

    version = ScheduleVersion(tournament_id=tournament.id, version_number=1, status="draft")
    session.add(version)
    session.commit()
    session.refresh(version)

    team_a = Team(
        event_id=womens_b.id,
        name="Smith / Jones",
        seed=1,
        display_name="Smith / Jones",
        source_team_key="11|22",
        wf_group_index=1,
    )
    team_b = Team(event_id=womens_b.id, name="Brown / Davis", seed=2, display_name="Brown / Davis")
    team_c = Team(event_id=womens_b.id, name="Lee / Patel", seed=3, display_name="Lee / Patel")
    team_d = Team(event_id=womens_b.id, name="Nguyen / Kim", seed=4, display_name="Nguyen / Kim")
    team_e = Team(event_id=womens_b.id, name="Foster / Reed", seed=5, display_name="Foster / Reed")
    defaulted_team = Team(
        event_id=womens_b.id,
        name="Defaulted / Pair",
        seed=6,
        display_name="Defaulted / Pair",
        is_defaulted=True,
    )
    dest_1 = Team(event_id=womens_c.id, name="Chen / Garcia", seed=1, display_name="Chen / Garcia")
    dest_2 = Team(event_id=womens_c.id, name="Walsh / Ortiz", seed=2, display_name="Walsh / Ortiz")
    other_event_team = Team(event_id=womens_a.id, name="Adams / Baker", seed=1, display_name="Adams / Baker")
    session.add(team_a)
    session.add(team_b)
    session.add(team_c)
    session.add(team_d)
    session.add(team_e)
    session.add(defaulted_team)
    session.add(dest_1)
    session.add(dest_2)
    session.add(other_event_team)
    session.commit()
    for row in (team_a, team_b, team_c, team_d, team_e, defaulted_team, dest_1, dest_2, other_event_team):
        session.refresh(row)

    p1 = Player(tournament_id=tournament.id, full_name="Smith", phone_e164="+15551110001")
    p2 = Player(tournament_id=tournament.id, full_name="Jones", phone_e164="+15551110002")
    session.add(p1)
    session.add(p2)
    session.commit()
    session.refresh(p1)
    session.refresh(p2)
    session.add(TeamPlayer(team_id=team_a.id, player_id=p1.id, lineup_slot=1))
    session.add(TeamPlayer(team_id=team_a.id, player_id=p2.id, lineup_slot=2))
    session.add(
        TeamAvoidEdge(
            event_id=womens_b.id,
            team_id_a=min(team_a.id, team_b.id),
            team_id_b=max(team_a.id, team_b.id),
            reason="source who-knows-who",
        )
    )
    session.add(
        TeamAvoidEdge(
            event_id=womens_c.id,
            team_id_a=min(dest_1.id, dest_2.id),
            team_id_b=max(dest_1.id, dest_2.id),
            reason="destination who-knows-who",
        )
    )
    session.commit()

    source_m1 = Match(
        tournament_id=tournament.id,
        schedule_version_id=version.id,
        event_id=womens_b.id,
        match_code="WB_WF_01_01",
        match_type="WF",
        round_number=1,
        round_index=1,
        sequence_in_round=1,
        duration_minutes=60,
        placeholder_side_a=team_a.name,
        placeholder_side_b=team_b.name,
        team_a_id=team_a.id,
        team_b_id=team_b.id,
        status="scheduled",
    )
    source_m2 = Match(
        tournament_id=tournament.id,
        schedule_version_id=version.id,
        event_id=womens_b.id,
        match_code="WB_WF_01_02",
        match_type="WF",
        round_number=1,
        round_index=1,
        sequence_in_round=2,
        duration_minutes=60,
        placeholder_side_a=team_c.name,
        placeholder_side_b=team_d.name,
        team_a_id=team_c.id,
        team_b_id=team_d.id,
        status="unscheduled",
    )
    dest_m1 = Match(
        tournament_id=tournament.id,
        schedule_version_id=version.id,
        event_id=womens_c.id,
        match_code="WC_WF_01_01",
        match_type="WF",
        round_number=1,
        round_index=1,
        sequence_in_round=1,
        duration_minutes=60,
        placeholder_side_a=dest_1.name,
        placeholder_side_b=dest_2.name,
        team_a_id=dest_1.id,
        team_b_id=dest_2.id,
        status="scheduled",
    )
    session.add(source_m1)
    session.add(source_m2)
    session.add(dest_m1)
    session.commit()
    session.refresh(source_m1)
    session.refresh(source_m2)
    session.refresh(dest_m1)

    slot = ScheduleSlot(
        tournament_id=tournament.id,
        schedule_version_id=version.id,
        day_date=date(2026, 3, 1),
        start_time=time(9, 0),
        end_time=time(10, 0),
        block_minutes=60,
        court_number=1,
        court_label="Court 1",
    )
    session.add(slot)
    session.commit()
    session.refresh(slot)
    assignment = MatchAssignment(
        schedule_version_id=version.id,
        match_id=source_m1.id,
        slot_id=slot.id,
        assigned_by="TEST",
    )
    session.add(assignment)
    session.commit()
    session.refresh(assignment)

    return {
        "tournament_id": tournament.id,
        "womens_b_id": womens_b.id,
        "womens_c_id": womens_c.id,
        "womens_a_id": womens_a.id,
        "version_id": version.id,
        "team_a_id": team_a.id,
        "team_b_id": team_b.id,
        "team_c_id": team_c.id,
        "team_d_id": team_d.id,
        "team_e_id": team_e.id,
        "dest_1_id": dest_1.id,
        "dest_2_id": dest_2.id,
        "defaulted_team_id": defaulted_team.id,
        "womens_a_team_id": other_event_team.id,
        "source_m1_id": source_m1.id,
        "source_m2_id": source_m2.id,
        "dest_m1_id": dest_m1.id,
        "slot_id": slot.id,
        "assignment_id": assignment.id,
        "player_1_id": p1.id,
        "player_2_id": p2.id,
    }


def _move(client: TestClient, fx, team_id: int, dest_event_id: int, confirm: bool = True):
    return client.post(
        f"/api/tournaments/{fx['tournament_id']}/teams/{team_id}/move-division",
        json={"destination_event_id": dest_event_id, "confirm_existing_draws": confirm},
    )


def _edit(client: TestClient, fx, match_id: int, team_a_id, team_b_id):
    return client.post(
        f"/api/tournaments/{fx['tournament_id']}/schedule/matches/{match_id}/wf-r1-matchup",
        json={"team_a_id": team_a_id, "team_b_id": team_b_id},
    )


def test_move_requires_confirmation_when_draws_exist(client: TestClient, post_draw_fixture):
    fx = post_draw_fixture
    res = _move(client, fx, fx["team_a_id"], fx["womens_c_id"], confirm=False)
    assert res.status_code == 409
    detail = res.json()["detail"]
    assert detail["code"] == "DRAWS_EXIST_CONFIRMATION_REQUIRED"
    assert detail["message"] == DRAWS_EXIST_WARNING
    assert detail["source_has_matches"] is True
    assert detail["destination_has_matches"] is True


def test_move_team_between_events(client: TestClient, session: Session, post_draw_fixture):
    """TEST 1 — Move team between events. TEST 8 — pair integrity."""
    fx = post_draw_fixture
    team_count_before = len(session.exec(select(Team)).all())
    player_count_before = len(session.exec(select(Player)).all())
    link_count_before = len(session.exec(select(TeamPlayer)).all())

    res = _move(client, fx, fx["team_a_id"], fx["womens_c_id"], confirm=True)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["source_event_id"] == fx["womens_b_id"]
    assert body["destination_event_id"] == fx["womens_c_id"]
    assert body["team_id"] == fx["team_a_id"]
    assert set(body["player_ids"]) == {fx["player_1_id"], fx["player_2_id"]}

    session.expire_all()
    team = session.get(Team, fx["team_a_id"])
    assert team is not None
    assert team.event_id == fx["womens_c_id"]
    source_ids = {t.id for t in session.exec(select(Team).where(Team.event_id == fx["womens_b_id"])).all()}
    dest_ids = {t.id for t in session.exec(select(Team).where(Team.event_id == fx["womens_c_id"])).all()}
    assert fx["team_a_id"] not in source_ids
    assert fx["team_a_id"] in dest_ids

    links = session.exec(select(TeamPlayer).where(TeamPlayer.team_id == fx["team_a_id"])).all()
    assert {link.player_id for link in links} == {fx["player_1_id"], fx["player_2_id"]}
    assert len(session.exec(select(Team)).all()) == team_count_before
    assert len(session.exec(select(Player)).all()) == player_count_before
    assert len(session.exec(select(TeamPlayer)).all()) == link_count_before

    source_event = session.get(Event, fx["womens_b_id"])
    dest_event = session.get(Event, fx["womens_c_id"])
    assert source_event is not None and dest_event is not None
    assert source_event.team_count == 5
    assert dest_event.team_count == 3
    assert team.seed is None
    assert team.wf_group_index is None
    assert body["seed_cleared"] is True
    assert SEED_CLEARED_WARNING in body["warnings"]
    assert body["avoid_edges_removed"] == 1
    assert WHO_KNOWS_WHO_WARNING in body["warnings"]
    assert "Women's B" in body["message"]
    assert "was cleared" in body["message"]
    assert DESTINATION_DRAW_EXISTS_MESSAGE in body["message"]


def test_existing_source_draw_remains_intact(client: TestClient, session: Session, post_draw_fixture):
    """Moving an unplayed team clears ONLY its WF R1 side; match id/assignment/court/time survive."""
    fx = post_draw_fixture
    source_ids_before = {
        m.id for m in session.exec(select(Match).where(Match.event_id == fx["womens_b_id"])).all()
    }
    m2_before = session.get(Match, fx["source_m2_id"])
    assert m2_before is not None
    m2_snap = (m2_before.team_a_id, m2_before.team_b_id, m2_before.match_code, m2_before.round_index)

    with (
        patch("app.services.draw_plan_engine.generate_matches_for_event") as gen_engine,
        patch("app.utils.match_generation.generate_wf_matches") as gen_wf,
    ):
        res = _move(client, fx, fx["team_a_id"], fx["womens_c_id"], confirm=True)
        gen_engine.assert_not_called()
        gen_wf.assert_not_called()
    assert res.status_code == 200, res.text
    body = res.json()
    affected_ids = {m["id"] for m in body["affected_source_matches"]}
    assert fx["source_m1_id"] in affected_ids
    assert fx["source_m2_id"] not in affected_ids
    assert body["affected_source_matches"][0]["cleared_slots"] == ["A"]

    session.expire_all()
    source_ids_after = {
        m.id for m in session.exec(select(Match).where(Match.event_id == fx["womens_b_id"])).all()
    }
    assert source_ids_before == source_ids_after
    m1 = session.get(Match, fx["source_m1_id"])
    assert m1 is not None
    assert m1.id == fx["source_m1_id"]
    assert m1.team_a_id is None
    assert m1.team_b_id == fx["team_b_id"]
    assert m1.placeholder_side_a == EMPTY_WF_PLACEHOLDER
    assert m1.placeholder_side_b == "Brown / Davis"
    assert m1.match_type == "WF"
    assert m1.round_index == 1
    assert m1.sequence_in_round == 1
    assignment = session.get(MatchAssignment, fx["assignment_id"])
    assert assignment is not None
    assert assignment.match_id == fx["source_m1_id"]
    assert assignment.slot_id == fx["slot_id"]
    slot = session.get(ScheduleSlot, fx["slot_id"])
    assert slot is not None
    assert slot.court_label == "Court 1"
    assert slot.start_time == time(9, 0)
    m2 = session.get(Match, fx["source_m2_id"])
    assert m2 is not None
    assert (m2.team_a_id, m2.team_b_id, m2.match_code, m2.round_index) == m2_snap


def test_destination_draw_remains_intact(client: TestClient, session: Session, post_draw_fixture):
    """TEST 3 — destination draw is not regenerated or auto-rewritten."""
    fx = post_draw_fixture
    dest_before = {
        m.id: (m.team_a_id, m.team_b_id, m.match_code, m.round_index, m.sequence_in_round, m.placeholder_side_a, m.placeholder_side_b)
        for m in session.exec(select(Match).where(Match.event_id == fx["womens_c_id"])).all()
    }

    res = _move(client, fx, fx["team_a_id"], fx["womens_c_id"], confirm=True)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["destination_has_matches"] is True
    assert "Place this team manually using Edit WF Matchup" in body["message"]

    session.expire_all()
    dest_after = {
        m.id: (m.team_a_id, m.team_b_id, m.match_code, m.round_index, m.sequence_in_round, m.placeholder_side_a, m.placeholder_side_b)
        for m in session.exec(select(Match).where(Match.event_id == fx["womens_c_id"])).all()
    }
    assert dest_before == dest_after
    dest_m1 = session.get(Match, fx["dest_m1_id"])
    assert dest_m1 is not None
    assert dest_m1.team_a_id == fx["dest_1_id"]
    assert dest_m1.team_b_id == fx["dest_2_id"]


def test_edit_wf_r1_matchup_preserves_match_identity(
    client: TestClient, session: Session, post_draw_fixture
):
    """TEST 4 — replace Team 2, keep match id / stage / round / schedule."""
    fx = post_draw_fixture
    m2_before = session.get(Match, fx["source_m2_id"])
    dest_before = session.get(Match, fx["dest_m1_id"])
    assert m2_before is not None and dest_before is not None
    m2_snapshot = (
        m2_before.id,
        m2_before.team_a_id,
        m2_before.team_b_id,
        m2_before.match_code,
        m2_before.round_index,
        m2_before.sequence_in_round,
        m2_before.status,
    )
    dest_snapshot = (dest_before.id, dest_before.team_a_id, dest_before.team_b_id, dest_before.match_code)

    res = _edit(client, fx, fx["source_m1_id"], fx["team_a_id"], fx["team_e_id"])
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["match_id"] == fx["source_m1_id"]
    assert body["old_team_a_id"] == fx["team_a_id"]
    assert body["old_team_b_id"] == fx["team_b_id"]
    assert body["new_team_a_id"] == fx["team_a_id"]
    assert body["new_team_b_id"] == fx["team_e_id"]
    assert body["match_type"] == "WF"
    assert body["round_index"] == 1
    assert body["assignment_slot_id"] == fx["slot_id"]
    assert body["court_label"] == "Court 1"
    assert body["scheduled_time"] == "09:00"

    session.expire_all()
    m1 = session.get(Match, fx["source_m1_id"])
    assert m1 is not None
    assert m1.id == fx["source_m1_id"]
    assert m1.team_a_id == fx["team_a_id"]
    assert m1.team_b_id == fx["team_e_id"]
    assert m1.match_type == "WF"
    assert m1.round_index == 1
    assert m1.round_number == 1
    assert m1.sequence_in_round == 1
    assert m1.status == "scheduled"
    assignment = session.get(MatchAssignment, fx["assignment_id"])
    assert assignment is not None
    assert assignment.match_id == fx["source_m1_id"]
    assert assignment.slot_id == fx["slot_id"]
    slot = session.get(ScheduleSlot, fx["slot_id"])
    assert slot is not None
    assert slot.court_label == "Court 1"
    assert slot.start_time == time(9, 0)

    m2 = session.get(Match, fx["source_m2_id"])
    dest = session.get(Match, fx["dest_m1_id"])
    assert m2 is not None and dest is not None
    assert (
        m2.id,
        m2.team_a_id,
        m2.team_b_id,
        m2.match_code,
        m2.round_index,
        m2.sequence_in_round,
        m2.status,
    ) == m2_snapshot
    assert (dest.id, dest.team_a_id, dest.team_b_id, dest.match_code) == dest_snapshot


def test_edit_wf_r1_matchup_direct_replace_unused_side(
    client: TestClient, session: Session, post_draw_fixture
):
    """Replace Team B with a team that is not already in another R1 match after clearing."""
    fx = post_draw_fixture
    # Team B vs Team D would duplicate D. Clear D from m2, then replace B with D on m1.
    clear = _edit(client, fx, fx["source_m2_id"], fx["team_c_id"], None)
    assert clear.status_code == 200, clear.text
    res = _edit(client, fx, fx["source_m1_id"], fx["team_a_id"], fx["team_d_id"])
    assert res.status_code == 200, res.text
    session.expire_all()
    m1 = session.get(Match, fx["source_m1_id"])
    assert m1 is not None
    assert m1.id == fx["source_m1_id"]
    assert m1.team_a_id == fx["team_a_id"]
    assert m1.team_b_id == fx["team_d_id"]
    assert m1.match_type == "WF"
    assert m1.round_index == 1


def test_duplicate_team_prevention(client: TestClient, session: Session, post_draw_fixture):
    """TEST 5 — inserting a team already in another WF R1 match is rejected."""
    fx = post_draw_fixture
    m1_before = session.get(Match, fx["source_m1_id"])
    m2_before = session.get(Match, fx["source_m2_id"])
    assert m1_before is not None and m2_before is not None
    m1_snap = (m1_before.team_a_id, m1_before.team_b_id)
    m2_snap = (m2_before.team_a_id, m2_before.team_b_id)

    res = _edit(client, fx, fx["source_m1_id"], fx["team_a_id"], fx["team_c_id"])
    assert res.status_code == 409
    detail = res.json()["detail"]
    assert detail["code"] == "DUPLICATE_WF_R1_TEAM"
    assert "Match #2" in detail["message"]

    session.expire_all()
    m1 = session.get(Match, fx["source_m1_id"])
    m2 = session.get(Match, fx["source_m2_id"])
    assert m1 is not None and m2 is not None
    assert (m1.team_a_id, m1.team_b_id) == m1_snap
    assert (m2.team_a_id, m2.team_b_id) == m2_snap


def test_wrong_event_prevention(client: TestClient, session: Session, post_draw_fixture):
    """TEST 6 — a Women's A team cannot be placed into Women's B."""
    fx = post_draw_fixture
    res = _edit(client, fx, fx["source_m1_id"], fx["team_a_id"], fx["womens_a_team_id"])
    assert res.status_code == 400
    detail = res.json()["detail"]
    assert detail["code"] == "WRONG_EVENT"

    session.expire_all()
    m1 = session.get(Match, fx["source_m1_id"])
    assert m1 is not None
    assert m1.team_a_id == fx["team_a_id"]
    assert m1.team_b_id == fx["team_b_id"]


def test_completed_match_protection(client: TestClient, session: Session, post_draw_fixture):
    """TEST 7 — completed/in-progress matches cannot be edited; downstream stays put."""
    fx = post_draw_fixture
    m1 = session.get(Match, fx["source_m1_id"])
    assert m1 is not None
    downstream = Match(
        tournament_id=fx["tournament_id"],
        schedule_version_id=fx["version_id"],
        event_id=fx["womens_b_id"],
        match_code="WB_WF_02_01",
        match_type="WF",
        round_number=2,
        round_index=2,
        sequence_in_round=1,
        duration_minutes=60,
        placeholder_side_a="W(R1_1)",
        placeholder_side_b="W(R1_2)",
        team_a_id=fx["team_a_id"],
        team_b_id=None,
        source_match_a_id=fx["source_m1_id"],
        source_a_role="WINNER",
        status="unscheduled",
    )
    session.add(downstream)
    m1.runtime_status = "FINAL"
    m1.winner_team_id = fx["team_a_id"]
    m1.score_json = {"sets": [{"a": 6, "b": 3}]}
    m1.status = "complete"
    session.add(m1)
    session.commit()
    session.refresh(downstream)
    downstream_id = downstream.id
    downstream_snap = (downstream.team_a_id, downstream.team_b_id, downstream.match_code)

    res = _edit(client, fx, fx["source_m1_id"], fx["team_a_id"], fx["team_d_id"])
    assert res.status_code == 409
    detail = res.json()["detail"]
    assert detail["code"] == "MATCH_HAS_RESULT"
    assert "invalidate downstream bracket data" in detail["message"]

    session.expire_all()
    m1_after = session.get(Match, fx["source_m1_id"])
    child = session.get(Match, downstream_id)
    assert m1_after is not None and child is not None
    assert m1_after.team_a_id == fx["team_a_id"]
    assert m1_after.team_b_id == fx["team_b_id"]
    assert m1_after.winner_team_id == fx["team_a_id"]
    assert (child.team_a_id, child.team_b_id, child.match_code) == downstream_snap


def test_pair_integrity_move_does_not_split_partners(
    client: TestClient, session: Session, post_draw_fixture
):
    """TEST 8 — moving a doubles team moves both player links with the same team id."""
    fx = post_draw_fixture
    res = _move(client, fx, fx["team_a_id"], fx["womens_c_id"], confirm=True)
    assert res.status_code == 200, res.text
    session.expire_all()
    links = session.exec(select(TeamPlayer).where(TeamPlayer.team_id == fx["team_a_id"])).all()
    assert len(links) == 2
    assert {link.player_id for link in links} == {fx["player_1_id"], fx["player_2_id"]}
    team = session.get(Team, fx["team_a_id"])
    assert team is not None
    assert team.event_id == fx["womens_c_id"]
    for link in links:
        assert link.team_id == fx["team_a_id"]
    p1 = session.get(Player, fx["player_1_id"])
    p2 = session.get(Player, fx["player_2_id"])
    assert p1 is not None and p2 is not None
    assert p1.tournament_id == fx["tournament_id"]
    assert p2.tournament_id == fx["tournament_id"]


def test_same_team_both_sides_rejected(client: TestClient, post_draw_fixture):
    fx = post_draw_fixture
    res = _edit(client, fx, fx["source_m1_id"], fx["team_a_id"], fx["team_a_id"])
    assert res.status_code == 400
    assert res.json()["detail"]["code"] == "SAME_TEAM_BOTH_SIDES"


def test_wf_r1_matchup_context(client: TestClient, post_draw_fixture):
    fx = post_draw_fixture
    res = client.get(
        f"/api/tournaments/{fx['tournament_id']}/schedule/matches/{fx['source_m1_id']}/wf-r1-matchup"
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["stage"] == "WF"
    assert body["round_index"] == 1
    assert body["match_id"] == fx["source_m1_id"]
    assert body["court_label"] == "Court 1"
    assert body["scheduled_time"] == "09:00"
    assert body["edit_blocked"] is False
    available_ids = {t["id"] for t in body["available_teams"]}
    assert fx["team_a_id"] in available_ids
    assert fx["womens_a_team_id"] not in available_ids
    assert fx["defaulted_team_id"] not in available_ids
    assert all(t["is_defaulted"] is False for t in body["available_teams"])


def _move_state(session: Session, fx) -> dict:
    team = session.get(Team, fx["team_a_id"])
    m1 = session.get(Match, fx["source_m1_id"])
    m2 = session.get(Match, fx["source_m2_id"])
    dest = session.get(Match, fx["dest_m1_id"])
    assignment = session.get(MatchAssignment, fx["assignment_id"])
    assert team and m1 and m2 and dest and assignment
    source_edges = session.exec(select(TeamAvoidEdge).where(TeamAvoidEdge.event_id == fx["womens_b_id"])).all()
    dest_edges = session.exec(select(TeamAvoidEdge).where(TeamAvoidEdge.event_id == fx["womens_c_id"])).all()
    return {
        "event_id": team.event_id,
        "seed": team.seed,
        "wf_group_index": team.wf_group_index,
        "m1": (
            m1.id,
            m1.team_a_id,
            m1.team_b_id,
            m1.placeholder_side_a,
            m1.placeholder_side_b,
            m1.match_type,
            m1.round_index,
            m1.sequence_in_round,
        ),
        "m2": (m2.team_a_id, m2.team_b_id),
        "dest": (dest.team_a_id, dest.team_b_id),
        "assignment": (assignment.match_id, assignment.slot_id),
        "source_edge_pairs": sorted((e.team_id_a, e.team_id_b) for e in source_edges),
        "dest_edge_pairs": sorted((e.team_id_a, e.team_id_b) for e in dest_edges),
    }


def _assert_move_rejected_untouched(client: TestClient, session: Session, fx) -> None:
    before = _move_state(session, fx)
    res = _move(client, fx, fx["team_a_id"], fx["womens_c_id"], confirm=True)
    assert res.status_code == 409, res.text
    detail = res.json()["detail"]
    assert detail["code"] == "SOURCE_MATCH_PLAYED_OR_ADVANCED"
    assert detail["message"] == MOVE_BLOCKED_PLAYED_SOURCE
    session.expire_all()
    assert _move_state(session, fx) == before


def test_move_rejected_if_source_match_started(client: TestClient, session: Session, post_draw_fixture):
    fx = post_draw_fixture
    m1 = session.get(Match, fx["source_m1_id"])
    assert m1 is not None
    m1.runtime_status = "IN_PROGRESS"
    m1.started_at = datetime(2026, 3, 1, 9, 0)
    session.add(m1)
    session.commit()
    _assert_move_rejected_untouched(client, session, fx)


def test_move_rejected_if_source_match_has_score(client: TestClient, session: Session, post_draw_fixture):
    fx = post_draw_fixture
    m1 = session.get(Match, fx["source_m1_id"])
    assert m1 is not None
    m1.score_json = {"sets": [{"a": 6, "b": 2}]}
    session.add(m1)
    session.commit()
    _assert_move_rejected_untouched(client, session, fx)


def test_move_rejected_if_source_match_has_winner(client: TestClient, session: Session, post_draw_fixture):
    fx = post_draw_fixture
    m1 = session.get(Match, fx["source_m1_id"])
    assert m1 is not None
    m1.winner_team_id = fx["team_a_id"]
    session.add(m1)
    session.commit()
    _assert_move_rejected_untouched(client, session, fx)


def test_move_rejected_if_source_match_has_downstream_advancement(
    client: TestClient, session: Session, post_draw_fixture
):
    fx = post_draw_fixture
    downstream = Match(
        tournament_id=fx["tournament_id"],
        schedule_version_id=fx["version_id"],
        event_id=fx["womens_b_id"],
        match_code="WB_WF_02_01",
        match_type="WF",
        round_number=2,
        round_index=2,
        sequence_in_round=1,
        duration_minutes=60,
        placeholder_side_a="W(R1_1)",
        placeholder_side_b="W(R1_2)",
        team_a_id=fx["team_a_id"],
        team_b_id=None,
        source_match_a_id=fx["source_m1_id"],
        source_a_role="WINNER",
        status="unscheduled",
    )
    session.add(downstream)
    session.commit()
    before = _move_state(session, fx)
    downstream_id = downstream.id
    res = _move(client, fx, fx["team_a_id"], fx["womens_c_id"], confirm=True)
    assert res.status_code == 409, res.text
    assert res.json()["detail"]["code"] == "SOURCE_MATCH_PLAYED_OR_ADVANCED"
    session.expire_all()
    assert _move_state(session, fx) == before
    child = session.get(Match, downstream_id)
    assert child is not None
    assert child.team_a_id == fx["team_a_id"]
    assert child.source_match_a_id == fx["source_m1_id"]


def test_defaulted_team_cannot_be_inserted_into_wf_r1_matchup(
    client: TestClient, session: Session, post_draw_fixture
):
    fx = post_draw_fixture
    m1_before = session.get(Match, fx["source_m1_id"])
    assert m1_before is not None
    snap = (m1_before.team_a_id, m1_before.team_b_id)
    res = _edit(client, fx, fx["source_m1_id"], fx["team_a_id"], fx["defaulted_team_id"])
    assert res.status_code == 400, res.text
    detail = res.json()["detail"]
    assert detail["code"] == "DEFAULTED_TEAM"
    session.expire_all()
    m1 = session.get(Match, fx["source_m1_id"])
    assert m1 is not None
    assert (m1.team_a_id, m1.team_b_id) == snap
    defaulted = session.get(Team, fx["defaulted_team_id"])
    assert defaulted is not None
    assert defaulted.is_defaulted is True


def test_seed_collision_clears_seed_not_reassigned(client: TestClient, session: Session, post_draw_fixture):
    fx = post_draw_fixture
    dest_seeds_before = {
        t.seed for t in session.exec(select(Team).where(Team.event_id == fx["womens_c_id"])).all() if t.seed is not None
    }
    assert 1 in dest_seeds_before
    res = _move(client, fx, fx["team_a_id"], fx["womens_c_id"], confirm=True)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["seed_cleared"] is True
    assert SEED_CLEARED_WARNING in body["warnings"]
    session.expire_all()
    moved = session.get(Team, fx["team_a_id"])
    assert moved is not None
    assert moved.seed is None
    dest_seeds_after = {
        t.seed for t in session.exec(select(Team).where(Team.event_id == fx["womens_c_id"])).all() if t.seed is not None
    }
    assert dest_seeds_after == dest_seeds_before


def test_source_avoid_edges_removed_destination_not_created(
    client: TestClient, session: Session, post_draw_fixture
):
    fx = post_draw_fixture
    dest_pairs_before = sorted(
        (e.team_id_a, e.team_id_b)
        for e in session.exec(select(TeamAvoidEdge).where(TeamAvoidEdge.event_id == fx["womens_c_id"])).all()
    )
    res = _move(client, fx, fx["team_a_id"], fx["womens_c_id"], confirm=True)
    assert res.status_code == 200, res.text
    assert res.json()["avoid_edges_removed"] == 1
    assert WHO_KNOWS_WHO_WARNING in res.json()["warnings"]
    session.expire_all()
    source_edges = session.exec(select(TeamAvoidEdge).where(TeamAvoidEdge.event_id == fx["womens_b_id"])).all()
    assert source_edges == []
    dest_edges = session.exec(select(TeamAvoidEdge).where(TeamAvoidEdge.event_id == fx["womens_c_id"])).all()
    dest_pairs_after = sorted((e.team_id_a, e.team_id_b) for e in dest_edges)
    assert dest_pairs_after == dest_pairs_before
    involved = {
        tid
        for e in dest_edges
        for tid in (e.team_id_a, e.team_id_b)
    }
    assert fx["team_a_id"] not in involved
