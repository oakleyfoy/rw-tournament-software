"""Match generation for WF_10_SIX_FOUR draw template."""

from __future__ import annotations

from typing import List, Tuple

from app.models.match import Match
from app.services.draw_plan_engine import DrawPlanSpec
from app.services.wf_10_format import (
    FUN_PAIRINGS,
    LOSS_RR_PAIRINGS,
    LOSS_SUN_PAIRINGS,
    REQUIRED_WF_ROUNDS,
    TEAM_COUNT,
    WF_R1_MATCHES,
    WIN_RR_PAIRINGS,
    WIN_SUN_PAIRINGS,
    loss_rank_placeholder,
    win_rank_placeholder,
)
from app.services.wf_pairing import TeamSeed, build_wf_r1_pairings


def _load_event_teams(session, event_id: int):
    from sqlmodel import select

    from app.models.team import Team

    return list(session.exec(select(Team).where(Team.event_id == event_id)).all())


def _team_display_name(team) -> str:
    if not team:
        return "TBD"
    return team.name or getattr(team, "display_name", None) or f"Team {team.id}"


def _participating_teams_for_draw(
    all_teams: list,
    linked_team_ids: List[int],
    warnings: List[str],
) -> list:
    if linked_team_ids:
        by_id = {t.id: t for t in all_teams}
        picked = []
        for tid in linked_team_ids:
            if len(picked) >= TEAM_COUNT:
                break
            t = by_id.get(tid)
            if t is not None:
                picked.append(t)
        if len(picked) >= TEAM_COUNT:
            if len(all_teams) > TEAM_COUNT:
                warnings.append(
                    f"WF_10_SIX_FOUR: using {TEAM_COUNT} linked teams; {len(all_teams)} team rows on this event"
                )
            return picked[:TEAM_COUNT]

    ordered = sorted(
        all_teams,
        key=lambda t: (t.seed if t.seed is not None else 9999, t.id),
    )
    if len(ordered) > TEAM_COUNT:
        warnings.append(f"WF_10_SIX_FOUR: using seeds 1–{TEAM_COUNT}; {len(ordered)} team rows on this event")
    return ordered[:TEAM_COUNT]


def generate_wf_10_matches(
    session,
    version_id: int,
    spec: DrawPlanSpec,
    linked_team_ids: List[int],
) -> Tuple[List[Match], List[str]]:
    matches: List[Match] = []
    warnings: List[str] = []

    if spec.team_count != TEAM_COUNT:
        warnings.append(f"WF_10_SIX_FOUR requires team_count={TEAM_COUNT}, got {spec.team_count}")
        return matches, warnings
    if spec.waterfall_rounds != REQUIRED_WF_ROUNDS:
        warnings.append(f"WF_10_SIX_FOUR requires waterfall_rounds={REQUIRED_WF_ROUNDS}, got {spec.waterfall_rounds}")
        return matches, warnings

    prefix = spec.match_code_prefix
    all_teams = _load_event_teams(session, spec.event_id)
    participating = _participating_teams_for_draw(all_teams, linked_team_ids, warnings)
    if len(participating) < TEAM_COUNT:
        warnings.append(
            f"WF_10_SIX_FOUR: expected {TEAM_COUNT} teams, found {len(participating)} ({len(all_teams)} rows on event)"
        )

    ordered = sorted(
        participating,
        key=lambda t: (t.seed if t.seed is not None else 9999, t.id or 0),
    )
    field = ordered[:TEAM_COUNT]

    # -------------------------------------------------------------------------
    # WF R1 — 10 teams, 5 matches
    # -------------------------------------------------------------------------
    r1_matches: List[Match] = []
    pairing = None
    if len(field) >= TEAM_COUNT:
        seed_teams: List[TeamSeed] = []
        for idx, t in enumerate(field, start=1):
            seed_teams.append(
                TeamSeed(
                    seed=idx,
                    team_id=t.id,
                    avoid_group=getattr(t, "avoid_group", None),
                    display_name=getattr(t, "display_name", None),
                    name=getattr(t, "name", None),
                    rating=getattr(t, "rating", None),
                )
            )
        pairing = build_wf_r1_pairings(seed_teams, len(field))

    team_by_seed = {idx: t for idx, t in enumerate(field, start=1)}
    for i in range(WF_R1_MATCHES):
        if pairing and i < len(pairing.pairs):
            seed_a, seed_b = pairing.pairs[i]
            team_a_id, team_b_id = pairing.team_id_pairs[i]
            name_a, name_b = pairing.name_pairs[i]
            placeholder_a = name_a or f"Seed {seed_a}"
            placeholder_b = name_b or f"Seed {seed_b}"
        else:
            seed_a = i + 1
            seed_b = i + WF_R1_MATCHES + 1
            ta = team_by_seed.get(seed_a)
            tb = team_by_seed.get(seed_b)
            team_a_id = ta.id if ta else None
            team_b_id = tb.id if tb else None
            placeholder_a = _team_display_name(ta) if ta else f"Seed {seed_a}"
            placeholder_b = _team_display_name(tb) if tb else f"Seed {seed_b}"

        m = Match(
            tournament_id=spec.tournament_id,
            event_id=spec.event_id,
            schedule_version_id=version_id,
            match_code=f"{prefix}WF_R1_{i + 1:02d}",
            match_type="WF",
            round_number=1,
            round_index=1,
            sequence_in_round=i + 1,
            team_a_id=team_a_id,
            team_b_id=team_b_id,
            placeholder_side_a=placeholder_a,
            placeholder_side_b=placeholder_b,
            duration_minutes=spec.waterfall_minutes,
        )
        matches.append(m)
        r1_matches.append(m)

    if pairing and pairing.conflicts:
        for c in pairing.conflicts:
            warnings.append(
                f"W_WF_R1_AVOID_GROUP_CONFLICT: seed {c.seed_a} vs seed {c.seed_b} (both group '{c.group}')"
            )

    session.add_all(r1_matches)
    session.flush()

    round_by_tag = {"FRI": 1, "SAT1": 2, "SAT2": 3}

    # -------------------------------------------------------------------------
    # Winners mini-pool RR (placeholders W1..W6)
    # -------------------------------------------------------------------------
    for cp in WIN_RR_PAIRINGS:
        ri = round_by_tag[cp.schedule_tag]
        matches.append(
            Match(
                tournament_id=spec.tournament_id,
                event_id=spec.event_id,
                schedule_version_id=version_id,
                match_code=f"{prefix}WIN_{cp.schedule_tag}_{cp.pool}{cp.sequence:02d}",
                match_type="RR",
                round_number=ri,
                round_index=ri,
                sequence_in_round=cp.sequence,
                placeholder_side_a=win_rank_placeholder(cp.rank_a),
                placeholder_side_b=win_rank_placeholder(cp.rank_b),
                duration_minutes=spec.standard_minutes,
            )
        )

    # -------------------------------------------------------------------------
    # Fun matches (bye vs bye)
    # -------------------------------------------------------------------------
    for cp in FUN_PAIRINGS:
        ri = round_by_tag[cp.schedule_tag]
        matches.append(
            Match(
                tournament_id=spec.tournament_id,
                event_id=spec.event_id,
                schedule_version_id=version_id,
                match_code=f"{prefix}FUN_{cp.schedule_tag}_{cp.sequence:02d}",
                match_type="RR",
                round_number=ri,
                round_index=ri,
                sequence_in_round=10 + cp.sequence,
                placeholder_side_a=win_rank_placeholder(cp.rank_a),
                placeholder_side_b=win_rank_placeholder(cp.rank_b),
                duration_minutes=spec.standard_minutes,
                placement_type="WF10_FUN",
            )
        )

    # -------------------------------------------------------------------------
    # Losers 4-team RR (placeholders L1..L4)
    # -------------------------------------------------------------------------
    for cp in LOSS_RR_PAIRINGS:
        ri = round_by_tag[cp.schedule_tag]
        matches.append(
            Match(
                tournament_id=spec.tournament_id,
                event_id=spec.event_id,
                schedule_version_id=version_id,
                match_code=f"{prefix}LOSS_{cp.schedule_tag}_{cp.sequence:02d}",
                match_type="RR",
                round_number=ri,
                round_index=ri,
                sequence_in_round=20 + cp.sequence,
                placeholder_side_a=loss_rank_placeholder(cp.rank_a),
                placeholder_side_b=loss_rank_placeholder(cp.rank_b),
                duration_minutes=spec.standard_minutes,
            )
        )

    # -------------------------------------------------------------------------
    # Sunday placement
    # -------------------------------------------------------------------------
    for idx, (slot_a, slot_b) in enumerate(WIN_SUN_PAIRINGS, start=1):
        matches.append(
            Match(
                tournament_id=spec.tournament_id,
                event_id=spec.event_id,
                schedule_version_id=version_id,
                match_code=f"{prefix}WIN_SUN_{idx:02d}",
                match_type="PLACEMENT",
                round_number=1,
                round_index=1,
                sequence_in_round=idx,
                placeholder_side_a=slot_a,
                placeholder_side_b=slot_b,
                placement_type="WF10_WIN_CROSS",
                duration_minutes=spec.standard_minutes,
            )
        )

    for idx, (slot_a, slot_b) in enumerate(LOSS_SUN_PAIRINGS, start=1):
        matches.append(
            Match(
                tournament_id=spec.tournament_id,
                event_id=spec.event_id,
                schedule_version_id=version_id,
                match_code=f"{prefix}LOSS_SUN_{idx:02d}",
                match_type="PLACEMENT",
                round_number=1,
                round_index=1,
                sequence_in_round=10 + idx,
                placeholder_side_a=slot_a,
                placeholder_side_b=slot_b,
                placement_type="WF10_LOSS_PLACE",
                duration_minutes=spec.standard_minutes,
            )
        )

    return matches, warnings
