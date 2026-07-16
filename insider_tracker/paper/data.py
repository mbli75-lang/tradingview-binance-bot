"""Dataladdning för paper trading: OHLCV-serier + marknadskalender."""
from __future__ import annotations

import bisect
import logging
import statistics
from dataclasses import dataclass
from datetime import date, timedelta

from insider_tracker.config import Config

logger = logging.getLogger(__name__)


def _d(s: str) -> date:
    return date.fromisoformat(s[:10])


@dataclass
class OHLCData:
    calendar: list[date]
    # isin -> kronologisk lista av (datum, open, close, volume)
    bars: dict[str, list[tuple[date, float | None, float, float | None]]]

    def close_series(self, isin: str) -> list[tuple[date, float]]:
        return [(d, c) for d, _o, c, _v in self.bars.get(isin, [])]

    def open_asof_next(self, isin: str, after: date) -> tuple[date, float] | None:
        """Öppningskurs för första handelsdagen strikt efter 'after'."""
        bars = self.bars.get(isin)
        if not bars:
            return None
        dates = [b[0] for b in bars]
        i = bisect.bisect_right(dates, after)
        while i < len(bars):
            if bars[i][1] is not None:
                return bars[i][0], bars[i][1]
            i += 1
        return None

    def turnover_30d(self, isin: str, before: date, window: int = 30) -> float | None:
        """Snitt daglig omsättning (close*volume) i fönstret [before-window, before)."""
        bars = self.bars.get(isin)
        if not bars:
            return None
        start = before - timedelta(days=window)
        vals = [c * v for d, _o, c, v in bars
                if start <= d < before and v is not None]
        return statistics.mean(vals) if vals else None


def load_ohlc(cfg: Config, repo) -> OHLCData:
    bench_isin = cfg["backtest"]["benchmark_isin"]
    rows = repo.fetch_all("prices", "isin,date,open,close,volume",
                          order="isin.asc,date.asc")
    bars: dict[str, list] = {}
    bench: list[tuple[date, float]] = []
    for r in rows:
        c = r.get("close")
        if c is None:
            continue
        d = _d(r["date"])
        o = r.get("open")
        v = r.get("volume")
        if r["isin"] == bench_isin:
            bench.append((d, float(c)))
        else:
            bars.setdefault(r["isin"], []).append(
                (d, float(o) if o is not None else None, float(c),
                 float(v) if v is not None else None))
    bench.sort()
    calendar = [d for d, _ in bench]
    logger.info("OHLCV: %d bolag, %d handelsdagar", len(bars), len(calendar))
    return OHLCData(calendar=calendar, bars=bars)
