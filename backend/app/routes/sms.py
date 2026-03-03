"""SMS routes for tournament texting.

Provides endpoints for:
- Sending texts (blast, team, match, timeslot)
- Viewing send history (log)
- Managing templates
- Managing auto-text settings
"""

import logging
import re
from datetime import datetime, timezone
from typing import List, Optional
from urllib.parse import parse_qsl

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict
from sqlmodel import Session, select

from app.database import get_session
from app.models.event import Event
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
    skipped_test_mode: int = 0
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
    test_mode: bool
    test_allowlist: Optional[str] = None


class SmsSettingsUpdate(BaseModel):
    """Update request for SMS settings."""

    auto_first_match: Optional[bool] = None
    auto_post_match_next: Optional[bool] = None
    auto_on_deck: Optional[bool] = None
    auto_up_next: Optional[bool] = None
    auto_court_change: Optional[bool] = None
    test_mode: Optional[bool] = None
    test_allowlist: Optional[str] = None


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


class SmsPlayerLookupItem(BaseModel):
    """Lookup row for selecting a player target in UI."""

    player_id: int
    player_name: str
    phone_e164: Optional[str] = None
    consent_status: str


class SmsMatchLookupItem(BaseModel):
    """Lookup row for selecting a match target in UI."""

    match_id: int
    match_code: str
    event_name: str
    team_a_name: str
    team_b_name: str
    runtime_status: str
    phase: str  # upcoming|completed
    day_date: Optional[str] = None
    start_time: Optional[str] = None
    display_label: str


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


def _normalize_allowlist_text(raw: Optional[str]) -> str:
    """Normalize CSV/newline-separated phone list to canonical E.164 CSV."""
    if not raw or not raw.strip():
        return ""

    token_source = re.sub(r"[;\n]+", ",", raw)
    tokens = [t.strip() for t in token_source.split(",") if t.strip()]
    normalized: List[str] = []
    seen = set()
    invalid: List[str] = []
    for token in tokens:
        try:
            phone = format_e164(token)
        except ValueError:
            invalid.append(token)
            continue
        if phone not in seen:
            normalized.append(phone)
            seen.add(phone)

    if invalid:
        raise HTTPException(
            400,
            f"Invalid phone(s) in test_allowlist: {', '.join(invalid)}",
        )
    return ",".join(normalized)


def _allowlist_set(raw: Optional[str]) -> set[str]:
    if not raw:
        return set()
    return {p.strip() for p in raw.split(",") if p.strip()}


def _normalize_match_key(value: str) -> str:
    """Case-insensitive, punctuation-insensitive normalization for matching."""
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def _event_category_text(event: Event) -> str:
    category = event.category
    if hasattr(category, "value"):
        return str(category.value)
    return str(category)


def _event_lookup_keys(event: Event) -> set[str]:
    """Build normalized keys that may identify an event as a 'division'."""
    category = _event_category_text(event)
    category_label = "women's" if category == "womens" else "mixed"
    name = (event.name or "").strip()
    keys = {
        _normalize_match_key(name),
        _normalize_match_key(f"{category} {name}"),
        _normalize_match_key(f"{category_label} {name}"),
    }
    return {k for k in keys if k}


def _normalize_team_phone(raw: Optional[str]) -> Optional[str]:
    if raw is None:
        return None
    value = str(raw).strip()
    if not value:
        return None
    if value in {"—", "-", "N/A", "n/a", "none", "None"}:
        return None
    try:
        return format_e164(value)
    except ValueError:
        return None


def _team_slot_phone(team: Team, slot: int) -> Optional[str]:
    if slot == 1:
        return (
            _normalize_team_phone(getattr(team, "player1_cellphone", None))
            or _normalize_team_phone(getattr(team, "p1_cell", None))
        )
    return (
        _normalize_team_phone(getattr(team, "player2_cellphone", None))
        or _normalize_team_phone(getattr(team, "p2_cell", None))
    )


def _team_player_names(team: Team) -> tuple[str, str]:
    source = (
        (getattr(team, "display_name", None) or "").strip()
        or (getattr(team, "name", None) or "").strip()
    )
    if not source:
        fallback = f"Team {getattr(team, 'id', 'Unknown')}"
        return (f"{fallback} Player 1", f"{fallback} Player 2")

    if "/" in source:
        parts = [p.strip() for p in source.split("/") if p.strip()]
    elif "&" in source:
        parts = [p.strip() for p in source.split("&") if p.strip()]
    else:
        parts = [source]

    if len(parts) == 1:
        p1 = parts[0]
        p2 = f"{parts[0]} (P2)"
    else:
        p1 = parts[0]
        p2 = parts[1]
    return (p1, p2)


def _match_is_completed(match: Match) -> bool:
    runtime = (match.runtime_status or "").upper()
    status = (match.status or "").lower()
    return runtime == "FINAL" or status in {"complete", "completed"}


def _team_name_for_lookup(team: Optional[Team], placeholder: Optional[str]) -> str:
    if team:
        return (team.display_name or team.name or f"Team {team.id}").strip()
    if placeholder and placeholder.strip():
        return placeholder.strip()
    return "TBD"


def _get_match_teams_for_tournament(
    session: Session,
    tournament_id: int,
    match_id: int,
) -> tuple[Match, List[Team]]:
    """Get a match + assigned teams, ensuring it belongs to tournament."""
    match = session.get(Match, match_id)
    if not match or match.tournament_id != tournament_id:
        raise HTTPException(404, f"Match {match_id} not found in tournament")

    teams: List[Team] = []
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
    return match, teams


def _settings_to_response(
    tournament_id: int,
    settings: Optional[TournamentSmsSettings],
) -> SmsSettingsResponse:
    if not settings:
        return SmsSettingsResponse(
            tournament_id=tournament_id,
            auto_first_match=False,
            auto_post_match_next=False,
            auto_on_deck=False,
            auto_up_next=False,
            auto_court_change=True,
            test_mode=False,
            test_allowlist=None,
        )
    return SmsSettingsResponse(
        tournament_id=settings.tournament_id,
        auto_first_match=settings.auto_first_match,
        auto_post_match_next=settings.auto_post_match_next,
        auto_on_deck=settings.auto_on_deck,
        auto_up_next=settings.auto_up_next,
        auto_court_change=settings.auto_court_change,
        test_mode=bool(getattr(settings, "test_mode", False)),
        test_allowlist=getattr(settings, "test_allowlist", None),
    )


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
    settings = session.exec(
        select(TournamentSmsSettings).where(
            TournamentSmsSettings.tournament_id == tournament_id
        )
    ).first()
    test_mode_enabled = bool(settings and getattr(settings, "test_mode", False))
    test_allowlist = _allowlist_set(
        getattr(settings, "test_allowlist", None) if settings else None
    )

    results: List[SmsSendResult] = []
    sent_count = 0
    failed_count = 0
    skipped_consent_count = 0
    skipped_dedupe_count = 0
    skipped_test_mode_count = 0

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

        if test_mode_enabled and phone not in test_allowlist:
            skipped_test_mode_count += 1
            blocked_reason = (
                "Test mode enabled: recipient not in test_allowlist"
            )
            session.add(
                SmsLog(
                    tournament_id=tournament_id,
                    team_id=team_id,
                    phone_number=phone,
                    message_body=message,
                    message_type=message_type,
                    twilio_sid=None,
                    status="blocked_test_mode",
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
                    status="blocked_test_mode",
                    error=blocked_reason,
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
        skipped_test_mode=skipped_test_mode_count,
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
    raw = division.strip()
    division_norm = _normalize_match_key(raw)

    events = session.exec(
        select(Event).where(Event.tournament_id == tournament_id)
    ).all()
    if not events:
        return []

    # Backward-compatible category matching ("mixed" / "womens")
    category_aliases = {
        "mixed": "mixed",
        "womens": "womens",
        "women": "womens",
        "women s": "womens",
        "women's": "womens",
    }
    category_match = category_aliases.get(division_norm)

    matched_event_ids: List[int] = []
    if category_match:
        matched_event_ids = [
            e.id for e in events if _event_category_text(e) == category_match
        ]
    else:
        matched_event_ids = [
            e.id for e in events if division_norm in _event_lookup_keys(e)
        ]

    if not matched_event_ids:
        valid_divisions = sorted(
            {
                _event_category_text(e)
                for e in events
            }
        )
        sample_named = sorted(
            {
                (("Women's" if _event_category_text(e) == "womens" else "Mixed") + f" {e.name}").strip()
                for e in events
            }
        )
        raise HTTPException(
            400,
            "Invalid division '{division}'. Must be one of: {valid}. "
            "Or an event-style division label like: {example}".format(
                division=division,
                valid=", ".join(valid_divisions),
                example=", ".join(sample_named[:6]),
            ),
        )

    teams = session.exec(
        select(Team).where(Team.event_id.in_(matched_event_ids))  # type: ignore
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


@router.get("/players", response_model=List[SmsPlayerLookupItem])
def get_sms_players(
    tournament_id: int,
    session: Session = Depends(get_session),
):
    """List known players for player-target lookup in SMS UI.

    If Player rows are missing (legacy team-only records), this endpoint
    auto-provisions players from team phone slots for reliable player search.
    """
    _get_tournament_or_404(session, tournament_id)
    rows = session.exec(
        select(Player).where(Player.tournament_id == tournament_id)
    ).all()

    players = list(rows)
    players_by_phone: dict[str, Player] = {
        p.phone_e164: p
        for p in players
        if p.phone_e164
    }

    teams = _get_all_teams_for_tournament(session, tournament_id)
    changed = False
    for team in teams:
        p1_name, p2_name = _team_player_names(team)
        for slot, player_name, phone_e164 in (
            (1, p1_name, _team_slot_phone(team, 1)),
            (2, p2_name, _team_slot_phone(team, 2)),
        ):
            if not phone_e164:
                continue

            existing = players_by_phone.get(phone_e164)
            if existing:
                if existing.full_name.startswith("Unknown (") and player_name:
                    existing.full_name = player_name
                    if not existing.display_name:
                        existing.display_name = player_name
                    existing.updated_at = datetime.now(timezone.utc)
                    session.add(existing)
                    changed = True
                continue

            created = Player(
                tournament_id=tournament_id,
                full_name=player_name or f"Team {team.id} Player {slot}",
                display_name=player_name or None,
                phone_e164=phone_e164,
                sms_consent_status="unknown",
                sms_consent_source="team_phone_sync",
                sms_consent_updated_at=datetime.now(timezone.utc),
            )
            session.add(created)
            session.flush()
            players.append(created)
            players_by_phone[phone_e164] = created
            changed = True

    if changed:
        session.commit()

    players.sort(
        key=lambda p: (
            (p.display_name or p.full_name or "").lower(),
            (p.phone_e164 or ""),
            p.id or 0,
        )
    )
    return [
        SmsPlayerLookupItem(
            player_id=p.id,  # type: ignore[arg-type]
            player_name=p.display_name or p.full_name,
            phone_e164=p.phone_e164,
            consent_status=(p.sms_consent_status or "unknown").lower(),
        )
        for p in players
        if p.id is not None
    ]


@router.get("/matches", response_model=List[SmsMatchLookupItem])
def get_sms_matches(
    tournament_id: int,
    phase: str = Query(default="upcoming"),
    session: Session = Depends(get_session),
):
    """
    List tournament matches for SMS targeting lookup.

    phase:
    - upcoming: matches not completed
    - completed: finalized/completed matches
    """
    _get_tournament_or_404(session, tournament_id)
    phase_norm = (phase or "upcoming").strip().lower()
    if phase_norm not in {"upcoming", "completed"}:
        raise HTTPException(400, "phase must be 'upcoming' or 'completed'")

    matches = session.exec(
        select(Match).where(Match.tournament_id == tournament_id)
    ).all()
    if not matches:
        return []

    match_ids = [m.id for m in matches if m.id is not None]
    assignments = []
    if match_ids:
        assignments = session.exec(
            select(MatchAssignment).where(MatchAssignment.match_id.in_(match_ids))  # type: ignore
        ).all()
    assignment_by_match_id = {a.match_id: a for a in assignments}

    slot_ids = [a.slot_id for a in assignments if a.slot_id is not None]
    slots = []
    if slot_ids:
        slots = session.exec(
            select(ScheduleSlot).where(ScheduleSlot.id.in_(slot_ids))  # type: ignore
        ).all()
    slot_by_id = {s.id: s for s in slots if s.id is not None}

    team_ids = {
        team_id
        for m in matches
        for team_id in (m.team_a_id, m.team_b_id)
        if team_id is not None
    }
    teams = []
    if team_ids:
        teams = session.exec(
            select(Team).where(Team.id.in_(team_ids))  # type: ignore
        ).all()
    team_by_id = {t.id: t for t in teams if t.id is not None}

    event_ids = {m.event_id for m in matches if m.event_id is not None}
    events = []
    if event_ids:
        events = session.exec(
            select(Event).where(Event.id.in_(event_ids))  # type: ignore
        ).all()
    event_name_by_id = {e.id: e.name for e in events if e.id is not None}

    rows: List[tuple[SmsMatchLookupItem, tuple]] = []
    for m in matches:
        # Match scope is intended for messaging all 4 players.
        # Require both teams assigned for lookup results.
        if not (m.team_a_id and m.team_b_id):
            continue

        is_completed = _match_is_completed(m)
        if phase_norm == "completed" and not is_completed:
            continue
        if phase_norm == "upcoming" and is_completed:
            continue

        team_a_name = _team_name_for_lookup(team_by_id.get(m.team_a_id), m.placeholder_side_a)
        team_b_name = _team_name_for_lookup(team_by_id.get(m.team_b_id), m.placeholder_side_b)
        event_name = event_name_by_id.get(m.event_id, "")

        assignment = assignment_by_match_id.get(m.id)
        slot = slot_by_id.get(assignment.slot_id) if assignment else None
        day_date = slot.day_date.isoformat() if slot else None
        start_time = slot.start_time.strftime("%H:%M") if slot else None

        when_bits = []
        if day_date:
            when_bits.append(day_date)
        if start_time:
            when_bits.append(start_time)
        when_text = f"{' '.join(when_bits)} | " if when_bits else ""
        display_label = (
            f"{when_text}{event_name} | {m.match_code} | {team_a_name} vs {team_b_name}"
        ).strip(" |")

        item = SmsMatchLookupItem(
            match_id=m.id,  # type: ignore[arg-type]
            match_code=m.match_code,
            event_name=event_name,
            team_a_name=team_a_name,
            team_b_name=team_b_name,
            runtime_status=(m.runtime_status or "SCHEDULED"),
            phase="completed" if is_completed else "upcoming",
            day_date=day_date,
            start_time=start_time,
            display_label=display_label,
        )

        if phase_norm == "upcoming":
            sort_key = (
                0 if (m.runtime_status or "").upper() == "IN_PROGRESS" else 1,
                day_date or "9999-12-31",
                start_time or "23:59",
                event_name.lower(),
                m.match_code,
                m.id or 0,
            )
            rows.append((item, sort_key))
        else:
            sort_key = (
                m.completed_at.isoformat() if m.completed_at else "",
                m.id or 0,
            )
            rows.append((item, sort_key))

    if phase_norm == "upcoming":
        rows.sort(key=lambda pair: pair[1])
    else:
        rows.sort(key=lambda pair: pair[1], reverse=True)

    return [item for item, _key in rows]


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

    Division can be either:
    - Category-level: mixed | womens
    - Event-style label: e.g., "Mixed A Div I", "Women's Open"
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
    _match, teams = _get_match_teams_for_tournament(
        session=session,
        tournament_id=tournament_id,
        match_id=match_id,
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
    """Preview recipients for category- or event-labeled division send."""
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


@router.post("/preview/match/{match_id}", response_model=SmsPreviewResponse)
def preview_match(
    tournament_id: int,
    match_id: int,
    body: SmsSendRequest,
    session: Session = Depends(get_session),
):
    """Preview recipients for a specific match (both assigned teams)."""
    _get_tournament_or_404(session, tournament_id)
    _match, teams = _get_match_teams_for_tournament(
        session=session,
        tournament_id=tournament_id,
        match_id=match_id,
    )
    return _preview_for_teams(teams=teams, message=body.message)


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

    return _settings_to_response(tournament_id, settings)


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
    if "test_allowlist" in update_data:
        update_data["test_allowlist"] = _normalize_allowlist_text(
            update_data["test_allowlist"]
        ) or None
    for key, value in update_data.items():
        setattr(settings, key, value)
    settings.updated_at = datetime.now(timezone.utc)

    session.add(settings)
    session.commit()
    session.refresh(settings)
    return _settings_to_response(tournament_id, settings)


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
