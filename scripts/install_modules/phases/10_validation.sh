#!/usr/bin/env bash
# Sidar installer phase: CUDA, smoke, integration, audit and CI validation helpers.

# ── 13. CUDA bağlantı testi ──────────────────────────────────────────────────
# CUDA wheel tag selection is sourced from scripts/install_modules/utils/python_env.sh.
sync_pytorch_cuda_wheels() {
    local cuda_tag="${1:-}"
    [[ -n "$cuda_tag" ]] || cuda_tag="$(select_pytorch_cuda_wheel_tag)"
    local index_url="${PYTORCH_CUDA_INDEX_URL:-https://download.pytorch.org/whl/${cuda_tag}}"
    local -a pip_args=(
        install
        --reinstall
        --reinstall-package torch
        --index-url "$index_url"
        torch
        torchvision
        torchaudio
    )

    info "PyTorch CUDA wheel seçimi uv run python -m pip ile uygulanıyor: ${cuda_tag} (${index_url})"
    if ! uv run python -m pip "${pip_args[@]}"; then
        fail "PyTorch CUDA bağımlılıkları uv run python -m pip ile güncellenemedi (${cuda_tag})."
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

    if [[ "$WSL2" == true && -z "${SIDAR_INSTALL_SMOKE_BASH_TIMEOUT:-}" ]]; then
        export SIDAR_INSTALL_SMOKE_BASH_TIMEOUT=180
        info "WSL2 ortamında smoke bash helper timeout değeri 180 saniyeye yükseltildi (SIDAR_INSTALL_SMOKE_BASH_TIMEOUT ile override edilebilir)."
    fi

    if [[ ! -d "$smoke_dir" ]]; then
        warn "Smoke test dizini bulunamadı: $smoke_dir"
        SMOKE_TEST_STATUS="dizin_yok"
        return
    fi

    if [[ "${SIDAR_PRE_SERVICE_INSTALLER_SMOKE_GATE_STATUS:-}" == "tamamlandi" ]]; then
        pytest_smoke_args+=(--ignore="$smoke_dir/test_install_verification.py")
        info "Servis öncesi installer smoke gate test_install_verification.py dosyasını zaten doğruladı; smoke tekrarında bu dosya atlanacak."
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
        persist_run_gpu_stress_dotenv
        info "RUN_GPU_STRESS=1 zaten tanımlı; GPU stres smoke testi zorunlu çalıştırılacak."
    elif [[ "$GPU_AVAILABLE" == true ]]; then
        export RUN_GPU_STRESS=1
        persist_run_gpu_stress_dotenv
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
    verify_sidar_keys_file_permissions
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


run_install_integration_api_tests() {
    step "Kurulum Entegrasyon Testleri"

    if [[ "$RUN_INSTALL_INTEGRATION_TESTS" != true ]]; then
        info "--with-integration verilmediği için bash run_tests.sh --stage integration çalıştırılmadı."
        INTEGRATION_TEST_STATUS="atlandi_bayrak"
        return
    fi

    local run_tests_script="$SCRIPT_DIR/run_tests.sh"
    local -a integration_env=(AUTO_OPEN_ARTIFACTS=0)
    local integration_failure_policy="${INTEGRATION_TEST_FAILURE_POLICY:-fail}"

    if [[ ! -f "$run_tests_script" ]]; then
        INTEGRATION_TEST_STATUS="betik_yok"
        fail "--with-integration entegrasyon kapısı çalıştırılamadı: $run_tests_script bulunamadı."
    fi

    local env_file="$SCRIPT_DIR/.env"
    local integration_database_url=""
    local integration_postgres_password=""
    local integration_redis_url=""
    if [[ -f "$env_file" ]]; then
        integration_database_url=$(read_env_value_from_file "DATABASE_URL" "$env_file")
        integration_postgres_password=$(read_env_value_from_file "POSTGRES_PASSWORD" "$env_file")
        integration_redis_url=$(read_env_value_from_file "REDIS_URL" "$env_file")
        if [[ -z "$integration_redis_url" ]]; then
            integration_redis_url=$(read_env_value_from_file "SIDAR_REDIS_URL" "$env_file")
        fi

        if [[ -n "$integration_database_url" ]]; then
            integration_env+=("DATABASE_URL=$integration_database_url")
            info "Entegrasyon test DATABASE_URL değeri .env dosyasından yenilendi."
        fi
        if [[ -n "$integration_postgres_password" ]]; then
            integration_env+=("POSTGRES_PASSWORD=$integration_postgres_password")
        fi
        if [[ -n "$integration_redis_url" ]]; then
            integration_env+=("REDIS_URL=$integration_redis_url")
        fi
    fi

    if ! wait_for_redis_before_smoke_tests; then
        warn "Redis hazır olmadığı için entegrasyon testleri çalıştırılmadı (false-negative önleme)."
        INTEGRATION_TEST_STATUS="atlandi_redis_hazir_degil"
        return
    fi
    wait_for_core_docker_health_before_smoke_tests

    info "Kurulum entegrasyon kapısı başlıyor: bash run_tests.sh --stage integration"
    if env "${integration_env[@]}" bash "$run_tests_script" --stage integration; then
        ok "Entegrasyon testleri başarıyla geçti (run_tests.sh --stage integration)."
        INTEGRATION_TEST_STATUS="tamamlandi"
    else
        INTEGRATION_TEST_STATUS="hata"
        if [[ "$integration_failure_policy" == "warn" ]]; then
            warn "Entegrasyon testlerinde hata var. INTEGRATION_TEST_FAILURE_POLICY=warn nedeniyle kurulum devam ediyor."
        else
            fail "Entegrasyon testlerinde hata var. Tekrar için: bash run_tests.sh --stage integration"
        fi
    fi
}


run_install_frontend_quality_validation() {
    step "Frontend Kalite Kapısı"

    if [[ "$RUN_INSTALL_INTEGRATION_TESTS" != true ]]; then
        info "--with-integration verilmediği için frontend stage çalıştırılmadı. Manuel komut: RUN_FRONTEND_E2E=1 bash run_tests.sh --stage frontend"
        FRONTEND_QUALITY_STATUS="atlandi_bayrak"
        return
    fi

    local run_tests_script="$SCRIPT_DIR/run_tests.sh"
    local frontend_failure_policy="${FRONTEND_QUALITY_FAILURE_POLICY:-fail}"
    if [[ ! -f "$run_tests_script" ]]; then
        FRONTEND_QUALITY_STATUS="betik_yok"
        fail "--with-integration frontend kalite kapısı çalıştırılamadı: $run_tests_script bulunamadı."
    fi

    info "Frontend kalite kapısı başlıyor: RUN_FRONTEND_E2E=1 bash run_tests.sh --stage frontend"
    info "Bu stage web_ui_react/package.json komutlarını çalıştırır: lint, typecheck, test:coverage, test:e2e:smoke."
    if env RUN_FRONTEND_E2E=1 AUTO_OPEN_ARTIFACTS=0 bash "$run_tests_script" --stage frontend; then
        ok "Frontend kalite kapısı başarıyla geçti (run_tests.sh --stage frontend)."
        FRONTEND_QUALITY_STATUS="tamamlandi"
    else
        FRONTEND_QUALITY_STATUS="hata"
        if [[ "$frontend_failure_policy" == "warn" ]]; then
            warn "Frontend kalite kapısında hata var. FRONTEND_QUALITY_FAILURE_POLICY=warn nedeniyle kurulum devam ediyor."
        else
            fail "Frontend kalite kapısı başarısız. Tekrar için: RUN_FRONTEND_E2E=1 bash run_tests.sh --stage frontend"
        fi
    fi
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
        # shellcheck disable=SC2034  # scripts/install_modules/phases/07_finish.sh reads this sourced state.
        AUDIT_STATUS="hata"
        fail "Test artifact denetimi başarısız oldu. Boş/uygunsuz test dosyalarını düzeltip tekrar deneyin."
    fi
}

sidar_install_production_gate_required() {
    local env_choice="${AUTO_ENV_TYPE:-ask}"
    local env_file_value=""
    local production_readiness_raw=""

    production_readiness_raw="$(normalize_bool "${SIDAR_PRODUCTION_READINESS:-${PRODUCTION_READINESS:-}}")"
    [[ "$production_readiness_raw" == "true" ]] && return 0
    [[ "$env_choice" == "production" ]] && return 0

    if [[ "$env_choice" == "ask" && -f "$SCRIPT_DIR/.env" ]]; then
        env_file_value="$(read_env_value_from_file "SIDAR_ENV" "$SCRIPT_DIR/.env" | tr '[:upper:]' '[:lower:]' | tr -d '[:space:]')"
        [[ "$env_file_value" == "production" ]] && return 0
    fi

    return 1
}

sidar_install_optional_dev_full_validation_available() {
    [[ "${GPU_AVAILABLE:-false}" == true ]] || return 1
    [[ "${SMOKE_TEST_STATUS:-}" == "tamamlandi" ]] || return 1
    [[ "${NO_INTERACTION:-false}" != true ]] || return 1
    [[ "${AUTO_INSTALL:-false}" != true ]] || return 1
    [[ "${SILENT_MODE:-false}" != true ]] || return 1
    [[ -f "$SCRIPT_DIR/run_tests.sh" ]] || return 1
    return 0
}


sync_frontend_quality_status_from_test_summary() {
    local summary_frontend_lint=""
    local summary_frontend_typecheck=""
    local summary_frontend_coverage=""
    local summary_frontend_e2e=""

    if summary_frontend_lint="$(read_install_test_summary_field frontend_lint)" &&
        summary_frontend_typecheck="$(read_install_test_summary_field frontend_typecheck)" &&
        summary_frontend_coverage="$(read_install_test_summary_field frontend_coverage)" &&
        summary_frontend_e2e="$(read_install_test_summary_field frontend_e2e)" &&
        [[ "$summary_frontend_lint" == "passed" ]] &&
        [[ "$summary_frontend_typecheck" == "passed" ]] &&
        [[ "$summary_frontend_coverage" == "passed" ]] &&
        [[ "$summary_frontend_e2e" == "passed" ]]; then
        # shellcheck disable=SC2034  # scripts/install_modules/phases/07_finish.sh reads this sourced state.
        FRONTEND_QUALITY_STATUS="tamamlandi"
        info "Frontend kalite durumu artifacts/test-summary.json üzerinden tamamlandı olarak işaretlendi."
        return 0
    fi

    return 1
}

run_optional_dev_full_validation_prompt() {
    local optional_command="RUN_GPU_STRESS=1 RUN_BENCHMARKS=required RUN_FRONTEND_E2E=1 bash run_tests.sh --stage all"
    local reply=""

    if ! sidar_install_optional_dev_full_validation_available; then
        info "Development/local tam doğrulama prompt'u gösterilmedi (GPU, smoke servis doğrulaması veya etkileşimli mod koşulları sağlanmadı)."
        CI_FULL_VALIDATION_STATUS="atlandi_bayrak"
        return
    fi

    info "GPU ve smoke servis doğrulaması hazır; development tam doğrulama isteğe bağlı çalıştırılabilir."
    reply=$(prompt_yes_no_with_timeout_default_no "Kurulum sonunda tam doğrulama çalıştırılsın mı? (${optional_command}) [e/H] ")
    case "${reply:-H}" in
        [EeYy]*) ;;
        *)
            info "Development/local tam doğrulama kullanıcı tercihiyle atlandı. İsterseniz daha sonra çalıştırın: ${optional_command}"
            CI_FULL_VALIDATION_STATUS="atlandi_kullanici"
            return
            ;;
    esac

    info "Development tam doğrulama başlıyor: ${optional_command}"
    if env RUN_GPU_STRESS=1 RUN_BENCHMARKS=required RUN_FRONTEND_E2E=1 AUTO_OPEN_ARTIFACTS=0 \
        bash "$SCRIPT_DIR/run_tests.sh" --stage all; then
        ok "Development tam doğrulaması başarıyla tamamlandı (RUN_GPU_STRESS=1 run_tests.sh --stage all)."
        warn "⚠️  DEVELOPMENT VALIDATION ≠ PRODUCTION READINESS"
        echo -e "${YELLOW}   ✅ Development validation geçti: yerel geliştirme ortamı sağlıklı.${NC}"
        echo -e "${YELLOW}   ⏭️  Production readiness hâlâ çalıştırılmadı; release/merge için ayrı ve zorunlu kapıdır.${NC}"
        echo -e "${YELLOW}   Zorunlu komut: make production-readiness${NC}"
        echo -e "${YELLOW}   Eşdeğer: TEST_PROFILE=ci RUN_BENCHMARKS=required RUN_FRONTEND_E2E=1 SIDAR_PRODUCTION_READINESS=1 bash run_tests.sh --stage all${NC}"
        CI_FULL_VALIDATION_STATUS="tamamlandi"
        sync_frontend_quality_status_from_test_summary || true
    else
        CI_FULL_VALIDATION_STATUS="hata"
        warn "Development tam doğrulaması başarısız oldu. Uygulama smoke kontrolleri geçtiyse geliştirme amaçlı çalışabilir; ancak production-ready/merge kabulü için tam doğrulama başarıyla geçmelidir. Tekrar için: ${optional_command}"
    fi
}

run_install_ci_full_validation() {
    step "CI Tam Doğrulama"

    local production_gate_required=false
    if sidar_install_production_gate_required; then
        production_gate_required=true
        RUN_CI_FULL_VALIDATION=true
    fi

    if [[ "$RUN_CI_FULL_VALIDATION" != true ]]; then
        info "Development/local kurulumda run_tests.sh --stage all otomatik çalıştırılmadı; production için --production-readiness zorunlu gate olarak kullanılır."
        run_optional_dev_full_validation_prompt
        return
    fi

    local run_tests_script="$SCRIPT_DIR/run_tests.sh"
    local ci_full_failure_policy="${CI_FULL_VALIDATION_FAILURE_POLICY:-fail}"
    if [[ ! -f "$run_tests_script" ]]; then
        CI_FULL_VALIDATION_STATUS="betik_yok"
        if [[ "$production_gate_required" == true ]]; then
            fail "Production readiness gate çalıştırılamadı: tam doğrulama betiği bulunamadı ($run_tests_script)."
        fi
        warn "Tam doğrulama betiği bulunamadı: $run_tests_script"
        return
    fi

    info "Tam doğrulama başlıyor: TEST_PROFILE=ci RUN_BENCHMARKS=required RUN_FRONTEND_E2E=1 bash run_tests.sh --stage all"
    if env TEST_PROFILE=ci RUN_BENCHMARKS=required RUN_FRONTEND_E2E=1 SIDAR_PRODUCTION_READINESS=1 AUTO_OPEN_ARTIFACTS=0 \
        bash "$run_tests_script" --stage all; then
        ok "Tam CI doğrulaması başarıyla tamamlandı (run_tests.sh --stage all)."
        CI_FULL_VALIDATION_STATUS="tamamlandi"
        sync_frontend_quality_status_from_test_summary || true
    else
        CI_FULL_VALIDATION_STATUS="hata"
        if [[ "$production_gate_required" == true ]]; then
            fail "Production readiness gate başarısız. Tekrar için: TEST_PROFILE=ci RUN_BENCHMARKS=required RUN_FRONTEND_E2E=1 bash run_tests.sh --stage all"
        elif [[ "$ci_full_failure_policy" == "warn" ]]; then
            warn "Tam CI doğrulamasında hata var. CI_FULL_VALIDATION_FAILURE_POLICY=warn nedeniyle development/local kurulum devam ediyor."
        else
            fail "Tam CI doğrulamasında hata var. Tekrar için: TEST_PROFILE=ci RUN_BENCHMARKS=required RUN_FRONTEND_E2E=1 bash run_tests.sh --stage all"
        fi
    fi
}

sidar_read_coverage_fail_under() {
    local pyproject_path="$SCRIPT_DIR/pyproject.toml"
    if [[ ! -f "$pyproject_path" ]]; then
        printf 'bilinmiyor'
        return 0
    fi
    python - "$pyproject_path" <<'PY_COVERAGE_FAIL_UNDER' 2>/dev/null || printf 'bilinmiyor'
from pathlib import Path
import sys
import tomllib

path = Path(sys.argv[1])
data = tomllib.loads(path.read_text(encoding="utf-8"))
print(data.get("tool", {}).get("coverage", {}).get("report", {}).get("fail_under", "bilinmiyor"))
PY_COVERAGE_FAIL_UNDER
}

print_install_coverage_gate_note() {
    local coverage_fail_under=""
    local campaign_fail_under="${COVERAGE_FAIL_UNDER_CAMPAIGN:-100}"
    coverage_fail_under="$(sidar_read_coverage_fail_under)"
    echo ""
    echo -e "${BOLD}📈 Coverage ratchet / fail-under notu:${NC}"
    echo -e "   ${YELLOW}pyproject.toml coverage fail-under eşiği: ${coverage_fail_under}%.${NC}"
    echo -e "   ${YELLOW}Local/CI gate: pyproject.toml ratchet baseline ${coverage_fail_under}% (COVERAGE_FAIL_UNDER_LOCAL/CI veya açık COVERAGE_FAIL_UNDER ile override edilebilir).${NC}"
    echo -e "   ${YELLOW}Coverage campaign hedefi: ${campaign_fail_under}% (yalnız COVERAGE_CAMPAIGN=1 veya AUTONOMOUS_LOOP_OPERATION_PROFILE=coverage-campaign opt-in ile).${NC}"
    echo -e "   ${YELLOW}Pytest marker'ları ve warning politikası pyproject.toml içinde tanımlı; bu kalite kapısı yalnız run_tests.sh coverage akışında uygulanır.${NC}"
    echo -e "   ${YELLOW}Kurulum smoke/build adımları geçse bile tam doğrulama çalışmadıysa coverage fail-under ve ratchet devreye girmiş sayılmaz.${NC}"
    echo "   Coverage gate için: RUN_BENCHMARKS=required RUN_FRONTEND_E2E=1 bash run_tests.sh --stage all"
    echo "   Test rehberi: docs/TESTING.md (run_tests.sh PR/merge öncesi ana doğrulama yoludur)"
}

print_install_benchmark_baseline_note() {
    echo ""
    echo -e "${BOLD}📌 CI ilk çalıştırma / benchmark baseline notu:${NC}"
    echo -e "   ${YELLOW}CI production-readiness gate'i fail-closed çalışır; .benchmarks/*_baseline.json restore edilemezse normal CI baseline üretmez ve bilinçli olarak başarısız olur.${NC}"
    echo "   İlk/boş cache bootstrap sırası:"
    echo "     1. GitHub Actions → CI → Run workflow"
    echo "     2. seed_benchmark_baseline=true seçin"
    echo "     3. benchmark-baseline-seed artifact/cache oluşunca normal CI veya production-readiness gate'ini yeniden çalıştırın"
    echo "   Lokal artifact restore örneği ve ayrıntılar: docs/TESTING.md#ci-benchmark-baseline-cache-boşsa-ne-yapılır"
    echo "   Release/merge öncesi gate: TEST_PROFILE=ci RUN_BENCHMARKS=required RUN_FRONTEND_E2E=1 SIDAR_PRODUCTION_READINESS=1 bash run_tests.sh --stage all"
}

print_install_ci_parity_summary() {
    local ci_status="${CI_FULL_VALIDATION_STATUS:-atlandi_bayrak}"
    local frontend_status="${FRONTEND_QUALITY_STATUS:-atlandi_bayrak}"

    echo ""
    echo -e "${BOLD}🧩 GitHub Actions CI parite haritası:${NC}"
    echo "   CI step: Run installer shell gates                 → local: make lint && make test-shell"
    echo "   CI step: Run ShellCheck for installer/modules      → local: uv run shellcheck --severity=warning -x install_sidar.sh scripts/install_modules/**/*.sh"
    echo "   CI step: Run frontend lint/type-check/audit gate   → local: RUN_FRONTEND_E2E=1 bash run_tests.sh --stage frontend"
    echo "   CI step: Run critical/runtime smoke gates          → local: bash run_tests.sh --stage smoke"
    echo "   CI step: Run SAST gates (Bandit + pip-audit)       → local: bash run_tests.sh --stage static veya bash run_tests.sh --stage all"
    echo "   CI step: Run test suite + coverage + benchmark     → local: RUN_BENCHMARKS=required RUN_FRONTEND_E2E=1 bash run_tests.sh --stage all"
    echo "   CI step: Upload Playwright/BATS/Coverage artifacts → local: web_ui_react/playwright-report, artifacts/bats, htmlcov, web_ui_react/coverage dizinlerini kontrol edin"

    if [[ "$ci_status" == "tamamlandi" ]]; then
        echo -e "   ${GREEN}✅ Local durum: full CI parite komutu tamamlandı.${NC}"
    else
        echo -e "   ${YELLOW}⏭️  Local durum: CI'daki full test/coverage/benchmark/artifact kapsamı tamamlanmadı (${ci_status:-bilinmiyor}).${NC}"
    fi

    if [[ "$frontend_status" == "tamamlandi" ]]; then
        echo -e "   ${GREEN}✅ Frontend CI paritesi: lint/typecheck/audit/coverage/e2e smoke stage'i geçti.${NC}"
    elif [[ "$frontend_status" == "hata" ]]; then
        echo -e "   ${RED}❌ Frontend CI paritesi: frontend stage başarısız.${NC}"
    else
        echo -e "   ${YELLOW}⏭️  Frontend CI paritesi: frontend stage çalışmadı (${frontend_status:-bilinmiyor}).${NC}"
    fi
}

read_install_test_summary_field() {
    local field="$1"
    local summary_path="${TEST_SUMMARY_JSON:-${SCRIPT_DIR}/artifacts/test-summary.json}"
    [[ -f "$summary_path" ]] || return 1
    python - "$summary_path" "$field" <<'PY_SUMMARY_FIELD'
from __future__ import annotations

import json
import sys
from pathlib import Path

summary_path, field = sys.argv[1:3]
try:
    value = json.loads(Path(summary_path).read_text(encoding="utf-8"))[field]
except (OSError, KeyError, json.JSONDecodeError):
    raise SystemExit(1)

if isinstance(value, bool):
    print("true" if value else "false")
else:
    print(value)
PY_SUMMARY_FIELD
}

print_install_validation_gate_line() {
    local label="$1"
    local status="$2"
    local scope="$3"
    local retry_command="${4:-}"

    case "$status" in
        passed)
            echo -e "   ${GREEN}✅ ${label}: ${scope} GEÇTİ${NC}"
            ;;
        failed)
            if [[ -n "$retry_command" ]]; then
                echo -e "   ${RED}❌ ${label}: HATA; tekrar için ${retry_command}${NC}"
            else
                echo -e "   ${RED}❌ ${label}: HATA${NC}"
            fi
            ;;
        skipped)
            echo -e "   ${YELLOW}⏭️  ${label}: ATLANDI (${scope})${NC}"
            ;;
        *)
            echo -e "   ${YELLOW}⏭️  ${label}: DURUM BİLİNMİYOR (${status:-yok}; ${scope})${NC}"
            ;;
    esac
}

print_install_validation_coverage() {
    local smoke_status="${SMOKE_TEST_STATUS:-atlandi_bayrak}"
    local integration_status="${INTEGRATION_TEST_STATUS:-atlandi_bayrak}"
    local ci_status="${CI_FULL_VALIDATION_STATUS:-atlandi_bayrak}"
    local frontend_status="${FRONTEND_QUALITY_STATUS:-atlandi_bayrak}"
    local run_install_integration_tests="${RUN_INSTALL_INTEGRATION_TESTS:-false}"
    local gpu_available="${GPU_AVAILABLE:-false}"
    local full_coverage_reached=false
    [[ "$ci_status" == "tamamlandi" ]] && full_coverage_reached=true
    local summary_available=false
    local summary_smoke=""
    local summary_integration=""
    local summary_e2e=""
    local summary_frontend_lint=""
    local summary_frontend_typecheck=""
    local summary_frontend_coverage=""
    local summary_frontend_e2e=""
    local summary_benchmark=""
    local summary_production_ready=""
    local production_readiness_status_reported=false
    if [[ "$ci_status" == "tamamlandi" || "$ci_status" == "hata" ]] &&
        summary_smoke="$(read_install_test_summary_field smoke)" &&
        summary_integration="$(read_install_test_summary_field integration)" &&
        summary_e2e="$(read_install_test_summary_field e2e)" &&
        summary_frontend_lint="$(read_install_test_summary_field frontend_lint)" &&
        summary_frontend_typecheck="$(read_install_test_summary_field frontend_typecheck)" &&
        summary_frontend_coverage="$(read_install_test_summary_field frontend_coverage)" &&
        summary_frontend_e2e="$(read_install_test_summary_field frontend_e2e)" &&
        summary_benchmark="$(read_install_test_summary_field benchmark)" &&
        summary_production_ready="$(read_install_test_summary_field production_ready)"; then
        summary_available=true
    fi
    local production_readiness_command="TEST_PROFILE=ci RUN_BENCHMARKS=required RUN_FRONTEND_E2E=1 SIDAR_PRODUCTION_READINESS=1 bash run_tests.sh --stage all"
    local recommended_validation_command="RUN_BENCHMARKS=required RUN_FRONTEND_E2E=1 bash run_tests.sh --stage all"
    if [[ "$gpu_available" == true ]]; then
        recommended_validation_command="RUN_GPU_STRESS=1 ${recommended_validation_command}"
    fi

    echo ""
    echo -e "${BOLD}📊 Kurulum doğrulama kapsamı:${NC}"
    if [[ "$summary_available" == true ]]; then
        print_install_validation_gate_line "Smoke       " "$summary_smoke" "tests/smoke" "bash run_tests.sh --stage smoke"
        print_install_validation_gate_line "Integration " "$summary_integration" "tests/integration" "bash run_tests.sh --stage integration"
        print_install_validation_gate_line "E2E         " "$summary_e2e" "tests/e2e/{agents,cli,web}" "bash run_tests.sh --stage e2e"
        print_install_validation_gate_line "Frontend lint" "$summary_frontend_lint" "npm run lint" "bash run_tests.sh --stage frontend"
        print_install_validation_gate_line "Frontend type" "$summary_frontend_typecheck" "npm run typecheck" "bash run_tests.sh --stage frontend"
        print_install_validation_gate_line "Frontend cov " "$summary_frontend_coverage" "npm run test:coverage" "bash run_tests.sh --stage frontend"
        print_install_validation_gate_line "Frontend E2E " "$summary_frontend_e2e" "Playwright smoke" "RUN_FRONTEND_E2E=1 bash run_tests.sh --stage frontend"
        print_install_validation_gate_line "Benchmark   " "$summary_benchmark" "tests/performance" "RUN_BENCHMARKS=required bash run_tests.sh --stage all"
        if [[ "$summary_production_ready" == true ]]; then
            echo -e "   ${GREEN}✅ Production readiness: GEÇTİ${NC}"
            production_readiness_status_reported=true
        elif [[ "$ci_status" == "tamamlandi" ]] && ! sidar_install_production_gate_required; then
            echo -e "   ${YELLOW}${BOLD}⏭️  Production readiness: ÇALIŞTIRILMADI / TALEP EDİLMEDİ${NC}"
            echo -e "   ${YELLOW}   ✅ Development full validation geçti = geliştirici ortamı sağlıklı.${NC}"
            echo -e "   ${YELLOW}   ⚠️  Development validation ≠ release/merge onayı; production gate hâlâ zorunlu.${NC}"
            echo -e "   ${YELLOW}   Release/merge için tek zorunlu komut: ${production_readiness_command}${NC}"
            production_readiness_status_reported=true
        else
            echo -e "   ${YELLOW}⚠️  Production readiness: GEÇMEDİ${NC}"
            production_readiness_status_reported=true
        fi
    elif [[ "$smoke_status" == "tamamlandi" ]]; then
        echo -e "   ${GREEN}✅ Smoke:        TAMAMLANDI (kapsam: tests/smoke)${NC}"
    elif [[ "$smoke_status" == "hata" ]]; then
        echo -e "   ${RED}❌ Smoke:        HATA${NC}"
    else
        echo -e "   ${YELLOW}⏭️  Smoke:        ATLANDI (${smoke_status})${NC}"
    fi

    if [[ "$summary_available" == true ]]; then
        :
    elif [[ "$full_coverage_reached" == true ]]; then
        echo -e "   ${GREEN}✅ Integration:  TAMAMLANDI (kapsam: api/cli/db/managers/web/workflow)${NC}"
        echo -e "   ${GREEN}✅ E2E:          TAMAMLANDI (kapsam: agents/cli/web)${NC}"
        echo -e "   ${GREEN}✅ Benchmark:    TAMAMLANDI${NC}"
    else
        if [[ "$integration_status" == "tamamlandi" ]]; then
            echo -e "   ${GREEN}✅ Integration:  TAMAMLANDI (kapsam: run_tests.sh --stage integration)${NC}"
        elif [[ "$integration_status" == "hata" ]]; then
            echo -e "   ${RED}❌ Integration:  HATA; tekrar için run_tests.sh --stage integration${NC}"
        else
            echo -e "   ${YELLOW}⏭️  Integration:  ATLANDI (kapsam: run_tests.sh --stage integration → tests/integration)${NC}"
        fi
        echo -e "   ${YELLOW}⏭️  E2E:          ATLANDI (kapsam: run_tests.sh --stage e2e → tests/e2e/{agents,cli,web})${NC}"
        echo -e "   ${YELLOW}⏭️  Benchmark:    ATLANDI${NC}"
    fi

    if [[ "$summary_available" == true ]]; then
        :
    elif [[ "$frontend_status" == "tamamlandi" ]]; then
        echo -e "   ${GREEN}✅ Frontend:     LINT/TYPECHECK/COVERAGE/E2E SMOKE TAMAMLANDI${NC}"
    elif [[ "$frontend_status" == "hata" ]]; then
        echo -e "   ${RED}❌ Frontend:     LINT/TYPECHECK/COVERAGE/E2E SMOKE HATA${NC}"
    elif [[ "$run_install_integration_tests" == true ]]; then
        echo -e "   ${YELLOW}⏭️  Frontend:     ATLANDI (${frontend_status:-bilinmiyor})${NC}"
    fi

    if [[ "$ci_status" == "hata" ]]; then
        echo ""
        echo -e "   ${RED}${BOLD}❌ Tam doğrulama sonucu: HATA${NC}"
        echo -e "   ${YELLOW}   Kurulum smoke adımları geçmişse uygulama geliştirme amacıyla çalışabilir;${NC}"
        echo -e "   ${YELLOW}   ancak üretim/merge için tam doğrulama başarılı olmadan bu kurulum production-ready sayılmaz.${NC}"
        echo -e "   ${YELLOW}   Tekrar komutu: ${recommended_validation_command}${NC}"
    elif [[ "$full_coverage_reached" != true ]]; then
        echo ""
        if sidar_install_production_gate_required; then
            echo -e "   ${RED}${BOLD}⛔ PRODUCTION GATE: Tam CI/e2e/benchmark doğrulaması zorunludur.${NC}"
            echo -e "   ${RED}   Production ortamında integration/e2e/benchmark atlanmışsa kurulum production-ready sayılmaz.${NC}"
            echo -e "   ${RED}   Zorunlu gate: ${production_readiness_command}${NC}"
            if [[ "$production_readiness_status_reported" != true ]]; then
                echo "   Production readiness:      ./install_sidar.sh --production-readiness"
                echo "   Legacy CI alias:           ./install_sidar.sh --ci-full"
            fi
        else
            echo -e "   ${YELLOW}${BOLD}⚠️  KAPSAM EKSİK: Development/local kurulum tam proje doğrulaması değildir.${NC}"
            echo -e "   ${YELLOW}   Kurulum başarılı: $([[ "$smoke_status" == "hata" ]] && echo "Hayır" || echo "Evet")${NC}"
            echo -e "   ${YELLOW}   Smoke doğrulaması: $([[ "$smoke_status" == "tamamlandi" ]] && echo "Geçti" || echo "Tamamlanmadı (${smoke_status:-bilinmiyor})")${NC}"
            echo -e "   ${YELLOW}   Tam proje doğrulaması: Çalıştırılmadı${NC}"
            echo -e "   ${YELLOW}   Eksik kapsam: run_tests.sh stage all içindeki integration, e2e, benchmark, frontend, bats ve security gate sonuçları${NC}"
            echo ""
            echo -e "   ${YELLOW}${BOLD}⚠️  DEVELOPMENT UYARISI: Bu kurulum yalnızca smoke testleri (boot/GPU/import/kilit/WSL) kapsar.${NC}"
            echo -e "   ${YELLOW}   Agent orkestrasyonu, gerçek DB migrasyonları, WebSocket oturumları ve plugin sandbox'ı${NC}"
            echo -e "   ${YELLOW}   gibi kritik yollar bu aşamada DOĞRULANMADI. \"Smoke testler geçti\" mesajı, tam${NC}"
            echo -e "   ${YELLOW}   kapsamlı bir doğrulamanın yerine geçmez.${NC}"
            echo ""
            echo -e "   ${BOLD}➡️  Önerilen doğrulama komutu (duruma göre tek komut seçin):${NC}"
            echo "   Test rehberi:             docs/TESTING.md"
            echo -e "   ${BOLD}   Development tam doğrulama: ${recommended_validation_command}${NC}"
            echo "   Backend entegrasyon:       bash run_tests.sh --stage integration"
            echo "   Frontend kalite kapısı:    bash run_tests.sh --stage frontend"
            if [[ "$production_readiness_status_reported" != true ]]; then
                echo "   Production readiness:      ./install_sidar.sh --production-readiness"
                echo "   Legacy CI alias:           ./install_sidar.sh --ci-full"
            fi
        fi
    fi

    print_install_coverage_gate_note
    print_install_benchmark_baseline_note
    print_install_ci_parity_summary
}
