"""Dagligt delta av FI:s insynsregister (cron: vardagar 18:00 CET, efter FI:s uppdatering).

Hämtar de senaste N dagarna (default 7 för att täcka helger + 3 dagars
rapporteringsfrist) och upsertar. Idempotent – säker att köra om.

    python -m insider_tracker.ingest.daily [--days N]
"""
from __future__ import annotations

import argparse
import logging
from datetime import date, timedelta

from insider_tracker.ingest.backfill import run_backfill
from insider_tracker.logging_setup import setup_logging
from insider_tracker.notify.telegram import send_error

logger = logging.getLogger(__name__)

# Överlappande fönster: helg (2) + 3 handelsdagars rapporteringsfrist + marginal.
DEFAULT_LOOKBACK_DAYS = 7


def main() -> None:
    setup_logging()
    parser = argparse.ArgumentParser(description="FI insynsregister – dagligt delta")
    parser.add_argument("--days", type=int, default=DEFAULT_LOOKBACK_DAYS)
    args = parser.parse_args()

    to_date = date.today()
    from_date = to_date - timedelta(days=args.days)
    try:
        run_backfill(from_date, to_date, dry_run=False)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Daglig ingest kraschade")
        send_error("Daglig ingest kraschade", exc)
        raise


if __name__ == "__main__":
    main()
