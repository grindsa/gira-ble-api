"""In-memory device state merged from advertisements and commands."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal

from gira_ble_api.config import CoverConfig, ThermostatConfig
from gira_ble_api.protocol.ads import AdvertisementUpdate


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class ThermostatState:
    id: str
    name: str
    mac: str
    temperature_c: float | None = None
    setpoint_c: float | None = None
    heating_active: bool | None = None
    last_seen_at: datetime | None = None
    updated_at: datetime | None = None
    rssi: int | None = None
    error: str | None = None

    def to_dict(
        self,
        *,
        online_timeout_s: float,
        paired: bool | None = None,
        now: datetime | None = None,
    ) -> dict:
        ref = now if now is not None else _utcnow()
        online = False
        if self.last_seen_at is not None:
            online = (ref - self.last_seen_at).total_seconds() <= online_timeout_s
        return {
            "id": self.id,
            "name": self.name,
            "mac": self.mac,
            "online": online,
            "paired": paired,
            "temperature_c": self.temperature_c,
            "setpoint_c": self.setpoint_c,
            # GATT-only (property 0xF8); null until a status poll / setpoint write.
            "heating_active": self.heating_active,
            # Last BLE advertisement received from the device (null until first ad).
            "last_seen_at": self.last_seen_at.isoformat() if self.last_seen_at else None,
            # Any local state change (ad, optimistic setpoint, or error).
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "rssi": self.rssi,
            "error": self.error,
        }


@dataclass
class CoverState:
    id: str
    name: str
    mac: str
    position_pct: int | None = None
    last_seen_at: datetime | None = None
    updated_at: datetime | None = None
    rssi: int | None = None
    error: str | None = None

    def to_dict(
        self,
        *,
        online_timeout_s: float,
        paired: bool | None = None,
        now: datetime | None = None,
    ) -> dict:
        ref = now if now is not None else _utcnow()
        online = False
        if self.last_seen_at is not None:
            online = (ref - self.last_seen_at).total_seconds() <= online_timeout_s
        return {
            "id": self.id,
            "name": self.name,
            "mac": self.mac,
            "online": online,
            "paired": paired,
            "position_pct": self.position_pct,
            "last_seen_at": self.last_seen_at.isoformat() if self.last_seen_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "rssi": self.rssi,
            "error": self.error,
        }


Kind = Literal["thermostat", "cover"]


@dataclass
class DeviceStore:
    online_timeout_s: float
    _thermostats: dict[str, ThermostatState] = field(default_factory=dict)
    _covers: dict[str, CoverState] = field(default_factory=dict)
    _mac_to_kind: dict[str, Kind] = field(default_factory=dict)
    _mac_to_id: dict[str, str] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)
    # While the passive scanner is paused for GATT, freeze online ageing at
    # this timestamp so a multi-device heating poll does not mark everyone offline.
    _scan_paused_since: datetime | None = None

    def begin_scan_pause(self) -> None:
        with self._lock:
            if self._scan_paused_since is None:
                self._scan_paused_since = _utcnow()

    def end_scan_pause(self) -> None:
        with self._lock:
            self._scan_paused_since = None

    def _online_reference_now(self) -> datetime:
        """Wall clock, or pause start while the scanner is stopped for GATT."""
        if self._scan_paused_since is not None:
            return self._scan_paused_since
        return _utcnow()

    @classmethod
    def from_config(
        cls,
        thermostats: list[ThermostatConfig],
        *,
        covers: list[CoverConfig] | None = None,
        online_timeout_s: float,
    ) -> DeviceStore:
        store = cls(online_timeout_s=online_timeout_s)
        for t in thermostats:
            store._thermostats[t.id] = ThermostatState(id=t.id, name=t.name, mac=t.mac)
            store._mac_to_id[t.mac.upper()] = t.id
            store._mac_to_kind[t.mac.upper()] = "thermostat"
        for c in covers or []:
            store._covers[c.id] = CoverState(id=c.id, name=c.name, mac=c.mac)
            store._mac_to_id[c.mac.upper()] = c.id
            store._mac_to_kind[c.mac.upper()] = "cover"
        return store

    def list_thermostats(
        self, *, paired_by_mac: dict[str, bool | None] | None = None
    ) -> list[dict]:
        with self._lock:
            now = self._online_reference_now()
            out: list[dict] = []
            for s in self._thermostats.values():
                paired = None
                if paired_by_mac is not None:
                    paired = paired_by_mac.get(s.mac)
                out.append(
                    s.to_dict(
                        online_timeout_s=self.online_timeout_s,
                        paired=paired,
                        now=now,
                    )
                )
            return out

    def list_covers(
        self, *, paired_by_mac: dict[str, bool | None] | None = None
    ) -> list[dict]:
        with self._lock:
            now = self._online_reference_now()
            out: list[dict] = []
            for s in self._covers.values():
                paired = None
                if paired_by_mac is not None:
                    paired = paired_by_mac.get(s.mac)
                out.append(
                    s.to_dict(
                        online_timeout_s=self.online_timeout_s,
                        paired=paired,
                        now=now,
                    )
                )
            return out

    # Back-compat alias used by older call sites / tests.
    def list(self, *, paired_by_mac: dict[str, bool | None] | None = None) -> list[dict]:
        return self.list_thermostats(paired_by_mac=paired_by_mac)

    def get(
        self,
        thermostat_id: str,
        *,
        paired: bool | None = None,
    ) -> dict | None:
        with self._lock:
            state = self._thermostats.get(thermostat_id)
            if state is None:
                return None
            return state.to_dict(
                online_timeout_s=self.online_timeout_s,
                paired=paired,
                now=self._online_reference_now(),
            )

    def get_cover(
        self,
        cover_id: str,
        *,
        paired: bool | None = None,
    ) -> dict | None:
        with self._lock:
            state = self._covers.get(cover_id)
            if state is None:
                return None
            return state.to_dict(
                online_timeout_s=self.online_timeout_s,
                paired=paired,
                now=self._online_reference_now(),
            )

    def get_mac(self, thermostat_id: str) -> str | None:
        with self._lock:
            state = self._thermostats.get(thermostat_id)
            return state.mac if state else None

    def get_cover_mac(self, cover_id: str) -> str | None:
        with self._lock:
            state = self._covers.get(cover_id)
            return state.mac if state else None

    def apply_advertisement(
        self,
        mac: str,
        update: AdvertisementUpdate,
        rssi: int | None = None,
    ) -> None:
        with self._lock:
            key = mac.upper()
            kind = self._mac_to_kind.get(key)
            device_id = self._mac_to_id.get(key)
            if kind is None or device_id is None:
                return
            now = _utcnow()
            if kind == "thermostat":
                state = self._thermostats[device_id]
                state.last_seen_at = now
                state.updated_at = now
                state.error = None
                if rssi is not None:
                    state.rssi = rssi
                if update.temperature_c is not None:
                    state.temperature_c = update.temperature_c
                if update.setpoint_c is not None:
                    state.setpoint_c = update.setpoint_c
                if update.heating_active is not None:
                    state.heating_active = update.heating_active
                return

            state_c = self._covers[device_id]
            state_c.last_seen_at = now
            state_c.updated_at = now
            state_c.error = None
            if rssi is not None:
                state_c.rssi = rssi
            if update.position_pct is not None:
                state_c.position_pct = update.position_pct

    def set_setpoint_optimistic(self, thermostat_id: str, setpoint_c: float) -> None:
        with self._lock:
            state = self._thermostats.get(thermostat_id)
            if state is None:
                return
            state.setpoint_c = setpoint_c
            state.updated_at = _utcnow()
            state.error = None

    def get_setpoint(self, thermostat_id: str) -> float | None:
        with self._lock:
            state = self._thermostats.get(thermostat_id)
            return state.setpoint_c if state else None

    def touch_last_seen(self, thermostat_id: str) -> None:
        """Record that we heard from the device (e.g. GATT connect).

        Keeps ``online`` true while the scanner is paused for a status poll.
        """
        with self._lock:
            state = self._thermostats.get(thermostat_id)
            if state is None:
                return
            now = _utcnow()
            state.last_seen_at = now
            state.updated_at = now

    def apply_status_update(
        self,
        thermostat_id: str,
        update: AdvertisementUpdate,
    ) -> None:
        """Merge GATT-notify fields (heating / temp / setpoint) into state.

        Also refreshes ``last_seen_at``: a live GATT session means the device
        is reachable even while passive scanning is paused.
        """
        with self._lock:
            state = self._thermostats.get(thermostat_id)
            if state is None:
                return
            now = _utcnow()
            state.last_seen_at = now
            state.updated_at = now
            state.error = None
            if update.temperature_c is not None:
                state.temperature_c = update.temperature_c
            if update.setpoint_c is not None:
                state.setpoint_c = update.setpoint_c
            if update.heating_active is not None:
                state.heating_active = update.heating_active

    def set_position_optimistic(self, cover_id: str, position_pct: int) -> None:
        with self._lock:
            state = self._covers.get(cover_id)
            if state is None:
                return
            state.position_pct = position_pct
            state.updated_at = _utcnow()
            state.error = None

    def set_error(self, thermostat_id: str, message: str) -> None:
        with self._lock:
            state = self._thermostats.get(thermostat_id)
            if state is None:
                return
            state.error = message
            state.updated_at = _utcnow()

    def set_cover_error(self, cover_id: str, message: str) -> None:
        with self._lock:
            state = self._covers.get(cover_id)
            if state is None:
                return
            state.error = message
            state.updated_at = _utcnow()
