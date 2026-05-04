"""WF round 1 side swap (TD pre-play draw edit)."""

from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.models.event import Event
from app.models.match import Match
from app.models.schedule_version import ScheduleVersion
from app.models.team import Team
from app.models.tournament import Tournament


@pytest.fixture
def wf_swap_fixture(session: Session):
    tournament = Tournament(
        name="WF Swap Test",
        location="Here",
        timezone="America/New_York",
        start_date=date(2026, 2, 1),
        end_date=date(2026, 2, 3),
    )
    session.add(tournament)
    session.commit()
    session.refresh(tournament)

    event = Event(
        tournament_id=tournament.id,
        category="mixed",
        name="WF Event",
        team_count=4,
        draw_plan_json='{"template_type":"WF_TO_POOLS_DYNAMIC"}',
        draw_status="final",
        guarantee_selected=5,
    )
    session.add(event)
    session.commit()
    session.refresh(event)

    version = ScheduleVersion(tournament_id=tournament.id, version_number=1, status="draft")
    session.add(version)
    session.commit()
    session.refresh(version)

    t1 = Team(event_id=event.id, name="Team Alpha", seed=1)
    t2 = Team(event_id=event.id, name="Team Beta", seed=2)
    t3 = Team(event_id=event.id, name="Team Gamma", seed=3)
    t4 = Team(event_id=event.id, name="Team Delta", seed=4)
    session.add(t1)
    session.add(t2)
    session.add(t3)
    session.add(t4)
    session.commit()
    session.refresh(t1)
    session.refresh(t2)
    session.refresh(t3)
    session.refresh(t4)

    m1 = Match(
        tournament_id=tournament.id,
        schedule_version_id=version.id,
        event_id=event.id,
        match_code="E_WF_01_01",
        match_type="WF",
        round_number=1,
        round_index=1,
        sequence_in_round=1,
        duration_minutes=60,
        placeholder_side_a="Team Alpha",
        placeholder_side_b="Team Beta",
        team_a_id=t1.id,
        team_b_id=t2.id,
        status="unscheduled",
    )
    m2 = Match(
        tournament_id=tournament.id,
        schedule_version_id=version.id,
        event_id=event.id,
        match_code="E_WF_01_02",
        match_type="WF",
        round_number=1,
        round_index=1,
        sequence_in_round=2,
        duration_minutes=60,
        placeholder_side_a="Team Gamma",
        placeholder_side_b="Team Delta",
        team_a_id=t3.id,
        team_b_id=t4.id,
        status="unscheduled",
    )
    session.add(m1)
    session.add(m2)
    session.commit()
    session.refresh(m1)
    session.refresh(m2)

    return {
        "tournament_id": tournament.id,
        "event_id": event.id,
        "version_id": version.id,
        "m1_id": m1.id,
        "m2_id": m2.id,
        "t1_id": t1.id,
        "t2_id": t2.id,
        "t3_id": t3.id,
        "t4_id": t4.id,
    }


def test_wf_r1_swap_cross_matches(client: TestClient, session: Session, wf_swap_fixture):
    fx = wf_swap_fixture
    body = {
        "schedule_version_id": fx["version_id"],
        "event_id": fx["event_id"],
        "match_id_a": fx["m1_id"],
        "slot_a": "A",
        "match_id_b": fx["m2_id"],
        "slot_b": "A",
    }
    res = client.post(f"/api/tournaments/{fx['tournament_id']}/schedule/wf-r1-swap-slots", json=body)
    assert res.status_code == 200, res.text

    m1 = session.get(Match, fx["m1_id"])
    m2 = session.get(Match, fx["m2_id"])
    assert m1 is not None and m2 is not None
    assert m1.team_a_id == fx["t3_id"]
    assert m2.team_a_id == fx["t1_id"]
    assert m1.placeholder_side_a == "Team Gamma"
    assert m2.placeholder_side_a == "Team Alpha"


def test_wf_r1_swap_same_match_flips_sides(client: TestClient, session: Session, wf_swap_fixture):
    fx = wf_swap_fixture
    body = {
        "schedule_version_id": fx["version_id"],
        "event_id": fx["event_id"],
        "match_id_a": fx["m1_id"],
        "slot_a": "A",
        "match_id_b": fx["m1_id"],
        "slot_b": "B",
    }
    res = client.post(f"/api/tournaments/{fx['tournament_id']}/schedule/wf-r1-swap-slots", json=body)
    assert res.status_code == 200, res.text

    m1 = session.get(Match, fx["m1_id"])
    assert m1 is not None
    assert m1.team_a_id == fx["t2_id"]
    assert m1.team_b_id == fx["t1_id"]


def test_wf_r1_swap_rejects_final_version(client: TestClient, session: Session, wf_swap_fixture):
    fx = wf_swap_fixture
    ver = session.get(ScheduleVersion, fx["version_id"])
    assert ver is not None
    ver.status = "final"
    session.add(ver)
    session.commit()

    body = {
        "schedule_version_id": fx["version_id"],
        "event_id": fx["event_id"],
        "match_id_a": fx["m1_id"],
        "slot_a": "A",
        "match_id_b": fx["m2_id"],
        "slot_b": "B",
    }
    res = client.post(f"/api/tournaments/{fx['tournament_id']}/schedule/wf-r1-swap-slots", json=body)
    assert res.status_code == 400


def test_wf_r1_swap_rejects_non_wf_round(client: TestClient, session: Session, wf_swap_fixture):
    fx = wf_swap_fixture
    m2 = session.get(Match, fx["m2_id"])
    assert m2 is not None
    m2.round_index = 2
    session.add(m2)
    session.commit()

    body = {
        "schedule_version_id": fx["version_id"],
        "event_id": fx["event_id"],
        "match_id_a": fx["m1_id"],
        "slot_a": "A",
        "match_id_b": fx["m2_id"],
        "slot_b": "A",
    }
    res = client.post(f"/api/tournaments/{fx['tournament_id']}/schedule/wf-r1-swap-slots", json=body)
    assert res.status_code == 400
