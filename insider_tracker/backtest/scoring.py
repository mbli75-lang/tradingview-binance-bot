"""Scoring per insynsperson (steg 3).

Score = viktat snitt av netto-överavkastning (3 mån viktas högst), justerat för
antal trades (fler trades -> mer tillförlitligt, via shrinkage n/(n+k)).

Vikt per köp: upp för VD/CFO, belopp > 200 000 SEK; ner för närstående och
symboliska köp < 50 000 SEK. (Innehavsökning > 20 % kräver innehavsdata och är
inte aktivt än.)
"""
from __future__ import annotations

import logging
from collections import defaultdict

from insider_tracker.backtest.dataset import Dataset
from insider_tracker.config import Config

logger = logging.getLogger(__name__)


def trade_weight(cfg: Config, tr: dict, role: str | None) -> float:
    s = cfg["scoring"]
    w = 1.0
    if role:
        rl = role.lower()
        if any(k.lower() in rl for k in s["boost_roles"]):
            w *= s["role_boost"]
    amt = tr.get("amount_sek")
    if amt is not None:
        amt = float(amt)
        if amt >= s["boost_amount_sek"]:
            w *= s["amount_boost"]
        if amt < s["symbolic_amount_sek"]:
            w *= s["symbolic_penalty"]
    if tr.get("is_related_party"):
        w *= s["penalty_related_party"]
    return w


def _weighted_avg(pairs: list[tuple[float, float]]) -> float | None:
    """pairs = [(vikt, värde)]; None om ingen vikt."""
    den = sum(w for w, _ in pairs)
    if den <= 0:
        return None
    return sum(w * v for w, v in pairs) / den


def compute_scores(cfg: Config, ds: Dataset, trade_returns: list[dict]) -> list[dict]:
    s = cfg["scoring"]
    rw = s["return_weights"]
    min_trades = s["min_trades"]
    k = s["shrinkage_k"]

    by_insider: dict[int, list[dict]] = defaultdict(list)
    for tr in trade_returns:
        by_insider[tr["insider_id"]].append(tr)

    scores: list[dict] = []
    for insider_id, trs in by_insider.items():
        usable = [t for t in trs if any(
            t.get(f"exc_{lbl}") is not None for lbl in ("1m", "3m", "6m")
        )]
        if len(usable) < min_trades:
            continue

        avgs: dict[str, float | None] = {}
        for lbl in ("1m", "3m", "6m"):
            pairs = []
            for t in usable:
                exc = t.get(f"exc_{lbl}")
                if exc is None:
                    continue
                role = ds.roles.get((insider_id, t["company_isin"]))
                pairs.append((trade_weight(cfg, t, role), exc))
            avgs[lbl] = _weighted_avg(pairs)

        parts = [
            (rw["m1"], avgs["1m"]), (rw["m3"], avgs["3m"]), (rw["m6"], avgs["6m"]),
        ]
        wsum = sum(w for w, a in parts if a is not None)
        if wsum <= 0:
            continue
        combined = sum(w * a for w, a in parts if a is not None) / wsum

        n = len(usable)
        score = combined * n / (n + k)  # antal-trades-justering

        scores.append({
            "insider_id": insider_id,
            "company_isin": None,          # per-insider totalscore
            "score": score,
            "n_trades": n,
            "avg_return_1m": avgs["1m"],
            "avg_return_3m": avgs["3m"],
            "avg_return_6m": avgs["6m"],
        })

    logger.info("Scores beräknade för %d insiders (min %d köp)", len(scores), min_trades)
    return scores
