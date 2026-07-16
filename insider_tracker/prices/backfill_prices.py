"""Backfill av daglig EOD-kursdata för alla spårade bolag.

Börsdata primär (matchat via insId), EODHD fallback för ISIN Börsdata inte täcker
(aktiveras bara om EODHD_API_KEY finns). Inkluderar OMXSPI-benchmark (steg 3).

    python -m insider_tracker.prices.backfill_prices                 # 3 år (default)
    python -m insider_tracker.prices.backfill_prices --from 2025-01-01 --to 2025-12-31
    python -m insider_tracker.prices.backfill_prices --days 10       # senaste N dagar
"""
from __future__ import annotations

import argparse
import logging
from datetime import date, timedelta

from insider_tracker.config import load_config
from insider_tracker.ingest.sink import make_sink
from insider_tracker.logging_setup import setup_logging
from insider_tracker.notify.telegram import send_error
from insider_tracker.prices.borsdata_client import BorsdataClient
from insider_tracker.prices.eodhd_client import EODHDClient

logger = logging.getLogger(__name__)

_FLUSH_EVERY = 2000


def _to_price_rows(isin: str, raw: list[dict], source: str) -> list[dict]:
    rows = []
    for r in raw:
        if not r.get("d"):
            continue
        rows.append({
            "isin": isin, "date": r["d"],
            "open": r.get("o"), "high": r.get("h"), "low": r.get("l"),
            "close": r.get("c"), "volume": r.get("v"), "source": source,
        })
    return rows


def run_price_backfill(from_date: date, to_date: date) -> dict:
    cfg = load_config()
    bd = BorsdataClient(cfg)
    eod = EODHDClient(cfg)
    frm, to = from_date.isoformat(), to_date.isoformat()

    # ISIN -> insId (färsk, täcker även OMXSPI-benchmark).
    isin_to_insid = {i.isin: i.ins_id for i in bd.get_instruments() if i.isin}

    sink = make_sink(cfg)
    stats = {"instruments": 0, "borsdata": 0, "eodhd": 0, "missing": 0, "price_rows": 0}
    buffer: list[dict] = []

    def flush():
        if buffer:
            sink.upsert_prices(buffer)
            stats["price_rows"] += len(buffer)
            buffer.clear()

    try:
        companies = sink.tracked_companies()
        # Lägg till benchmark-ISIN (om ej redan spårat bolag).
        isins = [c["isin"] for c in companies]
        bench = cfg["backtest"].get("benchmark_isin")
        if bench and bench not in isins:
            isins.append(bench)

        for idx, isin in enumerate(isins, 1):
            ins_id = isin_to_insid.get(isin)
            if ins_id is not None:
                raw = bd.get_stock_prices(ins_id, frm, to)
                if raw:
                    buffer.extend(_to_price_rows(isin, raw, "borsdata"))
                    stats["borsdata"] += 1
                else:
                    stats["missing"] += 1
            elif eod.is_enabled():
                raw = eod.get_stock_prices(isin, frm, to)
                if raw:
                    buffer.extend(_to_price_rows(isin, raw, "eodhd"))
                    stats["eodhd"] += 1
                else:
                    stats["missing"] += 1
            else:
                stats["missing"] += 1
            stats["instruments"] += 1

            if len(buffer) >= _FLUSH_EVERY:
                flush()
            if idx % 100 == 0:
                logger.info("  %d/%d bolag – %d prisrader hittills",
                            idx, len(isins), stats["price_rows"] + len(buffer))
        flush()
    finally:
        sink.close()

    logger.info("Pris-backfill klar: %s", stats)
    if not eod.is_enabled() and stats["missing"]:
        logger.info(
            "OBS: %d bolag saknar Börsdata-täckning och EODHD är inaktivt "
            "(sätt EODHD_API_KEY för fallback).", stats["missing"],
        )
    return stats


def main() -> None:
    setup_logging()
    parser = argparse.ArgumentParser(description="Backfill EOD-kursdata")
    parser.add_argument("--from", dest="from_date")
    parser.add_argument("--to", dest="to_date")
    parser.add_argument("--days", type=int, help="Senaste N dagar (override from/to)")
    args = parser.parse_args()

    cfg = load_config()
    to_date = date.fromisoformat(args.to_date) if args.to_date else date.today()
    if args.days:
        from_date = to_date - timedelta(days=args.days)
    elif args.from_date:
        from_date = date.fromisoformat(args.from_date)
    else:
        years = cfg["prices"]["borsdata"]["history_years"]
        from_date = to_date - timedelta(days=int(round(years * 365.25)))

    try:
        run_price_backfill(from_date, to_date)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Pris-backfill kraschade")
        send_error("Pris-backfill kraschade", exc)
        raise


if __name__ == "__main__":
    main()
