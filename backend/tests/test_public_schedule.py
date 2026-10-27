"""
Phase B — Public Schedule Page tests.

Validates:
- Unpublished tournament returns NOT_PUBLISHED
- Published version returns matches with correct shape
- event_id filter works
- day filter works
- search filter returns correct subset
- search is case-insensitive
"""

from datetime import date, time

from sqlmodel import Session, select

from app.models.event import Event
from app.models.match import Match
from app.models.match_assignment import MatchAssignment
from app.models.schedule_slot import ScheduleSlot
from app.models.schedule_version import ScheduleVersion
from app.models.team import Team
from app.models.tournament import Tournament


def _setup_published_tournament(session: Session):
    """Create a published tournament with matches, slots, assignments, teams."""
    t = Tournament(
        name="Beach Classic",
        location="Virginia Beach",
        timezone="America/New_York",
        start_date=date(2026, 6, 5),
        end_date=date(2026, 6, 7),
    )
    session.add(t)
    session.flush()

    v = ScheduleVersion(
        tournament_id=t.id,
        version_number=1,
        status="final",
    )
    session.add(v)
    session.flush()

    ev1 = Event(
        tournament_id=t.id,
        category="womens",
        name="Women's A",
        team_count=16,
    )
    ev2 = Event(
        tournament_id=t.id,
        category="mixed",
        name="Mixed A",
        team_count=16,
    )
    session.add_all([ev1, ev2])
    session.flush()

    team_a = Team(event_id=ev1.id, name="Smith / Johnson - VA", seed=1, display_name="Smith / Johnson")
    team_b = Team(event_id=ev1.id, name="Davis / Brown - NC", seed=2, display_name="Davis / Brown")
    team_c = Team(event_id=ev2.id, name="Wilson / Lee - FL", seed=1, display_name="Wilson / Lee")
    team_d = Team(event_id=ev2.id, name="Garcia / Chen - TX", seed=2, display_name="Garcia / Chen")
    session.add_all([team_a, team_b, team_c, team_d])
    session.flush()

    m1 = Match(
        tournament_id=t.id,
        event_id=ev1.id,
        schedule_version_id=v.id,
        match_code="WOM_WOM_E1_WF_R1_M01",
        match_type="WF",
        round_number=1,
        round_index=1,
        sequence_in_round=1,
        duration_minutes=60,
        team_a_id=team_a.id,
        team_b_id=team_b.id,
        placeholder_side_a="Seed 1",
        placeholder_side_b="Seed 2",
    )
    m2 = Match(
        tournament_id=t.id,
        event_id=ev2.id,
        schedule_version_id=v.id,
        match_code="MIX_MIX_E2_WF_R1_M01",
        match_type="WF",
        round_number=1,
        round_index=1,
        sequence_in_round=1,
        duration_minutes=60,
        team_a_id=team_c.id,
        team_b_id=team_d.id,
        placeholder_side_a="Seed 1",
        placeholder_side_b="Seed 2",
    )
    session.add_all([m1, m2])
    session.flush()

    slot1 = ScheduleSlot(
        tournament_id=t.id,
        schedule_version_id=v.id,
        day_date=date(2026, 6, 5),
        start_time=time(9, 0),
        end_time=time(10, 0),
        court_number=1,
        court_label="1",
        block_minutes=60,
    )
    slot2 = ScheduleSlot(
        tournament_id=t.id,
        schedule_version_id=v.id,
        day_date=date(2026, 6, 6),
        start_time=time(13, 15),
        end_time=time(14, 15),
        court_number=2,
        court_label="2",
        block_minutes=60,
    )
    session.add_all([slot1, slot2])
    session.flush()

    a1 = MatchAssignment(
        schedule_version_id=v.id,
        match_id=m1.id,
        slot_id=slot1.id,
    )
    a2 = MatchAssignment(
        schedule_version_id=v.id,
        match_id=m2.id,
        slot_id=slot2.id,
    )
    session.add_all([a1, a2])
    session.flush()

    # Publish
    t.public_schedule_version_id = v.id
    session.add(t)
    session.commit()

    return t, v, ev1, ev2, m1, m2


def _setup_published_rr_tournament(session: Session):
    """Create a published tournament with RR matches for the public RR page."""
    t = Tournament(
        name="RR Public Test",
        location="Test Beach",
        timezone="America/New_York",
        start_date=date(2026, 6, 5),
        end_date=date(2026, 6, 7),
    )
    session.add(t)
    session.flush()

    v = ScheduleVersion(
        tournament_id=t.id,
        version_number=1,
        status="final",
    )
    session.add(v)
    session.flush()

    ev = Event(
        tournament_id=t.id,
        category="womens",
        name="Women's A",
        team_count=4,
    )
    session.add(ev)
    session.flush()

    team1 = Team(event_id=ev.id, name="Alpha / One", seed=1, display_name="Alpha / One")
    team2 = Team(event_id=ev.id, name="Bravo / Two", seed=2, display_name="Bravo / Two")
    team3 = Team(event_id=ev.id, name="Charlie / Three", seed=3, display_name="Charlie / Three")
    team4 = Team(event_id=ev.id, name="Delta / Four", seed=4, display_name="Delta / Four")
    session.add_all([team1, team2, team3, team4])
    session.flush()

    m1 = Match(
        tournament_id=t.id,
        event_id=ev.id,
        schedule_version_id=v.id,
        match_code="WOM_POOLA_RR_M01",
        match_type="RR",
        round_number=1,
        round_index=1,
        sequence_in_round=1,
        duration_minutes=60,
        team_a_id=team1.id,
        team_b_id=team2.id,
        placeholder_side_a="Seed 1",
        placeholder_side_b="Seed 2",
        runtime_status="FINAL",
        winner_team_id=team1.id,
        score_json={"display": "6-3, 6-4"},
    )
    m2 = Match(
        tournament_id=t.id,
        event_id=ev.id,
        schedule_version_id=v.id,
        match_code="WOM_POOLA_RR_M02",
        match_type="RR",
        round_number=1,
        round_index=1,
        sequence_in_round=2,
        duration_minutes=60,
        team_a_id=team3.id,
        team_b_id=team4.id,
        placeholder_side_a="Seed 3",
        placeholder_side_b="Seed 4",
        runtime_status="SCHEDULED",
    )
    session.add_all([m1, m2])
    session.flush()

    slot1 = ScheduleSlot(
        tournament_id=t.id,
        schedule_version_id=v.id,
        day_date=date(2026, 6, 5),
        start_time=time(9, 0),
        end_time=time(10, 0),
        court_number=1,
        court_label="1",
        block_minutes=60,
    )
    slot2 = ScheduleSlot(
        tournament_id=t.id,
        schedule_version_id=v.id,
        day_date=date(2026, 6, 5),
        start_time=time(10, 30),
        end_time=time(11, 30),
        court_number=1,
        court_label="1",
        block_minutes=60,
    )
    session.add_all([slot1, slot2])
    session.flush()
    session.add(MatchAssignment(schedule_version_id=v.id, match_id=m1.id, slot_id=slot1.id))
    session.add(MatchAssignment(schedule_version_id=v.id, match_id=m2.id, slot_id=slot2.id))

    t.public_schedule_version_id = v.id
    session.add(t)
    session.commit()
    return t, ev, team1


def test_unpublished_returns_not_published(client, session):
    """Schedule endpoint returns NOT_PUBLISHED when no pointer set."""
    t = Tournament(
        name="Unpub Tourney",
        location="Nowhere",
        timezone="America/New_York",
        start_date=date(2026, 6, 1),
        end_date=date(2026, 6, 3),
    )
    session.add(t)
    session.commit()

    resp = client.get(f"/api/public/tournaments/{t.id}/schedule")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "NOT_PUBLISHED"
    assert "message" in body


def test_published_returns_matches(client, session):
    """Published version returns matches with correct response shape."""
    t, v, ev1, ev2, m1, m2 = _setup_published_tournament(session)

    resp = client.get(f"/api/public/tournaments/{t.id}/schedule")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "OK"
    assert body["tournament_name"] == "Beach Classic"
    assert body["published_version_id"] == v.id
    assert len(body["matches"]) == 2

    match_item = body["matches"][0]
    assert "match_id" in match_item
    assert "match_number" in match_item
    assert "stage" in match_item
    assert "event_name" in match_item
    assert "day_index" in match_item
    assert "day_label" in match_item
    assert "team1_display" in match_item
    assert "team2_display" in match_item
    assert "team1_full_name" in match_item
    assert "team2_full_name" in match_item
    assert "status" in match_item

    assert len(body["events"]) == 2
    assert len(body["days"]) == 2


def test_event_id_filter(client, session):
    """event_id filter returns only matches from that event."""
    t, v, ev1, ev2, m1, m2 = _setup_published_tournament(session)

    resp = client.get(f"/api/public/tournaments/{t.id}/schedule?event_id={ev1.id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "OK"
    assert len(body["matches"]) == 1
    assert body["matches"][0]["event_name"] == "Women's A"

    # Filter options should still show all events (unfiltered)
    assert len(body["events"]) == 2


def test_event_filter_lists_only_that_events_divisions(client, session):
    """Choosing Mixed lists Mixed brackets, not Women's divisions."""
    t, v, ev1, ev2, _m1, _m2 = _setup_published_tournament(session)
    session.add_all([
        Match(
            tournament_id=t.id,
            event_id=ev1.id,
            schedule_version_id=v.id,
            match_code="WOM_BWW_QF_1",
            match_type="MAIN",
            round_number=1,
            round_index=1,
            sequence_in_round=1,
            duration_minutes=60,
            placeholder_side_a="Seed 1",
            placeholder_side_b="Seed 8",
        ),
        Match(
            tournament_id=t.id,
            event_id=ev1.id,
            schedule_version_id=v.id,
            match_code="WOM_BWL_QF_1",
            match_type="MAIN",
            round_number=1,
            round_index=1,
            sequence_in_round=2,
            duration_minutes=60,
            placeholder_side_a="Seed 4",
            placeholder_side_b="Seed 5",
        ),
        Match(
            tournament_id=t.id,
            event_id=ev2.id,
            schedule_version_id=v.id,
            match_code="MIX_B1_QF_1",
            match_type="MAIN",
            round_number=1,
            round_index=1,
            sequence_in_round=1,
            duration_minutes=60,
            placeholder_side_a="Seed 1",
            placeholder_side_b="Seed 8",
        ),
        Match(
            tournament_id=t.id,
            event_id=ev2.id,
            schedule_version_id=v.id,
            match_code="MIX_B2_QF_1",
            match_type="MAIN",
            round_number=1,
            round_index=1,
            sequence_in_round=2,
            duration_minutes=60,
            placeholder_side_a="Seed 9",
            placeholder_side_b="Seed 16",
        ),
    ])
    session.commit()

    mixed = client.get(f"/api/public/tournaments/{t.id}/schedule?event_id={ev2.id}")
    assert mixed.status_code == 200
    assert mixed.json()["divisions"] == ["Bracket 1", "Bracket 2"]

    womens = client.get(f"/api/public/tournaments/{t.id}/schedule?event_id={ev1.id}")
    assert womens.status_code == 200
    assert womens.json()["divisions"] == ["Division I", "Division II"]

    # A chosen bracket stays in the list so the other brackets for that event remain selectable.
    one_bracket = client.get(
        f"/api/public/tournaments/{t.id}/schedule?event_id={ev2.id}&division=Bracket%201"
    )
    assert one_bracket.status_code == 200
    assert one_bracket.json()["divisions"] == ["Bracket 1", "Bracket 2"]


def test_day_filter(client, session):
    """day filter returns only matches from that day_index."""
    t, v, ev1, ev2, m1, m2 = _setup_published_tournament(session)

    resp = client.get(f"/api/public/tournaments/{t.id}/schedule?day=1")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "OK"
    assert len(body["matches"]) == 1
    assert body["matches"][0]["day_index"] == 1


def test_search_filter(client, session):
    """search filter returns matches where team name contains search term."""
    t, v, ev1, ev2, m1, m2 = _setup_published_tournament(session)

    resp = client.get(f"/api/public/tournaments/{t.id}/schedule?search=Smith")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "OK"
    assert len(body["matches"]) == 1
    assert "Smith" in body["matches"][0]["team1_display"] or "Smith" in body["matches"][0]["team1_full_name"]


def test_search_case_insensitive(client, session):
    """search is case-insensitive."""
    t, v, ev1, ev2, m1, m2 = _setup_published_tournament(session)

    resp_upper = client.get(f"/api/public/tournaments/{t.id}/schedule?search=GARCIA")
    resp_lower = client.get(f"/api/public/tournaments/{t.id}/schedule?search=garcia")

    assert resp_upper.status_code == 200
    assert resp_lower.status_code == 200

    body_upper = resp_upper.json()
    body_lower = resp_lower.json()

    assert len(body_upper["matches"]) == 1
    assert len(body_lower["matches"]) == 1
    assert body_upper["matches"][0]["match_id"] == body_lower["matches"][0]["match_id"]


def test_public_schedule_hides_court_info_in_checkin_management(client, session):
    t, v, ev1, ev2, m1, m2 = _setup_published_tournament(session)
    t.desk_management_mode = "checkin_management"
    session.add(t)
    session.commit()

    resp = client.get(f"/api/public/tournaments/{t.id}/schedule")
    assert resp.status_code == 200, resp.text

    body = resp.json()
    assert body["show_court_info"] is False
    assert len(body["matches"]) == 2
    assert all(match["court_name"] is None for match in body["matches"])


def test_public_schedule_prefers_short_names_from_team_name_over_stale_display_name(client, session):
    t, v, ev1, ev2, m1, m2 = _setup_published_tournament(session)

    team_c = session.get(Team, m2.team_a_id)
    team_d = session.get(Team, m2.team_b_id)
    assert team_c is not None and team_d is not None

    team_c.name = "Jon Miller, Ocala, FL / Lisa Steed, Ocala, FL"
    team_c.display_name = "venitta / Ed"
    team_d.name = "Eric Tatum, Marietta, GA / Leana Tatum, Marietta, GA"
    team_d.display_name = "Eric / Leana"
    session.add(team_c)
    session.add(team_d)
    session.commit()

    resp = client.get(f"/api/public/tournaments/{t.id}/schedule")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    target = next(match for match in body["matches"] if match["match_id"] == m2.id)
    assert target["team1_display"] == "Jon / Lisa"
    assert target["team1_full_name"] == "Jon Miller, Ocala, FL / Lisa Steed, Ocala, FL"
    assert target["team2_display"] == "Eric / Leana"


def test_public_round_robin_uses_runtime_status_for_score_and_winner(client, session):
    """Public RR cards should show finalized score/winner from runtime_status data."""
    t, ev, winner_team = _setup_published_rr_tournament(session)

    resp = client.get(f"/api/public/tournaments/{t.id}/events/{ev.id}/roundrobin")
    assert resp.status_code == 200
    body = resp.json()

    assert body["event_name"] == "Women's A"
    assert len(body["pools"]) >= 1
    first_match = body["pools"][0]["matches"][0]
    assert first_match["status"] == "FINAL"
    assert first_match["score_display"] == "6-3, 6-4"
    assert first_match["winner_name"] == winner_team.display_name

    assert len(body["standings"]) >= 1
    rows = body["standings"][0]["rows"]
    winner_row = [r for r in rows if r["team_id"] == winner_team.id][0]
    assert winner_row["wins"] == 1
    assert winner_row["played"] == 1
    assert "W/L" in body["tiebreaker_note"]
    assert "Sets Lost" in body["tiebreaker_note"]
    assert "Game Differential" in body["tiebreaker_note"]


def test_public_round_robin_sorts_by_sets_lost_before_game_diff(client, session):
    """Public RR standings use sets lost before game differential."""
    t, ev, winner_team = _setup_published_rr_tournament(session)

    team2 = session.exec(select(Team).where(Team.event_id == ev.id, Team.display_name == "Bravo / Two")).one()
    team3 = session.exec(select(Team).where(Team.event_id == ev.id, Team.display_name == "Charlie / Three")).one()

    match_one = session.exec(
        select(Match).where(
            Match.event_id == ev.id,
            Match.schedule_version_id == t.public_schedule_version_id,
            Match.match_code == "WOM_POOLA_RR_M01",
        )
    ).one()
    match_one.score_json = {"display": "6-0 (RET)", "actual": "6-0"}
    session.add(match_one)

    match_two = session.exec(
        select(Match).where(
            Match.event_id == ev.id,
            Match.schedule_version_id == t.public_schedule_version_id,
            Match.match_code == "WOM_POOLA_RR_M02",
        )
    ).one()
    match_two.team_a_id = winner_team.id
    match_two.team_b_id = team3.id
    match_two.runtime_status = "FINAL"
    match_two.winner_team_id = team3.id
    match_two.score_json = {"display": "4-6, 4-6"}
    session.add(match_two)

    match_three = Match(
        tournament_id=t.id,
        event_id=ev.id,
        schedule_version_id=t.public_schedule_version_id,
        match_code="WOM_POOLA_RR_M03",
        match_type="RR",
        round_number=1,
        round_index=1,
        sequence_in_round=3,
        duration_minutes=60,
        team_a_id=team2.id,
        team_b_id=team3.id,
        placeholder_side_a="Seed 2",
        placeholder_side_b="Seed 3",
        runtime_status="FINAL",
        winner_team_id=team2.id,
        score_json={"display": "7-6 (RET)"},
    )
    session.add(match_three)
    session.commit()

    resp = client.get(f"/api/public/tournaments/{t.id}/events/{ev.id}/roundrobin")
    assert resp.status_code == 200
    rows = resp.json()["standings"][0]["rows"]

    assert [row["team_display"] for row in rows[:3]] == ["Charlie / Three", "Bravo / Two", "Alpha / One"]


def test_public_round_robin_standings_ignore_non_rr_match_codes(client, session):
    """Public RR standings should ignore finalized WF-coded matches even if typed RR."""
    t, ev, winner_team = _setup_published_rr_tournament(session)

    other_team = session.exec(select(Team).where(Team.event_id == ev.id, Team.id != winner_team.id)).first()
    assert other_team is not None

    bad = Match(
        tournament_id=t.id,
        event_id=ev.id,
        schedule_version_id=t.public_schedule_version_id,
        match_code="WOM_WF_R1_M99",
        match_type="RR",
        round_number=1,
        round_index=1,
        sequence_in_round=99,
        duration_minutes=60,
        runtime_status="FINAL",
        team_a_id=winner_team.id,
        team_b_id=other_team.id,
        placeholder_side_a="Seed 1",
        placeholder_side_b="Seed 2",
        winner_team_id=winner_team.id,
        score_json={"display": "6-0 6-0"},
    )
    session.add(bad)
    session.commit()

    resp = client.get(f"/api/public/tournaments/{t.id}/events/{ev.id}/roundrobin")
    assert resp.status_code == 200
    body = resp.json()
    rows = body["standings"][0]["rows"]
    winner_row = [r for r in rows if r["team_id"] == winner_team.id][0]

    # Should still reflect only the valid RR match from setup.
    assert winner_row["wins"] == 1
    assert winner_row["played"] == 1
    assert winner_row["sets_won"] == 2
    assert winner_row["games_won"] == 12


def test_public_round_robin_credits_selected_winner_for_winner_first_scores(client, session):
    """Public RR standings should align sets/games with selected winner_team_id."""
    t, ev, winner_team = _setup_published_rr_tournament(session)

    # Flip the finalized match to team_b as winner while keeping winner-first style score.
    match = session.exec(
        select(Match).where(
            Match.event_id == ev.id,
            Match.schedule_version_id == t.public_schedule_version_id,
            Match.match_code == "WOM_POOLA_RR_M01",
        )
    ).one()
    match.winner_team_id = match.team_b_id
    match.score_json = {"display": "6-4, 7-5"}
    session.add(match)
    session.commit()

    resp = client.get(f"/api/public/tournaments/{t.id}/events/{ev.id}/roundrobin")
    assert resp.status_code == 200
    rows = resp.json()["standings"][0]["rows"]
    row_a = [r for r in rows if r["team_id"] == match.team_a_id][0]
    row_b = [r for r in rows if r["team_id"] == match.team_b_id][0]

    assert row_b["wins"] == 1
    assert row_b["sets_won"] == 2
    assert row_b["sets_lost"] == 0
    assert row_a["losses"] == 1
    assert row_a["sets_won"] == 0
    assert row_a["sets_lost"] == 2


def test_public_round_robin_retired_uses_literal_score_orientation(client, session):
    """Retired RR keeps entered set/game orientation even if winner is opposite side."""
    t, ev, winner_team = _setup_published_rr_tournament(session)

    match = session.exec(
        select(Match).where(
            Match.event_id == ev.id,
            Match.schedule_version_id == t.public_schedule_version_id,
            Match.match_code == "WOM_POOLA_RR_M01",
        )
    ).one()
    match.winner_team_id = match.team_a_id
    match.score_json = {"display": "6-7 (RET)", "actual": "6-7"}
    session.add(match)
    session.commit()

    resp = client.get(f"/api/public/tournaments/{t.id}/events/{ev.id}/roundrobin")
    assert resp.status_code == 200
    rows = resp.json()["standings"][0]["rows"]
    row_a = [r for r in rows if r["team_id"] == match.team_a_id][0]
    row_b = [r for r in rows if r["team_id"] == match.team_b_id][0]

    assert row_a["wins"] == 1
    assert row_b["losses"] == 1
    assert row_a["sets_won"] == 0 and row_a["sets_lost"] == 1
    assert row_b["sets_won"] == 1 and row_b["sets_lost"] == 0
    assert row_a["games_won"] == 6 and row_a["games_lost"] == 7
    assert row_b["games_won"] == 7 and row_b["games_lost"] == 6


def test_public_round_robin_hides_court_info_in_checkin_management(client, session):
    t, ev, _winner_team = _setup_published_rr_tournament(session)
    t.desk_management_mode = "checkin_management"
    session.add(t)
    session.commit()

    resp = client.get(f"/api/public/tournaments/{t.id}/events/{ev.id}/roundrobin")
    assert resp.status_code == 200, resp.text

    body = resp.json()
    assert body["show_court_info"] is False


def test_public_bracket_hides_court_info_in_checkin_management(client, session):
    t = Tournament(
        name="Bracket Public Test",
        location="Test Beach",
        timezone="America/New_York",
        start_date=date(2026, 6, 5),
        end_date=date(2026, 6, 7),
        desk_management_mode="checkin_management",
    )
    session.add(t)
    session.flush()

    v = ScheduleVersion(
        tournament_id=t.id,
        version_number=1,
        status="final",
    )
    session.add(v)
    session.flush()

    ev = Event(
        tournament_id=t.id,
        category="womens",
        name="Women's A",
        team_count=8,
    )
    session.add(ev)
    session.flush()

    team1 = Team(event_id=ev.id, name="Alpha / One", seed=1, display_name="Alpha / One")
    team2 = Team(event_id=ev.id, name="Bravo / Two", seed=2, display_name="Bravo / Two")
    session.add_all([team1, team2])
    session.flush()

    match = Match(
        tournament_id=t.id,
        event_id=ev.id,
        schedule_version_id=v.id,
        match_code="WOM_BWW_QF1",
        match_type="MAIN",
        round_number=1,
        round_index=1,
        sequence_in_round=1,
        duration_minutes=60,
        team_a_id=team1.id,
        team_b_id=team2.id,
        placeholder_side_a="Seed 1",
        placeholder_side_b="Seed 2",
    )
    session.add(match)
    session.flush()

    slot = ScheduleSlot(
        tournament_id=t.id,
        schedule_version_id=v.id,
        day_date=date(2026, 6, 5),
        start_time=time(9, 0),
        end_time=time(10, 0),
        court_number=1,
        court_label="1",
        block_minutes=60,
    )
    session.add(slot)
    session.flush()
    session.add(MatchAssignment(schedule_version_id=v.id, match_id=match.id, slot_id=slot.id))

    t.public_schedule_version_id = v.id
    session.add(t)
    session.commit()

    resp = client.get(f"/api/public/tournaments/{t.id}/events/{ev.id}/bracket/BWW")
    assert resp.status_code == 200, resp.text

    body = resp.json()
    assert body["show_court_info"] is False


def test_public_schedule_names_each_feeder_source_match(client, session):
    """Waterfall sides use their own source match, including after one side is filled."""
    t = Tournament(
        name="Wild Dunes Mixed Feeders",
        location="Isle of Palms",
        timezone="America/New_York",
        start_date=date(2026, 10, 16),
        end_date=date(2026, 10, 18),
    )
    session.add(t)
    session.flush()
    version = ScheduleVersion(tournament_id=t.id, version_number=1, status="final")
    session.add(version)
    session.flush()
    event = Event(tournament_id=t.id, category="mixed", name="Mixed", team_count=24)
    session.add(event)
    session.flush()
    advanced = Team(event_id=event.id, name="Ada Smith / Bea Jones", seed=1, display_name="Ada / Bea")
    session.add(advanced)
    session.flush()

    def add_match(code, **kwargs):
        fields = {
            "round_number": 1,
            "round_index": 1,
            "sequence_in_round": 1,
            "duration_minutes": 60,
            "placeholder_side_a": "TBD",
            "placeholder_side_b": "TBD",
        }
        fields.update(kwargs)
        match = Match(
            tournament_id=t.id,
            event_id=event.id,
            schedule_version_id=version.id,
            match_code=code,
            match_type="WF",
            **fields,
        )
        session.add(match)
        session.flush()
        return match

    source_a = add_match("MIX_WF_R1_01", team_a_id=advanced.id, runtime_status="FINAL", winner_team_id=advanced.id)
    source_b = add_match("MIX_WF_R1_02")
    source_c = add_match("MIX_WF_R1_07")
    source_d = add_match("MIX_WF_R1_08")
    source_e = add_match("MIX_WF_R1_09")
    source_f = add_match("MIX_WF_R1_10")
    winner_match = add_match(
        "MIX_WF_R2_W01",
        round_number=2,
        round_index=2,
        placeholder_side_a="W(R1_1)",
        placeholder_side_b="W(R1_2)",
        source_match_a_id=source_a.id,
        source_a_role="WINNER",
        source_match_b_id=source_b.id,
        source_b_role="WINNER",
        team_a_id=advanced.id,
    )
    loser_four = add_match(
        "MIX_WF_R2_L04",
        round_number=2,
        round_index=2,
        placeholder_side_a="L(R1_7)",
        placeholder_side_b="L(R1_8)",
        source_match_a_id=source_c.id,
        source_a_role="LOSER",
        source_match_b_id=source_d.id,
        source_b_role="LOSER",
    )
    loser_five = add_match(
        "MIX_WF_R2_L05",
        round_number=2,
        round_index=2,
        placeholder_side_a="L(R1_9)",
        placeholder_side_b="L(R1_10)",
        source_match_a_id=source_e.id,
        source_a_role="LOSER",
        source_match_b_id=source_f.id,
        source_b_role="LOSER",
    )
    unknown = add_match(
        "MIX_WF_R2_W99",
        round_number=2,
        round_index=2,
        placeholder_side_a="W(R1_99)",
        placeholder_side_b="SEED_4",
    )
    t.public_schedule_version_id = version.id
    session.add(t)
    session.commit()

    resp = client.get(f"/api/public/tournaments/{t.id}/schedule?event_id={event.id}")
    assert resp.status_code == 200, resp.text
    by_id = {item["match_id"]: item for item in resp.json()["matches"]}

    filled = by_id[winner_match.id]
    assert filled["team1_full_name"] == "Ada Smith / Bea Jones"
    assert filled["team2_full_name"] == f"Winner of Match #{source_b.id}"
    assert str(winner_match.id) not in filled["team2_full_name"]

    fourth = by_id[loser_four.id]
    assert fourth["team1_full_name"] == f"Loser of Match #{source_c.id}"
    assert fourth["team2_full_name"] == f"Loser of Match #{source_d.id}"

    fifth = by_id[loser_five.id]
    assert fifth["team1_full_name"] == f"Loser of Match #{source_e.id}"
    assert fifth["team2_full_name"] == f"Loser of Match #{source_f.id}"

    unresolved = by_id[unknown.id]
    assert unresolved["team1_full_name"] == "Opponent TBD"
    assert unresolved["team2_full_name"] == "SEED_4"
