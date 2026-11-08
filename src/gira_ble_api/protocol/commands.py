"""Build GATT write payloads for Gira System 3000 devices."""

from __future__ import annotations

from typing import Literal

from .constants import (
    COVER_OBJECT_ID,
    COVER_PROPERTY_MOVE,
    COVER_PROPERTY_SET_POSITION,
    COVER_PROPERTY_STOP,
    MSG_WRITE,
    THERMO_OBJECT_ID,
    THERMO_PROPERTY_TARGET_TEMP,
)
from .cover import clamp_position_pct, position_pct_to_raw
from .temp import clamp_setpoint, encode_setpoint_u16


def build_setpoint_command(temp_c: float) -> bytes:
    """Build a write command that sets the absolute thermostat setpoint.

    Frame layout (matches stho/fc2800 HA integrations):
      F6 00 65 01 F5 10 01 <hi> <lo>

    where <hi><lo> is encode_setpoint_u16(temp_c) big-endian.
    Property 0xF5 = write target; ads report status on 0xFF.
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
            0x01,  # element length field used by Gira (not raw byte count)
            (raw >> 8) & 0xFF,
            raw & 0xFF,
        ]
    )


def _cover_frame(property_id: int, value: int) -> bytes:
    """Build a one-byte cover write: F6 03 20 01 <pid> 10 01 <value>."""
    return bytes(
        [
            MSG_WRITE,
            *COVER_OBJECT_ID,
            0x01,
            property_id,
            0x10,
            0x01,
            value & 0xFF,
        ]
    )


def build_cover_move(direction: Literal["up", "down"]) -> bytes:
    """Move cover fully up (0) or down (1). PID 0xFF."""
    if direction not in ("up", "down"):
        raise ValueError(f"direction must be 'up' or 'down', got {direction!r}")
    return _cover_frame(COVER_PROPERTY_MOVE, 0 if direction == "up" else 1)


def build_cover_stop() -> bytes:
    """Stop cover movement. PID 0xFD."""
    return _cover_frame(COVER_PROPERTY_STOP, 0)


def build_cover_position(position_pct: float | int) -> bytes:
    """Set absolute cover position (0=closed … 100=open). PID 0xFC."""
    raw = position_pct_to_raw(clamp_position_pct(position_pct))
    return _cover_frame(COVER_PROPERTY_SET_POSITION, raw)
