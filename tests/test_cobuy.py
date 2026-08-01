"""Tester för sam-köp-detektion (info-flagga)."""
from __future__ import annotations

from datetime import date

from insider_tracker.alerts.cobuy import detect_cobuys


def _b(isin, iid, d):
    return {"company_isin": isin, "insider_id": iid, "publish_date": date.fromisoformat(d)}


def test_two_insiders_within_window_flagged():
    # Micro Systemation-fallet: 2 unika insiders samma dag
    buys = [_b("SE1", 1, "2026-07-31"), _b("SE1", 2, "2026-07-31")]
    out = detect_cobuys(buys, window_days=14, cobuy_min=2, cluster_min=3,
                        since=date(2026, 7, 26))
    assert len(out) == 1
    assert out[0]["isin"] == "SE1" and out[0]["n_insiders"] == 2


def test_three_insiders_is_cluster_not_cobuy():
    buys = [_b("SE1", 1, "2026-07-31"), _b("SE1", 2, "2026-07-30"),
            _b("SE1", 3, "2026-07-29")]
    out = detect_cobuys(buys, 14, 2, 3, since=date(2026, 7, 26))
    assert out == []  # >= cluster_min -> exkluderas (kluster hanteras separat)


def test_single_insider_not_flagged():
    buys = [_b("SE1", 1, "2026-07-31"), _b("SE1", 1, "2026-07-30")]
    out = detect_cobuys(buys, 14, 2, 3, since=date(2026, 7, 26))
    assert out == []  # bara 1 unik insider


def test_old_buys_outside_window_not_counted():
    # en insider nyligen, en för länge sedan -> bara 1 i fönstret
    buys = [_b("SE1", 1, "2026-07-31"), _b("SE1", 2, "2026-06-01")]
    out = detect_cobuys(buys, 14, 2, 3, since=date(2026, 7, 26))
    assert out == []


def test_no_new_buy_since_cutoff():
    buys = [_b("SE1", 1, "2026-07-10"), _b("SE1", 2, "2026-07-10")]
    out = detect_cobuys(buys, 14, 2, 3, since=date(2026, 7, 26))
    assert out == []  # inget nytt köp i lookback
