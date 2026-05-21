#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════════
# Sidar AI — Kurulum Betiği (install_sidar.sh)
# Sürüm : pyproject.toml / sidar_version.py üzerinden otomatik çözülür
# Hedef : WSL2 / Ubuntu / Conda + NVIDIA RTX GPU ailesi (PyTorch CUDA wheel dinamik seçilir)
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

# Resume/auto-heal modunda GPU tespit fazı atlanabilir. Strict mode altında
# sonraki servis/smoke/özet fazlarının unbound variable ile kırılmaması için
# küresel GPU bayrağını en erken noktada güvenli CPU fallback'iyle tanımla.
export GPU_AVAILABLE="${GPU_AVAILABLE:-false}"

# GitHub Codespaces overlay dosya sisteminde uv hardlink uyarılarını ve gereksiz
# full-copy fallback denemelerini önlemek için copy modu varsayılanlaştırılır.
if [[ -z "${UV_LINK_MODE:-}" && ( "${CODESPACES:-}" == "true" || "${GITHUB_CODESPACES:-}" == "true" ) ]]; then
    export UV_LINK_MODE=copy
fi

# Kurulum loglarını eşzamanlı olarak terminale ve dosyaya yaz.
# Filtre önce terminal/log fan-out'una girer; böylece set -x, sed hata çıktısı
# veya beklenmeyen tool çıktıları DATABASE_URL/parola/token değerlerini hem
# terminalden hem de kalıcı log dosyasından maskeler.
mask_install_log_stream() {
    sed -u -E \
        -e 's#((postgresql|postgres|mysql|mariadb)(\+[^:/@[:space:]]+)?://[^:/@[:space:]]+:)[^@[:space:]]+@#\1****@#g' \
        -e 's#((redis|rediss|amqp|amqps|mongodb|mongodb\+srv)://[^:/@[:space:]]+:)[^@[:space:]]+@#\1****@#g' \
        -e 's#((DATABASE_URL|SIDAR_CONTAINER_DATABASE_URL|SELF_HEAL_DATABASE_URL|TEST_DATABASE_URL|LOCAL_DEV_FALLBACK_DATABASE_URL|POSTGRES_PASSWORD|API_KEY|JWT_SECRET_KEY|MEMORY_ENCRYPTION_KEY|AUTONOMY_WEBHOOK_SECRET|SWARM_FEDERATION_SHARED_SECRET|GITHUB_WEBHOOK_SECRET|GRAFANA_ADMIN_PASSWORD|METRICS_TOKEN|OPENAI_API_KEY|GEMINI_API_KEY|ANTHROPIC_API_KEY|LITELLM_API_KEY|SIDAR_REDIS_URL|REDIS_URL|RABBITMQ_URL|SIDAR_RABBITMQ_URL)=)[^[:space:]";]+#\1****#g' \
        -e 's#((generated_password|safe_db_url|container_db_url|db_password|db_url|api_key|memory_key|grafana_password|pg_password)=)[^[:space:]";]+#\1****#gi' \
        -e 's#("(DATABASE_URL|SIDAR_CONTAINER_DATABASE_URL|SELF_HEAL_DATABASE_URL|TEST_DATABASE_URL|LOCAL_DEV_FALLBACK_DATABASE_URL|POSTGRES_PASSWORD|API_KEY|JWT_SECRET_KEY|MEMORY_ENCRYPTION_KEY|AUTONOMY_WEBHOOK_SECRET|SWARM_FEDERATION_SHARED_SECRET|GITHUB_WEBHOOK_SECRET|GRAFANA_ADMIN_PASSWORD|METRICS_TOKEN|OPENAI_API_KEY|GEMINI_API_KEY|ANTHROPIC_API_KEY|LITELLM_API_KEY|SIDAR_REDIS_URL|REDIS_URL|RABBITMQ_URL|SIDAR_RABBITMQ_URL)"[[:space:]]*:[[:space:]]*")[^"]*"#\1****"#g' \
        -e 's#((Authorization|X-API-Key|X-Auth-Token):[[:space:]]*)(Bearer[[:space:]]+)?[^[:space:]]+#\1\3****#gi'
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Resume çağrılarında önceki çalışma dizinini koru (örn. one-shot fetch sonrası
# 02_repo/03_runtime fazları atlandığında relative yolların sapmaması için).
if [[ -n "${SIDAR_INSTALL_RESUME_CWD:-}" && -d "${SIDAR_INSTALL_RESUME_CWD}" ]]; then
    cd "${SIDAR_INSTALL_RESUME_CWD}"
fi
# WSL integration autofix sentinel should not leak across reinstall attempts
rm -f "${TMPDIR:-/tmp}/sidar_wsl_integration_applied" 2>/dev/null || true
ORIGINAL_SCRIPT_PATH="$(readlink -f "${BASH_SOURCE[0]}")"
ORIGINAL_SCRIPT_DIR="$SCRIPT_DIR"
# shellcheck disable=SC2034  # consumed by install_remediation.sh after it is sourced.
SIDAR_INSTALL_ORIGINAL_ARGS=("$@")
# Not: Repo clone/sync tamamlanmadan TARGET_DIR altında dosya üretmeyin.
# Aksi halde "sıfır kurulum" akışında hedef dizin gereksiz yere dolu görünebilir.
LOG_DIR="$SCRIPT_DIR/logs"
if [[ "${SIDAR_INSTALL_TEST_MODE:-0}" != "1" ]]; then
    mkdir -p "$LOG_DIR"
    LOG_FILE="$LOG_DIR/install_$(date -u +%Y-%m-%dT%H%M%SZ).log"
    exec > >(mask_install_log_stream | tee -i >(sed -u -E $'s/\x1B\\[[0-9;]*[[:alpha:]]//g' > "$LOG_FILE")) 2>&1
else
    LOG_FILE=""
fi

# ── Renkler + i18n ────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; BOLD='\033[1m'; NC='\033[0m'

resolve_sidar_locale() {
    local raw_locale="${SIDAR_LOCALE:-${LANG:-${LC_ALL:-${LC_MESSAGES:-tr}}}}"
    raw_locale="${raw_locale,,}"
    raw_locale="${raw_locale%%.*}"
    raw_locale="${raw_locale%%_*}"
    raw_locale="${raw_locale%%-*}"

    case "$raw_locale" in
        en) echo "en" ;;
        *) echo "tr" ;;
    esac
}

SIDAR_EFFECTIVE_LOCALE="$(resolve_sidar_locale)"

sidar_is_english_locale() {
    [[ "${SIDAR_EFFECTIVE_LOCALE:-tr}" == "en" ]]
}

sidar_t() {
    local key="$1"
    shift || true

    if sidar_is_english_locale; then
        case "$key" in
            sed_expression_missing) printf 'sed_inplace: expression parameter is missing.' ;;
            sed_target_missing) printf 'sed_inplace: target file parameter is missing.' ;;
            timeout_yes) printf 'No response received within %s seconds. Default selection: Yes.' "$1" ;;
            timeout_no) printf 'No response received within %s seconds. Default selection: No.' "$1" ;;
            install_failed) printf 'Installation failed (line %s, exit code %s).' "$1" "$2" ;;
            failed_command) printf '   Failed command: %s' "$1" ;;
            check_log) printf '   Check the log file for cleanup/review: %s' "$1" ;;
            banner_title) printf 'Sidar AI — Installation Starting' ;;
            invalid_arg) printf 'Unknown argument: %s. Accepted values: doctor | prepare-system | sync-deps | provision-models | smoke | --upgrade-lock | --i-understand-full-access | --cpu | --docker-only | --runtime-mode=local|docker | --silent | --auto | --mode=... | --env=... | --reset-db | --no-reset-db | --start-services | --no-start-services | --vscode | --no-vscode | --with-browsers | --skip-browsers | --offline | --air-gapped | --install-docker-cli | --skip-docker-cli | --force-postgres-volume-cleanup | --force-docker-cleanup | --kubernetes | --helm | --helm-release=... | --namespace=... | --values=... | --smoke-test | --skip-smoke-test | --audit | --skip-models | --download-models | --build-ui | --enable-audio | --ci | --no-interaction | --non-interactive | --headless | --yes | -y' "$1" ;;
            invalid_docker_cli) printf 'Invalid DOCKER_CLI_INSTALL value: %s. Supported: auto|always|never' "$1" ;;
            invalid_mode) printf 'Invalid --mode value: %s. Supported: local|docker' "$1" ;;
            invalid_env) printf 'Invalid --env value: %s. Supported: development|production' "$1" ;;
            silent_mode_enabled) printf 'Silent autonomous installation mode enabled (CI/CD-safe defaults are applied).' ;;
            incompatible_model_flags) printf '%s' '--skip-models and --download-models cannot be used together.' ;;
            kubernetes_ignores_cpu) printf '%s' '--cpu is not used in --kubernetes/--helm mode; it will be ignored.' ;;
            root_install) printf 'Installer is running as root; no sudo password blocker is expected.' ;;
            sudo_missing_noninteractive) printf 'sudo is required for non-interactive installation, but sudo was not found. Start the installer as root (for example: sudo ./install_sidar.sh).' ;;
            sudo_ready) printf 'Passwordless/pre-validated sudo access is ready for non-interactive mode.' ;;
            sudo_blocked) printf "A sudo password blocker was detected. Non-interactive/silent installation would be blocked. Fix: (1) start as root with sudo ./install_sidar.sh, (2) run 'sudo -v' beforehand, or (3) configure NOPASSWD sudo for the required commands." ;;
            *) printf '%s' "$key" ;;
        esac
    else
        case "$key" in
            sed_expression_missing) printf 'sed_inplace: ifade parametresi eksik.' ;;
            sed_target_missing) printf 'sed_inplace: hedef dosya parametresi eksik.' ;;
            timeout_yes) printf '%s saniye içinde yanıt alınamadı. Varsayılan seçim: Evet.' "$1" ;;
            timeout_no) printf '%s saniye içinde yanıt alınamadı. Varsayılan seçim: Hayır.' "$1" ;;
            install_failed) printf 'Kurulum başarısız (satır %s, çıkış kodu %s).' "$1" "$2" ;;
            failed_command) printf '   Hata veren komut: %s' "$1" ;;
            check_log) printf '   Temizleme/inceleme için log dosyasını kontrol edin: %s' "$1" ;;
            banner_title) printf 'Sidar AI — Kurulum Başlıyor' ;;
            invalid_arg) printf 'Bilinmeyen argüman: %s (doctor | prepare-system | sync-deps | provision-models | smoke | --upgrade-lock | --i-understand-full-access | --cpu | --docker-only | --runtime-mode=local|docker | --silent | --auto | --mode=... | --env=... | --reset-db | --no-reset-db | --start-services | --no-start-services | --vscode | --no-vscode | --with-browsers | --skip-browsers | --offline | --air-gapped | --install-docker-cli | --skip-docker-cli | --force-postgres-volume-cleanup | --force-docker-cleanup | --kubernetes | --helm | --helm-release=... | --namespace=... | --values=... | --smoke-test | --skip-smoke-test | --audit | --skip-models | --download-models | --build-ui | --enable-audio | --ci | --no-interaction | --non-interactive | --headless | --yes | -y kabul edilir)' "$1" ;;
            invalid_docker_cli) printf "Geçersiz DOCKER_CLI_INSTALL değeri: '%s'. Desteklenen: auto|always|never" "$1" ;;
            invalid_mode) printf "Geçersiz --mode değeri: '%s'. Desteklenen: local|docker" "$1" ;;
            invalid_env) printf "Geçersiz --env değeri: '%s'. Desteklenen: development|production" "$1" ;;
            silent_mode_enabled) printf 'Sessiz otonom kurulum modu etkin (CI/CD güvenli varsayılanları uygulanıyor).' ;;
            incompatible_model_flags) printf '%s' '--skip-models ve --download-models birlikte kullanılamaz.' ;;
            kubernetes_ignores_cpu) printf '%s' '--kubernetes/--helm modu aktifken --cpu parametresi kullanılmaz; göz ardı edilecek.' ;;
            root_install) printf 'Kurulum root yetkisiyle çalışıyor; sudo parola engeli beklenmiyor.' ;;
            sudo_missing_noninteractive) printf 'Etkileşimsiz kurulum için sudo gerekli ancak sistemde sudo bulunamadı. Kurulumu root olarak başlatın (ör. sudo ./install_sidar.sh).' ;;
            sudo_ready) printf 'Etkileşimsiz mod için şifresiz/ön-doğrulanmış sudo erişimi hazır.' ;;
            sudo_blocked) printf "Sudo parola engeli algılandı. Etkileşimsiz/sessiz kurulum bloke olur. Çözüm: (1) sudo ./install_sidar.sh ile root başlatın, (2) önceden 'sudo -v' çalıştırın, veya (3) gerekli komutlar için NOPASSWD sudo yapılandırın." ;;
            *) printf '%s' "$key" ;;
        esac
    fi
}

ok()   { echo -e "${GREEN}✅  $*${NC}" >&2; }
info() { echo -e "${BLUE}ℹ️   $*${NC}" >&2; }
debug() {
    [[ "${SIDAR_DEBUG:-0}" == "1" || "${SIDAR_VERBOSE:-0}" == "1" ]] || return 0
    echo -e "${BLUE}🔍  $*${NC}" >&2
}
warn() { echo -e "${YELLOW}⚠️   $*${NC}" >&2; }
fail() {
    echo -e "${RED}❌  $*${NC}" >&2
    if declare -F sidar_handle_install_failure >/dev/null 2>&1; then
        sidar_handle_install_failure 1 "${BASH_LINENO[0]:-unknown}" "${BASH_COMMAND:-fail}" "$*" || true
    fi
    exit 1
}
step() { echo -e "\n${BOLD}${BLUE}── $* ──${NC}" >&2; }

sed_inplace() {
    local expression="${1:-}"
    shift || fail "$(sidar_t sed_expression_missing)"
    [[ "$#" -gt 0 ]] || fail "$(sidar_t sed_target_missing)"

    case "$(uname -s 2>/dev/null || true)" in
        Darwin) sed -i '' "$expression" "$@" ;;
        *) sed -i "$expression" "$@" ;;
    esac
}

# BEGIN_BUNDLE_MODULES
INSTALL_MODULE_DIR="${SCRIPT_DIR}/scripts/install_modules"
INSTALL_HELPERS_MODULE="${INSTALL_MODULE_DIR}/install_helpers.sh"
INSTALL_HELPERS_TEMP_DIR=""

INSTALL_UTILITY_MODULES=(
    "utils/install_remediation.sh"
    "utils/wsl_integration_autofix.sh"
    "utils/wsl_gpu_preflight.sh"
    "utils/gpu_utils.sh"
    "utils/python_env.sh"
    "utils/db_credentials.sh"
    "utils/env_utils.sh"
    "utils/ollama_models.sh"
)

INSTALL_PHASE_MODULES=(
    "phases/01_context.sh"
    "phases/02_repo.sh"
    "phases/03_runtime.sh"
    "phases/04_workspace.sh"
    "phases/05_frontend.sh"
    "phases/06_services.sh"
    "phases/07_finish.sh"
)

INSTALL_REMOTE_MODULES=(
    "install_helpers.sh"
    "${INSTALL_UTILITY_MODULES[@]}"
    "${INSTALL_PHASE_MODULES[@]}"
)

download_remote_install_module() {
    local module_rel="$1"
    local remote_module_base="$2"
    local destination_root="$3"
    local remote_module_url="${remote_module_base}/${module_rel}"
    local destination_path="${destination_root}/${module_rel}"
    local tmp_module_path=""

    mkdir -p "$(dirname "$destination_path")"
    tmp_module_path="$(mktemp "${TMPDIR:-/tmp}/sidar_install_module.XXXXXX")"

    if command -v curl &>/dev/null; then
        if ! curl -fsSL "$remote_module_url" -o "$tmp_module_path"; then
            rm -f "$tmp_module_path"
            return 1
        fi
    elif command -v wget &>/dev/null; then
        if ! wget -qO "$tmp_module_path" "$remote_module_url"; then
            rm -f "$tmp_module_path"
            return 1
        fi
    else
        rm -f "$tmp_module_path"
        fail "Ne curl ne de wget bulundu; modül indirilemiyor."
    fi

    install -m 0644 "$tmp_module_path" "$destination_path"
    rm -f "$tmp_module_path"
}

download_remote_install_modules() {
    local remote_module_base="$1"
    local destination_root="$2"
    local module_rel=""

    if ! command -v curl &>/dev/null && ! command -v wget &>/dev/null; then
        [[ -n "${INSTALL_HELPERS_TEMP_DIR:-}" ]] && rm -rf "$INSTALL_HELPERS_TEMP_DIR"
        fail "Ne curl ne de wget bulundu; modül indirilemiyor."
    fi

    for module_rel in "${INSTALL_REMOTE_MODULES[@]}"; do
        if ! download_remote_install_module "$module_rel" "$remote_module_base" "$destination_root"; then
            [[ -n "${INSTALL_HELPERS_TEMP_DIR:-}" ]] && rm -rf "$INSTALL_HELPERS_TEMP_DIR"
            fail "Gerekli modül indirilemedi: ${remote_module_base}/${module_rel}"
        fi
    done
}

if [[ ! -f "$INSTALL_HELPERS_MODULE" ]]; then
    warn "Yerel modül dosyası bulunamadı: $INSTALL_HELPERS_MODULE"
    warn "Tek dosyalık çalıştırma algılandı; tüm kurulum modülleri uzaktan indirilmeyi deneyecek."

    INSTALL_HELPERS_TEMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/sidar_install_modules.XXXXXX")"
    INSTALL_MODULE_DIR="${INSTALL_HELPERS_TEMP_DIR}/install_modules"
    INSTALL_HELPERS_MODULE="${INSTALL_MODULE_DIR}/install_helpers.sh"
    REMOTE_MODULE_BASE="${SIDAR_INSTALL_MODULE_BASE_URL:-https://raw.githubusercontent.com/niluferbagevi-gif/Sidar/main/scripts/install_modules}"

    download_remote_install_modules "$REMOTE_MODULE_BASE" "$INSTALL_MODULE_DIR"
    ok "Kurulum modülleri indirildi ve geçici dizine kaydedildi: $INSTALL_MODULE_DIR"
fi
# shellcheck disable=SC1090
source "$INSTALL_HELPERS_MODULE"

# Eski/uzaktan indirilen yardımcı modüllerde fonksiyon henüz yoksa tek dosyalık
# kurulum akışını korumak için güvenli fallback tanımla.
if ! declare -F clear_stdin_buffer >/dev/null 2>&1; then
    clear_stdin_buffer() {
        local _trash=""
        [[ -t 0 ]] || return 0
        while IFS= read -r -t 0.01 _trash; do
            :
        done
    }
fi

validate_install_utility_modules() {
    local module_rel=""
    local module_path=""
    for module_rel in "${INSTALL_UTILITY_MODULES[@]}"; do
        module_path="${INSTALL_MODULE_DIR}/${module_rel}"
        if [[ ! -f "$module_path" ]]; then
            fail "Kurulum yardımcı modülü bulunamadı: ${module_path}. Repo modülleri eksik; lütfen depoyu güncelleyin."
        fi
    done
}

load_install_phase_modules() {
    local module_rel=""
    local module_path=""
    for module_rel in "${INSTALL_PHASE_MODULES[@]}"; do
        module_path="${INSTALL_MODULE_DIR}/${module_rel}"
        if [[ ! -f "$module_path" ]]; then
            fail "Kurulum faz modülü bulunamadı: ${module_path}. Repo modülleri eksik; lütfen depoyu güncelleyin."
        fi
        # shellcheck disable=SC1090
        source "$module_path"
    done
}

validate_install_utility_modules
sidar_source_install_utils "install_remediation.sh"
sidar_source_install_utils \
    "wsl_integration_autofix.sh" \
    "wsl_gpu_preflight.sh" \
    "gpu_utils.sh" \
    "python_env.sh" \
    "db_credentials.sh" \
    "env_utils.sh" \
    "ollama_models.sh"
load_install_phase_modules
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

SIDAR_PROMPT_TIMEOUT="${SIDAR_PROMPT_TIMEOUT:-180}"

prompt_yes_no_with_timeout_default_yes() {
    local prompt="$1"
    local timeout_seconds="${2:-$SIDAR_PROMPT_TIMEOUT}"
    local reply=""

    clear_stdin_buffer
    if read -r -t "$timeout_seconds" -p "$prompt" reply 2>/dev/tty; then
        :
    else
        warn "$(sidar_t timeout_yes "$timeout_seconds")"
        reply="E"
    fi

    echo "$reply"
}

prompt_yes_no_with_timeout_default_no() {
    local prompt="$1"
    local timeout_seconds="${2:-$SIDAR_PROMPT_TIMEOUT}"
    local reply=""

    clear_stdin_buffer
    if read -r -t "$timeout_seconds" -p "$prompt" reply 2>/dev/tty; then
        :
    else
        warn "$(sidar_t timeout_no "$timeout_seconds")"
        reply="H"
    fi

    echo "$reply"
}

on_install_error() {
    local exit_code=$?
    local failed_line="${1:-unknown}"
    local failed_cmd="${2:-unknown}"
    if declare -F sidar_handle_install_failure >/dev/null 2>&1; then
        sidar_handle_install_failure "$exit_code" "$failed_line" "$failed_cmd" "ERR trap" || true
    fi
    echo "❌ $(sidar_t install_failed "$failed_line" "$exit_code")" >&2
    echo "$(sidar_t failed_command "$failed_cmd")" >&2
    echo "$(sidar_t check_log "$LOG_FILE")" >&2
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

wsl_powershell_read() {
    local ps_command="$1"
    powershell.exe -NoProfile -Command "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8; \$OutputEncoding=[System.Text.Encoding]::UTF8; $ps_command" 2>/dev/null \
        | tr -d '\r' | tail -n1
}

ensure_docker_cli_available() {
    DOCKER_CLI_WSL_WARNED="${DOCKER_CLI_WSL_WARNED:-false}"
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
        if [[ "$DOCKER_CLI_WSL_WARNED" != "true" ]]; then
            warn "WSL2 ortamında Docker CLI bulunamadı. Öncelik Docker Desktop WSL Integration olmalı; otomatik APT kurulumu için --install-docker-cli veya DOCKER_CLI_INSTALL=always kullanın."
            DOCKER_CLI_WSL_WARNED="true"
        fi
        return 1
    fi

    install_docker_cli_from_apt
}

    verify_wsl_integration_listed() {
    [[ "$WSL2" == true ]] || return 0
    command -v powershell.exe &>/dev/null || return 0

    local current_distro="" default_distro="" enable_default="" integrated_csv="" integrated_norm=""
    local in_integrated=false default_covers=false
    local integration_autofix_sentinel="${TMPDIR:-/tmp}/sidar_wsl_integration_applied"
    local docker_socket_ready=false
    if DOCKER_HOST=unix:///var/run/docker.sock docker version --format '{{.Server.Version}}' &>/dev/null || docker info &>/dev/null; then
        docker_socket_ready=true
    fi

    current_distro="${WSL_DISTRO_NAME:-}"
    if [[ -z "$current_distro" ]]; then
        current_distro="$(powershell.exe -NoProfile -Command "wsl.exe -l -q | Select-Object -First 1" 2>/dev/null | iconv -f UTF-16LE -t UTF-8 2>/dev/null | tr -d '\0\r' | awk 'NF {print; exit}')"
    fi
    [[ -n "$current_distro" ]] || return 0

    default_distro="$(powershell.exe -NoProfile -Command "[Console]::OutputEncoding=[Text.Encoding]::UTF8; wsl.exe -l -q | Select-Object -First 1" 2>/dev/null | iconv -f UTF-16LE -t UTF-8 2>/dev/null | tr -d '\0\r' | awk 'NF {print; exit}')"
    enable_default="$(wsl_powershell_read "[Console]::OutputEncoding=[Text.Encoding]::UTF8; \$p=Join-Path \$env:APPDATA 'Docker\\settings-store.json'; if (!(Test-Path \$p)) { \$p=Join-Path \$env:APPDATA 'Docker\\settings.json' }; if (Test-Path \$p) { \$cfg=Get-Content \$p -Raw | ConvertFrom-Json; if (\$null -eq \$cfg.EnableIntegrationWithDefaultWslDistro) { '' } else { [string]\$cfg.EnableIntegrationWithDefaultWslDistro } }")"
    integrated_csv="$(wsl_powershell_read "[Console]::OutputEncoding=[Text.Encoding]::UTF8; \$p=Join-Path \$env:APPDATA 'Docker\\settings-store.json'; if (!(Test-Path \$p)) { \$p=Join-Path \$env:APPDATA 'Docker\\settings.json' }; if (Test-Path \$p) { \$cfg=Get-Content \$p -Raw | ConvertFrom-Json; \$found=\$false; \$keys=@('integratedWslDistros','IntegratedWslDistros','enabledWslIntegrations'); foreach (\$k in \$keys) { \$prop=\$cfg.PSObject.Properties | Where-Object { \$_.Name -ieq \$k } | Select-Object -First 1; if (\$null -ne \$prop -and \$null -ne \$cfg.(\$prop.Name)) { @(\$cfg.(\$prop.Name)) -join ','; \$found=\$true; break } }; if (-not \$found -and \$null -ne \$cfg.wsl) { \$nested=\$cfg.wsl.PSObject.Properties | Where-Object { \$_.Name -ieq 'integratedDistros' -or \$_.Name -ieq 'enabledWslIntegrations' } | Select-Object -First 1; if (\$null -ne \$nested -and \$null -ne \$cfg.wsl.(\$nested.Name)) { @(\$cfg.wsl.(\$nested.Name)) -join ',' } } }")"

    integrated_norm=",${integrated_csv// /},"
    [[ "$integrated_norm" == *",$current_distro,"* ]] && in_integrated=true
    if [[ "${enable_default,,}" == "true" && -n "$default_distro" && "$default_distro" == "$current_distro" ]]; then
        default_covers=true
    fi

    if [[ "$in_integrated" == true ]]; then
        ok "WSL entegrasyonu '${current_distro}' için açık."
        return 0
    fi
    if [[ "$default_covers" == true ]]; then
        if [[ "${WSL_INTEGRATION_HARDEN_EXPLICIT:-true}" == "true" ]]; then
            export WSL_INTEGRATION_AUTOFIX_ELIGIBLE=true
            info "Default-distro toggle '${current_distro}' kapsıyor; explicit toggle eklenmesi için postcheck'e devredildi."
            return 1
        fi
        info "Docker Desktop default-distro toggle'u '${current_distro}' dağıtımını kapsıyor."
        warn "Öneri: WSL Integration listesinden '${current_distro}' için explicit toggle'ı da açın."
        return 0
    fi
    if [[ "${WSL_INTEGRATION_AUTOFIX_APPLIED:-false}" == "true" || -f "$integration_autofix_sentinel" ]]; then
        if [[ "$docker_socket_ready" == true ]]; then
            ok "WSL Integration runtime doğrulandı: daemon socket erişilebilir (UI listesi '${current_distro}' için gecikmeli olabilir)."
            return 0
        fi
        warn "Docker Desktop WSL Integration hâlâ '${current_distro}' için kapalı görünüyor; daha önce bu oturumda otomatik düzeltme uygulandı, Docker Desktop senkronizasyonu bekleniyor."
        return 0
    fi
    if [[ "$docker_socket_ready" == true ]]; then
        info "Docker daemon socket erişilebilir; '${current_distro}' için WSL Integration UI listesi ile runtime durum farklı olabilir."
        return 0
    fi
    warn "Docker Desktop WSL Integration listesinde '${current_distro}' kapalı görünüyor."
    return 1
}

ensure_docker_daemon_running() {
    _docker_ready_with_socket() {
        if ! docker info &>/dev/null; then
            return 1
        fi

        if [[ "$WSL2" == true ]]; then
            DOCKER_HOST=unix:///var/run/docker.sock docker version --format '{{.Server.Os}}' &>/dev/null || return 1
        else
            docker version --format '{{.Server.Os}}' &>/dev/null || return 1
        fi

        return 0
    }

    _detect_current_wsl_distro_name() {
        if [[ -n "${WSL_DISTRO_NAME:-}" ]]; then
            printf '%s\n' "$WSL_DISTRO_NAME"
            return 0
        fi
        if command -v powershell.exe &>/dev/null; then
            powershell.exe -NoProfile -Command "wsl.exe -l -q | Select-Object -First 1" 2>/dev/null \
                | iconv -f UTF-16LE -t UTF-8 2>/dev/null | tr -d '\0\r' | awk 'NF {print; exit}'
            return 0
        fi
        printf '%s\n' ""
    }


    _wsl_integration_distro_listed() {
        local distro_name="$1"
        [[ "$WSL2" == true ]] || return 1
        command -v powershell.exe &>/dev/null || return 1
        [[ -n "$distro_name" ]] || return 1

        local integrated_csv integrated_norm
        integrated_csv="$(powershell.exe -NoProfile -Command "[Console]::OutputEncoding=[Text.Encoding]::UTF8; \$p=Join-Path \$env:APPDATA 'Docker\\settings-store.json'; if (!(Test-Path \$p)) { \$p=Join-Path \$env:APPDATA 'Docker\\settings.json' }; if (Test-Path \$p) { \$cfg=Get-Content \$p -Raw | ConvertFrom-Json; \$prop=\$cfg.PSObject.Properties | Where-Object { \$_.Name -ieq 'integratedWslDistros' } | Select-Object -First 1; if (\$null -ne \$prop -and \$null -ne \$cfg.(\$prop.Name)) { @(\$cfg.(\$prop.Name)) -join ',' } }" 2>/dev/null | iconv -f UTF-16LE -t UTF-8 2>/dev/null | tr -d '\0\r' | tail -n1)"
        integrated_norm=",${integrated_csv// /},"
        [[ "$integrated_norm" == *",$distro_name,"* ]]
    }

    _wait_for_docker_socket_mount_after_autofix() {
        local mount_wait_timeout="${WSL_INTEGRATION_SOCKET_WAIT_TIMEOUT:-30}"
        if ! [[ "$mount_wait_timeout" =~ ^[0-9]+$ ]] || (( mount_wait_timeout < 10 )); then
            mount_wait_timeout=30
        fi

        local elapsed=0
        while (( elapsed < mount_wait_timeout )); do
            if DOCKER_HOST=unix:///var/run/docker.sock docker version --format '{{.Server.Version}}' &>/dev/null; then
                ok "Docker socket mount doğrulandı (autofix sonrası)."
                return 0
            fi
            sleep 2
            ((elapsed += 2))
        done
        return 1
    }

    _docker_wsl_integration_postcheck() {
        [[ "$WSL2" == true ]] || return 0
        command -v powershell.exe &>/dev/null || return 0

        local current_distro="" default_distro="" enable_default="" integrated_csv="" integrated_norm=""
        local in_integrated=false default_covers=false
        local integration_autofix_sentinel="${TMPDIR:-/tmp}/sidar_wsl_integration_applied"

        current_distro="$(_detect_current_wsl_distro_name)"
        [[ -n "$current_distro" ]] || return 0

        default_distro="$(powershell.exe -NoProfile -Command "[Console]::OutputEncoding=[Text.Encoding]::UTF8; wsl.exe -l -q | Select-Object -First 1" 2>/dev/null | iconv -f UTF-16LE -t UTF-8 2>/dev/null | tr -d '\0\r' | awk 'NF {print; exit}')"
        enable_default="$(powershell.exe -NoProfile -Command "[Console]::OutputEncoding=[Text.Encoding]::UTF8; \$p=Join-Path \$env:APPDATA 'Docker\\settings-store.json'; if (!(Test-Path \$p)) { \$p=Join-Path \$env:APPDATA 'Docker\\settings.json' }; if (Test-Path \$p) { \$cfg=Get-Content \$p -Raw | ConvertFrom-Json; if (\$null -eq \$cfg.EnableIntegrationWithDefaultWslDistro) { '' } else { [string]\$cfg.EnableIntegrationWithDefaultWslDistro } }" 2>/dev/null | iconv -f UTF-16LE -t UTF-8 2>/dev/null | tr -d '\0\r' | tail -n1)"
        integrated_csv="$(powershell.exe -NoProfile -Command "[Console]::OutputEncoding=[Text.Encoding]::UTF8; \$p=Join-Path \$env:APPDATA 'Docker\\settings-store.json'; if (!(Test-Path \$p)) { \$p=Join-Path \$env:APPDATA 'Docker\\settings.json' }; if (Test-Path \$p) { \$cfg=Get-Content \$p -Raw | ConvertFrom-Json; \$found=\$false; \$keys=@('integratedWslDistros','IntegratedWslDistros','enabledWslIntegrations'); foreach (\$k in \$keys) { \$prop=\$cfg.PSObject.Properties | Where-Object { \$_.Name -ieq \$k } | Select-Object -First 1; if (\$null -ne \$prop -and \$null -ne \$cfg.(\$prop.Name)) { @(\$cfg.(\$prop.Name)) -join ','; \$found=\$true; break } }; if (-not \$found -and \$null -ne \$cfg.wsl) { \$nested=\$cfg.wsl.PSObject.Properties | Where-Object { \$_.Name -ieq 'integratedDistros' -or \$_.Name -ieq 'enabledWslIntegrations' } | Select-Object -First 1; if (\$null -ne \$nested -and \$null -ne \$cfg.wsl.(\$nested.Name)) { @(\$cfg.wsl.(\$nested.Name)) -join ',' } } }" 2>/dev/null | iconv -f UTF-16LE -t UTF-8 2>/dev/null | tr -d '\0\r' | tail -n1)"

        integrated_norm=",${integrated_csv// /},"
        [[ "$integrated_norm" == *",$current_distro,"* ]] && in_integrated=true

        if [[ "${enable_default,,}" == "true" && -n "$default_distro" && "$default_distro" == "$current_distro" ]]; then
            default_covers=true
        fi

        if [[ "$in_integrated" == true ]]; then
            ok "WSL entegrasyonu '${current_distro}' için açık."
            if ! DOCKER_HOST=unix:///var/run/docker.sock docker version --format '{{.Server.Version}}' &>/dev/null; then
                warn "Docker socket WSL2 dağıtımında mount edilmemiş olabilir; Docker Desktop toggle'ı '${current_distro}' için kapalı olabilir."
            fi
            return 0
        fi

        if [[ "$default_covers" == true ]]; then
            if [[ "${WSL_INTEGRATION_HARDEN_EXPLICIT:-true}" == "true" \
                  && "${WSL_INTEGRATION_AUTOFIX_APPLIED:-false}" != "true" \
                  && ! -f "$integration_autofix_sentinel" ]]; then
                info "Default-distro toggle '${current_distro}' kapsıyor; sertleştirme için explicit toggle ekleniyor."
                if apply_wsl_integration_autofix "$current_distro"; then
                    ok "Postcheck hardening: '${current_distro}' explicit toggle eklendi (Docker Desktop yeniden başlatıldı)."
                else
                    warn "Postcheck hardening başarısız; öneri olarak Settings > Resources > WSL Integration üzerinden manuel açın."
                fi
                return 0
            fi
            info "Docker Desktop default-distro toggle'u '${current_distro}' dağıtımını kapsıyor."
            warn "Öneri: WSL Integration listesinden '${current_distro}' için explicit toggle'ı da açın."
            if ! DOCKER_HOST=unix:///var/run/docker.sock docker version --format '{{.Server.Version}}' &>/dev/null; then
                warn "Docker socket WSL2 dağıtımında mount edilmemiş olabilir; Docker Desktop toggle'ı '${current_distro}' için explicit açılması gerekir."
            fi
            return 0
        fi

        if [[ "${WSL_INTEGRATION_AUTOFIX_APPLIED:-false}" == "true" || -f "$integration_autofix_sentinel" ]]; then
            if DOCKER_HOST=unix:///var/run/docker.sock docker version --format '{{.Server.Version}}' &>/dev/null; then
                if [[ "${_WSL_INTEGRATION_POSTFIX_NOTICE_SHOWN:-false}" != "true" ]]; then
                    ok "WSL Integration runtime doğrulandı: daemon socket erişilebilir (UI listesi henüz güncellenmemiş olabilir)."
                    _WSL_INTEGRATION_POSTFIX_NOTICE_SHOWN=true
                fi
                return 0
            fi
            warn "Docker Desktop WSL Integration hâlâ '${current_distro}' için kapalı görünüyor; daha önce bu oturumda otomatik düzeltme uygulandı, Docker Desktop senkronizasyonu bekleniyor."
            info "Autofix sonrası Docker socket mount doğrulaması başlatılıyor (maks. ${WSL_INTEGRATION_SOCKET_WAIT_TIMEOUT:-30}sn, 2sn aralıklarla)."
            if _wait_for_docker_socket_mount_after_autofix; then
                return 0
            fi
            warn "Autofix sonrası Docker socket mount doğrulanamadı; daemon hazırlanıyor olabilir."
            return 0
        fi

        local should_apply=false
        if [[ "${WSL_INTEGRATION_AUTOFIX_ELIGIBLE:-false}" == "true" ]]; then
            should_apply=true
            info "Preflight '${current_distro}' için autofix-eligible işareti verdi; aynı oturumda tekrar prompt göstermeden otomatik düzeltme uygulanacak."
        else
            if DOCKER_HOST=unix:///var/run/docker.sock docker version --format '{{.Server.Version}}' &>/dev/null || docker info &>/dev/null; then
                info "Docker daemon socket erişilebilir; '${current_distro}' için WSL Integration UI listesi gecikmeli/yanıltıcı olabilir."
                return 0
            fi
            warn "Docker Desktop WSL Integration listesinde '${current_distro}' kapalı görünüyor."
        fi
        if [[ "$should_apply" != true && ( "$NO_INTERACTION" == true || "$AUTO_INSTALL" == true ) ]]; then
            should_apply=true
            info "NO_INTERACTION/AUTO_INSTALL etkin: '${current_distro}' için Docker Desktop WSL entegrasyonu otomatik etkinleştirilecek."
        elif [[ "$should_apply" != true ]]; then
            local reply
            reply=$(prompt_yes_no_with_timeout_default_yes "'${current_distro}' için Docker Desktop WSL Integration ayarı otomatik açılsın mı? [E/h]: ")
            reply="${reply^^}"
            if [[ "$reply" == "E" || "$reply" == "EVET" || "$reply" == "Y" || "$reply" == "YES" || -z "$reply" ]]; then
                should_apply=true
            fi
        fi

        if [[ "$should_apply" != true ]]; then
            warn "WSL Integration otomatik güncellemesi atlandı. Docker Desktop > Settings > Resources > WSL Integration bölümünden '${current_distro}' anahtarını açın."
            return 1
        fi

        if ! apply_wsl_integration_autofix "$current_distro"; then
            warn "Docker Desktop WSL Integration ayarı otomatik güncellenemedi."
            return 1
        fi

        info "Docker Desktop yeniden başlatıldı; WSL Integration ayarının uygulanması bekleniyor..."
        local attempt
        for attempt in $(seq 1 20); do
            sleep 3
            if _wsl_integration_distro_listed "$current_distro"; then
                ok "Docker Desktop WSL Integration: '${current_distro}' artık aktif."
                return 0
            fi
            if DOCKER_HOST=unix:///var/run/docker.sock docker version --format '{{.Server.Version}}' &>/dev/null || docker info &>/dev/null; then
                ok "WSL Integration runtime doğrulandı: daemon socket erişilebilir (UI listesi '${current_distro}' için henüz güncellenmemiş olabilir)."
                return 0
            fi
        done

        if [[ "${WSL_INTEGRATION_AUTOFIX_APPLIED:-false}" == "true" ]] && (DOCKER_HOST=unix:///var/run/docker.sock docker version --format '{{.Server.Version}}' &>/dev/null || docker info &>/dev/null); then
            ok "Autofix sonrası daemon erişilebilir; WSL Integration runtime çalışıyor, UI senkronizasyonu bekleniyor."
            return 0
        fi
        warn "PowerShell autofix denendi fakat '${current_distro}' Docker Desktop tarafından hâlâ tanınmadı; Settings > Resources > WSL Integration üzerinden manuel açın."
        return 1
    }

    if ! docker_cli_healthy; then
        return 1
    fi

    if _docker_ready_with_socket; then return 0; fi

    warn "Docker daemon çalışmıyor görünüyor; otomatik başlatma denenecek."

    if command -v systemctl &>/dev/null; then
        sudo systemctl start docker >/dev/null 2>&1 || true
    fi

    if ! docker info &>/dev/null && command -v service &>/dev/null; then
        sudo service docker start >/dev/null 2>&1 || true
    fi

    if ! docker info &>/dev/null && command -v powershell.exe &>/dev/null; then
        local desktop_timeout
        desktop_timeout="${DOCKER_DESKTOP_READY_TIMEOUT:-240}"
        if ! [[ "$desktop_timeout" =~ ^[0-9]+$ ]] || (( desktop_timeout < 30 )); then
            desktop_timeout=240
        fi
        if [[ "${_DOCKER_DESKTOP_AUTOFIX_RESTARTED_AT:-}" =~ ^[0-9]+$ ]]; then
            local now_ts elapsed_since_autofix remaining_warmup
            now_ts="$(date +%s)"
            elapsed_since_autofix=$(( now_ts - _DOCKER_DESKTOP_AUTOFIX_RESTARTED_AT ))
            if (( elapsed_since_autofix < 0 )); then
                elapsed_since_autofix=0
            fi
            if (( elapsed_since_autofix < 300 )); then
                remaining_warmup=$(( 300 - elapsed_since_autofix ))
                desktop_timeout=$(( desktop_timeout + remaining_warmup ))
                info "Preflight autofix sonrası Docker Desktop hâlâ ısınma penceresinde (${elapsed_since_autofix}sn); bekleme süresi ${remaining_warmup}sn uzatıldı (toplam ${desktop_timeout}sn)."
            fi
        fi
        local integration_autofix_sentinel="${TMPDIR:-/tmp}/sidar_wsl_integration_applied"
        if [[ "${WSL_INTEGRATION_AUTOFIX_APPLIED:-false}" == "true" || -f "$integration_autofix_sentinel" ]]; then
            desktop_timeout=$(( desktop_timeout * 2 ))
            info "WSL integration autofix bu oturumda uygulandığı için Docker Desktop bekleme süresi uzatıldı (${desktop_timeout}sn)."
        fi

        powershell.exe -NoProfile -Command "Start-Process 'C:\\Program Files\\Docker\\Docker\\Docker Desktop.exe'" >/dev/null 2>&1 || true
        info "Docker Desktop başlatıldı, WSL entegrasyonunun hazır olması bekleniyor (maks. ${desktop_timeout}sn)..."
        local elapsed=0
        local sleep_step=3
        local progress_mark=30
        while (( elapsed < desktop_timeout )); do
            if _docker_ready_with_socket; then
                ok "Docker daemon erişilebilir duruma geldi."
                return 0
            fi
            sleep "$sleep_step"
            ((elapsed += sleep_step))
            if (( elapsed >= progress_mark )); then
                info "Docker daemon hâlâ hazırlanıyor... (${elapsed}/${desktop_timeout}sn)"
                progress_mark=$(( progress_mark + 30 ))
            fi
            if (( sleep_step < 12 )); then
                sleep_step=$(( sleep_step * 2 ))
                (( sleep_step > 12 )) && sleep_step=12
            fi
        done
        warn "Docker Desktop belirtilen süre içinde hazır hale gelmedi (${desktop_timeout}sn)."
    fi

    if _docker_ready_with_socket; then return 0; fi

    if [[ "$STRICT_DOCKER" == "true" ]]; then
        fail "Docker daemon erişilemedi. --strict-docker / SIDAR_REQUIRE_DOCKER=1 etkin olduğu için kurulum fail-fast durduruldu."
    fi

    return 1
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
        fail "Docker daemon socket erişim hatası (permission denied). Windows'ta $(wsl_integration_remediation_message "${WSL_DISTRO_NAME:-Ubuntu}")"
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

phase06_docker_daemon_gate_or_fail() {
    local max_attempts=3
    local attempt=1
    local integration_autofix_sentinel="${TMPDIR:-/tmp}/sidar_wsl_integration_applied"

    while (( attempt <= max_attempts )); do
        if docker info >/dev/null 2>&1; then
            if (( attempt > 1 )); then
                ok "Docker daemon doğrulaması ${attempt}. denemede başarılı."
            fi
            return 0
        fi

        warn "Phase 06 öncesi Docker daemon erişilemiyor (deneme ${attempt}/${max_attempts})."
        if [[ "$WSL2" == true && ("${WSL_INTEGRATION_AUTOFIX_APPLIED:-false}" == "true" || -f "$integration_autofix_sentinel") ]]; then
            info "Bu oturumda WSL integration autofix uygulandı; Docker Desktop açılışı gecikmiş olabilir."
        fi

        if (( attempt >= max_attempts )); then
            break
        fi

        if [[ "$NO_INTERACTION" == true || "$AUTO_INSTALL" == true ]]; then
            info "Etkileşimsiz mod: yeniden deneme öncesi 10sn bekleniyor."
            sleep 10
        else
            info "Lütfen Docker Desktop'ı açın/yeniden başlatın, sonra yeniden deneme yapılacak."
            clear_stdin_buffer
            read -r -p "Devam etmek için [ENTER] tuşuna basın..." 2>/dev/tty
        fi

        ((attempt += 1))
    done

    fail "Phase 06 öncesi Docker daemon doğrulanamadı (${max_attempts} deneme). Docker Compose adımlarına geçilmeden kurulum durduruldu."
}


sidar_add_unique_value() {
    local array_name="$1"
    local value="${2:-}"
    local existing=""

    [[ -n "$value" ]] || return 0
    local -n target_array="$array_name"
    for existing in "${target_array[@]}"; do
        [[ "$existing" == "$value" ]] && return 0
    done
    target_array+=("$value")
}

sidar_normalize_compose_project_name() {
    local raw="${1:-}"
    raw="${raw,,}"
    raw="$(printf '%s' "$raw" | sed -E 's/[^a-z0-9_-]+/-/g; s/^-+//; s/-+$//')"
    printf '%s' "$raw"
}

sidar_volume_name_matches_suffix() {
    local docker_volume_name="$1"
    local volume_suffix="$2"
    local compose_project_candidate="${3:-}"
    local normalized_project=""
    local lower_volume_name="${docker_volume_name,,}"
    local lower_volume_suffix="${volume_suffix,,}"

    [[ -n "$docker_volume_name" && -n "$volume_suffix" ]] || return 1

    if [[ "$docker_volume_name" == "$volume_suffix" || "$lower_volume_name" == "$lower_volume_suffix" ]]; then
        return 0
    fi

    if [[ -n "$compose_project_candidate" ]]; then
        normalized_project="$(sidar_normalize_compose_project_name "$compose_project_candidate")"
        if [[ "$docker_volume_name" == "${compose_project_candidate}_${volume_suffix}" || "$lower_volume_name" == "${compose_project_candidate,,}_${lower_volume_suffix}" ]]; then
            return 0
        fi
        if [[ -n "$normalized_project" && ( "$lower_volume_name" == "${normalized_project}_${lower_volume_suffix}" || "$lower_volume_name" == "${normalized_project}-${lower_volume_suffix//_/-}" ) ]]; then
            return 0
        fi
    fi

    # Sidar'ın eski/yeniden klonlanmış dizinlerinden kalmış, compose label'ı olmayan
    # volume adlarını da yakala. Başka projelerin genel postgres_data volume'lerini
    # proje adı bilinçli olarak Sidar ile ilişkilendirilemediği sürece kapsam dışında bırakır.
    if [[ "$lower_volume_name" =~ (^|[_-])sidar([_-].*)?([_-])(postgres|pg)([_-])?data$ ]]; then
        return 0
    fi

    return 1
}

sidar_volume_has_matching_compose_labels() {
    local docker_volume_name="$1"
    local volume_suffix="$2"
    shift 2
    local -a compose_project_candidates=("$@")
    local label_output=""
    local label_project=""
    local label_volume=""
    local candidate=""

    label_output=$(docker volume inspect "$docker_volume_name" --format '{{ index .Labels "com.docker.compose.project" }}|{{ index .Labels "com.docker.compose.volume" }}' 2>/dev/null || true)
    [[ -n "$label_output" ]] || return 1
    label_project="${label_output%%|*}"
    label_volume="${label_output#*|}"
    [[ "$label_project" != "<no value>" ]] || label_project=""
    [[ "$label_volume" != "<no value>" ]] || label_volume=""

    [[ "$label_volume" == "$volume_suffix" || "${label_volume,,}" == "${volume_suffix,,}" ]] || return 1
    for candidate in "${compose_project_candidates[@]}"; do
        if [[ "$label_project" == "$candidate" || "${label_project,,}" == "${candidate,,}" || "${label_project,,}" == "$(sidar_normalize_compose_project_name "$candidate")" ]]; then
            return 0
        fi
    done
    return 1
}

sidar_discover_postgres_volumes() {
    local compose_project_name="${1:-}"
    shift || true
    local -a candidate_volume_suffixes=("$@")
    local -a compose_project_candidates=()
    local docker_volume_name=""
    local volume_suffix=""
    local project_candidate=""
    local script_project_name=""
    local matched_volume=false

    sidar_add_unique_value compose_project_candidates "$compose_project_name"
    sidar_add_unique_value compose_project_candidates "$(sidar_normalize_compose_project_name "$compose_project_name")"
    script_project_name="$(basename "$SCRIPT_DIR")"
    sidar_add_unique_value compose_project_candidates "$script_project_name"
    sidar_add_unique_value compose_project_candidates "$(sidar_normalize_compose_project_name "$script_project_name")"
    sidar_add_unique_value compose_project_candidates "sidar"

    if mapfile -t docker_volume_names < <(docker volume ls --format '{{.Name}}' 2>/dev/null); then
        for docker_volume_name in "${docker_volume_names[@]}"; do
            matched_volume=false
            for volume_suffix in "${candidate_volume_suffixes[@]}"; do
                for project_candidate in "${compose_project_candidates[@]}"; do
                    if sidar_volume_name_matches_suffix "$docker_volume_name" "$volume_suffix" "$project_candidate"; then
                        printf '%s\n' "$docker_volume_name"
                        matched_volume=true
                        break 2
                    fi
                done
                if sidar_volume_has_matching_compose_labels "$docker_volume_name" "$volume_suffix" "${compose_project_candidates[@]}"; then
                    printf '%s\n' "$docker_volume_name"
                    matched_volume=true
                    break
                fi
            done
            if [[ "$matched_volume" == true ]]; then
                continue
            fi
        done
    fi
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
    if mapfile -t existing_pg_volumes < <(sidar_discover_postgres_volumes "$compose_project_name" "${candidate_volume_suffixes[@]}"); then
        :
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
        if "${compose_cmd[@]}" down --volumes --remove-orphans >/dev/null 2>&1; then
            if mapfile -t existing_pg_volumes < <(sidar_discover_postgres_volumes "$compose_project_name" "${candidate_volume_suffixes[@]}"); then
                :
            fi
            if [[ ${#existing_pg_volumes[@]} -eq 0 ]]; then
                POSTGRES_VOLUME_RESET_DONE=true
                return 0
            fi
            warn "Fallback sonrası PostgreSQL volume adayları bulundu: ${existing_pg_volumes[*]}"
        else
            warn "docker compose down --volumes --remove-orphans fallback'i çalıştırılamadı; volume adı eşleşmesi bulunamazsa kurulum güvenli uyarıyla devam edecek."
        fi
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
            -w \
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
                    -w \
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
STRICT_DOCKER=false
AUTO_RUNTIME_MODE="ask"
AUTO_START_DOCKER_SERVICES="ask"
AUTO_RESET_POSTGRES_VOLUMES="ask"
AUTO_ENV_TYPE="ask"
AUTO_OPEN_VSCODE="ask"
OFFLINE_MODE=false
# shellcheck disable=SC2034  # phase modules read this runtime override after sync.
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

print_install_help() {
    if sidar_is_english_locale; then
        cat <<EOF
Usage: $0 [doctor|prepare-system|sync-deps|provision-models|smoke] [--upgrade-lock] [--i-understand-full-access] [--cpu] [--docker-only] [--runtime-mode=local|docker] [--strict-docker] [--silent] [--auto] [--mode=local|docker] [--env=development|production] [--reset-db|--no-reset-db] [--start-services|--no-start-services] [--vscode|--no-vscode] [--with-browsers|--skip-browsers] [--offline|--air-gapped] [--install-docker-cli|--skip-docker-cli] [--force-postgres-volume-cleanup] [--skip-models] [--download-models] [--build-ui] [--kubernetes] [--smoke-test|--skip-smoke-test] [--audit] [--enable-audio] [--ci|--no-interaction|--non-interactive|--headless|--yes|-y]
  doctor|prepare-system|sync-deps|provision-models|smoke  Run a single installer phase
  --upgrade-lock  Intentionally update uv.lock
  --i-understand-full-access  Explicit risk acknowledgement for ACCESS_LEVEL=full
  --cpu  Force CPU mode even when a GPU is detected
  --docker-only  Do not install PostgreSQL/Redis on the host; use Docker services only
  --runtime-mode=local|docker  Runtime mode: local=app local + infrastructure in Docker, docker=all services in Docker
  --strict-docker  Fail-fast if Docker daemon cannot be reached after retries
  --force-postgres-volume-cleanup / --force-docker-cleanup  Enable project-scoped aggressive docker rm -f cleanup after DB password hardening
  --kubernetes / --helm  Use the Helm chart/Kubernetes flow instead of local installation
  --helm-release=<name>  Helm release name (default: sidar)
  --namespace=<name>  Kubernetes namespace (default: sidar)
  --values=<file>  Helm values file (for example: helm/sidar/values-prod.yaml)
  --smoke-test  Require tests/smoke at the end of installation
  --skip-smoke-test  Do not run smoke tests at the end of installation
  --audit  Run scripts/check_empty_test_artifacts.sh at the end of installation
  --skip-models  Skip Ollama model downloads
  --download-models  Download Ollama models by default
  --build-ui  Rebuild the React Web UI even when cache exists
  --enable-audio  Enable WSL2 audio support (default: disabled; PulseAudio/WSLg configured automatically)
  --ci / --no-interaction  Run non-interactively without prompting the user
  --non-interactive / --headless / --yes / -y  Short aliases for --no-interaction
  --silent  Quiet CI/CD install: DEBIAN_FRONTEND=noninteractive + safe automatic defaults
            Note: sudo cannot prompt for a password in non-interactive mode; run as root or pre-validate sudo.
  --auto  Short flag for non-interactive installation (AUTO_INSTALL=true)
  --mode=local|docker  Select runtime mode directly
  --env=development|production  Select post-install SIDAR_ENV directly
  --reset-db / --no-reset-db  Select whether PostgreSQL volumes may be reset
  --start-services / --no-start-services  Select whether Docker services should start
  --vscode / --no-vscode  Select whether VS Code opens at the end of installation
  --with-browsers / --skip-browsers  Force/skip Playwright Chromium browser installation
  --offline / --air-gapped  Use prepared packages under ./offline_packages instead of downloading from the internet
  --install-docker-cli  Force Docker CLI + Buildx + Compose v2 installation on Debian/Ubuntu hosts
  --skip-docker-cli / --no-install-docker-cli  Skip automatic Docker CLI installation

  Non-interactive environment variables:
    SIDAR_LOCALE=en|tr or LANG=en_US.UTF-8  Select installer message language
    AUTO_INSTALL=true|false        (true behaves like --no-interaction)
    INSTALL_MODE=1|2|local|docker  (1/local=developer, 2/docker=full Docker)
    ENV_TYPE=dev|prod              (SIDAR_ENV selection: development/production)
    RESET_DB=yes|no                (PostgreSQL volume reset approval)
    START_DOCKER_SERVICES=yes|no   (migration/final Docker startup approval)
    OPEN_VSCODE=yes|no             (VS Code launch approval)
    INSTALL_PLAYWRIGHT_BROWSERS=true|false (force/skip Playwright browser installation)
    OFFLINE_INSTALL=true|false     (equivalent to --offline/--air-gapped)
    SIDAR_PROMPT_TIMEOUT=180      Interactive prompt timeout (seconds)
    SIDAR_REPO_URL=https://...    Override repo clone/pull source for forks/organizations
    PYTORCH_CUDA_WHEEL_TAG=cu128  Override PyTorch CUDA wheel tag (cu124/cu126/cu128)
    PYTORCH_CUDA_INDEX_URL=https://...  Override PyTorch wheel index
    DOCKER_CLI_INSTALL=auto|always|never  Docker CLI automatic installation policy
    DOCKER_DESKTOP_READY_TIMEOUT=240  Docker Desktop startup wait timeout in seconds
    SIDAR_REQUIRE_DOCKER=1|0  Force strict Docker daemon requirement (1 = fail-fast)
    SIDAR_INSTALL_AUTO_HEAL=1|0  Enable/disable phase auto-heal + resume (default: 1)
    SIDAR_INSTALL_REMEDIATION_MAX_ATTEMPTS=1  Maximum auto-heal resume attempts per run
EOF
    else
        cat <<EOF
Kullanım: $0 [doctor|prepare-system|sync-deps|provision-models|smoke] [--upgrade-lock] [--i-understand-full-access] [--cpu] [--docker-only] [--runtime-mode=local|docker] [--strict-docker] [--silent] [--auto] [--mode=local|docker] [--env=development|production] [--reset-db|--no-reset-db] [--start-services|--no-start-services] [--vscode|--no-vscode] [--with-browsers|--skip-browsers] [--offline|--air-gapped] [--install-docker-cli|--skip-docker-cli] [--force-postgres-volume-cleanup] [--skip-models] [--download-models] [--build-ui] [--kubernetes] [--smoke-test|--skip-smoke-test] [--audit] [--enable-audio] [--ci|--no-interaction|--non-interactive|--headless|--yes|-y]
  doctor|prepare-system|sync-deps|provision-models|smoke  Tek kurulum fazını çalıştır
  --upgrade-lock  uv.lock dosyasını bilinçli olarak güncelle
  --i-understand-full-access  ACCESS_LEVEL=full için açık risk onayı
  --cpu  GPU algılansa bile CPU modunda kur
  --docker-only  PostgreSQL/Redis'i hosta kurma, sadece Docker servislerini kullan
  --runtime-mode=local|docker  Çalıştırma modu: local=uygulama local + altyapı docker, docker=tüm servisler docker
  --strict-docker  Docker daemon hazır değilse retry sonunda fail-fast dur
  --force-postgres-volume-cleanup / --force-docker-cleanup  DB parola hardening sonrası kilitli container/volume temizliği için projeye özel agresif docker rm -f adımlarını etkinleştir
  --kubernetes / --helm  Yerel kurulum yerine Helm chart ile Kubernetes kurulumu yap
  --helm-release=<ad>  Helm release adı (varsayılan: sidar)
  --namespace=<ad>  Kubernetes namespace (varsayılan: sidar)
  --values=<dosya>  Helm values dosyası (örn. helm/sidar/values-prod.yaml)
  --smoke-test  Kurulum sonunda tests/smoke testlerini zorunlu çalıştır
  --skip-smoke-test  Kurulum sonunda smoke test çalıştırma
  --audit  Kurulum sonunda scripts/check_empty_test_artifacts.sh denetimini çalıştır
  --skip-models  Ollama model indirmelerini atla
  --download-models  Ollama modellerini varsayılan olarak indir
  --build-ui  React Web UI yeniden build et (cache olsa bile)
  --enable-audio  WSL2 ses desteğini etkinleştir (varsayılan: kapalı, PulseAudio/WSLg otomatik yapılandırılır)
  --ci / --no-interaction  Kullanıcıdan onay istemeden etkileşimsiz kurulum çalıştır
  --non-interactive / --headless / --yes / -y  --no-interaction eşdeğeri kısayol bayraklar
  --silent  CI/CD için sessiz kurulum: DEBIAN_FRONTEND=noninteractive + güvenli otomatik varsayılanlar
            Not: Etkileşimsiz modda sudo parola sorulamaz; root çalıştırın veya önceden sudo doğrulayın.
  --auto  Etkileşimsiz kurulum için kısa bayrak (AUTO_INSTALL=true)
  --mode=local|docker  Çalışma modu seçimini doğrudan belirle
  --env=development|production  Kurulum sonrası SIDAR_ENV seçimini doğrudan belirle
  --reset-db / --no-reset-db  PostgreSQL volume sıfırlama kararını belirle
  --start-services / --no-start-services  Docker servis başlatma kararını belirle
  --vscode / --no-vscode  Kurulum sonunda VS Code açma kararını belirle
  --with-browsers / --skip-browsers  Playwright Chromium tarayıcı kurulumunu zorla/atla
  --offline / --air-gapped  İnternetten script/repo indirmek yerine ./offline_packages altındaki hazır paketleri kullan
  --install-docker-cli  Debian/Ubuntu hostta Docker CLI + Buildx + Compose v2 kurulumunu zorla
  --skip-docker-cli / --no-install-docker-cli  Docker CLI otomatik kurulumunu atla

  Etkileşimsiz çevre değişkenleri:
    SIDAR_LOCALE=en|tr veya LANG=en_US.UTF-8  Kurulum mesaj dilini seçer
    AUTO_INSTALL=true|false        (true ise --no-interaction gibi davranır)
    INSTALL_MODE=1|2|local|docker  (1/local=developer, 2/docker=tam docker)
    ENV_TYPE=dev|prod              (SIDAR_ENV seçimi: development/production)
    RESET_DB=yes|no                (PostgreSQL volume sıfırlama onayı)
    START_DOCKER_SERVICES=yes|no   (migrasyon ve final Docker başlatma onayı)
    OPEN_VSCODE=yes|no             (kurulum sonunda VS Code açma onayı)
    INSTALL_PLAYWRIGHT_BROWSERS=true|false (Playwright tarayıcı kurulumu zorla/atla)
    OFFLINE_INSTALL=true|false     (--offline/--air-gapped eşdeğeri)
    SIDAR_PROMPT_TIMEOUT=180      Etkileşimli prompt zaman aşımı (saniye)
    SIDAR_REPO_URL=https://...    Repo clone/pull kaynağını fork/organizasyon için override eder
    PYTORCH_CUDA_WHEEL_TAG=cu128  PyTorch CUDA wheel tag override (cu124/cu126/cu128)
    PYTORCH_CUDA_INDEX_URL=https://...  PyTorch wheel index override
    DOCKER_CLI_INSTALL=auto|always|never  Docker CLI otomatik kurulum politikası
    DOCKER_DESKTOP_READY_TIMEOUT=240  Docker Desktop hazır olma bekleme süresi (saniye)
    SIDAR_REQUIRE_DOCKER=1|0  Docker daemon zorunluluğunu fail-fast olarak uygular (1=zorunlu)
    SIDAR_INSTALL_AUTO_HEAL=1|0  Faz auto-heal + resume mantığını aç/kapat (varsayılan: 1)
    SIDAR_INSTALL_REMEDIATION_MAX_ATTEMPTS=1  Çalıştırma başına azami auto-heal resume denemesi
EOF
    fi
}

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
        --strict-docker) STRICT_DOCKER=true ;;
        --force-postgres-volume-cleanup|--force-docker-cleanup) FORCE_POSTGRES_VOLUME_CLEANUP=true ;;
        --enable-audio) ENABLE_AUDIO=true ;;
        --help|-h)
            print_install_help
            exit 0
            ;;
        *)      warn "$(sidar_t invalid_arg "$arg")"; exit 1 ;;
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
SIDAR_WSL_AUTO_UPGRADE="$(normalize_bool "${SIDAR_WSL_AUTO_UPGRADE:-false}")"
STRICT_DOCKER="$(normalize_bool "${STRICT_DOCKER:-${SIDAR_REQUIRE_DOCKER:-false}}")"
if [[ "$AUTO_INSTALL" == "true" ]]; then
    NO_INTERACTION=true
fi

OFFLINE_MODE_RAW="$(normalize_bool "${OFFLINE_INSTALL:-${AIR_GAPPED_INSTALL:-}}")"
if [[ "$OFFLINE_MODE_RAW" == "true" ]]; then
    OFFLINE_MODE=true
fi

case "${DOCKER_CLI_INSTALL_MODE}" in
    auto|always|never|true|false|yes|no|1|0) ;;
    *) fail "$(sidar_t invalid_docker_cli "${DOCKER_CLI_INSTALL_MODE}")" ;;
esac

PLAYWRIGHT_BROWSERS_RAW="$(normalize_bool "${INSTALL_PLAYWRIGHT_BROWSERS:-}")"
if [[ "$PLAYWRIGHT_BROWSERS_RAW" == "true" ]]; then
    PLAYWRIGHT_BROWSERS_MODE="always"
elif [[ "$PLAYWRIGHT_BROWSERS_RAW" == "false" ]]; then
    PLAYWRIGHT_BROWSERS_MODE="never"
fi

AUTO_RUNTIME_MODE="$(resolve_runtime_mode_choice "${CLI_MODE_RAW:-${INSTALL_MODE:-${RUNTIME_MODE:-${APP_RUNTIME_MODE:-ask}}}}")"
if [[ -n "$CLI_MODE_RAW" && "$AUTO_RUNTIME_MODE" == "ask" ]]; then
    fail "$(sidar_t invalid_mode "${CLI_MODE_RAW}")"
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
    fail "$(sidar_t invalid_env "${CLI_ENV_RAW}")"
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
    info "⚠️  $(sidar_t silent_mode_enabled)"
fi

if [[ "$SKIP_MODELS" == true && "$DOWNLOAD_MODELS" == true ]]; then
    fail "$(sidar_t incompatible_model_flags)"
fi

if [[ "$INSTALL_KUBERNETES" == true && "$FORCE_CPU" == true ]]; then
    warn "$(sidar_t kubernetes_ignores_cpu)"
fi

if [[ "$NO_INTERACTION" == true && "$RUN_SMOKE_TESTS_MODE" == "ask" ]]; then
    RUN_SMOKE_TESTS_MODE="never"
fi

# ── Sabitler ──────────────────────────────────────────────────────────────────
resolve_install_sidar_version() {
    local resolved_version=""

    if command -v python3 &>/dev/null && [[ -f "$SCRIPT_DIR/sidar_version.py" ]]; then
        resolved_version=$(PYTHONPATH="$SCRIPT_DIR" python3 - <<'PY_VERSION' 2>/dev/null || true
from sidar_version import resolve_version
print(resolve_version())
PY_VERSION
)
    fi

    if [[ -z "${resolved_version//[[:space:]]/}" && -f "$SCRIPT_DIR/pyproject.toml" ]]; then
        resolved_version=$(sed -nE 's/^[[:space:]]*version[[:space:]]*=[[:space:]]*"([^"]+)".*/\1/p' "$SCRIPT_DIR/pyproject.toml" | head -n1 || true)
    fi

    resolved_version="${resolved_version//[[:space:]]/}"
    echo "${resolved_version:-0.0.0}"
}

INSTALL_SIDAR_VERSION="${INSTALL_SIDAR_VERSION:-$(resolve_install_sidar_version)}"
refresh_install_sidar_version_from_repo() {
    local refreshed_version=""
    refreshed_version="$(resolve_install_sidar_version)"
    INSTALL_SIDAR_VERSION="${refreshed_version:-0.0.0}"
}

PYTHON_VERSION="3.11"
# shellcheck disable=SC2034  # retained for downstream phase/default URL hooks.
DEFAULT_DATABASE_URL=""
REPO_URL="${SIDAR_REPO_URL:-${REPO_URL:-https://github.com/niluferbagevi-gif/Sidar}}"
TARGET_DIR="$HOME/Sidar"
REQUIRED_DIRS=(data logs temp sessions data/rag data/lora_adapters data/continuous_learning)
# shellcheck disable=SC2034  # used by offline bundle flows when modules are sourced.
OFFLINE_PACKAGES_DIR_DEFAULT_NAME="offline_packages"

_visible_width() {
    local value="${1-}"
    python3 - "$value" <<'PY'
import sys
import unicodedata

text = sys.argv[1] if len(sys.argv) > 1 else ""
width = 0
for ch in text:
    if unicodedata.combining(ch):
        continue
    width += 2 if unicodedata.east_asian_width(ch) in {"F", "W"} else 1
print(width)
PY
}

_pad_visible() {
    local value="${1-}" target_width="${2:-0}"
    local current_width pad_len
    current_width="$(_visible_width "$value")"
    pad_len=$(( target_width - current_width ))
    if (( pad_len < 0 )); then
        pad_len=0
    fi
    printf '%s%*s' "$value" "$pad_len" ""
}

_center_visible() {
    local value="${1-}" target_width="${2:-60}"
    local current_width left_pad right_pad
    current_width="$(_visible_width "$value")"
    left_pad=$(( (target_width - current_width) / 2 ))
    (( left_pad < 0 )) && left_pad=0
    right_pad=$(( target_width - current_width - left_pad ))
    (( right_pad < 0 )) && right_pad=0
    printf '%*s%s%*s' "$left_pad" "" "$value" "$right_pad" ""
}

banner() {

    local version_suffix=""
    local banner_text=""
    local centered_banner=""
    if [[ "$INSTALL_SIDAR_VERSION" != "0.0.0" ]]; then
        version_suffix=" (v$INSTALL_SIDAR_VERSION)"
    fi
    banner_text="$(sidar_t banner_title)${version_suffix}"
    centered_banner="$(_center_visible "$banner_text" 60)"

    echo -e "${BOLD}${BLUE}"
    echo "╔══════════════════════════════════════════════════════════════╗"
    printf "║%s║\n" "$(_pad_visible "$centered_banner" 60)"
    echo "╚══════════════════════════════════════════════════════════════╝"
    echo -e "${NC}"
}

ensure_noninteractive_sudo_ready() {
    if [[ "$EUID" -eq 0 ]]; then
        info "$(sidar_t root_install)"
        return 0
    fi

    if ! command -v sudo >/dev/null 2>&1; then
        if [[ "$NO_INTERACTION" == true || "$SILENT_MODE" == true || "$AUTO_INSTALL" == true ]]; then
            fail "$(sidar_t sudo_missing_noninteractive)"
        fi
        return 0
    fi

    if [[ "$NO_INTERACTION" == true || "$SILENT_MODE" == true || "$AUTO_INSTALL" == true ]]; then
        if sudo -n -v >/dev/null 2>&1; then
            ok "$(sidar_t sudo_ready)"
        else
            fail "$(sidar_t sudo_blocked)"
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

check_host_ollama_healthy() {
    local env_file="${1:-$SCRIPT_DIR/.env}"
    local version_url=""
    version_url=$(resolve_ollama_version_url "$env_file")
    curl -sf "$version_url" >/dev/null 2>&1
}

log_host_ollama_runtime_diagnostics() {
    local env_file="${1:-$SCRIPT_DIR/.env}"
    local base_url=""
    local host=""

    base_url=$(resolve_ollama_base_url "$env_file")
    host="${base_url#http://}"
    host="${host#https://}"
    host="${host%%/*}"
    host="${host%%:*}"

    info "Host Ollama çalışma tanısı toplanıyor (GPU kullanımı opsiyonel kontrol)."
    local ollama_ps_reports_gpu=false

    if command -v ollama &>/dev/null; then
        if ollama ps >/tmp/sidar_ollama_ps.log 2>&1; then
            info "Host Ollama modelleri (ollama ps):"
            sed 's/^/       /' /tmp/sidar_ollama_ps.log
            if awk 'NR==1 {for (i=1;i<=NF;i++) if ($i=="PROCESSOR") c=i; next} c && toupper($c) ~ /GPU/ {found=1} END {exit !found}' /tmp/sidar_ollama_ps.log; then
                ollama_ps_reports_gpu=true
                info "ollama ps PROCESSOR sütunu GPU gösteriyor; host Ollama GPU üzerinde çalışıyor."
            fi
        else
            warn "ollama ps komutu çalıştırılamadı; host Ollama GPU durumu CLI üzerinden doğrulanamadı."
        fi
    else
        warn "ollama CLI bulunamadı; host Ollama GPU kullanımı için ollama ps çıktısı alınamadı."
    fi

    if [[ -z "$host" || "$host" == "localhost" || "$host" == "127.0.0.1" ]]; then
        local smi_cmd=""
        if command -v nvidia-smi &>/dev/null; then
            smi_cmd="nvidia-smi"
        elif command -v nvidia-smi.exe &>/dev/null; then
            smi_cmd="nvidia-smi.exe"
        fi

        if [[ "$WSL2" == true ]]; then
            info "WSL2: ollama ps doğrulaması yeterli; nvidia-smi compute-apps sorgusu atlandı."
        elif [[ "$ollama_ps_reports_gpu" == true ]]; then
            info "GPU kullanımı ollama ps ile doğrulandı; nvidia-smi compute-apps sorgusu atlandı."
        elif [[ -n "$smi_cmd" ]]; then
            if "$smi_cmd" --query-compute-apps=pid,process_name,used_gpu_memory --format=csv,noheader,nounits >/tmp/sidar_ollama_gpu_apps.log 2>&1; then
                if awk -F, 'tolower($2) ~ /ollama/ {found=1} END {exit !found}' /tmp/sidar_ollama_gpu_apps.log; then
                    info "nvidia-smi üzerinde Ollama süreçleri (PID, süreç, VRAM MiB):"
                    awk -F, 'tolower($2) ~ /ollama/ {gsub(/^ +| +$/, "", $1); gsub(/^ +| +$/, "", $2); gsub(/^ +| +$/, "", $3); printf "       %s, %s, %s MiB\n", $1, $2, $3}' /tmp/sidar_ollama_gpu_apps.log
                else
                    warn "nvidia-smi çalıştı ancak Ollama süreci görünmedi; host Ollama CPU modunda olabilir."
                fi
            else
                warn "nvidia-smi compute-apps sorgusu başarısız; host Ollama GPU süreci doğrulanamadı."
            fi
        else
            info "nvidia-smi bulunamadı; host Ollama GPU süreci doğrulaması atlandı."
        fi
    else
        info "Host Ollama uzak bir adreste (${base_url}); yerel nvidia-smi ile GPU süreci doğrulaması atlandı."
    fi
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
            local INSTALL_STASH_REF=""
            local INSTALL_STASH_MESSAGE=""
            if ! git diff --quiet || ! git diff --cached --quiet || [[ -n "$(git ls-files --others --exclude-standard)" ]]; then
                INSTALL_STASH_MESSAGE="sidar-install-auto-stash-$(date +%Y%m%d_%H%M%S)"
                info "Lokal değişiklikler geçici olarak stash'e alınıyor."
                git stash push -u -m "$INSTALL_STASH_MESSAGE" >/dev/null 2>&1 || fail "Lokal değişiklikler yedek stash'e alınamadı; git güncellemesi güvenli şekilde durduruldu."
                INSTALL_STASH_REF="$(git stash list --format='%gd:%gs' | awk -F: -v msg="$INSTALL_STASH_MESSAGE" '$0 ~ msg {print $1; exit}')"
                INSTALL_STASH_REF="${INSTALL_STASH_REF:-stash@{0}}"
                STASHED_CHANGES=true
                ok "Lokal değişiklikler yedek stash'e alındı: ${INSTALL_STASH_REF} (${INSTALL_STASH_MESSAGE})"
            fi

            git pull --rebase origin main || fail "Git çekme işlemi başarısız oldu!"

            if [[ "$STASHED_CHANGES" == true ]]; then
                # `apply` kullanıyoruz; başarı kesinleşmeden stash'i drop etmeyerek
                # reset/clean gibi yıkıcı kurtarma adımlarında kullanıcı çalışmasını
                # geri alınabilir bir stash referansıyla koruyoruz.
                if git stash apply "$INSTALL_STASH_REF" >/dev/null 2>&1; then
                    git stash drop "$INSTALL_STASH_REF" >/dev/null 2>&1 || warn "Uygulanan stash otomatik silinemedi; manuel kontrol edin: ${INSTALL_STASH_REF}"
                    ok "Lokal değişiklikler stash'ten geri yüklendi."
                else
                    warn "Stash apply sırasında çakışma oluştu; yedek stash korunuyor: ${INSTALL_STASH_REF} (${INSTALL_STASH_MESSAGE})"
                    git merge --abort >/dev/null 2>&1 || true
                    git rebase --abort >/dev/null 2>&1 || true
                    if [[ "$NO_INTERACTION" == true ]]; then
                        fail "Git çalışma ağacı çakışmalı durumda kaldı. --no-interaction modunda otomatik kurtarma yapılmadı. Yerel çalışma yedek stash içinde korunuyor: ${INSTALL_STASH_REF} (${INSTALL_STASH_MESSAGE}). Manuel çözün veya stash'i doğruladıktan sonra reset/clean işlemini bilinçli çalıştırın."
                    fi

                    echo ""
                    warn "Yerel değişiklikler yedek stash içinde korunuyor: ${INSTALL_STASH_REF} (${INSTALL_STASH_MESSAGE})"
                    warn "Yalnız bu stash referansını doğruladıktan sonra çalışma ağacını origin/main durumuna sıfırlayabilirsiniz."
                    local recovery_reply
                    recovery_reply=$(prompt_yes_no_with_timeout_default_no "Yedek stash doğrulandı. Çakışmayı temizlemek için 'git reset --hard origin/main && git clean -fd' uygulansın mı? [e/H] ")
                    case "${recovery_reply:-H}" in
                        [EeYy]*)
                            if [[ -z "$INSTALL_STASH_REF" ]] || ! git rev-parse -q --verify "${INSTALL_STASH_REF}^{commit}" >/dev/null; then
                                fail "Yıkıcı git kurtarma reddedildi: geçerli yedek stash referansı bulunamadı. git clean -fd çalıştırılmadı."
                            fi
                            warn "Kurtarma adımı uygulanıyor. Yerel çalışma yedek stash'te korunuyor: ${INSTALL_STASH_REF} (${INSTALL_STASH_MESSAGE})"
                            git fetch origin main || fail "Kurtarma için origin/main fetch başarısız oldu."
                            git reset --hard origin/main || fail "git reset --hard origin/main başarısız oldu. Yedek stash: ${INSTALL_STASH_REF}"
                            git clean -fd || warn "git clean -fd sırasında bazı dosyalar temizlenemedi. Yedek stash: ${INSTALL_STASH_REF}"
                            ok "Repo origin/main durumuna sıfırlandı. Yedek stash korunuyor: ${INSTALL_STASH_REF} (${INSTALL_STASH_MESSAGE}). Geri almak için: git stash apply ${INSTALL_STASH_REF}"
                            ;;
                        *)
                            fail "Git çalışma ağacı çakışmalı durumda kaldı. Yerel çalışma yedek stash içinde korunuyor: ${INSTALL_STASH_REF} (${INSTALL_STASH_MESSAGE}). Lütfen '$TARGET_DIR' içinde çakışmaları manuel çözün veya stash'i doğruladıktan sonra reset/clean işlemini bilinçli çalıştırın."
                            ;;
                    esac
                fi
            fi
        )
    fi

    SCRIPT_DIR="$TARGET_DIR"
    refresh_install_sidar_version_from_repo
    ok "Kurulum dizini güncellendi: $SCRIPT_DIR"
    info "Installer sürümü repo kaynaklarından yenilendi: v$INSTALL_SIDAR_VERSION"
    banner
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
            local -a ns_needs_normalize_files=()
            mapfile -t ns_needs_normalize_files < <(sudo sh -c "grep -Rsl 'deb .*deb.nodesource.com/${node_target_series}' /etc/apt/sources.list /etc/apt/sources.list.d 2>/dev/null | xargs -r grep -LE 'deb(\\s+\\[[^]]+\\])?\\s+https?://deb\\.nodesource\\.com/${node_target_series}\\s+nodistro\\s+main'" || true)
            local src_file=""
            if [[ "${#ns_needs_normalize_files[@]}" -gt 0 ]]; then
                for src_file in "${ns_needs_normalize_files[@]}"; do
                    sudo sed -E -i \
                        "s#(deb(\\s+\\[[^]]+\\])?\\s+https?://deb\\.nodesource\\.com/${node_target_series})\\s+[[:alnum:]_.-]+\\s+main#\\1 nodistro main#g" \
                        "$src_file"
                done
                ok "NodeSource apt girdileri nodistro formatına normalize edildi (${#ns_needs_normalize_files[@]} dosya)."
            else
                debug "NodeSource apt girdileri zaten nodistro formatında; normalize adımı değişiklik yapmadan atlandı."
            fi
        fi

        if ! sudo DEBIAN_FRONTEND=noninteractive apt-get -o Acquire::Retries=3 update -y; then
            warn "apt update başarısız oldu. NodeSource listesi sıfırlanıp tekrar denenecek..."
            sudo rm -f /etc/apt/sources.list.d/nodesource.list
            sudo DEBIAN_FRONTEND=noninteractive apt-get -o Acquire::Retries=3 update -y
        fi
        info "Gerekli temel paketler (curl, wget, git, zstd vb.) kuruluyor..."
        sudo DEBIAN_FRONTEND=noninteractive apt-get -o Acquire::Retries=3 install -y \
            curl wget git build-essential shellcheck software-properties-common zstd ca-certificates gnupg \
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
            verify_wsl_integration_listed || true
        else
            warn "Docker daemon başlatılamadı. Docker Desktop/service durumunu kontrol edin."
            verify_wsl_integration_listed || true
            if [[ "$NO_INTERACTION" == true || "$AUTO_INSTALL" == true ]]; then
                fail "Docker daemon erişilemedi ve etkileşimsiz mod aktif (NO_INTERACTION/AUTO_INSTALL). Kurulum fail-fast durduruldu."
            fi

            info "Lütfen Docker Desktop'ı manuel başlatın (veya service'i ayağa kaldırın), ardından tek seferlik yeniden deneme yapılacak."
            clear_stdin_buffer
            read -r -p "Docker hazır olduktan sonra [ENTER] tuşuna basın..." 2>/dev/tty

            if ensure_docker_daemon_running; then
                ok "Docker daemon manuel müdahale sonrası erişilebilir."
                verify_wsl_integration_listed || true
            else
                fail "Docker daemon manuel yeniden denemeden sonra da erişilemedi. Kurulum devam ettirilmiyor."
            fi
        fi
        if docker compose version &>/dev/null; then
            ok "Docker Compose eklentisi mevcut."
        elif command -v docker-compose &>/dev/null; then
            ok "docker-compose (standalone) mevcut."
        else
            warn "Docker Compose bulunamadı. Kurulum: https://docs.docker.com/compose/install/"
        fi
    else
        if [[ "$WSL2" == true ]]; then
            if [[ "$docker_version_error" == *"Input/output error"* ]]; then
                warn "Docker CLI çağrısı Input/output error döndürüyor. WSL entegrasyon mount'ları askıda kalmış olabilir."
            fi
            info "Docker şu anda WSL içinde doğrulanamadı; Docker Desktop entegrasyon kontrolüne geçiliyor."
        else
            warn "Docker bulunamadı veya çalıştırılamıyor. Docker komutları (örn. docker compose up sidar-gpu) çalışmayacaktır."
        fi
    fi

    # Sistem Python sürümü artık doğrulanmaz: uv, gerekli Python sürümünü izole
    # ortam için kendisi çözer/indirir ve proje sürümünü .python-version veya
    # pyproject.toml üzerinden create_uv_venv içinde uygular.

    if [[ "$WSL2" == true ]]; then
        info "WSL2 ortamı tespit edildi."
    fi

    if [[ "$WSL2" == true ]] && ! (command -v docker &>/dev/null && [[ "$docker_version_check_ok" == true ]]); then

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
            info "Docker şu anda WSL içinde kullanılamıyor; yeni bir dağıtım sonrası Docker Desktop entegrasyonu kopmuş olabilir."
            info "WSL Integration otomatik düzeltmesi denendi. Lütfen doğrulama için şu adımları uygulayın:"
            echo "  1. Windows'ta Docker Desktop'ı açın."
            echo "  2. Settings > Resources > WSL Integration menüsünde '${WSL_DISTRO_NAME:-Ubuntu}' dağıtımının açık olduğunu doğrulayın."
            echo "  3. Gerekirse Apply & restart yapın."
            echo "  4. $(wsl_integration_remediation_message "${WSL_DISTRO_NAME:-Ubuntu}")"
            echo ""
            if [[ "$NO_INTERACTION" == true || "$AUTO_INSTALL" == true ]]; then
                fail "WSL2 Docker Desktop entegrasyonu kapalı ve etkileşimsiz modda manuel onay alınamıyor (NO_INTERACTION/AUTO_INSTALL aktif). Önce entegrasyonu açıp tekrar deneyin."
            else
                clear_stdin_buffer
                read -r -p "Entegrasyonu tamamladıktan sonra devam etmek için [ENTER] tuşuna basın..." 2>/dev/tty
            fi

            # Kullanıcıdan onay sonrası tekrar doğrula
            if ! command -v docker &>/dev/null; then
                fail "[ENTER] sonrası docker CLI hâlâ bulunamadı. $(wsl_integration_remediation_message "${WSL_DISTRO_NAME:-Ubuntu}")"
            fi
            if ! docker_cli_healthy; then
                fail "[ENTER] sonrası docker CLI hâlâ sağlıksız. Docker Desktop entegrasyonunu ve WSL erişimini doğrulayın."
            fi
            if ! docker info &>/dev/null; then
                fail "[ENTER] sonrası docker daemon erişilemedi (docker info başarısız). $(wsl_integration_remediation_message "${WSL_DISTRO_NAME:-Ubuntu}")"
            fi
            ok "WSL2 Docker Desktop entegrasyonu doğrulandı (docker CLI + docker info)."
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
    local ollama_healthcheck_wait_seconds="${OLLAMA_API_HEALTHCHECK_MAX_WAIT_SECONDS:-30}"
    info "Ollama API healthcheck bekleme döngüsü başlatılıyor (maksimum ${ollama_healthcheck_wait_seconds} saniye)..."
    if wait_for_ollama_api_ready "$OLLAMA_VERSION_URL" "$ollama_healthcheck_wait_seconds" 1; then
        ok "Ollama API servisi aktif (${OLLAMA_VERSION_URL})."
    else
        warn "Ollama kurulu ancak API servisi şu an yanıt vermiyor (${OLLAMA_VERSION_URL})."
        info "Model indirmek veya servisi başlatmak için ayrı bir terminalde 'ollama serve' komutunu çalıştırabilirsiniz."
        info "Alternatif olarak .env içinde AI_PROVIDER=gemini veya openai kullanabilirsiniz."
    fi
}

# ── 2. NVIDIA GPU tespiti ────────────────────────────────────────────────────
detect_gpu() {
    step "GPU Tespiti"
    GPU_AVAILABLE=false
    CUDA_VERSION=""
    GPU_COMPUTE_CAPABILITY=""

    if [[ "$FORCE_CPU" == true ]]; then
        warn "--cpu bayrağı: GPU kullanımı devre dışı bırakıldı."
        return
    fi

    local SMI_CMD=""
    local smi_ping_out=""
    local query_out=""
    if command -v nvidia-smi &>/dev/null; then
        SMI_CMD="nvidia-smi"
    elif command -v nvidia-smi.exe &>/dev/null; then
        SMI_CMD="nvidia-smi.exe"
    fi

    if [[ -n "$SMI_CMD" ]]; then
        smi_ping_out=$("$SMI_CMD" -L 2>/dev/null | head -1 || true)
    fi

    if [[ -n "$SMI_CMD" ]] && [[ -n "$smi_ping_out" ]]; then
        query_out=$("$SMI_CMD" --query-gpu=name --format=csv,noheader 2>/dev/null | head -1 || true)
        GPU_NAME="${query_out:-Bilinmiyor}"

        query_out=$("$SMI_CMD" --query-gpu=memory.total --format=csv,noheader,nounits 2>/dev/null | head -1 || true)
        VRAM_MB=$(echo "${query_out:-0}" | tr -d ' ,' )
        if [[ -z "$VRAM_MB" ]]; then
            VRAM_MB="0"
        fi

        query_out=$("$SMI_CMD" --query-gpu=compute_cap --format=csv,noheader 2>/dev/null | head -1 || true)
        GPU_COMPUTE_CAPABILITY=$(echo "${query_out:-}" | tr -d '[:space:]')
        CUDA_VERSION=$("$SMI_CMD" 2>/dev/null | grep -oP 'CUDA Version: \K[\d.]+' | head -1 || true)
        DRIVER_VER=$("$SMI_CMD" --query-gpu=driver_version --format=csv,noheader 2>/dev/null | head -1 || true)

        GPU_AVAILABLE=true
        if [[ "${RUN_GPU_STRESS:-0}" != "1" ]]; then
            export RUN_GPU_STRESS=1
            info "GPU tespit edildiği için RUN_GPU_STRESS=1 otomatik etkinleştirildi."
        fi
        ok "GPU     : $GPU_NAME"
        ok "VRAM    : ${VRAM_MB} MiB"
        ok "Sürücü  : $DRIVER_VER"
        ok "CUDA    : $CUDA_VERSION"
        [[ -n "$GPU_COMPUTE_CAPABILITY" ]] && ok "Compute : $GPU_COMPUTE_CAPABILITY"

        if [[ "$WSL2" == true ]]; then
            info "WSL2 üzerinde CUDA, Windows NVIDIA sürücüsü (libcuda.so) üzerinden erişilir."
        fi
    else
        if command -v rocm-smi &>/dev/null || lspci 2>/dev/null | grep -qi "AMD/ATI"; then
            warn "AMD GPU tespit edildi. Bu kurulum akışı NVIDIA/CUDA odaklıdır; Docker için CPU profili kullanılacak."
        fi
        if [[ "$(uname -s)" == "Darwin" ]] && [[ "$(uname -m)" == "arm64" ]]; then
            warn "Apple Silicon (arm64) tespit edildi. CUDA/NVIDIA akışı devre dışı; CPU profili kullanılacak."
        fi
        warn "NVIDIA GPU bulunamadı veya nvidia-smi erişilemez — CPU modunda kurulum yapılacak."
    fi
}

# ── NVIDIA Container Toolkit Kurulumu ──────────────────────────────────────────
setup_nvidia_docker() {
    if [[ "$GPU_AVAILABLE" == true ]] && command -v docker &>/dev/null; then
        step "Docker GPU Desteği (nvidia-container-toolkit)"
        if ! command -v nvidia-ctk &>/dev/null; then
            warn "nvidia-container-toolkit bulunamadı. Kurulum başlatılıyor (sudo şifreniz istenebilir)..."

            # NVIDIA repolarını ekle ve kur
            curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg --yes
            curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | \
              sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
              sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list > /dev/null

            sudo apt-get update
            sudo apt-get install -y nvidia-container-toolkit

            # Docker'ı NVIDIA runtime kullanacak şekilde yapılandır
            sudo nvidia-ctk runtime configure --runtime=docker

            # Docker daemon'ı çalışma tipine duyarlı şekilde yeniden başlat
            info "Docker servisi yeniden başlatılıyor..."
            if command -v systemctl &>/dev/null && systemctl cat docker &>/dev/null; then
                if systemctl is-active --quiet docker; then
                    sudo systemctl restart docker
                    ok "Docker servisi systemd üzerinden yeniden başlatıldı."
                else
                    warn "Docker systemd ünitesi mevcut ama aktif değil. Docker Desktop/WSL entegrasyonu kullanılıyor olabilir."
                    info "nvidia-container-toolkit değişiklikleri için gerekirse Windows üzerinden Docker Desktop'ı yeniden başlatın."
                fi
            elif command -v service &>/dev/null && service docker status >/dev/null 2>&1; then
                sudo service docker restart
                ok "Docker servisi SysV/service üzerinden yeniden başlatıldı."
            else
                warn "Docker systemd veya service üzerinden yönetilmiyor (Docker Desktop kullanılıyor olabilir)."
                info "nvidia-container-toolkit'in aktif olması için Windows üzerinden Docker Desktop'ı yeniden başlatmanız gerekebilir."
            fi
            ok "nvidia-container-toolkit kuruldu ve Docker yapılandırıldı."
        else
            ok "nvidia-container-toolkit zaten kurulu."
        fi
    fi
}

# ── 4. uv CLI kurulumu / güncelleme ──────────────────────────────────────────
install_uv_cli() {
    step "uv CLI Paket Yöneticisi"
    export UV_PROGRESS_BAR=on
    export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"

    if ! command -v uv &>/dev/null; then
        local uv_install_script=""
        if [[ "$OFFLINE_MODE" == true ]]; then
            info "uv bulunamadı — çevrimdışı paketlerden kurulacak."
            uv_install_script="$(resolve_offline_package_file "uv/install.sh" || true)"
            [[ -z "$uv_install_script" ]] && uv_install_script="$(resolve_offline_package_file "uv_install.sh" || true)"
            [[ -z "$uv_install_script" ]] && uv_install_script="$(resolve_offline_package_file "install_uv.sh" || true)"
            [[ -n "$uv_install_script" ]] || fail "Çevrimdışı mod: offline_packages altında uv kurulum betiği bulunamadı (uv/install.sh, uv_install.sh, install_uv.sh)."
        else
            info "uv bulunamadı — resmi kurulum betiği ile indiriliyor..."
            DOWNLOADED_SCRIPT_FILE=""
            download_verified_script \
                "https://astral.sh/uv/install.sh" \
                "${UV_INSTALL_SHA256:-}" \
                "uv_install"
            validate_downloaded_script_file "$DOWNLOADED_SCRIPT_FILE" "uv_install"
            uv_install_script="$DOWNLOADED_SCRIPT_FILE"
        fi

        sh "$uv_install_script"
        [[ "$uv_install_script" == "${DOWNLOADED_SCRIPT_FILE:-}" ]] && rm -f "$DOWNLOADED_SCRIPT_FILE"
        if [[ -f "$HOME/.cargo/env" ]]; then
            # shellcheck disable=SC1090
            source "$HOME/.cargo/env"
        fi
        # Yeni kurulumlarda terminal yeniden başlatılmadan uv bulunabilsin
        export PATH="$HOME/.local/bin:$PATH"
    fi

    if ! command -v uv &>/dev/null; then
        fail "uv kurulumu başarısız oldu. Lütfen PATH ayarlarını ve kurulum çıktısını kontrol edin."
    fi
    ok "uv $(uv --version | cut -d' ' -f2)"
}

# ── 4.1 uv venv oluşturma / etkinleştirme ───────────────────────────────────
create_uv_venv() {
    step "uv venv Ortamı"
    VENV_DIR="$SCRIPT_DIR/.venv"
    info "Python sürümü uv ile sabitleniyor ($PYTHON_VERSION)..."
    uv python install "$PYTHON_VERSION"

    if [[ -d "$VENV_DIR" ]]; then
        info "Mevcut uv venv bulundu: $VENV_DIR"
    else
        info "Yeni uv venv oluşturuluyor ($PYTHON_VERSION)..."
        uv venv --python "$PYTHON_VERSION" "$VENV_DIR"
        ok "uv venv oluşturuldu."
    fi
    # shellcheck disable=SC1091
    source "$VENV_DIR/bin/activate"
    ok "Ortam aktif: $VENV_DIR"
}

# ── 5. Python bağımlılıklarını kur ───────────────────────────────────────────
install_python_deps() {
    step "Python Bağımlılıkları Kuruluyor"

    cd "$SCRIPT_DIR"
    UV_CMD=(uv)

    local -a SYNC_ARGS=(--frozen --all-extras)

    if [[ ! -f "$SCRIPT_DIR/uv.lock" ]]; then
        fail "uv.lock bulunamadı. Deterministik kurulum için önce geliştirici ortamında 'uv lock' çalıştırıp lock dosyasını repoya commit edin."
    fi

    if [[ "$UPGRADE_LOCK" == true ]]; then
        info "--upgrade-lock verildi; uv.lock bilinçli olarak güncelleniyor (uv lock --upgrade)."
        if ! env -u UV_EXTRA -u UV_ALL_EXTRAS -u UV_NO_EXTRA "${UV_CMD[@]}" lock --upgrade; then
            fail "uv lock --upgrade başarısız oldu; uv.lock güncellenemedi."
        fi
    else
        info "uv.lock korunuyor; kurulum lock dosyasını değiştirmeden yapılacak. Güncelleme için --upgrade-lock kullanın."
    fi

    info "Bağımlılıklar kilitli profilden senkronlanıyor: uv sync --frozen --all-extras. Dev araçları self-healing için standarttır."
    if ! "${UV_CMD[@]}" sync "${SYNC_ARGS[@]}"; then
        fail "uv sync --frozen --all-extras başarısız oldu. Lock dosyası pyproject ile uyumsuzsa bilinçli olarak --upgrade-lock çalıştırın."
    fi

    ok "Python bağımlılıkları kilitli uv.lock üzerinden senkronlandı."
    ensure_env_file_secrets_after_uv_sync
    validate_runtime_env_loading
}

# ── 5.1 Pyright LSP aracını kur/doğrula ─────────────────────────────────────
install_pyright_lsp_tool() {
    step "Pyright LSP Aracı"

    local venv_bin="$SCRIPT_DIR/.venv/bin"
    export PATH="$venv_bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH"

    if [[ -x "$venv_bin/pyright-langserver" ]]; then
        ok "Pyright LSP hazır: $venv_bin/pyright-langserver"
        return
    fi

    if uv run pyright-langserver --version >/dev/null 2>&1; then
        ok "Pyright LSP uv sync ortamında hazır: $(uv run python -c 'import shutil; print(shutil.which("pyright-langserver") or "uv-run")')"
        return
    fi

    fail "Pyright LSP bulunamadı. Standart akışla 'uv sync --frozen --all-extras' çalıştırın ve dev bağımlılıklarının proje ortamında kurulu olduğunu doğrulayın."
}

# ── 6. Playwright tarayıcı motorları ─────────────────────────────────────────
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
        local audio_restart_needed=false

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
            audio_restart_needed=true
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
            audio_restart_needed=true
        else
            ok "$HOME/.asoundrc zaten PulseAudio yapılandırması içeriyor."
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
                    audio_restart_needed=true
                fi
            fi
        done
        if [[ "$audio_restart_needed" == true ]]; then
            AUDIO_SESSION_RESTART_RECOMMENDED=true
        fi
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
                    sed_inplace 's/^ENABLE_MULTIMODAL=.*/ENABLE_MULTIMODAL=true/' "$env_file"
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
                    sed_inplace 's/^ENABLE_MULTIMODAL=.*/ENABLE_MULTIMODAL=false/' "$env_file"
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
        local total_bytes="0"
        local wmic_bytes=""
        local ps_bytes=""

        # Win11 24H2+ sürümlerde WMIC kaldırılabildiği için önce PowerShell/CIM yolunu dene.
        if command -v powershell.exe &>/dev/null; then
            ps_bytes=$(powershell.exe -NoProfile -Command "(Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory" 2>/dev/null \
                | tr -d '\r' \
                | awk 'NF {gsub(/^[[:space:]]+|[[:space:]]+$/, "", $0); if ($0 ~ /^[0-9]+$/) {print $0; exit}}' || true)
            if [[ -n "$ps_bytes" ]]; then
                total_bytes="$ps_bytes"
            fi
        fi
        if [[ -z "$total_bytes" || "$total_bytes" -le 0 ]] \
            && command -v cmd.exe &>/dev/null \
            && command -v wmic.exe &>/dev/null; then
            wmic_bytes=$(cmd.exe /c "wmic ComputerSystem get TotalPhysicalMemory /value" 2>/dev/null \
                | tr -d '\r' \
                | awk -F= '/^TotalPhysicalMemory=/ {gsub(/^[[:space:]]+|[[:space:]]+$/, "", $2); if ($2 ~ /^[0-9]+$/) {print $2; exit}}' || true)
            if [[ -n "$wmic_bytes" ]]; then
                total_bytes="$wmic_bytes"
            fi
        fi

        if [[ -z "$total_bytes" || "$total_bytes" -le 0 ]] && [[ -r /proc/meminfo ]]; then
            local total_kb="0"
            total_kb=$(awk '/^MemTotal:/ {print $2; exit}' /proc/meminfo 2>/dev/null || echo "0")
            if [[ -n "$total_kb" && "$total_kb" -gt 0 ]]; then
                total_bytes=$((total_kb * 1024))
            fi
        fi
        if [[ -z "$total_bytes" || "$total_bytes" -le 0 ]]; then
            echo "16"
            return
        fi
        # Yukarı yuvarla: bytes -> GB
        echo $(((total_bytes + 1073741823) / 1073741824))
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
            if mv "$tmp_file" "$cfg_file" 2>/dev/null || { cp "$tmp_file" "$cfg_file" && rm -f "$tmp_file"; }; then
                return 0
            fi
            rm -f "$tmp_file"
            return 2
        fi

        rm -f "$tmp_file"
        return 1
    }

    # [wsl2] bölümünde anahtar değerini zorla günceller (ilkini değiştirir, tekrarları temizler).
    _set_wsl2_key_value() {
        local cfg_file="$1"
        local cfg_key="$2"
        local cfg_value="$3"
        local tmp_file
        tmp_file=$(mktemp)

        awk -v key="$cfg_key" -v value="$cfg_value" '
            BEGIN { in_wsl2=0; set_key=0 }
            {
                if ($0 ~ /^\[.*\]$/) {
                    if (in_wsl2 && !set_key) {
                        print key "=" value
                        set_key=1
                    }
                    in_wsl2 = ($0 == "[wsl2]")
                    print
                    next
                }
                if (in_wsl2 && $0 ~ ("^" key "=")) {
                    if (!set_key) {
                        print key "=" value
                        set_key=1
                    }
                    next
                }
                print
            }
            END {
                if (in_wsl2 && !set_key) {
                    print key "=" value
                }
            }
        ' "$cfg_file" > "$tmp_file"

        if ! cmp -s "$cfg_file" "$tmp_file"; then
            if mv "$tmp_file" "$cfg_file" 2>/dev/null || { cp "$tmp_file" "$cfg_file" && rm -f "$tmp_file"; }; then
                return 0
            fi
            rm -f "$tmp_file"
            return 2
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
            sed_inplace "s/__SIDAR_WSL_MEMORY__/${target_memory}/g; s/__SIDAR_WSL_SWAP__/${target_swap}/g" "$wslconfig_path"
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
            local ensure_memory_rc=0
            _ensure_wsl2_key_once "$wslconfig_path" "memory" "$target_memory" || ensure_memory_rc=$?
            case $ensure_memory_rc in
                0)
                    ok "WSL2: .wslconfig içinde memory satırı düzenlendi/eklendi."
                    changed=true
                    ;;
                1)
                    : # no-op: zaten istenen durumda
                    ;;
                2)
                    warn "WSL2: .wslconfig memory satırı güncellenemedi (dosya yazma hatası)."
                    ;;
            esac

            local cur_mem cur_mem_gb
            cur_mem=$(awk '
                BEGIN { in_wsl2=0 }
                /^\[.*\]$/ { in_wsl2 = ($0 == "[wsl2]") }
                in_wsl2 && /^memory=/ { sub(/^memory=/, "", $0); print; exit }
            ' "$wslconfig_path")
            cur_mem_gb=$(_parse_gb "$cur_mem")
            if [[ "$cur_mem_gb" -lt "$target_memory_gb" ]]; then
                warn "WSL2: .wslconfig memory=${cur_mem} — bu makine için düşük olabilir (önerilen: ${target_memory})."
                local should_upgrade_mem=false
                if [[ "$SIDAR_WSL_AUTO_UPGRADE" == "true" || "$NO_INTERACTION" == true || "$AUTO_INSTALL" == true ]]; then
                    should_upgrade_mem=true
                else
                    local upgrade_mem_reply
                    upgrade_mem_reply=$(prompt_yes_no_with_timeout_default_yes "WSL2 memory=${cur_mem} düşük görünüyor. ${target_memory} değerine otomatik yükseltelim mi? [E/h]: ")
                    upgrade_mem_reply="${upgrade_mem_reply^^}"
                    if [[ "$upgrade_mem_reply" == "E" || "$upgrade_mem_reply" == "EVET" || "$upgrade_mem_reply" == "Y" || "$upgrade_mem_reply" == "YES" || -z "$upgrade_mem_reply" ]]; then
                        should_upgrade_mem=true
                    fi
                fi
                if [[ "$should_upgrade_mem" == true ]]; then
                    local set_memory_rc=0
                    _set_wsl2_key_value "$wslconfig_path" "memory" "$target_memory" || set_memory_rc=$?
                    case $set_memory_rc in
                        0)
                            ok "WSL2: .wslconfig memory ${cur_mem} -> ${target_memory} olarak yükseltildi."
                            changed=true
                            cur_mem="$target_memory"
                            ;;
                        2)
                            warn "WSL2: .wslconfig memory yazılamadı (${cur_mem} -> ${target_memory}). Lütfen dosya izinlerini kontrol edin."
                            ;;
                        *)
                            warn "WSL2: .wslconfig memory düşük kaldı (${cur_mem}). İsterseniz daha sonra ${target_memory} olarak güncelleyebilirsiniz."
                            ;;
                    esac
                else
                    warn "WSL2: .wslconfig memory düşük kaldı (${cur_mem}). İsterseniz daha sonra ${target_memory} olarak güncelleyebilirsiniz."
                fi
            elif [[ "$cur_mem_gb" -ge "$host_ram_gb" ]]; then
                warn "WSL2: .wslconfig memory=${cur_mem} — Windows host RAM'i (${host_ram_gb}GB) ile aynı/üstü; host için RAM tamponu bırakmıyor olabilir."
            else
                ok "WSL2: .wslconfig memory=${cur_mem} — yeterli."
            fi

            # [wsl2] altındaki swap= satırını tekilleştir; yoksa ekle
            local ensure_swap_rc=0
            _ensure_wsl2_key_once "$wslconfig_path" "swap" "$target_swap" || ensure_swap_rc=$?
            case $ensure_swap_rc in
                0)
                    ok "WSL2: .wslconfig içinde swap satırı düzenlendi/eklendi."
                    changed=true
                    ;;
                1)
                    : # no-op: zaten istenen durumda
                    ;;
                2)
                    warn "WSL2: .wslconfig swap satırı güncellenemedi (dosya yazma hatası)."
                    ;;
            esac

            local cur_swap cur_swap_gb
            cur_swap=$(awk '
                BEGIN { in_wsl2=0 }
                /^\[.*\]$/ { in_wsl2 = ($0 == "[wsl2]") }
                in_wsl2 && /^swap=/ { sub(/^swap=/, "", $0); print; exit }
            ' "$wslconfig_path")
            cur_swap_gb=$(_parse_gb "$cur_swap")
            if [[ "$cur_swap_gb" -lt "$target_swap_gb" ]]; then
                warn "WSL2: .wslconfig swap=${cur_swap} — bu makine için düşük olabilir (önerilen: ${target_swap})."
                local should_upgrade_swap=false
                if [[ "$SIDAR_WSL_AUTO_UPGRADE" == "true" || "$NO_INTERACTION" == true || "$AUTO_INSTALL" == true ]]; then
                    should_upgrade_swap=true
                else
                    local upgrade_swap_reply
                    upgrade_swap_reply=$(prompt_yes_no_with_timeout_default_yes "WSL2 swap=${cur_swap} düşük görünüyor. ${target_swap} değerine otomatik yükseltelim mi? [E/h]: ")
                    upgrade_swap_reply="${upgrade_swap_reply^^}"
                    if [[ "$upgrade_swap_reply" == "E" || "$upgrade_swap_reply" == "EVET" || "$upgrade_swap_reply" == "Y" || "$upgrade_swap_reply" == "YES" || -z "$upgrade_swap_reply" ]]; then
                        should_upgrade_swap=true
                    fi
                fi
                if [[ "$should_upgrade_swap" == true ]]; then
                    local set_swap_rc=0
                    _set_wsl2_key_value "$wslconfig_path" "swap" "$target_swap" || set_swap_rc=$?
                    case $set_swap_rc in
                        0)
                            ok "WSL2: .wslconfig swap ${cur_swap} -> ${target_swap} olarak yükseltildi."
                            changed=true
                            cur_swap="$target_swap"
                            ;;
                        2)
                            warn "WSL2: .wslconfig swap yazılamadı (${cur_swap} -> ${target_swap}). Lütfen dosya izinlerini kontrol edin."
                            ;;
                        *)
                            warn "WSL2: .wslconfig swap düşük kaldı (${cur_swap}). İsterseniz daha sonra ${target_swap} olarak güncelleyebilirsiniz."
                            ;;
                    esac
                else
                    warn "WSL2: .wslconfig swap düşük kaldı (${cur_swap}). İsterseniz daha sonra ${target_swap} olarak güncelleyebilirsiniz."
                fi
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
generate_secure_token() {
    local token_length="${1:-32}"
    local generated=""

    if command -v python3 &>/dev/null; then
        generated=$(python3 - <<PY
import secrets
print(secrets.token_urlsafe(${token_length}))
PY
)
    elif command -v openssl &>/dev/null; then
        generated=$(openssl rand -base64 "$token_length" | tr -d '\n')
    fi

    echo "$generated"
}

harden_database_credentials() {
    local env_file="$1"
    local db_url=""
    local sidar_env="development"
    local safe_db_url=""
    local hardening_enabled="${ENABLE_DB_PASSWORD_HARDENING:-1}"

    [[ -f "$env_file" ]] || return

    db_url=$(read_env_value_from_file "DATABASE_URL" "$env_file")
    sidar_env=$(read_env_value_from_file "SIDAR_ENV" "$env_file")
    sidar_env="${sidar_env:-development}"

    [[ -n "$db_url" ]] || return

    # Güvensiz bilinen varsayılan kimlik bilgileri (postgres:postgres vb.)
    if [[ "$db_url" =~ ^postgresql(\+asyncpg)?://([^:@/]+):([^@/]+)@(.+)$ ]]; then
        local db_user="${BASH_REMATCH[2]}"
        local db_password="${BASH_REMATCH[3]}"
        local db_host_and_name="${BASH_REMATCH[4]}"

        if is_weak_secret_value "$db_password"; then
            if [[ "$hardening_enabled" == "1" || "${FORCE_STRONG_DB_PASSWORD:-0}" == "1" ]]; then
                PRE_HARDEN_DB_PASSWORD="$db_password"
                local generated_password=""
                generated_password=$(generate_secure_token 24)
                if [[ -n "$generated_password" ]]; then
                    safe_db_url="postgresql+asyncpg://${db_user}:${generated_password}@${db_host_and_name}"
                    sed_inplace "s|^DATABASE_URL=.*|DATABASE_URL=${safe_db_url}|" "$env_file"
                    ok ".env: DATABASE_URL için güvenli bir veritabanı şifresi üretildi (SIDAR_ENV=${sidar_env})."

                    # Docker Compose ile çalışırken PostgreSQL container kimlik bilgileri
                    # DATABASE_URL ile senkron kalmalıdır.
                    if grep -q '^POSTGRES_PASSWORD=' "$env_file"; then
                        sed_inplace "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=${generated_password}|" "$env_file"
                    else
                        echo "POSTGRES_PASSWORD=${generated_password}" >> "$env_file"
                    fi
                    if grep -q '^POSTGRES_USER=' "$env_file"; then
                        sed_inplace "s|^POSTGRES_USER=.*|POSTGRES_USER=${db_user}|" "$env_file"
                    else
                        echo "POSTGRES_USER=${db_user}" >> "$env_file"
                    fi
                    local db_name_for_container="${db_host_and_name#*/}"
                    db_name_for_container="${db_name_for_container%%\?*}"
                    [[ -n "$db_name_for_container" && "$db_name_for_container" != "$db_host_and_name" ]] || db_name_for_container="sidar"
                    local container_db_url="postgresql+asyncpg://${db_user}:${generated_password}@postgres:5432/${db_name_for_container}"
                    if grep -q '^SIDAR_CONTAINER_DATABASE_URL=' "$env_file"; then
                        sed_inplace "s|^SIDAR_CONTAINER_DATABASE_URL=.*|SIDAR_CONTAINER_DATABASE_URL=${container_db_url}|" "$env_file"
                    else
                        echo "SIDAR_CONTAINER_DATABASE_URL=${container_db_url}" >> "$env_file"
                    fi
                    DB_PASSWORD_HARDENED=true
                    ok ".env: POSTGRES_USER/POSTGRES_PASSWORD değerleri DATABASE_URL ile senkronize edildi."
                    info "PostgreSQL şifresi güçlendirildi. Mevcut bir volume varsa kurulum migrasyon aşamasında otomatik olarak sıfırlayacak — manuel işlem gerekmez."
                    if command -v docker &>/dev/null && docker info >/dev/null 2>&1; then
                        local detected_pg_volume=""
                        detected_pg_volume=$(docker volume ls --format '{{.Name}}' | grep -Ei '(^|[_-])sidar([_-].*)?[_-](postgres|pg)[_-]?data$|(^|[_-])(postgres|pg)_?data$' | head -n1 || true)
                        if [[ -n "$detected_pg_volume" ]]; then
                            info "Tespit edilen PostgreSQL volume: ${detected_pg_volume} (gerekirse kurulum tarafından otomatik sıfırlanacak)."
                        fi
                    fi
                else
                    warn ".env: Güçlü veritabanı şifresi otomatik üretilemedi. DATABASE_URL parolanızı manuel güncelleyin."
                fi
            else
                warn ".env: ENABLE_DB_PASSWORD_HARDENING=1 olmadığı için otomatik DB parola güçlendirme atlandı."
                warn ".env: DATABASE_URL varsayılan/zayıf parola içeriyor (${db_user}:****)."
                warn "Parolayı manuel güncellemek isterseniz DATABASE_URL ve POSTGRES_PASSWORD alanlarını birlikte değiştirin."
            fi
        fi
    fi
}

sync_postgres_env_with_database_url() {
    local env_file="$1"
    local db_url=""

    [[ -f "$env_file" ]] || return

    db_url=$(read_env_value_from_file "DATABASE_URL" "$env_file")
    [[ -n "$db_url" ]] || return

    if [[ "$db_url" =~ ^postgresql(\+asyncpg)?://([^:@/]+):([^@/]+)@(.+)$ ]]; then
        local db_user="${BASH_REMATCH[2]}"
        local db_password="${BASH_REMATCH[3]}"
        local db_host_and_name="${BASH_REMATCH[4]}"
        local db_name="${db_host_and_name#*/}"

        # Host kısmında "/" yoksa varsayılan adı koru.
        if [[ "$db_name" == "$db_host_and_name" ]]; then
            db_name="sidar"
        fi

        # Olası query string'i temizle.
        db_name="${db_name%%\?*}"

        # Eski/çakışan satırları temizleyip en alta tek doğruluk kaynağını yaz.
        sed_inplace '/^POSTGRES_USER=/d' "$env_file"
        sed_inplace '/^POSTGRES_PASSWORD=/d' "$env_file"
        sed_inplace '/^POSTGRES_DB=/d' "$env_file"
        sed_inplace '/^DATABASE_URL=/d' "$env_file"

        local container_db_url="postgresql+asyncpg://${db_user}:${db_password}@postgres:5432/${db_name}"
        sed_inplace '/^SIDAR_CONTAINER_DATABASE_URL=/d' "$env_file"
        {
            echo "POSTGRES_USER=${db_user}"
            echo "POSTGRES_PASSWORD=${db_password}"
            echo "POSTGRES_DB=${db_name}"
            echo "DATABASE_URL=${db_url}"
            echo "SIDAR_CONTAINER_DATABASE_URL=${container_db_url}"
        } >> "$env_file"

        ok ".env: DATABASE_URL/POSTGRES_USER/POSTGRES_PASSWORD/POSTGRES_DB değerleri güvenli şekilde yeniden senkronize edildi."
    fi
}

write_generated_default_database_url() {
    local env_file="$1"
    local generated_password=""
    generated_password=$(generate_secure_token 24)
    [[ -n "$generated_password" ]] || fail "DATABASE_URL için güçlü parola üretilemedi."

    local local_db_url="postgresql+asyncpg://sidar:${generated_password}@127.0.0.1:5432/sidar"
    local container_db_url="postgresql+asyncpg://sidar:${generated_password}@postgres:5432/sidar"

    sed_inplace '/^POSTGRES_USER=/d' "$env_file"
    sed_inplace '/^POSTGRES_PASSWORD=/d' "$env_file"
    sed_inplace '/^POSTGRES_DB=/d' "$env_file"
    sed_inplace '/^DATABASE_URL=/d' "$env_file"
    sed_inplace '/^SIDAR_CONTAINER_DATABASE_URL=/d' "$env_file"
    {
        echo "POSTGRES_USER=sidar"
        echo "POSTGRES_PASSWORD=${generated_password}"
        echo "POSTGRES_DB=sidar"
        echo "DATABASE_URL=${local_db_url}"
        echo "SIDAR_CONTAINER_DATABASE_URL=${container_db_url}"
    } >> "$env_file"
    DB_PASSWORD_HARDENED=true
}

ensure_database_url_defaults() {
    local env_file="$1"
    local current_db_url=""

    if [[ ! -f "$env_file" ]]; then
        return
    fi

    current_db_url=$(read_env_value_from_file "DATABASE_URL" "$env_file")

    if [[ -z "$current_db_url" ]]; then
        write_generated_default_database_url "$env_file"
        ok ".env: DATABASE_URL güçlü rastgele PostgreSQL parolasıyla eklendi."
        return
    fi

    if [[ "$current_db_url" == sqlite* ]] && [[ "${ALLOW_SQLITE_DATABASE_URL:-0}" != "1" ]]; then
        warn ".env içinde SQLite DATABASE_URL tespit edildi: $current_db_url"
        write_generated_default_database_url "$env_file"
        ok ".env: DATABASE_URL güçlü rastgele PostgreSQL parolasıyla güncellendi."
        return
    fi

    if [[ "$current_db_url" == *lotus* ]]; then
        warn ".env içinde eski ürün adına ait DATABASE_URL tespit edildi; Sidar varsayılanına geçirilecek."
        write_generated_default_database_url "$env_file"
        ok ".env: DATABASE_URL güçlü rastgele Sidar PostgreSQL DSN değerine güncellendi."
    fi
}

ensure_rag_vector_backend_pgvector() {
    local env_file="$1"
    local current_backend=""

    if [[ ! -f "$env_file" ]]; then
        return
    fi

    current_backend=$(read_env_value_from_file "RAG_VECTOR_BACKEND" "$env_file")
    if [[ -z "$current_backend" ]]; then
        echo "RAG_VECTOR_BACKEND=pgvector" >> "$env_file"
        ok ".env: RAG_VECTOR_BACKEND=pgvector eklendi."
        return
    fi

    if [[ "$current_backend" != "pgvector" ]]; then
        sed_inplace 's|^RAG_VECTOR_BACKEND=.*|RAG_VECTOR_BACKEND=pgvector|' "$env_file"
        ok ".env: RAG_VECTOR_BACKEND pgvector olarak güncellendi."
    fi
}

# Kurulum sırasında kullanıcıdan veya SIDAR_KEYS_FILE üzerinden alınan API
# anahtarları tek merkezden yönetilir. Bu liste .env, raporlama ve .env.*
# varyant senkronizasyonunda ortak kullanılarak .env.advanced gibi şablondan
# üretilen dosyalarda boş placeholder kalması engellenir.
sidar_user_api_key_names() {
    printf '%s\n' \
        OPENAI_API_KEY GEMINI_API_KEY ANTHROPIC_API_KEY LITELLM_API_KEY HF_TOKEN \
        GITHUB_TOKEN \
        TAVILY_API_KEY GOOGLE_SEARCH_API_KEY GOOGLE_SEARCH_CX \
        SLACK_TOKEN SLACK_APP_LEVEL_TOKEN SLACK_WEBHOOK_URL SLACK_DEFAULT_CHANNEL \
        JIRA_URL JIRA_EMAIL JIRA_TOKEN JIRA_DEFAULT_PROJECT \
        TEAMS_WEBHOOK_URL
}

# ── İnteraktif API Anahtarı Toplama ──────────────────────────────────────────
# Eksik API anahtarları için zenity (GUI) → whiptail (TUI) → read (fallback)
# sırasıyla denenir; kullanıcı anahtarları girdikten sonra kurulum devam eder.
collect_api_keys_interactive() {
    local env_file="$1"

    # ── Tüm kullanıcı girişi gerektiren anahtarlar (otomatik üretilenler hariç) ──
    local -a KEY_ORDER=()
    mapfile -t KEY_ORDER < <(sidar_user_api_key_names)
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

    _api_key_env_targets() {
        local -a targets=("$env_file")
        local advanced_env_file="$SCRIPT_DIR/.env.advanced"
        local advanced_example_file="$SCRIPT_DIR/.env.advanced.example"
        local optional_env_file

        if [[ ! -f "$advanced_env_file" && -f "$advanced_example_file" ]]; then
            cp "$advanced_example_file" "$advanced_env_file"
            ok ".env.advanced dosyası .env.advanced.example'dan API anahtarı senkronizasyonu için oluşturuldu."
        fi

        [[ -f "$advanced_env_file" && "$advanced_env_file" != "$env_file" ]] && targets+=("$advanced_env_file")

        for optional_env_file in "$SCRIPT_DIR/.env.development" "$SCRIPT_DIR/.env.test"; do
            [[ -f "$optional_env_file" && "$optional_env_file" != "$env_file" ]] && targets+=("$optional_env_file")
        done

        printf '%s\n' "${targets[@]}"
    }

    # Anahtarı .env ve mevcut runtime env varyantlarına yazar; boşsa sessizce atlar.
    _write_key() {
        local key="$1"
        local val target target_name
        local -a target_env_files=()
        val=$(printf '%s' "${2:-}" | tr -d '\r\n ')
        [[ -z "$val" ]] && return

        mapfile -t target_env_files < <(_api_key_env_targets)
        for target in "${target_env_files[@]}"; do
            if grep -q "^${key}=" "$target" 2>/dev/null; then
                sed_inplace "s|^${key}=.*|${key}=${val}|" "$target"
            else
                echo "${key}=${val}" >> "$target"
            fi
            target_name="$(basename "$target")"
            ok "${target_name}: ${key} güncellendi."
        done
    }

    _warn_if_missing_critical_provider_keys() {
        local openai_key=""
        local anthropic_key=""

        openai_key=$(read_env_value_from_file "OPENAI_API_KEY" "$env_file" | tr -d '[:space:]')
        anthropic_key=$(read_env_value_from_file "ANTHROPIC_API_KEY" "$env_file" | tr -d '[:space:]')

        if [[ -z "$openai_key" && -z "$anthropic_key" ]]; then
            warn "[UYARI] Kritik sağlayıcı anahtarı eksik: OPENAI_API_KEY veya ANTHROPIC_API_KEY alanlarından en az biri boş."
            warn "[UYARI] Kurulum durdurulmadı. Lütfen .env dosyasını sonradan manuel güncelleyin."
        fi
    }

    _sync_existing_api_keys_to_env_targets() {
        local key current_val
        for key in "${KEY_ORDER[@]}"; do
            current_val=$(read_env_value_from_file "$key" "$env_file" | tr -d '\n')
            [[ -z "${current_val//[[:space:]]/}" ]] && continue
            _write_key "$key" "$current_val"
        done
    }

    if [[ "$NO_INTERACTION" == true ]]; then
        info "--ci/--no-interaction etkin: API anahtarı etkileşimli toplama adımı atlandı."
        _sync_existing_api_keys_to_env_targets
        return
    fi

    # ~/.sidar_keys.env gibi kalıcı bir dosyadan anahtarları içeri al.
    # Dosya varsa etkileşimli (zenity/whiptail/read) adımı tamamen atlanır.
    _import_api_keys_from_file() {
        local source_file="$1"
        local imported_count=0
        local key raw_val

        [[ -f "$source_file" ]] || return 1

        info "API anahtarları ${source_file} dosyasından içeri alınıyor (etkileşimli giriş atlanacak)..."
        for key in "${KEY_ORDER[@]}"; do
            raw_val=$(read_env_value_from_file "$key" "$source_file")
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
        _chk_val=$(read_env_value_from_file "$key" "$env_file" | tr -d '\n')
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
        _sync_existing_api_keys_to_env_targets
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
        _sync_existing_api_keys_to_env_targets
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
        _sync_existing_api_keys_to_env_targets
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
            clear_stdin_buffer
            IFS= read -rs input || true
            echo ""
            _write_key "$mk" "$input"
        done
        echo ""
    done
    ok "API anahtar girişi tamamlandı, kurulum devam ediyor."
    _sync_existing_api_keys_to_env_targets
    _warn_if_missing_critical_provider_keys
}

report_env_api_key_status() {
    local env_file="$1"
    local -a key_order=()
    mapfile -t key_order < <(sidar_user_api_key_names)

    ENV_API_KEYS_TOTAL="${#key_order[@]}"
    ENV_API_KEYS_FILLED=0
    ENV_API_KEYS_MISSING=()

    local key value
    for key in "${key_order[@]}"; do
        value=$(read_env_value_from_file "$key" "$env_file" | tr -d '\n')
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
    suffix = f" ({override}) {path}" if event.get("loaded") else ""
    print(f"  - {label}: {status}{suffix}")

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
    propagate_shared_secrets_to_env_variants "$env_file"
}

# ── Otomatik Secret Üretimi ────────────────────────────────────────────────
# Güvenlik anahtarlarını (API_KEY, JWT_SECRET_KEY, MEMORY_ENCRYPTION_KEY vb.)
# .env boşsa veya bilinen güvensiz örnekse otomatik üretir.
# Hem yeni oluşturulan hem de mevcut .env üzerinde çalışır.
ensure_auto_secrets() {
    local env_file="$1"

    # Boş, eksik veya bilinen güvensiz değer mi? → 0 (true) döner.
    # Bilinen örnek değerler merkezi weak-secret listesi ve .env.example üzerinden
    # okunur; bu fonksiyon gizli/örnek literal değerleri install script içinde
    # tekrar gömmemelidir.
    _is_missing_or_insecure() {
        local key="$1"
        local val
        val=$(read_env_value_from_file "$key" "$env_file" | tr -d '\n')
        is_weak_secret_value "$val" && return 0
        is_known_weak_secret_value "$key" "$val" && return 0
        is_env_example_secret_value "$key" "$val" && return 0
        return 1
    }

    # Üretilen değeri .env'e yazar (varsa günceller, yoksa satır ekler)
    _write_secret() {
        local key="$1" val="$2"
        if grep -q "^${key}=" "$env_file" 2>/dev/null; then
            sed_inplace "s|^${key}=.*|${key}=${val}|" "$env_file"
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
    if _is_missing_or_insecure "POSTGRES_PASSWORD"; then
        local _v; _v=$(_gen_urlsafe 24)
        if [[ -n "$_v" ]]; then
            _write_secret "POSTGRES_PASSWORD" "$_v"
            ok ".env: POSTGRES_PASSWORD otomatik ve güvenli bir değerle oluşturuldu."
        else
            warn "POSTGRES_PASSWORD otomatik üretilemedi. Lütfen .env içinde güçlü bir değer tanımlayın."
        fi
    fi

    # ── API_KEY ──────────────────────────────────────────────────────────────
    if _is_missing_or_insecure "API_KEY"; then
        local _v; _v=$(_gen_urlsafe 32)
        if [[ -n "$_v" ]]; then
            _write_secret "API_KEY" "$_v"
            ok ".env: API_KEY otomatik ve güvenli bir değerle oluşturuldu."
        else
            warn "API_KEY otomatik üretilemedi. Lütfen .env içinde güçlü bir değer tanımlayın."
        fi
    fi

    # ── JWT_SECRET_KEY ────────────────────────────────────────────────────────
    if _is_missing_or_insecure "JWT_SECRET_KEY"; then
        local _v; _v=$(_gen_urlsafe 64)
        if [[ -n "$_v" ]]; then
            _write_secret "JWT_SECRET_KEY" "$_v"
            ok ".env: JWT_SECRET_KEY otomatik ve güvenli bir değerle oluşturuldu."
        else
            warn "JWT_SECRET_KEY otomatik üretilemedi. Lütfen .env içinde güçlü bir değer tanımlayın."
        fi
    fi

    # ── MEMORY_ENCRYPTION_KEY (Fernet) ────────────────────────────────────────
    if _is_missing_or_insecure "MEMORY_ENCRYPTION_KEY"; then
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

    _auto_hex_secret "AUTONOMY_WEBHOOK_SECRET" 64
    _auto_hex_secret "SWARM_FEDERATION_SHARED_SECRET" 64
    _auto_hex_secret "GITHUB_WEBHOOK_SECRET" 40

    # ── GRAFANA_ADMIN_PASSWORD ────────────────────────────────────────────────
    if _is_missing_or_insecure "GRAFANA_ADMIN_PASSWORD"; then
        local _v; _v=$(_gen_urlsafe 32)
        if [[ -n "$_v" ]]; then
            _write_secret "GRAFANA_ADMIN_PASSWORD" "$_v"
            ok ".env: GRAFANA_ADMIN_PASSWORD otomatik ve güvenli bir değerle oluşturuldu."
        else
            warn "GRAFANA_ADMIN_PASSWORD otomatik üretilemedi. Lütfen .env içinde güçlü bir değer tanımlayın."
        fi
    fi

    # ── METRICS_TOKEN ─────────────────────────────────────────────────────────
    # /metrics uçlarını koruyan Bearer token; örnek/legacy değerler merkezi listeden denetlenir.
    if _is_missing_or_insecure "METRICS_TOKEN"; then
        local _v; _v=$(_gen_urlsafe 32)
        if [[ -n "$_v" ]]; then
            _write_secret "METRICS_TOKEN" "$_v"
            ok ".env: METRICS_TOKEN otomatik ve güvenli bir değerle oluşturuldu."
        else
            warn "METRICS_TOKEN otomatik üretilemedi. Lütfen .env içinde güçlü bir değer tanımlayın."
        fi
    fi
}

propagate_shared_secrets_to_env_variants() {
    local src="$1"
    local -a shared_keys=(
        POSTGRES_PASSWORD
        DATABASE_URL
        SIDAR_CONTAINER_DATABASE_URL
        API_KEY
        JWT_SECRET_KEY
        MEMORY_ENCRYPTION_KEY
        AUTONOMY_WEBHOOK_SECRET
        SWARM_FEDERATION_SHARED_SECRET
        GITHUB_WEBHOOK_SECRET
        GRAFANA_ADMIN_PASSWORD
        METRICS_TOKEN
    )
    local -a variants=(
        ".env.development:.env.development.example"
        ".env.test:.env.test.example"
        ".env.advanced:.env.advanced.example"  # Sürüm kontrollü şablondan üretilen advanced runtime env.
    )

    [[ -f "$src" ]] || return 0

    local pair target example name key val cur example_val
    for pair in "${variants[@]}"; do
        target="$SCRIPT_DIR/${pair%%:*}"
        example="$SCRIPT_DIR/${pair##*:}"
        name="${pair%%:*}"

        if [[ ! -f "$target" ]]; then
            if [[ -f "$example" ]]; then
                cp "$example" "$target"
                ok "${name} dosyası ${pair##*:} üzerinden oluşturuldu."
            else
                warn "${pair##*:} bulunamadı; ${name} secret senkronizasyonu atlandı."
                continue
            fi
        fi

        for key in "${shared_keys[@]}"; do
            val=$(read_env_value_from_file "$key" "$src" | tr -d '\n')
            [[ -z "${val//[[:space:]]/}" ]] && continue

            cur=$(read_env_value_from_file "$key" "$target" | tr -d '\n')
            example_val=$(read_env_value_from_file "$key" "$example" | tr -d '\n')

            local always_overwrite=false
            case "$key" in
                POSTGRES_PASSWORD|DATABASE_URL|SIDAR_CONTAINER_DATABASE_URL)
                    always_overwrite=true
                    ;;
            esac

            if [[ "$always_overwrite" == true ]] \
                || is_weak_secret_value "$cur" \
                || is_known_weak_secret_value "$key" "$cur" \
                || is_env_example_secret_value "$key" "$cur" \
                || [[ -n "${example_val//[[:space:]]/}" && "$cur" == "$example_val" ]]; then
                if grep -q "^${key}=" "$target" 2>/dev/null; then
                    sed_inplace "s|^${key}=.*|${key}=${val}|" "$target"
                else
                    echo "${key}=${val}" >> "$target"
                fi
                ok "${name}: ${key} .env ile senkronize edildi."
            fi
        done
    done
}

ensure_local_service_host_defaults() {
    local env_file="$1"
    # Lokal kurulumda Docker hostname yerine localhost kullan
    if grep -q '^REDIS_URL=redis://redis:6379/0' "$env_file"; then
        sed_inplace 's|^REDIS_URL=redis://redis:6379/0|REDIS_URL=redis://localhost:6379/0|' "$env_file"
        ok ".env: REDIS_URL lokal ortam için localhost olarak güncellendi."
    fi

    if grep -q '^OTEL_EXPORTER_ENDPOINT=http://jaeger:' "$env_file"; then
        sed_inplace 's|^OTEL_EXPORTER_ENDPOINT=http://jaeger:|OTEL_EXPORTER_ENDPOINT=http://localhost:|' "$env_file"
        ok ".env: OTEL_EXPORTER_ENDPOINT lokal ortam için localhost olarak güncellendi."
    fi
}

ensure_sidar_env_default() {
    local env_file="$1"
    local current_env=""

    current_env=$(read_env_value_from_file "SIDAR_ENV" "$env_file" | tr -d '"'\''[:space:]')

    if [[ -z "$current_env" ]]; then
        echo "SIDAR_ENV=development" >> "$env_file"
        ok ".env: SIDAR_ENV=development eklendi."
        return
    fi

    if [[ "$current_env" == "production" ]]; then
        sed_inplace 's/^SIDAR_ENV=.*/SIDAR_ENV=development/' "$env_file"
        warn ".env: SIDAR_ENV=production varsayılanı development olarak düzeltildi (üretimde manuel production yapın)."
    fi
}

prompt_post_install_sidar_env_mode() {
    local env_file="$SCRIPT_DIR/.env"
    local example_file="$SCRIPT_DIR/.env.example"
    local env_choice=""
    local selected_env="development"
    local previous_env=""

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
    previous_env="$(read_env_value_from_file "SIDAR_ENV" "$env_file" | tr -d '"'\''[:space:]')"

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

        clear_stdin_buffer
        if read -r -t "$SIDAR_PROMPT_TIMEOUT" -p "Seçiminiz (1 veya 2, varsayılan=1): " env_choice 2>/dev/tty; then
            :
        else
            warn "${SIDAR_PROMPT_TIMEOUT} saniye içinde seçim yapılmadı. Varsayılan seçim: 1 (Development)."
            env_choice="1"
        fi

        if [[ "$env_choice" == "2" ]]; then
            selected_env="production"
        fi
    fi

    if grep -qE '^SIDAR_ENV=' "$env_file"; then
        sed_inplace "s/^SIDAR_ENV=.*/SIDAR_ENV=$selected_env/" "$env_file"
    else
        echo "SIDAR_ENV=$selected_env" >> "$env_file"
    fi

    if [[ "$selected_env" == "production" ]]; then
        ok "🚀 Ortam değişkenleri 'Production' (Canlı Kullanım) olarak güncellendi."
    else
        ok "🛠️ Ortam değişkenleri 'Development' (Geliştirme) olarak güncellendi."
        if [[ "$previous_env" != "$selected_env" ]]; then
            info "SIDAR_ENV değişti (${previous_env:-bilinmiyor} -> ${selected_env}); veritabanı migrasyonu tekrar doğrulanıyor..."
            run_migrations
        elif ! is_alembic_at_head; then
            info "Alembic current/head uyuşmuyor; veritabanı migrasyonu tekrar doğrulanıyor..."
            run_migrations
        else
            info "SIDAR_ENV değişmedi ve Alembic current=head; tekrar migrasyon atlandı."
        fi
    fi

    ok "Sidar kullanıma hazır!"
}


get_env_value() {
    local env_file="$1" key="$2"
    read_env_value_from_file "$key" "$env_file"
}

secret_strength_script_file() {
    local primary="${SCRIPT_DIR}/scripts/secret_strength.py"
    local original="${ORIGINAL_SCRIPT_DIR}/scripts/secret_strength.py"
    if [[ -f "$primary" ]]; then
        printf '%s\n' "$primary"
    elif [[ -f "$original" ]]; then
        printf '%s\n' "$original"
    fi
}

is_weak_secret_value() {
    local value="${1:-}"
    local strength_script=""
    local strength_status=0
    [[ -n "${value//[[:space:]]/}" ]] || return 0

    strength_script="$(secret_strength_script_file)"
    if [[ -n "$strength_script" ]] && command -v python3 &>/dev/null; then
        if python3 "$strength_script" --quiet -- "$value"; then
            return 0
        fi
        strength_status="$?"
        [[ "$strength_status" == "1" ]] && return 1
    fi

    case "${value,,}" in
        *password*|*passwd*|sidar|admin|changeme|change_me|change-me*|replace-with-*|*secret*|default|*test*|example|postgres|root|*qwerty*|*letmein*|*welcome*|123456|12345678|*1234*|*abcd*|*asdf*|*zxcv*)
            return 0
            ;;
    esac
    (( ${#value} < 24 )) && return 0
    [[ "$value" =~ (.)\1\1\1 ]] && return 0
    return 1
}

known_weak_secrets_file() {
    local primary="${SCRIPT_DIR}/scripts/known_weak_secrets.txt"
    local original="${ORIGINAL_SCRIPT_DIR}/scripts/known_weak_secrets.txt"
    if [[ -f "$primary" ]]; then
        printf '%s\n' "$primary"
    elif [[ -f "$original" ]]; then
        printf '%s\n' "$original"
    fi
}

is_known_weak_secret_value() {
    local key="$1" value="${2:-}" weak_file line entry_key entry_value
    [[ -n "${value//[[:space:]]/}" ]] || return 1
    weak_file="$(known_weak_secrets_file)"
    [[ -n "$weak_file" && -f "$weak_file" ]] || return 1

    while IFS= read -r line || [[ -n "$line" ]]; do
        line="${line%$'\r'}"
        [[ -n "${line//[[:space:]]/}" ]] || continue
        [[ "${line:0:1}" == "#" ]] && continue
        [[ "$line" == *=* ]] || continue
        entry_key="${line%%=*}"
        entry_value="${line#*=}"
        entry_key="${entry_key//[[:space:]]/}"
        [[ "$entry_key" == "$key" || "$entry_key" == "*" ]] || continue
        [[ "$value" == "$entry_value" ]] && return 0
    done < "$weak_file"

    return 1
}

is_env_example_secret_value() {
    local key="$1" value="${2:-}" example_file example_value
    [[ -n "${value//[[:space:]]/}" ]] || return 1

    for example_file in "${SCRIPT_DIR}/.env.example" "${ORIGINAL_SCRIPT_DIR}/.env.example"; do
        [[ -f "$example_file" ]] || continue
        example_value=$(read_env_value_from_file "$key" "$example_file" | tr -d '\n')
        [[ -n "${example_value//[[:space:]]/}" ]] || continue
        [[ "$value" == "$example_value" ]] && return 0
    done

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

sync_database_env_chain_after_setup() {
    if ! command -v uv &>/dev/null; then
        warn "uv bulunamadı; PostgreSQL dotenv zinciri Python senkronizasyonu atlandı."
        return 0
    fi

    if [[ ! -f "$SCRIPT_DIR/scripts/sync_database_passwords.py" ]]; then
        warn "scripts.sync_database_passwords bulunamadı; PostgreSQL dotenv zinciri Python senkronizasyonu atlandı."
        return 0
    fi

    info "Ortam değişkenlerindeki veritabanı şifre çakışmaları temizleniyor..."
    if (cd "$SCRIPT_DIR" && uv run python -m scripts.sync_database_passwords --remove-explicit-urls >/dev/null 2>&1); then
        ok ".env zincirindeki PostgreSQL şifreleri kalıcı olarak eşitlendi."
    else
        warn "PostgreSQL dotenv zinciri Python senkronizasyonu tamamlanamadı; gerekirse manuel çalıştırın: "\
            "uv run python -m scripts.sync_database_passwords --remove-explicit-urls"
    fi
}

setup_env_file() {
    step ".env Yapılandırması"
    ENV_FILE="$SCRIPT_DIR/.env"
    EXAMPLE_FILE="$SCRIPT_DIR/.env.example"

    ADVANCED_ENV_FILE="$SCRIPT_DIR/.env.advanced"
    ADVANCED_EXAMPLE_FILE="$SCRIPT_DIR/.env.advanced.example"

    # .env.advanced eksikse example üzerinden oluştur. Secret değerleri
    # ensure_auto_secrets sonrasında propagate_shared_secrets_to_env_variants
    # ile .env dosyasından senkronize edilir.
    if [[ ! -f "$ADVANCED_ENV_FILE" && -f "$ADVANCED_EXAMPLE_FILE" ]]; then
        cp "$ADVANCED_EXAMPLE_FILE" "$ADVANCED_ENV_FILE"
        ok ".env.advanced dosyası .env.advanced.example'dan oluşturuldu."
    fi

    if [[ -f "$ENV_FILE" ]]; then
        ok ".env dosyası zaten mevcut — varsayılanlar ve güvenlik anahtarları kontrol ediliyor."
        ensure_sidar_env_default "$ENV_FILE"
        ensure_database_url_defaults "$ENV_FILE"
        ensure_rag_vector_backend_pgvector "$ENV_FILE"
        harden_database_credentials "$ENV_FILE"
        ensure_local_service_host_defaults "$ENV_FILE"
        ensure_auto_secrets "$ENV_FILE"
        propagate_shared_secrets_to_env_variants "$ENV_FILE"
        validate_required_security_profile "$ENV_FILE"
        collect_api_keys_interactive "$ENV_FILE"
        report_env_api_key_status "$ENV_FILE"
        sync_database_env_chain_after_setup
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
    ensure_local_service_host_defaults "$ENV_FILE"

    sync_postgres_env_with_database_url "$ENV_FILE"

    # Güvenlik secret'larını üret/doğrula (her iki yolda da çalışan üst-düzey fonksiyon)
    ensure_auto_secrets "$ENV_FILE"
    propagate_shared_secrets_to_env_variants "$ENV_FILE"
    validate_required_security_profile "$ENV_FILE"

    # GPU tespitine göre USE_GPU/GPU_MIXED_PRECISION değerlerini uyumlu hale getir
    if command -v sed &>/dev/null; then
        if [[ "$GPU_AVAILABLE" == true ]]; then
            info "DEBUG: GPU branch entered for .env configuration (GPU_AVAILABLE=true)."
            if grep -q '^USE_GPU=' "$ENV_FILE"; then
                sed_inplace 's/^USE_GPU=.*/USE_GPU=true/' "$ENV_FILE"
            else
                echo 'USE_GPU=true' >> "$ENV_FILE"
            fi
            if grep -q '^GPU_MIXED_PRECISION=' "$ENV_FILE"; then
                sed_inplace 's/^GPU_MIXED_PRECISION=.*/GPU_MIXED_PRECISION=true/' "$ENV_FILE"
            else
                echo 'GPU_MIXED_PRECISION=true' >> "$ENV_FILE"
            fi

            # Docker için GPU modunu ön tanımlı yap
            if grep -q '^COMPOSE_PROFILES=' "$ENV_FILE"; then
                sed_inplace 's/^COMPOSE_PROFILES=.*/COMPOSE_PROFILES=gpu/' "$ENV_FILE"
            else
                echo "COMPOSE_PROFILES=gpu" >> "$ENV_FILE"
            fi

            ok ".env: USE_GPU=true, GPU_MIXED_PRECISION=true (GPU tespit edildi)"
            ok ".env: COMPOSE_PROFILES=gpu ayarlandı (Docker GPU modu artık varsayılan)."
        else
            if grep -q '^USE_GPU=' "$ENV_FILE"; then
                sed_inplace 's/^USE_GPU=.*/USE_GPU=false/' "$ENV_FILE"
            else
                echo 'USE_GPU=false' >> "$ENV_FILE"
            fi
            if grep -q '^GPU_MIXED_PRECISION=' "$ENV_FILE"; then
                sed_inplace 's/^GPU_MIXED_PRECISION=.*/GPU_MIXED_PRECISION=false/' "$ENV_FILE"
            else
                echo 'GPU_MIXED_PRECISION=false' >> "$ENV_FILE"
            fi
            if grep -q '^COMPOSE_PROFILES=' "$ENV_FILE"; then
                sed_inplace 's/^COMPOSE_PROFILES=.*/COMPOSE_PROFILES=cpu/' "$ENV_FILE"
            else
                echo "COMPOSE_PROFILES=cpu" >> "$ENV_FILE"
            fi
            ok ".env: USE_GPU=false, GPU_MIXED_PRECISION=false, COMPOSE_PROFILES=cpu ayarlandı."
        fi
    fi

    # Docker + GPU tespit edildiyse NVIDIA runtime'ı varsayılan yap
    if [[ "$GPU_AVAILABLE" == true ]] && command -v docker &>/dev/null && command -v sed &>/dev/null; then
        if grep -q '^DOCKER_RUNTIME=' "$ENV_FILE"; then
            sed_inplace 's/^DOCKER_RUNTIME=.*/DOCKER_RUNTIME=nvidia/' "$ENV_FILE"
        else
            echo 'DOCKER_RUNTIME=nvidia' >> "$ENV_FILE"
        fi

        if grep -q '^DOCKER_ALLOWED_RUNTIMES=' "$ENV_FILE"; then
            if ! grep -q '^DOCKER_ALLOWED_RUNTIMES=.*nvidia' "$ENV_FILE"; then
                sed_inplace 's/^DOCKER_ALLOWED_RUNTIMES=.*/DOCKER_ALLOWED_RUNTIMES=runc,runsc,kata-runtime,nvidia/' "$ENV_FILE"
            fi
        else
            echo 'DOCKER_ALLOWED_RUNTIMES=runc,runsc,kata-runtime,nvidia' >> "$ENV_FILE"
        fi

        ok ".env: Docker GPU varsayılanları ayarlandı (DOCKER_RUNTIME=nvidia)."
    fi

    collect_api_keys_interactive "$ENV_FILE"
    sync_database_env_chain_after_setup
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

download_ollama_models() {
    step "Ollama Modelleri Hazırlanıyor"
    local estimated_size_gb="~14.8 GB"
    local temp_ollama_pid=""
    local ollama_tags_url=""
    local tags_payload=""
    local existing_model_count=0
    local env_file="$SCRIPT_DIR/.env"
    local missing_required_models=""
    local resolved_models_csv=""
    local should_prompt_for_download=true
    local -a models_to_pull=()
    local -a models=()
    _count_ollama_models_from_tags() {
        local payload="$1"
        if command -v python3 &>/dev/null; then
            python3 - "$payload" <<'PY' 2>/dev/null || echo "0"
import json
import sys
raw = sys.argv[1] if len(sys.argv) > 1 else ""
try:
    data = json.loads(raw)
except Exception:
    print("0")
    raise SystemExit(0)
models = data.get("models")
if isinstance(models, list):
    print(str(sum(1 for m in models if isinstance(m, dict) and m.get("name"))))
else:
    print("0")
PY
        else
            printf "%s" "$payload" | grep -o '"name"[[:space:]]*:' | wc -l | tr -d '[:space:]'
        fi
    }
    _model_exists_in_tags() {
        local payload="$1"
        local model_name="$2"
        if [[ -z "$payload" || -z "$model_name" ]]; then
            return 1
        fi
        if command -v python3 &>/dev/null; then
            python3 - "$payload" "$model_name" <<'PY' >/dev/null 2>&1
import json
import sys

raw = sys.argv[1] if len(sys.argv) > 1 else ""
target = (sys.argv[2] if len(sys.argv) > 2 else "").strip()
if not target:
    raise SystemExit(1)
try:
    data = json.loads(raw)
except Exception:
    raise SystemExit(1)
models = data.get("models")
if not isinstance(models, list):
    raise SystemExit(1)
names = {m.get("name") for m in models if isinstance(m, dict) and isinstance(m.get("name"), str)}
if target in names:
    raise SystemExit(0)
# Kullanıcı modeli etiketsiz verdiyse Ollama'da sık görülen :latest eşleşmesini de kabul et.
if ":" not in target and f"{target}:latest" in names:
    raise SystemExit(0)
raise SystemExit(1)
PY
            return $?
        fi

        if printf "%s" "$payload" | grep -q "\"name\"[[:space:]]*:[[:space:]]*\"${model_name}\""; then
            return 0
        fi
        if [[ "$model_name" != *:* ]] && printf "%s" "$payload" | grep -q "\"name\"[[:space:]]*:[[:space:]]*\"${model_name}:latest\""; then
            return 0
        fi
        return 1
    }
    cleanup_temp_ollama() {
        if [[ -n "${temp_ollama_pid:-}" ]] && kill -0 "${temp_ollama_pid:-}" >/dev/null 2>&1; then
            info "Geçici ollama serve süreci sonlandırılıyor (PID: ${temp_ollama_pid:-})..."
            kill "${temp_ollama_pid:-}" >/dev/null 2>&1 || true
            # Sürecin tamamen kapanmasını bekle; böylece 11434 portu Docker Ollama
            # servisi başlamadan önce işletim sistemi tarafından serbest bırakılır.
            local _i
            for _i in {1..10}; do
                kill -0 "${temp_ollama_pid:-}" >/dev/null 2>&1 || break
                sleep 1
            done
        fi
    }
    trap cleanup_temp_ollama RETURN

    if [[ "$WSL2" == true && "$WSLCONFIG_CHANGED" == true ]]; then
        warn "WSL2 .wslconfig bu kurulumda güncellendi; yeni memory/swap limitleri henüz etkin değil."
        info "Model indirme işlemleri güvenlik için ertelendi. Önce Windows PowerShell'de şunu çalıştırın:"
        echo "  wsl --shutdown"
        info "Ardından dağıtımı yeniden açıp modelleri indirmek için tekrar çalıştırın: ./install_sidar.sh --download-models"
        return
    fi

    if [[ "$SKIP_MODELS" == true ]]; then
        info "--skip-models bayrağı verildi, model indirmeleri atlanıyor."
        return
    fi

    OLLAMA_VERSION_URL=$(resolve_ollama_version_url "$SCRIPT_DIR/.env")
    OLLAMA_BASE_URL="${OLLAMA_VERSION_URL%/api/version}"
    ollama_tags_url="${OLLAMA_BASE_URL}/api/tags"

    if [[ ! -f "$env_file" ]]; then
        warn ".env bulunamadı, varsayılan modeller indirilemedi."
        return
    fi

    TEXT_MOD=$(read_env_value_from_file "TEXT_MODEL" "$env_file")
    CODE_MOD=$(read_env_value_from_file "CODING_MODEL" "$env_file")
    VISION_MOD=$(read_env_value_from_file "VISION_MODEL" "$env_file")
    MULTIMODAL=$(read_env_value_from_file "ENABLE_MULTIMODAL" "$env_file")

    if [[ -z "$TEXT_MOD" ]]; then
        TEXT_MOD="llama3.1:8b"
        warn "TEXT_MODEL boş/geçersiz görünüyor, varsayılan kullanılacak: $TEXT_MOD"
    fi
    if [[ -z "$CODE_MOD" ]]; then
        CODE_MOD="qwen2.5-coder:7b"
        warn "CODING_MODEL boş/geçersiz görünüyor, varsayılan kullanılacak: $CODE_MOD"
    fi
    models=("$TEXT_MOD" "$CODE_MOD" "nomic-embed-text")
    if [[ "${MULTIMODAL,,}" == "true" && -n "$VISION_MOD" ]]; then
        models+=("$VISION_MOD")
    fi

    # Etkileşimli "indirilsin mi?" sorusundan önce mevcut model adlarını doğrula.
    # Sadece sayıya göre değil, projede gereken model adlarına göre karar ver.
    if command -v ollama &>/dev/null; then
        tags_payload=$(curl -sf "$ollama_tags_url" 2>/dev/null || true)
        if [[ -n "$tags_payload" ]]; then
            existing_model_count=$(_count_ollama_models_from_tags "$tags_payload")
            for model in "${models[@]}"; do
                [[ -n "$model" ]] || continue
                if _model_exists_in_tags "$tags_payload" "$model"; then
                    continue
                fi
                models_to_pull+=("$model")
            done

            if (( ${#models_to_pull[@]} == 0 )); then
                ok "Ollama üzerinde ${existing_model_count} model mevcut ve gerekli modeller zaten yüklü (${ollama_tags_url})."
                run_coding_model_smoke_prompt "$CODE_MOD" "$OLLAMA_BASE_URL"
                return
            fi

            if [[ "$DOWNLOAD_MODELS" != true ]]; then
                missing_required_models=$(IFS=', '; echo "${models_to_pull[*]}")
                warn "Ollama'da model(ler) eksik: ${missing_required_models}. Sadece eksik modeller indirilecek."
                should_prompt_for_download=false
            fi
        fi
    fi

    if [[ "$DOWNLOAD_MODELS" != true && "$should_prompt_for_download" == true ]]; then
        if [[ "$NO_INTERACTION" == true ]]; then
            info "--ci/--no-interaction etkin ve --download-models verilmedi: model indirmeleri atlanıyor (${estimated_size_gb})."
            info "Model indirmek için: ./install_sidar.sh --download-models"
            return
        fi
        reply=$(prompt_yes_no_with_timeout_default_yes "Modeller indirilecek (${estimated_size_gb}). Devam edilsin mi? [E/h] ")
        case "${reply:-E}" in
            [HhNn]*)
                info "Model indirmesi kullanıcı tercihiyle atlandı."
                return
                ;;
        esac
    fi

    if ! command -v ollama &>/dev/null; then
        warn "Ollama bulunamadı, model indirme atlanıyor."
        return
    fi

    if ! curl -sf "$OLLAMA_VERSION_URL" &>/dev/null; then
        info "Ollama API erişilemedi (${OLLAMA_VERSION_URL})."
        if is_local_ollama_url "$OLLAMA_BASE_URL"; then
            info "Yerel Ollama servisi başlatma deneniyor..."
            if command -v systemctl &>/dev/null && command -v sudo &>/dev/null; then
                sudo systemctl enable --now ollama >/dev/null 2>&1 || true
            fi
            # systemd yoksa veya servis ayağa kalkmadıysa son çare olarak geçici süreç başlat.
            if ! curl -sf "$OLLAMA_VERSION_URL" &>/dev/null; then
                info "systemd ile Ollama doğrulanamadı, geçici 'ollama serve' süreci başlatılıyor..."
                ollama serve >/dev/null 2>&1 &
                temp_ollama_pid=$!
            fi
            for _ in {1..12}; do
                if curl -sf "$OLLAMA_VERSION_URL" &>/dev/null; then
                    break
                fi
                sleep 5
            done
        else
            warn "Uzak Ollama endpoint'i tespit edildi (${OLLAMA_BASE_URL}). Otomatik servis başlatma atlandı."
        fi
    fi

    if ! curl -sf "$OLLAMA_VERSION_URL" &>/dev/null; then
        warn "Ollama servisi doğrulanamadı (${OLLAMA_VERSION_URL}), model indirme atlanıyor."
        return
    fi

    if (( ${#models_to_pull[@]} == 0 )); then
        models_to_pull=("${models[@]}")
    fi

    resolved_models_csv=$(IFS=', '; echo "${models_to_pull[*]}")
    info "İndirilecek model listesi: ${resolved_models_csv}"

    for model in "${models_to_pull[@]}"; do
        if [[ -n "$model" ]]; then
            info "-> $model indiriliyor (bu işlem zaman alabilir)..."
            local pull_success=false
            for attempt in 1 2 3; do
                if ollama pull "$model"; then
                    pull_success=true
                    break
                fi
                warn "Model indirme denemesi başarısız (${model}) [${attempt}/3]."
                if [[ "$attempt" -lt 3 ]]; then
                    local backoff=$((attempt * 5))
                    info "${backoff}s sonra yeniden denenecek..."
                    sleep "$backoff"
                fi
            done

            if [[ "$pull_success" != true ]]; then
                fail "Model indirilemedi: ${model} (3 deneme sonrası başarısız)."
            fi
        fi
    done

    run_coding_model_smoke_prompt "$CODE_MOD" "$OLLAMA_BASE_URL"
    ok "Gerekli tüm modeller başarıyla hazırlandı ve doğrulandı."
}

# ── 12. Alembic migrasyonları ────────────────────────────────────────────────
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
        DB_URL=$(read_env_value_from_file "DATABASE_URL" "$ENV_FILE")
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

    if [[ -z "$DB_URL" && -f "$ENV_FILE" ]]; then
        DB_URL=$("$ALEMBIC_PYTHON" - "$ENV_FILE" <<'PY'
from pathlib import Path
from urllib.parse import quote
import sys

env_path = Path(sys.argv[1])
values = {}
for raw_line in env_path.read_text(encoding="utf-8").splitlines():
    line = raw_line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    key, value = line.split("=", 1)
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1]
    values[key.strip()] = value

password = values.get("POSTGRES_PASSWORD", "")
if password:
    user = values.get("POSTGRES_USER") or "sidar"
    host = values.get("POSTGRES_HOST") or "127.0.0.1"
    port = values.get("POSTGRES_PORT") or "5432"
    database = values.get("POSTGRES_DB") or "sidar"
    print(
        "postgresql+asyncpg://"
        f"{quote(user, safe='')}:{quote(password, safe='')}"
        f"@{host}:{port}/{quote(database, safe='')}"
    )
PY
)
        if [[ -n "$DB_URL" ]]; then
            info "DATABASE_URL .env içinde kasıtlı olarak tek kaynak yaklaşımıyla tutulmuyor; migrasyon DSN'i POSTGRES_* parçalarından üretildi."
        fi
    fi

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

host = parsed.hostname or "127.0.0.1"
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
        if [[ -n "${POSTGRES_PASSWORD:-}" ]]; then
            DB_PASSWORD="$POSTGRES_PASSWORD"
        fi
        ensure_postgres_databases_exist "$DB_HOST" "$DB_PORT" "$DB_USER" "$DB_PASSWORD" "$DB_NAME"

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
        refreshed_db_url=$(read_env_value_from_file "DATABASE_URL" "$ENV_FILE")
        refreshed_postgres_password=$(read_env_value_from_file "POSTGRES_PASSWORD" "$ENV_FILE")

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

is_alembic_at_head() {
    local env_file="$SCRIPT_DIR/.env"
    local alembic_ini="$SCRIPT_DIR/alembic.ini"
    local py_bin=""
    local db_url=""
    local current_rev=""
    local head_rev=""

    [[ -f "$alembic_ini" ]] || return 1
    if command -v python3 &>/dev/null; then
        py_bin="python3"
    elif command -v python &>/dev/null; then
        py_bin="python"
    else
        return 1
    fi

    [[ -f "$env_file" ]] || return 1
    db_url="$(read_env_value_from_file "DATABASE_URL" "$env_file" | tr -d '\n')"
    [[ -n "${db_url//[[:space:]]/}" ]] || return 1

    current_rev="$(env "DATABASE_URL=$db_url" "$py_bin" -m alembic current 2>/dev/null | awk '/^[0-9a-f]+/ {print $1}' | tail -n1)"
    head_rev="$(env "DATABASE_URL=$db_url" "$py_bin" -m alembic heads 2>/dev/null | awk '/^[0-9a-f]+/ {print $1}' | tail -n1)"
    [[ -n "$current_rev" && -n "$head_rev" && "$current_rev" == "$head_rev" ]]
}

ensure_postgres_databases_exist() {
    local db_host="$1"
    local db_port="$2"
    local db_user="$3"
    local db_password="$4"
    local primary_db="$5"
    local -a required_dbs=("$primary_db" "sidar" "sidar_development" "sidar_test")
    local db_name=""
    local unique_dbs=""

    if ! command -v psql &>/dev/null; then
        warn "psql bulunamadı; veritabanı varlık kontrolü atlandı."
        return 0
    fi

    unique_dbs=$(printf "%s\n" "${required_dbs[@]}" | awk 'NF && !seen[$0]++')
    while IFS= read -r db_name; do
        [[ -n "$db_name" ]] || continue
        local psql_err_file
        psql_err_file="$(mktemp)"
        if ! PGPASSWORD="$db_password" psql -w \
            -h "$db_host" -p "$db_port" -U "$db_user" -d postgres \
            -tAc "SELECT 1 FROM pg_database WHERE datname = '${db_name}'" 2>"$psql_err_file" | grep -q '^1$'; then
            if grep -Eqi 'authentication|password' "$psql_err_file"; then
                rm -f "$psql_err_file"
                fail "PostgreSQL auth başarısız: .env POSTGRES_PASSWORD ile container parolası uyumsuz. Çözüm: docker compose down -v && yeniden kurulum."
            fi
            info "Eksik PostgreSQL veritabanı oluşturuluyor: ${db_name}"
            if ! PGPASSWORD="$db_password" psql -w \
                -h "$db_host" -p "$db_port" -U "$db_user" -d postgres \
                -v ON_ERROR_STOP=1 \
                -c "CREATE DATABASE \"${db_name}\" OWNER \"${db_user}\";" >/dev/null 2>>"$psql_err_file"; then
                if grep -Eqi 'authentication|password' "$psql_err_file"; then
                    rm -f "$psql_err_file"
                    fail "PostgreSQL auth başarısız: .env POSTGRES_PASSWORD ile container parolası uyumsuz. Çözüm: docker compose down -v && yeniden kurulum."
                fi
                rm -f "$psql_err_file"
                return 1
            fi
            ok "Veritabanı hazır: ${db_name}"
        fi
        rm -f "$psql_err_file"
    done <<<"$unique_dbs"
}


seed_rag_metadata_after_migrations() {
    local seed_mode="${AUTO_SEED_RAG_METADATA:-true}"
    seed_mode="$(normalize_bool "$seed_mode")"
    [[ -z "$seed_mode" ]] && seed_mode="true"

    if [[ "$seed_mode" != "true" ]]; then
        info "AUTO_SEED_RAG_METADATA=${AUTO_SEED_RAG_METADATA:-false}; RAG metadata seed adımı atlandı."
        return 0
    fi

    if [[ "${MIGRATION_STATUS:-}" != "tamamlandi" ]]; then
        info "Migrasyon tamamlanmadığı için RAG metadata seed adımı atlandı (MIGRATION_STATUS=${MIGRATION_STATUS:-bilinmiyor})."
        return 0
    fi

    if ! command -v uv &>/dev/null; then
        warn "uv bulunamadı; RAG metadata seed otomasyonu atlandı. Manuel: uv run python -m scripts.seed_rag --metadata-only"
        return 0
    fi

    if [[ ! -f "$SCRIPT_DIR/scripts/seed_rag.py" ]]; then
        warn "scripts/seed_rag.py bulunamadı; RAG metadata seed otomasyonu atlandı."
        return 0
    fi

    info "RAG/GraphRAG metadata başlangıç seed'i uygulanıyor..."
    if (cd "$SCRIPT_DIR" && uv run python -m scripts.seed_rag --metadata-only); then
        ok "RAG index ve GraphRAG entity metadata seed adımı tamamlandı."
    else
        warn "RAG metadata seed adımı başarısız; Doctor uyarılarını gidermek için manuel çalıştırın: uv run python -m scripts.seed_rag --metadata-only"
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
            info "WSL2 için öneri: $(wsl_integration_remediation_message "${WSL_DISTRO_NAME:-Ubuntu}")"
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
select_pytorch_cuda_wheel_tag() {
    local override_tag="${PYTORCH_CUDA_WHEEL_TAG:-}"
    local cuda_version="${CUDA_VERSION:-}"
    local compute_capability="${GPU_COMPUTE_CAPABILITY:-}"
    local gpu_name="${GPU_NAME:-}"
    local compute_major=""
    local cuda_major=""
    local cuda_minor=""

    if [[ -n "$override_tag" ]]; then
        echo "$override_tag"
        return 0
    fi

    compute_major="${compute_capability%%.*}"
    if [[ "$compute_major" =~ ^[0-9]+$ ]] && (( compute_major >= 12 )); then
        # Blackwell / RTX 50xx sınıfı GPU'lar CUDA 12.6+ wheel ister; cu128 tercih edilir.
        echo "cu128"
        return 0
    fi

    if [[ "$gpu_name" =~ (Blackwell|RTX[[:space:]]*50|RTX[[:space:]]*5[0-9]{3}) ]]; then
        echo "cu128"
        return 0
    fi

    cuda_major="${cuda_version%%.*}"
    cuda_minor="${cuda_version#*.}"
    cuda_minor="${cuda_minor%%.*}"
    if [[ "$cuda_major" =~ ^[0-9]+$ && "$cuda_minor" =~ ^[0-9]+$ ]]; then
        if (( cuda_major > 12 || (cuda_major == 12 && cuda_minor >= 8) )); then
            echo "cu128"
            return 0
        fi
        if (( cuda_major == 12 && cuda_minor >= 6 )); then
            echo "cu126"
            return 0
        fi
    fi

    echo "cu124"
}

sync_pytorch_cuda_wheels() {
    local cuda_tag="${1:-}"
    [[ -n "$cuda_tag" ]] || cuda_tag="$(select_pytorch_cuda_wheel_tag)"
    local index_url="${PYTORCH_CUDA_INDEX_URL:-https://download.pytorch.org/whl/${cuda_tag}}"
    local -a sync_args=(
        --frozen
        --all-extras
        --index "$index_url"
        --reinstall-package torch
        --reinstall-package torchvision
        --reinstall-package torchaudio
    )

    info "PyTorch CUDA wheel seçimi uv sync ile uygulanıyor: ${cuda_tag} (${index_url})"
    if ! uv sync "${sync_args[@]}"; then
        fail "PyTorch CUDA bağımlılıkları uv sync ile senkronlanamadı (${cuda_tag})."
    fi
}

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
            info "GPU wheel için PyTorch yeniden kuruluyor (GPU compute capability/CUDA sürümüne göre dinamik index seçilecek)..."
            sync_pytorch_cuda_wheels "$(select_pytorch_cuda_wheel_tag)"

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

    local env_file="$SCRIPT_DIR/.env"
    local smoke_database_url=""
    local smoke_postgres_password=""
    local smoke_redis_url=""
    if [[ -f "$env_file" ]]; then
        smoke_database_url=$(read_env_value_from_file "DATABASE_URL" "$env_file")
        smoke_postgres_password=$(read_env_value_from_file "POSTGRES_PASSWORD" "$env_file")
        smoke_redis_url=$(read_env_value_from_file "REDIS_URL" "$env_file")
        if [[ -z "$smoke_redis_url" ]]; then
            smoke_redis_url=$(read_env_value_from_file "SIDAR_REDIS_URL" "$env_file")
        fi

        if [[ -n "$smoke_database_url" ]]; then
            pytest_smoke_env+=("DATABASE_URL=$smoke_database_url")
            info "Smoke test DATABASE_URL değeri .env dosyasından yenilendi."
        fi
        if [[ -n "$smoke_postgres_password" ]]; then
            pytest_smoke_env+=("POSTGRES_PASSWORD=$smoke_postgres_password")
        fi
        if [[ -n "$smoke_redis_url" ]]; then
            pytest_smoke_env+=("REDIS_URL=$smoke_redis_url")
        fi
    fi

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
    local summary_banner=""
    summary_banner="$(_center_visible "Sidar AI Kurulumu Tamamlandı!" 60)"
    echo ""
    echo -e "${BOLD}${GREEN}"
    echo "╔══════════════════════════════════════════════════════════════╗"
    printf "║%s║\n" "$(_pad_visible "$summary_banner" 60)"
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
        echo "       Altyapı servisleri: docker compose up -d postgres redis jaeger prometheus grafana"
        echo "       (Host Ollama yoksa ayrıca: docker compose up -d ollama)"
        echo "       Durdurma: docker compose stop postgres redis jaeger prometheus grafana ollama"
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
        [[ -f "$SCRIPT_DIR/.env" ]] && multimodal_val=$(read_env_value_from_file "ENABLE_MULTIMODAL" "$SCRIPT_DIR/.env" | tr -d '[:space:]')
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
    local runtime_mode="${APP_RUNTIME_MODE_SELECTED:-${APP_RUNTIME_MODE:-docker}}"
    local -a infra_services=(postgres redis jaeger prometheus grafana)

    if command -v docker &>/dev/null && docker compose version &>/dev/null; then
        docker_compose_cmd=(docker compose)
    elif command -v docker-compose &>/dev/null; then
        docker_compose_cmd=(docker-compose)
    else
        warn "Sistemde Docker veya Docker Compose bulunamadı, servisler otomatik başlatılamıyor."
        return
    fi

    if [[ -f "$env_file" ]]; then
        compose_profiles=$(read_env_value_from_file "COMPOSE_PROFILES" "$env_file" | tr -d '[:space:]')
    fi
    if [[ -z "$compose_profiles" ]]; then
        if [[ "$GPU_AVAILABLE" == true ]]; then
            compose_profiles="gpu"
        else
            compose_profiles="cpu"
        fi
    fi

    if [[ "$runtime_mode" == "ask" ]]; then
        runtime_mode="docker"
        APP_RUNTIME_MODE="$runtime_mode"
        APP_RUNTIME_MODE_SELECTED="$runtime_mode"
        warn "Çalışma modu daha önce seçilmemiş; tekrar menü göstermeden varsayılan 'docker' kullanılacak."
    fi

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
                    info "$(wsl_integration_remediation_message "${WSL_DISTRO_NAME:-Ubuntu}")"
                fi
                info "Entegrasyon tamamlandıktan sonra manuel çalıştırın: COMPOSE_PROFILES=$compose_profiles ${docker_compose_cmd[*]} up -d"
                return
            fi

            info "Docker Compose servisleri başlatılıyor..."
            info "Monitoring konfigürasyon dosyaları için bind-mount sanity check çalıştırılıyor..."
            validate_monitoring_mount_paths
            if [[ "$runtime_mode" == "local" ]]; then
                info "Seçilen çalışma modu: local (uygulama local + altyapı Docker)"
                if ! check_host_ollama_healthy "$env_file"; then
                    infra_services+=(ollama)
                    info "Host Ollama bulunamadı veya healthy değil; Docker Ollama konteyneri kullanılacak."
                else
                    info "Host Ollama healthy tespit edildi; Docker Ollama konteyneri başlatılmayacak."
                    log_host_ollama_runtime_diagnostics "$env_file"
                fi
                if COMPOSE_PROFILES="$compose_profiles" "${docker_compose_cmd[@]}" up -d "${infra_services[@]}"; then
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

# ── Çalışma Modu Seçimi ─────────────────────────────────────────────────────
select_runtime_mode() {
    local runtime_mode="${APP_RUNTIME_MODE:-ask}"
    local runtime_answer=""

    if [[ "$runtime_mode" == "ask" ]]; then
        if [[ "$NO_INTERACTION" == true ]]; then
            runtime_mode="docker"
            info "--ci/--no-interaction etkin: çalışma modu varsayılanı 'docker' seçildi."
        else
            echo ""
            info "Çalışma modu seçimi:"
            echo "  1) Geliştirici modu (önerilen): uygulama local, altyapı servisleri Docker"
            echo "  2) Tam Docker modu: web/agent dahil tüm servisler Docker"
            clear_stdin_buffer
            if read -r -t "$SIDAR_PROMPT_TIMEOUT" -p "Seçim [1/2, varsayılan=1]: " runtime_answer 2>/dev/tty; then
                :
            else
                warn "${SIDAR_PROMPT_TIMEOUT} saniye içinde seçim yapılmadı. Varsayılan seçim: 1 (geliştirici modu)."
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

    if SIDAR_CONFIG_QUIET=1 "${doctor_cmd[@]}"; then
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
    select_runtime_mode
    detect_gpu
    setup_nvidia_docker
    create_directories
    setup_env_file
    ok "prepare-system fazı tamamlandı."
}

run_sync_deps_phase() {
    cd "$SCRIPT_DIR"
    ensure_prerequisites
    select_runtime_mode
    detect_gpu
    install_uv_cli
    create_uv_venv
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
    seed_rag_metadata_after_migrations
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
    sidar_run_install_phase "01_context" sidar_phase_initialize_context
    if sidar_phase_handle_early_exit; then
        return
    fi

    sidar_run_install_phase "02_repo" sidar_phase_bootstrap_repo_system
    sidar_run_install_phase "03_runtime" sidar_phase_runtime_prerequisites
    sidar_run_install_phase "04_workspace" sidar_phase_workspace_config
    sidar_run_install_phase "05_frontend" sidar_phase_frontend_assets
    sidar_run_install_phase "06_models" sidar_phase_local_migrations_and_models
    sidar_run_install_phase "06_services" sidar_phase_services_and_validation
    sidar_run_install_phase "07_finish" sidar_phase_finish
}

if [[ "${SIDAR_INSTALL_TEST_MODE:-0}" != "1" ]]; then
    main "$@"
fi
