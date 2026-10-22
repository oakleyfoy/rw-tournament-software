"""Group photographs stay off teams, public draws, and photo SMS."""

from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlmodel import Session, select

from app.models.group_photo import TournamentGroupPhoto
from app.models.sms_log import SmsLog
from app.models.team_photo import TeamOfficialPhoto
from app.models.team_photo_sms import TeamPhotoSmsNotice
from app.models.tournament_sms_settings import TournamentSmsSettings
from app.services.team_photo_storage import get_object_store, reset_memory_store
from tests.test_team_photo_print import _roster, _save_photo
from tests.test_team_photography import _bootstrap_admin, _jpeg


@pytest.fixture(autouse=True)
def team_photo_memory(monkeypatch):
    monkeypatch.setenv("TEAM_PHOTO_OBJECT_STORE", "memory")
    reset_memory_store()
    yield
    reset_memory_store()


def _save_group(client: TestClient, headers: dict, tournament_id: int, upload_id: str, color: str = "green") -> dict:
    saved = client.post(
        f"/api/photography/tournaments/{tournament_id}/group-photos",
        headers=headers,
        files={"file": ("group.jpg", _jpeg(400, 600, color), "image/jpeg")},
        data={"client_upload_id": upload_id},
    )
    assert saved.status_code == 200, saved.text
    return saved.json()


def test_group_photos_print_without_a_team_draw_or_text(client: TestClient, session: Session, monkeypatch):
    monkeypatch.setenv("TEAM_PHOTO_AUTO_SMS_ENABLED", "false")
    admin = _bootstrap_admin(client)
    roster = _roster(session)
    _save_photo(client, admin, roster["tournament_id"], roster["team_id"])
    monkeypatch.setenv("TEAM_PHOTO_AUTO_SMS_ENABLED", "true")
    session.add(TournamentSmsSettings(tournament_id=roster["tournament_id"], texts_enabled=True, delivery_mode="live"))
    session.commit()
    official = session.exec(select(TeamOfficialPhoto).where(TeamOfficialPhoto.team_id == roster["team_id"])).one()
    official_before = get_object_store().get_bytes(official.storage_key)

    first = _save_group(client, admin, roster["tournament_id"], "groupphoto1")
    second = _save_group(client, admin, roster["tournament_id"], "groupphoto2", color="blue")
    again = _save_group(client, admin, roster["tournament_id"], "groupphoto1")
    assert again["id"] == first["id"]
    assert first["label"] == "Group Photo 1"
    assert second["label"] == "Group Photo 2"
    assert session.exec(select(TournamentGroupPhoto)).all().__len__() == 2
    assert official.storage_key == session.get(TeamOfficialPhoto, official.id).storage_key
    assert get_object_store().get_bytes(official.storage_key) == official_before
    assert session.exec(select(TeamPhotoSmsNotice)).all() == []
    assert session.exec(select(SmsLog)).all() == []

    listed = client.get(f"/api/photography/tournaments/{roster['tournament_id']}/official-photos", headers=admin)
    assert listed.status_code == 200
    assert [row["team_id"] for row in listed.json()] == [roster["team_id"]]
    public = client.get(f"/api/public/tournaments/{roster['tournament_id']}/teams/{roster['team_id']}/photo")
    assert public.status_code == 404

    workspace = client.get(f"/api/photography/tournaments/{roster['tournament_id']}/photo-print", headers=admin)
    assert workspace.status_code == 200, workspace.text
    groups = [photo for photo in workspace.json()["photos"] if photo["photo_kind"] == "group"]
    teams = [photo for photo in workspace.json()["photos"] if photo["photo_kind"] == "team"]
    assert [photo["player_names"] for photo in groups] == [["Group Photo 1"], ["Group Photo 2"]]
    assert teams[0]["player_names"] == ["Haley", "Stacey"]
    assert workspace.json()["totals"]["group_photos"] == 2
    assert all(photo["team_id"] is None for photo in groups)

    exported = client.post(
        f"/api/photography/tournaments/{roster['tournament_id']}/photo-print/exports",
        headers=admin,
        json={
            "team_ids": [roster["team_id"]],
            "group_photo_ids": [first["id"]],
            "print_size": "4x6",
            "quantity": 1,
            "acknowledge_low_resolution": True,
        },
    )
    assert exported.status_code == 200, exported.text
    files = exported.json()["files"]
    assert files[0]["width"] == 1200 and files[0]["height"] == 1800
    assert files[1]["width"] == 1200 and files[1]["height"] == 1800
    assert files[1]["player_names"] == ["Group Photo 1"]
    assert "Group-Photo-1" in files[1]["filename"]
    group = session.get(TournamentGroupPhoto, first["id"])
    assert get_object_store().get_bytes(group.storage_key) == _jpeg(400, 600, "green")
    team_file = client.get(
        f"/api/photography/tournaments/{roster['tournament_id']}/photo-print/photos/{roster['team_id']}/file?size=4x6",
        headers=admin,
    )
    group_file = client.get(
        f"/api/photography/tournaments/{roster['tournament_id']}/photo-print/group-photos/{first['id']}/file?size=4x6",
        headers=admin,
    )
    assert team_file.status_code == 200 and group_file.status_code == 200
    with Image.open(io.BytesIO(group_file.content)) as image:
        assert image.size == (1200, 1800)
    assert group_file.content != _jpeg(400, 600, "green")
    assert session.get(TeamOfficialPhoto, official.id).storage_key == official.storage_key

    removed = client.delete(
        f"/api/photography/tournaments/{roster['tournament_id']}/group-photos/{first['id']}",
        headers=admin,
    )
    assert removed.status_code == 200, removed.text
    session.expire_all()
    assert session.get(TournamentGroupPhoto, first["id"]) is None
    assert session.get(TournamentGroupPhoto, second["id"]) is not None
    assert get_object_store().get_bytes(official.storage_key) == official_before
    after = client.get(f"/api/photography/tournaments/{roster['tournament_id']}/photo-print", headers=admin)
    labels = [photo["player_names"] for photo in after.json()["photos"] if photo["photo_kind"] == "group"]
    assert labels == [["Group Photo 1"]]
    assert after.json()["photos"][0]["photo_kind"] == "team"
