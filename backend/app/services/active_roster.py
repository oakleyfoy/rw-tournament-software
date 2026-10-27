"""Canonical active-team rule for operational tournament views.

A team is active when it is not withdrawn, cancelled, or defaulted.
RW-OS refresh stores that state on ``Team.is_defaulted``: a source team that
leaves the active RW-OS roster is marked inactive when no started, scored,
won, or advanced match protects it. Historical rows stay in the database.
"""

from __future__ import annotations

from app.models.team import Team


def team_is_active(team: Team) -> bool:
    return not bool(team.is_defaulted)


def visible_roster_teams(teams: list[Team], matches: list) -> list[Team]:
    """Teams that belong on the desk and on Watermark & Print.

    Withdrawn teams stay out. Once an event has a draw, a team with no seed
    and no match is a leftover partner row, not a team in that event.
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
    return visible
