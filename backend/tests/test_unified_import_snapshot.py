from app.routes.teams import _parse_combined_import_rows
from app.services.canonical_teams import SnapshotTeam, normalize_avoid_group, validate_import_snapshot
from app.services.rw_os_import import snapshot_hash

COMPLETE_TEAM = {
    "teamKey": "11/22",
    "seed": 1,
    "avoidGroup": "A,B",
    "displayName": "Ann / Bea",
    "fullName": "Ann Able, Amelia, FL / Bea Best, Amelia, FL",
    "drawKind": "womens",
    "drawLabel": "Women's",
    "level": 8.5,
    "player1": {
        "rwId": "11",
        "rw_id": "11",
        "name": "Ann Able",
        "city": "Amelia",
        "state": "FL",
        "cellphone": "9045551111",
        "email": "ann@example.com",
        "towelColor": "Blue",
        "rating": 4.5,
        "ratingField": "ntrpRating",
        "identityStatus": "rw_id",
    },
    "player2": {
        "rwId": "22",
        "rw_id": "22",
        "name": "Bea Best",
        "city": "Amelia",
        "state": "FL",
        "cellphone": "9045552222",
        "email": "bea@example.com",
        "towelColor": "Pink",
        "rating": 4.0,
        "ratingField": "ntrpRating",
        "identityStatus": "rw_id",
    },
    "teamRating": 8.5,
    "ratingStatus": "complete",
    "status": "Confirmed",
    "bucket": "active",
    "sourceRecordKeys": ["reg-11", "reg-22"],
}


def _codes(teams):
    return {issue.code for issue in validate_import_snapshot(teams)}


def test_a_complete_team_round_trip_preserves_operational_fields():
    first = SnapshotTeam.from_dict(COMPLETE_TEAM)
    second = SnapshotTeam.from_dict(first.to_dict())
    assert second.team_key == "11/22"
    assert second.seed == 1
    assert second.avoid_group == "A,B"
    assert second.display_name == "Ann / Bea"
    assert second.full_name == "Ann Able, Amelia, FL / Bea Best, Amelia, FL"
    assert second.draw_kind == "womens"
    assert second.level == 8.5
    assert second.team_rating == 8.5
    assert second.player1.rw_id == "11"
    assert second.player1.city == "Amelia"
    assert second.player1.state == "FL"
    assert second.player1.cellphone == "9045551111"
    assert second.player1.email == "ann@example.com"
    assert second.player1.towel_color == "Blue"
    assert second.player1.identity_status == "rw_id"
    assert second.player2.rw_id == "22"
    assert second.player2.towel_color == "Pink"
    assert "missing_player1_cellphone" not in _codes([second])


def test_b_missing_contact_keeps_team_and_reports_diagnostics():
    payload = {
        **COMPLETE_TEAM,
        "player1": {**COMPLETE_TEAM["player1"], "cellphone": None, "email": None},
        "player2": {**COMPLETE_TEAM["player2"], "cellphone": None, "email": None},
    }
    team = SnapshotTeam.from_dict(payload)
    assert team.team_key == "11/22"
    codes = _codes([team])
    assert "missing_player1_cellphone" in codes
    assert "missing_player1_email" in codes
    assert "missing_player2_cellphone" in codes
    assert "missing_player2_email" in codes


def test_c_missing_towel_keeps_team_and_reports_diagnostics():
    payload = {
        **COMPLETE_TEAM,
        "player1": {**COMPLETE_TEAM["player1"], "towelColor": None},
        "player2": {**COMPLETE_TEAM["player2"], "towelColor": None},
    }
    team = SnapshotTeam.from_dict(payload)
    assert team.team_key == "11/22"
    assert "missing_towel_color" in _codes([team])


def test_d_missing_wkw_keeps_team_and_reports_diagnostics():
    payload = {**COMPLETE_TEAM, "avoidGroup": None}
    team = SnapshotTeam.from_dict(payload)
    assert team.team_key == "11/22"
    assert team.avoid_group is None
    assert "missing_who_knows_who" in _codes([team])


def test_e_team_key_stays_rw_id_based():
    team = SnapshotTeam.from_dict(COMPLETE_TEAM)
    assert team.team_key == "11/22"
    assert "904555" not in team.team_key
    assert "ann@" not in team.team_key


def test_f_contact_only_change_does_not_change_structural_source_hash():
    original = {"tournamentId": 244, "updatedAt": "2026-10-10T00:00:00.000Z", "version": "v1", "teams": [COMPLETE_TEAM]}
    changed = {
        **original,
        "teams": [
            {
                **COMPLETE_TEAM,
                "player1": {
                    **COMPLETE_TEAM["player1"],
                    "cellphone": "9045559999",
                    "email": "new@example.com",
                    "towelColor": "Lime",
                    "city": "Jacksonville",
                    "state": "GA",
                },
                "avoidGroup": "B",
                "seed": 9,
                "level": 9.9,
                "displayName": "New / Names",
                "fullName": "New Names, City, ST",
            }
        ],
    }
    assert snapshot_hash(original) == snapshot_hash(changed)


def test_f2_structural_inputs_do_change_source_hash():
    original = {"tournamentId": 244, "updatedAt": "2026-10-10T00:00:00.000Z", "version": "v1", "teams": [COMPLETE_TEAM]}
    for mutated in (
        {**COMPLETE_TEAM, "teamRating": 9.1},
        {**COMPLETE_TEAM, "drawKind": "mixed"},
        {**COMPLETE_TEAM, "status": "Waitlist"},
        {**COMPLETE_TEAM, "bucket": "waitlist"},
        {**COMPLETE_TEAM, "player1": {**COMPLETE_TEAM["player1"], "rating": 5.0}},
        {**COMPLETE_TEAM, "player1": {**COMPLETE_TEAM["player1"], "rwId": "999"}},
    ):
        assert snapshot_hash(original) != snapshot_hash({**original, "teams": [mutated]})


def test_g_wkw_round_trip_uses_combined_normalization():
    assert normalize_avoid_group("A") == "A"
    assert normalize_avoid_group("B") == "B"
    assert normalize_avoid_group("A,B") == "A,B"
    assert normalize_avoid_group("A, B") == "A,B"
    team = SnapshotTeam.from_dict({**COMPLETE_TEAM, "avoidGroup": "A, B"})
    assert SnapshotTeam.from_dict(team.to_dict()).avoid_group == "A,B"


def test_h_combined_report_with_rw_id_columns_parses():
    text = (
        "Seed\tWho knows who\tFirst names team\tFull name, city, state team\tDraw\tLevel\t"
        "RW_ID first player\tRW_ID second player\ttowel color first player\tcellphone first player\t"
        "email first player\ttowel color second player\tcellphone second player\temail second player\n"
        "1\tA,B\tAnn / Bea\tAnn Able, Amelia, FL / Bea Best, Amelia, FL\tWomens\t8.5\t"
        "11\t22\tBlue\t9045551111\tann@example.com\tPink\t9045552222\tbea@example.com"
    )
    parsed, rejected = _parse_combined_import_rows(text)
    assert rejected == []
    assert parsed[0]["p1_rw_id"] == "11"
    assert parsed[0]["p2_rw_id"] == "22"
    assert parsed[0]["avoid_group"] == "A,B"
    assert parsed[0]["p1_cell"] == "9045551111"


def test_i_old_combined_report_without_rw_id_columns_still_parses():
    text = (
        "Seed\tWho knows who\tFirst names team\tFull name, city, state team\tDraw\tLevel\t"
        "towel color first player\tcellphone first player\temail first player\t"
        "towel color second player\tcellphone second player\temail second player\n"
        "1\tB\tAlex / Torrie\tAlex Quiros, PA / Torrie Kline, PA\tWomens\t8.5\t"
        "Blue\t8123612060\talex@mail.com\tPink\t6109696386\ttorrie@mail.com"
    )
    parsed, rejected = _parse_combined_import_rows(text)
    assert rejected == []
    assert parsed[0]["p1_rw_id"] is None
    assert parsed[0]["p2_rw_id"] is None
    assert parsed[0]["avoid_group"] == "B"
    assert parsed[0]["display_name"] == "Alex / Torrie"
    assert parsed[0]["p1_towel_color"] == "Blue"
