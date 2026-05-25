"""M-037: classic pagination on /api/history (Next/Prev + page X of Y).

The backend already supports ``limit``/``offset`` since M-008 (v3.1) and
already returns ``total`` since M-024 (v3.2). These tests pin that
contract — they break if a refactor ever drops ``total`` from the
response, since the UI's "Página X de Y" computation would silently
display the wrong count.
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


def _seed(n: int, status: str = "completed"):
    """Insert ``n`` completed jobs with predictable ids and timestamps."""
    from app.database import get_conn, create_session, create_job, update_job
    sid = "hist-001"
    conn = get_conn()
    try:
        create_session(conn, sid, n, "2026-05-20 00:00:00")
        for i in range(n):
            jid = create_job(
                conn, sid, f"f{i:04}.mkv", f"/mnt/m/f{i:04}.mkv",
                100.0, 26, "cpu", "2026-05-20 00:00:00",
            )
            # Stagger completed_at by minutes so sort_by=completed_at has
            # a stable order across pages.
            mm = i % 60
            hh = i // 60
            ts = f"2026-05-20 {hh:02}:{mm:02}:00"
            update_job(conn, jid, status=status, completed_at=ts)
    finally:
        conn.close()


def test_total_present_in_response(api_client):
    """``total`` is the contract M-037 UI depends on for "page X of Y"."""
    _seed(250)
    r = api_client.get("/api/history", params={"limit": 50, "offset": 0})
    body = r.json()
    assert "total" in body, "total field missing — M-037 UI would break"
    assert body["total"] == 250
    assert len(body["records"]) == 50


def test_paginates_to_last_page(api_client):
    """Offset at the last full page returns the tail rows."""
    _seed(250)
    r = api_client.get("/api/history", params={"limit": 50, "offset": 200})
    body = r.json()
    assert body["total"] == 250
    assert len(body["records"]) == 50
    assert body["offset"] == 200
    assert body["limit"] == 50


def test_offset_past_total_returns_empty(api_client):
    """Past-the-end offset returns empty but still the correct total."""
    _seed(250)
    r = api_client.get("/api/history", params={"limit": 50, "offset": 250})
    body = r.json()
    assert body["total"] == 250
    assert body["records"] == []


def test_filter_applies_to_total(api_client):
    """``total`` reflects the filtered count, not the raw row count."""
    from app.database import get_conn, create_session, create_job, update_job
    conn = get_conn()
    try:
        create_session(conn, "mix-001", 80, "2026-05-20 00:00:00")
        for i in range(50):
            jid = create_job(conn, "mix-001", f"c{i}.mkv", f"/mnt/m/c{i}.mkv",
                             100.0, 26, "cpu", "2026-05-20 00:00:00")
            update_job(conn, jid, status="completed",
                       completed_at=f"2026-05-20 00:{i % 60:02}:00")
        for i in range(30):
            jid = create_job(conn, "mix-001", f"f{i}.mkv", f"/mnt/m/f{i}.mkv",
                             100.0, 26, "cpu", "2026-05-20 00:00:00")
            update_job(conn, jid, status="failed",
                       completed_at=f"2026-05-20 01:{i % 60:02}:00")
    finally:
        conn.close()
    r = api_client.get("/api/history", params={
        "limit": 100, "offset": 0, "filter_status": "failed",
    })
    body = r.json()
    assert body["total"] == 30, "filter_status not reflected in total"
    assert all(rec["status"] == "failed" for rec in body["records"])


def test_pages_dont_overlap_or_skip(api_client):
    """Two adjacent pages cover the dataset without duplicates or gaps."""
    _seed(120)
    p1 = api_client.get("/api/history", params={
        "limit": 50, "offset": 0, "sort_by": "id", "order": "asc",
    }).json()
    p2 = api_client.get("/api/history", params={
        "limit": 50, "offset": 50, "sort_by": "id", "order": "asc",
    }).json()
    p3 = api_client.get("/api/history", params={
        "limit": 50, "offset": 100, "sort_by": "id", "order": "asc",
    }).json()
    ids = [r["id"] for r in (p1["records"] + p2["records"] + p3["records"])]
    assert len(ids) == 120
    assert len(set(ids)) == 120, "duplicate ids across pages"
    assert ids == sorted(ids), "page order broke after offset"
