"""
Policy Invariant Verifier
=========================
Hard-stop safety envelope around schedule policy runs.

Every invariant is checked after placement. If any violation is found,
the run is rolled back and an InvariantReport is returned with details.

Invariants:
  A) No team plays > 2 matches per day
  B) No team's 2nd match starts before every team has started their 1st
     (per event, per day)
  C) No unresolved placeholder is scheduled (upstream dependencies)
  D) Consolation rounds only appear if the full round fits
  E) Spare-court rules are satisfied
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, time
from typing import Any, Dict, List, Optional, Set, Tuple

from sqlmodel import Session, select
from sqlalchemy import func

from app.models import Event, Match, MatchAssignment, ScheduleSlot


# ─── Data structures ─────────────────────────────────────────────────────

@dataclass
class Violation:
    code: str
    message: str
    event_id: Optional[int] = None
    match_id: Optional[int] = None
    team_id: Optional[int] = None
    context: Optional[Dict[str, Any]] = None


@dataclass
class InvariantStats:
    teams_over_cap: int = 0
    fairness_violations: int = 0
    unresolved_scheduled: int = 0
    consolation_partial: int = 0
    spare_violations: int = 0


@dataclass
class InvariantReport:
    ok: bool
    violations: List[Violation] = field(default_factory=list)
    stats: InvariantStats = field(default_factory=InvariantStats)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "violations": [
                {
                    "code": v.code,
                    "message": v.message,
                    "event_id": v.event_id,
                    "match_id": v.match_id,
                    "team_id": v.team_id,
                    "context": v.context,
                }
                for v in self.violations
            ],
            "stats": {
                "teams_over_cap": self.stats.teams_over_cap,
                "fairness_violations": self.stats.fairness_violations,
                "unresolved_scheduled": self.stats.unresolved_scheduled,
                "consolation_partial": self.stats.consolation_partial,
                "spare_violations": self.stats.spare_violations,
            },
        }


# ─── Helper: load day assignments with slot/match data ────────────────────

def _load_day_assignments(
    session: Session,
    version_id: int,
    day_date: date,
) -> List[Tuple[MatchAssignment, Match, ScheduleSlot]]:
    """Load all assignments for a given day with their match and slot."""
    results = session.exec(
        select(MatchAssignment, Match, ScheduleSlot)
        .join(Match, MatchAssignment.match_id == Match.id)
        .join(ScheduleSlot, MatchAssignment.slot_id == ScheduleSlot.id)
        .where(
            MatchAssignment.schedule_version_id == version_id,
            ScheduleSlot.day_date == day_date,
        )
    ).all()
    return results


# ─── Invariant A: No team > 2 matches/day ────────────────────────────────

def _check_team_daily_cap(
    assignments: List[Tuple[MatchAssignment, Match, ScheduleSlot]],
    day: date,
    cap: int = 2,
) -> List[Violation]:
    """Check that no team plays more than `cap` matches on a single day."""
    team_counts: Dict[int, int] = defaultdict(int)
    team_matches: Dict[int, List[int]] = defaultdict(list)

    for _asn, match, _slot in assignments:
        for tid in (match.team_a_id, match.team_b_id):
            if tid is not None:
                team_counts[tid] += 1
                team_matches[tid].append(match.id)

    violations = []
    for tid, count in team_counts.items():
        if count > cap:
            violations.append(Violation(
                code="TEAM_OVER_DAILY_CAP",
                message=f"Team {tid} has {count} matches on {day} (cap={cap})",
                team_id=tid,
                context={"day": str(day), "count": count, "match_ids": team_matches[tid]},
            ))
    return violations


# ─── Invariant B: Fairness — no 2nd match before all play 1st ────────────

def _check_fairness_ordering(
    assignments: List[Tuple[MatchAssignment, Match, ScheduleSlot]],
    day: date,
) -> List[Violation]:
    """
    Per event, per day: no team's 2nd match starts before every team
    in that event has started their 1st match.
    """
    # Group by event
    event_teams: Dict[int, Dict[int, List[time]]] = defaultdict(lambda: defaultdict(list))
    for _asn, match, slot in assignments:
        for tid in (match.team_a_id, match.team_b_id):
            if tid is not None:
                event_teams[match.event_id][tid].append(slot.start_time)

    violations = []
    for event_id, teams in event_teams.items():
        # Sort each team's times
        for tid in teams:
            teams[tid].sort()

        # Find latest first-match time across all teams in this event
        first_match_times = [times[0] for times in teams.values() if times]
        if not first_match_times:
            continue
        latest_first = max(first_match_times)

        # Check: any team's 2nd match starts before latest_first?
        for tid, times in teams.items():
            if len(times) >= 2:
                second_match_time = times[1]
                if second_match_time < latest_first:
                    violations.append(Violation(
                        code="FAIRNESS_SECOND_BEFORE_ALL_FIRST",
                        message=(
                            f"Team {tid} plays 2nd match at {second_match_time} "
                            f"but some teams in event {event_id} don't start "
                            f"their 1st until {latest_first}"
                        ),
                        event_id=event_id,
                        team_id=tid,
                        context={
                            "day": str(day),
                            "second_match_time": str(second_match_time),
                            "latest_first_match": str(latest_first),
                        },
                    ))
    return violations


# ─── Invariant C: No unresolved placeholder scheduled ─────────────────────

def _check_unresolved_dependencies(
    assignments: List[Tuple[MatchAssignment, Match, ScheduleSlot]],
    all_assignments_by_match: Dict[int, Tuple[MatchAssignment, ScheduleSlot]],
    day: date,
) -> List[Violation]:
    """
    For every assigned match on this day:
    - If it depends on upstream matches (source_match_a_id/b_id),
      verify those upstream matches are assigned at an earlier time.
    """
    violations = []
    for _asn, match, slot in assignments:
        for src_id, role_label in [
            (match.source_match_a_id, "source_a"),
            (match.source_match_b_id, "source_b"),
        ]:
            if src_id is None:
                continue

            upstream = all_assignments_by_match.get(src_id)
            if upstream is None:
                violations.append(Violation(
                    code="UNRESOLVED_UPSTREAM_UNASSIGNED",
                    message=(
                        f"Match {match.id} ({match.match_code}) depends on "
                        f"match {src_id} ({role_label}) which is not assigned"
                    ),
                    match_id=match.id,
                    event_id=match.event_id,
                    context={
                        "day": str(day),
                        "source_match_id": src_id,
                        "role": role_label,
                    },
                ))
            else:
                _up_asn, up_slot = upstream
                # Upstream must be at an earlier time (or earlier day)
                if up_slot.day_date > slot.day_date or (
                    up_slot.day_date == slot.day_date
                    and up_slot.start_time >= slot.start_time
                ):
                    violations.append(Violation(
                        code="UNRESOLVED_UPSTREAM_NOT_BEFORE",
                        message=(
                            f"Match {match.id} ({match.match_code}) at "
                            f"{slot.start_time} depends on match {src_id} "
                            f"which is at {up_slot.start_time} (not earlier)"
                        ),
                        match_id=match.id,
                        event_id=match.event_id,
                        context={
                            "day": str(day),
                            "source_match_id": src_id,
                            "source_time": str(up_slot.start_time),
                            "this_time": str(slot.start_time),
                        },
                    ))
    return violations


# ─── Invariant D: Consolation rounds complete or absent ───────────────────

def _check_consolation_completeness(
    assignments: List[Tuple[MatchAssignment, Match, ScheduleSlot]],
    all_matches: List[Match],
    all_assignments_by_match: Dict[int, Tuple[Any, Any]],
    day: date,
) -> List[Violation]:
    """
    For each consolation round slice that appears in today's assignments,
    verify that all matches in that slice are assigned SOMEWHERE (this day
    or a later day).

    This correctly handles day-boundary overflow: if a round starts on
    Day 2 but some matches overflow to Day 3, that's fine as long as
    all matches in the round are assigned. Only flags a violation when
    matches from a round are partially assigned and others are completely
    unassigned.
    """
    # Build slices: (event_id, match_type, round_index) -> list of match IDs
    cons_slices: Dict[Tuple[int, str, int], List[int]] = defaultdict(list)
    for m in all_matches:
        if m.match_type == "CONSOLATION":
            key = (m.event_id, m.match_type, m.round_index or 0)
            cons_slices[key].append(m.id)

    # Which consolation slices appear on this day?
    slices_on_day: Set[Tuple[int, str, int]] = set()
    for _asn, match, _slot in assignments:
        if match.match_type == "CONSOLATION":
            key = (match.event_id, match.match_type, match.round_index or 0)
            slices_on_day.add(key)

    violations = []
    for key in slices_on_day:
        match_ids = cons_slices.get(key, [])
        total = len(match_ids)
        assigned_anywhere = sum(1 for mid in match_ids if mid in all_assignments_by_match)
        unassigned = total - assigned_anywhere

        if unassigned > 0:
            event_id, mt, ri = key
            violations.append(Violation(
                code="CONSOLATION_PARTIAL_ROUND",
                message=(
                    f"Event {event_id}: {mt} round_index={ri} has "
                    f"{assigned_anywhere}/{total} assigned globally "
                    f"({unassigned} unassigned)"
                ),
                event_id=event_id,
                context={
                    "day": str(day),
                    "match_type": mt,
                    "round_index": ri,
                    "assigned_globally": assigned_anywhere,
                    "total_in_round": total,
                    "unassigned": unassigned,
                },
            ))
    return violations


# ─── Invariant E: Spare-court rules ──────────────────────────────────────

def _check_spare_court_rules(
    session: Session,
    version_id: int,
    day: date,
    assignments: List[Tuple[MatchAssignment, Match, ScheduleSlot]],
    spare_policy_enabled: bool = True,
) -> List[Violation]:
    """
    Verify spare-court rules (conditional — only when spare_policy_enabled).

    When enabled:
    - First time slot of the day: no reserved spare required
    - All other time slots: at least 1 spare court (unassigned slot)

    When disabled (capacity-tight tournaments):
    - Spare violations are reported as warnings in context but do NOT
      count as hard-stop violations (returned list is empty).
    """
    if not spare_policy_enabled:
        return []

    # Load all active slots for this day
    all_slots = session.exec(
        select(ScheduleSlot).where(
            ScheduleSlot.schedule_version_id == version_id,
            ScheduleSlot.day_date == day,
            ScheduleSlot.is_active == True,
        )
    ).all()

    # Group by start_time
    by_time: Dict[time, List[ScheduleSlot]] = defaultdict(list)
    for s in all_slots:
        by_time[s.start_time].append(s)
    sorted_times = sorted(by_time.keys())

    # Count assigned per time slot
    assigned_slot_ids = {asn.slot_id for asn, _, _ in assignments}
    violations = []

    for i, t in enumerate(sorted_times):
        total = len(by_time[t])
        assigned = sum(1 for s in by_time[t] if s.id in assigned_slot_ids)
        spare = total - assigned

        if i == 0:
            continue  # first slot: no spare required

        if spare < 1:
            violations.append(Violation(
                code="SPARE_COURT_VIOLATION",
                message=(
                    f"Time slot {t} on {day}: {total} courts, "
                    f"{assigned} assigned, {spare} spare (need >= 1)"
                ),
                context={
                    "day": str(day),
                    "time": str(t),
                    "total_courts": total,
                    "assigned": assigned,
                    "spare": spare,
                },
            ))

    return violations


# ─── Capacity detection ──────────────────────────────────────────────────

def _is_capacity_tight(
    session: Session,
    version_id: int,
) -> bool:
    """
    Determine whether a tournament is capacity-tight (total matches >= total
    usable slots after reserving 1 spare per non-first time bucket per day).

    If capacity-tight, the spare-court invariant should be advisory rather
    than a hard stop, since there's no room for spares.
    """
    # Count total matches
    match_count = session.exec(
        select(func.count(Match.id)).where(
            Match.schedule_version_id == version_id
        )
    ).one()

    # Count total active slots
    all_slots = session.exec(
        select(ScheduleSlot).where(
            ScheduleSlot.schedule_version_id == version_id,
            ScheduleSlot.is_active == True,
        )
    ).all()

    # Compute usable slots (total minus 1 spare per non-first time bucket)
    from collections import defaultdict as _dd
    by_day_time: Dict[Tuple, int] = _dd(int)
    for s in all_slots:
        by_day_time[(s.day_date, s.start_time)] += 1

    day_times: Dict[object, List] = _dd(list)
    for (d, t), cnt in by_day_time.items():
        day_times[d].append((t, cnt))

    usable = 0
    for d, time_list in day_times.items():
        sorted_tl = sorted(time_list, key=lambda x: x[0])
        for i, (t, cnt) in enumerate(sorted_tl):
            reserve = 0 if i == 0 else 1
            usable += max(0, cnt - reserve)

    return match_count >= usable


# ─── Main verifier ────────────────────────────────────────────────────────

def verify_day(
    session: Session,
    tournament_id: int,
    version_id: int,
    day: date,
    spare_policy_enabled: bool = True,
) -> InvariantReport:
    """
    Run all invariant checks for a single day's assignments.
    Returns an InvariantReport with ok=True if all pass.

    Args:
        spare_policy_enabled: if False, spare-court check is skipped
            (auto-disabled for capacity-tight tournaments).
    """
    # Load this day's assignments
    day_assignments = _load_day_assignments(session, version_id, day)

    # Load ALL assignments (for upstream dependency checking)
    all_asn_rows = session.exec(
        select(MatchAssignment, Match, ScheduleSlot)
        .join(Match, MatchAssignment.match_id == Match.id)
        .join(ScheduleSlot, MatchAssignment.slot_id == ScheduleSlot.id)
        .where(MatchAssignment.schedule_version_id == version_id)
    ).all()
    all_assignments_by_match: Dict[int, Tuple[MatchAssignment, ScheduleSlot]] = {
        m.id: (a, s) for a, m, s in all_asn_rows
    }

    # Load all matches for consolation completeness check
    all_matches = session.exec(
        select(Match).where(Match.schedule_version_id == version_id)
    ).all()

    violations: List[Violation] = []
    stats = InvariantStats()

    # A) Team daily cap
    cap_violations = _check_team_daily_cap(day_assignments, day)
    stats.teams_over_cap = len(cap_violations)
    violations.extend(cap_violations)

    # B) Fairness ordering
    fairness_violations = _check_fairness_ordering(day_assignments, day)
    stats.fairness_violations = len(fairness_violations)
    violations.extend(fairness_violations)

    # C) Unresolved dependencies
    dep_violations = _check_unresolved_dependencies(
        day_assignments, all_assignments_by_match, day
    )
    stats.unresolved_scheduled = len(dep_violations)
    violations.extend(dep_violations)

    # D) Consolation completeness
    cons_violations = _check_consolation_completeness(
        day_assignments, all_matches, all_assignments_by_match, day
    )
    stats.consolation_partial = len(cons_violations)
    violations.extend(cons_violations)

    # E) Spare court rules (conditional)
    spare_violations = _check_spare_court_rules(
        session, version_id, day, day_assignments,
        spare_policy_enabled=spare_policy_enabled,
    )
    stats.spare_violations = len(spare_violations)
    violations.extend(spare_violations)

    return InvariantReport(
        ok=len(violations) == 0,
        violations=violations,
        stats=stats,
    )


def verify_full_schedule(
    session: Session,
    tournament_id: int,
    version_id: int,
) -> InvariantReport:
    """
    Run all invariant checks across ALL days in the schedule.

    Auto-detects whether the tournament is capacity-tight. If so, the
    spare-court invariant becomes advisory (not a hard stop).
    """
    # Auto-detect capacity: if tight, don't hard-fail on spares
    spare_enabled = not _is_capacity_tight(session, version_id)

    # Get all days that have slots
    all_slots = session.exec(
        select(ScheduleSlot.day_date)
        .where(ScheduleSlot.schedule_version_id == version_id)
        .distinct()
    ).all()
    days = sorted(set(all_slots))

    combined_violations: List[Violation] = []
    combined_stats = InvariantStats()

    for day in days:
        report = verify_day(
            session, tournament_id, version_id, day,
            spare_policy_enabled=spare_enabled,
        )
        combined_violations.extend(report.violations)
        combined_stats.teams_over_cap += report.stats.teams_over_cap
        combined_stats.fairness_violations += report.stats.fairness_violations
        combined_stats.unresolved_scheduled += report.stats.unresolved_scheduled
        combined_stats.consolation_partial += report.stats.consolation_partial
        combined_stats.spare_violations += report.stats.spare_violations

    return InvariantReport(
        ok=len(combined_violations) == 0,
        violations=combined_violations,
        stats=combined_stats,
    )


# ─── Hashing ─────────────────────────────────────────────────────────────

def hash_policy_input(
    session: Session,
    tournament_id: int,
    version_id: int,
    policy_version: str = "sequence_v1",
) -> str:
    """
    Compute a canonical hash of the policy inputs:
    draw plan + slot layout + policy version.
    """
    # Slot digest: sorted list of (day, time, court, duration)
    slots = session.exec(
        select(ScheduleSlot).where(
            ScheduleSlot.schedule_version_id == version_id,
            ScheduleSlot.is_active == True,
        )
    ).all()
    slot_tuples = sorted(
        (str(s.day_date), str(s.start_time), s.court_number, s.block_minutes)
        for s in slots
    )

    # Match digest: sorted list of (match_id, event_id, match_type, round_index)
    matches = session.exec(
        select(Match).where(Match.schedule_version_id == version_id)
    ).all()
    match_tuples = sorted(
        (m.id, m.event_id, m.match_type, m.round_index or 0, m.sequence_in_round)
        for m in matches
    )

    # Event digest — includes draw_plan_json so a silent plan change
    # invalidates the hash and prevents stale replays.
    events = session.exec(
        select(Event).where(Event.tournament_id == tournament_id)
    ).all()
    event_tuples = sorted(
        (e.id, e.name, e.team_count or 0, e.category, e.draw_plan_json or "")
        for e in events
    )

    # Lock digest — changes to locks must invalidate the hash
    from app.models.match_lock import MatchLock
    from app.models.slot_lock import SlotLock
    match_locks = session.exec(
        select(MatchLock).where(MatchLock.schedule_version_id == version_id)
    ).all()
    match_lock_tuples = sorted(
        (ml.match_id, ml.slot_id) for ml in match_locks
    )
    slot_locks = session.exec(
        select(SlotLock).where(SlotLock.schedule_version_id == version_id)
    ).all()
    slot_lock_tuples = sorted(
        (sl.slot_id, sl.status) for sl in slot_locks
    )

    payload = json.dumps({
        "policy_version": policy_version,
        "slots": slot_tuples,
        "matches": match_tuples,
        "events": event_tuples,
        "match_locks": match_lock_tuples,
        "slot_locks": slot_lock_tuples,
    }, sort_keys=True, default=str)

    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def hash_policy_output(
    session: Session,
    version_id: int,
) -> str:
    """
    Compute a canonical hash of the policy output (assignments).
    Sorted by (day, start_time, court, match_id) for stability.
    """
    rows = session.exec(
        select(MatchAssignment, ScheduleSlot)
        .join(ScheduleSlot, MatchAssignment.slot_id == ScheduleSlot.id)
        .where(MatchAssignment.schedule_version_id == version_id)
    ).all()

    assignment_tuples = sorted(
        (str(s.day_date), str(s.start_time), s.court_number, a.match_id)
        for a, s in rows
    )

    payload = json.dumps(assignment_tuples, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]
