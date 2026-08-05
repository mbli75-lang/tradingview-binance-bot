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


def fmt_price(x: float | None) -> str:
    if x is None:
        return "n/a"
    return f"{x:.2f}".replace(".", ",") + " kr"


def buyer_line(b: dict) -> str:
    """En rad per köpare: 'Namn – roll: 92 000 kr @ 91,00 kr (2 köp)'."""
    e = html.escape
    n = b.get("n_buys", 1)
    tail = f" ({n} köp)" if n and n > 1 else ""
    who = f"{e(b.get('name') or '?')} – {e(b.get('role') or 'okänd roll')}"
    return f"   • {who}: {fmt_sek(b.get('amount'))} @ {fmt_price(b.get('price'))}{tail}"


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
        + (f" ({ctx['volume']:g} st @ {fmt_price(ctx.get('price'))})"
           if ctx.get("price") is not None and ctx.get("volume") is not None else "")
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
        f"({ctx.get('window_start')} → {ctx.get('trigger_date')}):",
    ]
    lines += [buyer_line(b) for b in ctx.get("buyers", [])]
    lines += [
        _liquidity_line(cfg, ctx.get("turnover")),
        f'🔗 <a href="{fi_link(cfg, ctx.get("issuer"))}">FI-posten</a>',
    ]
    return "\n".join(lines)


def build_cobuy_alert(cfg: Config, ctx: dict) -> str:
    """ctx: company, marketplace, segment, n_insiders, insiders (namn+roll-lista),
    window_start, trigger_date, turnover, issuer."""
    e = html.escape
    seg = f" · {e(ctx['segment'])}" if ctx.get("segment") else ""
    lines = [
        "🟣 <b>INFO: sam-köp</b> (flera insiders, under klustertröskeln)",
        f"<b>{e(ctx['company'])}</b> ({e(ctx.get('marketplace') or '?')}{seg})",
        f"👥 {ctx['n_insiders']} unika insiders köpte "
        f"({ctx.get('window_start')} → {ctx.get('trigger_date')}):",
    ]
    lines += [buyer_line(b) for b in ctx.get("buyers", [])]
    lines += [
        _liquidity_line(cfg, ctx.get("turnover")),
        f'🔗 <a href="{fi_link(cfg, ctx.get("issuer"))}">FI-posten</a>',
    ]
    return "\n".join(lines)


def build_cobuy_digest(cfg: Config, items: list[dict]) -> str:
    """Grupperad sam-köp-digest: flera bolag i ETT meddelande (mindre rörigt)."""
    e = html.escape
    warn = cfg["alerts"]["liquidity_warning_sek_per_day"]
    lines = [f"🟣 <b>Sam-köp (info) — {len(items)} bolag</b> "
             f"(flera insiders, under klustertröskeln)"]
    for c in items:
        seg = f" · {e(c['segment'])}" if c.get("segment") else ""
        turnover = c.get("turnover")
        liq = " ⚠️ låg likv." if (turnover is not None and turnover < warn) else ""
        lines.append("")
        lines.append(f"• <b>{e(c['company'])}</b> ({e(c.get('marketplace') or '?')}{seg}) — "
                     f"{c['n_insiders']} insiders{liq}")
        for b in c.get("buyers", []):
            lines.append(f"   {e(b.get('name') or '?')}: {fmt_sek(b.get('amount'))} "
                         f"@ {fmt_price(b.get('price'))}")
        lines.append(f'   <a href="{fi_link(cfg, c.get("issuer"))}">FI-posten</a> · {c.get("trigger_date")}')
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
