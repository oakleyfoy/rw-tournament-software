"""Queue and send one photo text per eligible player after the first official save.

The photograph, the team roster, and tournament SMS consent all live in this
app. War Campaign's outbox sends registration and invoice messages and has no
team-photo record, so this uses the existing Twilio sender and SmsLog. It does
not change match, check-in, or registration texts.

A notice is written in the same transaction as the official photo. The send
happens later, on the photo worker, so the camera flow does not wait on Twilio.
Consent is read again at send time. Missing or unknown consent is not treated
as permission. A retake does not create another automatic text.

Link policy: the token issued for the first official photo keeps working after
a retake and shows the current official JPEG. Deleting the photo revokes it.
The token expires one year after it is created.
"""

from __future__ import annotations

import logging
import os
import re
import secrets
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

from sqlalchemy import update
from sqlmodel import Session, select

from app.database import engine
from app.models.player import Player
from app.models.sms_log import SmsLog
from app.models.team import Team
from app.models.team_photo import TeamOfficialPhoto
from app.models.team_photo_sms import (
    NOTICE_DUPLICATE,
    NOTICE_NO_PHONE,
    NOTICE_READY,
    STATUS_DELIVERED,
    STATUS_FAILED,
    STATUS_PENDING,
    STATUS_QUEUED,
    STATUS_SENT,
    STATUS_SKIPPED_DUPLICATE,
    STATUS_SKIPPED_INVALID_NUMBER,
    STATUS_SKIPPED_NO_CONSENT,
    STATUS_SKIPPED_OPT_OUT,
    STATUS_SKIPPED_TEST_MODE,
    TeamPhotoShare,
    TeamPhotoSmsNotice,
)
from app.models.team_player import TeamPlayer
from app.models.tournament import Tournament
from app.models.tournament_sms_settings import (
    SMS_DELIVERY_MODE_ALLOWLIST,
    SMS_DELIVERY_MODE_LIVE,
    SMS_DELIVERY_MODE_REDIRECT,
    TournamentSmsSettings,
)
from app.services.team_photo_search import player_names_for_team
from app.services.twilio_service import format_e164, get_twilio_service

logger = logging.getLogger(__name__)

_ENABLED_VALUES = {"1", "true", "yes", "on"}
_PUBLIC_ORIGIN_KEYS = ("PUBLIC_APP_URL", "FRONTEND_URL", "PUBLIC_BASE_URL", "APP_BASE_URL")
_CALLBACK_ORIGIN_KEYS = ("SMS_STATUS_CALLBACK_BASE_URL", "PUBLIC_BASE_URL", "APP_BASE_URL", "EXTERNAL_BASE_URL")
_PERMANENT_ERROR_MARKERS = ("21211", "21610", "21614", "21408", "30005", "30006", "unsubscribed", "not a valid phone")
_BACKOFF_SECONDS = (30, 120, 480, 1800, 7200)
_MAX_ATTEMPTS = len(_BACKOFF_SECONDS)
_SHARE_TTL = timedelta(days=365)
_PHONE_IN_TEXT = re.compile(r"\+?\d[\d\-\s().]{6,}\d")
_NON_ROSTER_ROLES = {"sub", "alternate"}
_runner_lock = threading.Lock()
_runner_started = False

SendSms = Callable[..., dict]


def auto_sms_enabled() -> bool:
    return os.getenv("TEAM_PHOTO_AUTO_SMS_ENABLED", "").strip().lower() in _ENABLED_VALUES


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def photo_sms_body(tournament_name: str, photo_url: str) -> str:
    name = " ".join((tournament_name or "").split()) or "your tournament"
    return (
        "Racquet War 🎾\n"
        f"Your team photo from {name} is ready!\n"
        "View and download your picture:\n"
        f"{photo_url}\n"
        "Thanks for playing Racquet War!\n"
        "Reply STOP to opt out."
    )


def _public_origin() -> Optional[str]:
    for key in _PUBLIC_ORIGIN_KEYS:
        raw = os.getenv(key, "").strip()
        if raw:
            return raw.rstrip("/")
    return None


def _callback_url(tournament_id: int) -> Optional[str]:
    base = ""
    for key in _CALLBACK_ORIGIN_KEYS:
        raw = os.getenv(key, "").strip()
        if raw:
            base = raw.rstrip("/")
            break
    if not base:
        return None
    if base.endswith("/api"):
        return f"{base}/tournaments/{tournament_id}/sms/webhook/status-callback"
    return f"{base}/api/tournaments/{tournament_id}/sms/webhook/status-callback"


def _delivery_mode(settings: Optional[TournamentSmsSettings]) -> str:
    if settings is None:
        return SMS_DELIVERY_MODE_LIVE
    raw = str(getattr(settings, "delivery_mode", "") or "").strip().lower()
    if raw == SMS_DELIVERY_MODE_REDIRECT:
        return SMS_DELIVERY_MODE_REDIRECT
    if raw == SMS_DELIVERY_MODE_ALLOWLIST or bool(getattr(settings, "test_mode", False)):
        return SMS_DELIVERY_MODE_ALLOWLIST
    return SMS_DELIVERY_MODE_LIVE


def _allowlist(raw: Optional[str]) -> set[str]:
    if not raw:
        return set()
    numbers: set[str] = set()
    for token in re.split(r"[,;\n]+", raw):
        token = token.strip()
        if not token:
            continue
        try:
            numbers.add(format_e164(token))
        except ValueError:
            numbers.add(token)
    return numbers


def _roster_links(session: Session, team_id: int) -> list[TeamPlayer]:
    links = session.exec(select(TeamPlayer).where(TeamPlayer.team_id == team_id)).all()
    roster = [link for link in links if (link.role or "player").strip().lower() not in _NON_ROSTER_ROLES]
    roster.sort(key=lambda link: (link.lineup_slot is None, link.lineup_slot or 99, link.id or 0))
    return roster[:2]


def classify_photo_recipients(players: list[Player]) -> list[tuple[Player, Optional[str], str]]:
    """Return (player, e164 or None, kind) for the two roster players.

    kind is ready, duplicate, or no_phone. The same normalized number is one SMS.
    """
    seen: set[str] = set()
    plans: list[tuple[Player, Optional[str], str]] = []
    for player in players:
        phone = _normalize_phone(player.phone_e164)
        if phone and phone in seen:
            plans.append((player, phone, "duplicate"))
            continue
        if not phone:
            plans.append((player, None, "no_phone"))
            continue
        seen.add(phone)
        plans.append((player, phone, "ready"))
    return plans


def _normalize_phone(raw: Optional[str]) -> Optional[str]:
    text = (raw or "").strip()
    if not text:
        return None
    try:
        return format_e164(text)
    except ValueError:
        return None


def _roster_players(session: Session, team_id: int, tournament_id: int) -> list[Player]:
    players: list[Player] = []
    for link in _roster_links(session, team_id):
        player = session.get(Player, link.player_id)
        if player is None or player.tournament_id != tournament_id:
            continue
        players.append(player)
    return players


def queue_team_photo_sms(session: Session, photo: TeamOfficialPhoto) -> None:
    """Record share + recipient rows for a team's first official photo.

    Caller must invoke this only for a newly created official photo, inside the
    photo transaction, and before commit. A disabled flag records nothing, so
    turning the flag on later does not text photographs that already exist.
    """
    if not auto_sms_enabled() or photo.id is None or photo.team_id is None:
        return
    already = session.exec(
        select(TeamPhotoSmsNotice).where(
            TeamPhotoSmsNotice.team_id == photo.team_id,
            TeamPhotoSmsNotice.notice_type == NOTICE_READY,
        )
    ).first()
    if already:
        return

    share = session.exec(select(TeamPhotoShare).where(TeamPhotoShare.team_id == photo.team_id)).first()
    if share is None:
        share = TeamPhotoShare(
            tournament_id=photo.tournament_id,
            team_id=photo.team_id,
            photo_id=photo.id,
            token=secrets.token_urlsafe(32),
            expires_at=_utcnow() + _SHARE_TTL,
        )
        session.add(share)

    now = _utcnow()
    roster = _roster_players(session, photo.team_id, photo.tournament_id)
    for player, phone, kind in classify_photo_recipients(roster):
        if kind == "duplicate":
            session.add(
                TeamPhotoSmsNotice(
                    tournament_id=photo.tournament_id,
                    team_id=photo.team_id,
                    photo_id=photo.id,
                    player_id=player.id,
                    phone_e164=phone,
                    notice_type=NOTICE_DUPLICATE,
                    idempotency_key=f"photo-sms:{photo.team_id}:duplicate:{player.id}",
                    status=STATUS_SKIPPED_DUPLICATE,
                    consent_status=(player.sms_consent_status or "unknown").lower(),
                    consent_source=player.sms_consent_source,
                    created_at=now,
                    next_attempt_at=now,
                )
            )
            continue
        if kind == "no_phone":
            session.add(
                TeamPhotoSmsNotice(
                    tournament_id=photo.tournament_id,
                    team_id=photo.team_id,
                    photo_id=photo.id,
                    player_id=player.id,
                    phone_e164=None,
                    notice_type=NOTICE_NO_PHONE,
                    idempotency_key=f"photo-sms:{photo.team_id}:no-phone:{player.id}",
                    status=STATUS_SKIPPED_INVALID_NUMBER,
                    failure_code="invalid_number",
                    failure_reason="No valid mobile number",
                    consent_status=(player.sms_consent_status or "unknown").lower(),
                    consent_source=player.sms_consent_source,
                    created_at=now,
                    next_attempt_at=now,
                )
            )
            continue
        session.add(
            TeamPhotoSmsNotice(
                tournament_id=photo.tournament_id,
                team_id=photo.team_id,
                photo_id=photo.id,
                player_id=player.id,
                phone_e164=phone,
                notice_type=NOTICE_READY,
                idempotency_key=f"photo-sms:{photo.team_id}:team_photo_ready:{phone}",
                status=STATUS_PENDING,
                consent_status=(player.sms_consent_status or "unknown").lower(),
                consent_source=player.sms_consent_source,
                created_at=now,
                next_attempt_at=now,
            )
        )
    session.flush()


def revoke_team_photo_share(session: Session, team_id: int) -> None:
    share = session.exec(select(TeamPhotoShare).where(TeamPhotoShare.team_id == team_id)).first()
    if share is None or share.revoked_at is not None:
        return
    share.revoked_at = _utcnow()
    session.add(share)
    session.flush()


def _phone_opted_out(session: Session, tournament_id: int, phone: str) -> bool:
    players = session.exec(
        select(Player).where(Player.tournament_id == tournament_id, Player.phone_e164 == phone)
    ).all()
    return any((player.sms_consent_status or "").lower() == "opted_out" for player in players)


def _consent_decision(session: Session, notice: TeamPhotoSmsNotice) -> tuple[str, Optional[str], Optional[str]]:
    player = session.get(Player, notice.player_id) if notice.player_id else None
    status = (player.sms_consent_status or "unknown").lower() if player else "unknown"
    source = player.sms_consent_source if player else None
    phone = notice.phone_e164 or ""
    if status == "opted_out" or (phone and _phone_opted_out(session, notice.tournament_id, phone)):
        return STATUS_SKIPPED_OPT_OUT, "opted_out", source
    if status != "opted_in":
        return STATUS_SKIPPED_NO_CONSENT, status or "unknown", source
    return "", status, source


def _permanent_failure(error: Optional[str]) -> bool:
    text = (error or "").lower()
    return any(marker.lower() in text for marker in _PERMANENT_ERROR_MARKERS)


def _claim(session: Session, notice_id: int, now: datetime) -> bool:
    result = session.execute(
        update(TeamPhotoSmsNotice)
        .where(TeamPhotoSmsNotice.id == notice_id, TeamPhotoSmsNotice.status == STATUS_PENDING)
        .values(status=STATUS_QUEUED, last_attempt_at=now)
    )
    session.commit()
    return int(result.rowcount or 0) == 1


def _finish_skip(session: Session, notice: TeamPhotoSmsNotice, status: str, code: str, reason: str, source: Optional[str], consent: Optional[str]) -> None:
    notice.status = status
    notice.failure_code = code
    notice.failure_reason = reason
    notice.consent_status = consent
    notice.consent_source = source
    session.add(notice)
    session.commit()


def dispatch_team_photo_notices(
    session: Session,
    *,
    send: Optional[SendSms] = None,
    now: Optional[datetime] = None,
    limit: int = 50,
) -> int:
    """Send due photo notices. Returns how many provider accepts were recorded.

    A disabled flag leaves rows pending. Provider acceptance is SENT. Handset
    delivery stays on the status callback. A dry-run provider is left pending
    so an unconfigured sender is not reported as sent.
    """
    if not auto_sms_enabled():
        return 0
    moment = now or _utcnow()
    due = session.exec(
        select(TeamPhotoSmsNotice)
        .where(
            TeamPhotoSmsNotice.status == STATUS_PENDING,
            TeamPhotoSmsNotice.notice_type == NOTICE_READY,
            TeamPhotoSmsNotice.next_attempt_at <= moment,
        )
        .order_by(TeamPhotoSmsNotice.id)
        .limit(limit)
    ).all()
    sender = send or get_twilio_service().send_sms
    accepted = 0
    for notice in due:
        if notice.id is None or not _claim(session, notice.id, moment):
            continue
        session.refresh(notice)
        outcome = _dispatch_one(session, notice, sender, moment)
        if outcome:
            accepted += 1
    return accepted


def _dispatch_one(session: Session, notice: TeamPhotoSmsNotice, sender: SendSms, moment: datetime) -> bool:
    settings = session.exec(
        select(TournamentSmsSettings).where(TournamentSmsSettings.tournament_id == notice.tournament_id)
    ).first()
    if settings is not None and not bool(getattr(settings, "texts_enabled", True)):
        notice.status = STATUS_PENDING
        notice.next_attempt_at = moment + timedelta(seconds=60)
        notice.failure_code = "texts_disabled"
        notice.failure_reason = "Tournament texts are turned off"
        session.add(notice)
        session.commit()
        return False

    skip_status, consent, source = _consent_decision(session, notice)
    if skip_status:
        reason = "Opted out" if skip_status == STATUS_SKIPPED_OPT_OUT else "No SMS consent on file"
        _finish_skip(session, notice, skip_status, consent or "consent", reason, source, consent)
        return False

    mode = _delivery_mode(settings)
    phone = notice.phone_e164 or ""
    if mode == SMS_DELIVERY_MODE_ALLOWLIST and phone not in _allowlist(getattr(settings, "test_allowlist", None) if settings else None):
        _finish_skip(
            session,
            notice,
            STATUS_SKIPPED_TEST_MODE,
            "not_allowlisted",
            "Not an approved test number",
            source,
            consent,
        )
        return False

    origin = _public_origin()
    share = session.exec(select(TeamPhotoShare).where(TeamPhotoShare.team_id == notice.team_id)).first()
    if not origin or share is None or share.revoked_at is not None:
        notice.status = STATUS_PENDING
        notice.next_attempt_at = moment + timedelta(minutes=5)
        notice.failure_code = "link_unavailable"
        notice.failure_reason = "Photo link is not configured"
        session.add(notice)
        session.commit()
        return False

    tournament = session.get(Tournament, notice.tournament_id)
    photo_url = f"{origin}/p/photo/{share.token}"
    body = photo_sms_body(tournament.name if tournament else "", photo_url)
    delivery_phone = phone
    outbound = body
    if mode == SMS_DELIVERY_MODE_REDIRECT:
        redirect = str(getattr(settings, "redirect_phone", None) or "").strip()
        try:
            delivery_phone = format_e164(redirect)
        except ValueError:
            notice.status = STATUS_PENDING
            notice.next_attempt_at = moment + timedelta(minutes=5)
            notice.failure_code = "redirect_phone"
            notice.failure_reason = "Redirect test number is invalid"
            session.add(notice)
            session.commit()
            return False
        outbound = f"[TEST redirect — intended {phone}]\n{body}"

    try:
        result = sender(delivery_phone, outbound, status_callback_url=_callback_url(notice.tournament_id))
    except Exception as exc:
        logger.exception("Team photo SMS send failed for notice %s", notice.id)
        _schedule_retry(session, notice, moment, "send_error", str(exc)[:300])
        return False

    provider_status = str(result.get("status") or "failed").lower()
    if provider_status == "dry_run":
        notice.status = STATUS_PENDING
        notice.next_attempt_at = moment + timedelta(minutes=5)
        notice.failure_code = "provider_unconfigured"
        notice.failure_reason = "SMS provider is not configured"
        session.add(notice)
        session.commit()
        return False
    if provider_status not in {"queued", "sent"}:
        error = str(result.get("error") or "SMS provider rejected the message")
        if _permanent_failure(error):
            notice.status = STATUS_FAILED
            notice.failure_code = "permanent"
            notice.failure_reason = error[:300]
            notice.consent_status = consent
            notice.consent_source = source
            session.add(notice)
            session.commit()
            return False
        _schedule_retry(session, notice, moment, "transient", error[:300])
        return False

    notice.status = STATUS_SENT
    notice.provider_sid = result.get("sid")
    notice.sent_at = moment
    notice.consent_status = consent
    notice.consent_source = source
    notice.failure_code = None
    notice.failure_reason = None
    session.add(notice)
    session.add(
        SmsLog(
            tournament_id=notice.tournament_id,
            team_id=notice.team_id,
            phone_number=delivery_phone,
            intended_phone_number=phone,
            message_body=outbound,
            message_type="team_photo",
            twilio_sid=result.get("sid"),
            status=provider_status,
            error_message=None,
            trigger="auto",
            dedupe_key=notice.idempotency_key,
            sent_at=moment,
        )
    )
    session.commit()
    return True


def _schedule_retry(session: Session, notice: TeamPhotoSmsNotice, moment: datetime, code: str, reason: str) -> None:
    notice.retry_count = int(notice.retry_count or 0) + 1
    notice.failure_code = code
    notice.failure_reason = reason
    notice.last_attempt_at = moment
    if notice.retry_count >= _MAX_ATTEMPTS:
        notice.status = STATUS_FAILED
        notice.failure_code = "retries_exhausted"
    else:
        delay = _BACKOFF_SECONDS[min(notice.retry_count - 1, len(_BACKOFF_SECONDS) - 1)]
        notice.status = STATUS_PENDING
        notice.next_attempt_at = moment + timedelta(seconds=delay)
    session.add(notice)
    session.commit()


def record_team_photo_provider_status(
    session: Session,
    *,
    provider_sid: str,
    provider_status: str,
    error_code: Optional[str] = None,
    error_message: Optional[str] = None,
) -> bool:
    """Apply a provider delivery callback. Acceptance stays SENT until the handset status arrives."""
    sid = (provider_sid or "").strip()
    if not sid:
        return False
    notice = session.exec(select(TeamPhotoSmsNotice).where(TeamPhotoSmsNotice.provider_sid == sid)).first()
    if notice is None:
        return False
    status = (provider_status or "").strip().lower()
    if status == "delivered":
        notice.status = STATUS_DELIVERED
        notice.delivered_at = _utcnow()
        notice.failure_code = None
        notice.failure_reason = None
    elif status in {"failed", "undelivered"}:
        notice.status = STATUS_FAILED
        notice.failure_code = (error_code or status)[:80]
        notice.failure_reason = (error_message or status)[:300]
    elif status in {"queued", "sent", "accepted"} and notice.status != STATUS_DELIVERED:
        notice.status = STATUS_SENT
    else:
        return False
    session.add(notice)
    session.commit()
    return True


def _safe_reason(status: str, reason: Optional[str]) -> Optional[str]:
    labels = {
        STATUS_SKIPPED_NO_CONSENT: "No SMS consent on file",
        STATUS_SKIPPED_OPT_OUT: "Opted out",
        STATUS_SKIPPED_INVALID_NUMBER: "No valid mobile number",
        STATUS_SKIPPED_DUPLICATE: "Same number as the other player",
        STATUS_SKIPPED_TEST_MODE: "Not an approved test number",
    }
    if status in labels:
        return labels[status]
    if status == STATUS_FAILED and reason:
        return _PHONE_IN_TEXT.sub("…", reason)[:160]
    return None


def team_photo_sms_status(session: Session, tournament_id: int, team_id: int) -> list[dict]:
    notices = session.exec(
        select(TeamPhotoSmsNotice)
        .where(
            TeamPhotoSmsNotice.tournament_id == tournament_id,
            TeamPhotoSmsNotice.team_id == team_id,
        )
        .order_by(TeamPhotoSmsNotice.id)
    ).all()
    rows = []
    for notice in notices:
        player = session.get(Player, notice.player_id) if notice.player_id else None
        name = ""
        if player is not None:
            name = (player.display_name or player.full_name or "").strip()
        label = {
            STATUS_PENDING: "Pending",
            STATUS_QUEUED: "Pending",
            STATUS_SENT: "Sent",
            STATUS_DELIVERED: "Delivered",
            STATUS_FAILED: "Failed",
        }.get(notice.status, "Skipped")
        rows.append(
            {
                "name": name or "Player",
                "status": label,
                "detail": _safe_reason(notice.status, notice.failure_reason),
            }
        )
    return rows


def resolve_team_photo_share(session: Session, token: str) -> Optional[tuple[TeamPhotoShare, TeamOfficialPhoto, Team, Tournament, list[str]]]:
    cleaned = (token or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{32,128}", cleaned):
        return None
    share = session.exec(select(TeamPhotoShare).where(TeamPhotoShare.token == cleaned)).first()
    if share is None or share.revoked_at is not None:
        return None
    if _as_utc(share.expires_at) <= _utcnow():
        return None
    photo = session.exec(select(TeamOfficialPhoto).where(TeamOfficialPhoto.team_id == share.team_id)).first()
    team = session.get(Team, share.team_id)
    tournament = session.get(Tournament, share.tournament_id)
    if photo is None or team is None or tournament is None:
        return None
    if photo.tournament_id != share.tournament_id:
        return None
    linked = []
    for link in _roster_links(session, share.team_id):
        player = session.get(Player, link.player_id)
        if player is not None:
            linked.append((player.display_name or player.full_name or "").strip())
    names = player_names_for_team(team, linked)
    return share, photo, team, tournament, names


def _runner_loop(interval_seconds: int) -> None:
    while True:
        try:
            if auto_sms_enabled():
                with Session(engine) as session:
                    dispatch_team_photo_notices(session)
        except Exception:
            logger.exception("Team photo SMS worker failed")
        time.sleep(interval_seconds)


def start_team_photo_sms_worker() -> None:
    """Drain pending photo notices. Tests and a disabled flag do not send."""
    global _runner_started
    if "pytest" in sys.modules:
        return
    with _runner_lock:
        if _runner_started:
            return
        interval = int(os.getenv("TEAM_PHOTO_SMS_POLL_SECONDS", "15") or "15")
        thread = threading.Thread(
            target=_runner_loop,
            args=(max(5, interval),),
            name="team-photo-sms",
            daemon=True,
        )
        thread.start()
        _runner_started = True
