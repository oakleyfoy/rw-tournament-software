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
