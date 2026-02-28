"""SMS routes for tournament texting.

Provides endpoints for:
- Sending texts (blast, team, match, timeslot)
- Viewing send history (log)
- Managing templates
- Managing auto-text settings
"""

import logging
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from sqlmodel import Session, select

from app.database import get_session
from app.models.match import Match
from app.models.match_assignment import MatchAssignment
from app.models.schedule_slot import ScheduleSlot
from app.models.sms_log import SmsLog
from app.models.sms_template import DEFAULT_SMS_TEMPLATES, SmsTemplate
from app.models.team import Team
from app.models.tournament import Tournament
from app.models.tournament_sms_settings import TournamentSmsSettings
from app.services.twilio_service import (
    format_e164,
    get_team_phone_numbers,
    get_twilio_service,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/tournaments/{tournament_id}/sms", tags=["sms"])


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class SmsSendResult(BaseModel):
    """Result of sending SMS to one recipient."""

    phone: str
    team_id: Optional[int] = None
    team_name: Optional[str] = None
    status: str  # queued|sent|dry_run|failed
    error: Optional[str] = None


class SmsSendResponse(BaseModel):
    """Response from any send endpoint."""

    total: int
    sent: int
    failed: int
    skipped_no_phone: int
    message_type: str
    results: List[SmsSendResult]


class SmsPreviewRecipient(BaseModel):
    """Preview of who would receive a text."""

    team_id: int
    team_name: str
    phones: List[str]
    message: str


class SmsPreviewResponse(BaseModel):
    """Dry-run preview of a send operation."""

    total_teams: int
    total_messages: int
    teams_without_phone: int
    recipients: List[SmsPreviewRecipient]


class SmsLogResponse(BaseModel):
    """Single SMS log entry."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    tournament_id: int
    team_id: Optional[int] = None
    phone_number: str
    message_body: str
    message_type: str
    twilio_sid: Optional[str] = None
    status: str
    error_message: Optional[str] = None
    trigger: str
    sent_at: datetime


class SmsSettingsResponse(BaseModel):
    """Tournament SMS settings."""

    model_config = ConfigDict(from_attributes=True)

    tournament_id: int
    auto_first_match: bool
    auto_post_match_next: bool
    auto_on_deck: bool
    auto_up_next: bool
    auto_court_change: bool


class SmsSettingsUpdate(BaseModel):
    """Update request for SMS settings."""

    auto_first_match: Optional[bool] = None
    auto_post_match_next: Optional[bool] = None
    auto_on_deck: Optional[bool] = None
    auto_up_next: Optional[bool] = None
    auto_court_change: Optional[bool] = None


class SmsTemplateResponse(BaseModel):
    """Single SMS template."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    tournament_id: int
    message_type: str
    template_body: str
    is_active: bool


class SmsTemplateUpdate(BaseModel):
    """Update request for a template."""

    template_body: str
    is_active: Optional[bool] = None


class SmsSendRequest(BaseModel):
    """Request body for manual send endpoints."""

    message: str


class SmsTimeslotRequest(BaseModel):
    """Request body for timeslot send."""

    message: str
    day_date: str  # "2026-03-15"
    start_time: str  # "10:00" or "10:00:00"
    schedule_version_id: int


class SmsStatusResponse(BaseModel):
    """Quick status check for SMS configuration."""

    twilio_configured: bool
    from_number: Optional[str] = None
    tournament_has_settings: bool
    total_teams: int
    teams_with_phones: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_tournament_or_404(
    session: Session, tournament_id: int
) -> Tournament:
    """Get tournament or raise 404."""
    tournament = session.get(Tournament, tournament_id)
    if not tournament:
        raise HTTPException(404, f"Tournament {tournament_id} not found")
    return tournament


def _get_all_teams_for_tournament(
    session: Session, tournament_id: int
) -> List[Team]:
    """Get all teams across all events in a tournament."""
    from app.models.event import Event

    events = session.exec(
        select(Event).where(Event.tournament_id == tournament_id)
    ).all()
    event_ids = [e.id for e in events]
    if not event_ids:
        return []

    teams = session.exec(
        select(Team).where(Team.event_id.in_(event_ids))  # type: ignore
    ).all()
    return list(teams)


def _send_to_teams(
    session: Session,
    tournament_id: int,
    teams: List[Team],
    message: str,
    message_type: str,
    trigger: str = "manual",
) -> SmsSendResponse:
    """
    Core send logic: takes a list of teams and a message, sends to all phone numbers.
    Logs every send attempt to sms_log.
    """
    twilio = get_twilio_service()
    results: List[SmsSendResult] = []
    sent_count = 0
    failed_count = 0
    skipped_count = 0

    for team in teams:
        phones = get_team_phone_numbers(team)
        if not phones:
            skipped_count += 1
            continue

        for phone in phones:
            send_result = twilio.send_sms(phone, message)

            # Log to database
            log_entry = SmsLog(
                tournament_id=tournament_id,
                team_id=team.id,
                phone_number=phone,
                message_body=message,
                message_type=message_type,
                twilio_sid=send_result.get("sid"),
                status=send_result.get("status", "failed"),
                error_message=send_result.get("error"),
                trigger=trigger,
                sent_at=datetime.now(timezone.utc),
            )
            session.add(log_entry)

            status = send_result.get("status", "failed")
            if status in ("queued", "sent", "dry_run"):
                sent_count += 1
            else:
                failed_count += 1

            results.append(
                SmsSendResult(
                    phone=phone,
                    team_id=team.id,
                    team_name=team.name,
                    status=status,
                    error=send_result.get("error"),
                )
            )

    session.commit()

    return SmsSendResponse(
        total=len(results),
        sent=sent_count,
        failed=failed_count,
        skipped_no_phone=skipped_count,
        message_type=message_type,
        results=results,
    )


def _render_template(
    template_body: str,
    **kwargs,
) -> str:
    """
    Render a message template with placeholders.

    Supports: {tournament_name}, {team_name}, {date}, {time},
              {court}, {match_code}, {opponent}, {day_number}

    Unknown placeholders are left as-is (not crash).
    """
    try:
        return template_body.format_map(
            {k: v for k, v in kwargs.items() if v is not None}
        )
    except KeyError:
        # If template has placeholders we don't have values for,
        # do a safe partial render
        result = template_body
        for key, value in kwargs.items():
            if value is not None:
                result = result.replace(f"{{{key}}}", str(value))
        return result


# ---------------------------------------------------------------------------
# Status endpoint
# ---------------------------------------------------------------------------


@router.get("/status", response_model=SmsStatusResponse)
def get_sms_status(
    tournament_id: int,
    session: Session = Depends(get_session),
):
    """Check SMS configuration status for a tournament."""
    _get_tournament_or_404(session, tournament_id)
    twilio = get_twilio_service()

    teams = _get_all_teams_for_tournament(session, tournament_id)
    teams_with_phones = sum(1 for t in teams if get_team_phone_numbers(t))

    settings = session.exec(
        select(TournamentSmsSettings).where(
            TournamentSmsSettings.tournament_id == tournament_id
        )
    ).first()

    return SmsStatusResponse(
        twilio_configured=twilio.is_configured,
        from_number=twilio.from_number if twilio.is_configured else None,
        tournament_has_settings=settings is not None,
        total_teams=len(teams),
        teams_with_phones=teams_with_phones,
    )


# ---------------------------------------------------------------------------
# Send endpoints
# ---------------------------------------------------------------------------


@router.post("/blast", response_model=SmsSendResponse)
def send_tournament_blast(
    tournament_id: int,
    body: SmsSendRequest,
    session: Session = Depends(get_session),
):
    """Text all teams in the tournament."""
    _get_tournament_or_404(session, tournament_id)
    teams = _get_all_teams_for_tournament(session, tournament_id)
    if not teams:
        raise HTTPException(400, "No teams found in this tournament")

    return _send_to_teams(
        session=session,
        tournament_id=tournament_id,
        teams=teams,
        message=body.message,
        message_type="tournament_blast",
        trigger="manual",
    )


@router.post("/team/{team_id}", response_model=SmsSendResponse)
def send_team_text(
    tournament_id: int,
    team_id: int,
    body: SmsSendRequest,
    session: Session = Depends(get_session),
):
    """Text a specific team."""
    _get_tournament_or_404(session, tournament_id)
    team = session.get(Team, team_id)
    if not team:
        raise HTTPException(404, f"Team {team_id} not found")

    phones = get_team_phone_numbers(team)
    if not phones:
        raise HTTPException(
            400,
            f"Team '{team.name}' has no phone numbers on file",
        )

    return _send_to_teams(
        session=session,
        tournament_id=tournament_id,
        teams=[team],
        message=body.message,
        message_type="team_direct",
        trigger="manual",
    )


@router.post("/match/{match_id}", response_model=SmsSendResponse)
def send_match_text(
    tournament_id: int,
    match_id: int,
    body: SmsSendRequest,
    session: Session = Depends(get_session),
):
    """Text both teams in a specific match."""
    _get_tournament_or_404(session, tournament_id)
    match = session.get(Match, match_id)
    if not match:
        raise HTTPException(404, f"Match {match_id} not found")

    teams = []
    if match.team_a_id:
        team_a = session.get(Team, match.team_a_id)
        if team_a:
            teams.append(team_a)
    if match.team_b_id:
        team_b = session.get(Team, match.team_b_id)
        if team_b:
            teams.append(team_b)

    if not teams:
        raise HTTPException(
            400,
            "No teams assigned to this match yet (team IDs are null)",
        )

    return _send_to_teams(
        session=session,
        tournament_id=tournament_id,
        teams=teams,
        message=body.message,
        message_type="match_specific",
        trigger="manual",
    )


@router.post("/timeslot", response_model=SmsSendResponse)
def send_timeslot_text(
    tournament_id: int,
    body: SmsTimeslotRequest,
    session: Session = Depends(get_session),
):
    """Text all teams playing in a specific time slot."""
    _get_tournament_or_404(session, tournament_id)

    # Find slots matching day + time
    slots = session.exec(
        select(ScheduleSlot).where(
            ScheduleSlot.schedule_version_id == body.schedule_version_id,
            ScheduleSlot.day_date == body.day_date,
        )
    ).all()

    # Filter by start_time (handle both "10:00" and "10:00:00")
    target_time = body.start_time
    matching_slots = [
        s
        for s in slots
        if str(s.start_time).startswith(target_time)
    ]

    if not matching_slots:
        raise HTTPException(
            404,
            f"No slots found for {body.day_date} at {body.start_time}",
        )

    slot_ids = [s.id for s in matching_slots]

    # Find assignments for those slots
    assignments = session.exec(
        select(MatchAssignment).where(
            MatchAssignment.slot_id.in_(slot_ids)  # type: ignore
        )
    ).all()

    if not assignments:
        raise HTTPException(
            400,
            f"No matches assigned to slots at {body.day_date} {body.start_time}",
        )

    # Collect unique teams from those matches
    match_ids = [a.match_id for a in assignments]
    matches = session.exec(
        select(Match).where(Match.id.in_(match_ids))  # type: ignore
    ).all()

    team_ids = set()
    for m in matches:
        if m.team_a_id:
            team_ids.add(m.team_a_id)
        if m.team_b_id:
            team_ids.add(m.team_b_id)

    if not team_ids:
        raise HTTPException(400, "No teams assigned to matches in this time slot")

    teams = session.exec(
        select(Team).where(Team.id.in_(team_ids))  # type: ignore
    ).all()

    return _send_to_teams(
        session=session,
        tournament_id=tournament_id,
        teams=list(teams),
        message=body.message,
        message_type="time_slot_blast",
        trigger="manual",
    )


# ---------------------------------------------------------------------------
# Preview endpoint (dry-run)
# ---------------------------------------------------------------------------


@router.post("/preview/blast", response_model=SmsPreviewResponse)
def preview_blast(
    tournament_id: int,
    body: SmsSendRequest,
    session: Session = Depends(get_session),
):
    """Preview who would receive a tournament blast (no texts sent)."""
    _get_tournament_or_404(session, tournament_id)
    teams = _get_all_teams_for_tournament(session, tournament_id)

    recipients = []
    teams_without = 0
    total_messages = 0

    for team in teams:
        phones = get_team_phone_numbers(team)
        if not phones:
            teams_without += 1
            continue
        total_messages += len(phones)
        recipients.append(
            SmsPreviewRecipient(
                team_id=team.id,
                team_name=team.name,
                phones=phones,
                message=body.message,
            )
        )

    return SmsPreviewResponse(
        total_teams=len(teams),
        total_messages=total_messages,
        teams_without_phone=teams_without,
        recipients=recipients,
    )


# ---------------------------------------------------------------------------
# Log endpoint
# ---------------------------------------------------------------------------


@router.get("/log", response_model=List[SmsLogResponse])
def get_sms_log(
    tournament_id: int,
    limit: int = Query(default=100, le=500),
    message_type: Optional[str] = Query(default=None),
    session: Session = Depends(get_session),
):
    """View SMS send history for a tournament."""
    _get_tournament_or_404(session, tournament_id)

    query = select(SmsLog).where(SmsLog.tournament_id == tournament_id)
    if message_type:
        query = query.where(SmsLog.message_type == message_type)
    query = query.order_by(SmsLog.sent_at.desc()).limit(limit)  # type: ignore

    logs = session.exec(query).all()
    return logs


# ---------------------------------------------------------------------------
# Settings endpoints
# ---------------------------------------------------------------------------


@router.get("/settings", response_model=SmsSettingsResponse)
def get_sms_settings(
    tournament_id: int,
    session: Session = Depends(get_session),
):
    """Get SMS auto-text settings for a tournament."""
    _get_tournament_or_404(session, tournament_id)

    settings = session.exec(
        select(TournamentSmsSettings).where(
            TournamentSmsSettings.tournament_id == tournament_id
        )
    ).first()

    if not settings:
        # Return defaults (not persisted yet)
        return SmsSettingsResponse(
            tournament_id=tournament_id,
            auto_first_match=False,
            auto_post_match_next=False,
            auto_on_deck=False,
            auto_up_next=False,
            auto_court_change=True,
        )

    return settings


@router.patch("/settings", response_model=SmsSettingsResponse)
def update_sms_settings(
    tournament_id: int,
    body: SmsSettingsUpdate,
    session: Session = Depends(get_session),
):
    """Update SMS auto-text settings for a tournament."""
    _get_tournament_or_404(session, tournament_id)

    settings = session.exec(
        select(TournamentSmsSettings).where(
            TournamentSmsSettings.tournament_id == tournament_id
        )
    ).first()

    if not settings:
        # Create with defaults, then apply updates
        settings = TournamentSmsSettings(tournament_id=tournament_id)

    # Apply only provided fields
    update_data = body.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(settings, key, value)
    settings.updated_at = datetime.now(timezone.utc)

    session.add(settings)
    session.commit()
    session.refresh(settings)
    return settings


# ---------------------------------------------------------------------------
# Template endpoints
# ---------------------------------------------------------------------------


@router.get("/templates", response_model=List[SmsTemplateResponse])
def get_sms_templates(
    tournament_id: int,
    session: Session = Depends(get_session),
):
    """
    Get all SMS templates for a tournament.

    Returns custom templates if they exist, otherwise returns defaults.
    """
    _get_tournament_or_404(session, tournament_id)

    templates = session.exec(
        select(SmsTemplate).where(SmsTemplate.tournament_id == tournament_id)
    ).all()

    # If no custom templates, return defaults as response objects
    if not templates:
        result = []
        for msg_type, body in DEFAULT_SMS_TEMPLATES.items():
            result.append(
                SmsTemplateResponse(
                    id=0,  # Indicates default (not persisted)
                    tournament_id=tournament_id,
                    message_type=msg_type,
                    template_body=body,
                    is_active=True,
                )
            )
        return result

    return templates


@router.put("/templates/{message_type}", response_model=SmsTemplateResponse)
def update_sms_template(
    tournament_id: int,
    message_type: str,
    body: SmsTemplateUpdate,
    session: Session = Depends(get_session),
):
    """Create or update an SMS template for a specific message type."""
    _get_tournament_or_404(session, tournament_id)

    # Validate message_type
    valid_types = list(DEFAULT_SMS_TEMPLATES.keys())
    if message_type not in valid_types:
        raise HTTPException(
            400,
            f"Invalid message_type '{message_type}'. "
            f"Must be one of: {', '.join(valid_types)}",
        )

    template = session.exec(
        select(SmsTemplate).where(
            SmsTemplate.tournament_id == tournament_id,
            SmsTemplate.message_type == message_type,
        )
    ).first()

    if template:
        template.template_body = body.template_body
        if body.is_active is not None:
            template.is_active = body.is_active
        template.updated_at = datetime.now(timezone.utc)
    else:
        template = SmsTemplate(
            tournament_id=tournament_id,
            message_type=message_type,
            template_body=body.template_body,
            is_active=body.is_active if body.is_active is not None else True,
        )

    session.add(template)
    session.commit()
    session.refresh(template)
    return template


@router.post("/templates/reset")
def reset_sms_templates(
    tournament_id: int,
    session: Session = Depends(get_session),
):
    """Reset all templates to defaults (deletes custom templates)."""
    _get_tournament_or_404(session, tournament_id)

    templates = session.exec(
        select(SmsTemplate).where(SmsTemplate.tournament_id == tournament_id)
    ).all()
    for t in templates:
        session.delete(t)
    session.commit()

    return {"deleted": len(templates), "message": "Templates reset to defaults"}
