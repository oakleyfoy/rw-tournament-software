"""Unguessable public page for one team's official photograph."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel
from sqlmodel import Session

from app.database import get_session
from app.services.team_photo_sms import resolve_team_photo_share
from app.services.team_photo_storage import PhotoStorageUnavailable, get_object_store

router = APIRouter(prefix="/api/public/team-photo", tags=["public"])

_UNAVAILABLE = "This photo link is no longer available"


class PublicTeamPhotoPage(BaseModel):
    tournament_name: str
    players: list[str]


@router.get("/{token}", response_model=PublicTeamPhotoPage)
def public_team_photo_page(token: str, session: Session = Depends(get_session)):
    resolved = resolve_team_photo_share(session, token)
    if resolved is None:
        raise HTTPException(status_code=404, detail=_UNAVAILABLE)
    _share, _photo, _team, tournament, names = resolved
    return PublicTeamPhotoPage(tournament_name=tournament.name, players=names)


@router.get("/{token}/image")
def public_team_photo_image(
    token: str,
    download: int = Query(default=0),
    session: Session = Depends(get_session),
):
    resolved = resolve_team_photo_share(session, token)
    if resolved is None:
        raise HTTPException(status_code=404, detail=_UNAVAILABLE)
    _share, photo, _team, _tournament, _names = resolved
    try:
        data = get_object_store().get_bytes(photo.storage_key)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=_UNAVAILABLE) from exc
    except PhotoStorageUnavailable as exc:
        raise HTTPException(status_code=503, detail="Team photo is temporarily unavailable") from exc
    disposition = "attachment" if download else "inline"
    return Response(
        content=data,
        media_type="image/jpeg",
        headers={
            "Cache-Control": "private, no-store",
            "Content-Disposition": f'{disposition}; filename="racquet-war-team-photo.jpg"',
        },
    )
