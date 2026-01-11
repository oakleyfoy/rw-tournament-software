# Force SQLModel table registration at test discovery time
# This ensures all models are registered before any test database creation
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
