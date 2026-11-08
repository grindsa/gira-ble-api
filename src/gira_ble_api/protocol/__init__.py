"""Pure Gira System 3000 BLE protocol helpers (no Bleak / FastAPI)."""

from .ads import AdvertisementUpdate, parse_manufacturer_data
from .commands import (
    build_cover_move,
    build_cover_position,
    build_cover_stop,
    build_setpoint_command,
)
from .constants import GIRA_MANUFACTURER_ID, GIRA_SERVICE_UUID, GIRA_WRITE_CHAR_UUID
from .cover import clamp_position_pct, position_pct_to_raw, raw_to_position_pct
from .temp import decode_thermo_temp_u16, encode_setpoint_u16

__all__ = [
    "AdvertisementUpdate",
    "GIRA_MANUFACTURER_ID",
    "GIRA_SERVICE_UUID",
    "GIRA_WRITE_CHAR_UUID",
    "build_cover_move",
    "build_cover_position",
    "build_cover_stop",
    "build_setpoint_command",
    "clamp_position_pct",
    "decode_thermo_temp_u16",
    "encode_setpoint_u16",
    "parse_manufacturer_data",
    "position_pct_to_raw",
    "raw_to_position_pct",
]
