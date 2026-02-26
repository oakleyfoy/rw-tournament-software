import os
from pathlib import Path
from typing import Generator

from dotenv import load_dotenv
from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel, create_engine

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./tournament.db")

_is_sqlite = DATABASE_URL.startswith("sqlite")
_connect_args = {"check_same_thread": False} if _is_sqlite else {}
_echo = os.getenv("SQL_ECHO", "false").lower() in ("true", "1", "yes")

if _is_sqlite:
    db_path = DATABASE_URL.replace("sqlite:///", "", 1)
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)

engine: Engine = create_engine(
    DATABASE_URL,
    echo=_echo,
    connect_args=_connect_args,
)


def get_session() -> Generator[Session, None, None]:
    """Get database session"""
    with Session(engine) as session:
        yield session


def init_db() -> None:
    """Initialize database - create all tables"""
    # Import all models to ensure they're registered with SQLModel metadata
    from app.models.court_state import TournamentCourtState  # noqa: F401
    from app.models.event import Event  # noqa: F401
    from app.models.match import Match  # noqa: F401
    from app.models.match_assignment import MatchAssignment  # noqa: F401
    from app.models.match_lock import MatchLock  # noqa: F401
    from app.models.policy_run import PolicyRun  # noqa: F401
    from app.models.slot_lock import SlotLock  # noqa: F401
    from app.models.schedule_slot import ScheduleSlot  # noqa: F401
    from app.models.schedule_version import ScheduleVersion  # noqa: F401
    from app.models.team import Team  # noqa: F401
    from app.models.team_avoid_edge import TeamAvoidEdge  # noqa: F401
    from app.models.tournament import Tournament  # noqa: F401
    from app.models.tournament_day import TournamentDay  # noqa: F401
    from app.models.tournament_time_window import TournamentTimeWindow  # noqa: F401

    SQLModel.metadata.create_all(engine)
