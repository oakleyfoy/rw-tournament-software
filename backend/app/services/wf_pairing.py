"""
WF Round 1 Pairing — half-split matchups in bracket-fold order,
with Who Knows Who (avoid_group) conflict resolution.

Pipeline (never reorder bracket slots; only swap bottom-half opponents):

1. Build the canonical draw — half-split pairs ordered by
   ``_wf_r1_top_half_fold_order`` (tops fixed in bracket slots).
2. Resolve WKWK on WF Round 1: swap bottoms with other bottoms at the same
   rating anywhere in the round until stable (clears direct opponent conflicts).
3. WF Round 2 outlook (optional refinement): same-rating bottom swaps that keep
   Round 1 clean but reduce shared-letter overlap across consecutive R1 pairs that
   feed one WF R2 match each (seq 1+2, 3+4, …).

Unknown ratings may swap only with each other.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple


@dataclass
class TeamSeed:
    """Lightweight struct for pairing input."""
    seed: int
    team_id: int
    avoid_group: Optional[str] = None
    display_name: Optional[str] = None
    name: Optional[str] = None
    rating: Optional[float] = None  # import "Level" — used only for WKWK swap eligibility


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


def _wf_r1_top_half_fold_order(half: int) -> List[int]:
    """Permutation of seeds 1..half for WF R1 *match list* order (half-split opponents).

    Power-of-two half sizes use ``bracket_fold_positions(half)`` (same as standard brackets).

    Non-power-of-two halves use outside-in order ``[1, half, 2, half-1, …]`` so that
    with sequential WF R2 wiring (winners of R1 slots 1+2, 3+4, … meet), feeders
    mirror the bracket (e.g. half=10 → (1 vs 11) then (10 vs 20); those winners
    meet in WF R2).
    """
    if half <= 1:
        return [1] if half == 1 else []
    if half & (half - 1) == 0:
        return bracket_fold_positions(half)
    out: List[int] = []
    lo, hi = 1, half
    while lo <= hi:
        out.append(lo)
        if lo < hi:
            out.append(hi)
        lo += 1
        hi -= 1
    return out


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


def _same_level_rating(r_a: Optional[float], r_b: Optional[float]) -> bool:
    """True if two ratings qualify as the same Level for WKKW-only swaps."""
    if r_a is None and r_b is None:
        return True
    if r_a is None or r_b is None:
        return False
    return math.isclose(r_a, r_b, rel_tol=0.0, abs_tol=1e-9)


def _avoid_atoms(team: TeamSeed) -> Set[str]:
    """Lowercase atomic letters from avoid_group (comma-split). Used for WF R2 adjacency."""
    ag = team.avoid_group
    if not ag:
        return set()
    return {x.strip().lower() for x in ag.split(",") if x.strip()}


def _pair_union_atoms(match: Tuple[TeamSeed, TeamSeed]) -> Set[str]:
    a, b = match
    return _avoid_atoms(a) | _avoid_atoms(b)


def _wf_r2_adjacency_penalty(pairs: List[Tuple[TeamSeed, TeamSeed]]) -> int:
    """Sum shared-letter overlap across consecutive WF R2 feeders (R1 slots 1+2, 3+4, …)."""
    pen = 0
    for k in range(0, len(pairs) - 1, 2):
        ga = _pair_union_atoms(pairs[k])
        gb = _pair_union_atoms(pairs[k + 1])
        pen += len(ga & gb)
    return pen


def _wf_r1_draw_ordered_pairs(by_seed: Dict[int, TeamSeed], half: int) -> List[Tuple[TeamSeed, TeamSeed]]:
    """Canonical WF R1 draw: half-split with bracket-safe match-list order (tops fixed)."""
    matchups_by_top_seed = {
        i: (by_seed[i], by_seed[i + half]) for i in range(1, half + 1)
    }
    fold_order = _wf_r1_top_half_fold_order(half)
    return [matchups_by_top_seed[s] for s in fold_order]


def _pair_clean_opponents(match: Tuple[TeamSeed, TeamSeed]) -> bool:
    a, b = match
    return _groups_conflict(a.avoid_group, b.avoid_group) is None


def _try_bottom_swap(
    pairs: List[Tuple[TeamSeed, TeamSeed]], i: int, j: int
) -> Optional[List[Tuple[TeamSeed, TeamSeed]]]:
    """If swapping bottoms between slots i and j keeps both pairs WKWK-clean, return new list."""
    if i == j:
        return None
    a_i, b_i = pairs[i]
    a_j, b_j = pairs[j]
    if not _same_level_rating(b_i.rating, b_j.rating):
        return None
    if _groups_conflict(a_i.avoid_group, b_j.avoid_group):
        return None
    if _groups_conflict(a_j.avoid_group, b_i.avoid_group):
        return None
    out = list(pairs)
    out[i] = (a_i, b_j)
    out[j] = (a_j, b_i)
    return out


def _resolve_wkk_r1_bottom_swaps(
    pairs: List[Tuple[TeamSeed, TeamSeed]],
) -> List[Tuple[TeamSeed, TeamSeed]]:
    """Clear WF R1 opponent WKWK conflicts via same-rating bottom swaps (whole round)."""
    result = list(pairs)
    n = len(result)
    max_rounds = max(1, n * n * n)
    for _ in range(max_rounds):
        progressed = False
        for i in range(n):
            if _pair_clean_opponents(result[i]):
                continue
            for j in range(n):
                trial = _try_bottom_swap(result, i, j)
                if trial is None:
                    continue
                result = trial
                progressed = True
                break
            if progressed:
                break
        if not progressed:
            break
    return result


def _optimize_wf_r2_adjacency_swaps(
    pairs: List[Tuple[TeamSeed, TeamSeed]],
) -> List[Tuple[TeamSeed, TeamSeed]]:
    """Reduce WF R2 feeder overlap using same-rating bottom swaps; never introduces R1 WKKW hits."""
    result = list(pairs)
    n = len(result)
    max_rounds = max(1, n * n * n)
    for _ in range(max_rounds):
        base_pen = _wf_r2_adjacency_penalty(result)
        best: Optional[Tuple[int, int, int]] = None  # (penalty, i, j)

        for i in range(n):
            for j in range(n):
                trial = _try_bottom_swap(result, i, j)
                if trial is None:
                    continue
                if not all(_pair_clean_opponents(trial[k]) for k in range(n)):
                    continue
                pen_trial = _wf_r2_adjacency_penalty(trial)
                if pen_trial >= base_pen:
                    continue
                cand = (pen_trial, i, j)
                if best is None or cand < best:
                    best = cand

        if best is None:
            break
        _, bi, bj = best
        trial = _try_bottom_swap(result, bi, bj)
        assert trial is not None
        result = trial

    return result


# ── Main entry point ─────────────────────────────────────────────────


def build_wf_r1_pairings(teams: List[TeamSeed], n: int) -> PairingResult:
    """Build WF R1 pairings for *n* teams.

    Step 1 — Canonical draw: half-split, bracket-safe match order (tops fixed).
    Step 2 — WKKW on WF Round 1: swap bottoms with same-rated bottoms anywhere in the round.
    Step 3 — WF Round 2 outlook: optional swaps that keep Round 1 clean but reduce letter overlap
             across consecutive R1 pairs feeding each WF R2 slot.

    Step 4 — report any remaining (unavoidable) conflicts.

    Multi-group support: avoid_group "A,B" conflicts with any team
    in group A or group B.
    """
    assert n >= 2 and n % 2 == 0, f"n must be even >= 2, got {n}"
    assert len(teams) == n, f"Expected {n} teams, got {len(teams)}"

    by_seed = {t.seed: t for t in teams}
    half = n // 2

    ordered_pairs = _wf_r1_draw_ordered_pairs(by_seed, half)
    resolved_r1 = _resolve_wkk_r1_bottom_swaps(ordered_pairs)
    resolved_pairs = _optimize_wf_r2_adjacency_swaps(resolved_r1)

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
