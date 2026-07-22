"""Konsoliderad pipeline: en körning som gör allt i rätt ordning.

Daglig körning (vardagar efter FI:s uppdatering):
    python -m insider_tracker.pipeline --daily

Veckorapport (t.ex. måndagar):
    python -m insider_tracker.pipeline --weekly

Best-effort: varje steg är isolerat. Om ett steg fallerar loggas felet (och
skickas till Telegram) men pipelinen fortsätter – paper-loggningen körs ALLTID
sist, eftersom det är den som gör den framåtriktade valideringen möjlig.
"""
from __future__ import annotations

import argparse
import logging
import os
from datetime import date, timedelta

from insider_tracker.config import load_config
from insider_tracker.logging_setup import setup_logging
from insider_tracker.notify.telegram import send_error

logger = logging.getLogger(__name__)

# Utan dessa gör pipelinen ingenting meningsfullt – kräv dem och FALLERA högljutt
# (tyst grön no-op ser ut som "inga signaler" men är egentligen "allt trasigt").
REQUIRED_ENV = [
    "SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY",   # persistens (Supabase REST)
    "BORSDATA_API_KEY",                             # kursdata
    "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID",       # alerts + felnotiser
]


def _require_env() -> None:
    missing = [v for v in REQUIRED_ENV if not os.getenv(v)]
    if missing:
        msg = ("Saknade miljövariabler/secrets: " + ", ".join(missing)
               + ". Lägg in dem (GitHub → Settings → Secrets, eller .env) och kör igen.")
        logger.error(msg)
        try:  # försök notifiera – funkar bara om TELEGRAM-varianterna finns
            send_error("Pipeline avbruten – saknade secrets", RuntimeError(msg))
        except Exception:  # noqa: BLE001
            pass
        raise SystemExit(2)  # icke-noll -> Actions-jobbet blir rött och syns


def _step(name: str, fn) -> bool:
    """Kör ett steg isolerat. Returnerar True vid lyckat, False vid fel."""
    logger.info("▶ Steg: %s", name)
    try:
        fn()
        logger.info("✓ Klart: %s", name)
        return True
    except Exception as exc:  # noqa: BLE001
        logger.exception("✗ Steg misslyckades: %s", name)
        send_error(f"Pipeline-steg misslyckades: {name}", exc)
        return False


def run_daily() -> dict:
    _require_env()
    cfg = load_config()
    today = date.today()
    results: dict[str, bool] = {}

    # 1. FI-ingest (delta senaste dagarna, idempotent)
    from insider_tracker.ingest.backfill import run_backfill
    results["ingest"] = _step(
        "FI-ingest (delta)",
        lambda: run_backfill(today - timedelta(days=7), today, dry_run=False))

    # 2. Kursdata (delta)
    from insider_tracker.prices.backfill_prices import run_price_backfill
    results["prices"] = _step(
        "Kursdata (delta)",
        lambda: run_price_backfill(today - timedelta(days=5), today))

    # 3. Backtest + scoring + kluster (uppdatera scores inför flaggning)
    from insider_tracker.backtest.run import run as run_backtest
    results["backtest"] = _step(
        "Backtest + scoring + kluster",
        lambda: run_backtest(True, True, True))

    # 4. Realtidsflaggning (Telegram + spara signals)
    from insider_tracker.alerts.run_alerts import run_alerts
    results["alerts"] = _step(
        "Realtidsflaggning (alerts)",
        lambda: run_alerts(cfg, dry_run=False))

    # 5. Paper-loggning – ALLTID, även om ovan strular. Detta är valideringsloggen.
    from insider_tracker.paper.tracker import sync_paper_trades
    results["paper"] = _step(
        "Paper-loggning (paper_trades)",
        lambda: sync_paper_trades(cfg))

    logger.info("Daglig pipeline klar: %s", results)
    return results


def run_weekly() -> dict:
    _require_env()
    cfg = load_config()
    results: dict[str, bool] = {}
    # Säkerställ att paper-loggen är aktuell innan rapporten.
    from insider_tracker.paper.tracker import sync_paper_trades
    results["paper"] = _step("Paper-loggning", lambda: sync_paper_trades(cfg))

    from insider_tracker.backtest.dataset import _get_repo
    from insider_tracker.paper.weekly_report import send_weekly

    def _weekly():
        repo = _get_repo(cfg)
        trades = repo.fetch_all(
            "paper_trades",
            "signal_date,isin,company,signal_type,executable,status,"
            "entry_price_theoretical,entry_price_realistic,return_realistic")
        if hasattr(repo, "close"):
            repo.close()
        send_weekly(cfg, trades, dry_run=False)

    results["weekly_report"] = _step("Veckorapport (Telegram)", _weekly)
    logger.info("Veckopipeline klar: %s", results)
    return results


def main() -> None:
    setup_logging()
    p = argparse.ArgumentParser(description="Insider-Tracker pipeline")
    p.add_argument("--daily", action="store_true", help="Kör hela dagliga pipelinen")
    p.add_argument("--weekly", action="store_true", help="Kör veckorapporten")
    args = p.parse_args()
    if not (args.daily or args.weekly):
        args.daily = True
    failed = False
    if args.daily:
        failed |= not all(run_daily().values())
    if args.weekly:
        failed |= not all(run_weekly().values())
    if failed:
        # Minst ett steg fallerade -> avsluta icke-noll så Actions-jobbet blir rött.
        raise SystemExit(1)


if __name__ == "__main__":
    main()
