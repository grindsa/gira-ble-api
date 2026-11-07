"""Protocol constants for Gira System 3000 BLE.

Derived from reverse-engineered community sources (see README attribution).
Manufacturer company ID 1412 (0x0584).
"""

from __future__ import annotations

# Bluetooth SIG company identifier used in manufacturer advertisements.
GIRA_MANUFACTURER_ID = 1412  # 0x0584

# GATT service / characteristics used for commands (thermostat, shutters, …).
GIRA_SERVICE_UUID = "9769F147-F77A-43AE-8C35-09F0C5245308"
GIRA_WRITE_CHAR_UUID = "97696341-F77A-43AE-8C35-09F0C5245308"
GIRA_READ_CHAR_UUID = "9769C769-F77A-43AE-8C35-09F0C5245308"

# Message framing
MSG_WRITE = 0xF6
MSG_NOTIFY = 0xF7

# Thermostat object id 0x0065 (101)
THERMO_OBJECT_ID = bytes([0x00, 0x65])

# Advertisement value prefixes (payload after company id):
#   F7 01 41 01 FE 10 01 <hi> <lo>  — current temperature
#   F7 00 65 01 FF 10 01 <hi> <lo>  — target / setpoint temperature
THERMO_CURRENT_TEMP_PREFIX = bytes.fromhex("F7014101FE1001")
THERMO_TARGET_TEMP_PREFIX = bytes.fromhex("F7006501FF1001")

# Write: set absolute target temperature (property 0xF5, u16 payload).
THERMO_PROPERTY_TARGET_TEMP = 0xF5

# Dual-scale advertisement decode threshold (raw u16).
# raw <= 2100 → °C = raw / 100
# raw >  2100 → °C = raw / 100 - 10
THERMO_DUAL_SCALE_THRESHOLD = 2100

# Typical thermostat setpoint range (°C).
THERMO_MIN_C = 5.0
THERMO_MAX_C = 30.0
THERMO_STEP_C = 0.5

# Hooks for later device types (shutters / sensors) — prefixes only for now.
SHUTTER_POS_PREFIX = bytes.fromhex("F7032001F61001")
SENSOR_TEMPERATURE_PREFIX = bytes.fromhex("F7019901FF1001")
SENSOR_BRIGHTNESS_PREFIX = bytes.fromhex("F7019901FE1001")
