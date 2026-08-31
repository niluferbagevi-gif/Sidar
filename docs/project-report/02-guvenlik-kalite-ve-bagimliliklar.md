# Sidar Proje Raporu — Güvenlik, Kalite ve Bağımlılıklar

> Aktif ürün baseline: **v5.2.0**. Bu dosya, [`PROJE_RAPORU.md`](../PROJE_RAPORU.md) indeksinin bölümüdür.

<a id="içindekiler"></a>
## Bu dosyadaki bölümler

- Bölüm 5
- Bölüm 6
- Bölüm 7
- Bölüm 8

---

## 5. Güvenlik Analizi

[⬆ İçindekilere Dön](#içindekiler)

### 5.1 Güvenlik Kontrolleri Özeti

| Kontrol | Durum | Konum |
|---------|-------|-------|
| Path traversal engelleme | ✓ Aktif | `managers/security.py` |
| Symlink koruması | ✓ Aktif | `managers/security.py` |
| Hassas yol engelleme | ✓ Aktif | `managers/security.py` |
| Bearer Token Auth | ✓ Aktif (DB tabanlı) | `web_server.py` — `basic_auth_middleware`, `/auth/login`, `/auth/register`, `/auth/me` |
| Çoklu Kullanıcı (Tenant) İzolasyonu | ✓ Aktif (`user_id` tabanlı) | `core/db.py` — `users`, `auth_tokens`, `sessions`, `messages`, `provider_usage_daily`, `user_quotas` |
| WebSocket zorunlu Auth Handshake | ✓ Aktif (policy violation `1008`) | `web_server.py` — `/ws/chat`, `_ws_close_policy_violation()` |
| Fail-Closed Bellek Erişimi | ✓ Aktif (`MemoryAuthError`) | `core/memory.py` — `_require_active_user()` |
| Zero-Trust Docker Sandbox | ✓ Aktif (`network_mode="none"`, `mem_limit`, `nano_cpus`) | `managers/code_manager.py` — `execute_code()` |
| Mikro-VM Runtime Uyum Katmanı | ✓ Aktif (`runsc` / `kata-runtime` çözümleme) | `managers/code_manager.py` — `_resolve_runtime()` |
| DDoS koruması | ✓ Aktif (IP başına hız sınırı) | `web_server.py` — `ddos_rate_limit_middleware` |
| CORS kısıtlaması | ✓ Aktif (allowlist) | `web_server.py` — CORS middleware |
| Rate limiting | ✓ Aktif (HTTP + WS + Redis fallback) | `web_server.py` |
| DLP / PII Maskeleme | ✓ Aktif (`[MASKED]` temelli) | `core/dlp.py`, `core/llm_client.py` |
| HITL Onay Geçidi | ✓ Aktif (yüksek riskli eylemler için duraklatma/onay) | `core/hitl.py`, `web_server.py` |
| Tenant RBAC | ✓ Aktif (tenant + resource/action policy) | `web_server.py`, `core/db.py` |
| Audit Trail | ✓ Aktif (DB kalıcılığı) | `migrations/versions/0003_audit_trail.py`, `core/db.py`, `web_server.py` |
| LLM QA Devre Kesici | ✓ Aktif (`MAX_QA_RETRIES=3`) | `agent/sidar_agent.py` |
| GitHub binary engelleme | ✓ Aktif | `managers/github_manager.py` |
| Git upload blacklist | ✓ Aktif | `github_upload.py` |
| Bilinmeyen erişim seviyesi | ✓ Sandbox'a normalize | `managers/security.py` |
| Branch adı enjeksiyon koruması | ✓ Regex `_BRANCH_RE` | `managers/github_manager.py` |
| GitHub Webhook İmzası | ✓ Aktif (HMAC-SHA256) | `web_server.py` — `/api/webhook` |
| Büyük Dosya Okuma Limit | ✓ Aktif (boyut limiti) | `web_server.py` — `/file-content` |
| K8s Network Policy İzolasyonu | ✓ Aktif (Helm şablonu mevcut) | `helm/sidar/templates/networkpolicy-web.yaml` |
| K8s Secret Yönetimi | ✓ Aktif (Helm şablonu mevcut) | `helm/sidar/templates/secret-postgresql.yaml` |

### 5.2 Güvenlik Seviyeleri Davranışı

```
RESTRICTED → yalnızca okuma + analiz (yazma/çalıştırma/shell YOK)
SANDBOX    → okuma + /temp yazma + Docker Python REPL
FULL       → tam erişim (shell, git, npm, proje geneli yazma)
```

**QA ve Kod Onay Bariyeri (ReviewerAgent Süzgeci):** Hangi erişim seviyesinde (Sandbox veya Full) çalışılırsa çalışılsın, CoderAgent çıktıları ReviewerAgent doğrulamasından geçer. Ek olarak `MAX_QA_RETRIES=3` sınırı ile Coder ↔ Reviewer geri besleme zinciri fail-safe biçimde sonlandırılır; sonsuz döngü ve maliyet artışı engellenir.

**HITL Güvenlik Freni:** Yüksek riskli işlemler ayrıca Human-in-the-Loop kapısına alınabilir; sistem işlemi duraklatır ve admin/kullanıcı onayı olmadan kritik aksiyonu tamamlamaz.

### 5.3 Kurumsal Zero-Trust Savunma Sütunları (v3.0)

#### 5.3.1 Path Traversal + Blacklist + Symlink Koruması
- `SecurityManager`, ham yol girdilerinde `../` ve kritik sistem dizinlerini (`/etc`, `/proc`, `/sys`, `C:\Windows`, `Program Files`) `_DANGEROUS_PATH_RE` ile reddeder.
- `.env`, `.git`, `sessions`, `__pycache__` gibi hassas yollar `_BLOCKED_PATTERNS` ile ek katmanda engellenir; bu kural FULL seviyede dahi güvenlik zeminini korur.
- `Path.resolve()` + `relative_to(base_dir)` kontrolleri ile symlink üzerinden kök dizin dışına kaçış girişimleri fail-closed biçimde bloklanır.

#### 5.3.2 Docker Sandbox İzolasyonu (Kod Çalıştırma)
- `execute_code` akışı, kodu izole Docker konteynerinde çalıştırır; `network_mode="none"`, `mem_limit` ve `nano_cpus` ile ağ/kaynak sınırları uygulanır.
- Sandbox katmanı erişilemezse politika seviyesine göre kontrollü davranış devreye girer (SANDBOX modunda reddetme, FULL modda sınırlı fallback).

#### 5.3.3 Kriptografik Kimlik/Oturum Güvenliği (Güncellendi)
- Parola doğrulama akışı yeni kayıtlar için `Argon2id`, legacy kayıtlar için `PBKDF2-HMAC-SHA256` + salt + sabit-zamanlı karşılaştırma (`secrets.compare_digest`) ile uygulanır.
- **[ÖNEMLİ] Kriptografik Güçlendirme:** Parola türetme algoritmasındaki iterasyon sayısının (önceki: `120000`) güncel OWASP standartlarına (min `600000`) uygun hale getirilmesi teknik bir borç olarak işaretlenmiştir. Yeni nesil GPU'ların kırabilme kapasitesine karşı kurumsal sistemlerde bu değerin artırılması zorunludur.
- Oturum belirteçleri `secrets.token_urlsafe(...)` ile üretilir; kullanıcı/oturum anahtarlarında UUID kullanımı tahmin edilebilirlik riskini azaltır.
- WebSocket kanalında `auth` handshake zorunludur; geçersiz/eksik token durumunda bağlantı policy violation ile kapatılır.

#### 5.3.4 OOM/Binary ve Rate-Limit Savunmaları
- GitHub dosya okuma katmanında güvenli uzantı/uzantısız whitelist uygulanır; binary/uygunsuz dosya tipleri decode edilmeden reddedilir.
- API yüzeyinde DDoS/rate-limit middleware'leri ve Redis destekli limit mekanizmasıyla ani yüklenmelerde servis kararlılığı korunur.
- Büyük dosya okuma limitleri ve güvenli metin odaklı işleme yaklaşımı, bellek şişmesi (OOM) riskini azaltan uygulama savunması sağlar.

#### 5.3.5 Web UI XSS Sertleştirmesi
- `marked` ile üretilen HTML, istemci tarafında `sanitizeRenderedHtml(...)` süzgecinden geçirilir.
- `script/iframe/object/embed/form/meta/link` etiketleri ve `javascript:` gibi tehlikeli URL şemaları temizlenerek içerik render edilir.

#### 5.3.6 DLP (Veri Sızıntısı Önleme / PII Maskeleme)
- `core/dlp.py`, kullanıcı girdilerindeki kredi kartı, TC kimlik, e-posta, telefon, bearer token ve benzeri hassas desenleri regex/desen tanıma ile tespit eder.
- Bu katman, içerik üçüncü parti LLM sağlayıcılarına gitmeden önce verileri `[MASKED]` benzeri güvenli temsillere dönüştürerek hassas veri sızıntısı riskini azaltır.

#### 5.3.7 HITL (Human-in-the-Loop) Onay Katmanı
- `core/hitl.py` ve Web API yüzeyi, yüksek riskli işlemleri doğrudan yürütmek yerine bekleme durumuna alır ve açık kullanıcı/onaycı kararı bekler.
- Bu model; dosya silme, veritabanı değişikliği, yıkıcı komutlar veya üretim etkili eylemlerde ajan otonomisini kontrollü biçimde sınırlar.

#### 5.3.8 Multi-Tenant RBAC ve Audit Trail
- Çok kiracılı veri modeli ile kullanıcı/policy kayıtları tenant bağlamında değerlendirilir; `access_policy_middleware` rota, kaynak ve aksiyon bazlı karar üretir.
- Kritik izin kararları ile policy değişiklikleri, `0003_audit_trail` migrasyonu sonrası kalıcı audit log tablosuna yazılarak denetlenebilirlik sağlanır.

#### 5.3.9 Altyapı Ağ İzolasyonu ve Sırlar
- Helm chart içindeki `networkpolicy-web.yaml`, Kubernetes pod'ları arasında yalnızca gerekli trafik yollarını açık bırakan sıkı ağ izolasyonu yaklaşımını belgeler.
- Hassas bağlantı bilgileri ve veritabanı sırları, `secret-postgresql.yaml` ve ortam değişkenleri üzerinden izole edilerek uygulama katmanının dışında da savunma derinliği oluşturulur.

---

## 6. Test Kapsamı

[⬆ İçindekilere Dön](#içindekiler)

Güncel depoda test envanteri kurumsal kalite kapılarına göre agresif biçimde genişletilmiştir:

- **`test_*.py` modül sayısı:** **213**
- **`tests/*.py` toplamı (`conftest.py` + `__init__.py` dahil):** **215**
- **Toplam test satırı (`tests/*.py`):** **65.729**
- **Kapsama politikası:** `.coveragerc`, `pytest.ini`, `run_tests.sh` ve CI hattı ile yönetilen **%90 hard gate**

**Öne çıkan test kategorileri (v5.0.0-alpha):**
- **Coverage / Sert kalite kapısı:** `test_quick_100.py`, `test_ultimate_coverage.py`, `pytest-cov`, `.coveragerc`, `run_tests.sh`
- **Kurumsal izolasyon ve RBAC:** `test_tenant_rbac_scenarios.py`, `test_rbac_policy_runtime.py`, `test_db_postgresql_branches.py`
- **Güvenlik (DLP & HITL):** `test_dlp_masking.py`, `test_hitl_approval.py`, `test_github_webhook.py`, `test_web_ui_security_improvements.py`
- **Semantic Cache / Redis:** `test_semantic_cache_runtime.py`, `test_llm_client_retry_helpers.py`
- **Çoklu ajan ve Swarm:** `test_swarm_orchestrator.py`, `test_supervisor_agent.py`, `test_reviewer_agent.py`, `test_event_stream_runtime.py`
- **Plugin Marketplace:** `test_plugin_marketplace_flow.py` — dinamik ajan yükleme, `AgentRegistry` kaydı ve çağrı akışı doğrulaması
- **Observability / OTel:** `test_otel_rag_spans.py`, `test_observability_stack_compose.py`, `test_llm_metrics_runtime.py`, `test_grafana_dashboard_provisioning.py`
- **LLM-as-a-Judge ve Active Learning:** `test_llm_judge.py`, `test_active_learning.py`
- **Altyapı ve migration:** `test_migration_assets.py`, `test_migration_ci_guards.py`, `test_observability_stack_compose.py`, `test_sandbox_runtime_profiles.py`

> Not: Önceki audit notlarında geçen 0 bayt test artifact uyarıları tarihsel kayıt niteliğindedir; güncel pipeline `find tests -type f -size 0` kontrolüyle bu durumu bloklayıcı kalite kapısı olarak yönetir.

### 6.1 CI/CD Pipeline Durumu

| Kalite Kapısı | Durum | Kaynak |
|---|---|---|
| Tüm testleri çalıştır (`run_tests.sh`) | ✅ Aktif | `.github/workflows/ci.yml`, `run_tests.sh` |
| Coverage Quality Gate (local/CI ratchet-managed baseline `fail_under=100`, tüm standart profiller fail-closed) | ✅ Zorunlu | `pyproject.toml`, `run_tests.sh`, `.github/workflows/ci.yml`, `AGENTS.md §2.5.4` |
| Final birleşik coverage adımı (`coverage report --fail-under=${COVERAGE_FAIL_UNDER}`) | ✅ Aktif | `.github/workflows/ci.yml` |
| Boş test artifact engeli (`find tests -size 0`) | ✅ Zorunlu | `.github/workflows/ci.yml`, `scripts/check_empty_test_artifacts.sh` |
| `pg_stress` izolasyonu | ✅ Aktif | `.github/workflows/ci.yml`, `tests/test_db_postgresql_branches.py` |
| Sandbox/Reviewer sertleştirme testi | ✅ Aktif | `tests/test_sandbox_runtime_profiles.py`, `tests/test_reviewer_agent.py` |
| Swarm + Active Learning hedefli regresyon dilimi | ✅ Aktif | `.github/workflows/ci.yml`, `tests/test_swarm_orchestrator.py`, `tests/test_active_learning.py` |
| Production cutover rehearsal genişletmesi | ✅ Aktif | `.github/workflows/migration-cutover-checks.yml`, `tests/test_migration_ci_guards.py`, `tests/test_swarm_orchestrator.py`, `tests/test_active_learning.py` |

Bu yapı ile test disiplini yalnızca birim test sayısına değil, **coverage barajı + artifact hijyeni + enterprise senaryo regresyonları** üzerine kurulu kurumsal bir kalite modeline taşınmıştır. Swarm orkestrasyonu ile Active Learning hattı da artık bu model içinde açık isimli hedefli regresyon dilimi olarak ayrı görünürlük kazanmıştır.

### 6.2 Coverage Profile-Aware Quality Gates

Coverage Quality Gate üç operasyonel profil tarafından ortak kullanılan fail-closed
bir tabandır; release öncesi güncel baseline local/CI ve campaign için `%100`'dür
(detay için bkz. `AGENTS.md §2.5.4`):

- **Local profile (`TEST_PROFILE=local`)** — `pyproject.toml [tool.coverage.report].fail_under = 100`
  ratchet tabanıdır; `coverage_ratchet.py` step `%1` ile bu değeri
  yalnızca yukarı taşır ve `COVERAGE_RATCHET_MAX_GATE=100` ile ölçülen tam kapsamı
  regresyonlara karşı korur. `COVERAGE_FAIL_UNDER_LOCAL` envi tabanı override eder.
- **CI profile (`TEST_PROFILE=ci`)** — `.github/workflows/ci.yml` ana test
  job'unda artık ayrı bir sabit override bindirmiyor; local ile aynı
  ratchet edilmiş `pyproject.toml` tabanını kullanır. `COVERAGE_FAIL_UNDER_CI`
  envi hâlâ desteklenir ve verilirse tabanın üzerine geçer.
- **Coverage campaign** — `COVERAGE_CAMPAIGN=1` veya
  `AUTONOMOUS_LOOP_OPERATION_PROFILE=coverage-campaign` ile devreye girer,
  `COVERAGE_FAIL_UNDER_CAMPAIGN` varsayılan `%100` aspirasyonel hedefi
  uygular ve ratchet üst sınırını `%100`'e açar.

Doğrudan `COVERAGE_FAIL_UNDER` her zaman tüm profillerin önüne geçer
(geri uyumluluk). Rapor görünürlüğü `pyproject.toml` coverage ayarlarıyla
`show_missing = true` olarak korunur, `pytest.ini` `python_files = test_*.py`
ve `asyncio_mode = auto` ile test evrenini deterministik koşturur.

CI hattı (`.github/workflows/ci.yml`) coverage eşiğinden hemen önce
`tests/test_swarm_orchestrator.py` ve `tests/test_active_learning.py` için
hedefli bir regresyon dilimi koşturur; final birleşik rapor adımında
`coverage report --fail-under=${COVERAGE_FAIL_UNDER}` profile uygun eşiği
uygular. `run_tests.sh` betiği yerel kullanımda da aynı resolver'ı
çalıştırarak ekrandaki "Coverage quality gate eşiği" satırında hangi
profilin seçildiğini (`local | ci | campaign | explicit-override`) ve
ratchet üst sınırını birlikte loglar.
- `migration-cutover-checks.yml` production rehearsal hattı da aynı Swarm + Active Learning dilimini `tests/test_migration_ci_guards.py` guard testi ile birlikte çalıştırarak veri migrasyonu, connection pool smoke ve öğrenme/orkestrasyon omurgasını tek cutover zincirinde toplar.
- Depoda `test_quick_100.py` ve `test_ultimate_coverage.py` gibi agresif kapsama odaklı testler bulunur; bu yaklaşım, "test çalıştı" seviyesinin ötesinde **ölçülebilir kapsam** zorunluluğu getirir.

### 6.3 Test Havuzu ve Modüler Senaryolar

- Güncel depoda `test_*.py` desenine uyan **213 test modülü** bulunur; `tests/*.py` toplamı (yardımcı dosyalar dahil) **215** adettir.
- Test havuzu yalnızca klasik unit testlerden oluşmaz; tenant veri izolasyonu, RBAC policy enforcement, DLP maskeleme, HITL onay akışı, semantic cache eviction/benzerlik mantığı, swarm görev dağıtımı ve plugin marketplace gibi enterprise senaryoları kapsar.
- Örnek yüksek değerli senaryolar: `test_tenant_rbac_scenarios.py`, `test_dlp_masking.py`, `test_hitl_approval.py`, `test_semantic_cache_runtime.py`, `test_swarm_orchestrator.py`, `test_plugin_marketplace_flow.py`, `test_otel_rag_spans.py`, `test_llm_judge.py`, `test_active_learning.py`.

### 6.4 Asenkron Test Altyapısı

- `pytest.ini` içinde `python_files = test_*.py`, `asyncio_mode = auto` ve `asyncio_default_fixture_loop_scope = session` ayarları ile tüm async testler otomatik olarak session kapsamlı event loop'ta çalışır.
- `tests/conftest.py` standart `pytest-asyncio` mimarisine geçirilmiştir: deprecated `event_loop` override kaldırılmış, session kapsamlı event loop yönetimi `pytest.ini` üzerinden yapılandırılmıştır.
- `pytest.ini`'ye `slow` ve `pg_stress` marker'ları eklenmiştir; PostgreSQL bağlantı havuzu stres testleri `-m pg_stress` ile izole çalıştırılabilir.
- CI (`.github/workflows/ci.yml`) üzerinde ayrı `pg-stress` job'ı yer alır; PostgreSQL 16 service container, Alembic migration ve `tests/test_db_postgresql_branches.py` üstünden bağlantı havuzu yük testi otomatik olarak çalışır.

---

## 7. Temel Bağımlılıklar

[⬆ İçindekilere Dön](#içindekiler)

Bu bölüm, güncel `pyproject.toml`, `requirements-dev.txt`, `environment.yml` ve `web_ui_react/package.json` dosyalarına göre v5.0.0-alpha bağımlılık setini kurumsal kategorilerle özetler. (`requirements.txt` diskte bulunmaz; Python bağımlılıkları `pyproject.toml` PEP 621 standardında, React SPA bağımlılıkları ise `web_ui_react/package.json` içinde yönetilir.)

> **Sistem bağımlılığı notu (multimodal ingest):** `core/multimodal.py` içindeki dış video/ses işleme akışlarının (özellikle `ingest_video_insights`) sorunsuz çalışabilmesi için host/container seviyesinde `yt-dlp`, `ffmpeg` ve `whisper` CLI araçlarının kurulu olması gerekir.

### 7.1 Asenkron Altyapı ve Uygulama Çekirdeği

| Paket | Durum | Kullanım Yeri |
|-------|-------|---------------|
| `fastapi` + `uvicorn[standard]` | ✓ Zorunlu | Web API + WebSocket katmanı |
| `httpx` | ✓ Zorunlu | Asenkron HTTP istemcisi (LLM/web entegrasyonları) |
| `python-dotenv`, `pydantic`, `cachetools`, `anyio` | ✓ Zorunlu | Konfigürasyon, doğrulama, rate-limit yardımcıları |
| `redis` | Opsiyonel (önerilen) | Dağıtık/persist rate-limit altyapısı |

### 7.2 Veritabanı, Önbellek, Migrasyon ve Telemetri

| Paket | Durum | Kullanım Yeri |
|-------|-------|---------------|
| `SQLAlchemy` + `asyncpg` | `SQLAlchemy` çekirdek; `asyncpg` opsiyonel (`[project.optional-dependencies].postgres`) | Async PostgreSQL veri katmanı |
| `redis` | Çekirdek bağımlılık | Semantic cache ve dağıtık rate-limit altyapısı |
| `alembic` | ✓ Zorunlu | Şema sürümleme ve migration zinciri |
| `prometheus-client` | ✓ Zorunlu | `/metrics` ve LLM telemetri export |
| `opentelemetry-api`, `opentelemetry-sdk`, `opentelemetry-exporter-otlp` | Opsiyonel (`[project.optional-dependencies].telemetry`) | Distributed tracing + OTLP export |
| `opentelemetry-instrumentation-fastapi`, `opentelemetry-instrumentation-httpx` | Opsiyonel (`telemetry`) | FastAPI/HTTPX span enstrümantasyonu |
| `tiktoken` | ✓ Zorunlu | Token ölçümü ve özetleme eşikleri |

#### 7.2.1 Performans ve Ölçeklenebilirlik Notu (SQLite)
- **SQLite Concurrency Yönetimi:** SQLite modunda çalışırken, ASGI (FastAPI) eşzamanlılığında thread çakışmalarını önlemek için global bağlantı kullanımı yerine sıralı erişim/izolasyon stratejisi zorunlu kabul edilir. Kurumsal ölçekte önerilen hedef mimari doğrudan PostgreSQL (`asyncpg` pool) işletimidir; SQLite yalnızca edge/dev senaryolarında düşünülmelidir.
- **pgvector / psycopg2 Notu:** Kod tabanı pgvector backend desteği içerir; ancak mevcut `pyproject.toml` içinde `pgvector` veya `psycopg2` ayrı pinli bağımlılık olarak yer almaz. Kurumsal PostgreSQL kurulumunda bu destek ek runtime paketleri ile etkinleştirilir.

### 7.3 Güvenlik, Sandbox ve Donanım Gözlemlenebilirliği

| Paket | Durum | Kullanım Yeri |
|-------|-------|---------------|
| `docker` | Kritik/opsiyonel | Zero-Trust REPL sandbox çalıştırma |
| `yt-dlp`, `ffmpeg`, `whisper` (CLI) | Sistem seviyesi zorunlu (multimodal iş akışları için) | Harici video/ses indirme, dönüştürme, transkripsiyon ve özetleme zinciri (`core/multimodal.py`) |
| `nvidia-ml-py` + `psutil` | Opsiyonel | GPU/CPU/RAM donanım metrikleri |
| `cryptography` | Opsiyonel | Fernet tabanlı şifreleme yardımcıları |
| `python-multipart`, `packaging`, `pyyaml` | ✓ Zorunlu | Yardımcı runtime bileşenleri |

### 7.4 AI Sağlayıcıları, Gateway Desteği ve RAG Katmanı

| Paket | Durum | Kullanım Yeri |
|-------|-------|---------------|
| `anthropic`, `google-generativeai` | Opsiyonel (sağlayıcıya göre) | Sağlayıcıya özel resmi SDK entegrasyonları |
| `openai` | Ayrı paket pinli değil | OpenAI ve OpenAI-uyumlu uç noktalar mevcut kodda `httpx` tabanlı istemci üzerinden kullanılır |
| `litellm` | Ayrı paket pinli değil | LiteLLM Gateway desteği vardır; ancak mevcut repo bunu `litellm` Python SDK yerine HTTP/OpenAI-uyumlu gateway sözleşmesiyle tüketir |
| `chromadb` + `sentence-transformers` | Opsiyonel (`[project.optional-dependencies].rag`) | Vektör tabanlı RAG ve embedding |
| `rank-bm25` | Çekirdek bağımlılık | BM25 tabanlı hibrit arama uyumluluğu |
| `duckduckgo-search` + `beautifulsoup4` + `bleach` + `PyGithub` | Opsiyonel/çekirdek karışık kullanım | Web/GitHub entegrasyonları ve HTML sanitizasyonu |
| `torch` + `torchvision` | Opsiyonel (`[project.optional-dependencies].rag`) | Embedding ve GPU hızlandırmalı iş yükleri |

**Geçiş Notu (v4.0 hazırlığı):** `torch`, `torchvision` ve `sentence-transformers` bağımlılıkları `pyproject.toml` altında `rag` extras grubuna taşınmıştır; minimal CLI kurulumları artık ağır GPU/RAG paketlerini zorunlu çekmez.

**Bilinen bağımlılık açığı — `chromadb==0.5.20` (kabul edilmiş risk, `security/pip-audit-ignores.tsv`):** pip-audit üç yamasız CVE raporluyor (`CVE-2026-45830`/GHSA-2wm9-hf6c-p5cr, `CVE-2026-45833`/GHSA-36p7-vc44-83pf, `CVE-2026-45831`/GHSA-xph7-9rjv-w5fr; hiçbirinde `fix_version` yok). Üçü de ChromaDB'nin *sunucu modu* çok-kiracılı REST/RBAC katmanındaki yetkilendirme açıkları. Sidar bu yüzeyi hiç kullanmaz: `core/rag/backends/chroma.py` yalnızca embedded/in-process `chromadb.PersistentClient` çağırır, repo genelinde `HttpClient`/`AsyncHttpClient`/`chroma run` veya bir Chroma docker-compose servisi yoktur; ayrıca kurulum betiği `.env` içinde varsayılan olarak `RAG_VECTOR_BACKEND=pgvector` yazar, yani chromadb yalnızca opsiyonel bir fallback'tir ve çok-kiracılı RBAC/izolasyon zaten §5.3.8'de anlatılan uygulama-seviyesi katman tarafından sağlanır. İstisnalar `2026-11-30`'da sona erer; `next_review=2026-10-15` — o tarihte yamalı bir chromadb sürümü çıkıp çıkmadığı kontrol edilmeli.

#### 7.4.1 Frontend (React / Node.js) Paketleri

| Paket | Durum | Kullanım Yeri |
|-------|-------|---------------|
| `react`, `react-dom` | ✓ Zorunlu (`web_ui_react/package.json`) | Modern React SPA çekirdeği |
| `react-router-dom` | ✓ Zorunlu | Route tabanlı SPA navigasyonu |
| `react-markdown`, `remark-gfm`, `rehype-highlight` | ✓ Zorunlu | Sohbet/RAG çıktılarının zengin render edilmesi |
| `zustand` | ✓ Zorunlu | React durum yönetimi |
| `vite`, `@vitejs/plugin-react` | ✓ Zorunlu (frontend build) | Geliştirme sunucusu ve üretim build zinciri |
| `eslint` | ✓ Zorunlu (frontend QA) | React UI lint/kalite kapısı |

### 7.5 Test ve Kalite Kapıları (Dev Bağımlılıkları)

| Paket | Durum | Kullanım Yeri |
|-------|-------|---------------|
| `pytest`, `pytest-asyncio`, `pytest-cov`, `pytest-benchmark` | ✓ Zorunlu (CI/QA) | Test yürütme, async test, coverage gate, benchmark |
| `ruff format --check`, `ruff check`, `mypy` | ✓ Zorunlu (CI/QA) | Format, lint ve statik analiz kalite kapıları |
| `uv` | Ortam/araç bağımlılığı | `environment.yml` ve `uv.lock` ile hızlı kilit/paket yönetimi iş akışı |

**Geçiş Notu (v3.0):**
- `requests` bağımlılığı doğrudan runtime listesinde yer almamaktadır; ana HTTP akışı `httpx` ile asenkron modele taşınmıştır.
- `rank-bm25` bağımlılığı ise mevcut bağımlılık dosyalarında hâlen tanımlıdır; hibrit RAG/BM25 uyumluluğu için opsiyonel katmanda korunmaktadır.
- `chardet` şu an doğrudan bağımlılık listesinde pinlenmemiştir; encoding fallback davranışı uygulama katmanında güvenli decode stratejileriyle yönetilmektedir.

**Auth Notu (v3.0):** Güncel kod tabanında kimlik doğrulama bearer token + DB tabanlı oturum modeli ile yürütülür. Şifre doğrulama `core/db.py` içinde Argon2id varsayılanı ve legacy PBKDF2-HMAC doğrulamasıyla yapılır; **`PyJWT~=2.9.0`** `pyproject.toml` çekirdek bağımlılıkları arasında yer alır ve `web_server.py` içinde stateless JWT token üretimi/doğrulaması için kullanılır.

---

## 8. Kod Satır Sayısı Özeti

[⬆ İçindekilere Dön](#içindekiler)

Bu bölüm, 2026-03-26 tarihinde `scripts/collect_repo_metrics.sh` ve `scripts/audit_metrics.sh` ile takipli depo içeriği için yeniden üretilen `wc -l` ölçümlerini içerir.

**Hacimsel özet (yönetici görünümü):** 2026-03-26 ölçümünde takipli depo yüzeyi **408 dosya / 116.053 satır** seviyesindedir (`.py/.js/.css/.html/.md`). Python tarafında üretim kodu **32.936 satır / 70 dosya**, test havuzu **65.729 satır / 213 `test_*.py` modülü**, toplam Python hacmi ise **98.665 satır / 285 dosya** olarak doğrulanmıştır; ayrıca takipli Markdown havuzu **10.148 satır / 102 dosya** ile kurumsal dokümantasyon yükünü net biçimde göstermektedir. `web_ui_react/` altındaki **38** takipli dosya / **10.792** satırlık SPA hacmi ve `web_ui/` altındaki **4.769** satırlık legacy yüzey birlikte değerlendirildiğinde, Coverage/Poyraz ajanlarıyla genişleyen Faz E yüzeyi artık ölçülebilir ürün olgunluğunun parçası haline gelmiştir.

- **Test ağırlığı:** Python kod hacminin en büyük payı `tests/` altındaki unit, integration ve enterprise senaryo testlerinden gelir.
- **Backend + Swarm çekirdeği:** `core/`, `agent/`, `managers/` ve giriş dosyaları projenin ana motorunu oluşturan binlerce satırlık Python iş mantığını barındırır.
- **Modern frontend katmanı:** Legacy `web_ui/` korunurken `web_ui_react/` altındaki React/Vite SPA projeye ek JavaScript/JSX/CSS hacmi kazandırır.
- **Altyapı ve dokümantasyon:** Helm chart'ları, Docker/Grafana/Prometheus dosyaları, CI akışları ve runbook'lar üretim işletimini kod olarak tanımlar.

**Ölçüm notu (standart):** Kurumsal tekrar üretilebilirlik için satır sayısı raporları `scripts/audit_metrics.sh` ve `scripts/collect_repo_metrics.sh` ile otomatik üretilmelidir. Her iki betik de Git deposu içinde varsayılan olarak yalnızca takipli dosyaları ölçer.

### 8.1 Çekirdek Modüller (Güncel)

| Dosya | Satır |
|---|---:|
| `config.py` | 885 |
| `main.py` | 382 |
| `cli.py` | 290 |
| `web_server.py` | 3.213 |
| `agent/sidar_agent.py` | 689 |
| `agent/auto_handle.py` | 613 |
| `agent/definitions.py` | 169 |
| `agent/tooling.py` | 127 |
| `agent/base_agent.py` | 112 |
| `agent/registry.py` | 187 |
| `agent/swarm.py` | 541 |
| `core/llm_client.py` | 1.388 |
| `core/memory.py` | 301 |
| `core/rag.py` | 1.685 |
| `core/db.py` | 1.861 |
| `core/llm_metrics.py` | 282 |
| `core/agent_metrics.py` | 118 |
| `core/dlp.py` | 320 |
| `core/hitl.py` | 287 |
| `core/judge.py` | 476 |
| `core/router.py` | 211 |
| `core/entity_memory.py` | 281 |
| `core/cache_metrics.py` | 189 |
| `core/active_learning.py` | 772 |
| `core/vision.py` | 294 |
| `core/voice.py` | 310 |
| `managers/security.py` | 291 |
| `managers/code_manager.py` | 1.529 |
| `managers/github_manager.py` | 645 |
| `managers/system_health.py` | 538 |
| `managers/web_search.py` | 388 |
| `managers/package_info.py` | 344 |
| `managers/todo_manager.py` | 452 |
| `managers/slack_manager.py` | 234 |
| `managers/jira_manager.py` | 245 |
| `managers/teams_manager.py` | 234 |
| `managers/browser_manager.py` | 718 |
| `github_upload.py` | 295 |
| `gui_launcher.py` | 98 |

### 8.2 Multi-Agent Çekirdek ve Roller

| Dosya | Satır |
|---|---:|
| `agent/core/supervisor.py` | 291 |
| `agent/core/contracts.py` | 256 |
| `agent/core/event_stream.py` | 218 |
| `agent/core/memory_hub.py` | 55 |
| `agent/core/registry.py` | 30 |
| `agent/roles/coder_agent.py` | 168 |
| `agent/roles/researcher_agent.py` | 80 |
| `agent/roles/reviewer_agent.py` | 707 |
| `agent/roles/coverage_agent.py` | 262 |
| `agent/roles/poyraz_agent.py` | 498 |

### 8.3 Migration / Operasyon / Altyapı

| Dosya | Satır |
|---|---:|
| `migrations/env.py` | 66 |
| `migrations/versions/0001_baseline_schema.py` | 99 |
| `migrations/versions/0002_prompt_registry.py` | 53 |
| `migrations/versions/0003_audit_trail.py` | 38 |
| `migrations/versions/0004_faz_e_tables.py` | 144 |
| `scripts/migrate_sqlite_to_pg.py` | 92 |
| `scripts/load_test_db_pool.py` | 74 |
| `scripts/audit_metrics.sh` | 84 |
| `scripts/collect_repo_metrics.sh` | 35 |
| `scripts/install_host_sandbox.sh` | 201 |
| `docker/prometheus/prometheus.yml` | 8 |
| `docker/grafana/provisioning/datasources/prometheus.yml` | 9 |
| `docker/grafana/provisioning/dashboards/dashboards.yml` | 11 |
| `docker/grafana/dashboards/sidar-llm-overview.json` | 1.004 |
| `runbooks/production-cutover-playbook.md` | 182 |
| `runbooks/observability_simulation.md` | 87 |
| `runbooks/plugin_marketplace_demo.md` | 32 |
| `runbooks/tenant_rbac_scenarios.md` | 66 |
| `plugins/crypto_price_agent.py` | 50 |
| `plugins/upload_agent.py` | 11 |
| `Dockerfile` | 104 |
| `docker-compose.yml` | 264 |

### 8.4 Frontend ve Test Özeti

| Kapsam | Değer |
|---|---:|
| `web_ui/index.html` | 640 |
| `web_ui/style.css` | 1.685 |
| `web_ui/chat.js` | 711 |
| `web_ui/sidebar.js` | 413 |
| `web_ui/rag.js` | 132 |
| `web_ui/app.js` | 819 |
| **Web UI Toplamı (`web_ui/` + `web_ui_react/`)** | **15.561** |
| **Legacy UI (`web_ui/` toplam takipli satır)** | **4.769** |
| **React UI (`web_ui_react/` toplam takipli satır)** | **10.792** |
| **Voice UI alt kümesi (`VoiceAssistantPanel.jsx` + `useVoiceAssistant.js`)** | **711** |
| **Test modülü (`tests/test_*.py`)** | **213** |
| **`tests/*.py` toplam satır** | **65.729** |

### 8.5 Dizin Bazlı Hacim Özeti

| Dizin/Kapsam | Ölçüm | Değer |
|---|---|---:|
| `tests/` | `test_*.py` modül sayısı | 213 |
| `tests/` | `*.py` toplam dosya | 215 |
| `tests/` | `*.py` toplam satır | 65.729 |
| `web_ui_react/` | toplam takipli satır | 10.792 |
| `scripts/` | dosya sayısı | 7 |
| `scripts/` | toplam satır | 613 |
| `migrations/` | `.py` dosya sayısı (env.py + 4 versions) | 5 |
| `migrations/` | `*.py` toplam satır | 396 |
| `helm/sidar/` | şablon dosyası sayısı (templates/ dahil) | 25 |
| `helm/sidar/` | toplam satır | 913 |
| `docker/` | metin tabanlı stack dosyası sayısı (`*.yml`, `*.json`) | 4 |
| `docker/` | ilgili telemetri dosyaları toplam satır | 1.032 |
