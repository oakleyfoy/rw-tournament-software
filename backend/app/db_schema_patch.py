from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

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
    ("court_assignment_by_date_json", "TEXT", "TEXT"),
]

# Columns we must ensure exist in the "tournament" table.
REQUIRED_TOURNAMENT_COLUMNS: List[Tuple[str, str, str]] = [
    ("use_time_windows", "INTEGER", "BOOLEAN"),
    ("public_schedule_version_id", "INTEGER", "INTEGER"),
    ("is_archived", "INTEGER", "BOOLEAN"),
    ("desk_management_mode", "TEXT", "TEXT"),
    ("shared_screen_config_json", "TEXT", "TEXT"),
    ("event_schedule_day_orders_json", "TEXT", "TEXT"),
    ("source_rw_os_tournament_id", "INTEGER", "INTEGER"),
    ("source_rw_os_organization_slug", "TEXT", "TEXT"),
]

REQUIRED_TOURNAMENT_TIME_WINDOW_COLUMNS: List[Tuple[str, str, str]] = [
    ("extra_courts", "INTEGER", "INTEGER"),
]

REQUIRED_SCHEDULE_SLOT_COLUMNS: List[Tuple[str, str, str]] = [
    ("is_manual_only", "INTEGER", "BOOLEAN"),
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
    ("source_team_key", "TEXT", "TEXT"),
]

# Columns we must ensure exist in the "sms_log" table.
REQUIRED_SMS_LOG_COLUMNS: List[Tuple[str, str, str]] = [
    ("dedupe_key", "TEXT", "TEXT"),
    ("intended_phone_number", "TEXT", "TEXT"),
]

# Columns we must ensure exist in the "tournament_sms_settings" table.
REQUIRED_TOURNAMENT_SMS_SETTINGS_COLUMNS: List[Tuple[str, str, str]] = [
    ("texts_enabled", "INTEGER", "BOOLEAN"),
    ("test_mode", "INTEGER", "BOOLEAN"),
    ("test_allowlist", "TEXT", "TEXT"),
    ("delivery_mode", "TEXT", "TEXT"),
    ("redirect_phone", "TEXT", "TEXT"),
    ("player_contacts_only", "INTEGER", "BOOLEAN"),
    ("auto_checkin_first_match", "INTEGER", "BOOLEAN"),
    ("auto_checkin_slot_checkin", "INTEGER", "BOOLEAN"),
    ("auto_checkin_post_match_next", "INTEGER", "BOOLEAN"),
    ("auto_checkin_court_assigned", "INTEGER", "BOOLEAN"),
]

REQUIRED_SMS_PHONE_LIST_COLUMNS: List[Tuple[str, str, str]] = [
    ("created_at", "TIMESTAMP", "TIMESTAMP"),
    ("updated_at", "TIMESTAMP", "TIMESTAMP"),
]

REQUIRED_SMS_PHONE_LIST_MEMBER_COLUMNS: List[Tuple[str, str, str]] = [
    ("raw_name", "TEXT", "TEXT"),
    ("phone_number", "TEXT", "TEXT"),
    ("created_at", "TIMESTAMP", "TIMESTAMP"),
]

# Columns we must ensure exist in the "temporary_player_lookup" table.
REQUIRED_TEMPORARY_PLAYER_LOOKUP_COLUMNS: List[Tuple[str, str, str]] = [
    ("player_id", "INTEGER", "INTEGER"),
    ("source_name", "TEXT", "TEXT"),
    ("normalized_name", "TEXT", "TEXT"),
    ("source_phone", "TEXT", "TEXT"),
    ("normalized_phone", "TEXT", "TEXT"),
    ("source_email", "TEXT", "TEXT"),
    ("normalized_email", "TEXT", "TEXT"),
    ("towel_color", "TEXT", "TEXT"),
    ("report_url", "TEXT", "TEXT"),
    ("source", "TEXT", "TEXT"),
    ("source_team_key", "TEXT", "TEXT"),
    ("lineup_slot", "INTEGER", "INTEGER"),
    ("created_at", "TIMESTAMP", "TIMESTAMP"),
    ("updated_at", "TIMESTAMP", "TIMESTAMP"),
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
                    if name == "public_schedule_version_id":
                        default = "DEFAULT NULL"
                    elif name == "desk_management_mode":
                        default = "DEFAULT 'checkin_management'"
                    elif name in (
                        "shared_screen_config_json",
                        "event_schedule_day_orders_json",
                        "source_rw_os_tournament_id",
                        "source_rw_os_organization_slug",
                    ):
                        default = "DEFAULT NULL"
                    else:
                        default = "DEFAULT 0"
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
                    if name == "public_schedule_version_id":
                        default = "DEFAULT NULL"
                    elif name == "desk_management_mode":
                        default = "DEFAULT 'checkin_management'"
                    elif name in (
                        "shared_screen_config_json",
                        "event_schedule_day_orders_json",
                        "source_rw_os_tournament_id",
                        "source_rw_os_organization_slug",
                    ):
                        default = "DEFAULT NULL"
                    else:
                        default = "DEFAULT FALSE"
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
        _ensure_team_source_key_unique(engine)
    except Exception as e:
        import logging

        logger = logging.getLogger(__name__)
        logger.warning(f"Failed to ensure team columns (this is OK if table doesn't exist yet): {e}")


def _ensure_team_source_key_unique(engine: Engine) -> None:
    """UNIQUE (event_id, source_team_key) — multiple NULLs remain allowed."""
    if _is_sqlite(engine):
        with engine.begin() as conn:
            conn.execute(
                text("CREATE UNIQUE INDEX IF NOT EXISTS uq_event_source_team_key ON team (event_id, source_team_key)")
            )
        return
    with engine.begin() as conn:
        conn.execute(
            text("CREATE UNIQUE INDEX IF NOT EXISTS uq_event_source_team_key ON team (event_id, source_team_key)")
        )


def ensure_sms_log_columns(engine: Engine) -> None:
    """
    Idempotently adds required columns to the 'sms_log' table if missing.
    Safe to run at every startup.
    """
    try:
        from app.models.sms_log import SmsLog

        table = SmsLog.__table__.name

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
                for name, sqlite_type, _pg_type in REQUIRED_SMS_LOG_COLUMNS:
                    if name in existing:
                        continue
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {sqlite_type};"))
        else:
            with engine.connect() as conn:
                result = conn.execute(
                    text(
                        """
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables
                        WHERE table_schema = 'public' AND table_name = :table_name
                    )
                """
                    ),
                    {"table_name": table},
                ).fetchone()
                if not result or not result[0]:
                    return

            existing = _get_existing_columns_postgres(engine, table)
            with engine.begin() as conn:
                for name, _sqlite_type, pg_type in REQUIRED_SMS_LOG_COLUMNS:
                    if name in existing:
                        continue
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {name} {pg_type};"))
    except Exception as e:
        import logging

        logger = logging.getLogger(__name__)
        logger.warning(f"Failed to ensure sms_log columns (this is OK if table doesn't exist yet): {e}")


def ensure_tournament_sms_settings_columns(engine: Engine) -> None:
    """
    Idempotently adds required columns to the 'tournament_sms_settings' table if missing.
    Safe to run at every startup.
    """
    try:
        from app.models.tournament_sms_settings import TournamentSmsSettings

        table = TournamentSmsSettings.__table__.name

        if _is_sqlite(engine):
            with engine.connect() as conn:
                result = conn.execute(
                    text("SELECT name FROM sqlite_master WHERE type='table' AND name=:table_name"),
                    {"table_name": table},
                ).fetchone()
                if not result:
                    return

            existing = _get_existing_columns_sqlite(engine, table)
            added_delivery_mode = "delivery_mode" not in existing
            with engine.begin() as conn:
                for name, sqlite_type, _pg_type in REQUIRED_TOURNAMENT_SMS_SETTINGS_COLUMNS:
                    if name in existing:
                        continue
                    if name in {
                        "test_mode",
                        "player_contacts_only",
                        "auto_checkin_first_match",
                        "auto_checkin_slot_checkin",
                        "auto_checkin_post_match_next",
                        "auto_checkin_court_assigned",
                    }:
                        default = " DEFAULT 0"
                    elif name == "delivery_mode":
                        default = " DEFAULT 'live'"
                    else:
                        default = ""
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {sqlite_type}{default};"))
                if added_delivery_mode:
                    conn.execute(
                        text("UPDATE tournament_sms_settings SET delivery_mode = 'allowlist' WHERE test_mode != 0")
                    )
        else:
            with engine.connect() as conn:
                result = conn.execute(
                    text(
                        """
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables
                        WHERE table_schema = 'public' AND table_name = :table_name
                    )
                """
                    ),
                    {"table_name": table},
                ).fetchone()
                if not result or not result[0]:
                    return

            existing = _get_existing_columns_postgres(engine, table)
            added_delivery_mode = "delivery_mode" not in existing
            with engine.begin() as conn:
                for name, _sqlite_type, pg_type in REQUIRED_TOURNAMENT_SMS_SETTINGS_COLUMNS:
                    if name in existing:
                        continue
                    if name in {
                        "test_mode",
                        "player_contacts_only",
                        "auto_checkin_first_match",
                        "auto_checkin_slot_checkin",
                        "auto_checkin_post_match_next",
                        "auto_checkin_court_assigned",
                    }:
                        default = " DEFAULT FALSE"
                    elif name == "delivery_mode":
                        default = " DEFAULT 'live'"
                    else:
                        default = ""
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {name} {pg_type}{default};"))
                if added_delivery_mode:
                    conn.execute(
                        text("UPDATE tournament_sms_settings SET delivery_mode = 'allowlist' WHERE test_mode IS TRUE")
                    )
    except Exception as e:
        import logging

        logger = logging.getLogger(__name__)
        logger.warning(f"Failed to ensure tournament_sms_settings columns (this is OK if table doesn't exist yet): {e}")


def ensure_temporary_player_lookup_columns(engine: Engine) -> None:
    """
    Idempotently adds required columns to the 'temporary_player_lookup' table if missing.
    Safe to run at every startup.
    """
    try:
        from app.models.temporary_player_lookup import TemporaryPlayerLookup

        table = TemporaryPlayerLookup.__table__.name

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
                for name, sqlite_type, _pg_type in REQUIRED_TEMPORARY_PLAYER_LOOKUP_COLUMNS:
                    if name in existing:
                        continue
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {sqlite_type};"))
        else:
            with engine.connect() as conn:
                result = conn.execute(
                    text(
                        """
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables
                        WHERE table_schema = 'public' AND table_name = :table_name
                    )
                """
                    ),
                    {"table_name": table},
                ).fetchone()
                if not result or not result[0]:
                    return

            existing = _get_existing_columns_postgres(engine, table)
            with engine.begin() as conn:
                for name, _sqlite_type, pg_type in REQUIRED_TEMPORARY_PLAYER_LOOKUP_COLUMNS:
                    if name in existing:
                        continue
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {name} {pg_type};"))
        _ensure_rwos_lookup_source_identity_unique(engine)
    except Exception as e:
        import logging

        logger = logging.getLogger(__name__)
        logger.warning(f"Failed to ensure temporary_player_lookup columns (this is OK if table doesn't exist yet): {e}")


def _ensure_rwos_lookup_source_identity_unique(engine: Engine) -> None:
    """Partial unique identity for RW-OS towel rows; source=NULL rows stay unconstrained."""
    if _is_sqlite(engine):
        with engine.begin() as conn:
            conn.execute(
                text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS uq_rwos_lookup_source_identity "
                    "ON temporary_player_lookup (tournament_id, source, source_team_key, lineup_slot) "
                    "WHERE source IS NOT NULL"
                )
            )
        return
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_rwos_lookup_source_identity "
                "ON temporary_player_lookup (tournament_id, source, source_team_key, lineup_slot) "
                "WHERE source IS NOT NULL"
            )
        )


def ensure_sms_phone_list_columns(engine: Engine) -> None:
    """Idempotently adds required columns to the sms phone list tables."""
    try:
        from app.models.sms_phone_list import SmsPhoneList, SmsPhoneListMember

        for model, required_columns in (
            (SmsPhoneList, REQUIRED_SMS_PHONE_LIST_COLUMNS),
            (SmsPhoneListMember, REQUIRED_SMS_PHONE_LIST_MEMBER_COLUMNS),
        ):
            table = model.__table__.name

            if _is_sqlite(engine):
                with engine.connect() as conn:
                    result = conn.execute(
                        text("SELECT name FROM sqlite_master WHERE type='table' AND name=:table_name"),
                        {"table_name": table},
                    ).fetchone()
                    if not result:
                        continue

                existing = _get_existing_columns_sqlite(engine, table)
                with engine.begin() as conn:
                    for name, sqlite_type, _pg_type in required_columns:
                        if name in existing:
                            continue
                        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {sqlite_type};"))
            else:
                with engine.connect() as conn:
                    result = conn.execute(
                        text(
                            """
                        SELECT EXISTS (
                            SELECT FROM information_schema.tables
                            WHERE table_schema = 'public' AND table_name = :table_name
                        )
                    """
                        ),
                        {"table_name": table},
                    ).fetchone()
                    if not result or not result[0]:
                        continue

                existing = _get_existing_columns_postgres(engine, table)
                with engine.begin() as conn:
                    for name, _sqlite_type, pg_type in required_columns:
                        if name in existing:
                            continue
                        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {name} {pg_type};"))
    except Exception as e:
        import logging

        logger = logging.getLogger(__name__)
        logger.warning(f"Failed to ensure sms phone list columns (this is OK if table doesn't exist yet): {e}")


def ensure_start_over_baseline_assignment_table(engine: Engine) -> None:
    """
    Ensure start_over_baseline_assignment table exists.
    Safe to run at every startup.
    """
    try:
        from app.models.start_over_baseline_assignment import StartOverBaselineAssignment

        table = StartOverBaselineAssignment.__table__
        with engine.begin() as conn:
            table.create(conn, checkfirst=True)
    except Exception as e:
        import logging

        logger = logging.getLogger(__name__)
        logger.warning(
            f"Failed to ensure start_over_baseline_assignment table (this is OK if table doesn't exist yet): {e}"
        )


OPENING_SLOT_RELEASE_TABLE = "openingslotrelease"
COURT_DISPATCH_LOCK_TABLE = "courtdispatchlock"
UQ_OPENING_SLOT_RELEASE = "uq_opening_slot_release_version_day_slot"
UQ_COURT_DISPATCH_LOCK = "uq_court_dispatch_lock_version_day_court"

# Process cache avoids opening a second SQLite connection during an active
# write transaction (which can deadlock under the default journal mode).
_preassigned_schema_ready_cache: Optional[bool] = None


def invalidate_preassigned_schema_ready_cache() -> None:
    global _preassigned_schema_ready_cache
    _preassigned_schema_ready_cache = None


def _set_preassigned_schema_ready_cache(ready: bool) -> None:
    global _preassigned_schema_ready_cache
    _preassigned_schema_ready_cache = ready


def _sqlite_table_exists_conn(conn: Connection, table_name: str) -> bool:
    row = conn.execute(
        text("SELECT name FROM sqlite_master WHERE type='table' AND name=:table_name"),
        {"table_name": table_name},
    ).fetchone()
    return row is not None


def _postgres_table_exists_conn(conn: Connection, table_name: str) -> bool:
    row = conn.execute(
        text(
            """
            SELECT EXISTS (
                SELECT FROM information_schema.tables
                WHERE table_schema = 'public' AND table_name = :table_name
            )
            """
        ),
        {"table_name": table_name},
    ).fetchone()
    return bool(row and row[0])


def _sqlite_unique_index_covers_conn(
    conn: Connection,
    *,
    table_name: str,
    index_name: str,
    columns: List[str],
) -> bool:
    """True when a UNIQUE index with the expected name (or equivalent columns) exists."""
    indexes = conn.execute(text(f"PRAGMA index_list('{table_name}')")).fetchall()
    # row: (seq, name, unique, origin, partial)
    by_name = {str(r[1]): r for r in indexes if r[1]}
    if index_name in by_name and int(by_name[index_name][2] or 0) == 1:
        infos = conn.execute(text(f"PRAGMA index_info('{index_name}')")).fetchall()
        covered = [str(r[2]) for r in sorted(infos, key=lambda r: int(r[0]))]
        return covered == columns
    for row in indexes:
        if int(row[2] or 0) != 1:
            continue
        name = str(row[1])
        infos = conn.execute(text(f"PRAGMA index_info('{name}')")).fetchall()
        covered = [str(r[2]) for r in sorted(infos, key=lambda r: int(r[0]))]
        if covered == columns:
            return True
    return False


def _postgres_unique_constraint_exists_conn(conn: Connection, *, table_name: str, constraint_name: str) -> bool:
    row = conn.execute(
        text(
            """
            SELECT 1
            FROM information_schema.table_constraints
            WHERE table_schema = 'public'
              AND table_name = :table_name
              AND constraint_name = :constraint_name
              AND constraint_type = 'UNIQUE'
            """
        ),
        {"table_name": table_name, "constraint_name": constraint_name},
    ).fetchone()
    return row is not None


def _ensure_sqlite_unique_index(
    engine: Engine,
    *,
    table_name: str,
    index_name: str,
    columns: List[str],
) -> None:
    cols_sql = ", ".join(columns)
    with engine.begin() as conn:
        conn.execute(text(f"CREATE UNIQUE INDEX IF NOT EXISTS {index_name} ON {table_name} ({cols_sql})"))


def inspect_preassigned_automation_schema(
    engine: Engine,
    *,
    connection: Optional[Connection] = None,
) -> Dict[str, object]:
    """Read-only schema readiness for PREASSIGNED automation. Never mutates.

    Prefer passing ``connection=session.connection()`` when a session already
    holds a SQLite write transaction so a second connection is not opened.
    """
    dialect = engine.dialect.name.lower()
    errors: List[str] = []

    def _inspect(conn: Connection) -> Dict[str, object]:
        nonlocal errors
        errors = []
        if dialect == "sqlite":
            opening_table = _sqlite_table_exists_conn(conn, OPENING_SLOT_RELEASE_TABLE)
            lock_table = _sqlite_table_exists_conn(conn, COURT_DISPATCH_LOCK_TABLE)
            opening_uq = (
                _sqlite_unique_index_covers_conn(
                    conn,
                    table_name=OPENING_SLOT_RELEASE_TABLE,
                    index_name=UQ_OPENING_SLOT_RELEASE,
                    columns=["schedule_version_id", "day_date", "slot_key"],
                )
                if opening_table
                else False
            )
            lock_uq = (
                _sqlite_unique_index_covers_conn(
                    conn,
                    table_name=COURT_DISPATCH_LOCK_TABLE,
                    index_name=UQ_COURT_DISPATCH_LOCK,
                    columns=["schedule_version_id", "day_date", "court_number"],
                )
                if lock_table
                else False
            )
        else:
            opening_table = _postgres_table_exists_conn(conn, OPENING_SLOT_RELEASE_TABLE)
            lock_table = _postgres_table_exists_conn(conn, COURT_DISPATCH_LOCK_TABLE)
            opening_uq = (
                _postgres_unique_constraint_exists_conn(
                    conn, table_name=OPENING_SLOT_RELEASE_TABLE, constraint_name=UQ_OPENING_SLOT_RELEASE
                )
                if opening_table
                else False
            )
            lock_uq = (
                _postgres_unique_constraint_exists_conn(
                    conn, table_name=COURT_DISPATCH_LOCK_TABLE, constraint_name=UQ_COURT_DISPATCH_LOCK
                )
                if lock_table
                else False
            )

        if not opening_table:
            errors.append(f"missing table {OPENING_SLOT_RELEASE_TABLE}")
        if not lock_table:
            errors.append(f"missing table {COURT_DISPATCH_LOCK_TABLE}")
        if opening_table and not opening_uq:
            errors.append(f"missing unique constraint {UQ_OPENING_SLOT_RELEASE}")
        if lock_table and not lock_uq:
            errors.append(f"missing unique constraint {UQ_COURT_DISPATCH_LOCK}")

        ready = not errors
        result = {
            "ready": ready,
            "dialect": dialect,
            "opening_slot_release_table": opening_table,
            "court_dispatch_lock_table": lock_table,
            "uq_opening_slot_release_version_day_slot": opening_uq,
            "uq_court_dispatch_lock_version_day_court": lock_uq,
            "errors": errors,
        }
        _set_preassigned_schema_ready_cache(ready)
        return result

    if connection is not None:
        return _inspect(connection)
    with engine.connect() as conn:
        return _inspect(conn)


def is_preassigned_automation_schema_ready(
    engine: Engine,
    *,
    connection: Optional[Connection] = None,
    use_cache: bool = True,
) -> bool:
    if use_cache and _preassigned_schema_ready_cache is not None:
        return _preassigned_schema_ready_cache
    return bool(inspect_preassigned_automation_schema(engine, connection=connection)["ready"])


def ensure_opening_slot_release_table(engine: Engine) -> None:
    """Ensure openingslotrelease table + unique index exist.

    Failures are logged as errors and re-raised so startup/ops cannot treat
    PREASSIGNED automation as ready when schema initialization failed.
    """
    import logging

    logger = logging.getLogger(__name__)
    try:
        from app.models.opening_slot_release import OpeningSlotRelease

        table = OpeningSlotRelease.__table__
        with engine.begin() as conn:
            table.create(conn, checkfirst=True)
        if _is_sqlite(engine):
            _ensure_sqlite_unique_index(
                engine,
                table_name=OPENING_SLOT_RELEASE_TABLE,
                index_name=UQ_OPENING_SLOT_RELEASE,
                columns=["schedule_version_id", "day_date", "slot_key"],
            )
            with engine.connect() as conn:
                table_ok = _sqlite_table_exists_conn(conn, OPENING_SLOT_RELEASE_TABLE)
                uq_ok = _sqlite_unique_index_covers_conn(
                    conn,
                    table_name=OPENING_SLOT_RELEASE_TABLE,
                    index_name=UQ_OPENING_SLOT_RELEASE,
                    columns=["schedule_version_id", "day_date", "slot_key"],
                )
        else:
            with engine.connect() as conn:
                table_ok = _postgres_table_exists_conn(conn, OPENING_SLOT_RELEASE_TABLE)
                uq_ok = _postgres_unique_constraint_exists_conn(
                    conn,
                    table_name=OPENING_SLOT_RELEASE_TABLE,
                    constraint_name=UQ_OPENING_SLOT_RELEASE,
                )
        if not table_ok or not uq_ok:
            invalidate_preassigned_schema_ready_cache()
            raise RuntimeError(f"openingslotrelease schema not ready after ensure (table={table_ok}, unique={uq_ok})")
        invalidate_preassigned_schema_ready_cache()
    except Exception as e:
        invalidate_preassigned_schema_ready_cache()
        logger.error("Failed to ensure openingslotrelease table/constraints: %s", e)
        raise


def ensure_court_dispatch_lock_table(engine: Engine) -> None:
    """Ensure courtdispatchlock table + unique index exist.

    Failures are logged as errors and re-raised so startup/ops cannot treat
    PREASSIGNED automation as ready when schema initialization failed.
    """
    import logging

    logger = logging.getLogger(__name__)
    try:
        from app.models.court_dispatch_lock import CourtDispatchLock

        table = CourtDispatchLock.__table__
        with engine.begin() as conn:
            table.create(conn, checkfirst=True)
        if _is_sqlite(engine):
            _ensure_sqlite_unique_index(
                engine,
                table_name=COURT_DISPATCH_LOCK_TABLE,
                index_name=UQ_COURT_DISPATCH_LOCK,
                columns=["schedule_version_id", "day_date", "court_number"],
            )
            with engine.connect() as conn:
                table_ok = _sqlite_table_exists_conn(conn, COURT_DISPATCH_LOCK_TABLE)
                uq_ok = _sqlite_unique_index_covers_conn(
                    conn,
                    table_name=COURT_DISPATCH_LOCK_TABLE,
                    index_name=UQ_COURT_DISPATCH_LOCK,
                    columns=["schedule_version_id", "day_date", "court_number"],
                )
        else:
            with engine.connect() as conn:
                table_ok = _postgres_table_exists_conn(conn, COURT_DISPATCH_LOCK_TABLE)
                uq_ok = _postgres_unique_constraint_exists_conn(
                    conn,
                    table_name=COURT_DISPATCH_LOCK_TABLE,
                    constraint_name=UQ_COURT_DISPATCH_LOCK,
                )
        if not table_ok or not uq_ok:
            invalidate_preassigned_schema_ready_cache()
            raise RuntimeError(f"courtdispatchlock schema not ready after ensure (table={table_ok}, unique={uq_ok})")
        # Refresh cache after both ensures typically run; opening ensure cleared it.
        inspect_preassigned_automation_schema(engine)
    except Exception as e:
        invalidate_preassigned_schema_ready_cache()
        logger.error("Failed to ensure courtdispatchlock table/constraints: %s", e)
        raise


def ensure_tournament_time_window_columns(engine: Engine) -> None:
    """Idempotently adds required columns to the tournament time window table."""
    try:
        from app.models.tournament_time_window import TournamentTimeWindow

        table = TournamentTimeWindow.__table__.name
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
                for name, sqlite_type, _pg_type in REQUIRED_TOURNAMENT_TIME_WINDOW_COLUMNS:
                    if name in existing:
                        continue
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {sqlite_type} DEFAULT 0;"))
        else:
            with engine.connect() as conn:
                result = conn.execute(
                    text(
                        """
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables
                        WHERE table_schema = 'public' AND table_name = :table_name
                    )
                """
                    ),
                    {"table_name": table},
                ).fetchone()
                if not result or not result[0]:
                    return

            existing = _get_existing_columns_postgres(engine, table)
            with engine.begin() as conn:
                for name, _sqlite_type, pg_type in REQUIRED_TOURNAMENT_TIME_WINDOW_COLUMNS:
                    if name in existing:
                        continue
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {name} {pg_type} DEFAULT 0;"))
    except Exception as e:
        import logging

        logger = logging.getLogger(__name__)
        logger.warning(f"Failed to ensure tournament time window columns (this is OK if table doesn't exist yet): {e}")


def ensure_schedule_slot_columns(engine: Engine) -> None:
    """Idempotently adds required columns to the schedule slot table."""
    try:
        from app.models.schedule_slot import ScheduleSlot

        table = ScheduleSlot.__table__.name
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
                for name, sqlite_type, _pg_type in REQUIRED_SCHEDULE_SLOT_COLUMNS:
                    if name in existing:
                        continue
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {sqlite_type} DEFAULT 0;"))
        else:
            with engine.connect() as conn:
                result = conn.execute(
                    text(
                        """
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables
                        WHERE table_schema = 'public' AND table_name = :table_name
                    )
                """
                    ),
                    {"table_name": table},
                ).fetchone()
                if not result or not result[0]:
                    return

            existing = _get_existing_columns_postgres(engine, table)
            with engine.begin() as conn:
                for name, _sqlite_type, pg_type in REQUIRED_SCHEDULE_SLOT_COLUMNS:
                    if name in existing:
                        continue
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {name} {pg_type} DEFAULT FALSE;"))
    except Exception as e:
        import logging

        logger = logging.getLogger(__name__)
        logger.warning(f"Failed to ensure schedule slot columns (this is OK if table doesn't exist yet): {e}")


def ensure_tournament_import_columns(engine: Engine) -> None:
    """Add forecast_json / approved_source_hash to tournament_import when missing."""
    try:
        table = "tournament_import"
        required = (
            ("forecast_json", "TEXT"),
            ("approved_source_hash", "TEXT"),
        )
        if _is_sqlite(engine):
            existing = _get_existing_columns_sqlite(engine, table)
            if not existing:
                return
            with engine.begin() as conn:
                for name, sqlite_type in required:
                    if name in existing:
                        continue
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {sqlite_type} DEFAULT NULL;"))
            return
        existing = _get_existing_columns_postgres(engine, table)
        if not existing:
            return
        with engine.begin() as conn:
            for name, pg_type in required:
                if name in existing:
                    continue
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {name} {pg_type};"))
    except Exception as exc:
        import logging

        logging.getLogger(__name__).warning("Failed to ensure tournament_import columns: %s", exc)
