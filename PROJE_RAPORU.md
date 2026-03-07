# SİDAR Projesi — Kapsamlı Kod Analiz Raporu (Güncel)

> **Rapor Tarihi:** 2026-03-07
> **Proje Sürümü:** 2.7.0
> **Analiz Kapsamı:** Tüm kaynak dosyaları satır satır incelenmiştir.

---

## 1. Proje Genel Bakışı

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
│   ├── sidar_agent.py         # Ana ajan (1458 satır, 40+ araç)
│   ├── auto_handle.py         # Anahtar kelime tabanlı hızlı yönlendirici
│   └── definitions.py        # Sistem istemi ve ajan kimliği
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
├── tests/                     # 25 test modülü
│   ├── test_sidar.py
│   └── test_*_improvements.py
│
├── data/                      # RAG ve bellek verileri
├── CLAUDE.md                  # Geliştirici rehberi
└── .env.example               # Ortam değişkeni şablonu
```

---

## 3. Modül Bazında Detaylı Analiz

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

### 3.4 `web_server.py` — FastAPI Web Sunucusu (801 satır)

**Amaç:** SSE (Server-Sent Events) destekli asenkron chat web arayüzü.

**Temel API Endpoint'leri:**

| Endpoint | Metod | Açıklama |
|----------|-------|----------|
| `/` | GET | `index.html` servis et |
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
- Rate limiting: In-memory `defaultdict` ile 3 ayrı limit katmanı (chat/mutation/GET-IO)
- `anyio.ClosedResourceError` ile kopuk SSE bağlantıları sessizce kapatılır

**Singleton Ajan:** `get_agent()` fonksiyonu ile lazy-init; event loop başladıktan sonra `asyncio.Lock` oluşturulur.

---

### 3.5 `agent/sidar_agent.py` — Ana Ajan (1458 satır)

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

### 3.6 `agent/auto_handle.py` — Hızlı Yönlendirici (600 satır)

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

### 3.8 `core/llm_client.py` — LLM İstemcisi (340 satır)

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

### 3.9 `core/memory.py` — Konuşma Belleği (380 satır)

**Amaç:** Çok oturumlu, kalıcı, thread-safe ve opsiyonel şifreli bellek yönetimi.

**Mimari:**
- Her oturum `data/sessions/<uuid>.json` dosyasında saklanır
- `threading.RLock` ile tüm okuma/yazma işlemleri korunur
- Bozuk dosyalar `.json.broken` uzantısıyla karantinaya alınır (7 gün / 50 dosya retention)

**Fernet Şifrelemesi:**
- `MEMORY_ENCRYPTION_KEY` ayarlandığında oturum dosyaları AES-128-CBC ile şifrelenir
- Geçiş dönemi uyumu: şifre çözülemeyen eski dosyalar düz metin olarak okunmaya çalışılır
- Anahtar geçersizse `ValueError` ile sistem durdurulur (fail-closed)

**Kaydetme Optimizasyonu:**
- `_save_interval_seconds = 0.5` ile kısa aralıklı `add()` çağrıları birleştirilir
- `force_save()` ile anında disk yazımı (clear, session değişimi, başlık güncelleme)

**Özetleme Desteği:**
- `needs_summarization()`: bellek penceresinin %80'i dolu VEYA tahminî token > 6000 ise True
- `apply_summary(text)`: tüm geçmiş 2 mesaja (user + assistant özet) indirgenir

**Token Tahmini:** `_estimate_tokens()` — UTF-8 Türkçe için ~3.5 karakter/token heuristic kullanır.

---

### 3.10 `core/rag.py` — RAG Motoru (858 satır)

**Amaç:** ChromaDB (vektör) + BM25 (kelime sıklığı) + Keyword (basit eşleşme) hibrit belge deposu.

**Arama Modları:**

| Mod | Motor | Açıklama |
|-----|-------|----------|
| `auto` | ChromaDB → BM25 → Keyword | Kademeli fallback |
| `vector` | ChromaDB (cosine similarity) | Anlamsal arama |
| `bm25` | rank_bm25 | TF-IDF benzeri kelime sıklığı |
| `keyword` | Regex | Başlık ×5, etiket ×3, içerik ×1 ağırlıkla skor |

**Chunking Motoru:**
`_recursive_chunk_text()` LangChain'in `RecursiveCharacterTextSplitter` mantığını simüle eder. Öncelik sırası: `\nclass ` → `\ndef ` → `\n\n` → `\n` → ` ` → karakter. Overlap mekanizması bağlam sürekliliğini korur.

**GPU Embedding:**
`_build_embedding_function()` — `USE_GPU=true` ise `sentence-transformers/all-MiniLM-L6-v2` modeli CUDA üzerinde çalışır. `GPU_MIXED_PRECISION=true` ise FP16 ile VRAM tasarrufu sağlanır.

**BM25 Cache:**
Inkremental güncelleme: belge eklendiğinde/silindiğinde tüm corpus yeniden yüklenmez; yalnızca değişen kayıt güncellenir. `_ensure_bm25_index()` lazy build ile gereksiz CPU kullanımını önler.

**Belge Yönetimi:**
- `add_document()`: dosya sistemi + index.json + ChromaDB chunked upsert (thread-safe `_write_lock`)
- `add_document_from_url()`: httpx asenkron HTTP çekme + HTML temizleme + ekleme
- `add_document_from_file()`: uzantı whitelist kontrolü (.py, .md, .json, .yaml, vb.)
- `delete_document()`: dosya + ChromaDB (parent_id ile tüm chunk'lar) + BM25 cache

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

### 3.13 `managers/github_manager.py` — GitHub Yöneticisi (550 satır)

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

### 3.15 `managers/web_search.py` — Web Arama Yöneticisi (352 satır)

**Amaç:** Tavily → Google → DuckDuckGo kademeli motor desteğiyle asenkron web araması.

**`auto` Mod Öncelik Sırası:** Tavily → Google Custom Search → DuckDuckGo

**Desteklenen Operasyonlar:**
- `search(query)`: Genel web araması
- `fetch_url(url)`: URL içerik çekme + BeautifulSoup HTML temizleme
- `search_docs(library, topic)`: Resmi dokümantasyon araması
- `search_stackoverflow(query)`: Stack Overflow araması

**DuckDuckGo Uyumu:** v8 SDK uyumlu `DDGS` (sync) kullanılır; `asyncio.to_thread` ile event loop bloklanmaz.

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

### 3.18 `web_ui/index.html` — Web Arayüzü (3399 satır)

**Amaç:** Vanilla JavaScript ile yazılmış tek sayfa uygulaması.

**Temel Özellikler:**
- **SSE Chat:** `EventSource` ile gerçek zamanlı akış mesajları
- **Markdown Render:** `marked.js` ile kod blokları, tablolar, başlıklar
- **Kod Vurgulama:** `highlight.js` ile 180+ dil desteği
- **Çok Oturum Yönetimi:** Sol panel sohbet listesi, başlık düzenleme, silme
- **RAG Arayüzü:** Belge yükleme, arama, silme
- **Görev Listesi:** Todo görüntüleme
- **Git Paneli:** Commit geçmişi, branch listesi
- **Dosya Gezgini:** Proje dosyalarını ağaç görünümde listeler
- **Tema:** CSS custom properties ile karanlık/aydınlık mod uyumlu tasarım

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

Projede **25 test modülü** bulunmaktadır:

| Test Dosyası | Kapsam |
|-------------|--------|
| `test_sidar.py` | Genel entegrasyon testleri |
| `test_sidar_improvements.py` | Ajan iyileştirme testleri |
| `test_auto_handle_improvements.py` | AutoHandle regex ve mantık testleri |
| `test_agent_init_improvements.py` | Ajan başlatma testleri |
| `test_agent_subtask.py` | Alt görev (subtask) testleri |
| `test_llm_client_improvements.py` | LLM istemci testleri |
| `test_memory_improvements.py` | Bellek yönetimi testleri |
| `test_rag_improvements.py` | RAG motor testleri |
| `test_security_improvements.py` | Güvenlik kontrolü testleri |
| `test_code_manager_improvements.py` | Kod yöneticisi testleri |
| `test_github_manager_improvements.py` | GitHub entegrasyon testleri |
| `test_system_health_improvements.py` | Sağlık monitör testleri |
| `test_web_search_improvements.py` | Web arama testleri |
| `test_package_info_improvements.py` | Paket bilgi testleri |
| `test_todo_manager_improvements.py` | Görev yöneticisi testleri |
| `test_config_env_helpers.py` | Config yardımcı fonksiyon testleri |
| `test_web_server_improvements.py` | Web sunucu endpoint testleri |
| `test_web_ui_runtime_improvements.py` | Web UI çalışma zamanı testleri |
| `test_web_ui_security_improvements.py` | Web UI güvenlik testleri |
| `test_cli_banner.py` | CLI banner testleri |
| `test_cli_runtime_improvements.py` | CLI çalışma zamanı testleri |
| `test_main_launcher_improvements.py` | Başlatıcı testleri |
| `test_dockerfile_runtime_improvements.py` | Dockerfile çalışma zamanı testleri |
| `test_definitions_prompt.py` | Sistem istemi testleri |
| `test_*_md_improvements.py` | Dokümantasyon testleri |

**Test çalıştırma:** `pytest` veya `pytest --cov=.`

---

## 7. Temel Bağımlılıklar

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

| Dosya | Satır |
|-------|-------|
| `web_ui/index.html` | 3.399 |
| `agent/sidar_agent.py` | 1.458 |
| `core/rag.py` | 858 |
| `web_server.py` | 801 |
| `managers/code_manager.py` | 746 |
| `agent/auto_handle.py` | 600 |
| `managers/github_manager.py` | 550 |
| `config.py` | 517 |
| `managers/system_health.py` | 420 |
| `managers/todo_manager.py` | 380 |
| `core/memory.py` | 380 |
| `managers/web_search.py` | 352 |
| `core/llm_client.py` | 340 |
| `managers/package_info.py` | 314 |
| `github_upload.py` | 294 |
| `main.py` | 331 |
| `cli.py` | 274 |
| `agent/definitions.py` | 165 |
| **Toplam (kaynak)** | **~11.180** |

---

*Bu rapor, projedeki tüm kaynak dosyaların satır satır incelenmesiyle 2026-03-07 tarihinde hazırlanmıştır.*
