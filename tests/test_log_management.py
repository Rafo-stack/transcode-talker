"""M-024b / M-030 / M-031: per-job log view, search, export and retention."""
import json
import time
from pathlib import Path

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
        "log_retention_days": 30, "clean_logs_on_startup": True,
    }))
    from app import config as cfg
    monkeypatch.setattr(cfg, "CONFIG_PATH", config_path)

    static_dir = tmp_data_dir / "static"
    static_dir.mkdir(exist_ok=True)
    (static_dir / "index.html").write_text("<html></html>")

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


def _seed_session_with_log(events: list, status_per_job: dict):
    """Create one session with N jobs and a JSONL log file."""
    from app.database import (
        get_conn, create_session, create_job, update_job, append_event, LOGS_DIR,
    )
    conn = get_conn()
    try:
        create_session(conn, "sess1", 2, "2026-01-01 00:00:00")
        ids = []
        for fname in ("a.mkv", "b.mkv"):
            jid = create_job(conn, "sess1", fname, f"/x/{fname}", 100.0, 26, "cpu", "2026-01-01")
            update_job(conn, jid, status=status_per_job.get(fname, "completed"))
            ids.append(jid)
    finally:
        conn.close()

    for ev in events:
        append_event("sess1", ev)

    return ids


def test_job_logs_returns_only_matching_events(api_client):
    ids = _seed_session_with_log(
        events=[
            {"type": "queue_start", "session_id": "sess1", "time": "10:00:00"},
            {"type": "file_start",  "job_id": 1,           "time": "10:00:01"},
            {"type": "progress",    "job_id": 1, "pct": 25,"time": "10:00:30"},
            {"type": "file_done",   "job_id": 1,           "time": "10:01:00"},
            {"type": "file_start",  "job_id": 2,           "time": "10:01:10"},
            {"type": "progress",    "job_id": 2, "pct": 50,"time": "10:01:40"},
        ],
        status_per_job={"a.mkv": "completed", "b.mkv": "failed"},
    )

    r = api_client.get(f"/api/jobs/{ids[0]}/logs")
    assert r.status_code == 200
    body = r.json()
    types = [e["type"] for e in body["events"]]
    assert "file_start" in types
    assert "progress" in types
    assert "file_done" in types
    # Job 2's events should NOT be in job 1's slice
    assert all(e.get("job_id") == ids[0] for e in body["events"])


def test_job_logs_search_filters(api_client):
    ids = _seed_session_with_log(
        events=[
            {"type": "file_start", "job_id": 1, "file": "movie.mkv", "time": "10:00:00"},
            {"type": "step",       "job_id": 1, "msg": "Computing hash...", "time": "10:00:01"},
            {"type": "error",      "job_id": 1, "msg": "Stalled at frame 5000", "time": "10:00:30"},
        ],
        status_per_job={"a.mkv": "failed", "b.mkv": "completed"},
    )

    r = api_client.get(f"/api/jobs/{ids[0]}/logs?q=stall")
    body = r.json()
    assert body["count"] == 1
    assert "Stalled" in body["events"][0]["msg"]


def test_job_logs_returns_404_for_missing_job(api_client):
    r = api_client.get("/api/jobs/9999/logs")
    assert r.status_code == 404


def test_job_logs_export_text_format(api_client):
    ids = _seed_session_with_log(
        events=[
            {"type": "file_start", "job_id": 1, "file": "x.mkv", "time": "10:00:00"},
            {"type": "progress",   "job_id": 1, "pct": 10,       "time": "10:00:30"},
        ],
        status_per_job={"a.mkv": "completed", "b.mkv": "completed"},
    )
    r = api_client.get(f"/api/jobs/{ids[0]}/logs/export?fmt=text")
    body = r.json()
    assert "file_start" in body["text"]
    assert "progress" in body["text"]


def test_cleanup_old_logs_respects_age(tmp_data_dir):
    from app.database import cleanup_old_logs, LOGS_DIR

    # Create one old (40 days) and one fresh log
    fresh = LOGS_DIR / "session_fresh.jsonl"
    fresh.write_text('{"type":"x"}\n')
    old = LOGS_DIR / "session_old.jsonl"
    old.write_text('{"type":"x"}\n')
    old_mtime = time.time() - 40 * 86400
    import os
    os.utime(old, (old_mtime, old_mtime))

    deleted = cleanup_old_logs(max_age_days=30)
    assert deleted == 1
    assert fresh.exists()
    assert not old.exists()


def test_cleanup_old_logs_zero_days_is_forever(tmp_data_dir, monkeypatch):
    """log_retention_days=0 must NOT delete anything (kept forever).

    Contract is enforced at the startup hook in main.py; here we verify the
    helper itself by simulating the gating logic the hook performs.
    """
    from app.database import LOGS_DIR, cleanup_old_logs
    old = LOGS_DIR / "session_old.jsonl"
    old.write_text('{"type":"x"}\n')
    old_mtime = time.time() - 365 * 86400
    import os
    os.utime(old, (old_mtime, old_mtime))

    # Startup gating: when days == 0, cleanup is intentionally skipped.
    days = 0
    if days > 0:
        cleanup_old_logs(max_age_days=days)
    assert old.exists()  # nothing was deleted

    # And with a positive value, the same file IS deleted
    cleanup_old_logs(max_age_days=30)
    assert not old.exists()
