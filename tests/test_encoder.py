"""Tests for encoder.encode_file using a fake ffmpeg binary."""
import os
import time
import threading


def _run_encoder(job_id, session_id, src, config, stop_check):
    from worker.encoder import encode_file
    return encode_file(job_id, session_id, src, config, stop_check)


def test_encode_completes_successfully(tmp_data_dir, sample_video, encoder_config):
    """Happy path: fake ffmpeg runs, file replaces, status=completed."""
    from app.database import get_conn, create_session, create_job, get_job

    conn = get_conn()
    try:
        create_session(conn, "s1", 1, "2026-01-01 00:00:00")
        job_id = create_job(conn, "s1", "sample.mkv", sample_video, 100.0, 26, "cpu", "2026-01-01 00:00:00")
    finally:
        conn.close()

    # Fast fake encode
    os.environ["FAKE_FFMPEG_DURATION"] = "1"
    os.environ["FAKE_FFMPEG_FRAMES"]   = "30"

    result = _run_encoder(job_id, "s1", sample_video, encoder_config, lambda: False)

    assert result["status"] == "completed", f"Got: {result}"
    assert result["space_saved_mb"] is not None
    assert result["space_saved_mb"] >= 0
    assert os.path.exists(sample_video)  # Replaced original

    # Verify DB persisted result
    conn = get_conn()
    try:
        j = get_job(conn, job_id)
        assert j["original_hash"] is not None
        assert j["total_frames"] == 30
    finally:
        conn.close()


def test_encode_stops_when_stop_check_returns_true(tmp_data_dir, sample_video, encoder_config):
    """Stop_check returning True mid-encode terminates ffmpeg cleanly."""
    from app.database import get_conn, create_session, create_job

    conn = get_conn()
    try:
        create_session(conn, "s1", 1, "2026-01-01 00:00:00")
        job_id = create_job(conn, "s1", "sample.mkv", sample_video, 100.0, 26, "cpu", "2026-01-01 00:00:00")
    finally:
        conn.close()

    os.environ["FAKE_FFMPEG_DURATION"] = "10"  # Long encode
    os.environ["FAKE_FFMPEG_FRAMES"]   = "300"

    # Stop after 1 second
    stop_at = time.time() + 1.0
    def stop_check():
        return time.time() >= stop_at

    start = time.time()
    result = _run_encoder(job_id, "s1", sample_video, encoder_config, stop_check)
    elapsed = time.time() - start

    assert result["status"] == "interrupted", f"Got: {result}"
    assert elapsed < 8, f"Took too long to stop: {elapsed}s"

    # No leftover encoded file
    hdd = encoder_config["hdd_temp_path"]
    leftovers = [f for f in os.listdir(hdd) if f.startswith("ENCODED_")]
    assert leftovers == [], f"Leftover files: {leftovers}"


def test_encode_handles_ffmpeg_failure(tmp_data_dir, sample_video, encoder_config):
    """Non-zero exit code from ffmpeg → failed status, no replacement."""
    from app.database import get_conn, create_session, create_job

    conn = get_conn()
    try:
        create_session(conn, "s1", 1, "2026-01-01 00:00:00")
        job_id = create_job(conn, "s1", "sample.mkv", sample_video, 100.0, 26, "cpu", "2026-01-01 00:00:00")
    finally:
        conn.close()

    os.environ["FAKE_FFMPEG_DURATION"] = "0.5"
    os.environ["FAKE_FFMPEG_FRAMES"]   = "10"
    os.environ["FAKE_FFMPEG_EXIT"]     = "1"  # Force failure

    original_size = os.path.getsize(sample_video)
    result = _run_encoder(job_id, "s1", sample_video, encoder_config, lambda: False)

    assert result["status"] == "failed", f"Got: {result}"
    assert os.path.getsize(sample_video) == original_size  # Original untouched

    # Reset for next tests
    os.environ["FAKE_FFMPEG_EXIT"] = "0"


def test_stop_check_is_called_from_db(tmp_data_dir, sample_video, encoder_config):
    """The make_stop_check from worker.main reads DB. Test full integration."""
    from app.database import (
        get_conn, create_session, create_job, update_session
    )
    from worker.main import make_stop_check
    from worker import main as worker_main

    # Reset SHUTDOWN flag (may be left True by other tests)
    worker_main.SHUTDOWN[0] = False

    conn = get_conn()
    try:
        create_session(conn, "s1", 1, "2026-01-01 00:00:00")
        job_id = create_job(conn, "s1", "sample.mkv", sample_video, 100.0, 26, "cpu", "2026-01-01 00:00:00")
    finally:
        conn.close()

    os.environ["FAKE_FFMPEG_DURATION"] = "8"
    os.environ["FAKE_FFMPEG_FRAMES"]   = "240"

    stop_check = make_stop_check("s1")
    assert stop_check() is False  # Not interrupted yet

    # Run encoder in a thread, interrupt via DB after 1s
    result_holder = {}
    def run():
        result_holder["r"] = _run_encoder(job_id, "s1", sample_video, encoder_config, stop_check)

    t = threading.Thread(target=run)
    t.start()
    time.sleep(1.0)

    # Mark session as interrupted in DB — this is what API does on Stop
    conn = get_conn()
    try:
        update_session(conn, "s1", status="interrupted")
    finally:
        conn.close()

    t.join(timeout=10)
    assert not t.is_alive(), "Encoder did not respond to Stop"
    assert result_holder["r"]["status"] == "interrupted", f"Got: {result_holder['r']}"
