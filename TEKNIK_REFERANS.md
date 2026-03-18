# Sidar v3.0.0 — Teknik Referans ve Operasyon Kılavuzu

Bu doküman, Sidar projesinin **uygulama seviyesinde teknik sözleşmelerini** (DB şeması, endpoint envanteri, WebSocket protokolü, agent akışı, operasyon parametreleri) toplar.

> Mimari değerlendirme, üst düzey güvenlik özeti, test kapsamı ve roadmap için `PROJE_RAPORU.md` dosyasını kullanın.

---

## İçindekiler
- [1. Mimari Kapsam ve Bileşenler](#1-mimari-kapsam-ve-bileşenler)
- [2. Veri Katmanı (core/db.py)](#2-veri-katmanı-coredbpy)
  - [2.1 Backend seçimi ve bağlantı modeli](#21-backend-seçimi-ve-bağlantı-modeli)
  - [2.2 Tablo şemaları ve ilişkiler](#22-tablo-şemaları-ve-ilişkiler)
  - [2.3 Kimlik doğrulama ve token yaşam döngüsü](#23-kimlik-doğrulama-ve-token-yaşam-döngüsü)
  - [2.4 Kota/FinOps yazma-okuma akışı](#24-kotafinops-yazma-okuma-akışı)
- [3. API Sunucusu (web_server.py)](#3-api-sunucusu-web_serverpy)
  - [3.1 Middleware sırası ve güvenlik davranışı](#31-middleware-sırası-ve-güvenlik-davranışı)
  - [3.2 REST endpoint envanteri (tam)](#32-rest-endpoint-envanteri-tam)
  - [3.3 WebSocket protokolü: `/ws/chat`](#33-websocket-protokolü-wschat)
  - [3.4 Telemetri ve metrik endpointleri](#34-telemetri-ve-metrik-endpointleri)
- [4. Agent Orkestrasyonu ve Tooling](#4-agent-orkestrasyonu-ve-tooling)
  - [4.1 Supervisor-first çalışma modeli](#41-supervisor-first-çalışma-modeli)
  - [4.2 Tool dispatch envanteri](#42-tool-dispatch-envanteri)
  - [4.3 Reviewer/QA döngüsü](#43-reviewerqa-döngüsü)
  - [4.4 Prompt/Context inşası (`sidar_agent.py`)](#44-promptcontext-inşası-sidar_agentpy)
  - [4.5 Bellek sıkıştırma ve `memory_archive` akışı](#45-bellek-sıkıştırma-ve-memory_archive-akışı)
- [5. Konfigürasyon Referansı](#5-konfigürasyon-referansı)
  - [5.1 `.env` katmanlama (`SIDAR_ENV`)](#51-env-katmanlama-sidar_env)
  - [5.2 Config tarafından okunan env anahtarları (tam liste)](#52-config-tarafından-okunan-env-anahtarları-tam-liste)
  - [5.3 Docker Compose override değişkenleri](#53-docker-compose-override-değişkenleri)
- [6. Güvenlik ve İzolasyon Notları](#6-güvenlik-ve-izolasyon-notları)
- [7. Operasyon Runbook (kısa)](#7-operasyon-runbook-kısa)
- [8. Bakım Prensibi (SoC)](#8-bakım-prensibi-soc)

---

## 1. Mimari Kapsam ve Bileşenler

Sidar v3.0.0 teknik akışının ana bileşenleri:

- **Web/API katmanı:** `web_server.py` (FastAPI, WebSocket, middleware, auth, rate-limit, RAG/GitHub endpointleri)
- **Agent katmanı:** `agent/sidar_agent.py` + `agent/core/supervisor.py` + `agent/roles/*`
- **Veri katmanı:** `core/db.py` (SQLite + PostgreSQL uyumlu async erişim)
- **Güvenlik/çalıştırma:** `managers/security.py`, `managers/code_manager.py`
- **Dağıtım:** `docker-compose.yml`

Bu kılavuzdaki tüm başlıklar, doğrudan mevcut repo kod akışlarına göre hazırlanmıştır.

---

## 2. Veri Katmanı (core/db.py)

### 2.1 Backend seçimi ve bağlantı modeli

- `DATABASE_URL` `postgresql://` veya `postgresql+asyncpg://` ile başlıyorsa backend **PostgreSQL** seçilir.
- Aksi durumda backend **SQLite** (`sqlite+aiosqlite:///data/sidar.db`) olarak çalışır.
- PostgreSQL’de `asyncpg.create_pool(min_size=1, max_size=DB_POOL_SIZE)` kullanılır.
- SQLite’da thread-safe bağlantı için `check_same_thread=False`, `PRAGMA foreign_keys=ON`, `journal_mode=WAL` açılır.

### 2.2 Tablo şemaları ve ilişkiler

#### Kimlik/Oturum taban tabloları

1. `users`
   - PK: `id`
   - Alanlar: `username` (unique), `password_hash`, `role`, `created_at`
2. `auth_tokens`
   - PK: `token`
   - FK: `user_id -> users.id` (`ON DELETE CASCADE`)
   - Alanlar: `expires_at`, `created_at`
3. `sessions`
   - PK: `id`
   - FK: `user_id -> users.id` (`ON DELETE CASCADE`)
   - Alanlar: `title`, `created_at`, `updated_at`
4. `messages`
   - PK: `id`
   - FK: `session_id -> sessions.id` (`ON DELETE CASCADE`)
   - Alanlar: `role`, `content`, `tokens_used`, `created_at`

#### FinOps/Kota tabloları

5. `user_quotas`
   - PK/FK: `user_id -> users.id`
   - Alanlar: `daily_token_limit`, `daily_request_limit`
6. `provider_usage_daily`
   - PK: `id`
   - FK: `user_id -> users.id`
   - Alanlar: `provider`, `usage_date`, `requests_used`, `tokens_used`
   - Benzersizlik: `(user_id, provider, usage_date)`

#### İndeksler

- `idx_sessions_user_id`
- `idx_messages_session_id`
- `idx_auth_tokens_user_id`
- `idx_provider_usage_daily_user_id`

### 2.3 Kimlik doğrulama ve token yaşam döngüsü

- Şifre hash: `PBKDF2-HMAC-SHA256` (`pbkdf2_sha256$<salt>$<digest>`)
- Token üretimi: `secrets.token_urlsafe(48)`
- Varsayılan token TTL: `7 gün`
- `get_user_by_token()` sorgusu, `expires_at > now` filtresiyle geçerlilik kontrolü yapar.
- **Önemli:** PBKDF2 hashleme `password_hash` alanı içindir; `auth_tokens.token` değeri DB'de plain (rastgele üretilmiş bearer token) tutulur.

### 2.4 Kota/FinOps yazma-okuma akışı

- Kullanım yazımı: `record_provider_usage_daily(user_id, provider, tokens_used, requests_inc)`
- Kota güncelleme: `upsert_user_quota(...)`
- Kota okuma/ihlal kontrolü: `check_user_quota(...)`
- Admin görünümü: `get_admin_stats()` toplam token/istek + kullanıcı kota listesi döner.

---

## 3. API Sunucusu (web_server.py)

### 3.1 Middleware sırası ve güvenlik davranışı

`web_server.py` içinde güvenlik/limit middleware’leri şu sorumluluklarla çalışır:

1. **`basic_auth_middleware`**
   - Bearer token zorlar (`Authorization: Bearer <token>`)
   - `request.state.user` bağlar
   - Open-path listesi için auth bypass uygular (`/auth/*`, docs, metrics, health vb.)
2. **`ddos_rate_limit_middleware`**
   - IP bazlı genel DDoS koruması (`120 req / 60s`)
3. **`rate_limit_middleware`**
   - Endpoint türüne göre ayrı limit sınıfları:
     - chat/ws
     - mutasyon (`POST/DELETE`)
     - yoğun `GET` IO path’leri

Rate-limit katmanı Redis erişemezse local bellek fallback mekanizmasıyla çalışmaya devam eder.

### 3.2 REST endpoint envanteri (tam)

Aşağıdaki envanter, `@app.get/post/delete` dekoratörlerinden çıkarılmış **tam** listedir. Güncel kod tabanında **60 REST endpoint** bulunmaktadır; v3.0.26 turunda Vision, EntityMemory, FeedbackStore ve Slack/Jira/Teams entegrasyon yüzeyleri de HTTP katmanına bağlanmıştır.

| Method | Path | Not |
|---|---|---|
| POST | `/auth/register` | Kayıt |
| POST | `/auth/login` | Giriş + token |
| GET | `/auth/me` | Token doğrulama |
| GET | `/admin/stats` | Admin istatistik |
| GET | `/admin/prompts` | Prompt registry listesi (admin) |
| GET | `/admin/prompts/active` | Aktif prompt kaydı (admin) |
| POST | `/admin/prompts` | Prompt ekle / güncelle (admin) |
| POST | `/admin/prompts/activate` | Prompt aktifleştir (admin) |
| GET | `/admin/policies/{user_id}` | Kullanıcı erişim politika listesi (admin) |
| POST | `/admin/policies` | Erişim politikası ekle / güncelle (admin) |
| POST | `/api/agents/register` | Plugin ajan kayıt (source_code) (admin) |
| POST | `/api/agents/register-file` | Plugin ajan kayıt (dosya yolu) (admin) |
| POST | `/api/swarm/execute` | SwarmOrchestrator görevi çalıştır |
| GET | `/api/hitl/pending` | Bekleyen HITL istekleri |
| POST | `/api/hitl/request` | Yeni HITL isteği oluştur |
| POST | `/api/hitl/respond/{request_id}` | HITL onay/red yanıtı |
| GET | `/favicon.ico` | 204 |
| GET | `/vendor/{file_path:path}` | Vendor statik servis |
| GET | `/` | UI index |
| GET | `/status` | Ajan durum özeti |
| GET | `/health` | Sağlık kontrolü |
| GET | `/metrics` | Sistem metrikleri (admin veya METRICS_TOKEN) |
| GET | `/metrics/llm/prometheus` | OpenMetrics text (admin veya METRICS_TOKEN) |
| GET | `/metrics/llm` | LLM metrik JSON (admin veya METRICS_TOKEN) |
| GET | `/api/budget` | LLM bütçe JSON (admin veya METRICS_TOKEN) |
| GET | `/sessions` | Kullanıcı oturum listesi |
| GET | `/sessions/{session_id}` | Oturum geçmişi |
| POST | `/sessions/new` | Yeni oturum |
| DELETE | `/sessions/{session_id}` | Oturum sil |
| GET | `/files` | Proje içi dosya listesi |
| GET | `/file-content` | Güvenli dosya okuma (uzantı + 1 MB boyut limiti) |
| GET | `/git-info` | branch/repo/default-branch |
| GET | `/git-branches` | branch listesi |
| POST | `/set-branch` | branch değiştir |
| GET | `/github-repos` | erişilebilir repo listesi |
| GET | `/github-prs` | PR listesi |
| GET | `/github-prs/{number}` | PR detay |
| POST | `/set-repo` | aktif repo ayarla |
| GET | `/rag/docs` | RAG doküman listesi |
| POST | `/rag/add-file` | RAG’e yerel dosya ekle |
| POST | `/rag/add-url` | RAG’e URL ekle |
| DELETE | `/rag/docs/{doc_id}` | RAG doküman sil |
| POST | `/api/rag/upload` | upload ile RAG ekleme (max 50 MB, HTTP 413 limit) |
| GET | `/rag/search` | RAG arama |
| GET | `/todo` | görev listesi |
| POST | `/clear` | bellek temizleme |
| POST | `/set-level` | güvenlik seviyesi değişimi (yalnızca admin) |
| POST | `/api/vision/analyze` | Base64 görüntü analizi |
| POST | `/api/vision/mockup` | Mockup → kod dönüşümü |
| POST | `/api/memory/entity/upsert` | Persona/Entity kaydı ekle-güncelle |
| GET | `/api/memory/entity/{user_id}` | Kullanıcı entity profili |
| DELETE | `/api/memory/entity/{user_id}/{key}` | Entity kaydı sil |
| POST | `/api/feedback/record` | Active Learning geri bildirimi kaydet |
| GET | `/api/feedback/stats` | FeedbackStore istatistikleri |
| POST | `/api/integrations/slack/send` | Slack mesaj gönder |
| GET | `/api/integrations/slack/channels` | Slack kanal listesi |
| POST | `/api/integrations/jira/issue` | Jira issue oluştur |
| GET | `/api/integrations/jira/issues` | Jira issue ara (JQL) |
| POST | `/api/integrations/teams/send` | Teams mesaj gönder |
| POST | `/api/webhook` | GitHub webhook (HMAC-SHA256 doğrulama) |

### 3.3 WebSocket protokolü: `/ws/chat`

- Endpoint: `/ws/chat`
- **Öncelikli kimlik doğrulama:** HTTP upgrade sırasında `Sec-WebSocket-Protocol` başlığında Bearer token gönderilir; bağlantı kabul edilmeden önce doğrulama yapılır (O-5 çözümü).
- **Fallback:** Başlık yoksa bağlantı kurulduktan sonraki ilk JSON mesajında `{"action":"auth","token":"..."}` beklenir.
- Geçersiz veya eksik auth → `1008 Policy Violation`
- Başlıca istemci aksiyonları:
  - `auth` (fallback kimlik doğrulama)
  - `message` (metin)
  - `cancel` (aktif task iptali)
- Sunucu stream eventleri:
  - `{"status": "<source>: <message>"}` (event bus)
  - `{"thought": "..."}` (`\x00THOUGHT:` sentinel)
  - `{"tool_call": "..."}` (`\x00TOOL:` sentinel)
  - `{"chunk": "..."}` (token/metin stream)
  - `{"done": true}`

### 3.4 Telemetri ve metrik endpointleri

- `/metrics`:
  - Prometheus client kuruluysa OpenMetrics payload üretir
  - Aksi durumda JSON fallback döndürür
- `/metrics/llm/prometheus`:
  - LLM collector snapshot’unu text/plain olarak döndürür
- `/metrics/llm` ve `/api/budget`:
  - Aynı handler, collector snapshot JSON döner

---

## 4. Agent Orkestrasyonu ve Tooling

### 4.1 Supervisor-first çalışma modeli

- `SidarAgent.respond()` çağrıları Supervisor omurgasına yönlendirilir.
- `SupervisorAgent` içinde QA geri besleme limiti `MAX_QA_RETRIES = 3` olarak sabittir.
- `ENABLE_MULTI_AGENT` bayrağı config sınıfında `True` sabitlenmiş durumdadır (legacy toggle kaldırılmıştır).
- Intent routing kuralları `SupervisorAgent._intent()` içinde anahtar kelime tabanlıdır:
  - `research`: "araştır", "web", "url", "doküman", "search"
  - `review`: "github", "pull request", "issue", "review", "incele"
  - diğer tüm istekler varsayılan olarak `code`
- Legacy tekli ReAct akışı dosyada yardımcı/yedek kod olarak dursa da üretim omurgası Supervisor zinciridir.

### 4.2 Tool dispatch envanteri

`agent/tooling.py::build_tool_dispatch()` ile tek source-of-truth araç haritası üretilir.

Ana gruplar:

- Dosya/kod: `list_dir`, `read_file`, `write_file`, `patch_file`, `execute_code`, `audit`
- GitHub PR: `github_list_prs`, `github_get_pr`, `github_create_pr`, `github_comment_pr`, `github_close_pr`, `github_pr_diff`, `github_smart_pr`, `github_pr_files`
- GitHub Issue: `github_list_issues`, `github_create_issue`, `github_comment_issue`, `github_close_issue`
- RAG/Web: `web_search`, `fetch_url`, `docs_add`, `docs_search`, `docs_list`, `docs_delete`
- Paket sorguları: `pypi`, `pypi_compare`, `npm`, `gh_releases`, `gh_latest`
- Shell/yardımcı: `run_shell` (`bash`, `shell` alias), `glob_search`, `grep_files`, `get_config`
- Todo/plan: `todo_write`, `todo_read`, `todo_update`, `scan_project_todos`
- Delegasyon: `subtask` (`agent` alias), `parallel`

### 4.3 Reviewer/QA döngüsü

- `ReviewerAgent` test komutunu `REVIEWER_TEST_COMMAND` üzerinden alır.
- Güvenli kullanım kısıtı:
  - `bash run_tests.sh` veya `pytest ...` desenleri dışına çıkılmaz.
- Supervisor, reviewer geri bildirimi sonrası coder turunu sınırlı sayıda tekrarlar.

### 4.4 Prompt/Context inşası (`sidar_agent.py`)

Her üretim çağrısında prompt bağlamı katmanlı kurulur:

1. Sistem promptu (`SIDAR_SYSTEM_PROMPT`)
2. Tool listesi (`_build_tool_list()`)
3. Runtime context (`_build_context()`)
   - sağlayıcı/model
   - GPU bilgisi
   - erişim seviyesi
   - RAG durumu
4. Arşiv bağlamı (`_get_memory_archive_context()`)
   - ChromaDB'den `source=memory_archive` filtresiyle geri çağırma

Ek olarak `SIDAR.md` / `CLAUDE.md` talimat dosyaları hiyerarşik şekilde okunup prompta enjekte edilir.

### 4.5 Bellek sıkıştırma ve `memory_archive` akışı

`sidar_agent.py::_summarize_memory()` akışı özetle iki aşamadan oluşur:

1. Eski konuşma turları `memory_archive` etiketiyle vektör depoya arşivlenir.
2. Aktif konuşma penceresi, kısa bir özet + son turlar korunacak şekilde küçültülür.

Bu sayede:
- aktif context token yükü düşer,
- geçmiş bilgi kaybı minimuma iner,
- yeni sorularda arşivden semantik geri çağırma yapılabilir.

Not: `core/memory.py` tarafında aktif kullanıcı zorunluluğu (`_require_active_user`) fail-closed prensibiyle uygulanır; kullanıcı bağlamı yoksa bellek/oturum işlemleri hata verir.

---

## 5. Konfigürasyon Referansı

### 5.1 `.env` katmanlama (`SIDAR_ENV`)

`config.py` yükleme sırası:

1. Temel `.env`
2. Varsa profil dosyası `.env.<sidar_env>`

Böylece `SIDAR_ENV=production` gibi bir değer ile profil bazlı override uygulanır.

### 5.2 Config tarafından okunan env anahtarları (tam liste)

Aşağıdaki liste, `config.py` içindeki `os.getenv/get_*_env` çağrılarından çıkarılmıştır:

```text
ACCESS_LEVEL
AI_PROVIDER
ANTHROPIC_API_KEY
ANTHROPIC_MODEL
ANTHROPIC_TIMEOUT
API_KEY
AUTO_HANDLE_TIMEOUT
CODING_MODEL
DATABASE_URL
DB_POOL_SIZE
DB_SCHEMA_TARGET_VERSION
DB_SCHEMA_VERSION_TABLE
DEBUG_MODE
DOCKER_ALLOWED_RUNTIMES
DOCKER_EXEC_TIMEOUT
DOCKER_MEM_LIMIT
DOCKER_MICROVM_MODE
DOCKER_NANO_CPUS
DOCKER_NETWORK_DISABLED
DOCKER_PYTHON_IMAGE
DOCKER_RUNTIME
ENABLE_TRACING
GEMINI_API_KEY
GEMINI_MODEL
GITHUB_REPO
GITHUB_TOKEN
GITHUB_WEBHOOK_SECRET
GOOGLE_SEARCH_API_KEY
GOOGLE_SEARCH_CX
GPU_DEVICE
GPU_MEMORY_FRACTION
GPU_MIXED_PRECISION
HF_HUB_OFFLINE
HF_TOKEN
LLM_MAX_RETRIES
LLM_RETRY_BASE_DELAY
LLM_RETRY_MAX_DELAY
LOG_BACKUP_COUNT
LOG_FILE
LOG_LEVEL
LOG_MAX_BYTES
MAX_MEMORY_TURNS
MAX_REACT_STEPS
MEMORY_ENCRYPTION_KEY
MEMORY_SUMMARY_KEEP_LAST
MULTI_GPU
OLLAMA_TIMEOUT
OLLAMA_URL
OPENAI_API_KEY
OPENAI_MODEL
OPENAI_TIMEOUT
OTEL_EXPORTER_ENDPOINT
PACKAGE_INFO_CACHE_TTL
PACKAGE_INFO_TIMEOUT
RAG_CHUNK_OVERLAP
RAG_CHUNK_SIZE
RAG_DIR
RAG_FILE_THRESHOLD
RAG_TOP_K
RATE_LIMIT_CHAT
RATE_LIMIT_GET_IO
RATE_LIMIT_MUTATIONS
RATE_LIMIT_WINDOW
REACT_TIMEOUT
REDIS_URL
RESPONSE_LANGUAGE
REVIEWER_TEST_COMMAND
SEARCH_ENGINE
SIDAR_ENV
SUBTASK_MAX_STEPS
TAVILY_API_KEY
TEXT_MODEL
USE_GPU
WEB_FETCH_MAX_CHARS
WEB_FETCH_TIMEOUT
WEB_GPU_PORT
WEB_HOST
WEB_PORT
WEB_SCRAPE_MAX_CHARS
WEB_SEARCH_MAX_RESULTS
```

### 5.3 Docker Compose override değişkenleri

`docker-compose.yml` üzerinden doğrudan kullanılan başlıca override’lar:

- Kaynak limitleri:
  - `SIDAR_CPU_LIMIT`, `SIDAR_MEM_LIMIT`
  - `SIDAR_GPU_CPU_LIMIT`, `SIDAR_GPU_MEM_LIMIT`
  - `SIDAR_WEB_CPU_LIMIT`, `SIDAR_WEB_MEM_LIMIT`
  - `SIDAR_WEB_GPU_CPU_LIMIT`, `SIDAR_WEB_GPU_MEM_LIMIT`
- Portlar:
  - `WEB_PORT`, `WEB_GPU_PORT`
- Ağ/GPU:
  - `HOST_GATEWAY`
  - `NVIDIA_VISIBLE_DEVICES`
  - `NVIDIA_DRIVER_CAPABILITIES`
- Runtime davranış:
  - `AI_PROVIDER`, `OLLAMA_URL`, `GPU_*` değişkenleri

---

## 6. Güvenlik ve İzolasyon Notları

- Path traversal ve kritik yol engelleme regex/pattern kontrolleri `SecurityManager` üzerinde uygulanır.
- Kod yürütme sandbox’ında Docker kaynak limitleri (`mem_limit`, `nano_cpus`) uygulanır.
- İsteğe bağlı ağ kapatma (`network_mode="none"`) desteği vardır.
- Mikro-VM runtime uyumu için runtime çözümleme (`runsc`, `kata-runtime`) `CodeManager` içinde ele alınır.
- GitHub webhook doğrulaması `X-Hub-Signature-256` + `HMAC-SHA256` ile yapılır.
- `/file-content` endpoint’i uzantı allowlist + `1MB` boyut limiti ile korunur.

---

## 7. Operasyon Runbook (kısa)

### 7.1 Başlatma profilleri

- CLI CPU: `sidar-ai`
- CLI GPU: `sidar-gpu`
- Web CPU: `sidar-web`
- Web GPU: `sidar-web-gpu`

### 7.2 Gözlemlenebilirlik

- Prometheus: `:9090`
- Grafana: `:3000`
- Uygulama metrikleri: `/metrics`, `/metrics/llm`, `/metrics/llm/prometheus`

### 7.3 Yedekleme

- PostgreSQL: düzenli `pg_dump`
- SQLite: `data/sidar.db` periyodik snapshot
- RAG veri dizinleri (`data/rag` vb.) için düzenli volume backup

### 7.4 Hızlı sorun giderme

- **WS `1008`**: auth handshake mesajı eksik/yanlış
- **429 artışı**: DDoS limit + endpoint limit + günlük kota birlikte kontrol edilmeli
- **GitHub araçları çalışmıyor**: `GITHUB_TOKEN` + `GITHUB_REPO` doğrula
- **Supervisor izi görünmüyor**: `LOG_LEVEL=DEBUG` + süreç restart

---

## 8. Bakım Prensibi (SoC)

Dokümantasyonda **Separation of Concerns** uygulanır:

- **`PROJE_RAPORU.md`** → üst düzey mimari/denetim/özet
- **`TEKNIK_REFERANS.md`** → operasyonel ve teknik sözleşmeler

Bu ayrım sayesinde:

1. Hedef kitle ayrımı netleşir (yönetici/mimar vs. backend/devops).
2. API/şema değişiklikleri tek teknik dokümanda güncellenir.
3. Ana raporun okunabilirliği korunur (bloat engellenir).