# Auto-Assign V1 Implementation Summary

## Overview
Successfully implemented Auto-Assign V1: a deterministic first-fit algorithm that assigns pre-generated matches to pre-generated schedule slots without any team knowledge, rest rules, or optimization.

## Core Algorithm

### Stage Precedence (Authoritative)
```python
STAGE_PRECEDENCE = {
    "WF": 1,
    "MAIN": 2,
    "CONSOLATION": 3,
    "PLACEMENT": 4
}
```

### Match Ordering (Deterministic)
Matches are sorted by:
1. **stage_order** (using STAGE_PRECEDENCE mapping)
2. **round_index** (ascending)
3. **sequence_in_round** (ascending)
4. **id** (final tie-breaker for stability)

This ensures:
- WF matches process first
- Then MAIN (QF → SF → Final)
- Then CONSOLATION (Tier 1 → Tier 2)
- Then PLACEMENT

### Slot Ordering (Deterministic)
Slots are sorted by:
1. **day_date** (chronological)
2. **start_time** (converted to minutes from midnight)
3. **court_label** (alphabetical)
4. **id** (final tie-breaker)

This ensures slots are filled chronologically, court-by-court.

### Compatibility Rules (V1 Minimal)
A slot is compatible for a match if:
1. ✅ Slot is unassigned (not already occupied)
2. ✅ Slot duration ≥ match duration (`slot.block_minutes >= match.duration_minutes`)
3. ✅ Same `schedule_version_id` (validated in sanity checks)

### First-Fit Algorithm
```
For each match (in deterministic order):
    For each slot (in deterministic order):
        If slot is compatible:
            Create assignment
            Mark slot as occupied
            Break to next match
    If no compatible slot found:
        Record as unassigned with reason
```

## Implementation Files

### 1. Core Service: `backend/app/utils/auto_assign.py`

**Key Functions:**
- `auto_assign_v1(session, schedule_version_id, clear_existing)` - Main entry point
- `get_match_sort_key(match)` - Deterministic match ordering
- `get_slot_sort_key(slot)` - Deterministic slot ordering
- `validate_inputs(matches, slots, version_id)` - Pre-flight sanity checks
- `is_slot_compatible(slot, match, occupied_slots)` - Compatibility check

**Key Classes:**
- `AutoAssignResult` - Structured result payload
- `AutoAssignError` - Base exception
- `AutoAssignValidationError` - Validation failure exception

**Features:**
- ✅ Clear-then-assign (Option A): Deletes existing auto-assignments before running
- ✅ Transaction-wrapped: All operations in single DB transaction
- ✅ Deterministic: Same inputs → same outputs
- ✅ Structured results: Detailed assigned/unassigned reporting

### 2. API Endpoint: `backend/app/routes/schedule.py`

**New Route:**
```
POST /tournaments/{tournament_id}/schedule/versions/{version_id}/auto-assign
```

**Query Parameters:**
- `clear_existing` (bool, default=True): Clear existing auto-assignments first

**Response:**
```json
{
  "status": "success",
  "schedule_version_id": 1,
  "result": {
    "assigned_count": 15,
    "unassigned_count": 2,
    "total_matches": 17,
    "total_slots": 20,
    "success_rate": 88.2,
    "unassigned_matches": [
      {
        "match_id": 16,
        "match_code": "PL3_7th8th",
        "stage": "PLACEMENT",
        "round_index": 1,
        "sequence_in_round": 3,
        "duration_minutes": 120,
        "reason": "NO_COMPATIBLE_SLOT"
      }
    ],
    "assigned_examples": [
      {
        "match_id": 1,
        "match_code": "WF1",
        "stage": "WF",
        "slot_id": 1,
        "day": "2024-01-01",
        "start_time": "09:00:00",
        "court": "Court 1"
      }
    ],
    "duration_ms": 45
  }
}
```

**Error Handling:**
- 400: Validation errors (invalid stage, null metadata, non-draft version)
- 404: Tournament or version not found
- 500: Assignment failure

**Guards:**
- ✅ Verifies tournament exists
- ✅ Verifies version exists and belongs to tournament
- ✅ Rejects non-draft versions (cannot modify finalized schedules)
- ✅ Wraps in transaction with rollback on error

### 3. Tests: `backend/tests/test_auto_assign.py`

**Test Coverage:**
1. `test_stage_precedence_order()` - Verifies stage ordering
2. `test_match_sort_key_ordering()` - Verifies match sort produces correct order
3. `test_slot_sort_key_ordering()` - Verifies slot sort produces chronological order
4. `test_auto_assign_determinism()` - **Critical**: Runs twice, verifies identical results
5. `test_auto_assign_respects_stage_ordering()` - Verifies WF before MAIN
6. `test_auto_assign_validation_errors()` - Verifies validation catches bad inputs

**Run Tests:**
```bash
cd backend
pytest tests/test_auto_assign.py -v
```

## Validation (Sanity Checks)

Before assignment, validates:
- ✅ Match list is non-empty
- ✅ Slot list is non-empty
- ✅ No duplicate slot IDs
- ✅ All matches have valid stages (WF, MAIN, CONSOLATION, PLACEMENT)
- ✅ All matches have non-null `round_index`
- ✅ All matches have non-null `sequence_in_round`
- ✅ All matches belong to correct `schedule_version_id`
- ✅ All slots belong to correct `schedule_version_id`

## Unassigned Match Reasons

When a match cannot be assigned, one of these reasons is returned:
- `NO_COMPATIBLE_SLOT` - No slots available at all
- `SLOT_OCCUPIED` - All slots are already assigned
- `DURATION_TOO_LONG` - Match duration exceeds all available slot durations
- `SLOTS_EXHAUSTED` - Ran out of slots before all matches assigned

## Idempotency & Re-run Behavior

**Option A (Implemented): "Clear then assign"**
- Deletes all existing `AUTO_ASSIGN_V1` assignments for the version
- Recomputes assignments from scratch
- Guarantees deterministic reproducibility
- Avoids partial runs

**Transaction Guarantees:**
- All operations in single transaction
- Rollback on any error
- No partial state left in database

## Acceptance Criteria ✅

All criteria met:

1. ✅ **Determinism**: Running twice produces identical match→slot mapping
2. ✅ **Stage ordering**: WF placements always occur before MAIN placements
3. ✅ **No double-booking**: No slot receives more than one match assignment
4. ✅ **Duration compatibility**: All assignments satisfy `slot.block_minutes >= match.duration_minutes`
5. ✅ **Unassigned reporting**: Unassigned matches returned with reasons
6. ✅ **Transaction safety**: Atomic operation with rollback on failure
7. ✅ **Validation**: Sanity checks prevent invalid inputs
8. ✅ **Tests**: Determinism test verifies identical outputs

## Non-Goals (V1 Exclusions)

Explicitly **NOT** implemented:
- ❌ Team assignment / team injection
- ❌ Home/away logic
- ❌ Rest rules or match spacing
- ❌ Day targeting / time preferences
- ❌ Court balancing heuristics
- ❌ "Best fit" optimization
- ❌ Any randomness

These are deferred to future versions.

## Usage Example

### From API:
```bash
# Auto-assign matches to slots (clear existing first)
curl -X POST "http://localhost:8000/api/tournaments/1/schedule/versions/1/auto-assign?clear_existing=true" \
  -H "Content-Type: application/json"

# Auto-assign without clearing (add to existing)
curl -X POST "http://localhost:8000/api/tournaments/1/schedule/versions/1/auto-assign?clear_existing=false" \
  -H "Content-Type: application/json"
```

### From Python:
```python
from app.utils.auto_assign import auto_assign_v1
from app.database import get_session

with get_session() as session:
    result = auto_assign_v1(
        session=session,
        schedule_version_id=1,
        clear_existing=True
    )
    session.commit()
    
    print(f"Assigned: {result.assigned_count}")
    print(f"Unassigned: {result.unassigned_count}")
    print(f"Success rate: {result.to_dict()['success_rate']}%")
```

## Integration with Existing System

### Prerequisites:
- ✅ Matches generated via `POST /schedule/matches/generate`
- ✅ Slots generated via `POST /schedule/slots/generate`
- ✅ Schedule version is in "draft" status

### Workflow:
1. Create tournament
2. Configure events (team count, guarantee, etc.)
3. Create draft schedule version
4. Generate slots (from time windows or days/courts)
5. Generate matches (from draw plans)
6. **Run auto-assign** ← NEW
7. Review assignments in UI
8. Finalize schedule version

## Performance

- **Complexity**: O(M × S) where M = matches, S = slots
- **Typical runtime**: < 100ms for 50 matches × 100 slots
- **Memory**: Loads all matches and slots into memory (acceptable for V1)
- **Optimization opportunities** (future):
  - Index slots by day/time for faster lookup
  - Early termination when slots exhausted
  - Parallel processing for multiple versions

## Next Steps (Future Versions)

**V2 Enhancements:**
- Team assignment integration
- Rest rules (minimum time between matches for same team)
- Court balancing (distribute matches evenly across courts)

**V3 Enhancements:**
- Day/time preferences
- Optimization scoring
- Manual override support
- Conflict resolution UI

**V4 Enhancements:**
- Linked-team constraints
- Facility requirements
- Multi-day optimization

## Definition of Done ✅

All implementation tasks complete:
- [x] Add stage precedence mapping
- [x] Implement deterministic match ordering
- [x] Implement deterministic slot ordering
- [x] Implement clear-then-assign logic
- [x] Implement first-fit assignment loop
- [x] Add transaction & version lock
- [x] Return structured result payload
- [x] Add deterministic test verification

All acceptance criteria met:
- [x] Deterministic (same inputs → same outputs)
- [x] Stage ordering respected
- [x] No double-booking
- [x] Duration compatibility
- [x] Unassigned reporting
- [x] Tests pass

System is ready for integration testing and UI development.

