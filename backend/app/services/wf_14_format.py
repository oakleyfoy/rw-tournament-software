"""
14-team waterfall format: top-2 combined rating byes, 12-team WF R1, 8-team WF R2, then 2×4 pools.

Consolation flight: 6 WF R1 losers, ranked 1–6 by original tournament seed (best seed = 1).
Fixed division mapping: A = ranks 1,3,6 · B = ranks 2,4,5.
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
    return wf_14_total_wf_matches() + wf_14_total_rr_pool_matches() + wf_14_total_consolation_matches()


@dataclass(frozen=True)
class ConsolationPairing:
    """Losers ranked 1–6 by original seed; sides are rank indices."""

    rank_a: int
    rank_b: int
    schedule_tag: str  # FRI | SAT1 | SAT2
    sequence: int


CONS_REGULAR_PAIRINGS: Tuple[ConsolationPairing, ...] = (
    ConsolationPairing(1, 6, "FRI", 1),
    ConsolationPairing(2, 5, "FRI", 2),
    ConsolationPairing(3, 6, "SAT1", 1),
    ConsolationPairing(4, 5, "SAT1", 2),
    ConsolationPairing(1, 3, "SAT2", 1),
    ConsolationPairing(2, 4, "SAT2", 2),
)

CONS_PLACEMENT_PAIRINGS: Tuple[Tuple[str, str], ...] = (
    ("A1", "B1"),
    ("A2", "B2"),
    ("A3", "B3"),
)


def cons_loser_placeholder(rank: int) -> str:
    return f"ConsL{rank}"


def cons_division_slot(rank: int) -> str:
    """Map consolation rank 1–6 to division standing slot (A1..A3, B1..B3)."""
    mapping = {1: "A1", 3: "A2", 6: "A3", 2: "B1", 4: "B2", 5: "B3"}
    return mapping[rank]


def _rating_sort_key(team: "Team") -> Tuple[float, int]:
    rating = team.rating if team.rating is not None else float("-inf")
    seed = team.seed if team.seed is not None else 9999
    return (-rating, seed)


def select_top_two_bye_teams(teams: Sequence["Team"]) -> Tuple[Optional["Team"], Optional["Team"]]:
    """Top two combined ratings (higher rating first; tie-break lower seed)."""
    if len(teams) < 2:
        return None, None
    ordered = sorted(teams, key=_rating_sort_key)
    return ordered[0], ordered[1]


def teams_for_wf_r1(teams: Sequence["Team"], bye_ids: frozenset[int]) -> List["Team"]:
    """Remaining 12 teams in seed order for WF R1 pairing."""
    play = [t for t in teams if t.id not in bye_ids]
    return sorted(play, key=lambda t: t.seed if t.seed is not None else 9999)
