"""Photographer and staff endpoints for official tournament team photos."""

from __future__ import annotations

from datetime import date, datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from sqlmodel import Session, select

from app.auth import require_photo_user
from app.database import get_session
from app.models.event import Event
from app.models.team import Team
from app.models.team_photo import PhotographerTournamentAccess, TeamOfficialPhoto
from app.models.tournament import Tournament
from app.models.user_account import UserAccount
from app.services.team_photo_search import search_tournament_teams
from app.services.team_photo_storage import (
    PhotoRejected,
    PhotoStorageUnavailable,
    display_thumb_key,
    get_object_store,
    make_display_thumbnail,
    process_image,
)
from app.services.team_photos import delete_official_photo, save_official_photo

router = APIRouter(prefix="/api/photography", tags=["photography"], dependencies=[Depends(require_photo_user)])


class PhotographyTournamentItem(BaseModel):
    id: int
    name: str
    location: str
    start_date: date
    end_date: date


class PhotoTeamSearchHit(BaseModel):
    team_id: int
    event_id: int
    division: str
    seed: Optional[int] = None
    player_names: List[str]
    avoid_group: Optional[str] = None
    source_team_key: Optional[str] = None
    has_official_photo: bool = False


class OfficialPhotoResponse(BaseModel):
    team_id: int
    tournament_id: int
    photographer_user_id: Optional[int] = None
    captured_at: datetime
    updated_at: datetime
    byte_size: int
    version: str


class OfficialPhotoSummary(BaseModel):
    team_id: int
    updated_at: datetime
    version: str


class TeamPhotoSmsPlayerStatus(BaseModel):
    name: str
    status: str
    detail: Optional[str] = None


class TeamPhotoSmsStatusResponse(BaseModel):
    players: List[TeamPhotoSmsPlayerStatus]


def _role(user: UserAccount) -> str:
    return (user.role or "").strip().lower()


def _assert_can_photograph(session: Session, user: UserAccount, tournament_id: int) -> Tournament:
    tournament = session.get(Tournament, tournament_id)
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")
    if _role(user) in {"admin", "director"}:
        return tournament
    access = session.exec(
        select(PhotographerTournamentAccess).where(
            PhotographerTournamentAccess.user_id == user.id,
            PhotographerTournamentAccess.tournament_id == tournament_id,
        )
    ).first()
    if not access:
        raise HTTPException(status_code=403, detail="Not authorized to photograph this tournament")
    return tournament


def _team_in_tournament(session: Session, tournament_id: int, team_id: int) -> Team:
    team = session.get(Team, team_id)
    if not team or team.id is None:
        raise HTTPException(status_code=404, detail="Team not found")
    event = session.get(Event, team.event_id)
    if not event or event.tournament_id != tournament_id:
        raise HTTPException(status_code=404, detail="Team not found")
    return team


def _official_or_404(session: Session, team_id: int) -> TeamOfficialPhoto:
    photo = session.exec(select(TeamOfficialPhoto).where(TeamOfficialPhoto.team_id == team_id)).first()
    if not photo:
        raise HTTPException(status_code=404, detail="No official team photo")
    return photo


@router.get("/tournaments", response_model=List[PhotographyTournamentItem])
def list_photography_tournaments(
    user: UserAccount = Depends(require_photo_user),
    session: Session = Depends(get_session),
):
    if _role(user) in {"admin", "director"}:
        tournaments = session.exec(select(Tournament).order_by(Tournament.start_date.desc())).all()
    else:
        access_rows = session.exec(
            select(PhotographerTournamentAccess).where(PhotographerTournamentAccess.user_id == user.id)
        ).all()
        ids = [row.tournament_id for row in access_rows]
        if not ids:
            return []
        tournaments = session.exec(select(Tournament).where(Tournament.id.in_(ids))).all()  # type: ignore[attr-defined]
        tournaments.sort(key=lambda item: item.start_date, reverse=True)
    return [
        PhotographyTournamentItem(
            id=item.id,  # type: ignore[arg-type]
            name=item.name,
            location=item.location,
            start_date=item.start_date,
            end_date=item.end_date,
        )
        for item in tournaments
        if item.id is not None
    ]


@router.get("/tournaments/{tournament_id}/teams/search", response_model=List[PhotoTeamSearchHit])
def search_teams(
    tournament_id: int,
    q: str = "",
    user: UserAccount = Depends(require_photo_user),
    session: Session = Depends(get_session),
):
    _assert_can_photograph(session, user, tournament_id)
    return [PhotoTeamSearchHit(**hit) for hit in search_tournament_teams(session, tournament_id, q)]


@router.get("/tournaments/{tournament_id}/official-photos", response_model=List[OfficialPhotoSummary])
def list_official_photos(
    tournament_id: int,
    user: UserAccount = Depends(require_photo_user),
    session: Session = Depends(get_session),
):
    _assert_can_photograph(session, user, tournament_id)
    rows = session.exec(select(TeamOfficialPhoto).where(TeamOfficialPhoto.tournament_id == tournament_id)).all()
    return [
        OfficialPhotoSummary(team_id=row.team_id, updated_at=row.updated_at, version=row.storage_key)
        for row in rows
    ]


def _photo_response(photo: TeamOfficialPhoto) -> OfficialPhotoResponse:
    return OfficialPhotoResponse(
        team_id=photo.team_id,
        tournament_id=photo.tournament_id,
        photographer_user_id=photo.photographer_user_id,
        captured_at=photo.captured_at,
        updated_at=photo.updated_at,
        byte_size=photo.byte_size,
        version=photo.storage_key,
    )


def _discard_new_object(storage_key: Optional[str]) -> None:
    if not storage_key:
        return
    try:
        get_object_store().delete(storage_key)
    except PhotoStorageUnavailable:
        return


@router.post(
    "/tournaments/{tournament_id}/teams/{team_id}/official",
    response_model=OfficialPhotoResponse,
)
async def set_official_photo(
    tournament_id: int,
    team_id: int,
    file: UploadFile = File(...),
    client_upload_id: str = Form(...),
    user: UserAccount = Depends(require_photo_user),
    session: Session = Depends(get_session),
):
    client_upload_id = (client_upload_id or "").strip()
    if len(client_upload_id) < 8 or len(client_upload_id) > 80:
        raise HTTPException(status_code=400, detail="client_upload_id is invalid")
    _assert_can_photograph(session, user, tournament_id)
    team = _team_in_tournament(session, tournament_id, team_id)
    raw = await file.read()
    result = None
    try:
        processed = process_image(raw)
        result = save_official_photo(
            session,
            tournament_id=tournament_id,
            team_id=team.id,  # type: ignore[arg-type]
            client_upload_id=client_upload_id,
            image_bytes=processed,
            photographer_user_id=user.id,
        )
        if result.created:
            from app.services.team_photo_sms import queue_team_photo_sms

            queue_team_photo_sms(session, result.photo)
        session.commit()
    except PhotoRejected as exc:
        session.rollback()
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    except PhotoStorageUnavailable as exc:
        session.rollback()
        if result is not None:
            _discard_new_object(result.delete_on_failure)
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception:
        session.rollback()
        if result is not None:
            _discard_new_object(result.delete_on_failure)
        raise
    if result.delete_after_commit:
        _discard_new_object(result.delete_after_commit)
        _discard_new_object(display_thumb_key(result.delete_after_commit))
    session.refresh(result.photo)
    return _photo_response(result.photo)


@router.get(
    "/tournaments/{tournament_id}/teams/{team_id}/photo-sms",
    response_model=TeamPhotoSmsStatusResponse,
)
def team_photo_sms_delivery(
    tournament_id: int,
    team_id: int,
    user: UserAccount = Depends(require_photo_user),
    session: Session = Depends(get_session),
):
    """Read photo-text status. Opening this does not send or resend anything."""
    _assert_can_photograph(session, user, tournament_id)
    _team_in_tournament(session, tournament_id, team_id)
    from app.services.team_photo_sms import team_photo_sms_status

    return TeamPhotoSmsStatusResponse(
        players=[TeamPhotoSmsPlayerStatus(**row) for row in team_photo_sms_status(session, tournament_id, team_id)]
    )


@router.delete("/tournaments/{tournament_id}/teams/{team_id}/official")
def remove_official_photo(
    tournament_id: int,
    team_id: int,
    user: UserAccount = Depends(require_photo_user),
    session: Session = Depends(get_session),
):
    _assert_can_photograph(session, user, tournament_id)
    team = _team_in_tournament(session, tournament_id, team_id)
    try:
        delete_official_photo(session, tournament_id=tournament_id, team_id=team.id)  # type: ignore[arg-type]
        session.commit()
    except PhotoRejected as exc:
        session.rollback()
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    except PhotoStorageUnavailable as exc:
        session.rollback()
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception:
        session.rollback()
        raise
    return {"team_id": team.id, "deleted": True}


@router.get("/teams/{team_id}/official/content")
def official_photo_content(
    team_id: int,
    user: UserAccount = Depends(require_photo_user),
    session: Session = Depends(get_session),
):
    team = session.get(Team, team_id)
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
    event = session.get(Event, team.event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Team not found")
    _assert_can_photograph(session, user, event.tournament_id)
    photo = _official_or_404(session, team_id)
    if photo.team_id != team_id or photo.tournament_id != event.tournament_id:
        raise HTTPException(status_code=404, detail="No official team photo")
    try:
        data = get_object_store().get_bytes(photo.storage_key)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="No official team photo") from exc
    except PhotoStorageUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return Response(
        content=data,
        media_type="image/jpeg",
        headers={"Cache-Control": "private, no-store"},
    )


@router.get("/teams/{team_id}/official/thumb")
def official_photo_thumb(
    team_id: int,
    user: UserAccount = Depends(require_photo_user),
    session: Session = Depends(get_session),
):
    """Small display copy for Check-In Desk and Score Entry. The original object is not rewritten."""
    team = session.get(Team, team_id)
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
    event = session.get(Event, team.event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Team not found")
    _assert_can_photograph(session, user, event.tournament_id)
    photo = _official_or_404(session, team_id)
    if photo.team_id != team_id or photo.tournament_id != event.tournament_id:
        raise HTTPException(status_code=404, detail="No official team photo")
    store = get_object_store()
    thumb_key = display_thumb_key(photo.storage_key)
    try:
        thumb = None
        if thumb_key:
            try:
                thumb = store.get_bytes(thumb_key)
            except FileNotFoundError:
                thumb = None
        if thumb is None:
            original = store.get_bytes(photo.storage_key)
            thumb = make_display_thumbnail(original)
            if store.get_bytes(photo.storage_key) != original:
                raise HTTPException(status_code=500, detail="Official photograph was not left unchanged")
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="No official team photo") from exc
    except PhotoRejected as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    except PhotoStorageUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return Response(
        content=thumb,
        media_type="image/jpeg",
        headers={"Cache-Control": "private, max-age=300"},
    )
