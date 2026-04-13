#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════════
# Sidar AI — Kurulum Betiği (install_sidar.sh)
# Sürüm : 5.2.0
# Hedef : WSL2 / Ubuntu / Conda + NVIDIA RTX 30xx/40xx (CUDA 13.x)
#
# Kullanım:
#   chmod +x install_sidar.sh
#   ./install_sidar.sh           # standart kurulum
#   ./install_sidar.sh --dev     # geliştirici bağımlılıklarıyla
#   ./install_sidar.sh --cpu     # GPU algılansa bile CPU zorla
# ═══════════════════════════════════════════════════════════════════════════════
set -euo pipefail

# ── Renkler ──────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; BOLD='\033[1m'; NC='\033[0m'

ok()   { echo -e "${GREEN}✅  $*${NC}"; }
info() { echo -e "${BLUE}ℹ️   $*${NC}"; }
warn() { echo -e "${YELLOW}⚠️   $*${NC}"; }
fail() { echo -e "${RED}❌  $*${NC}"; exit 1; }
step() { echo -e "\n${BOLD}${BLUE}── $* ──${NC}"; }

# ── Argümanlar ────────────────────────────────────────────────────────────────
INSTALL_DEV=true
FORCE_CPU=false
PLAYWRIGHT_REQUESTED=false
REACT_UI_STATUS="atlandı"
for arg in "$@"; do
    case "$arg" in
        --dev)  INSTALL_DEV=true ;;
        --cpu)  FORCE_CPU=true ;;
        --help|-h)
            echo "Kullanım: $0 [--dev] [--cpu]"
            echo "  --dev  Geliştirici bağımlılıklarını kur"
            echo "  --cpu  GPU algılansa bile CPU modunda kur"
            exit 0
            ;;
        *)      warn "Bilinmeyen argüman: $arg (--dev | --cpu kabul edilir)"; exit 1 ;;
    esac
done

# ── Sabitler ──────────────────────────────────────────────────────────────────
CONDA_ENV_NAME="sidar"
PYTHON_VERSION="3.11"
DEFAULT_DATABASE_URL="postgresql+asyncpg://postgres:postgres@localhost:5432/sidar"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_URL="https://github.com/niluferbagevi-gif/Sidar"
TARGET_DIR="$HOME/Sidar"
REQUIRED_DIRS=(data logs temp sessions chroma_db data/rag data/lora_adapters data/continuous_learning)

banner() {
    echo -e "${BOLD}${BLUE}"
    echo "╔══════════════════════════════════════════════════════════════╗"
    echo "║          Sidar AI — Kurulum Başlıyor (v5.2.0)               ║"
    echo "╚══════════════════════════════════════════════════════════════╝"
    echo -e "${NC}"
}

# ── 0. GitHub deposunu hazırla / güncelle ────────────────────────────────────
sync_repo() {
    step "Sidar projesi GitHub'dan çekiliyor"

    if [[ "$SCRIPT_DIR" == "$TARGET_DIR" && -d "$SCRIPT_DIR/.git" ]]; then
        ok "Kurulum betiği zaten $TARGET_DIR içinde çalışıyor."
        return
    fi

    if [[ ! -d "$TARGET_DIR/.git" ]]; then
        info "Sidar deposu klonlanıyor: $REPO_URL → $TARGET_DIR"
        git clone "$REPO_URL" "$TARGET_DIR"
    else
        warn "Sidar klasörü zaten var. Git pull ile güncelleniyor..."
        (
            cd "$TARGET_DIR"
            git pull --ff-only
        )
    fi

    SCRIPT_DIR="$TARGET_DIR"
    ok "Kurulum dizini güncellendi: $SCRIPT_DIR"
}

# ── Sistem ve Donanım Bağımlılıkları ──────────────────────────────────────────
install_system_dependencies() {
    step "Sistem Güncelleme ve Temel Paketlerin Kurulumu"

    if command -v apt-get &>/dev/null && command -v sudo &>/dev/null; then
        info "Sistem güncelleniyor ve Linux temel paketleri kuruluyor..."
        sudo DEBIAN_FRONTEND=noninteractive apt-get update -y
        sudo DEBIAN_FRONTEND=noninteractive apt-get upgrade -y

        info "Gerekli temel paketler (curl, wget, git, zstd vb.) kuruluyor..."
        sudo DEBIAN_FRONTEND=noninteractive apt-get install -y \
            curl wget git build-essential software-properties-common zstd

        info "Kamera (v4l2) ve Ses (PortAudio/ALSA/FFmpeg) kütüphaneleri kuruluyor..."
        sudo DEBIAN_FRONTEND=noninteractive apt-get install -y \
            portaudio19-dev python3-pyaudio alsa-utils v4l-utils ffmpeg
        info "PostgreSQL istemci/geliştirme bağımlılıkları kuruluyor..."
        sudo DEBIAN_FRONTEND=noninteractive apt-get install -y \
            libpq-dev postgresql-client

        ok "Sistem paketleri ve donanım kütüphaneleri başarıyla kuruldu."
    elif command -v dnf &>/dev/null; then
        warn "RedHat/Fedora tabanlı sistem tespit edildi. Paketler dnf ile kuruluyor..."
        sudo dnf upgrade -y
        sudo dnf install -y curl wget git zstd portaudio-devel alsa-utils v4l-utils ffmpeg postgresql postgresql-devel
    else
        warn "apt-get veya sudo bulunamadı. Lütfen paketleri manuel kurun:"
        info "Gerekenler: zstd portaudio19-dev alsa-utils v4l-utils ffmpeg vb."
    fi
}

# ── 1. Ön koşul kontrolleri ───────────────────────────────────────────────────
check_prerequisites() {
    step "Ön Koşullar Kontrol Ediliyor"

    # Conda kontrolü ve otomatik Miniconda kurulumu
    if command -v conda &>/dev/null; then
        USE_CONDA=true
        ok "Conda $(conda --version | cut -d' ' -f2) zaten yüklü."
    else
        warn "Conda bulunamadı. Miniconda otomatik kurulumu denenecek..."

        OS="$(uname -s)"
        ARCH="$(uname -m)"
        MINICONDA_URL=""
        MINICONDA_INSTALLER="/tmp/miniconda.sh"
        MINICONDA_PREFIX="$HOME/miniconda3"

        case "$OS" in
            Linux)
                case "$ARCH" in
                    x86_64) MINICONDA_URL="https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh" ;;
                    aarch64|arm64) MINICONDA_URL="https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-aarch64.sh" ;;
                esac
                ;;
            Darwin)
                case "$ARCH" in
                    x86_64) MINICONDA_URL="https://repo.anaconda.com/miniconda/Miniconda3-latest-MacOSX-x86_64.sh" ;;
                    arm64) MINICONDA_URL="https://repo.anaconda.com/miniconda/Miniconda3-latest-MacOSX-arm64.sh" ;;
                esac
                ;;
        esac

        if [[ -z "$MINICONDA_URL" ]]; then
            USE_CONDA=false
            warn "Miniconda için desteklenmeyen platform ($OS/$ARCH). uv venv fallback kullanılacak."
        elif ! command -v curl &>/dev/null; then
            USE_CONDA=false
            warn "curl bulunamadı, Miniconda indirilemedi. uv venv fallback kullanılacak."
        else
            info "Miniconda indiriliyor: $MINICONDA_URL"
            if curl -fsSL "$MINICONDA_URL" -o "$MINICONDA_INSTALLER"; then
                if [[ -d "$MINICONDA_PREFIX" ]]; then
                    info "Mevcut dizin bulundu: $MINICONDA_PREFIX (yeniden kurulum atlandı)."
                else
                    info "Miniconda kuruluyor: $MINICONDA_PREFIX"
                    bash "$MINICONDA_INSTALLER" -b -p "$MINICONDA_PREFIX"
                fi
                rm -f "$MINICONDA_INSTALLER"

                # shellcheck disable=SC1091
                source "$MINICONDA_PREFIX/etc/profile.d/conda.sh"
                conda init bash >/dev/null 2>&1 || true
                USE_CONDA=true
                ok "Miniconda kuruldu ve conda aktif edildi: $(conda --version | cut -d' ' -f2)"
            else
                USE_CONDA=false
                warn "Miniconda indirilemedi. uv venv fallback kullanılacak."
            fi
        fi
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
            sudo apt-get update && sudo apt-get install -y ffmpeg || warn "FFmpeg otomatik kurulamadı, manuel kurunuz."
        elif command -v apt-get &>/dev/null; then
            info "Kurulum için: sudo apt-get update && sudo apt-get install -y ffmpeg"
        elif command -v dnf &>/dev/null; then
            info "Kurulum için: sudo dnf install -y ffmpeg ffmpeg-devel"
        elif command -v brew &>/dev/null; then
            info "Kurulum için: brew install ffmpeg"
        else
            warn "Paket yöneticisi otomatik tespit edilemedi. FFmpeg'i sisteminize manuel kurun."
        fi
    fi

    # Docker / Docker Compose (özet komutları için önerilir)
    if command -v docker &>/dev/null; then
        ok "Docker $(docker --version | awk '{print $3}' | tr -d ',')"
        if docker compose version &>/dev/null; then
            ok "Docker Compose eklentisi mevcut."
        elif command -v docker-compose &>/dev/null; then
            ok "docker-compose (standalone) mevcut."
        else
            warn "Docker Compose bulunamadı. Kurulum: https://docs.docker.com/compose/install/"
        fi
    else
        warn "Docker bulunamadı. Docker komutları (örn. docker compose up sidar-gpu) çalışmayacaktır."
    fi

    # Python 3.11+ kontrolü (conda içinde olacak, sadece sistem python denetimi)
    if command -v python3 &>/dev/null; then
        PY_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null || echo "0.0")
        PY_MAJOR=$(echo "$PY_VER" | cut -d. -f1)
        PY_MINOR=$(echo "$PY_VER" | cut -d. -f2)
        if [[ "$PY_MAJOR" -ge 3 && "$PY_MINOR" -ge 11 ]]; then
            ok "Python $PY_VER (sistem)"
        else
            warn "Sistem Python'u $PY_VER — conda ortamı Python $PYTHON_VERSION ile oluşturulacak."
        fi
    fi

    # WSL2 tespiti
    if grep -qi "microsoft" /proc/sys/kernel/osrelease 2>/dev/null; then
        info "WSL2 ortamı tespit edildi."
        WSL2=true
    else
        WSL2=false
    fi

    # Redis (Local Event Bus / cache)
    if ! command -v redis-server &>/dev/null && [[ "$WSL2" == false ]]; then
        warn "Lokal Redis sunucusu bulunamadı. Projenin düzgün çalışması için Redis gereklidir."
        info "Lokal yerine Docker kullanacaksanız bu uyarıyı dikkate almayın."
    fi

    if command -v psql &>/dev/null; then
        ok "PostgreSQL istemcisi hazır: $(psql --version | awk '{print $3}')"
    else
        warn "psql bulunamadı. PostgreSQL kullanımı için postgresql-client/libpq kurulu olmalı."
    fi

    # Ollama (varsayılan AI provider) - Akıllı Kontrol ve Kurulum
    if ! ollama -v &>/dev/null; then
        warn "Ollama bulunamadı veya kurulumu bozuk. İndiriliyor..."
        if command -v sudo &>/dev/null; then
            # Eski bozuk dosya kalıntılarını temizle
            sudo rm -f /usr/local/bin/ollama
            info "Ollama kurulumu başlatılıyor..."
            curl -fsSL https://ollama.com/install.sh | sh
            ok "Ollama başarıyla kuruldu."
        else
            warn "Sudo yetkisi bulunamadı. Kurulum manuel yapılmalı: https://ollama.com"
        fi
    else
        ok "Ollama zaten kurulu."
    fi

    # Servisin anlık olarak yanıt verip vermediğini kontrol et
    if curl -sf http://localhost:11434/api/version &>/dev/null; then
        ok "Ollama API servisi aktif (localhost:11434)."
    else
        warn "Ollama kurulu ancak API servisi şu an yanıt vermiyor."
        info "Model indirmek veya servisi başlatmak için ayrı bir terminalde 'ollama serve' komutunu çalıştırabilirsiniz."
        info "Alternatif olarak .env içinde AI_PROVIDER=gemini veya openai kullanabilirsiniz."
    fi
}

# ── 2. NVIDIA GPU tespiti ────────────────────────────────────────────────────
detect_gpu() {
    step "GPU Tespiti"
    GPU_AVAILABLE=false
    CUDA_VERSION=""

    if [[ "$FORCE_CPU" == true ]]; then
        warn "--cpu bayrağı: GPU kullanımı devre dışı bırakıldı."
        return
    fi

    if command -v nvidia-smi &>/dev/null && nvidia-smi &>/dev/null 2>&1; then
        GPU_NAME=$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -1 || echo "Bilinmiyor")
        VRAM_MB=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits 2>/dev/null | head -1 | tr -d ' ' || echo "0")
        CUDA_VERSION=$(nvidia-smi 2>/dev/null | grep -oP 'CUDA Version: \K[\d.]+' | head -1 || echo "")
        DRIVER_VER=$(nvidia-smi --query-gpu=driver_version --format=csv,noheader 2>/dev/null | head -1 || echo "")

        GPU_AVAILABLE=true
        ok "GPU     : $GPU_NAME"
        ok "VRAM    : ${VRAM_MB} MiB"
        ok "Sürücü  : $DRIVER_VER"
        ok "CUDA    : $CUDA_VERSION"

        if [[ "$WSL2" == true ]]; then
            info "WSL2 üzerinde CUDA, Windows NVIDIA sürücüsü (libcuda.so) üzerinden erişilir."
        fi
    else
        warn "NVIDIA GPU bulunamadı veya nvidia-smi erişilemez — CPU modunda kurulum yapılacak."
    fi
}

# ── NVIDIA Container Toolkit Kurulumu ──────────────────────────────────────────
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

            # WSL2 veya Native Ubuntu için Docker'ı yeniden başlat
            info "Docker servisi yeniden başlatılıyor..."
            if command -v systemctl &>/dev/null && systemctl is-active --quiet docker; then
                sudo systemctl restart docker
            else
                sudo service docker restart || true
            fi
            ok "nvidia-container-toolkit kuruldu ve Docker yapılandırıldı."
        else
            ok "nvidia-container-toolkit zaten kurulu."
        fi
    fi
}

# ── 3. Conda ortamı oluştur / güncelle ───────────────────────────────────────
setup_python_env() {
    if [[ "$USE_CONDA" == true ]]; then
        step "Conda Ortamı: $CONDA_ENV_NAME"

        # Conda init scriptini kaynak al (conda activate çalışması için gerekli)
        CONDA_BASE=$(conda info --base 2>/dev/null) || fail "conda info başarısız oldu."
        # shellcheck disable=SC1091
        source "$CONDA_BASE/etc/profile.d/conda.sh"

        if conda env list | grep -q "^${CONDA_ENV_NAME}\s"; then
            info "Mevcut conda ortamı bulundu: $CONDA_ENV_NAME — güncelleniyor..."
            conda env update -n "$CONDA_ENV_NAME" -f "$SCRIPT_DIR/environment.yml" --prune
            ok "Conda ortamı güncellendi."
        else
            info "Yeni conda ortamı oluşturuluyor: $CONDA_ENV_NAME (Python $PYTHON_VERSION)..."
            conda env create -f "$SCRIPT_DIR/environment.yml"
            ok "Conda ortamı oluşturuldu."
        fi

        conda activate "$CONDA_ENV_NAME"
        ok "Ortam aktif: $(conda info --envs | grep '\*' | awk '{print $1}')"
    else
        step "uv venv Ortamı"
        VENV_DIR="$SCRIPT_DIR/.venv"
        if [[ -d "$VENV_DIR" ]]; then
            info "Mevcut uv venv bulundu: $VENV_DIR"
        else
            info "Yeni uv venv oluşturuluyor ($PYTHON_VERSION)..."
            uv venv --python "$PYTHON_VERSION" "$VENV_DIR"
            ok "uv venv oluşturuldu."
        fi
        # shellcheck disable=SC1091
        source "$VENV_DIR/bin/activate"
        ok "Ortam aktif: $VENV_DIR"
    fi
}

# ── 4. uv kurulumu / güncelleme ──────────────────────────────────────────────
setup_uv() {
    step "uv Paket Yöneticisi"

    if ! command -v uv &>/dev/null; then
        info "uv bulunamadı — pip ile kuruluyor..."
        pip install --quiet "uv>=0.5.0"
    fi
    ok "uv $(uv --version | cut -d' ' -f2)"
}

# ── 5. Python bağımlılıklarını kur ───────────────────────────────────────────
install_python_deps() {
    step "Python Bağımlılıkları Kuruluyor"

    cd "$SCRIPT_DIR"

    # Reproducible kurulum için lock dosyası önceliklidir
    if [[ -f "$SCRIPT_DIR/uv.lock" ]]; then
        info "uv.lock bulundu — kilitli bağımlılıklar ile kurulum yapılıyor (uv sync --frozen)."
        SYNC_ARGS=(--frozen)
        if [[ "$INSTALL_DEV" == true ]]; then
            SYNC_ARGS+=(--extra dev)
        fi
        uv sync "${SYNC_ARGS[@]}"
        ok "Python bağımlılıkları uv.lock ile senkronlandı."
        return
    fi

    if [[ "$GPU_AVAILABLE" == true && -n "$CUDA_VERSION" ]]; then
        # CUDA major version'ı belirle (örn. 13.2 → cu130)
        CUDA_MAJOR=$(echo "$CUDA_VERSION" | cut -d. -f1)
        CUDA_MINOR=$(echo "$CUDA_VERSION" | cut -d. -f2)

        # PyTorch wheel dizini: cu130, cu121, cu124 gibi
        if   [[ "$CUDA_MAJOR" -ge 13 ]]; then TORCH_CU="cu130"
        elif [[ "$CUDA_MAJOR" -eq 12 && "$CUDA_MINOR" -ge 4 ]]; then TORCH_CU="cu124"
        elif [[ "$CUDA_MAJOR" -eq 12 ]]; then TORCH_CU="cu121"
        else TORCH_CU=""
        fi

        info "GPU kurulumu yapılıyor..."
        if [[ "$INSTALL_DEV" == true ]]; then
            INSTALL_SPEC=(-e ".[all,dev]")
        else
            INSTALL_SPEC=(-e ".[all]")
        fi
        PLAYWRIGHT_REQUESTED=true

        if [[ -n "$TORCH_CU" ]]; then
            info "GPU kurulumu: CUDA $CUDA_VERSION → PyTorch wheel: $TORCH_CU"
            uv pip install \
                --index-strategy unsafe-best-match \
                --extra-index-url "https://download.pytorch.org/whl/${TORCH_CU}" \
                "${INSTALL_SPEC[@]}"
        else
            warn "CUDA $CUDA_VERSION için PyTorch wheel URL'i belirlenemedi — PyPI'dan kuruluyor."
            uv pip install "${INSTALL_SPEC[@]}"
        fi
    else
        info "CPU modu kuruluyor..."
        if [[ "$INSTALL_DEV" == true ]]; then
            INSTALL_SPEC=(-e ".[dev]")
        else
            INSTALL_SPEC=(-e ".")
        fi
        uv pip install "${INSTALL_SPEC[@]}"
    fi

    ok "Python bağımlılıkları kuruldu."
}

# ── 6. Playwright tarayıcı motorları ─────────────────────────────────────────
install_playwright_browsers() {
    step "Playwright Tarayıcı Motorları"

    if [[ "$INSTALL_DEV" == true || "$PLAYWRIGHT_REQUESTED" == true ]]; then
        if python -c "import playwright" >/dev/null 2>&1; then
            info "Chromium ve Firefox motorları kuruluyor..."
            if python -m playwright install --with-deps chromium firefox; then
                ok "Playwright motorları kuruldu (chromium, firefox)."
            else
                warn "Playwright motor kurulumu başarısız oldu veya atlandı. Manuel komut: python -m playwright install --with-deps chromium firefox"
            fi
        else
            info "playwright paketi bu profilde kurulmadı — tarayıcı motor kurulumu atlandı."
        fi
    else
        info "Playwright kurulumu bu profil için talep edilmedi — tarayıcı motor kurulumu atlandı."
    fi
}

# ── 7. React Web UI bağımlılıkları ve build ──────────────────────────────────
setup_react_frontend() {
    step "React Web Arayüzü"

    REACT_DIR="$SCRIPT_DIR/web_ui_react"
    if [[ ! -d "$REACT_DIR" ]]; then
        info "web_ui_react dizini bulunamadı — frontend kurulumu atlandı."
        REACT_UI_STATUS="dizin_yok"
        return
    fi

    if [[ ! -f "$REACT_DIR/package.json" ]]; then
        info "web_ui_react/package.json bulunamadı — frontend kurulumu atlandı."
        REACT_UI_STATUS="package_json_yok"
        return
    fi

    if ! command -v npm &>/dev/null; then
        warn "npm bulunamadı. React Web UI için Node.js + npm kurun ve şu komutları çalıştırın:"
        echo "       cd web_ui_react && npm install && npm run build"
        REACT_UI_STATUS="npm_yok"
        return
    fi

    (
        cd "$REACT_DIR"
        info "npm install çalıştırılıyor..."
        npm install
        info "npm run build çalıştırılıyor..."
        npm run build
    )
    ok "React Web UI bağımlılıkları kuruldu ve build tamamlandı."
    REACT_UI_STATUS="hazır"
}

# ── 8. PyAudio WSL2 uyarısı ──────────────────────────────────────────────────
check_pyaudio_wsl2() {
    if [[ "$WSL2" == true ]]; then
        warn "WSL2 üzerinde ses donanımına erişim kısıtlıdır."
        info "Sesli özellik kullanmayacaksanız .env dosyanıza şunu ekleyin:"
        echo "       ENABLE_MULTIMODAL=false"
        info "Ses desteği istiyorsanız: https://learn.microsoft.com/tr-tr/windows/wsl/tutorials/gui-apps"
    fi
}

# ── 9. Dizinleri oluştur ──────────────────────────────────────────────────────
create_directories() {
    step "Proje Dizinleri"
    for dir in "${REQUIRED_DIRS[@]}"; do
        mkdir -p "$SCRIPT_DIR/$dir"
    done
    ok "Dizinler hazır: ${REQUIRED_DIRS[*]}"
}

# ── 10. .env dosyası ──────────────────────────────────────────────────────────
ensure_database_url_defaults() {
    local env_file="$1"
    local current_db_url=""

    if [[ ! -f "$env_file" ]]; then
        return
    fi

    current_db_url=$(grep -E '^DATABASE_URL=' "$env_file" | head -n1 | cut -d= -f2- || true)

    if [[ -z "$current_db_url" ]]; then
        echo "DATABASE_URL=${DEFAULT_DATABASE_URL}" >> "$env_file"
        ok ".env: DATABASE_URL varsayılan PostgreSQL DSN ile eklendi."
        return
    fi

    if [[ "$current_db_url" == sqlite* ]] && [[ "${ALLOW_SQLITE_DATABASE_URL:-0}" != "1" ]]; then
        warn ".env içinde SQLite DATABASE_URL tespit edildi: $current_db_url"
        sed -i "s|^DATABASE_URL=.*|DATABASE_URL=${DEFAULT_DATABASE_URL}|" "$env_file"
        ok ".env: DATABASE_URL PostgreSQL varsayılanına güncellendi (${DEFAULT_DATABASE_URL})."
    fi
}

setup_env_file() {
    step ".env Yapılandırması"
    ENV_FILE="$SCRIPT_DIR/.env"
    EXAMPLE_FILE="$SCRIPT_DIR/.env.example"

    if [[ -f "$ENV_FILE" ]]; then
        ok ".env dosyası zaten mevcut — PostgreSQL varsayılanları kontrol ediliyor."
        ensure_database_url_defaults "$ENV_FILE"
        return
    fi

    if [[ ! -f "$EXAMPLE_FILE" ]]; then
        warn ".env.example bulunamadı — .env oluşturulamadı. Manuel olarak oluşturun."
        return
    fi

    cp "$EXAMPLE_FILE" "$ENV_FILE"
    ok ".env dosyası .env.example'dan oluşturuldu."
    ensure_database_url_defaults "$ENV_FILE"

    # Lokal kurulumda Docker hostname yerine localhost kullan
    if grep -q '^REDIS_URL=redis://redis:6379/0' "$ENV_FILE"; then
        sed -i 's|^REDIS_URL=redis://redis:6379/0|REDIS_URL=redis://localhost:6379/0|' "$ENV_FILE"
        ok ".env: REDIS_URL lokal ortam için localhost olarak güncellendi."
    fi

    # API_KEY boşsa güçlü rastgele değer üret
    if ! grep -q '^API_KEY=' "$ENV_FILE" || grep -q '^API_KEY=$' "$ENV_FILE"; then
        GENERATED_API_KEY=""
        if command -v python3 &>/dev/null; then
            GENERATED_API_KEY=$(python3 - <<'PY'
import secrets
print(secrets.token_urlsafe(32))
PY
)
        elif command -v openssl &>/dev/null; then
            GENERATED_API_KEY=$(openssl rand -base64 32 | tr -d '\n')
        fi

        if [[ -n "$GENERATED_API_KEY" ]]; then
            if grep -q '^API_KEY=' "$ENV_FILE"; then
                sed -i "s|^API_KEY=.*|API_KEY=${GENERATED_API_KEY}|" "$ENV_FILE"
            else
                echo "API_KEY=${GENERATED_API_KEY}" >> "$ENV_FILE"
            fi
            ok ".env: API_KEY otomatik ve güvenli bir değerle oluşturuldu."
        else
            warn "API_KEY otomatik üretilemedi. Lütfen .env içinde güçlü bir değer tanımlayın."
        fi
    fi

    # JWT_SECRET_KEY boşsa güçlü rastgele değer üret
    if grep -q '^JWT_SECRET_KEY=$' "$ENV_FILE"; then
        GENERATED_JWT_KEY=""
        if command -v python3 &>/dev/null; then
            GENERATED_JWT_KEY=$(python3 - <<'PY'
import secrets
print(secrets.token_urlsafe(64))
PY
)
        elif command -v openssl &>/dev/null; then
            GENERATED_JWT_KEY=$(openssl rand -base64 64 | tr -d '\n')
        fi

        if [[ -n "$GENERATED_JWT_KEY" ]]; then
            sed -i "s|^JWT_SECRET_KEY=.*|JWT_SECRET_KEY=${GENERATED_JWT_KEY}|" "$ENV_FILE"
            ok ".env: JWT_SECRET_KEY otomatik ve güvenli bir değerle oluşturuldu."
        else
            warn "JWT_SECRET_KEY otomatik üretilemedi. Lütfen .env içinde güçlü bir değer tanımlayın."
        fi
    fi

    # MEMORY_ENCRYPTION_KEY boşsa Fernet anahtarı üret
    if grep -q '^MEMORY_ENCRYPTION_KEY=$' "$ENV_FILE"; then
        GENERATED_FERNET_KEY=""
        if command -v python3 &>/dev/null; then
            GENERATED_FERNET_KEY=$(python3 - <<'PY'
try:
    from cryptography.fernet import Fernet
    print(Fernet.generate_key().decode())
except Exception:
    pass
PY
)
        fi

        if [[ -n "$GENERATED_FERNET_KEY" ]]; then
            sed -i "s|^MEMORY_ENCRYPTION_KEY=.*|MEMORY_ENCRYPTION_KEY=${GENERATED_FERNET_KEY}|" "$ENV_FILE"
            ok ".env: MEMORY_ENCRYPTION_KEY (Fernet) otomatik üretildi."
        else
            warn "MEMORY_ENCRYPTION_KEY otomatik üretilemedi. Lütfen .env içinde geçerli bir Fernet anahtarı tanımlayın."
        fi
    fi

    # GPU tespitine göre USE_GPU/GPU_MIXED_PRECISION değerlerini uyumlu hale getir
    if command -v sed &>/dev/null; then
        if [[ "$GPU_AVAILABLE" == true ]]; then
            sed -i 's/^USE_GPU=false/USE_GPU=true/' "$ENV_FILE"
            sed -i 's/^GPU_MIXED_PRECISION=false/GPU_MIXED_PRECISION=true/' "$ENV_FILE"

            # Docker için GPU modunu ön tanımlı yap
            if grep -q '^COMPOSE_PROFILES=' "$ENV_FILE"; then
                sed -i 's/^COMPOSE_PROFILES=.*/COMPOSE_PROFILES=gpu/' "$ENV_FILE"
            else
                echo "COMPOSE_PROFILES=gpu" >> "$ENV_FILE"
            fi

            ok ".env: USE_GPU=true, GPU_MIXED_PRECISION=true (GPU tespit edildi)"
            ok ".env: COMPOSE_PROFILES=gpu ayarlandı (Docker GPU modu artık varsayılan)."
        else
            sed -i 's/^USE_GPU=true/USE_GPU=false/' "$ENV_FILE"
            ok ".env: USE_GPU=false (CPU modu / --cpu bayrağı)"
        fi
    fi

    # Docker + GPU tespit edildiyse NVIDIA runtime'ı varsayılan yap
    if [[ "$GPU_AVAILABLE" == true ]] && command -v docker &>/dev/null && command -v sed &>/dev/null; then
        if grep -q '^DOCKER_RUNTIME=' "$ENV_FILE"; then
            sed -i 's/^DOCKER_RUNTIME=.*/DOCKER_RUNTIME=nvidia/' "$ENV_FILE"
        else
            echo 'DOCKER_RUNTIME=nvidia' >> "$ENV_FILE"
        fi

        if grep -q '^DOCKER_ALLOWED_RUNTIMES=' "$ENV_FILE"; then
            if ! grep -q '^DOCKER_ALLOWED_RUNTIMES=.*nvidia' "$ENV_FILE"; then
                sed -i 's/^DOCKER_ALLOWED_RUNTIMES=.*/DOCKER_ALLOWED_RUNTIMES=,runc,runsc,kata-runtime,nvidia/' "$ENV_FILE"
            fi
        else
            echo 'DOCKER_ALLOWED_RUNTIMES=,runc,runsc,kata-runtime,nvidia' >> "$ENV_FILE"
        fi

        ok ".env: Docker GPU varsayılanları ayarlandı (DOCKER_RUNTIME=nvidia)."
    fi

    # WSL2 üzerinde ses tabanlı özellikler gerekmiyorsa multimodal'i varsayılan kapat
    if [[ "$WSL2" == true ]] && grep -q '^ENABLE_MULTIMODAL=true' "$ENV_FILE"; then
        sed -i 's/^ENABLE_MULTIMODAL=true/ENABLE_MULTIMODAL=false/' "$ENV_FILE"
        ok ".env: WSL2 için ENABLE_MULTIMODAL=false olarak ayarlandı."
    fi

    warn ".env dosyasını açın ve API anahtarlarınızı (OPENAI_API_KEY, GEMINI_API_KEY vb.) doldurun."
}

# ── 11. Alembic migrasyonları ────────────────────────────────────────────────
run_migrations() {
    step "Veritabanı Migrasyonları"
    ALEMBIC_INI="$SCRIPT_DIR/alembic.ini"
    ENV_FILE="$SCRIPT_DIR/.env"

    if [[ ! -f "$ALEMBIC_INI" ]]; then
        warn "alembic.ini bulunamadı — migrasyon atlandı."
        return
    fi

    DB_URL=""
    if [[ -f "$ENV_FILE" ]]; then
        DB_URL=$(grep -E '^DATABASE_URL=' "$ENV_FILE" 2>/dev/null | head -n1 | cut -d= -f2- || true)
    fi

    cd "$SCRIPT_DIR"

    if [[ -n "$DB_URL" ]]; then
        info "DATABASE_URL: $DB_URL"
        if python -m alembic -x "database_url=$DB_URL" upgrade head 2>&1; then
            ok "Alembic migrasyonları DATABASE_URL ile tamamlandı."
        else
            warn "Migrasyon başarısız. Log'ları kontrol edin."
        fi
    else
        info "DATABASE_URL bulunamadı — alembic.ini içindeki varsayılan URL kullanılacak."
        if python -m alembic upgrade head 2>&1; then
            ok "Alembic migrasyonları tamamlandı."
        else
            warn "Migrasyon başarısız. Log'ları kontrol edin."
        fi
    fi
}

# ── 12. CUDA bağlantı testi ──────────────────────────────────────────────────
verify_torch_cuda() {
    if [[ "$GPU_AVAILABLE" == true ]]; then
        step "PyTorch CUDA Doğrulaması"
        CUDA_OK=$(python -c "
import torch
avail = torch.cuda.is_available()
ver   = torch.version.cuda or 'N/A'
dev   = torch.cuda.get_device_name(0) if avail else 'N/A'
print(f'available={avail} cuda={ver} device={dev}')
" 2>/dev/null || echo "available=false cuda=N/A device=N/A")

        if echo "$CUDA_OK" | grep -q "available=True"; then
            TORCH_CUDA_VER=$(echo "$CUDA_OK" | grep -oP 'cuda=\K[^ ]+')
            TORCH_GPU_NAME=$(echo "$CUDA_OK" | grep -oP 'device=\K.+')
            ok "PyTorch CUDA aktif: $TORCH_GPU_NAME (CUDA $TORCH_CUDA_VER)"
        else
            warn "PyTorch CUDA bulunamadı. torch CPU sürümü kurulmuş olabilir."
            info "GPU wheel için: uv pip install torch>=2.4.1 --extra-index-url https://download.pytorch.org/whl/cu130"
        fi
    fi
}

# ── 13. Özet ─────────────────────────────────────────────────────────────────
print_summary() {
    echo ""
    echo -e "${BOLD}${GREEN}"
    echo "╔══════════════════════════════════════════════════════════════╗"
    echo "║              Sidar AI Kurulumu Tamamlandı!                  ║"
    echo "╚══════════════════════════════════════════════════════════════╝"
    echo -e "${NC}"

    echo -e "${BOLD}Sonraki Adımlar:${NC}"
    echo ""
    echo -e "  1️⃣  .env dosyasını düzenle:"
    echo "       nano .env"
    echo ""
    if [[ "$USE_CONDA" == true ]]; then
        echo -e "  2️⃣  Conda ortamını aktif et (yeni terminalde):"
        echo "       conda activate $CONDA_ENV_NAME"
        echo ""
        echo -e "  2️⃣a Conda'yı base ortamında güncelle (önerilir):"
        echo "       conda deactivate  # gerekirse sidar ortamından çık"
        echo "       conda update -n base -c defaults conda"
    else
        echo -e "  2️⃣  Sanal ortamı aktif et (yeni terminalde):"
        echo "       source .venv/bin/activate"
    fi
    echo ""
    echo -e "  3️⃣  CLI ile başlat:"
    echo "       python main.py"
    echo ""
    echo -e "  4️⃣  Web arayüzü ile başlat (http://localhost:7860):"
    echo "       python main.py --quick web"
    if [[ "$REACT_UI_STATUS" == "hazır" ]]; then
        echo "       React UI build: tamamlandı (web_ui_react/dist)"
    else
        echo "       React UI build: atlandı (${REACT_UI_STATUS})"
        echo "       Manuel build için: cd web_ui_react && npm install && npm run build"
    fi
    echo ""
    echo -e "  5️⃣  Testleri çalıştır (--dev ile kurulduysa):"
    echo "       ./run_tests.sh"
    echo ""

    if [[ "$GPU_AVAILABLE" == true ]]; then
        echo -e "  ${GREEN}🚀 GPU hızlandırma aktif — .env: USE_GPU=true${NC}"
        echo ""
    fi

    echo -e "${BOLD}Faydalı Komutlar:${NC}"
    echo "  python github_upload.py   — projeyi GitHub'a yükle"
    echo "  python -m alembic upgrade head  — DB migrasyonu"
    echo "  ollama serve              — Ollama servisini başlat"
    echo "  docker compose up sidar-gpu     — Docker GPU modu"
    echo "  Not: Docker GPU için nvidia-container-toolkit kurulu olmalıdır."
    echo "  Güvenlik notu: Üretimde ACCESS_LEVEL ayarını dikkatle yapılandırın."
    echo ""
}

# ── Ana Akış ─────────────────────────────────────────────────────────────────
main() {
    sync_repo
    cd "$SCRIPT_DIR"
    banner
    install_system_dependencies
    check_prerequisites
    detect_gpu
    setup_nvidia_docker
    if [[ "$USE_CONDA" == true ]]; then
        # Conda akışı: environment.yml içindeki uv ile devam et
        setup_python_env
        setup_uv
    else
        # uv-venv akışı: önce uv kur/güncelle, sonra venv oluştur
        setup_uv
        setup_python_env
    fi
    install_python_deps
    install_playwright_browsers
    check_pyaudio_wsl2
    create_directories
    setup_react_frontend
    setup_env_file
    run_migrations
    verify_torch_cuda
    print_summary
}

main "$@"
