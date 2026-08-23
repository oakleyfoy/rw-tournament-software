"""Plain-language planner explanations. Scoring math stays internal."""

from pathlib import Path

from app.services.bracket_split_planner import analyze_custom_structure, plan_draw
from app.services.canonical_teams import SnapshotPlayer, SnapshotTeam
from app.services.rw_os_fixtures import get_fixture_event
from app.services.team_rating import classify_rating_status, compute_team_rating

FRONTEND_CARD = Path(__file__).resolve().parents[2] / "frontend" / "src" / "pages" / "CreateTournamentFromRwOs.tsx"


def _team(key: str, rating, status="complete", draw="womens") -> SnapshotTeam:
    left, right = key.split("/")
    half = None if rating is None else rating / 2
    return SnapshotTeam(
        team_key=key,
        draw_kind=draw,
        draw_label="Women's",
        player1=SnapshotPlayer(rw_id=left, name=f"P{left}", rating=half),
        player2=SnapshotPlayer(rw_id=right, name=f"P{right}", rating=half),
        team_rating=rating,
        rating_status=status,
        status="Confirmed",
        bucket="active",
    )


def _named(draw, name1, id1, rating1, name2, id2, rating2) -> SnapshotTeam:
    return SnapshotTeam(
        team_key=f"{id1}/{id2}",
        draw_kind=draw,
        draw_label="Mixed" if draw == "mixed" else "Women's",
        player1=SnapshotPlayer(rw_id=id1, name=name1, rating=rating1),
        player2=SnapshotPlayer(rw_id=id2, name=name2, rating=rating2),
        team_rating=compute_team_rating(rating1, rating2),
        rating_status=classify_rating_status(rating1, rating2),
        status="Confirmed",
        bucket="active",
    )


def test_a_b_raw_score_breakdown_not_in_normal_card():
    text = FRONTEND_CARD.read_text(encoding="utf-8")
    assert "Score {option.score.total" not in text
    assert "Cut {option.score.cutQuality" not in text
    assert "Tiny −" not in text
    assert "Tiny penalty" not in text
    assert "score-line" not in text


def test_c_strong_cut_has_plain_language_positive():
    teams = [SnapshotTeam.from_dict(row) for row in get_fixture_event(244)["teams"]]
    option = analyze_custom_structure(teams, (20, 24))
    messages = [item["message"] for item in option["reasons"]]
    assert any("Strong natural rating break after team #20" in message for message in messages)
    assert all("Cut 40" not in message for message in messages)


def test_d_small_bracket_says_smaller_than_preferred():
    teams = [_team(f"{index}/{index + 100}", 10 - index * 0.02) for index in range(1, 45)]
    option = analyze_custom_structure(teams, (32, 12))
    warnings = [item["message"].lower() for item in option["warnings"]]
    assert any("smaller than preferred" in message for message in warnings)


def test_e_awkward_bracket_has_operational_warning():
    teams = [_team(f"{index}/{index + 200}", 10 - index * 0.02) for index in range(1, 45)]
    option = analyze_custom_structure(teams, (21, 23))
    assert any(item["code"] == "awkward_size" for item in option["warnings"])
    assert any("less operationally clean" in item["message"] for item in option["warnings"])


def test_f_unrated_penalty_becomes_rating_review_warning():
    teams = [
        _team("1/2", 8.0),
        _named("womens", "Pam Kennedy", "10", 4.0, "Michael Mullenmeister", "11", None),
    ]
    option = analyze_custom_structure(teams, (2,))
    warning = next(item for item in option["warnings"] if item["code"] == "rating_review")
    assert "rating review" in warning["message"]
    assert "1 team needs rating review" in warning["message"]


def test_g_provisional_cut_becomes_future_team_warning():
    teams = [_team(f"{index}/{index + 300}", 10 - index * 0.02) for index in range(1, 68)]
    option = analyze_custom_structure(teams, (32, 24, 12, 12), forecast_count=80)
    assert any(item["code"] == "provisional_cut" for item in option["warnings"])
    assert any("have not registered" in item["message"] for item in option["warnings"])


def test_h_recommended_card_has_reasons():
    teams = [SnapshotTeam.from_dict(row) for row in get_fixture_event(244)["teams"]]
    plan = plan_draw("womens", teams)
    recommended = plan["options"][0]
    assert recommended["recommended"] is True
    assert recommended["reasons"]


def test_i_alternatives_have_strengths_or_tradeoffs():
    teams = [SnapshotTeam.from_dict(row) for row in get_fixture_event(244)["teams"]]
    plan = plan_draw("womens", teams)
    alternatives = [option for option in plan["options"] if not option["recommended"]]
    assert alternatives
    for option in alternatives:
        assert option["reasons"] or option["warnings"]


def test_j_numeric_score_still_exists_internally():
    teams = [SnapshotTeam.from_dict(row) for row in get_fixture_event(244)["teams"]]
    plan = plan_draw("womens", teams)
    score = plan["options"][0]["score"]
    assert "total" in score
    assert "cutQuality" in score
    assert "sizeQuality" in score
    assert isinstance(score["total"], (int, float))


def test_k_44_team_recommendation_order_unchanged():
    teams = [SnapshotTeam.from_dict(row) for row in get_fixture_event(244)["teams"]]
    plan = plan_draw("womens", teams)
    assert [option["optionKey"] for option in plan["options"]][0] == "20-24"
    assert plan["options"][0]["recommended"] is True
