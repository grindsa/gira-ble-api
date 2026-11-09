"""YAML configuration loading."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator

from gira_ble_api.ble.client import normalize_mac


def parse_api_tokens(value: Any) -> list[str]:
    """Normalize api_tokens from YAML (comma-string, list, or empty)."""
    if value is None:
        return []
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    if isinstance(value, list):
        tokens: list[str] = []
        for item in value:
            text = str(item).strip()
            if text:
                tokens.append(text)
        return tokens
    raise ValueError("api_tokens must be a string, list, or empty")


class ThermostatConfig(BaseModel):
    id: str
    name: str
    mac: str

    @field_validator("mac")
    @classmethod
    def _norm_mac(cls, value: str) -> str:
        return normalize_mac(value)

    @field_validator("id")
    @classmethod
    def _non_empty_id(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("thermostat id must not be empty")
        return cleaned


class CoverConfig(BaseModel):
    id: str
    name: str
    mac: str

    @field_validator("mac")
    @classmethod
    def _norm_mac(cls, value: str) -> str:
        return normalize_mac(value)

    @field_validator("id")
    @classmethod
    def _non_empty_id(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("cover id must not be empty")
        return cleaned


class AppConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = 8787
    online_timeout_s: float = 120.0
    ble_timeout_s: float = 20.0
    idle_disconnect_s: float = 5.0
    # Background GATT poll for heating_active. 0 / omitted = no poll (on-demand only).
    # Set e.g. 120 to poll every 2 minutes on the Pi.
    heating_poll_s: float = 0.0
    # How long to keep GATT open waiting for property 0xF8 after connect/write.
    # Returns early once heating_active arrives (often ~10–15s after provoke).
    heating_listen_s: float = 20.0
    # Empty / omitted → no auth. Comma-separated string or YAML list of Bearer tokens.
    api_tokens: list[str] = Field(default_factory=list)
    thermostats: list[ThermostatConfig] = Field(default_factory=list)
    covers: list[CoverConfig] = Field(default_factory=list)

    @field_validator("api_tokens", mode="before")
    @classmethod
    def _parse_tokens(cls, value: Any) -> list[str]:
        return parse_api_tokens(value)

    @field_validator("thermostats")
    @classmethod
    def _unique_thermostats(cls, value: list[ThermostatConfig]) -> list[ThermostatConfig]:
        ids = [t.id for t in value]
        if len(ids) != len(set(ids)):
            raise ValueError("thermostat ids must be unique")
        macs = [t.mac for t in value]
        if len(macs) != len(set(macs)):
            raise ValueError("thermostat mac addresses must be unique")
        return value

    @field_validator("covers")
    @classmethod
    def _unique_covers(cls, value: list[CoverConfig]) -> list[CoverConfig]:
        ids = [c.id for c in value]
        if len(ids) != len(set(ids)):
            raise ValueError("cover ids must be unique")
        macs = [c.mac for c in value]
        if len(macs) != len(set(macs)):
            raise ValueError("cover mac addresses must be unique")
        return value

    @model_validator(mode="after")
    def _unique_across_device_types(self) -> AppConfig:
        thermo_ids = {t.id for t in self.thermostats}
        cover_ids = {c.id for c in self.covers}
        overlap_ids = thermo_ids & cover_ids
        if overlap_ids:
            raise ValueError(
                f"device ids must be unique across thermostats and covers: "
                f"{sorted(overlap_ids)}"
            )
        thermo_macs = {t.mac for t in self.thermostats}
        cover_macs = {c.mac for c in self.covers}
        overlap_macs = thermo_macs & cover_macs
        if overlap_macs:
            raise ValueError(
                f"mac addresses must be unique across thermostats and covers: "
                f"{sorted(overlap_macs)}"
            )
        return self


def load_config(path: str | Path) -> AppConfig:
    """Load and validate config from a YAML file."""
    config_path = Path(path)
    if not config_path.is_file():
        raise FileNotFoundError(f"Config not found: {config_path}")
    raw: Any = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError("Config root must be a mapping")
    return AppConfig.model_validate(raw)
