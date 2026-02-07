"""
Draw Plan Rules — Phase 1 Allowed Matrix (Single Source of Truth)

This module defines all Phase 1 validation rules for draw plan templates.
All other modules must import from here. Do NOT duplicate these rules elsewhere.
"""

from typing import Dict, FrozenSet, Literal, Optional, Tuple

# =============================================================================
# Phase 1 Allowed Matrix
# =============================================================================

# Template families
TemplateFamily = Literal["RR_ONLY", "WF_TO_POOLS_DYNAMIC", "WF_TO_BRACKETS_8"]

# Allowed team counts per family
ALLOWED_TEAM_COUNTS: Dict[TemplateFamily, FrozenSet[int]] = {
    "RR_ONLY": frozenset({4, 6}),
    "WF_TO_POOLS_DYNAMIC": frozenset({8, 10, 12, 16, 20, 24, 28}),
    "WF_TO_BRACKETS_8": frozenset({32}),
}

# All Phase 1 supported team counts (union of all families)
PHASE1_SUPPORTED_TEAM_COUNTS: FrozenSet[int] = frozenset().union(
    *ALLOWED_TEAM_COUNTS.values()
)

# Unsupported in Phase 1 (Phase 2 candidates)
PHASE2_TEAM_COUNTS: FrozenSet[int] = frozenset({14, 18, 22, 26, 30})


# =============================================================================
# Waterfall Rounds Rules
# =============================================================================

def required_wf_rounds(family: TemplateFamily, team_count: int) -> int:
    """
    Return the required number of waterfall rounds for a given family and team count.
    
    Rules:
    - RR_ONLY: always 0
    - WF_TO_POOLS_DYNAMIC: 1 for 8/10 teams, 2 for 12+ teams
    - WF_TO_BRACKETS_8: always 2
    """
    if family == "RR_ONLY":
        return 0
    elif family == "WF_TO_POOLS_DYNAMIC":
        return 1 if team_count in (8, 10) else 2
    elif family == "WF_TO_BRACKETS_8":
        return 2
    return 0


# =============================================================================
# Pool Sizing Rules
# =============================================================================

def pool_config(team_count: int) -> Tuple[int, int]:
    """
    Return (pools_count, teams_per_pool) for WF_TO_POOLS_DYNAMIC.
    
    Rules:
    - 10 teams: 2 pools of 5
    - All others: n/4 pools of 4
    """
    if team_count == 10:
        return (2, 5)
    else:
        return (team_count // 4, 4)


def rr_matches_per_pool(teams_per_pool: int) -> int:
    """Return number of RR matches in a pool: C(n, 2) = n*(n-1)/2."""
    return (teams_per_pool * (teams_per_pool - 1)) // 2


def rr_round_count(teams_per_pool: int) -> int:
    """
    Return number of RR rounds for a pool of n teams.
    Even n: n-1 rounds. Odd n: n rounds (with BYE).
    """
    if teams_per_pool % 2 == 0:
        return teams_per_pool - 1
    return teams_per_pool


def rr_pairings_by_round(teams_per_pool: int) -> list[tuple[int, int, int, int]]:
    """
    Round-robin pairings. Returns list of (round_index, sequence_in_round, idx_a, idx_b).
    idx_a, idx_b are 0-based pool positions (seeds 1-4 in pool = indices 0-3).

    Pool size 4 uses exact preset order (1v2 last):
    - Round 1: 1v4, 2v3  → (0,3), (1,2)
    - Round 2: 1v3, 2v4  → (0,2), (1,3)
    - Round 3: 1v2, 3v4  → (0,1), (2,3)

    Pool size != 4: circle method.
    """
    if teams_per_pool == 4:
        # Exact preset: R1: 1v4, 2v3; R2: 1v3, 2v4; R3: 1v2, 3v4
        return [
            (1, 1, 0, 3),
            (1, 2, 1, 2),
            (2, 1, 0, 2),
            (2, 2, 1, 3),
            (3, 1, 0, 1),
            (3, 2, 2, 3),
        ]

    n = teams_per_pool
    n2 = n + 1 if n % 2 == 1 else n  # Add BYE for odd n
    half = n2 // 2
    rounds_count = n2 - 1

    # positions: 0..n2-1. For odd n, position n is BYE (index n in 0..n)
    # Circle: fix 0, rotate the rest. Pair (i, n2-1-i); skip if either is BYE.
    bye_idx = n if n % 2 == 1 else -1  # BYE at index n when we have n+1 positions

    result: list[tuple[int, int, int, int]] = []
    positions = list(range(n2))  # 0..n for odd (n=BYE), 0..n-1 for even

    for round_num in range(1, rounds_count + 1):
        seq = 0
        for i in range(half):
            j = n2 - 1 - i
            a, b = positions[i], positions[j]
            if a == bye_idx or b == bye_idx:
                continue
            seq += 1
            result.append((round_num, seq, min(a, b), max(a, b)))
        # Rotate: keep 0, move last to second, shift others
        positions = [positions[0]] + [positions[-1]] + positions[1:-1]

    return result


# =============================================================================
# Validation Helpers
# =============================================================================

def get_valid_family_for_team_count(team_count: int) -> Optional[TemplateFamily]:
    """
    Return the valid template family for a given team count, or None if unsupported.
    
    Priority order (most specific first):
    1. WF_TO_BRACKETS_8 (32 only)
    2. WF_TO_POOLS_DYNAMIC (8, 10, 12, 16, 20, 24, 28)
    3. RR_ONLY (4, 6)
    """
    if team_count in ALLOWED_TEAM_COUNTS["WF_TO_BRACKETS_8"]:
        return "WF_TO_BRACKETS_8"
    if team_count in ALLOWED_TEAM_COUNTS["WF_TO_POOLS_DYNAMIC"]:
        return "WF_TO_POOLS_DYNAMIC"
    if team_count in ALLOWED_TEAM_COUNTS["RR_ONLY"]:
        return "RR_ONLY"
    return None


def is_team_count_valid_for_family(family: TemplateFamily, team_count: int) -> bool:
    """Check if a team count is valid for a given family."""
    return team_count in ALLOWED_TEAM_COUNTS.get(family, frozenset())


def validate_template_config(
    template_key: str,
    team_count: int,
    wf_rounds: int,
) -> Optional[str]:
    """
    Validate a template configuration.
    
    Returns None if valid, or an error message string if invalid.
    """
    # Normalize template key
    key = template_key.strip().upper().replace(" ", "_")
    
    # Check if this is a known family
    if key not in ALLOWED_TEAM_COUNTS:
        # Check for legacy templates
        if key == "WF_TO_POOLS_4":
            if team_count != 16:
                return f"WF_TO_POOLS_4 requires exactly 16 teams, got {team_count}"
            if wf_rounds != 2:
                return f"WF_TO_POOLS_4 requires 2 waterfall rounds, got {wf_rounds}"
            return None  # Legacy template is valid
        return f"Unknown template: {template_key}"
    
    family: TemplateFamily = key  # type: ignore
    
    # Validate team count
    if not is_team_count_valid_for_family(family, team_count):
        allowed = sorted(ALLOWED_TEAM_COUNTS[family])
        return f"{family} requires team_count in {{{','.join(map(str, allowed))}}}, got {team_count}"
    
    # Validate waterfall rounds
    expected_wf = required_wf_rounds(family, team_count)
    if wf_rounds != expected_wf:
        return f"{family} with {team_count} teams requires waterfall_rounds={expected_wf}, got {wf_rounds}"
    
    return None


# =============================================================================
# Inventory Calculation Helpers
# =============================================================================

def calculate_wf_matches(team_count: int, wf_rounds: int) -> int:
    """Calculate total waterfall matches: (n/2) * rounds."""
    return (team_count // 2) * wf_rounds


def calculate_rr_matches_for_pools(team_count: int) -> int:
    """Calculate total RR matches for WF_TO_POOLS_DYNAMIC."""
    pools_count, teams_per_pool = pool_config(team_count)
    rr_per_pool = rr_matches_per_pool(teams_per_pool)
    return pools_count * rr_per_pool


def calculate_rr_only_matches(team_count: int) -> int:
    """Calculate total RR matches for RR_ONLY: C(n, 2)."""
    return (team_count * (team_count - 1)) // 2
