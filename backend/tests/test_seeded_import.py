from datetime import date

from sqlmodel import select

from app.models.event import Event
from app.models.match import Match
from app.models.schedule_version import ScheduleVersion
from app.models.team import Team
from app.models.tournament import Tournament


def test_seeded_import_prunes_stale_teams_and_syncs_event_team_count(client, session):
    tournament = Tournament(
        name="Vegas Import Sync",
        location="Las Vegas",
        timezone="America/Chicago",
        start_date=date(2026, 5, 1),
        end_date=date(2026, 5, 3),
    )
    session.add(tournament)
    session.commit()
    session.refresh(tournament)

    event = Event(
        tournament_id=tournament.id,
        name="Womens",
        category="womens",
        team_count=16,
        draw_status="final",
    )
    session.add(event)
    session.commit()
    session.refresh(event)

    for seed in range(1, 17):
        session.add(
            Team(
                event_id=event.id,
                name=f"Old Team {seed}",
                seed=seed,
                display_name=f"Old {seed}",
                notes=f"Legacy note {seed}",
                is_defaulted=True,
            )
        )
    session.commit()

    # Import only 12 seeds; endpoint should prune stale 13-16.
    lines = []
    for seed in range(1, 13):
        lines.append(f"{seed} 9.0 Player{seed}A / Player{seed}B")
    payload = {"format": "sectioned_text", "text": "\n".join(lines)}

    resp = client.post(
        f"/api/tournaments/{tournament.id}/events/{event.id}/teams/import-seeded",
        json=payload,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert any("Removed 4 stale team(s)" in w for w in body["warnings"])

    teams_after = session.exec(select(Team).where(Team.event_id == event.id).order_by(Team.seed)).all()
    assert len(teams_after) == 12
    assert [t.seed for t in teams_after] == list(range(1, 13))
    assert all(t.notes is None for t in teams_after)
    assert all(t.is_defaulted is False for t in teams_after)

    session.expire_all()
    event_after = session.get(Event, event.id)
    assert event_after.team_count == 12


def test_seeded_import_clears_draft_match_references_for_removed_stale_teams(client, session):
    tournament = Tournament(
        name="Vegas Draft Cleanup",
        location="Las Vegas",
        timezone="America/Chicago",
        start_date=date(2026, 5, 1),
        end_date=date(2026, 5, 3),
    )
    session.add(tournament)
    session.commit()
    session.refresh(tournament)

    event = Event(
        tournament_id=tournament.id,
        name="Womens",
        category="womens",
        team_count=16,
        draw_status="final",
    )
    session.add(event)
    session.commit()
    session.refresh(event)

    teams = []
    for seed in range(1, 17):
        team = Team(
            event_id=event.id,
            name=f"Old Team {seed}",
            seed=seed,
            display_name=f"Old {seed}",
        )
        session.add(team)
        session.flush()
        teams.append(team)
    session.commit()

    version = ScheduleVersion(
        tournament_id=tournament.id,
        version_number=1,
        status="draft",
    )
    session.add(version)
    session.flush()

    stale_a = teams[12]  # seed 13
    stale_b = teams[13]  # seed 14
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
        team_a_id=stale_a.id,
        team_b_id=stale_b.id,
        winner_team_id=stale_a.id,
        placeholder_side_a="Seed 13",
        placeholder_side_b="Seed 14",
        runtime_status="SCHEDULED",
    )
    session.add(match)
    session.commit()
    session.refresh(match)

    lines = []
    for seed in range(1, 13):
        lines.append(f"{seed} 9.0 Player{seed}A / Player{seed}B")
    payload = {"format": "sectioned_text", "text": "\n".join(lines)}

    resp = client.post(
        f"/api/tournaments/{tournament.id}/events/{event.id}/teams/import-seeded",
        json=payload,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert any("Removed 4 stale team(s)" in w for w in body["warnings"])

    teams_after = session.exec(select(Team).where(Team.event_id == event.id).order_by(Team.seed)).all()
    assert len(teams_after) == 12
    assert [t.seed for t in teams_after] == list(range(1, 13))

    session.expire_all()
    match_after = session.get(Match, match.id)
    assert match_after is not None
    assert match_after.team_a_id is None
    assert match_after.team_b_id is None
    assert match_after.winner_team_id is None


def _finalized_mixed_tournament(session):
    tournament = Tournament(
        name="Combined Finalized",
        location="KC",
        timezone="America/Chicago",
        start_date=date(2026, 7, 24),
        end_date=date(2026, 7, 26),
    )
    session.add(tournament)
    session.commit()
    session.refresh(tournament)

    event = Event(
        tournament_id=tournament.id,
        name="Mixed",
        category="mixed",
        team_count=16,
        draw_status="final",
    )
    session.add(event)
    session.commit()
    session.refresh(event)

    teams = []
    for seed in range(1, 17):
        team = Team(
            event_id=event.id,
            name=f"Team {seed}, City, ST",
            seed=seed,
            display_name=f"Team {seed}",
        )
        session.add(team)
        session.flush()
        teams.append(team)

    # Finalized schedule version referencing every team → all 16 are "blocked".
    version = ScheduleVersion(
        tournament_id=tournament.id,
        version_number=1,
        status="final",
    )
    session.add(version)
    session.flush()

    for i in range(0, 16, 2):
        a, b = teams[i], teams[i + 1]
        session.add(
            Match(
                tournament_id=tournament.id,
                event_id=event.id,
                schedule_version_id=version.id,
                match_code=f"MIX_WF_R1_{i // 2 + 1:02d}",
                match_type="WF",
                round_number=1,
                round_index=1,
                sequence_in_round=i // 2 + 1,
                duration_minutes=60,
                team_a_id=a.id,
                team_b_id=b.id,
                winner_team_id=a.id,
                placeholder_side_a=f"Seed {a.seed}",
                placeholder_side_b=f"Seed {b.seed}",
                runtime_status="FINAL",
            )
        )
    session.commit()
    return tournament, event, teams


_COMBINED_HEADER = (
    "Seed\tFirst names team\tFull name city state team\tDraw\tLevel\t"
    "Cell phone first player\tEmail first player"
)


def test_combined_import_refreshes_finalized_roster_in_place(client, session):
    """Same teams at the same seeds → towel/contact info updates in place without
    wiping the finalized roster (team IDs and finalized assignments preserved)."""
    tournament, event, teams = _finalized_mixed_tournament(session)
    original_ids = {t.seed: t.id for t in teams}

    lines = [_COMBINED_HEADER]
    for seed in range(1, 17):
        lines.append(
            f"{seed}\tTeam {seed}\tTeam {seed}, City, ST\tMixed\t9.0\t555000{seed:04d}\tp{seed}@x.com"
        )
    payload = {"text": "\n".join(lines)}

    resp = client.post(
        f"/api/tournaments/{tournament.id}/teams/import-combined",
        json=payload,
    )
    assert resp.status_code == 200, resp.text

    session.expire_all()
    teams_after = session.exec(select(Team).where(Team.event_id == event.id).order_by(Team.seed)).all()
    assert len(teams_after) == 16
    # Team identities (IDs) are preserved — no wipe/recreate.
    assert {t.seed: t.id for t in teams_after} == original_ids
    # Contact info was refreshed in place.
    seed1 = next(t for t in teams_after if t.seed == 1)
    assert seed1.p1_cell == "5550000001"
    assert seed1.p1_email == "p1@x.com"


def test_combined_import_blocks_identity_change_on_finalized_team(client, session):
    """A *different* team at a finalized seed would change who plays a finalized
    match → the import is blocked with a 409."""
    tournament, event, _teams = _finalized_mixed_tournament(session)

    lines = [_COMBINED_HEADER]
    for seed in range(1, 17):
        name = "Brand New Team, City, ST" if seed == 1 else f"Team {seed}, City, ST"
        display = "Brand New" if seed == 1 else f"Team {seed}"
        lines.append(f"{seed}\t{display}\t{name}\tMixed\t9.0\t5550000000\tp@x.com")
    payload = {"text": "\n".join(lines)}

    resp = client.post(
        f"/api/tournaments/{tournament.id}/teams/import-combined",
        json=payload,
    )
    assert resp.status_code == 409, resp.text
    detail = resp.json()["detail"]
    assert "would be reassigned" in detail
    assert "seed 1" in detail

    # Roster untouched by the rejected import.
    session.expire_all()
    seed1 = session.exec(
        select(Team).where(Team.event_id == event.id, Team.seed == 1)
    ).first()
    assert seed1.name == "Team 1, City, ST"
