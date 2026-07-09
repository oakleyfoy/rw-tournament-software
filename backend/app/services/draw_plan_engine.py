"""
Draw Plan Engine — Single source of truth for match inventory and generation.

This module is the authoritative engine for:
1. Schedule Builder inventory calculations
2. Match generation during "Build Schedule"

All template logic lives here. No other module should contain template math.
Validation rules are imported from draw_plan_rules.py (single source of truth).
"""

import logging
from dataclasses import dataclass, field
from typing import List, Literal, Optional, Tuple

# Import Phase 1 rules from the single source of truth
from app.services.draw_plan_rules import (
    ALLOWED_TEAM_COUNTS,
    calculate_rr_matches_for_pools,
    calculate_rr_only_matches,
    calculate_wf_matches,
    pool_config,
    required_wf_rounds,
    rr_pairings_by_round,
)
from app.services.wf_pairing import PairingResult, TeamSeed, build_wf_r1_pairings
from app.services.wf_wiring import WiringPlan, build_wf_r2_wiring
from app.utils.rr_wiring import wire_rr_match_placeholders

logger = logging.getLogger(__name__)


def _qf_wf_r2_slot_pair(qf_sequence: int, r2_w_feeders: int) -> Tuple[int, int]:
    """QF placeholder slots within one WF R2 track (W or L), indices 1..r2_w_feeders.

    For 8 feeders (typical 32-team divisions), pair consecutive WF R2 slots so public
    labels (W01→Winner A, W02→Winner B, …) read straight down the waterfall order:
    QF1=(1,2), QF2=(3,4), QF3=(5,6), QF4=(7,8).

    For 4 feeders (16-team field), use a fixed rotation so each QF hits valid codes.
    """
    if not 1 <= qf_sequence <= 4:
        raise ValueError(f"qf_sequence must be 1..4, got {qf_sequence}")
    if r2_w_feeders >= 8:
        pairs = [(1, 2), (3, 4), (5, 6), (7, 8)]
        return pairs[qf_sequence - 1]
    if r2_w_feeders == 4:
        pairs = [(1, 2), (3, 4), (2, 3), (4, 1)]
        return pairs[qf_sequence - 1]
    if r2_w_feeders == 3:
        pairs = [(1, 2), (2, 3), (1, 3), (3, 1)]
        return pairs[qf_sequence - 1]
    if r2_w_feeders == 2:
        pairs = [(1, 2), (1, 2), (1, 2), (1, 2)]
        return pairs[qf_sequence - 1]
    raise ValueError(f"Unsupported WF R2 feeder count: {r2_w_feeders}")


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

    from sqlmodel import select

    from app.models.team import Team

    teams = session.exec(select(Team).where(Team.event_id == event_id)).all()

    if len(teams) < n:
        return None

    by_id = {t.id: t for t in teams}
    seed_teams: List[TeamSeed] = []
    for tid in linked_team_ids[:n]:
        t = by_id.get(tid)
        if not t or t.seed is None:
            return None
        seed_teams.append(
            TeamSeed(
                seed=t.seed,
                team_id=t.id,
                avoid_group=getattr(t, "avoid_group", None),
                display_name=getattr(t, "display_name", None),
                name=getattr(t, "name", None),
                rating=getattr(t, "rating", None),
            )
        )

    seed_teams.sort(key=lambda x: x.seed)
    if [t.seed for t in seed_teams] != list(range(1, n + 1)):
        return None

    return build_wf_r1_pairings(seed_teams, n)


def _load_teams_by_seed(session, event_id: int) -> dict:
    """Load team objects indexed by seed for partial binding.

    Returns {seed: Team} for every team that has a seed assigned.
    Used as fallback when the full pairing engine can't run
    (not all teams imported yet).
    """
    from sqlmodel import select

    from app.models.team import Team

    teams = session.exec(select(Team).where(Team.event_id == event_id)).all()
    return {t.seed: t for t in teams if t.seed is not None}


def _get_wf_r2_wiring(session, event_id: int, r1_matches: list) -> WiringPlan:
    """
    Load teams for the event and compute WF R2 wiring.

    Uses consecutive R1 pairs (``block_size=2``): WF R2 winners are W(R1_k) vs
    W(R1_{k+1}) for k = 1,3,5,…; losers bracket uses the same adjacency on the
    prior WF round. R1 ``sequence_in_round`` order must match the intended bracket.
    """
    from sqlmodel import select

    from app.models.team import Team

    try:
        teams = session.exec(select(Team).where(Team.event_id == event_id)).all()
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
BRACKET_MATCHES_G4 = 9  # 7 main + 2 consolation tier1
BRACKET_MATCHES_G5 = 12  # 7 main + 2 consolation tier1 + 1 tier2 + 2 placement

# Division display name mapping (bracket label -> user-facing name)
DIVISION_DISPLAY_NAMES = {
    "WW": "Division I",
    "WL": "Division II",
    "LW": "Division III",
    "LL": "Division IV",
}

# Supported event families (includes legacy WF_TO_POOLS_4)
EventFamily = Literal[
    "RR_ONLY", "WF_TO_POOLS_4", "WF_TO_POOLS_DYNAMIC", "WF_TO_BRACKETS_8", "WF_14_TOP2_BYE", "UNSUPPORTED"
]

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
    template_type: str  # Raw from DB/UI
    template_key: str  # Normalized (uppercase, underscores)
    guarantee: int  # 4 or 5
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

    if key == "WF_14_TOP2_BYE":
        return "WF_14_TOP2_BYE"

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
        errors.append(f"WF_TO_POOLS_DYNAMIC supports team_count in {{{','.join(map(str, allowed))}}}, got {n}")
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


def _compute_wf_14_top2_bye(spec: DrawPlanSpec) -> InventoryCounts:
    from app.services.wf_14_format import (
        REQUIRED_WF_ROUNDS,
        TEAM_COUNT,
        wf_14_total_consolation_matches,
        wf_14_total_matches,
        wf_14_total_rr_pool_matches,
        wf_14_total_wf_matches,
    )

    errors: List[str] = []
    if spec.team_count != TEAM_COUNT:
        errors.append(f"WF_14_TOP2_BYE requires team_count={TEAM_COUNT}, got {spec.team_count}")
    if spec.waterfall_rounds != REQUIRED_WF_ROUNDS:
        errors.append(f"WF_14_TOP2_BYE requires waterfall_rounds={REQUIRED_WF_ROUNDS}, got {spec.waterfall_rounds}")
    if errors:
        return InventoryCounts(errors=errors)

    wf = wf_14_total_wf_matches()
    rr = wf_14_total_rr_pool_matches()
    cons = wf_14_total_consolation_matches()
    return InventoryCounts(
        wf_matches=wf,
        bracket_matches=0,
        rr_matches=rr,
        total_matches=wf_14_total_matches(),
        counts_by_stage={"WF": wf, "RR_POOL": rr, "MAIN": cons},
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

    logger.debug("compute_inventory: event_id=%s family=%s template_key=%s", spec.event_id, family, spec.template_key)

    if family == "RR_ONLY":
        return _compute_rr_only(spec)

    if family == "WF_TO_POOLS_4":
        return _compute_wf_to_pools_4(spec)

    if family == "WF_TO_POOLS_DYNAMIC":
        return _compute_wf_to_pools_dynamic(spec)

    if family == "WF_14_TOP2_BYE":
        return _compute_wf_14_top2_bye(spec)

    if family == "WF_TO_BRACKETS_8":
        return _compute_wf_to_brackets_8(spec)

    # Unsupported
    return InventoryCounts(errors=[f"Unsupported template: {spec.template_type!r} (key={spec.template_key})"])


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
            code = m.match_code or ""
            if "CONS_FRI" in code and day_count >= 1:
                m.preferred_day = day_weekdays[0]
            elif "CONS_SAT" in code and day_count >= 2:
                m.preferred_day = day_weekdays[1]
            elif day_count >= 3:
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
        raise RuntimeError("generate_matches_for_event called outside build_schedule_v1")

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
    elif family == "WF_14_TOP2_BYE":
        from app.services.wf_14_generator import generate_wf_14_matches

        matches, warnings = generate_wf_14_matches(session, version_id, spec, linked_team_ids)
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
            f"RR_ONLY requires {n} linked teams, got {len(linked_team_ids)}; generating matches with available teams"
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

    prefix = spec.match_code_prefix

    # -------------------------------------------------------------------------
    # WF Round 1: 8 matches — avoid-group-aware pairing (falls back to half-split)
    # -------------------------------------------------------------------------
    half = 8
    r1_matches = []
    pairing = _get_wf_r1_pairing(session, spec.event_id, linked_team_ids, 16)
    # Fallback: load whatever teams exist by seed for partial binding
    team_by_seed = _load_teams_by_seed(session, spec.event_id) if not pairing else {}

    for i in range(half):
        if pairing:
            seed_a, seed_b = pairing.pairs[i]
            team_a_id = pairing.team_id_pairs[i][0]
            team_b_id = pairing.team_id_pairs[i][1]
            # WF R1: use full name for match cards
            name_a, name_b = pairing.name_pairs[i]
            placeholder_a = name_a or f"Seed {seed_a}"
            placeholder_b = name_b or f"Seed {seed_b}"
        else:
            seed_a = i + 1
            seed_b = i + half + 1
            ta = team_by_seed.get(seed_a)
            tb = team_by_seed.get(seed_b)
            team_a_id = ta.id if ta else None
            team_b_id = tb.id if tb else None
            # WF R1: use full name for match cards
            placeholder_a = (ta.name if ta else None) or f"Seed {seed_a}"
            placeholder_b = (tb.name if tb else None) or f"Seed {seed_b}"

        match = Match(
            tournament_id=spec.tournament_id,
            event_id=spec.event_id,
            schedule_version_id=version_id,
            match_code=f"{prefix}WF_R1_{i + 1:02d}",
            match_type="WF",
            round_number=1,
            round_index=1,
            sequence_in_round=i + 1,
            team_a_id=team_a_id,
            team_b_id=team_b_id,
            placeholder_side_a=placeholder_a,
            placeholder_side_b=placeholder_b,
            duration_minutes=spec.waterfall_minutes,
        )
        matches.append(match)
        r1_matches.append(match)

    if pairing and pairing.conflicts:
        for c in pairing.conflicts:
            warnings.append(
                f"W_WF_R1_AVOID_GROUP_CONFLICT: seed {c.seed_a} vs seed {c.seed_b} (both group '{c.group}')"
            )

    # Flush to get R1 match IDs
    session.add_all(r1_matches)
    session.flush()

    # -------------------------------------------------------------------------
    # WF Round 2: 8 matches (4 winners bracket + 4 losers bracket)
    # WF Round 2: consecutive R1 pairs → same WF R2 match (W then L brackets)
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
                match_code=f"{prefix}POOL{pool_label}_RR_{rr_idx + 1:02d}",
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
        warnings.append(f"WF_TO_POOLS_DYNAMIC with {n} teams requires wf_rounds={expected_wf_rounds}, got {wf_rounds}")
        return matches, warnings

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
    # Fallback: load whatever teams exist by seed for partial binding
    team_by_seed = _load_teams_by_seed(session, spec.event_id) if not pairing else {}

    for i in range(matches_per_wf_round):
        if pairing:
            seed_a, seed_b = pairing.pairs[i]
            team_a_id = pairing.team_id_pairs[i][0]
            team_b_id = pairing.team_id_pairs[i][1]
            # WF R1: use full name for match cards
            name_a, name_b = pairing.name_pairs[i]
            placeholder_a = name_a or f"Seed {seed_a}"
            placeholder_b = name_b or f"Seed {seed_b}"
        else:
            seed_a = i + 1
            seed_b = i + half + 1
            ta = team_by_seed.get(seed_a)
            tb = team_by_seed.get(seed_b)
            team_a_id = ta.id if ta else None
            team_b_id = tb.id if tb else None
            # WF R1: use full name for match cards
            placeholder_a = (ta.name if ta else None) or f"Seed {seed_a}"
            placeholder_b = (tb.name if tb else None) or f"Seed {seed_b}"

        match = Match(
            tournament_id=spec.tournament_id,
            event_id=spec.event_id,
            schedule_version_id=version_id,
            match_code=f"{prefix}WF_R1_{i + 1:02d}",
            match_type="WF",
            round_number=1,
            round_index=1,
            sequence_in_round=i + 1,
            team_a_id=team_a_id,
            team_b_id=team_b_id,
            placeholder_side_a=placeholder_a,
            placeholder_side_b=placeholder_b,
            duration_minutes=spec.waterfall_minutes,
        )
        matches.append(match)
        r1_matches.append(match)

    if pairing and pairing.conflicts:
        for c in pairing.conflicts:
            warnings.append(
                f"W_WF_R1_AVOID_GROUP_CONFLICT: seed {c.seed_a} vs seed {c.seed_b} (both group '{c.group}')"
            )

    # Flush to get R1 match IDs for dependency wiring
    session.add_all(r1_matches)
    session.flush()

    # -------------------------------------------------------------------------
    # WF Round 2 (if wf_rounds >= 2): n/2 matches
    # WF Round 2: consecutive R1 pairs → same WF R2 match (W then L brackets)
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
    pool_labels = [chr(ord("A") + i) for i in range(pools_count)]  # A, B, C, ...
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
                match_code=f"{prefix}POOL{pool_label}_RR_{rr_idx + 1:02d}",
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
            # Fallback: load whatever teams exist by seed for partial binding
            team_by_seed = _load_teams_by_seed(session, spec.event_id) if not pairing else {}

            for i in range(matches_in_round):
                if pairing:
                    seed_a, seed_b = pairing.pairs[i]
                    team_a_id = pairing.team_id_pairs[i][0]
                    team_b_id = pairing.team_id_pairs[i][1]
                    # WF R1: use full name for match cards
                    name_a, name_b = pairing.name_pairs[i]
                    placeholder_a = name_a or f"Seed {seed_a}"
                    placeholder_b = name_b or f"Seed {seed_b}"
                else:
                    seed_a = i + 1
                    seed_b = i + half_r1 + 1
                    ta = team_by_seed.get(seed_a)
                    tb = team_by_seed.get(seed_b)
                    team_a_id = ta.id if ta else None
                    team_b_id = tb.id if tb else None
                    # WF R1: use full name for match cards
                    placeholder_a = (ta.name if ta else None) or f"Seed {seed_a}"
                    placeholder_b = (tb.name if tb else None) or f"Seed {seed_b}"

                match = Match(
                    tournament_id=spec.tournament_id,
                    event_id=spec.event_id,
                    schedule_version_id=version_id,
                    match_code=f"{prefix}WF_R{wf_round}_{i + 1:02d}",
                    match_type="WF",
                    round_number=wf_round,
                    round_index=wf_round,
                    sequence_in_round=i + 1,
                    team_a_id=team_a_id,
                    team_b_id=team_b_id,
                    placeholder_side_a=placeholder_a,
                    placeholder_side_b=placeholder_b,
                    duration_minutes=spec.waterfall_minutes,
                )
                matches.append(match)
                round_matches.append(match)

            if pairing and pairing.conflicts:
                for c in pairing.conflicts:
                    warnings.append(
                        f"W_WF_R1_AVOID_GROUP_CONFLICT: seed {c.seed_a} vs seed {c.seed_b} (both group '{c.group}')"
                    )
        else:
            # Subsequent WF rounds: dependency-driven from previous round
            # Flush previous round to get IDs
            session.add_all(prev_round_matches)
            session.flush()

            # WF R2+: consecutive prev-round matches feed each WF match (block_size=2)
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
                    placeholder_side_a=f"W(R{wf_round - 1}_{prev_seq_a})",
                    placeholder_side_b=f"W(R{wf_round - 1}_{prev_seq_b})",
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
                    placeholder_side_a=f"L(R{wf_round - 1}_{prev_seq_a})",
                    placeholder_side_b=f"L(R{wf_round - 1}_{prev_seq_b})",
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

    # WF R2+ rows are created after the prior round flush but never flushed in the
    # last loop iteration; bracket _wire_placeholder needs real IDs in code_to_match.
    wf_pending = [m for m in matches if m.match_type == "WF" and m.id is None]
    if wf_pending:
        session.add_all(wf_pending)
        session.flush()

    # -------------------------------------------------------------------------
    # Generate Bracket Matches (8-team brackets with G4/G5 consolation)
    # -------------------------------------------------------------------------

    def get_qf_wf_r2_tokens(event_prefix: str, bracket_label: str, qf_sequence: int) -> tuple[str, str]:
        """
        Generate WF R2 match_code tokens for a division bracket QF.

        Feeds (WF Round 2 = one winners-bracket column ``W..`` + one losers ``L..``):
            - BWW (WW): winners of green R2 matches → token_type W, role WINNER when wired.
            - BWL (WL): losers of those same green R2 matches → token_type W, role LOSER.
            - BLW (LW): winners of orange R2 matches → token_type L, role WINNER.
            - BLL (LL): losers of orange R2 matches → token_type L, role LOSER.

        For 32-team fields, WW/WL still use ``W01``–``W08`` and LW/LL use ``L01``–``L08``
        (same ordinal slots as the green track; there is no second R2 octet in inventory).
        """
        if bracket_label in ("WW", "WL"):
            token_type = "W"
        elif bracket_label in ("LW", "LL"):
            token_type = "L"
        else:
            raise ValueError(f"Unknown bracket_label: {bracket_label}")

        wf_r2_feeders = n // 4 if wf_rounds >= 2 else 0
        sa, sb = _qf_wf_r2_slot_pair(qf_sequence, wf_r2_feeders)

        return (
            f"{event_prefix}_WF_R2_{token_type}{sa:02d}",
            f"{event_prefix}_WF_R2_{token_type}{sb:02d}",
        )

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
    event_prefix = prefix.rstrip("_") if prefix.endswith("_") else prefix

    # QF pairing for 8 WF R2 feeders: sequential (1v2, 3v4, 5v6, 7v8) — matches waterfall order / Winner A,B,C… labels.
    # For 4 feeders, get_qf_wf_r2_tokens uses the fixed rotation in _qf_wf_r2_slot_pair.

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
                    sequence_in_round = match_idx + 1  # 1..4 for QFs
                elif match_idx < 6:
                    round_index = 2
                    sequence_in_round = match_idx - 4 + 1  # 1..2 for SFs
                else:
                    round_index = 3
                    sequence_in_round = 1  # 1 for Final

                # Determine placeholders based on bracket round
                if match_idx < 4:
                    # QF matches: WF R2 tokens via get_qf_wf_r2_tokens (bracket shell when 8 feeders)
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
                consolation_match_number = match_idx - 6  # C1..C5 across the bracket
                # C1,C2 (match_idx 7,8) = Round 1 (consolation semis)
                # C3,C4,C5 (match_idx 9,10,11) = Round 2 (cons final + SF losers + cons semi losers)
                if match_idx <= 8:
                    round_index = 1
                    sequence_in_round = match_idx - 6  # 1, 2
                else:
                    round_index = 2
                    sequence_in_round = match_idx - 8  # 1, 2, 3 within round 2

                # Consolation placeholders reference a fixed per-bracket path:
                # C1 (Cons SF): LOSER of QF1 vs LOSER of QF2
                # C2 (Cons SF): LOSER of QF3 vs LOSER of QF4
                # C3 (Cons Final): WINNER of C1 vs WINNER of C2
                # C4 (Drop-In): LOSER of C1 vs LOSER of C2
                # C5 (Drop-In): LOSER of Main SF1 (M5) vs LOSER of Main SF2 (M6)
                # etc.
                if consolation_match_number == 1:
                    # Cons SF 1: LOSER of QF1 vs LOSER of QF2
                    qf1_code = f"{prefix}B{bracket_label}_M1"
                    qf2_code = f"{prefix}B{bracket_label}_M2"
                    placeholder_a = f"LOSER:{qf1_code}"
                    placeholder_b = f"LOSER:{qf2_code}"
                elif consolation_match_number == 2:
                    # Cons SF 2: LOSER of QF3 vs LOSER of QF4
                    qf3_code = f"{prefix}B{bracket_label}_M3"
                    qf4_code = f"{prefix}B{bracket_label}_M4"
                    placeholder_a = f"LOSER:{qf3_code}"
                    placeholder_b = f"LOSER:{qf4_code}"
                elif consolation_match_number == 3:
                    # Cons Final: WINNER of C1 vs WINNER of C2 (winners of consolation semi-finals)
                    c1_code = f"{prefix}B{bracket_label}_C1"
                    c2_code = f"{prefix}B{bracket_label}_C2"
                    placeholder_a = f"WINNER:{c1_code}"
                    placeholder_b = f"WINNER:{c2_code}"
                elif consolation_match_number == 4:
                    # First drop-in: LOSER of C1 vs LOSER of C2
                    c1_code = f"{prefix}B{bracket_label}_C1"
                    c2_code = f"{prefix}B{bracket_label}_C2"
                    placeholder_a = f"LOSER:{c1_code}"
                    placeholder_b = f"LOSER:{c2_code}"
                elif consolation_match_number == 5:
                    # Second drop-in: LOSER of Main SF1 vs LOSER of Main SF2
                    sf1_code = f"{prefix}B{bracket_label}_M5"
                    sf2_code = f"{prefix}B{bracket_label}_M6"
                    placeholder_a = f"LOSER:{sf1_code}"
                    placeholder_b = f"LOSER:{sf2_code}"
                else:
                    # Additional consolation matches (Placement, etc.)
                    # Reference prior matches deterministically
                    prev_match_idx = match_idx - 1
                    prev_sub_code = f"C{prev_match_idx - 6}" if prev_match_idx >= 7 else f"M{prev_match_idx + 1}"
                    prev_code = f"{prefix}B{bracket_label}_{prev_sub_code}"
                    placeholder_a = f"LOSER:{prev_code}"
                    placeholder_b = f"TBD:{bracket_label}_C{sequence_in_round}"  # Placeholder for complex cases

            # Validation: ensure no legacy placeholders
            assert not placeholder_a.startswith("Bracket "), (
                f"Legacy placeholder detected in placeholder_a: '{placeholder_a}'"
            )
            assert not placeholder_b.startswith("Bracket "), (
                f"Legacy placeholder detected in placeholder_b: '{placeholder_b}'"
            )
            assert not placeholder_a.startswith("Division "), (
                f"Legacy placeholder detected in placeholder_a: '{placeholder_a}'"
            )
            assert not placeholder_b.startswith("Division "), (
                f"Legacy placeholder detected in placeholder_b: '{placeholder_b}'"
            )
            # Also check for " TBD" suffix (old format)
            assert " TBD" not in placeholder_a or placeholder_a.startswith("TBD:"), (
                f"Legacy 'TBD' placeholder detected in placeholder_a: '{placeholder_a}'"
            )
            assert " TBD" not in placeholder_b or placeholder_b.startswith("TBD:"), (
                f"Legacy 'TBD' placeholder detected in placeholder_b: '{placeholder_b}'"
            )

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
    # WF matches were flushed after the waterfall loop (including R2+ IDs).
    bracket_only = [m for m in matches if m.match_type in ("MAIN", "CONSOLATION") and m.id is None]
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
            wired_count,
            len(bracket_only),
            spec.event_name,
        )

    return matches, warnings


# -----------------------------------------------------------------------------
# Spec Builder Helper
# -----------------------------------------------------------------------------


def normalize_draw_plan_for_team_count(team_count: int, draw_plan: Optional[dict]) -> dict:
    """
    Align template_type / wf_rounds with Phase-1 rules for team_count.
    Fixes stale draw_plan_json (e.g. WF_TO_POOLS_DYNAMIC saved before 14-team template existed).
    """
    from app.services.draw_plan_rules import get_valid_family_for_team_count, required_wf_rounds

    plan = dict(draw_plan or {})
    family = get_valid_family_for_team_count(team_count)
    if family == "WF_14_TOP2_BYE":
        plan["template_type"] = "WF_14_TOP2_BYE"
        plan["wf_rounds"] = required_wf_rounds("WF_14_TOP2_BYE", team_count)
    return plan


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

    draw_plan = normalize_draw_plan_for_team_count(event.team_count or 0, draw_plan or {})

    template_type = draw_plan.get("template_type", "RR_ONLY")
    wf_rounds = draw_plan.get("wf_rounds", 0)
    timing = draw_plan.get("timing") if isinstance(draw_plan.get("timing"), dict) else {}

    # Prefer timing persisted in draw_plan_json (source of truth from Draw Builder),
    # and fall back to event columns for older records.
    wf_minutes = timing.get("wf_block_minutes")
    if not isinstance(wf_minutes, int) or wf_minutes <= 0:
        wf_minutes = event.wf_block_minutes or 60
    standard_minutes = timing.get("standard_block_minutes")
    if not isinstance(standard_minutes, int) or standard_minutes <= 0:
        standard_minutes = event.standard_block_minutes or 120

    return DrawPlanSpec(
        event_id=event.id,
        event_name=event.name,
        division="Mixed" if event.category == "mixed" else "Women's",
        team_count=event.team_count or 0,
        template_type=template_type,
        template_key=normalize_template_key(template_type),
        guarantee=event.guarantee_selected or 5,
        waterfall_rounds=wf_rounds,
        waterfall_minutes=wf_minutes,
        standard_minutes=standard_minutes,
        tournament_id=event.tournament_id,
        event_category=event.category,
    )


def repair_existing_drop_in_wiring(
    session,
    schedule_version_id: int,
    event_id: Optional[int] = None,
) -> int:
    """Repair stale C4/C5 drop-in wiring for already-generated brackets."""
    from sqlmodel import select

    from app.models.match import Match

    query = select(Match).where(Match.schedule_version_id == schedule_version_id)
    if event_id is not None:
        query = query.where(Match.event_id == event_id)

    matches = session.exec(query).all()
    if not matches:
        return 0

    code_to_match = {m.match_code: m for m in matches if m.match_code}
    repaired = 0

    def _loser_team_id(source_match: Match) -> Optional[int]:
        winner_id = source_match.winner_team_id
        if winner_id is None:
            return None
        if (source_match.runtime_status or "SCHEDULED") != "FINAL":
            return None
        if source_match.team_a_id is not None and winner_id == source_match.team_a_id:
            return source_match.team_b_id
        if source_match.team_b_id is not None and winner_id == source_match.team_b_id:
            return source_match.team_a_id
        return None

    def _repair_side(match: Match, side: str, source_code: str) -> bool:
        source_match = code_to_match.get(source_code)
        if source_match is None or source_match.id is None:
            return False

        placeholder = f"LOSER:{source_code}"
        resolved_team_id = _loser_team_id(source_match)
        changed = False

        if side == "A":
            if match.source_match_a_id != source_match.id:
                match.source_match_a_id = source_match.id
                changed = True
            if match.source_a_role != "LOSER":
                match.source_a_role = "LOSER"
                changed = True
            if match.placeholder_side_a != placeholder:
                match.placeholder_side_a = placeholder
                changed = True
            if (match.runtime_status or "SCHEDULED") != "FINAL" and match.team_a_id != resolved_team_id:
                match.team_a_id = resolved_team_id
                changed = True
        else:
            if match.source_match_b_id != source_match.id:
                match.source_match_b_id = source_match.id
                changed = True
            if match.source_b_role != "LOSER":
                match.source_b_role = "LOSER"
                changed = True
            if match.placeholder_side_b != placeholder:
                match.placeholder_side_b = placeholder
                changed = True
            if (match.runtime_status or "SCHEDULED") != "FINAL" and match.team_b_id != resolved_team_id:
                match.team_b_id = resolved_team_id
                changed = True

        return changed

    for match in matches:
        match_code = (match.match_code or "").strip()
        if (match.match_type or "").upper() != "CONSOLATION" or not match_code:
            continue

        if match_code.endswith("_C4"):
            prefix = match_code[:-3]
            changed = _repair_side(match, "A", f"{prefix}_C1")
            changed = _repair_side(match, "B", f"{prefix}_C2") or changed
        elif match_code.endswith("_C5"):
            prefix = match_code[:-3]
            changed = _repair_side(match, "A", f"{prefix}_M5")
            changed = _repair_side(match, "B", f"{prefix}_M6") or changed
        else:
            continue

        if changed:
            session.add(match)
            repaired += 1

    if repaired:
        session.flush()
        logger.info(
            "Repaired %d stale drop-in matches for version %s event %s",
            repaired,
            schedule_version_id,
            event_id,
        )

    return repaired


def repair_bracket_placeholder_source_wiring(
    session,
    schedule_version_id: int,
    event_id: Optional[int] = None,
) -> int:
    """
    Populate source_match_a_id / source_match_b_id from placeholders when missing.

    Bracket rows often store placeholders like ``WINNER:..._M1`` or a raw
    ``{prefix}_WF_R2_W01`` token equal to a WF match_code. If the FK wiring
    step never ran (older builds, partial migrations, or clone quirks), the
    public bracket shows generic "Winner I" text and consolation layout
    breaks because source ids are absent.

    Idempotent: only fills sides where the corresponding source_*_id is NULL.
    """
    from sqlmodel import select

    from app.models.match import Match

    query = select(Match).where(Match.schedule_version_id == schedule_version_id)
    if event_id is not None:
        query = query.where(Match.event_id == event_id)

    matches = session.exec(query).all()
    if not matches:
        return 0

    code_to_match = {m.match_code: m for m in matches if m.match_code}
    sides_wired = 0

    def wire_side(m: Match, placeholder: Optional[str], side: str) -> None:
        nonlocal sides_wired
        ph = (placeholder or "").strip()
        if not ph:
            return
        if side == "A" and m.source_match_a_id is not None:
            return
        if side == "B" and m.source_match_b_id is not None:
            return

        ref_match: Optional[Match] = None
        role: Optional[str] = None

        if ":" in ph:
            parts = ph.split(":", 1)
            role_candidate = parts[0].strip().upper()
            ref_code = parts[1].strip() if len(parts) > 1 else ""
            if role_candidate in ("WINNER", "LOSER") and ref_code in code_to_match:
                ref_match = code_to_match[ref_code]
                role = role_candidate
        elif ph in code_to_match:
            ref_match = code_to_match[ph]
            mc = m.match_code or ""
            bracket_label = ""
            # Longer codes first so BWW does not pair with BWL, etc.
            for bl in ("BLL", "BLW", "BWL", "BWW"):
                if bl in mc:
                    bracket_label = bl[1:]
                    break
            if bracket_label in ("WW", "LW"):
                role = "WINNER"
            elif bracket_label in ("WL", "LL"):
                role = "LOSER"

        if ref_match and ref_match.id is not None and role in ("WINNER", "LOSER"):
            if side == "A":
                m.source_match_a_id = ref_match.id
                m.source_a_role = role
            else:
                m.source_match_b_id = ref_match.id
                m.source_b_role = role
            sides_wired += 1

    for m in matches:
        mt = (m.match_type or "").upper()
        if mt not in ("MAIN", "CONSOLATION"):
            continue
        before_a = m.source_match_a_id
        before_b = m.source_match_b_id
        wire_side(m, m.placeholder_side_a, "A")
        wire_side(m, m.placeholder_side_b, "B")
        if m.source_match_a_id != before_a or m.source_match_b_id != before_b:
            session.add(m)

    if sides_wired:
        session.flush()
        logger.info(
            "Repaired bracket placeholder wiring: %s sides for version %s event %s",
            sides_wired,
            schedule_version_id,
            event_id,
        )

    return sides_wired
