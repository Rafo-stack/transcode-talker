"""M-021: per-folder add-to-exclusion endpoint."""
import json
import pytest


@pytest.fixture
def api_client(tmp_data_dir, monkeypatch):
    config_path = tmp_data_dir / "config.json"
    config_path.write_text(json.dumps({
        "scan_folders": [], "exclude_folders": ["/already/excluded"],
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


def test_exclude_folder_adds_new_path(api_client):
    r = api_client.post("/api/config/exclude-folder", json={"path": "/mnt/media/specials"})
    assert r.status_code == 200
    body = r.json()
    assert "/mnt/media/specials" in body["exclude_folders"]
    assert "/already/excluded" in body["exclude_folders"]


def test_exclude_folder_is_idempotent(api_client):
    r1 = api_client.post("/api/config/exclude-folder", json={"path": "/x"})
    r2 = api_client.post("/api/config/exclude-folder", json={"path": "/x"})
    assert r2.status_code == 200
    assert r2.json()["exclude_folders"].count("/x") == 1


def test_exclude_folder_rejects_empty_path(api_client):
    r = api_client.post("/api/config/exclude-folder", json={"path": ""})
    assert r.status_code == 400


def test_exclude_folder_persists_in_config(api_client):
    api_client.post("/api/config/exclude-folder", json={"path": "/p"})
    cfg = api_client.get("/api/config").json()
    assert "/p" in cfg["exclude_folders"]
