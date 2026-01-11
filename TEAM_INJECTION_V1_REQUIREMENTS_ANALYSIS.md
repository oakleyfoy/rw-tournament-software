# Team Injection V1 - Requirements Analysis

## Status: SPECIFICATION ONLY - NOT YET IMPLEMENTED

---

## Current State Assessment

### Existing Schema

✅ **Match Model** (`backend/app/models/match.py`)
- Has `placeholder_side_a` and `placeholder_side_b` (strings)
- Has `match_type` ("WF" | "MAIN" | "CONSOLATION" | "PLACEMENT")
- Has `event_id` foreign key

❌ **Missing:**
- `team_a_id` (nullable integer FK to team.id)
- `team_b_id` (nullable integer FK to team.id)
- No team relationships

✅ **Event Model** (`backend/app/models/event.py`)
- Has `team_count` (integer)

❌ **Missing:**
- No `Team` model exists
- No teams relationship

### Conclusion

**Schema changes required:**
1. Create `Team` model
2. Add `team_a_id` and `team_b_id` to `Match` model
3. Create migration for these changes

---

## Team Injection Contract

### Input Requirements

```python
class InjectTeamsRequest(BaseModel):
    schedule_version_id: int
    event_id: int  # Required - teams are event-scoped
    # Optional: explicit team ordering override
    team_order_override: Optional[List[int]] = None  # List of team IDs in seed order
```

### Output Contract

For each match in the event:
- If **immediately assignable** (e.g., RR matches, bracket QFs):
  - Set `team_a_id` and `team_b_id` with concrete team IDs
- If **future-dependent** (e.g., bracket SFs, Finals):
  - Leave `team_a_id` and `team_b_id` as NULL
  - Keep `placeholder_side_a` and `placeholder_side_b` with descriptive text
  
### Determinism Guarantee

Given:
- Same `event_id`
- Same set of teams with same seeds/ordering
- Same match inventory

Result:
- **Identical team assignments** every time
- Stable sort order for tie-breaking

---

## Data Model Requirements

### 1. Team Model (NEW)

```python
class Team(SQLModel, table=True):
    __table_args__ = (
        SAUniqueConstraint("event_id", "team_name", name="uq_event_team_name"),
    )
    
    id: Optional[int] = Field(default=None, primary_key=True)
    event_id: int = Field(foreign_key="event.id")
    team_name: str
    seed: Optional[int] = Field(default=None)  # 1-based seed (1=highest)
    rating: Optional[float] = Field(default=None)  # For tie-breaking
    registration_timestamp: Optional[datetime] = Field(default=None)  # For tie-breaking
    created_at: datetime = Field(default_factory=datetime.utcnow)
    
    # Relationships
    event: "Event" = Relationship(back_populates="teams")
    matches_as_team_a: List["Match"] = Relationship(
        back_populates="team_a",
        sa_relationship_kwargs={"foreign_keys": "[Match.team_a_id]"}
    )
    matches_as_team_b: List["Match"] = Relationship(
        back_populates="team_b",
        sa_relationship_kwargs={"foreign_keys": "[Match.team_b_id]"}
    )
```

### 2. Match Model Updates (MODIFY)

**Add fields:**
```python
class Match(SQLModel, table=True):
    # ... existing fields ...
    
    # NEW: Concrete team assignments (nullable)
    team_a_id: Optional[int] = Field(default=None, foreign_key="team.id")
    team_b_id: Optional[int] = Field(default=None, foreign_key="team.id")
    
    # EXISTING: Placeholder text for future resolution
    placeholder_side_a: str  # e.g., "Winner of QF1" or "Team 1"
    placeholder_side_b: str  # e.g., "Winner of QF2" or "Team 2"
    
    # NEW: Relationships
    team_a: Optional["Team"] = Relationship(
        back_populates="matches_as_team_a",
        sa_relationship_kwargs={"foreign_keys": "[Match.team_a_id]"}
    )
    team_b: Optional["Team"] = Relationship(
        back_populates="matches_as_team_b",
        sa_relationship_kwargs={"foreign_keys": "[Match.team_b_id]"}
    )
```

### 3. Event Model Updates (MODIFY)

**Add relationship:**
```python
class Event(SQLModel, table=True):
    # ... existing fields ...
    
    # NEW: Relationship to teams
    teams: List["Team"] = Relationship(back_populates="event")
```

### 4. Migration Required

**New migration:** `008_add_teams_and_team_assignments.py`

Actions:
1. Create `team` table
2. Add `team_a_id` column to `match` table (nullable, FK to team.id)
3. Add `team_b_id` column to `match` table (nullable, FK to team.id)

---

## Bracket vs Round Robin Decision Logic

### Authoritative Rules

```python
def validate_team_count_for_event(event: Event) -> str:
    """
    Returns: "BRACKET_8" | "ROUND_ROBIN" | "INVALID"
    """
    team_count = event.team_count
    
    if team_count == 8:
        return "BRACKET_8"
    elif team_count < 8:
        return "ROUND_ROBIN"
    else:  # team_count > 8
        raise HTTPException(
            status_code=400,
            detail=f"Invalid team count: {team_count}. Must be ≤8 (8 for bracket, <8 for round robin)"
        )
```

### Match Type Validation

When injecting teams, verify:
- If `team_count == 8`: Matches should have `match_type` = "WF" or "MAIN" or "CONSOLATION" (bracket inventory)
- If `team_count < 8`: Matches should have `match_type` = "WF" or "MAIN" (RR inventory, no consolation)

---

## Team Placement Rules (Deterministic)

### A) Round Robin (<8 teams)

**Algorithm:**
1. Get all teams for event, sorted deterministically:
   ```python
   teams_sorted = sorted(teams, key=lambda t: (
       t.seed if t.seed is not None else 999,
       -(t.rating or 0),  # Higher rating first
       t.registration_timestamp or datetime.max,
       t.id
   ))
   ```

2. Generate all pairings (if not already in match inventory):
   - For N teams, generate N*(N-1)/2 matches
   - Standard round-robin pairing algorithm

3. Assign teams to matches:
   ```python
   # Get matches sorted by round_number, sequence_in_round
   matches_sorted = sorted(matches, key=lambda m: (
       m.round_number,
       m.sequence_in_round,
       m.id
   ))
   
   # Iterate and assign
   for match, (team_a, team_b) in zip(matches_sorted, pairings):
       match.team_a_id = team_a.id
       match.team_b_id = team_b.id
   ```

### B) 8-Team Bracket

**Seeding Rules:**
```python
def get_bracket_seed_mapping(teams: List[Team]) -> Dict[int, Team]:
    """
    Returns: {1: team, 2: team, ..., 8: team}
    """
    teams_sorted = sorted(teams, key=lambda t: (
        t.seed if t.seed is not None else 999,
        -(t.rating or 0),
        t.registration_timestamp or datetime.max,
        t.id
    ))
    
    return {i+1: team for i, team in enumerate(teams_sorted)}
```

**QF Assignment:**
```python
def assign_quarterfinals(matches: List[Match], seed_map: Dict[int, Team]):
    """
    Bracket structure:
    QF1: Seed 1 vs Seed 8
    QF2: Seed 4 vs Seed 5
    QF3: Seed 3 vs Seed 6
    QF4: Seed 2 vs Seed 7
    """
    qf_matches = [m for m in matches if m.match_type == "MAIN" and m.round_index == 1]
    qf_matches_sorted = sorted(qf_matches, key=lambda m: m.sequence_in_round)
    
    pairings = [
        (seed_map[1], seed_map[8]),  # QF1
        (seed_map[4], seed_map[5]),  # QF2
        (seed_map[3], seed_map[6]),  # QF3
        (seed_map[2], seed_map[7]),  # QF4
    ]
    
    for match, (team_a, team_b) in zip(qf_matches_sorted, pairings):
        match.team_a_id = team_a.id
        match.team_b_id = team_b.id
        match.placeholder_side_a = team_a.team_name  # Update placeholder too
        match.placeholder_side_b = team_b.team_name
```

**SF/Finals/Consolation:**
- **DO NOT** assign team IDs yet
- Keep as placeholders: "Winner of QF1", "Loser of QF3", etc.
- These get resolved when match results are entered (out of scope for V1)

---

## API Endpoints Required

### 1. Inject Teams Endpoint (NEW)

```python
@router.post("/tournaments/{tournament_id}/events/{event_id}/inject-teams")
def inject_teams(
    tournament_id: int,
    event_id: int,
    schedule_version_id: int = Query(...),
    team_order_override: Optional[List[int]] = None,  # Optional explicit team IDs in order
    session: Session = Depends(get_session)
):
    """
    Inject teams into matches for an event.
    
    For bracket (8 teams): Assigns QF matchups
    For RR (<8 teams): Assigns all pairings
    
    Idempotent: Can be run multiple times (clears previous injections first)
    """
    # 1. Validate tournament, event, version
    # 2. Validate team count
    # 3. Get teams (ordered)
    # 4. Determine bracket vs RR
    # 5. Assign teams to matches
    # 6. Return summary
```

**Response:**
```python
class InjectTeamsResponse(BaseModel):
    event_id: int
    team_count: int
    format: str  # "BRACKET_8" | "ROUND_ROBIN"
    matches_assigned: int  # Number of matches with teams assigned
    matches_placeholder: int  # Number of matches still with placeholders
    teams_injected: List[TeamSummary]  # List of teams with their assignments
```

### 2. Update GET /matches Endpoint (MODIFY)

**Current response:**
```json
{
  "id": 1,
  "match_code": "MAIN_QF1",
  "placeholder_side_a": "Team 1",
  "placeholder_side_b": "Team 8"
}
```

**Updated response:**
```json
{
  "id": 1,
  "match_code": "MAIN_QF1",
  "team_a_id": 5,
  "team_a_name": "Smash Bros",
  "team_b_id": 12,
  "team_b_name": "Net Ninjas",
  "placeholder_side_a": "Smash Bros",
  "placeholder_side_b": "Net Ninjas"
}
```

### 3. Update GET /schedule/grid Endpoint (MODIFY)

**Add to GridMatch:**
```python
class GridMatch(BaseModel):
    match_id: int
    stage: str
    round_index: int
    sequence_in_round: int
    duration_minutes: int
    match_code: str
    event_id: int
    # NEW:
    team_a_id: Optional[int] = None
    team_a_name: Optional[str] = None
    team_b_id: Optional[int] = None
    team_b_name: Optional[str] = None
    placeholder_side_a: str
    placeholder_side_b: str
```

### 4. Team Management Endpoints (NEW)

```python
# Create team
POST /tournaments/{tid}/events/{eid}/teams
Body: { name: str, seed?: int, rating?: float }

# List teams
GET /tournaments/{tid}/events/{eid}/teams
Returns: List[Team]

# Update team
PATCH /tournaments/{tid}/events/{eid}/teams/{team_id}
Body: { name?: str, seed?: int, rating?: float }

# Delete team
DELETE /tournaments/{tid}/events/{eid}/teams/{team_id}
```

---

## Verification Tests Required

### Test 1: 8-Team Bracket Seed Assignment

```python
def test_inject_teams_bracket_8_teams():
    """Verify seeds assigned to QFs correctly"""
    # Setup: Create event with 8 teams, seeds 1-8
    # Generate bracket matches
    # Call inject_teams
    # Assert:
    #   QF1: team_a=seed1, team_b=seed8
    #   QF2: team_a=seed4, team_b=seed5
    #   QF3: team_a=seed3, team_b=seed6
    #   QF4: team_a=seed2, team_b=seed7
    #   SF1: team_a_id=None, placeholder="Winner of QF1"
    #   SF2: team_a_id=None, placeholder="Winner of QF3"
    #   Final: both team_ids=None
```

### Test 2: Round Robin (<8 teams)

```python
def test_inject_teams_round_robin_4_teams():
    """Verify RR pairings for 4 teams"""
    # Setup: Create event with 4 teams
    # Generate RR matches (6 matches for 4 teams)
    # Call inject_teams
    # Assert:
    #   All 6 matches have team_a_id and team_b_id assigned
    #   Each team plays every other team exactly once
    #   No duplicates
```

### Test 3: Reject >8 Teams

```python
def test_inject_teams_reject_9_teams():
    """Verify 9+ teams rejected"""
    # Setup: Create event with 9 teams
    # Call inject_teams
    # Assert:
    #   Raises HTTPException with 400 status
    #   Error message mentions invalid team count
```

### Test 4: Idempotency

```python
def test_inject_teams_idempotent():
    """Running inject twice produces identical assignments"""
    # Setup: Create event with 8 teams
    # Call inject_teams → capture team assignments
    # Call inject_teams again → capture new assignments
    # Assert:
    #   All team_a_id values identical
    #   All team_b_id values identical
    #   Assignment is deterministic
```

### Test 5: Deterministic Tie-Breaking

```python
def test_inject_teams_deterministic_tie_breaking():
    """Same teams with same seeds always get same positions"""
    # Setup: Create 3 events with identical teams (same seeds, ratings)
    # Generate matches for each
    # Call inject_teams on each
    # Assert:
    #   All three events have identical team assignments
    #   Tie-breaking by rating, then registration_timestamp, then ID is stable
```

### Test 6: No Premature Resolution

```python
def test_inject_teams_no_premature_resolution():
    """SF/Finals remain placeholders after injection"""
    # Setup: 8-team bracket
    # Call inject_teams
    # Assert:
    #   QFs have team_ids
    #   SFs have team_a_id=None, team_b_id=None
    #   Final has team_a_id=None, team_b_id=None
    #   Placeholders like "Winner of QF1" still present
```

---

## Grid Display Updates

### Current (V1 - No Teams)

```
┌─────────────┬─────────────────┐
│ 9:00 AM     │ MAIN R1 #1      │
│             │ 120min          │
│             │ MAIN_QF1        │
└─────────────┴─────────────────┘
```

### After Team Injection

**With teams assigned:**
```
┌─────────────┬──────────────────┐
│ 9:00 AM     │ MAIN R1 #1       │
│             │ Smash Bros       │
│             │ vs               │
│             │ Net Ninjas       │
│             │ 120min           │
└─────────────┴──────────────────┘
```

**Without teams (placeholder):**
```
┌─────────────┬──────────────────┐
│ 10:30 AM    │ MAIN R2 #1       │
│             │ Winner of QF1    │
│             │ vs               │
│             │ Winner of QF2    │
│             │ 120min           │
└─────────────┴──────────────────┘
```

---

## Implementation Checklist

### Phase 1: Data Model
- [ ] Create `Team` model
- [ ] Add `team_a_id` and `team_b_id` to `Match` model
- [ ] Add teams relationship to `Event` model
- [ ] Create migration `008_add_teams_and_team_assignments.py`
- [ ] Run migration on dev database
- [ ] Verify schema with tests

### Phase 2: Team Management API
- [ ] POST create team
- [ ] GET list teams
- [ ] PATCH update team
- [ ] DELETE delete team
- [ ] Add validation (unique names per event)

### Phase 3: Team Injection Logic
- [ ] Implement deterministic team sorting
- [ ] Implement bracket seed mapping
- [ ] Implement RR pairing algorithm
- [ ] Implement team assignment logic
- [ ] Add team count validation guard

### Phase 4: Injection API Endpoint
- [ ] POST inject-teams endpoint
- [ ] Request/response models
- [ ] Integration with match inventory
- [ ] Idempotency handling (clear before inject)

### Phase 5: Update Existing Endpoints
- [ ] Update GET /matches to include team data
- [ ] Update GET /schedule/grid to include team data
- [ ] Update MatchResponse schema
- [ ] Update GridMatch schema

### Phase 6: Frontend Updates
- [ ] Update grid component to display teams
- [ ] Add team name labels
- [ ] Distinguish concrete vs placeholder
- [ ] Update TypeScript types
- [ ] Add team injection UI button (optional)

### Phase 7: Testing
- [ ] Test: 8-team bracket seed assignment
- [ ] Test: RR (<8 teams) pairing
- [ ] Test: Reject >8 teams
- [ ] Test: Idempotency
- [ ] Test: Deterministic tie-breaking
- [ ] Test: No premature resolution
- [ ] Integration test: Full flow

---

## Acceptance Criteria

Team Injection V1 is complete when:

1. ✅ **Bracket QFs have concrete team IDs**
   - 8-team bracket QF1-QF4 have team_a_id and team_b_id assigned
   - Assignment follows seed mapping rules

2. ✅ **RR matches have team IDs**
   - All RR matches (<8 teams) have both teams assigned
   - Every team plays every other team exactly once

3. ✅ **Later-stage placeholders remain**
   - SF, Finals, Consolation matches have team_ids=NULL
   - Placeholders like "Winner of QF1" preserved

4. ✅ **Grid displays teams**
   - When team_id is present: Show team name
   - When team_id is NULL: Show placeholder text
   - Clear visual distinction

5. ✅ **Deterministic and repeatable**
   - Same inputs → same outputs
   - All tests passing
   - Idempotent injection

6. ✅ **No team data in Grid V1**
   - Grid V1 (pre-injection) still works
   - No team names shown before injection
   - Backwards compatible

---

## Dependencies & Risks

### Dependencies
- Match generation must be complete before injection
- Event must have teams created before injection
- Seed/rating data must be set before injection for proper ordering

### Risks
- **Risk:** Teams created/modified after injection
  - **Mitigation:** Re-run injection to update (idempotent)
  
- **Risk:** Match inventory doesn't match expected format
  - **Mitigation:** Validate match inventory before injection
  
- **Risk:** Tie-breaking ambiguity if all sort keys are identical
  - **Mitigation:** Use team.id as final tie-breaker (always unique)

### Out of Scope for V1
- Match result entry
- Winner/loser resolution
- Dynamic bracket progression
- Home/away designation
- Multi-event team sharing
- Team stats/history

---

## Status

**Current State:** SPECIFICATION COMPLETE

**Next Step:** Review and approve specification before implementation

**Estimated Implementation:** 
- Backend: 6-8 hours
- Frontend: 3-4 hours
- Testing: 3-4 hours
- Total: ~13-16 hours

**Blocking Issues:** None - ready to implement once approved

