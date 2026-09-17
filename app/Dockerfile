# Ignite Chat HTTP backend for Azure Container Apps
# Multi-stage Linux image WITHOUT pywebview / pythonnet
FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        ffmpeg \
        git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY requirements-server.txt .
RUN pip install --upgrade pip && pip install -r requirements-server.txt

FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    IGNITE_RUNTIME_MODE=server \
    IGNITE_API_HOST=0.0.0.0 \
    IGNITE_API_PORT=8000 \
    # Persist sessions / RAG under Azure Files mount by default
    IGNITE_DATA_DIR=/data

RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --shell /bin/bash ignite

WORKDIR /app

COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

COPY . /app

RUN mkdir -p /data/log /data/Databases \
    && chown -R ignite:ignite /app /data

USER ignite
EXPOSE 8080 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
  CMD python -c "import os, urllib.request; p = os.environ.get('PORT', os.environ.get('IGNITE_API_PORT', '8000')); urllib.request.urlopen(f'http://127.0.0.1:{p}/health')" || exit 1

CMD ["sh", "-c", "python -m uvicorn server.main:app --host 0.0.0.0 --port ${PORT:-${IGNITE_API_PORT:-8000}}"]
