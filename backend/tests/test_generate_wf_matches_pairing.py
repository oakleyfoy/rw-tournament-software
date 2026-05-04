"""Regression: finalize-draw WF match generation uses half-split R1 (not Berger shell)."""

from datetime import date

from app.models.event import Event
from app.models.schedule_version import ScheduleVersion
from app.models.team import Team
from app.models.tournament import Tournament
from app.services.wf_pairing import TeamSeed, build_wf_r1_pairings
from app.utils.match_generation import generate_wf_matches


def _seed_pairs_from_r1(matches: list) -> list[tuple[int | None, int | None]]:
    r1 = sorted(
        [m for m in matches if getattr(m, "round_number", None) == 1],
        key=lambda m: (m.sequence_in_round or 0, m.id or 0),
    )
    return [(m.team_a_id, m.team_b_id) for m in r1]


def test_generate_wf_matches_r1_matches_build_wf_r1_pairings(session):
    """WF R1 bindings must follow half-split + bracket-fold (same as draw_plan_engine)."""
    tournament = Tournament(
        name="WF gen pairing test",
        location="Test",
        timezone="America/New_York",
        start_date=date(2026, 5, 1),
        end_date=date(2026, 5, 2),
    )
    session.add(tournament)
    session.flush()

    event = Event(
        tournament_id=tournament.id,
        category="mixed",
        name="WF Event",
        team_count=32,
        wf_block_minutes=60,
        standard_block_minutes=120,
    )
    session.add(event)
    session.flush()

    sv = ScheduleVersion(tournament_id=tournament.id, version_number=1, status="draft")
    session.add(sv)
    session.flush()

    teams = []
    for s in range(1, 33):
        t = Team(event_id=event.id, name=f"Team {s}", seed=s)
        session.add(t)
        teams.append(t)
    session.flush()

    by_seed = {t.seed: t for t in teams}
    seed_teams = [
        TeamSeed(seed=s, team_id=by_seed[s].id, name=by_seed[s].name)
        for s in range(1, 33)
    ]
    expected = build_wf_r1_pairings(seed_teams, 32)

    matches = generate_wf_matches(
        event=event,
        schedule_version_id=sv.id,
        tournament_id=tournament.id,
        wf_rounds=1,
        duration_minutes=60,
        event_prefix="E1",
        session=session,
    )

    got_ids = _seed_pairs_from_r1(matches)
    assert len(got_ids) == 16
    assert got_ids == expected.team_id_pairs

    # Explicit regression: not Berger round-1 shell (which would be 1 vs 32 first).
    ta, tb = got_ids[0]
    t_by_id = {t.id: t for t in teams}
    assert t_by_id[ta].seed == 1
    assert t_by_id[tb].seed == 17


def test_generate_wf_matches_r1_fallback_top_bottom_by_rank_order(session):
    """Without full seed ladder 1..n, pair list positions i vs i+half."""
    tournament = Tournament(
        name="WF fallback pairing test",
        location="Test",
        timezone="America/New_York",
        start_date=date(2026, 5, 1),
        end_date=date(2026, 5, 2),
    )
    session.add(tournament)
    session.flush()

    event = Event(
        tournament_id=tournament.id,
        category="womens",
        name="WF Event 2",
        team_count=20,
        wf_block_minutes=60,
        standard_block_minutes=120,
    )
    session.add(event)
    session.flush()

    sv = ScheduleVersion(tournament_id=tournament.id, version_number=1, status="draft")
    session.add(sv)
    session.flush()

    teams = []
    # Seeds 2..21 (gap at 1) — pairing_ok fails → index half-split
    for s in range(2, 22):
        t = Team(event_id=event.id, name=f"Team {s}", seed=s)
        session.add(t)
        teams.append(t)
    session.flush()

    matches = generate_wf_matches(
        event=event,
        schedule_version_id=sv.id,
        tournament_id=tournament.id,
        wf_rounds=1,
        duration_minutes=60,
        event_prefix="E2",
        session=session,
    )

    ordered = sorted(teams, key=lambda t: (t.seed is None, t.seed or 0, t.id))
    t_by_id = {t.id: t for t in teams}
    got_ids = _seed_pairs_from_r1(matches)
    assert len(got_ids) == 10
    for i, (aid, bid) in enumerate(got_ids):
        assert {t_by_id[aid].seed, t_by_id[bid].seed} == {
            ordered[i].seed,
            ordered[i + 10].seed,
        }
