"""Slippage-uppslag per marknadsplats/segment (round-trip, köp+sälj sammanlagt)."""
from __future__ import annotations

from insider_tracker.config import Config


def resolve_slippage(cfg: Config, marketplace: str | None, segment: str | None) -> float:
    """Returnera round-trip-slippage för en position.

    Prioritet: segment 'Small Cap' -> Spotlight -> First North -> default.
    """
    sl = cfg["slippage"]
    default = sl.get("Nasdaq Stockholm", 0.015)
    if segment == "Small Cap":
        return sl.get("Nasdaq Stockholm Small Cap", default)
    if segment == "Spotlight" or marketplace == "Spotlight":
        return sl.get("Spotlight", default)
    if segment == "First North" or marketplace == "First North":
        return sl.get("First North", default)
    if marketplace == "Nasdaq Stockholm":
        # Mid/Large Cap eller okänt Nasdaq-segment.
        return sl.get("Nasdaq Stockholm", default)
    return default
