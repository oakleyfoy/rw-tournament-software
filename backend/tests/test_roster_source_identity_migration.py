"""Verify Alembic 021 upgrade/downgrade and startup-patch equivalence on SQLite."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from sqlalchemy import create_engine, text

from app.db_schema_patch import (
    REQUIRED_TEAM_COLUMNS,
    REQUIRED_TEMPORARY_PLAYER_LOOKUP_COLUMNS,
    ensure_team_columns,
    ensure_temporary_player_lookup_columns,
    ensure_tournament_import_columns,
)

PREVIOUS_REVISION = "020_add_import_forecast_json"
TARGET_REVISION = "021_add_roster_source_identity"
BACKEND_ROOT = Path(__file__).resolve().parents[1]


def _run_alembic(db_path: Path, action: str, revision: str) -> None:
    """Invoke the installed Alembic library, not backend/alembic/."""
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
    completed = subprocess.run(
        [sys.executable, "-c", runner],
        cwd=str(db_path.parent),
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise AssertionError(
            f"alembic {action} {revision} failed\nstdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
        )


def _create_revision_020_schema(engine) -> None:
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE event (id INTEGER PRIMARY KEY, name TEXT)"))
        conn.execute(
            text(
                """
                CREATE TABLE team (
                    id INTEGER PRIMARY KEY,
                    event_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    seed INTEGER,
                    UNIQUE (event_id, seed),
                    UNIQUE (event_id, name)
                )
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE temporary_player_lookup (
                    id INTEGER PRIMARY KEY,
                    tournament_id INTEGER NOT NULL,
                    source_name TEXT NOT NULL,
                    normalized_name TEXT NOT NULL,
                    towel_color TEXT NOT NULL
                )
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE tournament_import (
                    id INTEGER PRIMARY KEY,
                    source_hash TEXT NOT NULL,
                    forecast_json TEXT
                )
                """
            )
        )
        conn.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
        conn.execute(text("INSERT INTO alembic_version (version_num) VALUES (:rev)"), {"rev": PREVIOUS_REVISION})
        conn.execute(text("INSERT INTO team (event_id, name, seed) VALUES (1, 'Manual One', 1)"))
        conn.execute(text("INSERT INTO team (event_id, name, seed) VALUES (1, 'Manual Two', 2)"))
        conn.execute(
            text(
                "INSERT INTO temporary_player_lookup "
                "(tournament_id, source_name, normalized_name, towel_color) "
                "VALUES (1, 'Manual Player', 'manual player', 'Green')"
            )
        )
        conn.execute(text("INSERT INTO tournament_import (source_hash, forecast_json) VALUES ('abc', '{}')"))


def _index_sql(engine, table: str) -> dict[str, str]:
    with engine.connect() as conn:
        rows = conn.execute(text(f"PRAGMA index_list({table})")).fetchall()
        sql = {}
        for row in rows:
            name = row[1]
            create = conn.execute(
                text("SELECT sql FROM sqlite_master WHERE type='index' AND name=:name"),
                {"name": name},
            ).fetchone()
            sql[name] = (create[0] if create and create[0] else "") or ""
        return sql


def _columns(engine, table: str) -> dict[str, tuple[str, int]]:
    with engine.connect() as conn:
        rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
    return {str(row[1]): (str(row[2]), int(row[3])) for row in rows}


def test_alembic_021_upgrades_from_020_and_downgrades(tmp_path):
    db_path = tmp_path / "upgrade.db"
    engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    _create_revision_020_schema(engine)

    _run_alembic(db_path, "upgrade", TARGET_REVISION)

    with engine.connect() as conn:
        version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    assert version == TARGET_REVISION

    team_cols = _columns(engine, "team")
    assert "source_team_key" in team_cols
    assert team_cols["source_team_key"][1] == 0

    lookup_cols = _columns(engine, "temporary_player_lookup")
    for name in ("source", "source_team_key", "lineup_slot"):
        assert name in lookup_cols
        assert lookup_cols[name][1] == 0

    import_cols = _columns(engine, "tournament_import")
    assert "approved_source_hash" in import_cols
    assert import_cols["approved_source_hash"][1] == 0

    team_indexes = _index_sql(engine, "team")
    assert "uq_event_source_team_key" in team_indexes
    lookup_indexes = _index_sql(engine, "temporary_player_lookup")
    assert "uq_rwos_lookup_source_identity" in lookup_indexes
    assert "source IS NOT NULL" in lookup_indexes["uq_rwos_lookup_source_identity"]

    with engine.connect() as conn:
        unique_sql = [
            row[0]
            for row in conn.execute(text("SELECT sql FROM sqlite_master WHERE type='table' AND name='team'")).fetchall()
        ]
    assert any("event_id" in (sql or "") and "seed" in (sql or "") for sql in unique_sql)
    assert any("name" in (sql or "") for sql in unique_sql)

    with engine.connect() as conn:
        team_count = conn.execute(text("SELECT COUNT(*) FROM team")).scalar_one()
        null_keys = conn.execute(text("SELECT COUNT(*) FROM team WHERE source_team_key IS NULL")).scalar_one()
        lookup_null = conn.execute(
            text("SELECT COUNT(*) FROM temporary_player_lookup WHERE source IS NULL")
        ).scalar_one()
        import_null = conn.execute(
            text("SELECT COUNT(*) FROM tournament_import WHERE approved_source_hash IS NULL")
        ).scalar_one()
    assert team_count == 2
    assert null_keys == 2
    assert lookup_null == 1
    assert import_null == 1

    _run_alembic(db_path, "downgrade", PREVIOUS_REVISION)
    with engine.connect() as conn:
        version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    assert version == PREVIOUS_REVISION
    assert "source_team_key" not in _columns(engine, "team")
    assert "source" not in _columns(engine, "temporary_player_lookup")
    assert "approved_source_hash" not in _columns(engine, "tournament_import")
    assert "uq_event_source_team_key" not in _index_sql(engine, "team")
    assert "uq_rwos_lookup_source_identity" not in _index_sql(engine, "temporary_player_lookup")


def test_db_schema_patch_matches_021_indexes(tmp_path):
    db_path = tmp_path / "patch.db"
    engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    _create_revision_020_schema(engine)
    ensure_team_columns(engine)
    ensure_temporary_player_lookup_columns(engine)
    ensure_tournament_import_columns(engine)

    assert "source_team_key" in {name for name, _sqlite, _pg in REQUIRED_TEAM_COLUMNS}
    assert {name for name, _a, _b in REQUIRED_TEMPORARY_PLAYER_LOOKUP_COLUMNS} >= {
        "source",
        "source_team_key",
        "lineup_slot",
    }
    assert "source_team_key" in _columns(engine, "team")
    lookup_cols = _columns(engine, "temporary_player_lookup")
    assert {"source", "source_team_key", "lineup_slot"} <= set(lookup_cols)
    assert "approved_source_hash" in _columns(engine, "tournament_import")

    team_indexes = _index_sql(engine, "team")
    lookup_indexes = _index_sql(engine, "temporary_player_lookup")
    assert "uq_event_source_team_key" in team_indexes
    assert "uq_rwos_lookup_source_identity" in lookup_indexes
    assert "source IS NOT NULL" in lookup_indexes["uq_rwos_lookup_source_identity"]
    assert "UNIQUE" in lookup_indexes["uq_rwos_lookup_source_identity"].upper()
