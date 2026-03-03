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
from urllib.parse import parse_qsl

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict
from sqlmodel import Session, select

from app.database import get_session
from app.models.event import Event, EventCategory
from app.models.match import Match
from app.models.match_assignment import MatchAssignment
from app.models.player import Player
from app.models.schedule_slot import ScheduleSlot
from app.models.sms_consent_event import SmsConsentEvent
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
    player_id: Optional[int] = None
    player_name: Optional[str] = None
    status: str  # queued|sent|dry_run|failed
    error: Optional[str] = None


class SmsSendResponse(BaseModel):
    """Response from any send endpoint."""

    total: int
    sent: int
    failed: int
    skipped_no_phone: int
    skipped_consent: int = 0
    skipped_dedupe: int = 0
    message_type: str
    results: List[SmsSendResult]


class SmsPreviewRecipient(BaseModel):
    """Preview of who would receive a text."""

    team_id: Optional[int] = None
    team_name: Optional[str] = None
    player_id: Optional[int] = None
    player_name: Optional[str] = None
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
    dedupe_key: Optional[str] = None
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
    dedupe_key: Optional[str] = None


class SmsTimeslotRequest(BaseModel):
    """Request body for timeslot send."""

    message: str
    day_date: str  # "2026-03-15"
    start_time: str  # "10:00" or "10:00:00"
    schedule_version_id: int
    dedupe_key: Optional[str] = None


class SmsStatusResponse(BaseModel):
    """Quick status check for SMS configuration."""

    twilio_configured: bool
    from_number: Optional[str] = None
    tournament_has_settings: bool
    total_teams: int
    teams_with_phones: int


class SmsWebhookResponse(BaseModel):
    """Response for inbound Twilio webhook processing."""

    ok: bool
    deduped: bool = False
    event_type: str
    phone_number: str
    player_id: Optional[int] = None


class SmsStatusCallbackResponse(BaseModel):
    """Response for Twilio delivery status callback processing."""

    ok: bool
    updated: bool


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


def _is_phone_send_allowed(
    session: Session,
    tournament_id: int,
    phone_e164: str,
) -> tuple[bool, str]:
    """
    Determine if SMS can be sent to a phone number.

    Backward-compatible policy:
    - If no Player record exists for the phone, allow send (legacy team-phone flow).
    - If Player exists with opted_out status, block send.
    - Otherwise allow send.
    """
    player = session.exec(
        select(Player).where(
            Player.tournament_id == tournament_id,
            Player.phone_e164 == phone_e164,
        )
    ).first()
    if not player:
        return True, "unknown"

    consent = (player.sms_consent_status or "unknown").lower()
    if consent == "opted_out":
        return False, consent
    return True, consent


def _validate_twilio_signature(
    request: Request,
    form_values: dict[str, str],
) -> None:
    """
    Validate X-Twilio-Signature when auth token is configured.

    In local/test mode without Twilio auth token configured, validation is skipped.
    """
    twilio = get_twilio_service()
    auth_token = twilio.auth_token
    if not auth_token:
        return

    signature = request.headers.get("X-Twilio-Signature")
    if not signature:
        raise HTTPException(403, "Missing Twilio signature")

    try:
        from twilio.request_validator import RequestValidator

        validator = RequestValidator(auth_token)
        is_valid = validator.validate(
            str(request.url),
            form_values,
            signature,
        )
    except Exception as exc:
        logger.exception("Twilio signature verification error: %s", exc)
        raise HTTPException(403, "Invalid Twilio signature")

    if not is_valid:
        raise HTTPException(403, "Invalid Twilio signature")


async def _parse_twilio_form(request: Request) -> dict[str, str]:
    """
    Parse x-www-form-urlencoded Twilio webhook payload without python-multipart.
    """
    raw_body = (await request.body()).decode("utf-8")
    return {k: v for k, v in parse_qsl(raw_body, keep_blank_values=True)}


_STOP_KEYWORDS = {"STOP", "STOPALL", "UNSUBSCRIBE", "CANCEL", "END", "QUIT"}
_START_KEYWORDS = {"START", "UNSTOP"}
_HELP_KEYWORDS = {"HELP"}


def _send_to_phone_targets(
    session: Session,
    tournament_id: int,
    targets: List[dict],
    message: str,
    message_type: str,
    trigger: str = "manual",
    dedupe_key: Optional[str] = None,
    skipped_no_phone: int = 0,
) -> SmsSendResponse:
    """Send to explicit phone targets with consent + dedupe protections."""
    twilio = get_twilio_service()
    results: List[SmsSendResult] = []
    sent_count = 0
    failed_count = 0
    skipped_consent_count = 0
    skipped_dedupe_count = 0

    for target in targets:
        phone = target["phone"]
        team_id = target.get("team_id")
        team_name = target.get("team_name")
        player_id = target.get("player_id")
        player_name = target.get("player_name")

        if dedupe_key:
            existing = session.exec(
                select(SmsLog.id).where(
                    SmsLog.tournament_id == tournament_id,
                    SmsLog.phone_number == phone,
                    SmsLog.message_type == message_type,
                    SmsLog.dedupe_key == dedupe_key,
                )
            ).first()
            if existing:
                skipped_dedupe_count += 1
                results.append(
                    SmsSendResult(
                        phone=phone,
                        team_id=team_id,
                        team_name=team_name,
                        player_id=player_id,
                        player_name=player_name,
                        status="deduped",
                        error=f"Skipped duplicate send for dedupe_key={dedupe_key}",
                    )
                )
                continue

        is_allowed, consent_state = _is_phone_send_allowed(
            session=session,
            tournament_id=tournament_id,
            phone_e164=phone,
        )
        if not is_allowed:
            skipped_consent_count += 1
            blocked_reason = "Recipient has opted out of SMS for this tournament"
            session.add(
                SmsLog(
                    tournament_id=tournament_id,
                    team_id=team_id,
                    phone_number=phone,
                    message_body=message,
                    message_type=message_type,
                    twilio_sid=None,
                    status="blocked_consent",
                    error_message=blocked_reason,
                    trigger=trigger,
                    dedupe_key=dedupe_key,
                    sent_at=datetime.now(timezone.utc),
                )
            )
            results.append(
                SmsSendResult(
                    phone=phone,
                    team_id=team_id,
                    team_name=team_name,
                    player_id=player_id,
                    player_name=player_name,
                    status="blocked_consent",
                    error=f"{blocked_reason} (state={consent_state})",
                )
            )
            continue

        send_result = twilio.send_sms(phone, message)
        status = send_result.get("status", "failed")
        if status in ("queued", "sent", "dry_run"):
            sent_count += 1
        else:
            failed_count += 1

        session.add(
            SmsLog(
                tournament_id=tournament_id,
                team_id=team_id,
                phone_number=phone,
                message_body=message,
                message_type=message_type,
                twilio_sid=send_result.get("sid"),
                status=status,
                error_message=send_result.get("error"),
                trigger=trigger,
                dedupe_key=dedupe_key,
                sent_at=datetime.now(timezone.utc),
            )
        )
        results.append(
            SmsSendResult(
                phone=phone,
                team_id=team_id,
                team_name=team_name,
                player_id=player_id,
                player_name=player_name,
                status=status,
                error=send_result.get("error"),
            )
        )

    session.commit()
    return SmsSendResponse(
        total=len(results),
        sent=sent_count,
        failed=failed_count,
        skipped_no_phone=skipped_no_phone,
        skipped_consent=skipped_consent_count,
        skipped_dedupe=skipped_dedupe_count,
        message_type=message_type,
        results=results,
    )


def _send_to_teams(
    session: Session,
    tournament_id: int,
    teams: List[Team],
    message: str,
    message_type: str,
    trigger: str = "manual",
    dedupe_key: Optional[str] = None,
) -> SmsSendResponse:
    """Send to all phone numbers found on a team list."""
    targets: List[dict] = []
    skipped_no_phone = 0
    for team in teams:
        phones = get_team_phone_numbers(team)
        if not phones:
            skipped_no_phone += 1
            continue
        for phone in phones:
            targets.append(
                {
                    "phone": phone,
                    "team_id": team.id,
                    "team_name": team.name,
                    "player_id": None,
                    "player_name": None,
                }
            )

    return _send_to_phone_targets(
        session=session,
        tournament_id=tournament_id,
        targets=targets,
        message=message,
        message_type=message_type,
        trigger=trigger,
        dedupe_key=dedupe_key,
        skipped_no_phone=skipped_no_phone,
    )


def _get_teams_for_event(
    session: Session,
    tournament_id: int,
    event_id: int,
) -> List[Team]:
    event = session.get(Event, event_id)
    if not event or event.tournament_id != tournament_id:
        raise HTTPException(404, f"Event {event_id} not found in tournament")

    teams = session.exec(
        select(Team).where(Team.event_id == event_id)
    ).all()
    return list(teams)


def _get_teams_for_division(
    session: Session,
    tournament_id: int,
    division: str,
) -> List[Team]:
    division_norm = division.strip().lower()
    valid_divisions = {c.value for c in EventCategory}
    if division_norm not in valid_divisions:
        raise HTTPException(
            400,
            f"Invalid division '{division}'. Must be one of: {', '.join(sorted(valid_divisions))}",
        )

    events = session.exec(
        select(Event).where(
            Event.tournament_id == tournament_id,
            Event.category == division_norm,
        )
    ).all()
    event_ids = [e.id for e in events]
    if not event_ids:
        return []

    teams = session.exec(
        select(Team).where(Team.event_id.in_(event_ids))  # type: ignore
    ).all()
    return list(teams)


def _preview_for_teams(
    teams: List[Team],
    message: str,
) -> SmsPreviewResponse:
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
                message=message,
            )
        )

    return SmsPreviewResponse(
        total_teams=len(teams),
        total_messages=total_messages,
        teams_without_phone=teams_without,
        recipients=recipients,
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
# Twilio webhook endpoints (inbound + delivery status)
# ---------------------------------------------------------------------------


@router.post("/webhook/inbound", response_model=SmsWebhookResponse)
async def handle_inbound_webhook(
    tournament_id: int,
    request: Request,
    session: Session = Depends(get_session),
):
    """
    Handle inbound SMS (STOP/START/HELP) and persist consent transitions.
    """
    _get_tournament_or_404(session, tournament_id)
    form_data = await _parse_twilio_form(request)
    _validate_twilio_signature(request, form_data)

    from_raw = form_data.get("From", "").strip()
    if not from_raw:
        raise HTTPException(400, "Missing From phone number")

    try:
        from_phone = format_e164(from_raw)
    except ValueError as exc:
        raise HTTPException(400, f"Invalid From phone number: {exc}")

    body = (form_data.get("Body") or "").strip()
    first_word = body.split()[0].upper() if body else ""
    message_sid = form_data.get("MessageSid")
    dedupe_key = f"inbound:{message_sid}" if message_sid else None

    if dedupe_key:
        existing = session.exec(
            select(SmsConsentEvent).where(
                SmsConsentEvent.tournament_id == tournament_id,
                SmsConsentEvent.dedupe_key == dedupe_key,
            )
        ).first()
        if existing:
            return SmsWebhookResponse(
                ok=True,
                deduped=True,
                event_type=existing.event_type,
                phone_number=from_phone,
                player_id=existing.player_id,
            )

    if first_word in _STOP_KEYWORDS:
        event_type = "opted_out"
        new_status = "opted_out"
    elif first_word in _START_KEYWORDS:
        event_type = "opted_in"
        new_status = "opted_in"
    elif first_word in _HELP_KEYWORDS:
        event_type = "help"
        new_status = None
    else:
        event_type = "other"
        new_status = None

    player = session.exec(
        select(Player).where(
            Player.tournament_id == tournament_id,
            Player.phone_e164 == from_phone,
        )
    ).first()

    if not player and new_status is not None:
        player = Player(
            tournament_id=tournament_id,
            full_name=f"Unknown ({from_phone})",
            phone_e164=from_phone,
            sms_consent_status="unknown",
        )
        session.add(player)
        session.flush()

    if player and new_status is not None:
        now_utc = datetime.now(timezone.utc)
        player.sms_consent_status = new_status
        player.sms_consent_source = "twilio_webhook"
        player.sms_consent_updated_at = now_utc
        player.updated_at = now_utc
        if new_status == "opted_in":
            player.sms_consented_at = now_utc
            player.sms_opted_out_at = None
        elif new_status == "opted_out":
            player.sms_opted_out_at = now_utc
        session.add(player)

    consent_event = SmsConsentEvent(
        tournament_id=tournament_id,
        player_id=player.id if player else None,
        phone_number=from_phone,
        event_type=event_type,
        source="twilio_webhook",
        message_text=body or None,
        provider_message_sid=message_sid,
        dedupe_key=dedupe_key,
        occurred_at=datetime.now(timezone.utc),
    )
    session.add(consent_event)
    session.commit()

    return SmsWebhookResponse(
        ok=True,
        deduped=False,
        event_type=event_type,
        phone_number=from_phone,
        player_id=player.id if player else None,
    )


@router.post(
    "/webhook/status-callback",
    response_model=SmsStatusCallbackResponse,
)
async def handle_status_callback(
    tournament_id: int,
    request: Request,
    session: Session = Depends(get_session),
):
    """Handle Twilio delivery status callbacks and update sms_log status."""
    _get_tournament_or_404(session, tournament_id)
    form_data = await _parse_twilio_form(request)
    _validate_twilio_signature(request, form_data)

    message_sid = (form_data.get("MessageSid") or "").strip()
    message_status = (form_data.get("MessageStatus") or "").strip()
    if not message_sid or not message_status:
        raise HTTPException(400, "Missing MessageSid or MessageStatus")

    log_entry = session.exec(
        select(SmsLog)
        .where(
            SmsLog.tournament_id == tournament_id,
            SmsLog.twilio_sid == message_sid,
        )
        .order_by(SmsLog.id.desc())
    ).first()

    if not log_entry:
        return SmsStatusCallbackResponse(ok=True, updated=False)

    log_entry.status = message_status
    err_code = (form_data.get("ErrorCode") or "").strip()
    err_message = (form_data.get("ErrorMessage") or "").strip()
    if err_code or err_message:
        if err_code and err_message:
            log_entry.error_message = f"Twilio {err_code}: {err_message}"
        elif err_code:
            log_entry.error_message = f"Twilio {err_code}"
        else:
            log_entry.error_message = err_message
    session.add(log_entry)
    session.commit()

    return SmsStatusCallbackResponse(ok=True, updated=True)


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
        dedupe_key=body.dedupe_key,
    )


@router.post("/event/{event_id}", response_model=SmsSendResponse)
def send_event_text(
    tournament_id: int,
    event_id: int,
    body: SmsSendRequest,
    session: Session = Depends(get_session),
):
    """Text all teams in a specific event."""
    _get_tournament_or_404(session, tournament_id)
    teams = _get_teams_for_event(session, tournament_id, event_id)
    if not teams:
        raise HTTPException(400, "No teams found in this event")

    return _send_to_teams(
        session=session,
        tournament_id=tournament_id,
        teams=teams,
        message=body.message,
        message_type="event_blast",
        trigger="manual",
        dedupe_key=body.dedupe_key,
    )


@router.post("/division/{division}", response_model=SmsSendResponse)
def send_division_text(
    tournament_id: int,
    division: str,
    body: SmsSendRequest,
    session: Session = Depends(get_session),
):
    """
    Text all teams in a division.

    Division currently maps to Event.category values (mixed|womens).
    """
    _get_tournament_or_404(session, tournament_id)
    teams = _get_teams_for_division(session, tournament_id, division)
    if not teams:
        raise HTTPException(400, f"No teams found in division '{division}'")

    return _send_to_teams(
        session=session,
        tournament_id=tournament_id,
        teams=teams,
        message=body.message,
        message_type="division_blast",
        trigger="manual",
        dedupe_key=body.dedupe_key,
    )


@router.post("/player/{player_id}", response_model=SmsSendResponse)
def send_player_text(
    tournament_id: int,
    player_id: int,
    body: SmsSendRequest,
    session: Session = Depends(get_session),
):
    """Text a specific player by Player ID."""
    _get_tournament_or_404(session, tournament_id)
    player = session.get(Player, player_id)
    if not player or player.tournament_id != tournament_id:
        raise HTTPException(404, f"Player {player_id} not found in tournament")
    if not player.phone_e164:
        raise HTTPException(400, "Player has no phone_e164 on file")

    try:
        phone = format_e164(player.phone_e164)
    except ValueError as exc:
        raise HTTPException(400, f"Player phone is invalid: {exc}")

    targets = [
        {
            "phone": phone,
            "team_id": None,
            "team_name": None,
            "player_id": player.id,
            "player_name": player.display_name or player.full_name,
        }
    ]
    return _send_to_phone_targets(
        session=session,
        tournament_id=tournament_id,
        targets=targets,
        message=body.message,
        message_type="player_direct",
        trigger="manual",
        dedupe_key=body.dedupe_key,
        skipped_no_phone=0,
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
        dedupe_key=body.dedupe_key,
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
        dedupe_key=body.dedupe_key,
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
        dedupe_key=body.dedupe_key,
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
    return _preview_for_teams(teams=teams, message=body.message)


@router.post("/preview/event/{event_id}", response_model=SmsPreviewResponse)
def preview_event(
    tournament_id: int,
    event_id: int,
    body: SmsSendRequest,
    session: Session = Depends(get_session),
):
    """Preview recipients for an event-wide send."""
    _get_tournament_or_404(session, tournament_id)
    teams = _get_teams_for_event(session, tournament_id, event_id)
    return _preview_for_teams(teams=teams, message=body.message)


@router.post("/preview/division/{division}", response_model=SmsPreviewResponse)
def preview_division(
    tournament_id: int,
    division: str,
    body: SmsSendRequest,
    session: Session = Depends(get_session),
):
    """Preview recipients for a division-wide send."""
    _get_tournament_or_404(session, tournament_id)
    teams = _get_teams_for_division(session, tournament_id, division)
    return _preview_for_teams(teams=teams, message=body.message)


@router.post("/preview/player/{player_id}", response_model=SmsPreviewResponse)
def preview_player(
    tournament_id: int,
    player_id: int,
    body: SmsSendRequest,
    session: Session = Depends(get_session),
):
    """Preview recipient for a player-specific send."""
    _get_tournament_or_404(session, tournament_id)
    player = session.get(Player, player_id)
    if not player or player.tournament_id != tournament_id:
        raise HTTPException(404, f"Player {player_id} not found in tournament")

    phones: List[str] = []
    if player.phone_e164:
        try:
            phones.append(format_e164(player.phone_e164))
        except ValueError:
            phones = []

    recipients = []
    if phones:
        recipients.append(
            SmsPreviewRecipient(
                team_id=None,
                team_name=None,
                player_id=player.id,
                player_name=player.display_name or player.full_name,
                phones=phones,
                message=body.message,
            )
        )

    return SmsPreviewResponse(
        total_teams=1,
        total_messages=len(phones),
        teams_without_phone=0 if phones else 1,
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
