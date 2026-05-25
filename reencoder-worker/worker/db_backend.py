"""
M-029: DB backend selection scaffolding.

This module is intentionally lightweight: it inspects the ``DB_BACKEND`` env
var and exposes ``active_backend()``. The full DAL port to Postgres is a
follow-up task — see ``Documentacao/sessao.md`` Etapa 1B for the plan.

Current behaviour:
  * ``DB_BACKEND`` unset or ``sqlite`` → use the existing ``app.database``
    DAL (default everywhere, preserves all v3.1 tests).
  * ``DB_BACKEND=postgres`` → log a clear warning and fall back to SQLite.
    The compose ``postgres`` profile already spins up a Postgres service
    so users can start migrating data even before the DAL switches over.

The History export/import JSON (M-024) is the supported way to move data
between SQLite and a future Postgres install.
"""
from __future__ import annotations

import os


SUPPORTED = ("sqlite", "postgres")
_warned = False


def configured_backend() -> str:
    """The literal value from the env var, lower-cased.

    v3.4: default changed to ``postgres`` to match the production deployment
    on M75q. The docker-compose default profile spins up a Postgres service
    so a plain ``docker compose up -d`` just works. To use SQLite instead,
    set ``DB_BACKEND=sqlite`` in the environment.
    """
    return (os.environ.get("DB_BACKEND") or "postgres").strip().lower()


def active_backend() -> str:
    """
    The backend actually used at runtime.

    v3.3: Postgres is fully supported. When ``DB_BACKEND=postgres`` is set,
    the SQLAlchemy engine is built against ``postgres_dsn()`` and all DAL
    code runs through it. Falls back to SQLite only if the value is
    unrecognised.
    """
    global _warned
    requested = configured_backend()
    if requested in SUPPORTED:
        return requested
    if not _warned:
        print(f"[db_backend] WARNING: unknown DB_BACKEND={requested!r}, "
              f"defaulting to sqlite. Valid values: {SUPPORTED}")
        _warned = True
    return "sqlite"


def postgres_dsn() -> str:
    """Build a libpq-style DSN from the POSTGRES_* env vars (M-029)."""
    host = os.environ.get("POSTGRES_HOST", "postgres")
    port = os.environ.get("POSTGRES_PORT", "5432")
    user = os.environ.get("POSTGRES_USER", "reencoder")
    pwd  = os.environ.get("POSTGRES_PASSWORD", "changeme")
    db   = os.environ.get("POSTGRES_DB", "reencoder")
    return f"postgresql://{user}:{pwd}@{host}:{port}/{db}"
