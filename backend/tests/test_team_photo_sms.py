"""Automatic team-photo SMS: queue on first save, consent, dedupe, and the private link."""

from __future__ import annotations

import io
from datetime import date, datetime, timedelta, timezone

import pytest

from fastapi.testclient import TestClient
from PIL import Image
from sqlmodel import Session, select

from app.models.event import Event
from app.models.player import Player
from app.models.sms_log import SmsLog
from app.models.team import Team
from app.models.team_photo_sms import TeamPhotoShare, TeamPhotoSmsNotice
from app.models.team_player import TeamPlayer
from app.models.tournament import Tournament
from app.models.tournament_sms_settings import TournamentSmsSettings
from app.services.team_photo_sms import (
    classify_photo_recipients,
    dispatch_team_photo_notices,
    photo_sms_body,
    record_team_photo_provider_status,
)
from app.services.team_photo_storage import reset_memory_store


def _jpeg(color: str = "red") -> bytes:
    image = Image.new("RGB", (8, 8), color)
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=90)
    return buffer.getvalue()


def _login(client: TestClient) -> dict[str, str]:
    created = client.post("/api/auth/bootstrap-admin", json={"username": "admin", "password": "password123"})
    assert created.status_code == 201, created.text
    response = client.post("/api/auth/login", json={"username": "admin", "password": "password123"})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _roster(
    session: Session,
    *,
    p1_phone: str | None = "+15555550101",
    p2_phone: str | None = "+15555550102",
    p1_consent: str = "opted_in",
    p2_consent: str = "opted_in",
) -> dict:
    tournament = Tournament(
        name="2026 Wild Dunes",
        location="Wild Dunes",
        timezone="America/New_York",
        start_date=date(2026, 10, 16),
        end_date=date(2026, 10, 18),
    )
    session.add(tournament)
    session.flush()
    event = Event(tournament_id=tournament.id, category="mixed", name="Mixed", team_count=4)
    session.add(event)
    session.flush()
    team = Team(event_id=event.id, name="Mike Arsenault / Dee Dee Worley", display_name="Mike / Dee Dee", seed=1)
    session.add(team)
    session.flush()
    players = []
    for slot, name, phone, consent in (
        (1, "Mike Arsenault", p1_phone, p1_consent),
        (2, "Dee Dee Worley", p2_phone, p2_consent),
    ):
        player = Player(
            tournament_id=tournament.id,
            full_name=name,
            phone_e164=phone,
            sms_consent_status=consent,
            sms_consent_source="registration",
        )
        session.add(player)
        session.flush()
        session.add(TeamPlayer(team_id=team.id, player_id=player.id, lineup_slot=slot))
        players.append(player)
    session.commit()
    return {"tournament_id": tournament.id, "team_id": team.id, "players": [player.id for player in players]}


def _save(client: TestClient, headers: dict, tournament_id: int, team_id: int, upload_id: str, payload: bytes):
    return client.post(
        f"/api/photography/tournaments/{tournament_id}/teams/{team_id}/official",
        headers=headers,
        files={"file": ("team.jpg", payload, "image/jpeg")},
        data={"client_upload_id": upload_id},
    )


def _statuses(session: Session, team_id: int) -> dict[str, str]:
    session.expire_all()
    rows = session.exec(select(TeamPhotoSmsNotice).where(TeamPhotoSmsNotice.team_id == team_id)).all()
    return {row.phone_e164 or f"player:{row.player_id}": row.status for row in rows}


def _sender(calls: list[dict]):
    def send(to: str, body: str, status_callback_url=None):
        calls.append({"to": to, "body": body, "callback": status_callback_url})
        return {"sid": f"SM{len(calls)}", "status": "sent", "error": None}

    return send


def test_same_phone_on_both_registrations_is_one_message():
    first = Player(full_name="Mike", phone_e164="(555) 555-0101", sms_consent_status="opted_in")
    second = Player(full_name="Dee", phone_e164="+15555550101", sms_consent_status="opted_in")
    plans = classify_photo_recipients([first, second])
    assert [kind for _player, _phone, kind in plans] == ["ready", "duplicate"]
    assert plans[0][1] == "+15555550101"


def test_message_uses_the_tournament_name_and_link():
    body = photo_sms_body("2026 Wild Dunes", "https://photos.test/p/photo/token")
    assert "2026 Wild Dunes" in body
    assert "https://photos.test/p/photo/token" in body
    assert "{{" not in body
    assert "Reply STOP to opt out." in body


def test_photo_saved_queues_two_messages_and_dispatch_sends_them(
    client: TestClient, session: Session, monkeypatch
):
    monkeypatch.setenv("TEAM_PHOTO_OBJECT_STORE", "memory")
    monkeypatch.setenv("TEAM_PHOTO_AUTO_SMS_ENABLED", "true")
    monkeypatch.setenv("PUBLIC_APP_URL", "https://photos.test")
    reset_memory_store()
    headers = _login(client)
    roster = _roster(session)
    saved = _save(client, headers, roster["tournament_id"], roster["team_id"], "upload-first-1", _jpeg())
    assert saved.status_code == 200, saved.text
    assert _statuses(session, roster["team_id"]) == {"+15555550101": "PENDING", "+15555550102": "PENDING"}

    calls: list[dict] = []
    sent = dispatch_team_photo_notices(session, send=_sender(calls))
    assert sent == 2
    assert len(calls) == 2
    assert {call["to"] for call in calls} == {"+15555550101", "+15555550102"}
    assert all("https://photos.test/p/photo/" in call["body"] for call in calls)
    assert _statuses(session, roster["team_id"]) == {"+15555550101": "SENT", "+15555550102": "SENT"}
    session.expire_all()
    notices = session.exec(select(TeamPhotoSmsNotice).where(TeamPhotoSmsNotice.team_id == roster["team_id"])).all()
    assert all(notice.provider_sid and notice.sent_at and notice.status == "SENT" for notice in notices)


def test_failed_upload_creates_no_notification(client: TestClient, session: Session, monkeypatch):
    monkeypatch.setenv("TEAM_PHOTO_OBJECT_STORE", "memory")
    monkeypatch.setenv("TEAM_PHOTO_AUTO_SMS_ENABLED", "true")
    reset_memory_store()
    headers = _login(client)
    roster = _roster(session)
    failed = _save(client, headers, roster["tournament_id"], roster["team_id"], "upload-bad-1", b"not-a-photo")
    assert failed.status_code == 400
    session.expire_all()
    assert session.exec(select(TeamPhotoSmsNotice)).all() == []
    assert session.exec(select(TeamPhotoShare)).all() == []


def test_one_opt_out_still_texts_the_other_player(client: TestClient, session: Session, monkeypatch):
    monkeypatch.setenv("TEAM_PHOTO_OBJECT_STORE", "memory")
    monkeypatch.setenv("TEAM_PHOTO_AUTO_SMS_ENABLED", "true")
    monkeypatch.setenv("PUBLIC_APP_URL", "https://photos.test")
    reset_memory_store()
    headers = _login(client)
    roster = _roster(session, p2_consent="opted_out")
    assert _save(client, headers, roster["tournament_id"], roster["team_id"], "upload-opt-1", _jpeg()).status_code == 200
    calls: list[dict] = []
    dispatch_team_photo_notices(session, send=_sender(calls))
    assert [call["to"] for call in calls] == ["+15555550101"]
    assert _statuses(session, roster["team_id"])["+15555550102"] == "SKIPPED_OPT_OUT"


def test_both_opted_out_sends_nothing(client: TestClient, session: Session, monkeypatch):
    monkeypatch.setenv("TEAM_PHOTO_OBJECT_STORE", "memory")
    monkeypatch.setenv("TEAM_PHOTO_AUTO_SMS_ENABLED", "true")
    monkeypatch.setenv("PUBLIC_APP_URL", "https://photos.test")
    reset_memory_store()
    headers = _login(client)
    roster = _roster(session, p1_consent="opted_out", p2_consent="opted_out")
    assert _save(client, headers, roster["tournament_id"], roster["team_id"], "upload-both-out", _jpeg()).status_code == 200
    calls: list[dict] = []
    assert dispatch_team_photo_notices(session, send=_sender(calls)) == 0
    assert calls == []
    assert set(_statuses(session, roster["team_id"]).values()) == {"SKIPPED_OPT_OUT"}


def test_missing_consent_sends_nothing(client: TestClient, session: Session, monkeypatch):
    monkeypatch.setenv("TEAM_PHOTO_OBJECT_STORE", "memory")
    monkeypatch.setenv("TEAM_PHOTO_AUTO_SMS_ENABLED", "true")
    monkeypatch.setenv("PUBLIC_APP_URL", "https://photos.test")
    reset_memory_store()
    headers = _login(client)
    roster = _roster(session, p1_consent="unknown", p2_consent="unknown")
    assert _save(client, headers, roster["tournament_id"], roster["team_id"], "upload-unknown", _jpeg()).status_code == 200
    calls: list[dict] = []
    dispatch_team_photo_notices(session, send=_sender(calls))
    assert calls == []
    assert set(_statuses(session, roster["team_id"]).values()) == {"SKIPPED_NO_CONSENT"}


def test_invalid_number_is_skipped(client: TestClient, session: Session, monkeypatch):
    monkeypatch.setenv("TEAM_PHOTO_OBJECT_STORE", "memory")
    monkeypatch.setenv("TEAM_PHOTO_AUTO_SMS_ENABLED", "true")
    monkeypatch.setenv("PUBLIC_APP_URL", "https://photos.test")
    reset_memory_store()
    headers = _login(client)
    roster = _roster(session, p2_phone="12")
    assert _save(client, headers, roster["tournament_id"], roster["team_id"], "upload-bad-phone", _jpeg()).status_code == 200
    calls: list[dict] = []
    dispatch_team_photo_notices(session, send=_sender(calls))
    assert len(calls) == 1
    session.expire_all()
    skipped = session.exec(
        select(TeamPhotoSmsNotice).where(TeamPhotoSmsNotice.status == "SKIPPED_INVALID_NUMBER")
    ).all()
    assert len(skipped) == 1


def test_double_save_and_replacement_and_thumbnail_do_not_send_again(
    client: TestClient, session: Session, monkeypatch
):
    monkeypatch.setenv("TEAM_PHOTO_OBJECT_STORE", "memory")
    monkeypatch.setenv("TEAM_PHOTO_AUTO_SMS_ENABLED", "true")
    monkeypatch.setenv("PUBLIC_APP_URL", "https://photos.test")
    reset_memory_store()
    headers = _login(client)
    roster = _roster(session)
    first = _save(client, headers, roster["tournament_id"], roster["team_id"], "upload-once-1", _jpeg())
    assert first.status_code == 200
    again = _save(client, headers, roster["tournament_id"], roster["team_id"], "upload-once-1", _jpeg())
    assert again.status_code == 200
    session.expire_all()
    assert len(session.exec(select(TeamPhotoSmsNotice).where(TeamPhotoSmsNotice.team_id == roster["team_id"])).all()) == 2
    thumb = client.get(f"/api/photography/teams/{roster['team_id']}/official/thumb", headers=headers)
    assert thumb.status_code == 200
    replaced = _save(client, headers, roster["tournament_id"], roster["team_id"], "upload-retake-2", _jpeg())
    assert replaced.status_code == 200
    session.expire_all()
    notices = session.exec(select(TeamPhotoSmsNotice).where(TeamPhotoSmsNotice.team_id == roster["team_id"])).all()
    assert len(notices) == 2
    calls: list[dict] = []
    dispatch_team_photo_notices(session, send=_sender(calls))
    assert len(calls) == 2
    assert dispatch_team_photo_notices(session, send=_sender(calls)) == 0
    assert len(calls) == 2


def test_transient_failure_retries_and_permanent_failure_stops(client: TestClient, session: Session, monkeypatch):
    monkeypatch.setenv("TEAM_PHOTO_OBJECT_STORE", "memory")
    monkeypatch.setenv("TEAM_PHOTO_AUTO_SMS_ENABLED", "true")
    monkeypatch.setenv("PUBLIC_APP_URL", "https://photos.test")
    reset_memory_store()
    headers = _login(client)
    roster = _roster(session, p2_phone=None)
    assert _save(client, headers, roster["tournament_id"], roster["team_id"], "upload-retry-1", _jpeg()).status_code == 200
    attempts = {"n": 0}

    def flaky(to, body, status_callback_url=None):
        attempts["n"] += 1
        if attempts["n"] == 1:
            return {"sid": None, "status": "failed", "error": "timeout"}
        return {"sid": "SMok", "status": "sent", "error": None}

    assert dispatch_team_photo_notices(session, send=flaky) == 0
    session.expire_all()
    notice = session.exec(select(TeamPhotoSmsNotice).where(TeamPhotoSmsNotice.notice_type == "team_photo_ready")).one()
    assert notice.status == "PENDING"
    assert notice.retry_count == 1
    notice.next_attempt_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    session.add(notice)
    session.commit()
    assert dispatch_team_photo_notices(session, send=flaky) == 1
    session.expire_all()
    assert session.get(TeamPhotoSmsNotice, notice.id).status == "SENT"

    other = _roster(session, p1_phone="+15555550109", p2_phone=None)
    assert _save(client, headers, other["tournament_id"], other["team_id"], "upload-permanent", _jpeg()).status_code == 200

    def rejected(to, body, status_callback_url=None):
        return {"sid": None, "status": "failed", "error": "Twilio 21211 not a valid phone"}

    assert dispatch_team_photo_notices(session, send=rejected) == 0
    session.expire_all()
    failed = session.exec(
        select(TeamPhotoSmsNotice).where(TeamPhotoSmsNotice.team_id == other["team_id"], TeamPhotoSmsNotice.notice_type == "team_photo_ready")
    ).one()
    assert failed.status == "FAILED"
    assert dispatch_team_photo_notices(session, send=rejected) == 0


def test_stop_before_dispatch_suppresses_the_text(client: TestClient, session: Session, monkeypatch):
    monkeypatch.setenv("TEAM_PHOTO_OBJECT_STORE", "memory")
    monkeypatch.setenv("TEAM_PHOTO_AUTO_SMS_ENABLED", "true")
    monkeypatch.setenv("PUBLIC_APP_URL", "https://photos.test")
    reset_memory_store()
    headers = _login(client)
    roster = _roster(session)
    assert _save(client, headers, roster["tournament_id"], roster["team_id"], "upload-stop-1", _jpeg()).status_code == 200
    session.expire_all()
    for player_id in roster["players"]:
        player = session.get(Player, player_id)
        player.sms_consent_status = "opted_out"
        player.sms_consent_source = "twilio_webhook"
        session.add(player)
    session.commit()
    calls: list[dict] = []
    assert dispatch_team_photo_notices(session, send=_sender(calls)) == 0
    assert calls == []
    assert set(_statuses(session, roster["team_id"]).values()) == {"SKIPPED_OPT_OUT"}


def test_delivery_callback_marks_delivered_not_merely_accepted(client: TestClient, session: Session, monkeypatch):
    monkeypatch.setenv("TEAM_PHOTO_OBJECT_STORE", "memory")
    monkeypatch.setenv("TEAM_PHOTO_AUTO_SMS_ENABLED", "true")
    monkeypatch.setenv("PUBLIC_APP_URL", "https://photos.test")
    monkeypatch.setattr("app.routes.sms._validate_twilio_signature", lambda *_args, **_kwargs: None)
    reset_memory_store()
    headers = _login(client)
    roster = _roster(session, p2_phone=None)
    assert _save(client, headers, roster["tournament_id"], roster["team_id"], "upload-callback", _jpeg()).status_code == 200
    dispatch_team_photo_notices(session, send=_sender([]))
    session.expire_all()
    notice = session.exec(select(TeamPhotoSmsNotice).where(TeamPhotoSmsNotice.notice_type == "team_photo_ready")).one()
    assert notice.status == "SENT"
    assert notice.delivered_at is None
    response = client.post(
        f"/api/tournaments/{roster['tournament_id']}/sms/webhook/status-callback",
        data={"MessageSid": notice.provider_sid, "MessageStatus": "delivered"},
    )
    assert response.status_code == 200, response.text
    session.expire_all()
    updated = session.get(TeamPhotoSmsNotice, notice.id)
    assert updated.status == "DELIVERED"
    assert updated.delivered_at is not None
    assert record_team_photo_provider_status(session, provider_sid="missing", provider_status="delivered") is False


def test_secure_link_returns_the_original_and_rejects_a_bad_token(client: TestClient, session: Session, monkeypatch):
    monkeypatch.setenv("TEAM_PHOTO_OBJECT_STORE", "memory")
    monkeypatch.setenv("TEAM_PHOTO_AUTO_SMS_ENABLED", "true")
    monkeypatch.setenv("PUBLIC_APP_URL", "https://photos.test")
    reset_memory_store()
    headers = _login(client)
    roster = _roster(session)
    original = _jpeg()
    assert _save(client, headers, roster["tournament_id"], roster["team_id"], "upload-link-1", original).status_code == 200
    session.expire_all()
    share = session.exec(select(TeamPhotoShare).where(TeamPhotoShare.team_id == roster["team_id"])).one()
    page = client.get(f"/api/public/team-photo/{share.token}")
    assert page.status_code == 200, page.text
    body = page.json()
    assert body["tournament_name"] == "2026 Wild Dunes"
    assert body["players"] == ["Mike Arsenault", "Dee Dee Worley"]
    assert "phone" not in page.text
    image = client.get(f"/api/public/team-photo/{share.token}/image")
    assert image.status_code == 200
    assert image.content == original
    download = client.get(f"/api/public/team-photo/{share.token}/image?download=1")
    assert "attachment" in download.headers["content-disposition"]
    assert client.get("/api/public/team-photo/not-a-real-token").status_code == 404
    share.revoked_at = datetime.now(timezone.utc)
    session.add(share)
    session.commit()
    assert client.get(f"/api/public/team-photo/{share.token}").status_code == 404


def test_feature_flag_off_does_not_queue_existing_or_new_photos(client: TestClient, session: Session, monkeypatch):
    monkeypatch.setenv("TEAM_PHOTO_OBJECT_STORE", "memory")
    monkeypatch.setenv("TEAM_PHOTO_AUTO_SMS_ENABLED", "false")
    reset_memory_store()
    headers = _login(client)
    roster = _roster(session)
    assert _save(client, headers, roster["tournament_id"], roster["team_id"], "upload-off-1", _jpeg()).status_code == 200
    session.expire_all()
    assert session.exec(select(TeamPhotoSmsNotice)).all() == []
    calls: list[dict] = []
    assert dispatch_team_photo_notices(session, send=_sender(calls)) == 0
    assert calls == []


def test_allowlist_mode_texts_only_approved_numbers(client: TestClient, session: Session, monkeypatch):
    monkeypatch.setenv("TEAM_PHOTO_OBJECT_STORE", "memory")
    monkeypatch.setenv("TEAM_PHOTO_AUTO_SMS_ENABLED", "true")
    monkeypatch.setenv("PUBLIC_APP_URL", "https://photos.test")
    reset_memory_store()
    headers = _login(client)
    roster = _roster(session)
    session.add(
        TournamentSmsSettings(
            tournament_id=roster["tournament_id"],
            delivery_mode="allowlist",
            test_mode=True,
            test_allowlist="+15555550101",
        )
    )
    session.commit()
    assert _save(client, headers, roster["tournament_id"], roster["team_id"], "upload-allow-1", _jpeg()).status_code == 200
    calls: list[dict] = []
    dispatch_team_photo_notices(session, send=_sender(calls))
    assert [call["to"] for call in calls] == ["+15555550101"]
    assert _statuses(session, roster["team_id"])["+15555550102"] == "SKIPPED_TEST_MODE"


def _photo_logs(session: Session, tournament_id: int) -> list[SmsLog]:
    session.expire_all()
    return session.exec(
        select(SmsLog).where(SmsLog.tournament_id == tournament_id, SmsLog.message_type == "team_photo")
    ).all()


def test_blocked_gates_do_not_send_when_they_are_opened_later(client: TestClient, session: Session, monkeypatch):
    monkeypatch.setenv("TEAM_PHOTO_OBJECT_STORE", "memory")
    monkeypatch.setenv("TEAM_PHOTO_AUTO_SMS_ENABLED", "true")
    monkeypatch.setenv("PUBLIC_APP_URL", "https://photos.test")
    reset_memory_store()
    headers = _login(client)
    roster = _roster(session)
    session.add(TournamentSmsSettings(tournament_id=roster["tournament_id"], texts_enabled=False, delivery_mode="live"))
    session.commit()
    assert _save(client, headers, roster["tournament_id"], roster["team_id"], "upload-hold-1", _jpeg()).status_code == 200
    calls: list[dict] = []
    assert dispatch_team_photo_notices(session, send=_sender(calls)) == 0
    assert calls == []
    assert set(_statuses(session, roster["team_id"]).values()) == {"SKIPPED_TEXTS_OFF"}
    assert _photo_logs(session, roster["tournament_id"]) == []

    settings = session.exec(
        select(TournamentSmsSettings).where(TournamentSmsSettings.tournament_id == roster["tournament_id"])
    ).one()
    settings.texts_enabled = True
    session.add(settings)
    session.commit()
    assert dispatch_team_photo_notices(session, send=_sender(calls)) == 0
    assert calls == []
    assert set(_statuses(session, roster["team_id"]).values()) == {"SKIPPED_TEXTS_OFF"}

    monkeypatch.setenv("TEAM_PHOTO_AUTO_SMS_ENABLED", "false")
    assert dispatch_team_photo_notices(session, send=_sender(calls)) == 0
    assert calls == []


def test_tournament_delivery_modes_gate_photo_texts(client: TestClient, session: Session, monkeypatch):
    monkeypatch.setenv("TEAM_PHOTO_OBJECT_STORE", "memory")
    monkeypatch.setenv("TEAM_PHOTO_AUTO_SMS_ENABLED", "true")
    monkeypatch.setenv("PUBLIC_APP_URL", "https://rw-tournament-software.onrender.com")
    reset_memory_store()
    headers = _login(client)
    roster = _roster(session)
    session.add(
        TournamentSmsSettings(
            tournament_id=roster["tournament_id"],
            texts_enabled=True,
            delivery_mode="redirect",
            redirect_phone="+15555550999",
        )
    )
    session.commit()
    assert _save(client, headers, roster["tournament_id"], roster["team_id"], "upload-modes-1", _jpeg()).status_code == 200
    calls: list[dict] = []
    assert dispatch_team_photo_notices(session, send=_sender(calls)) == 2
    assert {call["to"] for call in calls} == {"+15555550999"}
    assert all(call["body"].startswith("[TEST redirect — intended +") for call in calls)
    assert all("https://rw-tournament-software.onrender.com/p/photo/" in call["body"] for call in calls)
    logs = _photo_logs(session, roster["tournament_id"])
    assert len(logs) == 2
    assert {log.status for log in logs} == {"sent_redirect"}
    assert {log.phone_number for log in logs} == {"+15555550999"}
    assert {log.intended_phone_number for log in logs} == {"+15555550101", "+15555550102"}
    assert set(_statuses(session, roster["team_id"]).values()) == {"SENT"}

    notices = session.exec(select(TeamPhotoSmsNotice).where(TeamPhotoSmsNotice.team_id == roster["team_id"])).all()
    for notice in notices:
        notice.status = "PENDING"
        notice.provider_sid = None
        session.add(notice)
    for log in logs:
        session.delete(log)
    settings = session.exec(
        select(TournamentSmsSettings).where(TournamentSmsSettings.tournament_id == roster["tournament_id"])
    ).one()
    settings.delivery_mode = "allowlist"
    settings.test_mode = True
    settings.test_allowlist = "+15555550101"
    settings.redirect_phone = None
    session.add(settings)
    session.commit()
    calls.clear()
    assert dispatch_team_photo_notices(session, send=_sender(calls)) == 1
    assert [call["to"] for call in calls] == ["+15555550101"]
    assert _statuses(session, roster["team_id"])["+15555550102"] == "SKIPPED_TEST_MODE"
    blocked = [log for log in _photo_logs(session, roster["tournament_id"]) if log.status == "blocked_test_mode"]
    assert len(blocked) == 1
    assert blocked[0].intended_phone_number == "+15555550102"
    assert all(notice.status != "DELIVERED" for notice in session.exec(select(TeamPhotoSmsNotice)).all())

    for notice in session.exec(select(TeamPhotoSmsNotice).where(TeamPhotoSmsNotice.team_id == roster["team_id"])).all():
        if notice.phone_e164 == "+15555550101":
            notice.status = "PENDING"
            notice.provider_sid = None
            session.add(notice)
    session.commit()
    for log in session.exec(select(SmsLog).where(SmsLog.tournament_id == roster["tournament_id"])).all():
        session.delete(log)
    settings.delivery_mode = "live"
    settings.test_mode = False
    settings.test_allowlist = None
    session.add(settings)
    session.commit()
    calls.clear()
    assert dispatch_team_photo_notices(session, send=_sender(calls)) == 1
    assert [call["to"] for call in calls] == ["+15555550101"]
    live_logs = [log for log in _photo_logs(session, roster["tournament_id"]) if log.status == "sent"]
    assert len(live_logs) == 1
    assert live_logs[0].phone_number == "+15555550101"
    assert live_logs[0].intended_phone_number == "+15555550101"
    assert all(notice.status != "DELIVERED" for notice in session.exec(select(TeamPhotoSmsNotice)).all())


def test_photo_flag_off_blocks_even_when_tournament_texting_is_live(client: TestClient, session: Session, monkeypatch):
    monkeypatch.setenv("TEAM_PHOTO_OBJECT_STORE", "memory")
    monkeypatch.setenv("TEAM_PHOTO_AUTO_SMS_ENABLED", "true")
    monkeypatch.setenv("PUBLIC_APP_URL", "https://photos.test")
    reset_memory_store()
    headers = _login(client)
    roster = _roster(session)
    session.add(TournamentSmsSettings(tournament_id=roster["tournament_id"], texts_enabled=True, delivery_mode="live"))
    session.commit()
    assert _save(client, headers, roster["tournament_id"], roster["team_id"], "upload-flag-1", _jpeg()).status_code == 200
    monkeypatch.setenv("TEAM_PHOTO_AUTO_SMS_ENABLED", "false")
    calls: list[dict] = []
    assert dispatch_team_photo_notices(session, send=_sender(calls)) == 0
    assert calls == []
    assert set(_statuses(session, roster["team_id"]).values()) == {"SKIPPED_DISABLED"}
    monkeypatch.setenv("TEAM_PHOTO_AUTO_SMS_ENABLED", "true")
    assert dispatch_team_photo_notices(session, send=_sender(calls)) == 0
    assert calls == []
    assert set(_statuses(session, roster["team_id"]).values()) == {"SKIPPED_DISABLED"}


def test_staff_status_hides_phone_numbers(client: TestClient, session: Session, monkeypatch):
    monkeypatch.setenv("TEAM_PHOTO_OBJECT_STORE", "memory")
    monkeypatch.setenv("TEAM_PHOTO_AUTO_SMS_ENABLED", "true")
    monkeypatch.setenv("PUBLIC_APP_URL", "https://photos.test")
    reset_memory_store()
    headers = _login(client)
    roster = _roster(session, p2_consent="opted_out")
    assert _save(client, headers, roster["tournament_id"], roster["team_id"], "upload-staff-1", _jpeg()).status_code == 200
    dispatch_team_photo_notices(session, send=_sender([]))
    status = client.get(
        f"/api/photography/tournaments/{roster['tournament_id']}/teams/{roster['team_id']}/photo-sms",
        headers=headers,
    )
    assert status.status_code == 200, status.text
    payload = status.json()
    assert payload["players"][0]["name"] == "Mike Arsenault"
    assert payload["players"][0]["status"] == "Sent"
    assert payload["players"][1]["status"] == "Skipped"
    assert payload["players"][1]["detail"] == "Opted out"
    assert "555" not in status.text


def _delete(client: TestClient, headers: dict, tournament_id: int, team_id: int):
    return client.delete(
        f"/api/photography/tournaments/{tournament_id}/teams/{team_id}/official",
        headers=headers,
    )


def test_replace_keeps_the_link_and_delete_then_save_texts_again(
    client: TestClient, session: Session, monkeypatch
):
    monkeypatch.setenv("TEAM_PHOTO_OBJECT_STORE", "memory")
    monkeypatch.setenv("TEAM_PHOTO_AUTO_SMS_ENABLED", "true")
    monkeypatch.setenv("PUBLIC_APP_URL", "https://photos.test")
    reset_memory_store()
    headers = _login(client)
    roster = _roster(session)
    original = _jpeg("red")
    assert _save(client, headers, roster["tournament_id"], roster["team_id"], "upload-session-1", original).status_code == 200
    session.expire_all()
    first = session.exec(
        select(TeamPhotoSmsNotice).where(TeamPhotoSmsNotice.team_id == roster["team_id"]).order_by(TeamPhotoSmsNotice.id)
    ).all()
    assert len(first) == 2
    assert {notice.photo_session_id for notice in first} == {1}
    assert {notice.status for notice in first} == {"PENDING"}
    assert all(
        notice.idempotency_key == f"photo-sms:1:{roster['team_id']}:team_photo_ready:{notice.phone_e164}"
        for notice in first
    )
    share = session.exec(select(TeamPhotoShare).where(TeamPhotoShare.team_id == roster["team_id"])).one()
    first_token = share.token
    assert share.generation == 1
    assert client.get(f"/api/public/team-photo/{first_token}/image").content == original

    replaced_bytes = _jpeg("blue")
    replaced = _save(client, headers, roster["tournament_id"], roster["team_id"], "upload-session-retake", replaced_bytes)
    assert replaced.status_code == 200
    session.expire_all()
    after_replace = session.exec(select(TeamPhotoSmsNotice).where(TeamPhotoSmsNotice.team_id == roster["team_id"])).all()
    assert len(after_replace) == 2
    assert {notice.idempotency_key for notice in after_replace} == {notice.idempotency_key for notice in first}
    share = session.exec(select(TeamPhotoShare).where(TeamPhotoShare.team_id == roster["team_id"])).one()
    assert share.token == first_token
    assert share.revoked_at is None
    assert client.get(f"/api/public/team-photo/{first_token}/image").content == replaced_bytes
    thumb = client.get(f"/api/photography/teams/{roster['team_id']}/official/thumb", headers=headers)
    assert thumb.status_code == 200
    assert len(session.exec(select(TeamPhotoSmsNotice).where(TeamPhotoSmsNotice.team_id == roster["team_id"])).all()) == 2

    calls: list[dict] = []
    assert dispatch_team_photo_notices(session, send=_sender(calls)) == 2
    assert dispatch_team_photo_notices(session, send=_sender(calls)) == 0
    assert len(calls) == 2
    session.expire_all()
    delivered_source = session.exec(
        select(TeamPhotoSmsNotice).where(TeamPhotoSmsNotice.team_id == roster["team_id"]).order_by(TeamPhotoSmsNotice.id)
    ).all()
    kept = []
    for notice in delivered_source:
        assert record_team_photo_provider_status(
            session, provider_sid=notice.provider_sid, provider_status="delivered"
        )
        kept.append((notice.id, notice.provider_sid, notice.sent_at, notice.idempotency_key))
    session.expire_all()
    for notice_id, sid, sent_at, key in kept:
        row = session.get(TeamPhotoSmsNotice, notice_id)
        assert row.status == "DELIVERED"
        assert row.provider_sid == sid
        assert row.delivered_at is not None
        assert row.sent_at == sent_at
        assert row.idempotency_key == key
    logs_before = len(_photo_logs(session, roster["tournament_id"]))
    assert logs_before == 2
    consent_before = {
        player_id: session.get(Player, player_id).sms_consent_status for player_id in roster["players"]
    }

    removed = _delete(client, headers, roster["tournament_id"], roster["team_id"])
    assert removed.status_code == 200, removed.text
    session.expire_all()
    assert client.get(f"/api/public/team-photo/{first_token}").status_code == 404
    share = session.exec(select(TeamPhotoShare).where(TeamPhotoShare.team_id == roster["team_id"])).one()
    assert share.revoked_at is not None
    assert share.generation == 1
    history = session.exec(
        select(TeamPhotoSmsNotice).where(TeamPhotoSmsNotice.team_id == roster["team_id"]).order_by(TeamPhotoSmsNotice.id)
    ).all()
    assert len(history) == 2
    assert {row.status for row in history} == {"DELIVERED"}
    for notice_id, sid, sent_at, key in kept:
        row = session.get(TeamPhotoSmsNotice, notice_id)
        assert row.status == "DELIVERED"
        assert row.provider_sid == sid
        assert row.sent_at == sent_at
        assert row.idempotency_key == key
        assert row.delivered_at is not None
    assert len(_photo_logs(session, roster["tournament_id"])) == logs_before
    assert {
        player_id: session.get(Player, player_id).sms_consent_status for player_id in roster["players"]
    } == consent_before
    status = client.get(
        f"/api/photography/tournaments/{roster['tournament_id']}/teams/{roster['team_id']}/photo-sms",
        headers=headers,
    )
    assert status.status_code == 200
    assert len(session.exec(select(TeamPhotoSmsNotice)).all()) == 2

    fresh = _jpeg("green")
    assert _save(client, headers, roster["tournament_id"], roster["team_id"], "upload-session-2", fresh).status_code == 200
    again = _save(client, headers, roster["tournament_id"], roster["team_id"], "upload-session-2", fresh)
    assert again.status_code == 200
    retake = _save(client, headers, roster["tournament_id"], roster["team_id"], "upload-session-2b", _jpeg("green"))
    assert retake.status_code == 200
    session.expire_all()
    notices = session.exec(
        select(TeamPhotoSmsNotice).where(TeamPhotoSmsNotice.team_id == roster["team_id"]).order_by(TeamPhotoSmsNotice.id)
    ).all()
    assert len(notices) == 4
    current = [notice for notice in notices if notice.photo_session_id == 2]
    previous = [notice for notice in notices if notice.photo_session_id == 1]
    assert len(current) == 2
    assert {notice.status for notice in current} == {"PENDING"}
    assert {notice.status for notice in previous} == {"DELIVERED"}
    assert {notice.idempotency_key for notice in current}.isdisjoint({notice.idempotency_key for notice in previous})
    assert all(
        notice.idempotency_key == f"photo-sms:2:{roster['team_id']}:team_photo_ready:{notice.phone_e164}"
        for notice in current
    )
    share = session.exec(select(TeamPhotoShare).where(TeamPhotoShare.team_id == roster["team_id"])).one()
    assert share.generation == 2
    assert share.token != first_token
    assert share.revoked_at is None
    assert client.get(f"/api/public/team-photo/{first_token}").status_code == 404
    assert client.get(f"/api/public/team-photo/{share.token}/image").content == fresh
    for notice_id, sid, sent_at, key in kept:
        row = session.get(TeamPhotoSmsNotice, notice_id)
        assert row.status == "DELIVERED"
        assert row.provider_sid == sid
        assert row.idempotency_key == key
        assert row.sent_at == sent_at

    from app.services.team_photo_sms import queue_team_photo_sms
    from app.models.team_photo import TeamOfficialPhoto

    photo = session.exec(select(TeamOfficialPhoto).where(TeamOfficialPhoto.team_id == roster["team_id"])).one()
    queue_team_photo_sms(session, photo)
    session.commit()
    session.expire_all()
    assert len(session.exec(select(TeamPhotoSmsNotice).where(TeamPhotoSmsNotice.team_id == roster["team_id"])).all()) == 4

    calls.clear()
    assert dispatch_team_photo_notices(session, send=_sender(calls)) == 2
    assert {call["to"] for call in calls} == {"+15555550101", "+15555550102"}
    assert all(f"/p/photo/{share.token}" in call["body"] for call in calls)
    assert dispatch_team_photo_notices(session, send=_sender(calls)) == 0
    assert len(calls) == 2
    session.expire_all()
    assert {row.status for row in previous} == {"DELIVERED"}
    for notice_id, sid, _sent_at, key in kept:
        row = session.get(TeamPhotoSmsNotice, notice_id)
        assert row.status == "DELIVERED"
        assert row.provider_sid == sid
        assert row.idempotency_key == key


def test_delete_cancels_pending_and_queued_notices(client: TestClient, session: Session, monkeypatch):
    monkeypatch.setenv("TEAM_PHOTO_OBJECT_STORE", "memory")
    monkeypatch.setenv("TEAM_PHOTO_AUTO_SMS_ENABLED", "true")
    monkeypatch.setenv("PUBLIC_APP_URL", "https://photos.test")
    reset_memory_store()
    headers = _login(client)
    roster = _roster(session)
    assert _save(client, headers, roster["tournament_id"], roster["team_id"], "upload-cancel-1", _jpeg()).status_code == 200
    session.expire_all()
    queued = session.exec(
        select(TeamPhotoSmsNotice).where(TeamPhotoSmsNotice.phone_e164 == "+15555550102")
    ).one()
    queued.status = "QUEUED"
    session.add(queued)
    session.commit()
    consent = {player_id: session.get(Player, player_id).sms_consent_status for player_id in roster["players"]}
    assert _delete(client, headers, roster["tournament_id"], roster["team_id"]).status_code == 200
    session.expire_all()
    canceled = session.exec(select(TeamPhotoSmsNotice).where(TeamPhotoSmsNotice.team_id == roster["team_id"])).all()
    assert len(canceled) == 2
    assert {notice.status for notice in canceled} == {"CANCELED"}
    assert {player_id: session.get(Player, player_id).sms_consent_status for player_id in roster["players"]} == consent
    calls: list[dict] = []
    assert dispatch_team_photo_notices(session, send=_sender(calls)) == 0
    assert calls == []

    assert _save(client, headers, roster["tournament_id"], roster["team_id"], "upload-cancel-2", _jpeg("blue")).status_code == 200
    session.expire_all()
    notices = session.exec(select(TeamPhotoSmsNotice).where(TeamPhotoSmsNotice.team_id == roster["team_id"])).all()
    assert len(notices) == 4
    assert {notice.status for notice in notices if notice.photo_session_id == 1} == {"CANCELED"}
    assert {notice.status for notice in notices if notice.photo_session_id == 2} == {"PENDING"}
    assert dispatch_team_photo_notices(session, send=_sender(calls)) == 2
    assert len(calls) == 2
    session.expire_all()
    assert {notice.status for notice in session.exec(select(TeamPhotoSmsNotice).where(TeamPhotoSmsNotice.photo_session_id == 1)).all()} == {"CANCELED"}


def test_new_session_respects_redirect_texts_off_flag_and_stop(
    client: TestClient, session: Session, monkeypatch
):
    monkeypatch.setenv("TEAM_PHOTO_OBJECT_STORE", "memory")
    monkeypatch.setenv("TEAM_PHOTO_AUTO_SMS_ENABLED", "true")
    monkeypatch.setenv("PUBLIC_APP_URL", "https://photos.test")
    reset_memory_store()
    headers = _login(client)
    roster = _roster(session, p2_consent="opted_out")
    assert _save(client, headers, roster["tournament_id"], roster["team_id"], "upload-gate-1", _jpeg()).status_code == 200
    assert _delete(client, headers, roster["tournament_id"], roster["team_id"]).status_code == 200
    session.add(
        TournamentSmsSettings(
            tournament_id=roster["tournament_id"],
            texts_enabled=True,
            delivery_mode="redirect",
            redirect_phone="+15555550999",
        )
    )
    session.commit()
    assert _save(client, headers, roster["tournament_id"], roster["team_id"], "upload-gate-2", _jpeg("blue")).status_code == 200
    calls: list[dict] = []
    assert dispatch_team_photo_notices(session, send=_sender(calls)) == 1
    assert [call["to"] for call in calls] == ["+15555550999"]
    assert calls[0]["body"].startswith("[TEST redirect — intended +15555550101]")
    session.expire_all()
    opted_out = session.get(Player, roster["players"][1])
    assert opted_out.sms_consent_status == "opted_out"
    skipped = session.exec(
        select(TeamPhotoSmsNotice).where(
            TeamPhotoSmsNotice.photo_session_id == 2,
            TeamPhotoSmsNotice.phone_e164 == "+15555550102",
        )
    ).one()
    assert skipped.status == "SKIPPED_OPT_OUT"

    roster_off = _roster(session)
    session.add(TournamentSmsSettings(tournament_id=roster_off["tournament_id"], texts_enabled=False, delivery_mode="live"))
    session.commit()
    assert _save(client, headers, roster_off["tournament_id"], roster_off["team_id"], "upload-off-session", _jpeg()).status_code == 200
    assert _delete(client, headers, roster_off["tournament_id"], roster_off["team_id"]).status_code == 200
    assert _save(client, headers, roster_off["tournament_id"], roster_off["team_id"], "upload-off-next", _jpeg("blue")).status_code == 200
    calls.clear()
    assert dispatch_team_photo_notices(session, send=_sender(calls)) == 0
    assert calls == []
    assert {notice.status for notice in session.exec(select(TeamPhotoSmsNotice).where(TeamPhotoSmsNotice.team_id == roster_off["team_id"], TeamPhotoSmsNotice.photo_session_id == 2)).all()} == {"SKIPPED_TEXTS_OFF"}
    settings = session.exec(
        select(TournamentSmsSettings).where(TournamentSmsSettings.tournament_id == roster_off["tournament_id"])
    ).one()
    settings.texts_enabled = True
    session.add(settings)
    session.commit()
    assert dispatch_team_photo_notices(session, send=_sender(calls)) == 0
    assert calls == []

    monkeypatch.setenv("TEAM_PHOTO_AUTO_SMS_ENABLED", "false")
    silent = _roster(session)
    assert _save(client, headers, silent["tournament_id"], silent["team_id"], "upload-flag-session", _jpeg()).status_code == 200
    assert _delete(client, headers, silent["tournament_id"], silent["team_id"]).status_code == 200
    assert _save(client, headers, silent["tournament_id"], silent["team_id"], "upload-flag-next", _jpeg("blue")).status_code == 200
    session.expire_all()
    assert session.exec(select(TeamPhotoSmsNotice).where(TeamPhotoSmsNotice.team_id == silent["team_id"])).all() == []
    assert dispatch_team_photo_notices(session, send=_sender(calls)) == 0
    assert calls == []


def test_photo_session_columns_keep_existing_delivery_history(tmp_path):
    from sqlalchemy import create_engine, text

    from app.db_schema_patch import ensure_team_photo_sms_session_columns

    database = tmp_path / "legacy.db"
    engine = create_engine(f"sqlite:///{database}")
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE team_photo_share (
                    id INTEGER PRIMARY KEY,
                    tournament_id INTEGER NOT NULL,
                    team_id INTEGER NOT NULL,
                    photo_id INTEGER NOT NULL,
                    token VARCHAR(128) NOT NULL,
                    expires_at DATETIME NOT NULL,
                    revoked_at DATETIME,
                    created_at DATETIME NOT NULL
                )
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE team_photo_sms_notice (
                    id INTEGER PRIMARY KEY,
                    tournament_id INTEGER NOT NULL,
                    team_id INTEGER NOT NULL,
                    photo_id INTEGER NOT NULL,
                    player_id INTEGER,
                    phone_e164 VARCHAR,
                    notice_type VARCHAR(64) NOT NULL,
                    idempotency_key VARCHAR(200) NOT NULL,
                    status VARCHAR(40) NOT NULL,
                    provider_sid VARCHAR,
                    consent_status VARCHAR(40),
                    consent_source VARCHAR(80),
                    failure_code VARCHAR(80),
                    failure_reason VARCHAR(300),
                    retry_count INTEGER NOT NULL,
                    next_attempt_at DATETIME NOT NULL,
                    last_attempt_at DATETIME,
                    created_at DATETIME NOT NULL,
                    sent_at DATETIME,
                    delivered_at DATETIME
                )
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO team_photo_share
                    (id, tournament_id, team_id, photo_id, token, expires_at, revoked_at, created_at)
                VALUES
                    (1, 7, 9, 4, 'legacy-token', '2027-01-01 00:00:00', NULL, '2026-01-01 00:00:00')
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO team_photo_sms_notice (
                    id, tournament_id, team_id, photo_id, player_id, phone_e164, notice_type,
                    idempotency_key, status, provider_sid, consent_status, consent_source,
                    retry_count, next_attempt_at, created_at, sent_at, delivered_at
                ) VALUES (
                    5, 7, 9, 4, 3, '+15555550101', 'team_photo_ready',
                    'photo-sms:9:team_photo_ready:+15555550101', 'DELIVERED', 'SMKEEP',
                    'opted_in', 'registration',
                    0, '2026-01-01 00:00:00', '2026-01-01 00:00:00',
                    '2026-01-01 00:01:00', '2026-01-01 00:02:00'
                )
                """
            )
        )
    ensure_team_photo_sms_session_columns(engine)
    ensure_team_photo_sms_session_columns(engine)
    with engine.connect() as conn:
        share = conn.execute(text("SELECT generation, token, revoked_at FROM team_photo_share WHERE id = 1")).one()
        notice = conn.execute(
            text(
                """
                SELECT photo_session_id, status, provider_sid, idempotency_key, sent_at, delivered_at
                FROM team_photo_sms_notice WHERE id = 5
                """
            )
        ).one()
    assert share.generation == 1
    assert share.token == "legacy-token"
    assert share.revoked_at is None
    assert notice.photo_session_id == 1
    assert notice.status == "DELIVERED"
    assert notice.provider_sid == "SMKEEP"
    assert notice.idempotency_key == "photo-sms:9:team_photo_ready:+15555550101"
    assert notice.sent_at is not None
    assert notice.delivered_at is not None
    engine.dispose()


def test_photo_session_schema_refuses_an_incomplete_database(tmp_path):
    from sqlalchemy import create_engine

    from app.db_schema_patch import ensure_team_photo_sms_session_columns

    engine = create_engine(f"sqlite:///{tmp_path / 'empty.db'}")
    with pytest.raises(RuntimeError, match="incomplete"):
        ensure_team_photo_sms_session_columns(engine)
    engine.dispose()


def test_health_reports_session_columns_and_keeps_photo_sms_disabled(client: TestClient, monkeypatch):
    monkeypatch.delenv("TEAM_PHOTO_AUTO_SMS_ENABLED", raising=False)
    response = client.get("/api/health")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "healthy"
    assert body["team_photo_auto_sms_enabled"] is False
    assert body["team_photo_sms_tables_ready"] is True
    assert body["team_photo_sms_session_columns_ready"] is True

