"""Desk snapshot must open on a duplicated Palm Springs-style draw."""

from datetime import date, time

from sqlalchemy import text
from sqlmodel import Session

from app.models.event import Event
from app.models.match import Match
from app.models.match_assignment import MatchAssignment
from app.models.player import Player
from app.models.schedule_slot import ScheduleSlot
from app.models.schedule_version import ScheduleVersion
from app.models.team import Team
from app.models.team_player import TeamPlayer
from app.models.tournament import Tournament
from app.models.court_state import TournamentCourtState


def test_duplicate_palm_springs_style_desk_snapshot(client, session: Session, monkeypatch):
    tournament = Tournament(
        name="Palm Springs 2026",
        location="Palm Springs",
        timezone="America/Los_Angeles",
        start_date=date(2026, 12, 4),
        end_date=date(2026, 12, 7),
        desk_management_mode="checkin_management",
        court_names=["1", "12"],
    )
    session.add(tournament)
    session.flush()
    version = ScheduleVersion(
        tournament_id=tournament.id,
        version_number=1,
        status="final",
        notes="desk-draft",
    )
    session.add(version)
    session.flush()
    tournament.public_schedule_version_id = version.id
    event = Event(tournament_id=tournament.id, category="mixed", name="Mixed", team_count=2)
    session.add(event)
    session.flush()
    team_a = Team(
        event_id=event.id,
        name="Alex Bose, Winter Haven, FL / Jennifer Myers, Winter haven, FL",
        display_name="Alex / Jennifer",
        seed=1,
        p1_cell="9013593035",
        p2_cell="6155550100",
    )
    team_b = Team(
        event_id=event.id,
        name="Amanda Letonoff, Gulfport, Mississippi / Julie Bradley, Tampa, FL (2)",
        display_name="Amanda / Julie",
        seed=2,
    )
    session.add_all([team_a, team_b])
    session.flush()
    players = [
        Player(tournament_id=tournament.id, full_name="Alex Bose", display_name="Alex Bose"),
        Player(tournament_id=tournament.id, full_name="Jennifer Myers", display_name="Jennifer Myers"),
        Player(tournament_id=tournament.id, full_name="Amanda Letonoff", display_name="Amanda Letonoff"),
        Player(tournament_id=tournament.id, full_name="Julie Bradley", display_name="Julie Bradley"),
    ]
    session.add_all(players)
    session.flush()
    session.add_all(
        [
            TeamPlayer(team_id=team_a.id, player_id=players[0].id, lineup_slot=1),
            TeamPlayer(team_id=team_a.id, player_id=players[1].id, lineup_slot=2),
            TeamPlayer(team_id=team_b.id, player_id=players[2].id, lineup_slot=1),
            TeamPlayer(team_id=team_b.id, player_id=players[3].id, lineup_slot=2),
        ]
    )
    slot = ScheduleSlot(
        tournament_id=tournament.id,
        schedule_version_id=version.id,
        day_date=date(2026, 12, 4),
        start_time=time(9, 0),
        end_time=time(10, 0),
        court_number=12,
        court_label="12",
        block_minutes=60,
    )
    session.add(slot)
    session.flush()
    match = Match(
        tournament_id=tournament.id,
        event_id=event.id,
        schedule_version_id=version.id,
        match_code="MIX_WF_R1_01",
        match_type="WF",
        round_number=1,
        round_index=1,
        sequence_in_round=1,
        duration_minutes=60,
        team_a_id=team_a.id,
        team_b_id=team_b.id,
        placeholder_side_a="A",
        placeholder_side_b="B",
    )
    session.add(match)
    session.flush()
    session.add(
        MatchAssignment(
            schedule_version_id=version.id,
            match_id=match.id,
            slot_id=slot.id,
        )
    )
    session.add(
        TournamentCourtState(
            tournament_id=tournament.id,
            court_label="12",
            is_closed=False,
        )
    )
    session.commit()

    original = client.get(f"/api/desk/tournaments/{tournament.id}/snapshot")
    assert original.status_code == 200, original.text

    copied = client.post(f"/api/tournaments/{tournament.id}/duplicate")
    assert copied.status_code == 201, copied.text
    copy_id = copied.json()["id"]

    def _broken_player_eq(self, other):
        raise AttributeError("'Player' object has no attribute '_pydantic_extra_'")

    monkeypatch.setattr(Player, "__eq__", _broken_player_eq)
    snap = client.get(f"/api/desk/tournaments/{copy_id}/snapshot")
    assert snap.status_code == 200, snap.text
    body = snap.json()
    assert body["tournament_name"].endswith("(Copy)")
    assert body["matches"]


def test_a_deleted_copy_does_not_leave_day_started_or_extra_players_on_the_next_copy(client, session: Session):
    from sqlmodel import select

    from app.models.desk_day_run import DeskDayRun

    tournament = Tournament(
        name="Palm Springs 2026",
        location="Palm Springs",
        timezone="America/Los_Angeles",
        start_date=date(2026, 12, 4),
        end_date=date(2026, 12, 6),
        desk_management_mode="checkin_management",
    )
    session.add(tournament)
    session.flush()
    version = ScheduleVersion(tournament_id=tournament.id, version_number=1, status="draft", notes="Desk Draft")
    session.add(version)
    session.flush()
    tournament.public_schedule_version_id = version.id
    event = Event(tournament_id=tournament.id, category="mixed", name="Mixed", team_count=2)
    session.add(event)
    session.flush()
    team = Team(
        event_id=event.id,
        name="Amanda Letonoff, Gulfport, Mississippi / Robin Cardona, Palm Springs, CA",
        display_name="Amanda / Robin",
        seed=1,
    )
    other = Team(
        event_id=event.id,
        name="Amy Holly, Tampa, FL / Holly Neal, Austin, TX",
        display_name="Amy / Holly",
        seed=2,
    )
    session.add_all([team, other])
    session.flush()
    people = [
        Player(tournament_id=tournament.id, full_name="Amanda Letonoff", display_name="Amanda Letonoff"),
        Player(tournament_id=tournament.id, full_name="Robin Cardona", display_name="Robin Cardona"),
        Player(tournament_id=tournament.id, full_name="Amy Holly", display_name="Amy Holly"),
        Player(tournament_id=tournament.id, full_name="Holly Neal", display_name="Holly Neal"),
    ]
    session.add_all(people)
    session.flush()
    session.add_all(
        [
            TeamPlayer(team_id=team.id, player_id=people[0].id, lineup_slot=1),
            TeamPlayer(team_id=team.id, player_id=people[1].id, lineup_slot=2),
            TeamPlayer(team_id=other.id, player_id=people[2].id, lineup_slot=1),
            TeamPlayer(team_id=other.id, player_id=people[3].id, lineup_slot=2),
        ]
    )
    slot = ScheduleSlot(
        tournament_id=tournament.id,
        schedule_version_id=version.id,
        day_date=date(2026, 12, 4),
        start_time=time(9, 0),
        end_time=time(10, 0),
        court_number=1,
        court_label="1",
        block_minutes=60,
        is_active=False,
    )
    session.add(slot)
    session.flush()
    match = Match(
        tournament_id=tournament.id,
        event_id=event.id,
        schedule_version_id=version.id,
        match_code="MIX_WF_R1_01",
        match_type="WF",
        round_number=1,
        round_index=1,
        sequence_in_round=1,
        duration_minutes=60,
        team_a_id=team.id,
        team_b_id=other.id,
        placeholder_side_a="A",
        placeholder_side_b="B",
        runtime_status="IN_PROGRESS",
    )
    session.add(match)
    session.flush()
    session.add(MatchAssignment(schedule_version_id=version.id, match_id=match.id, slot_id=slot.id))
    session.commit()

    first = client.post(f"/api/tournaments/{tournament.id}/duplicate")
    assert first.status_code == 201, first.text
    first_id = first.json()["id"]
    started = client.post(
        f"/api/desk/tournaments/{first_id}/dashboard/start-day",
        json={"version_id": client.get(f"/api/desk/tournaments/{first_id}/snapshot").json()["version_id"], "day_date": "2026-12-04"},
    )
    assert started.status_code == 200, started.text
    removed = client.delete(f"/api/tournaments/{first_id}")
    assert removed.status_code == 204, removed.text

    second = client.post(f"/api/tournaments/{tournament.id}/duplicate")
    assert second.status_code == 201, second.text
    second_id = second.json()["id"]
    snap = client.get(f"/api/desk/tournaments/{second_id}/snapshot")
    assert snap.status_code == 200, snap.text
    body = snap.json()
    names_by_side = []
    for row in body["arrival_matches"]:
        for side in (row["side_a"], row["side_b"]):
            names_by_side.append([player["player_display"] for player in side["players"]])
    assert names_by_side
    for names in names_by_side:
        assert len(names) == 2, names
        assert len(set(names)) == 2, names
    assert body["dashboard_days"] == []
    assert session.exec(select(DeskDayRun).where(DeskDayRun.tournament_id == first_id)).all() == []
    original_snap = client.get(f"/api/desk/tournaments/{tournament.id}/snapshot")
    assert original_snap.status_code == 200
    assert original_snap.json()["dashboard_days"] == []
    session.expire_all()
    original_match = session.get(Match, match.id)
    assert (original_match.runtime_status or "").upper() == "IN_PROGRESS"
    copy_matches = session.exec(select(Match).where(Match.tournament_id == second_id)).all()
    assert copy_matches
    assert all((row.runtime_status or "").upper() == "SCHEDULED" for row in copy_matches)


def test_snapshot_survives_missing_dashboard_day_table(client, session: Session):
    tournament = Tournament(
        name="No Day Table",
        location="Test",
        timezone="America/Chicago",
        start_date=date(2026, 12, 4),
        end_date=date(2026, 12, 4),
        desk_management_mode="checkin_management",
    )
    session.add(tournament)
    session.flush()
    version = ScheduleVersion(tournament_id=tournament.id, version_number=1, status="final")
    session.add(version)
    session.flush()
    tournament.public_schedule_version_id = version.id
    event = Event(tournament_id=tournament.id, category="mixed", name="Mixed", team_count=2)
    session.add(event)
    session.flush()
    team_a = Team(event_id=event.id, name="Ann Able / Bea Baker", seed=1)
    team_b = Team(event_id=event.id, name="Cara Cole / Dee Dunn", seed=2)
    session.add_all([team_a, team_b])
    session.flush()
    slot = ScheduleSlot(
        tournament_id=tournament.id,
        schedule_version_id=version.id,
        day_date=date(2026, 12, 4),
        start_time=time(11, 0),
        end_time=time(12, 0),
        court_number=1,
        court_label="1",
        block_minutes=60,
    )
    session.add(slot)
    session.flush()
    match = Match(
        tournament_id=tournament.id,
        event_id=event.id,
        schedule_version_id=version.id,
        match_code="MIX_WF_R1_02",
        match_type="WF",
        round_number=1,
        round_index=1,
        sequence_in_round=1,
        duration_minutes=60,
        team_a_id=team_a.id,
        team_b_id=team_b.id,
        placeholder_side_a="A",
        placeholder_side_b="B",
    )
    session.add(match)
    session.flush()
    session.add(MatchAssignment(schedule_version_id=version.id, match_id=match.id, slot_id=slot.id))
    session.commit()

    session.connection().execute(text("DROP TABLE IF EXISTS deskdayrun"))
    session.commit()

    snap = client.get(f"/api/desk/tournaments/{tournament.id}/snapshot")
    assert snap.status_code == 200, snap.text
    assert snap.json()["dashboard_days"] == []
