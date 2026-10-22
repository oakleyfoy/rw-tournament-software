"""Watermark settings and print exports for official team photographs."""

from __future__ import annotations

import io
import json
import zipfile
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from app.auth import require_photo_user
from app.database import get_session
from app.models.event import Event
from app.models.player import Player
from app.models.team import Team
from app.models.group_photo import TournamentGroupPhoto, TournamentGroupPhotoPrint
from app.models.team_photo import PhotographerTournamentAccess, TeamOfficialPhoto
from app.models.team_photo_print import TeamPhotoPrint, TeamPhotoWatermark, TournamentPhotoWatermark
from app.models.team_player import TeamPlayer
from app.models.tournament import Tournament
from app.models.user_account import UserAccount
from app.services.team_photo_search import player_names_for_team
from app.services.team_photo_storage import PhotoRejected, PhotoStorageUnavailable, get_object_store
from app.services.team_photo_watermark import (
    WALGREENS_DIRECT_ORDERING,
    WALGREENS_NOTE,
    WALGREENS_ORDER_URL,
    default_settings,
    logo_object_key,
    new_print_version,
    normalize_settings,
    owned_logo_key,
    owned_print_key,
    prepare_logo,
    PRINT_SIZE,
    crop_cuts_photo,
    group_print_object_key,
    owned_group_print_key,
    print_filename,
    print_object_key,
    print_pixels,
    render_print_jpeg,
    source_needs_upscale,
)

router = APIRouter(prefix="/api/photography", tags=["photography"], dependencies=[Depends(require_photo_user)])


class WatermarkSettingsBody(BaseModel):
    settings: dict


class ReviewBody(BaseModel):
    reviewed: bool = True


class PrintRequest(BaseModel):
    team_ids: List[int] = Field(default_factory=list)
    group_photo_ids: List[int] = Field(default_factory=list)
    print_size: str = "4x6"
    quantity: int = 1
    acknowledge_low_resolution: bool = False


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


def _settings_row(session: Session, tournament_id: int) -> Optional[TournamentPhotoWatermark]:
    return session.exec(
        select(TournamentPhotoWatermark).where(TournamentPhotoWatermark.tournament_id == tournament_id)
    ).first()


def _stored_settings(session: Session, tournament: Tournament) -> dict:
    row = _settings_row(session, tournament.id)  # type: ignore[arg-type]
    if not row:
        return default_settings(tournament.name)
    try:
        payload = json.loads(row.settings_json)
    except json.JSONDecodeError:
        return default_settings(tournament.name)
    return normalize_settings(payload, tournament.name)


def _photo_names(session: Session, team: Team) -> list[str]:
    links = session.exec(select(TeamPlayer).where(TeamPlayer.team_id == team.id)).all()
    player_ids = [link.player_id for link in links]
    players = session.exec(select(Player).where(Player.id.in_(player_ids))).all() if player_ids else []  # type: ignore[attr-defined]
    by_id = {player.id: player.full_name for player in players}
    ordered = []
    for link in sorted(links, key=lambda item: item.lineup_slot if item.lineup_slot is not None else 99):
        name = by_id.get(link.player_id)
        if name:
            ordered.append(name)
    return player_names_for_team(team, ordered)


def _image_size(data: bytes) -> tuple[int, int]:
    from PIL import Image, ImageOps

    with Image.open(io.BytesIO(data)) as image:
        image = ImageOps.exif_transpose(image)
        return image.size


def _http_photo_error(exc: Exception) -> HTTPException:
    if isinstance(exc, PhotoRejected):
        return HTTPException(status_code=exc.status_code, detail=str(exc))
    if isinstance(exc, PhotoStorageUnavailable):
        return HTTPException(status_code=503, detail=str(exc))
    raise exc


def _workspace(session: Session, tournament: Tournament) -> dict:
    tournament_id = tournament.id
    photos = session.exec(
        select(TeamOfficialPhoto).where(TeamOfficialPhoto.tournament_id == tournament_id)
    ).all()
    events = session.exec(select(Event).where(Event.tournament_id == tournament_id)).all()
    event_ids = [event.id for event in events if event.id is not None]
    teams = session.exec(select(Team).where(Team.event_id.in_(event_ids))).all() if event_ids else []  # type: ignore[attr-defined]
    team_by_id = {team.id: team for team in teams if team.id is not None}
    overrides = session.exec(
        select(TeamPhotoWatermark).where(TeamPhotoWatermark.tournament_id == tournament_id)
    ).all()
    override_by_team = {row.team_id: row for row in overrides}
    default = _stored_settings(session, tournament)
    store = get_object_store()
    items = []
    for photo in photos:
        team = team_by_id.get(photo.team_id)
        if team is None:
            continue
        try:
            source = store.get_bytes(photo.storage_key)
            width, height = _image_size(source)
        except Exception:
            width, height = 0, 0
        override = override_by_team.get(photo.team_id)
        settings = default
        has_override = bool(override and override.settings_json)
        if has_override:
            try:
                settings = normalize_settings(json.loads(override.settings_json or "{}"), tournament.name)
            except (json.JSONDecodeError, PhotoRejected):
                settings = default
                has_override = False
        low_sizes = []
        target_w, target_h = print_pixels(PRINT_SIZE, width, height)
        if width and height and source_needs_upscale(width, height, target_w, target_h, settings["crop_mode"]):
            low_sizes.append(PRINT_SIZE)
        crop_warning = crop_cuts_photo(width, height, settings["crop_mode"])
        reviewed = bool(override and override.reviewed)
        items.append(
            {
                "photo_kind": "team",
                "team_id": photo.team_id,
                "group_photo_id": None,
                "player_names": _photo_names(session, team),
                "version": photo.storage_key,
                "reviewed": reviewed,
                "has_override": has_override,
                "settings": settings,
                "source_width": width,
                "source_height": height,
                "low_resolution_sizes": low_sizes,
                "crop_warning": crop_warning,
                "needs_attention": (not reviewed) or bool(low_sizes) or crop_warning,
            }
        )
    items.sort(key=lambda item: " ".join(item["player_names"]).lower())
    group_items = _group_photo_items(session, tournament, default, store)
    team_photo_count = len(items)
    items.extend(group_items)
    team_count = len(team_by_id)
    with_photos = team_photo_count
    reviewed_count = sum(1 for item in items if item["reviewed"])
    ready_count = sum(1 for item in items if item["reviewed"] and not item["low_resolution_sizes"])
    attention_count = sum(1 for item in items if item["needs_attention"])
    brand = _settings_row(session, tournament_id)  # type: ignore[arg-type]
    return {
        "tournament_id": tournament_id,
        "tournament_name": tournament.name,
        "default_settings": default,
        "has_custom_logo": bool(brand and brand.custom_logo_key),
        "totals": {
            "teams": team_count,
            "with_photos": with_photos,
            "group_photos": len(group_items),
            "reviewed": reviewed_count,
            "ready": ready_count,
            "needs_attention": attention_count,
        },
        "walgreens": {
            "ordering_url": WALGREENS_ORDER_URL,
            "direct_ordering_available": WALGREENS_DIRECT_ORDERING,
            "note": WALGREENS_NOTE,
        },
        "photos": items,
    }


def _group_photo_items(session: Session, tournament: Tournament, default: dict, store) -> list[dict]:
    photos = session.exec(
        select(TournamentGroupPhoto)
        .where(TournamentGroupPhoto.tournament_id == tournament.id)
        .order_by(TournamentGroupPhoto.id)
    ).all()
    items = []
    for index, photo in enumerate(photos, start=1):
        label = f"Group Photo {index}"
        try:
            source = store.get_bytes(photo.storage_key)
            width, height = _image_size(source)
        except Exception:
            width, height = 0, 0
        settings = default
        has_override = bool(photo.settings_json)
        if has_override:
            try:
                settings = normalize_settings(json.loads(photo.settings_json or "{}"), tournament.name)
            except (json.JSONDecodeError, PhotoRejected):
                settings = default
                has_override = False
        low_sizes = []
        target_w, target_h = print_pixels(PRINT_SIZE, width, height)
        if width and height and source_needs_upscale(width, height, target_w, target_h, settings["crop_mode"]):
            low_sizes.append(PRINT_SIZE)
        crop_warning = crop_cuts_photo(width, height, settings["crop_mode"])
        items.append(
            {
                "photo_kind": "group",
                "team_id": None,
                "group_photo_id": photo.id,
                "player_names": [label],
                "version": photo.storage_key,
                "reviewed": bool(photo.reviewed),
                "has_override": has_override,
                "settings": settings,
                "source_width": width,
                "source_height": height,
                "low_resolution_sizes": low_sizes,
                "crop_warning": crop_warning,
                "needs_attention": (not photo.reviewed) or bool(low_sizes) or crop_warning,
            }
        )
    return items


def _save_default(session: Session, tournament: Tournament, settings: dict) -> None:
    row = _settings_row(session, tournament.id)  # type: ignore[arg-type]
    if row is None:
        row = TournamentPhotoWatermark(
            tournament_id=tournament.id,  # type: ignore[arg-type]
            settings_json=json.dumps(settings),
        )
    else:
        row.settings_json = json.dumps(settings)
        row.updated_at = datetime.utcnow()
    session.add(row)


@router.get("/tournaments/{tournament_id}/photo-print")
def photo_print_workspace(
    tournament_id: int,
    user: UserAccount = Depends(require_photo_user),
    session: Session = Depends(get_session),
):
    tournament = _assert_can_photograph(session, user, tournament_id)
    return _workspace(session, tournament)


@router.put("/tournaments/{tournament_id}/photo-print/default")
def save_tournament_default(
    tournament_id: int,
    body: WatermarkSettingsBody,
    user: UserAccount = Depends(require_photo_user),
    session: Session = Depends(get_session),
):
    tournament = _assert_can_photograph(session, user, tournament_id)
    try:
        settings = normalize_settings(body.settings, tournament.name)
        _save_default(session, tournament, settings)
        session.commit()
    except PhotoRejected as exc:
        session.rollback()
        raise _http_photo_error(exc) from exc
    return {"default_settings": settings}


@router.post("/tournaments/{tournament_id}/photo-print/apply-all")
def apply_watermark_to_all(
    tournament_id: int,
    body: WatermarkSettingsBody,
    user: UserAccount = Depends(require_photo_user),
    session: Session = Depends(get_session),
):
    tournament = _assert_can_photograph(session, user, tournament_id)
    try:
        settings = normalize_settings(body.settings, tournament.name)
        _save_default(session, tournament, settings)
        overrides = session.exec(
            select(TeamPhotoWatermark).where(TeamPhotoWatermark.tournament_id == tournament_id)
        ).all()
        for row in overrides:
            row.settings_json = None
            row.updated_at = datetime.utcnow()
            session.add(row)
        groups = session.exec(
            select(TournamentGroupPhoto).where(TournamentGroupPhoto.tournament_id == tournament_id)
        ).all()
        for group in groups:
            group.settings_json = None
            session.add(group)
        session.commit()
    except PhotoRejected as exc:
        session.rollback()
        raise _http_photo_error(exc) from exc
    return _workspace(session, tournament)


@router.put("/tournaments/{tournament_id}/photo-print/photos/{team_id}")
def save_photo_override(
    tournament_id: int,
    team_id: int,
    body: WatermarkSettingsBody,
    user: UserAccount = Depends(require_photo_user),
    session: Session = Depends(get_session),
):
    tournament = _assert_can_photograph(session, user, tournament_id)
    _team_in_tournament(session, tournament_id, team_id)
    photo = session.exec(select(TeamOfficialPhoto).where(TeamOfficialPhoto.team_id == team_id)).first()
    if not photo or photo.tournament_id != tournament_id:
        raise HTTPException(status_code=404, detail="No official team photo")
    try:
        settings = normalize_settings(body.settings, tournament.name)
    except PhotoRejected as exc:
        raise _http_photo_error(exc) from exc
    row = session.exec(
        select(TeamPhotoWatermark).where(
            TeamPhotoWatermark.tournament_id == tournament_id,
            TeamPhotoWatermark.team_id == team_id,
        )
    ).first()
    if row is None:
        row = TeamPhotoWatermark(tournament_id=tournament_id, team_id=team_id, settings_json=json.dumps(settings), reviewed=True)
    else:
        row.settings_json = json.dumps(settings)
        row.reviewed = True
        row.updated_at = datetime.utcnow()
    session.add(row)
    session.commit()
    return {"team_id": team_id, "settings": settings, "reviewed": True, "has_override": True}


@router.delete("/tournaments/{tournament_id}/photo-print/photos/{team_id}")
def reset_photo_override(
    tournament_id: int,
    team_id: int,
    user: UserAccount = Depends(require_photo_user),
    session: Session = Depends(get_session),
):
    tournament = _assert_can_photograph(session, user, tournament_id)
    _team_in_tournament(session, tournament_id, team_id)
    row = session.exec(
        select(TeamPhotoWatermark).where(
            TeamPhotoWatermark.tournament_id == tournament_id,
            TeamPhotoWatermark.team_id == team_id,
        )
    ).first()
    if row is not None:
        row.settings_json = None
        row.updated_at = datetime.utcnow()
        session.add(row)
        session.commit()
    return {"team_id": team_id, "settings": _stored_settings(session, tournament), "has_override": False}


@router.post("/tournaments/{tournament_id}/photo-print/photos/{team_id}/review")
def mark_photo_reviewed(
    tournament_id: int,
    team_id: int,
    body: ReviewBody,
    user: UserAccount = Depends(require_photo_user),
    session: Session = Depends(get_session),
):
    _assert_can_photograph(session, user, tournament_id)
    _team_in_tournament(session, tournament_id, team_id)
    photo = session.exec(select(TeamOfficialPhoto).where(TeamOfficialPhoto.team_id == team_id)).first()
    if not photo or photo.tournament_id != tournament_id:
        raise HTTPException(status_code=404, detail="No official team photo")
    row = session.exec(
        select(TeamPhotoWatermark).where(
            TeamPhotoWatermark.tournament_id == tournament_id,
            TeamPhotoWatermark.team_id == team_id,
        )
    ).first()
    if row is None:
        row = TeamPhotoWatermark(tournament_id=tournament_id, team_id=team_id, reviewed=body.reviewed)
    else:
        row.reviewed = body.reviewed
        row.updated_at = datetime.utcnow()
    session.add(row)
    session.commit()
    return {"team_id": team_id, "reviewed": row.reviewed}


@router.post("/tournaments/{tournament_id}/photo-print/logo")
async def upload_custom_logo(
    tournament_id: int,
    file: UploadFile = File(...),
    remove_background: bool = Form(True),
    user: UserAccount = Depends(require_photo_user),
    session: Session = Depends(get_session),
):
    tournament = _assert_can_photograph(session, user, tournament_id)
    raw = await file.read()
    store = get_object_store()
    key = logo_object_key(tournament_id)
    try:
        prepared = prepare_logo(raw, remove_background=remove_background)
        store.put_jpeg(key, prepared, content_type="image/png")
        row = _settings_row(session, tournament_id)
        if row is None:
            row = TournamentPhotoWatermark(
                tournament_id=tournament_id,
                settings_json=json.dumps(default_settings(tournament.name)),
                custom_logo_key=key,
            )
        else:
            row.custom_logo_key = key
            row.updated_at = datetime.utcnow()
        session.add(row)
        session.commit()
    except (PhotoRejected, PhotoStorageUnavailable) as exc:
        session.rollback()
        raise _http_photo_error(exc) from exc
    return {"has_custom_logo": True}


@router.get("/tournaments/{tournament_id}/photo-print/logo")
def custom_logo_content(
    tournament_id: int,
    user: UserAccount = Depends(require_photo_user),
    session: Session = Depends(get_session),
):
    _assert_can_photograph(session, user, tournament_id)
    row = _settings_row(session, tournament_id)
    if not row or not owned_logo_key(tournament_id, row.custom_logo_key):
        raise HTTPException(status_code=404, detail="No custom logo")
    try:
        data = get_object_store().get_bytes(row.custom_logo_key or "")
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="No custom logo") from exc
    except PhotoStorageUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return Response(content=data, media_type="image/png")


def _render_team(
    session: Session,
    tournament: Tournament,
    team_id: int,
    print_size: str,
    quantity: int,
    acknowledge: bool,
) -> dict:
    team = _team_in_tournament(session, tournament.id, team_id)  # type: ignore[arg-type]
    photo = session.exec(select(TeamOfficialPhoto).where(TeamOfficialPhoto.team_id == team_id)).first()
    if not photo or photo.tournament_id != tournament.id:
        raise HTTPException(status_code=404, detail="No official team photo")
    if not str(photo.storage_key).startswith(f"team-photos/{int(tournament.id)}/"):
        raise HTTPException(status_code=404, detail="No official team photo")
    workspace_default = _stored_settings(session, tournament)
    override = session.exec(
        select(TeamPhotoWatermark).where(
            TeamPhotoWatermark.tournament_id == tournament.id,
            TeamPhotoWatermark.team_id == team_id,
        )
    ).first()
    settings = workspace_default
    if override and override.settings_json:
        settings = normalize_settings(json.loads(override.settings_json), tournament.name)
    store = get_object_store()
    original = store.get_bytes(photo.storage_key)
    original_key = photo.storage_key
    logo_bytes = None
    brand = _settings_row(session, tournament.id)  # type: ignore[arg-type]
    if settings["content_mode"] == "custom_logo" and brand and owned_logo_key(tournament.id, brand.custom_logo_key):  # type: ignore[arg-type]
        try:
            logo_bytes = store.get_bytes(brand.custom_logo_key or "")
        except FileNotFoundError:
            logo_bytes = None
    rendered, width, height, source_w, source_h, low_resolution = render_print_jpeg(
        original,
        settings,
        print_size,
        logo_bytes=logo_bytes,
        allow_upscale=acknowledge,
    )
    if store.get_bytes(original_key) != original:
        raise HTTPException(status_code=500, detail="Official photograph was not left unchanged")
    version = new_print_version()
    key = print_object_key(tournament.id, team_id, version)  # type: ignore[arg-type]
    names = _photo_names(session, team)
    filename = print_filename(tournament.name, names, print_size)
    existing = session.exec(
        select(TeamPhotoPrint).where(
            TeamPhotoPrint.tournament_id == tournament.id,
            TeamPhotoPrint.team_id == team_id,
            TeamPhotoPrint.print_size == print_size,
        )
    ).first()
    previous_key = existing.storage_key if existing else None
    store.put_jpeg(key, rendered)
    if existing is None:
        existing = TeamPhotoPrint(
            tournament_id=tournament.id,  # type: ignore[arg-type]
            team_id=team_id,
            print_size=print_size,
            storage_key=key,
            filename=filename,
            byte_size=len(rendered),
            width=width,
            height=height,
            source_width=source_w,
            source_height=source_h,
            low_resolution=low_resolution,
            quantity=quantity,
            settings_json=json.dumps(settings),
        )
    else:
        existing.storage_key = key
        existing.filename = filename
        existing.byte_size = len(rendered)
        existing.width = width
        existing.height = height
        existing.source_width = source_w
        existing.source_height = source_h
        existing.low_resolution = low_resolution
        existing.quantity = quantity
        existing.settings_json = json.dumps(settings)
        existing.created_at = datetime.utcnow()
    session.add(existing)
    if previous_key and previous_key != key and owned_print_key(tournament.id, team_id, previous_key):  # type: ignore[arg-type]
        store.delete(previous_key)
    photo_after = session.get(TeamOfficialPhoto, photo.id)
    if photo_after is None or photo_after.storage_key != original_key:
        raise HTTPException(status_code=500, detail="Official photograph was not left unchanged")
    return {
        "team_id": team_id,
        "player_names": names,
        "print_size": print_size,
        "filename": filename,
        "width": width,
        "height": height,
        "source_width": source_w,
        "source_height": source_h,
        "low_resolution": low_resolution,
        "quantity": quantity,
        "byte_size": len(rendered),
    }


def _group_in_tournament(session: Session, tournament_id: int, group_photo_id: int) -> TournamentGroupPhoto:
    photo = session.get(TournamentGroupPhoto, group_photo_id)
    if not photo or photo.tournament_id != tournament_id:
        raise HTTPException(status_code=404, detail="Group photo is not available")
    return photo


def _group_label(session: Session, photo: TournamentGroupPhoto) -> str:
    rows = session.exec(
        select(TournamentGroupPhoto)
        .where(TournamentGroupPhoto.tournament_id == photo.tournament_id)
        .order_by(TournamentGroupPhoto.id)
    ).all()
    for index, row in enumerate(rows, start=1):
        if row.id == photo.id:
            return f"Group Photo {index}"
    return "Group Photo"


@router.put("/tournaments/{tournament_id}/photo-print/group-photos/{group_photo_id}")
def save_group_photo_override(
    tournament_id: int,
    group_photo_id: int,
    body: WatermarkSettingsBody,
    user: UserAccount = Depends(require_photo_user),
    session: Session = Depends(get_session),
):
    tournament = _assert_can_photograph(session, user, tournament_id)
    photo = _group_in_tournament(session, tournament_id, group_photo_id)
    try:
        settings = normalize_settings(body.settings, tournament.name)
    except PhotoRejected as exc:
        raise _http_photo_error(exc) from exc
    photo.settings_json = json.dumps(settings)
    photo.reviewed = True
    session.add(photo)
    session.commit()
    return {"group_photo_id": group_photo_id, "settings": settings, "reviewed": True, "has_override": True}


@router.delete("/tournaments/{tournament_id}/photo-print/group-photos/{group_photo_id}")
def reset_group_photo_override(
    tournament_id: int,
    group_photo_id: int,
    user: UserAccount = Depends(require_photo_user),
    session: Session = Depends(get_session),
):
    tournament = _assert_can_photograph(session, user, tournament_id)
    photo = _group_in_tournament(session, tournament_id, group_photo_id)
    photo.settings_json = None
    session.add(photo)
    session.commit()
    return {"group_photo_id": group_photo_id, "settings": _stored_settings(session, tournament), "has_override": False}


@router.post("/tournaments/{tournament_id}/photo-print/group-photos/{group_photo_id}/review")
def mark_group_photo_reviewed(
    tournament_id: int,
    group_photo_id: int,
    body: ReviewBody,
    user: UserAccount = Depends(require_photo_user),
    session: Session = Depends(get_session),
):
    _assert_can_photograph(session, user, tournament_id)
    photo = _group_in_tournament(session, tournament_id, group_photo_id)
    photo.reviewed = body.reviewed
    session.add(photo)
    session.commit()
    return {"group_photo_id": group_photo_id, "reviewed": photo.reviewed}


def _render_group(
    session: Session,
    tournament: Tournament,
    group_photo_id: int,
    print_size: str,
    quantity: int,
    acknowledge: bool,
) -> dict:
    photo = _group_in_tournament(session, tournament.id, group_photo_id)  # type: ignore[arg-type]
    if not str(photo.storage_key).startswith(f"team-photos/{int(tournament.id)}/groups/"):
        raise HTTPException(status_code=404, detail="Group photo is not available")
    settings = _stored_settings(session, tournament)
    if photo.settings_json:
        settings = normalize_settings(json.loads(photo.settings_json), tournament.name)
    store = get_object_store()
    original = store.get_bytes(photo.storage_key)
    original_key = photo.storage_key
    logo_bytes = None
    brand = _settings_row(session, tournament.id)  # type: ignore[arg-type]
    if settings["content_mode"] == "custom_logo" and brand and owned_logo_key(tournament.id, brand.custom_logo_key):  # type: ignore[arg-type]
        try:
            logo_bytes = store.get_bytes(brand.custom_logo_key or "")
        except FileNotFoundError:
            logo_bytes = None
    rendered, width, height, source_w, source_h, low_resolution = render_print_jpeg(
        original,
        settings,
        print_size,
        logo_bytes=logo_bytes,
        allow_upscale=acknowledge,
    )
    if store.get_bytes(original_key) != original:
        raise HTTPException(status_code=500, detail="Group photograph was not left unchanged")
    version = new_print_version()
    key = group_print_object_key(tournament.id, group_photo_id, version)  # type: ignore[arg-type]
    label = _group_label(session, photo)
    filename = print_filename(tournament.name, [label], print_size)
    existing = session.exec(
        select(TournamentGroupPhotoPrint).where(
            TournamentGroupPhotoPrint.group_photo_id == group_photo_id,
            TournamentGroupPhotoPrint.print_size == print_size,
        )
    ).first()
    previous_key = existing.storage_key if existing else None
    store.put_jpeg(key, rendered)
    if existing is None:
        existing = TournamentGroupPhotoPrint(
            tournament_id=tournament.id,  # type: ignore[arg-type]
            group_photo_id=group_photo_id,
            print_size=print_size,
            storage_key=key,
            filename=filename,
            byte_size=len(rendered),
            width=width,
            height=height,
            source_width=source_w,
            source_height=source_h,
            low_resolution=low_resolution,
            quantity=quantity,
            settings_json=json.dumps(settings),
        )
    else:
        existing.storage_key = key
        existing.filename = filename
        existing.byte_size = len(rendered)
        existing.width = width
        existing.height = height
        existing.source_width = source_w
        existing.source_height = source_h
        existing.low_resolution = low_resolution
        existing.quantity = quantity
        existing.settings_json = json.dumps(settings)
        existing.created_at = datetime.utcnow()
    session.add(existing)
    if previous_key and previous_key != key and owned_group_print_key(tournament.id, group_photo_id, previous_key):  # type: ignore[arg-type]
        store.delete(previous_key)
    if store.get_bytes(original_key) != original:
        raise HTTPException(status_code=500, detail="Group photograph was not left unchanged")
    return {
        "photo_kind": "group",
        "team_id": None,
        "group_photo_id": group_photo_id,
        "player_names": [label],
        "print_size": print_size,
        "filename": filename,
        "width": width,
        "height": height,
        "source_width": source_w,
        "source_height": source_h,
        "low_resolution": low_resolution,
        "quantity": quantity,
        "byte_size": len(rendered),
    }


@router.post("/tournaments/{tournament_id}/photo-print/exports")
def export_prints(
    tournament_id: int,
    body: PrintRequest,
    user: UserAccount = Depends(require_photo_user),
    session: Session = Depends(get_session),
):
    tournament = _assert_can_photograph(session, user, tournament_id)
    if body.print_size != PRINT_SIZE:
        raise HTTPException(status_code=400, detail="Prints are 4×6 portrait only")
    quantity = max(1, min(int(body.quantity or 1), 20))
    team_ids = list(dict.fromkeys(body.team_ids))
    group_photo_ids = list(dict.fromkeys(body.group_photo_ids))
    if not team_ids and not group_photo_ids:
        raise HTTPException(status_code=400, detail="Select at least one photograph")
    results = []
    try:
        for team_id in team_ids:
            results.append(
                _render_team(session, tournament, team_id, body.print_size, quantity, body.acknowledge_low_resolution)
            )
        for group_photo_id in group_photo_ids:
            results.append(
                _render_group(session, tournament, group_photo_id, body.print_size, quantity, body.acknowledge_low_resolution)
            )
        session.commit()
    except HTTPException:
        session.rollback()
        raise
    except (PhotoRejected, PhotoStorageUnavailable) as exc:
        session.rollback()
        raise _http_photo_error(exc) from exc
    except Exception:
        session.rollback()
        raise
    return {
        "print_size": body.print_size,
        "quantity": quantity,
        "order_placed": False,
        "walgreens": {
            "ordering_url": WALGREENS_ORDER_URL,
            "direct_ordering_available": False,
            "note": WALGREENS_NOTE,
        },
        "files": results,
    }


@router.get("/tournaments/{tournament_id}/photo-print/photos/{team_id}/file")
def download_print_file(
    tournament_id: int,
    team_id: int,
    size: str = "4x6",
    user: UserAccount = Depends(require_photo_user),
    session: Session = Depends(get_session),
):
    _assert_can_photograph(session, user, tournament_id)
    row = session.exec(
        select(TeamPhotoPrint).where(
            TeamPhotoPrint.tournament_id == tournament_id,
            TeamPhotoPrint.team_id == team_id,
            TeamPhotoPrint.print_size == size,
        )
    ).first()
    if not row or not owned_print_key(tournament_id, team_id, row.storage_key):
        raise HTTPException(status_code=404, detail="Print file has not been created")
    try:
        data = get_object_store().get_bytes(row.storage_key)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Print file has not been created") from exc
    except PhotoStorageUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    headers = {"Content-Disposition": f'attachment; filename="{row.filename}"'}
    return Response(content=data, media_type="image/jpeg", headers=headers)


@router.get("/tournaments/{tournament_id}/photo-print/group-photos/{group_photo_id}/file")
def download_group_print_file(
    tournament_id: int,
    group_photo_id: int,
    size: str = "4x6",
    user: UserAccount = Depends(require_photo_user),
    session: Session = Depends(get_session),
):
    _assert_can_photograph(session, user, tournament_id)
    row = session.exec(
        select(TournamentGroupPhotoPrint).where(
            TournamentGroupPhotoPrint.tournament_id == tournament_id,
            TournamentGroupPhotoPrint.group_photo_id == group_photo_id,
            TournamentGroupPhotoPrint.print_size == size,
        )
    ).first()
    if not row or not owned_group_print_key(tournament_id, group_photo_id, row.storage_key):
        raise HTTPException(status_code=404, detail="Print file has not been created")
    try:
        data = get_object_store().get_bytes(row.storage_key)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Print file has not been created") from exc
    except PhotoStorageUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    headers = {"Content-Disposition": f'attachment; filename="{row.filename}"'}
    return Response(content=data, media_type="image/jpeg", headers=headers)


def _package_bytes(
    session: Session,
    tournament: Tournament,
    team_ids: list[int],
    group_photo_ids: list[int],
    print_size: str,
) -> bytes:
    rows = []
    for team_id in team_ids:
        row = session.exec(
            select(TeamPhotoPrint).where(
                TeamPhotoPrint.tournament_id == tournament.id,
                TeamPhotoPrint.team_id == team_id,
                TeamPhotoPrint.print_size == print_size,
            )
        ).first()
        if not row or not owned_print_key(tournament.id, team_id, row.storage_key):  # type: ignore[arg-type]
            raise HTTPException(status_code=404, detail="Create the print files before downloading the package")
        rows.append(row)
    for group_photo_id in group_photo_ids:
        row = session.exec(
            select(TournamentGroupPhotoPrint).where(
                TournamentGroupPhotoPrint.tournament_id == tournament.id,
                TournamentGroupPhotoPrint.group_photo_id == group_photo_id,
                TournamentGroupPhotoPrint.print_size == print_size,
            )
        ).first()
        if not row or not owned_group_print_key(tournament.id, group_photo_id, row.storage_key):  # type: ignore[arg-type]
            raise HTTPException(status_code=404, detail="Create the print files before downloading the package")
        rows.append(row)
    store = get_object_store()
    buffer = io.BytesIO()
    lines = [
        f"Tournament: {tournament.name}",
        f"Print size: {print_size}",
        "Walgreens has not confirmed this order.",
        f"Upload these files at {WALGREENS_ORDER_URL} and choose the pickup store.",
        "",
    ]
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        used_names = set()
        for row in rows:
            data = store.get_bytes(row.storage_key)
            filename = row.filename
            if filename in used_names:
                filename = f"{getattr(row, 'group_photo_id', None) or row.team_id}-{filename}"
            used_names.add(filename)
            archive.writestr(filename, data)
            lines.append(f"{filename}\tquantity {row.quantity}")
        archive.writestr("print-order.txt", "\n".join(lines) + "\n")
    return buffer.getvalue()


@router.post("/tournaments/{tournament_id}/photo-print/package")
def download_print_package(
    tournament_id: int,
    body: PrintRequest,
    user: UserAccount = Depends(require_photo_user),
    session: Session = Depends(get_session),
):
    tournament = _assert_can_photograph(session, user, tournament_id)
    if body.print_size != PRINT_SIZE:
        raise HTTPException(status_code=400, detail="Prints are 4×6 portrait only")
    team_ids = list(dict.fromkeys(body.team_ids))
    group_photo_ids = list(dict.fromkeys(body.group_photo_ids))
    if not team_ids and not group_photo_ids:
        raise HTTPException(status_code=400, detail="Select at least one photograph")
    quantity = max(1, min(int(body.quantity or 1), 20))
    try:
        for team_id in team_ids:
            _render_team(session, tournament, team_id, body.print_size, quantity, body.acknowledge_low_resolution)
        for group_photo_id in group_photo_ids:
            _render_group(session, tournament, group_photo_id, body.print_size, quantity, body.acknowledge_low_resolution)
        session.commit()
        payload = _package_bytes(session, tournament, team_ids, group_photo_ids, body.print_size)
    except HTTPException:
        session.rollback()
        raise
    except (PhotoRejected, PhotoStorageUnavailable) as exc:
        session.rollback()
        raise _http_photo_error(exc) from exc
    stem = print_filename(tournament.name, [], body.print_size).replace(".jpg", "")
    headers = {"Content-Disposition": f'attachment; filename="{stem}-prints.zip"'}
    return Response(content=payload, media_type="application/zip", headers=headers)


@router.get("/photo-print/walgreens")
def walgreens_ordering_status(user: UserAccount = Depends(require_photo_user)):
    return {
        "ordering_url": WALGREENS_ORDER_URL,
        "direct_ordering_available": WALGREENS_DIRECT_ORDERING,
        "order_placed": False,
        "note": WALGREENS_NOTE,
        "requested_by": user.id,
    }
