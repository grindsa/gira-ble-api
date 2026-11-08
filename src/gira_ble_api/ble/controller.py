"""Coordinate passive scanning vs short-lived GATT commands.

On macOS, a running BleakScanner often prevents reliable connects. We wait for
a fresh advertisement, pause scanning, connect immediately with that BLEDevice,
write, disconnect, then resume.
"""

from __future__ import annotations

import asyncio
import logging
import sys
import time

from bleak import BleakClient, BleakError, BleakScanner
from bleak.backends.device import BLEDevice

from gira_ble_api.protocol import GIRA_WRITE_CHAR_UUID
from gira_ble_api.protocol.ads import AdvertisementUpdate

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
    ) -> None:
        self._macs = {normalize_mac(m) for m in macs}
        self._ble_timeout_s = ble_timeout_s
        self._connect_attempts = max(1, connect_attempts)
        self._adapter_lock = asyncio.Lock()
        self._devices: dict[str, BLEDevice] = {}
        self._seen_at: dict[str, float] = {}
        self._seen_events: dict[str, asyncio.Event] = {}
        self._user_on_ad = on_advertisement
        self._scanner = BleScanner(self._macs, self._on_ad)

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
        await self._scanner.start()

    async def stop(self) -> None:
        await self._scanner.stop()

    async def write_command(self, mac: str, payload: bytes) -> None:
        """Wait for fresh ad → pause scan → connect/write → resume."""
        address = normalize_mac(mac)
        last_error: Exception | None = None

        async with self._adapter_lock:
            for attempt in range(1, self._connect_attempts + 1):
                was_running = self._scanner.running
                try:
                    device = await self._wait_for_fresh_device(address)
                    if was_running:
                        logger.info("Pausing BLE scanner for GATT command")
                        await self._scanner.stop()
                        # Connect immediately — long gaps make Gira units non-connectable.
                    await self._connect_and_write(
                        address, payload, device=device, attempt=attempt
                    )
                    return
                except BleCommandError as exc:
                    last_error = exc
                    if exc.code == "not_found":
                        # No point retrying the same absence forever.
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
                    # Drop stale handle; next attempt waits for a new ad.
                    self._devices.pop(address, None)
                    self._seen_at.pop(address, None)
                    await asyncio.sleep(0.3 * attempt)
                finally:
                    if was_running and not self._scanner.running:
                        try:
                            await self._scanner.start()
                            logger.info("Resumed BLE scanner")
                        except Exception:
                            logger.exception("Failed to resume BLE scanner")

        assert last_error is not None
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
        raise BleCommandError(
            f"BLE failed for {address} after {self._connect_attempts} attempt(s): "
            f"{_exc_text(last_error)}.{hint}",
            code=code,
        ) from last_error

    async def _wait_for_fresh_device(
        self, address: str, *, max_age_s: float = 3.0
    ) -> BLEDevice:
        """Return a BLEDevice seen in a recent advertisement."""
        now = time.monotonic()
        seen = self._seen_at.get(address)
        device = self._devices.get(address)
        if device is not None and seen is not None and (now - seen) <= max_age_s:
            logger.debug("Using fresh cached BLEDevice for %s (%.1fs old)", address, now - seen)
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
            # Last resort: active find (starts its own short scan).
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

    async def _connect_and_write(
        self,
        address: str,
        payload: bytes,
        *,
        device: BLEDevice,
        attempt: int,
    ) -> None:
        logger.info(
            "Connecting to %s (attempt %d, timeout=%.0fs)",
            address,
            attempt,
            self._ble_timeout_s,
        )

        # pair=False: on headless BlueZ, pair=True often yields AuthenticationCanceled
        # without an agent. First bond the device with bluetoothctl (see deploy/README).
        # macOS ignores pair= and prompts on the first encrypted GATT write instead.
        client = BleakClient(device, timeout=self._ble_timeout_s, pair=False)
        try:
            await asyncio.wait_for(client.connect(), timeout=self._ble_timeout_s)
            if not client.is_connected:
                raise BleCommandError(
                    f"Could not connect to {address}",
                    code="ble_connect",
                )

            logger.info("Connected to %s; writing %s", address, payload.hex())
            write_timeout = max(
                self._ble_timeout_s,
                60.0 if sys.platform == "darwin" else self._ble_timeout_s,
            )
            await asyncio.wait_for(
                client.write_gatt_char(
                    GIRA_WRITE_CHAR_UUID,
                    payload,
                    response=True,
                ),
                timeout=write_timeout,
            )
            logger.info("GATT write ok %s", address)
        finally:
            try:
                if client.is_connected:
                    await client.disconnect()
            except Exception:  # noqa: BLE001
                logger.debug("disconnect error for %s", address, exc_info=True)
