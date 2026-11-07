"""Discover nearby Gira System 3000 devices via manufacturer ads."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

from bleak import BleakScanner
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData

from gira_ble_api.protocol import GIRA_MANUFACTURER_ID, parse_manufacturer_data

from .client import normalize_mac

logger = logging.getLogger(__name__)


@dataclass
class DiscoveredDevice:
    """One Gira BLE advertiser seen during a discovery window."""

    address: str
    name: str | None = None
    rssi: int | None = None
    temperature_c: float | None = None
    setpoint_c: float | None = None
    shutter_position: int | None = None
    last_seen_at: str | None = None
    ad_count: int = 0
    kind_hints: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hint_kinds(
    *,
    temperature_c: float | None,
    setpoint_c: float | None,
    shutter_position: int | None,
) -> list[str]:
    hints: list[str] = []
    if temperature_c is not None or setpoint_c is not None:
        hints.append("thermostat")
    if shutter_position is not None:
        hints.append("shutter")
    return hints


async def discover_gira_devices(*, seconds: float = 15.0) -> list[DiscoveredDevice]:
    """Scan the host adapter for Gira manufacturer ads (company id 1412).

    No pairing / GATT. Put devices near the Mac (or briefly into pairing mode)
    so they advertise. Returns devices sorted by strongest RSSI first.
    """
    if seconds <= 0:
        raise ValueError("seconds must be > 0")

    found: dict[str, DiscoveredDevice] = {}

    def _on_detect(device: BLEDevice, ad: AdvertisementData) -> None:
        manufacturer_data = ad.manufacturer_data or {}
        payload = manufacturer_data.get(GIRA_MANUFACTURER_ID)
        if not payload:
            return

        address = normalize_mac(device.address or "")
        if not address:
            return

        update = parse_manufacturer_data(payload)
        name = ad.local_name or device.name
        now = _utcnow_iso()

        existing = found.get(address)
        if existing is None:
            hints = _hint_kinds(
                temperature_c=update.temperature_c,
                setpoint_c=update.setpoint_c,
                shutter_position=update.shutter_position,
            )
            found[address] = DiscoveredDevice(
                address=address,
                name=name,
                rssi=ad.rssi,
                temperature_c=update.temperature_c,
                setpoint_c=update.setpoint_c,
                shutter_position=update.shutter_position,
                last_seen_at=now,
                ad_count=1,
                kind_hints=hints,
            )
            logger.info(
                "discovered %s name=%r rssi=%s hints=%s",
                address,
                name,
                ad.rssi,
                hints or ["gira"],
            )
            return

        existing.ad_count += 1
        existing.last_seen_at = now
        if name:
            existing.name = name
        if ad.rssi is not None:
            existing.rssi = ad.rssi
        if update.temperature_c is not None:
            existing.temperature_c = update.temperature_c
        if update.setpoint_c is not None:
            existing.setpoint_c = update.setpoint_c
        if update.shutter_position is not None:
            existing.shutter_position = update.shutter_position
        for hint in _hint_kinds(
            temperature_c=update.temperature_c,
            setpoint_c=update.setpoint_c,
            shutter_position=update.shutter_position,
        ):
            if hint not in existing.kind_hints:
                existing.kind_hints.append(hint)

    logger.info("Scanning for Gira devices (manufacturer id %d) for %.0fs…", GIRA_MANUFACTURER_ID, seconds)
    scanner = BleakScanner(detection_callback=_on_detect)
    await scanner.start()
    try:
        await asyncio.sleep(seconds)
    finally:
        await scanner.stop()

    devices = list(found.values())
    devices.sort(
        key=lambda d: (d.rssi is not None, d.rssi if d.rssi is not None else -999),
        reverse=True,
    )
    logger.info("Scan done: %d Gira device(s)", len(devices))
    return devices


def format_discovery_table(devices: list[DiscoveredDevice]) -> str:
    """Human-readable table for the CLI."""
    if not devices:
        return (
            "No Gira devices seen.\n"
            "Tips: move closer, press the pairing button briefly so the unit "
            "advertises, grant Bluetooth permission to Terminal/IDE, retry with "
            "a longer --seconds."
        )

    headers = ("ADDRESS", "RSSI", "NAME", "TEMP°C", "SETPOINT°C", "HINTS", "ADS")
    rows: list[tuple[str, ...]] = [headers]
    for d in devices:
        rows.append(
            (
                d.address,
                str(d.rssi) if d.rssi is not None else "-",
                d.name or "-",
                f"{d.temperature_c:.2f}" if d.temperature_c is not None else "-",
                f"{d.setpoint_c:.2f}" if d.setpoint_c is not None else "-",
                ",".join(d.kind_hints) or "gira",
                str(d.ad_count),
            )
        )

    widths = [max(len(row[i]) for row in rows) for i in range(len(headers))]
    lines = [
        "  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)) for row in rows
    ]
    lines.append("")
    lines.append("Copy ADDRESS into config.yaml as mac: \"…\"")
    return "\n".join(lines)
