"""Recognize registration Terms_Conditions as tournament SMS consent.

Registration stores an explicit Terms_Conditions acceptance. That acceptance
covers event updates and operational alerts, which includes a team-photo link.
It is not applied unless the snapshot carries that acceptance. A later STOP
or opted_out status is left unchanged. This module does not send messages.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Session, select

from app.models.player import Player
from app.services.canonical_teams import SnapshotPlayer, SnapshotTeam
from app.services.player_roster_sync import normalize_player_phone


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse_consent_time(raw: Optional[str]) -> Optional[datetime]:
    text = (raw or "").strip()
    if not text:
        return None
    normalized = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _evidence_for_player(player: SnapshotPlayer) -> Optional[dict]:
    if (player.sms_consent or "").strip().lower() != "opted_in":
        return None
    if (player.sms_consent_source or "registration_terms").strip() != "registration_terms":
        return None
    phone = normalize_player_phone(player.cellphone)
    if not phone:
        return None
    return {
        "phone": phone,
        "record_key": (player.sms_consent_record_key or "").strip(),
        "consented_at": _parse_consent_time(player.sms_consent_at),
    }


def registration_sms_evidence_by_phone(teams: list[SnapshotTeam]) -> dict[str, dict]:
    evidence: dict[str, dict] = {}
    for team in teams:
        for person in (team.player1, team.player2):
            item = _evidence_for_player(person)
            if item is None:
                continue
            current = evidence.get(item["phone"])
            if current is None:
                evidence[item["phone"]] = item
                continue
            if item["consented_at"] and (
                current["consented_at"] is None or item["consented_at"] < current["consented_at"]
            ):
                evidence[item["phone"]] = item
    return evidence


def _registration_evidence_for_player(
    session: Session,
    tournament_id: int,
    player: Player,
    evidence: dict[str, dict],
) -> Optional[dict]:
    """Match registration consent by the player's phone, then by that player's team slot.

    The slot lookup uses the TeamPlayer lineup. It does not copy the slot phone
    onto the player, and it does not treat a nearby teammate's number as consent.
    """
    own = normalize_player_phone(player.phone_e164)
    if own and own in evidence:
        return evidence[own]
    if player.id is None:
        return None
    from app.models.event import Event
    from app.models.team import Team
    from app.models.team_player import TeamPlayer
    from app.routes.sms import _team_slot_phone

    links = session.exec(select(TeamPlayer).where(TeamPlayer.player_id == player.id)).all()
    for link in links:
        slot = int(link.lineup_slot or 0)
        if slot not in (1, 2):
            continue
        team = session.get(Team, link.team_id)
        event = session.get(Event, team.event_id) if team is not None else None
        if team is None or event is None or event.tournament_id != tournament_id:
            continue
        phone = _team_slot_phone(team, slot)
        if phone and phone in evidence:
            return evidence[phone]
    return None


def apply_registration_sms_consent(
    session: Session,
    tournament_id: int,
    teams: list[SnapshotTeam],
    *,
    write: bool = True,
) -> dict[str, int]:
    """Upgrade unknown players only when the snapshot proves registration consent.

    write=False counts the same decisions without changing rows. STOP and
    opted_out are left unchanged. A legacy team-slot phone can match the
    registration evidence without being copied onto the player.
    """
    evidence = registration_sms_evidence_by_phone(teams)
    players = session.exec(select(Player).where(Player.tournament_id == tournament_id)).all()
    counts = {
        "players": len(players),
        "reconciled": 0,
        "already_opted_in": 0,
        "opted_out_preserved": 0,
        "unresolved": 0,
    }
    now = _utcnow()
    for player in players:
        status = (player.sms_consent_status or "unknown").strip().lower()
        if status == "opted_out":
            counts["opted_out_preserved"] += 1
            continue
        if status == "opted_in":
            counts["already_opted_in"] += 1
            continue
        item = _registration_evidence_for_player(session, tournament_id, player, evidence)
        if item is None:
            counts["unresolved"] += 1
            continue
        counts["reconciled"] += 1
        if not write:
            continue
        record_key = item["record_key"]
        player.sms_consent_status = "opted_in"
        player.sms_consent_source = f"registration_terms:{record_key}" if record_key else "registration_terms"
        player.sms_consented_at = item["consented_at"] or now
        player.sms_consent_updated_at = now
        player.updated_at = now
        session.add(player)
    if write:
        session.flush()
    return counts
