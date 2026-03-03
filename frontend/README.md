# RW Tournament Software - Frontend

## Setup

Recommended (from repository root):
```bash
scripts/prepare-agent-env.sh --frontend-only
```

Manual setup (from `frontend/`):
1. Install dependencies:
```bash
npm ci
```

2. Start development server:
```bash
npm run dev
```

The app will be available at http://localhost:3000

## Build check

```bash
npm run build
```

## Features

### Phase 1B Implementation

- **Tournament List** (`/tournaments`)
  - Displays all tournaments in a table
  - Click row to navigate to setup
  - Create new tournament button

- **Tournament Setup** (`/tournaments/:id/setup`)
  - Section 1: Tournament Information
  - Section 2: Days & Courts Table
  - Section 3: Events Table
  - Section 4: Phase 1 Status & Proceed Button

## API Client

All API calls are centralized in `src/api/client.ts` with TypeScript types.

## Environment Variables

Create a `.env` file to configure the API base URL:
```
VITE_API_BASE_URL=http://localhost:8000/api
```

If not set, defaults to `http://localhost:8000/api`.

