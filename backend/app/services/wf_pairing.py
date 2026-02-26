"""
WF Round 1 Pairing — half-split matchups in bracket-fold order.

Matchups: seed i vs seed (i + n/2) — standard top-half vs bottom-half.
Ordering: bracket fold positions determine which match goes in which
bracket slot, so that if chalk holds seed 1 meets seed 2 in the final.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Tuple


@dataclass
class TeamSeed:
    """Lightweight struct for pairing input."""
    seed: int
    team_id: int
    avoid_group: Optional[str] = None
    display_name: Optional[str] = None


@dataclass
class PairingConflict:
    seed_a: int
    seed_b: int
    group: str
    reason: str


@dataclass
class PairingResult:
    pairs: List[Tuple[int, int]]
    team_id_pairs: List[Tuple[int, int]]
    conflicts: List[PairingConflict]


def bracket_fold_positions(n: int) -> List[int]:
    """Standard bracket-fold positions for *n* entries.

    Returns a flat list of seed numbers in bracket position order.
    Consecutive pairs indicate which seeds meet if chalk holds:
      4-entry  -> [1, 4, 2, 3]       -> (1v4), (2v3)
      8-entry  -> [1, 8, 4, 5, ...]   -> (1v8), (4v5), ...
      16-entry -> [1, 16, 8, 9, ...]   -> (1v16), (8v9), ...
    """
    if n == 2:
        return [1, 2]

    half = bracket_fold_positions(n // 2)

    expanded: List[int] = []
    for s in half:
        expanded.append(s)
        expanded.append(n + 1 - s)

    mid = len(expanded) // 2
    top = expanded[:mid]
    bot = expanded[mid:]
    if len(bot) >= 4:
        bot = bot[:-4] + bot[-2:] + bot[-4:-2]

    return top + bot


def build_wf_r1_pairings(teams: List[TeamSeed], n: int) -> PairingResult:
    """Build WF R1 pairings for *n* teams.

    Step 1 — half-split matchups: seed i vs seed (i + n/2).
    Step 2 — order the matches by bracket_fold_positions(n/2)
             so the bracket plays out correctly when chalk holds.

    Matchups are fixed by seed; avoid-group conflicts are reported
    but not avoided.
    """
    assert n >= 2 and n % 2 == 0, f"n must be even >= 2, got {n}"
    assert len(teams) == n, f"Expected {n} teams, got {len(teams)}"

    by_seed = {t.seed: t for t in teams}
    half = n // 2

    matchups_by_top_seed = {}
    for i in range(1, half + 1):
        matchups_by_top_seed[i] = (by_seed[i], by_seed[i + half])

    if half == 1:
        fold_order = [1]
    else:
        fold_order = bracket_fold_positions(half)

    ordered_pairs = [matchups_by_top_seed[s] for s in fold_order]

    seed_pairs: List[Tuple[int, int]] = []
    team_id_pairs: List[Tuple[int, int]] = []
    conflicts: List[PairingConflict] = []

    for a, b in ordered_pairs:
        seed_pairs.append((a.seed, b.seed))
        team_id_pairs.append((a.team_id, b.team_id))

        if a.avoid_group and b.avoid_group and a.avoid_group == b.avoid_group:
            conflicts.append(PairingConflict(
                seed_a=a.seed,
                seed_b=b.seed,
                group=a.avoid_group,
                reason=(
                    f"Half-split conflict: seed {a.seed} and seed {b.seed} "
                    f"both in group '{a.avoid_group}'"
                ),
            ))

    return PairingResult(
        pairs=seed_pairs,
        team_id_pairs=team_id_pairs,
        conflicts=conflicts,
    )
