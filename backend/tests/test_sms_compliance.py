"""Tests for SMS compliance webhook + consent enforcement."""

from datetime import date

import pytest
from sqlmodel import Session, select

from app.models.event import Event
from app.models.player import Player
from app.models.sms_consent_event import SmsConsentEvent
from app.models.sms_log import SmsLog
from app.models.team import Team
from app.models.tournament import Tournament


@pytest.fixture(autouse=True)
def _force_twilio_dry_run(monkeypatch):
    """Default tests to dry-run mode unless explicitly overridden."""
    import app.services.twilio_service as _mod

    monkeypatch.delenv("TWILIO_ACCOUNT_SID", raising=False)
    monkeypatch.delenv("TWILIO_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("TWILIO_FROM_NUMBER", raising=False)
    _mod._twilio_service = None


@pytest.fixture
def setup_tournament_team(session: Session):
    tournament = Tournament(
        name="SMS Compliance Test",
        location="Test Venue",
        timezone="America/Chicago",
        start_date=date(2026, 4, 10),
        end_date=date(2026, 4, 12),
    )
    session.add(tournament)
    session.commit()
    session.refresh(tournament)

    event = Event(
        tournament_id=tournament.id,
        name="Mixed Doubles",
        category="mixed",
        team_count=2,
    )
    session.add(event)
    session.commit()
    session.refresh(event)

    team = Team(
        event_id=event.id,
        name="Alex Carter / Jamie Quinn",
        seed=1,
        p1_cell="9013593035",
        p2_cell=None,
    )
    session.add(team)
    session.commit()
    session.refresh(team)
    return tournament, event, team


def test_stop_start_updates_consent_and_send_behavior(
    client, session, setup_tournament_team
):
    tournament, _, team = setup_tournament_team

    # Baseline manual send succeeds.
    before = client.post(
        f"/api/tournaments/{tournament.id}/sms/team/{team.id}",
        json={"message": "Before STOP"},
    )
    assert before.status_code == 200
    assert before.json()["sent"] == 1

    stop_resp = client.post(
        f"/api/tournaments/{tournament.id}/sms/webhook/inbound",
        data={
            "From": "9013593035",
            "Body": "STOP",
            "MessageSid": "SM_STOP_1",
        },
    )
    assert stop_resp.status_code == 200
    assert stop_resp.json()["event_type"] == "opted_out"

    player = session.exec(
        select(Player).where(
            Player.tournament_id == tournament.id,
            Player.phone_e164 == "+19013593035",
        )
    ).first()
    assert player is not None
    assert player.sms_consent_status == "opted_out"

    blocked = client.post(
        f"/api/tournaments/{tournament.id}/sms/team/{team.id}",
        json={"message": "After STOP"},
    )
    assert blocked.status_code == 200
    blocked_data = blocked.json()
    assert blocked_data["sent"] == 0
    assert blocked_data["skipped_consent"] == 1
    assert blocked_data["results"][0]["status"] == "blocked_consent"

    start_resp = client.post(
        f"/api/tournaments/{tournament.id}/sms/webhook/inbound",
        data={
            "From": "9013593035",
            "Body": "START",
            "MessageSid": "SM_START_1",
        },
    )
    assert start_resp.status_code == 200
    assert start_resp.json()["event_type"] == "opted_in"

    session.refresh(player)
    assert player.sms_consent_status == "opted_in"

    after = client.post(
        f"/api/tournaments/{tournament.id}/sms/team/{team.id}",
        json={"message": "After START"},
    )
    assert after.status_code == 200
    assert after.json()["sent"] == 1
    assert after.json()["skipped_consent"] == 0


def test_inbound_webhook_message_sid_deduped(client, session, setup_tournament_team):
    tournament, _, _ = setup_tournament_team

    payload = {
        "From": "9013593035",
        "Body": "STOP",
        "MessageSid": "SM_DEDUPE_1",
    }
    first = client.post(
        f"/api/tournaments/{tournament.id}/sms/webhook/inbound",
        data=payload,
    )
    second = client.post(
        f"/api/tournaments/{tournament.id}/sms/webhook/inbound",
        data=payload,
    )

    assert first.status_code == 200
    assert first.json()["deduped"] is False
    assert second.status_code == 200
    assert second.json()["deduped"] is True

    events = session.exec(
        select(SmsConsentEvent).where(
            SmsConsentEvent.tournament_id == tournament.id,
            SmsConsentEvent.dedupe_key == "inbound:SM_DEDUPE_1",
        )
    ).all()
    assert len(events) == 1


def test_status_callback_updates_sms_log(client, session, setup_tournament_team):
    tournament, _, team = setup_tournament_team

    send_resp = client.post(
        f"/api/tournaments/{tournament.id}/sms/team/{team.id}",
        json={"message": "Callback status test"},
    )
    assert send_resp.status_code == 200

    log = session.exec(
        select(SmsLog).where(
            SmsLog.tournament_id == tournament.id,
            SmsLog.message_type == "team_direct",
        )
    ).first()
    assert log is not None
    assert log.twilio_sid is not None

    cb_resp = client.post(
        f"/api/tournaments/{tournament.id}/sms/webhook/status-callback",
        data={
            "MessageSid": log.twilio_sid,
            "MessageStatus": "delivered",
            "ErrorCode": "",
            "ErrorMessage": "",
        },
    )
    assert cb_resp.status_code == 200
    assert cb_resp.json() == {"ok": True, "updated": True}

    session.refresh(log)
    assert log.status == "delivered"


def test_webhook_requires_signature_when_auth_token_configured(
    client, session, setup_tournament_team, monkeypatch
):
    tournament, _, _ = setup_tournament_team
    import app.services.twilio_service as twilio_mod

    monkeypatch.setenv("TWILIO_ACCOUNT_SID", "AC" + ("1" * 32))
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "a" * 32)
    monkeypatch.setenv("TWILIO_FROM_NUMBER", "+15551230000")
    twilio_mod._twilio_service = None

    resp = client.post(
        f"/api/tournaments/{tournament.id}/sms/webhook/inbound",
        data={
            "From": "9013593035",
            "Body": "STOP",
            "MessageSid": "SM_SIGNATURE_REQUIRED",
        },
    )
    assert resp.status_code == 403


def test_send_attaches_status_callback_url_when_base_configured(
    client, session, setup_tournament_team, monkeypatch
):
    tournament, _, team = setup_tournament_team
    monkeypatch.setenv("SMS_STATUS_CALLBACK_BASE_URL", "https://example.test")

    captured: dict[str, str | None] = {"url": None}

    class _FakeTwilio:
        @property
        def is_configured(self) -> bool:
            return True

        def send_sms(self, to: str, body: str, *, status_callback_url: str | None = None):
            captured["url"] = status_callback_url
            return {"sid": "SM_CALLBACK_TEST", "status": "queued", "error": None}

    monkeypatch.setattr("app.routes.sms.get_twilio_service", lambda: _FakeTwilio())

    resp = client.post(
        f"/api/tournaments/{tournament.id}/sms/team/{team.id}",
        json={"message": "Callback URL test"},
    )
    assert resp.status_code == 200
    assert captured["url"] == (
        f"https://example.test/api/tournaments/{tournament.id}/sms/webhook/status-callback"
    )


def test_send_attaches_status_callback_url_with_api_base(
    client, session, setup_tournament_team, monkeypatch
):
    tournament, _, team = setup_tournament_team
    monkeypatch.setenv("SMS_STATUS_CALLBACK_BASE_URL", "https://example.test/api")

    captured: dict[str, str | None] = {"url": None}

    class _FakeTwilio:
        @property
        def is_configured(self) -> bool:
            return True

        def send_sms(self, to: str, body: str, *, status_callback_url: str | None = None):
            captured["url"] = status_callback_url
            return {"sid": "SM_CALLBACK_TEST_2", "status": "queued", "error": None}

    monkeypatch.setattr("app.routes.sms.get_twilio_service", lambda: _FakeTwilio())

    resp = client.post(
        f"/api/tournaments/{tournament.id}/sms/team/{team.id}",
        json={"message": "Callback URL test"},
    )
    assert resp.status_code == 200
    assert captured["url"] == (
        f"https://example.test/api/tournaments/{tournament.id}/sms/webhook/status-callback"
    )
