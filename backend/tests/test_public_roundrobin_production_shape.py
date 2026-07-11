"""Round-robin endpoint with Waterville Women's (event 18) match-code shape."""

from datetime import date

from app.models.event import Event
from app.models.match import Match
from app.models.schedule_version import ScheduleVersion
from app.models.team import Team
from app.models.tournament import Tournament


def _seed_wom_e18_event(session):
    tournament = Tournament(
        name="Waterville Valley",
        location="NH",
        timezone="America/New_York",
        start_date=date(2026, 7, 24),
        end_date=date(2026, 7, 26),
    )
    session.add(tournament)
    session.flush()

    version = ScheduleVersion(tournament_id=tournament.id, version_number=37, status="final")
    session.add(version)
    session.flush()

    event = Event(
        tournament_id=tournament.id,
        name="Women's",
        category="womens",
        team_count=14,
        draw_status="final",
        draw_plan_json='{"template_type":"WF_14_TOP2_BYE","wf_rounds":2,"guarantee":4}',
    )
    session.add(event)
    session.flush()

    mid = 4300

    def add_match(code, mtype, rnd, seq, seq_val, **kw):
        nonlocal mid
        m = Match(
            id=mid,
            tournament_id=tournament.id,
            event_id=event.id,
            schedule_version_id=version.id,
            match_code=code,
            match_type=mtype,
            round_number=rnd,
            round_index=rnd,
            sequence_in_round=seq_val,
            duration_minutes=90,
            placeholder_side_a=kw.get("placeholder_side_a", "SEED_1"),
            placeholder_side_b=kw.get("placeholder_side_b", "SEED_2"),
            team_a_id=kw.get("team_a_id"),
            team_b_id=kw.get("team_b_id"),
            runtime_status=kw.get("runtime_status", "SCHEDULED"),
            winner_team_id=kw.get("winner_team_id"),
            score_json=kw.get("score_json"),
        )
        session.add(m)
        mid += 1
        return m

    for i in range(1, 7):
        add_match(
            f"WOM_WOM_E18_POOLA_RR_{i:02d}",
            "RR",
            1 if i <= 3 else 2,
            i,
            i if i % 2 else str(i),
            placeholder_side_a=f"SEED_{i}",
            placeholder_side_b=f"SEED_{i + 6}",
        )
    for i in range(1, 7):
        add_match(
            f"WOM_WOM_E18_POOLB_RR_{i:02d}",
            "RR",
            1 if i <= 3 else 2,
            i,
            str(i),
            placeholder_side_a=f"SEED_{i}",
            placeholder_side_b=f"SEED_{i + 6}",
        )

    t1 = Team(tournament_id=tournament.id, event_id=event.id, name="Cons A", seed=1)
    t2 = Team(tournament_id=tournament.id, event_id=event.id, name="Cons B", seed=2)
    session.add(t1)
    session.add(t2)
    session.flush()

    add_match(
        "WOM_WOM_E18_CONS_FRI_C01",
        "MAIN",
        1,
        1,
        1,
        team_a_id=t1.id,
        team_b_id=t2.id,
        runtime_status="FINAL",
        winner_team_id=t1.id,
        score_json={"sets": [[6, 2], [6, 3]], "display": "6-2, 6-3"},
        placeholder_side_a="",
        placeholder_side_b="",
    )
    add_match(
        "WOM_WOM_E18_CONS_FRI_D02",
        "MAIN",
        1,
        2,
        2,
        team_a_id=t2.id,
        team_b_id=t1.id,
        runtime_status="FINAL",
        winner_team_id=t2.id,
        score_json={"display": 8},
        placeholder_side_a="",
        placeholder_side_b="",
    )
    add_match(
        "WOM_WOM_E18_CONS_SAT2_C01",
        "MAIN",
        3,
        1,
        1,
        team_a_id=t1.id,
        team_b_id=t2.id,
        placeholder_side_a="",
        placeholder_side_b="",
    )
    add_match(
        "WOM_WOM_E18_CONS_SAT2_D02",
        "MAIN",
        3,
        2,
        2,
        team_a_id=t2.id,
        team_b_id=t1.id,
        placeholder_side_a="",
        placeholder_side_b="",
    )
    add_match(
        "WOM_WOM_E18_CONS_SAT1_C01",
        "MAIN",
        2,
        1,
        1,
        team_a_id=t1.id,
        team_b_id=t2.id,
        placeholder_side_a="",
        placeholder_side_b="",
    )
    add_match(
        "WOM_WOM_E18_CONS_SAT1_D02",
        "MAIN",
        2,
        2,
        2,
        team_a_id=t2.id,
        team_b_id=t1.id,
        placeholder_side_a="",
        placeholder_side_b="",
    )

    for i in range(1, 4):
        add_match(
            f"WOM_WOM_E18_CONS_SUN_{i:02d}",
            "PLACEMENT",
            4,
            i,
            i,
            placeholder_side_a=f"C{i}",
            placeholder_side_b=f"D{i}",
        )

    tournament.public_schedule_version_id = version.id
    session.add(tournament)
    session.commit()
    return tournament, event, version


def test_public_roundrobin_wom_e18_production_shape(client, session):
    tournament, event, version = _seed_wom_e18_event(session)
    resp = client.get(
        f"/api/public/tournaments/{tournament.id}/events/{event.id}/roundrobin"
        f"?version_id={version.id}"
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    codes = {p["pool_code"] for p in body["pools"]}
    assert {"POOLA", "POOLB", "POOLC", "POOLD", "CD_PLACEMENT"} <= codes
    assert sum(len(p["matches"]) for p in body["pools"]) >= 18
