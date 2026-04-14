#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════════
# Sidar AI — Kurulum Betiği (install_sidar.sh)
# Sürüm : 5.2.0
# Hedef : WSL2 / Ubuntu / Conda + NVIDIA RTX 30xx/40xx (CUDA 13.x, PyTorch cu124 fallback)
#
# Kullanım:
#   chmod +x install_sidar.sh
#   ./install_sidar.sh           # standart kurulum
#   ./install_sidar.sh --dev     # geliştirici bağımlılıklarıyla
#   ./install_sidar.sh --cpu     # GPU algılansa bile CPU zorla
#   ./install_sidar.sh --kubernetes  # Helm ile Kubernetes kurulumuna geç
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
INSTALL_DEV=false
FORCE_CPU=false
SKIP_MODELS=false
DOWNLOAD_MODELS=false
FORCE_REACT_BUILD=false
INSTALL_KUBERNETES=false
HELM_RELEASE_NAME="sidar"
HELM_NAMESPACE="sidar"
HELM_VALUES_FILE=""
RUN_SMOKE_TESTS_MODE="ask"
DOCKER_ONLY=false
REACT_UI_STATUS="atlandı"
MIGRATION_STATUS="atlandı"
SMOKE_TEST_STATUS="atlandı"
for arg in "$@"; do
    case "$arg" in
        --dev)  INSTALL_DEV=true ;;
        --cpu)  FORCE_CPU=true ;;
        --kubernetes|--helm) INSTALL_KUBERNETES=true ;;
        --skip-models) SKIP_MODELS=true ;;
        --download-models) DOWNLOAD_MODELS=true ;;
        --build-ui) FORCE_REACT_BUILD=true ;;
        --helm-release=*) HELM_RELEASE_NAME="${arg#*=}" ;;
        --namespace=*) HELM_NAMESPACE="${arg#*=}" ;;
        --values=*) HELM_VALUES_FILE="${arg#*=}" ;;
        --smoke-test) RUN_SMOKE_TESTS_MODE="always" ;;
        --skip-smoke-test) RUN_SMOKE_TESTS_MODE="never" ;;
        --docker-only) DOCKER_ONLY=true ;;
        --help|-h)
            echo "Kullanım: $0 [--dev] [--cpu] [--docker-only] [--skip-models] [--download-models] [--build-ui] [--kubernetes] [--smoke-test|--skip-smoke-test]"
            echo "  --dev  Geliştirici bağımlılıklarını kur"
            echo "  --cpu  GPU algılansa bile CPU modunda kur"
            echo "  --docker-only  PostgreSQL/Redis'i hosta kurma, sadece Docker servislerini kullan"
            echo "  --kubernetes / --helm  Yerel kurulum yerine Helm chart ile Kubernetes kurulumu yap"
            echo "  --helm-release=<ad>  Helm release adı (varsayılan: sidar)"
            echo "  --namespace=<ad>  Kubernetes namespace (varsayılan: sidar)"
            echo "  --values=<dosya>  Helm values dosyası (örn. helm/sidar/values-prod.yaml)"
            echo "  --smoke-test  Kurulum sonunda tests/smoke testlerini zorunlu çalıştır"
            echo "  --skip-smoke-test  Kurulum sonunda smoke test çalıştırma"
            echo "  --skip-models  Ollama model indirmelerini atla"
            echo "  --download-models  Ollama modellerini varsayılan olarak indir"
            echo "  --build-ui  React Web UI yeniden build et (cache olsa bile)"
            exit 0
            ;;
        *)      warn "Bilinmeyen argüman: $arg (--dev | --cpu | --docker-only | --kubernetes | --helm | --helm-release=... | --namespace=... | --values=... | --smoke-test | --skip-smoke-test | --skip-models | --download-models | --build-ui kabul edilir)"; exit 1 ;;
    esac
done

if [[ "$SKIP_MODELS" == true && "$DOWNLOAD_MODELS" == true ]]; then
    fail "--skip-models ve --download-models birlikte kullanılamaz."
fi

if [[ "$INSTALL_KUBERNETES" == true && "$FORCE_CPU" == true ]]; then
    warn "--kubernetes/--helm modu aktifken --cpu parametresi kullanılmaz; göz ardı edilecek."
fi

# ── Sabitler ──────────────────────────────────────────────────────────────────
CONDA_ENV_NAME="sidar"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_VERSION="3.11"
if [[ -f "$SCRIPT_DIR/.python-version" ]]; then
    PYTHON_VERSION_FROM_FILE=$(tr -d '[:space:]' < "$SCRIPT_DIR/.python-version" | cut -d. -f1,2)
    if [[ -n "$PYTHON_VERSION_FROM_FILE" ]]; then
        PYTHON_VERSION="$PYTHON_VERSION_FROM_FILE"
    fi
elif [[ -f "$SCRIPT_DIR/pyproject.toml" ]]; then
    PYPROJECT_PYTHON_VERSION=$(sed -nE 's/^[[:space:]]*requires-python[[:space:]]*=[[:space:]]*"[>=~^]*([0-9]+\.[0-9]+).*/\1/p' "$SCRIPT_DIR/pyproject.toml" | head -n1)
    if [[ -n "$PYPROJECT_PYTHON_VERSION" ]]; then
        PYTHON_VERSION="$PYPROJECT_PYTHON_VERSION"
    fi
fi
DEFAULT_DATABASE_URL="postgresql+asyncpg://sidar:sidar@localhost:5432/sidar"
REPO_URL="https://github.com/niluferbagevi-gif/Sidar"
TARGET_DIR="$HOME/Sidar"
REQUIRED_DIRS=(data logs temp sessions data/rag data/lora_adapters data/continuous_learning)

banner() {
    echo -e "${BOLD}${BLUE}"
    echo "╔══════════════════════════════════════════════════════════════╗"
    echo "║          Sidar AI — Kurulum Başlıyor (v5.2.0)               ║"
    echo "╚══════════════════════════════════════════════════════════════╝"
    echo -e "${NC}"
}

read_env_value_from_file() {
    local key="$1"
    local file_path="$2"
    [[ -f "$file_path" ]] || return 0

    awk -F= -v key="$key" '
        /^[[:space:]]*#/ { next }
        $0 ~ "^[[:space:]]*" key "[[:space:]]*=" {
            line = $0
            sub(/^[[:space:]]*[^=]+=[[:space:]]*/, "", line)
            sub(/[[:space:]]+#.*/, "", line)
            gsub(/\r/, "", line)
            gsub(/^[[:space:]]+|[[:space:]]+$/, "", line)
            gsub(/^"|"$/, "", line)
            gsub(/^'\''|'\''$/, "", line)
            print line
            exit
        }
    ' "$file_path"
}

normalize_ollama_base_url() {
    local raw="${1:-}"
    local normalized="$raw"

    normalized="${normalized%/}"
    normalized="${normalized%/api}"
    if [[ -z "$normalized" ]]; then
        echo "http://localhost:11434"
        return
    fi
    if [[ "$normalized" != http://* && "$normalized" != https://* ]]; then
        normalized="http://$normalized"
    fi
    echo "$normalized"
}

resolve_ollama_base_url() {
    local env_file="${1:-$SCRIPT_DIR/.env}"
    local detected="${OLLAMA_BASE_URL:-}"

    if [[ -z "$detected" ]]; then
        detected="${OLLAMA_HOST:-}"
    fi
    if [[ -z "$detected" && -f "$env_file" ]]; then
        detected=$(read_env_value_from_file "OLLAMA_BASE_URL" "$env_file")
    fi
    if [[ -z "$detected" && -f "$env_file" ]]; then
        detected=$(read_env_value_from_file "OLLAMA_HOST" "$env_file")
    fi

    normalize_ollama_base_url "$detected"
}

resolve_ollama_version_url() {
    local env_file="${1:-$SCRIPT_DIR/.env}"
    local base_url
    base_url=$(resolve_ollama_base_url "$env_file")
    echo "${base_url}/api/version"
}

is_local_ollama_url() {
    local url="$1"
    [[ "$url" == http://localhost:* || "$url" == https://localhost:* || "$url" == http://127.0.0.1:* || "$url" == https://127.0.0.1:* ]]
}

deploy_with_helm() {
    step "Kubernetes/Helm Dağıtımı"
    local chart_dir="$SCRIPT_DIR/helm/sidar"
    local helm_cmd=(helm upgrade --install "$HELM_RELEASE_NAME" "$chart_dir" --namespace "$HELM_NAMESPACE" --create-namespace)

    if ! command -v helm &>/dev/null; then
        fail "helm bulunamadı. Kurulum için: https://helm.sh/docs/intro/install/"
    fi

    if [[ ! -f "$chart_dir/Chart.yaml" ]]; then
        fail "Helm chart bulunamadı: $chart_dir/Chart.yaml"
    fi

    if [[ -n "$HELM_VALUES_FILE" ]]; then
        if [[ ! -f "$SCRIPT_DIR/$HELM_VALUES_FILE" && ! -f "$HELM_VALUES_FILE" ]]; then
            fail "--values ile verilen dosya bulunamadı: $HELM_VALUES_FILE"
        fi
        if [[ -f "$SCRIPT_DIR/$HELM_VALUES_FILE" ]]; then
            HELM_VALUES_FILE="$SCRIPT_DIR/$HELM_VALUES_FILE"
        fi
        helm_cmd+=(--values "$HELM_VALUES_FILE")
    fi

    info "Helm chart doğrulaması çalıştırılıyor..."
    helm lint "$chart_dir"

    info "Helm release kuruluyor/güncelleniyor: release=$HELM_RELEASE_NAME namespace=$HELM_NAMESPACE"
    "${helm_cmd[@]}"
    ok "Helm dağıtımı tamamlandı."

    if command -v kubectl &>/dev/null; then
        info "Servisleri doğrulamak için:"
        echo "       kubectl get pods -n $HELM_NAMESPACE"
        echo "       kubectl get svc -n $HELM_NAMESPACE"
    else
        warn "kubectl bulunamadı. Cluster doğrulaması için kubectl kurmanız önerilir."
    fi
}

# ── 0. GitHub deposunu hazırla / güncelle ────────────────────────────────────
sync_repo() {
    step "Sidar projesi GitHub'dan çekiliyor"

    # Bu adım git clone/pull çalıştırdığı için, akış sırası değişse bile
    # git erişimi burada da kesin olarak doğrulanır.
    if ! command -v git &>/dev/null; then
        fail "git komutu bulunamadı. Önce sistem bağımlılıklarını kurun (install_system_dependencies)."
    fi

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
            git fetch origin
            git pull --ff-only || {
                warn "Fast-forward pull başarısız (lokal değişiklikler mevcut). Sadece fetch yapıldı."
                info "Güncelleme için: git stash && git pull --ff-only && git stash pop"
            }
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
            curl wget git build-essential software-properties-common zstd ca-certificates gnupg

        info "Node.js 20.x (NodeSource) kuruluyor..."
        if curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -; then
            sudo DEBIAN_FRONTEND=noninteractive apt-get install -y nodejs
            ok "Node.js NodeSource üzerinden kuruldu: $(node --version 2>/dev/null || echo 'sürüm alınamadı')"
        else
            warn "NodeSource kurulumu başarısız oldu, apt deposundan nodejs/npm kurulumu deneniyor."
            sudo DEBIAN_FRONTEND=noninteractive apt-get install -y nodejs npm
        fi

        info "Kamera (v4l2) ve Ses (PortAudio/ALSA/FFmpeg) kütüphaneleri kuruluyor..."
        sudo DEBIAN_FRONTEND=noninteractive apt-get install -y \
            portaudio19-dev python3-pyaudio alsa-utils v4l-utils ffmpeg
        info "PostgreSQL istemci/geliştirme bağımlılıkları kuruluyor..."
        sudo DEBIAN_FRONTEND=noninteractive apt-get install -y \
            libpq-dev postgresql-client

        if [[ "$DOCKER_ONLY" == true ]]; then
            info "--docker-only aktif: postgresql/redis-server host paketleri atlandı."
        else
            info "Host PostgreSQL ve Redis sunucuları kuruluyor..."
            sudo DEBIAN_FRONTEND=noninteractive apt-get install -y postgresql redis-server

            info "Yerel servisler için PostgreSQL ve Redis servisleri etkinleştirilmeye çalışılıyor..."
            sudo systemctl enable postgresql redis-server >/dev/null 2>&1 || true
            sudo systemctl start postgresql redis-server >/dev/null 2>&1 || \
                warn "PostgreSQL/Redis servisleri başlatılamadı (özellikle WSL2'de normal olabilir). Gerekirse manuel başlatın."
        fi

        ok "Sistem paketleri ve donanım kütüphaneleri başarıyla kuruldu."
    elif command -v dnf &>/dev/null; then
        warn "RedHat/Fedora tabanlı sistem tespit edildi. Paketler dnf ile kuruluyor..."
        sudo dnf upgrade -y
        sudo dnf install -y curl wget git zstd nodejs npm portaudio-devel alsa-utils v4l-utils ffmpeg postgresql postgresql-devel
        if [[ "$DOCKER_ONLY" == true ]]; then
            info "--docker-only aktif: postgresql-server ve redis host paketleri atlandı."
        else
            sudo dnf install -y postgresql-server redis
        fi
    elif command -v brew &>/dev/null; then
        warn "macOS (Homebrew) ortamı tespit edildi. Paketler brew ile kuruluyor..."
        brew update
        brew install \
            curl wget git zstd node@20 ffmpeg portaudio \
            postgresql@16 || warn "Bazı Homebrew paketleri kurulamadı; eksikleri manuel tamamlayın."
        if [[ "$DOCKER_ONLY" == true ]]; then
            info "--docker-only aktif: redis host paketi kurulumu atlandı."
        else
            brew install redis || warn "redis kurulamadı; eksikleri manuel tamamlayın."
        fi

        if brew list node@20 &>/dev/null; then
            info "Node.js 20 için brew link işlemi deneniyor..."
            brew link --overwrite --force node@20 >/dev/null 2>&1 || true
            ok "Node.js sürümü: $(node --version 2>/dev/null || echo 'sürüm alınamadı')"
        fi

        if [[ "$DOCKER_ONLY" == true ]]; then
            info "--docker-only aktif: brew services ile PostgreSQL/Redis başlatma atlandı."
        else
            info "PostgreSQL ve Redis servisleri brew services ile başlatılmaya çalışılıyor..."
            brew services start postgresql@16 >/dev/null 2>&1 || \
                warn "postgresql@16 servisi başlatılamadı. Manuel başlatın: brew services start postgresql@16"
            brew services start redis >/dev/null 2>&1 || \
                warn "redis servisi başlatılamadı. Manuel başlatın: brew services start redis"
        fi

        ok "Homebrew tabanlı bağımlılık kurulumu tamamlandı."
    else
        warn "apt-get veya sudo bulunamadı. Lütfen paketleri manuel kurun:"
        info "Gerekenler: zstd portaudio19-dev alsa-utils v4l-utils ffmpeg vb."
    fi
}

# ── 1. Ön koşul kontrolleri ───────────────────────────────────────────────────
check_prerequisites() {
    step "Ön Koşullar Kontrol Ediliyor"

    # Conda kontrolü ve otomatik Miniconda kurulumu
    MINICONDA_PREFIX="$HOME/miniconda3"

    # Önce conda.sh üzerinden PATH'e ekle (terminal yeniden başlatılmamış olabilir)
    if [[ -f "$MINICONDA_PREFIX/etc/profile.d/conda.sh" ]]; then
        # shellcheck disable=SC1091
        source "$MINICONDA_PREFIX/etc/profile.d/conda.sh"
    fi

    if command -v conda &>/dev/null; then
        USE_CONDA=true
        ok "Conda $(conda --version | cut -d' ' -f2) zaten yüklü."
    elif [[ -x "$MINICONDA_PREFIX/bin/conda" ]]; then
        # shellcheck disable=SC1091
        source "$MINICONDA_PREFIX/etc/profile.d/conda.sh"
        conda init bash >/dev/null 2>&1 || true
        USE_CONDA=true
        ok "Miniconda zaten kurulu (PATH güncellendi): $(conda --version | cut -d' ' -f2)"
    else
        warn "Conda bulunamadı. Miniconda otomatik kurulumu denenecek..."

        OS="$(uname -s)"
        ARCH="$(uname -m)"
        MINICONDA_URL=""
        MINICONDA_INSTALLER="/tmp/miniconda.sh"

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
                info "Miniconda kuruluyor: $MINICONDA_PREFIX"
                bash "$MINICONDA_INSTALLER" -b -p "$MINICONDA_PREFIX"
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
    if [[ "$DOCKER_ONLY" == false ]] && ! command -v redis-server &>/dev/null && [[ "$WSL2" == false ]]; then
        warn "Lokal Redis sunucusu bulunamadı. Projenin düzgün çalışması için Redis gereklidir."
        info "Lokal yerine Docker kullanacaksanız bu uyarıyı dikkate almayın."
    fi

    if command -v psql &>/dev/null; then
        ok "PostgreSQL istemcisi hazır: $(psql --version | awk '{print $3}')"
    elif [[ "$DOCKER_ONLY" == true ]]; then
        info "--docker-only: psql istemcisi opsiyonel. DB bağlantısı Docker servisleriyle sağlanacak."
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
    OLLAMA_VERSION_URL=$(resolve_ollama_version_url "$SCRIPT_DIR/.env")
    if curl -sf "$OLLAMA_VERSION_URL" &>/dev/null; then
        ok "Ollama API servisi aktif (${OLLAMA_VERSION_URL})."
    else
        warn "Ollama kurulu ancak API servisi şu an yanıt vermiyor (${OLLAMA_VERSION_URL})."
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

        if conda env list | grep -q "^${CONDA_ENV_NAME}\s"; then
            info "Mevcut conda ortamı bulundu: $CONDA_ENV_NAME — güncelleniyor..."
            conda env update -n "$CONDA_ENV_NAME" -f "$SCRIPT_DIR/environment.yml" --prune
            ok "Conda ortamı güncellendi."
        else
            info "Yeni conda ortamı oluşturuluyor: $CONDA_ENV_NAME (Python $PYTHON_VERSION)..."
            conda env create -f "$SCRIPT_DIR/environment.yml"
            ok "Conda ortamı oluşturuldu."
        fi

        CONDA_RUN=(conda run -n "$CONDA_ENV_NAME")
        if "${CONDA_RUN[@]}" python -c "import sys; print(sys.version)" >/dev/null 2>&1; then
            ok "Conda ortamı hazır: $CONDA_ENV_NAME (komutlar conda run ile çalıştırılacak)"
        else
            fail "Conda ortamı doğrulanamadı: $CONDA_ENV_NAME"
        fi
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
    if [[ "$USE_CONDA" == true ]]; then
        UV_CMD=("${CONDA_RUN[@]}" uv)
    else
        UV_CMD=(uv)
    fi

    # uv.lock yönetimi: yoksa oluştur, varsa güncelle
    if [[ ! -f "$SCRIPT_DIR/uv.lock" ]]; then
        info "uv.lock bulunamadı — uv lock ile oluşturuluyor..."
        "${UV_CMD[@]}" lock
        ok "uv.lock oluşturuldu."
    else
        info "uv.lock bulundu — uv lock ile bağımlılıklar kontrol ediliyor..."
        "${UV_CMD[@]}" lock
        ok "uv.lock kontrol edildi."
    fi

    SYNC_ARGS=(--frozen --extra dev)
    if [[ "$GPU_AVAILABLE" == true && -n "$CUDA_VERSION" ]]; then
        for _extra in gemini anthropic openai litellm postgres telemetry rag gpu sandbox gui browser; do
            SYNC_ARGS+=(--extra "$_extra")
        done
    else
        for _extra in gemini anthropic openai litellm postgres telemetry rag sandbox gui browser; do
            SYNC_ARGS+=(--extra "$_extra")
        done
    fi
    info "Bağımlılıklar senkronlanıyor (uv sync --frozen)..."
    "${UV_CMD[@]}" sync "${SYNC_ARGS[@]}"
    ok "Python bağımlılıkları senkronlandı."
    return

    if [[ "$GPU_AVAILABLE" == true && -n "$CUDA_VERSION" ]]; then
        # CUDA major version'ı belirle (örn. 13.2 → cu124 fallback)
        CUDA_MAJOR=$(echo "$CUDA_VERSION" | cut -d. -f1)
        CUDA_MINOR=$(echo "$CUDA_VERSION" | cut -d. -f2)

        # PyTorch wheel dizini: cu124, cu121 gibi
        if   [[ "$CUDA_MAJOR" -ge 13 ]]; then TORCH_CU="cu124"
        elif [[ "$CUDA_MAJOR" -eq 12 && "$CUDA_MINOR" -ge 4 ]]; then TORCH_CU="cu124"
        elif [[ "$CUDA_MAJOR" -eq 12 ]]; then TORCH_CU="cu121"
        else TORCH_CU=""
        fi

        info "GPU kurulumu yapılıyor..."
        REQ_ARGS=()
        if [[ -f "$SCRIPT_DIR/requirements-gpu.txt" ]]; then
            REQ_ARGS+=("requirements-gpu.txt")
        elif [[ -f "$SCRIPT_DIR/requirements-all.txt" ]]; then
            REQ_ARGS+=("requirements-all.txt")
        elif [[ -f "$SCRIPT_DIR/requirements.txt" ]]; then
            REQ_ARGS+=("requirements.txt")
        fi
        if [[ "$INSTALL_DEV" == true && -f "$SCRIPT_DIR/requirements-dev.txt" ]]; then
            REQ_ARGS+=("requirements-dev.txt")
        fi

        if [[ "${#REQ_ARGS[@]}" -gt 0 ]]; then
            info "GPU için requirements dosyaları uv pip sync ile senkronlanıyor: ${REQ_ARGS[*]}"
            if [[ -n "$TORCH_CU" ]]; then
                "${UV_CMD[@]}" pip sync \
                    --index-strategy unsafe-best-match \
                    --extra-index-url "https://download.pytorch.org/whl/${TORCH_CU}" \
                    "${REQ_ARGS[@]}"
            else
                warn "CUDA $CUDA_VERSION için PyTorch wheel URL'i belirlenemedi — varsayılan indekslerle senkron yapılacak."
                "${UV_CMD[@]}" pip sync "${REQ_ARGS[@]}"
            fi
            ok "Python bağımlılıkları requirements dosyalarıyla senkronlandı."
            return
        fi

        if [[ "$INSTALL_DEV" == true ]]; then
            INSTALL_SPEC=(-e ".[all,dev]")
        else
            INSTALL_SPEC=(-e ".[all]")
        fi
        if [[ -n "$TORCH_CU" ]]; then
            info "GPU kurulumu: CUDA $CUDA_VERSION → PyTorch wheel: $TORCH_CU"
            "${UV_CMD[@]}" pip install \
                --index-strategy unsafe-best-match \
                --extra-index-url "https://download.pytorch.org/whl/${TORCH_CU}" \
                "${INSTALL_SPEC[@]}"
        else
            warn "CUDA $CUDA_VERSION için PyTorch wheel URL'i belirlenemedi — PyPI'dan kuruluyor."
            "${UV_CMD[@]}" pip install "${INSTALL_SPEC[@]}"
        fi
    else
        info "CPU modu kuruluyor..."
        REQ_ARGS=()
        if [[ -f "$SCRIPT_DIR/requirements-all.txt" ]]; then
            REQ_ARGS+=("requirements-all.txt")
        elif [[ -f "$SCRIPT_DIR/requirements.txt" ]]; then
            REQ_ARGS+=("requirements.txt")
        fi
        if [[ "$INSTALL_DEV" == true && -f "$SCRIPT_DIR/requirements-dev.txt" ]]; then
            REQ_ARGS+=("requirements-dev.txt")
        fi
        if [[ "${#REQ_ARGS[@]}" -gt 0 ]]; then
            info "CPU için requirements dosyaları uv pip sync ile senkronlanıyor: ${REQ_ARGS[*]}"
            "${UV_CMD[@]}" pip sync "${REQ_ARGS[@]}"
            ok "Python bağımlılıkları requirements dosyalarıyla senkronlandı."
            return
        fi

        if [[ "$INSTALL_DEV" == true ]]; then
            INSTALL_SPEC=(-e ".[postgres,browser,dev]")
        else
            INSTALL_SPEC=(-e ".[postgres,browser]")
        fi
        "${UV_CMD[@]}" pip install "${INSTALL_SPEC[@]}"
    fi

    ok "Python bağımlılıkları kuruldu."
}

# ── 6. Playwright tarayıcı motorları ─────────────────────────────────────────
install_playwright_browsers() {
    step "Playwright Tarayıcı Motorları"

    if [[ "$USE_CONDA" == true ]]; then
        PY_CMD=("${CONDA_RUN[@]}" python)
    else
        PY_CMD=(python)
    fi

    if "${PY_CMD[@]}" -c "import playwright" >/dev/null 2>&1; then
        info "Chromium ve Firefox motorları kuruluyor..."
        if "${PY_CMD[@]}" -m playwright install --with-deps chromium firefox; then
            ok "Playwright motorları kuruldu (chromium, firefox)."
        else
            warn "Playwright motor kurulumu başarısız oldu veya atlandı. Manuel komut: python -m playwright install --with-deps chromium firefox"
        fi
    else
        info "playwright paketi bu profilde kurulmadı — tarayıcı motor kurulumu atlandı."
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

    if command -v node &>/dev/null; then
        NODE_MAJOR="$(node -v | sed 's/^v//' | cut -d. -f1)"
        if [[ "$NODE_MAJOR" -lt 20 ]]; then
            warn "Node.js sürümü düşük: $(node -v). React build için Node.js 20+ önerilir."
            warn "Kurulum komutları: curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash - && sudo apt-get install -y nodejs"
        else
            ok "Node.js sürümü uygun: $(node -v)"
        fi
    fi

    if [[ "$FORCE_REACT_BUILD" != true && "$INSTALL_DEV" == false && -d "$REACT_DIR/dist" && -d "$REACT_DIR/node_modules" ]]; then
        ok "React Web UI zaten build edilmiş. Yeniden derleme atlanıyor (--build-ui ile zorlayabilirsiniz)."
        REACT_UI_STATUS="hazır_cache"
        return
    fi

    if ! (
        cd "$REACT_DIR"
        info "npm install çalıştırılıyor..."
        npm install
        info "npm run build çalıştırılıyor..."
        npm run build
    ); then
        warn "React UI build başarısız oldu. Kurulum devam edecek; özet bölümünde durum işaretlenecek."
        REACT_UI_STATUS="build_hata"
        return
    fi
    if [[ ! -d "$REACT_DIR/dist" ]]; then
        warn "React UI build tamamlandı görünüyor ancak dist klasörü bulunamadı: $REACT_DIR/dist"
        REACT_UI_STATUS="build_hata"
        return
    fi
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
        warn "WSL2 varsayılan RAM limiti düşükse lokal LLM/RAG işlemlerinde OOM (Out of Memory) yaşanabilir."
        info "Windows tarafında %UserProfile%\\.wslconfig dosyasına bellek limiti ekleyin (örnek):"
        echo "       [wsl2]"
        echo "       memory=16GB"
        echo "       swap=8GB"

        # Opsiyonel kolaylık: .wslconfig yoksa otomatik oluşturmayı dene
        local win_userprofile=""
        local wslconfig_path=""
        if command -v cmd.exe &>/dev/null; then
            win_userprofile=$(cmd.exe /c "echo %UserProfile%" 2>/dev/null | tr -d '\r' | tail -n1 || true)
            if [[ "$win_userprofile" =~ ^[A-Za-z]:\\ ]]; then
                local drive_letter
                local path_rest
                drive_letter=$(echo "$win_userprofile" | cut -d: -f1 | tr 'A-Z' 'a-z')
                path_rest=$(echo "$win_userprofile" | cut -d: -f2- | sed 's#\\#/#g')
                wslconfig_path="/mnt/${drive_letter}${path_rest}/.wslconfig"
            fi
        fi

        if [[ -n "$wslconfig_path" ]]; then
            if [[ ! -f "$wslconfig_path" ]]; then
                cat > "$wslconfig_path" <<'EOF'
[wsl2]
memory=16GB
swap=8GB
EOF
                ok "WSL2: %UserProfile%/.wslconfig otomatik oluşturuldu ($wslconfig_path)."
            else
                info "WSL2: .wslconfig zaten mevcut ($wslconfig_path)."
            fi
        else
            info "WSL2: %UserProfile% yolu otomatik çözümlenemedi; .wslconfig dosyasını manuel oluşturun."
        fi

        info "Değişiklik sonrası PowerShell'de 'wsl --shutdown' çalıştırıp dağıtımı yeniden başlatın."
    fi
}

# ── 9. Dizinleri oluştur ──────────────────────────────────────────────────────
create_directories() {
    step "Proje Dizinleri"
    for dir in "${REQUIRED_DIRS[@]}"; do
        mkdir -p "$SCRIPT_DIR/$dir"
    done
    if [[ -f "$SCRIPT_DIR/run_tests.sh" ]]; then
        chmod +x "$SCRIPT_DIR/run_tests.sh"
    fi
    ok "Dizinler hazır: ${REQUIRED_DIRS[*]}"
}

# ── 10. .env dosyası ──────────────────────────────────────────────────────────
generate_secure_token() {
    local token_length="${1:-32}"
    local generated=""

    if command -v python3 &>/dev/null; then
        generated=$(python3 - <<PY
import secrets
print(secrets.token_urlsafe(${token_length}))
PY
)
    elif command -v openssl &>/dev/null; then
        generated=$(openssl rand -base64 "$token_length" | tr -d '\n')
    fi

    echo "$generated"
}

harden_database_credentials() {
    local env_file="$1"
    local db_url=""
    local sidar_env="development"
    local safe_db_url=""

    [[ -f "$env_file" ]] || return

    db_url=$(grep -E '^DATABASE_URL=' "$env_file" | head -n1 | cut -d= -f2- || true)
    sidar_env=$(grep -E '^SIDAR_ENV=' "$env_file" | head -n1 | cut -d= -f2- || echo "development")

    [[ -n "$db_url" ]] || return

    # Güvensiz bilinen varsayılan kimlik bilgileri (postgres:postgres vb.)
    if [[ "$db_url" =~ ^postgresql(\+asyncpg)?://([^:@/]+):([^@/]+)@(.+)$ ]]; then
        local db_user="${BASH_REMATCH[2]}"
        local db_password="${BASH_REMATCH[3]}"
        local db_host_and_name="${BASH_REMATCH[4]}"

        case "$db_password" in
            postgres|password|admin|changeme|123456)
                if [[ "$sidar_env" == "production" || "${FORCE_STRONG_DB_PASSWORD:-0}" == "1" ]]; then
                    local generated_password=""
                    generated_password=$(generate_secure_token 24)
                    if [[ -n "$generated_password" ]]; then
                        safe_db_url="postgresql+asyncpg://${db_user}:${generated_password}@${db_host_and_name}"
                        sed -i "s|^DATABASE_URL=.*|DATABASE_URL=${safe_db_url}|" "$env_file"
                        ok ".env: DATABASE_URL için güvenli bir veritabanı şifresi üretildi (SIDAR_ENV=${sidar_env})."

                        # Docker Compose ile çalışırken PostgreSQL container kimlik bilgileri
                        # DATABASE_URL ile senkron kalmalıdır.
                        if grep -q '^POSTGRES_PASSWORD=' "$env_file"; then
                            sed -i "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=${generated_password}|" "$env_file"
                        else
                            echo "POSTGRES_PASSWORD=${generated_password}" >> "$env_file"
                        fi
                        if grep -q '^POSTGRES_USER=' "$env_file"; then
                            sed -i "s|^POSTGRES_USER=.*|POSTGRES_USER=${db_user}|" "$env_file"
                        else
                            echo "POSTGRES_USER=${db_user}" >> "$env_file"
                        fi
                        ok ".env: POSTGRES_USER/POSTGRES_PASSWORD değerleri DATABASE_URL ile senkronize edildi."
                        warn "Docker kullanıyorsanız PostgreSQL servisini yeni şifreyle yeniden başlatın:"
                        info "docker compose down && docker compose up -d postgres redis"
                    else
                        warn ".env: Güçlü veritabanı şifresi otomatik üretilemedi. DATABASE_URL parolanızı manuel güncelleyin."
                    fi
                else
                    warn ".env: DATABASE_URL varsayılan/zayıf parola içeriyor (${db_user}:${db_password})."
                    warn "Üretim için SIDAR_ENV=production ayarlayıp scripti tekrar çalıştırın veya DATABASE_URL parolasını manuel değiştirin."
                fi
                ;;
        esac
    fi
}

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
        return
    fi

    if [[ "$current_db_url" == *lotus* ]]; then
        warn ".env içinde eski 'lotus' referansı içeren DATABASE_URL tespit edildi: $current_db_url"
        sed -i "s|^DATABASE_URL=.*|DATABASE_URL=${DEFAULT_DATABASE_URL}|" "$env_file"
        ok ".env: DATABASE_URL Sidar varsayılanına güncellendi (${DEFAULT_DATABASE_URL})."
    fi
}

setup_env_file() {
    step ".env Yapılandırması"
    ENV_FILE="$SCRIPT_DIR/.env"
    EXAMPLE_FILE="$SCRIPT_DIR/.env.example"

    if [[ -f "$ENV_FILE" ]]; then
        ok ".env dosyası zaten mevcut — PostgreSQL varsayılanları kontrol ediliyor."
        ensure_database_url_defaults "$ENV_FILE"
        harden_database_credentials "$ENV_FILE"
        return
    fi

    if [[ ! -f "$EXAMPLE_FILE" ]]; then
        warn ".env.example bulunamadı — .env oluşturulamadı. Manuel olarak oluşturun."
        return
    fi

    cp "$EXAMPLE_FILE" "$ENV_FILE"
    ok ".env dosyası .env.example'dan oluşturuldu."
    ensure_database_url_defaults "$ENV_FILE"
    harden_database_credentials "$ENV_FILE"

    # Lokal kurulumda Docker hostname yerine localhost kullan
    if grep -q '^REDIS_URL=redis://redis:6379/0' "$ENV_FILE"; then
        sed -i 's|^REDIS_URL=redis://redis:6379/0|REDIS_URL=redis://localhost:6379/0|' "$ENV_FILE"
        ok ".env: REDIS_URL lokal ortam için localhost olarak güncellendi."
    fi

    if grep -q '^OTEL_EXPORTER_ENDPOINT=http://jaeger:' "$ENV_FILE"; then
        sed -i 's|^OTEL_EXPORTER_ENDPOINT=http://jaeger:|OTEL_EXPORTER_ENDPOINT=http://localhost:|' "$ENV_FILE"
        ok ".env: OTEL_EXPORTER_ENDPOINT lokal ortam için localhost olarak güncellendi."
    fi

    # Bilinen sızıntı/default değerleri de güvenli olmayan kabul edilir ve yeniden üretilir.
    is_missing_empty_or_known_insecure() {
        local key_name="$1"
        shift
        local current_value=""
        current_value=$(grep -E "^${key_name}=" "$ENV_FILE" | head -n1 | cut -d= -f2- || true)

        if ! grep -q "^${key_name}=" "$ENV_FILE"; then
            return 0
        fi
        if [[ -z "$current_value" ]]; then
            return 0
        fi
        for insecure_value in "$@"; do
            if [[ "$current_value" == "$insecure_value" ]]; then
                return 0
            fi
        done
        return 1
    }

    # API_KEY boşsa/yoksa veya bilinen güvensiz örnek değerse güçlü rastgele değer üret
    if is_missing_empty_or_known_insecure \
        "API_KEY" \
        "uyaL0M3t5hHt0dj5ous7-oScvna9HH9pV6CneB5hYJw"; then
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

    # JWT_SECRET_KEY boşsa/yoksa veya bilinen güvensiz örnek değerse güçlü rastgele değer üret
    if is_missing_empty_or_known_insecure \
        "JWT_SECRET_KEY" \
        "Lipg1iwRX5USyUaEt06ctbmnUQnYdywHcgW3y8Rif24fYvNiKX8V5xSQ3m1XOhpx6UuF9X6BGSekm8m_a3jQcg"; then
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
            if grep -q '^JWT_SECRET_KEY=' "$ENV_FILE"; then
                sed -i "s|^JWT_SECRET_KEY=.*|JWT_SECRET_KEY=${GENERATED_JWT_KEY}|" "$ENV_FILE"
            else
                echo "JWT_SECRET_KEY=${GENERATED_JWT_KEY}" >> "$ENV_FILE"
            fi
            ok ".env: JWT_SECRET_KEY otomatik ve güvenli bir değerle oluşturuldu."
        else
            warn "JWT_SECRET_KEY otomatik üretilemedi. Lütfen .env içinde güçlü bir değer tanımlayın."
        fi
    fi

    # MEMORY_ENCRYPTION_KEY boşsa/yoksa veya bilinen güvensiz örnek değerse Fernet anahtarı üret
    if is_missing_empty_or_known_insecure \
        "MEMORY_ENCRYPTION_KEY" \
        "vQYaMh2gwGHuEzCfG8638aVcBfQX4xLJ8d8uJzBWfW8="; then
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
            if grep -q '^MEMORY_ENCRYPTION_KEY=' "$ENV_FILE"; then
                sed -i "s|^MEMORY_ENCRYPTION_KEY=.*|MEMORY_ENCRYPTION_KEY=${GENERATED_FERNET_KEY}|" "$ENV_FILE"
            else
                echo "MEMORY_ENCRYPTION_KEY=${GENERATED_FERNET_KEY}" >> "$ENV_FILE"
            fi
            ok ".env: MEMORY_ENCRYPTION_KEY (Fernet) otomatik üretildi."
        else
            warn "MEMORY_ENCRYPTION_KEY otomatik üretilemedi. Lütfen .env içinde geçerli bir Fernet anahtarı tanımlayın."
        fi
    fi

    # Hex tabanlı webhook/federation secret değerleri boşsa/yoksa veya bilinen
    # güvensiz örnek değerlerse otomatik üret
    ensure_hex_secret() {
        local key_name="$1"
        local hex_len="${2:-64}"
        local generated=""
        shift 2

        if is_missing_empty_or_known_insecure "$key_name" "$@"; then
            if command -v python3 &>/dev/null; then
                generated=$(python3 - <<PY
import secrets
print(secrets.token_hex(${hex_len} // 2))
PY
)
            elif command -v openssl &>/dev/null; then
                generated=$(openssl rand -hex "$((hex_len / 2))" | tr -d '\n')
            fi

            if [[ -n "$generated" ]]; then
                if grep -q "^${key_name}=" "$ENV_FILE"; then
                    sed -i "s|^${key_name}=.*|${key_name}=${generated}|" "$ENV_FILE"
                else
                    echo "${key_name}=${generated}" >> "$ENV_FILE"
                fi
                ok ".env: ${key_name} otomatik ve güvenli bir değerle oluşturuldu."
            else
                warn "${key_name} otomatik üretilemedi. Lütfen .env içinde güçlü bir değer tanımlayın."
            fi
        fi
    }

    ensure_hex_secret \
        "AUTONOMY_WEBHOOK_SECRET" 64 \
        "a4313adde181fddef87f03ebff7fbf8f2f9f27d58b7ad8d0fa1cb5fc7e8d43ac"
    ensure_hex_secret \
        "SWARM_FEDERATION_SHARED_SECRET" 64 \
        "aeaac3534fe2f97f2147be6f756ea8f4500f4d0f0f5ef758f6f7798f7d8a3f1b"
    ensure_hex_secret \
        "GITHUB_WEBHOOK_SECRET" 40 \
        "69df1db55791dd991a3197958f5fce4ea0ed47e3"

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
            if grep -q '^COMPOSE_PROFILES=' "$ENV_FILE"; then
                sed -i 's/^COMPOSE_PROFILES=.*/COMPOSE_PROFILES=cpu/' "$ENV_FILE"
            else
                echo "COMPOSE_PROFILES=cpu" >> "$ENV_FILE"
            fi
            ok ".env: USE_GPU=false, COMPOSE_PROFILES=cpu ayarlandı."
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

# ── 11. Ollama modelleri ─────────────────────────────────────────────────────
download_ollama_models() {
    step "Ollama Modelleri Hazırlanıyor"
    local estimated_size_gb="~14.8 GB"
    local temp_ollama_pid=""
    cleanup_temp_ollama() {
        if [[ -n "${temp_ollama_pid:-}" ]] && kill -0 "${temp_ollama_pid:-}" >/dev/null 2>&1; then
            info "Geçici ollama serve süreci sonlandırılıyor (PID: ${temp_ollama_pid:-})..."
            kill "${temp_ollama_pid:-}" >/dev/null 2>&1 || true
        fi
    }
    trap cleanup_temp_ollama RETURN

    if [[ "$SKIP_MODELS" == true ]]; then
        info "--skip-models bayrağı verildi, model indirmeleri atlanıyor."
        return
    fi

    if [[ "$DOWNLOAD_MODELS" != true ]]; then
        if [[ -t 0 ]]; then
            read -r -p "Modeller indirilecek (${estimated_size_gb}). Devam edilsin mi? [E/h] " reply
            case "${reply:-E}" in
                [HhNn]*)
                    info "Model indirmesi kullanıcı tercihiyle atlandı."
                    return
                    ;;
            esac
        else
            info "--download-models verilmediği için model indirmeleri atlanıyor (tahmini ${estimated_size_gb})."
            info "Model indirmek için tekrar çalıştırın: ./install_sidar.sh --download-models"
            return
        fi
    fi

    if ! command -v ollama &>/dev/null; then
        warn "Ollama bulunamadı, model indirme atlanıyor."
        return
    fi

    OLLAMA_VERSION_URL=$(resolve_ollama_version_url "$SCRIPT_DIR/.env")
    OLLAMA_BASE_URL="${OLLAMA_VERSION_URL%/api/version}"
    if ! curl -sf "$OLLAMA_VERSION_URL" &>/dev/null; then
        info "Ollama API erişilemedi (${OLLAMA_VERSION_URL})."
        if is_local_ollama_url "$OLLAMA_BASE_URL"; then
            info "Yerel Ollama servisi başlatma deneniyor..."
            if command -v systemctl &>/dev/null && command -v sudo &>/dev/null; then
                sudo systemctl enable --now ollama >/dev/null 2>&1 || true
            fi
            # systemd yoksa veya servis ayağa kalkmadıysa son çare olarak geçici süreç başlat.
            if ! curl -sf "$OLLAMA_VERSION_URL" &>/dev/null; then
                info "systemd ile Ollama doğrulanamadı, geçici 'ollama serve' süreci başlatılıyor..."
                ollama serve >/dev/null 2>&1 &
                temp_ollama_pid=$!
            fi
            for _ in {1..12}; do
                if curl -sf "$OLLAMA_VERSION_URL" &>/dev/null; then
                    break
                fi
                sleep 5
            done
        else
            warn "Uzak Ollama endpoint'i tespit edildi (${OLLAMA_BASE_URL}). Otomatik servis başlatma atlandı."
        fi
    fi

    if ! curl -sf "$OLLAMA_VERSION_URL" &>/dev/null; then
        warn "Ollama servisi doğrulanamadı (${OLLAMA_VERSION_URL}), model indirme atlanıyor."
        return
    fi

    ENV_FILE="$SCRIPT_DIR/.env"
    if [[ ! -f "$ENV_FILE" ]]; then
        warn ".env bulunamadı, varsayılan modeller indirilemedi."
        return
    fi

    TEXT_MOD=$(read_env_value_from_file "TEXT_MODEL" "$ENV_FILE")
    CODE_MOD=$(read_env_value_from_file "CODING_MODEL" "$ENV_FILE")
    VISION_MOD=$(read_env_value_from_file "VISION_MODEL" "$ENV_FILE")
    MULTIMODAL=$(read_env_value_from_file "ENABLE_MULTIMODAL" "$ENV_FILE")

    if [[ -z "$TEXT_MOD" ]]; then
        TEXT_MOD="llama3.1:8b"
        warn "TEXT_MODEL boş/geçersiz görünüyor, varsayılan kullanılacak: $TEXT_MOD"
    fi
    if [[ -z "$CODE_MOD" ]]; then
        CODE_MOD="qwen2.5-coder:3b"
        warn "CODING_MODEL boş/geçersiz görünüyor, varsayılan kullanılacak: $CODE_MOD"
    fi

    MODELS=("$TEXT_MOD" "$CODE_MOD" "nomic-embed-text")
    if [[ "${MULTIMODAL,,}" == "true" && -n "$VISION_MOD" ]]; then
        MODELS+=("$VISION_MOD")
    fi

    for model in "${MODELS[@]}"; do
        if [[ -n "$model" ]]; then
            info "-> $model indiriliyor (bu işlem zaman alabilir)..."
            ollama pull "$model"
        fi
    done

    ok "Gerekli tüm modeller başarıyla hazırlandı."
}

# ── 12. Alembic migrasyonları ────────────────────────────────────────────────
run_migrations() {
    step "Veritabanı Migrasyonları"
    ALEMBIC_INI="$SCRIPT_DIR/alembic.ini"
    ENV_FILE="$SCRIPT_DIR/.env"

    if [[ ! -f "$ALEMBIC_INI" ]]; then
        warn "alembic.ini bulunamadı — migrasyon atlandı."
        MIGRATION_STATUS="alembic_yok"
        return
    fi

    DB_URL=""
    if [[ -f "$ENV_FILE" ]]; then
        DB_URL=$(grep -E '^DATABASE_URL=' "$ENV_FILE" 2>/dev/null | head -n1 | cut -d= -f2- || true)
    fi

    cd "$SCRIPT_DIR"

    if [[ -z "$DB_URL" ]]; then
        warn "DATABASE_URL bulunamadı — otomatik migrasyon atlandı."
        info "Veritabanını başlattıktan sonra manuel çalıştırın: python -m alembic upgrade head"
        MIGRATION_STATUS="db_url_yok"
        return
    fi

    info "DATABASE_URL: $DB_URL"

    if [[ "$DOCKER_ONLY" == true ]]; then
        DOCKER_COMPOSE_CMD=()
        if command -v docker &>/dev/null && docker compose version &>/dev/null; then
            DOCKER_COMPOSE_CMD=(docker compose)
        elif command -v docker-compose &>/dev/null; then
            DOCKER_COMPOSE_CMD=(docker-compose)
        fi
        if [[ ${#DOCKER_COMPOSE_CMD[@]} -gt 0 ]]; then
            info "--docker-only: PostgreSQL/Redis Docker servisleri başlatılıyor..."
            "${DOCKER_COMPOSE_CMD[@]}" up -d postgres redis || warn "Docker postgres/redis servisleri başlatılamadı."
        else
            warn "--docker-only aktif ancak docker compose bulunamadı. DB servislerini manuel başlatın."
        fi
    fi

    setup_pgvector_extension() {
        if ! command -v psql &>/dev/null; then
            return
        fi
        if [[ -z "$DB_URL" ]]; then
            return
        fi

        local psql_url
        psql_url="${DB_URL/postgresql+asyncpg:\/\//postgresql:\/\/}"

        info "pgvector extension kontrol ediliyor..."
        if psql "$psql_url" -c "CREATE EXTENSION IF NOT EXISTS vector;" >/dev/null 2>&1; then
            ok "pgvector extension hazır."
        else
            warn "pgvector kurulamadı. RAG pgvector backend çalışmayabilir."
        fi
    }

    setup_postgresql_local() {
        if ! command -v psql &>/dev/null; then
            return
        fi
        if ! command -v sudo &>/dev/null; then
            return
        fi
        if ! sudo -u postgres psql -tAc "SELECT 1;" >/dev/null 2>&1; then
            return
        fi

        info "Lokal PostgreSQL kullanıcı/veritabanı kontrolü yapılıyor..."
        sudo -u postgres psql -c "CREATE USER sidar WITH PASSWORD 'sidar';" >/dev/null 2>&1 || true
        sudo -u postgres psql -c "CREATE DATABASE sidar OWNER sidar;" >/dev/null 2>&1 || true
        ok "PostgreSQL: sidar kullanıcısı ve veritabanı hazır."
    }

    if [[ "$DB_URL" == postgresql* ]]; then
        if ! command -v pg_isready &>/dev/null; then
            warn "pg_isready bulunamadı — veritabanı erişilebilirliği doğrulanamadı, migrasyon atlandı."
            info "Veritabanını başlattıktan sonra manuel çalıştırın: python -m alembic -x \"database_url=$DB_URL\" upgrade head"
            MIGRATION_STATUS="pg_isready_yok"
            return
        fi

        DB_CONN_INFO=$(python - <<'PY' "$DB_URL"
from urllib.parse import urlparse, unquote
import sys

url = sys.argv[1]
url = url.replace("postgresql+asyncpg://", "postgresql://", 1)
parsed = urlparse(url)

host = parsed.hostname or "localhost"
port = str(parsed.port or 5432)
user = unquote(parsed.username or "postgres")
db = parsed.path.lstrip("/") or "postgres"

print(f"{host}|{port}|{user}|{db}")
PY
)

        DB_HOST=$(echo "$DB_CONN_INFO" | cut -d'|' -f1)
        DB_PORT=$(echo "$DB_CONN_INFO" | cut -d'|' -f2)
        DB_USER=$(echo "$DB_CONN_INFO" | cut -d'|' -f3)
        DB_NAME=$(echo "$DB_CONN_INFO" | cut -d'|' -f4)

        if [[ "$DB_HOST" == "localhost" || "$DB_HOST" == "127.0.0.1" ]]; then
            setup_postgresql_local
        fi

        if ! pg_isready -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" >/dev/null 2>&1; then
            DOCKER_COMPOSE_CMD=()
            if command -v docker &>/dev/null && docker compose version &>/dev/null; then
                DOCKER_COMPOSE_CMD=(docker compose)
            elif command -v docker-compose &>/dev/null; then
                DOCKER_COMPOSE_CMD=(docker-compose)
            fi

            if [[ ("$DB_HOST" == "localhost" || "$DB_HOST" == "127.0.0.1") && ${#DOCKER_COMPOSE_CMD[@]} -gt 0 ]]; then
                info "PostgreSQL erişilemedi ($DB_HOST:$DB_PORT/$DB_NAME). Docker servisleri otomatik başlatılıyor..."
                if "${DOCKER_COMPOSE_CMD[@]}" up -d postgres redis; then
                    info "Veritabanının hazır olması bekleniyor..."
                    for _ in {1..15}; do
                        if pg_isready -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" >/dev/null 2>&1; then
                            ok "PostgreSQL erişilebilir hale geldi."
                            break
                        fi
                        sleep 2
                    done
                else
                    warn "Docker servisleri başlatılamadı (postgres/redis)."
                fi
            fi

            if ! pg_isready -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" >/dev/null 2>&1; then
                warn "PostgreSQL erişilemedi ($DB_HOST:$DB_PORT/$DB_NAME) — migrasyon atlandı."
                info "DB hazır olduktan sonra manuel çalıştırın: python -m alembic -x \"database_url=$DB_URL\" upgrade head"
                MIGRATION_STATUS="db_erisilemez"
                return
            fi
        fi

        setup_pgvector_extension
    fi

    if python -m alembic -x "database_url=$DB_URL" upgrade head 2>&1; then
        ok "Alembic migrasyonları DATABASE_URL ile tamamlandı."
        MIGRATION_STATUS="tamamlandi"
    else
        warn "Migrasyon başarısız. Log'ları kontrol edin."
        MIGRATION_STATUS="hata"
    fi
}

# ── 13. CUDA bağlantı testi ──────────────────────────────────────────────────
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
            info "GPU wheel için: uv pip install torch>=2.4.1 --extra-index-url https://download.pytorch.org/whl/cu124"
        fi
    fi
}

# ── 14. Smoke testler ────────────────────────────────────────────────────────
run_smoke_tests() {
    step "Smoke Test Doğrulaması"
    local smoke_dir="$SCRIPT_DIR/tests/smoke"
    local should_run=false

    if [[ "$RUN_SMOKE_TESTS_MODE" == "never" ]]; then
        info "--skip-smoke-test verildiği için smoke testler atlandı."
        SMOKE_TEST_STATUS="atlandi_bayrak"
        return
    fi

    if [[ ! -d "$smoke_dir" ]]; then
        warn "Smoke test dizini bulunamadı: $smoke_dir"
        SMOKE_TEST_STATUS="dizin_yok"
        return
    fi

    if [[ "$RUN_SMOKE_TESTS_MODE" == "always" ]]; then
        should_run=true
    elif [[ -t 0 ]]; then
        read -r -p "Smoke testler (tests/smoke) çalıştırılsın mı? [E/h] " reply
        case "${reply:-E}" in
            [HhNn]*) should_run=false ;;
            *) should_run=true ;;
        esac
    else
        info "Etkileşimsiz modda smoke test otomatik atlandı. Çalıştırmak için --smoke-test kullanın."
        SMOKE_TEST_STATUS="atlandi_non_interactive"
        return
    fi

    if [[ "$should_run" != true ]]; then
        info "Smoke testler kullanıcı tercihiyle atlandı."
        SMOKE_TEST_STATUS="atlandi_kullanici"
        return
    fi

    if [[ "$USE_CONDA" == true ]]; then
        if ! "${CONDA_RUN[@]}" python -c "import pytest" >/dev/null 2>&1; then
            warn "pytest bu ortamda kurulu değil. --dev ile yeniden kurup tekrar deneyin."
            SMOKE_TEST_STATUS="pytest_yok"
            return
        fi
        if "${CONDA_RUN[@]}" python -m pytest "$smoke_dir"; then
            ok "Smoke testler başarıyla geçti."
            SMOKE_TEST_STATUS="tamamlandi"
        else
            warn "Smoke testlerde hata var. Logları inceleyin."
            SMOKE_TEST_STATUS="hata"
        fi
        return
    fi

    if ! python -c "import pytest" >/dev/null 2>&1; then
        warn "pytest bu ortamda kurulu değil. --dev ile yeniden kurup tekrar deneyin."
        SMOKE_TEST_STATUS="pytest_yok"
        return
    fi
    if python -m pytest "$smoke_dir"; then
        ok "Smoke testler başarıyla geçti."
        SMOKE_TEST_STATUS="tamamlandi"
    else
        warn "Smoke testlerde hata var. Logları inceleyin."
        SMOKE_TEST_STATUS="hata"
    fi
}

# ── 15. Özet ─────────────────────────────────────────────────────────────────
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
    echo -e "  3️⃣  Arka plan servislerini başlat (önerilir):"
    echo "       docker compose up -d"
    echo "       (PostgreSQL/Redis gibi servisleri Docker ile kullanıyorsanız önce bunu çalıştırın.)"
    echo ""
    echo -e "  4️⃣  CLI ile başlat:"
    echo "       python main.py"
    echo ""
    echo -e "  5️⃣  Web arayüzü ile başlat (http://localhost:7860):"
    echo "       python main.py --quick web"
    if [[ "$REACT_UI_STATUS" == "hazır" || "$REACT_UI_STATUS" == "hazır_cache" ]]; then
        if [[ "$REACT_UI_STATUS" == "hazır_cache" ]]; then
            echo "       React UI build: cache kullanıldı, yeniden derleme atlandı (web_ui_react/dist)"
        else
            echo "       React UI build: tamamlandı (web_ui_react/dist)"
        fi
    elif [[ "$REACT_UI_STATUS" == "build_hata" ]]; then
        echo "       React UI build: başarısız (npm install/npm run build hata verdi)"
        echo "       Logları kontrol edin ve manuel deneyin: cd web_ui_react && npm install && npm run build"
    else
        echo "       React UI build: atlandı (${REACT_UI_STATUS})"
        echo "       Manuel build için: cd web_ui_react && npm install && npm run build"
    fi
    echo ""
    echo -e "  6️⃣  Testleri çalıştır (--dev ile kurulduysa):"
    echo "       ./run_tests.sh"
    echo ""

    if [[ "$GPU_AVAILABLE" == true ]]; then
        echo -e "  ${GREEN}🚀 GPU hızlandırma aktif — .env: USE_GPU=true${NC}"
        echo ""
    fi

    echo -e "${BOLD}Faydalı Komutlar:${NC}"
    echo "  python github_upload.py   — projeyi GitHub'a yükle"
    if [[ "$MIGRATION_STATUS" == "tamamlandi" ]]; then
        echo "  Alembic migrasyonları kurulum sırasında tamamlandı."
    else
        echo "  python -m alembic upgrade head  — DB hazır olduktan sonra migrasyonu çalıştırın"
    fi
    if [[ "$SMOKE_TEST_STATUS" == "tamamlandi" ]]; then
        echo "  Smoke testler: başarılı (tests/smoke)."
    elif [[ "$SMOKE_TEST_STATUS" == "hata" ]]; then
        echo "  Smoke testler: hata var. Tekrar için: python -m pytest tests/smoke"
    else
        echo "  Smoke testler: atlandı (${SMOKE_TEST_STATUS}). Çalıştırmak için: python -m pytest tests/smoke"
    fi
    echo "  ollama serve              — Ollama servisini başlat"
    if [[ "$SKIP_MODELS" == true ]]; then
        echo "  ollama pull <model_adi>   — model indirmeleri atlandı, sonradan manuel indirin"
    fi
    echo "  docker compose up sidar-gpu     — Docker GPU modu"
    echo "  Not: Docker GPU için nvidia-container-toolkit kurulu olmalıdır."
    echo ""
    echo -e "${BOLD}Gözlemlenebilirlik (Telemetry)${NC}"
    echo "  İzleme servislerini başlat: docker compose up -d jaeger prometheus grafana"
    echo "  Grafana paneli    : http://localhost:3000 (varsayılan: admin / admin)"
    echo "  Prometheus paneli : http://localhost:9090"
    echo "  Jaeger UI         : http://localhost:16686"
    echo "  Not: Bu servisler docker_setup/ altındaki hazır konfigürasyonları kullanır."
    echo "  Güvenlik notu: Üretimde ACCESS_LEVEL ayarını dikkatle yapılandırın."
    echo ""
}

# ── Ana Akış ─────────────────────────────────────────────────────────────────
main() {
    banner
    if [[ "$INSTALL_KUBERNETES" == true ]]; then
        info "--kubernetes/--helm modu aktif: yerel bağımlılık kurulumu atlanacak, Helm dağıtımı yapılacak."
        deploy_with_helm
        return
    fi

    # Kritik sıra:
    # 1) Sistem bağımlılıkları (git/curl vb.)
    # 2) Repo senkronizasyonu (git clone/pull)
    # 3) Ön koşul doğrulaması (Conda/FFmpeg/Docker/Ollama)
    install_system_dependencies
    sync_repo
    cd "$SCRIPT_DIR"
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
    create_directories
    setup_react_frontend
    setup_env_file
    check_pyaudio_wsl2
    # Önce DB migrasyonu: olası bağlantı/şema hataları uzun model indirme öncesi görülsün.
    run_migrations
    download_ollama_models
    verify_torch_cuda
    run_smoke_tests
    print_summary
}

main "$@"