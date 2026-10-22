"""Watermark settings and print files stay off the official photograph."""

from __future__ import annotations

import io
import zipfile
from datetime import date

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlmodel import Session, select

from app.models.event import Event
from app.models.player import Player
from app.models.team import Team
from app.models.team_photo import TeamOfficialPhoto
from app.models.team_photo_print import TeamPhotoPrint
from app.models.team_player import TeamPlayer
from app.models.tournament import Tournament
from app.services.team_photo_storage import PhotoRejected, get_object_store, reset_memory_store
from app.services.team_photo_watermark import print_filename, render_print_jpeg, source_needs_upscale
from tests.test_team_photography import _bootstrap_admin, _create_user, _jpeg, _login


@pytest.fixture(autouse=True)
def team_photo_memory(monkeypatch):
    monkeypatch.setenv("TEAM_PHOTO_OBJECT_STORE", "memory")
    reset_memory_store()
    yield
    reset_memory_store()


def _roster(session: Session) -> dict:
    tournament = Tournament(
        name="Scottsdale 2026",
        location="Court",
        timezone="America/Phoenix",
        start_date=date(2026, 3, 1),
        end_date=date(2026, 3, 2),
    )
    other = Tournament(
        name="Other Open",
        location="Court",
        timezone="America/Phoenix",
        start_date=date(2026, 4, 1),
        end_date=date(2026, 4, 2),
    )
    session.add(tournament)
    session.add(other)
    session.flush()
    event = Event(tournament_id=tournament.id, category="womens", name="Women's 4.0", team_count=2)
    session.add(event)
    session.flush()
    team = Team(event_id=event.id, name="Haley / Stacey", display_name="Haley / Stacey", seed=1, source_team_key="rw-haley")
    session.add(team)
    session.flush()
    for slot, name in enumerate(["Haley", "Stacey"], start=1):
        player = Player(tournament_id=tournament.id, full_name=name)
        session.add(player)
        session.flush()
        session.add(TeamPlayer(team_id=team.id, player_id=player.id, lineup_slot=slot))
    session.commit()
    return {"tournament_id": tournament.id, "other_id": other.id, "team_id": team.id}


def _save_photo(client: TestClient, headers: dict, tournament_id: int, team_id: int) -> None:
    saved = client.post(
        f"/api/photography/tournaments/{tournament_id}/teams/{team_id}/official",
        headers=headers,
        files={"file": ("team.jpg", _jpeg(400, 600, "blue"), "image/jpeg")},
        data={"client_upload_id": "printready01"},
    )
    assert saved.status_code == 200, saved.text


def test_print_filename_uses_tournament_and_player_names():
    assert print_filename("Scottsdale 2026", ["Haley", "Stacey"], "4x6") == "Scottsdale-2026-Haley-Stacey-4x6.jpg"


def test_high_resolution_source_is_not_upscaled():
    source = Image.new("RGB", (2400, 3600), "white")
    raw = io.BytesIO()
    source.save(raw, format="JPEG", quality=90)
    data = raw.getvalue()
    settings = {
        "content_mode": "text_only",
        "event_text": "Scottsdale 2026",
        "custom_text": "",
        "font_family": "Arial",
        "font_style": "bold",
        "color": "#111111",
        "size_percent": 20,
        "logo_scale": 1,
        "spacing": 4,
        "opacity": 100,
        "position": "top-center",
        "offset_x": 0,
        "offset_y": 0,
        "shadow": False,
        "visible": True,
        "crop_mode": "fit",
        "crop_x": 0.5,
        "crop_y": 0.5,
        "show_margins": False,
    }
    assert source_needs_upscale(2400, 3600, 1200, 1800, "fit") is False
    rendered, width, height, source_w, source_h, low = render_print_jpeg(data, settings, "4x6", allow_upscale=False)
    assert (width, height, source_w, source_h, low) == (1200, 1800, 2400, 3600, False)
    assert rendered != data
    with Image.open(io.BytesIO(rendered)) as image:
        assert image.size == (1200, 1800)


def test_low_resolution_export_requires_warning_and_leaves_the_original(client: TestClient, session: Session):
    admin = _bootstrap_admin(client)
    roster = _roster(session)
    _save_photo(client, admin, roster["tournament_id"], roster["team_id"])
    photo = session.exec(select(TeamOfficialPhoto).where(TeamOfficialPhoto.team_id == roster["team_id"])).one()
    original = get_object_store().get_bytes(photo.storage_key)
    original_key = photo.storage_key

    missing = client.get(f"/api/photography/tournaments/{roster['tournament_id']}/photo-print")
    assert missing.status_code == 401

    workspace = client.get(
        f"/api/photography/tournaments/{roster['tournament_id']}/photo-print",
        headers=admin,
    )
    assert workspace.status_code == 200, workspace.text
    body = workspace.json()
    assert body["tournament_name"] == "Scottsdale 2026"
    assert body["photos"][0]["player_names"] == ["Haley", "Stacey"]
    assert body["default_settings"]["event_text"] == "Scottsdale 2026"
    assert body["walgreens"]["direct_ordering_available"] is False
    assert "4x6" in body["photos"][0]["low_resolution_sizes"]

    saved_default = client.put(
        f"/api/photography/tournaments/{roster['tournament_id']}/photo-print/default",
        headers=admin,
        json={"settings": {**body["default_settings"], "position": "bottom-right"}},
    )
    assert saved_default.status_code == 200
    override = client.put(
        f"/api/photography/tournaments/{roster['tournament_id']}/photo-print/photos/{roster['team_id']}",
        headers=admin,
        json={"settings": {**body["default_settings"], "position": "top-left", "color": "#1565c0"}},
    )
    assert override.status_code == 200
    applied = client.post(
        f"/api/photography/tournaments/{roster['tournament_id']}/photo-print/apply-all",
        headers=admin,
        json={"settings": {**body["default_settings"], "position": "bottom-center"}},
    )
    assert applied.status_code == 200
    assert applied.json()["photos"][0]["has_override"] is False
    assert applied.json()["photos"][0]["settings"]["position"] == "bottom-center"

    blocked = client.post(
        f"/api/photography/tournaments/{roster['tournament_id']}/photo-print/exports",
        headers=admin,
        json={"team_ids": [roster["team_id"]], "print_size": "4x6", "quantity": 1, "acknowledge_low_resolution": False},
    )
    assert blocked.status_code == 409
    assert "1200" in blocked.json()["detail"]

    exported = client.post(
        f"/api/photography/tournaments/{roster['tournament_id']}/photo-print/exports",
        headers=admin,
        json={"team_ids": [roster["team_id"]], "print_size": "4x6", "quantity": 2, "acknowledge_low_resolution": True},
    )
    assert exported.status_code == 200, exported.text
    created = exported.json()["files"][0]
    assert created["filename"] == "Scottsdale-2026-Haley-Stacey-4x6.jpg"
    assert created["low_resolution"] is True
    assert exported.json()["order_placed"] is False
    session.expire_all()
    photo_after = session.get(TeamOfficialPhoto, photo.id)
    assert photo_after.storage_key == original_key
    assert get_object_store().get_bytes(original_key) == original
    print_row = session.exec(select(TeamPhotoPrint).where(TeamPhotoPrint.team_id == roster["team_id"])).one()
    assert print_row.storage_key.startswith(f"team-photo-prints/{roster['tournament_id']}/{roster['team_id']}/")
    assert not print_row.storage_key.startswith("team-photos/")

    other = client.post(
        f"/api/photography/tournaments/{roster['other_id']}/photo-print/exports",
        headers=admin,
        json={"team_ids": [roster["team_id"]], "print_size": "4x6", "acknowledge_low_resolution": True},
    )
    assert other.status_code == 404

    package = client.post(
        f"/api/photography/tournaments/{roster['tournament_id']}/photo-print/package",
        headers=admin,
        json={"team_ids": [roster["team_id"]], "print_size": "4x6", "quantity": 2, "acknowledge_low_resolution": True},
    )
    assert package.status_code == 200
    assert package.headers["content-type"] == "application/zip"
    with zipfile.ZipFile(io.BytesIO(package.content)) as archive:
        names = archive.namelist()
        assert "Scottsdale-2026-Haley-Stacey-4x6.jpg" in names
        manifest = archive.read("print-order.txt").decode()
    assert "has not confirmed" in manifest
    assert "photo.walgreens.com/store/prints" in manifest
    session.expire_all()
    assert session.get(TeamOfficialPhoto, photo.id).storage_key == original_key
    assert get_object_store().get_bytes(original_key) == original


def test_photographer_cannot_print_another_tournament(client: TestClient, session: Session):
    admin = _bootstrap_admin(client)
    roster = _roster(session)
    photographer_id = _create_user(client, admin, "printer", "photographer")
    assigned = client.put(
        f"/api/auth/users/{photographer_id}/photography-tournaments",
        headers=admin,
        json={"tournament_ids": [roster["tournament_id"]]},
    )
    assert assigned.status_code == 200
    photographer = _login(client, "printer")
    allowed = client.get(f"/api/photography/tournaments/{roster['tournament_id']}/photo-print", headers=photographer)
    denied = client.get(f"/api/photography/tournaments/{roster['other_id']}/photo-print", headers=photographer)
    assert allowed.status_code == 200
    assert denied.status_code == 403
    status = client.get("/api/photography/photo-print/walgreens", headers=photographer)
    assert status.status_code == 200
    assert status.json()["direct_ordering_available"] is False
    assert status.json()["order_placed"] is False


def _print_settings(**overrides):
    settings = {
        "content_mode": "logo_only",
        "event_text": "Event",
        "custom_text": "",
        "font_family": "Arial",
        "font_style": "bold",
        "color": "#ffffff",
        "size_percent": 20,
        "logo_scale": 1,
        "spacing": 4,
        "opacity": 90,
        "position": "top-center",
        "offset_x": 0,
        "offset_y": 0,
        "shadow": True,
        "visible": True,
        "crop_mode": "fit",
        "crop_x": 0.5,
        "crop_y": 0.5,
        "show_margins": False,
    }
    settings.update(overrides)
    return settings


def test_only_portrait_4x6_is_accepted_and_low_resolution_is_blocked():
    try:
        render_print_jpeg(_jpeg(20, 30), _print_settings(), "8x10", allow_upscale=False)
    except PhotoRejected as exc:
        assert "4×6 portrait" in str(exc)
    else:
        raise AssertionError("a non-portrait size was accepted")
    try:
        render_print_jpeg(_jpeg(20, 30), _print_settings(), "4x6", allow_upscale=False)
    except PhotoRejected as exc:
        assert exc.status_code == 409
    else:
        raise AssertionError("low-resolution print was created without a warning")


def test_landscape_source_still_prints_as_portrait_and_warns_when_cropped():
    from app.services.team_photo_watermark import crop_cuts_photo

    wide = Image.new("RGB", (3000, 2000), "navy")
    raw = io.BytesIO()
    wide.save(raw, format="JPEG", quality=90)
    rendered, width, height, source_w, source_h, low = render_print_jpeg(
        raw.getvalue(),
        _print_settings(crop_mode="fit", content_mode="text_only", event_text="Scottsdale 2026", color="#111111"),
        "4x6",
        allow_upscale=False,
    )
    assert (width, height, source_w, source_h, low) == (1200, 1800, 3000, 2000, False)
    with Image.open(io.BytesIO(rendered)) as image:
        assert image.size == (1200, 1800)
    assert crop_cuts_photo(3000, 2000, "fill") is True
    assert crop_cuts_photo(1200, 1800, "fill") is False
    assert crop_cuts_photo(3000, 2000, "fit") is False


def test_default_watermark_uses_the_rw_emblem():
    source = Image.new("RGB", (2000, 3000), (0, 0, 0))
    raw = io.BytesIO()
    source.save(raw, format="JPEG", quality=95)
    rendered, width, height, _source_w, _source_h, low = render_print_jpeg(
        raw.getvalue(),
        _print_settings(content_mode="logo_only", color="#c62828", position="top-center", shadow=False, opacity=100),
        "4x6",
        allow_upscale=False,
    )
    assert (width, height, low) == (1200, 1800, False)
    with Image.open(io.BytesIO(rendered)) as image:
        margin = int(min(image.size) * 0.04)
        red = 0
        for y in range(margin, margin + 160):
            for x in range(width // 2 - 180, width // 2 + 180, 3):
                pixel = image.getpixel((x, y))
                if pixel[0] > 120 and pixel[0] > pixel[1] + 40 and pixel[0] > pixel[2] + 40:
                    red += 1
        assert red > 40


def test_watermark_stays_inside_the_printable_margin():
    source = Image.new("RGB", (2000, 3000), (0, 0, 0))
    raw = io.BytesIO()
    source.save(raw, format="JPEG", quality=95)
    rendered, width, height, _source_w, _source_h, low = render_print_jpeg(
        raw.getvalue(),
        _print_settings(
            content_mode="text_only",
            event_text="Scottsdale 2026",
            color="#ffffff",
            size_percent=36,
            position="top-center",
            shadow=False,
        ),
        "4x6",
        allow_upscale=False,
    )
    assert (width, height, low) == (1200, 1800, False)
    with Image.open(io.BytesIO(rendered)) as image:
        margin = int(min(image.size) * 0.04)
        assert image.getpixel((1, 1))[0] < 45
        assert image.getpixel((width - 2, height - 2))[0] < 45
        assert image.getpixel((width // 2, margin + 8))[0] < 45
        bright = max(image.getpixel((x, margin + 40))[0] for x in range(margin, width - margin, 8))
        assert bright > 80


def test_every_watermark_font_loads_its_own_face():
    from PIL import ImageDraw

    from app.services.team_photo_watermark import FONT_FAMILIES, _load_font

    image = Image.new("RGB", (800, 120), "white")
    draw = ImageDraw.Draw(image)
    widths = set()
    for family in FONT_FAMILIES:
        font = _load_font(family, "bold", 64)
        box = draw.textbbox((0, 0), "Kiawah", font=font)
        width = box[2] - box[0]
        assert width > 40
        widths.add(width)
    assert len(FONT_FAMILIES) == 16
    assert len(widths) >= 10
