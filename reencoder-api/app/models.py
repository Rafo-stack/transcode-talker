"""Pydantic models for API request/response validation."""
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict


class ScanFolder(BaseModel):
    path: str
    threshold_mb: int = 300


class Config(BaseModel):
    # extra=allow lets new keys land in config.json without a model bump.
    model_config = ConfigDict(extra="allow")

    scan_folders:    list[ScanFolder] = []
    exclude_folders: list[str] = []
    crf:             int = 26
    preset:          str = "medium"
    ffmpeg_threads:  int = 4
    encoder:         str = "cpu"
    hdd_temp_path:   str = "/mnt/hdd/reencoder-temp"
    ffmpeg_path:     str = "ffmpeg"
    ffprobe_path:    str = "ffprobe"
    extensions:      list[str] = [".mkv", ".mp4", ".avi", ".mov"]
    full_hash:           bool = False  # M-013: hash full file (slow) instead of head+tail
    skip_hevc_below_kbps: int = 0      # M-007: if source is HEVC under this bitrate, skip (0=off)
    vaapi_device_path:   str = "/dev/dri/renderD128"  # B-016: configurable
    # M-031
    log_retention_days:    int = 30   # 0 = keep forever
    clean_logs_on_startup: bool = True
    # M-034
    timezone:               str   = ""
    stall_timeout_s:        int   = 60
    worker_poll_interval_s: float = 2.0
    stop_check_interval_s:  float = 0.5
    log_buffer_size:        int   = 200
    # M-018 — opaque dict so the toggleable structure is preserved without
    # exhaustive field-by-field validation here.
    advanced_encode:        dict[str, Any] = {}
    # M-019/M-020/M-023
    theme:        str = "dark"
    accent_color: str = "#8b5cf6"
    brand_name:   str = "Transcode Talker"


class ScannedFile(BaseModel):
    path:          str
    filename:      str
    size_mb:       float
    folder:        str
    relative_path: str = ""
    selected:      bool = True


class EncodeJob(BaseModel):
    paths: list[str]


class QueueAdd(BaseModel):
    """M-028: add paths to the currently running session."""
    paths: list[str]
