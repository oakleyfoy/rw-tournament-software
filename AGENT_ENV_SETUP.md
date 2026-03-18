# Agent Environment Setup

Use this repository-level script to bootstrap dependencies for cloud/local agents.

## Quick start

```bash
scripts/prepare-agent-env.sh
```

By default this installs backend Python dependencies from
`backend/requirements.txt` (including `pytest`) for fast startup.

## Modes

```bash
# Backend only (Python dependencies)
scripts/prepare-agent-env.sh --backend-only

# Frontend only (Node dependencies)
scripts/prepare-agent-env.sh --frontend-only

# Full setup (backend + frontend)
scripts/prepare-agent-env.sh --full
```

## Validation commands

```bash
cd backend && python3 -m pytest tests/test_sms_phase1.py tests/test_sms_phase2.py
cd frontend && npm run build
```

## Suggested prompt for environment setup agents

Use this prompt in the environment setup workflow:

> Configure the cloud agent environment for this repository so startup runs `scripts/prepare-agent-env.sh` (backend-only fast path) by default, with `scripts/prepare-agent-env.sh --full` available for frontend work. Ensure Python 3.12 and Node/npm are available, and verify backend tests run with `python3 -m pytest` from `/workspace/backend`.
