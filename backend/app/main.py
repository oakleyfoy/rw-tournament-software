import json
import os
import subprocess
from datetime import datetime
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.auth import (
    require_authenticated_user,
    require_authenticated_user_except_sms_webhooks,
)
from app.database import engine, init_db
from app.db_schema_patch import (
    ensure_event_columns,
    ensure_schedule_slot_columns,
    ensure_sms_log_columns,
    ensure_sms_phone_list_columns,
    ensure_start_over_baseline_assignment_table,
    ensure_team_columns,
    ensure_temporary_player_lookup_columns,
    ensure_tournament_columns,
    ensure_tournament_import_columns,
    ensure_tournament_sms_settings_columns,
    ensure_tournament_time_window_columns,
)
from app.routes import (
    auth,
    avoid_edges,
    debug,
    desk,
    display_board,
    draw_builder,
    events,
    phase1_status,
    plan_report,
    post_draw_corrections,
    public,
    runtime,
    rw_os_import,
    schedule,
    schedule_builder,
    schedule_sanity,
    sms,
    team_import,
    teams,
    time_windows,
    tournament_days,
    tournaments,
    wf_conflicts,
    wf_grouping,
)
from app.services.sms_automation import start_first_match_runner_if_enabled

app = FastAPI(title="RW Tournament Software API")
_DEBUG_LOG_PATH = r"c:\RW Tournament Software\.cursor\debug.log"


def _agent_debug_log(hypothesis_id: str, location: str, message: str, data: dict) -> None:
    try:
        payload = {
            "runId": "pre-fix",
            "hypothesisId": hypothesis_id,
            "location": location,
            "message": message,
            "data": data,
            "timestamp": int(datetime.utcnow().timestamp() * 1000),
        }
        with open(_DEBUG_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(payload, separators=(",", ":")) + "\n")
    except Exception:
        pass


# Get build info
def get_build_info():
    """Get git commit hash or build timestamp"""
    try:
        # Try to get git commit hash
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=os.path.dirname(os.path.dirname(__file__)),
            capture_output=True,
            text=True,
            timeout=2,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass

    # Fallback to build timestamp
    return datetime.now().strftime("%Y%m%d-%H%M%S")


BUILD_HASH = get_build_info()

_cors_origins = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]
_extra = os.getenv("CORS_ORIGINS", "")
if _extra:
    _cors_origins.extend(o.strip() for o in _extra.split(",") if o.strip())

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def agent_request_trace(request: Request, call_next):
    if request.url.path.startswith("/api"):
        # region agent log
        _agent_debug_log(
            "H12",
            "main.py:middleware:entry",
            "api request entry",
            {
                "method": request.method,
                "path": request.url.path,
                "query": str(request.url.query or ""),
                "host": request.headers.get("host"),
                "origin": request.headers.get("origin"),
                "referer": request.headers.get("referer"),
            },
        )
        # endregion
    response = await call_next(request)
    if request.url.path.startswith("/api"):
        # region agent log
        _agent_debug_log(
            "H12",
            "main.py:middleware:return",
            "api request return",
            {
                "method": request.method,
                "path": request.url.path,
                "statusCode": response.status_code,
            },
        )
        # endregion
    return response


# Include routers
_protected_deps = [Depends(require_authenticated_user)]

app.include_router(tournaments.router, prefix="/api", tags=["tournaments"], dependencies=_protected_deps)
app.include_router(tournament_days.router, prefix="/api", tags=["tournament_days"], dependencies=_protected_deps)
app.include_router(events.router, prefix="/api", tags=["events"], dependencies=_protected_deps)
app.include_router(phase1_status.router, prefix="/api", tags=["phase1"], dependencies=_protected_deps)
app.include_router(debug.router, prefix="/api", tags=["debug"], dependencies=_protected_deps)
app.include_router(draw_builder.router, prefix="/api", tags=["draw-builder"], dependencies=_protected_deps)
app.include_router(schedule_builder.router, prefix="/api", tags=["schedule-builder"], dependencies=_protected_deps)
app.include_router(plan_report.router, prefix="/api", tags=["plan-report"], dependencies=_protected_deps)

# Include time_windows router
app.include_router(time_windows.router, prefix="/api", tags=["time_windows"], dependencies=_protected_deps)

# Include schedule router
app.include_router(schedule.router, prefix="/api", tags=["schedule"], dependencies=_protected_deps)
# Phase 4 runtime (match status + scoring; no schedule mutation)
app.include_router(runtime.router, prefix="/api", tags=["runtime"], dependencies=_protected_deps)

# Include schedule sanity-check router
app.include_router(schedule_sanity.router, prefix="/api", tags=["schedule"], dependencies=_protected_deps)

# Include teams router
app.include_router(teams.router, prefix="/api", tags=["teams"], dependencies=_protected_deps)

# Post-draw staff corrections (move division / edit WF R1 matchup)
app.include_router(post_draw_corrections.router, prefix="/api", tags=["post-draw-corrections"], dependencies=_protected_deps)

# Include avoid edges router
app.include_router(avoid_edges.router, prefix="/api", tags=["avoid-edges"], dependencies=_protected_deps)

# Include WF grouping router
app.include_router(wf_grouping.router, prefix="/api", tags=["wf-grouping"], dependencies=_protected_deps)

# Include WF conflicts router
app.include_router(wf_conflicts.router, prefix="/api", tags=["wf-conflicts"], dependencies=_protected_deps)

# Public read-only endpoints (no auth)
app.include_router(public.router, prefix="/api", tags=["public"])

# Desk runtime console (staff-only)
app.include_router(desk.router, prefix="/api", tags=["desk"], dependencies=_protected_deps)

# Tournament TV display boards (staff-only, read-only)
app.include_router(display_board.router, prefix="/api", tags=["display-board"], dependencies=_protected_deps)

# Auth routes
app.include_router(auth.router)

# SMS endpoints (webhooks bypass auth; all other SMS paths still protected)
app.include_router(
    sms.router,
    dependencies=[Depends(require_authenticated_user_except_sms_webhooks)],
)

# Enhanced team import (no extra prefix — router has its own /api/events/{id}/teams/import)
app.include_router(team_import.router, dependencies=_protected_deps)
app.include_router(rw_os_import.router, prefix="/api", dependencies=_protected_deps)
app.include_router(avoid_edges.router, prefix="/api", tags=["avoid-edges"], dependencies=_protected_deps)


@app.on_event("startup")
def on_startup():
    init_db()  # Use centralized init_db() which imports models and creates tables
    ensure_event_columns(engine)
    ensure_tournament_columns(engine)
    ensure_tournament_import_columns(engine)
    ensure_team_columns(engine)
    ensure_sms_log_columns(engine)
    ensure_start_over_baseline_assignment_table(engine)
    ensure_tournament_sms_settings_columns(engine)
    ensure_temporary_player_lookup_columns(engine)
    ensure_sms_phone_list_columns(engine)
    ensure_tournament_time_window_columns(engine)
    ensure_schedule_slot_columns(engine)
    start_first_match_runner_if_enabled()

    # Print all registered routes for debugging (full path stack)
    print("\n" + "=" * 80)
    print("REGISTERED ROUTES (Full Path Stack)")
    print("=" * 80)
    route_count = 0
    for r in app.routes:
        try:
            methods = getattr(r, "methods", None)
            path = getattr(r, "path", None)
            if path:  # Only print routes with paths
                methods_str = ", ".join(sorted(methods)) if methods else "N/A"
                print(f"{methods_str:20} {path}")
                route_count += 1
        except Exception as e:
            print(f"Error reading route: {e}")
    print("=" * 80)
    print(f"Total routes: {route_count}")
    print(f"Build hash: {BUILD_HASH}")
    print("=" * 80 + "\n")


@app.get("/api/health")
def health_check():
    """Diagnostic endpoint to verify which code is running"""
    return {"app_name": "RW Tournament Software API", "build_hash": BUILD_HASH, "status": "healthy"}


# Serve frontend static build in production.
# The build script places the Vite output in backend/static/
_static_dir = Path(__file__).resolve().parent.parent / "static"
if _static_dir.is_dir():
    from fastapi.responses import FileResponse

    app.mount("/assets", StaticFiles(directory=str(_static_dir / "assets")), name="static-assets")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        """Serve the SPA index.html for all non-API routes."""
        file_path = _static_dir / full_path
        if file_path.is_file():
            return FileResponse(str(file_path))
        return FileResponse(str(_static_dir / "index.html"))
else:

    @app.get("/")
    def root():
        return {"message": "RW Tournament Software API (no frontend build found)"}
