"""
FFmpeg Re-Encoder API v3 — clean rewrite.

Responsibilities:
  - Serve UI
  - REST endpoints for config, scan, history, encode start/stop, HDD
  - WebSocket for real-time event streaming
  - Poll session log files and broadcast new events to connected browsers

Does NOT run ffmpeg. The worker process does that, completely independently.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

import app.config as cfg
# v3.5: structured-logging ring buffer + roadmap YAML loader powering the new
# Admin Logs and Roadmap pages of the rebuilt UI.
from app import admin_logs as _admin_logs
from app.roadmap import load as _load_roadmap

# Dedicated logger for "business" events (scan started, encode started, …).
# Anything routed through this name lands in the Admin Logs ring as a real
# structured entry, not as an opaque uvicorn access line.
_event_logger = logging.getLogger("reencoder.api")
from app.database import (
    DB_PATH,
    get_conn, create_session, get_active_session, get_latest_session,
    get_jobs, get_jobs_page, count_jobs,
    get_all_jobs, count_all_jobs, save_scan, load_scan,
    get_encoded_paths, get_last_states_by_path,
    add_ignored, remove_ignored, get_ignored_paths, list_ignored,
    read_events, read_events_tail, read_events_since, log_file_size,
    append_event, update_session,
    cancel_pending_jobs, cleanup_old_logs,
)
from app.db_backup import (
    backup_db, list_backups, restore_backup, db_has_history, backups_dir,
)
from app.db_backend import active_backend, configured_backend
from app.help_content import get_help as _get_help
from app.models import Config, EncodeJob, QueueAdd
from app.scanner import scan


# B-007/M-002: timezone configurable via TZ env var (default America/New_York)
_TZ = ZoneInfo(os.environ.get("TZ", "America/New_York"))
app = FastAPI(title="FFmpeg Re-Encoder v3")
# v3.5: the new SPA frontend (reencoder-web nginx container) is the public
# face of the app. The API container only serves JSON + websocket. The legacy
# static/index.html has been removed; the StaticFiles mount stays as an
# optional no-op so existing /static/* links return 404 rather than crashing
# the app if the directory is gone.
if Path("static").exists():
    app.mount("/static", StaticFiles(directory="static"), name="static")

_ws_clients: set[WebSocket] = set()


# ── M-003: optional HTTP Basic auth ──────────────────────────────────────────
# Enabled when BOTH env vars are set. /api/health is intentionally unauthenticated
# so Docker healthcheck/probes keep working. Production: terminate TLS + auth at
# a reverse proxy (Caddy/Traefik/Authelia) instead of relying on this.
_BASIC_USER = os.environ.get("BASIC_AUTH_USER", "")
_BASIC_PASS = os.environ.get("BASIC_AUTH_PASS", "")
_AUTH_ENABLED = bool(_BASIC_USER and _BASIC_PASS)


def _check_basic_auth(auth_header: str) -> bool:
    if not auth_header or not auth_header.lower().startswith("basic "):
        return False
    import base64
    try:
        raw = base64.b64decode(auth_header.split(" ", 1)[1]).decode("utf-8")
        u, _, p = raw.partition(":")
    except Exception:
        return False
    return (
        secrets.compare_digest(u.encode(), _BASIC_USER.encode())
        and secrets.compare_digest(p.encode(), _BASIC_PASS.encode())
    )


@app.middleware("http")
async def _basic_auth_middleware(request: Request, call_next):
    if not _AUTH_ENABLED:
        return await call_next(request)
    p = request.url.path
    # Public: health probe + static assets so probes/UI bootstrap still load.
    if p == "/api/health" or p.startswith("/static/"):
        return await call_next(request)
    auth = request.headers.get("authorization", "")
    if not _check_basic_auth(auth):
        return JSONResponse(
            {"error": "Authentication required"},
            status_code=401,
            headers={"WWW-Authenticate": 'Basic realm="reencoder"'},
        )
    return await call_next(request)


def _now(fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
    return datetime.now(_TZ).strftime(fmt)


# M-016: snapshot of recovered jobs computed at startup (rendered as a UI banner).
_STARTUP_TS: str = ""

# B-017: state observed at startup so the UI can warn if the DB was created
# empty after an apparent volume issue (e.g. ``data/`` overwritten by a rebuild).
_DB_STATE: dict = {
    "existed_at_startup": False,
    "had_history": False,
    "backup_taken": None,
}


# ── Lifecycle ────────────────────────────────────────────────────────────────
@app.on_event("startup")
async def on_startup():
    global _STARTUP_TS
    _STARTUP_TS = _now()
    Path("/data/logs").mkdir(parents=True, exist_ok=True)

    # v3.5: install the in-memory log ring before anything else so the
    # Admin Logs page captures startup itself (DB state, backend, etc.).
    _admin_logs.install()
    # Probe so the ring has at least one verifiable entry on startup.
    logging.getLogger("reencoder.api").info("admin logs ring installed", extra={
        "ring_capacity": _admin_logs._RING_CAPACITY,
    })

    # M-029: log which backend we're using so users can confirm their config.
    backend = active_backend()
    requested = configured_backend()
    if requested != backend:
        print(f"[api] DB_BACKEND={requested!r} requested → falling back to {backend!r}")
    else:
        print(f"[api] DB backend: {backend}")

    # B-017: diagnose DB state BEFORE get_conn() runs the schema (which would
    # silently create the file). Then take an automatic snapshot so the last
    # known-good state survives the next rebuild even if the volume was
    # accidentally wiped.
    _DB_STATE["existed_at_startup"] = DB_PATH.exists()
    _DB_STATE["had_history"] = db_has_history(DB_PATH)
    if _DB_STATE["existed_at_startup"] and _DB_STATE["had_history"]:
        try:
            snap = backup_db(DB_PATH, label="startup")
            _DB_STATE["backup_taken"] = str(snap) if snap else None
            if snap:
                print(f"[api] Startup DB snapshot: {snap}")
        except Exception as e:
            print(f"[api] Startup backup failed: {e}")
    elif _DB_STATE["existed_at_startup"] and not _DB_STATE["had_history"]:
        print("[api] WARNING: DB file exists but has no history rows — "
              "possible volume issue. Check /data/backups for a snapshot to restore.")
    else:
        print("[api] No DB at startup — fresh install or volume not mounted.")

    get_conn().close()  # Initialize schema

    # B-009/M-001/M-031: prune old session logs so /data/logs doesn't grow
    # unbounded — controlled by user config (retention days + on-startup flag).
    try:
        c = cfg.load()
        if c.get("clean_logs_on_startup", True):
            days = int(c.get("log_retention_days", 30))
            if days > 0:
                deleted = cleanup_old_logs(max_age_days=days)
                if deleted:
                    print(f"[api] Pruned {deleted} session log(s) older than {days} days")
    except Exception as e:
        print(f"[api] Log cleanup failed: {e}")
    asyncio.create_task(_event_broadcaster())


@app.get("/api/recovered-since-startup")
async def recovered_since_startup():
    """M-016: jobs the worker marked as failed during crash-recovery this startup."""
    conn = get_conn()
    try:
        rows = conn.execute("""
            SELECT id, filename, original_path, completed_at
            FROM jobs
            WHERE status='failed'
              AND error_msg='Worker crashed or restarted'
              AND completed_at >= ?
            ORDER BY id DESC
        """, (_STARTUP_TS,)).fetchall()
    finally:
        conn.close()
    return {"records": [dict(r) for r in rows], "startup_ts": _STARTUP_TS}


@app.get("/")
async def root():
    # v3.5: the SPA is served by nginx in front; the API container only
    # needs to be reachable. Returning a small JSON makes "is the API up?"
    # debuggable without exposing the legacy HTML.
    return {
        "service": "reencoder-api",
        "version": "v0.3.5.1",
        "ui": "served by reencoder-web (nginx) on port 4246",
    }


# ── Config ───────────────────────────────────────────────────────────────────
@app.get("/api/config")
async def get_config():
    return cfg.load()


@app.post("/api/config")
async def save_config(config: Config):
    cfg.save(config.model_dump())
    _event_logger.info(
        "config_updated",
        extra={"keys": sorted(config.model_dump().keys())[:8]},
    )
    return {"ok": True}


@app.get("/api/config/first-run")
async def first_run():
    return {"first_run": cfg.is_first_run()}


# ── M-021: Add-to-exclusion convenience endpoint ─────────────────────────────
@app.post("/api/config/exclude-folder")
async def exclude_folder(payload: dict):
    """Append ``path`` to config.exclude_folders if not already present.

    Used by the Scan page's per-folder "Add to exclusion" action so the user
    doesn't have to navigate to Settings.
    """
    path = (payload or {}).get("path")
    if not path or not isinstance(path, str):
        return JSONResponse({"error": "path is required"}, status_code=400)
    current = cfg.load()
    excludes = list(current.get("exclude_folders") or [])
    if path not in excludes:
        excludes.append(path)
        current["exclude_folders"] = excludes
        cfg.save(current)
    return {"ok": True, "exclude_folders": excludes}


# ── Directory browsing ───────────────────────────────────────────────────────
# B-006/M-004: whitelist roots — refuse anything outside /mnt (also blocks ../).
_BROWSE_ROOTS = ("/mnt",)

def _browse_allowed(path: str) -> bool:
    real = os.path.realpath(path)
    if real in _BROWSE_ROOTS:
        return True
    return any(real == r or real.startswith(r + os.sep) for r in _BROWSE_ROOTS)

@app.get("/api/browse")
async def browse(path: str = "/mnt"):
    if not _browse_allowed(path):
        return JSONResponse(
            {"error": "Path outside allowed roots (/mnt)"},
            status_code=403,
        )
    try:
        entries = []
        with os.scandir(path) as it:
            for entry in it:
                if entry.is_dir(follow_symlinks=False):
                    entries.append(entry.name)
        entries.sort()
        parent = str(Path(path).parent) if (path != "/" and _browse_allowed(str(Path(path).parent))) else None
        return {"path": path, "dirs": entries, "parent": parent}
    except PermissionError:
        parent_p = str(Path(path).parent)
        return {"path": path, "dirs": [], "parent": parent_p if _browse_allowed(parent_p) else None}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)


# ── Scan ─────────────────────────────────────────────────────────────────────
@app.post("/api/scan")
async def run_scan():
    config = cfg.load()
    c      = Config(**config)
    _event_logger.info(
        "scan_started",
        extra={"scan_folders": len(c.scan_folders), "exclude_folders": len(c.exclude_folders)},
    )
    files  = await asyncio.get_event_loop().run_in_executor(
        None, scan, c.scan_folders, c.exclude_folders, c.extensions
    )
    file_list = [f.model_dump() for f in files]

    conn = get_conn()
    try:
        save_scan(conn, file_list, _now())
    finally:
        conn.close()

    _event_logger.info(
        "scan_completed",
        extra={"file_count": len(file_list)},
    )
    return {"files": file_list}


@app.get("/api/scan/last")
async def last_scan():
    conn = get_conn()
    try:
        files, saved_at = load_scan(conn)
    finally:
        conn.close()
    return {"files": files, "saved_at": saved_at}


@app.get("/api/scan/file-states")
async def scan_file_states():
    """M-036: tag every file in scan with its last encoding outcome.

    Returns a dict ``{original_path: status}`` derived from the most
    recent job per path (by ``completed_at``). Status values are the same
    used in the ``jobs`` table (``completed``, ``failed``, ``skipped``,
    ``interrupted``). Paths that never had a completed job are simply
    absent — the UI treats absence as ``never_encoded``.

    Payload is small (one entry per unique path; ~30 bytes per entry).
    No pagination needed at the scale this project targets.

    v3.5: also returns ``ignored`` — list of paths the user manually ignored.
    The two dimensions are independent; the UI ANDs them so users can combine
    filters like "ignored + failed" or "not-ignored + never_encoded".
    """
    conn = get_conn()
    try:
        states  = get_last_states_by_path(conn)
        ignored = get_ignored_paths(conn)
    finally:
        conn.close()
    return {"paths": states, "ignored": sorted(ignored)}


# ── v3.5: Per-file ignore ────────────────────────────────────────────────────
@app.post("/api/files/ignore")
async def ignore_file(payload: dict):
    """Mark a path as ignored. Idempotent — re-ignoring refreshes timestamp.

    Lets users hide already-encoded files inside a folder that still receives
    new content, without excluding the whole folder.
    """
    path   = (payload or {}).get("path")
    reason = (payload or {}).get("reason")
    if not path or not isinstance(path, str):
        return JSONResponse({"error": "path is required"}, status_code=400)
    conn = get_conn()
    try:
        add_ignored(conn, path, _now(), reason if isinstance(reason, str) else None)
    finally:
        conn.close()
    _event_logger.info("file_ignored", extra={"path": path, "reason": reason})
    return {"ok": True, "path": path}


@app.post("/api/files/unignore")
async def unignore_file(payload: dict):
    """Restore a previously-ignored path. 404 if it wasn't in the list."""
    path = (payload or {}).get("path")
    if not path or not isinstance(path, str):
        return JSONResponse({"error": "path is required"}, status_code=400)
    conn = get_conn()
    try:
        n = remove_ignored(conn, path)
    finally:
        conn.close()
    if n == 0:
        return JSONResponse({"error": "Path was not ignored"}, status_code=404)
    _event_logger.info("file_restored", extra={"path": path})
    return {"ok": True, "path": path}


@app.get("/api/files/ignored")
async def list_ignored_endpoint():
    """Full ignore list with timestamps + reason. Newest first."""
    conn = get_conn()
    try:
        rows = list_ignored(conn)
    finally:
        conn.close()
    return {"records": rows}


# ── Encode ───────────────────────────────────────────────────────────────────
@app.post("/api/encode/start")
async def start_encode(job: EncodeJob):
    """Start a new encode session. Validates paths and prevents double-start."""
    if not job.paths:
        return JSONResponse({"error": "No files provided"}, status_code=400)

    # v3.5: drop ignored paths (safety net — UI should already hide/deselect them).
    conn = get_conn()
    try:
        ignored = get_ignored_paths(conn)
    finally:
        conn.close()
    skipped_ignored = [p for p in job.paths if p in ignored]
    paths = [p for p in job.paths if p not in ignored]
    if not paths:
        return JSONResponse(
            {"error": "All selected files are ignored", "skipped_ignored": skipped_ignored},
            status_code=400,
        )

    # Validate all paths exist before creating session
    missing = [p for p in paths if not os.path.exists(p)]
    if missing:
        return JSONResponse(
            {"error": f"Files not found: {missing[:3]}"},
            status_code=400
        )

    conn = get_conn()
    try:
        # B-001: serialize check-then-create so two concurrent
        # /api/encode/start calls cannot both pass the active-session check.
        # v3.4 fix (B-018): the previous implementation used SQLite's
        # ``BEGIN IMMEDIATE`` which is a syntax error in Postgres. The result
        # was that EVERY call hit the except block and returned 409, breaking
        # the Encode button entirely on Postgres deployments. Now we branch:
        #
        #   * SQLite → ``BEGIN IMMEDIATE`` (acquires the write lock).
        #   * Postgres → ``pg_advisory_xact_lock(N)`` (blocks until lock
        #     acquired; auto-released on transaction end).
        #
        # Both serialise concurrent starts at the DB layer.
        from app.db_engine import get_engine
        _dialect = get_engine().dialect.name
        try:
            if _dialect == "sqlite":
                conn.execute("BEGIN IMMEDIATE")
            elif _dialect == "postgresql":
                # Arbitrary lock key shared across processes for the
                # "start_encode" critical section.
                conn.execute("SELECT pg_advisory_xact_lock(42)")
            # Other dialects: rely on the per-call transaction wrapper.
        except Exception as e:
            import traceback
            print(f"[start_encode] lock failed ({_dialect}): {e}")
            traceback.print_exc()
            return JSONResponse(
                {"error": "Database busy, try again"},
                status_code=409,
            )

        try:
            existing = get_active_session(conn)
            if existing:
                conn.rollback()
                # v3.4: include the blocking session id so the UI can offer
                # a one-click "force-reset" or jump-to-encode flow instead
                # of a dead-end 409.
                return JSONResponse(
                    {
                        "error": "An encode session is already running",
                        "active_session_id": existing["id"],
                    },
                    status_code=409,
                )

            session_id  = str(uuid.uuid4())[:8]
            config_data = cfg.load()
            created_at  = _now()

            create_session(conn, session_id, len(paths), created_at)

            for path in paths:
                fname = Path(path).name
                try:
                    size_mb = round(os.path.getsize(path) / 1048576, 2)
                except Exception:
                    size_mb = 0.0
                conn.execute("""
                    INSERT INTO jobs
                        (session_id, filename, original_path, original_size_mb,
                         crf_used, encoder_used, status, started_at)
                    VALUES (?, ?, ?, ?, ?, ?, 'queued', ?)
                """, (session_id, fname, path, size_mb,
                      config_data.get("crf", 26),
                      config_data.get("encoder", "cpu"),
                      created_at))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    finally:
        conn.close()

    _event_logger.info(
        "encode_session_started",
        extra={
            "session_id": session_id,
            "file_count": len(paths),
            "skipped_ignored": len(skipped_ignored),
        },
    )

    return {
        "ok": True,
        "session_id": session_id,
        "skipped_ignored": skipped_ignored,
    }


@app.post("/api/encode/force-reset")
async def encode_force_reset():
    """
    v3.4: nuke any zombie session that's blocking /api/encode/start.

    Marks all sessions still in 'running' state as 'interrupted', cancels
    every queued/encoding job, and lets the worker pick up new sessions.
    Use this when the UI sees 409 from /api/encode/start but no actual
    encode is making progress (worker died, crash between sessions, etc.).

    Returns {sessions_reset, jobs_cancelled}.
    """
    conn = get_conn()
    sessions_reset = 0
    jobs_cancelled = 0
    try:
        rows = conn.execute(
            "SELECT id FROM sessions WHERE status='running'"
        ).fetchall()
        ts = _now()
        for r in rows:
            sid = r["id"]
            update_session(conn, sid, status="interrupted", updated_at=ts)
            jobs_cancelled += cancel_pending_jobs(conn, sid, ts)
            sessions_reset += 1
            try:
                append_event(sid, {
                    "type": "queue_stopped",
                    "session_id": sid,
                    "reason": "force-reset",
                    "time": _now("%H:%M:%S"),
                })
            except Exception:
                pass
    finally:
        conn.close()
    return {
        "ok": True,
        "sessions_reset": sessions_reset,
        "jobs_cancelled": jobs_cancelled,
    }


@app.post("/api/encode/queue/add")
async def encode_queue_add(payload: QueueAdd):
    """
    M-028: append paths to the active session's queue.

    Returns 409 when no session is active (use ``/api/encode/start`` instead).
    De-duplicates against paths already in the session (any status).
    """
    if not payload.paths:
        return JSONResponse({"error": "No files provided"}, status_code=400)

    missing = [p for p in payload.paths if not os.path.exists(p)]
    if missing:
        return JSONResponse({"error": f"Files not found: {missing[:3]}"}, status_code=400)

    conn = get_conn()
    try:
        # v3.5: drop ignored paths (safety net)
        ignored_set = get_ignored_paths(conn)
        skipped_ignored = [p for p in payload.paths if p in ignored_set]
        queueable = [p for p in payload.paths if p not in ignored_set]

        session = get_active_session(conn)
        if not session:
            return JSONResponse(
                {"error": "No active session. Use /api/encode/start instead."},
                status_code=409,
            )
        session_id = session["id"]
        # De-dupe against this session's existing rows (any status)
        existing_rows = conn.execute(
            "SELECT original_path FROM jobs WHERE session_id = ?", (session_id,)
        ).fetchall()
        existing = {r["original_path"] for r in existing_rows}

        config_data = cfg.load()
        added = 0
        for path in queueable:
            if path in existing:
                continue
            fname = Path(path).name
            try:
                size_mb = round(os.path.getsize(path) / 1048576, 2)
            except Exception:
                size_mb = 0.0
            conn.execute("""
                INSERT INTO jobs
                    (session_id, filename, original_path, original_size_mb,
                     crf_used, encoder_used, status, started_at)
                VALUES (?, ?, ?, ?, ?, ?, 'queued', ?)
            """, (session_id, fname, path, size_mb,
                  config_data.get("crf", 26),
                  config_data.get("encoder", "cpu"),
                  _now()))
            existing.add(path)
            added += 1

        # Bump total_files on the session so progress accounting stays correct
        if added:
            conn.execute(
                "UPDATE sessions SET total_files = total_files + ?, updated_at = ? WHERE id = ?",
                (added, _now(), session_id),
            )
        conn.commit()
    finally:
        conn.close()

    if added:
        append_event(session_id, {
            "type": "queue_appended",
            "session_id": session_id,
            "added": added,
            "time": _now("%H:%M:%S"),
        })
        _event_logger.info(
            "queue_appended",
            extra={"session_id": session_id, "added": added},
        )

    return {
        "ok": True, "added": added, "session_id": session_id,
        "skipped_ignored": skipped_ignored,
    }


@app.post("/api/encode/stop")
async def stop_encode():
    """Mark active session as interrupted. Worker detects this and stops cleanly."""
    conn = get_conn()
    try:
        session = get_active_session(conn)
        if not session:
            return {"ok": True, "message": "No active session"}

        now = _now()
        update_session(conn, session["id"], status="interrupted", updated_at=now)
        cancelled = cancel_pending_jobs(conn, session["id"], now)

        append_event(session["id"], {
            "type": "queue_stopped",
            "session_id": session["id"],
            "cancelled": cancelled,
            "time": _now("%H:%M:%S"),
        })
        _event_logger.warning(
            "encode_session_stopped",
            extra={"session_id": session["id"], "cancelled_jobs": cancelled},
        )
    finally:
        conn.close()

    return {"ok": True, "cancelled": cancelled}


# ── v3.5.1: per-job cancel ───────────────────────────────────────────────────
# Used by the "X" button on each row of the Encode page's queue list.
#  - queued  → flip the row to 'interrupted'; the worker's next iteration
#              skips it because it only picks up rows still in 'queued'.
#  - encoding → there is no per-file stop signal in the current worker, so
#               we fall back to the existing session-wide stop. The frontend
#               warns the user about this before sending. A roadmap item
#               (F-305) tracks adding a per-file stop that keeps the queue
#               running.
#  - anything else (completed/failed/skipped/interrupted) → 409.
@app.post("/api/jobs/{job_id}/cancel")
async def cancel_job(job_id: int):
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT id, session_id, status, filename FROM jobs WHERE id = ?",
            (job_id,),
        ).fetchone()
        if not row:
            return JSONResponse({"ok": False, "error": "Job not found"}, status_code=404)

        status = row["status"]
        session_id = row["session_id"]

        if status == "queued":
            now = _now()
            conn.execute(
                "UPDATE jobs SET status = 'interrupted', completed_at = ?, error_msg = 'Removed from queue by user' WHERE id = ?",
                (now, job_id),
            )
            conn.commit()
            append_event(session_id, {
                "type": "queue_job_removed",
                "session_id": session_id,
                "job_id": job_id,
                "file": row["filename"],
                "time": _now("%H:%M:%S"),
            })
            _event_logger.info(
                "job_removed_from_queue",
                extra={"session_id": session_id, "job_id": job_id, "filename": row["filename"]},
            )
            return {"ok": True, "action": "removed_from_queue", "job_id": job_id}

        if status == "encoding":
            # Per-file cancel without aborting the queue isn't supported by
            # the worker yet. Best we can do today: stop the whole session.
            session = get_active_session(conn)
            if not session or session["id"] != session_id:
                return JSONResponse(
                    {"ok": False, "error": "Job is encoding but its session is not active"},
                    status_code=409,
                )
            now = _now()
            update_session(conn, session_id, status="interrupted", updated_at=now)
            cancelled = cancel_pending_jobs(conn, session_id, now)
            append_event(session_id, {
                "type": "queue_stopped",
                "session_id": session_id,
                "cancelled": cancelled,
                "trigger": "per_job_cancel",
                "job_id": job_id,
                "time": _now("%H:%M:%S"),
            })
            _event_logger.warning(
                "job_cancel_triggered_session_stop",
                extra={"session_id": session_id, "job_id": job_id, "cancelled_jobs": cancelled},
            )
            return {"ok": True, "action": "session_stop", "job_id": job_id, "cancelled": cancelled}

        return JSONResponse(
            {"ok": False, "error": f"Job is in terminal status {status!r}; nothing to cancel"},
            status_code=409,
        )
    finally:
        conn.close()


@app.get("/api/encode/status")
async def encode_status():
    """Quick status check — used for navigation indicator."""
    conn = get_conn()
    try:
        session = get_active_session(conn)
        if not session:
            return {"running": False, "session_id": None}
        jobs = get_jobs(conn, session["id"])
    finally:
        conn.close()

    current = next((j for j in jobs if j["status"] == "encoding"), None)
    return {
        "running":     True,
        "session_id":  session["id"],
        "total":       session["total_files"],
        "done":        session["done_files"],
        "current_job": current,
    }


# ── Session state (used for restoring UI on page load) ───────────────────────
@app.get("/api/session/active")
async def session_active(
    jobs_limit: int = 500,
    jobs_offset: int = 0,
    events_limit: int = 200,
):
    """Returns the active session (or most recent) for UI restore.

    B-025: response is now *paginated*. With a 6k-job queue and a 200 MB
    JSONL, the legacy "send everything" version saturated the API and
    timed out the browser. Defaults below cap the payload at a few MB
    while still giving the UI everything it needs for the first render
    (queue head + recent activity + recent events). The UI fetches
    additional pages on demand.

    - ``jobs_limit`` / ``jobs_offset``: window into ``jobs`` ordered by id.
    - ``events_limit``: last N events from the JSONL (cheap tail read).
    - Response also carries ``total_jobs``, ``log_size`` (bytes) and
      ``events_offset`` so the UI can resume the WS stream incrementally.
    """
    conn = get_conn()
    try:
        session = get_active_session(conn)
        if not session:
            session = get_latest_session(conn)
        if not session:
            return {
                "session":       None,
                "jobs":          [],
                "events":        [],
                "total_jobs":    0,
                "log_size":      0,
                "events_offset": 0,
                "jobs_limit":    int(jobs_limit),
                "jobs_offset":   int(jobs_offset),
            }
        sid = session["id"]
        jobs = get_jobs_page(conn, sid, limit=jobs_limit, offset=jobs_offset)
        total_jobs = count_jobs(conn, sid)
    finally:
        conn.close()

    events, log_size = read_events_tail(sid, n=int(events_limit))
    return {
        "session":       session,
        "jobs":          jobs,
        "events":        events,
        "total_jobs":    total_jobs,
        "log_size":      log_size,
        "events_offset": log_size,
        "jobs_limit":    int(jobs_limit),
        "jobs_offset":   int(jobs_offset),
    }


@app.get("/api/session/active/jobs")
async def session_active_jobs(
    limit: int = 500,
    offset: int = 0,
    status: Optional[str] = None,
):
    """B-025: companion endpoint for lazy-loading jobs of the active session.

    Lets the UI fetch additional pages of the queue (e.g. when scrolling)
    without resending the whole session payload.
    """
    conn = get_conn()
    try:
        session = get_active_session(conn) or get_latest_session(conn)
        if not session:
            return {"jobs": [], "total": 0, "limit": int(limit), "offset": int(offset)}
        sid = session["id"]
        jobs = get_jobs_page(conn, sid, limit=limit, offset=offset, status=status)
        total = count_jobs(conn, sid, status=status)
    finally:
        conn.close()
    return {
        "jobs":   jobs,
        "total":  total,
        "limit":  int(limit),
        "offset": int(offset),
        "status": status,
    }


@app.get("/api/session/active/events")
async def session_active_events(after: int = 0, limit_bytes: int = 1048576):
    """B-025: tail-stream events written after ``after`` bytes.

    Used by the UI on WS reconnect to catch up on what it missed without
    re-fetching the entire session JSONL. ``limit_bytes`` caps the delta
    so even a pathological "missed everything" client doesn't OOM the API.
    """
    conn = get_conn()
    try:
        session = get_active_session(conn) or get_latest_session(conn)
    finally:
        conn.close()
    if not session:
        return {"events": [], "offset": int(after), "log_size": 0}
    events, new_offset = read_events_since(session["id"], int(after))
    # Apply byte cap (best-effort: trim from the start if the delta was huge).
    if limit_bytes > 0:
        size_estimate = sum(len(json.dumps(e)) for e in events)
        while events and size_estimate > limit_bytes:
            ev = events.pop(0)
            size_estimate -= len(json.dumps(ev))
    return {
        "events":   events,
        "offset":   new_offset,
        "log_size": log_file_size(session["id"]),
    }


# ── History ──────────────────────────────────────────────────────────────────
_HISTORY_SORT_COLUMNS = {
    "id", "filename", "original_size_mb", "final_size_mb", "space_saved_mb",
    "started_at", "completed_at", "encoder_used", "status",
}


@app.get("/api/history")
async def get_history(
    limit: int = 200,
    offset: int = 0,
    sort_by: str = "id",
    order: str = "desc",
    filter_encoder: Optional[str] = None,
    filter_status: Optional[str] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
):
    """M-008 paginated history + M-024 sort/filter.

    sort_by must be one of _HISTORY_SORT_COLUMNS to avoid SQL injection.
    order must be 'asc' or 'desc'.
    from_date / to_date filter on completed_at (ISO/string compare works for
    the existing 'YYYY-MM-DD HH:MM:SS' format).
    """
    limit  = max(1, min(int(limit), 1000))
    offset = max(0, int(offset))

    if sort_by not in _HISTORY_SORT_COLUMNS:
        sort_by = "id"
    order = "ASC" if order.lower() == "asc" else "DESC"

    where = []
    params: list = []
    if filter_encoder:
        where.append("encoder_used = ?")
        params.append(filter_encoder)
    if filter_status:
        where.append("status = ?")
        params.append(filter_status)
    if from_date:
        where.append("(completed_at >= ? OR started_at >= ?)")
        params.extend([from_date, from_date])
    if to_date:
        where.append("(completed_at <= ? OR started_at <= ?)")
        params.extend([to_date, to_date])
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""

    conn = get_conn()
    try:
        rows = conn.execute(
            f"SELECT * FROM jobs {where_sql} "
            f"ORDER BY {sort_by} {order} LIMIT ? OFFSET ?",
            (*params, limit, offset),
        ).fetchall()
        total = conn.execute(
            f"SELECT COUNT(*) AS c FROM jobs {where_sql}",
            tuple(params),
        ).fetchone()["c"]
        return {
            "records": [dict(r) for r in rows],
            "limit":   limit,
            "offset":  offset,
            "total":   total,
            "sort_by": sort_by,
            "order":   order.lower(),
            "filters": {
                "encoder": filter_encoder,
                "status":  filter_status,
                "from":    from_date,
                "to":      to_date,
            },
        }
    finally:
        conn.close()


# ── History export/import (M-024 + M-029 compat) ────────────────────────────
# v3.3: schema bumped to v2 to carry per-job metadata + events. v1 imports
# remain accepted for backward compatibility.
HISTORY_EXPORT_SCHEMA_VERSION = 2


def _parse_meta(raw):
    """Decode a JSON string stored in source_metadata/destination_metadata.
    Returns the original raw value if it doesn't look like JSON so legacy
    rows from v3.2 (NULL) survive without errors."""
    if raw is None:
        return None
    if isinstance(raw, (dict, list)):
        return raw
    try:
        import json as _json
        return _json.loads(raw)
    except Exception:
        return raw


@app.get("/api/history/export")
async def history_export():
    """
    Export every session + every job — and for each job, also include the
    full ffprobe metadata of the source and destination files, the exact
    ffmpeg command used, and the slice of session events that belongs to
    that job. The export is intentionally heavy because the user wants a
    complete forensic snapshot.

    Schema is backend-agnostic so the same payload can be imported into a
    Postgres-backed install.
    """
    conn = get_conn()
    try:
        sessions = conn.execute(
            "SELECT * FROM sessions ORDER BY created_at"
        ).fetchall()
        jobs = conn.execute("SELECT * FROM jobs ORDER BY id").fetchall()
    finally:
        conn.close()

    # Group session log events by session_id so each job can carry the slice
    # of events that mention its own job_id. Sessions log files live under
    # /data/logs/session_<id>.jsonl.
    events_by_session: dict[str, list] = {}
    for s in sessions:
        sid = s["id"]
        try:
            events_by_session[sid] = read_events(sid)
        except Exception:
            events_by_session[sid] = []

    jobs_out: list[dict] = []
    for j in jobs:
        d = dict(j)
        d["source_metadata"]      = _parse_meta(d.get("source_metadata"))
        d["destination_metadata"] = _parse_meta(d.get("destination_metadata"))
        sid = d.get("session_id")
        # Events for this specific job: any event whose job_id matches OR
        # any session-wide event timestamped between started_at and
        # completed_at. We keep the per-job slice strict (job_id match) so
        # the export size grows linearly with the work the file received.
        evs = events_by_session.get(sid, []) or []
        d["events"] = [e for e in evs if e.get("job_id") == d["id"]]
        jobs_out.append(d)

    return {
        "schema_version": HISTORY_EXPORT_SCHEMA_VERSION,
        "exported_at":    _now(),
        "sessions":       [dict(s) for s in sessions],
        "jobs":           jobs_out,
    }


def _job_dedupe_key(row: dict) -> tuple:
    return (row.get("original_path") or "", row.get("completed_at") or "")


@app.post("/api/history/import")
async def history_import(payload: dict):
    """
    Merge an exported history JSON into the live DB.

    Strategy:
      * Sessions: INSERT OR IGNORE keyed on session.id (sessions imported
        first so jobs can reference them).
      * Jobs: skip when a row with the same (original_path, completed_at)
        already exists — avoids duplicating on re-import.
      * Active sessions/jobs (running/queued/encoding) are never touched.
    """
    if not isinstance(payload, dict):
        return JSONResponse({"error": "Body must be a JSON object"}, status_code=400)

    version = payload.get("schema_version")
    if version not in (1, 2):
        return JSONResponse(
            {"error": f"Unsupported schema_version: {version}"},
            status_code=400,
        )

    sessions_in = payload.get("sessions") or []
    jobs_in     = payload.get("jobs") or []
    if not isinstance(sessions_in, list) or not isinstance(jobs_in, list):
        return JSONResponse({"error": "sessions/jobs must be arrays"}, status_code=400)

    conn = get_conn()
    try:
        # Pre-restore snapshot so the user can roll back if the merge is wrong
        try:
            backup_db(DB_PATH, label="pre-import")
        except Exception:
            pass

        # Index of existing job dedupe keys
        existing_rows = conn.execute(
            "SELECT original_path, completed_at FROM jobs"
        ).fetchall()
        existing = {(r["original_path"] or "", r["completed_at"] or "") for r in existing_rows}

        # M-029: portable INSERT ... DO NOTHING — SQLite supports "INSERT
        # OR IGNORE"; Postgres needs "INSERT ... ON CONFLICT (id) DO NOTHING".
        # Detect dialect via the SQLAlchemy engine that backs the connection.
        from app.db_engine import get_engine
        is_postgres = get_engine().dialect.name == "postgresql"
        if is_postgres:
            session_sql = (
                "INSERT INTO sessions "
                "(id, status, total_files, done_files, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT (id) DO NOTHING"
            )
        else:
            session_sql = (
                "INSERT OR IGNORE INTO sessions "
                "(id, status, total_files, done_files, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?)"
            )

        sessions_added = 0
        existing_session_ids = {
            r["id"] for r in conn.execute("SELECT id FROM sessions").fetchall()
        }
        for s in sessions_in:
            if not s.get("id") or s["id"] in existing_session_ids:
                continue
            try:
                conn.execute(session_sql, (
                    s["id"], s.get("status", "completed"),
                    int(s.get("total_files") or 0),
                    int(s.get("done_files") or 0),
                    s.get("created_at") or _now(),
                    s.get("updated_at"),
                ))
                existing_session_ids.add(s["id"])
                sessions_added += 1
            except Exception:
                continue

        jobs_added = 0
        skipped = 0
        for j in jobs_in:
            key = _job_dedupe_key(j)
            if key in existing:
                skipped += 1
                continue
            if j.get("status") in ("queued", "encoding"):
                # Never import in-flight jobs
                skipped += 1
                continue
            try:
                # v3.3: source_metadata/destination_metadata are stored as
                # JSON-encoded TEXT. The v2 export uses dicts directly; v1
                # exports won't carry these fields, so default to None.
                src_meta = j.get("source_metadata")
                dst_meta = j.get("destination_metadata")
                src_meta_txt = (
                    json.dumps(src_meta) if isinstance(src_meta, (dict, list))
                    else src_meta
                )
                dst_meta_txt = (
                    json.dumps(dst_meta) if isinstance(dst_meta, (dict, list))
                    else dst_meta
                )
                conn.execute("""
                    INSERT INTO jobs
                        (session_id, filename, original_path, original_size_mb,
                         final_size_mb, space_saved_mb, original_hash, encoded_hash,
                         crf_used, encoder_used, status, current_frame, total_frames,
                         pct, fps, speed, eta_s, error_msg, started_at, completed_at,
                         source_metadata, destination_metadata, ffmpeg_cmd)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                            ?, ?, ?)
                """, (
                    j.get("session_id") or "imported",
                    j.get("filename") or Path(j.get("original_path", "")).name,
                    j.get("original_path", ""),
                    j.get("original_size_mb"),
                    j.get("final_size_mb"),
                    j.get("space_saved_mb"),
                    j.get("original_hash"),
                    j.get("encoded_hash"),
                    j.get("crf_used"),
                    j.get("encoder_used"),
                    j.get("status") or "completed",
                    j.get("current_frame") or 0,
                    j.get("total_frames") or 0,
                    j.get("pct") or 0,
                    j.get("fps"),
                    j.get("speed"),
                    j.get("eta_s") or 0,
                    j.get("error_msg"),
                    j.get("started_at"),
                    j.get("completed_at"),
                    src_meta_txt,
                    dst_meta_txt,
                    j.get("ffmpeg_cmd"),
                ))
                existing.add(key)
                jobs_added += 1
            except Exception:
                skipped += 1
                continue
        conn.commit()
    finally:
        conn.close()

    return {
        "ok": True,
        "sessions_added": sessions_added,
        "jobs_added":     jobs_added,
        "jobs_skipped":   skipped,
    }


@app.get("/api/history/stats")
async def get_stats():
    conn = get_conn()
    try:
        row = conn.execute("""
            SELECT
                COUNT(*)                                       AS total,
                SUM(CASE WHEN status='completed' THEN 1 END)  AS completed,
                SUM(CASE WHEN status='failed'    THEN 1 END)  AS failed,
                SUM(CASE WHEN status='skipped'   THEN 1 END)  AS skipped,
                COALESCE(SUM(space_saved_mb), 0)              AS total_saved_mb
            FROM jobs
        """).fetchone()
    finally:
        conn.close()
    return dict(row)


@app.get("/api/history/encoded-paths")
async def encoded_paths():
    """For UI: which paths in scan results have already been encoded."""
    conn = get_conn()
    try:
        return {"paths": list(get_encoded_paths(conn))}
    finally:
        conn.close()


@app.delete("/api/history/{record_id}")
@app.post("/api/history/{record_id}/delete")
async def delete_history(record_id: int):
    """Delete a single history record. Refuses if job is still active."""
    conn = get_conn()
    try:
        row = conn.execute("SELECT status FROM jobs WHERE id = ?",
                           (record_id,)).fetchone()
        if row is None:
            return JSONResponse({"error": "Record not found"}, status_code=404)
        if row["status"] in ("queued", "encoding"):
            return JSONResponse(
                {"error": "Cannot delete an active job. Stop the encode first."},
                status_code=409
            )
        conn.execute("DELETE FROM jobs WHERE id = ?", (record_id,))
        conn.commit()
    finally:
        conn.close()
    return {"ok": True}


@app.post("/api/history/bulk-delete")
async def bulk_delete(payload: dict):
    """Delete multiple history records at once. Skips active jobs."""
    ids = payload.get("ids", [])
    if not ids:
        return {"ok": True, "deleted": 0}

    conn = get_conn()
    try:
        placeholders = ",".join("?" * len(ids))
        # Count active jobs that would be skipped
        skipped_rows = conn.execute(
            f"SELECT id FROM jobs WHERE id IN ({placeholders}) "
            f"AND status IN ('queued','encoding')",
            ids
        ).fetchall()
        skipped = [r["id"] for r in skipped_rows]
        deletable = [i for i in ids if i not in skipped]

        if deletable:
            placeholders2 = ",".join("?" * len(deletable))
            conn.execute(
                f"DELETE FROM jobs WHERE id IN ({placeholders2})",
                deletable
            )
            conn.commit()
    finally:
        conn.close()

    return {"ok": True, "deleted": len(deletable), "skipped": skipped}


# ── HDD ──────────────────────────────────────────────────────────────────────
@app.get("/api/hdd/status")
async def hdd_status():
    config    = cfg.load()
    temp_path = config.get("hdd_temp_path", "/mnt/hdd/reencoder-temp")
    hdd_mount = "/mnt/hdd"

    files = []
    total_bytes = 0
    if os.path.exists(temp_path):
        for entry in os.scandir(temp_path):
            if entry.is_file():
                size = entry.stat().st_size
                total_bytes += size
                files.append({
                    "name": entry.name,
                    "size_mb": round(size / 1048576, 1),
                    "path": entry.path,
                })
        files.sort(key=lambda f: f["name"])

    disk = {"total_gb": 0, "used_gb": 0, "free_gb": 0}
    try:
        usage = shutil.disk_usage(hdd_mount)
        disk = {
            "total_gb": round(usage.total / 1073741824, 1),
            "used_gb":  round(usage.used  / 1073741824, 1),
            "free_gb":  round(usage.free  / 1073741824, 1),
        }
    except Exception:
        pass

    return {
        "temp_path": temp_path,
        "files": files,
        "total_mb": round(total_bytes / 1048576, 1),
        "disk": disk,
    }


@app.post("/api/hdd/clean")
async def hdd_clean():
    conn = get_conn()
    try:
        if get_active_session(conn):
            return JSONResponse(
                {"error": "Cannot clean while encode is running"},
                status_code=409
            )
    finally:
        conn.close()

    config    = cfg.load()
    temp_path = config.get("hdd_temp_path", "/mnt/hdd/reencoder-temp")
    deleted, errors = [], []
    if os.path.exists(temp_path):
        for entry in os.scandir(temp_path):
            if entry.is_file():
                try:
                    os.remove(entry.path)
                    deleted.append(entry.name)
                except Exception as e:
                    errors.append({"file": entry.name, "error": str(e)})
    return {"deleted": deleted, "errors": errors, "ok": len(errors) == 0}


# ── Job logs (M-024b / M-030 / M-031) ────────────────────────────────────────
@app.get("/api/jobs/{job_id}/logs")
async def job_logs(job_id: int, q: Optional[str] = None):
    """
    Return the slice of the session JSONL that belongs to this job, plus the
    job row itself. ``q`` filters events by case-insensitive substring on the
    JSON-stringified event (so users can search for filenames, error
    fragments, etc.).
    """
    conn = get_conn()
    try:
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    finally:
        conn.close()
    if row is None:
        return JSONResponse({"error": "Job not found"}, status_code=404)
    job = dict(row)
    # v3.3: decode JSON-stored metadata so the UI gets dicts, not strings.
    job["source_metadata"]      = _parse_meta(job.get("source_metadata"))
    job["destination_metadata"] = _parse_meta(job.get("destination_metadata"))
    sid = job["session_id"]
    all_events = read_events(sid)

    # An event is "this job's" when it carries job_id == job_id OR it's a
    # session-level event timestamped between started_at and completed_at.
    def belongs(ev):
        if ev.get("job_id") == job_id:
            return True
        return False
    events = [e for e in all_events if belongs(e)]

    if q:
        needle = q.lower()
        events = [e for e in events if needle in str(e).lower()]

    return {"job": job, "events": events, "count": len(events)}


@app.get("/api/jobs/{job_id}/logs/export")
async def job_logs_export(job_id: int, fmt: str = "json"):
    """Export the job's log slice as JSON (default) or text lines."""
    data = await job_logs(job_id)
    if isinstance(data, JSONResponse):
        return data
    if fmt == "text":
        lines = []
        for ev in data["events"]:
            t = ev.get("time", "")
            typ = ev.get("type", "?")
            extras = " ".join(f"{k}={v}" for k, v in ev.items() if k not in ("time", "type"))
            lines.append(f"[{t}] {typ:<14} {extras}")
        return JSONResponse(content={"text": "\n".join(lines), "job_id": job_id})
    return data


# ── DB Backup / Restore (B-017) ──────────────────────────────────────────────
@app.get("/api/db/state")
async def db_state():
    """B-017 + M-029: state observed at startup + active backend."""
    return {
        **_DB_STATE,
        "live_has_history": db_has_history(DB_PATH),
        "db_path": str(DB_PATH),
        "backend_active":    active_backend(),
        "backend_requested": configured_backend(),
    }


@app.get("/api/db/backups")
async def db_list_backups():
    return {"backups": list_backups()}


@app.post("/api/db/backup")
async def db_backup(payload: Optional[dict] = None):
    """Take a manual snapshot. Optional ``{"label": "before-xyz"}``."""
    label = (payload or {}).get("label", "manual")
    snap = backup_db(DB_PATH, label=label)
    if snap is None:
        return JSONResponse({"error": "DB does not exist yet"}, status_code=400)
    return {"ok": True, "snapshot": str(snap)}


@app.post("/api/db/restore")
async def db_restore(payload: dict):
    """
    Restore the live DB from a named backup. Refuses if an encode is active —
    the restore overwrites jobs that the worker is currently mutating.

    Body: ``{"name": "reencoder-startup-20260517T120000Z.db"}``
    """
    name = (payload or {}).get("name")
    if not name:
        return JSONResponse({"error": "name is required"}, status_code=400)

    # No active session check: restoring during an encode would corrupt the
    # worker's view of the world.
    conn = get_conn()
    try:
        if get_active_session(conn):
            return JSONResponse(
                {"error": "Cannot restore while an encode is running"},
                status_code=409,
            )
    finally:
        conn.close()

    candidate = backups_dir() / name
    try:
        result = restore_backup(candidate, db_path=DB_PATH)
    except FileNotFoundError:
        return JSONResponse({"error": f"Backup not found: {name}"}, status_code=404)
    except (PermissionError, ValueError) as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    return {"ok": True, **result}


# ── WebSocket ────────────────────────────────────────────────────────────────
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    _ws_clients.add(websocket)
    try:
        while True:
            # We don't receive anything from the client; just keep alive
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        _ws_clients.discard(websocket)


async def _broadcast(event: dict):
    dead = set()
    # B-011: iterate over a snapshot so a concurrent connect/disconnect
    # doesn't trigger "Set changed size during iteration".
    for ws in list(_ws_clients):
        try:
            await ws.send_json(event)
        except Exception:
            dead.add(ws)
    _ws_clients.difference_update(dead)


# ── Event broadcaster ────────────────────────────────────────────────────────
async def _event_broadcaster():
    """Background task: tail the active session's event log and forward
    newly-appended events to all connected WebSocket clients.

    B-025: tracks the **byte offset** into the JSONL instead of an item
    count, and uses ``read_events_since`` which seeks straight to that
    offset. The legacy version read the whole JSONL each tick, which on a
    24-hour session with 100k+ events meant tens of MB of disk + parse
    work *per second*. New cost is proportional to the delta written in
    the last tick — typically a few KB regardless of session age.

    Resets the offset when the active session changes.
    """
    last_session_id: Optional[str] = None
    last_offset:     int = 0

    while True:
        await asyncio.sleep(1)
        try:
            conn = get_conn()
            try:
                session = get_active_session(conn) or get_latest_session(conn)
            finally:
                conn.close()

            if not session:
                last_session_id = None
                last_offset = 0
                continue

            sid = session["id"]
            if sid != last_session_id:
                # New session: start from the *current* end so we don't
                # replay history events to clients that just connected.
                # The UI gets a snapshot via /api/session/active anyway.
                last_session_id = sid
                last_offset = log_file_size(sid)

            events, last_offset = read_events_since(sid, last_offset)
            for ev in events:
                await _broadcast(ev)
        except Exception:
            # B-008: don't kill the broadcaster on transient errors,
            # but at least log the traceback so silent failures surface.
            import sys, traceback
            print("[broadcaster] error:", file=sys.stderr)
            traceback.print_exc()


# ── Help / Manual (M-025) ────────────────────────────────────────────────────
@app.get("/api/help")
async def get_help(lang: str = "en"):
    return _get_help(lang)


@app.get("/api/health")
async def health():
    """Simple liveness probe."""
    return {"ok": True, "ts": _now()}


# ── v3.5: Roadmap (YAML-backed) ──────────────────────────────────────────────
@app.get("/api/roadmap")
async def get_roadmap():
    """Combined bugs/improvements/features served from /app/roadmap/*.yaml."""
    return _load_roadmap()


# ── v3.5: Admin Logs (in-memory ring + SSE stream) ───────────────────────────
@app.get("/api/admin/logs/recent")
async def admin_logs_recent(limit: int = 2000):
    return _admin_logs.recent(limit=limit)


@app.get("/api/admin/logs/stream")
async def admin_logs_stream(request: Request):
    """Server-Sent Events stream of structured log entries.

    The browser uses `EventSource` (Admin Logs page) to consume this. We
    detect client disconnection through `Request.is_disconnected()` so a
    closed tab doesn't keep the subscriber queue alive forever.
    """
    queue = _admin_logs.subscribe()

    async def event_gen():
        try:
            # Initial comment line so EventSource opens immediately.
            yield _admin_logs.heartbeat_payload()
            while True:
                if await request.is_disconnected():
                    break
                try:
                    entry = await asyncio.wait_for(queue.get(), timeout=15.0)
                    yield f"data: {json.dumps(entry)}\n\n"
                except asyncio.TimeoutError:
                    # Heartbeat to keep proxies from closing the connection.
                    yield _admin_logs.heartbeat_payload()
        finally:
            _admin_logs.unsubscribe(queue)

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # disables nginx response buffering
        },
    )
