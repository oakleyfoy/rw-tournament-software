"""Official team photograph lifecycle.

These operations update photograph metadata and the R2 object only. They do
not read or write match status, schedule assignments, check-in, or scores.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from sqlmodel import Session, select

from app.models.team_photo import TeamOfficialPhoto, TeamPhotoCapture
from app.services.team_photo_storage import (
    PhotoRejected,
    PhotoStorageUnavailable,
    get_object_store,
    official_object_key,
)


@dataclass
class OfficialSaveResult:
    photo: TeamOfficialPhoto
    delete_on_failure: Optional[str]
    delete_after_commit: Optional[str]


def _owned_photo_key(tournament_id: int, team_id: int, storage_key: str) -> bool:
    prefix = f"team-photos/{int(tournament_id)}/{int(team_id)}/"
    if not storage_key.startswith(prefix) or ".." in storage_key:
        return False
    remainder = storage_key[len(prefix):]
    return bool(remainder) and "/" not in remainder and remainder.endswith(".jpg")


def delete_official_photo(session: Session, *, tournament_id: int, team_id: int) -> None:
    """Remove one team's official photograph and its stored object.

    A missing photograph is treated as already deleted. Storage is removed
    only after every key is confirmed to belong to this team. If storage
    deletion fails, the database row stays in place.
    """
    photo = session.exec(select(TeamOfficialPhoto).where(TeamOfficialPhoto.team_id == team_id)).first()
    if photo is None:
        return
    if photo.tournament_id != tournament_id:
        raise PhotoRejected("Team not found", status_code=404)
    captures = session.exec(
        select(TeamPhotoCapture).where(
            TeamPhotoCapture.team_id == team_id,
            TeamPhotoCapture.tournament_id == tournament_id,
        )
    ).all()
    keys: list[str] = []
    for capture in captures:
        if capture.storage_key and capture.storage_key not in keys:
            keys.append(capture.storage_key)
    if photo.storage_key not in keys:
        keys.append(photo.storage_key)
    if any(not _owned_photo_key(tournament_id, team_id, key) for key in keys):
        raise PhotoRejected("Official photograph could not be deleted", status_code=409)
    store = get_object_store()
    for key in keys:
        store.delete(key)
    session.delete(photo)
    for capture in captures:
        session.delete(capture)
    session.flush()


def _delete_key(storage_key: Optional[str]) -> None:
    if not storage_key:
        return
    try:
        get_object_store().delete(storage_key)
    except PhotoStorageUnavailable:
        return


def relink_photos_for_team_merge(session: Session, canonical_team_id: int, duplicate_team_ids: list[int]) -> None:
    """Keep the canonical team's photo when duplicate team rows are merged."""
    if not duplicate_team_ids:
        return
    canonical = session.exec(
        select(TeamOfficialPhoto).where(TeamOfficialPhoto.team_id == canonical_team_id)
    ).first()
    duplicates = session.exec(
        select(TeamOfficialPhoto).where(TeamOfficialPhoto.team_id.in_(duplicate_team_ids))  # type: ignore[attr-defined]
    ).all()
    store = get_object_store()
    for photo in duplicates:
        if canonical is None:
            old_key = photo.storage_key
            try:
                data = store.get_bytes(old_key)
            except FileNotFoundError:
                photo.team_id = canonical_team_id
                photo.updated_at = datetime.utcnow()
                session.add(photo)
                canonical = photo
                continue
            new_key = official_object_key(
                photo.tournament_id,
                canonical_team_id,
                f"merge-{photo.team_id}-{photo.id or 0}",
            )
            store.put_jpeg(new_key, data)
            if store.head_size(new_key) != len(data):
                store.delete(new_key)
                raise PhotoStorageUnavailable("Uploaded photograph could not be verified")
            photo.team_id = canonical_team_id
            photo.storage_key = new_key
            photo.updated_at = datetime.utcnow()
            session.add(photo)
            canonical = photo
            if old_key != new_key:
                store.delete(old_key)
        else:
            _delete_key(photo.storage_key)
            session.delete(photo)

    captures = session.exec(
        select(TeamPhotoCapture).where(TeamPhotoCapture.team_id.in_(duplicate_team_ids))  # type: ignore[attr-defined]
    ).all()
    for capture in captures:
        _delete_key(capture.storage_key)
        session.delete(capture)


def save_official_photo(
    session: Session,
    *,
    tournament_id: int,
    team_id: int,
    client_upload_id: str,
    image_bytes: bytes,
    photographer_user_id: Optional[int],
) -> OfficialSaveResult:
    """Upload and verify the JPEG before changing the official photo pointer."""
    client_upload_id = client_upload_id.strip()
    other = session.exec(
        select(TeamOfficialPhoto).where(TeamOfficialPhoto.last_client_upload_id == client_upload_id)
    ).first()
    existing = session.exec(select(TeamOfficialPhoto).where(TeamOfficialPhoto.team_id == team_id)).first()
    if other and other.team_id != team_id:
        raise PhotoRejected("This upload already belongs to another team", status_code=409)
    if existing and existing.tournament_id != tournament_id:
        raise PhotoRejected("Team not found", status_code=404)
    if existing and existing.last_client_upload_id == client_upload_id:
        return OfficialSaveResult(photo=existing, delete_on_failure=None, delete_after_commit=None)

    new_key = official_object_key(tournament_id, team_id, client_upload_id)
    previous_key = existing.storage_key if existing else None
    store = get_object_store()
    store.put_jpeg(new_key, image_bytes)
    if store.head_size(new_key) != len(image_bytes):
        if previous_key != new_key:
            store.delete(new_key)
        raise PhotoStorageUnavailable("Uploaded photograph could not be verified")

    now = datetime.utcnow()
    if existing is None:
        existing = TeamOfficialPhoto(
            team_id=team_id,
            tournament_id=tournament_id,
            storage_key=new_key,
            content_type="image/jpeg",
            byte_size=len(image_bytes),
            photographer_user_id=photographer_user_id,
            last_client_upload_id=client_upload_id,
            captured_at=now,
            updated_at=now,
        )
    else:
        existing.tournament_id = tournament_id
        existing.storage_key = new_key
        existing.content_type = "image/jpeg"
        existing.byte_size = len(image_bytes)
        existing.photographer_user_id = photographer_user_id
        existing.last_client_upload_id = client_upload_id
        existing.captured_at = now
        existing.updated_at = now
    session.add(existing)
    try:
        session.flush()
    except Exception:
        if previous_key != new_key:
            store.delete(new_key)
        raise
    return OfficialSaveResult(
        photo=existing,
        delete_on_failure=None if previous_key == new_key else new_key,
        delete_after_commit=previous_key if previous_key and previous_key != new_key else None,
    )
