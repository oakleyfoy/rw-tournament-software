"""
Regression Tests for Manual Schedule Editor

These tests verify that manual assignment locking and validation work correctly:

1. Locked assignments are never moved by auto-assign
2. Manual moves enforce all hard invariants
3. Clone-before-edit semantics work
4. Manual and auto-assign coexist properly
"""

from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.models.match import Match
from app.models.match_assignment import MatchAssignment
from app.models.schedule_slot import ScheduleSlot
from app.models.schedule_version import ScheduleVersion


@pytest.fixture
def manual_editor_setup(client: TestClient, session: Session):
    """Create a tournament with schedule for manual editor testing"""
    from datetime import datetime, time
    from app.models.tournament import Tournament
    from app.models.event import Event
    
    # Create tournament directly in DB
    tournament = Tournament(
        name="Manual Editor Test Tournament",
        location="Test Location",
        timezone="America/New_York",
        start_date=date(2026, 1, 15),
        end_date=date(2026, 1, 17),
    )
    session.add(tournament)
    session.commit()
    session.refresh(tournament)
    
    # Create event directly in DB
    event = Event(
        tournament_id=tournament.id,
        category="mixed",
        name="Test Event",
        team_count=4,
        draw_plan_json='{"template_type":"ROUND_ROBIN"}',
        draw_status="final",
        guarantee_selected=2,
    )
    session.add(event)
    session.commit()
    session.refresh(event)
    
    # Create schedule version
    version = ScheduleVersion(
        tournament_id=tournament.id,
        version_number=1,
        notes="Test",
        status="draft",
    )
    session.add(version)
    session.commit()
    session.refresh(version)
    
    # Create slots manually
    for i in range(5):
        slot = ScheduleSlot(
            tournament_id=tournament.id,
            schedule_version_id=version.id,
            day_date=date(2026, 1, 15),
            start_time=time(9 + i, 0),
            end_time=time(10 + i, 0),
            block_minutes=60,
            court_number=i % 2 + 1,
            court_label=f"Court {i % 2 + 1}",
        )
        session.add(slot)
    
    # Create matches manually
    for i in range(3):
        match = Match(
            tournament_id=tournament.id,
            schedule_version_id=version.id,
            event_id=event.id,
            match_code=f"M{i+1}",
            match_type="MAIN",
            round_number=i + 1,
            round_index=i + 1,
            sequence_in_round=i + 1,
            duration_minutes=45,
            placeholder_side_a=f"Team A{i+1}",
            placeholder_side_b=f"Team B{i+1}",
            status="unscheduled",
        )
        session.add(match)
    
    session.commit()
    
    return {
        "tournament": {"id": tournament.id},
        "event": {"id": event.id},
        "version": {"id": version.id},
    }


# ============================================================================
# Test 1: Locked Assignments Are Never Moved by Auto-Assign
# ============================================================================


def test_locked_assignments_not_moved_by_autoassign(client: TestClient, session: Session, manual_editor_setup):
    """
    CRITICAL: Verify auto-assign V2 skips locked assignments.
    
    Workflow:
    1. Auto-assign some matches (creates unlocked assignments)
    2. Manually reassign one match (creates locked assignment)
    3. Run auto-assign again with clear_existing=True
    4. Verify locked assignment was NOT cleared/moved
    5. Verify unlocked assignments were cleared and reassigned
    """
    tournament_id = manual_editor_setup["tournament"]["id"]
    version_id = manual_editor_setup["version"]["id"]
    
    # Step 1: Run auto-assign V2 first time
    assign_resp = client.post(
        f"/api/tournaments/{tournament_id}/schedule/versions/{version_id}/auto-assign-rest",
        json={"schedule_version_id": version_id, "clear_existing": True},
        params={"v": 2},  # Use V2
    )
    assert assign_resp.status_code == 200
    
    # Get initial assignments
    grid_resp = client.get(
        f"/api/tournaments/{tournament_id}/schedule/grid",
        params={"schedule_version_id": version_id}
    )
    assert grid_resp.status_code == 200
    grid = grid_resp.json()
    
    initial_assignments = grid["assignments"]
    assert len(initial_assignments) > 0, "Should have some auto-assigned matches"
    
    # Step 2: Manually reassign one match (lock it)
    first_assignment = initial_assignments[0]
    
    # Find a different slot
    all_slots = grid["slots"]
    target_slot = None
    for slot in all_slots:
        if slot["slot_id"] != first_assignment["slot_id"]:
            # Check if slot is free
            occupied = any(a["slot_id"] == slot["slot_id"] for a in initial_assignments)
            if not occupied:
                target_slot = slot
                break
    
    assert target_slot is not None, "Should find an available slot"
    
    # Get assignment ID from database
    assignment_in_db = session.exec(
        select(MatchAssignment).where(
            MatchAssignment.match_id == first_assignment["match_id"],
            MatchAssignment.schedule_version_id == version_id
        )
    ).first()
    assert assignment_in_db is not None
    
    # Manually reassign
    manual_resp = client.patch(
        f"/api/tournaments/{tournament_id}/schedule/assignments/{assignment_in_db.id}",
        json={"new_slot_id": target_slot["slot_id"]}
    )
    assert manual_resp.status_code == 200
    manual_assignment = manual_resp.json()
    assert manual_assignment["locked"] is True
    assert manual_assignment["assigned_by"] == "MANUAL"
    
    # Step 3: Run auto-assign again with clear_existing=True
    assign_resp_2 = client.post(
        f"/api/tournaments/{tournament_id}/schedule/versions/{version_id}/auto-assign-rest",
        json={"schedule_version_id": version_id, "clear_existing": True},
        params={"v": 2},
    )
    assert assign_resp_2.status_code == 200
    
    # Step 4: Verify locked assignment was NOT moved
    session.expire_all()  # Refresh session to see changes from TestClient
    locked_assignment_after = session.get(MatchAssignment, assignment_in_db.id)
    assert locked_assignment_after is not None, "Locked assignment should still exist"
    assert locked_assignment_after.slot_id == target_slot["slot_id"], "Locked assignment should not have moved"
    assert locked_assignment_after.locked is True, "Assignment should still be locked"
    
    # Step 5: Verify other assignments were cleared and reassigned
    all_assignments_after = session.exec(
        select(MatchAssignment).where(MatchAssignment.schedule_version_id == version_id)
    ).all()
    
    # Should have at least the locked one plus any that auto-assign reassigned
    assert len(all_assignments_after) >= 1
    
    # Count how many are locked vs unlocked
    locked_count = sum(1 for a in all_assignments_after if a.locked)
    unlocked_count = sum(1 for a in all_assignments_after if not a.locked)
    
    assert locked_count == 1, "Should have exactly 1 locked assignment"
    # Unlocked should be from V2 (not the original locked one)
    for assignment in all_assignments_after:
        if assignment.locked:
            assert assignment.assigned_by == "MANUAL"
        else:
            assert assignment.assigned_by == "AUTO_ASSIGN_V2"


# ============================================================================
# Test 2: Manual Move Fails If It Violates Invariants
# ============================================================================


def test_manual_move_enforces_duration_fit(client: TestClient, session: Session, manual_editor_setup):
    """
    Verify manual moves are rejected if match duration > slot duration.
    """
    tournament_id = manual_editor_setup["tournament"]["id"]
    version_id = manual_editor_setup["version"]["id"]
    
    # Get a match and slot
    match = session.exec(select(Match).where(Match.schedule_version_id == version_id)).first()
    slot = session.exec(select(ScheduleSlot).where(ScheduleSlot.schedule_version_id == version_id)).first()
    
    assert match is not None
    assert slot is not None
    
    # Artificially make match duration exceed slot duration
    original_duration = match.duration_minutes
    match.duration_minutes = (slot.block_minutes or 60) + 10  # Too long
    session.add(match)
    session.commit()
    
    # Create assignment first
    assignment = MatchAssignment(
        schedule_version_id=version_id,
        match_id=match.id,
        slot_id=slot.id,
        assigned_by="TEST",
        locked=False,
    )
    session.add(assignment)
    session.commit()
    session.refresh(assignment)
    
    # Try to manually move to same slot (should fail due to duration)
    manual_resp = client.patch(
        f"/api/tournaments/{tournament_id}/schedule/assignments/{assignment.id}",
        json={"new_slot_id": slot.id}
    )
    
    # Clean up
    match.duration_minutes = original_duration
    session.add(match)
    session.commit()
    
    # Should fail validation
    assert manual_resp.status_code == 422
    assert "duration" in manual_resp.text.lower()


def test_manual_move_enforces_slot_availability(client: TestClient, session: Session, manual_editor_setup):
    """
    Verify manual moves are rejected if target slot is already occupied.
    """
    tournament_id = manual_editor_setup["tournament"]["id"]
    version_id = manual_editor_setup["version"]["id"]
    
    # Get two matches and one slot
    matches = session.exec(select(Match).where(Match.schedule_version_id == version_id).limit(2)).all()
    slot = session.exec(select(ScheduleSlot).where(ScheduleSlot.schedule_version_id == version_id)).first()
    
    assert len(matches) >= 2
    assert slot is not None
    
    match1, match2 = matches[0], matches[1]
    
    # Assign match1 to slot
    assignment1 = MatchAssignment(
        schedule_version_id=version_id,
        match_id=match1.id,
        slot_id=slot.id,
        assigned_by="TEST",
    )
    session.add(assignment1)
    
    # Assign match2 to a different slot (find another)
    other_slot = session.exec(
        select(ScheduleSlot).where(
            ScheduleSlot.schedule_version_id == version_id,
            ScheduleSlot.id != slot.id
        )
    ).first()
    
    assignment2 = MatchAssignment(
        schedule_version_id=version_id,
        match_id=match2.id,
        slot_id=other_slot.id,
        assigned_by="TEST",
    )
    session.add(assignment2)
    session.commit()
    session.refresh(assignment2)
    
    # Try to move match2 to slot (where match1 already is)
    manual_resp = client.patch(
        f"/api/tournaments/{tournament_id}/schedule/assignments/{assignment2.id}",
        json={"new_slot_id": slot.id}
    )
    
    # Should fail - slot occupied
    assert manual_resp.status_code == 422
    assert "already assigned" in manual_resp.text.lower() or "occupied" in manual_resp.text.lower()


def test_manual_move_fails_on_finalized_version(client: TestClient, session: Session, manual_editor_setup):
    """
    Verify manual moves are rejected on finalized schedules.
    
    Admins must clone to draft first.
    """
    tournament_id = manual_editor_setup["tournament"]["id"]
    version_id = manual_editor_setup["version"]["id"]
    
    # Create and finalize a schedule
    match = session.exec(select(Match).where(Match.schedule_version_id == version_id)).first()
    slot = session.exec(select(ScheduleSlot).where(ScheduleSlot.schedule_version_id == version_id)).first()
    
    assignment = MatchAssignment(
        schedule_version_id=version_id,
        match_id=match.id,
        slot_id=slot.id,
        assigned_by="TEST",
    )
    session.add(assignment)
    session.commit()
    session.refresh(assignment)
    
    # Finalize the version
    finalize_resp = client.post(
        f"/api/tournaments/{tournament_id}/schedule/versions/{version_id}/finalize"
    )
    assert finalize_resp.status_code == 200
    
    # Try to manually reassign on finalized version
    other_slot = session.exec(
        select(ScheduleSlot).where(
            ScheduleSlot.schedule_version_id == version_id,
            ScheduleSlot.id != slot.id
        )
    ).first()
    
    manual_resp = client.patch(
        f"/api/tournaments/{tournament_id}/schedule/assignments/{assignment.id}",
        json={"new_slot_id": other_slot.id}
    )
    
    # Should fail - version is finalized
    assert manual_resp.status_code == 422
    assert "finalized" in manual_resp.text.lower() or "draft" in manual_resp.text.lower()


# ============================================================================
# Test 3: Clone Restores Previous State Exactly
# ============================================================================


def test_clone_preserves_locked_assignments(client: TestClient, session: Session, manual_editor_setup):
    """
    Verify cloning a version preserves locked assignments exactly.
    
    This supports undo: clone before edit, revert by switching versions.
    """
    tournament_id = manual_editor_setup["tournament"]["id"]
    version_id = manual_editor_setup["version"]["id"]
    
    # Create some assignments with mixed locked status
    matches = session.exec(select(Match).where(Match.schedule_version_id == version_id).limit(3)).all()
    slots = session.exec(select(ScheduleSlot).where(ScheduleSlot.schedule_version_id == version_id).limit(3)).all()
    
    assignments_data = [
        {"match": matches[0], "slot": slots[0], "locked": True, "assigned_by": "MANUAL"},
        {"match": matches[1], "slot": slots[1], "locked": False, "assigned_by": "AUTO_ASSIGN_V2"},
        {"match": matches[2], "slot": slots[2], "locked": True, "assigned_by": "MANUAL"},
    ]
    
    for data in assignments_data:
        assignment = MatchAssignment(
            schedule_version_id=version_id,
            match_id=data["match"].id,
            slot_id=data["slot"].id,
            assigned_by=data["assigned_by"],
            locked=data["locked"],
        )
        session.add(assignment)
    session.commit()
    
    # PRE-CLONE ASSERTION: Verify locked status persisted correctly BEFORE finalize
    pre_finalize_assignments = session.exec(
        select(MatchAssignment).where(MatchAssignment.schedule_version_id == version_id)
    ).all()
    assert len(pre_finalize_assignments) == 3, "Should have 3 assignments before finalize"
    
    pre_locked_count = sum(1 for a in pre_finalize_assignments if a.locked)
    pre_manual_count = sum(1 for a in pre_finalize_assignments if a.assigned_by == "MANUAL")
    pre_auto_count = sum(1 for a in pre_finalize_assignments if a.assigned_by == "AUTO_ASSIGN_V2")
    
    assert pre_locked_count == 2, f"Expected 2 locked assignments before finalize, got {pre_locked_count}"
    assert pre_manual_count == 2, f"Expected 2 MANUAL assignments before finalize, got {pre_manual_count}"
    assert pre_auto_count == 1, f"Expected 1 AUTO_ASSIGN_V2 assignment before finalize, got {pre_auto_count}"
    
    # Finalize version
    finalize_resp = client.post(f"/api/tournaments/{tournament_id}/schedule/versions/{version_id}/finalize")
    assert finalize_resp.status_code == 200
    
    # Clone version
    clone_resp = client.post(f"/api/tournaments/{tournament_id}/schedule/versions/{version_id}/clone")
    assert clone_resp.status_code == 201
    cloned_version = clone_resp.json()
    
    # Verify cloned assignments
    cloned_assignments = session.exec(
        select(MatchAssignment).where(MatchAssignment.schedule_version_id == cloned_version["id"])
    ).all()
    
    assert len(cloned_assignments) == 3, f"Expected 3 cloned assignments, got {len(cloned_assignments)}"
    
    # Check locked status preserved
    locked_count = sum(1 for a in cloned_assignments if a.locked)
    manual_count = sum(1 for a in cloned_assignments if a.assigned_by == "MANUAL")
    auto_count = sum(1 for a in cloned_assignments if a.assigned_by == "AUTO_ASSIGN_V2")
    
    assert locked_count == 2, f"Should preserve 2 locked assignments, got {locked_count}"
    assert manual_count == 2, f"Should preserve 2 MANUAL assignments, got {manual_count}"
    assert auto_count == 1, f"Should preserve 1 AUTO_ASSIGN_V2 assignment, got {auto_count}"
    
    # STRONGEST INVARIANT: Verify exact mapping preservation
    # Build mapping of (match_id, slot_id, locked, assigned_by) tuples
    # Match IDs will be different (cloned), but relative structure should match
    
    # Get slot and match ID mappings
    source_slots = session.exec(
        select(ScheduleSlot).where(ScheduleSlot.schedule_version_id == version_id)
    ).all()
    cloned_slots = session.exec(
        select(ScheduleSlot).where(ScheduleSlot.schedule_version_id == cloned_version["id"])
    ).all()
    
    source_matches = session.exec(
        select(Match).where(Match.schedule_version_id == version_id)
    ).all()
    cloned_matches = session.exec(
        select(Match).where(Match.schedule_version_id == cloned_version["id"])
    ).all()
    
    # Build mapping based on slot attributes (day_date, start_time, court_number)
    def slot_key(s):
        return (s.day_date, s.start_time, s.court_number)
    
    # Build mapping based on match attributes (match_code)
    def match_key(m):
        return m.match_code
    
    slot_id_map = {slot_key(s): s.id for s in source_slots}
    cloned_slot_id_map = {slot_key(s): s.id for s in cloned_slots}
    
    match_id_map = {match_key(m): m.id for m in source_matches}
    cloned_match_id_map = {match_key(m): m.id for m in cloned_matches}
    
    # Build assignment tuples with normalized keys
    source_assignment_tuples = []
    for a in pre_finalize_assignments:
        # Find slot and match
        source_slot = next((s for s in source_slots if s.id == a.slot_id), None)
        source_match = next((m for m in source_matches if m.id == a.match_id), None)
        if source_slot and source_match:
            source_assignment_tuples.append((
                match_key(source_match),
                slot_key(source_slot),
                a.locked,
                a.assigned_by
            ))
    
    cloned_assignment_tuples = []
    for a in cloned_assignments:
        # Find slot and match
        cloned_slot = next((s for s in cloned_slots if s.id == a.slot_id), None)
        cloned_match = next((m for m in cloned_matches if m.id == a.match_id), None)
        if cloned_slot and cloned_match:
            cloned_assignment_tuples.append((
                match_key(cloned_match),
                slot_key(cloned_slot),
                a.locked,
                a.assigned_by
            ))
    
    # Sort both for comparison
    source_sorted = sorted(source_assignment_tuples)
    cloned_sorted = sorted(cloned_assignment_tuples)
    
    assert source_sorted == cloned_sorted, (
        f"Assignment structure not preserved exactly.\n"
        f"Source: {source_sorted}\n"
        f"Cloned: {cloned_sorted}"
    )


# ============================================================================
# Test 4: Successful Manual Move
# ============================================================================


def test_successful_manual_reassignment(client: TestClient, session: Session, manual_editor_setup):
    """
    Verify a valid manual reassignment works correctly.
    
    Creates locked=True assignment with assigned_by="MANUAL".
    """
    tournament_id = manual_editor_setup["tournament"]["id"]
    version_id = manual_editor_setup["version"]["id"]
    
    # Get match and two slots
    match = session.exec(select(Match).where(Match.schedule_version_id == version_id)).first()
    slots = session.exec(select(ScheduleSlot).where(ScheduleSlot.schedule_version_id == version_id).limit(2)).all()
    
    assert len(slots) >= 2
    slot1, slot2 = slots[0], slots[1]
    
    # Create initial assignment
    assignment = MatchAssignment(
        schedule_version_id=version_id,
        match_id=match.id,
        slot_id=slot1.id,
        assigned_by="AUTO_ASSIGN_V2",
        locked=False,
    )
    session.add(assignment)
    session.commit()
    session.refresh(assignment)
    
    # Manually reassign to slot2
    manual_resp = client.patch(
        f"/api/tournaments/{tournament_id}/schedule/assignments/{assignment.id}",
        json={"new_slot_id": slot2.id}
    )
    
    assert manual_resp.status_code == 200
    response_data = manual_resp.json()
    
    # Verify response
    assert response_data["assignment_id"] == assignment.id
    assert response_data["match_id"] == match.id
    assert response_data["slot_id"] == slot2.id
    assert response_data["locked"] is True
    assert response_data["assigned_by"] == "MANUAL"
    assert response_data["validation_passed"] is True
    
    # Verify database - expire session to see changes from TestClient
    session.expire_all()
    updated_assignment = session.get(MatchAssignment, assignment.id)
    assert updated_assignment.slot_id == slot2.id
    assert updated_assignment.locked is True
    assert updated_assignment.assigned_by == "MANUAL"


# ============================================================================
# Phase 3D.1 Tests: Enriched PATCH Response + Rest Constraints
# ============================================================================


def test_manual_reassignment_returns_enriched_response(client: TestClient, session: Session, manual_editor_setup):
    """
    Phase 3D.1 Task D(1): Verify PATCH returns slot_key + conflicts_summary + unassigned_matches.
    
    This ensures UI can refresh with zero additional API calls.
    """
    tournament_id = manual_editor_setup["tournament"]["id"]
    version_id = manual_editor_setup["version"]["id"]
    
    # Create assignment
    match = session.exec(select(Match).where(Match.schedule_version_id == version_id)).first()
    slots = session.exec(select(ScheduleSlot).where(ScheduleSlot.schedule_version_id == version_id).limit(2)).all()
    
    assignment = MatchAssignment(
        schedule_version_id=version_id,
        match_id=match.id,
        slot_id=slots[0].id,
        assigned_by="AUTO",
    )
    session.add(assignment)
    session.commit()
    session.refresh(assignment)
    
    # Manually reassign
    resp = client.patch(
        f"/api/tournaments/{tournament_id}/schedule/assignments/{assignment.id}",
        json={"new_slot_id": slots[1].id}
    )
    
    assert resp.status_code == 200
    data = resp.json()
    
    # Verify slot_key exists (stable identifier, no UI lookups needed)
    assert "slot_key" in data
    assert "day_date" in data["slot_key"]
    assert "start_time" in data["slot_key"]
    assert "court_number" in data["slot_key"]
    assert "court_label" in data["slot_key"]
    assert data["slot_key"]["court_number"] == slots[1].court_number
    assert data["slot_key"]["court_label"] == slots[1].court_label
    
    # Verify conflicts_summary exists
    assert "conflicts_summary" in data
    assert "total_matches" in data["conflicts_summary"]
    assert "assigned_matches" in data["conflicts_summary"]
    assert "unassigned_matches" in data["conflicts_summary"]
    assert "assignment_rate" in data["conflicts_summary"]
    assert data["conflicts_summary"]["tournament_id"] == tournament_id
    assert data["conflicts_summary"]["schedule_version_id"] == version_id
    
    # Verify unassigned_matches exists (list with reasons)
    assert "unassigned_matches" in data
    assert isinstance(data["unassigned_matches"], list)
    # Should have 2 unassigned matches (we have 3 total, assigned 1)
    assert len(data["unassigned_matches"]) == 2
    for unassigned in data["unassigned_matches"]:
        assert "match_id" in unassigned
        assert "stage" in unassigned
        assert "round_index" in unassigned
        assert "duration_minutes" in unassigned
        assert "reason" in unassigned  # Should have reason (not just "UNKNOWN")


def test_conflicts_recompute_path_is_shared(client: TestClient, session: Session, manual_editor_setup):
    """
    Phase 3D.1 Task D(3): Verify PATCH and GET /conflicts share same computation.
    
    PATCH response conflicts_summary should match GET /conflicts exactly.
    """
    tournament_id = manual_editor_setup["tournament"]["id"]
    version_id = manual_editor_setup["version"]["id"]
    
    # Create assignment
    match = session.exec(select(Match).where(Match.schedule_version_id == version_id)).first()
    slots = session.exec(select(ScheduleSlot).where(ScheduleSlot.schedule_version_id == version_id).limit(2)).all()
    
    assignment = MatchAssignment(
        schedule_version_id=version_id,
        match_id=match.id,
        slot_id=slots[0].id,
        assigned_by="AUTO",
    )
    session.add(assignment)
    session.commit()
    session.refresh(assignment)
    
    # Get conflicts BEFORE manual move
    conflicts_before = client.get(
        f"/api/tournaments/{tournament_id}/schedule/conflicts",
        params={"schedule_version_id": version_id}
    )
    assert conflicts_before.status_code == 200
    conflicts_before_data = conflicts_before.json()
    
    # Manually reassign
    patch_resp = client.patch(
        f"/api/tournaments/{tournament_id}/schedule/assignments/{assignment.id}",
        json={"new_slot_id": slots[1].id}
    )
    assert patch_resp.status_code == 200
    patch_data = patch_resp.json()
    
    # Get conflicts AFTER manual move
    conflicts_after = client.get(
        f"/api/tournaments/{tournament_id}/schedule/conflicts",
        params={"schedule_version_id": version_id}
    )
    assert conflicts_after.status_code == 200
    conflicts_after_data = conflicts_after.json()
    
    # CRITICAL: PATCH response should match GET response (same computation helper)
    patch_summary = patch_data["conflicts_summary"]
    get_summary = conflicts_after_data["summary"]
    
    assert patch_summary["total_matches"] == get_summary["total_matches"]
    assert patch_summary["assigned_matches"] == get_summary["assigned_matches"]
    assert patch_summary["unassigned_matches"] == get_summary["unassigned_matches"]
    assert patch_summary["assignment_rate"] == get_summary["assignment_rate"]
    
    # Verify state changed from before to after (assignment counts should match)
    assert conflicts_before_data["summary"]["assigned_matches"] == 1
    assert conflicts_after_data["summary"]["assigned_matches"] == 1  # Still 1 (just moved)


def test_manual_move_enforces_rest_constraints(client: TestClient, session: Session, manual_editor_setup):
    """
    Phase 3D.1 Task D(2): Verify manual moves cannot violate rest constraints.
    
    Create two matches with same team, try to assign to slots < 90 minutes apart.
    Should fail with clear error and no mutation.
    """
    from datetime import date, time
    from app.models.team import Team
    from app.models.event import Event
    
    tournament_id = manual_editor_setup["tournament"]["id"]
    version_id = manual_editor_setup["version"]["id"]
    event_id = manual_editor_setup["event"]["id"]
    
    # Create a team
    team = Team(
        event_id=event_id,
        name="Test Team A",
        seed=1,
    )
    session.add(team)
    session.commit()
    session.refresh(team)
    
    # Get two matches and assign teams
    matches = session.exec(select(Match).where(Match.schedule_version_id == version_id).limit(2)).all()
    assert len(matches) >= 2
    
    match1, match2 = matches[0], matches[1]
    match1.team_a_id = team.id  # Same team in both matches
    match2.team_a_id = team.id
    session.add(match1)
    session.add(match2)
    session.commit()
    
    # Get existing slots to use for the test (avoid creating duplicates that violate unique constraint)
    existing_slots = session.exec(
        select(ScheduleSlot).where(ScheduleSlot.schedule_version_id == version_id).limit(2)
    ).all()
    
    if len(existing_slots) < 2:
        # Create two new slots that are < 90 minutes apart (violates rest)
        # Use different day to avoid conflicts with fixture slots
        slot1 = ScheduleSlot(
            tournament_id=tournament_id,
            schedule_version_id=version_id,
            day_date=date(2026, 1, 16),  # Different day
            start_time=time(9, 0),
            end_time=time(10, 0),
            block_minutes=60,
            court_number=1,
            court_label="Court 1",
        )
        slot2 = ScheduleSlot(
            tournament_id=tournament_id,
            schedule_version_id=version_id,
            day_date=date(2026, 1, 16),
            start_time=time(10, 0),  # Only 60 minutes after slot1 start (< 90 min rest)
            end_time=time(11, 0),
            block_minutes=60,
            court_number=2,
            court_label="Court 2",
        )
        session.add(slot1)
        session.add(slot2)
        session.commit()
        session.refresh(slot1)
        session.refresh(slot2)
    else:
        # Use existing slots from fixture (they're at 9:00 and 10:00 on Court 1 and 2)
        slot1 = existing_slots[0]
        slot2 = existing_slots[1]
    
    # Assign match1 to slot1 (locked)
    assignment1 = MatchAssignment(
        schedule_version_id=version_id,
        match_id=match1.id,
        slot_id=slot1.id,
        assigned_by="MANUAL",
        locked=True,
    )
    session.add(assignment1)
    session.commit()
    session.refresh(assignment1)
    
    # Create assignment2 for match2 to a different slot initially
    other_slots = session.exec(
        select(ScheduleSlot).where(
            ScheduleSlot.schedule_version_id == version_id,
            ScheduleSlot.id != slot1.id,
            ScheduleSlot.id != slot2.id,
        )
    ).first()
    
    assignment2 = MatchAssignment(
        schedule_version_id=version_id,
        match_id=match2.id,
        slot_id=other_slots.id if other_slots else slot2.id,
        assigned_by="AUTO",
    )
    session.add(assignment2)
    session.commit()
    session.refresh(assignment2)
    
    # Record state before failed move
    original_slot_id = assignment2.slot_id
    original_locked = assignment2.locked
    original_assigned_by = assignment2.assigned_by
    
    # Try to move match2 to slot2 (would violate rest constraint)
    resp = client.patch(
        f"/api/tournaments/{tournament_id}/schedule/assignments/{assignment2.id}",
        json={"new_slot_id": slot2.id}
    )
    
    # Should fail with 422 and clear rest violation message
    assert resp.status_code == 422
    assert "rest" in resp.text.lower() or "90" in resp.text or "minutes" in resp.text.lower()
    
    # Verify NO mutation occurred (non-mutating validation failure)
    session.expire_all()
    assignment2_after = session.get(MatchAssignment, assignment2.id)
    assert assignment2_after.slot_id == original_slot_id  # Unchanged
    assert assignment2_after.locked == original_locked  # Unchanged
    assert assignment2_after.assigned_by == original_assigned_by  # Unchanged

