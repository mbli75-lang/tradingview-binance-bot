"""Dagligt EOD-delta (cron, efter FI-ingest). Hämtar senaste dagarna för alla bolag.

    python -m insider_tracker.prices.daily_prices [--days N]
"""
from __future__ import annotations

import argparse
import logging
from datetime import date, timedelta

from insider_tracker.prices.backfill_prices import run_price_backfill
from insider_tracker.logging_setup import setup_logging
from insider_tracker.notify.telegram import send_error

logger = logging.getLogger(__name__)

DEFAULT_LOOKBACK_DAYS = 5  # täcker helg + någon dags marginal


def main() -> None:
    setup_logging()
    parser = argparse.ArgumentParser(description="Dagligt EOD-kursdelta")
    parser.add_argument("--days", type=int, default=DEFAULT_LOOKBACK_DAYS)
    args = parser.parse_args()
    to_date = date.today()
    from_date = to_date - timedelta(days=args.days)
    try:
        run_price_backfill(from_date, to_date)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Daglig prisuppdatering kraschade")
        send_error("Daglig prisuppdatering kraschade", exc)
        raise


if __name__ == "__main__":
    main()
