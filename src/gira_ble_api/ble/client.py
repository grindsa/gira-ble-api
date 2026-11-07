"""Short-lived GATT client for setpoint writes (lazy pair, idle disconnect)."""

from __future__ import annotations

import asyncio
import logging

from bleak import BleakClient, BleakError

from gira_ble_api.protocol import GIRA_WRITE_CHAR_UUID

logger = logging.getLogger(__name__)


class BleCommandError(Exception):
    """Raised when a BLE connect/write fails."""

    def __init__(self, message: str, *, code: str = "ble_error") -> None:
        super().__init__(message)
        self.code = code


class BleClient:
    """Connect → write → idle-disconnect for a single MAC address."""

    def __init__(
        self,
        mac: str,
        *,
        timeout_s: float = 20.0,
        idle_disconnect_s: float = 5.0,
    ) -> None:
        self.mac = normalize_mac(mac)
        self.timeout_s = timeout_s
        self.idle_disconnect_s = idle_disconnect_s
        self._lock = asyncio.Lock()
        self._client: BleakClient | None = None
        self._idle_task: asyncio.Task[None] | None = None

    async def write(self, payload: bytes) -> None:
        """Write to the Gira command characteristic; pair on first connect."""
        async with self._lock:
            self._cancel_idle()
            try:
                client = await self._ensure_connected()
                logger.info(
                    "GATT write %s → %s (%d bytes)",
                    self.mac,
                    payload.hex(),
                    len(payload),
                )
                logger.debug("raw command hex=%s", payload.hex())
                await asyncio.wait_for(
                    client.write_gatt_char(
                        GIRA_WRITE_CHAR_UUID,
                        payload,
                        response=True,
                    ),
                    timeout=self.timeout_s,
                )
                logger.info("GATT write ok %s", self.mac)
                self._schedule_idle()
            except TimeoutError as exc:
                await self._force_disconnect()
                raise BleCommandError(
                    f"BLE timeout talking to {self.mac} "
                    f"(put device in pairing mode on first use)",
                    code="ble_timeout",
                ) from exc
            except BleakError as exc:
                await self._force_disconnect()
                msg = str(exc).lower()
                code = "ble_error"
                if "pair" in msg or "auth" in msg or "not permitted" in msg:
                    code = "not_paired"
                raise BleCommandError(
                    f"BLE failed for {self.mac}: {exc}. "
                    "On first command, put the thermostat into pairing mode.",
                    code=code,
                ) from exc

    async def close(self) -> None:
        async with self._lock:
            self._cancel_idle()
            await self._force_disconnect()

    async def _ensure_connected(self) -> BleakClient:
        if self._client is not None and self._client.is_connected:
            return self._client

        logger.info(
            "Connecting to %s (timeout=%.0fs); pairing attempted after connect",
            self.mac,
            self.timeout_s,
        )
        client = BleakClient(self.mac, timeout=self.timeout_s)
        await asyncio.wait_for(client.connect(), timeout=self.timeout_s)

        # Lazy pairing: required on first command. Device must be in pairing mode.
        try:
            await client.pair()
            logger.info("Paired with %s", self.mac)
        except Exception as pair_exc:  # noqa: BLE001 — platform-specific
            # Already paired, or macOS handles bonding differently — continue.
            logger.debug("pair() after connect (%s): %s", self.mac, pair_exc)

        if not client.is_connected:
            raise BleCommandError(
                f"Could not connect to {self.mac}",
                code="ble_connect",
            )

        self._client = client
        logger.info("Connected to %s", self.mac)
        return client

    def _schedule_idle(self) -> None:
        self._cancel_idle()

        async def _idle() -> None:
            try:
                await asyncio.sleep(self.idle_disconnect_s)
                async with self._lock:
                    await self._force_disconnect()
                    logger.debug("Idle-disconnected %s", self.mac)
            except asyncio.CancelledError:
                return

        self._idle_task = asyncio.create_task(_idle())

    def _cancel_idle(self) -> None:
        if self._idle_task is not None:
            self._idle_task.cancel()
            self._idle_task = None

    async def _force_disconnect(self) -> None:
        client = self._client
        self._client = None
        if client is None:
            return
        try:
            if client.is_connected:
                await client.disconnect()
        except Exception:  # noqa: BLE001
            logger.debug("disconnect error for %s", self.mac, exc_info=True)


def normalize_mac(mac: str) -> str:
    """Normalize MAC to uppercase colon-separated form when possible."""
    cleaned = mac.replace("-", ":").replace(".", ":").upper()
    parts = [p for p in cleaned.split(":") if p]
    if len(parts) == 6 and all(len(p) <= 2 for p in parts):
        return ":".join(p.zfill(2) for p in parts)
    # macOS CoreBluetooth may expose UUID-style identifiers — keep as-is.
    return mac.upper()
