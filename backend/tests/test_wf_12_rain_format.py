"""12-team rain draw: two flights of 6, friendlies, and 1/2/3 finals."""

from __future__ import annotations

from datetime import date

from sqlmodel import Session, select

from app.models.event import Event, EventCategory
from app.models.match import Match
from app.models.schedule_version import ScheduleVersion
from app.models.team import Team
from app.models.tournament import Tournament
from app.services.advancement_service import apply_advancement_with_details
from app.services.draw_plan_engine import DrawPlanSpec, compute_inventory, generate_matches_for_event
from app.services.draw_plan_rules import get_valid_family_for_team_count, required_wf_rounds
from app.services.rr_match_codes import rain_placement_bucket, rr_pool_code_for_match
from app.services.schedule_sequence import _cons_flight_phase, _phase_for_match
from app.routes.draw_builder import apply_rain_board_keeping_finals
from app.routes.teams import swap_teams_in_open_matches
from app.services.wf_12_rain_advancement import order_pool_teams, refresh_wf12_rain_placement
from app.services.wf_12_rain_format import wf_12_rain_total_matches


def test_rain_is_optional_for_12_and_has_24_matches():
    assert get_valid_family_for_team_count(12) == "WF_TO_POOLS_DYNAMIC"
    assert required_wf_rounds("WF_12_RAIN_SIX", 12) == 0
    assert wf_12_rain_total_matches() == 24

    spec = DrawPlanSpec(
        event_id=1,
        event_name="Cancun",
        division=None,
        team_count=12,
        template_type="WF_12_RAIN_SIX",
        template_key="WF_12_RAIN_SIX",
        guarantee=4,
        waterfall_rounds=0,
        waterfall_minutes=60,
        standard_minutes=90,
    )
    inventory = compute_inventory(spec)
    assert not inventory.has_errors()
    assert inventory.wf_matches == 0
    assert inventory.rr_matches == 18
    assert inventory.total_matches == 24
    assert inventory.counts_by_stage["PLACEMENT"] == 6


def test_rain_codes_and_phases():
    assert rr_pool_code_for_match("MIX_E1_TOP_FRI_A01") == "RAINA"
    assert rr_pool_code_for_match("MIX_E1_TOP_SAT2_B02") == "RAINB"
    assert rr_pool_code_for_match("MIX_E1_BOT_FRI_C01") == "RAINC"
    assert rr_pool_code_for_match("MIX_E1_BOT_SAT1_D02") == "RAIND"
    assert rr_pool_code_for_match("MIX_E1_TOP_FUN_FRI_01") == "TOPFUN"
    assert rr_pool_code_for_match("MIX_E1_BOT_FUN_SAT2_01") == "BOTFUN"
    assert rr_pool_code_for_match("MIX_E1_TOP_SUN_01") is None
    assert rain_placement_bucket("MIX_E1_TOP_SUN_01") == "TOP_PLACE"
    assert rain_placement_bucket("MIX_E1_BOT_SUN_03") == "BOT_PLACE"

    assert _cons_flight_phase("MIX_E1_TOP_FRI_A01") == 22
    assert _cons_flight_phase("MIX_E1_TOP_FUN_SAT1_01") == 32
    assert _cons_flight_phase("MIX_E1_BOT_SAT2_D02") == 42
    assert _cons_flight_phase("MIX_E1_TOP_SUN_01") == 53
    assert _cons_flight_phase("MIX_E1_BOT_SUN_02") == 53

    match = Match(
        tournament_id=1,
        event_id=1,
        schedule_version_id=1,
        match_code="X_BOT_FRI_C01",
        match_type="RR",
        round_number=1,
        round_index=1,
        sequence_in_round=1,
        duration_minutes=90,
        placeholder_side_a="A",
        placeholder_side_b="B",
    )
    assert _phase_for_match(match, wf_rounds=0) == 22


def test_head_to_head_beats_game_difference_for_a_two_team_tie():
    # A beat B in a close match. B beat C in a blowout. A and B are tied on wins.
    # Game difference would put B first. Head-to-head puts A first.
    order = order_pool_teams(
        [1, 2, 3],
        [
            _final_match(1, 2, 1, "8-6"),
            _final_match(2, 3, 2, "8-0"),
        ],
        {1: 1, 2: 2, 3: 3},
    )
    assert order == [1, 2, 3]


def test_three_way_tie_uses_game_difference_then_seed():
    # Circle: 1 beat 4, 4 beat 6, 6 beat 1. All 1-1, so head-to-head does not split them.
    order = order_pool_teams(
        [1, 4, 6],
        [
            _final_match(1, 4, 1, "8-6"),
            _final_match(4, 6, 4, "8-7"),
            _final_match(6, 1, 6, "8-2"),
        ],
        {1: 1, 4: 4, 6: 6},
    )
    assert order == [6, 4, 1]


def _seed_rain_event(session: Session):
    tournament = Tournament(
        name="Rain Cancun",
        location="Cancun",
        timezone="UTC",
        start_date=date(2026, 11, 12),
        end_date=date(2026, 11, 12),
    )
    session.add(tournament)
    session.commit()
    session.refresh(tournament)

    version = ScheduleVersion(tournament_id=tournament.id, version_number=1, status="draft")
    session.add(version)
    session.commit()
    session.refresh(version)

    event = Event(
        tournament_id=tournament.id,
        category=EventCategory.mixed,
        name="Cancun",
        team_count=12,
        draw_plan_json='{"template_type":"WF_12_RAIN_SIX","wf_rounds":0}',
    )
    session.add(event)
    session.commit()
    session.refresh(event)

    teams = []
    for seed in range(1, 13):
        team = Team(event_id=event.id, name=f"Team {seed}", seed=seed, display_name=f"T{seed}")
        session.add(team)
        teams.append(team)
    session.commit()
    for team in teams:
        session.refresh(team)
    return tournament, version, event, teams


def _spec(tournament, event) -> DrawPlanSpec:
    return DrawPlanSpec(
        event_id=event.id,
        event_name=event.name,
        division=None,
        team_count=12,
        template_type="WF_12_RAIN_SIX",
        template_key="WF_12_RAIN_SIX",
        guarantee=4,
        waterfall_rounds=0,
        waterfall_minutes=60,
        standard_minutes=90,
        tournament_id=tournament.id,
        event_category="mixed",
    )


def _final_match(team_a_id: int, team_b_id: int, winner_id: int, score: str) -> Match:
    return Match(
        tournament_id=1,
        event_id=1,
        schedule_version_id=1,
        match_code=f"UNIT_{team_a_id}_{team_b_id}",
        match_type="RR",
        round_number=1,
        round_index=1,
        sequence_in_round=1,
        duration_minutes=90,
        team_a_id=team_a_id,
        team_b_id=team_b_id,
        placeholder_side_a="A",
        placeholder_side_b="B",
        runtime_status="FINAL",
        winner_team_id=winner_id,
        score_json={"display": score},
    )


def _by_suffix(matches, suffix: str) -> Match:
    found = [match for match in matches if (match.match_code or "").endswith(suffix)]
    assert len(found) == 1, suffix
    return found[0]


def test_generator_assigns_seeds_and_leaves_finals_open(session: Session):
    tournament, version, event, teams = _seed_rain_event(session)
    by_seed = {team.seed: team for team in teams}
    session._allow_match_generation = True  # type: ignore[attr-defined]
    matches, warnings = generate_matches_for_event(
        session,
        version.id,
        _spec(tournament, event),
        [team.id for team in reversed(teams)],
        set(),
    )
    assert not any("requires" in warning.lower() for warning in warnings)
    session.add_all(matches)
    session.commit()
    assert len(matches) == 24

    # Top flight groups: A = 1, 4, 6 and B = 2, 3, 5. Friendlies are the byes.
    assert {_by_suffix(matches, "TOP_FRI_A01").team_a_id, _by_suffix(matches, "TOP_FRI_A01").team_b_id} == {
        by_seed[1].id,
        by_seed[6].id,
    }
    assert {_by_suffix(matches, "TOP_FRI_B02").team_a_id, _by_suffix(matches, "TOP_FRI_B02").team_b_id} == {
        by_seed[2].id,
        by_seed[5].id,
    }
    assert {_by_suffix(matches, "TOP_FUN_FRI_01").team_a_id, _by_suffix(matches, "TOP_FUN_FRI_01").team_b_id} == {
        by_seed[4].id,
        by_seed[3].id,
    }
    assert {_by_suffix(matches, "TOP_FUN_SAT1_01").team_a_id, _by_suffix(matches, "TOP_FUN_SAT1_01").team_b_id} == {
        by_seed[1].id,
        by_seed[2].id,
    }
    assert {_by_suffix(matches, "TOP_FUN_SAT2_01").team_a_id, _by_suffix(matches, "TOP_FUN_SAT2_01").team_b_id} == {
        by_seed[6].id,
        by_seed[5].id,
    }

    # Bottom flight is the same shape on seeds 7–12.
    assert {_by_suffix(matches, "BOT_FRI_C01").team_a_id, _by_suffix(matches, "BOT_FRI_C01").team_b_id} == {
        by_seed[7].id,
        by_seed[12].id,
    }
    assert {_by_suffix(matches, "BOT_FUN_FRI_01").team_a_id, _by_suffix(matches, "BOT_FUN_FRI_01").team_b_id} == {
        by_seed[10].id,
        by_seed[9].id,
    }

    finals = [match for match in matches if match.match_type == "PLACEMENT"]
    assert len(finals) == 6
    assert all(match.team_a_id is None and match.team_b_id is None for match in finals)
    assert _by_suffix(matches, "TOP_SUN_01").placeholder_side_a == "A1"
    assert _by_suffix(matches, "TOP_SUN_01").placeholder_side_b == "B1"
    assert _by_suffix(matches, "BOT_SUN_03").placeholder_side_a == "C3"
    assert _by_suffix(matches, "BOT_SUN_03").placeholder_side_b == "D3"
    assert sum(1 for match in matches if match.placement_type == "RAIN_FUN") == 6


def test_finals_use_group_results_and_ignore_friendlies(session: Session):
    tournament, version, event, teams = _seed_rain_event(session)
    by_seed = {team.seed: team for team in teams}
    session._allow_match_generation = True  # type: ignore[attr-defined]
    matches, _warnings = generate_matches_for_event(
        session,
        version.id,
        _spec(tournament, event),
        [team.id for team in teams],
        set(),
    )
    session.add_all(matches)
    session.commit()

    stored = session.exec(select(Match).where(Match.event_id == event.id)).all()

    def finish(suffix: str, winner_seed: int, score: str) -> Match:
        match = _by_suffix(stored, suffix)
        winner = by_seed[winner_seed]
        match.runtime_status = "FINAL"
        match.winner_team_id = winner.id
        match.score_json = {"display": score}
        # Score string is team A then team B. Put the winner on side A when needed.
        if match.team_a_id != winner.id:
            match.team_a_id, match.team_b_id = match.team_b_id, match.team_a_id
            match.placeholder_side_a, match.placeholder_side_b = match.placeholder_side_b, match.placeholder_side_a
        session.add(match)
        return match

    # Group A: seed 1 is 2-0, seed 4 is 1-1, seed 6 is 0-2.
    finish("TOP_FRI_A01", 1, "8-4")  # 1 vs 6
    finish("TOP_SAT1_A01", 4, "8-3")  # 4 vs 6
    finish("TOP_SAT2_A01", 1, "8-5")  # 1 vs 4
    # Group B: seed 3 is 2-0, seed 2 is 1-1, seed 5 is 0-2.
    finish("TOP_FRI_B02", 2, "8-6")  # 2 vs 5
    finish("TOP_SAT1_B02", 3, "8-2")  # 3 vs 5
    last = finish("TOP_SAT2_B02", 3, "8-4")  # 2 vs 3, 3 wins

    # Friendlies go the other way. They must not change who is #1/#2/#3.
    finish("TOP_FUN_FRI_01", 3, "8-0")  # 4 vs 3, 3 wins big
    finish("TOP_FUN_SAT1_01", 2, "8-0")  # 1 vs 2, 2 wins big
    finish("TOP_FUN_SAT2_01", 6, "8-0")  # 6 vs 5, 6 wins big
    session.commit()

    filled = refresh_wf12_rain_placement(session, tournament.id, event.id, version.id)
    assert filled == 3
    session.refresh(_by_suffix(stored, "TOP_SUN_01"))
    session.refresh(_by_suffix(stored, "TOP_SUN_02"))
    session.refresh(_by_suffix(stored, "TOP_SUN_03"))
    assert _by_suffix(stored, "TOP_SUN_01").team_a_id == by_seed[1].id
    assert _by_suffix(stored, "TOP_SUN_01").team_b_id == by_seed[3].id
    assert _by_suffix(stored, "TOP_SUN_02").team_a_id == by_seed[4].id
    assert _by_suffix(stored, "TOP_SUN_02").team_b_id == by_seed[2].id
    assert _by_suffix(stored, "TOP_SUN_03").team_a_id == by_seed[6].id
    assert _by_suffix(stored, "TOP_SUN_03").team_b_id == by_seed[5].id
    assert _by_suffix(stored, "TOP_SUN_01").placeholder_side_a == "A1"

    # Bottom flight stays open until its own groups finish.
    assert _by_suffix(stored, "BOT_SUN_01").team_a_id is None

    # Desk finalize path fills the same slots. Re-open one top final and score the last group match again.
    top_final = _by_suffix(stored, "TOP_SUN_01")
    top_final.team_a_id = None
    top_final.team_b_id = None
    session.add(top_final)
    session.commit()
    apply_advancement_with_details(session, last.id)
    session.refresh(top_final)
    assert top_final.team_a_id == by_seed[1].id
    assert top_final.team_b_id == by_seed[3].id


def test_rain_rebuild_keeps_finished_waterfall_and_adds_default(session: Session):
    tournament, version, event, teams = _seed_rain_event(session)
    by_seed = {team.seed: team for team in teams}
    played = Match(
        tournament_id=tournament.id,
        event_id=event.id,
        schedule_version_id=version.id,
        match_code="KEEP_WF_1",
        match_type="WF",
        round_number=1,
        round_index=1,
        sequence_in_round=1,
        duration_minutes=60,
        team_a_id=by_seed[1].id,
        team_b_id=by_seed[7].id,
        placeholder_side_a="T1",
        placeholder_side_b="T7",
        runtime_status="FINAL",
        winner_team_id=by_seed[1].id,
        score_json={"display": "8-3"},
    )
    unplayed = Match(
        tournament_id=tournament.id,
        event_id=event.id,
        schedule_version_id=version.id,
        match_code="DROP_RR",
        match_type="RR",
        round_number=1,
        round_index=1,
        sequence_in_round=1,
        duration_minutes=90,
        team_a_id=by_seed[1].id,
        team_b_id=by_seed[2].id,
        placeholder_side_a="T1",
        placeholder_side_b="T2",
        runtime_status="SCHEDULED",
    )
    session.add(played)
    session.add(unplayed)
    session.commit()
    session.refresh(played)

    result = apply_rain_board_keeping_finals(session, event, by_seed[6].id, by_seed[12].id)
    assert result["removed_unplayed"] == 1
    assert result["default_waterfall_created"] is True

    stored = list(session.exec(select(Match).where(Match.event_id == event.id)).all())
    kept = next(match for match in stored if match.id == played.id)
    assert kept.score_json["display"] == "8-3"
    assert kept.winner_team_id == by_seed[1].id
    assert all(match.match_code != "DROP_RR" for match in stored)

    rain = [match for match in stored if "TOP_" in (match.match_code or "") or "BOT_" in (match.match_code or "")]
    assert len(rain) == 24
    assert {_by_suffix(rain, "TOP_FRI_A01").team_a_id, _by_suffix(rain, "TOP_FRI_A01").team_b_id} == {
        by_seed[1].id,
        by_seed[6].id,
    }
    assert {_by_suffix(rain, "BOT_FRI_C01").team_a_id, _by_suffix(rain, "BOT_FRI_C01").team_b_id} == {
        by_seed[7].id,
        by_seed[12].id,
    }

    default_match = next(match for match in stored if match.winner_team_id == by_seed[6].id and match.match_type == "WF")
    assert default_match.team_a_id == by_seed[6].id
    assert default_match.team_b_id == by_seed[12].id
    assert default_match.score_json["display"] == "DEFAULT"
    assert default_match.runtime_status == "FINAL"
    session.refresh(by_seed[6])
    assert not by_seed[6].is_defaulted


def test_swap_teams_keeps_finished_matches(session: Session):
    tournament, version, event, teams = _seed_rain_event(session)
    scott, oakley = teams[3], teams[11]
    played = Match(
        tournament_id=tournament.id,
        event_id=event.id,
        schedule_version_id=version.id,
        match_code="WF_KEEP",
        match_type="WF",
        round_number=1,
        round_index=1,
        sequence_in_round=1,
        duration_minutes=60,
        team_a_id=scott.id,
        team_b_id=teams[0].id,
        placeholder_side_a="Scott",
        placeholder_side_b="Other",
        runtime_status="FINAL",
        winner_team_id=scott.id,
        score_json={"display": "9-7"},
    )
    open_match = Match(
        tournament_id=tournament.id,
        event_id=event.id,
        schedule_version_id=version.id,
        match_code="RR_OPEN",
        match_type="RR",
        round_number=1,
        round_index=1,
        sequence_in_round=1,
        duration_minutes=120,
        team_a_id=scott.id,
        team_b_id=teams[1].id,
        placeholder_side_a="Scott",
        placeholder_side_b="Other",
        runtime_status="SCHEDULED",
    )
    session.add(played)
    session.add(open_match)
    session.commit()

    result = swap_teams_in_open_matches(session, event.id, scott.id, oakley.id)
    assert result.matches_updated == 1
    assert result.finals_left_alone == 1
    session.refresh(played)
    session.refresh(open_match)
    session.refresh(scott)
    session.refresh(oakley)
    assert played.team_a_id == scott.id
    assert played.winner_team_id == scott.id
    assert open_match.team_a_id == oakley.id
    assert open_match.placeholder_side_a == "T12"
    assert scott.seed == 12
    assert oakley.seed == 4
