"""Staff notes stay on the player, and a direct text is logged without claiming delivery."""

from datetime import date, time

from sqlmodel import select

from app.models.event import Event
from app.models.match import Match
from app.models.match_assignment import MatchAssignment
from app.models.player import Player
from app.models.schedule_slot import ScheduleSlot
from app.models.schedule_version import ScheduleVersion
from app.models.sms_log import SmsLog
from app.models.team import Team
from app.models.team_player import TeamPlayer
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
    note_id = next(note["id"] for note in notes if note["player_id"] == natalia.id and note["body"] == "Needs a late start")
    edited = client.patch(
        f"/api/desk/tournaments/{tournament.id}/player-notes/{note_id}",
        json={"body": "Needs a later start"},
    )
    assert edited.status_code == 200, edited.text
    changed = next(note for note in edited.json()["notes"] if note["id"] == note_id)
    assert changed["body"] == "Needs a later start"
    assert changed["created_at"]
    removed = client.delete(f"/api/desk/tournaments/{tournament.id}/player-notes/{note_id}")
    assert removed.status_code == 200, removed.text
    assert all(note["id"] != note_id for note in removed.json()["notes"])
    assert any(note["player_id"] == natalia.id for note in removed.json()["notes"])


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


def test_checkin_text_uses_the_team_cell_when_the_player_profile_has_none(client, session, monkeypatch):
    tournament = Tournament(
        name="Palm Springs copy",
        location="Test",
        timezone="America/Chicago",
        start_date=date(2026, 12, 4),
        end_date=date(2026, 12, 6),
        desk_management_mode="checkin_management",
    )
    session.add(tournament)
    session.flush()
    version = ScheduleVersion(tournament_id=tournament.id, version_number=1, status="draft", notes="Desk Draft")
    session.add(version)
    session.flush()
    event = Event(tournament_id=tournament.id, category="mixed", name="Mixed A", team_count=2)
    session.add(event)
    session.flush()
    alex_team = Team(
        event_id=event.id,
        name="Alex Bose / Jennifer Myers",
        display_name="Alex Bose / Jennifer Myers",
        seed=1,
        player1_cellphone="(760) 555-0101",
        player2_cellphone="(760) 555-0102",
        notes="Bring the banner",
    )
    other = Team(event_id=event.id, name="Pat Lee / Sam Ng", display_name="Pat Lee / Sam Ng", seed=2)
    session.add_all([alex_team, other])
    session.flush()
    alex = Player(tournament_id=tournament.id, full_name="Alex Bose")
    jennifer = Player(tournament_id=tournament.id, full_name="Jennifer Myers")
    session.add_all([alex, jennifer])
    session.flush()
    session.add_all([
        TeamPlayer(team_id=alex_team.id, player_id=alex.id, lineup_slot=1),
        TeamPlayer(team_id=alex_team.id, player_id=jennifer.id, lineup_slot=2),
    ])
    opening = Match(
        tournament_id=tournament.id,
        event_id=event.id,
        schedule_version_id=version.id,
        match_code="MIX_E1_WF_R1_M01",
        match_type="WF",
        round_number=1,
        round_index=1,
        sequence_in_round=1,
        duration_minutes=60,
        team_a_id=alex_team.id,
        team_b_id=other.id,
        placeholder_side_a="Seed 1",
        placeholder_side_b="Seed 2",
    )
    session.add(opening)
    session.flush()
    slot = ScheduleSlot(
        tournament_id=tournament.id,
        schedule_version_id=version.id,
        day_date=date(2026, 12, 4),
        start_time=time(9, 0),
        end_time=time(10, 0),
        court_number=1,
        court_label="1",
        block_minutes=60,
    )
    session.add(slot)
    session.flush()
    session.add(MatchAssignment(schedule_version_id=version.id, match_id=opening.id, slot_id=slot.id))
    session.commit()

    snapshot = client.get(f"/api/desk/tournaments/{tournament.id}/snapshot?version_id={version.id}")
    assert snapshot.status_code == 200, snapshot.text
    side = snapshot.json()["arrival_matches"][0]["side_a"]
    phones = {player["player_display"]: player["phone_e164"] for player in side["players"]}
    assert phones["Alex Bose"] == "(760) 555-0101"
    assert phones["Jennifer Myers"] == "(760) 555-0102"
    assert snapshot.json()["arrival_matches"][0]["team1_notes"] == "Bring the banner"

    listed = client.get(f"/api/desk/tournaments/{tournament.id}/teams")
    assert listed.status_code == 200, listed.text
    row = next(team for team in listed.json() if team["team_id"] == alex_team.id)
    assert row["player1_cellphone"] == "(760) 555-0101"
    assert row["player1_id"] == alex.id
    assert row["player2_id"] == jennifer.id
    assert row["notes"] == "Bring the banner"

    class _FakeTwilio:
        @property
        def is_configured(self) -> bool:
            return True

        def send_sms(self, to: str, body: str, *, status_callback_url: str | None = None):
            return {"sid": "SM_TEAM_CELL", "status": "queued", "error": None}

    monkeypatch.setattr("app.routes.sms.get_twilio_service", lambda: _FakeTwilio())
    sent = client.post(
        f"/api/tournaments/{tournament.id}/sms/player/{alex.id}",
        json={"message": "Court 4 is ready", "team_id": alex_team.id},
    )
    assert sent.status_code == 200, sent.text
    assert sent.json()["results"][0]["status"] == "queued"
    session.expire_all()
    log = session.exec(select(SmsLog).where(SmsLog.player_id == alex.id)).first()
    assert log is not None
    assert log.phone_number == "+17605550101"
    assert log.status == "queued"
