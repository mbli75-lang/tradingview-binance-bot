"""Engine/session-fabrik. DB väljs via config.database_url (override: DATABASE_URL)."""
from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from insider_tracker.config import load_config
from insider_tracker.db.models import Base

_engine: Engine | None = None
_SessionFactory: sessionmaker[Session] | None = None


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        url = load_config().database_url
        # För lokala SQLite-filer: säkerställ att katalogen finns.
        if url.startswith("sqlite:///"):
            db_path = Path(url.replace("sqlite:///", "", 1))
            if db_path.parent and not db_path.parent.exists():
                db_path.parent.mkdir(parents=True, exist_ok=True)
        _engine = create_engine(url, future=True)
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    global _SessionFactory
    if _SessionFactory is None:
        _SessionFactory = sessionmaker(bind=get_engine(), future=True, expire_on_commit=False)
    return _SessionFactory


def init_db() -> None:
    """Skapa alla tabeller om de inte finns (idempotent)."""
    Base.metadata.create_all(get_engine())


def new_session() -> Session:
    return get_session_factory()()
