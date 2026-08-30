"""Project an approved RW-OS snapshot onto live Team / WKW / towel rows."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from sqlmodel import Session, select

from app.models.event import Event, EventCategory
from app.models.team import Team
from app.models.team_avoid_edge import TeamAvoidEdge
from app.models.temporary_player_lookup import TemporaryPlayerLookup
from app.models.tournament_import import TournamentDrawPlan, TournamentImport
from app.services.canonical_teams import SnapshotPlayer, SnapshotTeam, sort_teams_for_planning
from app.services.combined_roster_writes import (
    add_missing_group_avoid_edges,
    apply_team_contact_fields,
    group_map_from_avoid_groups,
    sync_players_from_team_slots_if_enabled,
)
from app.services.rw_os_import import parse_teams, snapshot_hash
from app.services.structure_events import event_category_for_draw_kind, event_protection_reason

RWOS_LOOKUP_SOURCE = "rwos-import"

CONFLICT_STRUCTURAL_SNAPSHOT = "structural_snapshot_changed_after_approval"
CONFLICT_TEAM_WOULD_MOVE = "projected_team_would_move_bracket"
CONFLICT_DRAW_PROTECTION = "live_draw_protection_blocks_structural_change"


@dataclass
class RosterProjectionResult:
    created_events: int = 0
    created_teams: int = 0
    created_towel_rows: int = 0
    created_wkw_edges: int = 0
    updated_teams: int = 0
    updated_contact_fields: int = 0
    updated_towel_rows: int = 0
    warnings: list[dict[str, Any]] = field(default_factory=list)
    conflicts: list[dict[str, Any]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.conflicts

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "created": {
                "events": self.created_events,
                "teams": self.created_teams,
                "towelRows": self.created_towel_rows,
                "wkwEdges": self.created_wkw_edges,
            },
            "updated": {
                "teams": self.updated_teams,
                "contactFields": self.updated_contact_fields,
                "towelRows": self.updated_towel_rows,
            },
            "warnings": list(self.warnings),
            "conflicts": list(self.conflicts),
        }


def current_snapshot_hash(import_row: TournamentImport) -> str:
    return snapshot_hash(
        {
            "tournamentId": import_row.source_tournament_id,
            "updatedAt": import_row.source_updated_at,
            "version": import_row.source_version,
            "teams": json.loads(import_row.snapshot_json or "[]"),
            "waitlistTeams": json.loads(import_row.waitlist_json or "[]"),
        }
    )


def _warning(code: str, message: str, **extra: Any) -> dict[str, Any]:
    return {"code": code, "message": message, **extra}


def _conflict(code: str, message: str, **extra: Any) -> dict[str, Any]:
    return {"code": code, "message": message, **extra}


def _player_name(player: SnapshotPlayer, fallback: str) -> str:
    return (player.name or "").strip() or fallback


def _team_full_name(team: SnapshotTeam) -> str:
    if team.full_name:
        return team.full_name
    left = _player_name(team.player1, "")
    right = _player_name(team.player2, "")
    if left and right:
        return f"{left} / {right}"
    return left or right or team.team_key


def _team_display_name(team: SnapshotTeam, full_name: str) -> str:
    if team.display_name:
        return team.display_name
    from app.routes.teams import _make_display_name

    return _make_display_name(full_name)


def _team_rating(team: SnapshotTeam) -> Optional[float]:
    if team.level is not None:
        return team.level
    return team.team_rating


def _unique_team_name(
    session: Session, event_id: int, desired: str, source_team_key: str, team_id: Optional[int]
) -> str:
    existing = session.exec(select(Team).where(Team.event_id == event_id, Team.name == desired)).first()
    if existing is None or existing.id == team_id:
        return desired
    suffix = f" ({source_team_key})"
    candidate = f"{desired}{suffix}"
    clash = session.exec(select(Team).where(Team.event_id == event_id, Team.name == candidate)).first()
    if clash is None or clash.id == team_id:
        return candidate
    return f"{desired} #{source_team_key}"


def _seed_available(session: Session, event_id: int, seed: int, team_id: Optional[int]) -> bool:
    existing = session.exec(select(Team).where(Team.event_id == event_id, Team.seed == seed)).first()
    return existing is None or existing.id == team_id


def _release_projected_seeds(session: Session, tournament_id: int) -> None:
    """Park source-backed seed/name keys before rematch so UNIQUE (event_id, seed|name) cannot collide."""
    rows = session.exec(
        select(Team).join(Event).where(Event.tournament_id == tournament_id, Team.source_team_key.is_not(None))
    ).all()
    touched = False
    for team in rows:
        dirty = False
        if team.seed is not None:
            team.seed = None
            dirty = True
        parked_name = f"__rwos_move_{team.id}"
        if team.id and team.name != parked_name:
            team.name = parked_name
            dirty = True
        if dirty:
            session.add(team)
            touched = True
    if touched:
        session.flush()


def _find_projected_team(session: Session, tournament_id: int, source_team_key: str) -> Optional[Team]:
    return session.exec(
        select(Team).join(Event).where(Event.tournament_id == tournament_id, Team.source_team_key == source_team_key)
    ).first()


def _event_by_route(events: list[Event], draw_kind: str, label: str) -> Optional[Event]:
    category = event_category_for_draw_kind(draw_kind)
    if category is None:
        return None
    wanted = (category.value, label.strip())
    for event in events:
        event_category = event.category.value if isinstance(event.category, EventCategory) else str(event.category)
        if (event_category, event.name) == wanted:
            return event
    return None


def _brackets_from_plan(plan: TournamentDrawPlan) -> list[dict[str, Any]]:
    parsed = json.loads(plan.brackets_json or "[]")
    if not isinstance(parsed, list):
        return []
    return [item for item in parsed if isinstance(item, dict)]


def route_snapshot_teams(
    teams: list[SnapshotTeam],
    brackets: list[dict[str, Any]],
) -> list[tuple[SnapshotTeam, dict[str, Any], int]]:
    ordered = sort_teams_for_planning(teams)
    routed: list[tuple[SnapshotTeam, dict[str, Any], int]] = []
    for rank, team in enumerate(ordered, start=1):
        bracket = next(
            (item for item in brackets if int(item.get("rankStart") or 0) <= rank <= int(item.get("rankEnd") or 0)),
            None,
        )
        if bracket:
            routed.append((team, bracket, rank))
    return routed


def _collect_operational_warnings(team: SnapshotTeam, warnings: list[dict[str, Any]]) -> None:
    for slot, player in ((1, team.player1), (2, team.player2)):
        if not (player.cellphone or "").strip():
            warnings.append(
                _warning(
                    f"missing_player{slot}_cellphone",
                    f"Team {team.team_key} is missing player {slot} cellphone.",
                    teamKey=team.team_key,
                )
            )
        if not (player.email or "").strip():
            warnings.append(
                _warning(
                    f"missing_player{slot}_email",
                    f"Team {team.team_key} is missing player {slot} email.",
                    teamKey=team.team_key,
                )
            )
        if not (player.towel_color or "").strip():
            warnings.append(
                _warning(
                    "missing_towel_color",
                    f"Team {team.team_key} player {slot} is missing a towel color.",
                    teamKey=team.team_key,
                    lineupSlot=slot,
                )
            )
        if player.identity_status == "unresolved":
            warnings.append(
                _warning(
                    "unresolved_player_identity",
                    f"Team {team.team_key} player {slot} has unresolved identity.",
                    teamKey=team.team_key,
                    lineupSlot=slot,
                )
            )
    if not (team.avoid_group or "").strip():
        warnings.append(
            _warning("missing_who_knows_who", f"Team {team.team_key} is missing Who-knows-who.", teamKey=team.team_key)
        )


def _upsert_rwos_towel_row(
    session: Session,
    tournament_id: int,
    team_key: str,
    slot: int,
    player: SnapshotPlayer,
    result: RosterProjectionResult,
) -> None:
    from app.routes.desk import _normalize_lookup_email, _normalize_lookup_name, _normalize_lookup_phone

    incoming_color = (player.towel_color or "").strip() or None
    existing = session.exec(
        select(TemporaryPlayerLookup).where(
            TemporaryPlayerLookup.tournament_id == tournament_id,
            TemporaryPlayerLookup.source == RWOS_LOOKUP_SOURCE,
            TemporaryPlayerLookup.source_team_key == team_key,
            TemporaryPlayerLookup.lineup_slot == slot,
        )
    ).first()
    if not incoming_color:
        return
    source_name = _player_name(player, f"Player {slot}")
    fields = {
        "source_name": source_name,
        "normalized_name": _normalize_lookup_name(source_name),
        "source_phone": player.cellphone,
        "normalized_phone": _normalize_lookup_phone(player.cellphone),
        "source_email": player.email,
        "normalized_email": _normalize_lookup_email(player.email),
        "towel_color": incoming_color,
        "updated_at": datetime.now(timezone.utc),
    }
    if existing:
        changed = False
        for name, value in fields.items():
            if getattr(existing, name) != value:
                setattr(existing, name, value)
                changed = True
        if changed:
            session.add(existing)
            result.updated_towel_rows += 1
        return

    lookup_rows = [
        {
            "source_name": source_name,
            "source_phone": player.cellphone,
            "source_email": player.email,
            "towel_color": incoming_color,
            "report_url": None,
        }
    ]
    from app.routes.desk import _resolve_lookup_player_ids

    resolved = _resolve_lookup_player_ids(session, tournament_id, lookup_rows)[0]
    session.add(
        TemporaryPlayerLookup(
            tournament_id=tournament_id,
            player_id=resolved.get("player_id"),
            source_name=resolved.get("source_name") or source_name,
            normalized_name=resolved.get("normalized_name") or fields["normalized_name"],
            source_phone=resolved.get("source_phone"),
            normalized_phone=resolved.get("normalized_phone"),
            source_email=resolved.get("source_email"),
            normalized_email=resolved.get("normalized_email"),
            towel_color=incoming_color,
            report_url=resolved.get("report_url"),
            source=RWOS_LOOKUP_SOURCE,
            source_team_key=team_key,
            lineup_slot=slot,
        )
    )
    result.created_towel_rows += 1


def _maybe_warn_stale_wkw(
    session: Session, event_id: int, team: Team, new_group: Optional[str], result: RosterProjectionResult
) -> None:
    new_letters = {part.strip().upper() for part in (new_group or "").split(",") if part.strip()}
    edges = session.exec(
        select(TeamAvoidEdge).where(
            TeamAvoidEdge.event_id == event_id,
            (TeamAvoidEdge.team_id_a == team.id) | (TeamAvoidEdge.team_id_b == team.id),
        )
    ).all()
    stale = False
    for edge in edges:
        reason = edge.reason or ""
        if not reason.startswith("group:"):
            continue
        letter = reason.split(":", 1)[1].strip().upper()
        if letter and letter not in new_letters:
            stale = True
            break
    if stale:
        result.warnings.append(
            _warning(
                "stale_wkw_edges_cannot_safely_delete",
                f"Team {team.source_team_key} may still have imported group edges that cannot be deleted safely.",
                teamKey=team.source_team_key,
            )
        )


def project_approved_roster(
    session: Session,
    import_row: TournamentImport,
    plans: list[TournamentDrawPlan],
    *,
    events_created: int = 0,
    operational_only: bool = False,
    allow_structural_rebuild: bool = False,
) -> RosterProjectionResult:
    result = RosterProjectionResult(created_events=events_created)
    teams = parse_teams(json.loads(import_row.snapshot_json or "[]"))
    current_hash = current_snapshot_hash(import_row)
    approved_hash = import_row.approved_source_hash
    structural_mismatch = bool(approved_hash and current_hash != approved_hash)

    if structural_mismatch and not allow_structural_rebuild:
        result.conflicts.append(
            _conflict(
                CONFLICT_STRUCTURAL_SNAPSHOT,
                "The structural snapshot changed after approval. Re-approve or rebuild before changing live bracket membership.",
                approvedSourceHash=approved_hash,
                currentSourceHash=current_hash,
            )
        )
        if not operational_only:
            return result

    events = list(session.exec(select(Event).where(Event.tournament_id == import_row.tournament_id)).all())
    if allow_structural_rebuild and not operational_only:
        _release_projected_seeds(session, import_row.tournament_id)
    touched_teams: list[Team] = []
    wkw_assignments: dict[int, list[tuple[int, Optional[str]]]] = {}

    for plan in plans:
        draw_teams = [team for team in teams if team.draw_kind == plan.draw_kind]
        routed = route_snapshot_teams(draw_teams, _brackets_from_plan(plan))
        assigned_keys = {team.team_key for team, _bracket, _rank in routed}
        for team in draw_teams:
            if team.team_key not in assigned_keys:
                result.warnings.append(
                    _warning(
                        "unassigned_planner_rank",
                        f"Team {team.team_key} is outside the approved rank range for {plan.draw_kind}.",
                        teamKey=team.team_key,
                        drawKind=plan.draw_kind,
                    )
                )

        for snapshot_team, bracket, planner_rank in routed:
            _collect_operational_warnings(snapshot_team, result.warnings)
            label = str(bracket.get("label") or "").strip()
            event = _event_by_route(events, plan.draw_kind, label)
            if event is None or event.id is None:
                result.conflicts.append(
                    _conflict(
                        "missing_event_for_bracket",
                        f"No Event exists for {plan.draw_kind} / {label}.",
                        drawKind=plan.draw_kind,
                        label=label,
                        teamKey=snapshot_team.team_key,
                    )
                )
                continue

            protection = event_protection_reason(session, event)
            existing = _find_projected_team(session, import_row.tournament_id, snapshot_team.team_key)
            in_bracket_seed = planner_rank - int(bracket.get("rankStart") or planner_rank) + 1
            full_name = _team_full_name(snapshot_team)
            display_name = _team_display_name(snapshot_team, full_name)
            rating = _team_rating(snapshot_team)
            avoid_group = snapshot_team.avoid_group

            if existing and existing.event_id != event.id:
                source_event = session.get(Event, existing.event_id)
                source_protection = event_protection_reason(session, source_event) if source_event else None
                if structural_mismatch and not allow_structural_rebuild:
                    result.conflicts.append(
                        _conflict(
                            CONFLICT_TEAM_WOULD_MOVE,
                            f"Team {snapshot_team.team_key} would move between Events after a structural snapshot change.",
                            teamKey=snapshot_team.team_key,
                            currentEventId=existing.event_id,
                            requestedEventId=event.id,
                        )
                    )
                    _apply_operational_team_updates(session, existing, snapshot_team, result, wkw_assignments)
                    touched_teams.append(existing)
                    continue
                if protection or source_protection or not allow_structural_rebuild:
                    result.conflicts.append(
                        _conflict(
                            CONFLICT_DRAW_PROTECTION if (protection or source_protection) else CONFLICT_TEAM_WOULD_MOVE,
                            f"Team {snapshot_team.team_key} would move between Events and was left in place.",
                            teamKey=snapshot_team.team_key,
                            currentEventId=existing.event_id,
                            requestedEventId=event.id,
                            reason=protection or source_protection,
                        )
                    )
                    _apply_operational_team_updates(session, existing, snapshot_team, result, wkw_assignments)
                    touched_teams.append(existing)
                    continue
                existing.seed = None
                if existing.id:
                    existing.name = f"__rwos_move_{existing.id}"
                existing.event_id = event.id

            if existing is None:
                if operational_only or (structural_mismatch and not allow_structural_rebuild):
                    continue
                if protection:
                    result.conflicts.append(
                        _conflict(
                            CONFLICT_DRAW_PROTECTION,
                            f"Cannot create Team {snapshot_team.team_key} on {event.name}: {protection}.",
                            teamKey=snapshot_team.team_key,
                            eventId=event.id,
                            reason=protection,
                        )
                    )
                    continue
                name = _unique_team_name(session, event.id, full_name, snapshot_team.team_key, None)
                seed = in_bracket_seed if _seed_available(session, event.id, in_bracket_seed, None) else None
                team = Team(
                    event_id=event.id,
                    name=name,
                    seed=seed,
                    rating=rating,
                    avoid_group=avoid_group,
                    display_name=display_name,
                    source_team_key=snapshot_team.team_key,
                    is_defaulted=False,
                )
                apply_team_contact_fields(
                    team,
                    player1_cellphone=snapshot_team.player1.cellphone,
                    player1_email=snapshot_team.player1.email,
                    player2_cellphone=snapshot_team.player2.cellphone,
                    player2_email=snapshot_team.player2.email,
                    only_if_present=True,
                )
                session.add(team)
                session.flush()
                result.created_teams += 1
                touched_teams.append(team)
                if team.id:
                    wkw_assignments.setdefault(event.id, []).append((team.id, avoid_group))
                _project_towels(session, import_row.tournament_id, snapshot_team, result)
                continue

            contact_updates = _apply_operational_team_updates(session, existing, snapshot_team, result, wkw_assignments)
            structural_blocked = bool(protection) and existing.event_id == event.id
            if (
                not operational_only
                and not (structural_mismatch and not allow_structural_rebuild)
                and not structural_blocked
            ):
                name = _unique_team_name(session, existing.event_id, full_name, snapshot_team.team_key, existing.id)
                changed = False
                if existing.name != name:
                    existing.name = name
                    changed = True
                if existing.display_name != display_name:
                    existing.display_name = display_name
                    changed = True
                if existing.rating != rating:
                    existing.rating = rating
                    changed = True
                if existing.event_id == event.id and _seed_available(session, event.id, in_bracket_seed, existing.id):
                    if existing.seed != in_bracket_seed:
                        existing.seed = in_bracket_seed
                        changed = True
                if existing.avoid_group != avoid_group:
                    _maybe_warn_stale_wkw(session, existing.event_id, existing, avoid_group, result)
                    existing.avoid_group = avoid_group
                    changed = True
                if changed or contact_updates:
                    session.add(existing)
                result.updated_teams += 1
            elif contact_updates:
                session.add(existing)
                result.updated_teams += 1
            touched_teams.append(existing)
            _project_towels(session, import_row.tournament_id, snapshot_team, result)

    for event_id, assignments in wkw_assignments.items():
        group_map = group_map_from_avoid_groups(assignments)
        try:
            result.created_wkw_edges += add_missing_group_avoid_edges(session, event_id, group_map)
        except Exception as exc:
            result.warnings.append(_warning("wkw_edge_error", f"Error creating avoid edges: {exc}"))

    sync_players_from_team_slots_if_enabled(session, import_row.tournament_id, touched_teams)
    session.commit()
    return result


def _apply_operational_team_updates(
    session: Session,
    team: Team,
    snapshot_team: SnapshotTeam,
    result: RosterProjectionResult,
    wkw_assignments: dict[int, list[tuple[int, Optional[str]]]],
) -> int:
    if team.avoid_group != snapshot_team.avoid_group:
        _maybe_warn_stale_wkw(session, team.event_id, team, snapshot_team.avoid_group, result)
        team.avoid_group = snapshot_team.avoid_group
        session.add(team)
    if team.id:
        wkw_assignments.setdefault(team.event_id, []).append((team.id, snapshot_team.avoid_group or team.avoid_group))
    updated = apply_team_contact_fields(
        team,
        player1_cellphone=snapshot_team.player1.cellphone,
        player1_email=snapshot_team.player1.email,
        player2_cellphone=snapshot_team.player2.cellphone,
        player2_email=snapshot_team.player2.email,
        only_if_present=True,
    )
    result.updated_contact_fields += updated
    return updated


def live_roster_summary(session: Session, import_row: TournamentImport) -> dict[str, Any]:
    """Current operational roster for GET/refresh. Not the last POST created/updated deltas."""
    from app.services.structure_events import (
        event_protection_reason,
        requested_event_sizes,
        serialize_structure_event,
    )

    events = list(session.exec(select(Event).where(Event.tournament_id == import_row.tournament_id)).all())
    teams = list(session.exec(select(Team).join(Event).where(Event.tournament_id == import_row.tournament_id)).all())
    towels = list(
        session.exec(
            select(TemporaryPlayerLookup).where(TemporaryPlayerLookup.tournament_id == import_row.tournament_id)
        ).all()
    )
    edges = list(
        session.exec(select(TeamAvoidEdge).join(Event).where(Event.tournament_id == import_row.tournament_id)).all()
    )
    plans = list(
        session.exec(
            select(TournamentDrawPlan).where(
                TournamentDrawPlan.import_id == import_row.id,
                TournamentDrawPlan.approved == True,  # noqa: E712
            )
        ).all()
    )
    requested = requested_event_sizes(plans, import_row.tournament_id)

    teams_by_event: dict[int, list[Team]] = {}
    for team in teams:
        teams_by_event.setdefault(team.event_id, []).append(team)

    event_payloads: list[dict[str, Any]] = []
    capacity_conflicts: list[dict[str, Any]] = []
    protection_warnings: list[dict[str, Any]] = []
    for event in events:
        event_category = event.category.value if isinstance(event.category, EventCategory) else str(event.category)
        event_teams = teams_by_event.get(event.id or 0, [])
        source_count = sum(1 for team in event_teams if team.source_team_key)
        protection = event_protection_reason(session, event)
        wanted = requested.get((event_category, event.name))
        event_payloads.append(
            serialize_structure_event(
                event,
                protectionReason=protection,
                requestedTeamCount=wanted,
                teamRowCount=len(event_teams),
                sourceTeamCount=source_count,
            )
        )
        if protection:
            protection_warnings.append(
                _warning(
                    CONFLICT_DRAW_PROTECTION,
                    f"{event.name}: {protection}.",
                    eventId=event.id,
                    reason=protection,
                )
            )
        if protection and wanted is not None and event.team_count != wanted:
            capacity_conflicts.append(
                {
                    "eventId": event.id,
                    "category": event_category,
                    "name": event.name,
                    "reason": protection,
                    "currentTeamCount": event.team_count,
                    "requestedTeamCount": wanted,
                }
            )

    source_teams = [team for team in teams if team.source_team_key]
    rwos_towels = [row for row in towels if row.source == RWOS_LOOKUP_SOURCE]
    group_edges = [edge for edge in edges if (edge.reason or "").startswith("group:")]

    def _filled(attr: str) -> int:
        return sum(1 for team in source_teams if (getattr(team, attr) or "").strip())

    return {
        "ok": not capacity_conflicts,
        "teams": {
            "total": len(teams),
            "sourceBacked": len(source_teams),
            "manual": len(teams) - len(source_teams),
        },
        "towels": {
            "total": len(towels),
            "rwosImport": len(rwos_towels),
            "untagged": len(towels) - len(rwos_towels),
        },
        "wkwEdges": {
            "total": len(edges),
            "groupReason": len(group_edges),
        },
        "contacts": {
            "sourceTeams": len(source_teams),
            "player1Cellphone": _filled("player1_cellphone"),
            "player1Email": _filled("player1_email"),
            "player2Cellphone": _filled("player2_cellphone"),
            "player2Email": _filled("player2_email"),
        },
        "events": event_payloads,
        "capacityConflicts": capacity_conflicts,
        "warnings": protection_warnings,
        "conflicts": [
            _conflict(
                CONFLICT_DRAW_PROTECTION,
                f"{item['name']}: {item['reason']} (kept {item['currentTeamCount']}, requested {item['requestedTeamCount']}).",
                **item,
            )
            for item in capacity_conflicts
        ],
    }


def roster_projection_from_live(summary: dict[str, Any]) -> dict[str, Any]:
    contacts = summary.get("contacts") or {}
    contact_fields = sum(
        int(contacts.get(name) or 0)
        for name in ("player1Cellphone", "player1Email", "player2Cellphone", "player2Email")
    )
    return {
        "ok": bool(summary.get("ok")),
        "created": {
            "events": 0,
            "teams": int((summary.get("teams") or {}).get("sourceBacked") or 0),
            "towelRows": int((summary.get("towels") or {}).get("rwosImport") or 0),
            "wkwEdges": int((summary.get("wkwEdges") or {}).get("groupReason") or 0),
        },
        "updated": {
            "teams": 0,
            "contactFields": contact_fields,
            "towelRows": 0,
        },
        "warnings": list(summary.get("warnings") or []),
        "conflicts": list(summary.get("conflicts") or []),
    }


def _project_towels(
    session: Session,
    tournament_id: int,
    snapshot_team: SnapshotTeam,
    result: RosterProjectionResult,
) -> None:
    _upsert_rwos_towel_row(session, tournament_id, snapshot_team.team_key, 1, snapshot_team.player1, result)
    _upsert_rwos_towel_row(session, tournament_id, snapshot_team.team_key, 2, snapshot_team.player2, result)
