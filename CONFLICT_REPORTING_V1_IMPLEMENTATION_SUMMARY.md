# Conflict Reporting V1 - Implementation Summary

## Overview

Conflict Reporting V1 is a comprehensive read-only diagnostic endpoint that provides detailed analysis of schedule assignments, identifying conflicts, unassigned matches, slot pressure, and ordering integrity violations.

## Implementation Status

✅ **COMPLETE** - All acceptance criteria met

## Endpoint Details

### Route
```
GET /api/tournaments/{tournament_id}/schedule/conflicts
```

### Query Parameters
- `schedule_version_id` (required): The schedule version to analyze
- `event_id` (optional): Filter matches by specific event

### Response Model: `ConflictReportV1`

The endpoint returns a comprehensive JSON report with five main sections:

## Response Structure

### 1. Summary
Provides high-level statistics about the schedule:

```json
{
  "tournament_id": 1,
  "schedule_version_id": 1,
  "total_slots": 320,
  "total_matches": 52,
  "assigned_matches": 0,
  "unassigned_matches": 52,
  "assignment_rate": 0.0
}
```

### 2. Unassigned Matches
Lists all unassigned matches with diagnostic reasons:

```json
[
  {
    "match_id": 5,
    "stage": "MAIN",
    "round_index": 1,
    "sequence_in_round": 1,
    "duration_minutes": 120,
    "reason": "DURATION_TOO_LONG",
    "notes": null
  }
]
```

**Reason Codes:**
- `SLOTS_EXHAUSTED` - No free slots available
- `DURATION_TOO_LONG` - No slots with sufficient duration
- `NO_COMPATIBLE_SLOT` - Free slots exist but aren't compatible
- `UNKNOWN` - Unable to determine reason

### 3. Slot Pressure
Analyzes slot utilization and availability:

```json
{
  "unused_slots_count": 320,
  "unused_slots_by_day": {
    "2026-01-08": 80,
    "2026-01-09": 80,
    "2026-01-10": 80,
    "2026-01-11": 80
  },
  "unused_slots_by_court": {
    "10": 64,
    "11": 64,
    "12": 64,
    "4": 64,
    "5": 64
  },
  "insufficient_duration_slots_count": 320,
  "longest_match_duration": 120,
  "max_slot_duration": 15
}
```

### 4. Stage Timeline
Tracks assignment timeline per stage with spillover detection:

```json
[
  {
    "stage": "WF",
    "first_assigned_start_time": "2026-03-01T09:00:00",
    "last_assigned_start_time": "2026-03-01T09:00:00",
    "assigned_count": 2,
    "unassigned_count": 0,
    "spillover_warning": false
  },
  {
    "stage": "MAIN",
    "first_assigned_start_time": "2026-03-01T10:00:00",
    "last_assigned_start_time": "2026-03-01T10:00:00",
    "assigned_count": 2,
    "unassigned_count": 1,
    "spillover_warning": false
  }
]
```

**Spillover Warning:** Flags when a later-priority stage (e.g., MAIN) is scheduled before an earlier-priority stage (e.g., WF).

### 5. Ordering Integrity
Validates that assigned matches respect deterministic ordering:

```json
{
  "deterministic_order_ok": true,
  "violations": []
}
```

**Violation Types:**
- `STAGE_ORDER_INVERSION` - Later stage scheduled before earlier stage
- `ROUND_ORDER_INVERSION` - Later round scheduled before earlier round
- `ORDERING_VIOLATION` - Generic ordering violation

Each violation includes:
```json
{
  "type": "STAGE_ORDER_INVERSION",
  "earlier_match_id": 2,
  "later_match_id": 1,
  "details": "MAIN_FINAL scheduled at 2026-04-01T09:00:00 comes after WF_QF1 at 2026-04-01T10:00:00 but should come before in deterministic order"
}
```

## Implementation Details

### Location
- **File:** `backend/app/routes/schedule.py` (lines 1344-1689)
- **Router:** Registered in `schedule.router`

### Key Features

1. **Read-Only Operation**
   - No database modifications
   - Safe to call repeatedly
   - No side effects

2. **Deterministic Analysis**
   - Uses same sort keys as Auto-Assign V1
   - Consistent with `get_match_sort_key()` and `get_slot_sort_key()`

3. **Stage Precedence**
   - WF (1) → MAIN (2) → CONSOLATION (3) → PLACEMENT (4)
   - From `app.utils.auto_assign.STAGE_PRECEDENCE`

4. **Best-Effort Reason Computation**
   - Analyzes available slots vs match requirements
   - Determines most likely cause of assignment failure

## Test Coverage

### Test File
`backend/tests/test_conflict_report.py`

### Tests Implemented (10 total, all passing)

1. ✅ `test_conflict_report_endpoint_exists` - Verifies endpoint returns 200
2. ✅ `test_conflict_report_summary` - Validates summary counts
3. ✅ `test_conflict_report_unassigned_with_reasons` - Checks unassigned match reasons
4. ✅ `test_conflict_report_slot_pressure` - Verifies slot pressure metrics
5. ✅ `test_conflict_report_stage_timeline` - Validates stage timeline data
6. ✅ `test_conflict_report_ordering_integrity` - Tests correct ordering validation
7. ✅ `test_conflict_report_ordering_violation_detection` - Tests violation detection
8. ✅ `test_conflict_report_requires_schedule_version_id` - Validates required parameter
9. ✅ `test_conflict_report_invalid_tournament` - Tests 404 handling
10. ✅ `test_conflict_report_read_only` - Confirms no database modifications

### Test Execution
```bash
cd backend
python -m pytest tests/test_conflict_report.py -v
# Result: 10 passed in 0.29s
```

## Acceptance Criteria - All Met

### ✅ Endpoint returns 200 with populated ConflictReportV1
- Verified with live database test
- Returns complete JSON structure with all sections

### ✅ No writes occur (verify DB untouched)
- `test_conflict_report_read_only` confirms no DB changes
- Counts matches, assignments, and slots before/after call
- All counts remain identical

### ✅ Report correctly identifies unassigned matches and gives reasons
- Best-effort reason computation implemented
- Three reason categories: SLOTS_EXHAUSTED, DURATION_TOO_LONG, NO_COMPATIBLE_SLOT
- Tested with fixtures containing unassigned matches

### ✅ Stage spillover detection works
- Compares stage time ranges against precedence order
- Flags when later-priority stage starts before earlier-priority stage
- Tested in `test_conflict_report_stage_timeline`

### ✅ Ordering integrity check exists and returns violations when forced
- Compares deterministic match order vs actual slot time order
- Detects STAGE_ORDER_INVERSION, ROUND_ORDER_INVERSION, generic violations
- `test_conflict_report_ordering_violation_detection` forces and detects violations

## Usage Example

### Python/Requests
```python
import requests

response = requests.get(
    "http://localhost:8000/api/tournaments/1/schedule/conflicts",
    params={"schedule_version_id": 1}
)

if response.status_code == 200:
    report = response.json()
    print(f"Assignment rate: {report['summary']['assignment_rate']}%")
    print(f"Unassigned: {len(report['unassigned'])}")
    print(f"Ordering OK: {report['ordering_integrity']['deterministic_order_ok']}")
```

### Frontend Integration
```typescript
// Example fetch call
const response = await fetch(
  `/api/tournaments/${tournamentId}/schedule/conflicts?schedule_version_id=${versionId}`
);

if (response.ok) {
  const report: ConflictReportV1 = await response.json();
  
  // Display summary
  console.log(`${report.summary.assigned_matches}/${report.summary.total_matches} matches assigned`);
  
  // Show unassigned matches
  report.unassigned.forEach(match => {
    console.log(`Match ${match.match_id}: ${match.reason}`);
  });
  
  // Check for violations
  if (!report.ordering_integrity.deterministic_order_ok) {
    console.warn(`${report.ordering_integrity.violations.length} ordering violations detected`);
  }
}
```

## Live Database Test Results

Tested against tournament ID 1, schedule version 1:

```
Tournament: Bahamas
Matches: 52 (WF: 16, MAIN: 36)
Slots: 320 (15-minute blocks across 4 days, 5 courts)
Assigned: 0
Unassigned: 52

Key Finding:
- All matches are 120 minutes duration
- All slots are only 15 minutes
- Reason: DURATION_TOO_LONG
- This correctly identifies the mismatch

Ordering Integrity: True (no violations since no assignments)
```

## Future Enhancements (Out of Scope for V1)

- Persist unassigned reasons from Auto-Assign V1 instead of recomputing
- Add filtering by stage/round
- Include suggested resolutions for each conflict
- Track historical conflict trends
- Add conflict severity scoring

## Related Files

### Core Implementation
- `backend/app/routes/schedule.py` - Endpoint and response models (lines 1344-1689)
- `backend/app/utils/auto_assign.py` - Shared sort functions and stage precedence

### Tests
- `backend/tests/test_conflict_report.py` - Comprehensive test suite (584 lines)

### Models
- `backend/app/models/match.py` - Match model with stage/round metadata
- `backend/app/models/match_assignment.py` - Assignment relationship
- `backend/app/models/schedule_slot.py` - Slot model with time/court data

## Notes

- The endpoint is already fully implemented and was present in the codebase
- All tests pass successfully (10/10)
- The implementation follows the exact specification from the requirements
- Read-only nature is verified through automated tests
- Deterministic ordering uses the same V1 sort keys as Auto-Assign

