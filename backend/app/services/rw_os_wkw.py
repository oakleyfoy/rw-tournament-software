"""Authoritative RW-OS Who Knows Who pairwise connections for Tournament Software.

RW-OS exports undirected effective edges. Tournament Software stores that graph
exactly and syncs TeamAvoidEdge rows owned by reason ``rw-os:wkw``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Iterable, Optional

from sqlmodel import Session, select

from app.models.team import Team
from app.models.team_avoid_edge import TeamAvoidEdge
from app.models.tournament_import import TournamentImport

RW_OS_WKW_REASON = "rw-os:wkw"
GROUP_REASON_PREFIX = "group:"


@dataclass(frozen=True)
class WhoKnowsWhoConnection:
    draw_kind: str
    team_a_key: str
    team_b_key: str

    def to_dict(self) -> dict[str, str]:
        return {
            "drawKind": self.draw_kind,
            "teamAKey": self.team_a_key,
            "teamBKey": self.team_b_key,
        }


@dataclass
class WkwEdgeSyncResult:
    current: int = 0
    added: int = 0
    removed: int = 0
    unresolved: list[dict[str, Any]] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.unresolved is None:
            self.unresolved = []

    def to_dict(self) -> dict[str, Any]:
        return {
            "current": self.current,
            "added": self.added,
            "removed": self.removed,
            "unresolved": list(self.unresolved),
        }


def ordered_team_key_pair(left: str, right: str) -> tuple[str, str]:
    a = (left or "").strip()
    b = (right or "").strip()
    if not a or not b or a == b:
        raise ValueError("team keys must be distinct non-empty strings")
    return (a, b) if a < b else (b, a)


def canonicalize_who_knows_who_connections(
    rows: Iterable[dict[str, Any]] | None,
) -> list[WhoKnowsWhoConnection]:
    """Normalize undirected pairs; reciprocal/duplicate edges collapse to one."""
    unique: dict[tuple[str, str, str], WhoKnowsWhoConnection] = {}
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        draw_kind = str(row.get("drawKind") or row.get("draw_kind") or "").strip()
        a = str(row.get("teamAKey") or row.get("team_a_key") or "").strip()
        b = str(row.get("teamBKey") or row.get("team_b_key") or "").strip()
        if not draw_kind or not a or not b or a == b:
            continue
        team_a, team_b = ordered_team_key_pair(a, b)
        key = (draw_kind, team_a, team_b)
        unique[key] = WhoKnowsWhoConnection(draw_kind=draw_kind, team_a_key=team_a, team_b_key=team_b)
    return sorted(
        unique.values(),
        key=lambda edge: (edge.draw_kind, edge.team_a_key, edge.team_b_key),
    )


def parse_who_knows_who_connections(payload: dict[str, Any] | None) -> Optional[list[WhoKnowsWhoConnection]]:
    """Return connections when the payload field is present; None means legacy letter mode."""
    if not isinstance(payload, dict) or "whoKnowsWhoConnections" not in payload:
        return None
    raw = payload.get("whoKnowsWhoConnections")
    if raw is None:
        return []
    if not isinstance(raw, list):
        return []
    return canonicalize_who_knows_who_connections(raw)


def connections_for_hash(connections: Optional[list[WhoKnowsWhoConnection]]) -> list[dict[str, str]]:
    if connections is None:
        return []
    return [edge.to_dict() for edge in connections]


def dump_snapshot_document(
    teams: list[dict[str, Any]],
    *,
    who_knows_who_connections: Optional[list[WhoKnowsWhoConnection]] = None,
) -> str:
    """Persist teams plus optional pairwise graph. Legacy readers use load_snapshot_teams."""
    document: dict[str, Any] = {"teams": teams}
    if who_knows_who_connections is not None:
        document["whoKnowsWhoConnections"] = [edge.to_dict() for edge in who_knows_who_connections]
    return json.dumps(document)


def load_snapshot_document(raw_json: str | None) -> dict[str, Any]:
    raw = json.loads(raw_json or "[]")
    if isinstance(raw, list):
        return {"teams": raw, "whoKnowsWhoConnections": None}
    if isinstance(raw, dict):
        connections = raw.get("whoKnowsWhoConnections")
        return {
            "teams": raw.get("teams") or [],
            "whoKnowsWhoConnections": (
                canonicalize_who_knows_who_connections(connections) if "whoKnowsWhoConnections" in raw else None
            ),
        }
    return {"teams": [], "whoKnowsWhoConnections": None}


def load_snapshot_teams(import_row: TournamentImport) -> list[dict[str, Any]]:
    return list(load_snapshot_document(import_row.snapshot_json).get("teams") or [])


def load_snapshot_connections(import_row: TournamentImport) -> Optional[list[WhoKnowsWhoConnection]]:
    return load_snapshot_document(import_row.snapshot_json).get("whoKnowsWhoConnections")


def is_group_reason(reason: Optional[str]) -> bool:
    return bool(reason and str(reason).startswith(GROUP_REASON_PREFIX))


def is_rw_os_wkw_reason(reason: Optional[str]) -> bool:
    return (reason or "") == RW_OS_WKW_REASON


def ordered_team_id_pair(left: int, right: int) -> tuple[int, int]:
    return (left, right) if left < right else (right, left)


def resolve_connection_team_ids(
    session: Session,
    *,
    event_id: int,
    team_a_key: str,
    team_b_key: str,
) -> Optional[tuple[int, int]]:
    """Map source team keys to current active Team ids for an event. No name matching."""
    teams = session.exec(
        select(Team).where(
            Team.event_id == event_id,
            Team.source_team_key.in_([team_a_key, team_b_key]),  # type: ignore[arg-type]
        )
    ).all()
    by_key = {
        team.source_team_key: team
        for team in teams
        if team.source_team_key and team.id is not None and not team.is_defaulted
    }
    left = by_key.get(team_a_key)
    right = by_key.get(team_b_key)
    if left is None or right is None or left.id is None or right.id is None:
        return None
    return ordered_team_id_pair(left.id, right.id)


def sync_rw_os_wkw_edges_for_event(
    session: Session,
    *,
    event_id: int,
    draw_kind: str,
    connections: list[WhoKnowsWhoConnection],
) -> WkwEdgeSyncResult:
    """Authoritative add/remove sync for RW-OS-owned pairwise edges on one event."""
    desired: set[tuple[int, int]] = set()
    unresolved: list[dict[str, Any]] = []
    for edge in connections:
        if edge.draw_kind != draw_kind:
            continue
        resolved = resolve_connection_team_ids(
            session,
            event_id=event_id,
            team_a_key=edge.team_a_key,
            team_b_key=edge.team_b_key,
        )
        if resolved is None:
            unresolved.append(edge.to_dict())
            continue
        desired.add(resolved)

    existing = session.exec(
        select(TeamAvoidEdge).where(
            TeamAvoidEdge.event_id == event_id,
            TeamAvoidEdge.reason == RW_OS_WKW_REASON,
        )
    ).all()
    actual = {(edge.team_id_a, edge.team_id_b): edge for edge in existing if edge.id is not None}
    actual_keys = set(actual)

    to_add = desired - actual_keys
    to_remove = actual_keys - desired

    for pair in to_remove:
        session.delete(actual[pair])
    for team_a, team_b in sorted(to_add):
        session.add(
            TeamAvoidEdge(
                event_id=event_id,
                team_id_a=team_a,
                team_id_b=team_b,
                reason=RW_OS_WKW_REASON,
            )
        )

    return WkwEdgeSyncResult(
        current=len(desired),
        added=len(to_add),
        removed=len(to_remove),
        unresolved=unresolved,
    )


def load_pairing_avoid_pairs(session: Session, event_id: int, *, pairwise_mode: bool) -> set[tuple[int, int]]:
    """Conflict pairs for the waterfall generator.

    Pairwise mode: RW-OS WKW edges plus non-legacy manual edges; never ``group:*``.
    Legacy letter mode still primarily uses Team.avoid_group on TeamSeed; this helper
    returns non-group edges when callers opt into edge-based pairing.
    """
    edges = session.exec(select(TeamAvoidEdge).where(TeamAvoidEdge.event_id == event_id)).all()
    pairs: set[tuple[int, int]] = set()
    for edge in edges:
        if pairwise_mode and is_group_reason(edge.reason):
            continue
        pairs.add(ordered_team_id_pair(edge.team_id_a, edge.team_id_b))
    return pairs


def event_uses_pairwise_wkw(import_row: TournamentImport) -> bool:
    return load_snapshot_connections(import_row) is not None


def pairwise_wkw_mode_for_event(session: Session, event_id: int) -> bool:
    """True when this event's tournament import carries whoKnowsWhoConnections."""
    from app.models.event import Event
    from app.services.rw_os_import import get_latest_import_for_tournament

    event = session.get(Event, event_id)
    if event is None:
        return False
    import_row = get_latest_import_for_tournament(session, event.tournament_id)
    if import_row is None:
        return False
    return event_uses_pairwise_wkw(import_row)


def avoid_pairs_for_generator(session: Session, event_id: int) -> Optional[set[tuple[int, int]]]:
    """Return edge pairs for pairing when pairwise WKW is authoritative; else None (letter mode)."""
    if not pairwise_wkw_mode_for_event(session, event_id):
        return None
    return load_pairing_avoid_pairs(session, event_id, pairwise_mode=True)


def neighbor_display_names(
    session: Session,
    *,
    event_id: int,
    team_id: int,
) -> list[str]:
    """Current TeamAvoidEdge neighbors for Draw Builder display (pairwise, not letters)."""
    edges = session.exec(
        select(TeamAvoidEdge).where(
            TeamAvoidEdge.event_id == event_id,
            (TeamAvoidEdge.team_id_a == team_id) | (TeamAvoidEdge.team_id_b == team_id),
        )
    ).all()
    neighbor_ids: list[int] = []
    for edge in edges:
        if is_group_reason(edge.reason):
            continue
        other = edge.team_id_b if edge.team_id_a == team_id else edge.team_id_a
        neighbor_ids.append(other)
    if not neighbor_ids:
        return []
    teams = session.exec(select(Team).where(Team.id.in_(neighbor_ids))).all()  # type: ignore[arg-type]
    by_id = {team.id: team for team in teams if team.id is not None}
    labels: list[str] = []
    for nid in sorted(neighbor_ids):
        team = by_id.get(nid)
        if team is None:
            continue
        labels.append((team.display_name or team.name or f"Team {nid}").strip())
    return labels


def count_rw_os_wkw_edges(session: Session, event_id: int) -> int:
    return len(
        session.exec(
            select(TeamAvoidEdge).where(
                TeamAvoidEdge.event_id == event_id,
                TeamAvoidEdge.reason == RW_OS_WKW_REASON,
            )
        ).all()
    )
