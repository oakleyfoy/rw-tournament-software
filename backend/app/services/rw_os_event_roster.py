"""Replace one event's team list with the matching RW-OS draw."""

from __future__ import annotations

import re
from typing import Any, Optional

from sqlmodel import Session, select

from app.models.event import Event, EventCategory
from app.models.team import Team
from app.models.tournament import Tournament
from app.services.canonical_teams import sort_teams_for_planning
from app.services.rw_os_client import RwOsClient
from app.services.rw_os_import import parse_teams
from app.services.rw_os_roster_projection import (
    RosterProjectionResult,
    _create_source_team,
    _delete_rwos_towel_rows,
    _delete_team_avoid_edges,
    _matches_for_team,
    _team_draw_lock_reason,
)


_YEAR = re.compile(r"^(?:19|20)\d{2}$")


def _compact(value: str) -> str:
    return " ".join((value or "").casefold().split())


def _draw_key(value: str) -> str:
    return _compact(value).replace("'", "").replace("’", "")


def _without_years(value: str) -> str:
    return " ".join(part for part in _compact(value).split() if not _YEAR.match(part))


def _years(value: str) -> set[str]:
    return {part for part in _compact(value).split() if _YEAR.match(part)}


def names_match_rw_os_event(candidate: str, event_name: str) -> bool:
    """Match a local name to an RW-OS event name.

    "Palm Springs 2026" and "2026 Palm Springs" are the same event. A year on
    both sides must agree, so 2026 does not pull 2025.
    """
    left = _compact(candidate)
    right = _compact(event_name)
    if not left or not right:
        return False
    if right in left or left in right:
        return True
    left_years = _years(candidate)
    right_years = _years(event_name)
    if left_years and right_years and left_years.isdisjoint(right_years):
        return False
    left_core = _without_years(candidate)
    right_core = _without_years(event_name)
    return bool(left_core) and left_core == right_core


def choose_rw_os_event(events: list[dict[str, Any]], *names: str) -> Optional[dict[str, Any]]:
    """Prefer a draw event name, then the tournament name. The longest RW-OS name wins."""
    for name in names:
        matches = [
            event
            for event in events
            if names_match_rw_os_event(name, str(event.get("eventName") or ""))
        ]
        if matches:
            return max(matches, key=lambda event: len(str(event.get("eventName") or "")))
    return None


def _category_value(event: Event) -> str:
    category = event.category
    return category.value if isinstance(category, EventCategory) else str(category or "")


def _events_in_category(session: Session, event: Event) -> list[Event]:
    category = _category_value(event)
    rows = session.exec(select(Event).where(Event.tournament_id == event.tournament_id)).all()
    return sorted(
        (row for row in rows if _category_value(row) == category),
        key=lambda row: (_compact(row.name or ""), row.id or 0),
    )


def _shared_draw_slice(events: list[Event], event: Event, active: list) -> list:
    """Split one RW-OS draw across local events.

    Women's A comes before Women's B by name, so A receives the strongest teams
    up to its team count and B receives the next slice.
    """
    ranked = sort_teams_for_planning(active)
    cursor = 0
    chosen: list = []
    for sibling in events:
        count = max(int(sibling.team_count or 0), 0)
        chunk = ranked[cursor : cursor + count]
        cursor += len(chunk)
        if sibling.id == event.id:
            chosen = chunk
    return chosen


def _teams_for_event(payload: dict[str, Any], event: Event, session: Session) -> list:
    category = _category_value(event)
    active = [
        team
        for team in parse_teams(list(payload.get("teams") or []))
        if team.bucket == "active" and team.draw_kind == category and team.team_key
    ]
    label = _draw_key(event.name)
    labeled = [team for team in active if _draw_key(team.draw_label) == label]
    if labeled:
        return sort_teams_for_planning(labeled)
    events = _events_in_category(session, event)
    if len(events) > 1:
        named = [
            sibling
            for sibling in events
            if any(_draw_key(sibling.name or "") == _draw_key(team.draw_label) for team in active)
        ]
        if named:
            labels = sorted({team.draw_label for team in active if team.draw_label})
            shown = ", ".join(labels) or "none"
            raise ValueError(
                f"{event.name} is one of several {category} events. "
                f"RW-OS draw names for this category: {shown}. "
                "Name this event to match one of those draws, then pull again."
            )
        chosen = _shared_draw_slice(events, event, active)
        if not chosen:
            raise ValueError(
                f"{event.name} has no players left after the earlier {category} events take their fields."
            )
        return chosen
    if not active:
        source_name = str(payload.get("eventName") or "RW-OS")
        raise ValueError(f"{source_name} has no {category} players to pull.")
    return sort_teams_for_planning(active)


def _retire_team(session: Session, tournament_id: int, team: Team) -> None:
    for match in _matches_for_team(session, team):
        if match.team_a_id == team.id and match.source_match_a_id is None:
            match.team_a_id = None
            match.placeholder_side_a = "TBD"
            session.add(match)
        if match.team_b_id == team.id and match.source_match_b_id is None:
            match.team_b_id = None
            match.placeholder_side_b = "TBD"
            session.add(match)
    if team.id is not None:
        _delete_team_avoid_edges(session, team.event_id, team.id)
    if team.source_team_key:
        _delete_rwos_towel_rows(session, tournament_id, team.source_team_key)
    team.is_defaulted = True
    team.seed = None
    team.source_team_key = None
    if team.id is not None:
        team.name = f"__retired_{team.id}"
    session.add(team)


def pull_event_players_from_rw_os(
    session: Session,
    tournament: Tournament,
    event: Event,
    *,
    client: Optional[RwOsClient] = None,
) -> dict[str, Any]:
    """Replace this event with the players from the RW-OS event it is named for."""
    client = client or RwOsClient()
    listed = client.list_events(include_historical=False)
    chosen = choose_rw_os_event(listed, event.name, tournament.name or "")
    if chosen is None:
        looked_for = [name.strip() for name in (event.name, tournament.name or "") if str(name or "").strip()]
        shown = " or ".join(f"'{name}'" for name in looked_for) or "this event"
        raise ValueError(f"No current RW-OS event matches {shown}.")
    source_id = int(chosen["tournamentId"])
    payload = client.get_event(source_id)
    incoming = _teams_for_event(payload, event, session)

    current = [
        team
        for team in session.exec(select(Team).where(Team.event_id == event.id)).all()
        if not team.is_defaulted
    ]
    locked = [team for team in current if _team_draw_lock_reason(session, team)]
    if locked:
        names = ", ".join(team.display_name or team.name for team in locked[:4])
        raise ValueError(f"These teams are already on a started match and were left in place: {names}")

    for team in current:
        _retire_team(session, tournament.id, team)  # type: ignore[arg-type]
    session.flush()

    result = RosterProjectionResult()
    created = []
    for seed, snapshot_team in enumerate(incoming, start=1):
        created.append(
            _create_source_team(
                session,
                event=event,
                snapshot_team=snapshot_team,
                seed=seed,
                result=result,
                wkw_assignments={},
                tournament_id=tournament.id,  # type: ignore[arg-type]
            )
        )

    event.team_count = len(created)
    session.add(event)
    tournament.source_rw_os_tournament_id = source_id
    if not tournament.source_rw_os_organization_slug:
        tournament.source_rw_os_organization_slug = str(payload.get("organizationSlug") or "rw")
    session.add(tournament)
    session.commit()
    return {
        "source_tournament_id": source_id,
        "source_event_name": str(payload.get("eventName") or chosen.get("eventName") or ""),
        "imported_count": len(created),
        "retired_count": len(current),
        "team_names": [team.display_name or team.name for team in created],
    }
