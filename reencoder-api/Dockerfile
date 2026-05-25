# ──────────────────────────────────────────────────────────────
# Reencoder API — FastAPI on Python 3.12.
#
# IMPORTANT: the build context for this Dockerfile is the REPO ROOT
# (not ./reencoder-api/), because we need to COPY both the app source
# AND ./roadmap/ (used by the /api/roadmap endpoint) into the image.
#
# See docker-compose.yml / .github/workflows/release.yml for how the
# context is set.
# ──────────────────────────────────────────────────────────────

FROM python:3.12-slim

# System dependencies:
#   ffmpeg              — supplies ffprobe, used by some /api/browse path checks
#   postgresql-client   — supplies pg_dump / pg_restore for backup/restore endpoints
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg postgresql-client \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first so requirements changes invalidate the layer cache
# more aggressively than source changes.
COPY reencoder-api/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application source.
COPY reencoder-api/app/ ./app/

# Roadmap YAML files served by /api/roadmap. Baked into the image so
# production deployments don't need a separate volume mount.
# Dev (docker-compose.yml) overrides this with a read-only bind mount so
# you can edit roadmap content without rebuilding the image.
COPY roadmap/ ./roadmap/

EXPOSE 4246
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "4246"]
