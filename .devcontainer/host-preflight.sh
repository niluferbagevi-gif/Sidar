#!/usr/bin/env bash
set -Eeuo pipefail

TIMEOUT_SECONDS="${SIDAR_DEVCONTAINER_PREFLIGHT_TIMEOUT_SECONDS:-20}"
STRICT_MODE="${SIDAR_DEVCONTAINER_PREFLIGHT_STRICT:-0}"
INSTALL_DOCKER_CLI="${SIDAR_DEVCONTAINER_PREFLIGHT_INSTALL_DOCKER_CLI:-auto}"

log() { printf 'ℹ️  %s\n' "$*"; }
ok() { printf '✅ %s\n' "$*"; }
warn() { printf '⚠️  %s\n' "$*"; }
fail() { printf '❌ %s\n' "$*"; }


normalize_bool_mode() {
  case "$1" in
    1|true|yes|always) printf 'always' ;;
    0|false|no|never) printf 'never' ;;
    auto|"") printf 'auto' ;;
    *)
      printf '⚠️  Geçersiz SIDAR_DEVCONTAINER_PREFLIGHT_INSTALL_DOCKER_CLI=%s; auto kabul edilecek. Desteklenen: auto|always|never.\n' "$1" >&2
      printf 'auto'
      ;;
  esac
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

install_docker_cli_from_apt() {
  if ! command -v apt-get >/dev/null 2>&1; then
    warn "apt-get bulunamadı; Docker CLI otomatik kurulumu bu hostta desteklenmiyor."
    return 1
  fi
  if ! command -v curl >/dev/null 2>&1; then
    warn "curl bulunamadı; Docker APT anahtarı indirilemediği için Docker CLI kurulumu atlandı."
    return 1
  fi

  local platform codename
  platform="$(docker_repo_platform 2>/dev/null || true)"
  codename="$(docker_repo_codename 2>/dev/null || true)"
  if [ -z "${platform}" ] || [ -z "${codename}" ]; then
    warn "Docker resmi APT deposu için Debian/Ubuntu platform kod adı belirlenemedi; manuel kurulum gerekir."
    return 1
  fi

  local sudo_cmd=()
  if [ "${EUID}" -ne 0 ]; then
    if command -v sudo >/dev/null 2>&1 && sudo -n true >/dev/null 2>&1; then
      sudo_cmd=(sudo)
    else
      warn "Docker CLI otomatik kurulumu için root veya parolasız sudo gerekir. Manuel: sudo apt-get install docker-ce-cli docker-buildx-plugin docker-compose-plugin"
      return 1
    fi
  fi

  log "Docker CLI resmi Docker APT deposundan kuruluyor (${platform}/${codename})."
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

  "${sudo_cmd[@]}" apt-get update
  "${sudo_cmd[@]}" env DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    docker-ce-cli docker-buildx-plugin docker-compose-plugin

  if command -v docker >/dev/null 2>&1; then
    ok "Docker CLI kuruldu: $(docker --version)"
    return 0
  fi

  warn "Docker CLI paketleri kuruldu ancak docker binary PATH üzerinde bulunamadı."
  return 1
}

ensure_docker_cli() {
  if command -v docker >/dev/null 2>&1; then
    ok "Docker CLI hazır: $(docker --version)"
    return 0
  fi

  local mode
  mode="$(normalize_bool_mode "${INSTALL_DOCKER_CLI}")"
  if [ "${mode}" = "never" ]; then
    fail "docker CLI bulunamadı. SIDAR_DEVCONTAINER_PREFLIGHT_INSTALL_DOCKER_CLI=never olduğu için otomatik kurulum atlandı."
    return 1
  fi

  if [ -n "${WSL_DISTRO_NAME:-}" ] && [ "${mode}" != "always" ]; then
    fail "docker CLI bulunamadı. WSL için önerilen yol Docker Desktop WSL Integration'dır; APT kurulumu istiyorsanız SIDAR_DEVCONTAINER_PREFLIGHT_INSTALL_DOCKER_CLI=always kullanın."
    return 1
  fi

  warn "docker CLI bulunamadı; Docker resmi APT deposundan docker-ce-cli/buildx/compose kurulumu denenecek."
  install_docker_cli_from_apt
}

verify_docker_cli_plugins() {
  if docker compose version >/dev/null 2>&1; then
    ok "Docker Compose v2 hazır: $(docker compose version)"
  else
    warn "Docker Compose v2 eklentisi doğrulanamadı; docker-compose.yml komutları çalışmayabilir."
  fi

  if docker buildx version >/dev/null 2>&1; then
    ok "Docker Buildx hazır: $(docker buildx version)"
  else
    warn "Docker Buildx eklentisi doğrulanamadı; docker buildx/build komutları çalışmayabilir."
  fi
}

run_with_timeout() {
  local label="$1"
  shift

  local status=0
  set +e
  timeout "${TIMEOUT_SECONDS}" "$@" >/tmp/sidar-devcontainer-preflight.out 2>/tmp/sidar-devcontainer-preflight.err
  status=$?
  set -e

  if [ "${status}" -eq 0 ]; then
    ok "${label} tamamlandı."
    return 0
  fi

  if [ "${status}" -eq 124 ]; then
    fail "${label} ${TIMEOUT_SECONDS}s içinde tamamlanmadı. Docker Desktop/WSL entegrasyonu hazır olmayabilir."
  else
    fail "${label} başarısız oldu (exit=${status})."
  fi

  if [ -s /tmp/sidar-devcontainer-preflight.err ]; then
    warn "Hata çıktısı: $(tr '\n' ' ' </tmp/sidar-devcontainer-preflight.err | sed 's/[[:space:]]\+/ /g' | cut -c1-500)"
  fi
  return "${status}"
}

log "Sidar Dev Container host preflight başlıyor."

if [ -n "${WSL_DISTRO_NAME:-}" ]; then
  ok "WSL distro algılandı: ${WSL_DISTRO_NAME}."
else
  log "WSL_DISTRO_NAME boş; Linux host veya Codespaces benzeri ortam olabilir."
fi

preflight_failed=0

if ! ensure_docker_cli; then
  preflight_failed=1
else
  verify_docker_cli_plugins
  run_with_timeout "docker daemon version" docker version --format '{{.Server.Version}}' || preflight_failed=1
  run_with_timeout "docker info" docker info --format '{{.ServerVersion}} {{.OperatingSystem}}' || preflight_failed=1
fi

if [ "${preflight_failed}" -ne 0 ]; then
  if [ "${STRICT_MODE}" = "1" ] || [ "${STRICT_MODE}" = "true" ]; then
    fail "Sidar Dev Container host preflight başarısız; strict mod açık olduğu için işlem durduruluyor."
    exit 1
  fi
  warn "Sidar Dev Container host preflight uyarı üretti; strict mod kapalı olduğu için Dev Containers akışı devam edecek."
else
  ok "Sidar Dev Container host preflight başarılı."
fi
