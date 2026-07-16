"""Kör backtest + scoring + klusterdetektion och lagrar resultaten.

    python -m insider_tracker.backtest.run              # allt
    python -m insider_tracker.backtest.run --returns    # bara avkastning
    python -m insider_tracker.backtest.run --scores     # bara scoring (kräver returns)
    python -m insider_tracker.backtest.run --clusters   # bara kluster
"""
from __future__ import annotations

import argparse
import logging
import statistics

from insider_tracker.backtest.clusters import backtest_clusters, detect_clusters
from insider_tracker.backtest.dataset import _get_repo, load_dataset
from insider_tracker.backtest.engine import compute_trade_returns
from insider_tracker.backtest.scoring import compute_scores
from insider_tracker.config import load_config
from insider_tracker.logging_setup import setup_logging
from insider_tracker.notify.telegram import send_error

logger = logging.getLogger(__name__)


def _summary(label: str, values: list[float]) -> str:
    vals = [v for v in values if v is not None]
    if not vals:
        return f"  {label}: (inga)"
    return (f"  {label}: n={len(vals)} snitt={statistics.mean(vals):+.1%} "
            f"median={statistics.median(vals):+.1%} "
            f"andel>0={sum(1 for v in vals if v > 0)/len(vals):.0%}")


def run(do_returns=True, do_scores=True, do_clusters=True) -> dict:
    cfg = load_config()
    ds = load_dataset(cfg)
    repo = _get_repo(cfg)
    result = {}

    trade_rows: list[dict] = []
    if do_returns or do_scores:
        trade_rows, stats = compute_trade_returns(cfg, ds)
        result["returns"] = stats
        if do_returns:
            repo.upsert_trade_returns(trade_rows)
            logger.info("Lagrade %d trade_returns", len(trade_rows))
            print("\n=== ÖVERAVKASTNING (netto, alla köp) ===")
            for lbl in ("1m", "3m", "6m"):
                print(_summary(f"exc_{lbl}", [r.get(f"exc_{lbl}") for r in trade_rows]))

    if do_scores:
        scores = compute_scores(cfg, ds, trade_rows)
        repo.replace_scores(scores)
        result["scores"] = len(scores)
        top = sorted(scores, key=lambda s: s["score"], reverse=True)[:10]
        print(f"\n=== TOPP 10 INSIDERS (av {len(scores)} scorade, min "
              f"{cfg['scoring']['min_trades']} köp) ===")
        id_to_name = {}
        for name_row in repo.fetch_all("insiders", "id,name"):
            id_to_name[name_row["id"]] = name_row["name"]
        for s in top:
            print(f"  {id_to_name.get(s['insider_id'], s['insider_id']):32.32} "
                  f"score={s['score']:+.3f} n={s['n_trades']} "
                  f"3m={s['avg_return_3m'] if s['avg_return_3m'] is None else format(s['avg_return_3m'],'+.1%')}")

    if do_clusters:
        clusters = detect_clusters(cfg, ds)
        clusters = backtest_clusters(cfg, ds, clusters)
        repo.upsert_clusters(clusters)
        result["clusters"] = len(clusters)
        print(f"\n=== KLUSTERSIGNAL ({len(clusters)} kluster) – egen statistik ===")
        for lbl in ("1m", "3m", "6m"):
            print(_summary(f"kluster exc_{lbl}", [c.get(f"exc_{lbl}") for c in clusters]))

    if hasattr(repo, "close"):
        repo.close()
    logger.info("Backtest klart: %s", result)
    return result


def main() -> None:
    setup_logging()
    p = argparse.ArgumentParser(description="Backtest + scoring + kluster")
    p.add_argument("--returns", action="store_true")
    p.add_argument("--scores", action="store_true")
    p.add_argument("--clusters", action="store_true")
    args = p.parse_args()
    # Om ingen flagga angavs: kör allt.
    if not (args.returns or args.scores or args.clusters):
        args.returns = args.scores = args.clusters = True
    try:
        run(args.returns, args.scores, args.clusters)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Backtest kraschade")
        send_error("Backtest kraschade", exc)
        raise


if __name__ == "__main__":
    main()
