"""
Team Management API Routes
Provides CRUD operations for teams within events, team injection,
and seeded team import from tab-separated text.
"""

import re
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy import or_
from sqlmodel import Session, select

from app.database import get_session
from app.models.event import Event
from app.models.match import Match
from app.models.schedule_version import ScheduleVersion
from app.models.sms_log import SmsLog
from app.models.temporary_player_lookup import TemporaryPlayerLookup
from app.models.team import Team
from app.models.team_avoid_edge import TeamAvoidEdge
from app.models.team_player import TeamPlayer
from app.models.tournament_sms_settings import TournamentSmsSettings
from app.utils.team_injection import TeamInjectionError, inject_teams_v1

router = APIRouter()


# ============================================================================
# Request/Response Models
# ============================================================================


class TeamCreateRequest(BaseModel):
    name: str
    seed: Optional[int] = None
    rating: Optional[float] = None
    avoid_group: Optional[str] = None
    display_name: Optional[str] = None
    player1_cellphone: Optional[str] = None
    player1_email: Optional[str] = None
    player2_cellphone: Optional[str] = None
    player2_email: Optional[str] = None
    registration_timestamp: Optional[datetime] = None


class TeamUpdateRequest(BaseModel):
    name: Optional[str] = None
    seed: Optional[int] = None
    rating: Optional[float] = None
    avoid_group: Optional[str] = None
    display_name: Optional[str] = None
    player1_cellphone: Optional[str] = None
    player1_email: Optional[str] = None
    player2_cellphone: Optional[str] = None
    player2_email: Optional[str] = None
    is_defaulted: Optional[bool] = None
    notes: Optional[str] = None


class TeamResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    event_id: int
    name: str
    seed: Optional[int] = None
    rating: Optional[float] = None
    avoid_group: Optional[str] = None
    display_name: Optional[str] = None
    player1_cellphone: Optional[str] = None
    player1_email: Optional[str] = None
    player2_cellphone: Optional[str] = None
    player2_email: Optional[str] = None
    p1_cell: Optional[str] = None
    p1_email: Optional[str] = None
    p2_cell: Optional[str] = None
    p2_email: Optional[str] = None
    is_defaulted: bool = False

    @field_validator("is_defaulted", mode="before")
    @classmethod
    def coerce_defaulted(cls, v: object) -> bool:
        return bool(v) if v is not None else False
    registration_timestamp: Optional[datetime] = None
    created_at: datetime
    wf_group_index: Optional[int] = None


# ============================================================================
# Team CRUD Endpoints
# ============================================================================


def _sync_player_contacts_if_enabled(session: Session, tournament_id: int) -> None:
    """Keep Player/TeamPlayer contacts in sync after team edits."""
    settings = session.exec(
        select(TournamentSmsSettings).where(
            TournamentSmsSettings.tournament_id == tournament_id
        )
    ).first()
    if not settings or not bool(getattr(settings, "player_contacts_only", False)):
        return
    from app.routes.sms import _sync_players_and_team_links_from_team_slots

    stats = _sync_players_and_team_links_from_team_slots(
        session=session,
        tournament_id=tournament_id,
    )
    if any(stats.values()):
        session.commit()


@router.get("/events/{event_id}/teams", response_model=List[TeamResponse])
def get_teams(event_id: int, session: Session = Depends(get_session)):
    """
    Get all teams for an event.

    Returns teams in deterministic order:
    1. seed ascending (nulls last)
    2. rating descending (nulls last)
    3. registration_timestamp ascending (nulls last)
    4. id ascending
    """
    # Verify event exists
    event = session.get(Event, event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    # Query teams with deterministic ordering
    query = select(Team).where(Team.event_id == event_id)
    teams = session.exec(query).all()

    # Sort deterministically in Python (SQLite sorting nulls is tricky)
    def sort_key(team: Team):
        return (
            # seed: nulls last, ascending
            (team.seed is None, team.seed if team.seed is not None else 0),
            # rating: nulls last, descending (negate for desc)
            (team.rating is None, -(team.rating if team.rating is not None else 0)),
            # registration_timestamp: nulls last, ascending
            (
                team.registration_timestamp is None,
                team.registration_timestamp if team.registration_timestamp is not None else datetime.max,
            ),
            # id: ascending
            team.id,
        )

    sorted_teams = sorted(teams, key=sort_key)

    return sorted_teams


@router.post("/events/{event_id}/teams", response_model=TeamResponse, status_code=201)
def create_team(event_id: int, request: TeamCreateRequest, session: Session = Depends(get_session)):
    """
    Create a new team for an event.

    Constraints:
    - (event_id, seed) must be unique if seed is not null
    - (event_id, name) must be unique
    """
    # Verify event exists
    event = session.get(Event, event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    team = Team(
        event_id=event_id,
        name=request.name,
        seed=request.seed,
        rating=request.rating,
        avoid_group=request.avoid_group,
        display_name=request.display_name,
        player1_cellphone=request.player1_cellphone,
        player1_email=request.player1_email,
        player2_cellphone=request.player2_cellphone,
        player2_email=request.player2_email,
        registration_timestamp=request.registration_timestamp,
    )

    try:
        session.add(team)
        session.commit()
        session.refresh(team)
        _sync_player_contacts_if_enabled(session, event.tournament_id)
        return team
    except Exception as e:
        session.rollback()
        # Check for constraint violations
        if "UNIQUE constraint failed" in str(e) or "IntegrityError" in str(type(e).__name__):
            if "seed" in str(e):
                raise HTTPException(
                    status_code=409, detail=f"Team with seed {request.seed} already exists for this event"
                )
            elif "name" in str(e):
                raise HTTPException(
                    status_code=409, detail=f"Team with name '{request.name}' already exists for this event"
                )
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/events/{event_id}/teams/{team_id}", response_model=TeamResponse)
def update_team(event_id: int, team_id: int, request: TeamUpdateRequest, session: Session = Depends(get_session)):
    """
    Update a team's name, seed, or rating.
    """
    # Get team
    team = session.get(Team, team_id)
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")

    # Verify team belongs to event
    if team.event_id != event_id:
        raise HTTPException(status_code=400, detail="Team does not belong to this event")
    event = session.get(Event, event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    if request.name is not None:
        team.name = request.name
    if request.seed is not None:
        team.seed = request.seed
    if request.rating is not None:
        team.rating = request.rating
    if request.avoid_group is not None:
        team.avoid_group = request.avoid_group
    if request.display_name is not None:
        team.display_name = request.display_name
    if request.player1_cellphone is not None:
        team.player1_cellphone = request.player1_cellphone
    if request.player1_email is not None:
        team.player1_email = request.player1_email
    if request.player2_cellphone is not None:
        team.player2_cellphone = request.player2_cellphone
    if request.player2_email is not None:
        team.player2_email = request.player2_email
    if request.is_defaulted is not None:
        team.is_defaulted = request.is_defaulted
    if request.notes is not None:
        team.notes = request.notes

    try:
        session.add(team)
        session.commit()
        session.refresh(team)
        _sync_player_contacts_if_enabled(session, event.tournament_id)
        return team
    except Exception as e:
        session.rollback()
        if "UNIQUE constraint failed" in str(e) or "IntegrityError" in str(type(e).__name__):
            if "seed" in str(e):
                raise HTTPException(
                    status_code=409, detail=f"Team with seed {request.seed} already exists for this event"
                )
            elif "name" in str(e):
                raise HTTPException(
                    status_code=409, detail=f"Team with name '{request.name}' already exists for this event"
                )
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/events/{event_id}/teams/{team_id}", status_code=204)
def delete_team(event_id: int, team_id: int, session: Session = Depends(get_session)):
    """
    Delete a team.
    """
    # Get team
    team = session.get(Team, team_id)
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")

    # Verify team belongs to event
    if team.event_id != event_id:
        raise HTTPException(status_code=400, detail="Team does not belong to this event")
    event = session.get(Event, event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    # Delete team
    session.delete(team)
    session.commit()
    _sync_player_contacts_if_enabled(session, event.tournament_id)

    return None


# ============================================================================
# Seeded Team Import
# ============================================================================


class SeededImportRequest(BaseModel):
    format: str = "sectioned_text"
    text: str


class RejectedRow(BaseModel):
    line: int
    text: str
    reason: str


class SeededImportResponse(BaseModel):
    imported_count: int
    updated_count: int
    total_seeds: int
    rejected_rows: List[RejectedRow]
    warnings: List[str]


class CombinedTeamImportRequest(BaseModel):
    text: str


class CombinedTeamImportResponse(BaseModel):
    imported_count: int
    updated_count: int
    total_rows: int
    events_touched: int
    towel_rows_imported: int
    towel_rows_matched: int
    rejected_rows: List[RejectedRow]
    warnings: List[str]


def _parse_seeded_line(raw: str, line_num: int) -> dict:
    """
    Parse a single line of tab-separated seeded team data.

    Handles two formats:
    1. New 10-field WAR format: seed, avoid_group, display_name, full_name,
       event_name, rating, p1_cell, p1_email, p2_cell, p2_email
    2. Old 4-field format: seed, avoid_group, rating, full_name

    Also handles space-separated fallback.

    Returns dict with: seed, avoid_group, rating, full_name, display_name,
    player1_cellphone, player1_email, player2_cellphone, player2_email,
    p1_cell, p1_email, p2_cell, p2_email
    Raises ValueError on parse failure.
    """
    # Try tab-separated first
    parts = raw.split("\t")

    # 10+ fields: use the enhanced parser from team_import
    if len(parts) >= 10:
        from app.routes.team_import import parse_team_rows
        rows = parse_team_rows(raw)
        if not rows:
            raise ValueError("Could not parse 10-field line")
        r = rows[0]
        if r.seed is None:
            raise ValueError(f"Cannot parse seed from line {line_num}")
        # full_name: use full_name if available, otherwise display_name
        full_name = r.full_name or r.display_name
        display_name = r.display_name or _make_display_name(full_name)
        return {
            "seed": r.seed,
            "avoid_group": r.avoid_group,
            "rating": r.rating,
            "full_name": full_name,
            "display_name": display_name,
            "player1_cellphone": r.p1_cell,
            "player1_email": r.p1_email,
            "player2_cellphone": r.p2_cell,
            "player2_email": r.p2_email,
            "p1_cell": r.p1_cell,
            "p1_email": r.p1_email,
            "p2_cell": r.p2_cell,
            "p2_email": r.p2_email,
        }

    if len(parts) >= 3:
        return _parse_tab_parts(parts, line_num)

    # Fallback: space-separated parsing
    return _parse_space_parts(raw.strip(), line_num)


def _normalize_import_header(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (value or "").strip().lower())


def _combined_header_aliases() -> dict[str, set[str]]:
    return {
        "seed": {"seed"},
        "avoid_group": {"whoknowswho", "whoknowswho?", "avoidgroup", "group"},
        "display_name": {"firstnamesteam", "displaynameteam", "displayname", "firstnames"},
        "full_name": {"fullnamecitystateteam", "fullnameteam", "fullname", "teamname"},
        "draw_name": {"draw", "event", "eventname", "division"},
        "rating": {"level", "rating"},
        "p1_towel_color": {"towelcolorfirstplayer", "firstplayertowelcolor", "p1towelcolor"},
        "p1_cell": {"cellphonefirstplayer", "phonefirstplayer", "p1cell", "p1phone"},
        "p1_email": {"emailfirstplayer", "p1email"},
        "p2_towel_color": {"towelcolorsecondplayer", "secondplayertowelcolor", "p2towelcolor"},
        "p2_cell": {"cellphonesecondplayer", "phonesecondplayer", "p2cell", "p2phone"},
        "p2_email": {"emailsecondplayer", "p2email"},
    }


def _parse_combined_import_rows(raw_text: str) -> tuple[List[dict], List[RejectedRow]]:
    lines = [line.rstrip("\r") for line in (raw_text or "").splitlines() if line.strip()]
    if not lines:
        raise HTTPException(status_code=400, detail="Paste the Excel rows including a header row")

    header_cells = [_normalize_import_header(cell) for cell in lines[0].split("\t")]
    alias_map = _combined_header_aliases()
    index_map: dict[str, int] = {}
    for idx, header in enumerate(header_cells):
        for canonical, aliases in alias_map.items():
            if header in aliases and canonical not in index_map:
                index_map[canonical] = idx

    required = {"seed", "display_name", "full_name", "draw_name"}
    if any(name not in index_map for name in required):
        raise HTTPException(
            status_code=400,
            detail=(
                "Header row must include Seed, First names team, Full name, city, state team, and Draw columns"
            ),
        )

    parsed: List[dict] = []
    rejected: List[RejectedRow] = []
    for line_num, raw_line in enumerate(lines[1:], start=2):
        fields = raw_line.split("\t")

        def _field(name: str) -> Optional[str]:
            idx = index_map.get(name)
            if idx is None or idx >= len(fields):
                return None
            value = fields[idx].strip()
            return value or None

        seed_raw = _field("seed")
        seed = _try_int(seed_raw or "")
        if seed is None:
            rejected.append(RejectedRow(line=line_num, text=raw_line[:120], reason="Seed must be a number"))
            continue

        draw_name = _field("draw_name")
        if not draw_name:
            rejected.append(RejectedRow(line=line_num, text=raw_line[:120], reason="Draw column is required"))
            continue

        full_name = _field("full_name")
        display_name = _field("display_name")
        if not full_name and not display_name:
            rejected.append(RejectedRow(line=line_num, text=raw_line[:120], reason="Team name is required"))
            continue

        full_name = full_name or display_name or ""
        display_name = display_name or _make_display_name(full_name)
        parsed.append(
            {
                "line_number": line_num,
                "seed": seed,
                "avoid_group": _field("avoid_group"),
                "rating": _try_float(_field("rating") or ""),
                "full_name": full_name,
                "display_name": display_name,
                "draw_name": draw_name,
                "p1_towel_color": _field("p1_towel_color"),
                "p1_cell": _field("p1_cell"),
                "p1_email": _field("p1_email"),
                "p2_towel_color": _field("p2_towel_color"),
                "p2_cell": _field("p2_cell"),
                "p2_email": _field("p2_email"),
                "player1_cellphone": _field("p1_cell"),
                "player1_email": _field("p1_email"),
                "player2_cellphone": _field("p2_cell"),
                "player2_email": _field("p2_email"),
            }
        )
    return parsed, rejected


def _normalize_event_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (value or "").lower())


def _resolve_event_for_draw(draw_name: str, events: List[Event]) -> Optional[Event]:
    draw_key = _normalize_event_key(draw_name)
    if not draw_key:
        return None

    exact = [event for event in events if _normalize_event_key(event.name) == draw_key]
    if len(exact) == 1:
        return exact[0]

    contains = [
        event
        for event in events
        if draw_key in _normalize_event_key(event.name) or _normalize_event_key(event.name) in draw_key
    ]
    if len(contains) == 1:
        return contains[0]

    womens = [event for event in events if (event.category or "").lower() == "womens"]
    mixed = [event for event in events if (event.category or "").lower() == "mixed"]
    if any(token in draw_key for token in ("women", "womens", "wom")) and len(womens) == 1:
        return womens[0]
    if "mixed" in draw_key and len(mixed) == 1:
        return mixed[0]
    return None


def _split_team_members(value: Optional[str]) -> List[str]:
    raw = (value or "").strip()
    if not raw:
        return []
    if "/" in raw:
        parts = raw.split("/")
    elif "&" in raw:
        parts = raw.split("&")
    else:
        parts = [raw]
    return [part.strip() for part in parts if part.strip()]


def _strip_player_location(value: str) -> str:
    return value.split(",", 1)[0].strip()


def _build_lookup_rows_from_combined_rows(rows: List[dict]) -> List[dict]:
    lookup_rows: List[dict] = []
    for row in rows:
        full_names = _split_team_members(row.get("full_name"))
        display_names = _split_team_members(row.get("display_name"))

        def _player_name(slot: int) -> Optional[str]:
            idx = slot - 1
            if idx < len(full_names):
                return _strip_player_location(full_names[idx])
            if idx < len(display_names):
                return display_names[idx].strip()
            return None

        for slot in (1, 2):
            towel_color = (row.get(f"p{slot}_towel_color") or "").strip()
            if not towel_color:
                continue
            player_name = _player_name(slot)
            if not player_name:
                continue
            lookup_rows.append(
                {
                    "source_name": player_name,
                    "source_phone": row.get(f"p{slot}_cell"),
                    "source_email": row.get(f"p{slot}_email"),
                    "towel_color": towel_color,
                    "report_url": None,
                }
            )
    return lookup_rows


def _parse_tab_parts(parts: list, line_num: int) -> dict:
    """
    Parse tab-separated columns. Handles multiple layouts:

    Layout A (user's spreadsheet):
      seed | [avoid_group] | rating | full_name | [display_name]
      "30"  "b"             "7.5"   "Ashley Wise, Charlotte, NC / Christi Farr..."  "Ashley / Christi"

    Layout B (compact):
      seed+group | rating | full_name
      "30b"       "7.5"   "Ashley Wise / Christi Farr"

    Walks non-empty columns left-to-right, detecting each field by type.
    """
    cols = [p.strip() for p in parts]
    non_empty = [(i, c) for i, c in enumerate(cols) if c]

    if len(non_empty) < 2:
        raise ValueError("Too few non-empty columns")

    idx = 0

    # First non-empty: seed (possibly with embedded avoid_group like "30b")
    seed, avoid_group = _extract_seed_and_group(non_empty[idx][1])
    if seed is None:
        raise ValueError(f"Cannot parse seed from '{non_empty[idx][1]}'")
    idx += 1

    # Next non-empty: avoid_group (single letter) or rating (number) or name
    if idx < len(non_empty) and re.match(r"^[a-zA-Z]$", non_empty[idx][1]):
        avoid_group = non_empty[idx][1].lower()
        idx += 1

    # Next non-empty: rating (float)
    rating = None
    if idx < len(non_empty):
        rating = _try_float(non_empty[idx][1])
        if rating is not None:
            idx += 1

    # Remaining non-empty columns: full_name, optionally display_name, phones, emails
    remaining = [non_empty[i][1] for i in range(idx, len(non_empty))]

    if not remaining:
        raise ValueError("No team name found")

    # Extract phones and emails from the tail of remaining columns
    phones: list[str] = []
    emails: list[str] = []
    name_cols = list(remaining)

    # Scan from the end for emails (contain @) and phones (mostly digits)
    tail_consumed = 0
    for candidate in reversed(remaining):
        if "@" in candidate and len(emails) < 2:
            emails.insert(0, candidate.strip())
            tail_consumed += 1
        elif re.match(r"^[\d\s\-\(\)\+\.]{7,}$", candidate) and len(phones) < 2:
            phones.insert(0, re.sub(r"[^\d]", "", candidate))
            tail_consumed += 1
        else:
            break
    if tail_consumed > 0:
        name_cols = remaining[: len(remaining) - tail_consumed]

    if not name_cols:
        raise ValueError("No team name found")

    full_name = name_cols[0]
    display_name = None

    # If there's a second remaining column that looks like a short display name
    # (contains "/" or "&", each part is 1-2 words), use it directly
    if len(name_cols) >= 2:
        candidate = name_cols[-1]
        if "/" in candidate or "&" in candidate:
            sep = "/" if "/" in candidate else "&"
            name_parts = [p.strip() for p in candidate.split(sep)]
            if all(len(p.split()) <= 3 for p in name_parts if p):
                display_name = candidate.strip()

    if not full_name:
        raise ValueError("No team name found")

    if display_name is None:
        display_name = _make_display_name(full_name)

    return {
        "seed": seed,
        "avoid_group": avoid_group,
        "rating": rating,
        "full_name": full_name,
        "display_name": display_name,
        "player1_cellphone": phones[0] if len(phones) >= 1 else None,
        "player2_cellphone": phones[1] if len(phones) >= 2 else None,
        "player1_email": emails[0] if len(emails) >= 1 else None,
        "player2_email": emails[1] if len(emails) >= 2 else None,
    }


def _parse_space_parts(line: str, line_num: int) -> dict:
    """
    Parse space-separated line like:
      "1 a 9 Heather Robinson / Shea Butler"
      "16 8 Mary Garvin / Lana Heinz"
    """
    tokens = line.split()
    if len(tokens) < 3:
        raise ValueError("Too few tokens")

    idx = 0
    # Token 0: seed (integer)
    seed = _try_int(tokens[idx])
    if seed is None:
        raise ValueError(f"Cannot parse seed from '{tokens[idx]}'")
    idx += 1

    # Token 1: optional avoid_group (single letter a-z)
    avoid_group = None
    if idx < len(tokens) and re.match(r"^[a-zA-Z]$", tokens[idx]):
        avoid_group = tokens[idx].lower()
        idx += 1

    # Next token: rating (float)
    rating = None
    if idx < len(tokens):
        rating = _try_float(tokens[idx])
        if rating is not None:
            idx += 1

    # Everything remaining is the team name
    full_name = " ".join(tokens[idx:]).strip()
    if not full_name:
        raise ValueError("No team name found")

    display_name = _make_display_name(full_name)

    return {
        "seed": seed,
        "avoid_group": avoid_group,
        "rating": rating,
        "full_name": full_name,
        "display_name": display_name,
        "player1_cellphone": None,
        "player1_email": None,
        "player2_cellphone": None,
        "player2_email": None,
    }


def _extract_seed_and_group(text: str) -> tuple:
    """Extract seed number and optional avoid_group letter from a token like '1a', '16', '3 b'."""
    text = text.strip()
    m = re.match(r"^(\d+)\s*([a-zA-Z])?$", text)
    if m:
        return int(m.group(1)), (m.group(2).lower() if m.group(2) else None)
    # Try just the number
    m = re.match(r"^(\d+)$", text)
    if m:
        return int(m.group(1)), None
    return None, None


def _try_int(s: str) -> Optional[int]:
    try:
        return int(s)
    except (ValueError, TypeError):
        return None


def _try_float(s: str) -> Optional[float]:
    try:
        return float(s)
    except (ValueError, TypeError):
        return None


def _make_display_name(full_name: str) -> str:
    """
    Derive a short display name from a full team name.
    "Heather Robinson / Shea Butler" -> "Heather / Shea"
    "Jane Smith-Jones / Bob Lee" -> "Jane / Bob"
    "Dee Dee Smith / Mike Jones" -> "Dee Dee / Mike"
    "Smith, Jane & Doe, Bob" -> "Smith / Doe"
    """
    # Normalize whitespace (collapse double-spaces, strip)
    name = re.sub(r"\s{2,}", " ", full_name).strip()
    if not name:
        return full_name

    # Detect separator: "/" or "&"
    if "/" in name:
        sep = "/"
    elif "&" in name:
        sep = "&"
    else:
        # Single player or no separator — return first name
        return name.split()[0] if name.split() else name

    players = [p.strip() for p in name.split(sep)]
    firsts = []
    for p in players:
        if not p:
            continue
        # Handle "Last, First" format
        if "," in p:
            parts = [x.strip() for x in p.split(",", 1)]
            firsts.append(parts[0])
        else:
            firsts.append(p.split()[0])
    return " / ".join(firsts) if firsts else name


def _upsert_seeded_rows_for_event(
    session: Session,
    event: Event,
    parsed: List[dict],
) -> tuple[int, int, List[str], List[Team]]:
    warnings: List[str] = []

    existing_teams = session.exec(
        select(Team).where(Team.event_id == event.id)
    ).all()
    incoming_seeds = {row["seed"] for row in parsed}

    stale_team_ids: List[int] = []
    for team in existing_teams:
        if team.seed in incoming_seeds:
            continue
        stale_team_ids.append(team.id)

    if stale_team_ids:
        stale_set = set(stale_team_ids)
        blocked_stale_ids: set[int] = set()
        stale_matches = session.exec(
            select(Match, ScheduleVersion.status)
            .join(ScheduleVersion, ScheduleVersion.id == Match.schedule_version_id)
            .where(
                Match.event_id == event.id,
                or_(
                    Match.team_a_id.in_(stale_team_ids),  # type: ignore[arg-type]
                    Match.team_b_id.in_(stale_team_ids),  # type: ignore[arg-type]
                    Match.winner_team_id.in_(stale_team_ids),  # type: ignore[arg-type]
                ),
            )
        ).all()
        for match, version_status in stale_matches:
            referenced_ids = {
                tid for tid in (match.team_a_id, match.team_b_id, match.winner_team_id)
                if tid in stale_set
            }
            if not referenced_ids:
                continue
            is_final_match = (match.runtime_status or "").upper() == "FINAL"
            if (version_status or "").lower() == "final" or is_final_match:
                blocked_stale_ids.update(referenced_ids)
                continue

            if match.team_a_id in referenced_ids:
                match.team_a_id = None
            if match.team_b_id in referenced_ids:
                match.team_b_id = None
            if match.winner_team_id in referenced_ids:
                match.winner_team_id = None
            session.add(match)

        removable_stale_ids = [tid for tid in stale_team_ids if tid not in blocked_stale_ids]
        removable_set = set(removable_stale_ids)

        if blocked_stale_ids:
            blocked_teams = session.exec(
                select(Team).where(Team.id.in_(list(blocked_stale_ids)))  # type: ignore[arg-type]
            ).all()
            for team in blocked_teams:
                warnings.append(
                    f"Skipped removing stale team seed={team.seed or '—'} "
                    f"('{team.display_name or team.name}') because it appears in finalized matches."
                )

        if removable_stale_ids:
            stale_sms_logs = session.exec(
                select(SmsLog).where(SmsLog.team_id.in_(removable_stale_ids))  # type: ignore[arg-type]
            ).all()
            for row in stale_sms_logs:
                row.team_id = None
                session.add(row)

            stale_edges = session.exec(
                select(TeamAvoidEdge).where(
                    TeamAvoidEdge.event_id == event.id,
                    or_(
                        TeamAvoidEdge.team_id_a.in_(removable_stale_ids),  # type: ignore[arg-type]
                        TeamAvoidEdge.team_id_b.in_(removable_stale_ids),  # type: ignore[arg-type]
                    ),
                )
            ).all()
            stale_player_links = session.exec(
                select(TeamPlayer).where(TeamPlayer.team_id.in_(removable_stale_ids))  # type: ignore[arg-type]
            ).all()
            for edge in stale_edges:
                session.delete(edge)
            for link in stale_player_links:
                session.delete(link)
            for team in existing_teams:
                if team.id in removable_set:
                    session.delete(team)
            session.flush()
            warnings.append(
                f"Removed {len(removable_stale_ids)} stale team(s) not present in imported seeds."
            )

    existing_teams = session.exec(
        select(Team).where(Team.event_id == event.id)
    ).all()
    existing_by_seed = {t.seed: t for t in existing_teams if t.seed is not None}

    imported_count = 0
    updated_count = 0
    group_map: dict[str, list[int]] = {}
    touched_teams: List[Team] = []

    for row in parsed:
        seed = row["seed"]
        existing = existing_by_seed.get(seed)

        if existing:
            if existing.name != row["full_name"]:
                warnings.append(
                    f"W_SEED_REASSIGNED: seed {seed} changed from "
                    f"'{existing.name}' to '{row['full_name']}'"
                )
            existing.name = row["full_name"]
            existing.rating = row["rating"]
            existing.avoid_group = row["avoid_group"]
            existing.display_name = row["display_name"]
            existing.notes = None
            existing.is_defaulted = False
            if row.get("player1_cellphone"):
                existing.player1_cellphone = row["player1_cellphone"]
            if row.get("player1_email"):
                existing.player1_email = row["player1_email"]
            if row.get("player2_cellphone"):
                existing.player2_cellphone = row["player2_cellphone"]
            if row.get("player2_email"):
                existing.player2_email = row["player2_email"]
            if row.get("p1_cell"):
                existing.p1_cell = row["p1_cell"]
            if row.get("p1_email"):
                existing.p1_email = row["p1_email"]
            if row.get("p2_cell"):
                existing.p2_cell = row["p2_cell"]
            if row.get("p2_email"):
                existing.p2_email = row["p2_email"]
            session.add(existing)
            session.flush()
            updated_count += 1
            team = existing
        else:
            team = Team(
                event_id=event.id,
                name=row["full_name"],
                seed=seed,
                rating=row["rating"],
                avoid_group=row["avoid_group"],
                display_name=row["display_name"],
                player1_cellphone=row.get("player1_cellphone"),
                player1_email=row.get("player1_email"),
                player2_cellphone=row.get("player2_cellphone"),
                player2_email=row.get("player2_email"),
                p1_cell=row.get("p1_cell"),
                p1_email=row.get("p1_email"),
                p2_cell=row.get("p2_cell"),
                p2_email=row.get("p2_email"),
            )
            session.add(team)
            session.flush()
            imported_count += 1

        touched_teams.append(team)
        team_id = team.id

        avoid_group = row.get("avoid_group")
        if team_id and avoid_group:
            groups = [g.strip().upper() for g in avoid_group.split(",")]
            for group_code in groups:
                if not group_code:
                    continue
                group_map.setdefault(group_code, []).append(team_id)

    avoid_edges_created = 0
    try:
        for group_code, team_ids in group_map.items():
            if len(team_ids) < 2:
                continue
            for i in range(len(team_ids)):
                for j in range(i + 1, len(team_ids)):
                    a_id = min(team_ids[i], team_ids[j])
                    b_id = max(team_ids[i], team_ids[j])
                    existing_edge = session.exec(
                        select(TeamAvoidEdge).where(
                            TeamAvoidEdge.event_id == event.id,
                            TeamAvoidEdge.team_id_a == a_id,
                            TeamAvoidEdge.team_id_b == b_id,
                        )
                    ).first()
                    if not existing_edge:
                        edge = TeamAvoidEdge(
                            event_id=event.id,
                            team_id_a=a_id,
                            team_id_b=b_id,
                            reason=f"group:{group_code}",
                        )
                        session.add(edge)
                        avoid_edges_created += 1
    except Exception as e:
        warnings.append(f"Error creating avoid edges: {e}")

    if avoid_edges_created > 0:
        warnings.append(f"Created {avoid_edges_created} avoid edge(s) from group assignments")

    total_teams = len(session.exec(select(Team).where(Team.event_id == event.id)).all())
    if event.team_count != total_teams:
        warnings.append(
            f"Event team_count was {event.team_count}, now {total_teams} teams in DB."
        )
        event.team_count = total_teams
        session.add(event)

    return imported_count, updated_count, warnings, touched_teams


@router.post(
    "/tournaments/{tournament_id}/events/{event_id}/teams/import-seeded",
    response_model=SeededImportResponse,
)
def import_seeded_teams(
    tournament_id: int,
    event_id: int,
    request: SeededImportRequest,
    session: Session = Depends(get_session),
):
    """
    Import seeded teams from tab-separated or space-separated text.

    Upserts on (event_id, seed): if a team with that seed already exists,
    it is updated. Otherwise a new team is created.

    Validates:
    - Seeds must be positive integers
    - No duplicate seeds in input
    - Seeds should be contiguous 1..N (warns if gaps)
    """
    event = session.get(Event, event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    if event.tournament_id != tournament_id:
        raise HTTPException(status_code=400, detail="Event does not belong to this tournament")

    lines = request.text.strip().split("\n")
    parsed = []
    rejected: List[RejectedRow] = []
    seen_seeds = set()

    for i, raw_line in enumerate(lines, start=1):
        raw_line = raw_line.strip()
        if not raw_line:
            continue

        # Skip header rows — first token is not a number
        first_token = raw_line.split("\t")[0].split()[0] if raw_line.split() else ""
        if first_token and not first_token[0].isdigit():
            continue

        try:
            row = _parse_seeded_line(raw_line, i)
        except ValueError as e:
            rejected.append(RejectedRow(line=i, text=raw_line[:120], reason=str(e)))
            continue

        seed = row["seed"]
        if seed in seen_seeds:
            rejected.append(RejectedRow(
                line=i, text=raw_line[:120],
                reason=f"Duplicate seed {seed} (already seen)",
            ))
            continue
        if seed < 1:
            rejected.append(RejectedRow(
                line=i, text=raw_line[:120],
                reason=f"Seed must be >= 1, got {seed}",
            ))
            continue

        seen_seeds.add(seed)
        parsed.append(row)

    # Validate contiguity
    warnings: List[str] = []
    if parsed:
        max_seed = max(r["seed"] for r in parsed)
        expected = set(range(1, max_seed + 1))
        missing = expected - seen_seeds
        if missing:
            warnings.append(
                f"Seeds not contiguous: missing {sorted(missing)}. "
                f"Got {len(parsed)} teams for seeds 1..{max_seed}."
            )

    imported_count, updated_count, helper_warnings, _ = _upsert_seeded_rows_for_event(session, event, parsed)
    warnings.extend(helper_warnings)
    session.commit()
    _sync_player_contacts_if_enabled(session, tournament_id)

    return SeededImportResponse(
        imported_count=imported_count,
        updated_count=updated_count,
        total_seeds=len(parsed),
        rejected_rows=rejected,
        warnings=warnings,
    )


@router.post(
    "/tournaments/{tournament_id}/teams/import-combined",
    response_model=CombinedTeamImportResponse,
)
def import_combined_teams(
    tournament_id: int,
    request: CombinedTeamImportRequest,
    session: Session = Depends(get_session),
):
    events = session.exec(
        select(Event).where(Event.tournament_id == tournament_id)
    ).all()
    if not events:
        raise HTTPException(status_code=404, detail="No events found for this tournament")

    parsed_rows, rejected_rows = _parse_combined_import_rows(request.text)
    grouped_rows: dict[int, List[dict]] = {}
    accepted_rows: List[dict] = []
    warnings: List[str] = []

    for row in parsed_rows:
        event = _resolve_event_for_draw(row.get("draw_name") or "", events)
        if not event:
            rejected_rows.append(
                RejectedRow(
                    line=row["line_number"],
                    text=(row.get("full_name") or row.get("display_name") or "")[:120],
                    reason=f"Could not match Draw '{row.get('draw_name') or ''}' to a tournament event",
                )
            )
            continue
        grouped_rows.setdefault(event.id, []).append(row)
        accepted_rows.append(row)

    imported_count = 0
    updated_count = 0
    events_touched = 0
    touched_teams: List[Team] = []
    accepted_lookup_rows: List[dict] = []

    for event in events:
        rows = grouped_rows.get(event.id) or []
        if not rows:
            continue

        seen_seeds: set[int] = set()
        valid_rows: List[dict] = []
        for row in rows:
            seed = row["seed"]
            if seed in seen_seeds:
                rejected_rows.append(
                    RejectedRow(
                        line=row["line_number"],
                        text=(row.get("full_name") or row.get("display_name") or "")[:120],
                        reason=f"Duplicate seed {seed} for event {event.name}",
                    )
                )
                continue
            if seed < 1:
                rejected_rows.append(
                    RejectedRow(
                        line=row["line_number"],
                        text=(row.get("full_name") or row.get("display_name") or "")[:120],
                        reason=f"Seed must be >= 1, got {seed}",
                    )
                )
                continue
            seen_seeds.add(seed)
            valid_rows.append(row)

        if not valid_rows:
            continue

        max_seed = max(row["seed"] for row in valid_rows)
        missing = set(range(1, max_seed + 1)) - seen_seeds
        if missing:
            warnings.append(
                f"{event.name} seeds not contiguous: missing {sorted(missing)}. "
                f"Got {len(valid_rows)} teams for seeds 1..{max_seed}."
            )

        imported, updated, event_warnings, event_teams = _upsert_seeded_rows_for_event(session, event, valid_rows)
        imported_count += imported
        updated_count += updated
        warnings.extend(event_warnings)
        touched_teams.extend(event_teams)
        accepted_lookup_rows.extend(valid_rows)
        events_touched += 1

    settings = session.exec(
        select(TournamentSmsSettings).where(TournamentSmsSettings.tournament_id == tournament_id)
    ).first()
    if settings and bool(getattr(settings, "player_contacts_only", False)):
        from app.routes.sms import _sync_players_and_team_links_from_team_slots

        _sync_players_and_team_links_from_team_slots(
            session=session,
            tournament_id=tournament_id,
            teams=touched_teams,
        )

    lookup_rows = _build_lookup_rows_from_combined_rows(accepted_lookup_rows)
    matched_count = 0
    if lookup_rows:
        from app.routes.desk import _resolve_lookup_player_ids

        resolved_lookup_rows = _resolve_lookup_player_ids(session, tournament_id, lookup_rows)
    else:
        resolved_lookup_rows = []

    existing_lookup_rows = session.exec(
        select(TemporaryPlayerLookup).where(TemporaryPlayerLookup.tournament_id == tournament_id)
    ).all()
    for row in existing_lookup_rows:
        session.delete(row)
    session.flush()

    for row in resolved_lookup_rows:
        if bool(row.get("matched_by_name")):
            matched_count += 1
        session.add(
            TemporaryPlayerLookup(
                tournament_id=tournament_id,
                player_id=row.get("player_id"),
                source_name=row["source_name"] or "",
                normalized_name=row["normalized_name"] or "",
                source_phone=row.get("source_phone"),
                normalized_phone=row.get("normalized_phone"),
                source_email=row.get("source_email"),
                normalized_email=row.get("normalized_email"),
                towel_color=row["towel_color"] or "",
                report_url=row.get("report_url"),
            )
        )

    session.commit()

    return CombinedTeamImportResponse(
        imported_count=imported_count,
        updated_count=updated_count,
        total_rows=len(parsed_rows),
        events_touched=events_touched,
        towel_rows_imported=len(resolved_lookup_rows),
        towel_rows_matched=matched_count,
        rejected_rows=rejected_rows,
        warnings=warnings,
    )


# ============================================================================
# Team Injection Endpoint
# ============================================================================


class TeamInjectionResponse(BaseModel):
    teams_count: int
    matches_updated_count: int
    injection_type: str  # "bracket" | "round_robin"
    warnings: List[str]


@router.post("/events/{event_id}/schedule/versions/{version_id}/inject-teams", response_model=TeamInjectionResponse)
def inject_teams(
    event_id: int,
    version_id: int,
    clear_existing: bool = Query(True, description="Clear existing team assignments before injection"),
    session: Session = Depends(get_session),
):
    """
    Inject teams into matches for an event's schedule version.

    Rules:
    - If team_count > 8: Reject (400)
    - If team_count == 8: Bracket injection (assigns QFs only)
    - If team_count < 8: Round robin injection (assigns all matches)

    Team assignment is deterministic based on:
    1. seed (ascending, nulls last)
    2. rating (descending, nulls last)
    3. registration_timestamp (ascending, nulls last)
    4. id (ascending)

    Args:
        event_id: Event ID
        version_id: Schedule version ID
        clear_existing: If true, clears all team assignments before injection

    Returns:
        Summary of injection results
    """
    try:
        result = inject_teams_v1(
            session=session, event_id=event_id, schedule_version_id=version_id, clear_existing=clear_existing
        )
        return TeamInjectionResponse(**result)
    except TeamInjectionError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Injection failed: {str(e)}")
