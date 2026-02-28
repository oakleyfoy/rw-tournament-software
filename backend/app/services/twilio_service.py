"""Twilio SMS service wrapper.

Thin wrapper around the Twilio REST API for sending SMS messages.
Handles single sends, bulk sends, and phone number formatting.
"""

import logging
import os
import re
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)


def format_e164(phone: str, default_country: str = "1") -> str:
    """
    Normalize a phone number to E.164 format (+1XXXXXXXXXX for US).

    Accepts:
      - +15551234567  (already E.164)
      - 15551234567   (missing +)
      - 5551234567    (10-digit US)
      - (555) 123-4567
      - 555-123-4567
      - 555.123.4567
      - 9013593035    (10-digit, as seen in WAR Tournaments)

    Returns:
      - "+15551234567"

    Raises:
      - ValueError if phone can't be parsed
    """
    if not phone or not phone.strip():
        raise ValueError("Phone number is empty")

    # Strip everything except digits and leading +
    digits = re.sub(r"[^\d]", "", phone)

    if len(digits) == 10:
        # US 10-digit: prepend country code
        return f"+{default_country}{digits}"
    elif len(digits) == 11 and digits.startswith(default_country):
        # US 11-digit with country code
        return f"+{digits}"
    elif len(digits) >= 10 and phone.startswith("+"):
        # International format
        return f"+{digits}"
    else:
        raise ValueError(
            f"Cannot parse phone number: '{phone}'. "
            f"Expected 10-digit US number or E.164 format."
        )


def validate_e164(phone: str) -> bool:
    """Check if a phone number is valid E.164 format."""
    return bool(re.match(r"^\+[1-9]\d{6,14}$", phone))


def get_team_phone_numbers(team) -> list[str]:
    """
    Extract all valid phone numbers from a Team object.

    Reads p1_cell and p2_cell, formats to E.164, skips blanks/invalid.
    Both P1 and P2 get texts.

    Returns:
        List of valid E.164 phone numbers (0-2 items)
    """
    phones = []
    for field in [team.p1_cell, team.p2_cell]:
        if not field or not field.strip():
            continue
        # Skip placeholder values
        if field.strip() in ("—", "-", "N/A", "n/a", "none", "None"):
            continue
        try:
            formatted = format_e164(field.strip())
            if formatted not in phones:  # Dedupe (P1 and P2 might be same person)
                phones.append(formatted)
        except ValueError:
            logger.warning(f"Skipping invalid phone number on team {team.id}: '{field}'")
    return phones


class TwilioService:
    """
    Wrapper around Twilio REST API for sending SMS.

    Reads credentials from environment variables:
      - TWILIO_ACCOUNT_SID
      - TWILIO_AUTH_TOKEN
      - TWILIO_FROM_NUMBER

    If credentials are not set, operates in dry-run mode
    (logs messages but doesn't send).
    """

    def __init__(self):
        self.account_sid = os.getenv("TWILIO_ACCOUNT_SID", "")
        self.auth_token = os.getenv("TWILIO_AUTH_TOKEN", "")
        self.from_number = os.getenv("TWILIO_FROM_NUMBER", "")
        self.client = None
        self.dry_run = False

        if self.account_sid and self.auth_token and self.from_number:
            try:
                from twilio.rest import Client

                self.client = Client(self.account_sid, self.auth_token)
                logger.info("Twilio client initialized successfully.")
            except ImportError:
                logger.warning(
                    "twilio package not installed. Running in dry-run mode. "
                    "Install with: pip install twilio"
                )
                self.dry_run = True
            except Exception as e:
                logger.error(f"Failed to initialize Twilio client: {e}")
                self.dry_run = True
        else:
            logger.warning(
                "Twilio credentials not configured. Running in dry-run mode. "
                "Set TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM_NUMBER."
            )
            self.dry_run = True

    def send_sms(self, to: str, body: str) -> dict:
        """
        Send a single SMS message.

        Args:
            to: Recipient phone number (E.164 format)
            body: Message text (max 1600 chars for Twilio)

        Returns:
            dict with keys: sid, status, error
        """
        if not validate_e164(to):
            return {
                "sid": None,
                "status": "failed",
                "error": f"Invalid phone number format: {to}",
            }

        # Truncate body if too long (Twilio max is 1600 chars)
        if len(body) > 1600:
            body = body[:1597] + "..."

        if self.dry_run:
            logger.info(f"[DRY RUN] SMS to {to}: {body[:80]}...")
            return {
                "sid": f"DRY_RUN_{datetime.now(timezone.utc).isoformat()}",
                "status": "dry_run",
                "error": None,
            }

        try:
            message = self.client.messages.create(
                body=body,
                from_=self.from_number,
                to=to,
            )
            logger.info(
                f"SMS sent to {to}: SID={message.sid}, status={message.status}"
            )
            return {
                "sid": message.sid,
                "status": message.status,
                "error": None,
            }
        except Exception as e:
            logger.error(f"Failed to send SMS to {to}: {e}")
            return {
                "sid": None,
                "status": "failed",
                "error": str(e),
            }

    def send_bulk(self, recipients: list[dict]) -> dict:
        """
        Send SMS to multiple recipients.

        Args:
            recipients: List of dicts with keys: phone, body, team_id (optional)

        Returns:
            dict with keys: total, sent, failed, results
        """
        results = []
        sent_count = 0
        failed_count = 0

        for r in recipients:
            phone = r.get("phone", "")
            body = r.get("body", "")
            team_id = r.get("team_id")

            result = self.send_sms(phone, body)
            result["phone"] = phone
            result["team_id"] = team_id
            results.append(result)

            if result["status"] in ("queued", "sent", "dry_run"):
                sent_count += 1
            else:
                failed_count += 1

        return {
            "total": len(recipients),
            "sent": sent_count,
            "failed": failed_count,
            "results": results,
        }

    @property
    def is_configured(self) -> bool:
        """Check if Twilio is properly configured (not in dry-run mode)."""
        return not self.dry_run


# Singleton instance
_twilio_service: Optional[TwilioService] = None


def get_twilio_service() -> TwilioService:
    """Get or create the singleton TwilioService instance."""
    global _twilio_service
    if _twilio_service is None:
        _twilio_service = TwilioService()
    return _twilio_service
