"""M-025: Help/Manual endpoint returns sectioned, multilingual content."""
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


def test_help_default_lang_is_english(api_client):
    r = api_client.get("/api/help")
    assert r.status_code == 200
    body = r.json()
    assert body["lang"] == "en"
    assert len(body["sections"]) >= 5
    assert "en" in body["languages"]
    assert "pt-BR" in body["languages"]


def test_help_returns_ptbr(api_client):
    r = api_client.get("/api/help?lang=pt-BR")
    body = r.json()
    assert body["lang"] == "pt-BR"
    # Sanity check on a few Portuguese keywords
    text = " ".join(s["body"] for s in body["sections"])
    assert "encoder" in text.lower()
    assert "arquivo" in text.lower() or "arquivos" in text.lower()


def test_help_unknown_lang_falls_back_to_english(api_client):
    r = api_client.get("/api/help?lang=xx-YY")
    body = r.json()
    assert body["lang"] == "en"


def test_help_all_languages_are_fully_translated(api_client):
    # v3.4.1: es/fr/zh-CN/ja are no longer placeholders. Each language must
    # have the same set of section ids as English and no "pending" stub.
    en = api_client.get("/api/help?lang=en").json()
    en_ids = [s["id"] for s in en["sections"]]
    assert "pending" not in en_ids
    for lang in ("pt-BR", "es", "fr", "zh-CN", "ja"):
        body = api_client.get(f"/api/help?lang={lang}").json()
        assert body["lang"] == lang
        ids = [s["id"] for s in body["sections"]]
        assert "pending" not in ids, f"{lang} still has a 'pending' placeholder"
        assert ids == en_ids, f"{lang} section ids diverged from EN"
        # Every section must have a non-empty body.
        for s in body["sections"]:
            assert s["body"].strip(), f"{lang} section {s['id']} has empty body"


def test_help_each_section_has_required_fields(api_client):
    r = api_client.get("/api/help?lang=en")
    for s in r.json()["sections"]:
        assert "id" in s and s["id"]
        assert "title" in s and s["title"]
        assert "body" in s and s["body"]
