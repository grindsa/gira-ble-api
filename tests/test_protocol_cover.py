"""Unit tests for cover position encode/decode and command frames."""

from __future__ import annotations

import pytest

from gira_ble_api.protocol.commands import (
    build_cover_move,
    build_cover_position,
    build_cover_stop,
)
from gira_ble_api.protocol.cover import (
    clamp_position_pct,
    position_pct_to_raw,
    raw_to_position_pct,
)


def test_raw_to_position_pct_extremes() -> None:
    assert raw_to_position_pct(0x00) == 100
    assert raw_to_position_pct(0xFF) == 0


def test_raw_to_position_pct_mid() -> None:
    # 0x80 ≈ halfway → ~50% open
    assert raw_to_position_pct(0x80) == 50


def test_position_pct_to_raw_extremes() -> None:
    assert position_pct_to_raw(100) == 0x00
    assert position_pct_to_raw(0) == 0xFF


def test_position_round_trip() -> None:
    for pct in (0, 25, 50, 75, 100):
        assert raw_to_position_pct(position_pct_to_raw(pct)) == pct


def test_clamp_position_pct() -> None:
    assert clamp_position_pct(-5) == 0
    assert clamp_position_pct(150) == 100
    assert clamp_position_pct(33.4) == 33


def test_build_cover_move_up() -> None:
    assert build_cover_move("up") == bytes.fromhex("F6032001FF100100")


def test_build_cover_move_down() -> None:
    assert build_cover_move("down") == bytes.fromhex("F6032001FF100101")


def test_build_cover_move_invalid() -> None:
    with pytest.raises(ValueError):
        build_cover_move("left")  # type: ignore[arg-type]


def test_build_cover_stop() -> None:
    assert build_cover_stop() == bytes.fromhex("F6032001FD100100")


def test_build_cover_position_open() -> None:
    # 100% open → raw 0x00
    assert build_cover_position(100) == bytes.fromhex("F6032001FC100100")


def test_build_cover_position_closed() -> None:
    # 0% open → raw 0xFF
    assert build_cover_position(0) == bytes.fromhex("F6032001FC1001FF")


def test_build_cover_position_half() -> None:
    # 50% → raw 0x80
    assert build_cover_position(50) == bytes.fromhex("F6032001FC100180")
