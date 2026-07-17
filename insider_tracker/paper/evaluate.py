"""Utvärdering: jämför paper trading (live/OOS) mot backtest (in-sample).

Körs manuellt efter 3 och 6 mån. Leder med MEDIAN (snittet ljuger i smallcaps),
delar upp på exekverbara vs illikvida, och mäter exekveringskostnaden
(teoretiskt vs realistiskt entry) – det backtesten inte kan mäta.
"""
from __future__ import annotations

import statistics

from insider_tracker.backtest.dataset import _get_repo
from insider_tracker.config import Config


def _med(xs):
    xs = [x for x in xs if x is not None]
    return statistics.median(xs) if xs else None


def _fmt(x):
    return "  n/a  " if x is None else f"{x:+6.1%}"


def _group_stats(trades: list[dict]) -> dict:
    closed = [t for t in trades if t.get("status") == "closed"]
    real = [t.get("return_realistic") for t in closed]
    theo = [t.get("return_theoretical") for t in closed]
    real_v = [x for x in real if x is not None]
    med_real = _med(real)
    med_theo = _med(theo)
    exec_cost = (med_theo - med_real) if (med_theo is not None and med_real is not None) else None
    return {
        "n": len(trades), "closed": len(closed),
        "median_real": med_real, "median_theo": med_theo,
        "exec_cost": exec_cost,
        "win_rate": (sum(1 for v in real_v if v > 0) / len(real_v)) if real_v else None,
    }


def evaluate(cfg: Config) -> str:
    repo = _get_repo(cfg)
    trades = repo.fetch_all(
        "paper_trades",
        "status,executable,signal_type,return_realistic,return_theoretical")
    # Backtest-referens (in-sample): median 3-mån gross stock return för köp.
    tr = repo.fetch_all("trade_returns", "ret_3m", exc_3m="not.is.null")
    if hasattr(repo, "close"):
        repo.close()
    bt_median = _med([t.get("ret_3m") for t in tr])

    def line(label, rows):
        s = _group_stats(rows)
        wr = "n/a" if s["win_rate"] is None else f"{s['win_rate']:.0%}"
        return (f"  {label:24} n={s['n']:4} stängda={s['closed']:4}  "
                f"median(real)={_fmt(s['median_real'])}  "
                f"median(teo)={_fmt(s['median_theo'])}  "
                f"exek.kostn={_fmt(s['exec_cost'])}  träff={wr}")

    execu = [t for t in trades if t.get("executable")]
    illiq = [t for t in trades if not t.get("executable")]
    buys = [t for t in trades if t.get("signal_type") == "insider_buy"]
    clus = [t for t in trades if t.get("signal_type") == "cluster"]

    out = [
        "=" * 100,
        "PAPER TRADING-UTVÄRDERING (live/out-of-sample vs backtest/in-sample)",
        "=" * 100,
        f"Backtest-referens (in-sample) median 3-mån gross: {_fmt(bt_median)}",
        "",
        "Live (paper), median leder – snittet ljuger i smallcaps:",
        line("ALLA", trades),
        line("  exekverbara", execu),
        line("  illikvida", illiq),
        line("  signaltyp: köp", buys),
        line("  signaltyp: kluster", clus),
        "",
        "Beslutsregel:",
        "  • Live-median (exekverbara) inom ~30% av backtest → systemet håller.",
        "  • Live kraftigt under / bara illikvida presterar → slippage-artefakt, kalibrera om.",
        "  • För få stängda för att avgöra → fortsätt logga, ta inget beslut.",
        "",
        "OBS: seedade signaler är fortfarande in-sample. Genuint OOS-underlag ackumuleras",
        "framåt i tiden – kör om detta efter 3 och 6 mån av live-körning.",
        "=" * 100,
    ]
    return "\n".join(out)
