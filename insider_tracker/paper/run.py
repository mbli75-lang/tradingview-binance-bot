"""Paper trading-CLI.

    python -m insider_tracker.paper.run --track       # uppdatera paper_trades (dagligt)
    python -m insider_tracker.paper.run --weekly       # skicka veckorapport (Telegram)
    python -m insider_tracker.paper.run --weekly --dry-run
    python -m insider_tracker.paper.run --evaluate     # jämförelsetabell (manuellt, 3/6 mån)
"""
from __future__ import annotations

import argparse
import logging

from insider_tracker.backtest.dataset import _get_repo
from insider_tracker.config import load_config
from insider_tracker.logging_setup import setup_logging
from insider_tracker.notify.telegram import send_error
from insider_tracker.paper.evaluate import evaluate
from insider_tracker.paper.tracker import sync_paper_trades
from insider_tracker.paper.weekly_report import send_weekly

logger = logging.getLogger(__name__)


def main() -> None:
    setup_logging()
    p = argparse.ArgumentParser(description="Paper trading – framåt-validering")
    p.add_argument("--track", action="store_true", help="Uppdatera paper_trades")
    p.add_argument("--weekly", action="store_true", help="Skicka veckorapport")
    p.add_argument("--evaluate", action="store_true", help="Jämförelsetabell live vs backtest")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    if not (args.track or args.weekly or args.evaluate):
        args.track = True

    cfg = load_config()
    try:
        if args.track:
            sync_paper_trades(cfg)
        if args.weekly:
            repo = _get_repo(cfg)
            trades = repo.fetch_all(
                "paper_trades",
                "signal_date,isin,company,signal_type,executable,status,"
                "entry_price_theoretical,entry_price_realistic,return_realistic")
            if hasattr(repo, "close"):
                repo.close()
            send_weekly(cfg, trades, dry_run=args.dry_run)
        if args.evaluate:
            print(evaluate(cfg))
    except Exception as exc:  # noqa: BLE001
        logger.exception("Paper trading-körning kraschade")
        send_error("Paper trading-körning kraschade", exc)
        raise


if __name__ == "__main__":
    main()
