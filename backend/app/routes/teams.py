"""
Team Management API Routes
Provides CRUD operations for teams within events and team injection.
"""

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from sqlmodel import Session, select

from app.database import get_session
from app.models.event import Event
from app.models.team import Team
from app.utils.team_injection import TeamInjectionError, inject_teams_v1

router = APIRouter()


# ============================================================================
# Request/Response Models
# ============================================================================


class TeamCreateRequest(BaseModel):
    name: str
    seed: Optional[int] = None
    rating: Optional[float] = None
    registration_timestamp: Optional[datetime] = None


class TeamUpdateRequest(BaseModel):
    name: Optional[str] = None
    seed: Optional[int] = None
    rating: Optional[float] = None


class TeamResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    event_id: int
    name: str
    seed: Optional[int] = None
    rating: Optional[float] = None
    registration_timestamp: Optional[datetime] = None
    created_at: datetime
    wf_group_index: Optional[int] = None  # A2: WF Grouping info


# ============================================================================
# Team CRUD Endpoints
# ============================================================================


@router.get("/events/{event_id}/teams", response_model=List[TeamResponse])
def get_teams(event_id: int, session: Session = Depends(get_session)):
    """
    Get all teams for an event.

    Returns teams in deterministic order:
    1. seed ascending (nulls last)
    2. rating descending (nulls last)
    3. registration_timestamp ascending (nulls last)
    4. id ascending
    """
    # Verify event exists
    event = session.get(Event, event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    # Query teams with deterministic ordering
    query = select(Team).where(Team.event_id == event_id)
    teams = session.exec(query).all()

    # Sort deterministically in Python (SQLite sorting nulls is tricky)
    def sort_key(team: Team):
        return (
            # seed: nulls last, ascending
            (team.seed is None, team.seed if team.seed is not None else 0),
            # rating: nulls last, descending (negate for desc)
            (team.rating is None, -(team.rating if team.rating is not None else 0)),
            # registration_timestamp: nulls last, ascending
            (
                team.registration_timestamp is None,
                team.registration_timestamp if team.registration_timestamp is not None else datetime.max,
            ),
            # id: ascending
            team.id,
        )

    sorted_teams = sorted(teams, key=sort_key)

    return sorted_teams


@router.post("/events/{event_id}/teams", response_model=TeamResponse, status_code=201)
def create_team(event_id: int, request: TeamCreateRequest, session: Session = Depends(get_session)):
    """
    Create a new team for an event.

    Constraints:
    - (event_id, seed) must be unique if seed is not null
    - (event_id, name) must be unique
    """
    # Verify event exists
    event = session.get(Event, event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    # Create team
    team = Team(
        event_id=event_id,
        name=request.name,
        seed=request.seed,
        rating=request.rating,
        registration_timestamp=request.registration_timestamp,
    )

    try:
        session.add(team)
        session.commit()
        session.refresh(team)
        return team
    except Exception as e:
        session.rollback()
        # Check for constraint violations
        if "UNIQUE constraint failed" in str(e) or "IntegrityError" in str(type(e).__name__):
            if "seed" in str(e):
                raise HTTPException(
                    status_code=409, detail=f"Team with seed {request.seed} already exists for this event"
                )
            elif "name" in str(e):
                raise HTTPException(
                    status_code=409, detail=f"Team with name '{request.name}' already exists for this event"
                )
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/events/{event_id}/teams/{team_id}", response_model=TeamResponse)
def update_team(event_id: int, team_id: int, request: TeamUpdateRequest, session: Session = Depends(get_session)):
    """
    Update a team's name, seed, or rating.
    """
    # Get team
    team = session.get(Team, team_id)
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")

    # Verify team belongs to event
    if team.event_id != event_id:
        raise HTTPException(status_code=400, detail="Team does not belong to this event")

    # Update fields
    if request.name is not None:
        team.name = request.name
    if request.seed is not None:
        team.seed = request.seed
    if request.rating is not None:
        team.rating = request.rating

    try:
        session.add(team)
        session.commit()
        session.refresh(team)
        return team
    except Exception as e:
        session.rollback()
        if "UNIQUE constraint failed" in str(e) or "IntegrityError" in str(type(e).__name__):
            if "seed" in str(e):
                raise HTTPException(
                    status_code=409, detail=f"Team with seed {request.seed} already exists for this event"
                )
            elif "name" in str(e):
                raise HTTPException(
                    status_code=409, detail=f"Team with name '{request.name}' already exists for this event"
                )
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/events/{event_id}/teams/{team_id}", status_code=204)
def delete_team(event_id: int, team_id: int, session: Session = Depends(get_session)):
    """
    Delete a team.
    """
    # Get team
    team = session.get(Team, team_id)
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")

    # Verify team belongs to event
    if team.event_id != event_id:
        raise HTTPException(status_code=400, detail="Team does not belong to this event")

    # Delete team
    session.delete(team)
    session.commit()

    return None


# ============================================================================
# Team Injection Endpoint
# ============================================================================


class TeamInjectionResponse(BaseModel):
    teams_count: int
    matches_updated_count: int
    injection_type: str  # "bracket" | "round_robin"
    warnings: List[str]


@router.post("/events/{event_id}/schedule/versions/{version_id}/inject-teams", response_model=TeamInjectionResponse)
def inject_teams(
    event_id: int,
    version_id: int,
    clear_existing: bool = Query(True, description="Clear existing team assignments before injection"),
    session: Session = Depends(get_session),
):
    """
    Inject teams into matches for an event's schedule version.

    Rules:
    - If team_count > 8: Reject (400)
    - If team_count == 8: Bracket injection (assigns QFs only)
    - If team_count < 8: Round robin injection (assigns all matches)

    Team assignment is deterministic based on:
    1. seed (ascending, nulls last)
    2. rating (descending, nulls last)
    3. registration_timestamp (ascending, nulls last)
    4. id (ascending)

    Args:
        event_id: Event ID
        version_id: Schedule version ID
        clear_existing: If true, clears all team assignments before injection

    Returns:
        Summary of injection results
    """
    try:
        result = inject_teams_v1(
            session=session, event_id=event_id, schedule_version_id=version_id, clear_existing=clear_existing
        )
        return TeamInjectionResponse(**result)
    except TeamInjectionError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Injection failed: {str(e)}")
