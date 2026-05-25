FROM python:3.12-slim

# B-022: trocado o static build do johnvansickle pelo ffmpeg do apt-Debian.
#   Motivo: o static do johnvansickle é CPU-only — não tem ``--enable-vaapi``
#   no script de build deles. Resultado: encode VAAPI quebrava com
#   "Device creation failed: -12" mesmo com /dev/dri mapeado e libva
#   instalada, porque o binário do ffmpeg não tinha o suporte compilado.
#   apt ffmpeg é construído contra a libva do próprio Debian (zero mismatch).
#   mesa-va-drivers é o VA driver pro AMD/Intel — é o que efetivamente
#   responde quando o ffmpeg abre /dev/dri/renderD128 via VAAPI.
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    vainfo libva-drm2 libva2 mesa-va-drivers \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY worker/ ./worker/

CMD ["python", "-m", "worker.main"]
