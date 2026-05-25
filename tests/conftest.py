"""
Pytest fixtures for the reencoder test suite.

Provides:
  - tmp_data_dir: isolated /data dir per test (DB, logs)
  - api_client:   FastAPI TestClient with isolated DB
  - fake_ffmpeg:  drop-in replacement that simulates progress
  - sample_video: fake source file (just bytes, won't be opened by mock)
"""
import os
import sys
import json
import time
import shutil
import sqlite3
from pathlib import Path

import pytest

# Make the api & worker importable
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "reencoder-api"))
sys.path.insert(0, str(ROOT / "reencoder-worker"))


@pytest.fixture
def tmp_data_dir(tmp_path, monkeypatch):
    """Set up an isolated /data directory and patch DB modules to use it.

    v3.4: since the production default is now Postgres, tests must
    explicitly force SQLite — otherwise the engine factory tries to
    resolve the Postgres hostname and fails outside Docker.

    v3.3: the engine is a SQLAlchemy singleton, so we must:
      1. Reset the cached engine before patching DB_PATH so the next
         get_engine() rebuilds against the new URL.
      2. Re-patch both API and Worker copies (db_engine.DB_PATH is what the
         engine reads; database.DB_PATH is the legacy re-export).
    """
    # v3.4: pin SQLite for local test runs.
    monkeypatch.setenv("DB_BACKEND", "sqlite")

    data = tmp_path / "data"
    logs = data / "logs"
    logs.mkdir(parents=True)

    new_db_path = data / "reencoder.db"

    from app import database as api_db
    from app import db_engine as api_engine
    from app import db_backend as api_backend
    from worker import database as worker_db
    from worker import db_engine as worker_engine
    from worker import db_backend as worker_backend

    # Reset the "warned once" flag so we don't suppress dialect warnings
    # in subsequent tests that expect them.
    api_backend._warned = False
    worker_backend._warned = False

    # Drop any pre-existing engine so it rebuilds against the tmp path.
    api_engine.reset_engine()
    worker_engine.reset_engine()

    for mod in (api_db, api_engine, worker_db, worker_engine):
        monkeypatch.setattr(mod, "DB_PATH",  new_db_path)
        monkeypatch.setattr(mod, "LOGS_DIR", logs)

    # Force engine init under the patched path
    conn = api_db.get_conn()
    conn.close()

    yield data

    # Tear down between tests so the next test gets a fresh engine.
    api_engine.reset_engine()
    worker_engine.reset_engine()


@pytest.fixture
def fake_ffmpeg(tmp_path):
    """
    Create a fake ffmpeg binary that:
      - Reads -i <src> and -y <dst> from args
      - Writes a small file to dst
      - Emits progress lines to stderr like real ffmpeg
      - Honours SIGTERM cleanly
      - Total duration controllable via FAKE_FFMPEG_DURATION env var (default 2s)
    """
    fake_bin = tmp_path / "fake_ffmpeg.py"
    fake_bin.write_text("""#!/usr/bin/env python3
import sys, os, time, signal, argparse

# Parse minimal flags we care about
args = sys.argv[1:]
src = dst = None
i = 0
while i < len(args):
    a = args[i]
    if a == "-i" and i+1 < len(args):
        src = args[i+1]; i += 2
    elif not a.startswith("-") and i == len(args) - 1:
        dst = a; i += 1
    else:
        i += 1

duration = float(os.environ.get("FAKE_FFMPEG_DURATION", "2"))
total_frames = int(os.environ.get("FAKE_FFMPEG_FRAMES", "100"))
exit_code = int(os.environ.get("FAKE_FFMPEG_EXIT", "0"))

stop = [False]
def handler(sig, frame):
    stop[0] = True
signal.signal(signal.SIGTERM, handler)
signal.signal(signal.SIGINT, handler)

start = time.time()
last_emit = 0
while True:
    if stop[0]:
        sys.exit(255)
    elapsed = time.time() - start
    if elapsed >= duration:
        break
    pct = elapsed / duration
    frame = int(pct * total_frames)
    if time.time() - last_emit >= 0.1:
        last_emit = time.time()
        print(f"frame={frame}", file=sys.stderr, flush=True)
        print(f"fps=30.0",       file=sys.stderr, flush=True)
        print(f"speed=1.0x",     file=sys.stderr, flush=True)
        print(f"out_time={elapsed:.2f}", file=sys.stderr, flush=True)
    time.sleep(0.05)

# Final frame
print(f"frame={total_frames}", file=sys.stderr, flush=True)

# Write a fake encoded file
if dst:
    if exit_code == 0:
        # Make it smaller than source to pass size check
        if src and os.path.exists(src):
            src_size = os.path.getsize(src)
            with open(dst, "wb") as f:
                f.write(b"X" * max(100, src_size // 2))
        else:
            with open(dst, "wb") as f:
                f.write(b"X" * 100)

sys.exit(exit_code)
""")
    fake_bin.chmod(0o755)
    return str(fake_bin)


@pytest.fixture
def fake_ffprobe(tmp_path):
    """Fake ffprobe that returns plausible video metadata."""
    fake_bin = tmp_path / "fake_ffprobe.py"
    fake_bin.write_text("""#!/usr/bin/env python3
import sys, os
args = sys.argv[1:]
# Verify mode (codec_name)
if "stream=codec_name" in args:
    print("hevc")
    sys.exit(0)
if "stream=nb_frames" in args:
    print(os.environ.get("FAKE_FFMPEG_FRAMES", "100"))
    sys.exit(0)
if "format=duration" in args:
    print(os.environ.get("FAKE_FFMPEG_DURATION", "2"))
    sys.exit(0)
if "stream=r_frame_rate" in args:
    print("30/1")
    sys.exit(0)
sys.exit(0)
""")
    fake_bin.chmod(0o755)
    return str(fake_bin)


@pytest.fixture
def sample_video(tmp_path):
    """Create a fake source 'video' file (just bytes — fake_ffmpeg won't decode)."""
    f = tmp_path / "sample.mkv"
    f.write_bytes(b"FAKEVIDEO" * 1000)  # ~9KB
    return str(f)


@pytest.fixture
def hdd_temp(tmp_path):
    d = tmp_path / "hdd-temp"
    d.mkdir()
    return str(d)


@pytest.fixture
def encoder_config(fake_ffmpeg, fake_ffprobe, hdd_temp):
    """Config dict for encoder using fake binaries."""
    return {
        "ffmpeg_path":    fake_ffmpeg,
        "ffprobe_path":   fake_ffprobe,
        "hdd_temp_path":  hdd_temp,
        "encoder":        "cpu",
        "crf":            26,
        "preset":         "fast",
        "ffmpeg_threads": 2,
    }
