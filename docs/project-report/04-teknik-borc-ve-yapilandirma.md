# Sidar Proje Raporu — Teknik Borç ve Yapılandırma

> Aktif ürün baseline: **v5.2.0**. Bu dosya, [`PROJE_RAPORU.md`](../PROJE_RAPORU.md) indeksinin bölümüdür.

<a id="içindekiler"></a>
## Bu dosyadaki bölümler

- Bölüm 11
- Bölüm 12

---

## 11. Mevcut Sorunlar ve Teknik Borç

> **Snapshot (2026-08-12 — v5.2.0):** Bu bölüm kalıcı bir “0 blocker” beyanı değildir.
> 12 Ağustos yerel doğrulamasında `web/plugins/sandbox.py` create-error yolları ve
> erişilemez cleanup branch'i nedeniyle backend coverage `%99,98` kalmış,
> `production_ready=false` üretilmiş ve merge/release bloke edilmiştir. İlgili branch
> kaldırılıp create timeout, non-zero return code ve boş container-id regresyon testleri
> eklenmiştir; ancak güncel karar her zaman aşağıda tarif edilen artifact ve CI kapılarından
> yeniden okunmalıdır. GitHub GPU evidence tarafında da `ENABLE_GPU_BENCH_GATE=true`,
> `GPU_RUNNER_MONITOR_TOKEN`, iki online `[self-hosted, linux, x64, gpu, cuda]` runner ve başarılı
> GPU inference artifact'ı doğrulanmadan production-ready kabulü yapılamaz.

### 11.1 Durum Özeti Paneli

| Gösterge | Durum |
|---|---|
| Son gözlenen yerel blocker | **2026-08-12: sandbox coverage `%99,98`; bu dalda test/kod düzeltmesi uygulandı, tam gate yeniden doğrulanmalı** |
| Harici evidence durumu | **GitHub GPU watchdog + inference gate + production aggregate sonucu repository ayarları ve runner kapasitesiyle doğrulanmalı** |
| Anlık release kararı | **Statik Markdown'dan verilmez; `artifacts/test-summary.json` ve güncel CI required check'leri kanoniktir** |
| İzlenen Mühendislik Kampanyaları | **Var — TypeScript migrasyonu, D100-D107 docstring envanteri ve modülerleştirme ratchet/planlarla yönetiliyor** |
| Denetim Durumu | **Production-ready kalite kapıları fail-closed; tarihli snapshot başarı garantisi değildir** |
| Son Arşivleme Notu | **Kapanan bulgular `docs/archive/` altında; aktif kampanyalar kendi plan ve baseline dosyalarında tutuluyor** |

- **Stratejik özet:** Ana rapor aktif riskleri izlemek için kullanılır; kapanmış bulgular operasyonel hafıza olarak arşivde tutulur.
- **Versiyon durumu:** Coverage tabanı `pyproject.toml` içinde `%100`, frontend TypeScript
  ilerlemesi ise `web_ui_react/typescript-migration-baseline.json` ile fail-closed izlenir.
  Bir tarihli koşunun geçmesi veya düzeltilmiş bir blocker, sonraki commit için otomatik
  production-ready sonucu oluşturmaz.

#### 11.1.1 Anlık doğruluk kaynağı

Bu rapor bağlam ve tarihli bulgu kaydıdır. Anlık merge/release durumu:

1. yerel doğrulamada `artifacts/test-summary.json` içindeki `production_ready` ve
   `release_blocking` alanlarından;
2. backend coverage artifact'ı ve `%100` ratchet sonucundan;
3. GitHub'daki `GPU Inference Required Evidence Gate` ile
   `Production readiness aggregate` required check'lerinden

okunur. Artifact yoksa, eskiyse veya güncel commit SHA'sına ait değilse durum “bilinmiyor”
sayılır; bu Markdown tablosundaki snapshot release onayı olarak kullanılamaz.

#### 11.1.2 Borç ve yol haritası ayrımı

- **Açık kritik teknik borç:** Merge/release kararını engelleyen, kabul edilmiş fakat
  çözülmemiş kusurdur. Sayısı yalnız güncel artifact/CI sonucundan türetilir.
- **İzlenen mühendislik borcu:** Ürünü bugün bloklamayan fakat tarihli kapanış ve
  geriye gitmeme kapısı bulunan işlerdir. TypeScript migrasyonu, kalan D100-D107
  docstring envanteri ve `docs/REFACTOR_PLAN.md` içindeki modülerleştirme dilimleri bu
  sınıftadır; bu nedenle genel “Açık Teknik Borç: 0” ifadesi kullanılmaz.
- **Gelecek ürün fazı:** Mevcut davranışta kusur olmayan yeni kapasitedir. Harici graph
  backend'i, bağımsız worker/pod tabanlı dağıtık swarm, tam RLHF/DPO eğitim
  orkestrasyonu ve canlı video/ekran WebRTC genişletmeleri Bölüm 14 yol haritasıdır.

#### 11.1.3 Frontend TypeScript ratchet durumu

`web_ui_react/typescript-migration-baseline.json`, `web_ui_react/src` için güncel
geriye-gitmeme sınırını **en fazla 26 untyped (`.js` + `.jsx`)** ve **en az 41 typed
(`.ts` + `.tsx`)** dosya olarak tanımlar. `npm run typecheck:inventory`, untyped
sayısındaki artışı veya typed sayısındaki düşüşü fail-closed reddeder. Mevcut baseline,
2026-10-31 için 20/47 ve 2027-01-31 için 10/57 ara hedeflerini, 2027-03-31 içinse
**0/67** kapanış hedefini zorunlu kılar.
Tam geçişte `allowJs`/`checkJs` uyumluluk modu kaldırılacaktır. Kampanya sahipliği,
envanter geçmişi ve kabul kriterleri
[`frontend-typescript-migration.md`](../development/frontend-typescript-migration.md)
dosyasında tutulur.

### 11.2 Arşiv ve Yönlendirme

Geçmişte çözülen teknik borçlar ve denetim bulgularının detaylı listesi için `docs/archive/` dizinindeki belgelere bakınız:

- [`docs/archive/resolved_issues_v3.md`](../archive/resolved_issues_v3.md) — v3.0 serisindeki teknik borç, kalite ve hata kapanışları.
- [`docs/archive/audit_history.md`](../archive/audit_history.md) — v4.0 öncesi denetim geçmişi, kapanan kritik bulgular ve audit faz özetleri.
- [`CHANGELOG.md`](../../CHANGELOG.md) — yalnızca sürümler arası farklar, kısa düzeltme notları ve “Teknik Borç Kapanışı” özetleri.

> Yönlendirme ilkesi: Ana rapor “mevcut risk ve kurumsal durum”, arşiv belgeleri ise “geçmiş çözüm hafızası” için kullanılmalıdır.

### 11.3 v5.0 Faz-6 Coverage Kapanışı

- `core/voice.py`, `web_ui_react` duplex ses akışı, `managers/browser_manager.py`, `main.py`, `core/rag.py`, `agent/core/contracts.py`, `core/ci_remediation.py` ve event-driven federation/webhook zinciri için beklenen regresyon kapsamı `tests/test_voice_pipeline.py`, `tests/test_web_server_voice.py`, `tests/test_browser_manager.py`, `tests/test_main_launcher_improvements.py`, `tests/test_rag_graph.py`, `tests/test_contracts_federation.py`, `tests/test_ci_remediation.py` ve `tests/test_web_server_autonomy.py` ile repoda mevcuttur.
- Opsiyonel `pyttsx3` bağımlılığı, HITL onay akışları ve launcher alt süreç davranışı için mocking/fake adapter stratejileri test dosyalarında uygulanmış durumdadır; bu başlık artık aktif borç değil, sürdürülen regresyon korumasıdır.

### 11.4 Operasyonel İzleme Başlıkları

Snapshot'ta kapatılmış kusurlar bulunsa da aşağıdaki başlıklar operasyonel olarak düzenli izlenmelidir:

- **LLM kota ve hız limitleri:** Paralel multi-agent çağrıları dış sağlayıcı RPM/TPM sınırlarını etkileyebilir.
- **Gateway / dış ağ erişimi:** LiteLLM gateway veya sağlayıcı erişim sorunları toplam yanıt süresini uzatabilir.
- **Yerel model donanım sınırları:** Ollama, embedding ve vision akışlarında CPU/GPU/VRAM kapasitesi throughput'u belirler.
- **Vektör veri katmanı ölçeği:** pgvector/ChromaDB indeks davranışı tenant ve belge hacmi arttıkça izlenmelidir.
- **Redis bağımlılıkları:** Semantic cache ve event-stream yüzeyleri Redis kesintilerinde fail-safe çalışsa da gecikme profili değişebilir.

### 11.5 Gelecek İyileştirmeler (Continuous Improvement)

Kritik teknik borcun anlık durumu kalite artifact'larından okunur. İzlenen mühendislik
kampanyalarına ek olarak aşağıdaki
iyileştirme alanları kapasite ve görünürlük eksenindedir:

- **Gelişmiş telemetri görselleştirmesi:** Ajanlar arası delegasyon sürelerinin Grafana panellerinde daha ayrıntılı kırılımlarla izlenmesi.
- **Kurumsal kapasite planlama notları:** pgvector indeks stratejileri, Redis kapasitesi ve uzun dönem maliyet trendlerinin düzenli arşivlenmesi.
- **Arşiv hijyeni:** Yeni kapanan bulguların ana rapora yığılmadan doğrudan `docs/archive/` altında versiyonlu biçimde tutulması.

## 12. `.env` Tam Değişken Referansı (v5.2.0 Kurumsal Sürüm)

[⬆ İçindekilere Dön](#içindekiler)

Sistemin davranışını kontrol eden çevre değişkenleri artık birkaç API anahtarından ibaret değildir; çalışma zamanı yapılandırması `config.py` tarafından merkezi olarak okunur ve güvenlik, gözlemlenebilirlik, semantic cache, çoklu ajan orkestrasyonu ve entegrasyon katmanları mantıksal modüller halinde yönetilir. Yükleme zinciri `config.py` varsayılanları, `.env`, `.env.advanced`, `.env.${SIDAR_ENV}`, `DOTENV_FILE` ve en son `SIDAR_KEYS_FILE` / `~/.sidar_keys.env` sırasını izler; `.env` ve `.env.advanced` `override=False` semantiğiyle mevcut dolu değerleri ezmez. Gerçek API anahtarları için kalıcı kaynak politikası yalnız `.env` ve repo dışındaki `~/.sidar_keys.env` dosyalarıdır; `.env.advanced` referans/operasyonel override şablonu olarak kalmalıdır.

> **Önemli doğruluk notu:** Güncel kod tabanında `DEBUG` yerine `DEBUG_MODE`, `ENABLE_TELEMETRY` yerine `ENABLE_TRACING`, `OTEL_EXPORTER_OTLP_ENDPOINT` yerine `OTEL_EXPORTER_ENDPOINT`, `LITELLM_BASE_URL` yerine `LITELLM_GATEWAY_URL`, `OLLAMA_BASE_URL` yerine `OLLAMA_URL` kullanılmaktadır. Ayrıca ayrı bir `DEFAULT_TENANT_ID` değişkeni yoktur; tenant varsayılanı auth/DB katmanında çalışma zamanında `default` olarak uygulanır. Bunun yanında bazı ileri seviye anahtarlar (`DATABASE_URL`, `DB_SCHEMA_VERSION_TABLE`, `DOCKER_MEM_LIMIT`, `DOCKER_MICROVM_MODE`) `config.py` tarafından desteklenir ancak mevcut `.env.example` şablonunda ön tanımlı satır olarak henüz yer almaz.

### 12.1 Temel Sistem Ayarları (Core Runtime)

| Değişken | Varsayılan | Açıklama |
|----------|-----------|----------|
| `SIDAR_ENV` | `development` (`.env.example`) / `""` (`config.py` fallback) | Ortam profili seçimi; varsa `.env.<profil>` dosyasını temel `.env` üzerine yükler |
| `DEBUG_MODE` | `false` | Ayrıntılı debug davranışlarını ve yapılandırma özetini açar |
| `LOG_LEVEL` | `INFO` | Uygulama geneli log seviyesi (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |
| `RESPONSE_LANGUAGE` | `tr` | Nihai yanıt dili |
| `REVIEWER_TEST_COMMAND` | `python -m pytest` | ReviewerAgent doğrulama safhasında koşturulan test komutu |
| `AI_PROVIDER` | `ollama` | Birincil LLM sağlayıcı seçimi: `ollama`, `gemini`, `openai`, `anthropic`, `litellm` |

### 12.2 Yapay Zeka Sağlayıcıları ve Gateway

| Değişken | Varsayılan | Açıklama |
|----------|-----------|----------|
| `OPENAI_API_KEY` / `OPENAI_MODEL` / `OPENAI_TIMEOUT` | `""` / `gpt-4o-mini` / `60` | OpenAI sağlayıcısı için kimlik bilgisi, model ve timeout |
| `ANTHROPIC_API_KEY` / `ANTHROPIC_MODEL` / `ANTHROPIC_TIMEOUT` | `""` / `claude-3-5-sonnet-latest` / `60` | Anthropic/Claude sağlayıcısı için ayarlar |
| `GEMINI_API_KEY` / `GEMINI_MODEL` | `""` / `gemini-2.5-flash` | Google Gemini sağlayıcı ayarları |
| `OLLAMA_URL` / `OLLAMA_TIMEOUT` | `http://localhost:11434/api` / `30` | Yerel Ollama API adresi ve timeout |
| `CODING_MODEL` / `TEXT_MODEL` | `qwen2.5-coder:7b` / `gemma2:9b` | Yerel görevlerde kullanılan varsayılan kod ve metin modeli |
| `LITELLM_GATEWAY_URL` / `LITELLM_API_KEY` | `http://localhost:4000` / `""` | LiteLLM/OpenRouter benzeri merkezi gateway erişimi |
| `LITELLM_MODEL` / `LITELLM_FALLBACK_MODELS` / `LITELLM_TIMEOUT` | `gpt-4o-mini` / `gpt-4o-mini,claude-3-haiku-20240307` / `60` | Gateway üzerinden kullanılacak birincil model, fallback listesi ve timeout |
| `LLM_MAX_RETRIES` / `LLM_RETRY_BASE_DELAY` / `LLM_RETRY_MAX_DELAY` | `2` / `0.4` / `4.0` | Sağlayıcı çağrılarında retry/backoff politikası |

### 12.3 Veritabanı, RAG ve Vektör Bellek

| Değişken | Varsayılan | Açıklama |
|----------|-----------|----------|
| `DATABASE_URL` | `sqlite+aiosqlite:///data/sidar.db` | Kalıcı bellek, kullanıcı, tenant-policy, audit ve pgvector için ana DB bağlantısı |
| `DB_POOL_SIZE` / `DB_SCHEMA_VERSION_TABLE` / `DB_SCHEMA_TARGET_VERSION` | `5` / `schema_versions` / `1` | Bağlantı havuzu ve şema sürümleme ayarları |
| `RAG_DIR` | `data/rag` | Yerel belge deposu dizini; Chroma tabanlı kurulumlarda veri kökü olarak kullanılır |
| `RAG_TOP_K` / `RAG_CHUNK_SIZE` / `RAG_CHUNK_OVERLAP` / `RAG_FILE_THRESHOLD` | `3` / `1000` / `200` / `20000` | Hibrit arama ve chunking ayarları |
| `RAG_VECTOR_BACKEND` | `chroma` | Vektör arka ucu: `chroma` veya `pgvector` |
| `PGVECTOR_TABLE` / `PGVECTOR_EMBEDDING_DIM` / `PGVECTOR_EMBEDDING_MODEL` | `rag_embeddings` / `384` / `all-MiniLM-L6-v2` | PostgreSQL/pgvector tarafında embedding tablo ve model ayarları |
| `MEMORY_ENCRYPTION_KEY` | `""` | Bellek kayıtlarını Fernet ile şifrelemek için opsiyonel anahtar |

> **RAG notu:** Güncel yapılandırmada ayrı bir `CHROMADB_PATH` değişkeni yoktur; Chroma tarafı `RAG_DIR` ve belge deposu düzeni üzerinden yönetilir. `DATABASE_URL` ve şema versiyon anahtarları çalışma zamanı ile `.env.example` şablonunda senkronize tutulur.

### 12.4 Anlamsal Önbellek, Redis ve Event Bus

| Değişken | Varsayılan | Açıklama |
|----------|-----------|----------|
| `ENABLE_SEMANTIC_CACHE` | `false` | Redis tabanlı semantic cache'i aktif eder |
| `SEMANTIC_CACHE_THRESHOLD` | `0.90` | Cache HIT kabulü için kosinüs benzerlik eşiği |
| `SEMANTIC_CACHE_TTL` / `SEMANTIC_CACHE_MAX_ITEMS` | `3600` / `500` | Cache ömrü ve LRU kapasitesi |
| `SIDAR_REDIS_URL` (`REDIS_URL` legacy) | `.env.example`: `redis://redis:6379/0`, `config.py` fallback: `redis://localhost:6379/0` | Semantic cache, rate limiting ve event-stream katmanının Redis bağlantısı |
| `SIDAR_EVENT_BUS_CHANNEL` / `SIDAR_EVENT_BUS_GROUP` | `sidar:agent_events` / `sidar:agent_events:cg` | Swarm/event bus için Redis Streams kanal ve consumer group adları |
| `SIDAR_RATE_LIMIT_WINDOW` / `SIDAR_RATE_LIMIT_CHAT` / `SIDAR_RATE_LIMIT_MUTATIONS` / `SIDAR_RATE_LIMIT_GET_IO` / `SIDAR_RATE_LIMIT_WS_CONNECTIONS` | `60` / `20` / `60` / `30` / `30` | API istekleri ile chat/voice WebSocket bağlantı açma denemelerinin pencere ve endpoint bazlı limitleri |
| `TRUSTED_PROXIES` | `""` | Güvenilir ters proxy IP listesi; boşsa proxy başlıkları güvenilmez sayılır |
| `MAX_RAG_UPLOAD_BYTES` | `52428800` | RAG dosya yükleme üst limiti (50 MB) |

### 12.5 Güvenlik, Kimlik Doğrulama, Tenant, DLP ve HITL

| Değişken | Varsayılan | Açıklama |
|----------|-----------|----------|
| `ACCESS_LEVEL` | `.env.example`: `sandbox`, `config_security.py` fallback: `sandbox` | Araç/yürütme erişim seviyesi: `restricted`, `sandbox`, `full`. `full` yalnız `SIDAR_ALLOW_FULL_ACCESS=true` açık onayıyla geçerlidir; aksi durumda başlangıç doğrulaması reddeder. |
| `API_KEY` | `""` | Web/API için opsiyonel ek anahtar tabanlı koruma |
| `JWT_SECRET_KEY` / `JWT_ALGORITHM` / `JWT_TTL_DAYS` | `""` / `HS256` / `7` | SPA/API oturumları için JWT imzalama ve yaşam süresi ayarları |
| `DLP_ENABLED` / `DLP_LOG_DETECTIONS` | `true` / `false` | PII/hassas veri maskeleme ve maskeleme loglama davranışı |
| `HITL_ENABLED` / `HITL_TIMEOUT_SECONDS` | `false` / `120` | Yıkıcı işlemler öncesi human-in-the-loop onay kapısı ve bekleme süresi |
| `METRICS_TOKEN` | `""` | `/metrics`, `/metrics/llm`, `/api/budget` gibi operasyonel endpoint'ler için statik bearer token |

> **Tenant notu:** Çoklu kiracı desteği runtime ve DB katmanında `tenant_id` alanı ile uygulanır; ancak yapılandırmada ayrı bir `DEFAULT_TENANT_ID` env değişkeni bulunmaz. Varsayılan tenant değeri auth ve veritabanı akışında `default` olarak üretilir.

### 12.6 Gözlemlenebilirlik (Observability & OTel)

| Değişken | Varsayılan | Açıklama |
|----------|-----------|----------|
| `ENABLE_TRACING` | `false` | OpenTelemetry tracing'i açar/kapatır |
| `OTEL_EXPORTER_ENDPOINT` | `.env.example`: `http://localhost:4317`, `config.py` fallback: `http://jaeger:4317` | OTLP exporter/collector/Jaeger adresi |
| `OTEL_SERVICE_NAME` | `sidar` | Telemetri panellerinde servisin görünen adı |
| `OTEL_INSTRUMENT_FASTAPI` / `OTEL_INSTRUMENT_HTTPX` | `true` / `true` | FastAPI ve HTTPX otomatik enstrümantasyon anahtarları |
| `GRAFANA_URL` | `http://localhost:3000` | Web admin panelindeki Grafana bağlantı hedefi |
| `GRAFANA_ADMIN_PASSWORD` | Installer tarafından `.env` içinde güvenli üretilir | Grafana kullanıcısı `admin` için zorunlu parola; `admin/admin` varsayılanı reddedilir |

### 12.7 Dış Entegrasyonlar, Managers ve Plugin Yüzeyleri

| Değişken | Varsayılan | Açıklama |
|----------|-----------|----------|
| `GITHUB_TOKEN` / `GITHUB_REPO` / `GITHUB_WEBHOOK_SECRET` / `GITHUB_WEBHOOK_REQUIRE_SIGNATURE` | `""` / `""` / `""` / `true` | GitHub repo erişimi, varsayılan repo ve webhook doğrulama ayarları; imza zorunluluğu production profilinde her zaman etkin kalır |
| `SLACK_TOKEN` / `SLACK_WEBHOOK_URL` / `SLACK_DEFAULT_CHANNEL` | `""` / `""` / `""` | Slack API veya webhook tabanlı bildirim ayarları |
| `JIRA_URL` / `JIRA_TOKEN` / `JIRA_EMAIL` / `JIRA_DEFAULT_PROJECT` | `""` / `""` / `""` / `""` | Jira entegrasyonu ve varsayılan proje bilgileri |
| `TEAMS_WEBHOOK_URL` | `""` | Microsoft Teams webhook bildirimi |
| `SEARCH_ENGINE` / `TAVILY_API_KEY` / `GOOGLE_SEARCH_API_KEY` / `GOOGLE_SEARCH_CX` | `auto` / `""` / `""` / `""` | Web arama sağlayıcı seçimi ve harici arama API ayarları |
| `WEB_SEARCH_MAX_RESULTS` / `WEB_FETCH_TIMEOUT` / `WEB_FETCH_MAX_CHARS` / `WEB_SCRAPE_MAX_CHARS` | `5` / `15` / `12000` / `12000` | Web içerik toplama ve scrape sınırları |
| `PACKAGE_INFO_TIMEOUT` / `PACKAGE_INFO_CACHE_TTL` | `12` / `1800` | Paket metadata sorguları için timeout ve cache süresi |

### 12.8 Donanım, Yerel Çalışma, Sandbox ve Gelişmiş Yetenekler

| Değişken | Varsayılan | Açıklama |
|----------|-----------|----------|
| `USE_GPU` / `GPU_DEVICE` / `MULTI_GPU` | `false` (`.env.example`) / `0` / `false` | GPU kullanımı, cihaz seçimi ve çoklu GPU modu |
| `GPU_MEMORY_FRACTION` / `LLM_GPU_MEMORY_FRACTION` / `RAG_GPU_MEMORY_FRACTION` | `0.8` / `0.8` / `0.3` | Yerel LLM ve RAG için VRAM bütçe ayarları |
| `GPU_MIXED_PRECISION` | `true` (production) / `false` (development) | FP16/mixed precision ile VRAM optimizasyonu |
| `DOCKER_PYTHON_IMAGE` / `DOCKER_EXEC_TIMEOUT` / `DOCKER_REQUIRED` | `python:3.11-alpine` / `10` / `true` | Kod çalıştırma sandbox'ının temel Docker davranışı; Docker yoksa host fallback yapılmaz |
| `DOCKER_RUNTIME` / `DOCKER_ALLOWED_RUNTIMES` / `DOCKER_MICROVM_MODE` | `""` / `,runc,runsc,kata-runtime` / `off` | Zero-trust sandbox runtime ve mikro-VM hazırlık seçenekleri |
| `DOCKER_MEM_LIMIT` / `SIDAR_DOCKER_NETWORK_DISABLED` / `SIDAR_DOCKER_NANO_CPUS` | `256m` / `true` / `1000000000` | Sandbox konteyner kaynak kısıtları |
| `SANDBOX_MEMORY` / `SANDBOX_CPUS` / `SANDBOX_NETWORK` / `SANDBOX_PIDS_LIMIT` / `SANDBOX_TIMEOUT` | `256m` / `0.5` / `none` / `64` / `10` | `config.py::SANDBOX_LIMITS` sözlüğüne beslenen detaylı çalışma kotaları |
| `WEB_HOST` / `WEB_PORT` / `WEB_GPU_PORT` | `0.0.0.0` / `7860` / `7861` | Web sunucusunun bind adresi ve portları |
| `HF_TOKEN` / `HF_HUB_OFFLINE` | `""` / `0/false` | HuggingFace model erişimi ve offline cache davranışı |
| `SIDAR_JUDGE_ENABLED` / `SIDAR_JUDGE_MODEL` / `SIDAR_JUDGE_PROVIDER` / `SIDAR_JUDGE_SAMPLE_RATE` | `false` / `""` / `ollama` / `0.2` | LLM-as-a-Judge kalite değerlendirme hattı |
| `ENABLE_COST_ROUTING` ve `COST_ROUTING_*` | `false` / eşik ve model varsayılanları | Basit/karmaşık sorgular için maliyet odaklı model yönlendirmesi |
| `ENABLE_ENTITY_MEMORY` / `ENTITY_MEMORY_TTL_DAYS` / `ENTITY_MEMORY_MAX_PER_USER` | `true` / `90` / `100` | Entity/persona memory kalıcılığı |
| `ENABLE_ACTIVE_LEARNING`, `AL_MIN_RATING_FOR_TRAIN`, `ENABLE_LORA_TRAINING`, `LORA_*` | çeşitli | Geri bildirim toplama ve LoRA/QLoRA fine-tuning hazırlıkları |
| `ENABLE_CONTINUOUS_LEARNING` | `false` | Judge/feedback sinyallerinden sürekli öğrenme (continuous learning) bundle'ı üretilmesini aktifleştirir. (v6.0 hazırlığı) |
| `CONTINUOUS_LEARNING_MIN_SFT_EXAMPLES` | `20` | Sürekli öğrenme için gereken minimum SFT (Supervised Fine-Tuning) örnek sayısı. |
| `CONTINUOUS_LEARNING_MIN_PREFERENCE_EXAMPLES` | `10` | RLHF/DPO için gereken minimum tercih (preference) örnek sayısı. |
| `CONTINUOUS_LEARNING_MAX_PENDING_SIGNALS` | `5000` | İşlenmeyi bekleyen maksimum sinyal kapasitesi. |
| `CONTINUOUS_LEARNING_COOLDOWN_SECONDS` | `3600` | İki ardışık sürekli öğrenme döngüsü arasındaki bekleme süresi (saniye). |
| `CONTINUOUS_LEARNING_OUTPUT_DIR` | `data/continuous_learning` | Sürekli öğrenme veri setlerinin dışa aktarılacağı dizin. |
| `CONTINUOUS_LEARNING_SFT_FORMAT` | `alpaca` | Supervised Fine-Tuning formatı (örn. alpaca, sharegpt). |
| `ENABLE_VISION` / `VISION_MAX_IMAGE_BYTES` | `true` / `10485760` | Çok modlu görsel girdi yetenekleri |
| `ENABLE_MULTIMODAL` / `MULTIMODAL_MAX_FILE_BYTES` / `VOICE_STT_PROVIDER` / `WHISPER_MODEL` / `VOICE_WS_MAX_BYTES` | `true` / `52428800` / `whisper` / `base` / `10485760` | Medya ingestion, ses işleme ve `/ws/voice` limiti |
| `VOICE_TTS_PROVIDER` / `VOICE_TTS_VOICE` / `VOICE_TTS_SEGMENT_CHARS` / `VOICE_TTS_BUFFER_CHARS` | `auto` / `""` / `48` / `96` | Duplex TTS sağlayıcısı, ses seçimi, segment boyu ve düşük gecikmeli buffer limiti |
| `VOICE_VAD_ENABLED` / `VOICE_VAD_MIN_SPEECH_BYTES` / `VOICE_DUPLEX_ENABLED` / `VOICE_VAD_INTERRUPT_MIN_BYTES` | `true` / `1024` / `true` / `384` | VAD tabanlı speech algılama, duplex akış ve barge-in interrupt eşikleri |
| `BROWSER_PROVIDER` / `BROWSER_HEADLESS` / `BROWSER_TIMEOUT_MS` / `BROWSER_ALLOWED_DOMAINS` | `auto` / `true` / `15000` / `[]` | Browser automation sağlayıcısı, görünüm modu, timeout ve domain allowlist |
| `ENABLE_LSP` / `LSP_TIMEOUT_SECONDS` / `LSP_MAX_REFERENCES` / `PYTHON_LSP_SERVER` / `TYPESCRIPT_LSP_SERVER` | `true` / `15` / `200` / `pyright-langserver` / `typescript-language-server` | LSP tabanlı anlamsal analiz/refactor ayarları |
| `ENABLE_AUTONOMOUS_CRON` / `AUTONOMOUS_CRON_INTERVAL_SECONDS` / `AUTONOMOUS_CRON_PROMPT` | `false` / `900` / varsayılan otonom prompt | Proaktif cron tetikleyicisinin açılması, periyodu ve sistem promptu |
| `ENABLE_NIGHTLY_MEMORY_PRUNING` / `NIGHTLY_MEMORY_INTERVAL_SECONDS` / `NIGHTLY_MEMORY_IDLE_SECONDS` / `NIGHTLY_MEMORY_KEEP_RECENT_SESSIONS` / `NIGHTLY_MEMORY_SESSION_MIN_MESSAGES` / `NIGHTLY_MEMORY_RAG_KEEP_RECENT_DOCS` | `false` / `86400` / `1800` / `2` / `12` / `2` | Idle-gece döngüsü ile konuşma özetleme, RAG pruning ve hafıza konsolidasyonu ayarları |
| `ENABLE_DISTRIBUTED_AGENT_LOCKS` / `DISTRIBUTED_AGENT_LOCK_REQUIRED` / `DISTRIBUTED_AGENT_LOCK_TTL_SECONDS` / `DISTRIBUTED_AGENT_LOCK_TIMEOUT_MS` | `true` / `false` / `1800` / `250` | Kubernetes/çoklu pod ortamında shared ajan bakım işlerini Redis lease ile tekilleştirir; production'da required mod Redis yoksa fail-open yarışını engeller |
| `ENABLE_EVENT_WEBHOOKS` / `AUTONOMY_WEBHOOK_SECRET` / `AUTONOMY_WEBHOOK_REQUIRE_SIGNATURE` / `ENABLE_SWARM_FEDERATION` / `SWARM_FEDERATION_SHARED_SECRET` | `true` / `""` / `true` / `true` / `""` | Otonom webhook dispatch ve dış swarm federation güvenlik ayarları; GitHub imza doğrulaması `GITHUB_WEBHOOK_REQUIRE_SIGNATURE`, autonomy imza doğrulaması `AUTONOMY_WEBHOOK_REQUIRE_SIGNATURE` ile ayrı yönetilir |
| `ENABLE_GRAPH_RAG` / `GRAPH_RAG_MAX_FILES` | `true` / `5000` | GraphRAG indeksleme aktivasyonu ve tarama üst sınırı |
| `ENABLE_RAG_ENTITY_EXTRACTION` / `RAG_ENTITY_MAX_PER_DOC` | `true` / `24` | RAG belgelerinden kampanya/marka/hedef kitle/dil/kanal entity çıkarımı ve ilişkisel bellek limiti |

### 12.9 Docker Compose Override Değişkenleri

| Değişken | Varsayılan | Açıklama |
|----------|-----------|----------|
| `SIDAR_CPU_LIMIT` | `2.0` | `sidar-ai` servisi için CPU limiti (`docker-compose.yml`) |
| `SIDAR_MEM_LIMIT` | `4g` | `sidar-ai` servisi için bellek limiti |
| `SIDAR_GPU_CPU_LIMIT` | `4.0` | `sidar-gpu` servisi için CPU limiti |
| `SIDAR_GPU_MEM_LIMIT` | `8g` | `sidar-gpu` servisi için bellek limiti |
| `SIDAR_WEB_CPU_LIMIT` | `2.0` | `sidar-web` servisi için CPU limiti |
| `SIDAR_WEB_MEM_LIMIT` | `4g` | `sidar-web` servisi için bellek limiti |
| `SIDAR_WEB_GPU_CPU_LIMIT` | `4.0` | `sidar-web-gpu` servisi için CPU limiti |
| `SIDAR_WEB_GPU_MEM_LIMIT` | `8g` | `sidar-web-gpu` servisi için bellek limiti |
| `HOST_GATEWAY` | `host-gateway` | Konteynerden host Ollama erişimi için `extra_hosts` gateway değeri |
| `WEB_PORT` / `WEB_GPU_PORT` | `7860` / `7861` | Compose port publish değerleri |
| `NVIDIA_VISIBLE_DEVICES` | `all` | GPU konteynerlerinde görünür cihaz seçimi |
| `NVIDIA_DRIVER_CAPABILITIES` | `compute,utility` | NVIDIA sürücü yetenek seti |

> **Not:** Bu değişkenler uygulama `Config` sınıfından çok, doğrudan container orkestrasyon katmanında (Compose) etkilidir.

---

<a id="13-v4x-kurumsal-enterprise-ve-swarm-mimarisi-evrimi-tamamlandı"></a>
