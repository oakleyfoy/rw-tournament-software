# Phase 3E Step 1: Smoke Test Quick Reference

**Duration**: 10 minutes  
**Audience**: Engineering only  
**Goal**: Technical validation, not UX testing

---

## ✅ Smoke Test Checklist

### Before You Start
- [ ] Backend running and accessible
- [ ] Frontend deployed with `VITE_ENABLE_MANUAL_EDITOR=true`
- [ ] Browser DevTools open (Console + Network tabs)
- [ ] At least one tournament with draft schedule version

---

### Test 1: Editor Button Visible
**Navigate to**: `/tournaments/{id}/schedule`

- [ ] Page loads without errors
- [ ] Schedule grid displays
- [ ] **Purple "✏️ Open Manual Schedule Editor" button visible**
- [ ] No console errors

**If button NOT visible** → Flag is disabled, check environment variable

---

### Test 2: Editor Loads
**Click**: "✏️ Open Manual Schedule Editor" button

- [ ] Editor page loads
- [ ] 3 panels visible: Match Queue | Grid | Conflicts
- [ ] Version selector populated
- [ ] No console errors

**Check Network Tab**:
- [ ] `GET /schedule/versions` → 200
- [ ] `GET /schedule/grid` → 200
- [ ] `GET /schedule/conflicts` → 200

---

### Test 3: Drag Works (Draft)
**Ensure**: Draft version selected

1. Find assigned match in grid (blue card)
2. Drag to empty slot (green background)
3. Drop

- [ ] Match shows "wait" cursor
- [ ] Grid refreshes
- [ ] Match appears in new slot
- [ ] No console errors

**Check Network Tab**:
- [ ] `PATCH /schedule/assignments/{id}` → 200
- [ ] `GET /schedule/grid` called after PATCH
- [ ] `GET /schedule/conflicts` called after PATCH

---

### Test 4: Final Read-Only
**Switch to**: Final version (or finalize a draft)

- [ ] Banner: "Read-only (Final). Clone to Draft to edit."
- [ ] Drag/drop disabled (no cursor change)
- [ ] Attempt drag → blocked (no PATCH sent)
- [ ] No console errors

---

### Test 5: Clone to Draft
**While on final version**: Click "Clone to Draft"

- [ ] Button shows "Cloning..."
- [ ] New draft created
- [ ] Editor switches to new draft
- [ ] Grid/conflicts reload
- [ ] Drag/drop now enabled
- [ ] No console errors

**Check Network Tab**:
- [ ] `POST /schedule/versions/{id}/clone` → 200
- [ ] `GET /schedule/versions` → 200
- [ ] `GET /schedule/grid` → 200
- [ ] `GET /schedule/conflicts` → 200

---

### Test 6: Conflicts Update
**Make a move**, then check conflicts panel

- [ ] Conflicts panel updates automatically
- [ ] Summary counts update
- [ ] Click "Refresh Conflicts" → data refreshes
- [ ] No console errors

---

## ⚠️ Stop Conditions

**STOP and rollback if you see ANY of**:
- Console errors (red text in DevTools Console)
- Network errors (4xx/5xx responses)
- Backend exceptions in logs
- Drag/drop not working at all
- Editor page crash/blank screen

---

## 📊 Results Template

```
[ ] All 6 tests PASS
[ ] Console errors: None
[ ] Network errors: None
[ ] Backend errors: None

Status: _______________ (PASS/FAIL)
Date: _______________
Tester: _______________
Environment: _______________
```

---

## 🚨 If Any Test Fails

**DO NOT CONTINUE** to Step 2.

1. Document failure details
2. Execute rollback (disable flag or revert code)
3. Report: "Step 1 blocked — [failure details]"

---

## ✅ If All Tests Pass

**Report**:
```
Step 1 approved — deploy is live and smoke tests passed

Environment: [URL]
All 6 smoke tests: PASS
Console/Network/Backend errors: None
Ready for 24-hour monitoring
```

**Then**: Monitor for 24 hours (zero errors = proceed to Step 2)

---

**Do NOT do deep UX testing until Step 1 is approved and stable for 24 hours.**

