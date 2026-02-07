"""
Regression test: Schedule Builder must reflect draw_plan_json exactly.

This ensures that when an event is finalized with a specific template/team_count/wf_rounds,
Schedule Builder shows the exact same values (not stale defaults).
"""
import pytest
from datetime import date
from sqlmodel import Session

from app.models.event import Event
from app.models.tournament import Tournament
from app.routes.schedule_builder import get_schedule_builder


def test_schedule_builder_reflects_rr_only_for_8_teams(session: Session):
    """8-team event with RR_ONLY should show RR_ONLY in Schedule Builder."""
    # Create tournament
    tournament = Tournament(
        name="Test Tournament",
        location="Test Location",
        timezone="America/New_York",
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 3),
    )
    session.add(tournament)
    session.commit()
    session.refresh(tournament)

    # Create event with 8 teams and RR_ONLY template
    event = Event(
        tournament_id=tournament.id,
        name="Test Event",
        category="mixed",
        team_count=8,
        draw_plan_json='{"version":"1.0","template_type":"RR_ONLY","wf_rounds":0}',
        draw_status="final",
        guarantee_selected=5,
        wf_block_minutes=60,
        standard_block_minutes=105,
    )
    session.add(event)
    session.commit()
    session.refresh(event)

    # Call Schedule Builder
    response = get_schedule_builder(tournament.id, session)

    # Find our event
    event_data = next((e for e in response["events"] if e["event_id"] == event.id), None)
    assert event_data is not None, "Event should appear in Schedule Builder"

    # Assert template matches what was stored
    assert event_data["template_type"] == "RR_ONLY", f"Expected RR_ONLY, got {event_data['template_type']}"
    assert event_data["template_key"] == "RR_ONLY", f"Expected RR_ONLY, got {event_data['template_key']}"
    assert event_data["team_count"] == 8, f"Expected team_count=8, got {event_data['team_count']}"
    assert event_data["waterfall_rounds"] == 0, f"Expected wf_rounds=0, got {event_data['waterfall_rounds']}"
    assert "error" not in event_data, f"Event should have no errors, got: {event_data.get('error')}"


def test_schedule_builder_reflects_wf_to_brackets_8_for_12_teams(session: Session):
    """12-team event with WF_TO_BRACKETS_8 should show WF_TO_BRACKETS_8 in Schedule Builder."""
    # Create tournament
    tournament = Tournament(
        name="Test Tournament",
        location="Test Location",
        timezone="America/New_York",
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 3),
    )
    session.add(tournament)
    session.commit()
    session.refresh(tournament)

    # Create event with 12 teams and WF_TO_BRACKETS_8 template
    event = Event(
        tournament_id=tournament.id,
        name="Test Event",
        category="womens",
        team_count=12,
        draw_plan_json='{"version":"1.0","template_type":"WF_TO_BRACKETS_8","wf_rounds":2}',
        draw_status="final",
        guarantee_selected=5,
        wf_block_minutes=60,
        standard_block_minutes=105,
    )
    session.add(event)
    session.commit()
    session.refresh(event)

    # Call Schedule Builder
    response = get_schedule_builder(tournament.id, session)

    # Find our event
    event_data = next((e for e in response["events"] if e["event_id"] == event.id), None)
    assert event_data is not None, "Event should appear in Schedule Builder"

    # Assert template matches what was stored (NOT WF_TO_POOLS_4)
    assert event_data["template_type"] == "WF_TO_BRACKETS_8", f"Expected WF_TO_BRACKETS_8, got {event_data['template_type']}"
    assert event_data["template_key"] == "WF_TO_BRACKETS_8", f"Expected WF_TO_BRACKETS_8, got {event_data['template_key']}"
    assert event_data["team_count"] == 12, f"Expected team_count=12, got {event_data['team_count']}"
    assert event_data["waterfall_rounds"] == 2, f"Expected wf_rounds=2, got {event_data['waterfall_rounds']}"
    assert "error" not in event_data, f"Event should have no errors, got: {event_data.get('error')}"


def test_schedule_builder_rejects_wf_to_pools_4_for_8_teams(session: Session):
    """8-team event with WF_TO_POOLS_4 should show error (invalid combination)."""
    # Create tournament
    tournament = Tournament(
        name="Test Tournament",
        location="Test Location",
        timezone="America/New_York",
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 3),
    )
    session.add(tournament)
    session.commit()
    session.refresh(tournament)

    # Create event with 8 teams but WF_TO_POOLS_4 template (invalid)
    event = Event(
        tournament_id=tournament.id,
        name="Test Event",
        category="mixed",
        team_count=8,
        draw_plan_json='{"version":"1.0","template_type":"WF_TO_POOLS_4","wf_rounds":2}',
        draw_status="final",
        guarantee_selected=5,
        wf_block_minutes=60,
        standard_block_minutes=105,
    )
    session.add(event)
    session.commit()
    session.refresh(event)

    # Call Schedule Builder
    response = get_schedule_builder(tournament.id, session)

    # Find our event
    event_data = next((e for e in response["events"] if e["event_id"] == event.id), None)
    assert event_data is not None, "Event should appear in Schedule Builder"

    # Assert error is shown (WF_TO_POOLS_4 requires team_count divisible by 4)
    assert "error" in event_data, "Event should have error for invalid template/team_count combination"
    assert "divisible by 4" in event_data["error"].lower() or "WF_TO_POOLS_4" in event_data["error"], \
        f"Error should mention WF_TO_POOLS_4 constraint, got: {event_data.get('error')}"
