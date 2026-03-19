# SİDAR — Yazılım Mühendisi AI Asistanı

> **v3.0.0** — ReAct + Multi-Agent kurumsal mimari üzerine kurulu, Türkçe dilli, tam async yazılım mühendisi AI projesi.

```
 ╔══════════════════════════════════════════════╗
 ║  ███████╗██╗██████╗  █████╗ ██████╗          ║
 ║  ██╔════╝██║██╔══██╗██╔══██╗██╔══██╗         ║
 ║  ███████╗██║██║  ██║███████║██████╔╝         ║
 ║  ╚════██║██║██║  ██║██╔══██║██╔══██╗         ║
 ║  ███████║██║██████╔╝██║  ██║██║  ██║         ║
 ║  ╚══════╝╚═╝╚═════╝ ╚═╝  ╚═╝╚═╝  ╚═╝         ║
 ║  Yazılım Mimarı & Baş Mühendis AI  v3.0.0  ║
 ╚══════════════════════════════════════════════╝
```

---

## Proje Hakkında

**Sidar**, kod yönetimi, sistem izleme, GitHub entegrasyonu, web araştırması ve güvenli dosya işlemleri konularında uzmanlaşmış bir AI asistanıdır. ReAct (Reason + Act) döngüsü ile çalışır; alias araçlar hariç **60+ çekirdek araç** üzerinden LLM destekli kararlar alır.

### Karakter Profili

| Özellik | Değer |
|---------|-------|
| Ad | SİDAR |
| Rol | Yazılım Mimarı & Baş Mühendis |
| Kişilik | Analitik, disiplinli, geek ruhu |
| İletişim | Minimal ve öz; gereksiz söz yok |
| Karar verme | Veri tabanlı, duygusal değil |
| Birincil Model | `qwen2.5-coder:7b` (Ollama, yerel) |
| Yedek Modeller | Google Gemini 2.5 Flash, OpenAI GPT-4o, Anthropic Claude 3.5 Sonnet (bulut) |

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
- **Direct P2P Handoff:** Coder/Reviewer/Researcher ajanları `p2p.v1` sözleşmesiyle sender, receiver, reason ve hop derinliği korunarak doğrudan görev devredebilir.

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

### Web Arayüzü (v3.0.0)
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

## v3.0.0 Öne Çıkan Yetenekler

### ✅ Kurumsal SaaS Altyapısı ve Çoklu Kullanıcı

- **PostgreSQL ve Alembic:** Veritabanı izolasyonu ile çoklu kullanıcı oturum yönetimi (`core/db.py`).
- **Kimlik Doğrulama:** JWT/Bearer Token tabanlı güvenli erişim ve yetkilendirme.
- **Uyum / Denetim:** Tenant RBAC kararları `audit_logs` trail’ine kullanıcı, tenant, kaynak, IP ve allow/deny sonucu ile yazılır.
- **Admin Paneli:** Sistem kullanımını, aktif kullanıcıları ve global kotaları izleyebileceğiniz Web UI yönetim arayüzü.
- **Gözlemlenebilirlik (Observability):** Grafana ve Prometheus üzerinden anlık token tüketimi, USD maliyet ve LLM gecikme (latency) takibi.

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

## Araç Listesi (60+ Çekirdek Araç)

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
| `github_create_pr` | PR oluştur | `{"title":"...","body":"...","head":"..."}` |
| `github_smart_pr` | Diff analizli akıllı PR aç | `[head[\|\|\|base[\|\|\|notes]]]` |
| `github_list_prs` | PR listesini getir | `{"state":"open","limit":10}` |
| `github_get_pr` | PR detayını getir | pr_no |
| `github_pr_diff` | PR diff kodunu getir | `{"number": pr_no}` |
| `github_comment_pr` | PR'a yorum ekle | `pr_no\|\|\|comment` |
| `github_close_pr` | PR kapat | pr_no |
| `github_pr_files` | PR dosya değişikliklerini listele | pr_no |
| `github_list_issues` | Issue listesini getir | `{"state":"open","limit":10}` |
| `github_create_issue` | Yeni issue aç | `{"title":"...","body":"..."}` |
| `github_comment_issue` | Issue'ya yorum ekle | `{"number":no,"body":"..."}` |
| `github_close_issue` | Issue kapat | `{"number": no}` |
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
| `scan_project_todos` | Proje genelinde TODO/FIXME tara | `{"directory":null,"extensions":null}` |
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

### pip ile (Conda dışı)

```bash
# Runtime + opsiyonel gruplar (pyproject.toml extras)
pip install -e .[rag,postgres,telemetry]

# Geliştirme + test bağımlılıkları
pip install -r requirements-dev.txt
```

### Opsiyonel: Masaüstü GUI Launcher

`main.py` mimarisini koruyan, `web_ui/` klasöründen bağımsız bir Eel tabanlı launcher vardır.

```bash
pip install eel
python gui_launcher.py
```

Launcher frontend dosyaları `launcher_gui/` altında bulunur ve seçimleri `gui_launcher.py`
üzerinden mevcut `preflight`, `build_command` ve `execute_command` akışına bağlar.

## Veritabanı Migration (Alembic)

v3.0 üretim hazırlığı kapsamında resmi migration zinciri `migrations/` klasörü altında tutulur.

```bash
pip install -r requirements-dev.txt
alembic upgrade head
```

PostgreSQL gibi farklı hedef veritabanı için bağlantıyı komut anında override edebilirsiniz:

```bash
alembic -x database_url="postgresql+psycopg://user:pass@host:5432/sidar" upgrade head
```

SQLite → PostgreSQL geçiş adımları için: `runbooks/production-cutover-playbook.md`.

Not: `migrations/env.py`, sırasıyla `-x database_url=...` ve `DATABASE_URL` environment variable değerlerini `alembic.ini` içindeki varsayılan URL'nin önüne geçirir.

> **Not:** GPU desteği için `torch` ve `torchvision` kurulumunda CUDA wheel kullanacaksanız kurulumdan önce
> `PIP_EXTRA_INDEX_URL=https://download.pytorch.org/whl/cu124` değişkenini tanımlayın.

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
--provider      AI sağlayıcısı (ollama/gemini/openai/anthropic)
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
│   ├── sidar_agent.py      # Ana ajan bağlayıcısı (583 satır)
│   ├── auto_handle.py      # Örüntü tabanlı hızlı komut eşleyici (612 satır)
│   ├── definitions.py      # Sidar karakter profili ve sistem talimatı (168 satır)
│   ├── tooling.py          # Araç kayıt + Pydantic argüman şema yöneticisi (112 satır)
│   ├── registry.py         # AgentRegistry + @register dekoratörü — plugin marketplace (186 satır)
│   ├── swarm.py            # SwarmOrchestrator: parallel/pipeline, TaskRouter (370 satır)
│   ├── base_agent.py       # BaseAgent soyut sınıfı (55 satır)
│   ├── core/
│   │   ├── supervisor.py   # Yönlendirici ve orkestrasyon ajanı (239 satır)
│   │   ├── contracts.py    # TaskEnvelope/TaskResult + P2P delegasyon sözleşmeleri (63 satır)
│   │   ├── event_stream.py # Ajan olay veriyolu — canlı durum akışı (217 satır)
│   │   ├── memory_hub.py   # Multi-agent bellek yönetim merkezi (54 satır)
│   │   └── registry.py     # Ajan ve yetenek kayıt defteri (29 satır)
│   └── roles/
│       ├── coder_agent.py      # Dosya/kod odaklı uzman ajan (134 satır)
│       ├── researcher_agent.py # Web + RAG odaklı uzman ajan (79 satır)
│       └── reviewer_agent.py   # Test koşturan QA ajanı (183 satır)
├── core/
│   ├── db.py               # Veritabanı bağlantısı, kullanıcı, kota tabloları (1.635 satır)
│   ├── llm_client.py       # Ollama + Gemini + OpenAI + Anthropic async istemcisi (1.351 satır)
│   ├── llm_metrics.py      # Token, maliyet ve Prometheus metrik toplayıcısı (271 satır)
│   ├── memory.py           # Çoklu oturum (session) yönetimi — DB destekli (299 satır)
│   ├── rag.py              # ChromaDB + BM25 hibrit RAG motoru (1.142 satır)
│   ├── dlp.py              # DLP & PII maskeleme: token, key, TC kimlik no, JWT vb. (320 satır)
│   ├── hitl.py             # Human-in-the-Loop onay geçidi: async polling, web API (274 satır)
│   ├── judge.py            # LLM-as-a-Judge: RAG alaka + halüsinasyon riski (257 satır)
│   ├── router.py           # Cost-Aware Model Routing: karmaşıklık skoru + bütçe (211 satır)
│   ├── entity_memory.py    # Entity/Persona Memory: TTL + LRU kişisel bellek (283 satır)
│   ├── cache_metrics.py    # Semantic cache hit/miss + Prometheus metrikleri (50 satır)
│   ├── active_learning.py  # Active Learning + LoRA/QLoRA: FeedbackStore, Exporter (419 satır)
│   └── vision.py           # Multimodal Vision Pipeline: UI mockup → kod (294 satır)
├── managers/
│   ├── code_manager.py     # Dosya operasyonları, AST, Docker REPL sandbox (932 satır)
│   ├── security.py         # OpenClaw 3 seviyeli erişim kontrol sistemi (290 satır)
│   ├── github_manager.py   # GitHub API entegrasyonu — PR + Issue + Release (644 satır)
│   ├── system_health.py    # CPU/RAM/GPU izleme (pynvml + nvidia-smi fallback) (487 satır)
│   ├── web_search.py       # Tavily + Google + DuckDuckGo (async, çoklu motor) (387 satır)
│   ├── package_info.py     # PyPI + npm + GitHub Releases (async) (343 satır)
│   ├── todo_manager.py     # Görev listesi yönetimi + proje TODO taraması (451 satır)
│   ├── slack_manager.py    # Slack Bot SDK + Webhook fallback, Block Kit (205 satır)
│   ├── jira_manager.py     # Jira Cloud REST API v3, Basic/Bearer auth (245 satır)
│   └── teams_manager.py    # Teams MessageCard + Adaptive Card v1.4, HITL (234 satır)
├── plugins/                # Plugin / Marketplace ajanları
│   ├── crypto_price_agent.py  # CryptoPriceAgent: CoinGecko BTC/ETH/SOL fiyat sorgusu (49 satır)
│   └── upload_agent.py        # UploadAgent: temel upload şablon ajanı (10 satır)
├── tests/                  # 142 test modülü — tam kapsam, 0 atlanan test
├── web_ui/                 # Vanilla JS web arayüzü (SSE, session, export, mobil)
│   ├── index.html, app.js, chat.js, sidebar.js, rag.js, style.css
├── web_ui_react/           # React + Vite modern UI (react-router-dom tabanlı)
│   └── src/components/     # ChatPanel, P2PDialoguePanel, SwarmFlowPanel, AgentManagerPanel…
├── migrations/             # Alembic veritabanı geçiş dosyaları
├── scripts/                # Operasyon, metrik ve test betikleri
├── runbooks/               # 4 operasyonel kılavuz (production-cutover, observability, plugin, rbac)
├── helm/sidar/             # Kubernetes Helm chart (16 şablon, staging + prod values)
├── docker/                 # Grafana/Prometheus observability konfigürasyonları
├── docs/module-notes/      # Otomatik üretilen modül notları
├── grafana/                # Grafana dashboard + provisioning (sidar_overview.json)
├── config.py               # Merkezi yapılandırma + GPU tespiti + WSL2 desteği (828 satır)
├── main.py                 # Etkileşimli launcher (wizard + quick start) (381 satır)
├── cli.py                  # Terminal tabanlı CLI giriş noktası (async loop) (289 satır)
├── web_server.py           # FastAPI + WebSocket + Rate limiting + Admin API (2.168 satır)
├── github_upload.py        # GitHub'a otomatik yükleme yardımcı betiği (294 satır)
├── gui_launcher.py         # Eel tabanlı masaüstü başlatıcı (97 satır)
├── Dockerfile              # CPU/GPU dual-mode build (python:3.11-slim)
├── docker-compose.yml      # 7 servis: redis, ai, gpu, web, web-gpu, prometheus, grafana
├── environment.yml         # Conda — PyTorch CUDA 12.4 (cu124) wheel, pytest-asyncio
├── .env.example            # Açıklamalı ortam değişkeni şablonu (70+ değişken)
└── install_sidar.sh        # Ubuntu/WSL sıfırdan kurulum scripti
```

---

## Testleri Çalıştır

```bash
cd sidar_project
pytest tests/ -v
pytest tests/ -v --cov=. --cov-report=term-missing
```

**Test paketi (142 modül):**
- `test_sidar.py` — Temel SidarAgent, CodeManager, SecurityManager, RAG, GPU testleri
- `test_web_server_runtime.py` — FastAPI endpoint ve WebSocket senaryoları
- `test_db_runtime.py` / `test_db_postgresql_branches.py` — SQLite/PostgreSQL yönetimi
- `test_supervisor_agent.py` / `test_reviewer_agent.py` — Multi-agent orkestrasyon
- `test_sandbox_runtime_profiles.py` — Docker sandbox güvenlik profilleri
- `test_llm_metrics_runtime.py` / `test_grafana_dashboard_provisioning.py` — Telemetri
- `test_plugin_marketplace_flow.py` — `CryptoPriceAgent` + `AgentRegistry` akışı
- `test_tenant_rbac_scenarios.py` — Çok kullanıcı izin matrisi doğrulaması
- `test_observability_stack_compose.py` — Jaeger/Prometheus/Grafana sağlık kontrolü
- `test_swarm_execute_api.py` — `/api/swarm/execute` endpoint testleri
- `test_dlp_masking.py` — DLP & PII maskeleme senaryoları
- `test_hitl_approval.py` — Human-in-the-Loop onay geçidi akışları
- `test_llm_judge.py` — LLM-as-a-Judge alaka + halüsinasyon ölçümü
- `test_env_parity.py` — config.py ↔ .env.example parite doğrulaması
- `test_cost_aware_routing.py` — Cost-Aware Model Routing ve bütçe mantığı
- `test_entity_persona_memory.py` — Entity/Persona Memory TTL + LRU testleri
- `test_semantic_cache_metrics.py` — Cache hit/miss sayaçları + Prometheus metrikleri
- `test_active_learning.py` — FeedbackStore, DatasetExporter, LoRATrainer testleri
- `test_vision.py` — Vision Pipeline provider formatları + mockup→kod
- `test_slack_jira_teams.py` — Slack/Jira/Teams entegrasyon testleri
- Ve daha 122 modül — edge-case, retry/fallback, migration, webhook, auth…

---

## Yapılandırma (.env)

```env
# AI Sağlayıcı
AI_PROVIDER=ollama              # ollama | gemini | openai | anthropic
CODING_MODEL=qwen2.5-coder:7b
OLLAMA_URL=http://localhost:11434/api
TEXT_MODEL=gemma2:9b
GEMINI_API_KEY=                 # Gemini kullanılacaksa
OPENAI_API_KEY=                 # OpenAI kullanılacaksa
ANTHROPIC_API_KEY=              # Anthropic Claude kullanılacaksa

# Veritabanı (v3.0.0+)
DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/sidar # Boş bırakılırsa SQLite kullanılır

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
| **v3.0.31** | Kurumsal rollout senkronizasyonu: `audit_logs` migration + DB audit trail yardımcıları + `access_policy_middleware` audit kaydı akışı raporlandı; direct `p2p.v1` handoff protokolü Supervisor ve Swarm katmanlarında belgelendi |
| **v3.0.24** | Faz 4 tamamlama: Slack Bot SDK + Webhook (`slack_manager`), Jira Cloud REST API v3 (`jira_manager`), Teams Adaptive Card v1.4 + HITL onay kartı (`teams_manager`); 44 yeni test; 142 test modülü, ~18.200+ Python kaynak satırı |
| **v3.0.23** | Faz 4: Active Learning + LoRA/QLoRA (`core/active_learning.py`), Multimodal Vision Pipeline (`core/vision.py`); 66 yeni test |
| **v3.0.22** | Faz 5 devam: Cost-Aware Model Routing (`core/router.py`), Entity/Persona Memory (`core/entity_memory.py`), Semantic Cache Grafana Hit Rate (`core/cache_metrics.py` + Grafana dashboard); 62 yeni test |
| **v3.0.21** | Faz 5 başlangıç: DLP & PII Maskeleme (`core/dlp.py`), Human-in-the-Loop (`core/hitl.py`), LLM-as-a-Judge (`core/judge.py`), .env.example↔config.py parite sertleştirmesi; 60 yeni test |
| **v3.0.20** | Kapsamlı rapor güncelleme turu: AUDIT_REPORT_v4.0.2, PROJE_RAPORU.md, README.md tüm satır sayıları ve araç envanteri mevcut koda göre yeniden ölçüldü ve güncellendi |
| **v3.0.19** | React SPA react-router-dom navigasyonu, PromptAdminPanel/SwarmFlowPanel/P2PDialoguePanel bileşenleri, `/api/swarm/execute` endpoint, DB destekli sistem promptu yükleme |
| **v3.0.18** | FAZ-6: D-6 `core/db.py` lazy lock dead-code kapatıldı. Tüm 18 güvenlik bulgusu (K/Y/O/D) kapatıldı. Güvenlik puanı 10.0/10 |
| **v3.0.17** | FAZ-5: O-1..O-6 tüm orta öncelikli bulgular kapatıldı (BASE_DIR kısıtlama, DOCKER_REQUIRED, shell blocklist) |
| **v3.0.16** | FAZ-4: Y-1..Y-5 tüm yüksek öncelikli bulgular doğrulandı/kapatıldı |
| **v3.0.15** | FAZ-3: D-1..D-5 teknik borç temizliği, metric auth, bleach sanitizasyon, CI pg-stress job |
| **v3.0.14** | Kapsamlı yeniden ölçüm; `agent/registry.py`, `agent/swarm.py`, `plugins/` eklendi; 132 test modülü, 30.613 test satırı |
| **v3.0.13** | Plugin marketplace, runbook turu, observability simülasyonu, tenant RBAC senaryoları |
| **v3.0.12** | AgentRegistry + SwarmOrchestrator, React/Vite frontend scaffold, dependency extras grupları |
| **v3.0.0** | Kurumsal/SaaS sürümü: Multi-Agent mimari, Bearer Auth + Admin Panel, Alembic/PostgreSQL cutover, Grafana/Prometheus observability, gVisor/Kata runtime hazırlıkları |
| **v2.7.0** | Launcher/CLI ayrımı, canlı aktivite paneli, hibrit RAG belge yönetimi |
| **v2.6.0** | GPU hızlandırma, Docker REPL sandbox, çoklu oturum, Recursive Chunking, Pydantic v2 |

---

## Lisans

Bu proje LotusAI ekosisteminin bir parçasıdır.

## 🧹 Depo Hijyeni

- Kök dizindeki geçici Ar-Ge not dosyası (`.note`) kaldırıldı; kalıcı mimari kararları için `PROJE_RAPORU.md` ve `RFC-MultiAgent.md` kullanılmalıdır.
- CI pipeline artık boş test artifact dosyalarını otomatik tespit eder (`find tests -type f -size 0`).
- Proje satır/dosya metrikleri tek komutla `scripts/audit_metrics.sh` üzerinden (JSON/Markdown) standart olarak üretilir.