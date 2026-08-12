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
| `web_server.py` | 2630 | Auth/JWT ile webhook HMAC/replay guard `web/security.py`, access-policy eşleme/serileştirme `web/middleware/access_policy.py`, rate-limit `web/middleware/ratelimit.py`, plugin policy `web/plugins/sandbox.py`, request modelleri `web/routes/request_models.py`, ortak prompt/swarm serileştirme `web/routes/serialization.py` ve route domainleri `web/routes/` altında ayrıldı; plugin sandbox policy üretimde fail-closed kalır, ana dosyada legacy monkeypatch/import wrapper azaltımı sürmeli. |
| `run_tests.sh` | 678 | Benchmark, coverage, frontend, service, summary, backend ve BATS uygulamaları `scripts/test_gates/*_helpers.sh` modüllerine çıkarıldı; kök betik stage seçimi, sıralama ve aggregate exit-code facade'ı olarak kaldı. Kalan inline frontend çağrı sıralaması düşük riskli P2 dilimidir. |
| `core/db/monolith.py` | 1340 | Eski `core/db.py` artık `core/db/` paketi; auth/audit/session/user/prompt/metrics/diagnostics/records/dialect/helpers modülleri ayrıldı ve `core/db/__init__.py` geriye dönük uyumlu facade oldu. Kota/budget yazma gövdesi dahil provider usage akışları `metrics.py`, mesaj CRUD `sessions.py` içindedir; schema bootstrap ile access-policy API yüzeyi hâlâ `monolith.py` içinde yoğunlaşıyor. |
| `config.py` | 1754 | Dotenv, logging, secret hardening, runtime path inference, rate-limit/Redis, event bus/Kafka, RAG store ve Docker sandbox loaderları ayrıldı; facade hâlâ çok sayıda class attribute compatibility yüzeyi taşıyor. |
| `install_sidar.sh` | 1849 | CLI argüman parsing `scripts/install_modules/install_cli.sh`, faz dispatcher `scripts/install_modules/install_dispatcher.sh` içine ayrıldı; ana script bootstrap facade olarak daha da inceltilmeli. Son dönemde installer supply-chain sertleştirmesi (SHA-pinli commit, embedded hash manifesti, fail-closed doğrulama) satır sayısını artırdı; bu güvenlik yüzeyi taşınırken davranış korunmalı. |
| `agent/sidar_agent.py` | 1162 | Self-heal planlama ve execute/rollback, autonomy ve federation helperları ayrıldı; facade küçültme tool/subtask sınırıyla sürmeli. |
| `core/rag/__init__.py` | 1581 | Query, metadata, entity graph/extraction, projection ve backend helperları ayrıldı; `DocumentStore` compatibility sınıfının kalan orchestration gövdesi hâlâ bu dosyada. |
| `main.py` | 1241 | Launcher CLI parsing, wizard, process supervision ve session telemetry hâlâ tek facade'da; Doctor preflight orkestrasyonu `core/doctor/launcher_preflight.py` içine ayrıldı. |
| `managers/code_manager.py` | 1377 | Docker SDK lifecycle ve shell sandbox adapterları ayrıldı; facade wrapper azaltımı güvenli şekilde sürdürülebilir. |

## P0 güvenlik backlog'u

### `SEC-PLUGIN-001` — Plugin yürütmesini process/container sınırına taşı

- **Öncelik:** P0 — production güvenlik sınırı; genel refactor maddelerinden önce ele alınır.
- **Durum:** İlk izolasyon dilimi uygulandı; production varsayılanı sürümlü JSON RPC kullanan,
  ephemeral ve fail-closed Docker worker'dır. Marketplace kayıtları host'a plugin sınıfını import
  etmek yerine container tarafında doğrulanan `BaseAgent` proxy'si kaydeder. 2026-08-09'da gerçek
  Docker daemon'ı ve build edilmiş imaj gerektiren container kaçış/integration matrisi eklendi
  (`tests/integration/web/test_plugin_sandbox_container_escape.py`) — kabul kriteri 2, 3 ve 6
  artık argv-mock unit testlerin ötesinde gerçek container'a karşı doğrulanıyor. **Bu matrisin CI'da
  ilk gerçek çalışması, argv-mock testlerin hiç yakalayamadığı kritik bir production bug'ı ortaya
  çıkardı ve aynı PR'da düzeltildi:** `DockerPluginSandboxBackend._command()` `docker run <imaj>
  python -m web.plugins.worker` üretiyordu, ama `Dockerfile`'ın `ENTRYPOINT`'i
  `["/app/.venv/bin/python", "main.py"]` olduğu için bu argv `docker run` tarafından komut
  değişimi değil, `main.py`'ye **eklenen argüman** olarak yorumlanıyordu — RPC worker hiçbir zaman
  gerçekten çalışmıyordu. Mock'lanmış `subprocess.run` ile yazılan unit testler yalnızca üretilen
  argv'yi doğruladığından bu hiç yakalanmamıştı. Düzeltme: `_isolation_argv()`'ye
  `--entrypoint=python` eklendi (zaten doğru olan `managers/code/docker.py` CLI sandbox
  fallback'iyle aynı desen). 2026-08-09'da Docker backend geliştirme/test dahil tüm
  ortamlarda varsayılanlaştırıldı; legacy process-içi backend yalnız
  `SIDAR_PLUGIN_SANDBOX_BACKEND=in_process` ve `SIDAR_ENABLE_IN_PROCESS_PLUGINS=1`
  birlikte verilirse, production dışında açılır.
- **Sahip:** Backend/Güvenlik bakım ekibi.
- **Hedef değerlendirme:** 2026-08-15.
- **Hedef kapanış:** 2026-09-30.
- **Mevcut risk:** AST doğrulaması ve kısıtlı builtins savunma-derinliğidir; işletim sistemi
  seviyesinde güvenlik sınırı değildir. Yalnız iki açık legacy opt-in'i kullanan
  geliştirme/test plugin kodu host process'in bellek, kimlik ve yaşam döngüsü sınırını paylaşır.
- **Hedef mimari:** `web.plugins.sandbox` çağrısını typed request/response sözleşmeli bir
  backend arayüzüne yönlendir; varsayılan production backend'ini `managers/code_manager.py`
  tarafından kullanılan Docker sandbox limitleriyle (ağ kapalı, salt-okunur dosya sistemi,
  CPU/bellek/PID/timeout sınırları, ayrı düşük yetkili kullanıcı) çalıştır. Docker kullanılamıyorsa
  production çağrısı fallback yapmadan reddedilir. Process backend yalnız aynı limitleri işletim
  sistemi düzeyinde uygulayabilen destekli geliştirme ortamlarında seçilebilir.
- **Gerçekleşen geçiş:** (1) sürümlü RPC envelope/backend, (2) ağsız, read-only, capability'siz,
  düşük yetkili kullanıcıyla ve CPU/bellek/PID/timeout limitli container worker, (3) bounded yanıt,
  timeout ve redakte host hataları, (4) marketplace için izole agent proxy'si tamamlandı, (5) gerçek
  imajla çalışan container kaçış/integration matrisi: ağ, dosya sistemi (read-only kök + noexec
  tmpfs), environment/secret sızıntısı, ayrıcalık yükseltme (setuid/privileged port/raw socket),
  pids-limit (fork bomb), OOM fail-closed, timeout fail-closed ve worker hata redaksiyonu gerçek
  `docker run` çağrılarıyla doğrulanıyor; ayrıca memory-swap artık `--memory` ile eşit pinlenerek
  swap üzerinden bellek limiti aşımı kapatıldı (aynı sertleştirme `managers/code/docker.py` CLI
  fallback'i ve `managers/code_manager.py` Docker SDK yoluna da uygulandı). `ci.yml`
  `AUTO_BUILD_DOCKER_TEST_IMAGE=1 DOCKER_TEST_IMAGE=sidar:latest` ile bu matrisi her PR'da
  `sidar:latest` imajına karşı, `release-quality.yml`'deki `docker-smoke` job'u ise
  `SIDAR_PLUGIN_SANDBOX_IMAGE=sidar:${{ github.sha }}` ile gerçek release aday imajına karşı
  çalıştırır (Docker/imaj yoksa modül fail-closed değil skip olur — bu bilinçli bir tercih, zira
  matris yalnızca gerçek altyapı olan ortamlarda anlam taşır).
  RPC yolu artık tek bir `docker run --rm` process deadline'ına bağlı değildir:
  `docker create` → `docker start --attach --interactive` → zorunlu `docker rm --force`
  yaşam döngüsü kullanılır. `SIDAR_PLUGIN_SANDBOX_TIMEOUT` (varsayılan 15 saniye) yalnız
  worker/RPC çalışmasını, `SIDAR_PLUGIN_SANDBOX_CLEANUP_TIMEOUT` (varsayılan 60 saniye)
  ise create/remove daemon işlemlerini sınırlar; geç tamamlanan teardown başarılı bir worker
  yanıtını yanlış biçimde plugin timeout olarak raporlamaz.
  Legacy process-içi backend geriye dönük geliştirme/test uyumluluğu için korunur, ancak artık
  hiçbir ortamın varsayılanı değildir ve iki ayrı açık opt-in gerektirir. Tam kaldırılması ayrı
  bir breaking-change sürümünde değerlendirilecektir.
- **Kabul kriterleri:**
  1. Production plugin yükleme/çalıştırma yolunda host process içinde `compile`/`exec` çağrısı yoktur.
  2. Ağ, dosya sistemi, environment/secret, subprocess ve host process erişim kaçış testleri
     container sınırında reddedilir. ✅ `test_plugin_sandbox_container_escape.py` ile gerçek
     container'a karşı doğrulandı (2026-08-09).
  3. Timeout, OOM, worker crash ve malformed RPC cevapları fail-closed sonuçlanır; worker zorla
     sonlandırılır ve hassas veri loglanmaz. ✅ Timeout/OOM/redaksiyon gerçek container'a karşı
     ayrıca doğrulandı (worker crash/malformed RPC unit contract testlerinde mock ile kalır).
  4. Agent çağrı/yetenek/hata şeması sürümlüdür; uyumsuz plugin host'a import edilmeden reddedilir.
  5. Docker bulunmayan production ortamında yerel subprocess veya process-içi fallback oluşmaz.
  6. Unit sandbox contract testlerine ek olarak container integration ve marketplace smoke testleri
     release kapısında geçer. ✅ `test_isolated_plugin_proxy_executes_successfully_against_the_real_image`
     marketplace proxy akışını gerçek imaja karşı çalıştırır.
- **Bloklayıcı kural:** Yeni plugin özelliği process-içi backend yüzeyini genişletemez. Bu madde
  kapanana kadar yalnız izolasyon geçişi, fail-closed sertleştirmesi ve test değişiklikleri kabul edilir.

## Öncelikli büyük dosyalar

| Dosya | Risk nedeni | Hedef modül sınırı | İlk düşük riskli adım | Test kapısı |
|---|---|---|---|---|
| `web_server.py` | Endpoint, WebSocket, middleware, auth, frontend fallback ve bootstrap tek dosyada yoğunlaşıyor; plugin marketplace içinde AST-validated `exec()` hâlâ process/container sandbox değildir. | `web/routes/ws_chat.py`, `web/routes/ws_voice.py`, `web/routes/collaboration.py`, `web/routes/webhooks.py`, `web/routes/operations.py`, `web/security.py`, `web/plugins/sandbox.py`, `web/app_factory.py`, `web/bootstrap.py`, `web/middleware/cors.py` | App factory boundary'si `web/app_factory.py` içine çıkarıldı; GitHub webhook router çıkarımı yapıldı; `/ws/chat` router factory, `/ws/voice` router factory, HITL router ve WebSocket token parser (`web/security.py`) çıkarımı yapıldı; frontend static mount ve SPA fallback bootstrap boundary'si `web/bootstrap.py` içine çıkarıldı; **middleware/frontend fallback bootstrap boundary** kapsamında loopback CORS middleware bootstrap'ı `web/middleware/cors.py`, access policy middleware orchestration'ı `web/middleware/access_policy.py` modülüne taşındı; aynı sınır saf path-policy eşleme, tenant normalizasyonu ve policy/audit serileştirme helperlarını da barındırıyor; frontend fallback/bootstrap akışı `web/bootstrap.py` modülüne taşındı; plugin AST/policy helperları `web/plugins/sandbox.py` modülüne ve açıkça legacy olarak adlandırılan tek process-içi runtime backend seam'i aynı modüle taşındı; `web_server.py` artık plugin kaynak yürütme ayrıntılarını barındırmak yerine bu seam'e delege ediyor. Production ortamında process-içi plugin exec artık yalnız varsayılan olarak değil koşulsuz fail-closed'dur; `SIDAR_ENABLE_IN_PROCESS_PLUGINS=1` bu sınırı aşamaz. **Sıradaki öncelikli adım P0 `SEC-PLUGIN-001`'dir:** plugin kaynak yürütmesini mevcut `managers/code_manager.py` Docker sandbox sözleşmesiyle uyumlu container/process izolasyonuna tamamen taşımak. Lifecycle/bootstrap refactorları bu güvenlik maddesinin önüne geçmez. **Nüans (bir arkadaş kod incelemesi, `web/routes/plugin_marketplace.py` extraction'ının en yüksek kaldıraçlı devam noktası olarak işaret etti):** `web_server.py:1447-1550` hâlâ 8 ince forwarding fonksiyonu (`_plugin_marketplace_state_path`, `_read_plugin_marketplace_state`, `_write_plugin_marketplace_state`, `_get_plugin_marketplace_entry`, `_serialize_marketplace_plugin`, `_install_marketplace_plugin`, `_uninstall_marketplace_plugin`, `_reload_persisted_marketplace_plugins`) barındırıyor — modülün kendi docstring'i bunun kasıtlı olduğunu, mevcut monkeypatch tabanlı testlerin (`tests/unit/root/test_web_server.py`, 12073 satır, ~26 referans) aynı isimleri gözlemlemeye devam etmesi için bırakıldığını söylüyor. Bu wrapper'lar salt kozmetik değil: `build_agent_router(...)` DI wiring'i (satır ~1974-1990) 4'ünü (`read_plugin_marketplace_state`, `serialize_marketplace_plugin`, `install_marketplace_plugin`, `uninstall_marketplace_plugin`) `lambda: _read_plugin_marketplace_state()` gibi late-bound referanslarla enjekte ediyor, `_reload_persisted_marketplace_plugins` ayrıca boot-time `await asyncio.to_thread(...)` ile (satır 982) çağrılıyor, `_write_plugin_marketplace_state` yalnızca diğer wrapper'ların içinden çağrılıyor — yani üretim yolu hâlâ bu isimlere bağımlı. `_plugin_marketplace_state_path` ve `_get_plugin_marketplace_entry` ise kendi tanımları dışında hiçbir yerden (üretim kodunda) çağrılmıyor — yalnızca test-only yüzey, en düşük riskli silinecek ikili. Doğrulanmış, hazır sıradaki adım: (1) `build_agent_router(...)` çağrısındaki 4 lambda'yı `plugin_marketplace_routes.X` fonksiyonlarına doğrudan (gerekli `catalog`/`agent_registry`/`register_plugin_agent` kwarg'larını threading ederek) yeniden bağlamak, boot-time çağrıyı da aynı şekilde güncellemek, (2) ~26 test monkeypatch hedefini `web_server._X`'ten `web.routes.plugin_marketplace.X`'e taşımak, (3) 8 wrapper'ı silmek. `main.py:874-903`'te de aynı desen (`build_command`/`_launcher_child_env`/`_format_cmd`/`_stream_pipe`/`_run_with_streaming` → `launcher/process.py`, ~20 test referansı) küçük ölçekte tekrarlanıyor. Bu incelemede uygulanmadı: plugin marketplace tarafı, yukarıdaki SEC-PLUGIN-001 önceliklendirmesiyle doğrudan çelişiyor (bu aynı dosyanın process-içi plugin yürütme yüzeyi — lifecycle refactoru güvenlik maddesinin önüne geçemez) ve her iki taraf da büyük/eski test dosyalarında (12073 + 1751 satır) geniş, dikkatli doğrulama gerektiren bir yeniden hedefleme istiyor; küçük-PR/düşük-risk disiplini için tek turda yapılmadı. | `tests/unit/root/test_web_server.py`, `tests/unit/web/*`, plugin marketplace tests, sandbox contract tests, smoke boot tests |
| `run_tests.sh` | Uygulama helperları ayrılmış olsa da stage sıralaması, frontend komut çağrıları ve aggregate exit-code kararı kök shell facade'ında kalıyor. | Mevcut `scripts/test_gates/benchmark_helpers.sh`, `scripts/test_gates/coverage_helpers.sh`, `scripts/test_gates/frontend_helpers.sh`, diğer `*_helpers.sh` modülleri ve `scripts/test_gates/summary.py` | Summary JSON, benchmark, coverage ve frontend yardımcıları çıkarıldı; `run_tests.sh` 678 satıra indi. Sıradaki düşük riskli adım yeni modül icat etmek değil, kökte kalan frontend çağrı sıralamasını mevcut `frontend_helpers.sh` API'sine taşımak ve facade'ı yalnız stage/exit-code koordinasyonunda tutmaktır. | `make production-readiness`, `tests/unit/scripts/*`, shellcheck/BATS gates |
| `install_sidar.sh` | Modüler installer modülleri olmasına rağmen bootstrap, UX, validation ve fallback yüzeyi ana scriptte yoğun kalıyor. | `scripts/install_modules/install_cli.sh`, `scripts/install_modules/install_dispatcher.sh`, `scripts/install_modules/install_runtime.sh`, `scripts/install_modules/bootstrap.sh`, `scripts/install_modules/utils/ux.sh`, `scripts/install_modules/validation.sh`, `scripts/install_modules/offline_bundle.sh` | CLI defaults/argument normalization `install_cli.sh`, sıralı phase dispatcher `install_dispatcher.sh` içine çıkarıldı; ana script bootstrap facade olarak korundu. Post-bootstrap progress/prompt/geçici modül cleanup/log relocation yardımcıları doğrulanmış `install_runtime.sh` modülüne taşındı; servis Docker/health helperları `scripts/install_modules/utils/services_docker.sh`, .env secret hardening helperları `scripts/install_modules/utils/env_secrets.sh` içinde tutuluyor. Sıradaki düşük riskli adım, doğrulanmamış bootstrap modülünü source ederek trust root'u bozmadan, remote module bootstrap ve manifest/hash guard fallbacklerini gömülü veya önceden doğrulanabilir `bootstrap.sh` sınırına taşımak. **Nüans (bir arkadaş kod incelemesi bu bloğu bağımsız olarak ölçüp genişliğini doğruladı):** `EMBEDDED_MODULE_HASHES_MANIFEST` tanımından (satır 596) `bootstrap_clone_and_reexec()`'e (satır 1306) kadar ~710 satırlık tek bir blok — `validate_remote_module_trust_root`, per-modül SHA-256 doğrulama, üstel geri çekilme + `Retry-After` destekli indirme, UID-sahiplik/symlink-reddeden cache ve üçüncü parti script'ler (Ollama/uv/Volta/NVM) için `/dev/tty` TOFU inceleme akışını kapsıyor; bu tam olarak yukarıdaki `bootstrap.sh` hedefinin kapsamı. Reviewer alternatif olarak `scripts/install_modules/utils/remote_module_fetch.sh` önerdi (mevcut `utils/` alt dizini konvansiyonuna uygun); isim seçimi ne olursa olsun asıl zorluk satır sayısı değil, yukarıda not edilen trust-root chicken-and-egg sorunu (kaynak dosyayı doğrulamak için önce kaynak dosyayı source etmek gerekmemeli). Bu turda extraction'ın kendisi yapılmadı — yalnızca plan netleştirildi. | installer smoke, `tests/unit/scripts/*`, shellcheck |
| `main.py` | CLI parsing, launcher wizard, Doctor preflight, process supervision ve session telemetry tek dosyada birleşiyor. | `main/cli.py`, `main/wizard.py`, `main/commands.py`, `main/supervision.py`, `main/session.py`, `core/doctor/launcher_preflight.py` | Launcher Doctor preflight sıralama/skip/parallel execution akışı `core/doctor/launcher_preflight.py` içine taşındı; `main.py` yalnız UI hook'ları, renkler ve env reload/auto-fix callback'lerini enjekte eden facade olarak kaldı. Sıradaki düşük riskli adım CLI parser ve process supervision sınırını aynı compatibility yüzeyiyle ayırmak. | `tests/unit/root/test_web_server.py`, `tests/unit/cli/test_main_helpers.py`, launcher smoke |
| `core/db/monolith.py` (eski `core/db.py`) | Schema, access-policy ve compatibility facade yüzeyi hâlâ tek ~1333 satırlık modülde. | `core/db/auth.py`, `core/db/audit.py`, `core/db/coverage.py`, `core/db/marketing.py`, `core/db/session.py`, ortak `core/db/models.py` | `core/db.py` artık `core/db/` paketi; `auth.py`, `audit.py`, `coverage.py`, `marketing.py`, `session.py`, `sessions.py`, `users.py`, `prompt_registry.py`, `metrics.py` (provider usage, quota/budget ve admin istatistikleri) ve `models.py` akışları çıkarıldı, `audit_log.py` legacy compatibility wrapper olarak bırakıldı. PostgreSQL teşhisleri `core/db/diagnostics.py`, saf zaman/JSON/UUID/SQLite helperları `core/db/helpers.py`, SQL dialect/asyncpg tag helperları `core/db/dialect.py`, domain dataclass kayıtları `core/db/records.py` modüllerine taşındı ve `core/db/__init__.py` legacy re-export facade'ı olarak korundu. 2026-07-20'de ilk read-only query helper adımı atıldı: `list_marketing_campaigns`, `list_content_assets`, `list_operation_checklists` gövdeleri `core/db/marketing.py`'ye taşındı ve `Database` üzerindeki metotlar ince delege wrapper'a indirildi (`core/db/__init__.py`'deki submodule whitelist'ine `marketing` eklendi — aksi halde `core.db` self-aliasing swap'ı sonrası `import core.db.marketing` kırılıyordu). 2026-08-02 itibarıyla `upsert_user_quota` gövdesi de `metrics.py` sınırına taşındı; facade yalnız delege eder. Sıradaki düşük riskli adım SQLite/Alembic schema bootstrap akışını `core/db/schema.py` içine, access-policy sorgularını ise ayrı domain modülüne taşımaktır; mesaj CRUD zaten `sessions.py` içindedir. **Nüans (bir arkadaş kod incelemesi `_init_schema_sqlite()`/`_init_schema_postgresql()` arasındaki drift riskini ayrıca işaret etti):** `_init_schema_sqlite()` (14 `CREATE TABLE`'lık elle yazılmış tek SQL string'i) ile `_init_schema_postgresql()` (Alembic migration'larını çalıştırır) bağımsız, elle bakım gören iki kaynak olduğu için yeni bir Alembic migration'ının SQLite string'ine yansıtılmaması hiçbir testle yakalanmıyordu -- bu risk bu incelemenin erken bir maddesinde zaten kapatıldı: `tests/integration/db/test_db_migrations_integration.py::test_sqlite_bootstrap_schema_matches_alembic_head_schema` iki şemanın tablo/sütun kümesini VE `nullable`/`default` değerlerini karşılaştırıyor (backend-tipi temsil farklarını normalize ederek) ve CI'nın `integration` aşamasında (`run_tests.sh --stage all`) çalışıyor -- yani önerilen (b) seçeneği (karşılaştırma CI kontrolü) zaten uygulanmış durumda; (a) seçeneği (SQLite şemasını doğrudan Alembic'ten üretmek) hâlâ yukarıdaki `core/db/schema.py` adımının kapsamında. | `tests/unit/core/test_db.py`, `tests/integration/db/test_db_migrations_integration.py::test_sqlite_bootstrap_schema_matches_alembic_head_schema` |
| `core/rag/__init__.py` | Embedding, store, query, GraphRAG ve package init davranışları aynı dosyada. | `core/rag/embeddings.py`, `core/rag/store.py`, `core/rag/query.py`, `core/rag/graph.py`, `core/rag/facade.py` | pgvector identifier/diagnostic helperları `core/rag/pgvector_helpers.py`, recursive chunking helperı `core/rag/chunking.py`, GraphRAG entity slug/id/value normalizer helperları `core/rag/entity_helpers.py` içine taşındı ve `__init__` içinde monkeypatch/import uyumlu facade bırakıldı. Arama sonuç formatlayıcıları `core/rag/formatting.py`, GraphRAG metin raporu formatlayıcıları `core/rag/graph_formatting.py`, knowledge graph projection builderları `core/rag/projection.py`, belge/chunk metadata builderları `core/rag/metadata.py`, session belge listeleme/consolidation seçici helperları `core/rag/session_documents.py` içine taşındı. DocumentStore içindeki entity extraction orchestration `core/rag/entity_extraction.py`, entity graph load/save/upsert/delete/search persistence sınırları `core/rag/entity_graph_store.py` içine ayrıldı. Sıradaki düşük riskli adım DocumentStore facade wrapper sayısını azaltıp graph/index orchestration yan etkilerini daha küçük servislerde toplamak. | `tests/unit/core/test_rag.py`, RAG integration tests |
| `config.py` | Env yükleme, secret hardening, GPU detect orkestrasyonu, runtime path inference, logging bootstrap ve çok sayıda backend domain setting'i tek facade içinde yoğunlaşıyor. | `core/config_dotenv.py`, `core/config_dirs.py`, `core/config_gpu_detect.py`, `core/config_logging_setup.py`, `core/config_runtime_env.py`, `core/config_runtime_paths.py`, `core/config_secret_hardening.py`, `core/config_secrets.py`, `core/config_rate_limit.py`, `core/config_event_bus.py`, `core/config_rag_store.py`, `core/config_sandbox.py` | Dotenv parse/load/reload tanılama helperları `core/config_dotenv.py`, logging bootstrap helperları `core/config_logging_setup.py`, secret hardening wrapperları `core/config_secret_hardening.py`, runtime path inference helperları `core/config_runtime_paths.py`, rate-limit/Redis loader'ı `core/config_rate_limit.py`, event bus/Kafka/RabbitMQ loader'ı `core/config_event_bus.py`, RAG store/pgvector loader'ı `core/config_rag_store.py` ve Docker sandbox loader'ı `core/config_sandbox.py` içine çıkarıldı; statik RAG default modülü `config_rag_defaults.py` olarak netleştirildi ve legacy `config_rag.py` yalnız shim olarak bırakıldı. Güncel değerlendirme: `config.py` gerçek bir god object değil; geriye dönük uyum için yaklaşık yirmi domain setting modülünü birleştiren compatibility facade'dır. İlk düşük riskli adım olarak `Config.llm_settings`, `Config.security_settings`, `Config.sandbox_settings` ve benzeri typed domain settings objeleri doğrudan expose edildi; sıradaki adım yeni kodu bu objelere yönlendirip legacy `Config.FOO` class attribute patch sayısını azaltmak. **Nüans:** bir arkadaş kod incelemesinde tespit edildiği üzere, `Config` sınıf gövdesinde tipli domain settings'e delege eden alanlarla (`AI_PROVIDER: str = LLM_SETTINGS.AI_PROVIDER` gibi) hâlâ ham `os.getenv(...)` inline çözümlenen ~35 alan (`TEXT_MODEL`, `GITHUB_*`, `HF_TOKEN`, `DB_DEGRADED_SQLITE_URL`/`DB_SCHEMA_VERSION_TABLE`, `SEARCH_ENGINE`/`TAVILY_API_KEY`/`GOOGLE_SEARCH_*`, `MEMORY_ENCRYPTION_KEY*`, `WEB_HOST`, `REVIEWER_TEST_COMMAND`, `COST_ROUTING_*`, `LORA_*`, `CONTINUOUS_LEARNING_*`, `VOICE_*`/`WHISPER_MODEL`, `BROWSER_PROVIDER`, `PYTHON_LSP_SERVER`/`TYPESCRIPT_LSP_SERVER`, `AUTONOMY_SERVICE_USER_ID`/`AUTONOMY_WEBHOOK_SECRET`, `RAG_LLM_ENTITY_*`, `META_GRAPH_*`/`INSTAGRAM_*`/`FACEBOOK_*`/`WHATSAPP_*`/`SLACK_*`/`JIRA_*`/`TEAMS_WEBHOOK_URL`) yan yana duruyor — bir okuyucu tek tek bakmadan hangi `Config.X` alanının tipli mi ad-hoc mu çözümlendiğini öngöremiyor. Bunların hepsini tek seferde typed settings objelerine taşımak (10+ yeni domain modülü) bu incelemenin diğer maddeleriyle aynı düşük-risk/küçük-PR disiplinine uymadığından yapılmadı; sıradaki düşük riskli adım bu grupları birer `core/config_*.py` domain settings objesine (marketing/social entegrasyonları önce, en izole grup) taşımak, geri kalanını aynı desenle takip eden ayrı PR'lara bölmek. | `tests/unit/root/test_config.py`, boot diagnostics tests |
| `managers/code_manager.py` | Shell execution, Docker sandbox, patching, LSP adapter ve güvenlik kontrolleri tek sınıfta. | `managers/code/runner.py`, `managers/code/docker.py`, `managers/code/docker_lifecycle.py`, `managers/code/shell_sandbox.py`, `managers/code/patcher.py`, `managers/code/lsp.py`, `managers/code/security_adapter.py` | `docker.py`, `docker_lifecycle.py`, `shell_sandbox.py`, `patcher.py`, `security_adapter.py` ve `runner.py` eklendi; `CodeManager` Docker CLI/sandbox limit, Docker SDK lifecycle, shell sandbox, patch, IO güvenlik ve local shell yürütme kararlarını bu helper/adapterlara delege ediyor. LSP install hint, uv/uvx target çözümleme, missing-binary stderr sınıflandırma, result/notification ayrıştırma, location formatlama ve position payload üretimi `managers/code/lsp.py` içine taşındı; facade private wrapperları geriye dönük test/eklenti uyumluluğu için ince delegeler olarak kaldı. Sıradaki düşük riskli adım subprocess LSP lifecycle/initialize sequence gövdesini adapter sınırına taşımaktır. | `tests/unit/managers/test_code_manager.py`, sandbox contract tests |
| `agent/sidar_agent.py` | Ana ajan orchestration, tool execution, self-heal, autonomy ve federation sorumlulukları birleşik. | `agent/tool_registry.py`, `agent/self_heal/planner.py`, `agent/self_heal/executor.py`, `agent/autonomy/service.py`, `agent/federation/service.py` | Deterministik teşhis/policy `core/ci_remediation.py` içinde bırakıldı; snapshot/batch/LLM patch-plan üretimi `agent/self_heal/planner.py`, execute/rollback sınırı `agent/self_heal/executor.py` içine taşındı. `SidarAgent` eski private metotları test/eklenti uyumluluğu için ince delegate wrapper olarak koruyor. Autonomy runtime history helperları `agent/autonomy/service.py`, federation task/action-feedback prompt builderları `agent/federation/service.py` içindedir. Sıradaki düşük riskli adım tool execution registry ve subtask loop adapter sınırlarını ayırmak. | `tests/unit/agent/test_sidar_agent.py`, `tests/unit/agent/self_heal/*`, CI remediation tests |
| `agent/roles/coverage_agent.py` | Coverage parsing, pytest output analysis, missing-test generation ve writer katmanları tek role içinde. | `agent/roles/coverage/analyzer.py`, `agent/roles/coverage/generator.py`, `agent/roles/coverage/writer.py`, `agent/roles/coverage/models.py` | Pure parsing/analyzer fonksiyonlarını yan etkisiz modüle taşıyıp role içinde orchestration bırakmak. | `tests/unit/agent/roles/test_coverage_agent.py`, coverage hotspot tests |
| `core/llm_client.py` | Tüm LLM provider adapter'ları, routing, semantic cache, DLP, retry, tracing ve Ollama stream parsing tek dosyada. | `core/llm/ollama.py`, `core/llm/openai.py`, `core/llm/anthropic.py`, `core/llm/gemini.py`, `core/llm/litellm.py`, compatibility shims under `core/llm/providers/*.py` (starting with `core/llm/providers/ollama.py`), `core/llm/router.py`, `core/llm/streaming.py`, `core/llm/cache.py`, `core/llm/facade.py` | P2 LLM provider adapter modülleri (`core/llm/{openai,anthropic,gemini,ollama,litellm}.py`) çıkarıldı ve public `LLMClient` facade/import boundary'si provider contract testleriyle korunuyor; routing/streaming/semantic cache/facade sorumlulukları `core/llm/{router,streaming,cache,facade}.py` modüllerine ayrıldı: routing adapterı `core/llm/router.py`, streaming helperları `core/llm/streaming.py`, semantic cache adapterı `core/llm/cache.py` ve provider facade contractı `core/llm/facade.py` içine çıkarıldı. Sıradaki düşük riskli adım DLP/retry/tracing wrapperlarını aynı compatibility yüzeyini koruyarak daraltmak. | `tests/unit/core/test_llm_client.py`, provider contract tests |
| `core/doctor/__init__.py` (eski `core/doctor.py`; repo'nun en büyük dosyası, 1943 satır) | Health check, dependency probing, GPU/Redis/DB/RAG doğrulamaları ve orchestration tek facade içinde yoğunlaşıyor. | `core/doctor/checks/database.py`, `core/doctor/checks/gpu.py`, `core/doctor/checks/redis.py`, `core/doctor/checks/rag.py`, `core/doctor/checks/security.py`, `core/doctor/reporting.py`, `core/doctor/models.py`, `core/doctor/facade.py` | Yan etkisiz check result modeli/contract/redaction helperları `core/doctor/models.py`, rapor aggregate/write formatlayıcıları `core/doctor/reporting.py` içine çıkarıldı ve `core.doctor` legacy facade exportları korundu. **Nüans:** `core/doctor/checks/*.py` dosyaları zaten var, ama bir arkadaş kod incelemesinde tespit edildiği üzere gerçek ayrıştırma değil — 5 dosyadaki 10 fonksiyondan 9'u (`database.py`'nin 3'ü, `gpu.py`'nin 2'si, `rag.py`'nin 3'ü, `security.py`'nin 1'i) tek satırlık pass-through (`return _doctor.check_x()`, gerçek gövde hâlâ `__init__.py`'de); yalnızca `redis.py::check_redis` gerçekten kendi kendine yeten, `__init__.py`'de karşılığı olmayan bağımsız bir implementasyon. Sıradaki düşük riskli adım bu 9 fonksiyonun gerçek gövdesini (ve yalnız onların kullandığı private helper'ları) ilgili `checks/*.py` dosyasına taşımak, `__init__.py`'deki orijinalleri `redis.py` deseniyle tutarlı şekilde ince pass-through'a çevirmek — health check orchestration wrapperlarını `core/doctor/facade.py` sınırına daraltmak bundan sonraki adımdır. | `tests/unit/core/test_doctor.py`, CLI doctor smoke tests |
| `agent/roles/reviewer_agent.py` | Review orchestration, judging heuristics, LSP/browser evidence ve raporlama aynı role dosyasında birleşiyor. | `agent/roles/reviewer/analyzer.py`, `agent/roles/reviewer/judge.py`, `agent/roles/reviewer/reporter.py`, `agent/roles/reviewer/evidence.py`, `agent/roles/reviewer/models.py` | Reviewer gate için pure judging/prompt helperları `agent/roles/reviewer/judge.py` modülüne taşındı; role sınıfı compatibility wrapper ve orchestration facade olarak korunuyor. Sıradaki düşük riskli adım evidence/reporter formatlayıcılarını ayrı modüllere almak. | `tests/unit/agent/roles/test_reviewer_agent.py`, reviewer registry tests |
| `core/ci_remediation.py` | CI failure context parsing, remediation payload, patch plan normalize ve validation komut seçimi tek dosyada. Runtime plan üretimi/uygulaması artık burada değildir. | `core/ci_remediation/context.py`, `core/ci_remediation/payload.py`, `core/ci_remediation/plan.py`, `core/ci_remediation/command_safety.py`, `core/ci_remediation/models.py` | `build_local_failure_context` ve validation command normalizer'larını pure modüllere taşıyıp mevcut import yolunu re-export etmek; agent runtime planlamasını yeniden bu policy modülüne eklememek. **Nüans (bir arkadaş kod incelemesi):** `_is_allowed_ruff_command`/`_is_allowed_validation_command` (satır 167-267) genel amaçlı "validation komut seçimi" değil — otonom self-heal döngüsünün hangi shell komutlarını (`pytest`, `uv run ruff check`, `bash run_tests.sh`, `uv pip install`) çalıştırabileceğini belirleyen, shell metakarakterlerini (`&&`/`||`/`;`/`|`/`>`/`<`/`$`) reddeden güvenlik-kritik bir allowlist'tir. Bunu genel bir `validation.py`'ye gömmek yerine ayrı, açıkça isimlendirilmiş `core/ci_remediation/command_safety.py`'ye çıkarmak, otonom kod yürütmeyi kapatan mantığın 1300+ satırlık genel amaçlı bir dosyada gözden kaybolma riskini azaltır ve gelecekteki güvenlik incelemelerinin doğru dosyayı hedeflemesini kolaylaştırır. Hedef modül listesi buna göre güncellendi (`validation.py` → `command_safety.py`); extraction'ın kendisi henüz başlamadı (`core/ci_remediation/` alt paketi yok), bu yalnızca plan güncellemesidir. | `tests/unit/core/test_ci_remediation.py`, auto-heal integration tests |
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
- **`src/components/SwarmFlowPanel.tsx` (435 → ~140 satır):** 14 `useState`, 5
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
