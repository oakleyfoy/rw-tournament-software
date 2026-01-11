# Build Schedule Button Fix

## Issue

**Error:** "Input should be a valid integer, unable to parse string as an integer"

**When:** Clicking "Build Schedule" button in the Schedule Page Grid V1

---

## Root Cause

The `useScheduleGrid` hook was calling the `buildSchedule` API function with incorrect parameters:

**Incorrect Call:**
```typescript
const result = await buildSchedule(tournamentId, { schedule_version_id: activeVersion.id })
```

**Expected Call:**
```typescript
const result = await buildSchedule(tournamentId, activeVersion.id)
```

### Problem Details

1. **Parameter Mismatch**: The function expected `(tournamentId: number, versionId: number)` but received `(number, { schedule_version_id: number })`
2. **Response Field Mismatch**: Frontend was trying to access fields that don't exist in the backend response

---

## Solution

**File:** `frontend/src/pages/schedule/hooks/useScheduleGrid.ts`

### Changes Made

#### 1. Fixed Function Call (Line 157)

**Before:**
```typescript
const result = await buildSchedule(tournamentId, { schedule_version_id: activeVersion.id })
```

**After:**
```typescript
const result = await buildSchedule(tournamentId, activeVersion.id)
```

#### 2. Fixed Response Field Mapping (Lines 159-168)

**Before:**
```typescript
setBuildSummary({
  schedule_version_id: result.schedule_version_id,  // ❌ Not in BuildSummary type
  slots_created: result.slots_created || 0,
  matches_generated: result.matches_generated || 0,  // ❌ Wrong field name
  assignments_created: result.assignments_created || 0,  // ❌ Wrong field name
  unassigned_count: result.unassigned_count || 0,  // ❌ Wrong field name
  assignment_rate: result.assignment_rate || 0,  // ❌ Doesn't exist
  duration_ms: result.duration_ms || 0,  // ❌ Doesn't exist
})
```

**After:**
```typescript
setBuildSummary({
  slots_created: result.slots_created || 0,  // ✅ Correct
  matches_created: result.matches_created || 0,  // ✅ Correct
  matches_assigned: result.matches_assigned || 0,  // ✅ Correct
  matches_unassigned: result.matches_unassigned || 0,  // ✅ Correct
  conflicts: result.conflicts,  // ✅ Optional field
  warnings: result.warnings,  // ✅ Optional field
})
```

---

## API Signatures

### Backend Endpoint

```python
@router.post("/tournaments/{tournament_id}/schedule/versions/{version_id}/build")
def build_schedule(
    tournament_id: int,
    version_id: int,  # ← Path parameter
    session: Session = Depends(get_session)
)
```

**Returns:**
```python
class BuildScheduleResponse(BaseModel):
    schedule_version_id: int
    slots_created: int
    matches_created: int  # ← Note: matches_CREATED
    matches_assigned: int  # ← Note: matches_ASSIGNED
    matches_unassigned: int  # ← Note: matches_UNASSIGNED
    conflicts: Optional[List[dict]] = None
    warnings: Optional[List[dict]] = None
```

### Frontend API Function

```typescript
export async function buildSchedule(
  tournamentId: number,
  versionId: number  // ← Second param is just the ID
): Promise<BuildScheduleResponse>
```

### Frontend Type

```typescript
export interface BuildSummary {
  slots_created: number
  matches_created: number
  matches_assigned: number
  matches_unassigned: number
  conflicts?: { reason: string; count: number }[]
  warnings?: { message: string; count: number }[]
}
```

---

## Testing

### Verification Steps

1. **Start Backend:**
   ```bash
   cd backend
   uvicorn app.main:app --reload
   ```

2. **Start Frontend:**
   ```bash
   cd frontend
   npm run dev
   ```

3. **Test Build Schedule:**
   - Navigate to `/tournaments/:id/schedule`
   - Ensure a draft schedule version exists
   - Click "Build Schedule" button
   - **Expected:** Build completes successfully
   - **Expected:** Build summary displays with correct stats
   - **Expected:** Grid refreshes with generated slots/matches
   - **Expected:** Conflicts banner updates

### What to Look For

✅ **Success Indicators:**
- No error toast
- "Schedule built successfully" toast appears
- Build summary panel shows slot/match counts
- Grid displays slots (with day tabs)
- Conflicts banner shows assignment stats

❌ **Failure Indicators (Fixed):**
- "Input should be a valid integer" error (FIXED)
- "Failed to build schedule" error
- Empty grid after build
- Missing build summary

---

## Related Files

### Modified
- `frontend/src/pages/schedule/hooks/useScheduleGrid.ts` - Fixed API call

### Reference (No Changes)
- `frontend/src/api/client.ts` - API function signature
- `frontend/src/pages/schedule/types.ts` - BuildSummary type
- `frontend/src/pages/schedule/components/ScheduleSummaryPanel.tsx` - Display component
- `backend/app/routes/schedule.py` - Backend endpoint

---

## Impact

**Scope:** Grid V1 schedule page only

**Components Affected:**
- Build Schedule button functionality
- Build summary display
- Grid refresh after build

**Components NOT Affected:**
- Manual slot/match generation
- Assignment operations
- Other schedule page variants

---

## Status

✅ **FIXED** - Ready for testing

**Changes:** 2 lines modified in `useScheduleGrid.ts`

**Risk Level:** LOW (simple parameter fix)

**Backwards Compatible:** YES (no API changes)

---

## Additional Notes

### Why the Mismatch Occurred

The hook was likely copied from another component that used a different API signature. The `buildSchedule` function was designed to take simple parameters (tournamentId, versionId) but the hook was passing an object format used by other endpoints.

### Future Prevention

Consider adding TypeScript strict mode or ESLint rules to catch:
- Parameter type mismatches
- Missing required fields
- Accessing non-existent properties

