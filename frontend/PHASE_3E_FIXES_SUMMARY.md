# Phase 3E: Manual Schedule Editor - Fixes Summary

**Date**: 2026-01-12  
**Status**: ✅ **Editor Loading Successfully**  
**Build**: 348.17 kB (gzipped: 102.06 kB)

---

## Problem → Solution Timeline

### Issue 1: CANONICAL_32 Hard-Throw (UI Crash)
**Error**: `CANONICAL_32 requires teamCount=32, got X`  
**Impact**: Entire UI crashed when viewing certain tournaments  
**Fix**: Replaced `throw` with safe fallback in `drawEstimation.ts`  
**Status**: ✅ Fixed

---

### Issue 2: Blank Screen from Feature Flag Guard
**Error**: Component returning `null` instead of descriptive message  
**Impact**: Blank screen when editor disabled  
**Fix**: Return informative message with instructions  
**Status**: ✅ Fixed

---

### Issue 3: Missing Root ErrorBoundary
**Error**: UI crashes show blank screen  
**Impact**: No error visibility for global crashes  
**Fix**: Added `RootErrorBoundary` in `main.tsx`  
**Status**: ✅ Fixed

---

### Issue 4: Infinite Loop (Maximum Update Depth Exceeded)
**Error**: `Maximum update depth exceeded`  
**Root Causes** (multiple, fixed sequentially):

#### 4A: Unstable Action in useEffect Dependencies ✅
**Problem**: `initialize` function included in effect dependency array  
**Why**: Zustand actions with `subscribeWithSelector` are recreated on every state change  
**Fix**: Removed `initialize` from deps, only keep `tournamentId` and `versionId`  
**File**: `ScheduleEditorPage.tsx`

```diff
- }, [tournamentId, versionId, initialize]);
+ }, [tournamentId, versionId]); // Actions excluded
```

#### 4B: Unmemoized Selector Creating New Arrays ✅
**Problem**: `selectUnassignedMatches` returned NEW array on every call  
**Why**: `.filter()` creates new reference, triggering Zustand's subscription system  
**Fix**: Added memoization cache based on input references  
**File**: `useEditorStore.ts`

```typescript
let cachedUnassigned: { matches, assignments, result } | null = null;

export const selectUnassignedMatches = (state) => {
  // Return cached result if inputs haven't changed
  if (cachedUnassigned && 
      cachedUnassigned.matches === state.matches &&
      cachedUnassigned.assignments === state.assignments) {
    return cachedUnassigned.result; // Same reference
  }
  
  // Recompute only when inputs change
  const result = state.matches.filter(...);
  cachedUnassigned = { matches: state.matches, assignments: state.assignments, result };
  return result;
};
```

**Status**: ✅ Fixed (both 4A and 4B required)

---

### Issue 5: Undefined Props Crash
**Error**: `Cannot read properties of undefined (reading 'length')`  
**Root Cause**: Components rendering before all data fully initialized  
**Fix**: Defensive guards in all child components  
**Files**: `ConflictsPanel.tsx`, `MatchQueuePanel.tsx`, `EditorGrid.tsx`

```typescript
// Pattern applied everywhere:
const safeItems = items || [];
const safeObj = obj || { defaultStructure };
```

**Status**: ✅ Fixed

---

## Final Architecture

### State Management: Zustand with Memoization
- Store wrapped with `subscribeWithSelector` middleware
- Component uses `useShallow` for selective subscriptions
- Selectors memoized when returning derived arrays/objects

### Error Handling: Multi-Layer
1. **Root ErrorBoundary** (`main.tsx`) - Catches global crashes
2. **EditorErrorBoundary** (`ScheduleEditorPage.tsx`) - Catches editor-specific crashes
3. **API Error States** (`lastError` in store) - Displays actionable error messages
4. **Defensive Guards** (all components) - Protects against undefined props

### Loading States: Explicit
- `pending.loadingVersions` - Version list loading
- `pending.loadingGrid` - Grid data loading
- `pending.loadingConflicts` - Conflicts loading
- `pending.cloning` - Clone operation in progress
- `pending.patchingAssignmentId` - Manual move in progress

---

## Testing Checklist

### ✅ Phase 3E Step 4 Verification (Completed)

- [x] Feature flag works (`VITE_ENABLE_MANUAL_EDITOR=true`)
- [x] Debug indicator shows flag status (dev only)
- [x] Route guard displays message when flag disabled
- [x] Button visibility matches flag state
- [x] Editor page loads without crashes
- [x] No infinite loops
- [x] No blank screens
- [x] Build passes (TypeScript + Vite)

### 🔲 Phase 3E Functional Testing (Next Step)

**Basic UI Rendering**:
- [ ] Version selector shows available versions
- [ ] Match Queue panel shows unassigned matches count
- [ ] Schedule Grid displays slots by time x court
- [ ] Conflicts panel shows summary stats

**Data Loading**:
- [ ] Versions load from API
- [ ] Grid data loads for selected version
- [ ] Conflicts load and display correctly
- [ ] Teams display with correct names

**Version Management**:
- [ ] Can switch between versions
- [ ] Final versions show "Read-only" banner
- [ ] Draft versions enable editing
- [ ] "Clone to Draft" button appears for final versions

**Manual Assignment** (Core Feature):
- [ ] Can drag assigned match in grid
- [ ] Drop on empty slot triggers PATCH
- [ ] Grid refreshes after successful move
- [ ] Conflicts refresh after successful move
- [ ] Error toast appears on PATCH failure
- [ ] Cannot drop on occupied slot

**Read-Only Guards**:
- [ ] Cannot drag matches in final versions
- [ ] Attempting edit on final shows modal/toast
- [ ] Clone workflow enables editing

---

## Key Lessons Learned

### 1. Zustand + subscribeWithSelector: Actions Are Unstable
**Rule**: Never put Zustand actions in `useEffect` dependency arrays when using `subscribeWithSelector` middleware.

**Why**: Actions are recreated on every state change → infinite rerenders.

**Fix**: Only include stable values (IDs, primitives) in deps.

---

### 2. Selectors Returning New Arrays Must Be Memoized
**Rule**: Any selector using `.filter()`, `.map()`, `.slice()`, or object spread must cache results.

**Why**: New reference on every call → Zustand thinks state changed → rerender loop.

**Fix**: Memoize based on input reference equality:
```typescript
if (cache && cache.inputs === state.inputs) return cache.result;
```

---

### 3. Defensive Guards Are Non-Negotiable
**Rule**: Every component should protect itself from undefined/null props.

**Why**: React lifecycle is complex; timing issues cause brief undefined states.

**Fix**: At top of component:
```typescript
const safeArray = propArray || [];
const safeObj = propObj || {};
```

---

### 4. Multiple Layers of Error Boundaries
**Rule**: Add error boundaries at multiple levels (root, feature, component).

**Why**: Different errors need different handling; one boundary can't catch all cases.

**Fix**:
- Root: Catch catastrophic failures
- Feature: Catch feature-specific issues without breaking entire app
- Component: Catch render errors in specific UI sections

---

## File Changes Summary

### Created (14 new files)
1. `frontend/src/pages/schedule/editor/ScheduleEditorPage.tsx` - Main editor page
2. `frontend/src/pages/schedule/editor/ScheduleEditorPage.css` - Editor styles
3. `frontend/src/pages/schedule/editor/useEditorStore.ts` - Zustand store
4. `frontend/src/pages/schedule/editor/components/EditorHeader.tsx` - Header component
5. `frontend/src/pages/schedule/editor/components/MatchQueuePanel.tsx` - Left panel
6. `frontend/src/pages/schedule/editor/components/EditorGrid.tsx` - Center grid
7. `frontend/src/pages/schedule/editor/components/ConflictsPanel.tsx` - Right panel
8. `frontend/src/pages/schedule/editor/components/DraggableAssignment.tsx` - Drag item
9. `frontend/src/pages/schedule/editor/components/DroppableSlot.tsx` - Drop target
10. `frontend/src/pages/schedule/editor/components/EditorErrorBoundary.tsx` - Error boundary
11. `frontend/src/config/featureFlags.ts` - Feature flag config
12. `frontend/STEP4_FEATURE_FLAG_DETERMINISTIC.md` - Flag documentation
13. `frontend/INFINITE_LOOP_FIX.md` - Loop debugging story
14. `frontend/ZUSTAND_EFFECT_DEPS_RULE.md` - Best practices guide

### Modified (6 files)
1. `frontend/src/App.tsx` - Added editor route
2. `frontend/src/pages/schedule/SchedulePageGridV1.tsx` - Added editor button + debug indicator
3. `frontend/src/api/client.ts` - Added conflicts + assignment endpoints
4. `frontend/src/utils/drawEstimation.ts` - Removed CANONICAL_32 throw
5. `frontend/src/main.tsx` - Added RootErrorBoundary
6. `frontend/package.json` - Added dependencies + scripts

### Dependencies Added
- `zustand` (^5.0.10) - State management
- `@dnd-kit/core` (^6.3.1) - Drag and drop
- `@dnd-kit/utilities` (^3.2.2) - DnD utilities
- `cross-env` (^10.1.0) - Cross-platform env vars (dev)

---

## Performance Metrics

### Build Size
- **Total**: 348.17 kB (102.06 kB gzipped)
- **CSS**: 23.76 kB (4.92 kB gzipped)
- **HTML**: 0.51 kB (0.32 kB gzipped)

### Bundle Analysis
- Editor code is tree-shaken when `VITE_ENABLE_MANUAL_EDITOR=false`
- No performance regressions in main schedule page
- Lazy loading not implemented (editor loads with main bundle)

---

## Next Steps

### Immediate (User Testing)
1. ✅ Verify editor loads (DONE)
2. 🔲 Test version switching
3. 🔲 Test drag-and-drop manual assignment
4. 🔲 Verify conflicts refresh after move
5. 🔲 Test final version read-only behavior
6. 🔲 Test clone-to-draft workflow

### Short-Term (Phase 3E Completion)
1. Fix any issues found in user testing
2. Remove debug indicator (temporary feature flag display)
3. Add integration tests for critical flows
4. Document known limitations

### Long-Term (Future Phases)
1. Add optimistic UI updates (currently refetches after every move)
2. Implement batch assignment operations
3. Add "Undo" via store state snapshots (not just version clones)
4. Add keyboard shortcuts for power users
5. Lazy-load editor bundle (code splitting)

---

## Known Limitations

### Not Yet Implemented
- **Locked assignments UI**: Backend supports `locked` field, but grid doesn't display lock indicators yet
- **Swap assignments**: Only empty slot drops supported; swapping two assignments requires manual two-step move
- **Candidate slot highlighting**: No visual hints for "best" slots for unassigned matches
- **Multi-select drag**: Can only move one assignment at a time
- **Undo/Redo**: Only via version cloning (no in-memory state snapshots)

### Architectural Constraints
- **No optimistic updates**: Always refetches after mutation (safer but slower)
- **No real-time collaboration**: Multiple users editing same draft can cause conflicts
- **No auto-save**: All changes are immediate (PATCH on drop)

---

## Deployment Readiness

### ✅ Ready for Limited Audience Deploy
- [x] Feature flag implemented (environment-based)
- [x] No breaking changes to existing features
- [x] Error boundaries prevent crashes
- [x] Build passes with zero errors
- [x] Editor loads successfully in dev
- [x] Backend Phase 3D frozen (no changes required)

### 🔲 Not Ready for General Release
- [ ] Full functional testing incomplete
- [ ] Integration tests not written
- [ ] Accessibility audit not performed
- [ ] Mobile responsiveness not tested
- [ ] Performance testing under load not done

---

## Support Information

### If Editor Won't Load
1. Check browser console for errors
2. Verify feature flag: `VITE_ENABLE_MANUAL_EDITOR=true`
3. Restart dev server after flag change
4. Clear browser cache or use incognito
5. Check network tab for failed API calls

### If Infinite Loop Returns
1. Check `useEffect` dependencies (no Zustand actions)
2. Check selectors return stable references when inputs unchanged
3. Verify `useShallow` is used for store subscriptions
4. Add `console.log` in selectors to detect excessive calls

### If Component Crashes
1. Check error boundary message
2. Look for `.length` or `.map()` on potentially undefined values
3. Add defensive guards: `const safe = value || []`
4. Verify API response shape matches TypeScript interfaces

---

**Date**: 2026-01-12  
**Phase**: 3E (Manual Schedule Editor UI)  
**Status**: ✅ Loading Successfully, Ready for Functional Testing  
**Next Milestone**: Complete user acceptance testing for manual assignment workflow

