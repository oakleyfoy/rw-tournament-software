# Step 1 — Limited-Audience Deploy Gate (Phase 3E)

## Pre-deploy verification ✅

- [x] Backend: `cd backend && python -m pytest -q` → **147 passed, 5 skipped**
- [x] Frontend: `cd frontend && npm run build` → **success**
- [x] Limited-audience artifact: `npm run build:editor-on` → **success** (output in `frontend/dist/`)

---

## Deploy (you do this)

1. **Produce artifact** (already done locally, or in CI):
   ```bash
   cd "C:\RW Tournament Software\frontend"
   npm run build:editor-on
   ```
2. **Deploy** `frontend/dist/` to your **limited environment** (staging/beta):
   - Path A: Copy entire `dist/` folder to staging web root (replace previous bundle).
   - Path B: In CI, set `VITE_ENABLE_MANUAL_EDITOR=true` at build time for the limited env only. Do **not** enable in production yet.

---

## Smoke tests (run on limited env URL, in this order)

Use your **limited environment base URL** (e.g. `https://staging.example.com`). Replace `{BASE}` and tournament id `1` if different.

| # | Check | How | Expect |
|---|--------|-----|--------|
| 1 | **Visibility gate** | Visit `{BASE}/tournaments/1/schedule` | Purple “✏️ Open Manual Schedule Editor” button is visible |
| 2 | **Editor loads** | Click the button | 3 columns render: Queue \| Grid \| Conflicts |
| 3 | **Network sanity** | DevTools → Network | `GET .../schedule/versions` → 200, `GET .../schedule/grid` → 200, `GET .../schedule/conflicts` → 200 |
| 4 | **Drag/drop reassignment** | Drag one assignment to a new slot | PATCH → 200; conflicts panel refreshes and stays consistent |
| 5 | **Final version read-only** | Switch to a finalized version | UI prevents editing; if forced, backend rejects mutation |
| 6 | **Clone-to-draft** | Trigger clone | New draft created; editing allowed on draft |

If any fail: stop and note the **failing test #** and **console/network error text**.

---

## Reply format (send this after smoke tests)

**If all smoke tests 1–6 pass:**

> ✅ Step 1 approved  
> (a) Limited env URL: `https://your-staging-url/tournaments/1/schedule`  
> (b) Smoke tests 1–6 pass

**If something fails:**

> ❌ Step 1 blocked  
> Failing test #: [number]  
> Console/network error: [paste exact text]

---

## Rollback (before expanding audience)

To roll back the limited audience:

- Redeploy the **previous** `dist/` artifact, **or**
- Rebuild with editor OFF and redeploy:
  ```bash
  cd "C:\RW Tournament Software\frontend"
  npm run build:editor-off
  ```
  Then deploy the new `dist/`.

---

## Deep test (optional, 30–45 min, after smoke passes)

When you have uninterrupted time:

- Move that should fail **duration-fit** → confirm **422** and clear message
- Move that violates **round dependency** → confirm blocked
- **WF vs MAIN** stage ordering → confirm blocked
- Refresh conflicts panel 3–5 times → order does not flip-flop (deterministic)
