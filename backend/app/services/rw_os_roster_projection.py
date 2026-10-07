"""Project an approved RW-OS snapshot onto live Team / WKW / towel rows."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import or_
from sqlmodel import Session, select

from app.models.event import Event, EventCategory
from app.models.match import Match
from app.models.team import Team
from app.models.team_avoid_edge import TeamAvoidEdge
from app.models.temporary_player_lookup import TemporaryPlayerLookup
from app.models.tournament_import import TournamentDrawPlan, TournamentImport
from app.services.active_roster import team_is_active
from app.services.canonical_teams import SnapshotPlayer, SnapshotTeam, sort_teams_for_planning
from app.services.combined_roster_writes import (
    add_missing_group_avoid_edges,
    apply_team_contact_fields,
    group_map_from_avoid_groups,
    sync_players_from_team_slots_if_enabled,
)
from app.services.post_draw_corrections import match_locked_for_participant_edit
from app.services.rw_os_import import parse_teams, snapshot_hash
from app.services.structure_events import event_category_for_draw_kind, event_protection_reason

RWOS_LOOKUP_SOURCE = "rwos-import"

CONFLICT_STRUCTURAL_SNAPSHOT = "structural_snapshot_changed_after_approval"
CONFLICT_TEAM_WOULD_MOVE = "projected_team_would_move_bracket"
CONFLICT_DRAW_PROTECTION = "live_draw_protection_blocks_structural_change"
CONFLICT_ROSTER_RECONCILIATION_BLOCKED = "roster_reconciliation_blocked"
CONFLICT_DRAW_PLACEMENT_UNRESOLVED = "roster_draw_placement_unresolved"
CONFLICT_ROSTER_RECONCILIATION_INCOMPLETE = "roster_reconciliation_incomplete"
EMPTY_DRAW_SLOT = "TBD"
_FEEDER_PLACEHOLDER = re.compile(r"^(?:W\(|L\(|WINNER:|LOSER:|TBD:|WFSEED:)", re.IGNORECASE)
_SEED_PLACEHOLDER = re.compile(r"^SEED[_ ](\d+)$", re.IGNORECASE)
_STRUCTURAL_SLOT = re.compile(r"^(?:SEED[_ ]\d+|TBD|BYE|WFSEED:\S*|W\(.+|L\(.+|WINNER:\S*|LOSER:\S*)$", re.IGNORECASE)


@dataclass
class RosterProjectionResult:
    created_events: int = 0
    created_teams: int = 0
    created_towel_rows: int = 0
    created_wkw_edges: int = 0
    updated_teams: int = 0
    updated_contact_fields: int = 0
    updated_towel_rows: int = 0
    updated_seeds: int = 0
    withdrawn_teams: int = 0
    draw_slots_replaced: int = 0
    field_changes: list[dict[str, Any]] = field(default_factory=list)
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
                "seeds": self.updated_seeds,
            },
            "reconciled": {
                "withdrawnTeams": self.withdrawn_teams,
                "drawSlotsReplaced": self.draw_slots_replaced,
            },
            "fieldChanges": list(self.field_changes),
            "warnings": list(self.warnings),
            "conflicts": list(self.conflicts),
        }


def _blank_text(value: Any) -> Optional[str]:
    text = str(value).strip() if value is not None else ""
    return text or None


def _values_equal(before: Any, after: Any) -> bool:
    if before is None and after is None:
        return True
    if isinstance(before, (int, float)) or isinstance(after, (int, float)):
        try:
            return before is not None and after is not None and float(before) == float(after)
        except (TypeError, ValueError):
            pass
    return before == after


def _record_field_change(
    result: RosterProjectionResult,
    *,
    team_key: str,
    team_label: str,
    field: str,
    label: str,
    before: Any,
    after: Any,
    player_slot: Optional[int] = None,
) -> None:
    if _values_equal(before, after):
        return
    result.field_changes.append(
        {
            "teamKey": team_key,
            "teamLabel": team_label,
            "field": field,
            "label": label,
            "before": before,
            "after": after,
            "playerSlot": player_slot,
        }
    )


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


def _source_key_aliases(source_team_key: str) -> set[str]:
    """Canonical key plus the swapped partner order. Player ids are text either way."""
    key = (source_team_key or "").strip()
    aliases = {key} if key else set()
    left, separator, right = key.partition("/")
    if separator and left and right:
        aliases.add(f"{right}/{left}")
    return aliases


def _find_projected_team(session: Session, tournament_id: int, source_team_key: str) -> Optional[Team]:
    aliases = _source_key_aliases(source_team_key)
    if not aliases:
        return None
    rows = session.exec(
        select(Team).join(Event).where(Event.tournament_id == tournament_id, Team.source_team_key.in_(aliases))
    ).all()
    exact = [team for team in rows if team.source_team_key == source_team_key]
    return (exact or rows or [None])[0]


def _category_events(events: list[Event], draw_kind: str) -> list[Event]:
    category = event_category_for_draw_kind(draw_kind)
    if category is None:
        return []
    matched: list[Event] = []
    for event in events:
        event_category = event.category.value if isinstance(event.category, EventCategory) else str(event.category)
        if event_category == category.value:
            matched.append(event)
    return matched


def _sole_category_event(events: list[Event], draw_kind: str) -> Optional[Event]:
    matched = _category_events(events, draw_kind)
    if len(matched) == 1:
        return matched[0]
    return None


def _resolve_roster_event(events: list[Event], draw_kind: str, label: str) -> Optional[Event]:
    """Label match first. One event in the category still receives the current roster."""
    found = _event_by_route(events, draw_kind, label)
    if found is not None:
        return found
    return _sole_category_event(events, draw_kind)


def _operational_brackets(
    brackets: list[dict[str, Any]],
    draw_teams: list[SnapshotTeam],
    events: list[Event],
    draw_kind: str,
) -> list[dict[str, Any]]:
    """Current teams fill the approved capacity. A stale rankEnd does not drop them.

    A single Mixed event of 24 is the whole Mixed field, even when the stored rank
    window is still 1–19 or the bracket label no longer matches the event name.
    Several events of the same category keep their own rank windows.
    """
    if not draw_teams:
        return brackets
    sole = _sole_category_event(events, draw_kind)
    capacity = int(sole.team_count or 0) if sole is not None else 0
    if sole is None or capacity < len(draw_teams):
        return brackets
    overlay = dict(brackets[0] if brackets else {})
    for bracket in brackets:
        label = str(bracket.get("label") or "").strip()
        if _event_by_route(events, draw_kind, label) is sole:
            overlay = dict(bracket)
            break
    overlay["label"] = sole.name
    overlay["rankStart"] = 1
    overlay["rankEnd"] = len(draw_teams)
    overlay["size"] = max(int(overlay.get("size") or 0), capacity, len(draw_teams))
    return [overlay]


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
    *,
    team_label: str | None = None,
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
        before_color = existing.towel_color
        changed = False
        for name, value in fields.items():
            if name == "updated_at":
                continue
            if getattr(existing, name) != value:
                setattr(existing, name, value)
                changed = True
        if not changed:
            return
        existing.updated_at = fields["updated_at"]
        session.add(existing)
        if before_color != incoming_color:
            result.updated_towel_rows += 1
            _record_field_change(
                result,
                team_key=team_key,
                team_label=team_label or team_key,
                field=f"player{slot}Towel",
                label=f"Player {slot} towel",
                before=before_color,
                after=incoming_color,
                player_slot=slot,
            )
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
    _record_field_change(
        result,
        team_key=team_key,
        team_label=team_label or team_key,
        field=f"player{slot}Towel",
        label=f"Player {slot} towel",
        before=None,
        after=incoming_color,
        player_slot=slot,
    )


def _group_letters(avoid_group: Optional[str]) -> set[str]:
    return {part.strip().upper() for part in (avoid_group or "").split(",") if part.strip()}


def _drop_stale_group_edges(session: Session, event_id: int, team: Team, new_group: Optional[str]) -> int:
    """Remove imported group edges that are no longer part of this team's RW-OS avoid group."""
    if team.id is None:
        return 0
    new_letters = _group_letters(new_group)
    edges = session.exec(
        select(TeamAvoidEdge).where(
            TeamAvoidEdge.event_id == event_id,
            (TeamAvoidEdge.team_id_a == team.id) | (TeamAvoidEdge.team_id_b == team.id),
        )
    ).all()
    removed = 0
    for edge in edges:
        reason = edge.reason or ""
        if not reason.startswith("group:"):
            continue
        letter = reason.split(":", 1)[1].strip().upper()
        if letter and letter not in new_letters:
            session.delete(edge)
            removed += 1
    return removed


def _delete_team_avoid_edges(session: Session, event_id: int, team_id: int) -> int:
    edges = session.exec(
        select(TeamAvoidEdge).where(
            TeamAvoidEdge.event_id == event_id,
            or_(TeamAvoidEdge.team_id_a == team_id, TeamAvoidEdge.team_id_b == team_id),
        )
    ).all()
    for edge in edges:
        session.delete(edge)
    return len(edges)


def _maybe_warn_stale_wkw(
    session: Session, event_id: int, team: Team, new_group: Optional[str], result: RosterProjectionResult
) -> None:
    del result
    _drop_stale_group_edges(session, event_id, team, new_group)


@dataclass
class _VacatedDrawSlot:
    match_id: int
    event_id: int
    side: str
    seed: Optional[int]
    sort_key: tuple
    withdrawn_key: str
    withdrawn_label: str


@dataclass
class _BlockedWithdrawal:
    team: Team
    event_name: str
    reason: str
    label: str


def _team_label(team: Team) -> str:
    return team.display_name or team.name or team.source_team_key or f"Team {team.id}"


def _matches_for_team(session: Session, team: Team) -> list[Match]:
    if team.id is None:
        return []
    return list(
        session.exec(
            select(Match).where(
                Match.event_id == team.event_id,
                or_(
                    Match.team_a_id == team.id,
                    Match.team_b_id == team.id,
                    Match.winner_team_id == team.id,
                ),
            )
        ).all()
    )


def _team_draw_lock_reason(session: Session, team: Team) -> Optional[str]:
    """Why this team's draw slot must not be rewritten. None when every slot is still an unplayed entry."""
    for match in _matches_for_team(session, team):
        locked = match_locked_for_participant_edit(session, match)
        if locked:
            return locked
        if match.team_a_id == team.id and match.source_match_a_id is not None:
            return "team has advanced into a downstream match"
        if match.team_b_id == team.id and match.source_match_b_id is not None:
            return "team has advanced into a downstream match"
        if match.winner_team_id == team.id:
            return "team is already recorded as a match winner"
    return None


def _delete_rwos_towel_rows(session: Session, tournament_id: int, team_key: str) -> int:
    rows = session.exec(
        select(TemporaryPlayerLookup).where(
            TemporaryPlayerLookup.tournament_id == tournament_id,
            TemporaryPlayerLookup.source == RWOS_LOOKUP_SOURCE,
            TemporaryPlayerLookup.source_team_key == team_key,
        )
    ).all()
    for row in rows:
        session.delete(row)
    return len(rows)


def _event_has_matches(session: Session, event_id: int) -> bool:
    return session.exec(select(Match.id).where(Match.event_id == event_id).limit(1)).first() is not None


def _team_occupies_match(session: Session, team: Team) -> bool:
    if team.id is None:
        return False
    row = session.exec(
        select(Match.id).where(
            Match.event_id == team.event_id,
            or_(Match.team_a_id == team.id, Match.team_b_id == team.id),
        )
    ).first()
    return row is not None


def _is_structural_draw_label(label: Optional[str]) -> bool:
    """Seed N, TBD, and feeder text are draw structure, not teams."""
    text = (label or "").strip()
    if not text or text == EMPTY_DRAW_SLOT:
        return True
    return _STRUCTURAL_SLOT.match(text) is not None or _FEEDER_PLACEHOLDER.match(text) is not None


def _drop_resolved_withdrawal_warnings(session: Session, result: RosterProjectionResult) -> None:
    """A placeholder is not a withdrawal, and a slot filled later in this run is not still open."""
    kept: list[dict[str, Any]] = []
    for warning in result.warnings:
        if warning.get("code") != "draw_slot_left_open":
            kept.append(warning)
            continue
        if _is_structural_draw_label(str(warning.get("slotLabel") or "")) or str(
            warning.get("teamKey") or ""
        ).startswith("open:"):
            continue
        match = session.get(Match, warning.get("matchId"))
        side = warning.get("side")
        if match is not None and (
            (side == "A" and match.team_a_id is not None) or (side == "B" and match.team_b_id is not None)
        ):
            continue
        kept.append(warning)
    result.warnings = kept


def _placeholder_seed(placeholder: Optional[str]) -> Optional[int]:
    match = _SEED_PLACEHOLDER.match((placeholder or "").strip())
    if not match:
        return None
    return int(match.group(1))


def _is_direct_entry_side(match: Match, placeholder: Optional[str]) -> bool:
    """True for a waterfall round-1 or round-robin side a team can occupy directly."""
    if "_BYE" in (match.match_code or "").upper():
        return False
    if _FEEDER_PLACEHOLDER.match((placeholder or "").strip()):
        return False
    kind = (match.match_type or "").upper()
    if kind == "WF":
        return (match.round_index or match.round_number or 0) == 1
    return kind in {"RR", "MAIN"}


def _open_capacity_entry_slots(session: Session, event_id: int) -> list[_VacatedDrawSlot]:
    """Unplayed entry sides that do not yet have a team.

    A 24-team draw built while only 20 teams existed keeps those empty sides.
    They are unused capacity, not a new bracket. Later feeder rounds and byes stay empty.
    """
    matches = session.exec(select(Match).where(Match.event_id == event_id)).all()
    slots: list[_VacatedDrawSlot] = []
    for match in matches:
        if match.id is None or match_locked_for_participant_edit(session, match):
            continue
        sides = (
            ("A", match.team_a_id, match.source_match_a_id, match.placeholder_side_a, 0),
            ("B", match.team_b_id, match.source_match_b_id, match.placeholder_side_b, 1),
        )
        for side, team_id, source_id, placeholder, side_order in sides:
            if team_id is not None or source_id is not None:
                continue
            if not _is_direct_entry_side(match, placeholder):
                continue
            seed = _placeholder_seed(placeholder)
            slots.append(
                _VacatedDrawSlot(
                    match_id=match.id,
                    event_id=event_id,
                    side=side,
                    seed=seed,
                    sort_key=(
                        seed if seed is not None else 10_000,
                        match.round_index or 0,
                        match.sequence_in_round or 0,
                        side_order,
                        match.id,
                    ),
                    withdrawn_key=f"open:{match.id}:{side}",
                    withdrawn_label=(placeholder or "").strip() or EMPTY_DRAW_SLOT,
                )
            )
    slots.sort(key=lambda slot: slot.sort_key)
    return slots


def _withdraw_absent_source_teams(
    session: Session,
    import_row: TournamentImport,
    active_keys: set[str],
    result: RosterProjectionResult,
) -> tuple[list[_VacatedDrawSlot], list[_BlockedWithdrawal]]:
    """Retire source teams that are no longer on the active RW-OS roster.

    Unplayed entry slots are cleared. Started, scored, won, or advanced matches are left intact
    and reported as conflicts.
    """
    live_teams = session.exec(
        select(Team)
        .join(Event)
        .where(Event.tournament_id == import_row.tournament_id, Team.source_team_key.is_not(None))
    ).all()
    vacated: list[_VacatedDrawSlot] = []
    blocked: list[_BlockedWithdrawal] = []
    for team in live_teams:
        key = team.source_team_key or ""
        if not key or key in active_keys or team.is_defaulted or team.id is None:
            continue
        event = session.get(Event, team.event_id)
        event_name = event.name if event else "Event"
        label = _team_label(team)
        reason = _team_draw_lock_reason(session, team)
        if reason:
            blocked.append(_BlockedWithdrawal(team=team, event_name=event_name, reason=reason, label=label))
            continue

        seed = team.seed
        for match in _matches_for_team(session, team):
            if match.team_a_id == team.id and match.source_match_a_id is None:
                match.team_a_id = None
                match.placeholder_side_a = EMPTY_DRAW_SLOT
                vacated.append(
                    _VacatedDrawSlot(
                        match_id=match.id,  # type: ignore[arg-type]
                        event_id=team.event_id,
                        side="A",
                        seed=seed,
                        sort_key=(match.round_index or 0, match.sequence_in_round or 0, 0, match.id or 0),
                        withdrawn_key=key,
                        withdrawn_label=label,
                    )
                )
                session.add(match)
            if match.team_b_id == team.id and match.source_match_b_id is None:
                match.team_b_id = None
                match.placeholder_side_b = EMPTY_DRAW_SLOT
                vacated.append(
                    _VacatedDrawSlot(
                        match_id=match.id,  # type: ignore[arg-type]
                        event_id=team.event_id,
                        side="B",
                        seed=seed,
                        sort_key=(match.round_index or 0, match.sequence_in_round or 0, 1, match.id or 0),
                        withdrawn_key=key,
                        withdrawn_label=label,
                    )
                )
                session.add(match)

        _record_field_change(
            result,
            team_key=key,
            team_label=label,
            field="rosterStatus",
            label="Roster status",
            before="Active",
            after="Withdrawn",
        )
        team.is_defaulted = True
        team.seed = None
        session.add(team)
        _delete_team_avoid_edges(session, team.event_id, team.id)
        _delete_rwos_towel_rows(session, import_row.tournament_id, key)
        result.withdrawn_teams += 1

    if vacated or blocked:
        session.flush()
    return vacated, blocked


def _create_source_team(
    session: Session,
    *,
    event: Event,
    snapshot_team: SnapshotTeam,
    seed: Optional[int],
    result: RosterProjectionResult,
    wkw_assignments: dict[int, list[tuple[int, Optional[str]]]],
    tournament_id: int,
) -> Team:
    full_name = _team_full_name(snapshot_team)
    display_name = _team_display_name(snapshot_team, full_name)
    rating = _team_rating(snapshot_team)
    name = _unique_team_name(session, event.id, full_name, snapshot_team.team_key, None)  # type: ignore[arg-type]
    usable_seed = seed if seed is not None and _seed_available(session, event.id, seed, None) else None  # type: ignore[arg-type]
    team = Team(
        event_id=event.id,  # type: ignore[arg-type]
        name=name,
        seed=usable_seed,
        rating=rating,
        avoid_group=snapshot_team.avoid_group,
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
    if team.id and event.id:
        wkw_assignments.setdefault(event.id, []).append((team.id, snapshot_team.avoid_group))
    _project_towels(session, tournament_id, snapshot_team, result)
    return team


def _assign_draw_slot(session: Session, match: Match, side: str, team: Team) -> bool:
    if match_locked_for_participant_edit(session, match):
        return False
    label = team.name or team.display_name or EMPTY_DRAW_SLOT
    if side == "A":
        if match.source_match_a_id is not None or match.team_a_id is not None:
            return False
        match.team_a_id = team.id
        match.placeholder_side_a = label
    else:
        if match.source_match_b_id is not None or match.team_b_id is not None:
            return False
        match.team_b_id = team.id
        match.placeholder_side_b = label
    session.add(match)
    return True


def _place_replacements_in_vacated_slots(
    session: Session,
    *,
    vacated: list[_VacatedDrawSlot],
    blocked: list[_BlockedWithdrawal],
    candidates: list[Team],
    result: RosterProjectionResult,
    skip_event_ids: Optional[set[int]] = None,
) -> None:
    """Put newly active teams into vacated or still-empty entry slots. Do not rebuild the draw."""
    explained_unplaced: set[int] = set()
    slots_by_event: dict[int, list[_VacatedDrawSlot]] = {}
    for slot in vacated:
        slots_by_event.setdefault(slot.event_id, []).append(slot)
    candidates_by_event: dict[int, list[Team]] = {}
    for team in candidates:
        if team.id is None or _team_occupies_match(session, team):
            continue
        candidates_by_event.setdefault(team.event_id, []).append(team)

    claimed = {(slot.match_id, slot.side) for slot in vacated}
    for event_id in candidates_by_event:
        for slot in _open_capacity_entry_slots(session, event_id):
            if (slot.match_id, slot.side) in claimed:
                continue
            claimed.add((slot.match_id, slot.side))
            slots_by_event.setdefault(event_id, []).append(slot)

    skipped = skip_event_ids or set()
    for event_id, slots in slots_by_event.items():
        if event_id in skipped:
            continue
        grouped: dict[str, list[_VacatedDrawSlot]] = {}
        for slot in slots:
            grouped.setdefault(slot.withdrawn_key, []).append(slot)
        ordered_groups = sorted(grouped.values(), key=lambda group: min(slot.sort_key for slot in group))
        ordered_teams = sorted(
            candidates_by_event.get(event_id, []),
            key=lambda team: (team.seed is None, team.seed or 0, team.id or 0),
        )
        for group, team in zip(ordered_groups, ordered_teams):
            for slot in sorted(group, key=lambda item: item.sort_key):
                match = session.get(Match, slot.match_id)
                if match is None or not _assign_draw_slot(session, match, slot.side, team):
                    continue
                if (
                    team.seed is None
                    and slot.seed is not None
                    and _seed_available(session, event_id, slot.seed, team.id)
                ):
                    team.seed = slot.seed
                    session.add(team)
                result.draw_slots_replaced += 1
                _record_field_change(
                    result,
                    team_key=team.source_team_key or "",
                    team_label=_team_label(team),
                    field="drawSlot",
                    label="Draw slot",
                    before=slot.withdrawn_label,
                    after=_team_label(team),
                )
        if len(ordered_groups) > len(ordered_teams):
            for group in ordered_groups[len(ordered_teams) :]:
                slot = group[0]
                if _is_structural_draw_label(slot.withdrawn_label) or slot.withdrawn_key.startswith("open:"):
                    continue
                result.warnings.append(
                    _warning(
                        "draw_slot_left_open",
                        (
                            f"{slot.withdrawn_label} was withdrawn from an unplayed draw slot and no replacement "
                            "team was available to take that spot."
                        ),
                        teamKey=slot.withdrawn_key,
                        eventId=event_id,
                        matchId=slot.match_id,
                        side=slot.side,
                        slotLabel=slot.withdrawn_label,
                    )
                )

    for item in blocked:
        replacements = [team for team in candidates if team.event_id == item.team.event_id and team.id is not None]
        unplaced = [team for team in replacements if not _team_occupies_match(session, team)]
        for team in unplaced:
            if team.id is not None:
                explained_unplaced.add(team.id)
        names = ", ".join(_team_label(team) for team in unplaced)
        replacement_sentence = (
            f" {names} is active in RW-OS but was not placed into that match."
            if names
            else " No replacement team was placed into that match."
        )
        result.conflicts.append(
            _conflict(
                CONFLICT_ROSTER_RECONCILIATION_BLOCKED,
                (
                    f"{item.event_name}: {item.label} is withdrawn in RW-OS, but automatic draw reconciliation was "
                    f"blocked because {item.reason} The draw and match history were not changed."
                    f"{replacement_sentence} Staff must resolve this matchup."
                ),
                teamKey=item.team.source_team_key,
                eventId=item.team.event_id,
                eventName=item.event_name,
                withdrawnTeam=item.label,
                replacementTeam=names or None,
                reason=item.reason,
            )
        )

    for event_id, teams in candidates_by_event.items():
        if event_id in skipped:
            continue
        unplaced = [
            team for team in teams if team.id not in explained_unplaced and not _team_occupies_match(session, team)
        ]
        if not unplaced or not _event_has_matches(session, event_id):
            continue
        event = session.get(Event, event_id)
        event_name = event.name if event else "Event"
        names = ", ".join(_team_label(team) for team in unplaced)
        result.conflicts.append(
            _conflict(
                CONFLICT_DRAW_PLACEMENT_UNRESOLVED,
                (
                    f"{event_name}: {names} was added to the team list, but no open unplayed draw slot was available. "
                    "Staff must place this team into the draw."
                ),
                eventId=event_id,
                eventName=event_name,
                replacementTeam=names,
            )
        )


def _place_existing_teams_in_open_capacity(
    session: Session,
    *,
    tournament_id: int,
    active_keys: set[str],
    vacated: list[_VacatedDrawSlot],
    result: RosterProjectionResult,
    skip_event_ids: Optional[set[int]] = None,
) -> None:
    """Put active source teams that never reached the draw into sides that were already empty.

    Slots cleared by a withdrawal in this same refresh stay reserved for a new or returning team.
    Occupied sides are not moved.
    """
    reserved = {(slot.match_id, slot.side) for slot in vacated}
    rows = session.exec(
        select(Team).join(Event).where(Event.tournament_id == tournament_id, Team.source_team_key.is_not(None))
    ).all()
    pending: dict[int, list[Team]] = {}
    for team in rows:
        key = team.source_team_key or ""
        if not key or key not in active_keys or not team_is_active(team) or team.id is None:
            continue
        if _team_occupies_match(session, team):
            continue
        pending.setdefault(team.event_id, []).append(team)
    skipped = skip_event_ids or set()
    for event_id, teams in pending.items():
        if event_id in skipped:
            continue
        slots = [
            slot for slot in _open_capacity_entry_slots(session, event_id) if (slot.match_id, slot.side) not in reserved
        ]
        ordered_teams = sorted(teams, key=lambda team: (team.seed is None, team.seed or 0, team.id or 0))
        for slot, team in zip(slots, ordered_teams):
            match = session.get(Match, slot.match_id)
            if match is None or not _assign_draw_slot(session, match, slot.side, team):
                continue
            if team.seed is None and slot.seed is not None and _seed_available(session, event_id, slot.seed, team.id):
                team.seed = slot.seed
                session.add(team)
            result.draw_slots_replaced += 1
            _record_field_change(
                result,
                team_key=team.source_team_key or "",
                team_label=_team_label(team),
                field="drawSlot",
                label="Draw slot",
                before=slot.withdrawn_label,
                after=_team_label(team),
            )


def _approved_draw_plans(session: Session, import_row: TournamentImport) -> list[TournamentDrawPlan]:
    return list(
        session.exec(
            select(TournamentDrawPlan).where(
                TournamentDrawPlan.import_id == import_row.id,
                TournamentDrawPlan.approved == True,  # noqa: E712
            )
        ).all()
    )


def _routed_event_ids(
    teams: list[SnapshotTeam],
    plans: list[TournamentDrawPlan],
    events: list[Event],
) -> dict[str, int]:
    routed_ids: dict[str, int] = {}
    for plan in plans:
        draw_teams = [team for team in teams if team.draw_kind == plan.draw_kind]
        brackets = _brackets_from_plan(plan)
        assigned: set[str] = set()
        for snapshot_team, bracket, _rank in route_snapshot_teams(draw_teams, brackets):
            label = str(bracket.get("label") or "").strip()
            event = _event_by_route(events, plan.draw_kind, label)
            if event is not None and event.id is not None:
                routed_ids[snapshot_team.team_key] = event.id
                assigned.add(snapshot_team.team_key)
        last = brackets[-1] if brackets else None
        last_label = str((last or {}).get("label") or "").strip()
        fallback = _event_by_route(events, plan.draw_kind, last_label) if last_label else None
        if fallback is None or fallback.id is None:
            continue
        for team in draw_teams:
            if team.team_key not in assigned and team.team_key not in routed_ids:
                routed_ids[team.team_key] = fallback.id
    return routed_ids


def operational_roster_drift(
    session: Session,
    import_row: TournamentImport,
    current_team_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """Compare the current RW-OS active roster with event membership and draw participants.

    The stored snapshot hash is not enough. A download that matches the last snapshot is still
    stale when those teams are missing from the event or from a draw that already exists.
    """
    empty = {
        "reconciliationNeeded": False,
        "missingFromEvent": [],
        "extraInEvent": [],
        "missingFromDraw": [],
        "extraInDraw": [],
        "seedMismatches": [],
    }
    if import_row.plan_status not in ("approved", "stale"):
        return empty
    plans = _approved_draw_plans(session, import_row)
    if not plans:
        return empty

    snapshot_teams = parse_teams(current_team_rows)
    rwos_keys = {team.team_key for team in snapshot_teams}
    live = session.exec(
        select(Team)
        .join(Event)
        .where(Event.tournament_id == import_row.tournament_id, Team.source_team_key.is_not(None))
    ).all()
    active_keys = {team.source_team_key for team in live if team.source_team_key and team_is_active(team)}
    events = list(session.exec(select(Event).where(Event.tournament_id == import_row.tournament_id)).all())
    events_with_matches = {
        event.id for event in events if event.id is not None and _event_has_matches(session, event.id)
    }
    draw_keys = {
        team.source_team_key
        for team in live
        if team.source_team_key and team.event_id in events_with_matches and _team_occupies_match(session, team)
    }
    existing_event = {team.source_team_key: team.event_id for team in live if team.source_team_key}
    routed = _routed_event_ids(snapshot_teams, plans, events)
    expected_draw: set[str] = set()
    for key in rwos_keys:
        event_id = existing_event.get(key, routed.get(key))
        if event_id in events_with_matches:
            expected_draw.add(key)

    missing_from_event = sorted(rwos_keys - active_keys)
    extra_in_event = sorted(active_keys - rwos_keys)
    missing_from_draw = sorted(expected_draw - draw_keys)
    extra_in_draw = sorted(key for key in draw_keys if key not in rwos_keys)
    seed_mismatches = _seed_mismatches(snapshot_teams, plans, events, live)
    return {
        "reconciliationNeeded": bool(
            missing_from_event or extra_in_event or missing_from_draw or extra_in_draw or seed_mismatches
        ),
        "missingFromEvent": missing_from_event,
        "extraInEvent": extra_in_event,
        "missingFromDraw": missing_from_draw,
        "extraInDraw": extra_in_draw,
        "seedMismatches": seed_mismatches,
    }


def _identity_line(team: SnapshotTeam) -> str:
    name = team.display_name or team.full_name or team.team_key
    return f"{name} ({team.team_key})"


def _desired_teams_by_event(
    plans: list[TournamentDrawPlan],
    teams: list[SnapshotTeam],
    events: list[Event],
    *,
    operational_only: bool,
) -> tuple[dict[int, list[SnapshotTeam]], list[SnapshotTeam]]:
    """Teams that belong on each event after capacity routing, plus teams with no event at all."""
    desired: dict[int, list[SnapshotTeam]] = {}
    untargeted: list[SnapshotTeam] = []
    for plan in plans:
        draw_teams = [team for team in teams if team.draw_kind == plan.draw_kind]
        brackets = _brackets_from_plan(plan)
        if operational_only:
            brackets = _operational_brackets(brackets, draw_teams, events, plan.draw_kind)
        routed = route_snapshot_teams(draw_teams, brackets)
        assigned: set[str] = set()
        for snapshot_team, bracket, _rank in routed:
            label = str(bracket.get("label") or "").strip()
            event = _event_by_route(events, plan.draw_kind, label)
            if (event is None or event.id is None) and operational_only:
                event = _resolve_roster_event(events, plan.draw_kind, label)
            if event is None or event.id is None:
                continue
            desired.setdefault(event.id, []).append(snapshot_team)
            assigned.add(snapshot_team.team_key)
        fallback: Optional[Event] = None
        if operational_only:
            last = brackets[-1] if brackets else None
            last_label = str((last or {}).get("label") or "").strip()
            fallback = _resolve_roster_event(events, plan.draw_kind, last_label)
        for snapshot_team in draw_teams:
            if snapshot_team.team_key in assigned:
                continue
            if fallback is not None and fallback.id is not None:
                desired.setdefault(fallback.id, []).append(snapshot_team)
            else:
                untargeted.append(snapshot_team)
    return desired, untargeted


def _canonical_seeds_by_event(
    plans: list[TournamentDrawPlan],
    teams: list[SnapshotTeam],
    events: list[Event],
) -> dict[int, dict[str, int]]:
    """Current seed is rating order within the event, then source key. It is not a draw slot."""
    desired, _untargeted = _desired_teams_by_event(plans, teams, events, operational_only=True)
    seeds: dict[int, dict[str, int]] = {}
    for event_id, group in desired.items():
        ordered = sort_teams_for_planning(group)
        seeds[event_id] = {team.team_key: index for index, team in enumerate(ordered, start=1)}
    return seeds


def _seed_mismatches(
    teams: list[SnapshotTeam],
    plans: list[TournamentDrawPlan],
    events: list[Event],
    live: list[Team],
) -> list[dict[str, Any]]:
    mismatches: list[dict[str, Any]] = []
    canonical = _canonical_seeds_by_event(plans, teams, events)
    live_by_key = {team.source_team_key: team for team in live if team.source_team_key}
    for event_id, key_seeds in canonical.items():
        for key, expected in key_seeds.items():
            team = live_by_key.get(key)
            if team is None or team.event_id != event_id or not team_is_active(team):
                continue
            if team.seed != expected:
                mismatches.append({"teamKey": key, "actual": team.seed, "expected": expected})
        for team in live:
            if team.event_id != event_id or not team.source_team_key or team_is_active(team) or team.seed is None:
                continue
            mismatches.append({"teamKey": team.source_team_key, "actual": team.seed, "expected": None})
    return mismatches


def _reconcile_active_seeds(
    session: Session,
    plans: list[TournamentDrawPlan],
    teams: list[SnapshotTeam],
    result: RosterProjectionResult,
    failed_event_ids: set[int],
) -> None:
    """Write current ranking onto Team.seed. Do not move match sides."""
    events = (
        list(session.exec(select(Event).where(Event.tournament_id == plans[0].tournament_id)).all()) if plans else []
    )
    if not events and plans:
        return
    canonical = _canonical_seeds_by_event(plans, teams, events)
    for event_id, key_seeds in canonical.items():
        if event_id in failed_event_ids:
            continue
        rows = session.exec(select(Team).where(Team.event_id == event_id)).all()
        active = [
            team for team in rows if team.source_team_key and team_is_active(team) and team.source_team_key in key_seeds
        ]
        if {team.source_team_key for team in active} != set(key_seeds):
            continue
        before = {team.id: team.seed for team in active}
        active_ids = set(before)
        for team in rows:
            if team.seed is None:
                continue
            if team.id not in active_ids:
                result.updated_seeds += 1
                _record_field_change(
                    result,
                    team_key=team.source_team_key or "",
                    team_label=_team_label(team),
                    field="seed",
                    label="Seed",
                    before=team.seed,
                    after=None,
                )
            team.seed = None
            session.add(team)
        session.flush()
        for team in active:
            desired = key_seeds[team.source_team_key or ""]
            team.seed = desired
            session.add(team)
            if before.get(team.id) == desired:
                continue
            result.updated_seeds += 1
            _record_field_change(
                result,
                team_key=team.source_team_key or "",
                team_label=_team_label(team),
                field="seed",
                label="Seed",
                before=before.get(team.id),
                after=desired,
            )
        session.flush()
        actual = {team.seed for team in active}
        expected = set(key_seeds.values())
        if actual != expected or len(actual) != len(active):
            label = teams[0].draw_label if teams else "Event"
            group_label = next((team.draw_label for team in teams if team.team_key in key_seeds), label)
            _append_roster_conflict(
                result,
                "\n".join(
                    [
                        f"{group_label} — Seed metadata could not be reconciled",
                        f"Expected seeds: {sorted(expected)}",
                        f"Actual seeds: {sorted(seed for seed in actual if seed is not None)}",
                    ]
                ),
                stage="seed",
                missing=[],
            )


def _append_roster_conflict(
    result: RosterProjectionResult,
    message: str,
    *,
    stage: str,
    missing: list[SnapshotTeam],
) -> None:
    result.conflicts.append(
        _conflict(
            CONFLICT_ROSTER_RECONCILIATION_INCOMPLETE,
            message,
            stage=stage,
            missingTeams=[_identity_line(team) for team in missing],
        )
    )


def _record_event_roster_failure(
    session: Session,
    import_row: TournamentImport,
    plans: list[TournamentDrawPlan],
    teams: list[SnapshotTeam],
    result: RosterProjectionResult,
) -> set[int]:
    """Stop before draw placement when the event roster is not the desired RW-OS set.

    A Team row somewhere else in the tournament is not membership in this event.
    """
    events = list(session.exec(select(Event).where(Event.tournament_id == import_row.tournament_id)).all())
    live = session.exec(
        select(Team)
        .join(Event)
        .where(Event.tournament_id == import_row.tournament_id, Team.source_team_key.is_not(None))
    ).all()
    desired, untargeted = _desired_teams_by_event(plans, teams, events, operational_only=True)
    failed: set[int] = set()
    for event_id, group in desired.items():
        keys = {team.team_key for team in group}
        active = [team for team in live if team.event_id == event_id and team.source_team_key and team_is_active(team)]
        active_keys = {team.source_team_key for team in active if team.source_team_key}
        missing = [team for team in group if team.team_key not in active_keys]
        extra = sorted(key for key in active_keys if key not in keys)
        if not missing and not extra:
            continue
        failed.add(event_id)
        label = group[0].draw_label or group[0].draw_kind
        lines = [
            f"{label} — Event roster could not be reconciled",
            f"RW-OS: {len(keys)}",
            f"Tournament teams: {len(active)}",
        ]
        if missing:
            lines.append("Missing:")
            lines.extend(_identity_line(team) for team in missing)
        if extra:
            lines.append("Still active locally but absent from RW-OS:")
            lines.extend(extra)
        _append_roster_conflict(result, "\n".join(lines), stage="event", missing=missing)
    if untargeted:
        by_kind: dict[str, list[SnapshotTeam]] = {}
        for team in untargeted:
            by_kind.setdefault(team.draw_kind, []).append(team)
        for group in by_kind.values():
            label = group[0].draw_label or group[0].draw_kind
            lines = [
                f"{label} — Event roster could not be reconciled",
                f"RW-OS: {len(group)}",
                "Tournament teams: 0",
                "Missing:",
                *[_identity_line(team) for team in group],
            ]
            _append_roster_conflict(result, "\n".join(lines), stage="event", missing=group)
    return failed


def _record_draw_reconciliation_failure(
    session: Session,
    import_row: TournamentImport,
    plans: list[TournamentDrawPlan],
    teams: list[SnapshotTeam],
    result: RosterProjectionResult,
    failed_event_ids: set[int],
) -> None:
    """Draw membership is checked only after the event roster already matches."""
    events = list(session.exec(select(Event).where(Event.tournament_id == import_row.tournament_id)).all())
    live = session.exec(
        select(Team)
        .join(Event)
        .where(Event.tournament_id == import_row.tournament_id, Team.source_team_key.is_not(None))
    ).all()
    desired, _untargeted = _desired_teams_by_event(plans, teams, events, operational_only=True)
    for event_id, group in desired.items():
        if event_id in failed_event_ids or not _event_has_matches(session, event_id):
            continue
        keys = {team.team_key for team in group}
        occupants = {
            team.source_team_key
            for team in live
            if team.event_id == event_id and team.source_team_key and _team_occupies_match(session, team)
        }
        missing = [team for team in group if team.team_key not in occupants]
        stale = sorted(key for key in occupants if key not in keys)
        if not missing and not stale:
            continue
        active_count = len(
            [team for team in live if team.event_id == event_id and team.source_team_key and team_is_active(team)]
        )
        draw_count = len(occupants & keys)
        label = group[0].draw_label or group[0].draw_kind
        lines = [
            f"{label} — Draw could not be reconciled",
            f"Tournament teams: {active_count}",
            f"Draw participants: {draw_count}",
        ]
        if missing:
            lines.append("Missing from draw:")
            lines.extend(_identity_line(team) for team in missing)
        if stale:
            lines.append("Still in the draw but absent from RW-OS:")
            lines.extend(stale)
        _append_roster_conflict(result, "\n".join(lines), stage="draw", missing=missing)


def project_approved_roster(
    session: Session,
    import_row: TournamentImport,
    plans: list[TournamentDrawPlan],
    *,
    events_created: int = 0,
    operational_only: bool = False,
    allow_structural_rebuild: bool = False,
    commit: bool = True,
) -> RosterProjectionResult:
    result = RosterProjectionResult(created_events=events_created)
    teams = parse_teams(json.loads(import_row.snapshot_json or "[]"))
    current_hash = current_snapshot_hash(import_row)
    approved_hash = import_row.approved_source_hash
    structural_mismatch = bool(approved_hash and current_hash != approved_hash)

    if structural_mismatch and not allow_structural_rebuild and not operational_only:
        result.conflicts.append(
            _conflict(
                CONFLICT_STRUCTURAL_SNAPSHOT,
                "The structural snapshot changed after approval. Re-approve or rebuild before changing live bracket membership.",
                approvedSourceHash=approved_hash,
                currentSourceHash=current_hash,
            )
        )
        return result

    events = list(session.exec(select(Event).where(Event.tournament_id == import_row.tournament_id)).all())
    if allow_structural_rebuild and not operational_only:
        _release_projected_seeds(session, import_row.tournament_id)
    touched_teams: list[Team] = []
    placement_candidates: list[Team] = []
    wkw_assignments: dict[int, list[tuple[int, Optional[str]]]] = {}
    active_keys = {team.team_key for team in teams}
    vacated_slots, blocked_withdrawals = _withdraw_absent_source_teams(session, import_row, active_keys, result)

    for plan in plans:
        draw_teams = [team for team in teams if team.draw_kind == plan.draw_kind]
        brackets = _brackets_from_plan(plan)
        if operational_only:
            brackets = _operational_brackets(brackets, draw_teams, events, plan.draw_kind)
        routed = route_snapshot_teams(draw_teams, brackets)
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
                if operational_only:
                    brackets = _brackets_from_plan(plan)
                    last = brackets[-1] if brackets else None
                    last_label = str((last or {}).get("label") or "").strip()
                    fallback_event = (
                        _resolve_roster_event(events, plan.draw_kind, last_label)
                        if last_label or operational_only
                        else None
                    )
                    existing_unassigned = _find_projected_team(session, import_row.tournament_id, team.team_key)
                    if existing_unassigned is None:
                        if fallback_event is not None and fallback_event.id is not None:
                            created = _create_source_team(
                                session,
                                event=fallback_event,
                                snapshot_team=team,
                                seed=None,
                                result=result,
                                wkw_assignments=wkw_assignments,
                                tournament_id=import_row.tournament_id,
                            )
                            touched_teams.append(created)
                            placement_candidates.append(created)
                    else:
                        _apply_operational_team_updates(session, existing_unassigned, team, result, wkw_assignments)
                        touched_teams.append(existing_unassigned)
                        if team_is_active(existing_unassigned) and not _team_occupies_match(
                            session, existing_unassigned
                        ):
                            placement_candidates.append(existing_unassigned)

        for snapshot_team, bracket, planner_rank in routed:
            _collect_operational_warnings(snapshot_team, result.warnings)
            label = str(bracket.get("label") or "").strip()
            event = _event_by_route(events, plan.draw_kind, label)
            if (event is None or event.id is None) and operational_only:
                event = _resolve_roster_event(events, plan.draw_kind, label)
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
                # Refresh creates the roster row even when a draw exists. Placement into a started
                # match is refused later; draw_status alone is not a block.
                if not operational_only and structural_mismatch and not allow_structural_rebuild:
                    continue
                if not operational_only and protection:
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
                team = _create_source_team(
                    session,
                    event=event,
                    snapshot_team=snapshot_team,
                    seed=in_bracket_seed,
                    result=result,
                    wkw_assignments=wkw_assignments,
                    tournament_id=import_row.tournament_id,
                )
                touched_teams.append(team)
                placement_candidates.append(team)
                continue

            was_inactive = bool(existing.is_defaulted)
            contact_updates = _apply_operational_team_updates(session, existing, snapshot_team, result, wkw_assignments)
            if was_inactive and team_is_active(existing):
                placement_candidates.append(existing)
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

    failed_event_ids: set[int] = set()
    if operational_only:
        session.flush()
        failed_event_ids = _record_event_roster_failure(session, import_row, plans, teams, result)
    _place_replacements_in_vacated_slots(
        session,
        vacated=vacated_slots,
        blocked=blocked_withdrawals,
        candidates=placement_candidates,
        result=result,
        skip_event_ids=failed_event_ids,
    )
    if operational_only:
        _place_existing_teams_in_open_capacity(
            session,
            tournament_id=import_row.tournament_id,
            active_keys=active_keys,
            vacated=vacated_slots,
            result=result,
            skip_event_ids=failed_event_ids,
        )
        _drop_resolved_withdrawal_warnings(session, result)
        _reconcile_active_seeds(session, plans, teams, result, failed_event_ids)

    for event_id, assignments in wkw_assignments.items():
        group_map = group_map_from_avoid_groups(assignments)
        try:
            result.created_wkw_edges += add_missing_group_avoid_edges(session, event_id, group_map)
        except Exception as exc:
            result.warnings.append(_warning("wkw_edge_error", f"Error creating avoid edges: {exc}"))

    sync_players_from_team_slots_if_enabled(session, import_row.tournament_id, touched_teams)
    if operational_only:
        session.flush()
        _record_draw_reconciliation_failure(session, import_row, plans, teams, result, failed_event_ids)
    # Refresh + Rebuild Draws holds this commit so a later draw failure can roll the roster back.
    # Normal Check / Refresh keeps the default and commits here.
    if commit:
        session.commit()
    else:
        session.flush()
    return result


def _apply_operational_team_updates(
    session: Session,
    team: Team,
    snapshot_team: SnapshotTeam,
    result: RosterProjectionResult,
    wkw_assignments: dict[int, list[tuple[int, Optional[str]]]],
) -> int:
    full_name = _team_full_name(snapshot_team)
    display_name = _team_display_name(snapshot_team, full_name)
    rating = _team_rating(snapshot_team)
    name = _unique_team_name(session, team.event_id, full_name, snapshot_team.team_key, team.id)
    team_label = display_name or team.display_name or snapshot_team.team_key
    identity_changed = False
    if team.source_team_key != snapshot_team.team_key:
        team.source_team_key = snapshot_team.team_key
        identity_changed = True
    if team.is_defaulted:
        _record_field_change(
            result,
            team_key=snapshot_team.team_key,
            team_label=team_label,
            field="rosterStatus",
            label="Roster status",
            before="Withdrawn",
            after="Active",
        )
        team.is_defaulted = False
        identity_changed = True
    if team.name != name:
        _record_field_change(
            result,
            team_key=snapshot_team.team_key,
            team_label=team_label,
            field="fullName",
            label="Full name",
            before=team.name,
            after=name,
        )
        team.name = name
        identity_changed = True
    if team.display_name != display_name:
        _record_field_change(
            result,
            team_key=snapshot_team.team_key,
            team_label=team_label,
            field="displayName",
            label="Short name",
            before=team.display_name,
            after=display_name,
        )
        team.display_name = display_name
        identity_changed = True
    if not _values_equal(team.rating, rating):
        _record_field_change(
            result,
            team_key=snapshot_team.team_key,
            team_label=team_label,
            field="rating",
            label="Rating",
            before=team.rating,
            after=rating,
        )
        team.rating = rating
        identity_changed = True
    if team.avoid_group != snapshot_team.avoid_group:
        _record_field_change(
            result,
            team_key=snapshot_team.team_key,
            team_label=team_label,
            field="avoidGroup",
            label="Who Knows Who",
            before=team.avoid_group,
            after=snapshot_team.avoid_group,
        )
        _maybe_warn_stale_wkw(session, team.event_id, team, snapshot_team.avoid_group, result)
        team.avoid_group = snapshot_team.avoid_group
        identity_changed = True
    if identity_changed:
        session.add(team)
    if team.id:
        wkw_assignments.setdefault(team.event_id, []).append((team.id, snapshot_team.avoid_group or team.avoid_group))
    contact_pairs = (
        (
            "player1Cellphone",
            "Player 1 cellphone",
            1,
            snapshot_team.player1.cellphone,
            team.player1_cellphone or team.p1_cell,
        ),
        ("player1Email", "Player 1 email", 1, snapshot_team.player1.email, team.player1_email or team.p1_email),
        (
            "player2Cellphone",
            "Player 2 cellphone",
            2,
            snapshot_team.player2.cellphone,
            team.player2_cellphone or team.p2_cell,
        ),
        ("player2Email", "Player 2 email", 2, snapshot_team.player2.email, team.player2_email or team.p2_email),
    )
    for field_name, label, slot, incoming, current in contact_pairs:
        incoming_value = _blank_text(incoming)
        if incoming_value is None:
            continue
        _record_field_change(
            result,
            team_key=snapshot_team.team_key,
            team_label=team_label,
            field=field_name,
            label=label,
            before=_blank_text(current),
            after=incoming_value,
            player_slot=slot,
        )
    updated = apply_team_contact_fields(
        team,
        player1_cellphone=snapshot_team.player1.cellphone,
        player1_email=snapshot_team.player1.email,
        player2_cellphone=snapshot_team.player2.cellphone,
        player2_email=snapshot_team.player2.email,
        only_if_present=True,
    )
    result.updated_contact_fields += updated
    return updated + (1 if identity_changed else 0)


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
        event_teams = [team for team in teams_by_event.get(event.id or 0, []) if team_is_active(team)]
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

    active_teams = [team for team in teams if team_is_active(team)]
    source_teams = [team for team in active_teams if team.source_team_key]
    inactive_teams = [team for team in teams if not team_is_active(team)]
    rwos_towels = [row for row in towels if row.source == RWOS_LOOKUP_SOURCE]
    group_edges = [edge for edge in edges if (edge.reason or "").startswith("group:")]

    def _filled(attr: str) -> int:
        return sum(1 for team in source_teams if (getattr(team, attr) or "").strip())

    return {
        "ok": not capacity_conflicts,
        "teams": {
            "total": len(active_teams),
            "sourceBacked": len(source_teams),
            "manual": len(active_teams) - len(source_teams),
            "inactive": len(inactive_teams),
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
        "fieldChanges": [],
        "warnings": list(summary.get("warnings") or []),
        "conflicts": list(summary.get("conflicts") or []),
    }


def _project_towels(
    session: Session,
    tournament_id: int,
    snapshot_team: SnapshotTeam,
    result: RosterProjectionResult,
) -> None:
    team_label = _team_display_name(snapshot_team, _team_full_name(snapshot_team))
    _upsert_rwos_towel_row(
        session, tournament_id, snapshot_team.team_key, 1, snapshot_team.player1, result, team_label=team_label
    )
    _upsert_rwos_towel_row(
        session, tournament_id, snapshot_team.team_key, 2, snapshot_team.player2, result, team_label=team_label
    )
