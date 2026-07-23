#!/usr/bin/env bash
set -Eeuo pipefail
# Sidar installer phase: system dependencies, prerequisites, GPU and NVIDIA Docker helpers.

# shellcheck disable=SC2034  # Set by remote_script.sh and consumed by phase helpers.
DOWNLOADED_SCRIPT_FILE=""

# GPU/CUDA detection is single-sourced from utils/gpu_utils.sh. Keep this phase
# focused on system provisioning and NVIDIA container-toolkit setup.
if [[ -z "${SIDAR_INSTALL_UTIL_WSL_HOST_SH_LOADED:-}" ]]; then
    _sidar_03_system_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    _sidar_wsl_host_utils="${_sidar_03_system_dir}/../utils/wsl_host.sh"
    if [[ -f "$_sidar_wsl_host_utils" ]]; then
        # shellcheck source=../utils/wsl_host.sh
        source "$_sidar_wsl_host_utils"
    fi
    unset _sidar_03_system_dir _sidar_wsl_host_utils
fi

if [[ -z "${SIDAR_INSTALL_UTIL_GPU_UTILS_SH_LOADED:-}" ]]; then
    _sidar_03_system_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    _sidar_gpu_utils="${_sidar_03_system_dir}/../utils/gpu_utils.sh"
    if [[ -f "$_sidar_gpu_utils" ]]; then
        # shellcheck source=../utils/gpu_utils.sh
        source "$_sidar_gpu_utils"
    fi
    unset _sidar_03_system_dir _sidar_gpu_utils
fi

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

    local retries="${DOCKER_CLI_HEALTH_RETRIES:-6}"
    local delay_seconds="${DOCKER_CLI_HEALTH_RETRY_DELAY:-2}"
    if [[ ! "$retries" =~ ^[0-9]+$ ]] || (( retries < 1 )); then
        retries=6
    fi
    if [[ ! "$delay_seconds" =~ ^[0-9]+$ ]]; then
        delay_seconds=2
    fi

    local attempt=1
    local docker_out=""
    local docker_rc=0

    while (( attempt <= retries )); do
        docker_rc=0
        docker_out="$(docker --version 2>&1)" || docker_rc=$?
        if [[ "$docker_rc" -eq 0 ]]; then
            return 0
        fi

        if (( attempt < retries )); then
            sleep "$delay_seconds"
        fi
        ((attempt += 1))
    done

    if [[ "$docker_rc" -eq 135 ]] || [[ "$docker_out" == *"Bus error"* ]]; then
        warn "Docker CLI Bus error veriyor. WSL2 Docker Desktop entegrasyonunu yeniden etkinleştirip WSL'i yeniden başlatın."
    elif [[ "$docker_out" == *"Input/output error"* ]]; then
        warn "Docker CLI Input/output error veriyor. WSL mount/entegrasyon durumu bozulmuş olabilir."
    fi
    return 1
}

verify_offline_bundle_manifest() {
    local bundle_dir="${1:-}"
    [[ -n "$bundle_dir" ]] || fail "Çevrimdışı mod etkin ancak offline bundle dizini bulunamadı."
    [[ -d "$bundle_dir" ]] || fail "Çevrimdışı bundle dizini bulunamadı: $bundle_dir"
    [[ -f "$bundle_dir/manifest.json" ]] || fail "Çevrimdışı bundle manifesti eksik: $bundle_dir/manifest.json"

    if command -v python3 &>/dev/null; then
        python3 "$SCRIPT_DIR/scripts/offline_bundle.py" verify "$bundle_dir" \
            || fail "Çevrimdışı bundle SHA256 doğrulaması başarısız oldu."
    else
        fail "Çevrimdışı manifest doğrulaması için python3 gereklidir."
    fi

    export UV_FIND_LINKS="${bundle_dir}/wheels"
    export UV_NO_INDEX=1
    export npm_config_cache="${bundle_dir}/npm/cache"
    export OLLAMA_MODELS="${bundle_dir}/ollama/models"
    ok "Çevrimdışı bundle doğrulandı ve wheel/npm/Ollama cache yolları ayarlandı."
}

docker_repo_platform() {
    if [[ ! -r /etc/os-release ]]; then
        return 1
    fi

    # shellcheck disable=SC1091
    . /etc/os-release
    case " ${ID:-} ${ID_LIKE:-} " in
        *" ubuntu "*) echo "ubuntu" ;;
        *" debian "*) echo "debian" ;;
        *) return 1 ;;
    esac
}

docker_repo_codename() {
    if [[ ! -r /etc/os-release ]]; then
        return 1
    fi

    # shellcheck disable=SC1091
    . /etc/os-release
    if [[ "$(docker_repo_platform 2>/dev/null || true)" == "ubuntu" && -n "${UBUNTU_CODENAME:-}" ]]; then
        echo "$UBUNTU_CODENAME"
    elif [[ -n "${VERSION_CODENAME:-}" ]]; then
        echo "$VERSION_CODENAME"
    else
        return 1
    fi
}

install_docker_cli_from_apt() {
    if [[ "$OFFLINE_MODE" == true ]]; then
        warn "Çevrimdışı modda Docker CLI APT deposundan kurulamaz; offline bundle veya manuel kurulum gerekir."
        return 1
    fi
    if ! command -v apt-get &>/dev/null; then
        warn "apt-get bulunamadı; Docker CLI otomatik kurulumu bu platformda desteklenmiyor."
        return 1
    fi
    if ! command -v curl &>/dev/null; then
        warn "curl bulunamadı; Docker APT anahtarı indirilemediği için Docker CLI kurulumu atlandı."
        return 1
    fi

    local docker_platform=""
    local docker_codename=""
    docker_platform="$(docker_repo_platform 2>/dev/null || true)"
    docker_codename="$(docker_repo_codename 2>/dev/null || true)"
    if [[ -z "$docker_platform" || -z "$docker_codename" ]]; then
        warn "Docker resmi APT deposu için Debian/Ubuntu platform kod adı belirlenemedi; manuel kurulum gerekir."
        return 1
    fi

    local -a sudo_cmd=()
    if [[ "${EUID}" -ne 0 ]]; then
        if command -v sudo &>/dev/null; then
            sudo_cmd=(sudo)
        else
            warn "sudo bulunamadı; Docker CLI paketleri otomatik kurulamadı."
            return 1
        fi
    fi

    if [[ "$NO_INTERACTION" == true ]]; then
        if [[ "${#sudo_cmd[@]}" -gt 0 ]] && ! sudo -n true >/dev/null 2>&1; then
            warn "--ci/--no-interaction modunda Docker CLI kurulumu için parolasız sudo yok. Manuel: sudo apt-get install docker-ce-cli docker-buildx-plugin docker-compose-plugin"
            return 1
        fi
    fi

    info "Docker CLI resmi Docker APT deposundan kuruluyor (${docker_platform}/${docker_codename})."
    "${sudo_cmd[@]}" apt-get update
    "${sudo_cmd[@]}" env DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends ca-certificates curl gnupg
    "${sudo_cmd[@]}" install -m 0755 -d /etc/apt/keyrings

    local keyring="/etc/apt/keyrings/docker-${docker_platform}.asc"
    local key_tmp=""
    key_tmp=$(mktemp)
    if ! curl -fsSL --retry 3 --retry-all-errors "https://download.docker.com/linux/${docker_platform}/gpg" -o "$key_tmp"; then
        rm -f "$key_tmp"
        warn "Docker APT GPG anahtarı indirilemedi."
        return 1
    fi
    "${sudo_cmd[@]}" install -m 0644 "$key_tmp" "$keyring"
    rm -f "$key_tmp"

    printf 'deb [arch=%s signed-by=%s] https://download.docker.com/linux/%s %s stable\n' \
        "$(dpkg --print-architecture)" "$keyring" "$docker_platform" "$docker_codename" | \
        "${sudo_cmd[@]}" tee /etc/apt/sources.list.d/docker.list >/dev/null

    "${sudo_cmd[@]}" apt-get update
    "${sudo_cmd[@]}" env DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        docker-ce-cli docker-buildx-plugin docker-compose-plugin

    if docker_cli_healthy; then
        ok "Docker CLI kuruldu: $(docker --version)"
    else
        warn "Docker CLI paketleri kuruldu ancak 'docker --version' sağlıklı çalışmadı."
        return 1
    fi

    if docker compose version &>/dev/null; then
        ok "Docker Compose v2 hazır: $(docker compose version)"
    else
        warn "Docker Compose v2 eklentisi kurulum sonrası doğrulanamadı."
    fi
}

wsl_powershell_read() {
    local ps_command="$1"
    powershell.exe -NoProfile -Command "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8; \$OutputEncoding=[System.Text.Encoding]::UTF8; $ps_command" 2>/dev/null \
        | tr -d '\r' | tail -n1
}

ensure_docker_cli_available() {
    DOCKER_CLI_WSL_WARNED="${DOCKER_CLI_WSL_WARNED:-false}"
    local mode="${DOCKER_CLI_INSTALL_MODE:-auto}"
    case "$mode" in
        auto|always|never) ;;
        true|yes|1) mode="always" ;;
        false|no|0) mode="never" ;;
        *)
            warn "DOCKER_CLI_INSTALL_MODE=${mode} geçersiz; auto kabul edilecek. Desteklenen: auto|always|never."
            mode="auto"
            ;;
    esac

    if docker_cli_healthy; then
        ok "Docker CLI hazır: $(docker --version)"
        return 0
    fi

    if [[ "$mode" == "never" ]]; then
        warn "Docker CLI bulunamadı/sağlıksız; DOCKER_CLI_INSTALL_MODE=never olduğu için otomatik kurulum atlandı."
        return 1
    fi

    if [[ "$WSL2" == true && "$mode" != "always" ]]; then
        if [[ "$DOCKER_CLI_WSL_WARNED" != "true" ]]; then
            warn "WSL2 ortamında Docker CLI bulunamadı. Öncelik Docker Desktop WSL Integration olmalı; otomatik APT kurulumu için --install-docker-cli veya DOCKER_CLI_INSTALL=always kullanın."
            DOCKER_CLI_WSL_WARNED="true"
        fi
        return 1
    fi

    install_docker_cli_from_apt
}

    ensure_current_user_in_docker_group() {
    local current_user="${USER:-$(id -un 2>/dev/null || true)}"
    [[ -n "$current_user" ]] || return 0

    if ! getent group docker >/dev/null 2>&1; then
        return 0
    fi

    if id -nG "$current_user" 2>/dev/null | tr ' ' '\n' | grep -qx "docker"; then
        return 0
    fi

    if ! command -v sudo >/dev/null 2>&1; then
        warn "Kullanıcı '${current_user}' docker grubunda değil; sudo bulunamadığı için otomatik ekleme atlandı."
        return 0
    fi

    info "Kullanıcı '${current_user}' docker grubuna ekleniyor (usermod -aG docker)."
    if [[ "$NO_INTERACTION" == true ]]; then
        if ! sudo -n usermod -aG docker "$current_user" >/dev/null 2>&1; then
            warn "--ci/--no-interaction modunda docker grubu güncellenemedi (sudo parolasız değil). Manuel komut: sudo usermod -aG docker $current_user"
            return 0
        fi
    else
        if ! sudo usermod -aG docker "$current_user"; then
            warn "Kullanıcı docker grubuna eklenemedi. Manuel komut: sudo usermod -aG docker $current_user"
            return 0
        fi
    fi

    ok "Kullanıcı '${current_user}' docker grubuna eklendi."
    info "Grup üyeliğinin etkili olması için oturumu kapatıp yeniden açın veya 'newgrp docker' çalıştırın."
}


# shellcheck disable=SC2120 # opsiyonel pozisyonel argümanlar; testler özel dosya yolu geçebilir.
persist_run_gpu_stress_dotenv() {
    [[ "${RUN_GPU_STRESS:-0}" == "1" ]] || return 0

    local target_env_file="${1:-${SCRIPT_DIR}/.env.development}"
    local example_env_file="${2:-${SCRIPT_DIR}/.env.development.example}"
    local target_label
    target_label="$(basename "$target_env_file")"

    if [[ ! -f "$target_env_file" ]]; then
        if [[ -f "$example_env_file" ]]; then
            cp "$example_env_file" "$target_env_file"
            chmod 600 "$target_env_file" 2>/dev/null || true
            ok "${target_label} dosyası $(basename "$example_env_file") üzerinden RUN_GPU_STRESS senkronizasyonu için oluşturuldu."
        else
            mkdir -p "$(dirname "$target_env_file")"
            : > "$target_env_file"
            chmod 600 "$target_env_file" 2>/dev/null || true
            ok "${target_label} dosyası RUN_GPU_STRESS senkronizasyonu için oluşturuldu."
        fi
    fi

    if grep -q '^RUN_GPU_STRESS=' "$target_env_file" 2>/dev/null; then
        sed_inplace 's|^RUN_GPU_STRESS=.*|RUN_GPU_STRESS=1|' "$target_env_file"
    else
        printf '\nRUN_GPU_STRESS=1\n' >> "$target_env_file"
    fi
    ok "${target_label}: RUN_GPU_STRESS=1 kalıcı hale getirildi."
}


# ── Sistem ve Donanım Bağımlılıkları ──────────────────────────────────────────
install_system_dependencies() {
    step "Temel Sistem Paketlerinin Kurulumu"
    local node_target_major=""
    node_target_major="$(resolve_target_node_major)"
    local node_target_series="node_${node_target_major}.x"
    local node_brew_formula="node@${node_target_major}"

    if command -v apt-get &>/dev/null && command -v sudo &>/dev/null; then
        info "Linux temel paketleri kuruluyor (tam sistem upgrade atlanır)..."
        local -a ns_source_files=()
        mapfile -t ns_source_files < <(sudo sh -c "grep -Rsl 'deb .*deb.nodesource.com/${node_target_series}' /etc/apt/sources.list /etc/apt/sources.list.d 2>/dev/null" || true)
        if [[ "${#ns_source_files[@]}" -gt 0 ]]; then
            local -a ns_needs_normalize_files=()
            mapfile -t ns_needs_normalize_files < <(sudo sh -c "grep -Rsl 'deb .*deb.nodesource.com/${node_target_series}' /etc/apt/sources.list /etc/apt/sources.list.d 2>/dev/null | xargs -r grep -LE 'deb(\\s+\\[[^]]+\\])?\\s+https?://deb\\.nodesource\\.com/${node_target_series}\\s+nodistro\\s+main'" || true)
            local src_file=""
            if [[ "${#ns_needs_normalize_files[@]}" -gt 0 ]]; then
                for src_file in "${ns_needs_normalize_files[@]}"; do
                    sudo sed -E -i \
                        "s#(deb(\\s+\\[[^]]+\\])?\\s+https?://deb\\.nodesource\\.com/${node_target_series})\\s+[[:alnum:]_.-]+\\s+main#\\1 nodistro main#g" \
                        "$src_file"
                done
                ok "NodeSource apt girdileri nodistro formatına normalize edildi (${#ns_needs_normalize_files[@]} dosya)."
            else
                debug "NodeSource apt girdileri zaten nodistro formatında; normalize adımı değişiklik yapmadan atlandı."
            fi
        fi

        if ! sudo DEBIAN_FRONTEND=noninteractive apt-get -o Acquire::Retries=3 update -y; then
            warn "apt update başarısız oldu. NodeSource listesi sıfırlanıp tekrar denenecek..."
            sudo rm -f /etc/apt/sources.list.d/nodesource.list
            sudo DEBIAN_FRONTEND=noninteractive apt-get -o Acquire::Retries=3 update -y
        fi
        info "Gerekli temel paketler (curl, wget, git, zstd vb.) kuruluyor..."
        sudo DEBIAN_FRONTEND=noninteractive apt-get -o Acquire::Retries=3 install -y \
            curl wget git build-essential shellcheck bats software-properties-common zstd ca-certificates gnupg jq \
            postgresql-client-common postgresql-client

        ensure_docker_cli_available || warn "Docker CLI otomatik kurulamadı; Docker gerektiren adımlar manuel kurulumdan sonra çalıştırılabilir."

        info "Node.js (v${node_target_major}.x) durumu kontrol ediliyor..."
        local node_bin=""
        node_bin="$(resolve_native_binary_path node || true)"
        if [[ -n "$node_bin" ]] && "$node_bin" -v | grep -q "^v${node_target_major}\\."; then
            ok "Node.js ${node_target_major}.x zaten kurulu: $("$node_bin" -v)"
        else
            if [[ -z "$node_bin" ]] && command -v node &>/dev/null; then
                warn "Sadece Windows Interop Node.js bulundu ($(command -v node)). Linux Node.js kurulacak."
            fi
            info "Node.js ${node_target_major}.x için izole kurulum (Volta/NVM) deneniyor..."
            local install_home="${HOME:-$TARGET_DIR}"
            local volta_home="${VOLTA_HOME:-$install_home/.volta}"
            local nvm_dir="${NVM_DIR:-$install_home/.nvm}"
            local isolated_node_ready=false

            if [[ -x "${volta_home}/bin/volta" ]]; then
                info "Volta bulundu, Node.js ${node_target_major}.x kurulumu güncelleniyor..."
            else
                info "Volta bulunamadı; kullanıcı dizinine kuruluyor (${volta_home})."
                DOWNLOADED_SCRIPT_FILE=""
                if download_verified_script_soft \
                    "https://get.volta.sh" \
                    "${VOLTA_INSTALL_SHA256:-}" \
                    "volta_install" \
                    && validate_downloaded_script_file "$DOWNLOADED_SCRIPT_FILE" "volta_install"; then
                    bash "$DOWNLOADED_SCRIPT_FILE" || warn "Volta kurulumu başarısız oldu; NVM fallback denenecek."
                    rm -f "$DOWNLOADED_SCRIPT_FILE"
                else
                    warn "Volta kurulum betiği doğrulanamadı; NVM fallback denenecek."
                fi
            fi

            if [[ -x "${volta_home}/bin/volta" ]]; then
                export VOLTA_HOME="$volta_home"
                export PATH="${VOLTA_HOME}/bin:${PATH}"
                if "${VOLTA_HOME}/bin/volta" install "node@${node_target_major}" >/dev/null 2>&1; then
                    node_bin="$(resolve_native_binary_path node || true)"
                    if [[ -n "$node_bin" ]] && "$node_bin" -v | grep -q "^v${node_target_major}\\."; then
                        isolated_node_ready=true
                        ok "Node.js Volta ile izole şekilde kuruldu: $("$node_bin" -v)"
                    fi
                fi
            fi

            if [[ "$isolated_node_ready" != true ]]; then
                info "Volta ile Node.js kurulamadı; NVM fallback deneniyor..."
                mkdir -p "$nvm_dir"
                if [[ -s "${nvm_dir}/nvm.sh" ]]; then
                    debug "NVM zaten kurulu görünüyor: ${nvm_dir}"
                else
                    DOWNLOADED_SCRIPT_FILE=""
                    if download_verified_script_soft \
                        "https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.3/install.sh" \
                        "${NVM_INSTALL_SHA256:-}" \
                        "nvm_install" \
                        && validate_downloaded_script_file "$DOWNLOADED_SCRIPT_FILE" "nvm_install"; then
                        bash "$DOWNLOADED_SCRIPT_FILE" || warn "NVM kurulumu başarısız oldu."
                        rm -f "$DOWNLOADED_SCRIPT_FILE"
                    else
                        warn "NVM kurulum betiği doğrulanamadı."
                    fi
                fi

                if [[ -s "${nvm_dir}/nvm.sh" ]]; then
                    # shellcheck source=/dev/null
                    # shellcheck disable=SC1090,SC1091
                    . "${nvm_dir}/nvm.sh"
                    if nvm install "${node_target_major}" >/dev/null 2>&1 && nvm alias default "${node_target_major}" >/dev/null 2>&1; then
                        node_bin="$(resolve_native_binary_path node || true)"
                        if [[ -n "$node_bin" ]] && "$node_bin" -v | grep -q "^v${node_target_major}\\."; then
                            isolated_node_ready=true
                            ok "Node.js NVM ile izole şekilde kuruldu: $("$node_bin" -v)"
                        fi
                    fi
                fi
            fi

            if [[ "$isolated_node_ready" == true ]]; then
                info "Node.js izole kurulum tamamlandı; apt tabanlı NodeSource adımı atlanıyor."
            else
                warn "İzole Node.js kurulumu başarısız oldu; NodeSource apt fallback devreye alınıyor..."
                info "Node.js ${node_target_major}.x (NodeSource nodistro) kuruluyor..."
            local ns_keyring="/etc/apt/keyrings/nodesource.gpg"
            local ns_repo_file="/etc/apt/sources.list.d/nodesource.list"
            local ns_pref_file="/etc/apt/preferences.d/nodesource.pref"
            local ns_key_tmp=""
            local ns_ready=false

            ns_key_tmp=$(mktemp)
            if curl -fsSL --retry 3 --retry-delay 2 --retry-connrefused \
                "https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key" -o "$ns_key_tmp"; then
                sudo install -m 0755 -d /etc/apt/keyrings
                if gpg --dearmor < "$ns_key_tmp" | sudo tee "$ns_keyring" >/dev/null; then
                    sudo chmod 0644 "$ns_keyring"
                    sudo rm -f "$ns_repo_file"
                    echo "deb [signed-by=${ns_keyring}] https://deb.nodesource.com/${node_target_series} nodistro main" | sudo tee "$ns_repo_file" >/dev/null
                    sudo chmod 0644 "$ns_repo_file"
                    sudo tee "$ns_pref_file" >/dev/null <<'EOF'
Package: nodejs
Pin: origin deb.nodesource.com
Pin-Priority: 1001
EOF
                    sudo chmod 0644 "$ns_pref_file"
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
                node_bin="$(resolve_native_binary_path node || true)"
                local installed_node_version=""
                local installed_node_major=""
                if [[ -n "$node_bin" ]]; then
                    installed_node_version="$("$node_bin" --version 2>/dev/null || true)"
                fi
                installed_node_major="$(echo "$installed_node_version" | grep -oE '[0-9]+' | head -n1 || true)"
                if sudo apt-cache policy nodejs 2>/dev/null | grep -qi 'nodesource'; then
                    ok "Node.js NodeSource üzerinden kuruldu: ${installed_node_version:-sürüm alınamadı}"
                else
                    warn "Node.js kurulumu tamamlandı ancak aktif paket kaynağı NodeSource görünmüyor: ${installed_node_version:-sürüm alınamadı}."
                fi
                if [[ -n "$installed_node_major" && "$installed_node_major" != "$node_target_major" ]]; then
                    warn "Node.js sürüm sapması tespit edildi: hedef ${node_target_major}.x, aktif ${installed_node_version}. React build uyumluluğu için Node.js ${node_target_major}.x önerilir (.nvmrc)."
                fi
            else
                warn "NodeSource üzerinden Node.js kurulamadı, varsayılan apt deposu deneniyor..."
                node_bin="$(resolve_native_binary_path node || true)"
                if [[ -n "$node_bin" ]]; then
                    warn "Sistemde node bulundu ($("$node_bin" -v 2>/dev/null || echo 'sürüm alınamadı'))."
                    warn "nodejs + npm çakışmasını önlemek için apt ile npm zorla kurulmayacak."
                    local npm_bin=""
                    npm_bin="$(resolve_native_binary_path npm || true)"
                    if [[ -n "$npm_bin" ]]; then
                        ok "npm zaten mevcut: $("$npm_bin" -v 2>/dev/null || echo 'sürüm alınamadı')"
                    else
                        warn "npm bulunamadı. NodeSource nodejs paketi npm içerir; PATH/kurulum durumu kontrol edilmeli."
                    fi
                else
                    sudo DEBIAN_FRONTEND=noninteractive apt-get -o Acquire::Retries=3 install -y nodejs npm
                fi
            fi
            fi
        fi

        info "Kamera ve ses kütüphaneleri kuruluyor..."
        local -a linux_media_pkgs=(
            portaudio19-dev alsa-utils v4l-utils ffmpeg
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
    elif command -v pacman &>/dev/null; then
        warn "Arch tabanlı sistem tespit edildi. Paketler pacman ile kuruluyor..."
        sudo pacman -Sy --noconfirm --needed \
            curl wget git zstd nodejs npm portaudio alsa-utils v4l-utils ffmpeg
        node_bin="$(resolve_native_binary_path node || true)"
        if [[ -n "$node_bin" ]]; then
            NODE_MAJOR="$("$node_bin" -v | sed 's/^v//' | cut -d. -f1)"
            if [[ "$NODE_MAJOR" -lt "$node_target_major" ]]; then
                warn "Arch depolarındaki Node.js sürümü hedefin altında olabilir: $("$node_bin" -v) (hedef: ${node_target_major}.x+)."
            else
                ok "Node.js sürümü uygun: $("$node_bin" -v)"
            fi
        fi
        info "Host PostgreSQL/Redis servis kurulumu atlandı. Servisleri Docker Compose ile yönetin."
    elif command -v zypper &>/dev/null; then
        warn "OpenSUSE/SLES tabanlı sistem tespit edildi. Paketler zypper ile kuruluyor..."
        sudo zypper --non-interactive refresh
        sudo zypper --non-interactive install --no-recommends \
            curl wget git zstd nodejs npm portaudio19-devel alsa-utils v4l-utils ffmpeg
        node_bin="$(resolve_native_binary_path node || true)"
        if [[ -n "$node_bin" ]]; then
            NODE_MAJOR="$("$node_bin" -v | sed 's/^v//' | cut -d. -f1)"
            if [[ "$NODE_MAJOR" -lt "$node_target_major" ]]; then
                warn "OpenSUSE depolarındaki Node.js sürümü hedefin altında olabilir: $("$node_bin" -v) (hedef: ${node_target_major}.x+)."
            else
                ok "Node.js sürümü uygun: $("$node_bin" -v)"
            fi
        fi
        info "Host PostgreSQL/Redis servis kurulumu atlandı. Servisleri Docker Compose ile yönetin."
    elif command -v brew &>/dev/null; then
        warn "macOS (Homebrew) ortamı tespit edildi. Paketler brew ile kuruluyor..."
        brew update
        brew install \
            curl wget git zstd "${node_brew_formula}" ffmpeg portaudio || warn "Bazı Homebrew paketleri kurulamadı; eksikleri manuel tamamlayın."
        info "Host Redis kurulumu atlandı. Servisleri Docker Compose ile yönetmeniz önerilir."

        if brew list "${node_brew_formula}" &>/dev/null; then
            info "Node.js ${node_target_major} için brew link işlemi deneniyor..."
            brew link --overwrite --force "${node_brew_formula}" >/dev/null 2>&1 || true
            ok "Node.js sürümü: $(node --version 2>/dev/null || echo 'sürüm alınamadı')"
        fi

        info "brew services ile host PostgreSQL/Redis başlatma adımı kaldırıldı (Docker Compose tercih ediliyor)."

        ok "Homebrew tabanlı bağımlılık kurulumu tamamlandı."
    else
        warn "Desteklenen paket yöneticileri (apt/dnf/pacman/zypper/brew) bulunamadı. Lütfen paketleri manuel kurun:"
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

    info "Kurulum yöneticisi: yalnızca uv venv akışı kullanılacak; eski paket yöneticisi tabanlı ortam kurulumları devre dışı."
    info "Not: install_sidar.sh betiğini sudo ile çalıştırmayın; gerekli yerde sudo apt-get çağrılarını betik kendisi yapar."

    if [[ "${EUID:-$(id -u)}" -eq 0 ]]; then
        fail "Bu betik root/sudo ile çalıştırılamaz. Lütfen normal kullanıcı ile çalıştırın: ./install_sidar.sh"
    fi

    local script_owner=""
    script_owner="$(stat -c %U "$SCRIPT_DIR" 2>/dev/null || true)"
    if [[ -n "$script_owner" && "$script_owner" != "${USER:-$(id -un)}" ]]; then
        fail "Dizin sahipliği mevcut kullanıcıyla uyumsuz (owner=$script_owner, user=${USER:-$(id -un)}). Düzeltme: sudo chown -R ${USER:-$(id -un)}:${USER:-$(id -un)} \"$SCRIPT_DIR\""
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
            if sudo apt-get update && sudo apt-get install -y ffmpeg; then
                ok "FFmpeg otomatik kuruldu."
            else
                warn "FFmpeg otomatik kurulamadı, manuel kurunuz."
            fi
        elif command -v apt-get &>/dev/null; then
            info "Kurulum için: sudo apt-get update && sudo apt-get install -y ffmpeg"
        elif command -v dnf &>/dev/null; then
            info "Kurulum için: sudo dnf install -y ffmpeg ffmpeg-devel"
        elif command -v pacman &>/dev/null; then
            info "Kurulum için: sudo pacman -Sy --noconfirm --needed ffmpeg"
        elif command -v zypper &>/dev/null; then
            info "Kurulum için: sudo zypper --non-interactive install ffmpeg"
        elif command -v brew &>/dev/null; then
            info "Kurulum için: brew install ffmpeg"
        else
            warn "Paket yöneticisi otomatik tespit edilemedi. FFmpeg'i sisteminize manuel kurun."
        fi
    fi

    # Docker / Docker Compose (özet komutları için önerilir)
    ensure_docker_cli_available || true

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
        ensure_current_user_in_docker_group
        if ensure_docker_daemon_running; then
            ok "Docker daemon çalışıyor."
            verify_wsl_integration_listed || true
	        else
	            warn "Docker daemon başlatılamadı. Docker Desktop/service durumunu kontrol edin."
	            verify_wsl_integration_listed || true
	            if [[ "$NO_INTERACTION" == true || "$AUTO_INSTALL" == true ]]; then
	                local backend_missing=false
	                if [[ "$WSL2" == true ]] && command -v powershell.exe &>/dev/null; then
	                    local wsl_distros_snapshot
	                    wsl_distros_snapshot="$(powershell.exe -NoProfile -Command "[Console]::OutputEncoding=[Text.Encoding]::UTF8; wsl.exe -l -q" 2>/dev/null | iconv -f UTF-16LE -t UTF-8 2>/dev/null | tr -d '\0\r')"
	                    if ! printf '%s\n' "$wsl_distros_snapshot" | awk 'NF {print}' | grep -Eq '^docker-desktop(-data)?$'; then
	                        backend_missing=true
	                    fi
	                fi
	                if [[ "$backend_missing" == true ]]; then
	                    fail "Docker daemon erişilemedi: Docker Desktop backend distro'su (docker-desktop / docker-desktop-data) WSL2'de kayıtlı değil. Etkileşimsiz modda otomatik düzeltilemez; Docker Desktop > Settings > Troubleshoot > Reset to factory defaults veya Docker Desktop yeniden kurulum sonrası betiği tekrar çalıştırın."
	                fi
	                fail "Docker daemon erişilemedi ve etkileşimsiz mod aktif (NO_INTERACTION/AUTO_INSTALL). Kurulum fail-fast durduruldu. Kök neden docker-desktop backend yokluğuysa Docker Desktop reset/reinstall gereklidir."
	            fi

            info "Lütfen Docker Desktop'ı manuel başlatın (veya service'i ayağa kaldırın), ardından tek seferlik yeniden deneme yapılacak."
            clear_stdin_buffer
            read -r -p "Docker hazır olduktan sonra [ENTER] tuşuna basın..." 2>/dev/tty

            local manual_retry_timeout=30

            if DOCKER_DESKTOP_READY_TIMEOUT="$manual_retry_timeout" ensure_docker_daemon_running; then
                ok "Docker daemon manuel müdahale sonrası erişilebilir."
                verify_wsl_integration_listed || true
            else
                fail "Docker daemon manuel yeniden denemeden sonra da erişilemedi. Kurulum devam ettirilmiyor."
            fi
        fi
        if docker compose version &>/dev/null; then
            ok "Docker Compose eklentisi mevcut."
        elif command -v docker-compose &>/dev/null; then
            ok "docker-compose (standalone) mevcut."
        else
            warn "Docker Compose bulunamadı. Kurulum: https://docs.docker.com/compose/install/"
        fi
    else
        if [[ "$WSL2" == true ]]; then
            if [[ "$docker_version_error" == *"Input/output error"* ]]; then
                warn "Docker CLI çağrısı Input/output error döndürüyor. WSL entegrasyon mount'ları askıda kalmış olabilir."
            fi
            info "Docker şu anda WSL içinde doğrulanamadı; Docker Desktop entegrasyon kontrolüne geçiliyor."
        else
            warn "Docker bulunamadı veya çalıştırılamıyor. Docker komutları (örn. docker compose up sidar-gpu) çalışmayacaktır."
        fi
    fi

    # Sistem Python sürümü artık doğrulanmaz: uv, gerekli Python sürümünü izole
    # ortam için kendisi çözer/indirir ve proje sürümünü .python-version veya
    # pyproject.toml üzerinden create_uv_venv içinde uygular.

    if [[ "$WSL2" == true ]]; then
        info "WSL2 ortamı tespit edildi."
    fi

    if [[ "$WSL2" == true ]] && ! (command -v docker &>/dev/null && [[ "$docker_version_check_ok" == true ]]); then

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
            info "Docker şu anda WSL içinde kullanılamıyor; yeni bir dağıtım sonrası Docker Desktop entegrasyonu kopmuş olabilir."
            info "WSL Integration otomatik düzeltmesi denendi. Lütfen doğrulama için şu adımları uygulayın:"
            echo "  1. Windows'ta Docker Desktop'ı açın."
            echo "  2. Settings > Resources > WSL Integration menüsünde '${WSL_DISTRO_NAME:-Ubuntu}' dağıtımının açık olduğunu doğrulayın."
            echo "  3. Gerekirse Apply & restart yapın."
            echo "  4. $(wsl_integration_remediation_message "${WSL_DISTRO_NAME:-Ubuntu}")"
            echo ""
            if [[ "$NO_INTERACTION" == true || "$AUTO_INSTALL" == true ]]; then
                fail "WSL2 Docker Desktop entegrasyonu kapalı ve etkileşimsiz modda manuel onay alınamıyor (NO_INTERACTION/AUTO_INSTALL aktif). Önce entegrasyonu açıp tekrar deneyin."
            else
                clear_stdin_buffer
                read -r -p "Entegrasyonu tamamladıktan sonra devam etmek için [ENTER] tuşuna basın..." 2>/dev/tty
            fi

            # Kullanıcıdan onay sonrası tekrar doğrula
            if ! command -v docker &>/dev/null; then
                fail "[ENTER] sonrası docker CLI hâlâ bulunamadı. $(wsl_integration_remediation_message "${WSL_DISTRO_NAME:-Ubuntu}")"
            fi
            if ! docker_cli_healthy; then
                fail "[ENTER] sonrası docker CLI hâlâ sağlıksız. Docker Desktop entegrasyonunu ve WSL erişimini doğrulayın."
            fi
            if ! docker info &>/dev/null; then
                fail "[ENTER] sonrası docker daemon erişilemedi (docker info başarısız). $(wsl_integration_remediation_message "${WSL_DISTRO_NAME:-Ubuntu}")"
            fi
            ok "WSL2 Docker Desktop entegrasyonu doğrulandı (docker CLI + docker info)."
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

    _ollama_install_step
}

# ── 2. NVIDIA GPU tespiti ────────────────────────────────────────────────────
# detect_gpu, detect_cuda_driver_capability, detect_pytorch_runtime_cuda_version
# ve configure_wsl2_cuda_library_paths tek kaynak olarak utils/gpu_utils.sh
# içinden yüklenir. Bu faz yalnız NVIDIA Container Toolkit kurulumunu sürdürür.

# ── NVIDIA Container Toolkit Kurulumu ──────────────────────────────────────────
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

