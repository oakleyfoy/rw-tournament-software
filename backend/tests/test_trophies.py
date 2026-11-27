"""Championship finals come from the winner bracket, not from match names."""

from datetime import date

from sqlmodel import Session, select

from app.models.event import Event
from app.models.match import Match
from app.models.player import Player
from app.models.schedule_version import ScheduleVersion
from app.models.team import Team
from app.models.team_player import TeamPlayer
from app.models.tournament import Tournament
from app.models.trophy_distribution import TrophyDistribution
from app.services.rr_standings import project_pool_outlook
from app.services.trophy import (
    championship_final_ids,
    is_championship_rr_match,
    mark_distributed,
    rr_last_match_teams,
    rr_match_marks,
    trophy_board,
    undo_distribution,
)


def _shell(session: Session):
    tournament = Tournament(
        name="Trophy Cup",
        location="Test",
        timezone="America/Chicago",
        start_date=date(2026, 12, 4),
        end_date=date(2026, 12, 6),
    )
    session.add(tournament)
    session.flush()
    version = ScheduleVersion(tournament_id=tournament.id, version_number=1, status="draft")
    event = Event(tournament_id=tournament.id, category="womens", name="Women's B", team_count=8)
    session.add(version)
    session.add(event)
    session.flush()
    return tournament, version, event


def _match(session, tournament, version, event, **kwargs) -> Match:
    match = Match(
        tournament_id=tournament.id,
        event_id=event.id,
        schedule_version_id=version.id,
        match_code=kwargs.pop("match_code"),
        match_type=kwargs.pop("match_type"),
        round_number=kwargs.pop("round_number", 1),
        round_index=kwargs.pop("round_index", 1),
        sequence_in_round=kwargs.pop("sequence_in_round", 1),
        duration_minutes=60,
        placeholder_side_a=kwargs.pop("placeholder_side_a", "A"),
        placeholder_side_b=kwargs.pop("placeholder_side_b", "B"),
        **kwargs,
    )
    session.add(match)
    session.flush()
    return match


def _team(session, event, name) -> Team:
    team = Team(event_id=event.id, name=name, display_name=name)
    session.add(team)
    session.flush()
    return team


def test_main_draw_final_is_the_winner_terminal_match(session: Session):
    tournament, version, event = _shell(session)
    quarter = _match(session, tournament, version, event, match_code="WB_BWW_M1", match_type="MAIN", round_index=1)
    semi = _match(
        session, tournament, version, event,
        match_code="WB_BWW_M5", match_type="MAIN", round_index=2,
        source_match_a_id=quarter.id, source_a_role="WINNER",
        source_match_b_id=quarter.id, source_b_role="WINNER",
    )
    final = _match(
        session, tournament, version, event,
        match_code="WB_BWW_M7", match_type="MAIN", round_index=3,
        source_match_a_id=semi.id, source_a_role="WINNER",
        source_match_b_id=semi.id, source_b_role="WINNER",
    )
    consolation = _match(
        session, tournament, version, event,
        match_code="WB_BWW_C3", match_type="CONSOLATION", round_index=2,
        source_match_a_id=quarter.id, source_a_role="WINNER",
        source_match_b_id=quarter.id, source_b_role="WINNER",
    )
    placement = _match(session, tournament, version, event, match_code="WB_PLACE_1", match_type="PLACEMENT")
    waterfall = _match(session, tournament, version, event, match_code="WB_WF_R1_01", match_type="WF")
    mislabeled = _match(session, tournament, version, event, match_code="WB_CONS_FRI_A01", match_type="MAIN", round_index=3)
    matches = [quarter, semi, final, consolation, placement, waterfall, mislabeled]
    assert championship_final_ids(matches) == {final.id}
    unwired = _match(session, tournament, version, event, match_code="WB_BWL_M7", match_type="MAIN", round_index=3)
    fed_semi = _match(
        session, tournament, version, event,
        match_code="WB_BWL_M5", match_type="MAIN", round_index=2,
        source_match_a_id=quarter.id, source_a_role="WINNER",
        source_match_b_id=quarter.id, source_b_role="WINNER",
    )
    blank_role = _match(
        session, tournament, version, event,
        match_code="WB_BLW_M6", match_type="MAIN", round_index=2,
        source_match_a_id=quarter.id, source_a_role=None,
        source_match_b_id=quarter.id, source_b_role=None,
    )
    assert championship_final_ids([unwired, fed_semi, consolation, mislabeled]) == {unwired.id}
    assert blank_role.id in championship_final_ids([quarter, blank_role])


def test_round_robin_uses_standings_and_not_the_last_match(session: Session):
    tournament, version, event = _shell(session)
    teams = [_team(session, event, name) for name in ("Alpha Team", "Beta Team", "Gamma Team")]
    for team, player_name in zip(teams, ("Ann Alpha", "Bea Beta", "Gia Gamma")):
        player = Player(tournament_id=tournament.id, full_name=player_name)
        session.add(player)
        session.flush()
        session.add(TeamPlayer(team_id=team.id, player_id=player.id, lineup_slot=1))
    session.flush()
    first = _match(
        session, tournament, version, event, match_code="WB_POOLA_RR_01", match_type="RR",
        team_a_id=teams[0].id, team_b_id=teams[1].id, runtime_status="FINAL", winner_team_id=teams[0].id,
        score_json={"display": "8-3"},
    )
    second = _match(
        session, tournament, version, event, match_code="WB_POOLA_RR_02", match_type="RR",
        team_a_id=teams[0].id, team_b_id=teams[2].id, runtime_status="SCHEDULED",
    )
    third = _match(
        session, tournament, version, event, match_code="WB_POOLA_RR_03", match_type="RR",
        team_a_id=teams[1].id, team_b_id=teams[2].id, runtime_status="SCHEDULED",
    )
    fun = _match(session, tournament, version, event, match_code="WB_FUN_FRI_01", match_type="RR", placement_type="WF10_FUN")
    loss = _match(session, tournament, version, event, match_code="WB_LOSS_FRI_01", match_type="RR")
    assert is_championship_rr_match(first)
    assert not is_championship_rr_match(fun)
    assert not is_championship_rr_match(loss)
    assert championship_final_ids([first, second, third]) == set()
    marks = rr_last_match_teams([first, second, third])
    assert teams[0].id in marks[second.id]
    assert teams[1].id in marks[third.id]
    assert teams[2].id not in marks.get(second.id, [])
    assert teams[2].id not in marks.get(third.id, [])
    board = trophy_board(session, tournament.id, [first, second, third])
    assert board["groups"] == []
    second.runtime_status = "FINAL"
    second.winner_team_id = teams[0].id
    second.score_json = {"display": "8-4"}
    third.runtime_status = "FINAL"
    third.winner_team_id = teams[1].id
    third.score_json = {"display": "8-2"}
    session.add(second)
    session.add(third)
    session.flush()
    board = trophy_board(session, tournament.id, [first, second, third])
    assert board["groups"][0]["official"] is True
    assert board["groups"][0]["awards"][0]["team_id"] == teams[0].id
    assert board["groups"][0]["awards"][0]["players"] == ["Ann Alpha"]
    assert board["groups"][0]["awards"][1]["team_id"] == teams[1].id
    assert board["pending"] == 2
    _contenders, champions, runners = rr_match_marks([first, second, third])
    assert champions
    assert runners
    assert teams[0].id in champions[max(champions)]
    assert teams[1].id in runners[max(runners)]


def test_tied_standings_do_not_award_trophies(session: Session):
    tournament, version, event = _shell(session)
    alpha = _team(session, event, "Alpha Team")
    beta = _team(session, event, "Beta Team")
    only = _match(
        session, tournament, version, event, match_code="WB_POOLA_RR_01", match_type="RR",
        team_a_id=alpha.id, team_b_id=beta.id, runtime_status="FINAL", winner_team_id=alpha.id,
        score_json={"display": "8-6"},
    )
    mirror = _match(
        session, tournament, version, event, match_code="WB_POOLA_RR_02", match_type="RR",
        team_a_id=alpha.id, team_b_id=beta.id, runtime_status="FINAL", winner_team_id=beta.id,
        score_json={"display": "6-8"},
    )
    board = trophy_board(session, tournament.id, [only, mirror])
    assert board["groups"][0]["official"] is False
    assert board["groups"][0]["unresolved_reason"] == "Tiebreak Review Required"
    assert board["groups"][0]["awards"] == []
    assert board["pending"] == 0


def test_distribution_stays_with_the_confirmed_team(session: Session, client):
    tournament, version, event = _shell(session)
    winner = _team(session, event, "Cup Winners")
    loser = _team(session, event, "Cup Runners")
    other = _team(session, event, "Other Side")
    semi = _match(session, tournament, version, event, match_code="WB_BWW_M5", match_type="MAIN", round_index=2)
    final = _match(
        session, tournament, version, event,
        match_code="WB_BWW_M7", match_type="MAIN", round_index=3,
        team_a_id=winner.id, team_b_id=loser.id,
        source_match_a_id=semi.id, source_a_role="WINNER",
        source_match_b_id=semi.id, source_b_role="WINNER",
        runtime_status="FINAL", winner_team_id=winner.id, score_json={"display": "8-5"},
    )
    board = trophy_board(session, tournament.id, [semi, final])
    key = board["finals"][0]["awards"][0]["award_key"]
    mark_distributed(session, tournament.id, version.id, key, winner.id)
    again = client.post(
        f"/api/desk/tournaments/{tournament.id}/trophies",
        json={"version_id": version.id, "award_key": key, "team_id": winner.id},
    )
    assert again.status_code == 409
    final.winner_team_id = loser.id
    final.team_a_id = loser.id
    final.team_b_id = other.id
    session.add(final)
    session.commit()
    reviewed = trophy_board(session, tournament.id, [semi, final])
    award = reviewed["finals"][0]["awards"][0]
    assert award["team_id"] == loser.id
    assert award["distributed"] is False
    assert award["review_required"] is True
    assert award["confirmed_team_id"] == winner.id
    blocked = client.post(
        f"/api/desk/tournaments/{tournament.id}/trophies",
        json={"version_id": version.id, "award_key": key, "team_id": loser.id},
    )
    assert blocked.status_code == 409
    undo_distribution(session, tournament.id, key)
    mark_distributed(session, tournament.id, version.id, key, loser.id)
    saved = session.exec(select(TrophyDistribution).where(TrophyDistribution.tournament_id == tournament.id)).all()
    assert [row.team_id for row in saved] == [loser.id]


def test_copy_records_stay_on_their_tournament(session: Session):
    original, version, event = _shell(session)
    copy = Tournament(
        name="Trophy Cup (Copy)",
        location="Test",
        timezone="America/Chicago",
        start_date=date(2026, 12, 4),
        end_date=date(2026, 12, 6),
        duplicated_from_tournament_id=original.id,
    )
    session.add(copy)
    session.flush()
    team = _team(session, event, "Cup Winners")
    session.add(TrophyDistribution(tournament_id=original.id, award_key="main:1:champion", team_id=team.id, role="champion"))
    session.commit()
    assert trophy_board(session, copy.id, [])["pending"] == 0
    assert session.exec(select(TrophyDistribution).where(TrophyDistribution.tournament_id == copy.id)).all() == []


def test_eliminated_round_robin_team_is_not_a_contender(session: Session):
    tournament, version, event = _shell(session)
    alpha, beta, gamma, delta = [_team(session, event, name) for name in ("Alpha", "Beta", "Gamma", "Delta")]
    played = [
        ("WB_POOLA_RR_01", alpha, beta, alpha, 1),
        ("WB_POOLA_RR_02", alpha, gamma, alpha, 1),
        ("WB_POOLA_RR_03", alpha, delta, alpha, 1),
        ("WB_POOLA_RR_04", beta, gamma, beta, 2),
        ("WB_POOLA_RR_05", beta, delta, beta, 2),
    ]
    matches = []
    for code, side_a, side_b, winner, round_index in played:
        matches.append(_match(
            session, tournament, version, event, match_code=code, match_type="RR",
            team_a_id=side_a.id, team_b_id=side_b.id, runtime_status="FINAL", winner_team_id=winner.id,
            score_json={"display": "8-4"}, round_index=round_index,
        ))
    last = _match(
        session, tournament, version, event, match_code="WB_POOLA_RR_06", match_type="RR",
        team_a_id=gamma.id, team_b_id=delta.id, round_index=3,
    )
    outlook = project_pool_outlook(matches + [last])
    assert outlook.guaranteed_champion == alpha.id
    assert outlook.guaranteed_runner_up == beta.id
    assert gamma.id in outlook.eliminated
    assert delta.id in outlook.eliminated
    marks = rr_last_match_teams(matches + [last])
    assert gamma.id not in marks.get(last.id, [])
    assert delta.id not in marks.get(last.id, [])
    assert trophy_board(session, tournament.id, matches + [last])["groups"] == []
    last.runtime_status = "FINAL"
    last.winner_team_id = gamma.id
    last.score_json = {"display": "8-5"}
    session.add(last)
    session.flush()
    board = trophy_board(session, tournament.id, matches + [last])
    assert board["groups"][0]["official"] is True
    assert [award["team_id"] for award in board["groups"][0]["awards"]] == [alpha.id, beta.id]
    _contenders, champions, runners = rr_match_marks(matches + [last])
    assert alpha.id in champions[matches[2].id]
    assert beta.id in runners[matches[4].id]
