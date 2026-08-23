from typing import Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from app.database import get_session
from app.models.event import Event
from app.models.match import Match
from app.models.tournament_import import TournamentImport
from app.services.rw_os_client import RwOsClient, RwOsClientError
from app.services.rw_os_import import (
    approve_structures,
    build_import_response,
    create_import_from_event,
    list_importable_events,
    refresh_import,
    select_draw_structure,
)

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


def _get_import(session: Session, import_id: int) -> TournamentImport:
    row = session.get(TournamentImport, import_id)
    if not row:
        raise HTTPException(status_code=404, detail="Import was not found.")
    return row


@router.get("/events")
def list_rw_os_events(session: Session = Depends(get_session)):
    try:
        return {"events": list_importable_events(session, RwOsClient())}
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
    row = session.exec(
        select(TournamentImport).where(TournamentImport.tournament_id == tournament_id)
    ).first()
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
        approve_structures(session, row, payload.selections)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    session.refresh(row)
    events = session.exec(select(Event).where(Event.tournament_id == row.tournament_id)).all()
    matches = session.exec(select(Match).where(Match.tournament_id == row.tournament_id)).all()
    response = build_import_response(session, row)
    response["eventsCreated"] = len(events)
    response["matchesCreated"] = len(matches)
    response["bracketsCreated"] = False
    return response
