"""Tests for expanded SMS targeting endpoints and dedupe behavior."""

from datetime import date

import pytest
from sqlmodel import Session, select

from app.models.event import Event
from app.models.player import Player
from app.models.sms_log import SmsLog
from app.models.team import Team
from app.models.tournament import Tournament


@pytest.fixture(autouse=True)
def _force_twilio_dry_run(monkeypatch):
    """Ensure deterministic test sends with no external Twilio calls."""
    import app.services.twilio_service as _mod

    monkeypatch.delenv("TWILIO_ACCOUNT_SID", raising=False)
    monkeypatch.delenv("TWILIO_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("TWILIO_FROM_NUMBER", raising=False)
    _mod._twilio_service = None


@pytest.fixture
def setup_targeting_data(session: Session):
    tournament = Tournament(
        name="SMS Targeting Test",
        location="Test Venue",
        timezone="America/Chicago",
        start_date=date(2026, 5, 1),
        end_date=date(2026, 5, 3),
    )
    session.add(tournament)
    session.commit()
    session.refresh(tournament)

    mixed_event = Event(
        tournament_id=tournament.id,
        name="Mixed Doubles",
        category="mixed",
        team_count=2,
    )
    womens_event = Event(
        tournament_id=tournament.id,
        name="Womens Doubles",
        category="womens",
        team_count=2,
    )
    session.add(mixed_event)
    session.add(womens_event)
    session.commit()
    session.refresh(mixed_event)
    session.refresh(womens_event)

    mixed_team = Team(
        event_id=mixed_event.id,
        name="Mixed Team",
        seed=1,
        p1_cell="9013593035",
    )
    womens_team = Team(
        event_id=womens_event.id,
        name="Womens Team",
        seed=1,
        p1_cell="9013594040",
    )
    session.add(mixed_team)
    session.add(womens_team)
    session.commit()
    session.refresh(mixed_team)
    session.refresh(womens_team)

    player = Player(
        tournament_id=tournament.id,
        full_name="Target Player",
        display_name="Target",
        phone_e164="+15550000099",
        sms_consent_status="opted_in",
        sms_consent_source="manual",
    )
    session.add(player)
    session.commit()
    session.refresh(player)

    return tournament, mixed_event, womens_event, mixed_team, womens_team, player


def test_event_scope_send(client, session, setup_targeting_data):
    tournament, mixed_event, _, _, _, _ = setup_targeting_data

    resp = client.post(
        f"/api/tournaments/{tournament.id}/sms/event/{mixed_event.id}",
        json={"message": "Event scoped"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["message_type"] == "event_blast"
    assert data["sent"] == 1


def test_division_scope_send(client, session, setup_targeting_data):
    tournament, _, _, _, _, _ = setup_targeting_data

    resp = client.post(
        f"/api/tournaments/{tournament.id}/sms/division/mixed",
        json={"message": "Division scoped"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["message_type"] == "division_blast"
    assert data["sent"] == 1


def test_player_scope_preview_and_send(client, session, setup_targeting_data):
    tournament, _, _, _, _, player = setup_targeting_data

    preview = client.post(
        f"/api/tournaments/{tournament.id}/sms/preview/player/{player.id}",
        json={"message": "Player preview"},
    )
    assert preview.status_code == 200
    preview_data = preview.json()
    assert preview_data["total_messages"] == 1
    assert preview_data["recipients"][0]["player_id"] == player.id

    send = client.post(
        f"/api/tournaments/{tournament.id}/sms/player/{player.id}",
        json={"message": "Player direct"},
    )
    assert send.status_code == 200
    send_data = send.json()
    assert send_data["message_type"] == "player_direct"
    assert send_data["sent"] == 1
    assert send_data["results"][0]["player_id"] == player.id


def test_dedupe_key_prevents_duplicate_retries(client, session, setup_targeting_data):
    tournament, _, _, mixed_team, _, _ = setup_targeting_data
    dedupe_key = "retry-team-send-1"

    first = client.post(
        f"/api/tournaments/{tournament.id}/sms/team/{mixed_team.id}",
        json={"message": "Retry-safe send", "dedupe_key": dedupe_key},
    )
    second = client.post(
        f"/api/tournaments/{tournament.id}/sms/team/{mixed_team.id}",
        json={"message": "Retry-safe send", "dedupe_key": dedupe_key},
    )

    assert first.status_code == 200
    assert second.status_code == 200
    first_data = first.json()
    second_data = second.json()
    assert first_data["sent"] == 1
    assert second_data["sent"] == 0
    assert second_data["skipped_dedupe"] == 1
    assert second_data["results"][0]["status"] == "deduped"

    logs = session.exec(
        select(SmsLog).where(
            SmsLog.tournament_id == tournament.id,
            SmsLog.message_type == "team_direct",
            SmsLog.dedupe_key == dedupe_key,
        )
    ).all()
    assert len(logs) == 1
