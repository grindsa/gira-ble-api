"""Online flag must not age while the BLE scanner is paused for GATT."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from gira_ble_api.config import ThermostatConfig
from gira_ble_api.protocol.ads import AdvertisementUpdate
from gira_ble_api.state import DeviceStore


def test_online_frozen_during_scan_pause() -> None:
    store = DeviceStore.from_config(
        [ThermostatConfig(id="living", name="Wohnzimmer", mac="AA:BB:CC:DD:EE:FF")],
        online_timeout_s=30.0,
    )
    store.apply_advertisement(
        "AA:BB:CC:DD:EE:FF",
        AdvertisementUpdate(temperature_c=21.0),
        rssi=-60,
    )
    assert store.get("living")["online"] is True

    store.begin_scan_pause()
    # Simulate wall-clock advancing far beyond online_timeout while paused.
    paused_at = store._scan_paused_since
    assert paused_at is not None
    store._thermostats["living"].last_seen_at = paused_at - timedelta(seconds=5)

    row = store.get("living")
    assert row["online"] is True

    store.end_scan_pause()
    store._thermostats["living"].last_seen_at = datetime.now(timezone.utc) - timedelta(
        seconds=60
    )
    assert store.get("living")["online"] is False
