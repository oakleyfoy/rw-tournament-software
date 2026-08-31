"""Read-only tournament display-board snapshot.

Canonical live sections for TV/monitor boards:
- currently_playing
- waiting_for_court
- upcoming
- upcoming_12h (NOW through next 12 hours; excludes playing/completed/past)

Does not mutate schedule, check-in, court assignment, or match runtime state.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone, tzinfo
from datetime import time as dt_time
from typing import Any, Dict, List, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

from sqlmodel import Session, select

from app.models.event import Event
from app.models.match import Match
from app.models.match_assignment import MatchAssignment
from app.models.match_checkin import MatchCheckIn
from app.models.match_player_checkin import MatchPlayerCheckIn
from app.models.player import Player
from app.models.schedule_slot import ScheduleSlot
from app.models.schedule_version import ScheduleVersion
from app.models.team import Team
from app.models.team_player import TeamPlayer
from app.models.tournament import Tournament

DESK_DRAFT_TAG = "Desk Draft"
UPCOMING_WINDOW_HOURS = 12
PLAYING_STATUSES = {"IN_PROGRESS", "PAUSED"}
COMPLETED_STATUSES = {"FINAL"}
HIDDEN_MATCH_STATUSES = {"cancelled", "complete"}

STAGE_MAP = {
    "WF": "WF",
    "RR": "RR",
    "MAIN": "BRACKET",
    "CONSOLATION": "CONS",
    "PLACEMENT": "PLACEMENT",
}

DIV_LABELS = {
    "BWW": "Division I",
    "BWL": "Division II",
    "BLW": "Division III",
    "BLL": "Division IV",
}

POOL_LABELS = {
    "POOLA": "Division I",
    "POOLB": "Division II",
    "POOLC": "Division III",
    "POOLD": "Division IV",
    "POOLE": "Division V",
    "POOLF": "Division VI",
    "POOLG": "Division VII",
    "POOLH": "Division VIII",
}

TBD_LABEL = "TBD"


class DisplayBoardError(Exception):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


@dataclass
class DisplayMatchData:
    match_id: int
    scheduled_at: Optional[str]
    scheduled_time: Optional[str]
    sort_time: Optional[str]
    day_date: Optional[str]
    event_name: str
    division_name: Optional[str]
    event_label: str
    round_label: Optional[str]
    stage: str
    team_a_names: str
    team_b_names: str
    team_a_checked_in: bool
    team_b_checked_in: bool
    team_a_has_tbd: bool
    team_b_has_tbd: bool
    board_section: str
    in_next_12_hours: bool
    court: Optional[str] = None


@dataclass
class DisplayTimeGroup:
    scheduled_time: str
    sort_time: str
    matches: List[DisplayMatchData] = field(default_factory=list)


@dataclass
class DisplayBoardSnapshot:
    tournament_id: int
    tournament_name: str
    tournament_timezone: str
    now_local: str
    currently_playing: List[DisplayMatchData]
    waiting_for_court: List[DisplayMatchData]
    upcoming: List[DisplayMatchData]
    upcoming_12h: List[DisplayMatchData]
    upcoming_12h_groups: List[DisplayTimeGroup]


def now_in_timezone(tz: tzinfo) -> datetime:
    return datetime.now(tz)


def tournament_zoneinfo(timezone_name: Optional[str]) -> tzinfo:
    tz_name = (timezone_name or "UTC").strip() or "UTC"
    try:
        return ZoneInfo(tz_name)
    except Exception:
        return timezone.utc


def format_clock(value: dt_time) -> str:
    hour = value.hour
    minute = value.minute
    ampm = "AM" if hour < 12 else "PM"
    hour12 = hour % 12 or 12
    return f"{hour12}:{minute:02d} {ampm}"


def coerce_slot_start_time(value: object) -> Optional[dt_time]:
    if isinstance(value, dt_time):
        return value
    if isinstance(value, str):
        try:
            parts = value.split(":")
            hour = int(parts[0]) if parts else 0
            minute = int(parts[1]) if len(parts) > 1 else 0
            return dt_time(hour, minute)
        except Exception:
            return None
    return None


def _is_tbd_token(value: Optional[str]) -> bool:
    raw = " ".join((value or "").strip().lower().split())
    if not raw:
        return False
    if raw in {"tbd", "tbd partner", "partner tbd"}:
        return True
    return raw.startswith("tbd:") or raw.startswith("tbd ")


def _cap_first(value: str) -> str:
    return (value[:1].upper() + value[1:]) if value else value


def first_name_only(value: Optional[str]) -> str:
    raw = " ".join((value or "").strip().split())
    if not raw:
        return ""
    if _is_tbd_token(raw):
        return TBD_LABEL
    if "," in raw:
        segments = [segment.strip() for segment in raw.split(",") if segment.strip()]
        if len(segments) >= 2:
            first_segment_words = segments[0].split()
            second_segment_words = segments[1].split()
            if len(first_segment_words) == 1 and second_segment_words:
                return first_name_only(second_segment_words[0])
            if first_segment_words:
                return first_name_only(first_segment_words[0])
    parts = raw.split()
    token = parts[0] if parts else raw
    if _is_tbd_token(token):
        return TBD_LABEL
    return _cap_first(token)


def split_team_player_names(team_name: Optional[str]) -> List[str]:
    raw = (team_name or "").strip()
    if not raw:
        return []
    if "/" in raw:
        parts = [part.strip() for part in raw.split("/") if part.strip()]
    elif "&" in raw:
        parts = [part.strip() for part in raw.split("&") if part.strip()]
    else:
        parts = [raw]
    return parts[:2]


def first_names_from_text(value: Optional[str]) -> Tuple[str, bool]:
    parts = split_team_player_names(value)
    if not parts:
        return "", False
    names = [first_name_only(part) or TBD_LABEL for part in parts]
    has_tbd = any(_is_tbd_token(part) or name == TBD_LABEL for part, name in zip(parts, names))
    if len(names) == 1:
        return names[0], has_tbd
    return " / ".join(names), has_tbd


def placeholder_display(placeholder: Optional[str]) -> Tuple[str, bool]:
    raw = " ".join((placeholder or "").strip().split())
    if not raw:
        return TBD_LABEL, True
    if _is_tbd_token(raw):
        return TBD_LABEL, True
    return raw, False


def derive_division(match_code: str, match_type: str) -> Optional[str]:
    code = (match_code or "").upper()
    if match_type == "RR":
        for pool_code, label in POOL_LABELS.items():
            if f"_{pool_code}_" in code:
                return label
        return None
    for div_code, label in DIV_LABELS.items():
        if f"_{div_code}_" in (match_code or ""):
            return label
    return None


def event_label(event_name: str, division_name: Optional[str]) -> str:
    name = (event_name or "").strip() or "Unknown"
    division = (division_name or "").strip()
    if not division:
        return name
    if division.lower() in name.lower():
        return name
    return f"{name} · {division}"


def round_label(match_type: str, round_number: Optional[int]) -> Optional[str]:
    stage = STAGE_MAP.get(match_type, match_type or "")
    if not stage:
        return None
    if round_number:
        return f"{stage} R{round_number}"
    return stage


def court_display(slot: ScheduleSlot) -> str:
    label = (slot.court_label or str(slot.court_number) or "").strip() or str(slot.court_number)
    if label.lower().startswith("court"):
        return label
    return f"Court {label}"


def resolve_schedule_version(
    session: Session,
    tournament: Tournament,
    version_id: Optional[int] = None,
) -> ScheduleVersion:
    """Prefer the live desk draft, then published, then latest final."""
    if version_id:
        version = session.get(ScheduleVersion, version_id)
        if not version or version.tournament_id != tournament.id:
            raise DisplayBoardError(404, "Schedule version not found")
        return version

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
        published = session.get(ScheduleVersion, tournament.public_schedule_version_id)
        if published:
            return published

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

    raise DisplayBoardError(404, "No schedule exists")


def _side_checked_in(
    *,
    match_id: int,
    side: str,
    team_id: Optional[int],
    team_checkin_map: Dict[Tuple[int, str], MatchCheckIn],
    player_checkin_map: Dict[Tuple[int, str, int], MatchPlayerCheckIn],
    players_by_team: Dict[int, List[int]],
) -> bool:
    team_row = team_checkin_map.get((match_id, side))
    if team_row and team_row.team_checked_in:
        return True
    if not team_id:
        return False
    player_ids = players_by_team.get(team_id, [])
    if not player_ids:
        return False
    for pid in player_ids:
        row = player_checkin_map.get((match_id, side, pid))
        if not row or not row.checked_in:
            return False
    return True


def _team_first_names(
    *,
    team_id: Optional[int],
    placeholder: Optional[str],
    team_map: Dict[int, Team],
    players_by_team: Dict[int, List[int]],
    player_map: Dict[int, Player],
) -> Tuple[str, bool]:
    if not team_id:
        return placeholder_display(placeholder)

    team = team_map.get(team_id)
    player_ids = players_by_team.get(team_id, [])
    if player_ids:
        names: List[str] = []
        has_tbd = False
        for pid in player_ids[:2]:
            player = player_map.get(pid)
            source = (player.display_name or player.full_name) if player else ""
            token = first_name_only(source) or TBD_LABEL
            if token == TBD_LABEL:
                has_tbd = True
            names.append(token)
        if len(names) == 1:
            names.append(TBD_LABEL)
            has_tbd = True
        return " / ".join(names), has_tbd

    if team:
        parsed, has_tbd = first_names_from_text(team.name)
        if parsed:
            parts = split_team_player_names(team.name)
            if len(parts) == 1:
                return f"{parsed} / {TBD_LABEL}", True
            return parsed, has_tbd
        parsed_display, has_tbd_display = first_names_from_text(team.display_name)
        if parsed_display:
            return parsed_display, has_tbd_display
    return placeholder_display(placeholder)


def _sort_key(match: DisplayMatchData) -> Tuple:
    return (
        match.day_date or "",
        match.sort_time or "",
        (match.event_name or "").lower(),
        (match.division_name or "").lower(),
        match.match_id,
    )


def _playing_sort_key(match: DisplayMatchData) -> Tuple:
    court_key = (match.court or "").lower()
    return (court_key, match.day_date or "", match.sort_time or "", match.match_id)


def build_display_board(
    session: Session,
    tournament_id: int,
    version_id: Optional[int] = None,
) -> DisplayBoardSnapshot:
    tournament = session.get(Tournament, tournament_id)
    if not tournament:
        raise DisplayBoardError(404, "Tournament not found")

    version = resolve_schedule_version(session, tournament, version_id)
    tz = tournament_zoneinfo(tournament.timezone)
    now_local_dt = now_in_timezone(tz)
    window_end = now_local_dt + timedelta(hours=UPCOMING_WINDOW_HOURS)

    matches = session.exec(select(Match).where(Match.schedule_version_id == version.id)).all()
    assignments = session.exec(select(MatchAssignment).where(MatchAssignment.schedule_version_id == version.id)).all()
    assignment_map = {row.match_id: row for row in assignments}

    slot_ids = list({row.slot_id for row in assignments})
    slots = session.exec(select(ScheduleSlot).where(ScheduleSlot.id.in_(slot_ids))).all() if slot_ids else []
    slot_map = {row.id: row for row in slots}

    team_ids = {tid for m in matches for tid in (m.team_a_id, m.team_b_id) if tid}
    teams = session.exec(select(Team).where(Team.id.in_(list(team_ids)))).all() if team_ids else []
    team_map = {row.id: row for row in teams}

    event_ids = list({m.event_id for m in matches})
    events = session.exec(select(Event).where(Event.id.in_(event_ids))).all() if event_ids else []
    event_map = {row.id: row for row in events}

    team_player_rows = (
        session.exec(
            select(TeamPlayer)
            .where(TeamPlayer.team_id.in_(list(team_ids)))
            .order_by(TeamPlayer.team_id, TeamPlayer.lineup_slot, TeamPlayer.id)
        ).all()
        if team_ids
        else []
    )
    players_by_team: Dict[int, List[int]] = {}
    player_ids: set[int] = set()
    for row in team_player_rows:
        players_by_team.setdefault(row.team_id, []).append(row.player_id)
        player_ids.add(row.player_id)
    players = session.exec(select(Player).where(Player.id.in_(list(player_ids)))).all() if player_ids else []
    player_map = {row.id: row for row in players}

    team_checkins = session.exec(select(MatchCheckIn).where(MatchCheckIn.schedule_version_id == version.id)).all()
    team_checkin_map = {(row.match_id, (row.side or "").upper()): row for row in team_checkins}

    player_checkins = session.exec(
        select(MatchPlayerCheckIn).where(MatchPlayerCheckIn.schedule_version_id == version.id)
    ).all()
    player_checkin_map = {(row.match_id, (row.side or "").upper(), row.player_id): row for row in player_checkins}

    currently_playing: List[DisplayMatchData] = []
    waiting_for_court: List[DisplayMatchData] = []
    upcoming: List[DisplayMatchData] = []
    upcoming_12h: List[DisplayMatchData] = []

    for match in matches:
        runtime = (match.runtime_status or "SCHEDULED").upper()
        schedule_status = (match.status or "").lower()
        if schedule_status in HIDDEN_MATCH_STATUSES or runtime in COMPLETED_STATUSES:
            continue

        assignment = assignment_map.get(match.id)
        if not assignment:
            continue
        slot = slot_map.get(assignment.slot_id)
        if not slot:
            continue

        start_time = coerce_slot_start_time(slot.start_time)
        if start_time is None:
            continue

        scheduled_dt = datetime.combine(slot.day_date, start_time, tzinfo=tz)
        scheduled_time = format_clock(start_time)
        sort_time = start_time.strftime("%H:%M")
        event = event_map.get(match.event_id)
        event_name = event.name if event else "Unknown"
        division_name = derive_division(match.match_code or "", match.match_type or "")
        team_a_names, team_a_has_tbd = _team_first_names(
            team_id=match.team_a_id,
            placeholder=match.placeholder_side_a,
            team_map=team_map,
            players_by_team=players_by_team,
            player_map=player_map,
        )
        team_b_names, team_b_has_tbd = _team_first_names(
            team_id=match.team_b_id,
            placeholder=match.placeholder_side_b,
            team_map=team_map,
            players_by_team=players_by_team,
            player_map=player_map,
        )
        team_a_checked = _side_checked_in(
            match_id=match.id,
            side="A",
            team_id=match.team_a_id,
            team_checkin_map=team_checkin_map,
            player_checkin_map=player_checkin_map,
            players_by_team=players_by_team,
        )
        team_b_checked = _side_checked_in(
            match_id=match.id,
            side="B",
            team_id=match.team_b_id,
            team_checkin_map=team_checkin_map,
            player_checkin_map=player_checkin_map,
            players_by_team=players_by_team,
        )

        is_playing = runtime in PLAYING_STATUSES
        both_checked = team_a_checked and team_b_checked
        if is_playing:
            board_section = "currently_playing"
        elif both_checked:
            board_section = "waiting_for_court"
        else:
            board_section = "upcoming"

        in_next_12_hours = (not is_playing) and (now_local_dt <= scheduled_dt < window_end)

        item = DisplayMatchData(
            match_id=match.id,
            scheduled_at=scheduled_dt.isoformat(),
            scheduled_time=scheduled_time,
            sort_time=sort_time,
            day_date=slot.day_date.isoformat(),
            event_name=event_name,
            division_name=division_name,
            event_label=event_label(event_name, division_name),
            round_label=round_label(match.match_type or "", match.round_number),
            stage=STAGE_MAP.get(match.match_type or "", match.match_type or ""),
            team_a_names=team_a_names,
            team_b_names=team_b_names,
            team_a_checked_in=team_a_checked,
            team_b_checked_in=team_b_checked,
            team_a_has_tbd=team_a_has_tbd,
            team_b_has_tbd=team_b_has_tbd,
            board_section=board_section,
            in_next_12_hours=in_next_12_hours,
            court=court_display(slot) if is_playing else None,
        )

        if board_section == "currently_playing":
            currently_playing.append(item)
        elif board_section == "waiting_for_court":
            waiting_for_court.append(item)
        else:
            upcoming.append(item)

        if in_next_12_hours:
            upcoming_copy = DisplayMatchData(**{**item.__dict__, "court": None})
            upcoming_12h.append(upcoming_copy)

    currently_playing.sort(key=_playing_sort_key)
    waiting_for_court.sort(key=_sort_key)
    upcoming.sort(key=_sort_key)
    upcoming_12h.sort(key=_sort_key)

    groups: List[DisplayTimeGroup] = []
    group_map: Dict[str, DisplayTimeGroup] = {}
    for item in upcoming_12h:
        label = item.scheduled_time or ""
        sort_time = item.sort_time or ""
        key = f"{item.day_date}|{sort_time}|{label}"
        group = group_map.get(key)
        if group is None:
            group = DisplayTimeGroup(scheduled_time=label, sort_time=sort_time, matches=[])
            group_map[key] = group
            groups.append(group)
        group.matches.append(item)

    return DisplayBoardSnapshot(
        tournament_id=tournament.id or tournament_id,
        tournament_name=tournament.name,
        tournament_timezone=tournament.timezone or "UTC",
        now_local=format_clock(dt_time(now_local_dt.hour, now_local_dt.minute)),
        currently_playing=currently_playing,
        waiting_for_court=waiting_for_court,
        upcoming=upcoming,
        upcoming_12h=upcoming_12h,
        upcoming_12h_groups=groups,
    )


def snapshot_to_public_dict(snapshot: DisplayBoardSnapshot) -> Dict[str, Any]:
    """Serialize only the fields the TV boards need. No private/financial data."""

    def match_dict(item: DisplayMatchData, include_court: bool) -> Dict[str, Any]:
        payload = {
            "match_id": item.match_id,
            "scheduled_at": item.scheduled_at,
            "scheduled_time": item.scheduled_time,
            "sort_time": item.sort_time,
            "day_date": item.day_date,
            "event_name": item.event_name,
            "division_name": item.division_name,
            "event_label": item.event_label,
            "round_label": item.round_label,
            "stage": item.stage,
            "team_a_names": item.team_a_names,
            "team_b_names": item.team_b_names,
            "team_a_checked_in": item.team_a_checked_in,
            "team_b_checked_in": item.team_b_checked_in,
            "team_a_has_tbd": item.team_a_has_tbd,
            "team_b_has_tbd": item.team_b_has_tbd,
            "board_section": item.board_section,
            "in_next_12_hours": item.in_next_12_hours,
        }
        if include_court and item.court:
            payload["court"] = item.court
        return payload

    return {
        "tournament_id": snapshot.tournament_id,
        "tournament_name": snapshot.tournament_name,
        "tournament_timezone": snapshot.tournament_timezone,
        "now_local": snapshot.now_local,
        "currently_playing": [match_dict(item, True) for item in snapshot.currently_playing],
        "waiting_for_court": [match_dict(item, False) for item in snapshot.waiting_for_court],
        "upcoming": [match_dict(item, False) for item in snapshot.upcoming],
        "upcoming_12h": [match_dict(item, False) for item in snapshot.upcoming_12h],
        "upcoming_12h_groups": [
            {
                "scheduled_time": group.scheduled_time,
                "sort_time": group.sort_time,
                "matches": [match_dict(item, False) for item in group.matches],
            }
            for group in snapshot.upcoming_12h_groups
        ],
    }


def collect_forbidden_keys(payload: Any, found: Optional[set[str]] = None) -> set[str]:
    forbidden = {
        "email",
        "phone",
        "phone_e164",
        "cellphone",
        "player1_cellphone",
        "player2_cellphone",
        "player1_email",
        "player2_email",
        "p1_cell",
        "p1_email",
        "p2_cell",
        "p2_email",
        "address",
        "payment",
        "invoice",
        "refund",
        "notes",
        "score_json",
        "winner_team_id",
    }
    found = found if found is not None else set()
    if isinstance(payload, dict):
        for key, value in payload.items():
            lowered = str(key).lower()
            if lowered in forbidden or any(
                token in lowered for token in ("email", "phone", "invoice", "payment", "refund")
            ):
                found.add(str(key))
            collect_forbidden_keys(value, found)
    elif isinstance(payload, Sequence) and not isinstance(payload, (str, bytes)):
        for item in payload:
            collect_forbidden_keys(item, found)
    return found
