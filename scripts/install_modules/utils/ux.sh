#!/usr/bin/env bash
# shellcheck disable=SC2034  # sentinel read indirectly by sidar_source_install_utils.
SIDAR_INSTALL_UTIL_UX_SH_LOADED=1

print_install_help() {
    if sidar_is_english_locale; then
        cat <<EOF
Usage: $0 [doctor|prepare-system|sync-deps|provision-models|smoke] [--upgrade-lock] [--dev-full|--production-minimal|--dependency-profile=dev-light|dev-full|dev-gpu|gpu-runtime|production-minimal|production|custom] [--i-understand-full-access] [--cpu] [--docker-only] [--runtime-mode=local|docker] [--strict-docker] [--silent] [--auto] [--mode=local|docker] [--env=development|production] [--reset-db|--no-reset-db] [--start-services|--no-start-services] [--vscode|--no-vscode] [--with-browsers|--skip-browsers] [--offline|--air-gapped] [--install-docker-cli|--skip-docker-cli] [--force-postgres-volume-cleanup] [--skip-models] [--download-models] [--build-ui] [--kubernetes] [--smoke-test|--skip-smoke-test|--with-integration|--ci-full|--production-readiness] [--enable-autonomous-cron] [--audit] [--enable-audio] [--ci|--no-interaction|--non-interactive|--headless|--yes|-y]
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
  --with-integration / --with-integration-tests  Also run bash run_tests.sh --stage integration after smoke tests
  --ci-full  After installation, run TEST_PROFILE=ci RUN_BENCHMARKS=required RUN_FRONTEND_E2E=1 bash run_tests.sh --stage all
  --production-readiness  Production gate alias for --ci-full; fails installation unless the full CI/e2e/benchmark gate passes
  --dev-full  Explicit full developer/CI dependency profile: uv sync --frozen --all-extras
  --production-minimal  Narrow runtime dependency profile: uv sync --frozen --extra production-minimal --no-dev
  --dependency-profile=dev-light|dev-full|dev-gpu|gpu-runtime|production-minimal|production|custom  Select installer dependency sync profile
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
Kullanım: $0 [doctor|prepare-system|sync-deps|provision-models|smoke] [--upgrade-lock] [--dev-full|--production-minimal|--dependency-profile=dev-light|dev-full|dev-gpu|gpu-runtime|production-minimal|production|custom] [--i-understand-full-access] [--cpu] [--docker-only] [--runtime-mode=local|docker] [--strict-docker] [--silent] [--auto] [--mode=local|docker] [--env=development|production] [--reset-db|--no-reset-db] [--start-services|--no-start-services] [--vscode|--no-vscode] [--with-browsers|--skip-browsers] [--offline|--air-gapped] [--install-docker-cli|--skip-docker-cli] [--force-postgres-volume-cleanup] [--skip-models] [--download-models] [--build-ui] [--kubernetes] [--smoke-test|--skip-smoke-test|--with-integration|--ci-full|--production-readiness] [--enable-autonomous-cron] [--audit] [--enable-audio] [--ci|--no-interaction|--non-interactive|--headless|--yes|-y]
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
  --with-integration / --with-integration-tests  Smoke sonrası bash run_tests.sh --stage integration çalıştır
  --ci-full  Kurulum sonunda TEST_PROFILE=ci RUN_BENCHMARKS=required RUN_FRONTEND_E2E=1 bash run_tests.sh --stage all çalıştır
  --production-readiness  --ci-full için üretim geçiş kapısı aliası; tam CI/e2e/benchmark geçmeden kurulumu başarılı saymaz
  --dev-full  Açık tam geliştirici/CI bağımlılık profili: uv sync --frozen --all-extras
  --production-minimal  Dar runtime bağımlılık profili: uv sync --frozen --extra production-minimal --no-dev
  --dependency-profile=dev-light|dev-full|dev-gpu|gpu-runtime|production-minimal|production|custom  Installer bağımlılık sync profilini seç
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
