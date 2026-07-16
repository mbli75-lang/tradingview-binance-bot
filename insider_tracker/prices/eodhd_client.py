"""EODHD-klient (fallback-kurskälla för ISIN som Börsdata inte täcker).

Inaktiv om EODHD_API_KEY saknas – is_enabled() returnerar då False och
pipelinen hoppar över fallbacken utan att krascha.

ISIN->symbol sker via exchange-symbol-list (fältet 'Isin'), eftersom search-API:et
inte ingår i alla planer. Avnoterade symboler inkluderas (delisted=1) – kritiskt
mot survivorship bias. Kurser hämtas sedan via /eod/{Code}.{Exchange}.
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
        self.exchanges = eod.get("exchanges", ["ST"])
        self.include_delisted = eod.get("include_delisted", True)
        self._token = os.getenv("EODHD_API_KEY") or os.getenv("EODHD_API_TOKEN")
        self.session = session or requests.Session()
        self.session.headers["User-Agent"] = "InsiderTracker/1.0 (+https://github.com)"
        self._isin_map: dict[str, str] | None = None  # ISIN -> "Code.Exchange"

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

    def _ensure_isin_map(self) -> dict[str, str]:
        if self._isin_map is not None:
            return self._isin_map
        m: dict[str, str] = {}
        for exch in self.exchanges:
            variants = [{}]
            if self.include_delisted:
                variants.append({"delisted": "1"})
            for extra in variants:
                data = self._get(f"exchange-symbol-list/{exch}", extra) or []
                for row in data:
                    isin = row.get("Isin")
                    code = row.get("Code")
                    if isin and code and isin not in m:
                        m[isin] = f"{code}.{exch}"
        self._isin_map = m
        logger.info("EODHD: %d ISIN->symbol-mappningar laddade", len(m))
        return m

    def resolve_symbol(self, isin: str) -> str | None:
        return self._ensure_isin_map().get(isin)

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
            if not r.get("date"):
                continue
            out.append({
                "d": r.get("date"),
                "o": r.get("open"),
                "h": r.get("high"),
                "l": r.get("low"),
                "c": r.get("adjusted_close", r.get("close")),
                "v": r.get("volume"),
            })
        return out
