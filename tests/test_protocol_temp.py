"""Unit tests for thermostat temperature encode/decode."""

from __future__ import annotations

import pytest

from gira_ble_api.protocol.temp import (
    clamp_setpoint,
    decode_thermo_temp_u16,
    encode_setpoint_u16,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # Simple scale (raw <= 2100): °C = raw / 100
        (0x060E, 15.50),  # community setpoint capture
        (1550, 15.50),
        (700, 7.00),
        (2100, 21.00),
        (1000, 10.00),
        (0, 0.00),
        # High scale (raw > 2100): °C = 21 + (raw - 3100) / 50
        (3100, 21.00),  # encode(21) round-trip
        (3150, 22.00),
        (2400, 7.00),  # encode(7) round-trip
        (0x0C14, 20.84),  # 3092 — community ~21 °C actual
    ],
)
def test_decode_thermo_temp_u16(raw: int, expected: float) -> None:
    assert decode_thermo_temp_u16(raw) == expected


@pytest.mark.parametrize(
    ("temp_c", "expected_raw"),
    [
        (21.0, 3100),
        (15.5, 2825),
        (20.0, 3050),
        (5.0, 2300),
        (7.0, 2400),
        (30.0, 3550),
    ],
)
def test_encode_setpoint_u16(temp_c: float, expected_raw: int) -> None:
    assert encode_setpoint_u16(temp_c) == expected_raw


@pytest.mark.parametrize("temp_c", [5.0, 7.0, 15.5, 21.0, 22.5, 30.0])
def test_encode_decode_roundtrip_high_scale(temp_c: float) -> None:
    raw = encode_setpoint_u16(temp_c)
    assert raw > 2100
    assert decode_thermo_temp_u16(raw) == temp_c


def test_clamp_setpoint() -> None:
    assert clamp_setpoint(21.0) == 21.0
    assert clamp_setpoint(0.0) == 5.0
    assert clamp_setpoint(40.0) == 30.0
