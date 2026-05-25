"""M-036: per-file last-state tags exposed via /api/scan/file-states.

Each file in the user's library can carry one of these tags on the Scan
page:
  - encoded    (last job: completed)
  - failed     (last job: failed)
  - skipped    (last job: skipped)
  - interrupted (last job: interrupted)
  - never_encoded (no history at all — derived client-side; backend
                    simply omits the path)

The source of truth is the ``jobs`` table; the endpoint returns the
status of the most recent job per ``original_path`` (by ``completed_at``).
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
        "extensions": [".mkv", ".mp4"], "ffmpeg_threads": 4,
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


def _seed(rows):
    """Insert (path, status, completed_at) triples directly via the DAL.

    All seeded jobs go into a single session for simplicity; tests assert
    on the per-path resolution, not on session relationships.
    """
    from app.database import get_conn, create_session, create_job, update_job
    sid = "fs-001"
    conn = get_conn()
    try:
        create_session(conn, sid, len(rows), "2026-05-20 00:00:00")
        for path, status, completed in rows:
            jid = create_job(conn, sid, path.split("/")[-1], path,
                             100.0, 26, "cpu", "2026-05-20 00:00:00")
            update_job(conn, jid, status=status, completed_at=completed)
    finally:
        conn.close()


def test_returns_last_status_per_path(api_client):
    """Different paths each get their own status."""
    _seed([
        ("/mnt/m/a.mkv", "completed", "2026-05-20 01:00:00"),
        ("/mnt/m/b.mkv", "failed",    "2026-05-20 02:00:00"),
        ("/mnt/m/c.mkv", "skipped",   "2026-05-20 03:00:00"),
    ])
    r = api_client.get("/api/scan/file-states")
    assert r.status_code == 200
    paths = r.json()["paths"]
    assert paths == {
        "/mnt/m/a.mkv": "completed",
        "/mnt/m/b.mkv": "failed",
        "/mnt/m/c.mkv": "skipped",
    }


def test_most_recent_wins_on_conflict(api_client):
    """A path with multiple jobs returns the chronologically most recent."""
    _seed([
        ("/mnt/m/x.mkv", "failed",    "2026-05-20 01:00:00"),
        ("/mnt/m/x.mkv", "completed", "2026-05-20 05:00:00"),  # later
        ("/mnt/m/x.mkv", "interrupted", "2026-05-20 02:00:00"),
    ])
    r = api_client.get("/api/scan/file-states")
    assert r.json()["paths"]["/mnt/m/x.mkv"] == "completed"


def test_in_flight_jobs_are_excluded(api_client):
    """Jobs without ``completed_at`` (still running) do not appear."""
    from app.database import get_conn, create_session, create_job
    sid = "fs-inflight"
    conn = get_conn()
    try:
        create_session(conn, sid, 1, "2026-05-20 00:00:00")
        # ``create_job`` sets status='queued' and never sets completed_at.
        create_job(conn, sid, "live.mkv", "/mnt/m/live.mkv",
                   100.0, 26, "cpu", "2026-05-20 00:00:00")
    finally:
        conn.close()
    r = api_client.get("/api/scan/file-states")
    assert "/mnt/m/live.mkv" not in r.json()["paths"]


def test_interrupted_tag_surfaces(api_client):
    """``interrupted`` jobs (Stop click) are first-class tags."""
    _seed([
        ("/mnt/m/y.mkv", "interrupted", "2026-05-20 03:00:00"),
    ])
    r = api_client.get("/api/scan/file-states")
    assert r.json()["paths"]["/mnt/m/y.mkv"] == "interrupted"


def test_endpoint_idempotent(api_client):
    """Calling twice in a row returns identical payloads."""
    _seed([
        ("/mnt/m/a.mkv", "completed", "2026-05-20 01:00:00"),
        ("/mnt/m/b.mkv", "failed",    "2026-05-20 02:00:00"),
    ])
    a = api_client.get("/api/scan/file-states").json()
    b = api_client.get("/api/scan/file-states").json()
    assert a == b
