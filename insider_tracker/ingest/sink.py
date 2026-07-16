"""Val av persistens-backend (sink) för ingest.

Två backends med samma gränssnitt (ingest_batch, count, close):
  * SqlAlchemySink  – SQLite/Postgres via SQLAlchemy (DATABASE_URL).
  * SupabaseRestSink – Supabase PostgREST över HTTPS (när port 5432 är blockerad).

Val styrs av config.storage.backend ('auto' | 'sqlalchemy' | 'supabase_rest').
"""
from __future__ import annotations

import logging
import os
from typing import Protocol

from insider_tracker.config import Config
from insider_tracker.ingest.parser import ParsedTransaction
from insider_tracker.ingest.repository import IngestStats

logger = logging.getLogger(__name__)

_TABLES = ["companies", "insiders", "insider_roles", "transactions"]


class Sink(Protocol):
    name: str

    def ingest_batch(self, records: list[ParsedTransaction]) -> IngestStats: ...
    def counts(self) -> dict[str, int]: ...
    def close(self) -> None: ...


class SqlAlchemySink:
    name = "sqlalchemy"

    def __init__(self, cfg: Config):
        from insider_tracker.db.session import init_db, new_session
        from insider_tracker.ingest.repository import Repository

        init_db()
        self._session = new_session()
        self._repo = Repository(self._session)

    def ingest_batch(self, records):
        return self._repo.ingest_batch(records)

    def counts(self) -> dict[str, int]:
        from sqlalchemy import func, select
        from insider_tracker.db.models import (
            Company, Insider, InsiderRole, Transaction,
        )
        models = {
            "companies": Company, "insiders": Insider,
            "insider_roles": InsiderRole, "transactions": Transaction,
        }
        return {
            name: self._session.scalar(select(func.count()).select_from(m))
            for name, m in models.items()
        }

    def close(self):
        self._session.close()


class SupabaseRestSink:
    name = "supabase_rest"

    def __init__(self, cfg: Config):
        from insider_tracker.ingest.supabase_repo import SupabaseRestRepository

        self._repo = SupabaseRestRepository(cfg)
        self._repo.ping()  # verifiera anslutning + att tabellerna finns

    def ingest_batch(self, records):
        return self._repo.ingest_batch(records)

    def counts(self) -> dict[str, int]:
        return {t: self._repo.count(t) for t in _TABLES}

    def close(self):
        self._repo.close()


def resolve_backend(cfg: Config) -> str:
    backend = (cfg.get("storage", {}) or {}).get("backend", "auto")
    if backend == "auto":
        if os.getenv("SUPABASE_URL") and os.getenv("SUPABASE_SERVICE_ROLE_KEY"):
            return "supabase_rest"
        return "sqlalchemy"
    return backend


def make_sink(cfg: Config) -> Sink:
    backend = resolve_backend(cfg)
    logger.info("Persistens-backend: %s", backend)
    if backend == "supabase_rest":
        return SupabaseRestSink(cfg)
    return SqlAlchemySink(cfg)
