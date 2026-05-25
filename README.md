# Transcode Talker

> Self-hosted HEVC re-encoding pipeline. Reclaim disk space from your media library, automatically.

[![License: MIT](https://img.shields.io/badge/License-MIT-teal.svg)](LICENSE)
[![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?logo=docker&logoColor=white)](https://docs.docker.com/compose/)
[![FastAPI](https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![React](https://img.shields.io/badge/React-18-61DAFB?logo=react&logoColor=black)](https://react.dev)

Transcode Talker scans your media library, queues oversized files, and re-encodes them to HEVC with hardware acceleration. Original files get replaced atomically. Every encode is recorded so you never re-process the same file twice.

---

## Quick start

```bash
mkdir reencoder && cd reencoder
curl -O https://raw.githubusercontent.com/Rafo-stack/transcode-talker/main/docker-compose.prod.yml
docker compose -f docker-compose.prod.yml up -d
```

Open `http://<host>:4246/` in your browser, point it at your media folders under **Settings → Scan folders**, and start encoding.

> Production compose pulls pre-built images from GitHub Container Registry. To build from source instead, clone the repo and use the regular `docker-compose.yml`.

---

## What it does

- **Walks your media folders** and finds files above a configurable size threshold
- **Skips files already in HEVC** so it never wastes a pass
- **Re-encodes with hardware acceleration**: VAAPI (AMD/Intel), QSV (Intel), NVENC (NVIDIA), or libx265 CPU fallback
- **Replaces originals atomically** once the encode succeeds and the hash is recorded
- **Persists everything** in PostgreSQL (or SQLite if you prefer), with full searchable history
- **Streams live progress** over WebSocket: current frame, fps, ETA, ffmpeg log
- **Survives restarts** via a heartbeat file, exponential-backoff reconnect, and a backup taken at startup

## Stack

Four Docker containers, one network, one published port:

| Service | Image | Purpose |
|---------|-------|---------|
| `reencoder-web` | nginx 1.27 + Vite SPA bundle | Serves the UI and reverse-proxies `/api/*` and `/ws` |
| `reencoder-api` | FastAPI on Python 3.12 | REST, WebSocket, SSE event bus |
| `reencoder-worker` | FFmpeg + Python 3.12 | Pulls jobs and runs the encoder |
| `postgres` | postgres:16-alpine | Metastore (sessions, jobs, history, scan results) |

Frontend: React 18 + TypeScript + Vite 6 + Tailwind 3 + TanStack Query + Zustand.

## Configuration

### Environment variables

Copy `.env.example` to `.env` and adjust before the first boot. The most important ones:

| Variable | Default | Purpose |
|----------|---------|---------|
| `POSTGRES_PASSWORD` | `reencoder` | **Change this before exposing the app.** Only applied on first volume init. |
| `DB_BACKEND` | `postgres` | Set to `sqlite` for single-user setups. |
| `TZ` | `America/New_York` | Container timezone. |
| `BASIC_AUTH_USER` / `BASIC_AUTH_PASS` | (empty) | Set both to enable HTTP Basic auth on every endpoint except `/api/health`. |

> **Postgres password rotation gotcha:** Postgres only writes `POSTGRES_PASSWORD` on the first boot of a fresh volume. To change it later, either wipe `./data/postgres/` (loses history, back up first) or run `ALTER USER reencoder WITH PASSWORD '<new>'` inside the container.

### Required host paths

Mount the folders you want to scan/encode into the worker (edit `docker-compose.prod.yml` to match your layout):

- `/mnt/media`, `/mnt/animes`, etc. — your media library
- `/mnt/hdd` — temp space for the encoder (a slower disk is fine)
- `/dev/dri` — optional, only required for VAAPI/QSV hardware acceleration

## Hardware acceleration

The worker auto-detects and uses the first available encoder, in this order:

1. **VAAPI** (AMD/Intel): mount `/dev/dri:/dev/dri` and the container will use it
2. **QSV** (Intel Quick Sync): same `/dev/dri` mount, different code path
3. **NVENC** (NVIDIA): requires the `nvidia` runtime
4. **libx265** (CPU): always available as fallback

You can also force a specific encoder under **Settings → Encoding**.

## Build from source

If you'd rather build locally instead of pulling images:

```bash
git clone https://github.com/Rafo-stack/transcode-talker.git
cd transcode-talker
docker compose build
docker compose up -d
docker compose ps
```

The first build takes about 30 seconds (Vite bundle + Python deps + nginx layer).

## Development

```bash
# Frontend (hot-reload at http://localhost:5173, proxies /api → :4246)
cd frontend
npm install
npm run dev

# Backend
cd reencoder-api
pip install -r requirements.txt
uvicorn app.main:app --reload --port 4246

# Run the test suite
pip install -r requirements-dev.txt
pytest -v tests/
```

The frontend dev server expects the API at `http://localhost:4246`. The Vite config rewrites `/api/*` and `/ws` to it automatically.

## License

[MIT](LICENSE). Use it, fork it, ship it.

## Acknowledgements

Built on top of [FFmpeg](https://ffmpeg.org/), [FastAPI](https://fastapi.tiangolo.com/), [React](https://react.dev/), and [PostgreSQL](https://www.postgresql.org/). Hardware encoders courtesy of AMD VAAPI, Intel QSV, and NVIDIA NVENC.
