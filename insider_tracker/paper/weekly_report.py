"""Veckovis Telegram-sammanfattning av paper trading: nya signaler + öppna positioner."""
from __future__ import annotations

import logging
import statistics
from datetime import date, timedelta

from insider_tracker.config import Config
from insider_tracker.notify.telegram import send_message

logger = logging.getLogger(__name__)


def _pct(x):
    return "n/a" if x is None else f"{x:+.1%}"


def build_weekly(cfg: Config, trades: list[dict]) -> str:
    week_ago = (date.today() - timedelta(days=7)).isoformat()
    new = [t for t in trades if (t.get("signal_date") or "") >= week_ago]
    open_ = [t for t in trades if t.get("status") == "open"]
    closed = [t for t in trades if t.get("status") == "closed"]

    lines = [
        f"📈 <b>Paper trading – veckosammanfattning</b> ({date.today():%Y-%m-%d})",
        f"Totalt spårade: <b>{len(trades)}</b> · öppna {len(open_)} · stängda {len(closed)}",
        "",
        f"<b>Nya signaler senaste 7 dagarna: {len(new)}</b>",
    ]
    for t in new[:15]:
        exe = "✅" if t.get("executable") else "⚠️ illikvid"
        lines.append(
            f"• {t.get('company') or t.get('isin')} ({t.get('signal_type')}) {exe} · "
            f"entry {t.get('entry_price_realistic') or t.get('entry_price_theoretical')}")
    if len(new) > 15:
        lines.append(f"… +{len(new) - 15} till")

    mtm = [t["return_realistic"] for t in open_ if t.get("return_realistic") is not None]
    if mtm:
        lines += ["", f"<b>Öppna positioner (mark-to-market, realistiskt entry)</b>",
                  f"   median {_pct(statistics.median(mtm))} · "
                  f"andel>0 {sum(1 for v in mtm if v > 0)/len(mtm):.0%} · n={len(mtm)}"]
    lines += ["", "<i>Out-of-sample-validering pågår. Ta inga beslut på tunt underlag.</i>"]
    return "\n".join(lines)


def send_weekly(cfg: Config, trades: list[dict], dry_run: bool = False) -> str:
    msg = build_weekly(cfg, trades)
    if dry_run:
        print(msg)
    else:
        send_message(msg)
        logger.info("Veckorapport skickad")
    return msg
