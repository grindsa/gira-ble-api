"""Connect to a Gira device and dump GATT notifications (protocol discovery)."""

from __future__ import annotations

import asyncio
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from bleak import BleakClient, BleakScanner
from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice

from gira_ble_api.protocol.constants import (
    GIRA_READ_CHAR_UUID,
    GIRA_SERVICE_UUID,
    GIRA_WRITE_CHAR_UUID,
)

from .client import normalize_mac

logger = logging.getLogger(__name__)


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _char_props(char: BleakGATTCharacteristic) -> str:
    props = getattr(char, "properties", None) or []
    if isinstance(props, (list, set, tuple)):
        return ",".join(sorted(str(p) for p in props))
    return str(props)


async def _find_device(address: str, *, timeout_s: float) -> BLEDevice:
    """Locate a BLEDevice by address (prefer a fresh advertisement)."""
    target = normalize_mac(address)
    logger.info("Looking for %s (timeout=%.0fs)…", target, timeout_s)
    found = await BleakScanner.find_device_by_address(target, timeout=timeout_s)
    if found is None:
        raise RuntimeError(
            f"Device {target} not found. Stand closer and/or enable pairing mode."
        )
    return found


async def sniff_gatt_notifies(
    address: str,
    *,
    seconds: float = 90.0,
    timeout_s: float = 30.0,
    output: Path | None = None,
    write_hex: str | None = None,
) -> int:
    """Connect, list GATT, subscribe to notifies, dump hex until timeout.

    Returns number of notification payloads received.
    """
    if seconds <= 0:
        raise ValueError("seconds must be > 0")

    device = await _find_device(address, timeout_s=timeout_s)
    out_lines: list[str] = []
    notify_count = 0

    def _emit(line: str) -> None:
        print(line, flush=True)
        out_lines.append(line)

    def _on_notify(sender: BleakGATTCharacteristic, data: bytearray) -> None:
        nonlocal notify_count
        notify_count += 1
        uuid = str(getattr(sender, "uuid", sender)).lower()
        payload = bytes(data)
        _emit(
            f"{_utcnow()} NOTIFY n={notify_count} char={uuid} "
            f"len={len(payload)} hex={payload.hex()}"
        )

    client = BleakClient(device, timeout=timeout_s, pair=False)
    connect_timeout = max(timeout_s, 60.0 if sys.platform == "darwin" else timeout_s)
    try:
        _emit(f"{_utcnow()} CONNECTING address={normalize_mac(address)}")
        await asyncio.wait_for(client.connect(), timeout=connect_timeout)
        if not client.is_connected:
            raise RuntimeError(f"Could not connect to {address}")
        _emit(f"{_utcnow()} CONNECTED name={device.name!r}")

        # Dump GATT tree for discovery (services / chars / properties).
        services = client.services
        for service in services:
            _emit(f"{_utcnow()} SERVICE {service.uuid}")
            for char in service.characteristics:
                _emit(
                    f"{_utcnow()}   CHAR {char.uuid} props=[{_char_props(char)}] "
                    f"handle={getattr(char, 'handle', '?')}"
                )

        # Subscribe to every notify/indicate characteristic; prefer Gira read UUID.
        subscribed: list[str] = []
        for service in services:
            for char in service.characteristics:
                props = {str(p).lower() for p in (char.properties or [])}
                if "notify" not in props and "indicate" not in props:
                    continue
                try:
                    await client.start_notify(char, _on_notify)
                    subscribed.append(str(char.uuid).lower())
                    _emit(f"{_utcnow()} SUBSCRIBED {char.uuid}")
                except Exception as exc:  # noqa: BLE001
                    _emit(f"{_utcnow()} SUBSCRIBE_FAIL {char.uuid} err={exc}")

        if not subscribed:
            # Fallback: try the known Gira read characteristic even if props look odd.
            try:
                await client.start_notify(GIRA_READ_CHAR_UUID, _on_notify)
                subscribed.append(GIRA_READ_CHAR_UUID.lower())
                _emit(f"{_utcnow()} SUBSCRIBED {GIRA_READ_CHAR_UUID} (fallback)")
            except Exception as exc:  # noqa: BLE001
                _emit(f"{_utcnow()} SUBSCRIBE_FAIL fallback err={exc}")

        if write_hex:
            payload = bytes.fromhex(write_hex.replace(" ", ""))
            _emit(
                f"{_utcnow()} WRITE char={GIRA_WRITE_CHAR_UUID} "
                f"len={len(payload)} hex={payload.hex()}"
            )
            await client.write_gatt_char(
                GIRA_WRITE_CHAR_UUID, payload, response=True
            )
            _emit(f"{_utcnow()} WRITE_OK")

        _emit(
            f"{_utcnow()} LISTENING seconds={seconds:.0f} "
            f"subscribed={len(subscribed)} "
            f"service={GIRA_SERVICE_UUID}"
        )
        _emit(
            f"{_utcnow()} HINT flip heating on the thermostat (setpoint/Boost) "
            "while this runs; Ctrl-C to stop early"
        )
        await asyncio.sleep(seconds)
    finally:
        try:
            if client.is_connected:
                await client.disconnect()
                _emit(f"{_utcnow()} DISCONNECTED")
        except Exception:  # noqa: BLE001
            logger.debug("disconnect error", exc_info=True)

    _emit(f"{_utcnow()} DONE notifies={notify_count}")
    if output is not None:
        output.write_text("\n".join(out_lines) + "\n", encoding="utf-8")
        _emit(f"{_utcnow()} WROTE {output}")
    return notify_count
