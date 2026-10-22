"""Registration Terms_Conditions becomes tournament SMS consent only with evidence."""

from datetime import date

from sqlmodel import Session, select

from app.models.event import Event
from app.models.player import Player
from app.models.sms_log import SmsLog
from app.models.team import Team
from app.models.team_photo import TeamOfficialPhoto
from app.models.team_photo_sms import TeamPhotoSmsNotice
from app.models.team_player import TeamPlayer
from app.models.tournament import Tournament
from app.services.canonical_teams import SnapshotPlayer, SnapshotTeam
from app.services.registration_sms_consent import apply_registration_sms_consent
from app.services.rw_os_import import snapshot_hash
from app.services.team_photo_sms import dispatch_team_photo_notices, queue_team_photo_sms


def _player(rw_id: str, phone: str, *, consent: str | None, at: str | None = "2026-09-01") -> SnapshotPlayer:
    return SnapshotPlayer(
        rw_id=rw_id,
        name=rw_id,
        rating=4.0,
        cellphone=phone,
        sms_consent=consent,
        sms_consent_source="registration_terms" if consent == "opted_in" else None,
        sms_consent_at=at if consent == "opted_in" else None,
        sms_consent_record_key="Registration_Web:900" if consent == "opted_in" else None,
    )


def _team(p1: SnapshotPlayer, p2: SnapshotPlayer) -> SnapshotTeam:
    return SnapshotTeam(
        team_key=f"{p1.rw_id}/{p2.rw_id}",
        draw_kind="mixed",
        draw_label="Mixed",
        player1=p1,
        player2=p2,
        team_rating=7.5,
        rating_status="complete",
        status="confirmed",
        bucket="active",
    )


def test_registration_consent_reconciles_unknown_and_preserves_opt_out(session: Session, monkeypatch):
    tournament = Tournament(
        name="Consent",
        location="Test",
        timezone="America/Chicago",
        start_date=date(2026, 10, 16),
        end_date=date(2026, 10, 18),
    )
    session.add(tournament)
    session.flush()
    documented = Player(
        tournament_id=tournament.id,
        full_name="Documented",
        phone_e164="+15555550101",
        sms_consent_status="unknown",
        sms_consent_source="team_phone_sync",
    )
    later_stop = Player(
        tournament_id=tournament.id,
        full_name="Stopped",
        phone_e164="+15555550102",
        sms_consent_status="opted_out",
        sms_consent_source="twilio_stop",
    )
    missing = Player(
        tournament_id=tournament.id,
        full_name="Missing",
        phone_e164="+15555550103",
        sms_consent_status="unknown",
        sms_consent_source="team_phone_sync",
    )
    partner = Player(
        tournament_id=tournament.id,
        full_name="Partner",
        phone_e164="+15555550104",
        sms_consent_status="unknown",
        sms_consent_source="team_phone_sync",
    )
    session.add(documented)
    session.add(later_stop)
    session.add(missing)
    session.add(partner)
    session.flush()

    teams = [
        _team(
            _player("11", "+15555550101", consent="opted_in"),
            _player("22", "+15555550102", consent="opted_in"),
        ),
        _team(
            _player("33", "+15555550103", consent=None),
            _player("44", "+15555550104", consent="opted_in"),
        ),
    ]
    preview = apply_registration_sms_consent(session, tournament.id, teams, write=False)
    assert preview == {
        "players": 4,
        "reconciled": 2,
        "already_opted_in": 0,
        "opted_out_preserved": 1,
        "unresolved": 1,
    }
    assert documented.sms_consent_status == "unknown"

    counts = apply_registration_sms_consent(session, tournament.id, teams)
    assert counts["reconciled"] == 2
    assert counts["opted_out_preserved"] == 1
    assert counts["unresolved"] == 1
    session.refresh(documented)
    session.refresh(later_stop)
    session.refresh(missing)
    session.refresh(partner)
    assert documented.sms_consent_status == "opted_in"
    assert documented.sms_consent_source == "registration_terms:Registration_Web:900"
    assert documented.sms_consented_at is not None
    assert partner.sms_consent_status == "opted_in"
    assert later_stop.sms_consent_status == "opted_out"
    assert later_stop.sms_consent_source == "twilio_stop"
    assert missing.sms_consent_status == "unknown"
    assert session.exec(select(SmsLog)).all() == []
    assert session.exec(select(TeamPhotoSmsNotice)).all() == []

    event = Event(tournament_id=tournament.id, category="mixed", name="Mixed", team_count=2)
    session.add(event)
    session.flush()
    team = Team(event_id=event.id, name="Documented / Partner", seed=1)
    session.add(team)
    session.flush()
    session.add(TeamPlayer(team_id=team.id, player_id=documented.id, lineup_slot=1))
    session.add(TeamPlayer(team_id=team.id, player_id=partner.id, lineup_slot=2))
    photo = TeamOfficialPhoto(
        team_id=team.id,
        tournament_id=tournament.id,
        storage_key="memory/consent-photo.jpg",
        byte_size=10,
    )
    session.add(photo)
    session.flush()
    monkeypatch.setenv("TEAM_PHOTO_AUTO_SMS_ENABLED", "true")
    monkeypatch.setenv("PUBLIC_APP_URL", "https://photos.test")
    calls: list[str] = []

    def fake_send(to, body, status_callback_url=None):
        calls.append(to)
        return {"sid": f"SM{len(calls)}", "status": "sent", "error": None}

    queue_team_photo_sms(session, photo)
    assert dispatch_team_photo_notices(session, send=fake_send) == 2
    assert calls == ["+15555550101", "+15555550104"]
    notices = session.exec(select(TeamPhotoSmsNotice)).all()
    assert {notice.player_id for notice in notices} == {documented.id, partner.id}
    assert all(notice.status == "SENT" for notice in notices)


def test_consent_fields_do_not_change_the_structural_snapshot_hash():
    base = {
        "tournamentId": 244,
        "teams": [{"teamKey": "11/22", "player1": {"rwId": "11", "rating": 4.0}, "player2": {"rwId": "22", "rating": 3.5}}],
    }
    with_consent = {
        **base,
        "teams": [
            {
                **base["teams"][0],
                "player1": {
                    "rwId": "11",
                    "rating": 4.0,
                    "smsConsent": "opted_in",
                    "smsConsentSource": "registration_terms",
                    "smsConsentAt": "2026-09-01",
                    "smsConsentRecordKey": "Registration_Web:900",
                },
            }
        ],
    }
    assert snapshot_hash(base) == snapshot_hash(with_consent)
