"""Config persistence — JSON file under /data."""
import json
from pathlib import Path
from typing import Any

CONFIG_PATH = Path("/data/config.json")
LOGS_DIR    = Path("/data/logs")

DEFAULT_CONFIG: dict[str, Any] = {
    "scan_folders":    [],
    "exclude_folders": [],
    "crf":             26,
    "preset":          "medium",
    "ffmpeg_threads":  4,
    "encoder":         "cpu",
    "hdd_temp_path":   "/mnt/hdd/reencoder-temp",
    "ffmpeg_path":     "ffmpeg",
    "ffprobe_path":    "ffprobe",
    "extensions":      [".mkv", ".mp4", ".avi", ".mov"],
    "full_hash":            False,  # M-013
    "skip_hevc_below_kbps": 0,      # M-007
    # B-016: device path used by VAAPI and Intel QSV pipelines. Override only
    # if your distro maps the render node somewhere other than the default.
    "vaapi_device_path": "/dev/dri/renderD128",
    # M-031: log retention policy. 0 means keep forever.
    "log_retention_days":     30,
    "clean_logs_on_startup":  True,
    # M-034: advanced runtime knobs.
    "timezone":                "",   # empty = honour TZ env var, fallback America/New_York
    "stall_timeout_s":         60,
    "worker_poll_interval_s":  2.0,
    "stop_check_interval_s":   0.5,
    "log_buffer_size":         200,
    # M-018: advanced encode controls. Each sub-feature has its own enabled flag.
    "advanced_encode": {
        "bitrate":       {"enabled": False, "max": "", "min": "", "avg": "", "bufsize": ""},
        "tune":          {"enabled": False, "value": "animation"},
        "profile":       {"enabled": False, "value": "main"},
        "level":         {"enabled": False, "value": ""},
        "tier":          {"enabled": False, "value": "main"},
        "pixel_format":  {"enabled": False, "value": "yuv420p"},
        "gop":           {"enabled": False, "keyint": 250},
        "x265_params":   {"enabled": False, "value": ""},
        "audio":         {"enabled": False, "codec": "aac", "bitrate": "192k"},
        "video_filters": {"enabled": False, "value": ""},
    },
    # M-019/M-020/M-023: UI customisation
    "theme":         "dark",       # dark | light | auto
    "accent_color":  "#8b5cf6",    # default violet (matches existing --accent)
    "brand_name":    "Transcode Talker",
}


def load() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        return DEFAULT_CONFIG.copy()
    try:
        saved = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        return {**DEFAULT_CONFIG, **saved}
    except Exception:
        return DEFAULT_CONFIG.copy()


def save(config: dict[str, Any]) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(
        json.dumps(config, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )


def is_first_run() -> bool:
    """B-004: also returns True when the config file exists but is not valid
    JSON — otherwise the UI would skip the first-run setup while load() is
    silently serving DEFAULT_CONFIG."""
    if not CONFIG_PATH.exists():
        return True
    try:
        json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        return False
    except Exception:
        return True
