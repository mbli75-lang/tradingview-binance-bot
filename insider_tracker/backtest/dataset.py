"""Laddar all data steg 3 behöver från databasen till minnet (via sink-repot).

Marknadskalendern = OMXSPI:s handelsdagar (benchmark-serien).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date

from insider_tracker.backtest.returns import PriceSeries
from insider_tracker.config import Config

logger = logging.getLogger(__name__)


def _d(s: str) -> date:
    return date.fromisoformat(s[:10])


@dataclass
class Dataset:
    calendar: list[date]
    benchmark: PriceSeries
    stock: dict[str, PriceSeries]
    buys: list[dict]                       # köp-transaktioner (dictar)
    roles: dict[tuple[int, str], str]      # (insider_id, isin) -> role
    segments: dict[str, str]               # isin -> segment
    marketplaces: dict[str, str] = field(default_factory=dict)


def _get_repo(cfg: Config):
    """Hämta ett REST- eller SQLAlchemy-repo direkt (utan sink-wrappern)."""
    from insider_tracker.ingest.sink import resolve_backend

    if resolve_backend(cfg) == "supabase_rest":
        from insider_tracker.ingest.supabase_repo import SupabaseRestRepository
        return SupabaseRestRepository(cfg)
    from insider_tracker.db.session import new_session
    from insider_tracker.ingest.repository import Repository
    return Repository(new_session())


def load_dataset(cfg: Config) -> Dataset:
    repo = _get_repo(cfg)
    bench_isin = cfg["backtest"]["benchmark_isin"]

    logger.info("Laddar kurser …")
    price_rows = repo.fetch_all("prices", "isin,date,close", order="isin.asc,date.asc")
    stock: dict[str, PriceSeries] = {}
    benchmark: PriceSeries = []
    for r in price_rows:
        c = r.get("close")
        if c is None:
            continue
        d = _d(r["date"])
        if r["isin"] == bench_isin:
            benchmark.append((d, float(c)))
        else:
            stock.setdefault(r["isin"], []).append((d, float(c)))
    benchmark.sort()
    calendar = [d for d, _ in benchmark]
    logger.info("Kurser: %d bolag, %d handelsdagar i kalendern", len(stock), len(calendar))

    logger.info("Laddar köp, roller, segment …")
    buys = repo.fetch_all(
        "transactions",
        "id,insider_id,company_isin,publish_date,marketplace,is_related_party,amount_sek",
        order="publish_date.asc", type="eq.buy",
    )
    role_rows = repo.fetch_all("insider_roles", "insider_id,company_isin,role")
    roles = {
        (r["insider_id"], r["company_isin"]): r.get("role")
        for r in role_rows if r.get("role")
    }
    comp_rows = repo.fetch_all("companies", "isin,segment,marketplace")
    segments = {r["isin"]: r.get("segment") for r in comp_rows}
    marketplaces = {r["isin"]: r.get("marketplace") for r in comp_rows}

    if hasattr(repo, "close"):
        repo.close()

    logger.info("Köp: %d | roller: %d | bolag: %d", len(buys), len(roles), len(segments))
    return Dataset(
        calendar=calendar, benchmark=benchmark, stock=stock, buys=buys,
        roles=roles, segments=segments, marketplaces=marketplaces,
    )
