"""M-018: build_cmd respects the toggleable advanced_encode block."""
import pytest
from worker.encoder import build_cmd


BASE = {
    "ffmpeg_path": "ffmpeg",
    "encoder": "cpu",
    "crf": 26,
    "preset": "medium",
    "ffmpeg_threads": 4,
}


def test_default_when_no_advanced_settings_matches_legacy_behaviour():
    cmd = build_cmd("/in.mkv", "/out.mkv", BASE)
    # Legacy invariants
    assert "-c:v" in cmd and "libx265" in cmd
    assert "-c:a" in cmd and "copy" in cmd
    assert "-crf" in cmd and "26" in cmd
    assert "-preset" in cmd and "medium" in cmd
    # No advanced overrides leaked
    for forbidden in ("-tune", "-pix_fmt", "-x265-params", "-b:v", "-g"):
        assert forbidden not in cmd, f"unexpected arg {forbidden}"


def test_disabled_toggles_do_not_inject_args():
    cfg = {**BASE, "advanced_encode": {
        "bitrate": {"enabled": False, "max": "5M"},
        "tune":    {"enabled": False, "value": "animation"},
        "profile": {"enabled": False, "value": "main10"},
    }}
    cmd = build_cmd("/in.mkv", "/out.mkv", cfg)
    for forbidden in ("-tune", "-profile:v", "-b:v"):
        assert forbidden not in cmd


def test_tune_enabled_injects_tune_arg():
    cfg = {**BASE, "advanced_encode": {"tune": {"enabled": True, "value": "animation"}}}
    cmd = build_cmd("/in.mkv", "/out.mkv", cfg)
    idx = cmd.index("-tune")
    assert cmd[idx + 1] == "animation"


def test_bitrate_block_injects_all_flags():
    cfg = {**BASE, "advanced_encode": {"bitrate": {
        "enabled": True, "max": "5M", "min": "2M", "avg": "", "bufsize": "10M",
    }}}
    cmd = build_cmd("/in.mkv", "/out.mkv", cfg)
    # -maxrate / -minrate / -bufsize must be present with their values
    for arg, val in (("-maxrate", "5M"), ("-minrate", "2M"), ("-bufsize", "10M")):
        idx = cmd.index(arg)
        assert cmd[idx + 1] == val


def test_audio_block_replaces_copy_with_aac():
    cfg = {**BASE, "advanced_encode": {"audio": {
        "enabled": True, "codec": "aac", "bitrate": "192k",
    }}}
    cmd = build_cmd("/in.mkv", "/out.mkv", cfg)
    # No bare "-c:a copy" any more
    pairs = list(zip(cmd, cmd[1:]))
    assert ("-c:a", "copy") not in pairs
    idx = cmd.index("-c:a")
    assert cmd[idx + 1] == "aac"
    bidx = cmd.index("-b:a")
    assert cmd[bidx + 1] == "192k"


def test_pixel_format_only_applies_to_cpu_encoder():
    cfg = {**BASE, "advanced_encode": {"pixel_format": {
        "enabled": True, "value": "yuv420p10le",
    }}}
    cmd_cpu = build_cmd("/in.mkv", "/out.mkv", cfg)
    assert "-pix_fmt" in cmd_cpu

    cfg_gpu = {**cfg, "encoder": "vaapi"}
    cmd_gpu = build_cmd("/in.mkv", "/out.mkv", cfg_gpu)
    # GPU pipeline has its own format=nv12 filter — pix_fmt is not appended.
    assert "-pix_fmt" not in cmd_gpu


def test_x265_params_only_applies_to_cpu():
    cfg = {**BASE, "advanced_encode": {"x265_params": {
        "enabled": True, "value": "keyint=240:bframes=8",
    }}}
    cmd = build_cmd("/in.mkv", "/out.mkv", cfg)
    idx = cmd.index("-x265-params")
    assert "keyint=240" in cmd[idx + 1]


def test_video_filter_applied_to_cpu():
    cfg = {**BASE, "advanced_encode": {"video_filters": {
        "enabled": True, "value": "hqdn3d",
    }}}
    cmd = build_cmd("/in.mkv", "/out.mkv", cfg)
    idx = cmd.index("-vf")
    assert cmd[idx + 1] == "hqdn3d"


def test_gop_keyint_emits_g_arg():
    cfg = {**BASE, "advanced_encode": {"gop": {
        "enabled": True, "keyint": 250,
    }}}
    cmd = build_cmd("/in.mkv", "/out.mkv", cfg)
    idx = cmd.index("-g")
    assert cmd[idx + 1] == "250"


def test_vaapi_encoder_still_works_with_advanced_toggles():
    cfg = {**BASE, "encoder": "vaapi", "advanced_encode": {
        "tune": {"enabled": True, "value": "animation"},
        "bitrate": {"enabled": True, "max": "8M"},
    }}
    cmd = build_cmd("/in.mkv", "/out.mkv", cfg)
    assert "hevc_vaapi" in cmd
    assert "-tune" in cmd
    assert "-maxrate" in cmd
