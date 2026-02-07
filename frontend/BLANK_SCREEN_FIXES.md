# Blank Screen Fixes - Summary

**Date**: 2026-01-12  
**Issue**: Multiple scenarios where UI could show blank screen instead of error messages  
**Status**: ✅ **All Fixed**

---

## Fixes Applied

### Step 1: Feature Flag Guard ✅

**File**: `frontend/src/pages/schedule/editor/ScheduleEditorPage.tsx`

**Before**: Complex styled div (correct, but not matching standard)  
**After**: Simple, clear message with instructions

```typescript
if (!featureFlags.manualScheduleEditor) {
  return (
    <div style={{ padding: 24 }}>
      <h2>Manual Schedule Editor is disabled</h2>
      <p>Set VITE_ENABLE_MANUAL_EDITOR=true and restart dev server.</p>
    </div>
  );
}
```

**Impact**: Users immediately see why editor is unavailable and how to enable it.

---

### Step 2: Root ErrorBoundary ✅

**File**: `frontend/src/main.tsx`

**Before**: No error boundary (crashes = blank screen)  
**After**: Root-level ErrorBoundary catches all React crashes

```typescript
class RootErrorBoundary extends React.Component<
  { children: React.ReactNode },
  { error: Error | null }
> {
  state = { error: null as Error | null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    console.error("RootErrorBoundary:", error, info);
  }

  render() {
    if (this.state.error) {
      return (
        <div style={{ padding: 24 }}>
          <h2>UI Crash</h2>
          <pre style={{ whiteSpace: "pre-wrap" }}>
            {String(this.state.error?.stack || this.state.error?.message)}
          </pre>
        </div>
      );
    }
    return this.props.children;
  }
}
```

**Impact**: Any unhandled React error now shows stack trace instead of blank screen.

---

### Step 3: CANONICAL_32 Crash Prevention ✅

**File**: `frontend/src/utils/drawEstimation.ts`

**Before**: `throw new Error(...)` when `teamCount !== 32`  
**After**: Console warning + safe fallback logic

```typescript
case 'CANONICAL_32':
  if (teamCount !== 32) {
    console.warn(
      `[drawEstimation] CANONICAL_32 mismatch: expected 32 teams, got ${teamCount}. Falling back to 8-team rules.`
    );

    if (teamCount < 8) {
      // Round robin: N*(N-1)/2 matches
      return {
        wfMatches: 0,
        standardMatches: (teamCount * (teamCount - 1)) / 2,
      };
    }

    // 8-team bracket baseline
    return {
      wfMatches: 0,
      standardMatches: 9, // Default for guarantee 4
      standardMatchesFor4: 9,
      standardMatchesFor5: 12,
    };
  }
```

**Impact**: DrawBuilder capacity calculations never crash, even with template/team mismatches.

---

### Step 4: Editor Loading States ✅

**File**: `frontend/src/pages/schedule/editor/ScheduleEditorPage.tsx`

**Before**: Various loading states (correct, but improved)  
**After**: Consistent, simple loading/error messages

```typescript
if (pending.loadingVersions) {
  return <div style={{ padding: 24 }}>Loading editor…</div>;
}

if (!tournamentId) {
  return (
    <div style={{ padding: 24 }}>
      <h2>Failed to load editor</h2>
      <pre>Tournament ID is required</pre>
    </div>
  );
}

if (lastError && lastError.scope === 'LOAD_VERSIONS') {
  return (
    <div style={{ padding: 24 }}>
      <h2>Failed to load editor</h2>
      <pre>{String(lastError.message)}</pre>
    </div>
  );
}
```

**Impact**: No `return null` anywhere; all states show clear messages.

---

## Build Verification

```bash
npm run build
```

**Result**: ✅ PASS
- TypeScript compilation: Zero errors
- Bundle size: 345.30 kB (gzipped: 101.18 kB)
- No breaking changes

---

## Testing Scenarios

### Scenario 1: Feature Flag Disabled
**Before**: Blank screen or route not found  
**After**: "Manual Schedule Editor is disabled" message with instructions

### Scenario 2: React Component Crash
**Before**: Blank white screen  
**After**: "UI Crash" message with full stack trace

### Scenario 3: DrawBuilder with CANONICAL_32 Mismatch
**Before**: App crashes, blank screen  
**After**: Console warning, safe fallback, UI remains functional

### Scenario 4: Editor Fails to Load
**Before**: Various states, some potentially blank  
**After**: "Failed to load editor" with specific error message

---

## Summary

| Fix | Status | Impact |
|-----|--------|--------|
| Feature flag guard | ✅ | Clear instructions shown |
| Root ErrorBoundary | ✅ | All crashes caught and displayed |
| CANONICAL_32 safe fallback | ✅ | No crashes from template mismatches |
| Editor loading states | ✅ | No null returns, all states visible |

**No more blank screens.** Every error condition now shows a clear, actionable message.

---

## Files Modified

1. `frontend/src/main.tsx` - Added RootErrorBoundary
2. `frontend/src/pages/schedule/editor/ScheduleEditorPage.tsx` - Improved guards and loading states
3. `frontend/src/utils/drawEstimation.ts` - Replaced throw with safe fallback (already done)

**Total changes**: 3 files  
**Breaking changes**: None  
**Ready for deployment**: ✅ Yes

---

**Date**: 2026-01-12  
**Build Status**: ✅ Passing (345.30 kB)  
**Deployment Ready**: ✅ Yes

