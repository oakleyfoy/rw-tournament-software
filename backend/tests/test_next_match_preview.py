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
