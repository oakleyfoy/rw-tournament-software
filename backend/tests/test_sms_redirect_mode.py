"""Tests for SMS delivery modes: live, allowlist, and redirect-all."""

from datetime import date

import pytest
from sqlmodel import Session, select

from app.models.sms_log import SmsLog
from app.models.tournament_sms_settings import TournamentSmsSettings


@pytest.fixture(autouse=True)
def _force_twilio_dry_run(monkeypatch):
    import app.services.twilio_service as _mod

    monkeypatch.delenv("TWILIO_ACCOUNT_SID", raising=False)
    monkeypatch.delenv("TWILIO_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("TWILIO_FROM_NUMBER", raising=False)
    _mod._twilio_service = None


@pytest.fixture
def setup_tournament_with_teams(session: Session):
    from app.models.event import Event
    from app.models.team import Team
    from app.models.tournament import Tournament

    tournament = Tournament(
        name="SMS Redirect Mode Test",
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

    teams = [
        Team(
            event_id=event.id,
            name="Dee Dee / Mike",
            seed=1,
            p1_cell="9013593035",
            p2_cell="5551112222",
        ),
        Team(
            event_id=event.id,
            name="Yuki / Sal",
            seed=2,
            p1_cell="5553334444",
            p2_cell=None,
        ),
        Team(event_id=event.id, name="No Phone A", seed=3, p1_cell=None, p2_cell=None),
        Team(event_id=event.id, name="No Phone B", seed=4, p1_cell=None, p2_cell=None),
    ]
    session.add_all(teams)
    session.commit()
    for team in teams:
        session.refresh(team)
    return tournament, event, teams


def test_redirect_mode_requires_valid_phone(client, session, setup_tournament_with_teams):
    tournament, _, _ = setup_tournament_with_teams

    missing = client.patch(
        f"/api/tournaments/{tournament.id}/sms/settings",
        json={"delivery_mode": "redirect"},
    )
    assert missing.status_code == 400
    assert "redirect_phone" in missing.json()["detail"].lower()

    invalid = client.patch(
        f"/api/tournaments/{tournament.id}/sms/settings",
        json={"delivery_mode": "redirect", "redirect_phone": "NOT-A-PHONE"},
    )
    assert invalid.status_code == 400


def test_redirect_mode_sends_all_to_test_number(client, session, setup_tournament_with_teams, monkeypatch):
    tournament, _, _ = setup_tournament_with_teams
    captured: list[tuple[str, str]] = []

    class _CaptureTwilio:
        is_configured = False
        from_number = ""

        def send_sms(self, to: str, body: str, *, status_callback_url=None):
            captured.append((to, body))
            return {"sid": f"SM{len(captured)}", "status": "sent", "error": None}

    monkeypatch.setattr("app.routes.sms.get_twilio_service", lambda: _CaptureTwilio())

    set_resp = client.patch(
        f"/api/tournaments/{tournament.id}/sms/settings",
        json={
            "delivery_mode": "redirect",
            "redirect_phone": "9703092022",
        },
    )
    assert set_resp.status_code == 200
    assert set_resp.json()["delivery_mode"] == "redirect"
    assert set_resp.json()["redirect_phone"] == "+19703092022"
    assert set_resp.json()["test_mode"] is False

    resp = client.post(
        f"/api/tournaments/{tournament.id}/sms/blast",
        json={"message": "Court assigned now"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["redirected"] == data["sent"]
    assert data["sent"] >= 3
    assert data["skipped_test_mode"] == 0
    assert all(to == "+19703092022" for to, _ in captured)
    assert len(captured) == data["sent"]

    # Each intended recipient produces a separately identifiable redirected body.
    intended_headers = [body.split("\n", 1)[0] for _, body in captured]
    assert len(set(intended_headers)) == len(intended_headers)
    assert all(h.startswith("[TEST redirect — intended +") for h in intended_headers)

    logs = session.exec(select(SmsLog).where(SmsLog.tournament_id == tournament.id)).all()
    redirected_logs = [log for log in logs if log.status == "sent_redirect"]
    assert len(redirected_logs) == data["sent"]
    assert all(log.phone_number == "+19703092022" for log in redirected_logs)
    assert all(log.intended_phone_number and log.intended_phone_number != "+19703092022" for log in redirected_logs)


def test_redirect_mode_never_falls_back_to_live_without_phone(
    client, session, setup_tournament_with_teams, monkeypatch
):
    tournament, _, _ = setup_tournament_with_teams
    settings = TournamentSmsSettings(
        tournament_id=tournament.id,
        delivery_mode="redirect",
        redirect_phone=None,
        test_mode=False,
    )
    session.add(settings)
    session.commit()

    sent_targets: list[str] = []

    class _CaptureTwilio:
        is_configured = False

        def send_sms(self, to: str, body: str, *, status_callback_url=None):
            sent_targets.append(to)
            return {"sid": "SM1", "status": "sent", "error": None}

    monkeypatch.setattr("app.routes.sms.get_twilio_service", lambda: _CaptureTwilio())

    resp = client.post(
        f"/api/tournaments/{tournament.id}/sms/blast",
        json={"message": "Should not send"},
    )
    assert resp.status_code == 400
    assert sent_targets == []


def test_texts_enabled_off_blocks_redirect(client, session, setup_tournament_with_teams, monkeypatch):
    tournament, _, _ = setup_tournament_with_teams
    sent_targets: list[str] = []

    class _CaptureTwilio:
        is_configured = False

        def send_sms(self, to: str, body: str, *, status_callback_url=None):
            sent_targets.append(to)
            return {"sid": "SM1", "status": "sent", "error": None}

    monkeypatch.setattr("app.routes.sms.get_twilio_service", lambda: _CaptureTwilio())

    client.patch(
        f"/api/tournaments/{tournament.id}/sms/settings",
        json={
            "delivery_mode": "redirect",
            "redirect_phone": "9703092022",
            "texts_enabled": False,
        },
    )
    resp = client.post(
        f"/api/tournaments/{tournament.id}/sms/blast",
        json={"message": "Blocked by master switch"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["sent"] == 0
    assert data["redirected"] == 0
    assert data["total"] == 0
    assert sent_targets == []


def test_allowlist_mode_unchanged(client, session, setup_tournament_with_teams):
    tournament, _, _ = setup_tournament_with_teams
    client.patch(
        f"/api/tournaments/{tournament.id}/sms/settings",
        json={
            "delivery_mode": "allowlist",
            "test_allowlist": "9013593035",
        },
    )
    resp = client.post(
        f"/api/tournaments/{tournament.id}/sms/blast",
        json={"message": "Allowlist check"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["sent"] == 1
    assert data["skipped_test_mode"] == 2
    assert data["redirected"] == 0
    allowed = [r for r in data["results"] if r["status"] != "blocked_test_mode"]
    assert allowed[0]["phone"] == "+19013593035"


def test_redirect_blast_does_not_inject_allowlist(client, session, setup_tournament_with_teams, monkeypatch):
    tournament, _, _ = setup_tournament_with_teams
    captured: list[str] = []

    class _CaptureTwilio:
        is_configured = False

        def send_sms(self, to: str, body: str, *, status_callback_url=None):
            captured.append(to)
            return {"sid": f"SM{len(captured)}", "status": "sent", "error": None}

    monkeypatch.setattr("app.routes.sms.get_twilio_service", lambda: _CaptureTwilio())

    client.patch(
        f"/api/tournaments/{tournament.id}/sms/settings",
        json={
            "delivery_mode": "redirect",
            "redirect_phone": "9703092022",
            "test_allowlist": "9703092022,9013593035",
        },
    )
    resp = client.post(
        f"/api/tournaments/{tournament.id}/sms/blast",
        json={"message": "No inject"},
    )
    assert resp.status_code == 200
    # Redirect destination itself is not injected as an extra intended recipient.
    intended = {row["intended_phone"] for row in resp.json()["results"] if row["status"] == "sent_redirect"}
    assert "+19703092022" not in intended
    assert all(to == "+19703092022" for to in captured)


def test_redirect_dedupe_keyed_on_intended_phone(client, session, setup_tournament_with_teams, monkeypatch):
    tournament, _, teams = setup_tournament_with_teams
    captured: list[tuple[str, str]] = []

    class _CaptureTwilio:
        is_configured = False

        def send_sms(self, to: str, body: str, *, status_callback_url=None):
            captured.append((to, body))
            return {"sid": f"SM{len(captured)}", "status": "sent", "error": None}

    monkeypatch.setattr("app.routes.sms.get_twilio_service", lambda: _CaptureTwilio())

    client.patch(
        f"/api/tournaments/{tournament.id}/sms/settings",
        json={"delivery_mode": "redirect", "redirect_phone": "9703092022"},
    )

    team_id = teams[0].id
    first = client.post(
        f"/api/tournaments/{tournament.id}/sms/team/{team_id}",
        json={"message": "Team text", "dedupe_key": "redirect-dedupe-1"},
    )
    assert first.status_code == 200
    first_data = first.json()
    assert first_data["sent"] == 2
    assert first_data["redirected"] == 2

    second = client.post(
        f"/api/tournaments/{tournament.id}/sms/team/{team_id}",
        json={"message": "Team text again", "dedupe_key": "redirect-dedupe-1"},
    )
    assert second.status_code == 200
    second_data = second.json()
    assert second_data["sent"] == 0
    assert second_data["skipped_dedupe"] == 2
    assert len(captured) == 2


def test_blocked_test_mode_consumes_dedupe_then_live_skips(client, session, setup_tournament_with_teams):
    tournament, _, teams = setup_tournament_with_teams
    team_id = teams[0].id

    client.patch(
        f"/api/tournaments/{tournament.id}/sms/settings",
        json={"delivery_mode": "allowlist", "test_allowlist": "9999999999"},
    )
    blocked = client.post(
        f"/api/tournaments/{tournament.id}/sms/team/{team_id}",
        json={"message": "Blocked first", "dedupe_key": "block-then-live"},
    )
    assert blocked.status_code == 200
    assert blocked.json()["skipped_test_mode"] == 2
    assert blocked.json()["sent"] == 0

    client.patch(
        f"/api/tournaments/{tournament.id}/sms/settings",
        json={"delivery_mode": "live"},
    )
    live = client.post(
        f"/api/tournaments/{tournament.id}/sms/team/{team_id}",
        json={"message": "Live retry", "dedupe_key": "block-then-live"},
    )
    assert live.status_code == 200
    assert live.json()["sent"] == 0
    assert live.json()["skipped_dedupe"] == 2


def test_redirect_respects_intended_consent(client, session, setup_tournament_with_teams, monkeypatch):
    from app.models.player import Player

    tournament, _, teams = setup_tournament_with_teams
    opted_out = Player(
        tournament_id=tournament.id,
        full_name="Opted Out",
        phone_e164="+19013593035",
        sms_consent_status="opted_out",
    )
    session.add(opted_out)
    session.commit()

    captured: list[str] = []

    class _CaptureTwilio:
        is_configured = False

        def send_sms(self, to: str, body: str, *, status_callback_url=None):
            captured.append(body)
            return {"sid": f"SM{len(captured)}", "status": "sent", "error": None}

    monkeypatch.setattr("app.routes.sms.get_twilio_service", lambda: _CaptureTwilio())

    client.patch(
        f"/api/tournaments/{tournament.id}/sms/settings",
        json={"delivery_mode": "redirect", "redirect_phone": "9703092022"},
    )
    resp = client.post(
        f"/api/tournaments/{tournament.id}/sms/team/{teams[0].id}",
        json={"message": "Consent check"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["skipped_consent"] == 1
    assert data["redirected"] == 1
    assert data["sent"] == 1
    # Opted-out intended recipient must never produce a redirected Twilio send.
    assert not any("intended +19013593035" in body for body in captured)
    assert any("intended +15551112222" in body for body in captured)


def test_mutually_exclusive_modes_via_api(client, session, setup_tournament_with_teams):
    tournament, _, _ = setup_tournament_with_teams

    allowlist = client.patch(
        f"/api/tournaments/{tournament.id}/sms/settings",
        json={"delivery_mode": "allowlist", "test_allowlist": "9013593035"},
    )
    assert allowlist.json()["delivery_mode"] == "allowlist"
    assert allowlist.json()["test_mode"] is True

    redirect = client.patch(
        f"/api/tournaments/{tournament.id}/sms/settings",
        json={"delivery_mode": "redirect", "redirect_phone": "9703092022"},
    )
    assert redirect.json()["delivery_mode"] == "redirect"
    assert redirect.json()["test_mode"] is False

    live = client.patch(
        f"/api/tournaments/{tournament.id}/sms/settings",
        json={"delivery_mode": "live"},
    )
    assert live.json()["delivery_mode"] == "live"
    assert live.json()["test_mode"] is False

    # Legacy test_mode=True still maps to allowlist.
    legacy = client.patch(
        f"/api/tournaments/{tournament.id}/sms/settings",
        json={"test_mode": True},
    )
    assert legacy.json()["delivery_mode"] == "allowlist"
    assert legacy.json()["test_mode"] is True
