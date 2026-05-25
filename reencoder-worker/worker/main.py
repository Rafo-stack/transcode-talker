"""
Worker — independent process that consumes encode jobs.

Responsibilities:
  1. Recover stale jobs on startup (if worker crashed mid-encode)
  2. Poll DB for active sessions
  3. For each session, process queued jobs in order
  4. Detect Stop requests via DB polling (session.status = 'interrupted')
  5. Update DB and emit events for UI consumption

Why DB polling for stop?
  The worker and API are separate processes. They share state via the SQLite
  DB. When the user clicks Stop in the UI, the API marks the session as
  'interrupted' in the DB. The worker checks this status during the encode
  loop (via the stop_check callback) and exits cleanly.

Survives:
  - Browser closing (worker doesn't care about UI)
  - API restart (worker keeps processing)
  - Worker restart (stale jobs recovered, then continues)
"""

import json
import logging
import os
import signal
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


# M-006: structured logging — replaces ad-hoc print() so log aggregators can
# filter/grep by level and source. Keep the [worker] prefix for grep continuity.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [worker] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger("worker")

from worker.database import (
    get_conn, get_active_session, get_jobs,
    update_job, update_session, append_event,
    is_session_interrupted, count_done_jobs,
    cancel_pending_jobs, recover_stale_jobs,
    cleanup_old_logs,
)
from worker.db_backend import active_backend, configured_backend
from worker.encoder import encode_file


# B-007/M-002: timezone configurable via TZ env var (default America/New_York)
_TZ         = ZoneInfo(os.environ.get("TZ", "America/New_York"))
CONFIG_PATH = Path("/data/config.json")
SHUTDOWN    = [False]   # Set by SIGTERM/SIGINT for clean shutdown


def _now(fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
    return datetime.now(_TZ).strftime(fmt)


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        return {}
    try:
        return json.loads(CONFIG_PATH.read_text())
    except Exception:
        return {}


# ── Signal handling ──────────────────────────────────────────────────────────
def handle_signal(sig, frame):
    log.info("Signal %s — graceful shutdown initiated", sig)
    SHUTDOWN[0] = True


signal.signal(signal.SIGINT,  handle_signal)
signal.signal(signal.SIGTERM, handle_signal)


# ── Stop detection ───────────────────────────────────────────────────────────
_STOP_CACHE_TTL = 2.0  # seconds — see B-014

def make_stop_check(session_id: str):
    """
    Returns a callable that checks if the encode should stop.

    The encoder calls this every 0.5s during the progress loop. To avoid
    hammering the DB (~7200 connections/hour during a 1h encode — B-014),
    we cache the negative answer for up to _STOP_CACHE_TTL seconds. A true
    answer is always returned immediately and never cached — the worker
    must react to Stop as fast as possible.
    """
    state = {"last_check": 0.0, "interrupted": False}

    def check():
        if SHUTDOWN[0]:
            return True
        now = time.time()
        if state["interrupted"]:
            return True
        if now - state["last_check"] < _STOP_CACHE_TTL:
            return False
        state["last_check"] = now
        try:
            conn = get_conn()
            try:
                v = is_session_interrupted(conn, session_id)
            finally:
                conn.close()
            state["interrupted"] = bool(v)
            return state["interrupted"]
        except Exception:
            return False
    return check


# ── Session processing ───────────────────────────────────────────────────────
def _fetch_session_total(session_id: str) -> int:
    """B-012: read the authoritative total_files from the DB to avoid using a
    stale snapshot when emitting events."""
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT total_files FROM sessions WHERE id = ?", (session_id,)
        ).fetchone()
        return int(row["total_files"]) if row else 0
    finally:
        conn.close()


def process_session(session: dict):
    """Process all queued jobs for a session. Returns when done or stopped."""
    session_id = session["id"]
    config     = load_config()
    stop_check = make_stop_check(session_id)

    log.info("Processing session %s", session_id)
    append_event(session_id, {
        "type": "queue_start",
        "session_id": session_id,
        "total": _fetch_session_total(session_id),
        "time": _now("%H:%M:%S"),
    })

    while not SHUTDOWN[0]:
        # Re-fetch session each iteration to catch Stop requests
        conn = get_conn()
        try:
            if is_session_interrupted(conn, session_id):
                log.info("Session %s interrupted by user", session_id)
                cancel_pending_jobs(conn, session_id, _now())
                append_event(session_id, {
                    "type": "queue_stopped",
                    "session_id": session_id,
                    "time": _now("%H:%M:%S"),
                })
                return

            # Get next queued job
            row = conn.execute("""
                SELECT * FROM jobs
                WHERE session_id = ? AND status = 'queued'
                ORDER BY id LIMIT 1
            """, (session_id,)).fetchone()

            if row is None:
                # No more queued jobs — mark session done
                update_session(conn, session_id,
                    status="completed", updated_at=_now())
                append_event(session_id, {
                    "type": "queue_done",
                    "session_id": session_id,
                    "time": _now("%H:%M:%S"),
                })
                log.info("Session %s complete", session_id)
                return

            job = dict(row)
        finally:
            conn.close()

        job_id   = job["id"]
        src_path = job["original_path"]
        fname    = job["filename"]

        # Mark as encoding
        conn = get_conn()
        try:
            update_job(conn, job_id, status="encoding", started_at=_now())
            done = count_done_jobs(conn, session_id)
            update_session(conn, session_id, done_files=done, updated_at=_now())
        finally:
            conn.close()

        append_event(session_id, {
            "type": "file_start",
            "job_id": job_id,
            "session_id": session_id,
            "file": fname,
            "idx": done + 1,
            "total": _fetch_session_total(session_id),
            "time": _now("%H:%M:%S"),
        })
        log.info("Encoding [%d]: %s", job_id, fname)

        # Run the actual encode
        result = encode_file(job_id, session_id, src_path, config, stop_check)

        # Persist result
        completed_at = _now()
        conn = get_conn()
        try:
            update_job(conn, job_id,
                status=result["status"],
                final_size_mb=result["final_size_mb"],
                space_saved_mb=result["space_saved_mb"],
                original_hash=result["original_hash"],
                encoded_hash=result["encoded_hash"],
                error_msg=result["error_msg"],
                completed_at=completed_at)
            done = count_done_jobs(conn, session_id)
            update_session(conn, session_id, done_files=done, updated_at=completed_at)
        finally:
            conn.close()

        append_event(session_id, {
            "type": "file_done",
            "job_id": job_id,
            "session_id": session_id,
            "file": fname,
            "status": result["status"],
            "space_saved_mb": result["space_saved_mb"],
            "time": _now("%H:%M:%S"),
        })
        log.info("%s -> %s", fname, result["status"])

        # If user stopped during this file, exit immediately
        if result["status"] == "interrupted":
            conn = get_conn()
            try:
                cancel_pending_jobs(conn, session_id, _now())
                update_session(conn, session_id,
                    status="interrupted", updated_at=_now())
            finally:
                conn.close()
            append_event(session_id, {
                "type": "queue_stopped",
                "session_id": session_id,
                "time": _now("%H:%M:%S"),
            })
            return


# ── Main loop ────────────────────────────────────────────────────────────────
def main():
    log.info("Starting")

    # v3.4: log which DB backend is in use for parity with the API. Helps
    # diagnose situations where the worker connects to a different DB than
    # the API (e.g. accidentally pointing to SQLite when Postgres was
    # expected). Tolerates connection failures gracefully — get_conn() will
    # retry on next poll cycle.
    backend = active_backend()
    requested = configured_backend()
    if requested != backend:
        log.warning("DB_BACKEND=%r requested → falling back to %r", requested, backend)
    else:
        log.info("DB backend: %s", backend)

    # Recover stale jobs from previous worker crash. v3.4: wrap in retry
    # because the Postgres healthcheck only guarantees pg_isready — there
    # is still a small window where the API initialised the schema and the
    # worker tries to read before the table cache is hot.
    for attempt in range(10):
        try:
            conn = get_conn()
            try:
                recovered = recover_stale_jobs(conn, _now())
                if recovered:
                    log.warning("Recovered %d stale job(s) from previous crash", recovered)
            finally:
                conn.close()
            break
        except Exception as e:
            log.warning("DB not ready (attempt %d/10): %s", attempt + 1, e)
            if SHUTDOWN[0]:
                return
            time.sleep(2)
    else:
        log.error("Could not connect to DB after 10 attempts — exiting")
        return

    # B-009/M-001: prune old session logs at startup
    try:
        deleted = cleanup_old_logs(max_age_days=30)
        if deleted:
            log.info("Pruned %d session log(s) older than 30 days", deleted)
    except Exception as e:
        log.error("Log cleanup failed: %s", e)

    log.info("Polling for active sessions every 2s")

    # M-005: docker healthcheck watches the mtime of this file.
    heartbeat = Path("/data/.worker_heartbeat")

    while not SHUTDOWN[0]:
        try:
            # Refresh heartbeat each loop iteration
            try:
                heartbeat.touch(exist_ok=True)
            except OSError:
                pass

            conn = get_conn()
            try:
                session = get_active_session(conn)
            finally:
                conn.close()

            if session:
                process_session(session)
        except Exception as e:
            log.exception("Error in main loop: %s", e)

        # Idle delay between polls
        for _ in range(20):  # 2s total, but check shutdown every 100ms
            if SHUTDOWN[0]:
                break
            time.sleep(0.1)

    log.info("Stopped")


if __name__ == "__main__":
    main()
