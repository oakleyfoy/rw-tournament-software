# Conflicts Endpoint Regression Test - Implementation Summary

## ✅ Completed Tasks

### 1. New Regression Test File Created

**File**: `backend/tests/test_schedule_conflicts_endpoint.py`

**Purpose**: Prove the GET `/schedule/conflicts` endpoint returns stable responses after refactors.

**Test Coverage** (6 tests):
1. ✅ `test_conflicts_endpoint_returns_200_with_stable_shape` - Validates status 200, response keys, version ID, and internal consistency
2. ✅ `test_conflicts_endpoint_unassigned_list_has_expected_fields` - Validates unassigned match diagnostics
3. ✅ `test_conflicts_endpoint_requires_schedule_version_id` - Validates required query param
4. ✅ `test_conflicts_endpoint_404_for_invalid_tournament` - Validates 404 handling
5. ✅ `test_conflicts_endpoint_404_for_invalid_version` - Validates 404 handling
6. ✅ `test_conflicts_endpoint_is_read_only` - Validates no database mutations

**All tests pass**: 6/6 ✅

---

### 2. "Connection failed" Message Investigation

**Finding**: The message is **NOT** from pytest or backend code.

**Source**: PowerShell Extension v2025.4.0 initialization in Cursor terminal.

**Evidence**:
- ✅ No matches for "Connection failed" in entire codebase
- ✅ No matches for "VPN" in backend
- ✅ Terminal file shows: `PowerShell Extension v2025.4.0\nCopyright (c) Microsoft Corporation.`

**Resolution**: **Safe to ignore** - it's just IDE terminal startup noise, not a test failure.

---

### 3. pytest Invocation Issues - Troubleshooting Guide

#### Problem: "10 collected / 10 deselected / 0 selected"

This happens when your `-k` filter doesn't match any test names.

#### ✅ Solutions:

**Option A: Run specific test file directly**
```powershell
cd "C:\RW Tournament Software\backend"
python -m pytest tests/test_schedule_conflicts_endpoint.py -v
```

**Option B: Run all tests in a file**
```powershell
python -m pytest tests/test_manual_schedule_editor.py -v
```

**Option C: Use `-k` filter correctly**
```powershell
# Find tests with "conflicts" in their name
python -m pytest tests/ -k conflicts -v

# Run a specific test function
python -m pytest tests/test_schedule_conflicts_endpoint.py::test_conflicts_endpoint_returns_200_with_stable_shape -v
```

**Option D: Run all tests**
```powershell
python -m pytest tests/ -v
```

#### Why `-k` deselects everything:

- `-k` is a **substring match** on test function names
- If your filter doesn't match any function names, everything is deselected
- Example: `-k endpoint` won't match `test_locked_assignments_not_moved_by_autoassign`

#### How to debug deselection:

1. Check what tests exist in the file:
   ```powershell
   python -m pytest tests/test_manual_schedule_editor.py --collect-only
   ```

2. See which tests match your filter:
   ```powershell
   python -m pytest tests/test_manual_schedule_editor.py -k conflicts --collect-only
   ```

---

### 4. Network Call Guardrails (Attempted, Reverted)

**Attempted**: Add `autouse=True` fixture to block `socket.socket()` calls.

**Result**: ❌ Too aggressive - broke asyncio event loop initialization on Windows.

**Reason**: Windows asyncio uses `socket.socketpair()` for internal IPC, not real network calls.

**Resolution**: Removed guardrail. TestClient already doesn't make real network calls (uses ASGI transport).

**Alternative**: If you need network guardrails in the future:
- Use `pytest-socket` plugin (supports asyncio)
- Mock `requests` / `httpx` at a higher level
- Use environment variables to disable external calls (`DISABLE_EXTERNAL_CALLS_IN_TESTS=1`)

---

## 📊 Test Fixture Used

**Fixture**: `conflicts_test_fixture` (in `test_schedule_conflicts_endpoint.py`)

**Creates**:
- 1 Tournament
- 1 Event
- 1 Schedule Version
- 5 Slots
- 4 Matches (2 assigned, 2 unassigned)

**Reuses the same pattern as**:
- `manual_editor_setup` (test_manual_schedule_editor.py)
- `conflict_report_fixture` (test_conflict_report.py)

---

## 🧪 Running the New Tests

```powershell
# Run just the new conflicts endpoint tests
cd "C:\RW Tournament Software\backend"
python -m pytest tests/test_schedule_conflicts_endpoint.py -v

# Run with short output
python -m pytest tests/test_schedule_conflicts_endpoint.py -q

# Run a single test
python -m pytest tests/test_schedule_conflicts_endpoint.py::test_conflicts_endpoint_returns_200_with_stable_shape -v
```

---

## 🎯 Key Validations in Regression Test

### Response Shape Validation
```python
assert "summary" in data
assert "unassigned" in data
assert "slot_pressure" in data
assert "stage_timeline" in data
assert "ordering_integrity" in data
```

### Internal Consistency Checks
```python
# Counts must add up
assert summary["total_matches"] == summary["assigned_matches"] + summary["unassigned_matches"]

# Assignment rate must be correct
expected_rate = (assigned / total * 100) if total > 0 else 0.0
assert abs(summary["assignment_rate"] - expected_rate) < 0.01
```

### ID Matching
```python
# Response must reference the correct version
assert summary["schedule_version_id"] == version_id
assert summary["tournament_id"] == tournament_id
```

---

## 🚀 Next Steps (Phase 3D.1 Task B)

These regression tests ensure you can safely refactor the conflicts endpoint:

1. ✅ **Before refactor**: Tests pass and prove current behavior
2. 🔄 **During refactor**: Run tests frequently to catch regressions
3. ✅ **After refactor**: Tests pass, proving same behavior

**Recommended workflow**:
```powershell
# Before making changes
python -m pytest tests/test_schedule_conflicts_endpoint.py -v

# ... make changes ...

# After each change
python -m pytest tests/test_schedule_conflicts_endpoint.py -v

# Final validation (run all tests)
python -m pytest tests/ -v
```

---

## 📝 Summary

✅ **6 new regression tests** cover conflicts endpoint  
✅ **"Connection failed" message** traced to PowerShell Extension (safe to ignore)  
✅ **pytest invocation guide** added to help troubleshoot deselection  
✅ **Network guardrails** attempted but reverted (incompatible with Windows asyncio)  

**All tests pass**: 6/6 ✅

The conflicts endpoint now has regression coverage for Phase 3D.1 refactoring work.

