"""B-025: session_active stays bounded even with huge queues and logs.

Regression tests for the production incident where a session with 6k+
jobs and 24h of progress events made the UI time out: the legacy
``/api/session/active`` returned every job and every event in the JSONL,
inflating the response to tens of MB. The fixes:

1. Response is paginated (jobs_limit + events_limit, defaults bounded).
2. ``read_events_tail`` reads only the last N events via reverse seek.
3. ``read_events_since(offset)`` returns only the delta since a known
   byte offset, used by the broadcaster to avoid O(N) per tick.

The tests below assert *negative* properties — the payload is bounded
and the readers don't return more than asked — so a future regression
that re-introduces O(N) is caught even if the suite is still using
fake fixtures.
"""
import json
import time

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


def _seed_session(n_jobs: int, sid: str = "scale-001"):
    """Seed a session with ``n_jobs`` queued jobs."""
    from app.database import get_conn, create_session, create_job
    conn = get_conn()
    try:
        create_session(conn, sid, n_jobs, "2026-05-20 10:00:00")
        for i in range(n_jobs):
            create_job(conn, sid, f"f{i}.mkv", f"/mnt/m/f{i}.mkv",
                       100.0, 26, "cpu", "2026-05-20 10:00:00")
    finally:
        conn.close()
    return sid


def _write_jsonl(tmp_data_dir, sid: str, n_events: int):
    """Append ``n_events`` progress events to the session JSONL."""
    log = tmp_data_dir / "logs" / f"session_{sid}.jsonl"
    log.parent.mkdir(parents=True, exist_ok=True)
    with open(log, "a", encoding="utf-8") as f:
        for i in range(n_events):
            f.write(json.dumps({
                "type": "progress", "i": i, "frame": i, "fps": "30.0",
            }) + "\n")
    return log


def test_session_active_caps_jobs_by_default(api_client, tmp_data_dir):
    """A session with 6k jobs returns the paginated default, not all 6k."""
    _seed_session(6000)
    r = api_client.get("/api/session/active")
    assert r.status_code == 200
    body = r.json()
    # Default jobs_limit=500 — must NOT return 6k rows.
    assert len(body["jobs"]) <= 500, \
        f"session_active leaked all jobs (got {len(body['jobs'])}), B-025 regressed"
    assert body["total_jobs"] == 6000
    assert body["jobs_limit"] == 500
    assert body["jobs_offset"] == 0


def test_session_active_caps_events_by_default(api_client, tmp_data_dir):
    """A JSONL with 100k events returns only the tail, not the full log."""
    sid = _seed_session(10)
    _write_jsonl(tmp_data_dir, sid, n_events=100_000)
    t0 = time.time()
    r = api_client.get("/api/session/active")
    elapsed = time.time() - t0
    assert r.status_code == 200
    body = r.json()
    assert len(body["events"]) <= 200, \
        f"session_active leaked all events (got {len(body['events'])}), B-025 regressed"
    # The log_size field exposes the true size so the UI can resume the
    # stream from there.
    assert body["log_size"] > 0
    assert body["events_offset"] == body["log_size"]
    # Performance: even with 100k lines, the tail read should be fast
    # (well under a second on any modern CI/dev host).
    assert elapsed < 2.0, f"session_active too slow with 100k events: {elapsed:.2f}s"


def test_session_active_jobs_paginates(api_client, tmp_data_dir):
    """The companion endpoint pages through the queue."""
    _seed_session(1200)
    r1 = api_client.get("/api/session/active/jobs", params={"limit": 500, "offset": 0})
    r2 = api_client.get("/api/session/active/jobs", params={"limit": 500, "offset": 500})
    r3 = api_client.get("/api/session/active/jobs", params={"limit": 500, "offset": 1000})
    assert r1.status_code == r2.status_code == r3.status_code == 200
    p1, p2, p3 = r1.json(), r2.json(), r3.json()
    assert len(p1["jobs"]) == 500
    assert len(p2["jobs"]) == 500
    assert len(p3["jobs"]) == 200      # tail
    assert p1["total"] == p2["total"] == p3["total"] == 1200
    # Pages don't overlap — ids strictly increase.
    last_p1 = p1["jobs"][-1]["id"]
    first_p2 = p2["jobs"][0]["id"]
    assert first_p2 > last_p1


def test_read_events_since_returns_only_delta(tmp_data_dir):
    """``read_events_since(offset)`` returns only what's new past offset."""
    from app.database import read_events_since, read_events_tail
    sid = "delta-001"
    _write_jsonl(tmp_data_dir, sid, n_events=50)
    _, offset_after_50 = read_events_tail(sid, n=10)
    # Append 5 more events; the tail offset must capture them as delta.
    _write_jsonl(tmp_data_dir, sid, n_events=5)
    delta, new_offset = read_events_since(sid, offset_after_50)
    assert len(delta) == 5
    assert new_offset > offset_after_50


def test_read_events_tail_is_sublinear(tmp_data_dir):
    """Tail of a 50k-event log is fast and bounded to N events."""
    from app.database import read_events_tail
    sid = "stress-001"
    _write_jsonl(tmp_data_dir, sid, n_events=50_000)
    t0 = time.time()
    events, offset = read_events_tail(sid, n=200)
    elapsed = time.time() - t0
    assert len(events) == 200
    assert events[-1]["i"] == 49_999       # really got the tail
    assert events[0]["i"] == 49_800        # exactly the last 200
    assert offset > 0
    # Reverse-chunk read of a 50k-line file should not approach the cost
    # of a full parse. 1s is a generous upper bound for CI.
    assert elapsed < 1.0, f"read_events_tail too slow on 50k events: {elapsed:.2f}s"
