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
        # Community capture: setpoint 0x060E = 1550 → 15.50 °C
        (0x060E, 15.50),
        (1550, 15.50),
        # Community capture: actual ~21 °C dual-scale (0x0C14 / 3092)
        (0x0C14, 20.92),
        (3085, 20.85),  # community note: "3085 = 21.0°C" (approx)
        # Boundary at dual-scale threshold
        (2100, 21.00),
        (2101, 11.01),
        (1000, 10.00),
        (0, 0.00),
    ],
)
def test_decode_thermo_temp_u16(raw: int, expected: float) -> None:
    assert decode_thermo_temp_u16(raw) == expected


@pytest.mark.parametrize(
    ("temp_c", "expected_raw"),
    [
        # raw = round((21 + temp) * 50 + 1000)
        (21.0, 3100),
        (15.5, 2825),
        (20.0, 3050),
        (5.0, 2300),
        (30.0, 3550),
    ],
)
def test_encode_setpoint_u16(temp_c: float, expected_raw: int) -> None:
    assert encode_setpoint_u16(temp_c) == expected_raw


def test_clamp_setpoint() -> None:
    assert clamp_setpoint(21.0) == 21.0
    assert clamp_setpoint(0.0) == 5.0
    assert clamp_setpoint(40.0) == 30.0
