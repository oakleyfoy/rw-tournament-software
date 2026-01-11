from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session

from app.database import get_session
from app.models.event import Event

router = APIRouter()


class DrawPlanUpdate(BaseModel):
    draw_plan_json: Optional[str] = None
    schedule_profile_json: Optional[str] = None
    wf_block_minutes: Optional[int] = None
    standard_block_minutes: Optional[int] = None


@router.get("/events/{event_id}/draw-plan")
def get_draw_plan(event_id: int, session: Session = Depends(get_session)):
    """Get draw plan data for an event"""
    event = session.get(Event, event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    return {
        "id": event.id,
        "draw_plan_json": event.draw_plan_json,
        "draw_plan_version": event.draw_plan_version,
        "draw_status": event.draw_status,
        "wf_block_minutes": event.wf_block_minutes,
        "standard_block_minutes": event.standard_block_minutes,
        "guarantee_selected": event.guarantee_selected,
        "schedule_profile_json": event.schedule_profile_json,
    }


@router.put("/events/{event_id}/draw-plan")
def update_draw_plan(event_id: int, plan_data: DrawPlanUpdate, session: Session = Depends(get_session)):
    """Update draw plan (draft)"""
    event = session.get(Event, event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    update_data = plan_data.model_dump(exclude_unset=True)

    # Set draw_status to draft if updating plan
    if update_data:
        event.draw_status = "draft"
        event.draw_plan_version = "1.0"

    for field, value in update_data.items():
        setattr(event, field, value)

    session.add(event)
    session.commit()
    session.refresh(event)

    return {
        "id": event.id,
        "draw_status": event.draw_status,
        "draw_plan_json": event.draw_plan_json,
        "schedule_profile_json": event.schedule_profile_json,
        "wf_block_minutes": event.wf_block_minutes,
        "standard_block_minutes": event.standard_block_minutes,
    }


class FinalizeRequest(BaseModel):
    guarantee_selected: int


@router.post("/events/{event_id}/draw-plan/finalize")
def finalize_draw_plan(event_id: int, request: FinalizeRequest, session: Session = Depends(get_session)):
    """Finalize draw plan - validates and sets guarantee"""
    event = session.get(Event, event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    # Basic validation: even team count
    if event.team_count % 2 != 0:
        raise HTTPException(status_code=422, detail="Cannot finalize: team_count must be even")

    # Validate guarantee_selected is 4 or 5
    if request.guarantee_selected not in [4, 5]:
        raise HTTPException(status_code=422, detail="guarantee_selected must be 4 or 5")

    # If draw_plan_json exists, finalize
    if event.draw_plan_json:
        event.guarantee_selected = request.guarantee_selected
        event.draw_status = "final"
        session.add(event)
        session.commit()
        session.refresh(event)

        return {
            "id": event.id,
            "draw_status": event.draw_status,
            "guarantee_selected": event.guarantee_selected,
        }
    else:
        raise HTTPException(status_code=422, detail="Cannot finalize: draw_plan_json is required")
