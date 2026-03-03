"""Tests for player/team_player/sms_consent_event foundation models."""

from datetime import date, datetime, timezone

import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.models.event import Event
from app.models.player import Player
from app.models.sms_consent_event import SmsConsentEvent
from app.models.team import Team
from app.models.team_player import TeamPlayer
from app.models.tournament import Tournament


@pytest.fixture
def setup_tournament_team(session: Session):
    tournament = Tournament(
        name="Player Foundation Test",
        location="Test Venue",
        timezone="America/Chicago",
        start_date=date(2026, 4, 1),
        end_date=date(2026, 4, 2),
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
        display_name="Alex / Jamie",
    )
    session.add(team)
    session.commit()
    session.refresh(team)

    return tournament, event, team


def test_player_crud_with_consent_snapshot(session: Session, setup_tournament_team):
    tournament, _, _ = setup_tournament_team

    player = Player(
        tournament_id=tournament.id,
        full_name="Alex Carter",
        display_name="Alex",
        phone_e164="+15550000001",
        sms_consent_status="opted_in",
        sms_consent_source="import",
        sms_consented_at=datetime.now(timezone.utc),
        sms_consent_updated_at=datetime.now(timezone.utc),
    )
    session.add(player)
    session.commit()
    session.refresh(player)

    assert player.id is not None
    assert player.sms_consent_status == "opted_in"
    assert player.phone_e164 == "+15550000001"


def test_player_phone_unique_per_tournament(session: Session, setup_tournament_team):
    tournament, _, _ = setup_tournament_team

    p1 = Player(
        tournament_id=tournament.id,
        full_name="Player One",
        phone_e164="+15550000002",
    )
    p2 = Player(
        tournament_id=tournament.id,
        full_name="Player Two",
        phone_e164="+15550000002",
    )
    session.add(p1)
    session.commit()
    session.refresh(p1)

    session.add(p2)
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_team_player_join_unique(session: Session, setup_tournament_team):
    tournament, _, team = setup_tournament_team

    player = Player(
        tournament_id=tournament.id,
        full_name="Jamie Quinn",
        phone_e164="+15550000003",
    )
    session.add(player)
    session.commit()
    session.refresh(player)

    link = TeamPlayer(team_id=team.id, player_id=player.id, lineup_slot=2)
    session.add(link)
    session.commit()
    session.refresh(link)
    assert link.id is not None

    dup = TeamPlayer(team_id=team.id, player_id=player.id, lineup_slot=2)
    session.add(dup)
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_sms_consent_event_dedupe_key(session: Session, setup_tournament_team):
    tournament, _, _ = setup_tournament_team

    event1 = SmsConsentEvent(
        tournament_id=tournament.id,
        player_id=None,
        phone_number="+15550000004",
        event_type="opted_out",
        source="twilio_webhook",
        dedupe_key="twilio:SM12345",
    )
    session.add(event1)
    session.commit()
    session.refresh(event1)

    dup = SmsConsentEvent(
        tournament_id=tournament.id,
        player_id=None,
        phone_number="+15550000004",
        event_type="opted_out",
        source="twilio_webhook",
        dedupe_key="twilio:SM12345",
    )
    session.add(dup)
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()

    rows = session.exec(
        select(SmsConsentEvent).where(
            SmsConsentEvent.tournament_id == tournament.id
        )
    ).all()
    assert len(rows) == 1
