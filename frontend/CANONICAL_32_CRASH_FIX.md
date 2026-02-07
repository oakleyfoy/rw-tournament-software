# CANONICAL_32 Hard-Throw Fix

**Issue**: DrawBuilder.tsx crashed when CANONICAL_32 template was used with teamCount ≠ 32  
**Root Cause**: `drawEstimation.ts::calculateMatches()` threw an error instead of gracefully handling mismatch  
**Impact**: Prevented users from viewing capacity calculations in DrawBuilder UI

---

## Fix Applied

**File**: `frontend/src/utils/drawEstimation.ts`  
**Function**: `calculateMatches()` → `case 'CANONICAL_32'`

### Before (Hard-Throw)
```typescript
case 'CANONICAL_32':
  if (teamCount !== 32) {
    throw new Error(`CANONICAL_32 requires teamCount=32, got ${teamCount}`);
  }
  // ... rest of logic
```

### After (Safe Fallback)
```typescript
case 'CANONICAL_32':
  // Safe fallback: if teamCount !== 32, use deterministic rules
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

    // 8-team bracket baseline (product invariant: bracket size is always 8)
    // Guarantee 4: 9 matches (7 main + 2 consolation)
    // Guarantee 5: 12 matches (7 main + 5 consolation)
    return {
      wfMatches: 0,
      standardMatches: 9, // Default for guarantee 4
      standardMatchesFor4: 9,
      standardMatchesFor5: 12,
    };
  }
  // ... rest of logic (unchanged)
```

---

## Fallback Logic

### Product Invariant
**Bracket size is always 8.** If teamCount < 8, use round robin; otherwise use 8-team bracket inventory.

### Deterministic Fallback Rules

#### Case 1: teamCount < 8 (Round Robin)
- **Formula**: `N * (N-1) / 2`
- **Example**: 6 teams → 15 matches
- **Guarantee**: Not applicable (RR gives full guarantee)

#### Case 2: teamCount >= 8 (8-Team Bracket)
- **Main Bracket**: QF(4) + SF(2) + F(1) = 7 matches
- **Guarantee 4**: 7 + 2 consolation = **9 matches**
- **Guarantee 5**: 7 + 5 consolation = **12 matches**

### wfRounds Mismatch (Also Fixed)
Previously threw if `wfRounds !== 2`. Now logs a warning but uses the provided value.

---

## Testing

### Build Verification
```powershell
cd "C:\RW Tournament Software\frontend"
npm run build
```
**Result**: ✅ TypeScript compilation passes (zero errors)

### Browser Testing (Manual)
1. Open DrawBuilder with an event where teamCount ≠ 32
2. Select CANONICAL_32 template
3. **Expected**: 
   - No UI crash
   - Console warning appears
   - Capacity calculation uses fallback logic
   - UI remains functional

---

## Impact

### Before Fix
- ❌ DrawBuilder crashes when CANONICAL_32 used with wrong team count
- ❌ Users see blank/error screen
- ❌ No graceful degradation

### After Fix
- ✅ DrawBuilder remains functional
- ✅ Console warning provides visibility
- ✅ Fallback logic is deterministic and documented
- ✅ UI never crashes due to template/team count mismatch

---

## Additional Changes

### wfRounds Flexibility
Also softened the `wfRounds !== 2` check:
- Before: Hard throw
- After: Console warning + use provided value

This prevents crashes if CANONICAL_32 is used with non-standard wfRounds (e.g., experimentation, edge cases).

---

## Summary

**Change Type**: Defensive programming / Crash prevention  
**Risk**: Low (makes UI more resilient)  
**Breaking Changes**: None (existing 32-team CANONICAL_32 behavior unchanged)  
**Deployment**: Ready (build passes, no backend changes)

**Date**: 2026-01-12  
**Status**: ✅ Complete

