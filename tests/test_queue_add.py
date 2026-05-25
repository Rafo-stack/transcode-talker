"""M-028: append paths to a running session."""
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
        "extensions": [".mkv"], "ffmpeg_threads": 4,
    }))
    from app import config as cfg
    monkeypatch.setattr(cfg, "CONFIG_PATH", config_path)
    (tmp_data_dir / "static").mkdir(exist_ok=True)
    (tmp_data_dir / "static" / "index.html").write_text("<html></html>")
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


def test_queue_add_without_session_returns_409(api_client, tmp_data_dir):
    src = tmp_data_dir / "fake.mkv"
    src.write_bytes(b"VIDEO" * 100)
    r = api_client.post("/api/encode/queue/add", json={"paths": [str(src)]})
    assert r.status_code == 409


def test_queue_add_rejects_missing_files(api_client, tmp_data_dir):
    # Start a session first
    src = tmp_data_dir / "fake.mkv"
    src.write_bytes(b"VIDEO" * 100)
    api_client.post("/api/encode/start", json={"paths": [str(src)]})

    r = api_client.post("/api/encode/queue/add", json={"paths": ["/no/such/file.mkv"]})
    assert r.status_code == 400


def test_queue_add_appends_to_active_session(api_client, tmp_data_dir):
    src1 = tmp_data_dir / "a.mkv"; src1.write_bytes(b"X" * 100)
    src2 = tmp_data_dir / "b.mkv"; src2.write_bytes(b"X" * 100)
    api_client.post("/api/encode/start", json={"paths": [str(src1)]})

    r = api_client.post("/api/encode/queue/add", json={"paths": [str(src2)]})
    assert r.status_code == 200
    assert r.json()["added"] == 1

    active = api_client.get("/api/session/active").json()
    assert len(active["jobs"]) == 2
    assert active["session"]["total_files"] == 2


def test_queue_add_dedupes_existing_paths(api_client, tmp_data_dir):
    src = tmp_data_dir / "x.mkv"
    src.write_bytes(b"VIDEO" * 100)
    api_client.post("/api/encode/start", json={"paths": [str(src)]})

    r = api_client.post("/api/encode/queue/add", json={"paths": [str(src)]})
    assert r.status_code == 200
    assert r.json()["added"] == 0  # already in session

    active = api_client.get("/api/session/active").json()
    assert len(active["jobs"]) == 1


def test_queue_add_empty_paths_returns_400(api_client, tmp_data_dir):
    src = tmp_data_dir / "x.mkv"; src.write_bytes(b"VIDEO" * 100)
    api_client.post("/api/encode/start", json={"paths": [str(src)]})

    r = api_client.post("/api/encode/queue/add", json={"paths": []})
    assert r.status_code == 400
