"""Read-only RW-OS integration client. Never writes."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Optional

from app.services.rw_os_fixtures import get_fixture_event, list_fixture_events, mutate_fixture_for_refresh

ALLOWED_METHODS = frozenset({"GET"})
LIVE_REQUEST_TIMEOUT_SECONDS = 20
LIVE_CONFIG_ERROR = "RW-OS live integration is not configured."
INVALID_RESPONSE_ERROR = "RW-OS returned an invalid response."
REQUEST_FAILED_ERROR = "RW-OS request failed."
PRODUCTION_FIXTURES_ERROR = "RW-OS fixtures are not allowed in production."

_TRUTHY = frozenset({"1", "true", "yes"})
_FALSY = frozenset({"0", "false", "no"})


class RwOsClientError(Exception):
    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


class RwOsReadOnlyError(RwOsClientError):
    def __init__(self, method: str):
        super().__init__(f"RW-OS client is read-only; {method} is not allowed.", 405)


def is_production_runtime() -> bool:
    """Use Render's injected flag plus conventional production env names.

    This project has no separate APP_ENV system. Render sets RENDER=true on
    deployed services, which is the production indicator we already have.
    """
    if os.getenv("RENDER", "").strip().lower() in _TRUTHY:
        return True
    env = (os.getenv("ENVIRONMENT") or os.getenv("APP_ENV") or "").strip().lower()
    return env in {"prod", "production"}


def _explicit_fixture_flag() -> Optional[bool]:
    raw = os.getenv("RW_OS_USE_FIXTURES")
    if raw is None or not raw.strip():
        return None
    value = raw.strip().lower()
    if value in _FALSY:
        return False
    if value in _TRUTHY:
        return True
    return None


def use_fixtures() -> bool:
    """Fixtures are a local/test default. Production fails closed."""
    explicit = _explicit_fixture_flag()
    if is_production_runtime():
        if explicit is True:
            raise RwOsClientError(PRODUCTION_FIXTURES_ERROR, 503)
        return False
    if explicit is False:
        return False
    return True


class RwOsClient:
    """GET-only client. Live mode never issues writes and never falls back to fixtures."""

    def __init__(self, *, fixtures: Optional[bool] = None):
        self.base_url = os.getenv("RW_OS_BASE_URL", "").rstrip("/")
        self.api_key = os.getenv("RW_OS_API_KEY", "")
        self.organization_slug = os.getenv("RW_OS_ORGANIZATION_SLUG", "rw")
        if fixtures is None:
            self.fixtures = use_fixtures()
        else:
            if fixtures and is_production_runtime():
                raise RwOsClientError(PRODUCTION_FIXTURES_ERROR, 503)
            self.fixtures = fixtures

    def list_events(self, *, include_historical: bool = False) -> list[dict[str, Any]]:
        if self.fixtures:
            return list_fixture_events(include_historical=include_historical)
        params = {
            "organizationSlug": self.organization_slug,
        }
        if not include_historical:
            params["status"] = "upcoming"
        payload = self._get("/api/integrations/tournament-software/events", params)
        return list(payload.get("events") or payload)

    def get_event(self, tournament_id: int) -> dict[str, Any]:
        if self.fixtures:
            event = get_fixture_event(tournament_id)
            if not event:
                raise RwOsClientError(f"RW-OS event {tournament_id} was not found.", 404)
            return event
        payload = self._get(
            f"/api/integrations/tournament-software/events/{tournament_id}",
            {"organizationSlug": self.organization_slug},
        )
        return payload

    def refresh_event(self, tournament_id: int, previous: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        if self.fixtures:
            event = get_fixture_event(tournament_id)
            if not event:
                raise RwOsClientError(f"RW-OS event {tournament_id} was not found.", 404)
            return mutate_fixture_for_refresh(event)
        return self.get_event(tournament_id)

    def _ensure_live_configured(self) -> None:
        if not self.base_url or not self.api_key:
            raise RwOsClientError(LIVE_CONFIG_ERROR, 503)

    def _get(self, path: str, params: dict[str, str]) -> dict[str, Any]:
        return self._request("GET", path, params)

    def _request(self, method: str, path: str, params: Optional[dict[str, str]] = None) -> dict[str, Any]:
        if method.upper() not in ALLOWED_METHODS:
            raise RwOsReadOnlyError(method)
        self._ensure_live_configured()
        query = urllib.parse.urlencode(params or {})
        url = f"{self.base_url}{path}"
        if query:
            url = f"{url}?{query}"
        request = urllib.request.Request(
            url,
            method="GET",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Accept": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=LIVE_REQUEST_TIMEOUT_SECONDS) as response:
                raw_bytes = response.read()
        except urllib.error.HTTPError as exc:
            raise RwOsClientError(f"RW-OS request failed ({exc.code}).", exc.code) from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise RwOsClientError(REQUEST_FAILED_ERROR, 502) from exc
        try:
            body = json.loads(raw_bytes.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise RwOsClientError(INVALID_RESPONSE_ERROR, 502) from exc
        if isinstance(body, dict) and body.get("success") is True and "data" in body:
            return body["data"]
        if isinstance(body, dict):
            return body
        raise RwOsClientError(INVALID_RESPONSE_ERROR, 502)
