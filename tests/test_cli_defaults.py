"""CLI argv defaults (no BLE)."""

from __future__ import annotations

from gira_ble_api.main import _with_default_serve


def test_default_serve_when_empty() -> None:
    assert _with_default_serve([]) == ["serve"]


def test_default_serve_for_flags() -> None:
    assert _with_default_serve(["-c", "config.yaml"]) == ["serve", "-c", "config.yaml"]


def test_verbose_then_serve_flags() -> None:
    assert _with_default_serve(["-v", "-c", "config.yaml"]) == [
        "-v",
        "serve",
        "-c",
        "config.yaml",
    ]


def test_keeps_scan() -> None:
    assert _with_default_serve(["scan", "--seconds", "5"]) == ["scan", "--seconds", "5"]


def test_verbose_before_scan() -> None:
    assert _with_default_serve(["-v", "scan"]) == ["-v", "scan"]
