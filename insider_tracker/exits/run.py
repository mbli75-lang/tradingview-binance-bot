"""Exit-tracker + månadsrapport (steg 5).

    python -m insider_tracker.exits.run                 # spåra exits + skicka rapport
    python -m insider_tracker.exits.run --track         # bara uppdatera signal_exits
    python -m insider_tracker.exits.run --report        # bara skicka månadsrapport
    python -m insider_tracker.exits.run --report --dry-run   # förhandsvisa rapporten
"""
from __future__ import annotations

import argparse
import logging

from insider_tracker.backtest.dataset import _get_repo
from insider_tracker.config import load_config
from insider_tracker.exits.monthly_report import send_monthly_report
from insider_tracker.exits.tracker import track_exits
from insider_tracker.logging_setup import setup_logging
from insider_tracker.notify.telegram import send_error

logger = logging.getLogger(__name__)


def main() -> None:
    setup_logging()
    p = argparse.ArgumentParser(description="Exit-tracker + månadsrapport")
    p.add_argument("--track", action="store_true", help="Uppdatera signal_exits")
    p.add_argument("--report", action="store_true", help="Skicka månadsrapport")
    p.add_argument("--dry-run", action="store_true", help="Förhandsvisa rapport (skicka ej)")
    args = p.parse_args()
    if not (args.track or args.report):
        args.track = args.report = True

    cfg = load_config()
    try:
        if args.track:
            track_exits(cfg)
        if args.report:
            repo = _get_repo(cfg)
            exits = repo.fetch_all(
                "signal_exits", "rule,net_return,gross_return,status")
            if hasattr(repo, "close"):
                repo.close()
            send_monthly_report(cfg, exits, dry_run=args.dry_run)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Exit-körning kraschade")
        send_error("Exit-körning kraschade", exc)
        raise


if __name__ == "__main__":
    main()
