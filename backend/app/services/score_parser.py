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


def validate_score_for_duration(score_text: str, duration_minutes: int) -> Tuple[bool, Optional[str]]:
    """Validate user-entered score text against the match scoring format.

    Duration mapping:
      <=35  -> PRO_SET_4
      <=60  -> PRO_SET_8
      >60   -> REGULAR (best-of-3 with 3rd set match tiebreak 1-0)
    """
    sets = _parse_sets_from_raw(score_text)
    if not sets:
        return False, "Invalid score format. Use scores like '8-6' or '6-4, 7-5'."

    modes = scoring_modes_for_duration(duration_minutes)
    if modes == ["PRO_SET_4"]:
        if not _is_valid_pro_set_4_match(sets):
            return False, (
                "Invalid score for 4-game pro set. Allowed set scores: "
                "4-0, 4-1, 4-2, 5-3, or 5-4."
            )
        return True, None

    if modes == ["PRO_SET_8", "REGULAR"]:
        if _is_valid_pro_set_8_match(sets) or _is_valid_regular_match(sets):
            return True, None
        return False, (
            "Invalid score for this match. Allowed scores are either: "
            "8-game pro set (8-0 through 8-6, 9-7, 9-8) "
            "or regular scoring (6-0..6-4, 7-5, 7-6; if split, third set is 1-0)."
        )

    if modes == ["PRO_SET_8"]:
        if not _is_valid_pro_set_8_match(sets):
            return False, (
                "Invalid score for 8-game pro set. Allowed set scores: "
                "8-0 through 8-6, plus 9-7 or 9-8."
            )
        return True, None

    # REGULAR
    if not _is_valid_regular_match(sets):
        return False, (
            "Invalid score for regular scoring. "
            "Use two sets with scores 6-0..6-4, 7-5, or 7-6; "
            "if sets are split, add a third set of 1-0."
        )
    return True, None


def scoring_modes_for_duration(duration_minutes: int) -> List[str]:
    """Infer acceptable scoring modes from duration.

    35-minute blocks are strictly 4-game pro sets.
    60-minute blocks allow either 8-game pro set or regular sets.
    90+/105+/120+ blocks are regular sets.
    """
    if duration_minutes <= 35:
        return ["PRO_SET_4"]
    if duration_minutes <= 60:
        return ["PRO_SET_8", "REGULAR"]
    return ["REGULAR"]


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
    sets = _parse_sets_from_raw(raw)

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


def _parse_sets_from_raw(raw: str) -> Optional[List[Tuple[int, int]]]:
    """Parse text into list of (a,b) set scores."""
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
        if a < 0 or b < 0:
            return None
        sets.append((a, b))
    return sets if sets else None


def _is_valid_pro_set_8(score: Tuple[int, int]) -> bool:
    a, b = score
    if a == b:
        return False
    winner = max(a, b)
    loser = min(a, b)
    if winner == 8 and 0 <= loser <= 6:
        return True
    return winner == 9 and loser in (7, 8)


def _is_valid_pro_set_4(score: Tuple[int, int]) -> bool:
    a, b = score
    if a == b:
        return False
    winner = max(a, b)
    loser = min(a, b)
    if winner == 4 and 0 <= loser <= 2:
        return True
    return winner == 5 and loser in (3, 4)


def _is_valid_regular_set(score: Tuple[int, int]) -> bool:
    a, b = score
    if a == b:
        return False
    winner = max(a, b)
    loser = min(a, b)
    if winner == 6 and 0 <= loser <= 4:
        return True
    return winner == 7 and loser in (5, 6)


def _is_valid_pro_set_8_match(sets: List[Tuple[int, int]]) -> bool:
    return len(sets) == 1 and _is_valid_pro_set_8(sets[0])


def _is_valid_pro_set_4_match(sets: List[Tuple[int, int]]) -> bool:
    return len(sets) == 1 and _is_valid_pro_set_4(sets[0])


def _is_valid_regular_match(sets: List[Tuple[int, int]]) -> bool:
    if len(sets) not in (2, 3):
        return False

    first_two = sets[:2]
    if not all(_is_valid_regular_set(s) for s in first_two):
        return False

    a_first_two = sum(1 for a, b in first_two if a > b)
    b_first_two = sum(1 for a, b in first_two if b > a)

    if len(sets) == 2:
        # Straight-sets only for two-set submission.
        return not (a_first_two == 1 and b_first_two == 1)

    third = sets[2]
    if third not in ((1, 0), (0, 1)):
        return False
    # Third set only valid when first two are split.
    return a_first_two == 1 and b_first_two == 1
