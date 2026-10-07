"""Rebuild draws from the current roster without moving scheduled match numbers.

The canonical generator has to insert rows so it can wire feeder ids. Those rows go on a
temporary schedule version. Draw content is then copied onto the live match rows, and the
temporary version is deleted before commit. Live match ids, assignments, and slots stay put.
"""

from __future__ import annotations

import json
import re
from typing import Optional

from sqlmodel import Session, select

from app.models.event import Event
from app.models.match import Match
from app.models.match_assignment import MatchAssignment
from app.models.schedule_slot import ScheduleSlot
from app.models.schedule_version import ScheduleVersion
from app.models.team import Team
from app.models.tournament_import import TournamentImport
from app.services.active_roster import team_is_active
from app.services.draw_plan_engine import (
    DrawPlanSpec,
    build_spec_from_event,
    generate_matches_for_event,
    resolve_event_family,
)
from app.services.post_draw_corrections import match_locked_for_participant_edit
from app.services.rw_os_import import parse_teams

STRUCTURE_REVIEW_MESSAGE = "Bracket structure requires review before draws can be rebuilt."
HEADING = "RW-OS Refreshed + Draws Rebuilt"
SCHEDULE_NOTE = "Match numbers, dates, times, courts, and grid assignments were preserved."
DRAW_DETAIL = "Draw rebuilt using current ratings, seeds, and Who-Knows-Who"

_DRAW_FIELDS = (
    "team_a_id",
    "team_b_id",
    "placeholder_side_a",
    "placeholder_side_b",
    "source_a_role",
    "source_b_role",
    "match_type",
    "round_number",
    "round_index",
    "sequence_in_round",
    "consolation_tier",
    "placement_type",
)
_STALE_ENTRY = re.compile(r"^(?:SEED[_ ]\d+|TBD)$", re.IGNORECASE)
_NOT_ENTRY = re.compile(r"^(?:WFSEED:|W\(|L\(|WINNER:|LOSER:|TBD:)", re.IGNORECASE)


class DrawRebuildError(Exception):
    def __init__(
        self,
        message: str,
        *,
        code: str,
        event_name: Optional[str] = None,
        match_numbers: Optional[list[int]] = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.event_name = event_name
        self.match_numbers = match_numbers or []


def rebuild_tournament_draws(session: Session, import_row: TournamentImport) -> dict:
    """Replace draw content on the scheduled matches. Caller commits.

    Raises DrawRebuildError before any live row is modified when the roster, seeds,
    capacity, protected play, or match-code topology cannot be rebuilt safely.
    """
    live_version_id = _scheduled_version_id(session, import_row.tournament_id)
    events = list(session.exec(select(Event).where(Event.tournament_id == import_row.tournament_id)).all())
    rebuildable: list[tuple[Event, list[Match]]] = []
    for event in events:
        if event.id is None:
            continue
        matches = list(session.exec(select(Match).where(Match.event_id == event.id)).all())
        if not matches:
            continue
        on_live = [match for match in matches if match.schedule_version_id == live_version_id]
        if len(on_live) != len(matches):
            raise DrawRebuildError(STRUCTURE_REVIEW_MESSAGE, code="structure_review", event_name=event.name)
        rebuildable.append((event, on_live))
    if not rebuildable:
        raise DrawRebuildError(STRUCTURE_REVIEW_MESSAGE, code="structure_review")

    _reject_protected_play(session, rebuildable)
    for event, _matches in rebuildable:
        _require_capacity_and_seeds(session, import_row, event)

    schedule_before = _schedule_fingerprint(session, live_version_id)
    temp_version = _temporary_version(session, import_row.tournament_id)
    generated_by_event: dict[int, list[Match]] = {}
    existing_codes: set[str] = set()
    session._allow_match_generation = True  # type: ignore[attr-defined]
    try:
        for event, _live_matches in rebuildable:
            spec = build_spec_from_event(event)
            linked_ids = _linked_team_ids(session, event)
            try:
                generate_matches_for_event(session, temp_version.id, spec, linked_ids, existing_codes)
            except DrawRebuildError:
                raise
            except Exception as exc:
                raise DrawRebuildError(
                    f"Draw generation failed for {event.name}.",
                    code="generation_failed",
                    event_name=event.name,
                ) from exc
            generated_by_event[event.id] = list(
                session.exec(
                    select(Match).where(
                        Match.schedule_version_id == temp_version.id,
                        Match.event_id == event.id,
                    )
                ).all()
            )
    finally:
        session._allow_match_generation = False  # type: ignore[attr-defined]

    for event, live_matches in rebuildable:
        _require_same_match_codes(event, live_matches, generated_by_event[event.id])
        _copy_draw_content(session, event, live_matches, generated_by_event[event.id])

    session.flush()
    for event, live_matches in rebuildable:
        _validate_rebuilt_event(session, event, live_matches)

    schedule_after = _schedule_fingerprint(session, live_version_id)
    if schedule_after != schedule_before:
        raise DrawRebuildError(
            "Schedule anchors changed during draw rebuild.",
            code="validation_failed",
        )
    _delete_temporary_version(session, temp_version)
    return _success_payload(session, rebuildable)


def _scheduled_version_id(session: Session, tournament_id: int) -> int:
    assigned_versions = set(
        session.exec(
            select(MatchAssignment.schedule_version_id)
            .join(Match, Match.id == MatchAssignment.match_id)
            .where(Match.tournament_id == tournament_id)
        ).all()
    )
    if len(assigned_versions) == 1:
        return next(iter(assigned_versions))
    if len(assigned_versions) > 1:
        raise DrawRebuildError(STRUCTURE_REVIEW_MESSAGE, code="structure_review")
    match_versions = set(
        session.exec(select(Match.schedule_version_id).where(Match.tournament_id == tournament_id)).all()
    )
    if len(match_versions) != 1:
        raise DrawRebuildError(STRUCTURE_REVIEW_MESSAGE, code="structure_review")
    return next(iter(match_versions))


def _reject_protected_play(session: Session, rebuildable: list[tuple[Event, list[Match]]]) -> None:
    blocked: list[tuple[str, list[int]]] = []
    for event, matches in rebuildable:
        numbers = sorted(
            match.id for match in matches if match.id is not None and match_locked_for_participant_edit(session, match)
        )
        if numbers:
            blocked.append((event.name, numbers))
    if not blocked:
        return
    parts = [f"{name} match {', '.join('#' + str(number) for number in numbers)}" for name, numbers in blocked]
    numbers = [number for _name, group in blocked for number in group]
    raise DrawRebuildError(
        "Competitive play has started, so draws were not rebuilt. Blocking " + "; ".join(parts) + ".",
        code="protected_play",
        event_name=blocked[0][0],
        match_numbers=numbers,
    )


def _require_capacity_and_seeds(session: Session, import_row: TournamentImport, event: Event) -> None:
    active = _active_teams(session, event)
    expected = event.team_count or 0
    if len(active) != expected or expected < 2:
        raise DrawRebuildError(STRUCTURE_REVIEW_MESSAGE, code="structure_review", event_name=event.name)
    try:
        seeds = sorted(team.seed for team in active)
    except TypeError:
        seeds = []
    if seeds != list(range(1, expected + 1)):
        raise DrawRebuildError(STRUCTURE_REVIEW_MESSAGE, code="structure_review", event_name=event.name)
    snapshot_by_key = {team.team_key: team for team in parse_teams(json.loads(import_row.snapshot_json or "[]"))}
    for team in active:
        snapshot = snapshot_by_key.get(team.source_team_key or "")
        if snapshot is None:
            raise DrawRebuildError(
                "RW-OS roster could not be reconciled.",
                code="roster_reconciliation_incomplete",
                event_name=event.name,
            )
        if _avoid_text(team.avoid_group) != _avoid_text(snapshot.avoid_group):
            raise DrawRebuildError(
                "Who-Knows-Who could not be reconciled before draws were rebuilt.",
                code="roster_reconciliation_incomplete",
                event_name=event.name,
            )


def _avoid_text(value: Optional[str]) -> Optional[str]:
    text = (value or "").strip()
    return text or None


def _active_teams(session: Session, event: Event) -> list[Team]:
    return [
        team
        for team in session.exec(select(Team).where(Team.event_id == event.id)).all()
        if team_is_active(team) and team.source_team_key
    ]


def _linked_team_ids(session: Session, event: Event) -> list[int]:
    ordered = sorted(
        _active_teams(session, event),
        key=lambda team: (team.seed is None, team.seed or 0, team.id or 0),
    )
    return [team.id for team in ordered if team.id is not None]


def _temporary_version(session: Session, tournament_id: int) -> ScheduleVersion:
    current_max = session.exec(
        select(ScheduleVersion.version_number).where(ScheduleVersion.tournament_id == tournament_id)
    ).all()
    version = ScheduleVersion(
        tournament_id=tournament_id,
        version_number=(max(current_max) if current_max else 0) + 1,
        status="draft",
        notes="rw-os-draw-rebuild-temp",
    )
    session.add(version)
    session.flush()
    return version


def _require_same_match_codes(event: Event, live_matches: list[Match], generated: list[Match]) -> None:
    live_codes = [match.match_code for match in live_matches]
    generated_codes = [match.match_code for match in generated]
    if len(live_codes) != len(set(live_codes)) or len(generated_codes) != len(set(generated_codes)):
        raise DrawRebuildError(STRUCTURE_REVIEW_MESSAGE, code="structure_review", event_name=event.name)
    if set(live_codes) != set(generated_codes):
        raise DrawRebuildError(STRUCTURE_REVIEW_MESSAGE, code="structure_review", event_name=event.name)


def _copy_draw_content(session: Session, event: Event, live_matches: list[Match], generated: list[Match]) -> None:
    live_by_code = {match.match_code: match for match in live_matches}
    temp_by_id = {match.id: match for match in generated if match.id is not None}
    for temp in generated:
        live = live_by_code[temp.match_code]
        for field_name in _DRAW_FIELDS:
            setattr(live, field_name, getattr(temp, field_name))
        live.source_match_a_id = _remap_feeder(event, temp.source_match_a_id, temp_by_id, live_by_code)
        live.source_match_b_id = _remap_feeder(event, temp.source_match_b_id, temp_by_id, live_by_code)
        session.add(live)


def _remap_feeder(
    event: Event,
    temp_source_id: Optional[int],
    temp_by_id: dict[int, Match],
    live_by_code: dict[str, Match],
) -> Optional[int]:
    if temp_source_id is None:
        return None
    source = temp_by_id.get(temp_source_id)
    if source is None or not source.match_code or source.match_code not in live_by_code:
        raise DrawRebuildError(
            f"Feeder mapping failed for {event.name}.",
            code="feeder_mapping",
            event_name=event.name,
        )
    live = live_by_code[source.match_code]
    if live.id is None:
        raise DrawRebuildError(
            f"Feeder mapping failed for {event.name}.",
            code="feeder_mapping",
            event_name=event.name,
        )
    return live.id


def _validate_rebuilt_event(session: Session, event: Event, live_matches_before: list[Match]) -> None:
    live_version_id = live_matches_before[0].schedule_version_id
    live_matches = list(
        session.exec(
            select(Match).where(
                Match.event_id == event.id,
                Match.schedule_version_id == live_version_id,
            )
        ).all()
    )
    before_ids = {match.id for match in live_matches_before}
    after_ids = {match.id for match in live_matches}
    if before_ids != after_ids or len(live_matches) != len(live_matches_before):
        raise DrawRebuildError(
            "Draw validation failed after rebuild.",
            code="validation_failed",
            event_name=event.name,
        )
    live_ids = {match.id for match in live_matches if match.id is not None}
    active = _active_teams(session, event)
    active_ids = {team.id for team in active if team.id is not None}
    entry_ids: list[int] = []
    saw_wf_entry = False
    for match in live_matches:
        for side in ("A", "B"):
            team_id = match.team_a_id if side == "A" else match.team_b_id
            placeholder = match.placeholder_side_a if side == "A" else match.placeholder_side_b
            source_id = match.source_match_a_id if side == "A" else match.source_match_b_id
            if str(placeholder or "").upper().startswith("WFSEED:") and team_id is not None:
                raise DrawRebuildError(
                    "Draw validation failed after rebuild.",
                    code="validation_failed",
                    event_name=event.name,
                )
            if source_id is not None and source_id not in live_ids:
                raise DrawRebuildError(
                    "Draw validation failed after rebuild.",
                    code="validation_failed",
                    event_name=event.name,
                )
            if not _is_entry_side(match, side):
                continue
            saw_wf_entry = saw_wf_entry or (match.match_type or "").upper() == "WF"
            if team_id is None or _STALE_ENTRY.match((placeholder or "").strip()):
                raise DrawRebuildError(
                    "Draw validation failed after rebuild.",
                    code="validation_failed",
                    event_name=event.name,
                )
            entry_ids.append(team_id)
    if saw_wf_entry:
        if len(entry_ids) != len(set(entry_ids)) or set(entry_ids) != active_ids:
            raise DrawRebuildError(
                "Draw validation failed after rebuild.",
                code="validation_failed",
                event_name=event.name,
            )


def _is_entry_side(match: Match, side: str) -> bool:
    source_id = match.source_match_a_id if side == "A" else match.source_match_b_id
    placeholder = match.placeholder_side_a if side == "A" else match.placeholder_side_b
    if source_id is not None or _NOT_ENTRY.match((placeholder or "").strip()):
        return False
    kind = (match.match_type or "").upper()
    if kind == "WF":
        return (match.round_index or 0) == 1
    return kind == "RR"


def _schedule_fingerprint(session: Session, version_id: int) -> dict:
    matches = list(session.exec(select(Match).where(Match.schedule_version_id == version_id)).all())
    fingerprint = {}
    for match in matches:
        assignment = session.exec(select(MatchAssignment).where(MatchAssignment.match_id == match.id)).first()
        slot = session.get(ScheduleSlot, assignment.slot_id) if assignment is not None else None
        fingerprint[match.id] = {
            "match_code": match.match_code,
            "schedule_version_id": match.schedule_version_id,
            "assignment_id": None if assignment is None else assignment.id,
            "slot_id": None if assignment is None else assignment.slot_id,
            "locked": None if assignment is None else assignment.locked,
            "day": None if slot is None else slot.day_date.isoformat(),
            "start": None if slot is None or slot.start_time is None else slot.start_time.isoformat(),
            "end": None if slot is None or slot.end_time is None else slot.end_time.isoformat(),
            "court_number": None if slot is None else slot.court_number,
            "court_label": None if slot is None else slot.court_label,
            "manual_only": None if slot is None else slot.is_manual_only,
            "status": match.status,
            "runtime_status": match.runtime_status,
            "winner_team_id": match.winner_team_id,
            "score_json": match.score_json,
            "started_at": None if match.started_at is None else match.started_at.isoformat(),
            "completed_at": None if match.completed_at is None else match.completed_at.isoformat(),
        }
    return fingerprint


def _delete_temporary_version(session: Session, version: ScheduleVersion) -> None:
    temp_matches = list(session.exec(select(Match).where(Match.schedule_version_id == version.id)).all())
    for match in temp_matches:
        match.source_match_a_id = None
        match.source_match_b_id = None
        session.add(match)
    session.flush()
    for match in temp_matches:
        session.delete(match)
    session.flush()
    session.delete(version)
    session.flush()


def _success_payload(session: Session, rebuildable: list[tuple[Event, list[Match]]]) -> dict:
    events = []
    for event, _matches in rebuildable:
        spec = build_spec_from_event(event)
        events.append(
            {
                "eventId": event.id,
                "name": event.name,
                "teamCount": len(_active_teams(session, event)),
                "structure": _structure_label(spec),
                "detail": DRAW_DETAIL,
                "schedulePreserved": True,
            }
        )
    return {
        "ok": True,
        "heading": HEADING,
        "events": events,
        "scheduleNote": SCHEDULE_NOTE,
    }


def _structure_label(spec: DrawPlanSpec) -> str:
    family = resolve_event_family(spec)
    if spec.waterfall_rounds > 0 and family != "RR_ONLY":
        return f"{spec.team_count}-team waterfall"
    if family == "RR_ONLY":
        return f"{spec.team_count}-team round robin"
    return f"{spec.team_count}-team draw"
