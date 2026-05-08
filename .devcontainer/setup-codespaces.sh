#!/usr/bin/env bash
set -Eeuo pipefail

PHASE="${1:-post-create}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_ROOT}"

export UV_LINK_MODE="${UV_LINK_MODE:-copy}"
export UV_PROJECT_ENVIRONMENT="${UV_PROJECT_ENVIRONMENT:-.venv}"
export SIDAR_PYTHON_VERSION="${SIDAR_PYTHON_VERSION:-3.11}"
export CODING_MODEL="${CODING_MODEL:-qwen2.5-coder:7b}"
export OLLAMA_REQUIRED_MODELS="${OLLAMA_REQUIRED_MODELS:-${CODING_MODEL}}"

log() { printf 'ℹ️  %s\n' "$*"; }
ok() { printf '✅ %s\n' "$*"; }
warn() { printf '⚠️  %s\n' "$*"; }

ensure_uv() {
  if command -v uv >/dev/null 2>&1; then
    ok "uv hazır: $(uv --version)"
    return 0
  fi

  warn "uv bulunamadı; resmi uv kurulum betiği ile bootstrapping yapılacak."
  local uv_tmp
  uv_tmp="$(mktemp)"
  curl -fsSL --retry 3 --retry-all-errors https://astral.sh/uv/install.sh -o "${uv_tmp}"
  sh "${uv_tmp}"
  rm -f "${uv_tmp}"
  export PATH="${HOME}/.local/bin:${HOME}/.cargo/bin:${PATH}"

  if ! command -v uv >/dev/null 2>&1; then
    warn "uv kurulduktan sonra PATH üzerinde bulunamadı; terminali yeniden başlatmanız gerekebilir."
    return 1
  fi
  ok "uv kuruldu: $(uv --version)"
}

sync_python_environment() {
  ensure_uv
  log "Codespaces overlay dosya sistemi için UV_LINK_MODE=${UV_LINK_MODE}."
  
  # İYİLEŞTİRME: .venv klasörü kontrolü eklendi
  if [ -d "${UV_PROJECT_ENVIRONMENT}" ]; then
    ok "Sanal ortam (${UV_PROJECT_ENVIRONMENT}) zaten mevcut, oluşturma adımı atlanıyor."
  else
    log "Sanal ortam hazırlanıyor: uv venv --python ${SIDAR_PYTHON_VERSION} ${UV_PROJECT_ENVIRONMENT}"
    uv venv --python "${SIDAR_PYTHON_VERSION}" "${UV_PROJECT_ENVIRONMENT}"
  fi

  log "Geliştirici ortamı senkronlanıyor: uv sync --frozen --all-extras"
  uv sync --frozen --all-extras

  if [ ! -f .env.test ] && [ -f .env.test.example ]; then
    cp .env.test.example .env.test
    ok ".env.test, .env.test.example şablonundan oluşturuldu."
  fi
}

install_ollama_if_requested() {
  if [ "${SIDAR_CODESPACES_INSTALL_OLLAMA:-1}" = "0" ] || [ "${SIDAR_CODESPACES_INSTALL_OLLAMA:-1}" = "false" ]; then
    log "SIDAR_CODESPACES_INSTALL_OLLAMA=${SIDAR_CODESPACES_INSTALL_OLLAMA}; Ollama CLI kurulumu atlandı."
    return 0
  fi

  if command -v ollama >/dev/null 2>&1; then
    ok "Ollama CLI hazır: $(ollama --version 2>/dev/null || printf 'installed')"
    return 0
  fi

  if ! command -v sudo >/dev/null 2>&1; then
    warn "sudo bulunamadı; Ollama CLI otomatik kurulamadı. Manuel kurulum: https://ollama.com/download/linux"
    return 0
  fi

  warn "Ollama CLI bulunamadı; Codespaces hazırlık aşamasında resmi Ollama kurulum betiği çalıştırılıyor."
  local ollama_tmp
  ollama_tmp="$(mktemp)"
  curl -fsSL --retry 3 --retry-all-errors https://ollama.com/install.sh -o "${ollama_tmp}"
  sudo sh "${ollama_tmp}"
  rm -f "${ollama_tmp}"

  if command -v ollama >/dev/null 2>&1; then
    ok "Ollama CLI kuruldu."
  else
    warn "Ollama CLI kurulumu doğrulanamadı; run_tests.sh health check'i güvenli şekilde atlayabilir."
  fi
}

start_ollama_service() {
  if ! command -v ollama >/dev/null 2>&1; then
    warn "Ollama CLI yok; servis başlatılamadı."
    return 0
  fi

  local base_url="${OLLAMA_URL:-http://127.0.0.1:11434}"
  base_url="${base_url%/}"
  base_url="${base_url%/api}"

  if command -v curl >/dev/null 2>&1 && curl -fsS --max-time 2 "${base_url}/api/tags" >/dev/null 2>&1; then
    ok "Ollama API zaten erişilebilir: ${base_url}"
  else
    log "Ollama servisi arka planda başlatılıyor (${base_url})."
    mkdir -p .devcontainer/logs
    nohup ollama serve > .devcontainer/logs/ollama.log 2>&1 &
    sleep 2
  fi

  if [ "${SIDAR_CODESPACES_PULL_OLLAMA_MODELS:-0}" = "1" ] || [ "${SIDAR_CODESPACES_PULL_OLLAMA_MODELS:-0}" = "true" ]; then
    IFS=',' read -r -a models <<< "${OLLAMA_REQUIRED_MODELS}"
    for model in "${models[@]}"; do
      model="${model## }"
      model="${model%% }"
      [ -n "${model}" ] || continue
      log "Ollama modeli indiriliyor: ${model}"
      ollama pull "${model}" || warn "Model indirilemedi: ${model}"
    done
  else
    log "Model indirme başlangıçta kapalı (SIDAR_CODESPACES_PULL_OLLAMA_MODELS=1 ile etkinleştirin). Gerektiğinde run_tests.sh OLLAMA_AUTO_PULL_MISSING politikasını kullanır."
  fi
}

case "${PHASE}" in
  post-create)
    sync_python_environment
    install_ollama_if_requested
    start_ollama_service
    ;;
  post-start)
    start_ollama_service
    ;;
  *)
    warn "Bilinmeyen Codespaces setup fazı: ${PHASE}"
    ;;
esac
