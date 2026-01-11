# Grid Population V1 - Verification Guide

## Quick Verification Steps

### Backend Verification

**1. Test Grid Endpoint**

```bash
cd backend
python -m pytest tests/test_grid_endpoint.py -v
```

**Expected:** All 13 tests pass ✅

**2. Live API Test**

```bash
# Start server (if not running)
cd backend
uvicorn app.main:app --reload

# In another terminal:
curl "http://localhost:8000/api/tournaments/1/schedule/grid?schedule_version_id=1"
```

**Expected:** HTTP 200 with JSON payload containing slots, assignments, matches, conflicts_summary

---

### Frontend Verification

**3. Start Frontend**

```bash
cd frontend
npm run dev
```

**4. Navigate to Schedule Page**

Open browser to: `http://localhost:3000/tournaments/1/schedule`

**Expected:** Schedule page loads using Grid V1 layout

---

## Manual Test Scenarios

### Scenario 1: Zero Matches Generated

**Steps:**
1. Navigate to tournament with draft schedule version
2. Ensure no matches have been generated yet

**Expected:**
- ✅ Page loads without errors
- ✅ Shows "No slots generated yet" message
- ✅ No 500 errors or "Failed to fetch"
- ✅ Conflicts banner shows 0 / 0 matches

---

### Scenario 2: Matches Generated But Unassigned

**Steps:**
1. Navigate to tournament with draft version
2. Click "Build Schedule" button
3. Wait for build to complete

**Expected:**
- ✅ Build summary appears showing slots/matches created
- ✅ Conflicts banner shows:
  - Total matches count
  - 0 assigned
  - Assignment rate: 0%
- ✅ Grid displays empty slots with "Open" label
- ✅ Day tabs appear for each tournament day
- ✅ Time rows and court columns visible

---

### Scenario 3: Matches Assigned (Auto-Assign V1)

**Steps:**
1. Navigate to tournament with built schedule
2. Ensure Auto-Assign V1 has run (or build triggers it automatically)
3. Observe grid

**Expected:**
- ✅ Conflicts banner shows:
  - X / Y matches assigned
  - Assignment rate > 0%
- ✅ Grid displays match cards in assigned slots:
  - Stage label (e.g., "WF", "MAIN")
  - Round index (e.g., "R1", "R2")
  - Sequence (e.g., "#1", "#2")
  - Duration (e.g., "120min")
  - Match code (e.g., "MIX_MIX_POOL1_RR_01")
- ✅ Unassigned slots still show "Open"
- ✅ Match cards have blue background (#e3f2fd)
- ✅ Open slots have white background

---

### Scenario 4: Sorting Stability

**Steps:**
1. Load schedule page
2. Note the order of slots in grid
3. Switch day tabs back and forth
4. Refresh browser
5. Check order again

**Expected:**
- ✅ Same day ordering every time
- ✅ Same court ordering (left to right)
- ✅ Same time ordering (top to bottom)
- ✅ No random shuffling or reordering

---

### Scenario 5: Read-Only Mode (Finalized Schedule)

**Steps:**
1. Navigate to tournament
2. Finalize the draft version
3. View the schedule

**Expected:**
- ✅ Grid displays normally
- ✅ Slot clicks do nothing (read-only)
- ✅ No assignment UI appears
- ✅ Version selector shows "Final" status

---

### Scenario 6: No Team References

**Steps:**
1. Inspect grid payload in browser DevTools Network tab
2. Look at matches array
3. Look at assignments array
4. Look at slots array

**Expected:**
- ✅ No fields named: team_a_id, team_b_id, team_a_name, team_b_name
- ✅ No home_team or away_team fields
- ✅ Placeholders like "Team 1 vs Team 2" are OK (they're placeholders)
- ✅ Match cards show stage/round/sequence, not team names

---

## Browser Console Checks

### No Errors Expected

Open DevTools Console and verify:

- ✅ No "Failed to fetch" errors
- ✅ No 500 Internal Server Error
- ✅ No React rendering errors
- ✅ No "Cannot read property of undefined" errors

### Network Tab Verification

1. Open DevTools → Network tab
2. Load schedule page
3. Find the `grid?schedule_version_id=X` request

**Verify:**
- ✅ Status: 200 OK
- ✅ Response time: < 500ms (for typical schedules)
- ✅ Response size: reasonable (depends on schedule size)
- ✅ Only ONE request to grid endpoint (no cascading calls)

---

## Performance Expectations

### Backend
- **Response Time:** < 200ms for 300 slots
- **Memory:** Minimal (simple queries and counting)
- **CPU:** Low (no complex computation)

### Frontend
- **Initial Render:** < 500ms
- **Day Tab Switch:** < 100ms
- **Browser Memory:** < 100MB for grid component

---

## Troubleshooting

### Issue: "No slots generated yet" message

**Cause:** Schedule version has no slots
**Solution:** Click "Build Schedule" button

### Issue: 500 Internal Server Error

**Possible Causes:**
1. Database migration not run (missing `consolation_tier` or `placement_type` columns)
2. Invalid schedule_version_id parameter
3. Database connection issue

**Solution:**
```bash
cd backend
alembic upgrade head
```

### Issue: Grid not loading (spinning forever)

**Possible Causes:**
1. Backend not running
2. CORS issue
3. Network error

**Solution:**
- Check backend is running on port 8000
- Check frontend can reach http://localhost:8000
- Check browser console for CORS errors

### Issue: Empty grid (no slots visible)

**Possible Causes:**
1. No active version selected
2. Version has no slots
3. Data fetch failed silently

**Solution:**
- Check version selector has an active version
- Check browser DevTools Network tab for failed requests
- Check gridData is not null in React DevTools

---

## API Endpoint Test with cURL

### Basic Request
```bash
curl "http://localhost:8000/api/tournaments/1/schedule/grid?schedule_version_id=1"
```

### With Pretty Print (requires jq)
```bash
curl "http://localhost:8000/api/tournaments/1/schedule/grid?schedule_version_id=1" | jq .
```

### Check Response Structure
```bash
curl "http://localhost:8000/api/tournaments/1/schedule/grid?schedule_version_id=1" | jq 'keys'
```

**Expected Output:**
```json
[
  "assignments",
  "conflicts_summary",
  "matches",
  "slots"
]
```

### Count Items
```bash
curl -s "http://localhost:8000/api/tournaments/1/schedule/grid?schedule_version_id=1" | jq '{
  slots: (.slots | length),
  matches: (.matches | length),
  assignments: (.assignments | length),
  assignment_rate: .conflicts_summary.assignment_rate
}'
```

---

## Success Criteria Checklist

Use this checklist to verify Grid Population V1 is working correctly:

### Backend
- [ ] GET /schedule/grid endpoint returns 200
- [ ] Response includes all 4 sections (slots, assignments, matches, conflicts_summary)
- [ ] Works with zero assignments
- [ ] Works with zero matches
- [ ] Sorts deterministically (day → time → court)
- [ ] Read-only (no DB changes)
- [ ] No team references in response
- [ ] All 13 tests pass

### Frontend
- [ ] Schedule page loads without errors
- [ ] Day tabs display and are clickable
- [ ] Time rows display in ascending order
- [ ] Court columns display in consistent order
- [ ] Assigned slots show match cards
- [ ] Unassigned slots show "Open"
- [ ] Conflicts banner displays correct stats
- [ ] Spillover warning appears when appropriate
- [ ] Read-only mode prevents clicks on finalized schedules
- [ ] No team names displayed anywhere

### Integration
- [ ] Build Schedule button works
- [ ] Grid refreshes after build
- [ ] Conflicts banner updates after build
- [ ] Version selector works
- [ ] Create Draft works
- [ ] Finalize works
- [ ] Clone works

---

## Known Limitations (V1)

These are intentional limitations of V1:

1. **No team names** - Only placeholder text and match codes
2. **No interactive assignment** - Use separate assignment UI (out of scope for V1)
3. **No drag-and-drop** - Manual assignment via drawer/panel only
4. **No filtering** - Shows all matches/slots (filtering is future enhancement)
5. **No multi-day view** - One day tab at a time
6. **No print layout** - Grid is screen-optimized only

---

## Next Steps (After Verification)

If all checks pass:

1. ✅ Mark Grid Population V1 as **COMPLETE**
2. ✅ Document any environment-specific notes
3. ✅ Update deployment checklist if needed
4. ✅ Consider performance monitoring in production
5. ✅ Plan V2 enhancements (drag-and-drop, etc.)

---

## Support

For issues or questions:
- Check backend logs: `backend/` (uvicorn output)
- Check frontend console: Browser DevTools
- Review test output: `pytest -v`
- Check API docs: http://localhost:8000/docs

