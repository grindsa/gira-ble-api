"""Parse Gira manufacturer advertisement payloads."""

from __future__ import annotations

from dataclasses import dataclass

from .constants import (
    COVER_POS_PREFIX,
    THERMO_CURRENT_TEMP_PREFIX,
    THERMO_TARGET_TEMP_PREFIX,
)
from .cover import raw_to_position_pct
from .temp import decode_thermo_temp_u16


@dataclass(frozen=True)
class AdvertisementUpdate:
    """Fields extracted from one manufacturer-data blob.

    Partial: an ad may carry only current temp, only setpoint, cover
    position, or a combination. Unknown frames leave fields as None.
    """

    temperature_c: float | None = None
    setpoint_c: float | None = None
    # Cover position percent open (0=closed … 100=open); None if absent.
    position_pct: int | None = None


def _find_u16_after(payload: bytes, prefix: bytes) -> int | None:
    idx = payload.find(prefix)
    if idx < 0:
        return None
    start = idx + len(prefix)
    if len(payload) < start + 2:
        return None
    return int.from_bytes(payload[start : start + 2], "big")


def parse_manufacturer_data(payload: bytes | bytearray) -> AdvertisementUpdate:
    """Parse Gira manufacturer-data bytes (company id already stripped).

    Thermostat ads may arrive as separate frames for actual vs setpoint;
    callers should merge non-None fields into existing state.
    """
    data = bytes(payload)
    temperature_c: float | None = None
    setpoint_c: float | None = None
    position_pct: int | None = None

    raw_cur = _find_u16_after(data, THERMO_CURRENT_TEMP_PREFIX)
    if raw_cur is not None:
        temperature_c = decode_thermo_temp_u16(raw_cur)

    raw_tgt = _find_u16_after(data, THERMO_TARGET_TEMP_PREFIX)
    if raw_tgt is not None:
        setpoint_c = decode_thermo_temp_u16(raw_tgt)

    pos_idx = data.find(COVER_POS_PREFIX)
    if pos_idx >= 0 and len(data) >= pos_idx + len(COVER_POS_PREFIX) + 1:
        position_pct = raw_to_position_pct(data[pos_idx + len(COVER_POS_PREFIX)])

    return AdvertisementUpdate(
        temperature_c=temperature_c,
        setpoint_c=setpoint_c,
        position_pct=position_pct,
    )
