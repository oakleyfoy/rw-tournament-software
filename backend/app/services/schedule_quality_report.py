"""
Schedule Quality Report — validates a completed schedule against Kiawah-standard rules.

Checks:
1. Completeness: All matches assigned (0 unassigned)
2. Sequencing: No match scheduled before its prerequisites
3. Rest compliance: No team plays twice within required rest gap
4. Daily cap: No team exceeds 2 matches on any day
5. Staggering: Categories spread across time slots
6. Spare courts: At least 1 spare per time bucket (except first)
7. Summary stats: Matches per day, per event, utilization %
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, time
from typing import Any, Dict, List, Optional, Set, Tuple

from sqlmodel import Session, select

from app.models.event import Event
from app.models.match import Match
from app.models.match_assignment import MatchAssignment
from app.models.schedule_slot import ScheduleSlot
from app.models.schedule_version import ScheduleVersion
from app.models.team import Team

logger = logging.getLogger(__name__)

# Rest rules (mirrored from rest_rules.py)
REST_MINUTES_WF_TO_SCORING = 60
REST_MINUTES_SCORING_TO_SCORING = 90


@dataclass
class CheckResult:
    """Result of a single quality check."""

    name: str
    passed: bool
    summary: str
    details: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "passed": self.passed,
            "summary": self.summary,
            "details": self.details[:20],  # Cap at 20 to avoid huge payloads
            "detail_count": len(self.details),
        }


@dataclass
class RestGapIssue:
    """One short-rest finding (per-team or structural slot transition)."""

    kind: str  # "team" | "structural"
    summary: str
    team_id: Optional[int] = None
    team_name: Optional[str] = None
    event_id: Optional[int] = None
    event_name: Optional[str] = None
    day: Optional[str] = None
    prev_match_code: Optional[str] = None
    prev_stage: Optional[str] = None
    prev_end_time: Optional[str] = None
    curr_match_code: Optional[str] = None
    curr_stage: Optional[str] = None
    curr_start_time: Optional[str] = None
    actual_minutes: Optional[int] = None
    required_minutes: Optional[int] = None
    match_duration_minutes: Optional[int] = None
    stage_transition: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind,
            "summary": self.summary,
            "team_id": self.team_id,
            "team_name": self.team_name,
            "event_id": self.event_id,
            "event_name": self.event_name,
            "day": self.day,
            "prev_match_code": self.prev_match_code,
            "prev_stage": self.prev_stage,
            "prev_end_time": self.prev_end_time,
            "curr_match_code": self.curr_match_code,
            "curr_stage": self.curr_stage,
            "curr_start_time": self.curr_start_time,
            "actual_minutes": self.actual_minutes,
            "required_minutes": self.required_minutes,
            "match_duration_minutes": self.match_duration_minutes,
            "stage_transition": self.stage_transition,
        }


@dataclass
class RestGapReport:
    """Full rest-gap audit for a placed schedule."""

    issue_count: int
    issues: List[RestGapIssue] = field(default_factory=list)

    @property
    def has_issues(self) -> bool:
        return self.issue_count > 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "issue_count": self.issue_count,
            "issues": [i.to_dict() for i in self.issues],
        }


@dataclass
class QualityReport:
    """Full schedule quality report."""

    version_id: int
    overall_passed: bool
    checks: List[CheckResult]
    stats: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version_id": self.version_id,
            "overall_passed": self.overall_passed,
            "checks": [c.to_dict() for c in self.checks],
            "stats": self.stats,
        }


def generate_quality_report(
    session: Session,
    tournament_id: int,
    version_id: int,
) -> QualityReport:
    """Generate a comprehensive quality report for a schedule version."""

    # Load all data
    version = session.get(ScheduleVersion, version_id)
    if not version or version.tournament_id != tournament_id:
        return QualityReport(
            version_id=version_id,
            overall_passed=False,
            checks=[CheckResult("version_valid", False, "Schedule version not found")],
            stats={},
        )

    all_matches = session.exec(select(Match).where(Match.schedule_version_id == version_id)).all()
    all_assignments = session.exec(
        select(MatchAssignment).where(MatchAssignment.schedule_version_id == version_id)
    ).all()
    all_slots = session.exec(select(ScheduleSlot).where(ScheduleSlot.schedule_version_id == version_id)).all()
    events = session.exec(select(Event).where(Event.tournament_id == tournament_id)).all()

    # Build lookup maps
    slot_by_id = {s.id: s for s in all_slots}
    match_by_id = {m.id: m for m in all_matches}
    event_by_id = {e.id: e for e in events}
    assigned_match_ids = {a.match_id for a in all_assignments}
    assigned_slot_ids = {a.slot_id for a in all_assignments}
    slot_by_match = {}
    for a in all_assignments:
        if a.slot_id in slot_by_id:
            slot_by_match[a.match_id] = slot_by_id[a.slot_id]

    # Run checks
    checks = []
    checks.append(_check_completeness(all_matches, assigned_match_ids, event_by_id))
    checks.append(_check_sequencing(all_matches, slot_by_match, match_by_id))
    rest_report = audit_rest_gaps(session, tournament_id, version_id)
    checks.append(_rest_report_to_check(rest_report))
    checks.append(_check_daily_cap(session, all_matches, slot_by_match))
    checks.append(_check_staggering(all_matches, slot_by_match, event_by_id))
    checks.append(_check_spare_courts(all_slots, assigned_slot_ids))

    # Compute stats
    stats = _compute_stats(all_matches, all_slots, all_assignments, slot_by_match, event_by_id)
    stats["rest_gap_report"] = rest_report.to_dict()

    overall = all(c.passed for c in checks)

    return QualityReport(
        version_id=version_id,
        overall_passed=overall,
        checks=checks,
        stats=stats,
    )


def audit_rest_gaps(
    session: Session,
    tournament_id: int,
    version_id: int,
    *,
    include_structural: bool = False,
) -> RestGapReport:
    """Audit team short rests (and optionally structural same-day stage transitions)."""
    all_matches = session.exec(select(Match).where(Match.schedule_version_id == version_id)).all()
    all_assignments = session.exec(
        select(MatchAssignment).where(MatchAssignment.schedule_version_id == version_id)
    ).all()
    all_slots = session.exec(select(ScheduleSlot).where(ScheduleSlot.schedule_version_id == version_id)).all()
    events = session.exec(select(Event).where(Event.tournament_id == tournament_id)).all()
    event_ids = [e.id for e in events if e.id is not None]
    teams = (
        session.exec(select(Team).where(Team.event_id.in_(event_ids))).all()  # type: ignore[attr-defined]
        if event_ids
        else []
    )

    slot_by_id = {s.id: s for s in all_slots}
    match_by_id = {m.id: m for m in all_matches if m.id is not None}
    event_by_id = {e.id: e for e in events if e.id is not None}
    team_by_id = {t.id: t for t in teams if t.id is not None}
    slot_by_match: Dict[int, ScheduleSlot] = {}
    for a in all_assignments:
        if a.slot_id in slot_by_id and a.match_id is not None:
            slot_by_match[a.match_id] = slot_by_id[a.slot_id]

    issues: List[RestGapIssue] = []
    issues.extend(
        _collect_team_rest_issues(
            all_matches,
            slot_by_match,
            match_by_id,
            event_by_id,
            team_by_id,
        )
    )
    if include_structural:
        issues.extend(
            _collect_structural_rest_issues(
                all_matches,
                slot_by_match,
                event_by_id,
            )
        )
    return RestGapReport(issue_count=len(issues), issues=issues)


def _rest_report_to_check(report: RestGapReport) -> CheckResult:
    if not report.has_issues:
        return CheckResult(
            "rest_compliance",
            True,
            "All rest gaps satisfied",
        )
    details = [i.summary for i in report.issues]
    return CheckResult(
        "rest_compliance",
        False,
        f"{report.issue_count} rest violations",
        details,
    )


def _format_clock(slot: ScheduleSlot) -> str:
    if not slot.start_time:
        return "?"
    return slot.start_time.strftime("%H:%M")


def _format_end_clock(slot: ScheduleSlot) -> str:
    if not slot.start_time:
        return "?"
    end_min = slot.start_time.hour * 60 + slot.start_time.minute + (slot.block_minutes or 0)
    return f"{end_min // 60:02d}:{end_min % 60:02d}"


def _stage_label(match: Match) -> str:
    mtype = (match.match_type or "?").upper()
    ri = match.round_index or match.round_number or 0
    if mtype == "WF":
        return f"WF R{ri or 1}"
    if mtype == "RR":
        return f"RR R{ri or 1}"
    return f"{mtype} R{ri}" if ri else mtype


def _required_rest_minutes(prev_match: Match) -> int:
    if (prev_match.match_type or "").upper() == "WF":
        return REST_MINUTES_WF_TO_SCORING
    return REST_MINUTES_SCORING_TO_SCORING


def _team_display_name(team: Optional[Team], team_id: int) -> str:
    if team is None:
        return f"Team {team_id}"
    return (team.display_name or team.name or f"Team {team_id}").strip()


def _collect_team_rest_issues(
    all_matches: List[Match],
    slot_by_match: Dict[int, ScheduleSlot],
    match_by_id: Dict[int, Match],
    event_by_id: Dict[int, Event],
    team_by_id: Dict[int, Team],
) -> List[RestGapIssue]:
    team_schedule: Dict[int, List[Tuple[Match, ScheduleSlot]]] = defaultdict(list)
    for match in all_matches:
        if match.id not in slot_by_match:
            continue
        slot = slot_by_match[match.id]
        for team_id in [match.team_a_id, match.team_b_id]:
            if team_id:
                team_schedule[team_id].append((match, slot))

    issues: List[RestGapIssue] = []
    for team_id, schedule in team_schedule.items():
        schedule.sort(key=lambda x: _slot_abs_minutes(x[1]))
        team = team_by_id.get(team_id)
        team_name = _team_display_name(team, team_id)
        for i in range(1, len(schedule)):
            prev_match, prev_slot = schedule[i - 1]
            curr_match, curr_slot = schedule[i]
            prev_end = _slot_abs_minutes(prev_slot) + (prev_slot.block_minutes or 0)
            curr_start = _slot_abs_minutes(curr_slot)
            gap = curr_start - prev_end
            required = _required_rest_minutes(prev_match)
            if gap >= required:
                continue
            event = event_by_id.get(curr_match.event_id) or event_by_id.get(prev_match.event_id)
            event_name = event.name if event else f"Event {curr_match.event_id}"
            day = str(curr_slot.day_date) if curr_slot.day_date else str(prev_slot.day_date)
            prev_stage = _stage_label(prev_match)
            curr_stage = _stage_label(curr_match)
            summary = (
                f"{team_name} ({event_name}): {gap}min rest between {prev_stage} "
                f"({prev_match.match_code}) ending {_format_end_clock(prev_slot)} and "
                f"{curr_stage} ({curr_match.match_code}) at {_format_clock(curr_slot)} "
                f"(required {required}min)"
            )
            issues.append(
                RestGapIssue(
                    kind="team",
                    summary=summary,
                    team_id=team_id,
                    team_name=team_name,
                    event_id=event.id if event else curr_match.event_id,
                    event_name=event_name,
                    day=day,
                    prev_match_code=prev_match.match_code,
                    prev_stage=prev_stage,
                    prev_end_time=_format_end_clock(prev_slot),
                    curr_match_code=curr_match.match_code,
                    curr_stage=curr_stage,
                    curr_start_time=_format_clock(curr_slot),
                    actual_minutes=gap,
                    required_minutes=required,
                    match_duration_minutes=prev_slot.block_minutes or prev_match.duration_minutes,
                    stage_transition=f"{prev_stage} → {curr_stage}",
                )
            )
    return issues


def _collect_structural_rest_issues(
    all_matches: List[Match],
    slot_by_match: Dict[int, ScheduleSlot],
    event_by_id: Dict[int, Event],
) -> List[RestGapIssue]:
    """One issue per event when consecutive WF/RR rounds share a day with a short gap."""
    # event_id -> stage_family -> round_index -> list of (match, slot)
    by_event_round: Dict[Tuple[int, str, int], List[Tuple[Match, ScheduleSlot]]] = defaultdict(list)
    for match in all_matches:
        if match.id not in slot_by_match:
            continue
        mtype = (match.match_type or "").upper()
        if mtype not in ("WF", "RR"):
            continue
        ri = match.round_index or match.round_number or 0
        if ri < 1:
            continue
        by_event_round[(match.event_id, mtype, ri)].append((match, slot_by_match[match.id]))

    issues: List[RestGapIssue] = []
    seen: Set[Tuple[int, str, int, str]] = set()

    # Group keys by event + family
    families: Dict[Tuple[int, str], List[int]] = defaultdict(list)
    for event_id, mtype, ri in by_event_round:
        families[(event_id, mtype)].append(ri)

    for (event_id, mtype), rounds in families.items():
        for ri in sorted(set(rounds)):
            next_ri = ri + 1
            if next_ri not in set(rounds):
                continue
            earlier = by_event_round[(event_id, mtype, ri)]
            later = by_event_round[(event_id, mtype, next_ri)]
            if not earlier or not later:
                continue

            # Representative: earliest start of earlier round, earliest start of later round
            earlier_slot = min(earlier, key=lambda x: _slot_abs_minutes(x[1]))[1]
            later_slot = min(later, key=lambda x: _slot_abs_minutes(x[1]))[1]
            if earlier_slot.day_date != later_slot.day_date:
                continue

            prev_end = _slot_abs_minutes(earlier_slot) + (earlier_slot.block_minutes or 0)
            curr_start = _slot_abs_minutes(later_slot)
            gap = curr_start - prev_end
            sample_match = earlier[0][0]
            required = _required_rest_minutes(sample_match)
            if gap >= required:
                continue

            day = str(earlier_slot.day_date)
            key = (event_id, mtype, ri, day)
            if key in seen:
                continue
            seen.add(key)

            event = event_by_id.get(event_id)
            event_name = event.name if event else f"Event {event_id}"
            prev_stage = f"{mtype} R{ri}"
            curr_stage = f"{mtype} R{next_ri}"
            duration = earlier_slot.block_minutes or sample_match.duration_minutes or 0
            summary = (
                f"{event_name} {prev_stage} at {_format_clock(earlier_slot)} → "
                f"{curr_stage} at {_format_clock(later_slot)} leaves {gap}min rest "
                f"after {duration}min matches (required {required}min)"
            )
            issues.append(
                RestGapIssue(
                    kind="structural",
                    summary=summary,
                    event_id=event_id,
                    event_name=event_name,
                    day=day,
                    prev_stage=prev_stage,
                    prev_end_time=_format_end_clock(earlier_slot),
                    curr_stage=curr_stage,
                    curr_start_time=_format_clock(later_slot),
                    actual_minutes=gap,
                    required_minutes=required,
                    match_duration_minutes=duration,
                    stage_transition=f"{prev_stage} → {curr_stage}",
                )
            )
    return issues


# ============================================================================
# Individual Checks
# ============================================================================


def _check_completeness(
    all_matches: List[Match],
    assigned_match_ids: Set[int],
    event_by_id: Dict[int, Event],
) -> CheckResult:
    """Check that all matches have been assigned to slots."""
    unassigned = [m for m in all_matches if m.id not in assigned_match_ids]
    total = len(all_matches)
    assigned = len(assigned_match_ids)

    if not unassigned:
        return CheckResult(
            "completeness",
            True,
            f"All {total} matches assigned",
        )

    details = []
    by_event_type = defaultdict(list)
    for m in unassigned:
        event = event_by_id.get(m.event_id)
        event_name = event.name if event else f"Event {m.event_id}"
        by_event_type[(event_name, m.match_type)].append(m)

    for (event_name, match_type), matches in sorted(by_event_type.items()):
        details.append(f"{event_name} / {match_type}: {len(matches)} unassigned")

    return CheckResult(
        "completeness",
        False,
        f"{len(unassigned)} of {total} matches unassigned ({assigned}/{total} assigned)",
        details,
    )


def _check_sequencing(
    all_matches: List[Match],
    slot_by_match: Dict[int, ScheduleSlot],
    match_by_id: Dict[int, Match],
) -> CheckResult:
    """Check that no match is scheduled before its prerequisite matches."""
    violations = []

    for match in all_matches:
        if match.id not in slot_by_match:
            continue

        match_slot = slot_by_match[match.id]
        match_abs = _slot_abs_minutes(match_slot)

        for source_id in [match.source_match_a_id, match.source_match_b_id]:
            if source_id and source_id in slot_by_match:
                prereq_slot = slot_by_match[source_id]
                prereq_end = _slot_abs_minutes(prereq_slot) + prereq_slot.block_minutes
                if match_abs < prereq_end:
                    prereq = match_by_id.get(source_id)
                    violations.append(
                        f"{match.match_code} at {match_slot.day_date} {match_slot.start_time} "
                        f"before prereq {prereq.match_code if prereq else source_id} "
                        f"(ends {prereq_slot.day_date} {prereq_slot.start_time}+{prereq_slot.block_minutes}m)"
                    )

    if not violations:
        return CheckResult("sequencing", True, "All match dependencies satisfied")

    return CheckResult(
        "sequencing",
        False,
        f"{len(violations)} sequencing violations",
        violations,
    )


def _check_rest_compliance(
    session: Session,
    all_matches: List[Match],
    slot_by_match: Dict[int, ScheduleSlot],
    match_by_id: Dict[int, Match],
) -> CheckResult:
    """Legacy wrapper — prefer audit_rest_gaps for structured issues."""
    # Infer tournament from matches
    if not all_matches:
        return CheckResult("rest_compliance", True, "All rest gaps satisfied (0 matches checked)")
    # Cannot call audit without tournament_id/version — keep simple team check for callers
    # that still pass the old signature. generate_quality_report uses audit_rest_gaps.
    violations = []
    team_schedule: Dict[int, List[Tuple[Match, ScheduleSlot]]] = defaultdict(list)
    for match in all_matches:
        if match.id not in slot_by_match:
            continue
        slot = slot_by_match[match.id]
        for team_id in [match.team_a_id, match.team_b_id]:
            if team_id:
                team_schedule[team_id].append((match, slot))

    for team_id, schedule in team_schedule.items():
        schedule.sort(key=lambda x: _slot_abs_minutes(x[1]))
        for i in range(1, len(schedule)):
            prev_match, prev_slot = schedule[i - 1]
            curr_match, curr_slot = schedule[i]
            prev_end = _slot_abs_minutes(prev_slot) + prev_slot.block_minutes
            curr_start = _slot_abs_minutes(curr_slot)
            gap = curr_start - prev_end
            required = _required_rest_minutes(prev_match)
            if gap < required:
                violations.append(
                    f"Team {team_id}: {gap}min gap between "
                    f"{prev_match.match_code} and {curr_match.match_code} "
                    f"(required {required}min)"
                )

    if not violations:
        assigned_count = len([m for m in all_matches if m.id in slot_by_match])
        return CheckResult("rest_compliance", True, f"All rest gaps satisfied ({assigned_count} matches checked)")

    return CheckResult(
        "rest_compliance",
        False,
        f"{len(violations)} rest violations",
        violations,
    )


def _check_daily_cap(
    session: Session,
    all_matches: List[Match],
    slot_by_match: Dict[int, ScheduleSlot],
) -> CheckResult:
    """Check that no team exceeds 2 matches on any day."""
    violations = []

    # Build team -> day -> count
    team_day_counts: Dict[int, Dict[date, int]] = defaultdict(lambda: defaultdict(int))
    for match in all_matches:
        if match.id not in slot_by_match:
            continue
        slot = slot_by_match[match.id]
        for team_id in [match.team_a_id, match.team_b_id]:
            if team_id:
                team_day_counts[team_id][slot.day_date] += 1

    for team_id, day_counts in team_day_counts.items():
        for day_date, count in day_counts.items():
            if count > 2:
                violations.append(f"Team {team_id}: {count} matches on {day_date} (max 2)")

    if not violations:
        return CheckResult("daily_cap", True, "No team exceeds 2 matches/day")

    return CheckResult(
        "daily_cap",
        False,
        f"{len(violations)} daily cap violations",
        violations,
    )


def _check_staggering(
    all_matches: List[Match],
    slot_by_match: Dict[int, ScheduleSlot],
    event_by_id: Dict[int, Event],
) -> CheckResult:
    """
    Check that categories are staggered across time slots.
    Passed if each day has matches from multiple events.
    """
    # Group assigned matches by day and event
    day_events: Dict[date, Set[int]] = defaultdict(set)
    for match in all_matches:
        if match.id not in slot_by_match:
            continue
        slot = slot_by_match[match.id]
        day_events[slot.day_date].add(match.event_id)

    total_events = len(event_by_id)
    details = []
    issues = 0

    for day_date in sorted(day_events.keys()):
        event_ids = day_events[day_date]
        event_names = [event_by_id[eid].name for eid in event_ids if eid in event_by_id]
        if len(event_ids) < min(total_events, 2):
            issues += 1
            details.append(f"{day_date}: only {len(event_ids)} event(s) - {', '.join(event_names)}")
        else:
            details.append(f"{day_date}: {len(event_ids)} events staggered - {', '.join(sorted(event_names))}")

    if issues == 0:
        return CheckResult("staggering", True, "Events well-staggered across all days", details)

    return CheckResult(
        "staggering",
        False,
        f"{issues} day(s) with insufficient event staggering",
        details,
    )


def _check_spare_courts(
    all_slots: List[ScheduleSlot],
    assigned_slot_ids: Set[int],
) -> CheckResult:
    """Check spare court availability per time bucket."""
    # Group slots by (day, start_time) = "time bucket"
    buckets: Dict[Tuple[date, time], List[ScheduleSlot]] = defaultdict(list)
    for s in all_slots:
        buckets[(s.day_date, s.start_time)].append(s)

    violations = []
    spare_counts = []

    for (day_date, start_time), slots in sorted(buckets.items()):
        total = len(slots)
        assigned = sum(1 for s in slots if s.id in assigned_slot_ids)
        spare = total - assigned
        spare_counts.append(spare)

        if spare < 1:
            violations.append(f"{day_date} {start_time}: {spare} spare courts ({assigned}/{total} used)")

    avg_spare = sum(spare_counts) / len(spare_counts) if spare_counts else 0

    if not violations:
        return CheckResult(
            "spare_courts",
            True,
            f"All time buckets have spare courts (avg {avg_spare:.1f} spare)",
        )

    return CheckResult(
        "spare_courts",
        False,
        f"{len(violations)} time bucket(s) with 0 spare courts",
        violations,
    )


# ============================================================================
# Stats
# ============================================================================


def _compute_stats(
    all_matches: List[Match],
    all_slots: List[ScheduleSlot],
    all_assignments: List[MatchAssignment],
    slot_by_match: Dict[int, ScheduleSlot],
    event_by_id: Dict[int, Event],
) -> Dict[str, Any]:
    """Compute summary statistics."""
    total_matches = len(all_matches)
    total_slots = len(all_slots)
    assigned = len(all_assignments)
    unassigned = total_matches - assigned

    # By day
    matches_per_day: Dict[str, int] = defaultdict(int)
    for m in all_matches:
        if m.id in slot_by_match:
            matches_per_day[str(slot_by_match[m.id].day_date)] += 1

    # By event
    matches_per_event: Dict[str, Dict[str, int]] = {}
    for m in all_matches:
        event = event_by_id.get(m.event_id)
        event_name = event.name if event else f"Event {m.event_id}"
        if event_name not in matches_per_event:
            matches_per_event[event_name] = {"total": 0, "assigned": 0}
        matches_per_event[event_name]["total"] += 1
        if m.id in slot_by_match:
            matches_per_event[event_name]["assigned"] += 1

    # Utilization
    utilization = (assigned / total_slots * 100) if total_slots > 0 else 0

    return {
        "total_matches": total_matches,
        "total_slots": total_slots,
        "assigned": assigned,
        "unassigned": unassigned,
        "utilization_pct": round(utilization, 1),
        "matches_per_day": dict(matches_per_day),
        "matches_per_event": matches_per_event,
    }


# ============================================================================
# Helpers
# ============================================================================


def _slot_abs_minutes(slot: ScheduleSlot) -> int:
    """Convert slot to absolute minutes for comparison."""
    # Use a fixed reference point (epoch-like)
    day_offset = slot.day_date.toordinal()
    return day_offset * 1440 + slot.start_time.hour * 60 + slot.start_time.minute
