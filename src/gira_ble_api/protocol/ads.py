"""Parse Gira manufacturer advertisement payloads."""

from __future__ import annotations

from dataclasses import dataclass

from .constants import (
    COVER_POS_PREFIX,
    THERMO_CURRENT_TEMP_PREFIX,
    THERMO_HEATING_PREFIX,
    THERMO_TARGET_TEMP_PREFIX,
)
from .cover import raw_to_position_pct
from .temp import decode_thermo_temp_u16


@dataclass(frozen=True)
class AdvertisementUpdate:
    """Fields extracted from one manufacturer-data / GATT-notify blob.

    Partial: an ad or notify may carry only current temp, only setpoint,
    heating status, cover position, or a combination. Unknown frames leave
    fields as None.
    """

    temperature_c: float | None = None
    setpoint_c: float | None = None
    # Valve / heater output active (GATT notify property 0xF8); None if absent.
    heating_active: bool | None = None
    # Cover position percent open (0=closed … 100=open); None if absent.
    position_pct: int | None = None

    def merge(self, other: AdvertisementUpdate) -> AdvertisementUpdate:
        """Prefer non-None fields from ``other``."""
        return AdvertisementUpdate(
            temperature_c=(
                other.temperature_c
                if other.temperature_c is not None
                else self.temperature_c
            ),
            setpoint_c=(
                other.setpoint_c if other.setpoint_c is not None else self.setpoint_c
            ),
            heating_active=(
                other.heating_active
                if other.heating_active is not None
                else self.heating_active
            ),
            position_pct=(
                other.position_pct
                if other.position_pct is not None
                else self.position_pct
            ),
        )


def _find_u16_after(payload: bytes, prefix: bytes) -> int | None:
    idx = payload.find(prefix)
    if idx < 0:
        return None
    start = idx + len(prefix)
    if len(payload) < start + 2:
        return None
    return int.from_bytes(payload[start : start + 2], "big")


def _find_u8_after(payload: bytes, prefix: bytes) -> int | None:
    idx = payload.find(prefix)
    if idx < 0:
        return None
    start = idx + len(prefix)
    if len(payload) < start + 1:
        return None
    return int(payload[start])


def parse_manufacturer_data(payload: bytes | bytearray) -> AdvertisementUpdate:
    """Parse Gira manufacturer-data or GATT-notify bytes (company id stripped).

    Thermostat ads/notifies may arrive as separate frames for actual vs
    setpoint vs heating; callers should merge non-None fields into state.
    """
    data = bytes(payload)
    temperature_c: float | None = None
    setpoint_c: float | None = None
    heating_active: bool | None = None
    position_pct: int | None = None

    raw_cur = _find_u16_after(data, THERMO_CURRENT_TEMP_PREFIX)
    if raw_cur is not None:
        temperature_c = decode_thermo_temp_u16(raw_cur)

    raw_tgt = _find_u16_after(data, THERMO_TARGET_TEMP_PREFIX)
    if raw_tgt is not None:
        setpoint_c = decode_thermo_temp_u16(raw_tgt)

    raw_heat = _find_u8_after(data, THERMO_HEATING_PREFIX)
    if raw_heat is not None:
        heating_active = bool(raw_heat & 0x01)

    pos_idx = data.find(COVER_POS_PREFIX)
    if pos_idx >= 0 and len(data) >= pos_idx + len(COVER_POS_PREFIX) + 1:
        position_pct = raw_to_position_pct(data[pos_idx + len(COVER_POS_PREFIX)])

    return AdvertisementUpdate(
        temperature_c=temperature_c,
        setpoint_c=setpoint_c,
        heating_active=heating_active,
        position_pct=position_pct,
    )
