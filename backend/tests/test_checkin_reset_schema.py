"""Persist checkin_reset_pending without rewriting existing match data."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool
from sqlmodel import Session, SQLModel, select

from app.db_schema_patch import ensure_match_checkin_reset_column
from app.models.match import Match
from app.models.match_assignment import MatchAssignment
from app.models.match_checkin import MatchCheckIn
from app.models.tournament import Tournament
from app.services.checkin_reset import return_match_to_waiting_checkin
from app.services.preassigned_dispatch import OUTCOME_WAITING_CHECKIN, evaluate_eligibility, start_match_canonical
from tests.test_return_to_waiting_checkin import _prepare_later_round

BACKEND_ROOT = Path(__file__).resolve().parents[1]


def _file_engine(path: Path):
    return create_engine(
        f"sqlite:///{path.as_posix()}",
        connect_args={"check_same_thread": False},
        poolclass=NullPool,
    )


def _snapshot(conn) -> dict:
    match_rows = conn.execute(
        text(
            """
            SELECT id, runtime_status, score_json, winner_team_id, team_a_id, team_b_id,
                   source_match_a_id, source_match_b_id, started_at, completed_at
            FROM match
            ORDER BY id
            """
        )
    ).fetchall()
    assignments = conn.execute(
        text("SELECT id, match_id, slot_id FROM matchassignment ORDER BY id")
    ).fetchall()
    checkins = conn.execute(
        text(
            """
            SELECT id, match_id, team_id, side, team_checked_in
            FROM matchcheckin
            ORDER BY id
            """
        )
    ).fetchall()
    return {"matches": match_rows, "assignments": assignments, "checkins": checkins}


def test_startup_patch_adds_reset_flag_without_changing_existing_rows(tmp_path):
    import app.models  # noqa: F401

    path = tmp_path / "legacy.db"
    engine = _file_engine(path)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        ctx = _prepare_later_round(session)
        later = ctx["m_r2"]
        later.runtime_status = "FINAL"
        later.winner_team_id = later.team_a_id
        later.score_json = {"display": "6-4 6-3"}
        session.add(later)
        session.add(
            MatchCheckIn(
                tournament_id=ctx["tournament"].id,
                schedule_version_id=ctx["version"].id,
                match_id=later.id,
                team_id=later.team_a_id,
                side="A",
                team_checked_in=True,
            )
        )
        session.commit()
        match_id = later.id
        slot_id = session.exec(select(MatchAssignment).where(MatchAssignment.match_id == match_id)).one().slot_id

    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE match DROP COLUMN checkin_reset_pending"))
    engine.dispose()

    engine = _file_engine(path)
    with engine.connect() as conn:
        before = _snapshot(conn)
        columns = [row[1] for row in conn.execute(text("PRAGMA table_info(match)")).fetchall()]
    assert "checkin_reset_pending" not in columns

    ensure_match_checkin_reset_column(engine)
    ensure_match_checkin_reset_column(engine)

    with engine.connect() as conn:
        columns = [row[1] for row in conn.execute(text("PRAGMA table_info(match)")).fetchall()]
        after = _snapshot(conn)
        flags = conn.execute(text("SELECT id, checkin_reset_pending FROM match ORDER BY id")).fetchall()
    assert "checkin_reset_pending" in columns
    assert after == before
    assert flags
    assert all(flag in (0, False) for _match_id, flag in flags)

    with Session(engine) as session:
        match = session.get(Match, match_id)
        assert match.runtime_status == "FINAL"
        assert match.score_json["display"] == "6-4 6-3"
        assert match.winner_team_id == match.team_a_id
        assert match.checkin_reset_pending is False
        assignment = session.exec(select(MatchAssignment).where(MatchAssignment.match_id == match_id)).one()
        assert assignment.slot_id == slot_id
        checkin = session.exec(select(MatchCheckIn).where(MatchCheckIn.match_id == match_id)).one()
        assert checkin.team_checked_in is True
    engine.dispose()


def test_reset_flag_survives_restart_and_keeps_the_match_held(tmp_path):
    import app.models  # noqa: F401

    path = tmp_path / "restart.db"
    engine = _file_engine(path)
    SQLModel.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE match DROP COLUMN checkin_reset_pending"))
    ensure_match_checkin_reset_column(engine)

    with Session(engine) as session:
        ctx = _prepare_later_round(session)
        tournament_id = ctx["tournament"].id
        match_id = ctx["m_r2"].id
        court_number = ctx["slot_c"].court_number
        assert return_match_to_waiting_checkin(
            session,
            tournament=ctx["tournament"],
            version=ctx["version"],
            match=ctx["m_r2"],
        ) == "IN_PROGRESS"
        session.commit()
    engine.dispose()

    restarted = _file_engine(path)
    with Session(restarted) as session:
        match = session.get(Match, match_id)
        tournament = session.get(Tournament, tournament_id)
        assert match.checkin_reset_pending is True
        assert match.runtime_status == "SCHEDULED"
        eligibility = evaluate_eligibility(session, tournament, match)
        assert eligibility.outcome == OUTCOME_WAITING_CHECKIN
        started, _detail = start_match_canonical(session, tournament, match)
        assert started is False
        assert session.get(Match, match_id).runtime_status == "SCHEDULED"
        assert court_number == 1
    restarted.dispose()


def test_alembic_revision_adds_the_column_once(tmp_path):
    path = tmp_path / "alembic.db"
    engine = _file_engine(path)
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE match (
                    id INTEGER PRIMARY KEY,
                    runtime_status TEXT NOT NULL,
                    score_json TEXT,
                    winner_team_id INTEGER,
                    team_a_id INTEGER,
                    team_b_id INTEGER
                )
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO match (id, runtime_status, score_json, winner_team_id, team_a_id, team_b_id)
                VALUES (7, 'FINAL', '{"display":"6-4"}', 3, 3, 4)
                """
            )
        )
    engine.dispose()

    _run_alembic(path, "stamp", "026_add_team_photography")
    _run_alembic(path, "upgrade", "027_add_match_checkin_reset_pending")
    _run_alembic(path, "upgrade", "027_add_match_checkin_reset_pending")

    check = _file_engine(path)
    with check.connect() as conn:
        row = conn.execute(
            text(
                """
                SELECT runtime_status, score_json, winner_team_id, team_a_id, team_b_id, checkin_reset_pending
                FROM match WHERE id = 7
                """
            )
        ).one()
        version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
    check.dispose()
    assert row == ("FINAL", '{"display":"6-4"}', 3, 3, 4, 0)
    assert version == "027_add_match_checkin_reset_pending"


def _run_alembic(db_path: Path, action: str, revision: str) -> None:
    ini_path = (BACKEND_ROOT / "alembic.ini").as_posix()
    script_location = (BACKEND_ROOT / "alembic").as_posix()
    url = f"sqlite:///{db_path.as_posix()}"
    runner = (
        "from alembic import command\n"
        "from alembic.config import Config\n"
        f"config = Config({ini_path!r})\n"
        f"config.set_main_option('script_location', {script_location!r})\n"
        f"config.set_main_option('sqlalchemy.url', {url!r})\n"
        f"command.{action}(config, {revision!r})\n"
    )
    env = os.environ.copy()
    # backend/alembic is the migration folder. The library must win the import.
    env.pop("PYTHONPATH", None)
    completed = subprocess.run(
        [sys.executable, "-c", runner],
        cwd=str(db_path.parent),
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    if completed.returncode != 0:
        raise AssertionError(
            f"alembic {action} {revision} failed\nstdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
        )
