# RW Tournament Software - Backend

## Phase 1A Implementation

This backend implements the tournament management system with the following features:

### Database Models

- **Tournament**: Main tournament entity with dates, location, timezone
- **TournamentDay**: Individual days within a tournament with court availability
- **Event**: Tournament events (Mixed/Women's) with team counts

### API Endpoints

#### Tournaments
- `GET /api/tournaments` - List all tournaments
- `POST /api/tournaments` - Create tournament (auto-generates days)
- `GET /api/tournaments/{id}` - Get tournament details
- `PUT /api/tournaments/{id}` - Update tournament (manages days on date range changes)

#### Tournament Days
- `GET /api/tournaments/{id}/days` - Get all days for a tournament
- `PUT /api/tournaments/{id}/days` - Bulk update days (courts, times, active status)

#### Events
- `GET /api/tournaments/{id}/events` - Get all events for a tournament
- `POST /api/tournaments/{id}/events` - Create event
- `PUT /api/events/{event_id}` - Update event
- `DELETE /api/events/{event_id}` - Delete event

#### Phase 1 Status
- `GET /api/tournaments/{id}/phase1-status` - Get readiness status for Phase 2

### Setup

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Run migrations:
```bash
alembic upgrade head
```

3. Start the server:
```bash
uvicorn app.main:app --reload
```

### Testing

Run tests with:
```bash
pytest
```

### Database

By default, uses SQLite (`sqlite:///./tournament.db`). To use PostgreSQL, set the `DATABASE_URL` environment variable.

