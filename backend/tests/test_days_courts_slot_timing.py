import json
from datetime import date, time

from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine, select
from sqlmodel.pool import StaticPool

from app.database import get_session
from app.main import app
from app.models import Event, ScheduleSlot, ScheduleVersion, Tournament, TournamentDay


def _make_session() -> Session:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def test_days_courts_slot_generation_uses_draw_plan_timing_by_day():
    session = _make_session()

    def get_session_override():
        return session

    app.dependency_overrides[get_session] = get_session_override
    client = TestClient(app)

    try:
        tournament = Tournament(
            name="Days Courts Timing Test",
            location="Test",
            timezone="America/New_York",
            start_date=date(2026, 4, 10),
            end_date=date(2026, 4, 11),
            use_time_windows=False,
            court_names=["Court 1"],
        )
        session.add(tournament)
        session.commit()
        session.refresh(tournament)

        session.add(
            TournamentDay(
                tournament_id=tournament.id,
                date=date(2026, 4, 10),
                is_active=True,
                start_time=time(10, 0),
                end_time=time(13, 0),
                courts_available=1,
            )
        )
        session.add(
            TournamentDay(
                tournament_id=tournament.id,
                date=date(2026, 4, 11),
                is_active=True,
                start_time=time(10, 0),
                end_time=time(13, 30),
                courts_available=1,
            )
        )
        session.commit()

        version = ScheduleVersion(tournament_id=tournament.id, version_number=1, status="draft")
        session.add(version)
        session.commit()
        session.refresh(version)

        event = Event(
            tournament_id=tournament.id,
            name="Womens",
            category="womens",
            team_count=20,
            draw_status="final",
            wf_block_minutes=105,
            standard_block_minutes=60,
            draw_plan_json=json.dumps(
                {
                    "version": "1.0",
                    "template_type": "WF_TO_POOLS_DYNAMIC",
                    "wf_rounds": 2,
                    "timing": {
                        "wf_block_minutes": 60,
                        "standard_block_minutes": 105,
                    },
                }
            ),
        )
        session.add(event)
        session.commit()

        response = client.post(
            f"/api/tournaments/{tournament.id}/schedule/versions/{version.id}/slots/generate"
        )
        assert response.status_code == 200, response.text

        slots = session.exec(
            select(ScheduleSlot).where(ScheduleSlot.schedule_version_id == version.id)
        ).all()
        assert slots

        day_one_blocks = {
            slot.block_minutes for slot in slots if slot.day_date == date(2026, 4, 10)
        }
        day_two_blocks = {
            slot.block_minutes for slot in slots if slot.day_date == date(2026, 4, 11)
        }
        assert day_one_blocks == {60}
        assert day_two_blocks == {105}
    finally:
        app.dependency_overrides.clear()
        session.close()
