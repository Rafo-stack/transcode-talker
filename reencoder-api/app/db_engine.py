"""
SQLAlchemy engine factory + shared schema (M-029, v3.3).

The same Table definitions and the same query code run on SQLite (default)
and Postgres (when ``DB_BACKEND=postgres``). The engine is a process-level
singleton built on first access.

Why SQLAlchemy Core (not ORM):
  * The existing DAL is row-oriented and dict-returning. ORM would force a
    bigger UI refactor than needed.
  * Core lets us keep the queries close to the original SQL while gaining
    dialect-aware DDL (autoincrement → SERIAL on Postgres, INTEGER PK on
    SQLite) and INSERT-with-conflict portability.

Why we still have a ``get_conn()``-shaped API:
  * Most callers want a "give me a thing I can write to and close" handle.
    The legacy code uses sqlite3.Connection. We replace it with a SQLAlchemy
    Connection that exposes ``.execute(text(...))``, ``.commit()`` and
    ``.close()`` — drop-in for the patterns we use.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from sqlalchemy import (
    Boolean, Column, Float, Integer, MetaData, String, Table, Text,
    create_engine, event,
)
from sqlalchemy.engine import Engine

from app.db_backend import active_backend, postgres_dsn


DB_PATH = Path("/data/reencoder.db")
LOGS_DIR = Path("/data/logs")

metadata = MetaData()

# Schema mirrors the previous CREATE TABLE statements. Columns are
# nullable=True to preserve the legacy permissive shape; constraints live
# in the app code (no FK on jobs→sessions because the worker rotates state
# faster than referential integrity would tolerate).
sessions_t = Table(
    "sessions", metadata,
    Column("id",          String,  primary_key=True),
    Column("status",      String,  nullable=False, server_default="pending"),
    Column("total_files", Integer, nullable=False, server_default="0"),
    Column("done_files",  Integer, nullable=False, server_default="0"),
    Column("created_at",  String,  nullable=False),
    Column("updated_at",  String),
)

jobs_t = Table(
    "jobs", metadata,
    Column("id",                   Integer, primary_key=True, autoincrement=True),
    Column("session_id",           String,  nullable=False),
    Column("filename",             String,  nullable=False),
    Column("original_path",        String,  nullable=False),
    Column("original_size_mb",     Float),
    Column("final_size_mb",        Float),
    Column("space_saved_mb",       Float),
    Column("original_hash",        String),
    Column("encoded_hash",         String),
    Column("crf_used",             Integer),
    Column("encoder_used",         String),
    Column("status",               String,  nullable=False, server_default="queued"),
    Column("current_frame",        Integer, server_default="0"),
    Column("total_frames",         Integer, server_default="0"),
    Column("pct",                  Float,   server_default="0"),
    Column("fps",                  String),
    Column("speed",                String),
    Column("eta_s",                Integer, server_default="0"),
    Column("error_msg",            Text),
    Column("started_at",           String),
    Column("completed_at",         String),
    # v3.3 enrichment:
    Column("source_metadata",      Text),
    Column("destination_metadata", Text),
    Column("ffmpeg_cmd",           Text),
)

scan_results_t = Table(
    "scan_results", metadata,
    Column("id",       Integer, primary_key=True),
    Column("data",     Text,    nullable=False),
    Column("saved_at", String,  nullable=False),
)

# v3.5: per-file ignore list. Independent from ``jobs`` so an ignore does not
# erase the file's real last status (failed/interrupted stays visible alongside
# the ignored badge). Path is the natural PK — one row per ignored file.
ignored_files_t = Table(
    "ignored_files", metadata,
    Column("original_path", String, primary_key=True),
    Column("ignored_at",    String, nullable=False),
    Column("reason",        Text),
)


_engine: Optional[Engine] = None


def _build_url() -> str:
    if active_backend() == "postgres":
        # SQLAlchemy URL format. psycopg2 is the sync driver.
        return postgres_dsn().replace("postgresql://", "postgresql+psycopg2://", 1)
    # SQLite. check_same_thread=False so we can use the same engine across
    # FastAPI threads (the broadcaster reads while endpoints write).
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{DB_PATH}?check_same_thread=false"


def reset_engine() -> None:
    """Drop the cached engine — tests use this when DB_PATH changes."""
    global _engine
    if _engine is not None:
        try:
            _engine.dispose()
        except Exception:
            pass
    _engine = None


def get_engine() -> Engine:
    """Lazy singleton. First call builds the engine and runs the DDL."""
    global _engine
    if _engine is not None:
        return _engine

    url = _build_url()
    kwargs = {"future": True, "pool_pre_ping": True}
    if url.startswith("sqlite"):
        # Use a single connection-per-call pattern; small pool is fine.
        kwargs["connect_args"] = {"timeout": 10}
    else:
        # Postgres: keep the pool small for a self-hosted single-user app.
        kwargs.update({"pool_size": 5, "max_overflow": 5, "pool_recycle": 1800})

    _engine = create_engine(url, **kwargs)

    if _engine.dialect.name == "sqlite":
        # Apply WAL/NORMAL once per connection so we keep the v3.1 behaviour.
        @event.listens_for(_engine, "connect")
        def _set_sqlite_pragma(dbapi_connection, _):
            cur = dbapi_connection.cursor()
            try:
                cur.execute("PRAGMA journal_mode=WAL")
                cur.execute("PRAGMA synchronous=NORMAL")
            finally:
                cur.close()

    # Create tables that don't exist. checkfirst=True so we never destroy
    # existing data when the schema is already present.
    metadata.create_all(_engine, checkfirst=True)
    _migrate_jobs_metadata_columns(_engine)
    return _engine


def _migrate_jobs_metadata_columns(engine: Engine) -> None:
    """
    v3.3 migration: ensure the three metadata columns exist on installs that
    were created against the v3.2 schema. Idempotent; safe to run on every
    startup. Postgres has native ``ADD COLUMN IF NOT EXISTS``; SQLite needs
    the existence probe via ``PRAGMA table_info``.
    """
    from sqlalchemy import text
    new_cols = {
        "source_metadata":      "TEXT",
        "destination_metadata": "TEXT",
        "ffmpeg_cmd":           "TEXT",
    }
    with engine.begin() as conn:
        if engine.dialect.name == "sqlite":
            existing = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(jobs)")}
            for name, typ in new_cols.items():
                if name not in existing:
                    conn.exec_driver_sql(f"ALTER TABLE jobs ADD COLUMN {name} {typ}")
        else:
            for name, typ in new_cols.items():
                conn.exec_driver_sql(
                    f"ALTER TABLE jobs ADD COLUMN IF NOT EXISTS {name} {typ}"
                )
