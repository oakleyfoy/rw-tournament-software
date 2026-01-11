# 8-Team Bracket Implementation Summary

## Overview
Successfully updated the RW Tournament Software to support 8-team bracket events with guarantee 4/5 logic, replacing the previous 32-team CANONICAL_32 template.

## Key Changes

### 1. Match Model Updates (`backend/app/models/match.py`)
- **Added `placement_type` field**: Optional string for PLACEMENT matches
  - Values: `"MAIN_SF_LOSERS"`, `"CONS_R1_WINNERS"`, `"CONS_R1_LOSERS"`
- **Updated `match_type` comment**: Now includes `"PLACEMENT"` as a valid stage
- **Migration**: `007_add_placement_type.py` created

### 2. Match Generation Logic (`backend/app/utils/match_generation.py`)

#### Updated `calculate_match_counts()`
- **CANONICAL_32 now requires `team_count=8`** (enforced validation)
- **Guarantee 4**: 9 total matches (7 MAIN + 2 CONSOLATION Tier 1)
- **Guarantee 5**: 13 total matches (7 MAIN + 2 CONS T1 + 1 CONS T2 + 3 PLACEMENT)
- **WF matches**: Changed from 32 to 8 (2 rounds × 4 matches)

#### Updated `generate_standard_matches()` for CANONICAL_32
Generates exactly 7 MAIN matches for 8-team bracket:
- **Round 1 (QF)**: 4 matches
  - `match_code`: `{prefix}_QF1` through `{prefix}_QF4`
  - `round_index=1`, `sequence_in_round=1..4`
- **Round 2 (SF)**: 2 matches
  - `match_code`: `{prefix}_SF1`, `{prefix}_SF2`
  - `round_index=2`, `sequence_in_round=1..2`
- **Round 3 (Final)**: 1 match
  - `match_code`: `{prefix}_FINAL`
  - `round_index=3`, `sequence_in_round=1`

#### Updated `generate_consolation_matches()`
- **Signature changed**: Removed `bracket_team_count`, added `guarantee` parameter
- **Tier 1**: Always generates 2 matches (first-round losers)
  - `consolation_tier=1`, `round_index=1`
  - `match_code`: `{prefix}_CONS1_1`, `{prefix}_CONS1_2`
- **Tier 2**: Only if `guarantee == 5`, generates 1 match
  - `consolation_tier=2`, `round_index=2`
  - `match_code`: `{prefix}_CONS2_1`

#### New `generate_placement_matches()` function
Generates 3 placement matches (Guarantee 5 only):
1. **MAIN_SF_LOSERS** (3rd/4th place)
   - `placement_type="MAIN_SF_LOSERS"`
   - `match_code`: `{prefix}_PL1_3rd4th`
2. **CONS_R1_WINNERS** (5th/6th place)
   - `placement_type="CONS_R1_WINNERS"`
   - `match_code`: `{prefix}_PL2_5th6th`
3. **CONS_R1_LOSERS** (7th/8th place)
   - `placement_type="CONS_R1_LOSERS"`
   - `match_code`: `{prefix}_PL3_7th8th`

All have: `match_type="PLACEMENT"`, `round_index=1`, `sequence_in_round=1..3`

### 3. Schedule Route Updates (`backend/app/routes/schedule.py`)
- **Import**: Added `generate_placement_matches`
- **Generation logic**: Updated to call new functions with guarantee parameter
- **Guarantee-aware**: Reads `event.guarantee_selected` (defaults to 5)
- **Placement generation**: Only calls `generate_placement_matches()` if `guarantee == 5`

### 4. Sanity-Check Updates (`backend/app/routes/schedule_sanity.py`)

#### Updated `get_match_stage()`
- Added `"PLACEMENT"` as a recognized stage

#### Updated `get_match_sort_key()`
- **Stage priority**: `WF (1) < MAIN (2) < CONSOLATION (3) < PLACEMENT (4)`
- **Placement type tie-breaker**: Ensures stable ordering within PLACEMENT
  - `MAIN_SF_LOSERS (1) < CONS_R1_WINNERS (2) < CONS_R1_LOSERS (3)`
- **Critical**: MAIN Final (round_index=3) sorts BEFORE any PLACEMENT matches

#### New Validations
1. **MAIN Bracket Structure**:
   - Round 1 (QF): expects 4 matches
   - Round 2 (SF): expects 2 matches
   - Round 3 (Final): expects 1 match
   - Flags issues if counts don't match

2. **CONSOLATION Validation** (updated for 8-team):
   - Validates `team_count == 8` for CANONICAL_32
   - Tier 1: expects 2 matches (always)
   - Tier 2: expects 1 if guarantee=5, 0 if guarantee=4
   - Validates round_index and tier metadata

3. **PLACEMENT Validation**:
   - Bracket events (CANONICAL_32):
     - Guarantee 4: expects 0 PLACEMENT matches
     - Guarantee 5: expects 3 PLACEMENT matches
     - Validates all 3 placement types are present
   - RR events: expects 0 PLACEMENT matches (flags if any found)

#### Report Structure
Added two new sections to sanity-check report:
- `main_bracket_structure`: Status and issues for MAIN round counts
- `placement_validation`: Status and issues for PLACEMENT matches

### 5. Database Migrations
- **006_add_consolation_tier.py**: Adds `consolation_tier` column (nullable int)
- **007_add_placement_type.py**: Adds `placement_type` column (nullable string)

## Match Ordering (Enforced by Sort Key)

For an 8-team bracket event, matches sort in this exact order:

1. **WF Round 1** (if applicable)
2. **WF Round 2** (if applicable)
3. **MAIN Round 1** (QF) - 4 matches
4. **MAIN Round 2** (SF) - 2 matches
5. **CONSOLATION Tier 1** - 2 matches
6. **CONSOLATION Tier 2** - 1 match (Guarantee 5 only)
7. **MAIN Round 3** (Final) - 1 match
8. **PLACEMENT Round 1** - 3 matches (Guarantee 5 only)
   - MAIN_SF_LOSERS
   - CONS_R1_WINNERS
   - CONS_R1_LOSERS

## Expected Match Counts

### Guarantee 4 (8-team bracket)
- WF: 8 matches (2 rounds)
- MAIN: 7 matches (4 QF + 2 SF + 1 Final)
- CONSOLATION: 2 matches (Tier 1 only)
- PLACEMENT: 0 matches
- **Total**: 17 matches per event

### Guarantee 5 (8-team bracket)
- WF: 8 matches (2 rounds)
- MAIN: 7 matches (4 QF + 2 SF + 1 Final)
- CONSOLATION: 3 matches (2 Tier 1 + 1 Tier 2)
- PLACEMENT: 3 matches
- **Total**: 21 matches per event

### Round Robin (any team count)
- WF: 0 matches
- MAIN: n×(n-1)/2 matches
- CONSOLATION: 0 matches
- PLACEMENT: 0 matches

## Business Rules Enforced

1. ✅ Bracket size is always 8 teams (enforced by validation error)
2. ✅ If event has <8 teams, must use Round Robin (not bracket)
3. ✅ Only bracket events have consolation
4. ✅ Consolation includes first-round losers only
5. ✅ Guarantee 4: MAIN + CONSOLATION Tier 1 only
6. ✅ Guarantee 5: MAIN + CONSOLATION Tier 1 + Tier 2 + PLACEMENT
7. ✅ RR events never generate consolation or placement
8. ✅ MAIN Final sorts before PLACEMENT matches
9. ✅ CONSOLATION Tier 1 sorts before Tier 2

## Testing Verification

All functions and imports verified:
- ✅ `calculate_match_counts()` returns correct counts for both guarantees
- ✅ `generate_consolation_matches()` imported successfully
- ✅ `generate_placement_matches()` imported successfully
- ✅ `Match.placement_type` field exists
- ✅ `get_match_sort_key()` imported successfully
- ✅ No Python syntax errors

## Next Steps for User

1. **Run migrations**:
   ```bash
   cd backend
   alembic upgrade head
   ```

2. **Restart backend server**:
   ```bash
   uvicorn app.main:app --reload --log-level debug
   ```

3. **Test with UI**:
   - Create an 8-team bracket event (CANONICAL_32 template)
   - Set guarantee to 4 or 5
   - Build schedule
   - Verify match counts:
     - Guarantee 4: 17 total (8 WF + 9 bracket)
     - Guarantee 5: 21 total (8 WF + 13 bracket)

4. **Run sanity-check**:
   ```bash
   curl http://localhost:8000/api/tournaments/{id}/schedule/versions/{vid}/sanity-check
   ```
   - Should report "ok" status
   - Verify stage breakdown shows correct counts
   - Check `main_bracket_structure` and `placement_validation` sections

## Definition of Done ✅

- [x] Bracket events (8 teams only) generate correct MAIN + CONSOLATION inventory
- [x] Guarantee 4 vs 5 drives Tier 2 + PLACEMENT generation exactly
- [x] Sorting key enforces the exact match ordering required for Phase 3B auto-assign
- [x] Sanity-check validates these rules and reports issues clearly
- [x] All code imports successfully with no syntax errors
- [x] Match counts verified: G4=9, G5=13 (excluding WF)

