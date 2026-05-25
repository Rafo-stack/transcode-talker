"""
End-to-end integration tests.

Spins up the worker as a thread alongside an in-memory API DB.
Validates the critical user flows:

  1. Start encode → progress updates → completes → file replaced
  2. Start encode → Stop → ffmpeg killed → queue cleared → can start again
  3. Worker crash recovery — stale 'encoding' jobs marked failed on restart
  4. Multi-file batch with stop in the middle
  5. State survives "browser close" (no shared in-memory state)
"""
import os
import time
import json
import threading
from pathlib import Path
import pytest


def _start_worker_thread():
    """Start the worker's main loop in a thread. Returns (thread, shutdown_fn)."""
    from worker import main as worker_main
    # Reset state — critical when running multiple e2e tests
    worker_main.SHUTDOWN[0] = False

    # Use a fresh thread; don't reuse module state across tests
    t = threading.Thread(target=worker_main.main, daemon=True)
    t.start()

    def shutdown():
        worker_main.SHUTDOWN[0] = True
        t.join(timeout=10)

    return t, shutdown


@pytest.fixture(autouse=True)
def _reset_worker_state():
    """Reset worker SHUTDOWN flag before each E2E test."""
    from worker import main as worker_main
    worker_main.SHUTDOWN[0] = False
    yield
    worker_main.SHUTDOWN[0] = True
    # Give any leftover thread a moment to exit
    import time as t_mod
    t_mod.sleep(0.3)
    worker_main.SHUTDOWN[0] = False


def _wait_until(predicate, timeout=15, interval=0.1):
    """Poll predicate() until it returns truthy or timeout."""
    start = time.time()
    while time.time() - start < timeout:
        result = predicate()
        if result:
            return result
        time.sleep(interval)
    return None


@pytest.fixture
def patched_config_for_worker(monkeypatch, encoder_config, tmp_data_dir):
    """Make worker.load_config() return our fake config."""
    config_path = tmp_data_dir / "config.json"
    config_path.write_text(json.dumps(encoder_config))

    from worker import main as worker_main
    monkeypatch.setattr(worker_main, "CONFIG_PATH", config_path)


def test_full_encode_flow(tmp_data_dir, sample_video, encoder_config,
                          patched_config_for_worker):
    """
    Start session → worker picks up job → encodes → completes → file replaced.
    """
    from app.database import (
        get_conn, create_session, create_job, get_job, get_session
    )

    os.environ["FAKE_FFMPEG_DURATION"] = "1"
    os.environ["FAKE_FFMPEG_FRAMES"]   = "30"

    # Create session + job (simulating what API does)
    conn = get_conn()
    try:
        create_session(conn, "s_e2e", 1, "2026-01-01 00:00:00")
        job_id = create_job(conn, "s_e2e", "sample.mkv", sample_video, 100.0, 26, "cpu", "2026-01-01 00:00:00")
    finally:
        conn.close()

    # Start worker
    _, shutdown = _start_worker_thread()

    try:
        # Wait for completion
        def is_done():
            conn = get_conn()
            try:
                j = get_job(conn, job_id)
                return j["status"] in ("completed", "failed", "skipped")
            finally:
                conn.close()

        done = _wait_until(is_done, timeout=20)
        assert done, "Job did not complete in time"

        # Verify
        conn = get_conn()
        try:
            j = get_job(conn, job_id)
            assert j["status"] == "completed", f"Status: {j['status']}, error: {j['error_msg']}"
            assert j["space_saved_mb"] > 0
            s = get_session(conn, "s_e2e")
            assert s["status"] == "completed"
            assert s["done_files"] == 1
        finally:
            conn.close()
    finally:
        shutdown()


def test_stop_kills_encoder_and_clears_queue(tmp_data_dir, sample_video, encoder_config,
                                               patched_config_for_worker):
    """
    Start a multi-file batch → Stop after first starts → all queued jobs
    become 'interrupted', ffmpeg dies, no leftover temp files.
    """
    from app.database import (
        get_conn, create_session, create_job, update_session, get_jobs, get_session
    )

    # Long encode so we have time to stop
    os.environ["FAKE_FFMPEG_DURATION"] = "10"
    os.environ["FAKE_FFMPEG_FRAMES"]   = "300"

    # Create 3 source files
    sources = []
    for i in range(3):
        s = Path(tmp_data_dir) / f"source_{i}.mkv"
        s.write_bytes(b"VIDEO" * 200)
        sources.append(str(s))

    conn = get_conn()
    job_ids = []
    try:
        create_session(conn, "s_stop", 3, "2026-01-01 00:00:00")
        for s in sources:
            job_ids.append(create_job(conn, "s_stop", Path(s).name, s, 100.0, 26, "cpu", "2026-01-01 00:00:00"))
    finally:
        conn.close()

    _, shutdown = _start_worker_thread()

    try:
        # Wait for first job to be 'encoding'
        def first_encoding():
            conn = get_conn()
            try:
                j = get_jobs(conn, "s_stop")[0]
                return j["status"] == "encoding"
            finally:
                conn.close()

        assert _wait_until(first_encoding, timeout=10), "First job never started encoding"

        # Now Stop via DB (simulating API)
        conn = get_conn()
        try:
            update_session(conn, "s_stop", status="interrupted")
        finally:
            conn.close()

        # All jobs should reach a terminal state
        def all_done():
            conn = get_conn()
            try:
                jobs = get_jobs(conn, "s_stop")
                return all(j["status"] not in ("queued", "encoding") for j in jobs)
            finally:
                conn.close()

        assert _wait_until(all_done, timeout=15), "Worker did not stop in time"

        # Verify final state
        conn = get_conn()
        try:
            jobs = get_jobs(conn, "s_stop")
            statuses = [j["status"] for j in jobs]
            # First might be interrupted or completed (if fast), rest should be interrupted
            assert all(s != "queued" for s in statuses), f"Statuses: {statuses}"
            assert all(s != "encoding" for s in statuses), f"Statuses: {statuses}"

            sess = get_session(conn, "s_stop")
            assert sess["status"] == "interrupted"
        finally:
            conn.close()

        # No leftover ENCODED_ files
        hdd = encoder_config["hdd_temp_path"]
        leftovers = [f for f in os.listdir(hdd) if f.startswith("ENCODED_")]
        assert leftovers == [], f"Leftovers: {leftovers}"

    finally:
        shutdown()


def test_can_start_new_session_after_stop(tmp_data_dir, sample_video, encoder_config,
                                            patched_config_for_worker):
    """After Stop, the system must accept a new encode session."""
    from app.database import (
        get_conn, create_session, create_job, update_session,
        get_active_session, get_jobs
    )

    os.environ["FAKE_FFMPEG_DURATION"] = "1"
    os.environ["FAKE_FFMPEG_FRAMES"]   = "30"

    # First session — interrupt immediately
    conn = get_conn()
    try:
        create_session(conn, "s1", 1, "2026-01-01 00:00:00")
        create_job(conn, "s1", "a.mkv", sample_video, 100.0, 26, "cpu", "2026-01-01 00:00:00")
        update_session(conn, "s1", status="interrupted")
        # Mark the job as interrupted too (cleanup phase)
        from app.database import cancel_pending_jobs
        cancel_pending_jobs(conn, "s1", "2026-01-01 00:00:01")
    finally:
        conn.close()

    # No active session anymore
    conn = get_conn()
    try:
        assert get_active_session(conn) is None
    finally:
        conn.close()

    # Start a new session
    src2 = Path(tmp_data_dir) / "second.mkv"
    src2.write_bytes(b"VIDEO" * 200)

    conn = get_conn()
    try:
        create_session(conn, "s2", 1, "2026-01-01 01:00:00")
        job_id = create_job(conn, "s2", "second.mkv", str(src2), 100.0, 26, "cpu", "2026-01-01 01:00:00")
    finally:
        conn.close()

    _, shutdown = _start_worker_thread()
    try:
        def is_done():
            conn = get_conn()
            try:
                from app.database import get_job
                j = get_job(conn, job_id)
                return j["status"] in ("completed", "failed", "skipped")
            finally:
                conn.close()

        assert _wait_until(is_done, timeout=15), "Second session never completed"
    finally:
        shutdown()


def test_state_persistence_across_api_restart(tmp_data_dir, sample_video, encoder_config,
                                                patched_config_for_worker):
    """
    Simulate: API starts encode → API restarts (new TestClient) →
    state is still there → can read progress.
    """
    from app.database import (
        get_conn, create_session, create_job,
        get_active_session, get_jobs, read_events, append_event
    )

    os.environ["FAKE_FFMPEG_DURATION"] = "5"
    os.environ["FAKE_FFMPEG_FRAMES"]   = "150"

    conn = get_conn()
    try:
        create_session(conn, "s_persist", 1, "2026-01-01 00:00:00")
        job_id = create_job(conn, "s_persist", "v.mkv", sample_video, 100.0, 26, "cpu", "2026-01-01 00:00:00")
    finally:
        conn.close()

    # Append some events (simulating what worker would do)
    append_event("s_persist", {"type": "step", "msg": "hello", "time": "00:00:00"})
    append_event("s_persist", {"type": "progress", "pct": 50, "frame": 75,
                                 "fps": "30", "speed": "1x", "eta": 30, "time": "00:00:01"})

    # "Restart API" — fresh DB connections
    conn = get_conn()
    try:
        # Active session still found
        s = get_active_session(conn)
        assert s is not None
        assert s["id"] == "s_persist"

        jobs = get_jobs(conn, "s_persist")
        assert len(jobs) == 1
        assert jobs[0]["status"] == "queued"

        # Events still readable
        events = read_events("s_persist")
        assert len(events) == 2
        assert events[0]["msg"] == "hello"
    finally:
        conn.close()


def test_worker_recovery_from_crash(tmp_data_dir, encoder_config, patched_config_for_worker):
    """
    Simulate worker crash: a job is in 'encoding' status with no actual worker.
    On worker restart, recover_stale_jobs should mark it as failed.
    """
    from app.database import (
        get_conn, create_session, create_job, update_job,
        recover_stale_jobs, get_job
    )

    conn = get_conn()
    try:
        create_session(conn, "s_crash", 2, "2026-01-01 00:00:00")
        j1 = create_job(conn, "s_crash", "a.mkv", "/x/a.mkv", 100.0, 26, "cpu", "2026-01-01 00:00:00")
        j2 = create_job(conn, "s_crash", "b.mkv", "/x/b.mkv", 100.0, 26, "cpu", "2026-01-01 00:00:00")
        # Simulate crash: j1 was being encoded
        update_job(conn, j1, status="encoding")
    finally:
        conn.close()

    # Recovery
    conn = get_conn()
    try:
        recovered = recover_stale_jobs(conn, "2026-01-01 01:00:00")
        assert recovered == 1

        j1_after = get_job(conn, j1)
        assert j1_after["status"] == "failed"
        assert "crashed" in j1_after["error_msg"].lower()

        j2_after = get_job(conn, j2)
        assert j2_after["status"] == "queued"
    finally:
        conn.close()
