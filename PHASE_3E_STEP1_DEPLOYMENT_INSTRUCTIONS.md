# Phase 3E Step 1: Limited Audience Deployment Instructions

**Objective**: Deploy Manual Schedule Editor UI to limited audience with feature flag control.

**Status**: ✅ **Code Ready for Deployment**

---

## Feature Flag Implementation Summary

### Files Modified
1. ✅ `frontend/src/config/featureFlags.ts` (NEW)
2. ✅ `frontend/src/pages/schedule/SchedulePageGridV1.tsx` (gated button)
3. ✅ `frontend/src/pages/schedule/editor/ScheduleEditorPage.tsx` (gated route)

### Build Status
- ✅ TypeScript compilation: PASS
- ✅ Production build: 344.82 kB (gzipped: 100.95 kB)
- ✅ Feature flag tested: Button hidden when flag disabled

---

## Deployment Options

### **Option 1: Environment Variable (Recommended)**

Deploy the same build to different environments with different environment variables.

#### Environments Setup

**Limited Audience Environment** (staging/beta/internal):
```bash
# .env.production.limited
VITE_ENABLE_MANUAL_EDITOR=true
```

**General Audience Environment** (production):
```bash
# .env.production
VITE_ENABLE_MANUAL_EDITOR=false
# OR leave unset (defaults to false)
```

#### Build Commands

**For Limited Audience**:
```bash
cd "C:\RW Tournament Software\frontend"

# Set environment variable
$env:VITE_ENABLE_MANUAL_EDITOR="true"

# Build with flag enabled
npm run build

# Deploy dist/ to limited audience environment
# (staging.yourdomain.com or beta.yourdomain.com)
```

**For General Audience** (when ready):
```bash
cd "C:\RW Tournament Software\frontend"

# Unset or set to false
$env:VITE_ENABLE_MANUAL_EDITOR="false"

# Build with flag disabled
npm run build

# Deploy dist/ to production environment
```

---

### **Option 2: Separate Build Artifacts**

Create two separate builds and deploy to different URLs.

**Limited Audience Build**:
```bash
cd "C:\RW Tournament Software\frontend"
$env:VITE_ENABLE_MANUAL_EDITOR="true"
npm run build
# Rename dist/ to dist-limited/
mv dist dist-limited
```

**General Audience Build**:
```bash
cd "C:\RW Tournament Software\frontend"
$env:VITE_ENABLE_MANUAL_EDITOR="false"
npm run build
# Keep as dist/
```

Deploy `dist-limited/` to: `beta.yourdomain.com` or `staging.yourdomain.com`  
Deploy `dist/` to: `www.yourdomain.com` or `app.yourdomain.com`

---

### **Option 3: Same Build + Access Control Layer**

Deploy the same build everywhere, but restrict access to `/tournaments/:id/schedule/editor` route at the hosting layer.

**Build with flag enabled**:
```bash
cd "C:\RW Tournament Software\frontend"
$env:VITE_ENABLE_MANUAL_EDITOR="true"
npm run build
```

**Add access control at web server level** (nginx example):
```nginx
# Restrict editor route to specific IPs or basic auth
location ~ ^/tournaments/[0-9]+/schedule/editor {
    # Option A: IP allowlist
    allow 192.168.1.0/24;
    deny all;
    
    # Option B: Basic auth
    auth_basic "Limited Access";
    auth_basic_user_file /etc/nginx/.htpasswd;
}
```

---

## Backend Deployment (No Changes Required)

**Phase 3D endpoints are already deployed** (from previous phase).

Verify these endpoints are live:
- `GET /api/tournaments/{id}/schedule/versions`
- `GET /api/tournaments/{id}/schedule/grid`
- `GET /api/tournaments/{id}/schedule/conflicts`
- `PATCH /api/tournaments/{id}/schedule/assignments/{assignmentId}`
- `POST /api/tournaments/{id}/schedule/versions/{versionId}/clone`

**No backend code changes in Phase 3E.**

---

## Step 1C: Production Smoke Test (10 Minutes)

### Prerequisites
- [ ] Backend is running and accessible
- [ ] Frontend build deployed with `VITE_ENABLE_MANUAL_EDITOR=true`
- [ ] At least one tournament with a draft schedule version exists
- [ ] Browser DevTools open (Console + Network tabs)

### Smoke Test Checklist

#### Test 1: Normal Schedule Page (Flag Verification)
1. Navigate to: `/tournaments/{id}/schedule`
2. **Expected**:
   - ✅ Page loads without errors
   - ✅ Schedule grid displays normally
   - ✅ **"✏️ Open Manual Schedule Editor"** button is visible (purple button)
3. **Check Console**: No errors
4. **If button is NOT visible**: Flag is disabled (check environment variable)

#### Test 2: Editor Route Loads
1. Click **"✏️ Open Manual Schedule Editor"** button
2. **Expected**:
   - ✅ Editor page loads with 3-column layout
   - ✅ Match Queue (left), Grid (center), Conflicts (right) all visible
   - ✅ Version selector shows versions
3. **Check Console**: No errors
4. **Check Network Tab**: 
   - ✅ `GET /schedule/versions` returns 200
   - ✅ `GET /schedule/grid` returns 200
   - ✅ `GET /schedule/conflicts` returns 200

#### Test 3: Draft Version - Move Assignment (Success Case)
1. Ensure a **draft version** is selected (dropdown shows "draft")
2. Find an assigned match in the grid (blue card)
3. Drag the match to an **empty slot** (green background)
4. **Expected**:
   - ✅ Match card shows "wait" cursor while saving
   - ✅ Grid and conflicts refresh automatically
   - ✅ Match appears in new slot
5. **Check Network Tab**:
   - ✅ `PATCH /schedule/assignments/{id}` returns 200
   - ✅ `GET /schedule/grid` called after PATCH
   - ✅ `GET /schedule/conflicts` called after PATCH
6. **Check Console**: No errors

#### Test 4: Final Version - Read-Only (Rejection Case)
1. Switch to a **final version** (or finalize a draft first)
2. **Expected**:
   - ✅ Banner appears: "Read-only (Final). Clone to Draft to edit."
   - ✅ Drag/drop is disabled (no cursor change on hover)
3. Attempt to drag a match (should not work)
4. **Expected**:
   - ✅ Drag is blocked (client-side prevention)
   - ✅ No PATCH request sent
5. **Check Console**: No errors

#### Test 5: Clone to Draft Workflow
1. While viewing a final version, click **"Clone to Draft"**
2. **Expected**:
   - ✅ Button shows "Cloning..." briefly
   - ✅ New draft version is created
   - ✅ Editor automatically switches to new draft
   - ✅ Grid and conflicts reload
   - ✅ Drag/drop is now enabled
3. **Check Network Tab**:
   - ✅ `POST /schedule/versions/{id}/clone` returns 200
   - ✅ `GET /schedule/versions` called after clone
   - ✅ `GET /schedule/grid` and `/conflicts` called for new version
4. **Check Console**: No errors

#### Test 6: Conflicts Panel Updates
1. Make a move that creates a conflict (e.g., move a match out of order)
2. **Expected**:
   - ✅ Conflicts panel updates automatically
   - ✅ Ordering violations appear (if applicable)
   - ✅ Unassigned count updates
3. Click **"Refresh Conflicts"** button
4. **Expected**:
   - ✅ Conflicts refetch successfully
   - ✅ Panel updates with latest data
5. **Check Console**: No errors

---

## Smoke Test Results Template

Copy this and fill in after testing:

```
SMOKE TEST RESULTS
Date: ___________
Tester: ___________
Environment: ___________

[ ] Test 1: Schedule page loads, editor button visible
[ ] Test 2: Editor route renders with 3-column layout
[ ] Test 3: Draft version - move assignment succeeds
[ ] Test 4: Final version - drag/drop disabled
[ ] Test 5: Clone to draft workflow completes
[ ] Test 6: Conflicts panel updates after move

Console Errors: [ ] None  [ ] Present (describe below)
Network Errors: [ ] None  [ ] Present (describe below)
Backend Errors: [ ] None  [ ] Present (describe below)

Additional Notes:
___________________________________________________________
___________________________________________________________

Status: [ ] PASS (all tests green)  [ ] FAIL (issues found)
```

---

## Rollback Procedure

### If Smoke Tests Fail

**Option A: Disable Feature Flag**
```bash
# Rebuild with flag disabled
cd "C:\RW Tournament Software\frontend"
$env:VITE_ENABLE_MANUAL_EDITOR="false"
npm run build

# Redeploy dist/
```

**Option B: Revert Frontend Code**
```bash
cd "C:\RW Tournament Software"
git revert HEAD --no-commit
git commit -m "Rollback: Disable Phase 3E Manual Editor"

cd frontend
npm run build
# Redeploy dist/
```

**Option C: Route-Level Block** (Emergency)
At web server level, block the editor route:
```nginx
location ~ ^/tournaments/[0-9]+/schedule/editor {
    return 503;
}
```

### Verify Rollback
1. Navigate to `/tournaments/{id}/schedule`
2. Confirm editor button is NOT visible
3. Try direct URL: `/tournaments/{id}/schedule/editor`
4. Confirm editor shows "This feature is currently disabled" message

---

## Exit Criteria for Step 1

**Report back with ONE of the following:**

### ✅ Success
```
Step 1 approved — deploy is live and smoke tests passed

Environment: [staging/beta/internal URL]
All 6 smoke tests: PASS
Console errors: None
Network errors: None
Backend errors: None
```

### ❌ Blocked
```
Step 1 blocked — here are the failing checks and errors

Failed Tests:
- [ ] Test X: Description of failure
- [ ] Test Y: Description of failure

Console Errors:
[paste errors]

Network Errors:
[paste failed requests + status codes]

Backend Errors:
[paste backend logs if applicable]

Rollback Status: [completed/in-progress/pending]
```

---

## Post-Deployment Monitoring (24 Hours)

After smoke tests pass, monitor for 24 hours:

**Metrics to Track**:
- [ ] Zero JavaScript errors in browser console
- [ ] Zero 500 errors from PATCH endpoint
- [ ] PATCH success rate > 95%
- [ ] No user-reported crashes
- [ ] Backend logs show no unexpected exceptions

**If any issues arise**:
1. Document the issue
2. Execute rollback procedure
3. Report: "Step 1 blocked — [issue description]"

---

## Who to Involve

**For Deployment**:
- Engineering (build + deploy)
- DevOps (environment config + hosting)

**For Smoke Tests**:
- Engineering only (technical validation)

**NOT involved yet**:
- ❌ UX team (no feedback yet)
- ❌ Product team (no usability testing yet)
- ❌ End users (limited audience only)

---

## Summary

**What is being deployed**:
- Manual Schedule Editor UI (Phase 3E)
- Gated by `VITE_ENABLE_MANUAL_EDITOR` environment variable
- Zero backend changes

**What is NOT being deployed**:
- No UX iteration
- No design changes
- No new backend features

**Success = Smoke tests pass + zero errors for 24 hours**

**Failure = Any test fails OR errors in console/network/backend**

---

**Next Step**: After you confirm "Step 1 approved", we proceed to Step 2 (deep testing + UX evaluation).

**Do NOT proceed to Step 2 until Step 1 is approved.**

