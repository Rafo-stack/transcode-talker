"""
Encoder — runs ffmpeg as subprocess, writes progress to DB.

Critical design points:
  1. stop_check is a callable that returns True when the encode should stop.
     This callable is provided by main.py and reads from the DB — so a Stop
     request from the API (which writes to the DB) is detected within seconds.

  2. ffmpeg is killed gracefully (terminate -> wait -> kill) on stop. The
     temp encoded file is cleaned up.

  3. Progress events are streamed via append_event() to the session log.
     They're throttled to once every 2 seconds to keep log size manageable.

  4. All exceptions are caught and converted to result dicts. The worker
     never panics on a single file failure.
"""

import hashlib
import json
import os
import shutil
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from worker.database import (
    get_conn, update_job, update_job_progress, append_event
)


# B-007/M-002: timezone configurable via TZ env var (default America/New_York)
_TZ = ZoneInfo(os.environ.get("TZ", "America/New_York"))


# ── Helpers ──────────────────────────────────────────────────────────────────
def _now_str(fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
    return datetime.now(_TZ).strftime(fmt)


def file_hash(path: str, full: bool = False) -> str:
    """Fast hash: size + first 4MB + last 4MB. Good enough for change detection.

    M-013: when full=True, hash the entire file (slower but detects internal
    corruption). Opt-in via config["full_hash"]=true.
    """
    h = hashlib.sha256()
    size = os.path.getsize(path)
    h.update(str(size).encode())
    chunk = 4 * 1024 * 1024
    with open(path, "rb") as f:
        if full:
            while True:
                buf = f.read(chunk)
                if not buf:
                    break
                h.update(buf)
        else:
            h.update(f.read(chunk))
            if size > chunk * 2:
                f.seek(-chunk, 2)
                h.update(f.read(chunk))
    return h.hexdigest()


def get_video_codec(path: str, ffprobe: str) -> str:
    """M-007: read the video codec name of the first video stream ('' on error)."""
    try:
        r = subprocess.run(
            [ffprobe, "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=codec_name",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            capture_output=True, text=True, timeout=30,
        )
        return r.stdout.strip().lower()
    except Exception:
        return ""


def size_mb(path: str) -> float:
    return round(os.path.getsize(path) / (1024 * 1024), 2)


def get_duration(path: str, ffprobe: str) -> float:
    try:
        r = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            capture_output=True, text=True, timeout=30)
        return float(r.stdout.strip())
    except Exception:
        return 0.0


def get_total_frames(path: str, ffprobe: str) -> int:
    """Try nb_frames first, fall back to duration * fps."""
    try:
        r = subprocess.run(
            [ffprobe, "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=nb_frames",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            capture_output=True, text=True, timeout=30)
        val = r.stdout.strip()
        if val and val not in ("N/A", ""):
            return int(val)

        r_dur = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            capture_output=True, text=True, timeout=30)
        r_fps = subprocess.run(
            [ffprobe, "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=r_frame_rate",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            capture_output=True, text=True, timeout=30)
        dur_str = r_dur.stdout.strip()
        fps_str = r_fps.stdout.strip()
        if dur_str and fps_str and dur_str not in ("N/A", "") and fps_str not in ("N/A", ""):
            num, den = fps_str.split("/")
            return int(float(dur_str) * float(num) / float(den))
    except Exception:
        pass
    return 0


def get_full_metadata(path: str, ffprobe: str) -> dict:
    """
    Full ffprobe JSON of the file — used to persist a per-job snapshot of
    everything we know about the source and (after encode) destination
    files. Output is a normalised dict so the UI can render it without
    knowing the ffprobe schema.

    Captures:
      * format: filename, size, duration, bitrate, format_long_name, tags
      * streams: list of {index, type, codec, language, title, plus
        type-specific fields like resolution+pix_fmt for video, channels
        +sample_rate for audio, etc.}
      * attachments: filename + mimetype + size when present
    """
    try:
        r = subprocess.run(
            [ffprobe, "-v", "error", "-show_format", "-show_streams",
             "-show_chapters", "-print_format", "json", path],
            capture_output=True, text=True, timeout=60,
        )
        if r.returncode != 0 or not r.stdout.strip():
            return {"error": (r.stderr or "ffprobe failed").strip()[:500]}
        raw = json.loads(r.stdout)
    except Exception as e:
        return {"error": str(e)[:500]}

    fmt = raw.get("format", {}) or {}
    out = {
        "format": {
            "filename":         fmt.get("filename"),
            "format_name":      fmt.get("format_name"),
            "format_long_name": fmt.get("format_long_name"),
            "duration":         _safe_float(fmt.get("duration")),
            "size":             _safe_int(fmt.get("size")),
            "bit_rate":         _safe_int(fmt.get("bit_rate")),
            "nb_streams":       _safe_int(fmt.get("nb_streams")),
            "tags":             fmt.get("tags") or {},
        },
        "streams":     [],
        "video":       [],
        "audio":       [],
        "subtitle":    [],
        "attachment":  [],
        "data":        [],
        "chapters":    raw.get("chapters") or [],
    }
    for s in raw.get("streams", []) or []:
        kind = (s.get("codec_type") or "").lower()
        tags = s.get("tags") or {}
        disp = s.get("disposition") or {}
        norm = {
            "index":         s.get("index"),
            "type":          kind,
            "codec":         s.get("codec_name"),
            "codec_long":    s.get("codec_long_name"),
            "profile":       s.get("profile"),
            "language":      tags.get("language") or tags.get("LANGUAGE"),
            "title":         tags.get("title") or tags.get("TITLE"),
            "default":       bool(disp.get("default")),
            "forced":        bool(disp.get("forced")),
            "bit_rate":      _safe_int(s.get("bit_rate") or tags.get("BPS")),
        }
        if kind == "video":
            norm.update({
                "width":          s.get("width"),
                "height":         s.get("height"),
                "pix_fmt":        s.get("pix_fmt"),
                "color_space":    s.get("color_space"),
                "color_transfer": s.get("color_transfer"),
                "color_primaries":s.get("color_primaries"),
                "level":          s.get("level"),
                "r_frame_rate":   s.get("r_frame_rate"),
                "avg_frame_rate": s.get("avg_frame_rate"),
                "nb_frames":      _safe_int(s.get("nb_frames")),
                "duration":       _safe_float(s.get("duration")),
            })
            out["video"].append(norm)
        elif kind == "audio":
            norm.update({
                "sample_rate":    _safe_int(s.get("sample_rate")),
                "channels":       s.get("channels"),
                "channel_layout": s.get("channel_layout"),
            })
            out["audio"].append(norm)
        elif kind == "subtitle":
            out["subtitle"].append(norm)
        elif kind == "attachment":
            norm.update({
                "filename":  tags.get("filename"),
                "mimetype":  tags.get("mimetype"),
            })
            out["attachment"].append(norm)
        else:
            out["data"].append(norm)
        out["streams"].append(norm)
    return out


def _safe_int(v):
    try:
        return int(v) if v not in (None, "", "N/A") else None
    except (TypeError, ValueError):
        return None


def _safe_float(v):
    try:
        return float(v) if v not in (None, "", "N/A") else None
    except (TypeError, ValueError):
        return None


def verify_file(path: str, ffprobe: str) -> bool:
    """Health check: can ffprobe read the encoded video stream?"""
    try:
        r = subprocess.run(
            [ffprobe, "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=codec_name",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            capture_output=True, text=True, timeout=60)
        return r.returncode == 0 and r.stdout.strip() != ""
    except Exception:
        return False


def _advanced_args(config: dict, encoder: str) -> tuple[list, list, list, dict]:
    """
    M-018: turn the advanced_encode config into extra ffmpeg arg fragments.

    Each toggleable sub-feature is consulted only when its ``enabled`` flag
    is True; otherwise behaviour is exactly as before. Returns:
      (pre_input_args, video_args, post_filter_args, output_overrides)

    ``output_overrides`` may contain:
      * ``audio_codec`` / ``audio_bitrate`` — replaces the default ``-c:a copy``
      * ``video_filter`` — extra -vf string appended to whatever the encoder
        already needs (only used by CPU; GPU pipelines have their own filters).
    """
    adv = config.get("advanced_encode") or {}
    pre, vargs, post = [], [], []
    out_over: dict = {}

    bitrate = adv.get("bitrate") or {}
    if bitrate.get("enabled"):
        for arg, key in (("-b:v", "max"), ("-maxrate", "max"),
                         ("-minrate", "min"), ("-bufsize", "bufsize")):
            v = bitrate.get(key)
            if v:
                vargs += [arg, str(v)]
        if bitrate.get("avg"):
            vargs += ["-b:v", str(bitrate["avg"])]

    tune = adv.get("tune") or {}
    if tune.get("enabled") and tune.get("value"):
        vargs += ["-tune", str(tune["value"])]

    profile = adv.get("profile") or {}
    if profile.get("enabled") and profile.get("value"):
        vargs += ["-profile:v", str(profile["value"])]

    level = adv.get("level") or {}
    if level.get("enabled") and level.get("value"):
        vargs += ["-level", str(level["value"])]

    tier = adv.get("tier") or {}
    if tier.get("enabled") and tier.get("value") and encoder == "cpu":
        vargs += ["-tier", str(tier["value"])]

    pixel = adv.get("pixel_format") or {}
    if pixel.get("enabled") and pixel.get("value") and encoder == "cpu":
        vargs += ["-pix_fmt", str(pixel["value"])]

    gop = adv.get("gop") or {}
    if gop.get("enabled") and gop.get("keyint"):
        vargs += ["-g", str(gop["keyint"])]

    x265p = adv.get("x265_params") or {}
    if x265p.get("enabled") and x265p.get("value") and encoder == "cpu":
        vargs += ["-x265-params", str(x265p["value"])]

    audio = adv.get("audio") or {}
    if audio.get("enabled"):
        out_over["audio_codec"]   = audio.get("codec") or "aac"
        out_over["audio_bitrate"] = audio.get("bitrate") or "192k"

    vf = adv.get("video_filters") or {}
    if vf.get("enabled") and vf.get("value"):
        out_over["video_filter"] = str(vf["value"])

    return pre, vargs, post, out_over


def _audio_out(out_over: dict) -> list:
    if "audio_codec" in out_over:
        a = ["-c:a", out_over["audio_codec"]]
        if out_over.get("audio_bitrate"):
            a += ["-b:a", out_over["audio_bitrate"]]
        return a
    return ["-c:a", "copy"]


def build_cmd(src: str, dst: str, config: dict) -> list[str]:
    """Build the ffmpeg command line based on encoder config.

    Supported encoders: cpu (libx265), vaapi (AMD), qsv (Intel), nvenc (NVIDIA).
    M-015: qsv/nvenc require the corresponding driver/runtime on the host and
    the appropriate ffmpeg build inside the worker container.
    M-018: when the user enables advanced_encode toggles, extra args are
    injected — otherwise behaviour is identical to v3.1.
    """
    ffmpeg = config.get("ffmpeg_path") or "ffmpeg"
    encoder = config.get("encoder", "cpu")
    crf = str(config.get("crf", 26))

    _pre, vargs, _post, out_over = _advanced_args(config, encoder)

    common_in  = ["-progress", "pipe:2", "-nostats", "-i", src]
    common_map = ["-map", "0:V", "-map", "0:a?", "-map", "0:s?", "-map", "0:t?"]
    common_out = [*_audio_out(out_over), "-c:s", "copy",
                  "-max_muxing_queue_size", "1024", dst]

    # B-016: device path configurable so people running on /dev/dri/card1,
    # iHD, etc. don't need to hack the worker.
    vaapi_dev = config.get("vaapi_device_path") or "/dev/dri/renderD128"

    if encoder == "vaapi":
        # B-020: ffmpeg 7 removed the legacy ``-vaapi_device`` global option.
        # ``-init_hw_device vaapi=va:<dev>`` + ``-filter_hw_device va`` is the
        # canonical replacement and also works on ffmpeg 4.x/5.x/6.x.
        # B-021: ffmpeg 7's new CLI parser rejects ``-rc_mode CQP`` as an
        # encoder-private option ("Unrecognized option 'rc_mode'"). Dropped —
        # when ``-qp <N>`` is supplied without an explicit rc_mode, the vaapi
        # encoder picks RC_MODE_CQP automatically (vaapi_encode.c), so the
        # encode result is byte-identical.
        return [
            ffmpeg, "-y",
            "-init_hw_device", f"vaapi=va:{vaapi_dev}",
            "-filter_hw_device", "va",
            *common_in,
            *common_map,
            "-vf", "format=nv12,hwupload", "-c:v", "hevc_vaapi",
            "-qp", crf,
            *vargs,
            *common_out,
        ]
    if encoder == "qsv":
        return [
            ffmpeg, "-y",
            "-init_hw_device", f"qsv=qs:{vaapi_dev}",
            "-filter_hw_device", "qs",
            "-hwaccel", "qsv", "-hwaccel_output_format", "qsv",
            *common_in,
            *common_map,
            "-c:v", "hevc_qsv",
            "-global_quality", crf,
            "-preset", config.get("preset", "medium"),
            *vargs,
            *common_out,
        ]
    if encoder == "nvenc":
        return [
            ffmpeg, "-y",
            *common_in,
            *common_map,
            "-c:v", "hevc_nvenc",
            "-rc", "constqp", "-qp", crf,
            "-preset", config.get("preset", "medium"),
            *vargs,
            *common_out,
        ]
    # Default: libx265 CPU
    cpu_video_filter = out_over.get("video_filter")
    cpu_extra = ["-vf", cpu_video_filter] if cpu_video_filter else []
    return [
        ffmpeg, "-y", *common_in, *common_map,
        *cpu_extra,
        "-c:v", "libx265", "-crf", crf,
        "-preset", config.get("preset", "medium"),
        "-threads", str(config.get("ffmpeg_threads", 4)),
        *vargs,
        *common_out,
    ]


def _cleanup(*paths):
    for p in paths:
        try:
            if p and os.path.exists(p):
                os.remove(p)
        except Exception:
            pass


def _emit(session_id: str, job_id: int, kind: str, fname: str, **kwargs):
    """Append a typed event to the session log."""
    append_event(session_id, {
        "type": kind, "job_id": job_id, "session_id": session_id,
        "file": fname, "time": _now_str("%H:%M:%S"), **kwargs
    })


# ── Main entry point ─────────────────────────────────────────────────────────
def encode_file(job_id: int, session_id: str, src_path: str,
                config: dict, stop_check) -> dict:
    """
    Encode a single file. Synchronous — runs in worker process.

    Args:
        job_id:      DB job row id
        session_id:  Owning session
        src_path:    Source file to encode (will be replaced on success)
        config:      Encoder config (crf, preset, encoder, hdd_temp_path...)
        stop_check:  callable() -> bool. True means abort and clean up.

    Returns:
        Result dict with status, sizes, hashes, error_msg.
    """
    # B-002/B-013: open the DB connection only for the duration of each write
    # via _with_conn() — avoids holding a long-lived connection during the entire
    # ffmpeg run (which can be hours) and lets WAL checkpoints proceed.
    def _with_conn(action):
        c = get_conn()
        try:
            return action(c)
        finally:
            c.close()

    ffprobe     = config.get("ffprobe_path") or "ffprobe"
    fname       = Path(src_path).name
    stem        = Path(src_path).stem
    ext         = Path(src_path).suffix
    hdd_base    = config.get("hdd_temp_path", "/mnt/hdd/reencoder-temp")
    os.makedirs(hdd_base, exist_ok=True)
    hdd_encoded = os.path.join(hdd_base, f"ENCODED_{stem}{ext}")

    result = {
        "status": "failed",
        "final_size_mb": None,
        "space_saved_mb": None,
        "original_hash": None,
        "encoded_hash": None,
        "error_msg": None,
    }

    def log(kind, **kwargs):
        _emit(session_id, job_id, kind, fname, **kwargs)

    try:
        # ── Step 1: Source file checks ───────────────────────────────────────
        if not os.path.exists(src_path):
            log("error", msg=f"Source file not found: {src_path}")
            result["error_msg"] = "Source not found"
            return result

        # M-007: skip if already HEVC and below the configured bitrate ceiling.
        skip_hevc_below_kbps = config.get("skip_hevc_below_kbps") or 0
        if skip_hevc_below_kbps:
            codec = get_video_codec(src_path, ffprobe)
            if codec in ("hevc", "h265"):
                dur = get_duration(src_path, ffprobe) or 0
                if dur > 0:
                    kbps = (size_mb(src_path) * 1024 * 8) / dur
                    if kbps < skip_hevc_below_kbps:
                        log("skipped", msg=f"Already HEVC at {kbps:.0f} kbps (< {skip_hevc_below_kbps})")
                        result.update({
                            "status": "skipped",
                            "final_size_mb": size_mb(src_path),
                            "space_saved_mb": 0.0,
                            "error_msg": None,
                        })
                        return result

        # ── Step 2: Hash original + full metadata snapshot ───────────────────
        log("step", msg="Computing hash...")
        orig_hash = file_hash(src_path, full=bool(config.get("full_hash", False)))
        result["original_hash"] = orig_hash
        _with_conn(lambda c: update_job(c, job_id, original_hash=orig_hash))
        log("step", msg=f"Hash: {orig_hash[:16]}...")

        # v3.3: full source metadata persisted per job + emitted as an event
        # so the UI can show codec/resolution/audio tracks/subtitles right away.
        src_meta = get_full_metadata(src_path, ffprobe)
        src_meta_json = json.dumps(src_meta, ensure_ascii=False)
        _with_conn(lambda c: update_job(c, job_id, source_metadata=src_meta_json))
        log("metadata", role="source", data=src_meta)

        if stop_check():
            result["status"] = "interrupted"
            result["error_msg"] = "Stopped before encode"
            log("stopped", msg="Stopped before encode")
            return result

        # ── Step 3: Probe video info ─────────────────────────────────────────
        total_frames = get_total_frames(src_path, ffprobe)
        total_dur    = get_duration(src_path, ffprobe)
        _with_conn(lambda c: update_job(c, job_id, total_frames=total_frames))
        log("step", msg=f"Encoding... (duration: {total_dur:.0f}s, frames: {total_frames})")

        # ── Step 4: Run ffmpeg ───────────────────────────────────────────────
        cmd  = build_cmd(src_path, hdd_encoded, config)
        cmd_str = " ".join(cmd)
        # B-016: log the full command at debug-friendly level so failures
        # reproduce easily. Skip the long paths for readability.
        log("step", msg="ffmpeg: " + " ".join(
            (a if len(a) < 80 else a[:60] + "…" + a[-15:]) for a in cmd))
        # v3.3: persist the exact command for forensics in the History panel.
        _with_conn(lambda c: update_job(c, job_id, ffmpeg_cmd=cmd_str))
        log("ffmpeg_cmd", cmd=cmd, cmd_str=cmd_str)

        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

        encode_start  = time.time()
        current: dict = {}
        last_db       = time.time()
        last_frame    = 0
        stall_count   = 0
        # B-016: keep a small ring buffer of non-progress stderr so we can
        # quote the real ffmpeg error in result["error_msg"] when it dies
        # before producing any frames (the common GPU-init failure mode).
        stderr_tail: list[str] = []
        STDERR_TAIL_MAX = 30

        # Stderr reader (ffmpeg writes progress key=value pairs to stderr)
        def read_stderr():
            for raw in proc.stderr:
                line = raw.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                if "=" in line and not line.lower().startswith(("error", "[")):
                    k, _, v = line.partition("=")
                    current[k.strip()] = v.strip()
                else:
                    stderr_tail.append(line)
                    if len(stderr_tail) > STDERR_TAIL_MAX:
                        del stderr_tail[: len(stderr_tail) - STDERR_TAIL_MAX]

        t = threading.Thread(target=read_stderr, daemon=True)
        t.start()

        # Main progress loop
        while proc.poll() is None:
            time.sleep(0.5)

            # Stop request from UI?
            if stop_check():
                log("stopped", msg="Stop requested — terminating ffmpeg...")
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    log("stopped", msg="Force killing ffmpeg...")
                    proc.kill()
                    proc.wait(timeout=5)
                t.join(timeout=3)
                log("stopped", msg="Encode stopped by user")
                result["status"]    = "interrupted"
                result["error_msg"] = "Interrupted by user"
                _cleanup(hdd_encoded)
                return result

            # Update progress
            elapsed       = time.time() - encode_start
            current_frame = int(current.get("frame", 0) or 0)
            fps_str       = current.get("fps", "")
            speed_str     = current.get("speed", "")
            pct = min(current_frame / total_frames, 1.0) if total_frames > 0 else 0.0
            eta = round((elapsed / pct - elapsed) if pct > 0.001 else 0)

            # Stall detection (60s without frame movement = ffmpeg hung)
            if current_frame == last_frame and current_frame > 0:
                stall_count += 1
            else:
                stall_count = 0
                last_frame  = current_frame

            if stall_count >= 120:
                log("error", msg=f"FFmpeg stalled at frame {current_frame}")
                proc.kill()
                proc.wait()
                result["error_msg"] = f"Stalled at frame {current_frame}"
                _cleanup(hdd_encoded)
                return result

            # Throttle DB writes + progress events to once every 2 seconds
            now = time.time()
            if now - last_db >= 2:
                last_db = now
                _with_conn(lambda c: update_job_progress(c, job_id,
                    frame=current_frame, pct=round(pct * 100, 1),
                    fps=fps_str, speed=speed_str, eta_s=eta))
                log("progress",
                    pct=round(pct * 100, 1), frame=current_frame,
                    fps=fps_str, speed=speed_str, eta=eta,
                    elapsed=round(elapsed))

        # Drain final stderr
        proc.wait()
        t.join(timeout=5)

        if proc.returncode != 0:
            # B-016: include the actual ffmpeg error message so GPU init
            # failures, missing devices, codec mismatches, etc. show up in
            # the History view instead of an opaque "FFmpeg exit 1".
            tail = "\n".join(stderr_tail[-10:]) if stderr_tail else "(no stderr)"
            log("error", msg=f"FFmpeg exited with code {proc.returncode}")
            log("error", msg=f"stderr tail: {tail}")
            result["error_msg"] = (
                f"FFmpeg exit {proc.returncode}: "
                + (stderr_tail[-1] if stderr_tail else "no stderr")
            )
            _cleanup(hdd_encoded)
            return result

        # Final progress = 100%
        _with_conn(lambda c: update_job_progress(c, job_id, frame=total_frames,
                            pct=100.0, fps="", speed="", eta_s=0))

        # ── Step 5: Health check + destination metadata snapshot ─────────────
        log("step", msg="Running health check...")
        if not verify_file(hdd_encoded, ffprobe):
            log("error", msg="Health check failed — encoded file is corrupt")
            result["error_msg"] = "Health check failed"
            _cleanup(hdd_encoded)
            return result

        # v3.3: full destination metadata persisted per job so the UI can
        # show before/after comparisons (codec, resolution, bitrate per
        # stream, retained subtitles, etc.).
        dst_meta = get_full_metadata(hdd_encoded, ffprobe)
        dst_meta_json = json.dumps(dst_meta, ensure_ascii=False)
        _with_conn(lambda c: update_job(c, job_id, destination_metadata=dst_meta_json))
        log("metadata", role="destination", data=dst_meta)

        # ── Step 6: Size check ───────────────────────────────────────────────
        new_size  = size_mb(hdd_encoded)
        orig_size = size_mb(src_path)
        if new_size >= orig_size:
            log("skipped", msg=f"Encoded ({new_size:.1f} MB) not smaller than original ({orig_size:.1f} MB)")
            result.update({
                "status": "skipped",
                "final_size_mb": new_size,
                "space_saved_mb": 0.0,
            })
            _cleanup(hdd_encoded)
            return result

        saved = round(orig_size - new_size, 2)
        log("step", msg=f"Size OK: {orig_size:.1f} MB -> {new_size:.1f} MB (saved {saved:.1f} MB)")

        # ── Step 7: Hash encoded ─────────────────────────────────────────────
        enc_hash = file_hash(hdd_encoded, full=bool(config.get("full_hash", False)))
        result["encoded_hash"] = enc_hash

        # ── Step 8: Replace original atomically ──────────────────────────────
        # B-005: copy to a sibling of src (same fs), fsync, then os.replace
        # (atomic on POSIX same-fs). Source stays intact until the rename
        # succeeds, so a crash mid-copy leaves the original untouched.
        log("step", msg="Replacing original...")
        staging = src_path + ".reencoded.tmp"
        try:
            shutil.copyfile(hdd_encoded, staging)
            with open(staging, "rb", buffering=0) as fh:
                os.fsync(fh.fileno())
            os.replace(staging, src_path)
        finally:
            if os.path.exists(staging):
                try: os.unlink(staging)
                except OSError: pass
        _cleanup(hdd_encoded)
        log("step", msg="Original replaced successfully")

        log("done", msg=f"Complete — saved {saved:.1f} MB")
        result.update({
            "status": "completed",
            "final_size_mb": new_size,
            "space_saved_mb": saved,
        })
        return result

    except Exception as e:
        log("error", msg=str(e))
        result["error_msg"] = str(e)
        _cleanup(hdd_encoded)
        return result
