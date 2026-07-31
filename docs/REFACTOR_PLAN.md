# Büyük Production Dosyaları Refactor Planı

Bu plan, mevcut davranışı koruyarak yüksek sorumluluk yoğunluğuna sahip üretim dosyalarını
küçük, test edilebilir ve domain odaklı modüllere ayırmak için yaşayan takip dokümanıdır.
Dosya boyutu tek başına hata değildir; ancak endpoint, orchestration, storage veya tool execution
sorumlulukları aynı dosyada biriktiğinde review maliyeti ve regresyon riski artar. Bu nedenle her
adım küçük PR'lara bölünmeli, public/legacy import sözleşmeleri korunmalı ve mevcut unit/integration
testleri taşınan kodla birlikte çalışmaya devam etmelidir.

## Refactor ilkeleri

- **Davranış koruma:** Önce modül boundary'si çıkarılır, ardından fonksiyon/sınıf taşınır; route path,
  response schema, environment variable ve legacy export isimleri değişmez.
- **Küçük PR:** Her PR tek domain kümesine odaklanır; geniş dosya taşıma + davranış değişikliği aynı PR'a
  konmaz.
- **Test-first güvence:** Taşımadan önce mevcut testler hedef modüle yönlendirilir veya direkt modül testi
  eklenir; smoke/API testleri geriye dönük import yüzeyini doğrular.
- **Compatibility shim:** Büyük dosyada kalan `import`/wrapper/export geçici olabilir, fakat TODO ve takip
  satırıyla kaldırılacağı hedef faz belirtilmelidir.
- **Yan etki izolasyonu:** DB, shell, Docker, LLM, WebSocket ve dosya sistemi çağrıları domain servislerine
  ayrılırken fake/mock fixture'ları korunur.

## Güncel bakım hotspot snapshot'ı (2026-07-31)

Aşağıdaki ölçüm işlevsel hata anlamına gelmez; yeni katkıda bulunanların
gezinme/review maliyetini azaltmak için refactor backlog'unu görünür tutar.
Plugin yürütme izolasyonu aşağıda ayrı bir **P0 güvenlik maddesi** olarak ele alınır;
bu nedenle genel refactor sıralamasına veya dosya boyutuna göre ertelenemez.
Satır sayısı tek başına hedef değildir; her adım domain boundary,
test kapısı ve legacy import uyumluluğu ile birlikte ilerlemelidir.

| Dosya | Yaklaşık satır | Not |
|---|---:|---|
| `web_server.py` | 2747 | Auth/JWT `web/security.py`, rate-limit `web/middleware/ratelimit.py`, plugin policy `web/plugins/sandbox.py` ve route domainleri `web/routes/` altında ayrıldı; plugin sandbox policy üretimde fail-closed kalır, ana dosyada legacy monkeypatch/import wrapper azaltımı sürmeli. |
| `run_tests.sh` | 2211 | Quality gate orchestration büyüdü; summary JSON üretimi ayrıldı, benchmark/frontend/coverage stage helper'ları ayrı script modüllerine çıkarılmalı. |
| `core/db/monolith.py` | 1846 | Eski `core/db.py` artık `core/db/` paketi; auth/audit/session/user/prompt/metrics/diagnostics/records/dialect/helpers modülleri ayrıldı ve `core/db/__init__.py` geriye dönük uyumlu facade oldu. `list_marketing_campaigns`/`list_content_assets`/`list_operation_checklists` read-only query gövdeleri `core/db/marketing.py` içine taşındı (facade metotları korundu); yazma yollu `upsert_marketing_campaign`/`add_content_asset`/`add_operation_checklist` ve coverage/access-policy API yüzeyi hâlâ `monolith.py` içinde yoğunlaşıyor. |
| `config.py` | 1856 | Dotenv, logging, secret hardening, runtime path inference, rate-limit/Redis, event bus/Kafka, RAG store ve Docker sandbox loaderları ayrıldı; facade hâlâ çok sayıda class attribute compatibility yüzeyi taşıyor. |
| `install_sidar.sh` | 1888 | CLI argüman parsing `scripts/install_modules/install_cli.sh`, faz dispatcher `scripts/install_modules/install_dispatcher.sh` içine ayrıldı; ana script bootstrap facade olarak daha da inceltilmeli. Son dönemde installer supply-chain sertleştirmesi (SHA-pinli commit, embedded hash manifesti, fail-closed doğrulama) satır sayısını artırdı; bu güvenlik yüzeyi taşınırken davranış korunmalı. |
| `agent/sidar_agent.py` | 1560 | Self-heal planlama ve execute/rollback, autonomy ve federation helperları ayrıldı; facade küçültme tool/subtask sınırıyla sürmeli. |
| `core/rag/__init__.py` | 1581 | Query, metadata, entity graph/extraction, projection ve backend helperları ayrıldı; `DocumentStore` compatibility sınıfının kalan orchestration gövdesi hâlâ bu dosyada. |
| `main.py` | 1473 | Launcher CLI parsing, wizard, process supervision ve session telemetry hâlâ tek facade'da; Doctor preflight orkestrasyonu `core/doctor/launcher_preflight.py` içine ayrıldı. |
| `managers/code_manager.py` | 1390 | Docker SDK lifecycle ve shell sandbox adapterları ayrıldı; facade wrapper azaltımı güvenli şekilde sürdürülebilir. |

## P0 güvenlik backlog'u

### `SEC-PLUGIN-001` — Plugin yürütmesini process/container sınırına taşı

- **Öncelik:** P0 — production güvenlik sınırı; genel refactor maddelerinden önce ele alınır.
- **Durum:** Planlandı; production process-içi yürütme koşulsuz fail-closed, izole backend henüz yok.
- **Sahip:** Backend/Güvenlik bakım ekibi.
- **Hedef değerlendirme:** 2026-08-15.
- **Hedef kapanış:** 2026-09-30.
- **Mevcut risk:** AST doğrulaması ve kısıtlı builtins savunma-derinliğidir; işletim sistemi
  seviyesinde güvenlik sınırı değildir. Geliştirme/test profilinde çalışan plugin kodu host
  process'in bellek, kimlik ve yaşam döngüsü sınırını paylaşır.
- **Hedef mimari:** `web.plugins.sandbox` çağrısını typed request/response sözleşmeli bir
  backend arayüzüne yönlendir; varsayılan production backend'ini `managers/code_manager.py`
  tarafından kullanılan Docker sandbox limitleriyle (ağ kapalı, salt-okunur dosya sistemi,
  CPU/bellek/PID/timeout sınırları, ayrı düşük yetkili kullanıcı) çalıştır. Docker kullanılamıyorsa
  production çağrısı fallback yapmadan reddedilir. Process backend yalnız aynı limitleri işletim
  sistemi düzeyinde uygulayabilen destekli geliştirme ortamlarında seçilebilir.
- **Geçiş sırası:** (1) RPC envelope ve backend protokolü, (2) container worker + kaynak
  limitleri, (3) lifecycle/timeout/kill ve hata redaksiyonu, (4) marketplace registration'ı
  doğrudan Python sınıfı yüklemek yerine izole agent proxy'sine taşıma, (5) legacy process-içi
  backend'i ve `SIDAR_ENABLE_IN_PROCESS_PLUGINS` bayrağını kaldırma.
- **Kabul kriterleri:**
  1. Production plugin yükleme/çalıştırma yolunda host process içinde `compile`/`exec` çağrısı yoktur.
  2. Ağ, dosya sistemi, environment/secret, subprocess ve host process erişim kaçış testleri
     container sınırında reddedilir.
  3. Timeout, OOM, worker crash ve malformed RPC cevapları fail-closed sonuçlanır; worker zorla
     sonlandırılır ve hassas veri loglanmaz.
  4. Agent çağrı/yetenek/hata şeması sürümlüdür; uyumsuz plugin host'a import edilmeden reddedilir.
  5. Docker bulunmayan production ortamında yerel subprocess veya process-içi fallback oluşmaz.
  6. Unit sandbox contract testlerine ek olarak container integration ve marketplace smoke testleri
     release kapısında geçer.
- **Bloklayıcı kural:** Yeni plugin özelliği process-içi backend yüzeyini genişletemez. Bu madde
  kapanana kadar yalnız izolasyon geçişi, fail-closed sertleştirmesi ve test değişiklikleri kabul edilir.

## Öncelikli büyük dosyalar

| Dosya | Risk nedeni | Hedef modül sınırı | İlk düşük riskli adım | Test kapısı |
|---|---|---|---|---|
| `web_server.py` | Endpoint, WebSocket, middleware, auth, frontend fallback ve bootstrap tek dosyada yoğunlaşıyor; plugin marketplace içinde AST-validated `exec()` hâlâ process/container sandbox değildir. | `web/routes/ws_chat.py`, `web/routes/ws_voice.py`, `web/routes/collaboration.py`, `web/routes/webhooks.py`, `web/routes/operations.py`, `web/security.py`, `web/plugins/sandbox.py`, `web/app_factory.py`, `web/bootstrap.py`, `web/middleware/cors.py` | App factory boundary'si `web/app_factory.py` içine çıkarıldı; GitHub webhook router çıkarımı yapıldı; `/ws/chat` router factory, `/ws/voice` router factory, HITL router ve WebSocket token parser (`web/security.py`) çıkarımı yapıldı; frontend static mount ve SPA fallback bootstrap boundary'si `web/bootstrap.py` içine çıkarıldı; **middleware/frontend fallback bootstrap boundary** kapsamında loopback CORS middleware bootstrap'ı `web/middleware/cors.py`, access policy middleware orchestration'ı `web/middleware/access_policy.py`, frontend fallback/bootstrap akışı `web/bootstrap.py` modüllerine taşındı; plugin AST/policy helperları `web/plugins/sandbox.py` modülüne ve açıkça legacy olarak adlandırılan tek process-içi runtime backend seam’i aynı modüle taşındı; `web_server.py` artık plugin kaynak yürütme ayrıntılarını barındırmak yerine bu seam’e delege ediyor. Production ortamında process-içi plugin exec artık yalnız varsayılan olarak değil koşulsuz fail-closed'dur; `SIDAR_ENABLE_IN_PROCESS_PLUGINS=1` bu sınırı aşamaz. **Sıradaki öncelikli adım P0 `SEC-PLUGIN-001`'dir:** plugin kaynak yürütmesini mevcut `managers/code_manager.py` Docker sandbox sözleşmesiyle uyumlu container/process izolasyonuna tamamen taşımak. Lifecycle/bootstrap refactorları bu güvenlik maddesinin önüne geçmez. | `tests/unit/root/test_web_server.py`, `tests/unit/web/*`, plugin marketplace tests, sandbox contract tests, smoke boot tests |
| `run_tests.sh` | Static analysis, coverage, BATS, benchmark, frontend, artifact summary ve production-readiness orchestration tek shell dosyasında büyüyor. | `scripts/test_gates/static_analysis.sh`, `scripts/test_gates/backend_pytest.sh`, `scripts/test_gates/benchmark.sh`, `scripts/test_gates/frontend.sh`, `scripts/test_gates/summary.py` | Salt raporlama/summary JSON üretimi `scripts/test_gates/summary.py` içine çıkarıldı; benchmark baseline/compare/trend fazı `scripts/test_gates/benchmark_helpers.sh::run_benchmark_quality_gate` sınırına taşındı ve `run_tests.sh` yalnız faz çağrısını yapıyor. Sıradaki düşük riskli adım frontend gate orkestrasyonunu mevcut `frontend_helpers.sh` contract'ına taşımak. | `make production-readiness`, `tests/unit/scripts/*`, shellcheck/BATS gates |
| `install_sidar.sh` | Modüler installer modülleri olmasına rağmen bootstrap, UX, validation ve fallback yüzeyi ana scriptte yoğun kalıyor. | `scripts/install_modules/install_cli.sh`, `scripts/install_modules/install_dispatcher.sh`, `scripts/install_modules/install_runtime.sh`, `scripts/install_modules/bootstrap.sh`, `scripts/install_modules/utils/ux.sh`, `scripts/install_modules/validation.sh`, `scripts/install_modules/offline_bundle.sh` | CLI defaults/argument normalization `install_cli.sh`, sıralı phase dispatcher `install_dispatcher.sh` içine çıkarıldı; ana script bootstrap facade olarak korundu. Post-bootstrap progress/prompt/geçici modül cleanup/log relocation yardımcıları doğrulanmış `install_runtime.sh` modülüne taşındı; servis Docker/health helperları `scripts/install_modules/utils/services_docker.sh`, .env secret hardening helperları `scripts/install_modules/utils/env_secrets.sh` içinde tutuluyor. Sıradaki düşük riskli adım, doğrulanmamış bootstrap modülünü source ederek trust root'u bozmadan, remote module bootstrap ve manifest/hash guard fallbacklerini gömülü veya önceden doğrulanabilir `bootstrap.sh` sınırına taşımak. | installer smoke, `tests/unit/scripts/*`, shellcheck |
| `main.py` | CLI parsing, launcher wizard, Doctor preflight, process supervision ve session telemetry tek dosyada birleşiyor. | `main/cli.py`, `main/wizard.py`, `main/commands.py`, `main/supervision.py`, `main/session.py`, `core/doctor/launcher_preflight.py` | Launcher Doctor preflight sıralama/skip/parallel execution akışı `core/doctor/launcher_preflight.py` içine taşındı; `main.py` yalnız UI hook'ları, renkler ve env reload/auto-fix callback'lerini enjekte eden facade olarak kaldı. Sıradaki düşük riskli adım CLI parser ve process supervision sınırını aynı compatibility yüzeyiyle ayırmak. | `tests/unit/root/test_web_server.py`, `tests/unit/cli/test_main_helpers.py`, launcher smoke |
| `core/db/monolith.py` (eski `core/db.py`) | Schema, kullanıcı, oturum, mesaj ve operational persistence API yüzeyi hâlâ tek ~1850 satırlık modülde. | `core/db/auth.py`, `core/db/audit.py`, `core/db/coverage.py`, `core/db/marketing.py`, `core/db/session.py`, ortak `core/db/models.py` | `core/db.py` artık `core/db/` paketi; `auth.py`, `audit.py`, `coverage.py`, `marketing.py`, `session.py`, `sessions.py`, `users.py`, `prompt_registry.py`, `metrics.py` ve `models.py` akışları çıkarıldı, `audit_log.py` legacy compatibility wrapper olarak bırakıldı. PostgreSQL teşhisleri `core/db/diagnostics.py`, saf zaman/JSON/UUID/SQLite helperları `core/db/helpers.py`, SQL dialect/asyncpg tag helperları `core/db/dialect.py`, domain dataclass kayıtları `core/db/records.py` modüllerine taşındı ve `core/db/__init__.py` legacy re-export facade'ı olarak korundu. 2026-07-20'de ilk read-only query helper adımı atıldı: `list_marketing_campaigns`, `list_content_assets`, `list_operation_checklists` gövdeleri `core/db/marketing.py`'ye taşındı ve `Database` üzerindeki metotlar ince delege wrapper'a indirildi (`core/db/__init__.py`'deki submodule whitelist'ine `marketing` eklendi — aksi halde `core.db` self-aliasing swap'ı sonrası `import core.db.marketing` kırılıyordu). Sıradaki düşük riskli adım aynı deseni `upsert_marketing_campaign`/`add_content_asset`/`add_operation_checklist` yazma yollarına ve `list_coverage_tasks`/`list_access_policies` read-only sorgularına uygulamak. | `tests/unit/core/test_db.py`, migration integration tests |
| `core/rag/__init__.py` | Embedding, store, query, GraphRAG ve package init davranışları aynı dosyada. | `core/rag/embeddings.py`, `core/rag/store.py`, `core/rag/query.py`, `core/rag/graph.py`, `core/rag/facade.py` | pgvector identifier/diagnostic helperları `core/rag/pgvector_helpers.py`, recursive chunking helperı `core/rag/chunking.py`, GraphRAG entity slug/id/value normalizer helperları `core/rag/entity_helpers.py` içine taşındı ve `__init__` içinde monkeypatch/import uyumlu facade bırakıldı. Arama sonuç formatlayıcıları `core/rag/formatting.py`, GraphRAG metin raporu formatlayıcıları `core/rag/graph_formatting.py`, knowledge graph projection builderları `core/rag/projection.py`, belge/chunk metadata builderları `core/rag/metadata.py`, session belge listeleme/consolidation seçici helperları `core/rag/session_documents.py` içine taşındı. DocumentStore içindeki entity extraction orchestration `core/rag/entity_extraction.py`, entity graph load/save/upsert/delete/search persistence sınırları `core/rag/entity_graph_store.py` içine ayrıldı. Sıradaki düşük riskli adım DocumentStore facade wrapper sayısını azaltıp graph/index orchestration yan etkilerini daha küçük servislerde toplamak. | `tests/unit/core/test_rag.py`, RAG integration tests |
| `config.py` | Env yükleme, secret hardening, GPU detect orkestrasyonu, runtime path inference, logging bootstrap ve çok sayıda backend domain setting'i tek facade içinde yoğunlaşıyor. | `core/config_dotenv.py`, `core/config_dirs.py`, `core/config_gpu_detect.py`, `core/config_logging_setup.py`, `core/config_runtime_env.py`, `core/config_runtime_paths.py`, `core/config_secret_hardening.py`, `core/config_secrets.py`, `core/config_rate_limit.py`, `core/config_event_bus.py`, `core/config_rag_store.py`, `core/config_sandbox.py` | Dotenv parse/load/reload tanılama helperları `core/config_dotenv.py`, logging bootstrap helperları `core/config_logging_setup.py`, secret hardening wrapperları `core/config_secret_hardening.py`, runtime path inference helperları `core/config_runtime_paths.py`, rate-limit/Redis loader'ı `core/config_rate_limit.py`, event bus/Kafka/RabbitMQ loader'ı `core/config_event_bus.py`, RAG store/pgvector loader'ı `core/config_rag_store.py` ve Docker sandbox loader'ı `core/config_sandbox.py` içine çıkarıldı; statik RAG default modülü `config_rag_defaults.py` olarak netleştirildi ve legacy `config_rag.py` yalnız shim olarak bırakıldı. Güncel değerlendirme: `config.py` gerçek bir god object değil; geriye dönük uyum için yaklaşık yirmi domain setting modülünü birleştiren compatibility facade'dır. İlk düşük riskli adım olarak `Config.llm_settings`, `Config.security_settings`, `Config.sandbox_settings` ve benzeri typed domain settings objeleri doğrudan expose edildi; sıradaki adım yeni kodu bu objelere yönlendirip legacy `Config.FOO` class attribute patch sayısını azaltmak. | `tests/unit/root/test_config.py`, boot diagnostics tests |
| `managers/code_manager.py` | Shell execution, Docker sandbox, patching, LSP adapter ve güvenlik kontrolleri tek sınıfta. | `managers/code/runner.py`, `managers/code/docker.py`, `managers/code/docker_lifecycle.py`, `managers/code/shell_sandbox.py`, `managers/code/patcher.py`, `managers/code/lsp.py`, `managers/code/security_adapter.py` | `docker.py`, `docker_lifecycle.py`, `shell_sandbox.py`, `patcher.py`, `security_adapter.py` ve `runner.py` eklendi; `CodeManager` Docker CLI/sandbox limit, Docker SDK lifecycle, shell sandbox, patch, IO güvenlik ve local shell yürütme kararlarını bu helper/adapterlara delege ediyor. Sıradaki düşük riskli adım LSP lifecycle wrapperlarını ve kalan compatibility shim sayısını azaltmak. | `tests/unit/managers/test_code_manager.py`, sandbox contract tests |
| `agent/sidar_agent.py` | Ana ajan orchestration, tool execution, self-heal, autonomy ve federation sorumlulukları birleşik. | `agent/tool_registry.py`, `agent/self_heal/planner.py`, `agent/self_heal/executor.py`, `agent/autonomy/service.py`, `agent/federation/service.py` | Deterministik teşhis/policy `core/ci_remediation.py` içinde bırakıldı; snapshot/batch/LLM patch-plan üretimi `agent/self_heal/planner.py`, execute/rollback sınırı `agent/self_heal/executor.py` içine taşındı. `SidarAgent` eski private metotları test/eklenti uyumluluğu için ince delegate wrapper olarak koruyor. Autonomy runtime history helperları `agent/autonomy/service.py`, federation task/action-feedback prompt builderları `agent/federation/service.py` içindedir. Sıradaki düşük riskli adım tool execution registry ve subtask loop adapter sınırlarını ayırmak. | `tests/unit/agent/test_sidar_agent.py`, `tests/unit/agent/self_heal/*`, CI remediation tests |
| `agent/roles/coverage_agent.py` | Coverage parsing, pytest output analysis, missing-test generation ve writer katmanları tek role içinde. | `agent/roles/coverage/analyzer.py`, `agent/roles/coverage/generator.py`, `agent/roles/coverage/writer.py`, `agent/roles/coverage/models.py` | Pure parsing/analyzer fonksiyonlarını yan etkisiz modüle taşıyıp role içinde orchestration bırakmak. | `tests/unit/agent/roles/test_coverage_agent.py`, coverage hotspot tests |
| `core/llm_client.py` | Tüm LLM provider adapter'ları, routing, semantic cache, DLP, retry, tracing ve Ollama stream parsing tek dosyada. | `core/llm/ollama.py`, `core/llm/openai.py`, `core/llm/anthropic.py`, `core/llm/gemini.py`, `core/llm/litellm.py`, compatibility shims under `core/llm/providers/*.py` (starting with `core/llm/providers/ollama.py`), `core/llm/router.py`, `core/llm/streaming.py`, `core/llm/cache.py`, `core/llm/facade.py` | P2 LLM provider adapter modülleri (`core/llm/{openai,anthropic,gemini,ollama,litellm}.py`) çıkarıldı ve public `LLMClient` facade/import boundary'si provider contract testleriyle korunuyor; routing/streaming/semantic cache/facade sorumlulukları `core/llm/{router,streaming,cache,facade}.py` modüllerine ayrıldı: routing adapterı `core/llm/router.py`, streaming helperları `core/llm/streaming.py`, semantic cache adapterı `core/llm/cache.py` ve provider facade contractı `core/llm/facade.py` içine çıkarıldı. Sıradaki düşük riskli adım DLP/retry/tracing wrapperlarını aynı compatibility yüzeyini koruyarak daraltmak. | `tests/unit/core/test_llm_client.py`, provider contract tests |
| `core/doctor.py` | Health check, dependency probing, GPU/Redis/DB/RAG doğrulamaları ve orchestration tek facade içinde yoğunlaşıyor. | `core/doctor/checks/database.py`, `core/doctor/checks/gpu.py`, `core/doctor/checks/redis.py`, `core/doctor/checks/rag.py`, `core/doctor/checks/security.py`, `core/doctor/reporting.py`, `core/doctor/models.py`, `core/doctor/facade.py` | Yan etkisiz check result modeli/contract/redaction helperları `core/doctor/models.py`, rapor aggregate/write formatlayıcıları `core/doctor/reporting.py` içine çıkarıldı ve `core.doctor` legacy facade exportları korundu. Sıradaki düşük riskli adım health check orchestration wrapperlarını `core/doctor/facade.py` sınırına daraltmak. | `tests/unit/core/test_doctor.py`, CLI doctor smoke tests |
| `agent/roles/reviewer_agent.py` | Review orchestration, judging heuristics, LSP/browser evidence ve raporlama aynı role dosyasında birleşiyor. | `agent/roles/reviewer/analyzer.py`, `agent/roles/reviewer/judge.py`, `agent/roles/reviewer/reporter.py`, `agent/roles/reviewer/evidence.py`, `agent/roles/reviewer/models.py` | Reviewer gate için pure judging/prompt helperları `agent/roles/reviewer/judge.py` modülüne taşındı; role sınıfı compatibility wrapper ve orchestration facade olarak korunuyor. Sıradaki düşük riskli adım evidence/reporter formatlayıcılarını ayrı modüllere almak. | `tests/unit/agent/roles/test_reviewer_agent.py`, reviewer registry tests |
| `core/ci_remediation.py` | CI failure context parsing, remediation payload, patch plan normalize ve validation komut seçimi tek dosyada. Runtime plan üretimi/uygulaması artık burada değildir. | `core/ci_remediation/context.py`, `core/ci_remediation/payload.py`, `core/ci_remediation/plan.py`, `core/ci_remediation/validation.py`, `core/ci_remediation/models.py` | `build_local_failure_context` ve validation command normalizer'larını pure modüllere taşıyıp mevcut import yolunu re-export etmek; agent runtime planlamasını yeniden bu policy modülüne eklememek. | `tests/unit/core/test_ci_remediation.py`, auto-heal integration tests |
| `managers/browser_manager.py` | Playwright, Selenium fallback, scraping, screenshot, visual drift ve multimodal escalation tek sınıfta. | `managers/browser/playwright.py`, `managers/browser/selenium.py`, `managers/browser/screenshot.py`, `managers/browser/visual_drift.py`, `managers/browser/scraping.py`, `managers/browser/models.py` | P2 Playwright/Selenium adapter arayüzlerini ayırıp screenshot ve visual-drift pure helper'larını alt modüllere taşımak. | `tests/unit/managers/test_browser_manager.py`, browser visual QA tests |
| `agent/swarm.py` | Task routing, parallel/pipeline execution, P2P handoff, retry/loop guard ve distributed dispatch tek orchestration dosyasında. | `agent/swarm/router.py`, `agent/swarm/executor.py`, `agent/swarm/handoff.py`, `agent/swarm/distributed.py`, `agent/swarm/models.py` | `SwarmTask`/`SwarmResult` modellerini ve `TaskRouter`'ı alt modüllere taşıyıp `agent.swarm` facade export'unu korumak. | `tests/test_swarm_orchestrator.py`, `tests/unit/agent/core/test_supervisor.py` |

## Frontend (web_ui_react) refactor backlog'u (2026-07-24)

Backend/installer tablolarındaki ilkeler (davranış koruma, küçük PR, test-first
güvence) burada da geçerlidir. Aşağıdaki maddeler bir arkadaş kod incelemesinde
tespit edildi ve gerçek koda karşı doğrulandı. TypeScript envanter maddesi artık
tarihli fail-closed kilometre taşlarıyla aktif kampanyadır; kalan geniş bileşen
taşımaları küçük domain PR'ları için backlog'da tutulur.

- **TypeScript kademeli kapısı (aktif):** `tsconfig.json`
  içinde `checkJs: false`; ağaç hâlâ ağırlıklı olarak `.jsx`/`.js`, ancak üç `.ts`
  dosyası (`src/hooks/useThrottledStream.ts`, `src/hooks/useFormState.ts` ve
  `src/lib/swarmFlowGraph.ts`) strict kapıya alınmış durumda; 0 `.tsx` var.
  `npm run typecheck` bu yüzden yalnızca bu üç dosyayı ve TS tarafı modül
  çözümlemesini denetliyor;
  `.jsx`/`.js` bileşen/hook mantığı için gerçek bir tip güvencesi vermiyor.
  `checkJs: true` denendiğinde (yerel diagnostik, commit edilmedi) ağaç genelinde
  ~2974 önceden var olan hata çıktı — kapıyı kırmadan tek adımda açılamaz.
  Kademeli `.jsx` → `.tsx` taşıması için sahip **Frontend bakım ekibi**, ilk değerlendirme
  **2026-09-30**, hedef tamamlanma **2027-03-31** olarak atanmıştır. JS/JSX toplamındaki
  net artış anlık ratchet ile engellenir; ayrıca 2026-09-30'dan başlayarak 45/15,
  30/30, 12/48 ve 0/60 untyped/typed ara hedefleri tarih geldiğinde
  `npm run typecheck:inventory` tarafından fail-closed uygulanır. Aşamalar ve baseline sözleşmesi
  `docs/development/frontend-typescript-migration.md` içinde tutulur.
- **`src/components/SwarmFlowPanel.jsx` (435 → ~140 satır):** 14 `useState`, 5
  `fetchJson` çağrısı, graph türetme ve operasyon callback'leri
  `src/hooks/useSwarmFlowController.ts` hook'una çıkarıldı; panel artık render/composition
  sınırı olarak kaldı. Kalan adım: `GraphView`'e geçen ~19 prop'u görünüm-modeli ve action
  nesneleriyle gruplamak; hook'un geniş dönüş yüzeyini domain alt-hook'larına ayırmak.
  Test kapısı: `src/components/SwarmFlowPanel.test.jsx`, `SwarmFlowPanel.helpers.test.jsx`.
- **`src/lib/api.js` (~242 satır):** token yaşam döngüsü (bellek + localStorage +
  eski format migrasyonu + `sidar:token-change` custom event), genel `fetchJson`
  HTTP client'ı ve ~10 domain-özel endpoint fonksiyonu aynı dosyada. Hedef adım:
  `src/lib/tokenStore.js` (token okuma/yazma/migrasyon/event), `src/lib/httpClient.js`
  (`fetchJson`/auth header) ve `src/lib/api.js` (yalnız domain endpoint'leri, mevcut
  import yolunu re-export ederek) olarak ayırmak — en kırılgan parça (auth) izole
  test edilebilir hale gelir. Test kapısı: `src/lib/api.test.js` (zaten
  `npm run test:critical` içinde ayrıca çalıştırılıyor).
- **`src/hooks/useWebSocket.js` (~285 satır):** `onmessage` içinde eski düz mesaj
  şeması (`type` alanı olmadan `chunk`/`error`/`status` gibi alanlara duck-typing
  ile bakan fallback) ile yeni oda-tabanlı şema (`room_state`/`presence`/
  `collaboration_event` vb. açık `type` alanlı) aynı if/else zincirinde karışıyor.
  `{type: handler}` dispatch map'e geçiş mümkün ama `type` alanı olmayan legacy
  mesajlar için mutlaka bir fallback dalı korunmalı — naif bir map bunları
  sessizce kaybeder. Test kapısı: `src/hooks/useWebSocket.test.js`.
- **`src/hooks/useVoiceAssistant.js` (~648 satır):** mikrofon yakalama, VAD,
  websocket protokolü ve ses oynatma kuyruğu tek hook'ta. Hedef adım:
  `useMicCapture`/`useVAD`/`useVoiceSocket`/`useAudioPlaybackQueue` gibi
  kompoze edilebilir hook'lara bölmek; gerçek mikrofon/ses donanımına bağımlı
  olduğu için bu bölme yalnızca mock'lanmış test kapısıyla (mevcut
  `src/hooks/useVoiceAssistant.test.js`) doğrulanabilir, manuel donanım testi
  bu ortamda mümkün değil.
- **Auth token durumu (modül-seviyesi singleton + `sidar:token-change` DOM event):**
  bir `TokenProvider` React context'ine taşımak bağımlılığı daha açık/test edilebilir
  yapar, ancak `api.js` bölünmesiyle aynı yüzeyi paylaşıyor ve tüm tüketicilerin
  (component ağacının sarılması dahil) güncellenmesini gerektiriyor — `api.js`
  bölünmesinden sonra, ayrı bir adım olarak ele alınmalı.
- **`src/lib/routerShim.jsx` (113 satır):** bundle bütçesi için makul bir
  `react-router-dom` alternatifi; parametreli/nested route desteği yok. Bu bir
  hata değil, bilinçli bir trade-off — detay sayfaları eklendiğinde ölçeklenme
  sınırı olarak not edilir, şu an için aksiyon gerektirmiyor.

Bu turda tek somut kod değişikliği: `OperationsQaPanel.jsx` içindeki 4 form
state'inin (`landingForm`/`campaignForm`/`coverageForm`/`batchForm`) neredeyse
birebir aynı `setXForm((prev) => ({...prev, [key]: value}))` güncelleyicileri
paylaşılan bir `src/hooks/useFormState.js` hook'una çıkarıldı (davranış birebir
korundu, `OperationsQaPanel.test.jsx` + yeni `useFormState.test.js` ile doğrulandı).

## CI/Test altyapısı değerlendirmesi (2026-07-24)

Bir arkadaş kod incelemesinde `.github/workflows/` ve `run_tests.sh` için altı
bulgu tespit edildi; her biri gerçek workflow/script içeriğine karşı doğrulandı.
İkisi zaten çözülmüş/yanlış, biri kasıtlı bir politika kararı (kapı gevşetilmedi;
runner sürekliliği ayrıca sertleştirildi), ikisi önerilen haliyle uygulanırsa regresyona yol
açar, biri zaten ayrı bir bölümde takip ediliyor:

- **`gpu-inference-policy-gate` her fork/GPU runner'sız ortamda `production-readiness`'i bloke ediyor (doğrulandı, KASITLI TASARIM — süreklilik planı eklendi):**
  `docs/CI_REQUIRED_CHECKS.md` bunu açıkça belgeliyor: *"Forks without an eligible
  runner must provision one before claiming merge/release readiness; there is no
  silent checklist-only bypass."* Bu, sessizce atlanabilen bir kalite kapısını
  kapatmak için bilinçli olarak sertleştirilmiş bir tasarım — kazara oluşmuş bir
  bug değil. Ancak repo'nun gerçek `ENABLE_GPU_BENCH_GATE` repo/org değişkeni ve
  self-hosted GPU runner'ı fiilen yapılandırılı değilse, bu politika **hiçbir
  PR'ın** (bu PR dahil) "Production readiness aggregate" required check'ini
  geçemeyeceği anlamına gelir. Bu, yalnızca repo sahibinin bilebileceği bir
  operasyonel durumdur; kapı gevşetilmedi. Bunun yerine primary + warm-standby
  runner sözleşmesi, saatlik iki-online-runner watchdog'u, 30 dakikalık RTO ve üç aylık
  failover tatbikatı `docs/runbooks/gpu-runner-continuity.md` ile devreye alındı.
- **Tek "test" job'unda shellcheck+BATS+npm+bandit+pip-audit+production-readiness sırayla (doğrulandı, uygulanmadı):**
  Gerçek — `test` job'u (ci.yml:130-524) hepsini tek runner'da sırayla çalıştırıyor.
  Ancak iş parçacığı zaten `run_tests.sh` satırındaki üstteki tabloda takip
  ediliyor ("benchmark/frontend/coverage stage helper'larını ayrı script
  modüllerine çıkarmak"); CI job topolojisini bölmek `docs/CI_REQUIRED_CHECKS.md`
  tarafından açıkça riskli işaretlenmiş: *"If a job `name:` changes, update
  branch protection at the same time or this audit will fail; without that sync,
  PRs may either be blocked forever ... or allowed to merge without the intended
  release gate."* Bu yüzden job bölme, branch protection güncellemesiyle
  eş zamanlı, repo sahibinin GitHub ayarlarına erişimi olan ayrı bir adımda
  yapılmalı.
- **Benchmark cache key'i `github.run_id` içeriyor (doğrulandı, ÖNERİLEN DÜZELTME YANLIŞ — uygulanmadı):**
  `run_id`'yi kaydetme (save) anahtarından çıkarmak önerisi incelendi ve
  **regresyona yol açacağı** için uygulanmadı: GitHub Actions cache action aynı
  anahtarla mevcut bir girdiyi güncellemez (yalnızca yeni/benzersiz anahtarlarda
  kaydeder). `run_id` olmadan, bir (`ref`, `lockfile`) kombinasyonu için cache
  yalnızca ilk seferinde kaydedilir ve bir daha asla güncellenmez — "rolling
  baseline" mekanizması tamamen kırılır. Mevcut tasarım (benzersiz save-key +
  prefix-match `restore-keys`) bu deseni doğru şekilde uyguluyor; cache tahliyesi
  gerçek bir risk ama zaten dokümante edilmiş bir manuel kurtarma akışı var
  (`benchmark-baseline-seed.yml`, `seed_benchmark_baseline` workflow_dispatch
  girdisi) ve eksik baseline durumunda step summary bu akışı doğrudan gösteriyor.
- **10 workflow arasında örtüşme (doğrulandı, kısmen yanlış karakterize edilmiş):**
  `nightly-*`/`weekly-*`/`release-*` workflow'larının çoğu yalnızca cron ile
  tetikleniyor (PR başına maliyet eklemiyorlar), bu yüzden "CI süresi" endişesiyle
  ilgisizler — bakım yükü endişesi geçerli ama düşük öncelikli. Tek gerçek
  per-PR örtüşme adayı `migration-cutover-checks.yml` (push/PR üzerinde
  tetikleniyor, `ci.yml`'deki `pg-stress` ile aynı Postgres/migration alanında);
  incelendiğinde farklı teknikler kullandığı görüldü (Alembic
  upgrade/downgrade/upgrade zinciri + SQLite→Postgres dry-run rehearsal +
  `load_test_db_pool.py` betiği ile 50 eşzamanlı bağlantı yük testi vs.
  `pg-stress`'in `pytest -m pg_stress` tabanlı entegrasyon testleri) — bu yüzden
  saf bir tekrar değil, konsolidasyon sinyal kaybı riski taşıyor. Aksiyon
  alınmadı.
- **Ruff borç ratchet tarihleri yalnızca işaretleniyor, CI'ı bloke etmiyor (doğrulandı YANLIŞ, kod değişikliği gerekmedi):**
  `scripts/ci/check_policy_dates.py` (CI'da `test` job'unun "Check dated
  policy/debt expirations" adımında çalışıyor) süresi geçmiş
  `close_docstring_campaign_by`/`e501_global_ignore_review_by`/
  `close_async240_campaign_by`/torch CVE tarihlerinde **`return 1` ile CI'ı
  gerçekten kırıyor** (`_add_if_expired`); yalnızca yaklaşan tarihler için
  non-blocking uyarı (`_add_if_due_soon`) veriyor. Bulgu güncel koda uymuyor.

## Gerçek TODO envanteri

- `core/rag/graph.py` içindeki `LLM_ENTITY_EXTRACTION_TODO` (eski TODO), 2026-Q3 başlangıcında kapatıldı: deterministic GraphRAG entity extraction artık `ENABLE_RAG_LLM_ENTITY_EXTRACTION` feature flag'i arkasında LLM-destekli extractor ile genişletilebilir. `core/rag/llm_entity_extraction.py` içindeki prompt/coercion/schema validator sınırı korunur; LLM çıktısı bu sınırı geçmeden entity graph'a yazılmamalıdır.
- Repo genelindeki diğer `TODO` / `FIXME` eşleşmeleri ağırlıklı olarak `todo_manager.py` ve ilgili testlerinin tarama fixture'larıdır; bunlar açık ürün borcu değil, TODO/FIXME algılama mantığını doğrulayan test verileridir.

## Gözden geçirilip bilinçli olarak bu plana eklenmeyen dosyalar

- **`managers/github_manager.py`** (793 satır, 25× `except Exception`): 2026-07-20'de gözden geçirildi. Yukarıdaki tablodaki dosyaların aksine bu dosya çok-domainli bir god object değil; tek sorumluluğu PyGithub SDK'sını CLI/web katmanı için `(bool, mesaj)` sözleşmesine çeviren dar bir adapter'dır. 25 `except Exception` bloğunun tamamı PyGithub/`requests` sınır çağrılarını sarar ve öngörülemeyen SDK istisna tiplerini (rate limit, ağ hatası, branch protection, kimlik doğrulama vb.) güvenli bir hata mesajına çevirir — bu, harici bir API sınırında kasıtlı ve tutarlı bir tasarımdır, biriken bir borç değildir. Belirli exception tiplerine (`GithubException` vb.) körü körüne daraltmak, `requests`/ağ kaynaklı istisnaları kaçırıp regresyona yol açabilir. `tests/unit/managers/test_github_manager.py` (631 satır) bu davranışı zaten kapsıyor. Bu yüzden dosya öncelikli refactor tablosuna eklenmedi; ileride yeniden değerlendirilirse en düşük riskli adım narrow exception tipleri değil, 25 sitede tekrar eden `if not self._repo: return False, ...` guard'ını ve hata-mesajı şablonunu ortak bir decorator/helper'a çıkarmak olurdu.

## Faz planı

1. **Faz 1 — Boundary ve facade:** Her hedef dosya için public API listesi çıkarılır, yeni modül oluşturulur,
   eski import yolu geçici re-export eder.
2. **Faz 2 — Pure helper taşıma:** Yan etkisiz parser/serializer/normalizer fonksiyonları taşınır; direkt
   modül testleri eklenir.
3. **Faz 3 — IO servisleri:** DB, shell, Docker, WebSocket ve LLM yan etkileri adapter/service sınıflarına
   ayrılır; fake fixture'lar bu sınıflara bağlanır.
4. **Faz 4 — Legacy shim azaltma:** Büyük dosyada kalan wrapper/export sayısı takip edilir; route/service
   sahipliği yeni modüllere geçtikçe shim kaldırılır.

## Kabul kriterleri

- Yeni modül public sözleşmesi ve import yolu testle korunur.
- Büyük dosya satır sayısı veya sorumluluk sayısı her fazda azalır; sadece satır taşıma değil domain ayrışması
  hedeflenir.
- Route path, CLI behavior, DB schema ve environment variable isimleri geriye dönük uyumlu kalır.
- Her PR açıklamasında taşınan sorumluluk, korunan legacy yüzey ve çalıştırılan test kapıları listelenir.
