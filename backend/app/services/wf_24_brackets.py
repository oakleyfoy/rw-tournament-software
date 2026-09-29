"""24-team waterfall into three seeded brackets.

Two waterfall rounds, then rank the field 1-24 by wins and tiebreakers.
Seeds 1-8, 9-16, and 17-24 each fill an 8-team bracket.
"""

from __future__ import annotations

import json
from typing import Optional

from sqlmodel import Session, select

from app.models.event import Event
from app.models.match import Match
from app.models.team import Team
from app.services.score_parser import parse_score
from app.utils.wf_seeding import WFTeamResult, wf_overall_seed_key

WFSEED_PREFIX = "WFSEED:"


def event_uses_wf24_brackets(event: Optional[Event]) -> bool:
    if not event or (event.team_count or 0) != 24:
        return False
    raw = event.draw_plan_json
    if not raw:
        return False
    try:
        plan = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return False
    template = str(plan.get("template_type") or "").upper()
    return template == "WF_TO_BRACKETS_8"


def maybe_place_wf24_brackets(session: Session, match: Match) -> int:
    """Fill bracket quarterfinals once every waterfall match in the event is final."""
    if (match.match_type or "").upper() != "WF":
        return 0
    event = session.get(Event, match.event_id)
    if not event_uses_wf24_brackets(event):
        return 0
    return place_wf24_brackets(session, match.tournament_id, match.schedule_version_id, match.event_id)


def place_wf24_brackets(session: Session, tournament_id: int, version_id: int, event_id: int) -> int:
    wf_matches = session.exec(
        select(Match).where(
            Match.tournament_id == tournament_id,
            Match.schedule_version_id == version_id,
            Match.event_id == event_id,
            Match.match_type == "WF",
        )
    ).all()
    if not wf_matches:
        return 0
    if any((m.runtime_status or "").upper() != "FINAL" or m.winner_team_id is None for m in wf_matches):
        return 0

    ranked = _rank_teams(session, version_id, event_id, wf_matches)
    if len(ranked) != 24:
        return 0
    seed_to_team = {seed: team_id for seed, team_id in enumerate(ranked, start=1)}

    bracket_matches = session.exec(
        select(Match).where(
            Match.tournament_id == tournament_id,
            Match.schedule_version_id == version_id,
            Match.event_id == event_id,
            Match.match_type == "MAIN",
            Match.round_index == 1,
        )
    ).all()

    updated = 0
    for bracket_match in bracket_matches:
        changed = False
        for side in ("a", "b"):
            placeholder = getattr(bracket_match, f"placeholder_side_{side}") or ""
            if not placeholder.startswith(WFSEED_PREFIX):
                continue
            try:
                seed = int(placeholder[len(WFSEED_PREFIX) :])
            except ValueError:
                continue
            team_id = seed_to_team.get(seed)
            if team_id is None:
                continue
            field = f"team_{side}_id"
            if getattr(bracket_match, field) != team_id:
                setattr(bracket_match, field, team_id)
                changed = True
        if changed:
            session.add(bracket_match)
            updated += 1
    if updated:
        session.commit()
    return updated


def _rank_teams(session: Session, version_id: int, event_id: int, wf_matches: list[Match]) -> list[int]:
    results: dict[int, WFTeamResult] = {}

    def ensure(team_id: int) -> WFTeamResult:
        row = results.get(team_id)
        if row is None:
            row = WFTeamResult(team_id=team_id, bucket_rank=0)
            results[team_id] = row
        return row

    for wf_match in wf_matches:
        if not wf_match.team_a_id or not wf_match.team_b_id or not wf_match.winner_team_id:
            continue
        winner_id = wf_match.winner_team_id
        loser_id = wf_match.team_b_id if winner_id == wf_match.team_a_id else wf_match.team_a_id
        winner = ensure(winner_id)
        loser = ensure(loser_id)
        winner.wf_matches_won += 1

        parsed = parse_score(wf_match.score_json)
        if not parsed:
            continue
        a_games = parsed.team_a_games
        b_games = parsed.team_b_games
        if winner_id == wf_match.team_a_id and b_games > a_games:
            a_games, b_games = b_games, a_games
        elif winner_id == wf_match.team_b_id and a_games > b_games:
            a_games, b_games = b_games, a_games
        winner_games = a_games if winner_id == wf_match.team_a_id else b_games
        loser_games = b_games if winner_id == wf_match.team_a_id else a_games
        winner.wf_game_diff += winner_games - loser_games
        loser.wf_game_diff += loser_games - winner_games
        if (wf_match.round_number or 0) >= 2:
            winner.wf2_game_diff += winner_games - loser_games
            loser.wf2_game_diff += loser_games - winner_games

    team_ids = list(results)
    teams = session.exec(select(Team).where(Team.id.in_(team_ids))).all() if team_ids else []
    for team in teams:
        row = results.get(team.id)
        if row is not None and team.seed is not None:
            row.original_seed = team.seed

    return sorted(results, key=lambda team_id: wf_overall_seed_key(results[team_id], version_id, event_id))
