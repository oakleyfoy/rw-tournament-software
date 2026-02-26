"""
Draw Plan Engine — Single source of truth for match inventory and generation.

This module is the authoritative engine for:
1. Schedule Builder inventory calculations
2. Match generation during "Build Schedule"

All template logic lives here. No other module should contain template math.
Validation rules are imported from draw_plan_rules.py (single source of truth).
"""

from dataclasses import dataclass, field
from typing import List, Literal, Optional, Tuple
import logging

# Import Phase 1 rules from the single source of truth
from app.services.draw_plan_rules import (
    ALLOWED_TEAM_COUNTS,
    PHASE1_SUPPORTED_TEAM_COUNTS,
    required_wf_rounds,
    pool_config,
    rr_matches_per_pool,
    rr_pairings_by_round,
    calculate_wf_matches,
    calculate_rr_matches_for_pools,
    calculate_rr_only_matches,
)
from app.services.wf_pairing import PairingResult, TeamSeed, build_wf_r1_pairings
from app.services.wf_wiring import WiringPlan, build_wf_r2_wiring
from app.utils.rr_wiring import wire_rr_match_placeholders

logger = logging.getLogger(__name__)


def _get_wf_r1_pairing(
    session,
    event_id: int,
    linked_team_ids: List[int],
    n: int,
) -> Optional[PairingResult]:
    """
    If all n teams are linked and have seeds, run the avoid-group-aware
    pairing solver. Returns None if teams aren't fully available.
    """
    if len(linked_team_ids) < n:
        return None

    from app.models.team import Team
    from sqlmodel import select

    teams = session.exec(
        select(Team).where(Team.event_id == event_id)
    ).all()

    if len(teams) < n:
        return None

    by_id = {t.id: t for t in teams}
    seed_teams: List[TeamSeed] = []
    for tid in linked_team_ids[:n]:
        t = by_id.get(tid)
        if not t or t.seed is None:
            return None
        seed_teams.append(TeamSeed(
            seed=t.seed,
            team_id=t.id,
            avoid_group=getattr(t, "avoid_group", None),
            display_name=getattr(t, "display_name", None),
        ))

    seed_teams.sort(key=lambda x: x.seed)
    if [t.seed for t in seed_teams] != list(range(1, n + 1)):
        return None

    return build_wf_r1_pairings(seed_teams, n)


def _get_wf_r2_wiring(session, event_id: int, r1_matches: list) -> WiringPlan:
    """
    Load teams for the event and compute WF R2 wiring.

    Uses block_size=2 so sequential R1 pairs (seq 1+2, 3+4, ...)
    advance into the same R2 match.
    """
    from app.models.team import Team
    from sqlmodel import select

    try:
        teams = session.exec(
            select(Team).where(Team.event_id == event_id)
        ).all()
        team_by_id = {t.id: t for t in teams}
    except Exception:
        team_by_id = {}

    r1_sorted = sorted(
        r1_matches,
        key=lambda m: (getattr(m, "sequence_in_round", 0) or 0, m.id or 0),
    )
    return build_wf_r2_wiring(r1_sorted, team_by_id, block_size=2)


# -----------------------------------------------------------------------------
# Constants
# -----------------------------------------------------------------------------

# Bracket match counts by guarantee level (for 8-team single-elimination + consolation)
# V1: G5 = 12 (7 main + 2 Tier1 consolation + 1 Tier2 + 2 placement), G4 = 9 (7 main + 2 Tier1)
BRACKET_MATCHES_G4 = 9   # 7 main + 2 consolation tier1
BRACKET_MATCHES_G5 = 12  # 7 main + 2 consolation tier1 + 1 tier2 + 2 placement

# Division display name mapping (bracket label -> user-facing name)
DIVISION_DISPLAY_NAMES = {
    "WW": "Division I",
    "WL": "Division II",
    "LW": "Division III",
    "LL": "Division IV",
}

# Supported event families (includes legacy WF_TO_POOLS_4)
EventFamily = Literal["RR_ONLY", "WF_TO_POOLS_4", "WF_TO_POOLS_DYNAMIC", "WF_TO_BRACKETS_8", "UNSUPPORTED"]

# Re-export for backwards compatibility
WF_TO_POOLS_DYNAMIC_TEAM_COUNTS = ALLOWED_TEAM_COUNTS["WF_TO_POOLS_DYNAMIC"]


# -----------------------------------------------------------------------------
# Data Models
# -----------------------------------------------------------------------------

@dataclass
class DrawPlanSpec:
    """Canonical input for draw plan calculations."""
    event_id: int
    event_name: str
    division: Optional[str]
    team_count: int
    template_type: str        # Raw from DB/UI
    template_key: str         # Normalized (uppercase, underscores)
    guarantee: int            # 4 or 5
    waterfall_rounds: int
    waterfall_minutes: int
    standard_minutes: int
    tournament_id: Optional[int] = None  # Set when building from event
    event_category: Optional[str] = None  # "mixed" or "womens"

    @property
    def match_code_prefix(self) -> str:
        """Generate a unique prefix for match codes based on event. Includes event_id for uniqueness across events."""
        cat = (self.event_category or "EVT")[:3].upper()
        name = (self.event_name or "")[:3].upper().replace(" ", "") or "EVT"
        return f"{cat}_{name}_E{self.event_id}_"


@dataclass
class InventoryCounts:
    """Output of inventory calculation."""
    wf_matches: int = 0
    bracket_matches: int = 0
    rr_matches: int = 0
    total_matches: int = 0
    errors: List[str] = field(default_factory=list)
    # Stage breakdown for API response: WF, RR_POOL, BRACKET_MAIN, CONSOLATION_T1, CONSOLATION_T2, PLACEMENT
    counts_by_stage: dict = field(default_factory=dict)

    def has_errors(self) -> bool:
        return len(self.errors) > 0


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------

def normalize_template_key(s: Optional[str]) -> str:
    """Normalize template type string to canonical key."""
    return (s or "").strip().upper().replace(" ", "_")


def bracket_inventory(guarantee_matches: int) -> dict:
    """
    Return per-bracket stage breakdown for an 8-team bracket.
    Guarantee 4: BRACKET_MAIN=7, CONSOLATION_T1=2, CONSOLATION_T2=0, PLACEMENT=0, TOTAL=9
    Guarantee 5: BRACKET_MAIN=7, CONSOLATION_T1=2, CONSOLATION_T2=1, PLACEMENT=2, TOTAL=12
    """
    if guarantee_matches == 4:
        return {
            "BRACKET_MAIN": 7,
            "CONSOLATION_T1": 2,
            "CONSOLATION_T2": 0,
            "PLACEMENT": 0,
            "TOTAL": 9,
        }
    if guarantee_matches == 5:
        return {
            "BRACKET_MAIN": 7,
            "CONSOLATION_T1": 2,
            "CONSOLATION_T2": 1,
            "PLACEMENT": 2,
            "TOTAL": 12,
        }
    raise ValueError(f"guarantee_matches must be 4 or 5, got {guarantee_matches}")


def bracket_matches_for_guarantee(guarantee: int) -> int:
    """Return total matches for an 8-team bracket given guarantee level."""
    g = 5 if guarantee not in (4, 5) else guarantee
    return bracket_inventory(g)["TOTAL"]


# -----------------------------------------------------------------------------
# Validation
# -----------------------------------------------------------------------------

def validate_spec(spec: DrawPlanSpec) -> List[str]:
    """
    Validate a DrawPlanSpec and return list of errors.
    Empty list means valid.
    """
    errors: List[str] = []

    if spec.team_count is None or spec.team_count < 2:
        errors.append("team_count must be at least 2")
    elif spec.team_count % 2 != 0:
        errors.append("team_count must be even")

    if spec.guarantee not in (4, 5):
        errors.append(f"guarantee must be 4 or 5, got {spec.guarantee}")

    if spec.waterfall_rounds < 0:
        errors.append("waterfall_rounds cannot be negative")

    return errors


# -----------------------------------------------------------------------------
# Event Family Resolution
# -----------------------------------------------------------------------------

def resolve_event_family(spec: DrawPlanSpec) -> EventFamily:
    """
    Determine which event family a spec belongs to.
    Returns the family name or "UNSUPPORTED".
    """
    key = spec.template_key

    # RR_ONLY: pure round robin
    if key == "RR_ONLY":
        return "RR_ONLY"

    # WF_TO_POOLS_DYNAMIC: waterfall into pools (Phase 1)
    # Supports: 8, 10, 12, 16, 20, 24, 28 teams
    if key == "WF_TO_POOLS_DYNAMIC":
        return "WF_TO_POOLS_DYNAMIC"

    # WF_TO_POOLS_4: 16 teams, 2 WF rounds, 4 pools of 4 (legacy, deprecated)
    if key == "WF_TO_POOLS_4":
        return "WF_TO_POOLS_4"

    # WF_TO_BRACKETS_8: waterfall into K brackets of 8
    # Aliases: WF2_TO_4BRACKETS_8, WF_TO_BRACKETS_8, or pattern matching
    if key in ("WF_TO_BRACKETS_8", "WF2_TO_4BRACKETS_8"):
        return "WF_TO_BRACKETS_8"

    # Legacy CANONICAL_32 maps to WF_TO_BRACKETS_8 ONLY for 8-team events
    # (CANONICAL_32 was historically misnamed; it's an 8-team bracket)
    # For 32-team events, use WF_TO_BRACKETS_8 directly - CANONICAL_32 is unsupported
    if key == "CANONICAL_32" and spec.team_count == 8:
        return "WF_TO_BRACKETS_8"

    return "UNSUPPORTED"


# -----------------------------------------------------------------------------
# Inventory Calculation
# -----------------------------------------------------------------------------

def _compute_rr_only(spec: DrawPlanSpec) -> InventoryCounts:
    """Compute inventory for RR_ONLY family using rules module."""
    rr_matches = calculate_rr_only_matches(spec.team_count)
    return InventoryCounts(
        wf_matches=0,
        bracket_matches=0,
        rr_matches=rr_matches,
        total_matches=rr_matches,
        counts_by_stage={"RR_POOL": rr_matches},
    )


def _compute_wf_to_pools_4(spec: DrawPlanSpec) -> InventoryCounts:
    """
    Compute inventory for WF_TO_POOLS_4 family.
    Hard spec: team_count=16, wf_rounds=2, 4 pools of 4.
    """
    errors: List[str] = []

    if spec.team_count != 16:
        errors.append(f"WF_TO_POOLS_4 requires team_count=16, got {spec.team_count}")
    if spec.waterfall_rounds != 2:
        errors.append(f"WF_TO_POOLS_4 requires waterfall_rounds=2, got {spec.waterfall_rounds}")

    if errors:
        return InventoryCounts(errors=errors)

    # 8 matches per WF round × 2 rounds = 16
    wf_matches = 8 * 2

    # 4 pools of 4: each pool has C(4,2)=6 RR matches
    rr_matches = 4 * 6

    return InventoryCounts(
        wf_matches=wf_matches,
        bracket_matches=0,
        rr_matches=rr_matches,
        total_matches=wf_matches + rr_matches,
        counts_by_stage={"WF": wf_matches, "RR_POOL": rr_matches},
    )


def _compute_wf_to_pools_dynamic(spec: DrawPlanSpec) -> InventoryCounts:
    """
    Compute inventory for WF_TO_POOLS_DYNAMIC family.
    
    Uses rules from draw_plan_rules.py (single source of truth).
    """
    errors: List[str] = []
    n = spec.team_count
    wf_rounds = spec.waterfall_rounds

    # Validate team count using rules module
    if n not in WF_TO_POOLS_DYNAMIC_TEAM_COUNTS:
        allowed = sorted(WF_TO_POOLS_DYNAMIC_TEAM_COUNTS)
        errors.append(
            f"WF_TO_POOLS_DYNAMIC supports team_count in {{{','.join(map(str, allowed))}}}, got {n}"
        )
        return InventoryCounts(errors=errors)

    # Validate waterfall rounds using rules module
    expected_wf_rounds = required_wf_rounds("WF_TO_POOLS_DYNAMIC", n)
    if wf_rounds != expected_wf_rounds:
        errors.append(
            f"WF_TO_POOLS_DYNAMIC with {n} teams requires waterfall_rounds={expected_wf_rounds}, got {wf_rounds}"
        )
        return InventoryCounts(errors=errors)

    # Calculate using rules module
    wf_matches = calculate_wf_matches(n, wf_rounds)
    rr_matches = calculate_rr_matches_for_pools(n)

    return InventoryCounts(
        wf_matches=wf_matches,
        bracket_matches=0,
        rr_matches=rr_matches,
        total_matches=wf_matches + rr_matches,
        counts_by_stage={"WF": wf_matches, "RR_POOL": rr_matches},
    )


def _compute_wf_to_brackets_8(spec: DrawPlanSpec) -> InventoryCounts:
    """
    Compute inventory for WF_TO_BRACKETS_8 family.
    Supports: 8, 12, 16, 32 teams with waterfall rounds 0-2.
    Post-WF yields K brackets of 8.
    """
    errors: List[str] = []
    n = spec.team_count
    wf_rounds = spec.waterfall_rounds

    # V1 supported team counts
    if n not in (8, 12, 16, 32):
        errors.append(f"WF_TO_BRACKETS_8 supports team_count in {{8,12,16,32}}, got {n}")
        return InventoryCounts(errors=errors)

    # V1 supported WF rounds
    if wf_rounds not in (0, 1, 2):
        errors.append(f"WF_TO_BRACKETS_8 supports waterfall_rounds in {{0,1,2}}, got {wf_rounds}")
        return InventoryCounts(errors=errors)

    # Determine bracket count K
    if n == 8:
        k = 1
    elif n in (12, 16):
        k = 2
    elif n == 32:
        k = 4
    else:
        k = 1  # Fallback

    # WF matches: each round has n/2 matches
    # For 32 teams with 2 rounds: 16 + 16 = 32
    wf_matches = (n // 2) * wf_rounds

    # Bracket matches: K brackets × matches per bracket (guarantee-dependent)
    brk = bracket_inventory(spec.guarantee)
    bracket_matches = k * brk["TOTAL"]
    counts_by_stage: dict = {"WF": wf_matches}
    for stage in ("BRACKET_MAIN", "CONSOLATION_T1", "CONSOLATION_T2", "PLACEMENT"):
        counts_by_stage[stage] = k * brk[stage]

    return InventoryCounts(
        wf_matches=wf_matches,
        bracket_matches=bracket_matches,
        rr_matches=0,
        total_matches=wf_matches + bracket_matches,
        counts_by_stage=counts_by_stage,
    )


def compute_inventory(spec: DrawPlanSpec) -> InventoryCounts:
    """
    Main entry point: compute match inventory for a DrawPlanSpec.
    Returns InventoryCounts with errors if spec is invalid or unsupported.
    """
    # Basic validation first
    validation_errors = validate_spec(spec)
    if validation_errors:
        return InventoryCounts(errors=validation_errors)

    # Resolve family
    family = resolve_event_family(spec)

    logger.debug(
        "compute_inventory: event_id=%s family=%s template_key=%s",
        spec.event_id, family, spec.template_key
    )

    if family == "RR_ONLY":
        return _compute_rr_only(spec)

    if family == "WF_TO_POOLS_4":
        return _compute_wf_to_pools_4(spec)

    if family == "WF_TO_POOLS_DYNAMIC":
        return _compute_wf_to_pools_dynamic(spec)

    if family == "WF_TO_BRACKETS_8":
        return _compute_wf_to_brackets_8(spec)

    # Unsupported
    return InventoryCounts(
        errors=[f"Unsupported template: {spec.template_type!r} (key={spec.template_key})"]
    )


# -----------------------------------------------------------------------------
# Preferred Day Assignment
# -----------------------------------------------------------------------------

def _assign_preferred_days(session, spec: DrawPlanSpec, matches: list) -> None:
    """
    Set preferred_day on generated matches based on tournament day structure.

    Day mapping (for 3-day tournaments):
      - WF matches -> Day 0 (first day)
      - Division QFs, RR Rounds 1-2, Consolation Semis (tier 1) -> Day 1 (second day)
      - Division SFs -> Day 1 (second day)
      - Division Finals, Consolation Finals (tier 2), Placement, RR Round 3+ -> Day 2 (third day)

    For 2-day tournaments, all division matches go to Day 1.
    For 1-day tournaments, no preferred_day is set.

    preferred_day uses Python weekday convention: 0=Monday, 6=Sunday.
    """
    if not spec.tournament_id:
        return

    from sqlmodel import select
    from app.models.tournament_day import TournamentDay

    # Get tournament days in order
    tournament_days = session.exec(
        select(TournamentDay)
        .where(
            TournamentDay.tournament_id == spec.tournament_id,
            TournamentDay.is_active == True,  # noqa: E712
        )
        .order_by(TournamentDay.date)
    ).all()

    if not tournament_days:
        return

    day_count = len(tournament_days)
    day_weekdays = [d.date.weekday() for d in tournament_days]

    for m in matches:
        if m.match_type == "WF":
            # Waterfall matches -> first day
            m.preferred_day = day_weekdays[0]

        elif m.match_type == "RR":
            if day_count >= 3:
                # RR rounds 1-2 -> day 1 (Saturday), round 3+ -> day 2 (Sunday)
                if m.round_index is not None and m.round_index <= 2:
                    m.preferred_day = day_weekdays[1]
                else:
                    m.preferred_day = day_weekdays[min(2, day_count - 1)]
            elif day_count >= 2:
                m.preferred_day = day_weekdays[1]

        elif m.match_type == "MAIN":
            if day_count >= 3:
                # Classify by round_index within bracket:
                # QFs (round_index 1-4) -> day 1, SFs (5-6) -> day 1, Finals (7) -> day 2
                if m.round_index is not None and m.round_index <= 6:
                    m.preferred_day = day_weekdays[1]  # QFs and SFs on day 1
                else:
                    m.preferred_day = day_weekdays[2]  # Finals on day 2
            elif day_count >= 2:
                m.preferred_day = day_weekdays[1]

        elif m.match_type == "CONSOLATION":
            if day_count >= 3:
                # Consolation tier 1 (semis) -> day 1 or 2, tier 2 (finals) -> day 2
                if m.consolation_tier == 1:
                    m.preferred_day = day_weekdays[1]  # Consolation semis -> Saturday
                else:
                    m.preferred_day = day_weekdays[2]  # Consolation finals -> Sunday
            elif day_count >= 2:
                m.preferred_day = day_weekdays[1]

        elif m.match_type == "PLACEMENT":
            if day_count >= 3:
                m.preferred_day = day_weekdays[2]  # Placement matches -> last day
            elif day_count >= 2:
                m.preferred_day = day_weekdays[1]


# -----------------------------------------------------------------------------
# Match Generation (to be implemented in Step 4)
# -----------------------------------------------------------------------------

def generate_matches_for_event(
    session,
    version_id: int,
    spec: DrawPlanSpec,
    linked_team_ids: List[int],
    existing_codes: set[str],
) -> Tuple[List, List[str]]:
    """Generate Match objects for an event based on its DrawPlanSpec.

    Args:
        session: SQLModel session
        version_id: Schedule version ID
        spec: The draw plan specification
        linked_team_ids: List of team IDs linked to this event (in seed order)
        existing_codes: Version-global set of match_codes (built once by caller, mutated in-place)

    Returns:
        Tuple of (list of Match objects to add, list of warning strings)

    Raises:
        ValueError: If duplicate match_codes are generated (internal bug)
    """
    if not getattr(session, "_allow_match_generation", False):
        raise RuntimeError(
            "generate_matches_for_event called outside build_schedule_v1"
        )

    from app.models.match import Match

    family = resolve_event_family(spec)
    matches: List[Match] = []
    warnings: List[str] = []

    if family == "RR_ONLY":
        matches, warnings = _generate_rr_only(session, version_id, spec, linked_team_ids)
    elif family == "WF_TO_POOLS_4":
        matches, warnings = _generate_wf_to_pools_4(session, version_id, spec, linked_team_ids)
    elif family == "WF_TO_POOLS_DYNAMIC":
        matches, warnings = _generate_wf_to_pools_dynamic(session, version_id, spec, linked_team_ids)
    elif family == "WF_TO_BRACKETS_8":
        matches, warnings = _generate_wf_to_brackets_8(session, version_id, spec, linked_team_ids)
    else:
        warnings.append(f"Unsupported family {family} for event {spec.event_name}")

    # =========================================================================
    # CRITICAL: In-memory duplicate match_code detection (internal batch)
    # =========================================================================
    seen: set[str] = set()
    dupes: list[str] = []
    for m in matches:
        if m.match_code in seen:
            dupes.append(m.match_code)
        else:
            seen.add(m.match_code)
    if dupes:
        raise RuntimeError(
            f"Duplicate match_code(s) generated: event_id={spec.event_id} "
            f"version_id={version_id} dupes={sorted(set(dupes))[:25]}"
        )

    # =========================================================================
    # Set preferred_day based on match type and tournament day structure
    # =========================================================================
    _assign_preferred_days(session, spec, matches)

    # Idempotency: skip matches that already exist (never INSERT duplicate)
    to_add: List[Match] = []
    for m in matches:
        if m.match_code in existing_codes:
            continue
        existing_codes.add(m.match_code)
        to_add.append(m)

    return to_add, warnings


# -----------------------------------------------------------------------------
# Match Generation: RR_ONLY
# -----------------------------------------------------------------------------

def _generate_rr_only(
    session,
    version_id: int,
    spec: DrawPlanSpec,
    linked_team_ids: List[int],
) -> Tuple[List, List[str]]:
    """
    Generate round-robin matches for RR_ONLY family using circle method.
    For RR_ONLY, treat entire event as single pool (pool_index=0).
    """
    from app.models.match import Match

    matches = []
    warnings = []
    n = spec.team_count

    if len(linked_team_ids) != n:
        warnings.append(
            f"RR_ONLY requires {n} linked teams, got {len(linked_team_ids)}; "
            "generating matches with available teams"
        )

    teams = linked_team_ids[:n] if len(linked_team_ids) >= n else linked_team_ids
    prefix = spec.match_code_prefix
    base_pairings = rr_pairings_by_round(n)
    
    # Wire placeholders for RR_ONLY (single pool, pool_index=0)
    # Enforce top2-last-round constraint
    wired_pairings = wire_rr_match_placeholders(
        pool_index=0,
        pool_size=n,
        pairings=base_pairings,
        enforce_top2_last=True,
    )

    for pair_count, (round_index, seq_in_round, placeholder_a, placeholder_b) in enumerate(wired_pairings, start=1):
        # Extract seed numbers from placeholders (e.g., "SEED_1" -> seed 1)
        # For RR_ONLY, seeds are 1..n, convert to 0-based indices
        try:
            seed_a = int(placeholder_a.replace("SEED_", ""))
            seed_b = int(placeholder_b.replace("SEED_", ""))
            idx_a = seed_a - 1  # Convert to 0-based (seed 1 -> index 0)
            idx_b = seed_b - 1
        except (ValueError, AttributeError):
            # Fallback: use pair_count (shouldn't happen with proper wiring)
            idx_a = pair_count - 1
            idx_b = pair_count - 1
        
        team_a_id = teams[idx_a] if idx_a < len(teams) else None
        team_b_id = teams[idx_b] if idx_b < len(teams) else None
        
        match = Match(
            tournament_id=spec.tournament_id,
            event_id=spec.event_id,
            schedule_version_id=version_id,
            match_code=f"{prefix}RR_{pair_count:02d}",
            match_type="RR",
            round_number=round_index,
            round_index=round_index,
            sequence_in_round=seq_in_round,
            team_a_id=team_a_id,
            team_b_id=team_b_id,
            placeholder_side_a=placeholder_a,
            placeholder_side_b=placeholder_b,
            duration_minutes=spec.standard_minutes,
        )
        matches.append(match)

    return matches, warnings


# -----------------------------------------------------------------------------
# Match Generation: WF_TO_POOLS_4
# -----------------------------------------------------------------------------

def _generate_wf_to_pools_4(
    session,
    version_id: int,
    spec: DrawPlanSpec,
    linked_team_ids: List[int],
) -> Tuple[List, List[str]]:
    """
    Generate matches for WF_TO_POOLS_4 family (16 teams, 2 WF rounds, 4 pools RR).
    """
    from app.models.match import Match

    matches = []
    warnings = []

    if spec.team_count != 16:
        warnings.append(f"WF_TO_POOLS_4 requires 16 teams, got {spec.team_count}")
        return matches, warnings

    # Ensure we have teams (may be fewer than 16 during early setup)
    teams = linked_team_ids[:16] if len(linked_team_ids) >= 16 else linked_team_ids
    have_all_teams = len(teams) == 16
    prefix = spec.match_code_prefix

    # -------------------------------------------------------------------------
    # WF Round 1: 8 matches — avoid-group-aware pairing (falls back to half-split)
    # -------------------------------------------------------------------------
    half = 8
    r1_matches = []
    pairing = _get_wf_r1_pairing(session, spec.event_id, linked_team_ids, 16)

    for i in range(half):
        if pairing:
            seed_a, seed_b = pairing.pairs[i]
            team_a_id = pairing.team_id_pairs[i][0]
            team_b_id = pairing.team_id_pairs[i][1]
        else:
            seed_a = i + 1
            seed_b = i + half + 1
            team_a_id = teams[i] if have_all_teams else None
            team_b_id = teams[i + half] if have_all_teams else None

        match = Match(
            tournament_id=spec.tournament_id,
            event_id=spec.event_id,
            schedule_version_id=version_id,
            match_code=f"{prefix}WF_R1_{i+1:02d}",
            match_type="WF",
            round_number=1,
            round_index=1,
            sequence_in_round=i + 1,
            team_a_id=team_a_id,
            team_b_id=team_b_id,
            placeholder_side_a=f"Seed {seed_a}",
            placeholder_side_b=f"Seed {seed_b}",
            duration_minutes=spec.waterfall_minutes,
        )
        matches.append(match)
        r1_matches.append(match)

    if pairing and pairing.conflicts:
        for c in pairing.conflicts:
            warnings.append(
                f"W_WF_R1_AVOID_GROUP_CONFLICT: seed {c.seed_a} vs seed {c.seed_b} "
                f"(both group '{c.group}')"
            )

    # Flush to get R1 match IDs
    session.add_all(r1_matches)
    session.flush()

    # -------------------------------------------------------------------------
    # WF Round 2: 8 matches (4 winners bracket + 4 losers bracket)
    # Wiring optimized for avoid_group separation within blocks of 4
    # -------------------------------------------------------------------------
    wiring = _get_wf_r2_wiring(session, spec.event_id, r1_matches)
    r1_by_id = {m.id: m for m in r1_matches}
    r2_half = len(wiring.pairs)

    # Winners bracket
    for seq, (src_a_id, src_b_id) in enumerate(wiring.pairs, start=1):
        seq_a = r1_by_id[src_a_id].sequence_in_round
        seq_b = r1_by_id[src_b_id].sequence_in_round
        match = Match(
            tournament_id=spec.tournament_id,
            event_id=spec.event_id,
            schedule_version_id=version_id,
            match_code=f"{prefix}WF_R2_W{seq:02d}",
            match_type="WF",
            round_number=2,
            round_index=2,
            sequence_in_round=seq,
            team_a_id=None,
            team_b_id=None,
            placeholder_side_a=f"W(R1_{seq_a})",
            placeholder_side_b=f"W(R1_{seq_b})",
            source_match_a_id=src_a_id,
            source_a_role="WINNER",
            source_match_b_id=src_b_id,
            source_b_role="WINNER",
            duration_minutes=spec.waterfall_minutes,
        )
        matches.append(match)

    # Losers bracket (same pairing order)
    for seq, (src_a_id, src_b_id) in enumerate(wiring.pairs, start=1):
        seq_a = r1_by_id[src_a_id].sequence_in_round
        seq_b = r1_by_id[src_b_id].sequence_in_round
        match = Match(
            tournament_id=spec.tournament_id,
            event_id=spec.event_id,
            schedule_version_id=version_id,
            match_code=f"{prefix}WF_R2_L{seq:02d}",
            match_type="WF",
            round_number=2,
            round_index=2,
            sequence_in_round=seq + r2_half,
            team_a_id=None,
            team_b_id=None,
            placeholder_side_a=f"L(R1_{seq_a})",
            placeholder_side_b=f"L(R1_{seq_b})",
            source_match_a_id=src_a_id,
            source_a_role="LOSER",
            source_match_b_id=src_b_id,
            source_b_role="LOSER",
            duration_minutes=spec.waterfall_minutes,
        )
        matches.append(match)

    for w in wiring.warnings:
        warnings.append(w.message)

    # -------------------------------------------------------------------------
    # Pool RR: 4 pools of 4 teams = 24 matches (circle method, 3 rounds × 2 matches)
    # Pool assignment by seed bands: [0..3], [4..7], [8..11], [12..15]
    # Wire placeholders deterministically by seed order
    # -------------------------------------------------------------------------
    pool_labels = ["A", "B", "C", "D"]
    pool_size = 4
    base_pairings = rr_pairings_by_round(pool_size)
    
    for pool_idx, pool_label in enumerate(pool_labels):
        # Wire placeholders for this pool (enforces top2-last-round constraint)
        wired_pairings = wire_rr_match_placeholders(
            pool_index=pool_idx,
            pool_size=pool_size,
            pairings=base_pairings,
            enforce_top2_last=True,
        )
        
        for rr_idx, (round_index, seq_in_round, placeholder_a, placeholder_b) in enumerate(wired_pairings):
            match = Match(
                tournament_id=spec.tournament_id,
                event_id=spec.event_id,
                schedule_version_id=version_id,
                match_code=f"{prefix}POOL{pool_label}_RR_{rr_idx+1:02d}",
                match_type="RR",
                round_number=round_index,
                round_index=round_index,
                sequence_in_round=seq_in_round,
                team_a_id=None,  # Assigned after WF resolves
                team_b_id=None,
                placeholder_side_a=placeholder_a,
                placeholder_side_b=placeholder_b,
                duration_minutes=spec.standard_minutes,
            )
            matches.append(match)

    return matches, warnings


# -----------------------------------------------------------------------------
# Match Generation: WF_TO_POOLS_DYNAMIC
# -----------------------------------------------------------------------------

def _generate_wf_to_pools_dynamic(
    session,
    version_id: int,
    spec: DrawPlanSpec,
    linked_team_ids: List[int],
) -> Tuple[List, List[str]]:
    """
    Generate matches for WF_TO_POOLS_DYNAMIC family.
    Uses rules from draw_plan_rules.py (single source of truth).
    """
    from app.models.match import Match

    matches = []
    warnings = []
    n = spec.team_count
    wf_rounds = spec.waterfall_rounds

    # Validate team count using rules module
    if n not in WF_TO_POOLS_DYNAMIC_TEAM_COUNTS:
        warnings.append(
            f"WF_TO_POOLS_DYNAMIC requires team_count in {sorted(WF_TO_POOLS_DYNAMIC_TEAM_COUNTS)}, got {n}"
        )
        return matches, warnings

    # Validate waterfall rounds using rules module
    expected_wf_rounds = required_wf_rounds("WF_TO_POOLS_DYNAMIC", n)
    if wf_rounds != expected_wf_rounds:
        warnings.append(
            f"WF_TO_POOLS_DYNAMIC with {n} teams requires wf_rounds={expected_wf_rounds}, got {wf_rounds}"
        )
        return matches, warnings

    teams = linked_team_ids[:n] if len(linked_team_ids) >= n else linked_team_ids
    have_all_teams = len(teams) == n
    prefix = spec.match_code_prefix
    
    # Determine pool structure using rules module
    pools_count, teams_per_pool = pool_config(n)

    # -------------------------------------------------------------------------
    # WF Round 1: n/2 matches — avoid-group-aware pairing (falls back to half-split)
    # -------------------------------------------------------------------------
    matches_per_wf_round = n // 2
    half = matches_per_wf_round
    r1_matches = []
    pairing = _get_wf_r1_pairing(session, spec.event_id, linked_team_ids, n)

    for i in range(matches_per_wf_round):
        if pairing:
            seed_a, seed_b = pairing.pairs[i]
            team_a_id = pairing.team_id_pairs[i][0]
            team_b_id = pairing.team_id_pairs[i][1]
        else:
            seed_a = i + 1
            seed_b = i + half + 1
            team_a_id = teams[i] if have_all_teams and i < len(teams) else None
            team_b_id = teams[i + half] if have_all_teams and (i + half) < len(teams) else None

        match = Match(
            tournament_id=spec.tournament_id,
            event_id=spec.event_id,
            schedule_version_id=version_id,
            match_code=f"{prefix}WF_R1_{i+1:02d}",
            match_type="WF",
            round_number=1,
            round_index=1,
            sequence_in_round=i + 1,
            team_a_id=team_a_id,
            team_b_id=team_b_id,
            placeholder_side_a=f"Seed {seed_a}",
            placeholder_side_b=f"Seed {seed_b}",
            duration_minutes=spec.waterfall_minutes,
        )
        matches.append(match)
        r1_matches.append(match)

    if pairing and pairing.conflicts:
        for c in pairing.conflicts:
            warnings.append(
                f"W_WF_R1_AVOID_GROUP_CONFLICT: seed {c.seed_a} vs seed {c.seed_b} "
                f"(both group '{c.group}')"
            )

    # Flush to get R1 match IDs for dependency wiring
    session.add_all(r1_matches)
    session.flush()

    # -------------------------------------------------------------------------
    # WF Round 2 (if wf_rounds >= 2): n/2 matches
    # Wiring optimized for avoid_group separation within blocks of 4
    # -------------------------------------------------------------------------
    if wf_rounds >= 2:
        wiring = _get_wf_r2_wiring(session, spec.event_id, r1_matches)
        r1_by_id = {m.id: m for m in r1_matches}
        r2_half = len(wiring.pairs)

        # Winners bracket
        for seq, (src_a_id, src_b_id) in enumerate(wiring.pairs, start=1):
            seq_a = r1_by_id[src_a_id].sequence_in_round
            seq_b = r1_by_id[src_b_id].sequence_in_round
            match = Match(
                tournament_id=spec.tournament_id,
                event_id=spec.event_id,
                schedule_version_id=version_id,
                match_code=f"{prefix}WF_R2_W{seq:02d}",
                match_type="WF",
                round_number=2,
                round_index=2,
                sequence_in_round=seq,
                team_a_id=None,
                team_b_id=None,
                placeholder_side_a=f"W(R1_{seq_a})",
                placeholder_side_b=f"W(R1_{seq_b})",
                source_match_a_id=src_a_id,
                source_a_role="WINNER",
                source_match_b_id=src_b_id,
                source_b_role="WINNER",
                duration_minutes=spec.waterfall_minutes,
            )
            matches.append(match)

        # Losers bracket (same pairing order)
        for seq, (src_a_id, src_b_id) in enumerate(wiring.pairs, start=1):
            seq_a = r1_by_id[src_a_id].sequence_in_round
            seq_b = r1_by_id[src_b_id].sequence_in_round
            match = Match(
                tournament_id=spec.tournament_id,
                event_id=spec.event_id,
                schedule_version_id=version_id,
                match_code=f"{prefix}WF_R2_L{seq:02d}",
                match_type="WF",
                round_number=2,
                round_index=2,
                sequence_in_round=seq + r2_half,
                team_a_id=None,
                team_b_id=None,
                placeholder_side_a=f"L(R1_{seq_a})",
                placeholder_side_b=f"L(R1_{seq_b})",
                source_match_a_id=src_a_id,
                source_a_role="LOSER",
                source_match_b_id=src_b_id,
                source_b_role="LOSER",
                duration_minutes=spec.waterfall_minutes,
            )
            matches.append(match)

        for w in wiring.warnings:
            warnings.append(w.message)

    # -------------------------------------------------------------------------
    # Pool RR: Generate round-robin matches within each pool (circle method)
    # No playoffs - pools only
    # Wire placeholders deterministically by seed order
    # -------------------------------------------------------------------------
    pool_labels = [chr(ord('A') + i) for i in range(pools_count)]  # A, B, C, ...
    base_pairings = rr_pairings_by_round(teams_per_pool)

    for pool_idx, pool_label in enumerate(pool_labels):
        # Wire placeholders for this pool (enforces top2-last-round constraint)
        wired_pairings = wire_rr_match_placeholders(
            pool_index=pool_idx,
            pool_size=teams_per_pool,
            pairings=base_pairings,
            enforce_top2_last=True,
        )
        
        for rr_idx, (round_index, seq_in_round, placeholder_a, placeholder_b) in enumerate(wired_pairings):
            match = Match(
                tournament_id=spec.tournament_id,
                event_id=spec.event_id,
                schedule_version_id=version_id,
                match_code=f"{prefix}POOL{pool_label}_RR_{rr_idx+1:02d}",
                match_type="RR",
                round_number=round_index,
                round_index=round_index,
                sequence_in_round=seq_in_round,
                team_a_id=None,  # Assigned after WF resolves
                team_b_id=None,
                placeholder_side_a=placeholder_a,
                placeholder_side_b=placeholder_b,
                duration_minutes=spec.standard_minutes,
            )
            matches.append(match)

    return matches, warnings


# -----------------------------------------------------------------------------
# Match Generation: WF_TO_BRACKETS_8
# -----------------------------------------------------------------------------

def _generate_wf_to_brackets_8(
    session,
    version_id: int,
    spec: DrawPlanSpec,
    linked_team_ids: List[int],
) -> Tuple[List, List[str]]:
    """
    Generate matches for WF_TO_BRACKETS_8 family.
    Supports 8, 12, 16, 32 teams with waterfall rounds 0-2.
    """
    from app.models.match import Match

    matches = []
    warnings = []
    n = spec.team_count
    wf_rounds = spec.waterfall_rounds

    if n not in (8, 12, 16, 32):
        warnings.append(f"WF_TO_BRACKETS_8 requires team_count in {{8,12,16,32}}, got {n}")
        return matches, warnings

    teams = linked_team_ids[:n] if len(linked_team_ids) >= n else linked_team_ids
    have_all_teams = len(teams) == n

    # Determine bracket count
    if n == 8:
        bracket_count = 1
    elif n in (12, 16):
        bracket_count = 2
    else:  # 32
        bracket_count = 4

    prefix = spec.match_code_prefix

    # -------------------------------------------------------------------------
    # Generate Waterfall Rounds
    # -------------------------------------------------------------------------
    prev_round_matches = []
    wf2_matches = []  # Track WF Round 2 matches for bracket wiring

    for wf_round in range(1, wf_rounds + 1):
        round_matches = []
        matches_in_round = n // 2

        if wf_round == 1:
            # WF R1: avoid-group-aware pairing (falls back to half-split)
            half_r1 = matches_in_round
            pairing = _get_wf_r1_pairing(session, spec.event_id, linked_team_ids, n)

            for i in range(matches_in_round):
                if pairing:
                    seed_a, seed_b = pairing.pairs[i]
                    team_a_id = pairing.team_id_pairs[i][0]
                    team_b_id = pairing.team_id_pairs[i][1]
                else:
                    seed_a = i + 1
                    seed_b = i + half_r1 + 1
                    team_a_id = teams[i] if have_all_teams else None
                    team_b_id = teams[i + half_r1] if have_all_teams else None

                match = Match(
                    tournament_id=spec.tournament_id,
                    event_id=spec.event_id,
                    schedule_version_id=version_id,
                    match_code=f"{prefix}WF_R{wf_round}_{i+1:02d}",
                    match_type="WF",
                    round_number=wf_round,
                    round_index=wf_round,
                    sequence_in_round=i + 1,
                    team_a_id=team_a_id,
                    team_b_id=team_b_id,
                    placeholder_side_a=f"Seed {seed_a}",
                    placeholder_side_b=f"Seed {seed_b}",
                    duration_minutes=spec.waterfall_minutes,
                )
                matches.append(match)
                round_matches.append(match)

            if pairing and pairing.conflicts:
                for c in pairing.conflicts:
                    warnings.append(
                        f"W_WF_R1_AVOID_GROUP_CONFLICT: seed {c.seed_a} vs seed {c.seed_b} "
                        f"(both group '{c.group}')"
                    )
        else:
            # Subsequent WF rounds: dependency-driven from previous round
            # Flush previous round to get IDs
            session.add_all(prev_round_matches)
            session.flush()

            # Use block-based wiring optimizer for avoid_group separation
            wiring = _get_wf_r2_wiring(session, spec.event_id, prev_round_matches)
            r1_by_id = {m.id: m for m in prev_round_matches}
            r2_half = len(wiring.pairs)

            # Winners bracket pairings
            for seq, (src_a_id, src_b_id) in enumerate(wiring.pairs, start=1):
                prev_seq_a = r1_by_id[src_a_id].sequence_in_round
                prev_seq_b = r1_by_id[src_b_id].sequence_in_round

                match = Match(
                    tournament_id=spec.tournament_id,
                    event_id=spec.event_id,
                    schedule_version_id=version_id,
                    match_code=f"{prefix}WF_R{wf_round}_W{seq:02d}",
                    match_type="WF",
                    round_number=wf_round,
                    round_index=wf_round,
                    sequence_in_round=seq,
                    team_a_id=None,
                    team_b_id=None,
                    placeholder_side_a=f"W(R{wf_round-1}_{prev_seq_a})",
                    placeholder_side_b=f"W(R{wf_round-1}_{prev_seq_b})",
                    source_match_a_id=src_a_id,
                    source_a_role="WINNER",
                    source_match_b_id=src_b_id,
                    source_b_role="WINNER",
                    duration_minutes=spec.waterfall_minutes,
                )
                matches.append(match)
                round_matches.append(match)
                if wf_round == 2:
                    wf2_matches.append(match)

            # Losers bracket pairings (same pairing order)
            for seq, (src_a_id, src_b_id) in enumerate(wiring.pairs, start=1):
                prev_seq_a = r1_by_id[src_a_id].sequence_in_round
                prev_seq_b = r1_by_id[src_b_id].sequence_in_round

                match = Match(
                    tournament_id=spec.tournament_id,
                    event_id=spec.event_id,
                    schedule_version_id=version_id,
                    match_code=f"{prefix}WF_R{wf_round}_L{seq:02d}",
                    match_type="WF",
                    round_number=wf_round,
                    round_index=wf_round,
                    sequence_in_round=r2_half + seq,
                    team_a_id=None,
                    team_b_id=None,
                    placeholder_side_a=f"L(R{wf_round-1}_{prev_seq_a})",
                    placeholder_side_b=f"L(R{wf_round-1}_{prev_seq_b})",
                    source_match_a_id=src_a_id,
                    source_a_role="LOSER",
                    source_match_b_id=src_b_id,
                    source_b_role="LOSER",
                    duration_minutes=spec.waterfall_minutes,
                )
                matches.append(match)
                round_matches.append(match)
                if wf_round == 2:
                    wf2_matches.append(match)

            for w in wiring.warnings:
                warnings.append(w.message)

        prev_round_matches = round_matches

    # -------------------------------------------------------------------------
    # Generate Bracket Matches (8-team brackets with G4/G5 consolation)
    # -------------------------------------------------------------------------
    
    def get_qf_wf_r2_tokens(event_prefix: str, bracket_label: str, qf_sequence: int) -> tuple[str, str]:
        """
        Generate WF R2 tokens for a QF match based on bracket label and QF sequence.
        
        Args:
            event_prefix: Event prefix (e.g., "WOM_WOM_E7_")
            bracket_label: One of "WW", "WL", "LW", "LL"
            qf_sequence: QF match number (1-4)
            
        Returns:
            Tuple of (token_a, token_b) for the two sides of the QF match
            
        Rules:
            - WW/WL reference W-track R2 matches (W01-W08)
            - LW/LL reference L-track R2 matches (L01-L08)
            - WW/LW take WINNER of the R2 match
            - WL/LL take LOSER of the R2 match
        """
        block_start = 1

        # token_type selects the R2 track: W-track for Div I/II, L-track for Div III/IV
        if bracket_label in ("WW", "WL"):
            token_type = "W"
        elif bracket_label in ("LW", "LL"):
            token_type = "L"
        else:
            raise ValueError(f"Unknown bracket_label: {bracket_label}")
        
        # Sequential pairing: the bracket fold is already embedded in the
        # waterfall R1 ordering via bracket_fold_positions(), so QFs pair
        # straight A vs B, C vs D, E vs F, G vs H.
        slot_a = (qf_sequence - 1) * 2 + 1
        slot_b = (qf_sequence - 1) * 2 + 2
        
        # Convert those slots to WF R2 overall sequence numbers
        wf_seq_a = block_start + (slot_a - 1)
        wf_seq_b = block_start + (slot_b - 1)
        
        # Format token with 2-digit padding
        # event_prefix already has trailing underscore removed, so add it back for consistency
        token_a = f"{event_prefix}_WF_R2_{token_type}{wf_seq_a:02d}"
        token_b = f"{event_prefix}_WF_R2_{token_type}{wf_seq_b:02d}"
        
        return token_a, token_b
    
    bracket_labels = ["WW", "WL", "LW", "LL"][:bracket_count]
    matches_per_bracket = bracket_matches_for_guarantee(spec.guarantee)

    # Sort WF2 matches deterministically by sequence_in_round
    # Winners come first (sequence 1-4), then losers (sequence 5-8 for 8-team)
    wf2_matches_sorted = sorted(wf2_matches, key=lambda m: (m.sequence_in_round or 0, m.match_code or ""))
    
    # For 8-team bracket, we expect 8 WF2 matches (4 winners + 4 losers)
    # For larger brackets, adjust accordingly
    expected_wf2_count = n // 2 if wf_rounds >= 2 else 0
    
    # Debug logging
    logger.debug(
        f"WF2 bracket wiring: wf_rounds={wf_rounds}, n={n}, "
        f"wf2_matches_count={len(wf2_matches)}, wf2_matches_sorted_count={len(wf2_matches_sorted)}, "
        f"expected_wf2_count={expected_wf2_count}"
    )
    
    if wf_rounds >= 2 and len(wf2_matches_sorted) < expected_wf2_count:
        warnings.append(
            f"Expected {expected_wf2_count} WF Round 2 matches for {n} teams, "
            f"found {len(wf2_matches_sorted)}. Bracket placeholders may be incomplete."
        )

    # Extract event prefix from match_code_prefix (remove trailing underscore)
    # match_code_prefix format: "{cat}_{name}_E{event_id}_"
    # Token prefix format: "{cat}_{name}_E{event_id}" (no trailing underscore)
    event_prefix = prefix.rstrip('_') if prefix.endswith('_') else prefix

    # QF pairing uses standard bracket fold (1v8, 4v5, 3v6, 2v7)
    # Placeholders are generated from WF2 tokens via get_qf_wf_r2_tokens

    for bracket_idx, bracket_label in enumerate(bracket_labels):
        # Check if WF2 tokens are available for bracket generation
        # For 16-team event with 2 WF rounds: 8 WF2 matches (4 winners + 4 losers)
        # For 32-team event with 2 WF rounds: 16 WF2 matches (8 winners + 8 losers)
        use_wf2_tokens = wf_rounds >= 2 and len(wf2_matches_sorted) > 0
        
        logger.debug(
            f"Bracket {bracket_label}: use_wf2_tokens={use_wf2_tokens}, wf_rounds={wf_rounds}, "
            f"wf2_count={len(wf2_matches_sorted)}, expected={expected_wf2_count}, "
            f"event_prefix={event_prefix}"
        )
        
        if not use_wf2_tokens:
            # WF2 is required for bracket generation - this should not happen for finalized events
            if wf_rounds >= 2:
                warnings.append(
                    f"Bracket {bracket_label}: WF2 rounds configured but no WF2 matches found. "
                    f"Cannot generate bracket placeholders."
                )
            raise ValueError(
                f"Cannot generate bracket matches without WF2. "
                f"Event {spec.event_id}, bracket {bracket_label}, wf_rounds={wf_rounds}, "
                f"wf2_matches={len(wf2_matches_sorted)}"
            )

        # Generate bracket matches
        bracket_matches = []  # Track for SF/Final/Consolation references
        qf_matches = []  # Track QF matches for consolation references
        
        for match_idx in range(matches_per_bracket):
            # Determine stage based on match index
            # Main bracket: matches 1-7, Consolation: matches 8+
            if match_idx < 7:
                match_type = "MAIN"
                sub_code = f"M{match_idx + 1}"
                # round_index groups bracket rounds properly:
                #   QF (match_idx 0-3) → round_index=1
                #   SF (match_idx 4-5) → round_index=2
                #   Final (match_idx 6) → round_index=3
                # sequence_in_round restarts within each round.
                if match_idx < 4:
                    round_index = 1
                    sequence_in_round = match_idx + 1        # 1..4 for QFs
                elif match_idx < 6:
                    round_index = 2
                    sequence_in_round = match_idx - 4 + 1    # 1..2 for SFs
                else:
                    round_index = 3
                    sequence_in_round = 1                     # 1 for Final
                
                # Determine placeholders based on bracket round
                if match_idx < 4:
                    # QF matches: use WF2-based tokens via helper function (bracket fold)
                    # WW QF1 → W01 vs W08, QF2 → W04 vs W05, QF3 → W03 vs W06, QF4 → W02 vs W07
                    qf_sequence = match_idx + 1  # 1..4 for QF
                    placeholder_a, placeholder_b = get_qf_wf_r2_tokens(event_prefix, bracket_label, qf_sequence)
                elif match_idx == 4:
                    # SF1: Winner of QF1 vs Winner of QF2
                    qf1_code = f"{prefix}B{bracket_label}_M1"
                    qf2_code = f"{prefix}B{bracket_label}_M2"
                    placeholder_a = f"WINNER:{qf1_code}"
                    placeholder_b = f"WINNER:{qf2_code}"
                elif match_idx == 5:
                    # SF2: Winner of QF3 vs Winner of QF4
                    qf3_code = f"{prefix}B{bracket_label}_M3"
                    qf4_code = f"{prefix}B{bracket_label}_M4"
                    placeholder_a = f"WINNER:{qf3_code}"
                    placeholder_b = f"WINNER:{qf4_code}"
                elif match_idx == 6:
                    # Final: Winner of SF1 vs Winner of SF2
                    sf1_code = f"{prefix}B{bracket_label}_M5"
                    sf2_code = f"{prefix}B{bracket_label}_M6"
                    placeholder_a = f"WINNER:{sf1_code}"
                    placeholder_b = f"WINNER:{sf2_code}"
                else:
                    raise ValueError(f"Unexpected match_idx {match_idx} for MAIN bracket")
            else:
                match_type = "CONSOLATION"
                sub_code = f"C{match_idx - 6}"
                # C1,C2 (match_idx 7,8) = Round 1 (consolation semis)
                # C3,C4,C5 (match_idx 9,10,11) = Round 2 (cons final + SF losers + cons semi losers)
                if match_idx <= 8:
                    round_index = 1
                    sequence_in_round = match_idx - 6   # 1, 2
                else:
                    round_index = 2
                    sequence_in_round = match_idx - 8   # 1, 2, 3
                
                # Consolation placeholders reference losers of QF matches
                # C1 (Cons SF): LOSER of QF1 vs LOSER of QF2
                # C2 (Cons SF): LOSER of QF3 vs LOSER of QF4
                # C3 (Cons Final): WINNER of C1 vs WINNER of C2
                # C4 (Main-Cons SF): LOSER of Main SF1 (M5) vs LOSER of Main SF2 (M6)
                # C5 (2XL): LOSER of C1 vs LOSER of C2
                # etc.
                if sequence_in_round == 1:
                    # Cons SF 1: LOSER of QF1 vs LOSER of QF2
                    qf1_code = f"{prefix}B{bracket_label}_M1"
                    qf2_code = f"{prefix}B{bracket_label}_M2"
                    placeholder_a = f"LOSER:{qf1_code}"
                    placeholder_b = f"LOSER:{qf2_code}"
                elif sequence_in_round == 2:
                    # Cons SF 2: LOSER of QF3 vs LOSER of QF4
                    qf3_code = f"{prefix}B{bracket_label}_M3"
                    qf4_code = f"{prefix}B{bracket_label}_M4"
                    placeholder_a = f"LOSER:{qf3_code}"
                    placeholder_b = f"LOSER:{qf4_code}"
                elif sequence_in_round == 3:
                    # Cons Final: WINNER of C1 vs WINNER of C2 (winners of consolation semi-finals)
                    c1_code = f"{prefix}B{bracket_label}_C1"
                    c2_code = f"{prefix}B{bracket_label}_C2"
                    placeholder_a = f"WINNER:{c1_code}"
                    placeholder_b = f"WINNER:{c2_code}"
                elif sequence_in_round == 4:
                    # Main-Cons SF: LOSER of Main SF1 (M5) vs LOSER of Main SF2 (M6) (losers of main draw semi-finals)
                    sf1_code = f"{prefix}B{bracket_label}_M5"
                    sf2_code = f"{prefix}B{bracket_label}_M6"
                    placeholder_a = f"LOSER:{sf1_code}"
                    placeholder_b = f"LOSER:{sf2_code}"
                elif sequence_in_round == 5:
                    # 2XL: LOSER of C1 vs LOSER of C2 (losers of consolation semi-finals 1 & 2)
                    c1_code = f"{prefix}B{bracket_label}_C1"
                    c2_code = f"{prefix}B{bracket_label}_C2"
                    placeholder_a = f"LOSER:{c1_code}"
                    placeholder_b = f"LOSER:{c2_code}"
                else:
                    # Additional consolation matches (Placement, etc.)
                    # Reference prior matches deterministically
                    prev_match_idx = match_idx - 1
                    prev_sub_code = f"C{prev_match_idx - 6}" if prev_match_idx >= 7 else f"M{prev_match_idx + 1}"
                    prev_code = f"{prefix}B{bracket_label}_{prev_sub_code}"
                    placeholder_a = f"LOSER:{prev_code}"
                    placeholder_b = f"TBD:{bracket_label}_C{sequence_in_round}"  # Placeholder for complex cases

            # Validation: ensure no legacy placeholders
            assert not placeholder_a.startswith("Bracket "), \
                f"Legacy placeholder detected in placeholder_a: '{placeholder_a}'"
            assert not placeholder_b.startswith("Bracket "), \
                f"Legacy placeholder detected in placeholder_b: '{placeholder_b}'"
            assert not placeholder_a.startswith("Division "), \
                f"Legacy placeholder detected in placeholder_a: '{placeholder_a}'"
            assert not placeholder_b.startswith("Division "), \
                f"Legacy placeholder detected in placeholder_b: '{placeholder_b}'"
            # Also check for " TBD" suffix (old format)
            assert " TBD" not in placeholder_a or placeholder_a.startswith("TBD:"), \
                f"Legacy 'TBD' placeholder detected in placeholder_a: '{placeholder_a}'"
            assert " TBD" not in placeholder_b or placeholder_b.startswith("TBD:"), \
                f"Legacy 'TBD' placeholder detected in placeholder_b: '{placeholder_b}'"

            match = Match(
                tournament_id=spec.tournament_id,
                event_id=spec.event_id,
                schedule_version_id=version_id,
                match_code=f"{prefix}B{bracket_label}_{sub_code}",
                match_type=match_type,
                round_number=match_idx + 1,
                round_index=round_index,
                sequence_in_round=sequence_in_round,
                team_a_id=None,  # Dependency-driven
                team_b_id=None,
                placeholder_side_a=placeholder_a,
                placeholder_side_b=placeholder_b,
                duration_minutes=spec.standard_minutes,
            )
            matches.append(match)
            if match_type == "MAIN":
                bracket_matches.append(match)
                if match_idx < 4:  # Track QF matches
                    qf_matches.append(match)

    # -------------------------------------------------------------------------
    # Wire source_match_a_id / source_match_b_id for bracket matches
    # -------------------------------------------------------------------------
    # Bracket matches store placeholder strings like "WINNER:code" or
    # "LOSER:code" but the actual source_match_a_id/b_id foreign keys
    # are not set.  We need to:
    #   1. Flush bracket matches to get database IDs
    #   2. Resolve placeholder references to actual match IDs
    # WF matches were already flushed earlier in this function.
    bracket_only = [
        m for m in matches
        if m.match_type in ("MAIN", "CONSOLATION") and m.id is None
    ]
    if bracket_only:
        session.add_all(bracket_only)
        session.flush()

    # Build match_code → match lookup from ALL matches in this event
    code_to_match = {m.match_code: m for m in matches if m.match_code}

    wired_count = 0

    def _wire_placeholder(m: Match, placeholder: str, side: str) -> bool:
        """Wire a single placeholder to source_match + role. Returns True if wired."""
        nonlocal wired_count
        if not placeholder:
            return False

        if ":" in placeholder:
            parts = placeholder.split(":", 1)
            role, ref_code = parts[0], parts[1]
            if role in ("WINNER", "LOSER") and ref_code in code_to_match:
                ref_match = code_to_match[ref_code]
                if side == "A":
                    m.source_match_a_id = ref_match.id
                    m.source_a_role = role
                else:
                    m.source_match_b_id = ref_match.id
                    m.source_b_role = role
                wired_count += 1
                return True
        elif placeholder in code_to_match:
            ref_match = code_to_match[placeholder]
            bracket_label = ""
            mc = m.match_code or ""
            for bl in ("BWW", "BWL", "BLW", "BLL"):
                if bl in mc:
                    bracket_label = bl[1:]
                    break
            if bracket_label in ("WW", "LW"):
                role = "WINNER"
            else:
                role = "LOSER"
            if side == "A":
                m.source_match_a_id = ref_match.id
                m.source_a_role = role
            else:
                m.source_match_b_id = ref_match.id
                m.source_b_role = role
            wired_count += 1
            return True
        return False

    for m in matches:
        if m.match_type not in ("MAIN", "CONSOLATION"):
            continue

        _wire_placeholder(m, m.placeholder_side_a, "A")
        _wire_placeholder(m, m.placeholder_side_b, "B")

    if wired_count:
        session.flush()
        logger.debug(
            "Wired %d source links for %d bracket matches (event %s)",
            wired_count, len(bracket_only), spec.event_name,
        )

    return matches, warnings


# -----------------------------------------------------------------------------
# Spec Builder Helper
# -----------------------------------------------------------------------------

def build_spec_from_event(event, draw_plan: Optional[dict] = None) -> DrawPlanSpec:
    """
    Build a DrawPlanSpec from an Event model and optional parsed draw_plan.
    """
    import json

    if draw_plan is None and event.draw_plan_json:
        try:
            draw_plan = json.loads(event.draw_plan_json)
        except (json.JSONDecodeError, TypeError, AttributeError):
            draw_plan = {}

    draw_plan = draw_plan or {}

    template_type = draw_plan.get("template_type", "RR_ONLY")
    wf_rounds = draw_plan.get("wf_rounds", 0)

    return DrawPlanSpec(
        event_id=event.id,
        event_name=event.name,
        division="Mixed" if event.category == "mixed" else "Women's",
        team_count=event.team_count or 0,
        template_type=template_type,
        template_key=normalize_template_key(template_type),
        guarantee=event.guarantee_selected or 5,
        waterfall_rounds=wf_rounds,
        waterfall_minutes=event.wf_block_minutes or 60,
        standard_minutes=event.standard_block_minutes or 120,
        tournament_id=event.tournament_id,
        event_category=event.category,
    )
