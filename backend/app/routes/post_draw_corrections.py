"""API routes for post-draw team swaps, division moves, and WF R1 matchup edits."""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlmodel import Session

from app.database import get_session
from app.models.event import Event
from app.models.team import Team
from app.models.tournament import Tournament
from app.services.post_draw_corrections import (
    PostDrawCorrectionError,
    edit_first_round_wf_matchup,
    get_wf_r1_matchup_context,
    move_team_between_events,
    swap_post_draw_teams,
)

router = APIRouter()


def _staff_user_from_request(request: Request) -> Optional[str]:
    user = getattr(request.state, "current_user", None)
    if user is None:
        return None
    return getattr(user, "username", None) or getattr(user, "display_name", None)


def _raise_correction_error(exc: PostDrawCorrectionError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.as_detail()) from exc


class MoveDivisionRequest(BaseModel):
    destination_event_id: int
    confirm_existing_draws: bool = False


class AffectedMatchResponse(BaseModel):
    id: int
    match_code: str
    match_type: str
    round_index: int
    sequence_in_round: int
    team_a_id: Optional[int] = None
    team_b_id: Optional[int] = None
    placeholder_side_a: str
    placeholder_side_b: str
    schedule_version_id: int
    cleared_slots: List[str] = Field(default_factory=list)


class MoveDivisionResponse(BaseModel):
    team_id: int
    source_event_id: int
    destination_event_id: int
    source_event_name: str
    destination_event_name: str
    source_has_matches: bool
    destination_has_matches: bool
    affected_source_matches: List[AffectedMatchResponse]
    warnings: List[str]
    message: str
    player_ids: List[int]
    seed_cleared: bool = False
    avoid_edges_removed: int = 0


class TeamSummaryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    display_name: Optional[str] = None
    seed: Optional[int] = None
    event_id: int
    is_defaulted: bool = False
    belongs_to_event: bool = True


class WfR1MatchupContextResponse(BaseModel):
    tournament_id: int
    event_id: int
    event_name: str
    stage: str
    round_index: int
    match_id: int
    match_code: str
    sequence_in_round: int
    team_a: Optional[TeamSummaryResponse] = None
    team_b: Optional[TeamSummaryResponse] = None
    scheduled_time: Optional[str] = None
    court_label: Optional[str] = None
    day_date: Optional[str] = None
    status: str
    runtime_status: str
    winner_team_id: Optional[int] = None
    has_score: bool
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    edit_blocked: bool
    edit_block_reason: Optional[str] = None
    available_teams: List[TeamSummaryResponse]


class EditWfR1MatchupRequest(BaseModel):
    team_a_id: Optional[int] = None
    team_b_id: Optional[int] = None


class EditWfR1MatchupResponse(BaseModel):
    match_id: int
    event_id: int
    tournament_id: int
    old_team_a_id: Optional[int] = None
    old_team_b_id: Optional[int] = None
    new_team_a_id: Optional[int] = None
    new_team_b_id: Optional[int] = None
    match_type: str
    round_index: int
    sequence_in_round: int
    status: str
    assignment_slot_id: Optional[int] = None
    court_label: Optional[str] = None
    scheduled_time: Optional[str] = None


class SwapPostDrawTeamsRequest(BaseModel):
    team_a_id: int
    team_b_id: int
    schedule_version_id: int


class SwapSlotResponse(BaseModel):
    match_id: int
    side: str
    match_code: str
    sequence_in_round: int
    event_id: int


class SwapPostDrawTeamsResponse(BaseModel):
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
    team_a_old_slot: SwapSlotResponse
    team_a_new_slot: SwapSlotResponse
    team_b_old_slot: SwapSlotResponse
    team_b_new_slot: SwapSlotResponse
    warnings: List[str] = Field(default_factory=list)
    message: str
    seed_cleared_team_ids: List[int] = Field(default_factory=list)
    wf_group_index_cleared_team_ids: List[int] = Field(default_factory=list)
    avoid_edges_removed: int = 0
    player_ids_a: List[int] = Field(default_factory=list)
    player_ids_b: List[int] = Field(default_factory=list)


@router.post(
    "/tournaments/{tournament_id}/teams/{team_id}/move-division",
    response_model=MoveDivisionResponse,
)
def move_team_division(
    tournament_id: int,
    team_id: int,
    body: MoveDivisionRequest,
    request: Request,
    session: Session = Depends(get_session),
):
    tournament = session.get(Tournament, tournament_id)
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")

    team = session.get(Team, team_id)
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
    source = session.get(Event, team.event_id)
    dest = session.get(Event, body.destination_event_id)
    if not source or source.tournament_id != tournament_id:
        raise HTTPException(status_code=404, detail="Team does not belong to this tournament")
    if not dest:
        raise HTTPException(status_code=404, detail="Destination event not found")
    if dest.tournament_id != tournament_id:
        raise HTTPException(status_code=400, detail="Destination event does not belong to this tournament")

    try:
        result = move_team_between_events(
            session,
            team_id=team_id,
            destination_event_id=body.destination_event_id,
            confirm_existing_draws=body.confirm_existing_draws,
            staff_user=_staff_user_from_request(request),
        )
        session.commit()
    except PostDrawCorrectionError as exc:
        session.rollback()
        _raise_correction_error(exc)
    except Exception:
        session.rollback()
        raise

    return MoveDivisionResponse(
        team_id=result.team_id,
        source_event_id=result.source_event_id,
        destination_event_id=result.destination_event_id,
        source_event_name=result.source_event_name,
        destination_event_name=result.destination_event_name,
        source_has_matches=result.source_has_matches,
        destination_has_matches=result.destination_has_matches,
        affected_source_matches=[
            AffectedMatchResponse(
                id=m.id,
                match_code=m.match_code,
                match_type=m.match_type,
                round_index=m.round_index,
                sequence_in_round=m.sequence_in_round,
                team_a_id=m.team_a_id,
                team_b_id=m.team_b_id,
                placeholder_side_a=m.placeholder_side_a,
                placeholder_side_b=m.placeholder_side_b,
                schedule_version_id=m.schedule_version_id,
                cleared_slots=m.cleared_slots,
            )
            for m in result.affected_source_matches
        ],
        warnings=result.warnings,
        message=result.message,
        player_ids=result.player_ids,
        seed_cleared=result.seed_cleared,
        avoid_edges_removed=result.avoid_edges_removed,
    )


@router.get(
    "/tournaments/{tournament_id}/schedule/matches/{match_id}/wf-r1-matchup",
    response_model=WfR1MatchupContextResponse,
)
def get_wf_r1_matchup(
    tournament_id: int,
    match_id: int,
    session: Session = Depends(get_session),
):
    try:
        ctx = get_wf_r1_matchup_context(session, match_id, tournament_id)
    except PostDrawCorrectionError as exc:
        _raise_correction_error(exc)

    return WfR1MatchupContextResponse(
        tournament_id=ctx.tournament_id,
        event_id=ctx.event_id,
        event_name=ctx.event_name,
        stage=ctx.stage,
        round_index=ctx.round_index,
        match_id=ctx.match_id,
        match_code=ctx.match_code,
        sequence_in_round=ctx.sequence_in_round,
        team_a=TeamSummaryResponse(**ctx.team_a.__dict__) if ctx.team_a else None,
        team_b=TeamSummaryResponse(**ctx.team_b.__dict__) if ctx.team_b else None,
        scheduled_time=ctx.scheduled_time,
        court_label=ctx.court_label,
        day_date=ctx.day_date,
        status=ctx.status,
        runtime_status=ctx.runtime_status,
        winner_team_id=ctx.winner_team_id,
        has_score=ctx.has_score,
        started_at=ctx.started_at,
        completed_at=ctx.completed_at,
        edit_blocked=ctx.edit_blocked,
        edit_block_reason=ctx.edit_block_reason,
        available_teams=[TeamSummaryResponse(**t.__dict__) for t in ctx.available_teams],
    )


@router.post(
    "/tournaments/{tournament_id}/schedule/matches/{match_id}/wf-r1-matchup",
    response_model=EditWfR1MatchupResponse,
)
def edit_wf_r1_matchup(
    tournament_id: int,
    match_id: int,
    body: EditWfR1MatchupRequest,
    request: Request,
    session: Session = Depends(get_session),
):
    try:
        result = edit_first_round_wf_matchup(
            session,
            match_id=match_id,
            tournament_id=tournament_id,
            team_a_id=body.team_a_id,
            team_b_id=body.team_b_id,
            staff_user=_staff_user_from_request(request),
        )
        session.commit()
    except PostDrawCorrectionError as exc:
        session.rollback()
        _raise_correction_error(exc)
    except Exception:
        session.rollback()
        raise

    return EditWfR1MatchupResponse(
        match_id=result.match_id,
        event_id=result.event_id,
        tournament_id=result.tournament_id,
        old_team_a_id=result.old_team_a_id,
        old_team_b_id=result.old_team_b_id,
        new_team_a_id=result.new_team_a_id,
        new_team_b_id=result.new_team_b_id,
        match_type=result.match_type,
        round_index=result.round_index,
        sequence_in_round=result.sequence_in_round,
        status=result.status,
        assignment_slot_id=result.assignment_slot_id,
        court_label=result.court_label,
        scheduled_time=result.scheduled_time,
    )


@router.post(
    "/tournaments/{tournament_id}/teams/swap-post-draw",
    response_model=SwapPostDrawTeamsResponse,
)
def swap_post_draw_teams_route(
    tournament_id: int,
    body: SwapPostDrawTeamsRequest,
    request: Request,
    session: Session = Depends(get_session),
):
    try:
        result = swap_post_draw_teams(
            session,
            tournament_id=tournament_id,
            team_a_id=body.team_a_id,
            team_b_id=body.team_b_id,
            schedule_version_id=body.schedule_version_id,
            staff_user=_staff_user_from_request(request),
        )
        session.commit()
    except PostDrawCorrectionError as exc:
        session.rollback()
        _raise_correction_error(exc)
    except Exception:
        session.rollback()
        raise

    def _slot(info) -> SwapSlotResponse:
        return SwapSlotResponse(
            match_id=info.match_id,
            side=info.side,
            match_code=info.match_code,
            sequence_in_round=info.sequence_in_round,
            event_id=info.event_id,
        )

    return SwapPostDrawTeamsResponse(
        mode=result.mode,
        tournament_id=result.tournament_id,
        team_a_id=result.team_a_id,
        team_b_id=result.team_b_id,
        team_a_name=result.team_a_name,
        team_b_name=result.team_b_name,
        team_a_old_event_id=result.team_a_old_event_id,
        team_a_new_event_id=result.team_a_new_event_id,
        team_b_old_event_id=result.team_b_old_event_id,
        team_b_new_event_id=result.team_b_new_event_id,
        team_a_old_event_name=result.team_a_old_event_name,
        team_a_new_event_name=result.team_a_new_event_name,
        team_b_old_event_name=result.team_b_old_event_name,
        team_b_new_event_name=result.team_b_new_event_name,
        team_a_old_slot=_slot(result.team_a_old_slot),
        team_a_new_slot=_slot(result.team_a_new_slot),
        team_b_old_slot=_slot(result.team_b_old_slot),
        team_b_new_slot=_slot(result.team_b_new_slot),
        warnings=result.warnings,
        message=result.message,
        seed_cleared_team_ids=result.seed_cleared_team_ids,
        wf_group_index_cleared_team_ids=result.wf_group_index_cleared_team_ids,
        avoid_edges_removed=result.avoid_edges_removed,
        player_ids_a=result.player_ids_a,
        player_ids_b=result.player_ids_b,
    )
