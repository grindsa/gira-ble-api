"""Report whether a device is paired/bonded with the host OS.

Linux: BlueZ via ``bluetoothctl devices Paired``
macOS: ``system_profiler SPBluetoothDataType`` (+ optional IOBluetooth)
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import subprocess
import sys
import time

logger = logging.getLogger(__name__)

_CACHE_TTL_S = 5.0
_cache_at: float = 0.0
_cache_addrs: set[str] | None = None

_MAC_RE = re.compile(r"(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}")
_UUID_RE = re.compile(
    r"[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}"
)


def normalize_pair_address(address: str) -> str:
    """Uppercase; classic MACs use colon separators."""
    text = address.strip().upper().replace("-", ":")
    if re.fullmatch(r"([0-9A-F]{2}:){5}[0-9A-F]{2}", text):
        return text
    return address.strip().upper()


def _collect_addresses_from_obj(node: object, out: set[str]) -> None:
    if isinstance(node, dict):
        for key, val in node.items():
            key_l = str(key).lower()
            if isinstance(val, str) and (
                "address" in key_l or key_l in {"device_address", "address", "coredevice"}
            ):
                for match in _MAC_RE.finditer(val):
                    out.add(normalize_pair_address(match.group(0)))
                for match in _UUID_RE.finditer(val):
                    out.add(match.group(0).upper())
            _collect_addresses_from_obj(val, out)
    elif isinstance(node, list):
        for item in node:
            _collect_addresses_from_obj(item, out)
    elif isinstance(node, str):
        for match in _MAC_RE.finditer(node):
            out.add(normalize_pair_address(match.group(0)))
        for match in _UUID_RE.finditer(node):
            out.add(match.group(0).upper())


def _paired_addresses_linux() -> set[str]:
    try:
        proc = subprocess.run(
            ["bluetoothctl", "devices", "Paired"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        logger.debug("bluetoothctl paired list failed: %s", exc)
        return set()

    addrs: set[str] = set()
    for line in proc.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0] == "Device":
            addrs.add(normalize_pair_address(parts[1]))
    return addrs


def _paired_addresses_iobluetooth() -> set[str]:
    addrs: set[str] = set()
    try:
        from IOBluetooth import IOBluetoothDevice  # type: ignore
    except Exception:
        return addrs

    paired = IOBluetoothDevice.pairedDevices()
    if not paired:
        return addrs
    for device in paired:
        try:
            address = device.addressString()
        except Exception:  # noqa: BLE001
            continue
        if address:
            addrs.add(normalize_pair_address(str(address)))
    return addrs


def _paired_addresses_macos() -> set[str]:
    addrs: set[str] = set()
    try:
        proc = subprocess.run(
            ["system_profiler", "SPBluetoothDataType", "-json"],
            check=False,
            capture_output=True,
            text=True,
            timeout=25,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        logger.debug("system_profiler Bluetooth failed: %s", exc)
        return set()

    if proc.returncode != 0 or not proc.stdout.strip():
        return set()

    try:
        report = json.loads(proc.stdout)
    except json.JSONDecodeError:
        logger.debug("system_profiler returned invalid JSON")
        return set()

    _collect_addresses_from_obj(report, addrs)
    try:
        addrs |= _paired_addresses_iobluetooth()
    except Exception as exc:  # noqa: BLE001
        logger.debug("IOBluetooth paired query failed: %s", exc)
    return addrs


def list_paired_addresses(*, force_refresh: bool = False) -> set[str] | None:
    """Paired addresses, or None if this OS cannot report pairing."""
    global _cache_at, _cache_addrs

    now = time.monotonic()
    if (
        not force_refresh
        and _cache_addrs is not None
        and (now - _cache_at) < _CACHE_TTL_S
    ):
        return set(_cache_addrs)

    if sys.platform.startswith("linux"):
        addrs = _paired_addresses_linux()
    elif sys.platform == "darwin":
        addrs = _paired_addresses_macos()
    else:
        return None

    _cache_at = now
    _cache_addrs = set(addrs)
    logger.debug("paired address cache: %d device(s)", len(addrs))
    return set(addrs)


def is_paired(address: str) -> bool | None:
    """True/False if known; None if unsupported on this host."""
    paired = list_paired_addresses()
    if paired is None:
        return None
    return normalize_pair_address(address) in paired


async def paired_map_async(addresses: list[str]) -> dict[str, bool | None]:
    """Resolve pairing for many addresses with one OS query."""

    def _run() -> dict[str, bool | None]:
        paired = list_paired_addresses()
        if paired is None:
            return {a: None for a in addresses}
        return {a: (normalize_pair_address(a) in paired) for a in addresses}

    return await asyncio.to_thread(_run)
