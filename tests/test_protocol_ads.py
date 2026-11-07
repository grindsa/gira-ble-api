"""Unit tests for advertisement parsing with captured example bytes."""

from __future__ import annotations

from gira_ble_api.protocol.ads import parse_manufacturer_data
from gira_ble_api.protocol.commands import build_setpoint_command


def test_parse_current_temperature_frame() -> None:
    # F7 01 41 01 FE 10 01 0C 14 — actual temp (community / stho prefix)
    payload = bytes.fromhex("F7014101FE10010C14")
    update = parse_manufacturer_data(payload)
    assert update.temperature_c == 20.84  # 3092 → high-scale decode
    assert update.setpoint_c is None


def test_parse_setpoint_frame() -> None:
    # F7 00 65 01 FF 10 01 06 0E — setpoint 15.50 °C
    payload = bytes.fromhex("F7006501FF1001060E")
    update = parse_manufacturer_data(payload)
    assert update.setpoint_c == 15.50
    assert update.temperature_c is None


def test_parse_combined_or_prefixed_payload() -> None:
    # Mesh/header bytes before the thermostat frame (realistic ads are longer).
    header = bytes.fromhex("AABBCCDDEE")
    current = bytes.fromhex("F7014101FE10010C14")
    payload = header + current
    update = parse_manufacturer_data(payload)
    assert update.temperature_c == 20.84


def test_parse_both_frames_in_one_blob() -> None:
    payload = bytes.fromhex(
        "F7014101FE10010C14"  # current
        "F7006501FF1001060E"  # setpoint
    )
    update = parse_manufacturer_data(payload)
    assert update.temperature_c == 20.84
    assert update.setpoint_c == 15.50


def test_parse_unrelated_payload() -> None:
    update = parse_manufacturer_data(bytes.fromhex("0102030405"))
    assert update.temperature_c is None
    assert update.setpoint_c is None
    assert update.shutter_position is None


def test_parse_shutter_hook() -> None:
    # F7 03 20 01 F6 10 01 <pos> — position byte reserved for later covers
    payload = bytes.fromhex("F7032001F61001" + "80")
    update = parse_manufacturer_data(payload)
    assert update.shutter_position == 0x80
    assert update.temperature_c is None


def test_build_setpoint_command() -> None:
    # F6 00 65 01 F5 10 01 <hi lo> with encode(21.0) = 3100 = 0x0C1C
    cmd = build_setpoint_command(21.0)
    assert cmd == bytes.fromhex("F6006501F510010C1C")


def test_build_setpoint_command_15_5() -> None:
    # encode(15.5) = 2825 = 0x0B09
    cmd = build_setpoint_command(15.5)
    assert cmd == bytes.fromhex("F6006501F510010B09")
