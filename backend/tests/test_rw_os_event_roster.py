"""Cancun, and any other named event, pulls its own RW-OS players."""

from datetime import date

from sqlmodel import Session, select

from app.models.event import Event, EventCategory
from app.models.team import Team
from app.models.team_avoid_edge import TeamAvoidEdge
from app.models.tournament import Tournament
from app.services.rw_os_event_roster import (
    choose_rw_os_event,
    pull_event_players_from_rw_os,
    sync_existing_event_who_knows_who,
)


class _Client:
    def __init__(self, events, details):
        self.events = events
        self.details = details
        self.fetched = None

    def list_events(self, include_historical=False):
        return self.events

    def get_event(self, tournament_id):
        self.fetched = tournament_id
        return self.details[tournament_id]


def _team(key, name, draw, rating):
    first, second = [part.strip() for part in name.split("/")]
    return {
        "teamKey": key,
        "drawKind": draw,
        "drawLabel": "Mixed" if draw == "mixed" else "Women's",
        "displayName": name,
        "fullName": name,
        "teamRating": rating,
        "bucket": "active",
        "status": "active",
        "player1": {"rwId": key.split("/")[0], "name": first, "rating": rating / 2},
        "player2": {"rwId": key.split("/")[1], "name": second, "rating": rating / 2},
    }


def test_palm_springs_2026_matches_rw_os_year_first():
    events = [
        {"tournamentId": 140, "eventName": "2025 Palm Springs"},
        {"tournamentId": 149, "eventName": "2026 Palm Springs"},
    ]
    chosen = choose_rw_os_event(events, "Mixed", "Palm Springs 2026")
    assert chosen["tournamentId"] == 149


def test_womens_a_pulls_only_that_draw_when_two_womens_events_exist(session: Session):
    tournament = Tournament(
        name="Palm Springs 2026",
        location="Rancho Las Palmas",
        timezone="America/Los_Angeles",
        start_date=date(2026, 12, 3),
        end_date=date(2026, 12, 5),
    )
    session.add(tournament)
    session.commit()
    session.refresh(tournament)
    womens_a = Event(
        tournament_id=tournament.id,
        name="Women's A",
        category=EventCategory.womens,
        team_count=32,
    )
    womens_b = Event(
        tournament_id=tournament.id,
        name="Women's B",
        category=EventCategory.womens,
        team_count=28,
    )
    session.add(womens_a)
    session.add(womens_b)
    session.commit()
    session.refresh(womens_a)

    def team(key, name, label, rating):
        row = _team(key, name, "womens", rating)
        row["drawLabel"] = label
        return row

    client = _Client(
        [{"tournamentId": 149, "eventName": "2026 Palm Springs"}],
        {
            149: {
                "organizationSlug": "rw",
                "tournamentId": 149,
                "eventName": "2026 Palm Springs",
                "teams": [
                    team("1/2", "Ann / Bea", "Women's A", 9.0),
                    team("3/4", "Cara / Dee", "Women's B", 7.0),
                ],
            }
        },
    )

    result = pull_event_players_from_rw_os(session, tournament, womens_a, client=client)
    assert result["imported_count"] == 1
    assert result["team_names"] == ["Ann / Bea"]


def test_one_womens_draw_splits_by_rating_into_a_then_b(session: Session):
    tournament = Tournament(
        name="Palm Springs 2026",
        location="Rancho Las Palmas",
        timezone="America/Los_Angeles",
        start_date=date(2026, 12, 3),
        end_date=date(2026, 12, 5),
    )
    session.add(tournament)
    session.commit()
    session.refresh(tournament)
    womens_a = Event(
        tournament_id=tournament.id,
        name="Women's A",
        category=EventCategory.womens,
        team_count=2,
    )
    womens_b = Event(
        tournament_id=tournament.id,
        name="Women's B",
        category=EventCategory.womens,
        team_count=1,
    )
    session.add(womens_a)
    session.add(womens_b)
    session.commit()
    session.refresh(womens_a)
    session.refresh(womens_b)

    client = _Client(
        [{"tournamentId": 149, "eventName": "2026 Palm Springs"}],
        {
            149: {
                "organizationSlug": "rw",
                "tournamentId": 149,
                "eventName": "2026 Palm Springs",
                "teams": [
                    _team("1/2", "Ann / Bea", "womens", 9.0),
                    _team("3/4", "Cara / Dee", "womens", 7.0),
                    _team("5/6", "Eve / Fay", "womens", 8.0),
                ],
            }
        },
    )

    top = pull_event_players_from_rw_os(session, tournament, womens_a, client=client)
    assert top["team_names"] == ["Ann / Bea", "Eve / Fay"]
    next_flight = pull_event_players_from_rw_os(session, tournament, womens_b, client=client)
    assert next_flight["team_names"] == ["Cara / Dee"]


def test_womens_b_pulls_the_next_flight_even_before_a_is_pulled(session: Session):
    tournament = Tournament(
        name="Palm Springs 2026",
        location="Rancho Las Palmas",
        timezone="America/Los_Angeles",
        start_date=date(2026, 12, 3),
        end_date=date(2026, 12, 5),
    )
    session.add(tournament)
    session.commit()
    session.refresh(tournament)
    womens_a = Event(
        tournament_id=tournament.id,
        name="Women's A",
        category=EventCategory.womens,
        team_count=32,
    )
    womens_b = Event(
        tournament_id=tournament.id,
        name="Women's B",
        category=EventCategory.womens,
        team_count=28,
    )
    session.add(womens_a)
    session.add(womens_b)
    session.commit()
    session.refresh(womens_b)

    teams = [
        _team(f"{index}/{index + 100}", f"P{index} / Q{index}", "womens", 100 - index)
        for index in range(1, 61)
    ]
    client = _Client(
        [{"tournamentId": 149, "eventName": "2026 Palm Springs"}],
        {
            149: {
                "organizationSlug": "rw",
                "tournamentId": 149,
                "eventName": "2026 Palm Springs",
                "teams": teams,
            }
        },
    )

    result = pull_event_players_from_rw_os(session, tournament, womens_b, client=client)
    assert result["imported_count"] == 28
    assert result["team_names"][0] == "P33 / Q33"
    assert result["team_names"][-1] == "P60 / Q60"
    assert "P1 / Q1" not in result["team_names"]


def test_event_name_cancun_beats_a_wild_dunes_tournament_name():
    events = [
        {"tournamentId": 148, "eventName": "2026 Wild Dunes"},
        {"tournamentId": 142, "eventName": "2026 Cancun"},
    ]
    chosen = choose_rw_os_event(events, "Cancun", "2026 Wild Dunes (Copy)")
    assert chosen["tournamentId"] == 142


def test_pull_replaces_the_copied_roster_with_the_named_event(session: Session):
    tournament = Tournament(
        name="2026 Wild Dunes (Copy)",
        location="Cancun",
        timezone="America/New_York",
        start_date=date(2026, 11, 12),
        end_date=date(2026, 11, 15),
        source_rw_os_tournament_id=148,
    )
    session.add(tournament)
    session.commit()
    session.refresh(tournament)
    event = Event(
        tournament_id=tournament.id,
        name="Cancun",
        category=EventCategory.mixed,
        team_count=12,
    )
    session.add(event)
    session.commit()
    session.refresh(event)
    session.add(
        Team(
            event_id=event.id,
            name="Mike Arsenault, Atlanta, GA / Dee Dee Worley, Atlanta, GA",
            display_name="Mike / Dee Dee",
            seed=1,
            rating=8.5,
            source_team_key="100/200",
        )
    )
    session.commit()

    client = _Client(
        [
            {"tournamentId": 148, "eventName": "2026 Wild Dunes"},
            {"tournamentId": 142, "eventName": "2026 Cancun"},
        ],
        {
            142: {
                "organizationSlug": "rw",
                "tournamentId": 142,
                "eventName": "2026 Cancun",
                "teams": [
                    _team("9271/9372", "Aaron / Wendy", "mixed", 6.5),
                    _team("9161/9182", "Mike / Dee Dee", "mixed", 8.5),
                    _team("11/22", "Lauri / Marc", "womens", 8.0),
                ],
            }
        },
    )

    result = pull_event_players_from_rw_os(session, tournament, event, client=client)

    assert client.fetched == 142
    assert result["source_event_name"] == "2026 Cancun"
    assert result["imported_count"] == 2
    assert result["retired_count"] == 1
    assert result["team_names"] == ["Mike / Dee Dee", "Aaron / Wendy"]

    session.refresh(tournament)
    session.refresh(event)
    assert tournament.source_rw_os_tournament_id == 142
    assert event.team_count == 2
    active = session.exec(
        select(Team).where(Team.event_id == event.id, Team.is_defaulted == False)  # noqa: E712
    ).all()
    assert [(team.seed, team.display_name) for team in sorted(active, key=lambda team: team.seed or 0)] == [
        (1, "Mike / Dee Dee"),
        (2, "Aaron / Wendy"),
    ]


def test_pull_keeps_who_knows_who_inside_womens_and_mixed(session: Session):
    tournament = Tournament(
        name="Palm Springs 2026",
        location="Rancho Las Palmas",
        timezone="America/Los_Angeles",
        start_date=date(2026, 12, 3),
        end_date=date(2026, 12, 5),
    )
    session.add(tournament)
    session.commit()
    session.refresh(tournament)
    womens_a = Event(tournament_id=tournament.id, name="Women's A", category=EventCategory.womens, team_count=2)
    womens_b = Event(tournament_id=tournament.id, name="Women's B", category=EventCategory.womens, team_count=2)
    mixed = Event(tournament_id=tournament.id, name="Mixed", category=EventCategory.mixed, team_count=2)
    session.add(womens_a)
    session.add(womens_b)
    session.add(mixed)
    session.commit()
    session.refresh(womens_a)
    session.refresh(womens_b)
    session.refresh(mixed)

    def womens(key, name, rating):
        return _team(key, name, "womens", rating)

    client = _Client(
        [{"tournamentId": 149, "eventName": "2026 Palm Springs"}],
        {
            149: {
                "organizationSlug": "rw",
                "tournamentId": 149,
                "eventName": "2026 Palm Springs",
                "teams": [
                    womens("1/2", "Ann / Bea", 9.0),
                    womens("3/4", "Cara / Dee", 8.5),
                    womens("5/6", "Eve / Fay", 7.0),
                    womens("7/8", "Gia / Hoa", 6.5),
                    _team("11/12", "Ian / Joy", "mixed", 8.0),
                    _team("13/14", "Ken / Lea", "mixed", 7.5),
                ],
                "whoKnowsWhoConnections": [
                    {"drawKind": "womens", "teamAKey": "1/2", "teamBKey": "3/4"},
                    {"drawKind": "womens", "teamAKey": "5/6", "teamBKey": "7/8"},
                    {"drawKind": "womens", "teamAKey": "1/2", "teamBKey": "5/6"},
                    {"drawKind": "mixed", "teamAKey": "11/12", "teamBKey": "13/14"},
                ],
            }
        },
    )

    a_result = pull_event_players_from_rw_os(session, tournament, womens_a, client=client)
    b_result = pull_event_players_from_rw_os(session, tournament, womens_b, client=client)
    m_result = pull_event_players_from_rw_os(session, tournament, mixed, client=client)

    assert a_result["who_knows_who"] == 1
    assert b_result["who_knows_who"] == 1
    assert m_result["who_knows_who"] == 1
    assert len(session.exec(select(TeamAvoidEdge).where(TeamAvoidEdge.event_id == womens_a.id)).all()) == 1
    assert len(session.exec(select(TeamAvoidEdge).where(TeamAvoidEdge.event_id == womens_b.id)).all()) == 1
    assert len(session.exec(select(TeamAvoidEdge).where(TeamAvoidEdge.event_id == mixed.id)).all()) == 1


def test_sync_who_knows_who_keeps_the_existing_draw(session: Session):
    tournament = Tournament(
        name="Palm Springs 2026",
        location="Rancho Las Palmas",
        timezone="America/Los_Angeles",
        start_date=date(2026, 12, 3),
        end_date=date(2026, 12, 5),
        source_rw_os_tournament_id=149,
    )
    session.add(tournament)
    session.commit()
    session.refresh(tournament)
    event = Event(tournament_id=tournament.id, name="Women's A", category=EventCategory.womens, team_count=2)
    session.add(event)
    session.commit()
    session.refresh(event)
    session.add(Team(event_id=event.id, name="Ann / Bea", display_name="Ann / Bea", seed=1, source_team_key="1/2"))
    session.add(Team(event_id=event.id, name="Cara / Dee", display_name="Cara / Dee", seed=2, source_team_key="3/4"))
    session.commit()

    client = _Client(
        [],
        {
            149: {
                "whoKnowsWhoConnections": [
                    {"drawKind": "womens", "teamAKey": "1/2", "teamBKey": "3/4"},
                ]
            }
        },
    )
    assert sync_existing_event_who_knows_who(session, tournament, event, client=client) == 1
    names = session.exec(select(Team).where(Team.event_id == event.id)).all()
    assert sorted(team.display_name for team in names) == ["Ann / Bea", "Cara / Dee"]

    class _Exploding:
        def get_event(self, tournament_id):
            raise AssertionError("should not fetch again")

    assert sync_existing_event_who_knows_who(session, tournament, event, client=_Exploding()) == 1
