"""EODHD-klient (fallback-kurskälla för ISIN som Börsdata inte täcker).

Inaktiv om EODHD_API_KEY saknas – is_enabled() returnerar då False och
pipelinen hoppar över fallbacken utan att krascha.

EODHD-flöde: slå upp ISIN -> symbol via /search, hämta sedan /eod/{symbol}.
"""
from __future__ import annotations

import logging
import os
import time

import requests

from insider_tracker.config import Config

logger = logging.getLogger(__name__)


class EODHDClient:
    def __init__(self, cfg: Config, session: requests.Session | None = None):
        eod = cfg["prices"]["eodhd"]
        self.base = eod["base_url"].rstrip("/")
        self.timeout = eod["request_timeout"]
        self._token = os.getenv("EODHD_API_KEY") or os.getenv("EODHD_API_TOKEN")
        self.session = session or requests.Session()
        self.session.headers["User-Agent"] = "InsiderTracker/1.0 (+https://github.com)"

    def is_enabled(self) -> bool:
        return bool(self._token)

    def _get(self, path: str, params: dict, retries: int = 3):
        params = dict(params)
        params["api_token"] = self._token
        params.setdefault("fmt", "json")
        url = f"{self.base}/{path.lstrip('/')}"
        delay = 2.0
        for attempt in range(retries):
            try:
                resp = self.session.get(url, params=params, timeout=self.timeout)
                resp.raise_for_status()
                return resp.json()
            except requests.RequestException as exc:
                logger.warning("EODHD %s försök %d/%d: %s", path, attempt + 1, retries, exc)
                if attempt < retries - 1:
                    time.sleep(delay)
                    delay *= 2
        return None

    def resolve_symbol(self, isin: str) -> str | None:
        data = self._get(f"search/{isin}", {})
        if data:
            # Föredra svensk börs (.ST) om flera träffar.
            hits = sorted(
                data,
                key=lambda h: 0 if str(h.get("Exchange", "")).upper() in ("ST", "STO") else 1,
            )
            if hits:
                code, exch = hits[0].get("Code"), hits[0].get("Exchange")
                if code and exch:
                    return f"{code}.{exch}"
        return None

    def get_stock_prices(self, isin: str, from_date: str, to_date: str) -> list[dict]:
        """Returnerar rader normaliserade till {d,o,h,l,c,v}."""
        symbol = self.resolve_symbol(isin)
        if not symbol:
            return []
        data = self._get(f"eod/{symbol}", {"from": from_date, "to": to_date})
        if not data:
            return []
        out = []
        for r in data:
            out.append({
                "d": r.get("date"),
                "o": r.get("open"),
                "h": r.get("high"),
                "l": r.get("low"),
                "c": r.get("adjusted_close", r.get("close")),
                "v": r.get("volume"),
            })
        return out
