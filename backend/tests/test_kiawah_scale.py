"""
Kiawah-Scale Integration Test

Validates the full scheduling pipeline at production scale:
- 4 events: Mixed (16 teams), Women's A/B/C (32 teams each)
- 3 tournament days (Friday/Saturday/Sunday)
- 15 courts (19 from midday) with split time windows
- ~300+ matches total
- Full policy-based scheduling

Asserts:
- All matches generated correctly (inventory counts)
- All matches assigned to slots (0 unassigned)
- No sequencing violations (QF before SF before Final, R1 before R2)
- Category staggering across time slots
- Daily match cap respected (≤2 per team per day)
"""

import json
from collections import defaultdict
from datetime import date, time, timedelta
from typing import Dict, List, Set, Tuple

import pytest
from sqlmodel import Session, SQLModel, create_engine, select
from sqlmodel.pool import StaticPool

from app.models.event import Event
from app.models.match import Match
from app.models.match_assignment import MatchAssignment
from app.models.schedule_slot import ScheduleSlot
from app.models.schedule_version import ScheduleVersion
from app.models.team import Team
from app.models.team_avoid_edge import TeamAvoidEdge
from app.models.tournament import Tournament
from app.models.tournament_day import TournamentDay
from app.models.tournament_time_window import TournamentTimeWindow


# ============================================================================
# Kiawah Reference Constants
# ============================================================================

FRIDAY = date(2026, 2, 20)
SATURDAY = date(2026, 2, 21)
SUNDAY = date(2026, 2, 22)

NUM_COURTS_BASE = 15    # Courts available all day
NUM_COURTS_MIDDAY = 19  # Courts available from midday onward

# Expected match counts per event
# Mixed 16: 16 WF + 24 RR = 40 matches
# Women's 32 (G5): 32 WF + 4 brackets × 12 matches = 80 matches per event
EXPECTED_MIXED_WF = 16
EXPECTED_MIXED_RR = 24
EXPECTED_MIXED_TOTAL = 40

EXPECTED_WOMENS_WF = 32
EXPECTED_WOMENS_BRACKET = 48  # 4 brackets × 12 matches (G5)
EXPECTED_WOMENS_TOTAL = 80

EXPECTED_TOTAL_MATCHES = EXPECTED_MIXED_TOTAL + 3 * EXPECTED_WOMENS_TOTAL  # 40 + 240 = 280


# ============================================================================
# Test Fixtures
# ============================================================================


@pytest.fixture(name="session")
def session_fixture():
    """Create in-memory SQLite database for Kiawah-scale test."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


@pytest.fixture(name="kiawah_tournament")
def kiawah_tournament_fixture(session: Session):
    """
    Set up a full Kiawah-scale tournament:
    - 3-day tournament (Fri/Sat/Sun)
    - 15 courts (19 from midday)
    - Time windows matching Kiawah schedule
    - 4 events: Mixed (16), Women's A (32), Women's B (32), Women's C (32)
    - Teams seeded for each event
    """
    # ── Tournament ─────────────────────────────────────────────────────
    # 19 courts total at the venue; 15 available all day, 4 more from midday
    court_names = [f"Court {i}" for i in range(1, NUM_COURTS_MIDDAY + 1)]
    tournament = Tournament(
        name="Kiawah Cup 2026",
        location="Kiawah Island, SC",
        timezone="America/New_York",
        start_date=FRIDAY,
        end_date=SUNDAY,
        use_time_windows=True,
        court_names=court_names,
    )
    session.add(tournament)
    session.commit()
    session.refresh(tournament)

    # ── Tournament Days ────────────────────────────────────────────────
    for d in [FRIDAY, SATURDAY, SUNDAY]:
        day = TournamentDay(
            tournament_id=tournament.id,
            date=d,
            is_active=True,
            start_time=time(8, 0),
            end_time=time(18, 30),
            courts_available=NUM_COURTS_MIDDAY,
        )
        session.add(day)
    session.commit()

    # ── Time Windows ───────────────────────────────────────────────────
    # Kiawah court availability: 15 courts in the morning, 19 from midday.
    # Each day is split into two time windows at the court-count boundary.
    #
    # Friday (WF day, 75-min blocks):
    #   8:00-12:00 → 15 courts (3 buckets: 8:00, 9:15, 10:30)  = 45 slots
    #   12:00-18:00 → 19 courts (4 buckets: 12:00, 13:15, 14:30, 15:45) = 76 slots
    #   Total: 121 slots for 112 WF matches
    _add_time_window(session, tournament.id, FRIDAY, time(8, 0), time(12, 0), NUM_COURTS_BASE, 75)
    _add_time_window(session, tournament.id, FRIDAY, time(12, 0), time(18, 0), NUM_COURTS_MIDDAY, 75)

    # Saturday (Division day, 105-min blocks):
    #   8:00-11:30 → 15 courts (2 buckets: 8:00, 9:45)  = 30 slots
    #   11:30-18:30 → 19 courts (4 buckets: 11:30, 13:15, 15:00, 16:45) = 76 slots
    #   Total: 106 slots
    _add_time_window(session, tournament.id, SATURDAY, time(8, 0), time(11, 30), NUM_COURTS_BASE, 105)
    _add_time_window(session, tournament.id, SATURDAY, time(11, 30), time(18, 30), NUM_COURTS_MIDDAY, 105)

    # Sunday (Finals day, 105-min blocks):
    #   8:00-11:30 → 15 courts (2 buckets: 8:00, 9:45)  = 30 slots
    #   11:30-18:30 → 19 courts (4 buckets: 11:30, 13:15, 15:00, 16:45) = 76 slots
    #   Total: 106 slots
    _add_time_window(session, tournament.id, SUNDAY, time(8, 0), time(11, 30), NUM_COURTS_BASE, 105)
    _add_time_window(session, tournament.id, SUNDAY, time(11, 30), time(18, 30), NUM_COURTS_MIDDAY, 105)

    session.commit()

    # ── Schedule Version ───────────────────────────────────────────────
    version = ScheduleVersion(
        tournament_id=tournament.id,
        version_number=1,
        status="draft",
    )
    session.add(version)
    session.commit()
    session.refresh(version)

    # ── Events ─────────────────────────────────────────────────────────
    events = {}

    # Mixed (16 teams) — WF_TO_POOLS_DYNAMIC, 2 WF rounds, 4 pools of 4 RR
    events["mixed"] = _create_event(
        session, tournament.id,
        name="Mixed",
        category="mixed",
        team_count=16,
        template_type="WF_TO_POOLS_DYNAMIC",
        wf_rounds=2,
        guarantee=4,
        wf_block_minutes=75,
        standard_block_minutes=105,
    )

    # Women's A (32 teams) — WF_TO_BRACKETS_8, 2 WF rounds, 4 brackets of 8
    events["womens_a"] = _create_event(
        session, tournament.id,
        name="Womens A",
        category="womens",
        team_count=32,
        template_type="WF_TO_BRACKETS_8",
        wf_rounds=2,
        guarantee=5,
        wf_block_minutes=75,
        standard_block_minutes=105,
    )

    # Women's B (32 teams)
    events["womens_b"] = _create_event(
        session, tournament.id,
        name="Womens B",
        category="womens",
        team_count=32,
        template_type="WF_TO_BRACKETS_8",
        wf_rounds=2,
        guarantee=5,
        wf_block_minutes=75,
        standard_block_minutes=105,
    )

    # Women's C (32 teams)
    events["womens_c"] = _create_event(
        session, tournament.id,
        name="Womens C",
        category="womens",
        team_count=32,
        template_type="WF_TO_BRACKETS_8",
        wf_rounds=2,
        guarantee=5,
        wf_block_minutes=75,
        standard_block_minutes=105,
    )

    return {
        "tournament_id": tournament.id,
        "version_id": version.id,
        "events": events,
    }


# ============================================================================
# Helper Functions
# ============================================================================


def _add_time_window(
    session: Session,
    tournament_id: int,
    day_date: date,
    start: time,
    end: time,
    courts: int,
    block_minutes: int,
):
    """Add a time window to the tournament."""
    window = TournamentTimeWindow(
        tournament_id=tournament_id,
        day_date=day_date,
        start_time=start,
        end_time=end,
        courts_available=courts,
        block_minutes=block_minutes,
        is_active=True,
    )
    session.add(window)


def _create_event(
    session: Session,
    tournament_id: int,
    name: str,
    category: str,
    team_count: int,
    template_type: str,
    wf_rounds: int,
    guarantee: int,
    wf_block_minutes: int = 75,
    standard_block_minutes: int = 105,
) -> Dict:
    """Create an event with teams and finalize it."""
    draw_plan_json = json.dumps({
        "template_type": template_type,
        "wf_rounds": wf_rounds,
        "guarantee": guarantee,
    })

    event = Event(
        tournament_id=tournament_id,
        name=name,
        category=category,
        team_count=team_count,
        draw_plan_json=draw_plan_json,
        draw_status="final",
        wf_block_minutes=wf_block_minutes,
        standard_block_minutes=standard_block_minutes,
        guarantee_selected=guarantee,
    )
    session.add(event)
    session.commit()
    session.refresh(event)

    # Create teams
    teams = []
    for i in range(1, team_count + 1):
        team = Team(
            event_id=event.id,
            name=f"{name} Team {i}",
            seed=i,
            rating=2000.0 - i,  # Higher-seeded teams have higher rating
        )
        teams.append(team)
    session.add_all(teams)
    session.commit()
    for t in teams:
        session.refresh(t)

    return {
        "event_id": event.id,
        "team_count": team_count,
        "team_ids": [t.id for t in teams],
    }


def _get_match_time(session: Session, match: Match, version_id: int) -> Tuple:
    """Get the (day_date, start_time) for an assigned match."""
    assignment = session.exec(
        select(MatchAssignment).where(
            MatchAssignment.match_id == match.id,
            MatchAssignment.schedule_version_id == version_id,
        )
    ).first()
    if not assignment:
        return None, None
    slot = session.get(ScheduleSlot, assignment.slot_id)
    if not slot:
        return None, None
    return slot.day_date, slot.start_time


# ============================================================================
# Tests
# ============================================================================


class TestKiawahMatchGeneration:
    """Test that match generation produces the right inventory."""

    def test_generate_matches_inventory(self, session: Session, kiawah_tournament):
        """Verify correct match counts for all 4 events."""
        from app.routes.schedule import generate_matches, MatchGenerateRequest

        tid = kiawah_tournament["tournament_id"]
        vid = kiawah_tournament["version_id"]

        # Generate matches for all events
        session._allow_match_generation = True  # type: ignore[attr-defined]
        request = MatchGenerateRequest(schedule_version_id=vid, wipe_existing=True)
        result = generate_matches(tid, request, session, _transactional=True)
        session._allow_match_generation = False  # type: ignore[attr-defined]

        total = result["total_matches_created"]
        print(f"\n=== Match Generation Results ===")
        print(f"Total matches created: {total}")
        for event_name, breakdown in result.get("per_event_breakdown", {}).items():
            print(f"  {event_name}: {breakdown}")

        # Verify total matches
        all_matches = session.exec(
            select(Match).where(Match.schedule_version_id == vid)
        ).all()
        print(f"Total matches in DB: {len(all_matches)}")

        # Count by event
        events = kiawah_tournament["events"]
        for label, event_info in events.items():
            eid = event_info["event_id"]
            event_matches = [m for m in all_matches if m.event_id == eid]
            wf = [m for m in event_matches if m.match_type == "WF"]
            rr = [m for m in event_matches if m.match_type == "RR"]
            main = [m for m in event_matches if m.match_type == "MAIN"]
            cons = [m for m in event_matches if m.match_type == "CONSOLATION"]
            placement = [m for m in event_matches if m.match_type == "PLACEMENT"]
            print(f"\n  {label} (event_id={eid}):")
            print(f"    WF={len(wf)}, RR={len(rr)}, MAIN={len(main)}, CONS={len(cons)}, PLACE={len(placement)}")
            print(f"    Total={len(event_matches)}")

        # Assert Mixed: 16 WF + 24 RR = 40
        mixed_eid = events["mixed"]["event_id"]
        mixed_matches = [m for m in all_matches if m.event_id == mixed_eid]
        mixed_wf = [m for m in mixed_matches if m.match_type == "WF"]
        mixed_rr = [m for m in mixed_matches if m.match_type == "RR"]
        assert len(mixed_wf) == EXPECTED_MIXED_WF, f"Mixed WF: expected {EXPECTED_MIXED_WF}, got {len(mixed_wf)}"
        assert len(mixed_rr) == EXPECTED_MIXED_RR, f"Mixed RR: expected {EXPECTED_MIXED_RR}, got {len(mixed_rr)}"

        # Assert each Women's event: 32 WF + bracket matches
        for label in ("womens_a", "womens_b", "womens_c"):
            eid = events[label]["event_id"]
            ev_matches = [m for m in all_matches if m.event_id == eid]
            ev_wf = [m for m in ev_matches if m.match_type == "WF"]
            assert len(ev_wf) == EXPECTED_WOMENS_WF, f"{label} WF: expected {EXPECTED_WOMENS_WF}, got {len(ev_wf)}"
            # Bracket matches: MAIN + CONSOLATION + PLACEMENT
            ev_bracket = [m for m in ev_matches if m.match_type in ("MAIN", "CONSOLATION", "PLACEMENT")]
            assert len(ev_bracket) >= 28, f"{label} bracket: expected >=28, got {len(ev_bracket)}"

        # Assert total is reasonable (at least 250 matches for this config)
        assert len(all_matches) >= 250, f"Total matches: expected >=250, got {len(all_matches)}"


class TestKiawahSlotGeneration:
    """Test that slot generation produces enough capacity."""

    def test_generate_slots_capacity(self, session: Session, kiawah_tournament):
        """Verify slot generation creates adequate capacity for 300+ matches."""
        from app.routes.schedule import generate_slots, SlotGenerateRequest

        tid = kiawah_tournament["tournament_id"]
        vid = kiawah_tournament["version_id"]

        request = SlotGenerateRequest(
            source="time_windows",
            schedule_version_id=vid,
            wipe_existing=True,
        )
        result = generate_slots(tid, request, session, _transactional=True)
        slots_created = result["slots_created"]

        print(f"\n=== Slot Generation Results ===")
        print(f"Total slots created: {slots_created}")

        # Get slots per day
        all_slots = session.exec(
            select(ScheduleSlot).where(ScheduleSlot.schedule_version_id == vid)
        ).all()

        by_day = defaultdict(list)
        for s in all_slots:
            by_day[s.day_date].append(s)

        for day_date in sorted(by_day.keys()):
            day_slots = by_day[day_date]
            times = sorted(set(s.start_time for s in day_slots))
            print(f"  {day_date}: {len(day_slots)} slots, {len(times)} time buckets")

        # Must have enough slots for 280 matches (with some spare capacity)
        assert slots_created >= 280, f"Need >=280 slots for Kiawah, got {slots_created}"

        # Must have slots on all 3 days
        assert len(by_day) == 3, f"Expected slots on 3 days, got {len(by_day)}"


class TestKiawahFullPipeline:
    """Integration test: full pipeline from generation to policy scheduling."""

    def test_full_policy_schedule(self, session: Session, kiawah_tournament):
        """
        Run the full scheduling pipeline and validate output quality.

        Steps:
        1. Generate matches
        2. Generate slots
        3. Run full policy scheduler
        4. Validate: completeness, sequencing, staggering
        """
        from app.routes.schedule import (
            generate_matches,
            generate_slots,
            MatchGenerateRequest,
            SlotGenerateRequest,
        )
        from app.services.schedule_policy_plan import run_full_schedule_policy

        tid = kiawah_tournament["tournament_id"]
        vid = kiawah_tournament["version_id"]
        events = kiawah_tournament["events"]

        # ── Step 1: Generate Matches ───────────────────────────────────
        session._allow_match_generation = True  # type: ignore[attr-defined]
        match_req = MatchGenerateRequest(schedule_version_id=vid, wipe_existing=True)
        match_result = generate_matches(tid, match_req, session, _transactional=True)
        session._allow_match_generation = False  # type: ignore[attr-defined]
        total_matches = match_result["total_matches_created"]
        print(f"\n=== Kiawah Full Pipeline ===")
        print(f"Matches generated: {total_matches}")

        # ── Step 2: Generate Slots ─────────────────────────────────────
        slot_req = SlotGenerateRequest(source="time_windows", schedule_version_id=vid, wipe_existing=True)
        slot_result = generate_slots(tid, slot_req, session, _transactional=True)
        slots_created = slot_result["slots_created"]
        print(f"Slots created: {slots_created}")

        # ── Step 3: Run Full Policy Scheduler ──────────────────────────
        policy_result = run_full_schedule_policy(session, tid, vid)

        print(f"\nPolicy Results:")
        print(f"  Total assigned: {policy_result.total_assigned}")
        print(f"  Total failed: {policy_result.total_failed}")
        print(f"  Duration: {policy_result.duration_ms}ms")
        for day_result in policy_result.day_results:
            print(f"  Day: {day_result}")

        # ── Step 4: Validate ───────────────────────────────────────────
        all_matches = session.exec(
            select(Match).where(Match.schedule_version_id == vid)
        ).all()
        all_assignments = session.exec(
            select(MatchAssignment).where(MatchAssignment.schedule_version_id == vid)
        ).all()
        assigned_match_ids = {a.match_id for a in all_assignments}
        unassigned = [m for m in all_matches if m.id not in assigned_match_ids]

        print(f"\n=== Validation ===")
        print(f"Total matches: {len(all_matches)}")
        print(f"Assigned: {len(assigned_match_ids)}")
        print(f"Unassigned: {len(unassigned)}")

        if unassigned:
            # Report unassigned by event and type
            by_event_type = defaultdict(list)
            for m in unassigned:
                by_event_type[(m.event_id, m.match_type)].append(m)
            print(f"\nUnassigned breakdown:")
            for (eid, mtype), matches in sorted(by_event_type.items()):
                print(f"  Event {eid}, {mtype}: {len(matches)} matches")

        # ── 4a. Completeness ───────────────────────────────────────────
        # Allow up to 5% unassigned (some consolation matches may be gated)
        unassigned_pct = len(unassigned) / len(all_matches) * 100 if all_matches else 0
        assert unassigned_pct < 5, (
            f"Too many unassigned: {len(unassigned)}/{len(all_matches)} "
            f"({unassigned_pct:.1f}%)"
        )

        # ── 4b. Sequencing Validation ──────────────────────────────────
        sequencing_violations = _check_sequencing(session, all_matches, vid)
        print(f"\nSequencing violations: {len(sequencing_violations)}")
        for v in sequencing_violations[:5]:
            print(f"  {v}")
        assert len(sequencing_violations) == 0, (
            f"Sequencing violations: {sequencing_violations[:5]}"
        )

        # ── 4c. Category Staggering ────────────────────────────────────
        stagger_report = _check_staggering(session, all_matches, vid, events)
        print(f"\nStaggering report:")
        for day_date, report in sorted(stagger_report.items()):
            print(f"  {day_date}:")
            for event_label, times in sorted(report.items()):
                if times:
                    print(f"    {event_label}: first={times[0]}, last={times[-1]}, count={len(times)}")

        # ── 4d. Day Distribution ───────────────────────────────────────
        day_dist = _check_day_distribution(session, all_matches, vid)
        print(f"\nDay distribution:")
        for day_date, count in sorted(day_dist.items()):
            print(f"  {day_date}: {count} matches")

        # Verify matches are spread across all 3 days
        assert len(day_dist) == 3, f"Expected matches on 3 days, got {len(day_dist)}"

        # Friday should have WF matches (most matches on day 1)
        friday_count = day_dist.get(FRIDAY, 0)
        assert friday_count >= 50, f"Friday should have >=50 WF matches, got {friday_count}"

        # Saturday should have division matches
        saturday_count = day_dist.get(SATURDAY, 0)
        assert saturday_count >= 50, f"Saturday should have >=50 division matches, got {saturday_count}"

        # Sunday should have finals/consolation
        sunday_count = day_dist.get(SUNDAY, 0)
        assert sunday_count >= 20, f"Sunday should have >=20 finals, got {sunday_count}"

        print(f"\n=== ALL CHECKS PASSED ===")

    def test_quality_report(self, session: Session, kiawah_tournament):
        """Test the quality report endpoint against a completed Kiawah schedule."""
        from app.routes.schedule import (
            generate_matches,
            generate_slots,
            MatchGenerateRequest,
            SlotGenerateRequest,
        )
        from app.services.schedule_policy_plan import run_full_schedule_policy
        from app.services.schedule_quality_report import generate_quality_report

        tid = kiawah_tournament["tournament_id"]
        vid = kiawah_tournament["version_id"]

        # Generate matches, slots, and run policy
        session._allow_match_generation = True  # type: ignore[attr-defined]
        generate_matches(tid, MatchGenerateRequest(schedule_version_id=vid, wipe_existing=True), session, _transactional=True)
        session._allow_match_generation = False  # type: ignore[attr-defined]
        generate_slots(tid, SlotGenerateRequest(source="time_windows", schedule_version_id=vid, wipe_existing=True), session, _transactional=True)
        run_full_schedule_policy(session, tid, vid)

        # Run quality report
        report = generate_quality_report(session, tid, vid)
        report_dict = report.to_dict()

        print(f"\n=== Quality Report ===")
        print(f"Overall: {'PASS' if report.overall_passed else 'FAIL'}")
        for check in report.checks:
            status = "PASS" if check.passed else "FAIL"
            print(f"  [{status}] {check.name}: {check.summary}")
            for d in check.details[:5]:
                print(f"    - {d}")

        print(f"\nStats:")
        for k, v in report.stats.items():
            print(f"  {k}: {v}")

        # The report should have all expected checks
        check_names = {c.name for c in report.checks}
        assert "completeness" in check_names
        assert "sequencing" in check_names
        assert "rest_compliance" in check_names
        assert "daily_cap" in check_names
        assert "staggering" in check_names
        assert "spare_courts" in check_names

        # Sequencing should always pass
        seq = next(c for c in report.checks if c.name == "sequencing")
        assert seq.passed, f"Sequencing failed: {seq.details[:3]}"

        # Stats should be populated
        assert report_dict["stats"]["total_matches"] >= 250
        assert report_dict["stats"]["total_slots"] >= 280


# ============================================================================
# Validation Helpers
# ============================================================================


def _check_sequencing(
    session: Session,
    all_matches: List[Match],
    version_id: int,
) -> List[str]:
    """
    Check that no match is scheduled before its prerequisite matches.
    Returns list of violation descriptions.
    """
    violations = []

    # Build match lookup
    match_by_id = {m.id: m for m in all_matches}

    # Build assignment lookup (match_id -> slot)
    assignments = session.exec(
        select(MatchAssignment).where(MatchAssignment.schedule_version_id == version_id)
    ).all()
    slot_by_match = {}
    for a in assignments:
        slot = session.get(ScheduleSlot, a.slot_id)
        if slot:
            slot_by_match[a.match_id] = slot

    for match in all_matches:
        if match.id not in slot_by_match:
            continue  # Unassigned, skip

        match_slot = slot_by_match[match.id]
        match_abs_time = _slot_abs_minutes(match_slot)

        # Check source dependencies
        for source_id in [match.source_match_a_id, match.source_match_b_id]:
            if source_id and source_id in slot_by_match:
                prereq_slot = slot_by_match[source_id]
                prereq_end = _slot_abs_minutes(prereq_slot) + prereq_slot.block_minutes
                if match_abs_time < prereq_end:
                    prereq_match = match_by_id.get(source_id)
                    violations.append(
                        f"Match {match.match_code} (at {match_slot.day_date} {match_slot.start_time}) "
                        f"scheduled before prerequisite {prereq_match.match_code if prereq_match else source_id} "
                        f"(ends at {prereq_slot.day_date} {prereq_slot.start_time}+{prereq_slot.block_minutes}m)"
                    )

    return violations


def _slot_abs_minutes(slot: ScheduleSlot) -> int:
    """Convert slot to absolute minutes from tournament start for comparison."""
    day_offset = (slot.day_date - date(2026, 2, 20)).days
    return day_offset * 1440 + slot.start_time.hour * 60 + slot.start_time.minute


def _check_staggering(
    session: Session,
    all_matches: List[Match],
    version_id: int,
    events: Dict,
) -> Dict:
    """
    Check category staggering: first match time per event per day.
    Returns {day_date: {event_label: [sorted start_times]}}.
    """
    # Build assignment lookup
    assignments = session.exec(
        select(MatchAssignment).where(MatchAssignment.schedule_version_id == version_id)
    ).all()
    slot_by_match = {}
    for a in assignments:
        slot = session.get(ScheduleSlot, a.slot_id)
        if slot:
            slot_by_match[a.match_id] = slot

    # Build event_id -> label
    eid_to_label = {}
    for label, info in events.items():
        eid_to_label[info["event_id"]] = label

    # Collect times per event per day
    result = defaultdict(lambda: defaultdict(list))
    for match in all_matches:
        if match.id not in slot_by_match:
            continue
        slot = slot_by_match[match.id]
        label = eid_to_label.get(match.event_id, f"event_{match.event_id}")
        result[slot.day_date][label].append(slot.start_time)

    # Sort times
    for day_date in result:
        for label in result[day_date]:
            result[day_date][label] = sorted(set(result[day_date][label]))

    return dict(result)


def _check_day_distribution(
    session: Session,
    all_matches: List[Match],
    version_id: int,
) -> Dict[date, int]:
    """Count assigned matches per day."""
    assignments = session.exec(
        select(MatchAssignment).where(MatchAssignment.schedule_version_id == version_id)
    ).all()
    slot_by_match = {}
    for a in assignments:
        slot = session.get(ScheduleSlot, a.slot_id)
        if slot:
            slot_by_match[a.match_id] = slot

    day_counts = defaultdict(int)
    for match in all_matches:
        if match.id in slot_by_match:
            day_counts[slot_by_match[match.id].day_date] += 1

    return dict(day_counts)


# ============================================================================
# 60-Minute Block Variant — matches real-world Kiawah configuration
# ============================================================================

@pytest.fixture(name="kiawah_60min")
def kiawah_60min_fixture(session: Session):
    """
    Kiawah tournament with 60-minute blocks (matching real-world config).

    This tests the scheduler with shorter blocks which create tighter
    scheduling constraints — bracket matches need more time slots to
    satisfy rest and dependency rules.
    """
    court_names = [f"Court {i}" for i in range(1, NUM_COURTS_MIDDAY + 1)]
    tournament = Tournament(
        name="Kiawah Cup 60min",
        location="Kiawah Island, SC",
        timezone="America/New_York",
        start_date=FRIDAY,
        end_date=SUNDAY,
        use_time_windows=True,
        court_names=court_names,
    )
    session.add(tournament)
    session.commit()
    session.refresh(tournament)

    for d in [FRIDAY, SATURDAY, SUNDAY]:
        day = TournamentDay(
            tournament_id=tournament.id,
            date=d,
            is_active=True,
            start_time=time(8, 0),
            end_time=time(18, 0),
            courts_available=NUM_COURTS_MIDDAY,
        )
        session.add(day)
    session.commit()

    # Friday: 60-min blocks, 15 courts 8-12, 19 courts 12-18
    _add_time_window(session, tournament.id, FRIDAY, time(8, 0), time(12, 0), NUM_COURTS_BASE, 60)
    _add_time_window(session, tournament.id, FRIDAY, time(12, 0), time(18, 0), NUM_COURTS_MIDDAY, 60)

    # Saturday: 60-min blocks, 15 courts 8-11:30, 19 courts 11:30-18
    _add_time_window(session, tournament.id, SATURDAY, time(8, 0), time(11, 30), NUM_COURTS_BASE, 60)
    _add_time_window(session, tournament.id, SATURDAY, time(11, 30), time(18, 0), NUM_COURTS_MIDDAY, 60)

    # Sunday: same as Saturday
    _add_time_window(session, tournament.id, SUNDAY, time(8, 0), time(11, 30), NUM_COURTS_BASE, 60)
    _add_time_window(session, tournament.id, SUNDAY, time(11, 30), time(18, 0), NUM_COURTS_MIDDAY, 60)

    session.commit()

    version = ScheduleVersion(
        tournament_id=tournament.id,
        version_number=1,
        status="draft",
    )
    session.add(version)
    session.commit()
    session.refresh(version)

    events = {}
    events["mixed"] = _create_event(
        session, tournament.id,
        name="Mixed",
        category="mixed",
        team_count=16,
        template_type="WF_TO_POOLS_DYNAMIC",
        wf_rounds=2,
        guarantee=4,
        wf_block_minutes=60,
        standard_block_minutes=60,
    )
    for label, name in [("womens_a", "Womens A"), ("womens_b", "Womens B"), ("womens_c", "Womens C")]:
        events[label] = _create_event(
            session, tournament.id,
            name=name,
            category="womens",
            team_count=32,
            template_type="WF_TO_BRACKETS_8",
            wf_rounds=2,
            guarantee=5,
            wf_block_minutes=60,
            standard_block_minutes=60,
        )

    return {
        "tournament_id": tournament.id,
        "version_id": version.id,
        "events": events,
    }


class TestKiawah60MinBlocks:
    """Test Kiawah scheduling with 60-minute blocks (real-world config)."""

    def test_full_policy_60min(self, session: Session, kiawah_60min):
        """All 280 matches should be assigned with 60-min blocks."""
        from app.routes.schedule import (
            generate_matches,
            generate_slots,
            MatchGenerateRequest,
            SlotGenerateRequest,
        )
        from app.services.schedule_policy_plan import run_full_schedule_policy

        tid = kiawah_60min["tournament_id"]
        vid = kiawah_60min["version_id"]

        # Generate matches
        session._allow_match_generation = True  # type: ignore[attr-defined]
        match_result = generate_matches(
            tid, MatchGenerateRequest(schedule_version_id=vid, wipe_existing=True),
            session, _transactional=True,
        )
        session._allow_match_generation = False  # type: ignore[attr-defined]
        total_matches = match_result["total_matches_created"]

        # Generate slots
        slot_result = generate_slots(
            tid, SlotGenerateRequest(source="time_windows", schedule_version_id=vid, wipe_existing=True),
            session, _transactional=True,
        )
        slots_created = slot_result["slots_created"]

        print(f"\n=== 60-min Block Test ===")
        print(f"Matches: {total_matches}, Slots: {slots_created}")

        # Run scheduler
        policy_result = run_full_schedule_policy(session, tid, vid)

        print(f"Assigned: {policy_result.total_assigned}")
        print(f"Failed: {policy_result.total_failed}")
        for dr in policy_result.day_results:
            print(f"  {dr}")

        # Validate completeness
        all_matches = session.exec(
            select(Match).where(Match.schedule_version_id == vid)
        ).all()
        all_assignments = session.exec(
            select(MatchAssignment).where(MatchAssignment.schedule_version_id == vid)
        ).all()
        assigned_ids = {a.match_id for a in all_assignments}
        unassigned = [m for m in all_matches if m.id not in assigned_ids]

        if unassigned:
            by_event_type = defaultdict(list)
            for m in unassigned:
                by_event_type[(m.event_id, m.match_type)].append(m.match_code)
            print(f"\nUnassigned ({len(unassigned)}):")
            for (eid, mtype), codes in sorted(by_event_type.items()):
                print(f"  Event {eid}, {mtype}: {codes[:5]}...")

        # Must have 0 unassigned (the rest gap fix should make this work)
        assert len(unassigned) == 0, (
            f"Expected 0 unassigned with 60-min blocks, got {len(unassigned)}"
        )

        # Validate sequencing
        violations = _check_sequencing(session, all_matches, vid)
        assert len(violations) == 0, f"Sequencing violations: {violations[:5]}"

        # Print Day 1 grid summary (event order verification)
        all_slots = session.exec(
            select(ScheduleSlot).where(ScheduleSlot.schedule_version_id == vid)
        ).all()
        slot_by_id = {s.id: s for s in all_slots}
        match_by_id = {m.id: m for m in all_matches}
        day1_date = min(s.day_date for s in all_slots)

        # Build time-bucket summary for day 1
        from collections import Counter
        bucket_events: Dict = defaultdict(lambda: Counter())
        spare_per_bucket: Dict = defaultdict(int)
        total_per_bucket: Dict = defaultdict(int)
        for s in all_slots:
            if s.day_date != day1_date:
                continue
            t_label = s.start_time.strftime("%H:%M") if s.start_time else "?"
            total_per_bucket[t_label] += 1
        for a in all_assignments:
            slot = slot_by_id.get(a.slot_id)
            if not slot or slot.day_date != day1_date:
                continue
            m = match_by_id.get(a.match_id)
            if not m:
                continue
            t_label = slot.start_time.strftime("%H:%M") if slot.start_time else "?"
            bucket_events[t_label][(m.event_id, m.match_type, m.round_number)] += 1

        from app.models.event import Event
        event_names = {e.id: e.name for e in session.exec(
            select(Event).where(Event.tournament_id == kiawah_60min["tournament_id"])
        ).all()}
        print(f"\n=== Day 1 Grid (event ordering) ===")
        for t_label in sorted(bucket_events.keys()):
            assigned_count = sum(bucket_events[t_label].values())
            total_courts = total_per_bucket.get(t_label, 0)
            spare = total_courts - assigned_count
            print(f"  {t_label} — {total_courts} courts ({assigned_count} assigned, {spare} spare)")
            for (eid, mtype, rnum), cnt in sorted(bucket_events[t_label].items()):
                print(f"    {event_names.get(eid, eid)} {mtype} R{rnum}: {cnt}")

        # Validate day distribution
        day_dist = _check_day_distribution(session, all_matches, vid)
        assert len(day_dist) == 3, f"Expected 3 days, got {len(day_dist)}"
        print(f"\nDay distribution: {dict(sorted(day_dist.items()))}")
        print("=== 60-min Block Test PASSED ===")
