#!/usr/bin/env bash
# shellcheck disable=SC2034  # sentinel read indirectly by sidar_source_install_utils.
SIDAR_INSTALL_UTIL_GPU_UTILS_SH_LOADED=1

# Functional install helpers for the phase-based Sidar installer.
# These definitions intentionally override the legacy monolithic fallbacks in
# install_sidar.sh when sourced by the relevant phase module.

configure_wsl2_cuda_library_paths() {
    [[ "${WSL2:-false}" == true ]] || return 0
    [[ "${GPU_AVAILABLE:-false}" == true ]] || return 0

    local -a preferred_cuda_paths=(
        "/usr/lib/wsl/lib"
        "/usr/local/cuda/lib64"
        "/usr/local/nvidia/lib64"
        "/usr/local/nvidia/lib"
    )
    local existing_ld_path="${LD_LIBRARY_PATH:-}"
    local combined_ld_path="$existing_ld_path"
    local path_entry=""

    for path_entry in "${preferred_cuda_paths[@]}"; do
        [[ -d "$path_entry" ]] || continue
        if [[ ":$combined_ld_path:" != *":$path_entry:"* ]]; then
            if [[ -n "$combined_ld_path" ]]; then
                combined_ld_path="${path_entry}:${combined_ld_path}"
            else
                combined_ld_path="$path_entry"
            fi
        fi
    done

    if [[ -n "$combined_ld_path" ]]; then
        export LD_LIBRARY_PATH="$combined_ld_path"
        export OLLAMA_LLM_LIBRARY="cuda"
        info "WSL2 CUDA/Tensor/Ollama için LD_LIBRARY_PATH ayarlandı: $LD_LIBRARY_PATH"
    fi
}

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
            declare -F persist_run_gpu_stress_dotenv >/dev/null 2>&1 && persist_run_gpu_stress_dotenv
            info "GPU tespit edildiği için RUN_GPU_STRESS=1 otomatik etkinleştirildi."
        fi
        ok "GPU     : $GPU_NAME"
        ok "VRAM    : ${VRAM_MB} MiB"
        ok "Sürücü  : $DRIVER_VER"
        ok "CUDA    : $CUDA_VERSION"
        [[ -n "$GPU_COMPUTE_CAPABILITY" ]] && ok "Compute : $GPU_COMPUTE_CAPABILITY"

        if [[ "$WSL2" == true ]]; then
            info "WSL2 üzerinde CUDA, Windows NVIDIA sürücüsü (libcuda.so) üzerinden erişilir."
            configure_wsl2_cuda_library_paths
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

print_docker_desktop_restart_notice() {
    warn "╔════════════════════════════════════════════════════════════════════╗"
    warn "║ Docker Desktop Restart gerekli olabilir                           ║"
    warn "║ nvidia-container-toolkit Docker runtime ayarını değiştirdi.       ║"
    warn "║ Windows tarafında Docker Desktop > Quit/Restart uygulayın;        ║"
    warn "║ ardından bu WSL terminalinde 'docker info' ile nvidia runtime'ı    ║"
    warn "║ doğrulayın ve install_sidar.sh komutunu tekrar çalıştırın.        ║"
    warn "╚════════════════════════════════════════════════════════════════════╝"
}

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
                    print_docker_desktop_restart_notice
                fi
            elif command -v service &>/dev/null && service docker status >/dev/null 2>&1; then
                sudo service docker restart
                ok "Docker servisi SysV/service üzerinden yeniden başlatıldı."
            else
                warn "Docker systemd veya service üzerinden yönetilmiyor (Docker Desktop kullanılıyor olabilir)."
                print_docker_desktop_restart_notice
            fi
            ok "nvidia-container-toolkit kuruldu ve Docker yapılandırıldı."
        else
            ok "nvidia-container-toolkit zaten kurulu."
        fi

        if docker info --format '{{json .Runtimes}}' 2>/dev/null | grep -q 'nvidia'; then
            ok "Docker NVIDIA runtime doğrulandı."
            SIDAR_DEFERRED_WARN_DOCKER_NVIDIA_RUNTIME="false"
            SIDAR_DEFERRED_WARN_DOCKER_NVIDIA_RUNTIME_MSG=""
        elif [[ "${SIDAR_DEFERRED_WARN_DOCKER_NVIDIA_RUNTIME:-false}" == "true" ]]; then
            warn "${SIDAR_DEFERRED_WARN_DOCKER_NVIDIA_RUNTIME_MSG:-Docker NVIDIA runtime kayıtlı görünmüyor; nvidia-container-toolkit doğrulamasını manuel kontrol edin.}"
        fi
    fi
}
