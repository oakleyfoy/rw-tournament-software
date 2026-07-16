"""
WF_14_TOP2_BYE consolation flight: rank R1 losers by seed, fill MAIN + Sunday placement.
"""

from __future__ import annotations

import json
from typing import Dict, List, Optional, Tuple

from sqlmodel import Session, select

from app.models.event import Event
from app.models.match import Match
from app.models.team import Team
from app.services.wf_14_format import POOL_C_RANKS, POOL_D_RANKS


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


def is_wf14_event(event: Event) -> bool:
    return _event_template(event) == "WF_14_TOP2_BYE"


def event_uses_wf14(
    session: Session,
    event_id: int,
    schedule_version_id: Optional[int] = None,
) -> bool:
    """
    Robust WF_14 detection.

    Prefers the draw-plan template, but also recognizes an event by its
    generated WF_14 signature matches (the Sunday cross-placement carries
    ``placement_type == "WF14_CONS_CROSS"``). This keeps loser-flight behavior
    working for duplicated/older events whose ``draw_plan_json`` template string
    no longer says ``WF_14_TOP2_BYE`` even though the matches are WF_14.
    """
    event = session.get(Event, event_id)
    if event and is_wf14_event(event):
        return True
    q = select(Match).where(
        Match.event_id == event_id,
        Match.placement_type == "WF14_CONS_CROSS",
    )
    if schedule_version_id is not None:
        q = q.where(Match.schedule_version_id == schedule_version_id)
    return session.exec(q).first() is not None


def _team_label(session: Session, team_id: Optional[int]) -> str:
    if team_id is None:
        return "TBD"
    t = session.get(Team, team_id)
    if not t:
        return "TBD"
    return t.name or getattr(t, "display_name", None) or f"Team {t.id}"


def _loser_id_from_final(match: Match) -> Optional[int]:
    if (match.runtime_status or "") != "FINAL" or match.winner_team_id is None:
        return None
    if match.team_a_id is None or match.team_b_id is None:
        return None
    if match.winner_team_id == match.team_a_id:
        return match.team_b_id
    if match.winner_team_id == match.team_b_id:
        return match.team_a_id
    return None


def compute_loser_rank_to_team(
    session: Session,
    event_id: int,
    schedule_version_id: int,
) -> Optional[Dict[int, int]]:
    """
    Map consolation rank 1..6 → team_id (1 = best original seed among R1 losers).
    Returns None until all six WF R1 losers are known (match FINAL).
    """
    r1_all = session.exec(
        select(Match).where(
            Match.event_id == event_id,
            Match.schedule_version_id == schedule_version_id,
            Match.match_type == "WF",
            Match.round_index == 1,
        )
    ).all()
    # Ignore the two auto-won bye matches (no opponent); only the 6 played R1 games
    # produce consolation losers.
    r1 = [m for m in r1_all if m.team_a_id and m.team_b_id and "_BYE" not in (m.match_code or "").upper()]
    if len(r1) != 6:
        return None

    losers: List[Tuple[int, int]] = []  # (seed, team_id)
    for m in r1:
        lid = _loser_id_from_final(m)
        if lid is None:
            return None
        team = session.get(Team, lid)
        if not team or team.seed is None:
            return None
        losers.append((team.seed, lid))

    losers.sort(key=lambda x: x[0])
    return {rank: team_id for rank, (_, team_id) in enumerate(losers, start=1)}


def _parse_cons_rank(placeholder: str) -> Optional[int]:
    if not placeholder or not placeholder.startswith("ConsL"):
        return None
    try:
        return int(placeholder[5:])
    except ValueError:
        return None


def refresh_wf14_consolation_main_slots(
    session: Session,
    event_id: int,
    schedule_version_id: int,
) -> int:
    """Fill MAIN consolation matches from ranked losers after WF R1 completes."""
    rank_to_team = compute_loser_rank_to_team(session, event_id, schedule_version_id)
    if not rank_to_team:
        return 0

    cons_main = session.exec(
        select(Match).where(
            Match.event_id == event_id,
            Match.schedule_version_id == schedule_version_id,
            Match.match_type == "MAIN",
            Match.match_code.contains("CONS_"),
        )
    ).all()
    updated = 0
    for m in cons_main:
        if "CONS_SUN" in (m.match_code or ""):
            continue
        ra = _parse_cons_rank(m.placeholder_side_a or "")
        rb = _parse_cons_rank(m.placeholder_side_b or "")
        if ra is None or rb is None:
            continue
        ta = rank_to_team.get(ra)
        tb = rank_to_team.get(rb)
        if ta is None or tb is None:
            continue
        changed = False
        if m.team_a_id != ta:
            m.team_a_id = ta
            m.placeholder_side_a = _team_label(session, ta)
            changed = True
        if m.team_b_id != tb:
            m.team_b_id = tb
            m.placeholder_side_b = _team_label(session, tb)
            changed = True
        if changed:
            session.add(m)
            updated += 1
    if updated:
        session.commit()
    return updated


def _division_ranks_for_team_ids(
    session: Session,
    team_ids: List[int],
    cons_matches: List[Match],
) -> Dict[int, int]:
    """
    Return team_id → standing 1..3 within division (1 = best) from finalized cons MAIN results.
    """
    allowed = set(team_ids)
    stats: Dict[int, Dict[str, int]] = {tid: {"w": 0, "l": 0} for tid in team_ids}
    seeds: Dict[int, int] = {}
    for tid in team_ids:
        t = session.get(Team, tid)
        seeds[tid] = t.seed if t and t.seed is not None else 9999

    for m in cons_matches:
        if (m.runtime_status or "") != "FINAL" or m.winner_team_id is None:
            continue
        if m.team_a_id not in allowed or m.team_b_id not in allowed:
            continue
        w = m.winner_team_id
        loser = m.team_b_id if w == m.team_a_id else m.team_a_id
        if w in stats:
            stats[w]["w"] += 1
        if loser in stats:
            stats[loser]["l"] += 1

    ordered = sorted(
        team_ids,
        key=lambda tid: (-stats[tid]["w"], stats[tid]["l"], seeds[tid]),
    )
    return {tid: idx + 1 for idx, tid in enumerate(ordered)}


def refresh_wf14_consolation_placement(
    session: Session,
    event_id: int,
    schedule_version_id: int,
) -> int:
    """After consolation MAIN round-robin, wire Sunday A1–B3 cross matches."""
    rank_to_team = compute_loser_rank_to_team(session, event_id, schedule_version_id)
    if not rank_to_team:
        return 0

    div_a_teams = [rank_to_team[r] for r in POOL_C_RANKS if r in rank_to_team]
    div_b_teams = [rank_to_team[r] for r in POOL_D_RANKS if r in rank_to_team]
    if len(div_a_teams) != 3 or len(div_b_teams) != 3:
        return 0

    cons_main = [
        m
        for m in session.exec(
            select(Match).where(
                Match.event_id == event_id,
                Match.schedule_version_id == schedule_version_id,
                Match.match_type == "MAIN",
                Match.match_code.contains("CONS_"),
            )
        ).all()
        if "CONS_SUN" not in (m.match_code or "")
    ]
    if not all((m.runtime_status or "") == "FINAL" and m.winner_team_id for m in cons_main):
        return 0

    stand_a = _division_ranks_for_team_ids(session, div_a_teams, cons_main)
    stand_b = _division_ranks_for_team_ids(session, div_b_teams, cons_main)

    # Pool C standings map to C1..C3, Pool D to D1..D3 (Sunday cross placement).
    slot_to_team_a = {f"C{stand_a[tid]}": tid for tid in div_a_teams}
    slot_to_team_b = {f"D{stand_b[tid]}": tid for tid in div_b_teams}

    placement = session.exec(
        select(Match).where(
            Match.event_id == event_id,
            Match.schedule_version_id == schedule_version_id,
            Match.match_type == "PLACEMENT",
            Match.placement_type == "WF14_CONS_CROSS",
        )
    ).all()
    updated = 0
    for m in placement:
        sa = (m.placeholder_side_a or "").strip()
        sb = (m.placeholder_side_b or "").strip()
        ta = slot_to_team_a.get(sa)
        tb = slot_to_team_b.get(sb)
        if ta is None or tb is None:
            continue
        changed = False
        if m.team_a_id != ta:
            m.team_a_id = ta
            m.placeholder_side_a = _team_label(session, ta)
            changed = True
        if m.team_b_id != tb:
            m.team_b_id = tb
            m.placeholder_side_b = _team_label(session, tb)
            changed = True
        if changed:
            session.add(m)
            updated += 1
    if updated:
        session.commit()
    return updated


def refresh_wf14_consolation_after_advancement(
    session: Session,
    event_id: int,
    schedule_version_id: int,
) -> int:
    if not event_uses_wf14(session, event_id, schedule_version_id):
        return 0
    n = refresh_wf14_consolation_main_slots(session, event_id, schedule_version_id)
    n += refresh_wf14_consolation_placement(session, event_id, schedule_version_id)
    return n
