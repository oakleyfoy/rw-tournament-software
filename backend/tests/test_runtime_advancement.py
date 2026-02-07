"""Phase 4 Advancement: finalizing upstream advances downstream team slots. Idempotent, version-isolated."""
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.models.event import Event
from app.models.match import Match
from app.models.tournament import Tournament
from app.models.schedule_version import ScheduleVersion
from app.models.team import Team


@pytest.fixture
def bracket_pair(client: TestClient, session: Session):
    """One upstream match, one downstream match (same version). Downstream source_match_a_id = upstream id."""
    tournament = Tournament(
        name="Advancement Test",
        location="Test",
        timezone="America/New_York",
        start_date=date(2026, 1, 15),
        end_date=date(2026, 1, 17),
    )
    session.add(tournament)
    session.commit()
    session.refresh(tournament)

    event = Event(
        tournament_id=tournament.id,
        category="mixed",
        name="Test Event",
        team_count=4,
        draw_plan_json="{}",
        draw_status="final",
    )
    session.add(event)
    session.commit()
    session.refresh(event)

    version = ScheduleVersion(
        tournament_id=tournament.id,
        version_number=1,
        notes="Test",
        status="draft",
    )
    session.add(version)
    session.commit()
    session.refresh(version)

    team1 = Team(event_id=event.id, name="Team1", seed=1)
    team2 = Team(event_id=event.id, name="Team2", seed=2)
    session.add(team1)
    session.add(team2)
    session.commit()
    session.refresh(team1)
    session.refresh(team2)

    upstream = Match(
        tournament_id=tournament.id,
        event_id=event.id,
        schedule_version_id=version.id,
        match_code="SF1",
        match_type="MAIN",
        round_number=1,
        round_index=1,
        sequence_in_round=1,
        duration_minutes=60,
        placeholder_side_a="A",
        placeholder_side_b="B",
        status="scheduled",
        team_a_id=team1.id,
        team_b_id=team2.id,
        runtime_status="SCHEDULED",
    )
    session.add(upstream)
    session.commit()
    session.refresh(upstream)

    downstream = Match(
        tournament_id=tournament.id,
        event_id=event.id,
        schedule_version_id=version.id,
        match_code="F1",
        match_type="MAIN",
        round_number=2,
        round_index=2,
        sequence_in_round=1,
        duration_minutes=60,
        placeholder_side_a="TBD",
        placeholder_side_b="TBD",
        status="scheduled",
        team_a_id=None,
        team_b_id=None,
        runtime_status="SCHEDULED",
        source_match_a_id=upstream.id,
        source_a_role="WINNER",
    )
    session.add(downstream)
    session.commit()
    session.refresh(downstream)

    return {
        "tournament_id": tournament.id,
        "upstream_id": upstream.id,
        "downstream_id": downstream.id,
        "version_id": version.id,
        "team1_id": team1.id,
    }


def test_finalizing_upstream_advances_downstream_team_slot(
    client: TestClient, session: Session, bracket_pair
):
    """Finalize upstream via PATCH; assert downstream.team_a_id is set to winner."""
    tid = bracket_pair["tournament_id"]
    upstream_id = bracket_pair["upstream_id"]
    downstream_id = bracket_pair["downstream_id"]
    team1_id = bracket_pair["team1_id"]

    resp = client.patch(
        f"/api/tournaments/{tid}/runtime/matches/{upstream_id}",
        json={"status": "FINAL", "winner_team_id": team1_id},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("match", {}).get("runtime_status") == "FINAL"
    assert data.get("advanced_count", 0) >= 1

    down = session.get(Match, downstream_id)
    assert down is not None
    assert down.team_a_id == team1_id


def test_advance_idempotent(client: TestClient, session: Session, bracket_pair):
    """Call advance endpoint twice; second call returns 0 (nothing to update)."""
    tid = bracket_pair["tournament_id"]
    upstream_id = bracket_pair["upstream_id"]
    team1_id = bracket_pair["team1_id"]

    client.patch(
        f"/api/tournaments/{tid}/runtime/matches/{upstream_id}",
        json={"status": "FINAL", "winner_team_id": team1_id},
    )

    r1 = client.post(f"/api/tournaments/{tid}/runtime/matches/{upstream_id}/advance")
    assert r1.status_code == 200
    c1 = r1.json().get("advanced_count", 0)

    r2 = client.post(f"/api/tournaments/{tid}/runtime/matches/{upstream_id}/advance")
    assert r2.status_code == 200
    c2 = r2.json().get("advanced_count", 0)
    assert c2 == 0


def test_advancement_isolation_by_version(client: TestClient, session: Session):
    """Downstream in another version is not updated when finalizing upstream in V1."""
    tournament = Tournament(
        name="Isolation Test",
        location="Test",
        timezone="America/New_York",
        start_date=date(2026, 1, 15),
        end_date=date(2026, 1, 17),
    )
    session.add(tournament)
    session.commit()
    session.refresh(tournament)

    event = Event(
        tournament_id=tournament.id,
        category="mixed",
        name="E",
        team_count=4,
        draw_plan_json="{}",
        draw_status="final",
    )
    session.add(event)
    session.commit()
    session.refresh(event)

    v1 = ScheduleVersion(tournament_id=tournament.id, version_number=1, notes="V1", status="draft")
    v2 = ScheduleVersion(tournament_id=tournament.id, version_number=2, notes="V2", status="draft")
    session.add(v1)
    session.add(v2)
    session.commit()
    session.refresh(v1)
    session.refresh(v2)

    t1 = Team(event_id=event.id, name="T1", seed=1)
    t2 = Team(event_id=event.id, name="T2", seed=2)
    session.add(t1)
    session.add(t2)
    session.commit()
    session.refresh(t1)
    session.refresh(t2)

    up1 = Match(
        tournament_id=tournament.id,
        event_id=event.id,
        schedule_version_id=v1.id,
        match_code="SF1",
        match_type="MAIN",
        round_number=1,
        round_index=1,
        sequence_in_round=1,
        duration_minutes=60,
        placeholder_side_a="A",
        placeholder_side_b="B",
        status="scheduled",
        team_a_id=t1.id,
        team_b_id=t2.id,
        runtime_status="SCHEDULED",
    )
    session.add(up1)
    session.commit()
    session.refresh(up1)

    down1 = Match(
        tournament_id=tournament.id,
        event_id=event.id,
        schedule_version_id=v1.id,
        match_code="F1",
        match_type="MAIN",
        round_number=2,
        round_index=2,
        sequence_in_round=1,
        duration_minutes=60,
        placeholder_side_a="TBD",
        placeholder_side_b="TBD",
        status="scheduled",
        team_a_id=None,
        team_b_id=None,
        runtime_status="SCHEDULED",
        source_match_a_id=up1.id,
        source_a_role="WINNER",
    )
    session.add(down1)
    session.commit()
    session.refresh(down1)

    up2 = Match(
        tournament_id=tournament.id,
        event_id=event.id,
        schedule_version_id=v2.id,
        match_code="SF1",
        match_type="MAIN",
        round_number=1,
        round_index=1,
        sequence_in_round=1,
        duration_minutes=60,
        placeholder_side_a="A",
        placeholder_side_b="B",
        status="scheduled",
        team_a_id=t1.id,
        team_b_id=t2.id,
        runtime_status="SCHEDULED",
    )
    session.add(up2)
    session.commit()
    session.refresh(up2)

    down2 = Match(
        tournament_id=tournament.id,
        event_id=event.id,
        schedule_version_id=v2.id,
        match_code="F1",
        match_type="MAIN",
        round_number=2,
        round_index=2,
        sequence_in_round=1,
        duration_minutes=60,
        placeholder_side_a="TBD",
        placeholder_side_b="TBD",
        status="scheduled",
        team_a_id=None,
        team_b_id=None,
        runtime_status="SCHEDULED",
        source_match_a_id=up2.id,
        source_a_role="WINNER",
    )
    session.add(down2)
    session.commit()
    session.refresh(down2)

    client.patch(
        f"/api/tournaments/{tournament.id}/runtime/matches/{up1.id}",
        json={"status": "FINAL", "winner_team_id": t1.id},
    )

    session.refresh(down1)
    session.refresh(down2)
    assert down1.team_a_id == t1.id
    assert down2.team_a_id is None
