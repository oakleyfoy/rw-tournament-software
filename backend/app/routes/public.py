"""
Public read-only API endpoints.

No auth required. Used by public-facing bracket/waterfall pages.
"""
import logging
from typing import Any, Dict, List, Optional, Union

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlmodel import Session, select

from app.database import get_session
from app.models.event import Event
from app.models.match import Match
from app.models.match_assignment import MatchAssignment
from app.models.schedule_slot import ScheduleSlot
from app.models.schedule_version import ScheduleVersion
from app.models.team import Team
from app.models.tournament import Tournament

logger = logging.getLogger(__name__)

router = APIRouter()


# ── Response models ──────────────────────────────────────────────────────

class MatchBox(BaseModel):
    match_id: int
    match_number: int
    court_label: Optional[str] = None
    start_time_local: Optional[str] = None
    status: str  # UNSCHEDULED | SCHEDULED | IN_PROGRESS | FINAL
    score_display: Optional[str] = None
    top_line: str
    line1: str
    line2: str
    notes: Optional[str] = None
    winner_team_id: Optional[int] = None
    team_a_id: Optional[int] = None
    team_b_id: Optional[int] = None


class WaterfallRow(BaseModel):
    loser_box: Optional[MatchBox] = None
    center_box: MatchBox
    winner_box: Optional[MatchBox] = None
    winner_dest: Optional[str] = None
    loser_dest: Optional[str] = None
    r2_winner_team_name: Optional[str] = None
    r2_loser_team_name: Optional[str] = None


class WaterfallResponse(BaseModel):
    tournament_name: str
    event_name: str
    rows: List[WaterfallRow]
    division_type: str = "bracket"  # "bracket" or "roundrobin"


class BracketMatchBox(BaseModel):
    match_id: int
    match_code: str
    match_type: str  # MAIN | CONSOLATION
    round_index: int
    sequence_in_round: int
    top_line: str
    line1: str
    line2: str
    status: str
    score_display: Optional[str] = None
    court_label: Optional[str] = None
    day_display: Optional[str] = None
    time_display: Optional[str] = None
    source_match_a_id: Optional[int] = None
    source_match_b_id: Optional[int] = None


class BracketResponse(BaseModel):
    tournament_name: str
    event_name: str
    division_label: str
    division_code: str
    main_matches: List[BracketMatchBox]
    consolation_matches: List[BracketMatchBox]


class DivisionItem(BaseModel):
    code: str
    label: str

class PublicEventItem(BaseModel):
    event_id: int
    name: str
    category: str
    team_count: int
    has_waterfall: bool
    has_round_robin: bool = False
    divisions: List[DivisionItem] = []


class NotPublishedResponse(BaseModel):
    status: str = "NOT_PUBLISHED"
    message: str = "Schedule not published yet."


class PublicDrawsListResponse(BaseModel):
    tournament_name: str
    events: List[PublicEventItem]


# ── Helpers ──────────────────────────────────────────────────────────────

def _format_score(score_json: Optional[Dict[str, Any]]) -> Optional[str]:
    """Convert score_json dict to display string like '8-4' or '6-3 6-4'."""
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


def _format_time(time_str: Optional[str]) -> Optional[str]:
    """Convert HH:MM:SS to 12-hour format like '9:00 AM'."""
    if not time_str:
        return None
    try:
        parts = time_str.split(":")
        h = int(parts[0])
        m = int(parts[1]) if len(parts) > 1 else 0
        ampm = "AM" if h < 12 else "PM"
        h12 = h % 12 or 12
        return f"{h12}:{m:02d} {ampm}"
    except (ValueError, IndexError):
        return time_str


def _format_day_date(day_date) -> Optional[str]:
    """Format a date as 'Friday \u2022 2/20/26'."""
    if not day_date:
        return None
    try:
        weekdays = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        wd = weekdays[day_date.weekday()]
        short_year = day_date.year % 100
        return f"{wd} \u2022 {day_date.month}/{day_date.day}/{short_year:02d}"
    except Exception:
        return str(day_date)


def _format_court(court_label: Optional[str]) -> Optional[str]:
    """Ensure court label has 'Court' prefix."""
    if not court_label:
        return None
    label = court_label.strip()
    if label.lower().startswith("court"):
        return label
    return f"Court {label}"


def _get_public_version(session: Session, tournament_id: int) -> Optional[ScheduleVersion]:
    """Return the explicitly published schedule version, or None."""
    tournament = session.get(Tournament, tournament_id)
    if not tournament or not tournament.public_schedule_version_id:
        return None
    version = session.get(ScheduleVersion, tournament.public_schedule_version_id)
    if version and version.status != "final" and (not version.notes or version.notes != "Desk Draft"):
        logger.warning(
            "public_schedule_version_id %d points to non-final version (status=%s)",
            tournament.public_schedule_version_id,
            version.status,
        )
    return version


def _build_match_box(
    match: Match,
    team_map: Dict[int, Team],
    assignment_map: Dict[int, MatchAssignment],
    slot_map: Dict[int, ScheduleSlot],
    all_matches_by_id: Dict[int, Match],
    is_center: bool,
) -> MatchBox:
    """Build a MatchBox for a single match."""

    # Status mapping
    if match.runtime_status == "FINAL":
        status = "FINAL"
    elif match.runtime_status == "IN_PROGRESS":
        status = "IN_PROGRESS"
    elif match.id in assignment_map:
        status = "SCHEDULED"
    else:
        status = "UNSCHEDULED"

    # Schedule info
    asgn = assignment_map.get(match.id)
    slot = slot_map.get(asgn.slot_id) if asgn else None
    court_label = slot.court_label if slot else None
    start_time_raw = str(slot.start_time) if slot and slot.start_time else None
    start_time_display = _format_time(start_time_raw)

    # Day/date from slot
    day_display = _format_day_date(slot.day_date) if slot and slot.day_date else None

    # Court label: ensure "Court" prefix
    court_display = _format_court(court_label) if court_label else None

    # Score
    score_display = _format_score(match.score_json) if status == "FINAL" else None

    # Top line: score takes priority over time
    # Format: "Match #1522 - Court 8 - Friday - 2/20/26 - 8:00 AM"
    match_num_str = f"Match #{match.id}"
    if status == "FINAL" and score_display:
        top_line = f"{match_num_str} \u2022 {score_display}"
    elif status in ("SCHEDULED", "IN_PROGRESS") and (court_display or day_display):
        parts = [match_num_str]
        if court_display:
            parts.append(court_display)
        if day_display:
            parts.append(day_display)
        if start_time_display:
            parts.append(start_time_display)
        top_line = " \u2022 ".join(parts)
    else:
        top_line = match_num_str

    # Team lines
    if is_center:
        line1 = _team_full_name(match.team_a_id, match.placeholder_side_a, team_map)
        line2 = _team_full_name(match.team_b_id, match.placeholder_side_b, team_map)
    else:
        line1 = _team_line_for_r2(
            match.team_a_id, match.placeholder_side_a, match.source_match_a_id,
            match.source_a_role, team_map, all_matches_by_id,
        )
        line2 = _team_line_for_r2(
            match.team_b_id, match.placeholder_side_b, match.source_match_b_id,
            match.source_b_role, team_map, all_matches_by_id,
        )

    # Notes (advancement destination)
    notes = _build_notes(match)

    return MatchBox(
        match_id=match.id,
        match_number=match.id,
        court_label=court_label,
        start_time_local=start_time_raw,
        status=status,
        score_display=score_display,
        top_line=top_line,
        line1=line1,
        line2=line2,
        notes=notes,
        winner_team_id=match.winner_team_id,
        team_a_id=match.team_a_id,
        team_b_id=match.team_b_id,
    )


def _team_full_name(
    team_id: Optional[int], placeholder: str, team_map: Dict[int, Team]
) -> str:
    """Team name for R1 center boxes — use display_name (short) if available."""
    if team_id is not None:
        team = team_map.get(team_id)
        if team:
            return team.display_name or team.name
    return placeholder or "TBD"


def _team_line_for_r2(
    team_id: Optional[int],
    placeholder: str,
    source_match_id: Optional[int],
    source_role: Optional[str],
    team_map: Dict[int, Team],
    all_matches: Dict[int, Match],
) -> str:
    """Team line for R2 boxes: show actual name or 'Winner/Loser of Match #X'."""
    if team_id is not None:
        team = team_map.get(team_id)
        if team:
            return team.display_name or team.name

    if source_match_id and source_role:
        role_label = "Winner" if source_role == "WINNER" else "Loser"
        return f"{role_label} of Match #{source_match_id}"

    return placeholder or "TBD"


def _build_notes(match: Match) -> Optional[str]:
    """Build notes text from placeholder info (advancement destinations)."""
    return None


_DIV_LABELS = {
    "BWW": "Division I",
    "BWL": "Division II",
    "BLW": "Division III",
    "BLL": "Division IV",
}


def _r2_dest_lines(event_name: str, r2_role: str, r2_seq: int, r2_winner_count: int) -> str:
    """Two-line destination label for an R2 match.

    Returns 'Winner to ... \\n Loser to ...' with the bracket letter
    derived from the R2 match sequence.
    r2_winner_count is the number of R2 winner matches (n/4 for an n-team event).
    """
    if r2_role == "WINNER":
        win_div = _DIV_LABELS["BWW"]
        lose_div = _DIV_LABELS["BWL"]
        letter = chr(ord("A") + r2_seq - 1)
    else:
        win_div = _DIV_LABELS["BLW"]
        lose_div = _DIV_LABELS["BLL"]
        letter = chr(ord("A") + r2_seq - r2_winner_count - 1)

    return (
        f"Winner to {event_name} {win_div} — {letter}\n"
        f"Loser to {event_name} {lose_div} — {letter}"
    )


# ── Public draws list ────────────────────────────────────────────────────

@router.get(
    "/public/tournaments/{tournament_id}/draws",
    response_model=Union[PublicDrawsListResponse, NotPublishedResponse],
)
def public_draws_list(
    tournament_id: int,
    session: Session = Depends(get_session),
):
    """List events for a tournament, with waterfall availability."""
    tournament = session.get(Tournament, tournament_id)
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")

    version = _get_public_version(session, tournament_id)
    if not version:
        return NotPublishedResponse()

    events = session.exec(
        select(Event).where(Event.tournament_id == tournament_id)
    ).all()

    items: List[PublicEventItem] = []
    for e in sorted(events, key=lambda x: (x.category, x.name)):
        wf_count = len(
            session.exec(
                select(Match.id).where(
                    Match.event_id == e.id,
                    Match.schedule_version_id == version.id,
                    Match.match_type == "WF",
                )
            ).all()
        )
        has_wf = wf_count > 0
        rr_count = len(
            session.exec(
                select(Match.id).where(
                    Match.event_id == e.id,
                    Match.schedule_version_id == version.id,
                    Match.match_type == "RR",
                )
            ).all()
        )
        has_rr = rr_count > 0

        divs: List[DivisionItem] = []
        bracket_codes = session.exec(
            select(Match.match_code).where(
                Match.event_id == e.id,
                Match.schedule_version_id == version.id,
                Match.match_code.isnot(None),
            )
        ).all()
        _DIV_ORDER = ["BWW", "BWL", "BLW", "BLL"]
        found = set()
        for mc in bracket_codes:
            if not mc:
                continue
            for dc in _DIV_ORDER:
                if f"_{dc}_" in mc:
                    found.add(dc)
        for dc in _DIV_ORDER:
            if dc in found:
                divs.append(DivisionItem(code=dc, label=_DIV_LABELS[dc]))

        items.append(PublicEventItem(
            event_id=e.id,
            name=e.name,
            category=e.category,
            team_count=e.team_count,
            has_waterfall=has_wf,
            has_round_robin=has_rr,
            divisions=divs,
        ))

    return PublicDrawsListResponse(
        tournament_name=tournament.name,
        events=items,
    )


# ── Public waterfall ─────────────────────────────────────────────────────

@router.get(
    "/public/tournaments/{tournament_id}/events/{event_id}/waterfall",
    response_model=Union[WaterfallResponse, NotPublishedResponse],
)
def public_waterfall(
    tournament_id: int,
    event_id: int,
    version_id: Optional[int] = Query(None),
    session: Session = Depends(get_session),
):
    """
    Public read-only waterfall bracket for an event.

    Returns rows sorted by R1 sequence_in_round, each with:
    - center_box: the WF R1 match
    - winner_box: the WF R2 winner match this R1 feeds into
    - loser_box: the WF R2 loser match this R1 feeds into
    """
    tournament = session.get(Tournament, tournament_id)
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")

    event = session.get(Event, event_id)
    if not event or event.tournament_id != tournament_id:
        raise HTTPException(status_code=404, detail="Event not found")

    if version_id:
        version = session.get(ScheduleVersion, version_id)
        if not version or version.tournament_id != tournament_id:
            raise HTTPException(status_code=404, detail="Schedule version not found")
    else:
        version = _get_public_version(session, tournament_id)
    if not version:
        return NotPublishedResponse()

    # Load all WF matches for this event + version
    wf_matches = session.exec(
        select(Match).where(
            Match.event_id == event_id,
            Match.schedule_version_id == version.id,
            Match.match_type == "WF",
        )
    ).all()

    if not wf_matches:
        return WaterfallResponse(
            tournament_name=tournament.name,
            event_name=event.name,
            rows=[],
        )

    rr_exists = len(session.exec(
        select(Match.id).where(
            Match.event_id == event_id,
            Match.schedule_version_id == version.id,
            Match.match_type == "RR",
        )
    ).all()) > 0
    div_type = "roundrobin" if rr_exists else "bracket"

    all_matches_by_id = {m.id: m for m in wf_matches}

    # Separate R1 and R2
    r1_matches = sorted(
        [m for m in wf_matches if m.round_index == 1],
        key=lambda m: (m.sequence_in_round or 0, m.id),
    )
    r2_matches = [m for m in wf_matches if m.round_index == 2]

    # Build R1→R2 mappings
    # For each R1 match, find which R2 winner and R2 loser it feeds into
    r1_to_winner: Dict[int, Match] = {}
    r1_to_loser: Dict[int, Match] = {}

    for r2 in r2_matches:
        is_winner_match = r2.source_a_role == "WINNER"
        is_loser_match = r2.source_a_role == "LOSER"

        for src_id in [r2.source_match_a_id, r2.source_match_b_id]:
            if src_id and src_id in all_matches_by_id:
                if is_winner_match:
                    r1_to_winner[src_id] = r2
                elif is_loser_match:
                    r1_to_loser[src_id] = r2

    # Load teams
    team_ids = set()
    for m in wf_matches:
        if m.team_a_id:
            team_ids.add(m.team_a_id)
        if m.team_b_id:
            team_ids.add(m.team_b_id)

    teams = session.exec(
        select(Team).where(Team.id.in_(list(team_ids)))
    ).all() if team_ids else []
    team_map = {t.id: t for t in teams}

    # Load assignments + slots for schedule info
    assignments = session.exec(
        select(MatchAssignment).where(
            MatchAssignment.schedule_version_id == version.id,
        )
    ).all()
    wf_match_ids = {m.id for m in wf_matches}
    assignment_map = {
        a.match_id: a for a in assignments if a.match_id in wf_match_ids
    }

    slot_ids = {a.slot_id for a in assignment_map.values()}
    slots = session.exec(
        select(ScheduleSlot).where(ScheduleSlot.id.in_(list(slot_ids)))
    ).all() if slot_ids else []
    slot_map = {s.id: s for s in slots}

    # Reorder R1 matches so the two that share the same R2 winner
    # destination are consecutive.  The frontend groups every 2 rows
    # into a visual pair, so this ensures correct advancement display.
    r1_by_id = {m.id: m for m in r1_matches}
    paired_r1_ids: set = set()
    ordered_r1: List[Match] = []

    for r2w in sorted(
        [r2 for r2 in r2_matches if r2.source_a_role == "WINNER"],
        key=lambda r2: (r2.sequence_in_round or 0, r2.id),
    ):
        src_ids = [
            sid for sid in [r2w.source_match_a_id, r2w.source_match_b_id]
            if sid and sid in r1_by_id
        ]
        src_ids.sort(key=lambda sid: (r1_by_id[sid].sequence_in_round or 0, sid))
        for sid in src_ids:
            if sid not in paired_r1_ids:
                ordered_r1.append(r1_by_id[sid])
                paired_r1_ids.add(sid)

    for r1 in r1_matches:
        if r1.id not in paired_r1_ids:
            ordered_r1.append(r1)

    # Build rows
    r2_winner_count = sum(
        1 for r2 in r2_matches if r2.source_a_role == "WINNER"
    )
    rows: List[WaterfallRow] = []
    for r1 in ordered_r1:
        center = _build_match_box(
            r1, team_map, assignment_map, slot_map, all_matches_by_id,
            is_center=True,
        )

        winner_match = r1_to_winner.get(r1.id)
        winner = _build_match_box(
            winner_match, team_map, assignment_map, slot_map, all_matches_by_id,
            is_center=False,
        ) if winner_match else None

        loser_match = r1_to_loser.get(r1.id)
        loser = _build_match_box(
            loser_match, team_map, assignment_map, slot_map, all_matches_by_id,
            is_center=False,
        ) if loser_match else None

        winner_dest = None
        loser_dest = None
        if winner_match:
            winner_dest = _r2_dest_lines(
                event.name, "WINNER", winner_match.sequence_in_round,
                r2_winner_count,
            )
        if loser_match:
            loser_dest = _r2_dest_lines(
                event.name, "LOSER", loser_match.sequence_in_round,
                r2_winner_count,
            )

        r2_winner_name = None
        r2_loser_name = None
        if winner_match and winner_match.winner_team_id:
            t = team_map.get(winner_match.winner_team_id)
            if t:
                r2_winner_name = t.display_name or t.name
        if loser_match and loser_match.winner_team_id:
            t = team_map.get(loser_match.winner_team_id)
            if t:
                r2_loser_name = t.display_name or t.name

        rows.append(WaterfallRow(
            center_box=center,
            winner_box=winner,
            loser_box=loser,
            winner_dest=winner_dest,
            loser_dest=loser_dest,
            r2_winner_team_name=r2_winner_name,
            r2_loser_team_name=r2_loser_name,
        ))

    return WaterfallResponse(
        tournament_name=tournament.name,
        event_name=event.name,
        rows=rows,
        division_type=div_type,
    )


# ── Public bracket ──────────────────────────────────────────────────────

_CODE_TO_DIV = {"BWW": "Division I", "BWL": "Division II",
                "BLW": "Division III", "BLL": "Division IV"}

_ROUND_LABELS = {1: "Quarterfinal", 2: "Semifinal", 3: "Final"}


def _bracket_team_line(
    team_id: Optional[int],
    placeholder: Optional[str],
    source_match_id: Optional[int],
    source_role: Optional[str],
    team_map: Dict[int, Team],
    match_map: Dict[int, Match],
) -> str:
    if team_id:
        team = team_map.get(team_id)
        if team:
            return team.display_name or team.name
    if source_match_id and source_role:
        role = "Winner" if source_role == "WINNER" else "Loser"
        return f"{role} of Match #{source_match_id}"
    if placeholder:
        if "_WF_R2_W" in placeholder:
            seq = int(placeholder.rsplit("W", 1)[-1].lstrip("0") or "1")
            letter = chr(ord("A") + seq - 1)
            return f"Winner {letter}"
        if "_WF_R2_L" in placeholder:
            seq = int(placeholder.rsplit("L", 1)[-1].lstrip("0") or "1")
            letter = chr(ord("A") + seq - 1)
            return f"Loser {letter}"
        return placeholder
    return "TBD"


def _build_bracket_box(
    match: Match,
    team_map: Dict[int, Team],
    assignment_map: Dict[int, Any],
    slot_map: Dict[int, Any],
    match_map: Dict[int, Match],
) -> BracketMatchBox:
    status = (match.status or "unscheduled").upper()
    asgn = assignment_map.get(match.id)
    slot = slot_map.get(asgn.slot_id) if asgn else None
    court_label = slot.court_label if slot else None
    start_time_raw = str(slot.start_time) if slot and slot.start_time else None
    start_time_display = _format_time(start_time_raw)
    day_display = _format_day_date(slot.day_date) if slot and slot.day_date else None
    court_display = _format_court(court_label) if court_label else None
    score_display = _format_score(match.score_json) if status == "FINAL" else None

    match_num_str = f"Match #{match.id}"
    if status == "FINAL" and score_display:
        top_line = f"{match_num_str} \u2022 {score_display}"
    elif status in ("SCHEDULED", "IN_PROGRESS") and (court_display or day_display):
        parts = [match_num_str]
        if court_display:
            parts.append(court_display)
        if day_display:
            parts.append(day_display)
        if start_time_display:
            parts.append(start_time_display)
        top_line = " \u2022 ".join(parts)
    else:
        top_line = match_num_str

    line1 = _bracket_team_line(
        match.team_a_id, match.placeholder_side_a,
        match.source_match_a_id, match.source_a_role,
        team_map, match_map,
    )
    line2 = _bracket_team_line(
        match.team_b_id, match.placeholder_side_b,
        match.source_match_b_id, match.source_b_role,
        team_map, match_map,
    )

    return BracketMatchBox(
        match_id=match.id,
        match_code=match.match_code or "",
        match_type=match.match_type or "MAIN",
        round_index=match.round_index or 0,
        sequence_in_round=match.sequence_in_round or 0,
        top_line=top_line,
        line1=line1,
        line2=line2,
        status=status,
        score_display=score_display,
        court_label=court_display,
        day_display=day_display,
        time_display=start_time_display,
        source_match_a_id=match.source_match_a_id,
        source_match_b_id=match.source_match_b_id,
    )


@router.get(
    "/public/tournaments/{tournament_id}/events/{event_id}/bracket/{division_code}",
    response_model=Union[BracketResponse, NotPublishedResponse],
)
def public_bracket(
    tournament_id: int,
    event_id: int,
    division_code: str,
    version_id: Optional[int] = Query(None),
    session: Session = Depends(get_session),
):
    """Public read-only bracket for a division (BWW, BWL, BLW, BLL)."""
    tournament = session.get(Tournament, tournament_id)
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")

    event = session.get(Event, event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    if version_id:
        version = session.get(ScheduleVersion, version_id)
        if not version or version.tournament_id != tournament_id:
            raise HTTPException(status_code=404, detail="Schedule version not found")
    else:
        version = _get_public_version(session, tournament_id)
    if not version:
        return NotPublishedResponse()

    div_upper = division_code.upper()
    div_label = _CODE_TO_DIV.get(div_upper, division_code)

    bracket_matches = session.exec(
        select(Match).where(
            Match.event_id == event_id,
            Match.schedule_version_id == version.id,
            Match.match_code.contains(f"_{div_upper}_"),
        )
    ).all()

    if not bracket_matches:
        return BracketResponse(
            tournament_name=tournament.name,
            event_name=event.name,
            division_label=div_label,
            division_code=div_upper,
            main_matches=[],
            consolation_matches=[],
        )

    match_map = {m.id: m for m in bracket_matches}

    team_ids = set()
    for m in bracket_matches:
        if m.team_a_id:
            team_ids.add(m.team_a_id)
        if m.team_b_id:
            team_ids.add(m.team_b_id)
    teams = session.exec(
        select(Team).where(Team.id.in_(list(team_ids)))
    ).all() if team_ids else []
    team_map = {t.id: t for t in teams}

    assignments = session.exec(
        select(MatchAssignment).where(
            MatchAssignment.schedule_version_id == version.id,
        )
    ).all()
    bracket_ids = {m.id for m in bracket_matches}
    assignment_map = {a.match_id: a for a in assignments if a.match_id in bracket_ids}
    slot_ids = {a.slot_id for a in assignment_map.values()}
    slots = session.exec(
        select(ScheduleSlot).where(ScheduleSlot.id.in_(list(slot_ids)))
    ).all() if slot_ids else []
    slot_map = {s.id: s for s in slots}

    main_matches = []
    consolation_matches = []

    for m in sorted(bracket_matches,
                    key=lambda m: (m.round_index or 0, m.sequence_in_round or 0)):
        box = _build_bracket_box(m, team_map, assignment_map, slot_map, match_map)
        if (m.match_type or "").upper() == "CONSOLATION":
            consolation_matches.append(box)
        else:
            main_matches.append(box)

    return BracketResponse(
        tournament_name=tournament.name,
        event_name=event.name,
        division_label=div_label,
        division_code=div_upper,
        main_matches=main_matches,
        consolation_matches=consolation_matches,
    )


# ── Public round robin ──────────────────────────────────────────────────

_POOL_LABELS = {"POOLA": "Division I", "POOLB": "Division II",
                "POOLC": "Division III", "POOLD": "Division IV"}


class RRMatchBox(BaseModel):
    match_id: int
    match_code: str
    line1: str
    line2: str
    status: str
    score_display: Optional[str] = None
    court_label: Optional[str] = None
    day_display: Optional[str] = None
    time_display: Optional[str] = None
    winner_name: Optional[str] = None


class RRPool(BaseModel):
    pool_code: str
    pool_label: str
    matches: List[RRMatchBox]


class RRStandingsRow(BaseModel):
    team_id: int
    team_display: str
    wins: int = 0
    losses: int = 0
    sets_won: int = 0
    sets_lost: int = 0
    games_won: int = 0
    games_lost: int = 0
    played: int = 0


class RRPoolStandings(BaseModel):
    pool_code: str
    pool_label: str
    rows: List[RRStandingsRow]


class RoundRobinResponse(BaseModel):
    tournament_name: str
    event_name: str
    pools: List[RRPool]
    standings: List[RRPoolStandings] = []
    tiebreaker_note: str = (
        "*Tie Breakers are determined in the following order: "
        "1) Sets Lost 2) Games Lost 3) Head to Head"
    )


@router.get(
    "/public/tournaments/{tournament_id}/events/{event_id}/roundrobin",
    response_model=Union[RoundRobinResponse, NotPublishedResponse],
)
def public_round_robin(
    tournament_id: int,
    event_id: int,
    version_id: Optional[int] = Query(None),
    session: Session = Depends(get_session),
):
    """Public read-only round robin pools for an event."""
    tournament = session.get(Tournament, tournament_id)
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")
    event = session.get(Event, event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    if version_id:
        version = session.get(ScheduleVersion, version_id)
        if not version or version.tournament_id != tournament_id:
            raise HTTPException(status_code=404, detail="Schedule version not found")
    else:
        version = _get_public_version(session, tournament_id)
    if not version:
        return NotPublishedResponse()

    rr_matches = session.exec(
        select(Match).where(
            Match.event_id == event_id,
            Match.schedule_version_id == version.id,
            Match.match_type == "RR",
        )
    ).all()

    if not rr_matches:
        return RoundRobinResponse(
            tournament_name=tournament.name,
            event_name=event.name,
            pools=[],
        )

    team_ids = set()
    for m in rr_matches:
        if m.team_a_id:
            team_ids.add(m.team_a_id)
        if m.team_b_id:
            team_ids.add(m.team_b_id)
    teams = session.exec(
        select(Team).where(Team.id.in_(list(team_ids)))
    ).all() if team_ids else []
    team_map: Dict[int, Team] = {t.id: t for t in teams}

    rr_ids = {m.id for m in rr_matches}
    assignments = session.exec(
        select(MatchAssignment).where(
            MatchAssignment.schedule_version_id == version.id,
        )
    ).all()
    assignment_map = {a.match_id: a for a in assignments if a.match_id in rr_ids}
    slot_ids = {a.slot_id for a in assignment_map.values()}
    slots = session.exec(
        select(ScheduleSlot).where(ScheduleSlot.id.in_(list(slot_ids)))
    ).all() if slot_ids else []
    slot_map = {s.id: s for s in slots}

    pool_matches: Dict[str, List[Match]] = {}
    for m in rr_matches:
        parts = m.match_code.split("_RR_")
        pool_key = parts[0].split("_")[-1] if parts else "POOLA"
        pool_matches.setdefault(pool_key, []).append(m)

    pools: List[RRPool] = []
    for pool_code in sorted(pool_matches.keys()):
        matches = sorted(
            pool_matches[pool_code],
            key=lambda m: (m.round_index or 0, m.sequence_in_round or 0),
        )
        boxes: List[RRMatchBox] = []
        for m in matches:
            line1 = _rr_team_line(m.team_a_id, m.placeholder_side_a, team_map)
            line2 = _rr_team_line(m.team_b_id, m.placeholder_side_b, team_map)

            status = (m.status or "UNSCHEDULED").upper()
            score_display = None
            if m.score_json:
                import json
                try:
                    sd = json.loads(m.score_json) if isinstance(m.score_json, str) else m.score_json
                    if isinstance(sd, dict) and sd.get("display"):
                        score_display = sd["display"]
                    elif isinstance(sd, str):
                        score_display = sd
                except Exception:
                    pass

            winner_name = None
            if m.winner_team_id:
                wt = team_map.get(m.winner_team_id)
                if wt:
                    winner_name = wt.display_name or wt.name

            court_display = None
            day_display = None
            time_display = None
            a = assignment_map.get(m.id)
            if a:
                slot = slot_map.get(a.slot_id)
                if slot:
                    court_display = f"Court {slot.court_number}" if slot.court_number else None
                    if slot.day_date:
                        from datetime import datetime, date as date_type, time as time_type
                        dd = slot.day_date
                        if isinstance(dd, str):
                            dd = date_type.fromisoformat(dd)
                        day_display = dd.strftime("%A, %B %d, %Y")
                    if slot.start_time:
                        from datetime import time as time_type
                        st = slot.start_time
                        if isinstance(st, str):
                            parts = st.split(":")
                            h, mi = int(parts[0]), int(parts[1])
                            ampm = "AM" if h < 12 else "PM"
                            h12 = h % 12 or 12
                            time_display = f"{h12}:{mi:02d} {ampm}"
                        else:
                            time_display = st.strftime("%I:%M %p").lstrip("0")

            boxes.append(RRMatchBox(
                match_id=m.id,
                match_code=m.match_code,
                line1=line1,
                line2=line2,
                status=status,
                score_display=score_display,
                court_label=court_display,
                day_display=day_display,
                time_display=time_display,
                winner_name=winner_name,
            ))

        pools.append(RRPool(
            pool_code=pool_code,
            pool_label=_POOL_LABELS.get(pool_code, pool_code),
            matches=boxes,
        ))

    # Compute standings per pool from FINAL matches
    from app.services.score_parser import parse_score as _parse_score

    standings_list: List[RRPoolStandings] = []
    for pool_code in sorted(pool_matches.keys()):
        matches_in_pool = pool_matches[pool_code]

        pool_team_ids: set = set()
        for m in matches_in_pool:
            if m.team_a_id:
                pool_team_ids.add(m.team_a_id)
            if m.team_b_id:
                pool_team_ids.add(m.team_b_id)

        rows_data: Dict[int, dict] = {}
        for tid in pool_team_ids:
            rows_data[tid] = {"wins": 0, "losses": 0, "sets_won": 0, "sets_lost": 0, "games_won": 0, "games_lost": 0, "played": 0}

        for m in matches_in_pool:
            rt = (m.runtime_status or "SCHEDULED").upper()
            if rt != "FINAL":
                continue
            if not m.team_a_id or not m.team_b_id or not m.winner_team_id:
                continue
            a_id, b_id = m.team_a_id, m.team_b_id
            if m.winner_team_id == a_id:
                rows_data[a_id]["wins"] += 1
                rows_data[b_id]["losses"] += 1
            else:
                rows_data[b_id]["wins"] += 1
                rows_data[a_id]["losses"] += 1
            rows_data[a_id]["played"] += 1
            rows_data[b_id]["played"] += 1

            parsed = _parse_score(m.score_json)
            if parsed:
                rows_data[a_id]["sets_won"] += parsed.team_a_sets_won
                rows_data[a_id]["sets_lost"] += parsed.team_b_sets_won
                rows_data[b_id]["sets_won"] += parsed.team_b_sets_won
                rows_data[b_id]["sets_lost"] += parsed.team_a_sets_won
                rows_data[a_id]["games_won"] += parsed.team_a_games
                rows_data[a_id]["games_lost"] += parsed.team_b_games
                rows_data[b_id]["games_won"] += parsed.team_b_games
                rows_data[b_id]["games_lost"] += parsed.team_a_games

        def _disp(tid: int) -> str:
            t = team_map.get(tid)
            return (t.display_name or t.name or f"Team {tid}") if t else f"Team {tid}"

        sorted_rows = sorted(
            rows_data.items(),
            key=lambda item: (
                -item[1]["wins"],
                -(item[1]["sets_won"] - item[1]["sets_lost"]),
                -(item[1]["games_won"] - item[1]["games_lost"]),
                _disp(item[0]),
            ),
        )

        standings_list.append(RRPoolStandings(
            pool_code=pool_code,
            pool_label=_POOL_LABELS.get(pool_code, pool_code),
            rows=[
                RRStandingsRow(team_id=tid, team_display=_disp(tid), **r)
                for tid, r in sorted_rows
            ],
        ))

    return RoundRobinResponse(
        tournament_name=tournament.name,
        event_name=event.name,
        pools=pools,
        standings=standings_list,
    )


def _rr_team_line(team_id: Optional[int], placeholder: Optional[str], team_map: Dict[int, Team]) -> str:
    if team_id:
        t = team_map.get(team_id)
        if t:
            return t.display_name or t.name
    if placeholder:
        if placeholder.startswith("SEED_"):
            return f"Seed {placeholder[5:]}"
        return placeholder
    return "TBD"


# ── Public schedule ─────────────────────────────────────────────────────


class ScheduleMatchItem(BaseModel):
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
    sort_time: Optional[str] = None  # 24h "HH:MM" for correct chronological sorting
    court_name: Optional[str] = None
    status: str
    team1_display: str
    team2_display: str
    team1_full_name: str
    team2_full_name: str
    score_display: Optional[str] = None
    winner_team_id: Optional[int] = None
    team_a_id: Optional[int] = None
    team_b_id: Optional[int] = None


class ScheduleEventOption(BaseModel):
    event_id: int
    event_name: str


class ScheduleDayOption(BaseModel):
    day_index: int
    label: str


class PublicScheduleResponse(BaseModel):
    status: str = "OK"
    tournament_name: str
    published_version_id: int
    matches: List[ScheduleMatchItem]
    events: List[ScheduleEventOption]
    divisions: List[str]
    days: List[ScheduleDayOption]


_STAGE_MAP = {
    "WF": "WF",
    "RR": "RR",
    "MAIN": "BRACKET",
    "CONSOLATION": "CONS",
    "PLACEMENT": "PLACEMENT",
}


def _derive_division(match_code: str, match_type: str) -> Optional[str]:
    """Extract division name from match code."""
    if match_type == "RR":
        for pool_code, label in _POOL_LABELS.items():
            if f"_{pool_code}_" in match_code.upper():
                return label
        return None
    for div_code, label in _DIV_LABELS.items():
        if f"_{div_code}_" in match_code:
            return label
    return None


def _schedule_team_line(
    team_id: Optional[int],
    placeholder: Optional[str],
    team_map: Dict[int, Team],
    short: bool = True,
) -> str:
    if team_id:
        t = team_map.get(team_id)
        if t:
            if short:
                return t.display_name or t.name
            return t.name
    return placeholder or "TBD"


@router.get(
    "/public/tournaments/{tournament_id}/schedule",
    response_model=Union[PublicScheduleResponse, NotPublishedResponse],
)
def public_schedule(
    tournament_id: int,
    event_id: Optional[int] = Query(None),
    division: Optional[str] = Query(None),
    day: Optional[int] = Query(None),
    search: Optional[str] = Query(None),
    session: Session = Depends(get_session),
):
    """Public read-only schedule for a tournament."""
    tournament = session.get(Tournament, tournament_id)
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")

    version = _get_public_version(session, tournament_id)
    if not version:
        return NotPublishedResponse()

    all_matches = session.exec(
        select(Match).where(Match.schedule_version_id == version.id)
    ).all()

    if not all_matches:
        return PublicScheduleResponse(
            tournament_name=tournament.name,
            published_version_id=version.id,
            matches=[],
            events=[],
            divisions=[],
            days=[],
        )

    # Bulk-load related data
    match_ids = [m.id for m in all_matches]
    assignments = session.exec(
        select(MatchAssignment).where(
            MatchAssignment.schedule_version_id == version.id,
            MatchAssignment.match_id.in_(match_ids),
        )
    ).all()
    assignment_map: Dict[int, MatchAssignment] = {a.match_id: a for a in assignments}

    slot_ids = list({a.slot_id for a in assignments})
    slots = session.exec(
        select(ScheduleSlot).where(ScheduleSlot.id.in_(slot_ids))
    ).all() if slot_ids else []
    slot_map: Dict[int, ScheduleSlot] = {s.id: s for s in slots}

    team_ids = set()
    for m in all_matches:
        if m.team_a_id:
            team_ids.add(m.team_a_id)
        if m.team_b_id:
            team_ids.add(m.team_b_id)
    teams = session.exec(
        select(Team).where(Team.id.in_(list(team_ids)))
    ).all() if team_ids else []
    team_map: Dict[int, Team] = {t.id: t for t in teams}

    event_ids = list({m.event_id for m in all_matches})
    events = session.exec(
        select(Event).where(Event.id.in_(event_ids))
    ).all()
    event_map: Dict[int, Event] = {e.id: e for e in events}

    # Build flat list
    items: List[ScheduleMatchItem] = []
    all_divisions: set = set()
    all_event_options: Dict[int, str] = {}
    all_day_options: Dict[int, str] = {}

    for m in all_matches:
        ev = event_map.get(m.event_id)
        ev_name = ev.name if ev else "Unknown"
        all_event_options[m.event_id] = ev_name

        stage = _STAGE_MAP.get(m.match_type, m.match_type)
        div_name = _derive_division(m.match_code or "", m.match_type or "")
        if div_name:
            all_divisions.add(div_name)

        a = assignment_map.get(m.id)
        slot = slot_map.get(a.slot_id) if a else None

        if slot:
            day_offset = (slot.day_date - tournament.start_date).days + 1
            weekday = slot.day_date.strftime("%A")
            month_day = slot.day_date.strftime("%B %d").replace(" 0", " ")
            day_label = f"{weekday}, {month_day}"
            all_day_options[day_offset] = day_label

            st = slot.start_time
            if isinstance(st, str):
                scheduled_time = _format_time(st)
                sort_time = st[:5] if len(st) >= 5 else st
            else:
                scheduled_time = st.strftime("%I:%M %p").lstrip("0") if st else None
                sort_time = st.strftime("%H:%M") if st else None

            court_name = f"Court {slot.court_label}" if slot.court_label else (
                f"Court {slot.court_number}" if slot.court_number else None
            )
            if court_name and court_name.lower().startswith("court court"):
                court_name = court_name[6:]
        else:
            day_offset = 0
            day_label = "Unscheduled"
            scheduled_time = None
            sort_time = None
            court_name = None

        status = (m.runtime_status or "SCHEDULED").upper()
        score = _format_score(m.score_json) if status == "FINAL" else None

        t1_display = _schedule_team_line(m.team_a_id, m.placeholder_side_a, team_map, short=True)
        t2_display = _schedule_team_line(m.team_b_id, m.placeholder_side_b, team_map, short=True)
        t1_full = _schedule_team_line(m.team_a_id, m.placeholder_side_a, team_map, short=False)
        t2_full = _schedule_team_line(m.team_b_id, m.placeholder_side_b, team_map, short=False)

        items.append(ScheduleMatchItem(
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
            team1_display=t1_display,
            team2_display=t2_display,
            team1_full_name=t1_full,
            team2_full_name=t2_full,
            score_display=score,
            winner_team_id=m.winner_team_id,
            team_a_id=m.team_a_id,
            team_b_id=m.team_b_id,
        ))

    # Compute filter options from full (unfiltered) set
    event_options = sorted(
        [ScheduleEventOption(event_id=eid, event_name=en) for eid, en in all_event_options.items()],
        key=lambda x: x.event_name,
    )
    day_options = sorted(
        [ScheduleDayOption(day_index=di, label=dl) for di, dl in all_day_options.items()],
        key=lambda x: x.day_index,
    )
    division_list = sorted(all_divisions)

    # Apply filters
    filtered = items
    if event_id is not None:
        filtered = [m for m in filtered if m.event_id == event_id]
    if division:
        filtered = [m for m in filtered if m.division_name and m.division_name.upper() == division.upper()]
    if day is not None:
        filtered = [m for m in filtered if m.day_index == day]
    if search:
        q = search.lower()
        filtered = [
            m for m in filtered
            if q in m.team1_display.lower()
            or q in m.team2_display.lower()
            or q in m.team1_full_name.lower()
            or q in m.team2_full_name.lower()
        ]

    # Sort by day, time (24h), court
    filtered.sort(key=lambda m: (m.day_index, m.sort_time or "", m.court_name or ""))

    return PublicScheduleResponse(
        tournament_name=tournament.name,
        published_version_id=version.id,
        matches=filtered,
        events=event_options,
        divisions=division_list,
        days=day_options,
    )
