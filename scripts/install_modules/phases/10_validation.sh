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
    step "API Entegrasyon Testleri"

    if [[ "$RUN_INSTALL_INTEGRATION_TESTS" != true ]]; then
        info "--with-integration verilmediği için tests/integration/api çalıştırılmadı."
        INTEGRATION_TEST_STATUS="atlandi_bayrak"
        return
    fi

    local integration_dir="$SCRIPT_DIR/tests/integration/api"
    local -a pytest_integration_args=("$integration_dir" --rootdir="$SCRIPT_DIR" -v --no-cov)
    local -a pytest_integration_env=()
    local integration_failure_policy="${INTEGRATION_TEST_FAILURE_POLICY:-fail}"

    if [[ ! -d "$integration_dir" ]]; then
        warn "API entegrasyon test dizini bulunamadı: $integration_dir"
        INTEGRATION_TEST_STATUS="dizin_yok"
        return
    fi

    if ! wait_for_redis_before_smoke_tests; then
        warn "Redis hazır olmadığı için API entegrasyon testleri çalıştırılmadı (false-negative önleme)."
        INTEGRATION_TEST_STATUS="atlandi_redis_hazir_degil"
        return
    fi
    wait_for_core_docker_health_before_smoke_tests

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
            pytest_integration_env+=("DATABASE_URL=$integration_database_url")
            info "API entegrasyon test DATABASE_URL değeri .env dosyasından yenilendi."
        fi
        if [[ -n "$integration_postgres_password" ]]; then
            pytest_integration_env+=("POSTGRES_PASSWORD=$integration_postgres_password")
        fi
        if [[ -n "$integration_redis_url" ]]; then
            pytest_integration_env+=("REDIS_URL=$integration_redis_url")
        fi
    fi

    if ! python -c "import pytest" >/dev/null 2>&1; then
        warn "pytest bu ortamda kurulu değil. Varsayılan dev paketleri için kurulum betiğini uv.lock ile tekrar çalıştırın."
        INTEGRATION_TEST_STATUS="pytest_yok"
        return
    fi

    if env "${pytest_integration_env[@]}" uv run pytest "${pytest_integration_args[@]}"; then
        ok "API entegrasyon testleri başarıyla geçti."
        INTEGRATION_TEST_STATUS="tamamlandi"
    else
        INTEGRATION_TEST_STATUS="hata"
        if [[ "$integration_failure_policy" == "warn" ]]; then
            warn "API entegrasyon testlerinde hata var. INTEGRATION_TEST_FAILURE_POLICY=warn nedeniyle kurulum devam ediyor."
        else
            fail "API entegrasyon testlerinde hata var. Kurulum güvenliği için süreç durduruldu."
        fi
    fi
}


run_install_frontend_quality_validation() {
    step "Frontend Entegrasyon Kalite Kapısı"

    if [[ "$RUN_INSTALL_INTEGRATION_TESTS" != true ]]; then
        info "--with-integration verilmediği için frontend lint/typecheck/coverage/e2e smoke çalıştırılmadı."
        FRONTEND_QUALITY_STATUS="atlandi_bayrak"
        return
    fi

    local frontend_dir="$SCRIPT_DIR/web_ui_react"
    local frontend_failure_policy="${FRONTEND_QUALITY_FAILURE_POLICY:-fail}"
    if [[ ! -f "$frontend_dir/package.json" ]]; then
        FRONTEND_QUALITY_STATUS="package_yok"
        fail "--with-integration frontend kalite kapısı çalıştırılamadı: $frontend_dir/package.json bulunamadı."
    fi
    if ! command -v npm >/dev/null 2>&1; then
        FRONTEND_QUALITY_STATUS="npm_yok"
        fail "--with-integration frontend kalite kapısı çalıştırılamadı: npm bulunamadı."
    fi

    info "Frontend kalite kapısı başlıyor: cd web_ui_react && npm run lint && npm run typecheck && npm run test:coverage && npm run test:e2e:smoke"
    if (
        cd "$frontend_dir" && \
        npm run lint && \
        npm run typecheck && \
        npm run test:coverage && \
        npm run test:e2e:smoke
    ); then
        ok "Frontend lint/typecheck/coverage/e2e smoke kalite kapısı başarıyla geçti."
        FRONTEND_QUALITY_STATUS="tamamlandi"
    else
        FRONTEND_QUALITY_STATUS="hata"
        if [[ "$frontend_failure_policy" == "warn" ]]; then
            warn "Frontend kalite kapısında hata var. FRONTEND_QUALITY_FAILURE_POLICY=warn nedeniyle kurulum devam ediyor."
        else
            fail "Frontend kalite kapısı başarısız. Tekrar için: cd web_ui_react && npm run lint && npm run typecheck && npm run test:coverage && npm run test:e2e:smoke"
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

run_install_ci_full_validation() {
    step "CI Tam Doğrulama"

    local production_gate_required=false
    if sidar_install_production_gate_required; then
        production_gate_required=true
        RUN_CI_FULL_VALIDATION=true
    fi

    if [[ "$RUN_CI_FULL_VALIDATION" != true ]]; then
        info "Development/local kurulumda run_tests.sh --stage all otomatik çalıştırılmadı; production için --production-readiness zorunlu gate olarak kullanılır."
        CI_FULL_VALIDATION_STATUS="atlandi_bayrak"
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

print_install_validation_coverage() {
    local full_coverage_reached=false
    [[ "$CI_FULL_VALIDATION_STATUS" == "tamamlandi" ]] && full_coverage_reached=true

    echo ""
    echo -e "${BOLD}📊 Kurulum doğrulama kapsamı:${NC}"
    if [[ "$SMOKE_TEST_STATUS" == "tamamlandi" ]]; then
        echo -e "   ${GREEN}✅ Smoke:        TAMAMLANDI (kapsam: tests/smoke)${NC}"
    elif [[ "$SMOKE_TEST_STATUS" == "hata" ]]; then
        echo -e "   ${RED}❌ Smoke:        HATA${NC}"
    else
        echo -e "   ${YELLOW}⏭️  Smoke:        ATLANDI (${SMOKE_TEST_STATUS})${NC}"
    fi

    if [[ "$full_coverage_reached" == true ]]; then
        echo -e "   ${GREEN}✅ Integration:  TAMAMLANDI (kapsam: api/cli/db/managers/web/workflow)${NC}"
        echo -e "   ${GREEN}✅ E2E:          TAMAMLANDI (kapsam: agents/cli/web)${NC}"
        echo -e "   ${GREEN}✅ Benchmark:    TAMAMLANDI${NC}"
    else
        if [[ "$INTEGRATION_TEST_STATUS" == "tamamlandi" ]]; then
            echo -e "   ${YELLOW}⚠️  Integration:  API TAMAMLANDI; TAM KAPSAM ATLANDI (api/cli/db/managers/web/workflow)${NC}"
        elif [[ "$INTEGRATION_TEST_STATUS" == "hata" ]]; then
            echo -e "   ${RED}❌ Integration:  API HATA; tam kapsam için run_tests.sh --stage integration${NC}"
        else
            echo -e "   ${YELLOW}⏭️  Integration:  ATLANDI (kapsam: api/cli/db/managers/web/workflow)${NC}"
        fi
        echo -e "   ${YELLOW}⏭️  E2E:          ATLANDI (kapsam: agents/cli/web)${NC}"
        echo -e "   ${YELLOW}⏭️  Benchmark:    ATLANDI${NC}"
    fi

    if [[ "$FRONTEND_QUALITY_STATUS" == "tamamlandi" ]]; then
        echo -e "   ${GREEN}✅ Frontend:     LINT/TYPECHECK/COVERAGE/E2E SMOKE TAMAMLANDI${NC}"
    elif [[ "$FRONTEND_QUALITY_STATUS" == "hata" ]]; then
        echo -e "   ${RED}❌ Frontend:     LINT/TYPECHECK/COVERAGE/E2E SMOKE HATA${NC}"
    elif [[ "$RUN_INSTALL_INTEGRATION_TESTS" == true ]]; then
        echo -e "   ${YELLOW}⏭️  Frontend:     ATLANDI (${FRONTEND_QUALITY_STATUS:-bilinmiyor})${NC}"
    fi

    if [[ "$CI_FULL_VALIDATION_STATUS" == "hata" ]]; then
        echo ""
        echo -e "   ${RED}Tam doğrulama sonucu: HATA${NC}"
    elif [[ "$full_coverage_reached" != true ]]; then
        echo ""
        if sidar_install_production_gate_required; then
            echo -e "   ${RED}${BOLD}⛔ PRODUCTION GATE: Tam CI/e2e/benchmark doğrulaması zorunludur.${NC}"
            echo -e "   ${RED}   Production ortamında integration/e2e/benchmark atlanmışsa kurulum production-ready sayılmaz.${NC}"
            echo -e "   ${RED}   Zorunlu gate: TEST_PROFILE=ci RUN_BENCHMARKS=required RUN_FRONTEND_E2E=1 bash run_tests.sh --stage all${NC}"
        else
            echo -e "   ${YELLOW}${BOLD}⚠️  DEVELOPMENT UYARISI: Bu kurulum yalnızca smoke testleri (boot/GPU/import/kilit/WSL) kapsar.${NC}"
            echo -e "   ${YELLOW}   Agent orkestrasyonu, gerçek DB migrasyonları, WebSocket oturumları ve plugin sandbox'ı${NC}"
            echo -e "   ${YELLOW}   gibi kritik yollar bu aşamada DOĞRULANMADI. \"Smoke testler geçti\" mesajı, tam${NC}"
            echo -e "   ${YELLOW}   kapsamlı bir doğrulamanın yerine geçmez.${NC}"
            echo ""
            echo -e "   ${BOLD}➡️  Development için önerilen sonraki adım:${NC}"
            echo -e "   ${BOLD}   ./run_tests.sh --stage integration${NC}"
            echo "   Production gate (integration + e2e + benchmark): ./install_sidar.sh --production-readiness"
            echo "   veya yalnızca:                                  TEST_PROFILE=ci RUN_BENCHMARKS=required RUN_FRONTEND_E2E=1 bash run_tests.sh --stage all"
        fi
    fi
}
