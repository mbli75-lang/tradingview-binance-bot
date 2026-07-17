"""Paper trading-tracker: en hypotetisk position per live-signal (out-of-sample).

Recompute-idempotent (upsert på signal_id). Loggar båda entry-priserna:
  * teoretiskt = signaldagens stängning (backtestens antagande)
  * realistiskt = nästa handelsdags öppning (mätbar exekveringskostnad)
Exit följer den konfigurerade regeln (default hold_3m).
"""
from __future__ import annotations

import bisect
import logging
from collections import defaultdict
from datetime import date

from insider_tracker.backtest.dataset import _get_repo
from insider_tracker.backtest.returns import price_asof
from insider_tracker.config import Config
from insider_tracker.exits.rules import compute_exits
from insider_tracker.paper.data import load_ohlc

logger = logging.getLogger(__name__)


def _d(s: str) -> date:
    return date.fromisoformat(s[:10])


def sync_paper_trades(cfg: Config) -> dict:
    repo = _get_repo(cfg)
    ohlc = load_ohlc(cfg, repo)
    pcfg = cfg["paper"]
    rule = pcfg["exit_rule"]
    min_turn = pcfg["executable_min_turnover_sek"]
    half_spread = pcfg.get("half_spread_pct", 0.0)
    ex = cfg["exits"]

    signals = repo.fetch_all(
        "signals", "id,isin,insider_id,signal_date,signal_type",
        signal_type="in.(insider_buy,cluster)")
    scores = {s["insider_id"]: s["score"] for s in repo.fetch_all(
        "insider_scores", "insider_id,score")}
    companies = {c["isin"]: c for c in repo.fetch_all(
        "companies", "isin,name,marketplace,segment")}
    roles = {(r["insider_id"], r["company_isin"]): r.get("role")
             for r in repo.fetch_all("insider_roles", "insider_id,company_isin,role")}
    sells: dict[tuple, list[date]] = defaultdict(list)
    if rule == "insider_sell":
        for t in repo.fetch_all("transactions", "insider_id,company_isin,publish_date",
                                type="eq.sell"):
            sells[(t["insider_id"], t["company_isin"])].append(_d(t["publish_date"]))

    rows: list[dict] = []
    stats = {"total": len(signals), "pending_entry": 0, "open": 0, "closed": 0, "no_price": 0}

    for sig in signals:
        isin = sig["isin"]
        sig_date = _d(sig["signal_date"])
        comp = companies.get(isin, {})
        close_series = ohlc.close_series(isin)

        # Entry-index på marknadskalendern (första handelsdag >= signaldatum).
        cal = ohlc.calendar
        i0 = bisect.bisect_left(cal, sig_date)
        theo = price_asof(close_series, cal[i0]) if i0 < len(cal) and close_series else None
        real = ohlc.open_asof_next(isin, cal[i0]) if i0 < len(cal) else None
        turnover = ohlc.turnover_30d(isin, sig_date)

        row = {
            "signal_id": sig["id"], "signal_date": sig["signal_date"][:10], "isin": isin,
            "company": comp.get("name"), "marketplace": comp.get("marketplace"),
            "segment": comp.get("segment"), "insider_id": sig["insider_id"],
            "role": roles.get((sig["insider_id"], isin)),
            "insider_score": scores.get(sig["insider_id"]),
            "signal_type": sig["signal_type"],
            "entry_price_theoretical": theo[1] if theo else None,
            "entry_price_realistic": (real[1] * (1 + half_spread)) if real else None,
            "avg_daily_turnover_30d": turnover,
            "executable": (turnover is not None and turnover >= min_turn),
            "exit_rule": rule,
        }

        if not close_series or theo is None:
            row["status"] = "no_price"
            stats["no_price"] += 1
            rows.append(row)
            continue
        if real is None:
            # Signalen är för färsk – nästa dags öppning finns inte än.
            row["status"] = "pending_entry"
            stats["pending_entry"] += 1
            rows.append(row)
            continue

        # Exit enligt konfigurerad regel (återanvänder testad exit-logik).
        results = {r.rule: r for r in compute_exits(
            cal, close_series, sig_date, sells.get((sig["insider_id"], isin), []),
            hold_days=ex["hold_trading_days"], trailing_pct=ex["trailing_stop_pct"],
            slippage=0.0)}
        res = results[rule]
        row["exit_date"] = res.exit_date.isoformat() if res.exit_date else None
        row["exit_price"] = res.exit_price
        row["status"] = "closed" if res.status == "closed" else "open"
        theo_e = row["entry_price_theoretical"]
        real_e = row["entry_price_realistic"]
        if res.exit_price is not None:
            if theo_e:
                row["return_theoretical"] = res.exit_price / theo_e - 1
            if real_e:
                row["return_realistic"] = res.exit_price / real_e - 1
        stats[row["status"]] += 1
        rows.append(row)

    repo.upsert_paper_trades(rows)
    if hasattr(repo, "close"):
        repo.close()
    logger.info("Paper-tracker: %s", stats)
    return stats
