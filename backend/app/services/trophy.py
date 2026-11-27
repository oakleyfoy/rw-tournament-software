"""Championship finals and round-robin trophy awards.

A championship final is a MAIN match whose two sides both come from winners
and from which no later match takes a winner. That is the end of one main-draw
bracket. Consolation finals are a different match type, or, in the 14-team
flight, MAIN rows that are not fed by two winner links. Quarterfinals and
semifinals still have a winner advancing out of them. Placement matches are
not MAIN.

Round-robin groups have no single final. A team playing its last scheduled
pool match is only marked as such. Championship and runner-up are taken from
the existing standings sort after every match in that pool is final and the
top two places are not tied. The standings engine does not compute a clinch
before the group is finished, so trophies are not awarded early.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Dict, List, Optional

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.models.event import Event
from app.models.match import Match
from app.models.player import Player
from app.models.team import Team
from app.models.team_player import TeamPlayer
from app.models.trophy_distribution import TrophyDistribution
from app.services.rr_match_codes import (
    is_public_rr_pool_match_code,
    is_rain_placement_code,
    is_wf10_sunday_placement_code,
    rr_pool_code_for_match,
)
from app.services.rr_standings import build_pool_standings

_NON_CHAMPIONSHIP_POOLS = {"FUN", "TOPFUN", "BOTFUN"}


def championship_final_ids(matches: List[Match]) -> set[int]:
    consumed_by_winner: set[int] = set()
    for match in matches:
        if (match.source_a_role or "").upper() == "WINNER" and match.source_match_a_id:
            consumed_by_winner.add(match.source_match_a_id)
        if (match.source_b_role or "").upper() == "WINNER" and match.source_match_b_id:
            consumed_by_winner.add(match.source_match_b_id)
    finals: set[int] = set()
    for match in matches:
        if (match.match_type or "").upper() != "MAIN" or match.id is None:
            continue
        if (match.source_a_role or "").upper() != "WINNER" or (match.source_b_role or "").upper() != "WINNER":
            continue
        if not match.source_match_a_id or not match.source_match_b_id:
            continue
        if match.id in consumed_by_winner:
            continue
        finals.add(match.id)
    return finals


def is_championship_rr_match(match: Match) -> bool:
    if (match.match_type or "").upper() != "RR":
        return False
    if getattr(match, "placement_type", None):
        return False
    code = match.match_code or ""
    if not is_public_rr_pool_match_code(code):
        return False
    upper = code.upper()
    if "_LOSS_" in upper or "_FUN_" in upper or "_CONS_" in upper:
        return False
    if is_rain_placement_code(code) or is_wf10_sunday_placement_code(code):
        return False
    pool = rr_pool_code_for_match(code)
    return bool(pool) and pool not in _NON_CHAMPIONSHIP_POOLS


def rr_last_match_teams(matches: List[Match]) -> Dict[int, List[int]]:
    """Team ids for whom this unfinished match is their last pool match."""
    pools: Dict[tuple, List[Match]] = defaultdict(list)
    for match in matches:
        if not is_championship_rr_match(match):
            continue
        pool = rr_pool_code_for_match(match.match_code)
        pools[(match.event_id, pool)].append(match)
    marks: Dict[int, List[int]] = {}
    for group in pools.values():
        remaining: Dict[int, List[Match]] = defaultdict(list)
        for match in group:
            if (match.runtime_status or "").upper() == "FINAL":
                continue
            for team_id in (match.team_a_id, match.team_b_id):
                if team_id:
                    remaining[team_id].append(match)
        for team_id, open_matches in remaining.items():
            if len(open_matches) != 1 or open_matches[0].id is None:
                continue
            marks.setdefault(open_matches[0].id, []).append(team_id)
    return marks


def _final_places(match: Match) -> Optional[tuple[int, int]]:
    if (match.runtime_status or "").upper() != "FINAL":
        return None
    winner = match.winner_team_id
    if winner not in (match.team_a_id, match.team_b_id):
        return None
    runner = match.team_b_id if winner == match.team_a_id else match.team_a_id
    if runner is None:
        return None
    return winner, runner


def _award_key(kind: str, identity: str, role: str) -> str:
    return f"{kind}:{identity}:{role}"


def _team_name(team: Optional[Team], team_id: int) -> str:
    if team is None:
        return f"Team {team_id}"
    return team.display_name or team.name or f"Team {team_id}"


def _player_names(session: Session, team_ids: List[int]) -> Dict[int, List[str]]:
    if not team_ids:
        return {}
    links = session.exec(select(TeamPlayer).where(TeamPlayer.team_id.in_(team_ids))).all()
    player_ids = [link.player_id for link in links]
    players = session.exec(select(Player).where(Player.id.in_(player_ids))).all() if player_ids else []
    by_id = {player.id: player.full_name for player in players}
    grouped: Dict[int, List[tuple]] = defaultdict(list)
    for link in links:
        grouped[link.team_id].append((link.lineup_slot or 99, by_id.get(link.player_id) or ""))
    return {
        team_id: [name for _, name in sorted(slots) if name]
        for team_id, slots in grouped.items()
    }


def _distribution_map(session: Session, tournament_id: int) -> Dict[str, TrophyDistribution]:
    rows = session.exec(select(TrophyDistribution).where(TrophyDistribution.tournament_id == tournament_id)).all()
    return {row.award_key: row for row in rows}


def _award_payload(key: str, role: str, team_id: int, teams: Dict[int, Team], players: Dict[int, List[str]], saved: Dict[str, TrophyDistribution]) -> dict:
    row = saved.get(key)
    review = bool(row and row.team_id != team_id)
    distributed = bool(row and row.team_id == team_id)
    confirmed = teams.get(row.team_id) if row else None
    return {
        "award_key": key,
        "role": role,
        "team_id": team_id,
        "team_name": _team_name(teams.get(team_id), team_id),
        "players": players.get(team_id) or [],
        "distributed": distributed,
        "review_required": review,
        "confirmed_team_id": row.team_id if row else None,
        "confirmed_team_name": _team_name(confirmed, row.team_id) if row else None,
    }


def trophy_board(session: Session, tournament_id: int, matches: List[Match]) -> dict:
    finals = championship_final_ids(matches)
    saved = _distribution_map(session, tournament_id)
    events = {
        event.id: event
        for event in session.exec(select(Event).where(Event.tournament_id == tournament_id)).all()
    }
    team_ids: set[int] = set()
    final_rows = []
    for match in matches:
        if match.id not in finals:
            continue
        places = _final_places(match)
        if not places:
            continue
        team_ids.update(places)
        event = events.get(match.event_id)
        final_rows.append((match, event, places))
    groups: Dict[tuple, List[Match]] = defaultdict(list)
    for match in matches:
        if not is_championship_rr_match(match):
            continue
        pool = rr_pool_code_for_match(match.match_code)
        groups[(match.event_id, pool)].append(match)
    group_rows = []
    for key, pool_matches in groups.items():
        built = build_pool_standings(pool_matches, lambda team_id: str(team_id))
        if not built.complete:
            continue
        event = events.get(key[0])
        champion_id = runner_id = None
        if built.official:
            champion_id = built.sorted_rows[0][0]
            runner_id = built.sorted_rows[1][0]
            team_ids.update((champion_id, runner_id))
        group_rows.append((key, event, pool_matches, built, champion_id, runner_id))
    teams = {
        team.id: team
        for team in (session.exec(select(Team).where(Team.id.in_(list(team_ids)))).all() if team_ids else [])
    }
    players = _player_names(session, list(team_ids))
    from app.routes.desk import _derive_division

    final_payload = []
    pending = 0
    for match, event, (champion_id, runner_id) in final_rows:
        division = _derive_division(match.match_code or "", match.match_type or "")
        awards = []
        for role, team_id in (("champion", champion_id), ("runner_up", runner_id)):
            payload = _award_payload(
                _award_key("main", str(match.id), role),
                role,
                team_id,
                teams,
                players,
                saved,
            )
            if not payload["distributed"]:
                pending += 1
            awards.append(payload)
        final_payload.append(
            {
                "match_id": match.id,
                "match_code": match.match_code,
                "event_name": event.name if event else "",
                "division_name": division,
                "awards": awards,
            }
        )
    group_payload = []
    for (event_id, pool), event, pool_matches, built, champion_id, runner_id in group_rows:
        sample = pool_matches[0]
        division = _derive_division(sample.match_code or "", "RR")
        awards = []
        if champion_id and runner_id:
            for role, team_id in (("champion", champion_id), ("runner_up", runner_id)):
                payload = _award_payload(
                    _award_key("rr", f"{event_id}:{pool}", role),
                    role,
                    team_id,
                    teams,
                    players,
                    saved,
                )
                if not payload["distributed"]:
                    pending += 1
                awards.append(payload)
        group_payload.append(
            {
                "event_id": event_id,
                "pool": pool,
                "event_name": event.name if event else "",
                "division_name": division,
                "official": built.official,
                "unresolved_reason": None if built.official else "Tiebreak Review Required",
                "awards": awards,
            }
        )
    return {"finals": final_payload, "groups": group_payload, "pending": pending}


def pending_award_count(session: Session, tournament_id: int, matches: List[Match]) -> int:
    return int(trophy_board(session, tournament_id, matches)["pending"])


def _current_award_team(session: Session, tournament_id: int, version_id: int, award_key: str) -> Optional[int]:
    matches = session.exec(
        select(Match).where(Match.tournament_id == tournament_id, Match.schedule_version_id == version_id)
    ).all()
    board = trophy_board(session, tournament_id, matches)
    for section in ("finals", "groups"):
        for item in board[section]:
            for award in item["awards"]:
                if award["award_key"] == award_key:
                    return award["team_id"]
    return None


def mark_distributed(session: Session, tournament_id: int, version_id: int, award_key: str, team_id: int) -> TrophyDistribution:
    current = _current_award_team(session, tournament_id, version_id, award_key)
    if current is None:
        raise ValueError("That trophy is not ready to distribute")
    if current != team_id:
        raise ValueError("Trophy confirmation does not match the current result")
    existing = session.exec(
        select(TrophyDistribution).where(
            TrophyDistribution.tournament_id == tournament_id,
            TrophyDistribution.award_key == award_key,
        )
    ).first()
    if existing and existing.team_id == team_id:
        raise ValueError("Trophies are already marked distributed")
    if existing and existing.team_id != team_id:
        raise ValueError("Review the previous trophy confirmation before marking a different team")
    row = TrophyDistribution(
        tournament_id=tournament_id,
        award_key=award_key,
        team_id=team_id,
        role="champion" if award_key.endswith(":champion") else "runner_up",
        distributed_at=datetime.utcnow(),
    )
    session.add(row)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ValueError("Trophies are already marked distributed") from exc
    session.refresh(row)
    return row


def undo_distribution(session: Session, tournament_id: int, award_key: str) -> None:
    row = session.exec(
        select(TrophyDistribution).where(
            TrophyDistribution.tournament_id == tournament_id,
            TrophyDistribution.award_key == award_key,
        )
    ).first()
    if row is None:
        return
    session.delete(row)
    session.commit()
