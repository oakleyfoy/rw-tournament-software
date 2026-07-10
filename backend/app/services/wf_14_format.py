"""
14-team waterfall format: top-2 SEED byes, 12-team WF R1, 8-team WF R2, then 4 pools.

Byes: #1 and #2 seeds get a WF R1 bye match (no opponent, auto-win 8-0) and advance
to WF R2. #1 sits at the top of the bracket, #2 at the bottom.

Winner flight (WF R2 field of 8):
  Pool A = won both WF matches (WF R2 winners)
  Pool B = won R1, lost R2 (WF R2 losers)

Loser flight (6 WF R1 losers, reseeded 1–6 by original tournament seed; best seed = 1):
  Pool C = reseed ranks 1, 4, 6
  Pool D = reseed ranks 2, 3, 5
Each of C/D plays a 3-team round robin, then a Sunday cross-pool placement
(C1vD1, C2vD2, C3vD3 by final standing within each pool).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, List, Optional, Sequence, Tuple

if TYPE_CHECKING:
    from app.models.team import Team

TEMPLATE_KEY = "WF_14_TOP2_BYE"
TEAM_COUNT = 14
REQUIRED_WF_ROUNDS = 2  # R1 (6 matches on 12) + R2 (4 matches on 8)

WF_R1_MATCHES = 6
WF_R1_BYE_MATCHES = 2  # #1 and #2 seeds auto-advance (no court needed)
WF_R2_MATCHES = 4
POOL_COUNT = 2
TEAMS_PER_POOL = 4
RR_MATCHES_PER_POOL = 6
CONS_REGULAR_MATCHES = 6
CONS_PLACEMENT_MATCHES = 3


def wf_14_total_wf_matches() -> int:
    return WF_R1_MATCHES + WF_R2_MATCHES


def wf_14_total_rr_pool_matches() -> int:
    return POOL_COUNT * RR_MATCHES_PER_POOL


def wf_14_total_consolation_matches() -> int:
    return CONS_REGULAR_MATCHES + CONS_PLACEMENT_MATCHES


def wf_14_total_matches() -> int:
    """Court-consuming matches (excludes auto-won byes) — used for inventory/estimation."""
    return wf_14_total_wf_matches() + wf_14_total_rr_pool_matches() + wf_14_total_consolation_matches()


def wf_14_total_bye_matches() -> int:
    return WF_R1_BYE_MATCHES


def wf_14_total_generated_matches() -> int:
    """All Match rows the generator creates, including the two auto-won byes."""
    return wf_14_total_matches() + wf_14_total_bye_matches()


# Loser-flight pools: reseed ranks 1–6 (best original seed among R1 losers = 1).
POOL_C_RANKS: Tuple[int, ...] = (1, 4, 6)
POOL_D_RANKS: Tuple[int, ...] = (2, 3, 5)


@dataclass(frozen=True)
class ConsolationPairing:
    """A loser-flight pool match. Sides are reseed rank indices (1–6)."""

    pool: str  # "C" | "D"
    rank_a: int
    rank_b: int
    schedule_tag: str  # FRI | SAT1 | SAT2
    sequence: int


# Pool C {1,4,6} and Pool D {2,3,5} each play a full 3-team round robin.
# Day layout: Fri = one match per pool, Sat AM + Sat PM = the rest.
CONS_REGULAR_PAIRINGS: Tuple[ConsolationPairing, ...] = (
    ConsolationPairing("C", 1, 6, "FRI", 1),
    ConsolationPairing("D", 2, 5, "FRI", 2),
    ConsolationPairing("C", 4, 6, "SAT1", 1),
    ConsolationPairing("D", 3, 5, "SAT1", 2),
    ConsolationPairing("C", 1, 4, "SAT2", 1),
    ConsolationPairing("D", 2, 3, "SAT2", 2),
)

# Sunday cross-pool placement by final standing within each pool.
CONS_PLACEMENT_PAIRINGS: Tuple[Tuple[str, str], ...] = (
    ("C1", "D1"),
    ("C2", "D2"),
    ("C3", "D3"),
)


def cons_loser_placeholder(rank: int) -> str:
    return f"ConsL{rank}"


def cons_pool_for_rank(rank: int) -> str:
    """Return the loser-flight pool ('C' or 'D') for a reseed rank."""
    return "C" if rank in POOL_C_RANKS else "D"


def cons_division_slot(rank: int) -> str:
    """Map reseed rank 1–6 to its pool + within-pool seed slot (C1..C3, D1..D3)."""
    mapping = {
        1: "C1",
        4: "C2",
        6: "C3",
        2: "D1",
        3: "D2",
        5: "D3",
    }
    return mapping[rank]


def _seed_sort_key(team: "Team") -> Tuple[int, int]:
    seed = team.seed if team.seed is not None else 9999
    return (seed, team.id or 0)


def select_top_two_bye_teams(teams: Sequence["Team"]) -> Tuple[Optional["Team"], Optional["Team"]]:
    """Top two SEEDS get the byes (#1 seed first, #2 seed second)."""
    if len(teams) < 2:
        return None, None
    ordered = sorted(teams, key=_seed_sort_key)
    return ordered[0], ordered[1]


def teams_for_wf_r1(teams: Sequence["Team"], bye_ids: frozenset[int]) -> List["Team"]:
    """Remaining 12 teams in seed order for WF R1 pairing."""
    play = [t for t in teams if t.id not in bye_ids]
    return sorted(play, key=lambda t: t.seed if t.seed is not None else 9999)
