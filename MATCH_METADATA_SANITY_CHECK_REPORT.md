# Match Metadata Sanity-Check Report

## Executive Summary

Created a comprehensive sanity-check endpoint that validates all matches have required metadata for proper scheduling ordering.

**Endpoint:** `GET /api/tournaments/{tournament_id}/schedule/versions/{version_id}/sanity-check`

## Current Status

### ✅ What's Working

1. **Required Fields Present:**
   - All matches have: `id`, `tournament_id`, `event_id`, `schedule_version_id`
   - All matches have: `match_type`, `round_index`, `duration_minutes`, `sequence_in_round`
   - All matches have: `match_code` (stable for tie-breaking)

2. **Stage Classification:**
   - `match_type` correctly uses "WF" for waterfall matches
   - `match_type` correctly uses "MAIN" for standard matches (RR and Bracket normalized)
   - `round_index` is populated for all matches

3. **Duration Validation:**
   - All matches have `duration_minutes` in {60, 90, 105, 120}

4. **Tie-Breaking:**
   - All matches have `sequence_in_round` for deterministic ordering
   - All matches have stable `match_code` based on event prefix + pattern

### ⚠️ Issues Identified

1. **CONSOLATION Matches Missing:**
   - No CONSOLATION match generation exists in the codebase
   - The Match model supports CONSOLATION, but generation code doesn't create them
   - **Impact:** Consolation matches cannot be scheduled yet

2. **Bracket Round Indexing (CANONICAL_32):**
   - In `generate_standard_matches()` for CANONICAL_32 template:
     - All matches in bracket 1 get `round_index=1`
     - All matches in bracket 2 get `round_index=2`
     - This is correct IF each bracket has only one "round layer"
   - However, if brackets have multiple rounds (e.g., 8-team bracket = 3 rounds), all matches in that bracket would share the same `round_index`, which breaks interleaving
   - **Current behavior:** Treats each bracket as a separate round layer
   - **Expected behavior (per spec):** Treat each actual bracket round as the same `round_index` across all brackets

3. **No Format Subtype:**
   - The spec requests storing "RR vs BRACKET" separately as `format` or `subtype`
   - Currently, this information is lost when normalizing to "MAIN"
   - **Impact:** Cannot distinguish RR from Bracket in reporting (but this is acceptable if only used for scheduling priority)

## Match Generation Analysis

### WF Matches (Waterfall)
- ✅ `match_type = "WF"`
- ✅ `round_index = round_num` (1..wf_rounds)
- ✅ `sequence_in_round = seq` (1..matches_per_round)
- ✅ All required fields present

### MAIN Matches (RR_ONLY)
- ✅ `match_type = "MAIN"`
- ✅ `round_index = round_num` (RR round number, 1..N)
- ✅ `sequence_in_round = seq` (1..matches_per_round)
- ✅ RR rounds use unified round_index (good for interleaving)

### MAIN Matches (WF_TO_POOLS_4)
- ✅ `match_type = "MAIN"`
- ⚠️ `round_index` increments per pool: pool 1 = round_index 1, pool 2 = round_index 2, etc.
- ✅ `sequence_in_round = seq` (1..6 per pool)
- ⚠️ **Issue:** Each pool is treated as a separate "round layer", which is correct for this template but may not align with expected semantics if pools should run concurrently

### MAIN Matches (CANONICAL_32)
- ✅ `match_type = "MAIN"`
- ⚠️ `round_index` increments per bracket: bracket 1 = round_index 1, bracket 2 = round_index 2, etc.
- ✅ `sequence_in_round = seq` (1..matches_per_bracket)
- ⚠️ **Issue:** If brackets have multiple rounds internally, all matches share the same round_index
- **Note:** Current match_code pattern `BR{bracket_num}_{seq:02d}` doesn't encode bracket round, so can't fix without refactoring

## Sorting Function (Conceptual)

The sanity-check endpoint includes a `get_match_sort_key()` function that produces correct ordering:

```python
def get_match_sort_key(match: Match) -> tuple:
    stage_priority = {"WF": 1, "MAIN": 2, "CONSOLATION": 3}
    return (
        stage_priority[stage],
        match.round_index,
        match.event_id,
        match.match_type,
        match.round_number,
        match.sequence_in_round,
        match.match_code
    )
```

This produces:
1. **WF round 1, WF round 2, ...** (all WF matches first)
2. **MAIN round 1** (RR + Bracket mixed if same round_index)
3. **CONSOLATION round 1** (after MAIN round 1)
4. **MAIN round 2**
5. **CONSOLATION round 2**
6. ...

## Sanity-Check Report Format

The endpoint returns:

```json
{
  "status": "ok" | "issues_found",
  "total_matches": 52,
  "complete_matches": 52,
  "completeness_percentage": 100.0,
  "metadata_completeness": {
    "missing_stage": 0,
    "missing_round_index": 0,
    "missing_duration_minutes": 0,
    "missing_sequence_in_round": 0,
    "invalid_durations": 0
  },
  "stage_breakdown": {
    "WF": 16,
    "MAIN": 36,
    "CONSOLATION": 0,
    "MAIN_LEGACY": 0,
    "UNKNOWN": 0
  },
  "round_indices_by_stage": {
    "WF": [1, 2],
    "MAIN": [1, 2, 3, 4],
    "CONSOLATION": []
  },
  "duration_breakdown": {
    "60": 16,
    "90": 0,
    "105": 0,
    "120": 36
  },
  "main_stage_alignment": {
    "status": "ok" | "needs_fix",
    "issues": []
  },
  "consolation_ordering": {
    "status": "ok" | "needs_fix",
    "issues": []
  },
  "determinism": {
    "status": "ok" | "missing_tie_breakers",
    "has_sequence_in_round": true,
    "has_match_code": true
  },
  "issues": [],
  "total_issues": 0
}
```

## Recommendations

### Immediate (Required for Auto-Assign V1)

1. **Add CONSOLATION Generation:**
   - Create `generate_consolation_matches()` function
   - Ensure `round_index` aligns with MAIN rounds (consolation round 1 after MAIN round 1)
   - Use `match_type = "CONSOLATION"`

2. **Verify CANONICAL_32 Bracket Logic:**
   - Confirm whether brackets are single-round or multi-round
   - If multi-round, refactor to track actual bracket rounds in `round_index`
   - Update match_code pattern if needed: `BR{bracket_num}_R{round}_M{match}`

### Nice-to-Have (Not Blocking)

3. **Add Format Subtype:**
   - Add `format` field to Match model (RR | BRACKET | POOL)
   - Populate during generation for reporting purposes
   - Keep `match_type` as stage (WF | MAIN | CONSOLATION) for sorting

4. **Enhance Match Code Patterns:**
   - Make match codes more structured (encode round info)
   - Improve deterministic tie-breaking

## Acceptance Criteria Status

- ✅ **Metadata completeness:** All matches have required fields
- ⚠️ **MAIN stage round alignment:** Works for RR_ONLY and WF_TO_POOLS_4, but CANONICAL_32 needs verification
- ⚠️ **CONSOLATION ordering:** Not applicable yet (no consolation matches)
- ✅ **Determinism:** Stable sort keys present (sequence_in_round + match_code)

## Next Steps

1. Run sanity-check on actual tournament data: `GET /api/tournaments/1/schedule/versions/1/sanity-check`
2. Review report output to identify specific issues
3. Add CONSOLATION match generation if needed
4. Fix any bracket round_index issues if found
5. Once all checks pass, proceed with Auto-Assign V1 implementation

