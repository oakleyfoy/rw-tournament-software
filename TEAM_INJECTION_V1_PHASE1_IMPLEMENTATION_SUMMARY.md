# Team Injection V1 — Phase 1 Implementation Summary

**Date:** January 7, 2026  
**Phase:** Data Model (Foundational)  
**Status:** ✅ COMPLETE — All Acceptance Gates Passed

---

## Overview

Phase 1 establishes the foundational data model for Team Injection V1. This includes creating a `Team` model/table and adding nullable team foreign key fields to the `Match` model. The implementation ensures backward compatibility with existing schedules that don't have teams assigned.

---

## 1.1 Create Teams Table/Model

### Changes Made

#### New Model: `backend/app/models/team.py`

Created a new `Team` SQLModel with the following schema:

```python
class Team(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    event_id: int = Field(foreign_key="event.id", index=True)
    name: str  # Team name (required)
    seed: Optional[int] = Field(default=None)  # 1-based seed
    rating: Optional[float] = Field(default=None)  # For tie-breaking
    registration_timestamp: Optional[datetime] = Field(default=None)  # For tie-breaking
    created_at: datetime = Field(default_factory=datetime.utcnow)
```

**Constraints:**
- **Primary Key:** `id`
- **Foreign Key:** `event_id` → `event.id`
- **Unique Constraint:** `(event_id, seed)` — Enforces deterministic seeds within an event
- **Unique Constraint:** `(event_id, name)` — Prevents duplicate team names within an event

**Relationships:**
- `event: Event` — Back-reference to parent event
- `matches_as_team_a: List[Match]` — Matches where this team is side A
- `matches_as_team_b: List[Match]` — Matches where this team is side B

#### Updated Model: `backend/app/models/event.py`

Added relationship to teams:

```python
teams: List["Team"] = Relationship(back_populates="event")
```

#### Updated: `backend/app/models/__init__.py`

Added `Team` to model imports and exports.

### Database Migration

**File:** `backend/alembic/versions/008_add_teams_and_team_assignments.py`

Migration creates the `team` table with:
- All fields as specified in the model
- Index on `event_id` for fast lookups
- Unique constraints on `(event_id, seed)` and `(event_id, name)`

**Note:** SQLite limitations mean foreign key constraints are enforced at the ORM level rather than being added as explicit ALTER TABLE constraints.

### Testing & Verification

**Test Results:**
- ✅ Migration applied cleanly on SQLite
- ✅ CRUD operations work correctly:
  - **Create:** Successfully inserted team linked to an event
  - **Read:** Retrieved team with all fields intact
  - **Update:** Modified team name and rating
  - **Delete:** Cleaned up test teams
- ✅ Unique constraints enforced:
  - Duplicate `(event_id, seed)` rejected with `IntegrityError`
  - Duplicate `(event_id, name)` rejected with `IntegrityError`
  - Teams with `NULL` seeds allowed (multiple per event)

---

## 1.2 Add Nullable FK Fields to Match

### Changes Made

#### Updated Model: `backend/app/models/match.py`

Added team assignment fields to the `Match` model:

```python
# Team assignments (nullable - populated by team injection)
team_a_id: Optional[int] = Field(default=None, foreign_key="team.id")
team_b_id: Optional[int] = Field(default=None, foreign_key="team.id")

# Placeholder text (always present, used when team_ids are null or for display)
placeholder_side_a: str
placeholder_side_b: str
```

**Important:** Existing placeholder fields (`placeholder_side_a`, `placeholder_side_b`) are **retained** and **not renamed**. They continue to work for matches without team assignments.

**Relationships:**
```python
team_a: Optional["Team"] = Relationship(
    back_populates="matches_as_team_a",
    sa_relationship_kwargs={"foreign_keys": "Match.team_a_id"}
)
team_b: Optional["Team"] = Relationship(
    back_populates="matches_as_team_b",
    sa_relationship_kwargs={"foreign_keys": "Match.team_b_id"}
)
```

#### Updated API Responses: `backend/app/routes/schedule.py`

**MatchResponse Model:**
```python
class MatchResponse(BaseModel):
    # ... existing fields ...
    team_a_id: Optional[int] = None
    team_b_id: Optional[int] = None
```

**GridMatch Model:**
```python
class GridMatch(BaseModel):
    # ... existing fields ...
    team_a_id: Optional[int] = None
    team_b_id: Optional[int] = None
    placeholder_side_a: str
    placeholder_side_b: str
```

**Endpoints Updated:**
1. `GET /api/tournaments/{tournament_id}/schedule/matches`
   - Now returns `team_a_id` and `team_b_id` fields
   - Fields are `null` for matches without team assignments
   
2. `GET /api/tournaments/{tournament_id}/schedule/grid`
   - `GridMatch` objects now include team IDs and placeholders
   - Enables UI to display both team info (when available) and placeholders

### Database Migration

**File:** `backend/alembic/versions/008_add_teams_and_team_assignments.py` (same as 1.1)

Migration adds:
- `team_a_id` column to `match` table (nullable, integer)
- `team_b_id` column to `match` table (nullable, integer)

**SQLite Note:** Foreign keys are enforced by SQLModel at the ORM level. Explicit FK constraints are not added via ALTER TABLE due to SQLite limitations.

### Testing & Verification

**Test Results:**
- ✅ `GET /api/tournaments/{id}/schedule/matches` works
  - Status: `200 OK`
  - Returns `team_a_id` and `team_b_id` fields
  - Fields are `null` for existing matches (backward compatible)
  
- ✅ `GET /api/tournaments/{id}/schedule/grid` works
  - Status: `200 OK`
  - Returns `team_a_id`, `team_b_id`, `placeholder_side_a`, `placeholder_side_b`
  - Grid matches include all necessary fields for UI display

- ✅ Existing schedules work without errors
  - All 52 matches in test tournament returned successfully
  - No schema errors or missing field exceptions

---

## Database Schema Changes

### New Table: `team`

| Column                     | Type     | Nullable | Constraints                         |
|----------------------------|----------|----------|-------------------------------------|
| id                         | INTEGER  | NOT NULL | Primary Key                         |
| event_id                   | INTEGER  | NOT NULL | Foreign Key → event.id, Indexed     |
| name                       | VARCHAR  | NOT NULL | Unique with event_id                |
| seed                       | INTEGER  | NULL     | Unique with event_id (when not null)|
| rating                     | FLOAT    | NULL     |                                     |
| registration_timestamp     | DATETIME | NULL     |                                     |
| created_at                 | DATETIME | NOT NULL |                                     |

**Indexes:**
- `ix_team_event_id` on `event_id`

**Unique Constraints:**
- `uq_event_seed` on `(event_id, seed)`
- `uq_event_team_name` on `(event_id, name)`

### Updated Table: `match`

**New Columns:**

| Column     | Type    | Nullable | Constraints            |
|------------|---------|----------|------------------------|
| team_a_id  | INTEGER | NULL     | Foreign Key → team.id  |
| team_b_id  | INTEGER | NULL     | Foreign Key → team.id  |

**Existing Columns Retained:**
- `placeholder_side_a` (VARCHAR, NOT NULL)
- `placeholder_side_b` (VARCHAR, NOT NULL)

---

## Acceptance Gates

### Phase 1.1 ✅
- ✅ Migration applies cleanly on SQLite
- ✅ CRUD can insert a team row linked to an event
- ✅ Unique constraints work as expected (`(event_id, seed)` and `(event_id, name)`)

### Phase 1.2 ✅
- ✅ `GET /schedule/matches` works and returns `team_a_id` and `team_b_id` fields
- ✅ No schema errors
- ✅ Existing schedules without teams still work (null IDs)

---

## Files Modified

### New Files
- `backend/app/models/team.py` — Team model definition
- `backend/alembic/versions/008_add_teams_and_team_assignments.py` — Database migration

### Modified Files
- `backend/app/models/match.py` — Added team FK fields and relationships
- `backend/app/models/event.py` — Added teams relationship
- `backend/app/models/__init__.py` — Added Team to exports
- `backend/app/routes/schedule.py` — Updated response models to include team fields

---

## Next Steps (Phase 2+)

With the foundational data model in place, the next phases can proceed:

1. **Phase 2:** Team CRUD API endpoints
   - `POST /api/events/{event_id}/teams` — Create teams
   - `GET /api/events/{event_id}/teams` — List teams
   - `PUT /api/events/{event_id}/teams/{team_id}` — Update team
   - `DELETE /api/events/{event_id}/teams/{team_id}` — Delete team

2. **Phase 3:** Team Injection Logic
   - Deterministic placement algorithms (bracket vs. round robin)
   - Update `match.team_a_id` and `match.team_b_id` based on seeding
   - Maintain placeholder text for non-injected matches

3. **Phase 4:** Frontend Integration
   - Team management UI
   - Display team names in match cards
   - Fallback to placeholders when teams not assigned

---

## Summary

**Phase 1 is complete and all acceptance gates have been passed.** The database schema now supports:
- Teams with seeding, ratings, and deterministic constraints
- Nullable team assignments on matches
- Full backward compatibility with existing schedules

The system is ready for Phase 2 implementation (Team CRUD API endpoints).

