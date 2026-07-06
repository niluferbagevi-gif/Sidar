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

    if declare -F sidar_handle_install_failure >/dev/null 2>&1; then
        sidar_handle_install_failure "$exit_code" "$failed_line" "$failed_cmd" "ERR trap" || true
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

    INSTALL_SIDAR_VERSION="${INSTALL_SIDAR_VERSION:-}"
    if [[ -z "$INSTALL_SIDAR_VERSION" && -f "${_sidar_probe_dir}/pyproject.toml" ]]; then
        while IFS= read -r _sidar_probe_line; do
            if [[ "$_sidar_probe_line" =~ ^[[:space:]]*version[[:space:]]*=[[:space:]]*\"([^\"]+)\" ]]; then
                INSTALL_SIDAR_VERSION="${BASH_REMATCH[1]}"
                break
            fi
        done < "${_sidar_probe_dir}/pyproject.toml"
    fi
    if [[ -z "$INSTALL_SIDAR_VERSION" ]]; then
        INSTALL_SIDAR_VERSION="0.0.0"
    fi
    export INSTALL_SIDAR_VERSION
    unset _sidar_probe_source _sidar_probe_dir _sidar_probe_line
    trap - ERR
    return 0 2>/dev/null || exit 0
fi

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
SIDAR_INSTALLER_EMBEDDED_SOURCE_COMMIT="unknown"

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
656bc57f6b036d10d7d436af6819725a1ba2a2913367184a4517e309c3eec6f5  core/memory.py
1fb2f74bbca1546c225f6c7c6831b66f131806c668575acb4c852c03b32fccd2  core/multimodal.py
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
                    '  Tests/automation: --smoke-test | --skip-smoke-test | --with-integration | --ci-full | --enable-autonomous-cron | --audit' \
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
                    '  Test/otomasyon: --smoke-test | --skip-smoke-test | --with-integration | --ci-full | --enable-autonomous-cron | --audit' \
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
INSTALL_HELPERS_MODULE="${INSTALL_MODULE_DIR}/install_helpers.sh"
INSTALL_HELPERS_TEMP_DIR=""
INSTALL_MODULES_DOWNLOADED=0

INSTALL_UTILITY_MODULES=(
    "utils/install_remediation.sh"
    "utils/wsl_integration_autofix.sh"
    "utils/wsl_gpu_preflight.sh"
    "utils/gpu_utils.sh"
    "utils/remote_script.sh"
    "utils/python_env.sh"
    "utils/database_url.sh"
    "utils/db_credentials.sh"
    "utils/env_utils.sh"
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
    "${INSTALL_UTILITY_MODULES[@]}"
    "utils/wsl_integration_autofix.ps1"
    "${INSTALL_PHASE_MODULES[@]}"
)

# Bundle üretiminde scripts/tools/bundle_install_sidar.sh bu bloğu doldurur.
# Repo çalışma ağacında varsayılan olarak boş bırakılır.
read -r -d '' EMBEDDED_MODULE_HASHES_MANIFEST <<'SIDAR_MODULE_HASHES_EOF' || true
f7ccb1908ae18ba9edffa4a46fde24ba564ae28a28f63a28a200703d1349aa6a  scripts/install_modules/install_helpers.sh
7e4ecc4d6bfa1ec5ac772d598df7b21cc047a4a9b24de13a336ceff0eca8138f  scripts/install_modules/phases/01_context.sh
57e71d61437133d573eec64c81749610f5d5ce60017f9e49aa3a17c671159019  scripts/install_modules/phases/02_repo.sh
f1a116aefb1ca56c4777fb47829461a2252872ddca51e1404cac134134116c8f  scripts/install_modules/phases/03_runtime.sh
987208d953324b5186a4f56f5411f81855036b95039837592f50b6a0895a49d0  scripts/install_modules/phases/03_runtime_ollama.sh
6eb393d06184a46d7901634e1a29e3af6e247343bcbc0a79d8b5a8222ad017dd  scripts/install_modules/phases/03_system.sh
74239b350bd85a7982be8516555c76c31f59bcd09492ed6c38b2f8fdcea9a99c  scripts/install_modules/phases/04_workspace.sh
76041c983eefaf3d97b2af8cec7744edc0eaeb0f95a1f3fa3e6bc70123d3e75d  scripts/install_modules/phases/05_frontend.sh
17dcf50d846ac39184fd07276a3c63a27007ce56702b2688bdcbaaf87d45528d  scripts/install_modules/phases/06_services.sh
179f368aa1d3bd859331ddb6a9cb8e3cce1c76817ff5cbb92a7b00f01a0d716d  scripts/install_modules/phases/07_finish.sh
32e44dd98310e384e02f12227217a1c6860d7bf276325cb2d2a64fdcaacaff77  scripts/install_modules/phases/08_env.sh
a5ed55e0d24f7c50feb43a8998de3a3e9e00fee1c8012f84d3403787a58c0029  scripts/install_modules/phases/09_ollama_models.sh
25cf8992693cbe4d969f4ee9cdd89cfd08151bc86962f7f5bdf0835fcd3c20b0  scripts/install_modules/phases/10_validation.sh
d15361999ab21b0ca5e8b04fbb5f0eccfebaaaa895d882d75f627d83bddcb618  scripts/install_modules/phases/11_post_install.sh
2f4784f18bf595a953cddc29dece235b52bf1e472a096cd1e50afdb6d5403036  scripts/install_modules/phases/12_alembic.sh
41e49d3eabf9058bfb4064c0f466ce609578d720f2ac37151dfde5eb1cc3ecc1  scripts/install_modules/phases/13_playwright.sh
3091e280753087ef2a8e495eaed6330699dfa8cee1975346147bfc2f5da4c826  scripts/install_modules/phases/14_react.sh
0607926653d6e9be9957c662f48dc8db686fa51ad54ee84503ff0237c3c1290b  scripts/install_modules/utils/database_url.sh
6c455996534b5b3930bb8ff79e7f3c2b78fd7634b8f55d38ae91facaf6e57630  scripts/install_modules/utils/db_credentials.sh
61e383f4162e8f8b35a3f90f8a9ec99909940c61e296b96c866673f94b8421f4  scripts/install_modules/utils/env_utils.sh
c74184b8082b1e6792693b54a9865fd05ef33ffdcb598df3d945c2b4a580f282  scripts/install_modules/utils/gpu_utils.sh
9b0468f312ac4cfb4f5081eb1a58c128de6f9376ca0483ac1abfd14a889396fb  scripts/install_modules/utils/install_remediation.sh
addbd87b75e7678972798935cb5ad694d6cb827a4a134ac3097cc24709cbb67f  scripts/install_modules/utils/ollama_models.sh
698ebc9f4c891736131f04f8e8eea2f146944bff620fa6346d06810f360fc4ad  scripts/install_modules/utils/playwright_ubuntu_override.sh
b265ddcc242226fe9af5eb88b2b0c12f057703017487e387c33cdc15cc8cfa91  scripts/install_modules/utils/python_env.sh
9823612f2782fad09a2001f040a5777190b0a57a13f9e35e127ac2955618761e  scripts/install_modules/utils/remote_script.sh
0d2b334ad2668d1d011e7f5573841be00f46fa175711dacf739c6d87d7afc2be  scripts/install_modules/utils/wsl_gpu_preflight.sh
1e6cb5e5c4d571987986b100694c50e5f043bbe1741bb9f824cbe5807d710c09  scripts/install_modules/utils/wsl_integration_autofix.ps1
59a71da6b15017249756e9acdc3a1fe6d807c529a7ced398923bb0f81e672674  scripts/install_modules/utils/wsl_integration_autofix.sh
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
        curl -fsSL "$remote_module_url" -o "$tmp_module_path" || { rm -f "$tmp_module_path"; return 1; }
    elif command -v wget &>/dev/null; then
        wget -qO "$tmp_module_path" "$remote_module_url" || { rm -f "$tmp_module_path"; return 1; }
    else
        rm -f "$tmp_module_path"
        return 1
    fi

    if [[ "${SIDAR_INSTALL_TEST_MODE:-0}" == "1" && "$remote_module_base" == file://* ]]; then
        INSTALL_REMOTE_MODULE_HASH_BYPASS=1
        :
    else
        verify_remote_install_module_hash "$module_rel" "$tmp_module_path"
    fi
    install -m 0644 "$tmp_module_path" "$destination_path"
    rm -f "$tmp_module_path"
    info "Fallback modül indirildi: ${module_rel} -> ${destination_path}"
}

download_remote_install_modules() {
    local remote_module_base="$1"
    local destination_root="$2"
    local module_rel=""

    for module_rel in "${INSTALL_REMOTE_MODULES[@]}"; do
        download_remote_install_module "$module_rel" "$remote_module_base" "$destination_root" || return 1
    done
}

verify_reexec_installer_or_fail() {
    local next_script="$1"
    local reexec_label="$2"
    local current_sha="bilinmiyor"
    local next_sha="bilinmiyor"

    [[ -f "$next_script" ]] || fail "${reexec_label} hedef install_sidar.sh bulunamadı: $next_script"

    current_sha="$(compute_sha256 "$ORIGINAL_SCRIPT_PATH" 2>/dev/null || echo bilinmiyor)"
    next_sha="$(compute_sha256 "$next_script" 2>/dev/null || echo bilinmiyor)"

    if [[ "$current_sha" == "bilinmiyor" || "$next_sha" == "bilinmiyor" ]]; then
        fail "${reexec_label} install_sidar.sh SHA256 doğrulaması yapılamadı (mevcut=${current_sha}, hedef=${next_sha}). Güvenli re-exec için sha256sum/shasum erişimini düzeltin."
    fi

    if [[ "$current_sha" != "$next_sha" ]]; then
        if [[ "${SIDAR_INSTALL_ALLOW_STALE_REEXEC:-0}" == "1" ]]; then
            warn "${reexec_label} install_sidar.sh SHA256 farklı (mevcut=${current_sha}, hedef=${next_sha}); SIDAR_INSTALL_ALLOW_STALE_REEXEC=1 nedeniyle devam ediliyor."
            return 0
        fi
        fail "${reexec_label} install_sidar.sh SHA256 farklı (mevcut=${current_sha}, hedef=${next_sha}). Yanlış/eski installer çalıştırma riskini önlemek için re-exec durduruldu. Hedef repoyu güncelleyin ya da bilinçli olarak SIDAR_INSTALL_ALLOW_STALE_REEXEC=1 ile tekrar deneyin."
    fi
}

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
    export SIDAR_BOOTSTRAP_ORIGINAL_INSTALLER_SHA256="$raw_installer_sha"
    export SIDAR_BOOTSTRAP_CLONED_INSTALLER_SHA256="$cloned_installer_sha"
    export SIDAR_BOOTSTRAP_INSTALLER_SHA_RELATION="$installer_sha_relation"
    export SIDAR_BOOTSTRAP_RAW_INSTALLER_SOURCE_REF="$SIDAR_INSTALLER_EMBEDDED_SOURCE_REF"
    export SIDAR_BOOTSTRAP_RAW_INSTALLER_SOURCE_COMMIT="$SIDAR_INSTALLER_EMBEDDED_SOURCE_COMMIT"
    info "Bootstrap clone tamamlandı (HEAD=${clone_head}, installer_sha=${installer_sha_relation}); yerel kurulum betiği yeniden başlatılıyor."
    exec "$next_script" "${SIDAR_INSTALL_ORIGINAL_ARGS[@]}"
}

if [[ ! -f "$INSTALL_HELPERS_MODULE" ]]; then
    if [[ "${SIDAR_BUNDLE_MODE:-0}" == "1" ]]; then
        fail "SIDAR_BUNDLE_MODE=1 algılandı ancak $INSTALL_HELPERS_MODULE bulunamadı. Bundle bütünlüğünü doğrulayın ve betiği yeniden üretin."
    fi
    info "Yerel modül dosyası bulunamadı: $INSTALL_HELPERS_MODULE"

    if { [[ "${SIDAR_INSTALL_TEST_MODE:-0}" != "1" ]] || [[ "${SIDAR_INSTALL_ALLOW_HOME_REEXEC_IN_TEST_MODE:-0}" == "1" ]]; } && [[ -d "$HOME/Sidar/.git" && -f "$HOME/Sidar/install_sidar.sh" ]]; then
        info "Mevcut repo algılandı: $HOME/Sidar — kurulum buradan yeniden başlatılıyor."
        verify_reexec_installer_or_fail "$HOME/Sidar/install_sidar.sh" "Mevcut $HOME/Sidar re-exec"
        cd "$HOME/Sidar" || fail "Mevcut repo dizinine geçilemedi: $HOME/Sidar"
        exec "$HOME/Sidar/install_sidar.sh" "${SIDAR_INSTALL_ORIGINAL_ARGS[@]}"
    fi

    REMOTE_MODULE_BASE="${SIDAR_INSTALL_MODULE_BASE_URL:-}"
    if [[ -n "$REMOTE_MODULE_BASE" ]]; then
        INSTALL_HELPERS_TEMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/sidar_install_modules.XXXXXX")"
        INSTALL_MODULE_DIR="${INSTALL_HELPERS_TEMP_DIR}/install_modules"
        INSTALL_HELPERS_MODULE="${INSTALL_MODULE_DIR}/install_helpers.sh"
        download_remote_install_modules "$REMOTE_MODULE_BASE" "$INSTALL_MODULE_DIR" || fail "Fallback modül indirme başarısız: $REMOTE_MODULE_BASE"
        INSTALL_MODULES_DOWNLOADED=1
        ok "Fallback modülleri geçici dizine indirildi: $INSTALL_MODULE_DIR"
    elif { [[ "${SIDAR_INSTALL_TEST_MODE:-0}" != "1" ]] || [[ "${SIDAR_INSTALL_ALLOW_BOOTSTRAP_IN_TEST_MODE:-0}" == "1" ]]; } && command -v git >/dev/null 2>&1; then
        bootstrap_clone_and_reexec
    fi

    if [[ "${INSTALL_MODULES_DOWNLOADED:-0}" != "1" ]] && ! command -v curl &>/dev/null && ! command -v wget &>/dev/null; then
        fail "Bootstrap clone için git yok, fallback indirme için curl/wget de yok. Kurulum devam edemiyor."
    fi

    if [[ "${INSTALL_MODULES_DOWNLOADED:-0}" != "1" ]]; then
        warn "git bulunamadı; fallback olarak modüller geçici dizine indirilecek."
        INSTALL_HELPERS_TEMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/sidar_install_modules.XXXXXX")"
        INSTALL_MODULE_DIR="${INSTALL_HELPERS_TEMP_DIR}/install_modules"
        INSTALL_HELPERS_MODULE="${INSTALL_MODULE_DIR}/install_helpers.sh"
        REMOTE_MODULE_BASE="${SIDAR_INSTALL_MODULE_BASE_URL:-}"
        if [[ -z "$REMOTE_MODULE_BASE" ]]; then
            REMOTE_MODULE_BASE="$(derive_remote_module_base_from_repo "${SIDAR_REPO_URL:-https://github.com/niluferbagevi-gif/Sidar.git}" "${SIDAR_REPO_BRANCH:-main}" || true)"
        fi
        [[ -n "$REMOTE_MODULE_BASE" ]] || REMOTE_MODULE_BASE="https://raw.githubusercontent.com/niluferbagevi-gif/Sidar/main/scripts/install_modules"
        download_remote_install_modules "$REMOTE_MODULE_BASE" "$INSTALL_MODULE_DIR" || fail "Fallback modül indirme başarısız: $REMOTE_MODULE_BASE"
        INSTALL_MODULES_DOWNLOADED=1
        ok "Fallback modülleri geçici dizine indirildi: $INSTALL_MODULE_DIR"
    fi
fi
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
    INSTALL_SIDAR_VERSION="${INSTALL_SIDAR_VERSION:-}"
    if is_blank "$INSTALL_SIDAR_VERSION" && [[ -f "$SCRIPT_DIR/pyproject.toml" ]]; then
        while IFS= read -r _sidar_version_probe_line; do
            if [[ "$_sidar_version_probe_line" =~ ^[[:space:]]*version[[:space:]]*=[[:space:]]*\"([^\"]+)\" ]]; then
                INSTALL_SIDAR_VERSION="${BASH_REMATCH[1]}"
                break
            fi
        done < "$SCRIPT_DIR/pyproject.toml"
        unset _sidar_version_probe_line
    fi
    if is_blank "$INSTALL_SIDAR_VERSION"; then
        INSTALL_SIDAR_VERSION="0.0.0"
    fi
    export INSTALL_SIDAR_VERSION
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
    info "SIDAR_INSTALL_ABORT_AFTER_HASH_VERIFY=1; hash doğrulaması sonrası erken çıkış."
    exit 0
fi
validate_install_utility_modules
sidar_source_install_utils "install_remediation.sh"
sidar_source_install_utils \
    "wsl_integration_autofix.sh" \
    "wsl_gpu_preflight.sh" \
    "gpu_utils.sh" \
    "remote_script.sh" \
    "python_env.sh" \
    "database_url.sh" \
    "db_credentials.sh" \
    "env_utils.sh" \
    "ollama_models.sh" \
    "playwright_ubuntu_override.sh"
INSTALL_SIDAR_VERSION="${INSTALL_SIDAR_VERSION:-$(resolve_install_sidar_version)}"
if is_blank "$INSTALL_SIDAR_VERSION"; then
    info "INSTALL_SIDAR_VERSION boş çözüldü; güvenli fallback sürümü kullanılacak."
    warn "Installer sürümü pyproject.toml/sidar_version.py üzerinden okunamadı; INSTALL_SIDAR_VERSION=0.0.0 olarak ayarlanıyor."
    INSTALL_SIDAR_VERSION="0.0.0"
fi
export INSTALL_SIDAR_VERSION

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
# Geliştirme bağımlılıkları Sidar self-healing için standart kurulumun parçasıdır.
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
RUN_INSTALL_INTEGRATION_TESTS=false
RUN_CI_FULL_VALIDATION=false
ENABLE_AUTONOMOUS_CRON=false
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
# shellcheck disable=SC2034  # scripts/install_modules/phases/07_finish.sh reads this sourced state.
REACT_UI_STATUS="atlandı"
# shellcheck disable=SC2034  # scripts/install_modules/phases/{07_finish.sh,12_alembic.sh} read this sourced state.
MIGRATION_STATUS="atlandı"
# shellcheck disable=SC2034  # scripts/install_modules/phases/{07_finish.sh,10_validation.sh} read this sourced state.
SMOKE_TEST_STATUS="atlandı"
# shellcheck disable=SC2034  # scripts/install_modules/phases/{07_finish.sh,10_validation.sh} read this sourced state.
INTEGRATION_TEST_STATUS="atlandı"
# shellcheck disable=SC2034  # scripts/install_modules/phases/10_validation.sh reads this sourced state.
CI_FULL_VALIDATION_STATUS="atlandı"
# shellcheck disable=SC2034  # scripts/install_modules/phases/07_finish.sh reads this sourced state.
AUDIT_STATUS="atlandı"
# shellcheck disable=SC2034  # scripts/install_modules/phases/07_finish.sh reads this sourced state.
AUTONOMOUS_CRON_STATUS="atlandı"
# shellcheck disable=SC2034  # scripts/install_modules/phases/12_alembic.sh reads this sourced state.
MIGRATION_DOCKER_POLICY="auto"
# shellcheck disable=SC2034  # scripts/install_modules/phases/{10_validation.sh,11_post_install.sh} read this sourced state.
DOCKER_DB_SERVICES_STARTED=false
# shellcheck disable=SC2034  # scripts/install_modules/{phases/06_services.sh,utils/database_url.sh} read this sourced state.
DB_PASSWORD_HARDENED=false
# shellcheck disable=SC2034  # scripts/install_modules/phases/06_services.sh reads this sourced state.
POSTGRES_VOLUME_RESET_DONE=false
# shellcheck disable=SC2034  # scripts/install_modules/{phases/12_alembic.sh,utils/db_credentials.sh} read this sourced state.
PRE_HARDEN_DB_PASSWORD=""
# shellcheck disable=SC2034  # scripts/install_modules/phases/07_finish.sh reads this sourced state.
AUDIO_SESSION_RESTART_RECOMMENDED=false
# shellcheck disable=SC2034  # multiple sourced phase/util scripts read this runtime flag (e.g. 03_system.sh, 06_services.sh, gpu_utils.sh).
WSL2=false
# shellcheck disable=SC2034  # scripts/install_modules/{phases/{07_finish.sh,09_ollama_models.sh,10_validation.sh},utils/ollama_models.sh} read this sourced state.
WSLCONFIG_CHANGED=false
# shellcheck disable=SC2034  # scripts/install_modules/phases/07_finish.sh reads this sourced state.
ENV_API_KEYS_TOTAL=0
# shellcheck disable=SC2034  # scripts/install_modules/phases/07_finish.sh reads this sourced state.
ENV_API_KEYS_FILLED=0
# shellcheck disable=SC2034  # scripts/install_modules/phases/07_finish.sh reads this sourced state.
ENV_API_KEYS_MISSING=()

print_install_help() {
    if sidar_is_english_locale; then
        cat <<EOF
Usage: $0 [doctor|prepare-system|sync-deps|provision-models|smoke] [--upgrade-lock] [--i-understand-full-access] [--cpu] [--docker-only] [--runtime-mode=local|docker] [--strict-docker] [--silent] [--auto] [--mode=local|docker] [--env=development|production] [--reset-db|--no-reset-db] [--start-services|--no-start-services] [--vscode|--no-vscode] [--with-browsers|--skip-browsers] [--offline|--air-gapped] [--install-docker-cli|--skip-docker-cli] [--force-postgres-volume-cleanup] [--skip-models] [--download-models] [--build-ui] [--kubernetes] [--smoke-test|--skip-smoke-test|--with-integration|--ci-full] [--enable-autonomous-cron] [--audit] [--enable-audio] [--ci|--no-interaction|--non-interactive|--headless|--yes|-y]
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
  --with-integration / --with-integration-tests  Also run tests/integration/api after smoke tests
  --ci-full  After installation, run TEST_PROFILE=ci ./run_tests.sh --stage all (integration + E2E + benchmark)
  --enable-autonomous-cron  Opt in to an hourly autonomous_loop.sh schedule via user systemd timer or crontab
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
  --keep-temp-modules  Keep temporary installer module directory for debugging (if created)

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
    SIDAR_REPO_BRANCH=main|...    Repo branch/ref for bootstrap clone + sync (default: main)
    PYTORCH_CUDA_WHEEL_TAG=cu128  Override PyTorch CUDA wheel tag (cu124/cu126/cu128)
    PYTORCH_CUDA_INDEX_URL=https://...  Override PyTorch wheel index
    DOCKER_CLI_INSTALL=auto|always|never  Docker CLI automatic installation policy
    DOCKER_DESKTOP_READY_TIMEOUT=240  Docker Desktop startup wait timeout in seconds
    SIDAR_REQUIRE_DOCKER=1|0  Force strict Docker daemon requirement (1 = fail-fast)
    SIDAR_INSTALL_AUTO_HEAL=1|0  Enable/disable phase auto-heal + resume (default: 1)
    SIDAR_PRE_SERVICE_INSTALLER_SMOKE_GATE=1|0  Enable/disable the local-mode pre-service installer smoke gate
    SIDAR_ENABLE_AUTONOMOUS_CRON=true|false  Equivalent to --enable-autonomous-cron
    SIDAR_INSTALL_REMEDIATION_MAX_ATTEMPTS=1  Maximum auto-heal resume attempts per run
    SIDAR_KEEP_TEMP_MODULES=1|0  Keep temporary installer module directory for debugging
EOF
    else
        cat <<EOF
Kullanım: $0 [doctor|prepare-system|sync-deps|provision-models|smoke] [--upgrade-lock] [--i-understand-full-access] [--cpu] [--docker-only] [--runtime-mode=local|docker] [--strict-docker] [--silent] [--auto] [--mode=local|docker] [--env=development|production] [--reset-db|--no-reset-db] [--start-services|--no-start-services] [--vscode|--no-vscode] [--with-browsers|--skip-browsers] [--offline|--air-gapped] [--install-docker-cli|--skip-docker-cli] [--force-postgres-volume-cleanup] [--skip-models] [--download-models] [--build-ui] [--kubernetes] [--smoke-test|--skip-smoke-test|--with-integration|--ci-full] [--enable-autonomous-cron] [--audit] [--enable-audio] [--ci|--no-interaction|--non-interactive|--headless|--yes|-y]
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
  --with-integration / --with-integration-tests  Smoke sonrası tests/integration/api testlerini de çalıştır
  --ci-full  Kurulum sonunda TEST_PROFILE=ci ./run_tests.sh --stage all çalıştır (integration + E2E + benchmark)
  --enable-autonomous-cron  autonomous_loop.sh için saatlik kullanıcı systemd timer veya crontab planını opt-in kur
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
  --keep-temp-modules  Geçici kurulum modül dizinini debug için koru (oluştuysa)

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
    SIDAR_REPO_BRANCH=main|...    Bootstrap clone + sync için repo branch/ref (varsayılan: main)
    PYTORCH_CUDA_WHEEL_TAG=cu128  PyTorch CUDA wheel tag override (cu124/cu126/cu128)
    PYTORCH_CUDA_INDEX_URL=https://...  PyTorch wheel index override
    DOCKER_CLI_INSTALL=auto|always|never  Docker CLI otomatik kurulum politikası
    DOCKER_DESKTOP_READY_TIMEOUT=240  Docker Desktop hazır olma bekleme süresi (saniye)
    SIDAR_REQUIRE_DOCKER=1|0  Docker daemon zorunluluğunu fail-fast olarak uygular (1=zorunlu)
    SIDAR_INSTALL_AUTO_HEAL=1|0  Faz auto-heal + resume mantığını aç/kapat (varsayılan: 1)
    SIDAR_PRE_SERVICE_INSTALLER_SMOKE_GATE=1|0  Local modda servis öncesi installer smoke gate'i aç/kapat
    SIDAR_ENABLE_AUTONOMOUS_CRON=true|false  --enable-autonomous-cron eşdeğeri
    SIDAR_INSTALL_REMEDIATION_MAX_ATTEMPTS=1  Çalıştırma başına azami auto-heal resume denemesi
    SIDAR_KEEP_TEMP_MODULES=1|0  Geçici kurulum modül dizinini debug için korur
EOF
    fi
}

INSTALL_SUBCOMMAND="full"
# shellcheck disable=SC2034  # UPGRADE_LOCK is consumed by sourced python_env.sh install_python_deps.
for arg in "$@"; do
    case "$arg" in
        --no-dev) warn "--no-dev artık desteklenmiyor; self-healing için dev bağımlılıkları standart kurulumda kalacak." ;;
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
        --keep-temp-modules) KEEP_TEMP_MODULES=true ;;
        --helm-release=*) HELM_RELEASE_NAME="${arg#*=}" ;;
        --namespace=*) HELM_NAMESPACE="${arg#*=}" ;;
        --values=*) HELM_VALUES_FILE="${arg#*=}" ;;
        --smoke-test) RUN_SMOKE_TESTS_MODE="always" ;;
        --skip-smoke-test) RUN_SMOKE_TESTS_MODE="never" ;;
        --with-integration|--with-integration-tests) RUN_INSTALL_INTEGRATION_TESTS=true ;;
        --ci-full) RUN_CI_FULL_VALIDATION=true; NO_INTERACTION=true ;;
        --enable-autonomous-cron) ENABLE_AUTONOMOUS_CRON=true ;;
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

AUTO_INSTALL="$(normalize_bool "${AUTO_INSTALL:-false}")"
SIDAR_WSL_AUTO_UPGRADE="$(normalize_bool "${SIDAR_WSL_AUTO_UPGRADE:-false}")"
STRICT_DOCKER="$(normalize_bool "${STRICT_DOCKER:-${SIDAR_REQUIRE_DOCKER:-false}}")"
ENABLE_AUTONOMOUS_CRON="$(normalize_bool "${ENABLE_AUTONOMOUS_CRON:-${SIDAR_ENABLE_AUTONOMOUS_CRON:-false}}")"
if [[ "$AUTO_INSTALL" == "true" ]]; then
    NO_INTERACTION=true
fi

OFFLINE_MODE_RAW="$(normalize_bool "${OFFLINE_INSTALL:-${AIR_GAPPED_INSTALL:-}}")"
if [[ "$OFFLINE_MODE_RAW" == "true" ]]; then
    # shellcheck disable=SC2034  # multiple sourced phase/util scripts read this runtime flag (e.g. 02_repo.sh, utils/python_env.sh).
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
main() {
    sidar_run_install_phase "01_context" sidar_phase_initialize_context
    sidar_fail_if_wsl_integration_autofix_applied_current_session_main
    if sidar_phase_handle_early_exit; then
        return
    fi

    sidar_run_install_phase "02_repo" sidar_phase_bootstrap_repo_system
    cleanup_bootstrap_script_copy
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
