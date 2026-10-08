import os
import sys
from pathlib import Path
from typing import Generator

from dotenv import load_dotenv
from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel, create_engine

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./tournament.db")

_is_sqlite = DATABASE_URL.startswith("sqlite")
# SQLite busy timeout (seconds): writers wait instead of failing immediately with
# "database is locked" under concurrent desk dispatch.
SQLITE_BUSY_TIMEOUT_SEC = float(os.getenv("SQLITE_BUSY_TIMEOUT_SEC", "30"))
_connect_args = {"check_same_thread": False, "timeout": SQLITE_BUSY_TIMEOUT_SEC} if _is_sqlite else {}
_echo = os.getenv("SQL_ECHO", "false").lower() in ("true", "1", "yes")

# BEGIN IMMEDIATE serializes SQLite writers (needed for concurrent court dispatch).
# Default ON for production/dev servers; default OFF under pytest because several
# legacy suites share the file-backed app.database.engine and contend on IMMEDIATE.
_under_pytest = ("pytest" in sys.modules) or any(a.endswith("pytest") or a == "pytest" for a in sys.argv)
_default_begin_immediate = "false" if _under_pytest else "true"
SQLITE_BEGIN_IMMEDIATE = os.getenv("SQLITE_BEGIN_IMMEDIATE", _default_begin_immediate).lower() in (
    "true",
    "1",
    "yes",
)

if _is_sqlite:
    db_path = DATABASE_URL.replace("sqlite:///", "", 1)
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)

engine: Engine = create_engine(
    DATABASE_URL,
    echo=_echo,
    connect_args=_connect_args,
)

if _is_sqlite and SQLITE_BEGIN_IMMEDIATE:

    @event.listens_for(engine, "begin")
    def _sqlite_begin_immediate(conn) -> None:  # type: ignore[no-untyped-def]
        """Serialize writers at transaction start (SQLite has no row-level locks)."""
        conn.exec_driver_sql("BEGIN IMMEDIATE")


def get_session() -> Generator[Session, None, None]:
    """Get database session"""
    with Session(engine) as session:
        yield session


def init_db() -> None:
    """Initialize database - create all tables"""
    # Import all models to ensure they're registered with SQLModel metadata
    from app.models.auth_session import AuthSession  # noqa: F401
    from app.models.court_dispatch_lock import CourtDispatchLock  # noqa: F401
    from app.models.court_state import TournamentCourtState  # noqa: F401
    from app.models.event import Event  # noqa: F401
    from app.models.match import Match  # noqa: F401
    from app.models.match_assignment import MatchAssignment  # noqa: F401
    from app.models.match_checkin import MatchCheckIn  # noqa: F401
    from app.models.match_lock import MatchLock  # noqa: F401
    from app.models.match_player_checkin import MatchPlayerCheckIn  # noqa: F401
    from app.models.opening_slot_release import OpeningSlotRelease  # noqa: F401
    from app.models.player import Player  # noqa: F401
    from app.models.policy_run import PolicyRun  # noqa: F401
    from app.models.schedule_slot import ScheduleSlot  # noqa: F401
    from app.models.schedule_version import ScheduleVersion  # noqa: F401
    from app.models.slot_lock import SlotLock  # noqa: F401
    from app.models.sms_consent_event import SmsConsentEvent  # noqa: F401
    from app.models.sms_phone_list import SmsPhoneList, SmsPhoneListMember  # noqa: F401
    from app.models.start_over_baseline_assignment import (  # noqa: F401
        StartOverBaselineAssignment,
    )
    from app.models.team import Team  # noqa: F401
    from app.models.team_avoid_edge import TeamAvoidEdge  # noqa: F401
    from app.models.team_player import TeamPlayer  # noqa: F401
    from app.models.temporary_player_lookup import TemporaryPlayerLookup  # noqa: F401
    from app.models.tournament import Tournament  # noqa: F401
    from app.models.tournament_day import TournamentDay  # noqa: F401
    from app.models.tournament_import import TournamentDrawPlan, TournamentImport  # noqa: F401
    from app.models.tournament_time_window import TournamentTimeWindow  # noqa: F401
    from app.models.user_account import UserAccount  # noqa: F401

    SQLModel.metadata.create_all(engine)
