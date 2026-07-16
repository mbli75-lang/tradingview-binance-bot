"""Persistens av parsade transaktioner – idempotent via dedupe_hash.

Upsertar companies/insiders/insider_roles och infogar endast nya transaktioner.
In-memory-cache håller nere antalet queries under en backfill.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from insider_tracker.db.models import (
    Company, Insider, InsiderRole, Price, Transaction,
)
from insider_tracker.ingest.parser import ParsedTransaction

logger = logging.getLogger(__name__)


@dataclass
class IngestStats:
    inserted: int = 0
    duplicates: int = 0
    companies_created: int = 0
    insiders_created: int = 0
    roles_created: int = 0

    def merge(self, other: "IngestStats") -> None:
        self.inserted += other.inserted
        self.duplicates += other.duplicates
        self.companies_created += other.companies_created
        self.insiders_created += other.insiders_created
        self.roles_created += other.roles_created


class Repository:
    def __init__(self, session: Session):
        self.session = session
        self._insider_cache: dict[str, int] = {}          # name_norm -> id
        self._company_cache: set[str] = set()             # isin
        self._role_cache: set[tuple[int, str, str]] = set()  # (insider_id, isin, role)

    # ---- companies ----
    def _ensure_company(self, rec: ParsedTransaction, stats: IngestStats) -> None:
        if rec.isin in self._company_cache:
            return
        company = self.session.get(Company, rec.isin)
        if company is None:
            company = Company(
                isin=rec.isin,
                name=rec.issuer,
                lei=rec.lei,
                marketplace=rec.marketplace,
            )
            self.session.add(company)
            self.session.flush()
            stats.companies_created += 1
        else:
            # Fyll i saknade fält om nyare rad har dem.
            if not company.name and rec.issuer:
                company.name = rec.issuer
            if not company.lei and rec.lei:
                company.lei = rec.lei
            if not company.marketplace and rec.marketplace:
                company.marketplace = rec.marketplace
        self._company_cache.add(rec.isin)

    # ---- insiders ----
    def _ensure_insider(self, rec: ParsedTransaction, stats: IngestStats) -> int:
        cached = self._insider_cache.get(rec.insider_name_normalized)
        if cached is not None:
            return cached
        insider = self.session.scalar(
            select(Insider).where(
                Insider.name_normalized == rec.insider_name_normalized
            )
        )
        if insider is None:
            insider = Insider(
                name=rec.insider_name,
                name_normalized=rec.insider_name_normalized,
            )
            self.session.add(insider)
            self.session.flush()
            stats.insiders_created += 1
        self._insider_cache[rec.insider_name_normalized] = insider.id
        return insider.id

    # ---- roles ----
    def _ensure_role(
        self, insider_id: int, rec: ParsedTransaction, stats: IngestStats
    ) -> None:
        if not rec.role:
            return
        key = (insider_id, rec.isin, rec.role)
        if key in self._role_cache:
            return
        exists = self.session.scalar(
            select(InsiderRole.id).where(
                InsiderRole.insider_id == insider_id,
                InsiderRole.company_isin == rec.isin,
                InsiderRole.role == rec.role,
            )
        )
        if exists is None:
            self.session.add(
                InsiderRole(
                    insider_id=insider_id,
                    company_isin=rec.isin,
                    role=rec.role,
                    valid_from=rec.trade_date,
                )
            )
            self.session.flush()
            stats.roles_created += 1
        self._role_cache.add(key)

    def ingest_batch(self, records: list[ParsedTransaction]) -> IngestStats:
        """Upserta en batch parsade transaktioner. Idempotent på dedupe_hash."""
        stats = IngestStats()
        if not records:
            return stats

        # Ladda befintliga dedupe_hash för batchen i en query.
        hashes = list({r.dedupe_hash for r in records})
        existing: set[str] = set()
        # Chunka IN-listan för att undvika för många parametrar.
        for i in range(0, len(hashes), 500):
            chunk = hashes[i : i + 500]
            rows = self.session.scalars(
                select(Transaction.dedupe_hash).where(
                    Transaction.dedupe_hash.in_(chunk)
                )
            ).all()
            existing.update(rows)

        seen_in_batch: set[str] = set()
        for rec in records:
            if rec.dedupe_hash in existing or rec.dedupe_hash in seen_in_batch:
                stats.duplicates += 1
                continue
            seen_in_batch.add(rec.dedupe_hash)

            self._ensure_company(rec, stats)
            insider_id = self._ensure_insider(rec, stats)
            self._ensure_role(insider_id, rec, stats)

            self.session.add(
                Transaction(
                    insider_id=insider_id,
                    company_isin=rec.isin,
                    type=rec.type,
                    volume=rec.volume,
                    price=rec.price,
                    currency=rec.currency,
                    amount_sek=rec.amount_sek,
                    trade_date=rec.trade_date,
                    publish_date=rec.publish_date,
                    publish_datetime=rec.publish_datetime,
                    is_related_party=rec.is_related_party,
                    instrument_type=rec.instrument_type,
                    instrument_name=rec.instrument_name,
                    marketplace=rec.marketplace,
                    marketplace_raw=rec.marketplace_raw,
                    character_raw=rec.character_raw,
                    status=rec.status,
                    is_first_report=rec.is_first_report,
                    linked_to_share_program=rec.linked_to_share_program,
                    dedupe_hash=rec.dedupe_hash,
                )
            )
            stats.inserted += 1

        self.session.commit()
        return stats

    # ---------- steg 2: berikning + kurser ----------
    def tracked_companies(self) -> list[dict]:
        rows = self.session.execute(
            select(Company.isin, Company.borsdata_ins_id, Company.segment)
        ).all()
        return [
            {"isin": r[0], "borsdata_ins_id": r[1], "segment": r[2]} for r in rows
        ]

    def update_companies_meta(self, rows: list[dict]) -> int:
        for row in rows:
            company = self.session.get(Company, row["isin"])
            if company is None:
                continue
            for key in ("segment", "sector", "borsdata_ins_id"):
                if row.get(key) is not None:
                    setattr(company, key, row[key])
        self.session.commit()
        return len(rows)

    def upsert_prices(self, rows: list[dict]) -> int:
        n = 0
        for row in rows:
            existing = self.session.scalar(
                select(Price).where(
                    Price.isin == row["isin"], Price.date == row["date"]
                )
            )
            if existing is None:
                self.session.add(Price(**row))
            else:
                for key in ("open", "high", "low", "close", "volume", "source"):
                    if row.get(key) is not None:
                        setattr(existing, key, row[key])
            n += 1
        self.session.commit()
        return n
