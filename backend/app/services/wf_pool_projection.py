"""
WF Pool Projection — compute projected RR pool assignments from WF match results.

Traces each team's waterfall path (W/L per round) to assign bucket ranks,
then uses wf_seeding utilities to rank within buckets and map to pools.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from sqlmodel import Session, select

from app.models.event import Event
from app.models.match import Match
from app.models.team import Team
from app.services.draw_plan_rules import pool_config, required_wf_rounds
from app.services.score_parser import parse_score
from app.utils.wf_seeding import (
    BUCKET_L,
    BUCKET_LL,
    BUCKET_LW,
    BUCKET_W,
    BUCKET_WL,
    BUCKET_WW,
    WFTeamResult,
    pool_assignment_contiguous,
    wf_rank_key,
)

POOL_LABELS = ["POOLA", "POOLB", "POOLC", "POOLD", "POOLE", "POOLEF", "POOLG", "POOLH"]
POOL_DISPLAY = {
    "POOLA": "Division I",
    "POOLB": "Division II",
    "POOLC": "Division III",
    "POOLD": "Division IV",
    "POOLE": "Division V",
    "POOLF": "Division VI",
    "POOLG": "Division VII",
    "POOLH": "Division VIII",
}

BUCKET_NAMES_2R = {BUCKET_WW: "WW", BUCKET_WL: "WL", BUCKET_LW: "LW", BUCKET_LL: "LL"}
BUCKET_NAMES_1R = {BUCKET_W: "W", BUCKET_L: "L"}


@dataclass
class ProjectedTeam:
    team_id: int
    team_display: str
    seed_position: int
    bucket: str
    status: str  # "confirmed" | "projected" | "pending"


@dataclass
class ProjectedPool:
    pool_label: str
    pool_display: str
    teams: List[ProjectedTeam]


@dataclass
class EventProjection:
    event_id: int
    event_name: str
    wf_complete: bool
    total_wf_matches: int
    finalized_wf_matches: int
    pools: List[ProjectedPool]
    unresolved_teams: List[Dict[str, Any]]


def compute_wf_projection(
    session: Session,
    tournament_id: int,
    version_id: int,
    event_id: int,
) -> Optional[EventProjection]:
    """Compute projected pool assignments for a single WF event."""
    event = session.get(Event, event_id)
    if not event or event.tournament_id != tournament_id:
        return None

    draw_plan = {}
    if event.draw_plan_json:
        try:
            draw_plan = json.loads(event.draw_plan_json)
        except (json.JSONDecodeError, TypeError):
            pass

    template_type = draw_plan.get("template_type", "RR_ONLY")
    if "WF_TO_POOLS" not in template_type:
        return None

    n = event.team_count or 0
    num_wf_rounds = draw_plan.get("wf_rounds", 0)
    if num_wf_rounds == 0:
        num_wf_rounds = required_wf_rounds(template_type, n)
    num_pools, teams_per_pool = pool_config(n)

    wf_matches = session.exec(
        select(Match).where(
            Match.tournament_id == tournament_id,
            Match.schedule_version_id == version_id,
            Match.event_id == event_id,
            Match.match_type == "WF",
        )
    ).all()

    if not wf_matches:
        return None

    total_wf = len(wf_matches)
    finalized_wf = sum(
        1 for m in wf_matches if (m.runtime_status or "SCHEDULED").upper() == "FINAL"
    )
    wf_complete = finalized_wf == total_wf

    # Separate by round
    r1_matches = [m for m in wf_matches if m.round_number == 1]
    r2_matches = [m for m in wf_matches if m.round_number == 2]

    # Collect all teams from R1 (they all start here)
    all_team_ids: set = set()
    for m in r1_matches:
        if m.team_a_id:
            all_team_ids.add(m.team_a_id)
        if m.team_b_id:
            all_team_ids.add(m.team_b_id)

    teams = session.exec(select(Team).where(Team.id.in_(list(all_team_ids)))).all() if all_team_ids else []
    team_map = {t.id: t for t in teams}

    def _disp(tid: int) -> str:
        t = team_map.get(tid)
        return (t.display_name or t.name or f"Team {tid}") if t else f"Team {tid}"

    # Build per-team WF results by tracing the match graph
    team_results: Dict[int, WFTeamResult] = {}

    # Track R1 outcomes: team_id -> ("W" | "L" | None)
    r1_outcome: Dict[int, Optional[str]] = {tid: None for tid in all_team_ids}
    r1_match_scores: Dict[int, Tuple[int, int]] = {}  # team_id -> (games_for, games_against)

    for m in r1_matches:
        status = (m.runtime_status or "SCHEDULED").upper()
        if status != "FINAL":
            continue
        if not m.team_a_id or not m.team_b_id or not m.winner_team_id:
            continue

        loser_id = m.team_b_id if m.winner_team_id == m.team_a_id else m.team_a_id
        r1_outcome[m.winner_team_id] = "W"
        r1_outcome[loser_id] = "L"

        parsed = parse_score(m.score_json)
        if parsed:
            r1_match_scores[m.team_a_id] = (parsed.team_a_games, parsed.team_b_games)
            r1_match_scores[m.team_b_id] = (parsed.team_b_games, parsed.team_a_games)

    if num_wf_rounds == 1:
        bucket_names = BUCKET_NAMES_1R
        for tid in all_team_ids:
            outcome = r1_outcome.get(tid)
            if outcome == "W":
                bucket = BUCKET_W
            elif outcome == "L":
                bucket = BUCKET_L
            else:
                bucket = -1  # pending

            gf, ga = r1_match_scores.get(tid, (0, 0))
            team_results[tid] = WFTeamResult(
                team_id=tid,
                bucket_rank=bucket if bucket >= 0 else 99,
                wf_matches_won=1 if outcome == "W" else 0,
                wf_game_diff=gf - ga,
                wf_games_lost=ga,
            )
    else:
        bucket_names = BUCKET_NAMES_2R
        # Track R2 outcomes
        r2_outcome: Dict[int, Optional[str]] = {}
        r2_match_scores: Dict[int, Tuple[int, int]] = {}

        # R2 matches have source_match_a_id/b_id pointing to R1 matches.
        # We need to find teams in R2 matches.
        for m in r2_matches:
            status = (m.runtime_status or "SCHEDULED").upper()
            a_id = m.team_a_id
            b_id = m.team_b_id

            if status == "FINAL" and a_id and b_id and m.winner_team_id:
                loser_id = b_id if m.winner_team_id == a_id else a_id
                r2_outcome[m.winner_team_id] = "W"
                r2_outcome[loser_id] = "L"

                parsed = parse_score(m.score_json)
                if parsed:
                    r2_match_scores[a_id] = (parsed.team_a_games, parsed.team_b_games)
                    r2_match_scores[b_id] = (parsed.team_b_games, parsed.team_a_games)
            else:
                # Not finalized yet — try to figure out who's in this match via advancement
                if a_id:
                    r2_outcome.setdefault(a_id, None)
                if b_id:
                    r2_outcome.setdefault(b_id, None)

        for tid in all_team_ids:
            o1 = r1_outcome.get(tid)
            o2 = r2_outcome.get(tid)

            if o1 == "W" and o2 == "W":
                bucket = BUCKET_WW
            elif o1 == "W" and o2 == "L":
                bucket = BUCKET_WL
            elif o1 == "L" and o2 == "W":
                bucket = BUCKET_LW
            elif o1 == "L" and o2 == "L":
                bucket = BUCKET_LL
            else:
                bucket = 99  # pending / incomplete

            r1_gf, r1_ga = r1_match_scores.get(tid, (0, 0))
            r2_gf, r2_ga = r2_match_scores.get(tid, (0, 0))
            total_gf = r1_gf + r2_gf
            total_ga = r1_ga + r2_ga

            wins = 0
            if o1 == "W":
                wins += 1
            if o2 == "W":
                wins += 1

            team_results[tid] = WFTeamResult(
                team_id=tid,
                bucket_rank=bucket,
                wf_matches_won=wins,
                wf_game_diff=total_gf - total_ga,
                wf_games_lost=total_ga,
                wf2_game_diff=r2_gf - r2_ga,
                wf2_games_lost=r2_ga,
            )

    # Rank all teams
    ranked_tids = sorted(
        team_results.keys(),
        key=lambda tid: wf_rank_key(team_results[tid], version_id, event_id),
    )

    # Assign to pools
    pool_assignments = pool_assignment_contiguous(ranked_tids, num_pools, teams_per_pool)

    pools: List[ProjectedPool] = []
    unresolved: List[Dict[str, Any]] = []
    seed_pos = 1

    for pool_idx, pool_team_ids in enumerate(pool_assignments):
        label = POOL_LABELS[pool_idx] if pool_idx < len(POOL_LABELS) else f"POOL{chr(ord('A') + pool_idx)}"
        display = POOL_DISPLAY.get(label, label)
        pool_teams: List[ProjectedTeam] = []

        for tid in pool_team_ids:
            result = team_results.get(tid)
            if not result:
                status = "pending"
                bucket_str = "—"
            elif result.bucket_rank == 99:
                status = "pending"
                bucket_str = "—"
                unresolved.append({"team_id": tid, "team_display": _disp(tid)})
            elif not wf_complete:
                status = "projected"
                bucket_str = bucket_names.get(result.bucket_rank, "?")
            else:
                status = "confirmed"
                bucket_str = bucket_names.get(result.bucket_rank, "?")

            pool_teams.append(ProjectedTeam(
                team_id=tid,
                team_display=_disp(tid),
                seed_position=seed_pos,
                bucket=bucket_str,
                status=status,
            ))
            seed_pos += 1

        pools.append(ProjectedPool(
            pool_label=label,
            pool_display=display,
            teams=pool_teams,
        ))

    return EventProjection(
        event_id=event_id,
        event_name=event.name,
        wf_complete=wf_complete,
        total_wf_matches=total_wf,
        finalized_wf_matches=finalized_wf,
        pools=pools,
        unresolved_teams=unresolved,
    )


def apply_pool_placement(
    session: Session,
    tournament_id: int,
    version_id: int,
    event_id: int,
    pools: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Resolve SEED_N placeholders on RR matches for the given event.

    pools: [{"pool_label": "POOLA", "team_ids": [4, 7, 12, 1]}, ...]

    Returns {"updated_matches": int, "assignments": [...]}
    """
    event = session.get(Event, event_id)
    if not event:
        raise ValueError("Event not found")

    draw_plan = {}
    if event.draw_plan_json:
        try:
            draw_plan = json.loads(event.draw_plan_json)
        except (json.JSONDecodeError, TypeError):
            pass

    n = event.team_count or 0
    num_pools, teams_per_pool = pool_config(n)

    # Build seed_number -> team_id mapping from the pools payload
    seed_to_team: Dict[int, int] = {}
    for pool_data in pools:
        pool_label = pool_data["pool_label"]
        team_ids = pool_data["team_ids"]

        # Determine pool index from label
        pool_idx = -1
        for i, lbl in enumerate(POOL_LABELS):
            if lbl == pool_label:
                pool_idx = i
                break
        if pool_idx < 0:
            raise ValueError(f"Unknown pool label: {pool_label}")

        for pos, tid in enumerate(team_ids):
            global_seed = pool_idx * teams_per_pool + pos + 1
            seed_to_team[global_seed] = tid

    # Load RR matches for this event+version
    rr_matches = session.exec(
        select(Match).where(
            Match.tournament_id == tournament_id,
            Match.schedule_version_id == version_id,
            Match.event_id == event_id,
            Match.match_type == "RR",
        )
    ).all()

    updated = 0
    assignments = []

    seed_pattern = re.compile(r"^SEED_(\d+)$")

    for m in rr_matches:
        changed = False

        ma = seed_pattern.match(m.placeholder_side_a or "")
        if ma:
            seed_num = int(ma.group(1))
            tid = seed_to_team.get(seed_num)
            if tid and m.team_a_id != tid:
                m.team_a_id = tid
                changed = True

        mb = seed_pattern.match(m.placeholder_side_b or "")
        if mb:
            seed_num = int(mb.group(1))
            tid = seed_to_team.get(seed_num)
            if tid and m.team_b_id != tid:
                m.team_b_id = tid
                changed = True

        if changed:
            session.add(m)
            updated += 1
            assignments.append({
                "match_id": m.id,
                "match_code": m.match_code,
                "team_a_id": m.team_a_id,
                "team_b_id": m.team_b_id,
            })

    session.commit()

    return {"updated_matches": updated, "assignments": assignments}
