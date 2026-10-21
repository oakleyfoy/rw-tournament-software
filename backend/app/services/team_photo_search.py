"""Search tournament teams by either partner's name.

Matching is in memory after loading the tournament roster. Team identity is
always `team.id` for that tournament event. Photos are never attached to
player rows, and a query cannot return teams from another tournament.
"""

from __future__ import annotations

import re
from typing import Iterable, Optional

from sqlmodel import Session, select

from app.models.event import Event
from app.models.player import Player
from app.models.team import Team
from app.models.team_photo import TeamOfficialPhoto
from app.models.team_player import TeamPlayer

_SPLIT_PARTNERS = re.compile(r"\s*(?:/|&|\band\b)\s*", re.IGNORECASE)


def person_matches(query: str, person_name: str) -> bool:
    """True when the query matches a first name, last name, or partial name."""
    q = " ".join((query or "").lower().split())
    if not q or not person_name:
        return False
    person = " ".join(person_name.lower().replace(",", " ").split())
    if q in person:
        return True
    tokens = [token for token in person.split(" ") if token]
    if not tokens:
        return False
    if any(token.startswith(q) for token in tokens):
        return True
    q_parts = q.split(" ")
    if len(q_parts) >= 2:
        return tokens[0].startswith(q_parts[0]) and tokens[-1].startswith(q_parts[-1])
    return False


def team_matches_query(query: str, player_names: Iterable[str]) -> bool:
    return any(person_matches(query, name) for name in player_names if name and name != "Partner not on file")


def _partner_names_from_label(label: Optional[str]) -> list[str]:
    text = (label or "").strip()
    if not text:
        return []
    parts = [part.strip(" ,") for part in _SPLIT_PARTNERS.split(text) if part.strip(" ,")]
    return parts


def player_names_for_team(team: Team, linked_names: list[str]) -> list[str]:
    names = [name.strip() for name in linked_names if name and name.strip()]
    if len(names) < 2:
        for candidate in _partner_names_from_label(team.name) + _partner_names_from_label(team.display_name):
            if candidate not in names:
                names.append(candidate)
            if len(names) >= 2:
                break
    while len(names) < 2:
        names.append("Partner not on file")
    return names[:2]


def search_tournament_teams(session: Session, tournament_id: int, query: str, limit: int = 20) -> list[dict]:
    cleaned = " ".join((query or "").split())
    if not cleaned:
        return []

    events = session.exec(select(Event).where(Event.tournament_id == tournament_id)).all()
    event_by_id = {event.id: event for event in events if event.id is not None}
    if not event_by_id:
        return []

    teams = session.exec(select(Team).where(Team.event_id.in_(list(event_by_id)))).all()  # type: ignore[attr-defined]
    if not teams:
        return []

    team_ids = [team.id for team in teams if team.id is not None]
    links = session.exec(select(TeamPlayer).where(TeamPlayer.team_id.in_(team_ids))).all()  # type: ignore[attr-defined]
    player_ids = {link.player_id for link in links}
    players = session.exec(select(Player).where(Player.id.in_(list(player_ids)))).all() if player_ids else []  # type: ignore[attr-defined]
    player_by_id = {player.id: player for player in players if player.id is not None}
    names_by_team: dict[int, list[tuple[int, str]]] = {}
    for link in links:
        player = player_by_id.get(link.player_id)
        if not player:
            continue
        slot = link.lineup_slot if link.lineup_slot is not None else 99
        names_by_team.setdefault(link.team_id, []).append((slot, player.full_name))

    official_rows = session.exec(
        select(TeamOfficialPhoto).where(TeamOfficialPhoto.team_id.in_(team_ids))  # type: ignore[attr-defined]
    ).all()
    official_team_ids = {row.team_id for row in official_rows}

    hits: list[dict] = []
    for team in teams:
        if team.id is None:
            continue
        ordered = [name for _slot, name in sorted(names_by_team.get(team.id, []))]
        names = player_names_for_team(team, ordered)
        if not team_matches_query(cleaned, names):
            continue
        event = event_by_id.get(team.event_id)
        hits.append(
            {
                "team_id": team.id,
                "event_id": team.event_id,
                "division": event.name if event else "",
                "seed": team.seed,
                "player_names": names,
                "avoid_group": team.avoid_group,
                "source_team_key": team.source_team_key,
                "has_official_photo": team.id in official_team_ids,
            }
        )

    hits.sort(key=lambda hit: ((hit["seed"] is None), hit["seed"] or 0, hit["division"], hit["team_id"]))
    return hits[:limit]
