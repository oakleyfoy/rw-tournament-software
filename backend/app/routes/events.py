from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator
from sqlmodel import Session, select

from app.database import get_session
from app.models.event import Event, EventCategory
from app.models.tournament import Tournament

router = APIRouter()


class EventCreate(BaseModel):
    category: EventCategory
    name: str
    team_count: int
    notes: Optional[str] = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, v):
        if not v or not v.strip():
            raise ValueError("name cannot be empty")
        return v.strip()

    @field_validator("team_count")
    @classmethod
    def validate_team_count(cls, v):
        if v < 2:
            raise ValueError("team_count must be >= 2")
        return v


class EventUpdate(BaseModel):
    category: Optional[EventCategory] = None
    name: Optional[str] = None
    team_count: Optional[int] = None
    notes: Optional[str] = None
    # Phase 2 fields
    draw_plan_json: Optional[str] = None
    draw_plan_version: Optional[str] = None
    draw_status: Optional[str] = None
    wf_block_minutes: Optional[int] = None
    standard_block_minutes: Optional[int] = None
    guarantee_selected: Optional[int] = None
    schedule_profile_json: Optional[str] = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, v):
        if v is not None and (not v or not v.strip()):
            raise ValueError("name cannot be empty")
        return v.strip() if v else v

    @field_validator("team_count")
    @classmethod
    def validate_team_count(cls, v):
        if v is not None and v < 2:
            raise ValueError("team_count must be >= 2")
        return v


class EventResponse(BaseModel):
    id: int
    tournament_id: int
    category: EventCategory
    name: str
    team_count: int
    notes: Optional[str] = None
    # Phase 2 fields
    draw_plan_json: Optional[str] = None
    draw_plan_version: Optional[str] = None
    draw_status: Optional[str] = None
    wf_block_minutes: Optional[int] = None
    standard_block_minutes: Optional[int] = None
    guarantee_selected: Optional[int] = None
    schedule_profile_json: Optional[str] = None

    class Config:
        from_attributes = True


@router.get("/tournaments/{tournament_id}/events", response_model=List[EventResponse])
def get_tournament_events(tournament_id: int, session: Session = Depends(get_session)):
    """Get all events for a tournament"""
    tournament = session.get(Tournament, tournament_id)
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")

    events = session.exec(select(Event).where(Event.tournament_id == tournament_id)).all()

    return events


@router.post("/tournaments/{tournament_id}/events", response_model=EventResponse, status_code=201)
def create_event(tournament_id: int, event_data: EventCreate, session: Session = Depends(get_session)):
    """Create a new event for a tournament"""
    tournament = session.get(Tournament, tournament_id)
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")

    # Check for duplicate
    existing = session.exec(
        select(Event).where(
            Event.tournament_id == tournament_id, Event.category == event_data.category, Event.name == event_data.name
        )
    ).first()

    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"Event with category '{event_data.category}' and name '{event_data.name}' already exists",
        )

    event = Event(tournament_id=tournament_id, **event_data.model_dump())
    session.add(event)
    session.commit()
    session.refresh(event)

    return event


@router.put("/events/{event_id}", response_model=EventResponse)
def update_event(event_id: int, event_data: EventUpdate, session: Session = Depends(get_session)):
    """Update an event"""
    event = session.get(Event, event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    update_data = event_data.model_dump(exclude_unset=True)

    # Check for duplicate if category or name is being changed
    if "category" in update_data or "name" in update_data:
        new_category = update_data.get("category", event.category)
        new_name = update_data.get("name", event.name)

        existing = session.exec(
            select(Event).where(
                Event.tournament_id == event.tournament_id,
                Event.category == new_category,
                Event.name == new_name,
                Event.id != event_id,
            )
        ).first()

        if existing:
            raise HTTPException(
                status_code=409, detail=f"Event with category '{new_category}' and name '{new_name}' already exists"
            )

    for field, value in update_data.items():
        setattr(event, field, value)

    session.add(event)
    session.commit()
    session.refresh(event)

    return event


@router.delete("/events/{event_id}", status_code=204)
def delete_event(event_id: int, session: Session = Depends(get_session)):
    """Delete an event"""
    event = session.get(Event, event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    session.delete(event)
    session.commit()

    return None
