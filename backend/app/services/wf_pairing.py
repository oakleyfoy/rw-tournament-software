"""
WF Round 1 Pairing — half-split matchups in bracket-fold order,
with avoid-group conflict resolution.

Matchups: seed i vs seed (i + n/2) — standard top-half vs bottom-half.
Ordering: bracket fold positions determine which match goes in which
bracket slot, so that if chalk holds seed 1 meets seed 2 in the final.

After generating the standard pairings, the algorithm checks for
avoid-group conflicts and tries to resolve them by swapping bottom-half
teams within the same bracket quarter.
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
    name: Optional[str] = None


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
    name_pairs: List[Tuple[str, str]] = field(default_factory=list)
    display_name_pairs: List[Tuple[Optional[str], Optional[str]]] = field(default_factory=list)


def bracket_fold_positions(n: int) -> List[int]:
    """Standard bracket-fold positions for *n* entries.

    Returns a flat list of seed numbers in bracket position order.
    Consecutive pairs indicate which seeds meet if chalk holds:
      4-entry  -> [1, 4, 2, 3]       -> (1v4), (2v3)
      8-entry  -> [1, 8, 4, 5, ...]   -> (1v8), (4v5), ...
      16-entry -> [1, 16, 8, 9, ...]   -> (1v16), (8v9), ...
    """
    if n <= 0:
        return []
    if n == 1:
        return [1]
    if n == 2:
        return [1, 2]
    # Bracket fold is defined for powers of two. For non-powers (e.g., 6 top seeds
    # in a 12-team WF round), keep deterministic seed order to avoid recursion.
    if n & (n - 1):
        return list(range(1, n + 1))

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


# ── Avoid-group helpers ──────────────────────────────────────────────


def _groups_conflict(group_a: Optional[str], group_b: Optional[str]) -> Optional[str]:
    """Check if two avoid_group strings share any group.

    Multi-group support: "A,B" conflicts with "B,C" via shared group "B".
    Returns the first shared group name (alphabetically), or None.
    """
    if not group_a or not group_b:
        return None
    set_a = {g.strip() for g in group_a.split(",")}
    set_b = {g.strip() for g in group_b.split(",")}
    overlap = set_a & set_b
    if overlap:
        return sorted(overlap)[0]
    return None


def _resolve_quarter_conflicts(
    pairs: List[Tuple[TeamSeed, TeamSeed]],
) -> List[Tuple[TeamSeed, TeamSeed]]:
    """Resolve avoid-group conflicts within a bracket quarter.

    For each conflicting pair (scanning in order), try swapping its
    bottom-half team with another bottom-half team in the quarter.
    Apply the first swap that resolves the conflict without introducing
    any new ones.  Deterministic: same inputs always produce same swaps.
    """
    n = len(pairs)
    if n < 2:
        return list(pairs)

    result = list(pairs)

    for i in range(n):
        a_i, b_i = result[i]
        if not _groups_conflict(a_i.avoid_group, b_i.avoid_group):
            continue  # no conflict at position i

        # Try swapping b_i with b_j for each j != i in this quarter
        for j in range(n):
            if j == i:
                continue
            a_j, b_j = result[j]

            # Only swap if it resolves i without breaking j
            new_conflict_i = _groups_conflict(a_i.avoid_group, b_j.avoid_group)
            new_conflict_j = _groups_conflict(a_j.avoid_group, b_i.avoid_group)

            if not new_conflict_i and not new_conflict_j:
                result[i] = (a_i, b_j)
                result[j] = (a_j, b_i)
                break  # conflict resolved, move on

    return result


# ── Main entry point ─────────────────────────────────────────────────


def build_wf_r1_pairings(teams: List[TeamSeed], n: int) -> PairingResult:
    """Build WF R1 pairings for *n* teams.

    Step 1 — half-split matchups: seed i vs seed (i + n/2).
    Step 2 — order the matches by bracket_fold_positions(n/2)
             so the bracket plays out correctly when chalk holds.
    Step 3 — resolve avoid-group conflicts by swapping bottom-half
             teams within each bracket quarter.
    Step 4 — report any remaining (unavoidable) conflicts.

    Multi-group support: avoid_group "A,B" conflicts with any team
    in group A or group B.
    """
    assert n >= 2 and n % 2 == 0, f"n must be even >= 2, got {n}"
    assert len(teams) == n, f"Expected {n} teams, got {len(teams)}"

    by_seed = {t.seed: t for t in teams}
    half = n // 2

    # Step 1: Standard half-split
    matchups_by_top_seed = {}
    for i in range(1, half + 1):
        matchups_by_top_seed[i] = (by_seed[i], by_seed[i + half])

    # Step 2: Order by bracket fold
    if half == 1:
        fold_order = [1]
    else:
        fold_order = bracket_fold_positions(half)

    ordered_pairs = [matchups_by_top_seed[s] for s in fold_order]

    # Step 3: Resolve conflicts within bracket quarters.
    # Quarter size = n_matches / 4 (minimum 2 so there's room to swap).
    num_matches = len(ordered_pairs)
    quarter_size = max(2, num_matches // 4)

    resolved_pairs: List[Tuple[TeamSeed, TeamSeed]] = []
    for start in range(0, num_matches, quarter_size):
        quarter = ordered_pairs[start:start + quarter_size]
        resolved_pairs.extend(_resolve_quarter_conflicts(quarter))

    # Step 4: Build result with remaining (unavoidable) conflicts
    seed_pairs: List[Tuple[int, int]] = []
    team_id_pairs: List[Tuple[int, int]] = []
    name_pairs: List[Tuple[str, str]] = []
    display_name_pairs: List[Tuple[Optional[str], Optional[str]]] = []
    conflicts: List[PairingConflict] = []

    for a, b in resolved_pairs:
        seed_pairs.append((a.seed, b.seed))
        team_id_pairs.append((a.team_id, b.team_id))
        name_pairs.append((a.name or "", b.name or ""))
        display_name_pairs.append((a.display_name, b.display_name))

        shared = _groups_conflict(a.avoid_group, b.avoid_group)
        if shared:
            conflicts.append(PairingConflict(
                seed_a=a.seed,
                seed_b=b.seed,
                group=shared,
                reason=(
                    f"Unavoidable conflict: seed {a.seed} and seed {b.seed} "
                    f"share avoid group '{shared}'"
                ),
            ))

    return PairingResult(
        pairs=seed_pairs,
        team_id_pairs=team_id_pairs,
        conflicts=conflicts,
        name_pairs=name_pairs,
        display_name_pairs=display_name_pairs,
    )
