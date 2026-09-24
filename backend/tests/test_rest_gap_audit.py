"""Tests for structured rest-gap audit and full-policy soft gate."""

from __future__ import annotations

from datetime import date, time, timedelta
from types import SimpleNamespace
from typing import List, Tuple

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.models.event import Event, EventCategory
from app.models.match import Match
from app.models.match_assignment import MatchAssignment
from app.models.schedule_slot import ScheduleSlot
from app.models.schedule_version import ScheduleVersion
from app.models.team import Team
from app.models.tournament import Tournament
from app.services.schedule_quality_report import (
    REST_MINUTES_WF_TO_SCORING,
    audit_rest_gaps,
    generate_quality_report,
)


DAY = date(2026, 3, 6)  # Friday


def _seed_short_rest_schedule(
    session: Session,
    *,
    r1_start: time = time(11, 0),
    r2_start: time = time(12, 30),
    block_minutes: int = 60,
) -> Tuple[int, int]:
    """
    Women's event: same two teams play WF R1 then WF R2 on one day.

    Default: 11:00 → 12:30 with 60min blocks → 30min rest (below 60 required).
    """
    tournament = Tournament(
        name="Rest Gap Test",
        location="Test",
        timezone="America/Phoenix",
        start_date=DAY,
        end_date=DAY + timedelta(days=2),
    )
    session.add(tournament)
    session.commit()
    session.refresh(tournament)

    version = ScheduleVersion(
        tournament_id=tournament.id,
        version_number=1,
        status="draft",
        notes="rest-gap",
    )
    session.add(version)
    session.commit()
    session.refresh(version)

    event = Event(
        tournament_id=tournament.id,
        category=EventCategory.womens,
        name="Women's A",
        team_count=4,
    )
    session.add(event)
    session.commit()
    session.refresh(event)

    t1 = Team(event_id=event.id, name="Alpha Pair", display_name="Alpha Pair")
    t2 = Team(event_id=event.id, name="Beta Pair", display_name="Beta Pair")
    t3 = Team(event_id=event.id, name="Gamma Pair", display_name="Gamma Pair")
    t4 = Team(event_id=event.id, name="Delta Pair", display_name="Delta Pair")
    session.add_all([t1, t2, t3, t4])
    session.commit()
    for t in (t1, t2, t3, t4):
        session.refresh(t)

    def end_time(start: time, minutes: int) -> time:
        total = start.hour * 60 + start.minute + minutes
        return time(total // 60, total % 60)

    slot_r1 = ScheduleSlot(
        tournament_id=tournament.id,
        schedule_version_id=version.id,
        day_date=DAY,
        start_time=r1_start,
        end_time=end_time(r1_start, block_minutes),
        court_number=1,
        court_label="1",
        block_minutes=block_minutes,
    )
    slot_r2 = ScheduleSlot(
        tournament_id=tournament.id,
        schedule_version_id=version.id,
        day_date=DAY,
        start_time=r2_start,
        end_time=end_time(r2_start, block_minutes),
        court_number=1,
        court_label="1",
        block_minutes=block_minutes,
    )
    session.add_all([slot_r1, slot_r2])
    session.commit()
    session.refresh(slot_r1)
    session.refresh(slot_r2)

    m_r1 = Match(
        tournament_id=tournament.id,
        event_id=event.id,
        schedule_version_id=version.id,
        match_code="W-WF-R1-1",
        match_type="WF",
        round_number=1,
        round_index=1,
        sequence_in_round=1,
        duration_minutes=block_minutes,
        team_a_id=t1.id,
        team_b_id=t2.id,
        placeholder_side_a="A",
        placeholder_side_b="B",
    )
    m_r2 = Match(
        tournament_id=tournament.id,
        event_id=event.id,
        schedule_version_id=version.id,
        match_code="W-WF-R2-1",
        match_type="WF",
        round_number=2,
        round_index=2,
        sequence_in_round=1,
        duration_minutes=block_minutes,
        team_a_id=t1.id,
        team_b_id=t2.id,
        placeholder_side_a="A",
        placeholder_side_b="B",
    )
    session.add_all([m_r1, m_r2])
    session.commit()
    session.refresh(m_r1)
    session.refresh(m_r2)

    session.add(
        MatchAssignment(
            schedule_version_id=version.id,
            match_id=m_r1.id,
            slot_id=slot_r1.id,
            assigned_by="TEST",
        )
    )
    session.add(
        MatchAssignment(
            schedule_version_id=version.id,
            match_id=m_r2.id,
            slot_id=slot_r2.id,
            assigned_by="TEST",
        )
    )
    session.commit()
    return tournament.id, version.id


def test_audit_short_rest_emits_team_issues(session: Session):
    tid, vid = _seed_short_rest_schedule(session)
    report = audit_rest_gaps(session, tid, vid)

    assert report.has_issues
    assert all(i.kind == "team" for i in report.issues)

    team_issues = report.issues
    assert len(team_issues) >= 2  # both teams in the match
    names = {i.team_name for i in team_issues}
    assert "Alpha Pair" in names
    assert "Beta Pair" in names
    for ti in team_issues:
        assert ti.actual_minutes == 30
        assert ti.required_minutes == REST_MINUTES_WF_TO_SCORING
        assert ti.prev_match_code == "W-WF-R1-1"
        assert ti.curr_match_code == "W-WF-R2-1"
        assert ti.event_name == "Women's A"
        assert ti.day == str(DAY)
        assert ti.prev_end_time == "12:00"
        assert ti.curr_start_time == "12:30"


def test_audit_structural_opt_in(session: Session):
    tid, vid = _seed_short_rest_schedule(session)
    report = audit_rest_gaps(session, tid, vid, include_structural=True)
    structural = [i for i in report.issues if i.kind == "structural"]
    assert len(structural) == 1
    s = structural[0]
    assert s.event_name == "Women's A"
    assert s.stage_transition == "WF R1 → WF R2"
    assert s.actual_minutes == 30


def test_audit_clean_double_duration_spacing_no_issues(session: Session):
    # 11:00 + 60min ends 12:00; 14:00 start → 120min rest (>= 60 WF rest)
    tid, vid = _seed_short_rest_schedule(
        session,
        r1_start=time(11, 0),
        r2_start=time(14, 0),
        block_minutes=60,
    )
    report = audit_rest_gaps(session, tid, vid)
    assert not report.has_issues
    assert report.issue_count == 0


def test_quality_report_rest_details_use_names(session: Session):
    tid, vid = _seed_short_rest_schedule(session)
    qr = generate_quality_report(session, tid, vid)
    rest_check = next(c for c in qr.checks if c.name == "rest_compliance")
    assert rest_check.passed is False
    assert any("Alpha Pair" in d for d in rest_check.details)
    assert any("Women's A" in d for d in rest_check.details)
    assert "rest_gap_report" in qr.stats
    assert qr.stats["rest_gap_report"]["issue_count"] > 0


def test_clear_assignments_endpoint(client: TestClient, session: Session):
    tid, vid = _seed_short_rest_schedule(session)
    before = session.exec(
        select(MatchAssignment).where(MatchAssignment.schedule_version_id == vid)
    ).all()
    assert len(before) == 2

    resp = client.post(f"/api/tournaments/{tid}/schedule/versions/{vid}/clear-assignments")
    assert resp.status_code == 200
    assert resp.json()["cleared_assignments_count"] == 2

    session.expire_all()
    after = session.exec(
        select(MatchAssignment).where(MatchAssignment.schedule_version_id == vid)
    ).all()
    assert after == []


def test_run_full_policy_needs_rest_approval(client: TestClient, session: Session, monkeypatch):
    tid, vid = _seed_short_rest_schedule(session)

    # Capture match/slot ids so the stub can re-place after clear
    matches = session.exec(select(Match).where(Match.schedule_version_id == vid)).all()
    slots = session.exec(select(ScheduleSlot).where(ScheduleSlot.schedule_version_id == vid)).all()
    by_code = {m.match_code: m for m in matches}
    by_time = {s.start_time: s for s in slots}
    place_pairs: List[Tuple[int, int]] = [
        (by_code["W-WF-R1-1"].id, by_time[time(11, 0)].id),
        (by_code["W-WF-R2-1"].id, by_time[time(12, 30)].id),
    ]

    def fake_sequence(sess, tournament_id, version_id, **kwargs):
        for match_id, slot_id in place_pairs:
            sess.add(
                MatchAssignment(
                    schedule_version_id=version_id,
                    match_id=match_id,
                    slot_id=slot_id,
                    assigned_by="STUB",
                )
            )
        sess.flush()
        return SimpleNamespace(
            total_assigned=2,
            total_failed=0,
            total_reserved_spares=0,
            duration_ms=1,
            day_results=[{"day": str(DAY), "assigned": 2, "failed": 0, "duration_ms": 1, "batches": []}],
            failed_matches=[],
        )

    def fake_verify(sess, tournament_id, version_id):
        return SimpleNamespace(
            ok=True,
            violations=[],
            to_dict=lambda: {"ok": True, "violations": [], "stats": {}},
        )

    import app.services.policy_invariants as inv_mod
    import app.services.schedule_sequence as seq_mod

    monkeypatch.setattr(seq_mod, "run_sequence_schedule", fake_sequence)
    monkeypatch.setattr(inv_mod, "verify_full_schedule", fake_verify)
    monkeypatch.setattr(inv_mod, "hash_policy_input", lambda *a, **k: "in")
    monkeypatch.setattr(inv_mod, "hash_policy_output", lambda *a, **k: "out")

    resp = client.post(f"/api/tournaments/{tid}/schedule/versions/{vid}/run-full-policy")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["needs_rest_approval"] is True
    assert data["rest_gap_report"] is not None
    assert data["rest_gap_report"]["issue_count"] > 0
    assert data["total_assigned"] == 2

    # Assignments remain committed
    session.expire_all()
    remaining = session.exec(
        select(MatchAssignment).where(MatchAssignment.schedule_version_id == vid)
    ).all()
    assert len(remaining) == 2

    # accept_short_rest skips soft gate flag
    resp2 = client.post(
        f"/api/tournaments/{tid}/schedule/versions/{vid}/run-full-policy?accept_short_rest=true"
    )
    assert resp2.status_code == 200, resp2.text
    data2 = resp2.json()
    assert data2["needs_rest_approval"] is False
    assert data2["rest_gap_report"] is not None  # still returned for visibility

    # force also skips soft gate
    resp3 = client.post(
        f"/api/tournaments/{tid}/schedule/versions/{vid}/run-full-policy?force=true"
    )
    assert resp3.status_code == 200, resp3.text
    assert resp3.json()["needs_rest_approval"] is False
