"""Börsdata API-klient (primär kurskälla).

Verifierat format (riktiga anrop 2026-07-16):
  * Auth: query-param authKey=<BORSDATA_API_KEY>
  * /markets   -> markets[].{id,name,countryId,isIndex}  (id = segment: Small Cap=3 …)
  * /instruments -> instruments[].{insId,name,isin,ticker,marketId,sectorId,countryId,…}
  * /instruments/{insId}/stockprices?from=&to= -> stockPricesList[].{d,o,h,l,c,v}
  * Rate limit ~100 anrop / 10 s.
"""
from __future__ import annotations

import collections
import logging
import os
import time
from dataclasses import dataclass

import requests

from insider_tracker.config import Config

logger = logging.getLogger(__name__)


@dataclass
class Instrument:
    ins_id: int
    name: str
    isin: str | None
    ticker: str | None
    market_id: int | None
    sector_id: int | None
    country_id: int | None


class _RateLimiter:
    """Enkel glidande-fönster-limiter: max N anrop per window_seconds."""

    def __init__(self, max_calls: int, window_seconds: float = 10.0):
        # Stanna säkert under gränsen.
        self.max_calls = max(1, int(max_calls * 0.9))
        self.window = window_seconds
        self._calls: collections.deque[float] = collections.deque()

    def wait(self) -> None:
        now = time.monotonic()
        while self._calls and now - self._calls[0] > self.window:
            self._calls.popleft()
        if len(self._calls) >= self.max_calls:
            sleep_for = self.window - (now - self._calls[0]) + 0.05
            if sleep_for > 0:
                time.sleep(sleep_for)
        self._calls.append(time.monotonic())


class BorsdataClient:
    def __init__(self, cfg: Config, session: requests.Session | None = None):
        bd = cfg["prices"]["borsdata"]
        self.base = bd["base_url"].rstrip("/")
        self.country_id = bd["country_id"]
        self.timeout = bd["request_timeout"]
        self.history_years = bd["history_years"]
        self._key = os.getenv("BORSDATA_API_KEY")
        if not self._key:
            raise RuntimeError("BORSDATA_API_KEY saknas i miljön.")
        self.session = session or requests.Session()
        self.session.headers["User-Agent"] = "InsiderTracker/1.0 (+https://github.com)"
        self._rl = _RateLimiter(bd["rate_limit_per_10s"])

    def _get(self, path: str, params: dict | None = None, retries: int = 4) -> dict:
        params = dict(params or {})
        params["authKey"] = self._key
        url = f"{self.base}/{path.lstrip('/')}"
        delay = 2.0
        last_exc: Exception | None = None
        for attempt in range(retries):
            self._rl.wait()
            try:
                resp = self.session.get(url, params=params, timeout=self.timeout)
                if resp.status_code == 429:  # rate limited -> vänta och försök igen
                    logger.warning("Börsdata 429 (rate limit) – väntar %.1fs", delay)
                    time.sleep(delay)
                    delay *= 2
                    continue
                resp.raise_for_status()
                return resp.json()
            except requests.RequestException as exc:
                last_exc = exc
                logger.warning("Börsdata %s försök %d/%d: %s", path, attempt + 1, retries, exc)
                if attempt < retries - 1:
                    time.sleep(delay)
                    delay *= 2
        raise RuntimeError(f"Börsdata-anrop gav upp: {path}") from last_exc

    # ---- metadata ----
    def get_markets(self) -> list[dict]:
        return self._get("markets").get("markets", [])

    def get_sectors(self) -> dict[int, str]:
        data = self._get("sectors").get("sectors", [])
        return {s["id"]: s["name"] for s in data}

    def get_instruments(self, country_only: bool = True) -> list[Instrument]:
        raw = self._get("instruments").get("instruments", [])
        out = []
        for i in raw:
            if country_only and i.get("countryId") != self.country_id:
                continue
            out.append(
                Instrument(
                    ins_id=i["insId"],
                    name=i.get("name") or "",
                    isin=i.get("isin"),
                    ticker=i.get("ticker"),
                    market_id=i.get("marketId"),
                    sector_id=i.get("sectorId"),
                    country_id=i.get("countryId"),
                )
            )
        return out

    # ---- kurser ----
    def get_stock_prices(
        self, ins_id: int, from_date: str, to_date: str
    ) -> list[dict]:
        """EOD-kurser för ett instrument. Returnerar [{d,o,h,l,c,v}, …]."""
        data = self._get(
            f"instruments/{ins_id}/stockprices",
            params={"from": from_date, "to": to_date},
        )
        return data.get("stockPricesList", [])
