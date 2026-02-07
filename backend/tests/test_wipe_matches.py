"""
Tests for wipe matches endpoint.
"""
from datetime import date, time

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.models.event import Event
from app.models.match import Match
from app.models.match_assignment import MatchAssignment
from app.models.schedule_version import ScheduleVersion
from app.models.tournament import Tournament


def test_wipe_matches_deletes_all_matches(client: TestClient, session: Session):
    """Test that wipe endpoint deletes all matches for a version."""
    # Create tournament and version
    tournament = Tournament(
        name="Test Tournament",
        location="Test Location",
        timezone="America/New_York",
        start_date=date(2026, 1, 15),
        end_date=date(2026, 1, 17),
        use_time_windows=False,
    )
    session.add(tournament)
    session.commit()
    session.refresh(tournament)

    version = ScheduleVersion(tournament_id=tournament.id, version_number=1, status="draft")
    session.add(version)
    session.commit()
    session.refresh(version)

    # Create event
    event = Event(
        tournament_id=tournament.id,
        category="mixed",
        name="Test Event",
        team_count=8,
        guarantee_selected=5,
        draw_status="final",
    )
    event.draw_plan_json = '{"template_type": "WF_TO_BRACKETS_8", "wf_rounds": 2}'
    session.add(event)
    session.commit()
    session.refresh(event)

    # Create some dummy matches
    match1 = Match(
        tournament_id=tournament.id,
        event_id=event.id,
        schedule_version_id=version.id,
        match_code=f"TEST_E{event.id}_WF_R1_01",
        match_type="WF",
        round_number=1,
        round_index=1,
        sequence_in_round=1,
        placeholder_side_a="Team A",
        placeholder_side_b="Team B",
        duration_minutes=60,
    )
    match2 = Match(
        tournament_id=tournament.id,
        event_id=event.id,
        schedule_version_id=version.id,
        match_code=f"TEST_E{event.id}_BWW_M1",
        match_type="MAIN",
        round_number=1,
        round_index=1,
        sequence_in_round=1,
        placeholder_side_a="Team C",
        placeholder_side_b="Team D",
        duration_minutes=105,
    )
    session.add(match1)
    session.add(match2)
    session.commit()

    # Verify matches exist
    matches_before = session.exec(
        select(Match).where(Match.schedule_version_id == version.id)
    ).all()
    assert len(matches_before) == 2

    # Call wipe endpoint
    response = client.delete(
        f"/api/tournaments/{tournament.id}/schedule/versions/{version.id}/matches"
    )

    assert response.status_code == 200
    data = response.json()
    assert data["deleted_matches"] == 2

    # Verify matches are deleted
    matches_after = session.exec(
        select(Match).where(Match.schedule_version_id == version.id)
    ).all()
    assert len(matches_after) == 0

    # Verify preview returns empty
    preview_response = client.get(
        f"/api/tournaments/{tournament.id}/schedule/versions/{version.id}/matches/preview"
    )
    assert preview_response.status_code == 200
    preview_data = preview_response.json()
    assert len(preview_data["matches"]) == 0


def test_wipe_matches_refuses_finalized_version(client: TestClient, session: Session):
    """Test that wipe endpoint refuses to delete matches for finalized version."""
    # Create tournament and finalized version
    tournament = Tournament(
        name="Test Tournament",
        location="Test Location",
        timezone="America/New_York",
        start_date=date(2026, 1, 15),
        end_date=date(2026, 1, 17),
        use_time_windows=False,
    )
    session.add(tournament)
    session.commit()
    session.refresh(tournament)

    version = ScheduleVersion(
        tournament_id=tournament.id,
        version_number=1,
        status="final",
    )
    session.add(version)
    session.commit()
    session.refresh(version)

    # Try to wipe matches
    response = client.delete(
        f"/api/tournaments/{tournament.id}/schedule/versions/{version.id}/matches"
    )

    assert response.status_code == 409
    assert "finalized" in response.json()["detail"].lower()


def test_wipe_matches_404_for_wrong_tournament(client: TestClient, session: Session):
    """Test that wipe endpoint returns 404 if version belongs to different tournament."""
    # Create two tournaments
    tournament1 = Tournament(
        name="Tournament 1",
        location="Location 1",
        timezone="America/New_York",
        start_date=date(2026, 1, 15),
        end_date=date(2026, 1, 17),
        use_time_windows=False,
    )
    tournament2 = Tournament(
        name="Tournament 2",
        location="Location 2",
        timezone="America/New_York",
        start_date=date(2026, 1, 15),
        end_date=date(2026, 1, 17),
        use_time_windows=False,
    )
    session.add(tournament1)
    session.add(tournament2)
    session.commit()
    session.refresh(tournament1)
    session.refresh(tournament2)

    version = ScheduleVersion(tournament_id=tournament1.id, version_number=1, status="draft")
    session.add(version)
    session.commit()
    session.refresh(version)

    # Try to wipe using wrong tournament ID
    response = client.delete(
        f"/api/tournaments/{tournament2.id}/schedule/versions/{version.id}/matches"
    )

    assert response.status_code == 404


def test_wipe_matches_deletes_assignments_too(client: TestClient, session: Session):
    """Test that wipe endpoint also deletes match assignments."""
    # Create tournament and version
    tournament = Tournament(
        name="Test Tournament",
        location="Test Location",
        timezone="America/New_York",
        start_date=date(2026, 1, 15),
        end_date=date(2026, 1, 17),
        use_time_windows=False,
    )
    session.add(tournament)
    session.commit()
    session.refresh(tournament)

    version = ScheduleVersion(tournament_id=tournament.id, version_number=1, status="draft")
    session.add(version)
    session.commit()
    session.refresh(version)

    # Create event
    event = Event(
        tournament_id=tournament.id,
        category="mixed",
        name="Test Event",
        team_count=8,
        guarantee_selected=5,
        draw_status="final",
    )
    session.add(event)
    session.commit()
    session.refresh(event)

    # Create match
    match = Match(
        tournament_id=tournament.id,
        event_id=event.id,
        schedule_version_id=version.id,
        match_code=f"TEST_E{event.id}_M1",
        match_type="MAIN",
        round_number=1,
        round_index=1,
        sequence_in_round=1,
        placeholder_side_a="Team A",
        placeholder_side_b="Team B",
        duration_minutes=105,
    )
    session.add(match)
    session.commit()
    session.refresh(match)

    # Create assignment (if slot exists, otherwise skip assignment test)
    from app.models.schedule_slot import ScheduleSlot

    slot = ScheduleSlot(
        tournament_id=tournament.id,
        schedule_version_id=version.id,
        event_id=event.id,
        day_date=date(2026, 1, 15),
        start_time=time(10, 0, 0),
        end_time=time(11, 45, 0),
        court_number=1,
        court_label="Court 1",
        block_minutes=105,
    )
    session.add(slot)
    session.commit()
    session.refresh(slot)

    assignment = MatchAssignment(
        tournament_id=tournament.id,
        schedule_version_id=version.id,
        match_id=match.id,
        slot_id=slot.id,
    )
    session.add(assignment)
    session.commit()

    # Verify assignment exists
    assignments_before = session.exec(
        select(MatchAssignment).where(MatchAssignment.schedule_version_id == version.id)
    ).all()
    assert len(assignments_before) == 1

    # Call wipe endpoint
    response = client.delete(
        f"/api/tournaments/{tournament.id}/schedule/versions/{version.id}/matches"
    )

    assert response.status_code == 200

    # Verify assignments are also deleted
    assignments_after = session.exec(
        select(MatchAssignment).where(MatchAssignment.schedule_version_id == version.id)
    ).all()
    assert len(assignments_after) == 0
