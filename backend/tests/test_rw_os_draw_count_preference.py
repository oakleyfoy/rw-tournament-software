"""Fewer practical draws are strongly preferred unless rating evidence is exceptional."""

from app.services.bracket_split_planner import (
    EXTRA_BRACKET_PENALTY,
    analyze_custom_structure,
    minimum_bracket_count,
    plan_draw,
    validate_custom_sizes,
)
from app.services.canonical_teams import SnapshotPlayer, SnapshotTeam
from app.services.rw_os_fixtures import get_fixture_event


def _team(key: str, rating, draw="womens") -> SnapshotTeam:
    left, right = key.split("/")
    half = None if rating is None else rating / 2
    return SnapshotTeam(
        team_key=key,
        draw_kind=draw,
        draw_label="Women's",
        player1=SnapshotPlayer(rw_id=left, name=f"P{left}", rating=half),
        player2=SnapshotPlayer(rw_id=right, name=f"P{right}", rating=half),
        team_rating=rating,
        rating_status="complete",
        status="Confirmed",
        bucket="active",
    )


def _rated_field(count: int, *, step=0.02, offset=0) -> list[SnapshotTeam]:
    return [
        _team(f"{index + offset}/{index + offset + 1000}", 10 - (index - 1) * step) for index in range(1, count + 1)
    ]


def _clustered_44(*, high=9.5, mid=7.0, low=4.0) -> list[SnapshotTeam]:
    teams = []
    for index in range(1, 45):
        if index <= 14:
            rating = high
        elif index <= 30:
            rating = mid
        else:
            rating = low
        teams.append(_team(f"{index}/{index + 800}", rating))
    return teams


def test_minimum_bracket_count_formula():
    assert minimum_bracket_count(44) == 2
    assert minimum_bracket_count(60) == 2
    assert minimum_bracket_count(68) == 3
    assert minimum_bracket_count(80) == 3
    assert minimum_bracket_count(97) == 4


def test_44_fixture_two_brackets_dominate():
    teams = [SnapshotTeam.from_dict(row) for row in get_fixture_event(244)["teams"]]
    plan = plan_draw("womens", teams, 44)
    keys = [option["optionKey"] for option in plan["options"]]
    two_count = sum(1 for option in plan["options"] if len(option["sizes"]) == 2)
    assert plan["options"][0]["recommended"] is True
    assert len(plan["options"][0]["sizes"]) == 2
    assert two_count >= 4
    assert any(item["code"] == "minimum_draw_count" for item in plan["options"][0]["reasons"])
    three = analyze_custom_structure(teams, (20, 12, 12))
    assert three["score"]["extraBracketPenalty"] == EXTRA_BRACKET_PENALTY
    assert three["score"]["total"] < plan["options"][0]["score"]["total"]
    assert any(item["code"] == "extra_draw" for item in three["warnings"])
    assert keys == ["20-24", "24-20", "16-28", "28-16", "12-32"] or all(
        len(option["sizes"]) == 2 for option in plan["options"]
    )


def test_68_three_brackets_dominate():
    plan = plan_draw("womens", _rated_field(67), 68)
    keys = [option["optionKey"] for option in plan["options"]]
    three_count = sum(1 for option in plan["options"] if len(option["sizes"]) == 3)
    assert plan["options"][0]["recommended"] is True
    assert len(plan["options"][0]["sizes"]) == 3
    assert three_count >= 4
    assert "16-16-16-20" not in keys
    four = analyze_custom_structure(_rated_field(67), (16, 16, 16, 20), forecast_count=68)
    assert four["fakeTeamCount"] == 0
    assert four["score"]["extraBracketPenalty"] == EXTRA_BRACKET_PENALTY
    assert four["score"]["total"] < plan["options"][0]["score"]["total"]
    assert all(len(option["sizes"]) == 3 for option in plan["options"])


def test_extra_draw_can_win_for_major_rating_clusters():
    teams = _clustered_44()
    plan = plan_draw("womens", teams, 44)
    recommended = plan["options"][0]
    two_best = analyze_custom_structure(teams, (20, 24))
    three = analyze_custom_structure(teams, (14, 16, 14))
    assert three["score"]["cutQuality"] > two_best["score"]["cutQuality"]
    assert three["score"]["total"] > two_best["score"]["total"]
    assert len(recommended["sizes"]) == 3 or three["score"]["total"] >= recommended["score"]["total"]
    assert any(item["code"] in {"extra_draw", "extra_draw_justified"} for item in three["warnings"] + three["reasons"])


def test_slight_rating_gain_cannot_justify_extra_draw():
    teams = _rated_field(44, step=0.01)
    two = analyze_custom_structure(teams, (20, 24))
    three = analyze_custom_structure(teams, (16, 14, 14))
    assert two["score"]["total"] > three["score"]["total"]
    plan = plan_draw("womens", teams, 44)
    assert len(plan["options"][0]["sizes"]) == 2


def test_custom_a_4_20_20_rejected():
    try:
        validate_custom_sizes((4, 20, 20), 44)
        assert False
    except ValueError as exc:
        assert "at least 8 teams" in str(exc)


def test_custom_b_8_16_20_valid():
    validate_custom_sizes((8, 16, 20), 44)


def test_custom_c_forecast_6_single_valid():
    validate_custom_sizes((6,), 6)


def test_custom_d_forecast_12_6_6_rejected():
    try:
        validate_custom_sizes((6, 6), 12)
        assert False
    except ValueError as exc:
        assert "at least 8 teams" in str(exc)


def test_custom_e_16_20_32_for_68_valid():
    validate_custom_sizes((16, 20, 32), 68)


def test_custom_f_over_32_rejected():
    try:
        validate_custom_sizes((36, 32), 68)
        assert False
    except ValueError as exc:
        assert "32" in str(exc)


def test_custom_g_wrong_sum_rejected():
    try:
        validate_custom_sizes((16, 20, 20), 68)
        assert False
    except ValueError as exc:
        assert "68" in str(exc)
