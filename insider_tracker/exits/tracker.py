"""Exit-tracker (steg 5): beräknar hypotetiskt utfall per exit-regel för varje köpflagg."""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date

from insider_tracker.backtest.dataset import _get_repo, load_dataset
from insider_tracker.backtest.slippage import resolve_slippage
from insider_tracker.config import Config
from insider_tracker.exits.rules import compute_exits

logger = logging.getLogger(__name__)


def _d(s: str) -> date:
    return date.fromisoformat(s[:10])


def track_exits(cfg: Config) -> dict:
    ds = load_dataset(cfg)
    repo = _get_repo(cfg)
    ex = cfg["exits"]
    apply_slip = ex["apply_slippage"]

    signals = repo.fetch_all(
        "signals", "id,isin,insider_id,signal_date", signal_type="eq.insider_buy")

    # Insiderns försäljningar per (insider_id, isin).
    sells: dict[tuple, list[date]] = defaultdict(list)
    for t in repo.fetch_all("transactions", "insider_id,company_isin,publish_date",
                            type="eq.sell"):
        sells[(t["insider_id"], t["company_isin"])].append(_d(t["publish_date"]))

    rows: list[dict] = []
    stats = {"signals": len(signals), "closed": 0, "open": 0, "no_price": 0}

    for sig in signals:
        isin = sig["isin"]
        series = ds.stock.get(isin)
        segment = ds.segments.get(isin)
        marketplace = ds.marketplaces.get(isin)
        slippage = resolve_slippage(cfg, marketplace, segment) if apply_slip else 0.0
        sell_dates = sells.get((sig["insider_id"], isin), [])
        results = compute_exits(
            ds.calendar, series or [], _d(sig["signal_date"]), sell_dates,
            hold_days=ex["hold_trading_days"], trailing_pct=ex["trailing_stop_pct"],
            slippage=slippage,
        )
        for r in results:
            rows.append({
                "signal_id": sig["id"], "isin": isin, "insider_id": sig["insider_id"],
                "signal_date": sig["signal_date"][:10], "rule": r.rule,
                "entry_date": r.entry_date.isoformat() if r.entry_date else None,
                "entry_price": r.entry_price,
                "exit_date": r.exit_date.isoformat() if r.exit_date else None,
                "exit_price": r.exit_price,
                "gross_return": r.gross_return, "net_return": r.net_return,
                "slippage": slippage, "status": r.status,
            })
            stats[r.status] = stats.get(r.status, 0) + 1

    repo.upsert_signal_exits(rows)
    if hasattr(repo, "close"):
        repo.close()
    logger.info("Exit-tracker: %d signaler, %d exit-rader. %s",
                len(signals), len(rows), stats)
    return stats
