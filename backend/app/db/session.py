"""SQLAlchemy engine/session lifecycle helpers."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session, sessionmaker

from app.db.config import get_database_url

_ENGINE: Engine | None = None
_SESSION_FACTORY: sessionmaker[Session] | None = None
_ENGINE_SIGNATURE: str | None = None


def _connect_args(database_url: str) -> dict:
    parsed = make_url(database_url)
    if parsed.drivername.startswith("sqlite"):
        return {"check_same_thread": False}
    return {}


def _ensure_sqlite_parent(database_url: str) -> None:
    parsed = make_url(database_url)
    if not parsed.drivername.startswith("sqlite"):
        return
    database = parsed.database
    if not database or database == ":memory:":
        return
    Path(database).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)


def get_engine() -> Engine:
    """Return a cached SQLAlchemy engine for the active database URL."""
    global _ENGINE, _ENGINE_SIGNATURE

    database_url = get_database_url()
    if _ENGINE is not None and _ENGINE_SIGNATURE == database_url:
        return _ENGINE

    if _ENGINE is not None:
        _ENGINE.dispose()

    _ensure_sqlite_parent(database_url)
    _ENGINE = create_engine(
        database_url,
        future=True,
        pool_pre_ping=True,
        connect_args=_connect_args(database_url),
    )
    _ENGINE_SIGNATURE = database_url
    return _ENGINE


def get_session_factory() -> sessionmaker[Session]:
    """Return a cached session factory for the active database URL."""
    global _SESSION_FACTORY

    engine = get_engine()
    if _SESSION_FACTORY is None or _SESSION_FACTORY.kw.get("bind") is not engine:
        _SESSION_FACTORY = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    return _SESSION_FACTORY


@contextmanager
def session_scope() -> Iterator[Session]:
    """Provide a transactional session scope."""
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def reset_session_cache(*, dispose: bool = True) -> None:
    """Clear cached DB objects after tests or environment changes."""
    global _ENGINE, _SESSION_FACTORY, _ENGINE_SIGNATURE

    if dispose and _ENGINE is not None:
        _ENGINE.dispose()
    _ENGINE = None
    _SESSION_FACTORY = None
    _ENGINE_SIGNATURE = None
