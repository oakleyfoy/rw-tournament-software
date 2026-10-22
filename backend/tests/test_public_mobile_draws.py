"""Public mobile draw directory and thumbnail access."""

from datetime import date
from io import BytesIO

from PIL import Image
from sqlmodel import Session

from app.models.event import Event
from app.models.match import Match
from app.models.player import Player
from app.models.schedule_version import ScheduleVersion
from app.models.team import Team
from app.models.team_photo import TeamOfficialPhoto
from app.models.team_player import TeamPlayer
from app.models.tournament import Tournament
from app.services.team_photo_storage import get_object_store, official_object_key, reset_memory_store


def _jpeg() -> bytes:
    image = Image.new("RGB", (24, 24), (20, 40, 80))
    out = BytesIO()
    image.save(out, format="JPEG")
    return out.getvalue()


def _published(session: Session):
    tournament = Tournament(
        name="Mobile Draws",
        location="Beach",
        timezone="America/New_York",
        start_date=date(2026, 6, 5),
        end_date=date(2026, 6, 7),
    )
    session.add(tournament)
    session.flush()
    version = ScheduleVersion(tournament_id=tournament.id, version_number=1, status="final")
    session.add(version)
    session.flush()
    event = Event(tournament_id=tournament.id, category="mixed", name="Mixed A", team_count=2)
    session.add(event)
    session.flush()
    team = Team(event_id=event.id, name="Ada Smith / Bea Jones", seed=1)
    other = Team(event_id=event.id, name="Cara Lee / Dee Chen", seed=2)
    session.add(team)
    session.add(other)
    session.flush()
    player = Player(tournament_id=tournament.id, full_name="Bea Jones", phone_e164="+15555550100", email="bea@example.com")
    session.add(player)
    session.flush()
    session.add(TeamPlayer(team_id=team.id, player_id=player.id, lineup_slot=2))
    session.add(Match(
        tournament_id=tournament.id,
        event_id=event.id,
        schedule_version_id=version.id,
        match_code="MIX_E1_WF_R1_01",
        match_type="WF",
        round_number=1,
        round_index=1,
        sequence_in_round=1,
        duration_minutes=60,
        team_a_id=team.id,
        team_b_id=other.id,
        placeholder_side_a="Ada Smith / Bea Jones",
        placeholder_side_b="Cara Lee / Dee Chen",
    ))
    tournament.public_schedule_version_id = version.id
    session.add(tournament)
    session.commit()
    return tournament, team


def test_public_directory_is_searchable_and_hides_private_fields(client, session: Session):
    tournament, team = _published(session)
    response = client.get(f"/api/public/tournaments/{tournament.id}/teams")
    assert response.status_code == 200
    body = response.json()
    listed = next(item for item in body["teams"] if item["team_id"] == team.id)
    assert "Bea Jones" in listed["players"]
    assert listed["photo_version"] is None
    raw = response.text.lower()
    assert "phone" not in raw
    assert "email" not in raw
    assert "storage_key" not in raw
    assert "+1555" not in raw


def test_public_photo_uses_the_existing_thumbnail_after_it_is_saved(client, session: Session, monkeypatch):
    monkeypatch.setenv("TEAM_PHOTO_OBJECT_STORE", "memory")
    reset_memory_store()
    tournament, team = _published(session)
    key = official_object_key(tournament.id, team.id, "public-photo-01")
    get_object_store().put_jpeg(key, _jpeg())
    session.add(TeamOfficialPhoto(
        tournament_id=tournament.id,
        team_id=team.id,
        storage_key=key,
        byte_size=10,
    ))
    session.commit()

    missing = client.get(f"/api/public/tournaments/{tournament.id}/teams/{team.id}/photo")
    assert missing.status_code == 200
    assert missing.headers["content-type"].startswith("image/jpeg")
    assert "max-age=60" in missing.headers["cache-control"]

    directory = client.get(f"/api/public/tournaments/{tournament.id}/teams")
    listed = next(item for item in directory.json()["teams"] if item["team_id"] == team.id)
    assert listed["photo_version"]

    other = client.get(f"/api/public/tournaments/{tournament.id}/teams/999999/photo")
    assert other.status_code == 404


def test_public_photo_stays_hidden_until_the_draw_is_published(client, session: Session):
    tournament = Tournament(
        name="Unpublished",
        location="Beach",
        timezone="America/New_York",
        start_date=date(2026, 6, 5),
        end_date=date(2026, 6, 7),
    )
    session.add(tournament)
    session.commit()
    session.refresh(tournament)
    response = client.get(f"/api/public/tournaments/{tournament.id}/teams")
    assert response.status_code == 200
    assert response.json()["status"] == "NOT_PUBLISHED"
    hidden = client.get(f"/api/public/tournaments/{tournament.id}/teams/1/photo")
    assert hidden.status_code == 404


def test_public_draws_hide_seeds_outside_round_robin_pools():
    from app.routes.public import _bracket_team_line, _rr_team_line, _waterfall_public_side

    assert _waterfall_public_side("Seed 1") == "TBD"
    assert _bracket_team_line(None, "Seed 4", None, None, {}, {}) == "TBD"
    assert _bracket_team_line(None, "Winner of Match #12", None, None, {}, {}) == "Winner of Match #12"
    assert _rr_team_line(None, "SEED_4", {}) == "Seed 4"
    assert _rr_team_line(None, "ConsL1", {}) == "Cons Seed 1"
