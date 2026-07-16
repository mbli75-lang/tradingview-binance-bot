"""Supabase-backend via PostgREST (HTTPS/443).

Används när Postgres wire-protocol (port 5432/6543) är blockerat av miljöns
nätverkspolicy men Supabase är nåbart över HTTPS. Samma gränssnitt som den
SQLAlchemy-baserade Repository: ingest_batch(records) -> IngestStats.

Kräver miljövariabler:
    SUPABASE_URL               t.ex. https://<ref>.supabase.co
    SUPABASE_SERVICE_ROLE_KEY  service_role-JWT (kringgår RLS)

Tabellerna måste finnas i förväg (kör insider_tracker/db/schema_supabase.sql
i Supabase SQL Editor) – PostgREST kan inte köra DDL.
"""
from __future__ import annotations

import datetime as dt
import logging
import os
import time

import requests

from insider_tracker.config import Config
from insider_tracker.ingest.parser import ParsedTransaction
from insider_tracker.ingest.repository import IngestStats

logger = logging.getLogger(__name__)

_CHUNK = 500


def _json_safe(value):
    if isinstance(value, (dt.date, dt.datetime)):
        return value.isoformat()
    return value


class SupabaseRestRepository:
    def __init__(self, cfg: Config, session: requests.Session | None = None):
        base = os.getenv("SUPABASE_URL")
        key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
        if not base or not key:
            raise RuntimeError(
                "SUPABASE_URL och SUPABASE_SERVICE_ROLE_KEY måste vara satta för "
                "REST-backenden."
            )
        self.cfg = cfg
        self.rest = base.rstrip("/") + "/rest/v1"
        self.timeout = cfg["fi"]["request_timeout"]
        self.session = session or requests.Session()
        self.session.headers.update(
            {
                "apikey": key,
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
                # Egress-proxyn blockerar default 'python-requests'-UA.
                "User-Agent": "InsiderTracker/1.0 (+https://github.com)",
            }
        )
        # Cache: normaliserat namn -> insider-id, över hela körningen.
        self._insider_ids: dict[str, int] = {}

    # ---------- lågnivå HTTP ----------
    def _request(self, method: str, path: str, *, params=None, json=None,
                 prefer=None, retries: int = 4) -> requests.Response:
        headers = {"Prefer": prefer} if prefer else None
        url = f"{self.rest}/{path}"
        delay = 2.0
        last_exc: Exception | None = None
        for attempt in range(retries):
            try:
                resp = self.session.request(
                    method, url, params=params, json=json, headers=headers,
                    timeout=self.timeout,
                )
                if resp.status_code >= 400:
                    # Ingen retry på klientfel – visa PostgREST-felet direkt.
                    raise RuntimeError(
                        f"Supabase {method} {path} -> HTTP {resp.status_code}: "
                        f"{resp.text[:500]}"
                    )
                return resp
            except requests.RequestException as exc:  # nätverksfel -> backoff
                last_exc = exc
                logger.warning("Supabase %s %s försök %d/%d: %s",
                               method, path, attempt + 1, retries, exc)
                if attempt < retries - 1:
                    time.sleep(delay)
                    delay *= 2
        raise RuntimeError(f"Supabase-anrop gav upp: {method} {path}") from last_exc

    def _upsert(self, table: str, rows: list[dict], on_conflict: str,
                resolution: str = "merge-duplicates", return_repr: bool = False,
                select: str | None = None) -> list[dict]:
        if not rows:
            return []
        params = {"on_conflict": on_conflict}
        if select:
            params["select"] = select
        ret = "return=representation" if return_repr else "return=minimal"
        prefer = f"resolution={resolution},{ret}"
        result: list[dict] = []
        for i in range(0, len(rows), _CHUNK):
            chunk = rows[i : i + _CHUNK]
            resp = self._request("POST", table, params=params, json=chunk, prefer=prefer)
            if return_repr:
                result.extend(resp.json())
        return result

    def count(self, table: str) -> int:
        resp = self._request("GET", table, params={"select": "id"},
                             prefer="count=exact")
        # Content-Range: 0-24/25  eller  */25
        cr = resp.headers.get("content-range", "*/0")
        return int(cr.split("/")[-1])

    def ping(self) -> None:
        """Verifiera anslutning + att tabellerna finns."""
        self._request("GET", "companies", params={"select": "isin", "limit": "1"})

    # ---------- ingest ----------
    def ingest_batch(self, records: list[ParsedTransaction]) -> IngestStats:
        stats = IngestStats()
        if not records:
            return stats

        # 1) companies (unik: isin)
        companies: dict[str, dict] = {}
        for r in records:
            companies.setdefault(r.isin, {
                "isin": r.isin, "name": r.issuer, "lei": r.lei,
                "marketplace": r.marketplace,
            })
        self._upsert("companies", list(companies.values()), on_conflict="isin")
        stats.companies_created = len(companies)

        # 2) insiders (unik: name_normalized) – bara de vi inte redan har id för
        new_insiders: dict[str, dict] = {}
        for r in records:
            nn = r.insider_name_normalized
            if nn not in self._insider_ids and nn not in new_insiders:
                new_insiders[nn] = {"name": r.insider_name, "name_normalized": nn}
        if new_insiders:
            returned = self._upsert(
                "insiders", list(new_insiders.values()),
                on_conflict="name_normalized", return_repr=True,
                select="id,name_normalized",
            )
            for row in returned:
                self._insider_ids[row["name_normalized"]] = row["id"]
            stats.insiders_created = len(returned)

        # 3) insider_roles (unik: insider_id, company_isin, role)
        roles: dict[tuple, dict] = {}
        for r in records:
            if not r.role:
                continue
            iid = self._insider_ids.get(r.insider_name_normalized)
            if iid is None:
                continue
            key = (iid, r.isin, r.role)
            roles.setdefault(key, {
                "insider_id": iid, "company_isin": r.isin, "role": r.role,
                "valid_from": _json_safe(r.trade_date),
            })
        if roles:
            self._upsert("insider_roles", list(roles.values()),
                         on_conflict="insider_id,company_isin,role",
                         resolution="ignore-duplicates")
            stats.roles_created = len(roles)

        # 4) transactions (unik: dedupe_hash) – ignore-duplicates för idempotens
        seen: set[str] = set()
        txn_rows: list[dict] = []
        for r in records:
            if r.dedupe_hash in seen:
                stats.duplicates += 1
                continue
            seen.add(r.dedupe_hash)
            iid = self._insider_ids.get(r.insider_name_normalized)
            txn_rows.append({
                "insider_id": iid,
                "company_isin": r.isin,
                "type": r.type,
                "volume": r.volume,
                "price": r.price,
                "currency": r.currency,
                "amount_sek": r.amount_sek,
                "trade_date": _json_safe(r.trade_date),
                "publish_date": _json_safe(r.publish_date),
                "publish_datetime": _json_safe(r.publish_datetime),
                "is_related_party": r.is_related_party,
                "instrument_type": r.instrument_type,
                "instrument_name": r.instrument_name,
                "marketplace": r.marketplace,
                "marketplace_raw": r.marketplace_raw,
                "character_raw": r.character_raw,
                "status": r.status,
                "is_first_report": r.is_first_report,
                "linked_to_share_program": r.linked_to_share_program,
                "dedupe_hash": r.dedupe_hash,
            })
        inserted = self._upsert(
            "transactions", txn_rows, on_conflict="dedupe_hash",
            resolution="ignore-duplicates", return_repr=True, select="id",
        )
        stats.inserted = len(inserted)
        stats.duplicates += len(txn_rows) - len(inserted)
        return stats

    def close(self) -> None:
        self.session.close()
