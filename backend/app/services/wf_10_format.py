"""
10-team waterfall format: 1 WF round, then winners 6 + losers 4.

After WF R1 (5 matches):
  - Winners flight (6): 5 WF winners + 1 lucky loser (closest-score loss among
    the 5 losers; ties → better original seed → deterministic hash).
    Ranked 1–6, then split into mini-pools:
      Pool A = ranks 1, 4, 6
      Pool B = ranks 2, 3, 5
    Each mini-pool plays a 3-team RR (Fri / Sat1 / Sat2). Byes from the two
    mini-pools play each other as a real "fun" match the same day.
  - Losers pool (4): remaining 4 WF losers play a 4-team RR (Fri / Sat1 / Sat2).

Sunday:
  - Winners: A1vB1, A2vB2, A3vB3 (standings within each mini-pool)
  - Losers: #1v#2 and #3v#4 (standings within the 4-team pool)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

TEMPLATE_KEY = "WF_10_SIX_FOUR"
TEAM_COUNT = 10
REQUIRED_WF_ROUNDS = 1

WF_R1_MATCHES = 5

# Winners flight
POOL_A_RANKS: Tuple[int, ...] = (1, 4, 6)
POOL_B_RANKS: Tuple[int, ...] = (2, 3, 5)
WIN_RR_MATCHES = 6  # 2 pools × 3 matches
FUN_MATCHES = 3  # one per RR round (bye vs bye)
WIN_SUN_MATCHES = 3  # A1vB1, A2vB2, A3vB3

# Losers flight
LOSS_RR_MATCHES = 6  # C(4,2)
LOSS_SUN_MATCHES = 2  # #1v#2 and #3v#4


def wf_10_total_wf_matches() -> int:
    return WF_R1_MATCHES


def wf_10_total_win_rr_matches() -> int:
    return WIN_RR_MATCHES


def wf_10_total_fun_matches() -> int:
    return FUN_MATCHES


def wf_10_total_loss_rr_matches() -> int:
    return LOSS_RR_MATCHES


def wf_10_total_sunday_matches() -> int:
    return WIN_SUN_MATCHES + LOSS_SUN_MATCHES


def wf_10_total_matches() -> int:
    """Court-consuming matches (all are real courts for this format)."""
    return (
        wf_10_total_wf_matches()
        + wf_10_total_win_rr_matches()
        + wf_10_total_fun_matches()
        + wf_10_total_loss_rr_matches()
        + wf_10_total_sunday_matches()
    )


def wf_10_total_generated_matches() -> int:
    return wf_10_total_matches()


@dataclass(frozen=True)
class TaggedPairing:
    """One pool RR (or fun) match with a schedule day tag."""

    pool: str  # "A" | "B" | "L" | "FUN"
    rank_a: int
    rank_b: int
    schedule_tag: str  # FRI | SAT1 | SAT2
    sequence: int


# Mini-pool RR: same day layout as WF_14 C/D (Fri one match, Sat AM + Sat PM).
# Pool A {1,4,6}: FRI 1v6 (bye 4), SAT1 4v6 (bye 1), SAT2 1v4 (bye 6)
# Pool B {2,3,5}: FRI 2v5 (bye 3), SAT1 3v5 (bye 2), SAT2 2v3 (bye 5)
WIN_RR_PAIRINGS: Tuple[TaggedPairing, ...] = (
    TaggedPairing("A", 1, 6, "FRI", 1),
    TaggedPairing("B", 2, 5, "FRI", 2),
    TaggedPairing("A", 4, 6, "SAT1", 1),
    TaggedPairing("B", 3, 5, "SAT1", 2),
    TaggedPairing("A", 1, 4, "SAT2", 1),
    TaggedPairing("B", 2, 3, "SAT2", 2),
)

# Bye ranks facing each other each day (fun matches).
FUN_PAIRINGS: Tuple[TaggedPairing, ...] = (
    TaggedPairing("FUN", 4, 3, "FRI", 1),  # A bye 4 vs B bye 3
    TaggedPairing("FUN", 1, 2, "SAT1", 1),  # A bye 1 vs B bye 2
    TaggedPairing("FUN", 6, 5, "SAT2", 1),  # A bye 6 vs B bye 5
)

# Losers 4-team RR: R1 1v4+2v3, R2 1v3+2v4, R3 1v2+3v4 (1v2 last).
LOSS_RR_PAIRINGS: Tuple[TaggedPairing, ...] = (
    TaggedPairing("L", 1, 4, "FRI", 1),
    TaggedPairing("L", 2, 3, "FRI", 2),
    TaggedPairing("L", 1, 3, "SAT1", 1),
    TaggedPairing("L", 2, 4, "SAT1", 2),
    TaggedPairing("L", 1, 2, "SAT2", 1),
    TaggedPairing("L", 3, 4, "SAT2", 2),
)

WIN_SUN_PAIRINGS: Tuple[Tuple[str, str], ...] = (
    ("A1", "B1"),
    ("A2", "B2"),
    ("A3", "B3"),
)

LOSS_SUN_PAIRINGS: Tuple[Tuple[str, str], ...] = (
    ("L1", "L2"),
    ("L3", "L4"),
)


def win_rank_placeholder(rank: int) -> str:
    return f"W{rank}"


def loss_rank_placeholder(rank: int) -> str:
    return f"L{rank}"


def win_pool_for_rank(rank: int) -> str:
    return "A" if rank in POOL_A_RANKS else "B"


def win_division_slot(rank: int) -> str:
    """Map winners-flight rank 1–6 to mini-pool seed slot A1..A3 / B1..B3."""
    mapping = {
        1: "A1",
        4: "A2",
        6: "A3",
        2: "B1",
        3: "B2",
        5: "B3",
    }
    return mapping[rank]
