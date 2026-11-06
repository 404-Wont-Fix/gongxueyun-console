"""Database wiring: SQLite by default, any SQLAlchemy URL by configuration."""

from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .settings import get_settings

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    pass


def _prepare_sqlite(url: str) -> dict:
    if not url.startswith("sqlite"):
        return {}
    path = url.split("///")[-1]
    if path and path not in {":memory:"}:
        Path(path).expanduser().parent.mkdir(parents=True, exist_ok=True)
    return {"check_same_thread": False, "timeout": 30}


_settings = get_settings()
engine = create_engine(
    _settings.database_url,
    future=True,
    pool_pre_ping=True,
    connect_args=_prepare_sqlite(_settings.database_url),
)

if _settings.database_url.startswith("sqlite"):

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_connection, _record):  # pragma: no cover - driver hook
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.close()


SessionLocal = sessionmaker(bind=engine, class_=Session, expire_on_commit=False, autoflush=False)


def init_db() -> None:
    from . import models  # noqa: F401  (register mappers)

    Base.metadata.create_all(engine)
    _apply_column_migrations()
    logger.info("database ready: %s", engine.url.render_as_string(hide_password=True))


def _apply_column_migrations() -> None:
    """Add columns introduced after the first release.

    ``create_all`` creates missing tables but never alters existing ones. A full
    migration tool is overkill for this project; adding nullable columns is the
    only migration we need so far, and it is portable across SQLite/MySQL.
    """
    from sqlalchemy import inspect, text

    additions = [
        ("accounts", "coord_type", "VARCHAR(8) DEFAULT 'gcj02'"),
        ("accounts", "profile", "JSON"),
        ("accounts", "calendar_enabled", "BOOLEAN DEFAULT TRUE"),
        ("report_drafts", "plan_id", "INTEGER"),
        ("report_drafts", "plan_date", "VARCHAR(10) DEFAULT ''"),
    ]
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    with engine.begin() as connection:
        for table, column, ddl in additions:
            if table not in existing_tables:
                continue
            columns = {item["name"] for item in inspector.get_columns(table)}
            if column in columns:
                continue
            connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))
            logger.info("migrated: %s.%s", table, column)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
