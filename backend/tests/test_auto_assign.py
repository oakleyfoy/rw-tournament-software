"""
Tests for Auto-Assign V1

Verifies deterministic behavior and correctness of the auto-assign algorithm.
"""

from datetime import date, time

import pytest
from sqlmodel import Session, SQLModel, create_engine, select
from sqlmodel.pool import StaticPool

from app.models.match import Match
from app.models.match_assignment import MatchAssignment
from app.models.schedule_slot import ScheduleSlot
from app.models.schedule_version import ScheduleVersion
from app.models.tournament import Tournament
from app.utils.auto_assign import (
    STAGE_PRECEDENCE,
    AutoAssignValidationError,
    auto_assign_v1,
    get_match_sort_key,
    get_slot_sort_key,
)


@pytest.fixture(name="session")
def session_fixture():
    """Create a fresh in-memory database for each test"""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def test_stage_precedence_order():
    """Test that stage precedence is correctly defined"""
    assert STAGE_PRECEDENCE["WF"] < STAGE_PRECEDENCE["MAIN"]
    assert STAGE_PRECEDENCE["MAIN"] < STAGE_PRECEDENCE["CONSOLATION"]
    assert STAGE_PRECEDENCE["CONSOLATION"] < STAGE_PRECEDENCE["PLACEMENT"]


def test_match_sort_key_ordering():
    """Test that match sort keys produce correct ordering"""
    # Create mock matches with different stages
    wf_match = Match(
        id=1,
        tournament_id=1,
        event_id=1,
        schedule_version_id=1,
        match_code="WF1",
        match_type="WF",
        round_number=1,
        round_index=1,
        sequence_in_round=1,
        duration_minutes=60,
        placeholder_side_a="TBD",
        placeholder_side_b="TBD",
    )

    main_match = Match(
        id=2,
        tournament_id=1,
        event_id=1,
        schedule_version_id=1,
        match_code="QF1",
        match_type="MAIN",
        round_number=1,
        round_index=1,
        sequence_in_round=1,
        duration_minutes=120,
        placeholder_side_a="TBD",
        placeholder_side_b="TBD",
    )

    cons_match = Match(
        id=3,
        tournament_id=1,
        event_id=1,
        schedule_version_id=1,
        match_code="CONS1",
        match_type="CONSOLATION",
        round_number=1,
        round_index=1,
        sequence_in_round=1,
        duration_minutes=120,
        consolation_tier=1,
        placeholder_side_a="TBD",
        placeholder_side_b="TBD",
    )

    placement_match = Match(
        id=4,
        tournament_id=1,
        event_id=1,
        schedule_version_id=1,
        match_code="PL1",
        match_type="PLACEMENT",
        round_number=1,
        round_index=1,
        sequence_in_round=1,
        duration_minutes=120,
        placement_type="MAIN_SF_LOSERS",
        placeholder_side_a="TBD",
        placeholder_side_b="TBD",
    )

    # Sort by key
    matches = [placement_match, cons_match, main_match, wf_match]
    sorted_matches = sorted(matches, key=get_match_sort_key)

    # Verify order: WF → MAIN → CONSOLATION → PLACEMENT
    assert sorted_matches[0].match_type == "WF"
    assert sorted_matches[1].match_type == "MAIN"
    assert sorted_matches[2].match_type == "CONSOLATION"
    assert sorted_matches[3].match_type == "PLACEMENT"


def test_slot_sort_key_ordering():
    """Test that slot sort keys produce chronological ordering"""
    # Create mock slots
    slot1 = ScheduleSlot(
        id=1,
        schedule_version_id=1,
        day_date=date(2024, 1, 1),
        start_time=time(9, 0),
        block_minutes=120,
        court_label="Court 1",
    )

    slot2 = ScheduleSlot(
        id=2,
        schedule_version_id=1,
        day_date=date(2024, 1, 1),
        start_time=time(9, 0),
        block_minutes=120,
        court_label="Court 2",
    )

    slot3 = ScheduleSlot(
        id=3,
        schedule_version_id=1,
        day_date=date(2024, 1, 1),
        start_time=time(11, 0),
        block_minutes=120,
        court_label="Court 1",
    )

    slot4 = ScheduleSlot(
        id=4,
        schedule_version_id=1,
        day_date=date(2024, 1, 2),
        start_time=time(9, 0),
        block_minutes=120,
        court_label="Court 1",
    )

    # Sort by key
    slots = [slot4, slot2, slot3, slot1]
    sorted_slots = sorted(slots, key=get_slot_sort_key)

    # Verify chronological order: day → time → court
    assert sorted_slots[0].id == 1  # Day 1, 9:00, Court 1
    assert sorted_slots[1].id == 2  # Day 1, 9:00, Court 2
    assert sorted_slots[2].id == 3  # Day 1, 11:00, Court 1
    assert sorted_slots[3].id == 4  # Day 2, 9:00, Court 1


def test_auto_assign_determinism(session: Session):
    """
    Test that auto-assign produces identical results when run twice.
    This is the critical acceptance criterion.
    """
    # Create tournament and version
    tournament = Tournament(
        name="Test Tournament",
        location="Test Location",
        timezone="America/New_York",
        start_date=date(2024, 1, 1),
        end_date=date(2024, 1, 2),
    )
    session.add(tournament)
    session.commit()
    session.refresh(tournament)

    version = ScheduleVersion(tournament_id=tournament.id, version_number=1, status="draft")
    session.add(version)
    session.commit()
    session.refresh(version)

    # Create matches (WF, MAIN, CONSOLATION)
    matches = [
        Match(
            tournament_id=tournament.id,
            event_id=1,
            schedule_version_id=version.id,
            match_code="WF1",
            match_type="WF",
            round_number=1,
            round_index=1,
            sequence_in_round=1,
            duration_minutes=60,
            placeholder_side_a="TBD",
            placeholder_side_b="TBD",
        ),
        Match(
            tournament_id=tournament.id,
            event_id=1,
            schedule_version_id=version.id,
            match_code="QF1",
            match_type="MAIN",
            round_number=1,
            round_index=1,
            sequence_in_round=1,
            duration_minutes=120,
            placeholder_side_a="TBD",
            placeholder_side_b="TBD",
        ),
        Match(
            tournament_id=tournament.id,
            event_id=1,
            schedule_version_id=version.id,
            match_code="CONS1",
            match_type="CONSOLATION",
            round_number=1,
            round_index=1,
            sequence_in_round=1,
            duration_minutes=120,
            consolation_tier=1,
            placeholder_side_a="TBD",
            placeholder_side_b="TBD",
        ),
    ]

    for match in matches:
        session.add(match)
    session.commit()

    for match in matches:
        session.refresh(match)

    # Create slots
    slots = [
        ScheduleSlot(
            tournament_id=tournament.id,
            schedule_version_id=version.id,
            day_date=date(2024, 1, 1),
            start_time=time(9, 0),
            end_time=time(11, 0),
            court_number=1,
            court_label="Court 1",
            block_minutes=120,
        ),
        ScheduleSlot(
            tournament_id=tournament.id,
            schedule_version_id=version.id,
            day_date=date(2024, 1, 1),
            start_time=time(11, 0),
            end_time=time(13, 0),
            court_number=1,
            court_label="Court 1",
            block_minutes=120,
        ),
        ScheduleSlot(
            tournament_id=tournament.id,
            schedule_version_id=version.id,
            day_date=date(2024, 1, 1),
            start_time=time(13, 0),
            end_time=time(15, 0),
            court_number=1,
            court_label="Court 1",
            block_minutes=120,
        ),
    ]

    for slot in slots:
        session.add(slot)
    session.commit()

    for slot in slots:
        session.refresh(slot)

    # Run auto-assign first time
    result1 = auto_assign_v1(session, version.id, clear_existing=True)
    session.commit()

    # Capture assignments
    assignments1 = session.exec(
        select(MatchAssignment).where(MatchAssignment.schedule_version_id == version.id).order_by(MatchAssignment.id)
    ).all()

    assignment_map1 = {a.match_id: a.slot_id for a in assignments1}

    # Run auto-assign second time
    result2 = auto_assign_v1(session, version.id, clear_existing=True)
    session.commit()

    # Capture assignments again
    assignments2 = session.exec(
        select(MatchAssignment).where(MatchAssignment.schedule_version_id == version.id).order_by(MatchAssignment.id)
    ).all()

    assignment_map2 = {a.match_id: a.slot_id for a in assignments2}

    # Verify identical results
    assert result1.assigned_count == result2.assigned_count
    assert result1.unassigned_count == result2.unassigned_count
    assert assignment_map1 == assignment_map2

    # Verify all matches were assigned
    assert result1.assigned_count == 3
    assert result1.unassigned_count == 0


def test_auto_assign_respects_stage_ordering(session: Session):
    """Test that WF matches are assigned before MAIN matches"""
    # Create tournament and version
    tournament = Tournament(
        name="Test Tournament",
        location="Test Location",
        timezone="America/New_York",
        start_date=date(2024, 1, 1),
        end_date=date(2024, 1, 2),
    )
    session.add(tournament)
    session.commit()
    session.refresh(tournament)

    version = ScheduleVersion(tournament_id=tournament.id, version_number=1, status="draft")
    session.add(version)
    session.commit()
    session.refresh(version)

    # Create matches in reverse order (MAIN first, WF second)
    main_match = Match(
        tournament_id=tournament.id,
        event_id=1,
        schedule_version_id=version.id,
        match_code="MAIN1",
        match_type="MAIN",
        round_number=1,
        round_index=1,
        sequence_in_round=1,
        duration_minutes=120,
        placeholder_side_a="TBD",
        placeholder_side_b="TBD",
    )

    wf_match = Match(
        tournament_id=tournament.id,
        event_id=1,
        schedule_version_id=version.id,
        match_code="WF1",
        match_type="WF",
        round_number=1,
        round_index=1,
        sequence_in_round=1,
        duration_minutes=60,
        placeholder_side_a="TBD",
        placeholder_side_b="TBD",
    )

    session.add(main_match)
    session.add(wf_match)
    session.commit()
    session.refresh(main_match)
    session.refresh(wf_match)

    # Create only one slot (forces ordering test)
    slot = ScheduleSlot(
        tournament_id=tournament.id,
        schedule_version_id=version.id,
        day_date=date(2024, 1, 1),
        start_time=time(9, 0),
        end_time=time(11, 0),
        court_number=1,
        court_label="Court 1",
        block_minutes=120,
    )
    session.add(slot)
    session.commit()
    session.refresh(slot)

    # Run auto-assign
    result = auto_assign_v1(session, version.id, clear_existing=True)
    session.commit()

    # Verify WF match got the slot (not MAIN)
    assignment = session.exec(select(MatchAssignment).where(MatchAssignment.schedule_version_id == version.id)).first()

    assert assignment is not None
    assert assignment.match_id == wf_match.id
    assert result.assigned_count == 1
    assert result.unassigned_count == 1


def test_auto_assign_validation_errors(session: Session):
    """Test that validation errors are raised for invalid inputs"""
    # Create tournament and version
    tournament = Tournament(
        name="Test Tournament",
        location="Test Location",
        timezone="America/New_York",
        start_date=date(2024, 1, 1),
        end_date=date(2024, 1, 2),
    )
    session.add(tournament)
    session.commit()
    session.refresh(tournament)

    version = ScheduleVersion(tournament_id=tournament.id, version_number=1, status="draft")
    session.add(version)
    session.commit()
    session.refresh(version)

    # Test: Empty match list
    with pytest.raises(AutoAssignValidationError, match="Match list is empty"):
        auto_assign_v1(session, version.id, clear_existing=True)

    # Add a match with invalid stage
    bad_match = Match(
        tournament_id=tournament.id,
        event_id=1,
        schedule_version_id=version.id,
        match_code="BAD1",
        match_type="INVALID_STAGE",
        round_number=1,
        round_index=1,
        sequence_in_round=1,
        duration_minutes=120,
        placeholder_side_a="TBD",
        placeholder_side_b="TBD",
    )
    session.add(bad_match)
    session.commit()

    # Add a slot so we pass the "Slot list is empty" check
    slot = ScheduleSlot(
        tournament_id=tournament.id,
        schedule_version_id=version.id,
        day_date=date(2024, 1, 1),
        start_time=time(9, 0),
        end_time=time(11, 0),
        court_number=1,
        court_label="Court 1",
        block_minutes=120,
    )
    session.add(slot)
    session.commit()

    # Test: Invalid stage
    with pytest.raises(AutoAssignValidationError, match="invalid stage"):
        auto_assign_v1(session, version.id, clear_existing=True)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
