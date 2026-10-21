"""Pool codes used by round-robin standings."""

from datetime import date

from app.models.event import Event
from app.models.match import Match
from app.models.schedule_version import ScheduleVersion
from app.models.team import Team
from app.models.tournament import Tournament
from app.services.rr_match_codes import rr_pool_code_for_match

_DIVISIONS = {
    "A": "Division I",
    "B": "Division II",
    "C": "Division III",
    "D": "Division IV",
    "E": "Division V",
    "F": "Division VI",
    "G": "Division VII",
    "H": "Division VIII",
    "I": "Division IX",
}


def test_pool_token_is_recognized_before_and_after_rr():
    for letter in _DIVISIONS:
        assert rr_pool_code_for_match(f"WOM_POOL{letter}_RR_01") == f"POOL{letter}"
        assert rr_pool_code_for_match(f"MIX_E1_RR_POOL{letter}_M01") == f"POOL{letter}"
        assert rr_pool_code_for_match(f"wom_wom_e18_pool{letter.lower()}_rr_03") == f"POOL{letter}"

    assert rr_pool_code_for_match("WB_POOLA_RR_01") == "POOLA"
    assert rr_pool_code_for_match("E12_POOLB_RR_01") == "POOLB"
    assert rr_pool_code_for_match("MIX_E1_RR_POOLA_M01") == "POOLA"
    assert rr_pool_code_for_match("MIX_E1_RR_POOLE_M01") == "POOLE"


def test_existing_non_pool_rr_formats_stay_unchanged():
    assert rr_pool_code_for_match(None) is None
    assert rr_pool_code_for_match("") is None
    assert rr_pool_code_for_match("MIX_E1_RR_01") == "E1"
    assert rr_pool_code_for_match("WOM_RR_01") == "WOM"
    assert rr_pool_code_for_match("WOM_E4_CONS_FRI_C01") == "POOLC"
    assert rr_pool_code_for_match("WOM_E4_CONS_SAT1_D02") == "POOLD"
    assert rr_pool_code_for_match("WOM_E4_CONS_SUN_01") is None
    assert rr_pool_code_for_match("MIX_WIN_FRI_A01") == "POOLA"
    assert rr_pool_code_for_match("MIX_WIN_SAT2_B02") == "POOLB"
    assert rr_pool_code_for_match("MIX_FUN_FRI_01") == "FUN"
    assert rr_pool_code_for_match("MIX_LOSS_FRI_01") == "POOLC"
    assert rr_pool_code_for_match("MIX_WIN_SUN_01") is None


def test_standings_labels_for_pools_a_through_i(client, session):
    tournament = Tournament(
        name="RR Pools A-I",
        location="Test Beach",
        timezone="America/New_York",
        start_date=date(2026, 6, 5),
        end_date=date(2026, 6, 7),
    )
    session.add(tournament)
    session.flush()
    version = ScheduleVersion(tournament_id=tournament.id, version_number=1, status="draft")
    session.add(version)
    session.flush()
    event = Event(tournament_id=tournament.id, category="mixed", name="Mixed A", team_count=18)
    classic = Event(tournament_id=tournament.id, category="womens", name="Women's A", team_count=2)
    session.add_all([event, classic])
    session.flush()

    expected_team_by_division = {}
    for index, (letter, division) in enumerate(_DIVISIONS.items()):
        winner = Team(
            event_id=event.id,
            name=f"Pool {letter} Winner",
            seed=index * 2 + 1,
            display_name=f"Pool {letter} Winner",
        )
        opponent = Team(
            event_id=event.id,
            name=f"Pool {letter} Opponent",
            seed=index * 2 + 2,
            display_name=f"Pool {letter} Opponent",
        )
        session.add_all([winner, opponent])
        session.flush()
        session.add(
            Match(
                tournament_id=tournament.id,
                event_id=event.id,
                schedule_version_id=version.id,
                match_code=f"MIX_E1_RR_POOL{letter}_M01",
                match_type="RR",
                round_number=1,
                round_index=1,
                sequence_in_round=1,
                duration_minutes=60,
                team_a_id=winner.id,
                team_b_id=opponent.id,
                placeholder_side_a="Seed 1",
                placeholder_side_b="Seed 2",
                runtime_status="FINAL",
                winner_team_id=winner.id,
                score_json={"display": "6-4"},
            )
        )
        expected_team_by_division[division] = f"Pool {letter} Winner"

    classic_winner = Team(event_id=classic.id, name="Classic Winner", seed=1, display_name="Classic Winner")
    classic_opponent = Team(event_id=classic.id, name="Classic Opponent", seed=2, display_name="Classic Opponent")
    session.add_all([classic_winner, classic_opponent])
    session.flush()
    session.add(
        Match(
            tournament_id=tournament.id,
            event_id=classic.id,
            schedule_version_id=version.id,
            match_code="WOM_POOLA_RR_01",
            match_type="RR",
            round_number=1,
            round_index=1,
            sequence_in_round=1,
            duration_minutes=60,
            team_a_id=classic_winner.id,
            team_b_id=classic_opponent.id,
            placeholder_side_a="Seed 1",
            placeholder_side_b="Seed 2",
            runtime_status="FINAL",
            winner_team_id=classic_winner.id,
            score_json={"display": "6-4"},
        )
    )
    session.commit()

    response = client.get(f"/api/desk/tournaments/{tournament.id}/standings?version_id={version.id}")
    assert response.status_code == 200, response.text
    events = response.json()["events"]
    by_label = {}
    for row in events:
        names = [team["team_display"] for team in row["rows"]]
        by_label.setdefault(row["division_name"], []).extend(names)
    assert set(by_label) == set(_DIVISIONS.values())
    for division, team_name in expected_team_by_division.items():
        assert team_name in by_label[division]
    assert "Classic Winner" in by_label["Division I"]
    assert "Pool E Winner" in by_label["Division V"]
    assert "Pool I Winner" in by_label["Division IX"]
