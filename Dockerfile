# syntax=docker/dockerfile:1.7

# ═══════════════════════════════════════════════════════════════
# Sidar AI — Dockerfile
# Sürüm: 5.2.0  (GPU & CPU destekli çift mod, multi-stage)
# ═══════════════════════════════════════════════════════════════

ARG PYTHON_VERSION=3.11
ARG BASE_IMAGE=python:${PYTHON_VERSION}-slim
ARG GPU_ENABLED=false
ARG UV_OPTIONAL_EXTRAS=""

FROM ${BASE_IMAGE} AS builder
ARG PYTHON_VERSION=3.11
ARG GPU_ENABLED=false
ARG MEMORY_ENCRYPTION_KEY=""
ARG UV_OPTIONAL_EXTRAS=""

LABEL maintainer="Sidar AI Project"
LABEL version="5.2.0"
LABEL description="Yazılım Mühendisi AI Asistanı - Docker İzolasyonu"

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

WORKDIR /app

# Builder: derleme ve native wheel gereksinimleri
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    set -eux; \
    apt-get update; \
    if [ "$GPU_ENABLED" = "true" ]; then \
      apt-get install -y --no-install-recommends software-properties-common; \
      add-apt-repository -y ppa:deadsnakes/ppa; \
      apt-get update; \
      apt-get install -y --no-install-recommends \
        python${PYTHON_VERSION} \
        python${PYTHON_VERSION}-venv \
        python${PYTHON_VERSION}-distutils; \
      ln -sf /usr/bin/python${PYTHON_VERSION} /usr/local/bin/python3; \
    fi; \
    apt-get install -y --no-install-recommends \
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
      shellcheck

ENV UV_INDEX_STRATEGY=first-index \
    PATH="${VIRTUAL_ENV}/bin:$PATH"

COPY --from=ghcr.io/astral-sh/uv:0.5.4 /uv /uvx /bin/
RUN uv --version && uvx --version
COPY pyproject.toml uv.lock README.md ./
RUN test -f uv.lock || (echo "uv.lock is required for deterministic builds" >&2; exit 1)
RUN --mount=type=cache,target=/root/.cache/uv \
    set -eux; \
    UV_SYNC_ARGS="--frozen --no-install-project"; \
    if [ -n "${UV_OPTIONAL_EXTRAS}" ]; then \
      for extra in $(echo "${UV_OPTIONAL_EXTRAS}" | tr ',' ' '); do \
        UV_SYNC_ARGS="${UV_SYNC_ARGS} --extra ${extra}"; \
      done; \
    fi; \
    uv sync ${UV_SYNC_ARGS}
RUN uv run python -c "import shutil; assert shutil.which('pyright-langserver'), 'pyright-langserver missing'; assert shutil.which('pyright'), 'pyright missing'"

ARG PRECACHE_RAG_MODEL=false
ARG RAG_EMBEDDING_MODEL=all-MiniLM-L6-v2
RUN if [ "$PRECACHE_RAG_MODEL" = "true" ]; then \
      python3 -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('${RAG_EMBEDDING_MODEL}')"; \
    else \
      echo "RAG model pre-cache atlandı"; \
    fi

COPY . .
RUN --mount=type=cache,target=/root/.cache/uv \
    set -eux; \
    UV_SYNC_ARGS="--frozen"; \
    if [ -n "${UV_OPTIONAL_EXTRAS}" ]; then \
      for extra in $(echo "${UV_OPTIONAL_EXTRAS}" | tr ',' ' '); do \
        UV_SYNC_ARGS="${UV_SYNC_ARGS} --extra ${extra}"; \
      done; \
    fi; \
    uv sync ${UV_SYNC_ARGS}

FROM ${BASE_IMAGE} AS runtime
ARG PYTHON_VERSION=3.11
ARG GPU_ENABLED=false
ARG MEMORY_ENCRYPTION_KEY=""

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=7860 \
    PIP_NO_CACHE_DIR=1 \
    UV_PYTHON=${PYTHON_VERSION} \
    VIRTUAL_ENV=/app/.venv \
    PYTHONPATH=/app \
    ACCESS_LEVEL=sandbox \
    USE_GPU=${GPU_ENABLED} \
    MEMORY_ENCRYPTION_KEY=${MEMORY_ENCRYPTION_KEY} \
    ENABLE_TRACING=false \
    OTEL_EXPORTER_ENDPOINT=http://localhost:4317 \
    REDIS_URL=redis://redis:6379/0 \
    UV_INDEX_STRATEGY=first-index \
    PATH="${VIRTUAL_ENV}/bin:$PATH"

WORKDIR /app

# Runtime: yalnız çalıştırma için gerekli paketler
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    set -eux; \
    apt-get update; \
    if [ "$GPU_ENABLED" = "true" ]; then \
      apt-get install -y --no-install-recommends software-properties-common; \
      add-apt-repository -y ppa:deadsnakes/ppa; \
      apt-get update; \
      apt-get install -y --no-install-recommends \
        python${PYTHON_VERSION} \
        python${PYTHON_VERSION}-venv \
        python${PYTHON_VERSION}-distutils; \
      ln -sf /usr/bin/python${PYTHON_VERSION} /usr/local/bin/python3; \
    fi; \
    apt-get install -y --no-install-recommends \
      python3-pip \
      curl \
      zstd \
      docker.io \
      portaudio19-dev \
      python3-pyaudio \
      alsa-utils \
      v4l-utils \
      ffmpeg

COPY --from=builder /app /app

RUN useradd -m -u 10001 sidaruser && mkdir -p /app/logs /app/data /app/temp /app/sessions /app/chroma_db /app/data/rag /app/data/lora_adapters /app/data/continuous_learning && chown -R sidaruser:sidaruser /app
USER sidaruser

EXPOSE 7860

HEALTHCHECK --interval=30s --timeout=10s --start-period=240s --retries=3 \
  CMD sh -c 'curl -fsS "http://localhost:${WEB_PORT:-7860}/status" > /dev/null || exit 1'

ENTRYPOINT ["/app/.venv/bin/python", "main.py"]
