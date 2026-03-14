from datetime import date

from sqlmodel import select

from app.models.event import Event
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
