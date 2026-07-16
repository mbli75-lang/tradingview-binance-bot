"""Tester för exit-reglerna (steg 5)."""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from insider_tracker.exits.rules import compute_exits


def cal(start: date, n: int) -> list[date]:
    return [start + timedelta(days=i) for i in range(n)]


def series_from(calendar, prices):
    return [(calendar[i], prices[i]) for i in range(len(prices))]


def by_rule(results):
    return {r.rule: r for r in results}


def test_fixed_hold_exits_after_n_days():
    c = cal(date(2024, 1, 1), 100)
    prices = [100.0] * 63 + [130.0] * 37   # kurs 130 vid +63
    s = series_from(c, prices)
    res = by_rule(compute_exits(c, s, c[0], [], hold_days=63, trailing_pct=0.15, slippage=0.0))
    b = res["hold_3m"]
    assert b.status == "closed"
    assert b.exit_date == c[63]
    assert b.exit_price == 130.0
    assert b.gross_return == pytest.approx(0.30)


def test_trailing_stop_triggers_on_15pct_drop():
    c = cal(date(2024, 1, 1), 20)
    # topp 120, sedan fall till 102 (=-15 % från 120) -> exit
    prices = [100, 110, 120, 118, 102] + [100] * 15
    s = series_from(c, [float(p) for p in prices])
    res = by_rule(compute_exits(c, s, c[0], [], hold_days=63, trailing_pct=0.15, slippage=0.0))
    t = res["trailing_15"]
    assert t.status == "closed"
    assert t.exit_price == 102.0
    assert t.exit_date == c[4]


def test_trailing_stop_stays_open_if_never_triggered():
    c = cal(date(2024, 1, 1), 10)
    s = series_from(c, [100.0, 101, 102, 103, 104, 105, 106, 107, 108, 109])
    res = by_rule(compute_exits(c, s, c[0], [], hold_days=63, trailing_pct=0.15, slippage=0.0))
    t = res["trailing_15"]
    assert t.status == "open"
    assert t.exit_price == 109.0   # mark-to-market mot sista kurs


def test_insider_sell_exits_at_sell_date():
    c = cal(date(2024, 1, 1), 30)
    s = series_from(c, [100.0 + i for i in range(30)])
    sell = c[10]
    res = by_rule(compute_exits(c, s, c[0], [sell], hold_days=63, trailing_pct=0.15, slippage=0.0))
    a = res["insider_sell"]
    assert a.status == "closed"
    assert a.exit_date == c[10]
    assert a.exit_price == 110.0


def test_slippage_applied_to_net():
    c = cal(date(2024, 1, 1), 100)
    s = series_from(c, [100.0] * 63 + [130.0] * 37)
    res = by_rule(compute_exits(c, s, c[0], [], hold_days=63, trailing_pct=0.15, slippage=0.04))
    b = res["hold_3m"]
    assert b.gross_return == pytest.approx(0.30)
    assert b.net_return == pytest.approx(0.30 - 0.04)


def test_no_price_series():
    c = cal(date(2024, 1, 1), 30)
    res = compute_exits(c, [], c[0], [], hold_days=63, trailing_pct=0.15, slippage=0.0)
    assert all(r.status == "no_price" for r in res)
    assert len(res) == 3
