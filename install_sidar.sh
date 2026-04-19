#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════════
# Sidar AI — Kurulum Betiği (install_sidar.sh)
# Sürüm : 5.2.1
# Hedef : WSL2 / Ubuntu / Conda + NVIDIA RTX 30xx/40xx (CUDA 13.x, PyTorch cu124 fallback)
#
# Kullanım:
#   chmod +x install_sidar.sh
#   ./install_sidar.sh           # standart kurulum
#   ./install_sidar.sh --dev     # geliştirici bağımlılıklarıyla
#   ./install_sidar.sh --cpu     # GPU algılansa bile CPU zorla
#   ./install_sidar.sh --kubernetes  # Helm ile Kubernetes kurulumuna geç
# ═══════════════════════════════════════════════════════════════════════════════
set -Eeuo pipefail

# Güvenilir kaynaklar için varsayılan olarak unverified indirmelere izin ver
export ALLOW_UNVERIFIED_REMOTE_SCRIPTS="${ALLOW_UNVERIFIED_REMOTE_SCRIPTS:-1}"

# Kurulum loglarını eşzamanlı olarak terminale ve dosyaya yaz
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ORIGINAL_SCRIPT_PATH="$(readlink -f "${BASH_SOURCE[0]}")"
ORIGINAL_SCRIPT_DIR="$SCRIPT_DIR"
INITIAL_TARGET_DIR="${HOME}/Sidar"
if [[ -d "$INITIAL_TARGET_DIR" ]]; then
    LOG_DIR="$INITIAL_TARGET_DIR/logs"
else
    LOG_DIR="$SCRIPT_DIR/logs"
fi
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/install_$(date +%Y%m%d_%H%M%S).log"
exec > >(tee -i "$LOG_FILE") 2>&1

# ── Renkler ──────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; BOLD='\033[1m'; NC='\033[0m'

ok()   { echo -e "${GREEN}✅  $*${NC}" >&2; }
info() { echo -e "${BLUE}ℹ️   $*${NC}" >&2; }
warn() { echo -e "${YELLOW}⚠️   $*${NC}" >&2; }
fail() { echo -e "${RED}❌  $*${NC}" >&2; exit 1; }
step() { echo -e "\n${BOLD}${BLUE}── $* ──${NC}" >&2; }

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

trap 'relocate_log_file_if_needed || true' EXIT

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

    local docker_out=""
    local docker_rc=0
    docker_out="$(docker --version 2>&1)" || docker_rc=$?
    if [[ "$docker_rc" -ne 0 ]]; then
        if [[ "$docker_rc" -eq 135 ]] || [[ "$docker_out" == *"Bus error"* ]]; then
            warn "Docker CLI Bus error veriyor. WSL2 Docker Desktop entegrasyonunu yeniden etkinleştirip WSL'i yeniden başlatın."
        elif [[ "$docker_out" == *"Input/output error"* ]]; then
            warn "Docker CLI Input/output error veriyor. WSL mount/entegrasyon durumu bozulmuş olabilir."
        fi
        return 1
    fi

    return 0
}

download_verified_script() {
    local script_url="$1"
    local expected_sha="$2"
    local script_label="$3"
    local script_file
    script_file=$(mktemp)

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
        sleep 8
    fi

    docker info &>/dev/null
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

    if [[ "$sidar_env" == "production" ]]; then
        warn "DB parola hardening algılandı ancak SIDAR_ENV=production olduğu için PostgreSQL volume otomatik sıfırlanmadı."
        return 0
    fi

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
    if [[ "$NO_INTERACTION" != true ]]; then
        should_reset=$(prompt_yes_no_with_timeout_default_yes \
            "DB şifresi güncellendi. Eski PostgreSQL volume'leri (${existing_pg_volumes[*]}) şimdi sıfırlansın mı? [E/h] ")
    fi

    local strict_postgres_reset_on_password_change="${STRICT_POSTGRES_VOLUME_RESET_ON_PASSWORD_CHANGE:-${STRICT_POSTGRES_VOLUME_RESET:-0}}"

    case "${should_reset:-E}" in
        E|e)
            reset_attempted=true
            warn "DB parola hardening sonrası eski kimlik bilgisi riskine karşı PostgreSQL volume sıfırlanıyor: ${existing_pg_volumes[*]}"
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
            local postgres_password_changed=0
            if [[ "$DB_PASSWORD_HARDENED" == true ]]; then
                postgres_password_changed=1
            fi
            if [[ "$postgres_password_changed" == "1" ]]; then
                warn "Parola değişimi saptandı, Docker süreçleri zorla temizleniyor..."
                "${compose_cmd[@]}" down --volumes --remove-orphans >/dev/null 2>&1 || true
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
                if [[ "$postgres_password_changed" == "1" ]]; then
                    docker volume rm "$volume_name" -f >/dev/null 2>&1 || true
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
        POSTGRES_VOLUME_RESET_FAILED=false
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
            POSTGRES_VOLUME_RESET_FAILED=false
            return 0
        fi
    fi

    warn "PostgreSQL volume sıfırlama tamamlanamadı; bağlantı hatası olursa docker compose down --volumes --remove-orphans && docker volume rm sidar_postgres_data -f komutlarını çalıştırın."
    if [[ "$reset_attempted" == true ]]; then
        POSTGRES_VOLUME_RESET_FAILED=true
        if [[ "$strict_postgres_reset_on_password_change" == "1" ]]; then
            return 1
        fi
        warn "Kurulum durdurulmadan devam ediliyor (STRICT_POSTGRES_VOLUME_RESET=1 veya STRICT_POSTGRES_VOLUME_RESET_ON_PASSWORD_CHANGE=1 ayarlanırsa bu durumda fail edilir)."
        return 0
    fi
    return 0
}

wait_for_postgres_ready_after_docker_start() {
    local db_host="$1"
    local db_port="$2"
    local db_user="$3"
    local db_name="$4"
    local db_password="$5"
    local max_attempts="${6:-30}"
    local sleep_seconds="${7:-2}"

    info "PostgreSQL hazır ve erişilebilir olana kadar bekleniyor (${db_host}:${db_port}/${db_name})..."
    for ((attempt=1; attempt<=max_attempts; attempt++)); do
        if pg_isready -h "$db_host" -p "$db_port" -U "$db_user" -d "$db_name" >/dev/null 2>&1; then
            local auth_rc=0
            verify_postgres_auth "$db_host" "$db_port" "$db_user" "$db_name" "$db_password" || auth_rc=$?
            case "$auth_rc" in
                0)
                    ok "PostgreSQL erişilebilir ve kimlik doğrulaması başarılı."
                    return 0
                    ;;
                10)
                    warn "PostgreSQL parola doğrulaması başarısız: ${POSTGRES_AUTH_CHECK_ERROR:-password authentication failed}"
                    fail "PostgreSQL ayakta ancak parola doğrulaması başarısız. Eski volume/parola uyuşmazlığı nedeniyle kurulum durduruldu."
                    ;;
                2)
                    warn "PostgreSQL erişilebilir, ancak psql/asyncpg ile auth doğrulaması yapılamadı. Kurulum devam edecek."
                    return 0
                    ;;
            esac
        fi
        sleep "$sleep_seconds"
    done

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
        elif [[ ${#python_cmd[@]} -gt 0 ]]; then
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
INSTALL_DEV=false
FORCE_CPU=false
SKIP_MODELS=false
DOWNLOAD_MODELS=false
FORCE_REACT_BUILD=false
INSTALL_KUBERNETES=false
HELM_RELEASE_NAME="sidar"
HELM_NAMESPACE="sidar"
HELM_VALUES_FILE=""
RUN_SMOKE_TESTS_MODE="ask"
RUN_AUDIT=false
NO_INTERACTION=false
DOCKER_ONLY=false
ENABLE_AUDIO=false
FORCE_POSTGRES_VOLUME_CLEANUP=false
REACT_UI_STATUS="atlandı"
MIGRATION_STATUS="atlandı"
SMOKE_TEST_STATUS="atlandı"
AUDIT_STATUS="atlandı"
MIGRATION_DOCKER_POLICY="auto"
DOCKER_DB_SERVICES_STARTED=false
DB_PASSWORD_HARDENED=false
POSTGRES_VOLUME_RESET_DONE=false
POSTGRES_VOLUME_RESET_FAILED=false
PRE_HARDEN_DB_PASSWORD=""
AUDIO_SESSION_RESTART_RECOMMENDED=false
WSL2=false
WSLCONFIG_CHANGED=false
ENV_API_KEYS_TOTAL=0
ENV_API_KEYS_FILLED=0
ENV_API_KEYS_MISSING=()
for arg in "$@"; do
    case "$arg" in
        --dev)  INSTALL_DEV=true ;;
        --cpu)  FORCE_CPU=true ;;
        --kubernetes|--helm) INSTALL_KUBERNETES=true ;;
        --skip-models) SKIP_MODELS=true ;;
        --download-models) DOWNLOAD_MODELS=true ;;
        --build-ui) FORCE_REACT_BUILD=true ;;
        --ci|--no-interaction) NO_INTERACTION=true ;;
        --helm-release=*) HELM_RELEASE_NAME="${arg#*=}" ;;
        --namespace=*) HELM_NAMESPACE="${arg#*=}" ;;
        --values=*) HELM_VALUES_FILE="${arg#*=}" ;;
        --smoke-test) RUN_SMOKE_TESTS_MODE="always" ;;
        --skip-smoke-test) RUN_SMOKE_TESTS_MODE="never" ;;
        --audit) RUN_AUDIT=true ;;
        --docker-only) DOCKER_ONLY=true ;;
        --force-postgres-volume-cleanup|--force-docker-cleanup) FORCE_POSTGRES_VOLUME_CLEANUP=true ;;
        --enable-audio) ENABLE_AUDIO=true ;;
        --help|-h)
            echo "Kullanım: $0 [--dev] [--cpu] [--docker-only] [--force-postgres-volume-cleanup] [--skip-models] [--download-models] [--build-ui] [--kubernetes] [--smoke-test|--skip-smoke-test] [--audit] [--enable-audio] [--ci|--no-interaction]"
            echo "  --dev  Geliştirici bağımlılıklarını kur"
            echo "  --cpu  GPU algılansa bile CPU modunda kur"
            echo "  --docker-only  PostgreSQL/Redis'i hosta kurma, sadece Docker servislerini kullan"
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
            exit 0
            ;;
        *)      warn "Bilinmeyen argüman: $arg (--dev | --cpu | --docker-only | --force-postgres-volume-cleanup | --force-docker-cleanup | --kubernetes | --helm | --helm-release=... | --namespace=... | --values=... | --smoke-test | --skip-smoke-test | --audit | --skip-models | --download-models | --build-ui | --enable-audio | --ci | --no-interaction kabul edilir)"; exit 1 ;;
    esac
done

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
CONDA_ENV_NAME="sidar"
CONDA_PYTHON_PATH="$HOME/miniconda3/envs/$CONDA_ENV_NAME/bin/python"
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
DEFAULT_DATABASE_URL="postgresql+asyncpg://sidar:sidar@localhost:5432/sidar"
REPO_URL="https://github.com/niluferbagevi-gif/Sidar"
TARGET_DIR="$HOME/Sidar"
REQUIRED_DIRS=(data logs temp sessions data/rag data/lora_adapters data/continuous_learning)
CONDA_BASE_UPDATE_DONE=false

banner() {
    echo -e "${BOLD}${BLUE}"
    echo "╔══════════════════════════════════════════════════════════════╗"
    echo "║          Sidar AI — Kurulum Başlıyor (v5.2.1)               ║"
    echo "╚══════════════════════════════════════════════════════════════╝"
    echo -e "${NC}"
}

update_conda_base_if_available() {
    if [[ "${USE_CONDA:-false}" != true ]]; then
        return 0
    fi

    if [[ "${CONDA_BASE_UPDATE_DONE:-false}" == true ]]; then
        return 0
    fi

    info "Conda base ortamı sessiz modda güncelleniyor..."
    if conda update -n base -c defaults conda -y --quiet >/dev/null 2>&1; then
        ok "Conda base ortamı güncellendi."
    else
        warn "Conda base güncellemesi başarısız/atlanmış olabilir. Mevcut sürümle devam ediliyor."
    fi

    CONDA_BASE_UPDATE_DONE=true
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
    step "Sistem Güncelleme ve Temel Paketlerin Kurulumu"

    if command -v apt-get &>/dev/null && command -v sudo &>/dev/null; then
        info "Sistem güncelleniyor ve Linux temel paketleri kuruluyor..."
        local -a ns_source_files=()
        mapfile -t ns_source_files < <(sudo sh -c "grep -Rsl 'deb .*deb.nodesource.com/node_20.x' /etc/apt/sources.list /etc/apt/sources.list.d 2>/dev/null" || true)
        if [[ "${#ns_source_files[@]}" -gt 0 ]]; then
            info "NodeSource apt girdileri nodistro formatına normalize ediliyor..."
            local src_file=""
            for src_file in "${ns_source_files[@]}"; do
                sudo sed -E -i \
                    's#(deb(\s+\[[^]]+\])?\s+https?://deb\.nodesource\.com/node_20\.x)\s+[[:alnum:]_.-]+\s+main#\1 nodistro main#g' \
                    "$src_file"
            done
        fi

        if ! sudo DEBIAN_FRONTEND=noninteractive apt-get -o Acquire::Retries=3 update -y; then
            warn "apt update başarısız oldu. NodeSource listesi sıfırlanıp tekrar denenecek..."
            sudo rm -f /etc/apt/sources.list.d/nodesource.list
            sudo DEBIAN_FRONTEND=noninteractive apt-get -o Acquire::Retries=3 update -y
        fi
        sudo DEBIAN_FRONTEND=noninteractive apt-get -o Acquire::Retries=3 upgrade -y

        info "Gerekli temel paketler (curl, wget, git, zstd vb.) kuruluyor..."
        sudo DEBIAN_FRONTEND=noninteractive apt-get -o Acquire::Retries=3 install -y \
            curl wget git build-essential software-properties-common zstd ca-certificates gnupg \
            postgresql-client-common postgresql-client

        info "Node.js (v20.x) durumu kontrol ediliyor..."
        if command -v node &>/dev/null && node -v | grep -q "^v20"; then
            ok "Node.js 20.x zaten kurulu: $(node -v)"
        else
            info "Node.js 20.x (NodeSource nodistro) kuruluyor..."
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
                    echo "deb [signed-by=${ns_keyring}] https://deb.nodesource.com/node_20.x nodistro main" | sudo tee "$ns_repo_file" >/dev/null
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
                if command -v node &>/dev/null; then
                    warn "Sistemde node bulundu ($(node -v 2>/dev/null || echo 'sürüm alınamadı'))."
                    warn "nodejs + npm çakışmasını önlemek için apt ile npm zorla kurulmayacak."
                    if command -v npm &>/dev/null; then
                        ok "npm zaten mevcut: $(npm -v 2>/dev/null || echo 'sürüm alınamadı')"
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
    elif command -v brew &>/dev/null; then
        warn "macOS (Homebrew) ortamı tespit edildi. Paketler brew ile kuruluyor..."
        brew update
        brew install \
            curl wget git zstd node@20 ffmpeg portaudio || warn "Bazı Homebrew paketleri kurulamadı; eksikleri manuel tamamlayın."
        info "Host Redis kurulumu atlandı. Servisleri Docker Compose ile yönetmeniz önerilir."

        if brew list node@20 &>/dev/null; then
            info "Node.js 20 için brew link işlemi deneniyor..."
            brew link --overwrite --force node@20 >/dev/null 2>&1 || true
            ok "Node.js sürümü: $(node --version 2>/dev/null || echo 'sürüm alınamadı')"
        fi

        info "brew services ile host PostgreSQL/Redis başlatma adımı kaldırıldı (Docker Compose tercih ediliyor)."

        ok "Homebrew tabanlı bağımlılık kurulumu tamamlandı."
    else
        warn "apt-get veya sudo bulunamadı. Lütfen paketleri manuel kurun:"
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

    # Conda kontrolü ve otomatik Miniconda kurulumu
    MINICONDA_PREFIX="$HOME/miniconda3"

    # Önce conda.sh üzerinden PATH'e ekle (terminal yeniden başlatılmamış olabilir)
    if [[ -f "$MINICONDA_PREFIX/etc/profile.d/conda.sh" ]]; then
        # shellcheck disable=SC1091
        source "$MINICONDA_PREFIX/etc/profile.d/conda.sh"
    fi

    if command -v conda &>/dev/null; then
        USE_CONDA=true
        ok "Conda $(conda --version | cut -d' ' -f2) zaten yüklü."
    elif [[ -x "$MINICONDA_PREFIX/bin/conda" ]]; then
        # shellcheck disable=SC1091
        source "$MINICONDA_PREFIX/etc/profile.d/conda.sh"
        conda init bash >/dev/null 2>&1 || true
        USE_CONDA=true
        ok "Miniconda zaten kurulu (PATH güncellendi): $(conda --version | cut -d' ' -f2)"
    else
        warn "Conda bulunamadı. Miniconda otomatik kurulumu denenecek..."

        OS="$(uname -s)"
        ARCH="$(uname -m)"
        MINICONDA_URL=""
        MINICONDA_INSTALLER="/tmp/miniconda.sh"

        case "$OS" in
            Linux)
                case "$ARCH" in
                    x86_64) MINICONDA_URL="https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh" ;;
                    aarch64|arm64) MINICONDA_URL="https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-aarch64.sh" ;;
                esac
                ;;
            Darwin)
                case "$ARCH" in
                    x86_64) MINICONDA_URL="https://repo.anaconda.com/miniconda/Miniconda3-latest-MacOSX-x86_64.sh" ;;
                    arm64) MINICONDA_URL="https://repo.anaconda.com/miniconda/Miniconda3-latest-MacOSX-arm64.sh" ;;
                esac
                ;;
        esac

        if [[ -z "$MINICONDA_URL" ]]; then
            USE_CONDA=false
            warn "Miniconda için desteklenmeyen platform ($OS/$ARCH). uv venv fallback kullanılacak."
        elif ! command -v curl &>/dev/null; then
            USE_CONDA=false
            warn "curl bulunamadı, Miniconda indirilemedi. uv venv fallback kullanılacak."
        else
            info "Miniconda indiriliyor: $MINICONDA_URL"
            if curl -fsSL "$MINICONDA_URL" -o "$MINICONDA_INSTALLER"; then
                info "Miniconda kuruluyor: $MINICONDA_PREFIX"
                bash "$MINICONDA_INSTALLER" -b -p "$MINICONDA_PREFIX"
                rm -f "$MINICONDA_INSTALLER"

                # shellcheck disable=SC1091
                source "$MINICONDA_PREFIX/etc/profile.d/conda.sh"
                conda init bash >/dev/null 2>&1 || true
                USE_CONDA=true
                ok "Miniconda kuruldu ve conda aktif edildi: $(conda --version | cut -d' ' -f2)"
            else
                USE_CONDA=false
                warn "Miniconda indirilemedi. uv venv fallback kullanılacak."
            fi
        fi
    fi

    if [[ "$USE_CONDA" == true ]]; then
        update_conda_base_if_available
    fi

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
        elif command -v brew &>/dev/null; then
            info "Kurulum için: brew install ffmpeg"
        else
            warn "Paket yöneticisi otomatik tespit edilemedi. FFmpeg'i sisteminize manuel kurun."
        fi
    fi

    # Docker / Docker Compose (özet komutları için önerilir)
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

    # Python 3.11+ kontrolü (conda içinde olacak, sadece sistem python denetimi)
    if command -v python3 &>/dev/null; then
        PY_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null || echo "0.0")
        PY_MAJOR=$(echo "$PY_VER" | cut -d. -f1)
        PY_MINOR=$(echo "$PY_VER" | cut -d. -f2)
        if [[ "$PY_MAJOR" -ge 3 && "$PY_MINOR" -ge 11 ]]; then
            ok "Python $PY_VER (sistem)"
        else
            warn "Sistem Python'u $PY_VER — conda ortamı Python $PYTHON_VERSION ile oluşturulacak."
        fi
    fi

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
            DOWNLOADED_SCRIPT_FILE=""
            download_verified_script \
                "https://ollama.com/install.sh" \
                "${OLLAMA_INSTALL_SHA256:-}" \
                "ollama_install"
            validate_downloaded_script_file "$DOWNLOADED_SCRIPT_FILE" "ollama_install"

            info "Ollama kurulumu öncesi sudo yetkisi doğrulanıyor..."
            if [[ "$NO_INTERACTION" == true ]]; then
                sudo -n -v || fail "Ollama kurulumu için sudo yetkisi gerekli. --ci/--no-interaction modunda şifresiz sudo veya önceden doğrulanmış sudo oturumu beklenir."
            else
                sudo -v || fail "Ollama kurulumu için sudo doğrulaması başarısız oldu."
            fi

            sh "$DOWNLOADED_SCRIPT_FILE"
            rm -f "$DOWNLOADED_SCRIPT_FILE"
            ok "Ollama başarıyla kuruldu."
        else
            warn "Sudo yetkisi bulunamadı. Kurulum manuel yapılmalı: https://ollama.com"
        fi
    else
        ok "Ollama zaten kurulu."
    fi

    # Servisin anlık olarak yanıt verip vermediğini kontrol et
    OLLAMA_VERSION_URL=$(resolve_ollama_version_url "$SCRIPT_DIR/.env")
    if curl -sf "$OLLAMA_VERSION_URL" &>/dev/null; then
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

        CUDA_VERSION=$("$SMI_CMD" 2>/dev/null | grep -oP 'CUDA Version: \K[\d.]+' | head -1 || true)
        DRIVER_VER=$("$SMI_CMD" --query-gpu=driver_version --format=csv,noheader 2>/dev/null | head -1 || true)

        GPU_AVAILABLE=true
        ok "GPU     : $GPU_NAME"
        ok "VRAM    : ${VRAM_MB} MiB"
        ok "Sürücü  : $DRIVER_VER"
        ok "CUDA    : $CUDA_VERSION"

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

# ── 3. Conda ortamı oluştur / güncelle ───────────────────────────────────────
activate_conda_env_in_current_shell() {
    local env_name="$1"
    local conda_base=""

    if ! command -v conda &>/dev/null; then
        fail "conda komutu bulunamadı; ortam aktive edilemiyor."
    fi

    conda_base="$(conda info --base 2>/dev/null || true)"
    if [[ -n "$conda_base" ]] && [[ -f "$conda_base/etc/profile.d/conda.sh" ]]; then
        # shellcheck disable=SC1090
        source "$conda_base/etc/profile.d/conda.sh"
    elif [[ -x "$HOME/miniconda3/bin/conda" ]]; then
        # shellcheck disable=SC1091
        eval "$("$HOME/miniconda3/bin/conda" shell.bash hook)"
    fi

    if ! conda activate "$env_name"; then
        fail "Conda ortamı aktive edilemedi: $env_name"
    fi

    export PATH="$HOME/miniconda3/envs/$env_name/bin:$PATH"
    export CONDA_DEFAULT_ENV="$env_name"
    ok "Conda ortamı aktif edildi (current shell): $env_name"
}

setup_python_env() {
    if [[ "$USE_CONDA" == true ]]; then
        step "Conda Ortamı: $CONDA_ENV_NAME"

        info "Conda Terms of Service (TOS) otomatik kabul adımı çalıştırılıyor..."
        conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/main || true
        conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/r || true
        ok "Conda TOS kabul adımı tamamlandı (gerekliyse)."

        update_conda_base_if_available

        if conda info --envs | awk '{print $1}' | grep -Eq "^${CONDA_ENV_NAME}$"; then
            info "Mevcut conda ortamı bulundu: $CONDA_ENV_NAME — güncelleniyor..."
            conda env update -n "$CONDA_ENV_NAME" -f "$SCRIPT_DIR/environment.yml" --prune
            ok "Conda ortamı güncellendi."
        else
            info "Yeni conda ortamı oluşturuluyor: $CONDA_ENV_NAME (Python $PYTHON_VERSION)..."
            conda env create -f "$SCRIPT_DIR/environment.yml"
            ok "Conda ortamı oluşturuldu."
        fi

        CONDA_RUN=(conda run --no-capture-output --cwd "$SCRIPT_DIR" -n "$CONDA_ENV_NAME")
        if "${CONDA_RUN[@]}" python -c "import sys; print(sys.version)" >/dev/null 2>&1; then
            ok "Conda ortamı hazır: $CONDA_ENV_NAME (komutlar conda run ile çalıştırılacak)"
        else
            fail "Conda ortamı doğrulanamadı: $CONDA_ENV_NAME"
        fi

        if [[ ! -x "$CONDA_PYTHON_PATH" ]]; then
            fail "Conda ortamı oluşturuldu ancak python ikilisi bulunamadı: $CONDA_PYTHON_PATH"
        fi

        activate_conda_env_in_current_shell "$CONDA_ENV_NAME"

        if [[ "$(command -v python || true)" != "$CONDA_PYTHON_PATH" ]]; then
            warn "Aktif python conda env ile eşleşmiyor. PATH zorlanıyor: $CONDA_PYTHON_PATH"
            hash -r
        fi
    else
        step "uv venv Ortamı"
        VENV_DIR="$SCRIPT_DIR/.venv"
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
    fi
}

# ── 4. uv kurulumu / güncelleme ──────────────────────────────────────────────
setup_uv() {
    step "uv Paket Yöneticisi"
    export UV_PROGRESS_BAR=on

    if ! command -v uv &>/dev/null; then
        info "uv bulunamadı — resmi kurulum betiği ile indiriliyor..."
        DOWNLOADED_SCRIPT_FILE=""
        download_verified_script \
            "https://astral.sh/uv/install.sh" \
            "${UV_INSTALL_SHA256:-}" \
            "uv_install"
        sh "$DOWNLOADED_SCRIPT_FILE"
        rm -f "$DOWNLOADED_SCRIPT_FILE"
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

# ── 5. Python bağımlılıklarını kur ───────────────────────────────────────────
install_python_deps() {
    step "Python Bağımlılıkları Kuruluyor"

    cd "$SCRIPT_DIR"
    UV_CMD=(uv)

    local -a EXTRAS=(dev gemini anthropic openai litellm postgres telemetry rag sandbox gui browser slack voice tools aws jira teams)
    if [[ "$GPU_AVAILABLE" == true && -n "$CUDA_VERSION" ]]; then
        EXTRAS+=(gpu)
    fi

    local -a LOCK_ARGS=(--index-strategy first-match)
    local -a SYNC_ARGS=(--frozen)
    for _extra in "${EXTRAS[@]}"; do
        SYNC_ARGS+=(--extra "$_extra")
    done

    # uv.lock yönetimi: extras seti belirlendikten sonra oluştur/güncelle
    if [[ ! -f "$SCRIPT_DIR/uv.lock" ]]; then
        info "uv.lock bulunamadı — seçili extras ile oluşturuluyor..."
    else
        info "uv.lock bulundu — seçili extras ile güncelleniyor..."
    fi
    if ! "${UV_CMD[@]}" lock "${LOCK_ARGS[@]}"; then
        fail "uv lock başarısız oldu. Bağımlılık çözümleme tamamlanamadı; kurulum durduruluyor."
    fi
    ok "uv.lock güncellendi."

    if [[ "$USE_CONDA" == true ]]; then
        local uv_export_file
        uv_export_file="$(mktemp)"

        info "Conda ortamına hızlı kurulum için kilit dosyasından requirements export ediliyor (uv export)..."
        if ! "${UV_CMD[@]}" export --index-strategy first-match "${SYNC_ARGS[@]}" --no-hashes -o "$uv_export_file"; then
            rm -f "$uv_export_file"
            fail "uv export başarısız oldu. Conda için requirements dosyası üretilemedi."
        fi

        info "Bağımlılıklar conda ortamına uv pip sync ile kuruluyor..."
        if ! run_with_progress_hint "Downloading packages..." uv pip sync --python "$CONDA_PYTHON_PATH" "$uv_export_file"; then
            rm -f "$uv_export_file"
            fail "uv pip sync başarısız oldu. Conda ortamına bağımlılıklar kurulamadı."
        fi
        rm -f "$uv_export_file"
    else
        info "Bağımlılıklar senkronlanıyor (uv sync --frozen, --index-strategy first-match)..."
        if ! run_with_progress_hint "Downloading packages..." "${UV_CMD[@]}" sync --index-strategy first-match "${SYNC_ARGS[@]}"; then
            fail "uv sync başarısız oldu. Python bağımlılıkları senkronlanamadı."
        fi
    fi

    info "Sidar paketi editable modda kuruluyor (pip install -e .)..."
    if [[ "$USE_CONDA" == true ]]; then
        if ! "$CONDA_PYTHON_PATH" -m pip install -e "$SCRIPT_DIR"; then
            fail "Sidar paketi conda ortamına editable olarak kurulamadı."
        fi
    else
        if ! python -m pip install -e "$SCRIPT_DIR"; then
            fail "Sidar paketi uv/venv ortamına editable olarak kurulamadı."
        fi
    fi

    ok "Python bağımlılıkları senkronlandı."
}

# ── 6. Playwright tarayıcı motorları ─────────────────────────────────────────
install_playwright_browsers() {
    step "Playwright Tarayıcı Motorları"

    if [[ "$USE_CONDA" == true ]]; then
        PY_CMD=("${CONDA_RUN[@]}" python)
    else
        PY_CMD=(python)
    fi

    if "${PY_CMD[@]}" -c "import playwright" >/dev/null 2>&1; then
        info "Chromium ve Firefox motorları kuruluyor..."
        local _pw_log; _pw_log=$(mktemp)
        if "${PY_CMD[@]}" -m playwright install --with-deps chromium firefox >"$_pw_log" 2>&1; then
            # Zaten kurulu paketlerin "is already the newest version" satırlarını filtrele
            grep -vE 'is already the newest version|0 upgraded.*0 newly|Reading package|Building dependency|Reading state|^$' \
                "$_pw_log" || true
            ok "Playwright motorları kuruldu (chromium, firefox)."
        else
            cat "$_pw_log" >&2
            warn "Playwright motor kurulumu başarısız oldu. Manuel komut: python -m playwright install --with-deps chromium firefox"
        fi
        rm -f "$_pw_log"
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

    if ! command -v npm &>/dev/null; then
        warn "npm bulunamadı. React Web UI için Node.js + npm kurun ve şu komutları çalıştırın:"
        echo "       cd web_ui_react && npm ci && npm run build"
        REACT_UI_STATUS="npm_yok"
        return
    fi

    if command -v node &>/dev/null; then
        NODE_MAJOR="$(node -v | sed 's/^v//' | cut -d. -f1)"
        if [[ "$NODE_MAJOR" -lt 20 ]]; then
            warn "Node.js sürümü düşük: $(node -v). React build için Node.js 20+ önerilir."
            warn "Kurulum komutları: sudo DEBIAN_FRONTEND=noninteractive apt-get install -y nodejs (NodeSource repo betik tarafından otomatik ayarlanır)"
        else
            ok "Node.js sürümü uygun: $(node -v)"
        fi
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
    local win_userprofile=""
    local wslconfig_path=""
    if command -v cmd.exe &>/dev/null; then
        win_userprofile=$(cmd.exe /c "echo %UserProfile%" 2>/dev/null | tr -d '\r' | tail -n1 || true)
        if [[ "$win_userprofile" =~ ^[A-Za-z]:\\ ]]; then
            local drive_letter path_rest
            drive_letter=$(echo "$win_userprofile" | cut -d: -f1 | tr 'A-Z' 'a-z')
            path_rest=$(echo "$win_userprofile" | cut -d: -f2- | sed 's#\\#/#g')
            wslconfig_path="/mnt/${drive_letter}${path_rest}/.wslconfig"
        fi
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

    local python_path
    if [[ "$USE_CONDA" == true ]]; then
        python_path="$HOME/miniconda3/envs/$CONDA_ENV_NAME/bin/python"
    else
        python_path="$SCRIPT_DIR/.venv/bin/python"
    fi

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

    db_url=$(grep -E '^DATABASE_URL=' "$env_file" | head -n1 | cut -d= -f2- || true)
    sidar_env=$(grep -E '^SIDAR_ENV=' "$env_file" | head -n1 | cut -d= -f2- || echo "development")

    [[ -n "$db_url" ]] || return

    # Güvensiz bilinen varsayılan kimlik bilgileri (postgres:postgres vb.)
    if [[ "$db_url" =~ ^postgresql(\+asyncpg)?://([^:@/]+):([^@/]+)@(.+)$ ]]; then
        local db_user="${BASH_REMATCH[2]}"
        local db_password="${BASH_REMATCH[3]}"
        local db_host_and_name="${BASH_REMATCH[4]}"

        case "$db_password" in
            sidar|postgres|password|admin|changeme|123456)
                if [[ "$hardening_enabled" == "1" || "${FORCE_STRONG_DB_PASSWORD:-0}" == "1" ]]; then
                    PRE_HARDEN_DB_PASSWORD="$db_password"
                    local generated_password=""
                    generated_password=$(generate_secure_token 24)
                    if [[ -n "$generated_password" ]]; then
                        safe_db_url="postgresql+asyncpg://${db_user}:${generated_password}@${db_host_and_name}"
                        sed -i "s|^DATABASE_URL=.*|DATABASE_URL=${safe_db_url}|" "$env_file"
                        ok ".env: DATABASE_URL için güvenli bir veritabanı şifresi üretildi (SIDAR_ENV=${sidar_env})."

                        # Docker Compose ile çalışırken PostgreSQL container kimlik bilgileri
                        # DATABASE_URL ile senkron kalmalıdır.
                        if grep -q '^POSTGRES_PASSWORD=' "$env_file"; then
                            sed -i "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=${generated_password}|" "$env_file"
                        else
                            echo "POSTGRES_PASSWORD=${generated_password}" >> "$env_file"
                        fi
                        if grep -q '^POSTGRES_USER=' "$env_file"; then
                            sed -i "s|^POSTGRES_USER=.*|POSTGRES_USER=${db_user}|" "$env_file"
                        else
                            echo "POSTGRES_USER=${db_user}" >> "$env_file"
                        fi
                        DB_PASSWORD_HARDENED=true
                        ok ".env: POSTGRES_USER/POSTGRES_PASSWORD değerleri DATABASE_URL ile senkronize edildi."
                        warn "Docker kullanıyorsanız PostgreSQL servisini yeni şifreyle yeniden başlatın."
                        warn "Mevcut PostgreSQL volume'ü eski şifreyle initialize edildiyse yeni şifreyi kabul etmeyebilir."
                        info "Önerilen sıfırlama (GELİŞTİRME ortamı): docker compose down -v && docker compose up -d postgres redis"
                        if command -v docker &>/dev/null; then
                            local detected_pg_volume=""
                            detected_pg_volume=$(docker volume ls --format '{{.Name}}' | grep -E '(^|_)postgres_data$' | head -n1 || true)
                            if [[ -n "$detected_pg_volume" ]]; then
                                warn "Tespit edilen PostgreSQL volume: ${detected_pg_volume}"
                                info "Sadece PostgreSQL volume temizleme: docker compose down && docker volume rm ${detected_pg_volume} && docker compose up -d postgres redis"
                            fi
                        fi
                    else
                        warn ".env: Güçlü veritabanı şifresi otomatik üretilemedi. DATABASE_URL parolanızı manuel güncelleyin."
                    fi
                else
                    warn ".env: ENABLE_DB_PASSWORD_HARDENING=1 olmadığı için otomatik DB parola güçlendirme atlandı."
                    warn ".env: DATABASE_URL varsayılan/zayıf parola içeriyor (${db_user}:${db_password})."
                    warn "Parolayı manuel güncellemek isterseniz DATABASE_URL ve POSTGRES_PASSWORD alanlarını birlikte değiştirin."
                fi
                ;;
        esac
    fi
}

ensure_database_url_defaults() {
    local env_file="$1"
    local current_db_url=""

    if [[ ! -f "$env_file" ]]; then
        return
    fi

    current_db_url=$(grep -E '^DATABASE_URL=' "$env_file" | head -n1 | cut -d= -f2- || true)

    if [[ -z "$current_db_url" ]]; then
        echo "DATABASE_URL=${DEFAULT_DATABASE_URL}" >> "$env_file"
        ok ".env: DATABASE_URL varsayılan PostgreSQL DSN ile eklendi."
        return
    fi

    if [[ "$current_db_url" == sqlite* ]] && [[ "${ALLOW_SQLITE_DATABASE_URL:-0}" != "1" ]]; then
        warn ".env içinde SQLite DATABASE_URL tespit edildi: $current_db_url"
        sed -i "s|^DATABASE_URL=.*|DATABASE_URL=${DEFAULT_DATABASE_URL}|" "$env_file"
        ok ".env: DATABASE_URL PostgreSQL varsayılanına güncellendi (${DEFAULT_DATABASE_URL})."
        return
    fi

    if [[ "$current_db_url" == *lotus* ]]; then
        warn ".env içinde eski 'lotus' referansı içeren DATABASE_URL tespit edildi: $current_db_url"
        sed -i "s|^DATABASE_URL=.*|DATABASE_URL=${DEFAULT_DATABASE_URL}|" "$env_file"
        ok ".env: DATABASE_URL Sidar varsayılanına güncellendi (${DEFAULT_DATABASE_URL})."
    fi
}

ensure_rag_vector_backend_pgvector() {
    local env_file="$1"
    local current_backend=""

    if [[ ! -f "$env_file" ]]; then
        return
    fi

    current_backend=$(grep -E '^RAG_VECTOR_BACKEND=' "$env_file" | head -n1 | cut -d= -f2- || true)
    if [[ -z "$current_backend" ]]; then
        echo "RAG_VECTOR_BACKEND=pgvector" >> "$env_file"
        ok ".env: RAG_VECTOR_BACKEND=pgvector eklendi."
        return
    fi

    if [[ "$current_backend" != "pgvector" ]]; then
        sed -i 's|^RAG_VECTOR_BACKEND=.*|RAG_VECTOR_BACKEND=pgvector|' "$env_file"
        ok ".env: RAG_VECTOR_BACKEND pgvector olarak güncellendi."
    fi
}

# ── İnteraktif API Anahtarı Toplama ──────────────────────────────────────────
# Eksik API anahtarları için zenity (GUI) → whiptail (TUI) → read (fallback)
# sırasıyla denenir; kullanıcı anahtarları girdikten sonra kurulum devam eder.
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

    step "API Anahtarları Yapılandırması"
    echo ""

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
            read -r input || true
            _write_key "$mk" "$input"
        done
        echo ""
    done
    ok "API anahtar girişi tamamlandı, kurulum devam ediyor."
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
        [[ -z "$val" ]] && return 0
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
        ensure_local_service_host_defaults "$ENV_FILE"
        ensure_auto_secrets "$ENV_FILE"
        collect_api_keys_interactive "$ENV_FILE"
        report_env_api_key_status "$ENV_FILE"
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

    # Güvenlik secret'larını üret/doğrula (her iki yolda da çalışan üst-düzey fonksiyon)
    ensure_auto_secrets "$ENV_FILE"

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
}

# ── 11. Ollama modelleri ─────────────────────────────────────────────────────
download_ollama_models() {
    step "Ollama Modelleri Hazırlanıyor"
    local estimated_size_gb="~14.8 GB"
    local temp_ollama_pid=""
    cleanup_temp_ollama() {
        if [[ -n "${temp_ollama_pid:-}" ]] && kill -0 "${temp_ollama_pid:-}" >/dev/null 2>&1; then
            info "Geçici ollama serve süreci sonlandırılıyor (PID: ${temp_ollama_pid:-})..."
            kill "${temp_ollama_pid:-}" >/dev/null 2>&1 || true
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

    if [[ "$DOWNLOAD_MODELS" != true ]]; then
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

    OLLAMA_VERSION_URL=$(resolve_ollama_version_url "$SCRIPT_DIR/.env")
    OLLAMA_BASE_URL="${OLLAMA_VERSION_URL%/api/version}"
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

    ENV_FILE="$SCRIPT_DIR/.env"
    if [[ ! -f "$ENV_FILE" ]]; then
        warn ".env bulunamadı, varsayılan modeller indirilemedi."
        return
    fi

    TEXT_MOD=$(read_env_value_from_file "TEXT_MODEL" "$ENV_FILE")
    CODE_MOD=$(read_env_value_from_file "CODING_MODEL" "$ENV_FILE")
    VISION_MOD=$(read_env_value_from_file "VISION_MODEL" "$ENV_FILE")
    MULTIMODAL=$(read_env_value_from_file "ENABLE_MULTIMODAL" "$ENV_FILE")

    if [[ -z "$TEXT_MOD" ]]; then
        TEXT_MOD="llama3.1:8b"
        warn "TEXT_MODEL boş/geçersiz görünüyor, varsayılan kullanılacak: $TEXT_MOD"
    fi
    if [[ -z "$CODE_MOD" ]]; then
        CODE_MOD="qwen2.5-coder:3b"
        warn "CODING_MODEL boş/geçersiz görünüyor, varsayılan kullanılacak: $CODE_MOD"
    fi

    MODELS=("$TEXT_MOD" "$CODE_MOD" "nomic-embed-text")
    if [[ "${MULTIMODAL,,}" == "true" && -n "$VISION_MOD" ]]; then
        MODELS+=("$VISION_MOD")
    fi

    for model in "${MODELS[@]}"; do
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

    ok "Gerekli tüm modeller başarıyla hazırlandı."
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
        DB_URL=$(grep -E '^DATABASE_URL=' "$ENV_FILE" 2>/dev/null | head -n1 | cut -d= -f2- || true)
    fi

    cd "$SCRIPT_DIR"

    ALEMBIC_PYTHON=""
    if [[ "$USE_CONDA" == true ]] && [[ -n "${CONDA_PYTHON_PATH:-}" ]] && [[ -x "${CONDA_PYTHON_PATH:-}" ]]; then
        ALEMBIC_PYTHON="$CONDA_PYTHON_PATH"
    elif command -v python3 &>/dev/null; then
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

    info "DATABASE_URL: $DB_URL"

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

    if [[ "$NO_INTERACTION" == true ]]; then
        info "--ci/--no-interaction etkin: migrasyon öncesi PostgreSQL/Redis servisleri otomatik hazırlanıyor."
        start_docker_services_or_fail "${docker_compose_cmd[@]}" -- postgres redis
        DOCKER_DB_SERVICES_STARTED=true
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
            wait_for_redis_ready_after_docker_start || warn "Redis hazır kontrolü başarısız; migrasyon sonrası test akışı etkilenebilir."
            ok "Migrasyon için PostgreSQL/Redis servisleri hazırlandı."
            ;;
    esac
}

# ── 13. CUDA bağlantı testi ──────────────────────────────────────────────────
verify_torch_cuda() {
    if [[ "$GPU_AVAILABLE" == true ]]; then
        step "PyTorch CUDA Doğrulaması"
        if [[ "$USE_CONDA" == true ]]; then
            if "${CONDA_RUN[@]}" python -c "import torch; exit(0 if torch.cuda.is_available() else 1)" >/dev/null 2>&1; then
                CUDA_OK=$("${CONDA_RUN[@]}" python -c "
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
                info "GPU wheel için PyTorch yeniden kuruluyor (CUDA 12.4 arayüzü ile)..."
                "${CONDA_RUN[@]}" uv pip install torch torchvision torchaudio --reinstall --extra-index-url https://download.pytorch.org/whl/cu124

                if "${CONDA_RUN[@]}" python -c "import torch; exit(0 if torch.cuda.is_available() else 1)" >/dev/null 2>&1; then
                    ok "PyTorch CUDA başarıyla kuruldu ve GPU tanındı."
                else
                    fail "PyTorch CUDA kurulumu yine başarısız oldu. Lütfen manuel kontrol edin."
                fi
            fi
        else
            info "Conda kullanılmıyor, PyTorch CUDA kontrolü atlanıyor."
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

    if [[ "$USE_CONDA" == true ]]; then
        python_cmd=("${CONDA_RUN[@]}" python)
    elif command -v python3 &>/dev/null; then
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
    local should_run=false
    local smoke_failure_policy="${SMOKE_TEST_FAILURE_POLICY:-fail}"

    if [[ "$WSL2" == true && "$WSLCONFIG_CHANGED" == true ]]; then
        warn "WSL2 .wslconfig bu kurulumda güncellendi; smoke testler yeniden başlatma sonrasına ertelendi."
        info "PowerShell'de 'wsl --shutdown' çalıştırıp dağıtımı yeniden açtıktan sonra testleri çalıştırın:"
        echo "  python -m pytest tests/smoke --rootdir=\"$SCRIPT_DIR\" -v --no-cov"
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

    if [[ "$USE_CONDA" == true ]]; then
        if ! "${CONDA_RUN[@]}" python -c "import pytest" >/dev/null 2>&1; then
            warn "pytest bu ortamda kurulu değil. --dev ile yeniden kurup tekrar deneyin."
            SMOKE_TEST_STATUS="pytest_yok"
            return
        fi
        if "${CONDA_RUN[@]}" python -m pytest "${pytest_smoke_args[@]}"; then
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
        return
    fi

    if ! python -c "import pytest" >/dev/null 2>&1; then
        warn "pytest bu ortamda kurulu değil. --dev ile yeniden kurup tekrar deneyin."
        SMOKE_TEST_STATUS="pytest_yok"
        return
    fi
    if python -m pytest "${pytest_smoke_args[@]}"; then
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
    local -a containers=("sidar_postgres" "sidar_redis")

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

    local container_name=""
    local state=""
    for container_name in "${containers[@]}"; do
        if ! docker inspect "$container_name" >/dev/null 2>&1; then
            continue
        fi

        for _ in {1..30}; do
            state=$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$container_name" 2>/dev/null || echo "unknown")
            case "$state" in
                healthy|running)
                    ok "Container hazır: ${container_name} (${state})"
                    break
                    ;;
                exited|dead|unhealthy)
                    warn "Container sağlıksız görünüyor: ${container_name} (${state})"
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
    if [[ "$USE_CONDA" == true ]]; then
        echo -e "  2️⃣  Conda ortamını aktif et (yeni terminalde):"
        echo "       conda activate $CONDA_ENV_NAME"
    else
        echo -e "  2️⃣  Sanal ortamı aktif et (yeni terminalde):"
        echo "       source .venv/bin/activate"
    fi
    echo ""
    echo -e "  3️⃣  Arka plan servisleri durumu:"
    echo "       Servisleri manuel yönetmek isterseniz: docker compose up -d / docker compose down"
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
    echo -e "  6️⃣  Testleri çalıştır (--dev ile kurulduysa):"
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
    echo "  python github_upload.py   — projeyi GitHub'a yükle"
    if [[ "$MIGRATION_STATUS" == "tamamlandi" ]]; then
        echo "  Alembic migrasyonları kurulum sırasında tamamlandı."
    else
        echo "  $CONDA_PYTHON_PATH -m alembic upgrade head  — DB hazır olduktan sonra migrasyonu çalıştırın"
    fi
    if [[ "$SMOKE_TEST_STATUS" == "tamamlandi" ]]; then
        echo "  Smoke testler: başarılı (tests/smoke)."
    elif [[ "$SMOKE_TEST_STATUS" == "hata" ]]; then
        echo "  Smoke testler: hata var. Tekrar için: python -m pytest tests/smoke --rootdir=\"$SCRIPT_DIR\" -v --no-cov"
    else
        echo "  Smoke testler: atlandı (${SMOKE_TEST_STATUS}). Çalıştırmak için: python -m pytest tests/smoke --rootdir=\"$SCRIPT_DIR\" -v --no-cov"
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

    if [[ "$NO_INTERACTION" == true ]]; then
        info "--ci/--no-interaction etkin: Docker servisleri otomatik başlatma onayı atlandı."
        info "Gerekirse manuel çalıştırın: COMPOSE_PROFILES=$compose_profiles docker compose up -d"
        return
    fi

    echo ""
    local start_prompt="Arka plan servisleri (PostgreSQL, Redis vb.) Docker ile başlatılsın mı? [E/h] "
    local start_default="E"
    local start_docker=""
    if [[ "$DOCKER_DB_SERVICES_STARTED" == true ]]; then
        info "PostgreSQL/Redis migrasyon adımında zaten başlatıldı; kalan Docker servisleri otomatik başlatılacak."
        start_docker="E"
    else
        start_docker=$(prompt_yes_no_with_timeout_default_yes "$start_prompt")
    fi

    case "${start_docker:-$start_default}" in
        [EeYy]*)
            echo "── Docker Servis Kontrolü ──"
            if ! docker info > /dev/null 2>&1; then
                echo "⚠️ Docker motoru şu anda çalışmıyor."
                echo "ℹ️ Docker başlatılmaya çalışılıyor..."

                # WSL2 / Linux Native kontrolü (başta belirlenen WSL2 bayrağı kullanılır)
                if [[ "$WSL2" == true ]]; then
                    echo "WSL ortamı algılandı. Service üzerinden başlatılıyor..."
                    if command -v sudo &>/dev/null; then
                        sudo service docker start
                    else
                        service docker start
                    fi
                else
                    echo "Linux ortamı algılandı. Systemctl üzerinden başlatılıyor..."
                    if command -v sudo &>/dev/null; then
                        sudo systemctl start docker
                    else
                        systemctl start docker
                    fi
                fi

                # Docker'ın ayağa kalkması için biraz bekle
                sleep 5

                if ! docker info > /dev/null 2>&1; then
                    echo "❌ Docker başlatılamadı! Lütfen Docker Desktop'ı veya Docker servisini manuel olarak başlatın."
                    exit 1
                else
                    echo "✅ Docker başarıyla başlatıldı."
                fi
            else
                echo "✅ Docker motoru zaten çalışıyor."
            fi

            info "Docker Compose servisleri başlatılıyor..."
            info "Monitoring konfigürasyon dosyaları için bind-mount sanity check çalıştırılıyor..."
            validate_monitoring_mount_paths
            info "Docker Compose profili: $compose_profiles"
            if COMPOSE_PROFILES="$compose_profiles" "${docker_compose_cmd[@]}" up -d; then
                ok "Docker servisleri başarıyla başlatıldı."
            else
                warn "Docker servisleri başlatılamadı. Port çakışması veya Docker kapalı olabilir."
            fi
            ;;
        *)
            info "Docker servislerinin başlatılması atlandı. (Manuel başlatmak için: COMPOSE_PROFILES=$compose_profiles docker compose up -d)"
            ;;
    esac
}

# ── Kurulum Sonrası IDE Başlatma ─────────────────────────────────────────────
launch_ide() {
    local vscode_mode="none"
    local vscode_target_path="$SCRIPT_DIR"

    if [[ "$NO_INTERACTION" == true ]]; then
        info "--ci/--no-interaction etkin: IDE açma adımı atlandı."
        return
    fi

    if command -v code &>/dev/null; then
        vscode_mode="code-cli"
    elif [[ "$WSL2" == true ]] && command -v cmd.exe &>/dev/null; then
        if cmd.exe /c "where code" >/dev/null 2>&1; then
            vscode_mode="windows-code-cli"
            if command -v wslpath &>/dev/null; then
                vscode_target_path=$(wslpath -w "$SCRIPT_DIR")
            fi
        elif [[ -x "/mnt/c/Program Files/Microsoft VS Code/Code.exe" ]]; then
            vscode_mode="windows-code-exe"
            if command -v wslpath &>/dev/null; then
                vscode_target_path=$(wslpath -w "$SCRIPT_DIR")
            fi
        fi
    fi

    if [[ "$vscode_mode" != "none" ]]; then
        echo ""
        open_code=$(prompt_yes_no_with_timeout_default_yes "Kurulum tamamlandı. Proje VS Code ile açılsın mı? [e/H] ")
        case "${open_code:-H}" in
            [EeYy]*)
                info "VS Code açılıyor..."
                if [[ "$USE_CONDA" == true ]]; then
                    info "Not: .vscode/settings.json ile yeni entegre terminallerde '$CONDA_ENV_NAME' ortamı otomatik aktive edilir."
                fi
                case "$vscode_mode" in
                    code-cli)
                        code "$SCRIPT_DIR"
                        ;;
                    windows-code-cli)
                        cmd.exe /c code "$vscode_target_path" >/dev/null 2>&1 || warn "Windows code CLI ile VS Code başlatılamadı."
                        ;;
                    windows-code-exe)
                        "/mnt/c/Program Files/Microsoft VS Code/Code.exe" "$vscode_target_path" >/dev/null 2>&1 || warn "Code.exe ile VS Code başlatılamadı."
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

    if [[ "$USE_CONDA" == true ]]; then
        local conda_base=""
        conda_base=$(conda info --base 2>/dev/null || true)
        helper_body=$(cat <<EOF
${marker_begin}
sidar_env() {
  cd "$TARGET_DIR" || return 1
  if [[ -f "$conda_base/etc/profile.d/conda.sh" ]]; then
    # shellcheck disable=SC1091
    source "$conda_base/etc/profile.d/conda.sh"
  fi
  conda activate "$CONDA_ENV_NAME"
}
alias sidar-env='sidar_env'
${marker_end}
EOF
)
    else
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
    fi

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

# ── Ana Akış ─────────────────────────────────────────────────────────────────
main() {
    banner
    report_repo_lookup_context
    detect_environment

    if [[ "$INSTALL_KUBERNETES" == true ]]; then
        info "--kubernetes/--helm modu aktif: yerel bağımlılık kurulumu atlanacak, Helm dağıtımı yapılacak."
        deploy_with_helm
        return
    fi

    # Kritik sıra:
    # 1) Sistem bağımlılıkları (git/curl vb.)
    # 2) Repo senkronizasyonu (git clone/pull)
    # 3) Ön koşul doğrulaması (Conda/FFmpeg/Docker/Ollama)
    install_system_dependencies
    sync_repo
    cd "$SCRIPT_DIR"
    ensure_prerequisites
    detect_gpu
    setup_nvidia_docker
    if [[ "$USE_CONDA" == true ]]; then
        # Conda akışı: environment.yml içindeki uv ile devam et
        setup_python_env
        setup_uv
    else
        # uv-venv akışı: önce uv kur/güncelle, sonra venv oluştur
        setup_uv
        setup_python_env
    fi
    install_python_deps
    verify_torch_cuda
    create_directories
    # VS Code ayarları, Python yorumlayıcı yolu belli olduktan sonra erken hazırlanabilir.
    setup_vscode_workspace
    setup_react_frontend
    setup_env_file
    install_playwright_browsers
    setup_shell_activation_shortcut
    setup_wsl2_audio
    # DB migrasyonu öncesi servis hazırlığı: kullanıcı onayı bu aşamada alınır.
    prepare_docker_for_migrations
    # Önce DB migrasyonu: olası bağlantı/şema hataları sonraki adımlara geçmeden görülsün.
    run_migrations
    # Smoke testlerde Ollama modeline bağlı senaryolar olabileceği için model indirmeyi öne al.
    download_ollama_models
    run_smoke_tests
    run_test_artifact_audit
    launch_docker_services
    print_summary
    # Yeni eklenen onaylı IDE başlatma adımı
    launch_ide
    relocate_log_file_if_needed
    cleanup_bootstrap_script_copy
}

main "$@"
