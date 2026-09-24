"""Tests for WF_10_SIX_FOUR format, generator, lucky loser, and day tags."""

from __future__ import annotations

from datetime import date

from sqlmodel import Session, select

from app.models.event import Event, EventCategory
from app.models.match import Match
from app.models.schedule_version import ScheduleVersion
from app.models.team import Team
from app.models.tournament import Tournament
from app.services.draw_plan_engine import DrawPlanSpec, compute_inventory, generate_matches_for_event
from app.services.draw_plan_rules import get_valid_family_for_team_count, required_wf_rounds
from app.services.schedule_sequence import _cons_flight_phase, _phase_for_match
from app.services.wf_10_advancement import compute_wf10_flight_ranks, refresh_wf10_rr_slots
from app.services.wf_10_format import (
    FUN_PAIRINGS,
    LOSS_RR_PAIRINGS,
    POOL_A_RANKS,
    POOL_B_RANKS,
    WIN_RR_PAIRINGS,
    wf_10_total_generated_matches,
    wf_10_total_matches,
)


def test_wf10_family_and_inventory():
    assert get_valid_family_for_team_count(10) == "WF_10_SIX_FOUR"
    assert required_wf_rounds("WF_10_SIX_FOUR", 10) == 1
    assert wf_10_total_matches() == 25
    assert wf_10_total_generated_matches() == 25
    assert POOL_A_RANKS == (1, 4, 6)
    assert POOL_B_RANKS == (2, 3, 5)
    assert len(WIN_RR_PAIRINGS) == 6
    assert len(FUN_PAIRINGS) == 3
    assert len(LOSS_RR_PAIRINGS) == 6


def test_wf10_day_tag_phases():
    assert _cons_flight_phase("MIX_WIN_FRI_A01") == 22
    assert _cons_flight_phase("MIX_FUN_SAT1_01") == 32
    assert _cons_flight_phase("MIX_LOSS_SAT2_02") == 42
    assert _cons_flight_phase("MIX_WIN_SUN_01") == 53
    assert _cons_flight_phase("MIX_LOSS_SUN_02") == 53

    m = Match(
        tournament_id=1,
        event_id=1,
        schedule_version_id=1,
        match_code="X_WIN_FRI_A01",
        match_type="RR",
        round_number=1,
        round_index=1,
        sequence_in_round=1,
        duration_minutes=90,
        placeholder_side_a="W1",
        placeholder_side_b="W6",
    )
    assert _phase_for_match(m, wf_rounds=1) == 22


def _seed_wf10_event(session: Session):
    t = Tournament(
        name="WF10 Test",
        location="X",
        timezone="UTC",
        start_date=date(2026, 10, 16),
        end_date=date(2026, 10, 18),
    )
    session.add(t)
    session.commit()
    session.refresh(t)

    v = ScheduleVersion(tournament_id=t.id, version_number=1, status="draft")
    session.add(v)
    session.commit()
    session.refresh(v)

    e = Event(
        tournament_id=t.id,
        category=EventCategory.mixed,
        name="Mixed A",
        team_count=10,
        draw_plan_json='{"template_type":"WF_10_SIX_FOUR","wf_rounds":1}',
    )
    session.add(e)
    session.commit()
    session.refresh(e)

    teams = []
    for i in range(1, 11):
        team = Team(event_id=e.id, name=f"Team {i}", seed=i, display_name=f"T{i}")
        session.add(team)
        teams.append(team)
    session.commit()
    for team in teams:
        session.refresh(team)
    return t, v, e, teams


def test_wf10_generator_creates_25_matches(session: Session):
    t, v, e, teams = _seed_wf10_event(session)
    spec = DrawPlanSpec(
        event_id=e.id,
        event_name=e.name,
        division=None,
        team_count=10,
        template_type="WF_10_SIX_FOUR",
        template_key="WF_10_SIX_FOUR",
        guarantee=4,
        waterfall_rounds=1,
        waterfall_minutes=60,
        standard_minutes=90,
        tournament_id=t.id,
        event_category="mixed",
    )
    inv = compute_inventory(spec)
    assert not inv.has_errors()
    assert inv.total_matches == 25

    session._allow_match_generation = True  # type: ignore[attr-defined]
    matches, warnings = generate_matches_for_event(session, v.id, spec, [tm.id for tm in teams], set())
    assert not any("requires" in w.lower() for w in warnings)
    session.add_all(matches)
    session.commit()
    assert len(matches) == 25

    codes = [m.match_code for m in matches]
    assert sum(1 for c in codes if "WF_R1_" in c) == 5
    assert sum(1 for c in codes if "WIN_FRI" in c or "WIN_SAT" in c) == 6
    assert sum(1 for c in codes if "FUN_" in c) == 3
    assert sum(1 for c in codes if "LOSS_FRI" in c or "LOSS_SAT" in c) == 6
    assert sum(1 for c in codes if "WIN_SUN" in c) == 3
    assert sum(1 for c in codes if "LOSS_SUN" in c) == 2


def test_wf10_lucky_loser_closest_score(session: Session):
    t, v, e, teams = _seed_wf10_event(session)
    # Create 5 finalized WF matches with known margins.
    # Winners: teams 1-5. Losers: 6-10 with diffs -1,-2,-3,-4,-5 → lucky = team 6 (closest).
    pairs = [(1, 6, 8, 7), (2, 7, 8, 6), (3, 8, 8, 5), (4, 9, 8, 4), (5, 10, 8, 3)]
    by_seed = {tm.seed: tm for tm in teams}
    for i, (wa, lb, ga, gb) in enumerate(pairs, start=1):
        m = Match(
            tournament_id=t.id,
            event_id=e.id,
            schedule_version_id=v.id,
            match_code=f"MIX_WF_R1_{i:02d}",
            match_type="WF",
            round_number=1,
            round_index=1,
            sequence_in_round=i,
            team_a_id=by_seed[wa].id,
            team_b_id=by_seed[lb].id,
            placeholder_side_a=f"T{wa}",
            placeholder_side_b=f"T{lb}",
            duration_minutes=60,
            runtime_status="FINAL",
            status="complete",
            winner_team_id=by_seed[wa].id,
            score_json={"team_a_games": ga, "team_b_games": gb, "display": f"{ga}-{gb}"},
        )
        session.add(m)
    session.commit()

    ranks = compute_wf10_flight_ranks(session, t.id, e.id, v.id)
    assert ranks is not None
    win_rank, loss_rank = ranks
    assert win_rank[6] == by_seed[6].id  # closest loss
    assert by_seed[6].id not in loss_rank.values()
    assert len(loss_rank) == 4
    assert set(loss_rank.values()) == {by_seed[i].id for i in (7, 8, 9, 10)}


def test_wf10_refresh_fills_rr_placeholders(session: Session):
    t, v, e, teams = _seed_wf10_event(session)
    spec = DrawPlanSpec(
        event_id=e.id,
        event_name=e.name,
        division=None,
        team_count=10,
        template_type="WF_10_SIX_FOUR",
        template_key="WF_10_SIX_FOUR",
        guarantee=4,
        waterfall_rounds=1,
        waterfall_minutes=60,
        standard_minutes=90,
        tournament_id=t.id,
        event_category="mixed",
    )
    session._allow_match_generation = True  # type: ignore[attr-defined]
    matches, _warnings = generate_matches_for_event(session, v.id, spec, [tm.id for tm in teams], set())
    session.add_all(matches)
    session.commit()

    by_seed = {tm.seed: tm for tm in teams}
    wf = session.exec(
        select(Match).where(
            Match.event_id == e.id,
            Match.schedule_version_id == v.id,
            Match.match_type == "WF",
        )
    ).all()
    assert len(wf) == 5
    # Finalize with winners 1-5, losers 6-10, team6 closest
    for i, m in enumerate(sorted(wf, key=lambda x: x.sequence_in_round or 0), start=1):
        wa, lb = i, i + 5
        m.team_a_id = by_seed[wa].id
        m.team_b_id = by_seed[lb].id
        m.winner_team_id = by_seed[wa].id
        m.runtime_status = "FINAL"
        m.status = "complete"
        margin = 8 - i  # loser games: 7,6,5,4,3 → team6 closest
        m.score_json = {"team_a_games": 8, "team_b_games": margin, "display": f"8-{margin}"}
        session.add(m)
    session.commit()

    n = refresh_wf10_rr_slots(session, t.id, e.id, v.id)
    assert n > 0
    win_rr = session.exec(
        select(Match).where(
            Match.event_id == e.id,
            Match.schedule_version_id == v.id,
            Match.match_type == "RR",
            Match.match_code.contains("WIN_FRI"),
        )
    ).all()
    assert win_rr
    assert all(m.team_a_id and m.team_b_id for m in win_rr)
