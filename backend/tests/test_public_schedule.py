"""
Phase B — Public Schedule Page tests.

Validates:
- Unpublished tournament returns NOT_PUBLISHED
- Published version returns matches with correct shape
- event_id filter works
- day filter works
- search filter returns correct subset
- search is case-insensitive
"""

from datetime import date, time

import pytest
from sqlmodel import Session

from app.models.event import Event
from app.models.match import Match
from app.models.match_assignment import MatchAssignment
from app.models.schedule_slot import ScheduleSlot
from app.models.schedule_version import ScheduleVersion
from app.models.team import Team
from app.models.tournament import Tournament


def _setup_published_tournament(session: Session):
    """Create a published tournament with matches, slots, assignments, teams."""
    t = Tournament(
        name="Beach Classic",
        location="Virginia Beach",
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

    ev1 = Event(
        tournament_id=t.id,
        category="womens",
        name="Women's A",
        team_count=16,
    )
    ev2 = Event(
        tournament_id=t.id,
        category="mixed",
        name="Mixed A",
        team_count=16,
    )
    session.add_all([ev1, ev2])
    session.flush()

    team_a = Team(event_id=ev1.id, name="Smith / Johnson - VA", seed=1, display_name="Smith / Johnson")
    team_b = Team(event_id=ev1.id, name="Davis / Brown - NC", seed=2, display_name="Davis / Brown")
    team_c = Team(event_id=ev2.id, name="Wilson / Lee - FL", seed=1, display_name="Wilson / Lee")
    team_d = Team(event_id=ev2.id, name="Garcia / Chen - TX", seed=2, display_name="Garcia / Chen")
    session.add_all([team_a, team_b, team_c, team_d])
    session.flush()

    m1 = Match(
        tournament_id=t.id,
        event_id=ev1.id,
        schedule_version_id=v.id,
        match_code="WOM_WOM_E1_WF_R1_M01",
        match_type="WF",
        round_number=1,
        round_index=1,
        sequence_in_round=1,
        duration_minutes=60,
        team_a_id=team_a.id,
        team_b_id=team_b.id,
        placeholder_side_a="Seed 1",
        placeholder_side_b="Seed 2",
    )
    m2 = Match(
        tournament_id=t.id,
        event_id=ev2.id,
        schedule_version_id=v.id,
        match_code="MIX_MIX_E2_WF_R1_M01",
        match_type="WF",
        round_number=1,
        round_index=1,
        sequence_in_round=1,
        duration_minutes=60,
        team_a_id=team_c.id,
        team_b_id=team_d.id,
        placeholder_side_a="Seed 1",
        placeholder_side_b="Seed 2",
    )
    session.add_all([m1, m2])
    session.flush()

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
        day_date=date(2026, 6, 6),
        start_time=time(13, 15),
        end_time=time(14, 15),
        court_number=2,
        court_label="2",
        block_minutes=60,
    )
    session.add_all([slot1, slot2])
    session.flush()

    a1 = MatchAssignment(
        schedule_version_id=v.id,
        match_id=m1.id,
        slot_id=slot1.id,
    )
    a2 = MatchAssignment(
        schedule_version_id=v.id,
        match_id=m2.id,
        slot_id=slot2.id,
    )
    session.add_all([a1, a2])
    session.flush()

    # Publish
    t.public_schedule_version_id = v.id
    session.add(t)
    session.commit()

    return t, v, ev1, ev2, m1, m2


def test_unpublished_returns_not_published(client, session):
    """Schedule endpoint returns NOT_PUBLISHED when no pointer set."""
    t = Tournament(
        name="Unpub Tourney",
        location="Nowhere",
        timezone="America/New_York",
        start_date=date(2026, 6, 1),
        end_date=date(2026, 6, 3),
    )
    session.add(t)
    session.commit()

    resp = client.get(f"/api/public/tournaments/{t.id}/schedule")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "NOT_PUBLISHED"
    assert "message" in body


def test_published_returns_matches(client, session):
    """Published version returns matches with correct response shape."""
    t, v, ev1, ev2, m1, m2 = _setup_published_tournament(session)

    resp = client.get(f"/api/public/tournaments/{t.id}/schedule")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "OK"
    assert body["tournament_name"] == "Beach Classic"
    assert body["published_version_id"] == v.id
    assert len(body["matches"]) == 2

    match_item = body["matches"][0]
    assert "match_id" in match_item
    assert "match_number" in match_item
    assert "stage" in match_item
    assert "event_name" in match_item
    assert "day_index" in match_item
    assert "day_label" in match_item
    assert "team1_display" in match_item
    assert "team2_display" in match_item
    assert "team1_full_name" in match_item
    assert "team2_full_name" in match_item
    assert "status" in match_item

    assert len(body["events"]) == 2
    assert len(body["days"]) == 2


def test_event_id_filter(client, session):
    """event_id filter returns only matches from that event."""
    t, v, ev1, ev2, m1, m2 = _setup_published_tournament(session)

    resp = client.get(f"/api/public/tournaments/{t.id}/schedule?event_id={ev1.id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "OK"
    assert len(body["matches"]) == 1
    assert body["matches"][0]["event_name"] == "Women's A"

    # Filter options should still show all events (unfiltered)
    assert len(body["events"]) == 2


def test_day_filter(client, session):
    """day filter returns only matches from that day_index."""
    t, v, ev1, ev2, m1, m2 = _setup_published_tournament(session)

    resp = client.get(f"/api/public/tournaments/{t.id}/schedule?day=1")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "OK"
    assert len(body["matches"]) == 1
    assert body["matches"][0]["day_index"] == 1


def test_search_filter(client, session):
    """search filter returns matches where team name contains search term."""
    t, v, ev1, ev2, m1, m2 = _setup_published_tournament(session)

    resp = client.get(f"/api/public/tournaments/{t.id}/schedule?search=Smith")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "OK"
    assert len(body["matches"]) == 1
    assert "Smith" in body["matches"][0]["team1_display"] or "Smith" in body["matches"][0]["team1_full_name"]


def test_search_case_insensitive(client, session):
    """search is case-insensitive."""
    t, v, ev1, ev2, m1, m2 = _setup_published_tournament(session)

    resp_upper = client.get(f"/api/public/tournaments/{t.id}/schedule?search=GARCIA")
    resp_lower = client.get(f"/api/public/tournaments/{t.id}/schedule?search=garcia")

    assert resp_upper.status_code == 200
    assert resp_lower.status_code == 200

    body_upper = resp_upper.json()
    body_lower = resp_lower.json()

    assert len(body_upper["matches"]) == 1
    assert len(body_lower["matches"]) == 1
    assert body_upper["matches"][0]["match_id"] == body_lower["matches"][0]["match_id"]
