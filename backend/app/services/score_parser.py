"""
Minimal score parser for standard tennis-style score strings.

Supports formats like:
  "8-4"           → 1 set, games 8-4
  "6-3 4-6 10-7"  → 3 sets, games summed
  "6-3, 4-6, 10-7" → comma-separated variant
  {"display": "8-4"} → extracts display string first

Returns None on parse failure (non-fatal).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class ParsedScore:
    sets: List[Tuple[int, int]]  # (team_a_games, team_b_games) per set
    team_a_sets_won: int
    team_b_sets_won: int
    team_a_games: int
    team_b_games: int


def parse_score(score_json: Optional[Dict[str, Any]]) -> Optional[ParsedScore]:
    """Parse a score_json blob into structured set/game counts.

    Returns None if the score cannot be parsed.
    """
    if not score_json:
        return None

    raw: Optional[str] = None
    if isinstance(score_json, str):
        raw = score_json
    elif isinstance(score_json, dict):
        if "sets" in score_json and isinstance(score_json["sets"], list):
            return _parse_structured_sets(score_json["sets"])
        raw = str(score_json.get("display") or score_json.get("score") or "")
    if not raw or not raw.strip():
        return None

    return _parse_score_string(raw.strip())


def _parse_structured_sets(sets_list: list) -> Optional[ParsedScore]:
    sets: List[Tuple[int, int]] = []
    a_sets = 0
    b_sets = 0
    a_games = 0
    b_games = 0
    for s in sets_list:
        a = int(s.get("a", 0))
        b = int(s.get("b", 0))
        sets.append((a, b))
        a_games += a
        b_games += b
        if a > b:
            a_sets += 1
        elif b > a:
            b_sets += 1
    return ParsedScore(
        sets=sets,
        team_a_sets_won=a_sets,
        team_b_sets_won=b_sets,
        team_a_games=a_games,
        team_b_games=b_games,
    )


def _parse_score_string(raw: str) -> Optional[ParsedScore]:
    """Parse strings like '8-4', '6-3 4-6 10-7', '6-3, 4-6, 10-7'."""
    # Normalize: replace commas with spaces, collapse whitespace
    normalized = raw.replace(",", " ").strip()
    parts = normalized.split()

    sets: List[Tuple[int, int]] = []
    for part in parts:
        pair = part.split("-")
        if len(pair) != 2:
            return None
        try:
            a = int(pair[0])
            b = int(pair[1])
        except ValueError:
            return None
        sets.append((a, b))

    if not sets:
        return None

    a_sets = sum(1 for a, b in sets if a > b)
    b_sets = sum(1 for a, b in sets if b > a)
    a_games = sum(a for a, _ in sets)
    b_games = sum(b for _, b in sets)

    return ParsedScore(
        sets=sets,
        team_a_sets_won=a_sets,
        team_b_sets_won=b_sets,
        team_a_games=a_games,
        team_b_games=b_games,
    )
