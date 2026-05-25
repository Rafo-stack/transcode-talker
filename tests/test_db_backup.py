"""B-017: backup / restore unit tests."""
import json
import sqlite3
import time
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _force_sqlite_for_local_backup_tests(monkeypatch):
    """v3.4: backup_db now branches on active_backend(). For SQLite-specific
    unit tests we must pin DB_BACKEND=sqlite — the new production default is
    postgres which would try to invoke pg_dump."""
    monkeypatch.setenv("DB_BACKEND", "sqlite")
    from app import db_backend
    db_backend._warned = False


@pytest.fixture
def api_client_with_backup(tmp_data_dir, monkeypatch):
    """FastAPI TestClient that uses tmp_data_dir for DB, logs and backups."""
    config_path = tmp_data_dir / "config.json"
    config_path.write_text(json.dumps({
        "scan_folders": [],
        "exclude_folders": [],
        "crf": 26,
        "preset": "fast",
        "encoder": "cpu",
        "hdd_temp_path": str(tmp_data_dir / "hdd-temp"),
        "ffmpeg_path": "ffmpeg",
        "ffprobe_path": "ffprobe",
        "extensions": [".mkv", ".mp4"],
        "ffmpeg_threads": 4,
    }))
    from app import config as cfg
    monkeypatch.setattr(cfg, "CONFIG_PATH", config_path)

    # db_backup writes to /data/backups by default; redirect both list and
    # backup_db helpers to a per-test directory by wrapping them.
    from app import db_backup as _db_backup_mod
    real_backups_dir = _db_backup_mod.backups_dir

    def _tmp_backups_dir(data_root=None):
        return real_backups_dir(data_root=data_root or tmp_data_dir)

    monkeypatch.setattr(_db_backup_mod, "backups_dir", _tmp_backups_dir)
    # Wrap backup_db so its default data_root is the tmp dir as well
    real_backup_db = _db_backup_mod.backup_db
    monkeypatch.setattr(
        _db_backup_mod, "backup_db",
        lambda db_path, *, label="auto", keep=_db_backup_mod.DEFAULT_KEEP, data_root=None:
            real_backup_db(db_path, label=label, keep=keep, data_root=data_root or tmp_data_dir),
    )
    real_restore = _db_backup_mod.restore_backup
    monkeypatch.setattr(
        _db_backup_mod, "restore_backup",
        lambda backup_path, *, db_path, data_root=None:
            real_restore(backup_path, db_path=db_path, data_root=data_root or tmp_data_dir),
    )
    real_list = _db_backup_mod.list_backups
    monkeypatch.setattr(
        _db_backup_mod, "list_backups",
        lambda data_root=None: real_list(data_root=data_root or tmp_data_dir),
    )

    # Static dir for FastAPI
    static_dir = tmp_data_dir / "static"
    static_dir.mkdir(exist_ok=True)
    (static_dir / "index.html").write_text("<html></html>")
    import os as _os
    old_cwd = _os.getcwd()
    _os.chdir(str(tmp_data_dir))

    try:
        import sys
        if "app.main" in sys.modules:
            del sys.modules["app.main"]
        from app import main as api_main
        # Re-bind the patched helpers onto main (they were imported by name)
        monkeypatch.setattr(api_main, "backup_db", _db_backup_mod.backup_db)
        monkeypatch.setattr(api_main, "list_backups", _db_backup_mod.list_backups)
        monkeypatch.setattr(api_main, "restore_backup", _db_backup_mod.restore_backup)
        monkeypatch.setattr(api_main, "backups_dir", _db_backup_mod.backups_dir)
        from app import database as api_db
        monkeypatch.setattr(api_main, "DB_PATH", api_db.DB_PATH)

        from fastapi.testclient import TestClient
        client = TestClient(api_main.app)
        yield client, tmp_data_dir
    finally:
        _os.chdir(old_cwd)


@pytest.fixture
def db_factory(tmp_path):
    """Build a small reencoder-shaped SQLite DB on disk and return its path."""
    def make(name="reencoder.db", rows=3):
        db = tmp_path / name
        conn = sqlite3.connect(str(db))
        conn.executescript("""
            CREATE TABLE sessions (id TEXT PRIMARY KEY, status TEXT);
            CREATE TABLE jobs (id INTEGER PRIMARY KEY, session_id TEXT, filename TEXT);
        """)
        for i in range(rows):
            conn.execute(
                "INSERT INTO sessions (id, status) VALUES (?, ?)",
                (f"s{i}", "completed"),
            )
            conn.execute(
                "INSERT INTO jobs (session_id, filename) VALUES (?, ?)",
                (f"s{i}", f"file_{i}.mkv"),
            )
        conn.commit()
        conn.close()
        return db
    return make


def test_backup_db_creates_snapshot(tmp_path, db_factory):
    from app.db_backup import backup_db, list_backups

    db = db_factory(rows=2)
    snap = backup_db(db, label="manual", data_root=tmp_path)

    assert snap is not None
    assert snap.exists()
    assert "manual" in snap.name

    snaps = list_backups(data_root=tmp_path)
    assert len(snaps) == 1
    assert snaps[0]["path"] == str(snap)


def test_backup_db_skips_missing_source(tmp_path):
    from app.db_backup import backup_db

    missing = tmp_path / "nope.db"
    assert backup_db(missing, label="auto", data_root=tmp_path) is None


def test_backup_db_snapshot_has_data(tmp_path, db_factory):
    from app.db_backup import backup_db

    db = db_factory(rows=5)
    snap = backup_db(db, label="auto", data_root=tmp_path)

    conn = sqlite3.connect(str(snap))
    try:
        n = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
    finally:
        conn.close()
    assert n == 5


def test_prune_keeps_only_recent_autos(tmp_path, db_factory):
    from app.db_backup import backup_db, list_backups

    db = db_factory(rows=1)
    # Create 7 auto snapshots; keep=3 should leave only 3
    paths = []
    for _ in range(7):
        paths.append(backup_db(db, label="auto", keep=3, data_root=tmp_path))
        time.sleep(0.01)  # ensure distinct mtime

    autos = [b for b in list_backups(data_root=tmp_path) if "-auto-" in b["name"]]
    assert len(autos) <= 3


def test_prune_does_not_touch_manual_snapshots(tmp_path, db_factory):
    from app.db_backup import backup_db, list_backups

    db = db_factory(rows=1)
    manuals = []
    for _ in range(3):
        manuals.append(backup_db(db, label="manual", keep=1, data_root=tmp_path))
        time.sleep(0.005)  # ensure unique millisecond timestamps
    autos = []
    for _ in range(3):
        autos.append(backup_db(db, label="auto", keep=1, data_root=tmp_path))
        time.sleep(0.005)

    all_snaps = list_backups(data_root=tmp_path)
    manual_names = [b for b in all_snaps if "-manual-" in b["name"]]
    auto_names = [b for b in all_snaps if "-auto-" in b["name"]]

    assert len(manual_names) == 3
    assert len(auto_names) <= 1


def test_restore_backup_replaces_db(tmp_path, db_factory):
    from app.db_backup import backup_db, restore_backup

    db = db_factory(rows=5)
    snap = backup_db(db, label="manual", data_root=tmp_path)

    # Mutate live DB
    conn = sqlite3.connect(str(db))
    conn.execute("DELETE FROM jobs")
    conn.commit()
    conn.close()

    # Sanity: live DB now empty
    conn = sqlite3.connect(str(db))
    assert conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 0
    conn.close()

    # Restore
    result = restore_backup(snap, db_path=db, data_root=tmp_path)
    assert result["restored_from"] == str(snap)
    assert result["pre_restore_snapshot"] is not None

    # DB should have 5 rows again
    conn = sqlite3.connect(str(db))
    assert conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 5
    conn.close()


def test_restore_rejects_path_outside_backups_dir(tmp_path, db_factory):
    from app.db_backup import restore_backup

    db = db_factory(rows=1)
    rogue = tmp_path / "rogue.db"
    rogue.write_bytes(db.read_bytes())

    with pytest.raises(PermissionError):
        restore_backup(rogue, db_path=db, data_root=tmp_path)


def test_restore_rejects_non_sqlite_file(tmp_path, db_factory):
    from app.db_backup import restore_backup, backups_dir

    db = db_factory(rows=1)
    bdir = backups_dir(tmp_path)
    fake = bdir / "reencoder-bogus.db"
    fake.write_text("not a sqlite file")

    with pytest.raises(Exception):
        restore_backup(fake, db_path=db, data_root=tmp_path)


def test_endpoint_state_reports_empty_history(api_client_with_backup):
    """B-017: /api/db/state surfaces empty-but-existing DB so the UI can warn."""
    client, data_dir = api_client_with_backup
    r = client.get("/api/db/state")
    assert r.status_code == 200
    body = r.json()
    assert "existed_at_startup" in body
    assert "had_history" in body
    assert body["had_history"] is False
    assert body["live_has_history"] is False


def test_endpoint_backup_and_list_roundtrip(api_client_with_backup, tmp_data_dir):
    """POST /api/db/backup → GET /api/db/backups returns the snapshot."""
    client, data_dir = api_client_with_backup
    from app import database as api_db

    # Seed the live DB so there's something worth backing up
    api_db.get_conn().close()
    conn = api_db.get_conn()
    api_db.create_session(conn, "alpha", 1, "2026-01-01 00:00:00")
    conn.close()

    r = client.post("/api/db/backup", json={"label": "before-tests"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert "before-tests" in body["snapshot"]

    r2 = client.get("/api/db/backups")
    assert r2.status_code == 200
    names = [b["name"] for b in r2.json()["backups"]]
    assert any("before-tests" in n for n in names)


def test_endpoint_restore_refuses_unknown_backup(api_client_with_backup):
    client, _ = api_client_with_backup
    r = client.post("/api/db/restore", json={"name": "does-not-exist.db"})
    assert r.status_code == 404


def test_endpoint_restore_refuses_during_active_session(api_client_with_backup, tmp_data_dir):
    """Restoring during an encode would corrupt worker state — must 409."""
    client, _ = api_client_with_backup
    from app import database as api_db
    from app.db_backup import backup_db, DEFAULT_KEEP

    # Take a snapshot of empty DB first
    api_db.get_conn().close()
    snap = backup_db(api_db.DB_PATH, label="for-restore-test")
    assert snap is not None

    # Start a session
    src = tmp_data_dir / "fake.mkv"
    src.write_bytes(b"VIDEO" * 50)
    client.post("/api/encode/start", json={"paths": [str(src)]})

    r = client.post("/api/db/restore", json={"name": snap.name})
    assert r.status_code == 409


def test_db_has_history_detects_empty_db(tmp_path, db_factory):
    from app.db_backup import db_has_history

    # No file → False
    assert db_has_history(tmp_path / "missing.db") is False

    # Empty schema, no rows → False
    db = tmp_path / "empty.db"
    conn = sqlite3.connect(str(db))
    conn.executescript("""
        CREATE TABLE sessions (id TEXT PRIMARY KEY);
        CREATE TABLE jobs (id INTEGER PRIMARY KEY);
    """)
    conn.commit()
    conn.close()
    assert db_has_history(db) is False

    # With rows → True
    populated = db_factory(rows=1)
    assert db_has_history(populated) is True
