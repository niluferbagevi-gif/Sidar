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

## 9. Modül Bağımlılık Haritası

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
agent/auto_handle.py  ←── managers/*, core/memory.py, core/rag.py
agent/sidar_agent.py  ←── config.py, core/*, managers/*, agent/auto_handle.py,
                            agent/definitions.py

cli.py         ←── config.py, agent/sidar_agent.py
web_server.py  ←── config.py, agent/sidar_agent.py, core/*, managers/*
main.py        ←── config.py (DummyConfig fallback'i de var)
github_upload.py ←── (bağımlılık YOK — bağımsız araç)
```

**Döngüsel bağımlılık:** Tespit edilmedi. `config.py` bağımlılık ağacının kökü; hiçbir iç modülü import etmez.

---

## 10. Veri Akış Diyagramı

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

## 11. Mevcut Sorunlar ve Dikkat Noktaları

Kod inceleme sürecinde tespit edilen sorunlar önem sırasına göre listelenmiştir.

### 11.1 Yüksek Öncelikli

| # | Dosya | Satır | Sorun |
|---|-------|-------|-------|
| 1 | `core/rag.py` | 295–306 | `_chunk_text()` geçici olarak `self._chunk_size` ve `self._chunk_overlap`'i değiştiriyor. Bu değişiklik `_write_lock` dışında yapılıyor; eşzamanlı `add_document` çağrılarında race condition riski var. |
| 2 | `core/rag.py` | 700–727 | `_bm25_search()` içinde `_ensure_bm25_index()` lock alıp bırakıyor, ardından skor hesaplaması lock içinde yapılıyor. Lock tutma süresi uzun; diğer yazma operasyonları bu süre boyunca beklemek zorunda kalıyor. |
| 3 | `agent/sidar_agent.py` | 128–129 | `_instructions_cache` ve `_instructions_mtimes` dict'leri asenkron ortamda lock korumasız. Eşzamanlı iki `respond()` çağrısı (web servisi) aynı anda mtime'ı okuyup yazabilir. |

### 11.2 Orta Öncelikli

| # | Dosya | Satır | Sorun |
|---|-------|-------|-------|
| 4 | `web_server.py` | 83–92 | Rate limiting salt in-memory `defaultdict`. Sunucu yeniden başlatıldığında tüm sayaçlar sıfırlanır; kısa kesintilerle limit aşılabilir. |
| 5 | `core/memory.py` | — | `_estimate_tokens()` 3.5 karakter/token heuristic kullanıyor. Kod ağırlıklı konuşmalarda (Python snippet'leri) bu oran ~2'ye düşer; özetleme gecikebilir. |
| 6 | `docker-compose.yml` | — | Tüm servisler `/var/run/docker.sock` bind mount yapıyor. Bu, konteyner içinden Docker daemon'a tam erişim demektir; container escape riski var. Yalnızca REPL servisleri için sınırlandırılmalı. |
| 7 | `managers/github_manager.py` | 296–299 | `list_commits(n)` en fazla 30 commit çekebiliyor ancak kullanıcı daha büyük değer verebilir. Hata mesajı yok; sessizce 30'a kesilir. |

### 11.3 Düşük Öncelikli / Teknik Borç

| # | Dosya | Satır | Sorun |
|---|-------|-------|-------|
| 8 | `agent/auto_handle.py` | 54–58 | `_MULTI_STEP_RE` yalnızca Türkçe kalıpları kapsıyor. İngilizce çok adımlı istekler ("first ... then ...", "step 1: ...") ReAct yerine AutoHandle'a düşebilir. |
| 9 | `core/rag.py` | 246 | `range(0, len(text_part), self._chunk_size - self._chunk_overlap)` ifadesinde `chunk_size == chunk_overlap` olması durumunda `ZeroDivisionError` riski; ancak Config varsayılanlarıyla (1000/200) bu durum oluşmuyor. |
| 10 | `managers/web_search.py` | — | DuckDuckGo `DDGS` senkron API `asyncio.to_thread` ile çalıştırılıyor. DDG SDK'sının olası gelecek versiyon değişiklikleri sessiz hata üretebilir; versiyon pinlemesi eksik. |
| 11 | `web_ui/index.html` | — | 3.399 satırlık tek dosya. JS, CSS ve HTML birbirinden ayrılmamış; test edilebilirlik düşük. |
| 12 | `config.py` | 513 | `Config.initialize_directories()` modül import anında çağrılıyor. Test ortamında istenmeyen dizin oluşturabilir; `pytest` fixture'larında `tmp_path` ile override gerekebilir. |

---

## 12. `.env` Tam Değişken Referansı

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

Kod tabanından çıkan teknik borç ve iyileştirme önerileri:

| Öncelik | Alan | Öneri |
|---------|------|-------|
| Yüksek | `rag.py` | `_chunk_text()` içindeki geçici attribute değişikliği parametre olarak geçirilmeli; `self._chunk_size/_overlap` dokunulmamalı |
| Yüksek | `sidar_agent.py` | `_instructions_cache` ve `_instructions_mtimes` `asyncio.Lock` ile korunmalı |
| Yüksek | `docker-compose.yml` | Docker socket mount yalnızca REPL gerektiren servislerle sınırlandırılmalı |
| Orta | `web_server.py` | Rate limiting Redis veya `cachetools` ile kalıcı hale getirilmeli |
| Orta | `core/memory.py` | Token tahmini için `tiktoken` gibi gerçek bir tokenizer kullanılmalı |
| Orta | `auto_handle.py` | `_MULTI_STEP_RE`'ye İngilizce çok adımlı kalıplar eklenmeli |
| Orta | `github_manager.py` | `list_commits(n)` için `n > 30` uyarısı eklenmeli |
| Düşük | `web_ui/index.html` | JS ve CSS ayrı dosyalara bölünmeli (`app.js`, `style.css`) |
| Düşük | `config.py` | Test ortamı için `initialize_directories()` çağrısı `__main__` guard arkasına alınmalı |
| Düşük | `rag.py` | `chunk_size == chunk_overlap` kenar durumu için koruyucu kontrol eklenmeli |

---

## 14. Sonraki Versiyon İçin Geliştirme Önerileri (v2.8+)

Bu bölüm, mevcut kodun sınırlarından ve mimari boşluklarından çıkarılan somut geliştirme hedeflerini kapsar. Her madde bağımsız bir özellik olarak ele alınabilir.

---

### 14.1 Çekirdek Mimari

#### 14.1.1 Kalıcı Rate Limiting
**Mevcut durum:** `web_server.py` `defaultdict` in-memory sayaç kullanıyor — sunucu yeniden başlayınca sıfırlanıyor.
**Öneri:** `Redis` veya `cachetools.TTLCache` tabanlı kalıcı pencere. Tek bir `RateLimiter` sınıfına taşınması halinde web_server ve CLI paylaşabilir.
**Etki:** Orta. Yalnızca dışa açık deploy senaryolarında kritik.

#### 14.1.2 Gerçek Token Sayacı
**Mevcut durum:** `memory.py` 3.5 karakter/token heuristic kullanıyor. Kod snippet'leri ağırlıklı konuşmalarda bu oran ~2'ye düşer; özetleme geç tetiklenir.
**Öneri:** `tiktoken` (OpenAI tokenizer — model bağımsız çalışır) veya `transformers.AutoTokenizer` ile model spesifik sayım. Config'e `TOKENIZER_MODEL` eklenmeli.
**Etki:** Yüksek. Bellek taşması ve bağlam kesme hatalarını azaltır.

#### 14.1.3 Asenkron Lock ile Talimat Cache Koruması
**Mevcut durum:** `sidar_agent.py:128-129` `_instructions_cache` ve `_instructions_mtimes` dict'leri `asyncio.Lock` olmadan kullanılıyor.
**Öneri:** `asyncio.Lock` ile sarmalama; `_load_instructions()` metoduna taşıma.
**Etki:** Yüksek. Web servisinde eşzamanlı iki istek aynı anda cache'i bozabilir.

#### 14.1.4 Thread-Safe Chunking
**Mevcut durum:** `rag.py:295-306` `_chunk_text()` geçici olarak `self._chunk_size/_overlap` attribute'larını değiştiriyor.
**Öneri:** Chunk boyutlarını yerel parametre olarak geçirme; `self` üzerinde hiçbir yan etki yok.
**Etki:** Yüksek. Eşzamanlı belge eklemelerinde sessiz veri bozulması riski.

---

### 14.2 LLM ve Ajan Katmanı

#### 14.2.1 Çoklu LLM Sağlayıcı Genişletmesi
**Mevcut durum:** Ollama ve Gemini destekleniyor.
**Öneri:** `LLMClient` soyut temel sınıfa dönüştürülmeli; yeni sağlayıcılar `OllamaClient`, `GeminiClient`, `OpenAIClient` şeklinde alt sınıf olarak eklenebilmeli.
**Eklentiler:** Anthropic Claude API, OpenAI GPT-4o, Azure OpenAI, LM Studio (yerel REST).

#### 14.2.2 Araç Tanımlarının Dışsallaştırılması
**Mevcut durum:** Araç tablosu `sidar_agent.py` içindeki `_tools` dict'inde hardcoded.
**Öneri:** Her araç `@tool(name, description, allowed_levels)` dekoratörü ile tanımlanmalı; araç kataloğu otomatik oluşturulmalı. `definitions.py`'deki sistem istemindeki araç listesi de otomatik güncellenebilir.
**Etki:** Yeni araç ekleme sürtünmesini sıfıra indirir.

#### 14.2.3 Paralel ReAct Adımları
**Mevcut durum:** `parallel` aracı araçları eşzamanlı çalıştırıyor ancak LLM bunu her zaman doğru kullanmıyor.
**Öneri:** Bağımsız alt görevleri LLM yerine ajan katmanı tespit edip otomatik olarak `asyncio.gather` ile paralel çalıştırmalı. Örneğin `read_file(a)` ve `read_file(b)` aynı anda çalışabilir.

#### 14.2.4 Yapısal Araç Şeması (MCP Uyumu)
**Mevcut durum:** Araç argümanı tek bir `str` — karmaşık araç çağrıları için JSON string kullanılıyor.
**Öneri:** Her araç için Pydantic `BaseModel` giriş şeması; LLM JSON Schema ile yönlendirilmeli. Bu Model Context Protocol (MCP) standardıyla uyumlu hale getirir.

---

### 14.3 RAG ve Bellek

#### 14.3.1 Hibrit Sıralama (RRF)
**Mevcut durum:** `auto` modda ChromaDB → BM25 → Keyword kademeli fallback; kazanan motor tek başına sıralamayı belirliyor.
**Öneri:** Reciprocal Rank Fusion (RRF) ile ChromaDB ve BM25 sonuçlarını birleştirme. Her iki motorun bulguları ağırlıklı olarak birleştirilir; tek motor yetersizliği azalır.

#### 14.3.2 BM25 Corpus Ölçeklenebilirliği
**Mevcut durum:** Tüm belgelerin token'ları RAM'de tutuluyor (`_bm25_corpus_tokens`). 10.000+ belge senaryosunda bellek basıncı oluşur.
**Öneri:** SQLite FTS5 (tam metin arama) veya Whoosh ile disk tabanlı BM25 indeksi. Corpus RAM'de değil, disk üzerinde tutulur.

#### 14.3.3 Çok Oturumlu RAG İzolasyonu
**Mevcut durum:** Tüm oturumlar aynı ChromaDB koleksiyonunu (`sidar_knowledge_base`) paylaşıyor.
**Öneri:** Oturum başına koleksiyon veya metadata filtresiyle (`session_id`) izolasyon. Kullanıcı A'nın eklediği belgeler kullanıcı B'nin aramasında çıkmamalı.

#### 14.3.4 Bellek Özetleme Stratejisi Seçimi
**Mevcut durum:** Özetleme tetiklendiğinde tüm geçmiş 2 mesaja indirgeniyor — bağlam kaybı riski yüksek.
**Öneri:** Kayan pencere (sliding window): Son N tur tam korunur, öncesi özetlenir. Yapılandırılabilir `MEMORY_SUMMARY_KEEP_LAST` parametresi.

---

### 14.4 Web Arayüzü ve API

#### 14.4.1 Web UI Modülarizasyonu
**Mevcut durum:** `web_ui/index.html` tek 3399 satırlık dosya.
**Öneri:** Dosya yapısı:
```
web_ui/
├── index.html       (iskelet)
├── app.js           (ana mantık)
├── chat.js          (SSE ve mesaj render)
├── sidebar.js       (oturum ve panel yönetimi)
├── rag.js           (RAG arayüzü)
└── style.css        (tema ve layout)
```
FastAPI `StaticFiles` middleware ile servis edilebilir.

#### 14.4.2 WebSocket Desteği
**Mevcut durum:** SSE (Server-Sent Events) tek yönlü akış; mesaj iptali için ayrı endpoint gerekiyor.
**Öneri:** FastAPI WebSocket ile çift yönlü kanal. Kullanıcı mesajı iptal edebilir; sunucu anlık durum güncellemesi gönderebilir.

#### 14.4.3 OpenAPI Şema Belgelendirmesi
**Mevcut durum:** FastAPI otomatik `/docs` oluşturuyor ancak endpoint açıklamaları eksik.
**Öneri:** Her endpoint için `summary`, `description`, `response_model` ve `responses` parametrelerinin doldurulması. Harici entegrasyon kolaylaşır.

#### 14.4.4 Kimlik Doğrulama
**Mevcut durum:** Web API yalnızca CORS ile korunuyor; token veya session auth yok.
**Öneri:** JWT tabanlı basit auth veya API key header (`X-API-Key`). `.env` üzerinden `API_KEY` konfigürasyonu. Özellikle dış ağa açık deploy için zorunlu.

---

### 14.5 GitHub Entegrasyonu

#### 14.5.1 Webhook Desteği
**Mevcut durum:** GitHub durumu yalnızca istek üzerine sorgulanıyor (pull model).
**Öneri:** GitHub Webhook alıcısı eklenebilir (push, PR, issue eventi). Yeni commit'te otomatik RAG güncelleme veya bildirim.

#### 14.5.2 Issue Yönetimi
**Mevcut durum:** `github_manager.py` PR işlemlerini destekliyor; issue yok.
**Öneri:** `create_issue`, `list_issues`, `comment_issue`, `close_issue` metodları. Ajan `todo_write` ile oluşturduğu görevi doğrudan GitHub Issue'ya bağlayabilir.

#### 14.5.3 Diff Analizi
**Mevcut durum:** `get_pr_files()` değişen dosyaları döndürüyor ama diff içeriğini değil.
**Öneri:** `PyGithub` `get_files()` üzerinden unified diff alınması. LLM kod inceleme yorumu yapabilir.

---

### 14.6 Güvenlik ve İzleme

#### 14.6.1 Docker Socket Riski Azaltma
**Mevcut durum:** Tüm docker-compose servisleri `/var/run/docker.sock` mount ediyor.
**Öneri:** Yalnızca REPL gerektiren servisler için socket mount; diğerleri için kaldırılmalı. Alternatif olarak `dockerd` rootless mod veya `sysbox` kullanımı.

#### 14.6.2 Denetim Logu (Audit Log)
**Mevcut durum:** Araç çağrıları yalnızca `logger.info` ile loglanıyor; yapısal değil.
**Öneri:** Ayrı `audit.jsonl` dosyasına yapısal kayıt: `{timestamp, session_id, tool, argument, access_level, result_ok}`. Güvenlik denetimleri için sorgulanabilir.

#### 14.6.3 Sandbox Çıktı Boyutu Limiti
**Mevcut durum:** Docker REPL'in çıktı boyutuna açık limit yok.
**Öneri:** `execute_code()` sonucunu `MAX_OUTPUT_CHARS` (örn. 10.000 karakter) ile kırpma. Bellek dolması ve UI donması riski azalır.

#### 14.6.4 Güvenlik Seviyesi Geçiş Logu
**Mevcut durum:** `set_provider_mode()` ve erişim seviyesi değişiklikleri loglanıyor ancak oturum bazında takip yok.
**Öneri:** Seviye değişikliklerini oturum belleğine de yazmak; `[GÜVENLIK] Erişim seviyesi full → sandbox olarak değiştirildi` şeklinde izlenebilir.

---

### 14.7 Test ve Kalite

#### 14.7.1 Entegrasyon Test Altyapısı
**Mevcut durum:** 25 test modülü var ancak çoğu unit test; gerçek LLM ve Docker gerektiren testler yok.
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

---

### 14.8 Operasyon ve Dağıtım

#### 14.8.1 Sağlık Endpoint Genişletmesi
**Mevcut durum:** `/health` metin yanıtı döndürüyor.
**Öneri:** Yapısal JSON: `{status, version, uptime, llm_available, rag_doc_count, memory_sessions, gpu_info}`. Kubernetes liveness/readiness probe uyumlu.

#### 14.8.2 Çevre Başına Konfigürasyon
**Mevcut durum:** Tek `.env` dosyası.
**Öneri:** `.env.development`, `.env.production`, `.env.test` desteği; `python-dotenv`'in `dotenv_values` zinciri ile birleştirme. Docker build-arg ile `ENV_FILE` override.

#### 14.8.3 Gözlemlenebilirlik (Observability)
**Mevcut durum:** Yalnızca dosya logu var.
**Öneri:** OpenTelemetry ile trace ID; her LLM çağrısı bir span olarak izlenir. Grafana/Jaeger entegrasyonu isteğe bağlı; telemetry sadece `OTEL_EXPORTER_ENDPOINT` ayarlıysa aktif olur.

#### 14.8.4 Model Önbellekleme ve Soğuk Start
**Mevcut durum:** ChromaDB embedding modeli ilk belgede yükleniyor; soğuk start gecikmesi var.
**Öneri:** Web sunucu `startup` event'inde `DocumentStore.prebuild_bm25_index()` ve ChromaDB bağlantısı açılmalı. `PRECACHE_RAG_MODEL=true` Dockerfile argümanı zaten var; web_server.py'de de aktive edilmeli.

---

### 14.9 Versiyon 2.8 İçin Önerilen Öncelik Sırası

| Sıra | Özellik | Etki | Çaba |
|------|---------|------|------|
| 1 | Thread-safe chunking (§14.1.4) | Yüksek | Düşük |
| 2 | Async lock ile talimat cache (§14.1.3) | Yüksek | Düşük |
| 3 | Gerçek token sayacı — tiktoken (§14.1.2) | Yüksek | Orta |
| 4 | Docker socket riski azaltma (§14.6.1) | Yüksek | Düşük |
| 5 | Sandbox çıktı boyutu limiti (§14.6.3) | Orta | Düşük |
| 6 | Kalıcı rate limiting (§14.1.1) | Orta | Orta |
| 7 | RRF ile hibrit sıralama (§14.3.1) | Orta | Orta |
| 8 | JWT / API key auth (§14.4.4) | Orta | Orta |
| 9 | Issue yönetimi (§14.5.2) | Orta | Yüksek |
| 10 | Web UI modülarizasyonu (§14.4.1) | Düşük | Yüksek |

---

*Bu rapor, projedeki tüm kaynak dosyaların satır satır incelenmesiyle 2026-03-07 tarihinde hazırlanmıştır.*
