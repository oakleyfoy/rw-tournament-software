"""
Schedule Plan Report — Authoritative contract for schedule readiness.

Pure function that validates draw plans against match inventory and emits
deterministic, stable-ordered reports with blocking errors and warnings.

Every list is returned in stable order:
  - events sorted by event_id
  - errors/warnings sorted by (code, event_id, message)
"""

import json
import logging
import re
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel
from sqlmodel import Session, select

from app.services.draw_plan_engine import (
    DrawPlanSpec,
    build_spec_from_event,
    compute_inventory,
    resolve_event_family,
    bracket_inventory,
    bracket_matches_for_guarantee,
)
from app.services.draw_plan_rules import (
    pool_config,
    rr_round_count,
    rr_matches_per_pool,
)

logger = logging.getLogger(__name__)

# ============================================================================
# Pydantic Response Models
# ============================================================================


class PlanReportError(BaseModel):
    code: str
    message: str
    event_id: Optional[int] = None
    context: Optional[Dict[str, Any]] = None


class WaterfallInfo(BaseModel):
    rounds: int
    r1_matches: int
    r2_matches: int
    r2_sequences_total: int


class PoolsInfo(BaseModel):
    pool_count: int
    pool_size: int
    rr_rounds: int
    rr_matches: int


class BracketsInfo(BaseModel):
    divisions: int
    main_matches: int
    consolation_matches: int
    total_matches: int


class PlaceholderInfo(BaseModel):
    rr_wired: bool
    bracket_wired: bool
    bye_count: int


class InventoryInfo(BaseModel):
    expected_total: int
    actual_total: int


class EventReport(BaseModel):
    event_id: int
    name: str
    teams_count: int
    template_code: str
    waterfall: WaterfallInfo
    pools: PoolsInfo
    brackets: BracketsInfo
    placeholders: PlaceholderInfo
    inventory: InventoryInfo


class TotalsInfo(BaseModel):
    events: int
    matches_total: int


class SchedulePlanReport(BaseModel):
    tournament_id: int
    schedule_version_id: Optional[int] = None
    version_status: Optional[str] = None
    ok: bool
    blocking_errors: List[PlanReportError]
    warnings: List[PlanReportError]
    events: List[EventReport]
    totals: TotalsInfo


# ============================================================================
# Helpers
# ============================================================================


def _extract_seed(placeholder: str) -> Optional[int]:
    """Extract seed number from a SEED_<n> placeholder."""
    if placeholder and placeholder.startswith("SEED_"):
        try:
            return int(placeholder[5:])
        except (ValueError, IndexError):
            return None
    return None


def _extract_pool_label(match_code: str) -> Optional[str]:
    """Extract pool label from match_code, or 'SINGLE' for RR_ONLY."""
    if "POOL" in match_code and "_RR_" in match_code:
        idx_pool = match_code.index("POOL") + 4
        idx_rr = match_code.index("_RR_")
        return match_code[idx_pool:idx_rr]
    elif "_RR_" in match_code:
        return "SINGLE"
    return None


def _compute_waterfall_info(spec: DrawPlanSpec, family: str) -> WaterfallInfo:
    """Compute waterfall structural info from spec."""
    n = spec.team_count
    wf_rounds = spec.waterfall_rounds

    if family == "RR_ONLY" or wf_rounds == 0:
        return WaterfallInfo(rounds=0, r1_matches=0, r2_matches=0, r2_sequences_total=0)

    r1_matches = n // 2
    r2_matches = n // 2 if wf_rounds >= 2 else 0
    r2_sequences_total = r2_matches  # each R2 match is one sequence

    return WaterfallInfo(
        rounds=wf_rounds,
        r1_matches=r1_matches,
        r2_matches=r2_matches,
        r2_sequences_total=r2_sequences_total,
    )


def _compute_pools_info(spec: DrawPlanSpec, family: str) -> PoolsInfo:
    """Compute pool structural info from spec."""
    if family == "RR_ONLY":
        n = spec.team_count
        rr_rounds = rr_round_count(n)
        rr_matches = (n * (n - 1)) // 2
        return PoolsInfo(pool_count=1, pool_size=n, rr_rounds=rr_rounds, rr_matches=rr_matches)

    if family in ("WF_TO_POOLS_4", "WF_TO_POOLS_DYNAMIC"):
        pools_count, teams_per_pool = pool_config(spec.team_count)
        rr_rounds = rr_round_count(teams_per_pool)
        rr_per_pool = rr_matches_per_pool(teams_per_pool)
        return PoolsInfo(
            pool_count=pools_count,
            pool_size=teams_per_pool,
            rr_rounds=rr_rounds,
            rr_matches=pools_count * rr_per_pool,
        )

    # Bracket-only events have no pools
    return PoolsInfo(pool_count=0, pool_size=0, rr_rounds=0, rr_matches=0)


def _compute_brackets_info(spec: DrawPlanSpec, family: str) -> BracketsInfo:
    """Compute bracket structural info from spec."""
    if family != "WF_TO_BRACKETS_8":
        return BracketsInfo(divisions=0, main_matches=0, consolation_matches=0, total_matches=0)

    n = spec.team_count
    if n == 8:
        k = 1
    elif n in (12, 16):
        k = 2
    else:
        k = 4

    brk = bracket_inventory(spec.guarantee)
    main_matches = k * brk["BRACKET_MAIN"]
    consolation = k * (brk["CONSOLATION_T1"] + brk["CONSOLATION_T2"] + brk["PLACEMENT"])
    total = k * brk["TOTAL"]

    return BracketsInfo(
        divisions=k,
        main_matches=main_matches,
        consolation_matches=consolation,
        total_matches=total,
    )


# ============================================================================
# Validation Checks (run against actual matches when version exists)
# ============================================================================


def _check_rr_placeholders(
    matches: list,
    event_id: int,
    errors: List[PlanReportError],
) -> Tuple[bool, int]:
    """
    Check RR match placeholder wiring.

    Returns:
        (rr_wired: bool, bye_count: int)
    """
    rr_matches = [m for m in matches if getattr(m, "match_type", "") == "RR"]
    if not rr_matches:
        return (True, 0)

    rr_wired = True
    bye_count = 0

    for m in rr_matches:
        pa = getattr(m, "placeholder_side_a", "") or ""
        pb = getattr(m, "placeholder_side_b", "") or ""

        # Check for BYE
        if pa.upper() == "BYE" or pb.upper() == "BYE":
            bye_count += 1
            continue

        # Both sides must have SEED_ placeholder
        if not pa.startswith("SEED_") or not pb.startswith("SEED_"):
            rr_wired = False
            errors.append(PlanReportError(
                code="E_RR_MATCH_MISSING_PLACEHOLDER",
                message=f"RR match {m.match_code} missing SEED_ placeholder "
                        f"(side_a={pa!r}, side_b={pb!r})",
                event_id=event_id,
                context={"match_id": m.id, "match_code": m.match_code},
            ))

    return (rr_wired, bye_count)


def _check_rr_top2_last_round(
    matches: list,
    event_id: int,
    spec: DrawPlanSpec,
    family: str,
    errors: List[PlanReportError],
) -> None:
    """Check that top-2 seeds in each pool play in the last RR round."""
    rr_matches = [m for m in matches if getattr(m, "match_type", "") == "RR"]
    if not rr_matches:
        return

    # Group by pool
    pools: Dict[str, list] = defaultdict(list)
    for m in rr_matches:
        label = _extract_pool_label(m.match_code) or "SINGLE"
        pools[label].append(m)

    # Determine pool structure
    if family == "RR_ONLY":
        pool_labels_expected = ["SINGLE"]
        pool_size = spec.team_count
    elif family in ("WF_TO_POOLS_4", "WF_TO_POOLS_DYNAMIC"):
        pools_count, pool_size = pool_config(spec.team_count)
        pool_labels_expected = [chr(ord("A") + i) for i in range(pools_count)]
    else:
        return  # No RR pools in bracket-only events

    for pool_idx, pool_label in enumerate(pool_labels_expected):
        pool_key = pool_label if pool_label != "SINGLE" else "SINGLE"
        pool_matches = pools.get(pool_key, [])
        if not pool_matches:
            continue

        # Find max round for this pool
        max_round = max(
            getattr(m, "round_index", 0) or getattr(m, "round_number", 0) or 0
            for m in pool_matches
        )
        if max_round == 0:
            continue

        # Get matches in the last round
        last_round_matches = [
            m for m in pool_matches
            if (getattr(m, "round_index", 0) or getattr(m, "round_number", 0) or 0) == max_round
        ]

        # Determine top-2 seeds for this pool
        top1 = pool_idx * pool_size + 1
        top2 = pool_idx * pool_size + 2

        # Check if top-2 play each other in last round
        found = False
        for m in last_round_matches:
            seed_a = _extract_seed(getattr(m, "placeholder_side_a", "") or "")
            seed_b = _extract_seed(getattr(m, "placeholder_side_b", "") or "")
            if seed_a is not None and seed_b is not None:
                if {seed_a, seed_b} == {top1, top2}:
                    found = True
                    break

        if not found:
            errors.append(PlanReportError(
                code="E_RR_TOP2_NOT_LAST_ROUND",
                message=f"Pool {pool_label}: seeds {top1} and {top2} not matched "
                        f"in final RR round {max_round}",
                event_id=event_id,
                context={
                    "pool": pool_label,
                    "top1_seed": top1,
                    "top2_seed": top2,
                    "last_round": max_round,
                },
            ))


def _check_bracket_placeholders(
    matches: list,
    event_id: int,
    errors: List[PlanReportError],
) -> bool:
    """
    Check bracket match placeholder validity.

    Returns:
        bracket_wired: bool
    """
    bracket_matches = [
        m for m in matches
        if getattr(m, "match_type", "") in ("MAIN", "CONSOLATION")
    ]
    if not bracket_matches:
        return True

    bracket_wired = True
    valid_patterns = [
        re.compile(r"^WINNER:.+$"),
        re.compile(r"^LOSER:.+$"),
        re.compile(r"^.+_WF_R\d+_[WL]\d+$"),
        re.compile(r"^TBD:.+$"),
    ]

    for m in bracket_matches:
        for side_attr in ("placeholder_side_a", "placeholder_side_b"):
            placeholder = getattr(m, side_attr, "") or ""
            if not placeholder:
                bracket_wired = False
                errors.append(PlanReportError(
                    code="E_BRACKET_PLACEHOLDER_INVALID_SOURCE",
                    message=f"Bracket match {m.match_code} has empty {side_attr}",
                    event_id=event_id,
                    context={"match_id": m.id, "match_code": m.match_code},
                ))
                continue

            # Check against known patterns
            if not any(p.match(placeholder) for p in valid_patterns):
                bracket_wired = False
                errors.append(PlanReportError(
                    code="E_BRACKET_PLACEHOLDER_INVALID_SOURCE",
                    message=f"Bracket match {m.match_code} has invalid placeholder "
                            f"{side_attr}={placeholder!r}",
                    event_id=event_id,
                    context={"match_id": m.id, "match_code": m.match_code, "placeholder": placeholder},
                ))

    return bracket_wired


def _check_cross_division_leak(
    matches: list,
    event_id: int,
    errors: List[PlanReportError],
) -> None:
    """Check bracket matches don't reference sources from other divisions."""
    bracket_matches = [
        m for m in matches
        if getattr(m, "match_type", "") in ("MAIN", "CONSOLATION")
    ]
    if not bracket_matches:
        return

    # Group by bracket label (extract B{label} from match_code)
    bracket_pattern = re.compile(r"B(WW|WL|LW|LL)_")

    for m in bracket_matches:
        mc = m.match_code or ""
        match_bracket = bracket_pattern.search(mc)
        if not match_bracket:
            continue
        my_label = match_bracket.group(1)

        for side_attr in ("placeholder_side_a", "placeholder_side_b"):
            placeholder = getattr(m, side_attr, "") or ""
            # Check WINNER:/LOSER: references
            if ":" in placeholder:
                ref_code = placeholder.split(":", 1)[1]
                ref_bracket = bracket_pattern.search(ref_code)
                if ref_bracket and ref_bracket.group(1) != my_label:
                    errors.append(PlanReportError(
                        code="E_CROSS_DIVISION_LEAK",
                        message=f"Match {mc} (bracket {my_label}) references "
                                f"{ref_code} from bracket {ref_bracket.group(1)}",
                        event_id=event_id,
                        context={
                            "match_code": mc,
                            "my_bracket": my_label,
                            "referenced_bracket": ref_bracket.group(1),
                        },
                    ))


def _check_duplicate_placeholder_slots(
    matches: list,
    event_id: int,
    errors: List[PlanReportError],
) -> None:
    """Check for duplicate SEED_ slots in same pool+round."""
    rr_matches = [m for m in matches if getattr(m, "match_type", "") == "RR"]
    if not rr_matches:
        return

    # Group by (pool_label, round)
    round_slots: Dict[Tuple[str, int], List[Tuple[str, str, str]]] = defaultdict(list)

    for m in rr_matches:
        pool = _extract_pool_label(m.match_code) or "SINGLE"
        rnd = getattr(m, "round_index", 0) or getattr(m, "round_number", 0) or 0
        pa = getattr(m, "placeholder_side_a", "") or ""
        pb = getattr(m, "placeholder_side_b", "") or ""
        round_slots[(pool, rnd)].append((m.match_code, pa, pb))

    for (pool, rnd), entries in sorted(round_slots.items()):
        seen_seeds: Dict[int, str] = {}
        for mc, pa, pb in entries:
            for placeholder in (pa, pb):
                seed = _extract_seed(placeholder)
                if seed is not None:
                    if seed in seen_seeds:
                        errors.append(PlanReportError(
                            code="E_DUPLICATE_PLACEHOLDER_SLOTS",
                            message=f"Seed {seed} appears in multiple matches in "
                                    f"pool {pool} round {rnd}: {seen_seeds[seed]} and {mc}",
                            event_id=event_id,
                            context={
                                "seed": seed,
                                "pool": pool,
                                "round": rnd,
                                "match_1": seen_seeds[seed],
                                "match_2": mc,
                            },
                        ))
                    else:
                        seen_seeds[seed] = mc


# ============================================================================
# Main Builder Function
# ============================================================================


def build_schedule_plan_report(
    session: Session,
    tournament_id: int,
    version_id: Optional[int] = None,
) -> SchedulePlanReport:
    """
    Build a deterministic schedule plan report.

    Pure function: read-only, no mutations.

    Args:
        session: DB session
        tournament_id: Tournament ID
        version_id: Optional schedule version ID. If provided, validates
                     actual match inventory. If None, validates draw plans only.

    Returns:
        SchedulePlanReport with deterministic, stable-ordered fields.
    """
    from app.models.event import Event
    from app.models.match import Match
    from app.models.schedule_version import ScheduleVersion
    from app.models.tournament import Tournament

    blocking_errors: List[PlanReportError] = []
    warnings: List[PlanReportError] = []
    event_reports: List[EventReport] = []

    # ── Load tournament ──────────────────────────────────────────────────
    tournament = session.get(Tournament, tournament_id)
    if not tournament:
        return SchedulePlanReport(
            tournament_id=tournament_id,
            schedule_version_id=version_id,
            version_status=None,
            ok=False,
            blocking_errors=[PlanReportError(
                code="E_TOURNAMENT_NOT_FOUND",
                message=f"Tournament {tournament_id} not found",
            )],
            warnings=[],
            events=[],
            totals=TotalsInfo(events=0, matches_total=0),
        )

    # ── Load version (optional) ──────────────────────────────────────────
    version = None
    version_status = None
    if version_id is not None:
        version = session.get(ScheduleVersion, version_id)
        if not version:
            blocking_errors.append(PlanReportError(
                code="E_VERSION_NOT_FOUND",
                message=f"Schedule version {version_id} not found",
            ))
        elif version.tournament_id != tournament_id:
            blocking_errors.append(PlanReportError(
                code="E_VERSION_NOT_FOUND",
                message=f"Schedule version {version_id} does not belong to tournament {tournament_id}",
            ))
            version = None
        else:
            version_status = version.status

    # ── Load events (sorted by event_id for determinism) ─────────────────
    all_events = session.exec(
        select(Event)
        .where(Event.tournament_id == tournament_id)
        .order_by(Event.id)
    ).all()

    # Only consider finalized events for the report
    finalized_events = [e for e in all_events if e.draw_status == "final"]

    # Warn about non-finalized events
    for e in all_events:
        if e.draw_status != "final":
            warnings.append(PlanReportError(
                code="W_EVENT_NOT_FINALIZED",
                message=f"Event '{e.name}' (id={e.id}) has draw_status='{e.draw_status or 'none'}'",
                event_id=e.id,
            ))

    # ── Load actual matches (if version exists) ──────────────────────────
    matches_by_event: Dict[int, list] = defaultdict(list)
    if version is not None:
        all_matches = session.exec(
            select(Match)
            .where(
                Match.tournament_id == tournament_id,
                Match.schedule_version_id == version.id,
            )
            .order_by(Match.event_id, Match.id)
        ).all()
        for m in all_matches:
            matches_by_event[m.event_id].append(m)

    # ── Process each finalized event ─────────────────────────────────────
    total_expected = 0
    total_actual = 0

    for event in finalized_events:
        spec = build_spec_from_event(event)
        inv = compute_inventory(spec)
        family = resolve_event_family(spec)

        # Structural info
        wf_info = _compute_waterfall_info(spec, family)
        pools_info = _compute_pools_info(spec, family)
        brackets_info = _compute_brackets_info(spec, family)

        expected_total = inv.total_matches
        actual_matches = matches_by_event.get(event.id, [])
        actual_total = len(actual_matches)

        total_expected += expected_total
        total_actual += actual_total

        # ── Inventory validation errors from engine ──────────────────────
        if inv.has_errors():
            for err_msg in inv.errors:
                blocking_errors.append(PlanReportError(
                    code="E_DRAW_PLAN_INVALID",
                    message=err_msg,
                    event_id=event.id,
                ))

        # ── E_EVENT_ZERO_MATCHES ─────────────────────────────────────────
        if expected_total == 0 and event.team_count >= 2:
            blocking_errors.append(PlanReportError(
                code="E_EVENT_ZERO_MATCHES",
                message=f"Event '{event.name}' produces 0 expected matches "
                        f"with {event.team_count} teams",
                event_id=event.id,
            ))

        # ── Placeholder + inventory checks (only when version exists) ────
        rr_wired = True
        bracket_wired = True
        bye_count = 0

        if version is not None:
            # E_INVENTORY_MISMATCH
            if expected_total != actual_total:
                blocking_errors.append(PlanReportError(
                    code="E_INVENTORY_MISMATCH",
                    message=f"Event '{event.name}': expected {expected_total} matches, "
                            f"found {actual_total}",
                    event_id=event.id,
                    context={
                        "expected": expected_total,
                        "actual": actual_total,
                    },
                ))

            # RR placeholder checks
            rr_wired, bye_count = _check_rr_placeholders(
                actual_matches, event.id, blocking_errors
            )

            # RR top-2-last-round check
            _check_rr_top2_last_round(
                actual_matches, event.id, spec, family, blocking_errors
            )

            # Bracket placeholder checks
            bracket_wired = _check_bracket_placeholders(
                actual_matches, event.id, blocking_errors
            )

            # Cross-division leak check
            _check_cross_division_leak(
                actual_matches, event.id, blocking_errors
            )

            # Duplicate placeholder slots check
            _check_duplicate_placeholder_slots(
                actual_matches, event.id, blocking_errors
            )

            # Warnings
            if bye_count > 0:
                warnings.append(PlanReportError(
                    code="W_BYE_IN_PARTIAL_POOL",
                    message=f"Event '{event.name}' has {bye_count} BYE match(es)",
                    event_id=event.id,
                    context={"bye_count": bye_count},
                ))

        # ── Build event report ───────────────────────────────────────────
        event_reports.append(EventReport(
            event_id=event.id,
            name=event.name,
            teams_count=event.team_count,
            template_code=spec.template_key,
            waterfall=wf_info,
            pools=pools_info,
            brackets=brackets_info,
            placeholders=PlaceholderInfo(
                rr_wired=rr_wired,
                bracket_wired=bracket_wired,
                bye_count=bye_count,
            ),
            inventory=InventoryInfo(
                expected_total=expected_total,
                actual_total=actual_total,
            ),
        ))

    # ── Sort errors and warnings for determinism ─────────────────────────
    blocking_errors.sort(key=lambda e: (e.code, e.event_id or 0, e.message))
    warnings.sort(key=lambda e: (e.code, e.event_id or 0, e.message))

    # ── Compute ok ───────────────────────────────────────────────────────
    ok = len(blocking_errors) == 0 and len(finalized_events) > 0

    return SchedulePlanReport(
        tournament_id=tournament_id,
        schedule_version_id=version.id if version else None,
        version_status=version_status,
        ok=ok,
        blocking_errors=blocking_errors,
        warnings=warnings,
        events=event_reports,
        totals=TotalsInfo(
            events=len(finalized_events),
            matches_total=total_expected,
        ),
    )
