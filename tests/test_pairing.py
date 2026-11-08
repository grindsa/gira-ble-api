"""Unit tests for OS pairing helpers (no hardware)."""

from __future__ import annotations

from gira_ble_api.ble.pairing import normalize_pair_address


def test_normalize_mac() -> None:
    assert normalize_pair_address("aa:bb:cc:dd:ee:ff") == "AA:BB:CC:DD:EE:FF"
    assert normalize_pair_address("AA-BB-CC-DD-EE-FF") == "AA:BB:CC:DD:EE:FF"


def test_normalize_uuid() -> None:
    uid = "36E35757-69C2-7C3E-712B-C525537FB9F1"
    assert normalize_pair_address(uid.lower()) == uid
