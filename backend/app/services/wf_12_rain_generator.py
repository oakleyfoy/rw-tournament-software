"""Match generation for the 12-team rain draw. Teams are assigned from the manual seed."""

from __future__ import annotations

from typing import List, Optional, Tuple

from app.models.match import Match
from app.services.draw_plan_engine import DrawPlanSpec
from app.services.wf_12_rain_format import (
    FLIGHTS,
    FUN_PAIRINGS,
    GROUP_PAIRINGS,
    PLACEMENT_SLOTS,
    REQUIRED_WF_ROUNDS,
    TEAM_COUNT,
    flight_pool_letters,
    seed_for_flight_rank,
)


def _load_event_teams(session, event_id: int):
    from sqlmodel import select

    from app.models.team import Team

    return list(session.exec(select(Team).where(Team.event_id == event_id)).all())


def _team_label(team) -> str:
    if not team:
        return "TBD"
    return getattr(team, "display_name", None) or team.name or f"Team {team.id}"


def _participating_teams(all_teams: list, linked_team_ids: List[int], warnings: List[str]) -> list:
    if linked_team_ids:
        by_id = {t.id: t for t in all_teams}
        picked = []
        for tid in linked_team_ids:
            if len(picked) >= TEAM_COUNT:
                break
            team = by_id.get(tid)
            if team is not None:
                picked.append(team)
        if len(picked) >= TEAM_COUNT:
            if len(all_teams) > TEAM_COUNT:
                warnings.append(
                    f"WF_12_RAIN_SIX: using {TEAM_COUNT} linked teams; {len(all_teams)} team rows on this event"
                )
            return picked[:TEAM_COUNT]

    ordered = sorted(all_teams, key=lambda t: (t.seed if t.seed is not None else 9999, t.id or 0))
    if len(ordered) > TEAM_COUNT:
        warnings.append(f"WF_12_RAIN_SIX: using the first {TEAM_COUNT} seeds; {len(ordered)} team rows on this event")
    return ordered[:TEAM_COUNT]


def generate_wf_12_rain_matches(
    session,
    version_id: int,
    spec: DrawPlanSpec,
    linked_team_ids: List[int],
) -> Tuple[List[Match], List[str]]:
    matches: List[Match] = []
    warnings: List[str] = []

    if spec.team_count != TEAM_COUNT:
        warnings.append(f"WF_12_RAIN_SIX requires team_count={TEAM_COUNT}, got {spec.team_count}")
        return matches, warnings
    if spec.waterfall_rounds != REQUIRED_WF_ROUNDS:
        warnings.append(
            f"WF_12_RAIN_SIX requires waterfall_rounds={REQUIRED_WF_ROUNDS}, got {spec.waterfall_rounds}"
        )
        return matches, warnings

    prefix = spec.match_code_prefix
    all_teams = _load_event_teams(session, spec.event_id)
    participating = _participating_teams(all_teams, linked_team_ids, warnings)
    if len(participating) < TEAM_COUNT:
        warnings.append(
            f"WF_12_RAIN_SIX: expected {TEAM_COUNT} teams, found {len(participating)} ({len(all_teams)} rows on event)"
        )

    ordered = sorted(participating, key=lambda t: (t.seed if t.seed is not None else 9999, t.id or 0))
    by_seed = {idx: team for idx, team in enumerate(ordered[:TEAM_COUNT], start=1)}
    round_by_tag = {"FRI": 1, "SAT1": 2, "SAT2": 3}

    def team_at(flight: str, rank: int):
        return by_seed.get(seed_for_flight_rank(flight, rank))

    def side_fields(team, fallback: str) -> Tuple[Optional[int], str]:
        if team is None:
            return None, fallback
        return team.id, _team_label(team)

    for flight in FLIGHTS:
        high_letter, low_letter = flight_pool_letters(flight)
        for pairing in GROUP_PAIRINGS:
            letter = high_letter if pairing.side == "HIGH" else low_letter
            team_a = team_at(flight, pairing.rank_a)
            team_b = team_at(flight, pairing.rank_b)
            team_a_id, label_a = side_fields(team_a, f"Seed {seed_for_flight_rank(flight, pairing.rank_a)}")
            team_b_id, label_b = side_fields(team_b, f"Seed {seed_for_flight_rank(flight, pairing.rank_b)}")
            round_index = round_by_tag[pairing.schedule_tag]
            matches.append(
                Match(
                    tournament_id=spec.tournament_id,
                    event_id=spec.event_id,
                    schedule_version_id=version_id,
                    match_code=f"{prefix}{flight}_{pairing.schedule_tag}_{letter}{pairing.sequence:02d}",
                    match_type="RR",
                    round_number=round_index,
                    round_index=round_index,
                    sequence_in_round=pairing.sequence,
                    team_a_id=team_a_id,
                    team_b_id=team_b_id,
                    placeholder_side_a=label_a,
                    placeholder_side_b=label_b,
                    duration_minutes=spec.standard_minutes,
                )
            )

        for pairing in FUN_PAIRINGS:
            team_a = team_at(flight, pairing.rank_a)
            team_b = team_at(flight, pairing.rank_b)
            team_a_id, label_a = side_fields(team_a, f"Seed {seed_for_flight_rank(flight, pairing.rank_a)}")
            team_b_id, label_b = side_fields(team_b, f"Seed {seed_for_flight_rank(flight, pairing.rank_b)}")
            round_index = round_by_tag[pairing.schedule_tag]
            matches.append(
                Match(
                    tournament_id=spec.tournament_id,
                    event_id=spec.event_id,
                    schedule_version_id=version_id,
                    match_code=f"{prefix}{flight}_FUN_{pairing.schedule_tag}_{pairing.sequence:02d}",
                    match_type="RR",
                    round_number=round_index,
                    round_index=round_index,
                    sequence_in_round=10 + pairing.sequence,
                    team_a_id=team_a_id,
                    team_b_id=team_b_id,
                    placeholder_side_a=label_a,
                    placeholder_side_b=label_b,
                    duration_minutes=spec.standard_minutes,
                    placement_type="RAIN_FUN",
                )
            )

        for idx, (high_slot, low_slot) in enumerate(PLACEMENT_SLOTS, start=1):
            matches.append(
                Match(
                    tournament_id=spec.tournament_id,
                    event_id=spec.event_id,
                    schedule_version_id=version_id,
                    match_code=f"{prefix}{flight}_SUN_{idx:02d}",
                    match_type="PLACEMENT",
                    round_number=1,
                    round_index=1,
                    sequence_in_round=idx if flight == "TOP" else 10 + idx,
                    placeholder_side_a=f"{high_letter}{high_slot}",
                    placeholder_side_b=f"{low_letter}{low_slot}",
                    placement_type="RAIN_TOP_CROSS" if flight == "TOP" else "RAIN_BOT_CROSS",
                    duration_minutes=spec.standard_minutes,
                )
            )

    return matches, warnings
