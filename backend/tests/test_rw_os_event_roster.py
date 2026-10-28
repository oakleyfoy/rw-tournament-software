"""Cancun, and any other named event, pulls its own RW-OS players."""

from datetime import date

from sqlmodel import Session, select

from app.models.event import Event, EventCategory
from app.models.team import Team
from app.models.tournament import Tournament
from app.services.rw_os_event_roster import choose_rw_os_event, pull_event_players_from_rw_os


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
