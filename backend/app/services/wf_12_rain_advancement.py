"""Fill 12-team rain finals from group standings. Friendlies do not count."""

from __future__ import annotations

import json
from functools import cmp_to_key
from typing import Dict, List, Optional, Sequence

from sqlmodel import Session, select

from app.models.event import Event
from app.models.match import Match
from app.models.team import Team
from app.services.score_parser import parse_score
from app.services.wf_12_rain_format import FLIGHTS, TEMPLATE_KEY, flight_pool_letters


def _event_template(event: Event) -> Optional[str]:
    if not event.draw_plan_json:
        return None
    try:
        plan = json.loads(event.draw_plan_json)
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(plan, dict):
        return None
    raw = plan.get("template_type") or plan.get("templateType")
    if not raw:
        return None
    return str(raw).strip().upper().replace(" ", "_")


def is_rain_event(event: Event) -> bool:
    return _event_template(event) == TEMPLATE_KEY


def event_uses_wf12_rain(session: Session, event_id: int, schedule_version_id: Optional[int] = None) -> bool:
    event = session.get(Event, event_id)
    return bool(event and is_rain_event(event))


def order_pool_teams(
    team_ids: Sequence[int],
    matches: Sequence[Match],
    seeds: Dict[int, int],
) -> List[int]:
    """Rank a group. Head-to-head splits a two-team tie; a three-way tie uses game difference, then seed."""
    ids = list(team_ids)
    stats = {tid: {"w": 0, "gd": 0} for tid in ids}
    allowed = set(ids)
    h2h: Dict[tuple, int] = {}

    for match in matches:
        if (match.runtime_status or "") != "FINAL" or match.winner_team_id is None:
            continue
        if match.team_a_id not in allowed or match.team_b_id not in allowed:
            continue
        winner = match.winner_team_id
        stats[winner]["w"] += 1
        parsed = parse_score(match.score_json)
        if parsed:
            a_games, b_games = parsed.team_a_games, parsed.team_b_games
            if winner == match.team_a_id:
                stats[match.team_a_id]["gd"] += a_games - b_games
                stats[match.team_b_id]["gd"] += b_games - a_games
            else:
                stats[match.team_b_id]["gd"] += b_games - a_games
                stats[match.team_a_id]["gd"] += a_games - b_games
        pair = (min(match.team_a_id, match.team_b_id), max(match.team_a_id, match.team_b_id))
        h2h[pair] = winner

    def cmp(left: int, right: int) -> int:
        if stats[left]["w"] != stats[right]["w"]:
            return stats[right]["w"] - stats[left]["w"]
        tied = [tid for tid in ids if stats[tid]["w"] == stats[left]["w"]]
        if len(tied) == 2 and right in tied:
            winner = h2h.get((min(left, right), max(left, right)))
            if winner == left:
                return -1
            if winner == right:
                return 1
        if stats[left]["gd"] != stats[right]["gd"]:
            return stats[right]["gd"] - stats[left]["gd"]
        seed_left = seeds.get(left, 9999)
        seed_right = seeds.get(right, 9999)
        if seed_left != seed_right:
            return seed_left - seed_right
        return left - right

    return sorted(ids, key=cmp_to_key(cmp))


def _team_label(session: Session, team_id: int) -> str:
    team = session.get(Team, team_id)
    if not team:
        return f"Team {team_id}"
    return team.display_name or team.name or f"Team {team_id}"


def _group_matches(matches: Sequence[Match], flight: str) -> List[Match]:
    needle = f"_{flight}_"
    grouped: List[Match] = []
    for match in matches:
        code = (match.match_code or "").upper()
        if match.match_type != "RR" or needle not in code or "_FUN_" in code:
            continue
        if any(tag in code for tag in ("_FRI_", "_SAT1_", "_SAT2_")):
            grouped.append(match)
    return grouped


def _teams_for_letter(matches: Sequence[Match], letter: str) -> List[int]:
    found: List[int] = []
    seen = set()
    suffix = f"_{letter}"
    for match in matches:
        code = (match.match_code or "").upper()
        tail = code.split("_")[-1]
        if not tail.startswith(letter) or suffix not in f"_{tail}":
            continue
        for team_id in (match.team_a_id, match.team_b_id):
            if team_id is not None and team_id not in seen:
                seen.add(team_id)
                found.append(team_id)
    return found


def refresh_wf12_rain_placement(
    session: Session,
    tournament_id: int,
    event_id: int,
    schedule_version_id: int,
) -> int:
    if not event_uses_wf12_rain(session, event_id, schedule_version_id):
        return 0

    event_matches = session.exec(
        select(Match).where(
            Match.tournament_id == tournament_id,
            Match.event_id == event_id,
            Match.schedule_version_id == schedule_version_id,
        )
    ).all()

    updated = 0
    for flight in FLIGHTS:
        group = _group_matches(event_matches, flight)
        if len(group) != 6:
            continue
        if not all((match.runtime_status or "") == "FINAL" and match.winner_team_id for match in group):
            continue

        high_letter, low_letter = flight_pool_letters(flight)
        high_ids = _teams_for_letter(group, high_letter)
        low_ids = _teams_for_letter(group, low_letter)
        if len(high_ids) != 3 or len(low_ids) != 3:
            continue

        seeds: Dict[int, int] = {}
        for team_id in high_ids + low_ids:
            team = session.get(Team, team_id)
            seeds[team_id] = team.seed if team and team.seed is not None else 9999

        high_order = order_pool_teams(high_ids, group, seeds)
        low_order = order_pool_teams(low_ids, group, seeds)
        slot_to_team = {f"{high_letter}{index}": team_id for index, team_id in enumerate(high_order, start=1)}
        slot_to_team.update({f"{low_letter}{index}": team_id for index, team_id in enumerate(low_order, start=1)})

        sun_tag = f"_{flight}_SUN_"
        for match in event_matches:
            if match.match_type != "PLACEMENT" or sun_tag not in (match.match_code or "").upper():
                continue
            if (match.runtime_status or "") in ("FINAL", "IN_PROGRESS"):
                continue
            team_a = slot_to_team.get((match.placeholder_side_a or "").strip())
            team_b = slot_to_team.get((match.placeholder_side_b or "").strip())
            if team_a is None or team_b is None:
                continue
            changed = False
            if match.team_a_id != team_a:
                match.team_a_id = team_a
                changed = True
            if match.team_b_id != team_b:
                match.team_b_id = team_b
                changed = True
            if changed:
                session.add(match)
                updated += 1

    if updated:
        session.commit()
    return updated
