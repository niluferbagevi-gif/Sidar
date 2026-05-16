#!/usr/bin/env bash
# Sidar installer phase 01: base operating-system package bootstrap.

# ── 0. Sistem bağımlılıkları ─────────────────────────────────────────────────
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
            info "NodeSource apt girdileri nodistro formatına normalize ediliyor..."
            local src_file=""
            for src_file in "${ns_source_files[@]}"; do
                sudo sed -E -i \
                    "s#(deb(\\s+\\[[^]]+\\])?\\s+https?://deb\\.nodesource\\.com/${node_target_series})\\s+[[:alnum:]_.-]+\\s+main#\\1 nodistro main#g" \
                    "$src_file"
            done
        fi

        if ! sudo DEBIAN_FRONTEND=noninteractive apt-get -o Acquire::Retries=3 update -y; then
            warn "apt update başarısız oldu. NodeSource listesi sıfırlanıp tekrar denenecek..."
            sudo rm -f /etc/apt/sources.list.d/nodesource.list
            sudo DEBIAN_FRONTEND=noninteractive apt-get -o Acquire::Retries=3 update -y
        fi
        info "Gerekli temel paketler (curl, wget, git, zstd vb.) kuruluyor..."
        sudo DEBIAN_FRONTEND=noninteractive apt-get -o Acquire::Retries=3 install -y \
            curl wget git build-essential software-properties-common zstd ca-certificates gnupg \
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
            info "Node.js ${node_target_major}.x (NodeSource nodistro) kuruluyor..."
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
                    echo "deb [signed-by=${ns_keyring}] https://deb.nodesource.com/${node_target_series} nodistro main" | sudo tee "$ns_repo_file" >/dev/null
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
