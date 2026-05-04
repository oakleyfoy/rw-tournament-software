"""
Schedule Builder — read-only authoritative match inventory.

Uses Draw Plan Engine for all calculations. No local template math.
"""

import logging
import json
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select

from app.database import get_session
from app.models.event import Event
from app.models.schedule_slot import ScheduleSlot
from app.models.schedule_version import ScheduleVersion
from app.models.tournament import Tournament
from app.services.draw_plan_engine import (
    build_spec_from_event,
    compute_inventory,
    resolve_event_family,
)

logger = logging.getLogger(__name__)

router = APIRouter()


def _resolve_schedule_version_for_calendar(session: Session, tournament: Tournament) -> Optional[ScheduleVersion]:
    """Match schedule policy: prefer published pointer, then latest FINAL, then latest version."""
    if tournament.public_schedule_version_id:
        v = session.get(ScheduleVersion, tournament.public_schedule_version_id)
        if v and v.tournament_id == tournament.id:
            return v

    latest_final = session.exec(
        select(ScheduleVersion)
        .where(
            ScheduleVersion.tournament_id == tournament.id,
            ScheduleVersion.status == "final",
        )
        .order_by(ScheduleVersion.version_number.desc(), ScheduleVersion.id.desc())
    ).first()
    if latest_final:
        return latest_final

    return session.exec(
        select(ScheduleVersion)
        .where(ScheduleVersion.tournament_id == tournament.id)
        .order_by(ScheduleVersion.version_number.desc(), ScheduleVersion.id.desc())
    ).first()


def _calendar_days_for_version(session: Session, version_id: int) -> List[str]:
    slots = session.exec(select(ScheduleSlot).where(ScheduleSlot.schedule_version_id == version_id)).all()
    days = sorted({s.day_date for s in slots})
    return [d.isoformat() for d in days]


def _policy_calendar_payload(
    session: Session, tournament: Tournament, schedule_version_id: Optional[int] = None
) -> Tuple[List[str], Optional[int]]:
    """
    Sorted ISO dates that define schedule-policy day_index (same as build_daily_plan).
    """
    if schedule_version_id is not None:
        v = session.get(ScheduleVersion, schedule_version_id)
        if not v or v.tournament_id != tournament.id:
            raise HTTPException(status_code=404, detail="Schedule version not found")
        return _calendar_days_for_version(session, v.id), v.id

    v = _resolve_schedule_version_for_calendar(session, tournament)
    if not v or v.id is None:
        return [], None
    return _calendar_days_for_version(session, v.id), v.id


def _get_manual_schedule_order(event: Event) -> int | None:
    raw = event.schedule_profile_json
    if not raw:
        return None
    try:
        profile = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(profile, dict):
        return None
    value = profile.get("schedule_order")
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value > 0:
        return value
    return None


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
        "schedule_order": _get_manual_schedule_order(event),
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
def get_schedule_builder(
    tournament_id: int,
    schedule_version_id: Optional[int] = Query(
        None,
        description="Use this schedule version's slot dates for policy day indices (defaults from published/final/latest).",
    ),
    session: Session = Depends(get_session),
):
    """
    Read-only authoritative match inventory for the scheduler.
    Shows ALL events; includes status=finalized/draft so UI can highlight.
    All inventory calculations delegated to draw_plan_engine.

    policy_calendar_days matches build_daily_plan day_index ordering for that version.
    """
    tournament = session.get(Tournament, tournament_id)
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")

    policy_calendar_days, policy_calendar_version_id = _policy_calendar_payload(
        session, tournament, schedule_version_id
    )
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
        "policy_calendar_days": policy_calendar_days,
        "policy_calendar_version_id": policy_calendar_version_id,
    }
