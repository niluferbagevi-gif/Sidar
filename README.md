# SİDAR — Yazılım Mühendisi AI Asistanı

> **v5.2.0 ürün baseline** — React SPA + Multi-Agent Swarm + PostgreSQL/pgvector kurumsal mimarisi üzerine kurulu, proaktif AI Co-Worker seviyesine yaklaşan Türkçe dilli, tam async yazılım mühendisi AI projesi.

```
 ╔══════════════════════════════════════════════╗
 ║  ███████╗██╗██████╗  █████╗ ██████╗          ║
 ║  ██╔════╝██║██╔══██╗██╔══██╗██╔══██╗         ║
 ║  ███████╗██║██║  ██║███████║██████╔╝         ║
 ║  ╚════██║██║██║  ██║██╔══██║██╔══██╗         ║
 ║  ███████║██║██████╔╝██║  ██║██║  ██║         ║
 ║  ╚══════╝╚═╝╚═════╝ ╚═╝  ╚═╝╚═╝  ╚═╝         ║
 ║ Yazılım Mimarı & Baş Mühendis AI v5.2.0 ║
 ╚══════════════════════════════════════════════╝
```

---

## Proje Hakkında

**Sidar**, kod yönetimi, sistem izleme, GitHub entegrasyonu, web araştırması, gerçek zamanlı sesli etkileşim, dinamik tarayıcı otomasyonu ve güvenli dosya işlemleri konularında uzmanlaşmış bir AI asistanıdır. ReAct (Reason + Act) döngüsü ile çalışır; alias araçlar hariç **60+ çekirdek araç** üzerinden LLM destekli kararlar alır ve v5.2.0 geçişiyle proaktif bir **AI Co-Worker** davranış modeline yaklaşmıştır.

> **Güncel Ürün Durumu:** Repo artık `v5.2.0` ürün baseline'ında çalışmaktadır ve Faz A + Faz B teslimleri ürünleşmiş durumdadır. React tabanlı `web_ui_react/` deneyimi varsayılan arayüz, legacy `web_ui/` geriye dönük fallback, PostgreSQL + `pgvector` + Alembic veri katmanı ise standart kurumsal omurga olmaya devam eder. Bunun üzerine **WebSocket tabanlı gerçek zamanlı sesli asistan**, **Playwright öncelikli dinamik tarayıcı otomasyonu**, **LSP destekli anlamsal kod denetimi**, multimodal medya hattı ve proaktif webhook/cron tetikleyicileri repo içinde ürünleşmiş Faz A kazanımları olarak çalışmaktadır. Faz A ve Faz B teslimleri tamamlanmıştır: GraphRAG'in Reviewer akışına bağlanması, tam duplex voice-to-voice iletişim, dış olay korelasyonu ve Swarm karar akışının canlı operasyon yüzeyine dönüşmesi repo içinde aktif hale gelmiştir. Resmî sonraki odak artık **Faz C**: proaktif remediation/self-healing, daha derin browser decisioning ve istemci tarafı ses deneyiminin daha da deterministik hale getirilmesidir.

> **v5.0 Vizyonu:** AI Co-Worker seviyesindeki ileri otonomi hedefleri, video/ses işleme, browser automation, GraphRAG, proaktif webhook ajanları ve görsel swarm karar grafiği önerileriyle [`docs/SIDAR_v5_0_MIMARI_RAPORU.md`](docs/SIDAR_v5_0_MIMARI_RAPORU.md) içinde ayrıntılandırılmıştır.

### v5.0 Co-Worker Öne Çıkan Özellikler

- **Gerçek zamanlı multimodal ses:** `/ws/voice` hattı duplex STT/TTS, VAD ve barge-in davranışıyla SİDAR'ı canlı sesli çalışma arkadaşına dönüştürür.
- **LSP destekli otonom kalite kapısı:** Reviewer ajanı GraphRAG + Pyright + TypeScript LSP sinyallerini birleştirerek daha güvenilir inceleme ve remediation önerileri üretir.
- **Kendi kendini uyandıran otonomi:** cron/webhook/federation tetikleri ve action feedback akışları sayesinde dış olaylar swarm görevlerine dönüştürülebilir.
- **Canlı operasyon yüzeyi:** `SwarmFlowPanel`, artık sadece karar grafiği değil; seçili node üzerinden görev türetme, hedefli rerun ve bekleyen HITL onaylarını yönetme yüzeyidir.

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
- **Maliyet Farkındalığı (Cost-Aware Routing):** `core/router.py`, promptu zero-latency heuristic tarama ile karmaşıklık skoruna ayırır; günlük USD bütçe limiti dolduğunda veya görev basit kaldığında lokal sağlayıcıya, aksi durumda bulut modele yönlendirme yapar.
- **Otonom Cron Tetikleyiciler:** `web_server.py` içindeki `_autonomous_cron_loop`, sistemin belirli aralıklarla kendi kendini uyandırıp bekleyen iş/sinyal fırsatlarını taramasını sağlar.

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
- **Tavily → Google Custom Search → DuckDuckGo** sıralı otomatik fallback; üst katman 401/403 veya timeout üretirse oturum bazında güvenli şekilde sıradaki sağlayıcıya düşer
- URL içerik çekme — HTML temizleme dahil (`fetch_url`)
- Kütüphane dokümantasyon araması (`search_docs`)
- Stack Overflow araması (`search_stackoverflow`)

### LSP Destekli Anlamsal Analiz (Kalıcı Yetenek)
- `managers/code_manager.py` içinde Pyright ve TypeScript Language Server Protocol entegrasyonu
- Reviewer ajanı için `lsp_diagnostics` tabanlı anlamsal kalite kapısı ve regresyon sinyali
- Sözdizimi denetiminin ötesine geçerek symbol/reference düzeyinde daha güvenilir kod inceleme akışı

### WebSocket Tabanlı Gerçek Zamanlı Sesli Asistan (Kalıcı Yetenek)
- `core/multimodal.py` ile video frame çıkarma, ses ayıklama ve Whisper tabanlı STT hattı
- `/ws/voice` WebSocket rotası ile gerçek zamanlı ses chunk kabulü, VAD olayları ve transcript→ajan yanıtı akışı
- `core/voice.py` üzerinden ses segmentasyonu, duplex output buffer durumu, interrupt/barge-in temizliği ve TTS adaptörleri
- FFmpeg sistem bağımlılığı ile medya dönüştürme; büyük dosyalar için byte limitleri ile korunur

### Playwright Dinamik Tarayıcı Otomasyonu (Kalıcı Yetenek)
- `managers/browser_manager.py` üzerinden Playwright öncelikli, Selenium fallback sağlayıcı soyutlaması
- Headless/headful çalışma, timeout ve allowlist domain sınırlarıyla kontrollü web etkileşimi
- Yüksek riskli aksiyonlar için audit trail + HITL korumaları uygulanmıştır; browser signal özetleri reviewer ve swarm akışlarına taşınabilir

### Paket Bilgi Sistemi (PackageInfoManager)
- PyPI paket bilgisi ve sürüm karşılaştırma (`pypi`, `pypi_compare`)
- npm paket bilgisi (`npm`)
- GitHub Releases listesi ve en güncel sürüm (`gh_releases`, `gh_latest`)

### Hibrit RAG Belge Deposu (DocumentStore)
- ChromaDB vektör araması (semantik) + GPU embedding desteği
- BM25 anahtar kelime araması
- **GraphRAG (beta)**: kod tabanı modül bağımlılıklarını grafik olarak tarayıp ilgili dosyaları ve bağımlılık yollarını açıklayabilir
- **Recursive Character Chunking** (`\nclass ` → `\ndef ` → `\n\n` → `\n` → ` ` öncelik sırası)
- URL'den async belge ekleme (`httpx.AsyncClient`)
- `RAG_CHUNK_SIZE`, `RAG_CHUNK_OVERLAP`, `RAG_TOP_K` env değişkenleri ile yapılandırılabilir

### Sistem Sağlığı (SystemHealthManager)
- CPU ve RAM kullanım izleme (psutil)
- GPU/CUDA bilgisi ve VRAM takibi (pynvml)
- GPU bellek optimizasyonu (VRAM boşaltma + Python GC)

### Web Arayüzü (v5.2.0 ürün baseline)
- **Görsel Swarm Akış Diyagramları + Canlı Operasyon:** `SwarmFlowPanel`, ajan görevleri, P2P handoff'lar, otonom cron tetikleri ve LLM düşünce/karar özetlerini node-graph olarak görselleştirir; seçili node üzerinden follow-up görev, rerun ve HITL karar aksiyonları sunar
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

### 🚀 Son Sürüm Öne Çıkan Özellikler (v3.2.0 / v4.2.0 dokümantasyon turu)

- **Autonomous LLMOps / LLM-as-a-Judge:** `core/judge.py` zayıf yanıtları arka planda puanlayıp uygun durumlarda `core/active_learning.py` hattına aktarır; böylece insan müdahalesi olmadan kalite geri besleme döngüsü kurulabilir.
- **P2P Swarm İletişimi:** Coder/Reviewer/Researcher ajanları `p2p.v1` sözleşmesiyle sender, receiver, reason ve handoff depth bağlamını koruyarak doğrudan görev devredebilir.
- **Kurumsal Audit Trail:** `audit_logs` tablosu ve `access_policy_middleware` entegrasyonu sayesinde tenant bazlı allow/deny kararları asenkron biçimde kalıcı denetim izine yazılır.
- **Derin Observability:** Semantic cache hit/miss/skip/eviction ve Redis latency metrikleri Prometheus/Grafana hattında görünür; maliyet, gecikme ve cache davranışı aynı operasyon yüzeyinde izlenir.

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

### Sistem Gereksinimleri

- Python 3.11 veya 3.12 (`>=3.11, <3.13`)
- Not: Python 3.13 ile bağımlılık çözümü başarısız olabilir (ör. SQLAlchemy kurulamadığı için `ModuleNotFoundError`).
- `ffmpeg` (multimodal video/ses ayrıştırma için zorunlu sistem bağımlılığı)
- `psutil` (sistem sağlık ölçümleri ve child-process cleanup akışları için Python bağımlılığı; `pyproject.toml` içinde tanımlı)
- İsteğe bağlı: Docker, Ollama, PostgreSQL/pgvector, Playwright tarayıcıları

### Önerilen: `.venv` + `uv` ile kurulum

```bash
cd Sidar
python -m venv .venv
source .venv/bin/activate
uv sync --all-extras
```

> Not: Bu akışta bağımlılıklar `pyproject.toml` üzerinden editable kurulum ile yüklenir.
> Kilitli ve platformlar arası deterministik çözüm için kaynak dosya `uv.lock` kabul edilir.

### Alternatif: Aktive etmeden `uv` ile çalıştırma

```bash
cd Sidar
python -m venv .venv
uv sync --all-extras
uv run python main.py
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
uv sync --all-extras
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
OLLAMA_NUM_PARALLEL=4 ollama serve
```

> Güvenlik notu: `install_sidar.sh` varsayılan olarak uzaktan kurulum scripti çalıştırmaz.
> Otomatik kurulum gerekiyorsa bilinçli opt-in ile çalıştırın: `ALLOW_OLLAMA_INSTALL_SCRIPT=1 ./install_sidar.sh`.

### Docker ile

> **GPU benchmark notu:** `test_gpu_concurrent_throughput` ve `test_gpu_vram_peak_under_load` testlerinin skip olmaması için Ollama servisini `OLLAMA_NUM_PARALLEL>=GPU_BENCH_CONCURRENCY` ile başlatın (varsayılan benchmark concurrency: 4).

> **GPU Driver Uyarısı:** `sidar-gpu`/`sidar-web-gpu` servisleri `nvidia/cuda:13.0.0-runtime-ubuntu22.04` tabanı kullanır.
> Host makinede en az **NVIDIA Driver v535+ (CUDA 12.2+)** önerilir; CUDA 13.x imajları için pratikte **v550+** sürücü serisi gerekir.
> Sürücü daha eskiyse konteyner GPU ile ayağa kalkmayabilir.

```bash
# CPU modu
docker compose up --build sidar-web

# GPU modu (NVIDIA)
OLLAMA_NUM_PARALLEL=4 docker compose up --build sidar-web-gpu
```

Production ortamında host izin (uid/gid/chown) sorunlarını azaltmak için bind mount yerine named volume kullanabilirsiniz:

```bash
export SIDAR_DATA_MOUNT=sidar_data_prod
export SIDAR_LOGS_MOUNT=sidar_logs_prod
export SIDAR_TEMP_MOUNT=sidar_temp_prod
docker compose up -d sidar-web
```

### Otomatik Kurulum Betiği (Ubuntu/WSL)

```bash
./install_sidar.sh

# Bulut/CI ortamı (ChatGPT Codex Cloud, Gitpod, Codespaces vb.) için
# etkileşim istemeden test-ready kurulum:
bash install_sidar.sh --ci

# İsteğe bağlı (riskli adımları bilinçli olarak açmak için):
ALLOW_APT_UPGRADE=1 ALLOW_OLLAMA_INSTALL_SCRIPT=1 ./install_sidar.sh
```

> Kurulum sırasında bir hata alırsanız betik loglarını `logs/install_YYYYMMDD_HHMMSS.log` altında inceleyin.
> En güncel log: `ls -1t logs/install_*.log | head -n 1`

---

## Kullanım

### 🚀 Ultimate Launcher ile Başlatma (Önerilen)

```bash
python main.py
```

`main.py`; preflight kontrollerini çalıştırır, etkileşimli TUI menüsünü açar, uygun çalışma modunu seçtirir ve `config.py` yüklenemezse child process'leri fail-fast biçimde durdurur. Varsayılan kullanıcı akışı artık burasıdır.

**TUI üzerinden yapabilecekleriniz:**
- Web arayüzünü veya CLI oturumunu menüden seçmek
- Önkoşul/hata durumlarını launch öncesi görmek
- Alt süreç loglarını tek yerden takip etmek
- Hızlı başlatma (quick start) ile standart web oturumuna geçmek

### 🌐 Web Arayüzü (Doğrudan)

```bash
python web_server.py
```

Tarayıcıda açılır: **http://localhost:7860**

```bash
# Varsayılan kurumsal port ile dışarı aç
python web_server.py --host 0.0.0.0 --port 7860

# Erişim seviyesi ile
python web_server.py --level sandbox

# Gemini sağlayıcısı ile
python web_server.py --provider gemini --port 7860
```

> `web_server.py`, `web_ui_react/dist/` mevcutsa React SPA'yı öncelikli sunar; build yoksa geriye dönük uyumluluk için legacy `web_ui/` arayüzüne düşer.

### ⚛️ React/Vite Geliştirme Arayüzü

```bash
cd web_ui_react
npm install
npm run dev
```

Geliştirme sunucusu varsayılan olarak **http://localhost:5173** adresinde açılır. Production için:

```bash
npm run build
```

Build çıktısı `web_ui_react/dist/` altına yazılır ve `web_server.py` tarafından otomatik servis edilir.

Web arayüzü özellikleri:
- React SPA rotaları: sohbet, P2P diyalog, swarm akışı, prompt admin, agent manager, tenant admin
- Streaming chat (daktilo efekti) + araç görselleştirmesi
- Çoklu oturum yönetimi, markdown/kod blokları ve Bearer token toolbar
- Legacy `web_ui/` için geriye dönük fallback desteği

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
Sidar/
├── agent/                  # Supervisor + swarm + uzman roller (coder/researcher/reviewer)
├── core/                   # LLM istemcisi, DB, RAG, DLP, HITL, Judge, Vision, metrics
├── managers/               # Kod, güvenlik, GitHub, sistem sağlığı, paket ve web arama yöneticileri
├── plugins/                # Marketplace ajan örnekleri
├── tests/                  # 149 test modülü / 151 Python test dosyası
├── web_ui/                 # Legacy vanilla JS arayüzü (fallback)
├── web_ui_react/           # React + Vite SPA (Chat, P2P, Swarm, Prompt/Agent/Tenant admin)
├── migrations/             # Alembic zinciri: 0001_baseline_schema, 0002_prompt_registry, 0003_audit_trail
├── scripts/                # Audit, env parity, SQLite→PostgreSQL migration, DB load test betikleri
├── runbooks/               # Production cutover, observability, plugin marketplace, tenant RBAC kılavuzları
├── helm/sidar/             # Kubernetes chart; web, ai-worker, redis, PostgreSQL, otel-collector, Jaeger, Zipkin
├── docker/                 # Prometheus + Grafana provisioning dosyaları
├── grafana/                # Semantic cache / LLM overview dashboard varlıkları
├── config.py               # Merkezi yapılandırma; runtime sürümü `v5.2.0`
├── web_server.py           # 62 REST endpoint + `/ws/chat` + `/ws/voice`
├── docker-compose.yml      # redis, postgres, sidar-web, sidar-web-gpu, sidar-ai, sidar-gpu, jaeger, prometheus, grafana
├── README.md               # Ürün ve kurulum rehberi
├── PROJE_RAPORU.md         # Mimari + kalite raporu
├── AUDIT_REPORT_v5.0.md    # Güvenlik, coverage ve denetim raporu
└── TEKNIK_REFERANS.md      # Operasyonel/uygulama seviyesi sözleşmeler
```

---

## Testleri Çalıştır

> Kritik not: Sadece `dev` extra ile kurulum yapmak (`uv sync --extra dev` veya `uv pip install -e ".[dev]"),
> opsiyonel entegrasyonları (ör. `postgres`, `telemetry`, `slack`, `jira`, `aws`, `browser`) **kurmaz**.
> CI/CD ve ekip paritesi için geliştirme ortamında standart kurulum komutu `uv sync --all-extras` olmalıdır.

```bash
cd Sidar
uv sync --all-extras
python -m pytest -c pyproject.toml tests/ -v
python -m pytest -c pyproject.toml tests/ -v --cov=. --cov-report=term-missing
bash run_tests.sh
uv run --with mutmut mutmut run --max-children 2
cd web_ui_react && npm run test:critical
bash scripts/ci/flaky_scan.sh
uv run pytest -q tests/performance/test_benchmark.py -k "password_hash_cpu_cost or password_verify_cpu_cost" --benchmark-json=artifacts/auth-benchmark/benchmark.json
```

> Not: `source .venv/bin/activate` zorunlu değildir. Sanal ortam yoksa veya farklı bir araç
> kullanıyorsanız komutları doğrudan `python -m pytest ...` ile çalıştırın.
>
> Mutation/edge-case kalite kapısı için GitHub Actions üzerinde haftalık
> `Weekly Mutation & Critical Assertion Gates` iş akışı tanımlıdır.
> Deterministiklik/flakiness taraması için ise gece çalışan `Nightly Flaky Scan`
> iş akışı aynı kritik test setini 5 tekrar (`pytest -n auto -q --maxfail=1`) koşturup
> `artifacts/flaky/report.md` raporu üretir.
> Kimlik doğrulama benchmark varyansı için `Nightly Auth Benchmark` iş akışı parola
> hash/verify testlerini izole CPU pinleme ile çalıştırır; P95/P99 eşiklerini
> (`AUTH_BENCH_P95_BUDGET_MS`, `AUTH_BENCH_P99_BUDGET_MS`) aşarsa alarm/fail üretir.
> SQLite/PostgreSQL karşılaştırmalı workload trendi için release tetiklemeli
> `Release DB Benchmark Trend` iş akışı benchmark JSON + `trend.md` artifact üretir.
> Bu job benchmark profilinde DB havuz boyutunu `SIDAR_BENCHMARK_DB_POOL_SIZE=5`
> ile sabitler.
> Yerel çalışmada `run_tests.sh` varsayılanı `RUN_BENCHMARKS=required` olarak ayarlanmıştır;
> benchmark fazı quality gate olarak zorunlu çalışır. Gecikme hassas akışlar için
> periyodik olarak `bash run_tests.sh` veya
> `uv run pytest -q tests/performance/ --benchmark-json=artifacts/benchmark/benchmark.json`
> komutlarından biriyle regresyon takibi yapın.
> GPU benchmarkları için `Nightly GPU Performance` hattında TTFT/TPS/VRAM metrikleri
> geçmiş 7 koşu medyanına göre (`GPU_TREND_WINDOW=7`) varsayılan ±%20 trend eşiği
> (`GPU_TREND_THRESHOLD_PERCENT`) ile korunur; quantization + architecture + driver
> profiline göre ayrı baseline/history tutulur.

**Test paketi (149 modül / 151 dosya):**
- `test_sidar.py` — Temel SidarAgent, CodeManager, SecurityManager, RAG, GPU testleri
- `test_web_server_runtime.py` — FastAPI endpoint ve WebSocket senaryoları
- `test_web_server_api_focus_additions.py` — WebSocket auth kapanışları, HITL broadcast temizliği ve Slack/Jira/Teams + EntityMemory/Feedback API fallback senaryoları
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
CODING_MODEL=qwen2.5-coder:3b
OLLAMA_URL=http://localhost:11434/api
OLLAMA_NUM_PARALLEL=4         # GPU benchmark concurrency için >=4 önerilir
TEXT_MODEL=llama3.1:8b
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

# GPU (önerilen)
USE_GPU=true                    # true: GPU embedding aktif
REQUIRE_GPU=true                # true: GPU yoksa uygulama başlangıçta durdurulur
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
| **v5.2.0** | Faz 6 görünür ürün geçişi: multimodal medya hattı, `/ws/voice`, tarayıcı otomasyonu, proaktif cron/webhook akışları, GraphRAG etki analizi ve launcher stabilizasyonu testlerle doğrulandı; aktif v5.2.0 coverage borcu kapatıldı |
| **v4.3.0** | Sürüm + metrik senkronizasyonu: `config.py`, `pyproject.toml`, `PKG-INFO`, Helm chart ve üst seviye dokümanlar 4.3.0 çizgisine taşındı; takipli dosya ölçümleri 58 üretim Python / 20.582 satır, 151 test dosyası / 39.147 satır ve 62 REST endpoint gerçekliğiyle güncellendi. Aynı baz çizgide v5.0 geçişi için multimodal, browser automation ve proaktif trigger iskeletleri devreye alındı |
| **v4.2.0** | Autonomous LLMOps operasyonel kapanışı: Faz 4 teslimatları audit trail + direct `p2p.v1` handoff doğrulamalarıyla kurumsal rollout seviyesinde kapatıldı; `PROJE_RAPORU.md`, `RFC-MultiAgent.md` ve `AUDIT_REPORT_v5.0.md` senkronize edildi |
| **v3.2.0** | Autonomous LLMOps konsolidasyonu: Active Learning/LoRA, Vision Pipeline, Cost-Aware Routing ve Slack/Jira/Teams orkestrasyonu Faz 4’ün birleşik ürün anlatısı olarak toplandı |
| **v3.0.31** | Kurumsal rollout senkronizasyonu: `audit_logs` migration + DB audit trail yardımcıları + `access_policy_middleware` audit kaydı akışı raporlandı; direct `p2p.v1` handoff protokolü Supervisor ve Swarm katmanlarında belgelendi |
| **v3.0.24** | Faz 4 tamamlama: Slack Bot SDK + Webhook (`slack_manager`), Jira Cloud REST API v3 (`jira_manager`), Teams Adaptive Card v1.4 + HITL onay kartı (`teams_manager`); 44 yeni test; 142 test modülü, ~18.200+ Python kaynak satırı |
| **v3.0.23** | Faz 4: Active Learning + LoRA/QLoRA (`core/active_learning.py`), Multimodal Vision Pipeline (`core/vision.py`); 66 yeni test |
| **v3.0.22** | Faz 5 devam: Cost-Aware Model Routing (`core/router.py`), Entity/Persona Memory (`core/entity_memory.py`), Semantic Cache Grafana Hit Rate (`core/cache_metrics.py` + Grafana dashboard); 62 yeni test |
| **v3.0.21** | Faz 5 başlangıç: DLP & PII Maskeleme (`core/dlp.py`), Human-in-the-Loop (`core/hitl.py`), LLM-as-a-Judge (`core/judge.py`), .env.example↔config.py parite sertleştirmesi; 60 yeni test |
| **v3.0.20** | Kapsamlı rapor güncelleme turu: AUDIT_REPORT_v5.0, PROJE_RAPORU.md, README.md tüm satır sayıları ve araç envanteri mevcut koda göre yeniden ölçüldü ve güncellendi |
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

Bu proje Sidar ekosisteminin bir parçasıdır.

## 🧹 Depo Hijyeni

- Kök dizindeki geçici Ar-Ge not dosyası (`.note`) kaldırıldı; kalıcı mimari kararları için `PROJE_RAPORU.md` ve `RFC-MultiAgent.md` kullanılmalıdır.
- CI pipeline artık boş test artifact dosyalarını otomatik tespit eder (`find tests -type f -size 0`).
- Proje satır/dosya metrikleri tek komutla `scripts/audit_metrics.sh` üzerinden (JSON/Markdown) standart olarak üretilir.
