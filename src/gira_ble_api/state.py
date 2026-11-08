"""In-memory thermostat state merged from advertisements and commands."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone

from gira_ble_api.config import ThermostatConfig
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
    last_seen_at: datetime | None = None
    updated_at: datetime | None = None
    rssi: int | None = None
    error: str | None = None

    def to_dict(
        self,
        *,
        online_timeout_s: float,
        paired: bool | None = None,
    ) -> dict:
        now = _utcnow()
        online = False
        if self.last_seen_at is not None:
            online = (now - self.last_seen_at).total_seconds() <= online_timeout_s
        return {
            "id": self.id,
            "name": self.name,
            "mac": self.mac,
            "online": online,
            "paired": paired,
            "temperature_c": self.temperature_c,
            "setpoint_c": self.setpoint_c,
            # Last BLE advertisement received from the device (null until first ad).
            "last_seen_at": self.last_seen_at.isoformat() if self.last_seen_at else None,
            # Any local state change (ad, optimistic setpoint, or error).
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "rssi": self.rssi,
            "error": self.error,
        }


@dataclass
class DeviceStore:
    online_timeout_s: float
    _by_id: dict[str, ThermostatState] = field(default_factory=dict)
    _mac_to_id: dict[str, str] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    @classmethod
    def from_config(
        cls,
        thermostats: list[ThermostatConfig],
        *,
        online_timeout_s: float,
    ) -> DeviceStore:
        store = cls(online_timeout_s=online_timeout_s)
        for t in thermostats:
            store._by_id[t.id] = ThermostatState(id=t.id, name=t.name, mac=t.mac)
            store._mac_to_id[t.mac.upper()] = t.id
        return store

    def list(self, *, paired_by_mac: dict[str, bool | None] | None = None) -> list[dict]:
        with self._lock:
            out: list[dict] = []
            for s in self._by_id.values():
                paired = None
                if paired_by_mac is not None:
                    paired = paired_by_mac.get(s.mac)
                out.append(
                    s.to_dict(online_timeout_s=self.online_timeout_s, paired=paired)
                )
            return out

    def get(
        self,
        thermostat_id: str,
        *,
        paired: bool | None = None,
    ) -> dict | None:
        with self._lock:
            state = self._by_id.get(thermostat_id)
            if state is None:
                return None
            return state.to_dict(
                online_timeout_s=self.online_timeout_s,
                paired=paired,
            )

    def get_mac(self, thermostat_id: str) -> str | None:
        with self._lock:
            state = self._by_id.get(thermostat_id)
            return state.mac if state else None

    def apply_advertisement(
        self,
        mac: str,
        update: AdvertisementUpdate,
        rssi: int | None = None,
    ) -> None:
        with self._lock:
            tid = self._mac_to_id.get(mac.upper())
            if tid is None:
                return
            state = self._by_id[tid]
            now = _utcnow()
            state.last_seen_at = now
            state.updated_at = now
            state.error = None
            if rssi is not None:
                state.rssi = rssi
            if update.temperature_c is not None:
                state.temperature_c = update.temperature_c
            if update.setpoint_c is not None:
                state.setpoint_c = update.setpoint_c

    def set_setpoint_optimistic(self, thermostat_id: str, setpoint_c: float) -> None:
        with self._lock:
            state = self._by_id.get(thermostat_id)
            if state is None:
                return
            state.setpoint_c = setpoint_c
            state.updated_at = _utcnow()
            state.error = None

    def set_error(self, thermostat_id: str, message: str) -> None:
        with self._lock:
            state = self._by_id.get(thermostat_id)
            if state is None:
                return
            state.error = message
            state.updated_at = _utcnow()
