"""Conviction-sizing: tänkt positionsstorlek per signal (rent teoretiskt).

Skalar positionen med övertygelse (insider-score, eller kluster-boost) och kapar
mot likviditeten (position <= X % av snittomsättning/dag). Rena funktioner -> testbara.
"""
from __future__ import annotations

from dataclasses import dataclass

from insider_tracker.config import Config


@dataclass
class Position:
    conviction_mult: float
    pct: float          # andel av teoretisk portfölj (efter likviditetskap)
    sek: float          # absolut belopp


def conviction_multiplier(
    cfg: Config, score: float | None, is_cluster: bool,
    score_lo: float, score_hi: float,
) -> float:
    s = cfg["sizing"]
    if is_cluster:
        return float(s["cluster_mult"])
    lo, hi = float(s["min_conviction_mult"]), float(s["max_conviction_mult"])
    if score is None:
        return lo
    if score_hi <= score_lo:
        return 1.0
    frac = (score - score_lo) / (score_hi - score_lo)
    frac = max(0.0, min(1.0, frac))  # klamra flaggade in i [0,1]
    return lo + frac * (hi - lo)


def intended_position(
    cfg: Config, score: float | None, is_cluster: bool,
    turnover: float | None, score_lo: float, score_hi: float,
) -> Position:
    s = cfg["sizing"]
    mult = conviction_multiplier(cfg, score, is_cluster, score_lo, score_hi)
    pct_uncapped = min(s["base_position_pct"] * mult, s["max_position_pct"])
    sek = s["portfolio_sek"] * pct_uncapped
    # Likviditetskap: positionen får inte överstiga X % av daglig omsättning.
    if turnover is not None:
        sek = min(sek, s["max_pct_of_adv"] * turnover)
    pct = sek / s["portfolio_sek"] if s["portfolio_sek"] else 0.0
    return Position(conviction_mult=round(mult, 4),
                    pct=round(pct, 6), sek=round(sek, 2))
