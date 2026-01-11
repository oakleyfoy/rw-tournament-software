"""
Who-Knows-Who WF Grouping V1 - Conflict-Minimizing Team Grouping

This module implements the grouping algorithm for waterfall events to minimize
conflicts between teams that should avoid playing each other in WF rounds.
"""

from math import ceil, floor
from typing import Dict, List, Set, Tuple

from sqlmodel import Session, select

from app.models.event import Event
from app.models.team import Team
from app.models.team_avoid_edge import TeamAvoidEdge

# ============================================================================
# Phase W3: Groups Count Computation
# ============================================================================


def compute_groups_count(team_count: int) -> int:
    """
    Compute number of groups for WF grouping.

    Deterministic rule:
    groups_count = max(1, ceil(team_count / 4))

    This yields nearly all size-4 groups when team_count is a multiple of 4.

    Examples:
    - 12 teams → 3 groups
    - 16 teams → 4 groups
    - 20 teams → 5 groups
    - 24 teams → 6 groups

    Args:
        team_count: Number of teams in the event

    Returns:
        Number of groups to create
    """
    if team_count <= 0:
        return 1
    return max(1, ceil(team_count / 4))


def compute_group_capacities(team_count: int, groups_count: int) -> List[int]:
    """
    Compute capacity (size) for each group.

    Algorithm:
    - base_size = floor(team_count / groups_count)
    - remainder = team_count % groups_count
    - First `remainder` groups have size (base_size + 1)
    - Remaining groups have size base_size

    This distributes teams as evenly as possible.

    Args:
        team_count: Number of teams to distribute
        groups_count: Number of groups

    Returns:
        List of group capacities (sizes), length = groups_count
    """
    if groups_count <= 0:
        return []

    base_size = floor(team_count / groups_count)
    remainder = team_count % groups_count

    capacities = []
    for i in range(groups_count):
        if i < remainder:
            capacities.append(base_size + 1)
        else:
            capacities.append(base_size)

    return capacities


# ============================================================================
# Phase W4: Conflict-Minimizing Grouping Algorithm
# ============================================================================


class GroupingResult:
    """Result of WF grouping operation"""

    def __init__(
        self,
        event_id: int,
        team_count: int,
        groups_count: int,
        group_sizes: List[int],
        team_assignments: Dict[int, int],  # team_id → group_index
        total_internal_conflicts: int,
        conflicts_by_group: Dict[int, int],  # group_index → conflict_count
        conflicted_pairs: List[Tuple[int, int, int]],  # (team_a_id, team_b_id, group_index)
    ):
        self.event_id = event_id
        self.team_count = team_count
        self.groups_count = groups_count
        self.group_sizes = group_sizes
        self.team_assignments = team_assignments
        self.total_internal_conflicts = total_internal_conflicts
        self.conflicts_by_group = conflicts_by_group
        self.conflicted_pairs = conflicted_pairs


def assign_wf_groups_v1(session: Session, event_id: int, clear_existing: bool = True) -> GroupingResult:
    """
    Assign teams to WF groups using conflict-minimizing algorithm.

    Algorithm:
    1. Load teams in deterministic order
    2. Load avoid edges and build adjacency
    3. Compute degree (number of avoid links) for each team
    4. Sort teams by: degree DESC, seed ASC, rating DESC, timestamp ASC, id ASC
    5. For each team, assign to group with minimum:
       - penalty (number of conflicts with teams already in group)
       - current group size (for balance)
       - group_index (tie-breaker)
    6. Persist wf_group_index for each team
    7. Return diagnostics

    Args:
        session: Database session
        event_id: Event ID
        clear_existing: If true, clear existing group assignments first

    Returns:
        GroupingResult with diagnostics
    """
    # Validate event exists
    event = session.get(Event, event_id)
    if not event:
        raise ValueError(f"Event {event_id} not found")

    # Clear existing group assignments if requested
    if clear_existing:
        teams_to_clear = session.exec(select(Team).where(Team.event_id == event_id)).all()
        for team in teams_to_clear:
            team.wf_group_index = None
            session.add(team)
        session.commit()

    # Load teams in deterministic order
    teams = session.exec(
        select(Team)
        .where(Team.event_id == event_id)
        .order_by(Team.seed.asc(), Team.rating.desc(), Team.registration_timestamp.asc(), Team.id.asc())
    ).all()

    team_count = len(teams)

    if team_count == 0:
        # No teams, return empty result
        return GroupingResult(
            event_id=event_id,
            team_count=0,
            groups_count=0,
            group_sizes=[],
            team_assignments={},
            total_internal_conflicts=0,
            conflicts_by_group={},
            conflicted_pairs=[],
        )

    # Load avoid edges and build adjacency
    edges = session.exec(select(TeamAvoidEdge).where(TeamAvoidEdge.event_id == event_id)).all()

    # Build adjacency set: {team_id: {other_team_ids to avoid}}
    adjacency: Dict[int, Set[int]] = {team.id: set() for team in teams}

    for edge in edges:
        adjacency[edge.team_id_a].add(edge.team_id_b)
        adjacency[edge.team_id_b].add(edge.team_id_a)

    # Compute degree for each team
    team_degrees: Dict[int, int] = {team.id: len(adjacency[team.id]) for team in teams}

    # Sort teams by conflict-minimizing priority
    sorted_teams = sorted(
        teams,
        key=lambda t: (
            -team_degrees[t.id],  # Higher degree first (more constrained)
            t.seed if t.seed is not None else float("inf"),  # Lower seed first
            -(t.rating if t.rating is not None else 0),  # Higher rating first
            t.registration_timestamp if t.registration_timestamp is not None else float("inf"),
            t.id,
        ),
    )

    # Compute groups_count and capacities
    groups_count = compute_groups_count(team_count)
    group_capacities = compute_group_capacities(team_count, groups_count)

    # Initialize groups
    groups: List[List[int]] = [[] for _ in range(groups_count)]
    team_assignments: Dict[int, int] = {}

    # Assign each team to best group
    for team in sorted_teams:
        best_group_index = None
        best_penalty = float("inf")
        best_size = float("inf")

        for group_index in range(groups_count):
            # Check if group has capacity
            if len(groups[group_index]) >= group_capacities[group_index]:
                continue

            # Calculate penalty: number of conflicts with teams already in this group
            penalty = 0
            for other_team_id in groups[group_index]:
                if other_team_id in adjacency[team.id]:
                    penalty += 1

            current_size = len(groups[group_index])

            # Choose group with minimum: penalty, size, group_index
            if (penalty, current_size, group_index) < (best_penalty, best_size, best_group_index or float("inf")):
                best_group_index = group_index
                best_penalty = penalty
                best_size = current_size

        # Assign team to best group
        if best_group_index is not None:
            groups[best_group_index].append(team.id)
            team_assignments[team.id] = best_group_index

            # Persist to database
            team.wf_group_index = best_group_index
            session.add(team)

    session.commit()

    # Compute diagnostics
    total_internal_conflicts = 0
    conflicts_by_group: Dict[int, int] = {i: 0 for i in range(groups_count)}
    conflicted_pairs: List[Tuple[int, int, int]] = []

    for group_index, group_teams in enumerate(groups):
        group_conflicts = 0

        # Check all pairs within this group
        for i in range(len(group_teams)):
            for j in range(i + 1, len(group_teams)):
                team_a_id = group_teams[i]
                team_b_id = group_teams[j]

                # Check if there's an avoid edge between these teams
                if team_b_id in adjacency[team_a_id]:
                    group_conflicts += 1
                    total_internal_conflicts += 1
                    conflicted_pairs.append((min(team_a_id, team_b_id), max(team_a_id, team_b_id), group_index))

        conflicts_by_group[group_index] = group_conflicts

    # Compute actual group sizes
    group_sizes = [len(group) for group in groups]

    return GroupingResult(
        event_id=event_id,
        team_count=team_count,
        groups_count=groups_count,
        group_sizes=group_sizes,
        team_assignments=team_assignments,
        total_internal_conflicts=total_internal_conflicts,
        conflicts_by_group=conflicts_by_group,
        conflicted_pairs=conflicted_pairs,
    )
