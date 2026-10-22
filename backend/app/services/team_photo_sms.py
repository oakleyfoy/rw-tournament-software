"""Queue and send one photo text per eligible player for each photo session.

The photograph, the team roster, and tournament SMS consent all live in this
app. War Campaign's outbox sends registration and invoice messages and has no
team-photo record, so this uses the existing Twilio sender and SmsLog. It does
not change match, check-in, or registration texts.

A notice is written in the same transaction as the official photo. The send
happens later, on the photo worker, so the camera flow does not wait on Twilio.
Consent is read again at send time. Missing or unknown consent is not treated
as permission. A retake keeps the same photo session and does not create
another automatic text. Deleting the official photo revokes its link and
cancels notices that have not been accepted by the provider. The next
successful save opens a new session and can text again.

Link policy: the token issued for a session keeps working after a retake and
shows the current official JPEG. Deleting the photo revokes it. A later
session gets a new token. The token expires one year after it is issued.
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
    STATUS_CANCELED,
    STATUS_SKIPPED_DISABLED,
    STATUS_SKIPPED_TEXTS_OFF,
    TeamPhotoShare,
    TeamPhotoSmsNotice,
)
from app.models.team_player import TeamPlayer
from app.models.tournament import Tournament
from app.services.team_photo_search import player_names_for_team
from app.services.twilio_service import format_e164

logger = logging.getLogger(__name__)

_ENABLED_VALUES = {"1", "true", "yes", "on"}
_PUBLIC_ORIGIN_KEYS = (
    "PUBLIC_APP_URL",
    "FRONTEND_URL",
    "PUBLIC_BASE_URL",
    "APP_BASE_URL",
    "RENDER_EXTERNAL_URL",
)
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


def _roster_links(session: Session, team_id: int) -> list[TeamPlayer]:
    links = session.exec(select(TeamPlayer).where(TeamPlayer.team_id == team_id)).all()
    roster = [link for link in links if (link.role or "player").strip().lower() not in _NON_ROSTER_ROLES]
    roster.sort(key=lambda link: (link.lineup_slot is None, link.lineup_slot or 99, link.id or 0))
    return roster[:2]


def classify_photo_recipients(
    players: list[Player],
    phones: Optional[list[Optional[str]]] = None,
) -> list[tuple[Player, Optional[str], str]]:
    """Return (player, e164 or None, kind) for the two roster players.

    kind is ready, duplicate, or no_phone. The same normalized number is one SMS.
    phones overrides Player.phone_e164 for this plan only and is not saved.
    """
    seen: set[str] = set()
    plans: list[tuple[Player, Optional[str], str]] = []
    for index, player in enumerate(players):
        raw = phones[index] if phones is not None else player.phone_e164
        phone = _normalize_phone(raw)
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


def _roster_players(session: Session, team_id: int, tournament_id: int) -> list[tuple[Player, Optional[str]]]:
    """Roster players and the number to text, without writing the player row.

    Player.phone_e164 wins. In legacy team-field mode the slot phone is only a
    fallback for this notice. Consent still comes from the player record.
    """
    from app.routes.sms import _team_slot_phone

    team = session.get(Team, team_id)
    found: list[tuple[Player, Optional[str]]] = []
    for link in _roster_links(session, team_id):
        player = session.get(Player, link.player_id)
        if player is None or player.tournament_id != tournament_id:
            continue
        phone = _normalize_phone(player.phone_e164)
        slot = int(link.lineup_slot or 0)
        if not phone and team is not None and slot in (1, 2):
            phone = _team_slot_phone(team, slot)
        found.append((player, phone))
    return found


def _idempotency_key(photo_session_id: int, team_id: int, notice_type: str, recipient: str) -> str:
    return f"photo-sms:{int(photo_session_id)}:{int(team_id)}:{notice_type}:{recipient}"


def _recipient_token(phone: Optional[str], player_id: Optional[int]) -> str:
    if phone:
        return phone
    return f"player:{int(player_id or 0)}"


def queue_team_photo_sms(session: Session, photo: TeamOfficialPhoto) -> None:
    """Record share + recipient rows for a new official-photo session.

    Caller must invoke this only when the official photo row was just created,
    inside the photo transaction, and before commit. A replacement keeps the
    current row and must not call this. A disabled flag records nothing, so
    turning the flag on later does not text photographs that already exist.

    An active share means this session was already queued. A revoked share
    means the previous official photo was deleted, so this save opens the
    next session and uses new idempotency keys.
    """
    if not auto_sms_enabled() or photo.id is None or photo.team_id is None:
        return

    share = session.exec(select(TeamPhotoShare).where(TeamPhotoShare.team_id == photo.team_id)).first()
    now = _utcnow()
    if share is None:
        generation = 1
        share = TeamPhotoShare(
            tournament_id=photo.tournament_id,
            team_id=photo.team_id,
            photo_id=photo.id,
            generation=generation,
            token=secrets.token_urlsafe(32),
            expires_at=now + _SHARE_TTL,
            created_at=now,
        )
        session.add(share)
    elif share.revoked_at is not None:
        generation = int(share.generation or 1) + 1
        share.generation = generation
        share.tournament_id = photo.tournament_id
        share.photo_id = photo.id
        share.token = secrets.token_urlsafe(32)
        share.revoked_at = None
        share.expires_at = now + _SHARE_TTL
        share.created_at = now
        session.add(share)
    else:
        return

    already = session.exec(
        select(TeamPhotoSmsNotice).where(
            TeamPhotoSmsNotice.team_id == photo.team_id,
            TeamPhotoSmsNotice.photo_session_id == generation,
            TeamPhotoSmsNotice.notice_type == NOTICE_READY,
        )
    ).first()
    if already:
        return

    roster = _roster_players(session, photo.team_id, photo.tournament_id)
    players = [player for player, _phone in roster]
    phones = [phone for _player, phone in roster]
    for player, phone, kind in classify_photo_recipients(players, phones):
        if kind == "duplicate":
            notice_type = NOTICE_DUPLICATE
            status = STATUS_SKIPPED_DUPLICATE
            failure_code = None
            failure_reason = None
        elif kind == "no_phone":
            notice_type = NOTICE_NO_PHONE
            status = STATUS_SKIPPED_INVALID_NUMBER
            failure_code = "invalid_number"
            failure_reason = "No valid mobile number"
        else:
            notice_type = NOTICE_READY
            status = STATUS_PENDING
            failure_code = None
            failure_reason = None
        key = _idempotency_key(generation, photo.team_id, notice_type, _recipient_token(phone, player.id))
        if session.exec(select(TeamPhotoSmsNotice).where(TeamPhotoSmsNotice.idempotency_key == key)).first():
            continue
        session.add(
            TeamPhotoSmsNotice(
                tournament_id=photo.tournament_id,
                team_id=photo.team_id,
                photo_id=photo.id,
                photo_session_id=generation,
                player_id=player.id,
                phone_e164=phone,
                notice_type=notice_type,
                idempotency_key=key,
                status=status,
                failure_code=failure_code,
                failure_reason=failure_reason,
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


def close_team_photo_sms_session(session: Session, team_id: int) -> None:
    """Revoke the current link and stop notices the provider has not accepted.

    Sent, delivered, failed, and skipped rows stay as they are. Player consent
    is not read or written here.
    """
    revoke_team_photo_share(session, team_id)
    pending = session.exec(
        select(TeamPhotoSmsNotice).where(
            TeamPhotoSmsNotice.team_id == team_id,
            TeamPhotoSmsNotice.status.in_([STATUS_PENDING, STATUS_QUEUED]),  # type: ignore[attr-defined]
        )
    ).all()
    if not pending:
        return
    for notice in pending:
        notice.status = STATUS_CANCELED
        notice.failure_code = "photo_deleted"
        notice.failure_reason = "Official photograph was deleted before this text was sent"
        session.add(notice)
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

    The feature flag and All Texting are both required on the tick that sends.
    A notice blocked by either gate is finished as skipped. Turning the gate
    on later does not release it and does not mark it delivered. Photographs
    saved while the feature flag is off are never queued.
    """
    if not auto_sms_enabled():
        _hold_pending(
            session,
            STATUS_SKIPPED_DISABLED,
            "feature_disabled",
            "Team photo texts are turned off",
        )
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
    accepted = 0
    for notice in due:
        if notice.id is None or not _claim(session, notice.id, moment):
            continue
        session.refresh(notice)
        outcome = _dispatch_one(session, notice, send, moment)
        if outcome:
            accepted += 1
    return accepted


def _hold_pending(session: Session, status: str, code: str, reason: str) -> None:
    """Stop pending photo texts. A later change to the gate does not send them."""
    pending = session.exec(
        select(TeamPhotoSmsNotice).where(
            TeamPhotoSmsNotice.status == STATUS_PENDING,
            TeamPhotoSmsNotice.notice_type == NOTICE_READY,
        )
    ).all()
    if not pending:
        return
    for notice in pending:
        notice.status = status
        notice.failure_code = code
        notice.failure_reason = reason
        session.add(notice)
    session.commit()


def _defer(session: Session, notice: TeamPhotoSmsNotice, moment: datetime, code: str, reason: str, delay: timedelta) -> None:
    notice.status = STATUS_PENDING
    notice.next_attempt_at = moment + delay
    notice.failure_code = code
    notice.failure_reason = reason
    session.add(notice)
    session.commit()


def _latest_photo_log(session: Session, notice: TeamPhotoSmsNotice, intended_phone: str) -> Optional[SmsLog]:
    return session.exec(
        select(SmsLog)
        .where(
            SmsLog.tournament_id == notice.tournament_id,
            SmsLog.team_id == notice.team_id,
            SmsLog.message_type == "team_photo",
            SmsLog.intended_phone_number == intended_phone,
        )
        .order_by(SmsLog.id.desc())
    ).first()


def _session_closed(share: Optional[TeamPhotoShare], notice: TeamPhotoSmsNotice) -> bool:
    if share is None or share.revoked_at is not None:
        return True
    return int(share.generation or 1) != int(notice.photo_session_id or 1)


def _cancel_closed_notice(session: Session, notice: TeamPhotoSmsNotice) -> None:
    notice.status = STATUS_CANCELED
    notice.failure_code = "photo_deleted"
    notice.failure_reason = "Official photograph was deleted before this text was sent"
    session.add(notice)
    session.commit()


def _dispatch_one(session: Session, notice: TeamPhotoSmsNotice, sender: Optional[SendSms], moment: datetime) -> bool:
    """Hand one notice to the tournament SMS sender.

    Consent is decided here. All Texting, Redirect All, Allowlist Only, and
    Live are decided inside that sender at call time, not when the photo was saved.
    A notice whose photo session was deleted is canceled instead of sent.
    """
    session.refresh(notice)
    if notice.status != STATUS_QUEUED:
        return False
    if not auto_sms_enabled():
        _finish_skip(
            session,
            notice,
            STATUS_SKIPPED_DISABLED,
            "feature_disabled",
            "Team photo texts are turned off",
            None,
            None,
        )
        return False

    skip_status, consent, source = _consent_decision(session, notice)
    if skip_status:
        reason = "Opted out" if skip_status == STATUS_SKIPPED_OPT_OUT else "No SMS consent on file"
        _finish_skip(session, notice, skip_status, consent or "consent", reason, source, consent)
        return False

    origin = _public_origin()
    share = session.exec(select(TeamPhotoShare).where(TeamPhotoShare.team_id == notice.team_id)).first()
    if share is None or _session_closed(share, notice):
        _cancel_closed_notice(session, notice)
        return False
    if not origin:
        _defer(session, notice, moment, "link_unavailable", "Photo link is not configured", timedelta(minutes=5))
        return False
    session.refresh(notice)
    session.refresh(share)
    if notice.status != STATUS_QUEUED:
        return False
    if _session_closed(share, notice):
        _cancel_closed_notice(session, notice)
        return False

    tournament = session.get(Tournament, notice.tournament_id)
    phone = notice.phone_e164 or ""
    body = photo_sms_body(tournament.name if tournament else "", f"{origin}/p/photo/{share.token}")
    from fastapi import HTTPException

    from app.routes.sms import _send_to_phone_targets

    try:
        response = _send_to_phone_targets(
            session,
            notice.tournament_id,
            targets=[{"phone": phone, "team_id": notice.team_id, "player_id": notice.player_id}],
            message=body,
            message_type="team_photo",
            trigger="auto",
            send_sms=sender,
        )
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, str) else "Tournament SMS delivery is not ready"
        _defer(session, notice, moment, "delivery_mode", detail[:300], timedelta(minutes=5))
        return False
    except Exception as exc:
        logger.exception("Team photo SMS send failed for notice %s", notice.id)
        _schedule_retry(session, notice, moment, "send_error", str(exc)[:300])
        return False

    if not response.results:
        _finish_skip(
            session,
            notice,
            STATUS_SKIPPED_TEXTS_OFF,
            "texts_disabled",
            "Tournament texts are turned off",
            source,
            consent,
        )
        return False

    result = response.results[0]
    status = (result.status or "").lower()
    if status == "blocked_test_mode":
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
    if status == "blocked_consent":
        _finish_skip(session, notice, STATUS_SKIPPED_OPT_OUT, "opted_out", "Opted out", source, "opted_out")
        return False
    if status == "dry_run":
        _defer(session, notice, moment, "provider_unconfigured", "SMS provider is not configured", timedelta(minutes=5))
        return False
    if status not in {"queued", "sent", "sent_redirect"}:
        error = str(result.error or "SMS provider rejected the message")
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

    log = _latest_photo_log(session, notice, phone)
    notice.status = STATUS_SENT
    notice.provider_sid = log.twilio_sid if log is not None else None
    notice.sent_at = moment
    notice.consent_status = consent
    notice.consent_source = source
    notice.failure_code = None
    notice.failure_reason = None
    session.add(notice)
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
        STATUS_SKIPPED_DISABLED: "Team photo texts are turned off",
        STATUS_SKIPPED_TEXTS_OFF: "Tournament texts are turned off",
        STATUS_CANCELED: "Official photograph was deleted",
    }
    if status in labels:
        return labels[status]
    if status == STATUS_FAILED and reason:
        return _PHONE_IN_TEXT.sub("…", reason)[:160]
    return None


def _phone_source(session: Session, notice: TeamPhotoSmsNotice, player: Optional[Player]) -> str:
    target = _normalize_phone(notice.phone_e164)
    if not target:
        return "none"
    if player is not None and _normalize_phone(player.phone_e164) == target:
        return "player"
    if player is None or player.id is None:
        return "unattributed"
    from app.routes.sms import _team_slot_phone

    link = session.exec(
        select(TeamPlayer).where(TeamPlayer.team_id == notice.team_id, TeamPlayer.player_id == player.id)
    ).first()
    team = session.get(Team, notice.team_id)
    slot = int(link.lineup_slot or 0) if link is not None else 0
    if team is not None and slot in (1, 2) and _normalize_phone(_team_slot_phone(team, slot)) == target:
        return "legacy_team_field"
    return "unattributed"


def _delivery_flags(notice: TeamPhotoSmsNotice) -> tuple[bool, bool]:
    """Whether the tournament sender ran, and whether Twilio accepted the message."""
    twilio_accepted = notice.status in {STATUS_SENT, STATUS_DELIVERED} or bool(notice.provider_sid)
    sender_called = twilio_accepted or notice.status in {
        STATUS_FAILED,
        STATUS_SKIPPED_TEXTS_OFF,
        STATUS_SKIPPED_TEST_MODE,
    }
    return sender_called, twilio_accepted and notice.status != STATUS_FAILED


def team_photo_sms_diagnostic(session: Session, tournament_id: int, team_id: int) -> list[dict]:
    """Staff view of one team's photo notices. Phone numbers and tokens are omitted."""
    notices = session.exec(
        select(TeamPhotoSmsNotice)
        .where(
            TeamPhotoSmsNotice.tournament_id == tournament_id,
            TeamPhotoSmsNotice.team_id == team_id,
        )
        .order_by(TeamPhotoSmsNotice.photo_session_id, TeamPhotoSmsNotice.id)
    ).all()
    rows = []
    for notice in notices:
        player = session.get(Player, notice.player_id) if notice.player_id else None
        name = ""
        if player is not None:
            name = (player.display_name or player.full_name or "").strip()
        sender_called, twilio_accepted = _delivery_flags(notice)
        rows.append(
            {
                "name": name or "Player",
                "phone_source": _phone_source(session, notice, player),
                "consent_status": (player.sms_consent_status if player is not None else notice.consent_status) or "unknown",
                "consent_source": player.sms_consent_source if player is not None else notice.consent_source,
                "photo_session": int(notice.photo_session_id or 1),
                "status": notice.status,
                "detail": _safe_reason(notice.status, notice.failure_reason),
                "sender_called": sender_called,
                "twilio_accepted": twilio_accepted,
            }
        )
    return rows


def team_photo_sms_status(session: Session, tournament_id: int, team_id: int) -> list[dict]:
    notices = session.exec(
        select(TeamPhotoSmsNotice)
        .where(
            TeamPhotoSmsNotice.tournament_id == tournament_id,
            TeamPhotoSmsNotice.team_id == team_id,
        )
        .order_by(TeamPhotoSmsNotice.id)
    ).all()
    if notices:
        latest = max(int(notice.photo_session_id or 1) for notice in notices)
        notices = [notice for notice in notices if int(notice.photo_session_id or 1) == latest]
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
            STATUS_CANCELED: "Canceled",
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
            with Session(engine) as session:
                dispatch_team_photo_notices(session)
        except Exception:
            logger.exception("Team photo SMS worker failed")
        time.sleep(interval_seconds)


def team_photo_sms_worker_started() -> bool:
    return _runner_started


def start_team_photo_sms_worker() -> None:
    """Start the photo-notice worker. Tests do not start it."""
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
