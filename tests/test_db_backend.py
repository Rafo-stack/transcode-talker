"""M-029: DB_BACKEND env var scaffolding."""
import os
import pytest


@pytest.fixture(autouse=True)
def _reset_warned():
    # Reset the module-level _warned flag between tests
    from app import db_backend
    db_backend._warned = False
    yield
    db_backend._warned = False


def test_default_backend_is_postgres(monkeypatch):
    """v3.4: production default flipped from sqlite to postgres."""
    monkeypatch.delenv("DB_BACKEND", raising=False)
    from app.db_backend import active_backend, configured_backend
    assert configured_backend() == "postgres"
    assert active_backend() == "postgres"


def test_sqlite_still_works_when_explicit(monkeypatch):
    """SQLite continues to be supported when explicitly requested."""
    monkeypatch.setenv("DB_BACKEND", "sqlite")
    from app.db_backend import active_backend, configured_backend
    assert configured_backend() == "sqlite"
    assert active_backend() == "sqlite"


def test_postgres_is_an_active_backend(monkeypatch):
    """v3.3: Postgres is fully supported (no more fallback)."""
    monkeypatch.setenv("DB_BACKEND", "postgres")
    from app.db_backend import active_backend, configured_backend
    assert configured_backend() == "postgres"
    assert active_backend() == "postgres"


def test_unknown_backend_falls_back(monkeypatch, capsys):
    monkeypatch.setenv("DB_BACKEND", "mysql")
    from app.db_backend import active_backend
    assert active_backend() == "sqlite"
    out = capsys.readouterr().out
    assert "mysql" in out.lower() or "unknown" in out.lower()


def test_dsn_builds_from_env(monkeypatch):
    monkeypatch.setenv("POSTGRES_HOST", "db.example")
    monkeypatch.setenv("POSTGRES_PORT", "6432")
    monkeypatch.setenv("POSTGRES_USER", "u")
    monkeypatch.setenv("POSTGRES_PASSWORD", "p")
    monkeypatch.setenv("POSTGRES_DB", "r")
    from app.db_backend import postgres_dsn
    assert postgres_dsn() == "postgresql://u:p@db.example:6432/r"


def test_warning_only_logs_once_for_unknown(monkeypatch, capsys):
    monkeypatch.setenv("DB_BACKEND", "mariadb")
    from app.db_backend import active_backend
    active_backend()
    active_backend()
    active_backend()
    out = capsys.readouterr().out
    assert out.lower().count("unknown db_backend") <= 1
