"""HTTP API smoke tests without BLE hardware."""

from __future__ import annotations

from fastapi.testclient import TestClient

from gira_ble_api.api import create_app
from gira_ble_api.config import AppConfig, CoverConfig, ThermostatConfig


def _app() -> TestClient:
    config = AppConfig(
        host="127.0.0.1",
        port=8787,
        thermostats=[
            ThermostatConfig(
                id="living",
                name="Wohnzimmer",
                mac="AA:BB:CC:DD:EE:FF",
            )
        ],
        covers=[
            CoverConfig(
                id="living_blind",
                name="Wohnzimmer Jalousie",
                mac="11:22:33:44:55:66",
            )
        ],
    )
    return TestClient(create_app(config, enable_ble=False))


def test_health() -> None:
    client = _app()
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"ok": True}


def test_list_thermostats() -> None:
    client = _app()
    r = client.get("/thermostats")
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 1
    assert data[0]["id"] == "living"
    assert data[0]["name"] == "Wohnzimmer"
    assert data[0]["mac"] == "AA:BB:CC:DD:EE:FF"
    assert data[0]["online"] is False
    assert data[0]["temperature_c"] is None
    assert data[0]["heating_active"] is None
    assert data[0]["last_seen_at"] is None
    assert data[0]["updated_at"] is None
    assert "paired" in data[0]


def test_get_thermostat() -> None:
    client = _app()
    r = client.get("/thermostats/living")
    assert r.status_code == 200
    assert r.json()["id"] == "living"
    assert r.json()["heating_active"] is None


def test_get_thermostat_refresh_requires_ble() -> None:
    client = _app()
    r = client.get("/thermostats/living", params={"refresh": "1"})
    assert r.status_code == 503
    assert r.json()["detail"]["code"] == "ble_disabled"


def test_get_unknown() -> None:
    client = _app()
    r = client.get("/thermostats/nope")
    assert r.status_code == 404


def test_list_covers() -> None:
    client = _app()
    r = client.get("/covers")
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 1
    assert data[0]["id"] == "living_blind"
    assert data[0]["name"] == "Wohnzimmer Jalousie"
    assert data[0]["mac"] == "11:22:33:44:55:66"
    assert data[0]["online"] is False
    assert data[0]["position_pct"] is None
    assert "paired" in data[0]


def test_get_cover() -> None:
    client = _app()
    r = client.get("/covers/living_blind")
    assert r.status_code == 200
    assert r.json()["id"] == "living_blind"


def test_get_unknown_cover() -> None:
    client = _app()
    r = client.get("/covers/nope")
    assert r.status_code == 404


def test_cover_command_requires_ble() -> None:
    client = _app()
    r = client.post("/covers/living_blind/command", json={"action": "up"})
    assert r.status_code == 503
    assert r.json()["detail"]["code"] == "ble_disabled"


def test_cover_command_validation() -> None:
    client = _app()
    both = client.post(
        "/covers/living_blind/command",
        json={"action": "up", "position": 50},
    )
    assert both.status_code == 422
    neither = client.post("/covers/living_blind/command", json={})
    assert neither.status_code == 422
