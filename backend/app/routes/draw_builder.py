import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from app.database import get_session
from app.models.event import Event
from app.models.match import Match
from app.utils.match_generation import (
    generate_consolation_matches,
    generate_placement_matches,
    generate_standard_matches,
    generate_wf_matches,
)

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
    """
    Finalize draw plan - validates, generates matches, and sets status to final
    
    This creates match records based on the draw plan configuration:
    - WF matches (waterfall rounds)
    - Standard matches (main bracket or round robin)
    - Consolation matches (if applicable)
    - Placement matches (if guarantee == 5)
    """
    event = session.get(Event, event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    # Basic validation: even team count
    if event.team_count % 2 != 0:
        raise HTTPException(status_code=422, detail="Cannot finalize: team_count must be even")

    # Validate guarantee_selected is 4 or 5
    if request.guarantee_selected not in [4, 5]:
        raise HTTPException(status_code=422, detail="guarantee_selected must be 4 or 5")

    # Require draw_plan_json
    if not event.draw_plan_json:
        raise HTTPException(status_code=422, detail="Cannot finalize: draw_plan_json is required")

    # Parse draw plan to get template type and WF rounds
    try:
        draw_plan = json.loads(event.draw_plan_json)
        template_type = draw_plan.get("template_type")  # Snake case from frontend
        wf_rounds = draw_plan.get("wf_rounds", 0)  # Snake case from frontend
    except (json.JSONDecodeError, AttributeError) as e:
        raise HTTPException(status_code=422, detail=f"Invalid draw_plan_json: {str(e)}")

    if not template_type:
        raise HTTPException(status_code=422, detail="draw_plan_json must contain template_type")
    
    # Validate template_type matches team_count constraints
    if template_type == "WF_TO_POOLS_4" and event.team_count % 4 != 0:
        raise HTTPException(
            status_code=422,
            detail=f"WF_TO_POOLS_4 requires team_count divisible by 4, got {event.team_count}"
        )
    
    if template_type == "WF_TO_BRACKETS_8" and event.team_count not in [8, 12, 16, 32]:
        raise HTTPException(
            status_code=422,
            detail=f"WF_TO_BRACKETS_8 requires team_count in {{8,12,16,32}}, got {event.team_count}"
        )
    
    # Ensure draw_plan_json is persisted (full replace, not partial)
    # This ensures we don't have stale fields from old plans
    event.draw_plan_json = json.dumps(draw_plan)
    event.draw_plan_version = "1.0"

    # Delete any existing matches for this event (in case re-finalizing)
    existing_matches = session.exec(select(Match).where(Match.event_id == event_id)).all()
    for match in existing_matches:
        session.delete(match)
    session.flush()

    # Generate matches using the same utilities as Build Schedule
    # Note: We create matches without a schedule_version_id (will be assigned during Build Schedule)
    # But for compatibility with match generation functions, we use event_id as placeholder
    
    all_matches = []
    event_prefix = f"E{event.id}"
    
    # For now, create matches without version ID (Build Schedule will handle versioning)
    # Use 0 as placeholder version_id
    schedule_version_id = 0
    tournament_id = event.tournament_id

    # Generate WF matches if applicable
    if wf_rounds > 0:
        wf_matches = generate_wf_matches(
            event=event,
            schedule_version_id=schedule_version_id,
            tournament_id=tournament_id,
            wf_rounds=wf_rounds,
            duration_minutes=event.wf_block_minutes,
            event_prefix=event_prefix,
            session=session,
        )
        all_matches.extend(wf_matches)

    # Generate standard matches (MAIN bracket or RR)
    # Calculate count based on template type
    if template_type == "CANONICAL_32":  # 8-team bracket
        # MAIN bracket: 7 matches (4 QF + 2 SF + 1 F)
        standard_count = 7
    elif template_type == "RR_ONLY":
        # Round robin: n*(n-1)/2
        standard_count = (event.team_count * (event.team_count - 1)) // 2
    elif template_type == "WF_TO_POOLS_4":
        # Pools of 4: (team_count/4) pools * 6 matches per pool
        pools = event.team_count // 4
        standard_count = pools * 6
    else:
        # Default fallback
        standard_count = 7  # Assume bracket

    standard_matches = generate_standard_matches(
        event=event,
        schedule_version_id=schedule_version_id,
        tournament_id=tournament_id,
        count=standard_count,
        duration_minutes=event.standard_block_minutes,
        event_prefix=event_prefix,
        template_type=template_type,
    )
    all_matches.extend(standard_matches)

    # Generate consolation matches for bracket templates
    if template_type in ["CANONICAL_32"]:  # Bracket templates
        consolation_matches = generate_consolation_matches(
            event=event,
            schedule_version_id=schedule_version_id,
            tournament_id=tournament_id,
            duration_minutes=event.standard_block_minutes,
            event_prefix=event_prefix,
            guarantee=request.guarantee_selected,
        )
        all_matches.extend(consolation_matches)

        # Generate placement matches if guarantee == 5
        if request.guarantee_selected == 5:
            placement_matches = generate_placement_matches(
                event=event,
                schedule_version_id=schedule_version_id,
                tournament_id=tournament_id,
                duration_minutes=event.standard_block_minutes,
                event_prefix=event_prefix,
            )
            all_matches.extend(placement_matches)

    # Save all matches
    for match in all_matches:
        session.add(match)

    # Update event status
    event.guarantee_selected = request.guarantee_selected
    event.draw_status = "final"
    session.add(event)
    
    # Commit everything
    session.commit()
    session.refresh(event)

    return {
        "id": event.id,
        "draw_status": event.draw_status,
        "guarantee_selected": event.guarantee_selected,
        "matches_created": len(all_matches),
    }
