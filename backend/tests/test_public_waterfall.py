from datetime import date, time

from app.models.event import Event
from app.models.match import Match
from app.models.match_assignment import MatchAssignment
from app.models.schedule_slot import ScheduleSlot
from app.models.schedule_version import ScheduleVersion
from app.models.tournament import Tournament


def test_public_waterfall_roundrobin_dest_uses_pool_seeding_not_four_divisions(client, session):
    tournament = Tournament(
        name="Vegas Public WF",
        location="Las Vegas",
        timezone="America/Chicago",
        start_date=date(2026, 3, 20),
        end_date=date(2026, 3, 22),
    )
    session.add(tournament)
    session.flush()

    version = ScheduleVersion(
        tournament_id=tournament.id,
        version_number=1,
        status="final",
    )
    session.add(version)
    session.flush()

    event = Event(
        tournament_id=tournament.id,
        name="Womens",
        category="womens",
        team_count=12,
        draw_status="final",
        draw_plan_json='{"template_type":"WF_TO_POOLS_DYNAMIC","wf_rounds":2,"guarantee":4}',
    )
    session.add(event)
    session.flush()

    r1 = Match(
        tournament_id=tournament.id,
        event_id=event.id,
        schedule_version_id=version.id,
        match_code="WOM_WF_R1_01",
        match_type="WF",
        round_number=1,
        round_index=1,
        sequence_in_round=1,
        duration_minutes=60,
        placeholder_side_a="Seed 1",
        placeholder_side_b="Seed 7",
    )
    session.add(r1)
    session.flush()

    r2_w = Match(
        tournament_id=tournament.id,
        event_id=event.id,
        schedule_version_id=version.id,
        match_code="WOM_WF_R2_W01",
        match_type="WF",
        round_number=2,
        round_index=2,
        sequence_in_round=1,
        duration_minutes=60,
        source_match_a_id=r1.id,
        source_a_role="WINNER",
        placeholder_side_a="W(R1_1)",
        placeholder_side_b="W(R1_2)",
    )
    r2_l = Match(
        tournament_id=tournament.id,
        event_id=event.id,
        schedule_version_id=version.id,
        match_code="WOM_WF_R2_L01",
        match_type="WF",
        round_number=2,
        round_index=2,
        sequence_in_round=4,
        duration_minutes=60,
        source_match_a_id=r1.id,
        source_a_role="LOSER",
        placeholder_side_a="L(R1_1)",
        placeholder_side_b="L(R1_2)",
    )
    rr = Match(
        tournament_id=tournament.id,
        event_id=event.id,
        schedule_version_id=version.id,
        match_code="WOM_POOLA_RR_01",
        match_type="RR",
        round_number=1,
        round_index=1,
        sequence_in_round=1,
        duration_minutes=120,
        placeholder_side_a="SEED_1",
        placeholder_side_b="SEED_4",
    )
    session.add(r2_w)
    session.add(r2_l)
    session.add(rr)
    tournament.public_schedule_version_id = version.id
    session.add(tournament)
    session.commit()

    resp = client.get(f"/api/public/tournaments/{tournament.id}/events/{event.id}/waterfall")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["division_type"] == "roundrobin"
    assert len(body["rows"]) == 1
    winner_dest = body["rows"][0]["winner_dest"]
    loser_dest = body["rows"][0]["loser_dest"]
    assert "3 pools × 4 teams" in winner_dest
    assert "3 pools × 4 teams" in loser_dest
    assert "Division IV" not in winner_dest
    assert "Division IV" not in loser_dest


def test_public_waterfall_hides_match_and_court_info_in_checkin_management(client, session):
    tournament = Tournament(
        name="Vegas Public WF Checkin",
        location="Las Vegas",
        timezone="America/Chicago",
        start_date=date(2026, 3, 20),
        end_date=date(2026, 3, 22),
        desk_management_mode="checkin_management",
    )
    session.add(tournament)
    session.flush()

    version = ScheduleVersion(
        tournament_id=tournament.id,
        version_number=1,
        status="final",
    )
    session.add(version)
    session.flush()

    event = Event(
        tournament_id=tournament.id,
        name="Womens",
        category="womens",
        team_count=8,
        draw_status="final",
        draw_plan_json='{"template_type":"WF_TO_POOLS_DYNAMIC","wf_rounds":1,"guarantee":4}',
    )
    session.add(event)
    session.flush()

    match = Match(
        tournament_id=tournament.id,
        event_id=event.id,
        schedule_version_id=version.id,
        match_code="WOM_WF_R1_01",
        match_type="WF",
        round_number=1,
        round_index=1,
        sequence_in_round=1,
        duration_minutes=60,
        placeholder_side_a="Seed 1",
        placeholder_side_b="Seed 8",
    )
    session.add(match)
    session.flush()

    slot = ScheduleSlot(
        tournament_id=tournament.id,
        schedule_version_id=version.id,
        day_date=date(2026, 3, 20),
        start_time=time(9, 0),
        end_time=time(10, 0),
        court_number=1,
        court_label="1",
        block_minutes=60,
    )
    session.add(slot)
    session.flush()
    session.add(MatchAssignment(schedule_version_id=version.id, match_id=match.id, slot_id=slot.id))

    tournament.public_schedule_version_id = version.id
    session.add(tournament)
    session.commit()

    resp = client.get(f"/api/public/tournaments/{tournament.id}/events/{event.id}/waterfall")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["show_court_info"] is False
    top_line = body["rows"][0]["center_box"]["top_line"]
    assert "Match #" in top_line
    assert "Court" not in top_line


def test_public_waterfall_bracket_four_division_names_from_final_r2(client, session):
    """Destination API lists both outcomes for each R2 track (I/II and III/IV)."""
    from app.models.team import Team

    tournament = Tournament(
        name="WF Bracket Public",
        location="KC",
        timezone="America/Chicago",
        start_date=date(2026, 5, 15),
        end_date=date(2026, 5, 17),
    )
    session.add(tournament)
    session.flush()

    version = ScheduleVersion(
        tournament_id=tournament.id,
        version_number=1,
        status="final",
    )
    session.add(version)
    session.flush()

    event = Event(
        tournament_id=tournament.id,
        name="Womens",
        category="womens",
        team_count=8,
        draw_status="final",
        draw_plan_json='{"template_type":"WF_TO_BRACKETS_8","wf_rounds":2,"guarantee":4}',
    )
    session.add(event)
    session.flush()

    t1 = Team(event_id=event.id, name="Alice / Ann", seed=1)
    t2 = Team(event_id=event.id, name="Bob / Ben", seed=2)
    t3 = Team(event_id=event.id, name="Cara / Cyd", seed=3)
    t4 = Team(event_id=event.id, name="Dana / Dee", seed=4)
    session.add_all([t1, t2, t3, t4])
    session.flush()

    r1a = Match(
        tournament_id=tournament.id,
        event_id=event.id,
        schedule_version_id=version.id,
        match_code="WOM_WF_R1_01",
        match_type="WF",
        round_number=1,
        round_index=1,
        sequence_in_round=1,
        duration_minutes=60,
        placeholder_side_a="Seed 1",
        placeholder_side_b="Seed 2",
        team_a_id=t1.id,
        team_b_id=t2.id,
        winner_team_id=t1.id,
        runtime_status="FINAL",
    )
    r1b = Match(
        tournament_id=tournament.id,
        event_id=event.id,
        schedule_version_id=version.id,
        match_code="WOM_WF_R1_02",
        match_type="WF",
        round_number=1,
        round_index=1,
        sequence_in_round=2,
        duration_minutes=60,
        placeholder_side_a="Seed 3",
        placeholder_side_b="Seed 4",
        team_a_id=t3.id,
        team_b_id=t4.id,
        winner_team_id=t3.id,
        runtime_status="FINAL",
    )
    session.add(r1a)
    session.add(r1b)
    session.flush()

    r2w = Match(
        tournament_id=tournament.id,
        event_id=event.id,
        schedule_version_id=version.id,
        match_code="WOM_WF_R2_W01",
        match_type="WF",
        round_number=2,
        round_index=2,
        sequence_in_round=1,
        duration_minutes=60,
        placeholder_side_a="W(R1_1)",
        placeholder_side_b="W(R1_2)",
        source_match_a_id=r1a.id,
        source_a_role="WINNER",
        source_match_b_id=r1b.id,
        source_b_role="WINNER",
        team_a_id=t1.id,
        team_b_id=t3.id,
        winner_team_id=t1.id,
        runtime_status="FINAL",
    )
    r2l = Match(
        tournament_id=tournament.id,
        event_id=event.id,
        schedule_version_id=version.id,
        match_code="WOM_WF_R2_L01",
        match_type="WF",
        round_number=2,
        round_index=2,
        sequence_in_round=2,
        duration_minutes=60,
        placeholder_side_a="L(R1_1)",
        placeholder_side_b="L(R1_2)",
        source_match_a_id=r1a.id,
        source_a_role="LOSER",
        source_match_b_id=r1b.id,
        source_b_role="LOSER",
        team_a_id=t2.id,
        team_b_id=t4.id,
        winner_team_id=t2.id,
        runtime_status="FINAL",
    )
    session.add(r2w)
    session.add(r2l)
    tournament.public_schedule_version_id = version.id
    session.add(tournament)
    session.commit()

    resp = client.get(f"/api/public/tournaments/{tournament.id}/events/{event.id}/waterfall")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["division_type"] == "bracket"
    row = body["rows"][0]
    assert row["r2_winner_bracket_winner_name"] == "Alice / Ann"
    assert row["r2_winner_bracket_loser_name"] == "Cara / Cyd"
    assert row["r2_loser_bracket_winner_name"] == "Bob / Ben"
    assert row["r2_loser_bracket_loser_name"] == "Dana / Dee"
    assert row["r2_winner_team_name"] == "Alice / Ann"
    assert row["r2_loser_team_name"] == "Bob / Ben"


def test_public_waterfall_wf14_byes_render_top_and_bottom(client, session):
    """WF_14 bye R1 matches are pre-bound onto R2 sides (no source_match).

    The #1 seed bye should render at the TOP paired with its R2 winner box,
    and the #2 seed bye at the BOTTOM — even though neither carries a
    source_match link.
    """
    from app.models.team import Team

    tournament = Tournament(
        name="WF14 Bye Layout",
        location="KC",
        timezone="America/Chicago",
        start_date=date(2026, 7, 24),
        end_date=date(2026, 7, 26),
    )
    session.add(tournament)
    session.flush()

    version = ScheduleVersion(tournament_id=tournament.id, version_number=1, status="final")
    session.add(version)
    session.flush()

    event = Event(
        tournament_id=tournament.id,
        name="Womens",
        category="womens",
        team_count=14,
        draw_status="final",
        draw_plan_json='{"template_type":"WF_14_TOP2_BYE","wf_rounds":2,"guarantee":4}',
    )
    session.add(event)
    session.flush()

    alex = Team(event_id=event.id, name="Alex / Torrie", seed=1)
    cat = Team(event_id=event.id, name="Catalina / Gricel", seed=2)
    m1a = Team(event_id=event.id, name="Lori / Paulina", seed=3)
    m2a = Team(event_id=event.id, name="Maria / Marie", seed=4)
    session.add_all([alex, cat, m1a, m2a])
    session.flush()

    def _mk(code, seq, **kw):
        m = Match(
            tournament_id=tournament.id,
            event_id=event.id,
            schedule_version_id=version.id,
            match_code=code,
            match_type="WF",
            round_number=kw.pop("round_number", 1),
            round_index=kw.pop("round_index", 1),
            sequence_in_round=seq,
            duration_minutes=60,
            **kw,
        )
        session.add(m)
        session.flush()
        return m

    match1 = _mk("WOM_WF_R1_01", 1, team_a_id=m1a.id, placeholder_side_a="Seed 3", placeholder_side_b="Seed 12")
    match2 = _mk("WOM_WF_R1_02", 2, team_a_id=m2a.id, placeholder_side_a="Seed 4", placeholder_side_b="Seed 11")
    bye_top = _mk(
        "WOM_WF_R1_BYE_TOP",
        7,
        team_a_id=alex.id,
        team_b_id=None,
        placeholder_side_a="Alex / Torrie",
        placeholder_side_b="BYE",
        winner_team_id=alex.id,
        runtime_status="FINAL",
        status="complete",
    )
    bye_bot = _mk(
        "WOM_WF_R1_BYE_BOT",
        8,
        team_a_id=cat.id,
        team_b_id=None,
        placeholder_side_a="Catalina / Gricel",
        placeholder_side_b="BYE",
        winner_team_id=cat.id,
        runtime_status="FINAL",
        status="complete",
    )

    # R2 top: #1 seed (bye, side A) vs winner of match 2 (side B, source).
    r2_top = _mk(
        "WOM_WF_R2_01",
        1,
        round_number=2,
        round_index=2,
        team_a_id=alex.id,
        placeholder_side_a="Alex / Torrie",
        placeholder_side_b="W(R1_2)",
        source_match_b_id=match2.id,
        source_b_role="WINNER",
    )
    # R2 bottom: winner of match 1 (side A, source) vs #2 seed (bye, side B).
    r2_bot = _mk(
        "WOM_WF_R2_02",
        2,
        round_number=2,
        round_index=2,
        team_b_id=cat.id,
        placeholder_side_a="W(R1_1)",
        placeholder_side_b="Catalina / Gricel",
        source_match_a_id=match1.id,
        source_a_role="WINNER",
    )

    tournament.public_schedule_version_id = version.id
    session.add(tournament)
    session.commit()

    resp = client.get(f"/api/public/tournaments/{tournament.id}/events/{event.id}/waterfall")
    assert resp.status_code == 200, resp.text
    rows = resp.json()["rows"]

    center_ids = [r["center_box"]["match_id"] for r in rows]
    # Top bye first, then its R2 partner (match 2); bottom bye last.
    assert center_ids[0] == bye_top.id
    assert center_ids[1] == match2.id
    assert center_ids[-1] == bye_bot.id

    # The top bye row carries the R2 box where the #1 seed plays.
    top_winner = rows[0]["winner_box"]
    assert top_winner is not None
    assert top_winner["match_id"] == r2_top.id
    assert top_winner["team_a_id"] == alex.id

    # The bottom bye's partner row (winner of match 1) carries the bottom R2 box.
    m1_row = next(r for r in rows if r["center_box"]["match_id"] == match1.id)
    assert m1_row["winner_box"] is not None
    assert m1_row["winner_box"]["match_id"] == r2_bot.id
    assert m1_row["winner_box"]["team_b_id"] == cat.id


def test_public_roundrobin_wf14_includes_consolation_pools_c_and_d(client, session):
    """WF_14 loser-flight pools C/D (3-team RRs stored as consolation matches)
    should appear as Division III / IV alongside the winner-flight A/B pools."""
    tournament = Tournament(
        name="WF14 Pools CD",
        location="KC",
        timezone="America/Chicago",
        start_date=date(2026, 7, 24),
        end_date=date(2026, 7, 26),
    )
    session.add(tournament)
    session.flush()

    version = ScheduleVersion(tournament_id=tournament.id, version_number=1, status="final")
    session.add(version)
    session.flush()

    event = Event(
        tournament_id=tournament.id,
        name="Womens",
        category="womens",
        team_count=14,
        draw_status="final",
        draw_plan_json='{"template_type":"WF_14_TOP2_BYE","wf_rounds":2,"guarantee":4}',
    )
    session.add(event)
    session.flush()

    def _mk(code, mtype, rnd, seq, pa, pb, **kw):
        m = Match(
            tournament_id=tournament.id,
            event_id=event.id,
            schedule_version_id=version.id,
            match_code=code,
            match_type=mtype,
            round_number=rnd,
            round_index=rnd,
            sequence_in_round=seq,
            duration_minutes=90,
            placeholder_side_a=pa,
            placeholder_side_b=pb,
            **kw,
        )
        session.add(m)
        return m

    # Winner-flight pools A/B (standard RR).
    _mk("WOM_POOLA_RR_01", "RR", 1, 1, "SEED_1", "SEED_4")
    _mk("WOM_POOLB_RR_01", "RR", 1, 1, "SEED_2", "SEED_3")

    # Loser-flight pools C {1,4,6} and D {2,3,5} — 3-team round robins.
    _mk("WOM_CONS_FRI_C01", "MAIN", 1, 1, "ConsL1", "ConsL6")
    _mk("WOM_CONS_SAT1_C01", "MAIN", 2, 1, "ConsL4", "ConsL6")
    _mk("WOM_CONS_SAT2_C01", "MAIN", 3, 1, "ConsL1", "ConsL4")
    _mk("WOM_CONS_FRI_D02", "MAIN", 1, 2, "ConsL2", "ConsL5")
    _mk("WOM_CONS_SAT1_D02", "MAIN", 2, 2, "ConsL3", "ConsL5")
    _mk("WOM_CONS_SAT2_D02", "MAIN", 3, 2, "ConsL2", "ConsL3")

    # Sunday cross-pool placement — its own round, not inside a pool RR.
    _mk("WOM_CONS_SUN_01", "PLACEMENT", 1, 1, "C1", "D1", placement_type="WF14_CONS_CROSS")
    _mk("WOM_CONS_SUN_02", "PLACEMENT", 1, 2, "C2", "D2", placement_type="WF14_CONS_CROSS")
    _mk("WOM_CONS_SUN_03", "PLACEMENT", 1, 3, "C3", "D3", placement_type="WF14_CONS_CROSS")

    tournament.public_schedule_version_id = version.id
    session.add(tournament)
    session.commit()

    resp = client.get(f"/api/public/tournaments/{tournament.id}/events/{event.id}/roundrobin")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    pools = {p["pool_code"]: p for p in body["pools"]}
    assert set(pools) == {"POOLA", "POOLB", "POOLC", "POOLD", "CD_PLACEMENT"}
    assert pools["POOLC"]["pool_label"] == "Division III"
    assert pools["POOLD"]["pool_label"] == "Division IV"

    # Pool C/D are full 3-team round robins (3 matches each), no cross-placement.
    assert len(pools["POOLC"]["matches"]) == 3
    assert len(pools["POOLD"]["matches"]) == 3
    for pc in ("POOLC", "POOLD"):
        codes = [b["match_code"] for b in pools[pc]["matches"]]
        assert not any("_SUN_" in c for c in codes)

    # Placeholders render cleanly.
    c_lines = {pools["POOLC"]["matches"][0]["line1"], pools["POOLC"]["matches"][0]["line2"]}
    assert "Cons Seed 1" in c_lines

    # Cross-pool placement round (III#1 vs IV#1, …) is its own section, sorted last.
    assert body["pools"][-1]["pool_code"] == "CD_PLACEMENT"
    placement = pools["CD_PLACEMENT"]
    assert len(placement["matches"]) == 3
    lines = [(b["line1"], b["line2"]) for b in placement["matches"]]
    assert lines == [("III #1", "IV #1"), ("III #2", "IV #2"), ("III #3", "IV #3")]


def test_public_roundrobin_wf14_finalized_cons_scores_do_not_500(client, session):
    """Regression: finalized consolation (C/D) pool matches whose score_json uses
    varied real-world shapes (list-of-lists sets, dict sets, retired string,
    plain display) must not 500 the public round-robin endpoint."""
    from app.models.team import Team

    tournament = Tournament(
        name="WF14 Cons Scores",
        location="KC",
        timezone="America/Chicago",
        start_date=date(2026, 7, 24),
        end_date=date(2026, 7, 26),
    )
    session.add(tournament)
    session.flush()

    version = ScheduleVersion(tournament_id=tournament.id, version_number=1, status="final")
    session.add(version)
    session.flush()

    event = Event(
        tournament_id=tournament.id,
        name="Womens",
        category="womens",
        team_count=14,
        draw_status="final",
        draw_plan_json='{"template_type":"WF_14_TOP2_BYE","wf_rounds":2,"guarantee":4}',
    )
    session.add(event)
    session.flush()

    # Six real loser-flight teams for pools C {1,4,6} and D {2,3,5}.
    teams: dict[str, Team] = {}
    for i in range(1, 7):
        t = Team(
            tournament_id=tournament.id,
            event_id=event.id,
            name=f"Cons Team {i}",
            seed=i,
        )
        session.add(t)
        session.flush()
        teams[f"t{i}"] = t

    def _mk(code, rnd, seq, a, b, **kw):
        m = Match(
            tournament_id=tournament.id,
            event_id=event.id,
            schedule_version_id=version.id,
            match_code=code,
            match_type="MAIN",
            round_number=rnd,
            round_index=rnd,
            sequence_in_round=seq,
            duration_minutes=90,
            placeholder_side_a="",
            placeholder_side_b="",
            team_a_id=a.id,
            team_b_id=b.id,
            **kw,
        )
        session.add(m)
        return m

    # Pool C: teams 1,4,6.  Various finalized score shapes.
    _mk(
        "WOM_CONS_FRI_C01",
        1,
        1,
        teams["t1"],
        teams["t6"],
        runtime_status="FINAL",
        winner_team_id=teams["t1"].id,
        # sets stored as list-of-lists (the production shape that 500'd).
        score_json={"sets": [[6, 2], [6, 3]], "display": "6-2, 6-3"},
    )
    _mk(
        "WOM_CONS_SAT1_C01",
        2,
        1,
        teams["t4"],
        teams["t6"],
        runtime_status="FINAL",
        winner_team_id=teams["t4"].id,
        # sets as dicts.
        score_json={"sets": [{"a": 6, "b": 4}, {"a": 7, "b": 5}]},
    )
    _mk(
        "WOM_CONS_SAT2_C01",
        3,
        1,
        teams["t1"],
        teams["t4"],
        runtime_status="FINAL",
        winner_team_id=teams["t1"].id,
        # retired string only.
        score_json={"display": "6-1 (RET)"},
    )

    # Pool D: teams 2,3,5.
    _mk(
        "WOM_CONS_FRI_D02",
        1,
        2,
        teams["t2"],
        teams["t5"],
        runtime_status="FINAL",
        winner_team_id=teams["t2"].id,
        score_json={"display": "8-4"},
    )
    _mk(
        "WOM_CONS_SAT1_D02",
        2,
        2,
        teams["t3"],
        teams["t5"],
        runtime_status="FINAL",
        winner_team_id=teams["t3"].id,
        # garbage sets element mixed with a valid pair.
        score_json={"sets": [None, "x", [6, 3]]},
    )
    _mk("WOM_CONS_SAT2_D02", 3, 2, teams["t2"], teams["t3"])

    tournament.public_schedule_version_id = version.id
    session.add(tournament)
    session.commit()

    resp = client.get(f"/api/public/tournaments/{tournament.id}/events/{event.id}/roundrobin")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    pools = {p["pool_code"]: p for p in body["pools"]}
    assert {"POOLC", "POOLD"} <= set(pools)
    # Standings computed without crashing.
    standings = {s["pool_code"]: s for s in body["standings"]}
    assert "POOLC" in standings and "POOLD" in standings


def test_public_draws_list_wf14_has_no_bracket_divisions(client, session):
    """A WF_14 (waterfall→pools) event must not expose Division I–IV bracket
    buttons — even if stale bracket-coded matches linger from an older draw."""
    tournament = Tournament(
        name="WF14 No Divs",
        location="KC",
        timezone="America/Chicago",
        start_date=date(2026, 7, 24),
        end_date=date(2026, 7, 26),
    )
    session.add(tournament)
    session.flush()

    version = ScheduleVersion(tournament_id=tournament.id, version_number=1, status="final")
    session.add(version)
    session.flush()

    event = Event(
        tournament_id=tournament.id,
        name="Womens",
        category="womens",
        team_count=14,
        draw_status="final",
        draw_plan_json='{"template_type":"WF_14_TOP2_BYE","wf_rounds":2,"guarantee":4}',
    )
    session.add(event)
    session.flush()

    def _mk(code, mtype, rnd, seq):
        session.add(
            Match(
                tournament_id=tournament.id,
                event_id=event.id,
                schedule_version_id=version.id,
                match_code=code,
                match_type=mtype,
                round_number=rnd,
                round_index=rnd,
                sequence_in_round=seq,
                duration_minutes=90,
                placeholder_side_a="",
                placeholder_side_b="",
            )
        )

    _mk("WOM_WF_R1_01", "WF", 1, 1)
    _mk("WOM_POOLA_RR_01", "RR", 1, 1)
    _mk("WOM_CONS_FRI_C01", "MAIN", 1, 1)
    # Stale bracket-division match left over from a previous draw structure.
    _mk("WOM_BWW_01", "BRACKET", 1, 1)

    tournament.public_schedule_version_id = version.id
    session.add(tournament)
    session.commit()

    resp = client.get(f"/api/public/tournaments/{tournament.id}/draws")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    ev = next(e for e in body["events"] if e["event_id"] == event.id)
    assert ev["divisions"] == []
    assert ev["has_waterfall"] is True
    assert ev["has_round_robin"] is True


def test_public_roundrobin_never_500s_when_build_raises(client, session, monkeypatch):
    """Hard guarantee: if the round-robin build raises for any reason, the public
    endpoint must degrade to a valid empty 200 response, never an HTTP 500."""
    import app.routes.public as public_module

    tournament = Tournament(
        name="RR Never 500",
        location="KC",
        timezone="America/Chicago",
        start_date=date(2026, 7, 24),
        end_date=date(2026, 7, 26),
    )
    session.add(tournament)
    session.flush()

    version = ScheduleVersion(tournament_id=tournament.id, version_number=1, status="final")
    session.add(version)
    session.flush()

    event = Event(
        tournament_id=tournament.id,
        name="Womens",
        category="womens",
        team_count=14,
        draw_status="final",
        draw_plan_json='{"template_type":"WF_14_TOP2_BYE","wf_rounds":2,"guarantee":4}',
    )
    session.add(event)
    session.flush()

    tournament.public_schedule_version_id = version.id
    session.add(tournament)
    session.commit()

    def _boom(*args, **kwargs):
        raise RuntimeError("simulated corrupt data")

    monkeypatch.setattr(public_module, "_public_round_robin_impl", _boom)

    resp = client.get(f"/api/public/tournaments/{tournament.id}/events/{event.id}/roundrobin")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["pools"] == []
    assert body["event_name"] == "Womens"
