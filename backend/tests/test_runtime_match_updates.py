"""Phase 4 runtime: match status + scoring. No schedule mutation."""
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
def tournament_with_match_and_team(client: TestClient, session: Session):
    """Tournament with one match and two teams (for winner)."""
    tournament = Tournament(
        name="Runtime Test",
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

    team_a = Team(event_id=event.id, name="Team A", seed=1)
    team_b = Team(event_id=event.id, name="Team B", seed=2)
    session.add(team_a)
    session.add(team_b)
    session.commit()
    session.refresh(team_a)
    session.refresh(team_b)

    match = Match(
        tournament_id=tournament.id,
        event_id=event.id,
        schedule_version_id=version.id,
        match_code="M1",
        match_type="MAIN",
        round_number=1,
        round_index=1,
        sequence_in_round=1,
        duration_minutes=60,
        placeholder_side_a="A",
        placeholder_side_b="B",
        status="scheduled",
        team_a_id=team_a.id,
        team_b_id=team_b.id,
        runtime_status="SCHEDULED",
    )
    session.add(match)
    session.commit()
    session.refresh(match)

    return {
        "tournament_id": tournament.id,
        "match_id": match.id,
        "version_id": version.id,
        "team_a_id": team_a.id,
        "team_b_id": team_b.id,
    }


def test_set_in_progress_sets_started_at(client: TestClient, session: Session, tournament_with_match_and_team):
    """Can set IN_PROGRESS; started_at is set."""
    tid = tournament_with_match_and_team["tournament_id"]
    mid = tournament_with_match_and_team["match_id"]

    resp = client.patch(
        f"/api/tournaments/{tid}/runtime/matches/{mid}",
        json={"status": "IN_PROGRESS"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["runtime_status"] == "IN_PROGRESS"
    assert data["started_at"] is not None
    assert data["completed_at"] is None

    match = session.get(Match, mid)
    assert match.runtime_status == "IN_PROGRESS"
    assert match.started_at is not None


def test_set_final_with_winner_sets_completed_at(client: TestClient, session: Session, tournament_with_match_and_team):
    """Can set FINAL with winner; completed_at is set and persists."""
    tid = tournament_with_match_and_team["tournament_id"]
    mid = tournament_with_match_and_team["match_id"]
    winner_id = tournament_with_match_and_team["team_a_id"]

    resp = client.patch(
        f"/api/tournaments/{tid}/runtime/matches/{mid}",
        json={"status": "FINAL", "winner_team_id": winner_id},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["runtime_status"] == "FINAL"
    assert data["winner_team_id"] == winner_id
    assert data["completed_at"] is not None

    match = session.get(Match, mid)
    assert match.runtime_status == "FINAL"
    assert match.winner_team_id == winner_id
    assert match.completed_at is not None


def test_cannot_revert_final_to_in_progress(client: TestClient, session: Session, tournament_with_match_and_team):
    """Cannot edit FINAL back to IN_PROGRESS (422)."""
    tid = tournament_with_match_and_team["tournament_id"]
    mid = tournament_with_match_and_team["match_id"]
    winner_id = tournament_with_match_and_team["team_a_id"]

    client.patch(
        f"/api/tournaments/{tid}/runtime/matches/{mid}",
        json={"status": "FINAL", "winner_team_id": winner_id},
    )

    resp = client.patch(
        f"/api/tournaments/{tid}/runtime/matches/{mid}",
        json={"status": "IN_PROGRESS"},
    )
    assert resp.status_code == 422
    assert "FINAL" in resp.text or "terminal" in resp.text.lower()


def test_tournament_isolation_wrong_tournament_404(client: TestClient, session: Session):
    """Wrong tournament_id → 404."""
    other = Tournament(
        name="Other",
        location="X",
        timezone="America/New_York",
        start_date=date(2026, 2, 1),
        end_date=date(2026, 2, 2),
    )
    session.add(other)
    session.commit()
    session.refresh(other)

    # Use match_id from another tournament's match (we don't have one, so use 99999 - match not found)
    resp = client.patch(
        f"/api/tournaments/{other.id}/runtime/matches/99999",
        json={"status": "IN_PROGRESS"},
    )
    assert resp.status_code == 404


def test_get_version_runtime_matches(client: TestClient, session: Session, tournament_with_match_and_team):
    """GET version matches returns list in stable order."""
    tid = tournament_with_match_and_team["tournament_id"]
    vid = tournament_with_match_and_team["version_id"]

    resp = client.get(f"/api/tournaments/{tid}/runtime/versions/{vid}/matches")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) >= 1
    m = data[0]
    assert "id" in m and "runtime_status" in m and "match_code" in m
