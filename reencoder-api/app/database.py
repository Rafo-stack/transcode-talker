"""
Shared database — used by both API and Worker.

Single source of truth for application state. Powered by SQLAlchemy 2.x Core
so the same code runs on SQLite (default) and Postgres (when
``DB_BACKEND=postgres``). See ``app/db_engine.py`` for the engine factory.

Tables:
  sessions      — encode batches (one per "Start Encode" click)
  jobs          — individual files to encode (one per file per session)
                  v3.3: also carries source_metadata, destination_metadata,
                  and ffmpeg_cmd snapshots so the History/Logs panel has
                  everything needed for forensics.
  scan_results  — last scan output, persisted across restarts

Event log lives on disk: /data/logs/session_{id}.jsonl
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Iterable, Optional

from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.db_engine import (
    DB_PATH, LOGS_DIR, get_engine, jobs_t, scan_results_t, sessions_t,
)


__all__ = [
    "DB_PATH", "LOGS_DIR",
    "get_conn", "row_to_dict",
    "create_session", "update_session", "get_session",
    "get_active_session", "get_latest_session", "is_session_interrupted",
    "create_job", "update_job", "update_job_progress",
    "get_jobs", "get_jobs_page", "count_jobs", "get_job",
    "get_all_jobs", "count_all_jobs", "count_done_jobs",
    "cancel_pending_jobs", "recover_stale_jobs",
    "save_scan", "load_scan", "get_encoded_paths", "get_last_states_by_path",
    "add_ignored", "remove_ignored", "get_ignored_paths", "list_ignored",
    "append_event", "read_events", "read_events_tail", "read_events_since",
    "log_file_size", "delete_session_log", "cleanup_old_logs",
]


# ── Connection facade ────────────────────────────────────────────────────────
# Legacy DAL code (and the bulk of the existing tests) expects a connection
# object with .execute(sql, params) / .commit() / .close() and dict-friendly
# row access. SQLAlchemy's Connection gives us almost the same shape — we
# wrap it so that:
#   * ``.execute(sql, params_tuple)`` is auto-translated from positional ``?``
#     placeholders to SQLAlchemy ``text()`` (named binds) when needed.
#   * ``.commit()`` is a no-op for already-autocommit engines and a real
#     commit elsewhere, so legacy code stays correct in both dialects.
class _Conn:
    """Thin wrapper around a SQLAlchemy Connection in AUTOCOMMIT-ish mode.

    Every call gets its own implicit transaction that ``.commit()`` finalises
    explicitly, matching the v3.1 sqlite3 contract.
    """

    def __init__(self, sa_conn: Connection):
        self._c = sa_conn
        self._tx = None
        self._begin_if_needed()

    def _begin_if_needed(self):
        if self._tx is None or not self._tx.is_active:
            self._tx = self._c.begin()

    def execute(self, sql, params=None):
        self._begin_if_needed()
        if params is None:
            return _Result(self._c.exec_driver_sql(sql))
        if isinstance(params, dict):
            return _Result(self._c.execute(text(sql), params))
        # Positional tuple/list — translate ``?`` to ``:p0, :p1, ...``.
        sql_named, bind_dict = _qmark_to_named(sql, params)
        return _Result(self._c.execute(text(sql_named), bind_dict))

    def exec_driver_sql(self, sql, params=None):
        self._begin_if_needed()
        if params is None:
            return _Result(self._c.exec_driver_sql(sql))
        return _Result(self._c.exec_driver_sql(sql, params))

    def commit(self):
        if self._tx is not None and self._tx.is_active:
            self._tx.commit()
        self._tx = None

    def rollback(self):
        if self._tx is not None and self._tx.is_active:
            self._tx.rollback()
        self._tx = None

    def close(self):
        try:
            if self._tx is not None and self._tx.is_active:
                self._tx.rollback()
        finally:
            self._tx = None
            self._c.close()

    # Context-manager support for cleanup-on-error patterns.
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False


class _Result:
    """Adapter so callers can keep using ``row[col]`` and ``.fetchone()`` /
    ``.fetchall()`` like with the legacy sqlite3 cursor.

    Adds two convenience shims the original sqlite3 cursor exposed:
      * ``.lastrowid`` for INSERT (best-effort; preserved for SQLite).
      * ``.rowcount`` from the underlying result.
    """

    def __init__(self, sa_result):
        self._r = sa_result
        # Cache rows so fetchone/fetchall can be called multiple times in
        # tests / debug paths.
        self._rows = None

    def _materialise(self):
        if self._rows is None:
            try:
                self._rows = self._r.fetchall()
            except Exception:
                self._rows = []
        return self._rows

    def fetchone(self):
        rows = self._materialise()
        return _RowProxy(rows[0]) if rows else None

    def fetchall(self):
        return [_RowProxy(r) for r in self._materialise()]

    @property
    def rowcount(self):
        return self._r.rowcount if self._r is not None else 0

    @property
    def lastrowid(self):
        return self._r.lastrowid if self._r is not None else None


class _RowProxy:
    """Behaves like a sqlite3.Row: indexable by name and by position, dict-castable."""

    def __init__(self, sa_row):
        self._row = sa_row

    def __getitem__(self, key):
        if isinstance(key, int):
            return self._row[key]
        return self._row._mapping[key]

    def get(self, key, default=None):
        try:
            return self._row._mapping[key]
        except KeyError:
            return default

    def keys(self):
        return list(self._row._mapping.keys())

    def __iter__(self):
        return iter(self._row)

    def __contains__(self, key):
        return key in self._row._mapping

    def items(self):
        return list(self._row._mapping.items())

    # dict(row) works because of keys() + __getitem__.


def _qmark_to_named(sql: str, params: Iterable) -> tuple[str, dict]:
    """Translate ``?`` placeholders to ``:p0, :p1, …`` for SQLAlchemy text().

    Quoted strings and SQL comments are skipped so we don't replace a ``?``
    that's inside a literal.
    """
    out_chars: list[str] = []
    binds: dict = {}
    in_squote = False
    in_dquote = False
    in_line_comment = False
    in_block_comment = False
    pidx = 0
    params = list(params)
    i = 0
    while i < len(sql):
        c = sql[i]
        nxt = sql[i + 1] if i + 1 < len(sql) else ""
        if in_line_comment:
            out_chars.append(c)
            if c == "\n":
                in_line_comment = False
            i += 1
            continue
        if in_block_comment:
            out_chars.append(c)
            if c == "*" and nxt == "/":
                out_chars.append(nxt)
                in_block_comment = False
                i += 2
                continue
            i += 1
            continue
        if in_squote:
            out_chars.append(c)
            if c == "'":
                in_squote = False
            i += 1
            continue
        if in_dquote:
            out_chars.append(c)
            if c == '"':
                in_dquote = False
            i += 1
            continue
        if c == "'":
            in_squote = True
            out_chars.append(c)
            i += 1
            continue
        if c == '"':
            in_dquote = True
            out_chars.append(c)
            i += 1
            continue
        if c == "-" and nxt == "-":
            in_line_comment = True
            out_chars.append(c)
            i += 1
            continue
        if c == "/" and nxt == "*":
            in_block_comment = True
            out_chars.append(c)
            i += 1
            continue
        if c == "?":
            key = f"p{pidx}"
            out_chars.append(f":{key}")
            binds[key] = params[pidx]
            pidx += 1
            i += 1
            continue
        out_chars.append(c)
        i += 1
    return "".join(out_chars), binds


def get_conn(db_path: Path = None) -> _Conn:
    """Open a connection (delegates to the SQLAlchemy engine).

    The ``db_path`` arg is preserved for legacy callers that monkey-patched
    it in tests; it is ignored when the active backend is Postgres. The
    engine reads ``app.db_engine.DB_PATH`` for the SQLite URL, so tests
    patch that module-level attribute instead.
    """
    eng = get_engine()
    return _Conn(eng.connect())


def row_to_dict(row):
    return dict(row) if row is not None else None


# ── Sessions ─────────────────────────────────────────────────────────────────
def create_session(conn: _Conn, session_id: str, total: int, created_at: str):
    conn.execute(
        "INSERT INTO sessions (id, status, total_files, created_at) "
        "VALUES (?, 'running', ?, ?)",
        (session_id, total, created_at),
    )
    conn.commit()


def update_session(conn: _Conn, session_id: str, **kwargs):
    if not kwargs:
        return
    fields = ", ".join(f"{k} = :{k}" for k in kwargs)
    params = dict(kwargs)
    params["__sid"] = session_id
    conn.execute(f"UPDATE sessions SET {fields} WHERE id = :__sid", params)
    conn.commit()


def get_session(conn: _Conn, session_id: str) -> dict:
    row = conn.execute(
        "SELECT * FROM sessions WHERE id = ?", (session_id,)
    ).fetchone()
    return row_to_dict(row)


def get_active_session(conn: _Conn) -> dict:
    """Most recent session with status='running' AND at least one queued/encoding job.

    Protects against zombie sessions where the worker died leaving
    status='running' but no actual work remaining.
    """
    row = conn.execute(
        "SELECT s.* FROM sessions s "
        "WHERE s.status = 'running' "
        "AND EXISTS ("
        "  SELECT 1 FROM jobs j "
        "  WHERE j.session_id = s.id "
        "  AND j.status IN ('queued', 'encoding')"
        ") "
        "ORDER BY s.created_at DESC "
        "LIMIT 1"
    ).fetchone()
    return row_to_dict(row)


def get_latest_session(conn: _Conn) -> dict:
    """Returns the most recently created session regardless of status."""
    row = conn.execute(
        "SELECT * FROM sessions ORDER BY created_at DESC LIMIT 1"
    ).fetchone()
    return row_to_dict(row)


def is_session_interrupted(conn: _Conn, session_id: str) -> bool:
    row = conn.execute(
        "SELECT status FROM sessions WHERE id = ?", (session_id,)
    ).fetchone()
    return row is not None and row["status"] == "interrupted"


# ── Jobs ─────────────────────────────────────────────────────────────────────
def create_job(conn: _Conn, session_id: str, filename: str, original_path: str,
               original_size_mb: float, crf: int, encoder: str,
               created_at: str) -> int:
    """INSERT a job row and return its new id (dialect-portable via RETURNING)."""
    eng = get_engine()
    if eng.dialect.name == "postgresql":
        row = conn.execute(
            "INSERT INTO jobs "
            "(session_id, filename, original_path, original_size_mb, "
            " crf_used, encoder_used, status, started_at) "
            "VALUES (?, ?, ?, ?, ?, ?, 'queued', ?) RETURNING id",
            (session_id, filename, original_path, original_size_mb,
             crf, encoder, created_at),
        ).fetchone()
        new_id = int(row["id"])
    else:
        cur = conn.execute(
            "INSERT INTO jobs "
            "(session_id, filename, original_path, original_size_mb, "
            " crf_used, encoder_used, status, started_at) "
            "VALUES (?, ?, ?, ?, ?, ?, 'queued', ?)",
            (session_id, filename, original_path, original_size_mb,
             crf, encoder, created_at),
        )
        new_id = int(cur.lastrowid)
    conn.commit()
    return new_id


def update_job(conn: _Conn, job_id: int, **kwargs):
    if not kwargs:
        return
    fields = ", ".join(f"{k} = :{k}" for k in kwargs)
    params = dict(kwargs)
    params["__jid"] = job_id
    conn.execute(f"UPDATE jobs SET {fields} WHERE id = :__jid", params)
    conn.commit()


def update_job_progress(conn: _Conn, job_id: int, frame: int, pct: float,
                        fps: str, speed: str, eta_s: int):
    conn.execute(
        "UPDATE jobs SET current_frame = ?, pct = ?, fps = ?, speed = ?, eta_s = ? "
        "WHERE id = ?",
        (frame, pct, fps, speed, eta_s, job_id),
    )
    conn.commit()


def get_jobs(conn: _Conn, session_id: str) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM jobs WHERE session_id = ? ORDER BY id", (session_id,)
    ).fetchall()
    return [row_to_dict(r) for r in rows]


def get_jobs_page(conn: _Conn, session_id: str, limit: int = 500,
                  offset: int = 0, status: Optional[str] = None) -> list[dict]:
    """B-025: paginate jobs of a session so payload stays bounded.

    Defaults aim to cover the visible portion of the UI (queue + recently
    completed) without forcing the API to serialise thousands of rows.
    Active-status jobs (`encoding`/`queued`) are always cheap to fetch via
    ``status='encoding'`` / ``status='queued'`` filters.
    """
    limit = max(1, min(int(limit), 5000))
    offset = max(0, int(offset))
    if status:
        rows = conn.execute(
            "SELECT * FROM jobs WHERE session_id = ? AND status = ? "
            "ORDER BY id LIMIT ? OFFSET ?",
            (session_id, status, limit, offset),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM jobs WHERE session_id = ? "
            "ORDER BY id LIMIT ? OFFSET ?",
            (session_id, limit, offset),
        ).fetchall()
    return [row_to_dict(r) for r in rows]


def count_jobs(conn: _Conn, session_id: str,
               status: Optional[str] = None) -> int:
    """B-025 companion: cheap COUNT for pagination headers."""
    if status:
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM jobs "
            "WHERE session_id = ? AND status = ?",
            (session_id, status),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM jobs WHERE session_id = ?",
            (session_id,),
        ).fetchone()
    return int(row["c"]) if row else 0


def get_job(conn: _Conn, job_id: int) -> dict:
    row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return row_to_dict(row)


def get_all_jobs(conn: _Conn, limit: int = 200, offset: int = 0) -> list[dict]:
    """M-008: paginate jobs via limit+offset."""
    rows = conn.execute(
        "SELECT * FROM jobs ORDER BY id DESC LIMIT ? OFFSET ?", (limit, offset)
    ).fetchall()
    return [row_to_dict(r) for r in rows]


def count_all_jobs(conn: _Conn) -> int:
    return int(conn.execute("SELECT COUNT(*) AS c FROM jobs").fetchone()["c"])


def count_done_jobs(conn: _Conn, session_id: str) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM jobs WHERE session_id = ? "
        "AND status IN ('completed','failed','skipped','interrupted')",
        (session_id,),
    ).fetchone()
    return int(row["n"]) if row else 0


def cancel_pending_jobs(conn: _Conn, session_id: str, timestamp: str) -> int:
    res = conn.execute(
        "UPDATE jobs SET status='interrupted', completed_at=? "
        "WHERE session_id = ? AND status IN ('queued','encoding')",
        (timestamp, session_id),
    )
    conn.commit()
    return int(res.rowcount or 0)


def recover_stale_jobs(conn: _Conn, timestamp: str,
                       session_id: Optional[str] = None) -> int:
    if session_id is not None:
        res = conn.execute(
            "UPDATE jobs SET status='failed', "
            "error_msg='Worker crashed or restarted', completed_at=? "
            "WHERE status='encoding' AND session_id = ?",
            (timestamp, session_id),
        )
    else:
        res = conn.execute(
            "UPDATE jobs SET status='failed', "
            "error_msg='Worker crashed or restarted', completed_at=? "
            "WHERE status='encoding'",
            (timestamp,),
        )
    conn.commit()
    return int(res.rowcount or 0)


# ── Scan results ─────────────────────────────────────────────────────────────
def save_scan(conn: _Conn, files: list, saved_at: str):
    conn.execute("DELETE FROM scan_results")
    conn.execute(
        "INSERT INTO scan_results (data, saved_at) VALUES (?, ?)",
        (json.dumps(files), saved_at),
    )
    conn.commit()


def load_scan(conn: _Conn) -> tuple[list, str]:
    row = conn.execute(
        "SELECT data, saved_at FROM scan_results LIMIT 1"
    ).fetchone()
    if not row:
        return [], ""
    return json.loads(row["data"]), row["saved_at"]


def get_encoded_paths(conn: _Conn) -> set[str]:
    rows = conn.execute(
        "SELECT DISTINCT original_path FROM jobs WHERE status = 'completed'"
    ).fetchall()
    return {r["original_path"] for r in rows}


def add_ignored(conn: _Conn, path: str, ignored_at: str,
                reason: Optional[str] = None) -> None:
    """v3.5: mark ``path`` as ignored. Idempotent — re-ignoring an existing
    path refreshes ``ignored_at``/``reason`` rather than erroring.

    Dialect-portable upsert: SQLite supports ``INSERT OR REPLACE``; Postgres
    needs ``ON CONFLICT``. We branch on the engine dialect just like
    create_session does.
    """
    from app.db_engine import get_engine
    dialect = get_engine().dialect.name
    if dialect == "postgresql":
        conn.execute(
            "INSERT INTO ignored_files (original_path, ignored_at, reason) "
            "VALUES (?, ?, ?) "
            "ON CONFLICT (original_path) DO UPDATE SET "
            "ignored_at = EXCLUDED.ignored_at, reason = EXCLUDED.reason",
            (path, ignored_at, reason),
        )
    else:
        conn.execute(
            "INSERT OR REPLACE INTO ignored_files "
            "(original_path, ignored_at, reason) VALUES (?, ?, ?)",
            (path, ignored_at, reason),
        )
    conn.commit()


def remove_ignored(conn: _Conn, path: str) -> int:
    """v3.5: restore ``path`` (drop its ignore row). Returns rowcount."""
    res = conn.execute(
        "DELETE FROM ignored_files WHERE original_path = ?", (path,)
    )
    conn.commit()
    return res.rowcount or 0


def get_ignored_paths(conn: _Conn) -> set[str]:
    """v3.5: set of ignored paths — cheap membership lookup for filtering."""
    rows = conn.execute("SELECT original_path FROM ignored_files").fetchall()
    return {r["original_path"] for r in rows}


def list_ignored(conn: _Conn) -> list[dict]:
    """v3.5: full ignore list with timestamps + reason, newest first."""
    rows = conn.execute(
        "SELECT original_path, ignored_at, reason FROM ignored_files "
        "ORDER BY ignored_at DESC"
    ).fetchall()
    return [dict(r) for r in rows]


def get_last_states_by_path(conn: _Conn) -> dict[str, str]:
    """M-036: for each ``original_path`` in jobs, return the status of the job
    with the most recent ``completed_at``.

    Jobs that never completed (``completed_at IS NULL``) are ignored — paths
    that only ever had in-flight jobs simply won't appear in the dict, and
    the front-end treats absence as ``never_encoded``.

    Portable SQL: uses a correlated subquery so it works the same on SQLite
    and Postgres without dialect-specific syntax (``DISTINCT ON`` would be
    Postgres-only). Index ``idx_jobs_status`` is enough for typical sizes.
    """
    rows = conn.execute(
        "SELECT j1.original_path, j1.status FROM jobs j1 "
        "WHERE j1.completed_at IS NOT NULL "
        "AND j1.completed_at = ("
        "  SELECT MAX(j2.completed_at) FROM jobs j2 "
        "  WHERE j2.original_path = j1.original_path "
        "  AND j2.completed_at IS NOT NULL"
        ")"
    ).fetchall()
    # Possible duplicate timestamps for the same path resolve to the last
    # row seen — acceptable since identical ``completed_at`` values are
    # extremely rare in practice (sub-second resolution).
    return {r["original_path"]: r["status"] for r in rows}


# ── Event log (file-based) ───────────────────────────────────────────────────
def append_event(session_id: str, event: dict, logs_dir: Path = None):
    base = logs_dir or LOGS_DIR
    base.mkdir(parents=True, exist_ok=True)
    log_path = base / f"session_{session_id}.jsonl"
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


def read_events(session_id: str, logs_dir: Path = None) -> list[dict]:
    """Legacy reader — reads the whole JSONL into memory.

    B-025 made this dangerous for long-running sessions (file can grow to
    hundreds of MB). New callers should use ``read_events_tail`` or
    ``read_events_since``; ``read_events`` is kept for back-compat with code
    paths that genuinely need the full log (the history export, M-024b).
    """
    base = logs_dir or LOGS_DIR
    log_path = base / f"session_{session_id}.jsonl"
    if not log_path.exists():
        return []
    events = []
    with open(log_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except Exception:
                pass
    return events


def log_file_size(session_id: str, logs_dir: Path = None) -> int:
    """B-025: file size in bytes (cheap stat). 0 if the log doesn't exist."""
    base = logs_dir or LOGS_DIR
    log_path = base / f"session_{session_id}.jsonl"
    try:
        return log_path.stat().st_size
    except OSError:
        return 0


def read_events_tail(session_id: str, n: int = 200,
                     logs_dir: Path = None) -> tuple[list[dict], int]:
    """B-025: return the last ``n`` events plus the resulting file offset.

    Reads from the *end* of the JSONL backwards in fixed-size chunks until
    we have at least ``n`` newlines (or hit BOF). For a 100MB log this
    typically touches only the last ~50 KB even when ``n`` is large.

    Returns ``(events, byte_offset)`` where ``byte_offset`` is the current
    file size — pass it to ``read_events_since`` later to get only the
    delta written after this call.
    """
    base = logs_dir or LOGS_DIR
    log_path = base / f"session_{session_id}.jsonl"
    if not log_path.exists():
        return [], 0
    n = max(0, int(n))
    size = log_path.stat().st_size
    if n == 0 or size == 0:
        return [], size

    # Read backwards in CHUNK-sized blocks until we have n+1 newlines (the
    # +1 is the trailing newline that delimits the last full record) or
    # until we've consumed the whole file.
    CHUNK = 64 * 1024
    needed = n + 1
    pos = size
    buf = b""
    newline_count = 0
    with open(log_path, "rb") as f:
        while pos > 0 and newline_count < needed:
            read_size = min(CHUNK, pos)
            pos -= read_size
            f.seek(pos)
            chunk = f.read(read_size)
            buf = chunk + buf
            newline_count = buf.count(b"\n")
    # Parse all lines, then keep only the last n.
    try:
        text_buf = buf.decode("utf-8", errors="replace")
    except Exception:
        text_buf = ""
    lines = [ln for ln in text_buf.splitlines() if ln.strip()]
    tail = lines[-n:]
    events: list[dict] = []
    for line in tail:
        try:
            events.append(json.loads(line))
        except Exception:
            continue
    return events, size


def read_events_since(session_id: str, byte_offset: int,
                      logs_dir: Path = None) -> tuple[list[dict], int]:
    """B-025: return events appended to the log after ``byte_offset``.

    Used by the event broadcaster — instead of re-reading the whole JSONL
    every second (O(N) per tick), we seek to the last-known byte offset
    and read only what's new. Cost is proportional to the delta, not to
    the historical size of the log.

    Returns ``(events, new_offset)``. If the file shrunk (rotation/
    truncation), starts again from 0.
    """
    base = logs_dir or LOGS_DIR
    log_path = base / f"session_{session_id}.jsonl"
    if not log_path.exists():
        return [], 0
    size = log_path.stat().st_size
    start = byte_offset if 0 <= byte_offset <= size else 0
    if start == size:
        return [], size
    events: list[dict] = []
    with open(log_path, "rb") as f:
        f.seek(start)
        # Read remainder in one shot — the broadcaster polls every second so
        # ``size - start`` is bounded by a few KB in steady state.
        raw = f.read(size - start)
    # If we resumed mid-line (offset wasn't at a newline boundary), drop
    # the partial first line. The full record will be picked up next tick
    # when the writer finishes the line.
    text_buf = raw.decode("utf-8", errors="replace")
    lines = text_buf.split("\n")
    # If the read ended without a trailing newline, the last element is a
    # partial line — push the new offset back to just before it so we
    # re-read it next time.
    new_offset = size
    if lines and lines[-1] != "":
        partial = lines[-1]
        new_offset = size - len(partial.encode("utf-8", errors="replace"))
        lines = lines[:-1]
    else:
        lines = lines[:-1]  # drop empty tail after the final newline
    # Drop partial first line ONLY when we explicitly didn't start at BOF.
    if start != 0 and lines:
        first = lines[0]
        # Heuristic: a complete event line starts with '{' — if it doesn't,
        # we landed mid-record and should skip it.
        if not first.lstrip().startswith("{"):
            lines = lines[1:]
    for line in lines:
        s = line.strip()
        if not s:
            continue
        try:
            events.append(json.loads(s))
        except Exception:
            continue
    return events, new_offset


def delete_session_log(session_id: str, logs_dir: Path = None):
    base = logs_dir or LOGS_DIR
    log_path = base / f"session_{session_id}.jsonl"
    if log_path.exists():
        log_path.unlink()


def cleanup_old_logs(max_age_days: int = 30, logs_dir: Path = None) -> int:
    """B-009/M-001: delete session_*.jsonl older than max_age_days."""
    base = logs_dir or LOGS_DIR
    if not base.exists():
        return 0
    cutoff = time.time() - (max_age_days * 86400)
    deleted = 0
    for log_path in base.glob("session_*.jsonl"):
        try:
            if log_path.stat().st_mtime < cutoff:
                log_path.unlink()
                deleted += 1
        except OSError:
            continue
    return deleted
