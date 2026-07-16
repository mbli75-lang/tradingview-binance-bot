"""Tester för kursdata-normalisering och Börsdata-metadata."""
from __future__ import annotations

import time

from insider_tracker.config import load_config
from insider_tracker.prices.backfill_prices import _to_price_rows
from insider_tracker.prices.borsdata_client import _RateLimiter


def test_to_price_rows_maps_borsdata_fields():
    raw = [
        {"d": "2026-07-10", "o": 5.88, "h": 6.0, "l": 5.81, "c": 5.9, "v": 584605},
        {"d": "2026-07-11", "o": 6.0, "h": 6.3, "l": 5.9, "c": 6.2, "v": 100},
    ]
    rows = _to_price_rows("SE0022242434", raw, "borsdata")
    assert len(rows) == 2
    r = rows[0]
    assert r["isin"] == "SE0022242434"
    assert r["date"] == "2026-07-10"
    assert (r["open"], r["high"], r["low"], r["close"], r["volume"]) == (
        5.88, 6.0, 5.81, 5.9, 584605,
    )
    assert r["source"] == "borsdata"


def test_to_price_rows_skips_rows_without_date():
    raw = [{"o": 1, "h": 1, "l": 1, "c": 1, "v": 1}]  # ingen 'd'
    assert _to_price_rows("SE0001", raw, "borsdata") == []


def test_segment_map_has_small_cap():
    cfg = load_config()
    seg = {int(k): v for k, v in cfg["prices"]["segment_by_market_id"].items()}
    assert seg[3] == "Small Cap"
    assert seg[5] == "Spotlight"
    assert seg[4] == "First North"


def test_rate_limiter_throttles():
    rl = _RateLimiter(max_calls=5, window_seconds=1.0)  # -> effektivt 4 (90%)
    start = time.monotonic()
    for _ in range(5):
        rl.wait()
    # Den femte anropet ska ha tvingat en väntan in i nästa fönster.
    assert time.monotonic() - start >= 0.5
