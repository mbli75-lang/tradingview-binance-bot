"""Realtidsflaggning (steg 4). Körs dagligen efter ingest + backtest.

Triggrar:
  1. Nytt köp av insider med score i topp-percentilen (default topp 20 %).
  2. Klusterköp (>= N unika insiders inom fönster).
  3. Info: försäljning av insider som tidigare fått köpflagg.

Dedupe via signals-tabellen (idempotent – säker att köra om).

    python -m insider_tracker.alerts.run_alerts [--dry-run] [--lookback N]
"""
from __future__ import annotations

import argparse
import logging
import statistics
from datetime import date, timedelta

from insider_tracker.alerts.cobuy import detect_cobuys
from insider_tracker.alerts.formatting import (
    build_buy_alert,
    build_cluster_alert,
    build_cobuy_alert,
    build_sell_alert,
)
from insider_tracker.alerts.liquidity import avg_daily_turnover
from insider_tracker.backtest.dataset import _get_repo
from insider_tracker.config import Config, load_config
from insider_tracker.logging_setup import setup_logging
from insider_tracker.notify.telegram import send_error, send_message

logger = logging.getLogger(__name__)


def _percentile(values: list[float], q: float) -> float | None:
    vals = sorted(v for v in values if v is not None)
    if not vals:
        return None
    # Tröskel så att andelen (1-q) ligger på/över den (topp (1-q) %).
    idx = min(len(vals) - 1, int(q * len(vals)))
    return vals[idx]


def run_alerts(cfg: Config, dry_run: bool = False, lookback: int | None = None,
               record_only: bool = False) -> dict:
    repo = _get_repo(cfg)
    a = cfg["alerts"]
    lookback = lookback if lookback is not None else a["lookback_days"]
    cutoff = (date.today() - timedelta(days=lookback)).isoformat()
    liq_cutoff = (date.today() - timedelta(days=a["liquidity_window_days"])).isoformat()

    # --- referensdata ---
    scores = {s["insider_id"]: s for s in repo.fetch_all(
        "insider_scores", "insider_id,score,n_trades,avg_return_3m")}
    threshold = _percentile([s["score"] for s in scores.values()],
                            a["score_percentile_threshold"])
    companies = {c["isin"]: c for c in repo.fetch_all(
        "companies", "isin,name,marketplace,segment")}
    insiders = {i["id"]: i["name"] for i in repo.fetch_all("insiders", "id,name")}
    roles = {(r["insider_id"], r["company_isin"]): r.get("role")
             for r in repo.fetch_all("insider_roles", "insider_id,company_isin,role")}

    # befintliga signals (dedupe + trigger 3)
    existing = repo.fetch_all("signals", "isin,insider_id,signal_type,signal_date")
    seen = {(s["isin"], s["insider_id"], s["signal_type"], s["signal_date"])
            for s in existing}
    flagged_buys = {(s["insider_id"], s["isin"])
                    for s in existing if s["signal_type"] == "insider_buy"}

    recent = repo.fetch_all(
        "transactions",
        "id,insider_id,company_isin,type,amount_sek,is_related_party,publish_date",
        publish_date=f"gte.{cutoff}")
    clusters = repo.fetch_all(
        "clusters", "company_isin,trigger_date,window_start,n_insiders,n_buys",
        trigger_date=f"gte.{cutoff}")

    def turnover(isin: str) -> float | None:
        rows = repo.fetch_all("prices", "close,volume", isin=f"eq.{isin}",
                              date=f"gte.{liq_cutoff}")
        return avg_daily_turnover(rows)

    messages: list[str] = []
    new_signals: list[dict] = []
    stats = {"buy": 0, "cluster": 0, "cobuy": 0, "sell": 0}

    # --- Trigger 1: köp av högt scorad insider ---
    for t in recent:
        if t["type"] != "buy":
            continue
        sc = scores.get(t["insider_id"])
        if not sc or threshold is None or sc["score"] < threshold:
            continue
        # Trigga inte på symbolköp (spec: symboliska köp viktas ner; här filtreras de).
        amt = t.get("amount_sek")
        if amt is not None and float(amt) < a.get("min_amount_sek", 0):
            continue
        isin = t["company_isin"]
        key = (isin, t["insider_id"], "insider_buy", t["publish_date"][:10])
        if key in seen:
            continue
        comp = companies.get(isin, {})
        if not record_only:  # record-only behöver inte bygga meddelandet (dyr turnover)
            messages.append(build_buy_alert(cfg, {
                "company": comp.get("name") or isin, "issuer": comp.get("name"),
                "marketplace": comp.get("marketplace"), "segment": comp.get("segment"),
                "insider": insiders.get(t["insider_id"], "?"),
                "role": roles.get((t["insider_id"], isin)),
                "amount_sek": t.get("amount_sek"), "is_related_party": t.get("is_related_party"),
                "n_trades": sc["n_trades"], "avg_return_3m": sc["avg_return_3m"],
                "score": sc["score"], "turnover": turnover(isin),
                "publish_date": t["publish_date"][:10],
            }))
        new_signals.append({"signal_date": t["publish_date"][:10], "isin": isin,
                            "insider_id": t["insider_id"], "signal_type": "insider_buy",
                            "status": "open"})
        seen.add(key)
        stats["buy"] += 1

    # --- Trigger 2: klusterköp ---
    for cl in clusters:
        isin = cl["company_isin"]
        key = (isin, None, "cluster", cl["trigger_date"][:10])
        if key in seen:
            continue
        comp = companies.get(isin, {})
        if not record_only:
            messages.append(build_cluster_alert(cfg, {
                "company": comp.get("name") or isin, "issuer": comp.get("name"),
                "marketplace": comp.get("marketplace"), "segment": comp.get("segment"),
                "n_insiders": cl["n_insiders"], "n_buys": cl["n_buys"],
                "window_start": cl["window_start"][:10], "trigger_date": cl["trigger_date"][:10],
                "turnover": turnover(isin),
            }))
        new_signals.append({"signal_date": cl["trigger_date"][:10], "isin": isin,
                            "insider_id": None, "signal_type": "cluster", "status": "open"})
        seen.add(key)
        stats["cluster"] += 1

    # --- Trigger 2b: sam-köp (2+ insiders under klustertröskeln), info-nivå ---
    cluster_min = cfg["scoring"]["cluster_min_insiders"]
    cobuy_min = a["cobuy_min_insiders"]
    cobuy_win = a["cobuy_window_days"]
    wide_cut = (date.today() - timedelta(days=lookback + cobuy_win)).isoformat()
    wide_buys = repo.fetch_all(
        "transactions", "insider_id,company_isin,publish_date",
        type="eq.buy", publish_date=f"gte.{wide_cut}")
    buys_parsed = [{"company_isin": b["company_isin"], "insider_id": b["insider_id"],
                    "publish_date": date.fromisoformat(b["publish_date"][:10])}
                   for b in wide_buys]
    for cb in detect_cobuys(buys_parsed, cobuy_win, cobuy_min, cluster_min,
                            since=date.fromisoformat(cutoff)):
        isin = cb["isin"]
        trig = cb["trigger_date"].isoformat()
        key = (isin, None, "cobuy", trig)
        if key in seen:
            continue
        comp = companies.get(isin, {})
        if not record_only:
            names = [f"{insiders.get(i,'?')} – {roles.get((i,isin)) or 'okänd roll'}"
                     for i in cb["insiders"]]
            messages.append(build_cobuy_alert(cfg, {
                "company": comp.get("name") or isin, "issuer": comp.get("name"),
                "marketplace": comp.get("marketplace"), "segment": comp.get("segment"),
                "n_insiders": cb["n_insiders"], "insiders": names,
                "window_start": (cb["trigger_date"] - timedelta(days=cobuy_win)).isoformat(),
                "trigger_date": trig, "turnover": turnover(isin),
            }))
        new_signals.append({"signal_date": trig, "isin": isin, "insider_id": None,
                            "signal_type": "cobuy", "status": "info"})
        seen.add(key)
        stats["cobuy"] = stats.get("cobuy", 0) + 1

    # --- Trigger 3: försäljning av tidigare köpflaggad insider ---
    for t in recent:
        if t["type"] != "sell":
            continue
        isin = t["company_isin"]
        if (t["insider_id"], isin) not in flagged_buys:
            continue
        key = (isin, t["insider_id"], "insider_sell", t["publish_date"][:10])
        if key in seen:
            continue
        comp = companies.get(isin, {})
        if not record_only:
            messages.append(build_sell_alert(cfg, {
                "company": comp.get("name") or isin, "issuer": comp.get("name"),
                "marketplace": comp.get("marketplace"),
                "insider": insiders.get(t["insider_id"], "?"),
                "role": roles.get((t["insider_id"], isin)),
                "amount_sek": t.get("amount_sek"), "publish_date": t["publish_date"][:10],
            }))
        new_signals.append({"signal_date": t["publish_date"][:10], "isin": isin,
                            "insider_id": t["insider_id"], "signal_type": "insider_sell",
                            "status": "info"})
        seen.add(key)
        stats["sell"] += 1

    logger.info("Alerts att skicka: %s (tröskel score=%.3f)", stats, threshold or 0)

    if dry_run:
        print(f"\n[dry-run] Tröskel (topp {(1-cfg['alerts']['score_percentile_threshold'])*100:.0f}%): "
              f"score >= {threshold:.3f}" if threshold else "[dry-run] ingen tröskel")
        for m in messages:
            print("\n" + "-" * 48 + "\n" + m)
        print(f"\n[dry-run] {sum(stats.values())} alerts skulle skickas. Inget skickades/sparades.")
    elif record_only:
        # Seeda signals utan att skicka Telegram (för exit-backtest).
        repo.insert_signals(new_signals)
        logger.info("record-only: sparade %d signals (inget skickat)", len(new_signals))
    else:
        sent = 0
        for m in messages:
            if send_message(m):
                sent += 1
        repo.insert_signals(new_signals)
        logger.info("Skickade %d/%d alerts, sparade %d signals",
                    sent, len(messages), len(new_signals))

    if hasattr(repo, "close"):
        repo.close()
    return stats


def main() -> None:
    setup_logging()
    p = argparse.ArgumentParser(description="Realtidsflaggning (Telegram)")
    p.add_argument("--dry-run", action="store_true", help="Visa alerts, skicka/spara inget")
    p.add_argument("--record-only", action="store_true",
                   help="Spara signals utan att skicka Telegram (seeda exit-backtest)")
    p.add_argument("--lookback", type=int, help="Antal dagar bakåt")
    args = p.parse_args()
    try:
        run_alerts(load_config(), dry_run=args.dry_run, lookback=args.lookback,
                   record_only=args.record_only)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Alert-körning kraschade")
        send_error("Alert-körning kraschade", exc)
        raise


if __name__ == "__main__":
    main()
