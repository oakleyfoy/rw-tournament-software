"""Return one desk match to Waiting for Check-In.

This is separate from Back To Ready To Go. Ready keeps both teams checked in.
Waiting clears this match's check-in and drops live court occupancy. The match,
draw, teams, slot assignment, and any recorded score stay in place.
"""

from datetime import datetime

from sqlmodel import Session, select

from app.models.match import Match
from app.models.match_checkin import MatchCheckIn
from app.models.match_player_checkin import MatchPlayerCheckIn
from app.models.schedule_version import ScheduleVersion
from app.models.tournament import Tournament
from app.services.preassigned_dispatch import match_fully_checked_in

RESETTABLE_STATUSES = frozenset({"SCHEDULED", "IN_PROGRESS", "PAUSED", "DELAYED"})
BLOCKED_DETAIL = (
    "This match cannot be returned to Waiting for Check-In because it has a "
    "recorded score or a finalized result."
)


class CheckInResetRejected(Exception):
    def __init__(self, detail: str, status_code: int = 409):
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


def _has_recorded_score(match: Match) -> bool:
    if match.winner_team_id is not None:
        return True
    score = match.score_json
    if score is None:
        return False
    if isinstance(score, str):
        return bool(score.strip())
    if isinstance(score, dict):
        return bool(score)
    return True


def return_match_to_waiting_checkin(
    session: Session,
    *,
    tournament: Tournament,
    version: ScheduleVersion,
    match: Match,
) -> str:
    """Clear this match's live court occupancy and check-in in the caller's transaction.

    The caller commits once. Nothing is written when the reset is rejected, so a
    scored or finalized match cannot be left half-reset.
    """
    if tournament.id is None or version.id is None or match.id is None:
        raise CheckInResetRejected("Match not found", 404)
    if match.tournament_id != tournament.id or match.schedule_version_id != version.id:
        raise CheckInResetRejected("Match not found", 404)
    if version.status != "draft":
        raise CheckInResetRejected(
            "Cannot modify matches in a FINAL version. Use a Desk Draft.",
            400,
        )

    previous = (match.runtime_status or "SCHEDULED").upper()
    if previous == "FINAL" or _has_recorded_score(match):
        raise CheckInResetRejected(BLOCKED_DETAIL, 409)
    if previous not in RESETTABLE_STATUSES:
        raise CheckInResetRejected(
            f"Match status {previous} cannot be returned to Waiting for Check-In.",
            400,
        )

    now = datetime.utcnow()
    team_rows = session.exec(
        select(MatchCheckIn).where(
            MatchCheckIn.schedule_version_id == version.id,
            MatchCheckIn.match_id == match.id,
        )
    ).all()
    for row in team_rows:
        row.team_checked_in = False
        row.checked_in_at = None
        row.updated_at = now
        session.add(row)

    player_rows = session.exec(
        select(MatchPlayerCheckIn).where(
            MatchPlayerCheckIn.schedule_version_id == version.id,
            MatchPlayerCheckIn.match_id == match.id,
        )
    ).all()
    for row in player_rows:
        row.checked_in = False
        row.checked_in_at = None
        row.updated_at = now
        session.add(row)

    match.runtime_status = "SCHEDULED"
    match.started_at = None
    match.completed_at = None
    match.checkin_reset_pending = True
    session.add(match)
    session.flush()
    return previous


def checkin_reset_blocks_start(session: Session, match: Match) -> bool:
    """True only for a match that was reset and is not fully checked in again."""
    if not bool(getattr(match, "checkin_reset_pending", False)):
        return False
    return not match_fully_checked_in(session, match)


def clear_checkin_reset_if_ready(session: Session, match: Match) -> None:
    """Drop the reset hold once both teams are checked in, then commit that alone."""
    if not bool(getattr(match, "checkin_reset_pending", False)):
        return
    if not match_fully_checked_in(session, match):
        return
    match.checkin_reset_pending = False
    session.add(match)
    session.commit()
