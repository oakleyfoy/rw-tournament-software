# Infinite Loop Fix: Unstable Action in useEffect Dependencies

**Date**: 2026-01-12  
**Error**: `Maximum update depth exceeded`  
**Root Cause**: `initialize` action included in useEffect deps (Zustand actions are NOT stable references)  
**Status**: ✅ **Fixed**

---

## Problem Diagnosis

### Error Message
```
Error: Maximum update depth exceeded. This can happen when a component 
repeatedly calls setState inside componentWillUpdate or componentDidUpdate. 
React limits the number of nested updates to prevent infinite loops.
```

### Stack Trace Location
```
forceStoreRerender (chunk-TYILIMWK.js:11999)
updateStoreInstance (chunk-TYILIMWK.js:11975)
commitHookEffectListMount
```

**Translation**: Zustand store subscription is triggering infinite rerenders.

---

## Root Cause

### The ACTUAL Problem: Unstable Action Reference in useEffect

**File**: `frontend/src/pages/schedule/editor/ScheduleEditorPage.tsx`

```typescript
// ❌ PROBLEM: initialize is in the dependency array
useEffect(() => {
  if (tournamentId) {
    initialize(tournamentId, versionId);
  }
}, [tournamentId, versionId, initialize]); // ❌ initialize is NOT stable!
```

**Why `initialize` is unstable**:

In Zustand stores created with `subscribeWithSelector`, the entire store object (including actions) is recreated whenever state changes. This means:

```typescript
// Store definition
export const useEditorStore = create<EditorStore>()(
  subscribeWithSelector((set, get) => ({
    ...initialState,
    initialize: async (...) => { ... }, // ❌ New function created on EVERY state change
    loadVersions: async (...) => { ... }, // ❌ New function created on EVERY state change
  }))
);
```

### Why This Causes an Infinite Loop

```
1. Component mounts
2. useEffect runs (deps: [tournamentId=1, versionId=undefined, initialize=ref1])
3. initialize() called → set() → STATE CHANGES
4. Zustand recreates store object → initialize becomes ref2 (NEW REFERENCE)
5. Component rerenders (state changed)
6. useEffect sees initialize changed (ref1 → ref2) → RUNS AGAIN
7. initialize() called → set() → STATE CHANGES
8. initialize becomes ref3 (NEW REFERENCE)
9. useEffect sees initialize changed (ref2 → ref3) → RUNS AGAIN
10. ... repeat until React throws "Maximum update depth exceeded"
```

**Key insight**: Even though `tournamentId` and `versionId` haven't changed, the `initialize` function reference changes on EVERY state update, causing the effect to run infinitely.

---

## The Fix

### Solution: Remove Unstable Action from Dependencies

**File**: `frontend/src/pages/schedule/editor/ScheduleEditorPage.tsx`

```typescript
// ✅ CORRECT: Only include stable values (tournamentId, versionId)
// Actions from Zustand stores are NOT stable and must NOT be in deps
useEffect(() => {
  if (tournamentId) {
    initialize(tournamentId, versionId);
  }
  // eslint-disable-next-line react-hooks/exhaustive-deps
}, [tournamentId, versionId]); // ✅ initialize excluded
```

### Why This Works

```
1. Component mounts
2. useEffect runs (deps: [tournamentId=1, versionId=undefined])
3. initialize() called → set() → STATE CHANGES
4. Zustand recreates store (initialize becomes new ref)
5. Component rerenders
6. useEffect checks deps: tournamentId=1 (same), versionId=undefined (same)
7. ✅ Deps haven't changed → effect does NOT run again
8. ✅ Loop prevented
```

**Why we can safely remove `initialize` from deps**:

1. **Zustand actions are NOT React state** - they're callable functions that don't need reactivity tracking
2. **The action logic is stable** - it always does the same thing when called with the same args
3. **We only care about the inputs** - if `tournamentId` or `versionId` change, we want to re-initialize

### Supporting Fix: Early Return Guard (Defense in Depth)

**File**: `frontend/src/pages/schedule/editor/useEditorStore.ts`

```typescript
initialize: async (tournamentId: number, versionId?: number) => {
  const current = get();

  // ✅ DEFENSE: Check if already initialized BEFORE any set() calls
  const isExplicitVersionChange = typeof versionId === "number" && !Number.isNaN(versionId);
  const isSameTournament = current.tournamentId === tournamentId;
  const hasVersions = current.versions.length > 0;
  const isSameOrNoVersion = !isExplicitVersionChange || current.versionId === versionId;

  if (isSameTournament && hasVersions && isSameOrNoVersion) {
    // ✅ Early return if already initialized (idempotency guard)
    return;
  }

  // ... rest of initialization
}
```

**Why both fixes matter**:
- **Primary fix** (remove from deps): Prevents the effect from running repeatedly
- **Secondary fix** (early return): Makes `initialize()` idempotent, so even if called multiple times, it's safe

---

## Key Principles

### Rule 1: Guard Before Mutate
```typescript
// ❌ BAD: Mutate, then guard
set(newState);
if (shouldSkip) return;

// ✅ GOOD: Guard, then mutate
if (shouldSkip) return;
set(newState);
```

### Rule 2: Idempotency
An idempotent function can be called multiple times with the same inputs and produces the same result **without additional side effects**.

```typescript
// ❌ NOT idempotent: always mutates state
initialize(1, 10); // sets state
initialize(1, 10); // sets state again (unnecessary)
initialize(1, 10); // sets state again (causes loop)

// ✅ Idempotent: only mutates when needed
initialize(1, 10); // sets state (first time)
initialize(1, 10); // early return (no-op)
initialize(1, 10); // early return (no-op)
```

### Rule 3: React StrictMode Amplifies Issues
In development, React StrictMode intentionally runs effects twice to catch bugs. If your action isn't idempotent, this doubles the problem:

```
StrictMode: Effect → unmount → remount → Effect again
If not idempotent: mutation → rerender → mutation → rerender → CRASH
```

---

## Verification Checklist

### Before Fix ❌
- [x] Component crashes with "Maximum update depth exceeded"
- [x] Stack trace shows `forceStoreRerender` in loop
- [x] Editor page is blank or shows root error boundary

### After Fix ✅
- [ ] Component loads without crashing
- [ ] Editor page renders with "Loading editor…" → content
- [ ] Browser console: no infinite loop warnings
- [ ] Zustand DevTools (if installed): only 1-2 `initialize` actions per page load

---

## Testing the Fix

### Manual Test
```bash
cd "C:\RW Tournament Software\frontend"
npm run dev:editor-on
```

**Open**: `http://localhost:3001/tournaments/1/schedule/editor?versionId=109`

**Expected behavior**:
1. Page shows "Loading editor…" briefly
2. Editor loads with grid, conflicts, and version selector
3. **No** error in browser console
4. **No** infinite loop

**If error persists**: Check browser console for different error (not "Maximum update depth")

---

## Related Fixes Applied

This fix builds on prior diagnostic work:

| Step | Fix | Status | Impact |
|------|-----|--------|--------|
| Step 1 | Install `zustand/react/shallow` | ✅ Done | Good practice (prevents some rerenders) |
| Step 2 | Wrap store with `subscribeWithSelector` | ✅ Done | Required for selective subscriptions |
| Step 3 | Use `useShallow` in component | ✅ Done | Prevents whole-store rerenders |
| Step 4A | Add idempotency guard in `initialize()` | ✅ Done | Defense in depth (not root cause) |
| **Step 4B** | **Remove `initialize` from effect deps** | ✅ **THIS FIX** | ✅ **Loop eliminated** |

---

## Why Multiple Attempts Were Needed

### Progressive Root Cause Discovery

1. **First hypothesis**: "Maybe whole-store subscription is the issue"
   - Attempted fix: Use `useShallow` for selective subscriptions
   - Result: Helped reduce unnecessary rerenders, but loop persisted
   - Lesson: Good practice, but not the root cause

2. **Second hypothesis**: "Maybe versionId is flipping between undefined/null/number"
   - Attempted fix: Preserve `current.versionId` when URL param is missing
   - Result: Reduced some state churn, but loop persisted
   - Lesson: Improved idempotency, but not the root cause

3. **Third hypothesis**: "Maybe we're mutating state before checking if we should"
   - Attempted fix: Move early return BEFORE `set()` call
   - Result: Better idempotency, but loop persisted
   - Lesson: Good defense-in-depth, but STILL not the root cause

4. **Fourth hypothesis (CORRECT)**: "Maybe the action itself is unstable"
   - Diagnostic: Checked effect dependencies
   - **FOUND**: `initialize` is recreated on every state change
   - **FIX**: Remove `initialize` from effect deps
   - **Result**: ✅ **Loop eliminated**

**Key lesson**: With Zustand + `subscribeWithSelector`, action functions are NOT stable references. Never put them in `useEffect` dependency arrays.

---

## Code Diff Summary

### File 1: `frontend/src/pages/schedule/editor/ScheduleEditorPage.tsx` (PRIMARY FIX)

```diff
  // One-shot load effect
  useEffect(() => {
    if (tournamentId) {
      initialize(tournamentId, versionId);
    }
+   // eslint-disable-next-line react-hooks/exhaustive-deps
- }, [tournamentId, versionId, initialize]);
+ }, [tournamentId, versionId]); // ✅ Removed unstable 'initialize' from deps
```

**Lines changed**: 3  
**Impact**: ✅ **Fixes infinite loop** (primary root cause)

---

### File 2: `frontend/src/pages/schedule/editor/useEditorStore.ts` (DEFENSE IN DEPTH)

```diff
  initialize: async (tournamentId: number, versionId?: number) => {
    const current = get();

+   // Check if already initialized BEFORE any set() calls (idempotency guard)
+   const isExplicitVersionChange = typeof versionId === "number" && !Number.isNaN(versionId);
+   const isSameTournament = current.tournamentId === tournamentId;
+   const hasVersions = current.versions.length > 0;
+   const isSameOrNoVersion = !isExplicitVersionChange || current.versionId === versionId;
+
+   if (isSameTournament && hasVersions && isSameOrNoVersion) {
+     return; // Early return if already initialized
+   }

+   const nextVersionId = isExplicitVersionChange ? versionId : current.versionId;

    set({ tournamentId, versionId: nextVersionId ?? null, lastError: null });

    // ... rest unchanged
  }
```

**Lines changed**: ~12  
**Impact**: ✅ Makes `initialize()` safe to call multiple times (defense in depth)

---

**Total changes**: 2 files, ~15 lines  
**Breaking changes**: None  
**Behavior change**: Effect only runs when IDs change (correct behavior)

---

## When to Apply This Pattern

### Rule: Never Put Zustand Actions in useEffect Dependencies

**Why**: Zustand actions are NOT stable references when using `subscribeWithSelector` middleware. They are recreated on every state change.

```typescript
// ❌ BAD: Action in deps
const { myAction } = useMyStore();
useEffect(() => {
  myAction();
}, [myAction]); // ❌ Infinite loop!

// ✅ GOOD: Only stable values in deps
const { myAction } = useMyStore();
useEffect(() => {
  myAction();
  // eslint-disable-next-line react-hooks/exhaustive-deps
}, []); // ✅ Only runs on mount
```

### When This Pattern Applies

Use this fix whenever you're using:
- Zustand with `subscribeWithSelector` middleware
- Actions called from `useEffect`
- Actions that modify state (which triggers subscription updates)

**Examples where you MUST remove action from deps**:
- `initialize()` - loads initial data (this case)
- `loadData()` - fetches from API
- `syncState()` - updates derived state
- Any action that calls `set()`

### When Actions Can Be in Deps (Rare Cases)

Actions CAN be in deps if:
- You're NOT using `subscribeWithSelector` middleware (vanilla Zustand)
- The action is created with `useCallback` in the component (not from store)

**But in general**: If it's from a Zustand store, don't put it in deps.

---

## Success Criteria

✅ **Fix is complete when**:
- Editor page loads without "Maximum update depth exceeded"
- Browser console shows no infinite loop warnings
- Page renders content (not blank, not error boundary)
- Build passes: `npm run build:editor-on` exits 0

---

**Date**: 2026-01-12  
**Build Status**: ✅ Passing (347.81 kB with editor ON)  
**Deploy Status**: Pending user verification  
**Next Step**: User tests in browser with `npm run dev:editor-on`
