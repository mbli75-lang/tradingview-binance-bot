"""Parallella exit-regler (steg 5) – rena, testbara funktioner.

Tre regler jämförs för varje köpflagg:
  (a) insider_sell – sälj när insidern själv säljer
  (b) hold_3m      – fast hold i N handelsdagar (63 ≈ 3 mån)
  (c) trailing_15  – trailing stop: sälj när kursen faller X % från toppen

Entry = första handelsdagen >= signaldatum. Öppna positioner mark-to-marketas
mot sista tillgängliga kurs (status 'open').
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from insider_tracker.backtest.returns import PriceSeries, entry_index, price_asof


@dataclass
class ExitResult:
    rule: str
    entry_date: date | None
    entry_price: float | None
    exit_date: date | None
    exit_price: float | None
    gross_return: float | None
    net_return: float | None
    status: str  # closed | open | no_price


def _result(rule, entry_dt, entry_px, exit_dt, exit_px, slippage, status) -> ExitResult:
    gross = net = None
    if entry_px and entry_px > 0 and exit_px is not None:
        gross = exit_px / entry_px - 1.0
        net = gross - slippage
    return ExitResult(rule, entry_dt, entry_px, exit_dt, exit_px, gross, net, status)


def compute_exits(
    calendar: list[date],
    series: PriceSeries,
    signal_date: date,
    sell_dates: list[date],
    hold_days: int,
    trailing_pct: float,
    slippage: float,
) -> list[ExitResult]:
    """Beräkna alla tre exit-reglerna för en köpflagg."""
    i0 = entry_index(calendar, signal_date)
    if i0 is None or not series:
        return [
            _result(r, None, None, None, None, slippage, "no_price")
            for r in ("insider_sell", "hold_3m", "trailing_15")
        ]
    entry_dt = calendar[i0]
    entry = price_asof(series, entry_dt)
    if entry is None:
        return [
            _result(r, entry_dt, None, None, None, slippage, "no_price")
            for r in ("insider_sell", "hold_3m", "trailing_15")
        ]
    entry_px = entry[1]
    last_dt, last_px = series[-1]

    # Kurspunkter strikt efter entry (kronologiska).
    forward = [(d, p) for d, p in series if d > entry_dt]

    # (a) insider_sell
    future_sells = sorted(d for d in sell_dates if d > entry_dt)
    if future_sells:
        sd = future_sells[0]
        sp = price_asof(series, sd)
        a = _result("insider_sell", entry_dt, entry_px,
                    sp[0] if sp else sd, sp[1] if sp else None, slippage, "closed")
    else:
        a = _result("insider_sell", entry_dt, entry_px, last_dt, last_px,
                    slippage, "open")

    # (b) hold_3m
    i_exit = i0 + hold_days
    if i_exit < len(calendar):
        ed = calendar[i_exit]
        ep = price_asof(series, ed)
        status = "closed" if (series[-1][0] >= ed) else "open"
        b = _result("hold_3m", entry_dt, entry_px, ep[0] if ep else ed,
                    ep[1] if ep else None, slippage, status)
    else:
        b = _result("hold_3m", entry_dt, entry_px, last_dt, last_px, slippage, "open")

    # (c) trailing_15
    peak = entry_px
    exit_dt = exit_px = None
    for d, p in forward:
        if p > peak:
            peak = p
        if p <= peak * (1 - trailing_pct):
            exit_dt, exit_px = d, p
            break
    if exit_dt is not None:
        c = _result("trailing_15", entry_dt, entry_px, exit_dt, exit_px, slippage, "closed")
    else:
        c = _result("trailing_15", entry_dt, entry_px, last_dt, last_px, slippage, "open")

    return [a, b, c]
