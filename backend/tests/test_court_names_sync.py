"""Saving court_names must relabel draft slots, trim excess, and cap day/window counts."""

from datetime import date, time

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.models.court_state import TournamentCourtState
from app.models.event import Event
from app.models.match import Match
from app.models.match_assignment import MatchAssignment
from app.models.schedule_slot import ScheduleSlot
from app.models.schedule_version import ScheduleVersion
from app.models.team import Team
from app.models.tournament import Tournament
from app.models.tournament_day import TournamentDay
from app.models.tournament_time_window import TournamentTimeWindow


def _old_labels(count: int = 15) -> list[str]:
    return [str(i) for i in range(1, count + 1)]


def _new_labels_5_to_18() -> list[str]:
    return [str(i) for i in range(5, 19)]


def _seed_tournament(session: Session, *, status: str = "draft", courts: int = 15) -> tuple:
    t = Tournament(
        name="Court Sync Test",
        location="Test",
        timezone="America/New_York",
        start_date=date(2026, 10, 16),
        end_date=date(2026, 10, 18),
        use_time_windows=True,
        court_names=_old_labels(courts),
    )
    session.add(t)
    session.flush()

    day = TournamentDay(
        tournament_id=t.id,
        date=date(2026, 10, 16),
        is_active=True,
        start_time=time(8, 0),
        end_time=time(18, 0),
        courts_available=courts,
    )
    window = TournamentTimeWindow(
        tournament_id=t.id,
        day_date=date(2026, 10, 16),
        start_time=time(8, 0),
        end_time=time(10, 0),
        courts_available=courts,
        extra_courts=0,
        block_minutes=60,
        is_active=True,
    )
    session.add_all([day, window])
    session.flush()

    v = ScheduleVersion(tournament_id=t.id, version_number=1, status=status)
    session.add(v)
    session.flush()

    slots = []
    for court_num in range(1, courts + 1):
        slot = ScheduleSlot(
            tournament_id=t.id,
            schedule_version_id=v.id,
            day_date=date(2026, 10, 16),
            start_time=time(8, 0),
            end_time=time(9, 0),
            court_number=court_num,
            court_label=str(court_num),
            block_minutes=60,
            is_active=True,
        )
        slots.append(slot)
    session.add_all(slots)

    session.add(
        TournamentCourtState(
            tournament_id=t.id,
            court_label="1",
            is_closed=True,
            note="Wet",
        )
    )
    session.commit()
    session.refresh(t)
    session.refresh(v)
    return t, v, day, window, slots


def test_save_court_names_relabels_trims_and_caps(client: TestClient, session: Session):
    t, v, day, window, _slots = _seed_tournament(session, status="draft", courts=15)
    new_names = _new_labels_5_to_18()
    assert len(new_names) == 14

    resp = client.put(
        f"/api/tournaments/{t.id}",
        json={"court_names": new_names},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["court_names"] == new_names
    sync = body["court_sync"]
    assert sync is not None
    assert sync["relabeled_slots"] == 14
    assert sync["removed_slots"] == 1
    assert sync["capped_windows"] == 1
    assert sync["capped_days"] == 1

    session.refresh(day)
    session.refresh(window)
    assert day.courts_available == 14
    assert window.courts_available == 14
    assert window.extra_courts == 0

    slots = session.exec(select(ScheduleSlot).where(ScheduleSlot.schedule_version_id == v.id)).all()
    assert len(slots) == 14
    by_num = {s.court_number: s.court_label for s in slots}
    assert by_num == {i + 1: new_names[i] for i in range(14)}
    assert 15 not in by_num

    states = session.exec(
        select(TournamentCourtState).where(TournamentCourtState.tournament_id == t.id)
    ).all()
    assert len(states) == 1
    assert states[0].court_label == "5"
    assert states[0].is_closed is True
    assert states[0].note == "Wet"


def test_save_court_names_rejects_when_excess_has_assignments(client: TestClient, session: Session):
    t, v, _day, _window, slots = _seed_tournament(session, status="draft", courts=15)

    event = Event(tournament_id=t.id, category="mixed", name="Mixed A", team_count=2)
    session.add(event)
    session.flush()
    team_a = Team(event_id=event.id, name="A / B", seed=1)
    team_b = Team(event_id=event.id, name="C / D", seed=2)
    session.add_all([team_a, team_b])
    session.flush()

    excess = next(s for s in slots if s.court_number == 15)
    match = Match(
        tournament_id=t.id,
        event_id=event.id,
        schedule_version_id=v.id,
        match_code="MX_WF_R1_M01",
        match_type="WF",
        round_number=1,
        round_index=1,
        sequence_in_round=1,
        duration_minutes=60,
        team_a_id=team_a.id,
        team_b_id=team_b.id,
        placeholder_side_a="Seed 1",
        placeholder_side_b="Seed 2",
    )
    session.add(match)
    session.flush()
    session.add(
        MatchAssignment(
            schedule_version_id=v.id,
            match_id=match.id,
            slot_id=excess.id,
        )
    )
    session.commit()

    resp = client.put(
        f"/api/tournaments/{t.id}",
        json={"court_names": _new_labels_5_to_18()},
    )
    assert resp.status_code == 400
    assert "assignment" in resp.json()["detail"].lower()

    session.refresh(t)
    assert t.court_names == _old_labels(15)


def test_save_court_names_leaves_final_version_slots_untouched(client: TestClient, session: Session):
    t, v, day, window, _slots = _seed_tournament(session, status="final", courts=15)
    new_names = _new_labels_5_to_18()

    resp = client.put(
        f"/api/tournaments/{t.id}",
        json={"court_names": new_names},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["court_names"] == new_names
    sync = body["court_sync"]
    assert sync is not None
    assert sync["relabeled_slots"] == 0
    assert sync["removed_slots"] == 0
    assert sync["capped_windows"] == 1
    assert sync["capped_days"] == 1

    slots = session.exec(select(ScheduleSlot).where(ScheduleSlot.schedule_version_id == v.id)).all()
    assert len(slots) == 15
    assert all(s.court_label == str(s.court_number) for s in slots)

    session.refresh(day)
    session.refresh(window)
    assert day.courts_available == 14
    assert window.courts_available == 14


def test_save_unchanged_court_names_is_noop(client: TestClient, session: Session):
    t, v, day, window, _slots = _seed_tournament(session, status="draft", courts=15)
    same = _old_labels(15)

    resp = client.put(
        f"/api/tournaments/{t.id}",
        json={"court_names": same},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body.get("court_sync") is None

    session.refresh(day)
    session.refresh(window)
    assert day.courts_available == 15
    assert window.courts_available == 15

    slots = session.exec(select(ScheduleSlot).where(ScheduleSlot.schedule_version_id == v.id)).all()
    assert len(slots) == 15
    assert all(s.court_label == str(s.court_number) for s in slots)


def test_cap_windows_reduces_extra_courts_first(client: TestClient, session: Session):
    t = Tournament(
        name="Extra Courts Cap",
        location="Test",
        timezone="America/New_York",
        start_date=date(2026, 10, 16),
        end_date=date(2026, 10, 16),
        use_time_windows=True,
        court_names=["1", "2", "3", "4", "5"],
    )
    session.add(t)
    session.flush()
    window = TournamentTimeWindow(
        tournament_id=t.id,
        day_date=date(2026, 10, 16),
        start_time=time(8, 0),
        end_time=time(10, 0),
        courts_available=3,
        extra_courts=3,
        block_minutes=60,
        is_active=True,
    )
    session.add(window)
    session.commit()

    resp = client.put(
        f"/api/tournaments/{t.id}",
        json={"court_names": ["A", "B", "C", "D"]},
    )
    assert resp.status_code == 200, resp.text
    sync = resp.json()["court_sync"]
    assert sync["capped_windows"] == 1

    session.refresh(window)
    assert window.courts_available == 3
    assert window.extra_courts == 1
