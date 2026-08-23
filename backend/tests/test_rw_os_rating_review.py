"""Draw-scoped rating-review identification. Display only — no rating or RW-OS writes."""

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.models.event import Event
from app.models.match import Match
from app.services.bracket_split_planner import plan_draw, plan_snapshot, rating_review_teams
from app.services.canonical_teams import SnapshotPlayer, SnapshotTeam
from app.services.rw_os_client import RwOsReadOnlyError
from app.services.team_rating import classify_rating_status, compute_team_rating


def _complete(key: str, rating: float, draw="womens") -> SnapshotTeam:
    left, right = key.split("/")
    half = rating / 2
    return SnapshotTeam(
        team_key=key,
        draw_kind=draw,
        draw_label="Women's" if draw == "womens" else "Mixed",
        player1=SnapshotPlayer(rw_id=left, name=f"P{left}", rating=half),
        player2=SnapshotPlayer(rw_id=right, name=f"P{right}", rating=half),
        team_rating=rating,
        rating_status="complete",
        status="Confirmed",
        bucket="active",
    )


def _named_team(
    *,
    draw: str,
    name1: str,
    id1: str,
    rating1,
    name2: str,
    id2: str,
    rating2,
) -> SnapshotTeam:
    return SnapshotTeam(
        team_key=f"{id1}/{id2}",
        draw_kind=draw,
        draw_label="Women's" if draw == "womens" else "Mixed",
        player1=SnapshotPlayer(rw_id=id1, name=name1, rating=rating1),
        player2=SnapshotPlayer(rw_id=id2, name=name2, rating=rating2),
        team_rating=compute_team_rating(rating1, rating2),
        rating_status=classify_rating_status(rating1, rating2),
        status="Confirmed",
        bucket="active",
    )


PARTIAL = _named_team(
    draw="mixed",
    name1="Pam Kennedy",
    id1="12345",
    rating1=4.0,
    name2="Michael Mullenmeister",
    id2="67890",
    rating2=None,
)
MISSING = _named_team(
    draw="mixed",
    name1="Jane Smith",
    id1="111",
    rating1=None,
    name2="Mary Jones",
    id2="222",
    rating2=None,
)
WOMENS_PARTIAL = _named_team(
    draw="womens",
    name1="Susan Brown",
    id1="333",
    rating1=None,
    name2="Lisa White",
    id2="444",
    rating2=3.5,
)


def test_a_zero_problem_teams_warning_absent():
    teams = [_complete("1/2", 8.0), _complete("3/4", 7.5)]
    plan = plan_draw("womens", teams)
    assert plan["ratingReviewNeeded"] == 0
    assert plan["ratingReviewTeams"] == []
    assert rating_review_teams(teams) == []


def test_b_one_partial_team_singular_and_exact():
    teams = [_complete("1/2", 8.0, "mixed"), PARTIAL]
    plan = plan_draw("mixed", teams)
    assert plan["ratingReviewNeeded"] == 1
    assert len(plan["ratingReviewTeams"]) == 1
    row = plan["ratingReviewTeams"][0]
    assert row["name"] == "Pam Kennedy / Michael Mullenmeister"
    assert row["ratingStatus"] == "partial"
    assert row["teamKey"] == "12345/67890"


def test_c_two_problem_teams_plural_and_both_listed():
    teams = [_complete("1/2", 8.0, "mixed"), PARTIAL, MISSING]
    plan = plan_draw("mixed", teams)
    assert plan["ratingReviewNeeded"] == 2
    names = {row["name"] for row in plan["ratingReviewTeams"]}
    assert names == {"Pam Kennedy / Michael Mullenmeister", "Jane Smith / Mary Jones"}


def test_d_partial_identifies_which_player_is_missing():
    row = rating_review_teams([PARTIAL])[0]
    assert row["ratingStatus"] == "partial"
    assert row["player1"]["name"] == "Pam Kennedy"
    assert row["player1"]["rwId"] == "12345"
    assert row["player1"]["rating"] == 4.0
    assert row["player2"]["name"] == "Michael Mullenmeister"
    assert row["player2"]["rwId"] == "67890"
    assert row["player2"]["rating"] is None
    assert row["teamRating"] == 4.0


def test_e_both_missing_shows_not_available():
    row = rating_review_teams([MISSING])[0]
    assert row["ratingStatus"] == "missing"
    assert row["player1"]["rating"] is None
    assert row["player2"]["rating"] is None
    assert row["teamRating"] is None


def test_f_complete_team_never_in_review_list():
    complete = _complete("9/10", 8.2, "mixed")
    rows = rating_review_teams([complete, PARTIAL])
    assert [row["teamKey"] for row in rows] == [PARTIAL.team_key]
    assert complete.rating_status == "complete"


def test_g_mixed_warning_only_lists_mixed_problems():
    snapshot = plan_snapshot([PARTIAL, MISSING, WOMENS_PARTIAL, _complete("5/6", 8.0)])
    mixed = next(draw for draw in snapshot["draws"] if draw["drawKind"] == "mixed")
    keys = {row["teamKey"] for row in mixed["ratingReviewTeams"]}
    assert keys == {PARTIAL.team_key, MISSING.team_key}
    assert all(row["drawKind"] == "mixed" for row in mixed["ratingReviewTeams"])


def test_h_womens_warning_only_lists_womens_problems():
    snapshot = plan_snapshot([PARTIAL, MISSING, WOMENS_PARTIAL, _complete("5/6", 8.0)])
    womens = next(draw for draw in snapshot["draws"] if draw["drawKind"] == "womens")
    assert len(womens["ratingReviewTeams"]) == 1
    assert womens["ratingReviewTeams"][0]["teamKey"] == WOMENS_PARTIAL.team_key
    assert womens["ratingReviewTeams"][0]["drawKind"] == "womens"


def test_i_reloading_planner_does_not_call_rw_os(client: TestClient, monkeypatch):
    created = client.post("/api/rw-os/imports", json={"tournament_id": 244})
    assert created.status_code == 201
    import_id = created.json()["import"]["id"]

    def forbid(*_args, **_kwargs):
        raise AssertionError("expanding/reloading the rating review must not call RW-OS")

    monkeypatch.setattr("app.services.rw_os_client.RwOsClient.get_event", forbid)
    monkeypatch.setattr("app.services.rw_os_client.RwOsClient.list_events", forbid)
    monkeypatch.setattr("app.services.rw_os_client.RwOsClient.refresh_event", forbid)
    loaded = client.get(f"/api/rw-os/imports/{import_id}")
    assert loaded.status_code == 200
    draw = loaded.json()["planner"]["draws"][0]
    assert "ratingReviewTeams" in draw
    assert draw["ratingReviewNeeded"] == len(draw["ratingReviewTeams"])


def test_j_no_production_or_local_writes(client: TestClient, session: Session):
    created = client.post("/api/rw-os/imports", json={"tournament_id": 244})
    tournament_id = created.json()["import"]["tournamentId"]
    assert created.json()["rwOsWrites"] == 0
    assert created.json()["bracketsCreated"] is False
    assert session.exec(select(Event).where(Event.tournament_id == tournament_id)).all() == []
    assert session.exec(select(Match).where(Match.tournament_id == tournament_id)).all() == []
    try:
        from app.services.rw_os_client import RwOsClient

        RwOsClient(fixtures=True)._request("POST", "/api/integrations/tournament-software/events")
        assert False
    except RwOsReadOnlyError:
        pass
