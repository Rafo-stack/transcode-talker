FROM python:3.12-slim

# ffmpeg gives us ffprobe (needed by API for /api/browse if any path checks).
# postgresql-client provides pg_dump/pg_restore for M-029 backup endpoints.
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg postgresql-client \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/    ./app/
COPY static/ ./static/

EXPOSE 4246
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "4246"]
