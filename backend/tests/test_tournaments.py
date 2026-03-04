from datetime import date, time, timedelta

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.models.court_state import TournamentCourtState
from app.models.event import Event
from app.models.match import Match
from app.models.match_assignment import MatchAssignment
from app.models.player import Player
from app.models.schedule_slot import ScheduleSlot
from app.models.schedule_version import ScheduleVersion
from app.models.sms_template import SmsTemplate
from app.models.team import Team
from app.models.team_avoid_edge import TeamAvoidEdge
from app.models.team_player import TeamPlayer
from app.models.tournament import Tournament
from app.models.tournament_sms_settings import TournamentSmsSettings
from app.models.tournament_time_window import TournamentTimeWindow


def test_create_tournament_auto_creates_days(client: TestClient):
    """Test that creating a tournament auto-creates correct number of days"""
    start_date = date(2026, 1, 15)
    end_date = date(2026, 1, 17)

    response = client.post(
        "/api/tournaments",
        json={
            "name": "Test Tournament",
            "location": "Test Location",
            "timezone": "America/New_York",
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "notes": "Test notes",
        },
    )

    assert response.status_code == 201
    tournament_data = response.json()
    assert tournament_data["name"] == "Test Tournament"
    assert tournament_data["start_date"] == start_date.isoformat()
    assert tournament_data["end_date"] == end_date.isoformat()

    # Check that days were created
    days_response = client.get(f"/api/tournaments/{tournament_data['id']}/days")
    assert days_response.status_code == 200
    days = days_response.json()

    # Should have 3 days (15, 16, 17)
    assert len(days) == 3

    # Check default values
    for day in days:
        assert day["is_active"] is True
        assert day["start_time"] == "08:00:00"
        assert day["end_time"] == "18:00:00"
        assert day["courts_available"] == 0

    # Check dates are correct
    dates = sorted([day["date"] for day in days])
    assert dates == [start_date.isoformat(), (start_date + timedelta(days=1)).isoformat(), end_date.isoformat()]


def test_tournament_validation_fails_if_end_before_start(client: TestClient):
    """Test that tournament validation fails if end_date < start_date"""
    response = client.post(
        "/api/tournaments",
        json={
            "name": "Test Tournament",
            "location": "Test Location",
            "timezone": "America/New_York",
            "start_date": "2026-01-17",
            "end_date": "2026-01-15",  # End before start
        },
    )

    assert response.status_code == 422
    error_detail = response.json()["detail"]
    assert any("end_date must be >= start_date" in str(err) for err in error_detail)


def test_tournament_timezone_required(client: TestClient):
    """Test that timezone is required"""
    response = client.post(
        "/api/tournaments",
        json={
            "name": "Test Tournament",
            "location": "Test Location",
            "timezone": "",  # Empty timezone
            "start_date": "2026-01-15",
            "end_date": "2026-01-17",
        },
    )

    assert response.status_code == 422


def test_get_tournament(client: TestClient):
    """Test getting a tournament by ID"""
    # Create tournament
    create_response = client.post(
        "/api/tournaments",
        json={
            "name": "Test Tournament",
            "location": "Test Location",
            "timezone": "America/New_York",
            "start_date": "2026-01-15",
            "end_date": "2026-01-17",
        },
    )
    tournament_id = create_response.json()["id"]

    # Get tournament
    response = client.get(f"/api/tournaments/{tournament_id}")
    assert response.status_code == 200
    assert response.json()["id"] == tournament_id


def test_update_tournament_date_range_manages_days(client: TestClient):
    """Test that updating tournament date range adds/removes days correctly"""
    # Create tournament
    create_response = client.post(
        "/api/tournaments",
        json={
            "name": "Test Tournament",
            "location": "Test Location",
            "timezone": "America/New_York",
            "start_date": "2026-01-15",
            "end_date": "2026-01-17",
        },
    )
    tournament_id = create_response.json()["id"]

    # Verify initial days
    days_response = client.get(f"/api/tournaments/{tournament_id}/days")
    assert len(days_response.json()) == 3

    # Update date range to extend it
    update_response = client.put(
        f"/api/tournaments/{tournament_id}",
        json={
            "start_date": "2026-01-14",
            "end_date": "2026-01-18",
        },
    )
    assert update_response.status_code == 200

    # Check days were updated (should have 5 days now: 14-18)
    days_response = client.get(f"/api/tournaments/{tournament_id}/days")
    assert len(days_response.json()) == 5

    # Update date range to shrink it
    update_response = client.put(
        f"/api/tournaments/{tournament_id}",
        json={
            "start_date": "2026-01-15",
            "end_date": "2026-01-16",
        },
    )
    assert update_response.status_code == 200

    # Check days were updated (should have 2 days now: 15-16)
    days_response = client.get(f"/api/tournaments/{tournament_id}/days")
    assert len(days_response.json()) == 2


def test_duplicate_tournament_deep_copies_snapshot(client: TestClient, session: Session):
    """Duplicate should copy courts, events, teams, and schedule graph."""
    source = Tournament(
        name="Lake Conroe",
        location="Conroe",
        timezone="America/Chicago",
        start_date=date(2026, 7, 10),
        end_date=date(2026, 7, 12),
        notes="Source snapshot",
        use_time_windows=True,
        court_names=["1", "2"],
    )
    session.add(source)
    session.flush()

    # Time windows + day state
    session.add(
        TournamentTimeWindow(
            tournament_id=source.id,
            day_date=date(2026, 7, 10),
            start_time=time(8, 0),
            end_time=time(20, 0),
            courts_available=2,
            block_minutes=90,
            label="Main Day",
            is_active=True,
        )
    )
    session.add(
        TournamentCourtState(
            tournament_id=source.id,
            court_label="2",
            is_closed=True,
            note="Wet court",
        )
    )

    event = Event(
        tournament_id=source.id,
        category="mixed",
        name="Mixed A",
        team_count=2,
    )
    session.add(event)
    session.flush()

    team_a = Team(event_id=event.id, name="Alpha / One", seed=1, p1_cell="9013593035")
    team_b = Team(event_id=event.id, name="Bravo / Two", seed=2, p1_cell="6155550100")
    session.add_all([team_a, team_b])
    session.flush()

    session.add(
        TeamAvoidEdge(
            event_id=event.id,
            team_id_a=min(team_a.id, team_b.id),
            team_id_b=max(team_a.id, team_b.id),
            reason="same club",
        )
    )

    player_a = Player(
        tournament_id=source.id,
        full_name="Alpha Player",
        phone_e164="+19013593035",
        sms_consent_status="opted_in",
    )
    player_b = Player(
        tournament_id=source.id,
        full_name="Bravo Player",
        phone_e164="+16155550100",
        sms_consent_status="unknown",
    )
    session.add_all([player_a, player_b])
    session.flush()
    session.add_all(
        [
            TeamPlayer(team_id=team_a.id, player_id=player_a.id, lineup_slot=1, is_primary_contact=True),
            TeamPlayer(team_id=team_b.id, player_id=player_b.id, lineup_slot=1, is_primary_contact=True),
        ]
    )

    version = ScheduleVersion(
        tournament_id=source.id,
        version_number=7,
        status="final",
        notes="Published snapshot",
    )
    session.add(version)
    session.flush()

    slot1 = ScheduleSlot(
        tournament_id=source.id,
        schedule_version_id=version.id,
        day_date=date(2026, 7, 10),
        start_time=time(9, 0),
        end_time=time(10, 30),
        court_number=1,
        court_label="1",
        block_minutes=90,
    )
    slot2 = ScheduleSlot(
        tournament_id=source.id,
        schedule_version_id=version.id,
        day_date=date(2026, 7, 10),
        start_time=time(10, 30),
        end_time=time(12, 0),
        court_number=1,
        court_label="1",
        block_minutes=90,
    )
    session.add_all([slot1, slot2])
    session.flush()

    match1 = Match(
        tournament_id=source.id,
        event_id=event.id,
        schedule_version_id=version.id,
        match_code="MIX_A_R1_M01",
        match_type="WF",
        round_number=1,
        round_index=1,
        sequence_in_round=1,
        duration_minutes=90,
        team_a_id=team_a.id,
        team_b_id=team_b.id,
        placeholder_side_a="A",
        placeholder_side_b="B",
        runtime_status="FINAL",
        winner_team_id=team_a.id,
    )
    session.add(match1)
    session.flush()

    match2 = Match(
        tournament_id=source.id,
        event_id=event.id,
        schedule_version_id=version.id,
        match_code="MIX_A_R2_M01",
        match_type="WF",
        round_number=2,
        round_index=1,
        sequence_in_round=1,
        duration_minutes=90,
        team_a_id=None,
        team_b_id=None,
        placeholder_side_a="Winner M01",
        placeholder_side_b="BYE",
        source_match_a_id=match1.id,
        source_a_role="WINNER",
    )
    session.add(match2)
    session.flush()

    session.add_all(
        [
            MatchAssignment(schedule_version_id=version.id, match_id=match1.id, slot_id=slot1.id),
            MatchAssignment(schedule_version_id=version.id, match_id=match2.id, slot_id=slot2.id),
        ]
    )

    session.add(
        TournamentSmsSettings(
            tournament_id=source.id,
            auto_first_match=True,
            player_contacts_only=True,
        )
    )
    session.add(
        SmsTemplate(
            tournament_id=source.id,
            message_type="on_deck",
            template_body="Custom on deck",
            is_active=True,
        )
    )

    source.public_schedule_version_id = version.id
    session.add(source)
    session.commit()

    resp = client.post(f"/api/tournaments/{source.id}/duplicate")
    assert resp.status_code == 201
    duplicated = resp.json()
    duplicated_id = duplicated["id"]
    assert duplicated["name"].endswith("(Copy)")
    assert duplicated["court_names"] == ["1", "2"]
    assert duplicated["use_time_windows"] is True

    cloned = session.get(Tournament, duplicated_id)
    assert cloned is not None
    assert cloned.public_schedule_version_id is not None

    cloned_events = session.exec(select(Event).where(Event.tournament_id == duplicated_id)).all()
    assert len(cloned_events) == 1
    assert cloned_events[0].name == "Mixed A"

    cloned_teams = session.exec(
        select(Team).where(Team.event_id == cloned_events[0].id)
    ).all()
    assert {t.name for t in cloned_teams} == {"Alpha / One", "Bravo / Two"}

    cloned_versions = session.exec(
        select(ScheduleVersion).where(ScheduleVersion.tournament_id == duplicated_id)
    ).all()
    assert len(cloned_versions) == 1
    assert cloned_versions[0].version_number == 7
    assert cloned.public_schedule_version_id == cloned_versions[0].id

    cloned_slots = session.exec(
        select(ScheduleSlot).where(ScheduleSlot.tournament_id == duplicated_id)
    ).all()
    assert len(cloned_slots) == 2

    cloned_matches = session.exec(
        select(Match).where(Match.tournament_id == duplicated_id)
    ).all()
    assert len(cloned_matches) == 2
    by_code = {m.match_code: m for m in cloned_matches}
    assert by_code["MIX_A_R2_M01"].source_match_a_id == by_code["MIX_A_R1_M01"].id

    cloned_assignments = session.exec(
        select(MatchAssignment).where(
            MatchAssignment.schedule_version_id == cloned_versions[0].id
        )
    ).all()
    assert len(cloned_assignments) == 2

    cloned_players = session.exec(
        select(Player).where(Player.tournament_id == duplicated_id)
    ).all()
    assert len(cloned_players) == 2

    cloned_team_links = session.exec(
        select(TeamPlayer).where(
            TeamPlayer.team_id.in_([t.id for t in cloned_teams])  # type: ignore
        )
    ).all()
    assert len(cloned_team_links) == 2

    cloned_sms_settings = session.exec(
        select(TournamentSmsSettings).where(
            TournamentSmsSettings.tournament_id == duplicated_id
        )
    ).first()
    assert cloned_sms_settings is not None
    assert cloned_sms_settings.player_contacts_only is True

    cloned_templates = session.exec(
        select(SmsTemplate).where(SmsTemplate.tournament_id == duplicated_id)
    ).all()
    assert len(cloned_templates) == 1
    assert cloned_templates[0].template_body == "Custom on deck"


def test_print_packet_pdf_downloads_for_womens_and_mixed(client: TestClient, session: Session):
    tournament = Tournament(
        name="Print Packet Test",
        location="Conroe",
        timezone="America/Chicago",
        start_date=date(2026, 7, 10),
        end_date=date(2026, 7, 12),
        court_names=["1", "2"],
    )
    session.add(tournament)
    session.flush()

    version = ScheduleVersion(
        tournament_id=tournament.id,
        version_number=1,
        status="final",
    )
    session.add(version)
    session.flush()

    womens_event = Event(
        tournament_id=tournament.id,
        category="womens",
        name="Women's A",
        team_count=2,
    )
    mixed_event = Event(
        tournament_id=tournament.id,
        category="mixed",
        name="Mixed A",
        team_count=2,
    )
    session.add_all([womens_event, mixed_event])
    session.flush()

    w1 = Team(event_id=womens_event.id, name="W Alpha", display_name="W Alpha")
    w2 = Team(event_id=womens_event.id, name="W Bravo", display_name="W Bravo")
    m1 = Team(event_id=mixed_event.id, name="M Alpha", display_name="M Alpha")
    m2 = Team(event_id=mixed_event.id, name="M Bravo", display_name="M Bravo")
    session.add_all([w1, w2, m1, m2])
    session.flush()

    slot1 = ScheduleSlot(
        tournament_id=tournament.id,
        schedule_version_id=version.id,
        day_date=date(2026, 7, 10),
        start_time=time(9, 0),
        end_time=time(10, 0),
        court_number=1,
        court_label="1",
        block_minutes=60,
    )
    slot2 = ScheduleSlot(
        tournament_id=tournament.id,
        schedule_version_id=version.id,
        day_date=date(2026, 7, 10),
        start_time=time(10, 0),
        end_time=time(11, 0),
        court_number=2,
        court_label="2",
        block_minutes=60,
    )
    session.add_all([slot1, slot2])
    session.flush()

    w_match = Match(
        tournament_id=tournament.id,
        event_id=womens_event.id,
        schedule_version_id=version.id,
        match_code="WOM_E1_WF_R1_M01",
        match_type="WF",
        round_number=1,
        round_index=1,
        sequence_in_round=1,
        duration_minutes=60,
        team_a_id=w1.id,
        team_b_id=w2.id,
        placeholder_side_a="Seed 1",
        placeholder_side_b="Seed 2",
        runtime_status="SCHEDULED",
    )
    m_match = Match(
        tournament_id=tournament.id,
        event_id=mixed_event.id,
        schedule_version_id=version.id,
        match_code="MIX_E2_RR_POOLA_M01",
        match_type="RR",
        round_number=1,
        round_index=1,
        sequence_in_round=1,
        duration_minutes=60,
        team_a_id=m1.id,
        team_b_id=m2.id,
        placeholder_side_a="A",
        placeholder_side_b="B",
        runtime_status="SCHEDULED",
    )
    session.add_all([w_match, m_match])
    session.flush()

    session.add_all(
        [
            MatchAssignment(schedule_version_id=version.id, match_id=w_match.id, slot_id=slot1.id),
            MatchAssignment(schedule_version_id=version.id, match_id=m_match.id, slot_id=slot2.id),
        ]
    )
    tournament.public_schedule_version_id = version.id
    session.add(tournament)
    session.commit()

    women_resp = client.get(f"/api/tournaments/{tournament.id}/print-packet/womens.pdf")
    assert women_resp.status_code == 200
    assert women_resp.headers["content-type"] == "application/pdf"
    assert women_resp.content.startswith(b"%PDF")

    mixed_resp = client.get(f"/api/tournaments/{tournament.id}/print-packet/mixed.pdf")
    assert mixed_resp.status_code == 200
    assert mixed_resp.headers["content-type"] == "application/pdf"
    assert mixed_resp.content.startswith(b"%PDF")


def test_print_packet_invalid_category(client: TestClient):
    create = client.post(
        "/api/tournaments",
        json={
            "name": "Invalid Category Test",
            "location": "x",
            "timezone": "America/Chicago",
            "start_date": "2026-01-01",
            "end_date": "2026-01-02",
        },
    )
    tid = create.json()["id"]
    resp = client.get(f"/api/tournaments/{tid}/print-packet/coed.pdf")
    assert resp.status_code == 400
