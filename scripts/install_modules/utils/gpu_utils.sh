#!/usr/bin/env bash
set -Eeuo pipefail
# shellcheck disable=SC2034  # sentinel read indirectly by sidar_source_install_utils.
SIDAR_INSTALL_UTIL_GPU_UTILS_SH_LOADED=1


detect_cuda_driver_capability() {
    local smi_cmd="${1:-}"
    local query_out=""
    local parsed_version=""

    [[ -n "$smi_cmd" ]] || return 0

    query_out=$("$smi_cmd" --query-gpu=cuda_version --format=csv,noheader 2>/dev/null | head -1 || true)
    parsed_version=$(echo "${query_out:-}" | tr -d '[:space:]' | grep -Eo '^[0-9]+([.][0-9]+)*' | head -1 || true)
    if [[ -n "$parsed_version" ]]; then
        printf '%s\n' "$parsed_version"
        return 0
    fi

    parsed_version=$("$smi_cmd" 2>/dev/null | grep -Eo 'CUDA Version:[[:space:]]*[0-9]+([.][0-9]+)*' | grep -Eo '[0-9]+([.][0-9]+)*' | head -1 || true)
    if [[ -n "$parsed_version" ]]; then
        printf '%s\n' "$parsed_version"
        return 0
    fi

    # WSL2'nin shim'lenmiş nvidia-smi'si banner'da "CUDA Version: N/A" gösterebilir
    # (bilinen WSL2/NVIDIA kısıtı). libcuda.so zaten yüklenmişse cuDriverGetVersion()
    # ile sürücünün desteklediği CUDA API sürümünü doğrudan sorgula; CUDA toolkit
    # gerektirmez.
    parsed_version=$(detect_cuda_driver_capability_via_libcuda || true)
    if [[ -n "$parsed_version" ]]; then
        printf '%s\n' "$parsed_version"
        return 0
    fi

    if command -v nvcc &>/dev/null; then
        parsed_version=$(nvcc --version 2>/dev/null | grep -Eo 'release[[:space:]]+[0-9]+([.][0-9]+)*' | grep -Eo '[0-9]+([.][0-9]+)*' | head -1 || true)
        [[ -n "$parsed_version" ]] && printf '%s\n' "$parsed_version"
    fi
}

detect_cuda_driver_capability_via_libcuda() {
    local python_cmd=""

    if command -v python3 &>/dev/null; then
        python_cmd="python3"
    elif command -v python &>/dev/null; then
        python_cmd="python"
    else
        return 0
    fi

    # SIDAR_LIBCUDA_CANDIDATE_PATHS is a test/diagnostic override that makes libcuda
    # discovery hermetic on WSL2 hosts where /usr/lib/wsl/lib/libcuda.so exists.
    "$python_cmd" - <<'PY_LIBCUDA' 2>/dev/null | head -1
import ctypes
import os

def load_libcuda():
    override = os.environ.get("SIDAR_LIBCUDA_CANDIDATE_PATHS")
    if override is not None:
        candidates = tuple(path for path in override.split(":") if path)
    else:
        candidates = (
            "libcuda.so.1",
            "libcuda.so",
            "/usr/lib/wsl/lib/libcuda.so.1",
            "/usr/lib/wsl/lib/libcuda.so",
        )
    for name in candidates:
        try:
            return ctypes.CDLL(name)
        except OSError:
            continue
    return None

lib = load_libcuda()
if lib is None:
    raise SystemExit(0)

try:
    if lib.cuInit(0) != 0:
        raise SystemExit(0)
    version = ctypes.c_int(0)
    if lib.cuDriverGetVersion(ctypes.byref(version)) != 0:
        raise SystemExit(0)
except Exception:
    raise SystemExit(0)

print(f"{version.value // 1000}.{(version.value % 1000) // 10}")
PY_LIBCUDA
}

detect_pytorch_runtime_cuda_version() {
    local python_cmd=()

    if command -v uv &>/dev/null; then
        python_cmd=(uv run python)
    elif command -v python3 &>/dev/null; then
        python_cmd=(python3)
    elif command -v python &>/dev/null; then
        python_cmd=(python)
    else
        return 0
    fi

    "${python_cmd[@]}" - <<'PY_TORCH_CUDA' 2>/dev/null | head -1
try:
    import torch
except Exception:
    raise SystemExit(0)
print(getattr(torch.version, "cuda", None) or "")
PY_TORCH_CUDA
}

report_gpu_cuda_diagnostics() {
    local cuda_driver_cap="${1:-}"
    local driver_version="${2:-}"
    local pytorch_runtime_cuda="${PYTORCH_RUNTIME_CUDA_VERSION:-}"
    local wsl_passthrough_active="${SIDAR_WSL_CUDA_PASSTHROUGH_ACTIVE:-}"

    [[ -n "$driver_version" ]] && ok "NVIDIA Windows Driver : $driver_version"
    if [[ -n "$cuda_driver_cap" ]]; then
        ok "Driver CUDA API Capability : $cuda_driver_cap"
    else
        info "Driver CUDA API Capability : bilinmiyor"
    fi

    if [[ "${WSL2:-false}" == true ]]; then
        case "$wsl_passthrough_active" in
            true) ok "WSL CUDA Passthrough : aktif" ;;
            false) warn "WSL CUDA Passthrough : pasif" ;;
            *) info "WSL CUDA Passthrough : bilinmiyor" ;;
        esac
        if [[ -n "$pytorch_runtime_cuda" ]]; then
            ok "PyTorch Runtime CUDA : $pytorch_runtime_cuda"
        else
            info "PyTorch Runtime CUDA : torch kurulumundan sonra doğrulanacak."
        fi
    elif [[ -n "$pytorch_runtime_cuda" ]]; then
        ok "PyTorch Runtime CUDA : $pytorch_runtime_cuda"
    fi
}

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
    GPU_NAME=""
    VRAM_MB="0"
    DRIVER_VER=""
    PYTORCH_RUNTIME_CUDA_VERSION=""

    if [[ "${FORCE_CPU:-false}" == true ]]; then
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
        local use_preflight_facts="${SIDAR_USE_GPU_PREFLIGHT_FACTS:-false}"

        query_out=$("$SMI_CMD" --query-gpu=name --format=csv,noheader 2>/dev/null | head -1 || true)
        GPU_NAME="${query_out:-Bilinmiyor}"
        if [[ "$use_preflight_facts" == true && -n "${SIDAR_GPU_PREFLIGHT_NAME:-}" ]]; then
            GPU_NAME="$SIDAR_GPU_PREFLIGHT_NAME"
        fi

        query_out=$("$SMI_CMD" --query-gpu=memory.total --format=csv,noheader,nounits 2>/dev/null | head -1 || true)
        VRAM_MB="$(echo "${query_out:-0}" | tr -d ' ,' )"
        if [[ "$use_preflight_facts" == true && -n "${SIDAR_GPU_PREFLIGHT_VRAM_MB:-}" ]]; then
            VRAM_MB="$SIDAR_GPU_PREFLIGHT_VRAM_MB"
        fi
        if [[ -z "$VRAM_MB" ]]; then
            VRAM_MB="0"
        fi

        query_out=$("$SMI_CMD" --query-gpu=compute_cap --format=csv,noheader 2>/dev/null | head -1 || true)
        GPU_COMPUTE_CAPABILITY="$(echo "${query_out:-}" | tr -d '[:space:]')"
        if [[ "$use_preflight_facts" == true && -n "${SIDAR_GPU_PREFLIGHT_COMPUTE_CAPABILITY:-}" ]]; then
            GPU_COMPUTE_CAPABILITY="$SIDAR_GPU_PREFLIGHT_COMPUTE_CAPABILITY"
        fi
        CUDA_VERSION="$(detect_cuda_driver_capability "$SMI_CMD")"
        if [[ "$use_preflight_facts" == true && -n "${SIDAR_GPU_PREFLIGHT_CUDA_DRIVER_CAPABILITY:-}" ]]; then
            CUDA_VERSION="$SIDAR_GPU_PREFLIGHT_CUDA_DRIVER_CAPABILITY"
        fi
        DRIVER_VER="$("$SMI_CMD" --query-gpu=driver_version --format=csv,noheader 2>/dev/null | head -1 || true)"
        if [[ "$use_preflight_facts" == true && -n "${SIDAR_GPU_PREFLIGHT_DRIVER_VERSION:-}" ]]; then
            DRIVER_VER="$SIDAR_GPU_PREFLIGHT_DRIVER_VERSION"
        fi
        PYTORCH_RUNTIME_CUDA_VERSION=$(detect_pytorch_runtime_cuda_version || true)

        GPU_AVAILABLE=true
        if [[ "${RUN_GPU_STRESS:-0}" != "1" ]]; then
            export RUN_GPU_STRESS=1
            declare -F persist_run_gpu_stress_dotenv >/dev/null 2>&1 && persist_run_gpu_stress_dotenv
            info "GPU tespit edildiği için RUN_GPU_STRESS=1 otomatik etkinleştirildi."
        fi
        ok "GPU     : $GPU_NAME"
        ok "VRAM    : ${VRAM_MB} MiB"
        report_gpu_cuda_diagnostics "$CUDA_VERSION" "$DRIVER_VER"
        [[ -n "$GPU_COMPUTE_CAPABILITY" ]] && ok "Compute : $GPU_COMPUTE_CAPABILITY"

        if [[ "${WSL2:-false}" == true ]]; then
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

docker_nvidia_runtime_registered() {
    docker info --format '{{json .Runtimes}}' 2>/dev/null | grep -q 'nvidia'
}

wait_for_docker_nvidia_runtime() {
    local timeout_seconds="${SIDAR_DOCKER_NVIDIA_RUNTIME_WAIT_SECONDS:-90}"
    local interval_seconds="${SIDAR_DOCKER_NVIDIA_RUNTIME_WAIT_INTERVAL_SECONDS:-3}"
    local elapsed=0

    [[ "$timeout_seconds" =~ ^[0-9]+$ ]] || timeout_seconds=90
    [[ "$interval_seconds" =~ ^[0-9]+$ && "$interval_seconds" -gt 0 ]] || interval_seconds=3

    if docker_nvidia_runtime_registered; then
        return 0
    fi

    info "Docker NVIDIA runtime kaydı bekleniyor (maks. ${timeout_seconds}sn)..."
    while (( elapsed < timeout_seconds )); do
        sleep "$interval_seconds"
        elapsed=$((elapsed + interval_seconds))
        if docker_nvidia_runtime_registered; then
            return 0
        fi
    done
    return 1
}

install_nvidia_container_repository() {
    local key_url="https://nvidia.github.io/libnvidia-container/gpgkey"
    local list_url="https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list"
    local keyring="/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg"
    local repo_file="/etc/apt/sources.list.d/nvidia-container-toolkit.list"
    local temp_dir=""

    temp_dir="$(mktemp -d)"
    if ! curl -fsSL --retry 3 --retry-all-errors "$key_url" -o "${temp_dir}/nvidia.asc" \
        || ! curl -fsSL --retry 3 --retry-all-errors "$list_url" -o "${temp_dir}/nvidia.list"; then
        rm -rf "$temp_dir"
        fail "NVIDIA container-toolkit imza anahtarı veya depo listesi indirilemedi."
    fi
    if ! gpg --batch --yes --dearmor --output "${temp_dir}/nvidia.gpg" "${temp_dir}/nvidia.asc"; then
        rm -rf "$temp_dir"
        fail "NVIDIA container-toolkit GPG anahtarı keyring biçimine dönüştürülemedi."
    fi
    if [[ ! -s "${temp_dir}/nvidia.gpg" ]] \
        || ! grep -Eq '^deb([[:space:]]|\[).*https://nvidia\.github\.io/libnvidia-container/' "${temp_dir}/nvidia.list"; then
        rm -rf "$temp_dir"
        fail "NVIDIA keyring/depo içeriği beklenen biçimde değil; APT yapılandırması değiştirilmedi."
    fi

    sed "s#deb https://#deb [signed-by=${keyring}] https://#g" \
        "${temp_dir}/nvidia.list" > "${temp_dir}/nvidia.signed.list"
    # gpg'yi sudo altında doğrudan hedef dosyaya yazdırmak, yarım dosya ve
    # root-owned geçici çıktı sorunlarına yol açabiliyordu. Doğrulanan dosyaları
    # install(1) ile atomik olarak ve APT'nin okuyabileceği açık izinlerle yerleştir.
    sudo install -d -m 0755 /usr/share/keyrings /etc/apt/sources.list.d
    sudo install -m 0644 "${temp_dir}/nvidia.gpg" "$keyring"
    sudo install -m 0644 "${temp_dir}/nvidia.signed.list" "$repo_file"
    rm -rf "$temp_dir"

    if [[ ! -r "$keyring" || ! -r "$repo_file" ]]; then
        fail "NVIDIA keyring/depo dosyaları APT kullanıcısı tarafından okunamıyor (${keyring}, ${repo_file})."
    fi
    ok "NVIDIA container-toolkit keyring ve depo izinleri doğrulandı (0644)."
}

setup_nvidia_docker() {
    if [[ "$GPU_AVAILABLE" == true ]] && command -v docker &>/dev/null; then
        step "Docker GPU Desteği (nvidia-container-toolkit)"
        if ! command -v nvidia-ctk &>/dev/null; then
            warn "nvidia-container-toolkit bulunamadı. Kurulum başlatılıyor (sudo şifreniz istenebilir)..."

            # NVIDIA repolarını doğrulanmış geçici dosyalardan, açık izinlerle kur.
            install_nvidia_container_repository

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

        if wait_for_docker_nvidia_runtime; then
            ok "Docker NVIDIA runtime doğrulandı."
            SIDAR_DEFERRED_WARN_DOCKER_NVIDIA_RUNTIME="false"
            SIDAR_DEFERRED_WARN_DOCKER_NVIDIA_RUNTIME_MSG=""
        elif [[ "$WSL2" == true ]]; then
            SIDAR_DEFERRED_WARN_DOCKER_NVIDIA_RUNTIME="true"
            SIDAR_DEFERRED_WARN_DOCKER_NVIDIA_RUNTIME_MSG="Docker NVIDIA runtime henüz kayıtlı görünmüyor; Docker Desktop restart sonrası 'docker info --format {{json .Runtimes}}' çıktısında nvidia görünene kadar bekleyin."
            warn "$SIDAR_DEFERRED_WARN_DOCKER_NVIDIA_RUNTIME_MSG"
        elif [[ "${SIDAR_DEFERRED_WARN_DOCKER_NVIDIA_RUNTIME:-false}" == "true" ]]; then
            warn "${SIDAR_DEFERRED_WARN_DOCKER_NVIDIA_RUNTIME_MSG:-Docker NVIDIA runtime kayıtlı görünmüyor; nvidia-container-toolkit doğrulamasını manuel kontrol edin.}"
        fi
    fi
}
