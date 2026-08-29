from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from app.database import get_session
from app.models.match import Match
from app.models.tournament_import import TournamentImport
from app.services.rw_os_client import RwOsClient, RwOsClientError
from app.services.rw_os_import import (
    approve_structures,
    build_import_response,
    create_import_from_event,
    default_forecasts,
    get_latest_import_for_tournament,
    list_importable_events,
    preview_custom_structure,
    refresh_import,
    save_forecasts,
    select_draw_structure,
)
from app.services.structure_events import serialize_structure_event, sync_events_from_approved_plans

router = APIRouter(prefix="/rw-os", tags=["rw-os-import"])


class ImportCreateRequest(BaseModel):
    tournament_id: int
    organization_slug: str = "rw"


class RefreshRequest(BaseModel):
    apply: bool = False


class SelectStructureRequest(BaseModel):
    draw_kind: str
    option_key: str


class ApprovePlanRequest(BaseModel):
    selections: Dict[str, str]


class ForecastUpdateRequest(BaseModel):
    forecasts: Dict[str, int]


class CustomStructureRequest(BaseModel):
    draw_kind: str
    sizes: List[int]


def _get_import(session: Session, import_id: int) -> TournamentImport:
    row = session.get(TournamentImport, import_id)
    if not row:
        raise HTTPException(status_code=404, detail="Import was not found.")
    return row


@router.get("/events")
def list_rw_os_events(session: Session = Depends(get_session)):
    try:
        client = RwOsClient()
        return {
            "events": list_importable_events(session, client),
            "source": "fixtures" if client.fixtures else "live",
        }
    except RwOsClientError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.get("/events/{source_tournament_id}")
def get_rw_os_event(source_tournament_id: int):
    try:
        return RwOsClient().get_event(source_tournament_id)
    except RwOsClientError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.post("/imports", status_code=201)
def create_rw_os_import(payload: ImportCreateRequest, session: Session = Depends(get_session)):
    try:
        import_row = create_import_from_event(
            session,
            payload.tournament_id,
            organization_slug=payload.organization_slug,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except RwOsClientError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return build_import_response(session, import_row)


@router.get("/imports/{import_id}")
def get_rw_os_import(import_id: int, session: Session = Depends(get_session)):
    return build_import_response(session, _get_import(session, import_id))


@router.get("/tournaments/{tournament_id}/import")
def get_tournament_import(tournament_id: int, session: Session = Depends(get_session)):
    row = get_latest_import_for_tournament(session, tournament_id)
    if not row:
        raise HTTPException(status_code=404, detail="No RW-OS import exists for this tournament.")
    return build_import_response(session, row)


@router.post("/imports/{import_id}/refresh")
def refresh_rw_os_import(
    import_id: int,
    payload: Optional[RefreshRequest] = None,
    session: Session = Depends(get_session),
):
    row = _get_import(session, import_id)
    apply = bool(payload.apply) if payload else False
    try:
        result = refresh_import(session, row, apply=apply)
    except RwOsClientError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    result["importResponse"] = build_import_response(session, row)
    return result


@router.put("/imports/{import_id}/forecasts")
def update_rw_os_forecasts(
    import_id: int,
    payload: ForecastUpdateRequest,
    session: Session = Depends(get_session),
):
    row = _get_import(session, import_id)
    try:
        save_forecasts(session, row, payload.forecasts)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return build_import_response(session, row)


@router.post("/imports/{import_id}/forecasts/reset")
def reset_rw_os_forecasts(import_id: int, session: Session = Depends(get_session)):
    row = _get_import(session, import_id)
    save_forecasts(session, row, default_forecasts(row))
    return build_import_response(session, row)


@router.post("/imports/{import_id}/custom-structure")
def preview_rw_os_custom_structure(
    import_id: int,
    payload: CustomStructureRequest,
    session: Session = Depends(get_session),
):
    row = _get_import(session, import_id)
    try:
        preview = preview_custom_structure(row, payload.draw_kind, payload.sizes)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    response = build_import_response(session, row)
    response["customOption"] = preview["option"]
    response["customDrawKind"] = payload.draw_kind
    return response


@router.post("/imports/{import_id}/select-structure")
def select_rw_os_structure(
    import_id: int,
    payload: SelectStructureRequest,
    session: Session = Depends(get_session),
):
    row = _get_import(session, import_id)
    try:
        select_draw_structure(session, row, payload.draw_kind, payload.option_key, approve=False)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return build_import_response(session, row)


@router.post("/imports/{import_id}/approve")
def approve_rw_os_plan(
    import_id: int,
    payload: ApprovePlanRequest,
    session: Session = Depends(get_session),
):
    row = _get_import(session, import_id)
    try:
        plans = approve_structures(session, row, payload.selections)
        sync = sync_events_from_approved_plans(session, row.tournament_id, plans)
        from app.services.rw_os_roster_projection import project_approved_roster

        projection = project_approved_roster(
            session,
            row,
            plans,
            events_created=len(sync.created),
            operational_only=False,
            allow_structural_rebuild=True,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    session.refresh(row)
    matches = session.exec(select(Match).where(Match.tournament_id == row.tournament_id)).all()
    response = build_import_response(session, row)
    response["eventsCreated"] = len(sync.created)
    response["eventsUpdated"] = len(sync.updated)
    response["matchesCreated"] = len(matches)
    response["bracketsCreated"] = False
    response["tournamentEvents"] = [serialize_structure_event(event) for event in sync.events]
    response["structureEventConflicts"] = sync.conflicts
    response["rosterProjection"] = projection.to_dict()
    response["projectionOk"] = projection.ok
    return response
