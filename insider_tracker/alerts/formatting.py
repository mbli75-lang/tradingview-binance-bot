"""Formatering av Telegram-alerts (HTML)."""
from __future__ import annotations

import html
import urllib.parse
from datetime import date

from insider_tracker.config import Config


def fmt_sek(x: float | None) -> str:
    if x is None:
        return "n/a"
    return f"{x:,.0f} kr".replace(",", " ")


def fmt_pct(x: float | None) -> str:
    if x is None:
        return "n/a"
    return f"{x:+.1%}"


def fi_link(cfg: Config, issuer: str | None) -> str:
    base = cfg["alerts"]["fi_search_base"]
    params = {"SearchFunctionType": "Insyn"}
    if issuer:
        params["Utgivare"] = issuer
    return f"{base}?{urllib.parse.urlencode(params)}"


def _liquidity_line(cfg: Config, turnover: float | None) -> str:
    warn = cfg["alerts"]["liquidity_warning_sek_per_day"]
    if turnover is None:
        return "💧 Likviditet: <i>okänd</i>"
    line = f"💧 Snittomsättning 30d: {fmt_sek(turnover)}/dag"
    if turnover < warn:
        line += " ⚠️ <b>LÅG LIKVIDITET</b>"
    return line


def build_buy_alert(cfg: Config, ctx: dict) -> str:
    """ctx: company, marketplace, segment, insider, role, amount_sek, n_trades,
    avg_return_3m, score, turnover, publish_date, issuer."""
    e = html.escape
    seg = f" · {e(ctx['segment'])}" if ctx.get("segment") else ""
    lines = [
        "🟢 <b>INSIDERKÖP – hög score</b>",
        f"<b>{e(ctx['company'])}</b> ({e(ctx.get('marketplace') or '?')}{seg})",
        f"👤 {e(ctx['insider'])} – {e(ctx.get('role') or 'okänd roll')}",
        f"💰 Belopp: {fmt_sek(ctx.get('amount_sek'))}"
        + ("  <i>(närstående)</i>" if ctx.get("is_related_party") else ""),
        f"📊 Historik: {ctx.get('n_trades', 0)} köp · snitt 3m "
        f"{fmt_pct(ctx.get('avg_return_3m'))} · score {ctx.get('score', 0):+.3f}",
        _liquidity_line(cfg, ctx.get("turnover")),
        f'🔗 <a href="{fi_link(cfg, ctx.get("issuer"))}">FI-posten</a>'
        f" · publ. {ctx.get('publish_date')}",
    ]
    return "\n".join(lines)


def build_cluster_alert(cfg: Config, ctx: dict) -> str:
    """ctx: company, marketplace, segment, n_insiders, n_buys, window_start,
    trigger_date, turnover, issuer, cluster_exc_3m."""
    e = html.escape
    seg = f" · {e(ctx['segment'])}" if ctx.get("segment") else ""
    lines = [
        "🔵 <b>KLUSTERKÖP</b>",
        f"<b>{e(ctx['company'])}</b> ({e(ctx.get('marketplace') or '?')}{seg})",
        f"👥 {ctx['n_insiders']} unika insiders · {ctx['n_buys']} köp "
        f"({ctx.get('window_start')} → {ctx.get('trigger_date')})",
        _liquidity_line(cfg, ctx.get("turnover")),
        f'🔗 <a href="{fi_link(cfg, ctx.get("issuer"))}">FI-posten</a>',
    ]
    return "\n".join(lines)


def build_sell_alert(cfg: Config, ctx: dict) -> str:
    """ctx: company, marketplace, insider, role, amount_sek, publish_date, issuer."""
    e = html.escape
    lines = [
        "🟠 <b>INFO: försäljning av tidigare köpflaggad insider</b>",
        f"<b>{e(ctx['company'])}</b> ({e(ctx.get('marketplace') or '?')})",
        f"👤 {e(ctx['insider'])} – {e(ctx.get('role') or 'okänd roll')}",
        f"💸 Sålde för {fmt_sek(ctx.get('amount_sek'))}",
        f'🔗 <a href="{fi_link(cfg, ctx.get("issuer"))}">FI-posten</a>'
        f" · publ. {ctx.get('publish_date')}",
    ]
    return "\n".join(lines)
