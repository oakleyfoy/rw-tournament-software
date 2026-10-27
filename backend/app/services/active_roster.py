"""Canonical active-team rule for operational tournament views.

A team is active when it is not withdrawn, cancelled, or defaulted.
RW-OS refresh stores that state on ``Team.is_defaulted``: a source team that
leaves the active RW-OS roster is marked inactive when no started, scored,
won, or advanced match protects it. Historical rows stay in the database.
"""

from __future__ import annotations

import re

from app.models.team import Team

_CLONE_SUFFIX = re.compile(r"\s+\(\d+\)$")


def team_is_active(team: Team) -> bool:
    return not bool(team.is_defaulted)


def _plain_team_name(value: str | None) -> str:
    raw = " ".join((value or "").strip().split())
    while True:
        trimmed = _CLONE_SUFFIX.sub("", raw).strip()
        if trimmed == raw:
            return raw.casefold()
        raw = trimmed


def _roster_identity(team: Team) -> str:
    return _plain_team_name(team.name) or _plain_team_name(team.display_name)


def _roster_keep_rank(team: Team, on_a_match: set) -> tuple:
    """Prefer the real row over a numbered copy of the same partnership."""
    return (
        1 if _CLONE_SUFFIX.search((team.name or "").strip()) else 0,
        0 if team.id in on_a_match else 1,
        team.seed if team.seed is not None else 10**9,
        team.id or 0,
    )


def _fits_event_draw(group: list[Team], on_a_match: set, draw_size: int) -> list[Team]:
    """Keep the draw, and only fill a missing seed from a team that is on a match."""
    seeded = [team for team in group if team.seed is not None and 1 <= team.seed <= draw_size]
    used = {team.seed for team in seeded}
    open_slots = draw_size - len(used)
    if open_slots <= 0:
        return seeded
    fillers = sorted(
        (team for team in group if team.seed is None and team.id in on_a_match),
        key=lambda team: (team.rating is None, -(team.rating or 0), team.id or 0),
    )
    return seeded + fillers[:open_slots]


def visible_roster_teams(
    teams: list[Team],
    matches: list,
    draw_sizes: dict | None = None,
) -> list[Team]:
    """Teams that belong on the desk and on Watermark & Print.

    Withdrawn teams stay out. Once an event has a draw, a team with no seed
    and no match is a leftover partner row, not a team in that event.
    A second row of the same partnership, including a " (5)" copy, stays out.
    A drawn event also stays at its draw size, so a partner row cannot become seed 33.
    """
    events_with_matches = {match.event_id for match in matches}
    on_a_match = {
        team_id
        for match in matches
        for team_id in (match.team_a_id, match.team_b_id)
        if team_id is not None
    }
    visible: list[Team] = []
    for team in teams:
        if not team_is_active(team):
            continue
        if team.seed is not None or team.id in on_a_match or team.event_id not in events_with_matches:
            visible.append(team)

    chosen: dict[tuple, Team] = {}
    for team in visible:
        identity = _roster_identity(team)
        if not identity:
            continue
        key = (team.event_id, identity)
        current = chosen.get(key)
        if current is None or _roster_keep_rank(team, on_a_match) < _roster_keep_rank(current, on_a_match):
            chosen[key] = team
    kept_ids = {team.id for team in chosen.values()}
    roster = [team for team in visible if not _roster_identity(team) or team.id in kept_ids]
    if not draw_sizes:
        return roster

    by_event: dict = {}
    for team in roster:
        by_event.setdefault(team.event_id, []).append(team)
    allowed_ids: set = set()
    for event_id, group in by_event.items():
        draw_size = draw_sizes.get(event_id) or 0
        if event_id not in events_with_matches or draw_size <= 0:
            allowed_ids.update(team.id for team in group if team.id is not None)
            continue
        allowed_ids.update(team.id for team in _fits_event_draw(group, on_a_match, draw_size) if team.id is not None)
    return [team for team in roster if team.id in allowed_ids]
