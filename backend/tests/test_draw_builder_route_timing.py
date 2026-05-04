import json
from datetime import date, time

from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine, select
from sqlmodel.pool import StaticPool

from app.database import get_session
from app.main import app
from app.models import Event, Match, Tournament
from app.models.match_assignment import MatchAssignment
from app.models.schedule_slot import ScheduleSlot
from app.models.schedule_version import ScheduleVersion


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


def test_finalize_draw_plan_again_removes_match_assignments_first():
    """Re-finalize deletes assignments (and related rows) before deleting matches."""
    session = _make_session()

    def get_session_override():
        return session

    app.dependency_overrides[get_session] = get_session_override
    client = TestClient(app)

    try:
        tournament = Tournament(
            name="Draw Builder Re-finalize FK Test",
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

        r1 = client.post(
            f"/api/events/{event.id}/draw-plan/finalize",
            json={"guarantee_selected": 5},
        )
        assert r1.status_code == 200, r1.text

        match_one = session.exec(select(Match).where(Match.event_id == event.id)).first()
        assert match_one is not None and match_one.id is not None

        version = session.exec(
            select(ScheduleVersion)
            .where(ScheduleVersion.tournament_id == tournament.id)
            .order_by(ScheduleVersion.version_number.desc())
        ).first()
        assert version is not None

        slot = ScheduleSlot(
            tournament_id=tournament.id,
            schedule_version_id=version.id,
            day_date=date(2026, 3, 1),
            start_time=time(9, 0),
            end_time=time(11, 0),
            court_number=1,
            court_label="1",
            block_minutes=120,
        )
        session.add(slot)
        session.commit()
        session.refresh(slot)

        session.add(
            MatchAssignment(
                schedule_version_id=version.id,
                match_id=match_one.id,
                slot_id=slot.id,
            )
        )
        session.commit()

        r2 = client.post(
            f"/api/events/{event.id}/draw-plan/finalize",
            json={"guarantee_selected": 5},
        )
        assert r2.status_code == 200, r2.text

        matches_after = session.exec(select(Match).where(Match.event_id == event.id)).all()
        assert matches_after
        assert session.exec(select(MatchAssignment).where(MatchAssignment.match_id == match_one.id)).first() is None
    finally:
        app.dependency_overrides.clear()
        session.close()
