"""Rebuild draws from the current roster without moving scheduled match numbers.

The canonical generator has to insert rows so it can wire feeder ids. Those rows go on a
temporary schedule version. Draw content is then copied onto the live match rows, and the
temporary version is deleted before commit. Live match ids, assignments, and slots stay put.

Only the authoritative operational schedule version is rebuilt. A cloned schedule keeps its
assignments; that historical copy is not a second current schedule.

Follow-up: normal Check / Refresh still loads draw matches by event and team, with no
schedule-version filter, so it can still see a historical clone. Do not copy that here.
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from typing import Optional

from sqlmodel import Session, select

from app.models.event import Event
from app.models.match import Match
from app.models.match_assignment import MatchAssignment
from app.models.schedule_slot import ScheduleSlot
from app.models.schedule_version import ScheduleVersion
from app.models.team import Team
from app.models.team_avoid_edge import TeamAvoidEdge
from app.models.tournament import Tournament
from app.models.tournament_import import TournamentImport
from app.services.active_roster import team_is_active
from app.services.display_board import DESK_DRAFT_TAG
from app.services.draw_plan_engine import (
    DrawPlanSpec,
    build_spec_from_event,
    generate_matches_for_event,
    resolve_event_family,
)
from app.services.post_draw_corrections import match_locked_for_participant_edit
from app.services.rw_os_import import parse_teams
from app.services.rw_os_wkw import count_rw_os_wkw_edges

logger = logging.getLogger(__name__)

STRUCTURE_REVIEW_MESSAGE = "Bracket structure requires review before draws can be rebuilt."
HEADING = "RW-OS Refreshed + Draws Rebuilt"
SCHEDULE_NOTE = "Match numbers, dates, times, courts, and grid assignments were preserved."
DRAW_DETAIL_WITH_WKW = "Draw rebuilt using current ratings, seeds, and Who-Knows-Who."
DRAW_DETAIL_NO_WKW = "Draw rebuilt using current ratings and seeds. No Who-Knows-Who connections were available."
DRAW_DETAIL = DRAW_DETAIL_WITH_WKW

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
_BRACKET_CODE = re.compile(r"^B(.+)_(M|C)(\d+)$")
# Same staff order as the draw QR board: Women's, then Mixed, then event name.
_CATEGORY_ORDER = {"womens": 0, "mixed": 1}
_GUARANTEE_CODES = {
    4: frozenset(f"M{number}" for number in range(1, 8)) | frozenset({"C1", "C2"}),
    5: frozenset(f"M{number}" for number in range(1, 8)) | frozenset(f"C{number}" for number in range(1, 6)),
}


class DrawRebuildError(Exception):
    def __init__(
        self,
        message: str,
        *,
        code: str,
        event_name: Optional[str] = None,
        match_numbers: Optional[list[int]] = None,
        details: Optional[dict] = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.event_name = event_name
        self.match_numbers = match_numbers or []
        self.details = details or {}


def rebuild_tournament_draws(session: Session, import_row: TournamentImport) -> dict:
    """Replace draw content on the scheduled matches. Caller commits.

    Raises DrawRebuildError before any live row is modified when the roster, seeds,
    capacity, protected play, or match-code topology cannot be rebuilt safely.
    """
    live_version_id = _authoritative_version_id(session, import_row.tournament_id)
    events = _ordered_events(
        list(session.exec(select(Event).where(Event.tournament_id == import_row.tournament_id)).all())
    )
    rebuildable: list[tuple[Event, list[Match]]] = []
    for event in events:
        if event.id is None:
            continue
        matches = list(
            session.exec(
                select(Match).where(
                    Match.event_id == event.id,
                    Match.schedule_version_id == live_version_id,
                )
            ).all()
        )
        if not matches:
            continue
        rebuildable.append((event, matches))
    if not rebuildable:
        raise _structure_error("No draws are available to rebuild.", code="structure_review")

    _reject_protected_play(session, rebuildable)
    for event, _matches in rebuildable:
        _require_capacity_and_seeds(session, import_row, event)

    specs = {event.id: _spec_for_rebuild(event, live_matches) for event, live_matches in rebuildable}
    schedule_before = _schedule_fingerprint(session, live_version_id)
    temp_version = _temporary_version(session, import_row.tournament_id)
    generated_by_event: dict[int, list[Match]] = {}
    existing_codes: set[str] = set()
    session._allow_match_generation = True  # type: ignore[attr-defined]
    try:
        for event, _live_matches in rebuildable:
            spec = specs[event.id]
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


def _authoritative_version_id(session: Session, tournament_id: int) -> int:
    """The schedule Tournament Desk is operating, not every version that still has assignments.

    Desk draft, then the published pointer, then the latest final by version number.
    Those are the same signals as the desk and display-board resolvers. A second assigned
    version is a historical clone unless it is itself the other current pointer.
    """
    tournament = session.get(Tournament, tournament_id)
    if tournament is None:
        raise _ambiguous_schedule_error(desk_ids=[], published_id=None, mismatch=False)

    desk_drafts = list(
        session.exec(
            select(ScheduleVersion)
            .where(
                ScheduleVersion.tournament_id == tournament_id,
                ScheduleVersion.status == "draft",
                ScheduleVersion.notes == DESK_DRAFT_TAG,
            )
            .order_by(ScheduleVersion.version_number.desc())
        ).all()
    )
    published = _published_version(session, tournament)
    published_id = None if published is None else published.id

    if len(desk_drafts) > 1:
        raise _ambiguous_schedule_error(
            desk_ids=[version.id for version in desk_drafts if version.id is not None],
            published_id=published_id,
            mismatch=False,
        )

    desk = desk_drafts[0] if desk_drafts else None
    if desk is not None and published is not None and desk.id != published.id:
        if _version_has_assignments(session, desk.id) and _version_has_assignments(session, published.id):
            raise _ambiguous_schedule_error(desk_ids=[desk.id], published_id=published.id, mismatch=True)
        if _version_has_assignments(session, desk.id) or not _version_has_assignments(session, published.id):
            logger.info(
                "draw rebuild authoritative schedule_version_id=%s tournament_id=%s",
                desk.id,
                tournament_id,
            )
            return desk.id
        logger.info(
            "draw rebuild authoritative schedule_version_id=%s tournament_id=%s",
            published.id,
            tournament_id,
        )
        return published.id

    if desk is not None and desk.id is not None:
        logger.info(
            "draw rebuild authoritative schedule_version_id=%s tournament_id=%s",
            desk.id,
            tournament_id,
        )
        return desk.id
    if published is not None and published.id is not None:
        logger.info(
            "draw rebuild authoritative schedule_version_id=%s tournament_id=%s",
            published.id,
            tournament_id,
        )
        return published.id

    finals = list(
        session.exec(
            select(ScheduleVersion)
            .where(
                ScheduleVersion.tournament_id == tournament_id,
                ScheduleVersion.status == "final",
            )
            .order_by(ScheduleVersion.version_number.desc())
        ).all()
    )
    if finals:
        leaders = [version for version in finals if version.version_number == finals[0].version_number]
        if len(leaders) != 1 or leaders[0].id is None:
            raise _ambiguous_schedule_error(desk_ids=[], published_id=None, mismatch=False)
        logger.info(
            "draw rebuild authoritative schedule_version_id=%s tournament_id=%s",
            leaders[0].id,
            tournament_id,
        )
        return leaders[0].id

    only = list(session.exec(select(ScheduleVersion).where(ScheduleVersion.tournament_id == tournament_id)).all())
    if len(only) == 1 and only[0].id is not None:
        logger.info(
            "draw rebuild authoritative schedule_version_id=%s tournament_id=%s",
            only[0].id,
            tournament_id,
        )
        return only[0].id
    raise _ambiguous_schedule_error(desk_ids=[], published_id=published_id, mismatch=False)


def _published_version(session: Session, tournament: Tournament) -> Optional[ScheduleVersion]:
    if not tournament.public_schedule_version_id:
        return None
    published = session.get(ScheduleVersion, tournament.public_schedule_version_id)
    if published is None or published.tournament_id != tournament.id:
        return None
    return published


def _version_has_assignments(session: Session, version_id: Optional[int]) -> bool:
    if version_id is None:
        return False
    return (
        session.exec(
            select(MatchAssignment.id)
            .join(Match, Match.id == MatchAssignment.match_id)
            .where(Match.schedule_version_id == version_id)
            .limit(1)
        ).first()
        is not None
    )


def _ambiguous_schedule_error(
    *,
    desk_ids: list[int],
    published_id: Optional[int],
    mismatch: bool,
) -> DrawRebuildError:
    desk_text = ", ".join(str(version_id) for version_id in desk_ids) if desk_ids else "none"
    published_text = str(published_id) if published_id is not None else "none"
    if mismatch:
        lead = (
            "The current Desk schedule and published schedule do not match.\n\n"
            f"Desk version: {desk_text}\n"
            f"Published version: {published_text}"
        )
    else:
        lead = (
            "The current operational schedule could not be determined safely.\n\n"
            f"Desk schedule: {desk_text}\n"
            f"Published schedule: {published_text}"
        )
    return DrawRebuildError(
        f"{lead}\n\nSelect/publish the intended schedule before rebuilding draws.",
        code="schedule_version_ambiguous",
        details={"deskVersionIds": desk_ids, "publishedVersionId": published_id},
    )


def _reject_protected_play(session: Session, rebuildable: list[tuple[Event, list[Match]]]) -> None:
    blocked: list[tuple[str, list[int]]] = []
    for event, matches in rebuildable:
        numbers = sorted(
            match.id
            for match in matches
            if match.id is not None
            and match_locked_for_participant_edit(session, match, schedule_version_id=match.schedule_version_id)
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
        raise DrawRebuildError(
            f"{event.name} roster does not fit the approved structure.\n\n"
            f"Active teams: {len(active)}\n"
            f"Approved capacity: {expected}",
            code="roster_count_mismatch",
            event_name=event.name,
            details={"activeTeams": len(active), "approvedCapacity": expected},
        )
    _require_seed_range(event, active, expected)
    from app.models.event import EventCategory
    from app.services.rw_os_import import import_snapshot_teams
    from app.services.rw_os_wkw import (
        RW_OS_WKW_REASON,
        applicable_rw_os_wkw_pairs_for_event,
        load_snapshot_connections,
        load_tournament_team_locations,
    )
    from app.services.structure_events import event_category_for_draw_kind

    snapshot_by_key = {team.team_key: team for team in parse_teams(import_snapshot_teams(import_row))}
    for team in active:
        snapshot = snapshot_by_key.get(team.source_team_key or "")
        if snapshot is None:
            raise DrawRebuildError(
                "RW-OS roster could not be reconciled.",
                code="roster_reconciliation_incomplete",
                event_name=event.name,
            )
    connections = load_snapshot_connections(import_row)
    if connections is None:
        for team in active:
            snapshot = snapshot_by_key.get(team.source_team_key or "")
            if snapshot is None:
                continue
            if _avoid_text(team.avoid_group) != _avoid_text(snapshot.avoid_group):
                raise DrawRebuildError(
                    "Who-Knows-Who could not be reconciled before draws were rebuilt.",
                    code="roster_reconciliation_incomplete",
                    event_name=event.name,
                )
        return
    # Pairwise mode: event constraints must match the same-event projection of the
    # tournament-wide snapshot graph. Cross-bracket / other-event edges are retained
    # in the snapshot but are not applicable to this event.

    category = event.category.value if isinstance(event.category, EventCategory) else str(event.category)
    draw_kind = None
    for kind in ("mixed", "womens"):
        mapped = event_category_for_draw_kind(kind)
        if mapped is not None and mapped.value == category:
            draw_kind = kind
            break
    if draw_kind is None:
        return
    if event.id is None:
        return
    locations = load_tournament_team_locations(session, import_row.tournament_id)
    applicability = applicable_rw_os_wkw_pairs_for_event(
        connections,
        locations,
        event_id=event.id,
        draw_kind=draw_kind,
    )
    if applicability.unresolved:
        sample = applicability.unresolved[0]
        raise DrawRebuildError(
            "Who-Knows-Who could not be reconciled before draws were rebuilt.\n\n"
            f"Unresolved connection: {sample.get('teamAKey')}–{sample.get('teamBKey')} "
            f"({sample.get('reason')}).",
            code="roster_reconciliation_incomplete",
            event_name=event.name,
            details={
                "unresolvedCount": len(applicability.unresolved),
                "unresolved": applicability.unresolved[:20],
                "skippedNonApplicable": applicability.skipped_non_applicable,
            },
        )
    desired = applicability.desired_pairs
    actual_edges = session.exec(
        select(TeamAvoidEdge).where(
            TeamAvoidEdge.event_id == event.id,
            TeamAvoidEdge.reason == RW_OS_WKW_REASON,
        )
    ).all()
    actual = {(edge.team_id_a, edge.team_id_b) for edge in actual_edges}
    if actual != desired:
        raise DrawRebuildError(
            "Who-Knows-Who could not be reconciled before draws were rebuilt.\n\n"
            f"Applicable event edges expected: {len(desired)}\n"
            f"Stored RW-OS-owned edges: {len(actual)}",
            code="roster_reconciliation_incomplete",
            event_name=event.name,
            details={
                "expectedCount": len(desired),
                "actualCount": len(actual),
                "missingPairs": sorted(desired - actual),
                "extraPairs": sorted(actual - desired),
                "skippedNonApplicable": applicability.skipped_non_applicable,
            },
        )


def _require_seed_range(event: Event, active: list[Team], expected: int) -> None:
    numeric = [team.seed for team in active if isinstance(team.seed, int)]
    unseeded = len(active) - len(numeric)
    counts = Counter(numeric)
    duplicates = sorted(seed for seed, count in counts.items() if count > 1)
    present = set(numeric)
    expected_seeds = set(range(1, expected + 1))
    missing = sorted(expected_seeds - present)
    unexpected = sorted(present - expected_seeds)
    if not unseeded and not duplicates and not missing and not unexpected:
        return
    lines = [f"{event.name} seed metadata is incomplete.", "", f"Expected seeds: 1–{expected}"]
    if missing:
        lines.append("Missing: " + ", ".join(str(seed) for seed in missing))
    if unexpected:
        lines.append("Unexpected: " + ", ".join(str(seed) for seed in unexpected))
    if duplicates:
        lines.append("Duplicate: " + ", ".join(str(seed) for seed in duplicates))
    if unseeded:
        lines.append(f"Unseeded teams: {unseeded}")
    raise DrawRebuildError(
        "\n".join(lines),
        code="seed_metadata_mismatch",
        event_name=event.name,
        details={
            "expectedSeeds": f"1-{expected}",
            "missingSeeds": missing,
            "unexpectedSeeds": unexpected,
            "duplicateSeeds": duplicates,
            "unseededTeams": unseeded,
        },
    )


def _spec_for_rebuild(event: Event, live_matches: list[Match]) -> DrawPlanSpec:
    """Use a stored guarantee. Infer one from the live draw only when it is missing."""
    spec = build_spec_from_event(event)
    inferred = _infer_live_guarantee(spec, live_matches)
    stored = event.guarantee_selected
    if stored is not None:
        if inferred is not None and int(stored) != inferred:
            raise DrawRebuildError(
                f"{event.name} draw structure does not match its stored guarantee.\n\n"
                f"Stored guarantee: {int(stored)}\n"
                f"Existing draw topology: guarantee {inferred}\n\n"
                f"{STRUCTURE_REVIEW_MESSAGE}",
                code="guarantee_conflict",
                event_name=event.name,
                details={"storedGuarantee": int(stored), "liveGuarantee": inferred},
            )
        spec.guarantee = int(stored)
        return spec
    if inferred is None:
        raise _structure_error(
            f"{event.name} draw topology does not establish a supported guarantee.",
            code="structure_review",
            event_name=event.name,
        )
    logger.info(
        "draw rebuild inferred guarantee=%s for event=%s because guarantee_selected is null",
        inferred,
        event.name,
    )
    spec.guarantee = inferred
    return spec


def _infer_live_guarantee(spec: DrawPlanSpec, live_matches: list[Match]) -> Optional[int]:
    """Return 4 or 5 when every bracket has that exact consolation set. Otherwise None."""
    if resolve_event_family(spec) != "WF_TO_BRACKETS_8":
        return None
    labels = _expected_bracket_labels(spec.team_count)
    if labels is None:
        return None
    by_label = {label: set() for label in labels}
    prefix = spec.match_code_prefix
    for match in live_matches:
        code = match.match_code or ""
        if not code.startswith(prefix):
            continue
        parsed = _BRACKET_CODE.match(code[len(prefix) :])
        if parsed is None:
            continue
        label = parsed.group(1)
        if label not in by_label:
            return None
        by_label[label].add(f"{parsed.group(2)}{int(parsed.group(3))}")
    signatures = {frozenset(codes) for codes in by_label.values()}
    if len(signatures) != 1:
        return None
    signature = next(iter(signatures))
    for guarantee, codes in _GUARANTEE_CODES.items():
        if signature == codes:
            return guarantee
    return None


def _expected_bracket_labels(team_count: int) -> Optional[list[str]]:
    """Bracket labels produced by the waterfall-to-brackets generator."""
    if team_count == 24:
        return ["1", "2", "3"]
    if team_count == 8:
        bracket_count = 1
    elif team_count in (12, 16):
        bracket_count = 2
    elif team_count == 32:
        bracket_count = 4
    else:
        return None
    return ["WW", "WL", "LW", "LL"][:bracket_count]


def _category_key(event: Event) -> str:
    category = event.category
    if hasattr(category, "value"):
        return str(category.value)
    return str(category)


def _ordered_events(events: list[Event]) -> list[Event]:
    return sorted(
        events,
        key=lambda event: (
            _CATEGORY_ORDER.get(_category_key(event).strip().lower(), 99),
            event.name or "",
            event.id or 0,
        ),
    )


def _structure_error(lead: str, *, code: str, event_name: Optional[str] = None) -> DrawRebuildError:
    return DrawRebuildError(
        f"{lead}\n\n{STRUCTURE_REVIEW_MESSAGE}",
        code=code,
        event_name=event_name,
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
    live_codes = [match.match_code or "" for match in live_matches]
    generated_codes = [match.match_code or "" for match in generated]
    live_only = sorted(set(live_codes) - set(generated_codes))
    generated_only = sorted(set(generated_codes) - set(live_codes))
    duplicate = len(live_codes) != len(set(live_codes)) or len(generated_codes) != len(set(generated_codes))
    if not duplicate and not live_only and not generated_only:
        return
    logger.warning(
        "draw rebuild match-code mismatch event=%s existing=%s generated=%s live_only=%s generated_only=%s",
        event.name,
        len(live_codes),
        len(generated_codes),
        live_only,
        generated_only,
    )
    if duplicate:
        message = f"{event.name} draw has duplicate match codes.\n\n{STRUCTURE_REVIEW_MESSAGE}"
    else:
        message = (
            f"{event.name} draw topology does not match the generated structure.\n\n"
            f"Existing matches: {len(live_codes)}\n"
            f"Generated matches: {len(generated_codes)}"
        )
    raise DrawRebuildError(
        message,
        code="match_code_mismatch",
        event_name=event.name,
        details={
            "existingMatchCount": len(live_codes),
            "generatedMatchCount": len(generated_codes),
            "liveOnlyMatchCodes": live_only,
            "generatedOnlyMatchCodes": generated_only,
        },
    )


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
        wkw_count = count_rw_os_wkw_edges(session, event.id) if event.id is not None else 0
        events.append(
            {
                "eventId": event.id,
                "name": event.name,
                "teamCount": len(_active_teams(session, event)),
                "structure": _structure_label(spec),
                "detail": DRAW_DETAIL_WITH_WKW if wkw_count > 0 else DRAW_DETAIL_NO_WKW,
                "whoKnowsWhoConnections": wkw_count,
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
