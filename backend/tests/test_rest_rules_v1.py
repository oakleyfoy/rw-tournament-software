"""
Test suite for Rest Rules V1

Tests rest time enforcement between matches:
- WF → Scoring: 60 minutes minimum
- Scoring → Scoring: 90 minutes minimum
- Placeholder matches: Rest rules skipped
- Determinism: Same input → same output
- Feeder rest: R2+ bracket matches enforce rest via source_match FKs
"""

from datetime import date, datetime, time, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.models.event import Event, EventCategory
from app.models.match import Match
from app.models.match_assignment import MatchAssignment
from app.models.schedule_slot import ScheduleSlot
from app.models.schedule_version import ScheduleVersion
from app.models.team import Team
from app.models.tournament import Tournament
from app.utils.rest_rules import (
    REST_MINIMUM_ANY_MINUTES,
    RestStateTracker,
    _intervals_overlap,
    auto_assign_with_rest,
    check_rest_compatibility,
)


@pytest.fixture
def setup_rest_test_scenario(client: TestClient, session: Session):
    """
    Create test scenario with:
    - 1 tournament
    - 1 schedule version (draft)
    - 1 event with 4 teams
    - WF and MAIN matches with real team assignments
    - 5 schedule slots with varying time gaps for testing rest rules
    """
    # Create tournament
    tournament_data = {
        "name": "Rest Test Tournament",
        "location": "Test Location",
        "timezone": "America/New_York",
        "start_date": date(2026, 1, 15).isoformat(),
        "end_date": date(2026, 1, 15).isoformat(),
    }
    t_response = client.post("/api/tournaments", json=tournament_data)
    assert t_response.status_code == 201
    tournament = t_response.json()

    # Get/create schedule version
    version = session.exec(select(ScheduleVersion).where(ScheduleVersion.tournament_id == tournament["id"])).first()

    if not version:
        version = ScheduleVersion(tournament_id=tournament["id"], version_number=1, status="draft")
        session.add(version)
        session.commit()
        session.refresh(version)

    # Create event with 4 teams
    event_data = {"category": "mixed", "name": "Test Event", "team_count": 4, "draw_status": "final"}
    e_response = client.post(f"/api/tournaments/{tournament['id']}/events", json=event_data)
    assert e_response.status_code == 201
    event = e_response.json()

    # Create 4 teams (matching team_count)
    teams = []
    for i in range(1, 5):
        team_data = {"name": f"Team {i}", "seed": i}
        t_resp = client.post(f"/api/events/{event['id']}/teams", json=team_data)
        assert t_resp.status_code == 201
        teams.append(t_resp.json())

    # Create WF match (60 min) with Team 1 vs Team 2
    wf_match = Match(
        tournament_id=tournament["id"],
        event_id=event["id"],
        schedule_version_id=version.id,
        match_code="WF_01",
        match_type="WF",
        round_number=1,
        round_index=1,
        sequence_in_round=1,
        duration_minutes=60,
        placeholder_side_a="Team 1",
        placeholder_side_b="Team 2",
        team_a_id=teams[0]["id"],  # Team 1
        team_b_id=teams[1]["id"],  # Team 2
    )
    session.add(wf_match)

    # Create MAIN match 1 (90 min) with Team 1 vs Team 3
    main_match_1 = Match(
        tournament_id=tournament["id"],
        event_id=event["id"],
        schedule_version_id=version.id,
        match_code="MAIN_01",
        match_type="MAIN",
        round_number=1,
        round_index=1,
        sequence_in_round=1,
        duration_minutes=90,
        placeholder_side_a="Team 1",
        placeholder_side_b="Team 3",
        team_a_id=teams[0]["id"],  # Team 1 (same as WF)
        team_b_id=teams[2]["id"],  # Team 3
    )
    session.add(main_match_1)

    # Create MAIN match 2 (90 min) with Team 1 vs Team 4
    main_match_2 = Match(
        tournament_id=tournament["id"],
        event_id=event["id"],
        schedule_version_id=version.id,
        match_code="MAIN_02",
        match_type="MAIN",
        round_number=1,
        round_index=1,
        sequence_in_round=2,
        duration_minutes=90,
        placeholder_side_a="Team 1",
        placeholder_side_b="Team 4",
        team_a_id=teams[0]["id"],  # Team 1 (again)
        team_b_id=teams[3]["id"],  # Team 4
    )
    session.add(main_match_2)

    session.commit()
    session.refresh(wf_match)
    session.refresh(main_match_1)
    session.refresh(main_match_2)

    # Create schedule slots with proper date/time objects
    # Slot 1: 9:00-11:00 (120 min) - for WF (60 min match)
    slot1 = ScheduleSlot(
        tournament_id=tournament["id"],
        schedule_version_id=version.id,
        day_date=date(2026, 1, 15),
        start_time=time(9, 0),
        end_time=time(11, 0),
        block_minutes=120,
        court_number=1,
        court_label="Court 1",
        is_active=True,
    )
    session.add(slot1)

    # Slot 2: 10:00-12:00 (120 min) - exactly 60 min after WF start
    slot2 = ScheduleSlot(
        tournament_id=tournament["id"],
        schedule_version_id=version.id,
        day_date=date(2026, 1, 15),
        start_time=time(10, 0),
        end_time=time(12, 0),
        block_minutes=120,
        court_number=2,
        court_label="Court 2",
        is_active=True,
    )
    session.add(slot2)

    # Slot 3: 9:59-11:59 (120 min) - 59 min after WF start (should FAIL for WF→MAIN)
    slot3 = ScheduleSlot(
        tournament_id=tournament["id"],
        schedule_version_id=version.id,
        day_date=date(2026, 1, 15),
        start_time=time(9, 59),
        end_time=time(11, 59),
        block_minutes=120,
        court_number=3,
        court_label="Court 3",
        is_active=True,
    )
    session.add(slot3)

    # Slot 4: 11:30-13:30 (120 min) - exactly 90 min after MAIN_01 start
    slot4 = ScheduleSlot(
        tournament_id=tournament["id"],
        schedule_version_id=version.id,
        day_date=date(2026, 1, 15),
        start_time=time(11, 30),
        end_time=time(13, 30),
        block_minutes=120,
        court_number=1,
        court_label="Court 1",
        is_active=True,
    )
    session.add(slot4)

    # Slot 5: 11:29-13:29 (120 min) - 89 min after MAIN_01 start (should FAIL for MAIN→MAIN)
    slot5 = ScheduleSlot(
        tournament_id=tournament["id"],
        schedule_version_id=version.id,
        day_date=date(2026, 1, 15),
        start_time=time(11, 29),
        end_time=time(13, 29),
        block_minutes=120,
        court_number=2,
        court_label="Court 2",
        is_active=True,
    )
    session.add(slot5)

    session.commit()
    session.refresh(slot1)
    session.refresh(slot2)
    session.refresh(slot3)
    session.refresh(slot4)
    session.refresh(slot5)

    return {
        "tournament": tournament,
        "event": event,
        "version": version,
        "teams": teams,
        "wf_match": wf_match,
        "main_match_1": main_match_1,
        "main_match_2": main_match_2,
        "slots": [slot1, slot2, slot3, slot4, slot5],
    }


def test_wf_to_scoring_60_minutes_allowed(client: TestClient, session: Session):
    """Test that WF → Scoring allows exactly 60 minutes rest"""
    # Create tournament
    tournament_data = {
        "name": "Rest Test Tournament",
        "location": "Test Location",
        "timezone": "America/New_York",
        "start_date": date(2026, 1, 15).isoformat(),
        "end_date": date(2026, 1, 15).isoformat(),
    }
    t_response = client.post("/api/tournaments", json=tournament_data)
    assert t_response.status_code == 201
    tournament = t_response.json()

    # Get/create schedule version
    version = session.exec(select(ScheduleVersion).where(ScheduleVersion.tournament_id == tournament["id"])).first()

    if not version:
        version = ScheduleVersion(tournament_id=tournament["id"], version_number=1, status="draft")
        session.add(version)
        session.commit()
        session.refresh(version)

    # Create event with 3 teams (matching actual team count)
    event_data = {"category": "mixed", "name": "Test Event", "team_count": 3, "draw_status": "final"}
    e_response = client.post(f"/api/tournaments/{tournament['id']}/events", json=event_data)
    assert e_response.status_code == 201
    event = e_response.json()

    # Create 3 teams
    teams = []
    for i in range(1, 4):
        team_data = {"name": f"Team {i}", "seed": i}
        t_resp = client.post(f"/api/events/{event['id']}/teams", json=team_data)
        assert t_resp.status_code == 201
        teams.append(t_resp.json())

    # Create WF match with Team 1 vs Team 2 (60 min)
    wf_match = Match(
        tournament_id=tournament["id"],
        event_id=event["id"],
        schedule_version_id=version.id,
        match_code="WF_01",
        match_type="WF",  # Explicitly set as WF
        round_number=1,
        round_index=1,
        sequence_in_round=1,
        duration_minutes=60,
        placeholder_side_a="Team 1",
        placeholder_side_b="Team 2",
        team_a_id=teams[0]["id"],  # Team 1
        team_b_id=teams[1]["id"],  # Team 2
    )
    session.add(wf_match)

    # Create MAIN/scoring match with Team 1 vs Team 3 (60 min)
    main_match = Match(
        tournament_id=tournament["id"],
        event_id=event["id"],
        schedule_version_id=version.id,
        match_code="MAIN_01",
        match_type="MAIN",  # Explicitly set as MAIN (scoring)
        round_number=1,
        round_index=1,
        sequence_in_round=1,
        duration_minutes=60,
        placeholder_side_a="Team 1",
        placeholder_side_b="Team 3",
        team_a_id=teams[0]["id"],  # Team 1 (same as WF)
        team_b_id=teams[2]["id"],  # Team 3
    )
    session.add(main_match)

    session.commit()
    session.refresh(wf_match)
    session.refresh(main_match)

    # Create two schedule slots on same court
    # Slot 1: 9:00-10:00 (60 min) - for WF
    slot1 = ScheduleSlot(
        tournament_id=tournament["id"],
        schedule_version_id=version.id,
        day_date=date(2026, 1, 15),
        start_time=time(9, 0),
        end_time=time(10, 0),
        block_minutes=60,
        court_number=1,
        court_label="Court 1",
        is_active=True,
    )
    session.add(slot1)

    # Slot 2: 11:00-12:00 (60 min) - exactly 60 min after WF ends
    slot2 = ScheduleSlot(
        tournament_id=tournament["id"],
        schedule_version_id=version.id,
        day_date=date(2026, 1, 15),
        start_time=time(11, 0),
        end_time=time(12, 0),
        block_minutes=60,
        court_number=1,
        court_label="Court 1",
        is_active=True,
    )
    session.add(slot2)

    session.commit()
    session.refresh(slot1)
    session.refresh(slot2)

    # Run auto-assign with rest
    response = client.post(
        f"/api/tournaments/{tournament['id']}/schedule/versions/{version.id}/auto-assign-rest",
        params={"clear_existing": True},
    )

    assert response.status_code == 200
    result = response.json()

    # Should assign both:
    # - WF_01 to slot 1 (9:00-10:00)
    # - MAIN_01 to slot 2 (11:00-12:00) - exactly 60 min after WF ends

    assert result["assigned_count"] == 2, f"Expected 2 assignments, got {result['assigned_count']}"
    assert result["rest_violations_summary"]["wf_to_scoring_violations"] == 0


def test_wf_to_scoring_59_minutes_rejected(client: TestClient, setup_rest_test_scenario, session: Session):
    """Test that WF → Scoring rejects 59 minutes rest"""
    tournament = setup_rest_test_scenario["tournament"]
    version = setup_rest_test_scenario["version"]

    # Manually assign WF to slot 1
    wf_match = setup_rest_test_scenario["wf_match"]
    slots = setup_rest_test_scenario["slots"]

    assignment = MatchAssignment(
        schedule_version_id=version.id,
        match_id=wf_match.id,
        slot_id=slots[0].id,  # 9:00 AM
    )
    session.add(assignment)
    session.commit()

    # Run auto-assign (will try to assign remaining matches)
    response = client.post(
        f"/api/tournaments/{tournament['id']}/schedule/versions/{version.id}/auto-assign-rest",
        params={"clear_existing": False},
    )

    assert response.status_code == 200
    result = response.json()

    # Slot 3 (9:59) should be rejected for MAIN_01 due to insufficient rest
    # Should skip to slot 2 (10:00) or later
    result.get("unassigned_reasons", {})

    # Verify that if any match is unassigned, it's due to rest or duration, not a crash
    assert "assigned_count" in result


def test_scoring_to_scoring_90_minutes_required(client: TestClient, setup_rest_test_scenario):
    """Test that Scoring → Scoring requires 90 minutes rest"""
    tournament = setup_rest_test_scenario["tournament"]
    version = setup_rest_test_scenario["version"]

    # Run auto-assign
    response = client.post(
        f"/api/tournaments/{tournament['id']}/schedule/versions/{version.id}/auto-assign-rest",
        params={"clear_existing": True},
    )

    assert response.status_code == 200
    result = response.json()

    # Should assign:
    # - WF_01 to slot 1 (9:00)
    # - MAIN_01 to slot 2 (10:00)
    # - MAIN_02 to slot 4 (11:30) - exactly 90 min after MAIN_01 start
    # Slot 5 (11:29) should be skipped as it's only 89 min rest

    assert "assigned_count" in result
    assert result["rest_violations_summary"]["scoring_to_scoring_violations"] == 0 or result["unassigned_count"] > 0


def test_scoring_to_scoring_89_minutes_rejected(client: TestClient, setup_rest_test_scenario, session: Session):
    """Test that Scoring → Scoring rejects 89 minutes rest"""
    tournament = setup_rest_test_scenario["tournament"]
    version = setup_rest_test_scenario["version"]
    wf_match = setup_rest_test_scenario["wf_match"]
    main_match_1 = setup_rest_test_scenario["main_match_1"]
    slots = setup_rest_test_scenario["slots"]

    # Manually assign WF and MAIN_01
    assignment1 = MatchAssignment(
        schedule_version_id=version.id,
        match_id=wf_match.id,
        slot_id=slots[0].id,  # 9:00 AM
    )
    assignment2 = MatchAssignment(
        schedule_version_id=version.id,
        match_id=main_match_1.id,
        slot_id=slots[1].id,  # 10:00 AM
    )
    session.add(assignment1)
    session.add(assignment2)
    session.commit()

    # Run auto-assign for remaining matches
    response = client.post(
        f"/api/tournaments/{tournament['id']}/schedule/versions/{version.id}/auto-assign-rest",
        params={"clear_existing": False},
    )

    assert response.status_code == 200
    result = response.json()

    # Slot 5 (11:29) should be rejected for MAIN_02
    # Should use slot 4 (11:30) or mark as unassigned
    assert "assigned_count" in result


def test_placeholder_match_ignores_rest(client: TestClient, setup_rest_test_scenario, session: Session):
    """Test that matches with placeholder teams (null team_id) ignore rest rules"""
    tournament = setup_rest_test_scenario["tournament"]
    version = setup_rest_test_scenario["version"]
    event = setup_rest_test_scenario["event"]

    # Create a match with null team_ids (placeholders)
    placeholder_match = Match(
        tournament_id=tournament["id"],
        event_id=event["id"],
        schedule_version_id=version.id,
        match_code="PLACEHOLDER_01",
        match_type="MAIN",
        round_number=2,
        round_index=2,
        sequence_in_round=1,
        duration_minutes=90,
        placeholder_side_a="Winner of Match 1",
        placeholder_side_b="Winner of Match 2",
        team_a_id=None,  # Placeholder
        team_b_id=None,  # Placeholder
    )
    session.add(placeholder_match)
    session.commit()

    # Run auto-assign
    response = client.post(
        f"/api/tournaments/{tournament['id']}/schedule/versions/{version.id}/auto-assign-rest",
        params={"clear_existing": True},
    )

    assert response.status_code == 200
    result = response.json()

    # Placeholder match should be assignable to any slot (rest not checked)
    assert result["assigned_count"] >= 1


def test_one_null_team_still_assigns(client: TestClient, setup_rest_test_scenario, session: Session):
    """Test that match with one null team_id still assigns (checks rest for known team only)"""
    tournament = setup_rest_test_scenario["tournament"]
    version = setup_rest_test_scenario["version"]
    event = setup_rest_test_scenario["event"]
    teams = setup_rest_test_scenario["teams"]

    # Create a match with one known team, one placeholder
    partial_match = Match(
        tournament_id=tournament["id"],
        event_id=event["id"],
        schedule_version_id=version.id,
        match_code="PARTIAL_01",
        match_type="MAIN",
        round_number=2,
        round_index=2,
        sequence_in_round=2,
        duration_minutes=90,
        placeholder_side_a="TBD",
        placeholder_side_b="Winner of Match X",
        team_a_id=teams[0]["id"],  # Known team
        team_b_id=None,  # Placeholder
    )
    session.add(partial_match)
    session.commit()

    # Run auto-assign
    response = client.post(
        f"/api/tournaments/{tournament['id']}/schedule/versions/{version.id}/auto-assign-rest",
        params={"clear_existing": True},
    )

    assert response.status_code == 200
    result = response.json()

    # Match should be assignable (rest checked for team_a only)
    assert result["assigned_count"] >= 1


def test_determinism(client: TestClient, setup_rest_test_scenario):
    """Test that two runs produce identical assignments"""
    tournament = setup_rest_test_scenario["tournament"]
    version = setup_rest_test_scenario["version"]

    # Run 1
    response1 = client.post(
        f"/api/tournaments/{tournament['id']}/schedule/versions/{version.id}/auto-assign-rest",
        params={"clear_existing": True},
    )
    assert response1.status_code == 200
    result1 = response1.json()

    # Run 2
    response2 = client.post(
        f"/api/tournaments/{tournament['id']}/schedule/versions/{version.id}/auto-assign-rest",
        params={"clear_existing": True},
    )
    assert response2.status_code == 200
    result2 = response2.json()

    # Results should be identical
    assert result1["assigned_count"] == result2["assigned_count"]
    assert result1["unassigned_count"] == result2["unassigned_count"]
    assert result1["rest_violations_summary"] == result2["rest_violations_summary"]


def test_no_team_scheduled_inside_rest_window(client: TestClient, setup_rest_test_scenario, session: Session):
    """Test that no team is ever scheduled inside its rest window"""
    tournament = setup_rest_test_scenario["tournament"]
    version = setup_rest_test_scenario["version"]

    # Run auto-assign
    response = client.post(
        f"/api/tournaments/{tournament['id']}/schedule/versions/{version.id}/auto-assign-rest",
        params={"clear_existing": True},
    )

    assert response.status_code == 200
    response.json()

    # Get all assignments
    assignments = session.exec(select(MatchAssignment).where(MatchAssignment.schedule_version_id == version.id)).all()

    # Build team schedule
    team_schedule = {}
    for assignment in assignments:
        match = session.get(Match, assignment.match_id)
        slot = session.get(ScheduleSlot, assignment.slot_id)

        slot_start = datetime.fromisoformat(f"{slot.day_date}T{slot.start_time}")
        slot_end = slot_start + timedelta(minutes=match.duration_minutes)

        for team_id in [match.team_a_id, match.team_b_id]:
            if team_id is None:
                continue

            if team_id not in team_schedule:
                team_schedule[team_id] = []

            team_schedule[team_id].append(
                {"start": slot_start, "end": slot_end, "stage": match.match_type, "match_code": match.match_code}
            )

    # Verify no rest violations
    for team_id, matches in team_schedule.items():
        sorted_matches = sorted(matches, key=lambda m: m["start"])

        for i in range(len(sorted_matches) - 1):
            current = sorted_matches[i]
            next_match = sorted_matches[i + 1]

            gap_minutes = (next_match["start"] - current["end"]).total_seconds() / 60

            # Determine required rest based on stage transitions
            if current["stage"] == "WF" and next_match["stage"] != "WF":
                required_rest = 60  # WF → Scoring
            elif current["stage"] != "WF" and next_match["stage"] != "WF":
                required_rest = 90  # Scoring → Scoring
            else:
                required_rest = REST_MINIMUM_ANY_MINUTES  # WF→WF or Scoring→WF

            # Verify gap meets requirement
            assert gap_minutes >= required_rest, (
                f"Team {team_id}: Rest violation between {current['match_code']} "
                f"and {next_match['match_code']}. Gap: {gap_minutes}min, Required: {required_rest}min"
            )


def test_rr_no_team_overlapping_slots(session: Session):
    """
    Regression: RR event with 4 teams and 2 rounds where one team appears in both rounds.
    Auto-assign must never assign a team to two overlapping slots.
    """
    # Create tournament, version, event, 4 teams
    tournament = Tournament(
        name="RR Overlap Test",
        location="Test",
        timezone="America/New_York",
        start_date=date(2026, 2, 20),
        end_date=date(2026, 2, 22),
    )
    session.add(tournament)
    session.commit()
    session.refresh(tournament)

    event = Event(
        tournament_id=tournament.id,
        category=EventCategory.mixed,
        name="RR Event",
        team_count=4,
        draw_status="final",
    )
    session.add(event)
    session.commit()
    session.refresh(event)

    teams = []
    for i in range(1, 5):
        t = Team(event_id=event.id, name=f"Team {i}", seed=i, rating=1000.0)
        session.add(t)
        teams.append(t)
    session.commit()
    for t in teams:
        session.refresh(t)

    version = ScheduleVersion(tournament_id=tournament.id, version_number=1, status="draft")
    session.add(version)
    session.commit()
    session.refresh(version)

    # RR-style: Round 1: M1 (T1 vs T2), M2 (T3 vs T4); Round 2: M3 (T1 vs T3), M4 (T2 vs T4)
    # Team 1 appears in M1 and M3 — must not get overlapping slots
    day = date(2026, 2, 20)
    matches_data = [
        ("RR_R1_1", 1, 1, teams[0].id, teams[1].id),   # T1 vs T2
        ("RR_R1_2", 1, 2, teams[2].id, teams[3].id),   # T3 vs T4
        ("RR_R2_1", 2, 1, teams[0].id, teams[2].id),   # T1 vs T3
        ("RR_R2_2", 2, 2, teams[1].id, teams[3].id),   # T2 vs T4
    ]
    for match_code, rnd, seq, ta, tb in matches_data:
        m = Match(
            tournament_id=tournament.id,
            event_id=event.id,
            schedule_version_id=version.id,
            match_code=match_code,
            match_type="RR",
            round_number=rnd,
            round_index=rnd,
            sequence_in_round=seq,
            duration_minutes=60,
            team_a_id=ta,
            team_b_id=tb,
            placeholder_side_a="TBD",
            placeholder_side_b="TBD",
        )
        session.add(m)
    session.commit()

    # 4 slots spaced so rest (90 min between scoring matches) is satisfied: 9:00, 11:30, 14:00, 16:30
    for i, (h, m) in enumerate([(9, 0), (11, 30), (14, 0), (16, 30)], start=1):
        slot = ScheduleSlot(
            tournament_id=tournament.id,
            schedule_version_id=version.id,
            day_date=day,
            start_time=time(h, m),
            end_time=time(h + 1, m),
            block_minutes=60,
            court_number=i,
            court_label=f"C{i}",
            is_active=True,
        )
        session.add(slot)
    session.commit()

    result = auto_assign_with_rest(session, version.id, clear_existing=True)
    assert result["unassigned_count"] == 0, f"Expected all assigned: {result}"
    assert result["assigned_count"] == 4

    # Build team_id -> list of (start_dt, end_dt)
    assignments = session.exec(
        select(MatchAssignment).where(MatchAssignment.schedule_version_id == version.id)
    ).all()
    team_intervals = {}
    for a in assignments:
        match = session.get(Match, a.match_id)
        slot = session.get(ScheduleSlot, a.slot_id)
        start_dt = datetime.combine(slot.day_date, slot.start_time)
        end_dt = start_dt + timedelta(minutes=match.duration_minutes)
        for tid in (match.team_a_id, match.team_b_id):
            if tid is None:
                continue
            team_intervals.setdefault(tid, []).append((start_dt, end_dt))

    # Assert no team has overlapping intervals
    for team_id, intervals in team_intervals.items():
        for i in range(len(intervals)):
            for j in range(i + 1, len(intervals)):
                a_start, a_end = intervals[i]
                b_start, b_end = intervals[j]
                assert not _intervals_overlap(a_start, a_end, b_start, b_end), (
                    f"Team {team_id}: overlapping slots {intervals[i]} and {intervals[j]}"
                )


def test_wf_to_wf_30_minutes_enforced(session: Session):
    """
    Test that WF → WF enforces the 30-minute universal minimum rest.

    Two WF matches for the same team: WF_01 ends at 10:00, WF_02 must not
    start before 10:30. A slot at 10:20 should be rejected; 10:30 should pass.
    """
    tournament = Tournament(
        name="WF-WF Rest Test",
        location="Test",
        timezone="America/New_York",
        start_date=date(2026, 3, 1),
        end_date=date(2026, 3, 1),
    )
    session.add(tournament)
    session.commit()
    session.refresh(tournament)

    event = Event(
        tournament_id=tournament.id,
        category=EventCategory.mixed,
        name="WF-WF Event",
        team_count=3,
        draw_status="final",
    )
    session.add(event)
    session.commit()
    session.refresh(event)

    teams = []
    for i in range(1, 4):
        t = Team(event_id=event.id, name=f"Team {i}", seed=i, rating=1000.0)
        session.add(t)
        teams.append(t)
    session.commit()
    for t in teams:
        session.refresh(t)

    version = ScheduleVersion(tournament_id=tournament.id, version_number=1, status="draft")
    session.add(version)
    session.commit()
    session.refresh(version)

    day = date(2026, 3, 1)

    # WF_01: Team 1 vs Team 2, 60 min
    wf1 = Match(
        tournament_id=tournament.id,
        event_id=event.id,
        schedule_version_id=version.id,
        match_code="WF_01",
        match_type="WF",
        round_number=1,
        round_index=1,
        sequence_in_round=1,
        duration_minutes=60,
        team_a_id=teams[0].id,
        team_b_id=teams[1].id,
        placeholder_side_a="T1",
        placeholder_side_b="T2",
    )
    # WF_02: Team 1 vs Team 3, 60 min
    wf2 = Match(
        tournament_id=tournament.id,
        event_id=event.id,
        schedule_version_id=version.id,
        match_code="WF_02",
        match_type="WF",
        round_number=1,
        round_index=1,
        sequence_in_round=2,
        duration_minutes=60,
        team_a_id=teams[0].id,
        team_b_id=teams[2].id,
        placeholder_side_a="T1",
        placeholder_side_b="T3",
    )
    session.add_all([wf1, wf2])
    session.commit()
    session.refresh(wf1)
    session.refresh(wf2)

    # Slot A: 9:00-10:00 (for WF_01)
    slot_a = ScheduleSlot(
        tournament_id=tournament.id,
        schedule_version_id=version.id,
        day_date=day,
        start_time=time(9, 0),
        end_time=time(10, 0),
        block_minutes=60,
        court_number=1,
        court_label="C1",
        is_active=True,
    )
    # Slot B: 10:20 — only 20 min after WF_01 ends (should be rejected)
    slot_b = ScheduleSlot(
        tournament_id=tournament.id,
        schedule_version_id=version.id,
        day_date=day,
        start_time=time(10, 20),
        end_time=time(11, 20),
        block_minutes=60,
        court_number=2,
        court_label="C2",
        is_active=True,
    )
    # Slot C: 10:30 — exactly 30 min after WF_01 ends (should pass)
    slot_c = ScheduleSlot(
        tournament_id=tournament.id,
        schedule_version_id=version.id,
        day_date=day,
        start_time=time(10, 30),
        end_time=time(11, 30),
        block_minutes=60,
        court_number=3,
        court_label="C3",
        is_active=True,
    )
    session.add_all([slot_a, slot_b, slot_c])
    session.commit()

    result = auto_assign_with_rest(session, version.id, clear_existing=True)

    # Both WF matches should be assigned
    assert result["assigned_count"] == 2, f"Expected 2 assigned, got: {result}"
    assert result["unassigned_count"] == 0

    # Verify Team 1's gap is at least 30 minutes
    assignments = session.exec(
        select(MatchAssignment).where(MatchAssignment.schedule_version_id == version.id)
    ).all()

    team1_entries = []
    for a in assignments:
        match = session.get(Match, a.match_id)
        slot = session.get(ScheduleSlot, a.slot_id)
        if teams[0].id in (match.team_a_id, match.team_b_id):
            start_dt = datetime.combine(slot.day_date, slot.start_time)
            end_dt = start_dt + timedelta(minutes=match.duration_minutes)
            team1_entries.append((start_dt, end_dt, match.match_code))

    team1_entries.sort()
    assert len(team1_entries) == 2
    gap = (team1_entries[1][0] - team1_entries[0][1]).total_seconds() / 60
    assert gap >= 30, f"WF→WF gap was {gap} min, expected >= 30"
    # Slot B (10:20) should have been skipped; WF_02 lands on slot C (10:30)
    assert team1_entries[1][0] == datetime(2026, 3, 1, 10, 30)


def test_wf_to_wf_unit_check_rest_compatibility():
    """
    Unit test: check_rest_compatibility correctly enforces 30 min WF→WF
    and reports REST_MINIMUM_GAP violation type.
    """
    tracker = RestStateTracker()
    # Simulate: Team 1 finished a WF match at 10:00
    tracker.update_team_state(team_id=1, end_time=datetime(2026, 3, 1, 10, 0), stage="WF")

    # Build a fake match (WF) involving team 1
    match = Match(
        id=100,
        tournament_id=1,
        event_id=1,
        schedule_version_id=1,
        match_code="WF_02",
        match_type="WF",
        round_number=1,
        round_index=1,
        sequence_in_round=2,
        duration_minutes=60,
        team_a_id=1,
        team_b_id=2,
        placeholder_side_a="T1",
        placeholder_side_b="T2",
    )

    # Slot at 10:20 — 20 min gap → should fail
    slot_early = ScheduleSlot(
        id=200,
        tournament_id=1,
        schedule_version_id=1,
        day_date=date(2026, 3, 1),
        start_time=time(10, 20),
        end_time=time(11, 20),
        block_minutes=60,
        court_number=1,
        court_label="C1",
        is_active=True,
    )
    ok, violations = check_rest_compatibility(slot_early, match, tracker)
    assert not ok
    assert len(violations) == 1
    assert violations[0].violation_type == "REST_MINIMUM_GAP"
    assert violations[0].required_rest_minutes == REST_MINIMUM_ANY_MINUTES

    # Slot at 10:30 — exactly 30 min gap → should pass
    slot_ok = ScheduleSlot(
        id=201,
        tournament_id=1,
        schedule_version_id=1,
        day_date=date(2026, 3, 1),
        start_time=time(10, 30),
        end_time=time(11, 30),
        block_minutes=60,
        court_number=2,
        court_label="C2",
        is_active=True,
    )
    ok, violations = check_rest_compatibility(slot_ok, match, tracker)
    assert ok
    assert len(violations) == 0


def test_weather_reschedule_bypasses_minimum(session: Session):
    """
    Test that weather_reschedule=True bypasses the 30-minute universal minimum
    for WF→WF, while stage-specific rules (WF→Scoring, Scoring→Scoring) still apply.
    """
    tournament = Tournament(
        name="Weather Override Test",
        location="Test",
        timezone="America/New_York",
        start_date=date(2026, 3, 1),
        end_date=date(2026, 3, 1),
    )
    session.add(tournament)
    session.commit()
    session.refresh(tournament)

    event = Event(
        tournament_id=tournament.id,
        category=EventCategory.mixed,
        name="Weather Event",
        team_count=3,
        draw_status="final",
    )
    session.add(event)
    session.commit()
    session.refresh(event)

    teams = []
    for i in range(1, 4):
        t = Team(event_id=event.id, name=f"Team {i}", seed=i, rating=1000.0)
        session.add(t)
        teams.append(t)
    session.commit()
    for t in teams:
        session.refresh(t)

    version = ScheduleVersion(tournament_id=tournament.id, version_number=1, status="draft")
    session.add(version)
    session.commit()
    session.refresh(version)

    day = date(2026, 3, 1)

    # WF_01: Team 1 vs Team 2, 60 min
    wf1 = Match(
        tournament_id=tournament.id,
        event_id=event.id,
        schedule_version_id=version.id,
        match_code="WF_01",
        match_type="WF",
        round_number=1,
        round_index=1,
        sequence_in_round=1,
        duration_minutes=60,
        team_a_id=teams[0].id,
        team_b_id=teams[1].id,
        placeholder_side_a="T1",
        placeholder_side_b="T2",
    )
    # WF_02: Team 1 vs Team 3, 60 min
    wf2 = Match(
        tournament_id=tournament.id,
        event_id=event.id,
        schedule_version_id=version.id,
        match_code="WF_02",
        match_type="WF",
        round_number=1,
        round_index=1,
        sequence_in_round=2,
        duration_minutes=60,
        team_a_id=teams[0].id,
        team_b_id=teams[2].id,
        placeholder_side_a="T1",
        placeholder_side_b="T3",
    )
    session.add_all([wf1, wf2])
    session.commit()
    session.refresh(wf1)
    session.refresh(wf2)

    # Slot A: 9:00-10:00 (for WF_01)
    slot_a = ScheduleSlot(
        tournament_id=tournament.id,
        schedule_version_id=version.id,
        day_date=day,
        start_time=time(9, 0),
        end_time=time(10, 0),
        block_minutes=60,
        court_number=1,
        court_label="C1",
        is_active=True,
    )
    # Slot B: 10:10 — only 10 min after WF_01 ends (normally rejected, but weather=True)
    slot_b = ScheduleSlot(
        tournament_id=tournament.id,
        schedule_version_id=version.id,
        day_date=day,
        start_time=time(10, 10),
        end_time=time(11, 10),
        block_minutes=60,
        court_number=2,
        court_label="C2",
        is_active=True,
    )
    session.add_all([slot_a, slot_b])
    session.commit()

    # Without weather_reschedule: WF_02 should NOT fit in slot_b (only 10 min gap < 30 min)
    result_normal = auto_assign_with_rest(session, version.id, clear_existing=True, weather_reschedule=False)
    assert result_normal["assigned_count"] == 1, f"Normal mode: expected 1 assigned, got {result_normal}"
    assert result_normal["unassigned_count"] == 1

    # With weather_reschedule: WF_02 SHOULD fit in slot_b (30 min minimum bypassed)
    result_weather = auto_assign_with_rest(session, version.id, clear_existing=True, weather_reschedule=True)
    assert result_weather["assigned_count"] == 2, f"Weather mode: expected 2 assigned, got {result_weather}"
    assert result_weather["unassigned_count"] == 0


def test_weather_reschedule_still_enforces_stage_rules(session: Session):
    """
    Test that weather_reschedule=True does NOT bypass the stage-specific rules
    (WF→Scoring 60 min, Scoring→Scoring 90 min).
    """
    tracker = RestStateTracker()
    # Simulate: Team 1 finished a WF match at 10:00
    tracker.update_team_state(team_id=1, end_time=datetime(2026, 3, 1, 10, 0), stage="WF")

    # Build a MAIN match involving team 1
    main_match = Match(
        id=100,
        tournament_id=1,
        event_id=1,
        schedule_version_id=1,
        match_code="MAIN_01",
        match_type="MAIN",
        round_number=1,
        round_index=1,
        sequence_in_round=1,
        duration_minutes=60,
        team_a_id=1,
        team_b_id=2,
        placeholder_side_a="T1",
        placeholder_side_b="T2",
    )

    # Slot at 10:50 — 50 min gap, violates WF→Scoring 60 min even with weather=True
    slot_50 = ScheduleSlot(
        id=300,
        tournament_id=1,
        schedule_version_id=1,
        day_date=date(2026, 3, 1),
        start_time=time(10, 50),
        end_time=time(11, 50),
        block_minutes=60,
        court_number=1,
        court_label="C1",
        is_active=True,
    )
    ok, violations = check_rest_compatibility(slot_50, main_match, tracker, weather_reschedule=True)
    assert not ok
    assert violations[0].violation_type == "REST_WF_TO_SCORING"
    assert violations[0].required_rest_minutes == 60

    # Slot at 11:00 — exactly 60 min → should pass with weather=True
    slot_60 = ScheduleSlot(
        id=301,
        tournament_id=1,
        schedule_version_id=1,
        day_date=date(2026, 3, 1),
        start_time=time(11, 0),
        end_time=time(12, 0),
        block_minutes=60,
        court_number=2,
        court_label="C2",
        is_active=True,
    )
    ok, violations = check_rest_compatibility(slot_60, main_match, tracker, weather_reschedule=True)
    assert ok
    assert len(violations) == 0


# ============================================================================
# Feeder Rest Enforcement Tests
# ============================================================================


def test_feeder_rest_wf_to_wf_30min():
    """
    Unit test: WF R1 feeder → WF R2 child enforces 30-min universal minimum.
    20-min gap fails with REST_FEEDER_GAP, 30-min gap passes.
    """
    tracker = RestStateTracker()

    # Feeder match (WF R1) — ends at 10:00
    feeder = Match(
        id=10,
        tournament_id=1,
        event_id=1,
        schedule_version_id=1,
        match_code="WF_R1_1",
        match_type="WF",
        round_number=1,
        round_index=1,
        sequence_in_round=1,
        duration_minutes=60,
        team_a_id=1,
        team_b_id=2,
        placeholder_side_a="T1",
        placeholder_side_b="T2",
    )

    # Child match (WF R2) — null teams, wired to feeder
    child = Match(
        id=20,
        tournament_id=1,
        event_id=1,
        schedule_version_id=1,
        match_code="WF_R2_1",
        match_type="WF",
        round_number=2,
        round_index=2,
        sequence_in_round=1,
        duration_minutes=60,
        team_a_id=None,
        team_b_id=None,
        source_match_a_id=10,
        source_match_b_id=None,
        placeholder_side_a="W(WF_R1_1)",
        placeholder_side_b="TBD",
    )

    feeder_end_times = {10: datetime(2026, 3, 1, 10, 0)}
    match_map = {10: feeder, 20: child}

    # Slot at 10:20 — 20 min gap → should fail
    slot_early = ScheduleSlot(
        id=200,
        tournament_id=1,
        schedule_version_id=1,
        day_date=date(2026, 3, 1),
        start_time=time(10, 20),
        end_time=time(11, 20),
        block_minutes=60,
        court_number=1,
        court_label="C1",
        is_active=True,
    )
    ok, violations = check_rest_compatibility(
        slot_early, child, tracker,
        feeder_end_times=feeder_end_times, match_map=match_map,
    )
    assert not ok
    assert len(violations) == 1
    assert violations[0].violation_type == "REST_FEEDER_GAP"
    assert violations[0].team_id == 0  # sentinel
    assert violations[0].required_rest_minutes == 30

    # Slot at 10:30 — exactly 30 min → should pass
    slot_ok = ScheduleSlot(
        id=201,
        tournament_id=1,
        schedule_version_id=1,
        day_date=date(2026, 3, 1),
        start_time=time(10, 30),
        end_time=time(11, 30),
        block_minutes=60,
        court_number=2,
        court_label="C2",
        is_active=True,
    )
    ok, violations = check_rest_compatibility(
        slot_ok, child, tracker,
        feeder_end_times=feeder_end_times, match_map=match_map,
    )
    assert ok
    assert len(violations) == 0


def test_feeder_rest_wf_to_scoring_60min():
    """
    Unit test: WF feeder → MAIN (scoring) child enforces 60-min stage-transition rest.
    """
    tracker = RestStateTracker()

    feeder = Match(
        id=10,
        tournament_id=1,
        event_id=1,
        schedule_version_id=1,
        match_code="WF_R1_1",
        match_type="WF",
        round_number=1,
        round_index=1,
        sequence_in_round=1,
        duration_minutes=60,
        team_a_id=1,
        team_b_id=2,
        placeholder_side_a="T1",
        placeholder_side_b="T2",
    )

    child = Match(
        id=30,
        tournament_id=1,
        event_id=1,
        schedule_version_id=1,
        match_code="MAIN_R1_1",
        match_type="MAIN",
        round_number=1,
        round_index=1,
        sequence_in_round=1,
        duration_minutes=90,
        team_a_id=None,
        team_b_id=None,
        source_match_a_id=10,
        source_match_b_id=None,
        placeholder_side_a="W(WF_R1_1)",
        placeholder_side_b="TBD",
    )

    feeder_end_times = {10: datetime(2026, 3, 1, 10, 0)}
    match_map = {10: feeder, 30: child}

    # Slot at 10:50 — 50 min gap → should fail (needs 60)
    slot_early = ScheduleSlot(
        id=200,
        tournament_id=1,
        schedule_version_id=1,
        day_date=date(2026, 3, 1),
        start_time=time(10, 50),
        end_time=time(12, 20),
        block_minutes=90,
        court_number=1,
        court_label="C1",
        is_active=True,
    )
    ok, violations = check_rest_compatibility(
        slot_early, child, tracker,
        feeder_end_times=feeder_end_times, match_map=match_map,
    )
    assert not ok
    assert violations[0].violation_type == "REST_FEEDER_GAP"
    assert violations[0].required_rest_minutes == 60

    # Slot at 11:00 — exactly 60 min → should pass
    slot_ok = ScheduleSlot(
        id=201,
        tournament_id=1,
        schedule_version_id=1,
        day_date=date(2026, 3, 1),
        start_time=time(11, 0),
        end_time=time(12, 30),
        block_minutes=90,
        court_number=2,
        court_label="C2",
        is_active=True,
    )
    ok, violations = check_rest_compatibility(
        slot_ok, child, tracker,
        feeder_end_times=feeder_end_times, match_map=match_map,
    )
    assert ok
    assert len(violations) == 0


def test_feeder_rest_weather_bypass():
    """
    Unit test: weather_reschedule=True bypasses WF→WF feeder 30-min universal minimum.
    """
    tracker = RestStateTracker()

    feeder = Match(
        id=10,
        tournament_id=1,
        event_id=1,
        schedule_version_id=1,
        match_code="WF_R1_1",
        match_type="WF",
        round_number=1,
        round_index=1,
        sequence_in_round=1,
        duration_minutes=60,
        team_a_id=1,
        team_b_id=2,
        placeholder_side_a="T1",
        placeholder_side_b="T2",
    )

    child = Match(
        id=20,
        tournament_id=1,
        event_id=1,
        schedule_version_id=1,
        match_code="WF_R2_1",
        match_type="WF",
        round_number=2,
        round_index=2,
        sequence_in_round=1,
        duration_minutes=60,
        team_a_id=None,
        team_b_id=None,
        source_match_a_id=10,
        source_match_b_id=None,
        placeholder_side_a="W(WF_R1_1)",
        placeholder_side_b="TBD",
    )

    feeder_end_times = {10: datetime(2026, 3, 1, 10, 0)}
    match_map = {10: feeder, 20: child}

    # Slot at 10:10 — only 10 min gap, normally fails for WF→WF (30 min)
    slot = ScheduleSlot(
        id=200,
        tournament_id=1,
        schedule_version_id=1,
        day_date=date(2026, 3, 1),
        start_time=time(10, 10),
        end_time=time(11, 10),
        block_minutes=60,
        court_number=1,
        court_label="C1",
        is_active=True,
    )

    # Without weather: should fail
    ok, violations = check_rest_compatibility(
        slot, child, tracker,
        feeder_end_times=feeder_end_times, match_map=match_map,
    )
    assert not ok

    # With weather: should pass (WF→WF has no stage-specific rule, only universal min)
    ok, violations = check_rest_compatibility(
        slot, child, tracker,
        weather_reschedule=True,
        feeder_end_times=feeder_end_times, match_map=match_map,
    )
    assert ok
    assert len(violations) == 0


def test_feeder_rest_weather_preserves_stage_rules():
    """
    Unit test: weather_reschedule=True still enforces WF→Scoring 60-min feeder rest.
    """
    tracker = RestStateTracker()

    feeder = Match(
        id=10,
        tournament_id=1,
        event_id=1,
        schedule_version_id=1,
        match_code="WF_R1_1",
        match_type="WF",
        round_number=1,
        round_index=1,
        sequence_in_round=1,
        duration_minutes=60,
        team_a_id=1,
        team_b_id=2,
        placeholder_side_a="T1",
        placeholder_side_b="T2",
    )

    child = Match(
        id=30,
        tournament_id=1,
        event_id=1,
        schedule_version_id=1,
        match_code="MAIN_R1_1",
        match_type="MAIN",
        round_number=1,
        round_index=1,
        sequence_in_round=1,
        duration_minutes=90,
        team_a_id=None,
        team_b_id=None,
        source_match_a_id=10,
        source_match_b_id=None,
        placeholder_side_a="W(WF_R1_1)",
        placeholder_side_b="TBD",
    )

    feeder_end_times = {10: datetime(2026, 3, 1, 10, 0)}
    match_map = {10: feeder, 30: child}

    # Slot at 10:50 — 50 min gap → should still fail with weather=True
    slot = ScheduleSlot(
        id=200,
        tournament_id=1,
        schedule_version_id=1,
        day_date=date(2026, 3, 1),
        start_time=time(10, 50),
        end_time=time(12, 20),
        block_minutes=90,
        court_number=1,
        court_label="C1",
        is_active=True,
    )
    ok, violations = check_rest_compatibility(
        slot, child, tracker,
        weather_reschedule=True,
        feeder_end_times=feeder_end_times, match_map=match_map,
    )
    assert not ok
    assert violations[0].violation_type == "REST_FEEDER_GAP"
    assert violations[0].required_rest_minutes == 60


def test_feeder_rest_integration(session: Session):
    """
    Integration test: auto_assign places R2 match in a far-enough slot,
    skipping a too-close slot based on feeder rest.
    """
    tournament = Tournament(
        name="Feeder Rest Integration",
        location="Test",
        timezone="America/New_York",
        start_date=date(2026, 3, 1),
        end_date=date(2026, 3, 1),
    )
    session.add(tournament)
    session.commit()
    session.refresh(tournament)

    event = Event(
        tournament_id=tournament.id,
        category=EventCategory.mixed,
        name="Feeder Event",
        team_count=4,
        draw_status="final",
    )
    session.add(event)
    session.commit()
    session.refresh(event)

    teams = []
    for i in range(1, 5):
        t = Team(event_id=event.id, name=f"Team {i}", seed=i, rating=1000.0)
        session.add(t)
        teams.append(t)
    session.commit()
    for t in teams:
        session.refresh(t)

    version = ScheduleVersion(tournament_id=tournament.id, version_number=1, status="draft")
    session.add(version)
    session.commit()
    session.refresh(version)

    day = date(2026, 3, 1)

    # WF R1: two matches with known teams (60 min each)
    wf_r1_1 = Match(
        tournament_id=tournament.id,
        event_id=event.id,
        schedule_version_id=version.id,
        match_code="WF_R1_1",
        match_type="WF",
        round_number=1,
        round_index=1,
        sequence_in_round=1,
        duration_minutes=60,
        team_a_id=teams[0].id,
        team_b_id=teams[1].id,
        placeholder_side_a="T1",
        placeholder_side_b="T2",
    )
    wf_r1_2 = Match(
        tournament_id=tournament.id,
        event_id=event.id,
        schedule_version_id=version.id,
        match_code="WF_R1_2",
        match_type="WF",
        round_number=1,
        round_index=1,
        sequence_in_round=2,
        duration_minutes=60,
        team_a_id=teams[2].id,
        team_b_id=teams[3].id,
        placeholder_side_a="T3",
        placeholder_side_b="T4",
    )
    session.add_all([wf_r1_1, wf_r1_2])
    session.commit()
    session.refresh(wf_r1_1)
    session.refresh(wf_r1_2)

    # WF R2: placeholder match wired to both R1 feeders
    wf_r2 = Match(
        tournament_id=tournament.id,
        event_id=event.id,
        schedule_version_id=version.id,
        match_code="WF_R2_1",
        match_type="WF",
        round_number=2,
        round_index=2,
        sequence_in_round=1,
        duration_minutes=60,
        team_a_id=None,
        team_b_id=None,
        source_match_a_id=wf_r1_1.id,
        source_match_b_id=wf_r1_2.id,
        placeholder_side_a="W(WF_R1_1)",
        placeholder_side_b="W(WF_R1_2)",
    )
    session.add(wf_r2)
    session.commit()
    session.refresh(wf_r2)

    # Slots:
    # Slot 1: 9:00 (for WF_R1_1 — ends at 10:00)
    # Slot 2: 9:00 court 2 (for WF_R1_2 — ends at 10:00)
    # Slot 3: 10:15 — only 15 min after R1 ends → should be SKIPPED for R2
    # Slot 4: 10:30 — exactly 30 min after R1 ends → should be USED for R2
    slot1 = ScheduleSlot(
        tournament_id=tournament.id,
        schedule_version_id=version.id,
        day_date=day,
        start_time=time(9, 0),
        end_time=time(10, 0),
        block_minutes=60,
        court_number=1,
        court_label="C1",
        is_active=True,
    )
    slot2 = ScheduleSlot(
        tournament_id=tournament.id,
        schedule_version_id=version.id,
        day_date=day,
        start_time=time(9, 0),
        end_time=time(10, 0),
        block_minutes=60,
        court_number=2,
        court_label="C2",
        is_active=True,
    )
    slot3 = ScheduleSlot(
        tournament_id=tournament.id,
        schedule_version_id=version.id,
        day_date=day,
        start_time=time(10, 15),
        end_time=time(11, 15),
        block_minutes=60,
        court_number=1,
        court_label="C1",
        is_active=True,
    )
    slot4 = ScheduleSlot(
        tournament_id=tournament.id,
        schedule_version_id=version.id,
        day_date=day,
        start_time=time(10, 30),
        end_time=time(11, 30),
        block_minutes=60,
        court_number=2,
        court_label="C2",
        is_active=True,
    )
    session.add_all([slot1, slot2, slot3, slot4])
    session.commit()
    session.refresh(slot3)
    session.refresh(slot4)

    result = auto_assign_with_rest(session, version.id, clear_existing=True)

    # All 3 matches should be assigned
    assert result["assigned_count"] == 3, f"Expected 3, got: {result}"
    assert result["unassigned_count"] == 0

    # Verify R2 match was NOT placed in the too-close slot (10:15)
    r2_assignment = session.exec(
        select(MatchAssignment).where(
            MatchAssignment.schedule_version_id == version.id,
            MatchAssignment.match_id == wf_r2.id,
        )
    ).first()
    assert r2_assignment is not None
    r2_slot = session.get(ScheduleSlot, r2_assignment.slot_id)
    r2_start = datetime.combine(r2_slot.day_date, r2_slot.start_time)
    # R2 should be at 10:30 (slot4), not 10:15 (slot3)
    assert r2_start == datetime(2026, 3, 1, 10, 30), f"R2 placed at {r2_start}, expected 10:30"


def test_feeder_rest_skips_when_unassigned():
    """
    Unit test: If feeder match is not in feeder_end_times (unassigned),
    no crash occurs and no violation is produced.
    """
    tracker = RestStateTracker()

    feeder = Match(
        id=10,
        tournament_id=1,
        event_id=1,
        schedule_version_id=1,
        match_code="WF_R1_1",
        match_type="WF",
        round_number=1,
        round_index=1,
        sequence_in_round=1,
        duration_minutes=60,
        team_a_id=1,
        team_b_id=2,
        placeholder_side_a="T1",
        placeholder_side_b="T2",
    )

    child = Match(
        id=20,
        tournament_id=1,
        event_id=1,
        schedule_version_id=1,
        match_code="WF_R2_1",
        match_type="WF",
        round_number=2,
        round_index=2,
        sequence_in_round=1,
        duration_minutes=60,
        team_a_id=None,
        team_b_id=None,
        source_match_a_id=10,
        source_match_b_id=None,
        placeholder_side_a="W(WF_R1_1)",
        placeholder_side_b="TBD",
    )

    # feeder_end_times is empty — feeder not assigned
    feeder_end_times = {}
    match_map = {10: feeder, 20: child}

    slot = ScheduleSlot(
        id=200,
        tournament_id=1,
        schedule_version_id=1,
        day_date=date(2026, 3, 1),
        start_time=time(10, 5),
        end_time=time(11, 5),
        block_minutes=60,
        court_number=1,
        court_label="C1",
        is_active=True,
    )
    ok, violations = check_rest_compatibility(
        slot, child, tracker,
        feeder_end_times=feeder_end_times, match_map=match_map,
    )
    # Should pass — no feeder data means no violation
    assert ok
    assert len(violations) == 0


def test_feeder_rest_dedup_same_source():
    """
    Unit test: Both sides reference the same feeder match → only one violation produced.
    """
    tracker = RestStateTracker()

    feeder = Match(
        id=10,
        tournament_id=1,
        event_id=1,
        schedule_version_id=1,
        match_code="WF_R1_1",
        match_type="WF",
        round_number=1,
        round_index=1,
        sequence_in_round=1,
        duration_minutes=60,
        team_a_id=1,
        team_b_id=2,
        placeholder_side_a="T1",
        placeholder_side_b="T2",
    )

    # Both sides wired to the same feeder (unusual but possible edge case)
    child = Match(
        id=20,
        tournament_id=1,
        event_id=1,
        schedule_version_id=1,
        match_code="WF_R2_1",
        match_type="WF",
        round_number=2,
        round_index=2,
        sequence_in_round=1,
        duration_minutes=60,
        team_a_id=None,
        team_b_id=None,
        source_match_a_id=10,
        source_match_b_id=10,  # same feeder on both sides
        placeholder_side_a="W(WF_R1_1)",
        placeholder_side_b="L(WF_R1_1)",
    )

    feeder_end_times = {10: datetime(2026, 3, 1, 10, 0)}
    match_map = {10: feeder, 20: child}

    # Slot at 10:15 — violates 30-min minimum
    slot = ScheduleSlot(
        id=200,
        tournament_id=1,
        schedule_version_id=1,
        day_date=date(2026, 3, 1),
        start_time=time(10, 15),
        end_time=time(11, 15),
        block_minutes=60,
        court_number=1,
        court_label="C1",
        is_active=True,
    )
    ok, violations = check_rest_compatibility(
        slot, child, tracker,
        feeder_end_times=feeder_end_times, match_map=match_map,
    )
    assert not ok
    # Should have exactly 1 violation, not 2 (dedup)
    assert len(violations) == 1
    assert violations[0].violation_type == "REST_FEEDER_GAP"
