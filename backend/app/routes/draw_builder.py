import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from app.database import get_session
from app.models.event import Event
from app.models.match import Match
from app.models.match_assignment import MatchAssignment
from app.models.match_checkin import MatchCheckIn
from app.models.match_lock import MatchLock
from app.models.match_player_checkin import MatchPlayerCheckIn
from app.models.schedule_version import ScheduleVersion
from app.models.start_over_baseline_assignment import StartOverBaselineAssignment
from app.models.team import Team
from app.utils.match_generation import (
    generate_consolation_matches,
    generate_placement_matches,
    generate_standard_matches,
    generate_wf_matches,
)

router = APIRouter()


def _purge_matches_for_event_draw_rebuild(session: Session, event_id: int) -> None:
    """
    Delete all matches for an event and rows that FK-match them.

    Re-finalizing a draw replaces generated matches; assignments and desk rows
    must be removed first or the DB raises integrity errors (PostgreSQL) or
    leaves orphans (SQLite without FK checks).
    """
    matches = list(session.exec(select(Match).where(Match.event_id == event_id)).all())
    ids = [m.id for m in matches if m.id is not None]
    if not ids:
        return

    for m in matches:
        if m.source_match_a_id is not None or m.source_match_b_id is not None:
            m.source_match_a_id = None
            m.source_match_b_id = None
            session.add(m)
    session.flush()

    for row in session.exec(select(MatchAssignment).where(MatchAssignment.match_id.in_(ids))).all():  # type: ignore[arg-type]
        session.delete(row)
    for row in session.exec(select(MatchLock).where(MatchLock.match_id.in_(ids))).all():  # type: ignore[arg-type]
        session.delete(row)
    for row in session.exec(select(MatchPlayerCheckIn).where(MatchPlayerCheckIn.match_id.in_(ids))).all():  # type: ignore[arg-type]
        session.delete(row)
    for row in session.exec(select(MatchCheckIn).where(MatchCheckIn.match_id.in_(ids))).all():  # type: ignore[arg-type]
        session.delete(row)
    for row in session.exec(
        select(StartOverBaselineAssignment).where(StartOverBaselineAssignment.match_id.in_(ids))  # type: ignore[arg-type]
    ).all():
        session.delete(row)
    session.flush()

    for m in matches:
        session.delete(m)
    session.flush()


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


class ReopenDraftResponse(BaseModel):
    id: int
    draw_status: str
    matches_cleared: int


@router.post("/events/{event_id}/draw-plan/reopen", response_model=ReopenDraftResponse)
def reopen_draw_plan(event_id: int, session: Session = Depends(get_session)):
    """Reopen a finalized draw as a draft, clearing its generated matches.

    Unlike a plain status flip, this also purges the event's matches (and their
    assignment/check-in/lock rows). That releases teams that were locked into a
    finalized schedule version / FINAL matches so the roster can be re-imported,
    after which the draw can be re-finalized to regenerate matches.
    """
    event = session.get(Event, event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    matches_before = len(session.exec(select(Match).where(Match.event_id == event_id)).all())
    _purge_matches_for_event_draw_rebuild(session, event_id)

    event.draw_status = "draft"
    event.guarantee_selected = None
    session.add(event)
    session.commit()
    session.refresh(event)

    return ReopenDraftResponse(
        id=event.id,
        draw_status=event.draw_status or "draft",
        matches_cleared=matches_before,
    )


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
    except (json.JSONDecodeError, AttributeError) as e:
        raise HTTPException(status_code=422, detail=f"Invalid draw_plan_json: {str(e)}")

    from app.services.draw_plan_engine import (
        build_spec_from_event,
        compute_inventory,
        generate_matches_for_event,
        normalize_draw_plan_for_team_count,
        normalize_template_key,
    )
    from app.services.draw_plan_rules import validate_template_config

    draw_plan = normalize_draw_plan_for_team_count(event.team_count or 0, draw_plan)
    template_type = draw_plan.get("template_type")  # Snake case from frontend
    wf_rounds = draw_plan.get("wf_rounds", 0)  # Snake case from frontend

    if not template_type:
        raise HTTPException(status_code=422, detail="draw_plan_json must contain template_type")

    template_key = normalize_template_key(template_type)
    config_err = validate_template_config(template_key, event.team_count, wf_rounds)
    if config_err:
        raise HTTPException(status_code=422, detail=config_err)

    # Validate template_type matches team_count constraints
    if template_type == "WF_TO_POOLS_4" and event.team_count % 4 != 0:
        raise HTTPException(
            status_code=422, detail=f"WF_TO_POOLS_4 requires team_count divisible by 4, got {event.team_count}"
        )

    if template_type == "WF_TO_BRACKETS_8" and event.team_count not in [8, 12, 16, 32]:
        raise HTTPException(
            status_code=422, detail=f"WF_TO_BRACKETS_8 requires team_count in {{8,12,16,32}}, got {event.team_count}"
        )

    # Ensure draw_plan_json is persisted (full replace, not partial)
    # This ensures we don't have stale fields from old plans
    event.draw_plan_json = json.dumps(draw_plan)
    event.draw_plan_version = "1.0"

    timing = draw_plan.get("timing") if isinstance(draw_plan.get("timing"), dict) else {}
    wf_block_minutes = timing.get("wf_block_minutes")
    if not isinstance(wf_block_minutes, int) or wf_block_minutes <= 0:
        wf_block_minutes = event.wf_block_minutes or 60
    standard_block_minutes = timing.get("standard_block_minutes")
    if not isinstance(standard_block_minutes, int) or standard_block_minutes <= 0:
        standard_block_minutes = event.standard_block_minutes or 120

    # Keep legacy event columns aligned with the persisted draw_plan timing.
    event.wf_block_minutes = wf_block_minutes
    event.standard_block_minutes = standard_block_minutes

    # Replace any existing generated matches (re-finalize after schedule/check-in).
    _purge_matches_for_event_draw_rebuild(session, event_id)

    # Match rows require a real schedule_version FK (DB-enforced). Prefer the tournament's
    # latest version if one exists (e.g. desk draft); otherwise create draft v1.
    tournament_id = event.tournament_id
    sv = session.exec(
        select(ScheduleVersion)
        .where(ScheduleVersion.tournament_id == tournament_id)
        .order_by(ScheduleVersion.version_number.desc())
    ).first()
    if not sv:
        sv = ScheduleVersion(tournament_id=tournament_id, version_number=1, status="draft")
        session.add(sv)
        session.flush()
    schedule_version_id = sv.id

    all_matches = []

    if template_key == "WF_14_TOP2_BYE":
        spec = build_spec_from_event(event, draw_plan)
        inventory = compute_inventory(spec)
        if inventory.has_errors():
            raise HTTPException(status_code=422, detail="; ".join(inventory.errors))
        linked_team_ids = [
            t.id for t in session.exec(select(Team).where(Team.event_id == event.id).order_by(Team.seed, Team.id)).all()
        ]
        existing_codes: set[str] = set(
            session.exec(select(Match.match_code).where(Match.schedule_version_id == schedule_version_id)).all()
        )
        session._allow_match_generation = True
        try:
            to_add, _warnings = generate_matches_for_event(
                session, schedule_version_id, spec, linked_team_ids, existing_codes
            )
        finally:
            session._allow_match_generation = False
        for match in to_add:
            session.add(match)
        all_matches.extend(to_add)
        event.draw_plan_json = json.dumps(draw_plan)
        event.draw_plan_version = "1.0"
        event.wf_block_minutes = wf_block_minutes
        event.standard_block_minutes = standard_block_minutes
        event.guarantee_selected = request.guarantee_selected
        event.draw_status = "final"
        session.add(event)
        session.commit()
        session.refresh(event)
        return {
            "id": event.id,
            "draw_status": event.draw_status,
            "guarantee_selected": event.guarantee_selected,
            "matches_created": len(all_matches),
        }

    event_prefix = f"E{event.id}"

    # Generate WF matches if applicable
    if wf_rounds > 0:
        wf_matches = generate_wf_matches(
            event=event,
            schedule_version_id=schedule_version_id,
            tournament_id=tournament_id,
            wf_rounds=wf_rounds,
            duration_minutes=wf_block_minutes,
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
        duration_minutes=standard_block_minutes,
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
            duration_minutes=standard_block_minutes,
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
                duration_minutes=standard_block_minutes,
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
