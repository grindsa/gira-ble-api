"""Protocol constants for Gira System 3000 BLE.

Derived from reverse-engineered community sources (see README attribution).
Manufacturer company ID 1412 (0x0584).
"""

from __future__ import annotations

# Bluetooth SIG company identifier used in manufacturer advertisements.
GIRA_MANUFACTURER_ID = 1412  # 0x0584

# GATT service / characteristics used for commands (thermostat, covers, …).
GIRA_SERVICE_UUID = "9769F147-F77A-43AE-8C35-09F0C5245308"
GIRA_WRITE_CHAR_UUID = "97696341-F77A-43AE-8C35-09F0C5245308"
GIRA_READ_CHAR_UUID = "9769C769-F77A-43AE-8C35-09F0C5245308"

# Message framing
MSG_WRITE = 0xF6
MSG_NOTIFY = 0xF7

# Thermostat object id 0x0065 (101)
THERMO_OBJECT_ID = bytes([0x00, 0x65])

# Advertisement / GATT-notify value prefixes (payload after company id):
#   F7 01 41 01 FE 10 01 <hi> <lo>  — current temperature
#   F7 00 65 01 FF 10 01 <hi> <lo>  — target / setpoint temperature
#   F7 00 65 01 F8 10 01 <00|01>    — heating active (GATT notify; not in ads)
THERMO_CURRENT_TEMP_PREFIX = bytes.fromhex("F7014101FE1001")
THERMO_TARGET_TEMP_PREFIX = bytes.fromhex("F7006501FF1001")
THERMO_HEATING_PREFIX = bytes.fromhex("F7006501F81001")

# Write: set absolute target temperature (property 0xF5, u16 payload).
THERMO_PROPERTY_TARGET_TEMP = 0xF5
# Status: heating output active (property 0xF8, PDT_BINARY).
THERMO_PROPERTY_HEATING = 0xF8

# Dual-scale advertisement decode threshold (raw u16).
# raw <= 2100 → °C = raw / 100
# raw >  2100 → °C = raw / 100 - 10
THERMO_DUAL_SCALE_THRESHOLD = 2100

# Typical thermostat setpoint range (°C).
THERMO_MIN_C = 5.0
THERMO_MAX_C = 30.0
THERMO_STEP_C = 0.5

# Cover object id 0x0320 (800) — Gira protocol “shutter” object
COVER_OBJECT_ID = bytes([0x03, 0x20])

# Cover property IDs (write / status).
COVER_PROPERTY_MOVE = 0xFF  # 0=up, 1=down
COVER_PROPERTY_STOP = 0xFD
COVER_PROPERTY_SET_POSITION = 0xFC  # absolute position (PDT_SCALING)
# Ad status: current absolute position (read-only notify).
COVER_POS_PREFIX = bytes.fromhex("F7032001F61001")

# Position: API uses 0=closed … 100=open (HA cover convention).
# Gira PDT_SCALING raw: 0x00 = open (100%), 0xFF = closed (0%).
COVER_MIN_PCT = 0
COVER_MAX_PCT = 100

# Hooks for later device types (sensors) — prefixes only for now.
SENSOR_TEMPERATURE_PREFIX = bytes.fromhex("F7019901FF1001")
SENSOR_BRIGHTNESS_PREFIX = bytes.fromhex("F7019901FE1001")
