"""Derive Tournament Event rows from an approved RW-OS draw structure.

Approval remains plan-first. This module only creates or safely updates Event
records for the same tournament. It never deletes events, never writes another
tournament's events, and never mutates events that already have draws or matches
when the new structure would change their team allocation.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Optional

from sqlmodel import Session, select

from app.models.event import Event, EventCategory
from app.models.match import Match
from app.models.match_assignment import MatchAssignment
from app.models.tournament_import import TournamentDrawPlan

STRUCTURE_NOTES_PREFIX = "Approved structure:"


@dataclass
class StructureEventSyncResult:
    created: list[Event] = field(default_factory=list)
    updated: list[Event] = field(default_factory=list)
    unchanged: list[Event] = field(default_factory=list)
    preserved: list[Event] = field(default_factory=list)
    conflicts: list[dict[str, Any]] = field(default_factory=list)
    events: list[Event] = field(default_factory=list)


def event_category_for_draw_kind(draw_kind: str) -> Optional[EventCategory]:
    if draw_kind == EventCategory.womens.value:
        return EventCategory.womens
    if draw_kind == EventCategory.mixed.value:
        return EventCategory.mixed
    return None


def structure_event_notes(bracket: dict[str, Any]) -> str:
    label = str(bracket.get("label") or "").strip()
    parts = [f"{STRUCTURE_NOTES_PREFIX} {label}".rstrip()]
    start = bracket.get("rankStart")
    end = bracket.get("rankEnd")
    size = bracket.get("size")
    if start is not None and end is not None:
        parts.append(f"ranks {start}–{end}")
    if size is not None:
        parts.append(f"{size} teams")
    return " · ".join(parts)


def serialize_structure_event(event: Event, **extra: Any) -> dict[str, Any]:
    category = event.category.value if isinstance(event.category, EventCategory) else str(event.category)
    payload = {
        "id": event.id,
        "tournamentId": event.tournament_id,
        "category": category,
        "name": event.name,
        "teamCount": event.team_count,
        "notes": event.notes,
    }
    payload.update(extra)
    return payload


def _canonical_name(bracket: dict[str, Any]) -> str:
    return str(bracket.get("label") or "").strip()


def _bracket_team_count(bracket: dict[str, Any]) -> Optional[int]:
    raw = bracket.get("size")
    if raw is None:
        return None
    try:
        size = int(raw)
    except (TypeError, ValueError):
        return None
    if size < 2:
        return None
    return size


def _brackets_from_plan(plan: TournamentDrawPlan) -> list[dict[str, Any]]:
    parsed = json.loads(plan.brackets_json or "[]")
    if not isinstance(parsed, list):
        return []
    return [item for item in parsed if isinstance(item, dict)]


def requested_event_sizes(plans: list[TournamentDrawPlan], tournament_id: int) -> dict[tuple[str, str], int]:
    requested: dict[tuple[str, str], int] = {}
    for plan in plans:
        if plan.tournament_id != tournament_id:
            continue
        category = event_category_for_draw_kind(plan.draw_kind)
        if category is None:
            continue
        for bracket in _brackets_from_plan(plan):
            name = _canonical_name(bracket)
            size = _bracket_team_count(bracket)
            if name and size is not None:
                requested[(category.value, name)] = size
    return requested


def _event_key(category: EventCategory, name: str) -> tuple[str, str]:
    return (category.value, name)


def _existing_key(event: Event) -> tuple[str, str]:
    category = event.category.value if isinstance(event.category, EventCategory) else str(event.category)
    return (category, event.name)


def _notes_are_structure_generated(notes: Optional[str]) -> bool:
    text = (notes or "").strip()
    return not text or text.startswith(STRUCTURE_NOTES_PREFIX)


# Saving a Draw Builder template writes draw_plan_json and sets "draft" without any
# roster or matches. Only finalize produces a live draw, so a draft is still rebuildable
# and must not block an approved structure change.
REBUILDABLE_DRAW_STATUSES = {"not_started", "draft"}


def _owned_event_matches(session: Session, event: Event) -> list[Match]:
    """Match rows that belong to this Event and this Tournament only."""
    if event.id is None or event.tournament_id is None:
        return []
    return list(
        session.exec(
            select(Match).where(
                Match.event_id == event.id,
                Match.tournament_id == event.tournament_id,
            )
        ).all()
    )


def _match_has_generated_draw_activity(session: Session, match: Match) -> bool:
    """True for a real generated/live match, not an empty unscheduled scaffold row."""
    if match.team_a_id or match.team_b_id or match.winner_team_id:
        return True
    if (match.status or "unscheduled").strip() != "unscheduled":
        return True
    if (match.runtime_status or "SCHEDULED").strip() != "SCHEDULED":
        return True
    if match.started_at or match.completed_at or match.score_json:
        return True
    if match.id is None:
        return False
    assignment = session.exec(select(MatchAssignment.id).where(MatchAssignment.match_id == match.id)).first()
    return assignment is not None


def event_protection_reason(session: Session, event: Event) -> Optional[str]:
    status = (event.draw_status or "not_started").strip()
    if status not in REBUILDABLE_DRAW_STATUSES:
        return "event has generated draw"
    if any(_match_has_generated_draw_activity(session, match) for match in _owned_event_matches(session, event)):
        return "event already has matches"
    return None


def sync_events_from_approved_plans(
    session: Session,
    tournament_id: int,
    plans: list[TournamentDrawPlan],
) -> StructureEventSyncResult:
    existing = list(session.exec(select(Event).where(Event.tournament_id == tournament_id)).all())
    by_key = {_existing_key(event): event for event in existing}
    intended_keys: set[tuple[str, str]] = set()
    result = StructureEventSyncResult()

    for plan in plans:
        if plan.tournament_id != tournament_id:
            continue
        category = event_category_for_draw_kind(plan.draw_kind)
        if category is None:
            continue
        for bracket in _brackets_from_plan(plan):
            name = _canonical_name(bracket)
            team_count = _bracket_team_count(bracket)
            if not name or team_count is None:
                continue
            key = _event_key(category, name)
            intended_keys.add(key)
            event = by_key.get(key)
            if event is None:
                event = Event(
                    tournament_id=tournament_id,
                    category=category,
                    name=name,
                    team_count=team_count,
                    notes=structure_event_notes(bracket),
                )
                session.add(event)
                session.flush()
                by_key[key] = event
                result.created.append(event)
                continue

            reason = event_protection_reason(session, event)
            if reason and event.team_count != team_count:
                result.conflicts.append(
                    {
                        "eventId": event.id,
                        "category": category.value,
                        "name": name,
                        "reason": reason,
                        "currentTeamCount": event.team_count,
                        "requestedTeamCount": team_count,
                    }
                )
                result.unchanged.append(event)
                continue

            changed = False
            if not reason and event.team_count != team_count:
                event.team_count = team_count
                changed = True
            if not reason and _notes_are_structure_generated(event.notes):
                notes = structure_event_notes(bracket)
                if event.notes != notes:
                    event.notes = notes
                    changed = True
            if changed:
                session.add(event)
                result.updated.append(event)
            else:
                result.unchanged.append(event)

    session.commit()
    result.events = list(session.exec(select(Event).where(Event.tournament_id == tournament_id)).all())
    result.preserved = [event for event in result.events if _existing_key(event) not in intended_keys]
    return result
