"""Championship finals follow the real draw generators for every supported format."""

from datetime import date, time

import random
from sqlmodel import Session, select

from app.models.event import Event
from app.models.match import Match
from app.models.schedule_version import ScheduleVersion
from app.models.team import Team
from app.models.tournament import Tournament
from app.services.dashboard_progression import start_day
from app.services.draw_plan_engine import DrawPlanSpec, _generate_wf_to_brackets_8, generate_matches_for_event
from app.services.result_simulator import simulate_time_slot
from app.services.trophy import championship_final_ids, trophy_board
from tests.test_result_simulator import _copy, _match, _team


def _event(session: Session, tournament: Tournament, name: str, count: int) -> tuple[Event, ScheduleVersion]:
    event = Event(tournament_id=tournament.id, category="mixed", name=name, team_count=count, guarantee_selected=5)
    session.add(event)
    session.flush()
    version = ScheduleVersion(tournament_id=tournament.id, version_number=1, status="draft")
    session.add(version)
    session.flush()
    return event, version


def _spec(event: Event, template: str, count: int, wf_rounds: int, guarantee: int = 5) -> DrawPlanSpec:
    return DrawPlanSpec(
        event_id=event.id,
        event_name=event.name,
        division="Mixed",
        team_count=count,
        template_type=template,
        template_key=template,
        guarantee=guarantee,
        waterfall_rounds=wf_rounds,
        waterfall_minutes=60,
        standard_minutes=105,
        tournament_id=event.tournament_id,
        event_category="mixed",
    )


def _bracket_labels(count: int) -> list[str]:
    if count == 8:
        return ["WW"]
    if count in (12, 16):
        return ["WW", "WL"]
    if count in (24, 28):
        return ["1", "2", "3"]
    return ["WW", "WL", "LW", "LL"]


def test_generated_brackets_have_one_final_per_division(session: Session):
    tournament = Tournament(
        name="Format Cup",
        location="Test",
        timezone="America/Chicago",
        start_date=date(2026, 12, 4),
        end_date=date(2026, 12, 6),
    )
    session.add(tournament)
    session.flush()
    cases = [
        (8, "WF_TO_BRACKETS_8", 2, 5),
        (8, "WF_TO_BRACKETS_8", 2, 4),
        (12, "WF_TO_BRACKETS_8", 2, 5),
        (16, "WF_TO_BRACKETS_8", 2, 5),
        (24, "WF_TO_BRACKETS_8", 2, 5),
        (32, "WF_TO_BRACKETS_8", 2, 5),
        (28, "WF_28_BRACKETS_RR", 2, 5),
    ]
    for count, template, wf_rounds, guarantee in cases:
        event, version = _event(session, tournament, f"{template}-{count}-{guarantee}", count)
        spec = _spec(event, template, count, wf_rounds, guarantee)
        matches, warnings = _generate_wf_to_brackets_8(session, version.id, spec, [])
        assert not any("Cannot generate" in warning for warning in warnings)
        finals = [match for match in matches if match.id in championship_final_ids(matches)]
        labels = _bracket_labels(count)
        assert len(finals) == len(labels)
        for label in labels:
            chosen = [match for match in finals if f"_B{label}_M7" in (match.match_code or "")]
            assert len(chosen) == 1
            final = chosen[0]
            assert final.match_type == "MAIN"
            assert final.source_a_role == "WINNER"
            assert final.source_b_role == "WINNER"
            assert final.source_match_a_id and final.source_match_b_id
        consolation_finals = [match for match in matches if (match.match_code or "").endswith("_C3")]
        assert not any(match.id in championship_final_ids(matches) for match in consolation_finals)
        if count == 24:
            quarterfinals = [match for match in matches if match.match_type == "MAIN" and match.round_index == 1]
            assert quarterfinals
            assert all((match.placeholder_side_a or "").startswith("WFSEED:") for match in quarterfinals)
            assert all(match.source_a_role is None for match in quarterfinals)


def test_round_robin_formats_have_no_championship_final(session: Session):
    tournament = Tournament(
        name="Pool Cup",
        location="Test",
        timezone="America/Chicago",
        start_date=date(2026, 12, 4),
        end_date=date(2026, 12, 6),
    )
    session.add(tournament)
    session.flush()
    session._allow_match_generation = True
    formats = [
        ("RR_ONLY", 2, 0),
        ("WF_TO_POOLS_4", 16, 2),
        ("WF_TO_POOLS_DYNAMIC", 8, 1),
        ("WF_TO_POOLS_DYNAMIC", 24, 2),
        ("WF_TO_POOLS_DYNAMIC", 28, 2),
        ("WF_10_SIX_FOUR", 10, 1),
        ("WF_12_RAIN_SIX", 12, 0),
        ("WF_14_TOP2_BYE", 14, 2),
    ]
    for template, count, wf_rounds in formats:
        event, version = _event(session, tournament, f"{template}-{count}", count)
        for seed in range(1, count + 1):
            session.add(Team(event_id=event.id, name=f"{template} {seed}", seed=seed, rating=float(1500 - seed)))
        session.flush()
        teams = session.exec(select(Team).where(Team.event_id == event.id)).all()
        spec = _spec(event, template, count, wf_rounds, 5)
        matches, _warnings = generate_matches_for_event(session, version.id, spec, [team.id for team in teams], set())
        assert championship_final_ids(matches) == set()
        if template == "WF_14_TOP2_BYE":
            assert any(match.match_type == "MAIN" for match in matches)
            assert any("BYE" in (match.match_code or "") for match in matches)


def test_simulator_completes_a_championship_final(session: Session):
    tournament, version, event = _copy(session, name="Format Cup (Copy)", source_id=18)
    alpha, beta = _team(session, event, "Alpha", 1), _team(session, event, "Beta", 2)
    semi = _match(session, tournament, version, event, 2, time(9, 0), (alpha, beta), "WB_BWW_M5")
    semi.match_type = "MAIN"
    semi.runtime_status = "FINAL"
    semi.winner_team_id = alpha.id
    semi.score_json = {"display": "8-2"}
    session.add(semi)
    session.flush()
    final = _match(session, tournament, version, event, 1, time(9, 0), (alpha, beta), "WB_BWW_M7")
    final.match_type = "MAIN"
    final.round_index = 3
    final.source_match_a_id = semi.id
    final.source_b_role = "WINNER"
    final.source_a_role = "WINNER"
    final.source_match_b_id = semi.id
    session.add(final)
    session.commit()
    assert championship_final_ids([semi, final]) == {final.id}
    start_day(session, tournament, version, date(2026, 12, 4))
    session.commit()
    summary = simulate_time_slot(session, tournament, version, date(2026, 12, 4), "09:00", rng=random.Random(1))
    assert summary["completed"] == 1
    session.expire_all()
    saved = session.get(Match, final.id)
    board = trophy_board(session, tournament.id, [semi, saved])
    assert board["pending"] == 2
    assert board["finals"][0]["awards"][0]["team_id"] == saved.winner_team_id
    assert {award["role"] for award in board["finals"][0]["awards"]} == {"champion", "runner_up"}
