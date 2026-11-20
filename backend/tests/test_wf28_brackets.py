import json
from datetime import date

from app.services.draw_plan_engine import DrawPlanSpec, compute_inventory, generate_matches_for_event
from app.services.draw_plan_rules import (
    get_valid_family_for_team_count,
    is_team_count_valid_for_family,
    required_wf_rounds,
)
from app.services.rr_match_codes import rr_pool_code_for_match


def test_28_team_default_stays_pools_and_brackets_rr_is_allowed():
    assert get_valid_family_for_team_count(28) == "WF_TO_POOLS_DYNAMIC"
    assert is_team_count_valid_for_family("WF_28_BRACKETS_RR", 28)
    assert not is_team_count_valid_for_family("WF_28_BRACKETS_RR", 24)
    assert required_wf_rounds("WF_28_BRACKETS_RR", 28) == 2


def test_inventory_is_three_brackets_plus_one_round_robin():
    spec = DrawPlanSpec(
        event_id=1,
        event_name="Open",
        division="Mixed",
        team_count=28,
        template_type="WF_28_BRACKETS_RR",
        template_key="WF_28_BRACKETS_RR",
        guarantee=5,
        waterfall_rounds=2,
        waterfall_minutes=60,
        standard_minutes=105,
    )
    inventory = compute_inventory(spec)
    assert inventory.errors == []
    assert inventory.wf_matches == 28
    assert inventory.bracket_matches == 36
    assert inventory.rr_matches == 6
    assert inventory.total_matches == 70

    spec.guarantee = 4
    inventory_g4 = compute_inventory(spec)
    assert inventory_g4.bracket_matches == 27
    assert inventory_g4.rr_matches == 6
    assert inventory_g4.total_matches == 61


def test_generated_draw_uses_seed_blocks_and_division_4(session):
    from app.models.event import Event
    from app.models.schedule_version import ScheduleVersion
    from app.models.tournament import Tournament

    tournament = Tournament(
        name="Palm Springs",
        location="Test",
        timezone="America/New_York",
        start_date=date(2026, 1, 15),
        end_date=date(2026, 1, 17),
        use_time_windows=False,
    )
    session.add(tournament)
    session.commit()
    session.refresh(tournament)

    event = Event(
        tournament_id=tournament.id,
        category="mixed",
        name="Open",
        team_count=28,
        guarantee_selected=5,
        draw_plan_json=json.dumps({"template_type": "WF_28_BRACKETS_RR", "wf_rounds": 2}),
    )
    session.add(event)
    session.commit()
    session.refresh(event)

    version = ScheduleVersion(tournament_id=tournament.id, version_number=1)
    session.add(version)
    session.commit()
    session.refresh(version)

    spec = DrawPlanSpec(
        event_id=event.id,
        event_name=event.name,
        division="Mixed",
        team_count=28,
        template_type="WF_28_BRACKETS_RR",
        template_key="WF_28_BRACKETS_RR",
        guarantee=5,
        waterfall_rounds=2,
        waterfall_minutes=60,
        standard_minutes=105,
        tournament_id=tournament.id,
        event_category="mixed",
    )
    session._allow_match_generation = True
    matches, warnings = generate_matches_for_event(session, version.id, spec, list(range(1, 29)), set())
    assert not any("Cannot generate" in warning or "requires" in warning for warning in warnings)

    assert sum(1 for match in matches if match.match_type == "WF") == 28
    assert sum(1 for match in matches if match.match_type == "MAIN") == 21
    assert sum(1 for match in matches if match.match_type == "CONSOLATION") == 15
    assert sum(1 for match in matches if match.match_type == "RR") == 6

    qf = [
        match
        for match in matches
        if match.match_type == "MAIN" and match.round_index == 1 and match.match_code.endswith("_M1")
    ]
    by_bracket = {match.match_code.split("_B")[-1].split("_")[0]: match for match in qf}
    assert (by_bracket["1"].placeholder_side_a, by_bracket["1"].placeholder_side_b) == ("WFSEED:01", "WFSEED:08")
    assert (by_bracket["2"].placeholder_side_a, by_bracket["2"].placeholder_side_b) == ("WFSEED:09", "WFSEED:16")
    assert (by_bracket["3"].placeholder_side_a, by_bracket["3"].placeholder_side_b) == ("WFSEED:17", "WFSEED:24")

    rr = sorted(
        (match for match in matches if match.match_type == "RR"),
        key=lambda match: match.match_code,
    )
    assert [rr_pool_code_for_match(match.match_code) for match in rr] == ["DIV4"] * 6
    assert [(match.placeholder_side_a, match.placeholder_side_b) for match in rr] == [
        ("SEED_25", "SEED_28"),
        ("SEED_26", "SEED_27"),
        ("SEED_25", "SEED_27"),
        ("SEED_26", "SEED_28"),
        ("SEED_25", "SEED_26"),
        ("SEED_27", "SEED_28"),
    ]


def test_placement_ranks_one_through_twenty_eight(session):
    from app.models.event import Event
    from app.models.match import Match
    from app.models.schedule_version import ScheduleVersion
    from app.models.team import Team
    from app.models.tournament import Tournament
    from app.services.wf_28_brackets import place_wf28_brackets

    tournament = Tournament(
        name="Palm Springs Placement",
        location="Test",
        timezone="America/New_York",
        start_date=date(2026, 1, 15),
        end_date=date(2026, 1, 17),
        use_time_windows=False,
    )
    session.add(tournament)
    session.commit()
    session.refresh(tournament)

    event = Event(
        tournament_id=tournament.id,
        category="mixed",
        name="Open",
        team_count=28,
        guarantee_selected=5,
        draw_plan_json=json.dumps({"template_type": "WF_28_BRACKETS_RR", "wf_rounds": 2}),
    )
    session.add(event)
    session.commit()
    session.refresh(event)

    version = ScheduleVersion(tournament_id=tournament.id, version_number=1)
    session.add(version)
    session.commit()
    session.refresh(version)

    teams = []
    for seed in range(1, 29):
        team = Team(event_id=event.id, name=f"Team {seed}", seed=seed)
        session.add(team)
        teams.append(team)
    session.commit()
    for team in teams:
        session.refresh(team)
    team_id = {seed: team.id for seed, team in enumerate(teams, start=1)}

    def add_match(code, round_number, winner_seed, loser_seed, winner_games, loser_games):
        session.add(
            Match(
                tournament_id=tournament.id,
                event_id=event.id,
                schedule_version_id=version.id,
                match_code=code,
                match_type="WF",
                round_number=round_number,
                round_index=round_number,
                sequence_in_round=1,
                duration_minutes=60,
                team_a_id=team_id[winner_seed],
                team_b_id=team_id[loser_seed],
                winner_team_id=team_id[winner_seed],
                runtime_status="FINAL",
                placeholder_side_a="A",
                placeholder_side_b="B",
                score_json={"display": f"{winner_games}-{loser_games}"},
            )
        )

    for left in range(1, 15):
        add_match(f"R1_{left}", 1, left, left + 14, 6, 4)
    for index, (winner, loser) in enumerate(
        ((1, 8), (2, 9), (3, 10), (4, 11), (5, 12), (6, 13), (7, 14)),
        start=1,
    ):
        add_match(f"R2W_{winner}", 2, winner, loser, 9 - index, 1)
    for index, (winner, loser) in enumerate(
        ((15, 22), (16, 23), (17, 24), (18, 25), (19, 26), (20, 27), (21, 28)),
        start=1,
    ):
        add_match(f"R2L_{winner}", 2, winner, loser, 9 - index, 1)

    qf = Match(
        tournament_id=tournament.id,
        event_id=event.id,
        schedule_version_id=version.id,
        match_code="B1_M1",
        match_type="MAIN",
        round_number=1,
        round_index=1,
        sequence_in_round=1,
        duration_minutes=105,
        placeholder_side_a="WFSEED:01",
        placeholder_side_b="WFSEED:08",
    )
    rr = Match(
        tournament_id=tournament.id,
        event_id=event.id,
        schedule_version_id=version.id,
        match_code="DIV4_RR_01",
        match_type="RR",
        round_number=1,
        round_index=1,
        sequence_in_round=1,
        duration_minutes=105,
        placeholder_side_a="SEED_25",
        placeholder_side_b="SEED_28",
    )
    session.add(qf)
    session.add(rr)
    session.commit()

    assert place_wf28_brackets(session, tournament.id, version.id, event.id) == 2
    session.refresh(qf)
    session.refresh(rr)
    assert qf.team_a_id == team_id[1]
    assert qf.team_b_id == team_id[15]
    assert rr.team_a_id == team_id[25]
    assert rr.team_b_id == team_id[22]
