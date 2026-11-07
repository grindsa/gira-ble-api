"""Passive BLE advertisement scanner for configured Gira devices."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable

from bleak import BleakScanner
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData

from gira_ble_api.protocol import GIRA_MANUFACTURER_ID, parse_manufacturer_data
from gira_ble_api.protocol.ads import AdvertisementUpdate

from .client import normalize_mac

logger = logging.getLogger(__name__)

AdCallback = Callable[[str, AdvertisementUpdate, int | None], None]


class BleScanner:
    """Continuously listen for Gira manufacturer advertisements."""

    def __init__(
        self,
        macs: set[str],
        on_advertisement: AdCallback,
    ) -> None:
        self._macs = {normalize_mac(m) for m in macs}
        self._on_advertisement = on_advertisement
        self._scanner: BleakScanner | None = None
        self._running = False

    async def start(self) -> None:
        if self._running:
            return
        self._scanner = BleakScanner(detection_callback=self._detection_callback)
        await self._scanner.start()
        self._running = True
        logger.info(
            "BLE scanner started; watching %d thermostat(s)",
            len(self._macs),
        )

    async def stop(self) -> None:
        if not self._running or self._scanner is None:
            return
        await self._scanner.stop()
        self._scanner = None
        self._running = False
        logger.info("BLE scanner stopped")

    def _detection_callback(
        self,
        device: BLEDevice,
        advertisement_data: AdvertisementData,
    ) -> None:
        address = normalize_mac(device.address or "")
        if address not in self._macs:
            return

        manufacturer_data = advertisement_data.manufacturer_data or {}
        payload = manufacturer_data.get(GIRA_MANUFACTURER_ID)
        if not payload:
            return

        logger.debug(
            "ad %s rssi=%s raw=%s",
            address,
            advertisement_data.rssi,
            bytes(payload).hex(),
        )

        update = parse_manufacturer_data(payload)
        if (
            update.temperature_c is None
            and update.setpoint_c is None
            and update.shutter_position is None
        ):
            return

        try:
            self._on_advertisement(address, update, advertisement_data.rssi)
        except Exception:
            logger.exception("advertisement callback failed for %s", address)


async def run_scanner_forever(
    scanner: BleScanner,
    stop_event: asyncio.Event,
) -> None:
    """Start scanner and wait until stop_event is set."""
    await scanner.start()
    try:
        await stop_event.wait()
    finally:
        await scanner.stop()
