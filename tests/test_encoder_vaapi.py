"""B-016: VAAPI/QSV/NVENC command generation and error reporting."""
import pytest
from worker.encoder import build_cmd


BASE = {
    "ffmpeg_path": "ffmpeg",
    "crf": 26,
    "preset": "medium",
    "ffmpeg_threads": 4,
}


def test_vaapi_uses_default_device_path():
    cmd = build_cmd("/in.mkv", "/out.mkv", {**BASE, "encoder": "vaapi"})
    assert any("/dev/dri/renderD128" in a for a in cmd)
    assert "hevc_vaapi" in cmd
    # B-016: must initialise the hw device explicitly so the filter chain works
    assert "-init_hw_device" in cmd
    assert "-filter_hw_device" in cmd


def test_vaapi_does_not_use_legacy_vaapi_device_flag():
    # B-020: ffmpeg 7 dropped ``-vaapi_device``. Using both flags makes ffmpeg
    # exit with code 8 ("Unrecognized option 'vaapi_device'").
    cmd = build_cmd("/in.mkv", "/out.mkv", {**BASE, "encoder": "vaapi"})
    assert "-vaapi_device" not in cmd


def test_vaapi_does_not_use_legacy_rc_mode_flag():
    # B-021: ffmpeg 7's new CLI parser rejects ``-rc_mode CQP``.
    # When ``-qp`` is supplied the encoder picks CQP automatically.
    cmd = build_cmd("/in.mkv", "/out.mkv", {**BASE, "encoder": "vaapi"})
    assert "-rc_mode" not in cmd
    # ``-qp <crf>`` must still be present so the encoder knows the target
    # quality (without it the encoder would pick its own default).
    assert "-qp" in cmd


def test_vaapi_respects_custom_device_path():
    cfg = {**BASE, "encoder": "vaapi", "vaapi_device_path": "/dev/dri/card1"}
    cmd = build_cmd("/in.mkv", "/out.mkv", cfg)
    # Custom device propagates everywhere
    assert any("/dev/dri/card1" in a for a in cmd)
    # And the default is not silently re-added
    assert not any("/dev/dri/renderD128" in a for a in cmd)


def test_qsv_uses_init_hw_device():
    cmd = build_cmd("/in.mkv", "/out.mkv", {**BASE, "encoder": "qsv"})
    assert "hevc_qsv" in cmd
    assert "-init_hw_device" in cmd
    assert any("qsv=qs:" in a for a in cmd)


def test_nvenc_does_not_need_hw_device():
    cmd = build_cmd("/in.mkv", "/out.mkv", {**BASE, "encoder": "nvenc"})
    # NVENC runs via the NVIDIA runtime — no init_hw_device required
    assert "hevc_nvenc" in cmd
    assert "-init_hw_device" not in cmd


def test_vaapi_includes_format_nv12_hwupload_filter():
    cmd = build_cmd("/in.mkv", "/out.mkv", {**BASE, "encoder": "vaapi"})
    # The filter is critical: without it ffmpeg can't move frames onto the GPU.
    idx = cmd.index("-vf")
    assert "format=nv12" in cmd[idx + 1]
    assert "hwupload" in cmd[idx + 1]


def test_vaapi_still_works_with_advanced_toggles():
    cfg = {**BASE, "encoder": "vaapi", "advanced_encode": {
        "tune": {"enabled": True, "value": "animation"},
    }}
    cmd = build_cmd("/in.mkv", "/out.mkv", cfg)
    assert "hevc_vaapi" in cmd
    assert "-tune" in cmd
