"""Player substitution keeps tournament texting eligibility in sync."""

from datetime import date

import pytest
from sqlmodel import Session, select

from app.models.event import Event
from app.models.match import Match
from app.models.match_player_checkin import MatchPlayerCheckIn
from app.models.player import Player
from app.models.schedule_version import ScheduleVersion
from app.models.sms_log import SmsLog
from app.models.team import Team
from app.models.team_player import TeamPlayer
from app.models.tournament import Tournament
from app.services.player_roster_sync import (
    detect_slot_substitutions,
    snapshot_team_slots,
)
from app.services.twilio_service import format_e164

JANE_PHONE = "9015551111"
MARY_PHONE = "9015552222"
ANN_PHONE = "9015553333"
MIXED_PARTNER_PHONE = "9015554444"
MANUAL_PHONE = "9015559999"

JANE_E164 = "+19015551111"
MARY_E164 = "+19015552222"
ANN_E164 = "+19015553333"
MIXED_PARTNER_E164 = "+19015554444"
MANUAL_E164 = "+19015559999"


@pytest.fixture(autouse=True)
def _force_twilio_dry_run(monkeypatch):
    import app.services.twilio_service as twilio_mod

    monkeypatch.delenv("TWILIO_ACCOUNT_SID", raising=False)
    monkeypatch.delenv("TWILIO_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("TWILIO_FROM_NUMBER", raising=False)
    twilio_mod._twilio_service = None


def _create_tournament(session: Session) -> Tournament:
    tournament = Tournament(
        name="Substitution SMS Test",
        location="Memphis",
        timezone="America/New_York",
        start_date=date(2026, 3, 15),
        end_date=date(2026, 3, 16),
    )
    session.add(tournament)
    session.commit()
    session.refresh(tournament)
    return tournament


def _create_event(session: Session, tournament_id: int, name: str, category: str) -> Event:
    event = Event(
        tournament_id=tournament_id,
        name=name,
        category=category,
        team_count=2,
    )
    session.add(event)
    session.commit()
    session.refresh(event)
    return event


def _preview_phones(client, tournament_id: int, path: str) -> set[str]:
    resp = client.post(
        f"/api/tournaments/{tournament_id}/sms/{path}",
        json={"message": "Eligibility preview only"},
    )
    assert resp.status_code == 200
    return {phone for row in resp.json()["recipients"] for phone in row["phones"]}


def _player_phones(client, tournament_id: int) -> set[str]:
    resp = client.get(f"/api/tournaments/{tournament_id}/sms/players")
    assert resp.status_code == 200
    return {row["phone_e164"] for row in resp.json()}


def _player_by_phone(session: Session, tournament_id: int, phone: str) -> Player | None:
    e164 = format_e164(phone)
    return session.exec(select(Player).where(Player.tournament_id == tournament_id, Player.phone_e164 == e164)).first()


def _slot_player_id(session: Session, team_id: int, slot: int) -> int | None:
    link = session.exec(select(TeamPlayer).where(TeamPlayer.team_id == team_id, TeamPlayer.lineup_slot == slot)).first()
    return link.player_id if link else None


def _sms_log_count(session: Session, tournament_id: int) -> int:
    return len(session.exec(select(SmsLog).where(SmsLog.tournament_id == tournament_id)).all())


def test_jane_to_mary_event_sms_uses_mary_only(client, session):
    tournament = _create_tournament(session)
    womens = _create_event(session, tournament.id, "Women's A", "womens")
    created = client.post(
        f"/api/events/{womens.id}/teams",
        json={
            "name": "Jane Smith / Ann Partner",
            "player1_cellphone": JANE_PHONE,
            "player2_cellphone": ANN_PHONE,
        },
    )
    assert created.status_code == 201
    team_id = created.json()["id"]

    updated = client.patch(
        f"/api/events/{womens.id}/teams/{team_id}",
        json={
            "name": "Mary Jones / Ann Partner",
            "player1_cellphone": MARY_PHONE,
        },
    )
    assert updated.status_code == 200
    body = updated.json()
    assert body["staff_message"]
    assert "Mary Jones replaced Jane Smith on Women's A" in body["staff_message"]
    assert "Text List has not been changed" in body["staff_message"]
    assert body["text_list_sync_required"] is True

    phones = _preview_phones(client, tournament.id, f"preview/event/{womens.id}")
    assert MARY_E164 in phones
    assert ANN_E164 in phones
    assert JANE_E164 not in phones
    assert _sms_log_count(session, tournament.id) == 0


def test_jane_to_mary_tournament_sms_excludes_jane_without_other_participation(client, session):
    tournament = _create_tournament(session)
    womens = _create_event(session, tournament.id, "Women's A", "womens")
    created = client.post(
        f"/api/events/{womens.id}/teams",
        json={
            "name": "Jane Smith / Ann Partner",
            "player1_cellphone": JANE_PHONE,
            "player2_cellphone": ANN_PHONE,
        },
    )
    team_id = created.json()["id"]
    client.patch(
        f"/api/events/{womens.id}/teams/{team_id}",
        json={"name": "Mary Jones / Ann Partner", "player1_cellphone": MARY_PHONE},
    )

    phones = _preview_phones(client, tournament.id, "preview/blast")
    assert MARY_E164 in phones
    assert JANE_E164 not in phones
    assert _sms_log_count(session, tournament.id) == 0


def test_jane_remains_eligible_when_still_on_mixed(client, session):
    tournament = _create_tournament(session)
    womens = _create_event(session, tournament.id, "Women's A", "womens")
    mixed = _create_event(session, tournament.id, "Mixed B", "mixed")
    womens_team = client.post(
        f"/api/events/{womens.id}/teams",
        json={
            "name": "Jane Smith / Ann Partner",
            "player1_cellphone": JANE_PHONE,
            "player2_cellphone": ANN_PHONE,
        },
    ).json()
    client.post(
        f"/api/events/{mixed.id}/teams",
        json={
            "name": "Jane Smith / Mixed Partner",
            "player1_cellphone": JANE_PHONE,
            "player2_cellphone": MIXED_PARTNER_PHONE,
        },
    )

    client.patch(
        f"/api/events/{womens.id}/teams/{womens_team['id']}",
        json={"name": "Mary Jones / Ann Partner", "player1_cellphone": MARY_PHONE},
    )

    womens_phones = _preview_phones(client, tournament.id, f"preview/event/{womens.id}")
    mixed_phones = _preview_phones(client, tournament.id, f"preview/event/{mixed.id}")
    blast_phones = _preview_phones(client, tournament.id, "preview/blast")
    picker = _player_phones(client, tournament.id)

    assert MARY_E164 in womens_phones
    assert JANE_E164 not in womens_phones
    assert JANE_E164 in mixed_phones
    assert JANE_E164 in blast_phones
    assert MARY_E164 in blast_phones
    assert JANE_E164 in picker
    assert MARY_E164 in picker
    session.expire_all()
    assert _player_by_phone(session, tournament.id, JANE_PHONE) is not None


def test_existing_mary_player_is_reused(client, session):
    tournament = _create_tournament(session)
    womens = _create_event(session, tournament.id, "Women's A", "womens")
    created = client.post(
        f"/api/events/{womens.id}/teams",
        json={
            "name": "Jane Smith / Ann Partner",
            "player1_cellphone": JANE_PHONE,
            "player2_cellphone": ANN_PHONE,
        },
    )
    team_id = created.json()["id"]

    existing_mary = Player(
        tournament_id=tournament.id,
        full_name="Mary Jones",
        display_name="Mary Jones",
        phone_e164=MARY_E164,
        sms_consent_status="unknown",
        sms_consent_source="manual_seed",
    )
    session.add(existing_mary)
    session.commit()
    session.refresh(existing_mary)
    mary_id = existing_mary.id

    client.patch(
        f"/api/events/{womens.id}/teams/{team_id}",
        json={"name": "Mary Jones / Ann Partner", "player1_cellphone": MARY_PHONE},
    )
    session.expire_all()

    marys = session.exec(
        select(Player).where(Player.tournament_id == tournament.id, Player.phone_e164 == MARY_E164)
    ).all()
    assert len(marys) == 1
    assert marys[0].id == mary_id
    assert _slot_player_id(session, team_id, 1) == mary_id


def test_new_mary_creates_and_links_player(client, session):
    tournament = _create_tournament(session)
    womens = _create_event(session, tournament.id, "Women's A", "womens")
    created = client.post(
        f"/api/events/{womens.id}/teams",
        json={
            "name": "Jane Smith / Ann Partner",
            "player1_cellphone": JANE_PHONE,
            "player2_cellphone": ANN_PHONE,
        },
    )
    team_id = created.json()["id"]
    assert _player_by_phone(session, tournament.id, MARY_PHONE) is None

    client.patch(
        f"/api/events/{womens.id}/teams/{team_id}",
        json={"name": "Mary Jones / Ann Partner", "player1_cellphone": MARY_PHONE},
    )
    session.expire_all()

    mary = _player_by_phone(session, tournament.id, MARY_PHONE)
    jane = _player_by_phone(session, tournament.id, JANE_PHONE)
    assert mary is not None
    assert jane is not None
    assert _slot_player_id(session, team_id, 1) == mary.id
    jane_links = session.exec(select(TeamPlayer).where(TeamPlayer.player_id == jane.id)).all()
    assert jane_links == []


def test_replace_player1_leaves_player2_link(client, session):
    tournament = _create_tournament(session)
    womens = _create_event(session, tournament.id, "Women's A", "womens")
    created = client.post(
        f"/api/events/{womens.id}/teams",
        json={
            "name": "Jane Smith / Ann Partner",
            "player1_cellphone": JANE_PHONE,
            "player2_cellphone": ANN_PHONE,
        },
    )
    team_id = created.json()["id"]
    session.expire_all()
    ann_id = _slot_player_id(session, team_id, 2)

    client.patch(
        f"/api/events/{womens.id}/teams/{team_id}",
        json={"name": "Mary Jones / Ann Partner", "player1_cellphone": MARY_PHONE},
    )
    session.expire_all()
    assert _slot_player_id(session, team_id, 2) == ann_id
    assert _player_by_phone(session, tournament.id, ANN_PHONE).id == ann_id


def test_replace_both_players_updates_both_links(client, session):
    tournament = _create_tournament(session)
    womens = _create_event(session, tournament.id, "Women's A", "womens")
    created = client.post(
        f"/api/events/{womens.id}/teams",
        json={
            "name": "Jane Smith / Ann Partner",
            "player1_cellphone": JANE_PHONE,
            "player2_cellphone": ANN_PHONE,
        },
    )
    team_id = created.json()["id"]
    client.patch(
        f"/api/events/{womens.id}/teams/{team_id}",
        json={
            "name": "Mary Jones / Pat New",
            "player1_cellphone": MARY_PHONE,
            "player2_cellphone": MIXED_PARTNER_PHONE,
        },
    )
    session.expire_all()
    assert _slot_player_id(session, team_id, 1) == _player_by_phone(session, tournament.id, MARY_PHONE).id
    assert _slot_player_id(session, team_id, 2) == _player_by_phone(session, tournament.id, MIXED_PARTNER_PHONE).id
    assert _player_by_phone(session, tournament.id, JANE_PHONE) is not None
    assert _player_by_phone(session, tournament.id, ANN_PHONE) is not None


def test_phone_formatting_only_is_not_a_substitution(client, session):
    tournament = _create_tournament(session)
    womens = _create_event(session, tournament.id, "Women's A", "womens")
    created = client.post(
        f"/api/events/{womens.id}/teams",
        json={
            "name": "Mary Jones / Ann Partner",
            "player1_cellphone": "(901) 555-2222",
            "player2_cellphone": ANN_PHONE,
        },
    )
    team_id = created.json()["id"]
    session.expire_all()
    mary_id = _slot_player_id(session, team_id, 1)

    updated = client.patch(
        f"/api/events/{womens.id}/teams/{team_id}",
        json={"player1_cellphone": "901-555-2222"},
    )
    assert updated.status_code == 200
    assert updated.json()["player_substitutions"] == []
    assert updated.json()["staff_message"] is None
    session.expire_all()
    assert _slot_player_id(session, team_id, 1) == mary_id
    assert len(session.exec(select(Player).where(Player.phone_e164 == MARY_E164)).all()) == 1


def test_former_player_hidden_from_picker_until_other_event_remains(client, session):
    tournament = _create_tournament(session)
    womens = _create_event(session, tournament.id, "Women's A", "womens")
    mixed = _create_event(session, tournament.id, "Mixed B", "mixed")
    womens_team = client.post(
        f"/api/events/{womens.id}/teams",
        json={
            "name": "Jane Smith / Ann Partner",
            "player1_cellphone": JANE_PHONE,
            "player2_cellphone": ANN_PHONE,
        },
    ).json()
    mixed_team = client.post(
        f"/api/events/{mixed.id}/teams",
        json={
            "name": "Jane Smith / Mixed Partner",
            "player1_cellphone": JANE_PHONE,
            "player2_cellphone": MIXED_PARTNER_PHONE,
        },
    ).json()

    client.patch(
        f"/api/events/{womens.id}/teams/{womens_team['id']}",
        json={"name": "Mary Jones / Ann Partner", "player1_cellphone": MARY_PHONE},
    )
    assert JANE_E164 in _player_phones(client, tournament.id)

    client.patch(
        f"/api/events/{mixed.id}/teams/{mixed_team['id']}",
        json={"name": "Sam Standin / Mixed Partner", "player1_cellphone": "9015556666"},
    )
    picker = _player_phones(client, tournament.id)
    assert JANE_E164 not in picker
    session.expire_all()
    assert _player_by_phone(session, tournament.id, JANE_PHONE) is not None


def test_text_list_roster_sync_replaces_former_player_and_keeps_manual(client, session):
    tournament = _create_tournament(session)
    womens = _create_event(session, tournament.id, "Women's A", "womens")
    created = client.post(
        f"/api/events/{womens.id}/teams",
        json={
            "name": "Jane Smith / Ann Partner",
            "player1_cellphone": JANE_PHONE,
            "player2_cellphone": ANN_PHONE,
        },
    )
    team_id = created.json()["id"]

    phone_list = client.post(
        f"/api/tournaments/{tournament.id}/sms/phone-lists",
        json={"name": "Tournament Text List"},
    ).json()
    imported = client.post(
        f"/api/tournaments/{tournament.id}/sms/phone-lists/{phone_list['id']}/import",
        json={"raw_text": f"Jane Smith\t{JANE_PHONE}\nAnn Partner\t{ANN_PHONE}\nVolunteer Desk\t{MANUAL_PHONE}"},
    )
    assert imported.status_code == 200

    client.patch(
        f"/api/events/{womens.id}/teams/{team_id}",
        json={"name": "Mary Jones / Ann Partner", "player1_cellphone": MARY_PHONE},
    )

    members_before = client.get(f"/api/tournaments/{tournament.id}/sms/phone-lists").json()[0]["members"]
    assert any(format_e164(row["phone_number"]) == JANE_E164 for row in members_before)
    assert any(format_e164(row["phone_number"]) == MANUAL_E164 for row in members_before)
    assert not any(format_e164(row["phone_number"]) == MARY_E164 for row in members_before)

    preview = client.get(f"/api/tournaments/{tournament.id}/sms/phone-lists/{phone_list['id']}/roster-sync")
    assert preview.status_code == 200
    data = preview.json()
    assert data["applied"] is False
    assert {row["phone"] for row in data["add"]} == {MARY_E164}
    assert {row["phone"] for row in data["remove"]} == {JANE_E164}
    assert data["unchanged_count"] == 2

    applied = client.post(f"/api/tournaments/{tournament.id}/sms/phone-lists/{phone_list['id']}/roster-sync")
    assert applied.status_code == 200
    applied_data = applied.json()
    assert applied_data["applied"] is True
    phones = {format_e164(row["phone_number"]) for row in applied_data["phone_list"]["members"]}
    assert MARY_E164 in phones
    assert ANN_E164 in phones
    assert MANUAL_E164 in phones
    assert JANE_E164 not in phones
    assert _sms_log_count(session, tournament.id) == 0


def test_checkin_stays_on_replaced_player_and_is_not_transferred(client, session):
    tournament = _create_tournament(session)
    womens = _create_event(session, tournament.id, "Women's A", "womens")
    created = client.post(
        f"/api/events/{womens.id}/teams",
        json={
            "name": "Jane Smith / Ann Partner",
            "player1_cellphone": JANE_PHONE,
            "player2_cellphone": ANN_PHONE,
        },
    )
    team_id = created.json()["id"]
    session.expire_all()
    jane = _player_by_phone(session, tournament.id, JANE_PHONE)
    assert jane is not None

    version = ScheduleVersion(tournament_id=tournament.id, version_number=1, status="final")
    session.add(version)
    session.commit()
    session.refresh(version)
    match = Match(
        tournament_id=tournament.id,
        event_id=womens.id,
        schedule_version_id=version.id,
        match_code="WA_E1_WF_R1_M01",
        match_type="WF",
        round_number=1,
        round_index=1,
        sequence_in_round=1,
        duration_minutes=60,
        team_a_id=team_id,
        placeholder_side_a="Jane Smith / Ann Partner",
        placeholder_side_b="TBD",
    )
    session.add(match)
    session.commit()
    session.refresh(match)
    checkin = MatchPlayerCheckIn(
        tournament_id=tournament.id,
        schedule_version_id=version.id,
        match_id=match.id,
        team_id=team_id,
        player_id=jane.id,
        side="A",
        checked_in=True,
    )
    session.add(checkin)
    session.commit()
    checkin_id = checkin.id

    client.patch(
        f"/api/events/{womens.id}/teams/{team_id}",
        json={"name": "Mary Jones / Ann Partner", "player1_cellphone": MARY_PHONE},
    )
    session.expire_all()
    mary = _player_by_phone(session, tournament.id, MARY_PHONE)
    jane_after = session.get(Player, jane.id)
    leftover = session.get(MatchPlayerCheckIn, checkin_id)
    assert jane_after is not None
    assert leftover is not None
    assert leftover.player_id == jane.id
    assert leftover.checked_in is True
    assert mary is not None
    assert leftover.player_id != mary.id
    mary_checkins = session.exec(select(MatchPlayerCheckIn).where(MatchPlayerCheckIn.player_id == mary.id)).all()
    assert mary_checkins == []
    assert _slot_player_id(session, team_id, 1) == mary.id


def test_name_only_sub_uses_existing_player_phone_not_replaced_partner(client, session):
    tournament = _create_tournament(session)
    womens = _create_event(session, tournament.id, "Women's A", "womens")
    mixed = _create_event(session, tournament.id, "Mixed 8", "mixed")
    client.post(
        f"/api/events/{womens.id}/teams",
        json={
            "name": "Darlene Oldenberg / Womens Partner",
            "player1_cellphone": MARY_PHONE,
            "player2_cellphone": ANN_PHONE,
        },
    )
    mixed_team = client.post(
        f"/api/events/{mixed.id}/teams",
        json={
            "name": "Old Partner / Brannan",
            "player1_cellphone": JANE_PHONE,
            "player2_cellphone": MIXED_PARTNER_PHONE,
        },
    ).json()

    updated = client.patch(
        f"/api/events/{mixed.id}/teams/{mixed_team['id']}",
        json={"name": "Darlene / Brannan"},
    )
    assert updated.status_code == 200

    phones = _preview_phones(client, tournament.id, f"preview/event/{mixed.id}")
    assert MARY_E164 in phones
    assert MIXED_PARTNER_E164 in phones
    assert JANE_E164 not in phones
    assert _sms_log_count(session, tournament.id) == 0


def test_detect_slot_substitutions_ignores_phone_formatting():
    team = Team(
        event_id=1,
        name="Mary Jones / Ann Partner",
        player1_cellphone="(901) 555-2222",
        player2_cellphone=ANN_PHONE,
    )
    before = snapshot_team_slots(team)
    team.player1_cellphone = "901-555-2222"
    after = snapshot_team_slots(team)
    assert detect_slot_substitutions(before, after, event_name="Women's A") == []
