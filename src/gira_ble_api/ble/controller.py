"""Coordinate passive scanning vs short-lived GATT commands.

On macOS, a running BleakScanner often prevents reliable connects. We wait for
a fresh advertisement, pause scanning, connect immediately with that BLEDevice,
write / listen, disconnect, then resume.
"""

from __future__ import annotations

import asyncio
import logging
import sys
import time

from bleak import BleakClient, BleakError, BleakScanner
from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice

from gira_ble_api.protocol import GIRA_WRITE_CHAR_UUID
from gira_ble_api.protocol.ads import AdvertisementUpdate, parse_manufacturer_data
from gira_ble_api.protocol.commands import build_setpoint_command
from gira_ble_api.protocol.constants import GIRA_READ_CHAR_UUID

from .client import BleCommandError, normalize_mac
from .scanner import BleScanner

logger = logging.getLogger(__name__)


def _exc_text(exc: BaseException) -> str:
    text = str(exc).strip()
    if text:
        return f"{type(exc).__name__}: {text}"
    return type(exc).__name__


class BleController:
    """Owns the advertisement scanner and exclusive GATT access."""

    def __init__(
        self,
        macs: set[str],
        on_advertisement,
        *,
        ble_timeout_s: float = 30.0,
        connect_attempts: int = 3,
        heating_listen_s: float = 25.0,
    ) -> None:
        self._macs = {normalize_mac(m) for m in macs}
        self._ble_timeout_s = ble_timeout_s
        self._connect_attempts = max(1, connect_attempts)
        self._heating_listen_s = max(1.0, heating_listen_s)
        self._adapter_lock = asyncio.Lock()
        self._devices: dict[str, BLEDevice] = {}
        self._seen_at: dict[str, float] = {}
        self._seen_events: dict[str, asyncio.Event] = {}
        self._user_on_ad = on_advertisement
        self._scanner = BleScanner(self._macs, self._on_ad)
        # When True, GATT sessions must restore passive scanning afterward.
        self._should_scan = False

    def _event_for(self, address: str) -> asyncio.Event:
        if address not in self._seen_events:
            self._seen_events[address] = asyncio.Event()
        return self._seen_events[address]

    def _on_ad(
        self,
        mac: str,
        update: AdvertisementUpdate,
        rssi: int | None,
        device: BLEDevice,
    ) -> None:
        self._devices[mac] = device
        self._seen_at[mac] = time.monotonic()
        self._event_for(mac).set()
        self._user_on_ad(mac, update, rssi)

    async def start(self) -> None:
        self._should_scan = True
        await self._scanner.start()

    async def stop(self) -> None:
        self._should_scan = False
        await self._scanner.stop()

    async def _ensure_scanner_restored(self) -> None:
        """Best-effort resume after GATT; recovers from a prior failed resume."""
        if not self._should_scan or self._scanner.running:
            return
        try:
            await self._scanner.start()
            logger.info("Resumed BLE scanner")
        except Exception:
            logger.exception("Failed to resume BLE scanner")

    async def write_command(self, mac: str, payload: bytes) -> AdvertisementUpdate:
        """Wait for fresh ad → pause scan → connect/write → listen → resume."""
        return await self._with_exclusive_gatt(
            mac,
            lambda address, device, attempt: self._connect_write_listen(
                address,
                device=device,
                attempt=attempt,
                payload=payload,
                listen_s=self._heating_listen_s,
            ),
        )

    async def fetch_thermostat_status(
        self,
        mac: str,
        *,
        provoke_setpoint_c: float | None = None,
    ) -> AdvertisementUpdate:
        """Connect, subscribe, optionally re-write setpoint to provoke 0xF8."""
        return await self._with_exclusive_gatt(
            mac,
            lambda address, device, attempt: self._connect_status_listen(
                address,
                device=device,
                attempt=attempt,
                provoke_setpoint_c=provoke_setpoint_c,
                listen_s=self._heating_listen_s,
            ),
        )

    async def _with_exclusive_gatt(self, mac: str, action) -> AdvertisementUpdate:
        address = normalize_mac(mac)
        last_error: Exception | None = None

        async with self._adapter_lock:
            for attempt in range(1, self._connect_attempts + 1):
                try:
                    device = await self._wait_for_fresh_device(address)
                    if self._scanner.running:
                        logger.info("Pausing BLE scanner for GATT session")
                        await self._scanner.stop()
                    return await action(address, device, attempt)
                except BleCommandError as exc:
                    last_error = exc
                    if exc.code == "not_found":
                        break
                    logger.warning(
                        "GATT attempt %d/%d failed for %s: %s",
                        attempt,
                        self._connect_attempts,
                        address,
                        _exc_text(exc),
                    )
                    await asyncio.sleep(0.3 * attempt)
                except (BleakError, TimeoutError, OSError) as exc:
                    last_error = exc
                    logger.warning(
                        "GATT attempt %d/%d failed for %s: %s",
                        attempt,
                        self._connect_attempts,
                        address,
                        _exc_text(exc),
                    )
                    self._devices.pop(address, None)
                    self._seen_at.pop(address, None)
                    await asyncio.sleep(0.3 * attempt)
                finally:
                    await self._ensure_scanner_restored()

        assert last_error is not None
        raise self._wrap_final_error(address, last_error) from last_error

    def _wrap_final_error(self, address: str, last_error: Exception) -> BleCommandError:
        msg = _exc_text(last_error).lower()
        code = "ble_timeout"
        if isinstance(last_error, BleCommandError):
            code = last_error.code
        elif "timeout" not in msg and not isinstance(last_error, TimeoutError):
            code = "ble_error"
        if (
            "pair" in msg
            or "auth" in msg
            or "not permitted" in msg
            or "authenticationcanceled" in msg.replace(" ", "")
        ):
            code = "not_paired"
        if sys.platform == "darwin":
            hint = (
                " Put the thermostat into pairing mode (BT icon blinking), stand "
                "close, then retry — and accept any macOS Bluetooth Pair dialog."
            )
        else:
            hint = (
                " On Linux/Pi, first-time pairing is more reliable via bluetoothctl "
                "(agent NoInputNoOutput + pair/trust) while the thermostat is in "
                "pairing mode — see deploy/README.md. Then retry the setpoint."
            )
        return BleCommandError(
            f"BLE failed for {address} after {self._connect_attempts} attempt(s): "
            f"{_exc_text(last_error)}.{hint}",
            code=code,
        )

    async def _wait_for_fresh_device(
        self, address: str, *, max_age_s: float = 3.0
    ) -> BLEDevice:
        """Return a BLEDevice seen in a recent advertisement."""
        now = time.monotonic()
        seen = self._seen_at.get(address)
        device = self._devices.get(address)
        if device is not None and seen is not None and (now - seen) <= max_age_s:
            logger.debug(
                "Using fresh cached BLEDevice for %s (%.1fs old)", address, now - seen
            )
            return device

        if not self._scanner.running:
            await self._scanner.start()

        logger.info(
            "Waiting for advertisement from %s before connect (timeout=%.0fs)…",
            address,
            self._ble_timeout_s,
        )
        event = self._event_for(address)
        event.clear()
        try:
            await asyncio.wait_for(event.wait(), timeout=self._ble_timeout_s)
        except TimeoutError as exc:
            logger.info("No ad callback; trying BleakScanner.find_device_by_address…")
            found = await BleakScanner.find_device_by_address(
                address, timeout=min(15.0, self._ble_timeout_s)
            )
            if found is None:
                raise BleCommandError(
                    f"Device {address} not advertising. Stand closer and/or "
                    "enable pairing mode so it becomes connectable.",
                    code="not_found",
                ) from exc
            self._devices[address] = found
            self._seen_at[address] = time.monotonic()
            return found

        device = self._devices.get(address)
        if device is None:
            raise BleCommandError(
                f"Device {address} not found while advertising.",
                code="not_found",
            )
        return device

    async def _connect_write_listen(
        self,
        address: str,
        *,
        device: BLEDevice,
        attempt: int,
        payload: bytes,
        listen_s: float,
    ) -> AdvertisementUpdate:
        logger.info(
            "Connecting to %s (attempt %d, timeout=%.0fs)",
            address,
            attempt,
            self._ble_timeout_s,
        )
        client = BleakClient(device, timeout=self._ble_timeout_s, pair=False)
        merged = AdvertisementUpdate()
        try:
            await asyncio.wait_for(client.connect(), timeout=self._ble_timeout_s)
            if not client.is_connected:
                raise BleCommandError(
                    f"Could not connect to {address}",
                    code="ble_connect",
                )

            heating_event = asyncio.Event()

            def _on_notify(_sender: BleakGATTCharacteristic, data: bytearray) -> None:
                nonlocal merged
                update = parse_manufacturer_data(bytes(data))
                merged = merged.merge(update)
                if update.heating_active is not None:
                    heating_event.set()

            try:
                await client.start_notify(GIRA_READ_CHAR_UUID, _on_notify)
            except Exception as exc:  # noqa: BLE001
                logger.debug("start_notify failed on %s: %s", address, exc)

            write_timeout = max(
                self._ble_timeout_s,
                60.0 if sys.platform == "darwin" else self._ble_timeout_s,
            )
            logger.info("Connected to %s; writing %s", address, payload.hex())
            await asyncio.wait_for(
                client.write_gatt_char(
                    GIRA_WRITE_CHAR_UUID,
                    payload,
                    response=True,
                ),
                timeout=write_timeout,
            )
            logger.info("GATT write ok %s; listening %.0fs for status", address, listen_s)
            await self._wait_for_heating(heating_event, listen_s)
            return merged
        finally:
            try:
                if client.is_connected:
                    await client.disconnect()
            except Exception:  # noqa: BLE001
                logger.debug("disconnect error for %s", address, exc_info=True)

    async def _connect_status_listen(
        self,
        address: str,
        *,
        device: BLEDevice,
        attempt: int,
        provoke_setpoint_c: float | None,
        listen_s: float,
    ) -> AdvertisementUpdate:
        logger.info(
            "Connecting to %s for status (attempt %d, timeout=%.0fs)",
            address,
            attempt,
            self._ble_timeout_s,
        )
        client = BleakClient(device, timeout=self._ble_timeout_s, pair=False)
        merged = AdvertisementUpdate()
        try:
            await asyncio.wait_for(client.connect(), timeout=self._ble_timeout_s)
            if not client.is_connected:
                raise BleCommandError(
                    f"Could not connect to {address}",
                    code="ble_connect",
                )

            heating_event = asyncio.Event()

            def _on_notify(_sender: BleakGATTCharacteristic, data: bytearray) -> None:
                nonlocal merged
                update = parse_manufacturer_data(bytes(data))
                merged = merged.merge(update)
                if update.heating_active is not None:
                    heating_event.set()

            await client.start_notify(GIRA_READ_CHAR_UUID, _on_notify)

            # Re-writing the known setpoint provokes property 0xF8; idle subscribe alone
            # often only yields temperature frames.
            if provoke_setpoint_c is not None:
                payload = build_setpoint_command(provoke_setpoint_c)
                write_timeout = max(
                    self._ble_timeout_s,
                    60.0 if sys.platform == "darwin" else self._ble_timeout_s,
                )
                logger.info(
                    "Provoking heating status on %s via setpoint %.1f°C",
                    address,
                    provoke_setpoint_c,
                )
                await asyncio.wait_for(
                    client.write_gatt_char(
                        GIRA_WRITE_CHAR_UUID,
                        payload,
                        response=True,
                    ),
                    timeout=write_timeout,
                )

            await self._wait_for_heating(heating_event, listen_s)
            return merged
        finally:
            try:
                if client.is_connected:
                    await client.disconnect()
            except Exception:  # noqa: BLE001
                logger.debug("disconnect error for %s", address, exc_info=True)

    async def _wait_for_heating(self, heating_event: asyncio.Event, listen_s: float) -> None:
        try:
            await asyncio.wait_for(heating_event.wait(), timeout=listen_s)
        except TimeoutError:
            logger.debug("No heating_active notify within %.0fs", listen_s)
