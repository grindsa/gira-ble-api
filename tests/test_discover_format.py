"""Unit tests for discovery table formatting (no BLE hardware)."""

from __future__ import annotations

from gira_ble_api.ble.discover import DiscoveredDevice, format_discovery_table


def test_format_empty() -> None:
    text = format_discovery_table([])
    assert "No Gira devices" in text


def test_format_row() -> None:
    devices = [
        DiscoveredDevice(
            address="AA:BB:CC:DD:EE:FF",
            name="Gira",
            rssi=-55,
            temperature_c=21.0,
            setpoint_c=20.0,
            kind_hints=["thermostat"],
            ad_count=3,
        )
    ]
    text = format_discovery_table(devices)
    assert "AA:BB:CC:DD:EE:FF" in text
    assert "thermostat" in text
    assert "21.00" in text
    assert "Copy ADDRESS" in text
