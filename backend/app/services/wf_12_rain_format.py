"""
12-team rain draw: manual seeds, no waterfall.

Seeds 1–6 and 7–12 are separate flights. Each flight splits like the 10-team
winners side:

  Group high: ranks 1, 4, 6
  Group low:  ranks 2, 3, 5

Each group plays a 3-team round robin. The two byes play a friendly the same
round; friendlies do not count toward the group order. After the groups finish,
#1 plays #1, #2 plays #2, and #3 plays #3 inside that flight.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

TEMPLATE_KEY = "WF_12_RAIN_SIX"
TEAM_COUNT = 12
REQUIRED_WF_ROUNDS = 0

# Ranks inside one flight of 6. Bottom flight uses the same ranks on seeds 7–12.
HIGH_RANKS: Tuple[int, ...] = (1, 4, 6)
LOW_RANKS: Tuple[int, ...] = (2, 3, 5)

GROUP_MATCHES_PER_FLIGHT = 6
FUN_MATCHES_PER_FLIGHT = 3
PLACEMENT_MATCHES_PER_FLIGHT = 3
FLIGHTS = ("TOP", "BOT")


def wf_12_rain_group_matches() -> int:
    return GROUP_MATCHES_PER_FLIGHT * len(FLIGHTS)


def wf_12_rain_fun_matches() -> int:
    return FUN_MATCHES_PER_FLIGHT * len(FLIGHTS)


def wf_12_rain_placement_matches() -> int:
    return PLACEMENT_MATCHES_PER_FLIGHT * len(FLIGHTS)


def wf_12_rain_total_matches() -> int:
    return wf_12_rain_group_matches() + wf_12_rain_fun_matches() + wf_12_rain_placement_matches()


@dataclass(frozen=True)
class RainGroupPairing:
    """One group match. side is HIGH (A/C) or LOW (B/D). ranks are 1–6 inside the flight."""

    side: str  # "HIGH" | "LOW"
    rank_a: int
    rank_b: int
    schedule_tag: str  # FRI | SAT1 | SAT2
    sequence: int


@dataclass(frozen=True)
class RainFunPairing:
    rank_a: int
    rank_b: int
    schedule_tag: str
    sequence: int


# Same day layout as the 10-team winners mini-pools.
# HIGH {1,4,6}: FRI 1v6 (bye 4), SAT1 4v6 (bye 1), SAT2 1v4 (bye 6)
# LOW  {2,3,5}: FRI 2v5 (bye 3), SAT1 3v5 (bye 2), SAT2 2v3 (bye 5)
GROUP_PAIRINGS: Tuple[RainGroupPairing, ...] = (
    RainGroupPairing("HIGH", 1, 6, "FRI", 1),
    RainGroupPairing("LOW", 2, 5, "FRI", 2),
    RainGroupPairing("HIGH", 4, 6, "SAT1", 1),
    RainGroupPairing("LOW", 3, 5, "SAT1", 2),
    RainGroupPairing("HIGH", 1, 4, "SAT2", 1),
    RainGroupPairing("LOW", 2, 3, "SAT2", 2),
)

FUN_PAIRINGS: Tuple[RainFunPairing, ...] = (
    RainFunPairing(4, 3, "FRI", 1),
    RainFunPairing(1, 2, "SAT1", 1),
    RainFunPairing(6, 5, "SAT2", 1),
)

# (high slot, low slot) — letters are applied per flight (A/B or C/D).
PLACEMENT_SLOTS: Tuple[Tuple[int, int], ...] = (
    (1, 1),
    (2, 2),
    (3, 3),
)


def flight_pool_letters(flight: str) -> Tuple[str, str]:
    """Return (high letter, low letter) for TOP (A/B) or BOT (C/D)."""
    if flight == "TOP":
        return "A", "B"
    if flight == "BOT":
        return "C", "D"
    raise ValueError(f"Unknown rain flight: {flight}")


def seed_for_flight_rank(flight: str, rank: int) -> int:
    """Map a 1–6 rank inside a flight onto the manual seed (1–12)."""
    if flight == "TOP":
        return rank
    if flight == "BOT":
        return rank + 6
    raise ValueError(f"Unknown rain flight: {flight}")
