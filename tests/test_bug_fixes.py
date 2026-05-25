"""Regression tests for bug fixes — one section per bug ID.

Keeps each bug discoverable when a future change re-introduces the issue.
"""
import os
import time
from pathlib import Path

import pytest


# ─────────────────────────────── B-005 ───────────────────────────────────────
# (atomic replace) — covered by the existing test_encoder.test_encode_completes_successfully
# which already validates the encoded bytes end up at src_path with the original gone.
# Adding an explicit unit for the staging-file invariant:

def test_b005_no_leftover_staging_file_after_replace(tmp_data_dir, tmp_path, fake_ffmpeg, fake_ffprobe, hdd_temp):
    """Replace step must clean up <src>.reencoded.tmp on success."""
    from worker.encoder import encode_file

    src = tmp_path / "video.mkv"
    src.write_bytes(b"FAKEVIDEO" * 2000)
    src_size = src.stat().st_size

    config = {
        "ffmpeg_path":    fake_ffmpeg,
        "ffprobe_path":   fake_ffprobe,
        "hdd_temp_path":  hdd_temp,
        "encoder":        "cpu",
        "crf":            26,
        "preset":         "fast",
        "ffmpeg_threads": 2,
    }
    result = encode_file(
        job_id=1, session_id="s_test", src_path=str(src),
        config=config, stop_check=lambda: False,
    )
    assert result["status"] == "completed"
    # Staging file must not survive
    assert not (tmp_path / "video.mkv.reencoded.tmp").exists()
    # Original was replaced (different content)
    assert src.exists()
    assert src.stat().st_size != src_size


# ─────────────────────────────── B-006 ───────────────────────────────────────

def test_b006_browse_rejects_paths_outside_mnt(tmp_data_dir):
    from fastapi.testclient import TestClient
    from app import main as api_main
    client = TestClient(api_main.app)

    for bad in ("/etc", "/", "/tmp", "/mnt/../etc"):
        r = client.get("/api/browse", params={"path": bad})
        assert r.status_code == 403, f"expected 403 for {bad}, got {r.status_code}"


def test_b006_browse_accepts_mnt_root(tmp_data_dir):
    from fastapi.testclient import TestClient
    from app import main as api_main
    client = TestClient(api_main.app)

    # /mnt may or may not exist on the host — accept either 200 or a graceful 400.
    r = client.get("/api/browse", params={"path": "/mnt"})
    assert r.status_code in (200, 400)


# ─────────────────────────────── B-009 / M-001 ───────────────────────────────

def test_b009_cleanup_old_logs_removes_old_files(tmp_data_dir):
    from app.database import cleanup_old_logs, LOGS_DIR

    fresh = LOGS_DIR / "session_fresh.jsonl"
    old   = LOGS_DIR / "session_old.jsonl"
    fresh.write_text('{"type":"x"}\n')
    old.write_text('{"type":"x"}\n')
    # Backdate "old" by 60 days
    sixty_days_ago = time.time() - (60 * 86400)
    os.utime(old, (sixty_days_ago, sixty_days_ago))

    deleted = cleanup_old_logs(max_age_days=30)

    assert deleted == 1
    assert fresh.exists()
    assert not old.exists()


def test_b009_cleanup_old_logs_handles_missing_dir(tmp_path):
    from app.database import cleanup_old_logs
    missing = tmp_path / "nonexistent"
    assert cleanup_old_logs(max_age_days=30, logs_dir=missing) == 0
