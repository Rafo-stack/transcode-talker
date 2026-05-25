FROM python:3.12-slim

# B-022: swapped johnvansickle's static ffmpeg for the Debian apt ffmpeg.
#   Reason: the static build from johnvansickle is CPU-only, it doesn't
#   include ``--enable-vaapi`` in their build script. Result: VAAPI encodes
#   would fail with "Device creation failed: -12" even with /dev/dri mapped
#   and libva installed, because the ffmpeg binary itself had no VAAPI
#   support compiled in.
#   The apt ffmpeg is built against Debian's own libva (zero mismatch).
#   mesa-va-drivers is the VA driver for AMD/Intel — that's what actually
#   responds when ffmpeg opens /dev/dri/renderD128 via VAAPI.
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    vainfo libva-drm2 libva2 mesa-va-drivers \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY worker/ ./worker/

CMD ["python", "-m", "worker.main"]
