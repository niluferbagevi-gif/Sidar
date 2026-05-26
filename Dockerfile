# syntax=docker/dockerfile:1.7

# ═══════════════════════════════════════════════════════════════
# Sidar AI — Dockerfile
# Sürüm: 5.2.0  (GPU & CPU destekli çift mod)
#
#  CPU modu (varsayılan):
#    docker build -t sidar:latest .
#
#  GPU modu (NVIDIA CUDA 13.0 — RTX 30xx/40xx, Driver ≥595):
#    docker build \
#      --build-arg BASE_IMAGE=nvidia/cuda:13.0.0-runtime-ubuntu22.04 \
#      --build-arg GPU_ENABLED=true \
#      -t sidar-gpu:latest .
#
#  WSL2 + Docker GPU notu:
#    Windows tarafında NVIDIA Driver (≥595.x) kurulu olmalı.
#    WSL2 içinde: sudo apt-get install -y nvidia-container-toolkit
#                 sudo nvidia-ctk runtime configure --runtime=docker
# ═══════════════════════════════════════════════════════════════

# ── Build-time argümanlar ──────────────────────────────────────
# GPU (varsayılan): nvidia/cuda:12.6.0-cudnn-runtime-ubuntu22.04
# CPU fallback:     python:${PYTHON_VERSION}-slim
ARG PYTHON_VERSION=3.11
ARG BASE_IMAGE=nvidia/cuda:12.6.0-cudnn-runtime-ubuntu22.04
ARG GPU_ENABLED=false

FROM ${BASE_IMAGE}

# FROM öncesi ARG değerini build katmanlarında da kullanmak için yeniden tanımla.
ARG PYTHON_VERSION=3.11

# Meta veriler
LABEL maintainer="Sidar AI Project"
LABEL version="5.3.0"
LABEL description="Yazılım Mühendisi AI Asistanı - Docker İzolasyonu"

# Çevresel değişkenler
# GPU_ENABLED build-arg çalışma zamanında USE_GPU env değişkenine dönüşür
# MEMORY_ENCRYPTION_KEY: docker run -e MEMORY_ENCRYPTION_KEY=<fernet_key> ile iletilebilir
ARG MEMORY_ENCRYPTION_KEY=""
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=7860 \
    PIP_NO_CACHE_DIR=1 \
    UV_PYTHON=${PYTHON_VERSION} \
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
    software-properties-common \
    && add-apt-repository ppa:deadsnakes/ppa \
    && apt-get update && apt-get install -y --no-install-recommends \
    python${PYTHON_VERSION} \
    python${PYTHON_VERSION}-venv \
    python${PYTHON_VERSION}-distutils \
    python3-pip \
    git \
    build-essential \
    curl \
    wget \
    zstd \
    # docker.io: docker-out-of-docker erişimi için (sock mount edildiğinde)
    docker.io \
    portaudio19-dev \
    python3-pyaudio \
    alsa-utils \
    v4l-utils \
    ffmpeg \
    cargo \
    pkg-config \
    shellcheck \
    && rm -rf /var/lib/apt/lists/*

RUN update-alternatives --install /usr/bin/python3 python3 /usr/bin/python${PYTHON_VERSION} 2

ENV UV_INDEX_STRATEGY=first-index \
    PATH="${VIRTUAL_ENV}/bin:$PATH"

# Bağımlılık Yönetimi — uv lock dosyasından deterministik kurulum
# Sandbox testleri `run_tests.sh` gibi betikleri doğrudan container içinde
# çalıştırdığı için uv binary'si imajda önceden bulunmalıdır.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
RUN uv --version && uvx --version
COPY pyproject.toml uv.lock README.md ./
RUN test -f uv.lock || (echo "uv.lock is required for deterministic builds" >&2; exit 1)
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --all-extras --extra dev --no-install-project
RUN uv run python -c "import shutil; assert shutil.which('pyright-langserver'), 'pyright-langserver missing'; assert shutil.which('pyright'), 'pyright missing'"

# Opsiyonel RAG embedding model pre-cache (offline/tekrarlı build hızlandırma)
# Örn: docker build --build-arg PRECACHE_RAG_MODEL=true -t sidar:latest .
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
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --all-extras --extra dev

# Kalıcı veri dizinleri + güvenlik için non-root kullanıcı (katman optimizasyonu)
RUN useradd -m -u 10001 sidaruser && mkdir -p /app/logs /app/data /app/temp /app/sessions /app/chroma_db && chown -R sidaruser:sidaruser /app
USER sidaruser

# Web arayüzü portu
EXPOSE 7860

# Sağlık kontrolü — uygulama içi health endpoint'i kullanır.
# /status endpoint'i DB/Redis gibi iç bağımlılıklarını 200/503 ile raporlamalıdır.
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
  CMD sh -c 'curl -fsS "http://localhost:${WEB_PORT:-7860}/status" > /dev/null || exit 1'

# Varsayılan başlatma (CLI)
# Web için (ENTRYPOINT argümanı olarak): docker run ... --quick web --host 0.0.0.0 --port 7860
ENTRYPOINT ["/app/.venv/bin/python", "main.py"]
