"""Tester för paper trading-datalagret."""
from __future__ import annotations

from datetime import date

from insider_tracker.paper.data import OHLCData


def make_data():
    bars = {
        "SE0001": [
            (date(2024, 1, 1), 10.0, 10.5, 1000.0),
            (date(2024, 1, 2), 10.6, 11.0, 2000.0),
            (date(2024, 1, 3), 11.0, 10.8, 500.0),
        ]
    }
    cal = [date(2024, 1, 1), date(2024, 1, 2), date(2024, 1, 3)]
    return OHLCData(calendar=cal, bars=bars)


def test_close_series():
    d = make_data()
    assert d.close_series("SE0001") == [
        (date(2024, 1, 1), 10.5), (date(2024, 1, 2), 11.0), (date(2024, 1, 3), 10.8)]
    assert d.close_series("UNKNOWN") == []


def test_open_asof_next():
    d = make_data()
    # första handelsdag strikt efter 2024-01-01 -> 2024-01-02 open 10.6
    assert d.open_asof_next("SE0001", date(2024, 1, 1)) == (date(2024, 1, 2), 10.6)
    # efter sista dagen -> None
    assert d.open_asof_next("SE0001", date(2024, 1, 3)) is None


def test_turnover_30d():
    d = make_data()
    # fönster [2023-12-05, 2024-01-04): alla tre dagar
    # (10.5*1000 + 11.0*2000 + 10.8*500) / 3 = (10500 + 22000 + 5400)/3 = 12633.33
    t = d.turnover_30d("SE0001", date(2024, 1, 4), window=30)
    assert round(t, 2) == 12633.33


def test_turnover_none_when_no_data():
    d = make_data()
    assert d.turnover_30d("UNKNOWN", date(2024, 1, 4)) is None
