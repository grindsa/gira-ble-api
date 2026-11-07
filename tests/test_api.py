"""HTTP API smoke tests without BLE hardware."""

from __future__ import annotations

from fastapi.testclient import TestClient

from gira_ble_api.api import create_app
from gira_ble_api.config import AppConfig, ThermostatConfig


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


def test_get_thermostat() -> None:
    client = _app()
    r = client.get("/thermostats/living")
    assert r.status_code == 200
    assert r.json()["id"] == "living"


def test_get_unknown() -> None:
    client = _app()
    r = client.get("/thermostats/nope")
    assert r.status_code == 404
