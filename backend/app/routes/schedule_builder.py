"""
Schedule Builder — read-only authoritative match inventory.

Uses Draw Plan Engine for all calculations. No local template math.
"""

import logging
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.database import get_session
from app.models.event import Event
from app.services.draw_plan_engine import (
    build_spec_from_event,
    compute_inventory,
    resolve_event_family,
)

logger = logging.getLogger(__name__)

router = APIRouter()


def _build_event_payload(event: Event) -> Dict[str, Any]:
    """
    Build schedule builder response for a single event.
    All inventory math delegated to draw_plan_engine.
    """
    # Build spec from event
    spec = build_spec_from_event(event)

    # Compute inventory via engine
    inventory = compute_inventory(spec)

    # Build response payload
    payload: Dict[str, Any] = {
        "event_id": event.id,
        "event_name": event.name,
        "division": spec.division,
        "team_count": spec.team_count,
        "template_type": spec.template_type,
        "template_key": spec.template_key,
        "family": resolve_event_family(spec),
        "guarantee": spec.guarantee,
        "waterfall_rounds": spec.waterfall_rounds,
        "wf_matches": inventory.wf_matches,
        "bracket_matches": inventory.bracket_matches,
        "round_robin_matches": inventory.rr_matches,
        "match_lengths": {
            "waterfall": spec.waterfall_minutes,
            "standard": spec.standard_minutes,
        },
        "total_matches": inventory.total_matches,
        "counts_by_stage": inventory.counts_by_stage,
    }

    # Include errors if any
    if inventory.has_errors():
        payload["error"] = "; ".join(inventory.errors)

    return payload


@router.get("/tournaments/{tournament_id}/schedule-builder")
def get_schedule_builder(tournament_id: int, session: Session = Depends(get_session)):
    """
    Read-only authoritative match inventory for the scheduler.
    Shows ALL events; includes status=finalized/draft so UI can highlight.
    All inventory calculations delegated to draw_plan_engine.
    """
    from app.models.tournament import Tournament

    tournament = session.get(Tournament, tournament_id)
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")

    # Query ALL events (not just finalized)
    all_events = session.exec(
        select(Event).where(Event.tournament_id == tournament_id).order_by(Event.id)
    ).all()

    finalized_events = [e for e in all_events if e.draw_status == "final"]

    logger.info(
        "SCHEDULE_BUILDER: tournament_id=%s events_total=%s events_finalized=%s",
        tournament_id,
        len(all_events),
        len(finalized_events),
    )

    event_payloads = []
    for e in all_events:
        payload = _build_event_payload(e)
        payload["status"] = e.draw_status or "draft"
        payload["is_finalized"] = e.draw_status == "final"

        # Add warning if not finalized (only if no other error)
        if e.draw_status != "final" and "error" not in payload:
            payload["warning"] = "Event not finalized"

        event_payloads.append(payload)

    return {
        "tournament_id": tournament_id,
        "events": event_payloads,
    }
