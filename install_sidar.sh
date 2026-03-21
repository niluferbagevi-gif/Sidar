#!/usr/bin/env bash
# Sidar AI — Otomatik Kurulum Betiği
# Sürüm: 5.1.0 (v5.0.0-alpha baseline)

# Hata durumunda betiği durdur
set -euo pipefail

PROJECT_NAME="Sidar"
ENV_NAME="sidar-ai"
# Gerekirse kendi SİDAR repo URL'nizle değiştirin
REPO_URL="https://github.com/niluferbagevi-gif/Sidar"
PROJECT_DIR="$HOME/$PROJECT_NAME"
MINICONDA_DIR="$HOME/miniconda3"
MINICONDA_SH="$MINICONDA_DIR/miniconda.sh"
OLLAMA_PID=""
ALLOW_APT_UPGRADE="${ALLOW_APT_UPGRADE:-0}"
ALLOW_OLLAMA_INSTALL_SCRIPT="${ALLOW_OLLAMA_INSTALL_SCRIPT:-0}"
DOCKER_COMPOSE_CMD=""

cleanup() {
  if [[ -n "${OLLAMA_PID}" ]] && kill -0 "${OLLAMA_PID}" >/dev/null 2>&1; then
    kill "${OLLAMA_PID}" || true
  fi
}
trap cleanup EXIT

detect_docker_compose() {
  if docker compose version >/dev/null 2>&1; then
    DOCKER_COMPOSE_CMD="docker compose"
  elif command -v docker-compose >/dev/null 2>&1; then
    DOCKER_COMPOSE_CMD="docker-compose"
  else
    DOCKER_COMPOSE_CMD=""
  fi
}

print_header() {
  echo "============================================================"
  echo " 🚀 SİDAR - Sıfırdan Ubuntu (WSL) Otomatik Kurulum Aracı"
  echo "============================================================"
}

install_system_packages() {
  echo -e "\n📦 1. Sistem paket indeksleri güncelleniyor ve temel paketler kuruluyor..."
  sudo apt update

  if [[ "$ALLOW_APT_UPGRADE" == "1" ]]; then
    echo "⚠️ ALLOW_APT_UPGRADE=1 olduğu için sistem yükseltmesi uygulanıyor..."
    sudo apt upgrade -y
  else
    echo "ℹ️ Sistem yükseltmesi varsayılan olarak kapalı (ALLOW_APT_UPGRADE=1 ile açabilirsiniz)."
  fi

  sudo apt install -y curl wget git build-essential software-properties-common zstd nodejs npm
  sudo apt install -y portaudio19-dev python3-pyaudio alsa-utils v4l-utils ffmpeg
}

install_google_chrome() {
  echo -e "\n🌐 1.5. Google Chrome kontrol ediliyor..."
  if command -v google-chrome-stable >/dev/null 2>&1 || command -v google-chrome >/dev/null 2>&1; then
    echo "✅ Google Chrome zaten kurulu."
    return 0
  fi
  echo "   Chrome bulunamadı. İndiriliyor ve kuruluyor..."
  wget https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb -O /tmp/chrome.deb
  sudo apt install -y /tmp/chrome.deb
  rm -f /tmp/chrome.deb
  echo "✅ Google Chrome başarıyla kuruldu."
}

install_miniconda() {
  echo -e "\n🐍 2. Miniconda kuruluyor..."
  if [[ ! -d "$MINICONDA_DIR" ]]; then
    mkdir -p "$MINICONDA_DIR"
    wget https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh -O "$MINICONDA_SH"
    bash "$MINICONDA_SH" -b -u -p "$MINICONDA_DIR"
    rm -f "$MINICONDA_SH"
    "$MINICONDA_DIR/bin/conda" init bash
    echo "✅ Miniconda başarıyla kuruldu."
  else
    echo "✅ Miniconda zaten kurulu."
  fi

  # Conda'yı bu oturumda hemen kullanabilmek için etkinleştiriyoruz
  # shellcheck disable=SC1091
  source "$MINICONDA_DIR/etc/profile.d/conda.sh"
}

install_ollama() {
  echo -e "\n🦙 3. Ollama kuruluyor..."
  if ! ollama -v >/dev/null 2>&1; then
    echo "⚠️ Ollama bulunamadı veya kurulumu bozuk."
    if [[ "$ALLOW_OLLAMA_INSTALL_SCRIPT" != "1" ]]; then
      echo "❌ Güvenlik nedeniyle otomatik uzaktan script çalıştırma kapalı."
      echo "   Önce manuel kurulum yapın: https://ollama.com/download/linux"
      echo "   Otomatik kurulum için bilinçli onay: ALLOW_OLLAMA_INSTALL_SCRIPT=1 ./install_sidar.sh"
      exit 1
    fi

    local installer="/tmp/ollama_install.sh"
    echo "ℹ️ Kurulum scripti indiriliyor: $installer"
    curl -fsSL https://ollama.com/install.sh -o "$installer"
    chmod 700 "$installer"
    sudo rm -f /usr/local/bin/ollama
    sh "$installer"
    rm -f "$installer"
    echo "✅ Ollama başarıyla kuruldu."
  else
    echo "✅ Ollama zaten kurulu ve çalışıyor."
  fi
}

clone_or_update_repo() {
  echo -e "\n🐙 4. SİDAR projesi GitHub'dan çekiliyor..."
  if [[ ! -d "$PROJECT_DIR" ]]; then
    git clone "$REPO_URL" "$PROJECT_DIR"
  else
    echo "⚠️ SİDAR klasörü zaten var. Git pull ile güncelleniyor..."
    git -C "$PROJECT_DIR" pull
  fi
  cd "$PROJECT_DIR"
}

prepare_runtime_dirs() {
  echo -e "\n📂 4.5. Gerekli çalışma dizinleri oluşturuluyor..."
  mkdir -p "$PROJECT_DIR/sessions" "$PROJECT_DIR/chroma_db" "$PROJECT_DIR/logs" "$PROJECT_DIR/models"
  echo "✅ sessions/, chroma_db/, logs/ ve models/ dizinleri hazır."
}

setup_conda_env() {
  echo -e "\n⚙️  5. Conda ortamı ($ENV_NAME) environment.yml dosyasından kuruluyor..."
  if conda info --envs | awk '{print $1}' | grep -qx "$ENV_NAME"; then
    echo "   Ortam zaten var, güncelleniyor (--prune ile eski paketler temizlenecek)..."
    conda env update -f environment.yml --prune
  else
    echo "   Yeni Conda ortamı oluşturuluyor..."
    conda env create -f environment.yml
  fi
  echo "✅ Conda ortamı hazır. Aktif hale getirmek için: conda activate $ENV_NAME"
}

pull_models() {
  echo -e "\n🧠 6. Yapay zeka modelleri hazırlanıyor..."
  if ! command -v ollama >/dev/null 2>&1; then
    echo "⚠️ Ollama bulunamadı, model indirme adımı atlandı."
    return 0
  fi

  ollama serve >/dev/null 2>&1 &
  OLLAMA_PID=$!

  echo -e "   Ollama servisi başlatılıyor..."
  local retries=30
  local i=0
  until curl -sf http://localhost:11434/api/tags >/dev/null 2>&1; do
    i=$((i + 1))
    if [[ $i -ge $retries ]]; then
      echo "❌ Ollama 30 saniye içinde yanıt vermedi. Kurulum durduruluyor."
      exit 1
    fi
    sleep 1
  done
  echo "   ✅ Ollama hazır (${i}s)."

  echo "-> qwen2.5-coder:7b (SİDAR varsayılan model) indiriliyor..."
  ollama pull qwen2.5-coder:7b
  echo "-> nomic-embed-text (RAG embed) indiriliyor..."
  ollama pull nomic-embed-text
}

print_footer() {
  echo "============================================================"
  echo "🚀 SİDAR v5.1.0 Kurulumu Tamamlandı!"
  echo "============================================================"
  echo "Lütfen yeni ayarların yüklenmesi için terminali kapatıp YENİDEN AÇIN."
  echo ""
  echo "🌐 Web Arayüzü: http://localhost:7860"
  echo "🚀 Ultimate Launcher: python main.py"
  if [[ -n "$DOCKER_COMPOSE_CMD" ]]; then
    echo "🐳 Docker Compose: $DOCKER_COMPOSE_CMD up --build sidar-web"
  else
    echo "⚠️ Docker Compose bulunamadı."
  fi
  echo ""
  echo "Sonrasında SİDAR'ı çalıştırmak için sırasıyla şunları yazın:"
  echo "  1. cd ~/$PROJECT_NAME"
  echo "  2. conda activate $ENV_NAME"
  echo "  3. nano .env                    ← AI sağlayıcısı, token'lar ve ayarları yapılandırın"
  echo "  4. alembic upgrade head         ← (ÖNEMLİ) Veritabanı tablolarını oluşturmak için"
  echo "  5. python -m pytest             ← (Opsiyonel) Tüm testleri çalıştırmak için"
  echo "  6. python main.py               ← Etkileşimli TUI menüsü ile başlatmak için"
  echo ""
  echo "Güvenlik notu:"
  echo "  - Sistem yükseltmesi varsayılan kapalıdır (ALLOW_APT_UPGRADE=1 ile açılır)."
  echo "  - Otomatik Ollama script kurulumu varsayılan kapalıdır (ALLOW_OLLAMA_INSTALL_SCRIPT=1 ile açılır)."
  echo "============================================================"
}

setup_env_file() {
  echo -e "\n⚙️  8. Çevre değişkenleri dosyası (.env) ayarlanıyor..."
  if [[ -f "$PROJECT_DIR/.env" ]]; then
    echo "✅ .env dosyası zaten mevcut. Üzerine yazılmıyor."
  else
    cp "$PROJECT_DIR/.env.example" "$PROJECT_DIR/.env"
    echo "✅ .env.example → .env olarak kopyalandı."
    echo "   📝 Önemli: $PROJECT_DIR/.env dosyasını açarak"
    echo "      AI sağlayıcınızı (AI_PROVIDER) ve diğer ayarları yapılandırın."
  fi
}

build_react_frontend() {
  echo -e "\n⚛️ 10. React tabanlı web arayüzü (web_ui_react) derleniyor..."
  if [[ -d "$PROJECT_DIR/web_ui_react" ]]; then
    cd "$PROJECT_DIR/web_ui_react"
    echo "   npm paketleri yükleniyor..."
    npm install
    echo "   Production build alınıyor..."
    npm run build
    cd "$PROJECT_DIR"
    echo "✅ React arayüzü başarıyla derlendi."
  else
    echo "⚠️ web_ui_react klasörü bulunamadı, bu adım atlanıyor."
  fi
}

download_vendor_libs() {
  echo -e "\n📚 9. Web arayüzü bağımlılıkları yerel olarak indiriliyor (çevrimdışı destek)..."
  local vendor_dir="$PROJECT_DIR/web_ui/vendor"
  mkdir -p "$vendor_dir"

  local failed=0

  curl -fsSL "https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/styles/github-dark.min.css" \
    -o "$vendor_dir/highlight.min.css" || { echo "⚠️ highlight.min.css indirilemedi (CDN yedek kullanılacak)."; failed=1; }
  curl -fsSL "https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/highlight.min.js" \
    -o "$vendor_dir/highlight.min.js" || { echo "⚠️ highlight.min.js indirilemedi (CDN yedek kullanılacak)."; failed=1; }
  curl -fsSL "https://cdn.jsdelivr.net/npm/marked@9.1.6/marked.min.js" \
    -o "$vendor_dir/marked.min.js" || { echo "⚠️ marked.min.js indirilemedi (CDN yedek kullanılacak)."; failed=1; }

  if [[ $failed -eq 0 ]]; then
    echo "✅ Vendor kütüphaneleri web_ui/vendor/ dizinine indirildi."
  else
    echo "⚠️ Bazı vendor dosyaları indirilemedi. Web arayüzü CDN üzerinden çalışmaya devam eder."
  fi
}

print_header
detect_docker_compose
install_system_packages
install_google_chrome
install_miniconda
install_ollama
clone_or_update_repo
prepare_runtime_dirs
setup_conda_env
pull_models
setup_env_file
download_vendor_libs
build_react_frontend
print_footer