"""Likviditetsberäkning: genomsnittlig daglig omsättning (SEK) senaste N dagarna."""
from __future__ import annotations

import statistics


def avg_daily_turnover(price_rows: list[dict]) -> float | None:
    """Snitt av daglig omsättning = close * volume över raderna.

    price_rows: [{close, volume}, …] (redan filtrerade till fönstret).
    """
    vals = []
    for r in price_rows:
        c, v = r.get("close"), r.get("volume")
        if c is None or v is None:
            continue
        vals.append(float(c) * float(v))
    if not vals:
        return None
    return statistics.mean(vals)
