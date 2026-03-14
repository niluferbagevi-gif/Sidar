# Sürüm Geçmişi (Changelog)

## [v3.0.0] - 2026-03-11
Bu sürüm, SİDAR'ın kurumsal/SaaS odaklı v3.0 kapanış sürümüdür.

### ✅ Öne çıkanlar
* **Kurumsal veri katmanı:** Alembic migration zinciri, SQLite→PostgreSQL cutover rehberi ve CI dry-run/prova kapıları.
* **Multi-Agent varsayılan mimari:** Supervisor + Coder + Researcher + Reviewer akışının üretim odağında olgunlaştırılması.
* **Güvenlik ve erişim:** Bearer auth, admin panel, WebSocket auth-handshake ve graceful session-expiry UX.
* **Gözlemlenebilirlik:** Prometheus metrikleri + Grafana provisioning/dashboard ile maliyet/hata/kullanıcı görünürlüğü.
* **Sandbox operasyonu:** gVisor/Kata host runtime otomasyon scripti ve rollout dokümantasyonu.

### Added (Eklenenler)
* **[Veritabanı Altyapısı]:** Kalıcılık katmanı JSON modelinden async PostgreSQL + Alembic migration temeline taşındı.
* **[Web Arayüzü]:** WebSocket destekli gerçek zamanlı Web UI üretim akışına alındı.
* **[Güvenli Kod Çalıştırma]:** Zero-Trust Docker REPL sandbox entegrasyonu ile ajan kod yürütme yolu izole edildi.
* **[Telemetri ve İzleme]:** Prometheus + Grafana hattı ile token/maliyet/gecikme görünürlüğü üretim seviyesine çıkarıldı.

### ✅ Ödenmiş teknik borçlar (v3.0 kapanış)
* **[Çözüldü] JSON tabanlı bellek kırılganlığı:** Kalıcılık DB katmanına taşındı; kullanıcı/oturum verileri UUID ve zaman damgası odaklı kayıt modeliyle yönetiliyor.
* **[Çözüldü] Senkron darboğazlar:** Kritik çağrı yolları async modele geçirildi (`httpx`/async servis akışları) ve blocking etkisi azaltıldı.
* **[Çözüldü] Tek ajan sınırı:** Supervisor-first çoklu ajan (Coder/Researcher/Reviewer) + P2P delegasyon/QA döngüsü üretim akışına alındı.
* **[Çözüldü] İzolasyon-güvenlik açığı:** Docker sandbox, path/symlink/blacklist kontrolleri ve auth katmanı sertleştirmeleri ile Zero-Trust çizgisi güçlendirildi.
* **[Çözüldü] Test/CI kalite eşiği:** GitHub Actions kalite kapıları, migration kontrolleri ve coverage hard gate (%95) operasyonel standarda bağlandı.

#### Önceki Denetimlerde (Audit) Çözüldüğü Doğrulanan Diğer Maddeler
| Madde | Doğrulama | Dosya / Referans |
|-------|-----------|-----------------|
| CLI `asyncio.Lock` lifetime hatası | ✅ `_interactive_loop_async()` tek async fonksiyon; `asyncio.run()` döngü dışında | `cli.py:1` |
| RAG oturum izolasyonu | ✅ `session_id` filtresi ChromaDB `where=` ve SQLite `WHERE` clause | `rag.py:_fetch_chroma`, `_fetch_bm25` |
| RRF hibrit sıralama | ✅ `_rrf_search()` k=60, her iki motordan bağımsız getirme | `rag.py:_rrf_search` |
| Sliding window özetleme | ✅ `apply_summary()` son `keep_last`=4 mesajı korur | `memory.py:apply_summary` |
| Web UI modülarizasyonu | ✅ 6 ayrı dosya; `StaticFiles` mount aktif | `web_server.py`, `web_ui/` |
| Bearer Token Auth | ✅ `basic_auth_middleware` + `auth_tokens` doğrulaması | `web_server.py`, `core/db.py` |
| DDoS rate limit | ✅ `ddos_rate_limit_middleware` 120 istek/60 sn; `/static/` muaf | `web_server.py` |
| LLM istemci yeniden yapılandırma | ✅ `BaseLLMClient` ABC + 3 concrete impl | `llm_client.py` |
| DuckDuckGo timeout koruması | ✅ `asyncio.wait_for` + doğru except sırası | `web_search.py` |
| GitHub Issue yönetimi | ✅ list/create/comment/close; 4 metod + 4 ajan aracı | `github_manager.py`, `tooling.py` |
| PR diff aracı | ✅ `get_pull_request_diff(pr_number)` + `github_pr_diff` ajan aracı | `github_manager.py` |
| `scan_project_todos` | ✅ `TodoManager.scan_project_todos()` + `ScanProjectTodosSchema` | `todo_manager.py`, `tooling.py` |
| Non-root Docker kullanıcısı | ✅ `sidaruser` uid=10001 | `Dockerfile` |
| Docker health check | ✅ web modunda `/status`, CLI'de PID 1 kontrol | `Dockerfile` |
| RAG pre-cache | ✅ `PRECACHE_RAG_MODEL=true` build-arg ile `all-MiniLM-L6-v2` önceden indirilir | `Dockerfile` |
| SQLite FTS5 disk tabanlı BM25 | ✅ `_init_fts()` PersistentClient; `unicode61 remove_diacritics 1` tokenizer | `rag.py:_init_fts` |
| Prometheus metrikleri | ✅ `update_prometheus_metrics()` + lazy Gauge init | `system_health.py` |
| OpenAI istemci | ✅ `OpenAIClient` + `response_format: json_object` | `llm_client.py` |
| Drag-drop dosya yükleme | ✅ `/api/rag/upload` endpoint; temp dizin temizleme | `web_server.py` |
| Coverage zorunluluğu (global %70 + kritik modüller %80) | ✅ `run_tests.sh` içinde iki aşamalı `pytest --cov` kapısı tanımlı | `run_tests.sh` |
| Performans benchmark baseline'ları | ✅ `tests/test_benchmark.py` ile ChromaDB/BM25/regex hedef eşikleri doğrulanıyor | `tests/test_benchmark.py` |



### 🧹 Audit Geçişi Konsolidasyonu (v2.x → v3.0)
* **Rapor düzeltmeleri sadeleştirildi:** Satır sayısı/test sayısı düzeltmeleri ana rapordan çıkarılarak yalnızca kalıcı teknik sonuçlar bırakıldı.
* **CLI kilitlenme düzeltmesi kalıcılandı:** Tek event-loop yaklaşımı (`_interactive_loop_async` + kontrollü `asyncio.run`) doğrulandı.
* **WebSocket sohbet altyapısı kalıcılandı:** `/ws/chat` hattının üretim kullanımında olduğu audit geçişlerinde tekrar doğrulandı.
* **Sandbox çıktı güvenlik sınırı korundu:** Kod çalıştırma çıktısı için üst limit yaklaşımı audit geçiş notlarına göre stabil kaldı.
* **Redis rate limiting fallback mimarisi doğrulandı:** Redis + bellek içi fallback yaklaşımı v3.0 geçişinde korunarak devam etti.
* **`/file-content` boyut limiti kapatıldı:** `MAX_FILE_CONTENT_BYTES = 1_048_576` ve `413 Payload Too Large` yanıtı ile sınırsız okuma riski kapatıldı.


## [v2.10.8] - 2026-03-10
Bu sürümde RAG cold-start optimizasyonu tamamlandı ve Anthropic (Claude) sağlayıcı desteği eklendi.

### ✅ RAG Soğuk Başlangıç İyileştirmesi
* **Startup prewarm (`web_server.py`):** FastAPI lifespan başlangıcında `_prewarm_rag_embeddings()` görevi ile Chroma/embedding hazırlığı arka planda tetiklenir.
* **Kullanıcı deneyimi:** İlk RAG çağrısındaki model yükleme gecikmesi sunucu başlangıcına taşındı.

### ✅ Anthropic (Claude) Sağlayıcı Desteği
* **Yeni istemci (`core/llm_client.py`):** `AnthropicClient` eklendi; non-stream ve stream chat akışları desteklenir.
* **Yapılandırma (`config.py`, `.env.example`):** `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL`, `ANTHROPIC_TIMEOUT` değişkenleri eklendi.
* **Başlatıcı/UI/bağımlılıklar:** CLI ve launcher provider seçeneklerine `anthropic` eklendi; Web UI model seçim listesi güncellendi; `requirements.txt` ve `environment.yml` dosyalarına `anthropic` paketi eklendi.

## [v2.10.7] - 2026-03-08
Bu sürümde çoklu ortam (environment) yapılandırma desteği tamamlandı.

### ✅ Çevre Başına Konfigürasyon
* **Ortam bazlı dotenv yükleme (`config.py`):** `SIDAR_ENV` değişkeni ile `.env.development`, `.env.production`, `.env.test` gibi dosyalar temel `.env` üzerine `override=True` ile yüklenebilir hale getirildi.

## [v2.10.6] - 2026-03-08
Bu sürümde GitHub entegrasyonu pull modelden webhook tabanlı push modele genişletildi.

### ✅ GitHub Webhook Desteği
* **Webhook alıcısı (`web_server.py`):** Push, Pull Request ve Issue event'lerini dinleyen `POST /api/webhook` endpoint'i eklendi.
* **HMAC doğrulaması (`web_server.py`, `config.py`):** `X-Hub-Signature-256` başlığı `GITHUB_WEBHOOK_SECRET` ile doğrulanır; geçersiz imza istekleri `401` ile reddedilir.
* **Ajan belleği bildirimi (`web_server.py`):** Doğrulanan webhook event'leri `[GITHUB BİLDİRİMİ]` formatında konuşma belleğine asenkron olarak yazılır.

## [v2.10.5] - 2026-03-08
Bu sürümde güvenlik seviyesi geçişleri ajanın kalıcı sohbet belleğine işlenecek şekilde geliştirildi.

### ✅ Güvenlik Seviyesi Geçiş Logu
* **Runtime seviye değişimi (`managers/security.py`, `agent/sidar_agent.py`):** `SecurityManager.set_level(...)` ve `SidarAgent.set_access_level(...)` eklendi; seviye değişimleri `[GÜVENLİK BİLDİRİMİ]` formatında konuşma belleğine kalıcı olarak yazılıyor.
* **CLI ve Web entegrasyonu (`cli.py`, `web_server.py`):** CLI'da `.level <seviye>` komutu ile dinamik seviye değişimi desteklendi; Web API tarafına `POST /set-level` endpoint'i eklendi.

## [v2.10.4] - 2026-03-08
Bu sürümde Web API dokümantasyonu OpenAPI/Swagger standardına yükseltilmiştir.

### ✅ Web API Dokümantasyon İyileştirmeleri
* **OpenAPI Şema Belgelendirmesi (`web_server.py`):** FastAPI `/docs` ve `/redoc` arayüzleri aktif edildi. Kritik API uç noktalarına (`/status`, `/health`, `/sessions`, `/rag/search`, `/rag/add-file`, `/clear`) `summary`, `description` ve `responses` detayları eklendi.

## [v2.10.3] - 2026-03-08
Bu sürümde test kalite kapıları ve performans baseline ölçümleri CI/test akışına entegre edilmiştir.

### ✅ Test ve Kalite İyileştirmeleri
* **Test Coverage Hedefleri (`run_tests.sh`):** CI süreçleri için global `%70` (`--cov-fail-under=70`) ve kritik çekirdek modüller (`managers.security`, `core.memory`, `core.rag`) için `%80` (`--cov-fail-under=80`) kapsam zorunluluğu eklendi.
* **Performans Benchmark (`tests/test_benchmark.py`):** Kritik RAG (ChromaDB, BM25) ve AutoHandle regex yolları için `pytest-benchmark` tabanlı otomatik hız testleri sisteme entegre edildi.

## [v2.9.0] - 2026-03-08
Bu sürümde RAG motoru ve konuşma belleği katmanında izolasyon, sıralama kalitesi ve ölçeklenebilirlik odaklı iyileştirmeler tamamlanmıştır.

### ✅ Çözülen RAG ve Bellek İyileştirmeleri
* **Hibrit Sıralama (RRF) (`core/rag.py`):** `auto` modda ChromaDB ve BM25 sonuçları Reciprocal Rank Fusion (RRF) ile birleştirilerek daha tutarlı top-k geri çağırma sağlandı.
* **BM25 Disk Motoru (`core/rag.py`):** RAM içi `rank_bm25` akışı kaldırılarak SQLite FTS5 tabanlı kalıcı BM25 indeksine geçildi (`bm25_fts.db`, `bm25_index`).
* **Çok Oturumlu RAG İzolasyonu (`core/rag.py`, `agent/sidar_agent.py`, `web_server.py`):** `session_id` filtrelemesi ChromaDB/BM25/keyword yollarına ve RAG endpoint akışına taşındı; oturumlar arası veri sızıntısı engellendi.
* **Sliding-Window Bellek Özetleme (`core/memory.py`, `agent/sidar_agent.py`):** `apply_summary()` son mesajları koruyan pencere stratejisiyle güncellendi; `MEMORY_SUMMARY_KEEP_LAST` ile yapılandırılabilir hale getirildi.

### 🔎 PROJE_RAPORU §14.3 Eşlemesi (Referans)
* **14.3.1 Hibrit Sıralama (RRF)** → `core/rag.py` içinde `_rrf_search()` ve birleşik skor akışı aktif.
* **14.3.2 BM25 Corpus Ölçeklenebilirliği** → SQLite FTS5 tabanlı disk indeks (`bm25_index`) kullanımı aktif.
* **14.3.3 Çok Oturumlu RAG İzolasyonu** → `session_id` filtreleme ve endpoint geçişleri aktif.
* **14.3.4 Bellek Özetleme Stratejisi Seçimi** → `ConversationMemory.apply_summary()` sliding-window yaklaşımıyla çalışıyor.

### 🔎 PROJE_RAPORU §14.5 Eşlemesi (Referans)
* **14.5.2 Issue Yönetimi** → `managers/github_manager.py` içinde `list_issues/create_issue/comment_issue/close_issue` akışları ve ajan tarafında karşılık gelen `github_*_issue` araçları aktif.
* **14.5.3 Diff Analizi** → `managers/github_manager.py` içinde `get_pull_request_diff()` ve ajan tarafında `github_pr_diff` aracı aktif.

### 🔎 PROJE_RAPORU §14.6 Eşlemesi (Referans)
* **14.6.1 Docker Socket Riski Azaltma** → `docker-compose.yml` içinde `/var/run/docker.sock` yalnızca CLI/REPL servislerinde bırakıldı; web servislerinden kaldırıldı.
* **14.6.2 Denetim Logu (Audit Log)** → `agent/sidar_agent.py` içinde araç çağrıları `logs/audit.jsonl` dosyasına yapısal JSONL olarak yazılıyor.
* **14.6.3 Sandbox Çıktı Boyutu Limiti** → `managers/code_manager.py` içinde `max_output_chars=10000` limiti ile Docker/lokal/shell çıktıları kırpılıyor.

### 🔎 PROJE_RAPORU §14.7 Eşlemesi (Referans)
* **14.7.1 Entegrasyon Test Altyapısı** → `pytest.ini` ile keşif/asenkron mod standardize edildi, `environment.yml` içinde `pytest` + `pytest-asyncio` tanımlandı ve `run_tests.sh` ile tek komut çalıştırma akışı mevcut.
* **14.7.5 Otonom TODO/FIXME Tarama** → `TodoManager.scan_project_todos(...)` ile tarama, `ScanProjectTodosSchema` ile şemalı argüman doğrulama ve ajan tarafında `_tool_scan_project_todos` (non-blocking `asyncio.to_thread`) akışı aktif.

### 🔎 PROJE_RAPORU §14.8 Eşlemesi (Referans)
* **14.8.1 Sağlık Endpoint Genişletmesi** → `SystemHealthManager.get_health_summary()` + `GET /health` endpoint akışı aktif; yanıta `uptime_seconds` ekleniyor ve `AI_PROVIDER=ollama` + erişim yoksa `status=degraded` ile `503` dönülüyor.

## [v2.8.0] - 2026-03-08
Bu sürümde kurumsal düzeyde AI Ajan (Agent) mimarisine, çoklu model desteğine ve Model Context Protocol (MCP) standartlarına geçiş yapılmıştır.

### ✅ Çözülen LLM ve Ajan Katmanı İyileştirmeleri (Mimari Değişiklikler)
* **Çoklu LLM Sağlayıcı Genişletmesi (`core/llm_client.py`):** `BaseLLMClient` soyut sınıfı oluşturularak Nesne Yönelimli (OOP) yapıya geçildi. Ollama ve Gemini'nin yanına yapısal stream destekli **OpenAI (GPT-4o)** sağlayıcısı eklendi.
* **Yapısal Araç Şemaları ve MCP Uyumu (`agent/tooling.py`):** Araçların aldığı argümanlar güvensiz string ayrıştırmasından kurtarılarak Pydantic `BaseModel` şemalarına bağlandı. LLM çıktıları JSON Schema kullanılarak yapısal (Structured Output) hale getirildi.
* **Araç Tanımlarının Dışsallaştırılması (`agent/sidar_agent.py`):** Ajan içindeki hardcoded `_tools` sözlüğü dış modüle taşındı, modülerleştirildi ve Pydantic validasyon ağına (`ToolCall`) entegre edildi.
* **Paralel ReAct Adımları (`agent/sidar_agent.py`):** ReAct döngüsü, LLM'den gelen JSON listelerini (Array) yakalayacak şekilde güncellendi. Sadece güvenli okuma/sorgulama araçları filtre edilerek `asyncio.gather` ile tam paralel çalıştırılabilir hale getirildi. Hantal `parallel` aracı kullanımdan kaldırıldı.

### ✅ Çözülen Teknik Borçlar ve Stabilite İyileştirmeleri
* **Web Arama / DuckDuckGo Güvenliği (`managers/web_search.py`, `environment.yml`):** DuckDuckGo arama motoru (DDGS) paketi `6.2.13` sürümüne sabitlendi. Gelecek versiyonlardaki mimari API değişikliklerine karşı koruma sağlamak için dinamik `AsyncDDGS` kontrolü eklendi ve thread'lerin asılı kalmasını (hang) önlemek amacıyla arama işlemlerine `asyncio.wait_for` ile zaman aşımı (timeout) koruması getirildi.
* **Web UI Modülarizasyonu (`web_ui/index.html`, `web_server.py`):** 3.300+ satırlık devasa HTML dosyası parçalanarak `style.css`, `app.js`, `chat.js`, `sidebar.js` ve `rag.js` modüllerine ayrıldı. FastAPI `StaticFiles` ara katmanı (middleware) eklenerek statik asset'lerin performanslı ve güvenli bir şekilde sunulması sağlandı. Ön yüzün (frontend) test edilebilirliği ve sürdürülebilirliği kurumsal standartlara taşındı.

### 🔎 PROJE_RAPORU §14.4 Eşlemesi (Referans)
* **14.4.1 Web UI Modülarizasyonu** → UI katmanı `index.html + style.css + app.js + chat.js + sidebar.js + rag.js` olarak ayrıştırıldı ve `/static` mount ile servis ediliyor.
* **14.4.4 Kimlik Doğrulama** → Web katmanında `API_KEY` tabanlı HTTP Basic Auth middleware akışı aktif (`API_KEY` boşsa bypass, doluysa zorunlu kimlik doğrulama).

## [v2.7.0] - 2026-03-07
Bu sürümde asenkron güvenlik, performans ve stabilite iyileştirmelerine odaklanılmıştır.

### ✅ Çözülen Yüksek Öncelikli Sorunlar
* **`core/rag.py` (Thread-Safety):** `_chunk_text()` içindeki geçici sınıf değişkeni değişimi lokal değişkenlere alınarak race condition engellendi. Sıfıra bölme ve sonsuz döngü koruması eklendi.
* **`core/rag.py` (Performans):** `_bm25_search()` içindeki skor hesaplaması `_write_lock` kapsamı dışına çıkarılarak thread bloklanması önlendi.
* **`agent/sidar_agent.py` (Cache Güvenliği):** `_instructions_cache` okuma/yazma işlemleri `threading.Lock` ile asenkron çakışmalara karşı koruma altına alındı.

### ✅ Çözülen Orta Öncelikli Sorunlar
* **`web_server.py` (Rate Limiting):** İstek sınırlandırması `defaultdict` yerine `cachetools.TTLCache` entegrasyonu ile kalıcı hale getirildi.
* **`core/memory.py` (Token Optimizasyonu):** Tahmini token hesabı yerine `tiktoken` kütüphanesi ile gerçek tokenizer entegrasyonu yapıldı.
* **`docker-compose.yml` (Güvenlik):** `sidar-web` ve `sidar-web-gpu` servislerinden `/var/run/docker.sock` erişimi kaldırılarak container escape zafiyeti giderildi.
* **`managers/github_manager.py` (API Güvenliği):** `list_commits` metodunda limit aşımlarında kullanıcıya açık uyarı dönecek şekilde düzenleme yapıldı.

### 🔎 PROJE_RAPORU §14.1 Eşlemesi (Referans)
* **14.1.1 Kalıcı Rate Limiting** → `web_server.py` üzerinde `TTLCache` tabanlı kalıcı pencere sınırlandırması uygulandı.
* **14.1.2 Gerçek Token Sayacı** → `core/memory.py` içinde `tiktoken` entegrasyonu aktif.
* **14.1.3 Talimat Cache Koruması** → `agent/sidar_agent.py` içinde `_instructions_cache` akışı `threading.Lock` ile korunuyor.
* **14.1.4 Thread-Safe Chunking** → `core/rag.py` içinde chunking adımında güvenli `step=max(1, size-overlap)` koruması mevcut.

### ✅ Çözülen Düşük Öncelikli / Teknik Borçlar
* **`agent/auto_handle.py`:** Çok adımlı regex kalıbına İngilizce bağlaçlar (`first`, `then`, `step`, vb.) eklendi.
* **`config.py`:** İçe aktarma anında çalışan dizin oluşturma komutları `__main__` koruması altına alınarak test ortamı izole edildi.