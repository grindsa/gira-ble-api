"""API token auth tests (no BLE)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from gira_ble_api.api import create_app
from gira_ble_api.api.auth import extract_bearer_token, token_is_allowed
from gira_ble_api.config import AppConfig, ThermostatConfig, parse_api_tokens


def _client(tokens) -> TestClient:
    config = AppConfig(
        host="127.0.0.1",
        port=8787,
        api_tokens=tokens,
        thermostats=[
            ThermostatConfig(id="living", name="Wohnzimmer", mac="AA:BB:CC:DD:EE:FF")
        ],
    )
    return TestClient(create_app(config, enable_ble=False))


def test_parse_api_tokens_comma_string() -> None:
    assert parse_api_tokens("a, b, c") == ["a", "b", "c"]
    assert parse_api_tokens("") == []
    assert parse_api_tokens(None) == []


def test_parse_api_tokens_list() -> None:
    assert parse_api_tokens(["a", " b "]) == ["a", "b"]


def test_config_accepts_comma_string() -> None:
    cfg = AppConfig.model_validate({"api_tokens": "one, two"})
    assert cfg.api_tokens == ["one", "two"]


def test_token_is_allowed() -> None:
    assert token_is_allowed("secret", ["secret", "other"]) is True
    assert token_is_allowed("nope", ["secret"]) is False
    assert token_is_allowed("", ["secret"]) is False


def test_extract_bearer_token() -> None:
    assert extract_bearer_token("Bearer abc") == "abc"
    assert extract_bearer_token("bearer abc") == "abc"
    assert extract_bearer_token("Basic abc") is None
    assert extract_bearer_token(None) is None


def test_no_tokens_open_access() -> None:
    client = _client([])
    assert client.get("/thermostats").status_code == 200
    assert client.get("/health").status_code == 200


def test_auth_required_when_configured() -> None:
    client = _client("dashboard, laptop")
    assert client.get("/health").status_code == 200
    denied = client.get("/thermostats")
    assert denied.status_code == 401
    assert denied.json()["detail"]["code"] == "unauthorized"


def test_auth_accepts_valid_bearer() -> None:
    client = _client("dashboard, laptop")
    ok = client.get(
        "/thermostats",
        headers={"Authorization": "Bearer laptop"},
    )
    assert ok.status_code == 200
    assert len(ok.json()) == 1


def test_auth_rejects_wrong_token() -> None:
    client = _client(["dashboard"])
    bad = client.get(
        "/thermostats",
        headers={"Authorization": "Bearer wrong"},
    )
    assert bad.status_code == 401
