"""Backtest-motor: beräknar avkastning per historiskt köp och lagrar trade_returns."""
from __future__ import annotations

import logging
from datetime import date

from insider_tracker.backtest.dataset import Dataset
from insider_tracker.backtest.returns import compute_horizon
from insider_tracker.backtest.slippage import resolve_slippage
from insider_tracker.config import Config

logger = logging.getLogger(__name__)

_LABELS = {0: "1m", 1: "3m", 2: "6m"}  # ordning enligt horizons_trading_days


def _d(s: str) -> date:
    return date.fromisoformat(s[:10])


def compute_trade_returns(cfg: Config, ds: Dataset) -> tuple[list[dict], dict]:
    horizons = cfg["backtest"]["horizons_trading_days"]
    bankrupt = set(cfg["backtest"].get("bankruptcy_isins", []) or [])
    max_return = cfg["backtest"].get("max_stock_return")

    rows: list[dict] = []
    stats = {"buys": len(ds.buys), "computed": 0, "no_price": 0, "no_entry": 0}

    for b in ds.buys:
        isin = b["company_isin"]
        series = ds.stock.get(isin)
        if not series:
            stats["no_price"] += 1
            continue
        pub = _d(b["publish_date"])
        segment = ds.segments.get(isin)
        marketplace = b.get("marketplace") or ds.marketplaces.get(isin)
        slippage = resolve_slippage(cfg, marketplace, segment)
        is_bankrupt = isin in bankrupt

        row: dict = {
            "transaction_id": b["id"],
            "insider_id": b["insider_id"],
            "company_isin": isin,
            "publish_date": pub.isoformat(),
            "marketplace": marketplace,
            "segment": segment,
            "slippage": slippage,
            "amount_sek": b.get("amount_sek"),
            "is_related_party": b.get("is_related_party"),
        }
        overall_status = None
        entry_set = False
        for idx, hz in enumerate(horizons):
            res = compute_horizon(
                ds.calendar, series, ds.benchmark, pub, hz, slippage, is_bankrupt,
                max_return=max_return,
            )
            if res is None:
                continue
            if not entry_set:
                row["entry_date"] = res.entry_date.isoformat()
                row["entry_price"] = res.entry_price
                entry_set = True
            lbl = _LABELS.get(idx, str(hz))
            row[f"ret_{lbl}"] = res.stock_return
            row[f"bench_{lbl}"] = res.benchmark_return
            row[f"exc_{lbl}"] = res.excess_return_net
            overall_status = res.exit_status  # längsta horisontens status

        if not entry_set:
            stats["no_entry"] += 1
            continue
        row["exit_status"] = overall_status
        rows.append(row)
        stats["computed"] += 1

    logger.info("Avkastning beräknad: %s", stats)
    return rows, stats
