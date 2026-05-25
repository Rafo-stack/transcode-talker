"""
M-025: Help/Manual content served by /api/help.

Structure: { lang: { sections: [ { id, title, body } ] } }

This is the in-app technical manual. It mirrors the architecture/runtime
parts of "01 - Reencoder - Documentacao.md" but intentionally drops:

- version history tables (Part I.1.2)
- features/bugs/improvements tables (Part I.1.3)
- detailed bug and improvement appendix (Part VII.3/7.4)
- audit checklist (Part VII.6/7.8)
- hand-off section (Part VIII)
- any commercial/secret personal config

What it KEEPS and explains in detail:

- the full architecture, component diagrams, sequence flows
- directory + container structure
- the database schema and JSONL event log shape
- every config.json field (and matching env var) with meaning + defaults
- every API endpoint
- every front-end React component
- every back-end Python module (responsibility + key functions)
- every FFmpeg setting and every advanced encode toggle
- testing layout
- useful commands and maintenance
- troubleshooting

Languages supported: English (en), Portuguese-Brazilian (pt-BR), Spanish (es),
French (fr), Simplified Chinese (zh-CN), Japanese (ja). All are fully
translated.
"""
from __future__ import annotations


# ─────────────────────────────────────────────────────────────────────────────
# English (en)
# ─────────────────────────────────────────────────────────────────────────────
_EN = [
    {
        "id": "intro",
        "title": "1. What is Transcode Talker?",
        "body": (
            "**Transcode Talker** is a self-hosted batch video re-encoder. It scans the "
            "folders you configure, lets you pick which files to re-encode using FFmpeg "
            "(libx265 on CPU, or a GPU pipeline — VAAPI/QSV/NVENC), and replaces the "
            "original with the smaller HEVC version **only when the result is actually "
            "smaller**. If the re-encoded file ends up bigger, it is discarded and the "
            "job is marked `skipped`.\n\n"
            "It is built as two Docker containers — an **API + UI** and a **worker** — "
            "that share state through a database (Postgres by default since v3.4, "
            "SQLite WAL as legacy) and JSONL log files. The split is deliberate: encodes "
            "can run for hours and the design ensures the encode keeps going even if "
            "the browser closes, the API restarts, or the worker reboots. Only a "
            "worker that is killed mid-encode loses the current file (it is recovered "
            "as `failed` on the next worker startup).\n\n"
            "The goal is simple: reduce the disk space taken by your media library "
            "while preserving every audio track, every subtitle, every attachment, "
            "and the same playback fidelity (controlled by CRF — Constant Rate Factor)."
        ),
    },
    {
        "id": "architecture",
        "title": "2. Architecture overview",
        "body": (
            "Two Docker containers and one optional database container, on a private "
            "bridge network:\n\n"
            "- **reencoder-api** (FastAPI on port 4246) — serves the React UI, the "
            "HTTP API, and a WebSocket event stream. It owns the schema and reads/"
            "writes the database. It does **not** spawn FFmpeg.\n"
            "- **reencoder-worker** (Python loop) — polls the database every "
            "`worker_poll_interval_s` seconds looking for a `running` session with "
            "queued jobs, then runs FFmpeg one file at a time. It updates job "
            "progress in the database and appends events to the JSONL log.\n"
            "- **postgres** (since v3.4 the default; optional) — Postgres 16-alpine, "
            "data persisted in `data/postgres/`. SQLite remains supported via "
            "`DB_BACKEND=sqlite`.\n\n"
            "Why two processes instead of one? Three reasons:\n\n"
            "1. **Resilience.** A FastAPI restart does not kill the encode.\n"
            "2. **Resource isolation.** The worker gets dedicated CPU/memory limits "
            "in docker-compose (8 CPU, 8G RAM by default).\n"
            "3. **Separation of concerns.** The API is request/response + websocket; "
            "the worker is a long-running subprocess wrangler.\n\n"
            "There is **no HTTP between API and worker** — they communicate exclusively "
            "via the shared database (Postgres or SQLite WAL) and JSONL event files "
            "under `/data/logs/`. This is intentional: the database is the single "
            "source of truth, and adding HTTP between them would only duplicate state."
        ),
    },
    {
        "id": "components_diagram",
        "title": "3. Component diagram",
        "body": (
            "```\n"
            "                 ┌─────────────────────┐\n"
            "                 │  Browser (React UI) │\n"
            "                 └─────────┬───────────┘\n"
            "                           │ HTTP + WebSocket\n"
            "                           ▼\n"
            "                 ┌─────────────────────┐\n"
            "                 │   reencoder-api     │  FastAPI :4246\n"
            "                 │  (FastAPI + Uvicorn)│  static/index.html\n"
            "                 └────┬────────────┬───┘\n"
            "                      │            │\n"
            "                      ▼            ▼\n"
            "             ┌─────────────┐  ┌──────────────┐\n"
            "             │  Database   │  │  /data/logs/ │\n"
            "             │  (Postgres  │◄─┤  *.jsonl     │\n"
            "             │   or SQLite)│  └──────────────┘\n"
            "             └──────┬──────┘          ▲\n"
            "                    │                 │\n"
            "                    ▼                 │\n"
            "             ┌─────────────────┐      │\n"
            "             │ reencoder-worker│──────┘  Python poll loop\n"
            "             │  (Python loop)  │         calls FFmpeg\n"
            "             └────────┬────────┘\n"
            "                      │\n"
            "                      ▼\n"
            "             ┌────────────────────────┐\n"
            "             │  FFmpeg + /dev/dri     │  GPU VAAPI (AMD/Intel)\n"
            "             │  + /mnt/media          │  source files\n"
            "             │  + /mnt/hdd            │  temp encode area\n"
            "             └────────────────────────┘\n"
            "```\n\n"
            "All persistent state lives in three places:\n\n"
            "- **Database** (`/data/reencoder.db` for SQLite, or the `postgres` "
            "container's volume) — `sessions`, `jobs`, `scan_results` tables.\n"
            "- **JSONL event log files** (`/data/logs/session_<id>.jsonl`) — one "
            "append-only file per session, holding the human-readable timeline.\n"
            "- **Config** (`/data/config.json`) — every UI-editable setting."
        ),
    },
    {
        "id": "flow_scan_encode",
        "title": "4. End-to-end flow: Scan → Select → Encode",
        "body": (
            "```\n"
            "User → UI:           POST /api/scan\n"
            "UI → API:            walks scan_folders, returns ScannedFile list\n"
            "API → DB:            replace scan_results row with new snapshot\n"
            "API → UI:            {files: [...]}\n"
            "\n"
            "User → UI:           select files, click ▶ Encode\n"
            "UI → API:            POST /api/encode/start {paths}\n"
            "API → DB:            check no active session (dialect-aware lock,\n"
            "                     BEGIN IMMEDIATE on SQLite, pg_advisory_xact_lock\n"
            "                     on Postgres — see B-018)\n"
            "API → DB:            INSERT session(running) + INSERT N jobs(queued)\n"
            "API → UI:            {ok, session_id}\n"
            "\n"
            "Worker loop (every worker_poll_interval_s, default 2s):\n"
            "  Worker → DB:       SELECT active session\n"
            "  Worker → DB:       SELECT next queued job in that session\n"
            "  Worker → DB:       UPDATE job status=encoding\n"
            "  Worker → FFmpeg:   spawn with build_cmd(...)\n"
            "  Loop every 0.5s while FFmpeg runs:\n"
            "    Worker → DB:     is_session_interrupted? (stop check)\n"
            "    FFmpeg → stderr: progress key=value\n"
            "    Worker → DB:     update_job_progress(pct, frame, fps, speed, eta)\n"
            "                     (throttled to once every 2s)\n"
            "    Worker → JSONL:  append progress event\n"
            "  When FFmpeg exits:\n"
            "    Worker → ffprobe: verify_file (codec_name == libx265 / hevc)\n"
            "    Worker → fs:     compare sizes; skip if encoded >= original\n"
            "    Worker → fs:     shutil.move HDD_temp → original path\n"
            "    Worker → DB:     UPDATE job status=completed (or skipped/failed)\n"
            "    Worker → DB:     UPDATE session.done_files++\n"
            "```\n\n"
            "**API event broadcaster** (background task in the API) tails each "
            "session's JSONL file every 1s and pushes new lines to every connected "
            "WebSocket client. The UI also calls `GET /api/session/active` on every "
            "WebSocket open to fully reconstruct state — so closing/reopening the "
            "browser, or restarting the API, never desyncs the UI."
        ),
    },
    {
        "id": "flow_stop",
        "title": "5. End-to-end flow: Stop",
        "body": (
            "```\n"
            "User → UI:           click ■ Stop, confirm\n"
            "UI → API:            POST /api/encode/stop\n"
            "API → DB:            UPDATE session status=interrupted\n"
            "API → DB:            UPDATE jobs status=interrupted\n"
            "                     WHERE status IN (queued, encoding)\n"
            "API → JSONL:         append queue_stopped event\n"
            "API → UI:            {ok, cancelled}\n"
            "\n"
            "Worker (next stop_check_interval_s tick, default 0.5s):\n"
            "  Worker → DB:       is_session_interrupted? → True\n"
            "  Worker → FFmpeg:   SIGTERM\n"
            "  Wait up to 5 seconds:\n"
            "    If still running: SIGKILL\n"
            "  Worker → fs:       _cleanup(hdd_encoded)  (delete partial)\n"
            "  Worker → DB:       finalize job state\n"
            "```\n\n"
            "Stop is **graceful by default**: SIGTERM gives FFmpeg up to 5 seconds to "
            "finish writing its mux trailer and exit cleanly. Only if it does not "
            "respond does the worker escalate to SIGKILL. The partial encoded file in "
            "the HDD temp area is always deleted by `_cleanup()`.\n\n"
            "**The Stop loop is critical** because the worker only checks the DB every "
            "0.5s — so there is a worst-case ~0.5s + ~5s window between clicking Stop "
            "and FFmpeg actually exiting. This is by design (tight enough for UX, "
            "loose enough to not hammer the DB)."
        ),
    },
    {
        "id": "flow_recovery",
        "title": "6. End-to-end flow: Crash recovery",
        "body": (
            "When the worker container starts, it runs `recover_stale_jobs()` before "
            "entering the poll loop. Any job whose status is `encoding` is marked "
            "`failed` with `error_msg='Worker crashed or restarted'`. This is the only "
            "way a job can be in `encoding` state without an actual worker process "
            "running, because the worker is single-threaded and writes "
            "`status=encoding` at the start and `status=completed/skipped/failed` at "
            "the end.\n\n"
            "```\n"
            "Worker startup:\n"
            "  Worker → DB:       recover_stale_jobs(now)\n"
            "                     UPDATE jobs SET status='failed',\n"
            "                            error_msg='Worker crashed or restarted'\n"
            "                     WHERE status='encoding'\n"
            "  Worker → log:      \"Recovered N stale job(s)\"\n"
            "  (v3.4) Worker retries up to 10 × 2s if the DB is not ready yet —\n"
            "  tolerates slow Postgres cold start.\n"
            "  Worker → loop:     enter main poll loop\n"
            "```\n\n"
            "The UI exposes recovered jobs via `GET /api/recovered-since-startup` so "
            "the front-end can show a banner notifying the user.\n\n"
            "**v3.4 also added `/api/encode/force-reset`** as a defence in depth: if a "
            "session is left `running` with no actual worker (e.g. host reboot + DB "
            "out-of-sync), the user can hit this endpoint (or accept the auto-`confirm()` "
            "prompt the UI shows on a stuck 409) to mark all `running` sessions as "
            "`interrupted` and cancel their queued/encoding jobs."
        ),
    },
    {
        "id": "flow_websocket",
        "title": "7. End-to-end flow: WebSocket sync & reconnect",
        "body": (
            "```\n"
            "UI:                  connect ws://host:4246/ws\n"
            "API:                 accept, add to _ws_clients set\n"
            "UI:                  GET /api/session/active\n"
            "API → DB:            fetch active session OR most-recent session\n"
            "API → DB:            fetch all jobs for that session\n"
            "API → JSONL:         read full event log for that session\n"
            "API → UI:            {session, jobs, events}\n"
            "UI:                  rebuild progress bars, queue, event log buffer\n"
            "\n"
            "Background loop in API (every 1s):\n"
            "  API → JSONL:       tail new lines from active session\n"
            "  API → all WS:      broadcast new events\n"
            "  (dead websockets get pruned automatically on send failure)\n"
            "\n"
            "On WebSocket close:\n"
            "  UI:                wait with exponential backoff (1s, 2s, 4s, 8s, max 30s)\n"
            "  UI:                reconnect, repeat from top\n"
            "```\n\n"
            "Progress events (`type: progress`) update only the live counters "
            "(pct/fps/speed/eta) for snappiness. Anything that changes structure — "
            "`file_start`, `file_done`, `queue_start`, `queue_done`, `queue_stopped` — "
            "triggers a full `syncFromServer()` call so the UI re-reads the "
            "authoritative state."
        ),
    },
    {
        "id": "directory_structure",
        "title": "8. Directory and container structure",
        "body": (
            "**Repository layout:**\n\n"
            "```\n"
            "reencoder-v3/\n"
            "├── docker-compose.yml\n"
            "├── .env.example                  # template for production secrets\n"
            "├── data/                         # persistent volume mounted at /data\n"
            "│   ├── config.json               # UI-editable config\n"
            "│   ├── config.example.json       # publishable template\n"
            "│   ├── reencoder.db              # SQLite (only when DB_BACKEND=sqlite)\n"
            "│   ├── postgres/                 # Postgres data volume\n"
            "│   ├── backups/                  # automatic + manual DB snapshots\n"
            "│   └── logs/\n"
            "│       └── session_<id>.jsonl    # one event log per session\n"
            "├── reencoder-api/\n"
            "│   ├── Dockerfile\n"
            "│   ├── requirements.txt\n"
            "│   ├── app/\n"
            "│   │   ├── main.py               # FastAPI endpoints + WS\n"
            "│   │   ├── database.py           # DAL (SQLAlchemy Core)\n"
            "│   │   ├── db_engine.py          # Engine factory + schema\n"
            "│   │   ├── db_backend.py         # SQLite/Postgres switch\n"
            "│   │   ├── db_backup.py          # snapshot + restore\n"
            "│   │   ├── config.py             # config.json persistence\n"
            "│   │   ├── models.py             # Pydantic models\n"
            "│   │   ├── scanner.py            # filesystem walk\n"
            "│   │   └── help_content.py       # this manual\n"
            "│   └── static/\n"
            "│       └── index.html            # React UI inline\n"
            "├── reencoder-worker/\n"
            "│   ├── Dockerfile                # apt ffmpeg + mesa-va-drivers (v3.4.1)\n"
            "│   ├── requirements.txt\n"
            "│   └── worker/\n"
            "│       ├── main.py               # poll loop + signal handling\n"
            "│       ├── encoder.py            # ffmpeg pipeline\n"
            "│       ├── database.py           # byte-equal mirror of api/database.py\n"
            "│       ├── db_engine.py          # mirror\n"
            "│       └── db_backend.py         # mirror\n"
            "└── tests/                        # pytest suite (140 tests in v3.4.1)\n"
            "```\n\n"
            "**Host filesystem expectations:**\n\n"
            "| Host path | Container path | Purpose |\n"
            "|---|---|---|\n"
            "| `./data` | `/data` | DB, config, logs, backups (shared by api+worker) |\n"
            "| `/mnt/animes` | `/mnt/animes` | media library (read+write for worker) |\n"
            "| `/mnt/media` | `/mnt/media` | media library |\n"
            "| `/mnt/hdd` | `/mnt/hdd` | slow disk used as encode temp area |\n"
            "| `/dev/dri` | `/dev/dri` | GPU device (worker only, for VAAPI/QSV) |"
        ),
    },
    {
        "id": "data_model",
        "title": "9. Data model (database schema)",
        "body": (
            "Three tables, the same shape on SQLite and Postgres. Migration is "
            "idempotent: every `CREATE TABLE` uses `IF NOT EXISTS` and new columns are "
            "added via `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` at startup.\n\n"
            "**`sessions`** — one row per Start Encode click.\n\n"
            "| Column | Type | Notes |\n"
            "|---|---|---|\n"
            "| `id` | TEXT PK | 8-char UUID truncate |\n"
            "| `status` | TEXT | `pending` / `running` / `completed` / `interrupted` |\n"
            "| `total_files` | INT | snapshot when session starts |\n"
            "| `done_files` | INT | live counter |\n"
            "| `created_at` | TEXT | ISO timestamp |\n"
            "| `updated_at` | TEXT | ISO timestamp |\n\n"
            "**`jobs`** — one row per file in a session.\n\n"
            "| Column | Type | Notes |\n"
            "|---|---|---|\n"
            "| `id` | INT PK auto | |\n"
            "| `session_id` | TEXT | logical FK to `sessions.id` |\n"
            "| `filename`, `original_path` | TEXT | basename and absolute path |\n"
            "| `original_size_mb`, `final_size_mb`, `space_saved_mb` | REAL | |\n"
            "| `original_hash`, `encoded_hash` | TEXT | sha256(size + head4MB + tail4MB) |\n"
            "| `crf_used`, `encoder_used` | INT / TEXT | settings used at encode time |\n"
            "| `status` | TEXT | `queued` / `encoding` / `completed` / `failed` / `skipped` / `interrupted` |\n"
            "| `current_frame`, `total_frames`, `pct` | INT / REAL | live progress |\n"
            "| `fps`, `speed` | TEXT | strings as ffmpeg reports them (e.g. `30.0`, `1.5x`) |\n"
            "| `eta_s` | INT | seconds remaining |\n"
            "| `error_msg` | TEXT | populated on failure (includes ffmpeg stderr tail) |\n"
            "| `started_at`, `completed_at` | TEXT | |\n"
            "| `source_metadata`, `destination_metadata` | TEXT (JSON) | full ffprobe snapshot (v3.3+) |\n"
            "| `ffmpeg_cmd` | TEXT | exact command used (v3.3+) |\n\n"
            "**`scan_results`** — single row, replaced on each new scan. Holds a JSON "
            "blob of the `ScannedFile` list plus the `saved_at` timestamp.\n\n"
            "**JSONL event log** (one file per session under `/data/logs/`): one JSON "
            "object per line, no header. Event types: `queue_start`, `queue_done`, "
            "`queue_stopped`, `file_start`, `file_done`, `step`, `progress`, `error`, "
            "`skipped`, `stopped`, `done`, `ffmpeg_cmd`."
        ),
    },
    {
        "id": "config_env",
        "title": "10. Environment variables (.env)",
        "body": (
            "These are read by `docker-compose.yml` and passed to the containers. "
            "`.env` is optional — Postgres defaults are insecure-but-working "
            "out-of-the-box. **In any non-local deployment, copy `.env.example` to "
            "`.env` and set a strong password before the first `docker compose up`.**\n\n"
            "| Variable | Default | Effect |\n"
            "|---|---|---|\n"
            "| `DB_BACKEND` | `postgres` (v3.4+) | `postgres` or `sqlite`. Sqlite stores in `/data/reencoder.db`; Postgres uses the bundled service. |\n"
            "| `POSTGRES_HOST` | `postgres` | service name on the compose network |\n"
            "| `POSTGRES_PORT` | `5432` | |\n"
            "| `POSTGRES_USER` | `reencoder` | |\n"
            "| `POSTGRES_PASSWORD` | `reencoder` | **change in production**; only applied on first volume init |\n"
            "| `POSTGRES_DB` | `reencoder` | |\n"
            "| `TZ` | `America/New_York` | timezone for timestamps; container-wide |\n"
            "| `BASIC_AUTH_USER` | empty | enable HTTP Basic auth when set together with PASS |\n"
            "| `BASIC_AUTH_PASS` | empty | the password for Basic auth |\n"
            "| `PYTHONUNBUFFERED` | `1` | so `print()` shows up immediately in `docker logs` |\n\n"
            "**Reminders on Postgres password:** Postgres only applies "
            "`POSTGRES_PASSWORD` when the data volume is empty. If you change it on a "
            "live deploy you must either wipe `data/postgres/` (loses history — make "
            "a backup first via History → Export JSON) or `ALTER USER reencoder WITH "
            "PASSWORD '<new>'` inside the container."
        ),
    },
    {
        "id": "config_json",
        "title": "11. Configuration fields (config.json)",
        "body": (
            "All UI-editable settings live in `/data/config.json` and map 1-to-1 with "
            "Pydantic fields in `app/models.py:Config`. The file is merged over "
            "defaults on every load, so adding a new field on upgrade is safe.\n\n"
            "**Scan and exclusion:**\n\n"
            "- `scan_folders: list[{path, threshold_mb}]` — folders to walk. Only "
            "files matching `extensions` and at least `threshold_mb` MB are returned. "
            "Threshold is **per-folder**, so you can require >4000MB for /movies but "
            ">300MB for /shorts.\n"
            "- `exclude_folders: list[str]` — case-insensitive prefix matches. Pruned "
            "from the walk so descending into giant subtrees is cheap.\n"
            "- `extensions: list[str]` — file extensions considered, lowercase, "
            "leading dot. Default: `.mkv .mp4 .avi .mov`.\n\n"
            "**Mandatory encoder parameters** (always applied):\n\n"
            "- `encoder: cpu | vaapi | qsv | nvenc` — see the per-encoder sections.\n"
            "- `crf: int` (1..51) — Constant Rate Factor. **Lower = bigger file, "
            "higher quality.** 23–28 is the typical HEVC range. 26 is a good default "
            "for most content.\n"
            "- `preset: ultrafast..slower` — x265 speed/efficiency trade-off.\n"
            "- `ffmpeg_threads: int` — libx265 thread count.\n\n"
            "**Paths and binaries:**\n\n"
            "- `hdd_temp_path: str` — where the encoded output lives during the run. "
            "Should be on a disk with enough space for the biggest file you'll encode.\n"
            "- `ffmpeg_path`, `ffprobe_path` — defaults to `ffmpeg`/`ffprobe` from "
            "PATH. Override only if you ship a custom build.\n"
            "- `vaapi_device_path: str` — default `/dev/dri/renderD128`. Change if "
            "your card lives at `card1` etc.\n\n"
            "**Behavior tuning:**\n\n"
            "- `full_hash: bool` (default `false`) — if true, hash the entire file "
            "with sha256 (slow but exact). If false, hash size + first 4MB + last 4MB.\n"
            "- `skip_hevc_below_kbps: int` (default `0` = off) — if the source is "
            "already HEVC at bitrate below this threshold, skip without encoding.\n"
            "- `stall_timeout_s: int` (default `60`) — kill FFmpeg if no frame "
            "progress for this many seconds.\n"
            "- `worker_poll_interval_s: float` (default `2.0`) — how often the worker "
            "polls the DB for new work.\n"
            "- `stop_check_interval_s: float` (default `0.5`) — how often the worker "
            "checks for Stop during an encode.\n\n"
            "**Logs and retention:**\n\n"
            "- `log_retention_days: int` (default `30`, `0` = forever).\n"
            "- `clean_logs_on_startup: bool` (default `true`).\n"
            "- `log_buffer_size: int` (default `200`) — UI keeps last N lines in "
            "memory.\n\n"
            "**Appearance and branding:**\n\n"
            "- `theme: dark | light | auto`\n"
            "- `accent_color: '#RRGGBB'` — overrides `--accent`/`--accent2` CSS vars.\n"
            "- `brand_name: str` — header title, defaults to `Transcode Talker`.\n\n"
            "**Authentication and timezone:**\n\n"
            "- `basic_auth_user`, `basic_auth_pass` — same effect as the env vars but "
            "applied via UI.\n"
            "- `timezone: str` — overrides the `TZ` env var. Empty string falls back "
            "to system tz.\n\n"
            "**Advanced encode** (`advanced_encode: dict`) — see section 14."
        ),
    },
    {
        "id": "api_reference",
        "title": "12. API reference",
        "body": (
            "All endpoints return JSON unless noted otherwise. Auth is HTTP Basic when "
            "configured (`BASIC_AUTH_USER`+`BASIC_AUTH_PASS`). The single exception is "
            "`/api/health`, which is always anonymous so Docker healthchecks work.\n\n"
            "**Health and meta:**\n"
            "- `GET /` — serves the React UI.\n"
            "- `GET /api/health` — `{ok, ts}`.\n"
            "- `WS  /ws` — server-to-client event stream.\n\n"
            "**Config:**\n"
            "- `GET  /api/config` — returns merged config (defaults + saved).\n"
            "- `POST /api/config` — body is the full `Config` model (extra=allow).\n"
            "- `GET  /api/config/first-run` — `{first_run: bool}`.\n"
            "- `POST /api/config/exclude-folder` — `{path}` idempotently appended.\n\n"
            "**Browse:**\n"
            "- `GET /api/browse?path=...` — list subdirectories. Restricted to `/mnt` "
            "and the configured scan roots to prevent path traversal (B-006 fix).\n\n"
            "**Scan:**\n"
            "- `POST /api/scan` — run scan now and replace the saved snapshot.\n"
            "- `GET  /api/scan/last` — return the saved snapshot.\n\n"
            "**Encode:**\n"
            "- `POST /api/encode/start` — `{paths}`. 400 if paths are missing or "
            "don't exist. 409 with `{error, active_session_id}` if a session is "
            "already running.\n"
            "- `POST /api/encode/stop` — marks current session interrupted and "
            "cancels its queued/encoding jobs.\n"
            "- `POST /api/encode/force-reset` (v3.4) — nukes all `running` sessions. "
            "Defence-in-depth for stuck zombie sessions.\n"
            "- `POST /api/encode/queue/add` — `{paths}` appended to the running "
            "session. 409 if no session is active.\n"
            "- `GET  /api/encode/status` — compact status `{running, session_id, "
            "total, done, current_job}` for the nav badge.\n\n"
            "**Session and history:**\n"
            "- `GET  /api/session/active` — active OR most-recent session with jobs + "
            "events. Used for full UI sync.\n"
            "- `GET  /api/history?limit&offset&sort_by&order&filter_encoder&"
            "filter_status&from_date&to_date` — paginated, filtered, sorted history.\n"
            "- `GET  /api/history/stats` — totals.\n"
            "- `GET  /api/history/encoded-paths` — set of already-encoded paths (for "
            "the UI badge).\n"
            "- `GET  /api/history/export` — full v2 schema export (includes per-job "
            "metadata + events).\n"
            "- `POST /api/history/import` — merge import, de-duped by (path, "
            "completed_at), pre-import snapshot taken.\n"
            "- `DELETE /api/history/{id}` and `POST /api/history/{id}/delete` — same "
            "thing, 409 if the job is active.\n"
            "- `POST /api/history/bulk-delete` — `{ids}` deletes many at once, skips "
            "active ones.\n\n"
            "**Logs per job:**\n"
            "- `GET /api/jobs/{id}/logs?q=<search>` — filtered slice of the JSONL.\n"
            "- `GET /api/jobs/{id}/logs/export?fmt=json|text` — download.\n\n"
            "**Database admin:**\n"
            "- `GET  /api/db/state` — startup diagnosis + active backend.\n"
            "- `GET  /api/db/backups` — list snapshots newest-first (SQLite + Postgres).\n"
            "- `POST /api/db/backup` — take manual snapshot, `{label?}`.\n"
            "- `POST /api/db/restore` — `{name}`. Refused during active encode (409). "
            "Pre-restore snapshot always created.\n\n"
            "**HDD (legacy):**\n"
            "- `GET  /api/hdd/status` — temp dir listing + disk usage.\n"
            "- `POST /api/hdd/clean` — wipe temp dir, 409 if encoding.\n\n"
            "**Manual:**\n"
            "- `GET /api/help?lang=...` — this manual."
        ),
    },
    {
        "id": "frontend",
        "title": "13. Front-end (static/index.html)",
        "body": (
            "The entire UI lives in **one HTML file** of ~2100 lines. It loads React "
            "18 and ReactDOM from unpkg CDN, plus `@babel/standalone` to transform "
            "JSX in the browser. There is no bundler, no `npm install`, no "
            "TypeScript — start the API and the UI is served directly.\n\n"
            "**Pages:**\n\n"
            "- **Scan & Select** — runs scans, groups files by folder in a "
            "collapsible tree, lets you filter (all / never encoded / done), "
            "supports add-to-exclusion, and shows per-folder completion badges "
            "(green = all encoded, yellow = some pending, gray = empty).\n"
            "- **Encode** — current job progress bar, queue list, live event log "
            "(coloured by event type), Clear event logs button.\n"
            "- **History** — paginated table with column sort and filter bar "
            "(encoder, status, date range). Export/Import JSON. Per-row View opens "
            "the JobLogModal.\n"
            "- **Settings** — collapsible sections (Scan folders, Exclude folders, "
            "Encode, Appearance, Log Management, Authentication, Database Backups, "
            "Advanced). Each field has an `ⓘ` tooltip.\n"
            "- **Encode Settings** — the 4 mandatory parameters at top + 10 "
            "toggleable advanced cards (see section 14).\n"
            "- **Help** — this manual, multilingual.\n\n"
            "**Critical components:**\n\n"
            "- `api` object — wrappers around `fetch` GET/POST that add `_ok` and "
            "`_status` to the response. Errors surface as toast notifications instead "
            "of generic 'Failed'.\n"
            "- `EncodeBar` — persistent top banner whenever a session is running.\n"
            "- `JobLogModal` — three tabs: Details (source vs destination cards), "
            "Events (filtered JSONL), FFmpeg cmd (copy button).\n"
            "- `DirBrowser` — modal driven by `/api/browse`.\n"
            "- App-level WebSocket handler — exponential backoff (1, 2, 4, 8, max "
            "30s) on reconnect. Calls `syncFromServer()` on every open. Snappy "
            "progress events update only counters; structural events trigger a "
            "full re-sync.\n\n"
            "**Theming** — CSS variables on `:root`. `theme` toggles a class, "
            "`accent_color` overrides `--accent`. v3.4 added `--selected-bg` and "
            "`--selected-fg` so selection highlights work in both light and dark."
        ),
    },
    {
        "id": "backend_modules",
        "title": "14. Back-end modules",
        "body": (
            "**`reencoder-api/app/main.py`** — FastAPI entry point. Every HTTP "
            "endpoint, the `/ws` WebSocket handler, the 1-second event broadcaster "
            "background task, and the startup hook (mkdir logs, init schema, take "
            "startup DB snapshot, prune old logs).\n\n"
            "**`reencoder-api/app/database.py`** — Data Access Layer. Since v3.3 it "
            "is a thin wrapper around SQLAlchemy 2.x Core that translates legacy `?` "
            "placeholders to named binds (`:p0`, `:p1`, ...) on the fly. `RETURNING "
            "id` on Postgres; `lastrowid` on SQLite. The same shape of API the worker "
            "uses too.\n\n"
            "**`reencoder-api/app/db_engine.py`** — Engine factory. Defines tables "
            "via `Table` objects, sets PRAGMA WAL+NORMAL on SQLite via "
            "`event.listens_for('connect')`, runs migrations.\n\n"
            "**`reencoder-api/app/db_backend.py`** — Decides which backend to use "
            "based on `DB_BACKEND` env var. Builds the SQLAlchemy URL.\n\n"
            "**`reencoder-api/app/db_backup.py`** — Snapshot and restore. Branches on "
            "dialect: SQLite uses online backup API; Postgres uses `pg_dump -Fc -Z 6` "
            "and `pg_restore --clean --if-exists`. Cross-backend restore is refused.\n\n"
            "**`reencoder-api/app/config.py`** — `/data/config.json` load/save with "
            "merge over defaults. `first_run` detection.\n\n"
            "**`reencoder-api/app/models.py`** — Pydantic models. `Config` has "
            "`extra='allow'` so adding a field doesn't break old config files.\n\n"
            "**`reencoder-api/app/scanner.py`** — Filesystem walk. Prunes excluded "
            "dirs during `os.walk` for speed. Lowercases extensions on both sides. "
            "Returns `ScannedFile` instances sorted by size desc.\n\n"
            "**`reencoder-worker/worker/main.py`** — Worker loop. Signal handlers for "
            "SIGTERM/SIGINT set `SHUTDOWN[0] = True`. `recover_stale_jobs()` runs at "
            "startup (v3.4: with retry × 10 × 2s to tolerate Postgres cold start). "
            "Main loop polls the DB every `worker_poll_interval_s`, calls "
            "`process_session()` when a session is found. Heartbeat file at "
            "`/data/.worker_heartbeat` updated every iteration for the Docker "
            "healthcheck.\n\n"
            "**`reencoder-worker/worker/encoder.py`** — The FFmpeg pipeline. "
            "`file_hash()` (sha256 of size+head+tail, or full file if `full_hash`), "
            "`get_total_frames()` (nb_frames with duration*fps fallback), "
            "`_advanced_args()` (parses the toggles dict into FFmpeg args), "
            "`build_cmd()` (per-encoder command construction), "
            "`encode_file()` (orchestrates probe → spawn → progress loop → "
            "verify → atomic move). The progress thread reads stderr key=value "
            "lines; the main thread polls Stop and stall every 0.5s."
        ),
    },
    {
        "id": "ffmpeg_basics",
        "title": "15. FFmpeg basics — the mandatory parameters",
        "body": (
            "These four fields are always applied, regardless of encoder. They are "
            "what was supported in v3.1, and turning every advanced toggle off makes "
            "the encode behave exactly like v3.1.\n\n"
            "### `encoder`\n\n"
            "The pipeline used to produce HEVC video:\n\n"
            "- `cpu` — `libx265` software encoder. **Most compatible.** Slowest but "
            "produces the smallest files for a given CRF.\n"
            "- `vaapi` — AMD/Intel GPU via VAAPI. Fast. Quality is lower than "
            "libx265 at the same CRF but compression is still good. Requires "
            "`/dev/dri/renderD128` mapped into the container and `mesa-va-drivers` "
            "in the image (v3.4.1+ has this out of the box).\n"
            "- `qsv` — Intel Quick Sync Video. Very fast. Requires Intel iGPU + "
            "`intel-media-va-driver` and a QSV-enabled ffmpeg.\n"
            "- `nvenc` — NVIDIA GPU. Very fast. Requires NVIDIA drivers + Container "
            "Toolkit + an NVENC-enabled ffmpeg.\n\n"
            "### `crf` — Constant Rate Factor\n\n"
            "An integer from 1 to 51, interpreted by libx265 (and used as `-qp` by "
            "the GPU encoders). **Lower = bigger file, higher quality.** Scale:\n\n"
            "- 18 — visually lossless for most content. Files are big.\n"
            "- 23 — high quality. Default in many ffmpeg presets.\n"
            "- 26 — **the Transcode Talker default**. Good balance for HEVC.\n"
            "- 28 — visibly compressed but still watchable for casual content.\n"
            "- 32+ — strong compression, visible artefacts.\n\n"
            "CRF is **logarithmic-ish**: each +6 doubles bitrate. So 26 → 32 is "
            "roughly half the bitrate. For animation and clean sources you can often "
            "push CRF higher than for live action.\n\n"
            "### `preset`\n\n"
            "x265 speed-vs-efficiency trade-off: `ultrafast`, `superfast`, `veryfast`, "
            "`faster`, `fast`, `medium` (**default**), `slow`, `slower`. Going from "
            "`medium` to `slow` typically saves 5–10% bitrate at the same CRF, at the "
            "cost of ~2× encode time. `slower` adds another ~2× time for marginal "
            "gain. `ultrafast` is roughly 4× faster than `medium` but produces files "
            "20–30% larger.\n\n"
            "Note: for `nvenc` and `qsv` the same string is passed as `-preset` but "
            "the values map differently — see the per-encoder sections.\n\n"
            "### `ffmpeg_threads`\n\n"
            "Number of threads `libx265` spawns. Default 4. On a system with 8 cores, "
            "the optimal is usually slightly less than the core count (leave one for "
            "the OS). Going higher than the physical core count usually hurts. Only "
            "affects the CPU encoder."
        ),
    },
    {
        "id": "ffmpeg_cpu",
        "title": "16. FFmpeg encoder — `cpu` (libx265)",
        "body": (
            "The command shape (defaults, no advanced toggles):\n\n"
            "```\n"
            "ffmpeg -y \\\n"
            "  -progress pipe:2 -nostats \\\n"
            "  -i <source> \\\n"
            "  -map 0:V -map 0:a? -map 0:s? -map 0:t? \\\n"
            "  -c:v libx265 -crf <CRF> -preset <preset> -threads <N> \\\n"
            "  -c:a copy -c:s copy \\\n"
            "  -max_muxing_queue_size 1024 \\\n"
            "  <hdd_temp_path>/ENCODED_<stem><ext>\n"
            "```\n\n"
            "Why each flag:\n\n"
            "- `-y` — overwrite output without prompting.\n"
            "- `-progress pipe:2 -nostats` — emit machine-readable `key=value` "
            "progress lines on stderr (replaces the per-frame stats spam).\n"
            "- `-map 0:V` — all video streams from input 0. Capital V means "
            "non-attached pictures only.\n"
            "- `-map 0:a?` — all audio streams. The `?` makes it optional — files "
            "with no audio still encode.\n"
            "- `-map 0:s?` — all subtitle streams.\n"
            "- `-map 0:t?` — all attachments (fonts in MKV).\n"
            "- `-c:v libx265 -crf -preset -threads` — the encoder and its mandatory "
            "knobs.\n"
            "- `-c:a copy` — audio is bit-perfectly copied (no quality loss). When "
            "the `audio` advanced toggle is on, this becomes `-c:a <codec> -b:a "
            "<bitrate>`.\n"
            "- `-c:s copy` — subtitles copied verbatim.\n"
            "- `-max_muxing_queue_size 1024` — prevents the muxer from running out "
            "of buffer slots on files with many streams and high variance.\n\n"
            "**Why no `-r` (framerate) or `-vsync`?** Because the encoder defaults "
            "to passing through the source timestamps, which is exactly what we want "
            "for a faithful re-encode."
        ),
    },
    {
        "id": "ffmpeg_vaapi",
        "title": "17. FFmpeg encoder — `vaapi` (AMD/Intel GPU)",
        "body": (
            "Since v3.4.1, the canonical command (the legacy `-vaapi_device` and "
            "`-rc_mode` flags were removed because ffmpeg 7 rejects them — see "
            "B-020/B-021 in the main doc):\n\n"
            "```\n"
            "ffmpeg -y \\\n"
            "  -init_hw_device vaapi=va:/dev/dri/renderD128 \\\n"
            "  -filter_hw_device va \\\n"
            "  -progress pipe:2 -nostats \\\n"
            "  -i <source> \\\n"
            "  -map 0:V -map 0:a? -map 0:s? -map 0:t? \\\n"
            "  -vf format=nv12,hwupload \\\n"
            "  -c:v hevc_vaapi -qp <CRF> \\\n"
            "  -c:a copy -c:s copy \\\n"
            "  -max_muxing_queue_size 1024 \\\n"
            "  <hdd_temp_path>/ENCODED_<stem><ext>\n"
            "```\n\n"
            "Specifics:\n\n"
            "- `-init_hw_device vaapi=va:<dev>` — creates a hardware device named "
            "`va` from the DRM render node. `<dev>` is `vaapi_device_path` in the "
            "config (default `/dev/dri/renderD128`).\n"
            "- `-filter_hw_device va` — binds filter graph hwupload to that device. "
            "This is what makes `hwupload` know which GPU to upload to.\n"
            "- `-vf format=nv12,hwupload` — converts frames to NV12 in software, "
            "then uploads them to GPU memory. The encoder consumes GPU surfaces.\n"
            "- `-c:v hevc_vaapi` — the VAAPI HEVC encoder.\n"
            "- `-qp <CRF>` — Quantization Parameter. **Reuses the CRF value** even "
            "though VAAPI is technically QP-based and not CRF-based. Higher QP = "
            "smaller file, lower quality. The encoder picks `RC_MODE_CQP` "
            "automatically when QP is provided without an explicit rate-control "
            "mode.\n\n"
            "**Requirements inside the container** (v3.4.1+ ships these out of the "
            "box):\n\n"
            "- `apt-get install ffmpeg vainfo libva-drm2 libva2 mesa-va-drivers`.\n"
            "- The device `/dev/dri` must be mapped in `docker-compose.yml` "
            "(`devices: - /dev/dri:/dev/dri`).\n"
            "- The host must have a working Mesa/AMD or Intel driver.\n\n"
            "**Validation:** `docker compose exec reencoder-worker vainfo` should "
            "list profiles like `HEVCMain`. If it says `Failed to initialize libva`, "
            "the device is not mapped or the host driver is missing."
        ),
    },
    {
        "id": "ffmpeg_qsv",
        "title": "18. FFmpeg encoder — `qsv` (Intel Quick Sync)",
        "body": (
            "```\n"
            "ffmpeg -y \\\n"
            "  -init_hw_device qsv=qs:/dev/dri/renderD128 \\\n"
            "  -filter_hw_device qs \\\n"
            "  -hwaccel qsv -hwaccel_output_format qsv \\\n"
            "  -progress pipe:2 -nostats \\\n"
            "  -i <source> \\\n"
            "  -map 0:V -map 0:a? -map 0:s? -map 0:t? \\\n"
            "  -c:v hevc_qsv -global_quality <CRF> -preset <preset> \\\n"
            "  -c:a copy -c:s copy \\\n"
            "  -max_muxing_queue_size 1024 \\\n"
            "  <hdd_temp_path>/ENCODED_<stem><ext>\n"
            "```\n\n"
            "Specifics:\n\n"
            "- `-hwaccel qsv` + `-hwaccel_output_format qsv` — decode and stay in "
            "GPU surfaces end-to-end. This is what makes QSV genuinely fast on Intel.\n"
            "- `-c:v hevc_qsv` — the QSV HEVC encoder.\n"
            "- `-global_quality <CRF>` — QSV's variable-quality knob. Same scale as "
            "CRF (lower = better).\n"
            "- `-preset` — `veryfast` … `veryslow`. The mapping is different from "
            "libx265, but the intent (speed vs efficiency) is the same.\n\n"
            "**Requirements:** Intel iGPU + `intel-media-va-driver` (or "
            "`intel-media-va-driver-non-free`) + a QSV-enabled FFmpeg build. The "
            "default Debian `ffmpeg` package usually does **not** include QSV — for "
            "Intel hardware, use `jellyfin-ffmpeg` or the Intel oneVPL builds."
        ),
    },
    {
        "id": "ffmpeg_nvenc",
        "title": "19. FFmpeg encoder — `nvenc` (NVIDIA GPU)",
        "body": (
            "```\n"
            "ffmpeg -y \\\n"
            "  -progress pipe:2 -nostats \\\n"
            "  -i <source> \\\n"
            "  -map 0:V -map 0:a? -map 0:s? -map 0:t? \\\n"
            "  -c:v hevc_nvenc -rc constqp -qp <CRF> -preset <preset> \\\n"
            "  -c:a copy -c:s copy \\\n"
            "  -max_muxing_queue_size 1024 \\\n"
            "  <hdd_temp_path>/ENCODED_<stem><ext>\n"
            "```\n\n"
            "Specifics:\n\n"
            "- `-c:v hevc_nvenc` — NVIDIA's HEVC encoder. **GPU-only.** Decode is "
            "still done on the CPU here (no `-hwaccel cuda` in the current pipeline) — "
            "this keeps compatibility with any input pixel format. For 4K HEVC sources "
            "you might want to add `-hwaccel cuda -hwaccel_output_format cuda` "
            "manually.\n"
            "- `-rc constqp -qp <CRF>` — constant-QP mode. Mirrors the CRF intent: "
            "fixed quality, variable bitrate.\n"
            "- `-preset` — `p1` (fastest) through `p7` (slowest/best quality). "
            "Modern NVENC presets. The mapping from libx265 names is not exact; if "
            "you pass `medium` it is interpreted by the encoder.\n\n"
            "**Requirements:** NVIDIA GPU + matching host driver + `nvidia-"
            "container-toolkit` + a CUDA-enabled FFmpeg build. The default Debian "
            "`ffmpeg` package does **not** include NVENC — use `jellyfin-ffmpeg` or "
            "BtbN's prebuilt binaries.\n\n"
            "**Status (v3.4.1):** NVENC was not revalidated in the latest session. "
            "If it breaks in your environment, the encoder layer accepts the same "
            "`vaapi_device_path` value as a hint and the build is straightforward."
        ),
    },
    {
        "id": "ffmpeg_advanced",
        "title": "20. Advanced encode toggles",
        "body": (
            "The **Encode Settings** tab exposes 10 toggles in `advanced_encode`. "
            "Each toggle is `{enabled: bool, value: ...}` and is **off by default** — "
            "with everything off, the command is byte-identical to v3.1.\n\n"
            "### `bitrate`\n\n"
            "Sets `-b:v <value>` and optionally `-maxrate <value>` + `-bufsize "
            "<value*2>`. Use when you need a hard ceiling, e.g. for streaming. **CRF "
            "is usually a better idea** for archival re-encodes.\n\n"
            "### `tune`\n\n"
            "Adds `-tune <value>`. Allowed values for libx265: `psnr`, `ssim`, "
            "`grain`, `zerolatency`, `fastdecode`, `animation`. `animation` is "
            "particularly useful for anime; `grain` preserves film grain instead of "
            "smoothing it out.\n\n"
            "### `profile` and `level` and `tier`\n\n"
            "- `-profile:v` — `main`, `main10`, `main12`, etc. Compatibility shim "
            "for devices that only handle 8-bit Main profile.\n"
            "- `-level` — `4.1`, `5.0`, `5.1`, etc. Limits max bitrate and "
            "resolution × framerate.\n"
            "- `-tier` (CPU-only) — `main` or `high`. High allows higher bitrates "
            "at the same level.\n\n"
            "### `pixel_format` (CPU-only)\n\n"
            "Adds `-pix_fmt <value>`. Use `yuv420p10le` for 10-bit HEVC. Gives "
            "better gradients in dark scenes and often compresses better even for "
            "8-bit sources. Not supported by all hardware decoders.\n\n"
            "### `gop` (keyint)\n\n"
            "Adds `-g <keyint>`. Distance between keyframes. Default in x265 is "
            "250. Smaller = better seek granularity but bigger files; larger = "
            "better compression but slower seek.\n\n"
            "### `x265_params` (CPU-only)\n\n"
            "Raw x265 parameters string, e.g. `aq-mode=3:psy-rd=2.0`. Power user "
            "knob — see x265 docs.\n\n"
            "### `audio`\n\n"
            "Switches audio from copy to re-encode. `{codec: aac, bitrate: 192k}`. "
            "Use sparingly — re-encoding lossy audio is always a quality loss.\n\n"
            "### `video_filters` (CPU-only)\n\n"
            "Adds `-vf <filter_chain>`. Examples: `scale=-2:720` (downscale to "
            "720p), `crop=1920:800:0:140` (crop letterbox), `yadif` (deinterlace). "
            "Chain with commas: `crop=...,scale=...`."
        ),
    },
    {
        "id": "first_run",
        "title": "21. First run",
        "body": (
            "1. **Deploy.** From the repo root: `docker compose build && docker "
            "compose up -d`. This starts Postgres + API + Worker.\n"
            "2. **Open the UI** at `http://<host>:4246`.\n"
            "3. **Settings → Scan folders** — add at least one `{path, "
            "threshold_mb}` row. Pick a path that exists inside the container "
            "(`/mnt/media/Movies`, not `C:\\Movies`).\n"
            "4. **Settings → Encoder** — start with `cpu`. It is the most "
            "compatible. Try GPU encoders only after CPU works end-to-end.\n"
            "5. **Settings → CRF** — leave it at 26 unless you have a strong "
            "reason. Run one encode, eyeball the result, adjust if needed.\n"
            "6. **Settings → HDD temp path** — must be on a disk with at least the "
            "size of the biggest file you'll encode.\n"
            "7. **Save configuration**, then go to **Scan & Select**, click **⟳ "
            "Scan**, pick one file, click **▶ Encode**. Watch the Encode page."
        ),
    },
    {
        "id": "running_an_encode",
        "title": "22. Running an encode (regular workflow)",
        "body": (
            "1. **Scan & Select** — click **⟳ Scan** to refresh, then expand "
            "folders and tick files. Use the filters (`All` / `Never encoded` / "
            "`Done`) and the per-folder badges (green/yellow/gray) to skip files "
            "you have already processed.\n"
            "2. **Start the encode.** Click **▶ Encode**. The Encode page becomes "
            "active and you see the first file's progress bar.\n"
            "3. **Add more work mid-flight.** While encoding, the Scan page's "
            "button changes to **+ Add to Queue (N)**. Selecting more files and "
            "clicking it appends them to the running session via "
            "`POST /api/encode/queue/add`.\n"
            "4. **Stop.** Click **■ Stop**, confirm. The current file is "
            "interrupted within ~5 seconds; the rest of the queue is cancelled.\n"
            "5. **Close the browser and come back later.** Reopening the UI calls "
            "`/api/session/active` automatically and restores the progress bar, "
            "queue, and event log.\n"
            "6. **Reboot.** If the host reboots mid-encode, the worker comes back "
            "and marks the in-flight job as `failed`. Re-select it manually on the "
            "next scan."
        ),
    },
    {
        "id": "history",
        "title": "23. History page",
        "body": (
            "Every job a worker has touched lives here forever (until you delete "
            "it).\n\n"
            "- **Filter** by encoder, status, or date range. Filters chain.\n"
            "- **Sort** by clicking any column header.\n"
            "- **View** opens the JobLogModal — three tabs:\n"
            "  - **Details** — source and destination ffprobe snapshots "
            "side-by-side (codec, resolution, pixel format, audio tracks with "
            "language/channels, subtitle tracks, attachments). Captured "
            "automatically since v3.3.\n"
            "  - **Events** — the JSONL log filtered for this job. Searchable "
            "(case-insensitive), exportable as `.txt` or `.json`.\n"
            "  - **FFmpeg cmd** — the exact command used. Copy button.\n"
            "- **Export JSON** — full v2 schema snapshot. Includes every job's "
            "metadata + events. Use this **before** any rebuild that could touch "
            "the database volume.\n"
            "- **Import JSON** — merges an export into the current DB. Accepts v1 "
            "(legacy) and v2 formats. De-dupes by `(original_path, completed_at)`. "
            "Active jobs are never overwritten. A pre-import DB snapshot is taken "
            "automatically so you can roll back."
        ),
    },
    {
        "id": "backups",
        "title": "24. Database backups",
        "body": (
            "Backups live in `/data/backups/`. They are dialect-aware:\n\n"
            "- **SQLite** snapshots use the SQLite online-backup API — safe to "
            "take while the API is live. Result: a `.db` file.\n"
            "- **Postgres** snapshots use `pg_dump -Fc -Z 6` (custom format, "
            "compressed). Result: a `.dump` file.\n\n"
            "Lifecycle:\n\n"
            "- **Automatic startup snapshot.** Every API start takes a snapshot "
            "labelled `startup`. The 10 most recent `startup` snapshots are kept; "
            "older ones are pruned.\n"
            "- **Manual snapshots.** Settings → Database Backups → Take snapshot. "
            "Manual snapshots are **never auto-pruned**.\n"
            "- **Pre-restore snapshot.** Any restore is preceded by a snapshot of "
            "the current state, so you can roll the restore back.\n"
            "- **Pre-import snapshot.** Any `POST /api/history/import` also takes a "
            "snapshot first.\n\n"
            "**Restore refuses to run during an active encode** (409 response). "
            "Cross-dialect restore (Postgres dump on a SQLite install, or vice "
            "versa) is rejected with 400 — use Export JSON instead.\n\n"
            "**Disaster recovery cookbook:**\n\n"
            "1. Settings → Database Backups → see if there is a recent `startup` "
            "snapshot.\n"
            "2. If yes, click Restore. Encoding must be stopped first.\n"
            "3. If no, look at `/data/backups/` directly — manual snapshots stick "
            "around.\n"
            "4. If nothing usable, use `POST /api/history/import` with a recent "
            "History → Export JSON you took yourself."
        ),
    },
    {
        "id": "logs_retention",
        "title": "25. Logs and retention",
        "body": (
            "Two log surfaces:\n\n"
            "- **Container logs** — `docker compose logs reencoder-api`/"
            "`reencoder-worker`. Configured to rotate at 10MB × 5 files via "
            "`docker-compose.yml`.\n"
            "- **JSONL session logs** — `/data/logs/session_<id>.jsonl`. One file "
            "per session, append-only. These are what the Event log on the Encode "
            "page reads from and what the JobLogModal slices by `job_id`.\n\n"
            "**Retention controls** (Settings → Log Management):\n\n"
            "- `log_retention_days` — 0 means keep forever; any positive integer "
            "means delete `session_*.jsonl` older than that many days.\n"
            "- `clean_logs_on_startup` — if false, the prune never runs "
            "automatically. You can still prune manually:\n\n"
            "```\n"
            "docker compose exec reencoder-api find /data/logs \\\n"
            "  -name 'session_*.jsonl' -mtime +30 -delete\n"
            "```"
        ),
    },
    {
        "id": "appearance",
        "title": "26. Appearance",
        "body": (
            "Settings → Appearance:\n\n"
            "- **Theme** — `dark` (default), `light`, or `auto`. Auto follows "
            "`prefers-color-scheme` from the OS.\n"
            "- **Accent colour** — picker. Overrides `--accent` and `--accent2` "
            "CSS variables in `:root`. Default `#8b5cf6`.\n"
            "- **Brand name** — header title. Default `Transcode Talker`. The "
            "project, paths, and container names stay `reencoder-v3` so deploys "
            "are not affected.\n\n"
            "Changes apply live without a page reload."
        ),
    },
    {
        "id": "testing",
        "title": "27. Testing",
        "body": (
            "Run from the repo root with the host Python:\n\n"
            "```\n"
            "pip install -r requirements-dev.txt\n"
            "pytest -v tests/\n"
            "```\n\n"
            "The `tests/conftest.py` fixtures force `DB_BACKEND=sqlite` and use "
            "monkey-patched `DB_PATH`/`LOGS_DIR` so the tests run hermetically "
            "without a Postgres container. They also provide `fake_ffmpeg` and "
            "`fake_ffprobe` shims so the encoder pipeline is exercised without "
            "actually running FFmpeg.\n\n"
            "**Suite layout (v3.4.1 — 140 tests):**\n\n"
            "- `test_database.py` — CRUD, recovery, active session, event log.\n"
            "- `test_api.py` — FastAPI endpoints with TestClient.\n"
            "- `test_encoder.py` — `encode_file` happy path + edge cases.\n"
            "- `test_e2e.py` — Worker + API together via thread + fake binaries.\n"
            "- `test_scanner.py` — walk + filters.\n"
            "- `test_bug_fixes.py` — regression for B-001..B-015.\n"
            "- `test_db_backup.py` — backup/restore endpoints.\n"
            "- `test_history_filters.py` — sort, filter, export/import.\n"
            "- `test_log_management.py` — view per-job, search, retention.\n"
            "- `test_advanced_config.py` — extra=allow + new fields.\n"
            "- `test_queue_add.py` — add-to-queue endpoint.\n"
            "- `test_advanced_encode.py` — every advanced toggle.\n"
            "- `test_exclude_folder.py` — idempotent add-to-exclusion.\n"
            "- `test_help.py` — this manual endpoint.\n"
            "- `test_encoder_vaapi.py` — VAAPI/QSV/NVENC args + negative regressions "
            "for B-020/B-021.\n"
            "- `test_db_backend.py` — DB_BACKEND env handling.\n"
            "- `test_metadata.py` — ffprobe full metadata capture.\n"
            "- `test_db_engine.py` — SQLAlchemy engine, qmark translator.\n"
            "- `test_db_backup_postgres.py` — pg_dump/pg_restore mocked.\n"
            "- `test_encode_start_dialects.py` — dialect-aware lock for B-018.\n"
            "- `test_theme_vars.py` — light-mode selection + theme-aware badges."
        ),
    },
    {
        "id": "useful_commands",
        "title": "28. Useful commands and maintenance",
        "body": (
            "```\n"
            "# Live logs\n"
            "docker compose logs -f reencoder-api\n"
            "docker compose logs -f reencoder-worker\n"
            "\n"
            "# Restart just the worker (preserves API + websocket clients)\n"
            "docker compose restart reencoder-worker\n"
            "\n"
            "# Healthcheck\n"
            "curl -s http://localhost:4246/api/health | jq\n"
            "\n"
            "# DB backend currently active\n"
            "curl -s http://localhost:4246/api/db/state | python3 -m json.tool\n"
            "\n"
            "# Postgres shell\n"
            "docker compose exec postgres psql -U reencoder -d reencoder\n"
            "  \\dt\n"
            "  SELECT id,status,total_files,done_files FROM sessions\n"
            "    ORDER BY created_at DESC LIMIT 10;\n"
            "  SELECT id,status,filename,pct FROM jobs\n"
            "    WHERE status IN ('queued','encoding');\n"
            "\n"
            "# SQLite shell (only when DB_BACKEND=sqlite)\n"
            "docker compose exec reencoder-api sqlite3 /data/reencoder.db\n"
            "\n"
            "# Force a recovery sweep (use after manual DB tweaks)\n"
            "curl -s -X POST http://localhost:4246/api/encode/force-reset \\\n"
            "  -H 'Content-Type: application/json' -d '{}'\n"
            "\n"
            "# Manual DB snapshot\n"
            "curl -s -X POST http://localhost:4246/api/db/backup \\\n"
            "  -H 'Content-Type: application/json' -d '{\"label\":\"pre-update\"}'\n"
            "curl -s http://localhost:4246/api/db/backups | python3 -m json.tool\n"
            "\n"
            "# Clean old JSONL session logs\n"
            "docker compose exec reencoder-api find /data/logs \\\n"
            "  -name 'session_*.jsonl' -mtime +30 -delete\n"
            "\n"
            "# Validate VAAPI inside the worker\n"
            "docker compose exec reencoder-worker ffmpeg -version 2>&1 | head -1\n"
            "docker compose exec reencoder-worker ffmpeg -hide_banner -hwaccels\n"
            "docker compose exec reencoder-worker vainfo 2>&1 | head -20\n"
            "\n"
            "# Rebuild from scratch (preserves volumes)\n"
            "docker compose down\n"
            "docker compose build --no-cache\n"
            "docker compose up -d\n"
            "\n"
            "# DANGER: full reset (deletes DB + logs + backups; preserves config.json)\n"
            "docker compose down\n"
            "sudo rm -rf data/postgres data/reencoder.db data/reencoder.db-wal \\\n"
            "            data/reencoder.db-shm data/logs data/backups\n"
            "docker compose build && docker compose up -d\n"
            "```"
        ),
    },
    {
        "id": "troubleshooting",
        "title": "29. Troubleshooting",
        "body": (
            "**Encode button does nothing, log shows `409 Conflict`.** You are on "
            "≤v3.3 against Postgres (B-018). Upgrade to v3.4+. Workaround: `POST "
            "/api/encode/force-reset`.\n\n"
            "**Light mode — selected row is invisible.** ≤v3.3 issue (B-019). "
            "Upgrade to v3.4+.\n\n"
            "**GPU encode fails with `Unrecognized option 'vaapi_device'` or "
            "`'rc_mode'`.** ≤v3.4 + ffmpeg 7 (B-020/B-021). Upgrade to v3.4.1+ and "
            "rebuild the worker: `docker compose build --no-cache reencoder-worker "
            "&& docker compose up -d`.\n\n"
            "**GPU encode fails with `Device creation failed: -12. Cannot allocate "
            "memory`.** ≤v3.4 (B-022) — the static FFmpeg has no VAAPI compiled and "
            "the image lacks `mesa-va-drivers`. Upgrade to v3.4.1+. Validate with "
            "`docker compose exec reencoder-worker vainfo`.\n\n"
            "**API in crash loop with `password authentication failed for user "
            "\"reencoder\"`.** `POSTGRES_PASSWORD` was changed after first boot; the "
            "volume still has the original password. Either wipe `data/postgres/` "
            "(loses history — back up first) or `ALTER USER reencoder WITH PASSWORD "
            "'<new>'` inside the container.\n\n"
            "**`database is locked` errors (SQLite only).** Make sure only one "
            "worker is running. Bump `worker_poll_interval_s` if many workers (not "
            "the default).\n\n"
            "**History disappeared after rebuild.** The API logs `WARNING: DB file "
            "exists but has no history rows` when this happens. Settings → Database "
            "Backups should have a `startup` snapshot from before the rebuild — "
            "restore it.\n\n"
            "**Encode stalls at `Computing hash...`.** Source file is on a slow "
            "filesystem (NFS/SMB). Either move to a faster path or set "
            "`full_hash=false` so only head+tail are hashed.\n\n"
            "**Progress stops updating but the encode is still running.** The "
            "event broadcaster may have died silently. `docker compose restart "
            "reencoder-api` fixes it without touching the encode."
        ),
    },
    {
        "id": "credits",
        "title": "30. Credits and references",
        "body": (
            "The name **Transcode Talker** is a nod to *Decode Talker* — a Cyberse "
            "Link Monster from Yu-Gi-Oh! Like its namesake, the goal is to take "
            "something larger and link it down into a leaner, more efficient form.\n\n"
            "Built on:\n\n"
            "- **FFmpeg** + libx265 + libva + Mesa drivers\n"
            "- **FastAPI** + **Uvicorn** + **Pydantic** + **SQLAlchemy 2.x**\n"
            "- **React 18** via unpkg CDN + `@babel/standalone`\n"
            "- **Postgres 16-alpine** (default) or **SQLite WAL** (legacy)\n"
            "- **Docker** + **Docker Compose**\n"
            "- **pytest** for the 140-test regression suite\n\n"
            "Maintainer: Rafael Mello."
        ),
    },
]


# ─────────────────────────────────────────────────────────────────────────────
# Other languages are appended below. Each list mirrors the EN structure
# (same `id` slugs, same order) with the body translated.
# ─────────────────────────────────────────────────────────────────────────────

_PT_BR = [
    {
        "id": "intro",
        "title": "1. O que é o Transcode Talker?",
        "body": (
            "O **Transcode Talker** é um re-encoder de vídeo em lote self-hosted. "
            "Ele varre as pastas que você configura, deixa você escolher quais "
            "arquivos re-encodar usando o FFmpeg (libx265 em CPU, ou um pipeline "
            "GPU — VAAPI/QSV/NVENC), e substitui o original pela versão HEVC menor "
            "**somente quando o resultado é de fato menor**. Se o arquivo "
            "re-encodado fica maior, é descartado e o job é marcado como `skipped`.\n\n"
            "É construído como dois containers Docker — uma **API + UI** e um "
            "**worker** — que compartilham estado através de um banco de dados "
            "(Postgres por default desde v3.4, SQLite WAL como legado) e arquivos "
            "JSONL de log. A separação é deliberada: encodes podem rodar por horas "
            "e o design garante que o encode continua mesmo se o navegador fecha, "
            "a API reinicia, ou o worker dá reboot. Apenas um worker morto no meio "
            "do encode perde o arquivo atual (que é recuperado como `failed` no "
            "próximo startup do worker).\n\n"
            "O objetivo é simples: reduzir o espaço em disco da sua biblioteca de "
            "mídia preservando todos os audios, legendas, attachments, e a mesma "
            "fidelidade de playback (controlada pelo CRF — Constant Rate Factor)."
        ),
    },
    {
        "id": "architecture",
        "title": "2. Visão geral da arquitetura",
        "body": (
            "Dois containers Docker e um container opcional de banco, em uma rede "
            "bridge privada:\n\n"
            "- **reencoder-api** (FastAPI na porta 4246) — serve a UI React, a API "
            "HTTP e o stream de eventos WebSocket. É dona do schema e lê/escreve "
            "no banco. **Não** spawna FFmpeg.\n"
            "- **reencoder-worker** (loop Python) — faz polling do banco a cada "
            "`worker_poll_interval_s` segundos buscando uma sessão `running` com "
            "jobs queued, e roda FFmpeg um arquivo de cada vez. Atualiza o "
            "progresso do job no banco e adiciona eventos ao log JSONL.\n"
            "- **postgres** (desde v3.4 default; opcional) — Postgres 16-alpine, "
            "dados persistidos em `data/postgres/`. SQLite continua suportado via "
            "`DB_BACKEND=sqlite`.\n\n"
            "Por que dois processos em vez de um? Três razões:\n\n"
            "1. **Resiliência.** Restart da FastAPI não mata o encode.\n"
            "2. **Isolamento de recursos.** O worker recebe limites dedicados de "
            "CPU/memória no docker-compose (8 CPU, 8G RAM por default).\n"
            "3. **Separação de responsabilidades.** A API é request/response + "
            "websocket; o worker é um gerenciador de subprocesso long-running.\n\n"
            "**Não há HTTP entre API e worker** — eles se comunicam exclusivamente "
            "via banco compartilhado (Postgres ou SQLite WAL) e arquivos JSONL de "
            "evento em `/data/logs/`. Isso é intencional: o banco é a única fonte "
            "da verdade, e adicionar HTTP entre eles só duplicaria estado."
        ),
    },
    {
        "id": "components_diagram",
        "title": "3. Diagrama de componentes",
        "body": (
            "```\n"
            "                 ┌─────────────────────┐\n"
            "                 │ Navegador (React)   │\n"
            "                 └─────────┬───────────┘\n"
            "                           │ HTTP + WebSocket\n"
            "                           ▼\n"
            "                 ┌─────────────────────┐\n"
            "                 │   reencoder-api     │  FastAPI :4246\n"
            "                 │  (FastAPI + Uvicorn)│  static/index.html\n"
            "                 └────┬────────────┬───┘\n"
            "                      │            │\n"
            "                      ▼            ▼\n"
            "             ┌─────────────┐  ┌──────────────┐\n"
            "             │   Banco     │  │  /data/logs/ │\n"
            "             │ (Postgres   │◄─┤  *.jsonl     │\n"
            "             │  ou SQLite) │  └──────────────┘\n"
            "             └──────┬──────┘          ▲\n"
            "                    │                 │\n"
            "                    ▼                 │\n"
            "             ┌─────────────────┐      │\n"
            "             │ reencoder-worker│──────┘  poll loop em Python\n"
            "             │  (loop Python)  │         chama FFmpeg\n"
            "             └────────┬────────┘\n"
            "                      │\n"
            "                      ▼\n"
            "             ┌────────────────────────┐\n"
            "             │  FFmpeg + /dev/dri     │  GPU VAAPI (AMD/Intel)\n"
            "             │  + /mnt/media          │  arquivos fonte\n"
            "             │  + /mnt/hdd            │  área temp de encode\n"
            "             └────────────────────────┘\n"
            "```\n\n"
            "Todo estado persistente fica em três lugares:\n\n"
            "- **Banco** (`/data/reencoder.db` para SQLite, ou o volume do "
            "container `postgres`) — tabelas `sessions`, `jobs`, `scan_results`.\n"
            "- **Arquivos JSONL de evento** (`/data/logs/session_<id>.jsonl`) — um "
            "arquivo append-only por sessão, com a timeline humana.\n"
            "- **Config** (`/data/config.json`) — todo setting editável pela UI."
        ),
    },
    {
        "id": "flow_scan_encode",
        "title": "4. Fluxo end-to-end: Scan → Selecionar → Encode",
        "body": (
            "```\n"
            "Usuário → UI:        POST /api/scan\n"
            "UI → API:            varre scan_folders, retorna lista de ScannedFile\n"
            "API → DB:            substitui row de scan_results com novo snapshot\n"
            "API → UI:            {files: [...]}\n"
            "\n"
            "Usuário → UI:        seleciona arquivos, clica ▶ Encode\n"
            "UI → API:            POST /api/encode/start {paths}\n"
            "API → DB:            checa que não há sessão ativa (lock dialect-aware,\n"
            "                     BEGIN IMMEDIATE no SQLite, pg_advisory_xact_lock\n"
            "                     no Postgres — ver B-018)\n"
            "API → DB:            INSERT session(running) + INSERT N jobs(queued)\n"
            "API → UI:            {ok, session_id}\n"
            "\n"
            "Loop do worker (cada worker_poll_interval_s, default 2s):\n"
            "  Worker → DB:       SELECT sessão ativa\n"
            "  Worker → DB:       SELECT próximo job queued nessa sessão\n"
            "  Worker → DB:       UPDATE job status=encoding\n"
            "  Worker → FFmpeg:   spawn com build_cmd(...)\n"
            "  Loop a cada 0.5s enquanto FFmpeg roda:\n"
            "    Worker → DB:     is_session_interrupted? (stop check)\n"
            "    FFmpeg → stderr: progresso key=value\n"
            "    Worker → DB:     update_job_progress(pct, frame, fps, speed, eta)\n"
            "                     (throttled a uma vez a cada 2s)\n"
            "    Worker → JSONL:  append evento progress\n"
            "  Quando FFmpeg sai:\n"
            "    Worker → ffprobe: verify_file (codec_name == libx265 / hevc)\n"
            "    Worker → fs:     compara tamanhos; skip se encoded >= original\n"
            "    Worker → fs:     shutil.move HDD_temp → path original\n"
            "    Worker → DB:     UPDATE job status=completed (ou skipped/failed)\n"
            "    Worker → DB:     UPDATE session.done_files++\n"
            "```\n\n"
            "**Event broadcaster da API** (task de background) tail-eia o arquivo "
            "JSONL de cada sessão a cada 1s e empurra novas linhas para cada cliente "
            "WebSocket conectado. A UI também chama `GET /api/session/active` em "
            "cada open de WebSocket para reconstruir o estado completo — então "
            "fechar/reabrir o browser, ou reiniciar a API, nunca dessincroniza a UI."
        ),
    },
    {
        "id": "flow_stop",
        "title": "5. Fluxo end-to-end: Stop",
        "body": (
            "```\n"
            "Usuário → UI:        clica ■ Stop, confirma\n"
            "UI → API:            POST /api/encode/stop\n"
            "API → DB:            UPDATE session status=interrupted\n"
            "API → DB:            UPDATE jobs status=interrupted\n"
            "                     WHERE status IN (queued, encoding)\n"
            "API → JSONL:         append evento queue_stopped\n"
            "API → UI:            {ok, cancelled}\n"
            "\n"
            "Worker (próximo tick de stop_check_interval_s, default 0.5s):\n"
            "  Worker → DB:       is_session_interrupted? → True\n"
            "  Worker → FFmpeg:   SIGTERM\n"
            "  Espera até 5 segundos:\n"
            "    Se ainda rodando: SIGKILL\n"
            "  Worker → fs:       _cleanup(hdd_encoded)  (apaga parcial)\n"
            "  Worker → DB:       finaliza estado do job\n"
            "```\n\n"
            "Stop é **graceful por default**: SIGTERM dá ao FFmpeg até 5 segundos "
            "para terminar de escrever o trailer de mux e sair limpo. Só se ele não "
            "responder o worker escala para SIGKILL. O arquivo parcial encoded na "
            "área temp do HDD é sempre apagado pelo `_cleanup()`.\n\n"
            "**O loop de Stop é crítico** porque o worker só checa o DB a cada 0.5s "
            "— então há uma janela pior caso de ~0.5s + ~5s entre clicar Stop e o "
            "FFmpeg realmente sair. É por design (apertado o suficiente pra UX, "
            "frouxo o suficiente pra não martelar o DB)."
        ),
    },
    {
        "id": "flow_recovery",
        "title": "6. Fluxo end-to-end: Recovery de crash",
        "body": (
            "Quando o container do worker inicia, ele roda `recover_stale_jobs()` "
            "antes de entrar no poll loop. Qualquer job com status `encoding` é "
            "marcado como `failed` com `error_msg='Worker crashed or restarted'`. "
            "Esse é o único jeito de um job estar em `encoding` sem um processo "
            "worker real rodando, porque o worker é single-threaded e escreve "
            "`status=encoding` no começo e `status=completed/skipped/failed` no "
            "final.\n\n"
            "```\n"
            "Startup do worker:\n"
            "  Worker → DB:       recover_stale_jobs(now)\n"
            "                     UPDATE jobs SET status='failed',\n"
            "                            error_msg='Worker crashed or restarted'\n"
            "                     WHERE status='encoding'\n"
            "  Worker → log:      \"Recovered N stale job(s)\"\n"
            "  (v3.4) Worker faz retry até 10 × 2s se o DB não estiver pronto —\n"
            "  tolera cold start lento do Postgres.\n"
            "  Worker → loop:     entra no poll loop principal\n"
            "```\n\n"
            "A UI expõe jobs recuperados via `GET /api/recovered-since-startup` "
            "para o front-end mostrar um banner notificando o usuário.\n\n"
            "**v3.4 também adicionou `/api/encode/force-reset`** como defesa em "
            "profundidade: se uma sessão fica `running` sem worker real (ex.: "
            "reboot do host + DB out-of-sync), o usuário pode bater nesse endpoint "
            "(ou aceitar o `confirm()` automático que a UI mostra em um 409 "
            "travado) para marcar todas as sessions `running` como `interrupted` e "
            "cancelar seus jobs queued/encoding."
        ),
    },
    {
        "id": "flow_websocket",
        "title": "7. Fluxo end-to-end: sync e reconnect do WebSocket",
        "body": (
            "```\n"
            "UI:                  conecta ws://host:4246/ws\n"
            "API:                 aceita, adiciona ao set _ws_clients\n"
            "UI:                  GET /api/session/active\n"
            "API → DB:            pega sessão ativa OU mais recente\n"
            "API → DB:            pega todos os jobs da sessão\n"
            "API → JSONL:         lê event log completo da sessão\n"
            "API → UI:            {session, jobs, events}\n"
            "UI:                  reconstrói barras de progresso, fila, log buffer\n"
            "\n"
            "Loop de background na API (cada 1s):\n"
            "  API → JSONL:       tail novas linhas da sessão ativa\n"
            "  API → todos WS:    broadcast novos eventos\n"
            "  (websockets mortos são removidos automaticamente em send error)\n"
            "\n"
            "Em WebSocket close:\n"
            "  UI:                espera com backoff exponencial (1s, 2s, 4s, 8s, max 30s)\n"
            "  UI:                reconecta, repete do topo\n"
            "```\n\n"
            "Eventos progress (`type: progress`) atualizam só os counters ao vivo "
            "(pct/fps/speed/eta) para snappiness. Qualquer coisa que muda estrutura "
            "— `file_start`, `file_done`, `queue_start`, `queue_done`, "
            "`queue_stopped` — dispara um `syncFromServer()` completo para a UI "
            "re-ler o estado autoritativo."
        ),
    },
    {
        "id": "directory_structure",
        "title": "8. Estrutura de diretórios e containers",
        "body": (
            "**Layout do repositório:**\n\n"
            "```\n"
            "reencoder-v3/\n"
            "├── docker-compose.yml\n"
            "├── .env.example                  # template para secrets de produção\n"
            "├── data/                         # volume persistente montado em /data\n"
            "│   ├── config.json               # config editável pela UI\n"
            "│   ├── config.example.json       # template publicável\n"
            "│   ├── reencoder.db              # SQLite (só com DB_BACKEND=sqlite)\n"
            "│   ├── postgres/                 # volume de dados do Postgres\n"
            "│   ├── backups/                  # snapshots automáticos + manuais\n"
            "│   └── logs/\n"
            "│       └── session_<id>.jsonl    # um event log por sessão\n"
            "├── reencoder-api/\n"
            "│   ├── Dockerfile\n"
            "│   ├── requirements.txt\n"
            "│   ├── app/\n"
            "│   │   ├── main.py               # endpoints FastAPI + WS\n"
            "│   │   ├── database.py           # DAL (SQLAlchemy Core)\n"
            "│   │   ├── db_engine.py          # factory de Engine + schema\n"
            "│   │   ├── db_backend.py         # switch SQLite/Postgres\n"
            "│   │   ├── db_backup.py          # snapshot + restore\n"
            "│   │   ├── config.py             # persistência do config.json\n"
            "│   │   ├── models.py             # models Pydantic\n"
            "│   │   ├── scanner.py            # walk de filesystem\n"
            "│   │   └── help_content.py       # este manual\n"
            "│   └── static/\n"
            "│       └── index.html            # UI React inline\n"
            "├── reencoder-worker/\n"
            "│   ├── Dockerfile                # apt ffmpeg + mesa-va-drivers (v3.4.1)\n"
            "│   ├── requirements.txt\n"
            "│   └── worker/\n"
            "│       ├── main.py               # poll loop + signal handling\n"
            "│       ├── encoder.py            # pipeline ffmpeg\n"
            "│       ├── database.py           # cópia byte-equiv do api/database.py\n"
            "│       ├── db_engine.py          # mirror\n"
            "│       └── db_backend.py         # mirror\n"
            "└── tests/                        # suite pytest (140 testes em v3.4.1)\n"
            "```\n\n"
            "**Expectativas do filesystem do host:**\n\n"
            "| Path host | Path container | Propósito |\n"
            "|---|---|---|\n"
            "| `./data` | `/data` | DB, config, logs, backups (compartilhado api+worker) |\n"
            "| `/mnt/animes` | `/mnt/animes` | biblioteca de mídia (read+write para o worker) |\n"
            "| `/mnt/media` | `/mnt/media` | biblioteca de mídia |\n"
            "| `/mnt/hdd` | `/mnt/hdd` | disco lento usado como área temp de encode |\n"
            "| `/dev/dri` | `/dev/dri` | device GPU (só worker, para VAAPI/QSV) |"
        ),
    },
    {
        "id": "data_model",
        "title": "9. Modelo de dados (schema do banco)",
        "body": (
            "Três tabelas, mesma forma em SQLite e Postgres. Migração é idempotente: "
            "todo `CREATE TABLE` usa `IF NOT EXISTS` e colunas novas são adicionadas "
            "via `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` no startup.\n\n"
            "**`sessions`** — uma row por clique de Start Encode.\n\n"
            "| Coluna | Tipo | Notas |\n"
            "|---|---|---|\n"
            "| `id` | TEXT PK | UUID truncado em 8 chars |\n"
            "| `status` | TEXT | `pending` / `running` / `completed` / `interrupted` |\n"
            "| `total_files` | INT | snapshot no início da sessão |\n"
            "| `done_files` | INT | counter ao vivo |\n"
            "| `created_at` | TEXT | timestamp ISO |\n"
            "| `updated_at` | TEXT | timestamp ISO |\n\n"
            "**`jobs`** — uma row por arquivo na sessão.\n\n"
            "| Coluna | Tipo | Notas |\n"
            "|---|---|---|\n"
            "| `id` | INT PK auto | |\n"
            "| `session_id` | TEXT | FK lógica para `sessions.id` |\n"
            "| `filename`, `original_path` | TEXT | basename e path absoluto |\n"
            "| `original_size_mb`, `final_size_mb`, `space_saved_mb` | REAL | |\n"
            "| `original_hash`, `encoded_hash` | TEXT | sha256(size + head4MB + tail4MB) |\n"
            "| `crf_used`, `encoder_used` | INT / TEXT | settings usados no encode |\n"
            "| `status` | TEXT | `queued` / `encoding` / `completed` / `failed` / `skipped` / `interrupted` |\n"
            "| `current_frame`, `total_frames`, `pct` | INT / REAL | progresso ao vivo |\n"
            "| `fps`, `speed` | TEXT | strings como ffmpeg reporta (`30.0`, `1.5x`) |\n"
            "| `eta_s` | INT | segundos restantes |\n"
            "| `error_msg` | TEXT | populado em falha (inclui tail do stderr do ffmpeg) |\n"
            "| `started_at`, `completed_at` | TEXT | |\n"
            "| `source_metadata`, `destination_metadata` | TEXT (JSON) | snapshot completo do ffprobe (v3.3+) |\n"
            "| `ffmpeg_cmd` | TEXT | comando exato usado (v3.3+) |\n\n"
            "**`scan_results`** — row única, substituída em cada novo scan. Guarda "
            "um blob JSON da lista de `ScannedFile` + o timestamp `saved_at`.\n\n"
            "**Event log JSONL** (um arquivo por sessão em `/data/logs/`): um "
            "objeto JSON por linha, sem header. Tipos de evento: `queue_start`, "
            "`queue_done`, `queue_stopped`, `file_start`, `file_done`, `step`, "
            "`progress`, `error`, `skipped`, `stopped`, `done`, `ffmpeg_cmd`."
        ),
    },
    {
        "id": "config_env",
        "title": "10. Variáveis de ambiente (.env)",
        "body": (
            "Lidas pelo `docker-compose.yml` e passadas aos containers. `.env` é "
            "opcional — os defaults do Postgres são inseguros-mas-funcionais "
            "out-of-the-box. **Em qualquer deploy não-local, copie `.env.example` "
            "para `.env` e defina uma senha forte antes do primeiro `docker "
            "compose up`.**\n\n"
            "| Variável | Default | Efeito |\n"
            "|---|---|---|\n"
            "| `DB_BACKEND` | `postgres` (v3.4+) | `postgres` ou `sqlite`. Sqlite guarda em `/data/reencoder.db`; Postgres usa o service bundled. |\n"
            "| `POSTGRES_HOST` | `postgres` | nome do service na rede compose |\n"
            "| `POSTGRES_PORT` | `5432` | |\n"
            "| `POSTGRES_USER` | `reencoder` | |\n"
            "| `POSTGRES_PASSWORD` | `reencoder` | **trocar em produção**; só aplicada no init inicial do volume |\n"
            "| `POSTGRES_DB` | `reencoder` | |\n"
            "| `TZ` | `America/New_York` | timezone para timestamps; container-wide |\n"
            "| `BASIC_AUTH_USER` | vazio | habilita HTTP Basic auth quando setado junto com PASS |\n"
            "| `BASIC_AUTH_PASS` | vazio | a senha para Basic auth |\n"
            "| `PYTHONUNBUFFERED` | `1` | para `print()` aparecer imediato em `docker logs` |\n\n"
            "**Lembretes sobre senha do Postgres:** o Postgres só aplica "
            "`POSTGRES_PASSWORD` quando o volume de dados está vazio. Se você "
            "trocar em deploy live, ou apague `data/postgres/` (perde histórico — "
            "faça backup primeiro via History → Export JSON) ou rode `ALTER USER "
            "reencoder WITH PASSWORD '<nova>'` dentro do container."
        ),
    },
    {
        "id": "config_json",
        "title": "11. Campos de configuração (config.json)",
        "body": (
            "Todos os settings editáveis pela UI ficam em `/data/config.json` e "
            "mapeiam 1-para-1 com os campos Pydantic em `app/models.py:Config`. O "
            "arquivo é mergeado sobre os defaults em cada load, então adicionar um "
            "campo novo no upgrade é seguro.\n\n"
            "**Scan e exclusão:**\n\n"
            "- `scan_folders: list[{path, threshold_mb}]` — pastas a varrer. "
            "Apenas arquivos que batem `extensions` e têm pelo menos `threshold_mb` "
            "MB são retornados. Threshold é **por pasta**, então você pode exigir "
            ">4000MB para /movies mas >300MB para /shorts.\n"
            "- `exclude_folders: list[str]` — match case-insensitive de prefixo. "
            "Removidas do walk para descer em subárvores gigantes ser barato.\n"
            "- `extensions: list[str]` — extensões consideradas, lowercase com "
            "ponto. Default: `.mkv .mp4 .avi .mov`.\n\n"
            "**Parâmetros obrigatórios do encoder** (sempre aplicados):\n\n"
            "- `encoder: cpu | vaapi | qsv | nvenc` — ver as seções por encoder.\n"
            "- `crf: int` (1..51) — Constant Rate Factor. **Menor = arquivo maior, "
            "qualidade maior.** 23–28 é o range típico HEVC. 26 é um bom default "
            "para a maior parte do conteúdo.\n"
            "- `preset: ultrafast..slower` — trade-off velocidade/eficiência x265.\n"
            "- `ffmpeg_threads: int` — quantas threads o libx265 usa.\n\n"
            "**Paths e binários:**\n\n"
            "- `hdd_temp_path: str` — onde o output encoded mora durante o run. "
            "Deve estar em disco com espaço para o maior arquivo que você vai "
            "encodar.\n"
            "- `ffmpeg_path`, `ffprobe_path` — default `ffmpeg`/`ffprobe` do PATH. "
            "Override só se tiver build custom.\n"
            "- `vaapi_device_path: str` — default `/dev/dri/renderD128`. Mude se "
            "sua placa mora em `card1` etc.\n\n"
            "**Tuning de comportamento:**\n\n"
            "- `full_hash: bool` (default `false`) — se true, hash do arquivo "
            "inteiro com sha256 (lento mas exato). Se false, hash size + primeiros "
            "4MB + últimos 4MB.\n"
            "- `skip_hevc_below_kbps: int` (default `0` = off) — se o source já é "
            "HEVC com bitrate abaixo desse threshold, pula sem encodar.\n"
            "- `stall_timeout_s: int` (default `60`) — mata FFmpeg se não houver "
            "progresso de frame por esses segundos.\n"
            "- `worker_poll_interval_s: float` (default `2.0`) — quão frequente o "
            "worker faz polling do DB.\n"
            "- `stop_check_interval_s: float` (default `0.5`) — quão frequente o "
            "worker checa por Stop durante um encode.\n\n"
            "**Logs e retenção:**\n\n"
            "- `log_retention_days: int` (default `30`, `0` = para sempre).\n"
            "- `clean_logs_on_startup: bool` (default `true`).\n"
            "- `log_buffer_size: int` (default `200`) — UI mantém últimas N linhas "
            "em memória.\n\n"
            "**Aparência e branding:**\n\n"
            "- `theme: dark | light | auto`\n"
            "- `accent_color: '#RRGGBB'` — sobrescreve CSS vars `--accent`/"
            "`--accent2`.\n"
            "- `brand_name: str` — título do header, default `Transcode Talker`.\n\n"
            "**Autenticação e timezone:**\n\n"
            "- `basic_auth_user`, `basic_auth_pass` — mesmo efeito das env vars mas "
            "aplicado pela UI.\n"
            "- `timezone: str` — sobrescreve a env var `TZ`. String vazia cai pro "
            "tz do sistema.\n\n"
            "**Advanced encode** (`advanced_encode: dict`) — ver seção 20."
        ),
    },
    {
        "id": "api_reference",
        "title": "12. Referência da API",
        "body": (
            "Todos os endpoints retornam JSON salvo nota em contrário. Auth é HTTP "
            "Basic quando configurado (`BASIC_AUTH_USER`+`BASIC_AUTH_PASS`). A "
            "única exceção é `/api/health`, sempre anônimo para os healthchecks do "
            "Docker funcionarem.\n\n"
            "**Health e meta:**\n"
            "- `GET /` — serve a UI React.\n"
            "- `GET /api/health` — `{ok, ts}`.\n"
            "- `WS  /ws` — stream de eventos servidor → cliente.\n\n"
            "**Config:**\n"
            "- `GET  /api/config` — retorna config mergeada (defaults + saved).\n"
            "- `POST /api/config` — body é o model `Config` completo (extra=allow).\n"
            "- `GET  /api/config/first-run` — `{first_run: bool}`.\n"
            "- `POST /api/config/exclude-folder` — `{path}` idempotentemente adicionado.\n\n"
            "**Browse:**\n"
            "- `GET /api/browse?path=...` — lista subdirs. Restrito a `/mnt` e às "
            "roots configuradas no scan para prevenir path traversal (fix B-006).\n\n"
            "**Scan:**\n"
            "- `POST /api/scan` — roda scan agora e substitui o snapshot salvo.\n"
            "- `GET  /api/scan/last` — retorna o snapshot salvo.\n\n"
            "**Encode:**\n"
            "- `POST /api/encode/start` — `{paths}`. 400 se paths ausentes ou não "
            "existem. 409 com `{error, active_session_id}` se já há sessão rodando.\n"
            "- `POST /api/encode/stop` — marca sessão atual interrupted e cancela "
            "jobs queued/encoding.\n"
            "- `POST /api/encode/force-reset` (v3.4) — destrava todas sessions "
            "`running`. Defesa em profundidade para sessões zumbi.\n"
            "- `POST /api/encode/queue/add` — `{paths}` adicionados à sessão "
            "running. 409 se não há sessão ativa.\n"
            "- `GET  /api/encode/status` — status compacto `{running, session_id, "
            "total, done, current_job}` para badge na nav.\n\n"
            "**Sessão e histórico:**\n"
            "- `GET  /api/session/active` — sessão ativa OU mais recente com jobs "
            "+ events. Usado para sync completo da UI.\n"
            "- `GET  /api/history?limit&offset&sort_by&order&filter_encoder&"
            "filter_status&from_date&to_date` — history paginado, filtrado, "
            "ordenado.\n"
            "- `GET  /api/history/stats` — totais.\n"
            "- `GET  /api/history/encoded-paths` — set de paths já encoded (para "
            "badge na UI).\n"
            "- `GET  /api/history/export` — export schema v2 completo (inclui "
            "metadata + events por job).\n"
            "- `POST /api/history/import` — merge, de-duplica por (path, "
            "completed_at), snapshot pré-import.\n"
            "- `DELETE /api/history/{id}` e `POST /api/history/{id}/delete` — "
            "mesma coisa, 409 se job ativo.\n"
            "- `POST /api/history/bulk-delete` — `{ids}` apaga vários, pula ativos.\n\n"
            "**Logs por job:**\n"
            "- `GET /api/jobs/{id}/logs?q=<search>` — slice filtrado do JSONL.\n"
            "- `GET /api/jobs/{id}/logs/export?fmt=json|text` — download.\n\n"
            "**Admin de banco:**\n"
            "- `GET  /api/db/state` — diagnóstico de startup + backend ativo.\n"
            "- `GET  /api/db/backups` — lista snapshots newest-first (SQLite + Postgres).\n"
            "- `POST /api/db/backup` — snapshot manual, `{label?}`.\n"
            "- `POST /api/db/restore` — `{name}`. Recusado durante encode ativo "
            "(409). Snapshot pré-restore sempre criado.\n\n"
            "**HDD (legado):**\n"
            "- `GET  /api/hdd/status` — listagem do temp dir + uso de disco.\n"
            "- `POST /api/hdd/clean` — limpa temp dir, 409 se encodando.\n\n"
            "**Manual:**\n"
            "- `GET /api/help?lang=...` — este manual."
        ),
    },
    {
        "id": "frontend",
        "title": "13. Front-end (static/index.html)",
        "body": (
            "A UI inteira vive em **um arquivo HTML** de ~2100 linhas. Carrega "
            "React 18 e ReactDOM da CDN unpkg, mais `@babel/standalone` para "
            "transformar JSX no browser. Sem bundler, sem `npm install`, sem "
            "TypeScript — sobe a API e a UI é servida direto.\n\n"
            "**Páginas:**\n\n"
            "- **Scan & Select** — roda scans, agrupa arquivos por pasta em árvore "
            "colapsável, deixa filtrar (todos / never encoded / done), suporta "
            "add-to-exclusion, e mostra badges de completude por pasta (verde = "
            "tudo encoded, amarelo = alguns pendentes, cinza = vazia).\n"
            "- **Encode** — barra de progresso do job atual, lista da fila, event "
            "log ao vivo (colorido por tipo de evento), botão Clear event logs.\n"
            "- **History** — tabela paginada com sort por coluna e filter bar "
            "(encoder, status, range de data). Export/Import JSON. View por row "
            "abre o JobLogModal.\n"
            "- **Settings** — sections colapsáveis (Scan folders, Exclude folders, "
            "Encode, Appearance, Log Management, Authentication, Database Backups, "
            "Advanced). Cada campo tem tooltip `ⓘ`.\n"
            "- **Encode Settings** — os 4 parâmetros obrigatórios no topo + 10 "
            "cards avançados toggleáveis (ver seção 20).\n"
            "- **Help** — este manual, multilíngue.\n\n"
            "**Componentes críticos:**\n\n"
            "- objeto `api` — wrappers em volta do `fetch` GET/POST que adicionam "
            "`_ok` e `_status` à response. Erros aparecem como toast em vez do "
            "genérico 'Failed'.\n"
            "- `EncodeBar` — banner persistente no topo sempre que há sessão "
            "rodando.\n"
            "- `JobLogModal` — três abas: Details (cards source vs destination), "
            "Events (JSONL filtrado), FFmpeg cmd (botão copiar).\n"
            "- `DirBrowser` — modal alimentado por `/api/browse`.\n"
            "- Handler WebSocket app-level — backoff exponencial (1, 2, 4, 8, max "
            "30s) no reconnect. Chama `syncFromServer()` em cada open. Eventos "
            "progress snappy atualizam só counters; eventos estruturais disparam "
            "re-sync completo.\n\n"
            "**Theming** — CSS variables no `:root`. `theme` faz toggle de classe, "
            "`accent_color` sobrescreve `--accent`. v3.4 adicionou `--selected-bg` "
            "e `--selected-fg` para o highlight de seleção funcionar em light e "
            "dark mode."
        ),
    },
    {
        "id": "backend_modules",
        "title": "14. Módulos do back-end",
        "body": (
            "**`reencoder-api/app/main.py`** — entry point da FastAPI. Todo "
            "endpoint HTTP, o handler do WebSocket `/ws`, a task de background do "
            "event broadcaster (1 segundo), e o startup hook (mkdir logs, init "
            "schema, snapshot DB de startup, poda de logs antigos).\n\n"
            "**`reencoder-api/app/database.py`** — Data Access Layer. Desde v3.3 é "
            "um wrapper fino em volta do SQLAlchemy 2.x Core que traduz placeholders "
            "`?` para named binds (`:p0`, `:p1`, ...) on the fly. `RETURNING id` no "
            "Postgres; `lastrowid` no SQLite. Mesma forma de API que o worker usa.\n\n"
            "**`reencoder-api/app/db_engine.py`** — Engine factory. Define tabelas "
            "via objetos `Table`, seta PRAGMA WAL+NORMAL no SQLite via "
            "`event.listens_for('connect')`, roda migrações.\n\n"
            "**`reencoder-api/app/db_backend.py`** — Decide qual backend usar pela "
            "env var `DB_BACKEND`. Constrói a URL SQLAlchemy.\n\n"
            "**`reencoder-api/app/db_backup.py`** — Snapshot e restore. Branches "
            "por dialect: SQLite usa a online backup API; Postgres usa `pg_dump "
            "-Fc -Z 6` e `pg_restore --clean --if-exists`. Restore cross-backend "
            "é recusado.\n\n"
            "**`reencoder-api/app/config.py`** — load/save do `/data/config.json` "
            "com merge sobre defaults. Detecção de `first_run`.\n\n"
            "**`reencoder-api/app/models.py`** — models Pydantic. `Config` tem "
            "`extra='allow'` para adicionar campo não quebrar configs antigas.\n\n"
            "**`reencoder-api/app/scanner.py`** — Walk de filesystem. Poda dirs "
            "excluídas durante `os.walk` por velocidade. Lowercase de extensões "
            "nos dois lados. Retorna `ScannedFile` ordenados por size desc.\n\n"
            "**`reencoder-worker/worker/main.py`** — Loop do worker. Handlers de "
            "sinal SIGTERM/SIGINT setam `SHUTDOWN[0] = True`. `recover_stale_jobs()` "
            "roda no startup (v3.4: com retry × 10 × 2s para tolerar cold start do "
            "Postgres). Loop principal faz polling do DB a cada "
            "`worker_poll_interval_s`, chama `process_session()` quando acha "
            "sessão. Heartbeat em `/data/.worker_heartbeat` atualizado a cada "
            "iteração para o healthcheck Docker.\n\n"
            "**`reencoder-worker/worker/encoder.py`** — O pipeline FFmpeg. "
            "`file_hash()` (sha256 de size+head+tail, ou full file se `full_hash`), "
            "`get_total_frames()` (nb_frames com fallback para duration*fps), "
            "`_advanced_args()` (parseia o dict de toggles em args FFmpeg), "
            "`build_cmd()` (construção do comando por encoder), "
            "`encode_file()` (orquestra probe → spawn → loop de progresso → "
            "verify → move atômico). A thread de progresso lê linhas key=value do "
            "stderr; a main thread faz polling de Stop e stall a cada 0.5s."
        ),
    },
    {
        "id": "ffmpeg_basics",
        "title": "15. Básico do FFmpeg — parâmetros obrigatórios",
        "body": (
            "Esses quatro campos são sempre aplicados, independente do encoder. São "
            "o que estava suportado na v3.1, e desligar todos os toggles avançados "
            "faz o encode se comportar exatamente como v3.1.\n\n"
            "### `encoder`\n\n"
            "O pipeline usado para produzir vídeo HEVC:\n\n"
            "- `cpu` — encoder software `libx265`. **Mais compatível.** Mais lento "
            "mas produz os arquivos menores para um dado CRF.\n"
            "- `vaapi` — GPU AMD/Intel via VAAPI. Rápido. Qualidade é inferior à do "
            "libx265 com o mesmo CRF mas compressão ainda é boa. Requer "
            "`/dev/dri/renderD128` mapeado no container e `mesa-va-drivers` na "
            "imagem (v3.4.1+ já vem com isso out of the box).\n"
            "- `qsv` — Intel Quick Sync Video. Muito rápido. Requer iGPU Intel + "
            "`intel-media-va-driver` e um ffmpeg com QSV habilitado.\n"
            "- `nvenc` — GPU NVIDIA. Muito rápido. Requer drivers NVIDIA + "
            "Container Toolkit + um ffmpeg com NVENC habilitado.\n\n"
            "### `crf` — Constant Rate Factor\n\n"
            "Inteiro de 1 a 51, interpretado pelo libx265 (e usado como `-qp` pelos "
            "encoders GPU). **Menor = arquivo maior, qualidade maior.** Escala:\n\n"
            "- 18 — visualmente lossless para a maior parte do conteúdo. Arquivos "
            "grandes.\n"
            "- 23 — alta qualidade. Default em muitos presets ffmpeg.\n"
            "- 26 — **default do Transcode Talker**. Boa balança para HEVC.\n"
            "- 28 — visivelmente comprimido mas ainda assistível para conteúdo "
            "casual.\n"
            "- 32+ — compressão forte, artefatos visíveis.\n\n"
            "CRF é **quase logarítmico**: cada +6 dobra bitrate. Então 26 → 32 é "
            "grosso modo metade do bitrate. Para animação e fontes limpas você "
            "pode geralmente subir o CRF mais que para live action.\n\n"
            "### `preset`\n\n"
            "Trade-off velocidade vs eficiência do x265: `ultrafast`, `superfast`, "
            "`veryfast`, `faster`, `fast`, `medium` (**default**), `slow`, "
            "`slower`. Ir de `medium` para `slow` tipicamente economiza 5–10% de "
            "bitrate no mesmo CRF, ao custo de ~2× tempo de encode. `slower` "
            "adiciona outro ~2× pra ganho marginal. `ultrafast` é cerca de 4× "
            "mais rápido que `medium` mas produz arquivos 20–30% maiores.\n\n"
            "Nota: para `nvenc` e `qsv` a mesma string é passada como `-preset` "
            "mas os valores mapeiam diferente — ver as seções por encoder.\n\n"
            "### `ffmpeg_threads`\n\n"
            "Número de threads que o `libx265` spawna. Default 4. Em um sistema "
            "de 8 cores, o ótimo é geralmente um pouco abaixo da contagem de "
            "cores (deixa um para o OS). Acima da contagem de cores físicos "
            "geralmente piora. Só afeta o encoder CPU."
        ),
    },
    {
        "id": "ffmpeg_cpu",
        "title": "16. Encoder FFmpeg — `cpu` (libx265)",
        "body": (
            "A forma do comando (defaults, sem toggles avançados):\n\n"
            "```\n"
            "ffmpeg -y \\\n"
            "  -progress pipe:2 -nostats \\\n"
            "  -i <source> \\\n"
            "  -map 0:V -map 0:a? -map 0:s? -map 0:t? \\\n"
            "  -c:v libx265 -crf <CRF> -preset <preset> -threads <N> \\\n"
            "  -c:a copy -c:s copy \\\n"
            "  -max_muxing_queue_size 1024 \\\n"
            "  <hdd_temp_path>/ENCODED_<stem><ext>\n"
            "```\n\n"
            "Por que cada flag:\n\n"
            "- `-y` — sobrescreve output sem perguntar.\n"
            "- `-progress pipe:2 -nostats` — emite linhas `key=value` "
            "machine-readable no stderr (substitui o spam de stats por frame).\n"
            "- `-map 0:V` — todas as streams de vídeo do input 0. V maiúsculo "
            "significa não-attached pictures only.\n"
            "- `-map 0:a?` — todas as streams de áudio. O `?` torna opcional — "
            "arquivos sem áudio ainda encodam.\n"
            "- `-map 0:s?` — todas as streams de legenda.\n"
            "- `-map 0:t?` — todos os attachments (fontes em MKV).\n"
            "- `-c:v libx265 -crf -preset -threads` — o encoder e seus knobs "
            "obrigatórios.\n"
            "- `-c:a copy` — áudio copiado bit-perfeito (zero perda). Quando o "
            "toggle avançado `audio` está ligado, vira `-c:a <codec> -b:a "
            "<bitrate>`.\n"
            "- `-c:s copy` — legendas copiadas verbatim.\n"
            "- `-max_muxing_queue_size 1024` — previne o muxer de ficar sem slots "
            "de buffer em arquivos com muitas streams e variância alta.\n\n"
            "**Por que sem `-r` (framerate) ou `-vsync`?** Porque o encoder "
            "default passa pelos timestamps do source, que é exatamente o que "
            "queremos para um re-encode fiel."
        ),
    },
    {
        "id": "ffmpeg_vaapi",
        "title": "17. Encoder FFmpeg — `vaapi` (GPU AMD/Intel)",
        "body": (
            "Desde v3.4.1, o comando canônico (os flags legados `-vaapi_device` e "
            "`-rc_mode` foram removidos porque o ffmpeg 7 rejeita — ver "
            "B-020/B-021 no doc principal):\n\n"
            "```\n"
            "ffmpeg -y \\\n"
            "  -init_hw_device vaapi=va:/dev/dri/renderD128 \\\n"
            "  -filter_hw_device va \\\n"
            "  -progress pipe:2 -nostats \\\n"
            "  -i <source> \\\n"
            "  -map 0:V -map 0:a? -map 0:s? -map 0:t? \\\n"
            "  -vf format=nv12,hwupload \\\n"
            "  -c:v hevc_vaapi -qp <CRF> \\\n"
            "  -c:a copy -c:s copy \\\n"
            "  -max_muxing_queue_size 1024 \\\n"
            "  <hdd_temp_path>/ENCODED_<stem><ext>\n"
            "```\n\n"
            "Especificidades:\n\n"
            "- `-init_hw_device vaapi=va:<dev>` — cria um device de hardware "
            "chamado `va` a partir do render node DRM. `<dev>` é "
            "`vaapi_device_path` na config (default `/dev/dri/renderD128`).\n"
            "- `-filter_hw_device va` — vincula o filter graph hwupload àquele "
            "device. É o que faz o `hwupload` saber em qual GPU fazer upload.\n"
            "- `-vf format=nv12,hwupload` — converte frames para NV12 em "
            "software, então faz upload para memória GPU. O encoder consome "
            "surfaces GPU.\n"
            "- `-c:v hevc_vaapi` — o encoder HEVC VAAPI.\n"
            "- `-qp <CRF>` — Quantization Parameter. **Reusa o valor do CRF** "
            "mesmo que VAAPI seja tecnicamente QP-based e não CRF-based. QP "
            "maior = arquivo menor, qualidade menor. O encoder escolhe "
            "`RC_MODE_CQP` automaticamente quando QP é dado sem rate-control "
            "explícito.\n\n"
            "**Requirements dentro do container** (v3.4.1+ já traz tudo):\n\n"
            "- `apt-get install ffmpeg vainfo libva-drm2 libva2 mesa-va-drivers`.\n"
            "- Device `/dev/dri` mapeado no `docker-compose.yml` (`devices: - "
            "/dev/dri:/dev/dri`).\n"
            "- O host deve ter driver Mesa/AMD ou Intel funcionando.\n\n"
            "**Validação:** `docker compose exec reencoder-worker vainfo` deve "
            "listar perfis tipo `HEVCMain`. Se sair `Failed to initialize libva`, "
            "device não está mapeado ou falta driver Mesa no host."
        ),
    },
    {
        "id": "ffmpeg_qsv",
        "title": "18. Encoder FFmpeg — `qsv` (Intel Quick Sync)",
        "body": (
            "```\n"
            "ffmpeg -y \\\n"
            "  -init_hw_device qsv=qs:/dev/dri/renderD128 \\\n"
            "  -filter_hw_device qs \\\n"
            "  -hwaccel qsv -hwaccel_output_format qsv \\\n"
            "  -progress pipe:2 -nostats \\\n"
            "  -i <source> \\\n"
            "  -map 0:V -map 0:a? -map 0:s? -map 0:t? \\\n"
            "  -c:v hevc_qsv -global_quality <CRF> -preset <preset> \\\n"
            "  -c:a copy -c:s copy \\\n"
            "  -max_muxing_queue_size 1024 \\\n"
            "  <hdd_temp_path>/ENCODED_<stem><ext>\n"
            "```\n\n"
            "Especificidades:\n\n"
            "- `-hwaccel qsv` + `-hwaccel_output_format qsv` — decode e fica em "
            "GPU surfaces end-to-end. É o que faz QSV ser genuinamente rápido em "
            "Intel.\n"
            "- `-c:v hevc_qsv` — o encoder HEVC QSV.\n"
            "- `-global_quality <CRF>` — knob de qualidade variável do QSV. Mesma "
            "escala do CRF (menor = melhor).\n"
            "- `-preset` — `veryfast` … `veryslow`. O mapping é diferente do "
            "libx265, mas a intenção (velocidade vs eficiência) é a mesma.\n\n"
            "**Requirements:** iGPU Intel + `intel-media-va-driver` (ou "
            "`intel-media-va-driver-non-free`) + um build de FFmpeg com QSV. O "
            "pacote `ffmpeg` default do Debian geralmente **não** inclui QSV — "
            "para hardware Intel, use `jellyfin-ffmpeg` ou builds oneVPL da Intel."
        ),
    },
    {
        "id": "ffmpeg_nvenc",
        "title": "19. Encoder FFmpeg — `nvenc` (GPU NVIDIA)",
        "body": (
            "```\n"
            "ffmpeg -y \\\n"
            "  -progress pipe:2 -nostats \\\n"
            "  -i <source> \\\n"
            "  -map 0:V -map 0:a? -map 0:s? -map 0:t? \\\n"
            "  -c:v hevc_nvenc -rc constqp -qp <CRF> -preset <preset> \\\n"
            "  -c:a copy -c:s copy \\\n"
            "  -max_muxing_queue_size 1024 \\\n"
            "  <hdd_temp_path>/ENCODED_<stem><ext>\n"
            "```\n\n"
            "Especificidades:\n\n"
            "- `-c:v hevc_nvenc` — o encoder HEVC NVIDIA. **Encode-only.** Decode "
            "é feito na CPU aqui (sem `-hwaccel cuda` no pipeline atual) — isso "
            "mantém compatibilidade com qualquer pixel format de input. Para "
            "fontes HEVC 4K talvez você queira adicionar `-hwaccel cuda "
            "-hwaccel_output_format cuda` manualmente.\n"
            "- `-rc constqp -qp <CRF>` — modo constant-QP. Espelha a intenção do "
            "CRF: qualidade fixa, bitrate variável.\n"
            "- `-preset` — `p1` (mais rápido) até `p7` (mais lento/melhor "
            "qualidade). Presets modernos do NVENC. O mapping dos nomes libx265 "
            "não é exato; se passar `medium` é interpretado pelo encoder.\n\n"
            "**Requirements:** GPU NVIDIA + driver host compatível + "
            "`nvidia-container-toolkit` + um build de FFmpeg com CUDA. O pacote "
            "`ffmpeg` default do Debian **não** inclui NVENC — use "
            "`jellyfin-ffmpeg` ou os binários prebuilt do BtbN.\n\n"
            "**Status (v3.4.1):** NVENC não foi revalidado na sessão mais recente. "
            "Se quebrar no seu ambiente, a camada de encoder aceita o mesmo valor "
            "de `vaapi_device_path` como hint e o build é direto."
        ),
    },
    {
        "id": "ffmpeg_advanced",
        "title": "20. Toggles avançados de encode",
        "body": (
            "A aba **Encode Settings** expõe 10 toggles em `advanced_encode`. Cada "
            "toggle é `{enabled: bool, value: ...}` e está **desligado por "
            "default** — com tudo off, o comando é byte-idêntico à v3.1.\n\n"
            "### `bitrate`\n\n"
            "Seta `-b:v <value>` e opcionalmente `-maxrate <value>` + `-bufsize "
            "<value*2>`. Use quando precisar de um teto rígido, e.g. para "
            "streaming. **CRF geralmente é melhor ideia** para re-encodes de "
            "arquivo.\n\n"
            "### `tune`\n\n"
            "Adiciona `-tune <value>`. Valores permitidos para libx265: `psnr`, "
            "`ssim`, `grain`, `zerolatency`, `fastdecode`, `animation`. "
            "`animation` é particularmente útil para anime; `grain` preserva grão "
            "de filme em vez de suavizar.\n\n"
            "### `profile`, `level` e `tier`\n\n"
            "- `-profile:v` — `main`, `main10`, `main12`, etc. Compatibilidade "
            "para dispositivos que só aguentam Main profile 8-bit.\n"
            "- `-level` — `4.1`, `5.0`, `5.1`, etc. Limita bitrate máximo e "
            "resolução × framerate.\n"
            "- `-tier` (só CPU) — `main` ou `high`. High permite bitrates mais "
            "altos no mesmo level.\n\n"
            "### `pixel_format` (só CPU)\n\n"
            "Adiciona `-pix_fmt <value>`. Use `yuv420p10le` para HEVC 10-bit. Dá "
            "gradientes melhores em cenas escuras e geralmente comprime melhor "
            "mesmo para fontes 8-bit. Não suportado por todos os decoders de "
            "hardware.\n\n"
            "### `gop` (keyint)\n\n"
            "Adiciona `-g <keyint>`. Distância entre keyframes. Default do x265 é "
            "250. Menor = melhor granularidade de seek mas arquivos maiores; "
            "maior = melhor compressão mas seek mais lento.\n\n"
            "### `x265_params` (só CPU)\n\n"
            "String raw de parâmetros x265, e.g. `aq-mode=3:psy-rd=2.0`. Knob "
            "para power user — ver docs do x265.\n\n"
            "### `audio`\n\n"
            "Troca áudio de copy para re-encode. `{codec: aac, bitrate: 192k}`. "
            "Use com parcimônia — re-encodar áudio lossy é sempre perda de "
            "qualidade.\n\n"
            "### `video_filters` (só CPU)\n\n"
            "Adiciona `-vf <filter_chain>`. Exemplos: `scale=-2:720` (downscale "
            "para 720p), `crop=1920:800:0:140` (crop letterbox), `yadif` "
            "(deinterlace). Encadeie com vírgulas: `crop=...,scale=...`."
        ),
    },
    {
        "id": "first_run",
        "title": "21. Primeira execução",
        "body": (
            "1. **Deploy.** Da raiz do repo: `docker compose build && docker "
            "compose up -d`. Sobe Postgres + API + Worker.\n"
            "2. **Abra a UI** em `http://<host>:4246`.\n"
            "3. **Settings → Scan folders** — adicione pelo menos uma row `{path, "
            "threshold_mb}`. Escolha um path que existe dentro do container "
            "(`/mnt/media/Filmes`, não `C:\\Filmes`).\n"
            "4. **Settings → Encoder** — comece com `cpu`. É o mais compatível. "
            "Tente encoders GPU só depois do CPU funcionar end-to-end.\n"
            "5. **Settings → CRF** — deixe em 26 a menos que tenha motivo forte. "
            "Roda um encode, dá uma olhada no resultado, ajusta se precisar.\n"
            "6. **Settings → HDD temp path** — tem que estar em disco com pelo "
            "menos o tamanho do maior arquivo que vai encodar.\n"
            "7. **Save configuration**, então vá em **Scan & Select**, clique "
            "**⟳ Scan**, escolha um arquivo, clique **▶ Encode**. Acompanhe na "
            "página Encode."
        ),
    },
    {
        "id": "running_an_encode",
        "title": "22. Rodando um encode (fluxo regular)",
        "body": (
            "1. **Scan & Select** — clique **⟳ Scan** para atualizar, expanda "
            "pastas e marque arquivos. Use os filtros (`All` / `Never encoded` / "
            "`Done`) e os badges por pasta (verde/amarelo/cinza) para pular o que "
            "já foi processado.\n"
            "2. **Inicia o encode.** Clique **▶ Encode**. A página Encode fica "
            "ativa e você vê a barra de progresso do primeiro arquivo.\n"
            "3. **Adiciona mais trabalho em pleno voo.** Enquanto encodando, o "
            "botão na Scan vira **+ Add to Queue (N)**. Selecionar mais arquivos "
            "e clicar adiciona à sessão rodando via "
            "`POST /api/encode/queue/add`.\n"
            "4. **Stop.** Clique **■ Stop**, confirme. O arquivo atual é "
            "interrompido em ~5 segundos; o resto da fila é cancelado.\n"
            "5. **Fecha o browser e volta depois.** Reabrir a UI chama "
            "`/api/session/active` automaticamente e restaura barra de progresso, "
            "fila e event log.\n"
            "6. **Reboot.** Se o host reboota no meio do encode, o worker volta e "
            "marca o job in-flight como `failed`. Re-seleciona ele manualmente no "
            "próximo scan."
        ),
    },
    {
        "id": "history",
        "title": "23. Página de Histórico",
        "body": (
            "Todo job que um worker tocou fica aqui para sempre (até você apagar).\n\n"
            "- **Filtre** por encoder, status ou range de data. Filtros encadeiam.\n"
            "- **Ordene** clicando em qualquer header de coluna.\n"
            "- **View** abre o JobLogModal — três abas:\n"
            "  - **Details** — snapshots ffprobe de source e destination "
            "lado-a-lado (codec, resolução, pixel format, áudios com idioma/"
            "canais, legendas, attachments). Capturado automaticamente desde v3.3.\n"
            "  - **Events** — o log JSONL filtrado para esse job. Busca "
            "case-insensitive, export para `.txt` ou `.json`.\n"
            "  - **FFmpeg cmd** — o comando exato usado. Botão copiar.\n"
            "- **Export JSON** — snapshot schema v2 completo. Inclui metadata + "
            "events de cada job. Use isso **antes** de qualquer rebuild que possa "
            "tocar o volume do banco.\n"
            "- **Import JSON** — merge de um export no DB atual. Aceita formatos "
            "v1 (legado) e v2. De-duplica por `(original_path, completed_at)`. "
            "Jobs ativos nunca são sobrescritos. Um snapshot pré-import é tirado "
            "automaticamente para você poder reverter."
        ),
    },
    {
        "id": "backups",
        "title": "24. Backups de banco",
        "body": (
            "Backups vivem em `/data/backups/`. São dialect-aware:\n\n"
            "- **SQLite** snapshots usam a online-backup API do SQLite — seguro "
            "tirar com a API live. Resultado: arquivo `.db`.\n"
            "- **Postgres** snapshots usam `pg_dump -Fc -Z 6` (formato custom, "
            "comprimido). Resultado: arquivo `.dump`.\n\n"
            "Ciclo de vida:\n\n"
            "- **Snapshot automático de startup.** Todo start da API tira "
            "snapshot com label `startup`. Os 10 mais recentes são mantidos; "
            "antigos são podados.\n"
            "- **Snapshots manuais.** Settings → Database Backups → Take "
            "snapshot. Manuais **nunca** são auto-podados.\n"
            "- **Snapshot pré-restore.** Todo restore é precedido de snapshot do "
            "estado atual, então você consegue reverter o restore.\n"
            "- **Snapshot pré-import.** Todo `POST /api/history/import` também "
            "tira snapshot antes.\n\n"
            "**Restore se recusa a rodar durante encode ativo** (response 409). "
            "Restore cross-dialect (dump Postgres em SQLite, ou vice-versa) é "
            "rejeitado com 400 — use Export JSON em vez disso.\n\n"
            "**Receita de disaster recovery:**\n\n"
            "1. Settings → Database Backups → veja se tem um snapshot `startup` "
            "recente.\n"
            "2. Se sim, clique Restore. Encode tem que estar parado.\n"
            "3. Se não, olhe direto em `/data/backups/` — snapshots manuais "
            "ficam.\n"
            "4. Se nada utilizável, use `POST /api/history/import` com um "
            "History → Export JSON recente que você mesmo fez."
        ),
    },
    {
        "id": "logs_retention",
        "title": "25. Logs e retenção",
        "body": (
            "Duas superfícies de log:\n\n"
            "- **Logs de container** — `docker compose logs reencoder-api`/"
            "`reencoder-worker`. Configurado para rotacionar em 10MB × 5 arquivos "
            "via `docker-compose.yml`.\n"
            "- **Logs de sessão JSONL** — `/data/logs/session_<id>.jsonl`. Um "
            "arquivo por sessão, append-only. É de onde o Event log na página "
            "Encode lê e o que o JobLogModal fatia por `job_id`.\n\n"
            "**Controles de retenção** (Settings → Log Management):\n\n"
            "- `log_retention_days` — 0 mantém para sempre; qualquer inteiro "
            "positivo apaga `session_*.jsonl` mais antigo que tantos dias.\n"
            "- `clean_logs_on_startup` — se false, a poda nunca roda "
            "automaticamente. Você ainda pode podar manualmente:\n\n"
            "```\n"
            "docker compose exec reencoder-api find /data/logs \\\n"
            "  -name 'session_*.jsonl' -mtime +30 -delete\n"
            "```"
        ),
    },
    {
        "id": "appearance",
        "title": "26. Aparência",
        "body": (
            "Settings → Appearance:\n\n"
            "- **Theme** — `dark` (default), `light`, ou `auto`. Auto segue "
            "`prefers-color-scheme` do OS.\n"
            "- **Accent colour** — picker. Sobrescreve CSS vars `--accent` e "
            "`--accent2` no `:root`. Default `#8b5cf6`.\n"
            "- **Brand name** — título do header. Default `Transcode Talker`. O "
            "projeto, paths e nomes de container ficam `reencoder-v3` para não "
            "afetar deploys.\n\n"
            "Mudanças aplicam ao vivo sem reload."
        ),
    },
    {
        "id": "testing",
        "title": "27. Testes",
        "body": (
            "Rode da raiz do repo com o Python do host:\n\n"
            "```\n"
            "pip install -r requirements-dev.txt\n"
            "pytest -v tests/\n"
            "```\n\n"
            "As fixtures de `tests/conftest.py` forçam `DB_BACKEND=sqlite` e usam "
            "`DB_PATH`/`LOGS_DIR` monkey-patched para os testes rodarem "
            "hermeticamente sem container Postgres. Também provêem shims "
            "`fake_ffmpeg` e `fake_ffprobe` para o pipeline do encoder ser "
            "exercitado sem rodar FFmpeg de verdade.\n\n"
            "**Layout da suite (v3.4.1 — 140 testes):**\n\n"
            "- `test_database.py` — CRUD, recovery, sessão ativa, event log.\n"
            "- `test_api.py` — endpoints FastAPI com TestClient.\n"
            "- `test_encoder.py` — happy path + edge cases do `encode_file`.\n"
            "- `test_e2e.py` — Worker + API juntos via thread + fake binaries.\n"
            "- `test_scanner.py` — walk + filtros.\n"
            "- `test_bug_fixes.py` — regressão para B-001..B-015.\n"
            "- `test_db_backup.py` — endpoints de backup/restore.\n"
            "- `test_history_filters.py` — sort, filter, export/import.\n"
            "- `test_log_management.py` — view per-job, busca, retenção.\n"
            "- `test_advanced_config.py` — extra=allow + campos novos.\n"
            "- `test_queue_add.py` — endpoint add-to-queue.\n"
            "- `test_advanced_encode.py` — cada toggle avançado.\n"
            "- `test_exclude_folder.py` — add-to-exclusion idempotente.\n"
            "- `test_help.py` — endpoint deste manual.\n"
            "- `test_encoder_vaapi.py` — args VAAPI/QSV/NVENC + regressões "
            "negativas para B-020/B-021.\n"
            "- `test_db_backend.py` — handling da env DB_BACKEND.\n"
            "- `test_metadata.py` — captura completa de metadata ffprobe.\n"
            "- `test_db_engine.py` — engine SQLAlchemy, tradutor qmark.\n"
            "- `test_db_backup_postgres.py` — pg_dump/pg_restore mocked.\n"
            "- `test_encode_start_dialects.py` — lock dialect-aware para B-018.\n"
            "- `test_theme_vars.py` — seleção light-mode + badges theme-aware."
        ),
    },
    {
        "id": "useful_commands",
        "title": "28. Comandos úteis e manutenção",
        "body": (
            "```\n"
            "# Logs ao vivo\n"
            "docker compose logs -f reencoder-api\n"
            "docker compose logs -f reencoder-worker\n"
            "\n"
            "# Restart só do worker (preserva API + clientes websocket)\n"
            "docker compose restart reencoder-worker\n"
            "\n"
            "# Healthcheck\n"
            "curl -s http://localhost:4246/api/health | jq\n"
            "\n"
            "# Backend de DB atualmente ativo\n"
            "curl -s http://localhost:4246/api/db/state | python3 -m json.tool\n"
            "\n"
            "# Shell Postgres\n"
            "docker compose exec postgres psql -U reencoder -d reencoder\n"
            "  \\dt\n"
            "  SELECT id,status,total_files,done_files FROM sessions\n"
            "    ORDER BY created_at DESC LIMIT 10;\n"
            "  SELECT id,status,filename,pct FROM jobs\n"
            "    WHERE status IN ('queued','encoding');\n"
            "\n"
            "# Shell SQLite (só quando DB_BACKEND=sqlite)\n"
            "docker compose exec reencoder-api sqlite3 /data/reencoder.db\n"
            "\n"
            "# Forçar sweep de recovery (após mexer no DB manualmente)\n"
            "curl -s -X POST http://localhost:4246/api/encode/force-reset \\\n"
            "  -H 'Content-Type: application/json' -d '{}'\n"
            "\n"
            "# Snapshot manual do DB\n"
            "curl -s -X POST http://localhost:4246/api/db/backup \\\n"
            "  -H 'Content-Type: application/json' -d '{\"label\":\"pre-update\"}'\n"
            "curl -s http://localhost:4246/api/db/backups | python3 -m json.tool\n"
            "\n"
            "# Limpar logs JSONL antigos\n"
            "docker compose exec reencoder-api find /data/logs \\\n"
            "  -name 'session_*.jsonl' -mtime +30 -delete\n"
            "\n"
            "# Validar VAAPI dentro do worker\n"
            "docker compose exec reencoder-worker ffmpeg -version 2>&1 | head -1\n"
            "docker compose exec reencoder-worker ffmpeg -hide_banner -hwaccels\n"
            "docker compose exec reencoder-worker vainfo 2>&1 | head -20\n"
            "\n"
            "# Rebuild from scratch (preserva volumes)\n"
            "docker compose down\n"
            "docker compose build --no-cache\n"
            "docker compose up -d\n"
            "\n"
            "# PERIGO: reset completo (apaga DB + logs + backups; preserva config.json)\n"
            "docker compose down\n"
            "sudo rm -rf data/postgres data/reencoder.db data/reencoder.db-wal \\\n"
            "            data/reencoder.db-shm data/logs data/backups\n"
            "docker compose build && docker compose up -d\n"
            "```"
        ),
    },
    {
        "id": "troubleshooting",
        "title": "29. Troubleshooting",
        "body": (
            "**Botão Encode não faz nada, log mostra `409 Conflict`.** Você está "
            "em ≤v3.3 contra Postgres (B-018). Atualize para v3.4+. Workaround: "
            "`POST /api/encode/force-reset`.\n\n"
            "**Light mode — row selecionado fica invisível.** Issue ≤v3.3 "
            "(B-019). Atualize para v3.4+.\n\n"
            "**Encode GPU falha com `Unrecognized option 'vaapi_device'` ou "
            "`'rc_mode'`.** ≤v3.4 + ffmpeg 7 (B-020/B-021). Atualize para v3.4.1+ "
            "e rebuild do worker: `docker compose build --no-cache "
            "reencoder-worker && docker compose up -d`.\n\n"
            "**Encode GPU falha com `Device creation failed: -12. Cannot "
            "allocate memory`.** ≤v3.4 (B-022) — o FFmpeg static não tem VAAPI "
            "compilado e a imagem não tem `mesa-va-drivers`. Atualize para "
            "v3.4.1+. Valide com `docker compose exec reencoder-worker vainfo`.\n\n"
            "**API em crash loop com `password authentication failed for user "
            "\"reencoder\"`.** `POSTGRES_PASSWORD` foi trocada depois do primeiro "
            "boot; o volume ainda tem a senha original. Ou apague `data/"
            "postgres/` (perde histórico — backup primeiro) ou rode `ALTER USER "
            "reencoder WITH PASSWORD '<nova>'` dentro do container.\n\n"
            "**Erros `database is locked` (só SQLite).** Confirme que só um "
            "worker está rodando. Suba `worker_poll_interval_s` se tiver "
            "múltiplos workers (não é o default).\n\n"
            "**Histórico sumiu depois do rebuild.** A API loga `WARNING: DB "
            "file exists but has no history rows` quando isso acontece. "
            "Settings → Database Backups deve ter snapshot `startup` de antes do "
            "rebuild — restaure ele.\n\n"
            "**Encode trava em `Computing hash...`.** Arquivo source está em "
            "filesystem lento (NFS/SMB). Ou mova para path mais rápido ou setar "
            "`full_hash=false` para só head+tail serem hashed.\n\n"
            "**Progress para de atualizar mas encode continua rodando.** O event "
            "broadcaster pode ter morrido silenciosamente. `docker compose "
            "restart reencoder-api` resolve sem tocar no encode."
        ),
    },
    {
        "id": "credits",
        "title": "30. Créditos e referências",
        "body": (
            "O nome **Transcode Talker** é uma referência a *Decode Talker* — um "
            "Cyberse Link Monster do Yu-Gi-Oh! Como sua contraparte, o objetivo é "
            "pegar algo maior e fazer link para uma forma mais enxuta e "
            "eficiente.\n\n"
            "Construído sobre:\n\n"
            "- **FFmpeg** + libx265 + libva + drivers Mesa\n"
            "- **FastAPI** + **Uvicorn** + **Pydantic** + **SQLAlchemy 2.x**\n"
            "- **React 18** via CDN unpkg + `@babel/standalone`\n"
            "- **Postgres 16-alpine** (default) ou **SQLite WAL** (legado)\n"
            "- **Docker** + **Docker Compose**\n"
            "- **pytest** para a suite de regressão de 140 testes\n\n"
            "Mantenedor: Rafael Mello."
        ),
    },
]   # populated by language modules below
_ES = [
    {
        "id": "intro",
        "title": "1. ¿Qué es Transcode Talker?",
        "body": (
            "**Transcode Talker** es un re-codificador de video por lotes "
            "auto-alojado. Escanea las carpetas que configuras, te permite elegir "
            "qué archivos re-codificar usando FFmpeg (libx265 en CPU, o un "
            "pipeline GPU — VAAPI/QSV/NVENC), y reemplaza el original con la "
            "versión HEVC más pequeña **solo cuando el resultado es realmente "
            "más pequeño**. Si el archivo re-codificado resulta más grande, se "
            "descarta y el trabajo se marca como `skipped`.\n\n"
            "Está construido como dos contenedores Docker — una **API + UI** y "
            "un **worker** — que comparten estado a través de una base de datos "
            "(Postgres por defecto desde v3.4, SQLite WAL como legado) y archivos "
            "de log JSONL. La separación es deliberada: las codificaciones pueden "
            "durar horas y el diseño asegura que la codificación continúa incluso "
            "si el navegador se cierra, la API se reinicia o el worker reinicia. "
            "Solo un worker matado a mitad de codificación pierde el archivo "
            "actual (que se recupera como `failed` en el siguiente arranque del "
            "worker).\n\n"
            "El objetivo es simple: reducir el espacio en disco que ocupa tu "
            "biblioteca de medios mientras se preservan todas las pistas de audio, "
            "todos los subtítulos, todos los attachments, y la misma fidelidad de "
            "reproducción (controlada por CRF — Constant Rate Factor)."
        ),
    },
    {
        "id": "architecture",
        "title": "2. Visión general de la arquitectura",
        "body": (
            "Dos contenedores Docker y un contenedor opcional de base de datos, "
            "en una red bridge privada:\n\n"
            "- **reencoder-api** (FastAPI en el puerto 4246) — sirve la UI React, "
            "la API HTTP y el stream de eventos WebSocket. Es dueña del schema y "
            "lee/escribe la base de datos. **No** lanza FFmpeg.\n"
            "- **reencoder-worker** (loop Python) — hace polling de la base cada "
            "`worker_poll_interval_s` segundos buscando una sesión `running` con "
            "jobs en cola, luego ejecuta FFmpeg un archivo a la vez. Actualiza el "
            "progreso del job en la base y agrega eventos al log JSONL.\n"
            "- **postgres** (desde v3.4 el default; opcional) — Postgres "
            "16-alpine, datos persistidos en `data/postgres/`. SQLite sigue "
            "soportado vía `DB_BACKEND=sqlite`.\n\n"
            "¿Por qué dos procesos en lugar de uno? Tres razones:\n\n"
            "1. **Resiliencia.** Un reinicio de FastAPI no mata la codificación.\n"
            "2. **Aislamiento de recursos.** El worker recibe límites de CPU/"
            "memoria dedicados en docker-compose (8 CPU, 8G RAM por defecto).\n"
            "3. **Separación de responsabilidades.** La API es request/response "
            "+ websocket; el worker es un gestor de subproceso de larga "
            "duración.\n\n"
            "**No hay HTTP entre API y worker** — se comunican exclusivamente a "
            "través de la base compartida (Postgres o SQLite WAL) y archivos "
            "JSONL de eventos en `/data/logs/`. Esto es intencional: la base es "
            "la única fuente de verdad, y agregar HTTP entre ellos solo "
            "duplicaría el estado."
        ),
    },
    {
        "id": "components_diagram",
        "title": "3. Diagrama de componentes",
        "body": (
            "```\n"
            "                 ┌─────────────────────┐\n"
            "                 │ Navegador (React)   │\n"
            "                 └─────────┬───────────┘\n"
            "                           │ HTTP + WebSocket\n"
            "                           ▼\n"
            "                 ┌─────────────────────┐\n"
            "                 │   reencoder-api     │  FastAPI :4246\n"
            "                 │  (FastAPI + Uvicorn)│  static/index.html\n"
            "                 └────┬────────────┬───┘\n"
            "                      │            │\n"
            "                      ▼            ▼\n"
            "             ┌─────────────┐  ┌──────────────┐\n"
            "             │   Base de   │  │  /data/logs/ │\n"
            "             │ datos       │◄─┤  *.jsonl     │\n"
            "             │ (Postgres   │  └──────────────┘\n"
            "             │  o SQLite)  │          ▲\n"
            "             └──────┬──────┘          │\n"
            "                    │                 │\n"
            "                    ▼                 │\n"
            "             ┌─────────────────┐      │\n"
            "             │ reencoder-worker│──────┘  poll loop en Python\n"
            "             │  (loop Python)  │         llama a FFmpeg\n"
            "             └────────┬────────┘\n"
            "                      │\n"
            "                      ▼\n"
            "             ┌────────────────────────┐\n"
            "             │  FFmpeg + /dev/dri     │  GPU VAAPI (AMD/Intel)\n"
            "             │  + /mnt/media          │  archivos fuente\n"
            "             │  + /mnt/hdd            │  área temp de codificación\n"
            "             └────────────────────────┘\n"
            "```\n\n"
            "Todo el estado persistente vive en tres lugares:\n\n"
            "- **Base de datos** (`/data/reencoder.db` para SQLite, o el volumen "
            "del contenedor `postgres`) — tablas `sessions`, `jobs`, "
            "`scan_results`.\n"
            "- **Archivos JSONL de eventos** (`/data/logs/session_<id>.jsonl`) — "
            "un archivo append-only por sesión, con la línea de tiempo legible.\n"
            "- **Config** (`/data/config.json`) — todo setting editable por UI."
        ),
    },
    {
        "id": "flow_scan_encode",
        "title": "4. Flujo end-to-end: Escaneo → Selección → Codificación",
        "body": (
            "```\n"
            "Usuario → UI:        POST /api/scan\n"
            "UI → API:            recorre scan_folders, retorna lista ScannedFile\n"
            "API → DB:            reemplaza fila scan_results con nuevo snapshot\n"
            "API → UI:            {files: [...]}\n"
            "\n"
            "Usuario → UI:        selecciona archivos, clic ▶ Encode\n"
            "UI → API:            POST /api/encode/start {paths}\n"
            "API → DB:            verifica que no haya sesión activa (lock\n"
            "                     dialect-aware: BEGIN IMMEDIATE en SQLite,\n"
            "                     pg_advisory_xact_lock en Postgres — ver B-018)\n"
            "API → DB:            INSERT session(running) + INSERT N jobs(queued)\n"
            "API → UI:            {ok, session_id}\n"
            "\n"
            "Loop del worker (cada worker_poll_interval_s, default 2s):\n"
            "  Worker → DB:       SELECT sesión activa\n"
            "  Worker → DB:       SELECT próximo job queued en esa sesión\n"
            "  Worker → DB:       UPDATE job status=encoding\n"
            "  Worker → FFmpeg:   spawn con build_cmd(...)\n"
            "  Loop cada 0.5s mientras FFmpeg corre:\n"
            "    Worker → DB:     is_session_interrupted? (stop check)\n"
            "    FFmpeg → stderr: progreso key=value\n"
            "    Worker → DB:     update_job_progress(pct, frame, fps, speed, eta)\n"
            "                     (throttled a una vez cada 2s)\n"
            "    Worker → JSONL:  append evento progress\n"
            "  Cuando FFmpeg termina:\n"
            "    Worker → ffprobe: verify_file (codec_name == libx265 / hevc)\n"
            "    Worker → fs:     compara tamaños; skip si encoded >= original\n"
            "    Worker → fs:     shutil.move HDD_temp → path original\n"
            "    Worker → DB:     UPDATE job status=completed (o skipped/failed)\n"
            "    Worker → DB:     UPDATE session.done_files++\n"
            "```\n\n"
            "El **event broadcaster de la API** (tarea de fondo) hace tail del "
            "archivo JSONL de cada sesión cada 1s y empuja líneas nuevas a cada "
            "cliente WebSocket conectado. La UI también llama "
            "`GET /api/session/active` en cada apertura de WebSocket para "
            "reconstruir el estado completo — así que cerrar/reabrir el "
            "navegador, o reiniciar la API, nunca desincroniza la UI."
        ),
    },
    {
        "id": "flow_stop",
        "title": "5. Flujo end-to-end: Stop",
        "body": (
            "```\n"
            "Usuario → UI:        clic ■ Stop, confirma\n"
            "UI → API:            POST /api/encode/stop\n"
            "API → DB:            UPDATE session status=interrupted\n"
            "API → DB:            UPDATE jobs status=interrupted\n"
            "                     WHERE status IN (queued, encoding)\n"
            "API → JSONL:         append evento queue_stopped\n"
            "API → UI:            {ok, cancelled}\n"
            "\n"
            "Worker (próximo tick de stop_check_interval_s, default 0.5s):\n"
            "  Worker → DB:       is_session_interrupted? → True\n"
            "  Worker → FFmpeg:   SIGTERM\n"
            "  Espera hasta 5 segundos:\n"
            "    Si sigue corriendo: SIGKILL\n"
            "  Worker → fs:       _cleanup(hdd_encoded)  (elimina parcial)\n"
            "  Worker → DB:       finaliza estado del job\n"
            "```\n\n"
            "Stop es **graceful por defecto**: SIGTERM da a FFmpeg hasta 5 "
            "segundos para terminar de escribir su trailer de mux y salir "
            "limpiamente. Solo si no responde, el worker escala a SIGKILL. El "
            "archivo parcial codificado en el área temp del HDD siempre se "
            "elimina con `_cleanup()`."
        ),
    },
    {
        "id": "flow_recovery",
        "title": "6. Flujo end-to-end: Recuperación de crash",
        "body": (
            "Cuando el contenedor del worker arranca, ejecuta "
            "`recover_stale_jobs()` antes de entrar al poll loop. Cualquier job "
            "cuyo status sea `encoding` se marca como `failed` con "
            "`error_msg='Worker crashed or restarted'`. Esta es la única manera "
            "de que un job esté en `encoding` sin un proceso worker realmente "
            "corriendo.\n\n"
            "```\n"
            "Arranque del worker:\n"
            "  Worker → DB:       recover_stale_jobs(now)\n"
            "                     UPDATE jobs SET status='failed'\n"
            "                     WHERE status='encoding'\n"
            "  (v3.4) Worker reintenta hasta 10 × 2s si el DB no está listo —\n"
            "  tolera arranque en frío lento de Postgres.\n"
            "```\n\n"
            "**v3.4 también agregó `/api/encode/force-reset`** como defensa en "
            "profundidad: si una sesión queda `running` sin worker real, el "
            "usuario puede llamar este endpoint (o aceptar el `confirm()` "
            "automático que la UI muestra ante un 409 trabado) para marcar todas "
            "las sesiones `running` como `interrupted`."
        ),
    },
    {
        "id": "flow_websocket",
        "title": "7. Flujo end-to-end: sync y reconexión del WebSocket",
        "body": (
            "```\n"
            "UI:                  conecta ws://host:4246/ws\n"
            "API:                 acepta, agrega al set _ws_clients\n"
            "UI:                  GET /api/session/active\n"
            "API → DB:            obtiene sesión activa O más reciente\n"
            "API → DB:            obtiene todos los jobs de esa sesión\n"
            "API → JSONL:         lee event log completo de esa sesión\n"
            "API → UI:            {session, jobs, events}\n"
            "UI:                  reconstruye barras de progreso, cola, log\n"
            "\n"
            "Loop de fondo en API (cada 1s):\n"
            "  API → JSONL:       tail nuevas líneas de la sesión activa\n"
            "  API → todos WS:    broadcast nuevos eventos\n"
            "\n"
            "Al cerrarse el WebSocket:\n"
            "  UI:                espera con backoff exponencial (1s, 2s, 4s, 8s, max 30s)\n"
            "  UI:                reconecta, repite desde arriba\n"
            "```\n\n"
            "Los eventos progress (`type: progress`) actualizan solo los "
            "contadores en vivo (pct/fps/speed/eta) para mantener la UI ágil. "
            "Cualquier cosa que cambie la estructura — `file_start`, "
            "`file_done`, `queue_start`, `queue_done`, `queue_stopped` — "
            "dispara un `syncFromServer()` completo."
        ),
    },
    {
        "id": "directory_structure",
        "title": "8. Estructura de directorios y contenedores",
        "body": (
            "**Layout del repositorio:**\n\n"
            "```\n"
            "reencoder-v3/\n"
            "├── docker-compose.yml\n"
            "├── .env.example                  # plantilla para secretos producción\n"
            "├── data/                         # volumen persistente montado en /data\n"
            "│   ├── config.json               # config editable por UI\n"
            "│   ├── reencoder.db              # SQLite (solo con DB_BACKEND=sqlite)\n"
            "│   ├── postgres/                 # volumen de datos Postgres\n"
            "│   ├── backups/                  # snapshots automáticos + manuales\n"
            "│   └── logs/\n"
            "│       └── session_<id>.jsonl    # un event log por sesión\n"
            "├── reencoder-api/\n"
            "│   ├── Dockerfile\n"
            "│   ├── app/\n"
            "│   │   ├── main.py               # endpoints FastAPI + WS\n"
            "│   │   ├── database.py           # DAL (SQLAlchemy Core)\n"
            "│   │   ├── db_engine.py          # factory de Engine + schema\n"
            "│   │   ├── db_backup.py          # snapshot + restore\n"
            "│   │   ├── config.py             # persistencia de config.json\n"
            "│   │   ├── models.py             # modelos Pydantic\n"
            "│   │   ├── scanner.py            # recorrido de filesystem\n"
            "│   │   └── help_content.py       # este manual\n"
            "│   └── static/index.html         # UI React inline\n"
            "├── reencoder-worker/\n"
            "│   ├── Dockerfile                # apt ffmpeg + mesa-va-drivers (v3.4.1)\n"
            "│   └── worker/\n"
            "│       ├── main.py               # poll loop + manejo de señales\n"
            "│       ├── encoder.py            # pipeline ffmpeg\n"
            "│       └── database.py           # mirror byte-equivalente\n"
            "└── tests/                        # suite pytest (140 tests en v3.4.1)\n"
            "```\n\n"
            "**Expectativas del filesystem del host:**\n\n"
            "| Path host | Path contenedor | Propósito |\n"
            "|---|---|---|\n"
            "| `./data` | `/data` | DB, config, logs, backups |\n"
            "| `/mnt/animes` | `/mnt/animes` | biblioteca de medios |\n"
            "| `/mnt/media` | `/mnt/media` | biblioteca de medios |\n"
            "| `/mnt/hdd` | `/mnt/hdd` | disco lento como área temp |\n"
            "| `/dev/dri` | `/dev/dri` | dispositivo GPU (solo worker) |"
        ),
    },
    {
        "id": "data_model",
        "title": "9. Modelo de datos (schema de la base)",
        "body": (
            "Tres tablas, misma forma en SQLite y Postgres. La migración es "
            "idempotente: cada `CREATE TABLE` usa `IF NOT EXISTS` y las columnas "
            "nuevas se agregan vía `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` "
            "en el arranque.\n\n"
            "**`sessions`** — una fila por clic de Start Encode.\n\n"
            "| Columna | Tipo | Notas |\n"
            "|---|---|---|\n"
            "| `id` | TEXT PK | UUID truncado a 8 chars |\n"
            "| `status` | TEXT | `pending` / `running` / `completed` / `interrupted` |\n"
            "| `total_files`, `done_files` | INT | totales |\n"
            "| `created_at`, `updated_at` | TEXT | timestamps ISO |\n\n"
            "**`jobs`** — una fila por archivo en la sesión.\n\n"
            "| Columna | Tipo | Notas |\n"
            "|---|---|---|\n"
            "| `id` | INT PK auto | |\n"
            "| `session_id` | TEXT | FK lógica |\n"
            "| `filename`, `original_path` | TEXT | |\n"
            "| `original_size_mb`, `final_size_mb`, `space_saved_mb` | REAL | |\n"
            "| `original_hash`, `encoded_hash` | TEXT | sha256 |\n"
            "| `crf_used`, `encoder_used` | INT / TEXT | settings al codificar |\n"
            "| `status` | TEXT | queued/encoding/completed/failed/skipped/interrupted |\n"
            "| `current_frame`, `total_frames`, `pct` | INT / REAL | progreso |\n"
            "| `fps`, `speed` | TEXT | como reporta ffmpeg |\n"
            "| `eta_s`, `error_msg` | INT / TEXT | |\n"
            "| `started_at`, `completed_at` | TEXT | |\n"
            "| `source_metadata`, `destination_metadata` | TEXT(JSON) | ffprobe (v3.3+) |\n"
            "| `ffmpeg_cmd` | TEXT | comando exacto (v3.3+) |\n\n"
            "**`scan_results`** — una fila única, reemplazada en cada nuevo "
            "scan.\n\n"
            "**Event log JSONL** (un archivo por sesión en `/data/logs/`): un "
            "objeto JSON por línea. Tipos de evento: `queue_start`, `queue_done`, "
            "`queue_stopped`, `file_start`, `file_done`, `step`, `progress`, "
            "`error`, `skipped`, `stopped`, `done`, `ffmpeg_cmd`."
        ),
    },
    {
        "id": "config_env",
        "title": "10. Variables de entorno (.env)",
        "body": (
            "Leídas por `docker-compose.yml` y pasadas a los contenedores. "
            "`.env` es opcional — los defaults de Postgres son inseguros pero "
            "funcionales out-of-the-box. **En cualquier deploy no-local, copia "
            "`.env.example` a `.env` y configura una contraseña fuerte antes del "
            "primer `docker compose up`.**\n\n"
            "| Variable | Default | Efecto |\n"
            "|---|---|---|\n"
            "| `DB_BACKEND` | `postgres` (v3.4+) | `postgres` o `sqlite` |\n"
            "| `POSTGRES_HOST` | `postgres` | nombre del service |\n"
            "| `POSTGRES_PORT` | `5432` | |\n"
            "| `POSTGRES_USER` | `reencoder` | |\n"
            "| `POSTGRES_PASSWORD` | `reencoder` | **cambiar en producción** |\n"
            "| `POSTGRES_DB` | `reencoder` | |\n"
            "| `TZ` | `America/New_York` | timezone para timestamps |\n"
            "| `BASIC_AUTH_USER`, `BASIC_AUTH_PASS` | vacíos | habilita HTTP Basic auth |\n\n"
            "**Recordatorios sobre la contraseña de Postgres:** Postgres solo "
            "aplica `POSTGRES_PASSWORD` cuando el volumen de datos está vacío. "
            "Si cambias en deploy live, debes o borrar `data/postgres/` (pierde "
            "historia — haz backup primero vía History → Export JSON) o "
            "`ALTER USER reencoder WITH PASSWORD '<nueva>'` dentro del "
            "contenedor."
        ),
    },
    {
        "id": "config_json",
        "title": "11. Campos de configuración (config.json)",
        "body": (
            "Todos los settings editables por UI viven en `/data/config.json` y "
            "mapean 1-a-1 con los campos Pydantic en `app/models.py:Config`. El "
            "archivo se mergea sobre los defaults en cada carga.\n\n"
            "**Escaneo y exclusión:**\n\n"
            "- `scan_folders: list[{path, threshold_mb}]` — carpetas a recorrer. "
            "Solo archivos que coincidan con `extensions` y tengan al menos "
            "`threshold_mb` MB se retornan.\n"
            "- `exclude_folders: list[str]` — match case-insensitive de prefijo.\n"
            "- `extensions: list[str]` — extensiones consideradas, en minúsculas "
            "con punto. Default: `.mkv .mp4 .avi .mov`.\n\n"
            "**Parámetros obligatorios del encoder:**\n\n"
            "- `encoder: cpu | vaapi | qsv | nvenc` — ver secciones por encoder.\n"
            "- `crf: int` (1..51) — Constant Rate Factor. **Menor = archivo más "
            "grande, mejor calidad.** 23–28 es el rango HEVC típico. 26 es un "
            "buen default.\n"
            "- `preset: ultrafast..slower` — trade-off velocidad/eficiencia x265.\n"
            "- `ffmpeg_threads: int` — cantidad de threads de libx265.\n\n"
            "**Paths y binarios:**\n\n"
            "- `hdd_temp_path: str` — dónde vive el output codificado durante el "
            "run. Debe estar en disco con espacio suficiente.\n"
            "- `ffmpeg_path`, `ffprobe_path` — defaults a `ffmpeg`/`ffprobe` "
            "del PATH.\n"
            "- `vaapi_device_path: str` — default `/dev/dri/renderD128`.\n\n"
            "**Tuning de comportamiento:**\n\n"
            "- `full_hash: bool` — si true, hashea el archivo completo (lento "
            "pero exacto). Si false, size + primeros 4MB + últimos 4MB.\n"
            "- `skip_hevc_below_kbps: int` — si la fuente ya es HEVC bajo este "
            "umbral, omite sin codificar.\n"
            "- `stall_timeout_s: int` (default 60) — mata FFmpeg si no hay "
            "progreso por estos segundos.\n"
            "- `worker_poll_interval_s: float` (default 2.0).\n"
            "- `stop_check_interval_s: float` (default 0.5).\n\n"
            "**Logs, apariencia y autenticación:**\n\n"
            "- `log_retention_days: int` (default 30, 0 = para siempre).\n"
            "- `clean_logs_on_startup: bool` (default true).\n"
            "- `theme: dark | light | auto`, `accent_color: '#RRGGBB'`, "
            "`brand_name: str`.\n"
            "- `basic_auth_user`, `basic_auth_pass`, `timezone: str`.\n\n"
            "**Advanced encode** (`advanced_encode: dict`) — ver sección 20."
        ),
    },
    {
        "id": "api_reference",
        "title": "12. Referencia de la API",
        "body": (
            "Todos los endpoints retornan JSON salvo nota contraria. Auth es "
            "HTTP Basic cuando está configurado. La única excepción es "
            "`/api/health`, siempre anónimo para que los healthchecks de Docker "
            "funcionen.\n\n"
            "**Health y meta:**\n"
            "- `GET /` — sirve la UI React.\n"
            "- `GET /api/health` — `{ok, ts}`.\n"
            "- `WS  /ws` — stream de eventos.\n\n"
            "**Config:**\n"
            "- `GET  /api/config` / `POST /api/config`\n"
            "- `GET  /api/config/first-run`\n"
            "- `POST /api/config/exclude-folder` — `{path}` idempotente.\n\n"
            "**Browse:**\n"
            "- `GET /api/browse?path=...` — restringido a `/mnt` y roots "
            "configurados.\n\n"
            "**Scan:**\n"
            "- `POST /api/scan`, `GET /api/scan/last`\n\n"
            "**Encode:**\n"
            "- `POST /api/encode/start` — 400 si paths inválidos, 409 con "
            "`{error, active_session_id}` si hay sesión activa.\n"
            "- `POST /api/encode/stop`\n"
            "- `POST /api/encode/force-reset` (v3.4) — anula sesiones "
            "`running` zombie.\n"
            "- `POST /api/encode/queue/add` — agrega paths a la sesión activa.\n"
            "- `GET  /api/encode/status`\n\n"
            "**Sesión e historial:**\n"
            "- `GET  /api/session/active`\n"
            "- `GET  /api/history?...` — paginado, filtrado, ordenado.\n"
            "- `GET  /api/history/stats`, `GET /api/history/encoded-paths`\n"
            "- `GET  /api/history/export`, `POST /api/history/import`\n"
            "- `DELETE /api/history/{id}` y bulk-delete\n\n"
            "**Logs por job:**\n"
            "- `GET /api/jobs/{id}/logs?q=`\n"
            "- `GET /api/jobs/{id}/logs/export?fmt=json|text`\n\n"
            "**Admin de base:**\n"
            "- `GET /api/db/state`, `GET /api/db/backups`\n"
            "- `POST /api/db/backup`, `POST /api/db/restore`\n\n"
            "**Manual:**\n"
            "- `GET /api/help?lang=...`"
        ),
    },
    {
        "id": "frontend",
        "title": "13. Front-end (static/index.html)",
        "body": (
            "Toda la UI vive en **un solo archivo HTML** de ~2100 líneas. Carga "
            "React 18 y ReactDOM desde unpkg CDN, más `@babel/standalone` para "
            "transformar JSX en el navegador. Sin bundler, sin `npm install`, "
            "sin TypeScript.\n\n"
            "**Páginas:**\n\n"
            "- **Scan & Select** — escanea, agrupa archivos por carpeta en árbol "
            "colapsable, filtros (all / never encoded / done), add-to-exclusion "
            "y badges de completitud por carpeta.\n"
            "- **Encode** — barra de progreso del job actual, lista de la cola, "
            "event log en vivo, botón Clear event logs.\n"
            "- **History** — tabla paginada con sort por columna y filter bar. "
            "Export/Import JSON. View abre JobLogModal.\n"
            "- **Settings** — secciones colapsables, cada campo con tooltip "
            "`ⓘ`.\n"
            "- **Encode Settings** — 4 parámetros obligatorios + 10 tarjetas "
            "avanzadas (ver sección 20).\n"
            "- **Help** — este manual, multilingüe.\n\n"
            "**Componentes críticos:**\n\n"
            "- Objeto `api` — wrappers de `fetch` con `_ok`/`_status`.\n"
            "- `EncodeBar` — banner persistente cuando hay sesión activa.\n"
            "- `JobLogModal` — tres pestañas: Details, Events, FFmpeg cmd.\n"
            "- `DirBrowser` — modal de browse.\n"
            "- Handler WS app-level con backoff exponencial (1, 2, 4, 8, max "
            "30s). Llama `syncFromServer()` en cada open.\n\n"
            "**Theming** — variables CSS en `:root`. v3.4 agregó "
            "`--selected-bg` y `--selected-fg`."
        ),
    },
    {
        "id": "backend_modules",
        "title": "14. Módulos del back-end",
        "body": (
            "**`main.py`** — entry point FastAPI. Cada endpoint HTTP, handler "
            "`/ws`, broadcaster de eventos cada 1s, y startup hook.\n\n"
            "**`database.py`** — Data Access Layer. Desde v3.3 es wrapper sobre "
            "SQLAlchemy 2.x Core que traduce placeholders `?` a named binds. "
            "`RETURNING id` en Postgres; `lastrowid` en SQLite.\n\n"
            "**`db_engine.py`** — Factory de Engine. Define tablas vía objetos "
            "`Table`, setea PRAGMA WAL+NORMAL en SQLite, corre migraciones.\n\n"
            "**`db_backend.py`** — Decide qué backend usar según `DB_BACKEND`.\n\n"
            "**`db_backup.py`** — Snapshot y restore. Branches por dialect: "
            "SQLite usa online backup API; Postgres usa `pg_dump -Fc -Z 6` y "
            "`pg_restore --clean --if-exists`.\n\n"
            "**`config.py`** — Load/save de `config.json` con merge sobre "
            "defaults.\n\n"
            "**`models.py`** — Modelos Pydantic. `Config` tiene "
            "`extra='allow'`.\n\n"
            "**`scanner.py`** — Walk de filesystem. Poda dirs excluidas durante "
            "`os.walk` para performance.\n\n"
            "**`worker/main.py`** — Loop del worker. Handlers SIGTERM/SIGINT. "
            "`recover_stale_jobs()` corre en startup (v3.4: retry × 10 × 2s para "
            "tolerar cold start de Postgres). Loop principal poll cada "
            "`worker_poll_interval_s`. Heartbeat en `/data/.worker_heartbeat`.\n\n"
            "**`worker/encoder.py`** — El pipeline FFmpeg. `file_hash()`, "
            "`get_total_frames()`, `_advanced_args()`, `build_cmd()`, "
            "`encode_file()`."
        ),
    },
    {
        "id": "ffmpeg_basics",
        "title": "15. Básicos de FFmpeg — parámetros obligatorios",
        "body": (
            "Estos cuatro campos se aplican siempre, sin importar el encoder. "
            "Son lo que estaba soportado en v3.1, y apagar todos los toggles "
            "avanzados hace que la codificación se comporte exactamente como "
            "v3.1.\n\n"
            "### `encoder`\n\n"
            "Pipeline usado para producir HEVC:\n\n"
            "- `cpu` — encoder software `libx265`. **El más compatible.** Más "
            "lento pero produce archivos más pequeños para un mismo CRF.\n"
            "- `vaapi` — GPU AMD/Intel vía VAAPI. Rápido. La calidad es menor "
            "que libx265 al mismo CRF.\n"
            "- `qsv` — Intel Quick Sync Video. Muy rápido.\n"
            "- `nvenc` — GPU NVIDIA. Muy rápido.\n\n"
            "### `crf` — Constant Rate Factor\n\n"
            "Entero de 1 a 51 (usado como `-qp` por los encoders GPU). **Menor = "
            "archivo más grande, mejor calidad.**\n\n"
            "- 18 — visualmente lossless.\n"
            "- 23 — alta calidad.\n"
            "- 26 — **default de Transcode Talker**.\n"
            "- 28 — visiblemente comprimido pero aún mirable.\n"
            "- 32+ — compresión fuerte, artefactos visibles.\n\n"
            "CRF es **quasi-logarítmico**: cada +6 duplica bitrate.\n\n"
            "### `preset`\n\n"
            "Trade-off velocidad-eficiencia: `ultrafast`, `superfast`, "
            "`veryfast`, `faster`, `fast`, `medium` (**default**), `slow`, "
            "`slower`. De `medium` a `slow` ahorra 5–10% bitrate al mismo CRF "
            "con ~2× tiempo.\n\n"
            "### `ffmpeg_threads`\n\n"
            "Threads que spawnea libx265. Default 4. Solo afecta encoder CPU."
        ),
    },
    {
        "id": "ffmpeg_cpu",
        "title": "16. Encoder FFmpeg — `cpu` (libx265)",
        "body": (
            "Forma del comando (defaults, sin toggles avanzados):\n\n"
            "```\n"
            "ffmpeg -y \\\n"
            "  -progress pipe:2 -nostats \\\n"
            "  -i <source> \\\n"
            "  -map 0:V -map 0:a? -map 0:s? -map 0:t? \\\n"
            "  -c:v libx265 -crf <CRF> -preset <preset> -threads <N> \\\n"
            "  -c:a copy -c:s copy \\\n"
            "  -max_muxing_queue_size 1024 \\\n"
            "  <hdd_temp_path>/ENCODED_<stem><ext>\n"
            "```\n\n"
            "Por qué cada flag:\n\n"
            "- `-y` — sobrescribe sin preguntar.\n"
            "- `-progress pipe:2 -nostats` — progreso machine-readable.\n"
            "- `-map 0:V` — todos los streams de video.\n"
            "- `-map 0:a?` — todos los streams de audio (opcional).\n"
            "- `-map 0:s?` — todos los streams de subtítulos.\n"
            "- `-map 0:t?` — todos los attachments.\n"
            "- `-c:a copy` — audio copiado bit-perfect.\n"
            "- `-c:s copy` — subtítulos copiados.\n"
            "- `-max_muxing_queue_size 1024` — previene buffer overflow del "
            "muxer."
        ),
    },
    {
        "id": "ffmpeg_vaapi",
        "title": "17. Encoder FFmpeg — `vaapi` (GPU AMD/Intel)",
        "body": (
            "Desde v3.4.1 el comando canónico (los flags legacy "
            "`-vaapi_device` y `-rc_mode` fueron removidos porque ffmpeg 7 los "
            "rechaza — ver B-020/B-021):\n\n"
            "```\n"
            "ffmpeg -y \\\n"
            "  -init_hw_device vaapi=va:/dev/dri/renderD128 \\\n"
            "  -filter_hw_device va \\\n"
            "  -progress pipe:2 -nostats \\\n"
            "  -i <source> \\\n"
            "  -map 0:V -map 0:a? -map 0:s? -map 0:t? \\\n"
            "  -vf format=nv12,hwupload \\\n"
            "  -c:v hevc_vaapi -qp <CRF> \\\n"
            "  -c:a copy -c:s copy \\\n"
            "  -max_muxing_queue_size 1024 \\\n"
            "  <hdd_temp_path>/ENCODED_<stem><ext>\n"
            "```\n\n"
            "Específicos:\n\n"
            "- `-init_hw_device vaapi=va:<dev>` — crea device de hardware "
            "llamado `va`.\n"
            "- `-filter_hw_device va` — vincula filter graph al device.\n"
            "- `-vf format=nv12,hwupload` — convierte a NV12 y sube a GPU.\n"
            "- `-c:v hevc_vaapi -qp <CRF>` — encoder VAAPI HEVC en modo CQP "
            "automático.\n\n"
            "**Requisitos en el contenedor** (v3.4.1+ ya los trae):\n\n"
            "- `apt-get install ffmpeg vainfo libva-drm2 libva2 "
            "mesa-va-drivers`.\n"
            "- Device `/dev/dri` mapeado en compose.\n"
            "- Driver Mesa/AMD o Intel funcionando en el host.\n\n"
            "**Validación:** `docker compose exec reencoder-worker vainfo` "
            "debería listar perfiles tipo `HEVCMain`."
        ),
    },
    {
        "id": "ffmpeg_qsv",
        "title": "18. Encoder FFmpeg — `qsv` (Intel Quick Sync)",
        "body": (
            "```\n"
            "ffmpeg -y \\\n"
            "  -init_hw_device qsv=qs:/dev/dri/renderD128 \\\n"
            "  -filter_hw_device qs \\\n"
            "  -hwaccel qsv -hwaccel_output_format qsv \\\n"
            "  -i <source> \\\n"
            "  -map 0:V -map 0:a? -map 0:s? -map 0:t? \\\n"
            "  -c:v hevc_qsv -global_quality <CRF> -preset <preset> \\\n"
            "  -c:a copy -c:s copy \\\n"
            "  ...\n"
            "```\n\n"
            "- `-hwaccel qsv -hwaccel_output_format qsv` — decode y mantiene "
            "GPU surfaces end-to-end.\n"
            "- `-global_quality <CRF>` — knob de calidad QSV.\n\n"
            "**Requisitos:** iGPU Intel + `intel-media-va-driver` + build de "
            "FFmpeg con QSV. El paquete `ffmpeg` default de Debian **no** "
            "incluye QSV — usa `jellyfin-ffmpeg`."
        ),
    },
    {
        "id": "ffmpeg_nvenc",
        "title": "19. Encoder FFmpeg — `nvenc` (GPU NVIDIA)",
        "body": (
            "```\n"
            "ffmpeg -y \\\n"
            "  -i <source> \\\n"
            "  -map 0:V -map 0:a? -map 0:s? -map 0:t? \\\n"
            "  -c:v hevc_nvenc -rc constqp -qp <CRF> -preset <preset> \\\n"
            "  -c:a copy -c:s copy \\\n"
            "  ...\n"
            "```\n\n"
            "- `-c:v hevc_nvenc` — encoder NVIDIA HEVC.\n"
            "- `-rc constqp -qp <CRF>` — modo constant-QP.\n"
            "- `-preset` — `p1`..`p7`.\n\n"
            "**Requisitos:** GPU NVIDIA + driver host + "
            "`nvidia-container-toolkit` + FFmpeg con CUDA. El `ffmpeg` default "
            "de Debian **no** incluye NVENC — usa `jellyfin-ffmpeg` o BtbN."
        ),
    },
    {
        "id": "ffmpeg_advanced",
        "title": "20. Toggles avanzados de codificación",
        "body": (
            "La pestaña **Encode Settings** expone 10 toggles en "
            "`advanced_encode`. Cada toggle es `{enabled: bool, value: ...}` y "
            "está **apagado por defecto** — con todo off, el comando es "
            "byte-idéntico a v3.1.\n\n"
            "### `bitrate`\n\n"
            "Setea `-b:v <value>` y opcionalmente `-maxrate`/`-bufsize`. Útil "
            "para techo rígido.\n\n"
            "### `tune`\n\n"
            "Agrega `-tune <value>`. Valores libx265: `psnr`, `ssim`, `grain`, "
            "`zerolatency`, `fastdecode`, `animation`.\n\n"
            "### `profile`, `level`, `tier`\n\n"
            "- `-profile:v` — `main`, `main10`, `main12`...\n"
            "- `-level` — `4.1`, `5.0`, `5.1`...\n"
            "- `-tier` (solo CPU) — `main` o `high`.\n\n"
            "### `pixel_format` (solo CPU)\n\n"
            "`-pix_fmt yuv420p10le` para HEVC 10-bit.\n\n"
            "### `gop` (keyint)\n\n"
            "`-g <keyint>`. Distancia entre keyframes.\n\n"
            "### `x265_params` (solo CPU)\n\n"
            "String raw de parámetros x265.\n\n"
            "### `audio`\n\n"
            "Cambia audio de copy a re-encode. `{codec, bitrate}`.\n\n"
            "### `video_filters` (solo CPU)\n\n"
            "`-vf <filter_chain>`. Ej: `scale=-2:720`, `crop=...`, `yadif`."
        ),
    },
    {
        "id": "first_run",
        "title": "21. Primera ejecución",
        "body": (
            "1. **Deploy.** Desde la raíz del repo: `docker compose build && "
            "docker compose up -d`.\n"
            "2. **Abre la UI** en `http://<host>:4246`.\n"
            "3. **Settings → Scan folders** — agrega al menos una fila `{path, "
            "threshold_mb}`.\n"
            "4. **Settings → Encoder** — empieza con `cpu`. Es el más "
            "compatible.\n"
            "5. **Settings → CRF** — déjalo en 26 a menos que tengas una razón "
            "fuerte.\n"
            "6. **Settings → HDD temp path** — debe estar en disco con espacio "
            "suficiente.\n"
            "7. **Save configuration**, luego **Scan & Select** → **⟳ Scan** → "
            "selecciona un archivo → **▶ Encode**."
        ),
    },
    {
        "id": "running_an_encode",
        "title": "22. Ejecutando una codificación",
        "body": (
            "1. **Scan & Select** — clic **⟳ Scan**, expande carpetas, marca "
            "archivos.\n"
            "2. **Inicia la codificación.** Clic **▶ Encode**.\n"
            "3. **Agrega más trabajo en vuelo.** Mientras codifica, el botón "
            "cambia a **+ Add to Queue (N)**.\n"
            "4. **Stop.** Clic **■ Stop**, confirma. El archivo actual se "
            "interrumpe en ~5 segundos.\n"
            "5. **Cierra el navegador y vuelve después.** Al reabrir, "
            "`/api/session/active` restaura todo.\n"
            "6. **Reboot.** Si el host reboota, el worker vuelve y marca el job "
            "in-flight como `failed`. Reseleccciónalo manualmente."
        ),
    },
    {
        "id": "history",
        "title": "23. Página de Historial",
        "body": (
            "Cada job que un worker tocó vive aquí para siempre (hasta que lo "
            "borres).\n\n"
            "- **Filtra** por encoder, status o rango de fecha.\n"
            "- **Ordena** clickeando cualquier header.\n"
            "- **View** abre el JobLogModal — tres pestañas:\n"
            "  - **Details** — snapshots ffprobe de fuente y destino lado a "
            "lado.\n"
            "  - **Events** — el log JSONL filtrado.\n"
            "  - **FFmpeg cmd** — comando exacto. Botón copiar.\n"
            "- **Export JSON** — snapshot completo schema v2.\n"
            "- **Import JSON** — mergea. De-duplica por `(original_path, "
            "completed_at)`. Snapshot pre-import automático."
        ),
    },
    {
        "id": "backups",
        "title": "24. Backups de base de datos",
        "body": (
            "Los backups viven en `/data/backups/`. Son dialect-aware:\n\n"
            "- **SQLite** — online-backup API. Resultado: archivo `.db`.\n"
            "- **Postgres** — `pg_dump -Fc -Z 6`. Resultado: archivo `.dump`.\n\n"
            "Ciclo de vida:\n\n"
            "- **Snapshot de startup automático.** Cada arranque de la API.\n"
            "- **Snapshots manuales.** Settings → Database Backups → Take "
            "snapshot. Nunca se auto-podan.\n"
            "- **Snapshot pre-restore.** Todo restore se precede de snapshot.\n"
            "- **Snapshot pre-import.** Todo `POST /api/history/import` "
            "también.\n\n"
            "**Restore se niega a correr durante encode activo** (409). Restore "
            "cross-dialect rechazado con 400 — usa Export JSON en su lugar."
        ),
    },
    {
        "id": "logs_retention",
        "title": "25. Logs y retención",
        "body": (
            "Dos superficies de log:\n\n"
            "- **Logs de contenedor** — `docker compose logs`. Rotación 10MB × "
            "5 archivos.\n"
            "- **Logs JSONL de sesión** — `/data/logs/session_<id>.jsonl`.\n\n"
            "**Controles de retención** (Settings → Log Management):\n\n"
            "- `log_retention_days` — 0 = para siempre.\n"
            "- `clean_logs_on_startup` — habilita poda automática."
        ),
    },
    {
        "id": "appearance",
        "title": "26. Apariencia",
        "body": (
            "Settings → Appearance:\n\n"
            "- **Theme** — `dark` / `light` / `auto`.\n"
            "- **Accent colour** — picker.\n"
            "- **Brand name** — título del header.\n\n"
            "Los cambios aplican en vivo sin reload."
        ),
    },
    {
        "id": "testing",
        "title": "27. Pruebas",
        "body": (
            "Desde la raíz del repo con Python del host:\n\n"
            "```\n"
            "pip install -r requirements-dev.txt\n"
            "pytest -v tests/\n"
            "```\n\n"
            "Los fixtures en `tests/conftest.py` fuerzan `DB_BACKEND=sqlite` y "
            "usan `DB_PATH`/`LOGS_DIR` monkey-patched para correr "
            "herméticamente. También proveen shims `fake_ffmpeg` y "
            "`fake_ffprobe`.\n\n"
            "**Layout de la suite (v3.4.1 — 140 tests):** ver doc principal "
            "para la lista completa por archivo."
        ),
    },
    {
        "id": "useful_commands",
        "title": "28. Comandos útiles y mantenimiento",
        "body": (
            "```\n"
            "# Logs en vivo\n"
            "docker compose logs -f reencoder-api\n"
            "docker compose logs -f reencoder-worker\n"
            "\n"
            "# Restart solo del worker\n"
            "docker compose restart reencoder-worker\n"
            "\n"
            "# Healthcheck\n"
            "curl -s http://localhost:4246/api/health | jq\n"
            "\n"
            "# Backend de DB activo\n"
            "curl -s http://localhost:4246/api/db/state | python3 -m json.tool\n"
            "\n"
            "# Shell Postgres\n"
            "docker compose exec postgres psql -U reencoder -d reencoder\n"
            "\n"
            "# Force-reset (destraba sesión zombie)\n"
            "curl -s -X POST http://localhost:4246/api/encode/force-reset \\\n"
            "  -H 'Content-Type: application/json' -d '{}'\n"
            "\n"
            "# Snapshot manual del DB\n"
            "curl -s -X POST http://localhost:4246/api/db/backup \\\n"
            "  -H 'Content-Type: application/json' -d '{\"label\":\"pre-update\"}'\n"
            "\n"
            "# Limpiar logs JSONL viejos\n"
            "docker compose exec reencoder-api find /data/logs \\\n"
            "  -name 'session_*.jsonl' -mtime +30 -delete\n"
            "\n"
            "# Validar VAAPI\n"
            "docker compose exec reencoder-worker ffmpeg -hide_banner -hwaccels\n"
            "docker compose exec reencoder-worker vainfo 2>&1 | head -20\n"
            "\n"
            "# Rebuild from scratch\n"
            "docker compose down\n"
            "docker compose build --no-cache && docker compose up -d\n"
            "\n"
            "# PELIGRO: reset completo (preserva config.json)\n"
            "docker compose down\n"
            "sudo rm -rf data/postgres data/reencoder.db data/logs data/backups\n"
            "docker compose build && docker compose up -d\n"
            "```"
        ),
    },
    {
        "id": "troubleshooting",
        "title": "29. Solución de problemas",
        "body": (
            "**Botón Encode no hace nada, log muestra `409 Conflict`.** Estás "
            "en ≤v3.3 contra Postgres (B-018). Actualiza a v3.4+. Workaround: "
            "`POST /api/encode/force-reset`.\n\n"
            "**Light mode — fila seleccionada invisible.** Issue ≤v3.3 "
            "(B-019). Actualiza a v3.4+.\n\n"
            "**Encode GPU falla con `Unrecognized option 'vaapi_device'` o "
            "`'rc_mode'`.** ≤v3.4 + ffmpeg 7 (B-020/B-021). Actualiza a "
            "v3.4.1+ y rebuild del worker: `docker compose build --no-cache "
            "reencoder-worker && docker compose up -d`.\n\n"
            "**Encode GPU falla con `Device creation failed: -12. Cannot "
            "allocate memory`.** ≤v3.4 (B-022). Actualiza a v3.4.1+. Valida "
            "con `docker compose exec reencoder-worker vainfo`.\n\n"
            "**API en crash loop con `password authentication failed`.** "
            "`POSTGRES_PASSWORD` cambiada después del primer boot; volumen "
            "tiene la contraseña original. Borra `data/postgres/` (pierde "
            "historia — backup primero) o usa `ALTER USER`.\n\n"
            "**Errores `database is locked` (solo SQLite).** Asegúrate de que "
            "solo un worker está corriendo.\n\n"
            "**Historial desapareció después del rebuild.** La API loga "
            "`WARNING: DB file exists but has no history rows`. Settings → "
            "Database Backups → restaura snapshot `startup`.\n\n"
            "**Encode trabado en `Computing hash...`.** Archivo fuente en "
            "filesystem lento (NFS/SMB). Setea `full_hash=false`."
        ),
    },
    {
        "id": "credits",
        "title": "30. Créditos y referencias",
        "body": (
            "El nombre **Transcode Talker** es un guiño a *Decode Talker* — un "
            "Cyberse Link Monster de Yu-Gi-Oh! Como su homónimo, el objetivo "
            "es tomar algo más grande y linkearlo a una forma más eficiente.\n\n"
            "Construido sobre:\n\n"
            "- **FFmpeg** + libx265 + libva + drivers Mesa\n"
            "- **FastAPI** + **Uvicorn** + **Pydantic** + **SQLAlchemy 2.x**\n"
            "- **React 18** vía unpkg CDN + `@babel/standalone`\n"
            "- **Postgres 16-alpine** (default) o **SQLite WAL** (legado)\n"
            "- **Docker** + **Docker Compose**\n"
            "- **pytest** para la suite de regresión de 140 tests\n\n"
            "Mantenedor: Rafael Mello."
        ),
    },
]
_FR = [
    {
        "id": "intro",
        "title": "1. Qu'est-ce que Transcode Talker ?",
        "body": (
            "**Transcode Talker** est un ré-encodeur vidéo par lots auto-hébergé. "
            "Il scanne les dossiers que vous configurez, vous laisse choisir "
            "quels fichiers ré-encoder en utilisant FFmpeg (libx265 sur CPU, ou "
            "un pipeline GPU — VAAPI/QSV/NVENC), et remplace l'original par la "
            "version HEVC plus petite **uniquement lorsque le résultat est "
            "réellement plus petit**. Si le fichier ré-encodé finit plus gros, "
            "il est jeté et le job est marqué `skipped`.\n\n"
            "Il est construit comme deux conteneurs Docker — une **API + UI** "
            "et un **worker** — qui partagent l'état via une base de données "
            "(Postgres par défaut depuis v3.4, SQLite WAL en legacy) et des "
            "fichiers de log JSONL. Cette séparation est délibérée : les "
            "encodages peuvent durer des heures et la conception garantit que "
            "l'encodage continue même si le navigateur se ferme, l'API "
            "redémarre, ou le worker reboote. Seul un worker tué en plein "
            "encodage perd le fichier actuel (récupéré comme `failed` au "
            "prochain démarrage du worker).\n\n"
            "L'objectif est simple : réduire l'espace disque occupé par votre "
            "bibliothèque média tout en préservant toutes les pistes audio, "
            "tous les sous-titres, tous les attachments, et la même fidélité "
            "de lecture (contrôlée par CRF — Constant Rate Factor)."
        ),
    },
    {
        "id": "architecture",
        "title": "2. Vue d'ensemble de l'architecture",
        "body": (
            "Deux conteneurs Docker et un conteneur de base optionnel, sur un "
            "réseau bridge privé :\n\n"
            "- **reencoder-api** (FastAPI sur le port 4246) — sert l'UI React, "
            "l'API HTTP, et le flux d'événements WebSocket. Elle est "
            "propriétaire du schéma et lit/écrit dans la base. Elle **ne "
            "spawne pas** FFmpeg.\n"
            "- **reencoder-worker** (boucle Python) — interroge la base toutes "
            "les `worker_poll_interval_s` secondes à la recherche d'une session "
            "`running` avec des jobs en file d'attente, puis exécute FFmpeg un "
            "fichier à la fois. Met à jour le progrès du job en base et ajoute "
            "des événements au log JSONL.\n"
            "- **postgres** (depuis v3.4 le défaut ; optionnel) — Postgres "
            "16-alpine, données persistées dans `data/postgres/`. SQLite reste "
            "supporté via `DB_BACKEND=sqlite`.\n\n"
            "Pourquoi deux processus au lieu d'un ? Trois raisons :\n\n"
            "1. **Résilience.** Un redémarrage de FastAPI ne tue pas "
            "l'encodage.\n"
            "2. **Isolation des ressources.** Le worker reçoit des limites "
            "CPU/mémoire dédiées en docker-compose (8 CPU, 8G RAM par défaut).\n"
            "3. **Séparation des préoccupations.** L'API est request/response "
            "+ websocket ; le worker est un gestionnaire de sous-processus à "
            "longue durée.\n\n"
            "**Il n'y a pas de HTTP entre l'API et le worker** — ils "
            "communiquent exclusivement via la base partagée (Postgres ou "
            "SQLite WAL) et les fichiers JSONL d'événements dans "
            "`/data/logs/`. C'est intentionnel : la base est la seule source "
            "de vérité."
        ),
    },
    {
        "id": "components_diagram",
        "title": "3. Diagramme des composants",
        "body": (
            "```\n"
            "                 ┌─────────────────────┐\n"
            "                 │ Navigateur (React)  │\n"
            "                 └─────────┬───────────┘\n"
            "                           │ HTTP + WebSocket\n"
            "                           ▼\n"
            "                 ┌─────────────────────┐\n"
            "                 │   reencoder-api     │  FastAPI :4246\n"
            "                 └────┬────────────┬───┘\n"
            "                      ▼            ▼\n"
            "             ┌─────────────┐  ┌──────────────┐\n"
            "             │ Base de     │  │  /data/logs/ │\n"
            "             │ données     │◄─┤  *.jsonl     │\n"
            "             │ (Postgres   │  └──────────────┘\n"
            "             │  ou SQLite) │          ▲\n"
            "             └──────┬──────┘          │\n"
            "                    ▼                 │\n"
            "             ┌─────────────────┐      │\n"
            "             │ reencoder-worker│──────┘  boucle poll Python\n"
            "             │  (boucle Py)    │         appelle FFmpeg\n"
            "             └────────┬────────┘\n"
            "                      ▼\n"
            "             ┌────────────────────────┐\n"
            "             │  FFmpeg + /dev/dri     │  GPU VAAPI\n"
            "             │  + /mnt/media          │  fichiers source\n"
            "             │  + /mnt/hdd            │  zone temp encodage\n"
            "             └────────────────────────┘\n"
            "```\n\n"
            "Tout l'état persistant vit à trois endroits :\n\n"
            "- **Base de données** — tables `sessions`, `jobs`, "
            "`scan_results`.\n"
            "- **Fichiers JSONL d'événements** — un fichier append-only par "
            "session.\n"
            "- **Config** (`/data/config.json`) — chaque réglage éditable par "
            "UI."
        ),
    },
    {
        "id": "flow_scan_encode",
        "title": "4. Flux end-to-end : Scan → Sélection → Encodage",
        "body": (
            "```\n"
            "Utilisateur → UI:    POST /api/scan\n"
            "UI → API:            parcourt scan_folders, retourne ScannedFile\n"
            "API → DB:            remplace ligne scan_results par snapshot\n"
            "API → UI:            {files: [...]}\n"
            "\n"
            "Utilisateur → UI:    sélectionne, clique ▶ Encode\n"
            "UI → API:            POST /api/encode/start {paths}\n"
            "API → DB:            vérifie qu'il n'y a pas de session active\n"
            "                     (verrou dialect-aware : BEGIN IMMEDIATE en\n"
            "                     SQLite, pg_advisory_xact_lock en Postgres)\n"
            "API → DB:            INSERT session(running) + N jobs(queued)\n"
            "API → UI:            {ok, session_id}\n"
            "\n"
            "Boucle du worker (chaque worker_poll_interval_s, défaut 2s):\n"
            "  Worker → DB:       SELECT session active\n"
            "  Worker → DB:       SELECT prochain job queued\n"
            "  Worker → DB:       UPDATE job status=encoding\n"
            "  Worker → FFmpeg:   spawn avec build_cmd(...)\n"
            "  Boucle chaque 0.5s pendant FFmpeg:\n"
            "    Worker → DB:     is_session_interrupted? (stop check)\n"
            "    FFmpeg → stderr: progrès key=value\n"
            "    Worker → DB:     update_job_progress (throttled 2s)\n"
            "    Worker → JSONL:  append événement progress\n"
            "  Quand FFmpeg sort:\n"
            "    Worker → ffprobe: verify_file (codec_name)\n"
            "    Worker → fs:     compare tailles; skip si encoded >= original\n"
            "    Worker → fs:     shutil.move HDD_temp → chemin original\n"
            "    Worker → DB:     UPDATE job status=completed\n"
            "```\n\n"
            "Le **broadcaster d'événements API** (tâche d'arrière-plan) tail "
            "le fichier JSONL de chaque session toutes les 1s et pousse les "
            "nouvelles lignes vers chaque client WebSocket connecté."
        ),
    },
    {
        "id": "flow_stop",
        "title": "5. Flux end-to-end : Stop",
        "body": (
            "```\n"
            "Utilisateur → UI:    clic ■ Stop, confirme\n"
            "UI → API:            POST /api/encode/stop\n"
            "API → DB:            UPDATE session status=interrupted\n"
            "API → DB:            UPDATE jobs (queued, encoding) → interrupted\n"
            "API → UI:            {ok, cancelled}\n"
            "\n"
            "Worker (prochain tick stop_check_interval_s, défaut 0.5s):\n"
            "  Worker → DB:       is_session_interrupted? → True\n"
            "  Worker → FFmpeg:   SIGTERM\n"
            "  Attend jusqu'à 5 secondes:\n"
            "    Si toujours actif: SIGKILL\n"
            "  Worker → fs:       _cleanup(hdd_encoded)\n"
            "  Worker → DB:       finalise état du job\n"
            "```\n\n"
            "Stop est **graceful par défaut** : SIGTERM laisse à FFmpeg jusqu'à "
            "5 secondes pour finir d'écrire son trailer de mux et sortir "
            "proprement. Seulement s'il ne répond pas, le worker escalade à "
            "SIGKILL."
        ),
    },
    {
        "id": "flow_recovery",
        "title": "6. Flux end-to-end : Récupération de crash",
        "body": (
            "Quand le conteneur du worker démarre, il exécute "
            "`recover_stale_jobs()` avant d'entrer dans la boucle poll. Tout "
            "job dont le status est `encoding` est marqué `failed` avec "
            "`error_msg='Worker crashed or restarted'`.\n\n"
            "**v3.4 a aussi ajouté `/api/encode/force-reset`** comme défense "
            "en profondeur : si une session reste `running` sans worker réel, "
            "l'utilisateur peut appeler cet endpoint (ou accepter la "
            "`confirm()` automatique que l'UI affiche sur un 409 bloqué) pour "
            "marquer toutes les sessions `running` comme `interrupted`."
        ),
    },
    {
        "id": "flow_websocket",
        "title": "7. Flux end-to-end : sync et reconnexion WebSocket",
        "body": (
            "```\n"
            "UI:                  connecte ws://host:4246/ws\n"
            "API:                 accepte, ajoute à _ws_clients\n"
            "UI:                  GET /api/session/active\n"
            "API → DB:            récupère session active OU plus récente\n"
            "API → UI:            {session, jobs, events}\n"
            "\n"
            "Boucle d'arrière-plan API (chaque 1s):\n"
            "  API → JSONL:       tail nouvelles lignes\n"
            "  API → tous WS:     broadcast nouveaux événements\n"
            "\n"
            "À la fermeture du WebSocket:\n"
            "  UI:                attente avec backoff exponentiel\n"
            "                     (1s, 2s, 4s, 8s, max 30s)\n"
            "  UI:                reconnecte, répète\n"
            "```\n\n"
            "Les événements `progress` mettent à jour seulement les compteurs "
            "en direct. Les événements structurels déclenchent un "
            "`syncFromServer()` complet."
        ),
    },
    {
        "id": "directory_structure",
        "title": "8. Structure des répertoires et conteneurs",
        "body": (
            "**Disposition du dépôt :**\n\n"
            "```\n"
            "reencoder-v3/\n"
            "├── docker-compose.yml\n"
            "├── .env.example\n"
            "├── data/                         # volume persistant /data\n"
            "│   ├── config.json\n"
            "│   ├── reencoder.db              # SQLite seulement\n"
            "│   ├── postgres/                 # volume Postgres\n"
            "│   ├── backups/                  # snapshots\n"
            "│   └── logs/session_<id>.jsonl\n"
            "├── reencoder-api/\n"
            "│   ├── app/main.py, database.py, db_engine.py, db_backup.py,\n"
            "│   │   config.py, models.py, scanner.py, help_content.py\n"
            "│   └── static/index.html\n"
            "├── reencoder-worker/\n"
            "│   ├── Dockerfile                # apt ffmpeg + mesa-va-drivers\n"
            "│   └── worker/main.py, encoder.py, database.py\n"
            "└── tests/                        # 140 tests pytest\n"
            "```\n\n"
            "**Attentes du système de fichiers de l'hôte :**\n\n"
            "| Chemin hôte | Chemin conteneur | Objectif |\n"
            "|---|---|---|\n"
            "| `./data` | `/data` | DB, config, logs, backups |\n"
            "| `/mnt/animes`, `/mnt/media` | idem | bibliothèque média |\n"
            "| `/mnt/hdd` | `/mnt/hdd` | zone temp d'encodage |\n"
            "| `/dev/dri` | `/dev/dri` | GPU (worker uniquement) |"
        ),
    },
    {
        "id": "data_model",
        "title": "9. Modèle de données (schéma de la base)",
        "body": (
            "Trois tables, même forme en SQLite et Postgres. La migration est "
            "idempotente.\n\n"
            "**`sessions`** — une ligne par clic Start Encode.\n\n"
            "Colonnes : `id` (TEXT PK), `status` (pending/running/completed/"
            "interrupted), `total_files`, `done_files`, `created_at`, "
            "`updated_at`.\n\n"
            "**`jobs`** — une ligne par fichier dans la session.\n\n"
            "Colonnes principales : `id`, `session_id`, `filename`, "
            "`original_path`, `original_size_mb`, `final_size_mb`, "
            "`space_saved_mb`, `original_hash`, `encoded_hash`, `crf_used`, "
            "`encoder_used`, `status` (queued/encoding/completed/failed/"
            "skipped/interrupted), `current_frame`, `total_frames`, `pct`, "
            "`fps`, `speed`, `eta_s`, `error_msg`, `started_at`, "
            "`completed_at`, `source_metadata` (JSON, v3.3+), "
            "`destination_metadata` (JSON, v3.3+), `ffmpeg_cmd` (v3.3+).\n\n"
            "**`scan_results`** — ligne unique, remplacée à chaque nouveau "
            "scan.\n\n"
            "**Log d'événements JSONL** : un objet JSON par ligne. Types : "
            "`queue_start`, `queue_done`, `queue_stopped`, `file_start`, "
            "`file_done`, `step`, `progress`, `error`, `skipped`, `stopped`, "
            "`done`, `ffmpeg_cmd`."
        ),
    },
    {
        "id": "config_env",
        "title": "10. Variables d'environnement (.env)",
        "body": (
            "Lues par `docker-compose.yml`. `.env` est optionnel — les défauts "
            "Postgres sont non-sécurisés mais fonctionnels. **Dans tout déploi "
            "non-local, copiez `.env.example` vers `.env` et définissez un mot "
            "de passe fort avant le premier `docker compose up`.**\n\n"
            "| Variable | Défaut | Effet |\n"
            "|---|---|---|\n"
            "| `DB_BACKEND` | `postgres` (v3.4+) | `postgres` ou `sqlite` |\n"
            "| `POSTGRES_HOST` | `postgres` | nom du service compose |\n"
            "| `POSTGRES_PORT` | `5432` | |\n"
            "| `POSTGRES_USER` | `reencoder` | |\n"
            "| `POSTGRES_PASSWORD` | `reencoder` | **changer en production** |\n"
            "| `POSTGRES_DB` | `reencoder` | |\n"
            "| `TZ` | `America/New_York` | timezone |\n"
            "| `BASIC_AUTH_USER`, `BASIC_AUTH_PASS` | vide | HTTP Basic auth |\n\n"
            "**Rappels mot de passe Postgres :** Postgres n'applique "
            "`POSTGRES_PASSWORD` que lorsque le volume est vide. Si vous "
            "changez sur un déploi vivant, soit effacez `data/postgres/` "
            "(perte d'historique — backup d'abord), soit `ALTER USER "
            "reencoder WITH PASSWORD '<nouveau>'`."
        ),
    },
    {
        "id": "config_json",
        "title": "11. Champs de configuration (config.json)",
        "body": (
            "Tous les réglages éditables par UI vivent dans "
            "`/data/config.json` et mappent 1-à-1 avec les champs Pydantic.\n\n"
            "**Scan et exclusion :**\n\n"
            "- `scan_folders: list[{path, threshold_mb}]` — dossiers à "
            "parcourir.\n"
            "- `exclude_folders: list[str]` — match préfixe insensible à la "
            "casse.\n"
            "- `extensions: list[str]` — extensions considérées. Défaut : "
            "`.mkv .mp4 .avi .mov`.\n\n"
            "**Paramètres obligatoires de l'encodeur :**\n\n"
            "- `encoder: cpu | vaapi | qsv | nvenc`\n"
            "- `crf: int` (1..51) — **plus bas = plus gros fichier, meilleure "
            "qualité.** 23–28 typique HEVC. 26 par défaut.\n"
            "- `preset: ultrafast..slower`\n"
            "- `ffmpeg_threads: int`\n\n"
            "**Chemins et binaires :**\n\n"
            "- `hdd_temp_path: str` — où vit l'output encodé.\n"
            "- `ffmpeg_path`, `ffprobe_path`\n"
            "- `vaapi_device_path: str` — défaut `/dev/dri/renderD128`.\n\n"
            "**Réglage du comportement :**\n\n"
            "- `full_hash: bool` — si true, hash le fichier entier.\n"
            "- `skip_hevc_below_kbps: int` — saute si source HEVC sous ce "
            "seuil.\n"
            "- `stall_timeout_s: int` (défaut 60).\n"
            "- `worker_poll_interval_s: float` (défaut 2.0).\n"
            "- `stop_check_interval_s: float` (défaut 0.5).\n\n"
            "**Logs et apparence :**\n\n"
            "- `log_retention_days: int` (défaut 30, 0 = pour toujours).\n"
            "- `clean_logs_on_startup: bool`.\n"
            "- `theme`, `accent_color`, `brand_name`.\n\n"
            "**Advanced encode** (`advanced_encode: dict`) — voir section 20."
        ),
    },
    {
        "id": "api_reference",
        "title": "12. Référence de l'API",
        "body": (
            "Tous les endpoints retournent JSON. Auth HTTP Basic quand "
            "configurée. Seule exception : `/api/health` toujours anonyme.\n\n"
            "**Health et meta :**\n"
            "- `GET /` — sert l'UI React.\n"
            "- `GET /api/health` — `{ok, ts}`.\n"
            "- `WS  /ws` — flux d'événements.\n\n"
            "**Config :** `GET/POST /api/config`, `/api/config/first-run`, "
            "`POST /api/config/exclude-folder`.\n\n"
            "**Browse :** `GET /api/browse?path=...` — restreint à `/mnt`.\n\n"
            "**Scan :** `POST /api/scan`, `GET /api/scan/last`.\n\n"
            "**Encode :**\n"
            "- `POST /api/encode/start` — 409 avec `{error, "
            "active_session_id}` si session active.\n"
            "- `POST /api/encode/stop`\n"
            "- `POST /api/encode/force-reset` (v3.4) — annule sessions zombie.\n"
            "- `POST /api/encode/queue/add`\n"
            "- `GET  /api/encode/status`\n\n"
            "**Session et historique :**\n"
            "- `GET  /api/session/active`\n"
            "- `GET  /api/history?...` — paginé, filtré, trié.\n"
            "- `GET  /api/history/stats`, `/encoded-paths`, `/export`\n"
            "- `POST /api/history/import`\n"
            "- `DELETE /api/history/{id}`, bulk-delete\n\n"
            "**Logs par job :** `GET /api/jobs/{id}/logs`, "
            "`/logs/export?fmt=...`\n\n"
            "**Admin base :** `GET /api/db/state`, `/backups`, `POST "
            "/api/db/backup`, `/restore`.\n\n"
            "**Manuel :** `GET /api/help?lang=...`."
        ),
    },
    {
        "id": "frontend",
        "title": "13. Front-end (static/index.html)",
        "body": (
            "Toute l'UI vit dans **un seul fichier HTML** de ~2100 lignes. "
            "Charge React 18 et ReactDOM depuis le CDN unpkg, plus "
            "`@babel/standalone` pour transformer JSX dans le navigateur. Sans "
            "bundler, sans `npm install`, sans TypeScript.\n\n"
            "**Pages :**\n\n"
            "- **Scan & Select** — scan, regroupement par dossier en arbre "
            "déployable, filtres, add-to-exclusion, badges de complétude par "
            "dossier.\n"
            "- **Encode** — barre de progression, file d'attente, event log "
            "en direct.\n"
            "- **History** — tableau paginé avec tri par colonne et barre de "
            "filtres. Export/Import JSON. View ouvre JobLogModal.\n"
            "- **Settings** — sections déployables avec tooltips `ⓘ`.\n"
            "- **Encode Settings** — 4 paramètres obligatoires + 10 cartes "
            "avancées toggleables.\n"
            "- **Help** — ce manuel, multilingue.\n\n"
            "**Composants critiques :**\n\n"
            "- Objet `api`, `EncodeBar`, `JobLogModal` (3 onglets), "
            "`DirBrowser`.\n"
            "- Handler WS niveau App avec backoff exponentiel (1, 2, 4, 8, "
            "max 30s). Appelle `syncFromServer()` à chaque ouverture.\n\n"
            "**Theming :** variables CSS sur `:root`. v3.4 a ajouté "
            "`--selected-bg` et `--selected-fg`."
        ),
    },
    {
        "id": "backend_modules",
        "title": "14. Modules du back-end",
        "body": (
            "**`main.py`** — point d'entrée FastAPI. Chaque endpoint HTTP, "
            "handler `/ws`, broadcaster d'événements 1 seconde, hook de "
            "démarrage.\n\n"
            "**`database.py`** — Couche d'accès aux données. Depuis v3.3, "
            "wrapper fin autour de SQLAlchemy 2.x Core qui traduit les "
            "placeholders `?` en named binds. `RETURNING id` sur Postgres ; "
            "`lastrowid` sur SQLite.\n\n"
            "**`db_engine.py`** — Factory d'Engine. Définit les tables via "
            "objets `Table`, configure PRAGMA WAL+NORMAL sur SQLite.\n\n"
            "**`db_backend.py`** — Décide quel backend utiliser selon "
            "`DB_BACKEND`.\n\n"
            "**`db_backup.py`** — Snapshot et restore. SQLite utilise "
            "online-backup API ; Postgres utilise `pg_dump -Fc -Z 6` et "
            "`pg_restore --clean --if-exists`.\n\n"
            "**`config.py`** — Load/save de `config.json` avec merge sur "
            "défauts.\n\n"
            "**`models.py`** — Modèles Pydantic. `Config` avec "
            "`extra='allow'`.\n\n"
            "**`scanner.py`** — Parcours du système de fichiers. Élague les "
            "dirs exclus pendant `os.walk`.\n\n"
            "**`worker/main.py`** — Boucle du worker. Handlers SIGTERM/"
            "SIGINT. `recover_stale_jobs()` au démarrage (v3.4 : retry × 10 × "
            "2s pour tolérer cold start Postgres). Heartbeat dans "
            "`/data/.worker_heartbeat`.\n\n"
            "**`worker/encoder.py`** — Le pipeline FFmpeg. `file_hash()`, "
            "`get_total_frames()`, `_advanced_args()`, `build_cmd()`, "
            "`encode_file()`."
        ),
    },
    {
        "id": "ffmpeg_basics",
        "title": "15. Bases de FFmpeg — paramètres obligatoires",
        "body": (
            "Ces quatre champs sont toujours appliqués, quel que soit "
            "l'encodeur. Avec tous les toggles avancés désactivés, l'encodage "
            "se comporte exactement comme v3.1.\n\n"
            "### `encoder`\n\n"
            "Le pipeline utilisé pour produire de la vidéo HEVC :\n\n"
            "- `cpu` — encodeur software `libx265`. **Le plus compatible.**\n"
            "- `vaapi` — GPU AMD/Intel via VAAPI. Rapide.\n"
            "- `qsv` — Intel Quick Sync Video. Très rapide.\n"
            "- `nvenc` — GPU NVIDIA. Très rapide.\n\n"
            "### `crf` — Constant Rate Factor\n\n"
            "Entier de 1 à 51 (utilisé comme `-qp` par les encodeurs GPU). "
            "**Plus bas = plus gros fichier, meilleure qualité.**\n\n"
            "- 18 — visuellement sans perte.\n"
            "- 23 — haute qualité.\n"
            "- 26 — **défaut Transcode Talker**.\n"
            "- 28 — compression visible mais regardable.\n"
            "- 32+ — forte compression, artefacts visibles.\n\n"
            "CRF est **quasi-logarithmique** : +6 double le bitrate.\n\n"
            "### `preset`\n\n"
            "Compromis vitesse/efficacité x265 : `ultrafast`..`slower`. De "
            "`medium` à `slow` économise 5–10% de bitrate au même CRF avec "
            "~2× le temps.\n\n"
            "### `ffmpeg_threads`\n\n"
            "Threads que `libx265` spawne. Défaut 4. N'affecte que "
            "l'encodeur CPU."
        ),
    },
    {
        "id": "ffmpeg_cpu",
        "title": "16. Encodeur FFmpeg — `cpu` (libx265)",
        "body": (
            "Forme de la commande (défauts, sans toggles avancés) :\n\n"
            "```\n"
            "ffmpeg -y \\\n"
            "  -progress pipe:2 -nostats \\\n"
            "  -i <source> \\\n"
            "  -map 0:V -map 0:a? -map 0:s? -map 0:t? \\\n"
            "  -c:v libx265 -crf <CRF> -preset <preset> -threads <N> \\\n"
            "  -c:a copy -c:s copy \\\n"
            "  -max_muxing_queue_size 1024 \\\n"
            "  <hdd_temp_path>/ENCODED_<stem><ext>\n"
            "```\n\n"
            "Pourquoi chaque flag :\n\n"
            "- `-y` — écrase sans demander.\n"
            "- `-progress pipe:2 -nostats` — progrès machine-readable.\n"
            "- `-map 0:V/a?/s?/t?` — toutes les streams (vidéo non-attached, "
            "audio, sous-titres, attachments).\n"
            "- `-c:v libx265 -crf -preset -threads` — encodeur et knobs "
            "obligatoires.\n"
            "- `-c:a copy` — audio copié bit-perfect.\n"
            "- `-c:s copy` — sous-titres copiés.\n"
            "- `-max_muxing_queue_size 1024` — évite l'épuisement des "
            "buffers du muxer."
        ),
    },
    {
        "id": "ffmpeg_vaapi",
        "title": "17. Encodeur FFmpeg — `vaapi` (GPU AMD/Intel)",
        "body": (
            "Depuis v3.4.1, la commande canonique (les flags legacy "
            "`-vaapi_device` et `-rc_mode` ont été retirés parce que ffmpeg 7 "
            "les rejette — voir B-020/B-021) :\n\n"
            "```\n"
            "ffmpeg -y \\\n"
            "  -init_hw_device vaapi=va:/dev/dri/renderD128 \\\n"
            "  -filter_hw_device va \\\n"
            "  -progress pipe:2 -nostats \\\n"
            "  -i <source> \\\n"
            "  -map 0:V -map 0:a? -map 0:s? -map 0:t? \\\n"
            "  -vf format=nv12,hwupload \\\n"
            "  -c:v hevc_vaapi -qp <CRF> \\\n"
            "  -c:a copy -c:s copy \\\n"
            "  ...\n"
            "```\n\n"
            "Spécifiques :\n\n"
            "- `-init_hw_device vaapi=va:<dev>` — crée un device hardware "
            "nommé `va`.\n"
            "- `-filter_hw_device va` — lie le filter graph au device.\n"
            "- `-vf format=nv12,hwupload` — convertit en NV12 et upload GPU.\n"
            "- `-c:v hevc_vaapi -qp <CRF>` — encodeur VAAPI HEVC en mode CQP "
            "automatique.\n\n"
            "**Prérequis dans le conteneur** (v3.4.1+ les fournit) :\n\n"
            "- `apt-get install ffmpeg vainfo libva-drm2 libva2 "
            "mesa-va-drivers`.\n"
            "- `/dev/dri` mappé dans compose.\n"
            "- Driver Mesa/AMD ou Intel fonctionnel sur l'hôte.\n\n"
            "**Validation :** `docker compose exec reencoder-worker vainfo` "
            "doit lister des profils comme `HEVCMain`."
        ),
    },
    {
        "id": "ffmpeg_qsv",
        "title": "18. Encodeur FFmpeg — `qsv` (Intel Quick Sync)",
        "body": (
            "```\n"
            "ffmpeg -y \\\n"
            "  -init_hw_device qsv=qs:/dev/dri/renderD128 \\\n"
            "  -filter_hw_device qs \\\n"
            "  -hwaccel qsv -hwaccel_output_format qsv \\\n"
            "  -i <source> \\\n"
            "  -map 0:V -map 0:a? -map 0:s? -map 0:t? \\\n"
            "  -c:v hevc_qsv -global_quality <CRF> -preset <preset> \\\n"
            "  ...\n"
            "```\n\n"
            "- `-hwaccel qsv -hwaccel_output_format qsv` — décodage et reste "
            "en GPU surfaces de bout en bout.\n"
            "- `-global_quality <CRF>` — bouton qualité QSV.\n\n"
            "**Prérequis :** iGPU Intel + `intel-media-va-driver` + un build "
            "FFmpeg avec QSV. Le paquet `ffmpeg` Debian standard **n'**inclut "
            "**pas** QSV — utilisez `jellyfin-ffmpeg`."
        ),
    },
    {
        "id": "ffmpeg_nvenc",
        "title": "19. Encodeur FFmpeg — `nvenc` (GPU NVIDIA)",
        "body": (
            "```\n"
            "ffmpeg -y \\\n"
            "  -i <source> \\\n"
            "  -map 0:V -map 0:a? -map 0:s? -map 0:t? \\\n"
            "  -c:v hevc_nvenc -rc constqp -qp <CRF> -preset <preset> \\\n"
            "  ...\n"
            "```\n\n"
            "- `-c:v hevc_nvenc` — encodeur NVIDIA HEVC.\n"
            "- `-rc constqp -qp <CRF>` — mode constant-QP.\n"
            "- `-preset` — `p1`..`p7`.\n\n"
            "**Prérequis :** GPU NVIDIA + driver hôte + "
            "`nvidia-container-toolkit` + FFmpeg avec CUDA. Le `ffmpeg` "
            "Debian standard **n'**inclut **pas** NVENC — utilisez "
            "`jellyfin-ffmpeg` ou BtbN."
        ),
    },
    {
        "id": "ffmpeg_advanced",
        "title": "20. Toggles avancés d'encodage",
        "body": (
            "L'onglet **Encode Settings** expose 10 toggles dans "
            "`advanced_encode`. Chaque toggle est `{enabled: bool, value: "
            "...}` et est **désactivé par défaut**.\n\n"
            "### `bitrate`\n\n"
            "`-b:v <value>` et optionnellement `-maxrate`/`-bufsize`. Utile "
            "pour plafond rigide.\n\n"
            "### `tune`\n\n"
            "`-tune <value>`. Valeurs libx265 : `psnr`, `ssim`, `grain`, "
            "`zerolatency`, `fastdecode`, `animation`.\n\n"
            "### `profile`, `level`, `tier`\n\n"
            "- `-profile:v` — `main`, `main10`, `main12`...\n"
            "- `-level` — `4.1`, `5.0`, `5.1`...\n"
            "- `-tier` (CPU uniquement) — `main` ou `high`.\n\n"
            "### `pixel_format` (CPU uniquement)\n\n"
            "`-pix_fmt yuv420p10le` pour HEVC 10-bit.\n\n"
            "### `gop` (keyint)\n\n"
            "`-g <keyint>`. Distance entre keyframes. Défaut x265 : 250.\n\n"
            "### `x265_params` (CPU uniquement)\n\n"
            "Chaîne brute de paramètres x265.\n\n"
            "### `audio`\n\n"
            "Passe audio de copy à re-encode. `{codec, bitrate}`.\n\n"
            "### `video_filters` (CPU uniquement)\n\n"
            "`-vf <filter_chain>`. Ex : `scale=-2:720`, `crop=...`, `yadif`."
        ),
    },
    {
        "id": "first_run",
        "title": "21. Première exécution",
        "body": (
            "1. **Déploiement.** Depuis la racine du dépôt : `docker compose "
            "build && docker compose up -d`.\n"
            "2. **Ouvrez l'UI** à `http://<host>:4246`.\n"
            "3. **Settings → Scan folders** — ajoutez au moins une ligne "
            "`{path, threshold_mb}`.\n"
            "4. **Settings → Encoder** — commencez avec `cpu`. Le plus "
            "compatible.\n"
            "5. **Settings → CRF** — laissez à 26 sauf raison forte.\n"
            "6. **Settings → HDD temp path** — disque avec espace suffisant.\n"
            "7. **Save configuration**, puis **Scan & Select** → **⟳ Scan** → "
            "sélectionnez un fichier → **▶ Encode**."
        ),
    },
    {
        "id": "running_an_encode",
        "title": "22. Lancer un encodage",
        "body": (
            "1. **Scan & Select** — clic **⟳ Scan**, déployez les dossiers, "
            "cochez les fichiers.\n"
            "2. **Démarrez l'encodage.** Clic **▶ Encode**.\n"
            "3. **Ajoutez du travail en vol.** Pendant encodage, le bouton "
            "devient **+ Add to Queue (N)**.\n"
            "4. **Stop.** Clic **■ Stop**, confirmez. Le fichier actuel est "
            "interrompu en ~5 secondes.\n"
            "5. **Fermez le navigateur et revenez plus tard.** L'UI restaure "
            "tout via `/api/session/active`.\n"
            "6. **Reboot.** Le worker revient et marque le job in-flight "
            "comme `failed`. Re-sélectionnez-le manuellement."
        ),
    },
    {
        "id": "history",
        "title": "23. Page Historique",
        "body": (
            "Chaque job qu'un worker a touché vit ici pour toujours (jusqu'à "
            "ce que vous le supprimiez).\n\n"
            "- **Filtrez** par encodeur, status ou plage de dates.\n"
            "- **Triez** en cliquant sur n'importe quel en-tête de colonne.\n"
            "- **View** ouvre JobLogModal — trois onglets :\n"
            "  - **Details** — snapshots ffprobe source vs destination "
            "côte-à-côte.\n"
            "  - **Events** — log JSONL filtré pour ce job, cherchable, "
            "exportable.\n"
            "  - **FFmpeg cmd** — commande exacte utilisée. Bouton copier.\n"
            "- **Export JSON** — snapshot complet schema v2.\n"
            "- **Import JSON** — merge. Dé-dupliqué par `(original_path, "
            "completed_at)`. Snapshot pré-import auto."
        ),
    },
    {
        "id": "backups",
        "title": "24. Sauvegardes de base de données",
        "body": (
            "Les sauvegardes vivent dans `/data/backups/`. Dialect-aware :\n\n"
            "- **SQLite** — online-backup API. Résultat : fichier `.db`.\n"
            "- **Postgres** — `pg_dump -Fc -Z 6`. Résultat : fichier "
            "`.dump`.\n\n"
            "Cycle de vie :\n\n"
            "- **Snapshot de démarrage automatique.** Chaque démarrage API.\n"
            "- **Snapshots manuels.** Jamais auto-élagués.\n"
            "- **Snapshot pré-restore** et **pré-import** automatiques.\n\n"
            "**Le restore refuse de tourner pendant un encodage actif** (409). "
            "Restore cross-dialect rejeté avec 400."
        ),
    },
    {
        "id": "logs_retention",
        "title": "25. Logs et rétention",
        "body": (
            "Deux surfaces de log :\n\n"
            "- **Logs de conteneur** — `docker compose logs`. Rotation 10MB × "
            "5 fichiers.\n"
            "- **Logs JSONL de session** — `/data/logs/session_<id>.jsonl`.\n\n"
            "**Contrôles de rétention** (Settings → Log Management) :\n\n"
            "- `log_retention_days` — 0 = pour toujours.\n"
            "- `clean_logs_on_startup` — active l'élagage automatique."
        ),
    },
    {
        "id": "appearance",
        "title": "26. Apparence",
        "body": (
            "Settings → Appearance :\n\n"
            "- **Theme** — `dark` / `light` / `auto`.\n"
            "- **Accent colour** — sélecteur de couleur.\n"
            "- **Brand name** — titre de l'en-tête.\n\n"
            "Les changements s'appliquent en direct sans recharger."
        ),
    },
    {
        "id": "testing",
        "title": "27. Tests",
        "body": (
            "Depuis la racine du dépôt avec Python de l'hôte :\n\n"
            "```\n"
            "pip install -r requirements-dev.txt\n"
            "pytest -v tests/\n"
            "```\n\n"
            "Les fixtures de `tests/conftest.py` forcent `DB_BACKEND=sqlite` "
            "et utilisent `DB_PATH`/`LOGS_DIR` monkey-patched pour des tests "
            "hermétiques. Fournissent aussi `fake_ffmpeg` et `fake_ffprobe`.\n\n"
            "**Layout de la suite (v3.4.1 — 140 tests) :** voir doc principal "
            "pour la liste complète par fichier."
        ),
    },
    {
        "id": "useful_commands",
        "title": "28. Commandes utiles et maintenance",
        "body": (
            "```\n"
            "# Logs en direct\n"
            "docker compose logs -f reencoder-api\n"
            "docker compose logs -f reencoder-worker\n"
            "\n"
            "# Redémarrer seulement le worker\n"
            "docker compose restart reencoder-worker\n"
            "\n"
            "# Healthcheck\n"
            "curl -s http://localhost:4246/api/health | jq\n"
            "\n"
            "# Backend DB actif\n"
            "curl -s http://localhost:4246/api/db/state | python3 -m json.tool\n"
            "\n"
            "# Shell Postgres\n"
            "docker compose exec postgres psql -U reencoder -d reencoder\n"
            "\n"
            "# Force-reset (débloque session zombie)\n"
            "curl -s -X POST http://localhost:4246/api/encode/force-reset \\\n"
            "  -H 'Content-Type: application/json' -d '{}'\n"
            "\n"
            "# Snapshot manuel DB\n"
            "curl -s -X POST http://localhost:4246/api/db/backup \\\n"
            "  -H 'Content-Type: application/json' -d '{\"label\":\"pre-update\"}'\n"
            "\n"
            "# Nettoyer vieux logs JSONL\n"
            "docker compose exec reencoder-api find /data/logs \\\n"
            "  -name 'session_*.jsonl' -mtime +30 -delete\n"
            "\n"
            "# Valider VAAPI\n"
            "docker compose exec reencoder-worker ffmpeg -hide_banner -hwaccels\n"
            "docker compose exec reencoder-worker vainfo 2>&1 | head -20\n"
            "\n"
            "# Rebuild from scratch\n"
            "docker compose down\n"
            "docker compose build --no-cache && docker compose up -d\n"
            "\n"
            "# DANGER : reset complet (préserve config.json)\n"
            "docker compose down\n"
            "sudo rm -rf data/postgres data/reencoder.db data/logs data/backups\n"
            "docker compose build && docker compose up -d\n"
            "```"
        ),
    },
    {
        "id": "troubleshooting",
        "title": "29. Dépannage",
        "body": (
            "**Bouton Encode ne fait rien, log montre `409 Conflict`.** Vous "
            "êtes en ≤v3.3 contre Postgres (B-018). Mettez à jour vers v3.4+. "
            "Workaround : `POST /api/encode/force-reset`.\n\n"
            "**Light mode — ligne sélectionnée invisible.** Issue ≤v3.3 "
            "(B-019). Mettez à jour vers v3.4+.\n\n"
            "**Encode GPU échoue avec `Unrecognized option 'vaapi_device'` "
            "ou `'rc_mode'`.** ≤v3.4 + ffmpeg 7 (B-020/B-021). Mettez à jour "
            "vers v3.4.1+ et rebuild du worker.\n\n"
            "**Encode GPU échoue avec `Device creation failed: -12`.** "
            "≤v3.4 (B-022). Mettez à jour vers v3.4.1+. Validez avec "
            "`docker compose exec reencoder-worker vainfo`.\n\n"
            "**API en crash loop avec `password authentication failed`.** "
            "`POSTGRES_PASSWORD` changée après le premier boot ; le volume "
            "garde l'ancien mot de passe. Effacez `data/postgres/` (perte "
            "d'historique — backup d'abord) ou `ALTER USER`.\n\n"
            "**Erreurs `database is locked` (SQLite seulement).** Assurez-"
            "vous qu'un seul worker tourne.\n\n"
            "**Historique disparu après rebuild.** L'API loge `WARNING: DB "
            "file exists but has no history rows`. Settings → Database "
            "Backups → restaurez le snapshot `startup`.\n\n"
            "**Encode bloqué à `Computing hash...`.** Fichier source sur "
            "système de fichiers lent (NFS/SMB). Réglez `full_hash=false`."
        ),
    },
    {
        "id": "credits",
        "title": "30. Crédits et références",
        "body": (
            "Le nom **Transcode Talker** est un clin d'œil à *Decode Talker* "
            "— un Cyberse Link Monster de Yu-Gi-Oh ! Comme son homonyme, le "
            "but est de prendre quelque chose de plus grand et de le lier "
            "vers une forme plus efficace.\n\n"
            "Construit sur :\n\n"
            "- **FFmpeg** + libx265 + libva + drivers Mesa\n"
            "- **FastAPI** + **Uvicorn** + **Pydantic** + **SQLAlchemy 2.x**\n"
            "- **React 18** via CDN unpkg + `@babel/standalone`\n"
            "- **Postgres 16-alpine** (défaut) ou **SQLite WAL** (legacy)\n"
            "- **Docker** + **Docker Compose**\n"
            "- **pytest** pour la suite de régression de 140 tests\n\n"
            "Mainteneur : Rafael Mello."
        ),
    },
]
_ZH_CN = [
    {
        "id": "intro",
        "title": "1. 什么是 Transcode Talker？",
        "body": (
            "**Transcode Talker** 是一个自托管的批量视频重编码器。它扫描您配置的"
            "文件夹，让您选择使用 FFmpeg（CPU 上的 libx265，或 GPU 流水线 — "
            "VAAPI/QSV/NVENC）重编码哪些文件，并且**仅当结果真的更小时**用更小"
            "的 HEVC 版本替换原始文件。如果重编码后的文件最终更大，会被丢弃并将"
            "该作业标记为 `skipped`。\n\n"
            "它由两个 Docker 容器构成 — 一个 **API + UI** 和一个 **worker** — "
            "它们通过数据库（v3.4 起默认 Postgres，SQLite WAL 作为遗留方案）"
            "和 JSONL 日志文件共享状态。这种分离是刻意的：编码可能持续数小时，"
            "此设计确保即使浏览器关闭、API 重启或 worker 重启，编码仍会继续。"
            "只有在编码中途被杀掉的 worker 才会丢失当前文件（在下次 worker 启"
            "动时被恢复为 `failed`）。\n\n"
            "目标很简单：减少您的媒体库占用的磁盘空间，同时保留所有音轨、所有"
            "字幕、所有附件，以及相同的播放保真度（由 CRF — Constant Rate "
            "Factor 控制）。"
        ),
    },
    {
        "id": "architecture",
        "title": "2. 架构概览",
        "body": (
            "两个 Docker 容器和一个可选的数据库容器，运行在私有 bridge 网络上：\n\n"
            "- **reencoder-api**（FastAPI 在端口 4246）— 提供 React UI、HTTP "
            "API 和 WebSocket 事件流。拥有 schema，读写数据库。**不会**启动 "
            "FFmpeg。\n"
            "- **reencoder-worker**（Python 循环）— 每 "
            "`worker_poll_interval_s` 秒轮询数据库寻找带有 queued 作业的 "
            "`running` 会话，然后一次一个文件运行 FFmpeg。在数据库中更新作业"
            "进度，并向 JSONL 日志追加事件。\n"
            "- **postgres**（自 v3.4 为默认；可选）— Postgres 16-alpine，"
            "数据持久化在 `data/postgres/`。SQLite 仍通过 `DB_BACKEND=sqlite` "
            "支持。\n\n"
            "为什么是两个进程而不是一个？三个原因：\n\n"
            "1. **弹性。** FastAPI 重启不会杀死编码。\n"
            "2. **资源隔离。** Worker 在 docker-compose 中获得专用的 CPU/"
            "内存限制（默认 8 CPU，8G RAM）。\n"
            "3. **关注点分离。** API 处理请求/响应 + websocket；worker 是"
            "长时间运行的子进程管理器。\n\n"
            "**API 和 worker 之间没有 HTTP** — 它们只通过共享数据库（Postgres "
            "或 SQLite WAL）和 `/data/logs/` 下的 JSONL 事件文件通信。这是有"
            "意的：数据库是唯一的真理来源。"
        ),
    },
    {
        "id": "components_diagram",
        "title": "3. 组件图",
        "body": (
            "```\n"
            "                 ┌─────────────────────┐\n"
            "                 │ 浏览器 (React UI)   │\n"
            "                 └─────────┬───────────┘\n"
            "                           │ HTTP + WebSocket\n"
            "                           ▼\n"
            "                 ┌─────────────────────┐\n"
            "                 │   reencoder-api     │  FastAPI :4246\n"
            "                 └────┬────────────┬───┘\n"
            "                      ▼            ▼\n"
            "             ┌─────────────┐  ┌──────────────┐\n"
            "             │  数据库     │  │  /data/logs/ │\n"
            "             │ (Postgres   │◄─┤  *.jsonl     │\n"
            "             │  或 SQLite) │  └──────────────┘\n"
            "             └──────┬──────┘          ▲\n"
            "                    ▼                 │\n"
            "             ┌─────────────────┐      │\n"
            "             │ reencoder-worker│──────┘  Python 轮询循环\n"
            "             │  (Python 循环)  │         调用 FFmpeg\n"
            "             └────────┬────────┘\n"
            "                      ▼\n"
            "             ┌────────────────────────┐\n"
            "             │  FFmpeg + /dev/dri     │  GPU VAAPI\n"
            "             │  + /mnt/media          │  源文件\n"
            "             │  + /mnt/hdd            │  编码临时区\n"
            "             └────────────────────────┘\n"
            "```\n\n"
            "所有持久状态存在于三个地方：\n\n"
            "- **数据库** — `sessions`、`jobs`、`scan_results` 表。\n"
            "- **JSONL 事件日志文件** — 每个会话一个 append-only 文件。\n"
            "- **配置** (`/data/config.json`) — UI 可编辑的每个设置。"
        ),
    },
    {
        "id": "flow_scan_encode",
        "title": "4. 端到端流程：扫描 → 选择 → 编码",
        "body": (
            "```\n"
            "用户 → UI:           POST /api/scan\n"
            "UI → API:            遍历 scan_folders，返回 ScannedFile 列表\n"
            "API → DB:            替换 scan_results 行为新快照\n"
            "API → UI:            {files: [...]}\n"
            "\n"
            "用户 → UI:           选择文件，点击 ▶ Encode\n"
            "UI → API:            POST /api/encode/start {paths}\n"
            "API → DB:            检查没有活动会话（dialect-aware 锁：\n"
            "                     SQLite 用 BEGIN IMMEDIATE，\n"
            "                     Postgres 用 pg_advisory_xact_lock）\n"
            "API → DB:            INSERT session(running) + N 个 jobs(queued)\n"
            "API → UI:            {ok, session_id}\n"
            "\n"
            "Worker 循环（每 worker_poll_interval_s，默认 2s）：\n"
            "  Worker → DB:       SELECT 活动会话\n"
            "  Worker → DB:       SELECT 该会话中下一个 queued 作业\n"
            "  Worker → DB:       UPDATE job status=encoding\n"
            "  Worker → FFmpeg:   用 build_cmd(...) 启动\n"
            "  FFmpeg 运行时每 0.5s 循环：\n"
            "    Worker → DB:     is_session_interrupted? (stop check)\n"
            "    FFmpeg → stderr: 进度 key=value\n"
            "    Worker → DB:     update_job_progress（节流到每 2s 一次）\n"
            "    Worker → JSONL:  追加进度事件\n"
            "  FFmpeg 退出时：\n"
            "    Worker → ffprobe: verify_file (codec_name == libx265 / hevc)\n"
            "    Worker → fs:     比较大小；若 encoded >= original 则 skip\n"
            "    Worker → fs:     shutil.move HDD_temp → 原路径\n"
            "    Worker → DB:     UPDATE job status=completed\n"
            "```\n\n"
            "**API 事件广播器**（后台任务）每 1s tail 每个会话的 JSONL 文件，"
            "将新行推送到所有连接的 WebSocket 客户端。"
        ),
    },
    {
        "id": "flow_stop",
        "title": "5. 端到端流程：停止",
        "body": (
            "```\n"
            "用户 → UI:           点击 ■ Stop，确认\n"
            "UI → API:            POST /api/encode/stop\n"
            "API → DB:            UPDATE session status=interrupted\n"
            "API → DB:            UPDATE jobs (queued, encoding) → interrupted\n"
            "\n"
            "Worker（下一个 stop_check_interval_s tick，默认 0.5s）：\n"
            "  Worker → DB:       is_session_interrupted? → True\n"
            "  Worker → FFmpeg:   SIGTERM\n"
            "  等待最多 5 秒：\n"
            "    如果仍在运行： SIGKILL\n"
            "  Worker → fs:       _cleanup(hdd_encoded)\n"
            "```\n\n"
            "停止**默认是优雅的**：SIGTERM 给 FFmpeg 最多 5 秒来完成写入其 mux "
            "trailer 并干净退出。只有当它不响应时，worker 才会升级到 SIGKILL。"
        ),
    },
    {
        "id": "flow_recovery",
        "title": "6. 端到端流程：崩溃恢复",
        "body": (
            "当 worker 容器启动时，它在进入轮询循环之前运行 "
            "`recover_stale_jobs()`。任何状态为 `encoding` 的作业都被标记为 "
            "`failed`，`error_msg='Worker crashed or restarted'`。\n\n"
            "**v3.4 还添加了 `/api/encode/force-reset`** 作为深度防御："
            "如果会话保持 `running` 但没有实际的 worker，用户可以调用此端点"
            "（或接受 UI 在卡住的 409 上显示的自动 `confirm()`）将所有 "
            "`running` 会话标记为 `interrupted`。"
        ),
    },
    {
        "id": "flow_websocket",
        "title": "7. 端到端流程：WebSocket 同步和重连",
        "body": (
            "```\n"
            "UI:                  连接 ws://host:4246/ws\n"
            "API:                 接受，加入 _ws_clients 集合\n"
            "UI:                  GET /api/session/active\n"
            "API → DB:            获取活动或最近会话\n"
            "API → UI:            {session, jobs, events}\n"
            "\n"
            "API 后台循环（每 1s）：\n"
            "  API → JSONL:       tail 活动会话的新行\n"
            "  API → 所有 WS:     广播新事件\n"
            "\n"
            "WebSocket 关闭时：\n"
            "  UI:                指数退避等待 (1s, 2s, 4s, 8s, 最大 30s)\n"
            "  UI:                重连，从顶部重复\n"
            "```\n\n"
            "`progress` 事件只更新实时计数器以保持快速响应。结构性事件触发"
            "完整的 `syncFromServer()`。"
        ),
    },
    {
        "id": "directory_structure",
        "title": "8. 目录和容器结构",
        "body": (
            "**仓库布局：**\n\n"
            "```\n"
            "reencoder-v3/\n"
            "├── docker-compose.yml\n"
            "├── .env.example\n"
            "├── data/                         # 挂载到 /data 的持久卷\n"
            "│   ├── config.json\n"
            "│   ├── reencoder.db              # 仅 SQLite\n"
            "│   ├── postgres/                 # Postgres 数据卷\n"
            "│   ├── backups/                  # 自动+手动快照\n"
            "│   └── logs/session_<id>.jsonl\n"
            "├── reencoder-api/\n"
            "│   ├── app/main.py, database.py, db_engine.py, db_backup.py,\n"
            "│   │   config.py, models.py, scanner.py, help_content.py\n"
            "│   └── static/index.html         # 内联 React UI\n"
            "├── reencoder-worker/\n"
            "│   ├── Dockerfile                # apt ffmpeg + mesa-va-drivers (v3.4.1)\n"
            "│   └── worker/main.py, encoder.py, database.py\n"
            "└── tests/                        # pytest 套件（v3.4.1 中 140 个测试）\n"
            "```\n\n"
            "**主机文件系统期望：**\n\n"
            "| 主机路径 | 容器路径 | 用途 |\n"
            "|---|---|---|\n"
            "| `./data` | `/data` | DB、配置、日志、备份 |\n"
            "| `/mnt/animes`, `/mnt/media` | 相同 | 媒体库 |\n"
            "| `/mnt/hdd` | `/mnt/hdd` | 慢盘作为编码临时区 |\n"
            "| `/dev/dri` | `/dev/dri` | GPU 设备（仅 worker） |"
        ),
    },
    {
        "id": "data_model",
        "title": "9. 数据模型（数据库 schema）",
        "body": (
            "三个表，在 SQLite 和 Postgres 上形状相同。迁移是幂等的。\n\n"
            "**`sessions`** — 每次 Start Encode 点击一行。\n\n"
            "列：`id` (TEXT PK，8 字符截断的 UUID)，`status` (pending/running/"
            "completed/interrupted)，`total_files`、`done_files`、"
            "`created_at`、`updated_at`。\n\n"
            "**`jobs`** — 会话中每个文件一行。\n\n"
            "主要列：`id`、`session_id`、`filename`、`original_path`、"
            "`original_size_mb`、`final_size_mb`、`space_saved_mb`、"
            "`original_hash`、`encoded_hash`、`crf_used`、`encoder_used`、"
            "`status` (queued/encoding/completed/failed/skipped/interrupted)、"
            "`current_frame`、`total_frames`、`pct`、`fps`、`speed`、`eta_s`、"
            "`error_msg`、`started_at`、`completed_at`、`source_metadata` "
            "(JSON, v3.3+)、`destination_metadata` (JSON, v3.3+)、"
            "`ffmpeg_cmd` (v3.3+)。\n\n"
            "**`scan_results`** — 单行，每次新扫描时替换。\n\n"
            "**JSONL 事件日志**：每行一个 JSON 对象。事件类型：`queue_start`、"
            "`queue_done`、`queue_stopped`、`file_start`、`file_done`、`step`、"
            "`progress`、`error`、`skipped`、`stopped`、`done`、`ffmpeg_cmd`。"
        ),
    },
    {
        "id": "config_env",
        "title": "10. 环境变量 (.env)",
        "body": (
            "由 `docker-compose.yml` 读取。`.env` 是可选的 — Postgres 默认值"
            "不安全但开箱即用。**在任何非本地部署中，将 `.env.example` 复制"
            "为 `.env` 并在首次 `docker compose up` 前设置强密码。**\n\n"
            "| 变量 | 默认 | 效果 |\n"
            "|---|---|---|\n"
            "| `DB_BACKEND` | `postgres` (v3.4+) | `postgres` 或 `sqlite` |\n"
            "| `POSTGRES_HOST` | `postgres` | compose 服务名 |\n"
            "| `POSTGRES_PORT` | `5432` | |\n"
            "| `POSTGRES_USER` | `reencoder` | |\n"
            "| `POSTGRES_PASSWORD` | `reencoder` | **生产环境必须更改** |\n"
            "| `POSTGRES_DB` | `reencoder` | |\n"
            "| `TZ` | `America/New_York` | 时区 |\n"
            "| `BASIC_AUTH_USER`, `BASIC_AUTH_PASS` | 空 | HTTP Basic 认证 |\n\n"
            "**关于 Postgres 密码的提醒：** Postgres 仅在数据卷为空时应用 "
            "`POSTGRES_PASSWORD`。如果在运行中更改，要么擦除 `data/postgres/`"
            "（丢失历史 — 先备份），要么在容器内 `ALTER USER reencoder WITH "
            "PASSWORD '<new>'`。"
        ),
    },
    {
        "id": "config_json",
        "title": "11. 配置字段 (config.json)",
        "body": (
            "所有 UI 可编辑设置都在 `/data/config.json`，与 `app/models.py:"
            "Config` 中的 Pydantic 字段一一对应。\n\n"
            "**扫描和排除：**\n\n"
            "- `scan_folders: list[{path, threshold_mb}]` — 要遍历的文件夹。\n"
            "- `exclude_folders: list[str]` — 不区分大小写的前缀匹配。\n"
            "- `extensions: list[str]` — 考虑的扩展名。默认：`.mkv .mp4 .avi "
            ".mov`。\n\n"
            "**强制编码器参数：**\n\n"
            "- `encoder: cpu | vaapi | qsv | nvenc`\n"
            "- `crf: int` (1..51) — **越低 = 文件越大，质量越高。** HEVC "
            "典型 23–28。26 是好的默认值。\n"
            "- `preset: ultrafast..slower`\n"
            "- `ffmpeg_threads: int`\n\n"
            "**路径和二进制：**\n\n"
            "- `hdd_temp_path: str` — 运行期间编码输出所在。\n"
            "- `ffmpeg_path`, `ffprobe_path`\n"
            "- `vaapi_device_path: str` — 默认 `/dev/dri/renderD128`。\n\n"
            "**行为调优：**\n\n"
            "- `full_hash: bool` — true 时哈希整个文件。\n"
            "- `skip_hevc_below_kbps: int` — 若源已是 HEVC 且低于此阈值则"
            "跳过。\n"
            "- `stall_timeout_s: int`（默认 60）。\n"
            "- `worker_poll_interval_s: float`（默认 2.0）。\n"
            "- `stop_check_interval_s: float`（默认 0.5）。\n\n"
            "**日志和外观：**\n\n"
            "- `log_retention_days: int`（默认 30，0 = 永远）。\n"
            "- `clean_logs_on_startup: bool`。\n"
            "- `theme`、`accent_color`、`brand_name`。\n\n"
            "**高级编码** (`advanced_encode: dict`) — 见第 20 节。"
        ),
    },
    {
        "id": "api_reference",
        "title": "12. API 参考",
        "body": (
            "所有端点返回 JSON。配置时使用 HTTP Basic 认证。唯一例外是 "
            "`/api/health`，始终匿名以便 Docker 健康检查工作。\n\n"
            "**Health 和元数据：**\n"
            "- `GET /` — 提供 React UI。\n"
            "- `GET /api/health` — `{ok, ts}`。\n"
            "- `WS  /ws` — 事件流。\n\n"
            "**配置：** `GET/POST /api/config`、`/api/config/first-run`、"
            "`POST /api/config/exclude-folder`。\n\n"
            "**浏览：** `GET /api/browse?path=...` — 限制在 `/mnt`。\n\n"
            "**扫描：** `POST /api/scan`、`GET /api/scan/last`。\n\n"
            "**编码：**\n"
            "- `POST /api/encode/start` — 409 与 `{error, "
            "active_session_id}` 如果有活动会话。\n"
            "- `POST /api/encode/stop`\n"
            "- `POST /api/encode/force-reset` (v3.4) — 清除僵尸 `running` "
            "会话。\n"
            "- `POST /api/encode/queue/add`\n"
            "- `GET  /api/encode/status`\n\n"
            "**会话和历史：**\n"
            "- `GET  /api/session/active`\n"
            "- `GET  /api/history?...` — 分页、过滤、排序。\n"
            "- `GET  /api/history/stats`、`/encoded-paths`、`/export`\n"
            "- `POST /api/history/import`\n"
            "- `DELETE /api/history/{id}`、bulk-delete\n\n"
            "**每作业日志：** `GET /api/jobs/{id}/logs`、`/logs/export`\n\n"
            "**数据库管理：** `GET /api/db/state`、`/backups`、`POST "
            "/api/db/backup`、`/restore`。\n\n"
            "**手册：** `GET /api/help?lang=...`。"
        ),
    },
    {
        "id": "frontend",
        "title": "13. 前端 (static/index.html)",
        "body": (
            "整个 UI 存在于**一个 HTML 文件**中，约 2100 行。从 unpkg CDN 加载 "
            "React 18 和 ReactDOM，加上 `@babel/standalone` 在浏览器中转换 "
            "JSX。没有打包器，没有 `npm install`，没有 TypeScript。\n\n"
            "**页面：**\n\n"
            "- **Scan & Select** — 运行扫描，按文件夹分组到可折叠树，过滤"
            "（all / never encoded / done），add-to-exclusion，按文件夹的"
            "完成徽章。\n"
            "- **Encode** — 当前作业进度条，队列列表，实时事件日志。\n"
            "- **History** — 分页表格，列排序和过滤栏。Export/Import JSON。"
            "View 打开 JobLogModal。\n"
            "- **Settings** — 可折叠部分，每个字段都有 `ⓘ` 工具提示。\n"
            "- **Encode Settings** — 4 个强制参数 + 10 个可切换高级卡片。\n"
            "- **Help** — 这个手册，多语言。\n\n"
            "**关键组件：**\n\n"
            "- `api` 对象、`EncodeBar`、`JobLogModal`（3 个选项卡）、"
            "`DirBrowser`。\n"
            "- 应用级 WebSocket 处理器，重连时指数退避（1、2、4、8、最大 "
            "30s）。每次打开时调用 `syncFromServer()`。\n\n"
            "**主题：** `:root` 上的 CSS 变量。v3.4 添加了 `--selected-bg` "
            "和 `--selected-fg`。"
        ),
    },
    {
        "id": "backend_modules",
        "title": "14. 后端模块",
        "body": (
            "**`main.py`** — FastAPI 入口点。每个 HTTP 端点、`/ws` 处理器、"
            "1 秒事件广播后台任务、启动钩子。\n\n"
            "**`database.py`** — 数据访问层。自 v3.3 起是围绕 SQLAlchemy "
            "2.x Core 的薄包装器，将 `?` 占位符转换为命名绑定。Postgres 上 "
            "`RETURNING id`；SQLite 上 `lastrowid`。\n\n"
            "**`db_engine.py`** — Engine 工厂。通过 `Table` 对象定义表，"
            "在 SQLite 上设置 PRAGMA WAL+NORMAL。\n\n"
            "**`db_backend.py`** — 根据 `DB_BACKEND` 决定使用哪个后端。\n\n"
            "**`db_backup.py`** — 快照和恢复。SQLite 使用 online-backup "
            "API；Postgres 使用 `pg_dump -Fc -Z 6` 和 `pg_restore --clean "
            "--if-exists`。\n\n"
            "**`config.py`** — 加载/保存 `config.json`，与默认值合并。\n\n"
            "**`models.py`** — Pydantic 模型。`Config` 带 `extra='allow'`。\n\n"
            "**`scanner.py`** — 文件系统遍历。在 `os.walk` 期间修剪排除"
            "的 dirs。\n\n"
            "**`worker/main.py`** — Worker 循环。SIGTERM/SIGINT 处理器。"
            "启动时运行 `recover_stale_jobs()`（v3.4：重试 × 10 × 2s 以"
            "容忍 Postgres 冷启动）。`/data/.worker_heartbeat` 中的心跳。\n\n"
            "**`worker/encoder.py`** — FFmpeg 流水线。`file_hash()`、"
            "`get_total_frames()`、`_advanced_args()`、`build_cmd()`、"
            "`encode_file()`。"
        ),
    },
    {
        "id": "ffmpeg_basics",
        "title": "15. FFmpeg 基础 — 强制参数",
        "body": (
            "这四个字段始终适用，无论使用哪个编码器。关闭所有高级切换会让"
            "编码行为与 v3.1 完全相同。\n\n"
            "### `encoder`\n\n"
            "用于产生 HEVC 视频的流水线：\n\n"
            "- `cpu` — 软件编码器 `libx265`。**最兼容。** 最慢，但相同 CRF "
            "下产生最小文件。\n"
            "- `vaapi` — 通过 VAAPI 的 AMD/Intel GPU。快。相同 CRF 下质量"
            "低于 libx265，但压缩仍然良好。\n"
            "- `qsv` — Intel Quick Sync Video。非常快。\n"
            "- `nvenc` — NVIDIA GPU。非常快。\n\n"
            "### `crf` — Constant Rate Factor\n\n"
            "整数 1 到 51（GPU 编码器用作 `-qp`）。**越低 = 文件越大，质量"
            "越高。**\n\n"
            "- 18 — 大多数内容视觉上无损。\n"
            "- 23 — 高质量。\n"
            "- 26 — **Transcode Talker 默认**。HEVC 的良好平衡。\n"
            "- 28 — 明显压缩但仍可观看。\n"
            "- 32+ — 强压缩，可见伪影。\n\n"
            "CRF 是**准对数的**：每 +6 比特率翻倍。\n\n"
            "### `preset`\n\n"
            "x265 的速度-效率权衡：`ultrafast`..`slower`。从 `medium` 到 "
            "`slow` 通常在相同 CRF 下节省 5–10% 比特率，代价是 ~2× 编码"
            "时间。\n\n"
            "### `ffmpeg_threads`\n\n"
            "`libx265` 生成的线程数。默认 4。仅影响 CPU 编码器。"
        ),
    },
    {
        "id": "ffmpeg_cpu",
        "title": "16. FFmpeg 编码器 — `cpu` (libx265)",
        "body": (
            "命令形式（默认，无高级切换）：\n\n"
            "```\n"
            "ffmpeg -y \\\n"
            "  -progress pipe:2 -nostats \\\n"
            "  -i <source> \\\n"
            "  -map 0:V -map 0:a? -map 0:s? -map 0:t? \\\n"
            "  -c:v libx265 -crf <CRF> -preset <preset> -threads <N> \\\n"
            "  -c:a copy -c:s copy \\\n"
            "  -max_muxing_queue_size 1024 \\\n"
            "  <hdd_temp_path>/ENCODED_<stem><ext>\n"
            "```\n\n"
            "每个标志的原因：\n\n"
            "- `-y` — 不提示直接覆盖。\n"
            "- `-progress pipe:2 -nostats` — 机器可读的进度。\n"
            "- `-map 0:V/a?/s?/t?` — 所有流（视频、音频、字幕、附件）。\n"
            "- `-c:a copy` — 音频按位完美复制。\n"
            "- `-c:s copy` — 字幕逐字复制。\n"
            "- `-max_muxing_queue_size 1024` — 防止 muxer 缓冲区用完。"
        ),
    },
    {
        "id": "ffmpeg_vaapi",
        "title": "17. FFmpeg 编码器 — `vaapi` (AMD/Intel GPU)",
        "body": (
            "自 v3.4.1，规范命令（移除了遗留的 `-vaapi_device` 和 "
            "`-rc_mode`，因为 ffmpeg 7 拒绝它们 — 见 B-020/B-021）：\n\n"
            "```\n"
            "ffmpeg -y \\\n"
            "  -init_hw_device vaapi=va:/dev/dri/renderD128 \\\n"
            "  -filter_hw_device va \\\n"
            "  -progress pipe:2 -nostats \\\n"
            "  -i <source> \\\n"
            "  -map 0:V -map 0:a? -map 0:s? -map 0:t? \\\n"
            "  -vf format=nv12,hwupload \\\n"
            "  -c:v hevc_vaapi -qp <CRF> \\\n"
            "  -c:a copy -c:s copy \\\n"
            "  ...\n"
            "```\n\n"
            "细节：\n\n"
            "- `-init_hw_device vaapi=va:<dev>` — 创建名为 `va` 的硬件设备。\n"
            "- `-filter_hw_device va` — 将 filter graph 绑定到设备。\n"
            "- `-vf format=nv12,hwupload` — 转换为 NV12 并上传到 GPU。\n"
            "- `-c:v hevc_vaapi -qp <CRF>` — VAAPI HEVC 编码器，自动 CQP "
            "模式。\n\n"
            "**容器内要求**（v3.4.1+ 开箱即用）：\n\n"
            "- `apt-get install ffmpeg vainfo libva-drm2 libva2 "
            "mesa-va-drivers`。\n"
            "- `/dev/dri` 必须在 docker-compose.yml 中映射。\n"
            "- 主机必须有工作的 Mesa/AMD 或 Intel 驱动。\n\n"
            "**验证：** `docker compose exec reencoder-worker vainfo` 应列出"
            "如 `HEVCMain` 的配置。"
        ),
    },
    {
        "id": "ffmpeg_qsv",
        "title": "18. FFmpeg 编码器 — `qsv` (Intel Quick Sync)",
        "body": (
            "```\n"
            "ffmpeg -y \\\n"
            "  -init_hw_device qsv=qs:/dev/dri/renderD128 \\\n"
            "  -filter_hw_device qs \\\n"
            "  -hwaccel qsv -hwaccel_output_format qsv \\\n"
            "  -i <source> \\\n"
            "  -map 0:V -map 0:a? -map 0:s? -map 0:t? \\\n"
            "  -c:v hevc_qsv -global_quality <CRF> -preset <preset> \\\n"
            "  ...\n"
            "```\n\n"
            "- `-hwaccel qsv -hwaccel_output_format qsv` — 解码并端到端保持 "
            "GPU surfaces。\n"
            "- `-global_quality <CRF>` — QSV 的质量旋钮。\n\n"
            "**要求：** Intel iGPU + `intel-media-va-driver` + 启用 QSV 的 "
            "FFmpeg 构建。Debian 默认 `ffmpeg` 包**不**包含 QSV — 使用 "
            "`jellyfin-ffmpeg`。"
        ),
    },
    {
        "id": "ffmpeg_nvenc",
        "title": "19. FFmpeg 编码器 — `nvenc` (NVIDIA GPU)",
        "body": (
            "```\n"
            "ffmpeg -y \\\n"
            "  -i <source> \\\n"
            "  -map 0:V -map 0:a? -map 0:s? -map 0:t? \\\n"
            "  -c:v hevc_nvenc -rc constqp -qp <CRF> -preset <preset> \\\n"
            "  ...\n"
            "```\n\n"
            "- `-c:v hevc_nvenc` — NVIDIA HEVC 编码器。\n"
            "- `-rc constqp -qp <CRF>` — 恒定 QP 模式。\n"
            "- `-preset` — `p1`..`p7`。\n\n"
            "**要求：** NVIDIA GPU + 主机驱动 + `nvidia-container-toolkit` + "
            "启用 CUDA 的 FFmpeg。Debian 默认 `ffmpeg` 包**不**包含 NVENC — "
            "使用 `jellyfin-ffmpeg` 或 BtbN 的预构建二进制。"
        ),
    },
    {
        "id": "ffmpeg_advanced",
        "title": "20. 高级编码切换",
        "body": (
            "**Encode Settings** 选项卡在 `advanced_encode` 中暴露了 10 个"
            "切换。每个切换是 `{enabled: bool, value: ...}` 并**默认关闭**。"
            "全部关闭时，命令与 v3.1 字节相同。\n\n"
            "### `bitrate`\n\n"
            "设置 `-b:v <value>` 和可选的 `-maxrate`/`-bufsize`。\n\n"
            "### `tune`\n\n"
            "添加 `-tune <value>`。libx265 允许的值：`psnr`、`ssim`、`grain`、"
            "`zerolatency`、`fastdecode`、`animation`。\n\n"
            "### `profile`、`level`、`tier`\n\n"
            "- `-profile:v` — `main`、`main10`、`main12`...\n"
            "- `-level` — `4.1`、`5.0`、`5.1`...\n"
            "- `-tier`（仅 CPU）— `main` 或 `high`。\n\n"
            "### `pixel_format`（仅 CPU）\n\n"
            "`-pix_fmt yuv420p10le` 用于 10 位 HEVC。\n\n"
            "### `gop` (keyint)\n\n"
            "`-g <keyint>`。关键帧之间的距离。x265 默认值为 250。\n\n"
            "### `x265_params`（仅 CPU）\n\n"
            "原始 x265 参数字符串。\n\n"
            "### `audio`\n\n"
            "将音频从 copy 切换为重编码。`{codec, bitrate}`。\n\n"
            "### `video_filters`（仅 CPU）\n\n"
            "`-vf <filter_chain>`。例：`scale=-2:720`、`crop=...`、`yadif`。"
        ),
    },
    {
        "id": "first_run",
        "title": "21. 首次运行",
        "body": (
            "1. **部署。** 从仓库根目录：`docker compose build && docker "
            "compose up -d`。\n"
            "2. **打开 UI** 在 `http://<host>:4246`。\n"
            "3. **Settings → Scan folders** — 添加至少一行 `{path, "
            "threshold_mb}`。\n"
            "4. **Settings → Encoder** — 从 `cpu` 开始。最兼容。\n"
            "5. **Settings → CRF** — 除非有强烈理由，否则保持 26。\n"
            "6. **Settings → HDD temp path** — 必须在有足够空间的磁盘上。\n"
            "7. **Save configuration**，然后 **Scan & Select** → **⟳ Scan** "
            "→ 选择一个文件 → **▶ Encode**。"
        ),
    },
    {
        "id": "running_an_encode",
        "title": "22. 运行编码",
        "body": (
            "1. **Scan & Select** — 点击 **⟳ Scan**，展开文件夹，勾选文件。\n"
            "2. **开始编码。** 点击 **▶ Encode**。\n"
            "3. **运行中添加更多工作。** 编码时，按钮变为 **+ Add to "
            "Queue (N)**。\n"
            "4. **停止。** 点击 **■ Stop**，确认。当前文件在 ~5 秒内中断。\n"
            "5. **关闭浏览器稍后回来。** 重新打开 UI 会自动调用 "
            "`/api/session/active` 并恢复所有内容。\n"
            "6. **重启。** 如果主机在编码中重启，worker 会回来并将运行中的"
            "作业标记为 `failed`。在下次扫描时手动重新选择它。"
        ),
    },
    {
        "id": "history",
        "title": "23. 历史页面",
        "body": (
            "Worker 触及的每个作业永久存在这里（直到您删除）。\n\n"
            "- **过滤** 按编码器、状态或日期范围。\n"
            "- **排序** 点击任意列标题。\n"
            "- **View** 打开 JobLogModal — 三个选项卡：\n"
            "  - **Details** — 源与目标 ffprobe 快照并排。\n"
            "  - **Events** — 此作业的过滤 JSONL 日志。\n"
            "  - **FFmpeg cmd** — 使用的确切命令。复制按钮。\n"
            "- **Export JSON** — 完整 v2 schema 快照。\n"
            "- **Import JSON** — 合并。按 `(original_path, completed_at)` "
            "去重。自动预导入快照。"
        ),
    },
    {
        "id": "backups",
        "title": "24. 数据库备份",
        "body": (
            "备份存在 `/data/backups/`。Dialect-aware：\n\n"
            "- **SQLite** — online-backup API。结果：`.db` 文件。\n"
            "- **Postgres** — `pg_dump -Fc -Z 6`。结果：`.dump` 文件。\n\n"
            "生命周期：\n\n"
            "- **自动启动快照。** 每次 API 启动。\n"
            "- **手动快照。** 永不自动修剪。\n"
            "- **预恢复**和**预导入**快照自动。\n\n"
            "**活动编码期间恢复拒绝运行**（409）。跨方言恢复被拒绝（400）。"
        ),
    },
    {
        "id": "logs_retention",
        "title": "25. 日志和保留",
        "body": (
            "两个日志表面：\n\n"
            "- **容器日志** — `docker compose logs`。10MB × 5 文件轮转。\n"
            "- **JSONL 会话日志** — `/data/logs/session_<id>.jsonl`。\n\n"
            "**保留控制**（Settings → Log Management）：\n\n"
            "- `log_retention_days` — 0 = 永远。\n"
            "- `clean_logs_on_startup` — 启用自动修剪。"
        ),
    },
    {
        "id": "appearance",
        "title": "26. 外观",
        "body": (
            "Settings → Appearance：\n\n"
            "- **Theme** — `dark` / `light` / `auto`。\n"
            "- **Accent colour** — 颜色选择器。\n"
            "- **Brand name** — 标题。\n\n"
            "更改实时应用，无需重新加载。"
        ),
    },
    {
        "id": "testing",
        "title": "27. 测试",
        "body": (
            "从仓库根目录使用主机 Python：\n\n"
            "```\n"
            "pip install -r requirements-dev.txt\n"
            "pytest -v tests/\n"
            "```\n\n"
            "`tests/conftest.py` 中的 fixtures 强制 `DB_BACKEND=sqlite` 并"
            "使用 monkey-patched `DB_PATH`/`LOGS_DIR`。还提供 `fake_ffmpeg` "
            "和 `fake_ffprobe`。\n\n"
            "**套件布局（v3.4.1 — 140 个测试）：** 参阅主文档获取完整文件"
            "列表。"
        ),
    },
    {
        "id": "useful_commands",
        "title": "28. 有用的命令和维护",
        "body": (
            "```\n"
            "# 实时日志\n"
            "docker compose logs -f reencoder-api\n"
            "docker compose logs -f reencoder-worker\n"
            "\n"
            "# 仅重启 worker\n"
            "docker compose restart reencoder-worker\n"
            "\n"
            "# 健康检查\n"
            "curl -s http://localhost:4246/api/health | jq\n"
            "\n"
            "# 当前活动的 DB 后端\n"
            "curl -s http://localhost:4246/api/db/state | python3 -m json.tool\n"
            "\n"
            "# Postgres shell\n"
            "docker compose exec postgres psql -U reencoder -d reencoder\n"
            "\n"
            "# Force-reset（解除僵尸会话）\n"
            "curl -s -X POST http://localhost:4246/api/encode/force-reset \\\n"
            "  -H 'Content-Type: application/json' -d '{}'\n"
            "\n"
            "# 手动 DB 快照\n"
            "curl -s -X POST http://localhost:4246/api/db/backup \\\n"
            "  -H 'Content-Type: application/json' -d '{\"label\":\"pre-update\"}'\n"
            "\n"
            "# 清理旧 JSONL 日志\n"
            "docker compose exec reencoder-api find /data/logs \\\n"
            "  -name 'session_*.jsonl' -mtime +30 -delete\n"
            "\n"
            "# 验证 VAAPI\n"
            "docker compose exec reencoder-worker ffmpeg -hide_banner -hwaccels\n"
            "docker compose exec reencoder-worker vainfo 2>&1 | head -20\n"
            "\n"
            "# 从头重建\n"
            "docker compose down\n"
            "docker compose build --no-cache && docker compose up -d\n"
            "\n"
            "# 危险：完全重置（保留 config.json）\n"
            "docker compose down\n"
            "sudo rm -rf data/postgres data/reencoder.db data/logs data/backups\n"
            "docker compose build && docker compose up -d\n"
            "```"
        ),
    },
    {
        "id": "troubleshooting",
        "title": "29. 故障排除",
        "body": (
            "**Encode 按钮没有反应，日志显示 `409 Conflict`。** 您在 ≤v3.3 "
            "对 Postgres（B-018）。升级到 v3.4+。临时解决：`POST "
            "/api/encode/force-reset`。\n\n"
            "**Light mode — 选中的行不可见。** ≤v3.3 问题（B-019）。升级"
            "到 v3.4+。\n\n"
            "**GPU 编码失败，`Unrecognized option 'vaapi_device'` 或 "
            "`'rc_mode'`。** ≤v3.4 + ffmpeg 7（B-020/B-021）。升级到 "
            "v3.4.1+ 并重建 worker。\n\n"
            "**GPU 编码失败，`Device creation failed: -12. Cannot allocate "
            "memory`。** ≤v3.4（B-022）。升级到 v3.4.1+。用 `docker compose "
            "exec reencoder-worker vainfo` 验证。\n\n"
            "**API 因 `password authentication failed for user "
            "\"reencoder\"` 崩溃循环。** 首次启动后更改了 "
            "`POSTGRES_PASSWORD`；卷仍有原密码。擦除 `data/postgres/`（丢失"
            "历史 — 先备份）或在容器内 `ALTER USER`。\n\n"
            "**`database is locked` 错误（仅 SQLite）。** 确保只有一个 "
            "worker 在运行。\n\n"
            "**重建后历史消失。** API 记录 `WARNING: DB file exists but "
            "has no history rows`。Settings → Database Backups → 恢复 "
            "`startup` 快照。\n\n"
            "**编码卡在 `Computing hash...`。** 源文件在慢速文件系统上。"
            "设置 `full_hash=false`。"
        ),
    },
    {
        "id": "credits",
        "title": "30. 致谢和参考",
        "body": (
            "**Transcode Talker** 的名字是对 *Decode Talker* 的致敬 — "
            "游戏王中的一个 Cyberse Link Monster。像它的同名怪一样，目标是"
            "将更大的东西链接到更精简、更高效的形式。\n\n"
            "基于：\n\n"
            "- **FFmpeg** + libx265 + libva + Mesa 驱动\n"
            "- **FastAPI** + **Uvicorn** + **Pydantic** + **SQLAlchemy 2.x**\n"
            "- **React 18** 通过 unpkg CDN + `@babel/standalone`\n"
            "- **Postgres 16-alpine**（默认）或 **SQLite WAL**（遗留）\n"
            "- **Docker** + **Docker Compose**\n"
            "- **pytest** 用于 140 测试回归套件\n\n"
            "维护者：Rafael Mello。"
        ),
    },
]
_JA = [
    {
        "id": "intro",
        "title": "1. Transcode Talker とは？",
        "body": (
            "**Transcode Talker** はセルフホスト型のバッチビデオ再エンコーダー"
            "です。設定したフォルダーをスキャンし、FFmpeg（CPU 上の libx265、"
            "または GPU パイプライン — VAAPI/QSV/NVENC）を使用してどのファイル"
            "を再エンコードするか選択でき、**結果が実際に小さくなった場合のみ**"
            "オリジナルを小さい HEVC バージョンで置き換えます。再エンコードした"
            "ファイルが大きくなった場合、破棄されジョブは `skipped` としてマー"
            "クされます。\n\n"
            "2 つの Docker コンテナとして構築されています — **API + UI** と "
            "**worker** — これらはデータベース（v3.4 以降デフォルトで Postgres、"
            "レガシーとして SQLite WAL）と JSONL ログファイル経由で状態を共有"
            "します。この分離は意図的です：エンコードは何時間も実行される可能性"
            "があり、設計はブラウザが閉じても、API が再起動しても、worker が"
            "再起動しても、エンコードが続行されることを保証します。エンコード中"
            "に kill された worker のみが現在のファイルを失います（次の worker "
            "起動時に `failed` として復旧されます）。\n\n"
            "目標はシンプル：すべてのオーディオトラック、字幕、添付ファイル、"
            "同じ再生忠実度（CRF — Constant Rate Factor で制御）を保ちながら、"
            "メディアライブラリが占めるディスク容量を削減することです。"
        ),
    },
    {
        "id": "architecture",
        "title": "2. アーキテクチャ概要",
        "body": (
            "プライベートな bridge ネットワーク上の 2 つの Docker コンテナと"
            "オプションのデータベースコンテナ：\n\n"
            "- **reencoder-api**（ポート 4246 の FastAPI）— React UI、HTTP "
            "API、WebSocket イベントストリームを提供します。スキーマを所有し、"
            "データベースに読み書きします。FFmpeg を **spawn しません**。\n"
            "- **reencoder-worker**（Python ループ）— `worker_poll_interval_s` "
            "秒ごとにデータベースをポーリングして queued ジョブのある "
            "`running` セッションを探し、FFmpeg を一度に 1 ファイル実行します。"
            "データベースのジョブ進捗を更新し、JSONL ログにイベントを追加し"
            "ます。\n"
            "- **postgres**（v3.4 以降デフォルト；オプション）— Postgres "
            "16-alpine、データは `data/postgres/` に永続化されます。SQLite "
            "は `DB_BACKEND=sqlite` で引き続きサポートされます。\n\n"
            "なぜ 1 つではなく 2 つのプロセスなのか？3 つの理由：\n\n"
            "1. **回復力。** FastAPI の再起動はエンコードを kill しません。\n"
            "2. **リソース分離。** Worker は docker-compose で専用 CPU/メモリ"
            "制限を取得します（デフォルト 8 CPU、8G RAM）。\n"
            "3. **関心の分離。** API はリクエスト/レスポンス + websocket；"
            "worker は長時間実行されるサブプロセスマネージャーです。\n\n"
            "**API と worker の間に HTTP はありません** — 共有データベース"
            "（Postgres または SQLite WAL）と `/data/logs/` 配下の JSONL イベ"
            "ントファイル経由でのみ通信します。これは意図的です：データベース"
            "が唯一の真実の源です。"
        ),
    },
    {
        "id": "components_diagram",
        "title": "3. コンポーネント図",
        "body": (
            "```\n"
            "                 ┌─────────────────────┐\n"
            "                 │ ブラウザ (React UI) │\n"
            "                 └─────────┬───────────┘\n"
            "                           │ HTTP + WebSocket\n"
            "                           ▼\n"
            "                 ┌─────────────────────┐\n"
            "                 │   reencoder-api     │  FastAPI :4246\n"
            "                 └────┬────────────┬───┘\n"
            "                      ▼            ▼\n"
            "             ┌─────────────┐  ┌──────────────┐\n"
            "             │ データベース│  │  /data/logs/ │\n"
            "             │ (Postgres   │◄─┤  *.jsonl     │\n"
            "             │  or SQLite) │  └──────────────┘\n"
            "             └──────┬──────┘          ▲\n"
            "                    ▼                 │\n"
            "             ┌─────────────────┐      │\n"
            "             │ reencoder-worker│──────┘  Python ポーリングループ\n"
            "             │  (Python loop)  │         FFmpeg を呼ぶ\n"
            "             └────────┬────────┘\n"
            "                      ▼\n"
            "             ┌────────────────────────┐\n"
            "             │  FFmpeg + /dev/dri     │  GPU VAAPI\n"
            "             │  + /mnt/media          │  ソースファイル\n"
            "             │  + /mnt/hdd            │  エンコード temp 領域\n"
            "             └────────────────────────┘\n"
            "```\n\n"
            "すべての永続的な状態は 3 つの場所にあります：\n\n"
            "- **データベース** — `sessions`、`jobs`、`scan_results` テーブル。\n"
            "- **JSONL イベントログファイル** — セッションごとに 1 つの "
            "append-only ファイル。\n"
            "- **設定** (`/data/config.json`) — UI で編集可能なすべての設定。"
        ),
    },
    {
        "id": "flow_scan_encode",
        "title": "4. エンドツーエンドフロー：スキャン → 選択 → エンコード",
        "body": (
            "```\n"
            "ユーザー → UI:       POST /api/scan\n"
            "UI → API:            scan_folders を歩き、ScannedFile リスト返却\n"
            "API → DB:            scan_results 行を新しいスナップショットで置換\n"
            "API → UI:            {files: [...]}\n"
            "\n"
            "ユーザー → UI:       ファイル選択、▶ Encode クリック\n"
            "UI → API:            POST /api/encode/start {paths}\n"
            "API → DB:            アクティブセッションが無いか確認\n"
            "                     (dialect-aware ロック: SQLite は\n"
            "                     BEGIN IMMEDIATE、Postgres は\n"
            "                     pg_advisory_xact_lock — B-018 参照)\n"
            "API → DB:            INSERT session(running) + N jobs(queued)\n"
            "API → UI:            {ok, session_id}\n"
            "\n"
            "Worker ループ (worker_poll_interval_s ごと、デフォルト 2s):\n"
            "  Worker → DB:       SELECT アクティブセッション\n"
            "  Worker → DB:       SELECT 次の queued ジョブ\n"
            "  Worker → DB:       UPDATE job status=encoding\n"
            "  Worker → FFmpeg:   build_cmd(...) で spawn\n"
            "  FFmpeg 実行中 0.5s ごとにループ:\n"
            "    Worker → DB:     is_session_interrupted? (停止チェック)\n"
            "    FFmpeg → stderr: 進捗 key=value\n"
            "    Worker → DB:     update_job_progress (2s ごとにスロットル)\n"
            "    Worker → JSONL:  progress イベントを append\n"
            "  FFmpeg 終了時:\n"
            "    Worker → ffprobe: verify_file (codec_name)\n"
            "    Worker → fs:     サイズ比較; encoded >= original なら skip\n"
            "    Worker → fs:     shutil.move HDD_temp → 元パス\n"
            "    Worker → DB:     UPDATE job status=completed\n"
            "```\n\n"
            "**API イベントブロードキャスター**（バックグラウンドタスク）は "
            "1 秒ごとに各セッションの JSONL ファイルを tail し、接続された"
            "すべての WebSocket クライアントに新しい行をプッシュします。"
        ),
    },
    {
        "id": "flow_stop",
        "title": "5. エンドツーエンドフロー：停止",
        "body": (
            "```\n"
            "ユーザー → UI:       ■ Stop クリック、確認\n"
            "UI → API:            POST /api/encode/stop\n"
            "API → DB:            UPDATE session status=interrupted\n"
            "API → DB:            UPDATE jobs (queued, encoding) → interrupted\n"
            "\n"
            "Worker (次の stop_check_interval_s tick、デフォルト 0.5s):\n"
            "  Worker → DB:       is_session_interrupted? → True\n"
            "  Worker → FFmpeg:   SIGTERM\n"
            "  最大 5 秒待機:\n"
            "    まだ実行中なら: SIGKILL\n"
            "  Worker → fs:       _cleanup(hdd_encoded)\n"
            "```\n\n"
            "停止は**デフォルトで graceful** です：SIGTERM は FFmpeg に最大 "
            "5 秒間、mux trailer を書き終えてクリーンに終了する時間を与えます。"
            "応答しない場合のみ、worker は SIGKILL にエスカレートします。"
        ),
    },
    {
        "id": "flow_recovery",
        "title": "6. エンドツーエンドフロー：クラッシュ復旧",
        "body": (
            "Worker コンテナが起動すると、ポーリングループに入る前に "
            "`recover_stale_jobs()` を実行します。ステータスが `encoding` の"
            "ジョブはすべて `failed` としてマークされ、`error_msg='Worker "
            "crashed or restarted'` が設定されます。\n\n"
            "**v3.4 は深層防御として `/api/encode/force-reset` も追加しました**："
            "実際の worker なしでセッションが `running` のままになった場合、"
            "ユーザーはこのエンドポイントを呼び出すか（または UI が動かない "
            "409 で表示する自動 `confirm()` を受け入れて）、すべての "
            "`running` セッションを `interrupted` としてマークできます。"
        ),
    },
    {
        "id": "flow_websocket",
        "title": "7. エンドツーエンドフロー：WebSocket 同期と再接続",
        "body": (
            "```\n"
            "UI:                  ws://host:4246/ws に接続\n"
            "API:                 accept、_ws_clients セットに追加\n"
            "UI:                  GET /api/session/active\n"
            "API → DB:            アクティブまたは最新のセッション取得\n"
            "API → UI:            {session, jobs, events}\n"
            "\n"
            "API バックグラウンドループ (毎 1s):\n"
            "  API → JSONL:       新しい行を tail\n"
            "  API → 全 WS:       新しいイベントをブロードキャスト\n"
            "\n"
            "WebSocket close 時:\n"
            "  UI:                指数バックオフで待機 (1s, 2s, 4s, 8s, 最大 30s)\n"
            "  UI:                再接続、上から繰り返し\n"
            "```\n\n"
            "`progress` イベントは応答性のためにライブカウンターのみを更新"
            "します。構造的なイベントは完全な `syncFromServer()` をトリガー"
            "します。"
        ),
    },
    {
        "id": "directory_structure",
        "title": "8. ディレクトリとコンテナ構造",
        "body": (
            "**リポジトリのレイアウト：**\n\n"
            "```\n"
            "reencoder-v3/\n"
            "├── docker-compose.yml\n"
            "├── .env.example\n"
            "├── data/                         # /data にマウントされる永続ボリューム\n"
            "│   ├── config.json\n"
            "│   ├── reencoder.db              # SQLite のみ\n"
            "│   ├── postgres/                 # Postgres データボリューム\n"
            "│   ├── backups/                  # 自動+手動スナップショット\n"
            "│   └── logs/session_<id>.jsonl\n"
            "├── reencoder-api/\n"
            "│   ├── app/main.py, database.py, db_engine.py, db_backup.py,\n"
            "│   │   config.py, models.py, scanner.py, help_content.py\n"
            "│   └── static/index.html\n"
            "├── reencoder-worker/\n"
            "│   ├── Dockerfile                # apt ffmpeg + mesa-va-drivers (v3.4.1)\n"
            "│   └── worker/main.py, encoder.py, database.py\n"
            "└── tests/                        # pytest スイート (v3.4.1 で 140 テスト)\n"
            "```\n\n"
            "**ホストファイルシステムの期待値：**\n\n"
            "| ホストパス | コンテナパス | 目的 |\n"
            "|---|---|---|\n"
            "| `./data` | `/data` | DB、設定、ログ、バックアップ |\n"
            "| `/mnt/animes`, `/mnt/media` | 同じ | メディアライブラリ |\n"
            "| `/mnt/hdd` | `/mnt/hdd` | エンコード temp 領域として使う遅いディスク |\n"
            "| `/dev/dri` | `/dev/dri` | GPU デバイス (worker のみ) |"
        ),
    },
    {
        "id": "data_model",
        "title": "9. データモデル（データベーススキーマ）",
        "body": (
            "3 つのテーブル、SQLite と Postgres で同じ形状。マイグレーション"
            "は冪等です。\n\n"
            "**`sessions`** — Start Encode クリックごとに 1 行。\n\n"
            "カラム：`id` (TEXT PK、8 文字に切り詰められた UUID)、`status` "
            "(pending/running/completed/interrupted)、`total_files`、"
            "`done_files`、`created_at`、`updated_at`。\n\n"
            "**`jobs`** — セッション内のファイルごとに 1 行。\n\n"
            "主要なカラム：`id`、`session_id`、`filename`、`original_path`、"
            "`original_size_mb`、`final_size_mb`、`space_saved_mb`、"
            "`original_hash`、`encoded_hash`、`crf_used`、`encoder_used`、"
            "`status` (queued/encoding/completed/failed/skipped/interrupted)、"
            "`current_frame`、`total_frames`、`pct`、`fps`、`speed`、`eta_s`、"
            "`error_msg`、`started_at`、`completed_at`、`source_metadata` "
            "(JSON、v3.3+)、`destination_metadata` (JSON、v3.3+)、"
            "`ffmpeg_cmd` (v3.3+)。\n\n"
            "**`scan_results`** — 単一行、新しいスキャンごとに置き換えられ"
            "ます。\n\n"
            "**JSONL イベントログ**：1 行に 1 つの JSON オブジェクト。"
            "イベントタイプ：`queue_start`、`queue_done`、`queue_stopped`、"
            "`file_start`、`file_done`、`step`、`progress`、`error`、"
            "`skipped`、`stopped`、`done`、`ffmpeg_cmd`。"
        ),
    },
    {
        "id": "config_env",
        "title": "10. 環境変数 (.env)",
        "body": (
            "`docker-compose.yml` で読み取られます。`.env` はオプションです — "
            "Postgres のデフォルトは安全ではありませんが、すぐに動作します。"
            "**ローカル以外のデプロイでは、最初の `docker compose up` の前に "
            "`.env.example` を `.env` にコピーし、強力なパスワードを設定して"
            "ください。**\n\n"
            "| 変数 | デフォルト | 効果 |\n"
            "|---|---|---|\n"
            "| `DB_BACKEND` | `postgres` (v3.4+) | `postgres` または `sqlite` |\n"
            "| `POSTGRES_HOST` | `postgres` | compose サービス名 |\n"
            "| `POSTGRES_PORT` | `5432` | |\n"
            "| `POSTGRES_USER` | `reencoder` | |\n"
            "| `POSTGRES_PASSWORD` | `reencoder` | **本番環境では変更すること** |\n"
            "| `POSTGRES_DB` | `reencoder` | |\n"
            "| `TZ` | `America/New_York` | タイムゾーン |\n"
            "| `BASIC_AUTH_USER`, `BASIC_AUTH_PASS` | 空 | HTTP Basic 認証 |\n\n"
            "**Postgres パスワードに関するリマインダー：** Postgres はデータ"
            "ボリュームが空のときのみ `POSTGRES_PASSWORD` を適用します。"
            "稼働中のデプロイで変更する場合は、`data/postgres/` を削除する"
            "（履歴を失う — 先にバックアップ）か、コンテナ内で "
            "`ALTER USER reencoder WITH PASSWORD '<new>'` を実行する必要が"
            "あります。"
        ),
    },
    {
        "id": "config_json",
        "title": "11. 設定フィールド (config.json)",
        "body": (
            "UI で編集可能なすべての設定は `/data/config.json` にあり、"
            "`app/models.py:Config` の Pydantic フィールドと 1 対 1 で対応"
            "しています。\n\n"
            "**スキャンと除外：**\n\n"
            "- `scan_folders: list[{path, threshold_mb}]` — 歩くフォルダー。\n"
            "- `exclude_folders: list[str]` — 大文字小文字を区別しないプレ"
            "フィックスマッチ。\n"
            "- `extensions: list[str]` — 考慮される拡張子。デフォルト："
            "`.mkv .mp4 .avi .mov`。\n\n"
            "**必須エンコーダーパラメーター：**\n\n"
            "- `encoder: cpu | vaapi | qsv | nvenc`\n"
            "- `crf: int` (1..51) — **低いほど = ファイルが大きく、品質が"
            "高い。** HEVC の典型は 23–28。26 が良いデフォルトです。\n"
            "- `preset: ultrafast..slower`\n"
            "- `ffmpeg_threads: int`\n\n"
            "**パスとバイナリ：**\n\n"
            "- `hdd_temp_path: str` — 実行中にエンコード出力が存在する場所。\n"
            "- `ffmpeg_path`、`ffprobe_path`\n"
            "- `vaapi_device_path: str` — デフォルト `/dev/dri/renderD128`。\n\n"
            "**動作チューニング：**\n\n"
            "- `full_hash: bool` — true ならファイル全体をハッシュ。\n"
            "- `skip_hevc_below_kbps: int` — ソースが既にこのしきい値未満の "
            "HEVC ならスキップ。\n"
            "- `stall_timeout_s: int` (デフォルト 60)。\n"
            "- `worker_poll_interval_s: float` (デフォルト 2.0)。\n"
            "- `stop_check_interval_s: float` (デフォルト 0.5)。\n\n"
            "**ログと外観：**\n\n"
            "- `log_retention_days: int` (デフォルト 30、0 = 永久)。\n"
            "- `clean_logs_on_startup: bool`。\n"
            "- `theme`、`accent_color`、`brand_name`。\n\n"
            "**Advanced encode** (`advanced_encode: dict`) — セクション 20 "
            "を参照。"
        ),
    },
    {
        "id": "api_reference",
        "title": "12. API リファレンス",
        "body": (
            "すべてのエンドポイントは JSON を返します。設定時は HTTP Basic "
            "認証。唯一の例外は `/api/health` で、Docker のヘルスチェックが"
            "動作するように常に匿名です。\n\n"
            "**Health とメタ：**\n"
            "- `GET /` — React UI を提供。\n"
            "- `GET /api/health` — `{ok, ts}`。\n"
            "- `WS  /ws` — イベントストリーム。\n\n"
            "**設定：** `GET/POST /api/config`、`/api/config/first-run`、"
            "`POST /api/config/exclude-folder`。\n\n"
            "**ブラウズ：** `GET /api/browse?path=...` — `/mnt` に制限。\n\n"
            "**スキャン：** `POST /api/scan`、`GET /api/scan/last`。\n\n"
            "**エンコード：**\n"
            "- `POST /api/encode/start` — アクティブセッションがある場合 "
            "`{error, active_session_id}` で 409。\n"
            "- `POST /api/encode/stop`\n"
            "- `POST /api/encode/force-reset` (v3.4) — ゾンビ `running` "
            "セッションをクリア。\n"
            "- `POST /api/encode/queue/add`\n"
            "- `GET  /api/encode/status`\n\n"
            "**セッションと履歴：**\n"
            "- `GET  /api/session/active`\n"
            "- `GET  /api/history?...` — ページ分割、フィルター、ソート。\n"
            "- `GET  /api/history/stats`、`/encoded-paths`、`/export`\n"
            "- `POST /api/history/import`\n"
            "- `DELETE /api/history/{id}`、bulk-delete\n\n"
            "**ジョブごとのログ：** `GET /api/jobs/{id}/logs`、`/logs/export`\n\n"
            "**DB 管理：** `GET /api/db/state`、`/backups`、`POST "
            "/api/db/backup`、`/restore`。\n\n"
            "**マニュアル：** `GET /api/help?lang=...`。"
        ),
    },
    {
        "id": "frontend",
        "title": "13. フロントエンド (static/index.html)",
        "body": (
            "UI 全体は約 2100 行の**単一の HTML ファイル**に存在します。"
            "unpkg CDN から React 18 と ReactDOM をロードし、ブラウザで JSX "
            "を変換するために `@babel/standalone` を追加します。バンドラー"
            "なし、`npm install` なし、TypeScript なし。\n\n"
            "**ページ：**\n\n"
            "- **Scan & Select** — スキャン実行、折りたたみ可能なツリーで"
            "フォルダーごとにファイルをグループ化、フィルター、"
            "add-to-exclusion、フォルダーごとの完了バッジ。\n"
            "- **Encode** — 現在のジョブのプログレスバー、キューリスト、"
            "ライブイベントログ。\n"
            "- **History** — カラムソートとフィルターバー付きのページ分割"
            "テーブル。Export/Import JSON。View は JobLogModal を開きます。\n"
            "- **Settings** — 折りたたみ可能なセクション、各フィールドに "
            "`ⓘ` ツールチップ。\n"
            "- **Encode Settings** — 4 つの必須パラメーター + 10 のトグル"
            "可能な高度なカード。\n"
            "- **Help** — このマニュアル、多言語。\n\n"
            "**重要なコンポーネント：**\n\n"
            "- `api` オブジェクト、`EncodeBar`、`JobLogModal`（3 タブ）、"
            "`DirBrowser`。\n"
            "- App レベルの WebSocket ハンドラーは指数バックオフ（1、2、4、"
            "8、最大 30 秒）で再接続。各 open で `syncFromServer()` を呼び"
            "出します。\n\n"
            "**テーマ：** `:root` の CSS 変数。v3.4 は `--selected-bg` と "
            "`--selected-fg` を追加しました。"
        ),
    },
    {
        "id": "backend_modules",
        "title": "14. バックエンドモジュール",
        "body": (
            "**`main.py`** — FastAPI エントリポイント。各 HTTP エンドポイ"
            "ント、`/ws` ハンドラー、1 秒イベントブロードキャスターバック"
            "グラウンドタスク、起動フック。\n\n"
            "**`database.py`** — データアクセスレイヤー。v3.3 以降、"
            "SQLAlchemy 2.x Core の薄いラッパーで、`?` プレースホルダーを"
            "名前付きバインドに変換します。Postgres では `RETURNING id`、"
            "SQLite では `lastrowid`。\n\n"
            "**`db_engine.py`** — Engine ファクトリ。`Table` オブジェクト"
            "でテーブルを定義、SQLite では PRAGMA WAL+NORMAL を設定。\n\n"
            "**`db_backend.py`** — `DB_BACKEND` に基づいてどのバックエンド"
            "を使うか決定。\n\n"
            "**`db_backup.py`** — スナップショットとリストア。SQLite は "
            "online-backup API、Postgres は `pg_dump -Fc -Z 6` と "
            "`pg_restore --clean --if-exists`。\n\n"
            "**`config.py`** — `config.json` のロード/保存、デフォルトとの"
            "マージ。\n\n"
            "**`models.py`** — Pydantic モデル。`Config` は `extra='allow'`。\n\n"
            "**`scanner.py`** — ファイルシステムウォーク。`os.walk` 中に"
            "除外された dir を剪定。\n\n"
            "**`worker/main.py`** — Worker ループ。SIGTERM/SIGINT ハンド"
            "ラー。起動時に `recover_stale_jobs()` が実行されます（v3.4："
            "Postgres のコールドスタートに耐えるためにリトライ × 10 × 2s）。"
            "`/data/.worker_heartbeat` のハートビート。\n\n"
            "**`worker/encoder.py`** — FFmpeg パイプライン。`file_hash()`、"
            "`get_total_frames()`、`_advanced_args()`、`build_cmd()`、"
            "`encode_file()`。"
        ),
    },
    {
        "id": "ffmpeg_basics",
        "title": "15. FFmpeg の基本 — 必須パラメーター",
        "body": (
            "これら 4 つのフィールドはエンコーダーに関係なく常に適用されます。"
            "すべての高度なトグルをオフにすると、エンコードは v3.1 とまったく"
            "同じように動作します。\n\n"
            "### `encoder`\n\n"
            "HEVC ビデオを生成するために使用されるパイプライン：\n\n"
            "- `cpu` — ソフトウェアエンコーダー `libx265`。**最も互換性が"
            "高い。** 最も遅いが、同じ CRF で最小のファイルを生成します。\n"
            "- `vaapi` — VAAPI 経由の AMD/Intel GPU。高速。同じ CRF での"
            "品質は libx265 より低いですが、圧縮は依然として良好です。\n"
            "- `qsv` — Intel Quick Sync Video。非常に高速。\n"
            "- `nvenc` — NVIDIA GPU。非常に高速。\n\n"
            "### `crf` — Constant Rate Factor\n\n"
            "1 から 51 の整数（GPU エンコーダーでは `-qp` として使用）。"
            "**低いほど = ファイルが大きく、品質が高い。**\n\n"
            "- 18 — ほとんどのコンテンツで視覚的にロスレス。\n"
            "- 23 — 高品質。\n"
            "- 26 — **Transcode Talker のデフォルト**。\n"
            "- 28 — 視覚的に圧縮されているがまだ視聴可能。\n"
            "- 32+ — 強い圧縮、目に見えるアーティファクト。\n\n"
            "CRF は**準対数的**：+6 ごとにビットレートが倍になります。\n\n"
            "### `preset`\n\n"
            "x265 の速度と効率のトレードオフ：`ultrafast`..`slower`。"
            "`medium` から `slow` に上げると、同じ CRF で通常 5–10% ビット"
            "レートを節約しますが、エンコード時間は ~2× かかります。\n\n"
            "### `ffmpeg_threads`\n\n"
            "`libx265` がスポーンするスレッド数。デフォルト 4。CPU エンコー"
            "ダーにのみ影響します。"
        ),
    },
    {
        "id": "ffmpeg_cpu",
        "title": "16. FFmpeg エンコーダー — `cpu` (libx265)",
        "body": (
            "コマンドの形状（デフォルト、高度なトグルなし）：\n\n"
            "```\n"
            "ffmpeg -y \\\n"
            "  -progress pipe:2 -nostats \\\n"
            "  -i <source> \\\n"
            "  -map 0:V -map 0:a? -map 0:s? -map 0:t? \\\n"
            "  -c:v libx265 -crf <CRF> -preset <preset> -threads <N> \\\n"
            "  -c:a copy -c:s copy \\\n"
            "  -max_muxing_queue_size 1024 \\\n"
            "  <hdd_temp_path>/ENCODED_<stem><ext>\n"
            "```\n\n"
            "各フラグの理由：\n\n"
            "- `-y` — プロンプトなしで上書き。\n"
            "- `-progress pipe:2 -nostats` — マシン読み取り可能な進捗。\n"
            "- `-map 0:V/a?/s?/t?` — すべてのストリーム（ビデオ、オーディオ、"
            "字幕、添付ファイル）。\n"
            "- `-c:a copy` — オーディオはビットパーフェクトにコピー。\n"
            "- `-c:s copy` — 字幕は逐語的にコピー。\n"
            "- `-max_muxing_queue_size 1024` — muxer のバッファ枯渇を防ぐ。"
        ),
    },
    {
        "id": "ffmpeg_vaapi",
        "title": "17. FFmpeg エンコーダー — `vaapi` (AMD/Intel GPU)",
        "body": (
            "v3.4.1 以降の標準コマンド（レガシーな `-vaapi_device` と "
            "`-rc_mode` は ffmpeg 7 が拒否するため削除されました — "
            "B-020/B-021 参照）：\n\n"
            "```\n"
            "ffmpeg -y \\\n"
            "  -init_hw_device vaapi=va:/dev/dri/renderD128 \\\n"
            "  -filter_hw_device va \\\n"
            "  -progress pipe:2 -nostats \\\n"
            "  -i <source> \\\n"
            "  -map 0:V -map 0:a? -map 0:s? -map 0:t? \\\n"
            "  -vf format=nv12,hwupload \\\n"
            "  -c:v hevc_vaapi -qp <CRF> \\\n"
            "  -c:a copy -c:s copy \\\n"
            "  ...\n"
            "```\n\n"
            "詳細：\n\n"
            "- `-init_hw_device vaapi=va:<dev>` — `va` という名前のハード"
            "ウェアデバイスを作成。\n"
            "- `-filter_hw_device va` — filter graph をデバイスにバインド。\n"
            "- `-vf format=nv12,hwupload` — NV12 に変換して GPU にアップロー"
            "ド。\n"
            "- `-c:v hevc_vaapi -qp <CRF>` — 自動 CQP モードの VAAPI HEVC "
            "エンコーダー。\n\n"
            "**コンテナ内の要件**（v3.4.1+ はすぐに使えます）：\n\n"
            "- `apt-get install ffmpeg vainfo libva-drm2 libva2 "
            "mesa-va-drivers`。\n"
            "- `docker-compose.yml` で `/dev/dri` がマップされている。\n"
            "- ホストに動作する Mesa/AMD または Intel ドライバー。\n\n"
            "**検証：** `docker compose exec reencoder-worker vainfo` は "
            "`HEVCMain` のようなプロファイルをリストするはずです。"
        ),
    },
    {
        "id": "ffmpeg_qsv",
        "title": "18. FFmpeg エンコーダー — `qsv` (Intel Quick Sync)",
        "body": (
            "```\n"
            "ffmpeg -y \\\n"
            "  -init_hw_device qsv=qs:/dev/dri/renderD128 \\\n"
            "  -filter_hw_device qs \\\n"
            "  -hwaccel qsv -hwaccel_output_format qsv \\\n"
            "  -i <source> \\\n"
            "  -map 0:V -map 0:a? -map 0:s? -map 0:t? \\\n"
            "  -c:v hevc_qsv -global_quality <CRF> -preset <preset> \\\n"
            "  ...\n"
            "```\n\n"
            "- `-hwaccel qsv -hwaccel_output_format qsv` — デコードしてエンド"
            "ツーエンドで GPU サーフェスのまま。\n"
            "- `-global_quality <CRF>` — QSV の品質ノブ。\n\n"
            "**要件：** Intel iGPU + `intel-media-va-driver` + QSV 対応 "
            "FFmpeg ビルド。Debian デフォルトの `ffmpeg` パッケージは QSV を"
            "**含みません** — `jellyfin-ffmpeg` を使用してください。"
        ),
    },
    {
        "id": "ffmpeg_nvenc",
        "title": "19. FFmpeg エンコーダー — `nvenc` (NVIDIA GPU)",
        "body": (
            "```\n"
            "ffmpeg -y \\\n"
            "  -i <source> \\\n"
            "  -map 0:V -map 0:a? -map 0:s? -map 0:t? \\\n"
            "  -c:v hevc_nvenc -rc constqp -qp <CRF> -preset <preset> \\\n"
            "  ...\n"
            "```\n\n"
            "- `-c:v hevc_nvenc` — NVIDIA HEVC エンコーダー。\n"
            "- `-rc constqp -qp <CRF>` — 定常 QP モード。\n"
            "- `-preset` — `p1`..`p7`。\n\n"
            "**要件：** NVIDIA GPU + ホストドライバー + "
            "`nvidia-container-toolkit` + CUDA 対応 FFmpeg。Debian デフォル"
            "トの `ffmpeg` パッケージは NVENC を**含みません** — "
            "`jellyfin-ffmpeg` または BtbN のプリビルトバイナリを使用。"
        ),
    },
    {
        "id": "ffmpeg_advanced",
        "title": "20. 高度なエンコードトグル",
        "body": (
            "**Encode Settings** タブは `advanced_encode` に 10 のトグルを"
            "公開します。各トグルは `{enabled: bool, value: ...}` で、**デフォ"
            "ルトでオフ** です。すべてオフの場合、コマンドは v3.1 とバイト"
            "単位で同じです。\n\n"
            "### `bitrate`\n\n"
            "`-b:v <value>` とオプションで `-maxrate`/`-bufsize` を設定。\n\n"
            "### `tune`\n\n"
            "`-tune <value>` を追加。libx265 の許可値：`psnr`、`ssim`、"
            "`grain`、`zerolatency`、`fastdecode`、`animation`。\n\n"
            "### `profile`、`level`、`tier`\n\n"
            "- `-profile:v` — `main`、`main10`、`main12`...\n"
            "- `-level` — `4.1`、`5.0`、`5.1`...\n"
            "- `-tier`（CPU のみ）— `main` または `high`。\n\n"
            "### `pixel_format`（CPU のみ）\n\n"
            "10 ビット HEVC 用の `-pix_fmt yuv420p10le`。\n\n"
            "### `gop` (keyint)\n\n"
            "`-g <keyint>`。キーフレーム間の距離。x265 のデフォルトは 250。\n\n"
            "### `x265_params`（CPU のみ）\n\n"
            "生の x265 パラメーター文字列。\n\n"
            "### `audio`\n\n"
            "オーディオを copy から再エンコードに切り替え。`{codec, bitrate}`。\n\n"
            "### `video_filters`（CPU のみ）\n\n"
            "`-vf <filter_chain>`。例：`scale=-2:720`、`crop=...`、`yadif`。"
        ),
    },
    {
        "id": "first_run",
        "title": "21. 初回実行",
        "body": (
            "1. **デプロイ。** リポジトリのルートから：`docker compose build "
            "&& docker compose up -d`。\n"
            "2. **UI を開く** `http://<host>:4246` で。\n"
            "3. **Settings → Scan folders** — 少なくとも 1 つの `{path, "
            "threshold_mb}` 行を追加。\n"
            "4. **Settings → Encoder** — `cpu` から始める。最も互換性が高い。\n"
            "5. **Settings → CRF** — 強い理由がない限り 26 のまま。\n"
            "6. **Settings → HDD temp path** — 十分な容量のあるディスクに必要。\n"
            "7. **Save configuration**、次に **Scan & Select** → **⟳ Scan** "
            "→ ファイル選択 → **▶ Encode**。"
        ),
    },
    {
        "id": "running_an_encode",
        "title": "22. エンコードを実行する",
        "body": (
            "1. **Scan & Select** — **⟳ Scan** をクリック、フォルダーを展開"
            "してファイルにチェック。\n"
            "2. **エンコードを開始。** **▶ Encode** をクリック。\n"
            "3. **実行中に作業を追加。** エンコード中、ボタンは "
            "**+ Add to Queue (N)** に変わります。\n"
            "4. **停止。** **■ Stop** をクリック、確認。現在のファイルは "
            "~5 秒で中断されます。\n"
            "5. **ブラウザを閉じて後で戻る。** UI を再度開くと、"
            "`/api/session/active` 経由ですべてが復元されます。\n"
            "6. **再起動。** ホストがエンコード中に再起動すると、worker は"
            "戻ってきて in-flight ジョブを `failed` としてマークします。"
            "次のスキャンで手動で再選択します。"
        ),
    },
    {
        "id": "history",
        "title": "23. 履歴ページ",
        "body": (
            "Worker が触れたすべてのジョブは永久にここに存在します（削除する"
            "まで）。\n\n"
            "- **フィルター** エンコーダー、ステータス、または日付範囲で。\n"
            "- **ソート** 任意のカラムヘッダーをクリック。\n"
            "- **View** は JobLogModal を開く — 3 つのタブ：\n"
            "  - **Details** — ソースと宛先の ffprobe スナップショットを並べて"
            "表示。\n"
            "  - **Events** — このジョブ用にフィルターされた JSONL ログ。\n"
            "  - **FFmpeg cmd** — 使用された正確なコマンド。コピーボタン。\n"
            "- **Export JSON** — 完全な v2 スキーマスナップショット。\n"
            "- **Import JSON** — マージ。`(original_path, completed_at)` で"
            "重複除去。自動プリインポートスナップショット。"
        ),
    },
    {
        "id": "backups",
        "title": "24. データベースバックアップ",
        "body": (
            "バックアップは `/data/backups/` に存在します。Dialect-aware：\n\n"
            "- **SQLite** — online-backup API。結果：`.db` ファイル。\n"
            "- **Postgres** — `pg_dump -Fc -Z 6`。結果：`.dump` ファイル。\n\n"
            "ライフサイクル：\n\n"
            "- **自動起動スナップショット。** すべての API 起動時。\n"
            "- **手動スナップショット。** 自動的にプルーンされません。\n"
            "- **プリリストア**と**プリインポート**スナップショットは自動。\n\n"
            "**アクティブなエンコード中はリストアの実行が拒否されます**（409）。"
            "クロスダイアレクトリストアは 400 で拒否されます。"
        ),
    },
    {
        "id": "logs_retention",
        "title": "25. ログと保持",
        "body": (
            "2 つのログサーフェス：\n\n"
            "- **コンテナログ** — `docker compose logs`。10MB × 5 ファイル"
            "でローテーション。\n"
            "- **JSONL セッションログ** — `/data/logs/session_<id>.jsonl`。\n\n"
            "**保持コントロール**（Settings → Log Management）：\n\n"
            "- `log_retention_days` — 0 = 永久。\n"
            "- `clean_logs_on_startup` — 自動プルーンを有効化。"
        ),
    },
    {
        "id": "appearance",
        "title": "26. 外観",
        "body": (
            "Settings → Appearance：\n\n"
            "- **Theme** — `dark` / `light` / `auto`。\n"
            "- **Accent colour** — カラーピッカー。\n"
            "- **Brand name** — ヘッダータイトル。\n\n"
            "変更はリロードなしでライブに適用されます。"
        ),
    },
    {
        "id": "testing",
        "title": "27. テスト",
        "body": (
            "リポジトリのルートからホスト Python で実行：\n\n"
            "```\n"
            "pip install -r requirements-dev.txt\n"
            "pytest -v tests/\n"
            "```\n\n"
            "`tests/conftest.py` のフィクスチャは `DB_BACKEND=sqlite` を強制"
            "し、`DB_PATH`/`LOGS_DIR` をモンキーパッチして密閉的に実行します。"
            "また `fake_ffmpeg` と `fake_ffprobe` シムも提供します。\n\n"
            "**スイートレイアウト（v3.4.1 — 140 テスト）：** ファイル別の完全"
            "なリストはメインドキュメントを参照してください。"
        ),
    },
    {
        "id": "useful_commands",
        "title": "28. 便利なコマンドとメンテナンス",
        "body": (
            "```\n"
            "# ライブログ\n"
            "docker compose logs -f reencoder-api\n"
            "docker compose logs -f reencoder-worker\n"
            "\n"
            "# Worker のみ再起動\n"
            "docker compose restart reencoder-worker\n"
            "\n"
            "# ヘルスチェック\n"
            "curl -s http://localhost:4246/api/health | jq\n"
            "\n"
            "# 現在アクティブな DB バックエンド\n"
            "curl -s http://localhost:4246/api/db/state | python3 -m json.tool\n"
            "\n"
            "# Postgres シェル\n"
            "docker compose exec postgres psql -U reencoder -d reencoder\n"
            "\n"
            "# Force-reset (ゾンビセッションを解除)\n"
            "curl -s -X POST http://localhost:4246/api/encode/force-reset \\\n"
            "  -H 'Content-Type: application/json' -d '{}'\n"
            "\n"
            "# 手動 DB スナップショット\n"
            "curl -s -X POST http://localhost:4246/api/db/backup \\\n"
            "  -H 'Content-Type: application/json' -d '{\"label\":\"pre-update\"}'\n"
            "\n"
            "# 古い JSONL ログをクリーンアップ\n"
            "docker compose exec reencoder-api find /data/logs \\\n"
            "  -name 'session_*.jsonl' -mtime +30 -delete\n"
            "\n"
            "# VAAPI を検証\n"
            "docker compose exec reencoder-worker ffmpeg -hide_banner -hwaccels\n"
            "docker compose exec reencoder-worker vainfo 2>&1 | head -20\n"
            "\n"
            "# 一から再構築\n"
            "docker compose down\n"
            "docker compose build --no-cache && docker compose up -d\n"
            "\n"
            "# 危険: 完全リセット (config.json は保持)\n"
            "docker compose down\n"
            "sudo rm -rf data/postgres data/reencoder.db data/logs data/backups\n"
            "docker compose build && docker compose up -d\n"
            "```"
        ),
    },
    {
        "id": "troubleshooting",
        "title": "29. トラブルシューティング",
        "body": (
            "**Encode ボタンが何もしない、ログに `409 Conflict`。** Postgres "
            "に対して ≤v3.3 です（B-018）。v3.4+ にアップグレード。回避策："
            "`POST /api/encode/force-reset`。\n\n"
            "**Light モード — 選択された行が見えない。** ≤v3.3 の問題"
            "（B-019）。v3.4+ にアップグレード。\n\n"
            "**GPU エンコードが `Unrecognized option 'vaapi_device'` または "
            "`'rc_mode'` で失敗。** ≤v3.4 + ffmpeg 7（B-020/B-021）。"
            "v3.4.1+ にアップグレードして worker を再構築。\n\n"
            "**GPU エンコードが `Device creation failed: -12. Cannot "
            "allocate memory` で失敗。** ≤v3.4（B-022）。v3.4.1+ にアップグ"
            "レード。`docker compose exec reencoder-worker vainfo` で検証。\n\n"
            "**API が `password authentication failed for user "
            "\"reencoder\"` でクラッシュループ。** `POSTGRES_PASSWORD` が"
            "最初のブート後に変更されました；ボリュームには元のパスワードが"
            "残っています。`data/postgres/` を消去する（履歴を失う — 先に"
            "バックアップ）か、コンテナ内で `ALTER USER` を使用。\n\n"
            "**`database is locked` エラー（SQLite のみ）。** 1 つの worker "
            "のみが実行されていることを確認。\n\n"
            "**再構築後に履歴が消えた。** API が `WARNING: DB file exists "
            "but has no history rows` をログします。Settings → Database "
            "Backups → `startup` スナップショットを復元。\n\n"
            "**エンコードが `Computing hash...` で止まる。** ソースファイル"
            "が遅いファイルシステム（NFS/SMB）にあります。`full_hash=false` "
            "を設定。"
        ),
    },
    {
        "id": "credits",
        "title": "30. クレジットと参考文献",
        "body": (
            "**Transcode Talker** という名前は、遊戯王の Cyberse リンクモン"
            "スターである *Decode Talker* へのオマージュです。同名のカード"
            "のように、目標はより大きなものをよりスリムで効率的な形にリンク"
            "することです。\n\n"
            "構築基盤：\n\n"
            "- **FFmpeg** + libx265 + libva + Mesa ドライバー\n"
            "- **FastAPI** + **Uvicorn** + **Pydantic** + **SQLAlchemy 2.x**\n"
            "- **React 18** unpkg CDN 経由 + `@babel/standalone`\n"
            "- **Postgres 16-alpine**（デフォルト）または **SQLite WAL**"
            "（レガシー）\n"
            "- **Docker** + **Docker Compose**\n"
            "- **pytest** で 140 テストの回帰スイート\n\n"
            "メンテナー：Rafael Mello。"
        ),
    },
]


HELP_CONTENT: dict[str, list[dict]] = {
    "en":    _EN,
    "pt-BR": _PT_BR,
    "es":    _ES,
    "fr":    _FR,
    "zh-CN": _ZH_CN,
    "ja":    _JA,
}


def get_help(lang: str) -> dict:
    sections = HELP_CONTENT.get(lang) or HELP_CONTENT["en"]
    # Fallback to EN if a translation has not been filled in yet (defensive
    # — should not happen in v3.4.1, but keeps the endpoint robust).
    if not sections:
        sections = HELP_CONTENT["en"]
        lang = "en"
    return {
        "lang":      lang if lang in HELP_CONTENT else "en",
        "languages": list(HELP_CONTENT.keys()),
        "sections":  sections,
    }
