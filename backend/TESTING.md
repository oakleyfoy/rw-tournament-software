# Testing Guide

This guide explains how to test the RW Tournament Software backend.

## Prerequisites

1. Python 3.8+ installed
2. Virtual environment (recommended)

## Setup

### 1. Install Dependencies

```bash
cd backend
pip install -r requirements.txt
```

### 2. Run Database Migrations

```bash
# From the backend directory
alembic upgrade head
```

This creates the database tables. By default, it uses SQLite (`tournament.db`).

## Automated Testing (Pytest)

Run all tests:

```bash
pytest
```

Run with verbose output:

```bash
pytest -v
```

Run a specific test file:

```bash
pytest tests/test_tournaments.py
```

Run a specific test:

```bash
pytest tests/test_tournaments.py::test_create_tournament_auto_creates_days
```

Run with coverage:

```bash
pytest --cov=app --cov-report=html
```

## Manual API Testing

### 1. Start the Server

```bash
uvicorn app.main:app --reload
```

The API will be available at `http://localhost:8000`

### 2. API Documentation

Once the server is running, visit:
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

### 3. Test Endpoints Manually

#### Create a Tournament

```bash
curl -X POST "http://localhost:8000/api/tournaments" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Summer Tournament 2026",
    "location": "Tennis Club",
    "timezone": "America/New_York",
    "start_date": "2026-07-15",
    "end_date": "2026-07-17",
    "notes": "Annual summer tournament"
  }'
```

#### List Tournaments

```bash
curl http://localhost:8000/api/tournaments
```

#### Get Tournament Details

```bash
curl http://localhost:8000/api/tournaments/1
```

#### Get Tournament Days

```bash
curl http://localhost:8000/api/tournaments/1/days
```

#### Update Days (Bulk)

```bash
curl -X PUT "http://localhost:8000/api/tournaments/1/days" \
  -H "Content-Type: application/json" \
  -d '{
    "days": [
      {
        "date": "2026-07-15",
        "is_active": true,
        "start_time": "08:00:00",
        "end_time": "18:00:00",
        "courts_available": 4
      },
      {
        "date": "2026-07-16",
        "is_active": true,
        "start_time": "09:00:00",
        "end_time": "17:00:00",
        "courts_available": 3
      }
    ]
  }'
```

#### Create Event

```bash
curl -X POST "http://localhost:8000/api/tournaments/1/events" \
  -H "Content-Type: application/json" \
  -d '{
    "category": "mixed",
    "name": "Mixed Doubles",
    "team_count": 16,
    "notes": "Main mixed doubles event"
  }'
```

#### Get Events

```bash
curl http://localhost:8000/api/tournaments/1/events
```

#### Check Phase 1 Status

```bash
curl http://localhost:8000/api/tournaments/1/phase1-status
```

## Testing Checklist

### ✅ Task A1 - Database Models
- [ ] Run `alembic upgrade head` successfully
- [ ] Verify tables created: `tournament`, `tournamentday`, `event`
- [ ] Check unique constraints exist

### ✅ Task A2 - Tournament CRUD
- [ ] Create tournament - should auto-generate days
- [ ] List tournaments
- [ ] Get tournament by ID
- [ ] Update tournament - verify days are managed correctly
- [ ] Validation: end_date < start_date should fail
- [ ] Validation: empty timezone should fail

### ✅ Task A3 - Days Endpoints
- [ ] Get tournament days
- [ ] Bulk update days
- [ ] Validation: active day with courts < 1 should fail
- [ ] Validation: active day with end_time <= start_time should fail
- [ ] Inactive day with 0 courts should be allowed

### ✅ Task A4 - Events CRUD
- [ ] Create event
- [ ] List events
- [ ] Update event
- [ ] Delete event
- [ ] Validation: team_count < 2 should fail
- [ ] Validation: empty name should fail
- [ ] Unique constraint: duplicate (category, name) should fail

### ✅ Task A5 - Phase 1 Status
- [ ] Initially should return `is_ready: false`
- [ ] After adding events and courts, should return `is_ready: true`
- [ ] Should calculate total_court_minutes correctly
- [ ] Should include specific error messages

### ✅ Task A6 - Tests
- [ ] All pytest tests pass
- [ ] Test coverage is adequate

## Using Python Requests (Alternative)

If you prefer Python for testing:

```python
import requests

BASE_URL = "http://localhost:8000/api"

# Create tournament
response = requests.post(f"{BASE_URL}/tournaments", json={
    "name": "Test Tournament",
    "location": "Test Location",
    "timezone": "America/New_York",
    "start_date": "2026-07-15",
    "end_date": "2026-07-17"
})
tournament = response.json()
tournament_id = tournament["id"]

# Get days
days = requests.get(f"{BASE_URL}/tournaments/{tournament_id}/days").json()

# Update days
requests.put(f"{BASE_URL}/tournaments/{tournament_id}/days", json={
    "days": [{
        "date": days[0]["date"],
        "is_active": True,
        "start_time": "08:00:00",
        "end_time": "18:00:00",
        "courts_available": 4
    }]
})

# Create event
requests.post(f"{BASE_URL}/tournaments/{tournament_id}/events", json={
    "category": "mixed",
    "name": "Mixed Doubles",
    "team_count": 16
})

# Check status
status = requests.get(f"{BASE_URL}/tournaments/{tournament_id}/phase1-status").json()
print(status)
```

## Troubleshooting

### Migration Issues
- If migration fails, check `alembic.ini` database URL
- Delete `tournament.db` and run `alembic upgrade head` again

### Import Errors
- Make sure you're in the `backend` directory
- Ensure virtual environment is activated
- Run `pip install -r requirements.txt` again

### Test Failures
- Check that all dependencies are installed
- Verify database is clean (tests use in-memory SQLite)
- Run with `-v` flag for detailed output

