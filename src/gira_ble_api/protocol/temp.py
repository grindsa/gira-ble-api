"""Temperature encode/decode for Gira System 3000 thermostats."""

from __future__ import annotations

from .constants import THERMO_DUAL_SCALE_THRESHOLD, THERMO_MAX_C, THERMO_MIN_C


def decode_thermo_temp_u16(raw: int) -> float:
    """Decode advertisement / notification temperature from a big-endian u16.

    Dual scale (fc2800 / stho reverse engineering):
    - raw <= 2100 → °C = raw / 100
      (manual UI / simple ads, e.g. 1550 → 15.5 °C)
    - raw >  2100 → °C = 21 + (raw - 3100) / 50
      (same scale used by absolute GATT writes)

    Round-trip with encode_setpoint_u16 for the high scale.
    """
    raw = int(raw) & 0xFFFF
    if raw <= THERMO_DUAL_SCALE_THRESHOLD:
        return round(raw / 100.0, 2)
    return round(21.0 + (raw - 3100) / 50.0, 2)


def encode_setpoint_u16(temp_c: float) -> int:
    """Encode a setpoint (°C) for the GATT write command.

    raw = round((21 + temp_c) * 50 + 1000)
    """
    raw = int(round((21.0 + float(temp_c)) * 50.0 + 1000.0))
    return max(0, min(0xFFFF, raw))


def clamp_setpoint(temp_c: float) -> float:
    """Clamp setpoint to the supported thermostat range."""
    return max(THERMO_MIN_C, min(THERMO_MAX_C, float(temp_c)))
