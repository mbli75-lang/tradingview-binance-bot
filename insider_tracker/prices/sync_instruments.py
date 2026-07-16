"""Synka Börsdata-instrumentmetadata till companies.

Berikar varje bolag (matchat på ISIN) med:
  * borsdata_ins_id  – för prishämtning
  * segment          – Large/Mid/Small Cap, First North, Spotlight, NGM (marketId)
  * sector           – sektornamn (sectorId)

Small Cap-segmentet är det FI inte kan ge; här kommer det från Börsdata.

    python -m insider_tracker.prices.sync_instruments
"""
from __future__ import annotations

import logging

from insider_tracker.config import load_config
from insider_tracker.ingest.sink import make_sink
from insider_tracker.logging_setup import setup_logging
from insider_tracker.notify.telegram import send_error
from insider_tracker.prices.borsdata_client import BorsdataClient

logger = logging.getLogger(__name__)


def run_sync() -> dict:
    cfg = load_config()
    client = BorsdataClient(cfg)
    segment_map = {int(k): v for k, v in cfg["prices"]["segment_by_market_id"].items()}

    sectors = client.get_sectors()
    instruments = client.get_instruments(country_only=True)
    by_isin = {i.isin: i for i in instruments if i.isin}
    logger.info("Börsdata: %d svenska instrument (%d med ISIN)",
                len(instruments), len(by_isin))

    sink = make_sink(cfg)
    try:
        companies = sink.tracked_companies()
        rows = []
        matched = 0
        seg_counter: dict[str, int] = {}
        for c in companies:
            inst = by_isin.get(c["isin"])
            if inst is None:
                continue
            matched += 1
            segment = segment_map.get(inst.market_id) if inst.market_id else None
            rows.append({
                "isin": c["isin"],
                # name måste med: PostgREST-upsert är INSERT..ON CONFLICT och
                # companies.name är NOT NULL. Behåller FI:s namn oförändrat.
                "name": c["name"],
                "borsdata_ins_id": inst.ins_id,
                "segment": segment,
                "sector": sectors.get(inst.sector_id) if inst.sector_id else None,
            })
            seg_counter[segment or "?"] = seg_counter.get(segment or "?", 0) + 1
        sink.update_companies_meta(rows)
    finally:
        sink.close()

    result = {
        "companies": len(companies),
        "matched": matched,
        "unmatched": len(companies) - matched,
        "by_segment": dict(sorted(seg_counter.items(), key=lambda x: -x[1])),
    }
    logger.info("Synk klar: %s", result)
    return result


def main() -> None:
    setup_logging()
    try:
        run_sync()
    except Exception as exc:  # noqa: BLE001
        logger.exception("Instrument-synk kraschade")
        send_error("Instrument-synk kraschade", exc)
        raise


if __name__ == "__main__":
    main()
