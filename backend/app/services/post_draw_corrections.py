"""
Post-draw staff corrections: swap two teams, move a team between events, edit WF R1 matchups.

These operations must never regenerate draws, rebuild brackets, or rewrite
unrelated matches. Match IDs, round/stage, and schedule assignments stay intact.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal, Optional

from sqlalchemy import or_
from sqlmodel import Session, select

from app.models.event import Event
from app.models.match import Match
from app.models.match_assignment import MatchAssignment
from app.models.schedule_slot import ScheduleSlot
from app.models.schedule_version import ScheduleVersion
from app.models.team import Team
from app.models.team_avoid_edge import TeamAvoidEdge
from app.models.team_player import TeamPlayer
from app.models.tournament import Tournament

logger = logging.getLogger(__name__)

DRAWS_EXIST_WARNING = (
    "Draws already exist for one or both events. Moving this team will NOT regenerate "
    "either draw. The team may need to be manually removed or placed in the appropriate WF matchup."
)
COMPLETED_MATCH_WARNING = (
    "This match already has a result or has advanced a team. "
    "Changing participants may invalidate downstream bracket data."
)
MOVE_BLOCKED_PLAYED_SOURCE = (
    "This team cannot be moved because it has already started play, recorded a result, "
    "or affected downstream bracket advancement in the current division."
)
DESTINATION_DRAW_EXISTS_MESSAGE = "Destination draw already exists. Place this team manually using Edit WF Matchup."
SEED_CLEARED_WARNING = "Seed was cleared because that seed is already in use in the destination event."
WHO_KNOWS_WHO_WARNING = (
    "Source event who-knows-who restrictions were removed. Configure destination restrictions separately if needed."
)
DEFAULTED_TEAM_ERROR = "Defaulted teams cannot be placed in a WF Round 1 matchup."
EMPTY_WF_PLACEHOLDER = "TBD"
SWAP_BLOCKED_PLAYED = (
    "These teams cannot be swapped because one or both teams have already started play, "
    "recorded a result, or affected downstream bracket advancement."
)
SAME_EVENT_SWAP_MESSAGE = "Teams swapped successfully. WF Round 1 positions were exchanged."
CROSS_EVENT_SWAP_MESSAGE = (
    "Teams swapped successfully. Both teams exchanged divisions and WF Round 1 positions. "
    "Existing match IDs, courts, and scheduled times were preserved."
)
SAME_EVENT_SLOT_SWAP = "SAME_EVENT_SLOT_SWAP"
CROSS_EVENT_TEAM_SWAP = "CROSS_EVENT_TEAM_SWAP"


class PostDrawCorrectionError(Exception):
    """Validation or safety failure for a post-draw correction."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int = 400,
        code: str = "POST_DRAW_CORRECTION_ERROR",
        extra: Optional[dict[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.code = code
        self.extra = extra or {}

    def as_detail(self) -> dict[str, Any]:
        detail: dict[str, Any] = {"code": self.code, "message": self.message}
        detail.update(self.extra)
        return detail


@dataclass
class AffectedMatchInfo:
    id: int
    match_code: str
    match_type: str
    round_index: int
    sequence_in_round: int
    team_a_id: Optional[int]
    team_b_id: Optional[int]
    placeholder_side_a: str
    placeholder_side_b: str
    schedule_version_id: int
    cleared_slots: list[str] = field(default_factory=list)


@dataclass
class MoveTeamResult:
    team_id: int
    source_event_id: int
    destination_event_id: int
    source_event_name: str
    destination_event_name: str
    source_has_matches: bool
    destination_has_matches: bool
    affected_source_matches: list[AffectedMatchInfo]
    warnings: list[str] = field(default_factory=list)
    message: str = "Team moved successfully."
    player_ids: list[int] = field(default_factory=list)
    seed_cleared: bool = False
    avoid_edges_removed: int = 0


@dataclass
class TeamSummary:
    id: int
    name: str
    display_name: Optional[str]
    seed: Optional[int]
    event_id: int
    is_defaulted: bool
    belongs_to_event: bool


@dataclass
class WfR1MatchupContext:
    tournament_id: int
    event_id: int
    event_name: str
    stage: str
    round_index: int
    match_id: int
    match_code: str
    sequence_in_round: int
    team_a: Optional[TeamSummary]
    team_b: Optional[TeamSummary]
    scheduled_time: Optional[str]
    court_label: Optional[str]
    day_date: Optional[str]
    status: str
    runtime_status: str
    winner_team_id: Optional[int]
    has_score: bool
    started_at: Optional[str]
    completed_at: Optional[str]
    edit_blocked: bool
    edit_block_reason: Optional[str]
    available_teams: list[TeamSummary]


@dataclass
class EditMatchupResult:
    match_id: int
    event_id: int
    tournament_id: int
    old_team_a_id: Optional[int]
    old_team_b_id: Optional[int]
    new_team_a_id: Optional[int]
    new_team_b_id: Optional[int]
    match_type: str
    round_index: int
    sequence_in_round: int
    status: str
    assignment_slot_id: Optional[int]
    court_label: Optional[str]
    scheduled_time: Optional[str]


@dataclass
class SwapSlotInfo:
    match_id: int
    side: str
    match_code: str
    sequence_in_round: int
    event_id: int


@dataclass
class SwapTeamsResult:
    mode: str
    tournament_id: int
    team_a_id: int
    team_b_id: int
    team_a_name: str
    team_b_name: str
    team_a_old_event_id: int
    team_a_new_event_id: int
    team_b_old_event_id: int
    team_b_new_event_id: int
    team_a_old_event_name: str
    team_a_new_event_name: str
    team_b_old_event_name: str
    team_b_new_event_name: str
    team_a_old_slot: SwapSlotInfo
    team_a_new_slot: SwapSlotInfo
    team_b_old_slot: SwapSlotInfo
    team_b_new_slot: SwapSlotInfo
    warnings: list[str] = field(default_factory=list)
    message: str = SAME_EVENT_SWAP_MESSAGE
    seed_cleared_team_ids: list[int] = field(default_factory=list)
    wf_group_index_cleared_team_ids: list[int] = field(default_factory=list)
    avoid_edges_removed: int = 0
    player_ids_a: list[int] = field(default_factory=list)
    player_ids_b: list[int] = field(default_factory=list)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _audit(action: str, payload: dict[str, Any]) -> None:
    record = {"action": action, "timestamp": _utcnow().isoformat(), **payload}
    logger.info("%s %s", action, json.dumps(record, default=str, sort_keys=True))


def _staff_label(staff_user: Optional[str]) -> Optional[str]:
    if staff_user is None:
        return None
    label = str(staff_user).strip()
    return label or None


def event_has_generated_matches(session: Session, event_id: int) -> bool:
    row = session.exec(select(Match.id).where(Match.event_id == event_id).limit(1)).first()
    return row is not None


def _refresh_event_team_count(session: Session, event: Event) -> None:
    total = len(session.exec(select(Team.id).where(Team.event_id == event.id)).all())
    if event.team_count != total:
        event.team_count = total
        session.add(event)


def _player_ids_for_team(session: Session, team_id: int) -> list[int]:
    links = session.exec(select(TeamPlayer).where(TeamPlayer.team_id == team_id)).all()
    return [link.player_id for link in links if link.player_id is not None]


def _matches_referencing_team_in_event(session: Session, event_id: int, team_id: int) -> list[Match]:
    return list(
        session.exec(
            select(Match)
            .where(
                Match.event_id == event_id,
                or_(Match.team_a_id == team_id, Match.team_b_id == team_id, Match.winner_team_id == team_id),
            )
            .order_by(Match.schedule_version_id, Match.round_index, Match.sequence_in_round, Match.id)
        ).all()
    )


def _affected_match_info(match: Match) -> AffectedMatchInfo:
    return AffectedMatchInfo(
        id=match.id,  # type: ignore[arg-type]
        match_code=match.match_code,
        match_type=match.match_type,
        round_index=match.round_index,
        sequence_in_round=match.sequence_in_round,
        team_a_id=match.team_a_id,
        team_b_id=match.team_b_id,
        placeholder_side_a=match.placeholder_side_a,
        placeholder_side_b=match.placeholder_side_b,
        schedule_version_id=match.schedule_version_id,
    )


def _delete_source_avoid_edges(session: Session, event_id: int, team_id: int) -> int:
    edges = session.exec(
        select(TeamAvoidEdge).where(
            TeamAvoidEdge.event_id == event_id,
            or_(TeamAvoidEdge.team_id_a == team_id, TeamAvoidEdge.team_id_b == team_id),
        )
    ).all()
    for edge in edges:
        session.delete(edge)
    return len(edges)


def _team_summary(team: Team, event_id: int) -> TeamSummary:
    return TeamSummary(
        id=team.id,  # type: ignore[arg-type]
        name=team.name,
        display_name=team.display_name,
        seed=team.seed,
        event_id=team.event_id,
        is_defaulted=bool(team.is_defaulted),
        belongs_to_event=team.event_id == event_id,
    )


def wf_r1_placeholder_for_team(session: Session, team_id: Optional[int]) -> str:
    """WF R1 labels match generate_wf_matches (round 1): full roster name, not short display_name."""
    if team_id is None:
        return EMPTY_WF_PLACEHOLDER
    team = session.get(Team, team_id)
    if not team:
        return EMPTY_WF_PLACEHOLDER
    return team.name or team.display_name or f"Team {team.id}"


def _score_present(match: Match) -> bool:
    score = match.score_json
    if not score:
        return False
    if isinstance(score, dict) and not score:
        return False
    return True


def _downstream_advanced(session: Session, match: Match) -> bool:
    if match.id is None:
        return False
    downstream = session.exec(
        select(Match).where(or_(Match.source_match_a_id == match.id, Match.source_match_b_id == match.id))
    ).all()
    for child in downstream:
        if child.source_match_a_id == match.id and child.team_a_id is not None:
            return True
        if child.source_match_b_id == match.id and child.team_b_id is not None:
            return True
    return False


def match_locked_for_participant_edit(session: Session, match: Match) -> Optional[str]:
    runtime = (match.runtime_status or "").upper()
    status = (match.status or "").lower()
    if match.winner_team_id is not None:
        return COMPLETED_MATCH_WARNING
    if _score_present(match):
        return COMPLETED_MATCH_WARNING
    if runtime in {"IN_PROGRESS", "FINAL"}:
        return COMPLETED_MATCH_WARNING
    if status == "complete":
        return COMPLETED_MATCH_WARNING
    if match.started_at is not None or match.completed_at is not None:
        return COMPLETED_MATCH_WARNING
    if _downstream_advanced(session, match):
        return COMPLETED_MATCH_WARNING
    return None


def _is_unplayed_wf_r1(session: Session, match: Match) -> bool:
    if (match.match_type or "").upper() != "WF":
        return False
    if match.round_index != 1:
        return False
    return match_locked_for_participant_edit(session, match) is None


def _source_match_blocks_team_move(session: Session, match: Match) -> bool:
    if match_locked_for_participant_edit(session, match):
        return True
    if not _is_unplayed_wf_r1(session, match):
        return True
    return False


def _clear_team_from_wf_r1_slot(match: Match, team_id: int) -> list[str]:
    """Clear only the moved team's side(s). Returns slot labels cleared (A/B)."""
    cleared: list[str] = []
    if match.team_a_id == team_id:
        match.team_a_id = None
        match.placeholder_side_a = EMPTY_WF_PLACEHOLDER
        cleared.append("A")
    if match.team_b_id == team_id:
        match.team_b_id = None
        match.placeholder_side_b = EMPTY_WF_PLACEHOLDER
        cleared.append("B")
    return cleared


def _assignment_view(session: Session, match: Match) -> tuple[Optional[int], Optional[str], Optional[str], Optional[str]]:
    assignment = session.exec(select(MatchAssignment).where(MatchAssignment.match_id == match.id)).first()
    if not assignment:
        return None, None, None, None
    slot = session.get(ScheduleSlot, assignment.slot_id)
    if not slot:
        return assignment.slot_id, None, None, None
    start = slot.start_time.strftime("%H:%M") if slot.start_time is not None else None
    day = slot.day_date.isoformat() if slot.day_date is not None else None
    return assignment.slot_id, slot.court_label, start, day


def _wf_slot_read_team_id(match: Match, slot: Literal["A", "B"]) -> Optional[int]:
    return match.team_a_id if slot == "A" else match.team_b_id


def _write_wf_r1_slot(session: Session, match: Match, slot: Literal["A", "B"], team_id: Optional[int]) -> None:
    """Write a WF R1 occupant + display placeholder. Does not change match identity or schedule."""
    ph = wf_r1_placeholder_for_team(session, team_id)
    if slot == "A":
        match.team_a_id = team_id
        match.placeholder_side_a = ph
    else:
        match.team_b_id = team_id
        match.placeholder_side_b = ph


def swap_wf_r1_slot_occupants(
    session: Session,
    match_a: Match,
    slot_a: Literal["A", "B"],
    match_b: Match,
    slot_b: Literal["A", "B"],
) -> tuple[Optional[int], Optional[int]]:
    """Exchange occupant team IDs between two WF R1 sides. Does not commit.

    Same mutation used by the existing same-event WF R1 slot-swap endpoint.
    """
    ta = _wf_slot_read_team_id(match_a, slot_a)
    tb = _wf_slot_read_team_id(match_b, slot_b)
    _write_wf_r1_slot(session, match_a, slot_a, tb)
    _write_wf_r1_slot(session, match_b, slot_b, ta)
    session.add(match_a)
    session.add(match_b)
    return ta, tb


def _match_schedule_identity(session: Session, match: Match) -> dict[str, Any]:
    slot_id, court, start, day = _assignment_view(session, match)
    return {
        "id": match.id,
        "event_id": match.event_id,
        "schedule_version_id": match.schedule_version_id,
        "match_type": match.match_type,
        "round_index": match.round_index,
        "sequence_in_round": match.sequence_in_round,
        "slot_id": slot_id,
        "court": court,
        "start": start,
        "day": day,
    }


def _assert_match_schedule_identity(session: Session, match: Match, before: dict[str, Any]) -> None:
    after = _match_schedule_identity(session, match)
    if after != before:
        raise PostDrawCorrectionError(
            "Match identity or schedule assignment changed unexpectedly; aborting",
            status_code=500,
            code="MATCH_IDENTITY_DRIFT",
            extra={"match_id": match.id, "before": before, "after": after},
        )


def _swap_slot_info(match: Match, slot: Literal["A", "B"]) -> SwapSlotInfo:
    return SwapSlotInfo(
        match_id=match.id,  # type: ignore[arg-type]
        side=slot,
        match_code=match.match_code,
        sequence_in_round=match.sequence_in_round,
        event_id=match.event_id,
    )


def _find_wf_r1_slot_for_team(
    session: Session,
    *,
    team_id: int,
    event_id: int,
    tournament_id: int,
    schedule_version_id: int,
) -> tuple[Match, Literal["A", "B"]]:
    rows = list(
        session.exec(
            select(Match).where(
                Match.tournament_id == tournament_id,
                Match.schedule_version_id == schedule_version_id,
                Match.event_id == event_id,
                Match.match_type == "WF",
                Match.round_index == 1,
                or_(Match.team_a_id == team_id, Match.team_b_id == team_id),
            )
        ).all()
    )
    if not rows:
        raise PostDrawCorrectionError(
            "Each selected team must occupy an unplayed WF Round 1 participant slot.",
            status_code=409,
            code="WF_R1_SLOT_NOT_FOUND",
            extra={"team_id": team_id, "event_id": event_id},
        )
    if len(rows) > 1:
        raise PostDrawCorrectionError(
            "Team occupies more than one WF Round 1 slot; swap is not possible.",
            status_code=409,
            code="AMBIGUOUS_WF_R1_SLOT",
            extra={"team_id": team_id, "match_ids": [m.id for m in rows]},
        )
    match = rows[0]
    on_a = match.team_a_id == team_id
    on_b = match.team_b_id == team_id
    if on_a and on_b:
        raise PostDrawCorrectionError(
            "Team occupies both sides of the same WF Round 1 match; swap is not possible.",
            status_code=409,
            code="TEAM_ON_BOTH_SIDES",
            extra={"team_id": team_id, "match_id": match.id},
        )
    slot: Literal["A", "B"] = "A" if on_a else "B"
    return match, slot


def _assert_team_safe_for_swap(session: Session, team: Team) -> None:
    refs = _matches_referencing_team_in_event(session, team.event_id, team.id)  # type: ignore[arg-type]
    for match in refs:
        if _source_match_blocks_team_move(session, match):
            raise PostDrawCorrectionError(
                SWAP_BLOCKED_PLAYED,
                status_code=409,
                code="SWAP_BLOCKED_PLAYED_OR_ADVANCED",
                extra={
                    "team_id": team.id,
                    "blocking_match_id": match.id,
                    "blocking_match_code": match.match_code,
                    "blocking_match_type": match.match_type,
                    "blocking_round_index": match.round_index,
                },
            )


def _seed_taken_in_event(
    session: Session,
    event_id: int,
    seed: Optional[int],
    except_team_id: int,
) -> bool:
    if seed is None:
        return False
    others = session.exec(select(Team).where(Team.event_id == event_id, Team.seed == seed)).all()
    return any(t.id != except_team_id for t in others)


def _assert_identity_fits_destination(
    session: Session,
    team: Team,
    dest_event_id: int,
    exclude_team_id: int,
) -> None:
    others = session.exec(
        select(Team).where(Team.event_id == dest_event_id, Team.id != exclude_team_id)
    ).all()
    for other in others:
        if other.name == team.name:
            raise PostDrawCorrectionError(
                f"A team named '{team.name}' already exists in the destination event",
                status_code=409,
                code="NAME_CONFLICT",
                extra={"team_id": team.id, "destination_event_id": dest_event_id},
            )
        if team.source_team_key and other.source_team_key and other.source_team_key == team.source_team_key:
            raise PostDrawCorrectionError(
                "A team with the same registration identity already exists in the destination event",
                status_code=409,
                code="SOURCE_TEAM_KEY_CONFLICT",
                extra={"team_id": team.id, "destination_event_id": dest_event_id},
            )


def _event_teams_sorted(session: Session, event_id: int) -> list[Team]:
    teams = session.exec(select(Team).where(Team.event_id == event_id)).all()

    def sort_key(team: Team) -> tuple:
        return (
            (team.seed is None, team.seed if team.seed is not None else 0),
            (team.rating is None, -(team.rating if team.rating is not None else 0.0)),
            team.id or 0,
        )

    return sorted(teams, key=sort_key)


def get_wf_r1_matchup_context(session: Session, match_id: int, tournament_id: int) -> WfR1MatchupContext:
    match = session.get(Match, match_id)
    if not match or match.tournament_id != tournament_id:
        raise PostDrawCorrectionError("Match not found", status_code=404, code="MATCH_NOT_FOUND")
    if (match.match_type or "").upper() != "WF":
        raise PostDrawCorrectionError("Match is not a waterfall match", code="NOT_WF_MATCH")
    if match.round_index != 1:
        raise PostDrawCorrectionError(
            "Only WF round 1 matchups can be edited",
            code="NOT_WF_ROUND_1",
        )

    event = session.get(Event, match.event_id)
    if not event:
        raise PostDrawCorrectionError("Event not found", status_code=404, code="EVENT_NOT_FOUND")

    team_a = session.get(Team, match.team_a_id) if match.team_a_id else None
    team_b = session.get(Team, match.team_b_id) if match.team_b_id else None
    available = [
        _team_summary(t, event.id)  # type: ignore[arg-type]
        for t in _event_teams_sorted(session, event.id)  # type: ignore[arg-type]
        if not bool(t.is_defaulted)
    ]
    block_reason = match_locked_for_participant_edit(session, match)
    _slot_id, court, start, day = _assignment_view(session, match)

    return WfR1MatchupContext(
        tournament_id=match.tournament_id,
        event_id=match.event_id,
        event_name=event.name,
        stage="WF",
        round_index=match.round_index,
        match_id=match.id,  # type: ignore[arg-type]
        match_code=match.match_code,
        sequence_in_round=match.sequence_in_round,
        team_a=_team_summary(team_a, event.id) if team_a else None,  # type: ignore[arg-type]
        team_b=_team_summary(team_b, event.id) if team_b else None,  # type: ignore[arg-type]
        scheduled_time=start,
        court_label=court,
        day_date=day,
        status=match.status,
        runtime_status=match.runtime_status,
        winner_team_id=match.winner_team_id,
        has_score=_score_present(match),
        started_at=match.started_at.isoformat() if match.started_at else None,
        completed_at=match.completed_at.isoformat() if match.completed_at else None,
        edit_blocked=block_reason is not None,
        edit_block_reason=block_reason,
        available_teams=available,
    )


def move_team_between_events(
    session: Session,
    *,
    team_id: int,
    destination_event_id: int,
    confirm_existing_draws: bool = False,
    staff_user: Optional[str] = None,
) -> MoveTeamResult:
    team = session.get(Team, team_id)
    if not team:
        raise PostDrawCorrectionError("Team not found", status_code=404, code="TEAM_NOT_FOUND")

    # A. Validate source/destination tournament/event relationship.
    # B. Validate the team belongs to source event.
    source_event = session.get(Event, team.event_id)
    dest_event = session.get(Event, destination_event_id)
    if not source_event:
        raise PostDrawCorrectionError("Source event not found", status_code=404, code="EVENT_NOT_FOUND")
    if not dest_event:
        raise PostDrawCorrectionError("Destination event not found", status_code=404, code="EVENT_NOT_FOUND")
    if source_event.tournament_id != dest_event.tournament_id:
        raise PostDrawCorrectionError(
            "Destination event must belong to the same tournament",
            code="CROSS_TOURNAMENT_MOVE",
        )
    if source_event.id == dest_event.id:
        raise PostDrawCorrectionError("Team is already in that event", code="SAME_EVENT")

    dest_teams = session.exec(select(Team).where(Team.event_id == dest_event.id)).all()
    for other in dest_teams:
        if other.id == team.id:
            continue
        if other.name == team.name:
            raise PostDrawCorrectionError(
                f"A team named '{team.name}' already exists in the destination event",
                status_code=409,
                code="NAME_CONFLICT",
            )
        if team.source_team_key and other.source_team_key and other.source_team_key == team.source_team_key:
            raise PostDrawCorrectionError(
                "A team with the same registration identity already exists in the destination event",
                status_code=409,
                code="SOURCE_TEAM_KEY_CONFLICT",
            )

    source_has_matches = event_has_generated_matches(session, source_event.id)  # type: ignore[arg-type]
    dest_has_matches = event_has_generated_matches(session, dest_event.id)  # type: ignore[arg-type]
    if (source_has_matches or dest_has_matches) and not confirm_existing_draws:
        raise PostDrawCorrectionError(
            DRAWS_EXIST_WARNING,
            status_code=409,
            code="DRAWS_EXIST_CONFIRMATION_REQUIRED",
            extra={
                "source_has_matches": source_has_matches,
                "destination_has_matches": dest_has_matches,
                "source_event_id": source_event.id,
                "destination_event_id": dest_event.id,
            },
        )

    # C. Inspect every source match referencing the team.
    source_matches = _matches_referencing_team_in_event(session, source_event.id, team.id)  # type: ignore[arg-type]

    # D. BLOCK if any source match is started/scored/completed/advanced (or later-round).
    for match in source_matches:
        if _source_match_blocks_team_move(session, match):
            raise PostDrawCorrectionError(
                MOVE_BLOCKED_PLAYED_SOURCE,
                status_code=409,
                code="SOURCE_MATCH_PLAYED_OR_ADVANCED",
                extra={
                    "blocking_match_id": match.id,
                    "blocking_match_code": match.match_code,
                    "blocking_match_type": match.match_type,
                    "blocking_round_index": match.round_index,
                },
            )

    # E. Identify eligible unplayed WF R1 source participant slots that must be cleared.
    slots_to_clear = [m for m in source_matches if _is_unplayed_wf_r1(session, m)]

    # F. Validate destination seed collision (apply after event_id change, same flush).
    seed_will_clear = bool(team.seed is not None and any(other.seed == team.seed for other in dest_teams))

    player_ids = _player_ids_for_team(session, team.id)  # type: ignore[arg-type]
    source_event_id = source_event.id
    dest_event_id = dest_event.id
    tournament_id = source_event.tournament_id
    original_seed = team.seed
    original_wf_group = team.wf_group_index

    # G–K. Mutate team identity in memory; flush with slot clears so unique(seed) cannot fire mid-move.
    team.event_id = dest_event_id  # type: ignore[assignment]
    team.wf_group_index = None
    seed_cleared = False
    if seed_will_clear:
        team.seed = None
        seed_cleared = True
    session.add(team)

    # H–I. Clear only the moved team's unplayed WF R1 participant slots + TBD placeholders.
    cleared_details: list[AffectedMatchInfo] = []
    for match in slots_to_clear:
        cleared_slots = _clear_team_from_wf_r1_slot(match, team.id)  # type: ignore[arg-type]
        if not cleared_slots:
            continue
        session.add(match)
        info = _affected_match_info(match)
        info.cleared_slots = cleared_slots
        cleared_details.append(info)

    # L. Remove source event-scoped avoid edges.
    avoid_edges_removed = _delete_source_avoid_edges(session, source_event_id, team.id)  # type: ignore[arg-type]

    session.flush()
    _refresh_event_team_count(session, source_event)
    _refresh_event_team_count(session, dest_event)
    session.flush()

    warnings: list[str] = []
    if seed_cleared:
        warnings.append(SEED_CLEARED_WARNING)
    if avoid_edges_removed:
        warnings.append(WHO_KNOWS_WHO_WARNING)

    if cleared_details:
        message = (
            f"Team moved successfully. The team's unplayed WF Round 1 slot in {source_event.name} "
            "was cleared. Existing match IDs, court assignments, and scheduled times were preserved."
        )
    else:
        message = "Team moved successfully."
    if dest_has_matches:
        message = f"{message} {DESTINATION_DRAW_EXISTS_MESSAGE}"

    # M. Audit/log (N. commit is the caller's responsibility).
    _audit(
        "POST_DRAW_TEAM_MOVE",
        {
            "tournament_id": tournament_id,
            "team_id": team.id,
            "player_ids": player_ids,
            "source_event_id": source_event_id,
            "destination_event_id": dest_event_id,
            "staff_user": _staff_label(staff_user),
            "source_has_matches": source_has_matches,
            "destination_has_matches": dest_has_matches,
            "cleared_source_match_ids": [m.id for m in cleared_details],
            "cleared_slots": {m.id: m.cleared_slots for m in cleared_details},
            "seed_cleared": seed_cleared,
            "original_seed": original_seed,
            "original_wf_group_index": original_wf_group,
            "avoid_edges_removed": avoid_edges_removed,
        },
    )

    return MoveTeamResult(
        team_id=team.id,  # type: ignore[arg-type]
        source_event_id=source_event_id,  # type: ignore[arg-type]
        destination_event_id=dest_event_id,  # type: ignore[arg-type]
        source_event_name=source_event.name,
        destination_event_name=dest_event.name,
        source_has_matches=source_has_matches,
        destination_has_matches=dest_has_matches,
        affected_source_matches=cleared_details,
        warnings=warnings,
        message=message,
        player_ids=player_ids,
        seed_cleared=seed_cleared,
        avoid_edges_removed=avoid_edges_removed,
    )


def _require_team_in_event(
    session: Session,
    team_id: int,
    *,
    tournament_id: int,
    event_id: int,
    slot_label: str,
) -> Team:
    team = session.get(Team, team_id)
    if not team:
        raise PostDrawCorrectionError(f"{slot_label} team not found", status_code=404, code="TEAM_NOT_FOUND")
    event = session.get(Event, team.event_id)
    if not event or event.tournament_id != tournament_id:
        raise PostDrawCorrectionError(
            f"{slot_label} team does not belong to this tournament",
            code="WRONG_TOURNAMENT",
        )
    if team.event_id != event_id:
        raise PostDrawCorrectionError(
            f"{slot_label} team belongs to a different event/division",
            code="WRONG_EVENT",
        )
    if bool(team.is_defaulted):
        raise PostDrawCorrectionError(
            DEFAULTED_TEAM_ERROR,
            status_code=400,
            code="DEFAULTED_TEAM",
            extra={"team_id": team.id, "slot": slot_label},
        )
    return team


def _other_wf_r1_occurrence(
    session: Session,
    *,
    event_id: int,
    schedule_version_id: int,
    team_id: int,
    current_match_id: int,
) -> Optional[Match]:
    rows = session.exec(
        select(Match).where(
            Match.event_id == event_id,
            Match.schedule_version_id == schedule_version_id,
            Match.match_type == "WF",
            Match.round_index == 1,
            Match.id != current_match_id,
            or_(Match.team_a_id == team_id, Match.team_b_id == team_id),
        )
    ).all()
    return rows[0] if rows else None


def edit_first_round_wf_matchup(
    session: Session,
    *,
    match_id: int,
    tournament_id: int,
    team_a_id: Optional[int],
    team_b_id: Optional[int],
    staff_user: Optional[str] = None,
) -> EditMatchupResult:
    match = session.get(Match, match_id)
    if not match or match.tournament_id != tournament_id:
        raise PostDrawCorrectionError("Match not found", status_code=404, code="MATCH_NOT_FOUND")
    if (match.match_type or "").upper() != "WF":
        raise PostDrawCorrectionError("Match is not a waterfall match", code="NOT_WF_MATCH")
    if match.round_index != 1:
        raise PostDrawCorrectionError("Only WF round 1 matchups can be edited", code="NOT_WF_ROUND_1")

    block_reason = match_locked_for_participant_edit(session, match)
    if block_reason:
        raise PostDrawCorrectionError(
            block_reason,
            status_code=409,
            code="MATCH_HAS_RESULT",
        )

    if team_a_id is not None and team_b_id is not None and team_a_id == team_b_id:
        raise PostDrawCorrectionError("Team 1 and Team 2 cannot be the same team", code="SAME_TEAM_BOTH_SIDES")

    resolved_a: Optional[Team] = None
    resolved_b: Optional[Team] = None
    if team_a_id is not None:
        resolved_a = _require_team_in_event(
            session,
            team_a_id,
            tournament_id=tournament_id,
            event_id=match.event_id,
            slot_label="Team 1",
        )
    if team_b_id is not None:
        resolved_b = _require_team_in_event(
            session,
            team_b_id,
            tournament_id=tournament_id,
            event_id=match.event_id,
            slot_label="Team 2",
        )

    for slot_name, tid in (("Team 1", team_a_id), ("Team 2", team_b_id)):
        if tid is None:
            continue
        other = _other_wf_r1_occurrence(
            session,
            event_id=match.event_id,
            schedule_version_id=match.schedule_version_id,
            team_id=tid,
            current_match_id=match.id,  # type: ignore[arg-type]
        )
        if other is not None:
            raise PostDrawCorrectionError(
                f"This team already appears in WF Round 1, Match #{other.sequence_in_round}. "
                "Remove or replace them there first.",
                status_code=409,
                code="DUPLICATE_WF_R1_TEAM",
                extra={
                    "conflicting_match_id": other.id,
                    "conflicting_match_code": other.match_code,
                    "conflicting_sequence_in_round": other.sequence_in_round,
                    "slot": slot_name,
                    "team_id": tid,
                },
            )

    old_a = match.team_a_id
    old_b = match.team_b_id
    snapshot_round = match.round_index
    snapshot_type = match.match_type
    snapshot_seq = match.sequence_in_round
    snapshot_status = match.status
    slot_id_before, court_before, time_before, _day_before = _assignment_view(session, match)

    match.team_a_id = team_a_id
    match.team_b_id = team_b_id
    match.placeholder_side_a = resolved_a.name if resolved_a else wf_r1_placeholder_for_team(session, team_a_id)
    match.placeholder_side_b = resolved_b.name if resolved_b else wf_r1_placeholder_for_team(session, team_b_id)
    session.add(match)
    session.flush()

    slot_id_after, court_after, time_after, _day_after = _assignment_view(session, match)
    if (
        match.round_index != snapshot_round
        or match.match_type != snapshot_type
        or match.sequence_in_round != snapshot_seq
        or match.status != snapshot_status
        or slot_id_after != slot_id_before
        or court_after != court_before
        or time_after != time_before
    ):
        raise PostDrawCorrectionError(
            "Match identity or schedule assignment changed unexpectedly; aborting",
            status_code=500,
            code="MATCH_IDENTITY_DRIFT",
        )

    _audit(
        "POST_DRAW_MATCH_EDIT",
        {
            "tournament_id": match.tournament_id,
            "event_id": match.event_id,
            "match_id": match.id,
            "old_team_a_id": old_a,
            "old_team_b_id": old_b,
            "new_team_a_id": match.team_a_id,
            "new_team_b_id": match.team_b_id,
            "staff_user": _staff_label(staff_user),
        },
    )

    return EditMatchupResult(
        match_id=match.id,  # type: ignore[arg-type]
        event_id=match.event_id,
        tournament_id=match.tournament_id,
        old_team_a_id=old_a,
        old_team_b_id=old_b,
        new_team_a_id=match.team_a_id,
        new_team_b_id=match.team_b_id,
        match_type=match.match_type,
        round_index=match.round_index,
        sequence_in_round=match.sequence_in_round,
        status=match.status,
        assignment_slot_id=slot_id_after,
        court_label=court_after,
        scheduled_time=time_after,
    )


def swap_post_draw_teams(
    session: Session,
    *,
    tournament_id: int,
    team_a_id: int,
    team_b_id: int,
    schedule_version_id: int,
    staff_user: Optional[str] = None,
) -> SwapTeamsResult:
    """Atomically swap two teams' WF R1 slots, and event membership when they differ.

    The backend decides SAME_EVENT_SLOT_SWAP vs CROSS_EVENT_TEAM_SWAP.
    Does not commit; the caller owns the transaction.
    """
    if team_a_id == team_b_id:
        raise PostDrawCorrectionError("Select two different teams to swap", code="SAME_TEAM")

    tournament = session.get(Tournament, tournament_id)
    if not tournament:
        raise PostDrawCorrectionError("Tournament not found", status_code=404, code="TOURNAMENT_NOT_FOUND")

    version = session.get(ScheduleVersion, schedule_version_id)
    if not version or version.tournament_id != tournament_id:
        raise PostDrawCorrectionError("Schedule version not found", status_code=404, code="SCHEDULE_VERSION_NOT_FOUND")
    if (version.status or "").lower() == "final":
        raise PostDrawCorrectionError(
            "Cannot modify a finalized schedule version",
            status_code=400,
            code="SCHEDULE_VERSION_FINAL",
        )

    team_a = session.get(Team, team_a_id)
    team_b = session.get(Team, team_b_id)
    if not team_a:
        raise PostDrawCorrectionError("Team A not found", status_code=404, code="TEAM_NOT_FOUND")
    if not team_b:
        raise PostDrawCorrectionError("Team B not found", status_code=404, code="TEAM_NOT_FOUND")

    event_a = session.get(Event, team_a.event_id)
    event_b = session.get(Event, team_b.event_id)
    if not event_a or event_a.tournament_id != tournament_id:
        raise PostDrawCorrectionError(
            "Team A does not belong to this tournament",
            code="WRONG_TOURNAMENT",
            extra={"team_id": team_a.id},
        )
    if not event_b or event_b.tournament_id != tournament_id:
        raise PostDrawCorrectionError(
            "Team B does not belong to this tournament",
            code="WRONG_TOURNAMENT",
            extra={"team_id": team_b.id},
        )

    if bool(team_a.is_defaulted) or bool(team_b.is_defaulted):
        raise PostDrawCorrectionError(
            DEFAULTED_TEAM_ERROR,
            status_code=400,
            code="DEFAULTED_TEAM",
            extra={
                "team_a_id": team_a.id,
                "team_b_id": team_b.id,
                "team_a_defaulted": bool(team_a.is_defaulted),
                "team_b_defaulted": bool(team_b.is_defaulted),
            },
        )

    match_a, slot_a = _find_wf_r1_slot_for_team(
        session,
        team_id=team_a.id,  # type: ignore[arg-type]
        event_id=team_a.event_id,
        tournament_id=tournament_id,
        schedule_version_id=schedule_version_id,
    )
    match_b, slot_b = _find_wf_r1_slot_for_team(
        session,
        team_id=team_b.id,  # type: ignore[arg-type]
        event_id=team_b.event_id,
        tournament_id=tournament_id,
        schedule_version_id=schedule_version_id,
    )

    if match_a.id == match_b.id and slot_a == slot_b:
        raise PostDrawCorrectionError("Select two different sides to swap", code="SAME_SLOT")

    if not _is_unplayed_wf_r1(session, match_a) or not _is_unplayed_wf_r1(session, match_b):
        raise PostDrawCorrectionError(
            SWAP_BLOCKED_PLAYED,
            status_code=409,
            code="SWAP_BLOCKED_PLAYED_OR_ADVANCED",
        )

    _assert_team_safe_for_swap(session, team_a)
    _assert_team_safe_for_swap(session, team_b)

    same_event = team_a.event_id == team_b.event_id
    mode = SAME_EVENT_SLOT_SWAP if same_event else CROSS_EVENT_TEAM_SWAP

    old_event_a_id = team_a.event_id
    old_event_b_id = team_b.event_id
    old_event_a_name = event_a.name
    old_event_b_name = event_b.name
    old_wf_group_a = team_a.wf_group_index
    old_wf_group_b = team_b.wf_group_index
    old_seed_a = team_a.seed
    old_seed_b = team_b.seed
    name_a = team_a.name
    name_b = team_b.name
    key_a = team_a.source_team_key
    key_b = team_b.source_team_key
    player_ids_a = _player_ids_for_team(session, team_a.id)  # type: ignore[arg-type]
    player_ids_b = _player_ids_for_team(session, team_b.id)  # type: ignore[arg-type]

    team_a_old_slot = _swap_slot_info(match_a, slot_a)
    team_b_old_slot = _swap_slot_info(match_b, slot_b)
    identity_a = _match_schedule_identity(session, match_a)
    identity_b = _match_schedule_identity(session, match_b)

    warnings: list[str] = []
    seed_cleared_team_ids: list[int] = []
    wf_group_index_cleared_team_ids: list[int] = []
    avoid_edges_removed = 0

    if not same_event:
        _assert_identity_fits_destination(session, team_a, old_event_b_id, team_b.id)  # type: ignore[arg-type]
        _assert_identity_fits_destination(session, team_b, old_event_a_id, team_a.id)  # type: ignore[arg-type]

        # Temporarily clear unique (event_id, name/seed/key) fields so the event_id
        # exchange cannot trip SQLite unique constraints mid-transaction.
        team_a.name = f"__swap_tmp_a_{team_a.id}"
        team_b.name = f"__swap_tmp_b_{team_b.id}"
        team_a.source_team_key = None
        team_b.source_team_key = None
        team_a.seed = None
        team_b.seed = None
        session.add(team_a)
        session.add(team_b)
        session.flush()

        team_a.event_id = old_event_b_id
        team_b.event_id = old_event_a_id
        team_a.wf_group_index = None
        team_b.wf_group_index = None
        if old_wf_group_a is not None:
            wf_group_index_cleared_team_ids.append(team_a.id)  # type: ignore[arg-type]
        if old_wf_group_b is not None:
            wf_group_index_cleared_team_ids.append(team_b.id)  # type: ignore[arg-type]
        session.add(team_a)
        session.add(team_b)
        session.flush()

        team_a.name = name_a
        team_b.name = name_b
        team_a.source_team_key = key_a
        team_b.source_team_key = key_b
        session.add(team_a)
        session.add(team_b)
        session.flush()

        if old_seed_a is not None and _seed_taken_in_event(session, team_a.event_id, old_seed_a, team_a.id):  # type: ignore[arg-type]
            seed_cleared_team_ids.append(team_a.id)  # type: ignore[arg-type]
        else:
            team_a.seed = old_seed_a
        if old_seed_b is not None and _seed_taken_in_event(session, team_b.event_id, old_seed_b, team_b.id):  # type: ignore[arg-type]
            seed_cleared_team_ids.append(team_b.id)  # type: ignore[arg-type]
        else:
            team_b.seed = old_seed_b
        session.add(team_a)
        session.add(team_b)
        session.flush()

        if seed_cleared_team_ids:
            warnings.append(SEED_CLEARED_WARNING)

    swap_wf_r1_slot_occupants(session, match_a, slot_a, match_b, slot_b)
    session.flush()
    _assert_match_schedule_identity(session, match_a, identity_a)
    _assert_match_schedule_identity(session, match_b, identity_b)

    if not same_event:
        removed_a = _delete_source_avoid_edges(session, old_event_a_id, team_a.id)  # type: ignore[arg-type]
        removed_b = _delete_source_avoid_edges(session, old_event_b_id, team_b.id)  # type: ignore[arg-type]
        avoid_edges_removed = removed_a + removed_b
        if avoid_edges_removed:
            warnings.append(WHO_KNOWS_WHO_WARNING)
        session.flush()

    team_a_new_slot = _swap_slot_info(match_b, slot_b)
    team_b_new_slot = _swap_slot_info(match_a, slot_a)
    new_event_a_name = event_b.name if not same_event else event_a.name
    new_event_b_name = event_a.name if not same_event else event_b.name
    message = SAME_EVENT_SWAP_MESSAGE if same_event else CROSS_EVENT_SWAP_MESSAGE

    _audit(
        "POST_DRAW_TEAM_SWAP",
        {
            "tournament_id": tournament_id,
            "mode": mode,
            "team_a_id": team_a.id,
            "team_b_id": team_b.id,
            "team_a_old_event_id": old_event_a_id,
            "team_a_new_event_id": team_a.event_id,
            "team_b_old_event_id": old_event_b_id,
            "team_b_new_event_id": team_b.event_id,
            "team_a_old_match_id": team_a_old_slot.match_id,
            "team_a_old_side": team_a_old_slot.side,
            "team_a_new_match_id": team_a_new_slot.match_id,
            "team_a_new_side": team_a_new_slot.side,
            "team_b_old_match_id": team_b_old_slot.match_id,
            "team_b_old_side": team_b_old_slot.side,
            "team_b_new_match_id": team_b_new_slot.match_id,
            "team_b_new_side": team_b_new_slot.side,
            "seed_cleared_team_ids": seed_cleared_team_ids,
            "original_seed_a": old_seed_a,
            "original_seed_b": old_seed_b,
            "wf_group_index_cleared_team_ids": wf_group_index_cleared_team_ids,
            "original_wf_group_index_a": old_wf_group_a,
            "original_wf_group_index_b": old_wf_group_b,
            "avoid_edges_removed": avoid_edges_removed,
            "staff_user": _staff_label(staff_user),
        },
    )

    return SwapTeamsResult(
        mode=mode,
        tournament_id=tournament_id,
        team_a_id=team_a.id,  # type: ignore[arg-type]
        team_b_id=team_b.id,  # type: ignore[arg-type]
        team_a_name=team_a.name,
        team_b_name=team_b.name,
        team_a_old_event_id=old_event_a_id,
        team_a_new_event_id=team_a.event_id,
        team_b_old_event_id=old_event_b_id,
        team_b_new_event_id=team_b.event_id,
        team_a_old_event_name=old_event_a_name,
        team_a_new_event_name=new_event_a_name,
        team_b_old_event_name=old_event_b_name,
        team_b_new_event_name=new_event_b_name,
        team_a_old_slot=team_a_old_slot,
        team_a_new_slot=team_a_new_slot,
        team_b_old_slot=team_b_old_slot,
        team_b_new_slot=team_b_new_slot,
        warnings=warnings,
        message=message,
        seed_cleared_team_ids=seed_cleared_team_ids,
        wf_group_index_cleared_team_ids=wf_group_index_cleared_team_ids,
        avoid_edges_removed=avoid_edges_removed,
        player_ids_a=player_ids_a,
        player_ids_b=player_ids_b,
    )
