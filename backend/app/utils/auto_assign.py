"""
Auto-Assign V1: Deterministic match-to-slot assignment

This module implements a deterministic first-fit algorithm that assigns
pre-generated matches to pre-generated schedule slots.

Non-goals (V1):
- Team assignment / team injection
- Home/away logic
- Rest rules or match spacing
- Day targeting / time preferences
- Court balancing heuristics
- "Best fit" optimization
- Any randomness
"""

import re
from collections import defaultdict
from datetime import datetime, time
from typing import Any, Dict, List, Optional, Set, Tuple

from sqlmodel import Session, select

from app.models.match import Match
from app.models.match_assignment import MatchAssignment
from app.models.schedule_slot import ScheduleSlot
from app.models.schedule_version import ScheduleVersion

# Stage precedence mapping (hard-coded, authoritative)
# WF=1, RR=2 (pools), MAIN=3 (brackets), CONSOLATION=4, PLACEMENT=5
STAGE_PRECEDENCE = {"WF": 1, "RR": 2, "MAIN": 3, "CONSOLATION": 4, "PLACEMENT": 5}

VALID_STAGES = set(STAGE_PRECEDENCE.keys())


class AutoAssignError(Exception):
    """Base exception for auto-assign errors"""

    pass


class AutoAssignValidationError(AutoAssignError):
    """Validation failed before assignment"""

    pass


class AutoAssignResult:
    """Structured result from auto-assign operation"""

    def __init__(self):
        self.assigned_count = 0
        self.unassigned_count = 0
        self.unassigned_matches: List[Dict[str, Any]] = []
        self.assigned_examples: List[Dict[str, Any]] = []
        self.total_matches = 0
        self.total_slots = 0
        self.duration_ms: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "assigned_count": self.assigned_count,
            "unassigned_count": self.unassigned_count,
            "total_matches": self.total_matches,
            "total_slots": self.total_slots,
            "success_rate": round(self.assigned_count / self.total_matches * 100, 1) if self.total_matches > 0 else 0,
            "unassigned_matches": self.unassigned_matches,
            "assigned_examples": self.assigned_examples[:10],  # First 10 for sanity
            "duration_ms": self.duration_ms,
        }


def get_match_sort_key(match: Match) -> Tuple:
    """
    Generate deterministic sort key for matches.

    Order: stage_order → round_index → sequence_in_round → id

    This ensures:
    - WF matches process first
    - Then MAIN (QF → SF → Final)
    - Then CONSOLATION (Tier 1 → Tier 2)
    - Then PLACEMENT

    NOTE: This does NOT include event ordering. Callers that need
    event-priority ordering (largest draw first) should use their
    own sort key — see assign_with_scope and assign_by_match_ids.
    """
    stage_order = STAGE_PRECEDENCE.get(match.match_type, 999)

    return (stage_order, match.round_index or 999, match.sequence_in_round or 999, match.id or 999)


def get_slot_sort_key(slot: ScheduleSlot) -> Tuple:
    """
    Generate deterministic sort key for slots.

    Order: start_time → court_label → id

    This ensures slots are filled chronologically, court-by-court.
    """
    # Convert time to minutes from midnight for sorting
    start_minutes = slot.start_time.hour * 60 + slot.start_time.minute if slot.start_time else 0

    return (slot.day_date, start_minutes, slot.court_label or "", slot.id or 999)


def validate_inputs(matches: List[Match], slots: List[ScheduleSlot], schedule_version_id: int) -> None:
    """
    Perform sanity checks before auto-assign.

    Raises AutoAssignValidationError if validation fails.
    """
    # Check non-empty
    if not matches:
        raise AutoAssignValidationError("Match list is empty")

    if not slots:
        raise AutoAssignValidationError("Slot list is empty")

    # Check for duplicate slot IDs
    slot_ids = [s.id for s in slots if s.id is not None]
    if len(slot_ids) != len(set(slot_ids)):
        raise AutoAssignValidationError("Duplicate slot IDs detected")

    # Validate match metadata
    for match in matches:
        # Check stage is valid
        if match.match_type not in VALID_STAGES:
            raise AutoAssignValidationError(
                f"Match {match.id} ({match.match_code}) has invalid stage: {match.match_type}"
            )

        # Check round_index and sequence_in_round are non-null
        if match.round_index is None:
            raise AutoAssignValidationError(f"Match {match.id} ({match.match_code}) has null round_index")

        if match.sequence_in_round is None:
            raise AutoAssignValidationError(f"Match {match.id} ({match.match_code}) has null sequence_in_round")

        # Check schedule_version_id matches
        if match.schedule_version_id != schedule_version_id:
            raise AutoAssignValidationError(
                f"Match {match.id} belongs to version {match.schedule_version_id}, expected {schedule_version_id}"
            )

    # Validate slot metadata
    for slot in slots:
        if slot.schedule_version_id != schedule_version_id:
            raise AutoAssignValidationError(
                f"Slot {slot.id} belongs to version {slot.schedule_version_id}, expected {schedule_version_id}"
            )


def is_slot_compatible(slot: ScheduleSlot, match: Match, occupied_slot_ids: set) -> Tuple[bool, Optional[str]]:
    """
    Check if a slot is compatible for a match.

    Returns: (is_compatible, reason_if_not)

    V1 compatibility rules:
    1. Slot is unassigned (not in occupied_slot_ids)
    2. Slot duration >= match duration
    3. Same schedule_version_id (already validated in validate_inputs)
    """
    # Check if slot is already occupied
    if slot.id in occupied_slot_ids:
        return False, "SLOT_OCCUPIED"

    # Check duration compatibility
    # For V1, we use block_minutes as the slot capacity
    slot_duration = slot.block_minutes or 0
    if slot_duration < match.duration_minutes:
        return False, "DURATION_TOO_LONG"

    return True, None


def _extract_division(match_code: str) -> str:
    """Extract bracket division from match_code (BWW/BWL/BLW/BLL), or '' if none."""
    m = re.search(r'B(WW|WL|LW|LL)[_]', match_code or "")
    return m.group(1) if m else ""


# Cache for bracket-tier classification — rebuilt per assign_by_match_ids call
_bracket_tier_cache: Dict[int, str] = {}


def _build_bracket_tier_cache(
    all_matches: List[Match],
) -> Dict[int, str]:
    """
    Classify every MAIN/CONSOLATION match as 'qf', 'sf', or 'final' using
    position-from-end logic within each event+stage+division group.

    Returns {match_id: tier}.
    """
    cache: Dict[int, str] = {}
    groups: Dict[str, List[Match]] = defaultdict(list)

    for m in all_matches:
        if m.match_type not in ("MAIN", "CONSOLATION"):
            continue
        div = _extract_division(m.match_code or "")
        key = f"{m.event_id}|{m.match_type}|{div}"
        groups[key].append(m)

    for group_matches in groups.values():
        sorted_group = sorted(
            group_matches, key=lambda x: (x.round_index or 0, x.sequence_in_round or 0)
        )
        n = len(sorted_group)
        if n == 0:
            continue
        elif n == 1:
            cache[sorted_group[0].id] = "final"
        elif n <= 3:
            cache[sorted_group[-1].id] = "final"
            for m in sorted_group[:-1]:
                cache[m.id] = "sf"
        else:
            cache[sorted_group[-1].id] = "final"
            for m in sorted_group[-3:-1]:
                cache[m.id] = "sf"
            for m in sorted_group[:-3]:
                cache[m.id] = "qf"

    return cache


def _get_bracket_prerequisites(
    match: Match,
    tier: str,
    all_matches: List[Match],
    bracket_tier_cache: Dict[int, str],
) -> List[Match]:
    """
    Return the prerequisite matches for a bracket match based on its tier.

    - QF → empty (no prerequisites)
    - SF → all QFs in the same event + stage + division
    - Final → all SFs in the same event + stage + division
    """
    if tier == "qf":
        return []

    target_tier = "qf" if tier == "sf" else "sf"
    div = _extract_division(match.match_code or "")

    prereqs: List[Match] = []
    for m in all_matches:
        if (
            m.event_id == match.event_id
            and m.match_type == match.match_type
            and _extract_division(m.match_code or "") == div
            and bracket_tier_cache.get(m.id) == target_tier
        ):
            prereqs.append(m)
    return prereqs


def check_round_dependencies_for_auto_assign(
    session: Session,
    match: Match,
    slot: ScheduleSlot,
    schedule_version_id: int,
    assigned_match_ids: set,
    bracket_tier_cache: Optional[Dict[int, str]] = None,
    all_version_matches: Optional[List[Match]] = None,
    match_by_id: Optional[Dict[int, Match]] = None,
) -> Tuple[bool, Optional[str]]:
    """
    Stage-aware dependency + rest-gap check for auto-assign.

    Rules by stage:
    - **WF:** round_index N requires all WF round_index N-1 in same event
              assigned and finished with rest gap.
    - **RR:** round_index N requires all RR round_index N-1 in same event
              assigned and finished with rest gap.
    - **MAIN / CONSOLATION (bracket):**
        - If source_match_a_id / source_match_b_id are wired, use those
          as the actual prerequisites (accurate for consolation brackets).
        - Otherwise fall back to position-from-end tier classification:
            QF → independent, SF → QFs, Final → SFs.
    - **PLACEMENT:** No dependency.

    Rest gap: prereq_end + match_duration <= target_slot_start
    (Effectively skips one full time slot between a team's consecutive matches.)

    Returns: (is_valid, reason_if_not)
    """
    stage = match.match_type

    # ── PLACEMENT: no dependency ──
    if stage == "PLACEMENT":
        return True, None

    # Convert target slot to absolute minutes (days * 1440 + time)
    slot_day_offset = (slot.day_date.toordinal() if slot.day_date else 0) * 1440
    slot_start_abs = slot_day_offset + (
        slot.start_time.hour * 60 + slot.start_time.minute if slot.start_time else 0
    )

    # ── Helper: check a list of prerequisite matches ──
    def _check_prereqs(
        prereqs: List[Match], label: str, use_rest_gap: bool = True
    ) -> Tuple[bool, Optional[str]]:
        """
        Verify all prerequisite matches are assigned and finished in time.

        Args:
            prereqs: Prerequisite match objects.
            label: Human-readable label for error messages.
            use_rest_gap: If True, enforce a full match-duration rest gap
                between the prereq's end and the target slot start (suitable
                for WF/RR where the *same* teams play consecutive rounds).
                If False, only require that the prereq finishes before the
                target slot starts — no extra gap (suitable for bracket
                matches where advancing teams already had rest while
                waiting for the bracket to progress).
        """
        for pm in prereqs:
            if pm.id not in assigned_match_ids:
                return False, f"Dependency: {label} not yet assigned"

            pa = session.exec(
                select(MatchAssignment).where(
                    MatchAssignment.schedule_version_id == schedule_version_id,
                    MatchAssignment.match_id == pm.id,
                )
            ).first()
            if not pa:
                continue

            ps = session.get(ScheduleSlot, pa.slot_id)
            if not ps or not ps.start_time:
                continue

            # Use absolute minutes (day * 1440 + time) for cross-day safety
            prereq_day_offset = (ps.day_date.toordinal() if ps.day_date else 0) * 1440
            prereq_start = prereq_day_offset + (
                ps.start_time.hour * 60 + ps.start_time.minute
            )
            prereq_end = prereq_start + pm.duration_minutes

            if use_rest_gap:
                # WF / RR: same teams play both rounds — enforce a full
                # match-duration rest gap (skip at least one time slot).
                if prereq_end + pm.duration_minutes > slot_start_abs:
                    return False, f"Rest gap: too close to {label}"
            else:
                # Bracket (MAIN / CONSOLATION): only require the prereq
                # to have finished before the target slot starts.
                if prereq_end > slot_start_abs:
                    return False, f"Ordering: {label} not yet finished"

        return True, None

    # ── WF: sequential round dependency ──
    if stage == "WF":
        if match.round_index is None or match.round_index <= 1:
            return True, None
        prereq_round = match.round_index - 1
        prereqs = session.exec(
            select(Match).where(
                Match.schedule_version_id == schedule_version_id,
                Match.event_id == match.event_id,
                Match.match_type == "WF",
                Match.round_index == prereq_round,
            )
        ).all()
        if not prereqs:
            return True, None
        return _check_prereqs(prereqs, f"WF R{prereq_round}")

    # ── RR: sequential round dependency ──
    if stage == "RR":
        if match.round_index is None or match.round_index <= 1:
            return True, None
        prereq_round = match.round_index - 1
        prereqs = session.exec(
            select(Match).where(
                Match.schedule_version_id == schedule_version_id,
                Match.event_id == match.event_id,
                Match.match_type == "RR",
                Match.round_index == prereq_round,
            )
        ).all()
        if not prereqs:
            return True, None
        return _check_prereqs(prereqs, f"RR R{prereq_round}")

    # ── MAIN / CONSOLATION: prefer actual source links, fall back to tier ──
    if stage in ("MAIN", "CONSOLATION"):
        # If the match has explicit source links (source_match_a_id /
        # source_match_b_id), use those as the real prerequisites instead
        # of the generic position-from-end tier classification.  This is
        # critical for consolation brackets where the dependency graph
        # doesn't follow a simple QF→SF→Final chain.
        has_source_a = match.source_match_a_id is not None
        has_source_b = match.source_match_b_id is not None

        if (has_source_a or has_source_b) and all_version_matches:
            # Build lookup (caller should ideally cache this, but we
            # keep it safe for the rare fallback path)
            match_by_id_local = (
                match_by_id if match_by_id is not None
                else {m.id: m for m in all_version_matches}
            )
            source_prereqs: List[Match] = []
            if has_source_a and match.source_match_a_id in match_by_id_local:
                source_prereqs.append(match_by_id_local[match.source_match_a_id])
            if has_source_b and match.source_match_b_id in match_by_id_local:
                source_prereqs.append(match_by_id_local[match.source_match_b_id])
            if source_prereqs:
                # Bracket matches: ordering only, no extra rest gap.
                # Teams advance through brackets with natural wait times
                # as they wait for other bracket matches to complete.
                return _check_prereqs(
                    source_prereqs, "source match prereqs",
                    use_rest_gap=False,
                )
            # Source links present but referenced matches not found — allow
            return True, None

        # Fallback: generic tier-based classification
        if bracket_tier_cache is None or all_version_matches is None:
            # Fallback: if no cache provided, QFs are independent (safe default)
            return True, None

        tier = bracket_tier_cache.get(match.id, "qf")
        if tier == "qf":
            return True, None  # QF matches are fully independent

        prereqs = _get_bracket_prerequisites(
            match, tier, all_version_matches, bracket_tier_cache
        )
        if not prereqs:
            return True, None
        # Bracket matches: ordering only, no extra rest gap
        return _check_prereqs(
            prereqs, f"bracket {tier} prereqs",
            use_rest_gap=False,
        )

    # Unknown stage — allow
    return True, None


def auto_assign_v1(session: Session, schedule_version_id: int, clear_existing: bool = True) -> AutoAssignResult:
    """
    Auto-Assign V1: Deterministic first-fit match-to-slot assignment.

    Args:
        session: Database session (must be in a transaction)
        schedule_version_id: Schedule version to assign
        clear_existing: If True, clear existing auto-assign assignments first (Option A)

    Returns:
        AutoAssignResult with assigned/unassigned counts and details

    Raises:
        AutoAssignValidationError: If input validation fails
        AutoAssignError: If assignment fails
    """
    start_time = datetime.utcnow()
    result = AutoAssignResult()

    # Verify schedule version exists
    version = session.get(ScheduleVersion, schedule_version_id)
    if not version:
        raise AutoAssignValidationError(f"Schedule version {schedule_version_id} not found")

    # Step 1: Clear existing assignments if requested (Option A)
    if clear_existing:
        existing_assignments = session.exec(
            select(MatchAssignment)
            .where(MatchAssignment.schedule_version_id == schedule_version_id)
            .where(MatchAssignment.assigned_by == "AUTO_ASSIGN_V1")
        ).all()

        for assignment in existing_assignments:
            session.delete(assignment)

        session.flush()

    # Step 2: Load matches in deterministic order
    matches = session.exec(
        select(Match)
        .where(Match.schedule_version_id == schedule_version_id)
        .order_by(Match.id)  # Initial fetch, will sort in Python
    ).all()

    # Sort matches deterministically
    matches_sorted = sorted(matches, key=get_match_sort_key)
    result.total_matches = len(matches_sorted)

    # Step 3: Load slots in deterministic order
    slots = session.exec(
        select(ScheduleSlot)
        .where(ScheduleSlot.schedule_version_id == schedule_version_id)
        .order_by(ScheduleSlot.id)  # Initial fetch, will sort in Python
    ).all()

    # Sort slots deterministically
    slots_sorted = sorted(slots, key=get_slot_sort_key)
    result.total_slots = len(slots_sorted)

    # Step 4: Validate inputs
    validate_inputs(matches_sorted, slots_sorted, schedule_version_id)

    # Step 5: Load existing assignments to track occupied slots
    existing_assignments = session.exec(
        select(MatchAssignment).where(MatchAssignment.schedule_version_id == schedule_version_id)
    ).all()

    occupied_slot_ids = {a.slot_id for a in existing_assignments}

    # Build bracket-tier cache for MAIN/CONSOLATION dependency checks
    bt_cache = _build_bracket_tier_cache(matches_sorted)
    mid_cache = {m.id: m for m in matches_sorted}

    # Step 6: First-fit assignment loop
    assigned_match_ids = set()

    for match in matches_sorted:
        assigned = False
        failure_reason = "NO_COMPATIBLE_SLOT"

        # Scan slots in order
        for slot in slots_sorted:
            compatible, reason = is_slot_compatible(slot, match, occupied_slot_ids)

            if compatible:
                # Check round dependencies
                round_deps_ok, round_deps_reason = check_round_dependencies_for_auto_assign(
                    session, match, slot, schedule_version_id, assigned_match_ids,
                    bracket_tier_cache=bt_cache, all_version_matches=matches_sorted,
                    match_by_id=mid_cache,
                )
                if not round_deps_ok:
                    # Track the failure reason
                    if failure_reason == "NO_COMPATIBLE_SLOT":
                        failure_reason = round_deps_reason or "ROUND_DEPENDENCY_VIOLATION"
                    continue
                # Create assignment
                assignment = MatchAssignment(
                    schedule_version_id=schedule_version_id,
                    match_id=match.id,
                    slot_id=slot.id,
                    assigned_by="AUTO_ASSIGN_V1",
                    assigned_at=datetime.utcnow(),
                )
                session.add(assignment)

                # Mark slot as occupied
                occupied_slot_ids.add(slot.id)
                assigned_match_ids.add(match.id)

                # Track for reporting
                result.assigned_count += 1
                if len(result.assigned_examples) < 10:
                    result.assigned_examples.append(
                        {
                            "match_id": match.id,
                            "match_code": match.match_code,
                            "stage": match.match_type,
                            "slot_id": slot.id,
                            "day": str(slot.day_date),
                            "start_time": str(slot.start_time),
                            "court": slot.court_label,
                        }
                    )

                assigned = True
                break
            else:
                # Track the first failure reason
                if failure_reason == "NO_COMPATIBLE_SLOT":
                    failure_reason = reason or "NO_COMPATIBLE_SLOT"

        # If not assigned, record as unassigned
        if not assigned:
            result.unassigned_count += 1
            result.unassigned_matches.append(
                {
                    "match_id": match.id,
                    "match_code": match.match_code,
                    "stage": match.match_type,
                    "round_index": match.round_index,
                    "sequence_in_round": match.sequence_in_round,
                    "duration_minutes": match.duration_minutes,
                    "reason": failure_reason,
                }
            )

    # Step 7: Flush assignments to DB
    session.flush()

    # Calculate duration
    end_time = datetime.utcnow()
    result.duration_ms = int((end_time - start_time).total_seconds() * 1000)

    return result


# Scope mapping for phased placement (Phase Flow V1)
SCOPE_FILTERS = {
    "WF_R1": lambda m: m.match_type == "WF" and m.round_number == 1,
    "WF_R2": lambda m: m.match_type == "WF" and m.round_number == 2,
    "RR_POOL": lambda m: m.match_type == "RR",
    "BRACKET_MAIN": lambda m: m.match_type == "MAIN",
    "ALL": lambda m: True,
}


def assign_with_scope(
    session: Session,
    schedule_version_id: int,
    scope: str,
    event_id: Optional[int] = None,
    clear_existing_assignments_in_scope: bool = False,
) -> AutoAssignResult:
    """
    Assign matches within a scope (WF_R1, WF_R2, RR_POOL, BRACKET_MAIN, ALL).

    Only assigns matches that are currently unassigned.
    Deterministic ordering: largest draw first (team_count DESC), then stage,
    round_index, sequence_in_round, match_code.
    """
    if scope not in SCOPE_FILTERS:
        raise AutoAssignValidationError(f"Invalid scope: {scope}. Must be one of {list(SCOPE_FILTERS.keys())}")

    filter_fn = SCOPE_FILTERS[scope]
    start_time = datetime.utcnow()
    result = AutoAssignResult()

    version = session.get(ScheduleVersion, schedule_version_id)
    if not version:
        raise AutoAssignValidationError(f"Schedule version {schedule_version_id} not found")

    # Load slots
    slots = session.exec(
        select(ScheduleSlot).where(ScheduleSlot.schedule_version_id == schedule_version_id)
    ).all()
    slots_sorted = sorted(slots, key=get_slot_sort_key)
    result.total_slots = len(slots_sorted)
    if not slots_sorted:
        raise AutoAssignValidationError("No slots exist. Generate slots first.")

    # Load all matches for version
    matches = session.exec(
        select(Match).where(Match.schedule_version_id == schedule_version_id)
    ).all()

    # Build event priority: largest draw first (team_count DESC), then by
    # event_id for deterministic tie-breaking within same-size events.
    from app.models.event import Event
    event_ids_in_matches = {m.event_id for m in matches}
    events = session.exec(
        select(Event).where(Event.id.in_(event_ids_in_matches))  # type: ignore[attr-defined]
    ).all()
    # Map event_id → (negative team_count for DESC, event_id for tie-break)
    event_sort_key: Dict[int, Tuple] = {
        e.id: (-(e.team_count or 0), e.id or 0) for e in events
    }

    # Filter by scope and event_id
    scope_matches = [m for m in matches if filter_fn(m) and (event_id is None or m.event_id == event_id)]

    # ── Phase-based sort ──────────────────────────────────────────────
    # Groups matches into scheduling phases so the first-fit fills them
    # in the correct day/priority order:
    #
    #   Phase 0 — WF  (Day 1 waterfall rounds)
    #   Phase 1 — RR + MAIN together (Day 2 bracket QFs and RR rounds)
    #   Phase 2 — CONSOLATION
    #   Phase 3 — PLACEMENT
    #
    # Within each phase, matches sort by:
    #   round_index → event_sort_key (largest draw first) → sequence → code
    #
    # Crucially, RR and MAIN share the same phase so MAIN QFs (round 1,
    # from 32-team events) sort BEFORE Mixed RR R1 (round 1, 16-team)
    # when they have the same round_index.  This produces the desired
    # largest-draws-first ordering across all event types.
    PHASE = {"WF": 0, "RR": 1, "MAIN": 1, "CONSOLATION": 2, "PLACEMENT": 3}
    scope_matches_sorted = sorted(
        scope_matches,
        key=lambda m: (
            PHASE.get(m.match_type, 999),
            m.round_index or 999,
            event_sort_key.get(m.event_id, (0, m.event_id or 0)),
            m.sequence_in_round or 999,
            m.match_code or "",
        ),
    )

    # Load existing assignments
    existing_assignments = session.exec(
        select(MatchAssignment).where(MatchAssignment.schedule_version_id == schedule_version_id)
    ).all()
    assigned_match_ids = {a.match_id for a in existing_assignments}

    # Optionally clear assignments for matches in scope
    if clear_existing_assignments_in_scope:
        scope_match_ids = {m.id for m in scope_matches_sorted}
        for a in existing_assignments:
            if a.match_id in scope_match_ids:
                session.delete(a)
        session.flush()
        remaining = session.exec(
            select(MatchAssignment).where(MatchAssignment.schedule_version_id == schedule_version_id)
        ).all()
        assigned_match_ids = {a.match_id for a in remaining}
        existing_assignments = remaining

    # Only process unassigned matches in scope
    to_assign = [m for m in scope_matches_sorted if m.id not in assigned_match_ids]
    result.total_matches = len(to_assign)

    if not to_assign:
        result.assigned_count = 0
        result.unassigned_count = 0
        result.duration_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)
        return result

    validate_inputs(to_assign, slots_sorted, schedule_version_id)
    occupied_slot_ids = {a.slot_id for a in session.exec(
        select(MatchAssignment).where(MatchAssignment.schedule_version_id == schedule_version_id)
    ).all()}

    # Build bracket-tier cache
    all_ver_matches = session.exec(
        select(Match).where(Match.schedule_version_id == schedule_version_id)
    ).all()
    bt_cache = _build_bracket_tier_cache(all_ver_matches)
    mid_cache = {m.id: m for m in all_ver_matches}

    assigned_match_ids = set(assigned_match_ids)

    for match in to_assign:
        assigned = False
        failure_reason = "NO_COMPATIBLE_SLOT"
        for slot in slots_sorted:
            compatible, reason = is_slot_compatible(slot, match, occupied_slot_ids)
            if compatible:
                round_deps_ok, round_deps_reason = check_round_dependencies_for_auto_assign(
                    session, match, slot, schedule_version_id, assigned_match_ids,
                    bracket_tier_cache=bt_cache, all_version_matches=all_ver_matches,
                    match_by_id=mid_cache,
                )
                if not round_deps_ok:
                    if failure_reason == "NO_COMPATIBLE_SLOT":
                        failure_reason = round_deps_reason or "ROUND_DEPENDENCY_VIOLATION"
                    continue
                assignment = MatchAssignment(
                    schedule_version_id=schedule_version_id,
                    match_id=match.id,
                    slot_id=slot.id,
                    assigned_by="ASSIGN_SCOPE_V1",
                    assigned_at=datetime.utcnow(),
                )
                session.add(assignment)
                occupied_slot_ids.add(slot.id)
                assigned_match_ids.add(match.id)
                result.assigned_count += 1
                if len(result.assigned_examples) < 10:
                    result.assigned_examples.append({
                        "match_id": match.id, "match_code": match.match_code, "stage": match.match_type,
                        "slot_id": slot.id, "day": str(slot.day_date), "start_time": str(slot.start_time),
                        "court": slot.court_label,
                    })
                assigned = True
                break
            else:
                if failure_reason == "NO_COMPATIBLE_SLOT":
                    failure_reason = reason or "NO_COMPATIBLE_SLOT"
        if not assigned:
            result.unassigned_count += 1
            result.unassigned_matches.append({
                "match_id": match.id, "match_code": match.match_code, "stage": match.match_type,
                "round_index": match.round_index, "sequence_in_round": match.sequence_in_round,
                "duration_minutes": match.duration_minutes, "reason": failure_reason,
            })

    session.flush()
    result.duration_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)
    return result


def assign_by_match_ids(
    session: Session,
    schedule_version_id: int,
    match_ids: List[int],
    target_day: Optional[Any] = None,
    target_time: Optional[Any] = None,
    min_start_time: Optional[Any] = None,
    blocked_slot_ids: Optional[set] = None,
) -> AutoAssignResult:
    """
    Assign a specific subset of matches by their IDs.

    Filters to only unassigned matches within the provided IDs, then runs the
    same deterministic first-fit algorithm used by assign_with_scope.

    The dependency check is stage-aware:
    - Bracket QFs are fully independent (no round-index chain).
    - SFs depend on their division's QFs with a rest gap.
    - WF/RR use sequential round dependency with rest gap.

    Args:
        session: Database session (must be in a transaction)
        schedule_version_id: Schedule version to assign
        match_ids: List of match IDs to assign (must belong to this version)
        target_day: If provided, only consider slots on this specific day.
            Prevents matches from leaking to other days when running a
            daily policy.
        target_time: If provided, only consider slots at this specific
            start_time.  Used by consolation fill to target a specific
            time slot.
        blocked_slot_ids: Slot IDs to exclude (blocked or locked-occupied).

    Returns:
        AutoAssignResult with assigned/unassigned counts and details
    """
    start_time_ts = datetime.utcnow()
    result = AutoAssignResult()

    version = session.get(ScheduleVersion, schedule_version_id)
    if not version:
        raise AutoAssignValidationError(f"Schedule version {schedule_version_id} not found")

    # Load slots — only active, optionally filtered to a single day/time
    slots = session.exec(
        select(ScheduleSlot).where(
            ScheduleSlot.schedule_version_id == schedule_version_id,
            ScheduleSlot.is_active == True,
        )
    ).all()
    if target_day is not None:
        slots = [s for s in slots if s.day_date == target_day]
    if target_time is not None:
        slots = [s for s in slots if s.start_time == target_time]
    if min_start_time is not None:
        slots = [s for s in slots if s.start_time > min_start_time]
    if blocked_slot_ids:
        slots = [s for s in slots if s.id not in blocked_slot_ids]
    slots_sorted = sorted(slots, key=get_slot_sort_key)
    result.total_slots = len(slots_sorted)
    if not slots_sorted:
        raise AutoAssignValidationError("No slots exist. Generate slots first.")

    # Load only the requested matches
    match_id_set = set(match_ids)
    all_matches = session.exec(
        select(Match).where(Match.schedule_version_id == schedule_version_id)
    ).all()
    target_matches = [m for m in all_matches if m.id in match_id_set]

    # Preserve caller's ordering: process matches in the order specified
    # by match_ids.  The caller (policy planner / frontend) is responsible
    # for providing a deterministic sort — we honour it so that event-
    # priority rotation and size-based ordering work correctly.
    match_id_order = {mid: idx for idx, mid in enumerate(match_ids)}
    target_matches_sorted = sorted(
        target_matches,
        key=lambda m: match_id_order.get(m.id, 999999),
    )

    # Load existing assignments — filter to only unassigned
    existing_assignments = session.exec(
        select(MatchAssignment).where(MatchAssignment.schedule_version_id == schedule_version_id)
    ).all()
    assigned_match_ids_set = {a.match_id for a in existing_assignments}

    to_assign = [m for m in target_matches_sorted if m.id not in assigned_match_ids_set]
    result.total_matches = len(to_assign)

    if not to_assign:
        result.assigned_count = 0
        result.unassigned_count = 0
        result.duration_ms = int((datetime.utcnow() - start_time_ts).total_seconds() * 1000)
        return result

    validate_inputs(to_assign, slots_sorted, schedule_version_id)
    occupied_slot_ids = {a.slot_id for a in existing_assignments}
    local_assigned_ids = set(assigned_match_ids_set)

    # Build bracket-tier cache from ALL version matches (not just this batch)
    bt_cache = _build_bracket_tier_cache(all_matches)
    mid_cache = {m.id: m for m in all_matches}

    for match in to_assign:
        assigned = False
        failure_reason = "NO_COMPATIBLE_SLOT"
        for slot in slots_sorted:
            compatible, reason = is_slot_compatible(slot, match, occupied_slot_ids)
            if compatible:
                round_deps_ok, round_deps_reason = check_round_dependencies_for_auto_assign(
                    session, match, slot, schedule_version_id, local_assigned_ids,
                    bracket_tier_cache=bt_cache, all_version_matches=all_matches,
                    match_by_id=mid_cache,
                )
                if not round_deps_ok:
                    if failure_reason == "NO_COMPATIBLE_SLOT":
                        failure_reason = round_deps_reason or "ROUND_DEPENDENCY_VIOLATION"
                    continue
                assignment = MatchAssignment(
                    schedule_version_id=schedule_version_id,
                    match_id=match.id,
                    slot_id=slot.id,
                    assigned_by="ASSIGN_SUBSET_V1",
                    assigned_at=datetime.utcnow(),
                )
                session.add(assignment)
                occupied_slot_ids.add(slot.id)
                local_assigned_ids.add(match.id)
                result.assigned_count += 1
                if len(result.assigned_examples) < 10:
                    result.assigned_examples.append({
                        "match_id": match.id, "match_code": match.match_code, "stage": match.match_type,
                        "slot_id": slot.id, "day": str(slot.day_date), "start_time": str(slot.start_time),
                        "court": slot.court_label,
                    })
                assigned = True
                break
            else:
                if failure_reason == "NO_COMPATIBLE_SLOT":
                    failure_reason = reason or "NO_COMPATIBLE_SLOT"
        if not assigned:
            result.unassigned_count += 1
            result.unassigned_matches.append({
                "match_id": match.id, "match_code": match.match_code, "stage": match.match_type,
                "round_index": match.round_index, "sequence_in_round": match.sequence_in_round,
                "duration_minutes": match.duration_minutes, "reason": failure_reason,
            })

    session.flush()
    result.duration_ms = int((datetime.utcnow() - start_time_ts).total_seconds() * 1000)
    return result
