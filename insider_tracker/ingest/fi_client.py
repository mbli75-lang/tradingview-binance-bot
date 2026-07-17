"""HTTP-klient mot FI:s insynsregister-export.

Exporten kapar vid ~1000 rader och ignorerar Page-parametern (verifierat), så
enda robusta backfill-vägen är datumfönster på Publiceringsdatum med adaptiv
split: når ett fönster taket halveras det tills det får plats.
"""
from __future__ import annotations

import logging
import time
from datetime import date, timedelta

import requests

from insider_tracker.config import Config
from insider_tracker.ingest.parser import decode_export, read_rows

logger = logging.getLogger(__name__)


class FIClient:
    def __init__(self, cfg: Config, session: requests.Session | None = None):
        self.cfg = cfg
        self.base_url = cfg["fi"]["base_url"]
        self.search_type = cfg["fi"]["search_function_type"]
        self.row_cap = cfg["fi"]["export_row_cap"]
        self.timeout = cfg["fi"]["request_timeout"]
        self.session = session or requests.Session()
        # requests plockar upp HTTPS_PROXY och REQUESTS_CA_BUNDLE från miljön automatiskt.
        # Sätt en beskrivande User-Agent: default 'python-requests/*' blockeras av
        # vissa egress-policies (och webbservrar), medan en vanlig UA släpps igenom.
        # Direkt tilldelning (inte setdefault): Session har redan en 'User-Agent'.
        self.session.headers["User-Agent"] = (
            "InsiderTracker/1.0 (+https://github.com; kontakt via repo)"
        )

    def _fetch_raw(self, from_date: date, to_date: date, retries: int = 4) -> bytes:
        params = {
            "SearchFunctionType": self.search_type,
            "Publiceringsdatum.From": from_date.isoformat(),
            "Publiceringsdatum.To": to_date.isoformat(),
            "button": "export",
        }
        delay = 2.0
        last_exc: Exception | None = None
        for attempt in range(retries):
            try:
                resp = self.session.get(self.base_url, params=params, timeout=self.timeout)
                resp.raise_for_status()
                return resp.content
            except requests.RequestException as exc:  # nätverksfel -> backoff
                last_exc = exc
                logger.warning(
                    "FI-hämtning misslyckades (%s..%s) försök %d/%d: %s",
                    from_date, to_date, attempt + 1, retries, exc,
                )
                if attempt < retries - 1:
                    time.sleep(delay)
                    delay *= 2
        raise RuntimeError(f"FI-hämtning gav upp efter {retries} försök") from last_exc

    def iter_windows(self, from_date: date, to_date: date):
        """Generator som yieldar (window_from, window_to, raw_rows) för hela intervallet.

        Splittar automatiskt fönster som når radtaket. raw_rows är oparsade
        FI-dictar (filtrering sker i parser-lagret).
        """
        stack: list[tuple[date, date]] = [(from_date, to_date)]
        while stack:
            frm, to = stack.pop()
            raw = self._fetch_raw(frm, to)
            rows = read_rows(decode_export(raw))
            n = len(rows)
            if n >= self.row_cap and frm < to:
                # Taket nått -> troligen trunkerat. Halvera fönstret.
                mid = frm + (to - frm) // 2
                logger.info(
                    "Fönster %s..%s nådde taket (%d rader) – splittar vid %s",
                    frm, to, n, mid,
                )
                # Lägg tillbaka båda halvorna (senare halvan poppas först, ordning spelar ingen roll).
                stack.append((mid + timedelta(days=1), to))
                stack.append((frm, mid))
                continue
            if n >= self.row_cap and frm == to:
                logger.warning(
                    "Enskild dag %s nådde radtaket (%d) – kan vara trunkerad!", frm, n
                )
            logger.info("Fönster %s..%s: %d råa rader", frm, to, n)
            yield frm, to, rows
