"""Manual Rebuild / Sync Player Contacts safety action."""

from datetime import date

import pytest
from sqlmodel import Session, select

from app.models.event import Event
from app.models.player import Player
from app.models.sms_log import SmsLog
from app.models.sms_phone_list import SmsPhoneListMember
from app.models.team import Team
from app.models.team_player import TeamPlayer
from app.models.tournament import Tournament
from app.services.twilio_service import format_e164

JANE_PHONE = "9015551111"
MARY_PHONE = "9015552222"
ANN_PHONE = "9015553333"
JANE_E164 = "+19015551111"
MARY_E164 = "+19015552222"
ANN_E164 = "+19015553333"
MANUAL_PHONE = "9015559999"


@pytest.fixture(autouse=True)
def _force_twilio_dry_run(monkeypatch):
    import app.services.twilio_service as twilio_mod

    monkeypatch.delenv("TWILIO_ACCOUNT_SID", raising=False)
    monkeypatch.delenv("TWILIO_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("TWILIO_FROM_NUMBER", raising=False)
    twilio_mod._twilio_service = None


def _create_tournament(session: Session) -> Tournament:
    tournament = Tournament(
        name="Rebuild Player Contacts Test",
        location="Memphis",
        timezone="America/New_York",
        start_date=date(2026, 3, 15),
        end_date=date(2026, 3, 16),
    )
    session.add(tournament)
    session.commit()
    session.refresh(tournament)
    return tournament


def _create_event(session: Session, tournament_id: int) -> Event:
    event = Event(
        tournament_id=tournament_id,
        name="Women's A",
        category="womens",
        team_count=2,
    )
    session.add(event)
    session.commit()
    session.refresh(event)
    return event


def _add_team(session: Session, event_id: int, name: str, p1: str, p2: str) -> Team:
    team = Team(
        event_id=event_id,
        name=name,
        player1_cellphone=p1,
        player2_cellphone=p2,
    )
    session.add(team)
    session.commit()
    session.refresh(team)
    return team


def _add_player(session: Session, tournament_id: int, name: str, phone: str) -> Player:
    player = Player(
        tournament_id=tournament_id,
        full_name=name,
        display_name=name,
        phone_e164=format_e164(phone),
        sms_consent_status="unknown",
        sms_consent_source="manual_seed",
    )
    session.add(player)
    session.commit()
    session.refresh(player)
    return player


def _slot_link(session: Session, team_id: int, slot: int) -> TeamPlayer | None:
    return session.exec(select(TeamPlayer).where(TeamPlayer.team_id == team_id, TeamPlayer.lineup_slot == slot)).first()


def _rebuild(client, tournament_id: int):
    return client.post(f"/api/tournaments/{tournament_id}/sms/sync-player-contacts")


def test_rebuild_repairs_missing_teamplayer_link(client, session):
    tournament = _create_tournament(session)
    event = _create_event(session, tournament.id)
    team = _add_team(session, event.id, "Jane Smith / Ann Partner", JANE_PHONE, ANN_PHONE)
    assert session.exec(select(TeamPlayer).where(TeamPlayer.team_id == team.id)).all() == []

    resp = _rebuild(client, tournament.id)
    assert resp.status_code == 200
    data = resp.json()
    assert data["links_created"] >= 2
    assert data["slots_checked"] == 2
    assert "Player contacts synchronized" in data["staff_message"]
    assert "No text messages were sent." in data["staff_message"]

    session.expire_all()
    assert _slot_link(session, team.id, 1) is not None
    assert _slot_link(session, team.id, 2) is not None
    assert team.name == "Jane Smith / Ann Partner"
    assert team.player1_cellphone == JANE_PHONE
    assert team.player2_cellphone == ANN_PHONE


def test_rebuild_replaces_incorrect_old_player_link(client, session):
    tournament = _create_tournament(session)
    event = _create_event(session, tournament.id)
    team = _add_team(session, event.id, "Mary Jones / Ann Partner", MARY_PHONE, ANN_PHONE)
    jane = _add_player(session, tournament.id, "Jane Smith", JANE_PHONE)
    mary = _add_player(session, tournament.id, "Mary Jones", MARY_PHONE)
    session.add(TeamPlayer(team_id=team.id, player_id=jane.id, lineup_slot=1, role="player", is_primary_contact=True))
    session.commit()

    resp = _rebuild(client, tournament.id)
    assert resp.status_code == 200
    assert resp.json()["links_updated"] >= 1

    session.expire_all()
    assert _slot_link(session, team.id, 1).player_id == mary.id
    assert session.get(Player, jane.id) is not None
    assert session.get(Player, jane.id).phone_e164 == JANE_E164


def test_rebuild_leaves_correct_link_unchanged(client, session):
    tournament = _create_tournament(session)
    event = _create_event(session, tournament.id)
    created = client.post(
        f"/api/events/{event.id}/teams",
        json={
            "name": "Jane Smith / Ann Partner",
            "player1_cellphone": JANE_PHONE,
            "player2_cellphone": ANN_PHONE,
        },
    )
    assert created.status_code == 201
    team_id = created.json()["id"]
    session.expire_all()
    before = session.exec(select(TeamPlayer).where(TeamPlayer.team_id == team_id)).all()
    before_ids = {(link.id, link.player_id, link.lineup_slot) for link in before}
    assert len(before_ids) == 2

    resp = _rebuild(client, tournament.id)
    assert resp.status_code == 200
    data = resp.json()
    assert data["links_created"] == 0
    assert data["links_updated"] == 0
    assert data["links_removed"] == 0
    assert data["already_correct"] == 2

    session.expire_all()
    after = session.exec(select(TeamPlayer).where(TeamPlayer.team_id == team_id)).all()
    assert {(link.id, link.player_id, link.lineup_slot) for link in after} == before_ids


def test_rebuild_creates_new_player_from_current_team_data(client, session):
    tournament = _create_tournament(session)
    event = _create_event(session, tournament.id)
    _add_team(session, event.id, "Mary Jones / Ann Partner", MARY_PHONE, ANN_PHONE)
    assert session.exec(select(Player).where(Player.tournament_id == tournament.id)).all() == []

    resp = _rebuild(client, tournament.id)
    assert resp.status_code == 200
    assert resp.json()["players_created"] >= 2

    session.expire_all()
    phones = {
        player.phone_e164 for player in session.exec(select(Player).where(Player.tournament_id == tournament.id)).all()
    }
    assert MARY_E164 in phones
    assert ANN_E164 in phones


def test_rebuild_does_not_delete_historical_player(client, session):
    tournament = _create_tournament(session)
    event = _create_event(session, tournament.id)
    _add_team(session, event.id, "Mary Jones / Ann Partner", MARY_PHONE, ANN_PHONE)
    jane = _add_player(session, tournament.id, "Jane Smith", JANE_PHONE)
    jane_id = jane.id

    _rebuild(client, tournament.id)
    session.expire_all()
    leftover = session.get(Player, jane_id)
    assert leftover is not None
    assert leftover.phone_e164 == JANE_E164
    jane_links = session.exec(select(TeamPlayer).where(TeamPlayer.player_id == jane_id)).all()
    assert jane_links == []


def test_rebuild_is_idempotent(client, session):
    tournament = _create_tournament(session)
    event = _create_event(session, tournament.id)
    _add_team(session, event.id, "Jane Smith / Ann Partner", JANE_PHONE, ANN_PHONE)

    first = _rebuild(client, tournament.id)
    assert first.status_code == 200
    assert first.json()["links_created"] >= 2

    second = _rebuild(client, tournament.id)
    assert second.status_code == 200
    data = second.json()
    assert data["players_created"] == 0
    assert data["players_updated"] == 0
    assert data["links_created"] == 0
    assert data["links_updated"] == 0
    assert data["links_removed"] == 0
    assert data["already_correct"] == 2
    assert data["slots_checked"] == 2


def test_rebuild_does_not_call_sms_send(client, session, monkeypatch):
    tournament = _create_tournament(session)
    event = _create_event(session, tournament.id)
    _add_team(session, event.id, "Jane Smith / Ann Partner", JANE_PHONE, ANN_PHONE)

    calls: list[str] = []

    def _blocked_send(self, *args, **kwargs):
        calls.append("send_sms")
        raise AssertionError("SMS send should not run during rebuild")

    def _blocked_bulk(self, *args, **kwargs):
        calls.append("send_bulk")
        raise AssertionError("SMS bulk send should not run during rebuild")

    monkeypatch.setattr("app.services.twilio_service.TwilioService.send_sms", _blocked_send)
    monkeypatch.setattr("app.services.twilio_service.TwilioService.send_bulk", _blocked_bulk)

    resp = _rebuild(client, tournament.id)
    assert resp.status_code == 200
    assert calls == []
    assert session.exec(select(SmsLog).where(SmsLog.tournament_id == tournament.id)).all() == []


def test_rebuild_leaves_text_list_untouched(client, session):
    tournament = _create_tournament(session)
    event = _create_event(session, tournament.id)
    _add_team(session, event.id, "Jane Smith / Ann Partner", JANE_PHONE, ANN_PHONE)

    phone_list = client.post(
        f"/api/tournaments/{tournament.id}/sms/phone-lists",
        json={"name": "Manual Recipients"},
    ).json()
    imported = client.post(
        f"/api/tournaments/{tournament.id}/sms/phone-lists/{phone_list['id']}/import",
        json={"raw_text": f"Volunteer Desk\t{MANUAL_PHONE}\nJane Smith\t{JANE_PHONE}"},
    )
    assert imported.status_code == 200
    before = imported.json()["phone_list"]["members"]
    before_rows = {(row["raw_name"], format_e164(row["phone_number"])) for row in before}

    resp = _rebuild(client, tournament.id)
    assert resp.status_code == 200

    after_lists = client.get(f"/api/tournaments/{tournament.id}/sms/phone-lists").json()
    after = after_lists[0]["members"]
    after_rows = {(row["raw_name"], format_e164(row["phone_number"])) for row in after}
    assert after_rows == before_rows
    session.expire_all()
    members = session.exec(select(SmsPhoneListMember).where(SmsPhoneListMember.phone_list_id == phone_list["id"])).all()
    assert len(members) == 2
