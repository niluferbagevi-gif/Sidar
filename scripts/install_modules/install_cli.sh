#!/usr/bin/env bash
set -Eeuo pipefail
# shellcheck shell=bash
# shellcheck disable=SC2034  # Sourced installer phases consume parsed globals.
# CLI defaults, argument parsing, and environment normalization for install_sidar.sh.

sidar_parse_install_cli() {
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
    DEPENDENCY_PROFILE="${SIDAR_DEPENDENCY_PROFILE:-ask}"
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

    # print_install_help is provided by scripts/install_modules/utils/ux.sh.


    INSTALL_SUBCOMMAND="full"
    DOCTOR_FIX=false
    # shellcheck disable=SC2034  # UPGRADE_LOCK is consumed by sourced python_env.sh install_python_deps.
    for arg in "$@"; do
        case "$arg" in
            --no-dev) warn "--no-dev artık desteklenmiyor; self-healing için dev bağımlılıkları standart kurulumda kalacak." ;;
            --upgrade-lock) UPGRADE_LOCK=true ;;
            --dev-full) DEPENDENCY_PROFILE="dev-full" ;;
            --production-minimal) DEPENDENCY_PROFILE="production-minimal" ;;
            --dependency-profile=*) DEPENDENCY_PROFILE="${arg#*=}" ;;
            --i-understand-full-access) ALLOW_FULL_ACCESS=true ;;
            doctor|prepare-system|sync-deps|provision-models|smoke) INSTALL_SUBCOMMAND="$arg" ;;
            --fix) DOCTOR_FIX=true ;;
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
            --production-readiness) RUN_CI_FULL_VALIDATION=true; NO_INTERACTION=true ;;
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

    if [[ "$DOCTOR_FIX" == true && "$INSTALL_SUBCOMMAND" != "doctor" ]]; then
        warn "--fix yalnız './install_sidar.sh doctor --fix' ile kullanılabilir."
        exit 1
    fi

    AUTO_INSTALL="$(normalize_bool "${AUTO_INSTALL:-false}")"
    SIDAR_WSL_AUTO_UPGRADE="$(normalize_bool "${SIDAR_WSL_AUTO_UPGRADE:-false}")"
    STRICT_DOCKER="$(normalize_bool "${STRICT_DOCKER:-${SIDAR_REQUIRE_DOCKER:-false}}")"
    ENABLE_AUTONOMOUS_CRON="$(normalize_bool "${ENABLE_AUTONOMOUS_CRON:-${SIDAR_ENABLE_AUTONOMOUS_CRON:-false}}")"
    SIDAR_PRODUCTION_READINESS_RAW="$(normalize_bool "${SIDAR_PRODUCTION_READINESS:-${PRODUCTION_READINESS:-}}")"
    if [[ "$SIDAR_PRODUCTION_READINESS_RAW" == "true" ]]; then
        RUN_CI_FULL_VALIDATION=true
        NO_INTERACTION=true
    fi
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

    if [[ "$AUTO_ENV_TYPE" == "production" && "$RUN_CI_FULL_VALIDATION" != true ]]; then
        RUN_CI_FULL_VALIDATION=true
        NO_INTERACTION=true
        warn "Production ortamı seçildi; kurulum başarısı için tam üretim doğrulaması zorunlu: TEST_PROFILE=ci RUN_BENCHMARKS=required RUN_FRONTEND_E2E=1 bash run_tests.sh --stage all"
    fi

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

    case "${DEPENDENCY_PROFILE}" in
        ask|dev-light|dev-full|dev-gpu|gpu-runtime|production-minimal|production|custom) ;;
        *) fail "Geçersiz dependency profile: ${DEPENDENCY_PROFILE}. Desteklenen: dev-light|dev-full|dev-gpu|gpu-runtime|production-minimal|production|custom" ;;
    esac
    export DEPENDENCY_PROFILE

    if [[ "$SKIP_MODELS" == true && "$DOWNLOAD_MODELS" == true ]]; then
        fail "$(sidar_t incompatible_model_flags)"
    fi

    if [[ "$INSTALL_KUBERNETES" == true && "$FORCE_CPU" == true ]]; then
        warn "$(sidar_t kubernetes_ignores_cpu)"
    fi

    if [[ "$NO_INTERACTION" == true && "$RUN_SMOKE_TESTS_MODE" == "ask" ]]; then
        RUN_SMOKE_TESTS_MODE="never"
    fi
}
