"""Read-only next-match projection for the score drawer.

The projection uses the same winner and loser feed as draw advancement, and the
same remaining scheduled matches for round robin. It does not write.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, time
from typing import Optional

from sqlmodel import Session, select

from app.models.match import Match
from app.models.match_assignment import MatchAssignment
from app.models.player import Player
from app.models.schedule_slot import ScheduleSlot
from app.models.team import Team
from app.models.team_player import TeamPlayer
from app.services.advancement_service import ROLE_LOSER, ROLE_WINNER, _infer_role_from_bracket
from app.services.score_parser import scoring_mode_for_match_type


def project_next_matches(session: Session, match: Match, winner_team_id: int) -> dict:
    if winner_team_id not in (match.team_a_id, match.team_b_id):
        return {"cards": [], "preview_key": "", "format_label": _format_label(match)}
    loser_team_id = match.team_b_id if winner_team_id == match.team_a_id else match.team_a_id
    version_id = match.schedule_version_id
    matches = session.exec(select(Match).where(Match.schedule_version_id == version_id)).all()
    assignments = session.exec(
        select(MatchAssignment).where(MatchAssignment.schedule_version_id == version_id)
    ).all()
    assignment_by_match = {row.match_id: row for row in assignments if row.match_id is not None}
    slot_ids = [row.slot_id for row in assignments if row.slot_id is not None]
    slots = session.exec(select(ScheduleSlot).where(ScheduleSlot.id.in_(slot_ids))).all() if slot_ids else []
    slot_by_id = {slot.id: slot for slot in slots if slot.id is not None}

    def slot_for(match_id: Optional[int]) -> Optional[ScheduleSlot]:
        assignment = assignment_by_match.get(match_id or -1)
        if not assignment:
            return None
        return slot_by_id.get(assignment.slot_id)

    teams = {
        team.id: team
        for team in session.exec(select(Team).where(Team.id.in_([winner_team_id, loser_team_id]))).all()
        if team.id is not None
    }
    players_by_team = _players_by_team(session, teams)
    other_team_ids = _other_team_ids(session, players_by_team, set(teams))

    cards = []
    for team_id, role in ((winner_team_id, "winner"), (loser_team_id, "other")):
        if team_id is None:
            continue
        team = teams.get(team_id)
        if team is None:
            continue
        draw_next = _draw_next(match, team_id, role, matches, slot_for)
        cards.extend(
            _cards_for_team(
                session,
                team,
                role,
                draw_next,
                players_by_team.get(team_id, []),
                other_team_ids,
                matches,
                slot_for,
            )
        )
    _mark_duplicate_phones(cards)
    preview_key = _preview_key(cards)
    return {"cards": cards, "preview_key": preview_key, "format_label": _format_label(match)}


def _format_label(match: Match) -> str:
    if scoring_mode_for_match_type(match.match_type) == "PRO_SET_8":
        return "8-game pro set · Tiebreak at 8–8"
    return "Best of three sets · Match tiebreak for third set"


def _players_by_team(session: Session, teams: dict[int, Team]) -> dict[int, list[dict]]:
    team_ids = list(teams)
    links = session.exec(select(TeamPlayer).where(TeamPlayer.team_id.in_(team_ids))).all() if team_ids else []
    player_ids = [link.player_id for link in links]
    players = {
        player.id: player
        for player in (session.exec(select(Player).where(Player.id.in_(player_ids))).all() if player_ids else [])
        if player.id is not None
    }
    grouped: dict[int, list[tuple[int, TeamPlayer]]] = {}
    for link in links:
        player = players.get(link.player_id)
        slot = int(link.lineup_slot or 0)
        grouped.setdefault(link.team_id, []).append((slot or 99, link, player))
    result: dict[int, list[dict]] = {}
    for team_id, team in teams.items():
        rows = []
        used_slots = set()
        for slot, link, player in sorted(grouped.get(team_id, []), key=lambda item: item[0]):
            if player is None:
                continue
            used_slots.add(slot)
            rows.append(_player_row(player, slot, team))
        for slot, phone in ((1, team.player1_cellphone or team.p1_cell), (2, team.player2_cellphone or team.p2_cell)):
            if slot in used_slots or any(row.get("lineup_slot") == slot for row in rows):
                continue
            if not phone and len(rows) >= 2:
                continue
        if not rows:
            rows = _players_from_team_name(team)
        result[team_id] = rows
    return result


def _player_row(player: Player, slot: int, team: Team) -> dict:
    phone = player.phone_e164
    if not phone and slot == 1:
        phone = team.player1_cellphone or team.p1_cell
    if not phone and slot == 2:
        phone = team.player2_cellphone or team.p2_cell
    return {
        "player_id": player.id,
        "name": _player_label(player.display_name or player.full_name),
        "full_name": player.full_name,
        "phone": phone or "",
        "consent": player.sms_consent_status or "unknown",
        "lineup_slot": slot,
    }


def _players_from_team_name(team: Team) -> list[dict]:
    label = team.display_name or team.name or "Team"
    parts = [part.strip() for part in label.replace(" / ", "/").split("/") if part.strip()]
    phones = [team.player1_cellphone or team.p1_cell or "", team.player2_cellphone or team.p2_cell or ""]
    rows = []
    for index, part in enumerate(parts[:2]):
        rows.append(
            {
                "player_id": None,
                "name": _player_label(part),
                "full_name": part,
                "phone": phones[index] if index < len(phones) else "",
                "consent": "unknown",
                "lineup_slot": index + 1,
                "team_phone_only": True,
            }
        )
    return rows


def _other_team_ids(session: Session, players_by_team: dict[int, list[dict]], current_team_ids: set[int]) -> dict[int, list[int]]:
    player_ids = [row["player_id"] for rows in players_by_team.values() for row in rows if row.get("player_id")]
    if not player_ids:
        return {}
    links = session.exec(select(TeamPlayer).where(TeamPlayer.player_id.in_(player_ids))).all()
    found: dict[int, list[int]] = {}
    for link in links:
        if link.team_id in current_team_ids:
            continue
        found.setdefault(link.player_id, []).append(link.team_id)
    return found


def _draw_next(match: Match, team_id: int, role: str, matches: list[Match], slot_for) -> Optional[tuple[Match, Optional[ScheduleSlot], Optional[str]]]:
    wanted = ROLE_WINNER if role == "winner" else ROLE_LOSER
    current_slot = slot_for(match.id)
    if (match.match_type or "").upper() == "RR":
        return _earliest_assigned(team_id, matches, slot_for, exclude_id=match.id, event_id=match.event_id, after_slot=current_slot)

    feeds = []
    for down in matches:
        if down.id == match.id:
            continue
        for slot_name in ("A", "B"):
            source_id = down.source_match_a_id if slot_name == "A" else down.source_match_b_id
            source_role = down.source_a_role if slot_name == "A" else down.source_b_role
            if source_id != match.id:
                continue
            resolved = (source_role or "").upper()
            if resolved not in (ROLE_WINNER, ROLE_LOSER) and (match.match_type or "").upper() == "WF":
                resolved = _infer_role_from_bracket(down.match_code)
            if resolved != wanted:
                continue
            current = down.team_a_id if slot_name == "A" else down.team_b_id
            if current not in (None, team_id):
                continue
            slot = slot_for(down.id)
            feeds.append((_sort_key(slot), down, slot, slot_name))
    if not feeds and (match.match_type or "").upper() == "WF" and match.match_code:
        for down in matches:
            for slot_name, placeholder in (("A", down.placeholder_side_a), ("B", down.placeholder_side_b)):
                if placeholder != match.match_code:
                    continue
                if _infer_role_from_bracket(down.match_code) != wanted:
                    continue
                current = down.team_a_id if slot_name == "A" else down.team_b_id
                if current not in (None, team_id):
                    continue
                slot = slot_for(down.id)
                feeds.append((_sort_key(slot), down, slot, slot_name))
    if feeds:
        feeds.sort(key=lambda row: row[0])
        _key, down, slot, slot_name = feeds[0]
        other_id = down.team_b_id if slot_name == "A" else down.team_a_id
        return down, slot, None if other_id in (None, team_id) else str(other_id)
    return _earliest_assigned(team_id, matches, slot_for, exclude_id=match.id, event_id=match.event_id, after_slot=current_slot)


def _earliest_assigned(team_id, matches, slot_for, *, exclude_id, event_id=None, after_slot=None):
    rows = []
    for down in matches:
        if down.id == exclude_id:
            continue
        if event_id is not None and down.event_id != event_id:
            continue
        if team_id not in (down.team_a_id, down.team_b_id):
            continue
        if (down.runtime_status or "SCHEDULED").upper() == "FINAL":
            continue
        slot = slot_for(down.id)
        if not slot:
            continue
        if after_slot is not None and _sort_key(slot) < _sort_key(after_slot):
            continue
        other_id = down.team_b_id if down.team_a_id == team_id else down.team_a_id
        rows.append((_sort_key(slot), down, slot, None if other_id in (None, team_id) else str(other_id)))
    if not rows:
        return None
    rows.sort(key=lambda row: row[0])
    _key, down, slot, other = rows[0]
    return down, slot, other


def _cards_for_team(session, team, role, draw_next, players, other_team_ids, matches, slot_for):
    team_label = _short_team_name(team)
    groups: dict[str, dict] = {}

    def add_player(player, assignment):
        key = assignment["group_key"]
        card = groups.get(key)
        if card is None:
            card = {**assignment, "players": [], "team_id": team.id, "team_label": team_label, "role": role}
            groups[key] = card
        card["players"].append(_recipient(player, {**assignment, "team_label": team_label}))

    draw_assignment = _assignment_from_next(session, draw_next, kind="draw")
    if not players:
        card = {**draw_assignment, "players": [], "team_id": team.id, "team_label": team_label, "role": role}
        return [card]

    for player in players:
        personal = _personal_next(player, other_team_ids, matches, slot_for, draw_next)
        if personal is not None:
            add_player(player, _assignment_from_next(session, personal, kind="player"))
        elif draw_next is not None:
            add_player(player, draw_assignment)
        elif player.get("player_id"):
            add_player(player, _complete_assignment("tournament_complete"))
        else:
            add_player(player, _complete_assignment("draw_complete"))
    return list(groups.values())


def _personal_next(player, other_team_ids, matches, slot_for, draw_next):
    player_id = player.get("player_id")
    if not player_id:
        return None
    best = None
    for team_id in other_team_ids.get(player_id, []):
        found = _earliest_assigned(team_id, matches, slot_for, exclude_id=None, event_id=None)
        if found is None:
            continue
        if best is None or _sort_key(found[1]) < _sort_key(best[1]):
            best = found
    if best is None:
        return None
    if draw_next is None:
        return best
    if _sort_key(best[1]) < _sort_key(draw_next[1]):
        return best
    return None


def _assignment_from_next(session, found, *, kind: str) -> dict:
    if found is None:
        return _complete_assignment("draw_complete")
    down, slot, other_token = found
    opponent = None
    if other_token and other_token.isdigit():
        other = session.get(Team, int(other_token))
        opponent = _short_team_name(other) if other else None
    pending_schedule = slot is None
    return {
        "group_key": f"match:{down.id}",
        "kind": "next",
        "next_match_id": down.id,
        "date_label": _date_label(slot.day_date) if slot else None,
        "time_label": _time_label(slot.start_time) if slot else None,
        "court_label": _court_label(slot) if slot else None,
        "opponent_label": opponent,
        "opponent_pending": opponent is None,
        "schedule_pending": pending_schedule,
        "status_label": None,
    }


def _complete_assignment(kind: str) -> dict:
    label = "Draw Complete — No Further Matches" if kind == "draw_complete" else "Tournament Complete"
    return {
        "group_key": kind,
        "kind": kind,
        "next_match_id": None,
        "date_label": None,
        "time_label": None,
        "court_label": None,
        "opponent_label": None,
        "opponent_pending": False,
        "schedule_pending": False,
        "status_label": label,
    }


def _mark_duplicate_phones(cards: list[dict]) -> None:
    seen: set[str] = set()
    for card in cards:
        for player in card.get("players") or []:
            phone = (player.get("phone") or "").replace(" ", "")
            if not phone or not player.get("eligible"):
                continue
            if phone in seen:
                player["eligible"] = False
                player["ineligible_reason"] = "Duplicate cellphone"
                player["message"] = ""
            else:
                seen.add(phone)


def _recipient(player: dict, assignment: dict) -> dict:
    phone = (player.get("phone") or "").strip()
    consent = player.get("consent") or "unknown"
    reason = None
    eligible = True
    if assignment["kind"] != "next":
        eligible = False
        reason = None
    elif assignment.get("schedule_pending") or not assignment.get("time_label") or not assignment.get("court_label"):
        eligible = False
        reason = "Next court or time is not confirmed"
    elif not phone:
        eligible = False
        reason = "No cellphone on file"
    elif consent == "opted_out":
        eligible = False
        reason = "Opted out of texts"
    elif player.get("player_id") is None:
        eligible = False
        reason = "No player record for this cellphone"
    message = _message(player, assignment) if eligible else ""
    return {
        "player_id": player.get("player_id"),
        "name": player.get("name") or "Player",
        "phone": phone,
        "eligible": eligible,
        "ineligible_reason": reason,
        "message": message,
    }


def _message(player: dict, assignment: dict) -> str:
    lines = [
        "Racquet War — Next Match",
        "",
        assignment.get("team_label") or player.get("name") or "Player",
        "",
        assignment.get("date_label") or "",
        f"{assignment.get('time_label')} · {assignment.get('court_label')}",
    ]
    if assignment.get("opponent_label"):
        lines.extend(["", f"Opponents: {assignment['opponent_label']}"])
    return "\n".join(line for line in lines if line is not None)


def _preview_key(cards: list[dict]) -> str:
    material = []
    for card in cards:
        material.append(
            {
                "team_id": card.get("team_id"),
                "role": card.get("role"),
                "kind": card.get("kind"),
                "next_match_id": card.get("next_match_id"),
                "date": card.get("date_label"),
                "time": card.get("time_label"),
                "court": card.get("court_label"),
                "opponent": card.get("opponent_label"),
                "players": sorted(player.get("player_id") or 0 for player in card.get("players") or []),
            }
        )
    raw = json.dumps(material, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _short_team_name(team: Optional[Team]) -> str:
    if team is None:
        return ""
    label = team.display_name or team.name or ""
    if "/" not in label:
        return label
    parts = [part.strip() for part in label.replace(" / ", "/").split("/") if part.strip()]
    return " / ".join(_first_name(part) for part in parts[:2]) or label


def _first_name(value: str) -> str:
    token = (value or "").strip().split(" ")[0]
    return token or value


def _player_label(value: str) -> str:
    text = (value or "").strip()
    parts = text.split()
    if len(parts) >= 3:
        return text
    return parts[0] if parts else text


def _date_label(day: date) -> str:
    return f"{day.strftime('%A, %b')} {day.day}"


def _time_label(value) -> str:
    if isinstance(value, str):
        hour, minute = [int(part) for part in value.split(":")[:2]]
    elif isinstance(value, time):
        hour, minute = value.hour, value.minute
    else:
        return ""
    suffix = "AM" if hour < 12 else "PM"
    hour12 = hour % 12 or 12
    return f"{hour12}:{minute:02d} {suffix}"


def _court_label(slot: ScheduleSlot) -> str:
    label = slot.court_label or str(slot.court_number)
    if str(label).lower().startswith("court"):
        return str(label)
    return f"Court {label}"


def _sort_key(slot: Optional[ScheduleSlot]):
    if slot is None:
        return (date.max, time.max, 999, 999)
    return (slot.day_date, slot.start_time, slot.court_number or 0, slot.id or 0)
