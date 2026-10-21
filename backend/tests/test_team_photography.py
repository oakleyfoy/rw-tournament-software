"""Team photography search, storage, permissions, and operational isolation."""

from __future__ import annotations

import io
from datetime import date

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlmodel import Session, select

from app.models.event import Event
from app.models.match import Match
from app.models.player import Player
from app.models.schedule_version import ScheduleVersion
from app.models.team import Team
from app.models.team_photo import TeamOfficialPhoto, TeamPhotoCapture
from app.models.team_player import TeamPlayer
from app.models.tournament import Tournament
from app.services.team_photo_search import person_matches
from app.services.team_photo_storage import arm_next_put_failure, get_object_store, official_object_key, reset_memory_store
from app.services.team_photos import relink_photos_for_team_merge


@pytest.fixture(autouse=True)
def team_photo_memory(monkeypatch):
    monkeypatch.setenv("TEAM_PHOTO_OBJECT_STORE", "memory")
    reset_memory_store()
    yield
    reset_memory_store()


def _jpeg(width: int = 20, height: int = 10, color: str = "red", orientation: int | None = None) -> bytes:
    image = Image.new("RGB", (width, height), color)
    buffer = io.BytesIO()
    if orientation is None:
        image.save(buffer, format="JPEG", quality=90)
    else:
        exif = Image.Exif()
        exif[274] = orientation
        image.save(buffer, format="JPEG", quality=90, exif=exif.tobytes())
    return buffer.getvalue()


def _login(client: TestClient, username: str, password: str = "password123") -> dict[str, str]:
    response = client.post("/api/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _bootstrap_admin(client: TestClient) -> dict[str, str]:
    created = client.post("/api/auth/bootstrap-admin", json={"username": "admin", "password": "password123"})
    assert created.status_code == 201, created.text
    return _login(client, "admin")


def _create_user(client: TestClient, admin_headers: dict[str, str], username: str, role: str) -> int:
    response = client.post(
        "/api/auth/users",
        headers=admin_headers,
        json={"username": username, "password": "password123", "role": role},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _tournament(session: Session, name: str) -> tuple[Tournament, Event]:
    tournament = Tournament(
        name=name,
        location="Court",
        timezone="America/New_York",
        start_date=date(2026, 10, 21),
        end_date=date(2026, 10, 23),
    )
    session.add(tournament)
    session.flush()
    event = Event(tournament_id=tournament.id, category="womens", name="Women's 3.5", team_count=4)
    session.add(event)
    session.flush()
    return tournament, event


def _team(
    session: Session,
    tournament: Tournament,
    event: Event,
    name: str,
    seed: int,
    players: list[str],
) -> Team:
    team = Team(event_id=event.id, name=name, display_name=name, seed=seed, source_team_key=f"rw-{seed}-{tournament.id}")
    session.add(team)
    session.flush()
    for index, player_name in enumerate(players, start=1):
        player = Player(tournament_id=tournament.id, full_name=player_name)
        session.add(player)
        session.flush()
        session.add(TeamPlayer(team_id=team.id, player_id=player.id, lineup_slot=index))
    session.flush()
    return team


def _seed_roster(session: Session):
    first, event = _tournament(session, "Autumn Open")
    other, other_event = _tournament(session, "Winter Open")
    jane_amy = _team(session, first, event, "Jane Doe / Amy Lee", 1, ["Jane Doe", "Amy Lee"])
    jane_sue = _team(session, first, event, "Jane Doe / Sue Park", 2, ["Jane Doe", "Sue Park"])
    jane_bob = _team(session, first, event, "Jane Smith / Bob Jones", 3, ["Jane Smith", "Bob Jones"])
    chris = _team(session, first, event, "Chris Alvarez / Pat Nguyen", 4, [])
    later = _team(session, other, other_event, "Jane Doe / Amy Lee", 1, ["Jane Doe", "Amy Lee"])
    version = ScheduleVersion(tournament_id=first.id, version_number=1, status="draft")
    session.add(version)
    session.flush()
    match = Match(
        tournament_id=first.id,
        event_id=event.id,
        schedule_version_id=version.id,
        match_code="WF-R1-01",
        match_type="WF",
        round_number=1,
        sequence_in_round=1,
        duration_minutes=60,
        placeholder_side_a="A",
        placeholder_side_b="B",
        team_a_id=jane_amy.id,
        team_b_id=jane_sue.id,
        status="scheduled",
        runtime_status="SCHEDULED",
    )
    session.add(match)
    session.commit()
    return {
        "tournament_id": first.id,
        "other_tournament_id": other.id,
        "jane_amy": jane_amy.id,
        "jane_sue": jane_sue.id,
        "jane_bob": jane_bob.id,
        "chris": chris.id,
        "later": later.id,
        "match_id": match.id,
    }


def _save(client: TestClient, headers: dict[str, str], tournament_id: int, team_id: int, upload_id: str, payload: bytes):
    return client.post(
        f"/api/photography/tournaments/{tournament_id}/teams/{team_id}/official",
        headers=headers,
        files={"file": ("team.jpg", payload, "image/jpeg")},
        data={"client_upload_id": upload_id},
    )


def test_person_matches_first_last_and_partial_names():
    assert person_matches("Jane", "Jane Doe")
    assert person_matches("Doe", "Jane Doe")
    assert person_matches("jan", "Jane Doe")
    assert person_matches("ane", "Jane Doe")
    assert not person_matches("Robert", "Jane Doe")
    assert not person_matches("   ", "Jane Doe")


def test_search_either_partner_partial_names_and_duplicates(client: TestClient, session: Session):
    admin = _bootstrap_admin(client)
    roster = _seed_roster(session)

    response = client.get(
        f"/api/photography/tournaments/{roster['tournament_id']}/teams/search",
        headers=admin,
        params={"q": "Amy"},
    )
    assert response.status_code == 200
    amy_hits = response.json()
    assert [hit["team_id"] for hit in amy_hits] == [roster["jane_amy"]]
    assert amy_hits[0]["player_names"] == ["Jane Doe", "Amy Lee"]
    assert amy_hits[0]["division"] == "Women's 3.5"
    assert amy_hits[0]["seed"] == 1

    doe = client.get(
        f"/api/photography/tournaments/{roster['tournament_id']}/teams/search",
        headers=admin,
        params={"q": "Doe"},
    ).json()
    assert [hit["team_id"] for hit in doe] == [roster["jane_amy"], roster["jane_sue"]]
    assert doe[0]["player_names"][1] == "Amy Lee"
    assert doe[1]["player_names"][1] == "Sue Park"

    partial = client.get(
        f"/api/photography/tournaments/{roster['tournament_id']}/teams/search",
        headers=admin,
        params={"q": "jan"},
    ).json()
    assert {hit["team_id"] for hit in partial} == {roster["jane_amy"], roster["jane_sue"], roster["jane_bob"]}

    pat = client.get(
        f"/api/photography/tournaments/{roster['tournament_id']}/teams/search",
        headers=admin,
        params={"q": "Pat"},
    ).json()
    assert [hit["team_id"] for hit in pat] == [roster["chris"]]
    assert "Pat Nguyen" in pat[0]["player_names"]

    other = client.get(
        f"/api/photography/tournaments/{roster['other_tournament_id']}/teams/search",
        headers=admin,
        params={"q": "Amy"},
    ).json()
    assert [hit["team_id"] for hit in other] == [roster["later"]]
    assert roster["jane_amy"] not in {hit["team_id"] for hit in other}

    assert client.get(
        f"/api/photography/tournaments/{roster['tournament_id']}/teams/search",
        headers=admin,
        params={"q": "   "},
    ).json() == []


def test_capture_selection_replacement_and_team_isolation(client: TestClient, session: Session):
    admin = _bootstrap_admin(client)
    roster = _seed_roster(session)
    tournament_id = roster["tournament_id"]
    team_id = roster["jane_amy"]
    other_team_id = roster["jane_sue"]
    match_before = session.get(Match, roster["match_id"])
    assert match_before is not None
    before = (
        match_before.status,
        match_before.runtime_status,
        match_before.score_json,
        match_before.winner_team_id,
        match_before.team_a_id,
        match_before.team_b_id,
    )

    failed = _save(client, admin, tournament_id, team_id, "upload-fail-1", b"not-an-image")
    assert failed.status_code == 400
    session.expire_all()
    assert session.exec(select(TeamOfficialPhoto)).all() == []
    assert get_object_store().objects == {}

    first_bytes = _jpeg()
    retried = _save(client, admin, tournament_id, team_id, "upload-fail-1", first_bytes)
    assert retried.status_code == 200, retried.text
    first_content = client.get(f"/api/photography/teams/{team_id}/official/content", headers=admin).content
    duplicate = _save(client, admin, tournament_id, team_id, "upload-fail-1", _jpeg(color="blue"))
    assert duplicate.status_code == 200
    assert client.get(f"/api/photography/teams/{team_id}/official/content", headers=admin).content == first_content
    session.expire_all()
    assert len(session.exec(select(TeamOfficialPhoto)).all()) == 1
    assert session.exec(select(TeamPhotoCapture)).all() == []

    wrong_team = _save(client, admin, tournament_id, other_team_id, "upload-fail-1", _jpeg(color="green"))
    assert wrong_team.status_code == 409
    assert session.exec(select(TeamOfficialPhoto).where(TeamOfficialPhoto.team_id == other_team_id)).first() is None

    oriented_jpeg = _jpeg(width=30, height=10, color="green", orientation=6)
    saved = _save(client, admin, tournament_id, team_id, "upload-best-02", oriented_jpeg)
    assert saved.status_code == 200, saved.text
    session.expire_all()
    assert saved.json()["team_id"] == team_id
    assert saved.json()["tournament_id"] == tournament_id
    photos = session.exec(select(TeamOfficialPhoto)).all()
    assert len(photos) == 1
    assert photos[0].team_id == team_id
    assert photos[0].tournament_id == tournament_id
    assert photos[0].photographer_user_id is not None
    assert photos[0].storage_key == official_object_key(tournament_id, team_id, "upload-best-02")
    assert official_object_key(tournament_id, team_id, "upload-fail-1") not in get_object_store().objects
    content = client.get(f"/api/photography/teams/{team_id}/official/content", headers=admin)
    assert content.status_code == 200
    assert content.headers["content-type"].startswith("image/jpeg")
    with Image.open(io.BytesIO(content.content)) as oriented:
        assert oriented.size == (10, 30)

    missing = client.get(f"/api/photography/teams/{other_team_id}/official/content", headers=admin)
    assert missing.status_code == 404

    summary = client.get(f"/api/photography/tournaments/{tournament_id}/official-photos", headers=admin)
    assert summary.status_code == 200
    assert [row["team_id"] for row in summary.json()] == [team_id]

    current_key = photos[0].storage_key
    arm_next_put_failure()
    blocked = _save(client, admin, tournament_id, team_id, "upload-blocked", _jpeg(color="blue"))
    assert blocked.status_code == 503
    session.expire_all()
    unchanged = session.exec(select(TeamOfficialPhoto)).one()
    assert unchanged.storage_key == current_key
    assert unchanged.last_client_upload_id == "upload-best-02"
    assert get_object_store().objects.keys() == {current_key}

    replaced = _save(client, admin, tournament_id, team_id, "upload-replace", _jpeg(color="blue"))
    assert replaced.status_code == 200, replaced.text
    retried_official = _save(client, admin, tournament_id, team_id, "upload-replace", _jpeg(color="yellow"))
    assert retried_official.status_code == 200
    session.expire_all()
    photos = session.exec(select(TeamOfficialPhoto)).all()
    assert len(photos) == 1
    assert photos[0].team_id == team_id
    assert photos[0].last_client_upload_id == "upload-replace"
    assert photos[0].storage_key == official_object_key(tournament_id, team_id, "upload-replace")
    assert current_key not in get_object_store().objects
    assert list(get_object_store().objects) == [photos[0].storage_key]
    session.expire_all()
    assert session.get(Team, team_id).name == "Jane Doe / Amy Lee"

    session.refresh(match_before)
    after = (
        match_before.status,
        match_before.runtime_status,
        match_before.score_json,
        match_before.winner_team_id,
        match_before.team_a_id,
        match_before.team_b_id,
    )
    assert after == before

    later_content = client.get(f"/api/photography/teams/{roster['later']}/official/content", headers=admin)
    assert later_content.status_code == 404


def test_photographer_permissions_and_admin_replacement(client: TestClient, session: Session):
    admin = _bootstrap_admin(client)
    roster = _seed_roster(session)
    photographer_id = _create_user(client, admin, "photographer1", "photographer")
    director_id = _create_user(client, admin, "director1", "director")
    assert director_id > 0
    assigned = client.put(
        f"/api/auth/users/{photographer_id}/photography-tournaments",
        headers=admin,
        json={"tournament_ids": [roster["tournament_id"]]},
    )
    assert assigned.status_code == 200
    assert assigned.json()["tournament_ids"] == [roster["tournament_id"]]

    photographer = _login(client, "photographer1")
    director = _login(client, "director1")

    visible = client.get("/api/photography/tournaments", headers=photographer)
    assert visible.status_code == 200
    assert [row["id"] for row in visible.json()] == [roster["tournament_id"]]

    allowed = client.get(
        f"/api/photography/tournaments/{roster['tournament_id']}/teams/search",
        headers=photographer,
        params={"q": "Amy"},
    )
    assert allowed.status_code == 200
    denied_tournament = client.get(
        f"/api/photography/tournaments/{roster['other_tournament_id']}/teams/search",
        headers=photographer,
        params={"q": "Amy"},
    )
    assert denied_tournament.status_code == 403

    assert client.get("/api/tournaments", headers=photographer).status_code == 403
    assert client.get(f"/api/desk/tournaments/{roster['tournament_id']}/snapshot", headers=photographer).status_code == 403
    assert client.patch(
        f"/api/desk/tournaments/{roster['tournament_id']}/matches/{roster['match_id']}/finalize",
        headers=photographer,
        json={"version_id": 1, "winner_team_id": roster["jane_amy"], "score": "8-4"},
    ).status_code == 403
    assert client.patch(
        f"/api/desk/tournaments/{roster['tournament_id']}/matches/{roster['match_id']}/checkin/team",
        headers=photographer,
        json={"version_id": 1, "side": "A"},
    ).status_code == 403
    assert client.get(f"/api/tournaments/{roster['tournament_id']}/display-board", headers=photographer).status_code == 403
    assert client.get("/api/auth/users", headers=photographer).status_code == 403

    assert client.get("/api/tournaments", headers=director).status_code == 200
    director_search = client.get(
        f"/api/photography/tournaments/{roster['other_tournament_id']}/teams/search",
        headers=director,
        params={"q": "Amy"},
    )
    assert director_search.status_code == 200

    saved = _save(client, photographer, roster["tournament_id"], roster["jane_amy"], "photo-auth-01", _jpeg())
    assert saved.status_code == 200, saved.text
    replaced = _save(client, admin, roster["tournament_id"], roster["jane_amy"], "photo-auth-02", _jpeg(color="blue"))
    assert replaced.status_code == 200, replaced.text
    session.expire_all()
    photo = session.exec(select(TeamOfficialPhoto)).one()
    assert photo.team_id == roster["jane_amy"]
    assert photo.storage_key == official_object_key(roster["tournament_id"], roster["jane_amy"], "photo-auth-02")

    outside = _save(
        client,
        photographer,
        roster["other_tournament_id"],
        roster["later"],
        "photo-auth-03",
        _jpeg(),
    )
    assert outside.status_code == 403
    assert session.exec(select(TeamOfficialPhoto).where(TeamOfficialPhoto.team_id == roster["later"])).first() is None


def test_merge_keeps_canonical_team_photo(session: Session):
    tournament, event = _tournament(session, "Merge Open")
    canonical = _team(session, tournament, event, "Jane Doe / Amy Lee", 1, ["Jane Doe", "Amy Lee"])
    duplicate = Team(event_id=event.id, name="Jane Doe / Amy Lee duplicate", seed=9)
    session.add(duplicate)
    session.commit()
    session.refresh(duplicate)
    payload = _jpeg(color="blue")
    duplicate_key = official_object_key(tournament.id, duplicate.id, "merge-source-photo")
    get_object_store().put_jpeg(duplicate_key, payload)
    session.add(
        TeamOfficialPhoto(
            team_id=duplicate.id,
            tournament_id=tournament.id,
            storage_key=duplicate_key,
            byte_size=len(payload),
        )
    )
    session.commit()
    relink_photos_for_team_merge(session, canonical.id, [duplicate.id])
    session.commit()
    photo = session.exec(select(TeamOfficialPhoto)).one()
    assert photo.team_id == canonical.id
    assert photo.storage_key == official_object_key(tournament.id, canonical.id, f"merge-{duplicate.id}-{photo.id}")
    assert get_object_store().get_bytes(photo.storage_key) == payload
    assert duplicate_key not in get_object_store().objects
    session.delete(duplicate)
    session.commit()
    assert session.get(Team, canonical.id) is not None


def test_unconfigured_r2_does_not_store_a_local_photograph(client: TestClient, session: Session, monkeypatch):
    monkeypatch.setenv("TEAM_PHOTO_OBJECT_STORE", "r2")
    for name in ("TEAM_PHOTO_R2_BUCKET", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_ENDPOINT", "R2_BUCKET"):
        monkeypatch.delenv(name, raising=False)
    admin = _bootstrap_admin(client)
    roster = _seed_roster(session)
    response = _save(client, admin, roster["tournament_id"], roster["jane_amy"], "upload-nor2-01", _jpeg())
    assert response.status_code == 503
    session.expire_all()
    assert session.exec(select(TeamOfficialPhoto)).all() == []


def test_heic_upload_is_stored_as_jpeg(client: TestClient, session: Session):
    from pillow_heif import register_heif_opener

    register_heif_opener()
    image = Image.new("RGB", (24, 12), "green")
    buffer = io.BytesIO()
    image.save(buffer, format="HEIF")
    admin = _bootstrap_admin(client)
    roster = _seed_roster(session)
    response = _save(client, admin, roster["tournament_id"], roster["jane_amy"], "upload-heic-01", buffer.getvalue())
    assert response.status_code == 200, response.text
    content = client.get(
        f"/api/photography/teams/{roster['jane_amy']}/official/content",
        headers=admin,
    )
    assert content.status_code == 200
    assert content.headers["content-type"].startswith("image/jpeg")
    with Image.open(io.BytesIO(content.content)) as saved:
        assert saved.format == "JPEG"
        assert saved.size == (24, 12)


def test_oversized_upload_is_rejected(client: TestClient, session: Session):
    admin = _bootstrap_admin(client)
    roster = _seed_roster(session)
    huge = b"x" * (12 * 1024 * 1024 + 1)
    response = _save(client, admin, roster["tournament_id"], roster["jane_amy"], "upload-huge-01", huge)
    assert response.status_code == 413
    assert session.exec(select(TeamOfficialPhoto)).all() == []
    assert get_object_store().objects == {}
