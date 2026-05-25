"""M-034: advanced config fields persist + are returned by /api/config."""
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


def test_defaults_include_new_keys(api_client):
    """All M-031, M-034, M-018 keys must round-trip through /api/config."""
    r = api_client.get("/api/config")
    body = r.json()
    for key in (
        "log_retention_days", "clean_logs_on_startup",
        "timezone", "stall_timeout_s",
        "worker_poll_interval_s", "stop_check_interval_s", "log_buffer_size",
        "advanced_encode", "theme", "accent_color", "brand_name",
    ):
        assert key in body, f"missing default: {key}"


def test_save_and_reload_advanced_fields(api_client):
    new_cfg = api_client.get("/api/config").json()
    new_cfg["log_retention_days"] = 7
    new_cfg["clean_logs_on_startup"] = False
    new_cfg["stall_timeout_s"] = 120
    new_cfg["worker_poll_interval_s"] = 1.5
    new_cfg["theme"] = "light"
    new_cfg["accent_color"] = "#ff8800"
    new_cfg["brand_name"] = "My Transcoder"

    r = api_client.post("/api/config", json=new_cfg)
    assert r.status_code == 200

    reloaded = api_client.get("/api/config").json()
    assert reloaded["log_retention_days"] == 7
    assert reloaded["clean_logs_on_startup"] is False
    assert reloaded["stall_timeout_s"] == 120
    assert reloaded["worker_poll_interval_s"] == 1.5
    assert reloaded["theme"] == "light"
    assert reloaded["accent_color"] == "#ff8800"
    assert reloaded["brand_name"] == "My Transcoder"


def test_advanced_encode_structure_roundtrip(api_client):
    new_cfg = api_client.get("/api/config").json()
    new_cfg["advanced_encode"] = {
        "bitrate": {"enabled": True, "max": "5M", "min": "", "avg": "", "bufsize": "10M"},
        "tune":    {"enabled": True, "value": "animation"},
    }
    r = api_client.post("/api/config", json=new_cfg)
    assert r.status_code == 200

    reloaded = api_client.get("/api/config").json()
    assert reloaded["advanced_encode"]["bitrate"]["enabled"] is True
    assert reloaded["advanced_encode"]["bitrate"]["max"] == "5M"
    assert reloaded["advanced_encode"]["tune"]["value"] == "animation"


def test_save_with_unknown_extra_key_is_preserved(api_client):
    """Config(extra='allow') means we don't lose forward-compatible fields."""
    new_cfg = api_client.get("/api/config").json()
    new_cfg["future_field"] = {"x": 1}
    r = api_client.post("/api/config", json=new_cfg)
    assert r.status_code == 200
    reloaded = api_client.get("/api/config").json()
    assert reloaded.get("future_field") == {"x": 1}
