import os
from typing import Generator

from dotenv import load_dotenv
from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel, create_engine

load_dotenv()

# Database URL - defaults to SQLite for development
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./tournament.db")

engine: Engine = create_engine(
    DATABASE_URL,
    echo=True,
    connect_args={"check_same_thread": False},
)


def get_session() -> Generator[Session, None, None]:
    """Get database session"""
    with Session(engine) as session:
        yield session


def init_db() -> None:
    """Initialize database - create all tables"""
    # Import all models to ensure they're registered with SQLModel metadata
    from app.models.event import Event  # noqa: F401
    from app.models.match import Match  # noqa: F401
    from app.models.match_assignment import MatchAssignment  # noqa: F401
    from app.models.schedule_slot import ScheduleSlot  # noqa: F401
    from app.models.schedule_version import ScheduleVersion  # noqa: F401
    from app.models.team import Team  # noqa: F401
    from app.models.team_avoid_edge import TeamAvoidEdge  # noqa: F401
    from app.models.tournament import Tournament  # noqa: F401
    from app.models.tournament_day import TournamentDay  # noqa: F401
    from app.models.tournament_time_window import TournamentTimeWindow  # noqa: F401

    SQLModel.metadata.create_all(engine)
