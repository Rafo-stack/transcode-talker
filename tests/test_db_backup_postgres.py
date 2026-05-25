"""v3.3: Postgres branch of db_backup uses pg_dump/pg_restore (mocked here)."""
import os
from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.fixture
def pg_mode(monkeypatch):
    """Force active_backend()=='postgres' for the duration of the test."""
    monkeypatch.setenv("DB_BACKEND", "postgres")
    monkeypatch.setenv("POSTGRES_HOST", "pg.test")
    monkeypatch.setenv("POSTGRES_PORT", "5432")
    monkeypatch.setenv("POSTGRES_USER", "u")
    monkeypatch.setenv("POSTGRES_PASSWORD", "p")
    monkeypatch.setenv("POSTGRES_DB", "r")
    from app import db_backend
    db_backend._warned = False
    yield


def test_backup_db_runs_pg_dump(tmp_path, pg_mode):
    from app import db_backup as bk

    captured = {}

    class _Result:
        returncode = 0
        stderr = ""

    def fake_run(cmd, env=None, **kwargs):
        captured["cmd"] = cmd
        captured["env"] = env
        # Simulate pg_dump writing the output file
        target = Path(cmd[cmd.index("-f") + 1])
        target.write_bytes(b"PGDMP fake dump")
        return _Result()

    with patch("app.db_backup.subprocess.run", side_effect=fake_run):
        snap = bk.backup_db(tmp_path / "ignored.db", label="manual",
                            data_root=tmp_path)

    assert snap is not None
    assert snap.suffix == ".dump"
    assert "pg_dump" in captured["cmd"]
    # Connection params propagated
    assert "-h" in captured["cmd"]
    assert "pg.test" in captured["cmd"]
    assert "-U" in captured["cmd"]
    # PGPASSWORD passed via env, not argv
    assert captured["env"].get("PGPASSWORD") == "p"


def test_backup_db_returns_none_on_pg_dump_failure(tmp_path, pg_mode):
    from app import db_backup as bk

    class _Failure:
        returncode = 1
        stderr = "connection refused"

    with patch("app.db_backup.subprocess.run", return_value=_Failure()):
        snap = bk.backup_db(tmp_path / "ignored.db", label="manual",
                            data_root=tmp_path)
    assert snap is None


def test_restore_refuses_sqlite_dump_when_active_is_postgres(tmp_path, pg_mode):
    """A backup created in SQLite mode (.db) must not be applied to a Postgres install."""
    from app import db_backup as bk
    bdir = bk.backups_dir(tmp_path)
    sqlite_snap = bdir / "reencoder-manual-20260517T120000000Z.db"
    sqlite_snap.write_bytes(b"SQLite format 3\0fake")

    with pytest.raises(ValueError):
        bk.restore_backup(sqlite_snap, db_path=tmp_path / "live.db",
                          data_root=tmp_path)


def test_restore_refuses_pg_dump_when_active_is_sqlite(tmp_path, monkeypatch):
    """Reverse: a Postgres dump cannot be restored over a SQLite live DB."""
    # v3.4: default is now postgres, so we set sqlite explicitly.
    monkeypatch.setenv("DB_BACKEND", "sqlite")
    from app import db_backup as bk, db_backend
    db_backend._warned = False
    bdir = bk.backups_dir(tmp_path)
    pg_snap = bdir / "reencoder-manual-20260517T120000000Z.dump"
    pg_snap.write_bytes(b"PGDMP fake")

    with pytest.raises(ValueError):
        bk.restore_backup(pg_snap, db_path=tmp_path / "live.db",
                          data_root=tmp_path)


def test_list_backups_includes_postgres_dumps(tmp_path):
    from app.db_backup import backups_dir, list_backups
    d = backups_dir(tmp_path)
    (d / "reencoder-auto-20260517T120000000Z.db").write_bytes(b"a")
    (d / "reencoder-auto-20260517T120100000Z.dump").write_bytes(b"b")
    snaps = list_backups(data_root=tmp_path)
    kinds = {b["kind"] for b in snaps}
    assert kinds == {"sqlite", "postgres"}
