"""WF14 consolation rank fill and Sunday placement advancement."""

import json
from datetime import date

from sqlmodel import select

from app.models.event import Event
from app.models.match import Match
from app.models.schedule_version import ScheduleVersion
from app.models.team import Team
from app.models.tournament import Tournament
from app.services.advancement_service import (
    apply_advancement_for_final_match,
    apply_advancement_with_details,
)
from app.services.draw_plan_engine import DrawPlanSpec, generate_matches_for_event
from app.services.wf_14_consolation import compute_loser_rank_to_team
from app.services.wf_pool_projection import compute_wf_projection


def _finalize_r1(session, version_id):
    """Finalize the 6 non-bye WF R1 matches (team_a wins); return them."""
    r1_all = session.exec(
        select(Match).where(
            Match.schedule_version_id == version_id,
            Match.match_type == "WF",
            Match.round_index == 1,
        )
    ).all()
    r1 = [m for m in r1_all if "_BYE" not in (m.match_code or "").upper()]
    for m in r1:
        m.runtime_status = "FINAL"
        m.winner_team_id = m.team_a_id
        m.score_json = {"display": "8-3", "team_a_games": 8, "team_b_games": 3}
        session.add(m)
    session.commit()
    return r1


def _finalize_match(session, match: Match, winner_a: bool):
    match.runtime_status = "FINAL"
    match.winner_team_id = match.team_a_id if winner_a else match.team_b_id
    session.add(match)
    session.commit()


def _build_wf14_event_with_matches(session):
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

    teams = []
    for seed in range(1, 15):
        t = Team(event_id=event.id, name=f"Team {seed}", seed=seed, rating=float(1500 - seed))
        session.add(t)
        teams.append(t)
    session.commit()
    for t in teams:
        session.refresh(t)

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
    linked = [t.id for t in sorted(teams, key=lambda x: x.seed)]
    matches, _ = generate_matches_for_event(session, version.id, spec, linked, set())
    session.add_all(matches)
    session.commit()
    return tournament, event, version


def test_wf14_consolation_fills_after_r1(session):
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

    teams = []
    for seed in range(1, 15):
        t = Team(event_id=event.id, name=f"Team {seed}", seed=seed, rating=float(1500 - seed))
        session.add(t)
        teams.append(t)
    session.commit()
    for t in teams:
        session.refresh(t)

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
    linked = [t.id for t in sorted(teams, key=lambda x: x.seed)]
    matches, _ = generate_matches_for_event(session, version.id, spec, linked, set())
    session.add_all(matches)
    session.commit()

    r1_all = session.exec(
        select(Match).where(
            Match.schedule_version_id == version.id,
            Match.match_type == "WF",
            Match.round_index == 1,
        )
    ).all()
    # Two of the R1 rows are auto-won byes (no opponent); only the 6 played games
    # produce consolation losers.
    byes = [m for m in r1_all if "_BYE" in m.match_code]
    r1 = [m for m in r1_all if m not in byes]
    assert len(byes) == 2
    assert len(r1) == 6

    for m in r1:
        assert m.team_a_id and m.team_b_id
        _finalize_match(session, m, winner_a=True)
        apply_advancement_for_final_match(session, m.id)

    ranks = compute_loser_rank_to_team(session, event.id, version.id)
    assert ranks is not None
    assert len(ranks) == 6

    cons_fri = session.exec(
        select(Match).where(
            Match.schedule_version_id == version.id,
            Match.match_code.contains("CONS_FRI"),
        )
    ).all()
    assert len(cons_fri) == 2
    for m in cons_fri:
        assert m.team_a_id is not None and m.team_b_id is not None


def test_wf14_consolation_fills_via_desk_finalize_path(session):
    """Regression: the desk finalize path (apply_advancement_with_details) must
    also populate Division III/IV consolation matches after WF R1 completes."""
    _tournament, event, version = _build_wf14_event_with_matches(session)

    r1_all = session.exec(
        select(Match).where(
            Match.schedule_version_id == version.id,
            Match.match_type == "WF",
            Match.round_index == 1,
        )
    ).all()
    r1 = [m for m in r1_all if "_BYE" not in (m.match_code or "").upper()]
    assert len(r1) == 6

    for m in r1:
        assert m.team_a_id and m.team_b_id
        _finalize_match(session, m, winner_a=True)
        apply_advancement_with_details(session, m.id)

    cons_pool = session.exec(
        select(Match).where(
            Match.schedule_version_id == version.id,
            Match.match_type == "MAIN",
            Match.match_code.contains("CONS_"),
        )
    ).all()
    cons_pool = [m for m in cons_pool if "CONS_SUN" not in (m.match_code or "")]
    assert len(cons_pool) > 0
    for m in cons_pool:
        assert m.team_a_id is not None, f"{m.match_code} side A not populated"
        assert m.team_b_id is not None, f"{m.match_code} side B not populated"


def test_wf14_loser_projection_shape(session):
    """Projection surfaces the loser flight as one Division III split into Pools C/D."""
    _tournament, event, version = _build_wf14_event_with_matches(session)

    # Before WF R1 finals: projection exists but is not complete.
    proj = compute_wf_projection(session, event.tournament_id, version.id, event.id)
    assert proj is not None
    assert proj.wf_complete is False
    labels = {p.pool_label for p in proj.pools}
    assert labels == {"POOLC", "POOLD"}

    _finalize_r1(session, version.id)

    proj = compute_wf_projection(session, event.tournament_id, version.id, event.id)
    assert proj is not None
    assert proj.wf_complete is True
    by_label = {p.pool_label: p for p in proj.pools}
    assert len(by_label["POOLC"].teams) == 3
    assert len(by_label["POOLD"].teams) == 3
    # Both pools grouped under a single Division III.
    assert by_label["POOLC"].pool_display.startswith("Division III")
    assert by_label["POOLD"].pool_display.startswith("Division III")
    # Reseed 1,4,6 -> Pool C; 2,3,5 -> Pool D (rank 1 = best original seed among losers).
    ranks = compute_loser_rank_to_team(session, event.id, version.id)
    assert [t.team_id for t in by_label["POOLC"].teams] == [ranks[1], ranks[4], ranks[6]]
    assert [t.team_id for t in by_label["POOLD"].teams] == [ranks[2], ranks[3], ranks[5]]


def test_wf14_split_pools_on_live_version(client, session):
    """The manual Split Pools action works on a LIVE (non-draft) version and fills C/D."""
    tournament, event, version = _build_wf14_event_with_matches(session)
    version.status = "final"
    session.add(version)
    session.commit()

    _finalize_r1(session, version.id)

    resp = client.post(
        f"/api/desk/tournaments/{tournament.id}/pool-placement",
        json={"version_id": version.id, "event_id": event.id, "pools": []},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is True
    assert body["updated_matches"] > 0

    cons_pool = session.exec(
        select(Match).where(
            Match.schedule_version_id == version.id,
            Match.match_type == "MAIN",
            Match.match_code.contains("CONS_"),
        )
    ).all()
    cons_pool = [m for m in cons_pool if "CONS_SUN" not in (m.match_code or "")]
    assert len(cons_pool) == 6
    for m in cons_pool:
        assert m.team_a_id is not None, f"{m.match_code} side A not populated"
        assert m.team_b_id is not None, f"{m.match_code} side B not populated"


def test_wf14_detected_by_matches_when_template_is_stale(client, session):
    """Duplicated/stale events whose draw_plan template no longer says WF_14 must
    still be recognized (via WF14_CONS_CROSS matches) so Split Pools works."""
    from app.services.wf_14_consolation import event_uses_wf14

    tournament, event, version = _build_wf14_event_with_matches(session)
    # Simulate a stale/duplicated event whose template string is generic.
    event.draw_plan_json = json.dumps({"template_type": "WF_TO_POOLS_DYNAMIC"})
    session.add(event)
    version.status = "final"
    session.add(version)
    session.commit()

    assert event_uses_wf14(session, event.id, version.id) is True

    _finalize_r1(session, version.id)

    # Projection must be the loser flight (Division III / Pools C+D), not generic.
    proj = compute_wf_projection(session, event.tournament_id, version.id, event.id)
    assert proj is not None
    assert {p.pool_label for p in proj.pools} == {"POOLC", "POOLD"}

    resp = client.post(
        f"/api/desk/tournaments/{tournament.id}/pool-placement",
        json={"version_id": version.id, "event_id": event.id, "pools": []},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["updated_matches"] > 0

    rr = client.get(
        f"/api/public/tournaments/{tournament.id}/events/{event.id}/roundrobin?version_id={version.id}"
    ).json()
    label_by_code = {p["pool_code"]: p["pool_label"] for p in rr["pools"]}
    assert label_by_code.get("POOLC", "").startswith("Division III")
    assert label_by_code.get("POOLD", "").startswith("Division III")
    assert "Division IV" not in " ".join(label_by_code.values())


def test_wf14_public_roundrobin_division_iii_labels(client, session):
    """Public RR shows C/D under one Division III and the relabeled placement round."""
    tournament, event, version = _build_wf14_event_with_matches(session)
    version.status = "final"
    session.add(version)
    session.commit()

    r1 = _finalize_r1(session, version.id)
    for m in r1:
        apply_advancement_with_details(session, m.id)

    resp = client.get(f"/api/public/tournaments/{tournament.id}/events/{event.id}/roundrobin?version_id={version.id}")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    label_by_code = {p["pool_code"]: p["pool_label"] for p in body["pools"]}
    assert label_by_code.get("POOLC", "").startswith("Division III")
    assert label_by_code.get("POOLD", "").startswith("Division III")
    assert "Division IV" not in " ".join(label_by_code.values())
    assert label_by_code.get("CD_PLACEMENT") == "Division III Placement (Pool C vs Pool D)"
