"""Shared Combined-importer write helpers reused by RW-OS projection."""

from __future__ import annotations

from typing import Any, Iterable, Optional

from sqlmodel import Session, select

from app.models.team import Team
from app.models.team_avoid_edge import TeamAvoidEdge
from app.models.tournament_sms_settings import TournamentSmsSettings


def apply_team_contact_fields(
    team: Team,
    *,
    player1_cellphone: Optional[str] = None,
    player1_email: Optional[str] = None,
    player2_cellphone: Optional[str] = None,
    player2_email: Optional[str] = None,
    only_if_present: bool = True,
) -> int:
    """Write both Combined contact representations. Empty incoming does not clear."""
    updated = 0
    pairs = (
        ("player1_cellphone", "p1_cell", player1_cellphone),
        ("player1_email", "p1_email", player1_email),
        ("player2_cellphone", "p2_cell", player2_cellphone),
        ("player2_email", "p2_email", player2_email),
    )
    for long_name, short_name, incoming in pairs:
        value = (incoming or "").strip() or None
        if only_if_present and not value:
            continue
        if getattr(team, long_name) != value:
            setattr(team, long_name, value)
            updated += 1
        if getattr(team, short_name) != value:
            setattr(team, short_name, value)
            updated += 1
    return updated


def apply_team_contact_row(team: Team, row: dict[str, Any], *, only_if_present: bool = True) -> int:
    return apply_team_contact_fields(
        team,
        player1_cellphone=row.get("player1_cellphone") or row.get("p1_cell"),
        player1_email=row.get("player1_email") or row.get("p1_email"),
        player2_cellphone=row.get("player2_cellphone") or row.get("p2_cell"),
        player2_email=row.get("player2_email") or row.get("p2_email"),
        only_if_present=only_if_present,
    )


def add_missing_group_avoid_edges(
    session: Session,
    event_id: int,
    group_map: dict[str, list[int]],
) -> int:
    """Add-only Combined WKW edges. Never deletes existing edges."""
    created = 0
    for group_code, team_ids in group_map.items():
        unique_ids = list(dict.fromkeys(team_id for team_id in team_ids if team_id))
        if len(unique_ids) < 2:
            continue
        for i in range(len(unique_ids)):
            for j in range(i + 1, len(unique_ids)):
                a_id = min(unique_ids[i], unique_ids[j])
                b_id = max(unique_ids[i], unique_ids[j])
                existing_edge = session.exec(
                    select(TeamAvoidEdge).where(
                        TeamAvoidEdge.event_id == event_id,
                        TeamAvoidEdge.team_id_a == a_id,
                        TeamAvoidEdge.team_id_b == b_id,
                    )
                ).first()
                if existing_edge:
                    continue
                session.add(
                    TeamAvoidEdge(
                        event_id=event_id,
                        team_id_a=a_id,
                        team_id_b=b_id,
                        reason=f"group:{group_code}",
                    )
                )
                created += 1
    return created


def group_map_from_avoid_groups(assignments: Iterable[tuple[int, Optional[str]]]) -> dict[str, list[int]]:
    group_map: dict[str, list[int]] = {}
    for team_id, avoid_group in assignments:
        if not team_id or not avoid_group:
            continue
        for group_code in [part.strip().upper() for part in avoid_group.split(",")]:
            if not group_code:
                continue
            group_map.setdefault(group_code, []).append(team_id)
    return group_map


def sync_players_from_team_slots_if_enabled(session: Session, tournament_id: int, teams: list[Team]) -> None:
    settings = session.exec(
        select(TournamentSmsSettings).where(TournamentSmsSettings.tournament_id == tournament_id)
    ).first()
    if not settings or not bool(getattr(settings, "player_contacts_only", False)):
        return
    from app.routes.sms import _sync_players_and_team_links_from_team_slots

    _sync_players_and_team_links_from_team_slots(
        session=session,
        tournament_id=tournament_id,
        teams=teams,
    )
