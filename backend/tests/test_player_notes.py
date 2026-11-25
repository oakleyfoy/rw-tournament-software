"""Staff notes stay on the player, and a direct text is logged without claiming delivery."""

from datetime import date

from sqlmodel import select

from app.models.player import Player
from app.models.sms_log import SmsLog
from app.models.tournament import Tournament


def test_player_notes_follow_the_player_and_do_not_copy_to_the_partner(client, session):
    tournament = Tournament(name="Notes", location="Test", timezone="America/Chicago", start_date=date(2026, 12, 4), end_date=date(2026, 12, 6))
    session.add(tournament)
    session.flush()
    natalia = Player(tournament_id=tournament.id, full_name="Natalia Stone", phone_e164="+15555550101")
    michael = Player(tournament_id=tournament.id, full_name="Michael Stone", phone_e164="+15555550102")
    session.add(natalia)
    session.add(michael)
    session.commit()

    one = client.post(
        f"/api/desk/tournaments/{tournament.id}/player-notes",
        json={"player_ids": [natalia.id], "body": "Needs a late start"},
    )
    assert one.status_code == 200, one.text
    saved = one.json()["notes"]
    assert [note["player_id"] for note in saved] == [natalia.id]
    assert saved[0]["body"] == "Needs a late start"

    both = client.post(
        f"/api/desk/tournaments/{tournament.id}/player-notes",
        json={"player_ids": [natalia.id, michael.id], "body": "Towels are at court 4"},
    )
    assert both.status_code == 200, both.text
    notes = both.json()["notes"]
    assert sum(1 for note in notes if note["player_id"] == natalia.id) == 2
    assert sum(1 for note in notes if note["player_id"] == michael.id) == 1
    assert notes[0]["body"] == "Towels are at court 4"


def test_player_text_is_logged_as_accepted_not_delivered(client, session, monkeypatch):
    tournament = Tournament(name="Texts", location="Test", timezone="America/Chicago", start_date=date(2026, 12, 4), end_date=date(2026, 12, 6))
    session.add(tournament)
    session.flush()
    player = Player(tournament_id=tournament.id, full_name="Natalia Stone", phone_e164="+15555550101")
    session.add(player)
    session.commit()

    class _FakeTwilio:
        @property
        def is_configured(self) -> bool:
            return True

        def send_sms(self, to: str, body: str, *, status_callback_url: str | None = None):
            return {"sid": "SM_TEST_NOTE", "status": "queued", "error": None}

    monkeypatch.setattr("app.routes.sms.get_twilio_service", lambda: _FakeTwilio())
    sent = client.post(
        f"/api/tournaments/{tournament.id}/sms/player/{player.id}",
        json={"message": "Court 4 is ready"},
    )
    assert sent.status_code == 200, sent.text
    assert sent.json()["results"][0]["status"] == "queued"
    assert sent.json()["results"][0]["status"] != "delivered"
    session.expire_all()
    log = session.exec(select(SmsLog).where(SmsLog.tournament_id == tournament.id)).first()
    assert log is not None
    assert log.player_id == player.id
    assert log.phone_number == "+15555550101"
    assert log.message_body == "Court 4 is ready"
    assert log.status == "queued"
    assert log.twilio_sid == "SM_TEST_NOTE"
