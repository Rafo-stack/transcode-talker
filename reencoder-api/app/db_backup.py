"""
DB backup / restore utilities — B-017.

Goal: protect against history loss caused by accidental volume overwrites,
manual ``rm -rf data/``, broken migrations, or a fresh DB being initialised
on top of a misconfigured mount.

Strategy:
  * On every API startup, take a snapshot using SQLite's online backup API
    (atomic, hot — works even if another process is writing) into
    ``/data/backups/reencoder-<UTC timestamp>.db``.
  * Keep the N most recent snapshots; prune the rest.
  * Expose endpoints so the user can backup/restore/list snapshots from the UI.

Restore is destructive: it overwrites the live DB. The endpoint creates a
``pre-restore`` snapshot first so the user can roll back.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from app.db_backend import active_backend

DEFAULT_KEEP = 10

# Snapshot file extension by backend — SQLite is ``.db``, Postgres custom
# dump is ``.dump`` so list_backups can present them side by side.
_PG_EXT = ".dump"


def backups_dir(data_root: Path | None = None) -> Path:
    base = data_root or Path("/data")
    d = base / "backups"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _timestamp() -> str:
    # Millisecond precision so multiple snapshots in the same second don't
    # collide on filename and overwrite each other.
    now = datetime.now(timezone.utc)
    return now.strftime("%Y%m%dT%H%M%S") + f"{now.microsecond // 1000:03d}Z"


def backup_db(
    db_path: Path,
    *,
    label: str = "auto",
    keep: int = DEFAULT_KEEP,
    data_root: Path | None = None,
) -> Path | None:
    """
    Take a snapshot of the live DB.

    Behaviour by backend:
      * SQLite: uses the online backup API into ``reencoder-<label>-<ts>.db``.
        Returns None if ``db_path`` does not exist (nothing to back up).
      * Postgres: shells out to ``pg_dump -Fc`` into
        ``reencoder-<label>-<ts>.dump``. Returns None if the dump command
        fails or the server is unreachable.

    ``label`` is sanitised for filename use. Auto-snapshots are pruned to
    ``keep`` per backend (manual labels are never auto-pruned).
    """
    safe_label = "".join(c for c in label if c.isalnum() or c in ("-", "_")) or "auto"
    ts = _timestamp()
    backend = active_backend()

    if backend == "postgres":
        target = backups_dir(data_root) / f"reencoder-{safe_label}-{ts}{_PG_EXT}"
        ok = _pg_dump(target)
        if not ok:
            try:
                target.unlink()
            except OSError:
                pass
            return None
        _prune_backups(keep=keep, data_root=data_root)
        return target

    # SQLite path
    if not db_path.exists():
        return None
    target = backups_dir(data_root) / f"reencoder-{safe_label}-{ts}.db"
    src = sqlite3.connect(str(db_path))
    try:
        dst = sqlite3.connect(str(target))
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()
    _prune_backups(keep=keep, data_root=data_root)
    return target


# ── Postgres helpers ─────────────────────────────────────────────────────────
def _pg_env() -> dict:
    """Build env vars for pg_dump/pg_restore from the standard POSTGRES_*
    container env vars. PGPASSWORD avoids any prompt."""
    env = os.environ.copy()
    env["PGPASSWORD"] = os.environ.get("POSTGRES_PASSWORD", "")
    return env


def _pg_args() -> list[str]:
    """Common -h/-p/-U/-d args for pg_dump and pg_restore."""
    return [
        "-h", os.environ.get("POSTGRES_HOST", "postgres"),
        "-p", os.environ.get("POSTGRES_PORT", "5432"),
        "-U", os.environ.get("POSTGRES_USER", "reencoder"),
        "-d", os.environ.get("POSTGRES_DB",   "reencoder"),
    ]


def _pg_dump(target: Path) -> bool:
    """Run pg_dump in custom format (-Fc) to ``target``. Returns success."""
    try:
        cmd = ["pg_dump", "-Fc", "-Z", "6", "-f", str(target), *_pg_args()]
        r = subprocess.run(cmd, env=_pg_env(), capture_output=True, text=True, timeout=600)
        if r.returncode != 0:
            print(f"[db_backup] pg_dump failed: {r.stderr.strip()[:500]}")
            return False
        return True
    except FileNotFoundError:
        print("[db_backup] pg_dump not found in container — install postgresql-client")
        return False
    except Exception as e:
        print(f"[db_backup] pg_dump error: {e}")
        return False


def _pg_restore(source: Path) -> bool:
    """Restore via ``pg_restore --clean --if-exists`` from a custom-format dump.

    --clean drops the existing objects first so the restore overwrites the
    current contents. --if-exists prevents errors when the schema is fresh.
    """
    try:
        cmd = [
            "pg_restore", "--clean", "--if-exists", "--no-owner", "--no-privileges",
            *_pg_args(),
            str(source),
        ]
        r = subprocess.run(cmd, env=_pg_env(), capture_output=True, text=True, timeout=600)
        # pg_restore may emit harmless warnings (rc=1 with -e off) — treat
        # any non-zero exit as failure to be conservative.
        if r.returncode != 0:
            print(f"[db_backup] pg_restore failed: {r.stderr.strip()[:500]}")
            return False
        return True
    except FileNotFoundError:
        print("[db_backup] pg_restore not found in container — install postgresql-client")
        return False
    except Exception as e:
        print(f"[db_backup] pg_restore error: {e}")
        return False


def list_backups(data_root: Path | None = None) -> list[dict]:
    """Return snapshots newest-first with size + mtime metadata. Lists both
    SQLite (.db) and Postgres (.dump) snapshots so cross-backend migration
    workflows are visible."""
    d = backups_dir(data_root)
    out = []
    for pattern in ("reencoder-*.db", f"reencoder-*{_PG_EXT}"):
        for p in d.glob(pattern):
            try:
                st = p.stat()
            except OSError:
                continue
            out.append({
                "name": p.name,
                "path": str(p),
                "size_mb": round(st.st_size / 1048576, 2),
                "created_at": datetime.fromtimestamp(st.st_mtime, timezone.utc).isoformat(),
                "mtime": st.st_mtime,
                "kind": "postgres" if p.suffix == _PG_EXT else "sqlite",
            })
    out.sort(key=lambda b: b["mtime"], reverse=True)
    return out


def _prune_backups(*, keep: int, data_root: Path | None = None) -> int:
    """Delete oldest auto-snapshots beyond the keep limit. Manual snapshots
    (label != ``auto``) are never pruned automatically. Prunes per kind
    (sqlite/postgres) independently so a mixed-backend backups directory
    doesn't accidentally drop the wrong type."""
    if keep <= 0:
        return 0
    deleted = 0
    for kind in ("sqlite", "postgres"):
        autos = [
            b for b in list_backups(data_root)
            if "-auto-" in b["name"] and b["kind"] == kind
        ]
        if len(autos) <= keep:
            continue
        for b in autos[keep:]:
            try:
                Path(b["path"]).unlink()
                deleted += 1
            except OSError:
                continue
    return deleted


def restore_backup(
    backup_path: Path,
    *,
    db_path: Path,
    data_root: Path | None = None,
) -> dict:
    """
    Restore the live DB from a snapshot.

    Behaviour by backend:
      * SQLite: validates the file, takes a pre-restore snapshot, replaces
        the live DB atomically (rename on same fs), drops stale WAL/SHM.
      * Postgres: takes a pre-restore snapshot via pg_dump, then runs
        ``pg_restore --clean --if-exists`` to overwrite the running schema.

    Common safety:
      * Path-traversal: backup must live under the backups directory.
      * Schema sanity check before restore.
    """
    backup_path = Path(backup_path)
    if not backup_path.exists():
        raise FileNotFoundError(f"Backup not found: {backup_path}")
    if not backup_path.is_file():
        raise ValueError("Backup path is not a file")

    bdir = backups_dir(data_root).resolve()
    if bdir not in backup_path.resolve().parents:
        raise PermissionError("Backup path outside the backups directory")

    backend = active_backend()
    is_pg_dump = backup_path.suffix == _PG_EXT
    if backend == "postgres" and not is_pg_dump:
        raise ValueError("Active backend is Postgres but the backup is a SQLite file")
    if backend == "sqlite" and is_pg_dump:
        raise ValueError("Active backend is SQLite but the backup is a Postgres dump")

    if backend == "postgres":
        pre = backup_db(db_path, label="pre-restore", data_root=data_root)
        ok = _pg_restore(backup_path)
        if not ok:
            raise RuntimeError("pg_restore failed — see server logs")
        return {
            "restored_from": str(backup_path),
            "pre_restore_snapshot": str(pre) if pre else None,
            "ts": _timestamp(),
        }

    # SQLite path
    test = sqlite3.connect(str(backup_path))
    try:
        rows = test.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        tables = {r[0] for r in rows}
        for required in ("sessions", "jobs"):
            if required not in tables:
                raise ValueError(f"Backup missing required table: {required}")
    finally:
        test.close()

    pre = backup_db(db_path, label="pre-restore", data_root=data_root)

    staging = db_path.with_suffix(db_path.suffix + ".restoring")
    shutil.copy2(backup_path, staging)
    staging.replace(db_path)

    for sidecar in (db_path.with_suffix(db_path.suffix + "-wal"),
                    db_path.with_suffix(db_path.suffix + "-shm")):
        if sidecar.exists():
            try:
                sidecar.unlink()
            except OSError:
                pass

    return {
        "restored_from": str(backup_path),
        "pre_restore_snapshot": str(pre) if pre else None,
        "ts": _timestamp(),
    }


def db_has_history(db_path: Path) -> bool:
    """B-017 diagnostics: True if the live DB has any rows in jobs/sessions.
    Used to detect 'DB file existed but was empty after rebuild' scenarios.

    Backend-aware: for Postgres we query the engine directly because the
    'file' on disk doesn't apply.
    """
    if active_backend() == "postgres":
        try:
            from app.db_engine import get_engine
            eng = get_engine()
            with eng.connect() as c:
                for table in ("jobs", "sessions"):
                    row = c.exec_driver_sql(f"SELECT COUNT(*) FROM {table}").fetchone()
                    if row and row[0] > 0:
                        return True
        except Exception:
            return False
        return False

    if not db_path.exists():
        return False
    try:
        conn = sqlite3.connect(str(db_path))
        try:
            for table in ("jobs", "sessions"):
                row = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                    (table,)
                ).fetchone()
                if not row:
                    continue
                row = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
                if row and row[0] > 0:
                    return True
        finally:
            conn.close()
    except sqlite3.DatabaseError:
        return False
    return False
