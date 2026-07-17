"""Historisk backfill av FI:s insynsregister.

Kör hela backfillen:
    python -m insider_tracker.ingest.backfill

Torrkörning som bara visar parsade exempel (skriver inget till DB):
    python -m insider_tracker.ingest.backfill --dry-run --from 2026-06-01 --to 2026-06-14 --sample 10

Flaggor:
    --from / --to   ISO-datum. Standard: (idag - backfill_years) .. idag.
    --dry-run       Hämta + parsa men skriv inget till databasen.
    --sample N      Skriv ut N parsade exempelrader (impliceras vid --dry-run).
"""
from __future__ import annotations

import argparse
import logging
from dataclasses import asdict
from datetime import date, timedelta

from insider_tracker.config import load_config
from insider_tracker.ingest.fi_client import FIClient
from insider_tracker.ingest.parser import parse_record
from insider_tracker.ingest.repository import IngestStats
from insider_tracker.ingest.sink import make_sink
from insider_tracker.logging_setup import setup_logging
from insider_tracker.notify.telegram import send_error

logger = logging.getLogger(__name__)


def _default_range(cfg) -> tuple[date, date]:
    today = date.today()
    years = cfg["fi"]["backfill_years"]
    start = today - timedelta(days=int(round(years * 365.25)))
    return start, today


def _print_sample(records, n: int) -> None:
    print(f"\n===== {min(n, len(records))} PARSADE EXEMPEL (av {len(records)}) =====")
    for rec in records[:n]:
        d = asdict(rec)
        amount = d["amount_sek"]
        amount_s = f"{amount:,.0f} SEK".replace(",", " ") if amount is not None else "n/a"
        print(
            f"\n  {d['publish_date']} (publ.) | trade {d['trade_date']}\n"
            f"    {d['issuer']}  [{d['isin']}]  {d['marketplace']}\n"
            f"    {d['insider_name']} – {d['role']}  (närstående: {'ja' if d['is_related_party'] else 'nej'})\n"
            f"    {d['type'].upper()} {d['character_raw']} | {d['instrument_type']} "
            f"| {d['volume']:g} @ {d['price']:g} {d['currency']} = {amount_s}"
        )
    print()


def run_backfill(
    from_date: date, to_date: date, dry_run: bool = False, sample: int = 0
) -> IngestStats:
    cfg = load_config()
    client = FIClient(cfg)

    total = IngestStats()
    sink = None if dry_run else make_sink(cfg)

    sample_records: list = []
    total_raw = 0
    total_parsed = 0

    logger.info("Backfill %s .. %s (dry_run=%s)", from_date, to_date, dry_run)
    try:
        for win_from, win_to, rows in client.iter_windows(from_date, to_date):
            total_raw += len(rows)
            parsed = [r for r in (parse_record(row, cfg) for row in rows) if r is not None]
            total_parsed += len(parsed)

            if dry_run:
                if len(sample_records) < max(sample, 1):
                    sample_records.extend(parsed[: max(sample, 1) - len(sample_records)])
            else:
                stats = sink.ingest_batch(parsed)
                total.merge(stats)
                logger.info(
                    "  %s..%s: +%d nya, %d dubbletter", win_from, win_to,
                    stats.inserted, stats.duplicates,
                )
    finally:
        counts = sink.counts() if sink is not None else None
        if sink is not None:
            sink.close()

    logger.info(
        "KLART. Råa rader: %d | parsade (efter filter): %d", total_raw, total_parsed
    )
    if dry_run:
        _print_sample(sample_records, sample or 10)
        print(
            f"[dry-run] Totalt {total_raw} råa rader, {total_parsed} efter filter. "
            f"Inget skrevs till databasen."
        )
    else:
        logger.info(
            "SKREV: +%d transaktioner, %d dubbletter hoppade.",
            total.inserted, total.duplicates,
        )
        logger.info("Totalt i databasen nu: %s", counts)
    return total


def main() -> None:
    setup_logging()
    parser = argparse.ArgumentParser(description="FI insynsregister – historisk backfill")
    parser.add_argument("--from", dest="from_date", help="ISO-datum (from)")
    parser.add_argument("--to", dest="to_date", help="ISO-datum (to)")
    parser.add_argument("--dry-run", action="store_true", help="Skriv inget till DB")
    parser.add_argument("--sample", type=int, default=0, help="Antal exempel att visa")
    args = parser.parse_args()

    cfg = load_config()
    default_from, default_to = _default_range(cfg)
    from_date = date.fromisoformat(args.from_date) if args.from_date else default_from
    to_date = date.fromisoformat(args.to_date) if args.to_date else default_to

    try:
        run_backfill(from_date, to_date, dry_run=args.dry_run, sample=args.sample)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Backfill kraschade")
        send_error("Backfill kraschade", exc)
        raise


if __name__ == "__main__":
    main()
