"""Tests for database operations — both API and Worker copies."""
import json
from datetime import datetime


def test_create_session_and_jobs(tmp_data_dir):
    from app.database import (
        get_conn, create_session, create_job, get_session,
        get_jobs, count_done_jobs
    )
    conn = get_conn()
    try:
        create_session(conn, "s1", 2, "2026-01-01 00:00:00")
        s = get_session(conn, "s1")
        assert s["status"] == "running"
        assert s["total_files"] == 2

        j1 = create_job(conn, "s1", "a.mkv", "/x/a.mkv", 100.0, 26, "cpu", "2026-01-01 00:00:00")
        j2 = create_job(conn, "s1", "b.mkv", "/x/b.mkv", 200.0, 26, "cpu", "2026-01-01 00:00:00")

        jobs = get_jobs(conn, "s1")
        assert len(jobs) == 2
        assert all(j["status"] == "queued" for j in jobs)

        assert count_done_jobs(conn, "s1") == 0
    finally:
        conn.close()


def test_get_active_session_requires_pending_jobs(tmp_data_dir):
    """A session with status=running but no queued/encoding jobs is NOT active."""
    from app.database import (
        get_conn, create_session, create_job, get_active_session, update_job
    )
    conn = get_conn()
    try:
        create_session(conn, "s1", 1, "2026-01-01 00:00:00")
        # No jobs yet
        assert get_active_session(conn) is None

        j1 = create_job(conn, "s1", "a.mkv", "/x/a.mkv", 100.0, 26, "cpu", "2026-01-01 00:00:00")
        # Now active
        assert get_active_session(conn)["id"] == "s1"

        # Mark job as completed — no more pending work
        update_job(conn, j1, status="completed")
        assert get_active_session(conn) is None
    finally:
        conn.close()


def test_is_session_interrupted(tmp_data_dir):
    from app.database import (
        get_conn, create_session, update_session, is_session_interrupted
    )
    conn = get_conn()
    try:
        create_session(conn, "s1", 1, "2026-01-01 00:00:00")
        assert not is_session_interrupted(conn, "s1")

        update_session(conn, "s1", status="interrupted")
        assert is_session_interrupted(conn, "s1")
    finally:
        conn.close()


def test_cancel_pending_jobs(tmp_data_dir):
    from app.database import (
        get_conn, create_session, create_job, cancel_pending_jobs,
        get_jobs, update_job
    )
    conn = get_conn()
    try:
        create_session(conn, "s1", 3, "2026-01-01 00:00:00")
        j1 = create_job(conn, "s1", "a.mkv", "/x/a.mkv", 100.0, 26, "cpu", "2026-01-01 00:00:00")
        j2 = create_job(conn, "s1", "b.mkv", "/x/b.mkv", 100.0, 26, "cpu", "2026-01-01 00:00:00")
        j3 = create_job(conn, "s1", "c.mkv", "/x/c.mkv", 100.0, 26, "cpu", "2026-01-01 00:00:00")

        # Mark j2 as encoding (currently in progress)
        update_job(conn, j2, status="encoding")
        # Mark j3 as completed (already done)
        update_job(conn, j3, status="completed")

        # Cancel: should affect j1 (queued) + j2 (encoding), but NOT j3 (completed)
        n = cancel_pending_jobs(conn, "s1", "2026-01-01 01:00:00")
        assert n == 2

        jobs = {j["id"]: j["status"] for j in get_jobs(conn, "s1")}
        assert jobs[j1] == "interrupted"
        assert jobs[j2] == "interrupted"
        assert jobs[j3] == "completed"
    finally:
        conn.close()


def test_recover_stale_jobs(tmp_data_dir):
    """If worker crashes leaving jobs as 'encoding', recover them on startup."""
    from app.database import (
        get_conn, create_session, create_job, update_job,
        recover_stale_jobs, get_jobs
    )
    conn = get_conn()
    try:
        create_session(conn, "s1", 2, "2026-01-01 00:00:00")
        j1 = create_job(conn, "s1", "a.mkv", "/x/a.mkv", 100.0, 26, "cpu", "2026-01-01 00:00:00")
        j2 = create_job(conn, "s1", "b.mkv", "/x/b.mkv", 100.0, 26, "cpu", "2026-01-01 00:00:00")
        # Simulate crash mid-encode
        update_job(conn, j1, status="encoding")

        n = recover_stale_jobs(conn, "2026-01-01 01:00:00")
        assert n == 1

        jobs = {j["id"]: j["status"] for j in get_jobs(conn, "s1")}
        assert jobs[j1] == "failed"
        assert jobs[j2] == "queued"  # Untouched
    finally:
        conn.close()


def test_event_log_persistence(tmp_data_dir):
    from app.database import append_event, read_events, LOGS_DIR
    append_event("sX", {"type": "step", "msg": "hello"})
    append_event("sX", {"type": "step", "msg": "world"})

    events = read_events("sX")
    assert len(events) == 2
    assert events[0]["msg"] == "hello"
    assert events[1]["msg"] == "world"


def test_scan_results_persistence(tmp_data_dir):
    from app.database import get_conn, save_scan, load_scan
    conn = get_conn()
    try:
        files = [
            {"path": "/a.mkv", "filename": "a.mkv", "size_mb": 100.0, "folder": "/x", "selected": True},
            {"path": "/b.mkv", "filename": "b.mkv", "size_mb": 200.0, "folder": "/x", "selected": True},
        ]
        save_scan(conn, files, "2026-01-01 00:00:00")

        loaded, ts = load_scan(conn)
        assert len(loaded) == 2
        assert loaded[0]["path"] == "/a.mkv"
        assert ts == "2026-01-01 00:00:00"

        # Save again — should replace, not append
        save_scan(conn, [files[0]], "2026-01-02 00:00:00")
        loaded, ts = load_scan(conn)
        assert len(loaded) == 1
    finally:
        conn.close()


def test_encoded_paths(tmp_data_dir):
    from app.database import (
        get_conn, create_session, create_job, update_job, get_encoded_paths
    )
    conn = get_conn()
    try:
        create_session(conn, "s1", 3, "2026-01-01 00:00:00")
        j1 = create_job(conn, "s1", "a.mkv", "/x/a.mkv", 100.0, 26, "cpu", "2026-01-01 00:00:00")
        j2 = create_job(conn, "s1", "b.mkv", "/x/b.mkv", 100.0, 26, "cpu", "2026-01-01 00:00:00")
        j3 = create_job(conn, "s1", "c.mkv", "/x/c.mkv", 100.0, 26, "cpu", "2026-01-01 00:00:00")

        update_job(conn, j1, status="completed")
        update_job(conn, j2, status="failed")
        # j3 stays queued

        paths = get_encoded_paths(conn)
        assert paths == {"/x/a.mkv"}
    finally:
        conn.close()
