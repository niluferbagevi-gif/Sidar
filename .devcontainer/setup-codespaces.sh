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

diagnose_devcontainer_runtime() {
  log "Dev Container tanılama: faz=${PHASE}, workspace=${REPO_ROOT}"

  if [ -n "${WSL_DISTRO_NAME:-}" ]; then
    log "WSL ortamı algılandı: ${WSL_DISTRO_NAME}. VS Code loglarındaki ilk 'server/node' Exit code 1 kontrolleri, mevcut server yolu bulunana kadar normal fallback davranışı olabilir."
  fi

  if command -v docker >/dev/null 2>&1; then
    local docker_version
    docker_version="$(docker version --format '{{.Server.Version}}' 2>/dev/null || true)"
    if [ -n "${docker_version}" ]; then
      ok "Docker daemon erişilebilir: ${docker_version}"
    else
      warn "docker komutu bulundu ancak daemon sürümü okunamadı; Docker Desktop/WSL entegrasyonunu kontrol edin."
    fi
  else
    warn "docker CLI container içinde yok; ensure_docker_cli adımı CLI kurulumunu deneyecek. Host Docker daemon kontrolü VS Code Dev Containers tarafından build öncesinde yapılır."
  fi
}

docker_repo_platform() {
  [ -r /etc/os-release ] || return 1
  # shellcheck disable=SC1091
  . /etc/os-release
  case " ${ID:-} ${ID_LIKE:-} " in
    *" ubuntu "*) printf 'ubuntu' ;;
    *" debian "*) printf 'debian' ;;
    *) return 1 ;;
  esac
}

docker_repo_codename() {
  [ -r /etc/os-release ] || return 1
  # shellcheck disable=SC1091
  . /etc/os-release
  if [ "$(docker_repo_platform 2>/dev/null || true)" = "ubuntu" ] && [ -n "${UBUNTU_CODENAME:-}" ]; then
    printf '%s' "${UBUNTU_CODENAME}"
  elif [ -n "${VERSION_CODENAME:-}" ]; then
    printf '%s' "${VERSION_CODENAME}"
  else
    return 1
  fi
}

install_docker_apt_repository() {
  local sudo_cmd=()
  if [ "${EUID}" -ne 0 ]; then
    if command -v sudo >/dev/null 2>&1; then
      sudo_cmd=(sudo)
    else
      warn "sudo bulunamadı; Docker APT deposu eklenemiyor."
      return 1
    fi
  fi

  local platform codename
  platform="$(docker_repo_platform 2>/dev/null || true)"
  codename="$(docker_repo_codename 2>/dev/null || true)"
  if [ -z "${platform}" ] || [ -z "${codename}" ]; then
    warn "Docker resmi APT deposu için Debian/Ubuntu platform kod adı belirlenemedi; manuel kurulum gerekir."
    return 1
  fi

  log "Docker CLI resmi Docker APT deposundan kurulacak (${platform}/${codename})."
  "${sudo_cmd[@]}" rm -f /etc/apt/sources.list.d/docker.list
  "${sudo_cmd[@]}" apt-get update
  "${sudo_cmd[@]}" env DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends ca-certificates curl gnupg
  "${sudo_cmd[@]}" install -m 0755 -d /etc/apt/keyrings

  local keyring="/etc/apt/keyrings/docker-${platform}.asc"
  local key_tmp
  key_tmp="$(mktemp)"
  if ! curl -fsSL --retry 3 --retry-all-errors "https://download.docker.com/linux/${platform}/gpg" -o "${key_tmp}"; then
    rm -f "${key_tmp}"
    warn "Docker APT GPG anahtarı indirilemedi."
    return 1
  fi
  "${sudo_cmd[@]}" install -m 0644 "${key_tmp}" "${keyring}"
  rm -f "${key_tmp}"

  printf 'deb [arch=%s signed-by=%s] https://download.docker.com/linux/%s %s stable\n' \
    "$(dpkg --print-architecture)" "${keyring}" "${platform}" "${codename}" | \
    "${sudo_cmd[@]}" tee /etc/apt/sources.list.d/docker.list >/dev/null
}

ensure_docker_cli() {
  if command -v docker >/dev/null 2>&1; then
    ok "Docker CLI hazır: $(docker --version)"
  else
    warn "Docker CLI bulunamadı; docker-ce-cli/buildx/compose eklentileri kurulacak."
    if ! command -v apt-get >/dev/null 2>&1; then
      warn "apt-get bulunamadı; Docker CLI otomatik kurulamadı."
      return 0
    fi

    local sudo_cmd=()
    if [ "${EUID}" -ne 0 ]; then
      if command -v sudo >/dev/null 2>&1; then
        sudo_cmd=(sudo)
      else
        warn "sudo bulunamadı; Docker CLI otomatik kurulamadı."
        return 0
      fi
    fi

    install_docker_apt_repository || return 0

    "${sudo_cmd[@]}" apt-get update
    "${sudo_cmd[@]}" env DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends docker-ce-cli docker-buildx-plugin docker-compose-plugin
    ok "Docker CLI kuruldu: $(docker --version)"
  fi

  if docker compose version >/dev/null 2>&1; then
    ok "Docker Compose v2 hazır: $(docker compose version)"
  else
    warn "Docker Compose v2 eklentisi doğrulanamadı; docker-compose.yml komutları çalışmayabilir."
  fi

  if [ -S /var/run/docker.sock ]; then
    ok "Host Docker socket mount edildi: /var/run/docker.sock"
  else
    warn "Docker CLI mevcut ancak /var/run/docker.sock görünmüyor; container içinden Docker daemon erişimi için docker-outside-of-docker feature/host socket gerekir."
  fi
}

ensure_system_dependencies() {
  local packages=(portaudio19-dev)

  if ! command -v apt-get >/dev/null 2>&1; then
    warn "apt-get bulunamadı; PyAudio/PortAudio sistem bağımlılığı otomatik doğrulanamadı."
    return 0
  fi

  local missing=()
  local package
  for package in "${packages[@]}"; do
    if ! dpkg-query -W -f='${Status}' "${package}" 2>/dev/null | grep -q "ok installed"; then
      missing+=("${package}")
    fi
  done

  if [ "${#missing[@]}" -eq 0 ]; then
    ok "Python native sistem bağımlılıkları hazır: ${packages[*]}"
    return 0
  fi

  warn "Eksik Python native sistem bağımlılıkları kurulacak: ${missing[*]}"
  local sudo_cmd=()
  if [ "${EUID}" -ne 0 ]; then
    if command -v sudo >/dev/null 2>&1; then
      sudo_cmd=(sudo)
    else
      warn "sudo bulunamadı; eksik paketleri kuramıyorum: ${missing[*]}"
      return 1
    fi
  fi

  "${sudo_cmd[@]}" apt-get update
  "${sudo_cmd[@]}" env DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends "${missing[@]}"
  ok "Python native sistem bağımlılıkları kuruldu: ${missing[*]}"
}

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


dependency_fingerprint() {
  local files=(pyproject.toml uv.lock .python-version)
  {
    printf 'SIDAR_PYTHON_VERSION=%s\n' "${SIDAR_PYTHON_VERSION}"
    printf 'UV_SYNC_COMMAND=uv sync --frozen --all-extras\n'
    local file
    for file in "${files[@]}"; do
      if [ -f "${file}" ]; then
        sha256sum "${file}"
      else
        printf 'missing  %s\n' "${file}"
      fi
    done
  } | sha256sum | awk '{print $1}'
}

should_force_uv_sync() {
  case "${SIDAR_FORCE_UV_SYNC:-0}" in
    1|true|TRUE|yes|YES|on|ON)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

uv_sync_marker_path() {
  printf '%s/.sidar-uv-sync.sha256\n' "${UV_PROJECT_ENVIRONMENT}"
}

uv_sync_is_current() {
  local marker_path="$1"
  local expected_fingerprint="$2"

  [ -f "${marker_path}" ] || return 1
  [ "$(cat "${marker_path}" 2>/dev/null || true)" = "${expected_fingerprint}" ]
}

record_uv_sync_fingerprint() {
  local marker_path="$1"
  local fingerprint="$2"

  mkdir -p "$(dirname "${marker_path}")"
  printf '%s\n' "${fingerprint}" > "${marker_path}"
}

remove_virtualenv_with_reason() {
  local venv_dir="$1"
  local reason="$2"

  warn "${reason}"
  case "${venv_dir}" in
    ""|"/"|"."|"..")
      warn "Güvenli olmayan sanal ortam yolu temizlenmedi: ${venv_dir:-<empty>}"
      return 1
      ;;
  esac
  rm -rf "${venv_dir}"
  ok "Geçersiz sanal ortam temizlendi: ${venv_dir}"
}

remove_invalid_virtualenv() {
  local venv_dir="$1"
  local venv_python="${venv_dir}/bin/python"

  if [ ! -e "${venv_dir}" ]; then
    return 0
  fi

  if [ ! -d "${venv_dir}" ]; then
    remove_virtualenv_with_reason \
      "${venv_dir}" \
      "Sanal ortam yolu (${venv_dir}) dizin değil; yeniden oluşturulacak."
    return 0
  fi

  if [ -L "${venv_python}" ]; then
    local target
    target="$(readlink "${venv_python}" || true)"
    if [ -n "${target}" ] && [[ "${target}" = /* ]] && [ ! -e "${target}" ]; then
      remove_virtualenv_with_reason \
        "${venv_dir}" \
        "Sanal ortam (${venv_dir}) container dışında kalmış kırık Python symlink'i içeriyor (${venv_python} -> ${target}); uv uyarısını beklemeden yeniden oluşturulacak."
      return 0
    fi
  fi

  if [ ! -x "${venv_python}" ]; then
    if [ -L "${venv_python}" ]; then
      local target
      target="$(readlink "${venv_python}" || true)"
      remove_virtualenv_with_reason \
        "${venv_dir}" \
        "Sanal ortam (${venv_dir}) kırık Python symlink'i içeriyor (${venv_python} -> ${target:-unknown}); uv uyarısını beklemeden yeniden oluşturulacak."
    else
      remove_virtualenv_with_reason \
        "${venv_dir}" \
        "Sanal ortam (${venv_dir}) geçersiz veya eksik Python içeriyor; yeniden oluşturulacak."
    fi
    return 0
  fi

  local actual_version
  actual_version="$(${venv_python} -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null || true)"
  if [ "${actual_version}" != "${SIDAR_PYTHON_VERSION}" ]; then
    remove_virtualenv_with_reason \
      "${venv_dir}" \
      "Sanal ortam Python sürümü ${actual_version:-unknown}; beklenen ${SIDAR_PYTHON_VERSION}. uv sync öncesinde yeniden oluşturulacak."
    return 0
  fi

  local pyvenv_cfg="${venv_dir}/pyvenv.cfg"
  if [ -f "${pyvenv_cfg}" ]; then
    local cfg_home
    cfg_home="$(awk -F= '/^home[[:space:]]*=/ {gsub(/^[[:space:]]+|[[:space:]]+$/, "", $2); print $2; exit}' "${pyvenv_cfg}" || true)"
    if [ -n "${cfg_home}" ] && [[ "${cfg_home}" = /* ]] && [ ! -e "${cfg_home}" ]; then
      remove_virtualenv_with_reason \
        "${venv_dir}" \
        "Sanal ortam (${venv_dir}) taşınmış workspace'e ait görünüyor; pyvenv.cfg home yolu bulunamadı (${cfg_home}). Yeniden oluşturulacak."
      return 0
    fi
  fi
}

sync_python_environment() {
  ensure_uv
  ensure_system_dependencies
  log "Dev Container overlay dosya sistemi için UV_LINK_MODE=${UV_LINK_MODE}."

  remove_invalid_virtualenv "${UV_PROJECT_ENVIRONMENT}"

  local venv_python="${UV_PROJECT_ENVIRONMENT}/bin/python"
  local venv_recreated=0
  if [ -x "${venv_python}" ]; then
    ok "Sanal ortam (${UV_PROJECT_ENVIRONMENT}) mevcut."
  else
    log "Sanal ortam hazırlanıyor: uv venv --python ${SIDAR_PYTHON_VERSION} ${UV_PROJECT_ENVIRONMENT}"
    uv venv --python "${SIDAR_PYTHON_VERSION}" "${UV_PROJECT_ENVIRONMENT}"
    venv_recreated=1
  fi

  local sync_fingerprint
  local sync_marker
  sync_fingerprint="$(dependency_fingerprint)"
  sync_marker="$(uv_sync_marker_path)"

  if [ "${venv_recreated}" -eq 0 ] && ! should_force_uv_sync && uv_sync_is_current "${sync_marker}" "${sync_fingerprint}"; then
    ok "Geliştirici ortamı güncel; uv sync atlandı (zorlamak için SIDAR_FORCE_UV_SYNC=1)."
  else
    log "Geliştirici ortamı senkronlanıyor: uv sync --frozen --all-extras"
    if ! uv sync --frozen --all-extras; then
      warn "uv sync başarısız oldu. PyAudio derleme hatası görüyorsanız portaudio19-dev paketinin kurulu olduğundan emin olun."
      return 1
    fi
    record_uv_sync_fingerprint "${sync_marker}" "${sync_fingerprint}"
    ok "uv sync parmak izi kaydedildi: ${sync_marker}"
  fi

  if [ -x "${venv_python}" ]; then
    local actual_version
    actual_version="$(${venv_python} -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
    if [ "${actual_version}" = "${SIDAR_PYTHON_VERSION}" ]; then
      ok "Python sanal ortam sürümü uyumlu: ${actual_version}"
    else
      warn "Python sanal ortam sürümü ${actual_version}; beklenen ${SIDAR_PYTHON_VERSION}. Gerekirse ${UV_PROJECT_ENVIRONMENT} silinip post-create yeniden çalıştırılmalı."
    fi
  else
    warn "Sanal ortam Python yorumlayıcısı bulunamadı: ${venv_python}"
  fi

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

  warn "Ollama CLI bulunamadı; Dev Container hazırlık aşamasında resmi Ollama kurulum betiği çalıştırılıyor."
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
  sync)
    diagnose_devcontainer_runtime
    ensure_docker_cli
    sync_python_environment
    ;;
  post-create)
    diagnose_devcontainer_runtime
    ensure_docker_cli
    sync_python_environment
    install_ollama_if_requested
    start_ollama_service
    ;;
  post-start)
    diagnose_devcontainer_runtime
    ensure_docker_cli
    start_ollama_service
    ;;
  *)
    warn "Bilinmeyen Dev Container setup fazı: ${PHASE}"
    ;;
esac
