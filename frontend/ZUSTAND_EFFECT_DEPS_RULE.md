# Zustand + useEffect Dependency Rule

**TL;DR**: Never put Zustand actions in `useEffect` dependency arrays when using `subscribeWithSelector` middleware.

---

## The Problem

```typescript
// ❌ THIS CAUSES INFINITE LOOPS
const { initialize } = useEditorStore();

useEffect(() => {
  initialize(tournamentId);
}, [tournamentId, initialize]); // ❌ 'initialize' is unstable!
```

**Why it loops**:
1. Effect runs → `initialize()` called → `set()` updates state
2. State change → Zustand recreates store object (including actions)
3. `initialize` gets new reference → Effect deps changed
4. Effect runs again → repeat until crash

---

## The Fix

```typescript
// ✅ CORRECT: Only stable values in deps
const { initialize } = useEditorStore();

useEffect(() => {
  initialize(tournamentId);
  // eslint-disable-next-line react-hooks/exhaustive-deps
}, [tournamentId]); // ✅ Action excluded
```

**Why it works**:
- `tournamentId` is stable (comes from URL params)
- Effect only runs when `tournamentId` changes (correct behavior)
- `initialize` reference changing doesn't trigger effect

---

## Why Zustand Actions Are Unstable

**With `subscribeWithSelector` middleware**:

```typescript
export const useStore = create<Store>()(
  subscribeWithSelector((set, get) => ({
    count: 0,
    increment: () => set({ count: get().count + 1 }), // ← New function on EVERY state change
  }))
);
```

Every time `set()` is called, the ENTIRE store object (including `increment`) is recreated. This means the `increment` reference changes on every state update.

**Without middleware** (vanilla Zustand):
```typescript
export const useStore = create<Store>((set, get) => ({
  count: 0,
  increment: () => set({ count: get().count + 1 }), // ← Stable reference
}));
```

Actions are stable, but you lose selective subscription features.

---

## Quick Decision Tree

```
Do you have a Zustand action in a useEffect dep array?
  ├─ Yes → Is it from a store with subscribeWithSelector?
  │         ├─ Yes → ❌ REMOVE IT (will cause loop)
  │         └─ No → ✅ OK (vanilla Zustand actions are stable)
  └─ No → ✅ You're good
```

---

## Real-World Example (From This Project)

**Before** (infinite loop):
```typescript
const { initialize } = useEditorStore(
  useShallow((s) => ({
    initialize: s.initialize,
    // ... other state
  }))
);

useEffect(() => {
  if (tournamentId) {
    initialize(tournamentId, versionId);
  }
}, [tournamentId, versionId, initialize]); // ❌ Loop!
```

**After** (fixed):
```typescript
const { initialize } = useEditorStore(
  useShallow((s) => ({
    initialize: s.initialize,
    // ... other state
  }))
);

useEffect(() => {
  if (tournamentId) {
    initialize(tournamentId, versionId);
  }
  // eslint-disable-next-line react-hooks/exhaustive-deps
}, [tournamentId, versionId]); // ✅ Stable values only
```

---

## FAQ

### Q: Won't eslint complain?

**A**: Yes. Use `// eslint-disable-next-line react-hooks/exhaustive-deps` with a comment explaining why.

### Q: Is this safe?

**A**: Yes. Zustand actions are "stable" in the sense that they always do the same thing. The reference changing is an implementation detail, not a semantic change.

### Q: What about other state management libraries?

**A**: 
- **Redux**: Actions are plain objects/functions, usually stable
- **MobX**: Similar issue with observables
- **Recoil**: Selectors are stable, setters might not be
- **Jotai**: Atoms are stable

**Rule of thumb**: If it's a "setter" or "action" from a state library, test if it's stable before including in deps.

---

## How to Test if an Action is Stable

```typescript
const { myAction } = useMyStore();

useEffect(() => {
  console.log('myAction reference:', myAction);
}, [myAction]);

// If console logs spam on every state change → NOT STABLE
// If console logs only once → STABLE
```

---

## Related Files

- `frontend/src/pages/schedule/editor/ScheduleEditorPage.tsx` - Fixed effect deps
- `frontend/src/pages/schedule/editor/useEditorStore.ts` - Store with subscribeWithSelector
- `frontend/INFINITE_LOOP_FIX.md` - Detailed debugging story

---

**Date**: 2026-01-12  
**Context**: Phase 3E Manual Schedule Editor  
**Issue**: Maximum update depth exceeded  
**Resolution**: Remove `initialize` from effect dependencies

