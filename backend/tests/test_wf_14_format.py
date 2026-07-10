"""Tests for 14-team WF_14_TOP2_BYE template."""

import json
from datetime import date

from app.models.event import Event
from app.models.schedule_version import ScheduleVersion
from app.models.team import Team
from app.models.tournament import Tournament
from app.services.draw_plan_engine import (
    DrawPlanSpec,
    compute_inventory,
    generate_matches_for_event,
    resolve_event_family,
)
from app.services.wf_14_format import wf_14_total_generated_matches, wf_14_total_matches


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
    teams = session.exec(__import__("sqlmodel").select(Team).where(Team.event_id == event.id)).all()
    by_seed = sorted(teams, key=lambda t: t.seed or 0)
    linked = [t.id for t in by_seed]

    matches, warnings = generate_matches_for_event(session, version.id, spec, linked, set())
    assert not warnings or all("expected 14 teams" not in w.lower() for w in warnings)
    assert len(matches) == wf_14_total_generated_matches()

    wf_r1_all = [m for m in matches if m.match_type == "WF" and m.round_index == 1]
    bye_matches = [m for m in wf_r1_all if "_BYE" in m.match_code]
    wf_r1 = [m for m in wf_r1_all if m not in bye_matches]
    wf_r2 = [m for m in matches if m.match_type == "WF" and m.round_index == 2]
    assert len(wf_r1) == 6
    assert len(wf_r2) == 4

    # #1 and #2 seeds get auto-won bye matches (no opponent) that advance to R2.
    assert len(bye_matches) == 2
    bye_ids = {by_seed[0].id, by_seed[1].id}
    assert {m.team_a_id for m in bye_matches} == bye_ids
    for m in bye_matches:
        assert m.team_b_id is None
        assert m.runtime_status == "FINAL"
        assert m.winner_team_id == m.team_a_id
    top = next(m for m in bye_matches if m.match_code.endswith("BYE_TOP"))
    bot = next(m for m in bye_matches if m.match_code.endswith("BYE_BOT"))
    assert top.team_a_id == by_seed[0].id  # #1 seed at top
    assert bot.team_a_id == by_seed[1].id  # #2 seed at bottom
    r2_with_byes = [m for m in wf_r2 if m.team_a_id in bye_ids or m.team_b_id in bye_ids]
    assert len(r2_with_byes) == 2

    cons = [m for m in matches if "CONS_" in m.match_code]
    assert len(cons) == 9

    # Loser-flight pools C {1,4,6} and D {2,3,5} — verify each pairing by reseed rank.
    def _cons_pair(code_fragment: str) -> set:
        m = next(mm for mm in cons if code_fragment in mm.match_code)
        return {m.placeholder_side_a, m.placeholder_side_b}

    assert _cons_pair("CONS_FRI_C") == {"ConsL1", "ConsL6"}
    assert _cons_pair("CONS_FRI_D") == {"ConsL2", "ConsL5"}
    assert _cons_pair("CONS_SAT1_C") == {"ConsL4", "ConsL6"}
    assert _cons_pair("CONS_SAT1_D") == {"ConsL3", "ConsL5"}
    assert _cons_pair("CONS_SAT2_C") == {"ConsL1", "ConsL4"}
    assert _cons_pair("CONS_SAT2_D") == {"ConsL2", "ConsL3"}

    # Sunday cross-pool placement by final standing: C1vD1, C2vD2, C3vD3.
    placement = sorted(
        (m for m in matches if m.match_type == "PLACEMENT"),
        key=lambda m: m.match_code,
    )
    assert [(m.placeholder_side_a, m.placeholder_side_b) for m in placement] == [
        ("C1", "D1"),
        ("C2", "D2"),
        ("C3", "D3"),
    ]


def test_wf_14_stale_draw_plan_coerced_on_generate(session, client):
    """14-team event with legacy WF_TO_POOLS_DYNAMIC JSON still generates via WF_14."""
    from sqlmodel import select

    from app.models.match import Match

    tournament = Tournament(
        name="Waterville",
        location="L",
        timezone="America/New_York",
        start_date=date(2026, 7, 24),
        end_date=date(2026, 7, 26),
        use_time_windows=False,
    )
    session.add(tournament)
    session.commit()
    session.refresh(tournament)

    womens = Event(
        tournament_id=tournament.id,
        category="womens",
        name="Women's",
        team_count=14,
        draw_plan_json=json.dumps({"template_type": "WF_TO_POOLS_DYNAMIC", "wf_rounds": 2, "guarantee": 5}),
        draw_status="final",
        wf_block_minutes=60,
        standard_block_minutes=105,
    )
    session.add(womens)
    session.commit()
    session.refresh(womens)

    for seed in range(1, 15):
        session.add(
            Team(
                event_id=womens.id,
                name=f"W {seed}",
                seed=seed,
                rating=float(1500 - seed),
            )
        )
    session.commit()

    version = ScheduleVersion(tournament_id=tournament.id, version_number=1, status="draft")
    session.add(version)
    session.commit()
    session.refresh(version)

    resp = client.post(f"/api/tournaments/{tournament.id}/schedule/versions/{version.id}/matches/generate")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["matches_generated"] == wf_14_total_generated_matches()
    assert "Women's" in (body.get("events_included") or [])
    assert body.get("events_skipped") in (None, [])

    count = len(
        session.exec(
            select(Match).where(
                Match.schedule_version_id == version.id,
                Match.event_id == womens.id,
            )
        ).all()
    )
    assert count == wf_14_total_generated_matches()


def test_wf_14_generates_when_event_has_extra_team_rows(session, client):
    """Extra team rows on the event (e.g. bad import) must not break WF R1 pairing."""
    from sqlmodel import select

    from app.models.match import Match

    tournament = Tournament(
        name="Extra Teams",
        location="L",
        timezone="America/New_York",
        start_date=date(2026, 7, 24),
        end_date=date(2026, 7, 26),
        use_time_windows=False,
    )
    session.add(tournament)
    session.commit()
    session.refresh(tournament)

    womens = Event(
        tournament_id=tournament.id,
        category="womens",
        name="Women's",
        team_count=14,
        draw_plan_json=json.dumps({"template_type": "WF_14_TOP2_BYE", "wf_rounds": 2}),
        draw_status="final",
    )
    session.add(womens)
    session.commit()
    session.refresh(womens)

    for seed in range(1, 63):
        session.add(
            Team(
                event_id=womens.id,
                name=f"W {seed}",
                seed=seed,
                rating=float(1600 - seed),
            )
        )
    session.commit()

    version = ScheduleVersion(tournament_id=tournament.id, version_number=1, status="draft")
    session.add(version)
    session.commit()
    session.refresh(version)

    resp = client.post(f"/api/tournaments/{tournament.id}/schedule/versions/{version.id}/matches/generate")
    assert resp.status_code == 200, resp.text
    assert resp.json()["matches_generated"] == wf_14_total_generated_matches()

    count = len(
        session.exec(
            select(Match).where(
                Match.schedule_version_id == version.id,
                Match.event_id == womens.id,
            )
        ).all()
    )
    assert count == wf_14_total_generated_matches()
