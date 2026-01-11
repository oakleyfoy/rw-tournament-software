# Frontend Quick Start

## Prerequisites

- Node.js 18+ installed
- Backend server running on http://localhost:8000

## Setup

1. Install dependencies:
```bash
cd frontend
npm install
```

2. Start the development server:
```bash
npm run dev
```

The frontend will be available at http://localhost:3000

## Features

### Tournament List (`/tournaments`)
- View all tournaments in a table
- Click any row to open tournament setup
- Click "Create Tournament" to create a new tournament

### Tournament Setup (`/tournaments/:id/setup`)

#### Section 1: Tournament Information
- Edit tournament details (name, location, timezone, dates, notes)
- Save button to persist changes

#### Section 2: Days & Courts
- Table showing all tournament days
- Toggle active/inactive for each day
- Set start time, end time, and courts available for active days
- Validation: Active days require times and at least 1 court
- Bulk save button

#### Section 3: Events
- List all events for the tournament
- Add new events (category, name, team count, notes)
- Edit existing events inline
- Delete events
- Validation: Team count must be >= 2

#### Section 4: Phase 1 Status
- Shows readiness status (Ready/Not Ready)
- Displays summary (active days, court minutes, event count)
- Lists any validation errors
- "Proceed to Draw Builder" button (enabled only when ready)

## Validation

- **Team Count**: Must be at least 2 (numeric validation)
- **Courts Available**: Must be at least 1 for active days (numeric validation)
- **Times**: End time must be greater than start time for active days
- **Backend Errors**: Displayed as toast notifications with clear messages

## Error Handling

- API errors are caught and displayed as toast notifications
- Validation errors shown inline below input fields
- Backend validation errors (Pydantic) are parsed and displayed clearly

