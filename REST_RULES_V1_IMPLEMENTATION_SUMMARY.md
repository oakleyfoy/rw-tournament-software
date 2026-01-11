# Rest Rules V1 — Implementation Summary

**Date:** January 7, 2026  
**Status:** ✅ COMPLETE — All Phases Implemented

---

## Executive Summary

Rest Rules V1 enforces minimum rest times between matches for teams, ensuring:
- **WF → Scoring**: 60 minutes minimum rest
- **Scoring → Scoring**: 90 minutes minimum rest
- **Placeholder matches**: Rest rules skipped (team_id = null)
- **Determinism**: Same input → same output every time

---

## Phase-by-Phase Implementation

### Phase R1: Configuration ✅

**Hard-coded Constants:**
```python
REST_WF_TO_SCORING_MINUTES = 60
REST_SCORING_TO_SCORING_MINUTES = 90
```

**Location:** `backend/app/utils/rest_rules.py`

**Note:** Intentionally hard-coded for V1. Can be externalized to database/config in future versions.

---

### Phase R2: Team Rest State Tracking ✅

**Classes Implemented:**
- `TeamRestState`: Tracks individual team's last match end time and stage
- `RestStateTracker`: Manages rest state for all teams during assignment

**Key Methods:**
- `update_team_state(team_id, end_time, stage)`: Updates after match assignment
- `get_team_state(team_id)`: Retrieves current rest state
- `has_previous_match()`: Checks if team has been assigned yet

**Tracking Logic:**
- State updated immediately after each assignment
- Tracks: `last_match_end_time`, `last_match_stage`
- Only updated when match is successfully assigned

---

### Phase R3: Rest Compatibility Check ✅

**Function:** `check_rest_compatibility(slot, match, rest_tracker)`

**Logic Flow:**
1. For each team (team_a_id, team_b_id):
   - If team_id is null → Skip rest check (placeholder)
   - If no prior match → Pass rest check
   - Else → Calculate required rest:
     - If `last_stage == "WF"` AND `current_stage != "WF"` → 60 min
     - Else → 90 min
2. Verify: `slot.start_time >= last_match_end_time + required_rest`
3. Return violations if any

**RestViolation Class:**
```python
RestViolation(
    team_id: int,
    violation_type: str,  # "REST_WF_TO_SCORING" or "REST_SCORING_TO_SCORING"
    required_rest_minutes: int,
    actual_gap_minutes: float,
    slot_start_time: datetime,
    earliest_allowed_time: datetime
)
```

---

### Phase R4: Assignment Strategy ✅

**Function:** `auto_assign_with_rest(session, schedule_version_id, clear_existing)`

**Strategy (Unchanged Determinism):**
1. Load matches in deterministic order:
   - `match_type` → `round_number` → `sequence_in_round` → `id`
2. Load slots in deterministic order:
   - `day_date` → `start_time` → `court_number` → `id`
3. For each match:
   - Try slots in order
   - Check duration compatibility
   - Check rest compatibility
   - Assign to **first** compatible slot
   - Update team rest state
4. Track unassigned matches with reasons

**Unassigned Reasons:**
- `NO_SLOT_WITH_DURATION`: No slot large enough
- `NO_REST_COMPATIBLE_SLOT`: Duration OK but rest violated

**Return Data:**
```python
{
    "assigned_count": int,
    "unassigned_count": int,
    "unassigned_reasons": {
        "NO_REST_COMPATIBLE_SLOT": [
            {
                "match_id": int,
                "match_code": str,
                "rest_violations": [
                    {
                        "team_id": int,
                        "violation_type": str,
                        "required_rest_minutes": int,
                        "actual_gap_minutes": float
                    }
                ]
            }
        ]
    },
    "rest_violations_summary": {
        "wf_to_scoring_violations": int,
        "scoring_to_scoring_violations": int,
        "total_rest_blocked": int
    }
}
```

---

### Phase R5: Endpoint ✅

**Endpoint:** `POST /api/tournaments/{tid}/schedule/versions/{vid}/auto-assign-rest`

**Query Parameters:**
- `clear_existing` (boolean, default=true): Clear assignments before running

**Response Model:**
```json
{
  "assigned_count": 12,
  "unassigned_count": 3,
  "unassigned_reasons": {
    "NO_REST_COMPATIBLE_SLOT": [
      {
        "match_id": 15,
        "match_code": "MAIN_03",
        "duration_minutes": 90,
        "team_a_id": 1,
        "team_b_id": 2,
        "rest_violations": [
          {
            "team_id": 1,
            "violation_type": "REST_SCORING_TO_SCORING",
            "required_rest_minutes": 90,
            "actual_gap_minutes": 75.5
          }
        ]
      }
    ]
  },
  "rest_violations_summary": {
    "wf_to_scoring_violations": 0,
    "scoring_to_scoring_violations": 3,
    "total_rest_blocked": 3
  }
}
```

**Location:** `backend/app/routes/schedule.py`

---

### Phase R6: Conflict Reporting Extension ✅

**Integrated into Auto-Assign Response:**
- `rest_violations_summary` includes:
  - `wf_to_scoring_violations`: Count of WF→Scoring blocks
  - `scoring_to_scoring_violations`: Count of Scoring→Scoring blocks
  - `total_rest_blocked`: Total matches blocked by rest

**Detailed Violations:**
- Each unassigned match includes:
  - Specific team_id causing violation
  - Violation type
  - Required vs actual rest time
  - Can be used to calculate `earliest_possible_start_time`

**Diagnostic Use:**
- Tournament directors can see which teams are blocking
- Can identify if more slots needed or matches need reordering
- Read-only reporting (no auto-resolution)

---

### Phase R7: Tests ✅

**Test File:** `backend/tests/test_rest_rules_v1.py`

**Test Coverage:**

| Test | Purpose | Status |
|------|---------|--------|
| `test_wf_to_scoring_60_minutes_allowed` | Verify 60 min WF→Scoring OK | ✅ |
| `test_wf_to_scoring_59_minutes_rejected` | Verify 59 min WF→Scoring rejected | ✅ |
| `test_scoring_to_scoring_90_minutes_required` | Verify 90 min Scoring→Scoring OK | ✅ |
| `test_scoring_to_scoring_89_minutes_rejected` | Verify 89 min Scoring→Scoring rejected | ✅ |
| `test_placeholder_match_ignores_rest` | Null team_ids skip rest check | ✅ |
| `test_one_null_team_still_assigns` | One null team still assigns | ✅ |
| `test_determinism` | Two runs → identical results | ✅ |
| `test_no_team_scheduled_inside_rest_window` | Comprehensive violation check | ✅ |

**Run Tests:**
```bash
cd backend
pytest tests/test_rest_rules_v1.py -v
```

---

## Technical Architecture

### File Structure

```
backend/
├── app/
│   ├── utils/
│   │   └── rest_rules.py          # Core logic (R1-R4)
│   └── routes/
│       └── schedule.py             # Endpoint (R5)
└── tests/
    └── test_rest_rules_v1.py       # Tests (R7)
```

### Key Design Decisions

1. **No Backtracking**: First-fit only, no optimization
   - Maintains determinism
   - Simple, predictable behavior
   - Fast execution

2. **Placeholder Handling**: Null team_ids bypass rest
   - Allows bracket progression matches
   - Rest only checked for known teams
   - One null team still assigns (checks known side)

3. **State Tracking**: In-memory during assignment
   - No database writes for intermediate state
   - Clean rollback on error
   - Efficient bulk assignment

4. **Violation Reporting**: Detailed diagnostics
   - Per-team violation details
   - Actual vs required rest times
   - Actionable feedback for tournament directors

---

## Usage Examples

### Example 1: Basic Auto-Assign with Rest

```bash
# Clear existing and run rest-aware assignment
curl -X POST "http://localhost:8000/api/tournaments/1/schedule/versions/1/auto-assign-rest?clear_existing=true"
```

**Response:**
```json
{
  "assigned_count": 18,
  "unassigned_count": 2,
  "unassigned_reasons": {...},
  "rest_violations_summary": {
    "wf_to_scoring_violations": 0,
    "scoring_to_scoring_violations": 2,
    "total_rest_blocked": 2
  }
}
```

### Example 2: Incremental Assignment

```bash
# Keep existing assignments, add new matches
curl -X POST "http://localhost:8000/api/tournaments/1/schedule/versions/1/auto-assign-rest?clear_existing=false"
```

---

## Acceptance Criteria Status

| Criterion | Status |
|-----------|--------|
| WF teams get exactly 1 hour before scoring | ✅ |
| All scoring matches enforce 90 minutes | ✅ |
| Violations surface as unassigned reasons | ✅ |
| No team scheduled inside rest window | ✅ |
| Deterministic behavior preserved | ✅ |

---

## Validation Examples

### Scenario: WF → Scoring Transition

**Setup:**
- WF match at 9:00 AM, duration 60 min, ends 10:00 AM
- MAIN match needs Team 1 (from WF)

**Slot Candidates:**
- Slot A: 10:00 AM → ✅ ALLOWED (60 min rest)
- Slot B: 9:59 AM → ❌ REJECTED (59 min rest)
- Slot C: 11:00 AM → ✅ ALLOWED (120 min rest)

**Result:** Match assigned to Slot A (first compatible)

### Scenario: Scoring → Scoring Transition

**Setup:**
- MAIN match 1 at 10:00 AM, duration 90 min, ends 11:30 AM
- MAIN match 2 needs Team 1 (from MAIN 1)

**Slot Candidates:**
- Slot A: 1:00 PM → ✅ ALLOWED (90 min rest)
- Slot B: 12:59 PM → ❌ REJECTED (89 min rest)
- Slot C: 2:00 PM → ✅ ALLOWED (150 min rest)

**Result:** Match assigned to Slot A (first compatible)

---

## Future Enhancements (V2+)

1. **Configurable Rest Times**
   - Per-tournament settings
   - Per-event overrides
   - Database-driven configuration

2. **Optimized Assignment**
   - Backtracking for better slot utilization
   - Minimize rest violations
   - Multi-objective optimization

3. **Rest Preferences**
   - Preferred rest > minimum rest
   - "Soft" vs "hard" rest requirements
   - Team-specific rest overrides

4. **Advanced Reporting**
   - Per-team rest analysis
   - Rest distribution histogram
   - "What-if" scenario analysis

5. **UI Integration**
   - Visual rest timeline
   - Color-coded rest status
   - Interactive rest violation resolution

---

## Known Limitations (V1)

1. **No Optimization**: Uses first compatible slot
   - May leave better slots unused
   - No global optimization

2. **Hard-coded Limits**: 60/90 min not configurable
   - Same for all tournaments
   - Can't accommodate special requirements

3. **No Soft Constraints**: All rest requirements are hard
   - Either passes or fails
   - No "preferred but not required" rest

4. **No Manual Override**: Rest violations block assignment
   - Tournament director can't force assignment
   - Would need to use non-rest-aware endpoint

---

## Files Modified/Created

### New Files
- `backend/app/utils/rest_rules.py` (core logic)
- `backend/tests/test_rest_rules_v1.py` (test suite)

### Modified Files
- `backend/app/routes/schedule.py` (added endpoint)

---

## Summary

Rest Rules V1 is **production-ready** with:
- ✅ Complete implementation across all 7 phases
- ✅ Comprehensive test coverage
- ✅ Deterministic, predictable behavior
- ✅ Detailed violation reporting
- ✅ Backward compatible (new endpoint, doesn't affect existing)

The system enforces team rest requirements while maintaining the deterministic assignment strategy critical for tournament management.


