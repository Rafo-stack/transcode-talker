"""v3.3: ffprobe metadata helpers + persistence in jobs table."""
import json
import os
import stat
import textwrap
from pathlib import Path

import pytest


@pytest.fixture
def fake_ffprobe_json(tmp_path):
    """A fake ffprobe that returns a fixed JSON when invoked with -print_format json."""
    bin_path = tmp_path / "fake_ffprobe_json.py"
    bin_path.write_text(textwrap.dedent("""\
        #!/usr/bin/env python3
        import json, sys

        args = sys.argv[1:]
        if "-print_format" in args:
            print(json.dumps({
                "format": {
                    "filename": args[-1],
                    "format_name": "matroska,webm",
                    "format_long_name": "Matroska / WebM",
                    "duration": "1234.56",
                    "size": "1073741824",
                    "bit_rate": "5000000",
                    "nb_streams": "4",
                    "tags": {"title": "Sample Movie"}
                },
                "streams": [
                    {"index": 0, "codec_type": "video", "codec_name": "h264",
                     "codec_long_name": "H.264 / AVC", "profile": "High",
                     "width": 1920, "height": 1080, "pix_fmt": "yuv420p",
                     "color_space": "bt709", "level": 40,
                     "r_frame_rate": "24000/1001", "avg_frame_rate": "24000/1001",
                     "nb_frames": "29568", "duration": "1234.56",
                     "disposition": {"default": 1, "forced": 0}},
                    {"index": 1, "codec_type": "audio", "codec_name": "aac",
                     "sample_rate": "48000", "channels": 6,
                     "channel_layout": "5.1",
                     "tags": {"language": "eng", "title": "English 5.1"},
                     "disposition": {"default": 1, "forced": 0}},
                    {"index": 2, "codec_type": "audio", "codec_name": "ac3",
                     "sample_rate": "48000", "channels": 2,
                     "channel_layout": "stereo",
                     "tags": {"language": "por"},
                     "disposition": {"default": 0, "forced": 0}},
                    {"index": 3, "codec_type": "subtitle", "codec_name": "subrip",
                     "tags": {"language": "eng"},
                     "disposition": {"default": 1, "forced": 0}},
                    {"index": 4, "codec_type": "attachment", "codec_name": "ttf",
                     "tags": {"filename": "OpenSans.ttf", "mimetype": "application/x-truetype-font"}},
                ],
                "chapters": [],
            }))
        else:
            # codec_name probe (used by verify_file)
            print("hevc")
        sys.exit(0)
    """))
    bin_path.chmod(bin_path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return str(bin_path)


def test_get_full_metadata_normalises_streams(fake_ffprobe_json, tmp_path):
    """v3.3: get_full_metadata classifies video/audio/subtitle/attachment."""
    from worker.encoder import get_full_metadata
    fake_video = tmp_path / "sample.mkv"
    fake_video.write_bytes(b"X")
    meta = get_full_metadata(str(fake_video), fake_ffprobe_json)

    assert "error" not in meta
    assert meta["format"]["format_name"] == "matroska,webm"
    assert meta["format"]["duration"] == 1234.56
    assert len(meta["video"]) == 1
    assert meta["video"][0]["codec"] == "h264"
    assert meta["video"][0]["width"] == 1920
    assert len(meta["audio"]) == 2
    assert {a["language"] for a in meta["audio"]} == {"eng", "por"}
    assert len(meta["subtitle"]) == 1
    assert meta["subtitle"][0]["language"] == "eng"
    assert len(meta["attachment"]) == 1
    assert meta["attachment"][0]["filename"] == "OpenSans.ttf"


def test_get_full_metadata_handles_ffprobe_error(tmp_path):
    """Missing ffprobe binary should not crash — returns {error: ...}."""
    from worker.encoder import get_full_metadata
    meta = get_full_metadata(str(tmp_path / "nope.mkv"), "/nonexistent/ffprobe")
    assert "error" in meta


def test_jobs_table_has_new_columns(tmp_data_dir):
    """v3.3 migration: source_metadata, destination_metadata, ffmpeg_cmd columns exist."""
    from app.database import get_conn
    conn = get_conn()
    try:
        # Insert a row with the new fields and read it back
        from app.database import create_session, create_job, update_job, get_job
        create_session(conn, "s1", 1, "2026-01-01")
        jid = create_job(conn, "s1", "x.mkv", "/x.mkv", 100.0, 26, "cpu", "2026-01-01")
        update_job(conn, jid,
                   source_metadata='{"format":{"duration":42}}',
                   destination_metadata='{"format":{"duration":42}}',
                   ffmpeg_cmd="ffmpeg -i /x.mkv -c:v libx265 /o.mkv")
        j = get_job(conn, jid)
        assert j["source_metadata"]      == '{"format":{"duration":42}}'
        assert j["destination_metadata"] == '{"format":{"duration":42}}'
        assert "libx265" in j["ffmpeg_cmd"]
    finally:
        conn.close()
