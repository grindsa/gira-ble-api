"""Position encode/decode for Gira System 3000 covers (blinds / shutters)."""

from __future__ import annotations

from .constants import COVER_MAX_PCT, COVER_MIN_PCT


def clamp_position_pct(position_pct: float | int) -> int:
    """Clamp cover position to 0–100 (0=closed, 100=open)."""
    return max(COVER_MIN_PCT, min(COVER_MAX_PCT, int(round(float(position_pct)))))


def raw_to_position_pct(raw: int) -> int:
    """Convert Gira PDT_SCALING byte to percent open.

    0x00 → 100% open, 0xFF → 0% open (fully closed).
    """
    raw = max(0, min(255, int(raw) & 0xFF))
    return int(round(100.0 - (raw / 255.0) * 100.0))


def position_pct_to_raw(position_pct: float | int) -> int:
    """Convert percent open (0=closed, 100=open) to Gira PDT_SCALING byte."""
    pct = clamp_position_pct(position_pct)
    return max(0, min(255, int(round((100 - pct) / 100.0 * 255.0))))
