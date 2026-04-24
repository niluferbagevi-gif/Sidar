# ═══════════════════════════════════════════════════════════════
# Sidar AI — Dockerfile
# Sürüm: 5.2.0  (GPU & CPU destekli çift mod)
#
#  CPU modu (varsayılan):
#    docker build -t sidar-ai .
#
#  GPU modu (NVIDIA CUDA 13.0 — RTX 30xx/40xx, Driver ≥595):
#    docker build \
#      --build-arg BASE_IMAGE=nvidia/cuda:13.0.0-runtime-ubuntu22.04 \
#      --build-arg GPU_ENABLED=true \
#      -t sidar-ai-gpu .
#
#  WSL2 + Docker GPU notu:
#    Windows tarafında NVIDIA Driver (≥595.x) kurulu olmalı.
#    WSL2 içinde: sudo apt-get install -y nvidia-container-toolkit
#                 sudo nvidia-ctk runtime configure --runtime=docker
# ═══════════════════════════════════════════════════════════════

# ── Build-time argümanlar ──────────────────────────────────────
# CPU-only: python:3.11-slim
# GPU:      nvidia/cuda:13.0.0-runtime-ubuntu22.04
ARG BASE_IMAGE=python:3.11-slim
ARG GPU_ENABLED=false
ARG INSTALL_DEV=false

FROM ${BASE_IMAGE}

# Meta veriler
LABEL maintainer="Sidar AI Project"
LABEL version="5.2.0"
LABEL description="Yazılım Mühendisi AI Asistanı - Docker İzolasyonu"

# Çevresel değişkenler
# GPU_ENABLED build-arg çalışma zamanında USE_GPU env değişkenine dönüşür
# MEMORY_ENCRYPTION_KEY: docker run -e MEMORY_ENCRYPTION_KEY=<fernet_key> ile iletilebilir
ARG MEMORY_ENCRYPTION_KEY=""
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=7860 \
    PIP_NO_CACHE_DIR=1 \
    UV_PYTHON=3.11 \
    UV_LINK_MODE=copy \
    VIRTUAL_ENV=/app/.venv \
    PYTHONPATH=/app \
    ACCESS_LEVEL=sandbox \
    USE_GPU=${GPU_ENABLED} \
    MEMORY_ENCRYPTION_KEY=${MEMORY_ENCRYPTION_KEY} \
    ENABLE_TRACING=false \
    OTEL_EXPORTER_ENDPOINT=http://localhost:4317 \
    REDIS_URL=redis://redis:6379/0

# Çalışma dizini
WORKDIR /app

# Sistem bağımlılıkları
# GPU base image'ında (nvidia/cuda) libcuda ve sürücü zaten mevcuttur.
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    git \
    build-essential \
    curl \
    wget \
    zstd \
    docker.io \
    portaudio19-dev \
    python3-pyaudio \
    alsa-utils \
    v4l-utils \
    ffmpeg \
    cargo \
    pkg-config \
    && rm -rf /var/lib/apt/lists/*

ENV UV_INDEX_STRATEGY=first-index \
    PATH="${VIRTUAL_ENV}/bin:$PATH"

# Bağımlılık Yönetimi — uv lock dosyasından deterministik kurulum
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
COPY pyproject.toml uv.lock README.md ./
RUN if [ "$INSTALL_DEV" = "true" ]; then \
      uv sync --frozen --no-install-project; \
    else \
      uv sync --frozen --no-dev --no-install-project; \
    fi

# Opsiyonel RAG embedding model pre-cache (offline/tekrarlı build hızlandırma)
# Örn: docker build --build-arg PRECACHE_RAG_MODEL=true -t sidar-ai .
ARG PRECACHE_RAG_MODEL=false
ARG RAG_EMBEDDING_MODEL=all-MiniLM-L6-v2
RUN if [ "$PRECACHE_RAG_MODEL" = "true" ]; then \
      python3 -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('${RAG_EMBEDDING_MODEL}')"; \
    else \
      echo "RAG model pre-cache atlandı"; \
    fi

# Uygulama kodlarını kopyala
COPY . .

# Proje paketini mevcut lock dosyasına göre ortama kur
RUN if [ "$INSTALL_DEV" = "true" ]; then \
      uv sync --frozen; \
    else \
      uv sync --frozen --no-dev; \
    fi

# Kalıcı veri dizinleri + güvenlik için non-root kullanıcı (katman optimizasyonu)
RUN useradd -m -u 10001 sidaruser && mkdir -p /app/logs /app/data /app/temp /app/sessions /app/chroma_db && chown -R sidaruser:sidaruser /app
USER sidaruser

# Web arayüzü portu
EXPOSE 7860

# Sağlık kontrolü — uygulama içi health endpoint'i kullanır.
# /status endpoint'i DB/Redis gibi iç bağımlılıklarını 200/503 ile raporlamalıdır.
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
  CMD curl -fsS http://localhost:7860/status > /dev/null || exit 1

# Varsayılan başlatma (CLI)
# Web için (ENTRYPOINT argümanı olarak): docker run ... --quick web --host 0.0.0.0 --port 7860
ENTRYPOINT ["/app/.venv/bin/python", "main.py"]
