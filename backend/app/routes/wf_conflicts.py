"""
API Routes for WF Conflict Lens - Audit Trail for Who-Knows-Who
"""

from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from app.database import get_session
from app.models.event import Event
from app.models.team import Team
from app.models.team_avoid_edge import TeamAvoidEdge

router = APIRouter()


# ============================================================================
# Response Models
# ============================================================================


class TopDegreeTeam(BaseModel):
    """Team with high conflict degree"""

    team_id: int
    team_name: str
    degree: int  # Number of avoid edges


class ConflictedPairDetail(BaseModel):
    """Detailed conflict pair information"""

    team_a_id: int
    team_a_name: str
    team_b_id: int
    team_b_name: str
    group_index: int
    reason: Optional[str] = None


class GraphSummary(BaseModel):
    """Summary of the avoid-edges graph"""

    team_count: int
    avoid_edges_count: int
    connected_components_count: int
    largest_component_size: int
    top_degree_teams: List[TopDegreeTeam]


class GroupingSummary(BaseModel):
    """Summary of WF grouping results"""

    groups_count: int
    group_sizes: List[int]
    total_internal_conflicts: int
    conflicts_by_group: Dict[int, int]


class SeparationEffectiveness(BaseModel):
    """Metrics for separation effectiveness"""

    separated_edges: int
    separation_rate: float  # 0.0 to 1.0


class WFConflictLensV1(BaseModel):
    """Complete WF conflict analysis lens"""

    event_id: int
    event_name: str
    graph_summary: GraphSummary
    grouping_summary: Optional[GroupingSummary] = None
    unavoidable_conflicts: List[ConflictedPairDetail]
    separation_effectiveness: Optional[SeparationEffectiveness] = None


# ============================================================================
# Endpoint
# ============================================================================


@router.get("/events/{event_id}/waterfall/conflicts", response_model=WFConflictLensV1)
def get_wf_conflict_lens(event_id: int, session: Session = Depends(get_session)):
    """
    Get comprehensive WF conflict analysis for an event.

    Provides:
    - Graph summary (edges, components, top-degree teams)
    - Grouping summary (if grouping has been run)
    - Unavoidable conflicts (pairs in same group)
    - Separation effectiveness metrics

    This endpoint provides the audit trail showing "we did everything possible"
    to separate conflicting teams.
    """
    # Validate event exists
    event = session.get(Event, event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    # Load teams
    teams = session.exec(select(Team).where(Team.event_id == event_id)).all()
    team_count = len(teams)
    team_map = {team.id: team for team in teams}

    # Load avoid edges
    edges = session.exec(select(TeamAvoidEdge).where(TeamAvoidEdge.event_id == event_id)).all()
    avoid_edges_count = len(edges)

    # Build adjacency for graph analysis
    adjacency: Dict[int, set] = {team.id: set() for team in teams}
    for edge in edges:
        adjacency[edge.team_id_a].add(edge.team_id_b)
        adjacency[edge.team_id_b].add(edge.team_id_a)

    # Find connected components (simple DFS)
    visited = set()
    components = []

    def dfs(node, component):
        visited.add(node)
        component.append(node)
        for neighbor in adjacency.get(node, []):
            if neighbor not in visited:
                dfs(neighbor, component)

    for team_id in adjacency.keys():
        if team_id not in visited:
            component = []
            dfs(team_id, component)
            components.append(component)

    connected_components_count = len(components)
    largest_component_size = max([len(c) for c in components]) if components else 0

    # Top degree teams
    team_degrees = [(team_id, len(neighbors)) for team_id, neighbors in adjacency.items()]
    team_degrees.sort(key=lambda x: (-x[1], x[0]))  # Desc by degree, asc by ID

    top_degree_teams = [
        TopDegreeTeam(team_id=team_id, team_name=team_map[team_id].name, degree=degree)
        for team_id, degree in team_degrees[:10]
        if degree > 0  # Only teams with conflicts
    ]

    graph_summary = GraphSummary(
        team_count=team_count,
        avoid_edges_count=avoid_edges_count,
        connected_components_count=connected_components_count,
        largest_component_size=largest_component_size,
        top_degree_teams=top_degree_teams,
    )

    # Check if grouping has been assigned
    grouped_teams = [t for t in teams if t.wf_group_index is not None]
    grouping_summary = None
    unavoidable_conflicts = []
    separation_effectiveness = None

    if grouped_teams:
        # Build groups
        groups: Dict[int, List[int]] = {}
        for team in grouped_teams:
            if team.wf_group_index not in groups:
                groups[team.wf_group_index] = []
            groups[team.wf_group_index].append(team.id)

        groups_count = len(groups)
        group_sizes = [len(groups[i]) for i in sorted(groups.keys())]

        # Count internal conflicts
        total_internal_conflicts = 0
        conflicts_by_group: Dict[int, int] = {i: 0 for i in groups.keys()}
        conflicted_pairs = []

        for group_index, group_teams in groups.items():
            group_conflicts = 0

            # Check all pairs within group
            for i in range(len(group_teams)):
                for j in range(i + 1, len(group_teams)):
                    team_a_id = group_teams[i]
                    team_b_id = group_teams[j]

                    # Check if avoid edge exists
                    if team_b_id in adjacency[team_a_id]:
                        group_conflicts += 1
                        total_internal_conflicts += 1

                        # Find the edge for reason
                        edge_reason = None
                        for edge in edges:
                            if edge.team_id_a == min(team_a_id, team_b_id) and edge.team_id_b == max(
                                team_a_id, team_b_id
                            ):
                                edge_reason = edge.reason
                                break

                        conflicted_pairs.append(
                            ConflictedPairDetail(
                                team_a_id=team_a_id,
                                team_a_name=team_map[team_a_id].name,
                                team_b_id=team_b_id,
                                team_b_name=team_map[team_b_id].name,
                                group_index=group_index,
                                reason=edge_reason,
                            )
                        )

            conflicts_by_group[group_index] = group_conflicts

        grouping_summary = GroupingSummary(
            groups_count=groups_count,
            group_sizes=group_sizes,
            total_internal_conflicts=total_internal_conflicts,
            conflicts_by_group=conflicts_by_group,
        )

        unavoidable_conflicts = conflicted_pairs

        # Calculate separation effectiveness
        separated_edges = avoid_edges_count - total_internal_conflicts
        separation_rate = separated_edges / avoid_edges_count if avoid_edges_count > 0 else 1.0

        separation_effectiveness = SeparationEffectiveness(
            separated_edges=separated_edges, separation_rate=separation_rate
        )

    return WFConflictLensV1(
        event_id=event_id,
        event_name=event.name,
        graph_summary=graph_summary,
        grouping_summary=grouping_summary,
        unavoidable_conflicts=unavoidable_conflicts,
        separation_effectiveness=separation_effectiveness,
    )
