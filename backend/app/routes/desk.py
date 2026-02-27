"""
Desk Runtime Console: Staff-only endpoints for live tournament operations.
Now Playing / Up Next, score entry, auto-advancement, working draft management.
"""
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlmodel import Session, select
from sqlalchemy import func

from app.database import get_session
from app.models.event import Event
from app.models.match import Match
from app.models.match_assignment import MatchAssignment
from app.models.schedule_slot import ScheduleSlot
from app.models.schedule_version import ScheduleVersion
from app.models.team import Team
from app.models.match_lock import MatchLock
from app.models.tournament import Tournament
from app.services.advancement_service import apply_advancement_with_details, resolve_all_dependencies
from app.services.reschedule_engine import (
    RescheduleParams,
    compute_reschedule,
    compute_feasibility,
    apply_reschedule,
    SCORING_FORMATS,
    SCORING_FORMAT_LABELS,
    RebuildDayConfig as RebuildDayConfigDC,
    compute_rebuild_preview,
    apply_rebuild,
)

logger = logging.getLogger(__name__)

router = APIRouter()


# ── Response models ─────────────────────────────────────────────────────

_STAGE_MAP = {
    "WF": "WF",
    "RR": "RR",
    "MAIN": "BRACKET",
    "CONSOLATION": "CONS",
    "PLACEMENT": "PLACEMENT",
}

_DIV_LABELS = {
    "BWW": "Division I",
    "BWL": "Division II",
    "BLW": "Division III",
    "BLL": "Division IV",
}

_POOL_LABELS = {
    "POOLA": "Division I",
    "POOLB": "Division II",
    "POOLC": "Division III",
    "POOLD": "Division IV",
}


class DeskMatchItem(BaseModel):
    match_id: int
    match_number: int
    match_code: str
    stage: str
    event_id: int
    event_name: str
    division_name: Optional[str] = None
    day_index: int
    day_label: str
    scheduled_time: Optional[str] = None
    sort_time: Optional[str] = None
    court_name: Optional[str] = None
    status: str
    team1_id: Optional[int] = None
    team1_display: str
    team2_id: Optional[int] = None
    team2_display: str
    score_display: Optional[str] = None
    source_match_a_id: Optional[int] = None
    source_match_b_id: Optional[int] = None
    # Timeline fields
    created_at: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    winner_display: Optional[str] = None
    winner_team_id: Optional[int] = None
    duration_minutes: int = 0
    team1_defaulted: bool = False
    team2_defaulted: bool = False
    team1_notes: Optional[str] = None
    team2_notes: Optional[str] = None
    # Grid fields for drag-and-drop move
    slot_id: Optional[int] = None
    assignment_id: Optional[int] = None
    court_number: Optional[int] = None
    day_date: Optional[str] = None


class BoardCourtSlot(BaseModel):
    court_name: str
    now_playing: Optional[DeskMatchItem] = None
    up_next: Optional[DeskMatchItem] = None
    on_deck: Optional[DeskMatchItem] = None


class SnapshotSlot(BaseModel):
    slot_id: int
    day_date: str
    start_time: str
    end_time: str
    court_number: int
    court_label: str
    block_minutes: int
    is_active: bool = True
    assigned_match_id: Optional[int] = None


class DeskSnapshotResponse(BaseModel):
    tournament_id: int
    tournament_name: str
    version_id: int
    version_status: str
    courts: List[str]
    matches: List[DeskMatchItem]
    now_playing_by_court: Dict[str, DeskMatchItem]
    up_next_by_court: Dict[str, DeskMatchItem]
    on_deck_by_court: Dict[str, DeskMatchItem]
    board_by_court: List[BoardCourtSlot]
    slots: List[SnapshotSlot] = []


class WorkingDraftResponse(BaseModel):
    version_id: int
    version_number: int
    status: str
    notes: Optional[str] = None
    created: bool = False


class FinalizeRequest(BaseModel):
    version_id: int
    score: Optional[str] = None
    winner_team_id: int
    is_default: bool = False
    is_retired: bool = False


class DownstreamUpdate(BaseModel):
    match_id: int
    slot_filled: str
    team_id: int
    team_name: str
    role: str
    next_day: Optional[str] = None
    next_time: Optional[str] = None
    next_court: Optional[str] = None
    opponent: Optional[str] = None


class AdvancementWarning(BaseModel):
    match_id: int
    reason: str
    detail: Optional[str] = None


class FinalizeResponse(BaseModel):
    match: DeskMatchItem
    downstream_updates: List[DownstreamUpdate]
    warnings: List[AdvancementWarning]
    auto_started: Optional[DeskMatchItem] = None


class StatusRequest(BaseModel):
    version_id: int
    status: str


class StatusResponse(BaseModel):
    match_id: int
    status: str


# ── Impact models ────────────────────────────────────────────────────────

class ImpactTarget(BaseModel):
    target_match_number: Optional[int] = None
    target_match_id: Optional[int] = None
    target_slot: Optional[str] = None  # "team_a" or "team_b"
    target_current_team_display: Optional[str] = None
    target_current_team_id: Optional[int] = None
    blocked_reason: Optional[str] = None  # SLOT_ALREADY_SET | TARGET_NOT_FOUND
    advanced: Optional[bool] = None  # set when source match is FINAL


class MatchImpactItem(BaseModel):
    match_id: int
    match_number: int
    match_code: str
    stage: str
    status: str
    team1_display: str
    team2_display: str
    team1_id: Optional[int] = None
    team2_id: Optional[int] = None
    winner_team_id: Optional[int] = None
    winner_target: Optional[ImpactTarget] = None
    loser_target: Optional[ImpactTarget] = None


class ImpactResponse(BaseModel):
    version_id: int
    impacts: List[MatchImpactItem]


# ── Conflict models ──────────────────────────────────────────────────────

MIN_REST_MINUTES = 45

DAILY_MATCH_CAP = 2


class ConflictCheckRequest(BaseModel):
    version_id: int
    action_type: str  # SET_IN_PROGRESS | FINALIZE | MOVE
    match_id: int
    target_slot_id: Optional[int] = None  # required for MOVE


class ConflictItem(BaseModel):
    code: str  # TEAM_ALREADY_PLAYING | DAY_CAP_EXCEEDED | REST_TOO_SHORT
    severity: str = "WARN"
    team_display: str
    message: str
    details: Dict[str, Any] = {}


class ConflictCheckResponse(BaseModel):
    conflicts: List[ConflictItem]


# ── Helpers ─────────────────────────────────────────────────────────────

def _format_score(score_json: Optional[Dict[str, Any]]) -> Optional[str]:
    if not score_json:
        return None
    if isinstance(score_json, str):
        return score_json
    if isinstance(score_json, dict):
        if "display" in score_json:
            return str(score_json["display"])
        if "sets" in score_json and isinstance(score_json["sets"], list):
            return " ".join(
                f"{s.get('a', 0)}-{s.get('b', 0)}" for s in score_json["sets"]
            )
        if "a" in score_json and "b" in score_json:
            return f"{score_json['a']}-{score_json['b']}"
        if "score" in score_json:
            return str(score_json["score"])
    return str(score_json) if score_json else None


def _derive_division(match_code: str, match_type: str) -> Optional[str]:
    if match_type == "RR":
        for pool_code, label in _POOL_LABELS.items():
            if f"_{pool_code}_" in match_code.upper():
                return label
        return None
    for div_code, label in _DIV_LABELS.items():
        if f"_{div_code}_" in match_code:
            return label
    return None


def _team_display(
    team_id: Optional[int],
    placeholder: Optional[str],
    team_map: Dict[int, Team],
) -> str:
    if team_id:
        t = team_map.get(team_id)
        if t:
            return t.display_name or t.name
    return placeholder or "TBD"


def _resolve_version(
    session: Session,
    tournament: Tournament,
    version_id: Optional[int],
) -> ScheduleVersion:
    """Resolve which version to use for the desk snapshot.

    Priority: explicit version_id > active desk draft > published pointer > latest FINAL.
    The desk draft is preferred because it holds live runtime state (IN_PROGRESS, scores).
    """
    if version_id:
        v = session.get(ScheduleVersion, version_id)
        if not v or v.tournament_id != tournament.id:
            raise HTTPException(status_code=404, detail="Schedule version not found")
        return v

    desk_draft = session.exec(
        select(ScheduleVersion).where(
            ScheduleVersion.tournament_id == tournament.id,
            ScheduleVersion.status == "draft",
            ScheduleVersion.notes == DESK_DRAFT_TAG,
        )
    ).first()
    if desk_draft:
        return desk_draft

    if tournament.public_schedule_version_id:
        v = session.get(ScheduleVersion, tournament.public_schedule_version_id)
        if v:
            return v

    latest_final = session.exec(
        select(ScheduleVersion)
        .where(
            ScheduleVersion.tournament_id == tournament.id,
            ScheduleVersion.status == "final",
        )
        .order_by(ScheduleVersion.version_number.desc())
    ).first()
    if latest_final:
        return latest_final

    raise HTTPException(status_code=404, detail="No schedule exists")


def _build_match_items(
    session: Session,
    tournament: Tournament,
    version: ScheduleVersion,
) -> tuple:
    """Build flat match list and court set. Returns (items, courts_set)."""
    all_matches = session.exec(
        select(Match).where(Match.schedule_version_id == version.id)
    ).all()

    if not all_matches:
        return [], set()

    match_ids = [m.id for m in all_matches]
    assignments = session.exec(
        select(MatchAssignment).where(
            MatchAssignment.schedule_version_id == version.id,
            MatchAssignment.match_id.in_(match_ids),
        )
    ).all()
    assignment_map = {a.match_id: a for a in assignments}

    slot_ids = list({a.slot_id for a in assignments})
    slots = session.exec(
        select(ScheduleSlot).where(ScheduleSlot.id.in_(slot_ids))
    ).all() if slot_ids else []
    slot_map = {s.id: s for s in slots}

    team_ids = set()
    for m in all_matches:
        if m.team_a_id:
            team_ids.add(m.team_a_id)
        if m.team_b_id:
            team_ids.add(m.team_b_id)
    teams = session.exec(
        select(Team).where(Team.id.in_(list(team_ids)))
    ).all() if team_ids else []
    team_map = {t.id: t for t in teams}

    event_ids = list({m.event_id for m in all_matches})
    events = session.exec(
        select(Event).where(Event.id.in_(event_ids))
    ).all()
    event_map = {e.id: e for e in events}

    items: List[DeskMatchItem] = []
    courts_set: set = set()

    for m in all_matches:
        ev = event_map.get(m.event_id)
        ev_name = ev.name if ev else "Unknown"
        stage = _STAGE_MAP.get(m.match_type, m.match_type)
        div_name = _derive_division(m.match_code or "", m.match_type or "")

        a = assignment_map.get(m.id)
        slot = slot_map.get(a.slot_id) if a else None

        if slot:
            day_offset = (slot.day_date - tournament.start_date).days + 1
            weekday = slot.day_date.strftime("%A")
            month_day = slot.day_date.strftime("%B %d").replace(" 0", " ")
            day_label = f"{weekday}, {month_day}"

            st = slot.start_time
            if isinstance(st, str):
                sort_time = st[:5] if len(st) >= 5 else st
                parts = st.split(":")
                h, mn = int(parts[0]), int(parts[1]) if len(parts) > 1 else 0
                ampm = "AM" if h < 12 else "PM"
                h12 = h % 12 or 12
                scheduled_time = f"{h12}:{mn:02d} {ampm}"
            else:
                scheduled_time = st.strftime("%I:%M %p").lstrip("0") if st else None
                sort_time = st.strftime("%H:%M") if st else None

            court_label = slot.court_label or str(slot.court_number)
            court_name = f"Court {court_label}" if not court_label.lower().startswith("court") else court_label
            courts_set.add(court_name)
        else:
            day_offset = 0
            day_label = "Unscheduled"
            scheduled_time = None
            sort_time = None
            court_name = None

        status = (m.runtime_status or "SCHEDULED").upper()
        score = _format_score(m.score_json) if status == "FINAL" else None

        winner_disp = None
        if m.winner_team_id and m.winner_team_id in team_map:
            wt = team_map[m.winner_team_id]
            winner_disp = wt.display_name or wt.name or f"Team {m.winner_team_id}"

        items.append(DeskMatchItem(
            match_id=m.id,
            match_number=m.id,
            match_code=m.match_code or "",
            stage=stage,
            event_id=m.event_id,
            event_name=ev_name,
            division_name=div_name,
            day_index=day_offset,
            day_label=day_label,
            scheduled_time=scheduled_time,
            sort_time=sort_time,
            court_name=court_name,
            status=status,
            team1_id=m.team_a_id,
            team1_display=_team_display(m.team_a_id, m.placeholder_side_a, team_map),
            team2_id=m.team_b_id,
            team2_display=_team_display(m.team_b_id, m.placeholder_side_b, team_map),
            score_display=score,
            source_match_a_id=m.source_match_a_id,
            source_match_b_id=m.source_match_b_id,
            created_at=m.created_at.isoformat() if m.created_at else None,
            started_at=m.started_at.isoformat() if m.started_at else None,
            completed_at=m.completed_at.isoformat() if m.completed_at else None,
            winner_display=winner_disp,
            winner_team_id=m.winner_team_id,
            duration_minutes=m.duration_minutes,
            team1_defaulted=bool(team_map.get(m.team_a_id, None) and getattr(team_map[m.team_a_id], 'is_defaulted', False)),
            team2_defaulted=bool(team_map.get(m.team_b_id, None) and getattr(team_map[m.team_b_id], 'is_defaulted', False)),
            team1_notes=getattr(team_map.get(m.team_a_id), 'notes', None) if m.team_a_id else None,
            team2_notes=getattr(team_map.get(m.team_b_id), 'notes', None) if m.team_b_id else None,
            slot_id=slot.id if slot else None,
            assignment_id=a.id if a else None,
            court_number=slot.court_number if slot else None,
            day_date=slot.day_date.isoformat() if slot else None,
        ))

    items.sort(key=lambda x: (x.day_index, x.sort_time or "", x.court_name or ""))
    return items, courts_set


def _match_to_desk_item(
    match: Match,
    session: Session,
    tournament: Tournament,
) -> DeskMatchItem:
    """Convert a single Match to DeskMatchItem (for finalize response)."""
    team_ids = set()
    if match.team_a_id:
        team_ids.add(match.team_a_id)
    if match.team_b_id:
        team_ids.add(match.team_b_id)
    teams = session.exec(
        select(Team).where(Team.id.in_(list(team_ids)))
    ).all() if team_ids else []
    team_map = {t.id: t for t in teams}

    ev = session.get(Event, match.event_id)
    ev_name = ev.name if ev else "Unknown"

    a = session.exec(
        select(MatchAssignment).where(
            MatchAssignment.schedule_version_id == match.schedule_version_id,
            MatchAssignment.match_id == match.id,
        )
    ).first()
    slot = session.get(ScheduleSlot, a.slot_id) if a else None

    if slot:
        day_offset = (slot.day_date - tournament.start_date).days + 1
        weekday = slot.day_date.strftime("%A")
        month_day = slot.day_date.strftime("%B %d").replace(" 0", " ")
        day_label = f"{weekday}, {month_day}"
        st = slot.start_time
        if isinstance(st, str):
            sort_time = st[:5]
            parts = st.split(":")
            h, mn = int(parts[0]), int(parts[1]) if len(parts) > 1 else 0
            ampm = "AM" if h < 12 else "PM"
            h12 = h % 12 or 12
            scheduled_time = f"{h12}:{mn:02d} {ampm}"
        else:
            scheduled_time = st.strftime("%I:%M %p").lstrip("0") if st else None
            sort_time = st.strftime("%H:%M") if st else None
        court_label = slot.court_label or str(slot.court_number)
        court_name = f"Court {court_label}" if not court_label.lower().startswith("court") else court_label
    else:
        day_offset = 0
        day_label = "Unscheduled"
        scheduled_time = None
        sort_time = None
        court_name = None

    status = (match.runtime_status or "SCHEDULED").upper()
    score = _format_score(match.score_json) if status == "FINAL" else None
    stage = _STAGE_MAP.get(match.match_type, match.match_type)
    div_name = _derive_division(match.match_code or "", match.match_type or "")

    winner_disp = None
    if match.winner_team_id:
        wt = team_map.get(match.winner_team_id)
        if wt:
            winner_disp = wt.display_name or wt.name or f"Team {match.winner_team_id}"
        else:
            wt2 = session.get(Team, match.winner_team_id)
            winner_disp = (wt2.display_name or wt2.name) if wt2 else f"Team {match.winner_team_id}"

    return DeskMatchItem(
        match_id=match.id,
        match_number=match.id,
        match_code=match.match_code or "",
        stage=stage,
        event_id=match.event_id,
        event_name=ev_name,
        division_name=div_name,
        day_index=day_offset,
        day_label=day_label,
        scheduled_time=scheduled_time,
        sort_time=sort_time,
        court_name=court_name,
        status=status,
        team1_id=match.team_a_id,
        team1_display=_team_display(match.team_a_id, match.placeholder_side_a, team_map),
        team2_id=match.team_b_id,
        team2_display=_team_display(match.team_b_id, match.placeholder_side_b, team_map),
        score_display=score,
        source_match_a_id=match.source_match_a_id,
        source_match_b_id=match.source_match_b_id,
        created_at=match.created_at.isoformat() if match.created_at else None,
        started_at=match.started_at.isoformat() if match.started_at else None,
        completed_at=match.completed_at.isoformat() if match.completed_at else None,
        winner_display=winner_disp,
        winner_team_id=match.winner_team_id,
        duration_minutes=match.duration_minutes,
        team1_defaulted=bool(team_map.get(match.team_a_id, None) and getattr(team_map[match.team_a_id], 'is_defaulted', False)),
        team2_defaulted=bool(team_map.get(match.team_b_id, None) and getattr(team_map[match.team_b_id], 'is_defaulted', False)),
        team1_notes=getattr(team_map.get(match.team_a_id), 'notes', None) if match.team_a_id else None,
        team2_notes=getattr(team_map.get(match.team_b_id), 'notes', None) if match.team_b_id else None,
        slot_id=slot.id if slot else None,
        assignment_id=a.id if a else None,
        court_number=slot.court_number if slot else None,
        day_date=slot.day_date.isoformat() if slot else None,
    )


# ── C2.1 Desk Snapshot ─────────────────────────────────────────────────

@router.get(
    "/desk/tournaments/{tournament_id}/snapshot",
    response_model=DeskSnapshotResponse,
)
def desk_snapshot(
    tournament_id: int,
    version_id: Optional[int] = Query(None),
    session: Session = Depends(get_session),
):
    """Staff-only snapshot: all matches + now_playing + up_next per court."""
    tournament = session.get(Tournament, tournament_id)
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")

    version = _resolve_version(session, tournament, version_id)
    items, courts_set = _build_match_items(session, tournament, version)

    # Build slots array for the grid view
    all_slots = session.exec(
        select(ScheduleSlot).where(ScheduleSlot.schedule_version_id == version.id)
    ).all()
    all_assignments = session.exec(
        select(MatchAssignment).where(MatchAssignment.schedule_version_id == version.id)
    ).all()
    slot_assignment_map = {a.slot_id: a.match_id for a in all_assignments}

    snapshot_slots: List[SnapshotSlot] = []
    for s in all_slots:
        court_label = s.court_label or str(s.court_number)
        court_display = f"Court {court_label}" if not court_label.lower().startswith("court") else court_label
        courts_set.add(court_display)
        st = s.start_time
        et = s.end_time
        snapshot_slots.append(SnapshotSlot(
            slot_id=s.id,
            day_date=s.day_date.isoformat(),
            start_time=st.strftime("%H:%M") if hasattr(st, "strftime") else str(st)[:5],
            end_time=et.strftime("%H:%M") if hasattr(et, "strftime") else str(et)[:5],
            court_number=s.court_number,
            court_label=court_label,
            block_minutes=s.block_minutes,
            is_active=s.is_active,
            assigned_match_id=slot_assignment_map.get(s.id),
        ))

    courts_sorted = sorted(courts_set, key=lambda c: (
        int("".join(ch for ch in c if ch.isdigit()) or "0"),
        c,
    ))

    now_playing: Dict[str, DeskMatchItem] = {}
    up_next: Dict[str, DeskMatchItem] = {}
    on_deck: Dict[str, DeskMatchItem] = {}

    court_matches: Dict[str, List[DeskMatchItem]] = {}
    for m in items:
        if m.court_name:
            court_matches.setdefault(m.court_name, []).append(m)

    for court, matches in court_matches.items():
        in_progress = [m for m in matches if m.status in ("IN_PROGRESS", "PAUSED")]
        if in_progress:
            now_playing[court] = in_progress[0]

        non_final = [m for m in matches if m.status not in ("FINAL", "IN_PROGRESS", "PAUSED")]
        if non_final:
            up_next[court] = non_final[0]
        if len(non_final) > 1:
            on_deck[court] = non_final[1]

    # Board: now_playing / up_next / on_deck per court (finals excluded)
    board: List[BoardCourtSlot] = []
    for court in courts_sorted:
        cms = court_matches.get(court, [])
        non_final_cms = [m for m in cms if m.status != "FINAL"]

        board_now = None
        board_up = None
        board_on = None

        in_prog = [m for m in non_final_cms if m.status in ("IN_PROGRESS", "PAUSED")]
        if in_prog:
            board_now = in_prog[0]

        remaining = [m for m in non_final_cms if m.match_id != (board_now.match_id if board_now else -1)]
        scheduled = [m for m in remaining if m.status not in ("IN_PROGRESS", "PAUSED")]
        if scheduled:
            board_up = scheduled[0]
        if len(scheduled) > 1:
            board_on = scheduled[1]

        board.append(BoardCourtSlot(
            court_name=court,
            now_playing=board_now,
            up_next=board_up,
            on_deck=board_on,
        ))

    return DeskSnapshotResponse(
        tournament_id=tournament.id,
        tournament_name=tournament.name,
        version_id=version.id,
        version_status=version.status,
        courts=courts_sorted,
        matches=items,
        now_playing_by_court=now_playing,
        up_next_by_court=up_next,
        on_deck_by_court=on_deck,
        board_by_court=board,
        slots=snapshot_slots,
    )


# ── C2.2 Working Draft ─────────────────────────────────────────────────

DESK_DRAFT_TAG = "Desk Draft"


@router.post(
    "/desk/tournaments/{tournament_id}/working-draft",
    response_model=WorkingDraftResponse,
)
def create_working_draft(
    tournament_id: int,
    session: Session = Depends(get_session),
):
    """Create or return existing desk working draft. Idempotent."""
    tournament = session.get(Tournament, tournament_id)
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")

    existing = session.exec(
        select(ScheduleVersion).where(
            ScheduleVersion.tournament_id == tournament_id,
            ScheduleVersion.status == "draft",
            ScheduleVersion.notes == DESK_DRAFT_TAG,
        )
    ).first()
    if existing:
        return WorkingDraftResponse(
            version_id=existing.id,
            version_number=existing.version_number,
            status=existing.status,
            notes=existing.notes,
            created=False,
        )

    # Find source version to clone from
    source_version_id = None
    if tournament.public_schedule_version_id:
        pub = session.get(ScheduleVersion, tournament.public_schedule_version_id)
        if pub:
            source_version_id = pub.id
    if not source_version_id:
        latest_final = session.exec(
            select(ScheduleVersion)
            .where(
                ScheduleVersion.tournament_id == tournament_id,
                ScheduleVersion.status == "final",
            )
            .order_by(ScheduleVersion.version_number.desc())
        ).first()
        if latest_final:
            source_version_id = latest_final.id

    if not source_version_id:
        raise HTTPException(
            status_code=404,
            detail="No FINAL schedule version to clone from",
        )

    # Clone using the shared function from schedule.py
    from app.routes.schedule import _clone_final_to_draft

    new_version = _clone_final_to_draft(tournament_id, source_version_id, session)
    new_version.notes = DESK_DRAFT_TAG
    session.add(new_version)

    # Auto-live: point public to the desk draft so players see results immediately
    tournament.public_schedule_version_id = new_version.id
    session.add(tournament)

    session.commit()
    session.refresh(new_version)

    return WorkingDraftResponse(
        version_id=new_version.id,
        version_number=new_version.version_number,
        status=new_version.status,
        notes=new_version.notes,
        created=True,
    )


# ── C2.3 Finalize Match ────────────────────────────────────────────────

@router.patch(
    "/desk/tournaments/{tournament_id}/matches/{match_id}/finalize",
    response_model=FinalizeResponse,
)
def finalize_match(
    tournament_id: int,
    match_id: int,
    payload: FinalizeRequest,
    session: Session = Depends(get_session),
):
    """Enter score and finalize a match. Auto-advances winner/loser downstream."""
    tournament = session.get(Tournament, tournament_id)
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")

    version = session.get(ScheduleVersion, payload.version_id)
    if not version or version.tournament_id != tournament_id:
        raise HTTPException(status_code=404, detail="Schedule version not found")
    if version.status != "draft":
        raise HTTPException(
            status_code=400,
            detail="Cannot modify matches in a FINAL version. Use a Desk Draft.",
        )

    match = session.get(Match, match_id)
    if not match or match.tournament_id != tournament_id:
        raise HTTPException(status_code=404, detail="Match not found")
    if match.schedule_version_id != payload.version_id:
        raise HTTPException(status_code=400, detail="Match does not belong to this version")

    # Idempotency: if already FINAL with same data, return current state
    if match.runtime_status == "FINAL":
        same_winner = match.winner_team_id == payload.winner_team_id
        same_score = True
        if payload.score is not None:
            existing_score = _format_score(match.score_json)
            same_score = existing_score == payload.score
        if same_winner and same_score:
            desk_item = _match_to_desk_item(match, session, tournament)
            return FinalizeResponse(
                match=desk_item,
                downstream_updates=[],
                warnings=[],
            )
        raise HTTPException(
            status_code=409,
            detail="Match already FINAL with different score/winner",
        )

    # Validate winner is one of the teams
    if payload.winner_team_id not in (match.team_a_id, match.team_b_id):
        raise HTTPException(
            status_code=400,
            detail=f"winner_team_id must be team_a ({match.team_a_id}) or team_b ({match.team_b_id})",
        )

    # Apply finalization
    match.runtime_status = "FINAL"
    match.winner_team_id = payload.winner_team_id
    match.completed_at = datetime.utcnow()
    if payload.is_default:
        dur = match.duration_minutes
        if dur <= 35:
            actual_score = "4-0"
        elif dur <= 60:
            actual_score = "8-0"
        else:
            actual_score = "6-0, 6-0"
        match.score_json = {"display": "DEFAULT", "actual": actual_score}
    elif payload.is_retired:
        actual_score = payload.score or "0-0"
        match.score_json = {"display": f"{actual_score} (RET)", "actual": actual_score}
    elif payload.score is not None:
        match.score_json = {"display": payload.score}
    session.add(match)
    session.commit()
    session.refresh(match)

    # Auto-advance
    adv_result = apply_advancement_with_details(session, match.id)

    # Auto-start next match on the same court
    auto_started_match_id = None
    finalized_assignment = session.exec(
        select(MatchAssignment).where(
            MatchAssignment.schedule_version_id == payload.version_id,
            MatchAssignment.match_id == match.id,
        )
    ).first()
    if finalized_assignment:
        finalized_slot = session.get(ScheduleSlot, finalized_assignment.slot_id)
        if finalized_slot:
            court_num = finalized_slot.court_number
            court_slots = session.exec(
                select(ScheduleSlot).where(
                    ScheduleSlot.schedule_version_id == payload.version_id,
                    ScheduleSlot.court_number == court_num,
                ).order_by(ScheduleSlot.day_date, ScheduleSlot.start_time)
            ).all()
            court_slot_ids = [s.id for s in court_slots]
            if court_slot_ids:
                court_assignments = session.exec(
                    select(MatchAssignment).where(
                        MatchAssignment.schedule_version_id == payload.version_id,
                        MatchAssignment.slot_id.in_(court_slot_ids),
                    )
                ).all()
                slot_order = {sid: i for i, sid in enumerate(court_slot_ids)}
                court_assignments.sort(key=lambda a: slot_order.get(a.slot_id, 0))

                finalized_order = slot_order.get(finalized_assignment.slot_id, -1)
                for ca in court_assignments:
                    if slot_order.get(ca.slot_id, -1) <= finalized_order:
                        continue
                    next_match = session.get(Match, ca.match_id)
                    if next_match and (next_match.runtime_status or "SCHEDULED") == "SCHEDULED":
                        next_match.runtime_status = "IN_PROGRESS"
                        next_match.started_at = datetime.utcnow()
                        session.add(next_match)
                        session.commit()
                        auto_started_match_id = next_match.id
                        break

    desk_item = _match_to_desk_item(match, session, tournament)

    # Enrich downstream updates with schedule info and opponent names
    raw_updates = adv_result.get("downstream_updates", [])

    # Collect all IDs needed for bulk lookups
    down_match_ids = [u["match_id"] for u in raw_updates]
    all_team_ids_needed = set(u["team_id"] for u in raw_updates)

    # Load downstream match objects to get opponent info
    down_matches = session.exec(
        select(Match).where(Match.id.in_(down_match_ids))
    ).all() if down_match_ids else []
    down_match_map = {m.id: m for m in down_matches}

    for dm in down_matches:
        if dm.team_a_id:
            all_team_ids_needed.add(dm.team_a_id)
        if dm.team_b_id:
            all_team_ids_needed.add(dm.team_b_id)

    adv_teams = session.exec(
        select(Team).where(Team.id.in_(list(all_team_ids_needed)))
    ).all() if all_team_ids_needed else []
    adv_team_map = {t.id: t for t in adv_teams}

    # Load assignments and slots for downstream matches
    down_assignments = session.exec(
        select(MatchAssignment).where(
            MatchAssignment.schedule_version_id == payload.version_id,
            MatchAssignment.match_id.in_(down_match_ids),
        )
    ).all() if down_match_ids else []
    down_assign_map = {a.match_id: a for a in down_assignments}

    down_slot_ids = [a.slot_id for a in down_assignments]
    down_slots = session.exec(
        select(ScheduleSlot).where(ScheduleSlot.id.in_(down_slot_ids))
    ).all() if down_slot_ids else []
    down_slot_map = {s.id: s for s in down_slots}

    downstream = []
    for u in raw_updates:
        t = adv_team_map.get(u["team_id"])
        team_name = (t.display_name or t.name) if t else f"Team {u['team_id']}"

        # Schedule info from slot
        next_day = None
        next_time = None
        next_court = None
        a = down_assign_map.get(u["match_id"])
        if a:
            slot = down_slot_map.get(a.slot_id)
            if slot:
                weekday = slot.day_date.strftime("%A")
                month_day = slot.day_date.strftime("%B %d").replace(" 0", " ")
                next_day = f"{weekday}, {month_day}"
                st = slot.start_time
                if isinstance(st, str):
                    parts = st.split(":")
                    h, mn = int(parts[0]), int(parts[1]) if len(parts) > 1 else 0
                    ampm = "AM" if h < 12 else "PM"
                    h12 = h % 12 or 12
                    next_time = f"{h12}:{mn:02d} {ampm}"
                elif st:
                    next_time = st.strftime("%I:%M %p").lstrip("0")
                cl = slot.court_label or str(slot.court_number)
                next_court = f"Court {cl}" if not cl.lower().startswith("court") else cl

        # Opponent: the other team in the downstream match
        opponent = None
        dm = down_match_map.get(u["match_id"])
        if dm:
            opp_id = dm.team_b_id if u["slot_filled"] == "A" else dm.team_a_id
            if opp_id and opp_id != u["team_id"]:
                opp = adv_team_map.get(opp_id)
                opponent = (opp.display_name or opp.name) if opp else None

        downstream.append(DownstreamUpdate(
            match_id=u["match_id"],
            slot_filled=u["slot_filled"],
            team_id=u["team_id"],
            team_name=team_name,
            role=u.get("role", "WINNER"),
            next_day=next_day,
            next_time=next_time,
            next_court=next_court,
            opponent=opponent,
        ))
    warns = [
        AdvancementWarning(
            match_id=w["match_id"],
            reason=w["reason"],
            detail=w.get("detail"),
        )
        for w in adv_result.get("warnings", [])
    ]

    auto_started_item = None
    if auto_started_match_id:
        started_match = session.get(Match, auto_started_match_id)
        if started_match:
            auto_started_item = _match_to_desk_item(started_match, session, tournament)

    return FinalizeResponse(
        match=desk_item,
        downstream_updates=downstream,
        warnings=warns,
        auto_started=auto_started_item,
    )


# ── C2.3b Correct Finalized Match ──────────────────────────────────────

class CorrectMatchRequest(BaseModel):
    version_id: int
    score: str
    winner_team_id: int


@router.patch(
    "/desk/tournaments/{tournament_id}/matches/{match_id}/correct",
    response_model=FinalizeResponse,
)
def correct_match(
    tournament_id: int,
    match_id: int,
    payload: CorrectMatchRequest,
    session: Session = Depends(get_session),
):
    """Correct the score and/or winner of a finalized match."""
    tournament = session.get(Tournament, tournament_id)
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")

    version = session.get(ScheduleVersion, payload.version_id)
    if not version or version.tournament_id != tournament_id:
        raise HTTPException(status_code=404, detail="Schedule version not found")
    if version.status != "draft":
        raise HTTPException(status_code=400, detail="Can only correct matches in a DRAFT version.")

    match = session.get(Match, match_id)
    if not match or match.tournament_id != tournament_id:
        raise HTTPException(status_code=404, detail="Match not found")
    if match.schedule_version_id != payload.version_id:
        raise HTTPException(status_code=400, detail="Match does not belong to this version")
    if (match.runtime_status or "SCHEDULED") != "FINAL":
        raise HTTPException(status_code=400, detail="Match is not finalized — use the normal finalize flow.")

    if payload.winner_team_id not in (match.team_a_id, match.team_b_id):
        raise HTTPException(
            status_code=400,
            detail=f"winner_team_id must be team_a ({match.team_a_id}) or team_b ({match.team_b_id})",
        )

    winner_changed = match.winner_team_id != payload.winner_team_id
    warnings: List[Dict[str, Any]] = []

    if winner_changed:
        downstream_a = session.exec(
            select(Match).where(
                Match.schedule_version_id == payload.version_id,
                Match.source_match_a_id == match_id,
            )
        ).all()
        downstream_b = session.exec(
            select(Match).where(
                Match.schedule_version_id == payload.version_id,
                Match.source_match_b_id == match_id,
            )
        ).all()

        for down in downstream_a:
            if (down.runtime_status or "SCHEDULED") == "FINAL":
                warnings.append({
                    "match_id": down.id,
                    "reason": "DOWNSTREAM_ALREADY_FINAL",
                    "detail": f"Match #{down.id} ({down.match_code}) is already finalized — correct it manually.",
                })
            else:
                down.team_a_id = None
                session.add(down)

        for down in downstream_b:
            if (down.runtime_status or "SCHEDULED") == "FINAL":
                warnings.append({
                    "match_id": down.id,
                    "reason": "DOWNSTREAM_ALREADY_FINAL",
                    "detail": f"Match #{down.id} ({down.match_code}) is already finalized — correct it manually.",
                })
            else:
                down.team_b_id = None
                session.add(down)

    match.winner_team_id = payload.winner_team_id
    match.score_json = {"display": payload.score}
    session.add(match)
    session.commit()
    session.refresh(match)

    adv_result: Dict[str, Any] = {"downstream_updates": [], "warnings": warnings}
    if winner_changed:
        adv = apply_advancement_with_details(session, match.id)
        adv_result["downstream_updates"] = adv.get("downstream_updates", [])
        adv_result["warnings"].extend(adv.get("warnings", []))

    desk_item = _match_to_desk_item(match, session, tournament)

    raw_updates = adv_result.get("downstream_updates", [])
    downstream = []
    if raw_updates:
        down_match_ids = [u["match_id"] for u in raw_updates]
        all_team_ids_needed = set(u["team_id"] for u in raw_updates)
        down_matches = session.exec(select(Match).where(Match.id.in_(down_match_ids))).all()
        down_match_map = {m.id: m for m in down_matches}
        for dm in down_matches:
            if dm.team_a_id:
                all_team_ids_needed.add(dm.team_a_id)
            if dm.team_b_id:
                all_team_ids_needed.add(dm.team_b_id)
        adv_teams = session.exec(select(Team).where(Team.id.in_(list(all_team_ids_needed)))).all()
        adv_team_map = {t.id: t for t in adv_teams}
        down_assignments = session.exec(
            select(MatchAssignment).where(
                MatchAssignment.schedule_version_id == payload.version_id,
                MatchAssignment.match_id.in_(down_match_ids),
            )
        ).all()
        down_assign_map = {a.match_id: a for a in down_assignments}
        down_slot_ids = [a.slot_id for a in down_assignments]
        down_slots = session.exec(select(ScheduleSlot).where(ScheduleSlot.id.in_(down_slot_ids))).all() if down_slot_ids else []
        down_slot_map = {s.id: s for s in down_slots}

        for u in raw_updates:
            t = adv_team_map.get(u["team_id"])
            team_name = (t.display_name or t.name) if t else f"Team {u['team_id']}"
            next_day = next_time = next_court = opponent = None
            a = down_assign_map.get(u["match_id"])
            if a:
                slot = down_slot_map.get(a.slot_id)
                if slot:
                    weekday = slot.day_date.strftime("%A")
                    month_day = slot.day_date.strftime("%B %d").replace(" 0", " ")
                    next_day = f"{weekday}, {month_day}"
                    st = slot.start_time
                    if isinstance(st, str):
                        parts = st.split(":")
                        h, mn = int(parts[0]), int(parts[1]) if len(parts) > 1 else 0
                        ampm = "AM" if h < 12 else "PM"
                        h12 = h % 12 or 12
                        next_time = f"{h12}:{mn:02d} {ampm}"
                    elif st:
                        next_time = st.strftime("%I:%M %p").lstrip("0")
                    cl = slot.court_label or str(slot.court_number)
                    next_court = f"Court {cl}" if not cl.lower().startswith("court") else cl
            dm = down_match_map.get(u["match_id"])
            if dm:
                opp_id = dm.team_b_id if u["slot_filled"] == "A" else dm.team_a_id
                if opp_id and opp_id != u["team_id"]:
                    opp = adv_team_map.get(opp_id)
                    opponent = (opp.display_name or opp.name) if opp else None
            downstream.append(DownstreamUpdate(
                match_id=u["match_id"],
                slot_filled=u["slot_filled"],
                team_id=u["team_id"],
                team_name=team_name,
                role=u.get("role", "WINNER"),
                next_day=next_day,
                next_time=next_time,
                next_court=next_court,
                opponent=opponent,
            ))

    warns = [
        AdvancementWarning(
            match_id=w["match_id"],
            reason=w["reason"],
            detail=w.get("detail"),
        )
        for w in adv_result.get("warnings", [])
    ]

    return FinalizeResponse(
        match=desk_item,
        downstream_updates=downstream,
        warnings=warns,
        auto_started=None,
    )


# ── C2.3c Repair Advancement ────────────────────────────────────────────

@router.post(
    "/desk/tournaments/{tournament_id}/repair-advancement",
)
def repair_advancement(
    tournament_id: int,
    version_id: int = Query(...),
    session: Session = Depends(get_session),
):
    """Re-run advancement for all finalized matches to fix missing WF→bracket wiring."""
    import re

    tournament = session.get(Tournament, tournament_id)
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")
    version = session.get(ScheduleVersion, version_id)
    if not version or version.tournament_id != tournament_id:
        raise HTTPException(status_code=404, detail="Schedule version not found")

    all_matches = session.exec(
        select(Match).where(Match.schedule_version_id == version_id)
    ).all()

    # Phase 1: Fix broken placeholders for BLW/BLL bracket QFs
    # BLW had W09-W16 → should be L01-L08
    # BLL had L09-L16 → should be L01-L08
    placeholder_fixes = 0
    wf_r2_pattern = re.compile(r'^(.+_WF_R2_)([WL])(\d+)$')

    for m in all_matches:
        if m.match_type not in ("MAIN", "CONSOLATION"):
            continue
        mc = m.match_code or ""
        is_blw = "BLW" in mc
        is_bll = "BLL" in mc
        if not is_blw and not is_bll:
            continue

        for side in ("a", "b"):
            ph = m.placeholder_side_a if side == "a" else m.placeholder_side_b
            if not ph:
                continue
            match_ph = wf_r2_pattern.match(ph)
            if not match_ph:
                continue
            prefix_part, track_letter, seq_str = match_ph.groups()
            seq = int(seq_str)
            if seq <= 8:
                continue

            new_seq = seq - 8
            new_ph = f"{prefix_part}L{new_seq:02d}"
            if side == "a":
                m.placeholder_side_a = new_ph
                m.source_match_a_id = None
                m.source_a_role = None
            else:
                m.placeholder_side_b = new_ph
                m.source_match_b_id = None
                m.source_b_role = None
            session.add(m)
            placeholder_fixes += 1

    if placeholder_fixes:
        session.commit()
        logger.info("Repaired %d broken WF→bracket placeholders", placeholder_fixes)

    # Phase 2: Wire placeholders to source matches and re-run advancement
    code_to_match = {m.match_code: m for m in all_matches if m.match_code}
    wired = 0
    for m in all_matches:
        if m.match_type not in ("MAIN", "CONSOLATION"):
            continue
        for side in ("a", "b"):
            ph = m.placeholder_side_a if side == "a" else m.placeholder_side_b
            src = m.source_match_a_id if side == "a" else m.source_match_b_id
            if not ph or src is not None:
                continue
            if ":" in ph:
                parts = ph.split(":", 1)
                role, ref_code = parts[0], parts[1]
                if role in ("WINNER", "LOSER") and ref_code in code_to_match:
                    ref = code_to_match[ref_code]
                    if side == "a":
                        m.source_match_a_id = ref.id
                        m.source_a_role = role
                    else:
                        m.source_match_b_id = ref.id
                        m.source_b_role = role
                    session.add(m)
                    wired += 1
            elif ph in code_to_match:
                ref = code_to_match[ph]
                mc = m.match_code or ""
                if "BWW" in mc or "BLW" in mc:
                    role = "WINNER"
                else:
                    role = "LOSER"
                if side == "a":
                    m.source_match_a_id = ref.id
                    m.source_a_role = role
                else:
                    m.source_match_b_id = ref.id
                    m.source_b_role = role
                session.add(m)
                wired += 1

    if wired:
        session.commit()
        logger.info("Wired %d source links during repair", wired)

    # Phase 3: Re-run advancement for all finalized matches
    result = resolve_all_dependencies(session, version_id)
    result["placeholder_fixes"] = placeholder_fixes
    result["wired"] = wired
    return result


# ── C2.4 Set Match Status ──────────────────────────────────────────────

@router.patch(
    "/desk/tournaments/{tournament_id}/matches/{match_id}/status",
    response_model=StatusResponse,
)
def set_match_status(
    tournament_id: int,
    match_id: int,
    payload: StatusRequest,
    session: Session = Depends(get_session),
):
    """Set match status (SCHEDULED or IN_PROGRESS). Use finalize for FINAL."""
    tournament = session.get(Tournament, tournament_id)
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")

    version = session.get(ScheduleVersion, payload.version_id)
    if not version or version.tournament_id != tournament_id:
        raise HTTPException(status_code=404, detail="Schedule version not found")
    if version.status != "draft":
        raise HTTPException(
            status_code=400,
            detail="Cannot modify matches in a FINAL version. Use a Desk Draft.",
        )

    if payload.status == "FINAL":
        raise HTTPException(
            status_code=400,
            detail="Use the /finalize endpoint to set a match to FINAL.",
        )

    if payload.status not in ("SCHEDULED", "IN_PROGRESS", "PAUSED", "DELAYED"):
        raise HTTPException(
            status_code=400,
            detail="Status must be SCHEDULED, IN_PROGRESS, PAUSED, or DELAYED",
        )

    match = session.get(Match, match_id)
    if not match or match.tournament_id != tournament_id:
        raise HTTPException(status_code=404, detail="Match not found")
    if match.schedule_version_id != payload.version_id:
        raise HTTPException(status_code=400, detail="Match does not belong to this version")

    if match.runtime_status == "FINAL":
        raise HTTPException(
            status_code=400,
            detail="Cannot change status of a FINAL match",
        )

    match.runtime_status = payload.status
    if payload.status == "IN_PROGRESS" and match.started_at is None:
        match.started_at = datetime.utcnow()

    session.add(match)
    session.commit()

    return StatusResponse(match_id=match.id, status=match.runtime_status)


# ── Impact endpoint ──────────────────────────────────────────────────────

@router.get(
    "/desk/tournaments/{tournament_id}/impact",
    response_model=ImpactResponse,
)
def get_impact(
    tournament_id: int,
    version_id: int = Query(...),
    match_id: Optional[int] = Query(None),
    session: Session = Depends(get_session),
):
    """Read-only downstream impact for matches: where winner/loser advance to."""
    tournament = session.get(Tournament, tournament_id)
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")

    version = session.get(ScheduleVersion, version_id)
    if not version or version.tournament_id != tournament_id:
        raise HTTPException(status_code=404, detail="Schedule version not found")

    if match_id:
        all_matches = session.exec(
            select(Match).where(Match.schedule_version_id == version_id)
        ).all()
        target_matches = [m for m in all_matches if m.id == match_id]
        if not target_matches:
            raise HTTPException(status_code=404, detail="Match not found in version")
    else:
        all_matches = session.exec(
            select(Match).where(Match.schedule_version_id == version_id)
        ).all()
        target_matches = all_matches

    match_by_id = {m.id: m for m in all_matches}

    # Build reverse index: upstream_match_id → list of (downstream_match, slot, role)
    downstream_map: Dict[int, List[dict]] = {}
    for m in all_matches:
        if m.source_match_a_id:
            downstream_map.setdefault(m.source_match_a_id, []).append({
                "downstream": m,
                "slot": "team_a",
                "role": (m.source_a_role or "WINNER").upper(),
            })
        if m.source_match_b_id:
            downstream_map.setdefault(m.source_match_b_id, []).append({
                "downstream": m,
                "slot": "team_b",
                "role": (m.source_b_role or "WINNER").upper(),
            })

    # Load team names
    team_ids = set()
    for m in all_matches:
        if m.team_a_id:
            team_ids.add(m.team_a_id)
        if m.team_b_id:
            team_ids.add(m.team_b_id)
        if m.winner_team_id:
            team_ids.add(m.winner_team_id)
    teams = session.exec(select(Team).where(Team.id.in_(list(team_ids)))).all() if team_ids else []
    team_map = {t.id: t for t in teams}

    # Load locks for this version
    locks = session.exec(
        select(MatchLock).where(MatchLock.schedule_version_id == version_id)
    ).all()
    locked_match_ids = {lk.match_id for lk in locks}

    def _team_disp(tid, placeholder):
        if tid and tid in team_map:
            t = team_map[tid]
            return t.display_name or t.name or f"Team {tid}"
        return placeholder or "TBD"

    def _build_target(upstream_match, role, entries) -> Optional[ImpactTarget]:
        """Build impact target for a given role (WINNER or LOSER)."""
        matches_for_role = [e for e in entries if e["role"] == role]
        if not matches_for_role:
            return None

        e = matches_for_role[0]
        ds: Match = e["downstream"]
        slot = e["slot"]  # "team_a" or "team_b"

        current_team_id = ds.team_a_id if slot == "team_a" else ds.team_b_id
        current_placeholder = ds.placeholder_side_a if slot == "team_a" else ds.placeholder_side_b
        current_display = _team_disp(current_team_id, current_placeholder)

        blocked = None
        advanced = None

        if upstream_match.runtime_status == "FINAL" and upstream_match.winner_team_id:
            if role == "WINNER":
                advancing_team = upstream_match.winner_team_id
            else:
                sides = [upstream_match.team_a_id, upstream_match.team_b_id]
                advancing_team = next((t for t in sides if t and t != upstream_match.winner_team_id), None)

            if advancing_team and current_team_id == advancing_team:
                advanced = True
            elif current_team_id and current_team_id != advancing_team:
                blocked = "SLOT_ALREADY_SET"
                advanced = False
            elif ds.id in locked_match_ids:
                blocked = "SLOT_LOCKED"
                advanced = False
            else:
                advanced = False  # match is final but team hasn't been placed yet

        elif ds.id in locked_match_ids:
            blocked = "SLOT_LOCKED"

        elif current_team_id:
            # Pre-finalize: slot already occupied by a different team (could be from prior advancement)
            pass

        return ImpactTarget(
            target_match_number=ds.id,
            target_match_id=ds.id,
            target_slot=slot,
            target_current_team_display=current_display,
            target_current_team_id=current_team_id,
            blocked_reason=blocked,
            advanced=advanced,
        )

    impacts: List[MatchImpactItem] = []
    for m in target_matches:
        status = (m.runtime_status or "SCHEDULED").upper()
        stage = _STAGE_MAP.get(m.match_type, m.match_type)
        entries = downstream_map.get(m.id, [])

        winner_target = _build_target(m, "WINNER", entries)
        loser_target = _build_target(m, "LOSER", entries)

        impacts.append(MatchImpactItem(
            match_id=m.id,
            match_number=m.id,
            match_code=m.match_code or "",
            stage=stage,
            status=status,
            team1_display=_team_disp(m.team_a_id, m.placeholder_side_a),
            team2_display=_team_disp(m.team_b_id, m.placeholder_side_b),
            team1_id=m.team_a_id,
            team2_id=m.team_b_id,
            winner_team_id=m.winner_team_id,
            winner_target=winner_target,
            loser_target=loser_target,
        ))

    impacts.sort(key=lambda x: x.match_number)

    return ImpactResponse(version_id=version_id, impacts=impacts)


# ── Conflict check endpoint ──────────────────────────────────────────────

@router.post(
    "/desk/tournaments/{tournament_id}/conflicts/check",
    response_model=ConflictCheckResponse,
)
def check_conflicts(
    tournament_id: int,
    payload: ConflictCheckRequest,
    session: Session = Depends(get_session),
):
    """Pure read — returns potential conflicts without mutating anything."""
    tournament = session.get(Tournament, tournament_id)
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")

    version = session.get(ScheduleVersion, payload.version_id)
    if not version or version.tournament_id != tournament_id:
        raise HTTPException(status_code=404, detail="Schedule version not found")
    if version.status != "draft":
        raise HTTPException(status_code=400, detail="Conflict checks only apply to DRAFT versions")

    match = session.get(Match, payload.match_id)
    if not match or match.schedule_version_id != payload.version_id:
        raise HTTPException(status_code=404, detail="Match not found in version")

    # Collect real team IDs for this match (skip placeholders)
    team_ids: List[int] = []
    if match.team_a_id:
        team_ids.append(match.team_a_id)
    if match.team_b_id:
        team_ids.append(match.team_b_id)

    if not team_ids:
        return ConflictCheckResponse(conflicts=[])

    # Load all matches + assignments + slots for this version in bulk
    all_matches = session.exec(
        select(Match).where(Match.schedule_version_id == payload.version_id)
    ).all()

    match_ids_all = [m.id for m in all_matches]
    assignments = session.exec(
        select(MatchAssignment).where(
            MatchAssignment.schedule_version_id == payload.version_id,
            MatchAssignment.match_id.in_(match_ids_all),
        )
    ).all() if match_ids_all else []
    assignment_map = {a.match_id: a for a in assignments}

    slot_ids = list({a.slot_id for a in assignments})
    slots = session.exec(
        select(ScheduleSlot).where(ScheduleSlot.id.in_(slot_ids))
    ).all() if slot_ids else []
    slot_map = {s.id: s for s in slots}

    # Team display names
    teams = session.exec(select(Team).where(Team.id.in_(team_ids))).all()
    team_name_map = {t.id: (t.display_name or t.name or f"Team {t.id}") for t in teams}

    # For MOVE actions, use the target slot instead of the current one
    if payload.action_type == "MOVE" and payload.target_slot_id:
        target_slot_obj = session.get(ScheduleSlot, payload.target_slot_id)
        if not target_slot_obj:
            raise HTTPException(status_code=404, detail="Target slot not found")
        this_slot = target_slot_obj
        slot_map[target_slot_obj.id] = target_slot_obj
    else:
        this_assignment = assignment_map.get(match.id)
        this_slot = slot_map.get(this_assignment.slot_id) if this_assignment else None

    this_day = this_slot.day_date if this_slot else None

    def _slot_for(m):
        a = assignment_map.get(m.id)
        return slot_map.get(a.slot_id) if a else None

    def _start_minutes(slot):
        """Convert start_time to minutes since midnight for comparison."""
        st = slot.start_time
        if st is None:
            return None
        if isinstance(st, str):
            parts = st.split(":")
            return int(parts[0]) * 60 + (int(parts[1]) if len(parts) > 1 else 0)
        return st.hour * 60 + st.minute

    conflicts: List[ConflictItem] = []

    for tid in team_ids:
        t_display = team_name_map.get(tid, f"Team {tid}")

        # Build list of OTHER matches this team is in (same version, different match)
        team_matches = [
            m for m in all_matches
            if m.id != match.id and (m.team_a_id == tid or m.team_b_id == tid)
        ]

        # ── 1) Concurrent play: team already IN_PROGRESS elsewhere ───────
        for om in team_matches:
            status = (om.runtime_status or "SCHEDULED").upper()
            if status == "IN_PROGRESS":
                om_slot = _slot_for(om)
                court_label = ""
                if om_slot:
                    cl = om_slot.court_label or str(om_slot.court_number)
                    court_label = f"Court {cl}" if not cl.lower().startswith("court") else cl
                conflicts.append(ConflictItem(
                    code="TEAM_ALREADY_PLAYING",
                    team_display=t_display,
                    message=f"{t_display} is already playing (Match #{om.id} on {court_label}).",
                    details={"match_number": om.id, "court_name": court_label},
                ))
                break  # one warning per team is enough

        # ── 2) Daily cap: >2 matches on the same day ─────────────────────
        if this_day:
            same_day_count = 0
            for om in team_matches:
                om_status = (om.runtime_status or "SCHEDULED").upper()
                if om_status not in ("FINAL", "IN_PROGRESS"):
                    continue
                om_slot = _slot_for(om)
                if om_slot and om_slot.day_date == this_day:
                    same_day_count += 1

            # The current match would also count toward today
            if same_day_count >= DAILY_MATCH_CAP:
                day_offset = (this_day - tournament.start_date).days + 1
                conflicts.append(ConflictItem(
                    code="DAY_CAP_EXCEEDED",
                    team_display=t_display,
                    message=f"{t_display} would have {same_day_count + 1} matches on Day {day_offset} (cap is {DAILY_MATCH_CAP}).",
                    details={"day_index": day_offset, "count": same_day_count + 1, "cap": DAILY_MATCH_CAP},
                ))

        # ── 3) Rest time: insufficient gap from last match ───────────────
        if this_slot:
            this_start = _start_minutes(this_slot)
            if this_start is not None:
                # Find closest earlier match end for this team (use start_time + block_minutes as proxy)
                closest_delta = None
                closest_match_id = None
                for om in team_matches:
                    om_status = (om.runtime_status or "SCHEDULED").upper()
                    if om_status not in ("FINAL", "IN_PROGRESS"):
                        continue
                    om_slot = _slot_for(om)
                    if not om_slot or om_slot.day_date != this_day:
                        continue
                    om_start = _start_minutes(om_slot)
                    if om_start is None:
                        continue
                    om_end = om_start + (om_slot.block_minutes or 60)
                    delta = this_start - om_end
                    if delta >= 0 and (closest_delta is None or delta < closest_delta):
                        closest_delta = delta
                        closest_match_id = om.id

                if closest_delta is not None and closest_delta < MIN_REST_MINUTES:
                    conflicts.append(ConflictItem(
                        code="REST_TOO_SHORT",
                        team_display=t_display,
                        message=f"{t_display} rest time would be {closest_delta} min (< {MIN_REST_MINUTES} min).",
                        details={"rest_minutes": closest_delta, "min_required": MIN_REST_MINUTES, "prior_match": closest_match_id},
                    ))

    return ConflictCheckResponse(conflicts=conflicts)


# ── Pool Projection models + endpoints ───────────────────────────────────

class ProjectedTeamItem(BaseModel):
    team_id: int
    team_display: str
    seed_position: int
    bucket: str
    status: str  # "confirmed" | "projected" | "pending"


class ProjectedPoolItem(BaseModel):
    pool_label: str
    pool_display: str
    teams: List[ProjectedTeamItem]


class EventProjectionItem(BaseModel):
    event_id: int
    event_name: str
    wf_complete: bool
    total_wf_matches: int
    finalized_wf_matches: int
    pools: List[ProjectedPoolItem]
    unresolved_teams: List[Dict[str, Any]]


class PoolProjectionResponse(BaseModel):
    tournament_id: int
    version_id: int
    events: List[EventProjectionItem]


class PoolPlacementRequest(BaseModel):
    version_id: int
    event_id: int
    pools: List[Dict[str, Any]]  # [{"pool_label": "POOLA", "team_ids": [4,7,12,1]}, ...]


class PoolPlacementResponse(BaseModel):
    success: bool
    updated_matches: int
    assignments: List[Dict[str, Any]]


@router.get(
    "/desk/tournaments/{tournament_id}/pool-projection",
    response_model=PoolProjectionResponse,
)
def get_pool_projection(
    tournament_id: int,
    version_id: int = Query(...),
    event_id: Optional[int] = Query(None),
    session: Session = Depends(get_session),
):
    """Projected RR pool assignments based on current WF results."""
    from app.services.wf_pool_projection import compute_wf_projection

    tournament = session.get(Tournament, tournament_id)
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")

    version = session.get(ScheduleVersion, version_id)
    if not version or version.tournament_id != tournament_id:
        raise HTTPException(status_code=404, detail="Schedule version not found")

    # Find WF events
    if event_id is not None:
        ev = session.get(Event, event_id)
        if not ev or ev.tournament_id != tournament_id:
            raise HTTPException(status_code=404, detail="Event not found")
        event_ids = [event_id]
    else:
        all_events = session.exec(
            select(Event).where(Event.tournament_id == tournament_id)
        ).all()
        event_ids = [e.id for e in all_events]

    projections: List[EventProjectionItem] = []
    for eid in event_ids:
        proj = compute_wf_projection(session, tournament_id, version_id, eid)
        if proj is None:
            continue
        projections.append(EventProjectionItem(
            event_id=proj.event_id,
            event_name=proj.event_name,
            wf_complete=proj.wf_complete,
            total_wf_matches=proj.total_wf_matches,
            finalized_wf_matches=proj.finalized_wf_matches,
            pools=[
                ProjectedPoolItem(
                    pool_label=p.pool_label,
                    pool_display=p.pool_display,
                    teams=[
                        ProjectedTeamItem(
                            team_id=t.team_id,
                            team_display=t.team_display,
                            seed_position=t.seed_position,
                            bucket=t.bucket,
                            status=t.status,
                        )
                        for t in p.teams
                    ],
                )
                for p in proj.pools
            ],
            unresolved_teams=proj.unresolved_teams,
        ))

    return PoolProjectionResponse(
        tournament_id=tournament_id,
        version_id=version_id,
        events=projections,
    )


@router.post(
    "/desk/tournaments/{tournament_id}/pool-placement",
    response_model=PoolPlacementResponse,
)
def confirm_pool_placement(
    tournament_id: int,
    payload: PoolPlacementRequest,
    session: Session = Depends(get_session),
):
    """Confirm pool placement — resolves SEED_N placeholders on RR matches."""
    from app.services.wf_pool_projection import apply_pool_placement, compute_wf_projection

    tournament = session.get(Tournament, tournament_id)
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")

    version = session.get(ScheduleVersion, payload.version_id)
    if not version or version.tournament_id != tournament_id:
        raise HTTPException(status_code=404, detail="Schedule version not found")

    if version.status != "draft":
        raise HTTPException(status_code=400, detail="Pool placement only allowed on DRAFT versions")

    # Check WF completeness
    proj = compute_wf_projection(session, tournament_id, payload.version_id, payload.event_id)
    if proj is None:
        raise HTTPException(status_code=400, detail="Event has no WF matches for pool projection")
    if not proj.wf_complete:
        raise HTTPException(
            status_code=400,
            detail=f"WF not complete: {proj.finalized_wf_matches}/{proj.total_wf_matches} finalized",
        )

    try:
        result = apply_pool_placement(
            session,
            tournament_id,
            payload.version_id,
            payload.event_id,
            payload.pools,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return PoolPlacementResponse(
        success=True,
        updated_matches=result["updated_matches"],
        assignments=result["assignments"],
    )


# ── Standings models + endpoint ──────────────────────────────────────────

class StandingsRow(BaseModel):
    team_id: int
    team_display: str
    wins: int = 0
    losses: int = 0
    sets_won: int = 0
    sets_lost: int = 0
    games_won: int = 0
    games_lost: int = 0
    point_diff: Optional[int] = None
    played: int = 0


class StandingsEvent(BaseModel):
    event_id: int
    event_name: str
    division_name: Optional[str] = None
    rows: List[StandingsRow]
    tiebreak_notes: str = "Sorted by Wins, then Set Diff, then Game Diff"
    warnings: List[Dict[str, Any]] = []


class StandingsResponse(BaseModel):
    tournament_id: int
    version_id: int
    events: List[StandingsEvent]


@router.get(
    "/desk/tournaments/{tournament_id}/standings",
    response_model=StandingsResponse,
)
def get_standings(
    tournament_id: int,
    version_id: int = Query(...),
    event_id: Optional[int] = Query(None),
    session: Session = Depends(get_session),
):
    """Live RR standings computed from FINAL matches in the given version."""
    from app.services.score_parser import parse_score

    tournament = session.get(Tournament, tournament_id)
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")

    version = session.get(ScheduleVersion, version_id)
    if not version or version.tournament_id != tournament_id:
        raise HTTPException(status_code=404, detail="Schedule version not found")

    # Load all RR matches for this version
    q = select(Match).where(
        Match.schedule_version_id == version_id,
        Match.tournament_id == tournament_id,
        Match.match_type == "RR",
    )
    if event_id is not None:
        q = q.where(Match.event_id == event_id)
    all_rr = session.exec(q).all()

    if not all_rr:
        return StandingsResponse(
            tournament_id=tournament_id,
            version_id=version_id,
            events=[],
        )

    # Group by event
    event_ids = list({m.event_id for m in all_rr})
    events = session.exec(select(Event).where(Event.id.in_(event_ids))).all()
    event_map = {e.id: e for e in events}

    # Load teams
    team_ids: set = set()
    for m in all_rr:
        if m.team_a_id:
            team_ids.add(m.team_a_id)
        if m.team_b_id:
            team_ids.add(m.team_b_id)
    teams = session.exec(select(Team).where(Team.id.in_(list(team_ids)))).all() if team_ids else []
    team_map = {t.id: t for t in teams}

    def _t_disp(tid):
        t = team_map.get(tid)
        return (t.display_name or t.name or f"Team {tid}") if t else f"Team {tid}"

    # Group matches by event_id, then by pool (derived from match_code)
    from collections import defaultdict
    matches_by_event_pool: Dict[tuple, List[Match]] = defaultdict(list)
    for m in all_rr:
        pool = None
        code_upper = (m.match_code or "").upper()
        for pool_code in _POOL_LABELS:
            if f"_{pool_code}_" in code_upper:
                pool = pool_code
                break
        matches_by_event_pool[(m.event_id, pool)].append(m)

    standings_events: List[StandingsEvent] = []

    for (eid, pool), matches in sorted(matches_by_event_pool.items()):
        ev = event_map.get(eid)
        ev_name = ev.name if ev else "Unknown"
        div_name = _POOL_LABELS.get(pool) if pool else None

        # Collect all teams in this pool (from all matches, not just FINAL)
        pool_team_ids: set = set()
        for m in matches:
            if m.team_a_id:
                pool_team_ids.add(m.team_a_id)
            if m.team_b_id:
                pool_team_ids.add(m.team_b_id)

        # Init rows
        rows: Dict[int, dict] = {}
        for tid in pool_team_ids:
            rows[tid] = {
                "wins": 0,
                "losses": 0,
                "sets_won": 0,
                "sets_lost": 0,
                "games_won": 0,
                "games_lost": 0,
                "played": 0,
            }

        warnings: List[Dict[str, Any]] = []

        # Process only FINAL matches
        for m in matches:
            status = (m.runtime_status or "SCHEDULED").upper()
            if status != "FINAL":
                continue
            if not m.team_a_id or not m.team_b_id:
                continue

            a_id = m.team_a_id
            b_id = m.team_b_id

            # Win/loss from winner_team_id
            if m.winner_team_id == a_id:
                rows.setdefault(a_id, {"wins": 0, "losses": 0, "sets_won": 0, "sets_lost": 0, "games_won": 0, "games_lost": 0, "played": 0})
                rows.setdefault(b_id, {"wins": 0, "losses": 0, "sets_won": 0, "sets_lost": 0, "games_won": 0, "games_lost": 0, "played": 0})
                rows[a_id]["wins"] += 1
                rows[b_id]["losses"] += 1
            elif m.winner_team_id == b_id:
                rows.setdefault(a_id, {"wins": 0, "losses": 0, "sets_won": 0, "sets_lost": 0, "games_won": 0, "games_lost": 0, "played": 0})
                rows.setdefault(b_id, {"wins": 0, "losses": 0, "sets_won": 0, "sets_lost": 0, "games_won": 0, "games_lost": 0, "played": 0})
                rows[b_id]["wins"] += 1
                rows[a_id]["losses"] += 1

            rows[a_id]["played"] += 1
            rows[b_id]["played"] += 1

            # Parse score for sets/games
            parsed = parse_score(m.score_json)
            if parsed:
                rows[a_id]["sets_won"] += parsed.team_a_sets_won
                rows[a_id]["sets_lost"] += parsed.team_b_sets_won
                rows[b_id]["sets_won"] += parsed.team_b_sets_won
                rows[b_id]["sets_lost"] += parsed.team_a_sets_won
                rows[a_id]["games_won"] += parsed.team_a_games
                rows[a_id]["games_lost"] += parsed.team_b_games
                rows[b_id]["games_won"] += parsed.team_b_games
                rows[b_id]["games_lost"] += parsed.team_a_games
            elif m.score_json:
                warnings.append({"match_number": m.id, "reason": "SCORE_PARSE_FAILED"})

        # Sort: wins desc, set diff desc, game diff desc, name asc
        sorted_rows = sorted(
            rows.items(),
            key=lambda item: (
                -item[1]["wins"],
                -(item[1]["sets_won"] - item[1]["sets_lost"]),
                -(item[1]["games_won"] - item[1]["games_lost"]),
                _t_disp(item[0]),
            ),
        )

        label_suffix = f" — {div_name}" if div_name else ""
        standings_events.append(StandingsEvent(
            event_id=eid,
            event_name=f"{ev_name}{label_suffix}",
            division_name=div_name,
            rows=[
                StandingsRow(
                    team_id=tid,
                    team_display=_t_disp(tid),
                    **r,
                )
                for tid, r in sorted_rows
            ],
            warnings=warnings,
        ))

    standings_events.sort(key=lambda e: (e.event_name, e.division_name or ""))

    return StandingsResponse(
        tournament_id=tournament_id,
        version_id=version_id,
        events=standings_events,
    )


# ── Bulk Status Models ───────────────────────────────────────────────────

class BulkPauseRequest(BaseModel):
    version_id: int


class BulkDelayRequest(BaseModel):
    version_id: int
    after_time: str  # "HH:MM" 24h format
    day_index: Optional[int] = None


class BulkStatusResponse(BaseModel):
    updated_count: int
    updated_match_numbers: List[int]


# ── Desk Teams ───────────────────────────────────────────────────────────

class DeskTeamItem(BaseModel):
    team_id: int
    event_id: int
    event_name: str
    seed: Optional[int] = None
    name: str
    display_name: Optional[str] = None
    rating: Optional[float] = None
    player1_cellphone: Optional[str] = None
    player1_email: Optional[str] = None
    player2_cellphone: Optional[str] = None
    player2_email: Optional[str] = None
    is_defaulted: bool = False
    notes: Optional[str] = None


@router.get(
    "/desk/tournaments/{tournament_id}/teams",
    response_model=List[DeskTeamItem],
)
def get_desk_teams(
    tournament_id: int,
    session: Session = Depends(get_session),
):
    """List all teams across all events for this tournament."""
    from app.models.event import Event

    events = session.exec(
        select(Event).where(Event.tournament_id == tournament_id)
    ).all()
    event_map = {e.id: e.name for e in events}
    event_ids = list(event_map.keys())
    if not event_ids:
        return []

    teams = session.exec(
        select(Team).where(Team.event_id.in_(event_ids))
    ).all()

    items = []
    for t in sorted(teams, key=lambda t: (event_map.get(t.event_id, ""), t.seed or 9999, t.id)):
        items.append(DeskTeamItem(
            team_id=t.id,
            event_id=t.event_id,
            event_name=event_map.get(t.event_id, ""),
            seed=t.seed,
            name=t.name,
            display_name=t.display_name,
            rating=t.rating,
            player1_cellphone=t.player1_cellphone,
            player1_email=t.player1_email,
            player2_cellphone=t.player2_cellphone,
            player2_email=t.player2_email,
            is_defaulted=t.is_defaulted if t.is_defaulted else False,
            notes=t.notes,
        ))
    return items


class DefaultWeekendRequest(BaseModel):
    version_id: int


class DefaultWeekendResponse(BaseModel):
    team_id: int
    team_name: str
    matches_defaulted: int
    match_ids: List[int]


@router.post(
    "/desk/tournaments/{tournament_id}/teams/{team_id}/default-weekend",
    response_model=DefaultWeekendResponse,
)
def default_team_weekend(
    tournament_id: int,
    team_id: int,
    payload: DefaultWeekendRequest,
    session: Session = Depends(get_session),
):
    """Mark a team as defaulted and auto-default all their remaining matches."""
    from app.services.reschedule_engine import SCORING_FORMATS

    team = session.get(Team, team_id)
    if not team:
        raise HTTPException(404, "Team not found")

    team.is_defaulted = True
    session.add(team)

    version = session.get(ScheduleVersion, payload.version_id)
    if not version or version.tournament_id != tournament_id:
        raise HTTPException(404, "Schedule version not found")

    all_matches = session.exec(
        select(Match).where(Match.schedule_version_id == payload.version_id)
    ).all()

    defaulted_ids: List[int] = []

    def _default_match(m: Match) -> bool:
        """Default a single match where the defaulted team plays. Returns True if defaulted."""
        if m.runtime_status == "FINAL":
            return False
        if m.runtime_status == "IN_PROGRESS":
            return False
        if m.match_type == "WF":
            return False

        opponent_id = None
        if m.team_a_id == team_id and m.team_b_id:
            opponent_id = m.team_b_id
        elif m.team_b_id == team_id and m.team_a_id:
            opponent_id = m.team_a_id
        else:
            return False

        dur = m.duration_minutes
        if dur <= 35:
            actual_score = "4-0"
        elif dur <= 60:
            actual_score = "8-0"
        else:
            actual_score = "6-0, 6-0"

        m.runtime_status = "FINAL"
        m.winner_team_id = opponent_id
        m.completed_at = datetime.utcnow()
        m.score_json = {"display": "DEFAULT", "actual": actual_score}
        session.add(m)
        return True

    # First pass: default all matches where both teams are assigned
    for m in all_matches:
        if m.team_a_id == team_id or m.team_b_id == team_id:
            if _default_match(m):
                defaulted_ids.append(m.id)

    session.commit()

    # Run advancement for each defaulted match (may cascade into new matches)
    for mid in list(defaulted_ids):
        apply_advancement_with_details(session, mid)

    # Second pass: check if advancement placed the defaulted team into new matches
    refreshed = session.exec(
        select(Match).where(Match.schedule_version_id == payload.version_id)
    ).all()
    for m in refreshed:
        if m.id in defaulted_ids:
            continue
        if m.runtime_status == "FINAL":
            continue
        if m.team_a_id == team_id or m.team_b_id == team_id:
            if _default_match(m):
                defaulted_ids.append(m.id)
                session.commit()
                apply_advancement_with_details(session, m.id)

    return DefaultWeekendResponse(
        team_id=team_id,
        team_name=team.display_name or team.name,
        matches_defaulted=len(defaulted_ids),
        match_ids=defaulted_ids,
    )


# ── Court State Models ───────────────────────────────────────────────────

class CourtStateItem(BaseModel):
    court_label: str
    is_closed: bool
    note: Optional[str] = None
    updated_at: Optional[str] = None


class CourtStatePatchRequest(BaseModel):
    is_closed: Optional[bool] = None
    note: Optional[str] = None


# ── Bulk Endpoints ───────────────────────────────────────────────────────

@router.post(
    "/desk/tournaments/{tournament_id}/bulk/pause-in-progress",
    response_model=BulkStatusResponse,
)
def bulk_pause_in_progress(
    tournament_id: int,
    payload: BulkPauseRequest,
    session: Session = Depends(get_session),
):
    """Pause all IN_PROGRESS matches in the given DRAFT version."""
    tournament = session.get(Tournament, tournament_id)
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")

    version = session.get(ScheduleVersion, payload.version_id)
    if not version or version.tournament_id != tournament_id:
        raise HTTPException(status_code=404, detail="Schedule version not found")
    if version.status != "draft":
        raise HTTPException(status_code=400, detail="Bulk pause only allowed on DRAFT versions")

    matches = session.exec(
        select(Match).where(
            Match.schedule_version_id == payload.version_id,
            Match.tournament_id == tournament_id,
        )
    ).all()

    updated_ids: List[int] = []
    for m in matches:
        if (m.runtime_status or "SCHEDULED").upper() == "IN_PROGRESS":
            m.runtime_status = "PAUSED"
            session.add(m)
            updated_ids.append(m.id)

    session.commit()
    return BulkStatusResponse(updated_count=len(updated_ids), updated_match_numbers=updated_ids)


@router.post(
    "/desk/tournaments/{tournament_id}/bulk/delay-after",
    response_model=BulkStatusResponse,
)
def bulk_delay_after(
    tournament_id: int,
    payload: BulkDelayRequest,
    session: Session = Depends(get_session),
):
    """Set all SCHEDULED matches after a given time to DELAYED."""
    tournament = session.get(Tournament, tournament_id)
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")

    version = session.get(ScheduleVersion, payload.version_id)
    if not version or version.tournament_id != tournament_id:
        raise HTTPException(status_code=404, detail="Schedule version not found")
    if version.status != "draft":
        raise HTTPException(status_code=400, detail="Bulk delay only allowed on DRAFT versions")

    # Parse threshold time
    try:
        parts = payload.after_time.split(":")
        threshold_minutes = int(parts[0]) * 60 + int(parts[1])
    except (ValueError, IndexError):
        raise HTTPException(status_code=400, detail="after_time must be in HH:MM format")

    matches = session.exec(
        select(Match).where(
            Match.schedule_version_id == payload.version_id,
            Match.tournament_id == tournament_id,
        )
    ).all()
    match_ids = [m.id for m in matches]

    assignments = session.exec(
        select(MatchAssignment).where(
            MatchAssignment.schedule_version_id == payload.version_id,
            MatchAssignment.match_id.in_(match_ids),
        )
    ).all() if match_ids else []
    assignment_map = {a.match_id: a for a in assignments}

    slot_ids = list({a.slot_id for a in assignments})
    slots = session.exec(
        select(ScheduleSlot).where(ScheduleSlot.id.in_(slot_ids))
    ).all() if slot_ids else []
    slot_map = {s.id: s for s in slots}

    updated_ids: List[int] = []
    for m in matches:
        if (m.runtime_status or "SCHEDULED").upper() != "SCHEDULED":
            continue

        a = assignment_map.get(m.id)
        if not a:
            continue
        slot = slot_map.get(a.slot_id)
        if not slot or slot.start_time is None:
            continue

        # Day filter
        if payload.day_index is not None:
            day_offset = (slot.day_date - tournament.start_date).days + 1
            if day_offset != payload.day_index:
                continue

        st = slot.start_time
        if isinstance(st, str):
            sp = st.split(":")
            slot_minutes = int(sp[0]) * 60 + (int(sp[1]) if len(sp) > 1 else 0)
        else:
            slot_minutes = st.hour * 60 + st.minute

        if slot_minutes >= threshold_minutes:
            m.runtime_status = "DELAYED"
            session.add(m)
            updated_ids.append(m.id)

    session.commit()
    return BulkStatusResponse(updated_count=len(updated_ids), updated_match_numbers=updated_ids)


@router.post(
    "/desk/tournaments/{tournament_id}/bulk/resume-paused",
    response_model=BulkStatusResponse,
)
def bulk_resume_paused(
    tournament_id: int,
    payload: BulkPauseRequest,
    session: Session = Depends(get_session),
):
    """Resume all PAUSED matches back to IN_PROGRESS."""
    tournament = session.get(Tournament, tournament_id)
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")

    version = session.get(ScheduleVersion, payload.version_id)
    if not version or version.tournament_id != tournament_id:
        raise HTTPException(status_code=404, detail="Schedule version not found")
    if version.status != "draft":
        raise HTTPException(status_code=400, detail="Bulk resume only allowed on DRAFT versions")

    matches = session.exec(
        select(Match).where(
            Match.schedule_version_id == payload.version_id,
            Match.tournament_id == tournament_id,
        )
    ).all()

    updated_ids: List[int] = []
    for m in matches:
        if (m.runtime_status or "SCHEDULED").upper() == "PAUSED":
            m.runtime_status = "IN_PROGRESS"
            session.add(m)
            updated_ids.append(m.id)

    session.commit()
    return BulkStatusResponse(updated_count=len(updated_ids), updated_match_numbers=updated_ids)


@router.post(
    "/desk/tournaments/{tournament_id}/bulk/undelay",
    response_model=BulkStatusResponse,
)
def bulk_undelay(
    tournament_id: int,
    payload: BulkPauseRequest,
    session: Session = Depends(get_session),
):
    """Set all DELAYED matches back to SCHEDULED."""
    tournament = session.get(Tournament, tournament_id)
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")

    version = session.get(ScheduleVersion, payload.version_id)
    if not version or version.tournament_id != tournament_id:
        raise HTTPException(status_code=404, detail="Schedule version not found")
    if version.status != "draft":
        raise HTTPException(status_code=400, detail="Bulk un-delay only allowed on DRAFT versions")

    matches = session.exec(
        select(Match).where(
            Match.schedule_version_id == payload.version_id,
            Match.tournament_id == tournament_id,
        )
    ).all()

    updated_ids: List[int] = []
    for m in matches:
        if (m.runtime_status or "SCHEDULED").upper() == "DELAYED":
            m.runtime_status = "SCHEDULED"
            session.add(m)
            updated_ids.append(m.id)

    session.commit()
    return BulkStatusResponse(updated_count=len(updated_ids), updated_match_numbers=updated_ids)


# ── Court State Endpoints ────────────────────────────────────────────────

@router.get(
    "/desk/tournaments/{tournament_id}/courts/state",
    response_model=List[CourtStateItem],
)
def get_court_states(
    tournament_id: int,
    session: Session = Depends(get_session),
):
    """Return court open/closed state and notes for all courts with known state."""
    from app.models.court_state import TournamentCourtState

    tournament = session.get(Tournament, tournament_id)
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")

    states = session.exec(
        select(TournamentCourtState).where(
            TournamentCourtState.tournament_id == tournament_id
        )
    ).all()

    return [
        CourtStateItem(
            court_label=s.court_label,
            is_closed=s.is_closed,
            note=s.note,
            updated_at=s.updated_at.isoformat() if s.updated_at else None,
        )
        for s in sorted(states, key=lambda x: x.court_label)
    ]


@router.patch(
    "/desk/tournaments/{tournament_id}/courts/{court_label}/state",
    response_model=CourtStateItem,
)
def patch_court_state(
    tournament_id: int,
    court_label: str,
    payload: CourtStatePatchRequest,
    session: Session = Depends(get_session),
):
    """Upsert court open/closed state and note."""
    from app.models.court_state import TournamentCourtState

    tournament = session.get(Tournament, tournament_id)
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")

    if payload.is_closed is None and payload.note is None:
        raise HTTPException(status_code=400, detail="Provide is_closed and/or note")

    if payload.note is not None and len(payload.note) > 280:
        raise HTTPException(status_code=400, detail="Note too long (max 280 chars)")

    existing = session.exec(
        select(TournamentCourtState).where(
            TournamentCourtState.tournament_id == tournament_id,
            TournamentCourtState.court_label == court_label,
        )
    ).first()

    if existing:
        if payload.is_closed is not None:
            existing.is_closed = payload.is_closed
        if payload.note is not None:
            existing.note = payload.note
        existing.updated_at = datetime.utcnow()
        session.add(existing)
    else:
        existing = TournamentCourtState(
            tournament_id=tournament_id,
            court_label=court_label,
            is_closed=payload.is_closed if payload.is_closed is not None else False,
            note=payload.note,
            updated_at=datetime.utcnow(),
        )
        session.add(existing)

    session.commit()
    session.refresh(existing)

    return CourtStateItem(
        court_label=existing.court_label,
        is_closed=existing.is_closed,
        note=existing.note,
        updated_at=existing.updated_at.isoformat() if existing.updated_at else None,
    )


# ── Match Move endpoint ──────────────────────────────────────────────────

class MoveMatchRequest(BaseModel):
    version_id: int
    target_slot_id: int


class MoveMatchResponse(BaseModel):
    success: bool
    match: DeskMatchItem
    warnings: List[str] = []


@router.patch(
    "/desk/tournaments/{tournament_id}/matches/{match_id}/move",
    response_model=MoveMatchResponse,
)
def move_match(
    tournament_id: int,
    match_id: int,
    payload: MoveMatchRequest,
    session: Session = Depends(get_session),
):
    """Move a match to a different slot (court/time). DRAFT only."""
    from app.utils.manual_assignment import (
        ManualAssignmentValidationError,
        validate_slot_available,
    )

    tournament = session.get(Tournament, tournament_id)
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")

    version = session.get(ScheduleVersion, payload.version_id)
    if not version or version.tournament_id != tournament_id:
        raise HTTPException(status_code=404, detail="Schedule version not found")
    if version.status != "draft":
        raise HTTPException(status_code=400, detail="Moves only allowed on DRAFT versions")

    match = session.get(Match, match_id)
    if not match or match.schedule_version_id != payload.version_id:
        raise HTTPException(status_code=404, detail="Match not found in version")

    target_slot = session.get(ScheduleSlot, payload.target_slot_id)
    if not target_slot or target_slot.schedule_version_id != payload.version_id:
        raise HTTPException(status_code=404, detail="Target slot not found in version")

    available, reason = validate_slot_available(
        session, payload.target_slot_id, payload.version_id, exclude_match_id=match_id,
    )
    if not available:
        occupant = session.exec(
            select(MatchAssignment).where(
                MatchAssignment.schedule_version_id == payload.version_id,
                MatchAssignment.slot_id == payload.target_slot_id,
            )
        ).first()
        occupant_id = occupant.match_id if occupant else None
        raise HTTPException(
            status_code=409,
            detail={
                "message": reason,
                "occupant_match_id": occupant_id,
            },
        )

    existing_assignment = session.exec(
        select(MatchAssignment).where(
            MatchAssignment.schedule_version_id == payload.version_id,
            MatchAssignment.match_id == match_id,
        )
    ).first()

    warnings: List[str] = []

    if existing_assignment:
        existing_assignment.slot_id = payload.target_slot_id
        existing_assignment.assigned_by = "DESK_MOVE"
        existing_assignment.assigned_at = datetime.utcnow()
        existing_assignment.locked = True
        session.add(existing_assignment)
    else:
        new_assignment = MatchAssignment(
            schedule_version_id=payload.version_id,
            match_id=match_id,
            slot_id=payload.target_slot_id,
            assigned_by="DESK_MOVE",
            assigned_at=datetime.utcnow(),
            locked=True,
        )
        session.add(new_assignment)

    session.commit()
    session.refresh(match)

    item = _match_to_desk_item(match, session, tournament)
    return MoveMatchResponse(success=True, match=item, warnings=warnings)


# ── Match Swap endpoint ──────────────────────────────────────────────────

class SwapMatchesRequest(BaseModel):
    version_id: int
    match_a_id: int
    match_b_id: int


class SwapMatchesResponse(BaseModel):
    success: bool
    match_a: DeskMatchItem
    match_b: DeskMatchItem
    warnings: List[str] = []


@router.post(
    "/desk/tournaments/{tournament_id}/matches/swap",
    response_model=SwapMatchesResponse,
)
def swap_matches(
    tournament_id: int,
    payload: SwapMatchesRequest,
    session: Session = Depends(get_session),
):
    """Swap two matches' slots atomically. DRAFT only."""
    tournament = session.get(Tournament, tournament_id)
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")

    version = session.get(ScheduleVersion, payload.version_id)
    if not version or version.tournament_id != tournament_id:
        raise HTTPException(status_code=404, detail="Schedule version not found")
    if version.status != "draft":
        raise HTTPException(status_code=400, detail="Swaps only allowed on DRAFT versions")

    match_a = session.get(Match, payload.match_a_id)
    match_b = session.get(Match, payload.match_b_id)
    if not match_a or match_a.schedule_version_id != payload.version_id:
        raise HTTPException(status_code=404, detail="Match A not found in version")
    if not match_b or match_b.schedule_version_id != payload.version_id:
        raise HTTPException(status_code=404, detail="Match B not found in version")

    assign_a = session.exec(
        select(MatchAssignment).where(
            MatchAssignment.schedule_version_id == payload.version_id,
            MatchAssignment.match_id == payload.match_a_id,
        )
    ).first()
    assign_b = session.exec(
        select(MatchAssignment).where(
            MatchAssignment.schedule_version_id == payload.version_id,
            MatchAssignment.match_id == payload.match_b_id,
        )
    ).first()

    if not assign_a or not assign_b:
        raise HTTPException(
            status_code=400, detail="Both matches must be assigned to slots to swap",
        )

    slot_a = assign_a.slot_id
    slot_b = assign_b.slot_id

    session.delete(assign_a)
    session.delete(assign_b)
    session.flush()

    new_a = MatchAssignment(
        schedule_version_id=payload.version_id,
        match_id=payload.match_a_id,
        slot_id=slot_b,
        assigned_by="DESK_SWAP",
        assigned_at=datetime.utcnow(),
        locked=True,
    )
    new_b = MatchAssignment(
        schedule_version_id=payload.version_id,
        match_id=payload.match_b_id,
        slot_id=slot_a,
        assigned_by="DESK_SWAP",
        assigned_at=datetime.utcnow(),
        locked=True,
    )
    session.add_all([new_a, new_b])
    session.commit()

    session.refresh(match_a)
    session.refresh(match_b)

    item_a = _match_to_desk_item(match_a, session, tournament)
    item_b = _match_to_desk_item(match_b, session, tournament)

    return SwapMatchesResponse(success=True, match_a=item_a, match_b=item_b)


# ── Add Time Slot endpoint ───────────────────────────────────────────────

class AddSlotRequest(BaseModel):
    version_id: int
    day_date: str  # ISO date string
    start_time: str  # HH:MM
    end_time: str  # HH:MM
    court_numbers: List[int]


class AddSlotItem(BaseModel):
    slot_id: int
    day_date: str
    start_time: str
    end_time: str
    court_number: int
    court_label: str
    block_minutes: int


class AddSlotResponse(BaseModel):
    success: bool
    created_slots: List[AddSlotItem]


@router.post(
    "/desk/tournaments/{tournament_id}/slots",
    response_model=AddSlotResponse,
)
def add_time_slots(
    tournament_id: int,
    payload: AddSlotRequest,
    session: Session = Depends(get_session),
):
    """Add individual time slots for specified courts. DRAFT only."""
    from datetime import date as date_type, time as time_type
    from app.utils.courts import court_label_for_index

    tournament = session.get(Tournament, tournament_id)
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")

    version = session.get(ScheduleVersion, payload.version_id)
    if not version or version.tournament_id != tournament_id:
        raise HTTPException(status_code=404, detail="Schedule version not found")
    if version.status != "draft":
        raise HTTPException(status_code=400, detail="Slot creation only allowed on DRAFT versions")

    day = date_type.fromisoformat(payload.day_date)
    st_parts = payload.start_time.split(":")
    et_parts = payload.end_time.split(":")
    st = time_type(int(st_parts[0]), int(st_parts[1]))
    et = time_type(int(et_parts[0]), int(et_parts[1]))

    start_min = st.hour * 60 + st.minute
    end_min = et.hour * 60 + et.minute
    block = end_min - start_min if end_min > start_min else 60

    created: List[AddSlotItem] = []

    for cn in payload.court_numbers:
        existing = session.exec(
            select(ScheduleSlot).where(
                ScheduleSlot.schedule_version_id == payload.version_id,
                ScheduleSlot.day_date == day,
                ScheduleSlot.start_time == st,
                ScheduleSlot.court_number == cn,
            )
        ).first()
        if existing:
            continue

        label = court_label_for_index(tournament.court_names, cn)
        slot = ScheduleSlot(
            tournament_id=tournament_id,
            schedule_version_id=payload.version_id,
            day_date=day,
            start_time=st,
            end_time=et,
            court_number=cn,
            court_label=label,
            block_minutes=block,
            is_active=True,
        )
        session.add(slot)
        session.flush()

        created.append(AddSlotItem(
            slot_id=slot.id,
            day_date=day.isoformat(),
            start_time=payload.start_time,
            end_time=payload.end_time,
            court_number=cn,
            court_label=label,
            block_minutes=block,
        ))

    session.commit()
    return AddSlotResponse(success=True, created_slots=created)


# ── Add Court endpoint ───────────────────────────────────────────────────

class AddCourtRequest(BaseModel):
    version_id: int
    court_label: str
    create_matching_slots: bool = False


class AddCourtResponse(BaseModel):
    success: bool
    court_label: str
    court_number: int
    courts: List[str]
    created_slots: int = 0


@router.post(
    "/desk/tournaments/{tournament_id}/courts",
    response_model=AddCourtResponse,
)
def add_court(
    tournament_id: int,
    payload: AddCourtRequest,
    session: Session = Depends(get_session),
):
    """Add a court to the tournament and optionally create matching time slots."""
    import json as _json

    tournament = session.get(Tournament, tournament_id)
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")

    version = session.get(ScheduleVersion, payload.version_id)
    if not version or version.tournament_id != tournament_id:
        raise HTTPException(status_code=404, detail="Schedule version not found")
    if version.status != "draft":
        raise HTTPException(status_code=400, detail="Court addition only allowed on DRAFT versions")

    court_names = list(tournament.court_names or [])
    if payload.court_label in court_names:
        raise HTTPException(status_code=400, detail=f"Court '{payload.court_label}' already exists")

    court_names.append(payload.court_label)
    tournament.court_names = court_names
    new_court_number = len(court_names)

    created_slots = 0
    if payload.create_matching_slots:
        existing_slots = session.exec(
            select(ScheduleSlot).where(
                ScheduleSlot.schedule_version_id == payload.version_id,
            )
        ).all()

        seen_times: set = set()
        for es in existing_slots:
            key = (es.day_date, es.start_time, es.end_time)
            if key not in seen_times:
                seen_times.add(key)
                slot = ScheduleSlot(
                    tournament_id=tournament_id,
                    schedule_version_id=payload.version_id,
                    day_date=es.day_date,
                    start_time=es.start_time,
                    end_time=es.end_time,
                    court_number=new_court_number,
                    court_label=payload.court_label,
                    block_minutes=es.block_minutes,
                    is_active=True,
                )
                session.add(slot)
                created_slots += 1

    session.add(tournament)
    session.commit()

    return AddCourtResponse(
        success=True,
        court_label=payload.court_label,
        court_number=new_court_number,
        courts=court_names,
        created_slots=created_slots,
    )


# ── Reschedule models ────────────────────────────────────────────────────

class FeasibilityRequest(BaseModel):
    version_id: int
    mode: str
    affected_day: str
    target_days: Optional[List[str]] = None


class FormatFeasibilityItem(BaseModel):
    format: str
    duration: int
    label: str
    fits: bool
    utilization: int


class FeasibilityResponse(BaseModel):
    affected_count: int
    formats: List[FormatFeasibilityItem]


class ReschedulePreviewRequest(BaseModel):
    version_id: int
    mode: str  # PARTIAL_DAY | FULL_WASHOUT | COURT_LOSS
    affected_day: str  # ISO date
    unavailable_from: Optional[str] = None  # HH:MM
    available_from: Optional[str] = None     # HH:MM
    unavailable_courts: Optional[List[int]] = None
    target_days: Optional[List[str]] = None
    extend_day_end: Optional[str] = None  # HH:MM
    add_time_slots: bool = True
    block_minutes: int = 60
    scoring_format: Optional[str] = None  # REGULAR | PRO_SET_8 | PRO_SET_4


class ProposedMoveItem(BaseModel):
    match_id: int
    match_number: int
    match_code: str
    event_name: str
    stage: str
    old_slot_id: Optional[int] = None
    old_court: Optional[str] = None
    old_time: Optional[str] = None
    old_day: Optional[str] = None
    new_slot_id: int
    new_court: str
    new_time: str
    new_day: str


class UnplaceableItem(BaseModel):
    match_id: int
    match_number: int
    match_code: str
    event_name: str
    stage: str
    reason: str


class ReschedulePreviewResponse(BaseModel):
    proposed_moves: List[ProposedMoveItem]
    unplaceable: List[UnplaceableItem]
    new_slots_created: int
    stats: Dict[str, int]
    format_applied: Optional[str] = None
    duration_updates: Optional[Dict[int, int]] = None


class RescheduleApplyRequest(BaseModel):
    version_id: int
    moves: List[Dict[str, Any]]
    duration_updates: Optional[Dict[str, int]] = None  # match_id (str key) -> new duration


class RescheduleApplyResponse(BaseModel):
    updated_matches: int
    applied_moves: int


# ── Reschedule endpoints ─────────────────────────────────────────────────

@router.post(
    "/desk/tournaments/{tournament_id}/reschedule/feasibility",
    response_model=FeasibilityResponse,
)
def reschedule_feasibility(
    tournament_id: int,
    payload: FeasibilityRequest,
    session: Session = Depends(get_session),
):
    from datetime import date as _date

    version = session.get(ScheduleVersion, payload.version_id)
    if not version or version.tournament_id != tournament_id:
        raise HTTPException(404, "Schedule version not found")
    if version.status != "draft":
        raise HTTPException(400, "Feasibility only on DRAFT versions")

    params = RescheduleParams(
        version_id=payload.version_id,
        mode=payload.mode,
        affected_day=_date.fromisoformat(payload.affected_day),
        target_days=[_date.fromisoformat(d) for d in payload.target_days] if payload.target_days else None,
    )
    result = compute_feasibility(session, tournament_id, params)
    return FeasibilityResponse(
        affected_count=result.affected_count,
        formats=[
            FormatFeasibilityItem(
                format=f.format,
                duration=f.duration,
                label=f.label,
                fits=f.fits,
                utilization=f.utilization,
            )
            for f in result.formats
        ],
    )


@router.post(
    "/desk/tournaments/{tournament_id}/reschedule/preview",
    response_model=ReschedulePreviewResponse,
)
def reschedule_preview(
    tournament_id: int,
    payload: ReschedulePreviewRequest,
    session: Session = Depends(get_session),
):
    from datetime import date as _date, time as _time

    version = session.get(ScheduleVersion, payload.version_id)
    if not version or version.tournament_id != tournament_id:
        raise HTTPException(404, "Schedule version not found")
    if version.status != "draft":
        raise HTTPException(400, "Reschedule preview only on DRAFT versions")

    params = RescheduleParams(
        version_id=payload.version_id,
        mode=payload.mode,
        affected_day=_date.fromisoformat(payload.affected_day),
        unavailable_from=_time.fromisoformat(payload.unavailable_from) if payload.unavailable_from else None,
        available_from=_time.fromisoformat(payload.available_from) if payload.available_from else None,
        unavailable_courts=payload.unavailable_courts,
        target_days=[_date.fromisoformat(d) for d in payload.target_days] if payload.target_days else None,
        extend_day_end=_time.fromisoformat(payload.extend_day_end) if payload.extend_day_end else None,
        add_time_slots=payload.add_time_slots,
        block_minutes=payload.block_minutes,
        scoring_format=payload.scoring_format,
    )

    preview = compute_reschedule(session, tournament_id, params)
    return ReschedulePreviewResponse(
        proposed_moves=[
            ProposedMoveItem(
                match_id=m.match_id,
                match_number=m.match_number,
                match_code=m.match_code,
                event_name=m.event_name,
                stage=m.stage,
                old_slot_id=m.old_slot_id,
                old_court=m.old_court,
                old_time=m.old_time,
                old_day=m.old_day,
                new_slot_id=m.new_slot_id,
                new_court=m.new_court,
                new_time=m.new_time,
                new_day=m.new_day,
            )
            for m in preview.proposed_moves
        ],
        unplaceable=[
            UnplaceableItem(
                match_id=u.match_id,
                match_number=u.match_number,
                match_code=u.match_code,
                event_name=u.event_name,
                stage=u.stage,
                reason=u.reason,
            )
            for u in preview.unplaceable
        ],
        new_slots_created=preview.new_slots_created,
        stats=preview.stats,
        format_applied=preview.format_applied,
        duration_updates=preview.duration_updates if preview.duration_updates else None,
    )


@router.post(
    "/desk/tournaments/{tournament_id}/reschedule/apply",
    response_model=RescheduleApplyResponse,
)
def reschedule_apply(
    tournament_id: int,
    payload: RescheduleApplyRequest,
    session: Session = Depends(get_session),
):
    version = session.get(ScheduleVersion, payload.version_id)
    if not version or version.tournament_id != tournament_id:
        raise HTTPException(404, "Schedule version not found")
    if version.status != "draft":
        raise HTTPException(400, "Reschedule apply only on DRAFT versions")

    dur_updates: Optional[Dict[int, int]] = None
    if payload.duration_updates:
        dur_updates = {int(k): v for k, v in payload.duration_updates.items()}

    result = apply_reschedule(session, tournament_id, payload.version_id, payload.moves, dur_updates)
    return RescheduleApplyResponse(**result)


# ── Rebuild Remaining Schedule ──────────────────────────────────────────

class RebuildDayConfigItem(BaseModel):
    date: str         # ISO date
    start_time: str   # HH:MM
    end_time: str     # HH:MM
    courts: int
    format: str       # REGULAR | PRO_SET_8 | PRO_SET_4


class RebuildRequest(BaseModel):
    version_id: int
    days: List[RebuildDayConfigItem]
    drop_consolation: str = "none"
    day1_max_matches: Optional[int] = None


class RebuildMatchItemResponse(BaseModel):
    match_id: int
    match_number: int
    match_code: str
    event_name: str
    stage: str
    team1: str
    team2: str
    status: str
    rank: int
    assigned_day: Optional[str] = None
    assigned_time: Optional[str] = None


class RebuildDaySummary(BaseModel):
    date: str
    slots: int
    courts: int
    format: str
    block_minutes: int


class RebuildPreviewResponse(BaseModel):
    remaining_matches: int
    in_progress_matches: int
    total_slots: int
    fits: bool
    overflow: int
    matches: List[RebuildMatchItemResponse]
    per_day: List[RebuildDaySummary]
    dropped_count: int = 0
    day1_match_count: int = 0


class RebuildApplyResponse(BaseModel):
    assigned: int
    unplaceable: int
    slots_created: int
    duration_updates: int
    dropped_count: int = 0


def _parse_day_configs(items: List[RebuildDayConfigItem]) -> List[RebuildDayConfigDC]:
    from datetime import date as _date, time as _time
    configs = []
    for item in items:
        configs.append(RebuildDayConfigDC(
            day_date=_date.fromisoformat(item.date),
            start_time=_time.fromisoformat(item.start_time),
            end_time=_time.fromisoformat(item.end_time),
            courts=item.courts,
            format=item.format,
        ))
    return configs


@router.post(
    "/desk/tournaments/{tournament_id}/rebuild/preview",
    response_model=RebuildPreviewResponse,
)
def rebuild_preview(
    tournament_id: int,
    payload: RebuildRequest,
    session: Session = Depends(get_session),
):
    version = session.get(ScheduleVersion, payload.version_id)
    if not version or version.tournament_id != tournament_id:
        raise HTTPException(404, "Schedule version not found")

    day_configs = _parse_day_configs(payload.days)
    preview = compute_rebuild_preview(
        session, tournament_id, payload.version_id, day_configs,
        drop_consolation=payload.drop_consolation,
        day1_max_matches=payload.day1_max_matches,
    )

    return RebuildPreviewResponse(
        remaining_matches=preview.remaining_matches,
        in_progress_matches=preview.in_progress_matches,
        total_slots=preview.total_slots,
        fits=preview.fits,
        overflow=preview.overflow,
        matches=[
            RebuildMatchItemResponse(
                match_id=m.match_id,
                match_number=m.match_number,
                match_code=m.match_code,
                event_name=m.event_name,
                stage=m.stage,
                team1=m.team1,
                team2=m.team2,
                status=m.status,
                rank=m.rank,
                assigned_day=m.assigned_day,
                assigned_time=m.assigned_time,
            )
            for m in preview.matches
        ],
        per_day=[
            RebuildDaySummary(**d) for d in preview.per_day
        ],
        dropped_count=preview.dropped_count,
        day1_match_count=preview.day1_match_count,
    )


@router.post(
    "/desk/tournaments/{tournament_id}/rebuild/apply",
    response_model=RebuildApplyResponse,
)
def rebuild_apply(
    tournament_id: int,
    payload: RebuildRequest,
    session: Session = Depends(get_session),
):
    version = session.get(ScheduleVersion, payload.version_id)
    if not version or version.tournament_id != tournament_id:
        raise HTTPException(404, "Schedule version not found")
    if version.status != "draft":
        raise HTTPException(400, "Rebuild only allowed on DRAFT versions")

    day_configs = _parse_day_configs(payload.days)
    result = apply_rebuild(
        session, tournament_id, payload.version_id, day_configs,
        drop_consolation=payload.drop_consolation,
        day1_max_matches=payload.day1_max_matches,
    )

    return RebuildApplyResponse(
        assigned=result.assigned,
        unplaceable=result.unplaceable,
        slots_created=result.slots_created,
        duration_updates=result.duration_updates,
        dropped_count=result.dropped_count,
    )
