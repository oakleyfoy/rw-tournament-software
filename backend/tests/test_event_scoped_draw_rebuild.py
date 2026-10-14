"""Event-scoped draw finalize + match regenerate (Mixed without touching Women's)."""

import json
from datetime import date

from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine, select
from sqlmodel.pool import StaticPool

from app.database import get_session
from app.main import app
from app.models import Event, Match, ScheduleVersion, Tournament


def _make_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def test_finalize_8_team_pools_dynamic_two_wf_rounds():
    """Finalize Mixed 8-team WF_TO_POOLS_DYNAMIC with 2 WF → 8 WF + 12 RR."""
    session = _make_session()

    def get_session_override():
        return session

    app.dependency_overrides[get_session] = get_session_override
    client = TestClient(app)

    try:
        tournament = Tournament(
            name="Scottsdale Mixed Rebuild",
            location="Scottsdale",
            timezone="America/Phoenix",
            start_date=date(2026, 10, 16),
            end_date=date(2026, 10, 18),
        )
        session.add(tournament)
        session.commit()
        session.refresh(tournament)

        event = Event(
            tournament_id=tournament.id,
            name="Mixed",
            category="mixed",
            team_count=8,
            draw_status="draft",
            draw_plan_json=json.dumps(
                {
                    "version": "1.0",
                    "template_type": "WF_TO_POOLS_DYNAMIC",
                    "wf_rounds": 2,
                    "timing": {"wf_block_minutes": 60, "standard_block_minutes": 120},
                }
            ),
        )
        session.add(event)
        session.commit()
        session.refresh(event)

        response = client.post(
            f"/api/events/{event.id}/draw-plan/finalize",
            json={"guarantee_selected": 4},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["draw_status"] == "final"
        assert body["matches_created"] == 20  # 8 WF + 12 RR

        matches = session.exec(select(Match).where(Match.event_id == event.id)).all()
        assert len(matches) == 20
        assert sum(1 for m in matches if m.match_type == "WF") == 8
        assert sum(1 for m in matches if m.match_type == "RR") == 12
    finally:
        app.dependency_overrides.clear()
        session.close()


def test_generate_matches_only_event_scoped_leaves_other_event():
    """Wipe+regenerate Mixed only; Women's matches stay intact."""
    session = _make_session()

    def get_session_override():
        return session

    app.dependency_overrides[get_session] = get_session_override
    client = TestClient(app)

    try:
        tournament = Tournament(
            name="Event Scoped Gen",
            location="Test",
            timezone="America/Phoenix",
            start_date=date(2026, 10, 16),
            end_date=date(2026, 10, 18),
        )
        session.add(tournament)
        session.commit()
        session.refresh(tournament)

        version = ScheduleVersion(tournament_id=tournament.id, version_number=1, status="draft")
        session.add(version)
        session.commit()
        session.refresh(version)

        mixed = Event(
            tournament_id=tournament.id,
            name="Mixed",
            category="mixed",
            team_count=8,
            draw_status="final",
            draw_plan_json=json.dumps(
                {
                    "version": "1.0",
                    "template_type": "WF_TO_POOLS_DYNAMIC",
                    "wf_rounds": 2,
                    "timing": {"wf_block_minutes": 60, "standard_block_minutes": 120},
                }
            ),
        )
        womens = Event(
            tournament_id=tournament.id,
            name="Women's",
            category="womens",
            team_count=8,
            draw_status="final",
            draw_plan_json=json.dumps(
                {
                    "version": "1.0",
                    "template_type": "WF_TO_POOLS_DYNAMIC",
                    "wf_rounds": 1,
                    "timing": {"wf_block_minutes": 60, "standard_block_minutes": 120},
                }
            ),
        )
        session.add(mixed)
        session.add(womens)
        session.commit()
        session.refresh(mixed)
        session.refresh(womens)

        # Seed Women's with a sentinel match that must survive Mixed rebuild.
        sentinel = Match(
            tournament_id=tournament.id,
            event_id=womens.id,
            schedule_version_id=version.id,
            match_code=f"E{womens.id}_SENTINEL",
            match_type="WF",
            round_number=1,
            round_index=1,
            sequence_in_round=1,
            duration_minutes=60,
            placeholder_side_a="Keep A",
            placeholder_side_b="Keep B",
            status="unscheduled",
        )
        session.add(sentinel)
        session.commit()
        session.refresh(sentinel)
        womens_match_id = sentinel.id
        womens_code = sentinel.match_code

        # First generate Mixed (event-scoped).
        r1 = client.post(
            f"/api/tournaments/{tournament.id}/schedule/versions/{version.id}/matches/generate",
            json={"event_id": mixed.id, "wipe_existing": True},
        )
        assert r1.status_code == 200, r1.text
        assert r1.json()["matches_generated"] == 20

        mixed_codes_before = {
            m.match_code
            for m in session.exec(select(Match).where(Match.event_id == mixed.id)).all()
        }
        assert len(mixed_codes_before) == 20

        womens_after_first = session.exec(select(Match).where(Match.event_id == womens.id)).all()
        assert len(womens_after_first) == 1
        assert womens_after_first[0].id == womens_match_id
        assert womens_after_first[0].match_code == womens_code

        # Wipe+regenerate Mixed again — Women's sentinel still untouched.
        r2 = client.post(
            f"/api/tournaments/{tournament.id}/schedule/versions/{version.id}/matches/generate",
            json={"event_id": mixed.id, "wipe_existing": True},
        )
        assert r2.status_code == 200, r2.text
        assert r2.json()["matches_generated"] == 20

        womens_after_second = session.exec(select(Match).where(Match.event_id == womens.id)).all()
        assert len(womens_after_second) == 1
        assert womens_after_second[0].id == womens_match_id
        assert womens_after_second[0].match_code == womens_code

        mixed_after = session.exec(select(Match).where(Match.event_id == mixed.id)).all()
        assert len(mixed_after) == 20
    finally:
        app.dependency_overrides.clear()
        session.close()
