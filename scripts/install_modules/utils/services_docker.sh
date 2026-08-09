#!/usr/bin/env bash
set -Eeuo pipefail
# Sidar installer Docker service orchestration helpers.

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

ensure_docker_compose_access_or_fail() {
    local -a compose_cmd=("$@")
    local docker_info_err=""
    local docker_info_err_file=""

    [[ ${#compose_cmd[@]} -gt 0 ]] || fail "Docker Compose komutu çözülemedi; servisler başlatılamıyor."
    command -v docker >/dev/null 2>&1 || fail "Docker CLI bulunamadı; servisleri başlatmak için Docker gerekli."

    docker_info_err_file="$(mktemp)"
    if docker info >/dev/null 2>"$docker_info_err_file"; then
        rm -f "$docker_info_err_file"
        return 0
    fi

    docker_info_err="$(<"$docker_info_err_file")"
    rm -f "$docker_info_err_file"

    if [[ "$docker_info_err" == *"permission denied"* || "$docker_info_err" == *"Got permission denied"* ]]; then
        if command -v sudo >/dev/null 2>&1 && sudo -n docker info >/dev/null 2>&1; then
            fail "Docker daemon erişimi bu kullanıcı için yetkisiz; sudo ile çalışıyor görünüyor. Kurulumu sudo docker compose ile sürdürmek yerine kullanıcıyı docker grubuna ekleyin (sudo usermod -aG docker ${USER:-$(id -un 2>/dev/null || echo '<user>')}) ve oturumu yenileyin; WSL2'de Docker Desktop WSL Integration açık olmalıdır."
        fi
        fail "Docker daemon socket erişim hatası (permission denied). WSL2 kullanıyorsanız Docker Desktop WSL Integration ayarını açın; Linux hostta kullanıcıyı docker grubuna ekleyip oturumu yenileyin."
    fi

    fail "Docker daemon erişilemedi; '${compose_cmd[*]} up -d' öncesi Docker Desktop/daemon hazır olmalıdır. docker info çıktısı: ${docker_info_err}"
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

    ensure_docker_compose_access_or_fail "${compose_cmd[@]}"

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

    local health_timeout_seconds="${COMPOSE_HEALTH_WAIT_TIMEOUT_SECONDS:-90}"
    local health_poll_seconds="${COMPOSE_HEALTH_WAIT_POLL_SECONDS:-2}"
    local health_deadline=0
    local now=0

    if ! [[ "$health_timeout_seconds" =~ ^[0-9]+$ ]] || (( health_timeout_seconds < 1 )); then
        health_timeout_seconds=90
    fi
    if ! [[ "$health_poll_seconds" =~ ^[0-9]+$ ]] || (( health_poll_seconds < 1 )); then
        health_poll_seconds=2
    fi

    info "Docker healthcheck senkronizasyonu başlatıldı (${services[*]}, timeout=${health_timeout_seconds}s, poll=${health_poll_seconds}s)..."
    for service_name in "${services[@]}"; do
        container_id="$("${compose_cmd[@]}" ps -q "$service_name" 2>/dev/null | head -n1 || true)"
        if [[ -z "$container_id" ]]; then
            warn "Servis için container ID alınamadı: ${service_name} (health bekleme atlandı)."
            continue
        fi

        health_deadline=$(( $(date +%s) + health_timeout_seconds ))
        while true; do
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
            now="$(date +%s)"
            if (( now >= health_deadline )); then
                break
            fi
            sleep "$health_poll_seconds"
        done

        state="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$container_id" 2>/dev/null || echo unknown)"
        if [[ "$state" != "healthy" && "$state" != "running" ]]; then
            warn "Servis health timeout: ${service_name} (son durum: ${state}, timeout=${health_timeout_seconds}s)"
            return 1
        fi
    done

    return 0
}

