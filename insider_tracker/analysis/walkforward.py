"""Walk-forward (out-of-sample) utvärdering.

Kärnprincip: scoringen får ALDRIG se data från perioden den utvärderas på. För
varje testkvartal beräknas insider-scores enbart på trades vars UTFALL var känt
FÖRE kvartalets start; de scorerna appliceras på signaler som uppstår UNDER
kvartalet, och utfallet mäts framåt.

Realistiskt: entry = nästa handelsdags öppning efter publiceringsdatum, exit =
close +21/+63/+126 handelsdagar, överavkastning mot OMXSPI, slippage per
marknadsplats, survivorship (avnoterat -> sista kurs). Likviditet rapporteras
med och utan kap (exekverbara vs illikvida).

    python -m insider_tracker.analysis.walkforward
"""
from __future__ import annotations

import bisect
import csv
import logging
import statistics
from collections import defaultdict
from datetime import date

from insider_tracker.backtest.dataset import _get_repo
from insider_tracker.backtest.returns import price_asof
from insider_tracker.backtest.scoring import trade_weight
from insider_tracker.backtest.slippage import resolve_slippage
from insider_tracker.config import load_config
from insider_tracker.logging_setup import setup_logging
from insider_tracker.paper.data import load_ohlc

logger = logging.getLogger(__name__)

HORIZONS = [("1m", 21), ("3m", 63), ("6m", 126)]
OUTDIR = "analysis_results"


def _d(s: str) -> date:
    return date.fromisoformat(s[:10])


def _quarter_start(d: date) -> date:
    return date(d.year, 3 * ((d.month - 1) // 3) + 1, 1)


def _next_quarter(d: date) -> date:
    return date(d.year + 1, 1, 1) if d.month >= 10 else date(d.year, d.month + 3, 1)


def build_trade_returns(cfg, ohlc, bench, buys, segments, marketplaces):
    """Per köp: entry (nästa dags öppning), turnover, och exc_net/exit_date per horisont."""
    cal = ohlc.calendar
    bankrupt = set(cfg["backtest"].get("bankruptcy_isins", []) or [])
    trades = []
    for b in buys:
        isin = b["company_isin"]
        series = ohlc.close_series(isin)
        if not series:
            continue
        pub = _d(b["publish_date"])
        entry = ohlc.open_asof_next(isin, pub)   # nästa handelsdags öppning
        if entry is None:
            continue
        entry_date, entry_open = entry
        if entry_open <= 0:
            continue
        i0 = bisect.bisect_left(cal, entry_date)
        seg = segments.get(isin)
        mkt = b.get("marketplace") or marketplaces.get(isin)
        slip = resolve_slippage(cfg, mkt, seg)
        turnover = ohlc.turnover_30d(isin, pub)  # point-in-time
        is_bankrupt = isin in bankrupt

        tr = {
            "insider_id": b["insider_id"], "isin": isin, "publish_date": pub,
            "entry_date": entry_date, "segment": seg, "marketplace": mkt,
            "amount_sek": b.get("amount_sek"), "is_related_party": b.get("is_related_party"),
            "turnover": turnover, "slippage": slip,
        }
        b_entry = price_asof(bench, entry_date)
        last_stock = series[-1][0]
        for lbl, h in HORIZONS:
            j = i0 + h
            reached = j < len(cal)
            exit_cd = cal[j] if reached else cal[-1]
            s_exit = price_asof(series, exit_cd)
            b_exit = price_asof(bench, exit_cd)
            exc = exit_dt = None
            if s_exit and b_entry and b_exit and b_entry[1] > 0:
                if is_bankrupt:
                    stock_ret = -1.0
                else:
                    stock_ret = s_exit[1] / entry_open - 1.0
                bench_ret = b_exit[1] / b_entry[1] - 1.0
                exc = stock_ret - bench_ret - slip     # netto överavkastning
                # exit_date känt endast om horisonten faktiskt nåtts i handeln
                if reached and (is_bankrupt or last_stock >= exit_cd):
                    exit_dt = exit_cd
                elif reached and last_stock < exit_cd:
                    exit_dt = last_stock  # avnoterat -> sista kurs; utfall känt vid avnotering
            tr[f"exc_{lbl}"] = exc
            tr[f"exit_{lbl}"] = exit_dt
        trades.append(tr)
    return trades


def score_asof(trades, T0, roles, cfg):
    """Insider-scores med ENBART utfall känt före T0 (point-in-time)."""
    s = cfg["scoring"]
    rw = s["return_weights"]
    wmap = {"1m": rw["m1"], "3m": rw["m3"], "6m": rw["m6"]}
    by_ins = defaultdict(list)
    for tr in trades:
        if tr["publish_date"] >= T0:
            continue
        obs = []
        for lbl in ("1m", "3m", "6m"):
            exc, ex = tr.get(f"exc_{lbl}"), tr.get(f"exit_{lbl}")
            if exc is not None and ex is not None and ex < T0:
                obs.append((wmap[lbl], exc))
        if not obs:
            continue
        combined = sum(w * e for w, e in obs) / sum(w for w, _ in obs)
        role = roles.get((tr["insider_id"], tr["isin"]))
        by_ins[tr["insider_id"]].append((trade_weight(cfg, tr, role), combined))
    scores = {}
    k = s["shrinkage_k"]
    for ins, lst in by_ins.items():
        if len(lst) < s["min_trades"]:
            continue
        den = sum(w for w, _ in lst)
        combined = sum(w * c for w, c in lst) / den if den else 0.0
        n = len(lst)
        scores[ins] = combined * n / (n + k)
    return scores


def _pct(vals, q):
    v = sorted(x for x in vals if x is not None)
    return v[min(len(v) - 1, int(q * len(v)))] if v else None


def cluster_flags(buys):
    """Point-in-time: köp där >=3 unika insiders köpt isin inom trailing 14 dagar."""
    from datetime import timedelta
    by_isin = defaultdict(list)
    for b in buys:
        by_isin[b["company_isin"]].append((_d(b["publish_date"]), b["insider_id"], id(b)))
    flag = {}
    for isin, evts in by_isin.items():
        evts.sort()
        for dt, _ins, bid in evts:
            lo = dt - timedelta(days=14)
            uniq = {i for d, i, _ in evts if lo <= d <= dt}
            flag[bid] = len(uniq) >= 3
    return flag


def summarize(rows, label):
    """rows: lista av (exc_3m, executable). Returnerar statistik-dict."""
    def stat(subset):
        v = [e for e, _ in subset if e is not None]
        if not v:
            return None
        return {"n": len(v), "median": statistics.median(v),
                "mean": statistics.mean(v),
                "win": sum(1 for x in v if x > 0) / len(v)}
    return {
        "alla": stat(rows),
        "exekverbara": stat([r for r in rows if r[1]]),
        "illikvida": stat([r for r in rows if not r[1]]),
        "label": label,
    }


def run(cfg) -> dict:
    import os
    repo = _get_repo(cfg)
    logger.info("Laddar OHLCV …")
    ohlc = load_ohlc(cfg, repo)
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
    if hasattr(repo, "close"):
        repo.close()

    logger.info("Beräknar per-trade-utfall (nästa-dags-öppning entry) …")
    trades = build_trade_returns(cfg, ohlc, bench, buys, segments, marketplaces)
    liq_warn = cfg["alerts"]["liquidity_warning_sek_per_day"]
    cl_flag = cluster_flags(buys)
    # koppla klusterflagga till trades via (isin, publish, insider) – räkna om enkelt
    from datetime import timedelta
    by_isin_dates = defaultdict(list)
    for tr in trades:
        by_isin_dates[tr["isin"]].append((tr["publish_date"], tr["insider_id"]))

    def is_cluster(tr):
        lo = tr["publish_date"] - timedelta(days=14)
        uniq = {i for d, i in by_isin_dates[tr["isin"]] if lo <= d <= tr["publish_date"]}
        return len(uniq) >= 3

    dates = [tr["publish_date"] for tr in trades]
    first_test = _next_quarter(_quarter_start(min(dates)))  # behöver historik innan test
    # hoppa fram tills det finns tillräckligt tränings-underlag: kräv 2 kvartal
    first_test = _next_quarter(first_test)
    last = max(dates)

    wf = {"baseline": [], "top": [], "cluster": []}   # (exc_3m, executable)
    wf_detail = []
    per_quarter = []
    threshold_used = None
    T0 = first_test
    while T0 <= last:
        T1 = _next_quarter(T0)
        scores = score_asof(trades, T0, roles, cfg)
        thr = _pct(list(scores.values()), cfg["alerts"]["score_percentile_threshold"])
        threshold_used = thr
        qtrades = [tr for tr in trades if T0 <= tr["publish_date"] < T1
                   and tr.get("exc_3m") is not None]
        nb = nt = nc = 0
        for tr in qtrades:
            exe = tr["turnover"] is not None and tr["turnover"] >= liq_warn
            rec = (tr["exc_3m"], exe)
            wf["baseline"].append(rec); nb += 1
            sc = scores.get(tr["insider_id"])
            is_top = sc is not None and thr is not None and sc >= thr
            if is_top:
                wf["top"].append(rec); nt += 1
            is_cl = is_cluster(tr)
            if is_cl:
                wf["cluster"].append(rec); nc += 1
            wf_detail.append({
                "quarter": f"{T0:%Y-Q}{(T0.month-1)//3+1}", "isin": tr["isin"],
                "insider_id": tr["insider_id"], "entry_date": tr["entry_date"].isoformat(),
                "segment": tr["segment"], "executable": int(exe),
                "score": round(sc, 4) if sc is not None else "",
                "top_scored": int(is_top), "cluster": int(is_cl),
                "exc_1m": tr.get("exc_1m"), "exc_3m": tr.get("exc_3m"), "exc_6m": tr.get("exc_6m"),
            })
        per_quarter.append({"quarter": f"{T0:%Y}Q{(T0.month-1)//3+1}",
                            "baseline": nb, "top": nt, "cluster": nc,
                            "threshold": round(thr, 4) if thr else None})
        T0 = T1

    # In-sample-referens: score på HELA historiken, applicerad på alla köp.
    full_scores = score_asof(trades, date(2100, 1, 1), roles, cfg)
    full_thr = _pct(list(full_scores.values()), cfg["alerts"]["score_percentile_threshold"])
    insample = {"baseline": [], "top": [], "cluster": []}
    for tr in trades:
        if tr.get("exc_3m") is None:
            continue
        exe = tr["turnover"] is not None and tr["turnover"] >= liq_warn
        rec = (tr["exc_3m"], exe)
        insample["baseline"].append(rec)
        sc = full_scores.get(tr["insider_id"])
        if sc is not None and full_thr is not None and sc >= full_thr:
            insample["top"].append(rec)
        if is_cluster(tr):
            insample["cluster"].append(rec)

    result = {
        "walkforward": {k: summarize(v, k) for k, v in wf.items()},
        "insample": {k: summarize(v, k) for k, v in insample.items()},
        "per_quarter": per_quarter,
        "threshold_last": threshold_used,
    }

    # --- spara detaljer ---
    os.makedirs(OUTDIR, exist_ok=True)
    with open(f"{OUTDIR}/walkforward_signals.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(wf_detail[0].keys()))
        w.writeheader(); w.writerows(wf_detail)
    with open(f"{OUTDIR}/walkforward_per_quarter.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(per_quarter[0].keys()))
        w.writeheader(); w.writerows(per_quarter)

    _print_report(cfg, result)
    _save_summary(result)
    return result


def _fmt(s):
    if s is None:
        return "   —   "
    return f"{s['median']:+.1%}/{s['mean']:+.1%} {s['win']:.0%} n={s['n']}"


def _print_report(cfg, res):
    print("\n" + "=" * 92)
    print("WALK-FORWARD (out-of-sample) vs IN-SAMPLE — netto-överavkastning 3 mån (median/snitt, träff, n)")
    print("=" * 92)
    for strat in ("baseline", "top", "cluster"):
        name = {"baseline": "Alla köp", "top": "Topp-scorade", "cluster": "Kluster"}[strat]
        wf = res["walkforward"][strat]; ins = res["insample"][strat]
        print(f"\n{name}:")
        for grp in ("alla", "exekverbara", "illikvida"):
            print(f"  {grp:12} WF: {_fmt(wf[grp]):30}  IN-SAMPLE: {_fmt(ins[grp])}")
    print("\nPer kvartal (n topp-scorade – flaggar tunna fönster < 20):")
    for q in res["per_quarter"]:
        thin = " ⚠️TUNT" if q["top"] < 20 else ""
        print(f"  {q['quarter']}  baseline={q['baseline']:4}  topp={q['top']:4}  "
              f"kluster={q['cluster']:4}  tröskel={q['threshold']}{thin}")
    print("=" * 92)


def _save_summary(res):
    import json
    with open(f"{OUTDIR}/walkforward_summary.json", "w") as f:
        json.dump(res, f, indent=2, default=str)


def main():
    setup_logging()
    run(load_config())


if __name__ == "__main__":
    main()

