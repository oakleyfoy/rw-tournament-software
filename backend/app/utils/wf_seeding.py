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
    bucket_rank: int  # retained for display; 99 indicates pending/incomplete
    wf_matches_won: int = 0
    wf_game_diff: int = 0  # games_for - games_against
    wf_games_lost: int = 0
    wf2_game_diff: int = 0  # 0 if no WF2
    wf2_games_lost: int = 0
    original_seed: int = 999999


def wf_overall_seed_key(
    result: WFTeamResult,
    schedule_version_id: int,
    event_id: int,
) -> tuple:
    """Rank the whole field 1..n after waterfall. Lower = better.

    Wins come first. Equal records are broken by waterfall tiebreakers
    (round-2 game diff, then overall game diff, then original seed).
    Win/loss path is not a separate tier, so a 1-1 team is not ranked
    above another 1-1 team just because it won round 1.
    """
    stable_hash = _stable_hash(schedule_version_id, event_id, result.team_id)
    return (
        1 if result.bucket_rank == 99 else 0,
        -result.wf_matches_won,
        -result.wf2_game_diff,
        -result.wf_game_diff,
        result.original_seed,
        stable_hash,
    )


def wf24_quarterfinal_seeds() -> list[list[tuple[int, int]]]:
    """Three 8-team brackets from an overall 1-24 seed.

    Bracket 1 is seeds 1-8, bracket 2 is 9-16, bracket 3 is 17-24.
    Inside each bracket the quarterfinals are 1v8, 4v5, 2v7, 3v6.
    """
    local_pairs = [(1, 8), (4, 5), (2, 7), (3, 6)]
    brackets: list[list[tuple[int, int]]] = []
    for bracket_index in range(3):
        offset = bracket_index * 8
        brackets.append([(offset + left, offset + right) for left, right in local_pairs])
    return brackets


def wf_rank_key(
    result: WFTeamResult,
    schedule_version_id: int,
    event_id: int,
) -> tuple:
    """
    Return sort key for post-WF ranking. Lower = better.

    Order: pending last, then bucket path, then -wf_matches_won,
           -wf2_game_diff, -wf_game_diff, original_seed, stable_hash (asc).
    """
    stable_hash = _stable_hash(schedule_version_id, event_id, result.team_id)
    return (
        1 if result.bucket_rank == 99 else 0,
        result.bucket_rank,
        -result.wf_matches_won,
        -result.wf2_game_diff,
        -result.wf_game_diff,
        result.original_seed,
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
