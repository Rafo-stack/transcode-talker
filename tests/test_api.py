"""Tests for API endpoints using FastAPI TestClient."""
import os
import json
import pytest
from pathlib import Path


@pytest.fixture
def api_client(tmp_data_dir, monkeypatch):
    """FastAPI TestClient with isolated state."""
    # Set up config path before importing app
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

    # Need static directory for FastAPI
    static_dir = tmp_data_dir / "static"
    static_dir.mkdir(exist_ok=True)
    (static_dir / "index.html").write_text("<html></html>")

    # Change cwd so StaticFiles finds it
    import os as os_module
    old_cwd = os_module.getcwd()
    os_module.chdir(str(tmp_data_dir))

    try:
        # Force re-import of app.main to get fresh state
        import importlib, sys
        if "app.main" in sys.modules:
            del sys.modules["app.main"]
        from app import main as api_main

        from fastapi.testclient import TestClient
        client = TestClient(api_main.app)
        yield client
    finally:
        os_module.chdir(old_cwd)


def test_health_check(api_client):
    r = api_client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_get_config_returns_defaults_or_saved(api_client):
    r = api_client.get("/api/config")
    assert r.status_code == 200
    data = r.json()
    assert "crf" in data
    assert "scan_folders" in data


def test_save_config(api_client):
    new_config = {
        "scan_folders": [{"path": "/tmp", "threshold_mb": 100}],
        "exclude_folders": [],
        "crf": 28,
        "preset": "medium",
        "ffmpeg_threads": 4,
        "encoder": "cpu",
        "hdd_temp_path": "/tmp/hdd",
        "ffmpeg_path": "ffmpeg",
        "ffprobe_path": "ffprobe",
        "extensions": [".mkv"],
    }
    r = api_client.post("/api/config", json=new_config)
    assert r.status_code == 200

    r = api_client.get("/api/config")
    assert r.json()["crf"] == 28


def test_encode_start_rejects_missing_files(api_client):
    r = api_client.post("/api/encode/start", json={
        "paths": ["/nonexistent/file.mkv"],
    })
    assert r.status_code == 400
    assert "not found" in r.json()["error"].lower()


def test_encode_start_rejects_empty_paths(api_client):
    r = api_client.post("/api/encode/start", json={"paths": []})
    assert r.status_code == 400


def test_encode_start_creates_session(api_client, tmp_data_dir):
    # Create a real source file
    src = tmp_data_dir / "fake.mkv"
    src.write_bytes(b"VIDEO" * 100)

    r = api_client.post("/api/encode/start", json={"paths": [str(src)]})
    assert r.status_code == 200
    assert r.json()["ok"] is True
    sid = r.json()["session_id"]

    # Active session check
    r2 = api_client.get("/api/session/active")
    data = r2.json()
    assert data["session"]["id"] == sid
    assert data["session"]["status"] == "running"
    assert len(data["jobs"]) == 1


def test_double_start_returns_409(api_client, tmp_data_dir):
    src = tmp_data_dir / "fake.mkv"
    src.write_bytes(b"VIDEO" * 100)

    r1 = api_client.post("/api/encode/start", json={"paths": [str(src)]})
    assert r1.status_code == 200

    r2 = api_client.post("/api/encode/start", json={"paths": [str(src)]})
    assert r2.status_code == 409


def test_stop_marks_session_interrupted(api_client, tmp_data_dir):
    src = tmp_data_dir / "fake.mkv"
    src.write_bytes(b"VIDEO" * 100)

    r1 = api_client.post("/api/encode/start", json={"paths": [str(src)]})
    sid = r1.json()["session_id"]

    r2 = api_client.post("/api/encode/stop", json={})
    assert r2.status_code == 200
    assert r2.json()["ok"] is True
    # 1 queued job → cancelled
    assert r2.json()["cancelled"] >= 1


def test_stop_when_no_session(api_client):
    r = api_client.post("/api/encode/stop", json={})
    assert r.status_code == 200
    # No error, just nothing to stop
    assert r.json()["ok"] is True


def test_session_active_returns_latest_when_no_running(api_client, tmp_data_dir):
    """After session ends, session/active should still return last session for UI."""
    src = tmp_data_dir / "fake.mkv"
    src.write_bytes(b"VIDEO" * 100)

    r1 = api_client.post("/api/encode/start", json={"paths": [str(src)]})
    sid = r1.json()["session_id"]
    api_client.post("/api/encode/stop", json={})

    r = api_client.get("/api/session/active")
    data = r.json()
    assert data["session"] is not None
    assert data["session"]["id"] == sid
    # Status should be 'interrupted' now
    assert data["session"]["status"] == "interrupted"


def test_history_empty_initially(api_client):
    r = api_client.get("/api/history")
    assert r.status_code == 200
    assert r.json()["records"] == []


def test_history_stats(api_client):
    r = api_client.get("/api/history/stats")
    assert r.status_code == 200
    data = r.json()
    assert "total" in data
    assert "completed" in data


def test_delete_active_job_returns_409(api_client, tmp_data_dir):
    src = tmp_data_dir / "fake.mkv"
    src.write_bytes(b"VIDEO" * 100)

    r1 = api_client.post("/api/encode/start", json={"paths": [str(src)]})
    sid = r1.json()["session_id"]

    # Get the job id
    r2 = api_client.get("/api/session/active")
    job_id = r2.json()["jobs"][0]["id"]

    r3 = api_client.post(f"/api/history/{job_id}/delete")
    assert r3.status_code == 409


def test_bulk_delete(api_client, tmp_data_dir):
    """Bulk delete should remove non-active jobs and skip active ones."""
    from app.database import get_conn, create_session, create_job, update_job

    # Create some completed jobs in DB directly
    conn = get_conn()
    try:
        create_session(conn, "old1", 2, "2026-01-01 00:00:00")
        j1 = create_job(conn, "old1", "a.mkv", "/x/a.mkv", 100.0, 26, "cpu", "2026-01-01 00:00:00")
        j2 = create_job(conn, "old1", "b.mkv", "/x/b.mkv", 100.0, 26, "cpu", "2026-01-01 00:00:00")
        update_job(conn, j1, status="completed")
        update_job(conn, j2, status="failed")
    finally:
        conn.close()

    r = api_client.post("/api/history/bulk-delete", json={"ids": [j1, j2]})
    assert r.status_code == 200
    assert r.json()["deleted"] == 2

    r = api_client.get("/api/history")
    assert len(r.json()["records"]) == 0


def test_scan_persistence(api_client, tmp_data_dir):
    """Saved scan results survive a 'restart' (new client)."""
    from app.database import get_conn, save_scan
    files = [
        {"path": "/a.mkv", "filename": "a.mkv", "size_mb": 100.0, "folder": "/x", "selected": True},
    ]
    conn = get_conn()
    try:
        save_scan(conn, files, "2026-01-01 00:00:00")
    finally:
        conn.close()

    r = api_client.get("/api/scan/last")
    assert r.status_code == 200
    assert len(r.json()["files"]) == 1


def test_encoded_paths_endpoint(api_client, tmp_data_dir):
    from app.database import get_conn, create_session, create_job, update_job

    conn = get_conn()
    try:
        create_session(conn, "s1", 2, "2026-01-01 00:00:00")
        j1 = create_job(conn, "s1", "a.mkv", "/p/a.mkv", 100.0, 26, "cpu", "2026-01-01 00:00:00")
        j2 = create_job(conn, "s1", "b.mkv", "/p/b.mkv", 100.0, 26, "cpu", "2026-01-01 00:00:00")
        update_job(conn, j1, status="completed")
        update_job(conn, j2, status="failed")
    finally:
        conn.close()

    r = api_client.get("/api/history/encoded-paths")
    assert r.status_code == 200
    paths = r.json()["paths"]
    assert "/p/a.mkv" in paths
    assert "/p/b.mkv" not in paths
