"""Regression tests for parse_score handling of structured 'sets' payloads."""

from app.services.score_parser import parse_score


def test_parse_score_sets_as_dicts():
    parsed = parse_score({"sets": [{"a": 6, "b": 2}, {"a": 6, "b": 3}]})
    assert parsed is not None
    assert parsed.team_a_sets_won == 2
    assert parsed.team_b_sets_won == 0
    assert parsed.team_a_games == 12
    assert parsed.team_b_games == 5


def test_parse_score_sets_as_lists_does_not_crash():
    # Some scores store sets as [a, b] pairs rather than {"a":..,"b":..}.
    # This previously raised AttributeError ('list' has no attribute 'get')
    # and 500'd the round-robin endpoint.
    parsed = parse_score({"sets": [[6, 2], [6, 3]], "display": "6-2, 6-3"})
    assert parsed is not None
    assert parsed.team_a_sets_won == 2
    assert parsed.team_b_sets_won == 0
    assert parsed.team_a_games == 12
    assert parsed.team_b_games == 5


def test_parse_score_sets_with_garbage_elements_is_safe():
    parsed = parse_score({"sets": [None, "x", 5, [6, 3]]})
    assert parsed is not None
    # Only the one valid pair contributes.
    assert parsed.team_a_sets_won == 1
    assert parsed.team_a_games == 6
    assert parsed.team_b_games == 3


def test_parse_score_display_string_still_works():
    parsed = parse_score({"display": "8-4"})
    assert parsed is not None
    assert parsed.team_a_games == 8
    assert parsed.team_b_games == 4
