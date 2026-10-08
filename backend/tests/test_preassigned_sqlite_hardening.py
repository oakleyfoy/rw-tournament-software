"""SQLite hardening for PREASSIGNED court automation (constraints + concurrency)."""

from __future__ import annotations

import threading
import time
from datetime import date, datetime
from datetime import time as time_of_day
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import event, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.pool import NullPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.db_schema_patch import (
    UQ_COURT_DISPATCH_LOCK,
    UQ_OPENING_SLOT_RELEASE,
    ensure_court_dispatch_lock_table,
    ensure_opening_slot_release_table,
    inspect_preassigned_automation_schema,
    invalidate_preassigned_schema_ready_cache,
    is_preassigned_automation_schema_ready,
)
from app.models.court_dispatch_lock import CourtDispatchLock
from app.models.event import Event
from app.models.match import Match
from app.models.match_assignment import MatchAssignment
from app.models.match_checkin import MatchCheckIn
from app.models.opening_slot_release import OpeningSlotRelease
from app.models.schedule_slot import ScheduleSlot
from app.models.schedule_version import ScheduleVersion
from app.models.team import Team
from app.models.tournament import Tournament
from app.models.tournament_day import TournamentDay
from app.services.court_assignment_mode import MODE_PREASSIGNED, replace_court_assignment_modes
from app.services.preassigned_dispatch import (
    COURT_LOCK_BUSY,
    SCHEMA_NOT_READY,
    dispatch_after_finalize,
    dispatch_court,
    start_match_canonical,
)
from app.services.schedule_slot_availability import slot_key_for_slot


def _file_sqlite_engine(db_path: Path):
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False, "timeout": 30},
        poolclass=NullPool,
    )

    @event.listens_for(engine, "begin")
    def _begin_immediate(conn) -> None:  # type: ignore[no-untyped-def]
        conn.exec_driver_sql("BEGIN IMMEDIATE")

    return engine


def _team(session: Session, event_id: int, name: str, seed: int) -> Team:
    team = Team(event_id=event_id, name=name, seed=seed, display_name=name)
    session.add(team)
    session.flush()
    return team


def _check_in(session: Session, tournament_id: int, version_id: int, match: Match) -> None:
    for side, team_id in (("A", match.team_a_id), ("B", match.team_b_id)):
        session.add(
            MatchCheckIn(
                tournament_id=tournament_id,
                schedule_version_id=version_id,
                match_id=match.id,
                team_id=team_id,
                side=side,
                team_checked_in=True,
                checked_in_at=datetime.utcnow(),
            )
        )
    session.flush()


def _seed_two_court12_matches(session: Session):
    day = date(2026, 11, 7)
    t = Tournament(
        name="SQLite Hardening",
        location="Test",
        timezone="America/New_York",
        start_date=day,
        end_date=day,
        desk_management_mode="checkin_management",
        court_names=["12"],
    )
    session.add(t)
    session.flush()
    session.add(TournamentDay(tournament_id=t.id, date=day, is_active=True, courts_available=1))
    v = ScheduleVersion(tournament_id=t.id, version_number=1, status="draft", notes="Desk Draft")
    session.add(v)
    session.flush()
    ev = Event(tournament_id=t.id, category="womens", name="Women's A", team_count=8)
    session.add(ev)
    session.flush()
    replace_court_assignment_modes(ev, {day.isoformat(): MODE_PREASSIGNED})
    session.add(ev)
    teams = [_team(session, ev.id, f"T{i}", i) for i in range(1, 5)]
    s1 = ScheduleSlot(
        tournament_id=t.id,
        schedule_version_id=v.id,
        day_date=day,
        start_time=time_of_day(9, 0),
        end_time=time_of_day(10, 0),
        court_number=12,
        court_label="12",
        block_minutes=60,
    )
    s2 = ScheduleSlot(
        tournament_id=t.id,
        schedule_version_id=v.id,
        day_date=day,
        start_time=time_of_day(10, 0),
        end_time=time_of_day(11, 0),
        court_number=12,
        court_label="12",
        block_minutes=60,
    )
    session.add(s1)
    session.add(s2)
    session.flush()
    m1 = Match(
        tournament_id=t.id,
        event_id=ev.id,
        schedule_version_id=v.id,
        match_code="R1-earlier",
        match_type="WF",
        round_number=1,
        round_index=1,
        sequence_in_round=1,
        duration_minutes=60,
        team_a_id=teams[0].id,
        team_b_id=teams[1].id,
        placeholder_side_a="A",
        placeholder_side_b="B",
        runtime_status="SCHEDULED",
    )
    m2 = Match(
        tournament_id=t.id,
        event_id=ev.id,
        schedule_version_id=v.id,
        match_code="R1-later",
        match_type="WF",
        round_number=1,
        round_index=1,
        sequence_in_round=2,
        duration_minutes=60,
        team_a_id=teams[2].id,
        team_b_id=teams[3].id,
        placeholder_side_a="A",
        placeholder_side_b="B",
        runtime_status="SCHEDULED",
    )
    session.add(m1)
    session.add(m2)
    session.flush()
    session.add(MatchAssignment(schedule_version_id=v.id, match_id=m1.id, slot_id=s1.id))
    session.add(MatchAssignment(schedule_version_id=v.id, match_id=m2.id, slot_id=s2.id))
    _check_in(session, t.id, v.id, m1)
    _check_in(session, t.id, v.id, m2)
    session.add(
        OpeningSlotRelease(
            tournament_id=t.id,
            schedule_version_id=v.id,
            day_date=day,
            slot_key=slot_key_for_slot(s1),
            released_at=datetime.utcnow(),
        )
    )
    session.add(
        OpeningSlotRelease(
            tournament_id=t.id,
            schedule_version_id=v.id,
            day_date=day,
            slot_key=slot_key_for_slot(s2),
            released_at=datetime.utcnow(),
        )
    )
    session.commit()
    return t, v, day, m1, m2


def test_unique_constraints_reject_duplicate_rows(session: Session):
    """Prove SQLite enforces the named unique indexes (not only ORM declarations)."""
    engine = session.get_bind()
    ensure_opening_slot_release_table(engine)
    ensure_court_dispatch_lock_table(engine)
    status = inspect_preassigned_automation_schema(engine)
    assert status["ready"] is True
    assert status["uq_opening_slot_release_version_day_slot"] is True
    assert status["uq_court_dispatch_lock_version_day_court"] is True

    day = date(2026, 11, 7)
    t, v, _ev, _ = _seed_minimal_tournament(session, day)

    session.add(
        OpeningSlotRelease(
            tournament_id=t.id,
            schedule_version_id=v.id,
            day_date=day,
            slot_key="2026-11-07|09:00",
            released_at=datetime.utcnow(),
        )
    )
    session.commit()
    session.add(
        OpeningSlotRelease(
            tournament_id=t.id,
            schedule_version_id=v.id,
            day_date=day,
            slot_key="2026-11-07|09:00",
            released_at=datetime.utcnow(),
        )
    )
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()

    session.add(
        CourtDispatchLock(
            schedule_version_id=v.id,
            day_date=day,
            court_number=12,
            holder="a",
            created_at=datetime.utcnow(),
        )
    )
    session.commit()
    session.add(
        CourtDispatchLock(
            schedule_version_id=v.id,
            day_date=day,
            court_number=12,
            holder="b",
            created_at=datetime.utcnow(),
        )
    )
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()

    # Raw SQL path also rejects duplicates (bypassing ORM uniqueness assumptions).
    with engine.begin() as conn:
        with pytest.raises(Exception):
            conn.execute(
                text(
                    """
                    INSERT INTO openingslotrelease
                    (tournament_id, schedule_version_id, day_date, slot_key, released_at)
                    VALUES (:t, :v, :d, :sk, :ra)
                    """
                ),
                {
                    "t": t.id,
                    "v": v.id,
                    "d": day.isoformat(),
                    "sk": "2026-11-07|09:00",
                    "ra": datetime.utcnow().isoformat(),
                },
            )


def _seed_minimal_tournament(session: Session, day: date):
    t = Tournament(
        name="Constraint Probe",
        location="Test",
        timezone="America/New_York",
        start_date=day,
        end_date=day,
        desk_management_mode="checkin_management",
        court_names=["12"],
    )
    session.add(t)
    session.flush()
    v = ScheduleVersion(tournament_id=t.id, version_number=1, status="draft")
    session.add(v)
    session.flush()
    ev = Event(tournament_id=t.id, category="womens", name="E", team_count=4)
    session.add(ev)
    session.flush()
    session.commit()
    return t, v, ev, day


def test_readiness_endpoint_reports_schema(client, session: Session):
    ensure_opening_slot_release_table(session.get_bind())
    ensure_court_dispatch_lock_table(session.get_bind())
    resp = client.get("/api/desk/preassigned-automation/readiness")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ready"] is True
    assert body["dialect"] == "sqlite"
    assert body["opening_slot_release_table"] is True
    assert body["court_dispatch_lock_table"] is True
    assert body["uq_opening_slot_release_version_day_slot"] is True
    assert body["uq_court_dispatch_lock_version_day_court"] is True
    assert body["errors"] == []


def test_schema_not_ready_blocks_dispatch(session: Session):
    t, v, day, m1, _m2 = _seed_two_court12_matches(session)
    engine = session.get_bind()
    try:
        with engine.begin() as conn:
            conn.execute(text(f"DROP INDEX IF EXISTS {UQ_COURT_DISPATCH_LOCK}"))
            conn.execute(text("DROP TABLE IF EXISTS courtdispatchlock"))
        invalidate_preassigned_schema_ready_cache()
        assert is_preassigned_automation_schema_ready(engine, use_cache=False) is False
        with patch("app.services.preassigned_dispatch.slot_start_has_arrived", return_value=True):
            result = dispatch_court(session, t, version_id=v.id, day_date=day, court_number=12)
            ok, detail = start_match_canonical(session, t, session.get(Match, m1.id))
        assert SCHEMA_NOT_READY in result.errors
        assert ok is False
        assert detail == SCHEMA_NOT_READY
        assert session.get(Match, m1.id).runtime_status == "SCHEDULED"
    finally:
        # Restore shared in-memory schema for later tests in this process.
        ensure_opening_slot_release_table(engine)
        ensure_court_dispatch_lock_table(engine)
        invalidate_preassigned_schema_ready_cache()
        inspect_preassigned_automation_schema(engine)


def test_finalize_dispatch_busy_keeps_final_score(session: Session):
    t, v, day, m1, m2 = _seed_two_court12_matches(session)
    m1.runtime_status = "IN_PROGRESS"
    session.add(m1)
    session.commit()

    m1.runtime_status = "FINAL"
    m1.winner_team_id = m1.team_a_id
    m1.score_json = {"display": "8-2"}
    m1.completed_at = datetime.utcnow()
    session.add(m1)
    session.commit()

    with patch("app.services.preassigned_dispatch._try_acquire_court_lock", return_value=False):
        with patch("app.services.preassigned_dispatch._DISPATCH_BUSY_ATTEMPTS", 2):
            with patch("app.services.preassigned_dispatch._LOCK_ACQUIRE_ATTEMPTS", 2):
                with patch("app.services.preassigned_dispatch._DISPATCH_BUSY_SLEEP_SEC", 0.001):
                    with patch("app.services.preassigned_dispatch._LOCK_ACQUIRE_SLEEP_SEC", 0.001):
                        with patch(
                            "app.services.preassigned_dispatch.slot_start_has_arrived",
                            return_value=True,
                        ):
                            result = dispatch_after_finalize(session, t, m1, downstream_match_ids=[m2.id])

    assert COURT_LOCK_BUSY in result.errors or any(COURT_LOCK_BUSY in e for e in result.errors)
    assert result.started_match_ids == []
    session.expire_all()
    assert session.get(Match, m1.id).runtime_status == "FINAL"
    assert session.get(Match, m1.id).score_json["display"] == "8-2"
    assert session.get(Match, m2.id).runtime_status == "SCHEDULED"

    # Retry after contention clears can start the next eligible match.
    with patch("app.services.preassigned_dispatch.slot_start_has_arrived", return_value=True):
        retry = dispatch_court(session, t, version_id=v.id, day_date=day, court_number=12)
    assert m2.id in retry.started_match_ids
    assert session.get(Match, m2.id).runtime_status == "IN_PROGRESS"


def _run_file_backed_concurrent_dispatch(db_path: Path, runs: int = 5) -> None:
    for run_idx in range(runs):
        if db_path.exists():
            db_path.unlink()
        engine = _file_sqlite_engine(db_path)
        import app.models  # noqa: F401

        SQLModel.metadata.create_all(engine)
        ensure_opening_slot_release_table(engine)
        ensure_court_dispatch_lock_table(engine)
        inspect_preassigned_automation_schema(engine)

        with Session(engine) as session:
            t, v, day, m1, m2 = _seed_two_court12_matches(session)
            tid, vid, day_val, mid1, mid2 = t.id, v.id, day, m1.id, m2.id

        start_gate = threading.Event()
        outcomes: list[tuple[str, list[int], list[str]]] = []
        errors: list[str] = []

        def worker(label: str) -> None:
            try:
                if not start_gate.wait(timeout=10):
                    raise TimeoutError("start gate timeout")
                with Session(engine) as worker_session:
                    tournament = worker_session.get(Tournament, tid)
                    assert tournament is not None
                    with patch(
                        "app.services.preassigned_dispatch.slot_start_has_arrived",
                        return_value=True,
                    ):
                        with patch("app.services.preassigned_dispatch._send_start_sms"):
                            result = dispatch_court(
                                worker_session,
                                tournament,
                                version_id=vid,
                                day_date=day_val,
                                court_number=12,
                            )
                    outcomes.append((label, list(result.started_match_ids), list(result.errors)))
            except Exception as exc:  # pragma: no cover
                errors.append(f"{label}:{exc}")

        threads = [
            threading.Thread(target=worker, args=("a",), name=f"dispatch-a-{run_idx}"),
            threading.Thread(target=worker, args=("b",), name=f"dispatch-b-{run_idx}"),
        ]
        for th in threads:
            th.start()
        time.sleep(0.05)
        start_gate.set()
        for th in threads:
            th.join(timeout=45)
            assert not th.is_alive(), f"thread hung on run {run_idx} errors={errors} outcomes={outcomes}"

        assert errors == [], errors
        with Session(engine) as verify:
            statuses = {
                mid1: (verify.get(Match, mid1).runtime_status or "").upper(),
                mid2: (verify.get(Match, mid2).runtime_status or "").upper(),
            }
            in_progress = [mid for mid, st in statuses.items() if st == "IN_PROGRESS"]
            assert len(in_progress) == 1, f"run={run_idx} statuses={statuses} outcomes={outcomes}"
            assert in_progress[0] == mid1, f"later match jumped ahead run={run_idx} statuses={statuses}"
            assert statuses[mid2] == "SCHEDULED"
            locks = verify.exec(select(CourtDispatchLock)).all()
            assert locks == [], f"stuck locks on run {run_idx}: {locks}"
            started_union = {mid for _label, started, _errs in outcomes for mid in started}
            assert started_union == {mid1}
            # Loser reports busy/waiting/empty start — never an unhandled DB lock crash.
            assert all("database is locked" not in e.lower() for _l, _s, errs in outcomes for e in errs)

        engine.dispose()


def test_file_backed_sqlite_cross_connection_dispatch(tmp_path: Path):
    _run_file_backed_concurrent_dispatch(tmp_path / "preassigned_dispatch.db", runs=5)


def test_file_backed_later_start_cannot_jump_earlier(tmp_path: Path):
    """Even if the later match's request acquires the write path first, prior wins."""
    db_path = tmp_path / "priority.db"
    engine = _file_sqlite_engine(db_path)
    import app.models  # noqa: F401

    SQLModel.metadata.create_all(engine)
    ensure_opening_slot_release_table(engine)
    ensure_court_dispatch_lock_table(engine)
    inspect_preassigned_automation_schema(engine)
    with Session(engine) as session:
        t, v, day, m1, m2 = _seed_two_court12_matches(session)
        tid, mid1, mid2 = t.id, m1.id, m2.id

    start_gate = threading.Event()
    results: list[tuple[int, bool, str]] = []
    errors: list[str] = []

    def worker(match_id: int) -> None:
        try:
            if not start_gate.wait(timeout=10):
                raise TimeoutError("start gate timeout")
            with Session(engine) as worker_session:
                tournament = worker_session.get(Tournament, tid)
                match = worker_session.get(Match, match_id)
                with patch("app.services.preassigned_dispatch.slot_start_has_arrived", return_value=True):
                    with patch("app.services.preassigned_dispatch._send_start_sms"):
                        ok, detail = start_match_canonical(worker_session, tournament, match)
                results.append((match_id, ok, detail))
        except Exception as exc:  # pragma: no cover
            errors.append(f"{match_id}:{exc}")

    # Start later match thread first to bias the race, then earlier.
    t_later = threading.Thread(target=worker, args=(mid2,), name="later")
    t_earlier = threading.Thread(target=worker, args=(mid1,), name="earlier")
    t_later.start()
    t_earlier.start()
    time.sleep(0.05)
    start_gate.set()
    t_later.join(timeout=45)
    t_earlier.join(timeout=45)
    assert errors == [], errors

    with Session(engine) as verify:
        assert (verify.get(Match, mid1).runtime_status or "").upper() == "IN_PROGRESS"
        assert (verify.get(Match, mid2).runtime_status or "").upper() == "SCHEDULED"
        assert verify.exec(select(CourtDispatchLock)).all() == []
    started = [mid for mid, ok, _ in results if ok]
    assert started == [mid1] or set(started) == {mid1}
    engine.dispose()


def test_ensure_functions_create_named_unique_indexes(tmp_path: Path):
    db_path = tmp_path / "ensure.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False, "timeout": 5})
    # Create empty DB without metadata, then ensure_* must create tables+indexes.
    ensure_opening_slot_release_table(engine)
    ensure_court_dispatch_lock_table(engine)
    status = inspect_preassigned_automation_schema(engine)
    assert status["ready"] is True
    with engine.connect() as conn:
        opening_indexes = conn.execute(text("PRAGMA index_list('openingslotrelease')")).fetchall()
        lock_indexes = conn.execute(text("PRAGMA index_list('courtdispatchlock')")).fetchall()
    opening_names = {str(r[1]) for r in opening_indexes}
    lock_names = {str(r[1]) for r in lock_indexes}
    assert UQ_OPENING_SLOT_RELEASE in opening_names
    assert UQ_COURT_DISPATCH_LOCK in lock_names
    engine.dispose()
