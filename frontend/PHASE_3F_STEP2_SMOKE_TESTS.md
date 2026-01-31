# Phase 3F Step 2 — Auto-Assign Assist UI — Smoke Tests

Run these on `/tournaments/{id}/schedule` (and optionally in the Manual Editor) after deploying.

## 1. Draft version: run auto-assign → unassigned decreases, conflicts update

- Select a **draft** schedule version.
- Open **Auto-Assign Assist** panel (below Build Schedule).
- Click **⚡ Run Auto-Assign (fills unassigned, respects 🔒 locked)**.
- **Expect:** Request completes; grid refreshes; conflicts summary updates; panel shows "Last run" delta (assigned / unassigned / rate change).
- **Optional:** In Manual Editor, click **⚡ Run Auto-Assign** in the header; grid and conflicts panel refresh.

## 2. Locked assignments remain unchanged

- In Manual Editor, lock one or more assignments (or rely on existing locked assignments from a prior manual move).
- Run Auto-Assign (from schedule page or editor).
- **Expect:** Locked slots stay assigned to the same match; only unassigned matches are filled.

## 3. Final version: button disabled (or backend rejects cleanly)

- Select a **final** schedule version.
- **Expect:** "Run Auto-Assign" button is **disabled** (and tooltip explains draft-only).
- If you force a build on final (e.g. via API), backend should return an error and no refresh.

## Verification commands

```bash
cd "C:\RW Tournament Software\frontend"
npm run dev:editor-on
```

Open: `/tournaments/1/schedule`

- Draft selected → button enabled.
- Click → observe before/after delta + grid updates.
- Switch to final version → button disabled.

```bash
npm run build
```

Must succeed with no errors.
