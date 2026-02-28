"""Tests for SMS Phase 2: Send endpoints, log, settings, templates."""

import pytest
from datetime import datetime, timezone, date, time
from sqlmodel import Session, select

from app.models.sms_log import SmsLog
from app.models.sms_template import SmsTemplate, DEFAULT_SMS_TEMPLATES
from app.models.tournament_sms_settings import TournamentSmsSettings


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def setup_tournament_with_teams(session: Session):
    """
    Create a tournament with an event and 4 teams (2 with phones, 2 without).
    Returns (tournament, event, teams_list).
    """
    from app.models.tournament import Tournament
    from app.models.event import Event
    from app.models.team import Team

    tournament = Tournament(
        name="SMS Phase 2 Test",
        location="Test Location",
        timezone="America/New_York",
        start_date=date(2026, 3, 15),
        end_date=date(2026, 3, 16),
    )
    session.add(tournament)
    session.commit()
    session.refresh(tournament)

    event = Event(
        tournament_id=tournament.id,
        name="Mixed Doubles",
        category="mixed",
        team_count=4,
    )
    session.add(event)
    session.commit()
    session.refresh(event)

    teams = []
    # Team 1: both players have phones
    t1 = Team(
        event_id=event.id,
        name="Dee Dee / Mike",
        seed=1,
        p1_cell="9013593035",
        p1_email="p1@test.com",
        p2_cell="5551112222",
        p2_email="p2@test.com",
    )
    # Team 2: only P1 has phone
    t2 = Team(
        event_id=event.id,
        name="Yuki / Sal",
        seed=2,
        p1_cell="5553334444",
        p1_email="yuki@test.com",
        p2_cell=None,
        p2_email=None,
    )
    # Team 3: no phones at all
    t3 = Team(
        event_id=event.id,
        name="Tracey / Bob",
        seed=3,
        p1_cell=None,
        p1_email=None,
        p2_cell=None,
        p2_email=None,
    )
    # Team 4: dash placeholders (no real phone)
    t4 = Team(
        event_id=event.id,
        name="Cas / Lisa",
        seed=4,
        p1_cell="—",
        p1_email=None,
        p2_cell="—",
        p2_email=None,
    )

    for t in [t1, t2, t3, t4]:
        session.add(t)
    session.commit()
    for t in [t1, t2, t3, t4]:
        session.refresh(t)
    teams = [t1, t2, t3, t4]

    return tournament, event, teams


# ---------------------------------------------------------------------------
# Send endpoints
# ---------------------------------------------------------------------------


def test_blast_sends_to_all_teams(client, session, setup_tournament_with_teams):
    """Blast should send to all teams with phones, skip those without."""
    tournament, event, teams = setup_tournament_with_teams

    resp = client.post(
        f"/api/tournaments/{tournament.id}/sms/blast",
        json={"message": "Tournament starts in 1 hour!"},
    )
    assert resp.status_code == 200
    data = resp.json()

    # Team 1 has 2 phones, Team 2 has 1 phone = 3 total messages
    # Team 3 and 4 have no valid phones = 2 skipped
    assert data["sent"] == 3
    assert data["skipped_no_phone"] == 2
    assert data["message_type"] == "tournament_blast"
    assert len(data["results"]) == 3


def test_blast_empty_tournament(client, session):
    """Blast to tournament with no teams should 400."""
    from app.models.tournament import Tournament

    tournament = Tournament(
        name="Empty Tournament",
        location="Nowhere",
        timezone="UTC",
        start_date=date(2026, 3, 15),
        end_date=date(2026, 3, 16),
    )
    session.add(tournament)
    session.commit()
    session.refresh(tournament)

    resp = client.post(
        f"/api/tournaments/{tournament.id}/sms/blast",
        json={"message": "Hello?"},
    )
    assert resp.status_code == 400


def test_team_text(client, session, setup_tournament_with_teams):
    """Send text to a specific team."""
    tournament, event, teams = setup_tournament_with_teams
    team_with_phones = teams[0]  # Dee Dee / Mike — 2 phones

    resp = client.post(
        f"/api/tournaments/{tournament.id}/sms/team/{team_with_phones.id}",
        json={"message": "Your match is next!"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["sent"] == 2
    assert data["message_type"] == "team_direct"


def test_team_text_no_phone(client, session, setup_tournament_with_teams):
    """Send text to team without phones should 400."""
    tournament, event, teams = setup_tournament_with_teams
    team_no_phone = teams[2]  # Tracey / Bob — no phones

    resp = client.post(
        f"/api/tournaments/{tournament.id}/sms/team/{team_no_phone.id}",
        json={"message": "Test"},
    )
    assert resp.status_code == 400
    assert "no phone" in resp.json()["detail"].lower()


def test_team_text_404(client, session, setup_tournament_with_teams):
    """Send text to nonexistent team should 404."""
    tournament, _, _ = setup_tournament_with_teams
    resp = client.post(
        f"/api/tournaments/{tournament.id}/sms/team/99999",
        json={"message": "Test"},
    )
    assert resp.status_code == 404


def test_match_text(client, session, setup_tournament_with_teams):
    """Send text to both teams in a match."""
    tournament, event, teams = setup_tournament_with_teams
    from app.models.match import Match
    from app.models.schedule_version import ScheduleVersion

    version = ScheduleVersion(
        tournament_id=tournament.id, version_number=1, status="draft"
    )
    session.add(version)
    session.commit()
    session.refresh(version)

    match = Match(
        tournament_id=tournament.id,
        event_id=event.id,
        schedule_version_id=version.id,
        match_type="MAIN",
        round_number=1,
        round_index=1,
        sequence_in_round=1,
        duration_minutes=60,
        match_code="TEST_QF1",
        placeholder_side_a="Seed 1",
        placeholder_side_b="Seed 2",
        team_a_id=teams[0].id,
        team_b_id=teams[1].id,
    )
    session.add(match)
    session.commit()
    session.refresh(match)

    resp = client.post(
        f"/api/tournaments/{tournament.id}/sms/match/{match.id}",
        json={"message": "Your match starts in 15 minutes on Court A!"},
    )
    assert resp.status_code == 200
    data = resp.json()
    # Team 1: 2 phones + Team 2: 1 phone = 3 messages
    assert data["sent"] == 3
    assert data["message_type"] == "match_specific"


def test_match_text_no_teams_assigned(client, session, setup_tournament_with_teams):
    """Match with no teams assigned should 400."""
    tournament, event, teams = setup_tournament_with_teams
    from app.models.match import Match
    from app.models.schedule_version import ScheduleVersion

    version = ScheduleVersion(
        tournament_id=tournament.id, version_number=1, status="draft"
    )
    session.add(version)
    session.commit()
    session.refresh(version)

    match = Match(
        tournament_id=tournament.id,
        event_id=event.id,
        schedule_version_id=version.id,
        match_type="MAIN",
        round_number=2,
        round_index=2,
        sequence_in_round=1,
        duration_minutes=60,
        match_code="TEST_SF1",
        placeholder_side_a="Winner QF1",
        placeholder_side_b="Winner QF2",
        team_a_id=None,
        team_b_id=None,
    )
    session.add(match)
    session.commit()
    session.refresh(match)

    resp = client.post(
        f"/api/tournaments/{tournament.id}/sms/match/{match.id}",
        json={"message": "Test"},
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Preview endpoint
# ---------------------------------------------------------------------------


def test_preview_blast(client, session, setup_tournament_with_teams):
    """Preview should show recipients without sending."""
    tournament, event, teams = setup_tournament_with_teams

    resp = client.post(
        f"/api/tournaments/{tournament.id}/sms/preview/blast",
        json={"message": "Preview test"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_teams"] == 4
    assert data["total_messages"] == 3  # 2 from team1 + 1 from team2
    assert data["teams_without_phone"] == 2  # team3 + team4
    assert len(data["recipients"]) == 2

    # Verify no SMS log entries were created (preview = no send)
    logs = session.exec(
        select(SmsLog).where(SmsLog.tournament_id == tournament.id)
    ).all()
    assert len(logs) == 0


# ---------------------------------------------------------------------------
# SMS Log
# ---------------------------------------------------------------------------


def test_sms_log_after_send(client, session, setup_tournament_with_teams):
    """Sending texts should create log entries."""
    tournament, event, teams = setup_tournament_with_teams

    # Send a blast
    client.post(
        f"/api/tournaments/{tournament.id}/sms/blast",
        json={"message": "Log test"},
    )

    # Check log
    resp = client.get(f"/api/tournaments/{tournament.id}/sms/log")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 3  # 3 messages sent
    assert all(entry["message_type"] == "tournament_blast" for entry in data)
    assert all(entry["trigger"] == "manual" for entry in data)


def test_sms_log_filter_by_type(client, session, setup_tournament_with_teams):
    """Log should be filterable by message_type."""
    tournament, event, teams = setup_tournament_with_teams

    # Send blast + team text
    client.post(
        f"/api/tournaments/{tournament.id}/sms/blast",
        json={"message": "Blast"},
    )
    client.post(
        f"/api/tournaments/{tournament.id}/sms/team/{teams[0].id}",
        json={"message": "Direct"},
    )

    # Filter by team_direct
    resp = client.get(
        f"/api/tournaments/{tournament.id}/sms/log",
        params={"message_type": "team_direct"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert all(entry["message_type"] == "team_direct" for entry in data)


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


def test_settings_defaults(client, session, setup_tournament_with_teams):
    """GET settings should return defaults when none exist."""
    tournament, _, _ = setup_tournament_with_teams

    resp = client.get(f"/api/tournaments/{tournament.id}/sms/settings")
    assert resp.status_code == 200
    data = resp.json()
    assert data["auto_first_match"] is False
    assert data["auto_court_change"] is True  # Default ON


def test_settings_update(client, session, setup_tournament_with_teams):
    """PATCH settings should update only provided fields."""
    tournament, _, _ = setup_tournament_with_teams

    resp = client.patch(
        f"/api/tournaments/{tournament.id}/sms/settings",
        json={"auto_first_match": True, "auto_on_deck": True},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["auto_first_match"] is True
    assert data["auto_on_deck"] is True
    assert data["auto_post_match_next"] is False  # Not changed
    assert data["auto_court_change"] is True  # Default preserved


def test_settings_persist(client, session, setup_tournament_with_teams):
    """Settings should persist across requests."""
    tournament, _, _ = setup_tournament_with_teams

    # Set first_match on
    client.patch(
        f"/api/tournaments/{tournament.id}/sms/settings",
        json={"auto_first_match": True},
    )

    # Read back
    resp = client.get(f"/api/tournaments/{tournament.id}/sms/settings")
    data = resp.json()
    assert data["auto_first_match"] is True


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------


def test_templates_defaults(client, session, setup_tournament_with_teams):
    """GET templates should return defaults when none customized."""
    tournament, _, _ = setup_tournament_with_teams

    resp = client.get(f"/api/tournaments/{tournament.id}/sms/templates")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == len(DEFAULT_SMS_TEMPLATES)
    types = [t["message_type"] for t in data]
    assert "first_match" in types
    assert "on_deck" in types


def test_template_update(client, session, setup_tournament_with_teams):
    """PUT template should create/update a custom template."""
    tournament, _, _ = setup_tournament_with_teams

    custom_body = "HEY {team_name}! Get to {court} NOW!"
    resp = client.put(
        f"/api/tournaments/{tournament.id}/sms/templates/on_deck",
        json={"template_body": custom_body},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["message_type"] == "on_deck"
    assert data["template_body"] == custom_body
    assert data["is_active"] is True


def test_template_invalid_type(client, session, setup_tournament_with_teams):
    """PUT with invalid message_type should 400."""
    tournament, _, _ = setup_tournament_with_teams

    resp = client.put(
        f"/api/tournaments/{tournament.id}/sms/templates/invalid_type",
        json={"template_body": "test"},
    )
    assert resp.status_code == 400


def test_templates_reset(client, session, setup_tournament_with_teams):
    """Reset should delete custom templates."""
    tournament, _, _ = setup_tournament_with_teams

    # Create custom template
    client.put(
        f"/api/tournaments/{tournament.id}/sms/templates/on_deck",
        json={"template_body": "custom"},
    )

    # Reset
    resp = client.post(f"/api/tournaments/{tournament.id}/sms/templates/reset")
    assert resp.status_code == 200
    assert resp.json()["deleted"] == 1

    # Verify defaults returned
    resp = client.get(f"/api/tournaments/{tournament.id}/sms/templates")
    data = resp.json()
    on_deck = [t for t in data if t["message_type"] == "on_deck"][0]
    assert on_deck["id"] == 0  # Default (not persisted)


# ---------------------------------------------------------------------------
# Status endpoint
# ---------------------------------------------------------------------------


def test_sms_status(client, session, setup_tournament_with_teams):
    """Status should report config and team phone coverage."""
    tournament, _, _ = setup_tournament_with_teams

    resp = client.get(f"/api/tournaments/{tournament.id}/sms/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_teams"] == 4
    assert data["teams_with_phones"] == 2  # team1 and team2
    assert data["twilio_configured"] is False  # No env vars in test
