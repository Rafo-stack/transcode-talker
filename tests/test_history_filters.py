"""M-024: history filters, sort and export/import."""
import json
import pytest


@pytest.fixture
def api_client(tmp_data_dir, monkeypatch):
    """Fresh API TestClient backed by the isolated DB."""
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
    """Insert a list of (session_id, status, encoder, original_path,
    started_at, completed_at) tuples directly via the DAL."""
    from app.database import get_conn, create_session, create_job, update_job
    sessions_made = set()
    conn = get_conn()
    try:
        for sid, status, enc, path, started, completed in rows:
            if sid not in sessions_made:
                create_session(conn, sid, len(rows), started)
                sessions_made.add(sid)
            jid = create_job(conn, sid, path.split("/")[-1], path,
                             100.0, 26, enc, started)
            update_job(conn, jid, status=status, completed_at=completed,
                       final_size_mb=60.0, space_saved_mb=40.0)
    finally:
        conn.close()


def test_history_default_returns_all_records(api_client):
    _seed([
        ("s1", "completed", "cpu",   "/a.mkv", "2026-01-01 10:00:00", "2026-01-01 10:10:00"),
        ("s1", "failed",    "vaapi", "/b.mkv", "2026-01-02 10:00:00", "2026-01-02 10:20:00"),
        ("s2", "skipped",   "cpu",   "/c.mkv", "2026-01-03 10:00:00", "2026-01-03 10:05:00"),
    ])

    r = api_client.get("/api/history")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 3
    assert len(body["records"]) == 3
    assert body["sort_by"] == "id"
    assert body["order"] == "desc"


def test_history_filter_by_encoder(api_client):
    _seed([
        ("s1", "completed", "cpu",   "/a.mkv", "2026-01-01 10:00:00", "2026-01-01 10:10:00"),
        ("s1", "completed", "vaapi", "/b.mkv", "2026-01-02 10:00:00", "2026-01-02 10:20:00"),
    ])
    r = api_client.get("/api/history?filter_encoder=vaapi")
    assert r.status_code == 200
    records = r.json()["records"]
    assert len(records) == 1
    assert records[0]["encoder_used"] == "vaapi"


def test_history_filter_by_status(api_client):
    _seed([
        ("s1", "completed", "cpu", "/a.mkv", "2026-01-01 10:00:00", "2026-01-01 10:10:00"),
        ("s1", "failed",    "cpu", "/b.mkv", "2026-01-02 10:00:00", "2026-01-02 10:20:00"),
        ("s1", "skipped",   "cpu", "/c.mkv", "2026-01-03 10:00:00", "2026-01-03 10:05:00"),
    ])
    r = api_client.get("/api/history?filter_status=failed")
    records = r.json()["records"]
    assert len(records) == 1
    assert records[0]["status"] == "failed"


def test_history_sort_by_completed_at_asc(api_client):
    _seed([
        ("s1", "completed", "cpu", "/a.mkv", "2026-01-01 10:00:00", "2026-01-01 10:10:00"),
        ("s1", "completed", "cpu", "/b.mkv", "2026-01-02 10:00:00", "2026-01-02 10:20:00"),
        ("s1", "completed", "cpu", "/c.mkv", "2026-01-03 10:00:00", "2026-01-03 10:05:00"),
    ])
    r = api_client.get("/api/history?sort_by=completed_at&order=asc")
    records = r.json()["records"]
    assert [j["filename"] for j in records] == ["a.mkv", "b.mkv", "c.mkv"]


def test_history_invalid_sort_falls_back_to_id(api_client):
    _seed([
        ("s1", "completed", "cpu", "/a.mkv", "2026-01-01", "2026-01-01"),
    ])
    r = api_client.get("/api/history?sort_by=DROP+TABLE+jobs")
    assert r.status_code == 200
    assert r.json()["sort_by"] == "id"


def test_history_date_range_filter(api_client):
    _seed([
        ("s1", "completed", "cpu", "/a.mkv", "2026-01-01 10:00:00", "2026-01-01 10:10:00"),
        ("s1", "completed", "cpu", "/b.mkv", "2026-02-01 10:00:00", "2026-02-01 10:20:00"),
        ("s1", "completed", "cpu", "/c.mkv", "2026-03-01 10:00:00", "2026-03-01 10:05:00"),
    ])
    r = api_client.get("/api/history?from_date=2026-02-01&to_date=2026-02-28")
    files = [j["filename"] for j in r.json()["records"]]
    assert files == ["b.mkv"]


def test_history_export_round_trip(api_client, tmp_data_dir):
    """Export → wipe → import = same data (sans active jobs)."""
    _seed([
        ("s1", "completed", "cpu",   "/a.mkv", "2026-01-01 10:00:00", "2026-01-01 10:10:00"),
        ("s1", "failed",    "vaapi", "/b.mkv", "2026-01-02 10:00:00", "2026-01-02 10:20:00"),
        ("s2", "skipped",   "cpu",   "/c.mkv", "2026-01-03 10:00:00", "2026-01-03 10:05:00"),
    ])

    export = api_client.get("/api/history/export").json()
    # v3.3: export schema bumped to v2 (carries per-job metadata + events).
    assert export["schema_version"] == 2
    assert len(export["jobs"]) == 3
    assert len(export["sessions"]) == 2
    # Each job MUST carry the new v2 fields (even if NULL when there's no
    # source/destination metadata yet — they come from real encodes).
    for j in export["jobs"]:
        assert "source_metadata" in j
        assert "destination_metadata" in j
        assert "ffmpeg_cmd" in j
        assert "events" in j

    # Wipe history
    from app.database import get_conn
    conn = get_conn()
    try:
        conn.execute("DELETE FROM jobs")
        conn.execute("DELETE FROM sessions")
        conn.commit()
    finally:
        conn.close()
    assert api_client.get("/api/history").json()["total"] == 0

    # Re-import
    r = api_client.post("/api/history/import", json=export)
    assert r.status_code == 200
    body = r.json()
    assert body["jobs_added"] == 3
    assert body["sessions_added"] == 2

    again = api_client.get("/api/history").json()
    assert again["total"] == 3


def test_history_import_dedupes_existing_jobs(api_client):
    _seed([
        ("s1", "completed", "cpu", "/a.mkv", "2026-01-01 10:00:00", "2026-01-01 10:10:00"),
    ])
    export = api_client.get("/api/history/export").json()

    # Re-import without wiping: nothing should be added
    r = api_client.post("/api/history/import", json=export)
    body = r.json()
    assert body["jobs_added"] == 0
    assert body["jobs_skipped"] == 1


def test_history_import_rejects_unknown_schema(api_client):
    r = api_client.post("/api/history/import", json={
        "schema_version": 999,
        "sessions": [],
        "jobs": [],
    })
    assert r.status_code == 400


def test_history_import_skips_in_flight_jobs(api_client):
    """Jobs marked queued/encoding in the payload are NOT imported."""
    payload = {
        "schema_version": 1,
        "exported_at": "2026-01-01 00:00:00",
        "sessions": [{
            "id": "ghost",
            "status": "running",
            "total_files": 1,
            "done_files": 0,
            "created_at": "2026-01-01 00:00:00",
        }],
        "jobs": [{
            "session_id": "ghost",
            "filename": "z.mkv",
            "original_path": "/z.mkv",
            "status": "encoding",
            "started_at": "2026-01-01 00:00:00",
        }],
    }
    r = api_client.post("/api/history/import", json=payload)
    assert r.status_code == 200
    assert r.json()["jobs_added"] == 0
