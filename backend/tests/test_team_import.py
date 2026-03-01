"""Tests for enhanced team import with full field support."""

import pytest
from datetime import date
from sqlmodel import Session, select

from app.models.team import Team
from app.routes.team_import import parse_team_rows


# ---------------------------------------------------------------------------
# Parser tests (no database needed)
# ---------------------------------------------------------------------------


class TestParseTeamRows:
    """Test the tab-separated parser."""

    def test_full_10_field_format(self):
        """Parse complete WAR Tournaments export format."""
        raw = (
            "1\tB\tAlex / Torrie\tAlex Quiros, PA / Torrie Kline, PA\t"
            "Womens\t8.5\t8123612060\talejandraquiros@hotmail.com\t"
            "6109696386\tTorrie1@6Klines.com"
        )
        rows = parse_team_rows(raw)
        assert len(rows) == 1
        r = rows[0]
        assert r.seed == 1
        assert r.avoid_group == "B"
        assert r.display_name == "Alex / Torrie"
        assert r.full_name == "Alex Quiros, PA / Torrie Kline, PA"
        assert r.event_name == "Womens"
        assert r.rating == 8.5
        assert r.p1_cell == "8123612060"
        assert r.p1_email == "alejandraquiros@hotmail.com"
        assert r.p2_cell == "6109696386"
        assert r.p2_email == "Torrie1@6Klines.com"

    def test_multiple_rows(self):
        """Parse multiple teams."""
        raw = (
            "1\tB\tAlex / Torrie\tFull Name 1\tWomens\t8.5\t"
            "8123612060\ta@test.com\t6109696386\tb@test.com\n"
            "2\tA\tJeni / Marina\tFull Name 2\tWomens\t8.5\t"
            "2819199929\tc@test.com\t7133068878\td@test.com\n"
            "3\t—\tNikki / Jonna\tFull Name 3\tWomens\t8\t"
            "3619606690\te@test.com\t3614388722\tf@test.com"
        )
        rows = parse_team_rows(raw)
        assert len(rows) == 3
        assert rows[0].seed == 1
        assert rows[0].avoid_group == "B"
        assert rows[1].seed == 2
        assert rows[1].avoid_group == "A"
        assert rows[2].seed == 3
        assert rows[2].avoid_group is None  # "—" becomes None

    def test_multi_group_avoid(self):
        """Parse team with multiple avoid groups like 'A,B'."""
        raw = "5\tA,B\tTest / Team\tFull\tMixed\t8\t5551234567\ta@b.com\t5559876543\tc@d.com"
        rows = parse_team_rows(raw)
        assert len(rows) == 1
        assert rows[0].avoid_group == "A,B"

    def test_dash_group_is_none(self):
        """Dash as avoid group should parse as None."""
        raw = "1\t-\tTeam Name\tFull Name\tMixed\t8\t5551111111\ta@b.com\t5552222222\tc@d.com"
        rows = parse_team_rows(raw)
        assert rows[0].avoid_group is None

    def test_original_4_field_format(self):
        """Backward compatible with original: seed group rating name."""
        raw = "1\ta\t9\tHeather Robinson / Shea Butler"
        rows = parse_team_rows(raw)
        assert len(rows) == 1
        r = rows[0]
        assert r.seed == 1
        assert r.avoid_group == "a"
        assert r.rating == 9.0
        assert r.display_name == "Heather Robinson / Shea Butler"

    def test_empty_lines_skipped(self):
        """Empty lines should be ignored."""
        raw = "1\tA\tTeam 1\tFull 1\tMixed\t8\t111\ta@b.com\t222\tc@d.com\n\n\n2\tB\tTeam 2\tFull 2\tMixed\t7\t333\te@f.com\t444\tg@h.com"
        rows = parse_team_rows(raw)
        assert len(rows) == 2

    def test_no_phones(self):
        """Teams without phone data should still parse."""
        raw = "1\t—\tTeam Name\tFull Name\tWomens\t8.5\t—\t—\t—\t—"
        rows = parse_team_rows(raw)
        assert len(rows) == 1
        assert rows[0].p1_cell is None
        assert rows[0].p2_cell is None

    def test_empty_input(self):
        """Empty input should return empty list."""
        assert parse_team_rows("") == []
        assert parse_team_rows("   ") == []


# ---------------------------------------------------------------------------
# API endpoint tests (need database)
# ---------------------------------------------------------------------------


@pytest.fixture
def setup_event(session: Session):
    """Create a tournament and event for import testing."""
    from app.models.tournament import Tournament
    from app.models.event import Event

    tournament = Tournament(
        name="Import Test",
        location="Test",
        timezone="UTC",
        start_date=date(2026, 3, 15),
        end_date=date(2026, 3, 16),
    )
    session.add(tournament)
    session.commit()
    session.refresh(tournament)

    event = Event(
        tournament_id=tournament.id,
        name="Womens",
        team_count=16,
        category="womens",
    )
    session.add(event)
    session.commit()
    session.refresh(event)

    return tournament, event


def test_import_full_format(client, session, setup_event):
    """Import teams with all fields."""
    _, event = setup_event

    raw_text = (
        "1\tB\tAlex / Torrie\tAlex Quiros, PA / Torrie Kline, PA\t"
        "Womens\t8.5\t8123612060\talejandraquiros@hotmail.com\t"
        "6109696386\tTorrie1@6Klines.com\n"
        "2\tA\tJeni / Marina\tJeni Dao, TX / Marina Wang, TX\t"
        "Womens\t8.5\t2819199929\tJenidao77@gmail.com\t"
        "7133068878\tmwangtx1@gmail.com\n"
        "3\t—\tNikki / Jonna\tNikki Cortinas, TX / Jonna Davidson, TX\t"
        "Womens\t8\t3619606690\tNikkic627@yahoo.com\t"
        "3614388722\tjonna@atesting.com"
    )

    resp = client.post(
        f"/api/events/{event.id}/teams/import",
        json={"raw_text": raw_text, "clear_existing": True},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_parsed"] == 3
    assert data["created"] == 3
    assert data["errors"] == 0

    # Verify teams in DB
    teams = session.exec(
        select(Team).where(Team.event_id == event.id)
    ).all()
    assert len(teams) == 3

    # Check first team has all fields
    alex = [t for t in teams if "Alex" in t.name][0]
    assert alex.seed == 1
    assert alex.rating == 8.5
    assert alex.p1_cell == "8123612060"
    assert alex.p1_email == "alejandraquiros@hotmail.com"
    assert alex.p2_cell == "6109696386"
    assert alex.p2_email == "Torrie1@6Klines.com"


def test_import_creates_avoid_edges(client, session, setup_event):
    """Import with avoid groups should create avoid edges."""
    _, event = setup_event

    # Two teams in group B — should create 1 avoid edge
    raw_text = (
        "1\tB\tTeam One\tFull 1\tWomens\t8.5\t111\ta@b.com\t222\tc@d.com\n"
        "2\tB\tTeam Two\tFull 2\tWomens\t8\t333\te@f.com\t444\tg@h.com\n"
        "3\tA\tTeam Three\tFull 3\tWomens\t8\t555\ti@j.com\t666\tk@l.com"
    )

    resp = client.post(
        f"/api/events/{event.id}/teams/import",
        json={"raw_text": raw_text, "clear_existing": True},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["created"] == 3
    # 2 teams in group B = 1 edge, 1 team in group A = 0 edges
    assert data["avoid_edges_created"] == 1


def test_import_multi_group_creates_edges(client, session, setup_event):
    """Team with 'A,B' should get edges to ALL teams in group A and group B."""
    _, event = setup_event

    raw_text = (
        "1\tA\tTeam Alpha\tFull\tW\t8\t111\ta@b.com\t222\tc@d.com\n"
        "2\tB\tTeam Beta\tFull\tW\t8\t333\te@f.com\t444\tg@h.com\n"
        "3\tA,B\tTeam Multi\tFull\tW\t8\t555\ti@j.com\t666\tk@l.com"
    )

    resp = client.post(
        f"/api/events/{event.id}/teams/import",
        json={"raw_text": raw_text, "clear_existing": True},
    )
    assert resp.status_code == 200
    data = resp.json()
    # Team Multi is in group A AND group B
    # Group A: [Team Alpha, Team Multi] = 1 edge
    # Group B: [Team Beta, Team Multi] = 1 edge
    # Total = 2 edges
    assert data["avoid_edges_created"] == 2


def test_import_clear_existing(client, session, setup_event):
    """clear_existing=True should remove old teams first."""
    _, event = setup_event

    # First import
    raw1 = "1\t—\tOld Team\tFull\tW\t8\t111\ta@b.com\t222\tc@d.com"
    client.post(
        f"/api/events/{event.id}/teams/import",
        json={"raw_text": raw1, "clear_existing": True},
    )
    teams = session.exec(select(Team).where(Team.event_id == event.id)).all()
    assert len(teams) == 1

    # Second import with clear
    raw2 = "1\t—\tNew Team A\tFull\tW\t9\t333\te@f.com\t444\tg@h.com\n2\t—\tNew Team B\tFull\tW\t8\t555\ti@j.com\t666\tk@l.com"
    client.post(
        f"/api/events/{event.id}/teams/import",
        json={"raw_text": raw2, "clear_existing": True},
    )
    teams = session.exec(select(Team).where(Team.event_id == event.id)).all()
    assert len(teams) == 2  # Old team cleared, 2 new ones


def test_preview_no_db_writes(client, session, setup_event):
    """Preview should not create any teams in the database."""
    _, event = setup_event

    raw_text = "1\tA\tPreview Team\tFull\tW\t8\t111\ta@b.com\t222\tc@d.com"
    resp = client.post(
        f"/api/events/{event.id}/teams/import/preview",
        json={"raw_text": raw_text},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_parsed"] == 1
    assert data["created"] == 1  # Would create

    # But no teams in DB
    teams = session.exec(select(Team).where(Team.event_id == event.id)).all()
    assert len(teams) == 0


def test_import_invalid_event(client, session):
    """Import to nonexistent event should 404."""
    resp = client.post(
        "/api/events/99999/teams/import",
        json={"raw_text": "1\t—\tTeam\tFull\tW\t8\t111\ta@b.com\t222\tc@d.com"},
    )
    assert resp.status_code == 404


def test_import_empty_text(client, session, setup_event):
    """Empty text should 400."""
    _, event = setup_event
    resp = client.post(
        f"/api/events/{event.id}/teams/import",
        json={"raw_text": ""},
    )
    assert resp.status_code == 400
