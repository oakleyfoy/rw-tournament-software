"""
WF_10_SIX_FOUR advancement: lucky loser, fill winners/losers RR, Sunday placement.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Dict, List, Optional, Tuple

from sqlmodel import Session, select

from app.models.event import Event
from app.models.match import Match
from app.models.team import Team
from app.services.score_parser import parse_score
from app.services.wf_10_format import POOL_A_RANKS, POOL_B_RANKS
from app.utils.wf_seeding import WFTeamResult, wf_rank_key


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


def is_wf10_event(event: Event) -> bool:
    return _event_template(event) == "WF_10_SIX_FOUR"


def event_uses_wf10(
    session: Session,
    event_id: int,
    schedule_version_id: Optional[int] = None,
) -> bool:
    event = session.get(Event, event_id)
    if event and is_wf10_event(event):
        return True
    q = select(Match).where(
        Match.event_id == event_id,
        Match.placement_type.in_(["WF10_WIN_CROSS", "WF10_LOSS_PLACE", "WF10_FUN"]),  # type: ignore[attr-defined]
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


def _is_retired_score(score_json) -> bool:
    if not score_json or not isinstance(score_json, dict):
        return False
    return bool(score_json.get("retired") or score_json.get("retirement"))


def _stable_coin(tournament_id: int, event_id: int, team_id: int) -> int:
    s = f"wf10-lucky:{tournament_id}:{event_id}:{team_id}"
    return int(hashlib.sha256(s.encode()).hexdigest()[:12], 16)


def _resolve_seed(session: Session, event_id: int, team_id: int, fallback: int) -> int:
    t = session.get(Team, team_id)
    if t and t.seed is not None:
        return t.seed
    return fallback


def compute_wf10_flight_ranks(
    session: Session,
    tournament_id: int,
    event_id: int,
    schedule_version_id: int,
) -> Optional[Tuple[Dict[int, int], Dict[int, int]]]:
    """
    After all 5 WF R1 matches are FINAL, return:
      (winners_rank_to_team 1..6, losers_rank_to_team 1..4)

    Winners 1–5 = WF winners ordered by wf_rank_key.
    Winner #6 = lucky loser (closest-score loss among 5 losers).
    Losers 1–4 = remaining losers ordered by wf_rank_key among losers.
    """
    r1 = session.exec(
        select(Match).where(
            Match.event_id == event_id,
            Match.schedule_version_id == schedule_version_id,
            Match.match_type == "WF",
            Match.round_index == 1,
        )
    ).all()
    r1 = [m for m in r1 if m.team_a_id and m.team_b_id]
    if len(r1) != 5:
        return None

    winners: List[int] = []
    losers: List[int] = []
    results: Dict[int, WFTeamResult] = {}

    for m in r1:
        if (m.runtime_status or "").upper() != "FINAL" or not m.winner_team_id:
            return None
        w = m.winner_team_id
        loser = _loser_id_from_final(m)
        if loser is None:
            return None
        winners.append(w)
        losers.append(loser)

        gf_a, ga_a = 0, 0
        gf_b, ga_b = 0, 0
        parsed = parse_score(m.score_json)
        if parsed:
            a_games = parsed.team_a_games
            b_games = parsed.team_b_games
            if not _is_retired_score(m.score_json):
                if w == m.team_a_id and b_games > a_games:
                    a_games, b_games = b_games, a_games
                elif w == m.team_b_id and a_games > b_games:
                    a_games, b_games = b_games, a_games
            gf_a, ga_a = a_games, b_games
            gf_b, ga_b = b_games, a_games

        for tid, gf, ga, won in (
            (m.team_a_id, gf_a, ga_a, w == m.team_a_id),
            (m.team_b_id, gf_b, ga_b, w == m.team_b_id),
        ):
            if tid is None:
                continue
            results[tid] = WFTeamResult(
                team_id=tid,
                bucket_rank=0 if won else 1,
                wf_matches_won=1 if won else 0,
                wf_game_diff=gf - ga,
                wf_games_lost=ga,
                original_seed=_resolve_seed(session, event_id, tid, 999999),
            )

    if len(winners) != 5 or len(losers) != 5:
        return None

    winners_sorted = sorted(
        winners,
        key=lambda tid: wf_rank_key(results[tid], schedule_version_id, event_id),
    )

    # Lucky loser: closest score loss = maximize game_diff among losers (least negative).
    # Ties: better original seed (lower number), then deterministic coin.
    def lucky_key(tid: int) -> tuple:
        r = results[tid]
        return (
            -r.wf_game_diff,  # closest loss first (higher / less negative diff)
            r.original_seed,
            _stable_coin(tournament_id, event_id, tid),
        )

    losers_by_margin = sorted(losers, key=lucky_key)
    lucky = losers_by_margin[0]
    remaining_losers = [tid for tid in losers if tid != lucky]
    remaining_losers.sort(key=lambda tid: wf_rank_key(results[tid], schedule_version_id, event_id))

    win_rank = {i + 1: tid for i, tid in enumerate(winners_sorted)}
    win_rank[6] = lucky
    loss_rank = {i + 1: tid for i, tid in enumerate(remaining_losers)}
    return win_rank, loss_rank


_W_PLACEHOLDER = re.compile(r"^W(\d+)$")
_L_PLACEHOLDER = re.compile(r"^L(\d+)$")


def refresh_wf10_rr_slots(
    session: Session,
    tournament_id: int,
    event_id: int,
    schedule_version_id: int,
) -> int:
    """Fill WIN_/FUN_/LOSS_ RR placeholders after WF completes."""
    ranks = compute_wf10_flight_ranks(session, tournament_id, event_id, schedule_version_id)
    if not ranks:
        return 0
    win_rank, loss_rank = ranks

    rr_matches = session.exec(
        select(Match).where(
            Match.event_id == event_id,
            Match.schedule_version_id == schedule_version_id,
            Match.match_type == "RR",
        )
    ).all()

    updated = 0
    for m in rr_matches:
        code = (m.match_code or "").upper()
        if not any(tag in code for tag in ("WIN_", "FUN_", "LOSS_")):
            continue
        changed = False
        for side in ("a", "b"):
            ph = (m.placeholder_side_a if side == "a" else m.placeholder_side_b) or ""
            mw = _W_PLACEHOLDER.match(ph.strip())
            ml = _L_PLACEHOLDER.match(ph.strip())
            tid = None
            if mw:
                tid = win_rank.get(int(mw.group(1)))
            elif ml:
                tid = loss_rank.get(int(ml.group(1)))
            if tid is None:
                continue
            if side == "a" and m.team_a_id != tid:
                m.team_a_id = tid
                m.placeholder_side_a = _team_label(session, tid)
                changed = True
            elif side == "b" and m.team_b_id != tid:
                m.team_b_id = tid
                m.placeholder_side_b = _team_label(session, tid)
                changed = True
        if changed:
            session.add(m)
            updated += 1
    if updated:
        session.commit()
    return updated


def _standing_ranks(
    session: Session,
    team_ids: List[int],
    pool_matches: List[Match],
) -> Dict[int, int]:
    """team_id → standing 1..n (1 = best) from finalized pool results."""
    allowed = set(team_ids)
    stats = {tid: {"w": 0, "l": 0, "gd": 0} for tid in team_ids}
    seeds: Dict[int, int] = {}
    for tid in team_ids:
        t = session.get(Team, tid)
        seeds[tid] = t.seed if t and t.seed is not None else 9999

    for m in pool_matches:
        if (m.runtime_status or "") != "FINAL" or m.winner_team_id is None:
            continue
        if m.team_a_id not in allowed or m.team_b_id not in allowed:
            continue
        w = m.winner_team_id
        loser = m.team_b_id if w == m.team_a_id else m.team_a_id
        stats[w]["w"] += 1
        stats[loser]["l"] += 1
        parsed = parse_score(m.score_json)
        if parsed:
            a_g, b_g = parsed.team_a_games, parsed.team_b_games
            if w == m.team_a_id:
                stats[m.team_a_id]["gd"] += a_g - b_g
                stats[m.team_b_id]["gd"] += b_g - a_g
            else:
                stats[m.team_b_id]["gd"] += b_g - a_g
                stats[m.team_a_id]["gd"] += a_g - b_g

    ordered = sorted(
        team_ids,
        key=lambda tid: (-stats[tid]["w"], stats[tid]["l"], -stats[tid]["gd"], seeds[tid]),
    )
    return {tid: idx + 1 for idx, tid in enumerate(ordered)}


def refresh_wf10_sunday_placement(
    session: Session,
    tournament_id: int,
    event_id: int,
    schedule_version_id: int,
) -> int:
    ranks = compute_wf10_flight_ranks(session, tournament_id, event_id, schedule_version_id)
    if not ranks:
        return 0
    win_rank, loss_rank = ranks

    pool_a = [win_rank[r] for r in POOL_A_RANKS if r in win_rank]
    pool_b = [win_rank[r] for r in POOL_B_RANKS if r in win_rank]
    pool_l = [loss_rank[r] for r in range(1, 5) if r in loss_rank]
    if len(pool_a) != 3 or len(pool_b) != 3 or len(pool_l) != 4:
        return 0

    all_rr = session.exec(
        select(Match).where(
            Match.event_id == event_id,
            Match.schedule_version_id == schedule_version_id,
            Match.match_type == "RR",
        )
    ).all()

    win_rr = [
        m for m in all_rr if "WIN_" in (m.match_code or "").upper() and "FUN_" not in (m.match_code or "").upper()
    ]
    # Fun matches do not count toward mini-pool standings.
    loss_rr = [m for m in all_rr if "LOSS_" in (m.match_code or "").upper()]

    # Need all non-fun WIN RR and LOSS RR finalized
    needed = [m for m in win_rr + loss_rr if "FUN_" not in (m.match_code or "").upper()]
    if not needed or not all((m.runtime_status or "") == "FINAL" and m.winner_team_id for m in needed):
        return 0

    stand_a = _standing_ranks(session, pool_a, win_rr)
    stand_b = _standing_ranks(session, pool_b, win_rr)
    stand_l = _standing_ranks(session, pool_l, loss_rr)

    slot_to_team = {f"A{stand_a[tid]}": tid for tid in pool_a}
    slot_to_team.update({f"B{stand_b[tid]}": tid for tid in pool_b})
    slot_to_team.update({f"L{stand_l[tid]}": tid for tid in pool_l})

    placement = session.exec(
        select(Match).where(
            Match.event_id == event_id,
            Match.schedule_version_id == schedule_version_id,
            Match.match_type == "PLACEMENT",
            Match.placement_type.in_(["WF10_WIN_CROSS", "WF10_LOSS_PLACE"]),  # type: ignore[attr-defined]
        )
    ).all()

    updated = 0
    for m in placement:
        sa = (m.placeholder_side_a or "").strip()
        sb = (m.placeholder_side_b or "").strip()
        # After first fill placeholders become names — skip if already filled with teams
        ta = slot_to_team.get(sa)
        tb = slot_to_team.get(sb)
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


def refresh_wf10_after_advancement(
    session: Session,
    tournament_id: int,
    event_id: int,
    schedule_version_id: int,
) -> int:
    if not event_uses_wf10(session, event_id, schedule_version_id):
        return 0
    n = refresh_wf10_rr_slots(session, tournament_id, event_id, schedule_version_id)
    n += refresh_wf10_sunday_placement(session, tournament_id, event_id, schedule_version_id)
    return n
