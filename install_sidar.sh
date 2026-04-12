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
INSTALL_DEV=false
FORCE_CPU=false
PLAYWRIGHT_REQUESTED=false
for arg in "$@"; do
    case "$arg" in
        --dev)  INSTALL_DEV=true ;;
        --cpu)  FORCE_CPU=true ;;
        *)      warn "Bilinmeyen argüman: $arg (--dev | --cpu kabul edilir)"; exit 1 ;;
    esac
done

# ── Sabitler ──────────────────────────────────────────────────────────────────
CONDA_ENV_NAME="sidar-ai"
PYTHON_VERSION="3.11"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REQUIRED_DIRS=(data logs temp sessions chroma_db data/rag data/lora_adapters data/continuous_learning)

banner() {
    echo -e "${BOLD}${BLUE}"
    echo "╔══════════════════════════════════════════════════════════════╗"
    echo "║          Sidar AI — Kurulum Başlıyor (v5.2.0)               ║"
    echo "╚══════════════════════════════════════════════════════════════╝"
    echo -e "${NC}"
}

# ── 1. Ön koşul kontrolleri ───────────────────────────────────────────────────
check_prerequisites() {
    step "Ön Koşullar Kontrol Ediliyor"

    # Conda (opsiyonel)
    if command -v conda &>/dev/null; then
        USE_CONDA=true
        ok "Conda $(conda --version | cut -d' ' -f2)"
    else
        USE_CONDA=false
        warn "Conda bulunamadı — uv venv fallback kullanılacak."
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
    step "React Web UI Kurulumu"

    REACT_DIR="$SCRIPT_DIR/web_ui_react"
    if [[ ! -d "$REACT_DIR" ]]; then
        info "web_ui_react dizini bulunamadı — frontend kurulumu atlandı."
        return
    fi

    if [[ ! -f "$REACT_DIR/package.json" ]]; then
        info "web_ui_react/package.json bulunamadı — frontend kurulumu atlandı."
        return
    fi

    if ! command -v npm &>/dev/null; then
        warn "npm bulunamadı. React Web UI için Node.js + npm kurun ve şu komutları çalıştırın:"
        echo "       cd web_ui_react && npm install && npm run build"
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
}

# ── 8. PyAudio WSL2 uyarısı ──────────────────────────────────────────────────
check_pyaudio_wsl2() {
    if [[ "$WSL2" == true ]]; then
        warn "WSL2 üzerinde ses donanımına erişim kısıtlıdır."
        info "Sesli özellik kullanmayacaksanız .env dosyanıza şunu ekleyin:"
        echo "       USE_VOICE=false"
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
setup_env_file() {
    step ".env Yapılandırması"
    ENV_FILE="$SCRIPT_DIR/.env"
    EXAMPLE_FILE="$SCRIPT_DIR/.env.example"

    if [[ -f "$ENV_FILE" ]]; then
        ok ".env dosyası zaten mevcut — atlandı."
        return
    fi

    if [[ ! -f "$EXAMPLE_FILE" ]]; then
        warn ".env.example bulunamadı — .env oluşturulamadı. Manuel olarak oluşturun."
        return
    fi

    cp "$EXAMPLE_FILE" "$ENV_FILE"
    ok ".env dosyası .env.example'dan oluşturuldu."

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

    # GPU tespiti varsa .env içinde USE_GPU=true yap
    if [[ "$GPU_AVAILABLE" == true ]]; then
        if command -v sed &>/dev/null; then
            sed -i 's/^USE_GPU=false/USE_GPU=true/' "$ENV_FILE"
            sed -i 's/^GPU_MIXED_PRECISION=false/GPU_MIXED_PRECISION=true/' "$ENV_FILE"
            ok ".env: USE_GPU=true, GPU_MIXED_PRECISION=true (RTX 30xx Ampere FP16 desteği)"
        fi
    fi

    warn ".env dosyasını açın ve API anahtarlarınızı (OPENAI_API_KEY, GEMINI_API_KEY vb.) doldurun."
}

# ── 11. Alembic migrasyonları ────────────────────────────────────────────────
run_migrations() {
    step "Veritabanı Migrasyonları"
    ALEMBIC_INI="$SCRIPT_DIR/alembic.ini"

    if [[ ! -f "$ALEMBIC_INI" ]]; then
        warn "alembic.ini bulunamadı — migrasyon atlandı."
        return
    fi

    cd "$SCRIPT_DIR"
    if python -m alembic upgrade head 2>&1; then
        ok "Alembic migrasyonları tamamlandı."
    else
        warn "Migrasyon başarısız veya kısmen tamamlandı. Log'ları kontrol edin."
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
    echo ""
    echo -e "  5️⃣  Testleri çalıştır (--dev ile kurulduysa):"
    echo "       pytest tests/ -x -q"
    echo ""

    if [[ "$GPU_AVAILABLE" == true ]]; then
        echo -e "  ${GREEN}🚀 GPU hızlandırma aktif — .env: USE_GPU=true${NC}"
        echo ""
    fi

    echo -e "${BOLD}Faydalı Komutlar:${NC}"
    echo "  python github_upload.py   — projeyi GitHub'a yükle"
    echo "  python -m alembic upgrade head  — DB migrasyonu"
    echo "  docker compose up sidar-gpu     — Docker GPU modu"
    echo "  Güvenlik notu: Üretimde ACCESS_LEVEL ayarını dikkatle yapılandırın."
    echo ""
}

# ── Ana Akış ─────────────────────────────────────────────────────────────────
main() {
    cd "$SCRIPT_DIR"
    banner
    check_prerequisites
    detect_gpu
    setup_uv
    setup_python_env
    install_python_deps
    install_playwright_browsers
    check_pyaudio_wsl2
    create_directories
    setup_env_file
    setup_react_frontend
    run_migrations
    verify_torch_cuda
    print_summary
}

main "$@"
