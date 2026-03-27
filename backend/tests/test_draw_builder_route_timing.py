import json
from datetime import date

from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine, select
from sqlmodel.pool import StaticPool

from app.database import get_session
from app.main import app
from app.models import Event, Match, Tournament


def _make_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def test_finalize_draw_plan_uses_draw_plan_timing_over_stale_event_columns():
    session = _make_session()

    def get_session_override():
        return session

    app.dependency_overrides[get_session] = get_session_override
    client = TestClient(app)

    try:
        tournament = Tournament(
            name="Draw Builder Timing Test",
            location="Test",
            timezone="America/New_York",
            start_date=date(2026, 3, 1),
            end_date=date(2026, 3, 2),
        )
        session.add(tournament)
        session.commit()
        session.refresh(tournament)

        event = Event(
            tournament_id=tournament.id,
            name="Mixed",
            category="mixed",
            team_count=16,
            draw_status="draft",
            wf_block_minutes=105,
            standard_block_minutes=90,
            draw_plan_json=json.dumps(
                {
                    "version": "1.0",
                    "template_type": "WF_TO_POOLS_4",
                    "wf_rounds": 2,
                    "timing": {
                        "wf_block_minutes": 60,
                        "standard_block_minutes": 120,
                    },
                }
            ),
        )
        session.add(event)
        session.commit()
        session.refresh(event)

        response = client.post(
            f"/api/events/{event.id}/draw-plan/finalize",
            json={"guarantee_selected": 5},
        )
        assert response.status_code == 200, response.text

        session.refresh(event)
        assert event.draw_status == "final"
        assert event.wf_block_minutes == 60
        assert event.standard_block_minutes == 120

        matches = session.exec(select(Match).where(Match.event_id == event.id)).all()
        assert matches
        assert any(m.match_type == "WF" for m in matches)
        assert any(m.match_type != "WF" for m in matches)
        assert all(m.duration_minutes == 60 for m in matches if m.match_type == "WF")
        assert all(m.duration_minutes == 120 for m in matches if m.match_type != "WF")
    finally:
        app.dependency_overrides.clear()
        session.close()
