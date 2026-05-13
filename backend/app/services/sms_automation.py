"""Centralized SMS automation triggers for desk/runtime events."""

from __future__ import annotations

import logging
import os
import threading
import time as std_time
from datetime import date, datetime, time, timezone
from typing import Any, Dict, Optional, Tuple
from zoneinfo import ZoneInfo

from sqlmodel import Session, select

from app.database import engine
from app.models.match import Match
from app.models.match_assignment import MatchAssignment
from app.models.schedule_slot import ScheduleSlot
from app.models.sms_template import DEFAULT_SMS_TEMPLATES, SmsTemplate
from app.models.team import Team
from app.models.tournament import Tournament
from app.models.tournament_sms_settings import TournamentSmsSettings

logger = logging.getLogger(__name__)

_runner_lock = threading.Lock()
_runner_started = False


def _normalize_sms_template_mode(raw: Optional[str]) -> str:
    mode = (raw or "").strip().lower()
    return "checkin_management" if mode == "checkin_management" else "court_management"


class SmsAutomationEngine:
    """Automation helper used by desk/runtime routes."""

    def __init__(self, session: Session, tournament: Tournament, version_id: int):
        self.session = session
        self.tournament = tournament
        self.version_id = version_id
        self._settings: Optional[TournamentSmsSettings] = None
        self._template_cache: Dict[str, Tuple[bool, str]] = {}
        self._team_cache: Dict[int, Optional[Team]] = {}
        self._assignment_cache: Dict[int, Optional[MatchAssignment]] = {}
        self._slot_cache: Dict[int, Optional[ScheduleSlot]] = {}

    # ------------------------------------------------------------------
    # Public triggers
    # ------------------------------------------------------------------

    def handle_match_status_change(
        self,
        match: Match,
        previous_status: str,
        new_status: str,
    ) -> None:
        """Run status-change automations for active desk management mode."""
        prev = (previous_status or "").upper()
        curr = (new_status or "").upper()
        if curr != "IN_PROGRESS":
            return
        if prev == "IN_PROGRESS":
            return

        if self._is_checkin_management():
            self._trigger_checkin_slot_checkin(match)
            return

        self._trigger_up_next(match)
        self._trigger_on_deck(match)

    def handle_match_finalized(self, match: Match) -> None:
        """Run post-final automations for active desk management mode."""
        self.send_match_finalized_texts(match)

    def preview_match_finalized_texts(self, match: Match) -> Dict[str, Any]:
        plan = self._match_finalized_sms_plan(match)
        jobs = list(plan["jobs"])
        recipients: list[dict[str, Any]] = []
        teams_with_next_match = len(jobs)
        teams_without_phone = 0
        blocked_test_mode = 0
        blocked_consent = 0
        deduped = 0
        for job in jobs:
            projection = self._project_team_send_outcomes(
                team=job["team"],
                message_type=job["message_type"],
                dedupe_key=job["dedupe_key"],
            )
            teams_without_phone += int(projection["no_phone"])
            blocked_test_mode += int(projection["blocked_test_mode"])
            blocked_consent += int(projection["blocked_consent"])
            deduped += int(projection["deduped"])
            recipients.extend(
                self._preview_template_to_phone_targets(
                    team=job["team"],
                    message=job["message"],
                    message_type=job["message_type"],
                    dedupe_key=job["dedupe_key"],
                )
            )
        message_type = str(plan["message_type"])
        return {
            "message_type": message_type,
            "total_messages": len(recipients),
            "recipients": recipients,
            "teams_with_next_match": teams_with_next_match,
            "teams_without_phone": teams_without_phone,
            "blocked_test_mode": blocked_test_mode,
            "blocked_consent": blocked_consent,
            "deduped": deduped,
            "disabled_reason": plan["disabled_reason"],
        }

    def send_match_finalized_texts(
        self,
        match: Match,
        *,
        trigger: str = "auto",
    ) -> Dict[str, Any]:
        plan = self._match_finalized_sms_plan(match)
        jobs = list(plan["jobs"])
        message_type = str(plan["message_type"])
        aggregate: Dict[str, Any] = {
            "total": 0,
            "sent": 0,
            "failed": 0,
            "skipped_no_phone": 0,
            "skipped_consent": 0,
            "skipped_dedupe": 0,
            "skipped_test_mode": 0,
            "message_type": message_type,
            "results": [],
        }
        for job in jobs:
            resp = self._send_message_to_team(
                team=job["team"],
                message=job["message"],
                message_type=job["message_type"],
                dedupe_key=job["dedupe_key"],
                trigger=trigger,
            )
            aggregate["total"] += int(resp.total)
            aggregate["sent"] += int(resp.sent)
            aggregate["failed"] += int(resp.failed)
            aggregate["skipped_no_phone"] += int(resp.skipped_no_phone)
            aggregate["skipped_consent"] += int(resp.skipped_consent)
            aggregate["skipped_dedupe"] += int(resp.skipped_dedupe)
            aggregate["skipped_test_mode"] += int(resp.skipped_test_mode)
            aggregate["results"].extend(resp.results)
        return aggregate

    def handle_court_change(
        self,
        match: Match,
        previous_slot_id: Optional[int],
        new_slot_id: Optional[int],
    ) -> None:
        """Run auto_court_change when a match's slot changes."""
        if self._is_checkin_management():
            return
        if not self._is_enabled("auto_court_change", default=True):
            return
        if not previous_slot_id or not new_slot_id:
            return
        if previous_slot_id == new_slot_id:
            return

        old_slot = self._slot_by_id(previous_slot_id)
        new_slot = self._slot_by_id(new_slot_id)
        if not old_slot or not new_slot:
            return

        old_sig = (old_slot.day_date, old_slot.start_time, old_slot.court_number)
        new_sig = (new_slot.day_date, new_slot.start_time, new_slot.court_number)
        if old_sig == new_sig:
            return

        for team in self._teams_for_match(match):
            dedupe_key = self._dedupe_key(
                "court_change",
                f"v{self.version_id}",
                f"m{match.id}",
                f"from{previous_slot_id}",
                f"to{new_slot_id}",
            )
            self._send_template_to_team(
                team=team,
                message_type="court_change",
                dedupe_key=dedupe_key,
                match=match,
                slot=new_slot,
                opponent=self._opponent_display(match, team.id),
            )

    def handle_checkin_court_assigned(
        self,
        match: Match,
        slot_id: Optional[int],
    ) -> None:
        """Run check-in court-assigned automation when desk assigns a court."""
        if not self._is_checkin_management():
            return
        if not self._is_enabled("auto_checkin_court_assigned", default=False):
            return
        if not slot_id:
            return
        slot = self._slot_by_id(slot_id)
        if not slot:
            return
        for team in self._teams_for_match(match):
            dedupe_key = self._dedupe_key(
                "checkin_court_assigned",
                f"v{self.version_id}",
                f"m{match.id}",
                f"s{slot_id}",
                f"t{team.id}",
            )
            self._send_template_to_team(
                team=team,
                message_type="checkin_court_assigned",
                dedupe_key=dedupe_key,
                match=match,
                slot=slot,
                opponent=self._opponent_display(match, team.id),
            )

    # ------------------------------------------------------------------
    # Trigger implementations
    # ------------------------------------------------------------------

    def _trigger_up_next(self, match: Match) -> None:
        if not self._is_enabled("auto_up_next", default=False):
            return
        slot = self._slot_for_match(match.id)
        for team in self._teams_for_match(match):
            dedupe_key = self._dedupe_key(
                "up_next",
                f"v{self.version_id}",
                f"m{match.id}",
                f"s{slot.id if slot else 'na'}",
            )
            self._send_template_to_team(
                team=team,
                message_type="up_next",
                dedupe_key=dedupe_key,
                match=match,
                slot=slot,
                opponent=self._opponent_display(match, team.id),
            )

    def _trigger_on_deck(self, current_match: Match) -> None:
        if not self._is_enabled("auto_on_deck", default=False):
            return
        current_slot = self._slot_for_match(current_match.id)
        if not current_slot:
            return

        non_final = self._non_final_matches_on_court(current_slot.court_number)
        if len(non_final) < 2:
            return
        on_deck = non_final[1]
        on_deck_slot = self._slot_for_match(on_deck.id)
        for team in self._teams_for_match(on_deck):
            dedupe_key = self._dedupe_key(
                "on_deck",
                f"v{self.version_id}",
                f"m{on_deck.id}",
                f"s{on_deck_slot.id if on_deck_slot else 'na'}",
            )
            self._send_template_to_team(
                team=team,
                message_type="on_deck",
                dedupe_key=dedupe_key,
                match=on_deck,
                slot=on_deck_slot,
                opponent=self._opponent_display(on_deck, team.id),
            )

    def _trigger_first_match(self, match: Match) -> None:
        if not self._is_enabled("auto_first_match", default=False):
            return
        slot = self._slot_for_match(match.id)
        for team in self._teams_for_match(match):
            team_id = team.id
            if not team_id:
                continue
            if not self._is_team_first_match(team_id=team_id, match_id=match.id):
                continue
            dedupe_key = self._dedupe_key(
                "first_match",
                f"v{self.version_id}",
                f"t{team_id}",
                f"m{match.id}",
            )
            self._send_template_to_team(
                team=team,
                message_type="first_match",
                dedupe_key=dedupe_key,
                match=match,
                slot=slot,
                opponent=self._opponent_display(match, team.id),
            )

    def _trigger_checkin_first_match(self, match: Match) -> None:
        if not self._is_enabled("auto_checkin_first_match", default=False):
            return
        slot = self._slot_for_match(match.id)
        for team in self._teams_for_match(match):
            team_id = team.id
            if not team_id:
                continue
            if not self._is_team_first_match(team_id=team_id, match_id=match.id):
                continue
            dedupe_key = self._dedupe_key(
                "checkin_first_match",
                f"v{self.version_id}",
                f"t{team_id}",
                f"m{match.id}",
            )
            self._send_template_to_team(
                team=team,
                message_type="checkin_first_match",
                dedupe_key=dedupe_key,
                match=match,
                slot=slot,
                opponent=self._opponent_display(match, team.id),
            )

    def _trigger_checkin_slot_checkin(self, current_match: Match) -> None:
        if not self._is_enabled("auto_checkin_slot_checkin", default=False):
            return
        current_slot = self._slot_for_match(current_match.id)
        if not current_slot:
            return
        # Only send once the final match in the current time slot starts.
        if not self._is_last_started_match_in_timeslot(current_match, current_slot):
            return
        current_key = self._slot_sort_key(current_slot)
        matches = self.session.exec(
            select(Match).where(Match.schedule_version_id == self.version_id)
        ).all()
        next_slot_key: Optional[tuple[date, time, int]] = None
        rows: list[tuple[Match, ScheduleSlot]] = []
        for match in matches:
            if match.id is None:
                continue
            if (match.runtime_status or "SCHEDULED").upper() in {"FINAL", "IN_PROGRESS"}:
                continue
            slot = self._slot_for_match(match.id)
            if not slot:
                continue
            key = self._slot_sort_key(slot)
            if key <= current_key:
                continue
            if next_slot_key is None or key < next_slot_key:
                next_slot_key = key
                rows = [(match, slot)]
            elif key == next_slot_key:
                rows.append((match, slot))
        if not rows:
            return
        for match, slot in rows:
            for team in self._teams_for_match(match):
                team_id = team.id
                if not team_id:
                    continue
                dedupe_key = self._dedupe_key(
                    "checkin_slot_checkin",
                    f"v{self.version_id}",
                    f"t{team_id}",
                    slot.day_date.isoformat(),
                    str(self._coerce_time(slot.start_time)),
                )
                self._send_template_to_team(
                    team=team,
                    message_type="checkin_slot_checkin",
                    dedupe_key=dedupe_key,
                    match=match,
                    slot=slot,
                    opponent=self._opponent_display(match, team.id),
                )

    def _is_last_started_match_in_timeslot(
        self,
        current_match: Match,
        current_slot: ScheduleSlot,
    ) -> bool:
        """
        Return True only when all assigned matches in this day/time slot
        are already started or finished.
        """
        current_time = self._coerce_time(current_slot.start_time)
        matches = self.session.exec(
            select(Match).where(Match.schedule_version_id == self.version_id)
        ).all()
        for match in matches:
            if match.id is None or match.id == current_match.id:
                continue
            # Ignore placeholder/unassigned rows that cannot be started yet.
            if match.team_a_id is None or match.team_b_id is None:
                continue
            slot = self._slot_for_match(match.id)
            if not slot:
                continue
            if slot.day_date != current_slot.day_date:
                continue
            if self._coerce_time(slot.start_time) != current_time:
                continue
            status = (match.runtime_status or "SCHEDULED").upper()
            if status in {"SCHEDULED", "DELAYED"}:
                return False
        return True

    def run_first_match_24h_reminders(
        self,
        *,
        now_utc: Optional[datetime] = None,
        window_minutes: int = 60,
        dry_run: bool = False,
        force_resend: bool = False,
        resend_run_key: Optional[str] = None,
        template_mode: str = "court_management",
    ) -> Dict[str, Any]:
        """
        Send first-match reminders for each team's first scheduled match.

        Uses the existing first_match template + message_type and shares the same
        dedupe key shape as match-start fallback; whichever path fires first wins.
        """
        stats: Dict[str, Any] = {
            "tournament_id": self.tournament.id,
            "version_id": self.version_id,
            "disabled": False,
            "considered_teams": 0,
            "eligible_teams": 0,
            "outside_window": 0,
            "sent": 0,
            "deduped": 0,
            "blocked_test_mode": 0,
            "blocked_consent": 0,
            "failed": 0,
            "dry_run": dry_run,
            "force_resend": force_resend,
            "resend_run_key": None,
            # Time-window gating is intentionally disabled; keep field for API compatibility.
            "window_minutes": 0,
            "now_utc": (now_utc or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat(),
        }
        if not self._texts_enabled():
            stats["disabled"] = True
            return stats
        normalized_mode = _normalize_sms_template_mode(template_mode)
        message_type = (
            "checkin_first_match"
            if normalized_mode == "checkin_management"
            else "first_match"
        )
        active, _template = self._template_for(message_type)

        tournament_tz_name = (self.tournament.timezone or "UTC").strip() or "UTC"
        try:
            tournament_tz = ZoneInfo(tournament_tz_name)
        except Exception:
            tournament_tz = ZoneInfo("UTC")
            tournament_tz_name = "UTC"
        stats["timezone"] = tournament_tz_name

        first_rows = self._first_match_rows_by_team()
        stats["considered_teams"] = len(first_rows)
        if not active:
            stats["template_inactive"] = True
            if not dry_run:
                return stats
        # Manual first-match runs are intentionally repeatable; each live run
        # gets a unique dedupe suffix so users can re-send whenever needed.
        key = (resend_run_key or "").strip()
        effective_resend_key: Optional[str] = key or f"manual-{std_time.time_ns()}"
        stats["resend_run_key"] = effective_resend_key

        for team_id, row in first_rows.items():
            team = row["team"]
            match = row["match"]
            slot = row["slot"]
            stats["eligible_teams"] += 1

            dedupe_key = self._dedupe_key(
                message_type,
                f"v{self.version_id}",
                f"t{team_id}",
                f"m{match.id}",
                f"rs{effective_resend_key}" if effective_resend_key else None,
            )
            if dry_run:
                projection = self._project_team_send_outcomes(
                    team=team,
                    message_type=message_type,
                    dedupe_key=dedupe_key,
                )
                stats["sent"] += int(projection["sent"])
                stats["deduped"] += int(projection["deduped"])
                stats["blocked_test_mode"] += int(projection["blocked_test_mode"])
                stats["blocked_consent"] += int(projection["blocked_consent"])
                continue

            resp = self._send_template_to_team(
                team=team,
                message_type=message_type,
                dedupe_key=dedupe_key,
                match=match,
                slot=slot,
                opponent=self._opponent_display(match, team.id),
            )
            if resp is None:
                continue
            stats["sent"] += int(resp.sent)
            stats["deduped"] += int(resp.skipped_dedupe)
            stats["blocked_test_mode"] += int(resp.skipped_test_mode)
            stats["blocked_consent"] += int(resp.skipped_consent)
            stats["failed"] += int(resp.failed)

        return stats

    def run_rr_first_match_reminders_for_event(
        self,
        *,
        event_id: int,
        dry_run: bool = False,
        force_resend: bool = False,
        resend_run_key: Optional[str] = None,
        template_mode: str = "court_management",
    ) -> Dict[str, Any]:
        """
        Send each team's first scheduled Round Robin match details for one event.

        Intended trigger: immediately after pool placement is confirmed.
        """
        stats: Dict[str, Any] = {
            "tournament_id": self.tournament.id,
            "version_id": self.version_id,
            "event_id": event_id,
            "disabled": False,
            "considered_teams": 0,
            "eligible_teams": 0,
            "missing_slot": 0,
            "sent": 0,
            "deduped": 0,
            "blocked_test_mode": 0,
            "blocked_consent": 0,
            "failed": 0,
            "dry_run": dry_run,
            "force_resend": force_resend,
            "resend_run_key": None,
        }
        if not self._texts_enabled():
            stats["disabled"] = True
            return stats
        normalized_mode = _normalize_sms_template_mode(template_mode)
        message_type = (
            "checkin_rr_first_match"
            if normalized_mode == "checkin_management"
            else "rr_first_match"
        )
        active, _template = self._template_for(message_type)

        first_rows = self._first_rr_match_rows_by_team(event_id=event_id)
        stats["considered_teams"] = len(first_rows)
        if not active:
            stats["template_inactive"] = True
            if not dry_run:
                return stats
        # Manual RR first-match runs are intentionally repeatable; each live run
        # gets a unique dedupe suffix so users can re-send whenever needed.
        key = (resend_run_key or "").strip()
        effective_resend_key: Optional[str] = key or f"manual-{std_time.time_ns()}"
        stats["resend_run_key"] = effective_resend_key

        for team_id, row in first_rows.items():
            team = row["team"]
            match = row["match"]
            slot = row["slot"]
            if slot is None:
                stats["missing_slot"] += 1
                continue
            stats["eligible_teams"] += 1

            dedupe_key = self._dedupe_key(
                message_type,
                f"v{self.version_id}",
                f"e{event_id}",
                f"t{team_id}",
                f"m{match.id}",
                f"rs{effective_resend_key}" if effective_resend_key else None,
            )
            if dry_run:
                projection = self._project_team_send_outcomes(
                    team=team,
                    message_type=message_type,
                    dedupe_key=dedupe_key,
                )
                stats["sent"] += int(projection["sent"])
                stats["deduped"] += int(projection["deduped"])
                stats["blocked_test_mode"] += int(projection["blocked_test_mode"])
                stats["blocked_consent"] += int(projection["blocked_consent"])
                continue

            resp = self._send_template_to_team(
                team=team,
                message_type=message_type,
                dedupe_key=dedupe_key,
                match=match,
                slot=slot,
                opponent=self._opponent_display(match, team.id),
            )
            if resp is None:
                continue
            stats["sent"] += int(resp.sent)
            stats["deduped"] += int(resp.skipped_dedupe)
            stats["blocked_test_mode"] += int(resp.skipped_test_mode)
            stats["blocked_consent"] += int(resp.skipped_consent)
            stats["failed"] += int(resp.failed)

        return stats

    # ------------------------------------------------------------------
    # Sending/template helpers
    # ------------------------------------------------------------------

    def _send_template_to_team(
        self,
        team: Team,
        message_type: str,
        dedupe_key: str,
        match: Optional[Match],
        slot: Optional[ScheduleSlot],
        opponent: Optional[str],
    ) -> Optional[Any]:
        active, template_body = self._template_for(message_type)
        if not active:
            return None

        message = self._render_template_message(
            team=team,
            template_body=template_body,
            match=match,
            slot=slot,
            opponent=opponent,
        )
        return self._send_message_to_team(
            team=team,
            message=message,
            message_type=message_type,
            dedupe_key=dedupe_key,
            trigger="auto",
        )

    def _send_message_to_team(
        self,
        *,
        team: Team,
        message: str,
        message_type: str,
        dedupe_key: str,
        trigger: str,
    ) -> Any:
        from app.routes.sms import _send_to_teams

        return _send_to_teams(
            session=self.session,
            tournament_id=self.tournament.id,  # type: ignore[arg-type]
            teams=[team],
            message=message,
            message_type=message_type,
            trigger=trigger,
            dedupe_key=dedupe_key,
        )

    def _render_template_message(
        self,
        *,
        team: Team,
        template_body: str,
        match: Optional[Match],
        slot: Optional[ScheduleSlot],
        opponent: Optional[str],
    ) -> str:
        from app.routes.sms import _normalize_sms_message, _render_template

        message = _render_template(
            template_body,
            tournament_name=self.tournament.name,
            team_name=self._team_label(team),
            date=self._format_date(slot.day_date) if slot else None,
            time=self._format_time(slot.start_time) if slot else None,
            court=self._format_court(slot) if slot else None,
            match_code=match.match_code if match else None,
            opponent=opponent,
            day_number=self._day_number(slot.day_date) if slot else None,
        )
        if match and match.match_code:
            suffix = f"({match.match_code})"
            trimmed = message.rstrip()
            if trimmed.endswith(suffix):
                message = trimmed[:-len(suffix)].rstrip()
        return _normalize_sms_message(message)

    def _template_for(self, message_type: str) -> Tuple[bool, str]:
        cached = self._template_cache.get(message_type)
        if cached is not None:
            return cached

        default_body = DEFAULT_SMS_TEMPLATES.get(message_type, "")
        custom = self.session.exec(
            select(SmsTemplate).where(
                SmsTemplate.tournament_id == self.tournament.id,
                SmsTemplate.message_type == message_type,
            )
        ).first()
        if custom is not None:
            resolved = (bool(custom.is_active), custom.template_body)
        else:
            resolved = (True, default_body)
        self._template_cache[message_type] = resolved
        return resolved

    def _is_enabled(self, field_name: str, default: bool) -> bool:
        if self._settings is None:
            self._settings = self.session.exec(
                select(TournamentSmsSettings).where(
                    TournamentSmsSettings.tournament_id == self.tournament.id
                )
            ).first()
        if self._settings is None:
            return default
        if not bool(getattr(self._settings, "texts_enabled", True)):
            return False
        return bool(getattr(self._settings, field_name, default))

    def _texts_enabled(self) -> bool:
        if self._settings is None:
            self._settings = self.session.exec(
                select(TournamentSmsSettings).where(
                    TournamentSmsSettings.tournament_id == self.tournament.id
                )
            ).first()
        if self._settings is None:
            return True
        return bool(getattr(self._settings, "texts_enabled", True))

    def _is_checkin_management(self) -> bool:
        mode = str(getattr(self.tournament, "desk_management_mode", "") or "")
        return mode.strip().lower() == "checkin_management"

    def _project_team_send_outcomes(
        self,
        *,
        team: Team,
        message_type: str,
        dedupe_key: str,
    ) -> Dict[str, int]:
        """Estimate send outcomes for dry-run without logging or sending."""
        from app.models.sms_log import SmsLog
        from app.routes.sms import (
            _allowlist_set,
            _is_phone_send_allowed,
            _player_contacts_only_enabled,
            _team_sms_targets,
        )

        if self._settings is None:
            self._settings = self.session.exec(
                select(TournamentSmsSettings).where(
                    TournamentSmsSettings.tournament_id == self.tournament.id
                )
            ).first()

        player_contacts_only = _player_contacts_only_enabled(
            self.session, self.tournament.id  # type: ignore[arg-type]
        )
        targets = _team_sms_targets(
            session=self.session,
            tournament_id=self.tournament.id,  # type: ignore[arg-type]
            team=team,
            player_contacts_only=player_contacts_only,
        )
        test_mode_enabled = bool(
            self._settings and getattr(self._settings, "test_mode", False)
        )
        allowlist = _allowlist_set(
            getattr(self._settings, "test_allowlist", None)
            if self._settings
            else None
        )

        projected = {
            "sent": 0,
            "deduped": 0,
            "blocked_test_mode": 0,
            "blocked_consent": 0,
            "no_phone": 0,
        }
        if not targets:
            projected["no_phone"] += 1
            return projected
        for target in targets:
            phone = str(target.get("phone") or "").strip()
            if not phone:
                continue
            existing = self.session.exec(
                select(SmsLog.id).where(
                    SmsLog.tournament_id == self.tournament.id,
                    SmsLog.phone_number == phone,
                    SmsLog.message_type == message_type,
                    SmsLog.dedupe_key == dedupe_key,
                )
            ).first()
            if existing:
                projected["deduped"] += 1
                continue
            if test_mode_enabled and phone not in allowlist:
                projected["blocked_test_mode"] += 1
                continue
            is_allowed, _consent = _is_phone_send_allowed(
                session=self.session,
                tournament_id=self.tournament.id,  # type: ignore[arg-type]
                phone_e164=phone,
            )
            if not is_allowed:
                projected["blocked_consent"] += 1
                continue
            projected["sent"] += 1
        return projected

    def _preview_template_to_phone_targets(
        self,
        *,
        team: Team,
        message: str,
        message_type: str,
        dedupe_key: str,
    ) -> list[dict[str, Any]]:
        from app.models.sms_log import SmsLog
        from app.routes.sms import (
            _allowlist_set,
            _is_phone_send_allowed,
            _player_contacts_only_enabled,
            _team_sms_targets,
        )

        if self._settings is None:
            self._settings = self.session.exec(
                select(TournamentSmsSettings).where(
                    TournamentSmsSettings.tournament_id == self.tournament.id
                )
            ).first()

        player_contacts_only = _player_contacts_only_enabled(
            self.session, self.tournament.id  # type: ignore[arg-type]
        )
        targets = _team_sms_targets(
            session=self.session,
            tournament_id=self.tournament.id,  # type: ignore[arg-type]
            team=team,
            player_contacts_only=player_contacts_only,
        )
        test_mode_enabled = bool(
            self._settings and getattr(self._settings, "test_mode", False)
        )
        allowlist = _allowlist_set(
            getattr(self._settings, "test_allowlist", None)
            if self._settings
            else None
        )

        preview_rows: list[dict[str, Any]] = []
        for target in targets:
            phone = str(target.get("phone") or "").strip()
            if not phone:
                continue
            existing = self.session.exec(
                select(SmsLog.id).where(
                    SmsLog.tournament_id == self.tournament.id,
                    SmsLog.phone_number == phone,
                    SmsLog.message_type == message_type,
                    SmsLog.dedupe_key == dedupe_key,
                )
            ).first()
            if existing:
                continue
            if test_mode_enabled and phone not in allowlist:
                continue
            is_allowed, _consent = _is_phone_send_allowed(
                session=self.session,
                tournament_id=self.tournament.id,  # type: ignore[arg-type]
                phone_e164=phone,
            )
            if not is_allowed:
                continue
            preview_rows.append(
                {
                    "team_id": target.get("team_id"),
                    "team_name": target.get("team_name"),
                    "player_id": target.get("player_id"),
                    "player_name": target.get("player_name"),
                    "phone": phone,
                    "message": message,
                }
            )
        return preview_rows

    def _match_finalized_sms_jobs(self, match: Match) -> list[dict[str, Any]]:
        return list(self._match_finalized_sms_plan(match)["jobs"])

    def _match_finalized_sms_plan(self, match: Match) -> Dict[str, Any]:
        if (match.runtime_status or "").upper() != "FINAL":
            return {
                "message_type": "checkin_post_match_next" if self._is_checkin_management() else "post_match_next",
                "disabled_reason": "match_not_final",
                "jobs": [],
            }
        is_checkin_mode = self._is_checkin_management()
        toggle_name = (
            "auto_checkin_post_match_next"
            if is_checkin_mode
            else "auto_post_match_next"
        )
        message_type = (
            "checkin_post_match_next"
            if is_checkin_mode
            else "post_match_next"
        )
        if not self._texts_enabled():
            return {
                "message_type": message_type,
                "disabled_reason": "texts_disabled",
                "jobs": [],
            }
        if not self._is_enabled(toggle_name, default=False):
            return {
                "message_type": message_type,
                "disabled_reason": "automation_disabled",
                "jobs": [],
            }

        current_slot = self._slot_for_match(match.id)
        jobs: list[dict[str, Any]] = []
        for team in self._teams_for_match(match):
            if team.id is None:
                continue
            next_pair = self._next_match_for_team(
                team_id=team.id,
                exclude_match_id=match.id,
                after_slot=current_slot,
            )
            if not next_pair:
                continue
            next_match, next_slot = next_pair
            dedupe_key = self._dedupe_key(
                message_type,
                f"v{self.version_id}",
                f"t{team.id}",
                f"m{next_match.id}",
            )
            active, template_body = self._template_for(message_type)
            if not active:
                return {
                    "message_type": message_type,
                    "disabled_reason": "template_inactive",
                    "jobs": [],
                }
            jobs.append(
                {
                    "team": team,
                    "message_type": message_type,
                    "dedupe_key": dedupe_key,
                    "message": self._render_template_message(
                        team=team,
                        template_body=template_body,
                        match=next_match,
                        slot=next_slot,
                        opponent=self._opponent_display(next_match, team.id),
                    ),
                }
            )
        return {
            "message_type": message_type,
            "disabled_reason": None,
            "jobs": jobs,
        }

    # ------------------------------------------------------------------
    # Match/slot/team helpers
    # ------------------------------------------------------------------

    def _teams_for_match(self, match: Match) -> list[Team]:
        teams: list[Team] = []
        for tid in (match.team_a_id, match.team_b_id):
            if not tid:
                continue
            team = self._team_by_id(tid)
            if team:
                teams.append(team)
        return teams

    def _team_by_id(self, team_id: int) -> Optional[Team]:
        if team_id not in self._team_cache:
            self._team_cache[team_id] = self.session.get(Team, team_id)
        return self._team_cache[team_id]

    def _assignment_for_match(self, match_id: int) -> Optional[MatchAssignment]:
        if match_id not in self._assignment_cache:
            self._assignment_cache[match_id] = self.session.exec(
                select(MatchAssignment).where(
                    MatchAssignment.schedule_version_id == self.version_id,
                    MatchAssignment.match_id == match_id,
                )
            ).first()
        return self._assignment_cache[match_id]

    def _slot_for_match(self, match_id: int) -> Optional[ScheduleSlot]:
        assignment = self._assignment_for_match(match_id)
        if not assignment or assignment.slot_id is None:
            return None
        return self._slot_by_id(assignment.slot_id)

    def _slot_by_id(self, slot_id: int) -> Optional[ScheduleSlot]:
        if slot_id not in self._slot_cache:
            self._slot_cache[slot_id] = self.session.get(ScheduleSlot, slot_id)
        return self._slot_cache[slot_id]

    def _non_final_matches_on_court(self, court_number: int) -> list[Match]:
        slots = self.session.exec(
            select(ScheduleSlot).where(
                ScheduleSlot.schedule_version_id == self.version_id,
                ScheduleSlot.court_number == court_number,
            )
        ).all()
        slot_by_id = {s.id: s for s in slots if s.id is not None}
        slot_ids = [sid for sid in slot_by_id.keys()]
        if not slot_ids:
            return []

        assignments = self.session.exec(
            select(MatchAssignment).where(
                MatchAssignment.schedule_version_id == self.version_id,
                MatchAssignment.slot_id.in_(slot_ids),  # type: ignore[arg-type]
            )
        ).all()
        if not assignments:
            return []

        match_ids = [a.match_id for a in assignments if a.match_id is not None]
        matches = self.session.exec(
            select(Match).where(Match.id.in_(match_ids))  # type: ignore[arg-type]
        ).all() if match_ids else []
        by_id = {m.id: m for m in matches if m.id is not None}

        rows: list[tuple[tuple[date, time, int], Match]] = []
        for a in assignments:
            match = by_id.get(a.match_id)
            slot = slot_by_id.get(a.slot_id)
            if not match or not slot:
                continue
            if (match.runtime_status or "SCHEDULED").upper() in {"FINAL", "IN_PROGRESS", "PAUSED"}:
                continue
            rows.append((self._slot_sort_key(slot), match))
        rows.sort(key=lambda pair: pair[0])
        return [m for _k, m in rows]

    def _is_team_first_match(self, team_id: int, match_id: int) -> bool:
        first_rows = self._first_match_rows_by_team()
        row = first_rows.get(team_id)
        if not row:
            return False
        return row["match"].id == match_id

    def _next_match_for_team(
        self,
        team_id: int,
        exclude_match_id: int,
        after_slot: Optional[ScheduleSlot],
    ) -> Optional[tuple[Match, ScheduleSlot]]:
        """
        Next scheduled appearance for this team after finalizing exclude_match_id.

        Prefer matches strictly after the completed match's slot in calendar order
        (day, time, court). If none qualify — common when the bracket places the
        winner's next round earlier on the clock than the match just finished —
        fall back to the earliest remaining non-FINAL match for the team so both
        sides still get post-match "next match" texts when scheduled.
        """
        matches = self.session.exec(
            select(Match).where(Match.schedule_version_id == self.version_id)
        ).all()
        candidates: list[tuple[tuple[date, time, int, int], Match, ScheduleSlot]] = []
        for m in matches:
            if m.id == exclude_match_id:
                continue
            if team_id not in (m.team_a_id, m.team_b_id):
                continue
            if (m.runtime_status or "SCHEDULED").upper() == "FINAL":
                continue
            slot = self._slot_for_match(m.id)  # type: ignore[arg-type]
            if not slot:
                continue
            key = self._slot_sort_key(slot)
            candidates.append((key, m, slot))
        if not candidates:
            return None
        after_key = self._slot_sort_key(after_slot) if after_slot else None
        preferred = [row for row in candidates if after_key is None or row[0] > after_key]
        pool = preferred if preferred else candidates
        pool.sort(key=lambda row: row[0])
        _key, match, slot = pool[0]
        return match, slot

    def _first_match_rows_by_team(self) -> Dict[int, Dict[str, Any]]:
        """
        Return first scheduled match row per team in this version.

        Each value includes:
          - team: Team
          - match: Match
          - slot: ScheduleSlot
          - sort_key: tuple
        """
        matches = self.session.exec(
            select(Match).where(Match.schedule_version_id == self.version_id)
        ).all()
        result: Dict[int, Dict[str, Any]] = {}
        for m in matches:
            if m.id is None:
                continue
            slot = self._slot_for_match(m.id)
            if not slot:
                continue
            sort_key = self._slot_sort_key(slot)
            for team_id in (m.team_a_id, m.team_b_id):
                if not team_id:
                    continue
                team = self._team_by_id(team_id)
                if not team:
                    continue
                current = result.get(team_id)
                if current is None or sort_key < current["sort_key"]:
                    result[team_id] = {
                        "team": team,
                        "match": m,
                        "slot": slot,
                        "sort_key": sort_key,
                    }
        return result

    def _first_rr_match_rows_by_team(self, *, event_id: int) -> Dict[int, Dict[str, Any]]:
        """
        Return first scheduled RR match row per team for one event in this version.
        """
        matches = self.session.exec(
            select(Match).where(
                Match.schedule_version_id == self.version_id,
                Match.event_id == event_id,
                Match.match_type == "RR",
            )
        ).all()
        result: Dict[int, Dict[str, Any]] = {}
        for m in matches:
            if m.id is None:
                continue
            if (m.runtime_status or "SCHEDULED").upper() == "FINAL":
                continue
            if m.team_a_id is None or m.team_b_id is None:
                continue
            slot = self._slot_for_match(m.id)
            if slot is None:
                # Keep track of team candidate with no slot so caller can report missing_slot.
                sort_key = (date.max, time.max, m.id or 0)
            else:
                sort_key = self._slot_sort_key(slot)
            for team_id in (m.team_a_id, m.team_b_id):
                if not team_id:
                    continue
                team = self._team_by_id(team_id)
                if not team:
                    continue
                current = result.get(team_id)
                if current is None or sort_key < current["sort_key"]:
                    result[team_id] = {
                        "team": team,
                        "match": m,
                        "slot": slot,
                        "sort_key": sort_key,
                    }
        return result

    # ------------------------------------------------------------------
    # Formatting helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _coerce_time(value: object) -> time:
        if isinstance(value, time):
            return value
        if isinstance(value, str):
            parts = value.split(":")
            hour = int(parts[0]) if parts else 0
            minute = int(parts[1]) if len(parts) > 1 else 0
            return time(hour=hour, minute=minute)
        return time(23, 59)

    def _slot_sort_key(self, slot: ScheduleSlot) -> tuple[date, time, int, int]:
        """Order slots by day, start time, court, then id (stable tie-break)."""
        return (
            slot.day_date,
            self._coerce_time(slot.start_time),
            int(slot.court_number or 0),
            slot.id or 0,
        )

    @staticmethod
    def _format_date(day_date: date) -> str:
        weekday = day_date.strftime("%A")
        month_day = day_date.strftime("%B %d").replace(" 0", " ")
        return f"{weekday}, {month_day}"

    @staticmethod
    def _format_time(start_time: object) -> str:
        if isinstance(start_time, str):
            parts = start_time.split(":")
            hour = int(parts[0]) if parts else 0
            minute = int(parts[1]) if len(parts) > 1 else 0
            ampm = "AM" if hour < 12 else "PM"
            hour12 = hour % 12 or 12
            return f"{hour12}:{minute:02d} {ampm}"
        if isinstance(start_time, time):
            return start_time.strftime("%I:%M %p").lstrip("0")
        return ""

    @staticmethod
    def _format_court(slot: ScheduleSlot) -> str:
        label = (slot.court_label or str(slot.court_number)).strip()
        if label.lower().startswith("court"):
            return label
        return f"Court {label}"

    def _day_number(self, day_date: date) -> Optional[int]:
        start = getattr(self.tournament, "start_date", None)
        if not start:
            return None
        return (day_date - start).days + 1

    @staticmethod
    def _team_label(team: Team) -> str:
        return (team.display_name or team.name or f"Team {team.id}").strip()

    def _opponent_display(self, match: Match, team_id: Optional[int]) -> Optional[str]:
        if not team_id:
            return None
        if team_id == match.team_a_id:
            if match.team_b_id:
                t = self._team_by_id(match.team_b_id)
                return self._team_label(t) if t else None
            return (match.placeholder_side_b or "").strip() or None
        if team_id == match.team_b_id:
            if match.team_a_id:
                t = self._team_by_id(match.team_a_id)
                return self._team_label(t) if t else None
            return (match.placeholder_side_a or "").strip() or None
        return None

    @staticmethod
    def _dedupe_key(trigger: str, *parts: object) -> str:
        out = [f"auto:{trigger}"]
        for item in parts:
            if item is None:
                continue
            out.append(str(item))
        return ":".join(out)


def run_first_match_24h_for_tournament(
    session: Session,
    tournament_id: int,
    *,
    now_utc: Optional[datetime] = None,
    window_minutes: int = 60,
    dry_run: bool = False,
    force_resend: bool = False,
    resend_run_key: Optional[str] = None,
    template_mode: str = "court_management",
) -> Dict[str, Any]:
    """Run the 24h first-match reminder scan for a single tournament."""
    tournament = session.get(Tournament, tournament_id)
    if not tournament:
        return {
            "tournament_id": tournament_id,
            "error": "tournament_not_found",
        }

    from app.routes.sms import _resolve_match_lookup_version

    version = _resolve_match_lookup_version(session, tournament)
    if not version:
        return {
            "tournament_id": tournament_id,
            "version_id": None,
            "disabled": False,
            "no_active_version": True,
            "considered_teams": 0,
            "eligible_teams": 0,
            "outside_window": 0,
            "sent": 0,
            "deduped": 0,
            "blocked_test_mode": 0,
            "blocked_consent": 0,
            "failed": 0,
            "dry_run": dry_run,
            "window_minutes": 0,
        }
    engine = SmsAutomationEngine(session, tournament, version.id)  # type: ignore[arg-type]
    return engine.run_first_match_24h_reminders(
        now_utc=now_utc,
        window_minutes=window_minutes,
        dry_run=dry_run,
        force_resend=force_resend,
        resend_run_key=resend_run_key,
        template_mode=template_mode,
    )


def run_rr_first_match_for_event(
    session: Session,
    tournament_id: int,
    *,
    event_id: int,
    dry_run: bool = False,
    force_resend: bool = False,
    resend_run_key: Optional[str] = None,
    template_mode: str = "court_management",
) -> Dict[str, Any]:
    """Run Round Robin first-match reminders for one event."""
    tournament = session.get(Tournament, tournament_id)
    if not tournament:
        return {
            "tournament_id": tournament_id,
            "event_id": event_id,
            "error": "tournament_not_found",
        }

    from app.routes.sms import _resolve_match_lookup_version

    version = _resolve_match_lookup_version(session, tournament)
    if not version:
        return {
            "tournament_id": tournament_id,
            "version_id": None,
            "event_id": event_id,
            "disabled": False,
            "no_active_version": True,
            "considered_teams": 0,
            "eligible_teams": 0,
            "missing_slot": 0,
            "sent": 0,
            "deduped": 0,
            "blocked_test_mode": 0,
            "blocked_consent": 0,
            "failed": 0,
            "dry_run": dry_run,
            "force_resend": force_resend,
            "resend_run_key": None,
        }

    engine = SmsAutomationEngine(session, tournament, version.id)  # type: ignore[arg-type]
    return engine.run_rr_first_match_reminders_for_event(
        event_id=event_id,
        dry_run=dry_run,
        force_resend=force_resend,
        resend_run_key=resend_run_key,
        template_mode=template_mode,
    )


def run_first_match_24h_for_all_tournaments(
    session: Session,
    *,
    now_utc: Optional[datetime] = None,
    window_minutes: int = 60,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Run first-match reminder scan across all tournaments."""
    tournament_ids = session.exec(select(Tournament.id)).all()
    runs = []
    aggregate = {
        "tournaments": 0,
        "sent": 0,
        "deduped": 0,
        "blocked_test_mode": 0,
        "blocked_consent": 0,
        "failed": 0,
        "eligible_teams": 0,
        "considered_teams": 0,
        "outside_window": 0,
    }
    for tid in tournament_ids:
        run = run_first_match_24h_for_tournament(
            session=session,
            tournament_id=tid,
            now_utc=now_utc,
            window_minutes=window_minutes,
            dry_run=dry_run,
        )
        runs.append(run)
        aggregate["tournaments"] += 1
        for key in (
            "sent",
            "deduped",
            "blocked_test_mode",
            "blocked_consent",
            "failed",
            "eligible_teams",
            "considered_teams",
            "outside_window",
        ):
            aggregate[key] += int(run.get(key, 0) or 0)
    return {
        "aggregate": aggregate,
        "runs": runs,
    }


def _runner_interval_seconds() -> int:
    raw = os.getenv("SMS_FIRST_MATCH_RUNNER_INTERVAL_SECONDS", "0").strip()
    try:
        return max(0, int(raw))
    except ValueError:
        return 0


def _runner_window_minutes() -> int:
    raw = os.getenv("SMS_FIRST_MATCH_REMINDER_WINDOW_MINUTES", "60").strip()
    try:
        return max(1, int(raw))
    except ValueError:
        return 60


def start_first_match_runner_if_enabled() -> None:
    """
    Start background first-match reminder runner when interval is configured.

    Disabled by default; set SMS_FIRST_MATCH_RUNNER_INTERVAL_SECONDS > 0 to enable.
    """
    # Disabled while first-match messaging is manual-only.
    logger.info("First-match reminder runner disabled (manual-only mode)")


def _runner_loop(interval_seconds: int) -> None:
    while True:
        started = std_time.time()
        try:
            with Session(engine) as session:
                summary = run_first_match_24h_for_all_tournaments(
                    session=session,
                    window_minutes=_runner_window_minutes(),
                    dry_run=False,
                )
            agg = summary.get("aggregate", {})
            sent = int(agg.get("sent", 0))
            failed = int(agg.get("failed", 0))
            if sent or failed:
                logger.info(
                    "First-match runner cycle: tournaments=%s sent=%s failed=%s deduped=%s",
                    agg.get("tournaments", 0),
                    sent,
                    failed,
                    agg.get("deduped", 0),
                )
        except Exception:
            logger.exception("First-match reminder runner cycle failed")

        elapsed = std_time.time() - started
        delay = max(1.0, interval_seconds - elapsed)
        std_time.sleep(delay)

