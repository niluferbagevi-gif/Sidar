# SİDAR Projesi — Kapsamlı Kod Analiz Raporu (Güncel)

> **Rapor Tarihi:** 2026-03-07
> **Son Güncelleme:** 2026-03-08 (v2.9.0 audit — RRF, RAG İzolasyonu, Sliding Window; web_server RAG session_id bug düzeltmesi; branch: claude/review-files-report-5uVFR)
> **Proje Sürümü:** 2.9.0
> **Analiz Kapsamı:** Tüm kaynak dosyaları satır satır incelenmiştir.

---

<a id="içindekiler"></a>
## İçindekiler
- [1. Proje Genel Bakışı](#1-proje-genel-bakışı)
  - [Temel Özellikler](#temel-özellikler)
- [2. Proje Dosya Yapısı](#2-proje-dosya-yapısı)
- [3. Modül Bazında Detaylı Analiz](#3-modül-bazında-detaylı-analiz)
  - [3.1 `config.py` — Merkezi Yapılandırma](#31-configpy--merkezi-yapılandırma-517-satır)
  - [3.2 `main.py` — Akıllı Başlatıcı](#32-mainpy--akıllı-başlatıcı-331-satır)
  - [3.3 `cli.py` — CLI Arayüzü](#33-clipy--cli-arayüzü-274-satır)
  - [3.4 `web_server.py` — FastAPI Web Sunucusu](#34-web_serverpy--fastapi-web-sunucusu-794-satır)
  - [3.5 `agent/sidar_agent.py` — Ana Ajan](#35-agentsidar_agentpy--ana-ajan-1455-satır)
  - [3.6 `agent/auto_handle.py` — Hızlı Yönlendirici](#36-agentauto_handlepy--hızlı-yönlendirici-601-satır)
  - [3.7 `agent/definitions.py` — Ajan Tanımları](#37-agentdefinitionspy--ajan-tanımları-165-satır)
  - [3.7b `agent/tooling.py` — Araç Kayıt ve Şema Yöneticisi](#37b-agenttoolingpy--araç-kayıt-ve-şema-yöneticisi-189-satır)
  - [3.8 `core/llm_client.py` — LLM İstemcisi](#38-corellm_clientpy--llm-istemcisi-513-satır)
  - [3.9 `core/memory.py` — Konuşma Belleği](#39-corememorypy--konuşma-belleği-384-satır)
  - [3.10 `core/rag.py` — RAG Motoru](#310-coreragpy--rag-motoru-851-satır)
  - [3.11 `managers/security.py` — Güvenlik Yöneticisi](#311-managerssecuritypy--güvenlik-yöneticisi-280-satır)
  - [3.12 `managers/code_manager.py` — Kod Yöneticisi](#312-managerscode_managerpy--kod-yöneticisi-746-satır)
  - [3.13 `managers/github_manager.py` — GitHub Yöneticisi](#313-managersgithub_managerpy--github-yöneticisi-560-satır)
  - [3.14 `managers/system_health.py` — Sistem Sağlık Yöneticisi](#314-managerssystem_healthpy--sistem-sağlık-yöneticisi-420-satır)
  - [3.15 `managers/web_search.py` — Web Arama Yöneticisi](#315-managersweb_searchpy--web-arama-yöneticisi-352-satır)
  - [3.16 `managers/package_info.py` — Paket Bilgi Yöneticisi](#316-managerspackage_infopy--paket-bilgi-yöneticisi-314-satır)
  - [3.17 `managers/todo_manager.py` — Görev Takip Yöneticisi](#317-managerstodo_managerpy--görev-takip-yöneticisi-380-satır)
  - [3.18 `web_ui/index.html` — Web Arayüzü](#318-web_uiindexhtml--web-arayüzü-3399-satır)
  - [3.19 `github_upload.py` — GitHub Yükleme Aracı](#319-github_uploadpy--github-yükleme-aracı-294-satır)
  - [3.20 Altyapı Dosyaları](#320-altyapı-dosyaları)
- [4. Mimari Değerlendirme](#4-mimari-değerlendirme)
  - [4.1 Güçlü Yönler](#41-güçlü-yönler)
  - [4.2 Kısıtlamalar](#42-kısıtlamalar)
- [5. Güvenlik Analizi](#5-güvenlik-analizi)
  - [5.1 Güvenlik Kontrolleri Özeti](#51-güvenlik-kontrolleri-özeti)
  - [5.2 Güvenlik Seviyeleri Davranışı](#52-güvenlik-seviyeleri-davranışı)
- [6. Test Kapsamı](#6-test-kapsamı)
- [7. Temel Bağımlılıklar](#7-temel-bağımlılıklar)
- [8. Kod Satır Sayısı Özeti](#8-kod-satır-sayısı-özeti)
- [9. Modül Bağımlılık Haritası](#9-modül-bağımlılık-haritası)
- [10. Veri Akış Diyagramı](#10-veri-akış-diyagramı)
  - [10.1 Bir Chat Mesajının Ömrü](#101-bir-chat-mesajının-ömrü)
  - [10.2 Bellek Yazma Yolu](#102-bellek-yazma-yolu)
  - [10.3 RAG Belge Ekleme Yolu](#103-rag-belge-ekleme-yolu)
- [11. Mevcut Sorunlar ve Teknik Borç](#11-mevcut-sorunlar-ve-teknik-borç)
- [12. `.env` Tam Değişken Referansı](#12-env-tam-değişken-referansı)
  - [12.1 AI Sağlayıcı](#121-ai-sağlayıcı)
  - [12.2 Güvenlik ve Erişim](#122-güvenlik-ve-erişim)
  - [12.3 GPU / Donanım](#123-gpu--donanım)
  - [12.4 Web Arayüzü](#124-web-arayüzü)
  - [12.5 Web Arama](#125-web-arama)
  - [12.6 RAG](#126-rag)
  - [12.7 Hafıza ve ReAct](#127-hafıza-ve-react)
  - [12.8 Loglama](#128-loglama)
  - [12.9 Rate Limiting](#129-rate-limiting)
  - [12.10 Çeşitli](#1210-çeşitli)
- [13. Olası İyileştirmeler](#13-olası-iyileştirmeler)
- [14. Sonraki Versiyon İçin Geliştirme Önerileri (v2.8+)](#14-sonraki-versiyon-için-geliştirme-önerileri-v28)
  - [14.1 Çekirdek Mimari](#141-çekirdek-mimari)
  - [14.3 RAG ve Bellek](#143-rag-ve-bellek)
  - [14.4 Web Arayüzü ve API](#144-web-arayüzü-ve-api)
  - [14.5 GitHub Entegrasyonu](#145-github-entegrasyonu)
  - [14.6 Güvenlik ve İzleme](#146-güvenlik-ve-izleme)
  - [14.7 Test ve Kalite](#147-test-ve-kalite)
  - [14.8 Operasyon ve Dağıtım](#148-operasyon-ve-dağıtım)
  - [14.9 Versiyon 2.8 İçin Önerilen Öncelik Sırası](#149-versiyon-28-için-önerilen-öncelik-sırası)
- [15. Özellik-Gereksinim Matrisi](#15-özellik-gereksinim-matrisi)
  - [15.1 Çekirdek Özellikler (Her Zaman Zorunlu)](#151-çekirdek-özellikler-her-zaman-zorunlu)
  - [15.2 Arama ve Web](#152-arama-ve-web)
  - [15.3 RAG (Belge Deposu)](#153-rag-belge-deposu)
  - [15.4 Sistem İzleme ve GPU](#154-sistem-izleme-ve-gpu)
  - [15.5 Kod Yürütme](#155-kod-yürütme)
  - [15.6 Özellik Profilleri](#156-özellik-profilleri)
- [16. Hata Yönetimi ve Loglama Stratejisi](#16-hata-yönetimi-ve-loglama-stratejisi)
  - [16.1 Hata Yönetimi Kalıpları](#161-hata-yönetimi-kalıpları)
  - [16.2 Loglama Stratejisi](#162-loglama-stratejisi)
  - [16.3 Asenkron Hata Yönetimi](#163-asenkron-hata-yönetimi)
  - [16.4 Bozuk Veri Karantinası](#164-bozuk-veri-karantinası)
- [17. Yaygın Sorunlar ve Çözümleri](#17-yaygın-sorunlar-ve-çözümleri)

---

## 1. Proje Genel Bakışı

[⬆ İçindekilere Dön](#içindekiler)

**Sidar**, ReAct (Reason + Act) döngüsüyle çalışan, tamamen asenkron bir yazılım mühendisi AI asistanıdır. Yerel LLM (Ollama) veya bulut tabanlı LLM (Google Gemini) ile çalışabilir; CLI ve FastAPI tabanlı Web arayüzü olmak üzere iki ayrı kullanıcı ara yüzü sunar.

### Temel Özellikler
- **Çift arayüz:** CLI (`cli.py`) ve Web (`web_server.py` + `web_ui/index.html`)
- **Çift LLM sağlayıcı:** Ollama (yerel) ve Gemini (bulut)
- **ReAct döngüsü:** LLM → Araç çağrısı → Gözlem → LLM (maks. `MAX_REACT_STEPS` adım)
- **RAG (Vektör Bellek):** ChromaDB + BM25 + Keyword hibrit arama
- **Güvenlik:** OpenClaw 3 katmanlı erişim sistemi (restricted / sandbox / full)
- **GPU desteği:** CUDA, FP16, çoklu GPU, WSL2 uyumu
- **Kalıcı bellek:** Fernet (AES-128-CBC) ile opsiyonel şifreli oturum depolama
- **Docker izolasyonu:** Kod çalıştırma sandbox ortamı

---

## 2. Proje Dosya Yapısı

[⬆ İçindekilere Dön](#içindekiler)

```
sidar_project/
├── main.py                    # Akıllı başlatıcı (wizard + --quick mod)
├── cli.py                     # CLI terminal arayüzü giriş noktası
├── web_server.py              # FastAPI web sunucusu (SSE streaming)
├── config.py                  # Merkezi yapılandırma (v2.7.0)
├── github_upload.py           # GitHub otomatik yükleme aracı
├── Dockerfile                 # CPU + GPU çift mod Dockerfile
├── docker-compose.yml         # 4 servis: cli/web × cpu/gpu
├── environment.yml            # Conda/pip bağımlılıkları
│
├── agent/
│   ├── __init__.py
│   ├── sidar_agent.py         # Ana ajan (1455 satır, 40+ araç)
│   ├── auto_handle.py         # Anahtar kelime tabanlı hızlı yönlendirici
│   ├── definitions.py         # Sistem istemi ve ajan kimliği
│   └── tooling.py             # Araç kayıt + Pydantic şema yöneticisi (189 satır)
│
├── core/
│   ├── __init__.py
│   ├── llm_client.py          # Ollama + Gemini asenkron istemci
│   ├── memory.py              # Kalıcı çok oturumlu bellek
│   └── rag.py                 # ChromaDB + BM25 hibrit RAG motoru
│
├── managers/
│   ├── __init__.py
│   ├── code_manager.py        # Dosya I/O + Docker REPL + denetim
│   ├── security.py            # OpenClaw erişim kontrol sistemi
│   ├── github_manager.py      # GitHub API entegrasyonu
│   ├── system_health.py       # CPU/RAM/GPU izleme
│   ├── web_search.py          # Tavily + Google + DuckDuckGo arama
│   ├── package_info.py        # PyPI + npm + GitHub Releases
│   └── todo_manager.py        # Görev takip yöneticisi
│
├── web_ui/
│   └── index.html             # Vanilla JS tek sayfa uygulama (3399 satır)
│
├── tests/                     # 32 test modülü
│   ├── test_sidar.py
│   ├── test_tooling_registry.py
│   ├── test_parallel_react_improvements.py
│   ├── test_github_upload_improvements.py
│   ├── test_core_init_improvements.py
│   ├── test_managers_init_improvements.py
│   ├── test_claude_md_improvements.py
│   ├── test_sidar_md_improvements.py
│   └── test_*_improvements.py
│
├── data/                      # RAG ve bellek verileri
├── CLAUDE.md                  # Geliştirici rehberi
└── .env.example               # Ortam değişkeni şablonu
```

---

## 3. Modül Bazında Detaylı Analiz

[⬆ İçindekilere Dön](#içindekiler)

---

### 3.1 `config.py` — Merkezi Yapılandırma (517 satır)

**Amaç:** Tüm sistem ayarlarını tek noktada toplar; `.env` dosyasını yükler ve donanım tespiti yapar.

**Kritik Bileşenler:**

| Bileşen | Açıklama |
|---------|----------|
| `get_bool_env / get_int_env / get_float_env / get_list_env` | Type-safe ortam değişkeni okuma yardımcıları |
| `HardwareInfo` (dataclass) | CUDA tespiti sonuçlarını tutar |
| `_is_wsl2()` | `/proc/sys/kernel/osrelease` ile WSL2 ortam tespiti |
| `check_hardware()` | PyTorch üzerinden GPU tespiti; pynvml ile sürücü bilgisi |
| `Config` (sınıf) | Tüm sistem parametrelerini sınıf attribute olarak tutar |

**`Config` Sınıfı Parametre Grupları:**

- **AI Sağlayıcı:** `AI_PROVIDER`, `GEMINI_API_KEY`, `GEMINI_MODEL`, `OLLAMA_URL`, `CODING_MODEL`, `TEXT_MODEL`
- **Güvenlik:** `ACCESS_LEVEL`, `MEMORY_ENCRYPTION_KEY`
- **GPU/Donanım:** `USE_GPU`, `GPU_DEVICE`, `GPU_COUNT`, `CUDA_VERSION`, `GPU_MEMORY_FRACTION`, `GPU_MIXED_PRECISION`, `MULTI_GPU`
- **ReAct:** `MAX_REACT_STEPS` (10), `REACT_TIMEOUT` (60), `SUBTASK_MAX_STEPS` (5), `AUTO_HANDLE_TIMEOUT` (12)
- **Rate Limiting:** `RATE_LIMIT_CHAT` (20/dk), `RATE_LIMIT_MUTATIONS` (60/dk), `RATE_LIMIT_GET_IO` (30/dk)
- **RAG:** `RAG_DIR`, `RAG_TOP_K` (3), `RAG_CHUNK_SIZE` (1000), `RAG_CHUNK_OVERLAP` (200), `RAG_FILE_THRESHOLD` (20000)
- **Web Arama:** `SEARCH_ENGINE`, `TAVILY_API_KEY`, `GOOGLE_SEARCH_API_KEY`, `WEB_SEARCH_MAX_RESULTS` (5)
- **Docker REPL:** `DOCKER_PYTHON_IMAGE` (`python:3.11-alpine`), `DOCKER_EXEC_TIMEOUT` (10sn)
- **Loglama:** `RotatingFileHandler` (10 MB / 5 yedek), UTF-8 zorunlu

**Dikkat Noktaları:**
- `_ensure_hardware_info_loaded()` ile lazy-load: import anında GPU yükleme yan etkisi yoktur.
- `validate_critical_settings()` Gemini API anahtarı ve Fernet anahtar formatını başlangıçta doğrular.
- Tüm sınıf attribute'ları modül import anında bir kez değerlendirilir; çalışma zamanı override için instance attribute kullanılmalıdır.

---

### 3.2 `main.py` — Akıllı Başlatıcı (331 satır)

**Amaç:** Sidar'ı başlatmak için etkileşimli sihirbaz veya `--quick` hızlı mod sağlar.

**Temel Fonksiyonlar:**

| Fonksiyon | Açıklama |
|-----------|----------|
| `print_banner()` | ANSI renkli ASCII art banner |
| `ask_choice(prompt, options, default)` | Güvenli menü seçimi (geçersiz giriş döngüsü) |
| `ask_text(prompt, default)` | Metin girişi (Enter = varsayılan) |
| `confirm(prompt, default_yes)` | Y/n onay istemi |
| `preflight(provider)` | `.env` varlığı, Python sürümü, Ollama/Gemini erişim kontrolü |
| `build_command(mode, provider, level, log, extra_args)` | `cli.py` veya `web_server.py` komutu oluşturur |
| `_stream_pipe(pipe, file, prefix, color, mirror)` | Thread'de pipe akışını bellek dostu okur |
| `_run_with_streaming(cmd, log_path)` | Çocuk süreç stdout/stderr canlı yayınlar; opsiyonel dosya logu |
| `execute_command(cmd, capture_output, child_log)` | `subprocess.run` veya streaming ile çalıştırır |
| `run_wizard()` | 4 adımlı etkileşimli menü |

**`--quick` Mod Argümanları:**
```
python main.py --quick web --host 0.0.0.0 --port 7860
python main.py --quick cli --provider gemini --level sandbox
python main.py --quick web --capture-output --child-log logs/child.log
```

**Mimari Not:** `DummyConfig` fallback sınıfı ile `config.py` olmadan da çalışır.

---

### 3.3 `cli.py` — CLI Arayüzü (274 satır)

**Amaç:** Terminal tabanlı etkileşimli REPL döngüsü.

**Mimari Düzeltme:**
Eski kodda `while` döngüsü içinde her turda `asyncio.run()` çağrılıyordu; bu `asyncio.Lock` ömrünü bozuyordu. Yeni yapıda tüm döngü tek bir `async` fonksiyona (`_interactive_loop_async`) alınmıştır — lock tüm oturum boyunca aynı event loop'ta yaşar.

**Desteklenen Nokta Komutları:**

| Komut | Eylem |
|-------|-------|
| `.status` | Sistem durumu |
| `.clear` / `/clear` / `/reset` | Konuşma belleğini temizle |
| `.audit` | Proje denetimi |
| `.health` | Sistem sağlık raporu |
| `.gpu` | GPU belleği optimize et |
| `.github` | GitHub bağlantı durumu |
| `.level` | Erişim seviyesini göster |
| `.web` | Web arama durumu |
| `.docs` | Belge deposunu listele |
| `.help` | Yardım |
| `.exit` / `.q` | Çıkış |

**Doğrudan Komutlar (AutoHandle üzerinden):**
- `web'de ara: <sorgu>`, `pypi: <paket>`, `npm: <paket>`, `github releases: <owner/repo>`, `docs ara: <sorgu>`, `stackoverflow: <sorgu>`, `belge ekle <url>`

**CLI Argümanları:**
- `--level`, `--provider`, `--model`, `--log`, `-c/--command`, `--status`

---

### 3.4 `web_server.py` — FastAPI Web Sunucusu (794 satır)

**Amaç:** SSE (Server-Sent Events) destekli asenkron chat web arayüzü.

**v2.8.0 Eklentisi:** `StaticFiles` middleware ile `web_ui/` dizininin `/static` yolu üzerinden servis edilmesi sağlandı. `index.html` ayrı rotası `/` → `FileResponse` ile korunuyor; statik JS/CSS dosyaları performanslı ve güvenli şekilde sunuluyor.

```python
app.mount("/static", StaticFiles(directory=web_ui_dir), name="static")
```

**Temel API Endpoint'leri:**

| Endpoint | Metod | Açıklama |
|----------|-------|----------|
| `/` | GET | `index.html` servis et |
| `/static/*` | GET | JS/CSS statik dosyaları (`web_ui/`) |
| `/chat` | POST | SSE akışlı LLM yanıtı (rate limit: 20/dk) |
| `/status` | GET | Sistem durumu JSON |
| `/metrics` | GET | Uptime, istek sayacı |
| `/sessions` | GET | Tüm oturum listesi |
| `/sessions` | POST | Yeni oturum oluştur |
| `/sessions/{id}` | POST | Oturum yükle / başlık güncelle |
| `/sessions/{id}` | DELETE | Oturum sil |
| `/clear` | POST | Aktif belleği temizle |
| `/files` | GET | Proje dosyalarını listele |
| `/file-content` | GET | Dosya içeriğini oku |
| `/git-info` | GET | Git log/status |
| `/git-branches` | GET | Branch listesi |
| `/rag/documents` | GET | RAG belge listesi |
| `/rag/documents` | POST | URL'den belge ekle |
| `/rag/documents/{id}` | DELETE | Belge sil |
| `/rag/search` | GET | RAG arama |
| `/todo` | GET | Görev listesi |
| `/github-prs` | GET | GitHub PR listesi |
| `/ollama-models` | GET | Ollama model listesi |
| `/health` | GET | Sağlık raporu |

**Güvenlik Mekanizmaları:**
- `CORSMiddleware`: Yalnızca `localhost/127.0.0.1/0.0.0.0` kökenlerine izin verir
- Rate limiting: `TTLCache(maxsize=10000, ttl=cfg.RATE_LIMIT_WINDOW)` ile 3 ayrı limit katmanı (chat/mutation/GET-IO)
- `anyio.ClosedResourceError` ile kopuk SSE bağlantıları sessizce kapatılır

**Singleton Ajan:** `get_agent()` fonksiyonu ile lazy-init; event loop başladıktan sonra `asyncio.Lock` oluşturulur.

---

### 3.5 `agent/sidar_agent.py` — Ana Ajan (1455 satır)

**Amaç:** ReAct döngüsü, araç yönetimi, akış yönetimi ve özetleme mantığı.

**Araç Kataloğu (40+ araç):**

| Kategori | Araçlar |
|----------|---------|
| Dosya İşlemleri | `list_dir`, `read_file`, `write_file`, `patch_file`, `glob_search`, `grep_files` |
| Kod Yürütme | `execute_code`, `run_shell` / `bash` / `shell` |
| GitHub | `github_commits`, `github_info`, `github_read`, `github_list_files`, `github_write`, `github_create_branch`, `github_create_pr`, `github_smart_pr`, `github_list_prs`, `github_get_pr`, `github_comment_pr`, `github_close_pr`, `github_pr_files`, `github_search_code` |
| Web | `web_search`, `fetch_url`, `search_docs`, `search_stackoverflow` |
| Paket Bilgi | `pypi`, `pypi_compare`, `npm`, `gh_releases`, `gh_latest` |
| RAG | `docs_search`, `docs_add`, `docs_add_file`, `docs_list`, `docs_delete` |
| Sistem | `health`, `gpu_optimize`, `audit`, `get_config`, `print_config_summary` |
| Görev | `todo_write`, `todo_read`, `todo_update` |
| Alt Ajan | `subtask` / `agent`, `parallel` |

**ReAct Döngüsü Akışı:**
```
kullanıcı mesajı
    → AutoHandle (hızlı yönlendirici)
        → [eşleşirse] doğrudan yanıt döner
        → [eşleşmezse] LLM çağrısı
            → JSON: {thought, tool, argument}
                → araç çalıştırılır
                    → sonuç belleğe eklenir
                        → [final_answer değilse] LLM tekrar çağrılır (maks. MAX_REACT_STEPS)
                            → final_answer → kullanıcıya akış
```

**Önemli Tasarım Kararları:**

1. **`_DIRECT_ROUTE_ALLOWED_TOOLS`:** `list_dir`, `read_file`, `health` vb. tek adımlı güvenli araçlar ReAct döngüsüne girmeden doğrudan çalıştırılır. Gereksiz LLM çağrısını önler.

2. **Yapısal Çıktı (Pydantic):** LLM çıktısı `ToolCall` modeli ile doğrulanır. Geçersiz JSON → `_FMT_SYS_ERR` formatında belleğe yazılır.

3. **Döngü Tespiti:** Aynı araç 3 kez arka arkaya çağrılırsa uyarı üretilir ve `final_answer`'a yönlendirilir.

4. **`_instructions_cache`:** `SIDAR.md` ve `CLAUDE.md` dosyaları mtime tabanlı cache ile okunur; her turda disk I/O yapılmaz.

5. **Bellek Özetleme:** `ConversationMemory.needs_summarization()` True döndürdüğünde ajan LLM'i özetleme için çağırır; eski turlar tek bir "KONUŞMA ÖZETİ" mesajıyla değiştirilir.

6. **`subtask` aracı:** Alt görev için bağımsız ajan döngüsü açar; `SUBTASK_MAX_STEPS` (varsayılan 5) adımla sınırlıdır.

7. **`parallel` aracı:** Birden fazla araç argümanını eşzamanlı `asyncio.gather` ile çalıştırır.

---

### 3.6 `agent/auto_handle.py` — Hızlı Yönlendirici (601 satır)

**Amaç:** Kullanıcı mesajındaki ortak kalıpları regex ile tanıyarak LLM döngüsüne girmeden cevap verir.

**Mimari:**
- `AutoHandle.handle(text)` → `(işlendi_mi: bool, yanıt: str)` döner
- Senkron araçlar `asyncio.to_thread` ile event loop bloklanmadan çalıştırılır
- `AUTO_HANDLE_TIMEOUT` (varsayılan 12 sn) ile her araç çağrısı zaman aşımına karşı korunur

**`_MULTI_STEP_RE` Koruyucu:** "ardından", "önce...sonra", numaralı adım kalıpları algılanırsa AutoHandle çıkar ve ReAct'a bırakır.

**İşlenen Kalıplar:**

| Kategori | Regex Tetikleyici Örnekler |
|----------|---------------------------|
| Nokta komutları | `.status`, `.health`, `.clear`, `.audit`, `.gpu` |
| Dosya okuma | `dosyayı oku`, `incele`, `cat` |
| Dizin listeleme | `dizin listele`, `ls` |
| Denetim | `denetle`, `audit`, `teknik rapor` |
| Sağlık | `sistem sağlık`, `cpu durumu`, `gpu durum` |
| GitHub | `son commit`, `PR listele`, `github bilgi` |
| Web arama | `web'de ara:`, `google:`, `internette ara` |
| Paket bilgi | `pypi:`, `npm:`, `github releases:` |
| RAG | `depoda ara:`, `belge ekle`, `belge listele` |
| Güvenlik durumu | `openclaw`, `erişim seviyesi`, `access level` |

---

### 3.7 `agent/definitions.py` — Ajan Tanımları (165 satır)

**Amaç:** `SIDAR_SYSTEM_PROMPT` sistem istemini barındırır.

**Sistem İstemi Bölümleri:**

| Bölüm | İçerik |
|-------|--------|
| KİŞİLİK | Analitik, minimal, veriye dayalı, güvenliğe şüpheci |
| MİSYON | Dosya erişimi, GitHub senkronizasyonu, kod yönetimi, teknik denetim |
| BİLGİ SINIRI | Ağustos 2025 sonrası için tahmin yasağı; `web_search` / `pypi` zorunlu |
| HALLUCINATION YASAĞI | Sistem değerlerini (versiyon, model, yol) ASLA uydurma; `get_config` kullan |
| DOSYA ERİŞİM STRATEJİSİ | `glob_search` → `read_file` → `patch_file` sırası |
| GÖREV TAKİP | Çok adımlı görevlerde `todo_write` zorunlu |
| SIDAR.md | Proje özel talimatların otomatik yüklenmesi |
| DÖNGÜ YASAĞI | Aynı araç 2 kez çağrılmaz; tek adımlı araçlar listelendi |
| ARAÇ KULLANIM STRATEJİLERİ | Her araç için ne zaman / hangi argüman kullanılacağı |
| ÖRNEK JSON YANITLARI | 5 örnek senaryo |

---

### 3.7b `agent/tooling.py` — Araç Kayıt ve Şema Yöneticisi (189 satır)

**Amaç:** Araçların Pydantic şemalarını ve `build_tool_dispatch()` fonksiyonu aracılığıyla araç dispatch tablosunu merkezi olarak yönetir.

**Kritik Bileşenler:**

| Bileşen | Açıklama |
|---------|----------|
| `WriteFileSchema` | `path` + `content` alanlarına sahip yazma şeması |
| `PatchFileSchema` | `path` + `old_text` + `new_text` alanlarına sahip yama şeması |
| `GithubListFilesSchema` | `path` + opsiyonel `branch` alanları |
| `GithubWriteSchema` | `path`, `content`, `commit_message`, opsiyonel `branch` |
| `GithubCreateBranchSchema` | `branch_name` + opsiyonel `from_branch` |
| `GithubCreatePRSchema` | `title`, `body`, `head`, opsiyonel `base` |
| `GithubListPRsSchema` | `state` (varsayılan: `"open"`) + `limit` (varsayılan: 10) |
| `TOOL_ARG_SCHEMAS` | Araç adını şema sınıfına eşleyen sözlük |
| `parse_tool_argument()` | JSON öncelikli, `|||` sınırlı legacy format fallback ile argüman ayrıştırma |
| `build_tool_dispatch()` | `SidarAgent` instance'ından araç adı → metod sözlüğü üretir |

**`parse_tool_argument()` İki Aşamalı Ayrıştırma Mantığı:**
1. **JSON öncelik:** `json.loads(text)` başarılıysa `schema.model_validate(dict)` ile Pydantic doğrulaması yapılır.
2. **Legacy format fallback:** `|||` ayırıcısı ile bölünmüş eski string formatı desteklenir. Bu, eski LLM çıktılarıyla geriye dönük uyumluluğu korur.

**`build_tool_dispatch()` Araç Tablosu (44 araç + alias'lar):**

| Araç Adı | Alias | Metod |
|----------|-------|-------|
| `list_dir` | `ls` | `_tool_list_dir` |
| `read_file` | — | `_tool_read_file` |
| `write_file` | — | `_tool_write_file` |
| `patch_file` | — | `_tool_patch_file` |
| `execute_code` | — | `_tool_execute_code` |
| `run_shell` | `bash`, `shell` | `_tool_run_shell` |
| `glob_search` | — | `_tool_glob_search` |
| `grep_files` | `grep` | `_tool_grep_files` |
| `github_*` (13 araç) | — | `_tool_github_*` |
| `web_search`, `fetch_url`, `search_docs`, `search_stackoverflow` | — | `_tool_*` |
| `pypi`, `pypi_compare`, `npm`, `gh_releases`, `gh_latest` | — | `_tool_*` |
| `docs_search`, `docs_add`, `docs_add_file`, `docs_list`, `docs_delete` | — | `_tool_*` |
| `health`, `gpu_optimize`, `audit` | — | `_tool_*` |
| `todo_write`, `todo_read`, `todo_update` | — | `_tool_*` |
| `get_config` | `print_config_summary` | `_tool_get_config` |
| `subtask` | `agent` | `_tool_subtask` |

> **Not:** `parallel` aracı bu dispatch tablosunda yer almaz; `sidar_agent.py` içinde ReAct döngüsünde doğrudan `asyncio.gather` ile işlenir.

**Mimari Değer:** `tooling.py` sayesinde araç ekleme/değiştirme işlemleri `sidar_agent.py` içine dağılmaz; tek bir yerden yönetilir. Şema eklemek için yalnızca `TOOL_ARG_SCHEMAS` sözlüğüne yeni giriş yapılması yeterlidir.

---

### 3.8 `core/llm_client.py` — LLM İstemcisi (513 satır)

**Amaç:** Ollama ve Gemini için asenkron chat arayüzü.

**`LLMClient.chat()` Parametreleri:**
- `stream`: True → `AsyncIterator[str]`, False → `str`
- `json_mode`: True → LLM'i `{thought, tool, argument}` JSON çıktısına zorlar

**Ollama Entegrasyonu:**
- **Yapısal Çıktı (Structured Output):** Ollama ≥0.4 için JSON Schema formatı ile `{thought, tool, argument}` şeması zorunlu kılınır. Hallucination ve yanlış format sorunlarını önler.
- **Stream Güvenliği:** `aiter_bytes()` + `codecs.IncrementalDecoder` ile TCP paket sınırlarında bölünen JSON satırları güvenle birleştirilir. `aiter_lines()` kullanılmaz çünkü bu yaklaşım içerik kaybına yol açabilir.
- **GPU Desteği:** `USE_GPU=true` ise `options.num_gpu=-1` ile tüm katmanlar GPU'ya gönderilir.
- **Timeout:** `max(10, OLLAMA_TIMEOUT)` — minimum 10 sn garanti edilir.

**Gemini Entegrasyonu:**
- `google.generativeai` paketi runtime'da import edilir; kurulu değilse anlamlı hata mesajı döner.
- `response_mime_type: application/json` ile JSON modu; `text/plain` ile düz metin modu.
- Safety settings: Tüm zararlı içerik kategorileri `BLOCK_NONE` — teknik konularda LLM bloklamalarını önler.
- `send_message_async` ile gerçek asenkron Gemini çağrısı.

**`_ensure_json_text()`:** Modelin JSON dışı metin döndürmesi durumunda `final_answer` sarmalayıcı olarak güvenli JSON üretir.

---

### 3.9 `core/memory.py` — Konuşma Belleği (394 satır)

**Amaç:** Çok oturumlu, kalıcı, thread-safe ve opsiyonel şifreli bellek yönetimi.

**Mimari:**
- Her oturum `data/sessions/<uuid>.json` dosyasında saklanır
- `threading.RLock` ile tüm okuma/yazma işlemleri korunur
- Bozuk dosyalar `.json.broken` uzantısıyla karantinaya alınır (7 gün / 50 dosya retention)
- `active_session_id: Optional[str]` özelliği ile mevcut oturum RAG izolasyonuna aktarılır

**Fernet Şifrelemesi:**
- `MEMORY_ENCRYPTION_KEY` ayarlandığında oturum dosyaları AES-128-CBC ile şifrelenir
- Geçiş dönemi uyumu: şifre çözülemeyen eski dosyalar düz metin olarak okunmaya çalışılır
- Anahtar geçersizse `ValueError` ile sistem durdurulur (fail-closed)

**Kaydetme Optimizasyonu:**
- `_save_interval_seconds = 0.5` ile kısa aralıklı `add()` çağrıları birleştirilir
- `force_save()` ile anında disk yazımı (clear, session değişimi, başlık güncelleme)

**Özetleme Desteği (v2.9.0 — §14.3.4 Sliding Window):**
- `needs_summarization()`: bellek penceresinin %80'i dolu VEYA tahminî token > 6000 ise True
- `apply_summary(text)`: v2.9.0 öncesi tüm geçmiş 2 mesaja indirgeniyor; v2.9.0 itibarıyla **kayan pencere** uygulandı:
  - Son `keep_last` mesaj (varsayılan: 4) tam olarak korunur
  - Daha eski mesajlar özet çiftiyle değiştirilir: `[özet_user, özet_assistant, *son_mesajlar]`
  - `MEMORY_SUMMARY_KEEP_LAST` env değişkeni ile yapılandırılabilir

**Token Tahmini:** `_estimate_tokens()` — UTF-8 Türkçe için ~3.5 karakter/token heuristic kullanır.

---

### 3.10 `core/rag.py` — RAG Motoru (777 satır)

**Amaç:** ChromaDB (vektör) + BM25 (kelime sıklığı) + Keyword (basit eşleşme) hibrit belge deposu. v2.9.0 itibarıyla **RRF birleştirme** ve **oturum izolasyonu** eklendi.

**Arama Modları (v2.9.0 — §14.3.1 RRF + §14.3.3 İzolasyon):**

| Mod | Motor | Açıklama |
|-----|-------|----------|
| `auto` | **RRF (ChromaDB + BM25)** → ChromaDB → BM25 → Keyword | v2.9.0: Her iki motor mevcutsa RRF öncelikli |
| `vector` | ChromaDB (cosine similarity + `session_id` where filtresi) | Anlamsal arama |
| `bm25` | rank_bm25 (Python'da `session_id` filtresi) | TF-IDF benzeri kelime sıklığı |
| `keyword` | Regex (`session_id` kontrolü) | Başlık ×5, etiket ×3, içerik ×1 ağırlıkla skor |

**RRF Algoritması (`_rrf_search`):**
```python
# Her iki motordan sonuç alınır; rank tabanlı birleştirme
rrf_score(doc) = Σ  1 / (k + rank_i)   (k=60, TREC'19 standardı)
```
ChromaDB ve BM25 sonuçları `_fetch_chroma()` / `_fetch_bm25()` ayrı metodlarıyla alınır; skorlar birleştirilerek `top_k` sonuç döndürülür.

**Oturum İzolasyonu (`session_id` — §14.3.3):**
- `add_document()`: her belgeye `session_id` metadata alanı eklenir
- `_fetch_chroma()`: `where={"session_id": session_id}` ChromaDB filtresi
- `_fetch_bm25()`: Python düzeyinde `valid_doc_ids` seti ile oturum filtresi
- `_keyword_search()`: `meta.get("session_id")` kontrolü
- `delete_document()`: farklı oturumun belgesini silmeye karşı yetki kontrolü
- `get_index_info()`: `session_id=None` → tüm belgeler; `session_id=<id>` → oturuma özgü

**Chunking Motoru:**
`_recursive_chunk_text()` LangChain'in `RecursiveCharacterTextSplitter` mantığını simüle eder. Öncelik sırası: `\nclass ` → `\ndef ` → `\n\n` → `\n` → ` ` → karakter. Overlap mekanizması bağlam sürekliliğini korur.

**GPU Embedding:**
`_build_embedding_function()` — `USE_GPU=true` ise `sentence-transformers/all-MiniLM-L6-v2` modeli CUDA üzerinde çalışır. `GPU_MIXED_PRECISION=true` ise FP16 ile VRAM tasarrufu sağlanır.

**BM25 Cache:**
Inkremental güncelleme: belge eklendiğinde/silindiğinde tüm corpus yeniden yüklenmez; yalnızca değişen kayıt güncellenir. `_ensure_bm25_index()` lazy build ile gereksiz CPU kullanımını önler.

**Belge Yönetimi:**
- `add_document(session_id)`: dosya sistemi + index.json + ChromaDB chunked upsert (thread-safe `_write_lock`)
- `add_document_from_url(session_id)`: httpx asenkron HTTP çekme + HTML temizleme + ekleme
- `add_document_from_file(session_id)`: uzantı whitelist kontrolü (.py, .md, .json, .yaml, vb.)
- `delete_document(session_id)`: izolasyon yetki kontrolü sonrası dosya + ChromaDB + BM25 cache

---

### 3.11 `managers/security.py` — Güvenlik Yöneticisi (280 satır)

**Amaç:** OpenClaw erişim kontrol sistemi — 3 katmanlı güvenlik.

**Erişim Seviyeleri:**

| Seviye | Okuma | Yazma | REPL | Shell |
|--------|-------|-------|------|-------|
| `restricted` (0) | ✓ | ✗ | ✗ | ✗ |
| `sandbox` (1) | ✓ | Yalnızca `/temp` | ✓ | ✗ |
| `full` (2) | ✓ | Proje kökü altı | ✓ | ✓ |

**Güvenlik Katmanları:**

1. **Path Traversal Koruması:** `_DANGEROUS_PATH_RE` ile `../`, `/etc/`, `/proc/`, `/sys/`, `C:\Windows` kalıpları engellenir.
2. **Hassas Yol Engelleme:** `_BLOCKED_PATTERNS` — `.env`, `sessions/`, `.git/`, `__pycache__/` engellenir.
3. **Symlink Koruması:** `Path.resolve()` ile gerçek hedef hesaplanır; base_dir dışına çıkan symlink'ler reddedilir.
4. **Bilinmeyen Seviye Normalize:** Geçersiz seviye adı → `sandbox` varsayılanı (fail-safe).

---

### 3.12 `managers/code_manager.py` — Kod Yöneticisi (746 satır)

**Amaç:** Dosya okuma/yazma, sözdizimi doğrulama, proje denetimi ve Docker izole kod çalıştırma.

**Docker REPL Mimarisi:**
- `_init_docker()` önce `docker.from_env()` dener; başarısız olursa WSL2 socket yollarını (`/var/run/docker.sock`, Desktop socket) dener.
- `execute_code()`: Python kodunu geçici dosyaya yazar; `python:3.11-alpine` konteynerinde çalıştırır; `DOCKER_EXEC_TIMEOUT` (10 sn) ile sonsuz döngü koruması.
- Docker yoksa subprocess fallback (sandbox fail-closed prensibi uygulanır).

**Desteklenen Dosya Uzantıları:** `.py`, `.js`, `.ts`, `.json`, `.yaml`, `.yml`, `.md`, `.txt`, `.sh`

**Metrikler:** `_files_read`, `_files_written`, `_syntax_checks`, `_audits_done` sayaçları

**Denetim (`audit_project`):** Proje kökündeki tüm Python dosyalarını tarar; import listesi, `TODO`/`FIXME` yorumları, sözdizimi hataları, büyük dosyalar raporlanır.

---

### 3.13 `managers/github_manager.py` — GitHub Yöneticisi (560 satır)

**Amaç:** PyGithub üzerinden GitHub API entegrasyonu.

**Güvenlik:**
- `SAFE_TEXT_EXTENSIONS` whitelist: yalnızca metin tabanlı dosyalar okunabilir (binary engellenir)
- `SAFE_EXTENSIONLESS`: `Makefile`, `Dockerfile`, `LICENSE` vb. uzantısız güvenli dosya isimleri
- `_BRANCH_RE`: Yalnızca `[a-zA-Z0-9/_.\-]` karakterleri içeren dal adları kabul edilir
- `_is_not_found_error()`: PyGithub 404 hatalarını güvenli şekilde yakalar

**Özellikler:**
- `list_commits(n)`, `get_repo_info()`, `list_files(path)`, `read_remote_file(path)`
- `write_file()`, `create_branch()`, `create_pr()`, `list_pull_requests()`
- `get_pull_request()`, `comment_pr()`, `close_pr()`, `get_pr_files()`
- `search_code(query)`, `github_smart_pr()` — LLM ile otomatik PR başlığı/açıklaması
- Commit listesi: güvenlik ve sayfalama nedeniyle maksimum 30 commit

---

### 3.14 `managers/system_health.py` — Sistem Sağlık Yöneticisi (420 satır)

**Amaç:** CPU/RAM/GPU donanım izleme ve VRAM optimizasyonu.

**Bağımlılıklar (opsiyonel):**
- `psutil`: CPU ve RAM metrikleri
- `torch`: CUDA mevcutluğu, VRAM kullanımı, `empty_cache()`
- `pynvml`: GPU sıcaklık, anlık kullanım yüzdesi, sürücü sürümü

**`full_report()`:** CPU yüzdesi, RAM (kullanılan/toplam/yüzde), GPU (VRAM kullanılan/toplam, sıcaklık, kullanım), platform bilgisi.

**`optimize_gpu_memory()`:** `torch.cuda.empty_cache()` + `gc.collect()` ile VRAM boşaltır.

**atexit hook:** `self.close()` ile pynvml kapatma garanti edilir.

---

### 3.15 `managers/web_search.py` — Web Arama Yöneticisi (379 satır)

**Amaç:** Tavily → Google → DuckDuckGo kademeli motor desteğiyle asenkron web araması.

**`auto` Mod Öncelik Sırası:** Tavily → Google Custom Search → DuckDuckGo

**Desteklenen Operasyonlar:**
- `search(query)`: Genel web araması
- `fetch_url(url)`: URL içerik çekme + BeautifulSoup HTML temizleme
- `search_docs(library, topic)`: Resmi dokümantasyon araması
- `search_stackoverflow(query)`: Stack Overflow araması

**v2.8.0 DuckDuckGo Güvenlik İyileştirmeleri (Madde #10 Çözümü):**

`_search_duckduckgo()` içinde üç katmanlı güvenlik uygulandı:

```python
# 1. Dinamik AsyncDDGS kontrolü (versiyon değişikliği koruması)
if hasattr(duckduckgo_search, "AsyncDDGS"):
    results = await asyncio.wait_for(_async_search(), timeout=FETCH_TIMEOUT)
else:
    # AsyncDDGS yoksa (gelecek sürümler için) sync+thread fallback
    results = await asyncio.wait_for(
        asyncio.to_thread(_sync_search), timeout=FETCH_TIMEOUT)

# 2. Timeout koruması — her iki yol da wait_for ile sınırlı
# 3. Except sırası: asyncio.TimeoutError > Exception (Python best practice)
except asyncio.TimeoutError:  # Spesifik önce
    ...
except Exception as exc:       # Genel sonra
    ...
```

| Güvenlik Katmanı | Açıklama |
|---|---|
| Versiyon pinleme | `environment.yml`: `duckduckgo-search~=6.2.13` |
| `AsyncDDGS` dinamik kontrol | `hasattr()` ile mevcut sürümde async yol, gelecek sürümlerde sync yol |
| `asyncio.wait_for()` | Her iki arama yolu için `FETCH_TIMEOUT` sınırı (sessiz takılma engeli) |
| `asyncio.TimeoutError` handler | Spesifik timeout mesajı + `logger.warning` |

**Konfigürasyon:** `WEB_SEARCH_MAX_RESULTS` (5), `WEB_FETCH_TIMEOUT` (15sn), `WEB_SCRAPE_MAX_CHARS` (12000)

---

### 3.16 `managers/package_info.py` — Paket Bilgi Yöneticisi (314 satır)

**Amaç:** PyPI, npm ve GitHub Releases gerçek zamanlı sorgusu.

**Özellikler:**
- `pypi_info(package)`: Sürüm, lisans, GitHub URL, son güncelleme tarihi
- `pypi_compare(package, version)`: Mevcut kurulu sürüm ile son sürüm karşılaştırması
- `npm_info(package)`: npm Registry paket bilgisi
- `github_releases(owner/repo)`: GitHub Releases listesi

**Cache:** `PACKAGE_INFO_CACHE_TTL` (1800 sn = 30 dk) ile in-memory TTL cache. API limit koruması sağlar.

---

### 3.17 `managers/todo_manager.py` — Görev Takip Yöneticisi (380 satır)

**Amaç:** Claude Code'daki `TodoWrite/TodoRead` araçlarına eşdeğer görev listesi.

**Görev Durumları:** `pending` ⬜ → `in_progress` 🔄 → `completed` ✅

**Özellikler:**
- Thread-safe `RLock` ile korunur
- `todo_write("görev1:::pending|||görev2:::in_progress")` formatı
- Aynı anda birden fazla `in_progress` görev varsa uyarı üretir
- Kalıcı: `data/todo.json` dosyasına kaydedilir

---

### 3.18 `web_ui/` — Web Arayüzü (v2.8.0 — Modüler Yapı)

> **v2.8.0 Mimari Değişikliği:** Daha önce 3.399 satırlık tek `index.html` dosyasında olan HTML + CSS + JavaScript ayrı modüllere bölündü. FastAPI `StaticFiles` middleware ile `/static/*` üzerinden servis edilmektedir.

**Dosya Yapısı:**

| Dosya | Satır | Sorumluluk |
|-------|-------|-----------|
| `index.html` | 436 | HTML iskeleti, modal'lar, script yükleme noktaları |
| `style.css` | 1.547 | CSS custom properties, tema (dark/light), tüm bileşen stilleri |
| `chat.js` | 644 | SSE streaming, mesaj render, kod vurgulama, dosya ekleme |
| `sidebar.js` | 394 | Oturum yönetimi, filtreleme, başlık düzenleme |
| `rag.js` | 131 | RAG belge listesi, ekleme, arama, silme UI |
| `app.js` | 242 | Tema, git bilgisi, model bilgisi, klavye kısayolları, DOMContentLoaded |
| **Toplam** | **3.394** | *(önceki tek dosyayla yakın satır, artık modüler)* |

**Yükleme Sırası (index.html → script tags):**
```html
<script src="/static/chat.js"></script>    <!-- Önce: bağımlılık yok -->
<script src="/static/sidebar.js"></script> <!-- Önce: bağımlılık yok -->
<script src="/static/rag.js"></script>     <!-- Önce: bağımlılık yok -->
<script src="/static/app.js"></script>     <!-- Son: diğer modüllere bağımlı -->
```

**Temel Özellikler:**
- **SSE Chat (`chat.js`):** `EventSource` ile gerçek zamanlı akış, düşünce/araç adımları görselleştirmesi
- **Markdown Render (`chat.js`):** `marked.js` ile kod blokları, tablolar, başlıklar
- **Kod Vurgulama (`chat.js`):** `highlight.js` ile 180+ dil desteği
- **Oturum Yönetimi (`sidebar.js`):** Sol panel sohbet listesi, başlık düzenleme, silme, arama
- **RAG Arayüzü (`rag.js`):** Belge yükleme (dosya/URL), arama, silme
- **Uygulama Başlatma (`app.js`):** Git/model bilgisi yükleme, sağlık şeridi, klavye kısayolları
- **Tema (`style.css`):** CSS `--bg`, `--accent` vb. custom properties ile karanlık/aydınlık mod

---

### 3.19 `github_upload.py` — GitHub Yükleme Aracı (294 satır)

**Amaç:** Projeyi otomatik olarak GitHub'a yükler/yedekler.

**Güvenlik Katmanı (`FORBIDDEN_PATHS`):**
- `.env`, `sessions/`, `chroma_db/`, `__pycache__/`, `.git/`, `logs/`, `models/`
- Binary/UTF-8 okunamayan dosyalar da engellenir

**Özellikler:**
- Git kimlik eksikse interaktif kullanıcı-adı/e-posta alma
- Repo yoksa `git init` + remote ekleme
- Çakışma durumunda `--rebase=false --allow-unrelated-histories -X ours` ile otomatik birleştirme seçeneği
- GitHub Push Protection (secret scanning) hata mesajı algılaması

---

### 3.20 Altyapı Dosyaları

#### `Dockerfile` (101 satır)
- **Çift mod:** `BASE_IMAGE` build-arg ile `python:3.11-slim` (CPU) veya `nvidia/cuda:12.4.1-runtime-ubuntu22.04` (GPU)
- **Bağımlılık:** `environment.yml`'den pip paketleri dinamik olarak çıkarılır
- **Güvenlik:** Non-root kullanıcı (`sidaruser`, uid=10001)
- **Sağlık kontrolü:** Web modunda `/status` endpoint, CLI modunda PID 1 süreç adı kontrol edilir
- **RAG Pre-cache:** `PRECACHE_RAG_MODEL=true` ile `all-MiniLM-L6-v2` build aşamasında indirilir
- **Varsayılan:** `ACCESS_LEVEL=sandbox`

#### `docker-compose.yml` (190 satır)
4 servis tanımı:

| Servis | Mod | CPU Limit | RAM Limit | Port |
|--------|-----|-----------|-----------|------|
| `sidar-ai` | CLI + CPU | 2.0 | 4 GB | — |
| `sidar-gpu` | CLI + GPU | 4.0 | 8 GB | — |
| `sidar-web` | Web + CPU | 2.0 | 4 GB | 7860 |
| `sidar-web-gpu` | Web + GPU | 4.0 | 8 GB | 7861 |

Tüm servisler `/var/run/docker.sock` bağlar (iç REPL sandbox için).

---

## 4. Mimari Değerlendirme

[⬆ İçindekilere Dön](#içindekiler)

### 4.1 Güçlü Yönler

| Alan | Değerlendirme |
|------|---------------|
| **Asenkron Mimari** | `async/await` ve `asyncio.to_thread` tutarlı kullanımı; event loop hiçbir yerde bloklanmıyor |
| **Güvenlik Derinliği** | 3 katmanlı erişim + path traversal + symlink + hassas yol koruması |
| **Yapısal LLM Çıktısı** | Ollama Structured Output ile JSON schema zorlaması; Pydantic doğrulaması |
| **Hata Toleransı** | Her araç try/except; ChromaDB yoksa BM25'e, BM25 yoksa keyword'e fallback |
| **Stream Güvenliği** | UTF-8 incremental decoder ile kırık TCP paketleri güvenle birleştirilir |
| **Bellek Güvenliği** | Fernet şifreleme, karantina mekanizması, RLock ile thread safety |
| **Konfigürasyon** | Tek merkezi Config; hardcoded değer yok; lazy hardware init |
| **Döngü Koruması** | Araç tekrar tespiti ve `_DIRECT_ROUTE_ALLOWED_TOOLS` ile gereksiz LLM çağrısı azaltılmış |

### 4.2 Kısıtlamalar

| Alan | Durum |
|------|-------|
| **Rate Limiting** | In-memory; sunucu yeniden başlarsa sıfırlanır, dağıtık ortamda çalışmaz |
| **Docker Zorunluluğu** | `execute_code` tam işlevsellik için Docker bağlantısı gerektirir |
| **BM25 Bellek** | Tüm belgelerin token'ları RAM'de tutulur; büyük korpuslarda ölçeklenemez |
| **Ollama Timeout** | Varsayılan 30 sn; büyük modellerde ilk yanıt bu süreyi aşabilir |

---

## 5. Güvenlik Analizi

[⬆ İçindekilere Dön](#içindekiler)

### 5.1 Güvenlik Kontrolleri Özeti

| Kontrol | Durum | Konum |
|---------|-------|-------|
| Path traversal engelleme | ✓ Aktif | `security.py:86` |
| Symlink koruması | ✓ Aktif | `security.py:96` |
| Hassas yol engelleme | ✓ Aktif | `security.py:32-37` |
| CORS kısıtlaması | ✓ Yalnızca localhost | `web_server.py:66` |
| Rate limiting | ✓ 3 katman | `web_server.py:83-92` |
| Bellek şifreleme | Opsiyonel (Fernet) | `memory.py:49` |
| Docker kod izolasyonu | Opsiyonel | `code_manager.py:63` |
| GitHub binary engelleme | ✓ Aktif | `github_manager.py:33` |
| Git upload blacklist | ✓ Aktif | `github_upload.py:18` |
| Bilinmeyen erişim seviyesi | ✓ Sandbox'a normalize | `security.py:75` |

### 5.2 Güvenlik Seviyeleri Davranışı

```
RESTRICTED → yalnızca okuma + analiz (yazma/çalıştırma/shell YOK)
SANDBOX    → okuma + /temp yazma + Docker Python REPL
FULL       → tam erişim (shell, git, npm, proje geneli yazma)
```

---

## 6. Test Kapsamı

[⬆ İçindekilere Dön](#içindekiler)

Projede **32 test modülü** bulunmaktadır (toplam ~1.836 satır):

| Test Dosyası | Satır | Kapsam |
|-------------|-------|--------|
| `test_sidar.py` | 1.052 | Genel entegrasyon testleri (en kapsamlı) |
| `test_sidar_improvements.py` | 7 | Ajan iyileştirme testleri |
| `test_auto_handle_improvements.py` | 34 | AutoHandle regex ve mantık testleri |
| `test_agent_init_improvements.py` | 15 | Ajan başlatma testleri |
| `test_agent_subtask.py` | 26 | Alt görev (subtask) testleri |
| `test_parallel_react_improvements.py` | 18 | `parallel` araç ve asyncio.gather testleri |
| `test_llm_client_improvements.py` | 38 | LLM istemci testleri |
| `test_memory_improvements.py` | 46 | Bellek yönetimi testleri |
| `test_rag_improvements.py` | 33 | RAG motor testleri |
| `test_security_improvements.py` | 36 | Güvenlik kontrolü testleri |
| `test_code_manager_improvements.py` | 31 | Kod yöneticisi testleri |
| `test_github_manager_improvements.py` | 30 | GitHub entegrasyon testleri |
| `test_github_upload_improvements.py` | 14 | GitHub yükleme aracı testleri |
| `test_system_health_improvements.py` | 24 | Sağlık monitör testleri |
| `test_web_search_improvements.py` | 36 | Web arama testleri |
| `test_package_info_improvements.py` | 25 | Paket bilgi testleri |
| `test_todo_manager_improvements.py` | 34 | Görev yöneticisi testleri |
| `test_tooling_registry.py` | 34 | `tooling.py` şema ve dispatch testleri |
| `test_config_env_helpers.py` | 30 | Config yardımcı fonksiyon testleri |
| `test_web_server_improvements.py` | 54 | Web sunucu endpoint testleri |
| `test_web_ui_runtime_improvements.py` | 16 | Web UI çalışma zamanı testleri |
| `test_web_ui_security_improvements.py` | 9 | Web UI güvenlik testleri |
| `test_cli_banner.py` | 29 | CLI banner testleri |
| `test_cli_runtime_improvements.py` | 17 | CLI çalışma zamanı testleri |
| `test_main_launcher_improvements.py` | 34 | Başlatıcı testleri |
| `test_dockerfile_runtime_improvements.py` | 22 | Dockerfile çalışma zamanı testleri |
| `test_definitions_prompt.py` | 26 | Sistem istemi testleri |
| `test_core_init_improvements.py` | 14 | `core/__init__.py` export testleri |
| `test_managers_init_improvements.py` | 7 | `managers/__init__.py` export testleri |
| `test_claude_md_improvements.py` | 23 | `CLAUDE.md` içerik testleri |
| `test_sidar_md_improvements.py` | 22 | `SIDAR.md` içerik testleri |

**Test çalıştırma:** `pytest` veya `pytest --cov=.`

> **Uyarı:** Test dosyalarının büyük çoğunluğu unit test niteliğindedir (mock ve stub kullanır). Gerçek LLM, Docker ve ChromaDB gerektiren entegrasyon testleri `test_sidar.py` içinde bulunmakla birlikte sınırlıdır. Bkz. §14.7.

---

## 7. Temel Bağımlılıklar

[⬆ İçindekilere Dön](#içindekiler)

| Paket | Zorunlu | Kullanım Yeri |
|-------|---------|---------------|
| `fastapi` + `uvicorn` | ✓ | Web sunucusu |
| `httpx` | ✓ | LLM + Web arama HTTP istemcisi |
| `python-dotenv` | ✓ | `.env` yükleme |
| `pydantic` | ✓ | ToolCall model doğrulaması |
| `PyGithub` | ✓ | GitHub API |
| `beautifulsoup4` | ✓ | HTML temizleme |
| `packaging` | ✓ | Sürüm karşılaştırması |
| `duckduckgo-search` | Opsiyonel | DDG web araması |
| `google-generativeai` | Opsiyonel | Gemini LLM |
| `chromadb` | Opsiyonel | Vektör RAG |
| `sentence-transformers` | Opsiyonel | GPU embedding |
| `rank_bm25` | Opsiyonel | BM25 RAG |
| `torch` | Opsiyonel | GPU kontrolü + embedding |
| `psutil` | Opsiyonel | CPU/RAM izleme |
| `pynvml` | Opsiyonel | GPU sıcaklık/kullanım |
| `cryptography` | Opsiyonel | Fernet bellek şifreleme |
| `docker` | Opsiyonel | REPL sandbox |

---

## 8. Kod Satır Sayısı Özeti

[⬆ İçindekilere Dön](#içindekiler)

| Dosya | Satır | Not |
|-------|-------|-----|
| `web_ui/style.css` | 1.547 | v2.8.0 — index.html'den ayrıldı |
| `agent/sidar_agent.py` | 1.463 | v2.9.0 — RAG araçlarına session_id eklendi |
| `core/rag.py` | 777 | v2.9.0 — RRF + izolasyon (refaktör ile 74 satır küçüldü) |
| `web_server.py` | 801 | v2.9.0 — RAG endpoint'lerine session_id eklendi |
| `managers/code_manager.py` | 746 | |
| `web_ui/chat.js` | 644 | v2.8.0 — index.html'den ayrıldı |
| `agent/auto_handle.py` | 601 | |
| `managers/github_manager.py` | 560 | |
| `core/llm_client.py` | 513 | |
| `config.py` | 520 | v2.9.0 — MEMORY_SUMMARY_KEEP_LAST eklendi |
| `managers/system_health.py` | 420 | |
| `managers/todo_manager.py` | 380 | |
| `web_ui/sidebar.js` | 394 | v2.8.0 — index.html'den ayrıldı |
| `core/memory.py` | 394 | v2.9.0 — Sliding window özetleme eklendi |
| `managers/web_search.py` | 379 | v2.8.0 — AsyncDDGS + timeout eklendi |
| `managers/package_info.py` | 314 | |
| `github_upload.py` | 294 | |
| `main.py` | 332 | |
| `web_ui/app.js` | 242 | v2.8.0 — index.html'den ayrıldı |
| `cli.py` | 275 | |
| `agent/tooling.py` | 189 | |
| `web_ui/rag.js` | 131 | v2.8.0 — index.html'den ayrıldı |
| `agent/definitions.py` | 164 | |
| `web_ui/index.html` | 436 | v2.8.0 — 3.399'dan 436'ya indirildi |
| `core/__init__.py` | 27 | |
| `managers/__init__.py` | 21 | |
| `agent/__init__.py` | 19 | |
| **Toplam (Python + JS/CSS/HTML)** | **~11.592** | v2.9.0 güncel |
| **Toplam (Python kaynak)** | **~8.197** | JS/CSS/HTML hariç |

---

## 9. Modül Bağımlılık Haritası

[⬆ İçindekilere Dön](#içindekiler)

Aşağıdaki tablo her modülün hangi iç modülleri import ettiğini gösterir. Okun yönü bağımlılık yönüdür.

```
config.py          ←── (bağımlılık YOK — temel taş)

core/llm_client.py ←── config.py
core/memory.py     ←── config.py
core/rag.py        ←── config.py

managers/security.py      ←── config.py
managers/code_manager.py  ←── managers/security.py, config.py
managers/github_manager.py←── (yalnızca dış: PyGithub)
managers/system_health.py ←── config.py
managers/web_search.py    ←── config.py
managers/package_info.py  ←── (yalnızca dış: httpx, packaging)
managers/todo_manager.py  ←── config.py

agent/definitions.py  ←── (bağımlılık YOK — salt metin sabiti)
agent/tooling.py      ←── pydantic (dış) — iç modül bağımlılığı YOK
agent/auto_handle.py  ←── managers/*, core/memory.py, core/rag.py
agent/sidar_agent.py  ←── config.py, core/*, managers/*, agent/auto_handle.py,
                            agent/definitions.py, agent/tooling.py

cli.py         ←── config.py, agent/sidar_agent.py
web_server.py  ←── config.py, agent/sidar_agent.py, core/*, managers/*
main.py        ←── config.py (DummyConfig fallback'i de var)
github_upload.py ←── (bağımlılık YOK — bağımsız araç)
```

**Döngüsel bağımlılık:** Tespit edilmedi. `config.py` bağımlılık ağacının kökü; hiçbir iç modülü import etmez.

---

## 10. Veri Akış Diyagramı

[⬆ İçindekilere Dön](#içindekiler)

### 10.1 Bir Chat Mesajının Ömrü

```
[Kullanıcı]
    │ metin gönderir
    ▼
[Web: POST /chat]  veya  [CLI: _interactive_loop_async]
    │
    ▼
[SidarAgent.respond(text, stream=True)]
    │
    ├─► [ConversationMemory.add("user", text)]
    │         └─► disk: data/sessions/<id>.json  (şifreli opsiyonel)
    │
    ├─► [AutoHandle.handle(text)]
    │         ├─► regex eşleşirse → doğrudan yanıt (LLM çağrısı YOK)
    │         └─► eşleşmezse → (False, "")
    │
    ├─► [SIDAR.md + CLAUDE.md okuma] (mtime cache'den)
    │
    └─► [LLMClient.chat(messages, json_mode=True)]  ← ReAct döngüsü başlar
              │
              ▼
        {thought, tool, argument}  ← Pydantic doğrulama
              │
              ├─► tool == "final_answer"  → akış → kullanıcı
              │
              └─► diğer araç
                      │
                      ▼
                  [_tools[tool](argument)]
                      │
                      ├── read_file   → CodeManager → SecurityManager → disk
                      ├── web_search  → WebSearchManager → httpx → Tavily/Google/DDG
                      ├── docs_search → DocumentStore → ChromaDB / BM25 / Keyword
                      ├── github_*    → GitHubManager → PyGithub → GitHub API
                      ├── execute_code→ CodeManager → Docker → python:3.11-alpine
                      └── health      → SystemHealthManager → psutil / pynvml / torch
                              │
                              ▼
                        sonuç belleğe eklenir
                              │
                              ▼
                        LLMClient.chat (bir sonraki adım)
                              │
                        [MAX_REACT_STEPS'e ulaşıldı?]
                              ├── HAYIR → döngü devam
                              └── EVET  → zorla final_answer
```

### 10.2 Bellek Yazma Yolu

```
add(role, content)
    → _save_interval_seconds (0.5 sn) debounce
        → JSON serileştirme
            → [MEMORY_ENCRYPTION_KEY varsa] Fernet.encrypt()
                → data/sessions/<uuid>.json
```

### 10.3 RAG Belge Ekleme Yolu

```
add_document(title, content, source)
    → _chunk_text()  ← recursive chunking
        → _write_lock alınır
            → store_dir/<doc_id>.txt  (tam metin)
            → index.json güncellenir
            → BM25 cache güncellenir (inkremental)
            → ChromaDB.upsert(chunks)  ← cosine space
        → _write_lock bırakılır
```

---

## 11. Mevcut Sorunlar ve Teknik Borç

[⬆ İçindekilere Dön](#içindekiler)

> **Not:** v2.7.0 ve v2.8.0 sürümlerinde çözülen tüm yüksek ve orta öncelikli sorunların listesi için [CHANGELOG.md](./CHANGELOG.md) dosyasına bakın.

**v2.8.0 itibarıyla tüm teknik borçlar kapatılmıştır. Aşağıdaki tablo doğrulama sonuçlarını içerir:**

| # | Dosya | Sorun | Çözüm (Satır Satır Doğrulama) | Durum |
|---|-------|-------|-------------------------------|-------|
| 10 | `managers/web_search.py` | DDG senkron API event loop'u bloklıyor; versiyon pinlemesi eksik | **`environment.yml:61`** → `duckduckgo-search~=6.2.13` (pinlendi). **`web_search.py:229`** → `hasattr(duckduckgo_search, "AsyncDDGS")` ile dinamik yol seçimi. **`web_search.py:242,253`** → her iki yol `asyncio.wait_for(timeout=FETCH_TIMEOUT)` içinde. **`web_search.py:273`** → `except asyncio.TimeoutError` spesifik olarak `except Exception`'dan önce. | ✅ **Çözüldü** (v2.8.0) |
| 11 | `web_ui/index.html` | 3.399 satır tek dosya; JS/CSS/HTML ayrılmamış; test edilebilirlik düşük | **`index.html`** → 436 satıra indirildi (iskelet + modal'lar). **`web_ui/style.css`** → 1.547 satır CSS. **`web_ui/chat.js`** → 644 satır SSE + render. **`web_ui/sidebar.js`** → 394 satır oturum yönetimi. **`web_ui/rag.js`** → 131 satır RAG UI. **`web_ui/app.js`** → 242 satır init + klavye. **`web_server.py:77`** → `app.mount("/static", StaticFiles(directory=web_ui_dir))` | ✅ **Çözüldü** (v2.8.0) |

## 12. `.env` Tam Değişken Referansı

[⬆ İçindekilere Dön](#içindekiler)

Aşağıdaki tablo projenin desteklediği tüm ortam değişkenlerini kapsar.

### 12.1 AI Sağlayıcı

| Değişken | Varsayılan | Açıklama |
|----------|-----------|----------|
| `AI_PROVIDER` | `ollama` | `ollama` veya `gemini` |
| `GEMINI_API_KEY` | `""` | Gemini modu için zorunlu |
| `GEMINI_MODEL` | `gemini-2.5-flash` | Kullanılacak Gemini model adı |
| `OLLAMA_URL` | `http://localhost:11434/api` | Ollama API adresi |
| `OLLAMA_TIMEOUT` | `30` | Ollama istek zaman aşımı (sn) |
| `CODING_MODEL` | `qwen2.5-coder:7b` | Ollama — kod görevleri modeli |
| `TEXT_MODEL` | `gemma2:9b` | Ollama — metin görevleri modeli |

### 12.2 Güvenlik ve Erişim

| Değişken | Varsayılan | Açıklama |
|----------|-----------|----------|
| `ACCESS_LEVEL` | `full` | `restricted` / `sandbox` / `full` |
| `MEMORY_ENCRYPTION_KEY` | `""` | Fernet anahtarı — boşsa şifreleme kapalı |

### 12.3 GPU / Donanım

| Değişken | Varsayılan | Açıklama |
|----------|-----------|----------|
| `USE_GPU` | `true` | GPU kullanımını açar/kapar |
| `GPU_DEVICE` | `0` | Çoklu GPU'da hedef cihaz indeksi |
| `GPU_MEMORY_FRACTION` | `0.8` | VRAM fraksiyonu (0.1–1.0) |
| `GPU_MIXED_PRECISION` | `false` | FP16 mixed precision |
| `MULTI_GPU` | `false` | Dağıtık çoklu GPU modu |

### 12.4 Web Arayüzü

| Değişken | Varsayılan | Açıklama |
|----------|-----------|----------|
| `WEB_HOST` | `0.0.0.0` | Web sunucu bind adresi |
| `WEB_PORT` | `7860` | CPU mod web portu |
| `WEB_GPU_PORT` | `7861` | GPU mod web portu |

### 12.5 Web Arama

| Değişken | Varsayılan | Açıklama |
|----------|-----------|----------|
| `SEARCH_ENGINE` | `auto` | `auto` / `tavily` / `google` / `duckduckgo` |
| `TAVILY_API_KEY` | `""` | Tavily API anahtarı |
| `GOOGLE_SEARCH_API_KEY` | `""` | Google Custom Search API anahtarı |
| `GOOGLE_SEARCH_CX` | `""` | Google Custom Search Engine ID |
| `WEB_SEARCH_MAX_RESULTS` | `5` | Maksimum arama sonucu sayısı |
| `WEB_FETCH_TIMEOUT` | `15` | URL çekme zaman aşımı (sn) |
| `WEB_SCRAPE_MAX_CHARS` | `12000` | URL içerik karakter limiti |

### 12.6 RAG

| Değişken | Varsayılan | Açıklama |
|----------|-----------|----------|
| `RAG_DIR` | `data/rag` | Belge deposu dizini |
| `RAG_TOP_K` | `3` | Arama sonucu sayısı |
| `RAG_CHUNK_SIZE` | `1000` | Chunking karakter büyüklüğü |
| `RAG_CHUNK_OVERLAP` | `200` | Chunk örtüşme miktarı |
| `RAG_FILE_THRESHOLD` | `20000` | RAG deposuna ekleme önerisi eşiği (karakter) |

### 12.7 Hafıza ve ReAct

| Değişken | Varsayılan | Açıklama |
|----------|-----------|----------|
| `MAX_MEMORY_TURNS` | `20` | Bellekte tutulan max konuşma turu |
| `MEMORY_SUMMARY_KEEP_LAST` | `4` | Özetleme sırasında tam korunacak son mesaj sayısı (sliding window) |
| `MAX_REACT_STEPS` | `10` | ReAct döngüsü max adım sayısı |
| `REACT_TIMEOUT` | `60` | ReAct tek adım zaman aşımı (sn) |
| `SUBTASK_MAX_STEPS` | `5` | Alt ajan max adım sayısı |
| `AUTO_HANDLE_TIMEOUT` | `12` | AutoHandle araç zaman aşımı (sn) |

### 12.8 Loglama

| Değişken | Varsayılan | Açıklama |
|----------|-----------|----------|
| `LOG_LEVEL` | `INFO` | `DEBUG` / `INFO` / `WARNING` / `ERROR` |
| `LOG_FILE` | `logs/sidar_system.log` | Log dosya yolu |
| `LOG_MAX_BYTES` | `10485760` | Log dosya maksimum boyutu (10 MB) |
| `LOG_BACKUP_COUNT` | `5` | Tutulan log yedek sayısı |
| `DEBUG_MODE` | `false` | Açıksa Config özeti konsola yazdırılır |

### 12.9 Rate Limiting

| Değişken | Varsayılan | Açıklama |
|----------|-----------|----------|
| `RATE_LIMIT_WINDOW` | `60` | Pencere süresi (sn) |
| `RATE_LIMIT_CHAT` | `20` | Chat endpoint limit (istek/pencere) |
| `RATE_LIMIT_MUTATIONS` | `60` | Yazma endpoint limit |
| `RATE_LIMIT_GET_IO` | `30` | Okuma endpoint limit |

### 12.10 Çeşitli

| Değişken | Varsayılan | Açıklama |
|----------|-----------|----------|
| `RESPONSE_LANGUAGE` | `tr` | LLM yanıt dili |
| `HF_TOKEN` | `""` | HuggingFace token (özel modeller) |
| `HF_HUB_OFFLINE` | `false` | HF Hub çevrimdışı mod |
| `GITHUB_TOKEN` | `""` | GitHub API token |
| `GITHUB_REPO` | `""` | Varsayılan GitHub repo (`owner/repo`) |
| `DOCKER_PYTHON_IMAGE` | `python:3.11-alpine` | REPL sandbox Docker imajı |
| `DOCKER_EXEC_TIMEOUT` | `10` | Docker REPL zaman aşımı (sn) |
| `PACKAGE_INFO_TIMEOUT` | `12` | Paket bilgi HTTP zaman aşımı (sn) |
| `PACKAGE_INFO_CACHE_TTL` | `1800` | Paket bilgi cache süresi (sn) |

---

## 13. Olası İyileştirmeler

[⬆ İçindekilere Dön](#içindekiler)

> **Not:** v2.7.0 öncesi tespit edilen tüm Yüksek ve Orta öncelikli iyileştirmeler (`rag.py`, `sidar_agent.py`, `docker-compose.yml`, `memory.py` vb.) başarıyla tamamlanmış ve kod tabanına entegre edilmiştir. Çözülen sorunlar tablodan kaldırılmıştır.

İleriki aşamalar (v2.8+) için kod tabanından çıkan ve planlanan mimari iyileştirme önerileri:

| Öncelik | Alan | Öneri |
|---------|------|-------|
| Düşük | `managers/web_search.py` | DuckDuckGo senkron API'si (`DDGS`) asenkrona çevrilmeli veya versiyonu sabitlenmeli. |
| Düşük | `web_ui/index.html` | 3.399 satırlık dosya modülarize edilerek JS ve CSS ayrı dosyalara bölünmeli (`app.js`, `style.css`). |

---

## 14. Sonraki Versiyon İçin Geliştirme Önerileri (v2.8+)

[⬆ İçindekilere Dön](#içindekiler)

Bu bölüm, mevcut kodun sınırlarından ve mimari boşluklarından çıkarılan somut geliştirme hedeflerini kapsar. Her madde bağımsız bir özellik olarak ele alınabilir.

---

### 14.1 Çekirdek Mimari

> **Durum Güncellemesi (v2.7.0):** Bu başlık altında yer alan önceki kritik maddeler tamamlanmıştır. Ayrıntılı uygulama özeti için [CHANGELOG.md](./CHANGELOG.md) dosyasına bakın.

#### 14.1.1 Kalıcı Rate Limiting
**Güncel durum:** ✅ `web_server.py` tarafında `TTLCache(maxsize=10000, ttl=cfg.RATE_LIMIT_WINDOW)` kullanıma alınmıştır.
**Not (v2.8+):** İhtiyaç halinde dağıtık ortamlar için Redis tabanlı merkezi rate limiter değerlendirilebilir.

#### 14.1.2 Gerçek Token Sayacı
**Güncel durum:** ✅ `core/memory.py` içinde `tiktoken` entegrasyonu aktif; paket yoksa güvenli fallback korunuyor.
**Not (v2.8+):** Model-spesifik tokenizer seçimi (`TOKENIZER_MODEL`) opsiyonel olarak eklenebilir.

#### 14.1.3 Talimat Cache Koruması
**Güncel durum:** ✅ `agent/sidar_agent.py` içinde `_instructions_cache` / `_instructions_mtimes` akışı `threading.Lock` ile korunuyor.
**Not:** Bu kod yolu senkron dosya I/O yaptığı için mevcut `threading.Lock` seçimi mimari olarak uygundur.

#### 14.1.4 Thread-Safe Chunking
**Güncel durum:** ✅ `core/rag.py` içinde chunking parametreleri yerel değişkenlerle yönetiliyor; `self` üstünde geçici mutasyon yok.
**Not:** Zorunlu bölme adımında `step = max(1, size - overlap)` koruması ile `ZeroDivisionError` riski giderilmiştir.

---

### 14.2 LLM ve Ajan Katmanı (✅ Tamamı Çözüldü - v2.8.0)

> **Not:** Bu bölümdeki tüm mimari hedefler (Çoklu LLM Soyutlaması, Araçların Pydantic Şemalarıyla Dışsallaştırılması ve Asenkron Paralel ReAct adımları) v2.8.0 güncellemesi ile başarıyla tamamlanmış ve `CHANGELOG.md` dosyasına eklenmiştir.

[⬆ İçindekilere Dön](#içindekiler)

---
### 14.3 RAG ve Bellek

#### 14.3.1 Hibrit Sıralama (RRF)
**Güncel durum:** ✅ **v2.9.0'da tamamlandı.**

`_rrf_search()` metodu eklendi. `auto` modda her iki motor (ChromaDB + BM25) mevcutsa RRF öncelikli çalışır:
- `_fetch_chroma()` → session filtreli ChromaDB sonuçları
- `_fetch_bm25()` → session filtreli BM25 sonuçları
- RRF puanı: `score(doc) = Σ 1/(k+rank)`, k=60 (TREC standardı)
- Her iki motordan gelen sonuçlar birleştirilip en iyi `top_k` döndürülür

#### 14.3.2 BM25 Corpus Ölçeklenebilirliği
**Güncel durum:** ✅ **Tamamlandı (SQLite FTS5, disk tabanlı BM25).**

`rank_bm25` tabanlı RAM içi indeks kaldırıldı ve BM25 katmanı SQLite FTS5'e taşındı:
- `_init_fts()` ile `bm25_fts.db` ve `bm25_index` (FTS5) sanal tablosu başlatılır
- Belge ekleme/silme işlemleri FTS tablosuna senkron `INSERT/DELETE` ile işlenir
- `_fetch_bm25()` artık `MATCH` + `bm25(...)` ile diskten arama yapar
- Eski in-memory cache/prebuild akışı kaldırılmıştır

#### 14.3.3 Çok Oturumlu RAG İzolasyonu
**Güncel durum:** ✅ **v2.9.0'da tamamlandı.**

`session_id` metadata alanı tüm RAG metodlarına eklendi:
- ChromaDB `where={"session_id": session_id}` filtresi
- BM25 Python düzeyinde `valid_doc_ids` seti ile filtreleme
- Keyword arama `meta.get("session_id")` kontrolü
- `delete_document()` izolasyon yetki kontrolü
- `sidar_agent.py` tüm RAG araçlarında `self.memory.active_session_id` geçiriliyor
- `web_server.py` tüm RAG endpoint'lerinde `agent.memory.active_session_id` geçiriliyor

#### 14.3.4 Bellek Özetleme Stratejisi Seçimi
**Güncel durum:** ✅ **v2.9.0'da tamamlandı.**

`apply_summary()` kayan pencere (sliding window) ile güncellendi:
- Son `keep_last` (varsayılan: 4) mesaj tam korunur
- Eski mesajlar özet çiftiyle değiştirilir: `[özet_user, özet_assistant] + son_mesajlar`
- `MEMORY_SUMMARY_KEEP_LAST` env değişkeniyle yapılandırılabilir (bkz. §12.7)

---

### 14.4 Web Arayüzü ve API

#### 14.4.1 Web UI Modülarizasyonu
**Güncel durum:** ✅ **v2.8.0'da tamamlandı.**

Önerilen yapı tam olarak uygulandı:
```
web_ui/
├── index.html    (436 satır — iskelet + modal'lar)
├── app.js        (242 satır — init, tema, git bilgisi, klavye kısayolları)
├── chat.js       (644 satır — SSE streaming, mesaj render, kod vurgulama)
├── sidebar.js    (394 satır — oturum yönetimi, filtreleme)
├── rag.js        (131 satır — RAG belge/arama UI)
└── style.css    (1.547 satır — tüm CSS, tema değişkenleri)
```
`web_server.py:77`'de `app.mount("/static", StaticFiles(directory=web_ui_dir))` ile servis edilmektedir.

#### 14.4.2 WebSocket Desteği
**Mevcut durum:** SSE (Server-Sent Events) tek yönlü akış; mesaj iptali için ayrı endpoint gerekiyor.
**Öneri:** FastAPI WebSocket ile çift yönlü kanal. Kullanıcı mesajı iptal edebilir; sunucu anlık durum güncellemesi gönderebilir.

#### 14.4.3 OpenAPI Şema Belgelendirmesi
**Mevcut durum:** FastAPI otomatik `/docs` oluşturuyor ancak endpoint açıklamaları eksik.
**Öneri:** Her endpoint için `summary`, `description`, `response_model` ve `responses` parametrelerinin doldurulması. Harici entegrasyon kolaylaşır.

#### 14.4.4 Kimlik Doğrulama
**Güncel durum:** ✅ **Tamamlandı (API_KEY tabanlı HTTP Basic Auth).**

Web katmanında opsiyonel kimlik doğrulama aktiftir:
- `config.py` içinde `API_KEY` tanımlıdır
- `web_server.py` içinde `basic_auth_middleware` ile tüm endpoint'ler korunur
- `API_KEY` boş ise auth bypass, dolu ise Basic Auth zorunlu
- `docker-compose.yml` web servislerine `API_KEY` environment olarak aktarılır

---

### 14.5 GitHub Entegrasyonu

#### 14.5.1 Webhook Desteği
**Mevcut durum:** GitHub durumu yalnızca istek üzerine sorgulanıyor (pull model).
**Öneri:** GitHub Webhook alıcısı eklenebilir (push, PR, issue eventi). Yeni commit'te otomatik RAG güncelleme veya bildirim.

#### 14.5.2 Issue Yönetimi
**Güncel durum:** ✅ **Tamamlandı.**

GitHub issue yaşam döngüsü araçları eklendi:
- `list_issues`, `create_issue`, `comment_issue`, `close_issue` (`managers/github_manager.py`)
- Ajan araçları: `github_list_issues`, `github_create_issue`, `github_comment_issue`, `github_close_issue`
- `agent/tooling.py` içinde ilgili Pydantic şemaları ve dispatch kayıtları mevcut

#### 14.5.3 Diff Analizi
**Güncel durum:** ✅ **Tamamlandı.**

PR inceleme için unified diff erişimi eklendi:
- `get_pull_request_diff(number)` ile dosya bazlı patch metni çekilir
- Ajan aracı `github_pr_diff` üzerinden LLM'e doğrudan diff içeriği verilebilir
- Böylece güvenlik/kod kalite odaklı otomatik review senaryoları mümkün hale gelmiştir

---

### 14.6 Güvenlik ve İzleme

#### 14.6.1 Docker Socket Riski Azaltma
**Güncel durum:** ✅ **Tamamlandı.**

`docker-compose.yml` içinde Docker socket mount yalnızca CLI/REPL servislerinde bırakıldı.
Web servislerinden (`sidar-web`, `sidar-web-gpu`) kaldırılarak container escape riski azaltıldı.

#### 14.6.2 Denetim Logu (Audit Log)
**Güncel durum:** ✅ **Tamamlandı.**

`SidarAgent._execute_tool` merkezi noktasında tüm araç çağrıları JSONL olarak loglanır:
- Hedef dosya: `logs/audit.jsonl`
- Alanlar: `timestamp`, `time_human`, `session_id`, `tool`, `argument`, `access_level`, `success`
- Uzun argümanlar 2000 karaktere kırpılarak disk şişmesi önlenir

#### 14.6.3 Sandbox Çıktı Boyutu Limiti
**Güncel durum:** ✅ **Tamamlandı.**

`CodeManager` içine `max_output_chars=10000` limiti eklendi:
- Docker sandbox (`execute_code`) çıktısı kırpılır
- Lokal subprocess (`execute_code_local`) çıktısı kırpılır
- Shell komutu (`run_shell`) birleşik çıktısı kırpılır
- Limit aşımlarında çıktı sonuna açık bir "ÇIKTI KIRPILDI" notu eklenir

#### 14.6.4 Güvenlik Seviyesi Geçiş Logu
**Mevcut durum:** `set_provider_mode()` ve erişim seviyesi değişiklikleri loglanıyor ancak oturum bazında takip yok.
**Öneri:** Seviye değişikliklerini oturum belleğine de yazmak; `[GÜVENLIK] Erişim seviyesi full → sandbox olarak değiştirildi` şeklinde izlenebilir.

---

### 14.7 Test ve Kalite

#### 14.7.1 Entegrasyon Test Altyapısı
**Mevcut durum:** 32 test modülü var (~1.836 satır) ancak çoğu unit test; gerçek LLM ve Docker gerektiren testler yok.
**Öneri:** `pytest-asyncio` ile asenkron test; `httpx.AsyncClient` ile web API testleri; `testcontainers-python` ile geçici ChromaDB ve Docker ortamı.

#### 14.7.2 Test Coverage Hedefi
**Mevcut durum:** Kapsam hedefi tanımlanmamış.
**Öneri:** CI'da `pytest --cov=. --cov-fail-under=70` eşiği. `security.py`, `memory.py`, `rag.py` %80+ hedef.

#### 14.7.3 Linting ve Tip Kontrolü
**Mevcut durum:** Tip anotasyonları var ancak `mypy` / `ruff` konfigürasyonu yok.
**Öneri:** `pyproject.toml` içine `ruff` (format + lint) ve `mypy --strict` konfigürasyonu. Pre-commit hook ile her commit'te otomatik çalıştırma.

#### 14.7.4 Performans Benchmark
**Mevcut durum:** RAG arama süresi, LLM ilk token gecikmesi (TTFT) ölçülmüyor.
**Öneri:** `pytest-benchmark` ile kritik yollar için baseline ölçümü: ChromaDB sorgu < 200ms, BM25 sorgu < 50ms, AutoHandle regex < 5ms.

#### 14.7.5 Otonom TODO/FIXME Tarama
**Güncel durum:** ✅ **Tamamlandı.**

Ajan artık proje kaynak kodunu tarayarak TODO/FIXME etiketlerini otomatik bulabilir:
- `TodoManager.scan_project_todos(...)` ile dizin + uzantı bazlı tarama
- `scan_project_todos` aracı `agent/tooling.py` üzerinden şemalı olarak erişilebilir
- Ajan aracı `_tool_scan_project_todos` disk taramasını `asyncio.to_thread` ile bloklamadan çalıştırır

---

### 14.8 Operasyon ve Dağıtım

#### 14.8.1 Sağlık Endpoint Genişletmesi
**Güncel durum:** ✅ **Tamamlandı.**

Yapısal sağlık özeti ve probe endpoint'i eklendi:
- `SystemHealthManager.get_health_summary()` JSON özet döndürür
- `GET /health` endpoint'i `uptime_seconds` alanı ile birlikte durum raporu üretir
- `AI_PROVIDER=ollama` ve Ollama erişilemezse endpoint `503` + `status=degraded` döndürür

#### 14.8.2 Çevre Başına Konfigürasyon
**Mevcut durum:** Tek `.env` dosyası.
**Öneri:** `.env.development`, `.env.production`, `.env.test` desteği; `python-dotenv`'in `dotenv_values` zinciri ile birleştirme. Docker build-arg ile `ENV_FILE` override.

#### 14.8.3 Gözlemlenebilirlik (Observability)
**Mevcut durum:** Yalnızca dosya logu var.
**Öneri:** OpenTelemetry ile trace ID; her LLM çağrısı bir span olarak izlenir. Grafana/Jaeger entegrasyonu isteğe bağlı; telemetry sadece `OTEL_EXPORTER_ENDPOINT` ayarlıysa aktif olur.

#### 14.8.4 Model Önbellekleme ve Soğuk Start
**Mevcut durum:** ChromaDB embedding modeli ilk belgede yükleniyor; soğuk start gecikmesi olabilir.
**Not:** BM25 artık SQLite FTS5 disk tabanlı olduğu için `prebuild_bm25_index()` akışı kaldırılmıştır.
**Öneri:** `startup` event'inde yalnızca gerekli model/vektör bağlantılarının ısıtılması (prewarm) değerlendirilebilir.

---

### 14.9 Öncelik Durumu (Güncel — v2.9.0)

> **Durum Notu:** Güvenlik, RAG ölçeklenebilirliği, GitHub issue/diff ve sağlık endpoint’i odaklı yüksek/orta öncelikli maddeler tamamlandı. Kalan açık maddeler düşük etki / opsiyonel kategorisindedir.

| Sıra | Özellik | Etki | Çaba | Durum |
|------|---------|------|------|-------|
| — | §14.1.1–14.1.4 (tiktoken, cache lock, RRF thread-safe, rate limiting) | Yüksek | Düşük–Orta | ✅ **v2.7.0** |
| — | DuckDuckGo güvenliği, Web UI modülarizasyonu (§10, §11, §14.4.1) | Yüksek | Düşük–Yüksek | ✅ **v2.8.0** |
| — | RRF sıralama (§14.3.1) | Orta | Orta | ✅ **v2.9.0** |
| — | RAG oturum izolasyonu (§14.3.3) | Orta | Orta | ✅ **v2.9.0** |
| — | Sliding window özetleme (§14.3.4) | Orta | Düşük | ✅ **v2.9.0** |
| — | web_server.py RAG session_id bug (kritik düzeltme) | Yüksek | Düşük | ✅ **v2.9.0 audit** |
| 1 | Docker socket riski azaltma (§14.6.1) | Yüksek | Düşük | ✅ Tamamlandı |
| 2 | Sandbox çıktı boyutu limiti (§14.6.3) | Orta | Düşük | ✅ Tamamlandı |
| 3 | API key auth (§14.4.4) | Orta | Orta | ✅ Tamamlandı |
| 4 | Issue yönetimi GitHub (§14.5.2) | Orta | Yüksek | ✅ Tamamlandı |
| 5 | BM25 corpus ölçeklenebilirliği (§14.3.2) | Orta | Yüksek | ✅ Tamamlandı |
| 6 | Denetim logu audit.jsonl (§14.6.2) | Düşük | Düşük | ✅ Tamamlandı |
| 7 | PR diff analizi (§14.5.3) | Orta | Orta | ✅ Tamamlandı |
| 8 | Sağlık endpoint JSON (§14.8.1) | Orta | Düşük | ✅ Tamamlandı |
| 9 | OpenTelemetry gözlemlenebilirlik (§14.8.3) | Düşük | Yüksek | ⏳ Açık |
| 10 | Kalıcı rate limiting — Redis (§14.1.1 ek) | Düşük | Orta | ⏳ Opsiyonel |

---

### 14.10 Rapor Güncelleme Politikası (Önerilen Süreç)

Bu proje için en sağlıklı yaklaşım, **her anlamlı geliştirme adımından hemen sonra raporu güncellemek** olacaktır.

Önerilen pratik:
- Kod değişikliği tamamlanınca ilgili alt başlıkta `Mevcut durum` → `Güncel durum` güncellemesi yapılır.
- Değişiklik bir yol haritası maddesini kapatıyorsa, §14.9 öncelik tablosundaki durum da aynı commit içinde güncellenir.
- Mümkünse her PR'da kısa bir “Rapor Etkisi” notu bulunur (hangi bölüm/başlık güncellendi).
- Küçük refactor/format değişikliklerinde rapor güncellemesi zorunlu değildir; ancak davranış, güvenlik, API, performans veya mimari değiştiyse rapor güncellemesi zorunlu kabul edilir.

Bu disiplin sayesinde rapor, geçmişi anlatan bir belge olmaktan çıkıp **canlı operasyonel durum panosu** gibi çalışır.

## 15. Özellik-Gereksinim Matrisi

[⬆ İçindekilere Dön](#içindekiler)

Hangi özelliği kullanmak için hangi paket veya dış servisin kurulu/yapılandırılmış olması gerektiğini gösterir.

### 15.1 Çekirdek Özellikler (Her Zaman Zorunlu)

| Özellik | Zorunlu Paket / Servis | Zorunlu `.env` |
|---------|----------------------|----------------|
| CLI arayüzü | Python ≥ 3.10, `httpx`, `python-dotenv` | — |
| Web arayüzü | `fastapi`, `uvicorn`, `httpx` | `WEB_PORT` (opsiyonel) |
| Ollama LLM | `httpx` + **çalışan `ollama serve`** | `OLLAMA_URL`, `CODING_MODEL` |
| Gemini LLM | `google-generativeai` | `GEMINI_API_KEY`, `GEMINI_MODEL` |
| Konuşma belleği | — (stdlib: `json`, `uuid`) | `MAX_MEMORY_TURNS` (opsiyonel) |
| Bellek şifreleme | `cryptography` | `MEMORY_ENCRYPTION_KEY` |
| GitHub entegrasyonu | `PyGithub` | `GITHUB_TOKEN`, `GITHUB_REPO` |
| Proje denetimi (`audit`) | — (stdlib: `ast`, `pathlib`) | — |

### 15.2 Arama ve Web

| Özellik | Zorunlu Paket / Servis | Zorunlu `.env` |
|---------|----------------------|----------------|
| Tavily web arama | `httpx` | `TAVILY_API_KEY` |
| Google Custom Search | `httpx` | `GOOGLE_SEARCH_API_KEY`, `GOOGLE_SEARCH_CX` |
| DuckDuckGo (fallback) | `duckduckgo-search` | — |
| URL içerik çekme | `httpx`, `beautifulsoup4` | `WEB_FETCH_TIMEOUT` (opsiyonel) |
| PyPI sorgulama | `httpx`, `packaging` | — |
| npm sorgulama | `httpx` | — |

### 15.3 RAG (Belge Deposu)

| Özellik | Zorunlu Paket / Servis | Zorunlu `.env` |
|---------|----------------------|----------------|
| Keyword arama (fallback) | — (stdlib) | — |
| BM25 arama | `rank_bm25` | — |
| Vektör arama (CPU) | `chromadb` | `RAG_DIR` (opsiyonel) |
| Vektör arama (GPU) | `chromadb`, `sentence-transformers`, `torch` (CUDA) | `USE_GPU=true`, `GPU_DEVICE` |
| GPU FP16 embedding | yukarıdaki + `torch.amp` | `GPU_MIXED_PRECISION=true` |
| HuggingFace model cache | `sentence-transformers` | `HF_TOKEN` (opsiyonel) |
| HF çevrimdışı mod | — | `HF_HUB_OFFLINE=true` |

### 15.4 Sistem İzleme ve GPU

| Özellik | Zorunlu Paket / Servis | Zorunlu `.env` |
|---------|----------------------|----------------|
| CPU/RAM izleme | `psutil` | — |
| CUDA tespiti | `torch` | — |
| GPU sıcaklık / kullanım | `pynvml` | — |
| VRAM fraksiyonu ayarı | `torch` | `GPU_MEMORY_FRACTION` |
| Mixed precision | `torch` ≥ 1.6 | `GPU_MIXED_PRECISION=true` |
| WSL2 GPU erişimi | Windows NVIDIA sürücüsü + CUDA 12.x wheel | — |

### 15.5 Kod Yürütme

| Özellik | Zorunlu Paket / Servis | Zorunlu `.env` |
|---------|----------------------|----------------|
| Docker REPL (izolasyon) | `docker` SDK + **çalışan Docker daemon** | `DOCKER_PYTHON_IMAGE` (opsiyonel) |
| Subprocess REPL (fallback) | — (stdlib) | `ACCESS_LEVEL=sandbox\|full` |
| Shell komutu (`run_shell`) | — (stdlib) | `ACCESS_LEVEL=full` |

### 15.6 Özellik Profilleri

Minimum kurulum senaryolarına göre gereken paket kümeleri:

| Profil | Gerekli Paketler |
|--------|-----------------|
| **Minimal CLI** (Ollama + keyword RAG) | `httpx`, `python-dotenv`, `pydantic`, `beautifulsoup4`, `packaging` |
| **Tam CLI** (+ BM25 + GitHub + web arama) | yukarıdaki + `rank_bm25`, `PyGithub`, `duckduckgo-search` |
| **Web Sunucu** | yukarıdaki + `fastapi`, `uvicorn` |
| **GPU RAG** | yukarıdaki + `chromadb`, `sentence-transformers`, `torch` (CUDA) |
| **Gemini Modu** | yukarıdaki + `google-generativeai` |
| **Tam Deploy** | tüm opsiyonel dahil + Docker + Redis (ileride) |

---

## 16. Hata Yönetimi ve Loglama Stratejisi

[⬆ İçindekilere Dön](#içindekiler)

### 16.1 Hata Yönetimi Kalıpları

Kod tabanı boyunca üç farklı hata yönetimi deseni kullanılmaktadır:

**1. Tuple Dönüş Deseni** (`Tuple[bool, str]`)
Araçların ve manager metodlarının büyük çoğunluğu `(başarı, mesaj)` tuple'ı döndürür. İstisna dışarıya sızmaz; hata durumu dönüş değerinden okunur. Bu, ReAct döngüsünün araç hatasını kolayca işlemesini sağlar.
```
(True, "sonuç metni")   → başarı
(False, "hata mesajı")  → hata
```
Kullanım yeri: `CodeManager`, `GitHubManager`, `WebSearchManager`, `DocumentStore`, `TodoManager`

**2. Loglama + Sessiz Fallback**
Opsiyonel bağımlılıklar (ChromaDB, BM25, psutil, pynvml, torch) yüklenemezse sistem çökmez; `logger.warning` ile kayıt alınır ve bir sonraki motora/moda geçilir.
```
ChromaDB başlatılamadı → _chroma_available = False → BM25'e düş
BM25 yok              → _bm25_available = False   → Keyword'e düş
```
Kullanım yeri: `DocumentStore.__init__`, `SystemHealthManager.__init__`

**3. Fail-Closed Güvenlik Deseni**
Güvenlik kararlarında belirsizlik varsa operasyon reddedilir. Erişim seviyesi tanımsızsa `sandbox`'a normalize edilir. Fernet anahtarı geçersizse `ValueError` ile sistem başlatılmaz.
```
bilinmeyen seviye → sandbox (daha kısıtlayıcı)
geçersiz şifreleme anahtarı → ValueError, sistem durur
```
Kullanım yeri: `SecurityManager`, `ConversationMemory`

### 16.2 Loglama Stratejisi

| Seviye | Ne Zaman Kullanılır | Örnekler |
|--------|--------------------|---------|
| `DEBUG` | Geliştirici detayları, başarılı rutin işlemler | Dizin hazır, VRAM fraksiyon atlandı |
| `INFO` | Başarılı sistem olayları | GPU aktif, ChromaDB başlatıldı, belge eklendi |
| `WARNING` | Düşürülmüş modda çalışma, eksik opsiyonel bağımlılık | PyTorch yok, Ollama'ya ulaşılamadı |
| `ERROR` | Başarısız operasyon, kullanıcıya görünür hata | Dizin oluşturulamadı, ChromaDB hatası, geçersiz API key |

**Logger İsimlendirme Tutarlılığı:**
- `config.py` → `Sidar.Config`
- Diğer tüm modüller → `logging.getLogger(__name__)` (modül adı)

**RotatingFileHandler:** 10 MB / 5 yedek, UTF-8 — Türkçe log mesajları güvenle yazılır.

### 16.3 Asenkron Hata Yönetimi

`AutoHandle` içindeki her araç çağrısı `asyncio.wait_for()` ile `AUTO_HANDLE_TIMEOUT` (12 sn) içine alınmıştır. `TimeoutError` yakalanarak kullanıcıya anlamlı mesaj döndürülür; event loop bloklanmaz.

ReAct döngüsünde araç exception'ı `_FMT_TOOL_ERR` formatına sarılarak belleğe yazılır ve LLM'e iletilir. LLM bir sonraki adımda farklı strateji deneyebilir.

### 16.4 Bozuk Veri Karantinası

`ConversationMemory` JSON okuma hatası veya şifre çözme başarısızlığı durumunda dosyayı `.json.broken` uzantısıyla yeniden adlandırır ve temiz bir oturum başlatır. 7 günden eski `.broken` dosyaları (en fazla 50 tutulur) otomatik temizlenir. Bu mekanizma disk üzerindeki kalıcı veri bozulmasının sistemi tamamen durdurmasını önler.

---

## 17. Yaygın Sorunlar ve Çözümleri

[⬆ İçindekilere Dön](#içindekiler)

Kodun incelenmesinden türetilen, gerçek kullanıcı senaryolarında karşılaşılması muhtemel sorunlar ve kodu okuyarak tespit edilen kökenleri.

### 17.1 Ollama Bağlantı Sorunları

**Belirti:** `⚠️ Ollama'ya ulaşılamadı` uyarısı; LLM yanıt vermiyor.

| Olası Neden | Nereden Anlaşılır | Çözüm |
|-------------|-------------------|-------|
| `ollama serve` çalışmıyor | `config.py:437` httpx bağlantı hatası | `ollama serve` komutunu çalıştır |
| `OLLAMA_URL` yanlış | `.env` veya varsayılan `http://localhost:11434/api` | URL'yi kontrol et, `/api` son ekini dahil et |
| Timeout çok kısa | `OLLAMA_TIMEOUT=30` büyük modelde yetersiz | `.env`'de `OLLAMA_TIMEOUT=120` yap |
| Model adı hatalı | `CODING_MODEL` / `TEXT_MODEL` | `ollama list` ile mevcut modelleri kontrol et |

### 17.2 GPU / CUDA Sorunları

**Belirti:** `CUDA bulunamadı — CPU modunda çalışılacak` veya embedding çok yavaş.

| Olası Neden | Nereden Anlaşılır | Çözüm |
|-------------|-------------------|-------|
| PyTorch CUDA wheel kurulmamış | `config.py:174` | `pip install torch --index-url https://download.pytorch.org/whl/cu124` |
| WSL2 + Windows sürücüsü eski | `config.py:130-131` WSL2 tespiti | NVIDIA Windows sürücüsünü güncelle |
| `USE_GPU=false` ayarı | `config.py:133` | `.env`'de `USE_GPU=true` yap |
| `GPU_MEMORY_FRACTION` aralık dışı | `config.py:151-157` | 0.1–1.0 arasında değer ver |

### 17.3 ChromaDB / RAG Sorunları

**Belirti:** Vektör arama çalışmıyor; `BM25'e düşülüyor` logu.

| Olası Neden | Nereden Anlaşılır | Çözüm |
|-------------|-------------------|-------|
| `chromadb` kurulmamış | `rag.py:129` import kontrolü | `pip install chromadb` |
| `sentence-transformers` yok | `rag.py:46` GPU embedding başlatma | `pip install sentence-transformers` |
| `all-MiniLM-L6-v2` indirilmemiş | İlk belgede uzun bekleme | `PRECACHE_RAG_MODEL=true` ile Docker build, veya `HF_HUB_OFFLINE=false` |
| ChromaDB versiyon uyumsuzluğu | `rag.py:201` başlatma hatası | `pip install chromadb --upgrade` |
| `chunk_size < chunk_overlap` | `rag.py:246` mantık hatası | `RAG_CHUNK_OVERLAP < RAG_CHUNK_SIZE` olduğundan emin ol |

### 17.4 Docker REPL Sorunları

**Belirti:** `execute_code` çalışmıyor; subprocess fallback devreye giriyor.

| Olası Neden | Nereden Anlaşılır | Çözüm |
|-------------|-------------------|-------|
| Docker daemon çalışmıyor | `code_manager.py:_init_docker` | `docker ps` ile kontrol et, daemon'ı başlat |
| WSL2 socket yolu hatalı | `code_manager.py` WSL2 socket fallback | Docker Desktop'ı kur veya `DOCKER_HOST` ayarla |
| `python:3.11-alpine` imajı yok | İlk çalıştırmada uzun bekleme | `docker pull python:3.11-alpine` önceden çek |
| Zaman aşımı çok kısa | `DOCKER_EXEC_TIMEOUT=10` | Uzun hesaplamalar için artır |
| `ACCESS_LEVEL=restricted` | `security.py` erişim kontrolü | Seviyeyi `sandbox` veya `full` yap |

### 17.5 Bellek / Şifreleme Sorunları

**Belirti:** `ValueError: MEMORY_ENCRYPTION_KEY geçersiz` veya oturum yüklenemiyor.

| Olası Neden | Nereden Anlaşılır | Çözüm |
|-------------|-------------------|-------|
| Geçersiz Fernet anahtarı | `config.py:411-420` | `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` ile yeni anahtar üret |
| `cryptography` kurulmamış | `config.py:421-427` | `pip install cryptography` |
| Eski şifresiz dosyalar | `memory.py` geçiş modu | Eski oturumlar `.broken` olarak işaretlenir; veri kaybı riski — yedekle |
| `data/sessions/` izin sorunu | `memory.py` write hatası | Dizin yazma izinlerini kontrol et |

### 17.6 GitHub Entegrasyon Sorunları

**Belirti:** `⚠ GitHub token ayarlanmamış` veya repo bulunamadı.

| Olası Neden | Nereden Anlaşılır | Çözüm |
|-------------|-------------------|-------|
| `GITHUB_TOKEN` boş | `github_manager.py:61` | GitHub Settings → Developer settings → Personal access tokens |
| Token yetkileri yetersiz | PyGithub 403 hatası | Token'a `repo`, `read:org` scopelarını ekle |
| `GITHUB_REPO` formatı hatalı | `github_manager.py:80` | `owner/repo-name` formatında yaz |
| Binary dosya okuma girişimi | `github_manager.py:33` whitelist | Yalnızca metin uzantılı dosyalar okunabilir |
| Commit limiti aşıldı | `github_manager.py:296` | Maksimum 30 commit; daha fazlası sessizce kesilir |

### 17.7 Web Sunucu Sorunları

**Belirti:** Rate limit hatası, CORS hatası veya SSE bağlantısı kopuyor.

| Olası Neden | Nereden Anlaşılır | Çözüm |
|-------------|-------------------|-------|
| Rate limit aşıldı | `web_server.py:83` | `RATE_LIMIT_CHAT` değerini artır veya sunucuyu yeniden başlat |
| CORS reddedildi | `web_server.py:66` | Yalnızca localhost kökeninden erişilebilir; proxy için CORS origins güncelle |
| Port kullanımda | `uvicorn` bind hatası | `WEB_PORT` farklı bir değere ayarla |
| SSE bağlantısı kopuyor | `anyio.ClosedResourceError` — zaten yönetiliyor | İstemci tarafı yeniden bağlanma mantığı ekle |

### 17.8 `.env` Dosyası Sorunları

**Belirti:** `⚠️ '.env' dosyası bulunamadı! Varsayılan ayarlar kullanılacak.`

| Olası Neden | Çözüm |
|-------------|-------|
| `.env` dosyası yok | `.env.example`'ı kopyala: `cp .env.example .env` |
| `.env` proje kökünde değil | `config.py:28` `BASE_DIR / ".env"` yolunu kullanır — dosyayı proje köküne taşı |
| Boolean değer yanlış formatda | `get_bool_env` yalnızca `true/1/yes/on` kabul eder (büyük-küçük harf bağımsız) |

---

*Bu rapor, projedeki tüm kaynak dosyaların satır satır incelenmesiyle 2026-03-07 tarihinde hazırlanmıştır.*
---