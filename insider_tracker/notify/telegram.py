"""Telegram-notifiering. Används för felrapporter (steg 1) och alerts (steg 4).

Token/chat-id läses från miljön (TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID).
Om de saknas är funktionerna no-ops så att ingest kan köras utan Telegram.
"""
from __future__ import annotations

import logging
import os

import requests

from insider_tracker.config import load_config

logger = logging.getLogger(__name__)


def _credentials() -> tuple[str | None, str | None]:
    return os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")


def send_message(text: str, disable_web_page_preview: bool = True) -> bool:
    cfg = load_config()
    if not (cfg.get("telegram", {}) or {}).get("enabled", False):
        return False
    token, chat_id = _credentials()
    if not token or not chat_id:
        logger.debug("Telegram ej konfigurerat (saknar token/chat-id) – hoppar över.")
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        resp = requests.post(
            url,
            json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": disable_web_page_preview,
            },
            timeout=20,
        )
        resp.raise_for_status()
        return True
    except requests.RequestException as exc:
        logger.error("Kunde inte skicka Telegram-meddelande: %s", exc)
        return False


def send_error(context: str, exc: BaseException) -> None:
    cfg = load_config()
    tg = cfg.get("telegram", {}) or {}
    if not tg.get("enabled") or not tg.get("send_errors"):
        return
    send_message(f"🚨 <b>Insider-Tracker fel</b>\n{context}\n<code>{exc!r}</code>")
