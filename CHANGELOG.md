
# Sürüm Geçmişi (Changelog)

> **Not:** Bu dosya yalnızca sürümler arası farkları, kısa düzeltme notlarını ve teknik borç kapanışı özetlerini içerir. Ayrıntılı çözüm geçmişi `docs/archive/` altında tutulur.

---

## [Unreleased]

### Güvenlik
- **Semantic/dataflow SAST yoktu — ne Python ne JS/TS için:** `.github/workflows/ci.yml`'deki "SAST" adımı yalnızca Bandit (Python-only, AST/pattern tabanlı, fonksiyon/modül sınırları arası taint-tracking yapmayan) + `pip-audit` (bağımlılık zafiyet taraması, SAST değil) çalıştırıyordu; `frontend-security-review.yml` da yalnızca `npm audit` (bağımlılık taraması). JS/TS kaynak kodu için (SQL injection, SSRF, path traversal, XSS, command injection gibi dataflow bulguları) hiçbir statik analiz aracı yoktu. Yeni `.github/workflows/codeql.yml`, Python ve `javascript-typescript` için ayrı CodeQL analiz job'ları çalıştırıyor (push/PR/main + haftalık zamanlanmış tarama), `security-extended` sorgu setiyle (varsayılandan daha geniş dataflow/taint-tracking kapsamı). Bulgular Security sekmesinde code scanning alert'i olarak raporlanır; standart CodeQL dağıtım modeline uygun olarak bulgu başına build'i kırmıyor (triage edilir, kör bir merge engeli olarak kullanılmıyor) — yalnızca gerçek analiz hatasında job fail olur. `docs/CI_REQUIRED_CHECKS.md`/`scripts/ci/verify_required_checks.py` yalnızca `ci.yml`'deki release-critical job'ları hedeflediği için bu ayrı, bilinçli olarak non-required workflow branch protection required-check listesine eklenmedi. README'deki CI kapı listesi güncellendi.
- **`pip-audit` production-readiness kapısı `pyasn1` 0.6.3 üzerindeki CVE-2026-59885/CVE-2026-59886 nedeniyle bloke oluyordu:** `google-genai` extra'sının transitive bağımlılığı olan `google-auth` → `pyasn1-modules` → `pyasn1` zincirinde hiç pin edilmemiş `pyasn1` 0.6.3'e kilitleniyordu; bu sürümde iki yeni CVE vardı ve `security/pip-audit-ignores.tsv`'deki mevcut torch/nltk istisnaları bunları kapsamıyordu (`--all-extras` senkronize edilmeden, örn. yalnızca `--extra dev` ile, `pyasn1` sorunu üretilmiyor — CI paritesi için `uv sync --frozen --all-extras` şart). `pyproject.toml`'a `pyasn1>=0.6.4` floor pin'i eklendi (mevcut `langsmith`/`starlette` transitive-floor desenine uygun), `uv.lock` `pyasn1` 0.6.3→0.6.4'e güncellendi ve `tool.sidar.dependency_inventory.labels`'a `pyasn1 = "runtime"` etiketi eklendi. `torch`/`nltk` istisnaları (sırasıyla 2026-09-15/2026-10-01'e kadar) hâlâ geçerli ve değiştirilmedi.
- **Repo kökünde `.dockerignore` eksikti — secret dosyaları Docker build context'i üzerinden image katmanlarına sızabiliyordu:** `Dockerfile` ve `Dockerfile.production` `COPY . .` kullanıyor; `.gitignore` yalnız git'i etkilediği için `install_sidar.sh` sonrası kökte oluşan `.env` / `.env.production` / `.env.test` gibi dosyalar (rotasyon runbook'unun kapsadığı `API_KEY`, `JWT_SECRET_KEY`, `MEMORY_ENCRYPTION_KEY` vb. 8 secret dahil — bkz. `runbooks/production-cutover-playbook.md` §1.5) `docker build .` çalıştırıldığında build context'e dahil olup image katmanlarına gömülebiliyordu. Kök dizine `.dockerignore` eklendi; `.env*` (örnek dosyalar hariç), `secrets/`, `credentials/`, anahtar/sertifika uzantıları, `.git/`, sanal ortamlar/cache'ler, `node_modules/` ve runtime veri dizinleri (`data/`, `logs/`, `sessions/`, `chroma_db/` vb.) build context'inden çıkarıldı. `web_ui_react/dist` (release-quality CI'da `npm run build` ile üretilip `web_server.py`'nin sunduğu React SPA çıktısı) bilinçli olarak dışarıda bırakılmadı. `docs/AUDIT_REPORT_v5.1_COMPREHENSIVE.md` bu dosyayı zaten "✅" olarak listeliyordu ancak arşivlenmiş/güncel-olmayan bir snapshot olduğu için gerçek durumu yansıtmıyordu — gerçek kontrol reponun kökünde dosyanın **bulunmadığını** doğruladı.
- **"`core/router.py`/`core/rag/backends/pgvector.py`'deki `# nosec B608` kullanımı GÜVENLİ" incelemesi doğrulandı:** İki dosyadaki f-string SQL'lerde interpolasyona giren her tablo/sütun adının çağrı noktasında `core.db.dialect`'in (canonical implementasyon: `core/db_components/dialect.py`) `assert_safe_sql_identifier`/`is_safe_sql_identifier` fonksiyonlarıyla (regex: `^[A-Za-z_][A-Za-z0-9_]*$`) doğrulandığı, gerçek veri değerlerinin her zaman bind-parameter olarak geçtiği ve `tests/unit/test_bandit_comments.py::test_bandit_does_not_globally_skip_dynamic_sql_check`'in global bir B608 skip'i zaten engellediği teyit edildi (küçük düzeltme: reviewer'ın "merkezi `core/db_components/dialect.py`" ifadesi teknik olarak doğru ama her iki dosya da onu `core.db.dialect` facade'ı üzerinden import ediyor, doğrudan değil). Önerilen ekstra güvence olarak yeni `tests/unit/test_bandit_comments.py::test_router_and_pgvector_nosec_b608_usage_keeps_the_identifier_validator_import` eklendi — `ast` modülüyle (grep değil, alias'lı importları da doğru tanıyabilmek için) bu iki dosyanın hâlâ validator'ı import ettiğini doğruluyor; testin gerçekten yakaladığını (validator import'u olmayan sahte bir dosya kaynağına karşı) manuel doğruladım. Bilinçli olarak yalnızca bu iki dosyaya scope edildi — kalan `# nosec B608` kullanımları (`core/db/monolith.py`, `core/db/prompt_registry.py`, `core/active_learning.py`, `scripts/migrate_sqlite_to_pg.py`) farklı ama meşru güvenli desenler kullanıyor (modül sabiti, hardcoded tablo allowlist'i, enumerate edilmiş bind-parameter adları) — bu incelemenin kapsamı dışında, genel bir "her B608 dosyası dialect import etmeli" testi bunlarda yanlış-pozitif üretirdi. `test_bandit_does_not_globally_skip_dynamic_sql_check`'in docstring'indeki dosya listesine eksik olan `core/active_learning.py` eklendi.
- **`install_sidar.sh`'in log maskeleme allowlist'inde 5 gerçek secret anahtarı eksikti — REDIS_PASSWORD/JIRA_API_TOKEN/META_GRAPH_API_TOKEN kurulum loglarına maskelenmeden yazdırılabiliyordu:** `mask_install_log_stream()`/`sidar_user_api_key_names()` (kullanıcı API key toplama akışı) `SIDAR_INTERNAL_SECRET_ENV_KEYS`/`SIDAR_USER_SECRET_ENV_KEYS`'e dayanıyor — proje kendi geçmişinde tam bu sınıf bir bug yaşamıştı (GITHUB_TOKEN/SLACK_TOKEN/TAVILY_API_KEY/HF_TOKEN/JIRA_TOKEN log maskelemesinden sessizce dışarıda kalmıştı, tek allowlist'e konsolide edilerek düzeltilmişti). Şu an şu 5 dosyada (`.env.example`, `.env.advanced.example`, `.env.production.example`, `.env.test.example`) bu iki dizide yer almayan gerçek secret-şekilli anahtarlar bulundu: `REDIS_PASSWORD`, `JIRA_API_TOKEN`, `META_GRAPH_API_TOKEN` hiç maskelenmiyordu; `SIDAR_AUTONOMY_WEBHOOK_SECRET`/`GOOGLE_API_KEY` yalnızca ilgisiz bir allowlist/catch-all girdisiyle (`AUTONOMY_WEBHOOK_SECRET`, case-insensitive `api_key` deseni) tesadüfi substring çakışmasıyla maskeleniyordu — kasıtlı değil, kırılgan. Beşi de `SIDAR_INTERNAL_SECRET_ENV_KEYS` (`REDIS_PASSWORD`, `SIDAR_AUTONOMY_WEBHOOK_SECRET` — `POSTGRES_PASSWORD`/`AUTONOMY_WEBHOOK_SECRET`'le aynı kategori) veya `SIDAR_USER_SECRET_ENV_KEYS`'e (`JIRA_API_TOKEN`, `META_GRAPH_API_TOKEN`, `GOOGLE_API_KEY` — üçüncü parti entegrasyon secret'ları) eklendi; bunun yalnızca maskeleme + raporlama sayımlarını etkilediğini, interaktif kurulum sihirbazının hangi anahtarları soracağını (ayrı, elle tutulan `API_GROUPS` dizisi) ETKİLEMEDİĞİNİ doğruladım. Düzeltmeden önce/sonra canlı `mask_install_log_stream()` çıktısıyla doğruladım. Önerilen ekstra güvence olarak yeni `tests/unit/scripts/test_run_tests_quality_gate.py::test_env_example_secret_keys_are_all_in_the_install_masking_allowlist` eklendi — tüm 5 `.env*.example` şablonundaki (reviewer yalnızca 2'sini önermişti, 5'inin tümüne genişlettim) her `*_TOKEN`/`*_KEY`/`*_SECRET`/`*_PASSWORD`-şekilli anahtarın birleşik allowlist'te olduğunu doğruluyor; eski koda karşı gerçekten aynı 5 anahtarı yakaladığı doğrulandı. `make check-install-manifests`, `shellcheck install_sidar.sh` ve mevcut secret-array testleri temiz.

### Düzeltmeler (Fixed)
- **`Makefile`'daki `ci-parity` hedefi `TEST_PROFILE=ci` ayarlamıyordu; `dev-full` ile fonksiyonel olarak aynıydı, adı yanıltıcıydı:** `ci-parity` yalnızca `FRONTEND_BUNDLE_BUDGET_LOCAL_FULL=1`'i `dev-full`'a iletiyordu — `TEST_PROFILE` hiç ayarlanmadığından `run_tests.sh` sessizce `local` profiline düşüyordu. Bu kozmetik bir fark değil: `TEST_PROFILE=ci` dalı `BENCHMARK_COMPARE_FAIL` eşiğini `mean:15%` (local varsayılan) yerine `mean:10%`'a sıkılaştırıyor, `RUN_BATS_TESTS`'i `auto` yerine koşulsuz `1` yapıyor, `AUTO_OPEN_ARTIFACTS`'i kapatıyor ve `COVERAGE_FAIL_UNDER_CI`/`_LOCAL` ayrımını etkinleştiriyor — yani `make ci-parity`, %15 tolerans içinde kalan ama gerçek CI'nın %10 eşiğinde fail olacak bir performans regresyonunu **local'de sessizce geçirebiliyordu**, tam da "CI parity" adının vaat ettiğinin tersi. `ci-parity` artık `TEST_PROFILE=ci` ve (bir önceki düzeltmeyle tutarlı) `FRONTEND_E2E_NPM_SCRIPT=test:e2e`'yi `dev-full`'a env değişkeni olarak iletiyor (Make değişken-geçişi değil — `dev-full`'un kendi tarifi bu değişkenleri `$(...)` ile referans almadığından, recursive `make` çağrısının önüne shell env prefix'i olarak eklendi; bu, iki seviyeli process ağacında (make → make → bash run_tests.sh) doğru şekilde miras alındığı ayrıca doğrulandı). `dev-full`'un kendisi bilinçli olarak değiştirilmedi — hâlâ hızlı, local-profilli geliştirici varsayılanı. Yeni `tests/unit/scripts/test_run_tests_quality_gate.py::test_ci_parity_actually_sets_the_ci_test_profile` bu regresyonu (eski tarif üzerinde çalıştırıp) gerçekten yakaladığını doğruladım; `docs/TESTING.md` güncellendi.
- **CI'da yalnızca `test:e2e:smoke` (1 spec) çalışıyordu; `web_ui_react/e2e/`'deki 7 panel-özel Playwright spec'i (`admin-panels`, `agent-manager`, `p2p-dialogue`, `prompt-admin`, `swarm-flow`, `tools-panel`, `voice-panel`) hiçbir otomatik yolda tetiklenmiyordu:** `.github/workflows/ci.yml`'nin `test` job'ı `FRONTEND_E2E_NPM_SCRIPT: "test:e2e:smoke"` kullanıyordu; ne başka bir CI job'ı, ne nightly/weekly/release workflow'u, ne de `make production-readiness` bu 7 spec'i hiç çalıştırmıyordu — `docs/TESTING.md`'nin "yalnız `RUN_FRONTEND_E2E=1` ile tam gate'te tetiklenir" iddiasına rağmen, çünkü `FRONTEND_E2E_NPM_SCRIPT` hiçbir otomatik yolda `test:e2e:smoke` dışına ayarlanmıyordu (`make production-readiness`/`base-quality-gates` dahil). CI'nın `test` job'ı ve `make base-quality-gates`/`production-readiness` artık `FRONTEND_E2E_NPM_SCRIPT=test:e2e` (tüm 8 spec, ~10 test, self-contained mock backend'lerle ~12sn) kullanıyor. Bunu release-blocking bir gate olarak açmadan önce local'de gerçekten çalıştırıp doğruladım; bu, önceden hiç tetiklenmemiş 2 gerçek bug ortaya çıkardı: (1) `voice-panel.spec.js`'in `navigator.mediaDevices = {...}` mikrofon mock'u Chromium'da sessizce no-op oluyordu (getter-only accessor'a düz atama, non-strict init script'te sessizce başarısız olur) — gerçek `getUserMedia` çağrılıp headless ortamda "Requested device not found" ile patlıyordu; `Object.defineProperty` ile düzeltildi (`useVoiceAssistant.test.js`'in zaten kullandığı doğru desen). (2) `useVoiceAssistant.ts`'de mikrofon durdurulduktan (`stop()`) sonra sunucunun `{action:"cancel"}`'a verdiği `voice_interruption` ack'i, mikrofon zaten kapalıyken bile durumu "SİDAR sesi kesildi" olarak sessizce eziyordu — `interrupt()` fonksiyonunun zaten kullandığı "mikrofon aktif değilse idle'a dön" desenine göre düzeltildi. Her iki bug da yalnızca gerçek bir mock backend'e karşı uçtan uca çalışan bu spec'lerle yakalanabilirdi; birim testleri bu entegrasyon yolunu hiç egzersiz etmiyordu. `docs/TESTING.md` gerçek duruma göre güncellendi.
- **CI'da `test_run_tests_summary_uses_phase_specific_backend_statuses` `FRONTEND_E2E_NPM_SCRIPT=test:e2e` ambient env'inden sızıntı yüzünden kırıldı (bu incelemenin bir önceki maddesinin yan etkisi):** `.github/workflows/ci.yml`'nin "Run base quality gates" adımı artık `FRONTEND_E2E_NPM_SCRIPT: "test:e2e"`'yi step-level gerçek bir env değişkeni olarak set ediyor (bir önceki madde); bu değişken adı `uv run pytest` sürecinden test'in kendi `subprocess.run([str(runner)])` çağrısına (açık `env=` verilmediği için) miras kaldı. Test, `write_test_summary_json`'ın `frontend_e2e_script="${FRONTEND_E2E_NPM_SCRIPT:-test:e2e:smoke}"` bash fallback'ini örtük olarak (kendi script'inde hiç set etmeden) sınıyordu — bu, değişkenin process ortamında **tamamen tanımsız** olmasını gerektirir; CI'nın step-level `env:` bloğu onu artık `test:e2e` olarak tanımladığından fallback hiç tetiklenmiyor ve `frontend_e2e_scope` beklenen `smoke` yerine `full` çıkıyor (`AssertionError: assert 'full' == 'smoke'`). Test artık `FRONTEND_E2E_NPM_SCRIPT=test:e2e:smoke`'u kendi runner script'inde açıkça set ediyor — dosyadaki kardeş test `test_frontend_playwright_e2e_retries_once_and_preserves_retry_failure`'ın zaten kullandığı hermetik-env deseniyle tutarlı. Hatayı lokalde `FRONTEND_E2E_NPM_SCRIPT=test:e2e uv run pytest ...` ile yeniden ürettim (düzeltmeden önce fail, sonra geçti) ve tüm dosyanın (207 test) hem sızıntı simülasyonuyla hem simülasyonsuz geçtiğini doğruladım.
- **`benchmark-baseline-keepalive.yml` — anti-eviction "keepalive" workflow'u kurulduğundan beri hiç çalışmıyordu; benchmark baseline cache tek nokta arızasının kendi telafi mekanizması bozuktu:** `.github/workflows/ci.yml`'deki release-blocking `benchmark-compare` job'ı (ve seed job'ları) baseline cache anahtarına `${{ runner.name }}` (self-hosted `[self-hosted, linux, benchmark]` runner'ın adı) ekliyor — bilinçli bir tasarım (bkz. `docs/CI_REQUIRED_CHECKS.md`: farklı donanımda üretilmiş baseline'la karşılaştırmayı önler), ama bu da cache'i tek bir runner kimliğine kilitliyor: cache 7 günlük hareketsizlikle silinir veya runner yeniden adlandırılırsa, `production-readiness` kapısı diff'iyle tamamen ilgisiz her PR'ı fail-closed bloke eder. Bunu önlemek için Pazartesi/Perşembe çalışan `benchmark-baseline-keepalive.yml` eklenmişti — ama `ubuntu-latest` üzerinde çalışıyordu ve cache anahtarında `${{ runner.name }}` hiç yoktu, bu yüzden gerçek baseline cache'ini (anahtarı `${{ runner.name }}` içeren) asla bulamıyordu. Workflow'un gerçek GitHub Actions'taki iki çalıştırması da (`2026-08-03`, `2026-08-06`) "Cache not found" ile fail oldu — yani telafi mekanizması hiçbir zaman çalışmamış, sessizce. `benchmark-baseline-keepalive.yml` artık `[self-hosted, linux, benchmark]` runner'ında çalışıyor ve `benchmark-compare`/seed job'larıyla birebir aynı cache key formatını kullanıyor. Yeni `tests/unit/scripts/test_run_tests_quality_gate.py::test_benchmark_baseline_cache_key_prefix_is_identical_everywhere` üç workflow dosyasındaki (`ci.yml`, `benchmark-baseline-seed.yml`, `benchmark-baseline-keepalive.yml`) tüm cache-key satırlarının aynı `${{ runner.name }}`-scoped prefix'i paylaştığını doğruluyor (bu regresyonu yeniden oluşturursam testin gerçekten yakaladığı manuel doğrulandı) — bu, `docs/CI_REQUIRED_CHECKS.md`'ye eklenen açıklamayla birlikte, arkadaş incelemesinde tespit edilen "cache eviction / runner rename → ilgisiz PR bile bloklanır" P1 riskinin kısmi telafisi. Runner değişimi/yeniden adlandırma senaryosu hâlâ tasarım gereği reseed gerektiriyor (bilinçli fail-closed politika, gevşetilmedi); asıl kapatılan boşluk, mevcut telafi mekanizmasının (keepalive) fiilen işlevsiz olmasıydı.
- **`core/db/monolith.py`'deki elle yazılmış SQLite bootstrap şeması (14 `CREATE TABLE`) ile PostgreSQL'i yöneten Alembic migration zinciri arasında otomatik senkron kontrolü yoktu:** `_init_schema_sqlite()` (local/degraded-mode kurulumlar) ve `migrations/versions/*.py` (PostgreSQL'in tek doğruluk kaynağı) bağımsız, elle bakım gören iki kaynak; aralarında hiçbir CI kontrolü olmadığı için `0004_faz_e_tables`'ın PostgreSQL `server_default`'ları sessizce sapmıştı: `marketing_campaigns.channel`/`objective` Postgres'te hiç default'suzdu, `owner_user_id` Postgres'te `'system'` iken SQLite/uygulama kodunda (`core/db/marketing.py`) hep `''`; `operation_checklists.status` `'open'` vs `'pending'`; `coverage_tasks.status`/`requester_role` `'queued'`/default'suz vs `'pending_review'`/`'coverage'`; `coverage_findings.severity` `'info'` vs `'medium'` (`core/db/coverage.py`). Uygulama kodu bu sütunlar için INSERT'lerde her zaman açık değer verdiğinden gözlemlenen bir çalışma zamanı etkisi yoktu, ama herhangi bir ham INSERT (backfill, manuel düzeltme, yeni kod yolu) SQLite/PostgreSQL arasında sessizce farklı davranırdı. Ayrıca hand-rolled DDL'deki `TEXT PRIMARY KEY` sütunları (`users.id`, `auth_tokens.token`, `user_quotas.user_id`, `sessions.id`, `schema_versions.version`) `NOT NULL` içermiyordu — SQLite'ta `PRIMARY KEY` tek başına `NOT NULL` anlamına gelmez ve UNIQUE/PK indeksi iki NULL'u çakışma saymadığından bu, NULL id'li birden fazla satırın eklenebilmesine izin veriyordu. Yeni `migrations/versions/0007_faz_e_defaults_parity.py` dokuz PostgreSQL `server_default`'unu uygulama kodunun zaten kullandığı gerçek değerlere hizaladı (`op.batch_alter_table` ile, SQLite'ta da çalışacak şekilde); `_init_schema_sqlite()`/`_ensure_schema_version_sqlite()`/`_ensure_schema_version_postgresql()`'daki tüm PRIMARY KEY sütunlarına açık `NOT NULL` eklendi. `tests/integration/db/test_db_migrations_integration.py::test_sqlite_bootstrap_schema_matches_alembic_head_schema` artık yalnızca tablo/sütun *adı* kümesini değil, `nullable` ve `default` değerlerini de karşılaştırıyor (backend-tipi temsil farklarını — örn. Boolean'ın SQLite'ta `0`/`1`, Postgres'te `false`/`true` render edilmesi — normalize ederek) ve gelecekteki her sapmayı CI'da fail-closed yakalayacak; `tests/unit/migrations/versions/test_0007_faz_e_defaults_parity.py` yeni migration'ı kapsıyor. `scripts/sync_packaged_migrations.py` ile `sidar_assets/migrations/` senkronlandı.
- **Frontend ESLint kapsamı `.js`/`.jsx` ile sınırlıydı; 22 production `.tsx` dosyası (a11y kuralları dahil) hiç lint edilmiyordu:** `web_ui_react/eslint.config.js`'deki tek kural bloğu yalnızca `src/**/*.{js,jsx}` glob'unu hedefliyordu ve `package.json`'daki `lint` script'i `eslint src --ext .js,.jsx` çalıştırıyordu; ne flat config ne de CLI, `App.tsx`, `ChatWindow.tsx`, `AgentManagerPanel.tsx` gibi kademeli TypeScript göçünün (bkz. `docs/development/frontend-typescript-migration.md`) ürettiği `.ts`/`.tsx` dosyalarını hiç görmüyordu — `jsx-a11y` dahil hiçbir kural bu dosyalara uygulanmıyordu ve bu boşluğu `npm run typecheck` (tip denetimi, lint değil) de kapatmıyordu. `typescript-eslint` (parser + `recommended` kural seti, type-aware olmayan) eklendi; yeni bir `src/**/*.{ts,tsx}` bloğu js/jsx tarafıyla aynı `react`/`react-hooks`/`jsx-a11y` kural setini paylaşıyor (ortak `reactAndA11yRules`/`reactAndA11yPlugins` sabitlerine çıkarıldı, iki dilimin sessizce birbirinden ayrışmasını — ki bu bulgunun asıl nedeniydi — önlemek için). `lint` script'i `--ext .js,.jsx,.ts,.tsx` olarak güncellendi. Genişletilmiş kapsamı ilk çalıştırma `src/lib/rehypeSidarHighlight.ts`'te tek bir gerçek `@typescript-eslint/no-unused-vars` bulgusu çıkardı (kullanılmayan `HastNode`/`HastText` tür tanımları); ikisi de kaldırıldı. Type-aware (`recommended-type-checked`) set bilinçli olarak açılmadı — `tsconfig.json`'da `checkJs=false` ve proje kademeli göç sürecinde; ayrı bir `parserOptions.project` kurulumu gerektirir ve sonraki bir adım olarak bırakıldı. `npm run lint`/`npm run typecheck` artık temiz ve tüm Vitest paketi (533 test) yeşil.
- **`config.py` importu (dolayısıyla `main.py`, `web_server.py`, `scripts/seed_rag.py`, `tests/smoke/*` dahil hemen her giriş noktası) taze bir kurulumda `OLLAMA_CODING_NUM_CTX` için `pydantic_core.ValidationError: int_parsing` ile çöküyordu:** Env-parity kapatma çalışmasında (`cef1a88`) `.env.advanced.example`'a eklenen `OLLAMA_CODING_NUM_CTX=` satırı bilinçli olarak boş bırakılmıştı — amaç, `Config._autoselect_ollama_coding_ctx_window()`'ın kurulum sırasında tespit edilen GPU VRAM'ine göre değeri otomatik ayarlayabilmesiydi. `install_sidar.sh` bu şablonu `.env.advanced` olarak kopyalayınca ve `config.py`'nin dotenv zinciri (`.env` → `.env.advanced`, `override=False`) bu boş değeri `os.environ`'a yazınca, `config_llm.LLMClientSettings` (pydantic-settings `BaseSettings`) boş string'i `int` alanı için varsayılana düşmek yerine doğrudan reddediyordu — `config.py` içindeki kardeş `get_int_env()` yardımcısının (boş string'i "tanımsız" sayıp varsayılana dönen) davranışıyla tutarsızdı. `LLMClientSettings.model_config`'e `env_ignore_empty=True` eklendi (hem statik sınıfta hem `load_llm_settings()`'in dinamik scoped alt sınıfında), böylece boş env değerleri artık field varsayılanına düşüyor. Ayrıca `_autoselect_ollama_coding_ctx_window()`'daki `os.getenv(...) is not None` kontrolü de aynı sınıf hatayı taşıyordu — boş string `None` olmadığı için "açıkça override edilmiş" sayılıp otomatik ayar hiç tetiklenmiyordu; kontrol artık boş/whitespace-only değerleri de "ayarlanmamış" kabul ediyor, gerçek (boş olmayan) override'lar hâlâ önceliğini koruyor. `tests/unit/root/test_config.py`'a hem gerçek kurulum senaryosunu (`.env`+`.env.advanced` zincirinden `os.environ`'a boş değer yükleyip `LLMClientSettings`/`load_llm_settings` çağırma) hem de auto-tune davranışını (boş değerde VRAM'e göre otomatik ayar, dolu değerde override'ın kazanması) doğrulayan regresyon testleri eklendi.
- **RAG Doctor kontrolleri, bileşenlerden türetilen güvenli PostgreSQL DSN'ini görmezden gelerek yanlış `database_env` blokajı üretiyordu:** `check_database_env()` ve PostgreSQL bağlantı kontrolleri, açık `DATABASE_URL` bulunmadığında `POSTGRES_USER`/`POSTGRES_PASSWORD`/`POSTGRES_DB` bileşenlerinden DSN üreten ortak `_resolved_database_urls()` sözleşmesini kullanırken `_rag_readiness_state()` ile geriye dönük aggregate `check_rag_readiness()` ham `os.getenv("DATABASE_URL")` okuyordu. Installer'ın kasıtlı tek-kaynak yapılandırmasında bu nedenle `database_env=pass` ve çalışan pgvector probuna rağmen RAG kontrolleri `blocked_by=database_env` raporluyordu. Her iki RAG yolu artık ortak çözücüyü kullanıyor; aggregate parola karşılaştırması URL-encode edilmiş parolaları da parse edip karşılaştırıyor. `tests/unit/core/test_doctor.py` yalnızca `POSTGRES_*` bileşenlerinin ayarlandığı pgvector regresyonunu hem state hem aggregate kontrolde koruyor.
- **P2 süreç güvenliği somut kapılara bağlandı:** Installer'ın en riskli `06_services.sh` ve `08_env.sh` fazları için doğrudan BATS senaryoları eklendi; Docker daemon retry/fail-closed, PostgreSQL volume reset güvenlik freni, production secret izolasyonu ve GPU env propagation davranışları test ediliyor. Self-hosted GPU CI tek nokta arızası için iki online runner kapasitesini saatlik denetleyen watchdog, primary/warm-standby runbook'u ve failover tatbikatı eklendi. Frontend TypeScript kampanyası ise yalnız nihai tarih yerine 45/15, 30/30, 12/48 ve 0/60 untyped/typed ara hedeflerine bağlandı; inventory checker hedef tarih geldiğinde otomatik fail-closed çalışıyor.
- **LLM/RAG VRAM bütçesindeki %80–%100 gri bölge sessizce kabul ediliyordu:** Ortak `normalize_gpu_memory_fractions()` politikası daha önce yalnız toplam `1.0`'ı aştığında güvenli `0.8` hedefine ölçekliyordu; bu nedenle geliştirme profilindeki eski `0.6 + 0.3 = 0.9` bütçesi hedefi aşmasına rağmen etkin kalıyordu. Normalizasyon artık toplam `0.8` hedefini geçtiği anda oranları koruyarak uygulanıyor; Doctor etkin değerleri raporluyor ve açık uyarı üretiyor. `.env.development.example` ve `.env.advanced.example` başlangıç değerleri de `0.53 + 0.27 = 0.8` olarak güvenli hedefe hizalandı; böylece yeni kurulumlar davranış değiştiren runtime normalizasyonuna veya gereksiz Doctor uyarısına ihtiyaç duymuyor. README ayrıca üst shell'den miras kalan `DATABASE_URL` değerinin neden dosya tabanlı `doctor --fix` ile değiştirilemediğini ve doğru `unset`/yeniden başlatma akışını belgeliyor. Aktif mimari/operasyon belgeleri v5.2.0 runtime baseline'ına hizalandı; v5.0/v5.1 adlı raporların tarihsel vizyon/faz kayıtları olduğu netleştirildi.

- **Self-heal planlama sınırı ayrıştırıldı:** `core/ci_remediation.py` deterministik CI teşhis/policy ve güvenli plan normalizasyonunun sahibi olarak bırakıldı; kaynak snapshot toplama, autonomous batch çözümleme ve LLM patch-plan retry/timeout akışı yeni `agent/self_heal/planner.py` modülüne taşındı. `SidarAgent` geriye dönük private API/monkeypatch uyumluluğu için yalnız ince delegate metotları koruyor; patch uygulama/validation/rollback ise `agent/self_heal/executor.py` sınırında kalıyor. Büyük dosya snapshot'ı da gerçek v5.2.0 modülerleşme durumuyla güncellendi: web auth/rate-limit/plugin/route ve config domain loader ayrımları zaten uygulanmış, RAG tarafında kalan ana borç `DocumentStore` orchestration gövdesidir.
- **`core.doctor`'daki `websocket_routes` kontrolü gerçek FastAPI kurulumunda her zaman `fail` veriyordu:** Kurulu FastAPI sürümü (`>=0.136.1,<0.140.0`, çözülen: `0.139.2`) `include_router()` çağrısını artık eskisi gibi `app.routes`'a düzleştirmiyor; alt router'ı `original_router` özniteliğiyle saran bir `_IncludedRouter` düğümüne sarıyor. `check_websocket_routes()` yalnızca `app.routes`'u sığ olarak tarıyordu, bu yüzden gerçek `/ws/chat`/`/ws/voice` route'ları (asıl HTTP/WS dispatch'i bozulmadan çalışmaya devam etse de) hiç bulunamıyor ve `websocket_paths: []` ile `fail` dönüyordu — kurulum sonunda "🚨 RELEASE / MERGE ONAYI VERMEYİN" uyarısına katkıda bulunan yanlış-pozitif bir sinyaldi. Testler bunu yakalayamamıştı çünkü `tests/unit/core/test_doctor.py` sahte `app` nesnesini elle düzleştirilmiş bir `routes` listesiyle kuruyordu, gerçek FastAPI `_IncludedRouter` şeklini hiç üretmiyordu. Yeni `_iter_effective_routes()` yardımcı fonksiyonu hem `_IncludedRouter.original_router.routes` hem de klasik `Mount`/`APIRouter.routes` şeklini özyinelemeli olarak dolaşıyor; ayrıca import-hatası fallback yolu artık güncel kaynağı (`web/routes/ws_chat.py`/`ws_voice.py` içindeki `@router.websocket(...)`) tarıyor — eski kod `web_server.py` içinde artık var olmayan `@app.websocket(...)` deseni arıyordu. `tests/unit/core/test_doctor.py`'a gerçek `_IncludedRouter` şeklini simüle eden bir regresyon testi eklendi; gerçek `web_server.app` üzerinde manuel doğrulandı (`websocket_paths` artık `['/ws/chat', '/ws/hitl', '/ws/voice']` dönüyor).
- **`core.doctor`'daki `database_connectivity` kontrolü, geçersiz bir `?ssl=disable` DATABASE_URL query parametresini yanlışlıkla TLS sertifika sorunu olarak sınıflandırıyordu:** asyncpg, SQLAlchemy'nin tanımadığı bir `ssl` sorgu değerini (libpq'nun `sslmode=disable` tarzı string'i) PostgreSQL'e bir başlangıç parametresi olarak iletiyor; `ssl` sunucu-taraflı salt-okunur bir GUC olduğundan PostgreSQL bunu `parameter "ssl" cannot be changed now` (`CantChangeRuntimeParamError`) ile reddediyor. Bu hata mesajı "ssl" kelimesini içerdiği için genel TLS/handshake dalına düşüyor ve kullanıcıyı sertifika güveni/proxy sorunlarına yönlendiren yanıltıcı `root_cause_hints` üretiyordu — asıl kök neden ise eski bir kurulumdan kalma, artık hiçbir kod yolunun üretmediği geçersiz bir query parametresiydi. `_postgres_connectivity_failure_guidance()`'a bu imzayı (`cannot be changed now` + `ssl`) genel TLS dalından ÖNCE yakalayan yeni bir `invalid_ssl_query_param` dalı eklendi; mesaj artık gerçek kök nedeni ve mevcut `scripts.sync_database_passwords --remove-explicit-urls` auto-fix'ini doğru işaret ediyor. `tests/unit/core/test_doctor.py`'a regresyon testi eklendi.
- **`core.doctor`'daki `gpu_memory_config` kontrolü, GPU'su olan makinelerde kendisiyle çelişen bir rapor üretiyordu (`"use_gpu": true` + `"gpu_info": "Devre Dışı / CPU Modu"`):** `Config.GPU_INFO`/`GPU_COUNT`/vb. yalnızca `Config._ensure_hardware_info_loaded()` içindeki gerçek donanım probu ile doldurulur; bu prob süreç içinde ilk `Config()` örneklenmesine kadar tembel (lazy) olarak ertelenir. `check_gpu_memory_config()` sınıf özniteliklerini `Config()` hiç oluşturulmadan doğrudan okuyordu; bu fonksiyon kontrol listesinde erken çalıştığından (4.), `USE_GPU` (`.env`'den doğrudan okunan) doğru `true` dönerken `GPU_INFO` hâlâ sabit `"Devre Dışı / CPU Modu"` varsayılanında donmuş kalıyordu. Bu, kullanıcının kendi RTX 3070 Ti kurulumunda gözlemlediği tam çelişkiydi. Kontrol artık alanları okumadan önce `Config._ensure_hardware_info_loaded()`'ı (hataları yutarak, bu bir tanı kontrolünü kilitlenmeye çevirmesin diye) zorluyor. `tests/unit/core/test_doctor.py`'a hem gerçek donanım probu sahteleyen hem de prob hatasını yutma davranışını doğrulayan iki regresyon testi eklendi.
- **`core.doctor`'daki `redis` kontrolü, yalnızca `SIDAR_REDIS_URL` ayarlanmış her kurulumda yanlış "REDIS_URL ayarlanmamış" uyarısı veriyordu:** Gerçek Redis bağlantı çözücüsü (`core/config_rate_limit.py:resolve_redis_url()`) önce `SIDAR_REDIS_URL`'i, ardından geriye dönük uyumluluk için `REDIS_URL` takma adını okur — ki bu tam olarak `install_sidar.sh`'ın kendi ürettiği `.env`'in davranışı (yalnızca `SIDAR_REDIS_URL` yazılır). `core/doctor/checks/redis.py:check_redis()` yalnızca ham `REDIS_URL` ortam değişkenine bakıyordu, bu yüzden Redis fiilen doğru yapılandırılmış ve çalışırken bile her zaman yanlış bir "warn" üretiyordu. Kontrol artık `SIDAR_REDIS_URL`'i önce kontrol ediyor (gerçek çözücüyle aynı öncelik sırası); mesaj metni her iki değişkenin de eksik olduğunu netleştiriyor. `tests/unit/core/doctor/test_checks_modules.py`'a `SIDAR_REDIS_URL`-yalnız senaryosunu doğrulayan regresyon testi eklendi.
- **`core.doctor`'daki `database_env` kontrolü, dosya tabanlı auto-fix'in düzeltemeyeceği bir uyarıyı sonsuza dek tekrarlıyordu ("alarm yorgunluğu"):** Kök neden, arkadaşınızın önerdiği "reload timing" teorisi değil, farklı bir mekanizma çıktı — `tests/unit/core/test_doctor.py::test_database_env_derives_urls_when_missing_but_postgres_password_present` zaten kanıtlıyor ki DATABASE_URL/SIDAR_CONTAINER_DATABASE_URL hiç explicit tanımlı değilken (yalnızca POSTGRES_* parçalarından türetildiğinde) bu uyarı asla oluşamıyor — her ikisi de aynı anda aynı canlı `POSTGRES_DB` değerinden türetiliyor. Gerçek tetikleyici: `DATABASE_URL`/`SIDAR_CONTAINER_DATABASE_URL` process ortamında set ama Sidar'ın kendi dotenv zincirindeki (`.env`, `.env.advanced`, `.env.$SIDAR_ENV`, `DOTENV_FILE`, `SIDAR_KEYS_FILE`) HİÇBİR dosyaya ait değil — örn. eski bir shell `export`'u, ya da `docker-compose.yml`'nin `environment:`/`env_file: .env` ile container'a enjekte ettiği, host `.env`'in POSTGRES_DB'sinden türetilmiş bir DATABASE_URL, `SIDAR_ENV=development` container içinde `.env.development`'ı (farklı POSTGRES_DB ile) override etse bile değişmiyor. `scripts/sync_database_passwords.py --remove-explicit-urls` yalnızca dotenv DOSYALARINI düzenleyebildiği için bu durumda hiçbir şey bulamıyor (`"changed": false`), ve launcher'ın (`main.py`) auto-fix sonrası reload zinciri de yalnızca dotenv'den yüklenen anahtarları yeniden uyguladığından bu "hayalet" değeri asla temizleyemiyor — döngü sonsuza kadar tekrarlanıyor. `core/doctor/__init__.py:check_database_env()` artık `DATABASE_URL`/`SIDAR_CONTAINER_DATABASE_URL`'in Sidar'ın kendi dotenv kaynak raporunda (`_dotenv_source_report`) hiç görünmediği bu durumu tespit edip uyarı mesajına net bir açıklama ekliyor (dosya tabanlı auto-fix'in düzeltemeyeceğini, parent shell/Docker Compose ortamının kontrol edilmesi gerektiğini belirtiyor) ve `database_url_source_unattributed`/`container_database_url_source_unattributed` detay alanlarını ekliyor. `tests/unit/core/test_doctor.py`'a regresyon testi eklendi.
- **Docker sandbox runtime allowlist uyarısı her sandbox çağrısında gereksiz yere tekrarlanıyordu:** `managers/code/docker_lifecycle.py:resolve_runtime()` `DOCKER_RUNTIME` hiç ayarlanmamışken (`runtime == ""`) bile allowlist kontrolüne giriyor, `"" not in DOCKER_ALLOWED_RUNTIMES"` olduğu için (kurulum `.env.advanced`'e `DOCKER_ALLOWED_RUNTIMES=runc,runsc,kata-runtime` yazıyor — boş string dahil değil, ve `core/config_env_helpers.py:get_list_env` zaten CSV'deki boş öğeleri her zaman filtreliyor) her sandbox kod çalıştırmada "Docker runtime '' izinli listede değil" uyarısı basıyordu. Kontrolün fiilen bir uygulama etkisi yoktu: her iki durumda da `""` dönüyor ve `code_manager.py` `runtime` kwarg'ını yalnızca dolu olduğunda set ediyor. `resolve_runtime()` artık allowlist kontrolünü yalnızca `runtime` boş değilken çalıştırıyor; açıkça ayarlanmış ama izinli olmayan bir runtime hâlâ uyarıp varsayılana düşüyor (davranış değişmedi, yalnızca log gürültüsü kalktı). `tests/unit/managers/test_code_manager.py`'ye regresyon testi eklendi.
- **GPU, development kurulumunda sessizce devre dışı kalıyordu:** `scripts/install_modules/phases/08_env.sh` GPU tespit edilince `USE_GPU=true`/`REQUIRE_GPU=true`/`GPU_MIXED_PRECISION=true`/`COMPOSE_PROFILES=gpu` değerlerini yalnızca `.env` dosyasına yazıyordu; `.env.development` (ve `.env.advanced`) `.env.development.example` şablonundan `USE_GPU=false` ile kopyalandığı ve hiç güncellenmediği için, `config.py`'deki dotenv zinciri `SIDAR_ENV=development` (kurulumdaki varsayılan) için `.env.development`'ı `override=True` ile en son yükleyip `.env`'deki GPU ayarını sessizce eziyordu. Ayrıca mevcut bir `.env` üzerinde kurulumu tekrar çalıştırmak GPU bloğunu hiç tetiklemiyordu. Yeni `configure_gpu_env_defaults`/`propagate_gpu_settings_to_env_variants` fonksiyonları GPU ayarlarını hem ilk kurulumda hem yeniden çalıştırmada `.env` ile birlikte `.env.development`/`.env.advanced`'e de yayıyor (`.env.production` kasıtlı olarak hariç — production GPU etkinleştirme gate'i geçmeden manuel kalmalı). `tests/shell/install_sidar_functions.bats` içine regresyon testleri eklendi.
- **`INSTALL_REMOTE_MODULES` fallback indirme listesi `install_cli.sh`/`install_dispatcher.sh` modüllerini atlıyordu:** `install_sidar.sh` yerel repo yokken (örn. `wget install_sidar.sh` + boş dizin) fallback modülleri `INSTALL_REMOTE_MODULES` dizisine göre indiriyor; bu dizi `install_cli.sh` ve `install_dispatcher.sh`'ı içermiyordu (embedded `EMBEDDED_MODULE_HASHES_MANIFEST`'te hash'leri olmasına ve script sonradan bu modülleri `source` etmesine rağmen). Sonuç: bu iki dosya hiç indirilmiyor, ardından hash doğrulama adımı "dosya yok" hatasıyla kurulumu durduruyordu. `install_sidar.sh:511-517` düzeltildi; `tests/shell/install_sidar_remote_modules.bats` içindeki "INSTALL_REMOTE_MODULES covers every module in the embedded hash manifest" testi artık doğrulanıyor.

### Teknik Borç Kapanışı
- **Frontend: 4 admin panelinde load/error/refresh state boilerplate'i tekrarlanmıştı; ortak `useAsyncResource` hook'u yoktu:** `PluginMarketplacePanel.tsx`, `PromptAdminPanel.tsx`, `TenantAdminPanel.tsx`, `OperationsQaPanel.tsx`'in dördü de kendi `[loading, setLoading] = useState(...)` + `[error, setError] = useState("")` çiftini ve `setLoading(true) → setError("") → try/catch/finally` döngüsünü ayrı ayrı tanımlıyordu. Yeni `src/hooks/useAsyncStatus.ts` bu ikili state'i ve `run(action, fallbackMessage?)` sarmalayıcısını tek yerden sağlıyor. Dördü de aynı hook'u kullanmıyor: `PluginMarketplacePanel`/`PromptAdminPanel`/`OperationsQaPanel`'in `loadMarketplace`/`loadPrompts`/`loadHitl` fonksiyonları `run()` sarmalayıcısına taşındı (davranış birebir korundu — OperationsQaPanel'in `loadHitl`'i öncesinde hatayı yalnız başarıdan *sonra* temizliyordu, artık diğer üç panelin konvansiyonuyla tutarlı şekilde çağrı *başlangıcında* temizliyor — kasıtlı, küçük bir tutarlılık iyileştirmesi, davranış regresyonu değil). `TenantAdminPanel`'in `loadTenantData`'sı bilinçli olarak `run()`'a taşınmadı: abort-controller + request-sequencing (race guard) + debounce içeren gerçek, gerekçeli bir kontrol akışı var; yalnızca ham `loading`/`error` state çiftini hook'tan alıyor, kendi akışını koruyor (`useAsyncStatus`'un docstring'i bu ayrımı açıklıyor). Yeni `src/hooks/useAsyncStatus.test.ts` eklendi (%100 kapsam); mevcut 4 panel test dosyası (72 test) ve tüm 8 Playwright e2e spec'i değişmeden geçiyor.
- **Frontend: aynı "hata mesajı çıkar" helper'ı 6 dosyada 3 farklı imzayla kopyalanmıştı:** `AgentManagerPanel.tsx`, `OperationsQaPanel.tsx`, `PluginMarketplacePanel.tsx`, `PromptAdminPanel.tsx`, `TenantAdminPanel.tsx`, `useSwarmFlowController.ts` — hepsi kendi `errorMessage()` fonksiyonunu tanımlıyordu: 3'ü `(error) => error instanceof Error ? error.message : String(error)` (OperationsQaPanel, TenantAdminPanel, useSwarmFlowController), 2'si `(error, fallback) => ... : fallback` (PluginMarketplacePanel, PromptAdminPanel), 1'i sabit Türkçe fallback'li `(error) => ... : "Ajan yüklenemedi"` (AgentManagerPanel) — üç farklı davranış sessizce birbirinden ayrışmıştı. Yeni `src/lib/errors.ts::errorMessage(error, fallback = String(error))` tek imzada üçünü de karşılıyor (fallback verilmezse `String(error)`'a düşer — ilk varyantla birebir; verilirse ikinci/üçüncü varyantla birebir). 6 dosyadaki yerel tanımlar kaldırılıp ortak import'a geçirildi; AgentManagerPanel'in tek çağrı noktası `errorMessage(err, "Ajan yüklenemedi")` olarak güncellendi ki davranış korunsun. Yeni `src/lib/errors.test.ts` eklendi (%100 kapsam). Ayrıca bu incelemenin bir önceki turunda `useVoiceAssistant.ts`'e eklenen `voice_interruption`/mikrofon-aktif-değil dalı için eksik kalan bir birim testi (`stop() sonrası gelen voice_interruption ack'i idle durumunu 'interrupted'a ezmez`) de eklendi — coverage taraması bu dalı işaretlemeseydi fark edilmeyecekti.
- **`config_llm.py`/`config_quality.py` içinde aynı ~15 satırlık "dotenv'e scoped `BaseSettings` alt sınıfı üret" `type(...)` metaprogramlama bloğu birebir kopyalanmıştı:** `load_llm_settings()` ve `load_quality_gate_settings()`, sırasıyla `LLMClientSettings`/`QualityGateSettings`'i belirli bir dotenv dosyasına ("scoped") bağlayan bir `type("ScopedXSettings", (XSettings,), {"__module__": ..., "model_config": SettingsConfigDict(...)})` bloğunu birebir tekrarlıyordu (yalnızca `env_ignore_empty=True` bayrağıyla ayrışıyorlardı — `config_llm.py`'de `OLLAMA_CODING_NUM_CTX` gibi boş-değer-varsayılana-düşsün placeholder'ları için gerekli, `config_quality.py`'de yok). Bu dinamik `type(...)` deseni kasıtlı: pydantic-settings'in `_env_file=...` init kwarg'ı `mypy --strict` altında gevşek tipli olduğu için her çağrı noktasında untyped-call uyarısı üretiyordu (bkz. `test_load_llm_settings_reads_scoped_dotenv_without_dynamic_init_kwargs`), o yüzden basitçe `XSettings(_env_file=env_file)` yerine bu subclass yaklaşımı seçilmişti — ama gerekçe iki dosyada ayrı ayrı yeniden icat edilmiş ve senkronize tutulması gereken bir kopya haline gelmişti. Yeni `core/config_scoped_settings.py::build_scoped_settings_type(settings_cls, *, env_file, env_ignore_empty=False)` bu bloğu tek yere indirdi (üretilen alt sınıfın `__name__`/`__module__`'ü öncekiyle birebir aynı, davranış değişikliği yok); `config_llm.py` ve `config_quality.py` artık bu helper'ı çağırıyor. Yeni `tests/unit/core/test_config_scoped_settings.py` helper'ı izole test ediyor (4 test: dosya okuma, `env_ignore_empty` varsayılanı/açık hali, isimlendirme); `tests/unit/root/test_config.py`'ye eklenen `test_llm_and_quality_gate_loaders_share_the_scoped_settings_builder` iki dosyanın eski inline bloğu yeniden icat etmediğini doğruluyor (eski koda karşı empirik olarak fail ettiği doğrulandı). `docs/module-notes/config.py.md`'ye yeni helper açıklaması eklendi.
- **`agent/self_heal/executor.py` coverage'ı %89.58'de kalmıştı (proje geneli %99.95):** En son eklenen mekanik autofix short-circuit'ının (`execute_mechanical_autofix()`) 4 hata/erken-çıkış dalı test kapsamı dışındaydı: `validation_commands` boşken `blocked` dönüşü (70-72), backup okuma döngüsünde tek dosyanın okunamayıp döngünün devam etmesi (82→80), `scope_paths` verilip hiçbir dosya okunamadığında `blocked` dönüşü (85-90), ve autofix komutunun (doğrulama değil, komutun kendisinin) döngü ortasında başarısız olup `reverted` dönüşü (96-100). Yeni `tests/unit/agent/self_heal/test_executor.py` hafif bir stub `_CodeManagerLike` ile bu 4 dalı hedefliyor (mevcut `tests/integration/workflow/test_self_heal_e2e.py` sandbox stack'i gerektirmeden); `agent/self_heal/executor.py` artık `test_executor.py` + `test_self_heal_e2e.py` + `test_sidar_agent.py` birlikte çalıştırıldığında %100 dal kapsamına ulaşıyor.

### Dokümantasyon
- **`docs/TEST_OPTIMIZATION_PLAN.md`, `pyproject.toml`'da artık bulunmayan `core/vision.py`/`core/voice.py` coverage-omit kayıtlarından bahsediyordu:** İki yerde (satır 38, 80) belge, "coverage artırma işi açmayın" örneği olarak `core/vision.py`/`core/voice.py`'yi `[tool.coverage.run].omit` listesinin üyesi gibi gösteriyordu; ancak `pyproject.toml:516-533`'teki güncel `omit` listesi yalnızca glob desenleri içeriyor (`migrations/*`, `web_ui_react/*`, `tests/*` vb.) ve bu iki dosya orada **değil** — ikisi de `tests/unit/core/test_vision.py`/`test_voice.py` ile tam `%100` gate'ine dahil. Belge, `pyproject.toml`'ın önceki bir sürümünü yansıtan güncel-olmayan bir referans taşıyordu; katkıda bulunanları, aslında kapsanması gereken iki modülü "kapsam dışı" sanıp coverage/regresyon testi eklemekten vazgeçirebilirdi. Her iki satır güncel `omit` glob örnekleriyle düzeltildi. Yeni `tests/unit/scripts/test_run_tests_quality_gate.py::test_test_optimization_plan_omit_examples_match_pyproject_omit_list`, belgedeki her `(örn. ...)` callout'unun her path'inin gerçekten bir `pyproject.toml` `omit` glob'uyla eşleştiğini doğruluyor (eski metne karşı gerçekten fail ettiği ampirik olarak doğrulandı).
- **`INTEGRATION_PYTEST_WORKERS` neden Aşama 1'in `PYTEST_WORKERS=auto`'sundan çok daha düşük bir sabite (2) kilitli olduğu hiçbir yerde açıklanmıyordu:** `scripts/test_gates/coverage_helpers.sh:137`'deki tek satırlık yorum ("sınırlı paralellik") gerekçeyi vermiyordu. Gerçek neden: Aşama 2 (integration/smoke/e2e) testleri CI'da tek, paylaşılan bir PostgreSQL servisine (`DATABASE_URL=.../sidar_test`, worker başına izole değil) bağlanıyor — unit fazının mock/izole state'inin aksine, yüksek paralellik aynı tabloları/satırları paylaşan testler arasında sahte-flaky race condition riski taşıyor (`tests/_fixtures/postgres.py`'deki worker-başına-container `pg_container`/`pg_stress` fixture'ları ayrı, kendi kendine izole bir job'a hizmet ediyor, bu varsayılanla ilgisiz). `coverage_helpers.sh` ve `docs/module-notes/tests.md`'ye gerekçe yorumu eklendi.
- **Coverage ratchet metrik senkronizasyonu:** Release öncesi kalite sözleşmesi güncellendi; ölçülen `%100` günlük local/CI coverage baseline olarak commitlenir, ratchet bu değeri düşürmez ve sonraki `%99.x` regresyonları fail-closed engellenir.
- **Doküman şişkinliği incelemesi (115 markdown dosyası, 4 audit report + 2 mimari raporu + `docs/project-report/` + `PROJE_RAPORU.md`):** Değerlendirme sonucu, "şişkinlik" izlenimi büyük ölçüde zaten kasıtlı ve korunaklı bir arşiv mimarisiyle ele alınmış: `docs/` altındaki 115 dosyanın 77'si `module-notes/` (modül başına bir dosya, kasıtlı desen — bkz. bu incelemenin `config.py.md` maddesi), 6'sı zaten `docs/project-report/`'a bölünmüş (`test_project_report_is_a_small_index_over_topic_sections` bunun yeniden monolitik bir rapora dönüşmediğini zorunlu kılıyor). Dört `AUDIT_REPORT_*.md` dosyasının hepsi "ARŞİV NOTU" banner'ıyla, iki `SIDAR_v5_*_MIMARI_RAPORU.md` dosyası "Belge sınıfı: Tarihsel" banner'ıyla güncel doğruluk kaynağına (`docs/REFACTOR_PLAN.md`/`ARCHITECTURE.md`) yönlendiriyor; bu ayrım `tests/unit/docs/test_architecture_docs.py::test_v52_architecture_is_canonical_and_versioned_reports_are_historical` ile zaten test korumalı. Bu tarihsel snapshot'ları birleştirmek/silmek CHANGELOG'un kendi politikasıyla (ayrıntılı geçmiş `docs/archive/`'de tutulur) çelişir ve P3 önceliği için riski/faydayı haklı çıkarmaz — bu nedenle konsolidasyon yapılmadı. İnceleme sırasında bununla doğrudan ilişkili gerçek bir hata bulundu: **`README.md`'nin depo ağacı diyagramı** `ARCHITECTURE.md`, `PROJE_RAPORU.md`, `project-report/`, `AUDIT_REPORT_v5.0.md`, `TEKNIK_REFERANS.md`'yi kök dizin girdisi gibi listeliyordu — beşi de gerçekte `docs/` altında yaşıyor, kökte hiçbiri yok, ve 115 dosyalık `docs/` dizininin kendisi diyagramda hiç görünmüyordu. "Depo Hijyeni" bölümündeki düz metin referansları da aynı şekilde `docs/` önekini atlıyordu. Diyagram `docs/` altına doğru şekilde iç içe geçirildi (`docs/` artık kendi girdisi, beş dosya onun altında), düz metin referansları `docs/` önekiyle düzeltildi. Yeni `tests/unit/docs/test_architecture_docs.py::test_readme_repo_tree_docs_entries_are_nested_under_docs` bu beş dosyanın diyagramda tekrar kök seviyesine dönmediğini VE gerçekten `docs/` altında var olduğunu doğruluyor (eski diyagrama karşı gerçekten fail ettiği doğrulandı).
- **`main.py`/`cli.py` isimlendirmesi kafa karıştırıcıydı — `main.py` aslında kurulum sihirbazı/launcher, gerçek ajan REPL giriş noktası `cli.py`'dir:** `main.py`'nin kendi docstring'i "Ultimate Launcher" olduğunu açıkça söylüyor (preflight + etkileşimli sihirbaz, sonunda `cli.py`/`web_server.py`'yi alt süreçte başlatır), ama Python'da "main.py" ismi genelde birincil giriş noktası beklentisi yaratır. Daha da kafa karıştırıcısı: `cli.py`'nin kendi docstring'i "Önceden `main.py` olarak adlandırılıyordu" diyor — bu tarihsel taşıma notu, bugün kökte *başka, tamamen farklı* bir `main.py`'nin var olduğunu hiç belirtmiyordu; hızlı okuyan biri "main.py artık yok, cli.py oldu" sonucuna varabilirdi. Dosyaları yeniden adlandırmak (isim takası) `install_sidar.sh`, Docker/Helm/systemd komutları, README/docs örnekleri, kullanıcı alışkanlığı (`python main.py`) ve olası test/CI referansları dahil geniş bir yüzeyi etkileyeceğinden ve P3 önceliği için riski haklı çıkarmadığından (bkz. bu incelemenin `core/doctor` maddesindeki aynı gerekçe) yeniden adlandırma yapılmadı. Bunun yerine her iki dosyanın modül docstring'ine açık çapraz referans eklendi (`main.py`: "Bu dosya ajan REPL'i değildir... Gerçek ajan giriş noktası `cli.py`'dir"; `cli.py`: bugünkü `main.py`'nin bu tarihsel taşımadan bağımsız, sonradan eklenmiş bir launcher olduğunu açıklayan not). Aynı zamanda `docs/module-notes/main.py.md`/`cli.py.md`'deki satır sayıları güncellendi (225→1241, 232→465 — beşte bir ile ikide bir arası büyümüş, eski sayılar anlamsız hale gelmişti) ve `main.py.md`'deki "Web varsayılanları: Host `0.0.0.0`" iddiası düzeltildi — gerçek varsayılan `127.0.0.1` (loopback); `0.0.0.0`, README/CLAUDE.md'deki örnek komutların bilinçli `--host` override'ı, yerleşik varsayılan değil. Yeni `tests/unit/docs/test_architecture_docs.py::test_main_and_cli_docstrings_cross_reference_the_naming_split` her iki dosyanın ve module-notes companion'larının çapraz referansı koruduğunu doğruluyor (eski docstring'lere karşı gerçekten fail ettiği doğrulandı).
- **"Backend mimarisi / `config.py` ve config sprawl" incelemesi (4 alt madde):** (1) *Tutarsız desen* — `Config` sınıf gövdesinde tipli domain settings'e delege eden alanlarla (`AI_PROVIDER: str = LLM_SETTINGS.AI_PROVIDER`) hâlâ ham `os.getenv(...)` inline çözümlenen ~35 alan (GitHub/HF/DB degraded/web search/memory encryption/cost routing/LoRA/continuous learning/voice/LSP/autonomy/RAG entity/marketing-social entegrasyonları) yan yana durduğu doğrulandı — gerçek ve dokümante edilmemiş bir tutarsızlık. Hepsini tek seferde typed settings objelerine taşımak (10+ yeni domain modülü) bu incelemenin küçük-PR/düşük-risk disipliniyle uyuşmadığından yapılmadı; `docs/REFACTOR_PLAN.md`'nin `config.py` satırına somut bir "sıradaki adım" (marketing/social entegrasyonları önce, en izole grup) olarak eklendi, `tests/unit/test_refactor_plan.py`'a bu nüansın belgede kaldığını doğrulayan assertion'lar eklendi. (2) *`config_rag.py` "ölü kod"* — bu incelemenin bir önceki maddesinde (#14) zaten kontrol edilip kasıtlı/test edilen bir geriye dönük uyumluluk shim'i olduğu doğrulanmıştı; tekrar değişiklik yapılmadı. (3) *`config_llm.py`/`config_quality.py` kopyalanmış metaprogramlama* — bu incelemenin bir önceki maddesinde (#15) zaten `core/config_scoped_settings.py::build_scoped_settings_type()`'a çıkarılmıştı; tekrar değişiklik yapılmadı. (4) *"`config_gpu.py` yalnızca saf yeniden-export, kök/core sınırı için yazılı kural yok"* iddiası **doğrulanamadı**: `config_gpu.py` gerçekte `core/config_gpu_detect.py`'den 4 isim re-export ederken kendi `PYTORCH_STABLE_CUDA_WHEEL_TAGS`/`PYTORCH_RECOMMENDED_CUDA_INSTALL_COMMAND` sabitlerini ve gerçek mantık içeren `gpu_mixed_precision_default()` fonksiyonunu da tanımlıyor — "yalnızca" saf re-export değil; ayrıca `docs/module-notes/config.py.md`'de zaten "## Kök/Core yerleşim kuralı" başlıklı, kök vs `core/config_*.py` yerleşimini açıkça tanımlayan yazılı bir kural mevcut (bu PR'dan önce eklenmiş). Bu iki alt-iddia için değişiklik yapılmadı, doğrulama sonucu raporlandı.
- **"`web_server.py` — kısmen tamamlanmış plugin marketplace extraction" incelemesi:** `web/routes/plugin_marketplace.py`'nin gerçek mantığı taşıdığı, `web_server.py:1447-1550`'nin ise mevcut monkeypatch tabanlı testlerin (`tests/unit/root/test_web_server.py`, 12073 satır) aynı isimleri gözlemlemeye devam etmesi için 8 ince forwarding fonksiyonu bilerek bıraktığı doğrulandı; aynı desen `main.py:874-903`'te (`build_command`/`_launcher_child_env`/`_format_cmd`/`_stream_pipe`/`_run_with_streaming` → `launcher/process.py`) küçük ölçekte tekrarlanıyor. İnceleme sırasında wrapper'ların üretim yoluna gerçekten bağlı olduğu doğrulandı — `build_agent_router(...)` DI wiring'i 4'ünü late-bound lambda ile enjekte ediyor, `_reload_persisted_marketplace_plugins` boot-time çağrılıyor; yalnızca `_plugin_marketplace_state_path`/`_get_plugin_marketplace_entry` üretim kodunda hiç çağrılmıyor (test-only yüzey). Bu wrapper'ları silmek — incelemenin önerdiği gibi — `docs/REFACTOR_PLAN.md`'nin `web_server.py` satırında zaten yazılı olan önceliklendirmeyle çelişiyor: **"Sıradaki öncelikli adım P0 `SEC-PLUGIN-001`'dir... Lifecycle/bootstrap refactorları bu güvenlik maddesinin önüne geçmez"** — plugin marketplace tam da bu dosyanın process-içi plugin yürütme yüzeyi. Ayrıca hem `test_web_server.py` (12073 satır) hem `test_main_helpers.py` (1751 satır) üzerinde ~26+20 monkeypatch hedefinin dikkatli yeniden hedeflenmesini gerektiriyor. Bu nedenlerle (proje kendi önceliklendirmesiyle çelişme + büyük/eski test dosyalarında geniş yeniden hedefleme riski) bu turda uygulanmadı; `docs/REFACTOR_PLAN.md`'nin `web_server.py` satırına doğrulanmış, hazır bir sıradaki-adım spesifikasyonu (hangi 4 lambda'nın nereye taşınacağı, hangi 2 wrapper'ın risksiz silinebileceği dahil) eklendi, `tests/unit/test_refactor_plan.py`'a bu nüansın belgede kaldığını doğrulayan assertion'lar eklendi.
- **"`core/db/monolith.py` — SQLite/PostgreSQL şema drift riski" incelemesi:** `_init_schema_sqlite()` (14 `CREATE TABLE`'lık elle yazılmış tek SQL string'i) ile `_init_schema_postgresql()` (Alembic migration'larını çalıştırır) arasında hiçbir otomatik senkron kontrolü olmadığı, yeni bir Alembic migration'ının SQLite string'ine yansıtılmamasının hiçbir testle yakalanamayacağı iddiası doğrulandı — **ama bu risk bu incelemenin erken bir maddesinde zaten kapatılmıştı**: `tests/integration/db/test_db_migrations_integration.py::test_sqlite_bootstrap_schema_matches_alembic_head_schema` (bkz. `migrations/versions/0007_faz_e_defaults_parity.py` maddesi) iki şemanın tablo/sütun kümesini VE `nullable`/`default` değerlerini karşılaştırıyor, CI'nın `integration` aşamasında çalışıyor — önerilen (b) seçeneği (karşılaştırma CI kontrolü) zaten uygulanmış. Yeni değişiklik yapılmadı; `docs/REFACTOR_PLAN.md`'nin `core/db/monolith.py` satırına bu doğrulamayı ve (a) seçeneğinin (SQLite şemasını doğrudan Alembic'ten üretmek) hâlâ mevcut `core/db/schema.py` çıkarım adımının kapsamında olduğunu netleştiren bir nüans eklendi; test kapısı sütunu artık testi adıyla referans veriyor.
- **"`core/doctor/__init__.py` — repo'nun en büyük dosyası, 'sahte' `checks/` alt paketi" incelemesi:** 1943 satır, 16 `check_*` fonksiyonu (toplam 50 fonksiyon) ve `checks/` alt paketinin (`database.py`/`gpu.py`/`rag.py`/`security.py`, 9 fonksiyon) gerçek ayrıştırma değil tek satırlık pass-through olduğu (`return _doctor.check_x()`, gerçek gövde hâlâ `__init__.py`'de; yalnızca `redis.py::check_redis` bağımsız) doğrulandı — **bu bulgu bu incelemenin daha önceki bir turunda (commit `15d1305`) zaten tespit edilip `docs/REFACTOR_PLAN.md`'nin `core/doctor/__init__.py` satırına eklenmişti**: dosya etiketi güncel gerçeği yansıtacak şekilde `core/doctor/__init__.py` (eski `core/doctor.py`) olarak değiştirildi, 9/10 fonksiyonun pass-through olduğu ve `redis.py`'nin istisna olduğu açıkça not edildi, sıradaki adım (gövdeleri taşıyıp `__init__.py`'deki orijinalleri `redis.py` deseniyle ince pass-through'a çevirmek) yazıldı. Yeni kod değişikliği yok; tek eksik olan `tests/unit/test_refactor_plan.py`'da bu spesifik nüans metnini pinleyen bir regresyon assertion'ıydı (önceki turda eklenmemişti) — şimdi eklendi.
- **"`core/ci_remediation.py` — güvenlik-kritik komut allowlist'i genel amaçlı planla iç içe" incelemesi:** 1318 satırlık dosyada `_is_allowed_ruff_command`/`_is_allowed_validation_command` (satır 167-267) doğrulandı — bunlar genel "validation komut seçimi" değil, otonom self-heal döngüsünün hangi shell komutlarını (`pytest`, `uv run ruff check`, `bash run_tests.sh`, `uv pip install`) çalıştırabileceğini belirleyen, shell metakarakterlerini (`&&`/`||`/`;`/`|`/`>`/`<`/`$`) reddeden güvenlik-kritik bir allowlist. `docs/REFACTOR_PLAN.md`'nin `core/ci_remediation.py` satırındaki hedef modül listesi bu ayrımı yapmıyordu — allowlist genel `core/ci_remediation/validation.py` hedefine gömülüydü. Extraction'ın kendisi henüz başlamadığından (alt paket yok) kod değişikliği yapılmadı; hedef, otonom kod yürütmeyi kapatan mantığın gelecekte doğru izole edilmesi ve doğru dosyayı hedefleyen güvenlik incelemelerinin kolaylaşması için açıkça `core/ci_remediation/command_safety.py`'ye güncellendi, gerekçe nüans olarak eklendi. `tests/unit/test_refactor_plan.py`'daki ilgili hedef-modül assertion'ı da `validation.py`'den `command_safety.py`'ye güncellendi, yeni nüans metnini pinleyen assertion'lar eklendi.
- **"`install_sidar.sh` + `scripts/install_modules/` — çift-kaynak hash manifesti ve remote module fetch bloğu" incelemesi (2 alt madde):** (1) *"`.pre-commit-config.yaml` bu kontrolü içermiyor"* iddiası **doğrulanamadı** — bu incelemenin çok daha erken bir turunda (madde #8, "install manifest pre-commit hook'u") zaten aynı sonuçla kapatılmıştı: `.pre-commit-config.yaml`'da `check-install-module-hashes` (`stages: [pre-commit]`, `update_install_module_hash_manifest.py --check-manifest-only` çalıştırır) ve `check-install-module-pin` (`stages: [pre-push]`, `--check` çalıştırır) hook'ları zaten var, ikisi de `install_sidar.sh`/`scripts/install_modules/**`/`scripts/sync_install_module_hashes.sh` değiştiğinde tetikleniyor — yani drift push'tan önce, hatta commit'ten önce yakalanıyor (reviewer'ın önerdiği `scripts/sync_install_module_hashes.sh --check`'in aksine bu script zaten bir `--check` bayrağı desteklemiyor; gerçek kontrol mekanizması farklı bir script). Her iki hook'u da lokalde çalıştırıp temiz geçtiğini doğruladım. (2) *Remote module fetch bloğunun (`validate_remote_module_trust_root`, per-modül SHA-256, üstel geri çekilme, TOFU inceleme akışı) ayrı bir dosyaya çıkarılması* önerisi doğrulandı — blok gerçekten `EMBEDDED_MODULE_HASHES_MANIFEST` (satır 596) ile `bootstrap_clone_and_reexec()` (satır 1306) arası ~710 satır. Ama bu zaten `docs/REFACTOR_PLAN.md`'nin `install_sidar.sh` satırındaki "sıradaki düşük riskli adım" olarak (hedef: `bootstrap.sh`) izleniyordu — extraction'ın kendisi supply-chain trust-root doğrulama mantığını taşıdığından (chicken-and-egg sorunu: kaynak dosyayı doğrulamak için önce onu source etmemek gerekir) bu turda yapılmadı. Plan'a doğrulanmış satır aralığı/boyutu ve reviewer'ın alternatif isim önerisi (`scripts/install_modules/utils/remote_module_fetch.sh`) nüans olarak eklendi, regresyon assertion'ları eklendi.
- **"`run_tests.sh` + `scripts/test_gates/*.sh` — büyük env-var yüzeyi, `--help` yok, yazım hatası koruması yok" incelemesi:** İki iddia ayrı ayrı değerlendirildi. *"`--help` çıktısı yok"* iddiası **doğrulanamadı**: `bash run_tests.sh --help`/`-h` gerçekten var, `--stage` seçeneklerini ve production-readiness komutlarını listeleyen anlamlı bir çıktı üretiyor, `tests/unit/scripts/test_run_tests_quality_gate.py::test_run_tests_help_lists_make_and_direct_production_readiness_commands` ile zaten test korumalı — çalıştırıp doğruladım. *"Bilinmeyen `SIDAR_*`/`BENCHMARK_*`/`COVERAGE_*` değişkenlerini reddeden şema doğrulaması yok"* iddiası **doğru**: `run_tests.sh` tek başına ~61-69, `scripts/test_gates/`'in 10 dosyasıyla (9 `.sh` + `summary.py`, ölçülen 2676 satır — reviewer'ın "2680" tahminine çok yakın) birlikte toplam ~176 farklı env-var adı referanslanıyor, hiçbiri doğrulanmıyor. Bir warn-only, kaynak koddan otomatik türetilmiş allowlist tasarımı denendi (run_tests.sh + test_gates script'lerindeki `${VAR}` referanslarını grep'leyip ortamdaki `SIDAR_*`/`BENCHMARK_*`/`COVERAGE_*` değişkenleriyle karşılaştırma) ama **somut bir false-positive nedeniyle ertelendi**: `SIDAR_ENV` — CI'da her zaman set edilen gerçek bir değişken — `run_tests.sh`/`scripts/test_gates/*.sh`'in hiçbirinde `${SIDAR_ENV}` olarak geçmiyor (çünkü bash orkestrasyonu değil `config.py`/Python runtime tarafından tüketiliyor); kaynak koddan türetilen bir allowlist bunu "olası yazım hatası" diye yanlış işaretlerdi. Bu, `SIDAR_*` gibi önekleri hem run_tests.sh'in kendi knob'ları hem de aynı CI ortamına akan uygulama config'i paylaştığı için doğru bir çözümün run_tests.sh'in kendi kaynağından daha genişini (örn. `config.py`'nin `os.getenv` yüzeyi) kapsaması gerektiğini gösteriyor — bu turun kapsamı dışında, ayrı bir iş kalemi. Kod değişikliği yapılmadı; `docs/TESTING.md`'ye yeni bir "`run_tests.sh` konfigürasyon yüzeyi ve yazım hatası koruması" bölümü eklendi (bilinen sınırlamayı ve denenip reddedilen tasarımı gerekçesiyle belgeliyor), regresyon testi eklendi.
- **"Benchmark gate — tek nokta arıza riski" incelemesi (3 alt madde):** (1) *"`benchmark-baseline-keepalive.yml` muhtemelen çalışmıyor, restore-key formatı `runner.name` eksik"* — **bu incelemenin çok daha erken bir turunda zaten kapatılmıştı** (`benchmark-baseline-keepalive.yml`'nin `runs-on`/cache-key'i düzeltildi, `test_benchmark_baseline_cache_key_prefix_is_identical_everywhere` regresyon testi eklendi); gerçek GitHub Actions çalışma geçmişini tekrar çektim, iki tarihsel çalıştırma da (`2026-08-03`, `2026-08-06` — düzeltmeden önceki ana daldan) `conclusion: failure` gösteriyor, tam olarak beklenen. Yeni değişiklik yapılmadı. (2) *Yalnız restore değil periyodik gerçek re-seed + eksik baseline için proaktif uyarı (issue açma)* önerisi gerçek bir iyileştirme fırsatı ama self-hosted runner yükü/cadence'i ve issue-oluşturma davranışı gibi kararlar gerektiriyor; bu ortamda gerçek `[self-hosted, linux, benchmark]` runner'a karşı doğrulanamayacağından uygulanmadı. (3) *`benchmark-baseline-seed.yml` ve `ci.yml`'in `seed-benchmark-baseline` job'unun neredeyse aynı mantığı iki yerde tuttuğu* doğrulandı — diff'le somutlaştırdım: farklı pinlenmiş action sürümleri (`checkout@v5`/`setup-python@v6`/`setup-uv@v6` vs `@v4`/`@v5`/`@v4`), `ci.yml`'in `install_ci_system_deps.sh` çalıştırıp mevcut cache'i overwrite'tan önce restore etmesi (diğerinde yok), farklı `retention-days` (30 vs 90), farklı artifact adı (dinamik vs sabit `benchmark-baseline-seed`), ve yalnız `benchmark-baseline-seed.yml`'in desteklediği `compare_name`/`benchmark_filter` girdileri. `workflow_call` ile birleştirme doğru yön ama önce bu farkların her biri için kanonik davranış kararı verilmesi ve birleştirilmiş workflow'un gerçek runner'da doğrulanması gerekiyor — bu alan bu incelemede zaten iki gerçek bug'a (madde 1) kaynaklık ettiğinden dokümantasyon turunda rewiring yapılmadı. Her üç madde de `docs/CI_REQUIRED_CHECKS.md`'ye somut, doğrulanmış detaylarla "Known follow-up improvements" olarak eklendi, regresyon testi eklendi.
- **"GPU-gated testler zaten doğru tasarlanmış; `ENABLE_GPU_TESTS=0` override'ı belgelenmemiş" incelemesi:** `ENABLE_GPU_TESTS=auto`'nun yalnızca gerçek GPU donanımı algılanınca açıldığı, `RUN_GPU_STRESS`'in varsayılan kapalı olduğu doğrulandı — bu bir tasarım kusuru değil (GPU'lu bir geliştirme makinesinde `auto → 1` çözülmesi ve tam koşuların ~6dk sürmesi beklenen davranış). README.md zaten bu otomatik algılama davranışını belgeliyordu ama GPU'lu makinede hızlı bir varsayılan geliştirme döngüsü isteyen katkıda bulunanlar için `ENABLE_GPU_TESTS=0 bash run_tests.sh` override'ından (kodda zaten çalışıyor — `scripts/test_gates/coverage_helpers.sh`'te `auto` değerini geçersiz kılıp `nvidia-smi` bulunsa bile GPU testlerini atlıyor) hiçbir yerde bahsetmiyordu. README.md'nin ilgili paragrafına bu override eklendi, regresyon testi eklendi (eski metne karşı gerçekten fail ettiği doğrulandı).
- **"`.github/workflows/` — CodeQL eksik" incelemesi:** Dependabot'un 5 ekosistemi (uv/npm/github-actions/docker/docker-compose) kapsadığı, `branch-protection-audit.yml`'in kendi kendini haftalık denetlediği ve Bandit/npm audit'in semantic/dataflow SAST sağlamadığı doğrulandı — bu incelemenin **madde #3'ünde zaten kapatılmış** aynı bulgu: `.github/workflows/codeql.yml` hem `python` hem `javascript-typescript` için, `security-extended` sorgu setiyle, `push`/`pull_request`/haftalık `schedule` üzerinde çalışıyor — reviewer'ın istediği "frontend-security-review.yml ile aynı kadans" iddiasından bile daha sık (o yalnızca haftalık, PR tetiklemesi yok). Workflow dosya sayısı da (14→15) bu eklemeyle tutarlı. Yeni kod değişikliği yok; ama bu dosyayı doğrulayan hiçbir regresyon testi olmadığı fark edildi (bu incelemenin `core/doctor` maddesinde bulunan aynı boşluk deseni) — `tests/unit/test_github_actions_python_runtime_contract.py::test_codeql_covers_both_languages_with_security_extended_queries` eklendi, dosya geçici olarak kaldırılıp testin gerçekten fail ettiği doğrulandı.
- **"TypeScript migrasyonu — tamamlanmaya çok yakın ama anlatım eski" incelemesi:** Install-log envanterinin (js=9, jsx=20, ts=10, tsx=22) doğru olduğu ve `web_ui_react/typescript-migration-baseline.json`'ın (saf sayısal ratchet dosyası) zaten güncel olduğu doğrulandı. Ama `web_ui_react/tsconfig.json`'ın `checkJs: false` yorumu ("most of the app remains .jsx/.js") ve `docs/development/frontend-typescript-migration.md`'nin "~2974 hata"/"bileşen ağacı" anlatımı ile milestone tablosunun 2027-02-15 satırındaki "Leaf React bileşenleri" teslim odağı **gerçekten eskiydi**: `find src -name "*.js" -o -name "*.jsx"` çıktısının 29 satırının tamamının `*.test.jsx`/`*.test.js`/`src/test/setup.js` olduğu doğrulandı — sıfır untyped uygulama bileşeni kalmamış, kalan kapsam tamamen test dosyaları. `checkJs: true` geçici olarak açılıp `tsc --noEmit` çalıştırıldığında (sonra geri alındı) ~2500 hata görüldü ve **hepsi test dosyalarında**, uygulama kaynağında sıfır hata — "~2974" rakamı da hafifçe eski ama asıl yanlış olan hataların *nerede* olduğu iddiasıydı. `tsconfig.json`'ın yorumu ve migration doc'un ilgili paragrafı + milestone tablosunun 2027-02-15/2027-03-31 satırları güncel duruma (bileşen/hook/lib migrasyonu tamam, kalan iş mekanik test dosyası dönüşümü) göre düzeltildi. Reviewer'ın açık bıraktığı "test dosyası dönüşümünü önceliklendirmeye değer mi" sorusuna yanıt olarak doküma bir öneri eklendi: hayır, ayrı bir sprint olarak değil — production risk taşımadığından milestone tablosundaki tarihli hedefler yeterli, her test dosyası zaten dokunulduğu PR'da fırsatçı biçimde taşınmalı. Yeni `tests/unit/docs/test_architecture_docs.py::test_frontend_typescript_migration_narrative_reflects_component_completion` hem alttaki gerçeği (kalan tüm `.js`/`.jsx` dosyalarının test dosyası olduğunu) hem düzeltilmiş anlatımı pinliyor; eski metne karşı gerçekten fail ettiği doğrulandı.
- **"ESLint kapsam hatası — a11y kuralları fiilen çalışmıyor" incelemesi (P0 olarak işaretlenmişti):** Reviewer'ın somut örneği (`GraphView.jsx`'teki `jsx-a11y/no-noninteractive-element-to-interactive-role` eslint-disable yorumu artık lint glob'unun dışında kalan bir `.tsx` dosyasında) dahil iddia doğrulandı ama **bu tam bulgu, bu PR'ın kendi ilk commit'inde (`caeb0b4`, "fix(frontend): lint .ts/.tsx sources — 22 tsx files were unlinted") zaten kapatılmıştı** — `eslint.config.js`'e `src/**/*.{ts,tsx}` için `typescript-eslint` + paylaşılan `reactAndA11yRules`/`reactAndA11yPlugins` (jsx-a11y dahil) bloğu eklenmiş, `package.json`'daki `lint` script'i `--ext .js,.jsx,.ts,.tsx`'e genişletilmişti. Canlı doğrulama: `npm run lint` temiz geçiyor ve gerçekten `.tsx` dosyalarını tarıyor; `GraphView.tsx:82`'deki a11y disable yorumu artık taranan glob'un içinde. Yeni kod değişikliği yapılmadı; ama bu düzeltmeyi pinleyen bir regresyon testi olmadığı fark edildi (bu incelemenin `core/doctor`/CodeQL maddelerinde bulunan aynı boşluk deseni) — yeni `tests/unit/scripts/test_run_tests_quality_gate.py::test_frontend_eslint_covers_typescript_sources_including_a11y_rules` eklendi; `lint` script'inin `--ext` listesini, `eslint.config.js`'in `.ts/.tsx` glob'unu ve paylaşılan a11y kural setini pinliyor, ayrıca `npm run lint`'i canlı çalıştırıp temiz geçtiğini doğruluyor. Düzeltme-öncesi (`caeb0b4~1`) dosya içerikleriyle test edildi, gerçekten fail ettiği doğrulandı.

---

## [v5.2.0-post2] - 2026-06-20

### Güvenlik
- **GHSA-4xgf-cpjx-pc3j (pydantic-settings 2.14.1):** Bağımlılık `>=2.14.2` taban sınırına çekildi.
  Sidar `secrets_dir`/`secrets_nested_subdir` yüzeyini kullanmıyor; risk teorik, bulgu yine de kapatıldı.
- **GHSA-f4xh-w4cj-qxq8 (langsmith 0.8.5):** Transitive `langsmith` paketine `>=0.8.18` floor eklendi.
  `TracingMiddleware` Sidar'da instance edilmediği için runtime etkisi yok; audit gate temizlendi.

---

## [v5.2.0-post1] - 2026-06-18

> Post-release patch notu: `install_sidar.sh` Ollama/uv kurulum betiği SHA-256 doğrulama akışı için auto-heal davranış düzeltmesi. Paket sürümü `5.2.0` olarak korundu (lock dosyası bütünlüğünü kırmamak için); değişiklik yalnız kurulum/remediation katmanını etkiler.

### Düzeltmeler (Fixed)
- **Auto-heal yanlış sınıflandırması (uzak betik checksum metadata eksikliği):** `install_sidar.sh` Ollama/uv kurulum betiğini SHA-256 olmadan indirmeyi reddettiğinde (`download_verified_script` → `fail`), `scripts/install_modules/utils/install_remediation.sh:283` `*"ollama_install"*` pattern'ine takılıp transient sayıyordu ve auto-heal 3 kez aynı duvara çarpıyordu. Artık `sidar_is_deterministic_failure_signal` ve `sidar_is_remote_script_checksum_missing` checksum-missing kök nedenini deterministik olarak işaretliyor, retry bütçesi 1'e iniyor ve operatöre TOFU yönergesi ile birlikte (`OLLAMA_INSTALL_SHA256` / `UV_INSTALL_SHA256` ve betik URL'i) `remote-script-checksum-missing` raporu yazılıyor.

### İyileştirmeler (Improved)
- **`sidar_emit_remediation_guidance` faz kapsamı genişledi:** Daha önce yalnız `04_workspace` için checksum-missing rehberini basıyordu; artık `03_runtime` (Ollama) dahil tüm fazlarda otomatik tespit ediyor, ilgili betik URL'ini ve değişken adını rehberle birlikte üretiyor.
- **`remote_script_checksum_hint` mesajı netleşti:** Operatöre auto-heal'in retry yapmayacağı, kök nedenin deterministik olduğu ve TOFU akışının nasıl koşulacağı tek adımda gösteriliyor.

### Teknik Borç Kapanışı
- Yeni regresyon testleri: `tests/unit/scripts/test_run_tests_quality_gate.py` içine `test_install_sidar_remote_script_checksum_missing_is_classified_deterministic`, `test_install_sidar_runtime_phase_skips_retry_when_remote_script_checksum_missing`, `test_install_sidar_remote_script_checksum_guidance_covers_runtime_phase`, `test_install_sidar_remote_script_checksum_hint_warns_about_deterministic_wall` eklendi; mevcut transient ollama_install retry akışı (`sudo: timed out`) ve test budgesi (`3/2/1/1/transient`) korunuyor.

---

## [v5.2.0] - 2026-03-26

### Düzeltmeler (Fixed)
- **openai sürüm sınırı:** `openai>=1.68.2` → `openai>=1.68.2,<2.0.0` — üst sınır eksikliği nedeniyle OpenAI SDK v2 kuruluyordu; v2 breaking changes içerdiğinden kırılmaya neden oluyordu.
- **asyncpg çift tanımlama:** `asyncpg` hem `dependencies` hem `postgres` extras içinde tanımlıydı; core `dependencies`'ten kaldırıldı — sadece `postgres` extras'ta kalması gerekir.
- **pgvector çift tanımlama:** `pgvector` hem `dependencies` hem `postgres` extras'ta bulunuyordu; `postgres` extras'tan kaldırıldı.
- **rag extras torch uyumsuzluğu:** `torch~=2.4.1` sabit pin'i kaldırıldı (`torch>=2.4.1` olarak güncellendi); `torchvision~=0.19.1` çıkarıldı — `openai-whisper` ve `sentence-transformers` zaten torch 2.11.x çekiyor, 0.19.1 ile uyumsuzluk yaratıyordu.
- **telemetry extras eski versiyon pinleri:** `opentelemetry-*~=1.29.0` ve `~=0.50b0` pinleri `>=` kısıtlamalarına dönüştürüldü — chromadb'nin çektiği 1.40.0 / 0.61b0 ile çakışma önlendi.

### Teknik Borç Kapanışı
- `requirements.txt` ve `requirements-dev.txt` güncel `pyproject.toml` kısıtlamalarına göre yeniden üretildi (`openai==1.109.1`, v1.x garantili).

---

## [v5.2.0-alpha] - 2026-03-21
Faz E otonom iş ekosistemi ajanları kod tabanına ve üst seviye raporlara resmi olarak işlendi.

### Eklenenler (Added)
- **CoverageAgent entegrasyonu:** `agent/roles/coverage_agent.py` ile otonom pytest analizi, coverage bulgusu kaydı ve eksik test üretim/yazım akışı sisteme eklendi.
- **PoyrazAgent entegrasyonu:** `agent/roles/poyraz_agent.py` ile sosyal medya paylaşımı, landing page oluşturma, WhatsApp entegrasyonu, video içgörüsü ingest'i ve kampanya yönetimi araçları devreye alındı.
- **Faz E rapor senkronizasyonu:** `PROJE_RAPORU.md`, `docs/SIDAR_v5_1_MIMARI_RAPORU.md` ve `AUDIT_REPORT_v5.1.md` Coverage/Poyraz ajanları, güncel repo metrikleri ve `core/db.py` Faz E yardımcılarıyla uyumlu hale getirildi.

### İyileştirmeler (Improved)
- **Mimari anlatı güncellemesi:** Faz E artık yol haritası diliyle değil, aktif ajan davranışları, tool kayıtları ve veritabanı yüzeyleriyle belgeleniyor.

### Teknik Borç Kapanışı
- Coverage ve pazarlama/operasyon otomasyonu artık yalnızca vizyon başlığı altında değil; kod, audit ve mimari raporlar arasında senkronize edilen fiili teslimat olarak izleniyor.

---

## [v5.1.3-alpha] - 2026-03-21
Swarm orkestrasyonu ile Active Learning yüzeyleri, production cutover ve coverage kalite kapıları içinde daha görünür ve hedefli bir regresyon dilimi olarak sabitlendi.

### İyileştirmeler (Improved)
- **CI coverage guard netleştirmesi:** `.github/workflows/ci.yml` içine `tests/test_swarm_orchestrator.py` ve `tests/test_active_learning.py` odaklı ayrı bir regresyon adımı eklenerek, `%99` local/CI ratchet gate ve opt-in `%100` campaign kontrolü öncesinde Swarm + Active Learning omurgasının açık isimli bir kalite kapısından geçmesi sağlandı.
- **Production cutover doğrulama genişlemesi:** `.github/workflows/migration-cutover-checks.yml` artık PostgreSQL migration + pool smoke zincirine ek olarak aynı Swarm + Active Learning dilimini ve workflow guard testini çalıştırarak cutover provasını yalnızca veri katmanı ile sınırlamıyor.

### Teknik Borç Kapanışı
- Coverage/cutover anlatısındaki örtük bağımlılık azaltıldı; Swarm koordinasyonu ile geri bildirim tabanlı öğrenme hattı artık CI ve production rehearsal katmanlarında isimli, testle doğrulanan bir operasyon yüzeyi olarak izleniyor.

---

## [v5.1.2-alpha] - 2026-03-21
Sürekli öğrenme (Continuous Learning) altyapısının temelleri atıldı, Akıllı Başlatıcı (Launcher) validasyonları ve asenkron ajan kilitleri (lock) sertleştirildi.

### Eklenenler (Added)
- **Continuous Learning (v6.0 hazırlığı):** `config.py` içine `ENABLE_CONTINUOUS_LEARNING`, bekleme süreleri, veri seti limitleri ve SFT formatı (`alpaca`) yapılandırmaları eklendi.
- **Port ve tip doğrulaması:** `main.py` içindeki `--port` argümanına tam sayı ve mantıksal aralık (`1-65535`) doğrulama adımları eklendi; kullanıcıya net hata mesajları sunulması sağlandı.

### İyileştirmeler (Improved)
- **Asenkron kilit (lock) yönetimi:** `agent/sidar_agent.py` içindeki `_autonomy_lock` ve `_nightly_maintenance_lock` objeleri, event-loop hatalarını engellemek amacıyla lazy initialization (ihtiyaç anında oluşturma) prensibiyle dokümantasyona işlendi.
- **Güvenli proaktif tetikleme (autonomy history):** Dış sistemlerden (Webhook/Cron) gelen tetiklemelerin `_append_autonomy_history` etrafındaki otonomi akışları thread-safe/autonomy-safe koruma modeliyle belgelerde netleştirildi.

---

## [v5.1.1-docs] - 2026-03-21
Kurumsal raporlar, `main.py` launcher sertleştirmeleri ve %100 coverage baseline'ını koruyan son edge-case test modülü ile yeniden senkronize edildi.

### Eklenenler (Added)
- **%100 coverage kapanışı:** `tests/test_missing_edge_case_coverage_final.py` eklenerek Redis fallback, `WebSocketDisconnect` kaynaklı async cancel, `tempfile.mkdtemp` hata yolu ile GitHub API 400/503 kenar durumları izole mock testleriyle coverage campaign/regresyon kalite kapısı içine alındı.

### İyileştirmeler (Improved)
- **Ultimate Launcher sertleştirmesi:** `main.py` içinde `--port` argümanı için `1-65535` aralık doğrulaması, `validate_runtime_dependencies` kontrolü ve child process stdout/stderr akışını bellek dostu biçimde yazdıran güvenli stream loglama yolu dokümantasyon baseline'ına işlendi.
- **Audit metriği yenilemesi:** `scripts/collect_repo_metrics.sh` ve `scripts/audit_metrics.sh` yeniden çalıştırıldı; yeni baseline **250** takipli Python dosyası / **79.462** Python satırı / **369** toplam takipli dosya olarak raporlara yansıtıldı.

### Teknik Borç Kapanışı
- Son mock tabanlı edge-case kapsamı sayesinde bağımlılık kopmaları, async iptal akışları ve yetkilendirme bypass girişimleri için regresyon boşluğu bırakılmadı; Coverage Agent yol haritası artık bu %100 baseline üzerine kurulacaktır.

---

## [v5.1.0-docs] - 2026-03-21
Faz D kurumsal ölçekleme teslimatları ve Faz E otonom iş ekosistemi vizyonu, güncel audit metrikleriyle birlikte üst seviye belgelere işlendi.

### Eklenenler (Added)
- **Faz D dokümantasyon senkronizasyonu:** `PROJE_RAPORU.md` içine Plugin Marketplace, Multiplayer Collaboration Workspace, Nightly Memory Maintenance ve chaos engineering olgunluğu mevcut durum özeti olarak eklendi.
- **Faz E mimari yönü:** `docs/SIDAR_v5_1_MIMARI_RAPORU.md` sonuna Coverage Agent, Poyraz ve YouTube/dış platform video analizi odaklı yeni mimari başlık eklendi.
- **Audit metriği yenilemesi:** `scripts/audit_metrics.sh` ve `scripts/collect_repo_metrics.sh` çıktıları yeniden alınarak `AUDIT_REPORT_v5.1.md` ile üst seviye raporlardaki satır/dosya sayıları güncellendi; yeni baseline 250 takipli Python dosyası / 79.462 Python satırı / 369 toplam takipli dosya seviyesine taşındı.

### Teknik Borç Kapanışı
- `tests/test_system_health_dependency_checks.py`, `tests/test_plugin_marketplace_hot_reload.py` ve `tests/test_nightly_memory_maintenance.py` ile temsil edilen Faz D yüzeyleri coverage anlatısına açıkça dahil edildi.
- Kaos mühendisliği, eklenti pazaryeri ve bellek bakımı modüllerinin regresyon güvenliği artık changelog ve audit katmanında da görünür durumdadır.
- `TEKNIK_REFERANS.md`, `nightly_memory_loop` temelli vektör optimizasyonu ve bakım politikası için ayrı teknik alt başlıkla güncellendi.
- Helm chart sürüm işaretleri runtime baseline ile hizalanarak `v5.0.0-alpha` çizgisine taşındı.

---

## [v5.0.0-alpha] - 2026-03-19
v5.0 Faz 6 geçişi; çok modlu algı, proaktif otonomi, LSP tabanlı anlamsal denetim ve akıllı başlatıcı yüzeyiyle görünür ürün fazına taşındı.

### Eklenenler (Added)
- **Ultimate Launcher (`main.py`):** Etkileşimli CLI arayüzü, ön kontrol (preflight) mekanizması, `--capture-output`/`--child-log` desteği ve thread tabanlı alt süreç log akışı ile daha güvenli launcher davranışı sağlandı.
- **Launcher Runtime Guard:** `config.py` importu başarısız olduğunda launcher artık `web_server.py` / `cli.py` alt süreçlerini fail-fast koruma ile durdurup kullanıcıya nedenini açıkça bildirir; böylece launcher-fallback ile child-process çökmesi arasındaki tutarsızlık giderildi.
- **Cross-Platform Ollama Cleanup:** `web_server.py` içindeki child-process keşfi artık önce `psutil` kullanıyor, Windows ortamında `ps` komutuna düşmeden güvenli biçimde boş liste döndürüyor; böylece shutdown cleanup hattı POSIX bağımlılığıyla sınırlı kalmıyor.
- **LSP Entegrasyonu:** `managers/code_manager.py` içine Pyright ve TypeScript LSP desteği, yapılandırılmış semantik audit ve güvenli refactor yardımcıları eklendi.
- **Reviewer Agent Yetenekleri:** Reviewer ajanına `lsp_diagnostics` aracı eklenerek anlamsal kod denetimi kalite kapısına bağlandı.
- **Multimodal Medya İşleme:** `core/multimodal.py` ile FFmpeg tabanlı video frame analizi, ses kanalı ayırma ve STT tabanlı medya bağlamı üretimi eklendi.
- **Voice WebSocket Arayüzü:** `web_server.py` üzerinde base64 ses verilerini işleyip LLM bağlamına katan gerçek zamanlı sesli iletişim endpoint'leri açıldı; VAD olayları ve duplex voice state payload'ları testlerle doğrulandı.
- **Duplex Voice-to-Voice Derinleşmesi:** `core/voice.py` ve `/ws/voice` hattına assistant turn kimliği, output buffer durumu, audio sıra numarası ve VAD tabanlı barge-in interrupt temizliği eklendi.
- **Otonom Cron Loop:** SİDAR'ın kendi kendine uyanıp görevleri değerlendirmesini sağlayan `_autonomous_cron_loop` arka plan görevi eklendi.
- **Tarayıcı Otomasyonu:** Playwright öncelikli dinamik web etkileşim katmanı (`managers/browser_manager.py`), yüksek riskli aksiyonlar için audit trail ve HITL korumalarıyla ürünleşti.
- **GraphRAG Etki Analizi:** `core/rag.py` içindeki impact analizi; risk seviyesi, etkilenen endpoint handler'ları ve reviewer hedeflerini üreten daha yönlendirici bir raporlama katmanına genişletildi.
- **Faz C Self-Healing Bootstrap:** `core/ci_remediation.py` ve `agent/sidar_agent.py` artık düşük riskli CI arızaları için LLM tabanlı JSON patch planı üretip patch uygular, sandbox içinde doğrular ve hata halinde otomatik rollback yapar; yüksek riskli akışlar ise HITL beklemeye devam eder.
- **React Duplex Voice Paneli:** `web_ui_react/src/components/VoiceAssistantPanel.jsx` ve `web_ui_react/src/hooks/useVoiceAssistant.js` ile istemci tarafı mikrofon/VAD yönetimi, `MediaRecorder` tabanlı akış, transcript/diagnostics görünürlüğü ve barge-in görsel geri bildirimi React SPA içine entegre edildi.
- **Reviewer → CodeManager Self-Healing Döngüsü:** Reviewer/LSP/GraphRAG sinyalleri ile başlayan remediation akışı, `core/ci_remediation.py`, `agent/sidar_agent.py` ve `managers/code_manager.py` üzerinden güvenli patch planı, sandbox doğrulaması ve rollback fail-safe zinciriyle proaktif onarım davranışına genişletildi.
- **Browser Decisioning Derinleşmesi:** `managers/browser_manager.py` artık Playwright/Selenium oturumlarından screenshot + DOM sinyalleri toplayıp typed browser tool şemaları ve reviewer browser_signals akışı için deterministik selector/HITL odaklı karar verisi üretiyor.
- **Event-Driven Swarm Federation:** `web_server.py`, `github_upload.py`, webhook uçları ve `agent/swarm.py` ile GitHub/Jira/sistem uyarılarından tetiklenen event-driven federation workflow'ları Coder + Reviewer pipeline'ına otomatik dağıtılıyor.
- **Nightly Memory Consolidation (Faz D başlangıcı):** `ConversationMemory`, `DocumentStore`, `SidarAgent` ve `web_server.py` üzerine idle-gated gece döngüsü eklendi; eski oturumlar özetleniyor, düşük değerli RAG dokümanları `memory://nightly-digest` ile konsolide edilip gereksiz embedding'ler temizleniyor, entity memory TTL purge işlemi aynı bakım turunda çalışıyor.

### Teknik Borç Kapanışı
- `core/voice.py`, `web_server.py`, `managers/browser_manager.py`, `main.py`, `core/ci_remediation.py`, `agent/core/contracts.py` ve `core/rag.py` çevresindeki v5.0-alpha test kapsamı `tests/test_voice_pipeline.py`, `tests/test_web_server_voice.py`, `tests/test_browser_manager.py`, `tests/test_main_launcher_improvements.py`, `tests/test_ci_remediation.py`, `tests/test_contracts_federation.py` ve `tests/test_rag_graph.py` ile kapatıldı.
- Böylece belgelerde daha önce izlenen v5.0-alpha coverage/test borcu kapanmış oldu; aktif teknik borç yerine sürdürülen regresyon güvenliği statüsüne geçildi.

---

## [4.3.0] - 2026-03-19
Repo metrikleri, sürüm numaraları ve üst seviye dokümantasyon mevcut takipli kod tabanı ile senkronize edildi.

### ✅ Dokümantasyon ve Sürüm Senkronizasyonu
**Dosyalar:** `config.py`, `pyproject.toml`, `sidar_project.egg-info/PKG-INFO`, `helm/sidar/Chart.yaml`, `README.md`, `PROJE_RAPORU.md`, `AUDIT_REPORT_v5.0.md`, `TEKNIK_REFERANS.md`, `SIDAR.md`, `CLAUDE.md`
- Runtime, paket ve dağıtım yüzeyi `v4.3.0` sürüm çizgisine taşındı; README, teknik referans, proje raporu ve geliştirici rehberleri aynı baseline ile hizalandı.
- Takipli depo ölçümleri yeniden doğrulandı: **58** üretim Python dosyası / **20.582** satır, **151** test dosyası / **39.147** satır, toplam takipli Python **209** dosya / **59.729** satır, Web UI toplamı **6.105** satır ve REST endpoint envanteri **60** olarak raporlara işlendi.
- Teknik referans turunda API/DB/env sözleşmeleri tekrar kontrol edildi; bu sürümde yeni endpoint, tablo veya config anahtarı eklenmediği için envanter korunurken başlık ve senkronizasyon notları güncellendi.

### ✅ Çözülen Bulgular
**Dosyalar:** `scripts/audit_metrics.sh`, `scripts/collect_repo_metrics.sh`, `tests/test_release_version_bump.py`
- Repo metrik betikleri Git deposu içinde öncelikle `git ls-files` kullanacak şekilde düzeltilerek `.venv`, `node_modules` ve benzeri takip dışı içeriklerin satır sayılarını şişirmesi engellendi.
- Sürüm doğrulama testi, yeni `v4.3.0` baseline ve güncel proje raporu/changelog/SIDAR talimatlarıyla uyumlu hale getirildi.

---

### Teknik Borç Kapanışı
- Repo metrik betikleri Git-takipli dosya ölçümüne alınarak rapor şişmesi üreten ölçüm drift'i kapatıldı.
- Sürüm doğrulama testi ve üst seviye dokümantasyon aynı release çizgisine hizalandı.

---

## [4.0.0] - 2026-03-19
Runtime sürümü ve üst seviye proje raporları, v4 kurumsal mimari omurgasıyla senkronize edildi.

### ✅ Sürüm ve Mimari Senkronizasyonu
**Dosyalar:** `config.py`, `pyproject.toml`, `sidar_project.egg-info/PKG-INFO`, `PROJE_RAPORU.md`, `README.md`
- Runtime ve paket sürümleri `3.0.0` / `0.0.0` seviyelerinden `4.0.0` değerine yükseltildi; böylece config, paket metadata'sı ve v4 audit anlatısı aynı sürüm çizgisine taşındı.
- React tabanlı `web_ui_react/` arayüzünün standart kullanıcı deneyimi olduğu, legacy `web_ui/` klasörünün ise geriye dönük uyumluluk/fallback amacıyla korunduğu dokümante edildi.
- SQLite'tan PostgreSQL + `pgvector` altyapısına geçiş, Alembic migration zinciri ve kurumsal deployment yüzeyinin (Docker Compose + Helm/Redis/Jaeger/OTel) proje raporlarında daha açık biçimde özetlenmesi sağlandı.
- Multi-agent swarm mimarisinin Coder/Researcher/Reviewer uzman rolleri, reviewer QA döngüsü ve token/maliyet gözlemlenebilirliğiyle birlikte ana dokümantasyonda öne çıkarılması tamamlandı.

---

### Teknik Borç Kapanışı
- v4 kurumsal mimari geçişinde sürüm ve rapor baseline farkları kapatıldı.
- Aktif teknik borç kaydı bırakılmadan dokümantasyon tek sürüm çizgisine toplandı.

---

## [v4.2.1] - 2026-03-19
FAZ-10 sonrası dokümantasyon, paketleme ve cutover doğrulama yüzeyi mevcut repo durumu ile senkronize edildi.

### ✅ Dokümantasyon ve Operasyon Senkronizasyonu
**Dosyalar:** `pyproject.toml`, `.github/workflows/migration-cutover-checks.yml`, `README.md`, `RFC-MultiAgent.md`, `TEKNIK_REFERANS.md`, `runbooks/production-cutover-playbook.md`, `PROJE_RAPORU.md`, `AUDIT_REPORT_v5.0.md`
- `pyproject.toml` paket sürümü `config.py` içindeki runtime sürümüyle uyumlu olacak şekilde `3.0.0` olarak düzeltildi.
- PostgreSQL cutover workflow'undan diskte bulunmayan `requirements.txt` bağımlılığı kaldırıldı; migration provası artık `requirements-dev.txt + asyncpg` ile çalışır.
- README, React/Vite geliştirme akışı, SPA öncelikli servisleme modeli, güncel proje ağacı ve 149 test modülü / 151 test dosyası gerçekliğiyle yenilendi.
- RFC ve teknik referans, Supervisor/Coder/Researcher/Reviewer sorumluluklarını ve reviewer'ın dinamik QA/sandbox regresyon rolünü yansıtacak şekilde güncellendi.
- Production cutover ve audit raporları prompt registry, DLP, observability dashboard'ları, migration provası ve `%99` local/CI ratchet gate ve opt-in `%100` coverage campaign detaylarıyla güçlendirildi.

### Teknik Borç Kapanışı
- Cutover workflow içindeki `requirements.txt` drift'i kaldırıldı.
- Operasyon ve audit dokümantasyonu mevcut repo gerçekliğiyle yeniden hizalandı.

---

## [v4.2.0] - 2026-03-19
FAZ-10 — Autonomous LLMOps kapanış anlatısı kurumsal operasyon seviyesiyle eşitlendi.

### ✅ FAZ-10 — Faz 4 Operasyonel Olarak Kapatıldı
**Dosyalar:** `PROJE_RAPORU.md`, `RFC-MultiAgent.md`, `AUDIT_REPORT_v5.0.md`, `README.md`
- Faz 4; aktif öğrenme, vision, cost-aware routing ve dış sistem orkestrasyonunu kapsayan birleşik **Autonomous LLMOps** katmanı olarak yeniden çerçevelendi.
- Audit trail ve direct `p2p.v1` handoff doğrulamaları bu kabiliyetlerin sadece mevcut değil, denetlenebilir ve rollout'a hazır olduğunu gösterecek şekilde dokümante edildi.
- Proje raporu ve RFC tarafında `v4.2.0` operasyonel kapanış dili, audit ve README tarafında da görünür hâle getirildi.

### Teknik Borç Kapanışı
- Faz 4 kapanışına ait operasyonel belirsizlikler tek kurumsal anlatıda konsolide edildi.

---

## [v3.2.0] - 2026-03-19
FAZ-10 — Autonomous LLMOps ürün anlatısı konsolide edildi.

### ✅ FAZ-10 — Faz 4 Ürün Hikâyesi Tek Çatı Altında Toplandı
**Dosyalar:** `PROJE_RAPORU.md`, `README.md`
- Active Learning/LoRA, Vision Pipeline, cost-aware routing ve Slack/Jira/Teams orkestrasyonu birlikte Faz 4 ürün hikâyesi olarak yeniden yazıldı.
- Faz 4 artık tekil özellik listesi yerine kapalı döngü öğrenme + çok modlu üretim + otonom entegrasyon yönetimi ekseninde anlatılıyor.

### Teknik Borç Kapanışı
- Ayrı bir yeni teknik borç kapanışı yok; Faz 4 ürün hikâyesi borç sonrası ürünleştirme diline taşındı.

---

## [v3.0.31] - 2026-03-19
FAZ-9 — Kurumsal audit trail ve doğrudan P2P handoff rollout'u raporlarla senkronize edildi.

### ✅ FAZ-9 — Tenant RBAC Audit Trail Kayıtları Operasyonel Olarak Doğrulandı
**Dosyalar:** `core/db.py`, `migrations/versions/0003_audit_trail.py`, `web_server.py`, `tests/test_rbac_policy_runtime.py`
- `audit_logs` tablosu Alembic migration `0003_audit_trail` ile şemaya eklendi; kullanıcı/zaman damgası indeksleri hazırlandı.
- `core/db.py` içine `record_audit_log()` ve `list_audit_logs()` yardımcıları eklenerek hem SQLite hem PostgreSQL yollarında denetim kaydı okunur/yazılır hale geldi.
- `web_server.py::access_policy_middleware` artık RBAC kararlarından sonra `user_id`, `tenant_id`, `action`, `resource`, `ip_address` ve `allowed` alanlarını audit trail'e asenkron olarak yazıyor.
- `tests/test_rbac_policy_runtime.py` hem DB round-trip'ini hem de middleware'in izin verilen erişimleri audit tablosuna kaydettiğini doğruluyor.

### ✅ FAZ-9 — Direct Agent Handoff Protokolü Swarm Katmanına Taşındı
**Dosyalar:** `agent/core/contracts.py`, `agent/base_agent.py`, `agent/core/supervisor.py`, `agent/swarm.py`, `tests/test_swarm_orchestrator.py`, `tests/test_supervisor_agent.py`
- `P2PMessage` / `DelegationRequest` sözleşmeleri `handoff_depth`, `protocol` ve `meta.reason` alanlarıyla kurumsal direct handoff protokolünü standartlaştırdı.
- `BaseAgent.delegate_to(...)` ve `SupervisorAgent._route_p2p(...)`, sender/receiver bağlamını ve hop sayısını koruyarak fail-closed P2P delegasyonu sürdürüyor.
- `SwarmOrchestrator._direct_handoff(...)` aynı sözleşmeyi runtime orchestration akışına taşıdı; coder → reviewer → coder zincirinde bağlam kaybı olmadan uzmanlar arası el değiştirme mümkün hale geldi.
- İlgili testler sender/receiver, `p2p_reason`, `p2p_protocol` ve `handoff_depth` alanlarının korunduğunu doğruluyor.

---

### Teknik Borç Kapanışı
- Tenant RBAC audit trail omurgası kurumsal doğrulama eksiklerini kapattı.
- Direct `p2p.v1` handoff zinciri bağlam korumalı hale getirildi.

---

## [v3.0.30] - 2026-03-19
FAZ-8 — Son düşük öncelikli kalite borçları kapatıldı; Zero Debt doğrulama turu tamamlandı.

### ✅ FAZ-8 — D-8..D-14 Kapanış Doğrulaması
**Dosyalar:** `core/entity_memory.py`, `core/cache_metrics.py`, `core/judge.py`, `core/vision.py`, `core/active_learning.py`, `core/hitl.py`, `core/llm_client.py`, `web_server.py`
- **D-8 Çözüldü:** `core/entity_memory.py` içindeki no-op / dead-code satırı kaldırıldı; `get_entity_memory()` artık yalnızca gerçek `db_url` çözümlemesi yapıyor.
- **D-9 Çözüldü:** `core/cache_metrics.py` içine modül düzeyinde public `record_cache_hit()`, `record_cache_miss()` ve `record_cache_skip()` sarmalayıcıları eklendi; `core/llm_client.py` private singleton yerine bu public API'yi kullanıyor.
- **D-10 Çözüldü:** `core/judge.py` içinde `Config()` nesnesi `LLMJudge.__init__()` içine alındı; `_call_llm()` artık aynı config örneğini yeniden kullanıyor.
- **D-11 Çözüldü:** `core/vision.py` içindeki görsel okuma akışı `await asyncio.to_thread(p.read_bytes)` ile event loop'u bloklamayacak şekilde güncellendi.
- **D-12 Çözüldü:** `core/active_learning.py` içindeki `IN (...)` SQL güncellemesi named placeholder (`:id_0`, `:id_1`, ...) yaklaşımına taşındı; veri bind parametreleriyle geçiriliyor.
- **D-13 Çözüldü:** `core/hitl.py` içindeki `_HITLStore` kilidi event loop dışında oluşturulmak yerine `None` ile başlatılıp ilk kullanımda lazy-init ediliyor.
- **D-14 Çözüldü:** `core/hitl.py` içine public `notify()` wrapper'ı eklendi; `web_server.py` artık private `_notify()` yerine bu public arayüzü çağırıyor.

**🏁 Zero Debt Sonucu:** Audit kapsamındaki tüm bulgular (`K-1..K-2`, `Y-1..Y-6`, `O-1..O-8`, `D-1..D-14`) kapatıldı. Açık kritik, yüksek, orta veya düşük öncelikli bulgu kalmadı; güvenlik/operasyon puanı **10.0/10** olarak teyit edildi.

---

### Teknik Borç Kapanışı
- `D-8..D-14` kümesinin tamamı kapatıldı.
- Proje denetim kapsamındaki tüm açık bulgular sıfırlanarak `Zero Debt` durumuna geçti.

---

## [v3.0.26] - 2026-03-18
FAZ-7 — Slack entegrasyonu ve audit çapraz-doğrulama turu tamamlandı.

### ✅ FAZ-7 — O-8 Düzeltme: SlackManager Senkron Blokajı Giderildi
**Dosya:** `managers/slack_manager.py`
- `_init_client()` içindeki senkron `auth_test()` çağrısı kaldırıldı.
- Token doğrulaması asenkron `initialize()` fonksiyonuna taşındı ve `asyncio.to_thread(...)` ile event loop bloklaması önlendi.
- Doğrulama: `managers/slack_manager.py:47-95`

### ✅ FAZ-7 — D-7 Düzeltme: Judge Prometheus Gauge Tekrar Kayıt Riski Giderildi
**Dosya:** `core/judge.py`
- `_prometheus_gauges` modül düzeyi önbelleği eklendi.
- `_inc_prometheus()` aynı metrik adını yeniden kaydetmek yerine mevcut Gauge nesnesini tekrar kullanıyor.
- Doğrulama: `core/judge.py:49-63`

### ✅ FAZ-7 — Önceden Kapatılan Entegrasyon Bulguları Yeniden Doğrulandı
**Dosyalar:** `core/llm_client.py`, `web_server.py`
- Y-6 için `record_routing_cost()` çağrısının aktif olduğu yeniden doğrulandı.
- O-7 için Vision / EntityMemory / FeedbackStore / Slack / Jira / Teams endpoint'lerinin HTTP katmanına gerçekten bağlandığı yeniden doğrulandı.

### ⚠️ FAZ-7 — Açık Kalan Düşük Öncelikli Bulgular
**Dosyalar:** `core/entity_memory.py`, `core/cache_metrics.py`, `core/judge.py`, `core/vision.py`, `core/active_learning.py`, `core/hitl.py`, `web_server.py`
- `D-8` açık: `core/entity_memory.py` içinde `db_url = db_url` no-op satırı hâlâ mevcut.
- `D-9` açık: `core/cache_metrics.py` yalnızca sınıf içi `record_*` metodlarına sahip; modül düzeyi public wrapper fonksiyonlar eklenmediği için `llm_client.py` private `_cache_metrics` nesnesini doğrudan kullanmaya devam ediyor.
- `D-10` açık: `core/judge.py::_call_llm()` içinde `Config()` hâlâ her çağrıda yeniden oluşturuluyor.
- `D-11` açık: `core/vision.py::load_image_as_base64()` hâlâ senkron `read_bytes()` kullanıyor.
- `D-12`, `D-13`, `D-14` açık: önceki audit raporundaki durum değişmedi.

---

### Teknik Borç Kapanışı
- `O-8` Slack senkron blokajı ve `D-7` Prometheus tekrar kayıt riski kapatıldı.
- Önceki `Y-6` ve `O-7` kapanışları yeniden doğrulanarak entegrasyon drift'i temizlendi.

---

## [v3.0.18] - 2026-03-18
FAZ-6 Düşük Öncelikli Son Bulgu — D-6 kapatıldı. Tüm bulgular tamamlandı.

### ✅ FAZ-6 — D-6 Düzeltme: DB `_run_sqlite_op` Gereksiz Lazy Lock Kontrolü
**Dosya:** `core/db.py`
- `_run_sqlite_op` içindeki erişilemez `if self._sqlite_lock is None: raise RuntimeError(...)` bloğu `assert self._sqlite_lock is not None` ile değiştirildi.
- `_connect_sqlite()` her zaman `_sqlite_lock = asyncio.Lock()` oluşturduğundan ve `_sqlite_conn is None` kontrolü üstte yapıldığından ikinci kontrol dead-code'du.
- `assert` ile hem gereksiz dal kaldırıldı hem de lock varlığı belgesi tutuldu.
- Doğrulama: `core/db.py:189`

**🏁 Denetim Tamamlandı:** Tüm K-1..K-2, Y-1..Y-5, O-1..O-6, D-1..D-6 bulguları kapatıldı. Güvenlik puanı: **10.0 / 10**.

---

### Teknik Borç Kapanışı
- `D-6` DB lazy-lock dead-code borcu kapatıldı.

---

## [v3.0.17] - 2026-03-18
FAZ-5 Orta Öncelikli Güvenlik Hardening — Tüm O-1..O-6 bulgular kapatıldı.

### ✅ FAZ-5 — O-1 Doğrulama: Tüm Kilitleri `_app_lifespan`'da Başlat
**Dosya:** `web_server.py`
- `_agent_lock`, `_redis_lock`, `_local_rate_lock` tümü `_app_lifespan` içinde event loop başlatıldıktan hemen sonra oluşturuluyor. Lazy init anti-pattern yok.
- Doğrulama: `web_server.py:289-293`

### ✅ FAZ-5 — O-2 Düzeltme: `add_document_from_file` Base Directory Kısıtlaması
**Dosya:** `core/rag.py`
- `file.is_relative_to(Config.BASE_DIR)` sınır kontrolü eklendi. Proje kök dizini dışındaki tüm dosyalara erişim engellendi.
- Boş uzantı (`""`) `_TEXT_EXTS` whitelist'inden zaten kaldırılmıştı; `_BLOCKED_PARTS` koruması da eklendi.
- Doğrulama: `core/rag.py:635-637`

### ✅ FAZ-5 — O-3 Düzeltme: `DOCKER_REQUIRED` Bayrağı
**Dosyalar:** `config.py`, `managers/code_manager.py`, `.env.example`
- `DOCKER_REQUIRED: bool = get_bool_env("DOCKER_REQUIRED", False)` alanı config.py'ye eklendi.
- `execute_code` fonksiyonunda Docker erişilemezken `Config.DOCKER_REQUIRED` kontrol ediliyor; `True` ise yerel subprocess fallback engelleniyor.
- `.env.example`'a `DOCKER_REQUIRED=false` belgesi eklendi.

### ✅ FAZ-5 — O-4 Doğrulama: Senkron Ollama Check `asyncio.to_thread` ile Sarıldı
**Dosya:** `web_server.py`
- `Config.validate_critical_settings()` zaten `await asyncio.to_thread(Config.validate_critical_settings)` ile sarılmış durumda.
- Doğrulama: `web_server.py:295`

### ✅ FAZ-5 — O-5 Doğrulama: WebSocket Token `Sec-WebSocket-Protocol` Başlığından Okunuyor
**Dosya:** `web_server.py`
- WebSocket handshake sırasında `sec-websocket-protocol` başlığından token okunuyor; JSON payload fallback ikincil konuma düşürüldü.
- Doğrulama: `web_server.py:1076-1103`

### ✅ FAZ-5 — O-6 Düzeltme: `run_shell` Tehlikeli Komut Blocklist
**Dosya:** `managers/code_manager.py`
- `allow_shell_features=True` yoluna yıkıcı komut kalıpları için blocklist eklendi (`rm -rf /`, fork bomb, disk silme, vb.).
- Blocklist `shell=True` subprocess çağrısından önce uygulanıyor.
- Doğrulama: `managers/code_manager.py:551-560`

---

### Teknik Borç Kapanışı
- `O-1..O-6` güvenlik hardening maddeleri kapatıldı.

---

## [v3.0.16] - 2026-03-18
FAZ-4 Yüksek Öncelikli Güvenlik Hardening — Tüm Y-1..Y-5 bulgular doğrulandı ve kapatıldı.

### ✅ FAZ-4 — Y-1 Doğrulama: `/set-level` Admin Kısıtlaması
**Dosya:** `web_server.py`
- `set_level_endpoint` zaten `_require_admin_user` Depends dependency'si ile korunuyor. Kod doğrulamasında bulgu önceden çözülmüş olarak tespit edildi.
- Doğrulama: `web_server.py:1865` — `async def set_level_endpoint(request: Request, _user=Depends(_require_admin_user))`

### ✅ FAZ-4 — Y-2 Doğrulama: RAG Upload Boyut Limiti
**Dosya:** `web_server.py`
- Upload endpoint'i zaten `await file.read(max_bytes + 1)` ile diske yazmadan önce boyut kontrolü yapıyor; aşımda HTTP 413 döndürüyor.
- Doğrulama: `web_server.py:1756-1762`

### ✅ FAZ-4 — Y-3 Doğrulama: `_summarize_memory` Async Çağrısı
**Dosya:** `agent/sidar_agent.py`
- `docs.add_document` zaten `await self.docs.add_document(...)` ile doğru şekilde çağrılıyor; `asyncio.to_thread` anti-pattern yok.
- Doğrulama: `agent/sidar_agent.py:497`

### ✅ FAZ-4 — Y-4 Doğrulama: X-Forwarded-For TRUSTED_PROXIES
**Dosya:** `web_server.py`
- `_get_client_ip()` zaten `Config.TRUSTED_PROXIES` whitelist kontrolü yapıyor; XFF başlığı yalnızca güvenilir proxy IP'lerinden geliyorsa okunuyor.
- Doğrulama: `web_server.py:945-955`

### ✅ FAZ-4 — Y-5 Düzeltme: REDIS_URL get_system_info'dan Kaldırıldı
**Dosya:** `config.py`
- `get_system_info()` dönüş sözlüğünden `redis_url` alanı tamamen kaldırıldı. Kısmi şifre maskeleme yetersiz görüldüğünden (host/port da ifşa oluyordu) alan bütünüyle çıkarıldı.
- Artık kullanılmayan `import re` de kaldırıldı.
- Doğrulama: `config.py:561` — alan mevcut değil.

---

### Teknik Borç Kapanışı
- `Y-1..Y-5` yüksek öncelikli güvenlik bulguları kapatıldı.

---

## [v3.0.15] - 2026-03-18
FAZ-3 Düşük Öncelikli Teknik Borç Temizliği — Tüm D-1..D-5 bulgular ve §11.2 refactor kalıntıları kapatıldı.

### ✅ FAZ-3-1 — web_server.py Dead-Code Temizliği (§11.2 / YN3-O-3 Kapatma)
**Dosya:** `web_server.py`
- `/auth/register` endpoint'inde `hasattr(payload, "username")` + `payload.get("username", "")` dead-code deseni kaldırıldı; `payload.username.strip()` ile doğrudan Pydantic model alanına erişildi.
- `/auth/login` endpoint'inde aynı pattern temizlendi; `payload.username.strip()` / `payload.password` doğrudan kullanım.
- `_RegisterRequest` ve `_LoginRequest` Pydantic modelleri zaten tüm doğrulamayı yapmaktadır; `hasattr`/`.get()` artık gerekmiyordu.

### ✅ FAZ-3-2 — Açık Metrik Endpoint Auth Koruması (D-3)
**Dosyalar:** `web_server.py`, `config.py`, `.env.example`
- `/metrics`, `/metrics/llm`, `/metrics/llm/prometheus`, `/api/budget` endpoint'leri `open_paths` whitelist'inden çıkarıldı.
- `_require_metrics_access(request, user)` Depends dependency eklendi: admin kullanıcı **veya** `METRICS_TOKEN` Bearer token ile erişim.
- `config.py`'ye `METRICS_TOKEN: str = os.getenv("METRICS_TOKEN", "")` alanı eklendi.
- `.env.example`'a `METRICS_TOKEN=` belgesi ve açıklaması eklendi.

### ✅ FAZ-3-3 — Test Altyapısı Standardizasyonu (§11.2 Yol Haritası)
**Dosyalar:** `tests/conftest.py`, `pytest.ini`, `.github/workflows/ci.yml`
- `conftest.py`: Deprecated `event_loop` session fixture override kaldırıldı; `asyncio` import temizlendi.
- `pytest.ini`: `asyncio_default_fixture_loop_scope = session` eklendi (pytest-asyncio ≥ 0.21 standart yolu); `slow` ve `pg_stress` marker tanımları eklendi.
- `ci.yml`: `pg-stress` job eklendi — PostgreSQL 16 service container, `alembic upgrade head` migration adımı ve `pytest -m pg_stress` bağlantı havuzu stres testi otomatikleştirildi.

### ✅ FAZ-3-4a — config.py GPU Fraction Yorum Düzeltmesi (D-1)
**Dosya:** `config.py`
- GPU bellek fraksiyonu hata mesajı: `"(0.1–1.0 bekleniyor)"` → `"(0.1–0.99 bekleniyor, 1.0 dahil değil)"` — `frac < 1.0` validation kuralıyla tutarlı hale getirildi.
- Satır 332 yorum da güncellendi: `# Embedding ve model yüklemeleri için VRAM fraksiyonu (0.1–0.99 bekleniyor, 1.0 dahil değil)`

### ✅ FAZ-3-4b — main.py Port Validasyonu (D-2)
**Dosya:** `main.py`
- `--port` argümanı için `parse_args()` sonrasına 1–65535 aralık doğrulayıcısı eklendi.
- Aralık dışı değer için `parser.error(f"--port değeri 1-65535 arasında...")` ile kullanıcı dostu hata mesajı.

### ✅ FAZ-3-4c — core/rag.py bleach HTML Sanitizasyonu (D-4)
**Dosyalar:** `core/rag.py`, `pyproject.toml`
- `bleach` kütüphanesi opsiyonel import olarak eklendi (`try/except ImportError`).
- `_clean_html()` metodu güncellendi: `bleach` varsa `bleach.clean(html, tags=[], strip=True, strip_comments=True)` ile DOM tabanlı sanitizasyon; yoksa mevcut regex fallback korunur.
- `pyproject.toml` çekirdek bağımlılıklarına `"bleach~=6.1.0"` eklendi.

### ✅ FAZ-3-4d — agent/sidar_agent.py Prompt Injection Koruması (D-5)
**Dosya:** `agent/sidar_agent.py`
- `BASE_DIR` tam dosya sistemi yolu `_build_context()` içinde LLM'e artık gönderilmiyor; `"[proje dizini]"` placeholder kullanılıyor.
- `GITHUB_REPO` tam URL yerine `owner/repo` formatına indirgendi.
- `Son dosya` alanı tam yol yerine `Path(last_file).name` (basename) ile sınırlandırıldı.
- Kod bloğuna güvenlik açıklama yorumu eklendi.

---

### Teknik Borç Kapanışı
- `D-1..D-5` teknik borç kümesi kapatıldı.
- Coverage gate, test standardizasyonu ve auth/HTML/context güvenlik temizliği tamamlandı.

---

## [v3.0.12] - 2026-03-16
§13 kalan maddeler: Extras fine-tuning tamamlandı; Swarm + React UI temeli oluşturuldu.

### ✅ Bağımlılık Extras Grupları — Tamamlandı
**Dosya:** `pyproject.toml`, `requirements-dev.txt`, `uv.lock`
- Yeni extras: `[gemini]` (`google-generativeai`), `[anthropic]` (`anthropic`), `[gpu]` (`nvidia-ml-py`), `[sandbox]` (`docker`), `[gui]` (`eel`)
- `openai~=1.51.2` core'dan kaldırıldı — codebase httpx ile OpenAI API'yi doğrudan çağırıyor; SDK hiç kullanılmıyordu
- `opentelemetry-instrumentation-httpx~=0.50b0` `[telemetry]` extras'ına eklendi (web_server.py'de HTTPXClientInstrumentor kullanılıyor)
- `[all]` kolaylık profili eklendi: tek komutla tüm opsiyonel paketleri kurar
- `requirements-dev.txt` → `-e .[all,dev]` olarak güncellendi
- `uv.lock` yeniden oluşturuldu (openai kaldırıldı, otel-httpx eklendi)

### 🔄 Agent Swarm + Marketplace Temeli
**Dosyalar:** `agent/registry.py`, `agent/swarm.py`
- **`AgentRegistry`**: Çalışma zamanı ajan keşfi ve eklenti kaydı. `@AgentRegistry.register()` dekoratörü veya `register_type()` ile yeni ajan tipleri eklenir. `find_by_capability()` intent bazlı arama sağlar.
- **`AgentSpec`**: `role_name`, `capabilities`, `description`, `version`, `is_builtin` meta verisi ile ajan tanımı
- **`SwarmOrchestrator`**: `run()` (tek görev), `run_parallel()` (eş zamanlı, semafore kısıtlı), `run_pipeline()` (sıralı, context aktarımlı) modları
- **`TaskRouter`**: `_INTENT_CAPABILITY_MAP` üzerinden intent → yetenek → ajan spec yönlendirmesi; yeni kayıtlı ajanlar otomatik keşfedilir
- Yerleşik 3 rol (coder, researcher, reviewer) otomatik kayıtlı

### 🔄 React Frontend Scaffold
**Dizin:** `web_ui_react/`
- Vite + React 18 + Zustand tabanlı modern SPA
- **`useWebSocket`**: FastAPI `/ws/{session_id}` endpoint'i ile tam uyumlu; streaming chunks, `[DONE]` sinyali, JSON zarf ve ham metin chunk desteği
- **`useChatStore`**: Zustand ile mesaj geçmişi, akış tamponu, hata durumu
- **Bileşenler:** `ChatWindow` (auto-scroll), `ChatMessage` (react-markdown + rehype-highlight), `ChatInput` (Enter gönder, Shift+Enter satır), `StatusBar` (WS durum + yeni oturum)
- Vite proxy: `/api`, `/ws`, `/admin`, `/sessions` → `localhost:7860`; `npm run dev` ile hazır çalışır
- Build çıktısı `web_ui_built/` → FastAPI mount'u için hazır yapı

### Güvenlik (önceki commit)
**Dosyalar:** `config.py`, `tests/test_security_warnings.py`
- `MEMORY_ENCRYPTION_KEY` boşken `logger.critical()` (JWT_SECRET_KEY pattern'i ile tutarlı)
- Redis rate limit fallback testleri (10 test)

---

### Teknik Borç Kapanışı
- Bu sürümde ayrı bir teknik borç kapanışı kaydı bulunmuyor; odak sürüm farklarının belgelenmesidir.

---

## [v3.0.11] - 2026-03-16
§13 v4.0 Kurumsal Yol Haritası iyileştirmeleri uygulandı.

### ✅ OTel Span Enstrümantasyonu — OpenAI ve LiteLLM Sağlayıcıları
**Dosya:** `core/llm_client.py`
Ollama ve Gemini sağlayıcılarında mevcut olan OpenTelemetry span enstrümantasyonu eksik olan iki sağlayıcıya eklendi:
- **OpenAI client:** `llm.openai.chat` span; `sidar.llm.provider`, `sidar.llm.model`, `sidar.llm.stream`, `sidar.llm.total_ms` attribute'ları; streaming için `start_span`, non-streaming için `start_as_current_span` pattern'i uygulandı; her iki `except` bloğuna `span_cm.__exit__` eklendi.
- **LiteLLM client:** `llm.litellm.chat` span; `sidar.llm.provider`, `sidar.llm.model`, `sidar.llm.stream`, `sidar.llm.total_ms` attribute'ları; fallback model döngüsü kapsamında hata yolları dahil tüm çıkış noktaları kapatıldı.
- **Sonuç:** Tüm 5 LLM sağlayıcısı (Ollama, Gemini, OpenAI, Anthropic, LiteLLM) artık `sidar.llm.*` attribute'larıyla tam kapsamlı OTel izlemeye sahip.

### ✅ OTel Span Enstrümantasyonu — RAG Arama Katmanı
**Dosya:** `core/rag.py`
- `opentelemetry` paketinin opsiyonel import'u eklendi (`try/except` — paket yoksa `None`).
- `search()` async metodu `rag.search` span ile sarıldı; `sidar.rag.mode`, `sidar.rag.session_id`, `sidar.rag.query_len`, `sidar.rag.success` attribute'ları eklendi.
- `asyncio.to_thread()` ile çağrılan `_search_sync` için span async sınırda (`search()` içinde) oluşturuldu — context propagation korundu.

### ✅ Prompt Registry Admin UI
**Dosyalar:** `web_ui/index.html`, `web_ui/app.js`
- `index.html` admin paneline "Prompt Registry" bölümü eklendi: istatistik kartları (aktif rol, toplam sayım), rol filtresi, yenile/yeni prompt butonları, ID/Rol/Versiyon/Durum/Güncellenme/İşlem sütunlarından oluşan tablo, prompt oluşturma/düzenleme formu (rol seçici, etkinleştirme checkbox'ı, textarea).
- `app.js`'e 5 yeni fonksiyon eklendi: `loadPromptRegistry()` (GET /admin/prompts), `showPromptForm()`, `hidePromptForm()`, `savePrompt()` (POST /admin/prompts), `activatePrompt(id)` (POST /admin/prompts/activate).
- `showAdminPanel()` fonksiyonu `loadPromptRegistry()` çağrısını içerecek şekilde güncellendi.

### ✅ `.env.example` Genişletildi
**Dosya:** `.env.example`
Eksik v4.0 konfigürasyon değişkenleri için yeni bölümler eklendi:
- **LiteLLM Gateway:** `LITELLM_GATEWAY_URL`, `LITELLM_API_KEY`, `LITELLM_MODEL`, `LITELLM_FALLBACK_MODELS`, `LITELLM_TIMEOUT`
- **Anlamsal Önbellekleme:** `ENABLE_SEMANTIC_CACHE`, `SEMANTIC_CACHE_THRESHOLD`, `SEMANTIC_CACHE_TTL`, `SEMANTIC_CACHE_MAX_ITEMS`
- **pgvector RAG:** `RAG_VECTOR_BACKEND`, `PGVECTOR_TABLE`, `PGVECTOR_EMBEDDING_DIM`, `PGVECTOR_EMBEDDING_MODEL`
- **Event Bus:** `SIDAR_EVENT_BUS_CHANNEL`, `SIDAR_EVENT_BUS_GROUP`
- **OTel genişletme:** `OTEL_SERVICE_NAME`, `OTEL_INSTRUMENT_FASTAPI`, `OTEL_INSTRUMENT_HTTPX`

### ✅ PROJE_RAPORU.md v3.0.11 Güncellendi
- §13'te Anlamsal Önbellekleme: 🟡 Kısmen → ✅ Tamamlandı (Redis + cosine similarity + LRU)
- §13'te Dinamik Prompt ve Model Yönetimi: pending → ✅ Tamamlandı (migration 0002 + 4 API endpoint + Admin UI)
- §13'te Dağıtık İzlenebilirlik: sınırlı → ✅ Tamamlandı (5 LLM sağlayıcısı + RAG OTel span)
- v4.0 özet bloğuna 3 yeni tamamlama maddesi eklendi.

---

### Teknik Borç Kapanışı
- Bu sürümde ayrı bir teknik borç kapanışı kaydı bulunmuyor; odak sürüm farklarının belgelenmesidir.

---

## [v3.0.9] - 2026-03-16
YN3 serisi kapatma — v3.0.7 doğrulama turunda tespit edilen 6 bulgunun tamamı giderildi.

### ✅ YN3-O-4 — Yanlış Pozitif Teyit Edildi
`agent/sidar_agent.py:96,321` — `threading.Lock()` `_load_instruction_files()` sync metodunda doğru kullanılıyor; metot `asyncio.to_thread()` ile thread pool'da çalışıyor. `asyncio.Lock()` thread-safe olmadığından değişiklik gerekmez.

### ✅ YN3-O-1 — `_ANYIO_CLOSED` Artık Kullanılıyor
**Dosya:** `web_server.py`
`_ANYIO_CLOSED` WebSocket handler dış `except` bloğuna eklendi. `anyio.ClosedResourceError` artık `WebSocketDisconnect` ile eşdeğer biçimde işleniyor; beklenmedik diğer istisnalar ise `logger.warning` ile iletilir.

### ✅ YN3-O-2 — `_rate_lock` Dead Code Kaldırıldı
**Dosyalar:** `web_server.py`, `tests/test_targeted_coverage_additions.py`, `tests/test_sidar.py`
* `_rate_lock: asyncio.Lock | None = None` satırı kaldırıldı (`web_server.py:467`).
* Test dosyalarındaki `web_server._rate_lock = asyncio.Lock()` ifadeleri (6 adet, 2 dosya) `web_server._local_rate_lock = asyncio.Lock()` olarak güncellendi. Artık testler üretim kodunun gerçekten kullandığı kilidi sıfırlıyor; test izolasyonu tamamlandı.
* `_rate_data` alias'ı korundu — `_local_rate_limits` sözlüğü için geçerli test temizleme noktası.

### ✅ YN3-O-3 — `isinstance(payload, dict)` Redundant Kaldırıldı
**Dosya:** `web_server.py` — `/auth/register` (satır 365-366) ve `/auth/login` (satır 382-383)
FastAPI Pydantic doğrulaması `payload`'ı her zaman model örneği olarak sağlar; `isinstance(payload, dict)` dalı hiçbir zaman `True` olmuyordu. `payload.username` / `payload.password` doğrudan kullanılıyor.

### ✅ YN3-D-1 — JWT_SECRET_KEY Config'e Taşındı + Kritik Uyarı Eklendi
**Dosyalar:** `config.py`, `web_server.py`, `.env.example`
* `JWT_SECRET_KEY`, `JWT_ALGORITHM`, `JWT_TTL_DAYS` `config.py` `Web Arayüzü` bölümüne eklendi.
* `web_server.py`'de `_get_jwt_secret()` yardımcı fonksiyonu oluşturuldu; `JWT_SECRET_KEY` boşsa `logger.critical(...)` ile açık uyarı verilir.
* `.env.example`'a JWT bölümü ve güvenlik notu eklendi.

### ✅ YN3-D-2 — Grafana URL Dinamik Injection
**Dosyalar:** `config.py`, `web_server.py`, `web_ui/index.html`, `.env.example`
* `GRAFANA_URL` env değişkeni `config.py`'ye eklendi (varsayılan: `http://localhost:3000`).
* `index()` route'u artık `window.__SIDAR_CONFIG__ = {"grafanaUrl": "..."}` config script'ini `<head>` içine inject ediyor.
* `web_ui/index.html:286` Grafana butonu `window.__SIDAR_CONFIG__.grafanaUrl` değerini kullanıyor; fallback olarak yine `http://localhost:3000` korunuyor.
* `.env.example`'a `GRAFANA_URL` ve açıklaması eklendi.

---

### Teknik Borç Kapanışı
- Bu sürümde ayrı bir teknik borç kapanışı kaydı bulunmuyor; odak sürüm farklarının belgelenmesidir.

---

## [v3.0.8] - 2026-03-16
YN2 serisi kapatma — v3.0.6 doğrulama turunda tespit edilen her iki operasyonel uyumsuzluk giderildi.

### ✅ YN2-Y-1 Kapatıldı — CI Kurulum Adımı Düzeltildi

**[YN2-Y-1 Çözüldü] `.github/workflows/ci.yml` — `pip install -r requirements.txt` satırı kaldırıldı**
* **Kök neden:** `ci.yml` `Install dependencies` adımı var olmayan `requirements.txt` dosyasını yüklemeye çalışıyordu. Bu, CI kurulumunu hata ile sonlandırıyor ve `pytest-asyncio` hiç yüklenmiyordu. `pytest.ini:4` `asyncio_mode = auto` ayarı aktif olmasına rağmen plugin eksikliği nedeniyle async testler çalışamıyordu.
* **Uygulanan düzeltme:** `pip install -r requirements.txt` satırı kaldırıldı. `requirements-dev.txt` zaten `-e .[rag,postgres,telemetry,dev]` komutuyla `pyproject.toml[dev]`'daki `pytest-asyncio>=0.23.0` dahil tüm bağımlılıkları yükler.
* **Değişen dosya:** `.github/workflows/ci.yml` satır 22 (eski satır silindi)
* **Doğrulama zinciri:** `requirements-dev.txt:3` → `pyproject.toml:40` `pytest-asyncio>=0.23.0`

### ✅ YN2-O-1 Kapatıldı — Mock Varlığı Doğrulandı

**[YN2-O-1 Doğrulandı] `tests/test_code_manager_runtime.py:280-285` — socket mock'ları zaten mevcut**
* `os.stat()` ve `stat.S_ISSOCK()` satır satır incelemeyle tam mock'lanmış olduğu teyit edildi.
* Rapor, mevcut mock'ları gözden kaçırmıştı; test deterministik olduğu onaylandı.
* Ek kod değişikliği gerektirmedi.

---

### Teknik Borç Kapanışı
- Bu sürümde ayrı bir teknik borç kapanışı kaydı bulunmuyor; odak sürüm farklarının belgelenmesidir.

---

## [v3.0.7] - 2026-03-16
Tam kaynak denetimi (v3.0.7) — tüm kaynak dosyalar yeniden satır satır incelendi; YN2-O-1 kapatıldı; YN2-Y-1 hâlâ açık; 6 yeni bulgu (YN3 serisi) kayıt altına alındı.

### ✅ YN2-O-1 Kapatıldı

**[YN2-O-1 Çözüldü] `managers/code_manager.py` — Docker socket fallback test mock'ları doğrulandı**
* `tests/test_code_manager_runtime.py:281-285` satırlarında `os.stat()` `st_mode=0` döndüren sahte nesneyle, `stat.S_ISSOCK()` her zaman `True` döndürecek şekilde tam mock'lanmıştır.
* Test artık WSL2 socket fallback akışını deterministik biçimde doğrulamaktadır.
* Referans: `tests/test_code_manager_runtime.py:238-285`

### 🟠 YN2-Y-1 Hâlâ Açık

**[YN2-Y-1 Devam Ediyor] `pytest.ini` / `pyproject.toml` — async test plugin bağımlılık uyumsuzluğu**
* `pytest.ini:4` içinde `asyncio_mode = auto` aktif. `pytest-asyncio>=0.23.0` yalnızca `pyproject.toml[dev]` extras'ında tanımlı.
* `environment.yml` `-e .[rag,postgres,telemetry,dev]` ile conda ortamında dev dahil ediliyor.
* Bare `pip install -e .` ile kurulan ortamlarda (`dev` extras olmadan) `pytest-asyncio` yüklenmez ve async testler `"async def functions are not natively supported"` hatası verir.
* **Öneri:** `pytest-asyncio` ve `anyio[trio]` paketlerini `pyproject.toml` ana `dependencies`'den değil, CI workflow'da `pip install -e ".[dev]"` ile zorunlu kılarak çözmek veya CI adımına eklemek.

### ✅ YN3 Serisi — Yeni Tespit Edilen Bulgular

| # | Dosya | Satır | Ciddiyet | Açıklama |
|---|-------|-------|----------|----------|
| YN3-O-4 | `agent/sidar_agent.py` | `96`, `321` | 🟠 ORTA | `threading.Lock()` async fonksiyon içinde kullanılıyor; event loop'u anlık bloklama riski. `asyncio.Lock()` ile değiştirilmeli. |
| YN3-O-1 | `web_server.py` | `32-35` | 🟡 ORTA | `_ANYIO_CLOSED` dead code — import ediliyor ama hiç kullanılmıyor. |
| YN3-O-2 | `web_server.py` | `466-467` | 🟡 ORTA | `_rate_data` ve `_rate_lock` dead code — `_local_rate_lock` kullanılırken bu değişkenler tanımlı ama işlevsiz. |
| YN3-O-3 | `web_server.py` | `365-366`, `382-383` | 🟡 ORTA | `isinstance(payload, dict)` redundant — FastAPI Pydantic validation sonrası `payload` her zaman model örneğidir; `.get()` çalışmaz. |
| YN3-D-1 | `web_server.py` | `196`, `207` | 🟡 DÜŞÜK | `"sidar-dev-secret"` hardcoded JWT fallback — production'da `JWT_SECRET_KEY` set edilmezse imzalar tahmin edilebilir. |
| YN3-D-2 | `web_ui/index.html` | `286` | 🟡 DÜŞÜK | `http://localhost:3000` hardcoded Grafana URL — container ortamında düzgün çalışmayabilir. |

---

### Teknik Borç Kapanışı
- Bu sürümde ayrı bir teknik borç kapanışı kaydı bulunmuyor; odak sürüm farklarının belgelenmesidir.

---

## [v3.0.6] - 2026-03-16
Doğrulama turu — v3.0.4/v3.0.5 bulguları kod üzerinde yeniden teyit edildi; 2 yeni operasyonel uyumsuzluk tespit edildi (YN2-Y-1, YN2-O-1).

_(Ayrıntılar PROJE_RAPORU.md §11.3'te kayıtlıdır.)_

---

### Teknik Borç Kapanışı
- Bu sürümde ayrı bir teknik borç kapanışı kaydı bulunmuyor; odak sürüm farklarının belgelenmesidir.

---

## [v3.0.5] - 2026-03-16
Tam kaynak denetimi (v3.0.5) — v3.0.4 tüm bulgular doğrulandı/kapatıldı; 5 yeni bulgu tespit edilip giderildi.

### ✅ v3.0.4 Bulgularının Doğrulanması ve Kapatılması

Aşağıdaki bulgular satır satır kaynak incelemesiyle doğrulanmıştır.

| Bulgu | Dosya | Durum |
|-------|-------|-------|
| K-1 — `.env`/`.example` `_SAFE_EXTENSIONS`'dan kaldırıldı | `web_server.py:876` | ✅ Doğrulandı |
| K-2 — `container.wait()` dict dönüş tipi | `managers/code_manager.py:393` | ✅ Yanlış Pozitif Teyit |
| Y-1 — Test kodu enjeksiyonu `repr()` ile giderildi | `agent/roles/reviewer_agent.py:52` | ✅ Doğrulandı |
| Y-2 — asyncpg `endswith("1")` → `int(...split()[-1]) > 0` | `core/db.py:516–519` | ✅ Doğrulandı |
| Y-3 — `handle()` blocking çağrıları `asyncio.to_thread` | `agent/auto_handle.py:93,96,108` | ✅ Doğrulandı |
| Y-4 — `add_document_from_file` sync | `core/rag.py:427` | ✅ Yanlış Pozitif Teyit |
| Y-5 — `_root = Path(__file__).parent.resolve()` | `web_server.py:838,879,1105` | ✅ Doğrulandı |
| O-1 — ReDoS: `.{0,200}` + 2000 karakter guard | `agent/auto_handle.py:56,72` | ✅ Doğrulandı |
| O-2 — `re.IGNORECASE` zaten mevcut | `managers/security.py:30` | ✅ Yanlış Pozitif Teyit |
| O-3 — `logger.warning()` webhook secret eksikliği | `web_server.py:1294` | ✅ Doğrulandı |
| O-4 — `__exit__(*sys.exc_info())` — 5 lokasyon | `core/llm_client.py:304,383,542,705,890` | ✅ Doğrulandı |
| O-5 — `_init_lock = asyncio.Lock()` pre-created | `agent/sidar_agent.py:101` | ✅ Doğrulandı |
| O-6 — `asyncio.wait_for(..., timeout=REACT_TIMEOUT)` | `agent/core/supervisor.py:86` | ✅ Doğrulandı |
| O-7 — `stat.S_ISSOCK()` WSL2 socket doğrulaması | `managers/code_manager.py:173` | ✅ Doğrulandı |
| D-1 — `async def` shim'ler `def`'e dönüştürüldü | `agent/core/memory_hub.py:45` | ✅ Doğrulandı |
| D-2 — `Version()` sürüm karşılaştırması | `managers/package_info.py:176` | ✅ Doğrulandı |
| D-3 — `daily_usage_usd` vs `total_usage_usd` ayrıldı | `core/llm_metrics.py:188` | ✅ Doğrulandı |
| D-4 — `self._tasks = []` __init__'te başlatılıyor | `managers/todo_manager.py:65` | ✅ Yanlış Pozitif Teyit |
| D-5 — Açıklayıcı `KeyError` mesajı | `agent/core/registry.py:19` | ✅ Doğrulandı |
| D-6 — FTS read `_write_lock` ile korundu | `core/rag.py:661` | ✅ Doğrulandı |

### ✅ v3.0.5 Yeni Bulgular — Giderilen

**[YN-K-1 Çözüldü] `core/rag.py` — `.env`/`.example` `_TEXT_EXTS`'den kaldırıldı (K-1 bypass)**
* `add_document_from_file` içindeki `_TEXT_EXTS` kümesinden `.env` ve `.example` uzantıları çıkarıldı.
* Artık `{"path": ".env"}` ile `/rag/add-file` endpoint'i üzerinden gizli dosyalar RAG deposuna indekslenemiyor.
* Referans: `core/rag.py:446`

**[YN-Y-1 Çözüldü] `agent/sidar_agent.py` — `_lock` lazy None init giderildi**
* `self._lock = None` → `self._lock = asyncio.Lock()` (`__init__` içinde).
* `respond()` içindeki `if self._lock is None:` guard kaldırıldı.
* O-5'te `_init_lock` için uygulanan aynı pattern `_lock` için de tamamlandı.
* Referans: `agent/sidar_agent.py:53`

**[YN-Y-2 Çözüldü] `core/rag.py` — `add_document_from_url` SSRF koruması eklendi**
* `_validate_url_safe()` statik metodu eklendi:
  - Yalnızca `http`/`https` şemalarına izin verilir.
  - IP adresi private/loopback/link-local/reserved ise `ValueError` fırlatır.
  - `localhost`, `169.254.169.254`, `metadata.google.internal` hostname'leri engellendi.
* `max_redirects=5` sınırı eklendi.
* `urllib.parse` ve `ipaddress` modülleri import edildi.
* Referans: `core/rag.py:411–431`

**[YN-Y-3 Çözüldü] `managers/github_manager.py` — `.env`/`.example` `SAFE_TEXT_EXTENSIONS`'dan kaldırıldı**
* GitHub deposu dosyası okuma izninden `.env` ve `.example` uzantıları çıkarıldı.
* K-1 güvenlik gerekçesiyle (hassas ortam değişkeni dosyaları) tutarlı hale getirildi.
* Referans: `managers/github_manager.py:33`

**[YN-O-1 Çözüldü] `web_server.py` — Auth endpoint'leri Pydantic model kullanıyor**
* `_RegisterRequest` (`username` min_length=3/max_length=64, `password` min_length=6/max_length=128) modeli eklendi.
* `_LoginRequest` (`username` max_length=64, `password` max_length=128) modeli eklendi.
* `/auth/register` ve `/auth/login` endpoint'leri `payload: dict` yerine bu modelleri kullanıyor.
* FastAPI'nin otomatik doğrulaması devreye girdiğinden `str(None)` DB'ye ulaşamaz.
* Referans: `web_server.py:269–306`

---

### Teknik Borç Kapanışı
- Bu sürümde ayrı bir teknik borç kapanışı kaydı bulunmuyor; odak sürüm farklarının belgelenmesidir.

---

## [v3.0.4] - 2026-03-16
Tam kaynak denetimi — test istatistikleri güncellendi, kapsama kalite kapısı %100'e yükseltildi, 20 yeni güvenlik/işlevsellik bulgusu tespit edilip giderildi.

### ✅ Güvenlik Düzeltmeleri

**[K-1 Çözüldü] `web_server.py` — `.env`/`.example` `/file-content` endpoint'inden engellendi**
* `_SAFE_EXTENSIONS` kümesinden `.env` ve `.example` kaldırıldı; bu uzantılara `415 Unsupported Media Type` döndürülüyor.
* Regresyon testi `tests/test_web_server_runtime.py::test_vendor_index_and_file_content_guard_paths`'e eklendi.

**[Y-1 Çözüldü] `agent/roles/reviewer_agent.py` — Test kodu enjeksiyonu engellendi**
* Triple-quote string embed → `repr()` ile tüm özel karakterler kaçışlandı.

**[Y-2 Çözüldü] `core/db.py` — asyncpg result `endswith("1")` kırılganlığı giderildi**
* `int(str(result).split()[-1]) > 0` ile "UPDATE 10+" senaryoları doğru işleniyor.

**[Y-3 Çözüldü] `agent/auto_handle.py` — Async bağlamda bloklayıcı senkron çağrılar**
* `handle()` içinde `_try_*` çağrıları `await asyncio.to_thread(...)` ile sarmalandı.

**[Y-5 Çözüldü] `web_server.py` — Symlink traversal tutarsızlığı**
* 3 endpoint'te `_root = Path(__file__).parent.resolve()` yapıldı.

### ✅ Asenkron / Yapısal Düzeltmeler

| Bulgu | Değişiklik |
|-------|-----------|
| O-1 ReDoS | `\bfirst\b.{0,200}\bthen\b` + 2000 karakter guard |
| O-3 Webhook | `logger.warning()` secret eksikliği için |
| O-4 `__exit__` | `sys.exc_info()` ile 5 lokasyon güncellendi |
| O-5 `_init_lock` | `asyncio.Lock()` pre-created in `__init__` |
| O-6 P2P timeout | `asyncio.wait_for(..., REACT_TIMEOUT)` |
| O-7 Docker socket | `stat.S_ISSOCK()` doğrulaması |

### ✅ Kalite / Mimari Düzeltmeler

| Bulgu | Değişiklik |
|-------|-----------|
| D-1 async shims | `async def` → `def` (4 metot) |
| D-2 Version | `packaging.version.Version()` karşılaştırması |
| D-3 daily/total | 24 saatlik pencere ayrımı |
| D-5 KeyError | Açıklayıcı hata mesajı |
| D-6 FTS read | `_write_lock` ile korundu |

---

### Teknik Borç Kapanışı
- Bu sürümde ayrı bir teknik borç kapanışı kaydı bulunmuyor; odak sürüm farklarının belgelenmesidir.

---

## [v3.0.1] - 2026-03-15
Teknik borç temizleme + tam repo denetimi yayını — tüm v3.0 nesil teknik borç kalemleri kapatıldı, Bölüm 11.2 tablosu sıfırlandı; satır sayımları güncellendi; `SANDBOX_*` env var dokümantasyon boşluğu kapatıldı.

### ✅ Ödenmiş Teknik Borçlar

**[Borç #2 Çözüldü] Vanilla JS UI ölçeklenme riski (`web_ui/*.js`)**
* `seedUIStore()` IIFE `app.js`'e eklenerek 12 paylaşımlı durum anahtarı (`isCurrentUserAdmin`, `isStreaming`, `msgCounter`, `currentRepo`, `currentBranch`, `defaultBranch`, `currentSessionId`, `attachedFileContent`, `attachedFileName`, `allSessions`, `cachedRepos`, `cachedBranches`) merkezi varsayılanlarla başlatıldı.
* Tüm dosya genelindeki `let` global değişkenleri kaldırıldı; `chat.js` 10 `let` bildirimi, `sidebar.js` `_cachedBranches`, `app.js` `isCurrentUserAdmin` tamamen UIStore'a taşındı.
* Çift yazma (double-write) anti-pattern'i kaldırıldı — `setUIState()` / `_setState()` tek ve yetkin kaynak oldu.
* `sidebar.js`'e `_getState` shim'i eklendi; dosyalar arası tüm koordinasyon `window.UIStore.state` üzerinden yürüyor.
* `app.js`: `loadGitInfo()` doğrudan global atamaları bıraktı, ESC kısayol ve DOMContentLoaded init UIStore okuyor.

**[Borç #3 Çözüldü] Sağlayıcılar arası tool-calling şema farkları (`core/llm_client.py`)**
* `SIDAR_TOOL_JSON_INSTRUCTION` paylaşımlı sabiti eklendi — Anthropic'teki dağınık inline string kaldırıldı; tüm sağlayıcılar aynı talimat metnini kullanıyor.
* `BaseLLMClient.json_mode_config()` soyut metodu eklendi — her alt sınıf kendi payload konfigürasyonunu kapsülüyor; `build_provider_json_mode_config()` dışarıdan string dispatch'e gerek kalmadı.
* `BaseLLMClient._inject_json_instruction()` statik yardımcısı: mevcut system mesajına talimatı birleştirir, yoksa başa ekler.
* `OllamaClient` → `{"format": SIDAR_TOOL_JSON_SCHEMA}` (değişmedi, metoda taşındı).
* `GeminiClient` → `response_mime_type: application/json` + system_text'e talimat enjeksiyonu.
* `OpenAIClient` → `json_object` yerine `json_schema` structured outputs (`strict: True`) + `_inject_json_instruction` ile system prompt enjeksiyonu.
* `AnthropicClient` → `json_mode_config()` `{}` döndürür; sistem talimatı `SIDAR_TOOL_JSON_INSTRUCTION` sabiti üzerinden enjekte edilir.

### 🔍 Çoklu Denetim Turu Bulguları

**Satır sayısı güncellemeleri (Borç #2 + #3 refaktörleri sonrası gerçek ölçüm):**
* `core/llm_client.py`: 860 → 898 satır (Borç #3 ilaveleri: `json_mode_config()`, `_inject_json_instruction()`, `SIDAR_TOOL_JSON_INSTRUCTION`)
* `web_ui/chat.js`: 721 → 708 satır (Borç #2: 10 `let` bildirimi kaldırıldı)
* `web_ui/sidebar.js`: 421 → 412 satır (Borç #2: `_cachedBranches` ve double-write kaldırıldı)
* `web_ui/app.js`: 710 → 733 satır (Borç #2: `seedUIStore()` IIFE ve `setUIState()` çağrıları eklendi)
* Web UI toplamı: 4.239 → 4.240 satır; Python kaynak toplamı: ~12.160 → 12.185 satır

**`SANDBOX_*` ortam değişkeni dokümantasyon boşluğu (kapatıldı):**
* `SANDBOX_MEMORY`, `SANDBOX_CPUS`, `SANDBOX_NETWORK`, `SANDBOX_PIDS_LIMIT`, `SANDBOX_TIMEOUT` değişkenleri `config.py::SANDBOX_LIMITS` sözlüğünde tanımlı olmasına rağmen `.env.example`'da ve PROJE_RAPORU.md §12.11'de yer almıyordu.
* Her iki dosyaya da eklenip belgelenmiştir.

**Denetim tespitleri (eylem gerektirmeyen / temiz):**
* 134 Python dosyasının tamamı sözdizimi hatası içermiyor (`ast.parse()` doğrulandı).
* Dairesel import riski yok; tüm iç bağımlılık grafiği tek yönlü DAG.
* Hardcoded secret/credential yok; tüm hassas değerler `os.getenv()` veya yardımcı sarmalayıcılar üzerinden okunuyor.
* `ENABLE_MULTI_AGENT` legacy bayrak olarak `config.py`'de `True` sabitine dönüştürüldü; `.env` üzerinden değiştirilemiyor (belgelendi).

**Bağımsız kod incelemelerinden gelen yeni açık teknik borçlar (§11.2'ye eklendi):**
* **Borç #4:** `inspect.isawaitable()` köprüsü — `memory.add()`/`memory.clear()` async olmasına rağmen `sidar_agent.py:432-434`, `397-399`'da wrapper mevcut.
* **Borç #5:** `ConversationMemory.__init__` `file_path` API kalıntısı — DB-first mimarisiyle çelişen `MEMORY_FILE` parametresi.
* **Borç #6:** RAG `DocumentStore` senkron blokajı — `add_document()` ve `search()` sync; `asyncio.to_thread()` ile wrap ediliyor.
* **Borç #7:** `requirements.txt` zorunlu ↔ runtime opsiyonel çelişkisi — `asyncpg`, `opentelemetry-*`, `chromadb` zorunlu listede ama `try/except` ile opsiyonel.
* **Borç #8 (kritik):** `ToolCall` Pydantic modeli `sidar_agent.py`'de tanımlı değil → `test_sidar.py` ImportError, `test_sidar_agent_runtime.py` AttributeError.
* **Borç #9 (kritik):** `_tool_subtask` metodu ve paralel ReAct kod parçacıkları `sidar_agent.py`'de yok → 8+ test kırık (`test_sidar_agent_runtime.py`, `test_parallel_react_improvements.py`, `test_agent_subtask.py`).
* **Borç #10:** `main.py` `DummyConfig` fail-fast sorunu — `config.py` yoksa sahte ayarlarla devam edilmesi.
* **§7.2/7.4:** `asyncpg`, `opentelemetry-*`, `chromadb` bağımlılık statüsü ⚠ notu ile güncellendi.
* **§13:** JWT stateless auth ve dependency extras grupları v4.0 yol haritasına eklendi.

### Teknik Borç Kapanışı
- Bu sürümde ayrı bir teknik borç kapanışı kaydı bulunmuyor; odak sürüm farklarının belgelenmesidir.

---

## [v3.0.0] - 2026-03-11
Bu sürüm, SİDAR'ın kurumsal/SaaS odaklı v3.0 kapanış sürümüdür.

### ✅ Öne çıkanlar
* **Kurumsal veri katmanı:** Alembic migration zinciri, SQLite→PostgreSQL cutover rehberi ve CI dry-run/prova kapıları.
* **Multi-Agent varsayılan mimari:** Supervisor + Coder + Researcher + Reviewer akışının üretim odağında olgunlaştırılması.
* **Güvenlik ve erişim:** Bearer auth, admin panel, WebSocket auth-handshake ve graceful session-expiry UX.
* **Gözlemlenebilirlik:** Prometheus metrikleri + Grafana provisioning/dashboard ile maliyet/hata/kullanıcı görünürlüğü.
* **Sandbox operasyonu:** gVisor/Kata host runtime otomasyon scripti ve rollout dokümantasyonu.

### ✅ Final doğrulama kayıtları (Audit #8–#11)
* **Güvenlik:** WebSocket zorunlu Auth Handshake ve ConversationMemory fail-closed (`MemoryAuthError`) sertleştirmesi eklendi.
* **QA:** ReviewerAgent ile dinamik unit test üretimi ve `MAX_QA_RETRIES=3` devre kesici (circuit-breaker) mekanizması devreye alındı.
* **Operasyon:** SQLite'tan PostgreSQL'e geçiş için `migrate_sqlite_to_pg.py` scripti ve Alembic migration zinciri standardize edildi.
* **Kalite:** Test coverage alt sınırı güncel `pyproject.toml fail_under=99` ratchet baseline'ına taşındı; CI üzerinde profile-aware bloklayıcı gate olarak izlenir.

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
* **[Çözüldü] Test/CI kalite eşiği:** GitHub Actions kalite kapıları, migration kontrolleri ve coverage ratchet gate (`fail_under=99`) ve opt-in `%100` campaign profili operasyonel standarda bağlandı.

#### Önceki Denetimlerde (Audit) Çözüldüğü Doğrulanan Diğer Maddeler
| Madde | Doğrulama | Dosya / Referans |
|-------|-----------|-----------------|
| CLI `asyncio.Lock` lifetime hatası | ✅ `_interactive_loop_async()` tek async fonksiyon; `asyncio.run()` döngü dışında | `cli.py:1` |
| RAG oturum izolasyonu | ✅ `session_id` filtresi ChromaDB `where=` ve SQLite `WHERE` clause | `rag.py:_fetch_chroma`, `_fetch_bm25` |
| RRF hibrit sıralama | ✅ `_rrf_search()` k=60, her iki motordan bağımsız getirme | `rag.py:_rrf_search` |
| Sliding window özetleme | ✅ `apply_summary()` son `keep_last`=4 mesajı korur | `memory.py:apply_summary` |
| Web UI modülarizasyonu | ✅ 6 ayrı dosya; `StaticFiles` mount aktif | `web_server.py`, `web_ui/` |
| Bearer Token Auth | ✅ `basic_auth_middleware` + `auth_tokens` doğrulaması | `web_server.py`, `core/db.py` |
| DDoS rate limit | ✅ `ddos_rate_limit_middleware` 120 istek/60 sn; `/health`, `/healthz`, `/readyz`, `/ui/`, `/static/` muaf | `web_server.py`, `web/middleware/ratelimit.py` |
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
| Coverage zorunluluğu (`pyproject.toml fail_under=99` + opt-in `%100` campaign) | ✅ `run_tests.sh` içinde profile-aware coverage kapısı tanımlı | `run_tests.sh` |
| Performans benchmark baseline'ları | ✅ `tests/test_benchmark.py` ile ChromaDB/BM25/regex hedef eşikleri doğrulanıyor | `tests/test_benchmark.py` |

### Teknik Borç Kapanışı
- Bu sürümde ayrı bir teknik borç kapanışı kaydı bulunmuyor; odak sürüm farklarının belgelenmesidir.

---

## [v2.10.8] - 2026-03-10
Bu sürümde RAG cold-start optimizasyonu tamamlandı ve Anthropic (Claude) sağlayıcı desteği eklendi.

### ✅ RAG Soğuk Başlangıç İyileştirmesi
* **Startup prewarm (`web_server.py`):** FastAPI lifespan başlangıcında `_prewarm_rag_embeddings()` görevi ile Chroma/embedding hazırlığı arka planda tetiklenir.
* **Kullanıcı deneyimi:** İlk RAG çağrısındaki model yükleme gecikmesi sunucu başlangıcına taşındı.

### ✅ Anthropic (Claude) Sağlayıcı Desteği
* **Yeni istemci (`core/llm_client.py`):** `AnthropicClient` eklendi; non-stream ve stream chat akışları desteklenir.
* **Yapılandırma (`config.py`, `.env.example`):** `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL`, `ANTHROPIC_TIMEOUT` değişkenleri eklendi.
* **Başlatıcı/UI/bağımlılıklar:** CLI ve launcher provider seçeneklerine `anthropic` eklendi; Web UI model seçim listesi güncellendi; `requirements.txt` ve `environment.yml` dosyalarına `anthropic` paketi eklendi.

### Teknik Borç Kapanışı
- Bu sürümde ayrı bir teknik borç kapanışı kaydı bulunmuyor; odak sürüm farklarının belgelenmesidir.

---

## [v2.10.7] - 2026-03-08
Bu sürümde çoklu ortam (environment) yapılandırma desteği tamamlandı.

### ✅ Çevre Başına Konfigürasyon
* **Ortam bazlı dotenv yükleme (`config.py`):** `SIDAR_ENV` değişkeni ile `.env.development`, `.env.production`, `.env.test` gibi dosyalar temel `.env` üzerine `override=True` ile yüklenebilir hale getirildi.

### Teknik Borç Kapanışı
- Bu sürümde ayrı bir teknik borç kapanışı kaydı bulunmuyor; odak sürüm farklarının belgelenmesidir.

---

## [v2.10.6] - 2026-03-08
Bu sürümde GitHub entegrasyonu pull modelden webhook tabanlı push modele genişletildi.

### ✅ GitHub Webhook Desteği
* **Webhook alıcısı (`web_server.py`):** Push, Pull Request ve Issue event'lerini dinleyen `POST /api/webhook` endpoint'i eklendi.
* **HMAC doğrulaması (`web_server.py`, `config.py`):** `X-Hub-Signature-256` başlığı `GITHUB_WEBHOOK_SECRET` ile doğrulanır; geçersiz imza istekleri `401` ile reddedilir.
* **Ajan belleği bildirimi (`web_server.py`):** Doğrulanan webhook event'leri `[GITHUB BİLDİRİMİ]` formatında konuşma belleğine asenkron olarak yazılır.

### Teknik Borç Kapanışı
- Bu sürümde ayrı bir teknik borç kapanışı kaydı bulunmuyor; odak sürüm farklarının belgelenmesidir.

---

## [v2.10.5] - 2026-03-08
Bu sürümde güvenlik seviyesi geçişleri ajanın kalıcı sohbet belleğine işlenecek şekilde geliştirildi.

### ✅ Güvenlik Seviyesi Geçiş Logu
* **Runtime seviye değişimi (`managers/security.py`, `agent/sidar_agent.py`):** `SecurityManager.set_level(...)` ve `SidarAgent.set_access_level(...)` eklendi; seviye değişimleri `[GÜVENLİK BİLDİRİMİ]` formatında konuşma belleğine kalıcı olarak yazılıyor.
* **CLI ve Web entegrasyonu (`cli.py`, `web_server.py`):** CLI'da `.level <seviye>` komutu ile dinamik seviye değişimi desteklendi; Web API tarafına `POST /set-level` endpoint'i eklendi.

### Teknik Borç Kapanışı
- Bu sürümde ayrı bir teknik borç kapanışı kaydı bulunmuyor; odak sürüm farklarının belgelenmesidir.

---

## [v2.10.4] - 2026-03-08
Bu sürümde Web API dokümantasyonu OpenAPI/Swagger standardına yükseltilmiştir.

### ✅ Web API Dokümantasyon İyileştirmeleri
* **OpenAPI Şema Belgelendirmesi (`web_server.py`):** FastAPI `/docs` ve `/redoc` arayüzleri aktif edildi. Kritik API uç noktalarına (`/status`, `/health`, `/sessions`, `/rag/search`, `/rag/add-file`, `/clear`) `summary`, `description` ve `responses` detayları eklendi.

### Teknik Borç Kapanışı
- Bu sürümde ayrı bir teknik borç kapanışı kaydı bulunmuyor; odak sürüm farklarının belgelenmesidir.

---

## [v2.10.3] - 2026-03-08
Bu sürümde test kalite kapıları ve performans baseline ölçümleri CI/test akışına entegre edilmiştir.

### ✅ Test ve Kalite İyileştirmeleri
* **Test Coverage Hedefleri (`run_tests.sh`):** CI süreçleri için `pyproject.toml` kaynaklı `fail_under=99` ratchet baseline ve kritik çekirdek modüller için opt-in `%100` coverage campaign yaklaşımı dokümante edildi.
* **Performans Benchmark (`tests/test_benchmark.py`):** Kritik RAG (ChromaDB, BM25) ve AutoHandle regex yolları için `pytest-benchmark` tabanlı otomatik hız testleri sisteme entegre edildi.

### Teknik Borç Kapanışı
- Bu sürümde ayrı bir teknik borç kapanışı kaydı bulunmuyor; odak sürüm farklarının belgelenmesidir.

---

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

### Teknik Borç Kapanışı
- Bu sürümde ayrı bir teknik borç kapanışı kaydı bulunmuyor; odak sürüm farklarının belgelenmesidir.

---

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

### Teknik Borç Kapanışı
- Bu sürümde ayrı bir teknik borç kapanışı kaydı bulunmuyor; odak sürüm farklarının belgelenmesidir.

---

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

### Teknik Borç Kapanışı
- Bu sürümde ayrı bir teknik borç kapanışı kaydı bulunmuyor; odak sürüm farklarının belgelenmesidir.

---
