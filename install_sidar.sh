#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════════
# Sidar AI — Kurulum Betiği (install_sidar.sh)
# Sürüm : 5.2.3
# Hedef : WSL2 / Ubuntu / Conda + NVIDIA RTX 30xx/40xx (CUDA 13.x, PyTorch cu124 fallback)
#
# Kullanım:
#   chmod +x install_sidar.sh
#   ./install_sidar.sh           # standart kurulum
#   ./install_sidar.sh --upgrade-lock  # uv.lock dosyasını bilinçli olarak güncelle
#   ./install_sidar.sh --cpu     # GPU algılansa bile CPU zorla
#   ./install_sidar.sh --kubernetes  # Helm ile Kubernetes kurulumuna geç
#   ./install_sidar.sh --headless --yes  # tam etkileşimsiz kurulum (CI/sunucu)
#   ./install_sidar.sh --silent   # CI/CD için sessiz kurulum (güvenli varsayılanlarla)
#   ./install_sidar.sh --auto --mode=local --env=development --reset-db --no-vscode
#   ./install_sidar.sh --with-browsers  # Playwright Chromium + deps kurulumunu zorla
#   AUTO_INSTALL=true INSTALL_MODE=1 ENV_TYPE=dev RESET_DB=yes START_DOCKER_SERVICES=yes OPEN_VSCODE=no ./install_sidar.sh
# ═══════════════════════════════════════════════════════════════════════════════
set -Eeuo pipefail

# Uzak script indirmelerinde checksum yoksa güvenlik gereği varsayılan olarak reddet
export ALLOW_UNVERIFIED_REMOTE_SCRIPTS="${ALLOW_UNVERIFIED_REMOTE_SCRIPTS:-0}"

# GitHub Codespaces overlay dosya sisteminde uv hardlink uyarılarını ve gereksiz
# full-copy fallback denemelerini önlemek için copy modu varsayılanlaştırılır.
if [[ -z "${UV_LINK_MODE:-}" && ( "${CODESPACES:-}" == "true" || "${GITHUB_CODESPACES:-}" == "true" ) ]]; then
    export UV_LINK_MODE=copy
fi

# Kurulum loglarını eşzamanlı olarak terminale ve dosyaya yaz
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ORIGINAL_SCRIPT_PATH="$(readlink -f "${BASH_SOURCE[0]}")"
ORIGINAL_SCRIPT_DIR="$SCRIPT_DIR"
# Not: Repo clone/sync tamamlanmadan TARGET_DIR altında dosya üretmeyin.
# Aksi halde "sıfır kurulum" akışında hedef dizin gereksiz yere dolu görünebilir.
LOG_DIR="$SCRIPT_DIR/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/install_$(date +%Y%m%d_%H%M%S).log"
exec > >(tee -i >(sed -u -E $'s/\x1B\\[[0-9;]*[[:alpha:]]//g' > "$LOG_FILE")) 2>&1

# ── Renkler ──────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; BOLD='\033[1m'; NC='\033[0m'

ok()   { echo -e "${GREEN}✅  $*${NC}" >&2; }
info() { echo -e "${BLUE}ℹ️   $*${NC}" >&2; }
warn() { echo -e "${YELLOW}⚠️   $*${NC}" >&2; }
fail() { echo -e "${RED}❌  $*${NC}" >&2; exit 1; }
step() { echo -e "\n${BOLD}${BLUE}── $* ──${NC}" >&2; }

# BEGIN_BUNDLE_MODULES
INSTALL_MODULE_DIR="${SCRIPT_DIR}/scripts/install_modules"
INSTALL_HELPERS_TEMP_DIR=""
REQUIRED_INSTALL_MODULES=(
    "install_helpers.sh"
    "gpu_utils.sh"
    "env_utils.sh"
    "db_credentials.sh"
    "ollama_models.sh"
)
missing_install_modules=()
for module_name in "${REQUIRED_INSTALL_MODULES[@]}"; do
    if [[ ! -f "${INSTALL_MODULE_DIR}/${module_name}" ]]; then
        missing_install_modules+=("$module_name")
    fi
done

if (( ${#missing_install_modules[@]} > 0 )); then
    warn "Yerel kurulum modülleri eksik: ${missing_install_modules[*]}"
    warn "Tek dosyalık/eksik checkout algılandı; modüller uzaktan indirilmeyi deneyecek."

    INSTALL_HELPERS_TEMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/sidar_install_modules.XXXXXX")"
    INSTALL_MODULE_DIR="${INSTALL_HELPERS_TEMP_DIR}/install_modules"
    mkdir -p "$INSTALL_MODULE_DIR"
    REMOTE_MODULE_BASE="${SIDAR_INSTALL_MODULE_BASE_URL:-https://raw.githubusercontent.com/niluferbagevi-gif/Sidar/main/scripts/install_modules}"

    for module_name in "${REQUIRED_INSTALL_MODULES[@]}"; do
        remote_module_url="${REMOTE_MODULE_BASE}/${module_name}"
        tmp_module_path="$(mktemp "${TMPDIR:-/tmp}/sidar_install_${module_name%.sh}.XXXXXX.sh")"
        if command -v curl &>/dev/null; then
            if ! curl -fsSL "$remote_module_url" -o "$tmp_module_path"; then
                rm -f "$tmp_module_path"
                rm -rf "$INSTALL_HELPERS_TEMP_DIR"
                fail "Gerekli modül indirilemedi: ${remote_module_url}"
            fi
        elif command -v wget &>/dev/null; then
            if ! wget -qO "$tmp_module_path" "$remote_module_url"; then
                rm -f "$tmp_module_path"
                rm -rf "$INSTALL_HELPERS_TEMP_DIR"
                fail "Gerekli modül indirilemedi: ${remote_module_url}"
            fi
        else
            rm -f "$tmp_module_path"
            rm -rf "$INSTALL_HELPERS_TEMP_DIR"
            fail "Ne curl ne de wget bulundu; modüller indirilemiyor."
        fi

        install -m 0644 "$tmp_module_path" "${INSTALL_MODULE_DIR}/${module_name}"
        rm -f "$tmp_module_path"
    done
    ok "Kurulum modülleri geçici dizine indirildi: $INSTALL_MODULE_DIR"
fi

for module_name in "${REQUIRED_INSTALL_MODULES[@]}"; do
    # shellcheck disable=SC1090
    source "${INSTALL_MODULE_DIR}/${module_name}"
done
unset module_name missing_install_modules remote_module_url tmp_module_path
# END_BUNDLE_MODULES

run_with_progress_hint() {
    local label="$1"
    shift
    local -a cmd=("$@")

    "${cmd[@]}" &
    local cmd_pid=$!
    local pct=5

    while kill -0 "$cmd_pid" 2>/dev/null; do
        local filled=$((pct / 4))
        local empty=$((25 - filled))
        local bar_filled
        local bar_empty
        printf -v bar_filled '%*s' "$filled" ''
        printf -v bar_empty '%*s' "$empty" ''
        bar_filled="${bar_filled// /█}"
        bar_empty="${bar_empty// /░}"
        echo -e "${BLUE}[${bar_filled}${bar_empty}] ${pct}% ${label}${NC}" >&2

        pct=$((pct + 5))
        if (( pct > 95 )); then
            pct=95
        fi
        sleep 4
    done

    wait "$cmd_pid"
    local cmd_rc=$?
    if [[ "$cmd_rc" -eq 0 ]]; then
        echo -e "${GREEN}[█████████████████████████] 100% ${label}${NC}" >&2
    fi
    return "$cmd_rc"
}

prompt_yes_no_with_timeout_default_yes() {
    local prompt="$1"
    local timeout_seconds="${2:-180}"
    local reply=""

    if read -r -t "$timeout_seconds" -p "$prompt" reply; then
        :
    else
        warn "${timeout_seconds} saniye içinde yanıt alınamadı. Varsayılan seçim: Evet."
        reply="E"
    fi

    echo "$reply"
}

prompt_yes_no_with_timeout_default_no() {
    local prompt="$1"
    local timeout_seconds="${2:-180}"
    local reply=""

    if read -r -t "$timeout_seconds" -p "$prompt" reply; then
        :
    else
        warn "${timeout_seconds} saniye içinde yanıt alınamadı. Varsayılan seçim: Hayır."
        reply="H"
    fi

    echo "$reply"
}

on_install_error() {
    local exit_code=$?
    local failed_line="${1:-unknown}"
    local failed_cmd="${2:-unknown}"
    echo "❌ Kurulum başarısız (satır ${failed_line}, çıkış kodu ${exit_code})." >&2
    echo "   Hata veren komut: ${failed_cmd}" >&2
    echo "   Temizleme/inceleme için log dosyasını kontrol edin: ${LOG_FILE}" >&2
    exit "$exit_code"
}

trap 'on_install_error "$LINENO" "$BASH_COMMAND"' ERR

cleanup_temp_install_modules_if_needed() {
    if [[ -n "${INSTALL_HELPERS_TEMP_DIR:-}" && -d "$INSTALL_HELPERS_TEMP_DIR" ]]; then
        rm -rf "$INSTALL_HELPERS_TEMP_DIR"
        info "Geçici modül dizini temizlendi: $INSTALL_HELPERS_TEMP_DIR"
    fi
}

relocate_log_file_if_needed() {
    [[ -n "${TARGET_DIR:-}" ]] || return 0
    local target_log_dir="${TARGET_DIR}/logs"
    local source_log_dir="$LOG_DIR"

    if [[ -f "$LOG_FILE" && "$LOG_DIR" != "$target_log_dir" ]]; then
        mkdir -p "$target_log_dir"
        mv "$LOG_FILE" "$target_log_dir/"
        LOG_DIR="$target_log_dir"
        LOG_FILE="$target_log_dir/$(basename "$LOG_FILE")"
        info "Kurulum log dosyası ${LOG_FILE} konumuna taşındı."

        if [[ -d "$source_log_dir" ]]; then
            rmdir "$source_log_dir" 2>/dev/null || true
        fi
    fi
}

trap 'relocate_log_file_if_needed || true; cleanup_temp_install_modules_if_needed || true' EXIT

compute_sha256() {
    local file_path="$1"
    if command -v sha256sum &>/dev/null; then
        sha256sum "$file_path" | awk '{print $1}'
    elif command -v shasum &>/dev/null; then
        shasum -a 256 "$file_path" | awk '{print $1}'
    else
        fail "SHA256 doğrulaması için sha256sum/shasum bulunamadı."
    fi
}

DOWNLOADED_SCRIPT_FILE=""

validate_downloaded_script_file() {
    local script_file="${1:-}"
    local script_label="${2:-indirilen_betik}"
    if [[ -z "$script_file" ]]; then
        fail "${script_label}: indirilen betik yolu boş."
    fi
    if [[ "$script_file" == *$'\n'* ]]; then
        fail "${script_label}: betik yolu birden fazla satır içeriyor, güvenli değil."
    fi
    if [[ ! -f "$script_file" ]]; then
        fail "${script_label}: betik dosyası bulunamadı (${script_file})."
    fi
}

docker_cli_healthy() {
    command -v docker &>/dev/null || return 1

    local retries="${DOCKER_CLI_HEALTH_RETRIES:-6}"
    local delay_seconds="${DOCKER_CLI_HEALTH_RETRY_DELAY:-2}"
    if [[ ! "$retries" =~ ^[0-9]+$ ]] || (( retries < 1 )); then
        retries=6
    fi
    if [[ ! "$delay_seconds" =~ ^[0-9]+$ ]]; then
        delay_seconds=2
    fi

    local attempt=1
    local docker_out=""
    local docker_rc=0

    while (( attempt <= retries )); do
        docker_rc=0
        docker_out="$(docker --version 2>&1)" || docker_rc=$?
        if [[ "$docker_rc" -eq 0 ]]; then
            return 0
        fi

        if (( attempt < retries )); then
            sleep "$delay_seconds"
        fi
        ((attempt += 1))
    done

    if [[ "$docker_rc" -eq 135 ]] || [[ "$docker_out" == *"Bus error"* ]]; then
        warn "Docker CLI Bus error veriyor. WSL2 Docker Desktop entegrasyonunu yeniden etkinleştirip WSL'i yeniden başlatın."
    elif [[ "$docker_out" == *"Input/output error"* ]]; then
        warn "Docker CLI Input/output error veriyor. WSL mount/entegrasyon durumu bozulmuş olabilir."
    fi
    return 1
}

is_windows_interop_binary_path() {
    local bin_path="${1:-}"
    [[ -z "$bin_path" ]] && return 1

    # WSL üzerinde Windows binary'leri genellikle /mnt/<drive>/... altında ve .exe uzantılıdır.
    [[ "$bin_path" == /mnt/[A-Za-z]/* ]] && return 0
    [[ "$bin_path" == *.exe ]] && return 0
    return 1
}

resolve_native_binary_path() {
    local cmd_name="${1:-}"
    local resolved_path=""
    [[ -n "$cmd_name" ]] || return 1

    resolved_path="$(type -P "$cmd_name" 2>/dev/null || true)"
    [[ -n "$resolved_path" ]] || return 1

    if is_windows_interop_binary_path "$resolved_path"; then
        return 1
    fi

    echo "$resolved_path"
}

has_native_binary() {
    local cmd_name="${1:-}"
    resolve_native_binary_path "$cmd_name" >/dev/null
}

windows_path_to_wsl_path() {
    local windows_path="${1:-}"
    if [[ "$windows_path" =~ ^[A-Za-z]:\\ ]]; then
        local drive_letter path_rest
        drive_letter=$(echo "$windows_path" | cut -d: -f1 | tr 'A-Z' 'a-z')
        path_rest=$(echo "$windows_path" | cut -d: -f2- | sed 's#\\#/#g')
        echo "/mnt/${drive_letter}${path_rest}"
        return 0
    fi
    return 1
}

resolve_windows_userprofile_path() {
    local win_userprofile=""
    local resolved_wsl_path=""

    # Birincil yöntem: cmd.exe interop
    if command -v cmd.exe &>/dev/null; then
        win_userprofile=$(cmd.exe /d /c "echo %UserProfile%" 2>/dev/null | tr -d '\r' | tail -n1 || true)
        resolved_wsl_path="$(windows_path_to_wsl_path "$win_userprofile" || true)"
        if [[ -n "$resolved_wsl_path" ]]; then
            echo "$resolved_wsl_path"
            return 0
        fi
    fi

    # Fallback: powershell.exe interop (kurumsal cmd policy kısıtlarında işe yarayabilir)
    if command -v powershell.exe &>/dev/null; then
        win_userprofile=$(powershell.exe -NoProfile -Command '$env:UserProfile' 2>/dev/null | tr -d '\r' | tail -n1 || true)
        resolved_wsl_path="$(windows_path_to_wsl_path "$win_userprofile" || true)"
        if [[ -n "$resolved_wsl_path" ]]; then
            echo "$resolved_wsl_path"
            return 0
        fi
    fi

    # Son fallback: yaygın varsayım (C:\Users\<username>)
    if [[ -n "${USER:-}" && -d "/mnt/c/Users/${USER}" ]]; then
        echo "/mnt/c/Users/${USER}"
        return 0
    fi

    return 1
}

resolve_windows_localappdata_path() {
    local win_localappdata=""
    local resolved_wsl_path=""

    if command -v cmd.exe &>/dev/null; then
        win_localappdata=$(cmd.exe /d /c "echo %LocalAppData%" 2>/dev/null | tr -d '\r' | tail -n1 || true)
        resolved_wsl_path="$(windows_path_to_wsl_path "$win_localappdata" || true)"
        if [[ -n "$resolved_wsl_path" ]]; then
            echo "$resolved_wsl_path"
            return 0
        fi
    fi

    if command -v powershell.exe &>/dev/null; then
        win_localappdata=$(powershell.exe -NoProfile -Command '$env:LocalAppData' 2>/dev/null | tr -d '\r' | tail -n1 || true)
        resolved_wsl_path="$(windows_path_to_wsl_path "$win_localappdata" || true)"
        if [[ -n "$resolved_wsl_path" ]]; then
            echo "$resolved_wsl_path"
            return 0
        fi
    fi

    local userprofile_path=""
    userprofile_path="$(resolve_windows_userprofile_path 2>/dev/null || true)"
    if [[ -n "$userprofile_path" && -d "${userprofile_path}/AppData/Local" ]]; then
        echo "${userprofile_path}/AppData/Local"
        return 0
    fi

    return 1
}


verify_offline_bundle_manifest() {
    local bundle_dir="${1:-}"
    [[ -n "$bundle_dir" ]] || fail "Çevrimdışı mod etkin ancak offline bundle dizini bulunamadı."
    [[ -d "$bundle_dir" ]] || fail "Çevrimdışı bundle dizini bulunamadı: $bundle_dir"
    [[ -f "$bundle_dir/manifest.json" ]] || fail "Çevrimdışı bundle manifesti eksik: $bundle_dir/manifest.json"

    if command -v python3 &>/dev/null; then
        python3 "$SCRIPT_DIR/scripts/offline_bundle.py" verify "$bundle_dir" \
            || fail "Çevrimdışı bundle SHA256 doğrulaması başarısız oldu."
    else
        fail "Çevrimdışı manifest doğrulaması için python3 gereklidir."
    fi

    export UV_FIND_LINKS="${bundle_dir}/wheels"
    export UV_NO_INDEX=1
    export npm_config_cache="${bundle_dir}/npm/cache"
    export OLLAMA_MODELS="${bundle_dir}/ollama/models"
    ok "Çevrimdışı bundle doğrulandı ve wheel/npm/Ollama cache yolları ayarlandı."
}

download_verified_script() {
    local script_url="$1"
    local expected_sha="$2"
    local script_label="$3"
    local script_file
    script_file=$(mktemp)

    if [[ "$OFFLINE_MODE" == true ]]; then
        rm -f "$script_file"
        fail "${script_label}: --offline/--air-gapped modunda uzak betik indirilemez (${script_url}). offline_packages kullanın."
    fi

    if ! curl -fsSL --retry 3 --retry-all-errors \
        -H "Cache-Control: no-cache" -H "Pragma: no-cache" \
        "$script_url" -o "$script_file"; then
        rm -f "$script_file"
        fail "${script_label} indirilemedi: ${script_url}"
    fi

    local actual_sha
    actual_sha=$(compute_sha256 "$script_file")

    if [[ -z "$expected_sha" ]]; then
        if [[ "${ALLOW_UNVERIFIED_REMOTE_SCRIPTS:-0}" != "1" ]]; then
            rm -f "$script_file"
            fail "${script_label} checksum değeri tanımlı değil. ${script_label^^}_SHA256 değişkenini ayarlayın veya ALLOW_UNVERIFIED_REMOTE_SCRIPTS=1 kullanın."
        fi
        warn "${script_label} checksum doğrulaması atlandı (ALLOW_UNVERIFIED_REMOTE_SCRIPTS=1)."
    elif [[ "$actual_sha" != "$expected_sha" ]]; then
        rm -f "$script_file"
        fail "${script_label} checksum doğrulaması başarısız! Beklenen=${expected_sha}, Gelen=${actual_sha}"
    else
        ok "${script_label} checksum doğrulaması başarılı."
    fi

    DOWNLOADED_SCRIPT_FILE="$script_file"
}

docker_repo_platform() {
    if [[ ! -r /etc/os-release ]]; then
        return 1
    fi

    # shellcheck disable=SC1091
    . /etc/os-release
    case " ${ID:-} ${ID_LIKE:-} " in
        *" ubuntu "*) echo "ubuntu" ;;
        *" debian "*) echo "debian" ;;
        *) return 1 ;;
    esac
}

docker_repo_codename() {
    if [[ ! -r /etc/os-release ]]; then
        return 1
    fi

    # shellcheck disable=SC1091
    . /etc/os-release
    if [[ "$(docker_repo_platform 2>/dev/null || true)" == "ubuntu" && -n "${UBUNTU_CODENAME:-}" ]]; then
        echo "$UBUNTU_CODENAME"
    elif [[ -n "${VERSION_CODENAME:-}" ]]; then
        echo "$VERSION_CODENAME"
    else
        return 1
    fi
}

install_docker_cli_from_apt() {
    if [[ "$OFFLINE_MODE" == true ]]; then
        warn "Çevrimdışı modda Docker CLI APT deposundan kurulamaz; offline bundle veya manuel kurulum gerekir."
        return 1
    fi
    if ! command -v apt-get &>/dev/null; then
        warn "apt-get bulunamadı; Docker CLI otomatik kurulumu bu platformda desteklenmiyor."
        return 1
    fi
    if ! command -v curl &>/dev/null; then
        warn "curl bulunamadı; Docker APT anahtarı indirilemediği için Docker CLI kurulumu atlandı."
        return 1
    fi

    local docker_platform=""
    local docker_codename=""
    docker_platform="$(docker_repo_platform 2>/dev/null || true)"
    docker_codename="$(docker_repo_codename 2>/dev/null || true)"
    if [[ -z "$docker_platform" || -z "$docker_codename" ]]; then
        warn "Docker resmi APT deposu için Debian/Ubuntu platform kod adı belirlenemedi; manuel kurulum gerekir."
        return 1
    fi

    local -a sudo_cmd=()
    if [[ "${EUID}" -ne 0 ]]; then
        if command -v sudo &>/dev/null; then
            sudo_cmd=(sudo)
        else
            warn "sudo bulunamadı; Docker CLI paketleri otomatik kurulamadı."
            return 1
        fi
    fi

    if [[ "$NO_INTERACTION" == true ]]; then
        if [[ "${#sudo_cmd[@]}" -gt 0 ]] && ! sudo -n true >/dev/null 2>&1; then
            warn "--ci/--no-interaction modunda Docker CLI kurulumu için parolasız sudo yok. Manuel: sudo apt-get install docker-ce-cli docker-buildx-plugin docker-compose-plugin"
            return 1
        fi
    fi

    info "Docker CLI resmi Docker APT deposundan kuruluyor (${docker_platform}/${docker_codename})."
    "${sudo_cmd[@]}" apt-get update
    "${sudo_cmd[@]}" env DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends ca-certificates curl gnupg
    "${sudo_cmd[@]}" install -m 0755 -d /etc/apt/keyrings

    local keyring="/etc/apt/keyrings/docker-${docker_platform}.asc"
    local key_tmp=""
    key_tmp=$(mktemp)
    if ! curl -fsSL --retry 3 --retry-all-errors "https://download.docker.com/linux/${docker_platform}/gpg" -o "$key_tmp"; then
        rm -f "$key_tmp"
        warn "Docker APT GPG anahtarı indirilemedi."
        return 1
    fi
    "${sudo_cmd[@]}" install -m 0644 "$key_tmp" "$keyring"
    rm -f "$key_tmp"

    printf 'deb [arch=%s signed-by=%s] https://download.docker.com/linux/%s %s stable\n' \
        "$(dpkg --print-architecture)" "$keyring" "$docker_platform" "$docker_codename" | \
        "${sudo_cmd[@]}" tee /etc/apt/sources.list.d/docker.list >/dev/null

    "${sudo_cmd[@]}" apt-get update
    "${sudo_cmd[@]}" env DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        docker-ce-cli docker-buildx-plugin docker-compose-plugin

    if docker_cli_healthy; then
        ok "Docker CLI kuruldu: $(docker --version)"
    else
        warn "Docker CLI paketleri kuruldu ancak 'docker --version' sağlıklı çalışmadı."
        return 1
    fi

    if docker compose version &>/dev/null; then
        ok "Docker Compose v2 hazır: $(docker compose version)"
    else
        warn "Docker Compose v2 eklentisi kurulum sonrası doğrulanamadı."
    fi
}

ensure_docker_cli_available() {
    local mode="${DOCKER_CLI_INSTALL_MODE:-auto}"
    case "$mode" in
        auto|always|never) ;;
        true|yes|1) mode="always" ;;
        false|no|0) mode="never" ;;
        *)
            warn "DOCKER_CLI_INSTALL_MODE=${mode} geçersiz; auto kabul edilecek. Desteklenen: auto|always|never."
            mode="auto"
            ;;
    esac

    if docker_cli_healthy; then
        ok "Docker CLI hazır: $(docker --version)"
        return 0
    fi

    if [[ "$mode" == "never" ]]; then
        warn "Docker CLI bulunamadı/sağlıksız; DOCKER_CLI_INSTALL_MODE=never olduğu için otomatik kurulum atlandı."
        return 1
    fi

    if [[ "$WSL2" == true && "$mode" != "always" ]]; then
        warn "WSL2 ortamında Docker CLI bulunamadı. Öncelik Docker Desktop WSL Integration olmalı; otomatik APT kurulumu için --install-docker-cli veya DOCKER_CLI_INSTALL=always kullanın."
        return 1
    fi

    install_docker_cli_from_apt
}

ensure_docker_daemon_running() {
    if ! docker_cli_healthy; then
        return 1
    fi

    if docker info &>/dev/null; then
        return 0
    fi

    warn "Docker daemon çalışmıyor görünüyor; otomatik başlatma denenecek."

    if command -v systemctl &>/dev/null; then
        sudo systemctl start docker >/dev/null 2>&1 || true
    fi

    if ! docker info &>/dev/null && command -v service &>/dev/null; then
        sudo service docker start >/dev/null 2>&1 || true
    fi

    if ! docker info &>/dev/null && command -v powershell.exe &>/dev/null; then
        powershell.exe -NoProfile -Command "Start-Process 'C:\\Program Files\\Docker\\Docker\\Docker Desktop.exe'" >/dev/null 2>&1 || true
        info "Docker Desktop başlatıldı, WSL entegrasyonunun hazır olması bekleniyor (maks. 60sn)..."
        local elapsed=0
        while (( elapsed < 60 )); do
            if docker info &>/dev/null; then
                ok "Docker daemon erişilebilir duruma geldi."
                return 0
            fi
            sleep 3
            ((elapsed += 3))
        done
        warn "Docker Desktop belirtilen süre içinde hazır hale gelmedi."
    fi

    docker info &>/dev/null
}

ensure_current_user_in_docker_group() {
    local current_user="${USER:-$(id -un 2>/dev/null || true)}"
    [[ -n "$current_user" ]] || return 0

    if ! getent group docker >/dev/null 2>&1; then
        return 0
    fi

    if id -nG "$current_user" 2>/dev/null | tr ' ' '\n' | grep -qx "docker"; then
        return 0
    fi

    if ! command -v sudo >/dev/null 2>&1; then
        warn "Kullanıcı '${current_user}' docker grubunda değil; sudo bulunamadığı için otomatik ekleme atlandı."
        return 0
    fi

    info "Kullanıcı '${current_user}' docker grubuna ekleniyor (usermod -aG docker)."
    if [[ "$NO_INTERACTION" == true ]]; then
        if ! sudo -n usermod -aG docker "$current_user" >/dev/null 2>&1; then
            warn "--ci/--no-interaction modunda docker grubu güncellenemedi (sudo parolasız değil). Manuel komut: sudo usermod -aG docker $current_user"
            return 0
        fi
    else
        if ! sudo usermod -aG docker "$current_user"; then
            warn "Kullanıcı docker grubuna eklenemedi. Manuel komut: sudo usermod -aG docker $current_user"
            return 0
        fi
    fi

    ok "Kullanıcı '${current_user}' docker grubuna eklendi."
    info "Grup üyeliğinin etkili olması için oturumu kapatıp yeniden açın veya 'newgrp docker' çalıştırın."
}

validate_monitoring_mount_paths() {
    local prometheus_cfg="$SCRIPT_DIR/docker_setup/prometheus/prometheus.yml"
    local grafana_provisioning_dir="$SCRIPT_DIR/docker_setup/grafana/provisioning"
    local grafana_dashboards_dir="$SCRIPT_DIR/docker_setup/grafana/dashboards"
    local grafana_datasource_cfg="$SCRIPT_DIR/docker_setup/grafana/provisioning/datasources/prometheus.yml"
    local -a errors=()

    if [[ -d "$prometheus_cfg" ]]; then
        warn "Docker Desktop bug'ı tespit edildi: $prometheus_cfg bir klasör olarak oluşturulmuş. Silinip dosya olarak yeniden oluşturulacak."
        rm -rf "$prometheus_cfg"
    fi

    if [[ ! -e "$prometheus_cfg" ]]; then
        warn "Prometheus konfigürasyon dosyası bulunamadı, varsayılan dosya oluşturuluyor: $prometheus_cfg"
        mkdir -p "$(dirname "$prometheus_cfg")"
        cat > "$prometheus_cfg" <<'EOF'
global:
  scrape_interval: 15s

scrape_configs:
  - job_name: "prometheus"
    static_configs:
      - targets: ["localhost:9090"]
EOF
    elif [[ ! -f "$prometheus_cfg" ]]; then
        errors+=("Dosya bekleniyordu ancak farklı tipte: $prometheus_cfg")
    fi

    if [[ ! -e "$grafana_provisioning_dir" ]]; then
        warn "Grafana provisioning dizini bulunamadı, oluşturuluyor: $grafana_provisioning_dir"
        mkdir -p "$grafana_provisioning_dir"
    elif [[ ! -d "$grafana_provisioning_dir" ]]; then
        errors+=("Dizin bekleniyordu ancak farklı tipte: $grafana_provisioning_dir")
    fi

    if [[ ! -e "$grafana_dashboards_dir" ]]; then
        warn "Grafana dashboards dizini bulunamadı, oluşturuluyor: $grafana_dashboards_dir"
        mkdir -p "$grafana_dashboards_dir"
    elif [[ ! -d "$grafana_dashboards_dir" ]]; then
        errors+=("Dizin bekleniyordu ancak farklı tipte: $grafana_dashboards_dir")
    fi

    if [[ -d "$grafana_provisioning_dir" ]] && [[ ! -e "$grafana_datasource_cfg" ]]; then
        warn "Grafana Prometheus datasource tanımı bulunamadı, varsayılan dosya oluşturuluyor: $grafana_datasource_cfg"
        mkdir -p "$(dirname "$grafana_datasource_cfg")"
        cat > "$grafana_datasource_cfg" <<'EOF'
apiVersion: 1
datasources:
  - name: Prometheus
    type: prometheus
    access: proxy
    url: http://prometheus:9090
    isDefault: true
EOF
    elif [[ -e "$grafana_datasource_cfg" ]] && [[ ! -f "$grafana_datasource_cfg" ]]; then
        errors+=("Dosya bekleniyordu ancak farklı tipte: $grafana_datasource_cfg")
    fi

    if (( ${#errors[@]} > 0 )); then
        printf ' - %s\n' "${errors[@]}" >&2
        fail "Docker Compose monitoring bind-mount sanity check başarısız. Lütfen eksik/yanlış tipte yolları düzeltin."
    fi
}

start_docker_services_or_fail() {
    local -a compose_cmd=()
    while [[ $# -gt 0 ]]; do
        if [[ "$1" == "--" ]]; then
            shift
            break
        fi
        compose_cmd+=("$1")
        shift
    done
    local -a services=("$@")
    local stderr_file
    stderr_file=$(mktemp)

    if ! maybe_reset_postgres_volume_after_password_hardening "${compose_cmd[@]}" -- "${services[@]}"; then
        fail "DB parola hardening sonrası PostgreSQL volume sıfırlanamadı; eski kimlik bilgileri nedeniyle kurulum güvenli şekilde durduruldu."
    fi

    if "${compose_cmd[@]}" up -d "${services[@]}" 2>"$stderr_file"; then
        rm -f "$stderr_file"
        return 0
    fi

    local compose_err=""
    compose_err="$(<"$stderr_file")"
    rm -f "$stderr_file"

    if [[ "$compose_err" == *"permission denied while trying to connect to the Docker daemon socket"* ]]; then
        fail "Docker daemon socket erişim hatası (permission denied). Windows'ta Docker Desktop > Settings > Resources > WSL Integration bölümünden Ubuntu entegrasyonunu açıp Apply & restart yapın."
    fi

    fail "Docker servisleri başlatılamadı: ${services[*]}. Logları kontrol edip tekrar deneyin."
}

wait_for_compose_services_health() {
    local -a compose_cmd=()
    while [[ $# -gt 0 ]]; do
        if [[ "$1" == "--" ]]; then
            shift
            break
        fi
        compose_cmd+=("$1")
        shift
    done
    local -a services=("$@")
    local service_name=""
    local container_id=""
    local state=""

    [[ ${#services[@]} -gt 0 ]] || return 0

    if ! command -v docker &>/dev/null; then
        warn "Docker CLI bulunamadı; compose health bekleme adımı atlanıyor."
        return 0
    fi

    info "Docker healthcheck senkronizasyonu başlatıldı (${services[*]})..."
    for service_name in "${services[@]}"; do
        container_id="$("${compose_cmd[@]}" ps -q "$service_name" 2>/dev/null | head -n1 || true)"
        if [[ -z "$container_id" ]]; then
            warn "Servis için container ID alınamadı: ${service_name} (health bekleme atlandı)."
            continue
        fi

        for _ in {1..45}; do
            state="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$container_id" 2>/dev/null || echo unknown)"
            case "$state" in
                healthy|running)
                    ok "Servis hazır: ${service_name} (${state})"
                    break
                    ;;
                unhealthy|exited|dead)
                    warn "Servis sağlıksız durumda: ${service_name} (${state})"
                    return 1
                    ;;
            esac
            sleep 2
        done

        state="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$container_id" 2>/dev/null || echo unknown)"
        if [[ "$state" != "healthy" && "$state" != "running" ]]; then
            warn "Servis health timeout: ${service_name} (son durum: ${state})"
            return 1
        fi
    done

    return 0
}

maybe_reset_postgres_volume_after_password_hardening() {
    local -a compose_cmd=()
    while [[ $# -gt 0 ]]; do
        if [[ "$1" == "--" ]]; then
            shift
            break
        fi
        compose_cmd+=("$1")
        shift
    done
    local -a services=("$@")
    local reset_attempted=false

    if [[ "$DB_PASSWORD_HARDENED" != true || "$POSTGRES_VOLUME_RESET_DONE" == true ]]; then
        return 0
    fi

    local includes_postgres=false
    for service in "${services[@]}"; do
        if [[ "$service" == "postgres" ]]; then
            includes_postgres=true
            break
        fi
    done
    [[ "$includes_postgres" == true ]] || return 0

    local env_file="$SCRIPT_DIR/.env"
    local sidar_env="development"
    if [[ -f "$env_file" ]]; then
        sidar_env=$(read_env_value_from_file "SIDAR_ENV" "$env_file")
    fi
    sidar_env=$(echo "${sidar_env:-development}" | tr -d '"'\''[:space:]')

    local allow_production_volume_reset="${ALLOW_PRODUCTION_DB_VOLUME_RESET:-0}"
    case "$sidar_env" in
        development|dev|local|test)
            ;;
        production|prod|staging|preprod)
            if [[ "$allow_production_volume_reset" != "1" ]]; then
                warn "DB parola hardening algılandı ancak SIDAR_ENV=${sidar_env} olduğu için PostgreSQL volume otomatik sıfırlanmadı (güvenlik freni)."
                warn "Sadece bilinçli operasyonlarda ALLOW_PRODUCTION_DB_VOLUME_RESET=1 ile açıkça izin verin."
                return 0
            fi
            warn "ALLOW_PRODUCTION_DB_VOLUME_RESET=1 verildi; SIDAR_ENV=${sidar_env} için PostgreSQL volume sıfırlama güvenlik freni operatör onayıyla bypass edildi."
            ;;
        *)
            warn "SIDAR_ENV='${sidar_env}' tanınmadı; veri kaybını önlemek için PostgreSQL volume otomatik sıfırlanmadı."
            return 0
            ;;
    esac

    if [[ "${AUTO_RESET_POSTGRES_VOLUME_ON_PASSWORD_CHANGE:-1}" != "1" ]]; then
        warn "AUTO_RESET_POSTGRES_VOLUME_ON_PASSWORD_CHANGE=1 olmadığı için PostgreSQL volume otomatik sıfırlanmadı."
        return 0
    fi

    if ! command -v docker &>/dev/null; then
        warn "DB parola hardening algılandı ancak docker CLI bulunamadı; PostgreSQL volume otomatik sıfırlanamadı."
        return 0
    fi

    local -a candidate_volume_suffixes=()
    local compose_project_name="${COMPOSE_PROJECT_NAME:-}"
    local compose_arg=""
    local consume_next_as_project_name=false
    for compose_arg in "${compose_cmd[@]}"; do
        if [[ "$consume_next_as_project_name" == true ]]; then
            compose_project_name="$compose_arg"
            consume_next_as_project_name=false
            continue
        fi
        case "$compose_arg" in
            -p|--project-name)
                consume_next_as_project_name=true
                ;;
            -p=*|--project-name=*)
                compose_project_name="${compose_arg#*=}"
                ;;
        esac
    done

    if [[ -z "$compose_project_name" ]]; then
        compose_project_name=$(read_env_value_from_file "COMPOSE_PROJECT_NAME" "$env_file")
    fi
    compose_project_name=$(echo "${compose_project_name:-}" | tr -d '"'\''[:space:]')
    if mapfile -t compose_volumes < <("${compose_cmd[@]}" config --volumes 2>/dev/null); then
        for volume_name in "${compose_volumes[@]}"; do
            if [[ "$volume_name" =~ (^|_)postgres_data$ ]]; then
                candidate_volume_suffixes+=("$volume_name")
            fi
        done
    fi

    # docker compose config --volumes çoğunlukla kısa adı (örn: postgres_data) döndürür.
    # Gerçek Docker volume adı ise çoğu zaman proje önekli olur (örn: sidar_postgres_data).
    # Bu nedenle kısa adları suffix olarak ele alıp docker volume ls çıktısından gerçek adları çözüyoruz.
    if [[ ${#candidate_volume_suffixes[@]} -eq 0 ]]; then
        candidate_volume_suffixes+=("postgres_data")
    fi

    local -a existing_pg_volumes=()
    if mapfile -t docker_volume_names < <(docker volume ls --format '{{.Name}}' 2>/dev/null); then
        for docker_volume_name in "${docker_volume_names[@]}"; do
            for volume_suffix in "${candidate_volume_suffixes[@]}"; do
                if [[ -n "$compose_project_name" ]]; then
                    if [[ "$docker_volume_name" == "$volume_suffix" || "$docker_volume_name" == "${compose_project_name}_${volume_suffix}" ]]; then
                        existing_pg_volumes+=("$docker_volume_name")
                        break
                    fi
                elif [[ "$docker_volume_name" == "$volume_suffix" || "$docker_volume_name" == *_"$volume_suffix" ]]; then
                    existing_pg_volumes+=("$docker_volume_name")
                    break
                fi
            done
        done
    fi

    if [[ ${#existing_pg_volumes[@]} -gt 1 ]]; then
        local -A unique_existing_pg_volumes=()
        local -a deduped_existing_pg_volumes=()
        for volume_name in "${existing_pg_volumes[@]}"; do
            if [[ -z "${unique_existing_pg_volumes[$volume_name]:-}" ]]; then
                unique_existing_pg_volumes["$volume_name"]=1
                deduped_existing_pg_volumes+=("$volume_name")
            fi
        done
        existing_pg_volumes=("${deduped_existing_pg_volumes[@]}")
    fi

    if [[ ${#existing_pg_volumes[@]} -eq 0 ]]; then
        info "DB parola hardening sonrası silinecek PostgreSQL volume bulunamadı; temiz başlangıç varsayıldı."
        POSTGRES_VOLUME_RESET_DONE=true
        return 0
    fi

    local should_reset="E"
    if [[ "$AUTO_RESET_POSTGRES_VOLUMES" == "true" ]]; then
        should_reset="E"
        info "AUTO_INSTALL: RESET_DB=true olduğu için PostgreSQL volume sıfırlama onayı otomatik verildi."
    elif [[ "$AUTO_RESET_POSTGRES_VOLUMES" == "false" ]]; then
        should_reset="H"
        info "AUTO_INSTALL: RESET_DB=false olduğu için PostgreSQL volume sıfırlama atlandı."
    elif [[ "$NO_INTERACTION" != true ]]; then
        should_reset=$(prompt_yes_no_with_timeout_default_yes \
            "DB şifresi güncellendi. Eski PostgreSQL volume'leri (${existing_pg_volumes[*]}) şimdi sıfırlansın mı? [E/h] ")
    fi

    local strict_postgres_reset_on_password_change="${STRICT_POSTGRES_VOLUME_RESET_ON_PASSWORD_CHANGE:-${STRICT_POSTGRES_VOLUME_RESET:-0}}"

    case "${should_reset:-E}" in
        E|e)
            reset_attempted=true
            warn "DB parola hardening sonrası eski kimlik bilgisi riskine karşı PostgreSQL volume sıfırlanıyor: ${existing_pg_volumes[*]}"
            if ! backup_postgres_before_volume_reset "${compose_cmd[@]}"; then
                warn "PostgreSQL yedeği alınamadı; volume yine de sıfırlanıyor (geliştirme ortamı — veri kurtarılamaz durumda)."
            fi
            local -a postgres_service_container_ids=()
            if mapfile -t postgres_service_container_ids < <("${compose_cmd[@]}" ps -q postgres 2>/dev/null); then
                if [[ ${#postgres_service_container_ids[@]} -gt 0 ]]; then
                    warn "postgres servisine ait mevcut container(lar) doğrudan kaldırılıyor."
                    docker stop "${postgres_service_container_ids[@]}" >/dev/null 2>&1 || true
                    docker rm -f "${postgres_service_container_ids[@]}" >/dev/null 2>&1 || warn "postgres container kaldırma adımı tamamlanamadı."
                fi
            fi
            if ! "${compose_cmd[@]}" down --volumes --remove-orphans >/dev/null 2>&1; then
                warn "docker compose down --volumes --remove-orphans komutu başarısız oldu; volume kilidi manuel olarak çözülecek."
            fi
            if [[ "$FORCE_POSTGRES_VOLUME_CLEANUP" == true ]]; then
                warn "Agresif container temizliği etkin: projeye ait asılı kalan container'lar zorla kaldırılıyor."
                local -a project_container_ids=()
                if [[ -n "$compose_project_name" ]]; then
                    if mapfile -t project_container_ids < <(docker ps -a --filter "label=com.docker.compose.project=${compose_project_name}" --format '{{.ID}}' 2>/dev/null); then
                        if [[ ${#project_container_ids[@]} -gt 0 ]]; then
                            docker rm -f "${project_container_ids[@]}" >/dev/null 2>&1 || warn "Projeye ait bazı container'lar zorla kaldırılamadı."
                        fi
                    fi
                fi
            fi
            local removed_any=false
            for volume_name in "${existing_pg_volumes[@]}"; do
                local -a volume_container_ids=()
                if mapfile -t volume_container_ids < <(docker ps -a --filter "volume=${volume_name}" --format '{{.ID}}' 2>/dev/null); then
                    if [[ ${#volume_container_ids[@]} -gt 0 ]]; then
                        warn "Volume bağlı container(lar) bulundu (${volume_name}); zorla kaldırılıyor."
                        docker rm -f "${volume_container_ids[@]}" >/dev/null 2>&1 || warn "Volume kullanan container'lar kaldırılamadı: ${volume_name}"
                    fi
                fi
                if [[ "$FORCE_POSTGRES_VOLUME_CLEANUP" == true ]]; then
                    local -a dangling_by_name_container_ids=()
                    if mapfile -t dangling_by_name_container_ids < <(docker ps -a --filter "name=${volume_name}" --format '{{.ID}}' 2>/dev/null); then
                        if [[ ${#dangling_by_name_container_ids[@]} -gt 0 ]]; then
                            warn "Agresif mod: volume adıyla eşleşen asılı container(lar) kaldırılıyor (${volume_name})."
                            docker rm -f "${dangling_by_name_container_ids[@]}" >/dev/null 2>&1 || warn "Volume adına göre bulunan container'lar kaldırılamadı: ${volume_name}"
                        fi
                    fi
                fi
                if docker volume rm "$volume_name" -f >/dev/null 2>&1; then
                    ok "PostgreSQL volume temizlendi: ${volume_name}"
                    removed_any=true
                else
                    warn "PostgreSQL volume otomatik silinemedi (${volume_name}). Geliştirme ortamında manuel olarak sıfırlayın."
                fi
            done
            if [[ "$removed_any" == true ]]; then
                POSTGRES_VOLUME_RESET_DONE=true
            fi
            ;;
        *)
            warn "PostgreSQL volume sıfırlama kullanıcı tercihiyle atlandı; eski parola kaynaklı auth hatası oluşabilir."
            ;;
    esac

    if [[ "$POSTGRES_VOLUME_RESET_DONE" == true ]]; then
        return 0
    fi

    if [[ "$reset_attempted" == true && "${DB_PASSWORD_HARDENED:-false}" == true ]]; then
        warn "Volume temizliği tamamlanamadı; kilitli Docker artefaktlarını çözmek için docker system prune -f çalıştırılıyor."
        docker system prune -f >/dev/null 2>&1 || warn "docker system prune -f adımı tamamlanamadı."

        local removed_after_prune=false
        for volume_name in "${existing_pg_volumes[@]}"; do
            if docker volume rm "$volume_name" -f >/dev/null 2>&1; then
                ok "PostgreSQL volume prune sonrası temizlendi: ${volume_name}"
                removed_after_prune=true
            fi
        done
        if [[ "$removed_after_prune" == true ]]; then
            POSTGRES_VOLUME_RESET_DONE=true
            return 0
        fi
    fi

    warn "PostgreSQL volume sıfırlama tamamlanamadı; bağlantı hatası olursa docker compose down --volumes --remove-orphans && docker volume rm sidar_postgres_data -f komutlarını çalıştırın."
    if [[ "$reset_attempted" == true ]]; then
        if [[ "$strict_postgres_reset_on_password_change" == "1" ]]; then
            return 1
        fi
        warn "Kurulum durdurulmadan devam ediliyor (STRICT_POSTGRES_VOLUME_RESET=1 veya STRICT_POSTGRES_VOLUME_RESET_ON_PASSWORD_CHANGE=1 ayarlanırsa bu durumda fail edilir)."
        return 0
    fi
    return 0
}

backup_postgres_before_volume_reset() {
    local -a compose_cmd=("$@")
    local postgres_container_id=""
    local backup_dir="$SCRIPT_DIR/backups"
    local backup_file=""
    local dump_error_file=""
    local dump_ok=false
    local candidate_db_user=""
    local -a candidate_db_users=()
    local candidate_db_users_seen="|"
    local env_db_user=""
    local env_postgres_user=""

    if ! command -v docker &>/dev/null; then
        warn "Docker CLI bulunamadı; volume sıfırlama öncesi PostgreSQL yedeği alınamadı."
        return 0
    fi

    if mapfile -t _postgres_container_ids < <("${compose_cmd[@]}" ps -q postgres 2>/dev/null); then
        if [[ ${#_postgres_container_ids[@]} -gt 0 ]]; then
            postgres_container_id="${_postgres_container_ids[0]}"
        fi
    fi

    if [[ -z "$postgres_container_id" ]]; then
        warn "postgres container bulunamadı; volume sıfırlama öncesi pg_dumpall yedeği alınamadı (kurulum otomatik devam edecek)."
        return 1
    fi

    mkdir -p "$backup_dir"
    backup_file="$backup_dir/postgres_before_volume_reset_$(date +%Y%m%d_%H%M%S).sql"
    dump_error_file="$(mktemp)"

    # Önce container içi yapılandırmadan ve .env dosyasından özel kullanıcı adlarını dene.
    env_postgres_user="$(docker exec "$postgres_container_id" sh -lc 'printenv POSTGRES_USER' 2>/dev/null || true)"
    env_postgres_user="$(echo "$env_postgres_user" | tr -d '"'\''[:space:]')"
    if [[ -n "$env_postgres_user" ]] && [[ "$candidate_db_users_seen" != *"|${env_postgres_user}|"* ]]; then
        candidate_db_users+=("$env_postgres_user")
        candidate_db_users_seen+="${env_postgres_user}|"
    fi

    if [[ -n "${ENV_FILE:-}" && -f "${ENV_FILE:-}" ]]; then
        env_postgres_user="$(read_env_value_from_file "POSTGRES_USER" "$ENV_FILE")"
        env_postgres_user="$(echo "$env_postgres_user" | tr -d '"'\''[:space:]')"
        if [[ -n "$env_postgres_user" ]] && [[ "$candidate_db_users_seen" != *"|${env_postgres_user}|"* ]]; then
            candidate_db_users+=("$env_postgres_user")
            candidate_db_users_seen+="${env_postgres_user}|"
        fi
        local env_database_url=""
        env_database_url="$(read_env_value_from_file "DATABASE_URL" "$ENV_FILE")"
        if [[ "$env_database_url" =~ ^postgresql(\+asyncpg)?://([^:@/]+):([^@/]+)@ ]]; then
            env_db_user="${BASH_REMATCH[2]}"
        fi
        env_db_user="$(echo "$env_db_user" | tr -d '"'\''[:space:]')"
        if [[ -n "$env_db_user" ]] && [[ "$candidate_db_users_seen" != *"|${env_db_user}|"* ]]; then
            candidate_db_users+=("$env_db_user")
            candidate_db_users_seen+="${env_db_user}|"
        fi
    fi

    # Varsayılan fallback kullanıcılarını en sona ekle.
    if [[ "$candidate_db_users_seen" != *"|postgres|"* ]]; then
        candidate_db_users+=("postgres")
        candidate_db_users_seen+="postgres|"
    fi
    if [[ "$candidate_db_users_seen" != *"|sidar|"* ]]; then
        candidate_db_users+=("sidar")
        candidate_db_users_seen+="sidar|"
    fi

    for candidate_db_user in "${candidate_db_users[@]}"; do
        if docker exec "$postgres_container_id" sh -lc "pg_dumpall -U ${candidate_db_user}" >"$backup_file" 2>"$dump_error_file"; then
            local backup_size=0
            backup_size=$(stat -c%s "$backup_file" 2>/dev/null || echo 0)
            if [[ -s "$backup_file" && "$backup_size" -gt 512 ]] && grep -qE '^(CREATE|INSERT|--.*PostgreSQL)' "$backup_file" 2>/dev/null; then
                dump_ok=true
                break
            fi
        fi
    done

    if [[ "$dump_ok" == true ]]; then
        ok "PostgreSQL hızlı yedek alındı: ${backup_file}"
        info "Eski verileriniz ${backup_file} olarak kaydedildi, volume sıfırlanıyor."
        rm -f "$dump_error_file"
        return 0
    fi

    rm -f "$backup_file"
    warn "Volume sıfırlama öncesi pg_dumpall yedeği alınamadı. Detay: $(cat "$dump_error_file" 2>/dev/null || echo 'bilinmeyen_hata')"
    rm -f "$dump_error_file"
    return 1
}

wait_for_postgres_ready_after_docker_start() {
    local db_host="$1"
    local db_port="$2"
    local db_user="$3"
    local db_name="$4"
    local db_password="$5"
    local max_attempts="${6:-30}"
    local sleep_seconds="${7:-2}"
    local stable_auth_checks_required="${POSTGRES_READY_STABLE_AUTH_CHECKS:-2}"
    local stable_auth_checks_passed=0

    info "PostgreSQL'in tabloları ve kullanıcıları oluşturması bekleniyor (${db_host}:${db_port}/${db_name})..."
    for ((attempt=1; attempt<=max_attempts; attempt++)); do
        if pg_isready -h "$db_host" -p "$db_port" -U "$db_user" -d "$db_name" >/dev/null 2>&1; then
            local auth_rc=0
            verify_postgres_auth "$db_host" "$db_port" "$db_user" "$db_name" "$db_password" || auth_rc=$?
            case "$auth_rc" in
                0)
                    ((stable_auth_checks_passed+=1))
                    if (( stable_auth_checks_passed >= stable_auth_checks_required )); then
                        ok "PostgreSQL tam olarak hazır ve kimlik doğrulaması başarılı."
                        return 0
                    fi
                    info "Kimlik doğrulaması başarılı (denge kontrolü ${stable_auth_checks_passed}/${stable_auth_checks_required}); kısa bir doğrulama daha yapılacak..."
                    ;;
                10)
                    stable_auth_checks_passed=0
                    warn "PostgreSQL henüz hazır değil veya parola senkronize değil (${attempt}/${max_attempts}): ${POSTGRES_AUTH_CHECK_ERROR:-password authentication failed}"
                    ;;
                2)
                    stable_auth_checks_passed=0
                    warn "PostgreSQL erişilebilir, ancak psql/asyncpg ile auth doğrulaması yapılamadı (${attempt}/${max_attempts})."
                    warn "Auth doğrulaması yapılamadığından DB hazır kabul ediliyor; Alembic adımında yeniden doğrulanacak."
                    return 0
                    ;;
                *)
                    stable_auth_checks_passed=0
                    warn "PostgreSQL bağlantı kontrolü başarısız (${attempt}/${max_attempts}): ${POSTGRES_AUTH_CHECK_ERROR:-bilinmeyen_hata}"
                    ;;
            esac
        else
            stable_auth_checks_passed=0
            info "⏳ Veritabanı başlatılıyor... (${attempt}/${max_attempts})"
        fi
        sleep "$sleep_seconds"
    done

    warn "PostgreSQL ${max_attempts} denemede tam hazır hale gelmedi."
    return 1
}

wait_for_redis_ready_after_docker_start() {
    local env_file="$SCRIPT_DIR/.env"
    local redis_url=""
    local redis_host="localhost"
    local redis_port="6379"
    local -a python_cmd=()

    if [[ -f "$env_file" ]]; then
        redis_url=$(read_env_value_from_file "REDIS_URL" "$env_file")
    fi
    if [[ -z "$redis_url" ]]; then
        redis_url="redis://localhost:6379/0"
    fi

    if command -v python3 &>/dev/null; then
        python_cmd=(python3)
    elif command -v python &>/dev/null; then
        python_cmd=(python)
    fi

    if [[ ${#python_cmd[@]} -gt 0 ]]; then
        if mapfile -t redis_conn < <("${python_cmd[@]}" - "$redis_url" <<'PY'
from urllib.parse import urlparse
import sys

url = (sys.argv[1] or "").strip() or "redis://localhost:6379/0"
parsed = urlparse(url)
print(parsed.hostname or "localhost")
print(str(parsed.port or 6379))
PY
); then
            redis_host="${redis_conn[0]:-localhost}"
            redis_port="${redis_conn[1]:-6379}"
        fi
    fi

    info "Redis hazır olana kadar bekleniyor (${redis_host}:${redis_port})..."
    for _ in {1..30}; do
        if command -v redis-cli &>/dev/null; then
            if redis-cli -h "$redis_host" -p "$redis_port" ping 2>/dev/null | grep -q "PONG"; then
                ok "Redis erişilebilir hale geldi."
                return 0
            fi
        elif command -v timeout &>/dev/null; then
            # Hafif fallback: her döngüde python process spawn etmek yerine bash /dev/tcp kullan.
            if timeout 1 bash -c "</dev/tcp/$redis_host/$redis_port" >/dev/null 2>&1; then
                ok "Redis erişilebilir hale geldi."
                return 0
            fi
        elif [[ ${#python_cmd[@]} -gt 0 ]]; then
            # timeout yoksa son çare olarak tek TCP connect kontrolü.
            if "${python_cmd[@]}" - "$redis_host" "$redis_port" <<'PY' >/dev/null 2>&1
import socket
import sys
host = sys.argv[1]
port = int(sys.argv[2])
with socket.create_connection((host, port), timeout=1.0):
    pass
PY
            then
                ok "Redis erişilebilir hale geldi."
                return 0
            fi
        else
            warn "redis-cli veya python bulunamadı; Redis hazır kontrolü atlanıyor."
            return 0
        fi
        sleep 2
    done

    warn "Redis ${redis_host}:${redis_port} 60 saniye içinde hazır olmadı."
    return 1
}

verify_postgres_auth_with_psql() {
    local db_host="$1"
    local db_port="$2"
    local db_user="$3"
    local db_name="$4"
    local db_password="$5"
    POSTGRES_AUTH_CHECK_ERROR=""

    if ! command -v psql &>/dev/null; then
        POSTGRES_AUTH_CHECK_ERROR="psql_missing"
        return 2
    fi

    local psql_output=""
    if psql_output=$(
        PGPASSWORD="$db_password" psql \
            "host=$db_host port=$db_port user=$db_user dbname=$db_name connect_timeout=5" \
            -tAc "SELECT 1" 2>&1
    ); then
        return 0
    fi

    POSTGRES_AUTH_CHECK_ERROR="$psql_output"
    if [[ "$psql_output" == *"password authentication failed"* ]]; then
        return 10
    fi
    return 1
}

verify_postgres_auth_with_python() {
    local db_host="$1"
    local db_port="$2"
    local db_user="$3"
    local db_name="$4"
    local db_password="$5"
    local -a py_cmd=()
    local py_output=""
    POSTGRES_AUTH_CHECK_ERROR=""

    if command -v python3 &>/dev/null; then
        py_cmd=(python3)
    elif command -v python &>/dev/null; then
        py_cmd=(python)
    else
        POSTGRES_AUTH_CHECK_ERROR="python_missing"
        return 2
    fi

    if py_output=$("${py_cmd[@]}" - "$db_host" "$db_port" "$db_user" "$db_name" "$db_password" <<'PY' 2>&1
import asyncio
import sys

host, port, user, database, password = sys.argv[1:6]

async def main():
    try:
        import asyncpg
    except Exception as exc:
        print(f"asyncpg_missing:{exc}")
        raise SystemExit(2)

    try:
        conn = await asyncpg.connect(
            host=host,
            port=int(port),
            user=user,
            password=password,
            database=database,
            timeout=5,
        )
        try:
            await conn.fetchval("SELECT 1")
        finally:
            await conn.close()
        print("ok")
        raise SystemExit(0)
    except Exception as exc:
        print(str(exc))
        raise

try:
    asyncio.run(main())
except SystemExit:
    raise
except Exception:
    raise SystemExit(1)
PY
); then
        return 0
    fi

    local py_rc=$?
    POSTGRES_AUTH_CHECK_ERROR="$py_output"
    if [[ "$py_output" == *"password authentication failed"* || "$py_output" == *"InvalidPasswordError"* ]]; then
        return 10
    fi
    if [[ "$py_rc" -eq 2 ]]; then
        return 2
    fi
    return 1
}

verify_postgres_auth() {
    local db_host="$1"
    local db_port="$2"
    local db_user="$3"
    local db_name="$4"
    local db_password="$5"

    verify_postgres_auth_with_psql "$db_host" "$db_port" "$db_user" "$db_name" "$db_password"
    local auth_rc=$?
    if [[ "$auth_rc" -ne 2 ]]; then
        return "$auth_rc"
    fi

    verify_postgres_auth_with_python "$db_host" "$db_port" "$db_user" "$db_name" "$db_password"
    return $?
}

try_recover_postgres_password_with_alter_user() {
    local db_host="$1"
    local db_port="$2"
    local db_user="$3"
    local db_name="$4"
    local new_password="$5"
    shift 5
    local -a old_password_candidates=("$@")

    local candidate=""
    local escape_sql_literal_password="${new_password//\'/\'\'}"
    local escape_sql_identifier_user="${db_user//\"/\"\"}"
    local -A seen_candidates=()

    for candidate in "${old_password_candidates[@]}"; do
        [[ -n "$candidate" ]] || continue
        if [[ -n "${seen_candidates[$candidate]:-}" ]]; then
            continue
        fi
        seen_candidates["$candidate"]=1
        if [[ "$candidate" == "$new_password" ]]; then
            continue
        fi

        if verify_postgres_auth "$db_host" "$db_port" "$db_user" "$db_name" "$candidate"; then
            info "Eski parola ile erişim doğrulandı; ALTER USER ile parola güncellemesi deneniyor."

            if command -v psql &>/dev/null; then
                if PGPASSWORD="$candidate" psql \
                    "host=$db_host port=$db_port user=$db_user dbname=$db_name connect_timeout=5" \
                    -v ON_ERROR_STOP=1 \
                    -c "ALTER USER \"${escape_sql_identifier_user}\" WITH PASSWORD '${escape_sql_literal_password}';" \
                    >/dev/null 2>&1; then
                    ok "ALTER USER ile PostgreSQL parolası güncellendi."
                    return 0
                fi
            fi

            local -a py_cmd=()
            if command -v python3 &>/dev/null; then
                py_cmd=(python3)
            elif command -v python &>/dev/null; then
                py_cmd=(python)
            fi

            if [[ ${#py_cmd[@]} -gt 0 ]]; then
                if "${py_cmd[@]}" - "$db_host" "$db_port" "$db_user" "$db_name" "$candidate" "$new_password" <<'PY' >/dev/null 2>&1
import asyncio
import sys

host, port, user, database, old_password, new_password = sys.argv[1:7]

async def main():
    import asyncpg
    conn = await asyncpg.connect(
        host=host,
        port=int(port),
        user=user,
        password=old_password,
        database=database,
        timeout=5,
    )
    try:
        await conn.execute(f'ALTER USER "{user.replace(chr(34), chr(34)*2)}" WITH PASSWORD $1', new_password)
    finally:
        await conn.close()

asyncio.run(main())
PY
                then
                    ok "ALTER USER (python/asyncpg) ile PostgreSQL parolası güncellendi."
                    return 0
                fi
            fi
        fi
    done

    return 1
}

# ── Argümanlar ────────────────────────────────────────────────────────────────
# Geliştirme bağımlılıkları Sidar self-healing için standart kurulumun parçasıdır.
INSTALL_DEV=true
UPGRADE_LOCK=false
ALLOW_FULL_ACCESS=false
FORCE_CPU=false
SKIP_MODELS=false
DOWNLOAD_MODELS=true
FORCE_REACT_BUILD=true
INSTALL_KUBERNETES=false
HELM_RELEASE_NAME="sidar"
HELM_NAMESPACE="sidar"
HELM_VALUES_FILE=""
RUN_SMOKE_TESTS_MODE="always"
RUN_AUDIT=true
NO_INTERACTION=false
DOCKER_ONLY=false
APP_RUNTIME_MODE="ask"
ENABLE_AUDIO=true
FORCE_POSTGRES_VOLUME_CLEANUP=false
AUTO_INSTALL=false
AUTO_RUNTIME_MODE="ask"
AUTO_START_DOCKER_SERVICES="ask"
AUTO_RESET_POSTGRES_VOLUMES="ask"
AUTO_ENV_TYPE="ask"
AUTO_OPEN_VSCODE="ask"
OFFLINE_MODE=false
OFFLINE_PACKAGES_DIR=""
DOCKER_CLI_INSTALL_MODE="${DOCKER_CLI_INSTALL:-auto}"
PLAYWRIGHT_BROWSERS_MODE="auto"
CLI_MODE_RAW=""
CLI_ENV_RAW=""
CLI_RESET_POSTGRES_VOLUMES="ask"
CLI_START_DOCKER_SERVICES="ask"
CLI_OPEN_VSCODE="ask"
SILENT_MODE=false
REACT_UI_STATUS="atlandı"
MIGRATION_STATUS="atlandı"
SMOKE_TEST_STATUS="atlandı"
AUDIT_STATUS="atlandı"
MIGRATION_DOCKER_POLICY="auto"
DOCKER_DB_SERVICES_STARTED=false
DB_PASSWORD_HARDENED=false
POSTGRES_VOLUME_RESET_DONE=false
PRE_HARDEN_DB_PASSWORD=""
AUDIO_SESSION_RESTART_RECOMMENDED=false
WSL2=false
WSLCONFIG_CHANGED=false
ENV_API_KEYS_TOTAL=0
ENV_API_KEYS_FILLED=0
ENV_API_KEYS_MISSING=()
INSTALL_SUBCOMMAND="full"
for arg in "$@"; do
    case "$arg" in
        --no-dev) warn "--no-dev artık desteklenmiyor; self-healing için dev bağımlılıkları standart kurulumda kalacak." ; INSTALL_DEV=true ;;
        --upgrade-lock) UPGRADE_LOCK=true ;;
        --i-understand-full-access) ALLOW_FULL_ACCESS=true ;;
        doctor|prepare-system|sync-deps|provision-models|smoke) INSTALL_SUBCOMMAND="$arg" ;;
        --cpu)  FORCE_CPU=true ;;
        --kubernetes|--helm) INSTALL_KUBERNETES=true ;;
        --silent) SILENT_MODE=true ;;
        --auto) AUTO_INSTALL=true ;;
        --skip-models) SKIP_MODELS=true ;;
        --download-models) DOWNLOAD_MODELS=true ;;
        --build-ui) FORCE_REACT_BUILD=true ;;
        --ci|--no-interaction|--non-interactive|--headless|--yes|-y) NO_INTERACTION=true ;;
        --mode=*) CLI_MODE_RAW="${arg#*=}" ;;
        --env=*) CLI_ENV_RAW="${arg#*=}" ;;
        --reset-db) CLI_RESET_POSTGRES_VOLUMES="true" ;;
        --no-reset-db) CLI_RESET_POSTGRES_VOLUMES="false" ;;
        --start-services) CLI_START_DOCKER_SERVICES="true" ;;
        --no-start-services) CLI_START_DOCKER_SERVICES="false" ;;
        --vscode) CLI_OPEN_VSCODE="true" ;;
        --no-vscode) CLI_OPEN_VSCODE="false" ;;
        --with-browsers) PLAYWRIGHT_BROWSERS_MODE="always" ;;
        --skip-browsers) PLAYWRIGHT_BROWSERS_MODE="never" ;;
        --offline|--air-gapped) OFFLINE_MODE=true ;;
        --install-docker-cli) DOCKER_CLI_INSTALL_MODE="always" ;;
        --skip-docker-cli|--no-install-docker-cli) DOCKER_CLI_INSTALL_MODE="never" ;;
        --helm-release=*) HELM_RELEASE_NAME="${arg#*=}" ;;
        --namespace=*) HELM_NAMESPACE="${arg#*=}" ;;
        --values=*) HELM_VALUES_FILE="${arg#*=}" ;;
        --smoke-test) RUN_SMOKE_TESTS_MODE="always" ;;
        --skip-smoke-test) RUN_SMOKE_TESTS_MODE="never" ;;
        --audit) RUN_AUDIT=true ;;
        --docker-only) DOCKER_ONLY=true ;;
        --runtime-mode=local) APP_RUNTIME_MODE="local" ;;
        --runtime-mode=docker) APP_RUNTIME_MODE="docker" ;;
        --force-postgres-volume-cleanup|--force-docker-cleanup) FORCE_POSTGRES_VOLUME_CLEANUP=true ;;
        --enable-audio) ENABLE_AUDIO=true ;;
        --help|-h)
            echo "Kullanım: $0 [doctor|prepare-system|sync-deps|provision-models|smoke] [--upgrade-lock] [--i-understand-full-access] [--cpu] [--docker-only] [--runtime-mode=local|docker] [--silent] [--auto] [--mode=local|docker] [--env=development|production] [--reset-db|--no-reset-db] [--start-services|--no-start-services] [--vscode|--no-vscode] [--with-browsers|--skip-browsers] [--offline|--air-gapped] [--install-docker-cli|--skip-docker-cli] [--force-postgres-volume-cleanup] [--skip-models] [--download-models] [--build-ui] [--kubernetes] [--smoke-test|--skip-smoke-test] [--audit] [--enable-audio] [--ci|--no-interaction|--non-interactive|--headless|--yes|-y]"
            echo "  doctor|prepare-system|sync-deps|provision-models|smoke  Tek kurulum fazını çalıştır"
            echo "  --upgrade-lock  uv.lock dosyasını bilinçli olarak güncelle
  --i-understand-full-access  ACCESS_LEVEL=full için açık risk onayı"
            echo "  --cpu  GPU algılansa bile CPU modunda kur"
            echo "  --docker-only  PostgreSQL/Redis'i hosta kurma, sadece Docker servislerini kullan"
            echo "  --runtime-mode=local|docker  Çalıştırma modu: local=uygulama local + altyapı docker, docker=tüm servisler docker"
            echo "  --force-postgres-volume-cleanup / --force-docker-cleanup  DB parola hardening sonrası kilitli container/volume temizliği için projeye özel agresif docker rm -f adımlarını etkinleştir"
            echo "  --kubernetes / --helm  Yerel kurulum yerine Helm chart ile Kubernetes kurulumu yap"
            echo "  --helm-release=<ad>  Helm release adı (varsayılan: sidar)"
            echo "  --namespace=<ad>  Kubernetes namespace (varsayılan: sidar)"
            echo "  --values=<dosya>  Helm values dosyası (örn. helm/sidar/values-prod.yaml)"
            echo "  --smoke-test  Kurulum sonunda tests/smoke testlerini zorunlu çalıştır"
            echo "  --skip-smoke-test  Kurulum sonunda smoke test çalıştırma"
            echo "  --audit  Kurulum sonunda scripts/check_empty_test_artifacts.sh denetimini çalıştır"
            echo "  --skip-models  Ollama model indirmelerini atla"
            echo "  --download-models  Ollama modellerini varsayılan olarak indir"
            echo "  --build-ui  React Web UI yeniden build et (cache olsa bile)"
            echo "  --enable-audio  WSL2 ses desteğini etkinleştir (varsayılan: kapalı, PulseAudio/WSLg otomatik yapılandırılır)"
            echo "  --ci / --no-interaction  Kullanıcıdan onay istemeden etkileşimsiz kurulum çalıştır"
            echo "  --non-interactive / --headless / --yes / -y  --no-interaction eşdeğeri kısayol bayraklar"
            echo "  --silent  CI/CD için sessiz kurulum: DEBIAN_FRONTEND=noninteractive + güvenli otomatik varsayılanlar"
            echo "            Not: Etkileşimsiz modda sudo parola sorulamaz; root çalıştırın veya önceden sudo doğrulayın."
            echo "  --auto  Etkileşimsiz kurulum için kısa bayrak (AUTO_INSTALL=true)"
            echo "  --mode=local|docker  Çalışma modu seçimini doğrudan belirle"
            echo "  --env=development|production  Kurulum sonrası SIDAR_ENV seçimini doğrudan belirle"
            echo "  --reset-db / --no-reset-db  PostgreSQL volume sıfırlama kararını belirle"
            echo "  --start-services / --no-start-services  Docker servis başlatma kararını belirle"
            echo "  --vscode / --no-vscode  Kurulum sonunda VS Code açma kararını belirle"
            echo "  --with-browsers / --skip-browsers  Playwright Chromium tarayıcı kurulumunu zorla/atla"
            echo "  --offline / --air-gapped  İnternetten script/repo indirmek yerine ./offline_packages altındaki hazır paketleri kullan"
            echo "  --install-docker-cli  Debian/Ubuntu hostta Docker CLI + Buildx + Compose v2 kurulumunu zorla"
            echo "  --skip-docker-cli / --no-install-docker-cli  Docker CLI otomatik kurulumunu atla"
            echo ""
            echo "  Etkileşimsiz çevre değişkenleri:"
            echo "    AUTO_INSTALL=true|false        (true ise --no-interaction gibi davranır)"
            echo "    INSTALL_MODE=1|2|local|docker  (1/local=developer, 2/docker=tam docker)"
            echo "    ENV_TYPE=dev|prod              (SIDAR_ENV seçimi: development/production)"
            echo "    RESET_DB=yes|no                (PostgreSQL volume sıfırlama onayı)"
            echo "    START_DOCKER_SERVICES=yes|no   (migrasyon ve final Docker başlatma onayı)"
            echo "    OPEN_VSCODE=yes|no             (kurulum sonunda VS Code açma onayı)"
            echo "    INSTALL_PLAYWRIGHT_BROWSERS=true|false (Playwright tarayıcı kurulumu zorla/atla)"
            echo "    OFFLINE_INSTALL=true|false     (--offline/--air-gapped eşdeğeri)"
            echo "    DOCKER_CLI_INSTALL=auto|always|never  Docker CLI otomatik kurulum politikası"
            exit 0
            ;;
        *)      warn "Bilinmeyen argüman: $arg (doctor | prepare-system | sync-deps | provision-models | smoke | --upgrade-lock | --i-understand-full-access | --cpu | --docker-only | --runtime-mode=local|docker | --silent | --auto | --mode=... | --env=... | --reset-db | --no-reset-db | --start-services | --no-start-services | --vscode | --no-vscode | --with-browsers | --skip-browsers | --offline | --air-gapped | --install-docker-cli | --skip-docker-cli | --force-postgres-volume-cleanup | --force-docker-cleanup | --kubernetes | --helm | --helm-release=... | --namespace=... | --values=... | --smoke-test | --skip-smoke-test | --audit | --skip-models | --download-models | --build-ui | --enable-audio | --ci | --no-interaction | --non-interactive | --headless | --yes | -y kabul edilir)"; exit 1 ;;
    esac
done

normalize_bool() {
    local value="${1:-}"
    value=$(echo "$value" | tr '[:upper:]' '[:lower:]' | tr -d '[:space:]')
    case "$value" in
        1|true|yes|y|evet|e) echo "true" ;;
        0|false|no|n|hayir|h|hayır) echo "false" ;;
        *) echo "" ;;
    esac
}

resolve_runtime_mode_choice() {
    local raw="${1:-}"
    raw=$(echo "$raw" | tr '[:upper:]' '[:lower:]' | tr -d '[:space:]')
    case "$raw" in
        1|local|dev|developer|gelistirici|geliştirici) echo "local" ;;
        2|docker|full|full-docker|tam-docker) echo "docker" ;;
        *) echo "ask" ;;
    esac
}

resolve_env_type_choice() {
    local raw="${1:-}"
    raw=$(echo "$raw" | tr '[:upper:]' '[:lower:]' | tr -d '[:space:]')
    case "$raw" in
        1|dev|development|gelistirme|geliştirme) echo "development" ;;
        2|prod|production|canli|canlı) echo "production" ;;
        *) echo "ask" ;;
    esac
}

AUTO_INSTALL="$(normalize_bool "${AUTO_INSTALL:-false}")"
if [[ "$AUTO_INSTALL" == "true" ]]; then
    NO_INTERACTION=true
fi

OFFLINE_MODE_RAW="$(normalize_bool "${OFFLINE_INSTALL:-${AIR_GAPPED_INSTALL:-}}")"
if [[ "$OFFLINE_MODE_RAW" == "true" ]]; then
    OFFLINE_MODE=true
fi

case "${DOCKER_CLI_INSTALL_MODE}" in
    auto|always|never|true|false|yes|no|1|0) ;;
    *) fail "Geçersiz DOCKER_CLI_INSTALL değeri: '${DOCKER_CLI_INSTALL_MODE}'. Desteklenen: auto|always|never" ;;
esac

PLAYWRIGHT_BROWSERS_RAW="$(normalize_bool "${INSTALL_PLAYWRIGHT_BROWSERS:-}")"
if [[ "$PLAYWRIGHT_BROWSERS_RAW" == "true" ]]; then
    PLAYWRIGHT_BROWSERS_MODE="always"
elif [[ "$PLAYWRIGHT_BROWSERS_RAW" == "false" ]]; then
    PLAYWRIGHT_BROWSERS_MODE="never"
fi

AUTO_RUNTIME_MODE="$(resolve_runtime_mode_choice "${CLI_MODE_RAW:-${INSTALL_MODE:-${RUNTIME_MODE:-${APP_RUNTIME_MODE:-ask}}}}")"
if [[ -n "$CLI_MODE_RAW" && "$AUTO_RUNTIME_MODE" == "ask" ]]; then
    fail "Geçersiz --mode değeri: '${CLI_MODE_RAW}'. Desteklenen: local|docker"
fi
if [[ "$AUTO_RUNTIME_MODE" != "ask" ]]; then
    APP_RUNTIME_MODE="$AUTO_RUNTIME_MODE"
fi

AUTO_START_DOCKER_SERVICES="$(normalize_bool "${CLI_START_DOCKER_SERVICES:-${START_DOCKER_SERVICES:-${START_SERVICES:-}}}")"
[[ -z "$AUTO_START_DOCKER_SERVICES" ]] && AUTO_START_DOCKER_SERVICES="ask"

AUTO_RESET_POSTGRES_VOLUMES="$(normalize_bool "${CLI_RESET_POSTGRES_VOLUMES:-${RESET_DB:-${RESET_POSTGRES_VOLUMES:-}}}")"
[[ -z "$AUTO_RESET_POSTGRES_VOLUMES" ]] && AUTO_RESET_POSTGRES_VOLUMES="ask"

AUTO_ENV_TYPE="$(resolve_env_type_choice "${CLI_ENV_RAW:-${ENV_TYPE:-${SIDAR_ENV_TYPE:-}}}")"
if [[ -n "$CLI_ENV_RAW" && "$AUTO_ENV_TYPE" == "ask" ]]; then
    fail "Geçersiz --env değeri: '${CLI_ENV_RAW}'. Desteklenen: development|production"
fi
AUTO_OPEN_VSCODE="$(normalize_bool "${CLI_OPEN_VSCODE:-${OPEN_VSCODE:-${LAUNCH_VSCODE:-}}}")"
[[ -z "$AUTO_OPEN_VSCODE" ]] && AUTO_OPEN_VSCODE="ask"

if [[ "$SILENT_MODE" == true ]]; then
    export DEBIAN_FRONTEND=noninteractive
    NO_INTERACTION=true
    AUTO_INSTALL=true
    [[ "$AUTO_RUNTIME_MODE" == "ask" ]] && AUTO_RUNTIME_MODE="docker"
    [[ "$AUTO_START_DOCKER_SERVICES" == "ask" ]] && AUTO_START_DOCKER_SERVICES="true"
    [[ "$AUTO_RESET_POSTGRES_VOLUMES" == "ask" ]] && AUTO_RESET_POSTGRES_VOLUMES="true"
    [[ "$AUTO_ENV_TYPE" == "ask" ]] && AUTO_ENV_TYPE="development"
    [[ "$AUTO_OPEN_VSCODE" == "ask" ]] && AUTO_OPEN_VSCODE="false"
    [[ "$PLAYWRIGHT_BROWSERS_MODE" == "auto" ]] && PLAYWRIGHT_BROWSERS_MODE="never"
    info "⚠️  Sessiz otonom kurulum modu etkin (CI/CD güvenli varsayılanları uygulanıyor)."
fi

if [[ "$SKIP_MODELS" == true && "$DOWNLOAD_MODELS" == true ]]; then
    fail "--skip-models ve --download-models birlikte kullanılamaz."
fi

if [[ "$INSTALL_KUBERNETES" == true && "$FORCE_CPU" == true ]]; then
    warn "--kubernetes/--helm modu aktifken --cpu parametresi kullanılmaz; göz ardı edilecek."
fi

if [[ "$NO_INTERACTION" == true && "$RUN_SMOKE_TESTS_MODE" == "ask" ]]; then
    RUN_SMOKE_TESTS_MODE="never"
fi

# ── Sabitler ──────────────────────────────────────────────────────────────────
PYTHON_VERSION="3.11"
if [[ -f "$SCRIPT_DIR/.python-version" ]]; then
    PYTHON_VERSION_FROM_FILE=$(tr -d '[:space:]' < "$SCRIPT_DIR/.python-version" | cut -d. -f1,2)
    if [[ -n "$PYTHON_VERSION_FROM_FILE" ]]; then
        PYTHON_VERSION="$PYTHON_VERSION_FROM_FILE"
    fi
elif [[ -f "$SCRIPT_DIR/pyproject.toml" ]]; then
    PYPROJECT_PYTHON_VERSION=$(sed -nE 's/^[[:space:]]*requires-python[[:space:]]*=[[:space:]]*"[>=~^]*([0-9]+\.[0-9]+).*/\1/p' "$SCRIPT_DIR/pyproject.toml" | head -n1)
    if [[ -n "$PYPROJECT_PYTHON_VERSION" ]]; then
        PYTHON_VERSION="$PYPROJECT_PYTHON_VERSION"
    fi
fi
DEFAULT_DATABASE_URL=""
REPO_URL="https://github.com/niluferbagevi-gif/Sidar"
TARGET_DIR="$HOME/Sidar"
REQUIRED_DIRS=(data logs temp sessions data/rag data/lora_adapters data/continuous_learning)
OFFLINE_PACKAGES_DIR_DEFAULT_NAME="offline_packages"

banner() {
    echo -e "${BOLD}${BLUE}"
    echo "╔══════════════════════════════════════════════════════════════╗"
    echo "║          Sidar AI — Kurulum Başlıyor (v5.2.3)               ║"
    echo "╚══════════════════════════════════════════════════════════════╝"
    echo -e "${NC}"
}

ensure_noninteractive_sudo_ready() {
    if [[ "$EUID" -eq 0 ]]; then
        info "Kurulum root yetkisiyle çalışıyor; sudo parola engeli beklenmiyor."
        return 0
    fi

    if ! command -v sudo >/dev/null 2>&1; then
        if [[ "$NO_INTERACTION" == true || "$SILENT_MODE" == true || "$AUTO_INSTALL" == true ]]; then
            fail "Etkileşimsiz kurulum için sudo gerekli ancak sistemde sudo bulunamadı. Kurulumu root olarak başlatın (ör. sudo ./install_sidar.sh)."
        fi
        return 0
    fi

    if [[ "$NO_INTERACTION" == true || "$SILENT_MODE" == true || "$AUTO_INSTALL" == true ]]; then
        if sudo -n -v >/dev/null 2>&1; then
            ok "Etkileşimsiz mod için şifresiz/ön-doğrulanmış sudo erişimi hazır."
        else
            fail "Sudo parola engeli algılandı. Etkileşimsiz/sessiz kurulum bloke olur. Çözüm: (1) sudo ./install_sidar.sh ile root başlatın, (2) önceden 'sudo -v' çalıştırın, veya (3) gerekli komutlar için NOPASSWD sudo yapılandırın."
        fi
    fi
}


read_env_value_from_file() {
    local key="$1"
    local file_path="$2"
    [[ -f "$file_path" ]] || return 0

    awk -F= -v key="$key" '
        /^[[:space:]]*#/ { next }
        $0 ~ "^[[:space:]]*" key "[[:space:]]*=" {
            line = $0
            sub(/^[[:space:]]*[^=]+=[[:space:]]*/, "", line)
            sub(/[[:space:]]+#.*/, "", line)
            gsub(/\r/, "", line)
            gsub(/^[[:space:]]+|[[:space:]]+$/, "", line)
            gsub(/^"|"$/, "", line)
            gsub(/^'\''|'\''$/, "", line)
            print line
            exit
        }
    ' "$file_path"
}

normalize_ollama_base_url() {
    local raw="${1:-}"
    local normalized="$raw"

    normalized="${normalized%/}"
    normalized="${normalized%/api}"
    if [[ -z "$normalized" ]]; then
        echo "http://localhost:11434"
        return
    fi
    if [[ "$normalized" != http://* && "$normalized" != https://* ]]; then
        normalized="http://$normalized"
    fi
    echo "$normalized"
}

resolve_ollama_base_url() {
    local env_file="${1:-$SCRIPT_DIR/.env}"
    local detected="${OLLAMA_BASE_URL:-}"

    if [[ -z "$detected" ]]; then
        detected="${OLLAMA_HOST:-}"
    fi
    if [[ -z "$detected" && -f "$env_file" ]]; then
        detected=$(read_env_value_from_file "OLLAMA_BASE_URL" "$env_file")
    fi
    if [[ -z "$detected" && -f "$env_file" ]]; then
        detected=$(read_env_value_from_file "OLLAMA_HOST" "$env_file")
    fi

    normalize_ollama_base_url "$detected"
}

resolve_ollama_version_url() {
    local env_file="${1:-$SCRIPT_DIR/.env}"
    local base_url
    base_url=$(resolve_ollama_base_url "$env_file")
    echo "${base_url}/api/version"
}

is_local_ollama_url() {
    local url="$1"
    [[ "$url" == http://localhost:* || "$url" == https://localhost:* || "$url" == http://127.0.0.1:* || "$url" == https://127.0.0.1:* ]]
}

wait_for_ollama_api_ready() {
    local version_url="$1"
    local max_wait_seconds="${2:-10}"
    local poll_interval_seconds="${3:-1}"
    local elapsed=0

    while (( elapsed < max_wait_seconds )); do
        if curl -sf "$version_url" &>/dev/null; then
            return 0
        fi
        sleep "$poll_interval_seconds"
        elapsed=$((elapsed + poll_interval_seconds))
    done

    return 1
}

deploy_with_helm() {
    step "Kubernetes/Helm Dağıtımı"
    local chart_dir="$SCRIPT_DIR/helm/sidar"
    local helm_cmd=(helm upgrade --install "$HELM_RELEASE_NAME" "$chart_dir" --namespace "$HELM_NAMESPACE" --create-namespace)

    if ! command -v helm &>/dev/null; then
        fail "helm bulunamadı. Kurulum için: https://helm.sh/docs/intro/install/"
    fi

    if [[ ! -f "$chart_dir/Chart.yaml" ]]; then
        fail "Helm chart bulunamadı: $chart_dir/Chart.yaml"
    fi

    if [[ -n "$HELM_VALUES_FILE" ]]; then
        if [[ ! -f "$SCRIPT_DIR/$HELM_VALUES_FILE" && ! -f "$HELM_VALUES_FILE" ]]; then
            fail "--values ile verilen dosya bulunamadı: $HELM_VALUES_FILE"
        fi
        if [[ -f "$SCRIPT_DIR/$HELM_VALUES_FILE" ]]; then
            HELM_VALUES_FILE="$SCRIPT_DIR/$HELM_VALUES_FILE"
        fi
        helm_cmd+=(--values "$HELM_VALUES_FILE")
    fi

    info "Helm chart doğrulaması çalıştırılıyor..."
    helm lint "$chart_dir"

    info "Helm release kuruluyor/güncelleniyor: release=$HELM_RELEASE_NAME namespace=$HELM_NAMESPACE"
    "${helm_cmd[@]}"
    ok "Helm dağıtımı tamamlandı."

    if command -v kubectl &>/dev/null; then
        info "Servisleri doğrulamak için:"
        echo "       kubectl get pods -n $HELM_NAMESPACE"
        echo "       kubectl get svc -n $HELM_NAMESPACE"
    else
        warn "kubectl bulunamadı. Cluster doğrulaması için kubectl kurmanız önerilir."
    fi
}

report_repo_lookup_context() {
    local current_pwd
    current_pwd="$(pwd)"

    info "Kurulum çalışma dizini: $current_pwd"
    info "Sidar deposu hedef dizini: $TARGET_DIR"

    if [[ "$current_pwd" == /mnt/* ]]; then
        warn "Kurulum /mnt altında çalışıyor. Windows dosya sistemi önceki Sidar klasörünü koruyor olabilir."
        info "Temiz kurulum için öneri: cd \"$HOME\" && ./Sidar/install_sidar.sh veya doğrudan cd \"$TARGET_DIR\"."
    fi
}

# ── 0. GitHub deposunu hazırla / güncelle ────────────────────────────────────
sync_repo() {
    step "Sidar projesi GitHub'dan çekiliyor"

    if [[ "$OFFLINE_MODE" == true ]]; then
        if [[ -d "$SCRIPT_DIR/.git" ]]; then
            TARGET_DIR="$SCRIPT_DIR"
            ok "Çevrimdışı mod: mevcut repo kullanılacak (git clone/pull atlandı): $SCRIPT_DIR"
            return
        fi

        if [[ -d "$TARGET_DIR/.git" ]]; then
            SCRIPT_DIR="$TARGET_DIR"
            ok "Çevrimdışı mod: mevcut hedef repo kullanılacak (git clone/pull atlandı): $TARGET_DIR"
            return
        fi

        fail "Çevrimdışı modda git clone yapılamaz. Lütfen repo içinden çalıştırın veya $TARGET_DIR altında önceden klonlanmış repo sağlayın."
    fi

    # Bu adım git clone/pull çalıştırdığı için, akış sırası değişse bile
    # git erişimi burada da kesin olarak doğrulanır.
    if ! command -v git &>/dev/null; then
        fail "git komutu bulunamadı. Önce sistem bağımlılıklarını kurun (install_system_dependencies)."
    fi

    if [[ "$SCRIPT_DIR" == "$TARGET_DIR" && -d "$SCRIPT_DIR/.git" ]]; then
        ok "Kurulum betiği zaten $TARGET_DIR içinde çalışıyor."
        return
    fi

    if [[ ! -d "$TARGET_DIR/.git" ]]; then
        info "Sidar deposu klonlanıyor: $REPO_URL → $TARGET_DIR"
        git clone "$REPO_URL" "$TARGET_DIR"
    else
        warn "Sidar klasörü zaten var ($TARGET_DIR). Rebase tabanlı git pull ile güncelleniyor..."
        info "Not: Sıfır kurulum beklenirken bu uyarıyı görüyorsanız mevcut çalışma dizinini kontrol edin: $(pwd)"
        (
            cd "$TARGET_DIR"
            local STASHED_CHANGES=false
            if ! git diff --quiet || ! git diff --cached --quiet || [[ -n "$(git ls-files --others --exclude-standard)" ]]; then
                info "Lokal değişiklikler geçici olarak stash'e alınıyor."
                git stash push -u -m "sidar-install-auto-stash-$(date +%Y%m%d_%H%M%S)" >/dev/null 2>&1
                STASHED_CHANGES=true
            fi

            git pull --rebase origin main || fail "Git çekme işlemi başarısız oldu!"

            if [[ "$STASHED_CHANGES" == true ]]; then
                if git stash pop >/dev/null 2>&1; then
                    ok "Lokal değişiklikler stash'ten geri yüklendi."
                else
                    warn "Stash pop sırasında çakışma oluştu. Repo güvenliği için kurtarma seçeneği sunulacak."
                    git merge --abort >/dev/null 2>&1 || true
                    git rebase --abort >/dev/null 2>&1 || true
                    if [[ "$NO_INTERACTION" == true ]]; then
                        fail "Git çalışma ağacı çakışmalı durumda kaldı. --no-interaction modunda otomatik kurtarma yapılamadı. Manuel çözün veya '$TARGET_DIR' içinde 'git reset --hard origin/main && git clean -fd' çalıştırın."
                    fi

                    echo ""
                    warn "İsterseniz yerel değişiklikleri silerek origin/main durumuna geri dönebilirsiniz."
                    local recovery_reply
                    recovery_reply=$(prompt_yes_no_with_timeout_default_no "Çakışmayı otomatik temizlemek için 'git reset --hard origin/main && git clean -fd' uygulansın mı? [e/H] ")
                    case "${recovery_reply:-H}" in
                        [EeYy]*)
                            warn "Kurtarma adımı uygulanıyor: yerel değişiklikler silinecek."
                            git fetch origin main || fail "Kurtarma için origin/main fetch başarısız oldu."
                            git reset --hard origin/main || fail "git reset --hard origin/main başarısız oldu."
                            git clean -fd || warn "git clean -fd sırasında bazı dosyalar temizlenemedi."
                            ok "Repo origin/main durumuna sıfırlandı. Kurulum devam edecek."
                            ;;
                        *)
                            fail "Git çalışma ağacı çakışmalı durumda kaldı. Lütfen '$TARGET_DIR' içinde çakışmaları çözün veya 'git reset --hard origin/main && git clean -fd' ile temizleyip kurulumu tekrar başlatın."
                            ;;
                    esac
                fi
            fi
        )
    fi

    SCRIPT_DIR="$TARGET_DIR"
    ok "Kurulum dizini güncellendi: $SCRIPT_DIR"
}

# ── Sistem ve Donanım Bağımlılıkları ──────────────────────────────────────────
install_system_dependencies() {
    step "Temel Sistem Paketlerinin Kurulumu"
    local node_target_major=""
    node_target_major="$(resolve_target_node_major)"
    local node_target_series="node_${node_target_major}.x"
    local node_brew_formula="node@${node_target_major}"

    if command -v apt-get &>/dev/null && command -v sudo &>/dev/null; then
        info "Linux temel paketleri kuruluyor (tam sistem upgrade atlanır)..."
        local -a ns_source_files=()
        mapfile -t ns_source_files < <(sudo sh -c "grep -Rsl 'deb .*deb.nodesource.com/${node_target_series}' /etc/apt/sources.list /etc/apt/sources.list.d 2>/dev/null" || true)
        if [[ "${#ns_source_files[@]}" -gt 0 ]]; then
            info "NodeSource apt girdileri nodistro formatına normalize ediliyor..."
            local src_file=""
            for src_file in "${ns_source_files[@]}"; do
                sudo sed -E -i \
                    "s#(deb(\\s+\\[[^]]+\\])?\\s+https?://deb\\.nodesource\\.com/${node_target_series})\\s+[[:alnum:]_.-]+\\s+main#\\1 nodistro main#g" \
                    "$src_file"
            done
        fi

        if ! sudo DEBIAN_FRONTEND=noninteractive apt-get -o Acquire::Retries=3 update -y; then
            warn "apt update başarısız oldu. NodeSource listesi sıfırlanıp tekrar denenecek..."
            sudo rm -f /etc/apt/sources.list.d/nodesource.list
            sudo DEBIAN_FRONTEND=noninteractive apt-get -o Acquire::Retries=3 update -y
        fi
        info "Gerekli temel paketler (curl, wget, git, zstd vb.) kuruluyor..."
        sudo DEBIAN_FRONTEND=noninteractive apt-get -o Acquire::Retries=3 install -y \
            curl wget git build-essential software-properties-common zstd ca-certificates gnupg \
            postgresql-client-common postgresql-client

        ensure_docker_cli_available || warn "Docker CLI otomatik kurulamadı; Docker gerektiren adımlar manuel kurulumdan sonra çalıştırılabilir."

        info "Node.js (v${node_target_major}.x) durumu kontrol ediliyor..."
        local node_bin=""
        node_bin="$(resolve_native_binary_path node || true)"
        if [[ -n "$node_bin" ]] && "$node_bin" -v | grep -q "^v${node_target_major}\\."; then
            ok "Node.js ${node_target_major}.x zaten kurulu: $("$node_bin" -v)"
        else
            if [[ -z "$node_bin" ]] && command -v node &>/dev/null; then
                warn "Sadece Windows Interop Node.js bulundu ($(command -v node)). Linux Node.js kurulacak."
            fi
            info "Node.js ${node_target_major}.x (NodeSource nodistro) kuruluyor..."
            local ns_keyring="/etc/apt/keyrings/nodesource.gpg"
            local ns_repo_file="/etc/apt/sources.list.d/nodesource.list"
            local ns_key_tmp=""
            local ns_ready=false

            ns_key_tmp=$(mktemp)
            if curl -fsSL --retry 3 --retry-delay 2 --retry-connrefused \
                "https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key" -o "$ns_key_tmp"; then
                sudo install -m 0755 -d /etc/apt/keyrings
                if gpg --dearmor < "$ns_key_tmp" | sudo tee "$ns_keyring" >/dev/null; then
                    sudo chmod 0644 "$ns_keyring"
                    sudo rm -f "$ns_repo_file"
                    echo "deb [signed-by=${ns_keyring}] https://deb.nodesource.com/${node_target_series} nodistro main" | sudo tee "$ns_repo_file" >/dev/null
                    sudo chmod 0644 "$ns_repo_file"
                    ns_ready=true
                else
                    warn "NodeSource GPG keyring oluşturulamadı."
                fi
            else
                warn "NodeSource GPG anahtarı indirilemedi."
            fi
            rm -f "$ns_key_tmp"

            if [[ "$ns_ready" == true ]] && \
                sudo DEBIAN_FRONTEND=noninteractive apt-get -o Acquire::Retries=3 update -y && \
                sudo DEBIAN_FRONTEND=noninteractive apt-get -o Acquire::Retries=3 install -y nodejs; then
                ok "Node.js NodeSource üzerinden kuruldu: $(node --version 2>/dev/null || echo 'sürüm alınamadı')"
            else
                warn "NodeSource üzerinden Node.js kurulamadı, varsayılan apt deposu deneniyor..."
                node_bin="$(resolve_native_binary_path node || true)"
                if [[ -n "$node_bin" ]]; then
                    warn "Sistemde node bulundu ($("$node_bin" -v 2>/dev/null || echo 'sürüm alınamadı'))."
                    warn "nodejs + npm çakışmasını önlemek için apt ile npm zorla kurulmayacak."
                    local npm_bin=""
                    npm_bin="$(resolve_native_binary_path npm || true)"
                    if [[ -n "$npm_bin" ]]; then
                        ok "npm zaten mevcut: $("$npm_bin" -v 2>/dev/null || echo 'sürüm alınamadı')"
                    else
                        warn "npm bulunamadı. NodeSource nodejs paketi npm içerir; PATH/kurulum durumu kontrol edilmeli."
                    fi
                else
                    sudo DEBIAN_FRONTEND=noninteractive apt-get -o Acquire::Retries=3 install -y nodejs npm
                fi
            fi
        fi

        info "Kamera ve ses kütüphaneleri kuruluyor..."
        local -a linux_media_pkgs=(
            portaudio19-dev python3-pyaudio alsa-utils v4l-utils ffmpeg
        )
        if [[ "$WSL2" == true ]]; then
            info "WSL2 için PulseAudio uyumluluk paketleri de kurulacak."
            linux_media_pkgs+=(pulseaudio-utils libpulse-dev libasound2-plugins pulseaudio)
        fi
        sudo DEBIAN_FRONTEND=noninteractive apt-get -o Acquire::Retries=3 install -y "${linux_media_pkgs[@]}"
        info "Host PostgreSQL/Redis kurulumu devre dışı bırakıldı (port çakışmasını önlemek için)."
        info "Veritabanı ve cache servislerini Docker Compose ile yönetin: docker compose up -d"

        ok "Sistem paketleri ve donanım kütüphaneleri başarıyla kuruldu."
    elif command -v dnf &>/dev/null; then
        warn "RedHat/Fedora tabanlı sistem tespit edildi. Paketler dnf ile kuruluyor..."
        sudo dnf upgrade -y
        sudo dnf install -y curl wget git zstd nodejs npm portaudio-devel alsa-utils v4l-utils ffmpeg
        info "Host PostgreSQL/Redis servis kurulumu atlandı. Servisleri Docker Compose ile yönetin."
    elif command -v pacman &>/dev/null; then
        warn "Arch tabanlı sistem tespit edildi. Paketler pacman ile kuruluyor..."
        sudo pacman -Sy --noconfirm --needed \
            curl wget git zstd nodejs npm portaudio alsa-utils v4l-utils ffmpeg
        node_bin="$(resolve_native_binary_path node || true)"
        if [[ -n "$node_bin" ]]; then
            NODE_MAJOR="$("$node_bin" -v | sed 's/^v//' | cut -d. -f1)"
            if [[ "$NODE_MAJOR" -lt "$node_target_major" ]]; then
                warn "Arch depolarındaki Node.js sürümü hedefin altında olabilir: $("$node_bin" -v) (hedef: ${node_target_major}.x+)."
            else
                ok "Node.js sürümü uygun: $("$node_bin" -v)"
            fi
        fi
        info "Host PostgreSQL/Redis servis kurulumu atlandı. Servisleri Docker Compose ile yönetin."
    elif command -v zypper &>/dev/null; then
        warn "OpenSUSE/SLES tabanlı sistem tespit edildi. Paketler zypper ile kuruluyor..."
        sudo zypper --non-interactive refresh
        sudo zypper --non-interactive install --no-recommends \
            curl wget git zstd nodejs npm portaudio19-devel alsa-utils v4l-utils ffmpeg
        node_bin="$(resolve_native_binary_path node || true)"
        if [[ -n "$node_bin" ]]; then
            NODE_MAJOR="$("$node_bin" -v | sed 's/^v//' | cut -d. -f1)"
            if [[ "$NODE_MAJOR" -lt "$node_target_major" ]]; then
                warn "OpenSUSE depolarındaki Node.js sürümü hedefin altında olabilir: $("$node_bin" -v) (hedef: ${node_target_major}.x+)."
            else
                ok "Node.js sürümü uygun: $("$node_bin" -v)"
            fi
        fi
        info "Host PostgreSQL/Redis servis kurulumu atlandı. Servisleri Docker Compose ile yönetin."
    elif command -v brew &>/dev/null; then
        warn "macOS (Homebrew) ortamı tespit edildi. Paketler brew ile kuruluyor..."
        brew update
        brew install \
            curl wget git zstd "${node_brew_formula}" ffmpeg portaudio || warn "Bazı Homebrew paketleri kurulamadı; eksikleri manuel tamamlayın."
        info "Host Redis kurulumu atlandı. Servisleri Docker Compose ile yönetmeniz önerilir."

        if brew list "${node_brew_formula}" &>/dev/null; then
            info "Node.js ${node_target_major} için brew link işlemi deneniyor..."
            brew link --overwrite --force "${node_brew_formula}" >/dev/null 2>&1 || true
            ok "Node.js sürümü: $(node --version 2>/dev/null || echo 'sürüm alınamadı')"
        fi

        info "brew services ile host PostgreSQL/Redis başlatma adımı kaldırıldı (Docker Compose tercih ediliyor)."

        ok "Homebrew tabanlı bağımlılık kurulumu tamamlandı."
    else
        warn "Desteklenen paket yöneticileri (apt/dnf/pacman/zypper/brew) bulunamadı. Lütfen paketleri manuel kurun:"
        info "Gerekenler: zstd portaudio19-dev alsa-utils v4l-utils ffmpeg vb."
    fi
}

detect_environment() {
    step "Çalışma Ortamı Tespiti"

    if grep -qi "microsoft" /proc/sys/kernel/osrelease 2>/dev/null; then
        WSL2=true
        info "Ortam: WSL2 (Windows Subsystem for Linux)"
    elif [[ "$(uname -s)" == "Darwin" ]]; then
        WSL2=false
        info "Ortam: macOS"
    else
        WSL2=false
        info "Ortam: Linux (native/container)"
    fi
}

# ── 1. Ön koşul kontrolleri ───────────────────────────────────────────────────
ensure_prerequisites() {
    step "Ön Koşullar Kontrol Ediliyor"

    info "Kurulum yöneticisi: yalnızca uv venv akışı kullanılacak (Conda/Miniconda adımları devre dışı)."

    # Git
    if ! command -v git &>/dev/null; then
        fail "Git bulunamadı. Kurun: sudo apt-get install -y git"
    fi
    ok "Git $(git --version | cut -d' ' -f3)"

    # FFmpeg (openai-whisper / yt-dlp için zorunlu)
    if command -v ffmpeg &>/dev/null; then
        FFMPEG_VER=$(ffmpeg -version 2>/dev/null | head -1 | awk '{print $3}')
        ok "FFmpeg ${FFMPEG_VER:-yüklü}"
    else
        warn "FFmpeg bulunamadı. openai-whisper ve yt-dlp özellikleri FFmpeg olmadan çalışmaz."
        if command -v apt-get &>/dev/null && command -v sudo &>/dev/null; then
            info "Kurulum yapılıyor: sudo apt-get update && sudo apt-get install -y ffmpeg"
            sudo apt-get update && sudo apt-get install -y ffmpeg || warn "FFmpeg otomatik kurulamadı, manuel kurunuz."
        elif command -v apt-get &>/dev/null; then
            info "Kurulum için: sudo apt-get update && sudo apt-get install -y ffmpeg"
        elif command -v dnf &>/dev/null; then
            info "Kurulum için: sudo dnf install -y ffmpeg ffmpeg-devel"
        elif command -v pacman &>/dev/null; then
            info "Kurulum için: sudo pacman -Sy --noconfirm --needed ffmpeg"
        elif command -v zypper &>/dev/null; then
            info "Kurulum için: sudo zypper --non-interactive install ffmpeg"
        elif command -v brew &>/dev/null; then
            info "Kurulum için: brew install ffmpeg"
        else
            warn "Paket yöneticisi otomatik tespit edilemedi. FFmpeg'i sisteminize manuel kurun."
        fi
    fi

    # Docker / Docker Compose (özet komutları için önerilir)
    ensure_docker_cli_available || true

    local docker_version_check_ok=false
    local docker_version_error=""
    if command -v docker &>/dev/null; then
        local _docker_err_file
        _docker_err_file=$(mktemp)
        if docker_cli_healthy 2>"$_docker_err_file"; then
            docker_version_check_ok=true
        else
            docker_version_error="$(<"$_docker_err_file")"
        fi
        rm -f "$_docker_err_file"
    fi

    if command -v docker &>/dev/null && [[ "$docker_version_check_ok" == true ]]; then
        local docker_ver
        docker_ver=$(docker --version 2>/dev/null | awk '{print $3}' | tr -d ',' || true)
        ok "Docker ${docker_ver:-yüklü}"
        ensure_current_user_in_docker_group
        if ensure_docker_daemon_running; then
            ok "Docker daemon çalışıyor."
        else
            warn "Docker daemon başlatılamadı. Docker Desktop/service durumunu kontrol edin."
        fi
        if docker compose version &>/dev/null; then
            ok "Docker Compose eklentisi mevcut."
        elif command -v docker-compose &>/dev/null; then
            ok "docker-compose (standalone) mevcut."
        else
            warn "Docker Compose bulunamadı. Kurulum: https://docs.docker.com/compose/install/"
        fi
    else
        if [[ "$WSL2" == true ]] && [[ "$docker_version_error" == *"Input/output error"* ]]; then
            warn "Docker CLI çağrısı Input/output error döndürüyor. WSL entegrasyon mount'ları askıda kalmış olabilir."
        fi
        warn "Docker bulunamadı veya çalıştırılamıyor. Docker komutları (örn. docker compose up sidar-gpu) çalışmayacaktır."
    fi

    # Sistem Python sürümü artık doğrulanmaz: uv, gerekli Python sürümünü izole
    # ortam için kendisi çözer/indirir ve proje sürümünü .python-version veya
    # pyproject.toml üzerinden setup_python_env içinde uygular.

    if [[ "$WSL2" == true ]]; then
        info "WSL2 ortamı tespit edildi."
    fi

    if [[ "$WSL2" == true ]] && !(command -v docker &>/dev/null && [[ "$docker_version_check_ok" == true ]]); then

        # Windows tarafında Docker Desktop'ın gerçekten kurulu olup olmadığını denetle
        local docker_desktop_installed=false
        if [[ -f "/mnt/c/Program Files/Docker/Docker/Docker Desktop.exe" ]] || command -v docker.exe &>/dev/null; then
            docker_desktop_installed=true
        fi

        # Eğer Windows'ta kurulu değilse net bir şekilde hata verip kurulumu iptal et
        if [[ "$docker_desktop_installed" == false ]]; then
            fail "Docker Desktop sisteminizde hiç bulunamadı, lütfen önce Windows'a kurun."
        else
            # Windows'ta kurulu ama WSL2'de çalışmıyorsa entegrasyon bozuktur
            warn "Docker kullanılamıyor! Yeni bir WSL dağıtımı kurduğunuz için Docker Desktop entegrasyonu kopmuş olabilir."
            info "Lütfen şu adımları uygulayın:"
            echo "  1. Windows'ta Docker Desktop'ı açın."
            echo "  2. Settings > Resources > WSL Integration menüsüne gidin."
            echo "  3. 'Ubuntu' anahtarını aktif edip 'Apply & restart' butonuna tıklayın."
            echo ""
            read -r -p "Entegrasyonu tamamladıktan sonra devam etmek için [ENTER] tuşuna basın..."

            # Kullanıcıdan onay sonrası tekrar doğrula
            if ! docker_cli_healthy; then
                fail "Docker hâlâ kullanılamıyor. Kurulum iptal edildi; entegrasyonu tamamladıktan sonra tekrar deneyin."
            fi
        fi
    fi

    # Redis (Local Event Bus / cache)
    if [[ "$DOCKER_ONLY" == false ]] && ! command -v redis-server &>/dev/null && [[ "$WSL2" == false ]]; then
        warn "Lokal Redis sunucusu bulunamadı. Projenin düzgün çalışması için Redis gereklidir."
        info "Lokal yerine Docker kullanacaksanız bu uyarıyı dikkate almayın."
    fi

    if command -v psql &>/dev/null; then
        ok "PostgreSQL istemcisi hazır: $(psql --version | awk '{print $3}')"
    elif [[ "$DOCKER_ONLY" == true ]]; then
        info "--docker-only: psql istemcisi opsiyonel. DB bağlantısı Docker servisleriyle sağlanacak."
    else
        warn "psql bulunamadı. Bu kurulum akışı Docker Compose PostgreSQL servisini esas alır."
    fi

    # Ollama (varsayılan AI provider) - Akıllı Kontrol ve Kurulum
    if ! ollama -v &>/dev/null; then
        warn "Ollama bulunamadı veya kurulumu bozuk. İndiriliyor..."
        if command -v sudo &>/dev/null; then
            # Eski bozuk dosya kalıntılarını temizle
            sudo rm -f /usr/local/bin/ollama
            info "Ollama kurulumu başlatılıyor..."
            local ollama_install_script=""
            if [[ "$OFFLINE_MODE" == true ]]; then
                ollama_install_script="$(resolve_offline_package_file "ollama/install.sh" || true)"
                [[ -z "$ollama_install_script" ]] && ollama_install_script="$(resolve_offline_package_file "ollama_install.sh" || true)"
                [[ -z "$ollama_install_script" ]] && ollama_install_script="$(resolve_offline_package_file "install_ollama.sh" || true)"
                [[ -n "$ollama_install_script" ]] || fail "Çevrimdışı mod: offline_packages altında Ollama kurulum betiği bulunamadı (ollama/install.sh, ollama_install.sh, install_ollama.sh)."
            else
                DOWNLOADED_SCRIPT_FILE=""
                download_verified_script \
                    "https://ollama.com/install.sh" \
                    "${OLLAMA_INSTALL_SHA256:-}" \
                    "ollama_install"
                validate_downloaded_script_file "$DOWNLOADED_SCRIPT_FILE" "ollama_install"
                ollama_install_script="$DOWNLOADED_SCRIPT_FILE"
            fi

            info "Ollama kurulumu öncesi sudo yetkisi doğrulanıyor..."
            if [[ "$NO_INTERACTION" == true ]]; then
                sudo -n -v || fail "Ollama kurulumu için sudo yetkisi gerekli. --ci/--no-interaction modunda şifresiz sudo veya önceden doğrulanmış sudo oturumu beklenir."
            else
                sudo -v || fail "Ollama kurulumu için sudo doğrulaması başarısız oldu."
            fi

            sh "$ollama_install_script"
            [[ "$ollama_install_script" == "${DOWNLOADED_SCRIPT_FILE:-}" ]] && rm -f "$DOWNLOADED_SCRIPT_FILE"
            ok "Ollama başarıyla kuruldu."
        else
            warn "Sudo yetkisi bulunamadı. Kurulum manuel yapılmalı: https://ollama.com"
        fi
    else
        ok "Ollama zaten kurulu."
    fi

    # Servisin anlık olarak yanıt verip vermediğini kontrol et
    OLLAMA_VERSION_URL=$(resolve_ollama_version_url "$SCRIPT_DIR/.env")
    info "Ollama API healthcheck bekleme döngüsü başlatılıyor (maksimum 10 saniye)..."
    if wait_for_ollama_api_ready "$OLLAMA_VERSION_URL" 10 1; then
        ok "Ollama API servisi aktif (${OLLAMA_VERSION_URL})."
    else
        warn "Ollama kurulu ancak API servisi şu an yanıt vermiyor (${OLLAMA_VERSION_URL})."
        info "Model indirmek veya servisi başlatmak için ayrı bir terminalde 'ollama serve' komutunu çalıştırabilirsiniz."
        info "Alternatif olarak .env içinde AI_PROVIDER=gemini veya openai kullanabilirsiniz."
    fi
}

# ── 2. NVIDIA GPU tespiti ────────────────────────────────────────────────────
# detect_gpu scripts/install_modules altında modülerleştirildi.
# setup_nvidia_docker scripts/install_modules altında modülerleştirildi.
# setup_python_env scripts/install_modules altında modülerleştirildi.
# setup_uv scripts/install_modules altında modülerleştirildi.
# install_python_deps scripts/install_modules altında modülerleştirildi.
# install_pyright_lsp_tool scripts/install_modules altında modülerleştirildi.
should_install_playwright_browsers() {
    case "$PLAYWRIGHT_BROWSERS_MODE" in
        always) return 0 ;;
        never) return 1 ;;
    esac

    local env_file="$SCRIPT_DIR/.env"
    local sidar_env="development"
    if [[ -f "$env_file" ]]; then
        sidar_env="$(read_env_value_from_file "SIDAR_ENV" "$env_file")"
    fi
    sidar_env=$(echo "${sidar_env:-development}" | tr '[:upper:]' '[:lower:]' | tr -d '"'\''[:space:]')

    case "$sidar_env" in
        development|dev|local|test) return 0 ;;
        *) return 1 ;;
    esac
}

install_playwright_browsers() {
    step "Playwright Tarayıcı Motorları"

    if ! should_install_playwright_browsers; then
        info "Playwright tarayıcı kurulumu atlandı (mode=${PLAYWRIGHT_BROWSERS_MODE}, SIDAR_ENV tabanlı otomatik politika)."
        return
    fi

    PY_CMD=(python)

    if "${PY_CMD[@]}" -c "import playwright" >/dev/null 2>&1; then
        local pw_timeout_ms="${PLAYWRIGHT_DOWNLOAD_CONNECTION_TIMEOUT:-120000}"
        local _pw_install_log; _pw_install_log=$(mktemp)

        info "Playwright headless optimizasyonu: yalnızca Chromium (--with-deps) kuruluyor (timeout=${pw_timeout_ms}ms)..."
        if env PLAYWRIGHT_DOWNLOAD_CONNECTION_TIMEOUT="$pw_timeout_ms" \
            "${PY_CMD[@]}" -m playwright install --with-deps chromium >"$_pw_install_log" 2>&1; then
            grep -vE 'is already the newest version|0 upgraded.*0 newly|Reading package|Building dependency|Reading state|^$' \
                "$_pw_install_log" || true
            ok "Playwright kurulumu tamamlandı (chromium, --with-deps)."
        else
            cat "$_pw_install_log" >&2
            warn "Playwright kurulumu başarısız oldu. Manuel komut: uv run python -m playwright install --with-deps chromium"
        fi

        rm -f "$_pw_install_log"
    else
        info "playwright paketi bu profilde kurulmadı — tarayıcı motor kurulumu atlandı."
    fi
}

# ── 7. React Web UI bağımlılıkları ve build ──────────────────────────────────
setup_react_frontend() {
    step "React Web Arayüzü"

    REACT_DIR="$SCRIPT_DIR/web_ui_react"
    if [[ ! -d "$REACT_DIR" ]]; then
        info "web_ui_react dizini bulunamadı — frontend kurulumu atlandı."
        REACT_UI_STATUS="dizin_yok"
        return
    fi

    if [[ ! -f "$REACT_DIR/package.json" ]]; then
        info "web_ui_react/package.json bulunamadı — frontend kurulumu atlandı."
        REACT_UI_STATUS="package_json_yok"
        return
    fi

    local npm_bin=""
    npm_bin="$(resolve_native_binary_path npm || true)"
    if [[ -z "$npm_bin" ]]; then
        if command -v npm &>/dev/null; then
            warn "Sadece Windows Interop npm bulundu ($(command -v npm)). Linux Node.js/npm kullanın."
        fi
        warn "npm bulunamadı. React Web UI için Node.js + npm kurun ve şu komutları çalıştırın:"
        echo "       cd web_ui_react && npm ci && npm run build"
        REACT_UI_STATUS="npm_yok"
        return
    fi

    local node_bin=""
    node_bin="$(resolve_native_binary_path node || true)"
    local node_target_major=""
    node_target_major="$(resolve_target_node_major)"
    if [[ -n "$node_bin" ]]; then
        NODE_MAJOR="$("$node_bin" -v | sed 's/^v//' | cut -d. -f1)"
        if [[ "$NODE_MAJOR" -lt "$node_target_major" ]]; then
            warn "Node.js sürümü düşük: $("$node_bin" -v). React build için Node.js ${node_target_major}+ önerilir."
            warn "Kurulum komutları: sudo DEBIAN_FRONTEND=noninteractive apt-get install -y nodejs (NodeSource repo betik tarafından hedef sürüme göre otomatik ayarlanır)"
        else
            ok "Node.js sürümü uygun: $("$node_bin" -v)"
        fi
    elif command -v node &>/dev/null; then
        warn "Sadece Windows Interop node bulundu ($(command -v node)). React build için Linux Node.js kullanılmalı."
    fi

    if [[ "$FORCE_REACT_BUILD" != true && "$INSTALL_DEV" == false && -d "$REACT_DIR/dist" && -d "$REACT_DIR/node_modules" ]]; then
        ok "React Web UI zaten build edilmiş. Yeniden derleme atlanıyor (--build-ui ile zorlayabilirsiniz)."
        REACT_UI_STATUS="hazır_cache"
        return
    fi

    if ! (
        cd "$REACT_DIR"
        if [[ -f "package-lock.json" ]]; then
            info "package-lock.json bulundu. npm ci çalıştırılıyor..."
            npm ci
        else
            warn "package-lock.json bulunamadı. npm ci yerine npm install kullanılacak."
            npm install
        fi
        info "npm run build çalıştırılıyor..."
        npm run build
    ); then
        warn "React UI build başarısız oldu. Kurulum devam edecek; özet bölümünde durum işaretlenecek."
        REACT_UI_STATUS="build_hata"
        return
    fi
    if [[ ! -d "$REACT_DIR/dist" ]]; then
        warn "React UI build tamamlandı görünüyor ancak dist klasörü bulunamadı: $REACT_DIR/dist"
        REACT_UI_STATUS="build_hata"
        return
    fi
    ok "React Web UI bağımlılıkları kuruldu ve build tamamlandı."
    REACT_UI_STATUS="hazır"
}

# ── 8. WSL2 Ses Desteği Kurulumu ─────────────────────────────────────────────
# WSLg (Windows 11 Build 22000+) PulseAudio soketi üzerinden gerçek zamanlı
# mikrofon/hoparlör erişimini etkinleştirir.
setup_wsl2_audio() {
    [[ "$WSL2" == true ]] || return 0

    step "WSL2 Ses Desteği"

    local pulse_socket=""
    local pulse_uid
    pulse_uid=$(id -u)
    local pulse_runtime_dir="/run/user/${pulse_uid}"

    # WSLg PulseAudio soket konumlarını sırayla dene
    for candidate in \
        "${pulse_runtime_dir}/pulse/native" \
        "/tmp/pulse-${pulse_uid}/native" \
        "/tmp/pulse-socket"; do
        if [[ -S "$candidate" ]]; then
            pulse_socket="$candidate"
            break
        fi
    done

    # ── WSLg soketi tespit edildi: tam ses kurulumu ────────────────────────────
    if [[ -n "$pulse_socket" ]]; then
        ok "WSLg PulseAudio soketi tespit edildi: $pulse_socket"
        info "Windows 11 WSLg üzerinde ses desteği yapılandırılıyor..."
        AUDIO_SESSION_RESTART_RECOMMENDED=true

        # PulseAudio istemci araçları + ALSA→PulseAudio köprüsü
        info "PulseAudio istemci kütüphaneleri kontrol ediliyor..."
        local pa_pkgs_needed=()
        for pkg in pulseaudio-utils libpulse-dev libasound2-plugins; do
            dpkg -l "$pkg" &>/dev/null 2>&1 || pa_pkgs_needed+=("$pkg")
        done
        if [[ ${#pa_pkgs_needed[@]} -gt 0 ]]; then
            sudo DEBIAN_FRONTEND=noninteractive apt-get install -y "${pa_pkgs_needed[@]}" \
                >/dev/null 2>&1 && ok "PulseAudio paketleri kuruldu: ${pa_pkgs_needed[*]}" \
                || warn "Bazı PulseAudio paketleri kurulamadı: ${pa_pkgs_needed[*]}"
        else
            ok "PulseAudio paketleri zaten kurulu."
        fi

        # ALSA → PulseAudio yönlendirmesi (~/.asoundrc)
        local asoundrc="$HOME/.asoundrc"
        if [[ ! -f "$asoundrc" ]] || ! grep -q "pcm.pulse" "$asoundrc" 2>/dev/null; then
            cat > "$asoundrc" <<'ASOUNDRC'
# Sidar: ALSA varsayılanını PulseAudio'ya yönlendir (WSL2/WSLg)
pcm.default pulse
ctl.default pulse

pcm.pulse {
    type pulse
}
ctl.pulse {
    type pulse
}
ASOUNDRC
            ok "ALSA → PulseAudio köprüsü yapılandırıldı (~/.asoundrc)."
        else
            ok "~/.asoundrc zaten PulseAudio yapılandırması içeriyor."
        fi

        # PULSE_SERVER ortam değişkeni (yeni terminaller için kalıcı)
        local pulse_export="export PULSE_SERVER=unix:${pulse_socket}"
        for rcfile in "$HOME/.bashrc" "$HOME/.zshrc"; do
            if [[ -f "$rcfile" ]]; then
                if grep -Fxq "$pulse_export" "$rcfile" 2>/dev/null; then
                    ok "PULSE_SERVER zaten ${rcfile} içinde tanımlı."
                else
                    echo "" >> "$rcfile"
                    echo "# Sidar WSL2 ses desteği" >> "$rcfile"
                    echo "$pulse_export" >> "$rcfile"
                    ok "PULSE_SERVER → ${rcfile} dosyasına eklendi."
                fi
            fi
        done
        # Mevcut oturum için de hemen ayarla
        export PULSE_SERVER="unix:${pulse_socket}"

        # PulseAudio bağlantısını doğrula
        if command -v pactl &>/dev/null && pactl info &>/dev/null 2>&1; then
            local pa_server
            pa_server=$(pactl info 2>/dev/null | grep -i "Server Name" | cut -d: -f2- | xargs || echo "aktif")
            ok "PulseAudio bağlantısı doğrulandı: ${pa_server}"

            # .env'de ENABLE_MULTIMODAL=true yap (ses çalışıyor)
            local env_file="$SCRIPT_DIR/.env"
            if [[ -f "$env_file" ]]; then
                if grep -q "^ENABLE_MULTIMODAL=" "$env_file"; then
                    sed -i 's/^ENABLE_MULTIMODAL=.*/ENABLE_MULTIMODAL=true/' "$env_file"
                else
                    echo "ENABLE_MULTIMODAL=true" >> "$env_file"
                fi
                ok ".env: ENABLE_MULTIMODAL=true — ses/mikrofon desteği aktif."
            fi
        else
            warn "PulseAudio soketi mevcut fakat pactl ile doğrulanamadı."
            info "Yeni bir terminal açtıktan sonra test edin: pactl info"
            info "Sorun devam ederse: wsl --shutdown && wsl (Windows PowerShell'de)"
        fi

    # ── WSLg soketi bulunamadı: yönlendirme ve otomatik WSLg etkinleştirme ────
    else
        # --enable-audio bayrağıyla çalışıyorsa aktif etkinleştirme girişimi yap
        if [[ "$ENABLE_AUDIO" == true ]]; then
            warn "WSLg PulseAudio soketi henüz mevcut değil."
            info "WSLg'yi etkinleştirmek için aşağıdaki adımları uygulayın:"
            echo ""
            echo "  Windows PowerShell / CMD (yönetici olarak):"
            echo "    1. wsl --update"
            echo "    2. wsl --shutdown"
            echo "    3. Dağıtımı yeniden başlatın: wsl -d Ubuntu"
            echo ""
            echo "  Gereksinimler:"
            echo "    • Windows 11 Build 22000+ (veya Windows 10 KB5004296+)"
            echo "    • WSL 2.0.0+ (wsl --update ile güncelleyin)"
            echo ""
            echo "  WSLg sonra kurulumu tamamlayın:"
            echo "    ./install_sidar.sh --enable-audio"
            echo ""
            info "Ses desteği olmadan devam edilecek (ENABLE_MULTIMODAL=false)."
            local env_file="$SCRIPT_DIR/.env"
            if [[ -f "$env_file" ]]; then
                if grep -q "^ENABLE_MULTIMODAL=" "$env_file"; then
                    sed -i 's/^ENABLE_MULTIMODAL=.*/ENABLE_MULTIMODAL=false/' "$env_file"
                fi
            fi
        else
            warn "WSL2 üzerinde ses donanımına erişim kısıtlıdır."
            info "Ses desteğini etkinleştirmek için:"
            echo "  1. Windows 11 Build 22000+ ile WSLg otomatik olarak ses desteği sağlar."
            echo "  2. 'wsl --update' ile WSL'yi güncelleyin, ardından 'wsl --shutdown' yapın."
            echo "  3. Kurulum betiğini --enable-audio bayrağıyla yeniden çalıştırın:"
            echo "       ./install_sidar.sh --enable-audio"
            echo ""
            info "Sesli özellik kullanmayacaksanız .env dosyanızda ENABLE_MULTIMODAL=false kalabilir."
        fi
    fi

    # ── RAM limiti kontrolü ve .wslconfig otomatik yapılandırma ──────────────
    local wslconfig_path=""
    local resolved_windows_home=""
    resolved_windows_home="$(resolve_windows_userprofile_path || true)"
    if [[ -n "$resolved_windows_home" ]]; then
        wslconfig_path="${resolved_windows_home}/.wslconfig"
    fi

    # Mevcut memory değerini GB cinsinden sayıya çevir (örn. "16GB" → 16)
    _parse_gb() {
        echo "${1:-0}" | grep -oP '^\d+' || echo "0"
    }

    _detect_host_ram_gb() {
        local total_kb="0"
        if [[ -r /proc/meminfo ]]; then
            total_kb=$(awk '/^MemTotal:/ {print $2; exit}' /proc/meminfo 2>/dev/null || echo "0")
        fi
        if [[ -z "$total_kb" || "$total_kb" -le 0 ]]; then
            echo "16"
            return
        fi
        # Yukarı yuvarla: KB -> GB
        echo $(((total_kb + 1048575) / 1048576))
    }

    _clamp_int() {
        local val="$1"
        local min="$2"
        local max="$3"
        if [[ "$val" -lt "$min" ]]; then
            echo "$min"
            return
        fi
        if [[ "$val" -gt "$max" ]]; then
            echo "$max"
            return
        fi
        echo "$val"
    }

    local host_ram_gb
    local target_memory_gb
    local target_swap_gb
    host_ram_gb=$(_detect_host_ram_gb)
    target_memory_gb=$((host_ram_gb * 3 / 4))
    target_memory_gb=$(_clamp_int "$target_memory_gb" 4 32)
    target_swap_gb=$((host_ram_gb / 2))
    target_swap_gb=$(_clamp_int "$target_swap_gb" 2 16)

    local target_memory="${target_memory_gb}GB"
    local target_swap="${target_swap_gb}GB"
    info "WSL2 için dinamik .wslconfig hedefleri: memory=${target_memory}, swap=${target_swap} (host RAM: ${host_ram_gb}GB)."

    # [wsl2] bölümünde bir anahtarın tekil olmasını sağlar; yoksa ekler.
    # Değer zaten varsa korur, yinelenen satırları temizler.
    _ensure_wsl2_key_once() {
        local cfg_file="$1"
        local cfg_key="$2"
        local cfg_value="$3"
        local tmp_file
        tmp_file=$(mktemp)

        awk -v key="$cfg_key" -v value="$cfg_value" '
            BEGIN { in_wsl2=0; seen_key=0 }
            {
                if ($0 ~ /^\[.*\]$/) {
                    if (in_wsl2 && !seen_key) {
                        print key "=" value
                        seen_key=1
                    }
                    in_wsl2 = ($0 == "[wsl2]")
                    print
                    next
                }

                if (in_wsl2 && $0 ~ ("^" key "=")) {
                    if (!seen_key) {
                        print
                        seen_key=1
                    }
                    next
                }

                print
            }
            END {
                if (in_wsl2 && !seen_key) {
                    print key "=" value
                }
            }
        ' "$cfg_file" > "$tmp_file"

        if ! cmp -s "$cfg_file" "$tmp_file"; then
            mv "$tmp_file" "$cfg_file"
            return 0
        fi

        rm -f "$tmp_file"
        return 1
    }

    if [[ -n "$wslconfig_path" ]]; then
        if [[ ! -f "$wslconfig_path" ]]; then
            cat > "$wslconfig_path" <<'WSLCFG'
[wsl2]
memory=__SIDAR_WSL_MEMORY__
swap=__SIDAR_WSL_SWAP__
WSLCFG
            sed -i "s/__SIDAR_WSL_MEMORY__/${target_memory}/g; s/__SIDAR_WSL_SWAP__/${target_swap}/g" "$wslconfig_path"
            ok "WSL2: %UserProfile%/.wslconfig oluşturuldu (memory=${target_memory}, swap=${target_swap})."
            WSLCONFIG_CHANGED=true
            info "Değişiklik sonrası PowerShell'de 'wsl --shutdown' çalıştırıp dağıtımı yeniden başlatın."
        else
            local changed=false

            # [wsl2] bölümü yoksa dosyanın sonuna ekle
            if ! grep -q '^\[wsl2\]' "$wslconfig_path" 2>/dev/null; then
                printf '\n[wsl2]\n' >> "$wslconfig_path"
                ok "WSL2: .wslconfig içine [wsl2] bölümü eklendi."
                changed=true
            fi

            # [wsl2] altındaki memory= satırını tekilleştir; yoksa ekle
            if _ensure_wsl2_key_once "$wslconfig_path" "memory" "$target_memory"; then
                ok "WSL2: .wslconfig içinde memory satırı düzenlendi/eklendi."
                changed=true
            fi

            local cur_mem cur_mem_gb
            cur_mem=$(awk '
                BEGIN { in_wsl2=0 }
                /^\[.*\]$/ { in_wsl2 = ($0 == "[wsl2]") }
                in_wsl2 && /^memory=/ { sub(/^memory=/, "", $0); print; exit }
            ' "$wslconfig_path")
            cur_mem_gb=$(_parse_gb "$cur_mem")
            if [[ "$cur_mem_gb" -lt "$target_memory_gb" ]]; then
                warn "WSL2: .wslconfig memory=${cur_mem} — bu makine için düşük olabilir (önerilen: ${target_memory})."
            else
                ok "WSL2: .wslconfig memory=${cur_mem} — yeterli."
            fi

            # [wsl2] altındaki swap= satırını tekilleştir; yoksa ekle
            if _ensure_wsl2_key_once "$wslconfig_path" "swap" "$target_swap"; then
                ok "WSL2: .wslconfig içinde swap satırı düzenlendi/eklendi."
                changed=true
            fi

            local cur_swap cur_swap_gb
            cur_swap=$(awk '
                BEGIN { in_wsl2=0 }
                /^\[.*\]$/ { in_wsl2 = ($0 == "[wsl2]") }
                in_wsl2 && /^swap=/ { sub(/^swap=/, "", $0); print; exit }
            ' "$wslconfig_path")
            cur_swap_gb=$(_parse_gb "$cur_swap")
            if [[ "$cur_swap_gb" -lt "$target_swap_gb" ]]; then
                warn "WSL2: .wslconfig swap=${cur_swap} — bu makine için düşük olabilir (önerilen: ${target_swap})."
            else
                ok "WSL2: .wslconfig swap=${cur_swap} — yeterli."
            fi

            if [[ "$changed" == true ]]; then
                WSLCONFIG_CHANGED=true
                info "Değişiklik sonrası PowerShell'de 'wsl --shutdown' çalıştırıp dağıtımı yeniden başlatın."
            fi
        fi
    else
        warn "WSL2: %UserProfile% yolu çözümlenemedi. .wslconfig dosyasını manuel yapılandırın:"
        echo "       %UserProfile%\\.wslconfig içeriği:"
        echo "       [wsl2]"
        echo "       memory=${target_memory}"
        echo "       swap=${target_swap}"
    fi
}

# ── 9. Dizinleri oluştur ──────────────────────────────────────────────────────
create_directories() {
    step "Proje Dizinleri"
    for dir in "${REQUIRED_DIRS[@]}"; do
        mkdir -p "$SCRIPT_DIR/$dir"
        chmod 755 "$SCRIPT_DIR/$dir" 2>/dev/null || true
    done

    local log_file="$SCRIPT_DIR/logs/sidar_system.log"
    if [[ -f "$log_file" && ! -w "$log_file" ]]; then
        chown "$(id -u):$(id -g)" "$log_file" 2>/dev/null || true
        chmod u+rw "$log_file" 2>/dev/null || true
    fi

    if [[ -f "$SCRIPT_DIR/run_tests.sh" ]]; then
        chmod +x "$SCRIPT_DIR/run_tests.sh"
    fi
    ok "Dizinler hazır: ${REQUIRED_DIRS[*]}"
}

# ── VS Code Çalışma Alanı Hazırlığı ──────────────────────────────────────────
setup_vscode_workspace() {
    step "VS Code Çalışma Alanı Hazırlığı"
    local vscode_dir="$SCRIPT_DIR/.vscode"

    mkdir -p "$vscode_dir"

    local python_path="$SCRIPT_DIR/.venv/bin/python"

    cat > "$vscode_dir/settings.json" <<EOF
{
    "python.defaultInterpreterPath": "${python_path}",
    "python.terminal.activateEnvironment": true,
    "terminal.integrated.defaultProfile.linux": "bash"
}
EOF

    ok "VS Code çalışma alanı yapılandırıldı (.vscode/settings.json)."
}

# ── 10. .env dosyası ──────────────────────────────────────────────────────────
# generate_secure_token scripts/install_modules altında modülerleştirildi.
# harden_database_credentials scripts/install_modules altında modülerleştirildi.
# sync_postgres_env_with_database_url scripts/install_modules altında modülerleştirildi.
# write_generated_default_database_url scripts/install_modules altında modülerleştirildi.
# ensure_database_url_defaults scripts/install_modules altında modülerleştirildi.
# ensure_rag_vector_backend_pgvector scripts/install_modules altında modülerleştirildi.
collect_api_keys_interactive() {
    local env_file="$1"

    if [[ "$NO_INTERACTION" == true ]]; then
        info "--ci/--no-interaction etkin: API anahtarı etkileşimli toplama adımı atlandı."
        return
    fi

    # ── Tüm kullanıcı girişi gerektiren anahtarlar (otomatik üretilenler hariç) ──
    local -a KEY_ORDER=(
        OPENAI_API_KEY GEMINI_API_KEY ANTHROPIC_API_KEY LITELLM_API_KEY HF_TOKEN
        GITHUB_TOKEN
        TAVILY_API_KEY GOOGLE_SEARCH_API_KEY GOOGLE_SEARCH_CX
        SLACK_TOKEN SLACK_APP_LEVEL_TOKEN SLACK_WEBHOOK_URL SLACK_DEFAULT_CHANNEL
        JIRA_URL JIRA_EMAIL JIRA_TOKEN JIRA_DEFAULT_PROJECT
        TEAMS_WEBHOOK_URL
    )
    local sidar_keys_file="${SIDAR_KEYS_FILE:-$HOME/.sidar_keys.env}"

    # Gruplar: "Başlık|KEY1,KEY2,..."  (her grup zenity'de ayrı form / whiptail'de bölüm)
    # NOT: GROUPS bash reserved değişkeni olduğundan API_GROUPS adı kullanılıyor.
    local -a API_GROUPS=(
        "AI Sağlayıcıları|OPENAI_API_KEY,GEMINI_API_KEY,ANTHROPIC_API_KEY,LITELLM_API_KEY,HF_TOKEN"
        "GitHub ve Web Arama|GITHUB_TOKEN,TAVILY_API_KEY,GOOGLE_SEARCH_API_KEY,GOOGLE_SEARCH_CX"
        "Slack|SLACK_TOKEN,SLACK_APP_LEVEL_TOKEN,SLACK_WEBHOOK_URL,SLACK_DEFAULT_CHANNEL"
        "Jira|JIRA_URL,JIRA_EMAIL,JIRA_TOKEN,JIRA_DEFAULT_PROJECT"
        "Microsoft Teams|TEAMS_WEBHOOK_URL"
    )

    _key_label() {
        case "$1" in
            OPENAI_API_KEY)        echo "OpenAI API Anahtarı" ;;
            GEMINI_API_KEY)        echo "Google Gemini API Anahtarı" ;;
            ANTHROPIC_API_KEY)     echo "Anthropic Claude API Anahtarı" ;;
            LITELLM_API_KEY)       echo "LiteLLM / OpenRouter API Anahtarı" ;;
            HF_TOKEN)              echo "HuggingFace Token" ;;
            GITHUB_TOKEN)          echo "GitHub Token (repo erişimi)" ;;
            TAVILY_API_KEY)        echo "Tavily Arama API Anahtarı" ;;
            GOOGLE_SEARCH_API_KEY) echo "Google Custom Search API Anahtarı" ;;
            GOOGLE_SEARCH_CX)      echo "Google Search Engine ID (cx)" ;;
            SLACK_TOKEN)           echo "Slack Bot OAuth Token (xoxb-...)" ;;
            SLACK_APP_LEVEL_TOKEN) echo "Slack App Level Token (xapp-...) [opt]" ;;
            SLACK_WEBHOOK_URL)     echo "Slack Incoming Webhook URL [opt]" ;;
            SLACK_DEFAULT_CHANNEL) echo "Slack Varsayılan Kanal (örn: #sidar)" ;;
            JIRA_URL)              echo "Jira URL (örn: https://sirket.atlassian.net)" ;;
            JIRA_EMAIL)            echo "Jira Atlassian E-posta" ;;
            JIRA_TOKEN)            echo "Jira API Token" ;;
            JIRA_DEFAULT_PROJECT)  echo "Jira Proje Anahtarı (örn: SID)" ;;
            TEAMS_WEBHOOK_URL)     echo "Microsoft Teams Webhook URL" ;;
            *)                     echo "$1" ;;
        esac
    }

    # Anahtarı .env'e yazar; boşsa sessizce atlar
    _write_key() {
        local key="$1"
        local val
        val=$(printf '%s' "${2:-}" | tr -d '\r\n ')
        [[ -z "$val" ]] && return
        if grep -q "^${key}=" "$env_file" 2>/dev/null; then
            sed -i "s|^${key}=.*|${key}=${val}|" "$env_file"
        else
            echo "${key}=${val}" >> "$env_file"
        fi
        ok ".env: ${key} güncellendi."
    }

    _warn_if_missing_critical_provider_keys() {
        local openai_key=""
        local anthropic_key=""

        openai_key=$(grep -E '^OPENAI_API_KEY=' "$env_file" 2>/dev/null | head -n1 | cut -d= -f2- | tr -d '\r\n[:space:]' || true)
        anthropic_key=$(grep -E '^ANTHROPIC_API_KEY=' "$env_file" 2>/dev/null | head -n1 | cut -d= -f2- | tr -d '\r\n[:space:]' || true)

        if [[ -z "$openai_key" && -z "$anthropic_key" ]]; then
            warn "[UYARI] Kritik sağlayıcı anahtarı eksik: OPENAI_API_KEY veya ANTHROPIC_API_KEY alanlarından en az biri boş."
            warn "[UYARI] Kurulum durdurulmadı. Lütfen .env dosyasını sonradan manuel güncelleyin."
        fi
    }

    # ~/.sidar_keys.env gibi kalıcı bir dosyadan anahtarları içeri al.
    # Dosya varsa etkileşimli (zenity/whiptail/read) adımı tamamen atlanır.
    _import_api_keys_from_file() {
        local source_file="$1"
        local imported_count=0
        local key raw_val

        [[ -f "$source_file" ]] || return 1

        info "API anahtarları ${source_file} dosyasından içeri alınıyor (etkileşimli giriş atlanacak)..."
        for key in "${KEY_ORDER[@]}"; do
            raw_val=$(grep -E "^${key}=" "$source_file" 2>/dev/null | tail -n1 | cut -d= -f2- | tr -d '\r' || true)
            raw_val="${raw_val#"${raw_val%%[![:space:]]*}"}"
            raw_val="${raw_val%"${raw_val##*[![:space:]]}"}"

            # Basit tek satır tırnaklarını temizle: KEY="value" / KEY='value'
            if [[ "$raw_val" == \"*\" && "$raw_val" == *\" ]]; then
                raw_val="${raw_val:1:${#raw_val}-2}"
            elif [[ "$raw_val" == \'*\' && "$raw_val" == *\' ]]; then
                raw_val="${raw_val:1:${#raw_val}-2}"
            fi

            if [[ -n "$raw_val" ]]; then
                _write_key "$key" "$raw_val"
                ((imported_count += 1))
            fi
        done

        if (( imported_count > 0 )); then
            ok "${imported_count} API anahtarı ${source_file} üzerinden .env dosyasına aktarıldı."
        else
            warn "${source_file} bulundu ancak beklenen API anahtarlarından hiçbiri dolu değil."
        fi

        return 0
    }

    step "API Anahtarları Yapılandırması"
    echo ""

    if _import_api_keys_from_file "$sidar_keys_file"; then
        info "Kalıcı anahtar dosyası tespit edildiği için etkileşimli API anahtarı soruları atlandı."
        _warn_if_missing_critical_provider_keys
        return
    fi

    # ── Durum tespiti: doğrudan inline (subshell yok, \r temizlendi) ──────────
    local -a missing_keys=()
    local _chk_val
    for key in "${KEY_ORDER[@]}"; do
        _chk_val=$(grep -E "^${key}=" "$env_file" 2>/dev/null \
                   | head -n1 | cut -d= -f2- | tr -d '\r\n' || true)
        if [[ -z "$_chk_val" ]]; then
            missing_keys+=("$key")
            info "  [ eksik  ] ${key}"
        else
            ok   "  [ mevcut ] ${key}"
        fi
    done
    echo ""

    if [[ ${#missing_keys[@]} -eq 0 ]]; then
        ok "Tüm API anahtarları zaten tanımlı, devam ediliyor."
        return
    fi

    info "${#missing_keys[@]} anahtar eksik."
    info "Kullanmak istediğiniz servislerin anahtarlarını girin; kullanmayacaklarınızı boş bırakın."
    info "Sistemi yalnızca yerel Ollama ile kullanacaksanız hepsini boş bırakıp geçebilirsiniz."
    echo ""

    # Bir grubun eksik anahtarlarını döndürür (inline — subshell kullanmaz)
    _fill_group_missing() {
        # $1: virgülle ayrılmış grup anahtarları  $2: sonucu yazacağımız dizi adı (nameref)
        local -n _out_arr="$2"
        _out_arr=()
        local gk mk
        IFS=',' read -ra _gkeys <<< "$1"
        for gk in "${_gkeys[@]}"; do
            for mk in "${missing_keys[@]}"; do
                [[ "$mk" == "$gk" ]] && { _out_arr+=("$mk"); break; }
            done
        done
    }

    # ─── 1. Zenity GUI (WSLg / X11 ekranı varsa) ────────────────────────────
    local has_display=false
    [[ -n "${DISPLAY:-}" || -n "${WAYLAND_DISPLAY:-}" ]] && has_display=true

    if [[ "$has_display" == true ]] && ! command -v zenity &>/dev/null; then
        info "Grafik pencere için zenity kuruluyor..."
        sudo apt-get install -y zenity -qq >/dev/null 2>&1 || true
    fi

    if command -v zenity &>/dev/null && [[ "$has_display" == true ]]; then
        info "API anahtarı giriş pencereleri açılıyor (zenity — grup grup)..."
        local grp_spec grp_title grp_keys
        local -a grp_missing z_args _vals
        for grp_spec in "${API_GROUPS[@]}"; do
            grp_title="${grp_spec%%|*}"
            grp_keys="${grp_spec##*|}"
            _fill_group_missing "$grp_keys" grp_missing
            [[ ${#grp_missing[@]} -eq 0 ]] && continue

            z_args=(
                "--title=Sidar AI — ${grp_title}"
                "--text=${grp_title} için anahtarları girin.\nKullanmayacaklarınızı boş bırakın."
                "--separator=|"
            )
            local mk
            for mk in "${grp_missing[@]}"; do
                z_args+=("--add-entry=$(_key_label "$mk"):")
            done

            local zenity_out=""
            zenity_out=$(zenity --forms "${z_args[@]}" 2>/dev/null) || true
            [[ -z "$zenity_out" ]] && continue   # iptal / kapatıldı

            IFS='|' read -ra _vals <<< "$zenity_out"
            for i in "${!grp_missing[@]}"; do
                _write_key "${grp_missing[$i]}" "${_vals[$i]:-}"
            done
        done
        ok "API anahtarları kaydedildi, kurulum devam ediyor."
        _warn_if_missing_critical_provider_keys
        return
    fi

    # ─── 2. Whiptail TUI (terminal içi diyalog) ─────────────────────────────
    if command -v whiptail &>/dev/null; then
        info "Terminal tabanlı arayüz açılıyor (whiptail)..."
        local grp_spec grp_title grp_keys
        local -a grp_missing
        for grp_spec in "${API_GROUPS[@]}"; do
            grp_title="${grp_spec%%|*}"
            grp_keys="${grp_spec##*|}"
            _fill_group_missing "$grp_keys" grp_missing
            [[ ${#grp_missing[@]} -eq 0 ]] && continue

            whiptail --title "Sidar AI — API Anahtarları" \
                --msgbox "── ${grp_title} ──\n\nBu gruba ait anahtarları girmeniz istenecek.\nKullanmayacaklarınızı boş bırakabilirsiniz." \
                9 68 2>/dev/null || true

            local mk lbl input
            for mk in "${grp_missing[@]}"; do
                lbl="$(_key_label "$mk")"
                input=""
                input=$(whiptail \
                    --title "Sidar AI — ${grp_title}" \
                    --inputbox "${lbl}\n(Boş bırakmak için doğrudan Enter'a basın)" \
                    10 72 "" \
                    3>&1 1>&2 2>&3) || true
                _write_key "$mk" "$input"
            done
        done
        ok "API anahtar girişi tamamlandı, kurulum devam ediyor."
        _warn_if_missing_critical_provider_keys
        return
    fi

    # ─── 3. Basit read (her ortamda çalışır, fallback) ──────────────────────
    info "API anahtarlarını girin (boş bırakmak için doğrudan Enter'a basın):"
    echo ""
    local grp_spec grp_title grp_keys
    local -a grp_missing
    for grp_spec in "${API_GROUPS[@]}"; do
        grp_title="${grp_spec%%|*}"
        grp_keys="${grp_spec##*|}"
        _fill_group_missing "$grp_keys" grp_missing
        [[ ${#grp_missing[@]} -eq 0 ]] && continue

        echo -e "${BOLD}${BLUE}  ── ${grp_title} ──${NC}"
        local mk lbl input
        for mk in "${grp_missing[@]}"; do
            lbl="$(_key_label "$mk")"
            printf "  %-46s : " "$lbl"
            input=""
            # Gizli giriş: anahtarlar terminalde görünmez; satır düzeni için ardından echo basılır.
            IFS= read -rs input || true
            echo ""
            _write_key "$mk" "$input"
        done
        echo ""
    done
    ok "API anahtar girişi tamamlandı, kurulum devam ediyor."
    _warn_if_missing_critical_provider_keys
}

report_env_api_key_status() {
    local env_file="$1"
    local -a key_order=(
        OPENAI_API_KEY GEMINI_API_KEY ANTHROPIC_API_KEY LITELLM_API_KEY HF_TOKEN GITHUB_TOKEN
        TAVILY_API_KEY GOOGLE_SEARCH_API_KEY GOOGLE_SEARCH_CX
        SLACK_TOKEN SLACK_APP_LEVEL_TOKEN SLACK_WEBHOOK_URL SLACK_DEFAULT_CHANNEL
        JIRA_URL JIRA_EMAIL JIRA_TOKEN JIRA_DEFAULT_PROJECT
        TEAMS_WEBHOOK_URL
    )

    ENV_API_KEYS_TOTAL="${#key_order[@]}"
    ENV_API_KEYS_FILLED=0
    ENV_API_KEYS_MISSING=()

    local key value
    for key in "${key_order[@]}"; do
        value=$(grep -E "^${key}=" "$env_file" 2>/dev/null \
                | head -n1 | cut -d= -f2- | tr -d '\r\n' || true)
        if [[ -n "$value" ]]; then
            ((ENV_API_KEYS_FILLED+=1))
        else
            ENV_API_KEYS_MISSING+=("$key")
        fi
    done
}

validate_runtime_env_loading() {
    local env_file="$SCRIPT_DIR/.env"

    step "Runtime .env Enjeksiyon Kontrolü"
    info "Yükleme zinciri: .env, .env.advanced, .env.\${SIDAR_ENV}, DOTENV_FILE, SIDAR_KEYS_FILE (proses env korunur; secret dosyası en sonda)"

    if ! command -v uv &>/dev/null; then
        warn "uv bulunamadı; runtime env enjeksiyon kontrolü atlandı. Önce uv sync --all-extras çalıştırın."
        return 0
    fi

    if [[ ! -f "$env_file" ]]; then
        warn ".env bulunamadı; runtime yalnız proses env ve opsiyonel DOTENV_FILE/SIDAR_KEYS_FILE ile başlayacak."
    fi

    if ! (cd "$SCRIPT_DIR" && uv run python - <<'PY_RUNTIME_ENV_CHECK'
from __future__ import annotations

import config

print("ℹ️ Runtime dotenv yükleme raporu:")
for event in config.get_dotenv_load_report():
    label = event.get("label", "unknown")
    path = event.get("path") or event.get("raw_path") or "-"
    status = "loaded" if event.get("loaded") else f"skipped:{event.get('reason') or 'not_loaded'}"
    override = "override" if event.get("override") else "no-override"
    print(f"  - {label}: {status} ({override}) {path}")

missing = config.Config.get_missing_critical_runtime_keys()
if missing:
    print(
        "⚠️ Kritik runtime anahtarları çözülemedi: "
        + ", ".join(missing)
        + ". Değerleri .env, .env.advanced, DOTENV_FILE veya SIDAR_KEYS_FILE içine ekleyin."
    )
else:
    print("✅ Kritik runtime anahtarları dotenv yükleme zincirinden başarıyla çözüldü.")
PY_RUNTIME_ENV_CHECK
    ); then
        warn "Runtime env enjeksiyon kontrolü tamamlanamadı; uygulama başlatmadan önce .env/DOTENV_FILE/SIDAR_KEYS_FILE değerlerini kontrol edin."
        return 0
    fi
}

ensure_env_file_secrets_after_uv_sync() {
    local env_file="$SCRIPT_DIR/.env"
    local example_file="$SCRIPT_DIR/.env.example"

    # uv venv / uv sync tamamlanır tamamlanmaz temel .env dosyasını hazırla.
    # Bu adım bilinçli olarak interaktif değildir; kullanıcıyı manuel secret
    # üretme yükünden kurtarır ve sonraki setup_env_file doğrulamasına sağlam
    # başlangıç değerleri bırakır.
    if [[ ! -f "$env_file" ]]; then
        if [[ -f "$example_file" ]]; then
            cp "$example_file" "$env_file"
            ok ".env dosyası uv sync sonrası .env.example üzerinden oluşturuldu."
        else
            : > "$env_file"
            warn ".env.example bulunamadı; boş .env oluşturuldu ve secret alanları eklenecek."
        fi
    elif [[ ! -s "$env_file" && -f "$example_file" ]]; then
        cp "$example_file" "$env_file"
        ok "Boş .env dosyası uv sync sonrası .env.example ile dolduruldu."
    fi

    ensure_sidar_env_default "$env_file"
    ensure_auto_secrets "$env_file"
}

# ── Otomatik Secret Üretimi ────────────────────────────────────────────────
# Güvenlik anahtarlarını (API_KEY, JWT_SECRET_KEY, MEMORY_ENCRYPTION_KEY vb.)
# .env boşsa veya bilinen güvensiz örnekse otomatik üretir.
# Hem yeni oluşturulan hem de mevcut .env üzerinde çalışır.
ensure_auto_secrets() {
    local env_file="$1"

    # Boş, eksik veya bilinen güvensiz değer mi? → 0 (true) döner
    _is_missing_or_insecure() {
        local key="$1"; shift
        local val
        val=$(grep -E "^${key}=" "$env_file" 2>/dev/null \
              | head -n1 | cut -d= -f2- | tr -d '\r\n' || true)
        is_weak_secret_value "$val" && return 0
        local bad
        for bad in "$@"; do [[ "$val" == "$bad" ]] && return 0; done
        return 1
    }

    # Üretilen değeri .env'e yazar (varsa günceller, yoksa satır ekler)
    _write_secret() {
        local key="$1" val="$2"
        if grep -q "^${key}=" "$env_file" 2>/dev/null; then
            sed -i "s|^${key}=.*|${key}=${val}|" "$env_file"
        else
            echo "${key}=${val}" >> "$env_file"
        fi
    }

    # urlsafe token üretici (python3 → openssl fallback)
    _gen_urlsafe() {
        local n="$1"
        if command -v python3 &>/dev/null; then
            python3 -c "import secrets; print(secrets.token_urlsafe($n))" 2>/dev/null || true
        elif command -v openssl &>/dev/null; then
            openssl rand -base64 "$n" 2>/dev/null | tr '+/' '-_' | tr -d '\n=' || true
        fi
    }

    # hex token üretici
    _gen_hex() {
        local bits="$1"
        if command -v python3 &>/dev/null; then
            python3 -c "import secrets; print(secrets.token_hex($((bits / 2))))" 2>/dev/null || true
        elif command -v openssl &>/dev/null; then
            openssl rand -hex "$((bits / 2))" 2>/dev/null | tr -d '\n' || true
        fi
    }

    # Fernet anahtarı üretici
    _gen_fernet() {
        python3 - 2>/dev/null <<'PY' || true
try:
    from cryptography.fernet import Fernet
    print(Fernet.generate_key().decode())
except Exception:
    pass
PY
    }

    # ── POSTGRES_PASSWORD ────────────────────────────────────────────────────
    if _is_missing_or_insecure "POSTGRES_PASSWORD" \
        "change-me-to-a-strong-password" "replace-with-a-strong-24-plus-character-password"; then
        local _v; _v=$(_gen_urlsafe 24)
        if [[ -n "$_v" ]]; then
            _write_secret "POSTGRES_PASSWORD" "$_v"
            ok ".env: POSTGRES_PASSWORD otomatik ve güvenli bir değerle oluşturuldu."
        else
            warn "POSTGRES_PASSWORD otomatik üretilemedi. Lütfen .env içinde güçlü bir değer tanımlayın."
        fi
    fi

    # ── API_KEY ──────────────────────────────────────────────────────────────
    if _is_missing_or_insecure "API_KEY" \
        "uyaL0M3t5hHt0dj5ous7-oScvna9HH9pV6CneB5hYJw"; then
        local _v; _v=$(_gen_urlsafe 32)
        if [[ -n "$_v" ]]; then
            _write_secret "API_KEY" "$_v"
            ok ".env: API_KEY otomatik ve güvenli bir değerle oluşturuldu."
        else
            warn "API_KEY otomatik üretilemedi. Lütfen .env içinde güçlü bir değer tanımlayın."
        fi
    fi

    # ── JWT_SECRET_KEY ────────────────────────────────────────────────────────
    if _is_missing_or_insecure "JWT_SECRET_KEY" \
        "Lipg1iwRX5USyUaEt06ctbmnUQnYdywHcgW3y8Rif24fYvNiKX8V5xSQ3m1XOhpx6UuF9X6BGSekm8m_a3jQcg"; then
        local _v; _v=$(_gen_urlsafe 64)
        if [[ -n "$_v" ]]; then
            _write_secret "JWT_SECRET_KEY" "$_v"
            ok ".env: JWT_SECRET_KEY otomatik ve güvenli bir değerle oluşturuldu."
        else
            warn "JWT_SECRET_KEY otomatik üretilemedi. Lütfen .env içinde güçlü bir değer tanımlayın."
        fi
    fi

    # ── MEMORY_ENCRYPTION_KEY (Fernet) ────────────────────────────────────────
    if _is_missing_or_insecure "MEMORY_ENCRYPTION_KEY" \
        "vQYaMh2gwGHuEzCfG8638aVcBfQX4xLJ8d8uJzBWfW8="; then
        local _v; _v=$(_gen_fernet)
        if [[ -n "$_v" ]]; then
            _write_secret "MEMORY_ENCRYPTION_KEY" "$_v"
            ok ".env: MEMORY_ENCRYPTION_KEY (Fernet) otomatik üretildi."
        else
            warn "MEMORY_ENCRYPTION_KEY otomatik üretilemedi. Lütfen .env içinde geçerli bir Fernet anahtarı tanımlayın."
        fi
    fi

    # ── Hex tabanlı webhook/federation secret'lar ─────────────────────────────
    _auto_hex_secret() {
        local key="$1" bits="${2:-64}"; shift 2
        if _is_missing_or_insecure "$key" "$@"; then
            local _v; _v=$(_gen_hex "$bits")
            if [[ -n "$_v" ]]; then
                _write_secret "$key" "$_v"
                ok ".env: ${key} otomatik ve güvenli bir değerle oluşturuldu."
            else
                warn "${key} otomatik üretilemedi. Lütfen .env içinde güçlü bir değer tanımlayın."
            fi
        fi
    }

    _auto_hex_secret "AUTONOMY_WEBHOOK_SECRET" 64 \
        "a4313adde181fddef87f03ebff7fbf8f2f9f27d58b7ad8d0fa1cb5fc7e8d43ac"
    _auto_hex_secret "SWARM_FEDERATION_SHARED_SECRET" 64 \
        "aeaac3534fe2f97f2147be6f756ea8f4500f4d0f0f5ef758f6f7798f7d8a3f1b"
    _auto_hex_secret "GITHUB_WEBHOOK_SECRET" 40 \
        "69df1db55791dd991a3197958f5fce4ea0ed47e3"

    # ── GRAFANA_ADMIN_PASSWORD ────────────────────────────────────────────────
    if _is_missing_or_insecure "GRAFANA_ADMIN_PASSWORD" "admin" "sidar" "password" "changeme"; then
        local _v; _v=$(_gen_urlsafe 32)
        if [[ -n "$_v" ]]; then
            _write_secret "GRAFANA_ADMIN_PASSWORD" "$_v"
            ok ".env: GRAFANA_ADMIN_PASSWORD otomatik ve güvenli bir değerle oluşturuldu."
        else
            warn "GRAFANA_ADMIN_PASSWORD otomatik üretilemedi. Lütfen .env içinde güçlü bir değer tanımlayın."
        fi
    fi

    # ── METRICS_TOKEN ─────────────────────────────────────────────────────────
    # /metrics uçlarını koruyan Bearer token; .env.example'daki örnek değer güvensizdir.
    if _is_missing_or_insecure "METRICS_TOKEN" \
        "H4gi2982LlyRXyO1hPusH4XWvcYM44yp35TjGlF6JDw"; then
        local _v; _v=$(_gen_urlsafe 32)
        if [[ -n "$_v" ]]; then
            _write_secret "METRICS_TOKEN" "$_v"
            ok ".env: METRICS_TOKEN otomatik ve güvenli bir değerle oluşturuldu."
        else
            warn "METRICS_TOKEN otomatik üretilemedi. Lütfen .env içinde güçlü bir değer tanımlayın."
        fi
    fi
}

ensure_local_service_host_defaults() {
    local env_file="$1"
    # Lokal kurulumda Docker hostname yerine localhost kullan
    if grep -q '^REDIS_URL=redis://redis:6379/0' "$env_file"; then
        sed -i 's|^REDIS_URL=redis://redis:6379/0|REDIS_URL=redis://localhost:6379/0|' "$env_file"
        ok ".env: REDIS_URL lokal ortam için localhost olarak güncellendi."
    fi

    if grep -q '^OTEL_EXPORTER_ENDPOINT=http://jaeger:' "$env_file"; then
        sed -i 's|^OTEL_EXPORTER_ENDPOINT=http://jaeger:|OTEL_EXPORTER_ENDPOINT=http://localhost:|' "$env_file"
        ok ".env: OTEL_EXPORTER_ENDPOINT lokal ortam için localhost olarak güncellendi."
    fi
}

ensure_sidar_env_default() {
    local env_file="$1"
    local current_env=""

    current_env=$(grep -E '^SIDAR_ENV=' "$env_file" | head -n1 | cut -d= -f2- || true)
    current_env=$(echo "$current_env" | tr -d '"'\''[:space:]')

    if [[ -z "$current_env" ]]; then
        echo "SIDAR_ENV=development" >> "$env_file"
        ok ".env: SIDAR_ENV=development eklendi."
        return
    fi

    if [[ "$current_env" == "production" ]]; then
        sed -i 's/^SIDAR_ENV=.*/SIDAR_ENV=development/' "$env_file"
        warn ".env: SIDAR_ENV=production varsayılanı development olarak düzeltildi (üretimde manuel production yapın)."
    fi
}

prompt_post_install_sidar_env_mode() {
    local env_file="$SCRIPT_DIR/.env"
    local example_file="$SCRIPT_DIR/.env.example"
    local env_choice=""
    local selected_env="development"

    step "Kurulum Sonrası Uygulama Ortamı Seçimi"

    # Emniyet ağı: .env herhangi bir nedenle yoksa örnek dosyadan oluştur.
    if [[ ! -f "$env_file" ]]; then
        if [[ -f "$example_file" ]]; then
            cp "$example_file" "$env_file"
            ok ".env dosyası .env.example üzerinden oluşturuldu."
        else
            warn ".env.example bulunamadı; SIDAR_ENV güncellemesi atlanıyor."
            return
        fi
    fi

    if [[ "$AUTO_ENV_TYPE" != "ask" ]]; then
        selected_env="$AUTO_ENV_TYPE"
        info "AUTO_INSTALL: ENV_TYPE=$selected_env olarak uygulandı."
    elif [[ "$NO_INTERACTION" == true ]]; then
        info "--ci/--no-interaction etkin: SIDAR_ENV varsayılanı development bırakıldı."
    else
        echo ""
        echo "======================================================"
        echo "✅ Kurulum işlemleri tamamlandı!"
        echo "Sistemi hangi modda çalıştırmak istiyorsunuz?"
        echo "  1) Development (Geliştirme ve Test - Debug logları açık)"
        echo "  2) Production  (Canlı Kullanım - Hızlı, güvenli, optimize)"
        echo "======================================================"

        if read -r -t 180 -p "Seçiminiz (1 veya 2, varsayılan=1): " env_choice; then
            :
        else
            warn "180 saniye içinde seçim yapılmadı. Varsayılan seçim: 1 (Development)."
            env_choice="1"
        fi

        if [[ "$env_choice" == "2" ]]; then
            selected_env="production"
        fi
    fi

    if grep -qE '^SIDAR_ENV=' "$env_file"; then
        sed -i "s/^SIDAR_ENV=.*/SIDAR_ENV=$selected_env/" "$env_file"
    else
        echo "SIDAR_ENV=$selected_env" >> "$env_file"
    fi

    if [[ "$selected_env" == "production" ]]; then
        ok "🚀 Ortam değişkenleri 'Production' (Canlı Kullanım) olarak güncellendi."
    else
        ok "🛠️ Ortam değişkenleri 'Development' (Geliştirme) olarak güncellendi."
    fi

    ok "Sidar kullanıma hazır!"
}


get_env_value() {
    local env_file="$1" key="$2"
    grep -E "^${key}=" "$env_file" 2>/dev/null | head -n1 | cut -d= -f2- | tr -d '\r' || true
}

is_weak_secret_value() {
    local value="${1:-}"
    [[ -n "${value//[[:space:]]/}" ]] || return 0
    case "${value,,}" in
        sidar|admin|password|changeme|change_me|change-me*|replace-with-*|secret|default|test|example|postgres|root|123456|12345678)
            return 0
            ;;
    esac
    (( ${#value} < 24 )) && return 0
    return 1
}

validate_required_security_profile() {
    local env_file="$1"
    local api_key memory_key access_level db_password database_url pg_password grafana_password
    api_key="$(get_env_value "$env_file" API_KEY)"
    memory_key="$(get_env_value "$env_file" MEMORY_ENCRYPTION_KEY)"
    access_level="$(get_env_value "$env_file" ACCESS_LEVEL)"
    database_url="$(get_env_value "$env_file" DATABASE_URL)"
    pg_password="$(get_env_value "$env_file" POSTGRES_PASSWORD)"
    grafana_password="$(get_env_value "$env_file" GRAFANA_ADMIN_PASSWORD)"

    if is_weak_secret_value "$api_key"; then
        fail ".env güvenlik doğrulaması başarısız: API_KEY boş veya zayıf. Güçlü bir token tanımlayın."
    fi

    if [[ -z "$memory_key" ]]; then
        fail ".env güvenlik doğrulaması başarısız: MEMORY_ENCRYPTION_KEY boş. Geçerli Fernet anahtarı zorunludur."
    fi
    if ! python3 - "$memory_key" <<'PYFERNET'
import sys
from cryptography.fernet import Fernet
Fernet(sys.argv[1].encode())
PYFERNET
    then
        fail ".env güvenlik doğrulaması başarısız: MEMORY_ENCRYPTION_KEY geçerli Fernet anahtarı değil."
    fi

    if [[ "${access_level,,}" == "full" && "$ALLOW_FULL_ACCESS" != true ]]; then
        fail "ACCESS_LEVEL=full yalnız açık onayla kullanılabilir. Riskleri kabul ediyorsanız --i-understand-full-access bayrağını verin."
    fi

    db_password="$(python3 - "$database_url" <<'PYDB' 2>/dev/null || true
import sys
from urllib.parse import urlparse, unquote
url = sys.argv[1]
if url:
    print(unquote(urlparse(url).password or ""))
PYDB
)"
    if [[ -n "$database_url" ]] && is_weak_secret_value "$db_password"; then
        fail ".env güvenlik doğrulaması başarısız: DATABASE_URL içindeki veritabanı parolası boş veya zayıf."
    fi
    if is_weak_secret_value "$pg_password"; then
        fail ".env güvenlik doğrulaması başarısız: POSTGRES_PASSWORD boş veya zayıf."
    fi
    if is_weak_secret_value "$grafana_password"; then
        fail ".env güvenlik doğrulaması başarısız: GRAFANA_ADMIN_PASSWORD boş veya zayıf."
    fi
}

setup_env_file() {
    step ".env Yapılandırması"
    ENV_FILE="$SCRIPT_DIR/.env"
    EXAMPLE_FILE="$SCRIPT_DIR/.env.example"

    if [[ -f "$ENV_FILE" ]]; then
        ok ".env dosyası zaten mevcut — varsayılanlar ve güvenlik anahtarları kontrol ediliyor."
        ensure_sidar_env_default "$ENV_FILE"
        ensure_database_url_defaults "$ENV_FILE"
        ensure_rag_vector_backend_pgvector "$ENV_FILE"
        harden_database_credentials "$ENV_FILE"
        sync_postgres_env_with_database_url "$ENV_FILE"
        ensure_local_service_host_defaults "$ENV_FILE"
        ensure_auto_secrets "$ENV_FILE"
        validate_required_security_profile "$ENV_FILE"
        collect_api_keys_interactive "$ENV_FILE"
        report_env_api_key_status "$ENV_FILE"
        validate_runtime_env_loading
        return
    fi

    if [[ ! -f "$EXAMPLE_FILE" ]]; then
        warn ".env.example bulunamadı — .env oluşturulamadı. Manuel olarak oluşturun."
        return
    fi

    cp "$EXAMPLE_FILE" "$ENV_FILE"
    ok ".env dosyası .env.example'dan oluşturuldu."
    ensure_sidar_env_default "$ENV_FILE"
    ensure_database_url_defaults "$ENV_FILE"
    ensure_rag_vector_backend_pgvector "$ENV_FILE"
    harden_database_credentials "$ENV_FILE"
    sync_postgres_env_with_database_url "$ENV_FILE"
    ensure_local_service_host_defaults "$ENV_FILE"

    # Güvenlik secret'larını üret/doğrula (her iki yolda da çalışan üst-düzey fonksiyon)
    ensure_auto_secrets "$ENV_FILE"
    validate_required_security_profile "$ENV_FILE"

    # GPU tespitine göre USE_GPU/GPU_MIXED_PRECISION değerlerini uyumlu hale getir
    if command -v sed &>/dev/null; then
        if [[ "$GPU_AVAILABLE" == true ]]; then
            sed -i 's/^USE_GPU=false/USE_GPU=true/' "$ENV_FILE"
            sed -i 's/^GPU_MIXED_PRECISION=false/GPU_MIXED_PRECISION=true/' "$ENV_FILE"

            # Docker için GPU modunu ön tanımlı yap
            if grep -q '^COMPOSE_PROFILES=' "$ENV_FILE"; then
                sed -i 's/^COMPOSE_PROFILES=.*/COMPOSE_PROFILES=gpu/' "$ENV_FILE"
            else
                echo "COMPOSE_PROFILES=gpu" >> "$ENV_FILE"
            fi

            ok ".env: USE_GPU=true, GPU_MIXED_PRECISION=true (GPU tespit edildi)"
            ok ".env: COMPOSE_PROFILES=gpu ayarlandı (Docker GPU modu artık varsayılan)."
        else
            sed -i 's/^USE_GPU=true/USE_GPU=false/' "$ENV_FILE"
            if grep -q '^COMPOSE_PROFILES=' "$ENV_FILE"; then
                sed -i 's/^COMPOSE_PROFILES=.*/COMPOSE_PROFILES=cpu/' "$ENV_FILE"
            else
                echo "COMPOSE_PROFILES=cpu" >> "$ENV_FILE"
            fi
            ok ".env: USE_GPU=false, COMPOSE_PROFILES=cpu ayarlandı."
        fi
    fi

    # Docker + GPU tespit edildiyse NVIDIA runtime'ı varsayılan yap
    if [[ "$GPU_AVAILABLE" == true ]] && command -v docker &>/dev/null && command -v sed &>/dev/null; then
        if grep -q '^DOCKER_RUNTIME=' "$ENV_FILE"; then
            sed -i 's/^DOCKER_RUNTIME=.*/DOCKER_RUNTIME=nvidia/' "$ENV_FILE"
        else
            echo 'DOCKER_RUNTIME=nvidia' >> "$ENV_FILE"
        fi

        if grep -q '^DOCKER_ALLOWED_RUNTIMES=' "$ENV_FILE"; then
            if ! grep -q '^DOCKER_ALLOWED_RUNTIMES=.*nvidia' "$ENV_FILE"; then
                sed -i 's/^DOCKER_ALLOWED_RUNTIMES=.*/DOCKER_ALLOWED_RUNTIMES=runc,runsc,kata-runtime,nvidia/' "$ENV_FILE"
            fi
        else
            echo 'DOCKER_ALLOWED_RUNTIMES=runc,runsc,kata-runtime,nvidia' >> "$ENV_FILE"
        fi

        ok ".env: Docker GPU varsayılanları ayarlandı (DOCKER_RUNTIME=nvidia)."
    fi

    collect_api_keys_interactive "$ENV_FILE"
    report_env_api_key_status "$ENV_FILE"
    validate_runtime_env_loading
}

# ── 11. Ollama modelleri ─────────────────────────────────────────────────────

run_coding_model_smoke_prompt() {
    local model_name="${1:-}"
    local ollama_base_url="${2:-}"
    local response_file=""
    local response_text=""

    [[ -n "$model_name" ]] || model_name="qwen2.5-coder:7b"
    [[ -n "$ollama_base_url" ]] || ollama_base_url="http://localhost:11434"
    response_file=$(mktemp)

    info "Coding model JSON smoke testi çalışıyor (${model_name})..."
    if ! curl -fsS --max-time 75 \
        -H 'Content-Type: application/json' \
        -d "{\"model\":\"${model_name}\",\"prompt\":\"Return exactly this JSON and nothing else: {\\\"sidar_smoke\\\": true}\",\"stream\":false,\"format\":\"json\"}" \
        "${ollama_base_url%/}/api/generate" > "$response_file"; then
        rm -f "$response_file"
        fail "Coding model JSON smoke testi başarısız: Ollama generate çağrısı yanıt vermedi (${model_name})."
    fi

    response_text=$(python3 - "$response_file" <<'PYSMOKE' 2>/dev/null || true
import json
import sys
payload = json.loads(open(sys.argv[1], encoding="utf-8").read())
print(payload.get("response", ""))
PYSMOKE
)
    rm -f "$response_file"

    if ! python3 - "$response_text" <<'PYJSON' >/dev/null 2>&1
import json
import sys
parsed = json.loads(sys.argv[1])
raise SystemExit(0 if parsed.get("sidar_smoke") is True else 1)
PYJSON
    then
        fail "Coding model JSON smoke testi başarısız: model geçerli JSON çıktı üretmedi. Yanıt: ${response_text:0:200}"
    fi

    ok "Coding model JSON smoke testi başarılı (${model_name})."
}

# download_ollama_models scripts/install_modules altında modülerleştirildi.
run_migrations() {
    step "Veritabanı Migrasyonları"
    ALEMBIC_INI="$SCRIPT_DIR/alembic.ini"
    ENV_FILE="$SCRIPT_DIR/.env"

    if [[ ! -f "$ALEMBIC_INI" ]]; then
        warn "alembic.ini bulunamadı — migrasyon atlandı."
        MIGRATION_STATUS="alembic_yok"
        return
    fi

    DB_URL=""
    if [[ -f "$ENV_FILE" ]]; then
        DB_URL=$(grep -E '^DATABASE_URL=' "$ENV_FILE" 2>/dev/null | head -n1 | cut -d= -f2- || true)
    fi

    cd "$SCRIPT_DIR"

    ALEMBIC_PYTHON=""
    if command -v python3 &>/dev/null; then
        ALEMBIC_PYTHON="python3"
    elif command -v python &>/dev/null; then
        ALEMBIC_PYTHON="python"
    else
        fail "Python yorumlayıcısı bulunamadı. python3 kurup yeniden deneyin (örn. sudo apt-get install -y python3)."
    fi
    ALEMBIC_CMD=("$ALEMBIC_PYTHON" -m alembic upgrade head)

    if [[ -z "$DB_URL" ]]; then
        warn "DATABASE_URL bulunamadı — otomatik migrasyon atlandı."
        info "Veritabanını başlattıktan sonra manuel çalıştırın: ${ALEMBIC_PYTHON} -m alembic upgrade head"
        MIGRATION_STATUS="db_url_yok"
        return
    fi

    # Güvenlik: DB_URL içindeki parolayı loglarda maskele
    local masked_db_url="$DB_URL"
    if [[ "$DB_URL" =~ ^(postgresql(\+asyncpg)?://[^:/?#]+:)([^@]+)(@.+)$ ]]; then
        masked_db_url="${BASH_REMATCH[1]}***${BASH_REMATCH[4]}"
    fi
    info "DATABASE_URL: $masked_db_url"

    if [[ "$DOCKER_ONLY" == true ]]; then
        DOCKER_COMPOSE_CMD=()
        if command -v docker &>/dev/null && docker compose version &>/dev/null; then
            DOCKER_COMPOSE_CMD=(docker compose)
        elif command -v docker-compose &>/dev/null; then
            DOCKER_COMPOSE_CMD=(docker-compose)
        fi
        if [[ ${#DOCKER_COMPOSE_CMD[@]} -gt 0 ]]; then
            info "--docker-only: PostgreSQL/Redis Docker servisleri başlatılıyor..."
            start_docker_services_or_fail "${DOCKER_COMPOSE_CMD[@]}" -- postgres redis
            DOCKER_DB_SERVICES_STARTED=true
            wait_for_compose_services_health "${DOCKER_COMPOSE_CMD[@]}" -- postgres redis || warn "Compose healthcheck bekleme başarısız; klasik bağlantı kontrolleriyle devam edilecek."
            wait_for_redis_ready_after_docker_start || warn "Redis hazır kontrolü başarısız; sonraki adımlarda bağlantı hatası oluşabilir."
        else
            fail "--docker-only aktif ancak docker compose bulunamadı. Migrasyon öncesi servisler başlatılamıyor."
        fi
    fi

    if [[ "$DB_URL" == postgresql* ]]; then
        if ! command -v pg_isready &>/dev/null; then
            warn "pg_isready bulunamadı — veritabanı erişilebilirliği doğrulanamadı, migrasyon atlandı."
            info "Veritabanını başlattıktan sonra manuel çalıştırın: ${ALEMBIC_PYTHON} -m alembic upgrade head"
            MIGRATION_STATUS="pg_isready_yok"
            return
        fi

        DB_CONN_INFO=$("$ALEMBIC_PYTHON" - "$DB_URL" <<'PY'
from urllib.parse import urlparse, unquote
import sys

url = sys.argv[1]
url = url.replace("postgresql+asyncpg://", "postgresql://", 1)
parsed = urlparse(url)

host = parsed.hostname or "localhost"
port = str(parsed.port or 5432)
user = unquote(parsed.username or "postgres")
password = unquote(parsed.password or "")
db = parsed.path.lstrip("/") or "postgres"

print(f"{host}|{port}|{user}|{db}|{password}")
PY
)

        DB_HOST=$(echo "$DB_CONN_INFO" | cut -d'|' -f1)
        DB_PORT=$(echo "$DB_CONN_INFO" | cut -d'|' -f2)
        DB_USER=$(echo "$DB_CONN_INFO" | cut -d'|' -f3)
        DB_NAME=$(echo "$DB_CONN_INFO" | cut -d'|' -f4)
        DB_PASSWORD=$(echo "$DB_CONN_INFO" | cut -d'|' -f5-)

        if ! pg_isready -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" >/dev/null 2>&1; then
            DOCKER_COMPOSE_CMD=()
            if command -v docker &>/dev/null && docker compose version &>/dev/null; then
                DOCKER_COMPOSE_CMD=(docker compose)
            elif command -v docker-compose &>/dev/null; then
                DOCKER_COMPOSE_CMD=(docker-compose)
            fi

            if [[ ("$DB_HOST" == "localhost" || "$DB_HOST" == "127.0.0.1") && ${#DOCKER_COMPOSE_CMD[@]} -gt 0 ]]; then
                if [[ "$MIGRATION_DOCKER_POLICY" == "disabled" ]]; then
                    info "Kullanıcı tercihi nedeniyle migrasyon sırasında Docker servisleri otomatik başlatılmayacak."
                else
                    info "PostgreSQL erişilemedi ($DB_HOST:$DB_PORT/$DB_NAME). Docker servisleri otomatik başlatılıyor..."
                    start_docker_services_or_fail "${DOCKER_COMPOSE_CMD[@]}" -- postgres redis
                    DOCKER_DB_SERVICES_STARTED=true
                    wait_for_compose_services_health "${DOCKER_COMPOSE_CMD[@]}" -- postgres redis || warn "Compose healthcheck bekleme başarısız; klasik bağlantı kontrolleriyle devam edilecek."
                    wait_for_redis_ready_after_docker_start || warn "Redis hazır kontrolü başarısız; migrasyon sırasında cache/bağlantı hataları görülebilir."
                    wait_for_postgres_ready_after_docker_start "$DB_HOST" "$DB_PORT" "$DB_USER" "$DB_NAME" "$DB_PASSWORD" || true
                fi
            fi

            if ! pg_isready -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" >/dev/null 2>&1; then
                warn "PostgreSQL erişilemedi ($DB_HOST:$DB_PORT/$DB_NAME) — migrasyon atlandı."
                if [[ ${#DOCKER_COMPOSE_CMD[@]} -gt 0 ]]; then
                    info "PostgreSQL log özeti (son 80 satır) alınıyor..."
                    "${DOCKER_COMPOSE_CMD[@]}" logs --tail 80 postgres || warn "PostgreSQL logları okunamadı."
                fi
                info "DB hazır olduktan sonra manuel çalıştırın: ${ALEMBIC_PYTHON} -m alembic upgrade head"
                MIGRATION_STATUS="db_erisilemez"
                if [[ "$MIGRATION_DOCKER_POLICY" == "disabled" ]]; then
                    warn "MIGRATION_DOCKER_POLICY=disabled olduğu için kurulum migrasyon olmadan devam ediyor."
                    return
                fi
                fail "Veritabanına erişilemediği için migrasyon tamamlanamadı. Kurulum güvenli şekilde durduruldu."
            fi
        fi

        local auth_check_rc=0
        verify_postgres_auth "$DB_HOST" "$DB_PORT" "$DB_USER" "$DB_NAME" "$DB_PASSWORD" || auth_check_rc=$?
        if [[ "$auth_check_rc" -eq 2 ]]; then
            warn "PostgreSQL kimlik doğrulaması doğrulanamadı (psql/asyncpg denetimi kullanılamadı). Alembic denenecek."
        elif [[ "$auth_check_rc" -eq 10 ]]; then
            warn "PostgreSQL erişilebilir ancak parola doğrulaması başarısız. Eski volume kaynaklı şifre uyuşmazlığı giderilmeye çalışılıyor."
            local -a recovery_password_candidates=()
            if [[ -n "${PRE_HARDEN_DB_PASSWORD:-}" ]]; then
                recovery_password_candidates+=("$PRE_HARDEN_DB_PASSWORD")
            fi
            recovery_password_candidates+=("sidar" "postgres" "password" "admin" "changeme" "123456")
            if try_recover_postgres_password_with_alter_user \
                "$DB_HOST" "$DB_PORT" "$DB_USER" "$DB_NAME" "$DB_PASSWORD" "${recovery_password_candidates[@]}"; then
                auth_check_rc=0
                verify_postgres_auth "$DB_HOST" "$DB_PORT" "$DB_USER" "$DB_NAME" "$DB_PASSWORD" || auth_check_rc=$?
                if [[ "$auth_check_rc" -eq 0 ]]; then
                    ok "ALTER USER kurtarma adımı sonrası PostgreSQL parola doğrulaması başarılı."
                fi
            fi

            if [[ "$auth_check_rc" -eq 10 ]]; then
                DOCKER_COMPOSE_CMD=()
                if command -v docker &>/dev/null && docker compose version &>/dev/null; then
                    DOCKER_COMPOSE_CMD=(docker compose)
                elif command -v docker-compose &>/dev/null; then
                    DOCKER_COMPOSE_CMD=(docker-compose)
                fi

                if [[ ("$DB_HOST" == "localhost" || "$DB_HOST" == "127.0.0.1") && ${#DOCKER_COMPOSE_CMD[@]} -gt 0 ]]; then
                    DB_PASSWORD_HARDENED=true
                    POSTGRES_VOLUME_RESET_DONE=false
                    if ! maybe_reset_postgres_volume_after_password_hardening "${DOCKER_COMPOSE_CMD[@]}" -- postgres redis; then
                        MIGRATION_STATUS="db_auth_hatasi"
                        fail "PostgreSQL volume sıfırlanamadı; eski parola ile çalışan volume nedeniyle migrasyon güvenli şekilde durduruldu."
                    fi
                    start_docker_services_or_fail "${DOCKER_COMPOSE_CMD[@]}" -- postgres redis
                    DOCKER_DB_SERVICES_STARTED=true
                    wait_for_compose_services_health "${DOCKER_COMPOSE_CMD[@]}" -- postgres redis || warn "Compose healthcheck bekleme başarısız; klasik bağlantı kontrolleriyle devam edilecek."
                    wait_for_redis_ready_after_docker_start || warn "Redis hazır kontrolü başarısız; migrasyon sırasında cache/bağlantı hataları görülebilir."

                    wait_for_postgres_ready_after_docker_start "$DB_HOST" "$DB_PORT" "$DB_USER" "$DB_NAME" "$DB_PASSWORD" || true

                    auth_check_rc=0
                    verify_postgres_auth "$DB_HOST" "$DB_PORT" "$DB_USER" "$DB_NAME" "$DB_PASSWORD" || auth_check_rc=$?
                    if [[ "$auth_check_rc" -eq 0 ]]; then
                        ok "PostgreSQL parola doğrulaması SELECT 1 ile başarılı."
                    fi
                fi
            fi
        fi

        if [[ "$auth_check_rc" -ne 0 && "$auth_check_rc" -ne 2 ]]; then
            warn "PostgreSQL kimlik doğrulama kontrolü başarısız: ${POSTGRES_AUTH_CHECK_ERROR:-bilinmeyen_hata}"
            MIGRATION_STATUS="db_auth_hatasi"
            fail "PostgreSQL kimlik doğrulaması başarısız olduğu için migrasyon güvenli şekilde durduruldu."
        fi
    fi

    # Shell belleğinde kalmış eski değişkenlerin .env değerlerini ezmesini engelle.
    unset DATABASE_URL
    unset POSTGRES_PASSWORD
    if [[ -f "$ENV_FILE" ]]; then
        local refreshed_db_url=""
        local refreshed_postgres_password=""
        refreshed_db_url=$(grep -E '^DATABASE_URL=' "$ENV_FILE" 2>/dev/null | head -n1 | cut -d= -f2- || true)
        refreshed_postgres_password=$(grep -E '^POSTGRES_PASSWORD=' "$ENV_FILE" 2>/dev/null | head -n1 | cut -d= -f2- || true)

        if [[ -n "$refreshed_db_url" ]]; then
            DB_URL="$refreshed_db_url"
            export DATABASE_URL="$refreshed_db_url"
        fi
        if [[ -n "$refreshed_postgres_password" ]]; then
            export POSTGRES_PASSWORD="$refreshed_postgres_password"
        fi
    fi

    ALEMBIC_CMD=(env "DATABASE_URL=$DB_URL" "$ALEMBIC_PYTHON" -m alembic upgrade head)

    local alembic_output_file=""
    alembic_output_file=$(mktemp)
    if "${ALEMBIC_CMD[@]}" \
        > >(tee -a "$alembic_output_file") \
        2> >(tee -a "$alembic_output_file" >&2); then
        rm -f "$alembic_output_file"
        ok "Alembic migrasyonları DATABASE_URL ile tamamlandı."
        MIGRATION_STATUS="tamamlandi"
    else
        warn "Alembic migrasyonu başarısız oldu. Hata özeti (son 120 satır):"
        tail -n 120 "$alembic_output_file" || true
        rm -f "$alembic_output_file"
        MIGRATION_STATUS="hata"
        fail "Migrasyon başarısız. Log'ları kontrol edin ve hatayı düzeltmeden kuruluma devam etmeyin."
    fi
}

prepare_docker_for_migrations() {
    local docker_compose_cmd=()

    if command -v docker &>/dev/null && docker compose version &>/dev/null; then
        docker_compose_cmd=(docker compose)
    elif command -v docker-compose &>/dev/null; then
        docker_compose_cmd=(docker-compose)
    else
        return
    fi

    if ! ensure_docker_daemon_running; then
        warn "Docker daemon erişilemediği için migrasyon öncesi PostgreSQL/Redis servisleri otomatik başlatılamadı."
        if [[ "$WSL2" == true ]]; then
            info "WSL2 için öneri: Docker Desktop > Settings > Resources > WSL Integration bölümünden Ubuntu entegrasyonunu açıp Apply & restart yapın."
        fi
        info "Docker hazır olduktan sonra manuel çalıştırın: ${docker_compose_cmd[*]} up -d postgres redis"
        MIGRATION_DOCKER_POLICY="disabled"
        return
    fi

    if [[ "$AUTO_START_DOCKER_SERVICES" == "true" ]]; then
        info "AUTO_INSTALL: START_DOCKER_SERVICES=true olduğu için migrasyon öncesi servisler otomatik başlatılıyor."
        start_docker_services_or_fail "${docker_compose_cmd[@]}" -- postgres redis
        DOCKER_DB_SERVICES_STARTED=true
        wait_for_compose_services_health "${docker_compose_cmd[@]}" -- postgres redis || warn "Compose healthcheck bekleme başarısız; klasik bağlantı kontrolleriyle devam edilecek."
        wait_for_redis_ready_after_docker_start || warn "Redis hazır kontrolü başarısız; smoke testlerden önce servis hazır olmayabilir."
        return
    elif [[ "$AUTO_START_DOCKER_SERVICES" == "false" ]]; then
        MIGRATION_DOCKER_POLICY="disabled"
        info "AUTO_INSTALL: START_DOCKER_SERVICES=false olduğu için migrasyon sırasında servis başlatma atlandı."
        return
    elif [[ "$NO_INTERACTION" == true ]]; then
        info "--ci/--no-interaction etkin: migrasyon öncesi PostgreSQL/Redis servisleri otomatik hazırlanıyor."
        start_docker_services_or_fail "${docker_compose_cmd[@]}" -- postgres redis
        DOCKER_DB_SERVICES_STARTED=true
        wait_for_compose_services_health "${docker_compose_cmd[@]}" -- postgres redis || warn "Compose healthcheck bekleme başarısız; klasik bağlantı kontrolleriyle devam edilecek."
        wait_for_redis_ready_after_docker_start || warn "Redis hazır kontrolü başarısız; smoke testlerden önce servis hazır olmayabilir."
        return
    fi

    echo ""
    start_for_migration=$(prompt_yes_no_with_timeout_default_yes "Migrasyon öncesi PostgreSQL/Redis Docker servisleri şimdi başlatılsın mı? [E/h] ")
    case "${start_for_migration:-E}" in
        [HhNn]*)
            MIGRATION_DOCKER_POLICY="disabled"
            info "Migrasyon sırasında Docker servisleri otomatik başlatma kapatıldı."
            ;;
        *)
            start_docker_services_or_fail "${docker_compose_cmd[@]}" -- postgres redis
            DOCKER_DB_SERVICES_STARTED=true
            wait_for_compose_services_health "${docker_compose_cmd[@]}" -- postgres redis || warn "Compose healthcheck bekleme başarısız; klasik bağlantı kontrolleriyle devam edilecek."
            wait_for_redis_ready_after_docker_start || warn "Redis hazır kontrolü başarısız; migrasyon sonrası test akışı etkilenebilir."
            ok "Migrasyon için PostgreSQL/Redis servisleri hazırlandı."
            ;;
    esac
}

# ── 13. CUDA bağlantı testi ──────────────────────────────────────────────────
verify_torch_cuda() {
    if [[ "$GPU_AVAILABLE" == true ]]; then
        step "PyTorch CUDA Doğrulaması"
        if python -c "import torch; exit(0 if torch.cuda.is_available() else 1)" >/dev/null 2>&1; then
                CUDA_OK=$(python -c "
import torch
avail = torch.cuda.is_available()
ver   = torch.version.cuda or 'N/A'
dev   = torch.cuda.get_device_name(0) if avail else 'N/A'
print(f'available={avail} cuda={ver} device={dev}')
" 2>/dev/null || echo "available=true cuda=N/A device=N/A")
            TORCH_CUDA_VER=$(echo "$CUDA_OK" | grep -oP 'cuda=\K[^ ]+')
            TORCH_GPU_NAME=$(echo "$CUDA_OK" | grep -oP 'device=\K.+')
            ok "PyTorch CUDA aktif: $TORCH_GPU_NAME (CUDA $TORCH_CUDA_VER)"
        else
            warn "PyTorch CUDA bulunamadı. torch CPU sürümü kurulmuş olabilir."
            info "GPU wheel için PyTorch yeniden kuruluyor (pyproject.toml içindeki [tool.uv] index ayarları kullanılarak)..."
            uv pip install torch torchvision torchaudio --reinstall

            if python -c "import torch; exit(0 if torch.cuda.is_available() else 1)" >/dev/null 2>&1; then
                ok "PyTorch CUDA başarıyla kuruldu ve GPU tanındı."
            else
                fail "PyTorch CUDA kurulumu yine başarısız oldu. Lütfen manuel kontrol edin."
            fi
        fi
    fi
}

# ── 14. Smoke testler ────────────────────────────────────────────────────────
wait_for_redis_before_smoke_tests() {
    local env_file="$SCRIPT_DIR/.env"
    local redis_url=""
    local redis_host=""
    local redis_port=""
    local redis_host_lc=""
    local redis_is_local=false
    local docker_start_attempted=false
    local -a docker_compose_cmd=()
    local -a python_cmd=()

    if [[ -f "$env_file" ]]; then
        redis_url=$(read_env_value_from_file "REDIS_URL" "$env_file")
    fi
    if [[ -z "$redis_url" ]]; then
        redis_url="redis://localhost:6379/0"
    fi

    if command -v python3 &>/dev/null; then
        python_cmd=(python3)
    elif command -v python &>/dev/null; then
        python_cmd=(python)
    else
        warn "Python bulunamadı; Redis hazır bekleme adımı atlandı."
        return 0
    fi

    if ! mapfile -t redis_conn < <("${python_cmd[@]}" - "$redis_url" <<'PY'
from urllib.parse import urlparse
import sys

url = (sys.argv[1] or "").strip()
if not url:
    print("localhost")
    print("6379")
    raise SystemExit(0)

parsed = urlparse(url)
host = parsed.hostname or "localhost"
port = parsed.port or 6379
print(host)
print(str(port))
PY
); then
        warn "REDIS_URL ayrıştırılamadı ($redis_url); Redis hazır bekleme adımı atlandı."
        return 0
    fi

    redis_host="${redis_conn[0]:-localhost}"
    redis_port="${redis_conn[1]:-6379}"
    redis_host_lc="${redis_host,,}"
    if [[ "$redis_host_lc" == "localhost" || "$redis_host_lc" == "127.0.0.1" || "$redis_host_lc" == "redis" ]]; then
        redis_is_local=true
    fi

    if command -v docker &>/dev/null && docker compose version &>/dev/null; then
        docker_compose_cmd=(docker compose)
    elif command -v docker-compose &>/dev/null; then
        docker_compose_cmd=(docker-compose)
    fi

    info "Redis hazır olana kadar bekleniyor (${redis_host}:${redis_port})..."
    for _ in {1..30}; do
        if "${python_cmd[@]}" - "$redis_host" "$redis_port" <<'PY' >/dev/null 2>&1
import socket
import sys

host = sys.argv[1]
port = int(sys.argv[2])
sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.settimeout(1.0)
try:
    sock.connect((host, port))
except OSError:
    raise SystemExit(1)
finally:
    sock.close()
PY
        then
            ok "Redis erişilebilir hale geldi."
            return 0
        fi

        if [[ "$redis_is_local" == true && "$docker_start_attempted" == false && "$DOCKER_DB_SERVICES_STARTED" != true ]]; then
            docker_start_attempted=true
            if [[ ${#docker_compose_cmd[@]} -eq 0 ]]; then
                warn "Redis henüz erişilebilir değil ve docker compose bulunamadı; servis otomatik başlatılamıyor."
            elif ! ensure_docker_daemon_running; then
                warn "Redis henüz erişilebilir değil; Docker daemon çalışmadığı için postgres/redis otomatik başlatılamadı."
            else
                info "Redis erişilemediği için PostgreSQL/Redis Docker servisleri otomatik başlatılıyor..."
                start_docker_services_or_fail "${docker_compose_cmd[@]}" -- postgres redis
                DOCKER_DB_SERVICES_STARTED=true
            fi
        fi

        sleep 2
    done

    warn "Redis ${redis_host}:${redis_port} 60 saniye içinde hazır olmadı; smoke testler atlanacak."
    return 1
}

run_smoke_tests() {
    step "Smoke Test Doğrulaması"
    local smoke_dir="$SCRIPT_DIR/tests/smoke"
    local -a pytest_smoke_args=("$smoke_dir" --rootdir="$SCRIPT_DIR" -v --no-cov)
    local -a pytest_smoke_env=()
    local should_run=false
    local smoke_failure_policy="${SMOKE_TEST_FAILURE_POLICY:-fail}"

    if [[ "$WSL2" == true && "$WSLCONFIG_CHANGED" == true ]]; then
        warn "WSL2 .wslconfig bu kurulumda güncellendi; smoke testler yeniden başlatma sonrasına ertelendi."
        info "PowerShell'de 'wsl --shutdown' çalıştırıp dağıtımı yeniden açtıktan sonra testleri çalıştırın:"
        echo "  uv run pytest tests/smoke --rootdir=\"$SCRIPT_DIR\" -v --no-cov"
        SMOKE_TEST_STATUS="ertelendi_wsl_restart"
        return
    fi

    if [[ "$RUN_SMOKE_TESTS_MODE" == "never" ]]; then
        info "--skip-smoke-test verildiği için smoke testler atlandı."
        SMOKE_TEST_STATUS="atlandi_bayrak"
        return
    fi

    if [[ ! -d "$smoke_dir" ]]; then
        warn "Smoke test dizini bulunamadı: $smoke_dir"
        SMOKE_TEST_STATUS="dizin_yok"
        return
    fi

    if [[ "$RUN_SMOKE_TESTS_MODE" == "always" ]]; then
        should_run=true
    else
        reply=$(prompt_yes_no_with_timeout_default_yes "Smoke testler (tests/smoke) çalıştırılsın mı? [E/h] ")
        case "${reply:-E}" in
            [HhNn]*) should_run=false ;;
            *) should_run=true ;;
        esac
    fi

    if [[ "$should_run" != true ]]; then
        info "Smoke testler kullanıcı tercihiyle atlandı."
        SMOKE_TEST_STATUS="atlandi_kullanici"
        return
    fi

    if ! wait_for_redis_before_smoke_tests; then
        warn "Redis hazır olmadığı için smoke testler çalıştırılmadı (false-negative önleme)."
        SMOKE_TEST_STATUS="atlandi_redis_hazir_degil"
        return
    fi
    wait_for_core_docker_health_before_smoke_tests

    if [[ "${RUN_GPU_STRESS:-0}" == "1" ]]; then
        info "RUN_GPU_STRESS=1 zaten tanımlı; GPU stres smoke testi zorunlu çalıştırılacak."
    elif [[ "$GPU_AVAILABLE" == true ]]; then
        pytest_smoke_env+=("RUN_GPU_STRESS=1")
        info "GPU tespit edildiği için smoke testlerde RUN_GPU_STRESS=1 otomatik etkinleştirildi."
    else
        info "GPU tespit edilmedi; GPU stres smoke testi varsayılan davranışla atlanabilir."
    fi

    if ! python -c "import pytest" >/dev/null 2>&1; then
        warn "pytest bu ortamda kurulu değil. Varsayılan dev paketleri için kurulum betiğini uv.lock ile tekrar çalıştırın."
        SMOKE_TEST_STATUS="pytest_yok"
        return
    fi
    if env "${pytest_smoke_env[@]}" uv run pytest "${pytest_smoke_args[@]}"; then
        ok "Smoke testler başarıyla geçti."
        SMOKE_TEST_STATUS="tamamlandi"
    else
        SMOKE_TEST_STATUS="hata"
        if [[ "$smoke_failure_policy" == "warn" ]]; then
            warn "Smoke testlerde hata var. SMOKE_TEST_FAILURE_POLICY=warn nedeniyle kurulum devam ediyor."
        else
            fail "Smoke testlerde hata var. Kurulum güvenliği için süreç durduruldu."
        fi
    fi
}

wait_for_core_docker_health_before_smoke_tests() {
    local -a docker_compose_cmd=()
    local -a services=("postgres" "redis")

    if command -v docker &>/dev/null && docker compose version &>/dev/null; then
        docker_compose_cmd=(docker compose)
    elif command -v docker-compose &>/dev/null; then
        docker_compose_cmd=(docker-compose)
    else
        return 0
    fi

    if ! ensure_docker_daemon_running; then
        warn "Docker daemon erişilemedi; smoke test öncesi container health kontrolü atlandı."
        return 0
    fi

    # Bu adım, smoke testlerin servisler tam hazır olmadan başlamasını azaltır.
    info "Smoke test öncesi Docker servis health kontrolleri yapılıyor (postgres/redis)..."
    "${docker_compose_cmd[@]}" ps --status running postgres redis >/dev/null 2>&1 || true

    local svc=""
    local container_id=""
    local state=""
    for svc in "${services[@]}"; do
        container_id=$("${docker_compose_cmd[@]}" ps -q "$svc" 2>/dev/null | head -n1 || true)
        if [[ -z "$container_id" ]]; then
            warn "'$svc' servisi için container bulunamadı. Compose projesi ayakta mı?"
            continue
        fi

        for _ in {1..30}; do
            state=$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$container_id" 2>/dev/null || echo "unknown")
            case "$state" in
                healthy|running)
                    ok "'$svc' servisi hazır: ${container_id} (${state})"
                    break
                    ;;
                exited|dead|unhealthy)
                    warn "'$svc' servisi sağlıksız görünüyor: ${container_id} (${state})"
                    return 0
                    ;;
            esac
            sleep 2
        done
    done
}

run_test_artifact_audit() {
    step "Test Artifact Denetimi"

    if [[ "$RUN_AUDIT" != true ]]; then
        info "--audit verilmediği için test artifact denetimi atlandı."
        AUDIT_STATUS="atlandi_bayrak"
        return
    fi

    local audit_script="$SCRIPT_DIR/scripts/check_empty_test_artifacts.sh"
    if [[ ! -f "$audit_script" ]]; then
        warn "Audit betiği bulunamadı: $audit_script"
        AUDIT_STATUS="betik_yok"
        return
    fi

    if bash "$audit_script"; then
        ok "Test artifact denetimi başarıyla tamamlandı."
        AUDIT_STATUS="tamamlandi"
    else
        AUDIT_STATUS="hata"
        fail "Test artifact denetimi başarısız oldu. Boş/uygunsuz test dosyalarını düzeltip tekrar deneyin."
    fi
}

# ── 15. Özet ─────────────────────────────────────────────────────────────────
print_summary() {
    echo ""
    echo -e "${BOLD}${GREEN}"
    echo "╔══════════════════════════════════════════════════════════════╗"
    echo "║              Sidar AI Kurulumu Tamamlandı!                  ║"
    echo "╚══════════════════════════════════════════════════════════════╝"
    echo -e "${NC}"

    echo -e "${BOLD}Sonraki Adımlar:${NC}"
    echo ""
    echo -e "  1️⃣  .env dosyasını düzenle:"
    echo "       nano .env"
    echo ""
    echo -e "${BOLD}.env API anahtar durumu:${NC}"
    if [[ "$ENV_API_KEYS_TOTAL" -gt 0 && "$ENV_API_KEYS_FILLED" -eq "$ENV_API_KEYS_TOTAL" ]]; then
        echo -e "  ${GREEN}✅ .env dosyası API anahtarları açısından eksiksiz görünüyor (${ENV_API_KEYS_FILLED}/${ENV_API_KEYS_TOTAL}).${NC}"
    else
        echo -e "  ${YELLOW}⚠️  Dolu anahtar: ${ENV_API_KEYS_FILLED}/${ENV_API_KEYS_TOTAL}${NC}"
        if [[ "${#ENV_API_KEYS_MISSING[@]}" -gt 0 ]]; then
            echo "  Eksik / boş bırakılan anahtarlar:"
            local missing_key
            for missing_key in "${ENV_API_KEYS_MISSING[@]}"; do
                echo "    - ${missing_key}"
            done
        fi
        echo "  Not: Kullanmayacağınız servis anahtarlarını boş bırakabilirsiniz."
    fi
    echo ""
    echo -e "  2️⃣  Sanal ortamı aktif et (yeni terminalde):"
    echo "       source .venv/bin/activate"
    echo ""
    echo -e "  3️⃣  Arka plan servisleri durumu:"
    if [[ "${APP_RUNTIME_MODE_SELECTED:-docker}" == "local" ]]; then
        echo "       Çalışma modu: Geliştirici (uygulama local, altyapı Docker)."
        echo "       Altyapı servisleri: docker compose up -d postgres redis ollama jaeger prometheus grafana"
        echo "       Durdurma: docker compose stop postgres redis ollama jaeger prometheus grafana"
    else
        echo "       Çalışma modu: Tam Docker (web/agent dahil)."
        echo "       Servisleri manuel yönetmek isterseniz: docker compose up -d / docker compose down"
    fi
    echo ""
    echo -e "  4️⃣  CLI ile başlat:"
    echo "       python main.py"
    echo ""
    echo -e "  5️⃣  Web arayüzü ile başlat (http://localhost:7860):"
    echo "       python main.py --quick web"
    if [[ "$REACT_UI_STATUS" == "hazır" || "$REACT_UI_STATUS" == "hazır_cache" ]]; then
        if [[ "$REACT_UI_STATUS" == "hazır_cache" ]]; then
            echo "       React UI build: cache kullanıldı, yeniden derleme atlandı (web_ui_react/dist)"
        else
            echo "       React UI build: tamamlandı (web_ui_react/dist)"
        fi
    elif [[ "$REACT_UI_STATUS" == "build_hata" ]]; then
        echo "       React UI build: başarısız (npm ci|npm install ve/veya npm run build hata verdi)"
        echo "       Logları kontrol edin ve manuel deneyin: cd web_ui_react && npm ci && npm run build"
    else
        echo "       React UI build: atlandı (${REACT_UI_STATUS})"
        echo "       Manuel build için: cd web_ui_react && npm ci && npm run build"
    fi
    echo ""
    echo -e "  6️⃣  Testleri çalıştır (varsayılan kurulumda hazır):"
    echo "       ./run_tests.sh"
    echo ""

    if [[ "$GPU_AVAILABLE" == true ]]; then
        echo -e "  ${GREEN}🚀 GPU hızlandırma aktif — .env: USE_GPU=true${NC}"
        echo ""
    fi

    if [[ "$WSL2" == true ]]; then
        local multimodal_val=""
        [[ -f "$SCRIPT_DIR/.env" ]] && multimodal_val=$(grep -E "^ENABLE_MULTIMODAL=" "$SCRIPT_DIR/.env" | head -n1 | cut -d= -f2- | tr -d '[:space:]' || true)
        if [[ "$multimodal_val" == "true" ]]; then
            echo -e "  ${GREEN}🎙️  Ses/mikrofon desteği aktif (WSLg PulseAudio) — .env: ENABLE_MULTIMODAL=true${NC}"
            if [[ "$AUDIO_SESSION_RESTART_RECOMMENDED" == true ]]; then
                echo -e "  ${YELLOW}⚠️  Ses paketleri/yol değişkenleri güncellendi. Sağlıklı çalışması için kurulumdan sonra terminali kapatıp yeniden açın.${NC}"
            fi
        else
            echo -e "  ${YELLOW}🔇 Ses desteği kapalı. Etkinleştirmek için: ./install_sidar.sh --enable-audio${NC}"
        fi
        if [[ "$WSLCONFIG_CHANGED" == true ]]; then
            echo -e "  ${YELLOW}⚠️  ÖNEMLİ: .wslconfig değişti → memory/swap ayarlarının etkili olması için:${NC}"
            echo "       PowerShell'de: wsl --shutdown && wsl"
        fi
        echo ""
    fi

    echo -e "${BOLD}Faydalı Komutlar:${NC}"
    echo "  uv run python github_upload.py   — projeyi GitHub'a yükle"
    if [[ "$MIGRATION_STATUS" == "tamamlandi" ]]; then
        echo "  Alembic migrasyonları kurulum sırasında tamamlandı."
    else
        echo "  uv run alembic upgrade head  — DB hazır olduktan sonra migrasyonu çalıştırın"
    fi
    if [[ "$SMOKE_TEST_STATUS" == "tamamlandi" ]]; then
        echo "  Smoke testler: başarılı (tests/smoke)."
        echo "  Not: Smoke testler yalnızca hızlı kurulum doğrulamasıdır; tam QA/coverage için ./run_tests.sh çalıştırın."
    elif [[ "$SMOKE_TEST_STATUS" == "hata" ]]; then
        echo "  Smoke testler: hata var. Tekrar için: uv run pytest tests/smoke --rootdir=\"$SCRIPT_DIR\" -v --no-cov"
        echo "  Tam kalite kapısı ve coverage doğrulaması için: ./run_tests.sh"
    else
        echo "  Smoke testler: atlandı (${SMOKE_TEST_STATUS}). Çalıştırmak için: uv run pytest tests/smoke --rootdir=\"$SCRIPT_DIR\" -v --no-cov"
        echo "  Kurulum sonrası tam QA/coverage için: ./run_tests.sh"
    fi
    if [[ "$AUDIT_STATUS" == "tamamlandi" ]]; then
        echo "  Test artifact audit: başarılı (scripts/check_empty_test_artifacts.sh)."
    elif [[ "$RUN_AUDIT" == true ]]; then
        echo "  Test artifact audit: ${AUDIT_STATUS}."
    else
        echo "  Test artifact audit: atlandı. Çalıştırmak için: ./install_sidar.sh --audit"
    fi
    echo "  ollama serve              — Ollama servisini başlat"
    if [[ "$SKIP_MODELS" == true ]]; then
        echo "  ollama pull <model_adi>   — model indirmeleri atlandı, sonradan manuel indirin"
    fi
    echo "  docker compose up sidar-gpu     — Docker GPU modu"
    echo "  Not: Docker GPU için nvidia-container-toolkit kurulu olmalıdır."
    echo ""
    echo -e "${BOLD}Gözlemlenebilirlik (Telemetry)${NC}"
    echo "  İzleme servislerini başlat: docker compose up -d jaeger prometheus grafana"
    echo "  Grafana paneli    : http://localhost:3000 (varsayılan: admin / admin)"
    echo "  Prometheus paneli : http://localhost:9090"
    echo "  Jaeger UI         : http://localhost:16686"
    echo "  Not: Bu servisler docker_setup/ altındaki hazır konfigürasyonları kullanır."
    echo "  Güvenlik notu: Üretimde ACCESS_LEVEL ayarını dikkatle yapılandırın."
    echo ""
}

# ── Docker Servislerini Başlatma ──────────────────────────────────────────────
launch_docker_services() {
    local docker_compose_cmd=()
    local compose_profiles=""
    local env_file="$SCRIPT_DIR/.env"
    local runtime_mode="${APP_RUNTIME_MODE:-ask}"
    local runtime_answer=""
    local -a infra_services=(postgres redis ollama jaeger prometheus grafana)

    if command -v docker &>/dev/null && docker compose version &>/dev/null; then
        docker_compose_cmd=(docker compose)
    elif command -v docker-compose &>/dev/null; then
        docker_compose_cmd=(docker-compose)
    else
        warn "Sistemde Docker veya Docker Compose bulunamadı, servisler otomatik başlatılamıyor."
        return
    fi

    if [[ -f "$env_file" ]]; then
        compose_profiles=$(grep -E '^COMPOSE_PROFILES=' "$env_file" | tail -n1 | cut -d= -f2- | tr -d '[:space:]' || true)
    fi
    if [[ -z "$compose_profiles" ]]; then
        if [[ "$GPU_AVAILABLE" == true ]]; then
            compose_profiles="gpu"
        else
            compose_profiles="cpu"
        fi
    fi

    if [[ "$runtime_mode" == "ask" ]]; then
        if [[ "$NO_INTERACTION" == true ]]; then
            runtime_mode="docker"
            info "--ci/--no-interaction etkin: çalışma modu varsayılanı 'docker' seçildi."
        else
            echo ""
            info "Çalışma modu seçimi:"
            echo "  1) Geliştirici modu (önerilen): uygulama local, altyapı servisleri Docker"
            echo "  2) Tam Docker modu: web/agent dahil tüm servisler Docker"
            if read -r -t 180 -p "Seçim [1/2, varsayılan=1]: " runtime_answer; then
                :
            else
                warn "180 saniye içinde seçim yapılmadı. Varsayılan seçim: 1 (geliştirici modu)."
                runtime_answer="1"
            fi
            case "${runtime_answer:-1}" in
                2) runtime_mode="docker" ;;
                *) runtime_mode="local" ;;
            esac
        fi
    fi

    APP_RUNTIME_MODE_SELECTED="$runtime_mode"
    echo ""
    local start_prompt="Docker servisleri başlatılsın mı? [E/h] "
    local start_default="E"
    local start_docker=""
    if [[ "$AUTO_START_DOCKER_SERVICES" == "true" ]]; then
        start_docker="E"
        info "AUTO_INSTALL: START_DOCKER_SERVICES=true olduğu için Docker servisleri otomatik başlatılacak."
    elif [[ "$AUTO_START_DOCKER_SERVICES" == "false" ]]; then
        start_docker="H"
        info "AUTO_INSTALL: START_DOCKER_SERVICES=false olduğu için Docker servis başlatma adımı atlanacak."
    elif [[ "$DOCKER_DB_SERVICES_STARTED" == true ]]; then
        info "PostgreSQL/Redis migrasyon adımında zaten başlatıldı; kalan Docker servisleri otomatik başlatılacak."
        start_docker="E"
    elif [[ "$NO_INTERACTION" == true ]]; then
        start_docker="E"
    else
        start_docker=$(prompt_yes_no_with_timeout_default_yes "$start_prompt")
    fi

    case "${start_docker:-$start_default}" in
        [EeYy]*)
            echo "── Docker Servis Kontrolü ──"
            if ensure_docker_daemon_running; then
                echo "✅ Docker motoru erişilebilir."
            else
                warn "Docker motoruna erişilemediği için arka plan servis başlatma adımı atlandı."
                if [[ "$WSL2" == true ]]; then
                    info "Docker Desktop > Settings > Resources > WSL Integration bölümünden Ubuntu entegrasyonunu açıp Apply & restart yapın."
                fi
                info "Entegrasyon tamamlandıktan sonra manuel çalıştırın: COMPOSE_PROFILES=$compose_profiles ${docker_compose_cmd[*]} up -d"
                return
            fi

            info "Docker Compose servisleri başlatılıyor..."
            info "Monitoring konfigürasyon dosyaları için bind-mount sanity check çalıştırılıyor..."
            validate_monitoring_mount_paths
            if [[ "$runtime_mode" == "local" ]]; then
                info "Seçilen çalışma modu: local (uygulama local + altyapı Docker)"
                if "${docker_compose_cmd[@]}" up -d "${infra_services[@]}"; then
                    ok "Altyapı Docker servisleri başarıyla başlatıldı (${infra_services[*]})."
                else
                    warn "Altyapı Docker servisleri başlatılamadı. Port çakışması veya Docker kapalı olabilir."
                fi
            else
                info "Seçilen çalışma modu: docker (tüm servisler Docker)"
                info "Docker Compose profili: $compose_profiles"
                if COMPOSE_PROFILES="$compose_profiles" "${docker_compose_cmd[@]}" up -d; then
                    ok "Docker servisleri başarıyla başlatıldı."
                else
                    warn "Docker servisleri başlatılamadı. Port çakışması veya Docker kapalı olabilir."
                fi
            fi
            ;;
        *)
            if [[ "$runtime_mode" == "local" ]]; then
                info "Docker servislerinin başlatılması atlandı. (Manuel: docker compose up -d ${infra_services[*]})"
            else
                info "Docker servislerinin başlatılması atlandı. (Manuel: COMPOSE_PROFILES=$compose_profiles docker compose up -d)"
            fi
            ;;
    esac
}

# ── Çalışma Modu Seçimi (Erken) ──────────────────────────────────────────────
select_runtime_mode_early() {
    local runtime_mode="${APP_RUNTIME_MODE:-ask}"
    local runtime_answer=""

    if [[ "$runtime_mode" == "ask" ]]; then
        if [[ "$NO_INTERACTION" == true ]]; then
            runtime_mode="docker"
            info "--ci/--no-interaction etkin: çalışma modu varsayılanı 'docker' seçildi."
        else
            echo ""
            info "Kurulum başlangıcında çalışma modu seçimi:"
            echo "  1) Geliştirici modu (önerilen): uygulama local, altyapı servisleri Docker"
            echo "  2) Tam Docker modu: web/agent dahil tüm servisler Docker"
            if read -r -t 180 -p "Seçim [1/2, varsayılan=1]: " runtime_answer; then
                :
            else
                warn "180 saniye içinde seçim yapılmadı. Varsayılan seçim: 1 (geliştirici modu)."
                runtime_answer="1"
            fi
            case "${runtime_answer:-1}" in
                2) runtime_mode="docker" ;;
                *) runtime_mode="local" ;;
            esac
        fi
    fi

    APP_RUNTIME_MODE="$runtime_mode"
    APP_RUNTIME_MODE_SELECTED="$runtime_mode"

    if [[ "$runtime_mode" == "docker" ]]; then
        info "Seçilen çalışma modu: docker (tam docker akışı uygulanacak)."
    else
        info "Seçilen çalışma modu: local (uygulama local + altyapı Docker)."
    fi
}

# ── Kurulum Sonrası IDE Başlatma ─────────────────────────────────────────────
launch_ide() {
    local vscode_mode="none"
    local vscode_target_path="$SCRIPT_DIR"
    local vscode_exe_path="/mnt/c/Program Files/Microsoft VS Code/Code.exe"

    if [[ "$NO_INTERACTION" == true && "$AUTO_OPEN_VSCODE" != "true" ]]; then
        info "--ci/--no-interaction etkin: IDE açma adımı atlandı."
        return
    fi

    if command -v code &>/dev/null; then
        vscode_mode="code-cli"
    elif [[ "$WSL2" == true ]] && command -v cmd.exe &>/dev/null; then
        if cmd.exe /c "where code" >/dev/null 2>&1; then
            vscode_mode="windows-code-cli"
            if command -v wslpath &>/dev/null; then
                vscode_target_path=$(wslpath -w "$SCRIPT_DIR" 2>/dev/null || echo "$SCRIPT_DIR")
            fi
        else
            local localappdata_path=""
            localappdata_path="$(resolve_windows_localappdata_path 2>/dev/null || true)"
            if [[ -n "$localappdata_path" && -x "${localappdata_path}/Programs/Microsoft VS Code/Code.exe" ]]; then
                vscode_exe_path="${localappdata_path}/Programs/Microsoft VS Code/Code.exe"
            fi
        fi

        if [[ -x "$vscode_exe_path" ]]; then
            vscode_mode="windows-code-exe"
            if command -v wslpath &>/dev/null; then
                vscode_target_path=$(wslpath -w "$SCRIPT_DIR" 2>/dev/null || echo "$SCRIPT_DIR")
            fi
        fi
    fi

    if [[ "$vscode_mode" != "none" ]]; then
        echo ""
        if [[ "$AUTO_OPEN_VSCODE" == "true" ]]; then
            open_code="E"
            info "AUTO_INSTALL: OPEN_VSCODE=true olduğu için VS Code otomatik açılacak."
        elif [[ "$AUTO_OPEN_VSCODE" == "false" ]]; then
            open_code="H"
            info "AUTO_INSTALL: OPEN_VSCODE=false olduğu için VS Code açılmayacak."
        else
            open_code=$(prompt_yes_no_with_timeout_default_yes "Kurulum tamamlandı. Proje VS Code ile açılsın mı? [e/H] ")
        fi
        case "${open_code:-H}" in
            [EeYy]*)
                info "VS Code açılıyor..."
                case "$vscode_mode" in
                    code-cli)
                        code "$SCRIPT_DIR"
                        ;;
                    windows-code-cli)
                        cmd.exe /c code "$vscode_target_path" >/dev/null 2>&1 || warn "Windows code CLI ile VS Code başlatılamadı."
                        ;;
                    windows-code-exe)
                        "$vscode_exe_path" "$vscode_target_path" >/dev/null 2>&1 || warn "Code.exe ile VS Code başlatılamadı."
                        ;;
                esac
                ;;
            *)
                info "VS Code başlatılması atlandı."
                ;;
        esac
    else
        warn "Sistemde VS Code launcher bulunamadı (code PATH, Windows code CLI veya Code.exe)."
        info "WSL ile tam entegrasyon için Windows tarafına VS Code ve 'WSL' eklentisini kurmanız önerilir."
    fi
}


cleanup_bootstrap_script_copy() {
    if [[ "$ORIGINAL_SCRIPT_DIR" == "$TARGET_DIR" ]]; then
        return
    fi

    if [[ "$(basename "$ORIGINAL_SCRIPT_PATH")" != "install_sidar.sh" ]]; then
        return
    fi

    if [[ -d "$ORIGINAL_SCRIPT_DIR/.git" ]]; then
        info "Kurulum farklı bir repo kopyasından çalıştırıldığı için betik dosyası silinmedi: $ORIGINAL_SCRIPT_PATH"
        return
    fi

    if [[ -f "$ORIGINAL_SCRIPT_PATH" ]]; then
        if rm -f "$ORIGINAL_SCRIPT_PATH"; then
            ok "Geçici kurulum betiği kaldırıldı: $ORIGINAL_SCRIPT_PATH"
        else
            warn "Geçici kurulum betiği silinemedi: $ORIGINAL_SCRIPT_PATH"
        fi
    fi

    info "Kurulum bundan sonra $TARGET_DIR dizininden yönetilmelidir."
}

# ── Terminal kısayolu: Sidar ortamını hızlı aktive et ───────────────────────
setup_shell_activation_shortcut() {
    step "Terminal Kısayolu Yapılandırması"

    local -a rc_files=("$HOME/.bashrc" "$HOME/.zshrc")
    local marker_begin="# >>> Sidar shell helper >>>"
    local marker_end="# <<< Sidar shell helper <<<"
    local helper_body=""
    helper_body=$(cat <<EOF
${marker_begin}
sidar_env() {
  cd "$TARGET_DIR" || return 1
  # shellcheck disable=SC1091
  source "$TARGET_DIR/.venv/bin/activate"
}
alias sidar-env='sidar_env'
${marker_end}
EOF
)

    local rcfile
    for rcfile in "${rc_files[@]}"; do
        [[ -f "$rcfile" ]] || touch "$rcfile"
        if grep -qF "$marker_begin" "$rcfile" 2>/dev/null; then
            info "Sidar terminal kısayolu zaten mevcut: $rcfile"
            continue
        fi
        {
            echo ""
            echo "$helper_body"
        } >> "$rcfile"
        ok "Sidar terminal kısayolu eklendi: $rcfile (kullanım: sidar-env)"
    done
}


run_doctor_phase() {
    step "Sidar Doctor"
    cd "$SCRIPT_DIR"
    mkdir -p artifacts/install
    local -a doctor_cmd=()
    if command -v uv &>/dev/null; then
        doctor_cmd=(uv run python -m core.doctor artifacts/install/doctor.json)
    elif command -v python3 &>/dev/null; then
        doctor_cmd=(python3 -m core.doctor artifacts/install/doctor.json)
    else
        fail "Doctor çalıştırmak için python3 veya uv bulunamadı."
    fi

    if "${doctor_cmd[@]}"; then
        ok "Doctor raporu üretildi: artifacts/install/doctor.json"
    else
        warn "Doctor raporu üretildi ancak bir veya daha fazla kontrol fail durumunda. Rapor: artifacts/install/doctor.json"
        return 1
    fi
}

run_prepare_system_phase() {
    install_system_dependencies
    sync_repo
    cd "$SCRIPT_DIR"
    ensure_prerequisites
    select_runtime_mode_early
    detect_gpu
    setup_nvidia_docker
    create_directories
    setup_env_file
    ok "prepare-system fazı tamamlandı."
}

run_sync_deps_phase() {
    cd "$SCRIPT_DIR"
    ensure_prerequisites
    select_runtime_mode_early
    detect_gpu
    setup_uv
    setup_python_env
    install_python_deps
    install_pyright_lsp_tool
    verify_torch_cuda
    ok "sync-deps fazı tamamlandı."
}

run_provision_models_phase() {
    cd "$SCRIPT_DIR"
    ensure_prerequisites
    detect_gpu
    setup_env_file
    download_ollama_models
    ok "provision-models fazı tamamlandı."
}

run_smoke_phase() {
    cd "$SCRIPT_DIR"
    ensure_prerequisites
    detect_gpu
    prepare_docker_for_migrations
    run_migrations
    run_smoke_tests
    run_test_artifact_audit
    run_doctor_phase || true
    ok "smoke fazı tamamlandı."
}

run_install_subcommand_if_requested() {
    case "$INSTALL_SUBCOMMAND" in
        full) return 1 ;;
        doctor)
            run_doctor_phase
            return 0
            ;;
        prepare-system)
            run_prepare_system_phase
            return 0
            ;;
        sync-deps)
            run_sync_deps_phase
            return 0
            ;;
        provision-models)
            run_provision_models_phase
            return 0
            ;;
        smoke)
            run_smoke_phase
            return 0
            ;;
    esac
    return 1
}

# ── Ana Akış ─────────────────────────────────────────────────────────────────
main() {
    banner
    report_repo_lookup_context
    detect_environment
    if [[ "$OFFLINE_MODE" == true ]]; then
        OFFLINE_PACKAGES_DIR="$(resolve_offline_packages_dir || true)"
        if [[ -n "$OFFLINE_PACKAGES_DIR" ]]; then
            info "Çevrimdışı/air-gapped mod etkin. Paket kaynağı: $OFFLINE_PACKAGES_DIR"
            verify_offline_bundle_manifest "$OFFLINE_PACKAGES_DIR"
        else
            fail "Çevrimdışı mod etkin ancak offline_packages dizini bulunamadı."
        fi
    fi

    if [[ "$INSTALL_SUBCOMMAND" == "doctor" ]]; then
        run_doctor_phase
        return
    fi

    ensure_noninteractive_sudo_ready

    if run_install_subcommand_if_requested; then
        relocate_log_file_if_needed
        cleanup_bootstrap_script_copy
        return
    fi

    if [[ "$INSTALL_KUBERNETES" == true ]]; then
        info "--kubernetes/--helm modu aktif: yerel bağımlılık kurulumu atlanacak, Helm dağıtımı yapılacak."
        deploy_with_helm
        return
    fi

    # Kritik sıra:
    # 1) Sistem bağımlılıkları (git/curl vb.)
    # 2) Repo senkronizasyonu (git clone/pull)
    # 3) Ön koşul doğrulaması (uv/Python/FFmpeg/Docker/Ollama)
    install_system_dependencies
    sync_repo
    cd "$SCRIPT_DIR"
    ensure_prerequisites
    select_runtime_mode_early
    detect_gpu
    setup_nvidia_docker
    if [[ "$APP_RUNTIME_MODE_SELECTED" == "local" ]]; then
        # uv-venv akışı: önce uv kur/güncelle, sonra venv oluştur
        setup_uv
        setup_python_env
        install_python_deps
        install_pyright_lsp_tool
        verify_torch_cuda
    else
        info "Tam Docker modu: lokal Python/Conda ortam kurulumu atlanıyor."
    fi
    create_directories
    # VS Code ayarları, Python yorumlayıcı yolu belli olduktan sonra erken hazırlanabilir.
    setup_vscode_workspace
    setup_env_file
    if [[ "$APP_RUNTIME_MODE_SELECTED" == "local" ]]; then
        setup_react_frontend
        install_playwright_browsers
    else
        info "Tam Docker modu: lokal React build ve Playwright kurulumu atlanıyor."
    fi
    setup_shell_activation_shortcut
    setup_wsl2_audio
    if [[ "$APP_RUNTIME_MODE_SELECTED" == "local" ]]; then
        # DB migrasyonu öncesi servis hazırlığı: kullanıcı onayı bu aşamada alınır.
        prepare_docker_for_migrations
        # Önce DB migrasyonu: olası bağlantı/şema hataları sonraki adımlara geçmeden görülsün.
        run_migrations
        # Model indirme: fonksiyon sonunda cleanup_temp_ollama trap'i geçici 'ollama serve'
        # sürecini otomatik sonlandırır; hemen ardından gelen launch_docker_services'in
        # Docker Ollama servisiyle 11434 port çakışması bu şekilde önlenir.
        download_ollama_models
    else
        MIGRATION_STATUS="tam_docker_modu_nedeniyle_atlandi"
        info "Tam Docker modu: lokal migrasyon/model indirme adımları atlanıyor."
    fi
    # Tüm altyapı (jaeger/prometheus/grafana dahil) smoke testlerden önce hazır olsun.
    launch_docker_services
    if [[ "$APP_RUNTIME_MODE_SELECTED" == "local" ]]; then
        run_smoke_tests
        run_test_artifact_audit
    else
        SMOKE_TEST_STATUS="tam_docker_modu_nedeniyle_atlandi"
        AUDIT_STATUS="tam_docker_modu_nedeniyle_atlandi"
        info "Tam Docker modu: lokal smoke-test/audit adımları atlanıyor."
    fi
    print_summary
    relocate_log_file_if_needed
    cleanup_bootstrap_script_copy
    prompt_post_install_sidar_env_mode
    # En son adım: IDE başlatma onayı
    launch_ide
}

main "$@"