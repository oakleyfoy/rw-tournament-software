"""Next-match preview reads the draw and does not save a score."""

from sqlmodel import Session

from app.models.match import Match
from tests.test_desk import _setup_tournament_with_matches


def test_waterfall_preview_projects_the_winner_without_writing(client, session: Session):
    tournament, _version, _event, teams, _matches = _setup_tournament_with_matches(session)
    draft_id = client.post(f"/api/desk/tournaments/{tournament.id}/working-draft").json()["version_id"]
    snap = client.get(f"/api/desk/tournaments/{tournament.id}/snapshot?version_id={draft_id}").json()
    first = next(match for match in snap["matches"] if match["match_code"] == "WOM_E1_WF_R1_M01")
    before = session.get(Match, first["match_id"]).runtime_status

    preview = client.post(
        f"/api/desk/tournaments/{tournament.id}/matches/{first['match_id']}/next-preview",
        json={"version_id": draft_id, "winner_team_id": first["team1_id"]},
    )
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body["format_label"] == "8-game pro set · Tiebreak at 8–8"
    winner = next(card for card in body["cards"] if card["role"] == "winner")
    assert winner["time_label"] == "11:00 AM"
    assert winner["court_label"] == "Court 1"
    assert winner["opponent_pending"] is True
    session.expire_all()
    assert session.get(Match, first["match_id"]).runtime_status == before
    assert session.get(Match, first["match_id"]).winner_team_id is None

    rejected = client.patch(
        f"/api/desk/tournaments/{tournament.id}/matches/{first['match_id']}/finalize",
        json={"version_id": draft_id, "score": "4-8", "winner_team_id": teams[0].id},
    )
    assert rejected.status_code == 400
    assert "does not match" in rejected.json()["detail"]


def test_either_team_can_win_eight_three_from_the_winners_perspective(client, session: Session):
    tournament, _version, _event, _teams, _matches = _setup_tournament_with_matches(session)
    draft_id = client.post(f"/api/desk/tournaments/{tournament.id}/working-draft").json()["version_id"]
    snap = client.get(f"/api/desk/tournaments/{tournament.id}/snapshot?version_id={draft_id}").json()
    first = next(match for match in snap["matches"] if match["match_code"] == "WOM_E1_WF_R1_M01")
    second = next(match for match in snap["matches"] if match["match_code"] == "WOM_E1_WF_R1_M02")

    team_one = client.patch(
        f"/api/desk/tournaments/{tournament.id}/matches/{first['match_id']}/finalize",
        json={"version_id": draft_id, "score": "8-3", "winner_team_id": first["team1_id"]},
    )
    team_two = client.patch(
        f"/api/desk/tournaments/{tournament.id}/matches/{second['match_id']}/finalize",
        json={"version_id": draft_id, "score": "8-3", "winner_team_id": second["team2_id"]},
    )
    assert team_one.status_code == 200, team_one.text
    assert team_two.status_code == 200, team_two.text
    session.expire_all()
    saved = session.get(Match, second["match_id"])
    assert saved.winner_team_id == second["team2_id"]
    assert saved.score_json["actual"] == "8-3"
    assert saved.score_json["entry"] == "winner"


def test_default_win_stores_the_waterfall_score_without_asking_staff_to_flip_it(client, session: Session):
    tournament, _version, _event, _teams, _matches = _setup_tournament_with_matches(session)
    draft_id = client.post(f"/api/desk/tournaments/{tournament.id}/working-draft").json()["version_id"]
    snap = client.get(f"/api/desk/tournaments/{tournament.id}/snapshot?version_id={draft_id}").json()
    first = next(match for match in snap["matches"] if match["match_code"] == "WOM_E1_WF_R1_M01")
    second = next(match for match in snap["matches"] if match["match_code"] == "WOM_E1_WF_R2_M01")
    assert second["stage"] == "WF"

    accepted = client.patch(
        f"/api/desk/tournaments/{tournament.id}/matches/{first['match_id']}/finalize",
        json={"version_id": draft_id, "winner_team_id": first["team2_id"], "is_default": True},
    )
    assert accepted.status_code == 200, accepted.text
    session.expire_all()
    saved = session.get(Match, first["match_id"])
    assert saved.score_json["display"] == "DEFAULT"
    assert saved.score_json["actual"] == "8-0"
    assert saved.winner_team_id == first["team2_id"]
