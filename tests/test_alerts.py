"""Tester för alert-modulen (steg 4)."""
from __future__ import annotations

from insider_tracker.alerts.liquidity import avg_daily_turnover
from insider_tracker.alerts.run_alerts import _percentile
from insider_tracker.alerts.formatting import build_buy_alert, fmt_sek, fmt_pct
from insider_tracker.config import load_config


def test_avg_daily_turnover():
    rows = [{"close": 10.0, "volume": 1000}, {"close": 20.0, "volume": 500}]
    # (10*1000 + 20*500) / 2 = (10000 + 10000)/2 = 10000
    assert avg_daily_turnover(rows) == 10000.0


def test_avg_daily_turnover_skips_missing():
    rows = [{"close": 10.0, "volume": None}, {"close": 5.0, "volume": 200}]
    assert avg_daily_turnover(rows) == 1000.0
    assert avg_daily_turnover([]) is None


def test_percentile():
    vals = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    assert _percentile(vals, 0.80) == 9   # topp 20 %-gräns
    assert _percentile([], 0.8) is None


def test_fmt_helpers():
    assert fmt_sek(1234567) == "1 234 567 kr"
    assert fmt_sek(None) == "n/a"
    assert fmt_pct(0.153) == "+15.3%"
    assert fmt_pct(-0.05) == "-5.0%"


def test_build_buy_alert_contains_key_fields():
    cfg = load_config()
    msg = build_buy_alert(cfg, {
        "company": "Testbolag AB", "issuer": "Testbolag AB",
        "marketplace": "Spotlight", "segment": "Spotlight",
        "insider": "Anna Andersson", "role": "Verkställande direktör",
        "amount_sek": 250000, "is_related_party": False,
        "n_trades": 7, "avg_return_3m": 0.12, "score": 0.35,
        "turnover": 300000, "publish_date": "2026-07-15",
    })
    assert "Testbolag AB" in msg
    assert "Anna Andersson" in msg
    assert "250 000 kr" in msg
    assert "LÅG LIKVIDITET" in msg          # 300k < 500k tröskel
    assert "marknadssok.fi.se" in msg       # FI-länk
    assert "+12.0%" in msg                  # snitt 3m
