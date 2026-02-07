"""Canonical court_names parser: string and list inputs must both produce correct labels."""
import pytest

from app.utils.courts import parse_court_names


def test_parse_court_names_string_comma_separated():
    """'1,5,6' parses to ['1','5','6'] (no list('1,5,6') corruption)."""
    assert parse_court_names("1,5,6") == ["1", "5", "6"]


def test_parse_court_names_list_unchanged():
    """['1','5','6'] stays ['1','5','6']."""
    assert parse_court_names(["1", "5", "6"]) == ["1", "5", "6"]


def test_parse_court_names_none_or_empty():
    """None or '' -> []."""
    assert parse_court_names(None) == []
    assert parse_court_names("") == []
    assert parse_court_names("   ") == []


def test_parse_court_names_string_strips_whitespace():
    """Comma-separated string: strip each part."""
    assert parse_court_names(" 1 , 5 , 6 ") == ["1", "5", "6"]


def test_parse_court_names_list_coerces_to_str():
    """List with mixed types coerces to str and strips."""
    assert parse_court_names([1, 5, 6]) == ["1", "5", "6"]
