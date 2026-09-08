"""Read-only public-draw descriptors for the staff Draw QR Board.

Availability matches the existing public draws index: a draw is included only
when the tournament has a published schedule version and that version contains
the matching generated matches. This module does not write tournament data and
does not invent new public routes.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Iterable, List, Optional, Sequence
from urllib.parse import urlparse

from sqlmodel import Session, select

from app.models.event import Event
from app.models.match import Match
from app.models.schedule_version import ScheduleVersion
from app.models.tournament import Tournament

DRAW_TYPE_WATERFALL = "waterfall"
DRAW_TYPE_ROUND_ROBIN = "round_robin"
DRAW_TYPE_BRACKET = "bracket"

DRAW_TYPE_LABELS = {
    DRAW_TYPE_WATERFALL: "Waterfall",
    DRAW_TYPE_ROUND_ROBIN: "Round Robin",
    DRAW_TYPE_BRACKET: "Bracket",
}

BRACKET_DIV_ORDER = ("BWW", "BWL", "BLW", "BLL")
BRACKET_DIV_LABELS = {
    "BWW": "Division I",
    "BWL": "Division II",
    "BLW": "Division III",
    "BLL": "Division IV",
}
POOLS_ONLY_TEMPLATES = ("WF_14_TOP2_BYE", "WF_TO_POOLS_DYNAMIC")

PUBLIC_ORIGIN_ENV_KEYS = (
    "PUBLIC_APP_URL",
    "FRONTEND_URL",
    "PUBLIC_BASE_URL",
    "APP_BASE_URL",
)


@dataclass(frozen=True)
class DrawQrBoardItem:
    event_id: int
    event_name: str
    label: str
    draw_type: str
    draw_type_label: str
    public_path: str
    public_url: str
    division_code: Optional[str] = None


@dataclass(frozen=True)
class DrawQrBoardSnapshot:
    tournament_id: int
    tournament_name: str
    filename_slug: str
    items: List[DrawQrBoardItem]


class DrawQrBoardError(Exception):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def tournament_filename_slug(name: str, tournament_id: int) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")
    return slug or str(tournament_id)


def _normalize_origin(raw: str) -> str:
    value = (raw or "").strip().rstrip("/")
    if value.endswith("/api"):
        value = value[: -len("/api")]
    parsed = urlparse(value if "://" in value else f"https://{value}")
    if not parsed.netloc:
        return value.rstrip("/")
    return f"{parsed.scheme}://{parsed.netloc}"


def resolve_public_frontend_origin(request_base_url: Optional[str] = None) -> str:
    """Player-facing origin for QR URLs.

    Prefer an explicit public/frontend env var so localhost or internal hosts
    are never baked into production codes. Fall back to the current request
    origin for local/staging when no env is set.
    """
    for key in PUBLIC_ORIGIN_ENV_KEYS:
        raw = os.getenv(key, "").strip()
        if raw:
            return _normalize_origin(raw)
    if request_base_url:
        return _normalize_origin(request_base_url)
    return "http://localhost:3000"


def public_waterfall_path(tournament_id: int, event_id: int) -> str:
    return f"/t/{tournament_id}/draws/{event_id}/waterfall"


def public_round_robin_path(tournament_id: int, event_id: int) -> str:
    return f"/t/{tournament_id}/draws/{event_id}/roundrobin"


def public_bracket_path(tournament_id: int, event_id: int, division_code: str) -> str:
    return f"/t/{tournament_id}/draws/{event_id}/bracket/{division_code}"


# QR board display order: Women's, then Mixed. Do not use string sort of
# Event.category ("mixed" < "womens") and do not use schedule day_orders
# (those are policy priority and can put C before A).
_CATEGORY_ORDER = {
    "womens": 0,
    "mixed": 1,
}


def _event_category_key(event: Event) -> str:
    category = event.category
    if hasattr(category, "value"):
        return str(category.value)
    return str(category)


def _event_sort_key(event: Event) -> tuple:
    """Women's before Mixed; A → B → C via Event.name within a category."""
    category = _event_category_key(event).strip().lower()
    return (_CATEGORY_ORDER.get(category, 99), event.name or "", event.id or 0)


def _ordered_events(events: Sequence[Event]) -> List[Event]:
    return sorted(events, key=_event_sort_key)


def _template_type(event: Event) -> Optional[str]:
    if not event.draw_plan_json:
        return None
    try:
        parsed = json.loads(event.draw_plan_json) or {}
    except (TypeError, json.JSONDecodeError):
        return None
    value = parsed.get("template_type")
    return str(value) if value else None


def _event_match_rows(session: Session, event_id: int, version_id: int) -> List[Match]:
    return list(
        session.exec(
            select(Match).where(
                Match.event_id == event_id,
                Match.schedule_version_id == version_id,
            )
        ).all()
    )


def _has_waterfall(matches: Iterable[Match]) -> bool:
    return any((match.match_type or "") == "WF" for match in matches)


def _has_round_robin(matches: Iterable[Match]) -> bool:
    return any((match.match_type or "") == "RR" for match in matches)


def _bracket_division_codes(event: Event, matches: Iterable[Match]) -> List[str]:
    if _template_type(event) in POOLS_ONLY_TEMPLATES:
        return []
    found: set[str] = set()
    for match in matches:
        code = (match.match_code or "").upper()
        for div in BRACKET_DIV_ORDER:
            if f"_{div}_" in code:
                found.add(div)
    return [div for div in BRACKET_DIV_ORDER if div in found]


def _item(
    *,
    tournament_id: int,
    event: Event,
    draw_type: str,
    public_path: str,
    origin: str,
    draw_type_label: Optional[str] = None,
    division_code: Optional[str] = None,
) -> DrawQrBoardItem:
    name = event.name or f"Event {event.id}"
    return DrawQrBoardItem(
        event_id=int(event.id),
        event_name=name,
        label=name,
        draw_type=draw_type,
        draw_type_label=draw_type_label or DRAW_TYPE_LABELS[draw_type],
        public_path=public_path,
        public_url=f"{origin}{public_path}",
        division_code=division_code,
    )


def build_draw_qr_board(
    session: Session,
    tournament_id: int,
    request_base_url: Optional[str] = None,
) -> DrawQrBoardSnapshot:
    tournament = session.get(Tournament, tournament_id)
    if not tournament:
        raise DrawQrBoardError(404, "Tournament not found")

    origin = resolve_public_frontend_origin(request_base_url)
    slug = tournament_filename_slug(tournament.name, tournament_id)
    version: Optional[ScheduleVersion] = None
    if tournament.public_schedule_version_id:
        version = session.get(ScheduleVersion, tournament.public_schedule_version_id)

    items: List[DrawQrBoardItem] = []
    if version is None:
        return DrawQrBoardSnapshot(
            tournament_id=tournament_id,
            tournament_name=tournament.name,
            filename_slug=slug,
            items=items,
        )

    events = list(session.exec(select(Event).where(Event.tournament_id == tournament_id)).all())
    for event in _ordered_events(events):
        matches = _event_match_rows(session, int(event.id), int(version.id))
        if _has_waterfall(matches):
            items.append(
                _item(
                    tournament_id=tournament_id,
                    event=event,
                    draw_type=DRAW_TYPE_WATERFALL,
                    public_path=public_waterfall_path(tournament_id, int(event.id)),
                    origin=origin,
                )
            )
        if _has_round_robin(matches):
            items.append(
                _item(
                    tournament_id=tournament_id,
                    event=event,
                    draw_type=DRAW_TYPE_ROUND_ROBIN,
                    public_path=public_round_robin_path(tournament_id, int(event.id)),
                    origin=origin,
                )
            )
        bracket_codes = _bracket_division_codes(event, matches)
        multi_bracket = len(bracket_codes) > 1
        for code in bracket_codes:
            items.append(
                _item(
                    tournament_id=tournament_id,
                    event=event,
                    draw_type=DRAW_TYPE_BRACKET,
                    public_path=public_bracket_path(tournament_id, int(event.id), code),
                    origin=origin,
                    draw_type_label=BRACKET_DIV_LABELS[code] if multi_bracket else DRAW_TYPE_LABELS[DRAW_TYPE_BRACKET],
                    division_code=code,
                )
            )

    return DrawQrBoardSnapshot(
        tournament_id=tournament_id,
        tournament_name=tournament.name,
        filename_slug=slug,
        items=items,
    )


def snapshot_to_public_dict(snapshot: DrawQrBoardSnapshot) -> dict:
    return {
        "tournament_id": snapshot.tournament_id,
        "tournament_name": snapshot.tournament_name,
        "filename_slug": snapshot.filename_slug,
        "items": [
            {
                "event_id": item.event_id,
                "event_name": item.event_name,
                "label": item.label,
                "draw_type": item.draw_type,
                "draw_type_label": item.draw_type_label,
                "division_code": item.division_code,
                "public_path": item.public_path,
                "public_url": item.public_url,
            }
            for item in snapshot.items
        ],
    }
