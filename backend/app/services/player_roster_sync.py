"""
Shared Team-player mutation helpers for tournament texting.

Substitutions are detected from Team name/phone slots. Player/TeamPlayer
links are always synchronized after those writes. Text List members are
never mutated here — that requires an explicit staff roster sync.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Optional

from sqlmodel import Session, select

from app.models.event import Event
from app.models.player import Player
from app.models.sms_phone_list import SmsPhoneList, SmsPhoneListMember
from app.models.team import Team
from app.models.team_player import TeamPlayer
from app.services.twilio_service import format_e164


def normalize_player_name(value: Optional[str]) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (value or "").lower()).strip()


def normalize_player_phone(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    raw = str(value).strip()
    if not raw or raw in {"—", "-", "N/A", "n/a", "none", "None"}:
        return None
    try:
        return format_e164(raw)
    except ValueError:
        digits = re.sub(r"\D", "", raw)
        return digits or None


def _team_slot_names(team: Team) -> tuple[str, str]:
    source = (getattr(team, "display_name", None) or "").strip() or (getattr(team, "name", None) or "").strip()
    if not source:
        fallback = f"Team {getattr(team, 'id', 'Unknown')}"
        return (f"{fallback} Player 1", f"{fallback} Player 2")
    if "/" in source:
        parts = [part.strip() for part in source.split("/") if part.strip()]
    elif "&" in source:
        parts = [part.strip() for part in source.split("&") if part.strip()]
    else:
        parts = [source]
    if len(parts) == 1:
        return (parts[0], f"{parts[0]} (P2)")
    return (parts[0], parts[1])


def _team_slot_phone(team: Team, slot: int) -> Optional[str]:
    if slot == 1:
        return normalize_player_phone(getattr(team, "player1_cellphone", None)) or normalize_player_phone(
            getattr(team, "p1_cell", None)
        )
    return normalize_player_phone(getattr(team, "player2_cellphone", None)) or normalize_player_phone(
        getattr(team, "p2_cell", None)
    )


@dataclass(frozen=True)
class TeamSlotSnapshot:
    slot: int
    name: str
    phone: Optional[str]


@dataclass(frozen=True)
class PlayerSubstitution:
    slot: int
    event_name: str
    old_name: str
    new_name: str
    old_phone: Optional[str]
    new_phone: Optional[str]


def snapshot_team_slots(team: Team) -> list[TeamSlotSnapshot]:
    p1_name, p2_name = _team_slot_names(team)
    return [
        TeamSlotSnapshot(slot=1, name=p1_name, phone=_team_slot_phone(team, 1)),
        TeamSlotSnapshot(slot=2, name=p2_name, phone=_team_slot_phone(team, 2)),
    ]


def detect_slot_substitutions(
    before: Iterable[TeamSlotSnapshot],
    after: Iterable[TeamSlotSnapshot],
    *,
    event_name: str,
) -> list[PlayerSubstitution]:
    before_by_slot = {item.slot: item for item in before}
    substitutions: list[PlayerSubstitution] = []
    for item in after:
        previous = before_by_slot.get(item.slot)
        if previous is None:
            continue
        name_changed = normalize_player_name(previous.name) != normalize_player_name(item.name)
        phone_changed = (previous.phone or "") != (item.phone or "")
        if not name_changed and not phone_changed:
            continue
        substitutions.append(
            PlayerSubstitution(
                slot=item.slot,
                event_name=event_name,
                old_name=previous.name,
                new_name=item.name,
                old_phone=previous.phone,
                new_phone=item.phone,
            )
        )
    return substitutions


PLAYER_SYNC_MUTATION_KEYS = (
    "players_created",
    "players_updated",
    "links_created",
    "links_updated",
    "links_removed",
)


def player_sync_has_changes(stats: dict[str, int]) -> bool:
    return any(int(stats.get(key, 0) or 0) for key in PLAYER_SYNC_MUTATION_KEYS)


def build_player_sync_staff_message(stats: dict[str, int]) -> str:
    slots_checked = int(stats.get("slots_checked", 0) or 0)
    players_created = int(stats.get("players_created", 0) or 0)
    already_correct = int(stats.get("already_correct", 0) or 0)
    links_changed = (
        int(stats.get("links_created", 0) or 0)
        + int(stats.get("links_updated", 0) or 0)
        + int(stats.get("links_removed", 0) or 0)
    )
    player_word = "player" if players_created == 1 else "players"
    link_word = "link" if links_changed == 1 else "links"
    return (
        "Player contacts synchronized\n\n"
        f"{slots_checked} team player slots checked\n"
        f"{links_changed} player {link_word} updated\n"
        f"{players_created} new {player_word} created\n"
        f"{already_correct} already correct\n\n"
        "No text messages were sent."
    )


def sync_player_links_for_tournament(
    session: Session,
    tournament_id: int,
    teams: Optional[list[Team]] = None,
) -> dict[str, int]:
    """Always refresh TeamPlayer → Player from current Team slots."""
    from app.routes.sms import _sync_players_and_team_links_from_team_slots

    return _sync_players_and_team_links_from_team_slots(
        session=session,
        tournament_id=tournament_id,
        teams=teams,
    )


def active_tournament_player_ids(session: Session, tournament_id: int) -> set[int]:
    event_ids = [event.id for event in session.exec(select(Event).where(Event.tournament_id == tournament_id)).all()]
    if not event_ids:
        return set()
    team_ids = [
        team.id
        for team in session.exec(select(Team).where(Team.event_id.in_(event_ids))).all()  # type: ignore[arg-type]
        if team.id is not None
    ]
    if not team_ids:
        return set()
    links = session.exec(select(TeamPlayer).where(TeamPlayer.team_id.in_(team_ids))).all()  # type: ignore[arg-type]
    return {link.player_id for link in links if link.player_id is not None}


def current_roster_contacts(session: Session, tournament_id: int) -> list[dict[str, Optional[str]]]:
    events = session.exec(select(Event).where(Event.tournament_id == tournament_id)).all()
    event_map = {event.id: event for event in events if event.id is not None}
    if not event_map:
        return []
    teams = session.exec(select(Team).where(Team.event_id.in_(list(event_map.keys())))).all()  # type: ignore[arg-type]
    contacts: list[dict[str, Optional[str]]] = []
    seen: set[str] = set()
    for team in teams:
        for slot_snap in snapshot_team_slots(team):
            if not slot_snap.phone or slot_snap.phone in seen:
                continue
            seen.add(slot_snap.phone)
            event = event_map.get(team.event_id)
            contacts.append(
                {
                    "name": slot_snap.name,
                    "phone": slot_snap.phone,
                    "event_name": event.name if event else None,
                }
            )
    return contacts


def build_substitution_staff_message(
    substitutions: list[PlayerSubstitution],
    *,
    text_list_sync_required: bool = True,
) -> Optional[str]:
    if not substitutions:
        return None
    replacements = [f"{item.new_name} replaced {item.old_name} on {item.event_name}" for item in substitutions]
    if len(replacements) == 1:
        body = f"Player updated\n\n{replacements[0]}.\nTournament SMS contact updated."
    else:
        body = (
            "Player updated\n\n" + " ".join(f"{part}." for part in replacements) + "\nTournament SMS contact updated."
        )
    if text_list_sync_required:
        body += "\n\nText List has not been changed.\nSync the Text List with the current tournament roster if needed."
    return body


def preview_text_list_roster_sync(
    session: Session,
    tournament_id: int,
    phone_list_id: int,
) -> dict:
    phone_list = session.get(SmsPhoneList, phone_list_id)
    if not phone_list or phone_list.tournament_id != tournament_id:
        raise ValueError("Phone list not found")

    members = session.exec(
        select(SmsPhoneListMember)
        .where(SmsPhoneListMember.phone_list_id == phone_list_id)
        .order_by(SmsPhoneListMember.id.asc())
    ).all()
    roster = current_roster_contacts(session, tournament_id)
    roster_by_phone = {row["phone"]: row for row in roster if row.get("phone")}
    member_by_phone: dict[str, SmsPhoneListMember] = {}
    for member in members:
        phone = normalize_player_phone(member.phone_number)
        if phone and phone not in member_by_phone:
            member_by_phone[phone] = member

    active_ids = active_tournament_player_ids(session, tournament_id)
    former_phones: set[str] = set()
    players = session.exec(select(Player).where(Player.tournament_id == tournament_id)).all()
    for player in players:
        phone = normalize_player_phone(player.phone_e164)
        if not phone or player.id in active_ids:
            continue
        former_phones.add(phone)

    add_rows = []
    for phone, row in roster_by_phone.items():
        if phone not in member_by_phone:
            add_rows.append({"name": row["name"], "phone": phone, "event_name": row.get("event_name")})

    remove_rows = []
    for phone, member in member_by_phone.items():
        if phone in roster_by_phone:
            continue
        if phone not in former_phones:
            continue
        remove_rows.append(
            {
                "name": member.raw_name or phone,
                "phone": phone,
                "member_id": member.id,
            }
        )

    unchanged_count = len(members) - len(remove_rows)
    return {
        "phone_list_id": phone_list.id,
        "phone_list_name": phone_list.name,
        "add": add_rows,
        "remove": remove_rows,
        "unchanged_count": max(unchanged_count, 0),
    }


def apply_text_list_roster_sync(
    session: Session,
    tournament_id: int,
    phone_list_id: int,
) -> dict:
    preview = preview_text_list_roster_sync(session, tournament_id, phone_list_id)
    for row in preview["remove"]:
        member = session.get(SmsPhoneListMember, row["member_id"])
        if member and member.phone_list_id == phone_list_id:
            session.delete(member)
    for row in preview["add"]:
        session.add(
            SmsPhoneListMember(
                phone_list_id=phone_list_id,
                raw_name=row["name"],
                phone_number=row["phone"],
            )
        )
    phone_list = session.get(SmsPhoneList, phone_list_id)
    if phone_list:
        from datetime import datetime, timezone

        phone_list.updated_at = datetime.now(timezone.utc)
        session.add(phone_list)
    session.commit()
    return preview
