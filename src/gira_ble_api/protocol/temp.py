"""Temperature encode/decode for Gira System 3000 thermostats."""

from __future__ import annotations

from .constants import THERMO_DUAL_SCALE_THRESHOLD, THERMO_MAX_C, THERMO_MIN_C


def decode_thermo_temp_u16(raw: int) -> float:
    """Decode advertisement temperature from a big-endian u16.

    Gira uses a dual-scale encoding for thermostat ads:
    - raw <= 2100 → °C = raw / 100
    - raw >  2100 → °C = raw / 100 - 10

    Examples from community captures:
    - 0x060E (1550) → 15.5 °C (setpoint)
    - 0x0C14 (3092) → 20.92 °C (actual; often reported ~21.0)
    """
    raw = int(raw) & 0xFFFF
    temp = raw / 100.0
    if raw > THERMO_DUAL_SCALE_THRESHOLD:
        temp -= 10.0
    return round(temp, 2)


def encode_setpoint_u16(temp_c: float) -> int:
    """Encode a setpoint (°C) for the GATT write command.

    Device-specific write encoding (not the same as advertisement raw):
        raw = round((21 + temp_c) * 50 + 1000)
    """
    raw = int(round((21.0 + float(temp_c)) * 50.0 + 1000.0))
    return max(0, min(0xFFFF, raw))


def clamp_setpoint(temp_c: float) -> float:
    """Clamp setpoint to the supported thermostat range."""
    return max(THERMO_MIN_C, min(THERMO_MAX_C, float(temp_c)))
