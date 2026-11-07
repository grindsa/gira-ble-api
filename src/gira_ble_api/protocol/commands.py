"""Build GATT write payloads for Gira System 3000 devices."""

from __future__ import annotations

from .constants import (
    MSG_WRITE,
    THERMO_OBJECT_ID,
    THERMO_PROPERTY_TARGET_TEMP,
)
from .temp import clamp_setpoint, encode_setpoint_u16


def build_setpoint_command(temp_c: float) -> bytes:
    """Build a write command that sets the absolute thermostat setpoint.

    Frame layout:
      F6 00 65 01 F5 10 01 <hi> <lo>

    where <hi><lo> is encode_setpoint_u16(temp_c).
    """
    clamped = clamp_setpoint(temp_c)
    raw = encode_setpoint_u16(clamped)
    return bytes(
        [
            MSG_WRITE,
            *THERMO_OBJECT_ID,
            0x01,
            THERMO_PROPERTY_TARGET_TEMP,
            0x10,
            0x01,
            (raw >> 8) & 0xFF,
            raw & 0xFF,
        ]
    )
