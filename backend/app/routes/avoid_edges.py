"""
API Routes for Team Avoid Edges - Who-Knows-Who WF Grouping V1
"""

from typing import Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, model_validator
from sqlmodel import Session, select

from app.database import get_session
from app.models.event import Event
from app.models.team import Team
from app.models.team_avoid_edge import TeamAvoidEdge

router = APIRouter()


# ============================================================================
# Request/Response Models
# ============================================================================


class AvoidEdgeCreate(BaseModel):
    """Request model for creating an avoid edge"""

    team_id_a: int
    team_id_b: int
    reason: Optional[str] = None

    @model_validator(mode="after")
    def validate_different_teams(self):
        if self.team_id_a == self.team_id_b:
            raise ValueError("team_id_a and team_id_b must be different")
        return self


class AvoidEdgeResponse(BaseModel):
    """Response model for avoid edge"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    event_id: int
    team_id_a: int
    team_id_b: int
    reason: Optional[str] = None
    created_at: str


# ============================================================================
# Endpoints
# ============================================================================


@router.get("/events/{event_id}/avoid-edges", response_model=List[AvoidEdgeResponse])
def get_avoid_edges(event_id: int, session: Session = Depends(get_session)):
    """Get all avoid edges for an event"""
    # Validate event exists
    event = session.get(Event, event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    # Get all avoid edges for this event
    edges = session.exec(
        select(TeamAvoidEdge)
        .where(TeamAvoidEdge.event_id == event_id)
        .order_by(TeamAvoidEdge.team_id_a, TeamAvoidEdge.team_id_b)
    ).all()

    return [
        AvoidEdgeResponse(
            id=edge.id,
            event_id=edge.event_id,
            team_id_a=edge.team_id_a,
            team_id_b=edge.team_id_b,
            reason=edge.reason,
            created_at=edge.created_at.isoformat(),
        )
        for edge in edges
    ]


@router.post("/events/{event_id}/avoid-edges", response_model=AvoidEdgeResponse, status_code=201)
def create_avoid_edge(event_id: int, edge_data: AvoidEdgeCreate, session: Session = Depends(get_session)):
    """Create a new avoid edge between two teams"""
    # Validate event exists
    event = session.get(Event, event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    # Validate both teams exist and belong to this event
    team_a = session.get(Team, edge_data.team_id_a)
    team_b = session.get(Team, edge_data.team_id_b)

    if not team_a or team_a.event_id != event_id:
        raise HTTPException(status_code=404, detail=f"Team {edge_data.team_id_a} not found in this event")

    if not team_b or team_b.event_id != event_id:
        raise HTTPException(status_code=404, detail=f"Team {edge_data.team_id_b} not found in this event")

    # Ensure team_id_a < team_id_b (database constraint)
    team_id_a = min(edge_data.team_id_a, edge_data.team_id_b)
    team_id_b = max(edge_data.team_id_a, edge_data.team_id_b)

    # Check if edge already exists
    existing_edge = session.exec(
        select(TeamAvoidEdge).where(
            TeamAvoidEdge.event_id == event_id,
            TeamAvoidEdge.team_id_a == team_id_a,
            TeamAvoidEdge.team_id_b == team_id_b,
        )
    ).first()

    if existing_edge:
        raise HTTPException(
            status_code=409, detail=f"Avoid edge already exists between teams {team_id_a} and {team_id_b}"
        )

    # Create new edge
    new_edge = TeamAvoidEdge(event_id=event_id, team_id_a=team_id_a, team_id_b=team_id_b, reason=edge_data.reason)

    session.add(new_edge)
    session.commit()
    session.refresh(new_edge)

    return AvoidEdgeResponse(
        id=new_edge.id,
        event_id=new_edge.event_id,
        team_id_a=new_edge.team_id_a,
        team_id_b=new_edge.team_id_b,
        reason=new_edge.reason,
        created_at=new_edge.created_at.isoformat(),
    )


@router.delete("/events/{event_id}/avoid-edges/{edge_id}", status_code=204)
def delete_avoid_edge(event_id: int, edge_id: int, session: Session = Depends(get_session)):
    """Delete an avoid edge"""
    # Validate event exists
    event = session.get(Event, event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    # Get edge
    edge = session.get(TeamAvoidEdge, edge_id)
    if not edge or edge.event_id != event_id:
        raise HTTPException(status_code=404, detail="Avoid edge not found")

    # Delete edge
    session.delete(edge)
    session.commit()

    return None


# ============================================================================
# A1: Bulk Avoid-Edges Endpoint with Dry-Run Support
# ============================================================================


class EdgePair(BaseModel):
    """Single avoid edge pair"""

    team_a_id: int
    team_b_id: int
    reason: Optional[str] = None


class LinkGroup(BaseModel):
    """Group of teams that should all avoid each other"""

    code: str
    team_ids: List[int]
    reason: Optional[str] = None


class BulkAvoidEdgesRequest(BaseModel):
    """Request for bulk avoid edges creation"""

    pairs: Optional[List[EdgePair]] = None
    link_groups: Optional[List[LinkGroup]] = None


class RejectedItem(BaseModel):
    """An item that was rejected during bulk processing"""

    input: Dict
    error: str


class BulkAvoidEdgesResponse(BaseModel):
    """Response for bulk avoid edges operation"""

    dry_run: bool = False
    created_count: Optional[int] = None  # For real runs
    would_create_count: Optional[int] = None  # For dry runs
    skipped_duplicates_count: Optional[int] = None  # For real runs
    would_skip_duplicates_count: Optional[int] = None  # For dry runs
    rejected_count: int
    rejected_items: List[RejectedItem]
    created_edges_sample: Optional[List[Dict]] = None  # For real runs
    would_create_edges: Optional[List[Dict]] = None  # For dry runs


@router.post("/events/{event_id}/avoid-edges/bulk", response_model=BulkAvoidEdgesResponse)
def bulk_create_avoid_edges(
    event_id: int,
    request: BulkAvoidEdgesRequest,
    dry_run: bool = Query(False, description="Preview changes without writing to database"),
    session: Session = Depends(get_session),
):
    """
    Bulk create avoid edges from pairs or link groups.

    Supports two input formats:
    1. pairs: List of explicit team pairs
    2. link_groups: Groups of teams (expands to all pairwise edges)

    With dry_run=true:
    - Validates all inputs
    - Expands link groups
    - Returns preview of what would be created
    - Does NOT write to database

    With dry_run=false (default):
    - Creates all edges
    - Commits to database
    - Returns actual results

    Behavior:
    - Normalizes edges to (min_id, max_id)
    - Rejects self-edges
    - Ignores exact duplicates (idempotent)
    - Validates all team IDs exist in event
    """
    # Validate event exists
    event = session.get(Event, event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    # Load all teams for this event for validation
    teams = session.exec(select(Team).where(Team.event_id == event_id)).all()
    team_ids_set = {team.id for team in teams}

    # Load existing edges for duplicate detection
    existing_edges = session.exec(select(TeamAvoidEdge).where(TeamAvoidEdge.event_id == event_id)).all()
    existing_edges_set = {(edge.team_id_a, edge.team_id_b) for edge in existing_edges}

    # Collect all edges to create
    edges_to_create: List[Tuple[int, int, Optional[str]]] = []
    rejected_items: List[RejectedItem] = []

    # Process pairs
    if request.pairs:
        for pair in request.pairs:
            team_a_id = pair.team_a_id
            team_b_id = pair.team_b_id
            reason = pair.reason

            # Validate self-edge
            if team_a_id == team_b_id:
                rejected_items.append(
                    RejectedItem(input={"team_a_id": team_a_id, "team_b_id": team_b_id}, error="SELF_EDGE")
                )
                continue

            # Validate team IDs exist
            if team_a_id not in team_ids_set:
                rejected_items.append(
                    RejectedItem(input={"team_a_id": team_a_id, "team_b_id": team_b_id}, error="INVALID_TEAM_ID")
                )
                continue

            if team_b_id not in team_ids_set:
                rejected_items.append(
                    RejectedItem(input={"team_a_id": team_a_id, "team_b_id": team_b_id}, error="INVALID_TEAM_ID")
                )
                continue

            # Normalize to canonical form
            normalized_a = min(team_a_id, team_b_id)
            normalized_b = max(team_a_id, team_b_id)

            edges_to_create.append((normalized_a, normalized_b, reason))

    # Process link groups
    if request.link_groups:
        for group in request.link_groups:
            # Validate all team IDs in group
            invalid_ids = [tid for tid in group.team_ids if tid not in team_ids_set]
            if invalid_ids:
                rejected_items.append(
                    RejectedItem(input={"code": group.code, "team_ids": group.team_ids}, error="TEAM_NOT_IN_EVENT")
                )
                continue

            # Expand to all pairwise edges
            for i in range(len(group.team_ids)):
                for j in range(i + 1, len(group.team_ids)):
                    team_a_id = group.team_ids[i]
                    team_b_id = group.team_ids[j]

                    # Skip self-edges (shouldn't happen but defensive)
                    if team_a_id == team_b_id:
                        continue

                    # Normalize
                    normalized_a = min(team_a_id, team_b_id)
                    normalized_b = max(team_a_id, team_b_id)

                    edges_to_create.append((normalized_a, normalized_b, group.reason))

    # De-duplicate edges (keep first occurrence)
    seen_edges: set = set()
    unique_edges: List[Tuple[int, int, Optional[str]]] = []
    duplicates_count = 0

    for edge in edges_to_create:
        edge_key = (edge[0], edge[1])
        if edge_key in seen_edges or edge_key in existing_edges_set:
            duplicates_count += 1
        else:
            seen_edges.add(edge_key)
            unique_edges.append(edge)

    # Sort edges deterministically
    unique_edges.sort(key=lambda e: (e[0], e[1], e[2] or ""))

    # DRY RUN MODE
    if dry_run:
        # Return preview without writing to database
        would_create_edges = [
            {"team_id_a": edge[0], "team_id_b": edge[1], "reason": edge[2]}
            for edge in unique_edges[:50]  # Limit to first 50
        ]

        return BulkAvoidEdgesResponse(
            dry_run=True,
            would_create_count=len(unique_edges),
            would_skip_duplicates_count=duplicates_count,
            rejected_count=len(rejected_items),
            rejected_items=rejected_items,
            would_create_edges=would_create_edges,
        )

    # REAL MODE - Write to database
    created_edges = []
    for edge in unique_edges:
        new_edge = TeamAvoidEdge(event_id=event_id, team_id_a=edge[0], team_id_b=edge[1], reason=edge[2])
        session.add(new_edge)
        created_edges.append(new_edge)

    session.commit()

    # Refresh to get IDs
    for edge in created_edges:
        session.refresh(edge)

    # Build response
    created_edges_sample = [
        {"id": edge.id, "team_id_a": edge.team_id_a, "team_id_b": edge.team_id_b, "reason": edge.reason}
        for edge in created_edges[:20]  # First 20
    ]

    return BulkAvoidEdgesResponse(
        dry_run=False,
        created_count=len(created_edges),
        skipped_duplicates_count=duplicates_count,
        rejected_count=len(rejected_items),
        rejected_items=rejected_items,
        created_edges_sample=created_edges_sample,
    )
