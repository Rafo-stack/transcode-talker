"""
B-018 regression: /api/encode/start must work on both SQLite and Postgres.

Pre-v3.4 the endpoint executed ``BEGIN IMMEDIATE`` unconditionally, which
is a syntax error in Postgres → every call hit the broad ``except`` and
returned 409 Conflict, completely breaking the Encode button on Postgres
deployments. These tests exercise:

  * the SQLite path (default in tests; should keep working as before),
  * the Postgres branch of the lock acquisition path (mocked dialect),
  * the force-reset endpoint that lets the UI recover from zombie sessions,
  * the enriched 409 payload that now carries ``active_session_id``.
"""
import json
import pytest


@pytest.fixture
def api_client(tmp_data_dir, monkeypatch):
    config_path = tmp_data_dir / "config.json"
    config_path.write_text(json.dumps({
        "scan_folders": [], "exclude_folders": [],
        "crf": 26, "preset": "fast", "encoder": "cpu",
        "hdd_temp_path": str(tmp_data_dir / "hdd-temp"),
        "ffmpeg_path": "ffmpeg", "ffprobe_path": "ffprobe",
        "extensions": [".mkv"], "ffmpeg_threads": 4,
    }))
    from app import config as cfg
    monkeypatch.setattr(cfg, "CONFIG_PATH", config_path)
    (tmp_data_dir / "static").mkdir(exist_ok=True)
    (tmp_data_dir / "static" / "index.html").write_text("<html></html>")
    import os
    old_cwd = os.getcwd()
    os.chdir(str(tmp_data_dir))
    try:
        import sys
        if "app.main" in sys.modules:
            del sys.modules["app.main"]
        from app import main as api_main
        from fastapi.testclient import TestClient
        yield TestClient(api_main.app)
    finally:
        os.chdir(old_cwd)


def test_encode_start_works_on_sqlite(api_client, tmp_data_dir):
    """Regression: SQLite path still acquires BEGIN IMMEDIATE without raising."""
    src = tmp_data_dir / "movie.mkv"
    src.write_bytes(b"VIDEO" * 100)
    r = api_client.post("/api/encode/start", json={"paths": [str(src)]})
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True
    assert r.json()["session_id"]


def test_encode_start_409_includes_active_session_id(api_client, tmp_data_dir):
    """v3.4: 409 payload now carries the blocking session id."""
    src = tmp_data_dir / "a.mkv"
    src.write_bytes(b"X" * 100)
    first = api_client.post("/api/encode/start", json={"paths": [str(src)]})
    assert first.status_code == 200
    sid = first.json()["session_id"]

    second = api_client.post("/api/encode/start", json={"paths": [str(src)]})
    assert second.status_code == 409
    body = second.json()
    assert "active_session_id" in body, body
    assert body["active_session_id"] == sid


def test_postgres_branch_uses_advisory_lock_not_begin_immediate(monkeypatch, api_client, tmp_data_dir):
    """B-018: when dialect is postgresql, we must call
    ``pg_advisory_xact_lock`` instead of ``BEGIN IMMEDIATE``.

    Pre-fix this would raise a syntax error and the endpoint would return
    409 for every request. We force the dialect to ``postgresql`` and
    record what SQL the endpoint asks the connection to execute. The
    expected call is the advisory lock; the legacy BEGIN IMMEDIATE must
    NOT appear.
    """
    from app import db_engine
    real_engine = db_engine.get_engine()

    class _PgDialect:
        name = "postgresql"

    class _FakeEngine:
        dialect = _PgDialect()
        # SQLAlchemy's Connection used by _Conn is opened from the real
        # engine — we only need to fake the ``dialect.name`` lookup.

    monkeypatch.setattr(db_engine, "get_engine", lambda: _FakeEngine())

    executed = []
    from app import database as api_db
    real_execute = api_db._Conn.execute

    def spy_execute(self, sql, params=None):
        executed.append(sql)
        if isinstance(sql, str) and sql.strip().lower().startswith("select pg_advisory_xact_lock"):
            # Skip — SQLite has no such function, would explode.
            return real_execute(self, "SELECT 1")
        return real_execute(self, sql, params)

    monkeypatch.setattr(api_db._Conn, "execute", spy_execute)

    src = tmp_data_dir / "z.mkv"
    src.write_bytes(b"X" * 100)
    r = api_client.post("/api/encode/start", json={"paths": [str(src)]})
    # Restore so subsequent tests aren't affected
    monkeypatch.setattr(db_engine, "get_engine", lambda: real_engine)

    assert r.status_code == 200, r.text
    # The Postgres lock SQL was issued
    assert any(
        isinstance(s, str) and "pg_advisory_xact_lock" in s.lower()
        for s in executed
    ), f"advisory lock not issued. Executed: {executed!r}"
    # AND the SQLite-only BEGIN IMMEDIATE was NOT
    assert not any(
        isinstance(s, str) and "begin immediate" in s.lower()
        for s in executed
    ), f"BEGIN IMMEDIATE leaked into Postgres path: {executed!r}"


def test_force_reset_clears_zombie_sessions(api_client, tmp_data_dir):
    """v3.4: /api/encode/force-reset unblocks /api/encode/start."""
    src = tmp_data_dir / "z.mkv"
    src.write_bytes(b"X" * 100)
    # Create a session — worker isn't running so it stays as a zombie.
    first = api_client.post("/api/encode/start", json={"paths": [str(src)]})
    assert first.status_code == 200

    # Second start hits 409 because the session is still "running" with
    # queued jobs and no worker has touched them.
    blocked = api_client.post("/api/encode/start", json={"paths": [str(src)]})
    assert blocked.status_code == 409

    # Force-reset → next start works.
    reset = api_client.post("/api/encode/force-reset", json={})
    assert reset.status_code == 200
    assert reset.json()["sessions_reset"] >= 1
    assert reset.json()["jobs_cancelled"] >= 1

    second = api_client.post("/api/encode/start", json={"paths": [str(src)]})
    assert second.status_code == 200


def test_force_reset_is_noop_with_no_active_session(api_client):
    r = api_client.post("/api/encode/force-reset", json={})
    assert r.status_code == 200
    assert r.json()["sessions_reset"] == 0
    assert r.json()["jobs_cancelled"] == 0
