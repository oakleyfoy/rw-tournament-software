"""
Post-WF seeding and pool assignment.

Deterministic rules for ranking teams after waterfall rounds and assigning to pools.
"""

import hashlib
from dataclasses import dataclass
from typing import List, Sequence

# Bucket rank: WW=0, WL=1, LW=2, LL=3 (or W=0, L=1 if single WF round)
BUCKET_WW = 0
BUCKET_WL = 1
BUCKET_LW = 2
BUCKET_LL = 3
BUCKET_W = 0
BUCKET_L = 1


@dataclass
class WFTeamResult:
    """
    WF match results for a team. Used for tiebreak ranking.
    """

    team_id: int
    bucket_rank: int  # 0=best (WW or W), 3=worst (LL or L)
    wf_matches_won: int = 0
    wf_game_diff: int = 0  # games_for - games_against
    wf_games_lost: int = 0
    wf2_game_diff: int = 0  # 0 if no WF2
    wf2_games_lost: int = 0


def wf_rank_key(
    result: WFTeamResult,
    schedule_version_id: int,
    event_id: int,
) -> tuple:
    """
    Return sort key for post-WF ranking. Lower = better.

    Order: bucket, -wf_matches_won, -wf_game_diff, wf_games_lost,
           -wf2_game_diff, wf2_games_lost, stable_hash (asc for determinism).
    """
    stable_hash = _stable_hash(schedule_version_id, event_id, result.team_id)
    return (
        result.bucket_rank,
        -result.wf_matches_won,
        -result.wf_game_diff,
        result.wf_games_lost,
        -result.wf2_game_diff,
        result.wf2_games_lost,
        stable_hash,
    )


def _stable_hash(schedule_version_id: int, event_id: int, team_id: int) -> int:
    """Deterministic hash for tiebreak. Same inputs always yield same value."""
    s = f"{schedule_version_id}:{event_id}:{team_id}"
    return int(hashlib.sha256(s.encode()).hexdigest()[:12], 16)


def pool_assignment_contiguous(
    seeds_sorted: Sequence[int],
    num_pools: int,
    teams_per_pool: int,
) -> List[List[int]]:
    """
    Assign teams to pools using contiguous seed blocks.

    Pool A: seeds_sorted[0:teams_per_pool]
    Pool B: seeds_sorted[teams_per_pool:2*teams_per_pool]
    etc.

    No serpentine, no randomization.

    Args:
        seeds_sorted: Team IDs (or indices) in final seed order (best first)
        num_pools: Number of pools
        teams_per_pool: Teams per pool

    Returns:
        List of pools, each a list of team IDs in pool order
    """
    pools: List[List[int]] = []
    for pool_index in range(num_pools):
        start = pool_index * teams_per_pool
        end = start + teams_per_pool
        pool_teams = list(seeds_sorted[start:end])
        pools.append(pool_teams)
    return pools
