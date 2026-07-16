"""Avkastningsberäkning per köp (steg 3, kärna).

Rena funktioner (inga DB-beroenden) -> lätta att testa.

Princip:
  * Agerbart datum = PUBLICERINGSDATUM (inte transaktionsdatum). Entry = första
    handelsdagen >= publiceringsdatum.
  * Horisonter i HANDELSDAGAR (21/63/126) räknade på marknadskalendern (OMXSPI:s
    handelsdagar).
  * Överavkastning = aktieavkastning − OMXSPI-avkastning för samma period.
  * Slippage (köp+sälj sammanlagt) dras av en gång från överavkastningen.
  * Survivorship: avnoterat bolag exkluderas INTE. Saknas kurs vid exit används
    sista tillgängliga kurs (uppköp), eller −100 % om bolaget är känt konkursat.
"""
from __future__ import annotations

import bisect
from dataclasses import dataclass
from datetime import date

# En kursserie: kronologiskt sorterad lista av (datum, close).
PriceSeries = list[tuple[date, float]]


@dataclass
class HorizonResult:
    horizon_days: int
    entry_date: date
    exit_date: date | None
    entry_price: float
    exit_price: float | None
    stock_return: float | None
    benchmark_return: float | None
    excess_return: float | None       # brutto (stock − benchmark)
    excess_return_net: float | None   # efter slippage
    exit_status: str                  # ok | delisted | bankrupt | pending


def entry_index(calendar: list[date], publish_date: date) -> int | None:
    """Index i kalendern för första handelsdagen >= publiceringsdatum."""
    i = bisect.bisect_left(calendar, publish_date)
    if i >= len(calendar):
        return None
    return i


def price_asof(series: PriceSeries, d: date) -> tuple[date, float] | None:
    """Sista (datum, close) med datum <= d, annars None."""
    if not series:
        return None
    dates = [x[0] for x in series]
    i = bisect.bisect_right(dates, d) - 1
    if i < 0:
        return None
    return series[i]


def compute_horizon(
    calendar: list[date],
    stock: PriceSeries,
    benchmark: PriceSeries,
    publish_date: date,
    horizon_days: int,
    slippage: float,
    is_bankrupt: bool = False,
) -> HorizonResult | None:
    """Beräkna avkastning för en horisont. None om entry saknas helt."""
    i0 = entry_index(calendar, publish_date)
    if i0 is None:
        return None
    entry_dt = calendar[i0]

    entry = price_asof(stock, entry_dt)
    if entry is None:
        return None  # ingen kurs vid entry -> kan ej beräkna
    entry_price = entry[1]
    if entry_price <= 0:
        return None

    i_exit = i0 + horizon_days
    exit_reached = i_exit < len(calendar)
    exit_cal_date = calendar[i_exit] if exit_reached else calendar[-1]

    # Benchmark
    b_entry = price_asof(benchmark, entry_dt)
    b_exit = price_asof(benchmark, exit_cal_date)
    benchmark_return = None
    if b_entry and b_exit and b_entry[1] > 0:
        benchmark_return = b_exit[1] / b_entry[1] - 1.0

    # Aktie
    last_stock_date = stock[-1][0]
    status = "ok"
    if is_bankrupt:
        stock_return = -1.0
        exit_price = 0.0
        status = "bankrupt"
    else:
        s_exit = price_asof(stock, exit_cal_date)
        if s_exit is None:
            return None
        exit_price = s_exit[1]
        stock_return = exit_price / entry_price - 1.0
        if exit_reached and last_stock_date < exit_cal_date:
            # Bolaget slutade handlas före exit -> sista kurs (uppköpsantagande).
            status = "delisted"
        elif not exit_reached:
            # Horisonten sträcker sig bortom tillgänglig data.
            status = "pending"

    excess = None
    excess_net = None
    if benchmark_return is not None and stock_return is not None:
        excess = stock_return - benchmark_return
        excess_net = excess - slippage

    return HorizonResult(
        horizon_days=horizon_days,
        entry_date=entry_dt,
        exit_date=exit_cal_date if (exit_reached or status in ("delisted", "bankrupt")) else None,
        entry_price=entry_price,
        exit_price=exit_price,
        stock_return=stock_return,
        benchmark_return=benchmark_return,
        excess_return=excess,
        excess_return_net=excess_net,
        exit_status=status,
    )
