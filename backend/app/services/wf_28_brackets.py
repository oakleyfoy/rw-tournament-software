"""28-team waterfall into three brackets and a 4-team round robin.

Two waterfall rounds, then rank the field 1-28 by wins and tiebreakers.
Seeds 1-8, 9-16, and 17-24 fill the three 8-team brackets.
Seeds 25-28 play the Division 4 round robin.
"""

from __future__ import annotations

import json
from typing import Optional

from sqlmodel import Session, select

from app.models.event import Event
from app.models.match import Match
from app.services.wf_24_brackets import _rank_teams

WFSEED_PREFIX = "WFSEED:"
SEED_PREFIX = "SEED_"


def event_uses_wf28_brackets(event: Optional[Event]) -> bool:
    if not event or (event.team_count or 0) != 28:
        return False
    raw = event.draw_plan_json
    if not raw:
        return False
    try:
        plan = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return False
    template = str(plan.get("template_type") or "").upper()
    return template == "WF_28_BRACKETS_RR"


def maybe_place_wf28_brackets(session: Session, match: Match) -> int:
    """Fill bracket quarterfinals and Division 4 once every waterfall match is final."""
    if (match.match_type or "").upper() != "WF":
        return 0
    event = session.get(Event, match.event_id)
    if not event_uses_wf28_brackets(event):
        return 0
    return place_wf28_brackets(session, match.tournament_id, match.schedule_version_id, match.event_id)


def place_wf28_brackets(session: Session, tournament_id: int, version_id: int, event_id: int) -> int:
    wf_matches = session.exec(
        select(Match).where(
            Match.tournament_id == tournament_id,
            Match.schedule_version_id == version_id,
            Match.event_id == event_id,
            Match.match_type == "WF",
        )
    ).all()
    if not wf_matches:
        return 0
    if any((m.runtime_status or "").upper() != "FINAL" or m.winner_team_id is None for m in wf_matches):
        return 0

    ranked = _rank_teams(session, version_id, event_id, wf_matches)
    if len(ranked) != 28:
        return 0
    seed_to_team = {seed: team_id for seed, team_id in enumerate(ranked, start=1)}

    targets = session.exec(
        select(Match).where(
            Match.tournament_id == tournament_id,
            Match.schedule_version_id == version_id,
            Match.event_id == event_id,
            Match.match_type.in_(("MAIN", "RR")),
        )
    ).all()

    updated = 0
    for target in targets:
        if (target.match_type or "").upper() == "MAIN" and target.round_index != 1:
            continue
        changed = False
        for side in ("a", "b"):
            if _assign_seed_side(target, side, seed_to_team):
                changed = True
        if changed:
            session.add(target)
            updated += 1
    if updated:
        session.commit()
    return updated


def _assign_seed_side(match: Match, side: str, seed_to_team: dict[int, int]) -> bool:
    placeholder = getattr(match, f"placeholder_side_{side}") or ""
    seed = _seed_from_placeholder(placeholder)
    if seed is None:
        return False
    team_id = seed_to_team.get(seed)
    if team_id is None:
        return False
    field = f"team_{side}_id"
    if getattr(match, field) != team_id:
        setattr(match, field, team_id)
        return True
    return False


def _seed_from_placeholder(placeholder: str) -> Optional[int]:
    if placeholder.startswith(WFSEED_PREFIX):
        raw = placeholder[len(WFSEED_PREFIX) :]
    elif placeholder.startswith(SEED_PREFIX):
        raw = placeholder[len(SEED_PREFIX) :]
    else:
        return None
    try:
        return int(raw)
    except ValueError:
        return None
