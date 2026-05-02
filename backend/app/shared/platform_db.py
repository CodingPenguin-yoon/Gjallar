"""Platform state database configuration helpers."""

from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import MetaData, create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker


PROJECT_ROOT = Path(__file__).resolve().parents[3]
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Declarative base for platform state models."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def resolve_platform_state_db_path(project_root: Path | None = None) -> Path:
    """Resolve the platform state SQLite path."""
    root = project_root or PROJECT_ROOT
    raw_path = os.getenv("PLATFORM_STATE_DB_PATH", "").strip()
    if not raw_path:
        return root / "data" / "platform_state.db"

    candidate = Path(os.path.expanduser(raw_path))
    if candidate.is_absolute():
        return candidate
    return root / candidate


def resolve_platform_state_database_url(project_root: Path | None = None) -> str:
    """Resolve the SQLAlchemy URL for the platform state database."""
    explicit_url = os.getenv("PLATFORM_STATE_DATABASE_URL", "").strip()
    if explicit_url:
        return explicit_url

    db_path = resolve_platform_state_db_path(project_root)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite+pysqlite:///{db_path}"


def create_platform_engine(database_url: str | None = None) -> Engine:
    """Create a SQLAlchemy engine for platform state."""
    url = database_url or resolve_platform_state_database_url()
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    return create_engine(
        url,
        future=True,
        pool_pre_ping=True,
        connect_args=connect_args,
    )


def create_session_factory(engine: Engine) -> sessionmaker:
    """Create a SQLAlchemy session factory."""
    return sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
        future=True,
    )
