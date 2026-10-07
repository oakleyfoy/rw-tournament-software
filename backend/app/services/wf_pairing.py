"""
WF Round 1 Pairing — half-split matchups in bracket-fold order,
with Who Knows Who conflict resolution.

Conflict source:
- Pairwise mode: unordered team-id pairs from TeamAvoidEdge (RW-OS WKW + manual).
- Legacy mode: shared avoid_group letters on TeamSeed.

Pipeline (never reorder bracket slots; only swap bottom-half opponents):

1. Build the canonical draw — half-split pairs ordered by
   ``_wf_r1_top_half_fold_order`` (tops fixed in bracket slots).
2. Resolve WKWK on WF Round 1: swap bottoms with other bottoms at the same
   rating anywhere in the round until stable (clears direct opponent conflicts).
3. WF Round 2 outlook (optional refinement): same-rating bottom swaps that keep
   Round 1 clean but reduce WKKW clustering within each consecutive **pod of
   four** R1 matches (slots 1–4, 5–8, … — two WF R2 feeder pairs per pod).

Unknown ratings may swap only with each other.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

AvoidPairSet = Set[Tuple[int, int]]


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


# ── Avoid helpers ─────────────────────────────────────────────────────


def _ordered_ids(left: int, right: int) -> Tuple[int, int]:
    return (left, right) if left < right else (right, left)


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


def _pair_conflict_label(
    a: TeamSeed,
    b: TeamSeed,
    avoid_pairs: Optional[AvoidPairSet],
) -> Optional[str]:
    """Return a conflict label when A and B should avoid each other."""
    if avoid_pairs is not None:
        if _ordered_ids(a.team_id, b.team_id) in avoid_pairs:
            return "wkw"
        return None
    return _groups_conflict(a.avoid_group, b.avoid_group)


def _same_level_rating(r_a: Optional[float], r_b: Optional[float]) -> bool:
    """True if two ratings qualify as the same Level for WKKW-only swaps."""
    if r_a is None and r_b is None:
        return True
    if r_a is None or r_b is None:
        return False
    return math.isclose(r_a, r_b, rel_tol=0.0, abs_tol=1e-9)


def _avoid_atoms(team: TeamSeed) -> Set[str]:
    """Lowercase atomic letters from avoid_group (comma-split). Used for WKKW pod scoring."""
    ag = team.avoid_group
    if not ag:
        return set()
    return {x.strip().lower() for x in ag.split(",") if x.strip()}


def _pair_union_atoms(match: Tuple[TeamSeed, TeamSeed]) -> Set[str]:
    a, b = match
    return _avoid_atoms(a) | _avoid_atoms(b)


def _match_team_ids(match: Tuple[TeamSeed, TeamSeed]) -> Set[int]:
    return {match[0].team_id, match[1].team_id}


def _crossing_edge_count(
    match_a: Tuple[TeamSeed, TeamSeed],
    match_b: Tuple[TeamSeed, TeamSeed],
    avoid_pairs: AvoidPairSet,
) -> int:
    """Count WKW edges with one endpoint in each R1 match (faithful pairwise pod metric)."""
    left = _match_team_ids(match_a)
    right = _match_team_ids(match_b)
    count = 0
    for team_a in left:
        for team_b in right:
            if _ordered_ids(team_a, team_b) in avoid_pairs:
                count += 1
    return count


def _wf_r2_pod_of_four_penalty(
    pairs: List[Tuple[TeamSeed, TeamSeed]],
    avoid_pairs: Optional[AvoidPairSet] = None,
) -> int:
    """Penalty when WKKW touches multiple R1 matches inside the same pod of four.

    Letter mode: shared avoid-group atoms across matches in the pod.
    Pairwise mode: count of effective edges that cross between distinct R1 matches
    in the pod (does not invent clique/group semantics).
    """
    pen = 0
    n = len(pairs)
    for block_start in range(0, n, 4):
        block_end = min(block_start + 4, n)
        for i in range(block_start, block_end):
            for j in range(i + 1, block_end):
                if avoid_pairs is not None:
                    pen += _crossing_edge_count(pairs[i], pairs[j], avoid_pairs)
                else:
                    ga = _pair_union_atoms(pairs[i])
                    gb = _pair_union_atoms(pairs[j])
                    pen += len(ga & gb)
    return pen


def _wf_r1_draw_ordered_pairs(by_seed: Dict[int, TeamSeed], half: int) -> List[Tuple[TeamSeed, TeamSeed]]:
    """Canonical WF R1 draw: half-split with bracket-safe match-list order (tops fixed)."""
    matchups_by_top_seed = {i: (by_seed[i], by_seed[i + half]) for i in range(1, half + 1)}
    fold_order = _wf_r1_top_half_fold_order(half)
    return [matchups_by_top_seed[s] for s in fold_order]


def _pair_clean_opponents(
    match: Tuple[TeamSeed, TeamSeed],
    avoid_pairs: Optional[AvoidPairSet] = None,
) -> bool:
    a, b = match
    return _pair_conflict_label(a, b, avoid_pairs) is None


def _try_bottom_swap(
    pairs: List[Tuple[TeamSeed, TeamSeed]],
    i: int,
    j: int,
    avoid_pairs: Optional[AvoidPairSet] = None,
) -> Optional[List[Tuple[TeamSeed, TeamSeed]]]:
    """If swapping bottoms between slots i and j keeps both pairs WKWK-clean, return new list."""
    if i == j:
        return None
    a_i, b_i = pairs[i]
    a_j, b_j = pairs[j]
    if not _same_level_rating(b_i.rating, b_j.rating):
        return None
    if _pair_conflict_label(a_i, b_j, avoid_pairs):
        return None
    if _pair_conflict_label(a_j, b_i, avoid_pairs):
        return None
    out = list(pairs)
    out[i] = (a_i, b_j)
    out[j] = (a_j, b_i)
    return out


def _resolve_wkk_r1_bottom_swaps(
    pairs: List[Tuple[TeamSeed, TeamSeed]],
    avoid_pairs: Optional[AvoidPairSet] = None,
) -> List[Tuple[TeamSeed, TeamSeed]]:
    """Clear WF R1 opponent WKWK conflicts via same-rating bottom swaps (whole round)."""
    result = list(pairs)
    n = len(result)
    max_rounds = max(1, n * n * n)
    for _ in range(max_rounds):
        progressed = False
        for i in range(n):
            if _pair_clean_opponents(result[i], avoid_pairs):
                continue
            for j in range(n):
                trial = _try_bottom_swap(result, i, j, avoid_pairs)
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
    avoid_pairs: Optional[AvoidPairSet] = None,
) -> List[Tuple[TeamSeed, TeamSeed]]:
    """Spread WKKW across pods using same-rated bottom swaps when possible.

    Minimizes ``_wf_r2_pod_of_four_penalty`` without introducing R1 opponent WKWK hits.
    """
    result = list(pairs)
    n = len(result)
    max_rounds = max(1, n * n * n)
    for _ in range(max_rounds):
        base_pen = _wf_r2_pod_of_four_penalty(result, avoid_pairs)
        best: Optional[Tuple[int, int, int]] = None  # (penalty, i, j)

        for i in range(n):
            for j in range(n):
                trial = _try_bottom_swap(result, i, j, avoid_pairs)
                if trial is None:
                    continue
                if not all(_pair_clean_opponents(trial[k], avoid_pairs) for k in range(n)):
                    continue
                pen_trial = _wf_r2_pod_of_four_penalty(trial, avoid_pairs)
                if pen_trial >= base_pen:
                    continue
                cand = (pen_trial, i, j)
                if best is None or cand < best:
                    best = cand

        if best is None:
            break
        _, bi, bj = best
        trial = _try_bottom_swap(result, bi, bj, avoid_pairs)
        assert trial is not None
        result = trial

    return result


# ── Main entry point ─────────────────────────────────────────────────


def build_wf_r1_pairings(
    teams: List[TeamSeed],
    n: int,
    *,
    avoid_pairs: Optional[AvoidPairSet] = None,
) -> PairingResult:
    """Build WF R1 pairings for *n* teams.

    Step 1 — Canonical draw: half-split, bracket-safe match order (tops fixed).
    Step 2 — WKKW on WF Round 1: swap bottoms with same-rated bottoms anywhere in the round.
    Step 3 — WF Round 2 outlook: optional swaps that keep Round 1 clean but reduce WKKW
             clustering within each consecutive pod of four R1 slots (1–4, 5–8, …).

    Step 4 — report any remaining (unavoidable) conflicts.

    When *avoid_pairs* is provided, conflict(A,B) is true iff the unordered team-id pair
    is in that set (pairwise RW-OS WKW). Otherwise legacy avoid_group letter overlap is used.
    """
    assert n >= 2 and n % 2 == 0, f"n must be even >= 2, got {n}"
    assert len(teams) == n, f"Expected {n} teams, got {len(teams)}"

    by_seed = {t.seed: t for t in teams}
    half = n // 2

    ordered_pairs = _wf_r1_draw_ordered_pairs(by_seed, half)
    resolved_r1 = _resolve_wkk_r1_bottom_swaps(ordered_pairs, avoid_pairs)
    resolved_pairs = _optimize_wf_r2_adjacency_swaps(resolved_r1, avoid_pairs)

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

        shared = _pair_conflict_label(a, b, avoid_pairs)
        if shared:
            if avoid_pairs is not None:
                reason = f"Unavoidable conflict: seed {a.seed} and seed {b.seed} are connected by Who Knows Who"
            else:
                reason = f"Unavoidable conflict: seed {a.seed} and seed {b.seed} share avoid group '{shared}'"
            conflicts.append(
                PairingConflict(
                    seed_a=a.seed,
                    seed_b=b.seed,
                    group=shared,
                    reason=reason,
                )
            )

    return PairingResult(
        pairs=seed_pairs,
        team_id_pairs=team_id_pairs,
        conflicts=conflicts,
        name_pairs=name_pairs,
        display_name_pairs=display_name_pairs,
    )
