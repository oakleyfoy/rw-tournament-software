import re
from datetime import date, datetime, time, timedelta
from io import BytesIO
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, field_validator, model_validator
from sqlmodel import Session, func, select, text

from app.database import get_session
from app.models.court_state import TournamentCourtState
from app.models.event import Event
from app.models.match import Match
from app.models.match_assignment import MatchAssignment
from app.models.match_lock import MatchLock
from app.models.player import Player
from app.models.policy_run import PolicyRun
from app.models.schedule_slot import ScheduleSlot
from app.models.schedule_version import ScheduleVersion
from app.models.slot_lock import SlotLock
from app.models.sms_template import SmsTemplate
from app.models.team import Team
from app.models.team_avoid_edge import TeamAvoidEdge
from app.models.team_player import TeamPlayer
from app.models.tournament import Tournament
from app.models.tournament_day import TournamentDay
from app.models.tournament_sms_settings import TournamentSmsSettings
from app.models.tournament_time_window import TournamentTimeWindow
from app.utils.courts import parse_court_names

router = APIRouter()

PRINT_PACKET_PAGE_SIZE = (32 * 72, 24 * 72)  # 32x24 in, points
_PRINT_CATEGORY_LABEL = {
    "womens": "Women's",
    "mixed": "Mixed",
}


class TournamentCreate(BaseModel):
    name: str
    location: str
    timezone: str
    start_date: date
    end_date: date
    notes: Optional[str] = None

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, v):
        if not v or not v.strip():
            raise ValueError("timezone is required")
        return v.strip()

    @model_validator(mode="after")
    def validate_date_range(self):
        if self.end_date < self.start_date:
            raise ValueError("end_date must be >= start_date")
        return self


class TournamentUpdate(BaseModel):
    name: Optional[str] = None
    location: Optional[str] = None
    timezone: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    notes: Optional[str] = None
    use_time_windows: Optional[bool] = None
    court_names: Optional[List[str]] = None

    @model_validator(mode="after")
    def validate_date_range(self):
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValueError("end_date must be >= start_date")
        return self


class TournamentResponse(BaseModel):
    id: int
    name: str
    location: str
    timezone: str
    start_date: date
    end_date: date
    notes: Optional[str]
    use_time_windows: bool
    court_names: Optional[List[str]] = None
    public_schedule_version_id: Optional[int] = None
    created_at: datetime
    updated_at: datetime

    @field_validator("court_names", mode="before")
    @classmethod
    def normalize_court_names(cls, v):
        """Handle legacy DB storage: court_names may be string '1,2,3' instead of list."""
        if v is None:
            return None
        return parse_court_names(v)  # handles str and list, returns List[str]

    class Config:
        from_attributes = True


def _resolve_print_version(session: Session, tournament: Tournament) -> Optional[ScheduleVersion]:
    """Prefer published pointer, then latest FINAL, then latest version."""
    if tournament.public_schedule_version_id:
        v = session.get(ScheduleVersion, tournament.public_schedule_version_id)
        if v and v.tournament_id == tournament.id:
            return v

    latest_final = session.exec(
        select(ScheduleVersion)
        .where(
            ScheduleVersion.tournament_id == tournament.id,
            ScheduleVersion.status == "final",
        )
        .order_by(ScheduleVersion.version_number.desc(), ScheduleVersion.id.desc())
    ).first()
    if latest_final:
        return latest_final

    return session.exec(
        select(ScheduleVersion)
        .where(ScheduleVersion.tournament_id == tournament.id)
        .order_by(ScheduleVersion.version_number.desc(), ScheduleVersion.id.desc())
    ).first()


def _score_display(score_json: Optional[dict]) -> str:
    if not score_json:
        return ""
    if isinstance(score_json, str):
        return score_json
    if isinstance(score_json, dict):
        if "display" in score_json:
            return str(score_json["display"])
        if "sets" in score_json and isinstance(score_json["sets"], list):
            return " ".join(f"{s.get('a', 0)}-{s.get('b', 0)}" for s in score_json["sets"])
        if "a" in score_json and "b" in score_json:
            return f"{score_json['a']}-{score_json['b']}"
    return str(score_json)


def _format_slot_fields(slot: Optional[ScheduleSlot]) -> Tuple[str, str, str]:
    if not slot:
        return "", "", ""

    day = slot.day_date.strftime("%a %m/%d")
    st = slot.start_time
    if isinstance(st, str):
        parts = st.split(":")
        hour = int(parts[0]) if parts else 0
        minute = int(parts[1]) if len(parts) > 1 else 0
        ampm = "AM" if hour < 12 else "PM"
        h12 = hour % 12 or 12
        time_str = f"{h12}:{minute:02d} {ampm}"
    else:
        time_str = st.strftime("%I:%M %p").lstrip("0") if st else ""

    cl = slot.court_label or str(slot.court_number)
    court = f"Court {cl}" if cl and not str(cl).lower().startswith("court") else str(cl)
    return day, time_str, court


def _pool_from_match_code(match_code: str) -> str:
    code = (match_code or "").upper()
    for marker in ("POOLA", "POOLB", "POOLC", "POOLD"):
        if f"_{marker}_" in code:
            return marker
    return ""


def _build_print_packet_pdf(
    tournament: Tournament,
    category: str,
    version: ScheduleVersion,
    events: List[Event],
    matches_by_event: Dict[int, List[Match]],
    assignment_by_match: Dict[int, MatchAssignment],
    slot_map: Dict[int, ScheduleSlot],
    team_map: Dict[int, Team],
) -> bytes:
    import math

    from reportlab.pdfgen import canvas

    C_BLACK = 0.0
    C_DARK = 0.2
    C_MID = 0.45
    C_LIGHT = 0.75
    C_BG = 0.95

    pool_label_map = {
        "POOLA": "Division I",
        "POOLB": "Division II",
        "POOLC": "Division III",
        "POOLD": "Division IV",
    }
    dest_label_map = {
        "BWW": "Division I",
        "BWL": "Division II",
        "BLW": "Division III",
        "BLL": "Division IV",
    }

    def _team_name(team_id: Optional[int], placeholder: Optional[str]) -> str:
        if team_id and team_id in team_map:
            t = team_map[team_id]
            return t.display_name or t.name or f"Team {team_id}"
        return placeholder or "TBD"

    def _status_for(match: Match) -> str:
        rt = (match.runtime_status or "").upper()
        if rt in {"FINAL", "IN_PROGRESS"}:
            return rt
        return "SCHEDULED" if match.id in assignment_by_match else "UNSCHEDULED"

    def _clip(c: canvas.Canvas, text: str, font: str, size: float, max_w: float) -> str:
        if not text:
            return ""
        raw = str(text)
        if c.stringWidth(raw, font, size) <= max_w:
            return raw
        ell = "..."
        s = raw
        while s and c.stringWidth(s + ell, font, size) > max_w:
            s = s[:-1]
        return (s + ell) if s else ell

    def _match_top_line(match: Match) -> str:
        status = _status_for(match)
        score = _score_display(match.score_json) if status == "FINAL" else ""
        base = f"Match #{match.id}"
        if score:
            return f"{base} - {score}"
        asgn = assignment_by_match.get(match.id)
        slot = slot_map.get(asgn.slot_id) if asgn else None
        if not slot:
            return base
        day, tm, court = _format_slot_fields(slot)
        parts = [base]
        if court:
            parts.append(court)
        if day:
            parts.append(day)
        if tm:
            parts.append(tm)
        return " - ".join(parts)

    def _draw_header(c: canvas.Canvas, title: str, subtitle: str) -> None:
        width, height = PRINT_PACKET_PAGE_SIZE
        top = height - 28
        bar_h = 42
        c.setFillGray(C_BLACK)
        c.rect(24, top - bar_h, width - 48, bar_h, stroke=0, fill=1)
        c.setFillGray(1.0)
        c.setFont("Helvetica-Bold", 18)
        c.drawString(36, top - 17, _clip(c, title.upper(), "Helvetica-Bold", 18, width - 80))
        c.setFillGray(C_DARK)
        c.setFont("Helvetica", 10)
        c.drawString(36, top - bar_h - 14, _clip(c, subtitle, "Helvetica", 10, width - 72))
        c.setStrokeGray(C_LIGHT)
        c.setLineWidth(1)
        c.line(24, top - bar_h - 18, width - 24, top - bar_h - 18)

    def _draw_footer(c: canvas.Canvas) -> None:
        width, _ = PRINT_PACKET_PAGE_SIZE
        c.setFillGray(C_MID)
        c.setFont("Helvetica", 9)
        c.drawCentredString(width / 2, 14, f"Page {c.getPageNumber()}")

    def _draw_arrow(c: canvas.Canvas, x1: float, y: float, x2: float) -> None:
        c.setStrokeGray(C_LIGHT)
        c.setFillGray(C_LIGHT)
        c.setLineWidth(1)
        c.line(x1, y, x2, y)
        if abs(x2 - x1) < 8:
            return
        if x2 > x1:
            c.line(x2 - 5, y + 3, x2, y)
            c.line(x2 - 5, y - 3, x2, y)
        else:
            c.line(x2 + 5, y + 3, x2, y)
            c.line(x2 + 5, y - 3, x2, y)

    def _draw_match_card(
        c: canvas.Canvas,
        match: Match,
        x: float,
        y: float,
        w: float,
        h: float,
        variant: str,
    ) -> None:
        status = _status_for(match)
        score = _score_display(match.score_json) if status == "FINAL" else ""

        base_fill = C_BG
        if variant == "winner":
            base_fill = 0.93
        elif variant == "loser":
            base_fill = 0.90
        elif variant == "center":
            base_fill = 0.95
        if status == "FINAL":
            base_fill = max(0.84, base_fill - 0.06)

        c.setFillGray(base_fill)
        c.setStrokeGray(C_LIGHT)
        c.rect(x, y, w, h, stroke=1, fill=1)

        top_line = _match_top_line(match)
        team_a = _team_name(match.team_a_id, match.placeholder_side_a)
        team_b = _team_name(match.team_b_id, match.placeholder_side_b)

        team_a_won = status == "FINAL" and match.winner_team_id and match.team_a_id == match.winner_team_id
        team_b_won = status == "FINAL" and match.winner_team_id and match.team_b_id == match.winner_team_id

        top_y = y + h - 13
        c.setFillGray(C_DARK)
        c.setFont("Helvetica-Bold", 9)
        c.drawString(x + 6, top_y, _clip(c, top_line, "Helvetica-Bold", 9, w - 12))

        t1_y = top_y - 14
        c.setFont("Helvetica-Bold" if team_a_won else "Helvetica", 10)
        c.setFillGray(C_BLACK if team_a_won else C_DARK)
        c.drawString(x + 6, t1_y, _clip(c, team_a, c._fontname, 10, w - 12))

        vs_y = t1_y - 11
        c.setFont("Helvetica-Oblique", 8)
        c.setFillGray(C_MID)
        c.drawCentredString(x + (w / 2), vs_y, "vs")

        t2_y = vs_y - 10
        c.setFont("Helvetica-Bold" if team_b_won else "Helvetica", 10)
        c.setFillGray(C_BLACK if team_b_won else C_DARK)
        c.drawString(x + 6, t2_y, _clip(c, team_b, c._fontname, 10, w - 12))

        if score:
            c.setFont("Helvetica-Bold", 9)
            c.setFillGray(C_BLACK)
            c.drawRightString(x + w - 6, y + 7, _clip(c, score, "Helvetica-Bold", 9, 90))
        elif status in {"IN_PROGRESS", "SCHEDULED", "UNSCHEDULED"}:
            c.setFont("Helvetica", 8)
            c.setFillGray(C_MID)
            c.drawRightString(x + w - 6, y + 7, status.replace("_", " "))

    def _draw_dest_card(c: canvas.Canvas, x: float, y: float, w: float, h: float, label: str, team_name: Optional[str]) -> None:
        c.setFillGray(0.97)
        c.setStrokeGray(C_LIGHT)
        c.rect(x, y, w, h, stroke=1, fill=1)
        text_y = y + h - 15
        if team_name:
            c.setFont("Helvetica-Bold", 10)
            c.setFillGray(C_BLACK)
            c.drawCentredString(x + (w / 2), text_y, _clip(c, team_name, "Helvetica-Bold", 10, w - 10))
            text_y -= 14
            c.setStrokeGray(C_LIGHT)
            c.line(x + 6, text_y + 4, x + w - 6, text_y + 4)
        c.setFillGray(C_DARK)
        c.setFont("Helvetica", 8.5)
        for raw in (label or "").split("\n"):
            if text_y < y + 8:
                break
            c.drawCentredString(x + (w / 2), text_y, _clip(c, raw, "Helvetica", 8.5, w - 10))
            text_y -= 11

    def _dest_lines(event_name: str, r2_role: str, r2_seq: int, r2_winner_count: int) -> str:
        if r2_role == "WINNER":
            win_div = dest_label_map["BWW"]
            lose_div = dest_label_map["BWL"]
            letter = chr(ord("A") + r2_seq - 1)
        else:
            win_div = dest_label_map["BLW"]
            lose_div = dest_label_map["BLL"]
            letter = chr(ord("A") + r2_seq - r2_winner_count - 1)
        return (
            f"Winner to {event_name} {win_div} - {letter}\n"
            f"Loser to {event_name} {lose_div} - {letter}"
        )

    def _build_wf_rows(event: Event, wf_matches: List[Match]) -> List[Dict[str, Any]]:
        all_matches = {m.id: m for m in wf_matches}
        r1_matches = sorted(
            [m for m in wf_matches if (m.round_index or 0) == 1],
            key=lambda m: (m.sequence_in_round or 0, m.id),
        )
        r2_matches = [m for m in wf_matches if (m.round_index or 0) == 2]
        if not r1_matches:
            return []

        r1_to_winner: Dict[int, Match] = {}
        r1_to_loser: Dict[int, Match] = {}
        for r2 in r2_matches:
            is_winner_match = (r2.source_a_role or "").upper() == "WINNER"
            is_loser_match = (r2.source_a_role or "").upper() == "LOSER"
            for src_id in [r2.source_match_a_id, r2.source_match_b_id]:
                if not src_id or src_id not in all_matches:
                    continue
                if is_winner_match:
                    r1_to_winner[src_id] = r2
                elif is_loser_match:
                    r1_to_loser[src_id] = r2

        r1_by_id = {m.id: m for m in r1_matches}
        ordered_r1: List[Match] = []
        seen: set[int] = set()
        for r2w in sorted(
            [r2 for r2 in r2_matches if (r2.source_a_role or "").upper() == "WINNER"],
            key=lambda m: (m.sequence_in_round or 0, m.id),
        ):
            src_ids = [sid for sid in [r2w.source_match_a_id, r2w.source_match_b_id] if sid and sid in r1_by_id]
            src_ids.sort(key=lambda sid: (r1_by_id[sid].sequence_in_round or 0, sid))
            for sid in src_ids:
                if sid not in seen:
                    ordered_r1.append(r1_by_id[sid])
                    seen.add(sid)
        for r1 in r1_matches:
            if r1.id not in seen:
                ordered_r1.append(r1)

        r2_winner_count = sum(1 for r2 in r2_matches if (r2.source_a_role or "").upper() == "WINNER")
        rows: List[Dict[str, Any]] = []
        for r1 in ordered_r1:
            winner_match = r1_to_winner.get(r1.id)
            loser_match = r1_to_loser.get(r1.id)
            winner_dest = None
            loser_dest = None
            if winner_match and winner_match.sequence_in_round:
                winner_dest = _dest_lines(event.name, "WINNER", winner_match.sequence_in_round, r2_winner_count)
            if loser_match and loser_match.sequence_in_round:
                loser_dest = _dest_lines(event.name, "LOSER", loser_match.sequence_in_round, r2_winner_count)

            r2_winner_name = _team_name(winner_match.winner_team_id, None) if winner_match and winner_match.winner_team_id else None
            r2_loser_name = _team_name(loser_match.winner_team_id, None) if loser_match and loser_match.winner_team_id else None

            rows.append(
                {
                    "center": r1,
                    "winner": winner_match,
                    "loser": loser_match,
                    "winner_dest": winner_dest,
                    "loser_dest": loser_dest,
                    "r2_winner_name": r2_winner_name,
                    "r2_loser_name": r2_loser_name,
                }
            )
        return rows

    def _draw_wf_page(c: canvas.Canvas, event: Event, wf_matches: List[Match], category_label: str) -> None:
        width, height = PRINT_PACKET_PAGE_SIZE
        generated = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
        _draw_header(
            c,
            f"{event.name} - {category_label} Waterfall",
            f"{tournament.name} | Version #{version.version_number} ({version.status.upper()}) | {generated}",
        )

        rows = _build_wf_rows(event, wf_matches)
        if not rows:
            c.setFillGray(C_DARK)
            c.setFont("Helvetica", 14)
            c.drawString(44, height - 120, "No waterfall matches.")
            _draw_footer(c)
            c.showPage()
            return

        pairs: List[Tuple[Dict[str, Any], Optional[Dict[str, Any]]]] = []
        idx = 0
        while idx < len(rows):
            first = rows[idx]
            second = rows[idx + 1] if idx + 1 < len(rows) else None
            pairs.append((first, second))
            idx += 2

        left = 24
        right = width - 24
        top = height - 112
        bottom = 34

        conn_w = 24.0
        dest_w = 210.0
        side_w = 320.0
        center_w = 540.0
        bundle_w = (2 * dest_w) + (2 * side_w) + center_w + (4 * conn_w)
        available_w = right - left
        if bundle_w > available_w:
            scale = available_w / bundle_w
            conn_w *= scale
            dest_w *= scale
            side_w *= scale
            center_w *= scale
            bundle_w = available_w
        start_x = left + ((available_w - bundle_w) / 2.0)
        x_dest_left = start_x
        x_loser = x_dest_left + dest_w + conn_w
        x_center = x_loser + side_w + conn_w
        x_winner = x_center + center_w + conn_w
        x_dest_right = x_winner + side_w + conn_w

        pair_count = max(1, len(pairs))
        pair_gap = 20.0
        available_h = max(120.0, top - bottom)
        pair_h = (available_h - (pair_gap * (pair_count - 1))) / pair_count
        if pair_h < 120:
            pair_h = 120
            pair_gap = 12

        for pi, (row_a, row_b) in enumerate(pairs):
            y_top = top - (pi * (pair_h + pair_gap))
            y_bottom = y_top - pair_h
            if y_bottom < bottom:
                break

            if row_b:
                center_gap = 10.0
                center_h = (pair_h - center_gap) / 2.0
                c1_y = y_bottom + center_h + center_gap
                c2_y = y_bottom
                _draw_match_card(c, row_a["center"], x_center, c1_y, center_w, center_h, "center")
                _draw_match_card(c, row_b["center"], x_center, c2_y, center_w, center_h, "center")
                center_mid_ys = [c1_y + center_h / 2.0, c2_y + center_h / 2.0]
            else:
                center_h = pair_h
                c_y = y_bottom
                _draw_match_card(c, row_a["center"], x_center, c_y, center_w, center_h, "center")
                center_mid_ys = [c_y + center_h / 2.0]

            loser_match = row_a.get("loser") or (row_b.get("loser") if row_b else None)
            winner_match = row_a.get("winner") or (row_b.get("winner") if row_b else None)
            loser_dest = row_a.get("loser_dest") or (row_b.get("loser_dest") if row_b else None)
            winner_dest = row_a.get("winner_dest") or (row_b.get("winner_dest") if row_b else None)
            loser_team_name = row_a.get("r2_loser_name") or (row_b.get("r2_loser_name") if row_b else None)
            winner_team_name = row_a.get("r2_winner_name") or (row_b.get("r2_winner_name") if row_b else None)

            if loser_match:
                _draw_match_card(c, loser_match, x_loser, y_bottom, side_w, pair_h, "loser")
            if winner_match:
                _draw_match_card(c, winner_match, x_winner, y_bottom, side_w, pair_h, "winner")

            if loser_dest:
                _draw_dest_card(c, x_dest_left, y_bottom, dest_w, pair_h, loser_dest, loser_team_name)
            if winner_dest:
                _draw_dest_card(c, x_dest_right, y_bottom, dest_w, pair_h, winner_dest, winner_team_name)

            left_mid_y = y_bottom + pair_h / 2.0
            right_mid_y = left_mid_y

            if loser_match:
                for cy in center_mid_ys:
                    _draw_arrow(c, x_center, cy, x_loser + side_w)
                _draw_arrow(c, x_loser, left_mid_y, x_dest_left + dest_w)
            if winner_match:
                for cy in center_mid_ys:
                    _draw_arrow(c, x_center + center_w, cy, x_winner)
                _draw_arrow(c, x_winner + side_w, right_mid_y, x_dest_right)

        _draw_footer(c)
        c.showPage()

    def _draw_rr_match_card(c: canvas.Canvas, match: Match, x: float, y: float, w: float, h: float) -> None:
        status = _status_for(match)
        score = _score_display(match.score_json) if status == "FINAL" else None
        team_a = _team_name(match.team_a_id, match.placeholder_side_a)
        team_b = _team_name(match.team_b_id, match.placeholder_side_b)
        asgn = assignment_by_match.get(match.id)
        slot = slot_map.get(asgn.slot_id) if asgn else None
        _, tm, court = _format_slot_fields(slot)

        c.setFillGray(1.0)
        c.setStrokeGray(C_LIGHT)
        c.rect(x, y, w, h, stroke=1, fill=1)

        c.setFont("Helvetica-Bold", 9.5)
        c.setFillGray(C_BLACK)
        c.drawString(x + 6, y + h - 13, _clip(c, team_a, "Helvetica-Bold", 9.5, w - 12))

        meta = f"Match #{match.id}"
        if court:
            meta += f" - {court}"
        c.setFont("Helvetica", 8)
        c.setFillGray(C_MID)
        c.drawString(x + 6, y + h - 25, _clip(c, meta, "Helvetica", 8, w - 12))

        state_text = score if score else status.replace("_", " ")
        c.setFont("Helvetica-Bold", 8.5)
        c.setFillGray(C_DARK)
        c.drawCentredString(x + (w / 2), y + h - 38, _clip(c, state_text, "Helvetica-Bold", 8.5, w - 12))

        if tm and not score:
            c.setFont("Helvetica", 7.5)
            c.setFillGray(C_MID)
            c.drawCentredString(x + (w / 2), y + h - 49, _clip(c, tm, "Helvetica", 7.5, w - 12))

        c.setStrokeGray(C_BG)
        c.line(x + 6, y + 24, x + w - 6, y + 24)
        c.setFont("Helvetica-Bold", 9.5)
        c.setFillGray(C_BLACK)
        c.drawString(x + 6, y + 10, _clip(c, team_b, "Helvetica-Bold", 9.5, w - 12))

    def _draw_rr_page(c: canvas.Canvas, event: Event, rr_matches: List[Match], category_label: str) -> None:
        width, height = PRINT_PACKET_PAGE_SIZE
        generated = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
        _draw_header(
            c,
            f"{event.name} - {category_label} Round Robin",
            f"{tournament.name} | Version #{version.version_number} ({version.status.upper()}) | {generated}",
        )

        pools: Dict[str, List[Match]] = {}
        for m in rr_matches:
            p = _pool_from_match_code(m.match_code or "") or "POOL"
            pools.setdefault(p, []).append(m)
        for p in pools:
            pools[p].sort(key=lambda m: (m.round_index or 0, m.sequence_in_round or 0, m.id))

        ordered_pool_keys = sorted(
            pools.keys(),
            key=lambda p: {"POOLA": 1, "POOLB": 2, "POOLC": 3, "POOLD": 4}.get(p, 99),
        )
        if not ordered_pool_keys:
            c.setFillGray(C_DARK)
            c.setFont("Helvetica", 14)
            c.drawString(44, height - 120, "No round robin matches.")
            _draw_footer(c)
            c.showPage()
            return

        left = 28
        right = width - 28
        top = height - 112
        bottom = 34
        cols = 2 if len(ordered_pool_keys) > 1 else 1
        rows = max(1, math.ceil(len(ordered_pool_keys) / cols))
        col_gap = 18.0
        row_gap = 18.0
        card_w = (right - left - (col_gap * (cols - 1))) / cols
        card_h = (top - bottom - (row_gap * (rows - 1))) / rows

        for idx, pool_code in enumerate(ordered_pool_keys):
            row = idx // cols
            col = idx % cols
            x = left + (col * (card_w + col_gap))
            y_top = top - (row * (card_h + row_gap))
            y_bottom = y_top - card_h
            if y_bottom < bottom:
                continue

            c.setFillGray(C_BG)
            c.setStrokeGray(C_LIGHT)
            c.rect(x, y_bottom, card_w, card_h, stroke=1, fill=1)

            title = f"{category_label.upper()} ROUND ROBIN {pool_label_map.get(pool_code, pool_code).upper()}"
            title_h = 18.0
            c.setFillGray(C_BLACK)
            c.rect(x, y_top - title_h, card_w, title_h, stroke=0, fill=1)
            c.setFillGray(1.0)
            c.setFont("Helvetica-Bold", 9.5)
            c.drawString(x + 6, y_top - 12.5, _clip(c, title, "Helvetica-Bold", 9.5, card_w - 12))

            matches = pools.get(pool_code, [])
            rounds_map: Dict[int, List[Match]] = {}
            for m in matches:
                rounds_map.setdefault(m.round_index or 1, []).append(m)
            round_keys = sorted(rounds_map.keys())

            content_top = y_top - title_h - 8
            content_bottom = y_bottom + 8
            content_h = max(20.0, content_top - content_bottom)
            if not round_keys:
                c.setFillGray(C_MID)
                c.setFont("Helvetica-Oblique", 9)
                c.drawString(x + 8, content_top - 10, "No matches.")
                continue

            row_h = content_h / len(round_keys)
            if row_h < 52:
                line_y = content_top - 11
                for m in matches:
                    if line_y < content_bottom + 8:
                        c.setFillGray(C_MID)
                        c.setFont("Helvetica-Oblique", 8)
                        c.drawString(x + 8, content_bottom + 2, "... more matches")
                        break
                    desc = f"R{m.round_index or 1}  {_team_name(m.team_a_id, m.placeholder_side_a)} vs {_team_name(m.team_b_id, m.placeholder_side_b)}"
                    c.setFillGray(C_DARK)
                    c.setFont("Helvetica", 8)
                    c.drawString(x + 8, line_y, _clip(c, desc, "Helvetica", 8, card_w - 16))
                    line_y -= 10
                continue

            for rk_index, rk in enumerate(round_keys):
                matches_in_round = sorted(rounds_map[rk], key=lambda m: (m.sequence_in_round or 0, m.id))
                ry_top = content_top - (rk_index * row_h)
                ry_bottom = ry_top - row_h
                if ry_bottom < content_bottom:
                    break

                round_label_w = 76.0
                c.setFillGray(C_DARK)
                c.setFont("Helvetica-Bold", 8.5)
                c.drawCentredString(x + (round_label_w / 2.0), ry_bottom + (row_h / 2.0) - 3, f"Round {rk}")

                area_x = x + round_label_w + 6
                area_w = card_w - round_label_w - 12
                match_count = max(1, len(matches_in_round))
                gap = 8.0
                m_w = (area_w - (gap * (match_count - 1))) / match_count
                m_h = min(86.0, row_h - 8)
                m_y = ry_bottom + ((row_h - m_h) / 2.0)
                for mi, m in enumerate(matches_in_round):
                    mx = area_x + (mi * (m_w + gap))
                    _draw_rr_match_card(c, m, mx, m_y, m_w, m_h)

        _draw_footer(c)
        c.showPage()

    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=PRINT_PACKET_PAGE_SIZE)
    category_label = _PRINT_CATEGORY_LABEL.get(category, category.title())

    events_sorted = sorted(events, key=lambda e: (e.name or "").lower())
    rendered_any = False

    for event in events_sorted:
        event_matches = matches_by_event.get(event.id, [])
        wf = sorted(
            [m for m in event_matches if (m.match_type or "").upper() == "WF"],
            key=lambda m: (m.round_index or 0, m.sequence_in_round or 0, m.id),
        )
        rr = sorted(
            [m for m in event_matches if (m.match_type or "").upper() == "RR"],
            key=lambda m: (
                _pool_from_match_code(m.match_code or ""),
                m.round_index or 0,
                m.sequence_in_round or 0,
                m.id,
            ),
        )
        if wf:
            _draw_wf_page(c, event, wf, category_label)
            rendered_any = True
        if rr:
            _draw_rr_page(c, event, rr, category_label)
            rendered_any = True

    if not rendered_any:
        generated = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
        _draw_header(
            c,
            f"{tournament.name} — {category_label} Draw Packet",
            f"Version #{version.version_number} ({version.status.upper()}) | {generated}",
        )
        c.setFont("Helvetica", 14)
        c.drawString(40, PRINT_PACKET_PAGE_SIZE[1] - 100, f"No {category_label.lower()} WF/RR matches found.")
        _draw_footer(c)
        c.showPage()

    c.save()
    return buffer.getvalue()


def generate_tournament_days(session: Session, tournament_id: int, start_date: date, end_date: date):
    """Generate tournament days for the date range"""
    current_date = start_date
    while current_date <= end_date:
        # Check if day already exists
        existing = session.exec(
            select(TournamentDay).where(
                TournamentDay.tournament_id == tournament_id, TournamentDay.date == current_date
            )
        ).first()

        if not existing:
            day = TournamentDay(
                tournament_id=tournament_id,
                date=current_date,
                is_active=True,
                start_time=time(8, 0),
                end_time=time(18, 0),
                courts_available=0,
            )
            session.add(day)
        current_date += timedelta(days=1)
    session.commit()


@router.get("/tournaments", response_model=List[TournamentResponse])
def list_tournaments(session: Session = Depends(get_session)):
    """List all tournaments"""
    tournaments = session.exec(select(Tournament)).all()
    return tournaments


@router.post("/tournaments", response_model=TournamentResponse, status_code=201)
def create_tournament(tournament_data: TournamentCreate, session: Session = Depends(get_session)):
    """Create a new tournament and auto-generate days"""
    tournament = Tournament(**tournament_data.model_dump())
    session.add(tournament)
    session.commit()
    session.refresh(tournament)

    # Auto-generate days
    generate_tournament_days(session, tournament.id, tournament.start_date, tournament.end_date)

    return tournament


@router.get("/tournaments/{tournament_id}", response_model=TournamentResponse)
def get_tournament(tournament_id: int, session: Session = Depends(get_session)):
    """Get a tournament by ID"""
    tournament = session.get(Tournament, tournament_id)
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")
    return tournament


@router.get("/tournaments/{tournament_id}/print-packet/{category}.pdf")
def download_print_packet_pdf(
    tournament_id: int,
    category: str,
    session: Session = Depends(get_session),
):
    """Download a 32x24 B/W print packet PDF for one category."""
    cat = (category or "").strip().lower()
    if cat not in _PRINT_CATEGORY_LABEL:
        raise HTTPException(status_code=400, detail="category must be 'womens' or 'mixed'")

    tournament = session.get(Tournament, tournament_id)
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")

    version = _resolve_print_version(session, tournament)
    if not version:
        raise HTTPException(status_code=400, detail="No schedule version found for this tournament")

    events = session.exec(
        select(Event).where(
            Event.tournament_id == tournament_id,
            Event.category == cat,
        )
    ).all()
    event_ids = [e.id for e in events]

    matches = session.exec(
        select(Match).where(
            Match.tournament_id == tournament_id,
            Match.schedule_version_id == version.id,
            Match.event_id.in_(event_ids),  # type: ignore
            Match.match_type.in_(["WF", "RR"]),  # type: ignore
        )
    ).all() if event_ids else []
    matches_by_event: Dict[int, List[Match]] = {}
    for m in matches:
        matches_by_event.setdefault(m.event_id, []).append(m)

    match_ids = [m.id for m in matches]
    assignments = session.exec(
        select(MatchAssignment).where(
            MatchAssignment.schedule_version_id == version.id,
            MatchAssignment.match_id.in_(match_ids),  # type: ignore
        )
    ).all() if match_ids else []
    assignment_by_match = {a.match_id: a for a in assignments}

    slot_ids = list({a.slot_id for a in assignments})
    slots = session.exec(
        select(ScheduleSlot).where(ScheduleSlot.id.in_(slot_ids))
    ).all() if slot_ids else []
    slot_map = {s.id: s for s in slots}

    team_ids = set()
    for m in matches:
        if m.team_a_id:
            team_ids.add(m.team_a_id)
        if m.team_b_id:
            team_ids.add(m.team_b_id)
    teams = session.exec(
        select(Team).where(Team.id.in_(list(team_ids)))
    ).all() if team_ids else []
    team_map = {t.id: t for t in teams}

    try:
        pdf_bytes = _build_print_packet_pdf(
            tournament=tournament,
            category=cat,
            version=version,
            events=events,
            matches_by_event=matches_by_event,
            assignment_by_match=assignment_by_match,
            slot_map=slot_map,
            team_map=team_map,
        )
    except ModuleNotFoundError as exc:
        if "reportlab" in str(exc):
            raise HTTPException(status_code=500, detail="PDF dependency missing: reportlab") from exc
        raise

    safe_name = re.sub(r"[^A-Za-z0-9_-]+", "_", tournament.name).strip("_") or "tournament"
    filename = f"{safe_name}_{cat}_draw_packet.pdf"
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    return Response(content=pdf_bytes, media_type="application/pdf", headers=headers)


@router.put("/tournaments/{tournament_id}", response_model=TournamentResponse)
def update_tournament(tournament_id: int, tournament_data: TournamentUpdate, session: Session = Depends(get_session)):
    """Update a tournament and manage days based on date range changes"""
    tournament = session.get(Tournament, tournament_id)
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")

    old_start = tournament.start_date
    old_end = tournament.end_date

    # Update tournament fields
    update_data = tournament_data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(tournament, field, value)

    tournament.updated_at = datetime.utcnow()
    session.add(tournament)
    session.commit()

    # Handle date range changes
    new_start = tournament.start_date
    new_end = tournament.end_date

    if old_start != new_start or old_end != new_end:
        # Remove days outside the new range
        session.exec(
            select(TournamentDay)
            .where(TournamentDay.tournament_id == tournament_id)
            .where((TournamentDay.date < new_start) | (TournamentDay.date > new_end))
        )
        days_to_remove = session.exec(
            select(TournamentDay).where(
                TournamentDay.tournament_id == tournament_id,
                (TournamentDay.date < new_start) | (TournamentDay.date > new_end),
            )
        ).all()
        for day in days_to_remove:
            session.delete(day)

        # Add missing days for new range
        generate_tournament_days(session, tournament_id, new_start, new_end)

    session.refresh(tournament)
    return tournament


@router.post("/tournaments/{tournament_id}/duplicate", response_model=TournamentResponse, status_code=201)
def duplicate_tournament(tournament_id: int, session: Session = Depends(get_session)):
    """
    Deep-duplicate a tournament snapshot.

    Copies tournament configuration and operational state, including:
    - tournament fields (courts, dates, timezone, notes)
    - days + time windows
    - events + teams + avoid edges
    - players + team_player links
    - schedule versions + slots + matches + assignments
    - match/slot locks + policy runs
    - court state + SMS settings/templates
    """
    try:
        source_tournament = session.get(Tournament, tournament_id)
        if not source_tournament:
            raise HTTPException(status_code=404, detail="Tournament not found")

        # 1) Create destination tournament shell.
        new_tournament = Tournament(
            name=f"{source_tournament.name} (Copy)",
            location=source_tournament.location,
            timezone=source_tournament.timezone,
            start_date=source_tournament.start_date,
            end_date=source_tournament.end_date,
            notes=source_tournament.notes,
            use_time_windows=source_tournament.use_time_windows,
            court_names=list(source_tournament.court_names or []),
        )
        session.add(new_tournament)
        session.flush()

        source_days = session.exec(
            select(TournamentDay).where(TournamentDay.tournament_id == tournament_id)
        ).all()
        source_windows = session.exec(
            select(TournamentTimeWindow).where(TournamentTimeWindow.tournament_id == tournament_id)
        ).all()
        source_events = session.exec(
            select(Event).where(Event.tournament_id == tournament_id)
        ).all()
        source_versions = session.exec(
            select(ScheduleVersion)
            .where(ScheduleVersion.tournament_id == tournament_id)
            .order_by(ScheduleVersion.version_number.asc(), ScheduleVersion.id.asc())
        ).all()
        source_slots = session.exec(
            select(ScheduleSlot).where(ScheduleSlot.tournament_id == tournament_id)
        ).all()
        source_matches = session.exec(
            select(Match).where(Match.tournament_id == tournament_id)
        ).all()
        source_court_state = session.exec(
            select(TournamentCourtState).where(
                TournamentCourtState.tournament_id == tournament_id
            )
        ).all()
        source_sms_settings = session.exec(
            select(TournamentSmsSettings).where(
                TournamentSmsSettings.tournament_id == tournament_id
            )
        ).first()
        source_sms_templates = session.exec(
            select(SmsTemplate).where(SmsTemplate.tournament_id == tournament_id)
        ).all()

        source_event_ids = [e.id for e in source_events if e.id is not None]
        source_teams = session.exec(
            select(Team).where(Team.event_id.in_(source_event_ids))  # type: ignore
        ).all() if source_event_ids else []
        source_team_ids = [t.id for t in source_teams if t.id is not None]

        source_avoid_edges = session.exec(
            select(TeamAvoidEdge).where(TeamAvoidEdge.event_id.in_(source_event_ids))  # type: ignore
        ).all() if source_event_ids else []

        source_players = session.exec(
            select(Player).where(Player.tournament_id == tournament_id)
        ).all()
        source_team_players = session.exec(
            select(TeamPlayer).where(TeamPlayer.team_id.in_(source_team_ids))  # type: ignore
        ).all() if source_team_ids else []

        source_version_ids = [v.id for v in source_versions if v.id is not None]

        source_assignments = session.exec(
            select(MatchAssignment).where(
                MatchAssignment.schedule_version_id.in_(source_version_ids)  # type: ignore
            )
        ).all() if source_version_ids else []
        source_match_locks = session.exec(
            select(MatchLock).where(
                MatchLock.schedule_version_id.in_(source_version_ids)  # type: ignore
            )
        ).all() if source_version_ids else []
        source_slot_locks = session.exec(
            select(SlotLock).where(
                SlotLock.schedule_version_id.in_(source_version_ids)  # type: ignore
            )
        ).all() if source_version_ids else []
        source_policy_runs = session.exec(
            select(PolicyRun).where(
                PolicyRun.schedule_version_id.in_(source_version_ids)  # type: ignore
            )
        ).all() if source_version_ids else []

        # 2) Copy day/time-window metadata.
        for day in source_days:
            session.add(
                TournamentDay(
                    tournament_id=new_tournament.id,  # type: ignore[arg-type]
                    date=day.date,
                    is_active=day.is_active,
                    start_time=day.start_time,
                    end_time=day.end_time,
                    courts_available=day.courts_available,
                )
            )
        for window in source_windows:
            session.add(
                TournamentTimeWindow(
                    tournament_id=new_tournament.id,  # type: ignore[arg-type]
                    day_date=window.day_date,
                    start_time=window.start_time,
                    end_time=window.end_time,
                    courts_available=window.courts_available,
                    block_minutes=window.block_minutes,
                    label=window.label,
                    is_active=window.is_active,
                )
            )

        # 3) Copy event + team graph.
        event_id_map: dict[int, int] = {}
        for event in source_events:
            if event.id is None:
                continue
            cloned = Event(
                tournament_id=new_tournament.id,  # type: ignore[arg-type]
                category=event.category,
                name=event.name,
                team_count=event.team_count,
                notes=event.notes,
                draw_plan_json=event.draw_plan_json,
                draw_plan_version=event.draw_plan_version,
                draw_status=event.draw_status,
                wf_block_minutes=event.wf_block_minutes,
                standard_block_minutes=event.standard_block_minutes,
                guarantee_selected=event.guarantee_selected,
                schedule_profile_json=event.schedule_profile_json,
            )
            session.add(cloned)
            session.flush()
            event_id_map[event.id] = cloned.id  # type: ignore[index]

        team_id_map: dict[int, int] = {}
        for team in source_teams:
            if team.id is None:
                continue
            mapped_event_id = event_id_map.get(team.event_id)
            if mapped_event_id is None:
                continue
            cloned = Team(
                event_id=mapped_event_id,
                name=team.name,
                seed=team.seed,
                rating=team.rating,
                registration_timestamp=team.registration_timestamp,
                wf_group_index=team.wf_group_index,
                avoid_group=team.avoid_group,
                display_name=team.display_name,
                player1_cellphone=team.player1_cellphone,
                player1_email=team.player1_email,
                player2_cellphone=team.player2_cellphone,
                player2_email=team.player2_email,
                p1_cell=team.p1_cell,
                p1_email=team.p1_email,
                p2_cell=team.p2_cell,
                p2_email=team.p2_email,
                is_defaulted=team.is_defaulted,
                notes=team.notes,
                created_at=team.created_at,
            )
            session.add(cloned)
            session.flush()
            team_id_map[team.id] = cloned.id  # type: ignore[index]

        for edge in source_avoid_edges:
            mapped_event_id = event_id_map.get(edge.event_id)
            mapped_a = team_id_map.get(edge.team_id_a)
            mapped_b = team_id_map.get(edge.team_id_b)
            if mapped_event_id is None or mapped_a is None or mapped_b is None:
                continue
            session.add(
                TeamAvoidEdge(
                    event_id=mapped_event_id,
                    team_id_a=min(mapped_a, mapped_b),
                    team_id_b=max(mapped_a, mapped_b),
                    reason=edge.reason,
                    created_at=edge.created_at,
                )
            )

        # 4) Copy player/contact graph used by SMS/player targeting.
        player_id_map: dict[int, int] = {}
        for player in source_players:
            if player.id is None:
                continue
            cloned = Player(
                tournament_id=new_tournament.id,  # type: ignore[arg-type]
                full_name=player.full_name,
                display_name=player.display_name,
                phone_e164=player.phone_e164,
                email=player.email,
                sms_consent_status=player.sms_consent_status,
                sms_consent_source=player.sms_consent_source,
                sms_consent_updated_at=player.sms_consent_updated_at,
                sms_consented_at=player.sms_consented_at,
                sms_opted_out_at=player.sms_opted_out_at,
                created_at=player.created_at,
                updated_at=player.updated_at,
            )
            session.add(cloned)
            session.flush()
            player_id_map[player.id] = cloned.id  # type: ignore[index]

        for link in source_team_players:
            mapped_team_id = team_id_map.get(link.team_id)
            mapped_player_id = player_id_map.get(link.player_id)
            if mapped_team_id is None or mapped_player_id is None:
                continue
            session.add(
                TeamPlayer(
                    team_id=mapped_team_id,
                    player_id=mapped_player_id,
                    lineup_slot=link.lineup_slot,
                    role=link.role,
                    is_primary_contact=link.is_primary_contact,
                    created_at=link.created_at,
                    updated_at=link.updated_at,
                )
            )

        # 5) Copy schedule graph (versions -> slots/matches -> assignments/locks).
        version_id_map: dict[int, int] = {}
        for version in source_versions:
            if version.id is None:
                continue
            cloned = ScheduleVersion(
                tournament_id=new_tournament.id,  # type: ignore[arg-type]
                version_number=version.version_number,
                status=version.status,
                created_at=version.created_at,
                created_by=version.created_by,
                notes=version.notes,
                finalized_at=version.finalized_at,
                finalized_checksum=version.finalized_checksum,
            )
            session.add(cloned)
            session.flush()
            version_id_map[version.id] = cloned.id  # type: ignore[index]

        slot_id_map: dict[int, int] = {}
        for slot in source_slots:
            if slot.id is None:
                continue
            mapped_version_id = version_id_map.get(slot.schedule_version_id)
            if mapped_version_id is None:
                continue
            cloned = ScheduleSlot(
                tournament_id=new_tournament.id,  # type: ignore[arg-type]
                schedule_version_id=mapped_version_id,
                day_date=slot.day_date,
                start_time=slot.start_time,
                end_time=slot.end_time,
                court_number=slot.court_number,
                court_label=slot.court_label,
                block_minutes=slot.block_minutes,
                label=slot.label,
                is_active=slot.is_active,
            )
            session.add(cloned)
            session.flush()
            slot_id_map[slot.id] = cloned.id  # type: ignore[index]

        match_id_map: dict[int, int] = {}
        pending_match_source_links: List[tuple[Match, Optional[int], Optional[int]]] = []
        for match in source_matches:
            if match.id is None:
                continue
            mapped_event_id = event_id_map.get(match.event_id)
            mapped_version_id = version_id_map.get(match.schedule_version_id)
            if mapped_event_id is None or mapped_version_id is None:
                continue
            cloned = Match(
                tournament_id=new_tournament.id,  # type: ignore[arg-type]
                event_id=mapped_event_id,
                schedule_version_id=mapped_version_id,
                match_code=match.match_code,
                match_type=match.match_type,
                round_number=match.round_number,
                round_index=match.round_index,
                sequence_in_round=match.sequence_in_round,
                duration_minutes=match.duration_minutes,
                consolation_tier=match.consolation_tier,
                placement_type=match.placement_type,
                team_a_id=team_id_map.get(match.team_a_id) if match.team_a_id else None,
                team_b_id=team_id_map.get(match.team_b_id) if match.team_b_id else None,
                placeholder_side_a=match.placeholder_side_a,
                placeholder_side_b=match.placeholder_side_b,
                preferred_day=match.preferred_day,
                source_match_a_id=None,
                source_match_b_id=None,
                source_a_role=match.source_a_role,
                source_b_role=match.source_b_role,
                status=match.status,
                created_at=match.created_at,
                runtime_status=match.runtime_status,
                score_json=match.score_json,
                winner_team_id=team_id_map.get(match.winner_team_id) if match.winner_team_id else None,
                started_at=match.started_at,
                completed_at=match.completed_at,
            )
            session.add(cloned)
            session.flush()
            match_id_map[match.id] = cloned.id  # type: ignore[index]
            pending_match_source_links.append((cloned, match.source_match_a_id, match.source_match_b_id))

        for cloned_match, old_a_id, old_b_id in pending_match_source_links:
            cloned_match.source_match_a_id = match_id_map.get(old_a_id) if old_a_id else None
            cloned_match.source_match_b_id = match_id_map.get(old_b_id) if old_b_id else None
            session.add(cloned_match)

        for assignment in source_assignments:
            mapped_version_id = version_id_map.get(assignment.schedule_version_id)
            mapped_match_id = match_id_map.get(assignment.match_id)
            mapped_slot_id = slot_id_map.get(assignment.slot_id)
            if mapped_version_id is None or mapped_match_id is None or mapped_slot_id is None:
                continue
            session.add(
                MatchAssignment(
                    schedule_version_id=mapped_version_id,
                    match_id=mapped_match_id,
                    slot_id=mapped_slot_id,
                    assigned_at=assignment.assigned_at,
                    assigned_by=assignment.assigned_by,
                    locked=assignment.locked,
                )
            )

        for lock in source_match_locks:
            mapped_version_id = version_id_map.get(lock.schedule_version_id)
            mapped_match_id = match_id_map.get(lock.match_id)
            mapped_slot_id = slot_id_map.get(lock.slot_id)
            if mapped_version_id is None or mapped_match_id is None or mapped_slot_id is None:
                continue
            session.add(
                MatchLock(
                    schedule_version_id=mapped_version_id,
                    match_id=mapped_match_id,
                    slot_id=mapped_slot_id,
                    created_at=lock.created_at,
                    created_by=lock.created_by,
                )
            )

        for lock in source_slot_locks:
            mapped_version_id = version_id_map.get(lock.schedule_version_id)
            mapped_slot_id = slot_id_map.get(lock.slot_id)
            if mapped_version_id is None or mapped_slot_id is None:
                continue
            session.add(
                SlotLock(
                    schedule_version_id=mapped_version_id,
                    slot_id=mapped_slot_id,
                    status=lock.status,
                    created_at=lock.created_at,
                )
            )

        for run in source_policy_runs:
            mapped_version_id = version_id_map.get(run.schedule_version_id)
            if mapped_version_id is None:
                continue
            session.add(
                PolicyRun(
                    tournament_id=new_tournament.id,  # type: ignore[arg-type]
                    schedule_version_id=mapped_version_id,
                    day_date=run.day_date,
                    policy_version=run.policy_version,
                    created_at=run.created_at,
                    input_hash=run.input_hash,
                    output_hash=run.output_hash,
                    ok=run.ok,
                    total_assigned=run.total_assigned,
                    total_failed=run.total_failed,
                    total_reserved_spares=run.total_reserved_spares,
                    duration_ms=run.duration_ms,
                    snapshot_json=run.snapshot_json,
                )
            )

        # 6) Copy desk/UI state and SMS config artifacts.
        for row in source_court_state:
            session.add(
                TournamentCourtState(
                    tournament_id=new_tournament.id,  # type: ignore[arg-type]
                    court_label=row.court_label,
                    is_closed=row.is_closed,
                    note=row.note,
                    updated_at=row.updated_at,
                )
            )

        if source_sms_settings:
            session.add(
                TournamentSmsSettings(
                    tournament_id=new_tournament.id,  # type: ignore[arg-type]
                    auto_first_match=source_sms_settings.auto_first_match,
                    auto_post_match_next=source_sms_settings.auto_post_match_next,
                    auto_on_deck=source_sms_settings.auto_on_deck,
                    auto_up_next=source_sms_settings.auto_up_next,
                    auto_court_change=source_sms_settings.auto_court_change,
                    test_mode=source_sms_settings.test_mode,
                    test_allowlist=source_sms_settings.test_allowlist,
                    player_contacts_only=source_sms_settings.player_contacts_only,
                    created_at=source_sms_settings.created_at,
                    updated_at=source_sms_settings.updated_at,
                )
            )

        for template in source_sms_templates:
            session.add(
                SmsTemplate(
                    tournament_id=new_tournament.id,  # type: ignore[arg-type]
                    message_type=template.message_type,
                    template_body=template.template_body,
                    is_active=template.is_active,
                    created_at=template.created_at,
                    updated_at=template.updated_at,
                )
            )

        # Preserve the source tournament's public version pointer if possible.
        source_public_version_id = source_tournament.public_schedule_version_id
        if source_public_version_id is not None:
            new_tournament.public_schedule_version_id = version_id_map.get(source_public_version_id)
            session.add(new_tournament)

        session.commit()
        session.refresh(new_tournament)

        return new_tournament
    except HTTPException:
        raise
    except Exception as e:
        session.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to duplicate tournament: {str(e)}")


@router.delete("/tournaments/{tournament_id}", status_code=204)
def delete_tournament(tournament_id: int, session: Session = Depends(get_session)):
    """Delete a tournament and all its related data (events, days, time windows, etc.)"""
    try:
        # Check if tournament exists (without loading it into session to avoid relationship handling)
        tournament_exists = session.exec(select(func.count(Tournament.id)).where(Tournament.id == tournament_id)).one()

        if tournament_exists == 0:
            raise HTTPException(status_code=404, detail="Tournament not found")

        # Delete related records using raw SQL to completely bypass SQLAlchemy ORM
        # This prevents any relationship handling or tracking
        # Using parameterized queries to prevent SQL injection
        # Order matters: delete child records before parent records

        # 1. Delete events (and their related data will be cascade deleted if configured)
        session.execute(
            text("DELETE FROM event WHERE tournament_id = :tournament_id"), {"tournament_id": tournament_id}
        )

        # 2. Delete time windows using raw SQL
        session.execute(
            text("DELETE FROM tournamenttimewindow WHERE tournament_id = :tournament_id"),
            {"tournament_id": tournament_id},
        )

        # 3. Delete tournament days using raw SQL
        session.execute(
            text("DELETE FROM tournamentday WHERE tournament_id = :tournament_id"), {"tournament_id": tournament_id}
        )

        # 4. Delete schedule-related data (if any exists)
        # Schedule versions, slots, matches, assignments
        session.execute(
            text(
                "DELETE FROM matchassignment WHERE schedule_version_id IN (SELECT id FROM scheduleversion WHERE tournament_id = :tournament_id)"
            ),
            {"tournament_id": tournament_id},
        )
        session.execute(
            text("DELETE FROM match WHERE tournament_id = :tournament_id"), {"tournament_id": tournament_id}
        )
        session.execute(
            text("DELETE FROM scheduleslot WHERE tournament_id = :tournament_id"), {"tournament_id": tournament_id}
        )
        session.execute(
            text("DELETE FROM scheduleversion WHERE tournament_id = :tournament_id"), {"tournament_id": tournament_id}
        )

        # 5. Delete the tournament itself using raw SQL
        session.execute(text("DELETE FROM tournament WHERE id = :tournament_id"), {"tournament_id": tournament_id})

        session.commit()

        return Response(status_code=204)
    except HTTPException:
        raise
    except Exception as e:
        session.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to delete tournament: {str(e)}")
