"""Round-robin standings used by the desk and by trophy awards.

The sort is the desk rule: wins, then fewer sets lost, then higher game
differential. Name order is only a display order. It does not break a tie
for a trophy.

Trophy eligibility projects every legal winner and the score shapes accepted
for that match length. A team is eliminated only when every one of those
results leaves two teams strictly ahead. A clinch is recorded internally
when every result gives the team a unique first or unique second. Awards
still wait until the pool is complete and the same keys are unique.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

from app.models.match import Match
from app.services.score_parser import parse_score, scoring_mode_for_match_type


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


@dataclass
class PoolOutlook:
    """Projected trophy places for one round-robin pool.

    `guaranteed` is internal. It does not authorize handing a trophy out
    before `build_pool_standings` says the pool is official.
    """

    eligible: set[int] = field(default_factory=set)
    eliminated: set[int] = field(default_factory=set)
    guaranteed_champion: Optional[int] = None
    guaranteed_runner_up: Optional[int] = None


def _score_shapes(match_type: str) -> List[Tuple[int, int, int]]:
    """Legal (winner sets lost, loser sets lost, winner game differential)."""
    if scoring_mode_for_match_type(match_type) == "PRO_SET_8":
        texts = ["8-0", "9-8"]
    else:
        texts = ["6-0, 6-0", "7-6, 7-6", "6-4, 0-6, 1-0", "7-5, 5-7, 1-0"]
    shapes: List[Tuple[int, int, int]] = []
    for text in texts:
        parsed = parse_score({"display": text})
        if not parsed or parsed.team_a_sets_won <= parsed.team_b_sets_won:
            continue
        shapes.append(
            (
                parsed.team_b_sets_won,
                parsed.team_a_sets_won,
                parsed.team_a_games - parsed.team_b_games,
            )
        )
    return shapes or [(0, 1, 1)]


def project_pool_outlook(matches: List[Match]) -> PoolOutlook:
    """Whether each team can still finish first or second under the desk tiebreak."""
    teams = set()
    for match in matches:
        if match.team_a_id:
            teams.add(match.team_a_id)
        if match.team_b_id:
            teams.add(match.team_b_id)
    outlook = PoolOutlook(eligible=set(teams))
    if len(teams) < 2:
        return outlook
    if any(not match.team_a_id or not match.team_b_id for match in matches):
        return outlook

    base = {team_id: [0, 0, 0] for team_id in teams}
    remaining: List[tuple] = []
    for match in matches:
        status = (match.runtime_status or "").upper()
        winner = match.winner_team_id
        if status == "FINAL" and winner in (match.team_a_id, match.team_b_id):
            loser = match.team_b_id if winner == match.team_a_id else match.team_a_id
            parsed = parse_score(match.score_json)
            if parsed:
                if winner == match.team_a_id:
                    winner_sets_lost = parsed.team_b_sets_won
                    loser_sets_lost = parsed.team_a_sets_won
                    diff = parsed.team_a_games - parsed.team_b_games
                else:
                    winner_sets_lost = parsed.team_a_sets_won
                    loser_sets_lost = parsed.team_b_sets_won
                    diff = parsed.team_b_games - parsed.team_a_games
            else:
                winner_sets_lost, loser_sets_lost, diff = 0, 1, 1
            base[winner][0] += 1
            base[winner][1] += winner_sets_lost
            base[loser][1] += loser_sets_lost
            base[winner][2] += diff
            base[loser][2] -= diff
            continue
        shapes = _score_shapes(match.match_type or "")
        remaining.append((match.team_a_id, match.team_b_id, shapes))

    if len(remaining) > 3:
        return _wins_only_outlook(teams, base, remaining)

    can_place = {team_id: False for team_id in teams}
    always_champion = {team_id: True for team_id in teams}
    always_runner = {team_id: True for team_id in teams}
    scenarios = 0

    def visit(index: int) -> None:
        nonlocal scenarios
        if index == len(remaining):
            scenarios += 1
            order = sorted(teams, key=lambda team_id: (-base[team_id][0], base[team_id][1], -base[team_id][2], team_id))
            keys = [(-base[team_id][0], base[team_id][1], -base[team_id][2]) for team_id in order]
            for team_id in teams:
                key = (-base[team_id][0], base[team_id][1], -base[team_id][2])
                ahead = sum(1 for other in teams if other != team_id and (-base[other][0], base[other][1], -base[other][2]) < key)
                if ahead < 2:
                    can_place[team_id] = True
                unique_first = keys[0] != keys[1] and order[0] == team_id
                unique_second = len(order) > 2 and keys[0] != keys[1] and keys[1] != keys[2] and order[1] == team_id
                if len(order) == 2:
                    unique_second = keys[0] != keys[1] and order[1] == team_id
                if not unique_first:
                    always_champion[team_id] = False
                if not unique_second:
                    always_runner[team_id] = False
            return
        side_a, side_b, shapes = remaining[index]
        for winner, loser in ((side_a, side_b), (side_b, side_a)):
            for winner_sets_lost, loser_sets_lost, diff in shapes:
                base[winner][0] += 1
                base[winner][1] += winner_sets_lost
                base[loser][1] += loser_sets_lost
                base[winner][2] += diff
                base[loser][2] -= diff
                visit(index + 1)
                base[winner][0] -= 1
                base[winner][1] -= winner_sets_lost
                base[loser][1] -= loser_sets_lost
                base[winner][2] -= diff
                base[loser][2] += diff

    visit(0)
    if scenarios == 0:
        return outlook
    outlook.eligible = {team_id for team_id, placed in can_place.items() if placed}
    outlook.eliminated = teams - outlook.eligible
    champions = [team_id for team_id, locked in always_champion.items() if locked]
    runners = [team_id for team_id, locked in always_runner.items() if locked]
    if len(champions) == 1:
        outlook.guaranteed_champion = champions[0]
    if len(runners) == 1 and outlook.guaranteed_champion != runners[0]:
        outlook.guaranteed_runner_up = runners[0]
    return outlook


def _wins_only_outlook(teams: set[int], base: Dict[int, List[int]], remaining: List[tuple]) -> PoolOutlook:
    """Exact on wins when too many matches remain to enumerate score shapes."""
    can_place = {team_id: False for team_id in teams}
    always_champion = {team_id: True for team_id in teams}
    always_runner = {team_id: True for team_id in teams}

    def visit(index: int) -> None:
        if index == len(remaining):
            wins = {team_id: base[team_id][0] for team_id in teams}
            ordered = sorted(teams, key=lambda team_id: (-wins[team_id], team_id))
            for team_id in teams:
                ahead = sum(1 for other, count in wins.items() if other != team_id and count > wins[team_id])
                if ahead < 2:
                    can_place[team_id] = True
                unique_first = wins[ordered[0]] > wins[ordered[1]] and ordered[0] == team_id
                second_id = ordered[1]
                others = [wins[team] for team in ordered[2:]]
                unique_second = (
                    wins[ordered[0]] > wins[second_id]
                    and (not others or wins[second_id] > max(others))
                    and second_id == team_id
                )
                if not unique_first:
                    always_champion[team_id] = False
                if not unique_second:
                    always_runner[team_id] = False
            return
        side_a, side_b, _shapes = remaining[index]
        for winner in (side_a, side_b):
            base[winner][0] += 1
            visit(index + 1)
            base[winner][0] -= 1

    visit(0)
    outlook = PoolOutlook(eligible={team_id for team_id, placed in can_place.items() if placed})
    outlook.eliminated = teams - outlook.eligible
    champions = [team_id for team_id, locked in always_champion.items() if locked]
    runners = [team_id for team_id, locked in always_runner.items() if locked]
    if len(champions) == 1:
        outlook.guaranteed_champion = champions[0]
    if len(runners) == 1:
        outlook.guaranteed_runner_up = runners[0]
    return outlook
