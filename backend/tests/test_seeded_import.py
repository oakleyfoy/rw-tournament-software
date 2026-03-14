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

    teams_after = session.exec(
        select(Team).where(Team.event_id == event.id).order_by(Team.seed)
    ).all()
    assert len(teams_after) == 12
    assert [t.seed for t in teams_after] == list(range(1, 13))

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

    teams_after = session.exec(
        select(Team).where(Team.event_id == event.id).order_by(Team.seed)
    ).all()
    assert len(teams_after) == 12
    assert [t.seed for t in teams_after] == list(range(1, 13))

    session.expire_all()
    match_after = session.get(Match, match.id)
    assert match_after is not None
    assert match_after.team_a_id is None
    assert match_after.team_b_id is None
    assert match_after.winner_team_id is None
