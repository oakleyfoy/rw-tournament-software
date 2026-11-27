"""Round-robin standings used by the desk and by trophy awards.

The sort is the desk rule: wins, then fewer sets lost, then higher game
differential. Name order is only a display order. It does not break a tie
for a trophy. This engine does not project unfinished matches, so it cannot
declare a clinched place before the group is complete.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

from app.models.match import Match
from app.services.score_parser import parse_score


def _retired(score_json) -> bool:
    if not score_json:
        return False
    if isinstance(score_json, dict):
        return "(RET" in str(score_json.get("display") or "").upper()
    if isinstance(score_json, str):
        return "(RET" in score_json.upper()
    return False


def _blank() -> dict:
    return {
        "wins": 0,
        "losses": 0,
        "sets_won": 0,
        "sets_lost": 0,
        "games_won": 0,
        "games_lost": 0,
        "played": 0,
    }


def competitive_key(stats: dict) -> Tuple[int, int, int]:
    """Wins, sets lost, game differential. Name is not part of this key."""
    return (stats["wins"], stats["sets_lost"], stats["games_won"] - stats["games_lost"])


@dataclass
class PoolStandings:
    sorted_rows: List[Tuple[int, dict]]
    warnings: List[dict] = field(default_factory=list)
    complete: bool = False
    official: bool = False


def build_pool_standings(matches: List[Match], display: Callable[[int], str]) -> PoolStandings:
    team_ids = set()
    for match in matches:
        if match.team_a_id:
            team_ids.add(match.team_a_id)
        if match.team_b_id:
            team_ids.add(match.team_b_id)
    rows: Dict[int, dict] = {team_id: _blank() for team_id in team_ids}
    warnings: List[dict] = []
    complete = bool(matches)
    for match in matches:
        status = (match.runtime_status or "SCHEDULED").upper()
        if status != "FINAL" or not match.team_a_id or not match.team_b_id or not match.winner_team_id:
            complete = False
            continue
        a_id = match.team_a_id
        b_id = match.team_b_id
        rows.setdefault(a_id, _blank())
        rows.setdefault(b_id, _blank())
        if match.winner_team_id == a_id:
            rows[a_id]["wins"] += 1
            rows[b_id]["losses"] += 1
        elif match.winner_team_id == b_id:
            rows[b_id]["wins"] += 1
            rows[a_id]["losses"] += 1
        else:
            complete = False
        rows[a_id]["played"] += 1
        rows[b_id]["played"] += 1
        parsed = parse_score(match.score_json)
        if parsed:
            a_sets = parsed.team_a_sets_won
            b_sets = parsed.team_b_sets_won
            a_games = parsed.team_a_games
            b_games = parsed.team_b_games
            if not _retired(match.score_json) and match.winner_team_id == a_id and b_sets > a_sets:
                a_sets, b_sets = b_sets, a_sets
                a_games, b_games = b_games, a_games
            elif not _retired(match.score_json) and match.winner_team_id == b_id and a_sets > b_sets:
                a_sets, b_sets = b_sets, a_sets
                a_games, b_games = b_games, a_games
            rows[a_id]["sets_won"] += a_sets
            rows[a_id]["sets_lost"] += b_sets
            rows[b_id]["sets_won"] += b_sets
            rows[b_id]["sets_lost"] += a_sets
            rows[a_id]["games_won"] += a_games
            rows[a_id]["games_lost"] += b_games
            rows[b_id]["games_won"] += b_games
            rows[b_id]["games_lost"] += a_games
        elif match.score_json:
            warnings.append({"match_number": match.id, "reason": "SCORE_PARSE_FAILED"})
    sorted_rows = sorted(
        rows.items(),
        key=lambda item: (
            -item[1]["wins"],
            item[1]["sets_lost"],
            -(item[1]["games_won"] - item[1]["games_lost"]),
            display(item[0]),
        ),
    )
    official = False
    if complete and len(sorted_rows) >= 2:
        first = competitive_key(sorted_rows[0][1])
        second = competitive_key(sorted_rows[1][1])
        tied_for_first = first == second
        tied_for_second = any(competitive_key(stats) == second for _, stats in sorted_rows[2:])
        official = not tied_for_first and not tied_for_second
    return PoolStandings(sorted_rows=sorted_rows, warnings=warnings, complete=complete, official=official)
