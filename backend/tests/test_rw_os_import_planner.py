import json

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.models.event import Event
from app.models.match import Match
from app.models.tournament_import import TournamentDrawPlan, TournamentImport
from app.services.bracket_split_planner import (
    MAX_BRACKET_SIZE,
    MIN_BRACKET_SIZE,
    generate_split_sizes,
    plan_draw,
    plan_snapshot,
)
from app.services.canonical_teams import (
    SnapshotPlayer,
    SnapshotTeam,
    canonicalize_team_key,
    classify_registration_bucket,
    sort_teams_for_planning,
    validate_import_snapshot,
)
from app.services.draw_catalog import resolve_draw_kind
from app.services.rw_os_client import RwOsClient, RwOsReadOnlyError
from app.services.rw_os_fixtures import EVENTS, get_fixture_event, list_fixture_events
from app.services.team_rating import classify_rating_status, compute_team_rating, parse_rating


def _team(key: str, rating, status="complete", draw="womens") -> SnapshotTeam:
    p1, p2 = key.split("/")
    half = None if rating is None else rating / 2
    return SnapshotTeam(
        team_key=key,
        draw_kind=draw,
        draw_label="Women's",
        player1=SnapshotPlayer(rw_id=p1, name=f"P{p1}", rating=half),
        player2=SnapshotPlayer(rw_id=p2, name=f"P{p2}", rating=half),
        team_rating=rating,
        rating_status=status,
        status="Confirmed",
        bucket="active",
    )


def test_a_only_current_upcoming_events_returned():
    events = list_fixture_events(include_historical=False)
    ids = {event["tournamentId"] for event in events}
    assert 101 not in ids
    assert {148, 244, 280}.issubset(ids)
    assert all(event["eventDate"] >= "2026-08-23" for event in events)


def test_b_already_imported_event_excluded(client: TestClient):
    first = client.post("/api/rw-os/imports", json={"tournament_id": 148, "organization_slug": "rw"})
    assert first.status_code == 201
    listed = client.get("/api/rw-os/events")
    assert listed.status_code == 200
    ids = {event["tournamentId"] for event in listed.json()["events"]}
    assert 148 not in ids
    assert 244 in ids
    duplicate = client.post("/api/rw-os/imports", json={"tournament_id": 148, "organization_slug": "rw"})
    assert duplicate.status_code == 409


def test_c_canonical_team_count_matches_rw_os(client: TestClient):
    fixture = get_fixture_event(148)
    response = client.post("/api/rw-os/imports", json={"tournament_id": 148})
    assert response.status_code == 201
    body = response.json()
    assert body["import"]["sourceTeamCount"] == fixture["teamCount"]
    assert len(body["import"]["teams"]) == fixture["teamCount"]
    assert body["import"]["sourceTeamCount"] == 89
    assert body["drawCounts"]["Women's"] == 78
    assert body["drawCounts"]["Mixed"] == 11


def test_d_withdrawn_team_excluded():
    event = get_fixture_event(148)
    keys = {team["teamKey"] for team in event["teams"]}
    assert "91001/91002" not in keys


def test_e_waitlist_separated(client: TestClient):
    response = client.post("/api/rw-os/imports", json={"tournament_id": 148})
    body = response.json()
    waitlist = body["import"]["waitlistTeams"]
    active_keys = {team["teamKey"] for team in body["import"]["teams"]}
    assert len(waitlist) == 2
    assert all(team["bucket"] == "waitlist" for team in waitlist)
    assert active_keys.isdisjoint({team["teamKey"] for team in waitlist})
    assert body["import"]["sourceTeamCount"] == 89
    assert classify_registration_bucket("WaitList", "womens") == "waitlist"
    assert classify_registration_bucket("Confirmed", "womens_waitlist") == "waitlist"


def test_f_womens_spelling_normalized():
    assert resolve_draw_kind("Women's") == "womens"
    assert resolve_draw_kind("Womens") == "womens"
    assert resolve_draw_kind("Womens (WAITLIST)") == "womens_waitlist"
    assert resolve_draw_kind("Mixed") == "mixed"
    assert resolve_draw_kind("Men's") == "mens"


def test_g_duplicate_team_prevented():
    team = _team("11/22", 8.0)
    dup = _team("11/22", 7.9)
    other = _team("11/33", 7.5)
    issues = validate_import_snapshot([team, dup, other])
    codes = {issue.code for issue in issues}
    assert "duplicate_team_key" in codes
    assert "duplicate_rw_id" in codes


def test_h_team_rating_sorting_correct():
    teams = [
        _team("3/4", None, "missing"),
        _team("5/6", 8.0),
        _team("1/2", 8.0),
        _team("7/8", 7.2),
    ]
    ordered = sort_teams_for_planning(teams)
    assert [team.team_key for team in ordered] == ["1/2", "5/6", "7/8", "3/4"]
    assert compute_team_rating(4.2, 4.1) == 8.3
    assert compute_team_rating(4.2, None) == 4.2
    assert classify_rating_status(4.2, None) == "partial"
    assert compute_team_rating(None, None) is None
    assert parse_rating("0.0") == 0.0
    assert parse_rating("-") is None


def test_i_44_teams_generates_valid_split_options():
    teams = [_team(f"{i}/{i+100}", 10 - (i * 0.05)) for i in range(1, 45)]
    plan = plan_draw("womens", teams)
    size_sets = {tuple(option["sizes"]) for option in plan["options"]}
    assert (32, 12) in size_sets
    assert (28, 16) in size_sets
    assert (24, 20) in size_sets
    assert (20, 24) in size_sets
    assert all(max(option["sizes"]) <= MAX_BRACKET_SIZE for option in plan["options"])


def test_j_80_teams_generates_valid_split_options():
    sizes = set(generate_split_sizes(80))
    assert (32, 32, 16) in sizes
    assert (32, 28, 20) in sizes
    assert (32, 24, 24) in sizes
    assert (28, 28, 24) in sizes


def test_k_no_generated_bracket_over_32():
    for count in (11, 32, 44, 60, 78, 80, 96):
        for parts in generate_split_sizes(count):
            assert max(parts) <= MAX_BRACKET_SIZE


def test_l_avoid_bracket_under_8_unless_unavoidable():
    assert generate_split_sizes(7) == [(7,)]
    for count in (11, 16, 32, 44, 60, 80):
        for parts in generate_split_sizes(count):
            if count >= MIN_BRACKET_SIZE:
                assert all(part >= MIN_BRACKET_SIZE for part in parts)


def test_m_duplicate_partitions_canonicalized():
    sizes = generate_split_sizes(80)
    assert sizes.count((32, 28, 20)) == 1
    assert (20, 28, 32) not in sizes
    assert (28, 32, 20) not in sizes


def test_n_and_o_cut_line_and_gap_correct():
    fixture_teams = [SnapshotTeam.from_dict(row) for row in get_fixture_event(244)["teams"]]
    plan = plan_draw("womens", fixture_teams)
    option = next(item for item in plan["options"] if item["optionKey"] == "20-24")
    cut = option["cuts"][0]
    assert cut["upperRank"] == 20
    assert cut["lowerRank"] == 21
    assert cut["ratingGap"] == round(cut["upperRating"] - cut["lowerRating"], 4)
    assert cut["ratingGap"] > 0.4


def test_p_three_bracket_option_has_two_cut_analyses():
    option = next(
        item
        for item in plan_draw("womens", [SnapshotTeam.from_dict(row) for row in get_fixture_event(280)["teams"]])["options"]
        if item["optionKey"] == "32-32-16"
    )
    assert len(option["cuts"]) == 2
    assert option["cuts"][0]["upperRank"] == 32
    assert option["cuts"][0]["lowerRank"] == 33
    assert option["cuts"][1]["upperRank"] == 64
    assert option["cuts"][1]["lowerRank"] == 65


def test_q_recommendation_uses_rating_break_and_size_quality():
    fixture_teams = [SnapshotTeam.from_dict(row) for row in get_fixture_event(244)["teams"]]
    plan = plan_draw("womens", fixture_teams)
    recommended = next(item for item in plan["options"] if item["recommended"])
    assert recommended["optionKey"] in {"20-24", "24-20"}
    assert recommended["score"]["cutQuality"] > 0
    assert recommended["score"]["sizeQuality"] > 0
    assert any("rating break" in reason.lower() or "healthy" in reason.lower() for reason in recommended["score"]["reasons"])
    sixty = generate_split_sizes(60)
    assert (32, 28) in sixty
    scored_60 = plan_snapshot(
        [_team(f"{i}/{i+200}", 9 - i * 0.02) for i in range(1, 61)]
    )["draws"][0]
    rec_60 = next(item for item in scored_60["options"] if item["recommended"])
    assert rec_60["sizes"] != [32, 20, 8]


def test_r_staff_can_select_non_recommended_option(client: TestClient):
    created = client.post("/api/rw-os/imports", json={"tournament_id": 244})
    import_id = created.json()["import"]["id"]
    recommended = next(item for item in created.json()["planner"]["draws"][0]["options"] if item["recommended"])
    other = next(item for item in created.json()["planner"]["draws"][0]["options"] if not item["recommended"])
    selected = client.post(
        f"/api/rw-os/imports/{import_id}/select-structure",
        json={"draw_kind": "womens", "option_key": other["optionKey"]},
    )
    assert selected.status_code == 200
    plan = selected.json()["selectedPlans"][0]
    assert plan["optionKey"] == other["optionKey"]
    assert plan["optionKey"] != recommended["optionKey"]
    assert plan["approved"] is False


def test_s_approved_plan_persists(client: TestClient, session: Session):
    created = client.post("/api/rw-os/imports", json={"tournament_id": 148})
    import_id = created.json()["import"]["id"]
    womens = next(draw for draw in created.json()["planner"]["draws"] if draw["drawKind"] == "womens")
    mixed = next(draw for draw in created.json()["planner"]["draws"] if draw["drawKind"] == "mixed")
    womens_key = next(option for option in womens["options"] if option["recommended"])["optionKey"]
    mixed_key = mixed["options"][0]["optionKey"]
    approved = client.post(
        f"/api/rw-os/imports/{import_id}/approve",
        json={"selections": {"womens": womens_key, "mixed": mixed_key}},
    )
    assert approved.status_code == 200
    assert approved.json()["import"]["planStatus"] == "approved"
    assert len(approved.json()["approvedPlans"]) == 2
    rows = session.exec(select(TournamentDrawPlan).where(TournamentDrawPlan.import_id == import_id)).all()
    assert {row.draw_kind for row in rows} == {"womens", "mixed"}
    assert all(row.approved for row in rows)
    persisted = json.loads(rows[0].brackets_json)
    assert persisted[0]["label"].startswith("Women's ")
    assert persisted[0]["rankStart"] == 1


def test_t_rw_os_remains_read_only():
    client = RwOsClient(fixtures=True)
    try:
        client._request("POST", "/api/integrations/tournament-software/events")
        assert False, "write should be rejected"
    except RwOsReadOnlyError:
        pass
    assert "POST" not in {method.upper() for method in ("GET",)}
    assert EVENTS[148]["tournamentId"] == 148


def test_no_actual_brackets_or_events_created(client: TestClient, session: Session):
    created = client.post("/api/rw-os/imports", json={"tournament_id": 244})
    import_id = created.json()["import"]["id"]
    tournament_id = created.json()["import"]["tournamentId"]
    option_key = created.json()["planner"]["draws"][0]["options"][0]["optionKey"]
    approved = client.post(
        f"/api/rw-os/imports/{import_id}/approve",
        json={"selections": {"womens": option_key}},
    )
    assert approved.json()["bracketsCreated"] is False
    assert approved.json()["eventsCreated"] == 0
    assert approved.json()["matchesCreated"] == 0
    assert session.exec(select(Event).where(Event.tournament_id == tournament_id)).all() == []
    assert session.exec(select(Match).where(Match.tournament_id == tournament_id)).all() == []


def test_refresh_shows_changes_without_silent_overwrite(client: TestClient, session: Session):
    created = client.post("/api/rw-os/imports", json={"tournament_id": 244})
    import_id = created.json()["import"]["id"]
    original_hash = created.json()["import"]["sourceHash"]
    preview = client.post(f"/api/rw-os/imports/{import_id}/refresh", json={"apply": False})
    assert preview.status_code == 200
    diff = preview.json()["diff"]
    assert diff["changed"] is True
    assert diff["addedCount"] == 1
    assert diff["withdrawnCount"] == 1
    row = session.get(TournamentImport, import_id)
    assert row.source_hash == original_hash
    applied = client.post(f"/api/rw-os/imports/{import_id}/refresh", json={"apply": True})
    assert applied.json()["applied"] is True
    session.refresh(row)
    assert row.source_hash != original_hash


def test_needs_attention_for_invalid_snapshot():
    teams = [_team("11/22", 8.0), _team("11/22", 7.0)]
    issues = validate_import_snapshot(teams)
    assert issues


def test_canonical_team_key_uses_rw_ids_not_names():
    assert canonicalize_team_key(["22", "11"]) == "11/22"


def test_client_get_unknown_event_404():
    try:
        RwOsClient(fixtures=True).get_event(999)
        assert False
    except Exception as exc:
        assert getattr(exc, "status_code", None) == 404
