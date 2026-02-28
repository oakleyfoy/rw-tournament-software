"""Tests for SMS Phase 1: Data Models + Twilio Service."""

import pytest
from datetime import datetime, timezone
from sqlmodel import Session, select
from types import SimpleNamespace

from app.models.sms_log import SmsLog
from app.models.sms_template import SmsTemplate, DEFAULT_SMS_TEMPLATES
from app.models.tournament_sms_settings import TournamentSmsSettings
from app.services.twilio_service import (
    format_e164,
    validate_e164,
    get_team_phone_numbers,
)


# ---------------------------------------------------------------------------
# Phone number formatting tests
# ---------------------------------------------------------------------------


class TestFormatE164:
    """Test phone number formatting to E.164."""

    def test_ten_digit_us(self):
        assert format_e164("5551234567") == "+15551234567"

    def test_war_format(self):
        """Phone numbers as they appear in WAR Tournaments (e.g. 9013593035)."""
        assert format_e164("9013593035") == "+19013593035"

    def test_eleven_digit_us(self):
        assert format_e164("15551234567") == "+15551234567"

    def test_already_e164(self):
        assert format_e164("+15551234567") == "+15551234567"

    def test_dashes(self):
        assert format_e164("555-123-4567") == "+15551234567"

    def test_dots(self):
        assert format_e164("555.123.4567") == "+15551234567"

    def test_parens(self):
        assert format_e164("(555) 123-4567") == "+15551234567"

    def test_spaces(self):
        assert format_e164("555 123 4567") == "+15551234567"

    def test_invalid_short(self):
        with pytest.raises(ValueError, match="Cannot parse"):
            format_e164("12345")

    def test_invalid_empty(self):
        with pytest.raises(ValueError, match="empty"):
            format_e164("")

    def test_invalid_none_string(self):
        with pytest.raises(ValueError, match="empty"):
            format_e164("   ")


class TestValidateE164:
    """Test E.164 validation."""

    def test_valid_us(self):
        assert validate_e164("+15551234567") is True

    def test_valid_uk(self):
        assert validate_e164("+447911123456") is True

    def test_missing_plus(self):
        assert validate_e164("15551234567") is False

    def test_too_short(self):
        assert validate_e164("+1234") is False

    def test_not_a_number(self):
        assert validate_e164("+abcdefghij") is False


# ---------------------------------------------------------------------------
# get_team_phone_numbers tests
# ---------------------------------------------------------------------------


class TestGetTeamPhoneNumbers:
    """Test extracting phone numbers from Team objects."""

    def _make_team(self, p1_cell=None, p2_cell=None, team_id=1):
        """Create a fake team object with phone fields."""
        return SimpleNamespace(id=team_id, p1_cell=p1_cell, p2_cell=p2_cell)

    def test_both_players(self):
        team = self._make_team(p1_cell="9013593035", p2_cell="5551234567")
        phones = get_team_phone_numbers(team)
        assert phones == ["+19013593035", "+15551234567"]

    def test_p1_only(self):
        team = self._make_team(p1_cell="9013593035", p2_cell=None)
        phones = get_team_phone_numbers(team)
        assert phones == ["+19013593035"]

    def test_p2_only(self):
        team = self._make_team(p1_cell=None, p2_cell="5551234567")
        phones = get_team_phone_numbers(team)
        assert phones == ["+15551234567"]

    def test_no_phones(self):
        team = self._make_team(p1_cell=None, p2_cell=None)
        phones = get_team_phone_numbers(team)
        assert phones == []

    def test_blank_strings(self):
        team = self._make_team(p1_cell="", p2_cell="   ")
        phones = get_team_phone_numbers(team)
        assert phones == []

    def test_dash_placeholder(self):
        """WAR Tournaments shows '—' for empty cells."""
        team = self._make_team(p1_cell="9013593035", p2_cell="—")
        phones = get_team_phone_numbers(team)
        assert phones == ["+19013593035"]

    def test_deduplication(self):
        """Same number for P1 and P2 should only appear once."""
        team = self._make_team(p1_cell="9013593035", p2_cell="9013593035")
        phones = get_team_phone_numbers(team)
        assert phones == ["+19013593035"]

    def test_invalid_number_skipped(self):
        """Invalid numbers should be skipped, not crash."""
        team = self._make_team(p1_cell="9013593035", p2_cell="123")
        phones = get_team_phone_numbers(team)
        assert phones == ["+19013593035"]


# ---------------------------------------------------------------------------
# Model CRUD tests (require database fixture)
# ---------------------------------------------------------------------------


@pytest.fixture
def setup_tournament(session: Session):
    """Create a tournament for FK references."""
    from datetime import date
    from app.models.tournament import Tournament

    tournament = Tournament(
        name="SMS Test Tournament",
        location="Test Venue",
        timezone="America/Chicago",
        start_date=date(2026, 3, 1),
        end_date=date(2026, 3, 2),
    )
    session.add(tournament)
    session.commit()
    session.refresh(tournament)
    return tournament


def test_sms_log_crud(session: Session, setup_tournament):
    """Test creating an SMS log entry."""
    tournament = setup_tournament

    log = SmsLog(
        tournament_id=tournament.id,
        phone_number="+19013593035",
        message_body="Your first match is tomorrow at 10 AM on Court A.",
        message_type="first_match",
        twilio_sid="SM1234567890abcdef",
        status="sent",
        trigger="auto",
    )
    session.add(log)
    session.commit()
    session.refresh(log)

    assert log.id is not None
    assert log.tournament_id == tournament.id
    assert log.message_type == "first_match"
    assert log.trigger == "auto"

    # Query back
    logs = session.exec(
        select(SmsLog).where(SmsLog.tournament_id == tournament.id)
    ).all()
    assert len(logs) == 1


def test_sms_log_without_team(session: Session, setup_tournament):
    """SMS log works without a team_id (tournament blast)."""
    tournament = setup_tournament

    log = SmsLog(
        tournament_id=tournament.id,
        team_id=None,
        phone_number="+19013593035",
        message_body="Tournament starts in 1 hour!",
        message_type="tournament_blast",
        status="sent",
        trigger="manual",
    )
    session.add(log)
    session.commit()
    assert log.id is not None
    assert log.team_id is None


def test_sms_template_crud(session: Session, setup_tournament):
    """Test creating and updating SMS templates."""
    tournament = setup_tournament

    template = SmsTemplate(
        tournament_id=tournament.id,
        message_type="first_match",
        template_body="{tournament_name}: {team_name}, you play at {time} on {court}!",
    )
    session.add(template)
    session.commit()
    session.refresh(template)

    assert template.id is not None
    assert "{team_name}" in template.template_body
    assert template.is_active is True


def test_sms_template_unique_per_tournament_type(session: Session, setup_tournament):
    """Test unique constraint on tournament_id + message_type."""
    from sqlalchemy.exc import IntegrityError

    tournament = setup_tournament

    t1 = SmsTemplate(
        tournament_id=tournament.id,
        message_type="on_deck",
        template_body="Template 1",
    )
    session.add(t1)
    session.commit()

    t2 = SmsTemplate(
        tournament_id=tournament.id,
        message_type="on_deck",  # Duplicate type for same tournament
        template_body="Template 2",
    )
    session.add(t2)
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_tournament_sms_settings_defaults(session: Session, setup_tournament):
    """Test creating tournament SMS settings with defaults."""
    tournament = setup_tournament

    settings = TournamentSmsSettings(tournament_id=tournament.id)
    session.add(settings)
    session.commit()
    session.refresh(settings)

    assert settings.id is not None
    assert settings.auto_first_match is False
    assert settings.auto_post_match_next is False
    assert settings.auto_on_deck is False
    assert settings.auto_up_next is False
    assert settings.auto_court_change is True  # This one defaults ON


def test_tournament_sms_settings_toggle(session: Session, setup_tournament):
    """Test toggling SMS settings."""
    tournament = setup_tournament

    settings = TournamentSmsSettings(tournament_id=tournament.id)
    session.add(settings)
    session.commit()

    settings.auto_first_match = True
    settings.auto_on_deck = True
    session.add(settings)
    session.commit()
    session.refresh(settings)

    assert settings.auto_first_match is True
    assert settings.auto_on_deck is True
    assert settings.auto_post_match_next is False  # Still off


def test_default_templates_exist():
    """Verify all expected default templates are defined."""
    expected_types = [
        "first_match",
        "post_match_next",
        "on_deck",
        "up_next",
        "court_change",
    ]
    for msg_type in expected_types:
        assert msg_type in DEFAULT_SMS_TEMPLATES
        assert len(DEFAULT_SMS_TEMPLATES[msg_type]) > 0
        assert "{team_name}" in DEFAULT_SMS_TEMPLATES[msg_type]


# ---------------------------------------------------------------------------
# Twilio service tests (always dry-run in test env)
# ---------------------------------------------------------------------------


def test_twilio_service_dry_run():
    """Test TwilioService in dry-run mode (no credentials)."""
    from app.services.twilio_service import TwilioService

    service = TwilioService()
    assert service.dry_run is True
    assert service.is_configured is False

    result = service.send_sms("+19013593035", "Test message")
    assert result["status"] == "dry_run"
    assert result["sid"].startswith("DRY_RUN_")
    assert result["error"] is None


def test_twilio_service_invalid_phone():
    """Test TwilioService rejects invalid phone numbers."""
    from app.services.twilio_service import TwilioService

    service = TwilioService()
    result = service.send_sms("not-a-phone", "Test")
    assert result["status"] == "failed"
    assert "Invalid phone number" in result["error"]


def test_twilio_service_bulk_dry_run():
    """Test bulk send in dry-run mode."""
    from app.services.twilio_service import TwilioService

    service = TwilioService()
    recipients = [
        {"phone": "+19013593035", "body": "Message 1", "team_id": 1},
        {"phone": "+15552222222", "body": "Message 2", "team_id": 2},
        {"phone": "bad-number", "body": "Message 3", "team_id": 3},
    ]

    result = service.send_bulk(recipients)
    assert result["total"] == 3
    assert result["sent"] == 2  # Two valid phones
    assert result["failed"] == 1  # One invalid
