# PROJECT_CONTEXT

## System Overview

RW Tournament Software is a full-stack tournament operations platform for racket sports events with advanced draw generation, scheduling, desk operations, public display pages, and SMS infrastructure.

The system supports the full lifecycle:

1. Tournament + event setup
2. Draw generation (Waterfall, Round Robin, Bracket, Placement)
3. Slot generation and assignment
4. Live runtime desk operations (in-progress, paused, delayed, final, default, retired)
5. Public-facing schedule/draw publishing
6. Rescheduling/rebuild workflows for weather and operational disruptions
7. SMS communications (manual currently, auto foundation in place)

Deployment is a single Render web service:
- FastAPI backend serves API and static frontend
- React/Vite frontend built and copied into `backend/static`
- SQLite persisted on Render disk (`/data/tournament.db`)
- Python pinned to 3.12.x for compatibility/stability


## Architecture Layers

### 1) Data Layer
- SQLModel models in `backend/app/models/`
- Alembic migrations + startup schema patching
- Core entities:
  - Tournament, Event, Team
  - Match, MatchAssignment, ScheduleSlot, ScheduleVersion
  - Runtime lock/control models (match/slot/court state)
  - SMS models (`sms_log`, `sms_template`, `tournament_sms_settings`)

### 2) Domain/Service Layer
- Business logic in `backend/app/services/`
- Key engines:
  - Draw plan engine (Waterfall/Bracket/RR generation and wiring)
  - Advancement engine (post-finalization propagation)
  - Sequence/policy scheduling
  - Weather reschedule and rebuild engine
  - Invariant checks (hard-stop/advisory behavior)

### 3) API Layer
- FastAPI routes in `backend/app/routes/`
- Important route domains:
  - `schedule.py` (generation, assignment, policy placement, report)
  - `desk.py` (runtime operations, finalize/default/retire, team notes)
  - `public.py` (read-only public views and published schedule)
  - `sms.py` (manual sends, templates, settings, log)

### 4) Frontend Layer
- React + TypeScript in `frontend/src/`
- Major operational UIs:
  - Schedule phased builder
  - Tournament Desk (courts/grid/weather/teams tabs)
  - Public pages (schedule, waterfall, bracket, round robin)
- `frontend/src/api/client.ts` is the typed API contract hub

### 5) Infrastructure/Runtime Layer
- `build.sh` orchestrates backend+frontend build
- `render.yaml` defines service, env vars, disk mount
- Backend startup initializes DB/model metadata and schema safeguards


## Core Invariants

Invariant framework exists to validate schedule safety after policy placement.

Current hard-stop intent:
- A) Team daily cap (default strict in core policy flow)
- B) Fairness ordering
- C) No unresolved upstream dependencies scheduled

Advisory (non-blocking) behavior currently used:
- Consolation partial-round issues (tracked, not rollback-triggering)
- Spare-court rule checks (spare reservation effectively disabled)

Operational note:
- Weather/rebuild paths intentionally allow more flexibility than full policy flow in some cases; this is a deliberate operational tradeoff.


## SMS System Foundation (Current State)

SMS backend foundation is already implemented and Twilio-ready.

### Implemented
- Twilio service wrapper (`twilio_service.py`)
  - E.164 normalization
  - dry-run fallback when creds absent
- Manual send endpoints:
  - tournament blast
  - team direct
  - match-specific (both teams)
  - timeslot blast
- Template system:
  - default + per-tournament override
- Per-tournament auto-toggle settings model exists
- Send log model exists and records each attempt

### Not fully implemented yet
- Automatic triggers are scaffolded by settings/template types but not fully wired end-to-end:
  - 24h before first match
  - post-match next-match text
  - court/time change text
  - on-deck/up-next auto triggers

### Strategic direction
- Move from team-cell-only targeting to first-class Player model + TeamPlayer mapping
- Add consent/opt-in/opt-out compliance flow
- Add dedupe keys for automation idempotency


## Tournament Engine Structure

### Draw Engine
- Generates canonical match structures by event format:
  - Waterfall rounds
  - Round robin pools
  - Bracket and placement matches
- Handles WF-to-division/bracket wiring and placeholder semantics

### Scheduling Engine
- Creates slots from tournament windows/day-court definitions
- Assigns matches by staged/policy sequence
- Supports rebuild and weather-driven reallocation

### Runtime Desk Engine
- Controls live match state transitions:
  - scheduled → in progress/paused/delayed/final
  - default and retired pathways
- Propagates advancement dependencies on completion
- Supports manual controls and lock workflows

### Public Projection
- Publishes stable read-only projections for schedule and draw pages
- Includes winner indication and display-name/full-name context-specific rendering


## Non-Negotiable Design Principles

1. **Operational correctness over cosmetic convenience**
   - Never sacrifice match dependency correctness or runtime integrity for UI shortcuts.

2. **Deterministic behavior**
   - Draw/schedule operations should be reproducible with stable inputs.

3. **Draft safety**
   - Destructive schedule mutations are draft-gated wherever possible.

4. **Auditability**
   - Log meaningful mutations and communication events (e.g., SMS logs, policy run snapshots).

5. **Fail-safe defaults**
   - If uncertain, prefer non-destructive behavior and explicit operator action.

6. **Clear separation of concerns**
   - Models store state, services enforce domain rules, routes orchestrate I/O, frontend presents workflows.

7. **Incremental extensibility**
   - New capabilities (e.g., player-level SMS automation) must layer onto existing contracts, not break them.

8. **Environment stability**
   - Keep runtime/tooling pinned and deployment deterministic (Python version, build script, persistent DB path).


## Known Operational Rules/Conventions

- Render deployment:
  - Python pinned to 3.12.x
  - persistent disk mounted at `/data`
  - SQLite URL points to `/data/tournament.db`
- Frontend TypeScript build is strict (`tsc` errors are blocking)
- Public display naming:
  - Waterfall R1 center can require full names
  - Other contexts often prefer display/short names
- Weather rebuild tooling includes day split/cutoff controls for practical compression scenarios


## Immediate Roadmap Priorities

1. Player-first identity model (`Player`, `TeamPlayer`) for precise targeting
2. Complete SMS automation trigger wiring with dedupe
3. Add SMS admin UI in frontend (targets, templates, preview, logs, toggles)
4. Harden compliance (opt-in/out + STOP/START handling)
5. Preserve and document invariant policy boundaries between normal policy scheduling and weather/rebuild operations
