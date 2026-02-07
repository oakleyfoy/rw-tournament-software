# Quick Start Testing Guide

## Step 1: Install Dependencies

```bash
cd backend
pip install -r requirements.txt
```

## Step 2: Run Migrations

```bash
alembic upgrade head
```

## Step 3: Run Automated Tests

```bash
pytest -v
```

All tests should pass. This verifies:
- ✅ Tournament creation auto-generates days
- ✅ Validation works correctly
- ✅ Days bulk update validation
- ✅ Events validation
- ✅ Phase 1 status calculation

## Step 4: Start the Server

From the `backend` folder you can:

**Start (first time or after closing):**
- Double-click `start_server.bat`, or
- In a terminal: `uvicorn app.main:app --reload`

**Restart (e.g. after code changes so the new code is loaded):**
- Double-click `restart_server.bat`  
  This stops whatever is using port 8000 and starts the server again. Use this when you’ve changed backend code and want to be sure the new version is running.

If the server is already running in a terminal, you can instead press **Ctrl+C** there, then run `start_server.bat` or `uvicorn app.main:app --reload` again.

## Step 5: Test Manually

### Option A: Use the Interactive API Docs
Visit http://localhost:8000/docs in your browser and test endpoints interactively.

### Option B: Run the Manual Test Script
In a new terminal:

```bash
cd backend
python test_manual.py
```

### Option C: Use curl (examples)

```bash
# Create tournament
curl -X POST "http://localhost:8000/api/tournaments" \
  -H "Content-Type: application/json" \
  -d '{"name":"Test","location":"Test","timezone":"America/New_York","start_date":"2026-07-15","end_date":"2026-07-17"}'

# Get days (replace 1 with your tournament ID)
curl http://localhost:8000/api/tournaments/1/days

# Check phase 1 status
curl http://localhost:8000/api/tournaments/1/phase1-status
```

## Expected Results

After running tests and setting up a tournament with days and events:

1. **Tournament created** → 3 days auto-generated (July 15-17)
2. **Days updated** → Courts and times set
3. **Events created** → At least one event added
4. **Phase 1 status** → `is_ready: true` with calculated court minutes

## Troubleshooting

- **Import errors**: Make sure you're in the `backend` directory and virtual environment is activated
- **Migration errors**: Delete `tournament.db` and run `alembic upgrade head` again
- **Server won't start**: Check if port 8000 is already in use

