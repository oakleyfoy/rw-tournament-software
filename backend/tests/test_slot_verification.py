from datetime import date, time

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.models.schedule_slot import ScheduleSlot
from app.models.schedule_version import ScheduleVersion
from app.models.tournament import Tournament
from app.models.tournament_day import TournamentDay
from app.models.tournament_time_window import TournamentTimeWindow


def _create_tournament(session: Session, *, use_time_windows: bool) -> Tournament:
    tournament = Tournament(
        name="Slot Verification",
        location="Test",
        timezone="America/New_York",
        start_date=date(2026, 6, 5),
        end_date=date(2026, 6, 7),
        use_time_windows=use_time_windows,
        court_names=[str(i) for i in range(1, 25)],
    )
    session.add(tournament)
    session.commit()
    session.refresh(tournament)
    return tournament


def _create_version(session: Session, tournament_id: int) -> ScheduleVersion:
    version = ScheduleVersion(tournament_id=tournament_id, version_number=1, status="draft")
    session.add(version)
    session.commit()
    session.refresh(version)
    return version


def _verification(client: TestClient, tournament_id: int, version_id: int):
    response = client.get(f"/api/tournaments/{tournament_id}/schedule/versions/{version_id}/slots/verification")
    assert response.status_code == 200, response.text
    return response.json()


def test_time_windows_verified_after_generate(client: TestClient, session: Session):
    tournament = _create_tournament(session, use_time_windows=True)
    session.add(
        TournamentTimeWindow(
            tournament_id=tournament.id,
            day_date=date(2026, 6, 5),
            start_time=time(9, 30),
            end_time=time(10, 30),
            courts_available=17,
            block_minutes=60,
            is_active=True,
        )
    )
    session.commit()
    version = _create_version(session, tournament.id)

    generated = client.post(f"/api/tournaments/{tournament.id}/schedule/versions/{version.id}/slots/generate")
    assert generated.status_code == 200
    assert generated.json()["slots_generated"] == 17

    body = _verification(client, tournament.id, version.id)
    assert body["source"] == "time_windows"
    assert body["expected_slots"] == 17
    assert body["generated_slots"] == 17
    assert body["status"] == "verified"
    assert len(body["days"]) == 1
    period = body["days"][0]["periods"][0]
    assert period["start_time"].startswith("09:30")
    assert period["end_time"].startswith("10:30")
    assert period["courts"] == 17
    assert period["expected_slots"] == 17
    assert period["generated_slots"] == 17
    assert period["status"] == "verified"


def test_overlapping_windows_remain_separate_rows(client: TestClient, session: Session):
    tournament = _create_tournament(session, use_time_windows=True)
    session.add_all(
        [
            TournamentTimeWindow(
                tournament_id=tournament.id,
                day_date=date(2026, 6, 6),
                start_time=time(8, 0),
                end_time=time(9, 30),
                courts_available=17,
                block_minutes=90,
                is_active=True,
            ),
            TournamentTimeWindow(
                tournament_id=tournament.id,
                day_date=date(2026, 6, 6),
                start_time=time(9, 0),
                end_time=time(10, 45),
                courts_available=17,
                block_minutes=105,
                is_active=True,
            ),
        ]
    )
    session.commit()
    version = _create_version(session, tournament.id)
    generated = client.post(f"/api/tournaments/{tournament.id}/schedule/versions/{version.id}/slots/generate")
    assert generated.status_code == 200
    assert generated.json()["slots_generated"] == 34

    body = _verification(client, tournament.id, version.id)
    assert len(body["days"]) == 1
    periods = body["days"][0]["periods"]
    assert len(periods) == 2
    assert [period["start_time"][:5] for period in periods] == ["08:00", "09:00"]
    assert all(period["expected_slots"] == 17 for period in periods)
    assert all(period["generated_slots"] == 17 for period in periods)
    assert all(period["status"] == "verified" for period in periods)
    assert body["status"] == "verified"


def test_deleted_slot_is_mismatch_not_auto_fixed(client: TestClient, session: Session):
    tournament = _create_tournament(session, use_time_windows=True)
    session.add(
        TournamentTimeWindow(
            tournament_id=tournament.id,
            day_date=date(2026, 6, 5),
            start_time=time(12, 30),
            end_time=time(13, 30),
            courts_available=17,
            block_minutes=60,
            is_active=True,
        )
    )
    session.commit()
    version = _create_version(session, tournament.id)
    client.post(f"/api/tournaments/{tournament.id}/schedule/versions/{version.id}/slots/generate")

    before = session.exec(select(ScheduleSlot).where(ScheduleSlot.schedule_version_id == version.id)).all()
    assert len(before) == 17
    session.delete(before[0])
    session.commit()

    body = _verification(client, tournament.id, version.id)
    assert body["expected_slots"] == 17
    assert body["generated_slots"] == 16
    assert body["status"] == "mismatch"
    assert body["days"][0]["periods"][0]["status"] == "mismatch"

    after = session.exec(select(ScheduleSlot).where(ScheduleSlot.schedule_version_id == version.id)).all()
    assert len(after) == 16


def test_days_courts_verified_after_generate(client: TestClient, session: Session):
    tournament = _create_tournament(session, use_time_windows=False)
    session.add(
        TournamentDay(
            tournament_id=tournament.id,
            date=date(2026, 6, 7),
            is_active=True,
            start_time=time(8, 0),
            end_time=time(10, 0),
            courts_available=12,
        )
    )
    session.commit()
    version = _create_version(session, tournament.id)
    generated = client.post(f"/api/tournaments/{tournament.id}/schedule/versions/{version.id}/slots/generate")
    assert generated.status_code == 200
    # No events → 60-minute blocks, 08:00 and 09:00 × 12 courts
    assert generated.json()["slots_generated"] == 24

    body = _verification(client, tournament.id, version.id)
    assert body["source"] == "days_courts"
    assert body["expected_slots"] == 24
    assert body["generated_slots"] == 24
    assert body["status"] == "verified"
    period = body["days"][0]["periods"][0]
    assert period["courts"] == 12
    assert period["blocks_per_court"] == 2
    assert period["source_kind"] == "tournament_day"


def test_verification_get_does_not_change_slots(client: TestClient, session: Session):
    tournament = _create_tournament(session, use_time_windows=True)
    session.add(
        TournamentTimeWindow(
            tournament_id=tournament.id,
            day_date=date(2026, 6, 5),
            start_time=time(14, 0),
            end_time=time(15, 0),
            courts_available=8,
            extra_courts=2,
            block_minutes=60,
            is_active=True,
        )
    )
    session.commit()
    version = _create_version(session, tournament.id)
    client.post(f"/api/tournaments/{tournament.id}/schedule/versions/{version.id}/slots/generate")
    ids_before = {
        slot.id
        for slot in session.exec(select(ScheduleSlot).where(ScheduleSlot.schedule_version_id == version.id)).all()
    }
    body = _verification(client, tournament.id, version.id)
    assert body["expected_slots"] == 10
    assert body["generated_slots"] == 10
    ids_after = {
        slot.id
        for slot in session.exec(select(ScheduleSlot).where(ScheduleSlot.schedule_version_id == version.id)).all()
    }
    assert ids_before == ids_after


def test_unknown_version_404(client: TestClient, session: Session):
    tournament = _create_tournament(session, use_time_windows=True)
    response = client.get(f"/api/tournaments/{tournament.id}/schedule/versions/99999/slots/verification")
    assert response.status_code == 404
