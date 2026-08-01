"""Sam-köp-detektion (info-nivå): 2+ unika insiders köper i samma bolag inom ett
rullande fönster, men UNDER klustertröskeln (≥3). Håller "kluster" = ≥3 orört så
den backtestade signalen inte späds ut.

Ren funktion -> testbar.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta


def detect_cobuys(
    buys: list[dict], window_days: int, cobuy_min: int, cluster_min: int, since: date,
) -> list[dict]:
    """Hitta bolag med ett nytt köp (publ >= since) där antalet unika insiders inom
    [trigger - window, trigger] ligger i [cobuy_min, cluster_min - 1].

    buys: [{company_isin, insider_id, publish_date(date)}] (godtycklig ordning).
    Returnerar [{isin, trigger_date, n_insiders, insiders}] – en per bolag.
    """
    by_isin: dict[str, list[tuple[date, int]]] = defaultdict(list)
    for b in buys:
        by_isin[b["company_isin"]].append((b["publish_date"], b["insider_id"]))

    out: list[dict] = []
    for isin, evts in by_isin.items():
        evts.sort()
        # Senaste köpet som är "nytt" (publ >= since) är trigger.
        new_dates = [d for d, _ in evts if d >= since]
        if not new_dates:
            continue
        trigger = max(new_dates)
        lo = trigger - timedelta(days=window_days)
        insiders = {i for d, i in evts if lo <= d <= trigger}
        if cobuy_min <= len(insiders) < cluster_min:
            out.append({
                "isin": isin, "trigger_date": trigger,
                "n_insiders": len(insiders), "insiders": insiders,
            })
    return out
