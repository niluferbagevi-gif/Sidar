#!/usr/bin/env bash
# shellcheck disable=SC2034  # sentinel read indirectly by sidar_source_install_utils.
SIDAR_INSTALL_UTIL_PYTHON_ENV_SH_LOADED=1

# uv-only Python environment helpers for the phase-based Sidar installer.
# Package resolution and environment synchronization intentionally go through
# uv venv / uv sync; legacy environment and tool-install fallbacks are not used.

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
            # shellcheck source=/dev/null
            # shellcheck disable=SC1090,SC1091
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

create_uv_venv() {
    step "uv venv Ortamı"
    local expected_python_version="3.11"
    local requested_python_version="${PYTHON_VERSION:-$expected_python_version}"
    if [[ -n "${PYTHON_VERSION:-}" && "$requested_python_version" != "$expected_python_version" ]]; then
        warn "PYTHON_VERSION=${requested_python_version} algılandı; runtime için ${expected_python_version} zorunlu."
    fi
    # Global bırakılır: sonraki installer phase/helper fonksiyonları zorunlu
    # runtime sürümünü PYTHON_VERSION üzerinden okur. Local yapılırsa fazlar
    # arasında Python sürümü tekrar override edilip regression oluşabilir.
    PYTHON_VERSION="$expected_python_version"
    VENV_DIR="$SCRIPT_DIR/.venv"
    info "Python sürümü uv ile sabitleniyor ($PYTHON_VERSION)..."
    uv python install "$PYTHON_VERSION"

    if [[ -d "$VENV_DIR" ]]; then
        info "Mevcut uv venv bulundu: $VENV_DIR"
        local detected_python_version=""
        detected_python_version="$("$VENV_DIR/bin/python" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null || true)"
        if [[ -z "$detected_python_version" && -f "$VENV_DIR/pyvenv.cfg" ]]; then
            detected_python_version="$(awk -F'= *' '/^version[[:space:]]*=/{print $2; exit}' "$VENV_DIR/pyvenv.cfg" 2>/dev/null | awk -F. '{print $1"."$2}' || true)"
        fi
        if [[ "$detected_python_version" == "$PYTHON_VERSION" ]]; then
            ok ".venv mevcut sürümle uyumlu: $detected_python_version"
        else
            warn "Mevcut .venv Python sürümü ${detected_python_version:-bilinmiyor}; zorunlu sürüm $PYTHON_VERSION. .venv yeniden oluşturuluyor."
            if [[ -O "$VENV_DIR" ]]; then
                if ! rm -rf "$VENV_DIR"; then
                    fail ".venv silinemedi: $VENV_DIR. Düzeltme: sudo chown -R $(id -u):$(id -g) \"$SCRIPT_DIR\" && rm -rf \"$VENV_DIR\""
                fi
            else
                local venv_backup_dir
                venv_backup_dir="$SCRIPT_DIR/.venv.broken-$(date +%Y%m%d-%H%M%S)"
                warn ".venv mevcut kullanıcıya ait değil. Güvenli yol olarak yedek adla taşımayı deniyorum: $venv_backup_dir"
                if mv "$VENV_DIR" "$venv_backup_dir" 2>/dev/null; then
                    warn "Eski .venv taşındı: $venv_backup_dir"
                elif [[ -t 0 ]] && command -v sudo &>/dev/null; then
                    warn "Taşıma başarısız; etkileşimli modda sudo ile kaldırma onayı istenecek."
                    if sudo rm -rf "$VENV_DIR"; then
                        ok "Sudo ile eski .venv kaldırıldı."
                    else
                        fail ".venv kaldırılamadı. Düzeltme: sudo chown -R $(id -u):$(id -g) \"$SCRIPT_DIR\" && rm -rf \"$VENV_DIR\""
                    fi
                else
                    fail ".venv mevcut kullanıcıya ait değil ve taşınamadı. Düzeltme: sudo chown -R $(id -u):$(id -g) \"$SCRIPT_DIR\" (veya yalnızca .venv) ardından kurulumu tekrar çalıştırın."
                fi
            fi
            uv venv --python "$PYTHON_VERSION" "$VENV_DIR"
            ok "uv venv zorunlu Python $PYTHON_VERSION ile yeniden oluşturuldu."
        fi
    else
        info "Yeni uv venv oluşturuluyor ($PYTHON_VERSION)..."
        uv venv --python "$PYTHON_VERSION" "$VENV_DIR"
        ok "uv venv oluşturuldu."
    fi
    # shellcheck source=/dev/null
    # shellcheck disable=SC1091
    source "$VENV_DIR/bin/activate"
    ok "Ortam aktif: $VENV_DIR"
}


normalize_dependency_profile_value() {
    local raw="${1:-}"
    raw="${raw,,}"
    raw="${raw//[[:space:]]/}"
    case "$raw" in
        dev|dev-light|light) printf 'dev-light' ;;
        full|developer-full|dev-full|all|all-extras) printf 'dev-full' ;;
        prod-min|prod-minimal|production-minimal|minimal) printf 'production-minimal' ;;
        prod|production) printf 'production' ;;
        dev-gpu|gpu-dev|developer-gpu) printf 'dev-gpu' ;;
        gpu-runtime|runtime-gpu|gpu) printf 'gpu-runtime' ;;
        custom|provider|providers|özel|ozel) printf 'custom' ;;
        ask|"") printf 'ask' ;;
        *) printf '%s' "$raw" ;;
    esac
}

select_dependency_profile() {
    local requested="${DEPENDENCY_PROFILE:-${SIDAR_DEPENDENCY_PROFILE:-ask}}"
    requested="$(normalize_dependency_profile_value "$requested")"

    if [[ "$requested" == "ask" ]]; then
        if [[ "${RUN_CI_FULL_VALIDATION:-false}" == true ]]; then
            requested="dev-full"
            info "Tam CI/production-readiness doğrulaması seçildi; bağımlılık profili developer-full olarak ayarlandı."
        elif [[ "${NO_INTERACTION:-false}" == true || "${AUTO_INSTALL:-false}" == true ]]; then
            requested="dev-light"
            info "Etkileşimsiz kurulum: varsayılan hafif geliştirici bağımlılık profili seçildi (dev-light)."
        elif [[ -t 0 ]]; then
            echo
            echo "Bağımlılık profili seçin:"
            echo "  1) dev-light (önerilen; hızlı yerel geliştirme + test araçları)"
            echo "  2) developer-full (tüm extras; CI/tam doğrulama)"
            echo "  3) dev-gpu (geliştirici + RAG/GPU runtime; provider extras yok)"
            echo "  4) production-minimal (dar no-dev runtime)"
            echo "  5) production (runtime + postgres + telemetry)"
            echo "  6) gpu-runtime (dar no-dev RAG/GPU runtime)"
            echo "  7) özel provider seçimi (SIDAR_DEPENDENCY_EXTRAS)"
            local profile_choice=""
            if read -r -t "${SIDAR_PROMPT_TIMEOUT:-180}" -p "Seçim [1-7, varsayılan 1]: " profile_choice 2>/dev/tty; then
                profile_choice="${profile_choice:-1}"
            else
                profile_choice="1"
                echo
                warn "Bağımlılık profili seçimi zaman aşımına uğradı; dev-light seçildi."
            fi
            case "$profile_choice" in
                1) requested="dev-light" ;;
                2) requested="dev-full" ;;
                3) requested="dev-gpu" ;;
                4) requested="production-minimal" ;;
                5) requested="production" ;;
                6) requested="gpu-runtime" ;;
                7) requested="custom" ;;
                *)
                    warn "Geçersiz bağımlılık profili seçimi (${profile_choice}); dev-light kullanılacak."
                    requested="dev-light"
                    ;;
            esac
        else
            requested="dev-light"
            info "TTY yok; varsayılan hafif geliştirici bağımlılık profili seçildi (dev-light)."
        fi
    fi

    if [[ "$requested" == "custom" && -z "${SIDAR_DEPENDENCY_EXTRAS:-}" ]]; then
        if [[ "${NO_INTERACTION:-false}" == true || "${AUTO_INSTALL:-false}" == true || ! -t 0 ]]; then
            fail "custom dependency profile için SIDAR_DEPENDENCY_EXTRAS zorunlu (örn. SIDAR_DEPENDENCY_EXTRAS='dev,openai,postgres')."
        fi
        local custom_extras=""
        if read -r -t "${SIDAR_PROMPT_TIMEOUT:-180}" -p "Özel extras listesini virgül/boşluk ile girin (örn. dev,openai,postgres): " custom_extras 2>/dev/tty; then
            SIDAR_DEPENDENCY_EXTRAS="$custom_extras"
        fi
        [[ -n "${SIDAR_DEPENDENCY_EXTRAS:-}" ]] || fail "custom dependency profile seçildi ancak extras listesi boş."
    fi

    case "$requested" in
        dev-light|dev-full|dev-gpu|gpu-runtime|production-minimal|production|custom) ;;
        *) fail "Geçersiz dependency profile: ${requested}. Desteklenen: dev-light|dev-full|dev-gpu|gpu-runtime|production-minimal|production|custom" ;;
    esac

    DEPENDENCY_PROFILE="$requested"
    export DEPENDENCY_PROFILE SIDAR_DEPENDENCY_EXTRAS
    ok "Bağımlılık profili seçildi: ${DEPENDENCY_PROFILE}${SIDAR_DEPENDENCY_EXTRAS:+ (extras=${SIDAR_DEPENDENCY_EXTRAS})}"
}

build_custom_dependency_sync_args() {
    local raw_extras="${SIDAR_DEPENDENCY_EXTRAS:-}"
    local extra=""
    local -a args=(--frozen)

    raw_extras="${raw_extras//,/ }"
    for extra in $raw_extras; do
        extra="${extra//[[:space:]]/}"
        [[ -z "$extra" ]] && continue
        args+=(--extra "$extra")
    done

    if [[ "${#args[@]}" -le 1 ]]; then
        fail "custom dependency profile için en az bir extra seçilmelidir."
    fi

    printf '%s\0' "${args[@]}"
}

install_python_deps() {
    step "Python Bağımlılıkları Kuruluyor"

    cd "$SCRIPT_DIR" || return 1
    UV_CMD=(uv)

    local dependency_profile="${DEPENDENCY_PROFILE:-${SIDAR_DEPENDENCY_PROFILE:-dev-light}}"
    dependency_profile="$(normalize_dependency_profile_value "$dependency_profile")"
    if [[ "$dependency_profile" == "ask" ]]; then
        select_dependency_profile
        dependency_profile="${DEPENDENCY_PROFILE:-dev-light}"
    fi
    local sync_command_label="uv sync --frozen --extra dev-light"
    local -a SYNC_ARGS=()

    case "$dependency_profile" in
        dev-full)
            # Standart kurulum komutu: uv sync --frozen --all-extras — all extra grubu
            # dev dahil tüm extras'ı içerir.
            SYNC_ARGS=(--frozen --all-extras)
            sync_command_label="uv sync --frozen --all-extras"
            ;;
        dev-light)
            SYNC_ARGS=(--frozen --extra dev-light)
            sync_command_label="uv sync --frozen --extra dev-light"
            ;;
        dev-gpu)
            SYNC_ARGS=(--frozen --extra dev-gpu)
            sync_command_label="uv sync --frozen --extra dev-gpu"
            ;;
        gpu-runtime)
            SYNC_ARGS=(--frozen --extra gpu-runtime --no-dev)
            sync_command_label="uv sync --frozen --extra gpu-runtime --no-dev"
            ;;
        custom)
            mapfile -d '' -t SYNC_ARGS < <(build_custom_dependency_sync_args)
            sync_command_label="uv sync ${SYNC_ARGS[*]}"
            ;;
        production)
            SYNC_ARGS=(--frozen --extra production --no-dev)
            sync_command_label="uv sync --frozen --extra production --no-dev"
            ;;
        production-minimal)
            SYNC_ARGS=(--frozen --extra production-minimal --no-dev)
            sync_command_label="uv sync --frozen --extra production-minimal --no-dev"
            ;;
        *)
            fail "Geçersiz dependency profile: ${dependency_profile}. Desteklenen: dev-light|dev-full|dev-gpu|gpu-runtime|production-minimal|production|custom"
            ;;
    esac
    export DEPENDENCY_PROFILE="$dependency_profile"

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

    if [[ "$dependency_profile" == "dev-full" ]]; then
        ensure_portaudio_dev "$sync_command_label"
    else
        info "Dependency profile ${dependency_profile}: PortAudio/voice sistem ön koşulu yalnız dev-full profilinde zorunlu kontrol edilir."
    fi

    info "Bağımlılık profili: ${dependency_profile} — ${sync_command_label}."
    if [[ "$dependency_profile" == "production" || "$dependency_profile" == "production-minimal" ]]; then
        warn "Production dependency profili dev/test araçlarını kurmaz; smoke/CI/self-healing için dev-full veya dev-light kullanın."
    fi
    if ! "${UV_CMD[@]}" sync "${SYNC_ARGS[@]}"; then
        fail "Bağımlılık kurulumu başarısız oldu (${sync_command_label}). Lock dosyası pyproject ile uyumsuzsa bilinçli olarak --upgrade-lock çalıştırın."
    fi

    if ! "${UV_CMD[@]}" run python -c "import pydantic, pydantic_settings" >/dev/null 2>&1; then
        fail "Zorunlu runtime bağımlılık doğrulaması başarısız: pydantic/pydantic-settings import edilemedi. Standart kurulum komutunu temiz bir ortamda tekrar çalıştırın: ${sync_command_label}."
    fi

    ok "Zorunlu runtime bağımlılıkları doğrulandı: pydantic + pydantic-settings."
    ok "Python bağımlılıkları kilitli uv.lock üzerinden senkronlandı."
    ensure_env_file_secrets_after_uv_sync
    validate_runtime_env_loading
}

install_pre_commit_hooks() {
    step "Pre-commit Hook Kurulumu"

    local dependency_profile="${DEPENDENCY_PROFILE:-${SIDAR_DEPENDENCY_PROFILE:-dev-light}}"
    dependency_profile="$(normalize_dependency_profile_value "$dependency_profile")"
    [[ "$dependency_profile" != "ask" ]] || dependency_profile="dev-light"

    case "$dependency_profile" in
        production|production-minimal|gpu-runtime)
            warn "Dependency profile ${dependency_profile}: pre-commit dev bağımlılıkları kurulmaz; hook kurulumu atlandı."
            return 0
            ;;
    esac

    if [[ ! -d "$SCRIPT_DIR/.git" ]]; then
        warn "Git deposu bulunamadı; pre-commit hook kurulumu atlandı."
        return 0
    fi

    if ! uv run pre-commit install --hook-type pre-commit --hook-type pre-push; then
        fail "pre-commit/pre-push hook kurulumu başarısız oldu. Manuel doğrulama: uv run pre-commit install --hook-type pre-commit --hook-type pre-push"
    fi

    ok "pre-commit ve pre-push hook'ları kuruldu."
}

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

    if [[ "${DEPENDENCY_PROFILE:-dev-full}" == "production" || "${DEPENDENCY_PROFILE:-dev-full}" == "production-minimal" ]]; then
        warn "Pyright LSP production dependency profilinde kurulmaz; reviewer/self-heal geliştirme akışları için --dev-full veya --dependency-profile=dev-light kullanın."
        return
    fi

    fail "Pyright LSP bulunamadı. Standart kurulum komutunu çalıştırın: uv sync --frozen --all-extras veya installer için --dev-full kullanın."
}

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
    local dependency_profile="${DEPENDENCY_PROFILE:-${SIDAR_DEPENDENCY_PROFILE:-dev-light}}"
    dependency_profile="$(normalize_dependency_profile_value "$dependency_profile")"
    [[ "$dependency_profile" != "ask" ]] || dependency_profile="dev-light"

    local -a sync_args=(--frozen)
    local sync_profile_label="$dependency_profile"
    case "$dependency_profile" in
        dev-full)
            # Kullanıcı bilinçli tam profili seçtiyse mevcut kapsam korunur.
            sync_args+=(--all-extras)
            ;;
        dev-light|dev-gpu)
            sync_args+=(--extra dev-gpu)
            sync_profile_label="${dependency_profile} → dev-gpu"
            ;;
        production|production-minimal|gpu-runtime)
            sync_args+=(--extra gpu-runtime --no-dev)
            sync_profile_label="${dependency_profile} → gpu-runtime"
            ;;
        custom)
            mapfile -d '' -t sync_args < <(build_custom_dependency_sync_args)
            sync_args+=(--extra gpu-runtime)
            sync_profile_label="custom + gpu-runtime"
            ;;
        *)
            fail "Geçersiz dependency profile: ${dependency_profile}. Desteklenen: dev-light|dev-full|dev-gpu|gpu-runtime|production-minimal|production|custom"
            ;;
    esac

    sync_args+=(
        --index "$index_url"
        --reinstall-package torch
        --reinstall-package torchvision
    )

    info "PyTorch CUDA wheel seçimi uv sync ile uygulanıyor: ${cuda_tag} (${index_url}); profil: ${sync_profile_label}"
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
