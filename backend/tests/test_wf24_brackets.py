from app.services.draw_plan_rules import get_valid_family_for_team_count, is_team_count_valid_for_family
from app.utils.wf_seeding import WFTeamResult, wf24_quarterfinal_seeds, wf_overall_seed_key


def test_24_team_default_stays_pools_and_brackets_are_allowed():
    assert get_valid_family_for_team_count(24) == "WF_TO_POOLS_DYNAMIC"
    assert get_valid_family_for_team_count(32) == "WF_TO_BRACKETS_8"
    assert is_team_count_valid_for_family("WF_TO_BRACKETS_8", 24)


def test_quarterfinals_use_three_seed_blocks():
    brackets = wf24_quarterfinal_seeds()
    assert brackets[0] == [(1, 8), (4, 5), (2, 7), (3, 6)]
    assert brackets[1] == [(9, 16), (12, 13), (10, 15), (11, 14)]
    assert brackets[2] == [(17, 24), (20, 21), (18, 23), (19, 22)]
    seeds = [seed for pairs in brackets for pair in pairs for seed in pair]
    assert sorted(seeds) == list(range(1, 25))


def test_generated_24_team_brackets_use_overall_seeds(session):
    import json
    from datetime import date

    from app.models.event import Event
    from app.models.schedule_version import ScheduleVersion
    from app.models.tournament import Tournament
    from app.services.draw_plan_engine import DrawPlanSpec, generate_matches_for_event

    tournament = Tournament(
        name="Twenty Four",
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
        team_count=24,
        guarantee_selected=5,
        draw_plan_json=json.dumps({"template_type": "WF_TO_BRACKETS_8", "wf_rounds": 2}),
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
        team_count=24,
        template_type="WF_TO_BRACKETS_8",
        template_key="WF_TO_BRACKETS_8",
        guarantee=5,
        waterfall_rounds=2,
        waterfall_minutes=60,
        standard_minutes=105,
        tournament_id=tournament.id,
        event_category="mixed",
    )
    session._allow_match_generation = True
    matches, warnings = generate_matches_for_event(session, version.id, spec, list(range(1, 25)), set())
    assert not any("Cannot generate" in warning for warning in warnings)

    qf = [
        match
        for match in matches
        if match.match_type == "MAIN" and match.round_index == 1 and match.match_code.endswith("_M1")
    ]
    by_bracket = {match.match_code.split("_B")[-1].split("_")[0]: match for match in qf}
    assert (by_bracket["1"].placeholder_side_a, by_bracket["1"].placeholder_side_b) == ("WFSEED:01", "WFSEED:08")
    assert (by_bracket["2"].placeholder_side_a, by_bracket["2"].placeholder_side_b) == ("WFSEED:09", "WFSEED:16")
    assert (by_bracket["3"].placeholder_side_a, by_bracket["3"].placeholder_side_b) == ("WFSEED:17", "WFSEED:24")


def test_placement_seeds_one_through_twenty_four_by_tiebreakers(session):
    import json
    from datetime import date

    from app.models.event import Event
    from app.models.match import Match
    from app.models.schedule_version import ScheduleVersion
    from app.models.team import Team
    from app.models.tournament import Tournament
    from app.services.wf_24_brackets import place_wf24_brackets

    tournament = Tournament(
        name="Seed Test",
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
        team_count=24,
        guarantee_selected=5,
        draw_plan_json=json.dumps({"template_type": "WF_TO_BRACKETS_8", "wf_rounds": 2}),
    )
    session.add(event)
    session.commit()
    session.refresh(event)

    version = ScheduleVersion(tournament_id=tournament.id, version_number=1)
    session.add(version)
    session.commit()
    session.refresh(version)

    teams = []
    for seed in range(1, 25):
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

    for left, right in (
        (1, 13),
        (2, 14),
        (3, 15),
        (4, 16),
        (5, 17),
        (6, 18),
        (7, 19),
        (8, 20),
        (9, 21),
        (10, 22),
        (11, 23),
        (12, 24),
    ):
        add_match(f"R1_{left}", 1, left, right, 6, 4)
    for index, (winner, loser) in enumerate(((1, 7), (2, 8), (3, 9), (4, 10), (5, 11), (6, 12)), start=1):
        add_match(f"R2W_{winner}", 2, winner, loser, 9 - index, 1)
    for index, (winner, loser) in enumerate(((13, 19), (14, 20), (15, 21), (16, 22), (17, 23), (18, 24)), start=1):
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
    session.add(qf)
    session.commit()

    assert place_wf24_brackets(session, tournament.id, version.id, event.id) == 1
    session.refresh(qf)
    # Seeds 1-6 are the 2-0 teams. Seeds 7-8 are the best 1-1 teams, which won
    # round 2 (teams 13 and 14), ahead of round-1 winners who lost round 2.
    assert qf.team_a_id == team_id[1]
    assert qf.team_b_id == team_id[14]
    undefeated = WFTeamResult(team_id=1, bucket_rank=0, wf_matches_won=2, wf_game_diff=4, original_seed=10)
    split_better = WFTeamResult(
        team_id=2, bucket_rank=1, wf_matches_won=1, wf2_game_diff=3, wf_game_diff=1, original_seed=8
    )
    split_worse = WFTeamResult(
        team_id=3, bucket_rank=2, wf_matches_won=1, wf2_game_diff=-2, wf_game_diff=-1, original_seed=1
    )
    winless = WFTeamResult(team_id=4, bucket_rank=3, wf_matches_won=0, wf_game_diff=-6, original_seed=2)
    ranked = sorted(
        [winless, split_worse, undefeated, split_better],
        key=lambda result: wf_overall_seed_key(result, 1, 1),
    )
    assert [result.team_id for result in ranked] == [1, 2, 3, 4]
