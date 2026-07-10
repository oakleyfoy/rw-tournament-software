"""Match generation for WF_14_TOP2_BYE draw template."""

from __future__ import annotations

from typing import List, Optional, Tuple

from app.models.match import Match
from app.services.draw_plan_engine import DrawPlanSpec
from app.services.draw_plan_rules import rr_pairings_by_round
from app.services.wf_14_format import (
    CONS_PLACEMENT_PAIRINGS,
    CONS_REGULAR_PAIRINGS,
    REQUIRED_WF_ROUNDS,
    TEAM_COUNT,
    WF_R1_MATCHES,
    cons_loser_placeholder,
    select_top_two_bye_teams,
    teams_for_wf_r1,
)
from app.services.wf_pairing import TeamSeed, build_wf_r1_pairings
from app.utils.rr_wiring import wire_rr_match_placeholders


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
    """Use exactly TEAM_COUNT teams; ignore extra rows on the event (bad imports / duplicates)."""
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
                    f"WF_14_TOP2_BYE: using {TEAM_COUNT} linked teams; {len(all_teams)} team rows on this event"
                )
            return picked[:TEAM_COUNT]

    ordered = sorted(
        all_teams,
        key=lambda t: (t.seed if t.seed is not None else 9999, t.id),
    )
    if len(ordered) > TEAM_COUNT:
        warnings.append(f"WF_14_TOP2_BYE: using seeds 1–{TEAM_COUNT}; {len(ordered)} team rows on this event")
    return ordered[:TEAM_COUNT]


def generate_wf_14_matches(
    session,
    version_id: int,
    spec: DrawPlanSpec,
    linked_team_ids: List[int],
) -> Tuple[List[Match], List[str]]:
    matches: List[Match] = []
    warnings: List[str] = []

    if spec.team_count != TEAM_COUNT:
        warnings.append(f"WF_14_TOP2_BYE requires team_count={TEAM_COUNT}, got {spec.team_count}")
        return matches, warnings
    if spec.waterfall_rounds != REQUIRED_WF_ROUNDS:
        warnings.append(f"WF_14_TOP2_BYE requires waterfall_rounds={REQUIRED_WF_ROUNDS}, got {spec.waterfall_rounds}")
        return matches, warnings

    prefix = spec.match_code_prefix
    all_teams = _load_event_teams(session, spec.event_id)
    participating = _participating_teams_for_draw(all_teams, linked_team_ids, warnings)
    if len(participating) < TEAM_COUNT:
        warnings.append(
            f"WF_14_TOP2_BYE: expected {TEAM_COUNT} teams, found {len(participating)} ({len(all_teams)} rows on event)"
        )

    bye_a, bye_b = select_top_two_bye_teams(participating)
    bye_ids = frozenset(t.id for t in (bye_a, bye_b) if t and t.id is not None)
    r1_teams = teams_for_wf_r1(participating, bye_ids)
    r1_field = r1_teams[: WF_R1_MATCHES * 2]

    # -------------------------------------------------------------------------
    # WF R1 — 12 teams, 6 matches (seeds 1–12 within playing field for pairing)
    # -------------------------------------------------------------------------
    r1_matches: List[Match] = []
    pairing = None
    if len(r1_field) >= WF_R1_MATCHES * 2:
        seed_teams: List[TeamSeed] = []
        for idx, t in enumerate(r1_field, start=1):
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
        pairing = build_wf_r1_pairings(seed_teams, len(r1_field))
    team_by_seed = {idx: t for idx, t in enumerate(r1_teams, start=1)}

    for i in range(WF_R1_MATCHES):
        if pairing and i < len(pairing.pairs):
            seed_a, seed_b = pairing.pairs[i]
            team_a_id, team_b_id = pairing.team_id_pairs[i]
            name_a, name_b = pairing.name_pairs[i]
            placeholder_a = name_a or f"Seed {seed_a}"
            placeholder_b = name_b or f"Seed {seed_b}"
        else:
            half = 6
            seed_a = i + 1
            seed_b = i + half + 1
            ta = team_by_seed.get(seed_a)
            tb = team_by_seed.get(seed_b)
            team_a_id = ta.id if ta else None
            team_b_id = tb.id if tb else None
            placeholder_a = _team_display_name(ta) if ta else f"PlaySeed {seed_a}"
            placeholder_b = _team_display_name(tb) if tb else f"PlaySeed {seed_b}"

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

    # -------------------------------------------------------------------------
    # WF R1 byes — #1 seed (top) and #2 seed (bottom) advance with no opponent.
    # Auto-finalized 8-0 so the bracket shows them winning into R2. These carry
    # no opponent (team_b_id=None) and are skipped by the court scheduler.
    # -------------------------------------------------------------------------
    def _bye_match(tag: str, team, seq: int) -> Optional[Match]:
        if team is None:
            return None
        name = _team_display_name(team)
        return Match(
            tournament_id=spec.tournament_id,
            event_id=spec.event_id,
            schedule_version_id=version_id,
            match_code=f"{prefix}WF_R1_BYE_{tag}",
            match_type="WF",
            round_number=1,
            round_index=1,
            sequence_in_round=seq,
            team_a_id=team.id,
            team_b_id=None,
            placeholder_side_a=name,
            placeholder_side_b="BYE",
            duration_minutes=spec.waterfall_minutes,
            runtime_status="FINAL",
            status="complete",
            winner_team_id=team.id,
            score_json={"display": "8-0", "team_a_games": 8, "team_b_games": 0, "bye": True},
        )

    bye_top = _bye_match("TOP", bye_a, WF_R1_MATCHES + 1)
    bye_bot = _bye_match("BOT", bye_b, WF_R1_MATCHES + 2)
    bye_matches = [m for m in (bye_top, bye_bot) if m is not None]
    matches.extend(bye_matches)
    if bye_matches:
        session.add_all(bye_matches)
        session.flush()

    # -------------------------------------------------------------------------
    # WF R2 — 8 teams: 2 rating byes + 6 R1 winners (4 matches)
    # -------------------------------------------------------------------------
    r1_wins_sorted = sorted(r1_matches, key=lambda m: m.sequence_in_round or 0)

    def _r2_match(
        seq: int,
        side_a_team_id: Optional[int],
        side_a_ph: str,
        side_b_team_id: Optional[int],
        side_b_ph: str,
        src_a_id: Optional[int],
        src_b_id: Optional[int],
    ) -> Match:
        return Match(
            tournament_id=spec.tournament_id,
            event_id=spec.event_id,
            schedule_version_id=version_id,
            match_code=f"{prefix}WF_R2_{seq:02d}",
            match_type="WF",
            round_number=2,
            round_index=2,
            sequence_in_round=seq,
            team_a_id=side_a_team_id,
            team_b_id=side_b_team_id,
            placeholder_side_a=side_a_ph,
            placeholder_side_b=side_b_ph,
            source_match_a_id=src_a_id,
            source_a_role="WINNER" if src_a_id else None,
            source_match_b_id=src_b_id,
            source_b_role="WINNER" if src_b_id else None,
            duration_minutes=spec.waterfall_minutes,
        )

    bye_a_name = _team_display_name(bye_a)
    bye_b_name = _team_display_name(bye_b)
    bye_a_id = bye_a.id if bye_a else None
    bye_b_id = bye_b.id if bye_b else None
    # Bye teams are pre-bound onto R2 (their R1 bye is auto-won). We intentionally
    # do NOT set source_match for the bye side: byes are never assigned a court, and
    # a source link would trip the "upstream must be scheduled earlier" invariant.

    # W1..W6 = R1 winners by sequence
    def w_ph(idx: int) -> str:
        m = r1_wins_sorted[idx]
        return f"W(R1_{m.sequence_in_round})"

    def w_src(idx: int) -> int:
        return r1_wins_sorted[idx].id

    # R2 bracket wiring:
    #   Top:    #1 seed (bye) vs winner of match 2
    #   Middle: winner match 3 vs winner match 4
    #   Middle: winner match 5 vs winner match 6
    #   Bottom: winner of match 1 vs #2 seed (bye)
    r2_defs = [
        (bye_a_id, bye_a_name, None, None, w_ph(1), w_src(1)),
        (None, w_ph(2), w_src(2), None, w_ph(3), w_src(3)),
        (None, w_ph(4), w_src(4), None, w_ph(5), w_src(5)),
        (None, w_ph(0), w_src(0), bye_b_id, bye_b_name, None),
    ]
    r2_matches: List[Match] = []
    for seq, (ta_id, ta_ph, src_a, tb_id, tb_ph, src_b) in enumerate(r2_defs, start=1):
        m = _r2_match(seq, ta_id, ta_ph, tb_id, tb_ph, src_a, src_b)
        matches.append(m)
        r2_matches.append(m)

    session.add_all(r2_matches)
    session.flush()

    # -------------------------------------------------------------------------
    # Winner-flight pools — same 2×4 RR as 8-team WF→pools (after one WF round on 8)
    # -------------------------------------------------------------------------
    pool_labels = ["A", "B"]
    base_pairings = rr_pairings_by_round(4)
    for pool_idx, pool_label in enumerate(pool_labels):
        wired = wire_rr_match_placeholders(
            pool_index=pool_idx,
            pool_size=4,
            pairings=base_pairings,
            enforce_top2_last=True,
        )
        for rr_idx, (round_index, seq_in_round, placeholder_a, placeholder_b) in enumerate(wired):
            matches.append(
                Match(
                    tournament_id=spec.tournament_id,
                    event_id=spec.event_id,
                    schedule_version_id=version_id,
                    match_code=f"{prefix}POOL{pool_label}_RR_{rr_idx + 1:02d}",
                    match_type="RR",
                    round_number=round_index,
                    round_index=round_index,
                    sequence_in_round=seq_in_round,
                    placeholder_side_a=placeholder_a,
                    placeholder_side_b=placeholder_b,
                    duration_minutes=spec.standard_minutes,
                )
            )

    # -------------------------------------------------------------------------
    # Consolation flight — ranks 1–6 by original seed among WF R1 losers
    # -------------------------------------------------------------------------
    cons_round_by_tag = {"FRI": 1, "SAT1": 2, "SAT2": 3}
    for cp in CONS_REGULAR_PAIRINGS:
        cons_round = cons_round_by_tag[cp.schedule_tag]
        matches.append(
            Match(
                tournament_id=spec.tournament_id,
                event_id=spec.event_id,
                schedule_version_id=version_id,
                match_code=f"{prefix}CONS_{cp.schedule_tag}_{cp.pool}{cp.sequence:02d}",
                match_type="MAIN",
                round_number=cons_round,
                round_index=cons_round,
                sequence_in_round=cp.sequence,
                placeholder_side_a=cons_loser_placeholder(cp.rank_a),
                placeholder_side_b=cons_loser_placeholder(cp.rank_b),
                duration_minutes=spec.standard_minutes,
            )
        )

    for idx, (slot_a, slot_b) in enumerate(CONS_PLACEMENT_PAIRINGS, start=1):
        matches.append(
            Match(
                tournament_id=spec.tournament_id,
                event_id=spec.event_id,
                schedule_version_id=version_id,
                match_code=f"{prefix}CONS_SUN_{idx:02d}",
                match_type="PLACEMENT",
                round_number=1,
                round_index=1,
                sequence_in_round=idx,
                placeholder_side_a=slot_a,
                placeholder_side_b=slot_b,
                placement_type="WF14_CONS_CROSS",
                duration_minutes=spec.standard_minutes,
            )
        )

    return matches, warnings
