# RW Tournament Software

Tournament operations platform for racket sports events, including draw generation, scheduling, desk operations, public pages, and SMS infrastructure.

## Quick start

Bootstrap this repository for local or cloud-agent work:

```bash
scripts/prepare-agent-env.sh
```

Backend-only bootstrap:

```bash
scripts/prepare-agent-env.sh --backend-only
```

Frontend-only bootstrap:

```bash
scripts/prepare-agent-env.sh --frontend-only
```

## Validate setup

```bash
cd backend && python3 -m pytest tests/test_sms_phase1.py tests/test_sms_phase2.py
cd frontend && npm run build
```

## Documentation map

- Agent environment setup: [`AGENT_ENV_SETUP.md`](./AGENT_ENV_SETUP.md)
- Backend guide: [`backend/README.md`](./backend/README.md)
- Frontend guide: [`frontend/README.md`](./frontend/README.md)
