"""Klusterdetektion + separat backtest (steg 3).

Flagga när >= N unika insiders köper i samma bolag inom ett rullande fönster.
Klustersignalen backtestas separat och får egen avkastningsstatistik.
"""
from __future__ import annotations

import logging
from collections import defaultdict, deque
from datetime import date

from insider_tracker.backtest.dataset import Dataset
from insider_tracker.backtest.returns import compute_horizon
from insider_tracker.backtest.slippage import resolve_slippage
from insider_tracker.config import Config

logger = logging.getLogger(__name__)

_LABELS = {0: "1m", 1: "3m", 2: "6m"}


def _d(s: str) -> date:
    return date.fromisoformat(s[:10])


def detect_clusters(cfg: Config, ds: Dataset) -> list[dict]:
    min_ins = cfg["scoring"]["cluster_min_insiders"]
    win = cfg["scoring"]["cluster_window_days"]

    by_company: dict[str, list[tuple[date, int]]] = defaultdict(list)
    for b in ds.buys:
        by_company[b["company_isin"]].append((_d(b["publish_date"]), b["insider_id"]))

    clusters: list[dict] = []
    for isin, evts in by_company.items():
        evts.sort()
        dq: deque[tuple[date, int]] = deque()
        in_cluster = False
        for dt, ins in evts:
            dq.append((dt, ins))
            while dq and (dt - dq[0][0]).days > win:
                dq.popleft()
            uniq = {i for _, i in dq}
            if len(uniq) >= min_ins and not in_cluster:
                clusters.append({
                    "company_isin": isin,
                    "trigger_date": dt.isoformat(),
                    "window_start": dq[0][0].isoformat(),
                    "n_insiders": len(uniq),
                    "n_buys": len(dq),
                })
                in_cluster = True
            elif len(uniq) < min_ins:
                in_cluster = False

    logger.info("Kluster hittade: %d (>= %d insiders inom %d dagar)",
                len(clusters), min_ins, win)
    return clusters


def backtest_clusters(cfg: Config, ds: Dataset, clusters: list[dict]) -> list[dict]:
    horizons = cfg["backtest"]["horizons_trading_days"]
    for cl in clusters:
        isin = cl["company_isin"]
        series = ds.stock.get(isin)
        cl["exit_status"] = "no_price"
        if not series:
            continue
        segment = ds.segments.get(isin)
        marketplace = ds.marketplaces.get(isin)
        slippage = resolve_slippage(cfg, marketplace, segment)
        trigger = _d(cl["trigger_date"])
        entry_set = False
        for idx, hz in enumerate(horizons):
            res = compute_horizon(ds.calendar, series, ds.benchmark, trigger, hz, slippage)
            if res is None:
                continue
            if not entry_set:
                cl["entry_date"] = res.entry_date.isoformat()
                cl["entry_price"] = res.entry_price
                entry_set = True
            cl[f"exc_{_LABELS[idx]}"] = res.excess_return_net
            cl["exit_status"] = res.exit_status
    return clusters
