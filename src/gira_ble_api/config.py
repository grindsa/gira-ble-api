"""YAML configuration loading."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, field_validator

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


class AppConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = 8787
    online_timeout_s: float = 120.0
    ble_timeout_s: float = 20.0
    idle_disconnect_s: float = 5.0
    # Empty / omitted → no auth. Comma-separated string or YAML list of Bearer tokens.
    api_tokens: list[str] = Field(default_factory=list)
    thermostats: list[ThermostatConfig] = Field(default_factory=list)

    @field_validator("api_tokens", mode="before")
    @classmethod
    def _parse_tokens(cls, value: Any) -> list[str]:
        return parse_api_tokens(value)

    @field_validator("thermostats")
    @classmethod
    def _unique_ids(cls, value: list[ThermostatConfig]) -> list[ThermostatConfig]:
        ids = [t.id for t in value]
        if len(ids) != len(set(ids)):
            raise ValueError("thermostat ids must be unique")
        macs = [t.mac for t in value]
        if len(macs) != len(set(macs)):
            raise ValueError("thermostat mac addresses must be unique")
        return value


def load_config(path: str | Path) -> AppConfig:
    """Load and validate config from a YAML file."""
    config_path = Path(path)
    if not config_path.is_file():
        raise FileNotFoundError(f"Config not found: {config_path}")
    raw: Any = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError("Config root must be a mapping")
    return AppConfig.model_validate(raw)
