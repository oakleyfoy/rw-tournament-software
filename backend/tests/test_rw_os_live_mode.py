import json
import urllib.error
import urllib.request

import pytest
from fastapi.testclient import TestClient

from app.services.rw_os_client import (
    INVALID_RESPONSE_ERROR,
    LIVE_CONFIG_ERROR,
    PRODUCTION_FIXTURES_ERROR,
    REQUEST_FAILED_ERROR,
    RwOsClient,
    RwOsClientError,
    is_production_runtime,
    use_fixtures,
)

PRODUCTION_KEYS = ("RENDER", "ENVIRONMENT", "APP_ENV")
RW_OS_KEYS = (
    "RW_OS_USE_FIXTURES",
    "RW_OS_BASE_URL",
    "RW_OS_API_KEY",
    "RW_OS_ORGANIZATION_SLUG",
)


@pytest.fixture
def clean_rw_os_env(monkeypatch):
    for key in (*PRODUCTION_KEYS, *RW_OS_KEYS):
        monkeypatch.delenv(key, raising=False)


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def _forbid_fixture_fallback(monkeypatch):
    def boom(*_args, **_kwargs):
        raise AssertionError("fixture fallback is not allowed")

    monkeypatch.setattr("app.services.rw_os_client.list_fixture_events", boom)
    monkeypatch.setattr("app.services.rw_os_client.get_fixture_event", boom)


def test_a_development_omitted_fixtures_uses_local_fixtures(clean_rw_os_env):
    assert is_production_runtime() is False
    assert use_fixtures() is True
    client = RwOsClient()
    assert client.fixtures is True
    events = client.list_events()
    assert {event["tournamentId"] for event in events} >= {148, 244, 280}


def test_b_production_omitted_fixtures_uses_live_mode(clean_rw_os_env, monkeypatch):
    monkeypatch.setenv("RENDER", "true")
    assert is_production_runtime() is True
    assert use_fixtures() is False
    client = RwOsClient()
    assert client.fixtures is False


def test_c_production_live_missing_url_is_config_error(clean_rw_os_env, monkeypatch):
    monkeypatch.setenv("RENDER", "true")
    monkeypatch.setenv("RW_OS_API_KEY", "test-key")
    _forbid_fixture_fallback(monkeypatch)
    client = RwOsClient()
    with pytest.raises(RwOsClientError, match=LIVE_CONFIG_ERROR) as exc:
        client.list_events()
    assert exc.value.status_code == 503


def test_d_production_live_missing_key_is_config_error(clean_rw_os_env, monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("RW_OS_BASE_URL", "https://example-rw-os-api")
    _forbid_fixture_fallback(monkeypatch)
    client = RwOsClient()
    with pytest.raises(RwOsClientError, match=LIVE_CONFIG_ERROR) as exc:
        client.list_events()
    assert exc.value.status_code == 503


def test_e_production_with_url_and_key_uses_live_client(clean_rw_os_env, monkeypatch):
    monkeypatch.setenv("RENDER", "true")
    monkeypatch.setenv("RW_OS_BASE_URL", "https://example-rw-os-api")
    monkeypatch.setenv("RW_OS_API_KEY", "test-key")
    _forbid_fixture_fallback(monkeypatch)
    called = {}

    def fake_urlopen(request, timeout=None):
        called["url"] = request.full_url
        called["authorization"] = request.get_header("Authorization")
        called["timeout"] = timeout
        return FakeResponse({"success": True, "data": {"events": [{"tournamentId": 244, "eventName": "Live"}]}})

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    client = RwOsClient()
    assert client.fixtures is False
    events = client.list_events()
    assert events == [{"tournamentId": 244, "eventName": "Live"}]
    assert called["url"].startswith("https://example-rw-os-api/api/integrations/tournament-software/events")
    assert "organizationSlug=rw" in called["url"]
    assert called["authorization"] == "Bearer test-key"
    assert called["timeout"] == 20


def test_f_live_401_does_not_fall_back_to_fixtures(clean_rw_os_env, monkeypatch):
    monkeypatch.setenv("RENDER", "true")
    monkeypatch.setenv("RW_OS_BASE_URL", "https://example-rw-os-api")
    monkeypatch.setenv("RW_OS_API_KEY", "test-key")
    _forbid_fixture_fallback(monkeypatch)

    def fake_urlopen(request, timeout=None):
        raise urllib.error.HTTPError(request.full_url, 401, "Unauthorized", hdrs=None, fp=None)

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(RwOsClientError, match=r"RW-OS request failed \(401\)\.") as exc:
        RwOsClient().list_events()
    assert exc.value.status_code == 401


def test_g_live_403_does_not_fall_back_to_fixtures(clean_rw_os_env, monkeypatch):
    monkeypatch.setenv("RENDER", "true")
    monkeypatch.setenv("RW_OS_BASE_URL", "https://example-rw-os-api")
    monkeypatch.setenv("RW_OS_API_KEY", "test-key")
    _forbid_fixture_fallback(monkeypatch)

    def fake_urlopen(request, timeout=None):
        raise urllib.error.HTTPError(request.full_url, 403, "Forbidden", hdrs=None, fp=None)

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(RwOsClientError, match=r"RW-OS request failed \(403\)\.") as exc:
        RwOsClient().get_event(244)
    assert exc.value.status_code == 403


def test_h_live_network_failure_is_502_without_fixtures(clean_rw_os_env, monkeypatch):
    monkeypatch.setenv("RENDER", "true")
    monkeypatch.setenv("RW_OS_BASE_URL", "https://example-rw-os-api")
    monkeypatch.setenv("RW_OS_API_KEY", "test-key")
    _forbid_fixture_fallback(monkeypatch)

    def fake_urlopen(request, timeout=None):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(RwOsClientError, match=REQUEST_FAILED_ERROR) as exc:
        RwOsClient().list_events()
    assert exc.value.status_code == 502


def test_i_live_malformed_json_is_controlled_502(clean_rw_os_env, monkeypatch):
    monkeypatch.setenv("RENDER", "true")
    monkeypatch.setenv("RW_OS_BASE_URL", "https://example-rw-os-api")
    monkeypatch.setenv("RW_OS_API_KEY", "test-key")
    _forbid_fixture_fallback(monkeypatch)

    def fake_urlopen(request, timeout=None):
        return FakeResponse(b"<html>not json</html>")

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(RwOsClientError, match=INVALID_RESPONSE_ERROR) as exc:
        RwOsClient().list_events()
    assert exc.value.status_code == 502
    assert "not json" not in str(exc.value)
    assert "test-key" not in str(exc.value)


def test_j_explicit_production_fixtures_are_rejected(clean_rw_os_env, monkeypatch, client: TestClient):
    monkeypatch.setenv("RENDER", "true")
    monkeypatch.setenv("RW_OS_USE_FIXTURES", "true")
    monkeypatch.setenv("RW_OS_BASE_URL", "https://example-rw-os-api")
    monkeypatch.setenv("RW_OS_API_KEY", "test-key")
    with pytest.raises(RwOsClientError, match=PRODUCTION_FIXTURES_ERROR) as exc:
        use_fixtures()
    assert exc.value.status_code == 503
    with pytest.raises(RwOsClientError, match=PRODUCTION_FIXTURES_ERROR):
        RwOsClient()
    with pytest.raises(RwOsClientError, match=PRODUCTION_FIXTURES_ERROR):
        RwOsClient(fixtures=True)
    response = client.get("/api/rw-os/events")
    assert response.status_code == 503
    assert response.json()["detail"] == PRODUCTION_FIXTURES_ERROR
