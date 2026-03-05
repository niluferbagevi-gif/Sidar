# SİDAR — Yazılım Mühendisi AI Asistanı

> **v2.7.0** — ReAct mimarisi üzerine kurulu, Türkçe dilli, tam async yazılım mühendisi AI projesi.

```
 ╔══════════════════════════════════════════════╗
 ║  ███████╗██╗██████╗  █████╗ ██████╗          ║
 ║  ██╔════╝██║██╔══██╗██╔══██╗██╔══██╗         ║
 ║  ███████╗██║██║  ██║███████║██████╔╝         ║
 ║  ╚════██║██║██║  ██║██╔══██║██╔══██╗         ║
 ║  ███████║██║██████╔╝██║  ██║██║  ██║         ║
 ║  ╚══════╝╚═╝╚═════╝ ╚═╝  ╚═╝╚═╝  ╚═╝         ║
 ║  Yazılım Mimarı & Baş Mühendis AI  v2.7.0  ║
 ╚══════════════════════════════════════════════╝
```

---

## Proje Hakkında

**Sidar**, kod yönetimi, sistem izleme, GitHub entegrasyonu, web araştırması ve güvenli dosya işlemleri konularında uzmanlaşmış bir AI asistanıdır. ReAct (Reason + Act) döngüsü ile çalışır; alias araçlar hariç **44+ çekirdek araç** üzerinden LLM destekli kararlar alır.

### Karakter Profili

| Özellik | Değer |
|---------|-------|
| Ad | SİDAR |
| Rol | Yazılım Mimarı & Baş Mühendis |
| Kişilik | Analitik, disiplinli, geek ruhu |
| İletişim | Minimal ve öz; gereksiz söz yok |
| Karar verme | Veri tabanlı, duygusal değil |
| Birincil Model | `qwen2.5-coder:7b` (Ollama, yerel) |
| Yedek Model | Google Gemini 2.0 Flash (bulut) |

---

## Özellikler

### Kod Yönetimi (CodeManager)
- PEP 8 uyumlu Python dosyası okuma/yazma
- Yazılımdan önce otomatik sözdizimi doğrulama (AST)
- JSON doğrulama
- Dosya yamalama (`patch_file` — sadece değişen satırlar)
- Dizin listeleme ve proje denetimi (`audit`)
- **Docker REPL Sandbox**: `python:3.11-alpine` içinde ağ/RAM/CPU kısıtlı izole kod çalıştırma (10 sn timeout)
- Metrik takibi (okunan/yazılan/doğrulanan)

### OpenClaw Güvenlik Sistemi (SecurityManager)

| Seviye | Okuma | Yazma | Kod Çalıştırma | Terminal (Shell) |
|--------|-------|-------|----------------|-----------------|
| `restricted` | ✓ | ✗ | ✗ | ✗ |
| `sandbox` | ✓ | Yalnızca `/temp` | ✓ | ✗ |
| `full` | ✓ | Her yer | ✓ | ✓ |

### Çoklu Oturum Bellek Yönetimi (ConversationMemory)
- UUID tabanlı, `data/sessions/*.json` şeklinde ayrı dosyalarda saklanan çoklu sohbet oturumları
- Thread-safe, JSON tabanlı kalıcı depolama
- Kayan pencere (varsayılan: 20 tur = 40 mesaj)
- **Otomatik Özetleme**: Pencere %80 dolduğunda LLM ile özetleme tetiklenir
- En son güncellenen oturum başlangıçta otomatik yükleniyor
- `create_session()`, `load_session()`, `delete_session()`, `update_title()` API'si

### ReAct Döngüsü (SidarAgent)
- **AutoHandle**: Örüntü tabanlı hızlı komut eşleme (LLM gerektirmez)
- **ReAct**: `Düşün → Araç çağır → Gözlemle` döngüsü (max 10 adım)
- **Pydantic v2 Doğrulama**: JSON ayrıştırma hatası alındığında modele hata detayı + beklenen format geri beslenir
- **Araç Görselleştirme**: Her tool çağrısı SSE eventi olarak istemciye iletilir; web UI'da badge olarak gösterilir
- Streaming yanıt (daktilo efekti)

### GPU Hızlandırma (v2.6.0+)
- PyTorch CUDA 12.4 desteği (RTX / Ampere serisi)
- FP16 mixed precision embedding (`GPU_MIXED_PRECISION=true`)
- VRAM fraksiyonu kontrolü (`GPU_MEMORY_FRACTION`)
- Çoklu GPU desteği (`MULTI_GPU=true`)
- WSL2 NVIDIA sürücü desteği (pynvml + nvidia-smi fallback)

### GitHub Entegrasyonu (GitHubManager)
- Depo bilgisi ve istatistikleri
- Son commit listesi
- Uzak dosya okuma (`github_read`)
- Uzak dosya yazma/commit (`github_write`)
- Branch listeleme + branch oluşturma (`github_list_files`, `github_create_branch`)
- PR açma/yönetimi (`github_create_pr`, `github_smart_pr`, `github_list_prs`, `github_get_pr`, `github_comment_pr`, `github_close_pr`, `github_pr_files`)
- Depo içinde kod arama (`github_search_code`)
- Çalışma zamanında aktif depo değiştirme (`/set-repo`)

### Web & Araştırma (WebSearchManager)
- **Tavily** (öncelikli), **Google Custom Search**, **DuckDuckGo** (sırasıyla denenir)
- URL içerik çekme — HTML temizleme dahil (`fetch_url`)
- Kütüphane dokümantasyon araması (`search_docs`)
- Stack Overflow araması (`search_stackoverflow`)

### Paket Bilgi Sistemi (PackageInfoManager)
- PyPI paket bilgisi ve sürüm karşılaştırma (`pypi`, `pypi_compare`)
- npm paket bilgisi (`npm`)
- GitHub Releases listesi ve en güncel sürüm (`gh_releases`, `gh_latest`)

### Hibrit RAG Belge Deposu (DocumentStore)
- ChromaDB vektör araması (semantik) + GPU embedding desteği
- BM25 anahtar kelime araması
- **Recursive Character Chunking** (`\nclass ` → `\ndef ` → `\n\n` → `\n` → ` ` öncelik sırası)
- URL'den async belge ekleme (`httpx.AsyncClient`)
- `RAG_CHUNK_SIZE`, `RAG_CHUNK_OVERLAP`, `RAG_TOP_K` env değişkenleri ile yapılandırılabilir

### Sistem Sağlığı (SystemHealthManager)
- CPU ve RAM kullanım izleme (psutil)
- GPU/CUDA bilgisi ve VRAM takibi (pynvml)
- GPU bellek optimizasyonu (VRAM boşaltma + Python GC)

### Web Arayüzü (v2.7.0)
- **Çoklu oturum sidebar**: oturum geçişi, oluşturma, silme, arama/filtreleme
- **Dışa Aktarma**: Sohbet geçmişini MD veya JSON olarak indirme
- **ReAct Araç Görselleştirmesi**: Her tool çağrısı animasyonlu Türkçe badge (genişletilmiş araç seti)
- **Talimat Dosyası Uyumu**: `SIDAR.md` ve `CLAUDE.md` dosyaları proje genelinde otomatik taranır; alt klasör talimatları üst klasörleri override edecek şekilde bağlama eklenir
- **Hazır Şablon Dosyaları**: Proje kökünde varsayılan `SIDAR.md` ve `CLAUDE.md` dosyaları gelir; doğrudan düzenleyip kendi kurallarınızı yazabilirsiniz
- **Mobil Uyum**: 768px altında hamburger menüsü + sidebar overlay
- Koyu/Açık tema (localStorage tabanlı)
- Klavye kısayolları (`Ctrl+K`, `Ctrl+L`, `Alt+T`, `Esc`)
- Streaming durdur butonu (AbortController)
- Kod bloğu kopyala butonu (hover ile görünür)
- Dosya ekleme (200 KB limit, metin/kod dosyaları)
- Dinamik model ismi gösterimi (`/status` üzerinden)
- Dal seçimi — gerçek `git checkout` ile backend'e bağlı
- Katmanlı rate limiting: `/chat` için 20, mutasyon (POST/DELETE) için 60, Git/Dosya I/O GET uçları için 30 istek/dakika/IP

---

## v2.7.0 Öne Çıkan Yetenekler

### ✅ TodoManager ile Görev Takibi

- Ajan görevleri `TodoManager` üzerinden durum bazlı (`pending`, `in_progress`, `done`) yönetir.
- Aynı anda tek aktif iş kuralı uygulanır; odak kaybı ve çoklu görev karmaşası azaltılır.
- Web UI ve CLI akışlarında görevler kullanıcıya şeffaf şekilde raporlanır.

### ✅ Sonsuz Hafıza (Vector Archive)

- Uzun sohbetlerde eski bağlam, tamamen silinmek yerine vektör arşive (ChromaDB) aktarılır.
- Gerektiğinde benzerlik tabanlı geri çağırma ile geçmiş bilgi yeniden bağlama alınır.
- Bu model, bağlam penceresi baskısını azaltırken bilgi sürekliliğini korur.

### ✅ Bellek Şifreleme (Fernet)

- `MEMORY_ENCRYPTION_KEY` tanımlandığında oturum dosyaları diskte şifrelenir.
- Hassas ortamlarda varsayılan JSON saklama yerine şifreli depolama önerilir.
- Anahtar üretimi için örnek komut:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

---

## Araç Listesi (44+ Çekirdek Araç)

| Araç | Açıklama | Argüman |
|------|----------|---------|
| `list_dir` | Dizin listele | yol |
| `read_file` | Dosya oku | dosya_yolu |
| `write_file` | Dosya yaz (tamamını) | `path\|\|\|content` |
| `patch_file` | Dosya yamala (fark) | `path\|\|\|eski\|\|\|yeni` |
| `glob_search` | Glob deseni ile dosya ara | `desen[\|\|\|dizin]` |
| `grep_files` | Regex ile içerik ara | `regex[\|\|\|path[\|\|\|filtre[\|\|\|bağlam]]]` |
| `execute_code` | Python REPL (Docker sandbox) | python_kodu |
| `run_shell` (`bash`) | Kabuk komutu çalıştır | komut |
| `audit` | Proje denetimi | `.` |
| `health` | Sistem sağlık raporu | — |
| `gpu_optimize` | GPU bellek temizle | — |
| `get_config` | Runtime konfigürasyonunu getir | — |
| `github_commits` | Son commit listesi | sayı |
| `github_info` | Depo bilgisi | — |
| `github_read` | Uzak depodaki dosyayı oku | dosya_yolu |
| `github_list_files` | Uzak dizin içeriği listele | `path[\|\|\|branch]` |
| `github_write` | Uzak depoya dosya yaz/commit | `path\|\|\|content\|\|\|commit[\|\|\|branch]` |
| `github_create_branch` | Yeni branch oluştur | `branch[\|\|\|source]` |
| `github_create_pr` | PR oluştur | `title\|\|\|body\|\|\|head[\|\|\|base]` |
| `github_smart_pr` | Diff analizli akıllı PR aç | `[head[\|\|\|base[\|\|\|notes]]]` |
| `github_list_prs` | PR listesini getir | `state[\|\|\|limit]` |
| `github_get_pr` | PR detayını getir | pr_no |
| `github_comment_pr` | PR'a yorum ekle | `pr_no\|\|\|comment` |
| `github_close_pr` | PR kapat | pr_no |
| `github_pr_files` | PR dosya değişikliklerini listele | pr_no |
| `github_search_code` | Depoda kod ara | sorgu |
| `web_search` | Tavily/Google/DDG ile ara | sorgu |
| `fetch_url` | URL içeriğini çek | url |
| `search_docs` | Kütüphane dokümanı ara | `lib konu` |
| `search_stackoverflow` | Stack Overflow araması | sorgu |
| `pypi` | PyPI paket bilgisi | paket_adı |
| `pypi_compare` | Sürüm karşılaştır | `paket\|sürüm` |
| `npm` | npm paket bilgisi | paket_adı |
| `gh_releases` | GitHub release listesi | `owner/repo` |
| `gh_latest` | En güncel release | `owner/repo` |
| `docs_search` | Belge deposunda ara | sorgu |
| `docs_add` | URL'den belge ekle | `başlık\|url` |
| `docs_add_file` | Yerel dosyayı RAG'a ekle | `dosya_yolu` veya `başlık\|dosya_yolu` |
| `docs_list` | Belgeleri listele | — |
| `docs_delete` | Belge sil | doc_id |
| `todo_write` | Görev listesi oluştur/güncelle | `görev:::durum\|\|\|...` |
| `todo_read` | Görev listesini oku | — |
| `todo_update` | Görev durumunu güncelle | `id\|\|\|durum` |
| `subtask` (`agent`) | Alt ajan görevi çalıştır | alt_görev |
| `parallel` | Birden çok alt görevi paralel yürüt | `görev1\|\|\|görev2...` |
| `final_answer` | Kullanıcıya yanıt ver | yanıt_metni |

---

## Kurulum

### Conda ile (Önerilen)

```bash
cd sidar_project
conda env create -f environment.yml
conda activate sidar-ai
```

### pip ile

```bash
pip install python-dotenv httpx psutil pynvml \
            google-generativeai PyGithub duckduckgo-search \
            rank-bm25 chromadb sentence-transformers \
            fastapi uvicorn pydantic docker pywebview \
            pytest pytest-asyncio pytest-cov
```

> **Not:** GPU desteği için `torch` ve `torchvision`'ı [PyTorch resmi sitesinden](https://pytorch.org/get-started/locally/) CUDA sürümünüze uygun wheel ile kurun.

### Çevre Değişkenleri

```bash
cp .env.example .env
# .env dosyasını düzenleyin
```

### Ollama Kurulumu

```bash
# Resmi Linux kurulumu: https://ollama.com/download/linux
ollama pull qwen2.5-coder:7b
ollama serve
```

> Güvenlik notu: `install_sidar.sh` varsayılan olarak uzaktan kurulum scripti çalıştırmaz.
> Otomatik kurulum gerekiyorsa bilinçli opt-in ile çalıştırın: `ALLOW_OLLAMA_INSTALL_SCRIPT=1 ./install_sidar.sh`.

### Docker ile

```bash
# CPU modu
docker compose up --build sidar-web

# GPU modu (NVIDIA)
docker compose up --build sidar-web-gpu
```

### Otomatik Kurulum Betiği (Ubuntu/WSL)

```bash
./install_sidar.sh

# İsteğe bağlı (riskli adımları bilinçli olarak açmak için):
ALLOW_APT_UPGRADE=1 ALLOW_OLLAMA_INSTALL_SCRIPT=1 ./install_sidar.sh
```

---

## Kullanım

### 🌐 Web Arayüzü (Önerilen)

```bash
python web_server.py
```

Tarayıcıda açılır: **http://localhost:7860**

```bash
# Özel host/port
python web_server.py --host 0.0.0.0 --port 8080

# Erişim seviyesi ile
python web_server.py --level sandbox

# Gemini sağlayıcısı ile
python web_server.py --provider gemini --port 7860
```

Web arayüzü özellikleri:
- Streaming chat (daktilo efekti) + araç görselleştirmesi
- Çoklu oturum yönetimi (sidebar)
- Sohbet geçmişini MD/JSON olarak dışa aktarma
- Markdown ve kod bloğu renklendirme (highlight.js)
- Sistem durumu paneli (model, versiyon, GitHub, RAG, GPU)
- Dal seçimi (gerçek git checkout)
- Mobil uyumlu hamburger menüsü

### 🚀 Akıllı Launcher (main.py)

```bash
# Etkileşimli sihirbaz (önerilen)
python main.py

# Sihirbazı atlayıp hızlı CLI başlat
python main.py --quick cli --provider ollama --level full --model qwen2.5-coder:7b

# Sihirbazı atlayıp hızlı Web başlat
python main.py --quick web --provider gemini --level sandbox --host 0.0.0.0 --port 7860
```

Launcher akışı step-by-step olarak seçim yaptırır ve `cli.py` veya `web_server.py` süreçlerini alt süreçte başlatır.

### 💻 Terminal (CLI) Modu

```bash
python cli.py
```

### Tek Komut Modu

```bash
python cli.py -c "Proje dizinini listele"
python cli.py --status
python cli.py --level full -c "Sistemi denetle"
python cli.py --provider gemini -c "FastAPI nedir?"
```

### CLI Seçenekleri

```
-c, --command   Tek komut çalıştır ve çık
--status        Sistem durumunu göster
--level         Erişim seviyesi (restricted/sandbox/full)
--provider      AI sağlayıcısı (ollama/gemini)
--model         Ollama model adı
--log           Log seviyesi (DEBUG/INFO/WARNING)
```

### Dahili Komutlar (CLI)

```
.status     Sistem durumunu göster
.clear      Konuşma belleğini temizle
.audit      Proje denetimini çalıştır
.health     Sistem sağlık raporu
.gpu        GPU belleğini optimize et
.github     GitHub bağlantı durumu
.level      Mevcut erişim seviyesini göster
.web        Web arama durumu
.docs       Belge deposunu listele
.help       Yardım
.exit / .q  Çıkış
```

---

## Örnek Komutlar

```
# Dizin & Dosya
"Ana klasördeki dosyaları listele"
"config.py dosyasını oku ve özetle"
"main.py içindeki X satırını Y ile değiştir"

# Kod Geliştirme
"Fibonacci dizisi hesaplayan bir fonksiyon yaz ve test et"
"Bu kodu çalıştır: print(sum(range(100)))"

# Sistem
"Sistem sağlık raporu ver"
"GPU belleğini temizle"
"Projeyi denetle ve teknik rapor ver"

# GitHub
"Son 10 commit'i listele"
"GitHub'dan README.md dosyasını oku"

# Web Araştırma
"FastAPI'nin son sürümünü kontrol et"
"web'de ara: Python async best practices 2025"
"pypi: httpx"
"stackoverflow: Python type hints generic"

# Belgeler (RAG)
"belge ekle https://docs.python.org/3/library/asyncio.html"
"docs ara: asyncio event loop"
```

---

## Proje Yapısı

```
sidar_project/
├── agent/
│   ├── __init__.py
│   ├── definitions.py      # Sidar karakter profili ve sistem talimatı (25 araç)
│   ├── sidar_agent.py      # Ana ajan (ReAct, Pydantic v2, dispatcher, araç sentinel)
│   └── auto_handle.py      # Örüntü tabanlı hızlı komut eşleyici (async)
├── core/
│   ├── __init__.py
│   ├── memory.py           # Çoklu oturum (session) yönetimi — thread-safe JSON
│   ├── llm_client.py       # Ollama stream + Gemini async istemcisi
│   └── rag.py              # Hibrit RAG (ChromaDB + BM25), Recursive Chunking, GPU
├── managers/
│   ├── __init__.py
│   ├── code_manager.py     # Dosya operasyonları, AST, Docker REPL sandbox
│   ├── system_health.py    # CPU/RAM/GPU izleme (pynvml + nvidia-smi fallback)
│   ├── github_manager.py   # GitHub API entegrasyonu (binary koruma, branch)
│   ├── security.py         # OpenClaw 3 seviyeli erişim kontrol sistemi
│   ├── web_search.py       # Tavily + Google + DuckDuckGo (async, çoklu motor)
│   ├── package_info.py     # PyPI + npm + GitHub Releases (async)
│   └── todo_manager.py     # Görev listesi yönetimi (pending/in_progress/completed)
├── tests/
│   ├── __init__.py
│   └── test_sidar.py       # 11 test sınıfı (GPU + Chunking + Pydantic testleri dahil)
├── web_ui/
│   └── index.html          # Tam özellikli web arayüzü (SSE, session, export, mobil)
├── data/                   # Oturum JSON'ları ve RAG veritabanı (gitignore'da)
├── temp/                   # Sandbox modunda yazma dizini (gitignore'da)
├── logs/                   # Log dosyaları — RotatingFileHandler (gitignore'da)
├── config.py               # Merkezi yapılandırma + GPU tespiti + WSL2 desteği
├── main.py                 # Etkileşimli launcher (wizard + quick start)
├── cli.py                  # Asıl terminal tabanlı CLI giriş noktası (async loop)
├── web_server.py           # FastAPI + SSE + Rate limiting + Session API + /set-branch
├── github_upload.py        # GitHub'a otomatik yükleme yardımcı betiği
├── Dockerfile              # CPU/GPU dual-mode build (python:3.11-slim)
├── docker-compose.yml      # 4 servis: CPU/GPU × CLI/Web
├── environment.yml         # Conda — PyTorch CUDA 12.4 (cu124) wheel, pytest-asyncio
├── .env.example            # Açıklamalı ortam değişkeni şablonu
└── install_sidar.sh        # Ubuntu/WSL sıfırdan kurulum scripti
```

---

## Testleri Çalıştır

```bash
cd sidar_project
pytest tests/ -v
pytest tests/ -v --cov=. --cov-report=term-missing
```

**Test sınıfları (11 adet):**
- `TestCodeManager` — Dosya yazma/okuma ve AST doğrulama
- `TestToolCallPydantic` — Pydantic v2 ToolCall şeması doğrulama
- `TestWebSearchManager` — Motor seçimi ve durum (async)
- `TestDocumentStore` — Chunking + retrieve + GPU parametreleri
- `TestSidarAgentInit` — SidarAgent başlatma (async)
- `TestHardwareInfo` — HardwareInfo dataclass alanları
- `TestConfigGPU` — Config GPU alanları
- `TestSystemHealthManager` — CPU-only rapor
- `TestSystemHealthGPU` — GPU bilgi yapısı
- `TestRAGGPU` — DocumentStore GPU parametreleri
- `TestSecurityManager` — OpenClaw izin sistemi

---

## Yapılandırma (.env)

```env
# AI Sağlayıcı
AI_PROVIDER=ollama              # ollama | gemini
CODING_MODEL=qwen2.5-coder:7b
OLLAMA_URL=http://localhost:11434/api
TEXT_MODEL=gemma2:9b
GEMINI_API_KEY=                 # Gemini kullanılacaksa

# Güvenlik
ACCESS_LEVEL=sandbox            # restricted | sandbox | full

# GitHub
GITHUB_TOKEN=
GITHUB_REPO=kullanici/depo

# Web Sunucu
WEB_HOST=0.0.0.0
WEB_PORT=7860

# Bellek & Oturum
MAX_MEMORY_TURNS=20
MEMORY_ENCRYPTION_KEY=          # Opsiyonel (Fernet key)

# Zaman Aşımı
OLLAMA_TIMEOUT=30
REACT_TIMEOUT=60

# Web Arama
TAVILY_API_KEY=                 # Tavily kullanılacaksa (öncelikli)
GOOGLE_SEARCH_API_KEY=          # Google Custom Search kullanılacaksa
GOOGLE_SEARCH_CX=
WEB_SEARCH_MAX_RESULTS=5
WEB_FETCH_TIMEOUT=15
WEB_FETCH_MAX_CHARS=4000

# RAG
RAG_TOP_K=3
RAG_CHUNK_SIZE=1000
RAG_CHUNK_OVERLAP=200

# Paket Bilgi
PACKAGE_INFO_TIMEOUT=12

# GPU (opsiyonel)
USE_GPU=false                   # true: GPU embedding aktif
GPU_DEVICE=0
GPU_MEMORY_FRACTION=0.8
GPU_MIXED_PRECISION=false
MULTI_GPU=false
```

---

## Geliştirme

```bash
black .
flake8 . --max-line-length=100
mypy . --ignore-missing-imports
```

---

## Sürüm Geçmişi

| Versiyon | Önemli Değişiklikler |
|----------|----------------------|
| **v2.7.0** | Launcher/CLI ayrımı (`main.py` launcher, `cli.py` async terminal), canlı aktivite paneli, THOUGHT sentinel, hibrit RAG belge yönetimi ve ek doğrulama düzeltmeleri |
| **v2.6.1** | Web UI düzeltmeleri: dışa aktarma, araç görselleştirme, mobil menü, dinamik model adı, gerçek git checkout, CancelledError düzeltmesi |
| **v2.6.0** | GPU hızlandırma, Docker REPL sandbox, çoklu oturum, Recursive Chunking, Pydantic v2, rate limiting, WSL2 desteği |
| **v2.5.0** | Async mimari (httpx, asyncio.Lock), dispatcher tablosu, pytest-asyncio |
| **v2.3.2** | İlk kararlı sürüm |

---

## Lisans

Bu proje LotusAI ekosisteminin bir parçasıdır.