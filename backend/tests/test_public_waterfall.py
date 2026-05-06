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

    resp = client.get(
        f"/api/public/tournaments/{tournament.id}/events/{event.id}/waterfall"
    )
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

    resp = client.get(
        f"/api/public/tournaments/{tournament.id}/events/{event.id}/waterfall"
    )
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

    resp = client.get(
        f"/api/public/tournaments/{tournament.id}/events/{event.id}/waterfall"
    )
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
    bc = row.get("bracket_compass_dest") or ""
    assert "Division I" in bc and "Division II" in bc
    assert "Division III" in bc and "Division IV" in bc
    assert "winners' bracket" in bc.lower() or "winners'" in bc