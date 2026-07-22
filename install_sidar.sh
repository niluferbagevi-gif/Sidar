#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════════
# Sidar AI — Kurulum Betiği (install_sidar.sh)
# Sürüm : pyproject.toml / sidar_version.py üzerinden otomatik çözülür
# Hedef : WSL2 / Ubuntu / uv venv + NVIDIA RTX GPU ailesi (PyTorch CUDA wheel dinamik seçilir)
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
#   ./install_sidar.sh --production-readiness  # production öncesi tam CI/e2e/benchmark doğrulaması
#   AUTO_INSTALL=true INSTALL_MODE=1 ENV_TYPE=dev RESET_DB=yes START_DOCKER_SERVICES=yes OPEN_VSCODE=no ./install_sidar.sh
# ═══════════════════════════════════════════════════════════════════════════════
set -Eeuo pipefail

# Tek ERR trap handler'ı: sidar_t/warn/LOG_FILE gibi loglama yardımcıları
# script'in ilerleyen satırlarına (~300+) kadar tanımlı değildir, bu yüzden
# bootstrap aşamasında (örn. probe-only fast-path) bu fonksiyonlar henüz
# yokken çağrılmamaları için önce varlıkları kontrol edilir.
on_install_error() {
    local exit_code=$?
    local failed_line="${1:-unknown}"
    local failed_cmd="${2:-unknown}"

    if ! declare -F sidar_t >/dev/null 2>&1; then
        echo "install_sidar.sh: satır=${failed_line} cmd=${failed_cmd} exit=${exit_code}" >&2
        exit "$exit_code"
    fi

    local remediation_reason="${SIDAR_LAST_FAIL_MESSAGE:-ERR trap}"

    if declare -F sidar_handle_install_failure >/dev/null 2>&1; then
        sidar_handle_install_failure "$exit_code" "$failed_line" "$failed_cmd" "$remediation_reason" || true
    fi
    echo "❌ $(sidar_t install_failed "$failed_line" "$exit_code")" >&2
    sidar_t failed_command "$failed_cmd" >&2
    sidar_t check_log "$LOG_FILE" >&2
    exit "$exit_code"
}

trap 'on_install_error "$LINENO" "$BASH_COMMAND"' ERR

# Güvenlik/operasyon guard: root ile çalıştırılan kurulum .venv sahipliğini bozup
# sonraki uv run çağrılarında Permission denied zinciri üretebilir.
if [[ "${EUID:-$(id -u)}" -eq 0 && "${SIDAR_INSTALL_TEST_MODE:-0}" != "1" ]]; then
    echo "❌ Bu betik root/sudo ile çalıştırılamaz. Normal kullanıcı ile çalıştırın: ./install_sidar.sh" >&2
    if [[ -n "${SUDO_USER:-}" ]]; then
        echo "ℹ️ Tespit edilen normal kullanıcı: ${SUDO_USER}. Dizin sahipliği bozulduysa düzeltme:" >&2
        guard_script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
        printf '   sudo chown -R %s:%s %q\n' "$SUDO_USER" "$SUDO_USER" "${guard_script_dir}/.venv" >&2
    else
        guard_script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
        echo "ℹ️ Root oturumundan çıkıp normal kullanıcı hesabınızla tekrar çalıştırın." >&2
        echo "ℹ️ Eğer root altında çalıştırma sonrası sahiplik bozulduysa normal kullanıcı adınızla şu komutu uygulayın:" >&2
        printf '   sudo chown -R <normal-kullanıcı>:<normal-kullanıcı> %q\n' "${guard_script_dir}/.venv" >&2
    fi
    exit 1
fi

# Uzak script indirmelerinde checksum yoksa güvenlik gereği varsayılan olarak reddet
export ALLOW_UNVERIFIED_REMOTE_SCRIPTS="${ALLOW_UNVERIFIED_REMOTE_SCRIPTS:-0}"

# Resume/auto-heal modunda GPU tespit fazı atlanabilir. Strict mode altında
# sonraki servis/smoke/özet fazlarının unbound variable ile kırılmaması için
# küresel GPU bayrağını en erken noktada güvenli CPU fallback'iyle tanımla.
export GPU_AVAILABLE="${GPU_AVAILABLE:-false}"

# Ultra fast-path: smoke/version probe akışı sadece INSTALL_SIDAR_VERSION
# export'unu doğrular. WSL2 + Defender gibi yavaş fork() ortamlarında bu probe'un
# helper source, checksum yükleme, manifest parse veya log fan-out aşamalarına
# girmesi kurulum smoke gate'ini dakikalarca kilitleyebilir. Bu nedenle probe-only
# modunu en üstte, yalnız Bash built-in'leriyle pyproject.toml okuyarak bitir.
if [[ "${SIDAR_INSTALL_VERSION_PROBE_ONLY:-0}" == "1" ]]; then
    _sidar_probe_source="${BASH_SOURCE[0]}"
    if [[ "$_sidar_probe_source" == */* ]]; then
        _sidar_probe_dir="${_sidar_probe_source%/*}"
        [[ "$_sidar_probe_dir" == /* ]] || _sidar_probe_dir="${PWD}/${_sidar_probe_dir}"
    else
        _sidar_probe_dir="${PWD}"
    fi

    _sidar_probe_requested_version="${INSTALL_SIDAR_VERSION:-}"
    _sidar_probe_pyproject_version=""
    if [[ -f "${_sidar_probe_dir}/pyproject.toml" ]]; then
        while IFS= read -r _sidar_probe_line; do
            if [[ "$_sidar_probe_line" =~ ^[[:space:]]*version[[:space:]]*=[[:space:]]*\"([^\"]+)\" ]]; then
                _sidar_probe_pyproject_version="${BASH_REMATCH[1]}"
                break
            fi
        done < "${_sidar_probe_dir}/pyproject.toml"
    fi
    if [[ -n "$_sidar_probe_requested_version" && -n "$_sidar_probe_pyproject_version" && "$_sidar_probe_requested_version" != "$_sidar_probe_pyproject_version" ]]; then
        echo "❌ INSTALL_SIDAR_VERSION uyumsuz: ortam=${_sidar_probe_requested_version}, pyproject.toml=${_sidar_probe_pyproject_version}. Smoke/version probe için pyproject.toml tek doğruluk kaynağıdır." >&2
        unset _sidar_probe_source _sidar_probe_dir _sidar_probe_line _sidar_probe_requested_version _sidar_probe_pyproject_version
        trap - ERR
        return 1 2>/dev/null || exit 1
    fi
    INSTALL_SIDAR_VERSION="${_sidar_probe_pyproject_version:-${_sidar_probe_requested_version:-}}"
    if [[ -z "$INSTALL_SIDAR_VERSION" ]]; then
        INSTALL_SIDAR_VERSION="0.0.0"
    fi
    export INSTALL_SIDAR_VERSION
    unset _sidar_probe_source _sidar_probe_dir _sidar_probe_line _sidar_probe_requested_version _sidar_probe_pyproject_version
    trap - ERR
    return 0 2>/dev/null || exit 0
fi

# GitHub Codespaces overlay dosya sisteminde uv hardlink uyarılarını ve gereksiz
# full-copy fallback denemelerini önlemek için copy modu varsayılanlaştırılır.
if [[ -z "${UV_LINK_MODE:-}" && ( "${CODESPACES:-}" == "true" || "${GITHUB_CODESPACES:-}" == "true" ) ]]; then
    export UV_LINK_MODE=copy
fi

# Sidar'ın kendi ürettiği/yönettiği dahili secret'lar (kullanıcının interaktif
# API key toplama akışının parçası değildir, bu yüzden aşağıdaki kullanıcı
# secret listesinden ayrı tutulur).
SIDAR_INTERNAL_SECRET_ENV_KEYS=(
    DATABASE_URL SIDAR_CONTAINER_DATABASE_URL SELF_HEAL_DATABASE_URL
    TEST_DATABASE_URL LOCAL_DEV_FALLBACK_DATABASE_URL POSTGRES_PASSWORD
    API_KEY JWT_SECRET_KEY MEMORY_ENCRYPTION_KEY AUTONOMY_WEBHOOK_SECRET
    SWARM_FEDERATION_SHARED_SECRET GITHUB_WEBHOOK_SECRET GRAFANA_ADMIN_PASSWORD
    METRICS_TOKEN SIDAR_REDIS_URL REDIS_URL RABBITMQ_URL SIDAR_RABBITMQ_URL
)

# Kullanıcının interaktif olarak sağladığı API key/secret adlarının TEK
# doğruluk kaynağı. scripts/install_modules/phases/08_env.sh içindeki
# sidar_user_api_key_names() bu diziyi olduğu gibi döndürür; aşağıdaki log
# maskeleme deseni de aynı diziyi kullanır. Yeni bir kullanıcı API
# key'i/secret'ı eklerken SADECE bu diziyi güncelleyin — iki ayrı allowlist'i
# elle senkron tutmaya çalışmayın (bu, önceden GITHUB_TOKEN, SLACK_TOKEN,
# TAVILY_API_KEY, HF_TOKEN, JIRA_TOKEN gibi değerlerin log maskelemesinden
# sessizce dışarıda kalmasına yol açan tam da bu sınıf bir bug'dı).
SIDAR_USER_SECRET_ENV_KEYS=(
    OPENAI_API_KEY GEMINI_API_KEY ANTHROPIC_API_KEY LITELLM_API_KEY HF_TOKEN
    GITHUB_TOKEN
    TAVILY_API_KEY GOOGLE_SEARCH_API_KEY GOOGLE_SEARCH_CX
    SLACK_TOKEN SLACK_APP_LEVEL_TOKEN SLACK_WEBHOOK_URL SLACK_DEFAULT_CHANNEL
    JIRA_URL JIRA_EMAIL JIRA_TOKEN JIRA_DEFAULT_PROJECT
    TEAMS_WEBHOOK_URL
)

# Kurulum loglarını eşzamanlı olarak terminale ve dosyaya yaz.
# Filtre önce terminal/log fan-out'una girer; böylece set -x, sed hata çıktısı
# veya beklenmeyen tool çıktıları DATABASE_URL/parola/token değerlerini hem
# terminalden hem de kalıcı log dosyasından maskeler.
mask_install_log_stream() {
    local masked_keys_pattern
    masked_keys_pattern="$(
        IFS='|'
        printf '%s' "${SIDAR_INTERNAL_SECRET_ENV_KEYS[*]}|${SIDAR_USER_SECRET_ENV_KEYS[*]}"
    )"
    sed -u -E \
        -e 's#((postgresql|postgres|mysql|mariadb)(\+[^:/@[:space:]]+)?://[^:/@[:space:]]+:)[^@[:space:]]+@#\1****@#g' \
        -e 's#((redis|rediss|amqp|amqps|mongodb|mongodb\+srv)://[^:/@[:space:]]+:)[^@[:space:]]+@#\1****@#g' \
        -e "s#((${masked_keys_pattern})=)[^[:space:]\";]+#\1****#g" \
        -e 's#((generated_password|safe_db_url|container_db_url|db_password|db_url|api_key|memory_key|grafana_password|pg_password)=)[^[:space:]";]+#\1****#gi' \
        -e "s#(\"(${masked_keys_pattern})\"[[:space:]]*:[[:space:]]*\")[^\"]*\"#\1****\"#g" \
        -e 's#((Authorization|X-API-Key|X-Auth-Token):[[:space:]]*)(Bearer[[:space:]]+)?[^[:space:]]+#\1\3****#gi'
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

load_remote_script_checksums() {
    local checksum_file="${SIDAR_REMOTE_CHECKSUMS_FILE:-${SCRIPT_DIR}/scripts/install_modules/remote_checksums.env}"
    if [[ -f "$checksum_file" ]]; then
        # shellcheck source=/dev/null
        # shellcheck disable=SC1090
        source "$checksum_file"
        printf 'ℹ️   Uzak kurulum betiği checksum varsayılanları yüklendi: %s\n' "$checksum_file" >&2
    fi
}

load_remote_script_checksums

SIDAR_INSTALLER_EMBEDDED_SOURCE_REF="main"
SIDAR_INSTALLER_EMBEDDED_SOURCE_COMMIT="0014bb247291f7d96c9db779759a7e247bf39cdb"

sidar_truthy_early_bool() {
    local raw="${1:-}"
    raw="${raw,,}"
    raw="${raw//[[:space:]]/}"
    case "$raw" in
        1|true|yes|y|evet|e) return 0 ;;
        *) return 1 ;;
    esac
}

sidar_detect_early_offline_mode() {
    local early_arg=""
    for early_arg in "$@"; do
        case "$early_arg" in
            --offline|--air-gapped)
                OFFLINE_MODE=true
                export OFFLINE_MODE
                return 0
                ;;
        esac
    done

    if sidar_truthy_early_bool "${OFFLINE_INSTALL:-}" || sidar_truthy_early_bool "${AIR_GAPPED_INSTALL:-}"; then
        OFFLINE_MODE=true
        export OFFLINE_MODE
        return 0
    fi

    OFFLINE_MODE="${OFFLINE_MODE:-false}"
    export OFFLINE_MODE
    return 1
}

sidar_detect_early_offline_mode "$@" || true

if ! declare -F compute_sha256 >/dev/null 2>&1; then
    compute_sha256() {
        local file_path="$1"
        if command -v sha256sum >/dev/null 2>&1; then
            sha256sum "$file_path" | awk '{print $1}'
            return 0
        fi
        if command -v shasum >/dev/null 2>&1; then
            shasum -a 256 "$file_path" | awk '{print $1}'
            return 0
        fi
        return 1
    }
fi

verify_core_install_manifest() {
    local manifest_path="${SCRIPT_DIR}/.sidar_manifest.txt"
    local required_files=(
        "core/memory.py"
        "core/multimodal.py"
    )
    local rel_path=""

    for rel_path in "${required_files[@]}"; do
        if [[ ! -f "${SCRIPT_DIR}/${rel_path}" ]]; then
            info "Çekirdek dosya eksik (${rel_path}); bootstrap/repo senkronizasyonu tamamlandıktan sonra hash doğrulaması çalıştırılacak."
            return 2
        fi
    done

    cat <<'SIDAR_INSTALL_MANIFEST_EOF' > "$manifest_path"
32bb465e8344f235b5d50b76498466415dda43b03d7e40fa7014aa3d38847e63  core/memory.py
8da261301210fbeba7d5d55cff37200342d1661cf6aaa52b43c79295ce56ee46  core/multimodal.py
SIDAR_INSTALL_MANIFEST_EOF

    if (cd "$SCRIPT_DIR" && sha256sum -c "$manifest_path" --status); then
        ok "Çekirdek kurulum manifest hash doğrulaması başarılı."
        return 0
    fi

    local expected=""
    local actual=""
    local target=""
    local failures=0
    local -a mismatched_files=()
    local mismatch_details=""

    while IFS=' ' read -r expected rel_path; do
        [[ -n "${expected:-}" && -n "${rel_path:-}" ]] || continue
        target="${SCRIPT_DIR}/${rel_path}"
        if [[ ! -f "$target" ]]; then
            warn "Çekirdek manifest hash doğrulama atlandı (dosya yok): ${rel_path}"
            failures=$((failures + 1))
            mismatched_files+=("${rel_path} (eksik dosya)")
            mismatch_details+=$'\n'"  • ${rel_path}"$'\n'"    Beklenen: ${expected}"$'\n'"    Mevcut:   <dosya-yok>"
            continue
        fi
        actual="$(compute_sha256 "$target" 2>/dev/null || echo "<sha256-hesaplanamadı>")"
        if [[ "$actual" != "$expected" ]]; then
            warn "Çekirdek manifest hash uyuşmazlığı: ${rel_path} (beklenen=${expected}, mevcut=${actual})"
            failures=$((failures + 1))
            mismatched_files+=("${rel_path}")
            mismatch_details+=$'\n'"  • ${rel_path}"$'\n'"    Beklenen: ${expected}"$'\n'"    Mevcut:   ${actual}"
        fi
    done < <(awk 'NF>=2 && $1 !~ /^#/ {print $1, $2}' "$manifest_path")

    local mismatched_csv=""
    if (( ${#mismatched_files[@]} > 0 )); then
        local _ifs_old="$IFS"
        IFS=', '
        mismatched_csv="${mismatched_files[*]}"
        IFS="$_ifs_old"
    fi
    [[ -n "$mismatch_details" ]] || mismatch_details=$'\n  • bilinmiyor'

    local bootstrap_context=""
    local git_head="bilinmiyor"
    local git_branch="bilinmiyor"
    local git_remote="bilinmiyor"
    if command -v git >/dev/null 2>&1 && [[ -d "${SCRIPT_DIR}/.git" ]]; then
        git_head="$(git -C "$SCRIPT_DIR" rev-parse HEAD 2>/dev/null || echo bilinmiyor)"
        git_branch="$(git -C "$SCRIPT_DIR" rev-parse --abbrev-ref HEAD 2>/dev/null || echo bilinmiyor)"
        git_remote="$(git -C "$SCRIPT_DIR" remote get-url origin 2>/dev/null || echo bilinmiyor)"
    fi

    if [[ -n "${SIDAR_BOOTSTRAP_REEXEC_TARGET:-}" ]]; then
        bootstrap_context="
Bootstrap durumu:
  • Clone/re-exec tamamlandı: ${SIDAR_BOOTSTRAP_REEXEC_TARGET}
  • Ref: ${SIDAR_BOOTSTRAP_REEXEC_REF:-bilinmiyor}
  • Clone HEAD: ${SIDAR_BOOTSTRAP_REEXEC_HEAD:-${git_head}}
  • Clone remote: ${SIDAR_BOOTSTRAP_REEXEC_REMOTE:-${git_remote}}
  • Raw installer metadata: ref=${SIDAR_BOOTSTRAP_RAW_INSTALLER_SOURCE_REF:-${SIDAR_INSTALLER_EMBEDDED_SOURCE_REF}}, commit=${SIDAR_BOOTSTRAP_RAW_INSTALLER_SOURCE_COMMIT:-${SIDAR_INSTALLER_EMBEDDED_SOURCE_COMMIT}}
  • Raw installer SHA256: ${SIDAR_BOOTSTRAP_ORIGINAL_INSTALLER_SHA256:-bilinmiyor}
  • Clone install_sidar.sh SHA256: ${SIDAR_BOOTSTRAP_CLONED_INSTALLER_SHA256:-bilinmiyor}
  • Raw/clone installer ilişkisi: ${SIDAR_BOOTSTRAP_INSTALLER_SHA_RELATION:-bilinmiyor}
  • Bu aşama wget/chmod/git clone veya helper modül yükleme hatası değildir;
    hata clone sonrası çekirdek manifest karşılaştırmasında oluştu.
"
    fi

    fail "Güvenlik ihlali: çekirdek kurulum dosyaları hash doğrulamasını geçemedi (${failures} hata).

Bu hata kurulum modül manifestinden (scripts/install_modules) değil, çekirdek
kurulum manifestinden gelir. Doğrulanan çekirdek dosyalar:
  • core/memory.py
  • core/multimodal.py

Uyumsuz çekirdek dosyalar: ${mismatched_csv:-bilinmiyor}

Uyumsuz çekirdek dosya detayları:${mismatch_details}

Repo durumu:
  • Repo: ${git_remote}
  • Branch: ${git_branch}
  • HEAD: ${git_head}
${bootstrap_context}

Çözüm:
  1) Repo'da scripts/sync_install_manifest.sh çalıştırıp .sidar_manifest.txt ve
     install_sidar.sh içindeki SIDAR_INSTALL_MANIFEST_EOF bloğunu güncelleyin.
  2) Değişikliği commit/PR ile main dalına taşıyın; kullanıcı kurulumu ancak
     çekirdek manifest repo içeriğiyle senkron olduğunda devam eder.

Bu hata genellikle core dosyası değiştiği halde çekirdek manifestin
güncellenmediği anlamına gelir. Geliştirici çözümü:
  scripts/sync_install_manifest.sh

Kurulum güvenlik nedeniyle durduruldu.

Not: ALLOW_UNVERIFIED_REMOTE_SCRIPTS yalnız kurulum modülleri için geçici/test
bypass mekanizmasıdır; çekirdek dosya manifesti için bypass uygulanmaz."
}

# Resume çağrılarında önceki çalışma dizinini koru (örn. one-shot fetch sonrası
# 02_repo/03_runtime fazları atlandığında relative yolların sapmaması için).
if [[ -n "${SIDAR_INSTALL_RESUME_CWD:-}" && -d "${SIDAR_INSTALL_RESUME_CWD}" ]]; then
    cd "${SIDAR_INSTALL_RESUME_CWD}"
fi
if [[ "${SIDAR_INSTALL_VERSION_PROBE_ONLY:-0}" != "1" ]]; then
    # WSL integration autofix sentinel should not leak across reinstall attempts.
    rm -f "${TMPDIR:-/tmp}/sidar_wsl_integration_applied" 2>/dev/null || true
    ORIGINAL_SCRIPT_PATH="$(readlink -f "${BASH_SOURCE[0]}")"
    # shellcheck disable=SC2034  # scripts/install_modules/{phases/08_env.sh,phases/11_post_install.sh,install_helpers.sh} read this sourced state.
    ORIGINAL_SCRIPT_DIR="$SCRIPT_DIR"
fi
# shellcheck disable=SC2034  # consumed by install_remediation.sh after it is sourced.
SIDAR_INSTALL_ORIGINAL_ARGS=("$@")
# Not: Repo clone/sync tamamlanmadan TARGET_DIR altında dosya üretmeyin.
# Aksi halde "sıfır kurulum" akışında hedef dizin gereksiz yere dolu görünebilir.
LOG_DIR="$SCRIPT_DIR/logs"
if [[ "${SIDAR_INSTALL_TEST_MODE:-0}" != "1" ]]; then
    if ! mkdir -p "$LOG_DIR" 2>/dev/null; then
        LOG_DIR="${TMPDIR:-/tmp}"
        printf '⚠️  Log dizini oluşturulamıyor, geçici olarak %s kullanılacak.\n' "$LOG_DIR" >&2
        mkdir -p "$LOG_DIR" 2>/dev/null || true
    elif [[ -d "$LOG_DIR" && ! -w "$LOG_DIR" ]]; then
        LOG_DIR="${TMPDIR:-/tmp}"
        printf '⚠️  Log dizini yazılamıyor, geçici olarak %s kullanılacak.\n' "$LOG_DIR" >&2
        mkdir -p "$LOG_DIR" 2>/dev/null || true
    fi
    LOG_FILE="$LOG_DIR/install_$(date -u +%Y-%m-%dT%H%M%SZ).log"
    exec > >(mask_install_log_stream | tee -i >(sed -u -E $'s/\x1B\\[[0-9;]*[[:alpha:]]//g' > "$LOG_FILE")) 2>&1
else
    LOG_FILE=""
fi

# ── Renkler + i18n ────────────────────────────────────────────────────────────
RED=$'\033[0;31m'; GREEN=$'\033[0;32m'; YELLOW=$'\033[1;33m'
BLUE=$'\033[0;34m'; BOLD=$'\033[1m'; NC=$'\033[0m'

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
            invalid_arg)
                printf '%s\n%s\n%s\n%s\n%s\n%s\n%s\n%s\n%s' \
                    "Unknown argument: $1." \
                    'Accepted values:' \
                    '  Commands: doctor | prepare-system | sync-deps | provision-models | smoke' \
                    '  Core flags: --upgrade-lock | --i-understand-full-access | --cpu | --docker-only | --runtime-mode=local|docker | --silent | --auto' \
                    '  Environment: --mode=... | --env=... | --reset-db | --no-reset-db | --start-services | --no-start-services | --vscode | --no-vscode' \
                    '  Assets/offline: --with-browsers | --skip-browsers | --offline | --air-gapped | --install-docker-cli | --skip-docker-cli' \
                    '  Cleanup/Kubernetes: --force-postgres-volume-cleanup | --force-docker-cleanup | --kubernetes | --helm | --helm-release=... | --namespace=... | --values=...' \
                    '  Tests/automation: --smoke-test | --skip-smoke-test | --with-integration | --ci-full | --production-readiness | --enable-autonomous-cron | --audit' \
                    '  Models/UI/audio: --skip-models | --download-models | --build-ui | --enable-audio'
                printf '\n%s' '  Non-interactive: --ci | --no-interaction | --non-interactive | --headless | --yes | -y'
                ;;
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
            invalid_arg)
                printf '%s\n%s\n%s\n%s\n%s\n%s\n%s\n%s\n%s' \
                    "Bilinmeyen argüman: $1." \
                    'Kabul edilen değerler:' \
                    '  Komutlar: doctor | prepare-system | sync-deps | provision-models | smoke' \
                    '  Temel bayraklar: --upgrade-lock | --i-understand-full-access | --cpu | --docker-only | --runtime-mode=local|docker | --silent | --auto' \
                    '  Ortam: --mode=... | --env=... | --reset-db | --no-reset-db | --start-services | --no-start-services | --vscode | --no-vscode' \
                    '  Varlık/offline: --with-browsers | --skip-browsers | --offline | --air-gapped | --install-docker-cli | --skip-docker-cli' \
                    '  Temizlik/Kubernetes: --force-postgres-volume-cleanup | --force-docker-cleanup | --kubernetes | --helm | --helm-release=... | --namespace=... | --values=...' \
                    '  Test/otomasyon: --smoke-test | --skip-smoke-test | --with-integration | --ci-full | --production-readiness | --enable-autonomous-cron | --audit' \
                    '  Model/UI/ses: --skip-models | --download-models | --build-ui | --enable-audio'
                printf '\n%s' '  Etkileşimsiz: --ci | --no-interaction | --non-interactive | --headless | --yes | -y'
                ;;
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

ok()   { printf '%s\n' "${GREEN}✅  $*${NC}" >&2; }
info() { printf '%s\n' "${BLUE}ℹ️   $*${NC}" >&2; }
debug() {
    [[ "${SIDAR_DEBUG:-0}" == "1" || "${SIDAR_VERBOSE:-0}" == "1" ]] || return 0
    printf '%s\n' "${BLUE}🔍  $*${NC}" >&2
}
warn() { printf '%s\n' "${YELLOW}⚠️   $*${NC}" >&2; }
fail() {
    local fail_reason="$*"
    SIDAR_LAST_FAIL_MESSAGE="$fail_reason"
    export SIDAR_LAST_FAIL_MESSAGE
    printf '%s\n' "${RED}❌  ${fail_reason}${NC}" >&2
    if declare -F sidar_handle_install_failure >/dev/null 2>&1; then
        sidar_handle_install_failure 1 "${BASH_LINENO[0]:-unknown}" "fail" "$fail_reason" || true
    fi
    exit 1
}
step() { printf '\n%s\n' "${BOLD}${BLUE}── $* ──${NC}" >&2; }

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
# shellcheck disable=SC2034  # External probes/operators may read the plural alias after sourcing the installer.
INSTALL_MODULES_DIR="$INSTALL_MODULE_DIR"
INSTALL_HELPERS_MODULE="${INSTALL_MODULE_DIR}/install_helpers.sh"
INSTALL_HELPERS_TEMP_DIR=""
INSTALL_MODULES_DOWNLOADED=0
SIDAR_INSTALL_MODULE_DOWNLOAD_RETRIES="${SIDAR_INSTALL_MODULE_DOWNLOAD_RETRIES:-5}"
SIDAR_INSTALL_MODULE_RETRY_DELAY="${SIDAR_INSTALL_MODULE_RETRY_DELAY:-2}"
SIDAR_INSTALL_MODULE_CONNECT_TIMEOUT="${SIDAR_INSTALL_MODULE_CONNECT_TIMEOUT:-15}"
SIDAR_INSTALL_MODULE_MAX_TIME="${SIDAR_INSTALL_MODULE_MAX_TIME:-120}"
SIDAR_INSTALL_MODULE_CACHE_ROOT="${SIDAR_INSTALL_MODULE_CACHE_ROOT:-}"
SIDAR_INSTALL_MODULE_CACHE_ROOT_AUTO=0
SIDAR_INSTALL_MODULE_CACHE_CLEANUP_DAYS="${SIDAR_INSTALL_MODULE_CACHE_CLEANUP_DAYS:-7}"
export SIDAR_INSTALLER_BOOTSTRAP_MODE="${SIDAR_INSTALLER_BOOTSTRAP_MODE:-unknown}"
export SIDAR_INSTALL_MODULES_DOWNLOADED_COUNT="${SIDAR_INSTALL_MODULES_DOWNLOADED_COUNT:-0}"
export SIDAR_INSTALL_MODULE_DOWNLOAD_ATTEMPTS="${SIDAR_INSTALL_MODULE_DOWNLOAD_ATTEMPTS:-0}"
export SIDAR_INSTALL_MODULE_HTTP_429_RETRIES="${SIDAR_INSTALL_MODULE_HTTP_429_RETRIES:-0}"
export SIDAR_INSTALL_MODULE_CACHE_HITS="${SIDAR_INSTALL_MODULE_CACHE_HITS:-0}"

sidar_set_install_module_dir() {
    INSTALL_MODULE_DIR="$1"
    # INSTALL_MODULE_DIR is the historical internal variable. Keep the plural
    # alias in sync because operator notes and external probes often refer to
    # the tree as INSTALL_MODULES_DIR.
    # shellcheck disable=SC2034  # External probes/operators may read the plural alias after sourcing the installer.
    INSTALL_MODULES_DIR="$INSTALL_MODULE_DIR"
    INSTALL_HELPERS_MODULE="${INSTALL_MODULE_DIR}/install_helpers.sh"
}

INSTALL_UTILITY_MODULES=(
    "utils/install_remediation.sh"
    "utils/ux.sh"
    "utils/wsl_integration_autofix.sh"
    "utils/wsl_gpu_preflight.sh"
    "utils/wsl_host.sh"
    "utils/gpu_utils.sh"
    "utils/installer_hash_guard.sh"
    "utils/remote_script.sh"
    "utils/python_env.sh"
    "utils/database_url.sh"
    "utils/db_credentials.sh"
    "utils/env_utils.sh"
    "utils/env_secrets.sh"
    "utils/services_docker.sh"
    "utils/ollama_models.sh"
    "utils/playwright_ubuntu_override.sh"
)

INSTALL_PHASE_MODULES=(
    "phases/01_context.sh"
    "phases/02_repo.sh"
    "phases/03_system.sh"
    "phases/03_runtime_ollama.sh"
    "phases/03_runtime.sh"
    "phases/04_workspace.sh"
    "phases/14_react.sh"
    "phases/05_frontend.sh"
    "phases/08_env.sh"
    "phases/09_ollama_models.sh"
    "phases/10_validation.sh"
    "phases/11_post_install.sh"
    "phases/13_playwright.sh"
    "phases/12_alembic.sh"
    "phases/06_services.sh"
    "phases/07_finish.sh"
)

INSTALL_REMOTE_MODULES=(
    "install_helpers.sh"
    "install_cli.sh"
    "install_dispatcher.sh"
    "${INSTALL_UTILITY_MODULES[@]}"
    "utils/wsl_integration_autofix.ps1"
    "${INSTALL_PHASE_MODULES[@]}"
)

# Bundle üretiminde scripts/tools/bundle_install_sidar.sh bu bloğu doldurur.
# Repo çalışma ağacında varsayılan olarak boş bırakılır.
read -r -d '' EMBEDDED_MODULE_HASHES_MANIFEST <<'SIDAR_MODULE_HASHES_EOF' || true
776d8636ceaaac819415f73939f8e55fe101f8940c2500d731700a6b83c92a64  scripts/install_modules/install_cli.sh
da28d54a68a4d2d30ff539cd8d0435265fe87000e24727505b312fee79e33603  scripts/install_modules/install_dispatcher.sh
1b2321633b1385cee8640917c3f2bed925d8626f49dce8b3fe9c7b9d484c331b  scripts/install_modules/install_helpers.sh
2e70edd087a296d4175c429cc12f1d961e4fece46c6c83bcc80a94e4e6db359b  scripts/install_modules/phases/01_context.sh
07a95b338f6b2a6f304811ed9442ce04a65936742cecd92560577450f8997289  scripts/install_modules/phases/02_repo.sh
41d198205629671a12d3d9de44e3ca0a597447c00eb2b93feab40c7a0add98df  scripts/install_modules/phases/03_runtime.sh
36d89771aece3334013906d55be48ee2d7a357490688e4562fd76684a7523702  scripts/install_modules/phases/03_runtime_ollama.sh
e7f820d4b649b87dca61f4fab70177917e65ba41c0f78d6ee7d82c185d82fafb  scripts/install_modules/phases/03_system.sh
4ef61725d2c0cf92088b4002e03f36e15354477a37c88fac5f8771a79a5f3e97  scripts/install_modules/phases/04_workspace.sh
6beadb2761652016b9d7c4de0d35b53b11837ceb16164c9b31ecd84e5f67f816  scripts/install_modules/phases/05_frontend.sh
2e0fc43c0f177da51d1252e3da257025df9f5ce476f0f16324af3fbb0fb38d87  scripts/install_modules/phases/06_services.sh
1d15811d323818d868d273f719178a04e37ad953c76e4ab62b08dd7bac59645c  scripts/install_modules/phases/07_finish.sh
faaf13c54e5e4abe630371cfeb2ec3e027174ba795f038f80775a5434e50c362  scripts/install_modules/phases/08_env.sh
3c5dbf7687703bcef6e0af4a2acd172b0634fe1ae68718e8894bc9781fd23672  scripts/install_modules/phases/09_ollama_models.sh
03d9297bf0326f953e2b036a496d181be3868c7cd1afdebfb1f8a8bac104581a  scripts/install_modules/phases/10_validation.sh
d75380e5a3cf44b35f6fc894a41c774a1e3afd2b0eb0735aa8b75a754d5d58db  scripts/install_modules/phases/11_post_install.sh
76c9804fd20dd7dd070df758b019f7560b044981b4224c9d8e3b8e8d4f3be7fa  scripts/install_modules/phases/12_alembic.sh
d1b9b686a11ce94cb9131924c8175a82377f15fa309d42a1963419ab45090768  scripts/install_modules/phases/13_playwright.sh
d154b3e6b9f3ec882f9563538f6c5283708c2ed3c5dfa3cebfbf3c308b685431  scripts/install_modules/phases/14_react.sh
7069d4012443aa6986d2ef6d56fa5c7e13cd2b1edb0bd226792cba8f2085aa14  scripts/install_modules/utils/database_url.sh
642067cac2e051e2e2abcebee3968bb702569d2de4f3261dcc4f62f07227f5c6  scripts/install_modules/utils/db_credentials.sh
ed07067c6dc62bebf8af21fdd6c3682d1caf805b35ebaf51a0a4e9438defa6d0  scripts/install_modules/utils/env_secrets.sh
831b5aa53053588259b7825f7f6391e37281d04f76baf5be842d5d255b1538c5  scripts/install_modules/utils/env_utils.sh
2e0cb7e3618a2312b26042f59fd035852436caef0c60ea56b82c14969e86426f  scripts/install_modules/utils/gpu_utils.sh
9e1534740edec9c8abfca8bff06ca0e7d48ec6cfa16ba4ac2165f8d12ba72872  scripts/install_modules/utils/install_remediation.sh
95d2664491bc38ff01d7f3951cde14832dc542965aea5e0cdeffef01f0d31b2a  scripts/install_modules/utils/installer_hash_guard.sh
2b4934ce22b5814a6bfc800e149392def0ebbf7b12a951fcfc443a0431aba585  scripts/install_modules/utils/ollama_models.sh
04d67e8a412448bb38bd94ab525f8d5d95856d20fa7bb10a098ad3e893676ea2  scripts/install_modules/utils/playwright_ubuntu_override.sh
a8997d9ab218f5879e140fbfa784754898a353c2c9b77dc3801093f1960d8bc7  scripts/install_modules/utils/python_env.sh
ae01c4d07589332e304f189928e78555514aa5d1b85b2178e0a35fb40e60ed11  scripts/install_modules/utils/remote_script.sh
efec83c69fa618e4274f4936bb1156128f3dc6e9f605270ebfe3b8fc58afde77  scripts/install_modules/utils/services_docker.sh
4effdccc94e05adaf27362aef74593b64bf34acab8930baba7b147289c640587  scripts/install_modules/utils/ux.sh
19edb98405a5255322d247fdbe2a9691b2ea21cfa33de942c529280c83639357  scripts/install_modules/utils/wsl_gpu_preflight.sh
22898858fffb46b0bf522f91ddd9bde6e78ed70c06245f8cb966de2918446e48  scripts/install_modules/utils/wsl_host.sh
1e6cb5e5c4d571987986b100694c50e5f043bbe1741bb9f824cbe5807d710c09  scripts/install_modules/utils/wsl_integration_autofix.ps1
53ebf2c5d772a2cdbe27dbef5286dfcbdb76dea5c7c67b1584589ec9c47c7d7d  scripts/install_modules/utils/wsl_integration_autofix.sh
SIDAR_MODULE_HASHES_EOF

declare -A INSTALL_REMOTE_MODULE_HASHES=()
EMBEDDED_MODULE_HASH_MANIFEST_TEMP_FILE=""

populate_remote_module_hashes_from_embedded_manifest() {
    local expected_hash=""
    local rel_path=""
    local module_rel=""

    [[ -n "${EMBEDDED_MODULE_HASHES_MANIFEST:-}" ]] || return 0
    while IFS=' ' read -r expected_hash rel_path; do
        [[ -n "${expected_hash:-}" && -n "${rel_path:-}" ]] || continue
        module_rel="${rel_path#scripts/install_modules/}"
        INSTALL_REMOTE_MODULE_HASHES["$module_rel"]="$expected_hash"
    done < <(printf '%s\n' "$EMBEDDED_MODULE_HASHES_MANIFEST" | awk 'NF>=2 && $1 !~ /^#/ {print $1, $2}')
}

if [[ "${SIDAR_INSTALL_VERSION_PROBE_ONLY:-0}" != "1" ]]; then
    populate_remote_module_hashes_from_embedded_manifest
fi

cleanup_embedded_module_hash_manifest_temp_file() {
    if [[ -n "${EMBEDDED_MODULE_HASH_MANIFEST_TEMP_FILE:-}" ]]; then
        rm -f "$EMBEDDED_MODULE_HASH_MANIFEST_TEMP_FILE"
        EMBEDDED_MODULE_HASH_MANIFEST_TEMP_FILE=""
    fi
}

verify_remote_install_module_hash() {
    local module_rel="$1"
    local downloaded_file="$2"
    local expected_hash="${INSTALL_REMOTE_MODULE_HASHES[$module_rel]:-}"
    local actual_hash=""

    if [[ -z "$expected_hash" ]]; then
        if [[ "${ALLOW_UNVERIFIED_REMOTE_SCRIPTS:-0}" == "1" ]]; then
            warn "Fallback modül hash manifestinde kayıt yok: ${module_rel} (ALLOW_UNVERIFIED_REMOTE_SCRIPTS=1 ile devam ediliyor)."
            return 0
        fi
        fail "Fallback modül hash manifestinde kayıt yok: ${module_rel}. Defense-in-depth gereği doğrulamasız modül yüklenemez."
    fi

    actual_hash="$(compute_sha256 "$downloaded_file")"
    if [[ "$actual_hash" == "$expected_hash" ]]; then
        return 0
    fi

    if [[ "${ALLOW_UNVERIFIED_REMOTE_SCRIPTS:-0}" == "1" ]]; then
        warn "Fallback modül hash uyuşmazlığı: ${module_rel} (beklenen=${expected_hash}, mevcut=${actual_hash}); ALLOW_UNVERIFIED_REMOTE_SCRIPTS=1 ile devam ediliyor."
        return 0
    fi

    fail "Fallback modül hash doğrulaması başarısız: ${module_rel} (beklenen=${expected_hash}, mevcut=${actual_hash})."
}

sidar_ref_is_commit_sha() {
    local ref="${1:-}"
    [[ "$ref" =~ ^[0-9a-fA-F]{40}$ ]]
}

sidar_raw_github_module_ref() {
    local remote_module_base="${1:-}"
    printf '%s' "$remote_module_base" | sed -nE 's#^https://raw\.githubusercontent\.com/[^/]+/[^/]+/([^/]+)/scripts/install_modules/?$#\1#p'
}

sidar_github_repo_slug_from_url() {
    local repo_url="${1:-}"
    local owner_repo=""

    repo_url="${repo_url%.git}"
    owner_repo="$(printf '%s' "$repo_url" | sed -nE 's#^https?://github\.com/([^/]+/[^/]+)$#\1#p')"
    if [[ -z "$owner_repo" ]]; then
        owner_repo="$(printf '%s' "$repo_url" | sed -nE 's#^git@github\.com:([^/]+/[^/]+)$#\1#p')"
    fi
    printf '%s' "$owner_repo"
}

resolve_github_ref_commit_sha() {
    local repo_url="${1:-}"
    local ref="${2:-main}"
    local owner_repo=""
    local api_url=""
    local response=""
    local resolved_sha=""

    sidar_ref_is_commit_sha "$ref" && { printf '%s' "$ref"; return 0; }
    owner_repo="$(sidar_github_repo_slug_from_url "$repo_url")"
    [[ -n "$owner_repo" ]] || return 1
    api_url="https://api.github.com/repos/${owner_repo}/commits/${ref}"

    if command -v curl >/dev/null 2>&1; then
        response="$(curl -fsSL --connect-timeout 10 --max-time 20 "$api_url" 2>/dev/null || true)"
    elif command -v wget >/dev/null 2>&1; then
        response="$(wget -qO- --timeout=20 "$api_url" 2>/dev/null || true)"
    else
        return 1
    fi

    resolved_sha="$(printf '%s\n' "$response" | sed -nE 's/.*"sha"[[:space:]]*:[[:space:]]*"([0-9a-fA-F]{40})".*/\1/p' | head -n 1)"
    if sidar_ref_is_commit_sha "$resolved_sha"; then
        printf '%s' "$resolved_sha"
        return 0
    fi
    return 1
}

resolve_remote_module_ref() {
    local resolved_ref=""
    local mutable_ref="${SIDAR_INSTALLER_EMBEDDED_SOURCE_REF:-${SIDAR_REPO_BRANCH:-main}}"

    if [[ -n "${SIDAR_BOOTSTRAP_PINNED_REF:-}" ]]; then
        printf '%s' "$SIDAR_BOOTSTRAP_PINNED_REF"
        return 0
    fi
    if sidar_ref_is_commit_sha "${SIDAR_INSTALLER_EMBEDDED_SOURCE_COMMIT:-}"; then
        printf '%s' "$SIDAR_INSTALLER_EMBEDDED_SOURCE_COMMIT"
        return 0
    fi
    if resolved_ref="$(resolve_github_ref_commit_sha "${SIDAR_REPO_URL:-https://github.com/niluferbagevi-gif/Sidar.git}" "$mutable_ref")"; then
        warn "Embedded installer commit pin bulunamadı; ${mutable_ref} GitHub API üzerinden ${resolved_ref} commit SHA'sına çözüldü. Kalıcı çözüm için SIDAR_INSTALLER_EMBEDDED_SOURCE_COMMIT damgalanmalı."
        printf '%s' "$resolved_ref"
        return 0
    fi
    printf '%s' "${SIDAR_REPO_BRANCH:-main}"
}

validate_remote_module_trust_root() {
    local remote_module_base="${1:-}"
    local raw_ref=""

    raw_ref="$(sidar_raw_github_module_ref "$remote_module_base")"
    [[ -n "$raw_ref" ]] || return 0
    if sidar_ref_is_commit_sha "$raw_ref"; then
        return 0
    fi
    if [[ "${SIDAR_INSTALL_ALLOW_MUTABLE_MODULE_REF:-0}" == "1" ]]; then
        warn "Fallback modül kaynağı mutable GitHub ref kullanıyor (${raw_ref}); SIDAR_INSTALL_ALLOW_MUTABLE_MODULE_REF=1 ile TOFU riski operatör tarafından kabul edildi."
        return 0
    fi

    fail "Fallback modül güven kökü zayıf: ${remote_module_base} mutable GitHub ref (${raw_ref}) kullanıyor. SIDAR_BOOTSTRAP_PINNED_REF=<40 karakter commit SHA> veya SIDAR_INSTALL_MODULE_BASE_URL=https://raw.githubusercontent.com/<owner>/<repo>/<commit-sha>/scripts/install_modules ile commit'e pinleyin. Bilinçli geçici bypass için SIDAR_INSTALL_ALLOW_MUTABLE_MODULE_REF=1 ayarlanabilir."
}

derive_remote_module_base_from_repo() {
    local repo_url="${1:-}"
    local repo_branch="${2:-main}"
    local owner_repo=""

    repo_url="${repo_url%.git}"
    owner_repo="$(printf '%s' "$repo_url" | sed -nE 's#^https?://github.com/([^/]+/[^/]+)$#\1#p')"
    if [[ -z "$owner_repo" ]]; then
        owner_repo="$(printf '%s' "$repo_url" | sed -nE 's#^git@github.com:([^/]+/[^/]+)$#\1#p')"
    fi
    [[ -n "$owner_repo" ]] || return 1
    printf 'https://raw.githubusercontent.com/%s/%s/scripts/install_modules' "$owner_repo" "$repo_branch"
}

remote_install_module_cache_key() {
    local remote_module_base="$1"
    if command -v sha256sum >/dev/null 2>&1; then
        printf '%s' "$remote_module_base" | sha256sum | awk '{print $1}'
        return 0
    fi
    if command -v shasum >/dev/null 2>&1; then
        printf '%s' "$remote_module_base" | shasum -a 256 | awk '{print $1}'
        return 0
    fi
    printf '%s' "$remote_module_base" | sed -E 's#[^A-Za-z0-9._-]+#_#g'
}

default_install_module_cache_root() {
    local uid_suffix=""
    local cache_home=""

    uid_suffix="$(id -u 2>/dev/null || printf unknown)"
    if [[ -n "${HOME:-}" && -d "${HOME:-}" ]]; then
        cache_home="${XDG_CACHE_HOME:-${HOME}/.cache}"
        printf '%s/sidar/install_modules' "$cache_home"
        return 0
    fi

    printf '%s/sidar_install_modules_cache_%s' "${TMPDIR:-/tmp}" "$uid_suffix"
}

cleanup_legacy_auto_install_module_caches() {
    local cleanup_days="${SIDAR_INSTALL_MODULE_CACHE_CLEANUP_DAYS:-7}"
    local tmp_root="${TMPDIR:-/tmp}"
    local uid_suffix=""
    local cache_dir=""
    local owner_uid=""
    local current_uid=""

    [[ "$cleanup_days" =~ ^[0-9]+$ ]] || return 0
    uid_suffix="$(id -u 2>/dev/null || printf unknown)"
    current_uid="$(id -u 2>/dev/null || true)"
    for cache_dir in "$tmp_root"/sidar_install_modules_cache_${uid_suffix}.*; do
        [[ -d "$cache_dir" && ! -L "$cache_dir" ]] || continue
        if [[ -n "$current_uid" ]]; then
            owner_uid="$(stat -c '%u' "$cache_dir" 2>/dev/null || stat -f '%u' "$cache_dir" 2>/dev/null || true)"
            [[ "$owner_uid" == "$current_uid" ]] || continue
        fi
        if find "$cache_dir" -maxdepth 0 -mtime +"$cleanup_days" -print -quit 2>/dev/null | read -r _; then
            rm -rf -- "$cache_dir" || true
        fi
    done
}

prepare_install_module_cache_root() {
    local cache_root="${SIDAR_INSTALL_MODULE_CACHE_ROOT:-}"
    local owner_uid=""
    local current_uid=""

    if [[ -z "${cache_root:-}" ]]; then
        cache_root="$(default_install_module_cache_root)"
        SIDAR_INSTALL_MODULE_CACHE_ROOT="$cache_root"
        # shellcheck disable=SC2034  # Exposed for installer probes/tests to distinguish auto-created cache roots.
        SIDAR_INSTALL_MODULE_CACHE_ROOT_AUTO=1
        cleanup_legacy_auto_install_module_caches
    fi
    if [[ -L "$cache_root" ]]; then
        fail "Fallback modül cache dizini sembolik link olamaz: $cache_root"
    fi
    if [[ -e "$cache_root" && ! -d "$cache_root" ]]; then
        fail "Fallback modül cache yolu dizin değil: $cache_root"
    fi

    mkdir -p "$cache_root" || fail "Fallback modül cache dizini oluşturulamadı: $cache_root"
    chmod 700 "$cache_root" 2>/dev/null || true

    current_uid="$(id -u 2>/dev/null || true)"
    if [[ -n "$current_uid" ]]; then
        if owner_uid="$(stat -c '%u' "$cache_root" 2>/dev/null || stat -f '%u' "$cache_root" 2>/dev/null)"; then
            if [[ "$owner_uid" != "$current_uid" ]]; then
                fail "Fallback modül cache dizini mevcut kullanıcıya ait değil: $cache_root (owner_uid=$owner_uid, current_uid=$current_uid)"
            fi
        fi
    fi
}

remote_install_module_cached_path() {
    local module_rel="$1"
    local remote_module_base="$2"
    local cache_key=""

    cache_key="$(remote_install_module_cache_key "$remote_module_base")"
    printf '%s/%s/%s' "$SIDAR_INSTALL_MODULE_CACHE_ROOT" "$cache_key" "$module_rel"
}

remote_install_module_retry_sleep() {
    local attempt="$1"
    local retry_after="${2:-}"
    local delay="$SIDAR_INSTALL_MODULE_RETRY_DELAY"
    local jitter=0

    if [[ "$retry_after" =~ ^[0-9]+$ && "$retry_after" -gt 0 ]]; then
        delay="$retry_after"
    else
        delay=$((SIDAR_INSTALL_MODULE_RETRY_DELAY * (2 ** (attempt - 1))))
        jitter=$(( RANDOM % 3 ))
        delay=$((delay + jitter))
    fi

    if [[ "${SIDAR_INSTALL_TEST_MODE:-0}" == "1" || "${SIDAR_INSTALL_SKIP_RETRY_SLEEP:-0}" == "1" ]]; then
        info "Fallback modül retry beklemesi test modunda atlandı: ${delay}s"
        return 0
    fi
    sleep "$delay"
}

download_remote_install_module_with_curl() {
    local module_rel="$1"
    local remote_module_url="$2"
    local tmp_module_path="$3"
    local headers_path="$4"
    local http_code=""

    http_code="$(
        curl \
            -fsSL \
            --retry "$SIDAR_INSTALL_MODULE_DOWNLOAD_RETRIES" \
            --retry-all-errors \
            --retry-delay "$SIDAR_INSTALL_MODULE_RETRY_DELAY" \
            --connect-timeout "$SIDAR_INSTALL_MODULE_CONNECT_TIMEOUT" \
            --max-time "$SIDAR_INSTALL_MODULE_MAX_TIME" \
            -D "$headers_path" \
            -w '%{http_code}' \
            "$remote_module_url" \
            -o "$tmp_module_path" 2>/dev/null
    )" || {
        printf '%s' "${http_code:-000}"
        return 1
    }
    printf '%s' "${http_code:-000}"
    return 0
}

download_remote_install_module_with_wget() {
    local remote_module_url="$1"
    local tmp_module_path="$2"

    wget \
        --tries="$SIDAR_INSTALL_MODULE_DOWNLOAD_RETRIES" \
        --connect-timeout="$SIDAR_INSTALL_MODULE_CONNECT_TIMEOUT" \
        --read-timeout="$SIDAR_INSTALL_MODULE_MAX_TIME" \
        --waitretry="$SIDAR_INSTALL_MODULE_RETRY_DELAY" \
        -qO "$tmp_module_path" "$remote_module_url"
}

remote_install_module_status_is_retryable() {
    local http_code="${1:-000}"

    case "$http_code" in
        000|403|408|409|425|429|5??) return 0 ;;
        *) return 1 ;;
    esac
}

remote_install_module_retry_after_header() {
    local headers_path="$1"
    awk 'BEGIN{IGNORECASE=1} /^Retry-After:/ {gsub("\r", "", $2); print $2; exit}' "$headers_path" 2>/dev/null || true
}

download_remote_install_module() {
    local module_rel="$1"
    local remote_module_base="$2"
    local destination_root="$3"
    local remote_module_url="${remote_module_base}/${module_rel}"
    local destination_path="${destination_root}/${module_rel}"
    local tmp_module_path=""
    local cache_path=""
    local cache_sentinel=""
    local headers_path=""
    local attempt=1
    local max_attempts=$((SIDAR_INSTALL_MODULE_DOWNLOAD_RETRIES + 1))
    local http_code="000"
    local retry_after=""

    mkdir -p "$(dirname "$destination_path")"
    prepare_install_module_cache_root
    cache_path="$(remote_install_module_cached_path "$module_rel" "$remote_module_base")"
    cache_sentinel="${cache_path}.ok"
    if [[ -f "$cache_path" && -f "$cache_sentinel" ]]; then
        SIDAR_INSTALL_MODULE_CACHE_HITS=$((SIDAR_INSTALL_MODULE_CACHE_HITS + 1))
        if [[ "${SIDAR_INSTALL_TEST_MODE:-0}" == "1" && "${SIDAR_INSTALL_ENFORCE_FILE_MODULE_HASHES:-0}" != "1" && "$remote_module_base" == file://* ]]; then
            :
        else
            verify_remote_install_module_hash "$module_rel" "$cache_path"
        fi
        install -m 0644 "$cache_path" "$destination_path"
        info "Fallback modül cache'den kullanıldı: ${module_rel} -> ${destination_path}"
        return 0
    fi

    tmp_module_path="$(mktemp "${TMPDIR:-/tmp}/sidar_install_module.XXXXXX")"
    headers_path="$(mktemp "${TMPDIR:-/tmp}/sidar_install_module_headers.XXXXXX")"

    while (( attempt <= max_attempts )); do
        rm -f "$tmp_module_path" "$headers_path"
        SIDAR_INSTALL_MODULE_DOWNLOAD_ATTEMPTS=$((SIDAR_INSTALL_MODULE_DOWNLOAD_ATTEMPTS + 1))
        if command -v curl &>/dev/null; then
            if http_code="$(download_remote_install_module_with_curl "$module_rel" "$remote_module_url" "$tmp_module_path" "$headers_path")"; then
                break
            fi
        elif command -v wget &>/dev/null; then
            if download_remote_install_module_with_wget "$remote_module_url" "$tmp_module_path"; then
                http_code="200"
                break
            fi
            http_code="000"
        else
            rm -f "$tmp_module_path" "$headers_path"
            fail "Fallback modül indirilemedi (${module_rel}): curl veya wget bulunamadı."
        fi

        if (( attempt >= max_attempts )) || ! remote_install_module_status_is_retryable "$http_code"; then
            rm -f "$tmp_module_path" "$headers_path"
            warn "Fallback modül indirme başarısız (${module_rel}); url=${remote_module_url}; http_status=${http_code}; deneme=${attempt}/${max_attempts}"
            return 1
        fi

        if [[ "$http_code" == "429" ]]; then
            SIDAR_INSTALL_MODULE_HTTP_429_RETRIES=$((SIDAR_INSTALL_MODULE_HTTP_429_RETRIES + 1))
        fi
        retry_after="$(remote_install_module_retry_after_header "$headers_path")"
        warn "Fallback modül indirme geçici hata (${module_rel}); http_status=${http_code}; deneme=${attempt}/${max_attempts}. Exponential backoff ile tekrar denenecek."
        remote_install_module_retry_sleep "$attempt" "$retry_after"
        attempt=$((attempt + 1))
    done

    if [[ "${SIDAR_INSTALL_TEST_MODE:-0}" == "1" && "${SIDAR_INSTALL_ENFORCE_FILE_MODULE_HASHES:-0}" != "1" && "$remote_module_base" == file://* ]]; then
        INSTALL_REMOTE_MODULE_HASH_BYPASS=1
        :
    else
        verify_remote_install_module_hash "$module_rel" "$tmp_module_path"
    fi
    install -m 0644 "$tmp_module_path" "$destination_path"
    mkdir -p "$(dirname "$cache_path")"
    install -m 0644 "$tmp_module_path" "$cache_path"
    printf 'module=%s\nsource=%s\n' "$module_rel" "$remote_module_base" > "$cache_sentinel"
    rm -f "$tmp_module_path" "$headers_path"
    SIDAR_INSTALL_MODULES_DOWNLOADED_COUNT=$((SIDAR_INSTALL_MODULES_DOWNLOADED_COUNT + 1))
    info "Fallback modül indirildi: ${module_rel} -> ${destination_path}"
}


resolve_remote_module_base() {
    local remote_module_base="${SIDAR_INSTALL_MODULE_BASE_URL:-}"
    local remote_module_ref=""

    if [[ -z "$remote_module_base" ]]; then
        remote_module_ref="$(resolve_remote_module_ref)"
        remote_module_base="$(derive_remote_module_base_from_repo "${SIDAR_REPO_URL:-https://github.com/niluferbagevi-gif/Sidar.git}" "$remote_module_ref" || true)"
    fi
    [[ -n "$remote_module_base" ]] || remote_module_base="https://raw.githubusercontent.com/niluferbagevi-gif/Sidar/$(resolve_remote_module_ref)/scripts/install_modules"
    printf '%s' "$remote_module_base"
}

install_module_tree_missing_summary() {
    local module_root="$1"
    local module_rel=""
    local missing_count=0
    local missing_preview=()

    for module_rel in "${INSTALL_REMOTE_MODULES[@]}"; do
        if [[ ! -f "${module_root}/${module_rel}" ]]; then
            missing_count=$((missing_count + 1))
            if [[ ${#missing_preview[@]} -lt 6 ]]; then
                missing_preview+=("$module_rel")
            fi
        fi
    done

    if [[ $missing_count -eq 0 ]]; then
        return 0
    fi

    printf '%s eksik' "$missing_count"
    if [[ ${#missing_preview[@]} -gt 0 ]]; then
        printf ': %s' "${missing_preview[*]}"
        if [[ $missing_count -gt ${#missing_preview[@]} ]]; then
            printf ' ...'
        fi
    fi
    return 1
}


use_existing_install_module_tree_if_available() {
    local candidate_dir=""
    local candidate_status=""
    local candidates=(
        "${INSTALL_MODULE_DIR}"
        "${PWD}/scripts/install_modules"
        "${HOME}/Sidar/scripts/install_modules"
    )
    local seen=""

    if [[ -n "${TARGET_DIR:-}" ]]; then
        candidates+=("${TARGET_DIR}/scripts/install_modules")
    fi

    for candidate_dir in "${candidates[@]}"; do
        [[ -n "${candidate_dir:-}" && -d "$candidate_dir" ]] || continue
        case ":${seen}:" in
            *":${candidate_dir}:"*) continue ;;
        esac
        seen="${seen}:${candidate_dir}"
        candidate_status="$(install_module_tree_missing_summary "$candidate_dir" || true)"
        if [[ -z "$candidate_status" ]]; then
            if [[ "$candidate_dir" != "$INSTALL_MODULE_DIR" ]]; then
                info "Mevcut repo kurulum modülleri doğrudan kullanılacak: $candidate_dir"
                sidar_set_install_module_dir "$candidate_dir"
            fi
            if [[ "${SIDAR_INSTALLER_BOOTSTRAP_MODE:-unknown}" == "unknown" ]]; then
                if [[ "${SIDAR_BUNDLE_MODE:-0}" == "1" ]]; then
                    SIDAR_INSTALLER_BOOTSTRAP_MODE="bundle"
                else
                    SIDAR_INSTALLER_BOOTSTRAP_MODE="local-module-tree"
                fi
            fi
            return 0
        fi
        info "Aday kurulum modül ağacı eksik: $candidate_dir (${candidate_status})"
    done

    return 1
}

download_install_modules_to_temp() {
    local remote_module_base="$1"

    INSTALL_HELPERS_TEMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/sidar_install_modules.XXXXXX")"
    sidar_set_install_module_dir "${INSTALL_HELPERS_TEMP_DIR}/install_modules"
    download_remote_install_modules "$remote_module_base" "$INSTALL_MODULE_DIR" || fail "Fallback modül indirme başarısız: $remote_module_base"
    INSTALL_MODULES_DOWNLOADED=1
    SIDAR_INSTALLER_BOOTSTRAP_MODE="raw-module-fallback"
    export SIDAR_INSTALL_MODULE_BASE_URL="$remote_module_base"
    ok "Fallback modülleri geçici dizine indirildi: $INSTALL_MODULE_DIR"
}

download_remote_install_modules() {
    local remote_module_base="$1"
    local destination_root="$2"
    local module_rel=""

    for module_rel in "${INSTALL_REMOTE_MODULES[@]}"; do
        download_remote_install_module "$module_rel" "$remote_module_base" "$destination_root" || {
            warn "Fallback modül indirme akışı ${module_rel} dosyasında durdu. Cache korunur; aynı komut tekrar çalıştırıldığında başarılı modüller yeniden kullanılacaktır."
            return 1
        }
    done
}

if [[ -f "${INSTALL_MODULE_DIR}/utils/installer_hash_guard.sh" ]]; then
    # shellcheck source=scripts/install_modules/utils/installer_hash_guard.sh
    # shellcheck disable=SC1091
    source "${INSTALL_MODULE_DIR}/utils/installer_hash_guard.sh"
fi

# Raw/standalone installer runs may reach the re-exec decision before utility
# modules exist locally. Keep a minimal fallback shim here; once modules are
# present, utils/installer_hash_guard.sh becomes the shared implementation used
# by the installer and sourced install modules.
if ! declare -F installer_hash_guard_git_root_for_script >/dev/null 2>&1; then
    installer_hash_guard_git_root_for_script() {
        local script_path="$1"
        local script_dir=""

        [[ -n "$script_path" ]] || return 1
        script_dir="$(cd "$(dirname "$script_path")" 2>/dev/null && pwd -P)" || return 1
        git -C "$script_dir" rev-parse --show-toplevel 2>/dev/null
    }
fi

if ! declare -F log_installer_hash_drift_git_context >/dev/null 2>&1; then
    log_installer_hash_drift_git_context() {
        local label="$1"
        local script_path="$2"
        local repo_root=""
        local repo_head=""
        local status_output=""

        command -v git >/dev/null 2>&1 || return 0
        repo_root="$(installer_hash_guard_git_root_for_script "$script_path" || true)"
        [[ -n "$repo_root" ]] || return 0

        repo_head="$(git -C "$repo_root" rev-parse --short HEAD 2>/dev/null || echo bilinmiyor)"
        status_output="$(git -C "$repo_root" status --short 2>/dev/null || true)"
        warn "${label} git bağlamı: repo=${repo_root}, HEAD=${repo_head}"
        if [[ -n "$status_output" ]]; then
            warn "${label} git status --short:"
            while IFS= read -r status_line; do
                warn "  ${status_line}"
            done <<< "$status_output"
        else
            info "${label} git status --short: temiz"
        fi
    }
fi

if ! declare -F check_installer_hash >/dev/null 2>&1; then
    check_installer_hash() {
        local current_script="$1"
        local next_script="$2"
        local reexec_label="$3"
        local current_sha="bilinmiyor"
        local next_sha="bilinmiyor"

        [[ -f "$next_script" ]] || fail "${reexec_label} hedef install_sidar.sh bulunamadı: $next_script"

        current_sha="$(compute_sha256 "$current_script" 2>/dev/null || echo bilinmiyor)"
        next_sha="$(compute_sha256 "$next_script" 2>/dev/null || echo bilinmiyor)"

        if [[ "$current_sha" == "bilinmiyor" || "$next_sha" == "bilinmiyor" ]]; then
            fail "${reexec_label} install_sidar.sh SHA256 doğrulaması yapılamadı (mevcut=${current_sha}, hedef=${next_sha}). Güvenli re-exec için sha256sum/shasum erişimini düzeltin."
        fi

        if [[ "$current_sha" != "$next_sha" ]]; then
            if [[ "${SIDAR_INSTALL_ALLOW_STALE_REEXEC:-0}" == "1" ]]; then
                warn "${reexec_label} install_sidar.sh SHA256 farklı (mevcut=${current_sha}, hedef=${next_sha}); SIDAR_INSTALL_ALLOW_STALE_REEXEC=1 nedeniyle devam ediliyor."
                return 0
            fi
            log_installer_hash_drift_git_context "Mevcut installer" "$current_script"
            log_installer_hash_drift_git_context "Hedef installer" "$next_script"
            fail "${reexec_label} install_sidar.sh SHA256 farklı (mevcut=${current_sha}, hedef=${next_sha}). Yanlış/eski installer çalıştırma riskini önlemek için re-exec durduruldu. NEXT STEP → hash drift kaynağını temizleyin: \$HOME/Sidar/install_sidar.sh eskiyse 'rm -f \"\$HOME/Sidar/install_sidar.sh\"' komutuyla kaldırıp güncel install_sidar.sh ile yeniden deneyin; hedef repo driftliyse git pull --ff-only veya temiz clone kullanın. Yalnız bilinçli/incelemesi yapılmış durumda SIDAR_INSTALL_ALLOW_STALE_REEXEC=1 ile tekrar deneyin."
        fi
    }
fi

if ! declare -F verify_reexec_installer_or_fail >/dev/null 2>&1; then
    verify_reexec_installer_or_fail() {
        local next_script="$1"
        local reexec_label="$2"

        check_installer_hash "$ORIGINAL_SCRIPT_PATH" "$next_script" "$reexec_label"
    }
fi


if ! declare -F sidar_resolve_resume_installer_path >/dev/null 2>&1; then
    sidar_resolve_resume_installer_path() {
        local repo_script="${SCRIPT_DIR:-}/install_sidar.sh"

        if [[ -n "${SCRIPT_DIR:-}" && -f "$repo_script" ]]; then
            printf '%s\n' "$repo_script"
            return 0
        fi

        if [[ -n "${ORIGINAL_SCRIPT_PATH:-}" && -f "$ORIGINAL_SCRIPT_PATH" ]]; then
            printf '%s\n' "$ORIGINAL_SCRIPT_PATH"
            return 0
        fi

        fail "Auto-heal resume için çalıştırılabilir install_sidar.sh bulunamadı. Denenenler: SCRIPT_DIR=${SCRIPT_DIR:-boş}, ORIGINAL_SCRIPT_PATH=${ORIGINAL_SCRIPT_PATH:-boş}. Repo içindeki install_sidar.sh ile kurulumu yeniden başlatın."
    }
fi

if ! declare -F sidar_verify_resume_installer_or_fail >/dev/null 2>&1; then
    sidar_verify_resume_installer_or_fail() {
        local resume_script="$1"
        local current_script="${ORIGINAL_SCRIPT_PATH:-}"

        [[ -n "$resume_script" ]] || fail "Auto-heal resume hedefi boş."
        [[ -f "$resume_script" ]] || fail "Auto-heal resume hedef install_sidar.sh bulunamadı: $resume_script"

        if [[ -z "$current_script" || ! -f "$current_script" ]]; then
            current_script="$resume_script"
        fi
        check_installer_hash "$current_script" "$resume_script" "Auto-heal resume re-exec"
    }
fi

if ! declare -F verify_home_reexec_candidate_if_present >/dev/null 2>&1; then
    verify_home_reexec_candidate_if_present() {
        local home_script="$HOME/Sidar/install_sidar.sh"

        [[ -d "$HOME/Sidar/.git" && -f "$home_script" ]] || return 0
        if [[ "${SIDAR_INSTALL_TEST_MODE:-0}" == "1" && "${SIDAR_INSTALL_ALLOW_HOME_REEXEC_IN_TEST_MODE:-0}" != "1" ]]; then
            return 0
        fi

        verify_reexec_installer_or_fail "$home_script" "Mevcut $HOME/Sidar re-exec"
    }
fi

bootstrap_clone_and_reexec() {
    local clone_url="${SIDAR_BOOTSTRAP_CLONE_URL:-${SIDAR_REPO_URL:-https://github.com/niluferbagevi-gif/Sidar.git}}"
    local clone_parent="${SIDAR_BOOTSTRAP_CLONE_PARENT_DIR:-$PWD}"
    local clone_name="${SIDAR_BOOTSTRAP_CLONE_DIRNAME:-Sidar}"
    local clone_target="${clone_parent%/}/${clone_name}"
    local preferred_ref="${SIDAR_BOOTSTRAP_CLONE_REF:-${SIDAR_REPO_BRANCH:-main}}"
    local home_repo_candidate="${HOME}/Sidar"
    local clone_head="bilinmiyor"
    local clone_remote="bilinmiyor"
    local raw_installer_sha="bilinmiyor"
    local cloned_installer_sha="bilinmiyor"
    local installer_sha_relation="bilinmiyor"

    warn "Yerel modüller eksik. Geçici /tmp modül indirme yerine bootstrap clone akışı başlatılıyor."

    command -v git >/dev/null 2>&1 || fail "Bootstrap clone için git gerekli ancak sistemde bulunamadı."
    mkdir -p "$clone_parent"

    if [[ -d "$home_repo_candidate/.git" && -f "$home_repo_candidate/scripts/install_modules/install_helpers.sh" ]]; then
        info "Mevcut repo bulundu, bootstrap için kullanılacak: $home_repo_candidate"
        clone_target="$home_repo_candidate"
    fi

    if [[ -d "$clone_target/.git" ]]; then
        info "Mevcut Sidar deposu bulundu, güncelleniyor: $clone_target"
        git -C "$clone_target" fetch --all --tags --prune || fail "Mevcut depo güncellenemedi: $clone_target"
        git -C "$clone_target" checkout -q "$preferred_ref" || fail "Bootstrap ref'e geçilemedi: ${preferred_ref}"
        git -C "$clone_target" pull --ff-only || fail "Depo fast-forward güncellenemedi: $clone_target"
    elif [[ -e "$clone_target" ]]; then
        fail "Bootstrap clone hedefi mevcut ama git deposu değil: $clone_target (devam edilemiyor)."
    else
        step "Sidar deposu bootstrap clone ile indiriliyor"
        git clone --depth=1 --branch "$preferred_ref" "$clone_url" "$clone_target" || fail "Git clone başarısız: $clone_url"
        git -C "$clone_target" checkout -q "$preferred_ref" || fail "Bootstrap ref'e geçilemedi: ${preferred_ref}"
    fi

    local next_script="$clone_target/install_sidar.sh"
    [[ -f "$next_script" ]] || fail "Clone sonrası install_sidar.sh bulunamadı: $next_script"
    clone_head="$(git -C "$clone_target" rev-parse HEAD 2>/dev/null || echo bilinmiyor)"
    clone_remote="$(git -C "$clone_target" remote get-url origin 2>/dev/null || echo bilinmiyor)"
    raw_installer_sha="$(compute_sha256 "$ORIGINAL_SCRIPT_PATH" 2>/dev/null || echo bilinmiyor)"
    cloned_installer_sha="$(compute_sha256 "$next_script" 2>/dev/null || echo bilinmiyor)"
    if [[ "$raw_installer_sha" == "$cloned_installer_sha" ]]; then
        installer_sha_relation="eşleşiyor"
    else
        installer_sha_relation="farklı"
    fi
    verify_reexec_installer_or_fail "$next_script" "Bootstrap clone re-exec"
    chmod +x "$next_script" || true
    cd "$clone_target" || fail "Clone sonrası dizine geçilemedi: $clone_target"
    export SIDAR_BOOTSTRAP_REEXEC_TARGET="$clone_target"
    export SIDAR_BOOTSTRAP_REEXEC_REF="$preferred_ref"
    export SIDAR_BOOTSTRAP_REEXEC_HEAD="$clone_head"
    export SIDAR_BOOTSTRAP_REEXEC_REMOTE="$clone_remote"
    export SIDAR_INSTALLER_BOOTSTRAP_MODE="bootstrap-clone-reexec"
    export SIDAR_BOOTSTRAP_ORIGINAL_INSTALLER_SHA256="$raw_installer_sha"
    export SIDAR_BOOTSTRAP_CLONED_INSTALLER_SHA256="$cloned_installer_sha"
    export SIDAR_BOOTSTRAP_INSTALLER_SHA_RELATION="$installer_sha_relation"
    export SIDAR_BOOTSTRAP_RAW_INSTALLER_SOURCE_REF="$SIDAR_INSTALLER_EMBEDDED_SOURCE_REF"
    export SIDAR_BOOTSTRAP_RAW_INSTALLER_SOURCE_COMMIT="$SIDAR_INSTALLER_EMBEDDED_SOURCE_COMMIT"
    info "Bootstrap clone tamamlandı (HEAD=${clone_head}, installer_sha=${installer_sha_relation}); yerel kurulum betiği yeniden başlatılıyor."
    exec "$next_script" "${SIDAR_INSTALL_ORIGINAL_ARGS[@]}"
}

use_existing_install_module_tree_if_available || true
LOCAL_INSTALL_MODULE_TREE_STATUS="$(install_module_tree_missing_summary "$INSTALL_MODULE_DIR" || true)"
if [[ -n "${LOCAL_INSTALL_MODULE_TREE_STATUS:-}" ]]; then
    if [[ "${SIDAR_BUNDLE_MODE:-0}" == "1" ]]; then
        fail "SIDAR_BUNDLE_MODE=1 algılandı ancak yerel kurulum modül ağacı eksik: $INSTALL_MODULE_DIR (${LOCAL_INSTALL_MODULE_TREE_STATUS}). Bundle bütünlüğünü doğrulayın ve betiği yeniden üretin."
    fi
    info "Yerel kurulum modül ağacı eksik: $INSTALL_MODULE_DIR (${LOCAL_INSTALL_MODULE_TREE_STATUS})"
    verify_home_reexec_candidate_if_present

    if [[ "${OFFLINE_MODE:-false}" == "true" ]]; then
        fail "--offline/--air-gapped erken algılandı; yerel kurulum modül ağacı eksik olduğu için raw fallback modül indirme veya bootstrap clone yapılmayacak. Hava boşluklu kurulum için release bundle install_sidar.sh kullanın veya scripts/install_modules ağacını aynı dizine yerleştirin."
    fi

    if [[ "${SIDAR_INSTALL_SKIP_DIRECT_MODULE_DOWNLOAD:-0}" == "1" ]]; then
        warn "SIDAR_INSTALL_SKIP_DIRECT_MODULE_DOWNLOAD=1; fallback modül indirme atlandı, bootstrap/re-exec yolu denenecek."
    elif command -v curl &>/dev/null || command -v wget &>/dev/null; then
        REMOTE_MODULE_BASE="$(resolve_remote_module_base)"
        validate_remote_module_trust_root "$REMOTE_MODULE_BASE"
        info "Git clone/re-exec öncesi fallback modüller doğrudan indirilecek: $REMOTE_MODULE_BASE"
        download_install_modules_to_temp "$REMOTE_MODULE_BASE"
    fi

    if [[ "${INSTALL_MODULES_DOWNLOADED:-0}" != "1" ]]; then
        if { [[ "${SIDAR_INSTALL_TEST_MODE:-0}" != "1" ]] || [[ "${SIDAR_INSTALL_ALLOW_HOME_REEXEC_IN_TEST_MODE:-0}" == "1" ]]; } && [[ -d "$HOME/Sidar/.git" && -f "$HOME/Sidar/install_sidar.sh" ]]; then
            info "Mevcut repo algılandı: $HOME/Sidar — kurulum buradan yeniden başlatılıyor."
            verify_reexec_installer_or_fail "$HOME/Sidar/install_sidar.sh" "Mevcut $HOME/Sidar re-exec"
            cd "$HOME/Sidar" || fail "Mevcut repo dizinine geçilemedi: $HOME/Sidar"
            exec "$HOME/Sidar/install_sidar.sh" "${SIDAR_INSTALL_ORIGINAL_ARGS[@]}"
        fi

        if { [[ "${SIDAR_INSTALL_TEST_MODE:-0}" != "1" ]] || [[ "${SIDAR_INSTALL_ALLOW_BOOTSTRAP_IN_TEST_MODE:-0}" == "1" ]]; } && command -v git >/dev/null 2>&1; then
            bootstrap_clone_and_reexec
        fi
    fi

    if [[ "${INSTALL_MODULES_DOWNLOADED:-0}" != "1" ]]; then
        fail "Yerel kurulum modülleri eksik; doğrudan fallback indirme için curl/wget, bootstrap clone için git bulunamadı. Kurulum devam edemiyor."
    fi
fi
unset LOCAL_INSTALL_MODULE_TREE_STATUS
if [[ "${SIDAR_INSTALL_VERSION_PROBE_ONLY:-0}" != "1" ]]; then
    # shellcheck disable=SC1090
    source "$INSTALL_HELPERS_MODULE"
    if [[ "${INSTALL_MODULES_DOWNLOADED:-0}" == "1" ]]; then
        ok "Kurulum modülleri indirildi."
    fi

    core_manifest_status=0
    if [[ "${SIDAR_INSTALL_TEST_MODE:-0}" == "1" && "${BASH_SOURCE[0]}" != "$0" ]]; then
        info "SIDAR_INSTALL_TEST_MODE=1 source akışı: çekirdek manifest doğrulaması atlandı."
    else
        verify_core_install_manifest || core_manifest_status=$?
        if [[ $core_manifest_status -ne 0 ]]; then
            case "$core_manifest_status" in
                2) info "Manifest doğrulaması bootstrap/repo senkronizasyonu sonrasına ertelendi." ;;
                *) fail "Çekirdek kurulum manifest doğrulaması başarısız." ;;
            esac
        fi
    fi
fi

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


is_blank() {
    local value="${1-}"
    [[ -z "${value//[[:space:]]/}" ]]
}

resolve_install_sidar_version() {
    local resolved_version=""
    local python_version_error=""
    local pyproject_line=""

    # Repo refresh/source smoke paths must not depend on python3 or sed just to
    # resolve the installer version. Always try the Bash-only pyproject parser
    # first and return immediately when [project].version is present.
    if [[ -f "$SCRIPT_DIR/pyproject.toml" ]]; then
        while IFS= read -r pyproject_line; do
            if [[ "$pyproject_line" =~ ^[[:space:]]*version[[:space:]]*=[[:space:]]*\"([^\"]+)\" ]]; then
                resolved_version="${BASH_REMATCH[1]}"
                break
            fi
        done < "$SCRIPT_DIR/pyproject.toml"
    fi
    resolved_version="${resolved_version//[[:space:]]/}"
    if [[ -n "$resolved_version" ]]; then
        echo "$resolved_version"
        return 0
    fi

    if is_blank "$resolved_version" && [[ -f "$SCRIPT_DIR/scripts/version_probe.py" && -f "$SCRIPT_DIR/pyproject.toml" ]] && command -v python3 &>/dev/null; then
        python_version_error="$(mktemp "${TMPDIR:-/tmp}/sidar_version_resolve.XXXXXX")" || python_version_error=""
        resolved_version=$(python3 "$SCRIPT_DIR/scripts/version_probe.py" --pyproject "$SCRIPT_DIR/pyproject.toml" 2>"${python_version_error:-/dev/null}" || true)
        if [[ -n "$python_version_error" ]]; then
            if is_blank "$resolved_version" && [[ -s "$python_version_error" ]]; then
                warn "scripts/version_probe.py üzerinden sürüm okunamadı; sidar_version.py fallback denenecek: $(tr '\n' ' ' < "$python_version_error")"
            fi
            rm -f "$python_version_error"
        fi
    fi

    if is_blank "$resolved_version" && [[ -f "$SCRIPT_DIR/sidar_version.py" && "${SIDAR_INSTALL_TEST_MODE:-0}" != "1" ]] && command -v python3 &>/dev/null; then
        python_version_error="$(mktemp "${TMPDIR:-/tmp}/sidar_version_resolve.XXXXXX")" || python_version_error=""
        resolved_version=$(PYTHONPATH="$SCRIPT_DIR" python3 - <<'PY_VERSION' 2>"${python_version_error:-/dev/null}" || true
from sidar_version import resolve_version

print(resolve_version())
PY_VERSION
)
        if [[ -n "$python_version_error" ]]; then
            if is_blank "$resolved_version" && [[ -s "$python_version_error" ]]; then
                warn "sidar_version.py üzerinden sürüm okunamadı; 0.0.0 fallback kullanılabilir: $(tr '\n' ' ' < "$python_version_error")"
            fi
            rm -f "$python_version_error"
        fi
    fi

    resolved_version="${resolved_version//[[:space:]]/}"
    echo "${resolved_version:-0.0.0}"
}


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

# Fast-path: version-probe-only akışı (örn. CI smoke gate) için tüm ağır
# subprocess çağrılarını (readlink, sed, sha256sum, helper source, manifest
# verify) atlayarak pure-bash regex ile pyproject.toml'dan sürümü çözüp
# kullanıcının yavaş fork() ortamlarında (örn. WSL2 + Defender) 10s'lik
# timeout'a takılmadan dönmemizi sağlar.
if [[ "${SIDAR_INSTALL_VERSION_PROBE_ONLY:-0}" == "1" ]]; then
    _sidar_version_probe_requested="${INSTALL_SIDAR_VERSION:-}"
    _sidar_version_probe_pyproject=""
    if [[ -f "$SCRIPT_DIR/pyproject.toml" ]]; then
        while IFS= read -r _sidar_version_probe_line; do
            if [[ "$_sidar_version_probe_line" =~ ^[[:space:]]*version[[:space:]]*=[[:space:]]*\"([^\"]+)\" ]]; then
                _sidar_version_probe_pyproject="${BASH_REMATCH[1]}"
                break
            fi
        done < "$SCRIPT_DIR/pyproject.toml"
        unset _sidar_version_probe_line
    fi
    if [[ -n "$_sidar_version_probe_requested" && -n "$_sidar_version_probe_pyproject" && "$_sidar_version_probe_requested" != "$_sidar_version_probe_pyproject" ]]; then
        fail "INSTALL_SIDAR_VERSION uyumsuz: ortam=${_sidar_version_probe_requested}, pyproject.toml=${_sidar_version_probe_pyproject}. Smoke/version probe için pyproject.toml tek doğruluk kaynağıdır."
    fi
    INSTALL_SIDAR_VERSION="${_sidar_version_probe_pyproject:-${_sidar_version_probe_requested:-}}"
    if is_blank "$INSTALL_SIDAR_VERSION"; then
        INSTALL_SIDAR_VERSION="0.0.0"
    fi
    export INSTALL_SIDAR_VERSION
    unset _sidar_version_probe_requested _sidar_version_probe_pyproject
    return 0 2>/dev/null || exit 0
fi

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

verify_install_module_hashes_if_present() {
    local hash_manifest="${SCRIPT_DIR}/MODULE_HASHES.txt"
    local embedded_manifest_file=""
    local rel_path=""
    local expected=""
    local target=""
    local actual=""
    local failures=0
    local -a mismatched_files=()

    if [[ "${SIDAR_INSTALL_TEST_MODE:-0}" == "1" && "${INSTALL_REMOTE_MODULE_HASH_BYPASS:-0}" == "1" ]]; then
        info "Test modu file:// fallback modül doğrulaması atlandı; indirilen modül listesi dosya varlığıyla doğrulanacak."
        return 0
    fi

    if [[ ! -f "$hash_manifest" && -n "${EMBEDDED_MODULE_HASHES_MANIFEST:-}" ]]; then
        embedded_manifest_file="$(mktemp "${TMPDIR:-/tmp}/sidar_module_hashes.XXXXXX")"
        EMBEDDED_MODULE_HASH_MANIFEST_TEMP_FILE="$embedded_manifest_file"
        trap 'cleanup_embedded_module_hash_manifest_temp_file' EXIT
        trap 'cleanup_embedded_module_hash_manifest_temp_file; exit 130' INT
        trap 'cleanup_embedded_module_hash_manifest_temp_file; exit 143' TERM
        printf '%s\n' "$EMBEDDED_MODULE_HASHES_MANIFEST" > "$embedded_manifest_file"
        hash_manifest="$embedded_manifest_file"
    fi

    [[ -f "$hash_manifest" ]] || return 0
    info "Kurulum modül hash manifesti bulundu, SHA256 doğrulaması yapılıyor: $hash_manifest"

    while IFS=' ' read -r expected rel_path; do
        [[ -n "${expected:-}" && -n "${rel_path:-}" ]] || continue
        target="${SCRIPT_DIR}/${rel_path}"
        if [[ ! -f "$target" && -n "${INSTALL_MODULE_DIR:-}" ]]; then
            target="${INSTALL_MODULE_DIR}/${rel_path#scripts/install_modules/}"
        fi
        if [[ ! -f "$target" ]]; then
            warn "Hash doğrulama atlandı (dosya yok): ${rel_path}"
            failures=$((failures + 1))
            mismatched_files+=("${rel_path} (eksik dosya)")
            continue
        fi
        actual="$(compute_sha256 "$target")"
        if [[ "$actual" != "$expected" ]]; then
            warn "Hash uyuşmazlığı: ${rel_path} (beklenen=${expected}, mevcut=${actual})"
            failures=$((failures + 1))
            mismatched_files+=("${rel_path}")
        fi
    done < <(awk 'NF>=2 && $1 !~ /^#/ {print $1, $2}' "$hash_manifest")

    if (( failures > 0 )); then
        local manifest_source="MODULE_HASHES.txt (${hash_manifest})"
        if [[ -n "$embedded_manifest_file" ]]; then
            manifest_source="install_sidar.sh içine gömülü EMBEDDED_MODULE_HASHES_MANIFEST"
        fi

        local installer_branch="${SIDAR_BOOTSTRAP_CLONE_REF:-${SIDAR_REPO_BRANCH:-main}}"
        local installer_repo="${SIDAR_BOOTSTRAP_CLONE_URL:-${SIDAR_REPO_URL:-https://github.com/niluferbagevi-gif/Sidar.git}}"
        local clone_branch="bilinmiyor"
        local clone_remote="bilinmiyor"
        if command -v git >/dev/null 2>&1 && [[ -d "${SCRIPT_DIR}/.git" ]]; then
            clone_branch="$(git -C "$SCRIPT_DIR" rev-parse --abbrev-ref HEAD 2>/dev/null || echo bilinmiyor)"
            clone_remote="$(git -C "$SCRIPT_DIR" remote get-url origin 2>/dev/null || echo bilinmiyor)"
        fi

        local mismatched_csv=""
        if (( ${#mismatched_files[@]} > 0 )); then
            local _ifs_old="$IFS"
            IFS=', '
            mismatched_csv="${mismatched_files[*]}"
            IFS="$_ifs_old"
        fi

        local scope_hint
        if (( failures == 1 )); then
            scope_hint="Yalnızca tek dosyada uyuşmazlık var: bu, ilgili modül güncellenirken install_sidar.sh içindeki gömülü manifestin güncellenmemiş olduğunun klasik göstergesidir."
        else
            scope_hint="${failures} dosyada uyuşmazlık var: birden çok modül değiştiği için scripts/sync_install_module_hashes.sh manifesti tek adımda tazeler."
        fi

        if [[ "${ALLOW_UNVERIFIED_REMOTE_SCRIPTS:-0}" == "1" ]]; then
            warn "Kurulum modül hash doğrulamasında ${failures} hata bulundu; ALLOW_UNVERIFIED_REMOTE_SCRIPTS=1 nedeniyle devam ediliyor. Uyumsuz modüller: ${mismatched_csv} (manifest=${manifest_source}, installer=${installer_branch}, clone=${clone_branch})."
        else
            fail "Kurulum modül hash doğrulaması başarısız (${failures} hata).

Karşılaştırma:
  • Manifest kaynağı: ${manifest_source}
  • Beklenen (raw installer):   repo=${installer_repo}, branch=${installer_branch}
  • Mevcut (klonlanmış repo):   repo=${clone_remote}, branch=${clone_branch}
  • Uyumsuz modüller (${failures}): ${mismatched_csv}

${scope_hint}

Bu hata genellikle scripts/install_modules altındaki bir dosya değiştirilip
install_sidar.sh içindeki gömülü manifest güncellenmeden merge edildiğinde
oluşur. Çözüm:
  1) Repo'da scripts/sync_install_module_hashes.sh çalıştırıp PR/commit'i
     güncel hashlerle yenileyin (önerilen).
  2) Geçici/test kullanım için, risk kabulüyle:
       ALLOW_UNVERIFIED_REMOTE_SCRIPTS=1 bash install_sidar.sh ...
     (modül kodu doğrulanmadığından yalnızca güvenilir ortamlarda yapın).

Geçersiz modül yüklemeyi önlemek için kurulum durduruldu."
        fi
    else
        ok "Kurulum modül hash doğrulaması başarılı."
    fi

    if [[ -n "$embedded_manifest_file" ]]; then
        cleanup_embedded_module_hash_manifest_temp_file
        trap - EXIT INT TERM
    fi
}

if [[ "${SIDAR_INSTALL_TEST_MODE:-0}" == "1" && "${SIDAR_INSTALL_ABORT_AFTER_HASH_VERIFY:-0}" != "1" && "${BASH_SOURCE[0]}" != "$0" ]]; then
    info "SIDAR_INSTALL_TEST_MODE=1 source akışı: modül hash doğrulaması atlandı; fonksiyon modülleri yüklenmeye devam edecek."
else
    verify_install_module_hashes_if_present
fi
if [[ "${SIDAR_INSTALL_ABORT_AFTER_HASH_VERIFY:-0}" == "1" ]]; then
    if [[ "${core_manifest_status:-0}" == "2" ]]; then
        warn "SIDAR_INSTALL_ABORT_AFTER_HASH_VERIFY=1 ancak çekirdek manifest doğrulaması repo senkronizasyonu sonrasına ertelendi; başarılı erken çıkış yapılmayacak."
        if { [[ "${SIDAR_INSTALL_TEST_MODE:-0}" != "1" ]] || [[ "${SIDAR_INSTALL_ALLOW_BOOTSTRAP_IN_TEST_MODE:-0}" == "1" ]]; } && command -v git >/dev/null 2>&1; then
            bootstrap_clone_and_reexec
        fi
        fail "SIDAR_INSTALL_ABORT_AFTER_HASH_VERIFY=1 ancak çekirdek manifest doğrulaması repo senkronizasyonu sonrasına ertelendi. Çekirdek manifest doğrulanmadan başarılı çıkılamaz."
    fi
    info "SIDAR_INSTALL_ABORT_AFTER_HASH_VERIFY=1; hash doğrulaması sonrası erken çıkış."
    exit 0
fi
validate_install_utility_modules
sidar_source_install_utils "install_remediation.sh" "ux.sh"
sidar_source_install_utils \
    "wsl_integration_autofix.sh" \
    "wsl_gpu_preflight.sh" \
    "wsl_host.sh" \
    "gpu_utils.sh" \
    "installer_hash_guard.sh" \
    "remote_script.sh" \
    "python_env.sh" \
    "database_url.sh" \
    "db_credentials.sh" \
    "env_utils.sh" \
    "env_secrets.sh" \
    "services_docker.sh" \
    "ollama_models.sh" \
    "playwright_ubuntu_override.sh"
SIDAR_INSTALL_REQUESTED_VERSION="${INSTALL_SIDAR_VERSION:-}"
INSTALL_SIDAR_VERSION="$(resolve_install_sidar_version)"
if [[ -n "$SIDAR_INSTALL_REQUESTED_VERSION" && "$INSTALL_SIDAR_VERSION" != "0.0.0" && "$SIDAR_INSTALL_REQUESTED_VERSION" != "$INSTALL_SIDAR_VERSION" ]]; then
    fail "INSTALL_SIDAR_VERSION uyumsuz: ortam=${SIDAR_INSTALL_REQUESTED_VERSION}, pyproject.toml=${INSTALL_SIDAR_VERSION}. Kurulum sürümü pyproject.toml ile senkron kalmalıdır; ortam değişkenini kaldırın veya pyproject.toml sürümüyle eşitleyin."
fi
if is_blank "$INSTALL_SIDAR_VERSION"; then
    info "INSTALL_SIDAR_VERSION boş çözüldü; güvenli fallback sürümü kullanılacak."
    warn "Installer sürümü pyproject.toml/sidar_version.py üzerinden okunamadı; INSTALL_SIDAR_VERSION=0.0.0 olarak ayarlanıyor."
    INSTALL_SIDAR_VERSION="0.0.0"
fi
export INSTALL_SIDAR_VERSION
unset SIDAR_INSTALL_REQUESTED_VERSION

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

cleanup_temp_install_modules_if_needed() {
    local exit_code="${1:-0}"
    local keep_temp_raw="${SIDAR_KEEP_TEMP_MODULES:-0}"
    keep_temp_raw="$(echo "$keep_temp_raw" | tr '[:upper:]' '[:lower:]' | tr -d '[:space:]')"
    if [[ "${KEEP_TEMP_MODULES:-false}" == "true" || "$keep_temp_raw" == "1" || "$keep_temp_raw" == "true" || "$keep_temp_raw" == "yes" ]]; then
        [[ -n "${INSTALL_HELPERS_TEMP_DIR:-}" && -d "$INSTALL_HELPERS_TEMP_DIR" ]] && info "Geçici modül dizini korunuyor (debug): $INSTALL_HELPERS_TEMP_DIR"
        return 0
    fi

    if [[ "$exit_code" -ne 0 ]]; then
        [[ -n "${INSTALL_HELPERS_TEMP_DIR:-}" && -d "$INSTALL_HELPERS_TEMP_DIR" ]] && warn "Kurulum hata ile sonlandı (exit=${exit_code}); debug için geçici modül dizini korunuyor: $INSTALL_HELPERS_TEMP_DIR"
        warn "İsterseniz sonraki çalıştırmada --keep-temp-modules veya SIDAR_KEEP_TEMP_MODULES=1 kullanabilirsiniz."
        return 0
    fi

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

# shellcheck disable=SC2154
trap 'sidar_exit_code=$?; relocate_log_file_if_needed || true; if declare -F sidar_phase06_cleanup_pre_service_smoke_log >/dev/null 2>&1; then sidar_phase06_cleanup_pre_service_smoke_log || true; fi; cleanup_temp_install_modules_if_needed "$sidar_exit_code" || true' EXIT

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

# ── İndirme / Docker CLI / WSL path yardımcıları ─────────────────────────────
# Remote script, Docker CLI ve Windows path yardımcıları scripts/install_modules/phases/03_system.sh içinden yüklenir.

# ── Docker / PostgreSQL servis yardımcıları ───────────────────────────────────
# Servis, volume ve DB auth yardımcıları scripts/install_modules/phases/06_services.sh içinden yüklenir.

# ── Argümanlar ────────────────────────────────────────────────────────────────
# CLI defaults, argument parsing, and environment normalization live in a
# dedicated facade module so install_sidar.sh can focus on bootstrap + dispatch.
# shellcheck source=scripts/install_modules/install_cli.sh
source "${INSTALL_MODULE_DIR}/install_cli.sh"
sidar_parse_install_cli "$@"

# ── Sabitler ──────────────────────────────────────────────────────────────────
refresh_install_sidar_version_from_repo() {
    local refreshed_version=""
    refreshed_version="$(resolve_install_sidar_version)"
    INSTALL_SIDAR_VERSION="${refreshed_version:-0.0.0}"
    if is_blank "$INSTALL_SIDAR_VERSION"; then
        info "Repo yenileme sonrası INSTALL_SIDAR_VERSION boş çözüldü; güvenli fallback sürümü kullanılacak."
        warn "Installer sürümü repo kaynaklarından okunamadı; INSTALL_SIDAR_VERSION=0.0.0 olarak ayarlanıyor."
        INSTALL_SIDAR_VERSION="0.0.0"
    fi
    export INSTALL_SIDAR_VERSION
}

PYTHON_VERSION="3.11"
if [[ -f "$SCRIPT_DIR/.python-version" ]]; then
    PYTHON_VERSION="$(tr -d '[:space:]' < "$SCRIPT_DIR/.python-version")"
fi
if [[ "$PYTHON_VERSION" != "3.11" ]]; then
    fail ".python-version değeri yalnızca 3.11 olmalıdır. Güncel değer: ${PYTHON_VERSION}"
fi
# shellcheck disable=SC2034  # retained for downstream phase/default URL hooks.
DEFAULT_DATABASE_URL=""
# Repo kaynağını override etmek için (fork/organizasyon):
#   SIDAR_REPO_URL=https://github.com/<org>/Sidar.git ./install_sidar.sh
# Örnek: export SIDAR_REPO_URL=https://github.com/<org>/Sidar.git
REPO_URL="${SIDAR_REPO_URL:-${REPO_URL:-https://github.com/niluferbagevi-gif/Sidar}}"
TARGET_DIR="$HOME/Sidar"
# shellcheck disable=SC2034  # scripts/install_modules/phases/04_workspace.sh reads this sourced state.
REQUIRED_DIRS=(data logs temp sessions data/rag data/lora_adapters data/continuous_learning)
# shellcheck disable=SC2034  # used by offline bundle flows when modules are sourced.
OFFLINE_PACKAGES_DIR_DEFAULT_NAME="offline_packages"

# Context/helper seçim ve banner yardımcıları scripts/install_modules/phases/01_context.sh içinden yüklenir.

# GPU stress dotenv yardımcıları scripts/install_modules/phases/03_system.sh içinden yüklenir.

# .env dosya okuma yardımcıları scripts/install_modules/utils/env_utils.sh içinden yüklenir.

# Ollama URL ve host tanı yardımcıları scripts/install_modules/phases/09_ollama_models.sh içinden yüklenir.

# ── 0. GitHub deposunu hazırla / güncelle ────────────────────────────────────
# Repo/Helm bootstrap yardımcıları scripts/install_modules/phases/02_repo.sh içinden yüklenir.

# ── Sistem / donanım / NVIDIA yardımcıları ───────────────────────────────────
# Sistem bağımlılığı ve GPU yardımcıları scripts/install_modules/phases/03_system.sh içinden yüklenir.

# ── 4. uv CLI kurulumu / güncelleme ──────────────────────────────────────────
# Python/uv environment helpers are sourced from scripts/install_modules/utils/python_env.sh.
# Keep that module as the single source of truth; do not redefine them inline here.

# ── 6. Playwright tarayıcı motorları ─────────────────────────────────────────
# Playwright browser installation helpers live in scripts/install_modules/phases/13_playwright.sh.

# ── 7. React Web UI bağımlılıkları ve build ──────────────────────────────────
# React frontend setup helpers live in scripts/install_modules/phases/14_react.sh.


# ── 8. WSL2 Ses Desteği Kurulumu ─────────────────────────────────────────────
# WSL2 ses yardımcıları scripts/install_modules/phases/05_frontend.sh içinden yüklenir.
# WSL/audio kontratı: processors=__SIDAR_WSL_PROCESSORS__ şablonu 05_frontend.sh içinde korunur.
# WSL/audio kontratı: kernelCommandLine=__SIDAR_WSL_KERNEL_COMMAND_LINE__ şablonu 05_frontend.sh içinde korunur.
# WSL/audio kontratı: [experimental] bölümü 05_frontend.sh içindeki .wslconfig şablonunda korunur.
# WSL/audio kontratı: sparseVhd=__SIDAR_WSL_SPARSE_VHD__, _detect_host_processors, kernelCommandLine=${target_kernel_command_line} ve sparseVhd=${target_sparse_vhd} davranışları 05_frontend.sh içinde korunur.

# ── 9. Dizin / VS Code çalışma alanı yardımcıları ───────────────────────────
# Workspace yardımcıları scripts/install_modules/phases/04_workspace.sh içinden yüklenir.

# ── 10. .env dosyası ──────────────────────────────────────────────────────────
# .env / secret senkronizasyon yardımcıları scripts/install_modules/phases/08_env.sh içinden yüklenir.

# ── 11. Ollama modelleri ─────────────────────────────────────────────────────
# Ollama model hazırlık yardımcıları scripts/install_modules/phases/09_ollama_models.sh içinden yüklenir.

# ── 12. Alembic migrasyonları ────────────────────────────────────────────────
# Migrasyon ve RAG seed yardımcıları scripts/install_modules/phases/12_alembic.sh içinden yüklenir.

# ── 13-14. CUDA / Smoke / CI doğrulamaları ───────────────────────────────────
# Kurulum doğrulama yardımcıları scripts/install_modules/phases/10_validation.sh içinden yüklenir.
# Smoke gate kontratı: WSL2 ortamında smoke bash helper timeout değeri 180 saniyeye yükseltildi.
# Smoke gate kontratı: export SIDAR_INSTALL_SMOKE_BASH_TIMEOUT=180 davranışı 10_validation.sh içinde korunur.

# ── 15. Özet ─────────────────────────────────────────────────────────────────
# Özet ve kapanış yardımcıları scripts/install_modules/phases/07_finish.sh içinden yüklenir.

# ── Post-install servis / runtime / alt komut yardımcıları ───────────────────
# Post-install yardımcıları scripts/install_modules/phases/11_post_install.sh içinden yüklenir.

# ── Ana Akış ─────────────────────────────────────────────────────────────────
# shellcheck source=scripts/install_modules/install_dispatcher.sh
source "${INSTALL_MODULE_DIR}/install_dispatcher.sh"

main() {
    sidar_dispatch_install_phases "$@"
}

if [[ "${SIDAR_INSTALL_TEST_MODE:-0}" != "1" ]]; then
    main "$@"
fi
