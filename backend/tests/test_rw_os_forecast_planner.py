"""Forecast-aware planner: expected finals, five scenarios, custom structures."""

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.models.event import Event
from app.models.match import Match
from app.models.tournament_import import TournamentImport
from app.services.bracket_split_planner import (
    AWKWARD_SIZE_PENALTY,
    MAX_BRACKET_SIZE,
    MAX_DEFAULT_SCENARIOS,
    OPERATIONAL_BRACKET_SIZES,
    analyze_custom_structure,
    generate_split_sizes,
    plan_draw,
    validate_custom_sizes,
)
from app.services.canonical_teams import SnapshotPlayer, SnapshotTeam
from app.services.rw_os_client import RwOsClient, RwOsReadOnlyError
from app.services.rw_os_fixtures import get_fixture_event


def _team(key: str, rating, status="complete", draw="womens") -> SnapshotTeam:
    p1, p2 = key.split("/")
    half = None if rating is None else rating / 2
    return SnapshotTeam(
        team_key=key,
        draw_kind=draw,
        draw_label="Women's" if draw == "womens" else "Mixed",
        player1=SnapshotPlayer(rw_id=p1, name=f"P{p1}", rating=half),
        player2=SnapshotPlayer(rw_id=p2, name=f"P{p2}", rating=half),
        team_rating=rating,
        rating_status=status,
        status="Confirmed",
        bucket="active",
    )


def _rated_field(count: int, *, draw="womens", start=10.0, step=0.02, key_offset=0) -> list[SnapshotTeam]:
    return [
        _team(f"{i + key_offset}/{i + key_offset + 1000}", start - (index * step), draw=draw)
        for index, i in enumerate(range(1, count + 1))
    ]


def _amelia_like_field() -> list[SnapshotTeam]:
    return _rated_field(67, draw="womens") + _rated_field(44, draw="mixed", key_offset=5000)


def test_a_current_44_forecast_44_sums():
    plan = plan_draw("mixed", _rated_field(44, draw="mixed"), 44)
    assert plan["currentCount"] == 44
    assert plan["forecastCount"] == 44
    assert plan["options"]
    assert all(sum(option["sizes"]) == 44 for option in plan["options"])


def test_b_current_67_forecast_68_no_fake_team():
    teams = _rated_field(67)
    plan = plan_draw("womens", teams, 68)
    assert plan["currentCount"] == 67
    assert plan["forecastCount"] == 68
    assert all(sum(option["sizes"]) == 68 for option in plan["options"])
    assert all(option["fakeTeamCount"] == 0 for option in plan["options"])
    assert all(not team.get("fake") for team in plan["teams"])
    assert len(plan["teams"]) == 67
    keys = {team["teamKey"] for team in plan["teams"]}
    assert len(keys) == 67
    assert all(bracket.get("unknownTeamCount", 0) >= 0 for option in plan["options"] for bracket in option["brackets"])


def test_c_forecast_greater_than_current_marks_provisional_cut():
    teams = _rated_field(67)
    option = analyze_custom_structure(teams, (32, 24, 12, 12), forecast_count=80)
    assert option["fakeTeamCount"] == 0
    provisional = [cut for cut in option["cuts"] if cut["provisional"]]
    assert provisional
    assert any(cut["upperRank"] > 67 for cut in provisional)
    assert "have not registered" in (provisional[0]["message"] or "")


def test_d_forecast_below_current_uses_current_ratings():
    teams = _rated_field(67)
    plan = plan_draw("womens", teams, 64)
    assert plan["forecastCount"] == 64
    assert plan["shrinkCount"] == 3
    assert "below the current" in (plan["planningNote"] or "")
    assert all(sum(option["sizes"]) == 64 for option in plan["options"])
    known = [cut for option in plan["options"] for cut in option["cuts"] if not cut.get("provisional")]
    assert known
    assert all(cut["upperTeamName"] for cut in known)


def test_e_maximum_five_default_recommendations():
    for count, forecast in ((44, 44), (67, 67), (67, 68), (80, 80)):
        plan = plan_draw("womens", _rated_field(count), forecast)
        assert plan["optionCount"] <= MAX_DEFAULT_SCENARIOS
        assert len(plan["options"]) <= 5


def test_f_best_recommendation_is_first():
    plan = plan_draw("womens", [SnapshotTeam.from_dict(row) for row in get_fixture_event(244)["teams"]])
    assert plan["options"][0]["recommended"] is True
    totals = [option["score"]["total"] for option in plan["options"]]
    assert totals == sorted(totals, reverse=True)


def test_g_alternatives_are_meaningfully_diversified():
    plan = plan_draw("womens", _rated_field(68), 68)
    signatures = {
        (
            tuple(option["sizes"]),
            tuple(cut["upperRank"] for cut in option["cuts"]),
            tuple(sorted(option["sizes"])),
        )
        for option in plan["options"]
    }
    assert len(signatures) == len(plan["options"])
    profiles = [tuple(sorted(option["sizes"])) for option in plan["options"]]
    assert profiles.count(profiles[0]) <= 2


def test_h_clean_sizes_beat_awkward_when_cuts_comparable():
    teams = _rated_field(44, step=0.01)
    plan = plan_draw("womens", teams, 44)
    recommended = plan["options"][0]
    assert all(size in OPERATIONAL_BRACKET_SIZES for size in recommended["sizes"])
    awkward = analyze_custom_structure(teams, (21, 23), forecast_count=44)
    assert awkward["score"]["awkwardSizePenalty"] >= AWKWARD_SIZE_PENALTY
    assert recommended["score"]["total"] > awkward["score"]["total"]


def test_i_awkward_size_can_win_with_material_cut():
    teams = []
    for index in range(1, 45):
        rating = 9.5 if index <= 30 else 4.0 - (index * 0.01)
        teams.append(_team(f"{index}/{index + 800}", rating))
    clean = analyze_custom_structure(teams, (20, 24), forecast_count=44)
    awkward = analyze_custom_structure(teams, (30, 14), forecast_count=44)
    assert any(size not in OPERATIONAL_BRACKET_SIZES for size in awkward["sizes"])
    assert all(size in OPERATIONAL_BRACKET_SIZES for size in clean["sizes"])
    assert awkward["score"]["cutQuality"] > clean["score"]["cutQuality"]
    assert awkward["score"]["total"] > clean["score"]["total"]
    assert awkward["score"]["cutQuality"] - clean["score"]["cutQuality"] >= 16


def test_j_no_returned_bracket_over_32():
    for current, forecast in ((44, 44), (67, 68), (80, 80)):
        plan = plan_draw("womens", _rated_field(current), forecast)
        assert all(max(option["sizes"]) <= MAX_BRACKET_SIZE for option in plan["options"])
        assert all(max(parts) <= MAX_BRACKET_SIZE for parts in generate_split_sizes(forecast))


def test_k_custom_16_20_32_for_forecast_68():
    teams = _rated_field(67)
    option = analyze_custom_structure(teams, (16, 20, 32), forecast_count=68)
    assert option["custom"] is True
    assert option["sizes"] == [16, 20, 32]
    assert option["fakeTeamCount"] == 0


def test_l_custom_wrong_total_rejected():
    try:
        validate_custom_sizes((16, 20, 32), 67)
        assert False
    except ValueError as exc:
        assert "68" in str(exc) or "67" in str(exc) or "expected" in str(exc).lower() or "sum" in str(exc).lower()


def test_m_custom_bracket_over_32_rejected():
    try:
        validate_custom_sizes((36, 32), 68)
        assert False
    except ValueError as exc:
        assert "32" in str(exc)


def test_n_forecast_survives_rw_os_refresh(client: TestClient, session: Session):
    created = client.post("/api/rw-os/imports", json={"tournament_id": 244})
    import_id = created.json()["import"]["id"]
    assert created.json()["import"]["forecasts"]["womens"] == 44
    updated = client.put(f"/api/rw-os/imports/{import_id}/forecasts", json={"forecasts": {"womens": 50}})
    assert updated.status_code == 200
    assert updated.json()["import"]["forecasts"]["womens"] == 50
    applied = client.post(f"/api/rw-os/imports/{import_id}/refresh", json={"apply": True})
    assert applied.status_code == 200
    session.refresh(session.get(TournamentImport, import_id))
    refreshed = client.get(f"/api/rw-os/imports/{import_id}")
    assert refreshed.json()["import"]["forecasts"]["womens"] == 50
    assert refreshed.json()["planner"]["draws"][0]["forecastCount"] == 50


def test_o_reset_forecasts_returns_current_counts(client: TestClient):
    created = client.post("/api/rw-os/imports", json={"tournament_id": 244})
    import_id = created.json()["import"]["id"]
    client.put(f"/api/rw-os/imports/{import_id}/forecasts", json={"forecasts": {"womens": 50}})
    reset = client.post(f"/api/rw-os/imports/{import_id}/forecasts/reset")
    assert reset.status_code == 200
    current = reset.json()["planner"]["draws"][0]["currentCount"]
    assert reset.json()["import"]["forecasts"]["womens"] == current


def test_p_q_r_no_event_match_or_rw_os_writes(client: TestClient, session: Session):
    created = client.post("/api/rw-os/imports", json={"tournament_id": 244})
    import_id = created.json()["import"]["id"]
    tournament_id = created.json()["import"]["tournamentId"]
    client.put(f"/api/rw-os/imports/{import_id}/forecasts", json={"forecasts": {"womens": 44}})
    custom = client.post(
        f"/api/rw-os/imports/{import_id}/custom-structure",
        json={"draw_kind": "womens", "sizes": [20, 24]},
    )
    assert custom.status_code == 200
    approved = client.post(
        f"/api/rw-os/imports/{import_id}/approve",
        json={"selections": {"womens": "20-24"}},
    )
    assert approved.json()["matchesCreated"] == 0
    assert approved.json()["bracketsCreated"] is False
    assert approved.json()["rwOsWrites"] == 0
    expected_events = sum(len(plan["brackets"]) for plan in approved.json()["approvedPlans"])
    assert approved.json()["eventsCreated"] == expected_events
    events = session.exec(select(Event).where(Event.tournament_id == tournament_id)).all()
    assert len(events) == expected_events
    assert session.exec(select(Match).where(Match.tournament_id == tournament_id)).all() == []
    try:
        RwOsClient(fixtures=True)._request("POST", "/api/integrations/tournament-software/events")
        assert False
    except RwOsReadOnlyError:
        pass


def test_s_source_hash_change_detection_still_works(client: TestClient, session: Session):
    created = client.post("/api/rw-os/imports", json={"tournament_id": 244})
    import_id = created.json()["import"]["id"]
    original_hash = created.json()["import"]["sourceHash"]
    preview = client.post(f"/api/rw-os/imports/{import_id}/refresh", json={"apply": False})
    assert preview.json()["diff"]["changed"] is True
    row = session.get(TournamentImport, import_id)
    assert row.source_hash == original_hash
    applied = client.post(f"/api/rw-os/imports/{import_id}/refresh", json={"apply": True})
    assert applied.json()["applied"] is True
    session.refresh(row)
    assert row.source_hash != original_hash


def test_u_44_team_fixture_still_sensible():
    teams = [SnapshotTeam.from_dict(row) for row in get_fixture_event(244)["teams"]]
    plan = plan_draw("womens", teams, 44)
    recommended = plan["options"][0]
    assert recommended["recommended"] is True
    assert recommended["optionKey"] in {"20-24", "24-20", "16-28", "28-16", "32-12", "12-32"}
    assert recommended["score"]["cutQuality"] > 0
    option = analyze_custom_structure(teams, (20, 24))
    assert option["cuts"][0]["ratingGap"] > 0.4


def test_v_ordered_structures_stay_distinct_when_cuts_differ():
    teams = _rated_field(80, step=0.01)
    left = analyze_custom_structure(teams, (32, 28, 20))
    right = analyze_custom_structure(teams, (20, 28, 32))
    assert [cut["upperRank"] for cut in left["cuts"]] != [cut["upperRank"] for cut in right["cuts"]]
    plan = plan_draw("womens", teams, 80)
    keys = [option["optionKey"] for option in plan["options"]]
    assert len(keys) == len(set(keys))


def test_custom_api_accepts_16_20_32_for_forecast_68(client: TestClient):
    created = client.post("/api/rw-os/imports", json={"tournament_id": 244})
    import_id = created.json()["import"]["id"]
    client.put(f"/api/rw-os/imports/{import_id}/forecasts", json={"forecasts": {"womens": 68}})
    ok = client.post(
        f"/api/rw-os/imports/{import_id}/custom-structure",
        json={"draw_kind": "womens", "sizes": [16, 20, 32]},
    )
    assert ok.status_code == 200
    assert ok.json()["customOption"]["sizes"] == [16, 20, 32]
    bad_total = client.post(
        f"/api/rw-os/imports/{import_id}/custom-structure",
        json={"draw_kind": "womens", "sizes": [16, 20, 20]},
    )
    assert bad_total.status_code == 400
    too_big = client.post(
        f"/api/rw-os/imports/{import_id}/custom-structure",
        json={"draw_kind": "womens", "sizes": [36, 32]},
    )
    assert too_big.status_code == 400


def test_invalid_forecast_rejected(client: TestClient):
    created = client.post("/api/rw-os/imports", json={"tournament_id": 244})
    import_id = created.json()["import"]["id"]
    negative = client.put(f"/api/rw-os/imports/{import_id}/forecasts", json={"forecasts": {"womens": -1}})
    assert negative.status_code == 400
    huge = client.put(f"/api/rw-os/imports/{import_id}/forecasts", json={"forecasts": {"womens": 999}})
    assert huge.status_code == 400


def test_amelia_like_current_and_forecast_examples():
    teams = _amelia_like_field()
    mixed = plan_draw("mixed", [team for team in teams if team.draw_kind == "mixed"], 44)
    womens = plan_draw("womens", [team for team in teams if team.draw_kind == "womens"], 68)
    assert mixed["currentCount"] == 44
    assert mixed["forecastCount"] == 44
    assert womens["currentCount"] == 67
    assert womens["forecastCount"] == 68
    assert len(mixed["options"]) <= 5
    assert len(womens["options"]) <= 5
