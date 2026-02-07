# Phase 3D Completion Gate - Immutable Backend Semantics

**Status**: ✅ LOCKED (Do not re-decide)  
**Date**: 2026-01-12  
**Purpose**: Freeze Phase 3D backend semantics so UI work can proceed without re-opening backend

---

## Immutable Decisions (Non-Negotiable)

### 1. Finalized Schedule Versions Cannot Be Mutated ✅
**Rule**: Finalized schedule versions are **read-only**.

**Enforcement**:
- ✅ Route-level validation (422 error if finalized)
- ✅ Service-level guard in `manually_assign_match()` (Step 4)
- ✅ Test coverage: `test_manual_move_fails_on_finalized_version`

**Workflow**:
- To edit a finalized schedule: **Clone → Draft → Edit**
- Finalized versions are immutable history

**Why**: Prevents accidental corruption of published schedules.

---

### 2. Locked Assignments Are Immutable Facts ✅
**Rule**: Manual edits set `locked=True`; auto-assign **skips** locked assignments.

**Enforcement**:
- ✅ `manually_assign_match()` sets `locked=True`
- ✅ Auto-assign V2 filters out `locked=True` assignments
- ✅ Test coverage: `test_locked_assignments_not_moved_by_autoassign`

**Semantics**:
- Locked = "admin decision, do not touch"
- Unlocked = "auto-assigned, can be moved"

**Why**: Preserves manual overrides during re-optimization.

---

### 3. Conflict Computation Is Deterministic ✅
**Rule**: Identical inputs → identical outputs (byte-for-byte).

**Enforcement**:
- ✅ `ConflictReportBuilder.compute()` uses explicit sorting
- ✅ No timestamps in response
- ✅ Test coverage: `test_conflicts_endpoint_is_deterministic`

**Guarantees**:
- No random UUIDs
- No `generated_at` timestamps
- Stable list ordering (unassigned matches, violations, stages)
- Stable dict ordering (Python 3.7+ insertion order)

**Why**: UI can cache/compare conflict reports reliably.

---

### 4. Single Conflict Implementation (Service Layer) ✅
**Rule**: Only `ConflictReportBuilder.compute()` exists. No wrapper, no helper.

**Enforcement**:
- ✅ Wrapper function deleted (Step 3)
- ✅ All routes call service directly
- ✅ Zero remaining callers confirmed

**Architecture**:
```
Route Handler (Thin)
  └─ ConflictReportBuilder.compute() (Single source of truth)
```

**Why**: Eliminates drift between GET and PATCH responses.

---

### 5. Undo Model: Clone-Before-Edit ✅
**Rule**: "Undo" is accomplished by **cloning drafts pre-mutation** (or using prior clone).

**Workflow**:
1. User has draft version V1
2. UI clones V1 → V2 (before edit)
3. User edits V2
4. To undo: switch back to V1

**NOT Supported**:
- ❌ Transaction-level rollback (too complex)
- ❌ Event sourcing (overkill)
- ❌ Undo stack (state management nightmare)

**Why**: Simple, reliable, leverages existing clone infrastructure.

---

## Test Coverage (Immutable Proof)

### Determinism Tests
- ✅ `test_conflicts_endpoint_is_deterministic` (3 calls = identical JSON)
- ✅ `test_conflicts_endpoint_determinism.py` (5 additional tests)

### Finalized Version Guards
- ✅ `test_manual_move_fails_on_finalized_version` (route + service)

### Locked Assignment Semantics
- ✅ `test_locked_assignments_not_moved_by_autoassign` (auto-assign skips)
- ✅ `test_clone_preserves_locked_assignments` (clone preserves state)

### Service Layer Extraction
- ✅ 26 tests passing (conflicts + manual editor + determinism)
- ✅ Zero wrapper callers (confirmed by grep)

---

## API Contracts (Immutable)

### GET `/api/tournaments/{id}/schedule/conflicts`
**Query Params**:
- `schedule_version_id` (required)
- `event_id` (optional filter)

**Response Shape** (ConflictReportV1):
```json
{
  "summary": { "tournament_id", "schedule_version_id", "total_slots", ... },
  "unassigned": [ { "match_id", "stage", "reason", ... } ],
  "slot_pressure": { "unused_slots_count", ... },
  "stage_timeline": [ { "stage", "first_assigned_start_time", ... } ],
  "ordering_integrity": { "deterministic_order_ok", "violations": [...] }
}
```

**Guarantees**:
- Deterministic (same input → same output)
- Read-only (no mutations)
- Status codes: 200 (OK), 404 (not found), 422 (validation)

---

### PATCH `/api/tournaments/{id}/schedule/assignments/{assignment_id}`
**Request Body**:
```json
{
  "new_slot_id": 123
}
```

**Response Shape** (ManualAssignmentResponse):
```json
{
  "assignment_id", "match_id", "slot_id", "locked": true, "assigned_by": "MANUAL",
  "assigned_at", "validation_passed": true,
  "slot_key": { "day_date", "start_time", "court_number", "court_label" },
  "conflicts_summary": { ... },
  "unassigned_matches": [ ... ]
}
```

**Guarantees**:
- Sets `locked=True` (manual override)
- Recomputes conflicts (same as GET)
- Fails on finalized versions (422)
- Status codes: 200 (OK), 404 (not found), 422 (validation)

---

## Service Layer Contract (Immutable)

### `ConflictReportBuilder.compute()`
**Signature**:
```python
def compute(
    self,
    session: Session,
    *,
    tournament_id: int,
    schedule_version_id: int,
    event_id: Optional[int] = None,
) -> ConflictReportV1:
```

**Guarantees**:
- Pure function (no mutations)
- Deterministic (explicit sorting)
- No HTTP dependencies
- Returns Pydantic model

**Usage**:
```python
builder = ConflictReportBuilder()
report = builder.compute(
    session=session,
    tournament_id=tid,
    schedule_version_id=vid,
)
```

---

## Mutation Layer Contract (Immutable)

### `manually_assign_match()`
**Signature**:
```python
def manually_assign_match(
    session: Session,
    match_id: int,
    new_slot_id: int,
    schedule_version_id: int,
    assigned_by: str = "MANUAL"
) -> MatchAssignment:
```

**Guarantees**:
- Enforces draft-only (raises if finalized)
- Sets `locked=True`
- Validates slot availability, duration, rest constraints
- Raises `ManualAssignmentValidationError` on failure

---

## UI Assumptions (Safe to Build On)

### Conflicts Endpoint
- ✅ Can be called repeatedly (deterministic)
- ✅ Can be cached (no timestamps)
- ✅ Can be compared (stable ordering)

### Manual Assignment
- ✅ Always sets `locked=True`
- ✅ Returns full conflict report (no extra API calls)
- ✅ Fails gracefully on finalized versions

### Undo Model
- ✅ Clone before edit (pre-mutation snapshot)
- ✅ Switch versions to "undo" (no transaction rollback)

---

## What UI Can Build Now

### Phase 3E: Manual Editor UI
- ✅ Display conflicts (GET endpoint)
- ✅ Drag-and-drop reassignment (PATCH endpoint)
- ✅ Lock indicator (show `locked=True` assignments)
- ✅ Finalized version guard (disable edits, show "clone to edit")
- ✅ Undo via version switching (clone before edit)

### What UI Should NOT Do
- ❌ Implement undo stack (use clone-before-edit)
- ❌ Cache conflicts indefinitely (recompute after mutations)
- ❌ Allow edits on finalized versions (backend blocks it)

---

## Rollback Plan (If UI Finds Issues)

### If Backend Semantics Must Change
1. **Stop**: Do not change backend without re-opening Phase 3D
2. **Document**: File issue explaining why semantics must change
3. **Re-test**: Run full 26-test suite after changes
4. **Update Gate**: Re-publish this document with new decisions

### If UI Finds Bugs
1. **Check**: Is it a backend bug or UI assumption?
2. **Test**: Does existing test suite catch it?
3. **Fix**: Add regression test, fix bug, re-run suite

---

## Sign-Off

**Phase 3D Backend**: ✅ COMPLETE  
**Tests**: 26/26 passing  
**Wrapper**: Deleted  
**Determinism**: Proven  
**Draft-Only**: Enforced  

**UI Work Can Begin**: ✅ YES

---

## Quick Reference

```powershell
# Run full test suite
cd "C:\RW Tournament Software\backend"
python -m pytest tests/test_schedule_conflicts_endpoint.py tests/test_manual_schedule_editor.py tests/test_conflict_report.py -v

# Check for wrapper callers (should be zero)
grep "compute_conflict_report\(" backend/app
# Result: Only in docs (none in code)

# Verify determinism
python -m pytest tests/test_schedule_conflicts_endpoint.py::test_conflicts_endpoint_is_deterministic -v
```

---

**This document is immutable.** If semantics must change, re-open Phase 3D with explicit justification.

