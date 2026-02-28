from __future__ import annotations

from typing import Dict, List, Tuple

from sqlalchemy import text
from sqlalchemy.engine import Engine

# Columns we must ensure exist in the "event" table.
# (name, sqlite_type, postgres_type)
REQUIRED_EVENT_COLUMNS: List[Tuple[str, str, str]] = [
    ("draw_plan_json", "TEXT", "TEXT"),
    ("draw_plan_version", "TEXT", "TEXT"),
    ("draw_status", "TEXT", "TEXT"),
    ("wf_block_minutes", "INTEGER", "INTEGER"),
    ("standard_block_minutes", "INTEGER", "INTEGER"),
    ("guarantee_selected", "INTEGER", "INTEGER"),
    ("schedule_profile_json", "TEXT", "TEXT"),
]

# Columns we must ensure exist in the "tournament" table.
REQUIRED_TOURNAMENT_COLUMNS: List[Tuple[str, str, str]] = [
    ("use_time_windows", "INTEGER", "BOOLEAN"),
    ("public_schedule_version_id", "INTEGER", "INTEGER"),
]

# Columns we must ensure exist in the "team" table.
REQUIRED_TEAM_COLUMNS: List[Tuple[str, str, str]] = [
    ("avoid_group", "VARCHAR(4)", "VARCHAR(4)"),
    ("display_name", "TEXT", "TEXT"),
    ("player1_cellphone", "TEXT", "TEXT"),
    ("player1_email", "TEXT", "TEXT"),
    ("player2_cellphone", "TEXT", "TEXT"),
    ("player2_email", "TEXT", "TEXT"),
    ("is_defaulted", "INTEGER", "BOOLEAN"),
    ("notes", "TEXT", "TEXT"),
    ("p1_cell", "TEXT", "TEXT"),
    ("p1_email", "TEXT", "TEXT"),
    ("p2_cell", "TEXT", "TEXT"),
    ("p2_email", "TEXT", "TEXT"),
]


def _is_sqlite(engine: Engine) -> bool:
    return engine.dialect.name.lower() == "sqlite"


def _get_existing_columns_sqlite(engine: Engine, table_name: str) -> Dict[str, str]:
    cols: Dict[str, str] = {}
    with engine.connect() as conn:
        res = conn.execute(text(f"PRAGMA table_info({table_name});")).fetchall()
        # PRAGMA table_info returns rows: (cid, name, type, notnull, dflt_value, pk)
        for row in res:
            cols[str(row[1])] = str(row[2])
    return cols


def _get_existing_columns_postgres(engine: Engine, table_name: str) -> Dict[str, str]:
    cols: Dict[str, str] = {}
    sql = """
    SELECT column_name, data_type
    FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = :table_name;
    """
    with engine.connect() as conn:
        res = conn.execute(text(sql), {"table_name": table_name}).fetchall()
        for row in res:
            cols[str(row[0])] = str(row[1])
    return cols


def ensure_event_columns(engine: Engine) -> None:
    """
    Idempotently adds required columns to the 'event' table if missing.
    Safe to run at every startup.
    Uses the actual table name from the Event model.
    """
    try:
        # Get the actual table name from the Event model
        from app.models.event import Event

        table = Event.__table__.name

        # Check if table exists first
        if _is_sqlite(engine):
            # For SQLite, check if table exists
            with engine.connect() as conn:
                result = conn.execute(
                    text("SELECT name FROM sqlite_master WHERE type='table' AND name=:table_name"),
                    {"table_name": table},
                ).fetchone()
                if not result:
                    # Table doesn't exist yet, skip (create_all should create it)
                    return

            existing = _get_existing_columns_sqlite(engine, table)
            with engine.begin() as conn:
                for name, sqlite_type, _pg_type in REQUIRED_EVENT_COLUMNS:
                    if name in existing:
                        continue
                    # SQLite supports ADD COLUMN without IF NOT EXISTS
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {sqlite_type};"))
        else:
            # For Postgres, check if table exists
            with engine.connect() as conn:
                result = conn.execute(
                    text("""
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables
                        WHERE table_schema = 'public' AND table_name = :table_name
                    )
                """),
                    {"table_name": table},
                ).fetchone()
                if not result or not result[0]:
                    # Table doesn't exist yet, skip
                    return

            existing = _get_existing_columns_postgres(engine, table)
            with engine.begin() as conn:
                for name, _sqlite_type, pg_type in REQUIRED_EVENT_COLUMNS:
                    if name in existing:
                        continue
                    # Postgres supports IF NOT EXISTS
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {name} {pg_type};"))
    except Exception as e:
        # Log error but don't crash the server
        import logging

        logger = logging.getLogger(__name__)
        logger.warning(f"Failed to ensure event columns (this is OK if table doesn't exist yet): {e}")


def ensure_tournament_columns(engine: Engine) -> None:
    """
    Idempotently adds required columns to the 'tournament' table if missing.
    Safe to run at every startup.
    """
    try:
        from app.models.tournament import Tournament

        table = Tournament.__table__.name

        # Check if table exists first
        if _is_sqlite(engine):
            with engine.connect() as conn:
                result = conn.execute(
                    text("SELECT name FROM sqlite_master WHERE type='table' AND name=:table_name"),
                    {"table_name": table},
                ).fetchone()
                if not result:
                    return

            existing = _get_existing_columns_sqlite(engine, table)
            with engine.begin() as conn:
                for name, sqlite_type, _pg_type in REQUIRED_TOURNAMENT_COLUMNS:
                    if name in existing:
                        continue
                    default = "DEFAULT NULL" if name == "public_schedule_version_id" else "DEFAULT 0"
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {sqlite_type} {default};"))
        else:
            with engine.connect() as conn:
                result = conn.execute(
                    text("""
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables
                        WHERE table_schema = 'public' AND table_name = :table_name
                    )
                """),
                    {"table_name": table},
                ).fetchone()
                if not result or not result[0]:
                    return

            existing = _get_existing_columns_postgres(engine, table)
            with engine.begin() as conn:
                for name, _sqlite_type, pg_type in REQUIRED_TOURNAMENT_COLUMNS:
                    if name in existing:
                        continue
                    default = "DEFAULT NULL" if name == "public_schedule_version_id" else "DEFAULT FALSE"
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {name} {pg_type} {default};"))
    except Exception as e:
        import logging

        logger = logging.getLogger(__name__)
        logger.warning(f"Failed to ensure tournament columns (this is OK if table doesn't exist yet): {e}")


def ensure_team_columns(engine: Engine) -> None:
    """
    Idempotently adds required columns to the 'team' table if missing.
    Safe to run at every startup.
    """
    try:
        from app.models.team import Team

        table = Team.__table__.name

        if _is_sqlite(engine):
            with engine.connect() as conn:
                result = conn.execute(
                    text("SELECT name FROM sqlite_master WHERE type='table' AND name=:table_name"),
                    {"table_name": table},
                ).fetchone()
                if not result:
                    return

            existing = _get_existing_columns_sqlite(engine, table)
            with engine.begin() as conn:
                for name, sqlite_type, _pg_type in REQUIRED_TEAM_COLUMNS:
                    if name in existing:
                        continue
                    default = " DEFAULT 0" if name == "is_defaulted" else ""
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {sqlite_type}{default};"))
        else:
            with engine.connect() as conn:
                result = conn.execute(
                    text("""
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables
                        WHERE table_schema = 'public' AND table_name = :table_name
                    )
                """),
                    {"table_name": table},
                ).fetchone()
                if not result or not result[0]:
                    return

            existing = _get_existing_columns_postgres(engine, table)
            with engine.begin() as conn:
                for name, _sqlite_type, pg_type in REQUIRED_TEAM_COLUMNS:
                    if name in existing:
                        continue
                    default = " DEFAULT FALSE" if name == "is_defaulted" else ""
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {name} {pg_type}{default};"))
    except Exception as e:
        import logging

        logger = logging.getLogger(__name__)
        logger.warning(f"Failed to ensure team columns (this is OK if table doesn't exist yet): {e}")
