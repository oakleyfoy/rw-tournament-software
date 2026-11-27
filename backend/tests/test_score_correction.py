"""Completed-score corrections stay completed and leave started matches alone."""

from sqlmodel import Session, select

from app.models.match import Match
from app.models.match_assignment import MatchAssignment
from app.models.sms_log import SmsLog
from app.services.rr_standings import build_pool_standings
from tests.test_desk import _setup_tournament_with_matches


def _draft(client, tournament_id: int) -> tuple[int, dict, dict]:
    draft_id = client.post(f"/api/desk/tournaments/{tournament_id}/working-draft").json()["version_id"]
    snap = client.get(f"/api/desk/tournaments/{tournament_id}/snapshot?version_id={draft_id}").json()
    by_code = {match["match_code"]: match for match in snap["matches"]}
    return draft_id, by_code["WOM_E1_WF_R1_M01"], by_code["WOM_E1_WF_R2_M01"]


def _finalize(client, tournament_id: int, draft_id: int, match: dict, score: str, winner_id: int):
    response = client.patch(
        f"/api/desk/tournaments/{tournament_id}/matches/{match['match_id']}/finalize",
        json={"version_id": draft_id, "score": score, "winner_team_id": winner_id},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_same_winner_correction_keeps_match_completed(client, session: Session):
    tournament, _version, _event, teams, _matches = _setup_tournament_with_matches(session)
    draft_id, first, downstream = _draft(client, tournament.id)
    finalized = _finalize(client, tournament.id, draft_id, first, "8-4", first["team1_id"])
    completed_at = finalized["match"]["completed_at"]
    assert completed_at

    playing = client.patch(
        f"/api/desk/tournaments/{tournament.id}/matches/{downstream['match_id']}/status",
        json={"version_id": draft_id, "status": "IN_PROGRESS"},
    )
    assert playing.status_code == 200, playing.text
    session.expire_all()
    downstream_before = session.get(Match, downstream["match_id"])
    assignment_before = session.exec(
        select(MatchAssignment).where(MatchAssignment.match_id == first["match_id"])
    ).first()
    sms_before = len(session.exec(select(SmsLog).where(SmsLog.tournament_id == tournament.id)).all())
    assert downstream_before.runtime_status == "IN_PROGRESS"
    assert downstream_before.team_a_id == teams[0].id

    corrected = client.patch(
        f"/api/desk/tournaments/{tournament.id}/matches/{first['match_id']}/correct",
        json={"version_id": draft_id, "score": "8-5", "winner_team_id": first["team1_id"]},
    )
    assert corrected.status_code == 200, corrected.text
    body = corrected.json()
    assert body["match"]["status"] == "FINAL"
    assert body["match"]["score_display"] == "8-5"
    assert body["match"]["completed_at"] == completed_at
    assert body["downstream_updates"] == []
    history = body["match"]["score_corrections"]
    assert history[-1]["previous_score"] == "8-4"
    assert history[-1]["corrected_score"] == "8-5"
    assert history[-1]["previous_winner"] == "Alpha"
    assert history[-1]["corrected_winner"] == "Alpha"
    assert history[-1]["corrected_at"]

    snap = client.get(f"/api/desk/tournaments/{tournament.id}/snapshot?version_id={draft_id}").json()
    updated = next(match for match in snap["matches"] if match["match_id"] == first["match_id"])
    still_playing = next(match for match in snap["matches"] if match["match_id"] == downstream["match_id"])
    assert updated["score_display"] == "8-5"
    assert updated["status"] == "FINAL"
    assert updated["completed_at"] == completed_at
    assert still_playing["status"] == "IN_PROGRESS"
    assert still_playing["team1_id"] == teams[0].id

    session.expire_all()
    assignment_after = session.exec(
        select(MatchAssignment).where(MatchAssignment.match_id == first["match_id"])
    ).first()
    assert assignment_after.slot_id == assignment_before.slot_id
    sms_after = len(session.exec(select(SmsLog).where(SmsLog.tournament_id == tournament.id)).all())
    assert sms_after == sms_before

    draft_match = session.get(Match, first["match_id"])
    draft_match.match_type = "RR"
    draft_match.match_code = "WOM_E1_POOLA_RR_01"
    session.add(draft_match)
    session.commit()
    standings = build_pool_standings([draft_match], lambda team_id: str(team_id))
    winner_stats = dict(standings.sorted_rows)[teams[0].id]
    assert winner_stats["wins"] == 1
    assert winner_stats["games_won"] == 8
    assert winner_stats["games_lost"] == 5


def test_winner_change_does_not_rewrite_started_match(client, session: Session):
    tournament, _version, _event, teams, _matches = _setup_tournament_with_matches(session)
    draft_id, first, downstream = _draft(client, tournament.id)
    _finalize(client, tournament.id, draft_id, first, "8-4", first["team1_id"])
    playing = client.patch(
        f"/api/desk/tournaments/{tournament.id}/matches/{downstream['match_id']}/status",
        json={"version_id": draft_id, "status": "IN_PROGRESS"},
    )
    assert playing.status_code == 200, playing.text

    corrected = client.patch(
        f"/api/desk/tournaments/{tournament.id}/matches/{first['match_id']}/correct",
        json={"version_id": draft_id, "score": "4-8", "winner_team_id": first["team2_id"]},
    )
    assert corrected.status_code == 200, corrected.text
    reasons = {warning["reason"] for warning in corrected.json()["warnings"]}
    assert "DOWNSTREAM_ALREADY_STARTED" in reasons
    assert corrected.json()["match"]["status"] == "FINAL"
    assert corrected.json()["match"]["winner_team_id"] == first["team2_id"]

    session.expire_all()
    downstream_match = session.get(Match, downstream["match_id"])
    original = session.get(Match, first["match_id"])
    assert downstream_match.runtime_status == "IN_PROGRESS"
    assert downstream_match.team_a_id == teams[0].id
    assert original.runtime_status == "FINAL"
    assert original.completed_at is not None


def test_winner_change_updates_scheduled_downstream_only(client, session: Session):
    tournament, _version, _event, teams, _matches = _setup_tournament_with_matches(session)
    draft_id, first, downstream = _draft(client, tournament.id)
    _finalize(client, tournament.id, draft_id, first, "8-4", first["team1_id"])

    corrected = client.patch(
        f"/api/desk/tournaments/{tournament.id}/matches/{first['match_id']}/correct",
        json={"version_id": draft_id, "score": "4-8", "winner_team_id": first["team2_id"]},
    )
    assert corrected.status_code == 200, corrected.text
    session.expire_all()
    downstream_match = session.get(Match, downstream["match_id"])
    assert downstream_match.runtime_status == "SCHEDULED"
    assert downstream_match.team_a_id == teams[3].id


def test_winner_change_keeps_trophy_distribution_under_review(client, session: Session):
    tournament, _version, _event, _teams, _matches = _setup_tournament_with_matches(session)
    draft_id, first, downstream = _draft(client, tournament.id)
    session.expire_all()
    match = session.get(Match, first["match_id"])
    match.match_type = "BRACKET"
    match.match_code = "WOM_E1_B1_M7"
    feeder = session.get(Match, downstream["match_id"])
    feeder.source_match_a_id = None
    feeder.source_a_role = None
    session.add(match)
    session.add(feeder)
    session.commit()

    _finalize(client, tournament.id, draft_id, first, "8-4", first["team1_id"])
    board = client.get(f"/api/desk/tournaments/{tournament.id}/trophies?version_id={draft_id}").json()
    awards = board["finals"][0]["awards"]
    champion = next(award for award in awards if award["role"] == "champion")
    marked = client.post(
        f"/api/desk/tournaments/{tournament.id}/trophies",
        json={"version_id": draft_id, "award_key": champion["award_key"], "team_id": champion["team_id"]},
    )
    assert marked.status_code == 200, marked.text

    corrected = client.patch(
        f"/api/desk/tournaments/{tournament.id}/matches/{first['match_id']}/correct",
        json={"version_id": draft_id, "score": "4-8", "winner_team_id": first["team2_id"]},
    )
    assert corrected.status_code == 200, corrected.text
    reviewed = client.get(f"/api/desk/tournaments/{tournament.id}/trophies?version_id={draft_id}").json()
    reviewed_champion = next(award for award in reviewed["finals"][0]["awards"] if award["role"] == "champion")
    assert reviewed_champion["team_id"] == first["team2_id"]
    assert reviewed_champion["review_required"] is True
    assert reviewed_champion["distributed"] is False
    rejected = client.post(
        f"/api/desk/tournaments/{tournament.id}/trophies",
        json={"version_id": draft_id, "award_key": reviewed_champion["award_key"], "team_id": first["team2_id"]},
    )
    assert rejected.status_code == 409
