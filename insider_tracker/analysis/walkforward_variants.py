"""Föranmäld slutlig walk-forward: fyra strukturella varianter + insider-exit.

Regler satta FÖRE resultat: inga tunade trösklar, exakt dessa varianter, alla
rapporteras. Ribba (förbestämd): en variant KLARAR endast om median-överavkastning
mot OMXSPI är > 0 out-of-sample, på EXEKVERBARA signaler, med stabilt n/kvartal.

    python -m insider_tracker.analysis.walkforward_variants
"""
from __future__ import annotations

import bisect
import csv
import json
import logging
import os
import statistics
from collections import defaultdict
from datetime import date, timedelta

from insider_tracker.analysis.walkforward import (
    _d, _next_quarter, _pct, _quarter_start, build_trade_returns, score_asof,
)
from insider_tracker.backtest.dataset import _get_repo
from insider_tracker.backtest.returns import price_asof
from insider_tracker.backtest.slippage import resolve_slippage
from insider_tracker.config import load_config
from insider_tracker.logging_setup import setup_logging
from insider_tracker.paper.data import load_ohlc

logger = logging.getLogger(__name__)
OUTDIR = "analysis_results"


def _stat(recs):
    """recs: [(exc, executable)]. -> dict per grupp med median/mean/win/n."""
    def s(sub):
        v = [e for e, _ in sub if e is not None]
        if not v:
            return None
        return {"n": len(v), "median": statistics.median(v),
                "mean": statistics.mean(v), "win": sum(1 for x in v if x > 0) / len(v)}
    return {"exekverbara": s([r for r in recs if r[1]]),
            "illikvida": s([r for r in recs if not r[1]]),
            "alla": s(recs)}


def run(cfg) -> dict:
    repo = _get_repo(cfg)
    logger.info("Laddar data …")
    ohlc = load_ohlc(cfg, repo)
    cal = ohlc.calendar
    bench_isin = cfg["backtest"]["benchmark_isin"]
    bench = sorted((_d(r["date"]), float(r["close"])) for r in
                   repo.fetch_all("prices", "date,close", isin=f"eq.{bench_isin}")
                   if r.get("close") is not None)
    buys = repo.fetch_all(
        "transactions",
        "insider_id,company_isin,publish_date,marketplace,amount_sek,is_related_party",
        type="eq.buy", order="publish_date.asc")
    roles = {(r["insider_id"], r["company_isin"]): r.get("role")
             for r in repo.fetch_all("insider_roles", "insider_id,company_isin,role")}
    comp = repo.fetch_all("companies", "isin,segment,marketplace")
    segments = {c["isin"]: c.get("segment") for c in comp}
    marketplaces = {c["isin"]: c.get("marketplace") for c in comp}
    sells = defaultdict(list)
    for t in repo.fetch_all("transactions", "insider_id,company_isin,publish_date",
                            type="eq.sell"):
        sells[(t["insider_id"], t["company_isin"])].append(_d(t["publish_date"]))
    for k in sells:
        sells[k].sort()
    if hasattr(repo, "close"):
        repo.close()

    trades = build_trade_returns(cfg, ohlc, bench, buys, segments, marketplaces)
    liq = cfg["alerts"]["liquidity_warning_sek_per_day"]
    vdcfo = [r.lower() for r in cfg["scoring"]["boost_roles"]]
    big = cfg["scoring"]["boost_amount_sek"]

    # index per isin för kluster-räkning (point-in-time)
    by_isin = defaultdict(list)
    for tr in trades:
        by_isin[tr["isin"]].append((tr["publish_date"], tr["insider_id"]))

    def unique_insiders(isin, d, win=14):
        lo = d - timedelta(days=win)
        return len({i for dd, i in by_isin[isin] if lo <= dd <= d})

    def is_vdcfo(tr):
        role = (roles.get((tr["insider_id"], tr["isin"])) or "").lower()
        return any(k in role for k in vdcfo)

    def executable(tr):
        return tr["turnover"] is not None and tr["turnover"] >= liq

    def insider_exit_excess(tr):
        """Variant 4: realiserad överavkastning köp -> insiderns faktiska sälj."""
        future = [d for d in sells.get((tr["insider_id"], tr["isin"]), [])
                  if d > tr["publish_date"]]
        if not future:
            return None  # ingen faktisk försäljning -> öppen, exkluderas
        sell_d = future[0]
        series = ohlc.close_series(tr["isin"])
        i = bisect.bisect_left(cal, sell_d)
        if i >= len(cal):
            return None
        exit_cd = cal[i]
        s_exit = price_asof(series, exit_cd)
        b_entry = price_asof(bench, tr["entry_date"])
        b_exit = price_asof(bench, exit_cd)
        # entry_open sparades inte; approximera med close på entry_date? Nej – använd
        # samma entry som trade-beräkningen: öppning nästa dag efter publ.
        entry = ohlc.open_asof_next(tr["isin"], tr["publish_date"])
        if not (s_exit and b_entry and b_exit and entry and entry[1] > 0 and b_entry[1] > 0):
            return None
        stock = s_exit[1] / entry[1] - 1.0
        bmk = b_exit[1] / b_entry[1] - 1.0
        return stock - bmk - tr["slippage"]

    dates = [tr["publish_date"] for tr in trades]
    T0 = _next_quarter(_next_quarter(_quarter_start(min(dates))))
    last = max(dates)

    # ackumulatorer: variant -> {'wf':[recs], 'is':[recs], 'q':{quarter:n_exec}}
    V = {v: {"wf": [], "is": [], "q": defaultdict(int)}
         for v in ("vdcfo", "big_proxy", "cluster4", "insider_exit")}

    # in-sample scores (för insider_exit-urvalet in-sample)
    full_scores = score_asof(trades, date(2100, 1, 1), roles, cfg)
    full_thr = _pct(list(full_scores.values()), cfg["alerts"]["score_percentile_threshold"])

    while T0 <= last:
        T1 = _next_quarter(T0)
        qlabel = f"{T0:%Y}Q{(T0.month-1)//3+1}"
        scores = score_asof(trades, T0, roles, cfg)
        thr = _pct(list(scores.values()), cfg["alerts"]["score_percentile_threshold"])
        qtrades = [tr for tr in trades if T0 <= tr["publish_date"] < T1]

        for tr in qtrades:
            exe = executable(tr)
            e3 = tr.get("exc_3m")
            # V1 VD/CFO
            if is_vdcfo(tr) and e3 is not None:
                V["vdcfo"]["wf"].append((e3, exe))
                if exe:
                    V["vdcfo"]["q"][qlabel] += 1
            # V2 proxy: absolut stort köp (>= boost_amount_sek)
            amt = tr.get("amount_sek")
            if amt is not None and float(amt) >= big and e3 is not None:
                V["big_proxy"]["wf"].append((e3, exe))
                if exe:
                    V["big_proxy"]["q"][qlabel] += 1
            # V3 täta kluster 4+
            if unique_insiders(tr["isin"], tr["publish_date"]) >= 4 and e3 is not None:
                V["cluster4"]["wf"].append((e3, exe))
                if exe:
                    V["cluster4"]["q"][qlabel] += 1
            # V4 insider-exit på topp-scorade (as-of) köp, endast stängda par
            sc = scores.get(tr["insider_id"])
            if sc is not None and thr is not None and sc >= thr:
                ex = insider_exit_excess(tr)
                if ex is not None:
                    V["insider_exit"]["wf"].append((ex, exe))
                    if exe:
                        V["insider_exit"]["q"][qlabel] += 1
        T0 = T1

    # In-sample-motsvarighet (strukturella = identiska; insider_exit använder full-scores)
    for tr in trades:
        exe = executable(tr); e3 = tr.get("exc_3m")
        if is_vdcfo(tr) and e3 is not None:
            V["vdcfo"]["is"].append((e3, exe))
        amt = tr.get("amount_sek")
        if amt is not None and float(amt) >= big and e3 is not None:
            V["big_proxy"]["is"].append((e3, exe))
        if unique_insiders(tr["isin"], tr["publish_date"]) >= 4 and e3 is not None:
            V["cluster4"]["is"].append((e3, exe))
        sc = full_scores.get(tr["insider_id"])
        if sc is not None and full_thr is not None and sc >= full_thr:
            ex = insider_exit_excess(tr)
            if ex is not None:
                V["insider_exit"]["is"].append((ex, exe))

    result = {v: {"wf": _stat(d["wf"]), "is": _stat(d["is"]),
                  "per_quarter_exec": dict(sorted(d["q"].items()))}
              for v, d in V.items()}
    os.makedirs(OUTDIR, exist_ok=True)
    with open(f"{OUTDIR}/walkforward_variants.json", "w") as f:
        json.dump(result, f, indent=2, default=str)
    _report(result)
    return result


def _f(s):
    return "     —      " if s is None else f"{s['median']:+.1%}/{s['mean']:+.1%} {s['win']:.0%} n={s['n']}"


def _report(res):
    names = {"vdcfo": "1. Enbart VD/CFO-köp",
             "big_proxy": "2. Stora köp (PROXY abs ≥200k – förmögenhetsdata saknas)",
             "cluster4": "3. Täta kluster (4+ insiders)",
             "insider_exit": "4. Insider-exit (topp-scorade, endast stängda par)"}
    print("\n" + "=" * 96)
    print("FÖRANMÄLD SLUT-WALK-FORWARD — netto-överavkastning vs OMXSPI (median/snitt, träff, n)")
    print("Ribba: median > 0 OUT-OF-SAMPLE på EXEKVERBARA + stabilt n/kvartal")
    print("=" * 96)
    for v in ("vdcfo", "big_proxy", "cluster4", "insider_exit"):
        r = res[v]
        print(f"\n{names[v]}")
        for grp in ("exekverbara", "illikvida"):
            print(f"    {grp:12} WF: {_f(r['wf'][grp]):30} IN-SAMPLE: {_f(r['is'][grp])}")
        q = r["per_quarter_exec"]
        thin = sum(1 for n in q.values() if n < 20)
        wf_exec = r["wf"]["exekverbara"]
        passed = (wf_exec and wf_exec["median"] > 0)
        print(f"    exek n/kvartal: {list(q.values())}  "
              f"({'STABILT' if thin==0 and q else f'{thin} tunna fönster'})")
        print(f"    RIBBA (median>0 OOS exek): {'✅ KLARAR' if passed else '❌ klarar ej'}")
    print("=" * 96)


def main():
    setup_logging()
    run(load_config())


if __name__ == "__main__":
    main()
