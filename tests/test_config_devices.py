"""Config validation for thermostats + covers."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from gira_ble_api.config import AppConfig


def test_unique_across_types_ids() -> None:
    with pytest.raises(ValidationError, match="device ids must be unique"):
        AppConfig.model_validate(
            {
                "thermostats": [
                    {"id": "living", "name": "T", "mac": "AA:BB:CC:DD:EE:FF"}
                ],
                "covers": [
                    {"id": "living", "name": "C", "mac": "11:22:33:44:55:66"}
                ],
            }
        )


def test_unique_across_types_macs() -> None:
    with pytest.raises(ValidationError, match="mac addresses must be unique"):
        AppConfig.model_validate(
            {
                "thermostats": [
                    {"id": "living", "name": "T", "mac": "AA:BB:CC:DD:EE:FF"}
                ],
                "covers": [
                    {"id": "blind", "name": "C", "mac": "AA:BB:CC:DD:EE:FF"}
                ],
            }
        )


def test_covers_only_ok() -> None:
    cfg = AppConfig.model_validate(
        {
            "covers": [
                {"id": "blind", "name": "C", "mac": "11:22:33:44:55:66"}
            ],
        }
    )
    assert len(cfg.covers) == 1
    assert cfg.thermostats == []
