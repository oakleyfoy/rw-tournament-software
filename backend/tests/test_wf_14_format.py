"""Tests for 14-team WF_14_TOP2_BYE template."""

import json
from datetime import date

from app.models.event import Event
from app.models.schedule_version import ScheduleVersion
from app.models.team import Team
from app.models.tournament import Tournament
from app.services.draw_plan_engine import DrawPlanSpec, compute_inventory, generate_matches_for_event, resolve_event_family
from app.services.wf_14_format import wf_14_total_matches


def test_wf_14_inventory():
    spec = DrawPlanSpec(
        event_id=1,
        event_name="Fourteen",
        division="Mixed",
        team_count=14,
        template_type="WF_14_TOP2_BYE",
        template_key="WF_14_TOP2_BYE",
        guarantee=5,
        waterfall_rounds=2,
        waterfall_minutes=60,
        standard_minutes=105,
    )
    assert resolve_event_family(spec) == "WF_14_TOP2_BYE"
    inv = compute_inventory(spec)
    assert not inv.has_errors(), inv.errors
    assert inv.total_matches == wf_14_total_matches()
    assert inv.wf_matches == 10
    assert inv.rr_matches == 12


def test_wf_14_generates_match_codes(session):
    tournament = Tournament(
        name="T",
        location="L",
        timezone="America/New_York",
        start_date=date(2026, 3, 1),
        end_date=date(2026, 3, 3),
        use_time_windows=False,
    )
    session.add(tournament)
    session.commit()
    session.refresh(tournament)

    event = Event(
        tournament_id=tournament.id,
        category="mixed",
        name="Open",
        team_count=14,
        guarantee_selected=5,
    )
    event.draw_plan_json = json.dumps({"template_type": "WF_14_TOP2_BYE", "wf_rounds": 2})
    session.add(event)
    session.commit()
    session.refresh(event)

    for seed in range(1, 15):
        session.add(
            Team(
                event_id=event.id,
                name=f"Team {seed}",
                seed=seed,
                rating=float(1500 - seed * 10),
            )
        )
    session.commit()

    version = ScheduleVersion(tournament_id=tournament.id, version_number=1)
    session.add(version)
    session.commit()
    session.refresh(version)

    spec = DrawPlanSpec(
        event_id=event.id,
        event_name=event.name,
        division="Mixed",
        team_count=14,
        template_type="WF_14_TOP2_BYE",
        template_key="WF_14_TOP2_BYE",
        guarantee=5,
        waterfall_rounds=2,
        waterfall_minutes=60,
        standard_minutes=105,
        tournament_id=tournament.id,
        event_category="mixed",
    )

    session._allow_match_generation = True
    teams = session.exec(
        __import__("sqlmodel").select(Team).where(Team.event_id == event.id)
    ).all()
    by_seed = sorted(teams, key=lambda t: t.seed or 0)
    linked = [t.id for t in by_seed]

    matches, warnings = generate_matches_for_event(session, version.id, spec, linked, set())
    assert not warnings or all("expected 14 teams" not in w.lower() for w in warnings)
    assert len(matches) == wf_14_total_matches()

    wf_r1 = [m for m in matches if m.match_type == "WF" and m.round_index == 1]
    wf_r2 = [m for m in matches if m.match_type == "WF" and m.round_index == 2]
    assert len(wf_r1) == 6
    assert len(wf_r2) == 4

    # Top two ratings: seed 1 (1490) and seed 2 (1480) — bound on R2 as byes
    bye_ids = {by_seed[0].id, by_seed[1].id}
    r2_with_byes = [m for m in wf_r2 if m.team_a_id in bye_ids or m.team_b_id in bye_ids]
    assert len(r2_with_byes) == 2

    cons = [m for m in matches if "CONS_" in m.match_code]
    assert len(cons) == 9
