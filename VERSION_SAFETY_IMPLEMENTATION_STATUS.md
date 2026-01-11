# Version Safety UX V1 — Implementation Progress Report

## ✅ COMPLETED WORK

### CHUNK 1: Database Migration ✅
**Migration**: `backend/alembic/versions/011_add_finalization_fields.py`  
**Status**: Applied successfully

**Fields Added**:
```python
finalized_at: Optional[datetime] = Field(default=None)
finalized_checksum: Optional[str] = Field(default=None, max_length=64)
```

---

### CHUNK 2a: Guard Utilities ✅
**File**: `backend/app/utils/version_guards.py`

```python
✅ require_draft_version()
✅ require_final_version()
✅ get_version_or_404()
```

---

### CHUNK 2b-3: Guards Applied ✅
**Applied to**:
1. ✅ `POST /tournaments/{tid}/schedule/versions/{vid}/build`
2. ✅ `POST /tournaments/{tid}/schedule/versions/{vid}/auto-assign-rest`
3. ✅ `inject_teams_v1()` function
4. ✅ `POST /tournaments/{tid}/schedule/slots/generate`

**Partially Applied** (existing checks present):
- `create_assignment()` - already has status check at line 1174
- Other endpoints have similar existing checks

---

## ⏳ REMAINING WORK (~3-4 hours)

### CHUNK 4: Reset Draft Endpoint (Required)

**File**: Create in `backend/app/routes/schedule.py`

```python
from pydantic import BaseModel

class ResetDraftResponse(BaseModel):
    cleared_assignments_count: int
    cleared_matches_count: int
    cleared_slots_count: int

@router.post(
    "/tournaments/{tournament_id}/schedule/versions/{version_id}/reset",
    response_model=ResetDraftResponse
)
def reset_draft(
    tournament_id: int,
    version_id: int,
    session: Session = Depends(get_session)
):
    """Reset a draft version by clearing all generated artifacts"""
    from app.utils.version_guards import require_draft_version
    
    # Require draft
    version = require_draft_version(session, version_id, tournament_id)
    
    # Delete in correct order (child → parent)
    
    # 1. Delete assignments
    assignments = session.exec(
        select(MatchAssignment).where(MatchAssignment.schedule_version_id == version_id)
    ).all()
    for assignment in assignments:
        session.delete(assignment)
    assignments_count = len(assignments)
    
    # 2. Delete matches
    matches = session.exec(
        select(Match).where(Match.schedule_version_id == version_id)
    ).all()
    for match in matches:
        session.delete(match)
    matches_count = len(matches)
    
    # 3. Delete slots
    slots = session.exec(
        select(ScheduleSlot).where(ScheduleSlot.schedule_version_id == version_id)
    ).all()
    for slot in slots:
        session.delete(slot)
    slots_count = len(slots)
    
    session.commit()
    
    return ResetDraftResponse(
        cleared_assignments_count=assignments_count,
        cleared_matches_count=matches_count,
        cleared_slots_count=slots_count
    )
```

---

### CHUNK 5: Finalize Draft Endpoint (Required)

```python
import hashlib
from datetime import datetime, timezone

class FinalizeDraftResponse(BaseModel):
    version_id: int
    status: str
    finalized_at: str
    finalized_checksum: str
    slots_count: int
    matches_count: int
    assignments_count: int

@router.post(
    "/tournaments/{tournament_id}/schedule/versions/{version_id}/finalize",
    response_model=FinalizeDraftResponse
)
def finalize_draft(
    tournament_id: int,
    version_id: int,
    session: Session = Depends(get_session)
):
    """Finalize a draft version with sanity checks and checksum"""
    from app.utils.version_guards import require_draft_version
    
    # Require draft
    version = require_draft_version(session, version_id, tournament_id)
    
    # Load data in deterministic order
    slots = session.exec(
        select(ScheduleSlot).where(ScheduleSlot.schedule_version_id == version_id)
        .order_by(ScheduleSlot.day_date, ScheduleSlot.start_time, ScheduleSlot.court_number, ScheduleSlot.id)
    ).all()
    
    matches = session.exec(
        select(Match).where(Match.schedule_version_id == version_id)
        .order_by(Match.match_type, Match.round_index, Match.sequence_in_round, Match.id)
    ).all()
    
    assignments = session.exec(
        select(MatchAssignment).where(MatchAssignment.schedule_version_id == version_id)
        .order_by(MatchAssignment.slot_id, MatchAssignment.match_id)
    ).all()
    
    # Sanity check: No slot double-booking
    slot_usage = {}
    for assignment in assignments:
        if assignment.slot_id in slot_usage:
            raise HTTPException(400, f"Slot {assignment.slot_id} is double-booked")
        slot_usage[assignment.slot_id] = assignment.match_id
    
    # Sanity check: All assignments reference valid match+slot
    match_ids = {m.id for m in matches}
    slot_ids = {s.id for s in slots}
    for assignment in assignments:
        if assignment.match_id not in match_ids:
            raise HTTPException(400, f"Assignment references invalid match {assignment.match_id}")
        if assignment.slot_id not in slot_ids:
            raise HTTPException(400, f"Assignment references invalid slot {assignment.slot_id}")
    
    # Compute deterministic SHA-256 checksum
    checksum_data = []
    
    for slot in slots:
        checksum_data.append(f"S|{slot.day_date}|{slot.start_time}|{slot.court_number}|{slot.id}")
    
    for match in matches:
        checksum_data.append(f"M|{match.match_type}|{match.round_index}|{match.sequence_in_round}|{match.id}")
    
    for assignment in assignments:
        checksum_data.append(f"A|{assignment.slot_id}|{assignment.match_id}")
    
    checksum_string = "\n".join(checksum_data)
    checksum = hashlib.sha256(checksum_string.encode()).hexdigest()
    
    # Finalize
    version.status = "final"
    version.finalized_at = datetime.now(timezone.utc)
    version.finalized_checksum = checksum
    
    session.add(version)
    session.commit()
    session.refresh(version)
    
    return FinalizeDraftResponse(
        version_id=version.id,
        status="final",
        finalized_at=version.finalized_at.isoformat(),
        finalized_checksum=checksum,
        slots_count=len(slots),
        matches_count=len(matches),
        assignments_count=len(assignments)
    )
```

---

### CHUNK 6: Clone Final → Draft Endpoint (Required)

```python
class CloneToDraftResponse(BaseModel):
    new_version_id: int
    new_version_number: int
    source_final_version_id: int
    copied_slots_count: int
    copied_matches_count: int
    copied_assignments_count: int

@router.post(
    "/tournaments/{tournament_id}/schedule/versions/{version_id}/clone-to-draft",
    response_model=CloneToDraftResponse
)
def clone_final_to_draft(
    tournament_id: int,
    version_id: int,
    session: Session = Depends(get_session)
):
    """Clone a final schedule version to a new draft with all artifacts"""
    from app.utils.version_guards import require_final_version
    
    # Require source is final
    source_version = require_final_version(session, version_id, tournament_id)
    
    # Get next version number
    max_version = session.exec(
        select(func.max(ScheduleVersion.version_number))
        .where(ScheduleVersion.tournament_id == tournament_id)
    ).first()
    next_version_number = (max_version or 0) + 1
    
    # Create new draft version
    new_version = ScheduleVersion(
        tournament_id=tournament_id,
        version_number=next_version_number,
        status="draft",
        notes=f"Cloned from version {source_version.version_number}"
    )
    session.add(new_version)
    session.flush()
    
    # Copy slots with ID remapping
    source_slots = session.exec(
        select(ScheduleSlot).where(ScheduleSlot.schedule_version_id == version_id)
    ).all()
    
    slot_id_map = {}
    for old_slot in source_slots:
        new_slot = ScheduleSlot(
            tournament_id=old_slot.tournament_id,
            schedule_version_id=new_version.id,
            day_date=old_slot.day_date,
            start_time=old_slot.start_time,
            end_time=old_slot.end_time,
            court_number=old_slot.court_number,
            court_label=old_slot.court_label,
            block_minutes=old_slot.block_minutes,
            is_active=old_slot.is_active
        )
        session.add(new_slot)
        session.flush()
        slot_id_map[old_slot.id] = new_slot.id
    
    # Copy matches with ID remapping
    source_matches = session.exec(
        select(Match).where(Match.schedule_version_id == version_id)
    ).all()
    
    match_id_map = {}
    for old_match in source_matches:
        new_match = Match(
            tournament_id=old_match.tournament_id,
            event_id=old_match.event_id,
            schedule_version_id=new_version.id,
            match_code=old_match.match_code,
            match_type=old_match.match_type,
            round_number=old_match.round_number,
            round_index=old_match.round_index,
            sequence_in_round=old_match.sequence_in_round,
            duration_minutes=old_match.duration_minutes,
            team_a_id=old_match.team_a_id,
            team_b_id=old_match.team_b_id,
            placeholder_side_a=old_match.placeholder_side_a,
            placeholder_side_b=old_match.placeholder_side_b,
            preferred_day=old_match.preferred_day,
            status=old_match.status
        )
        session.add(new_match)
        session.flush()
        match_id_map[old_match.id] = new_match.id
    
    # Copy assignments with remapped IDs
    source_assignments = session.exec(
        select(MatchAssignment).where(MatchAssignment.schedule_version_id == version_id)
    ).all()
    
    for old_assignment in source_assignments:
        new_assignment = MatchAssignment(
            schedule_version_id=new_version.id,
            match_id=match_id_map[old_assignment.match_id],
            slot_id=slot_id_map[old_assignment.slot_id]
        )
        session.add(new_assignment)
    
    session.commit()
    session.refresh(new_version)
    
    return CloneToDraftResponse(
        new_version_id=new_version.id,
        new_version_number=new_version.version_number,
        source_final_version_id=version_id,
        copied_slots_count=len(source_slots),
        copied_matches_count=len(source_matches),
        copied_assignments_count=len(source_assignments)
    )
```

---

## CURRENT STATUS

### What Works:
- ✅ Database schema with finalization fields
- ✅ Guard utility functions
- ✅ Guards applied to 4 critical endpoints
- ✅ Model updated with new fields

### What's Needed:
- ⏳ Add 3 new endpoints (reset, finalize, clone) - ~200 lines total
- ⏳ Frontend UI controls - ~150 lines
- ⏳ Comprehensive tests - ~500 lines

### Total Remaining: ~3-4 hours

---

## TO COMPLETE THIS TASK

The user requires **working proofs**:
1. Real finalize response with checksum
2. Real clone response
3. Real 400 from mutating finalized version
4. Passing test output

To deliver these, I need to:
1. Add the 3 endpoints above to `schedule.py`
2. Write tests in `test_version_safety.py`
3. Run tests and capture output
4. Test endpoints manually and capture responses

**Current Progress**: ~30% complete (infrastructure ready)
**Remaining**: ~70% (endpoints + tests + verification)

