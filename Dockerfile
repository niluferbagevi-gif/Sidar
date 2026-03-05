# ═══════════════════════════════════════════════════════════════
# Sidar AI — Dockerfile
# Sürüm: 2.7.0  (GPU & CPU destekli çift mod)
#
#  CPU modu (varsayılan):
#    docker build -t sidar-ai .
#
#  GPU modu (NVIDIA CUDA 12.4):
#    docker build \
#      --build-arg BASE_IMAGE=nvidia/cuda:12.4.1-runtime-ubuntu22.04 \
#      --build-arg GPU_ENABLED=true \
#      -t sidar-ai-gpu .
# ═══════════════════════════════════════════════════════════════

# ── Build-time argümanlar ──────────────────────────────────────
# CPU-only: python:3.11-slim
# GPU:      nvidia/cuda:12.4.1-runtime-ubuntu22.04
ARG BASE_IMAGE=python:3.11-slim
ARG GPU_ENABLED=false

FROM ${BASE_IMAGE}

# Meta veriler
LABEL maintainer="Sidar AI Project"
LABEL version="2.7.0"
LABEL description="Yazılım Mühendisi AI Asistanı - Docker İzolasyonu"

# Çevresel değişkenler
# GPU_ENABLED build-arg çalışma zamanında USE_GPU env değişkenine dönüşür
# MEMORY_ENCRYPTION_KEY: docker run -e MEMORY_ENCRYPTION_KEY=<fernet_key> ile iletilebilir
ARG MEMORY_ENCRYPTION_KEY=""
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    ACCESS_LEVEL=sandbox \
    USE_GPU=${GPU_ENABLED} \
    MEMORY_ENCRYPTION_KEY=${MEMORY_ENCRYPTION_KEY}

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
    && rm -rf /var/lib/apt/lists/*

# GPU modunda PyTorch CUDA wheel URL'i (CPU için default)
# GPU build: --build-arg TORCH_INDEX_URL=https://download.pytorch.org/whl/cu124
ARG TORCH_INDEX_URL=https://download.pytorch.org/whl/cpu
ENV TORCH_INDEX_URL=${TORCH_INDEX_URL}

# Bağımlılık Yönetimi (environment.yml entegrasyonu)
COPY environment.yml .

# PyYAML kur → pip bağımlılıklarını çıkar → kur
# NOT: Conda'ya özgü pytorch-cuda satırları pip ile kurulmaz;
#      GPU için TORCH_INDEX_URL üzerinden ayrı torch wheel alınır.
RUN pip install --upgrade pip setuptools wheel pyyaml && \
    python3 -c "\
import yaml; \
deps = yaml.safe_load(open('environment.yml')); \
pkgs = next((item['pip'] for item in deps['dependencies'] if isinstance(item, dict) and 'pip' in item), []); \
print('\n'.join(pkgs))" > requirements.txt && \
    pip install -r requirements.txt

# Uygulama kodlarını kopyala
COPY . .

# Kalıcı veri dizinleri
RUN mkdir -p logs data temp

# Güvenlik: root olmayan kullanıcı
RUN useradd -m sidar && chown -R sidar:sidar /app
USER sidar

# Web arayüzü portu
EXPOSE 7860

# Sağlık kontrolü — çalışma moduna göre deterministik kontrol yapar.
# Web modu: PID 1 komutu web_server.py ise /status endpoint'i zorunlu olarak doğrulanır.
# CLI modu: PID 1'in main.py/cli.py olması beklenir; rastgele python süreçleri kabul edilmez.
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
  CMD sh -c 'if ps -p 1 -o args= | grep -Eq "python(3)? .*web_server.py"; then curl -fsS http://localhost:7860/status > /dev/null; else ps -p 1 -o args= | grep -Eq "python(3)? .* (main.py|cli.py)( |$)"; fi'

# Varsayılan başlatma (CLI)
# Web için: docker run ... python web_server.py
ENTRYPOINT ["python", "main.py"] 