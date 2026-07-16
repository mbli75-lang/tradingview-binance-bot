"""Månadsrapport (steg 5): jämför hypotetisk avkastning per exit-regel via Telegram."""
from __future__ import annotations

import logging
import statistics
from collections import defaultdict
from datetime import date

from insider_tracker.config import Config
from insider_tracker.notify.telegram import send_message

logger = logging.getLogger(__name__)

_RULE_LABELS = {
    "insider_sell": "(a) Sälj när insider säljer",
    "hold_3m": "(b) Fast 3-mån hold",
    "trailing_15": "(c) Trailing stop 15 %",
}


def _pct(x: float | None) -> str:
    return "n/a" if x is None else f"{x:+.1%}"


def build_report(cfg: Config, exits: list[dict]) -> str:
    by_rule: dict[str, list[dict]] = defaultdict(list)
    for e in exits:
        by_rule[e["rule"]].append(e)

    n_signals = len(exits) // 3 if exits else 0
    lines = [
        f"📅 <b>Månadsrapport – Insider-Tracker</b> ({date.today():%Y-%m})",
        f"Flaggade köp som spåras: <b>{n_signals}</b>",
        "",
        "<b>Hypotetisk avkastning per exit-regel</b> (netto, efter slippage):",
    ]
    for rule in ("insider_sell", "hold_3m", "trailing_15"):
        rows = by_rule.get(rule, [])
        nets = [r["net_return"] for r in rows if r.get("net_return") is not None]
        closed = sum(1 for r in rows if r.get("status") == "closed")
        if not nets:
            lines.append(f"{_RULE_LABELS[rule]}: <i>inga data</i>")
            continue
        mean = statistics.mean(nets)
        median = statistics.median(nets)
        win = sum(1 for v in nets if v > 0) / len(nets)
        lines.append(
            f"{_RULE_LABELS[rule]}\n"
            f"   snitt {_pct(mean)} · median {_pct(median)} · "
            f"träff {win:.0%} · n={len(nets)} ({closed} stängda)"
        )
    # Vilken regel vann på snitt?
    means = {}
    for rule in ("insider_sell", "hold_3m", "trailing_15"):
        nets = [r["net_return"] for r in by_rule.get(rule, []) if r.get("net_return") is not None]
        if nets:
            means[rule] = statistics.mean(nets)
    if means:
        best = max(means, key=means.get)
        lines += ["", f"🏆 Bäst på snitt: <b>{_RULE_LABELS[best]}</b> ({_pct(means[best])})"]
    return "\n".join(lines)


def send_monthly_report(cfg: Config, exits: list[dict], dry_run: bool = False) -> str:
    msg = build_report(cfg, exits)
    if dry_run:
        print(msg)
    else:
        send_message(msg)
        logger.info("Månadsrapport skickad till Telegram")
    return msg
