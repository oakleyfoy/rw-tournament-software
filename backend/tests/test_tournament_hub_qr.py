"""Staff Tournament Hub QR API tests."""

from datetime import date

from sqlmodel import Session, delete

from app.models.auth_session import AuthSession
from app.models.schedule_version import ScheduleVersion
from app.models.tournament import Tournament
from app.models.user_account import UserAccount
from app.services.tournament_hub_qr import public_tournament_hub_path


def _tournament(session: Session, name: str = "Racquet War Destin") -> Tournament:
    tournament = Tournament(
        name=name,
        location="Destin",
        timezone="America/Chicago",
        start_date=date(2026, 9, 12),
        end_date=date(2026, 9, 13),
    )
    session.add(tournament)
    session.flush()
    return tournament


def test_public_tournament_hub_path_is_stable():
    assert public_tournament_hub_path(42) == "/t/42/hub"


def test_tournament_hub_qr_uses_public_origin(client, session, monkeypatch):
    monkeypatch.setenv("PUBLIC_APP_URL", "https://players.example.com")
    tournament = _tournament(session)
    version = ScheduleVersion(
        tournament_id=tournament.id,
        version_number=1,
        status="final",
    )
    session.add(version)
    session.flush()
    tournament.public_schedule_version_id = version.id
    session.add(tournament)
    session.commit()

    resp = client.get(f"/api/tournaments/{tournament.id}/tournament-hub-qr")
    assert resp.status_code == 200
    body = resp.json()
    assert body["tournament_id"] == tournament.id
    assert body["tournament_name"] == "Racquet War Destin"
    assert body["public_path"] == f"/t/{tournament.id}/hub"
    assert body["public_url"] == f"https://players.example.com/t/{tournament.id}/hub"
    assert body["published"] is True
    assert "team=" not in body["public_url"]


def test_tournament_hub_qr_available_before_publish(client, session, monkeypatch):
    monkeypatch.setenv("PUBLIC_APP_URL", "https://players.example.com")
    tournament = _tournament(session, name="Unpublished Cup")
    session.commit()

    resp = client.get(f"/api/tournaments/{tournament.id}/tournament-hub-qr")
    assert resp.status_code == 200
    body = resp.json()
    assert body["published"] is False
    assert body["public_url"] == f"https://players.example.com/t/{tournament.id}/hub"


def test_tournament_hub_qr_requires_auth_after_bootstrap(client, session):
    session.exec(delete(AuthSession))
    session.exec(delete(UserAccount))
    session.commit()
    created = client.post(
        "/api/auth/bootstrap-admin",
        json={"username": "hubadmin", "password": "password123", "display_name": "Hub Admin"},
    )
    assert created.status_code == 201
    tournament = _tournament(session)
    session.commit()

    denied = client.get(f"/api/tournaments/{tournament.id}/tournament-hub-qr")
    assert denied.status_code == 401

    login = client.post("/api/auth/login", json={"username": "hubadmin", "password": "password123"})
    token = login.json()["access_token"]
    allowed = client.get(
        f"/api/tournaments/{tournament.id}/tournament-hub-qr",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert allowed.status_code == 200


def test_missing_tournament_hub_qr_is_404(client, session):
    resp = client.get("/api/tournaments/999999/tournament-hub-qr")
    assert resp.status_code == 404
