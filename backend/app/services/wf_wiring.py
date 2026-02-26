"""
WF Round 2 Wiring Optimizer — avoid-group-aware, deterministic.

Optimizes WF R1 -> R2 source wiring within blocks of 4 matches,
evaluating all 3 possible pairing patterns to minimize potential
avoid_group conflicts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Set, Tuple


@dataclass
class WiringWarning:
    block_index: int
    r1_match_codes: List[str]
    overlapping_groups: List[str]
    message: str


@dataclass
class WiringPlan:
    """Ordered R2 source wiring with potential-conflict warnings."""

    pairs: List[Tuple[int, int]]  # (source_match_a_id, source_match_b_id)
    warnings: List[WiringWarning] = field(default_factory=list)


def groups_for_r1_match(match: Any, team_by_id: Dict[int, Any]) -> Set[str]:
    """Return set of non-null avoid_group values for the two teams in an R1 match."""
    groups: Set[str] = set()
    for tid in (getattr(match, "team_a_id", None), getattr(match, "team_b_id", None)):
        if tid is not None:
            team = team_by_id.get(tid)
            if team:
                ag = getattr(team, "avoid_group", None)
                if ag:
                    groups.add(ag)
    return groups


# The 3 ways to partition indices [0,1,2,3] into 2 unordered pairs.
_PATTERNS_4: List[Tuple[Tuple[int, int], Tuple[int, int]]] = [
    ((0, 3), (1, 2)),
    ((0, 2), (1, 3)),
    ((0, 1), (2, 3)),
]


def best_pairing_for_block(
    r1_matches_block: List[Any],
    team_by_id: Dict[int, Any],
) -> List[Tuple[Any, Any]]:
    """
    For a block of (up to 4) R1 matches, evaluate all pairing patterns
    and pick the one with minimum total avoid_group overlap.
    Deterministic tie-break: first pattern in _PATTERNS_4 wins.
    """
    n = len(r1_matches_block)
    if n == 2:
        return [(r1_matches_block[0], r1_matches_block[1])]
    if n < 2:
        return []
    assert n == 4, f"Block must have 2 or 4 matches, got {n}"

    match_groups = {
        m.id: groups_for_r1_match(m, team_by_id) for m in r1_matches_block
    }

    best_score: float = float("inf")
    best_pairs: List[Tuple[Any, Any]] = []

    for pattern in _PATTERNS_4:
        total = 0
        pairs: List[Tuple[Any, Any]] = []
        for i_a, i_b in pattern:
            m_a = r1_matches_block[i_a]
            m_b = r1_matches_block[i_b]
            pairs.append((m_a, m_b))
            g_a = match_groups.get(m_a.id, set())
            g_b = match_groups.get(m_b.id, set())
            total += len(g_a & g_b)

        if total < best_score:
            best_score = total
            best_pairs = pairs

    return best_pairs


def build_wf_r2_wiring(
    r1_matches_ordered: List[Any],
    team_by_id: Dict[int, Any],
    block_size: int = 4,
) -> WiringPlan:
    """
    Build optimized WF R2 wiring from ordered WF R1 matches.

    Splits into blocks of block_size, optimizes each block independently,
    returns ordered (source_a_id, source_b_id) pairs for filling R2
    sequences and warnings for unavoidable overlaps.
    """
    all_pairs: List[Tuple[int, int]] = []
    warnings: List[WiringWarning] = []

    blocks = [
        r1_matches_ordered[i : i + block_size]
        for i in range(0, len(r1_matches_ordered), block_size)
    ]

    for block_idx, block in enumerate(blocks):
        block_pairs = best_pairing_for_block(block, team_by_id)

        match_groups = {
            m.id: groups_for_r1_match(m, team_by_id) for m in block
        }

        block_overlaps: Set[str] = set()
        for m_a, m_b in block_pairs:
            g_a = match_groups.get(m_a.id, set())
            g_b = match_groups.get(m_b.id, set())
            block_overlaps |= (g_a & g_b)

        for m_a, m_b in block_pairs:
            all_pairs.append((m_a.id, m_b.id))

        if block_overlaps:
            r1_codes = [getattr(m, "match_code", "?") for m in block]
            warnings.append(WiringWarning(
                block_index=block_idx,
                r1_match_codes=r1_codes,
                overlapping_groups=sorted(block_overlaps),
                message=(
                    f"W_WF_R2_AVOID_GROUP_POTENTIAL_CONFLICT: "
                    f"block {block_idx} ({', '.join(r1_codes)}): "
                    f"potential overlap on group(s) {sorted(block_overlaps)}"
                ),
            ))

    return WiringPlan(pairs=all_pairs, warnings=warnings)
