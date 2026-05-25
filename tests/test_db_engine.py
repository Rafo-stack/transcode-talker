"""v3.3: SQLAlchemy engine factory + qmark→named translator."""
import pytest


def test_engine_url_is_sqlite_when_explicitly_requested(tmp_data_dir, monkeypatch):
    """v3.4: default flipped to postgres. Explicit sqlite still works."""
    monkeypatch.setenv("DB_BACKEND", "sqlite")
    from app import db_engine
    db_engine.reset_engine()
    eng = db_engine.get_engine()
    try:
        assert eng.url.drivername.startswith("sqlite")
    finally:
        db_engine.reset_engine()


def test_engine_url_is_postgres_when_configured(monkeypatch, tmp_path):
    monkeypatch.setenv("DB_BACKEND", "postgres")
    monkeypatch.setenv("POSTGRES_HOST", "host.example")
    monkeypatch.setenv("POSTGRES_PORT", "5432")
    monkeypatch.setenv("POSTGRES_USER", "u")
    monkeypatch.setenv("POSTGRES_PASSWORD", "p")
    monkeypatch.setenv("POSTGRES_DB", "r")
    from app import db_engine, db_backend
    db_backend._warned = False
    db_engine.reset_engine()
    url = db_engine._build_url()
    assert url.startswith("postgresql+psycopg2://")
    assert "host.example" in url
    assert "/r" in url


def test_qmark_translator_replaces_positional_placeholders():
    from app.database import _qmark_to_named
    sql, binds = _qmark_to_named("SELECT * FROM x WHERE a=? AND b=?", (1, "two"))
    assert sql == "SELECT * FROM x WHERE a=:p0 AND b=:p1"
    assert binds == {"p0": 1, "p1": "two"}


def test_qmark_translator_skips_question_marks_inside_strings():
    from app.database import _qmark_to_named
    sql, binds = _qmark_to_named(
        "INSERT INTO x VALUES (?, 'literal?value', ?)", (1, 2),
    )
    assert sql == "INSERT INTO x VALUES (:p0, 'literal?value', :p1)"
    assert binds == {"p0": 1, "p1": 2}


def test_qmark_translator_skips_question_marks_in_line_comments():
    from app.database import _qmark_to_named
    sql, binds = _qmark_to_named(
        "SELECT ? -- what?\nFROM x WHERE id = ?", (1, 2),
    )
    assert binds == {"p0": 1, "p1": 2}
    assert ":p0" in sql and ":p1" in sql


def test_migration_idempotent(tmp_data_dir):
    """Running schema migration twice does not raise (production rebuilds run startup repeatedly)."""
    from app import db_engine
    db_engine._migrate_jobs_metadata_columns(db_engine.get_engine())
    db_engine._migrate_jobs_metadata_columns(db_engine.get_engine())
