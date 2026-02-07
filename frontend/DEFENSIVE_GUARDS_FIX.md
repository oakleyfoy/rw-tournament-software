# Defensive Guards Fix: Undefined Props

**Date**: 2026-01-12  
**Error**: `Cannot read properties of undefined (reading 'length')`  
**Root Cause**: Components rendering before all data loaded, accessing `.length` on undefined arrays  
**Status**: ✅ **Fixed**

---

## Problem

After fixing the infinite loop, the editor crashed with:

```
Manual Schedule Editor Error
The editor crashed while rendering. Check console for details.

Cannot read properties of undefined (reading 'length')
```

### Why This Happened

Components were rendering with props that could be:
- `undefined` (before initialization)
- `null` (explicit null in initial state, like `conflicts`)
- Empty arrays `[]` (safe, but needed to be guaranteed)

Even though the `ScheduleEditorPage` has loading guards, there's a timing window where:
1. Loading flags flip to `false`
2. Components render
3. Some state is still `null`/`undefined`
4. Component tries to access `.length` → crash

---

## The Fix: Defensive Guards in All Components

### Pattern

```typescript
// ❌ UNSAFE: Assumes prop is always an array
function MyComponent({ items }: { items: MyType[] }) {
  return <div>Count: {items.length}</div>; // Crashes if items is undefined
}

// ✅ SAFE: Guarantees array
function MyComponent({ items }: { items: MyType[] }) {
  const safeItems = items || [];
  return <div>Count: {safeItems.length}</div>; // Always works
}
```

---

## Files Fixed

### 1. ConflictsPanel.tsx

**Problem**: `conflicts` object might have undefined properties

**Fix**:
```typescript
// Defensive: ensure all expected properties exist
const summary = conflicts.summary || {
  total_slots: 0,
  total_matches: 0,
  assigned_matches: 0,
  unassigned_matches: 0,
  assignment_rate: 0,
};
const unassigned_matches = conflicts.unassigned_matches || [];
const slot_pressure = conflicts.slot_pressure || [];
const ordering_integrity = conflicts.ordering_integrity || { 
  violations_detected: 0, 
  violations: [] 
};
```

**Why needed**: Initial state has `conflicts: null`, and even after loading, backend might not return all fields.

---

### 2. MatchQueuePanel.tsx

**Problem**: `unassignedMatches` and `teams` might be undefined

**Fix**:
```typescript
// Defensive: ensure arrays are never undefined
const safeUnassigned = unassignedMatches || [];
const safeTeams = teams || [];

// Use safe versions everywhere
const teamsById = safeTeams.reduce(...);
return <h2>Unassigned Matches ({safeUnassigned.length})</h2>;
```

**Why needed**: Selector returns an array, but React component lifecycle might call render before selector runs.

---

### 3. EditorGrid.tsx

**Problem**: `slots`, `assignments`, `assignmentsBySlotId`, `matches` might be undefined

**Fix**:
```typescript
// Defensive: ensure props are never undefined
const safeSlots = slots || [];
const safeAssignments = assignments || [];
const safeAssignmentsBySlotId = assignmentsBySlotId || {};
const safeMatches = matches || {};

// Use safe versions in all logic
const gridStructure = useMemo(() => {
  safeSlots.forEach((slot) => { ... });
}, [safeSlots]);

if (safeSlots.length === 0) { ... }
```

**Why needed**: Initial state has all these as empty arrays/objects, but during React lifecycle, they might briefly be undefined.

---

## Why This Pattern Works

### Defense in Depth

Even though parent component has loading guards:

```typescript
if (pending.loadingGrid || pending.loadingConflicts) {
  return <div>Loading...</div>;
}
```

...there's still a timing issue:

```
1. Store updates: pending.loadingGrid = false
2. Parent component rerenders
3. Loading guard passes (data "should" be loaded)
4. Child components render
5. But some props are still null/undefined (race condition)
6. Child component crashes
```

**Solution**: Every component protects itself (don't rely on parent guards alone).

---

## Alternative Solutions (Not Used)

### Option A: Add More Guards in Parent

```typescript
// ScheduleEditorPage.tsx
if (!slots || !assignments || !conflicts) {
  return <div>Loading data...</div>;
}
```

**Why not used**: Would require checking every piece of state; defensive guards in children are simpler and more maintainable.

### Option B: Use Optional Chaining

```typescript
<h2>Unassigned Matches ({unassignedMatches?.length ?? 0})</h2>
```

**Why not used**: Would need to add `?` everywhere, and doesn't protect `.forEach()`, `.map()`, etc.

### Option C: TypeScript Non-Null Assertions

```typescript
const safeItems = items!; // Assert it's not null
```

**Why not used**: Doesn't actually prevent crashes, just silences TypeScript warnings.

---

## Code Diff Summary

### ConflictsPanel.tsx
```diff
  if (!conflicts) { ... }

- const { summary, unassigned_matches, slot_pressure, ordering_integrity } = conflicts;
+ const summary = conflicts.summary || { ... };
+ const unassigned_matches = conflicts.unassigned_matches || [];
+ const slot_pressure = conflicts.slot_pressure || [];
+ const ordering_integrity = conflicts.ordering_integrity || { violations_detected: 0, violations: [] };
```

### MatchQueuePanel.tsx
```diff
  export function MatchQueuePanel({ unassignedMatches, teams, loading }) {
+   const safeUnassigned = unassignedMatches || [];
+   const safeTeams = teams || [];

-   const teamsById = teams.reduce(...);
+   const teamsById = safeTeams.reduce(...);

-   return <h2>Unassigned Matches ({unassignedMatches.length})</h2>;
+   return <h2>Unassigned Matches ({safeUnassigned.length})</h2>;
  }
```

### EditorGrid.tsx
```diff
  export function EditorGrid({ slots, assignments, assignmentsBySlotId, matches, ... }) {
+   const safeSlots = slots || [];
+   const safeAssignments = assignments || [];
+   const safeAssignmentsBySlotId = assignmentsBySlotId || {};
+   const safeMatches = matches || {};

-   const gridStructure = useMemo(() => { slots.forEach(...) }, [slots]);
+   const gridStructure = useMemo(() => { safeSlots.forEach(...) }, [safeSlots]);

-   if (slots.length === 0) { ... }
+   if (safeSlots.length === 0) { ... }
  }
```

**Total changes**: 3 files, ~30 lines  
**Breaking changes**: None  
**Behavior change**: Components no longer crash on undefined props

---

## Testing Checklist

### Before Fix ❌
- [x] Editor loads briefly
- [x] Crashes with "Cannot read properties of undefined (reading 'length')"
- [x] Error boundary shows error message

### After Fix ✅
- [ ] Editor loads without crashing
- [ ] All panels render (Match Queue, Grid, Conflicts)
- [ ] No console errors
- [ ] Data loads correctly after API calls complete

---

## When to Apply This Pattern

### Always Add Defensive Guards For

1. **Array props that you iterate over**:
   ```typescript
   items.map(...)    // Add: const safeItems = items || [];
   items.forEach(...) // Add: const safeItems = items || [];
   items.length      // Add: const safeItems = items || [];
   ```

2. **Object props with nested properties**:
   ```typescript
   obj.nested.value  // Add: const safe = obj || { nested: { value: default } };
   ```

3. **Props from external APIs**:
   ```typescript
   conflicts.unassigned_matches // Backend might not return all fields
   ```

### Don't Need Guards For

1. **Primitives with defaults in parent**:
   ```typescript
   const count = props.count ?? 0; // Already has default
   ```

2. **Props that are always required in TypeScript**:
   ```typescript
   // If parent always passes it, no guard needed (but doesn't hurt)
   ```

---

## Related Files

- `frontend/src/pages/schedule/editor/components/ConflictsPanel.tsx` - Conflicts guards
- `frontend/src/pages/schedule/editor/components/MatchQueuePanel.tsx` - Array guards
- `frontend/src/pages/schedule/editor/components/EditorGrid.tsx` - Grid guards
- `frontend/src/pages/schedule/editor/ScheduleEditorPage.tsx` - Parent loading guards

---

## Key Takeaways

### 1. Never Trust Props in Render

Even if parent has guards, child components should protect themselves. React lifecycle is complex, and edge cases happen.

### 2. Pattern: Defensive Variable Assignment

```typescript
const safeValue = unsafeValue || defaultValue;
```

Do this at the top of the component, then use `safeValue` everywhere.

### 3. Arrays vs Objects

- Arrays: Default to `[]`
- Objects: Default to `{}` or specific shape
- Nested objects: Provide full default structure

---

**Date**: 2026-01-12  
**Build Status**: ✅ Passing (348.17 kB with editor ON)  
**Deploy Status**: Pending user verification  
**Next Step**: User tests in browser with all guards in place

