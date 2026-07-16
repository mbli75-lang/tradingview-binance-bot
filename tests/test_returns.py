"""Tester för avkastningsberäkningen (steg 3). Kravspec: tester för avkastning."""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from insider_tracker.backtest.returns import (
    compute_horizon,
    entry_index,
    price_asof,
)


def make_calendar(start: date, n: int) -> list[date]:
    """n på varandra följande 'handelsdagar' (förenklat: kalenderdagar)."""
    return [start + timedelta(days=i) for i in range(n)]


def flat_series(calendar, price):
    return [(d, price) for d in calendar]


def test_entry_index_first_trading_day_on_or_after_publish():
    cal = make_calendar(date(2024, 1, 1), 10)
    # publiceringsdatum finns i kalendern
    assert entry_index(cal, date(2024, 1, 3)) == 2
    # publiceringsdatum på helg/lucka -> nästa handelsdag
    cal2 = [date(2024, 1, 1), date(2024, 1, 4), date(2024, 1, 8)]
    assert entry_index(cal2, date(2024, 1, 2)) == 1
    # efter sista handelsdagen -> None
    assert entry_index(cal, date(2024, 2, 1)) is None


def test_price_asof_returns_last_on_or_before():
    s = [(date(2024, 1, 1), 10.0), (date(2024, 1, 3), 12.0)]
    assert price_asof(s, date(2024, 1, 2))[1] == 10.0
    assert price_asof(s, date(2024, 1, 3))[1] == 12.0
    assert price_asof(s, date(2023, 12, 31)) is None


def test_basic_return_and_excess():
    cal = make_calendar(date(2024, 1, 1), 30)
    # aktie: 100 vid entry (dag 0), 110 vid +21 handelsdagar
    stock = [(cal[i], 100.0 if i < 21 else 110.0) for i in range(30)]
    # benchmark platt -> ingen benchmarkavkastning
    bench = flat_series(cal, 500.0)
    r = compute_horizon(cal, stock, bench, cal[0], 21, slippage=0.0)
    assert r is not None
    assert r.entry_price == 100.0
    assert r.exit_price == 110.0
    assert r.stock_return == pytest.approx(0.10)
    assert r.benchmark_return == pytest.approx(0.0)
    assert r.excess_return == pytest.approx(0.10)
    assert r.exit_status == "ok"


def test_excess_subtracts_benchmark():
    cal = make_calendar(date(2024, 1, 1), 30)
    stock = [(cal[i], 100.0 if i < 21 else 110.0) for i in range(30)]     # +10 %
    bench = [(cal[i], 500.0 if i < 21 else 520.0) for i in range(30)]     # +4 %
    r = compute_horizon(cal, stock, bench, cal[0], 21, slippage=0.0)
    assert r.excess_return == pytest.approx(0.10 - 0.04)


def test_slippage_deducted_from_excess():
    cal = make_calendar(date(2024, 1, 1), 30)
    stock = [(cal[i], 100.0 if i < 21 else 110.0) for i in range(30)]
    bench = flat_series(cal, 500.0)
    r = compute_horizon(cal, stock, bench, cal[0], 21, slippage=0.04)  # Spotlight
    assert r.excess_return == pytest.approx(0.10)
    assert r.excess_return_net == pytest.approx(0.10 - 0.04)


def test_delisting_uses_last_price():
    cal = make_calendar(date(2024, 1, 1), 30)
    # aktie slutar handlas efter dag 10 på kurs 50 (från entry 100 -> -50 %)
    stock = [(cal[i], 100.0) for i in range(5)] + [(cal[10], 50.0)]
    bench = flat_series(cal, 500.0)
    r = compute_horizon(cal, stock, bench, cal[0], 21, slippage=0.0)
    assert r.exit_status == "delisted"
    assert r.exit_price == 50.0
    assert r.stock_return == pytest.approx(-0.5)


def test_bankruptcy_is_minus_100pct():
    cal = make_calendar(date(2024, 1, 1), 30)
    stock = [(cal[i], 100.0) for i in range(5)]
    bench = flat_series(cal, 500.0)
    r = compute_horizon(cal, stock, bench, cal[0], 21, slippage=0.0, is_bankrupt=True)
    assert r.exit_status == "bankrupt"
    assert r.stock_return == -1.0


def test_winsorize_caps_extreme_return():
    cal = make_calendar(date(2024, 1, 1), 30)
    # aktie 100x (penny stock): 1 -> 100 vid +21 dagar = +9900 %
    stock = [(cal[i], 1.0 if i < 21 else 100.0) for i in range(30)]
    bench = flat_series(cal, 500.0)
    r = compute_horizon(cal, stock, bench, cal[0], 21, slippage=0.0, max_return=5.0)
    assert r.stock_return == pytest.approx(5.0)  # kapat till +500 %


def test_no_entry_price_returns_none():
    cal = make_calendar(date(2024, 1, 1), 30)
    stock = [(cal[i], 100.0) for i in range(30)]
    bench = flat_series(cal, 500.0)
    # publiceringsdatum efter sista handelsdag
    assert compute_horizon(cal, stock, bench, date(2025, 1, 1), 21, 0.0) is None


def test_pending_when_horizon_beyond_data():
    cal = make_calendar(date(2024, 1, 1), 10)  # bara 10 handelsdagar
    stock = flat_series(cal, 100.0)
    bench = flat_series(cal, 500.0)
    r = compute_horizon(cal, stock, bench, cal[0], 21, slippage=0.0)
    assert r.exit_status == "pending"
