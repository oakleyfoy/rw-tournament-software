"""A text send must not keep the SQLite write lock while Twilio is called."""

from __future__ import annotations

import threading
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.pool import NullPool
from sqlmodel import Session, create_engine

from app.database import configure_sqlite_concurrency


def _file_engine(db_path: Path):
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False, "timeout": 1},
        poolclass=NullPool,
    )
    configure_sqlite_concurrency(engine, enabled=True)
    return engine


def _other_writer_blocked(db_path: Path) -> bool:
    blocked = {"value": False}

    def _try() -> None:
        engine = _file_engine(db_path)
        try:
            with Session(engine) as session:
                session.exec(text("select 1"))
                session.commit()
        except Exception:
            blocked["value"] = True
        finally:
            engine.dispose()

    thread = threading.Thread(target=_try)
    thread.start()
    thread.join(3)
    return blocked["value"] or thread.is_alive()


def test_commit_and_close_release_the_write_lock(tmp_path: Path):
    db_path = tmp_path / "desk.db"
    engine = _file_engine(db_path)
    with engine.connect() as conn:
        conn.exec_driver_sql("create table note(id integer)")
        conn.commit()

    session = Session(engine)
    session.exec(text("insert into note(id) values (1)"))
    assert _other_writer_blocked(db_path)

    session.commit()
    if session.in_transaction():
        session.rollback()
    session.close()

    assert _other_writer_blocked(db_path) is False

    check = Session(engine)
    count = check.exec(text("select count(*) from note")).one()
    assert count[0] == 1
    check.close()
    engine.dispose()


def test_open_write_still_serializes_other_writers(tmp_path: Path):
    db_path = tmp_path / "desk.db"
    engine = _file_engine(db_path)
    with engine.connect() as conn:
        conn.exec_driver_sql("create table note(id integer)")
        conn.commit()

    session = Session(engine)
    session.exec(text("insert into note(id) values (1)"))
    try:
        assert _other_writer_blocked(db_path)
    finally:
        session.rollback()
        session.close()
        engine.dispose()
