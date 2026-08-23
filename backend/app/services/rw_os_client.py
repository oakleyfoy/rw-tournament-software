"""Read-only RW-OS integration client. Fixture-first; never writes."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Optional

from app.services.rw_os_fixtures import get_fixture_event, list_fixture_events, mutate_fixture_for_refresh

ALLOWED_METHODS = frozenset({"GET"})


class RwOsClientError(Exception):
    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


class RwOsReadOnlyError(RwOsClientError):
    def __init__(self, method: str):
        super().__init__(f"RW-OS client is read-only; {method} is not allowed.", 405)


def use_fixtures() -> bool:
    flag = os.getenv("RW_OS_USE_FIXTURES", "true").strip().lower()
    if flag in {"0", "false", "no"}:
        return False
    if not os.getenv("RW_OS_BASE_URL", "").strip() or not os.getenv("RW_OS_API_KEY", "").strip():
        return True
    return flag in {"1", "true", "yes"}


class RwOsClient:
    """GET-only client. Live mode still never issues writes."""

    def __init__(self, *, fixtures: Optional[bool] = None):
        self.fixtures = use_fixtures() if fixtures is None else fixtures
        self.base_url = os.getenv("RW_OS_BASE_URL", "").rstrip("/")
        self.api_key = os.getenv("RW_OS_API_KEY", "")
        self.organization_slug = os.getenv("RW_OS_ORGANIZATION_SLUG", "rw")

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

    def _get(self, path: str, params: dict[str, str]) -> dict[str, Any]:
        return self._request("GET", path, params)

    def _request(self, method: str, path: str, params: Optional[dict[str, str]] = None) -> dict[str, Any]:
        if method.upper() not in ALLOWED_METHODS:
            raise RwOsReadOnlyError(method)
        if not self.base_url or not self.api_key:
            raise RwOsClientError("RW-OS live client is not configured.", 503)
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
            with urllib.request.urlopen(request, timeout=20) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise RwOsClientError(f"RW-OS request failed ({exc.code}).", exc.code) from exc
        except urllib.error.URLError as exc:
            raise RwOsClientError("RW-OS request failed.", 502) from exc
        if isinstance(body, dict) and body.get("success") is True and "data" in body:
            return body["data"]
        if isinstance(body, dict):
            return body
        raise RwOsClientError("RW-OS returned an unexpected payload.", 502)
