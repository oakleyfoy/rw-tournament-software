"""
API Routes for WF Grouping - Who-Knows-Who V1
"""

from typing import Dict, List

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlmodel import Session

from app.database import get_session
from app.models.event import Event
from app.utils.wf_grouping import assign_wf_groups_v1

router = APIRouter()


# ============================================================================
# Response Models
# ============================================================================


class ConflictedPair(BaseModel):
    """A pair of teams that are in the same group despite having an avoid edge"""

    team_a_id: int
    team_b_id: int
    group_index: int


class GroupingResponse(BaseModel):
    """Response model for WF grouping operation"""

    event_id: int
    team_count: int
    groups_count: int
    group_sizes: List[int]
    total_internal_conflicts: int
    conflicts_by_group: Dict[int, int]
    conflicted_pairs: List[ConflictedPair]


# ============================================================================
# Endpoints
# ============================================================================


@router.post("/events/{event_id}/waterfall/assign-groups", response_model=GroupingResponse)
def assign_waterfall_groups(
    event_id: int,
    clear_existing: bool = Query(True, description="Clear existing group assignments before running"),
    session: Session = Depends(get_session),
):
    """
    Assign teams to WF groups using conflict-minimizing algorithm.

    This endpoint is idempotent when clear_existing=True (default).

    Algorithm:
    1. Compute groups_count = max(1, ceil(team_count / 4))
    2. Sort teams by: degree DESC, seed ASC, rating DESC, timestamp ASC, id ASC
    3. For each team, assign to group with minimum:
       - penalty (conflicts with teams already in group)
       - current group size (for balance)
       - group_index (tie-breaker)
    4. Persist wf_group_index for each team
    5. Return diagnostics including conflicts

    Returns:
        GroupingResponse with:
        - groups_count: Number of groups created
        - group_sizes: Size of each group
        - total_internal_conflicts: Total number of unavoidable conflicts
        - conflicts_by_group: Conflict count per group
        - conflicted_pairs: List of conflicted team pairs (top 20)
    """
    # Validate event exists
    event = session.get(Event, event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    # Run grouping algorithm
    try:
        result = assign_wf_groups_v1(session, event_id, clear_existing)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Convert conflicted_pairs to response format (limit to top 20)
    conflicted_pairs_response = [
        ConflictedPair(team_a_id=pair[0], team_b_id=pair[1], group_index=pair[2])
        for pair in result.conflicted_pairs[:20]
    ]

    return GroupingResponse(
        event_id=result.event_id,
        team_count=result.team_count,
        groups_count=result.groups_count,
        group_sizes=result.group_sizes,
        total_internal_conflicts=result.total_internal_conflicts,
        conflicts_by_group=result.conflicts_by_group,
        conflicted_pairs=conflicted_pairs_response,
    )
