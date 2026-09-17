
# Sürüm Geçmişi (Changelog)

> **Not:** Bu dosya yalnızca sürümler arası farkları, kısa düzeltme notlarını ve teknik borç kapanışı özetlerini içerir. Ayrıntılı çözüm geçmişi `docs/archive/` altında tutulur. **Madde bütçesi:** Her yeni madde 2-3 cümleyle (sorun + kök neden/çözüm özeti) sınırlı tutulur; kök-neden analizi, reddedilen alternatifler ve test referansları gibi ayrıntılar doğrudan `docs/archive/` altına (sürüm kapanışında `docs/archive/resolved_issues_v3.md`'nin bir sonraki fazına, kapanmamış `[Unreleased]` maddeleri için `docs/archive/unreleased_root_cause_detail.md`'ye) yazılır. Bu bütçe `scripts/ci/check_changelog_entry_budget.py` ile CI'da zorunlu kılınır.

---

## [Unreleased]

> Bu bölümdeki maddelerin tam kök-neden analizi, araştırma süreci ve test referansları için bkz. [`docs/archive/unreleased_root_cause_detail.md`](docs/archive/unreleased_root_cause_detail.md) (2026-09-10 tarihli P3 bulgusu sonrası arşivlendi).

### Düzeltmeler
- **`tests/unit/core/test_rag.py`'deki üç `add_document_from_url` testi, ağ/DNS'i kısıtlı bir geliştirici makinesinde başarısız oluyordu:** Kök neden `_validate_url_safe(resolve_dns=True)`'nin (SSRF koruması) `example.com` için gerçek bir `socket.getaddrinfo()` çağrısı yapması — `respx` yalnızca httpx transport'unu mock'lar, ham DNS'i değil. Komşu testteki mevcut desen izlenerek `rag.socket.getaddrinfo` sabitlendi; artık gerçek ağ/DNS gerektirmiyor.
- **`docs/module-notes/` dokümantasyon borç ratchet'i son 10 modülde sabitti:** `managers/{browser,image_resolver,social_media,youtube}_manager.py` ve `plugins/` paketinin tamamı (6 dosya) için gerçek kaynağı okunarak yazılmış notlar eklendi. Dokümante edilmemiş production modül sayısı 10 → **0**; baseline `--update` ile sıkılaştırıldı, artık geçersiz olan 0-hedefli roadmap boşaltıldı. `test_committed_inventory_roadmap_and_registry_note_are_ratchet_protected` yeni değerlere güncellendi.
- **`detect_gpu()`'nun "GPU Tespiti" adımı, bir operatörün kendi kurulumunda 40+ dakika görünürde donmuş kalıyordu:** Kök neden `detect_pytorch_runtime_cuda_version()`'ın çıplak `uv run python` çağrısı — taze bir checkout'ta bu, gizli bir tam `uv sync`'i (sentence-transformers → torch) tetikliyordu. `uv run --no-sync`'e geçirildi; artık venv boşsa anında (~0.1sn) `ModuleNotFoundError` ile devam ediyor.
- **`docker-compose.yml` 20 servis/690+ satırdan 3 dosyaya bölündü (P3):** GPU profili servisleri `docker-compose.gpu.yml`'e, observability profili servisleri `docker-compose.observability.yml`'e taşındı; üç dosya `-f` ile birleştiriliyor. Installer'ın bare `docker compose` çağrıları ve `.env*` şablonları yeni dosya setini kapsayacak şekilde güncellendi; detay: `docs/archive/unreleased_root_cause_detail.md`.
- **`config.py` 1813 → 1754 satır: `init_telemetry()` `core/config_observability.py`'ye taşındı (P2):** ~95 satırlık OpenTelemetry/FastAPI/HTTPX kurulum mantığı mevcut `core/config_*.py` deseni izlenerek saf bir fonksiyona dönüştürüldü; `Config.init_telemetry` yalnızca canlı `cls.ENABLE_TRACING`/`cls.OTEL_*` değerlerini çözen ~20 satırlık ince bir sarmalayıcı olarak kaldı.
- **`web_server.py` boyut bütçesi eklendi (P2):** Dosyanın "ince sarmalayıcı kalmalı" dokümantasyonunu zorlayan hiçbir mekanizma yoktu ve sessizce 2.628 satıra çıkmıştı. Yeni `scripts/ci/check_web_server_size_baseline.py` + baseline JSON bunu CI'da tek yönlü bir satır bütçesi olarak zorluyor (manuel, `--update` yok).
- **Module-notes dokümantasyon borcu 133'ten 117'ye indirildi (P2, `docs/module-notes/inventory-debt-baseline.json`):** En riskli/en çok kullanılan 16 production modülüne (güvenlik/auth, DLP/HITL, swarm/judge/router) gerçek, dosyaya özgü notlar eklendi; `check_module_notes_inventory.py --update` ile baseline aynı commit'te sıkılaştırıldı.
- **Bandit suppression ratchet'i 15'ten 5'e indirme hedefi kondu; gerçekçi analiz sonucu 8'de sağlam bir zemine oturdu (15 → 8):** 4 dosya daha `core.utils.trusted_subprocess`'e taşındı, yeni `core/utils/trusted_urlopen.py` B310 için aynı deseni uyguladı, iki B615/B105 bulgusu gerçekten düzeltildi. Kalan 8 suppression tek tek incelenip belgelendi (irreducible by design); `skipped_tests` ratchet'i 8'e sıkılaştırıldı.
- **Faz 2 — merkezi subprocess wrapper migrasyonu devam etti (30 → 23):** 6 orta riskli dosya (`managers/code/*`, `system_health.py`, `web/process_lifecycle.py`) `core.utils.trusted_subprocess`'e taşındı; bir `check_output()` çağrısı davranış-koruyan biçimde yeniden yazıldı, gerçek bir mypy-strict regresyonu düzeltildi.
- **Bandit suppression ratchet'ini 15'e indirme hedefi kondu (39 → 30, Faz 1):** Merkezi, denetlenmiş `core/utils/trusted_subprocess.py` (`run_trusted_command()`/`popen_trusted_command()`) oluşturuldu; en düşük riskli 8 dosya buna taşındı, wrapper %100 kapsamla test edildi.
- **Bandit suppression ratchet tam tavanda duruyordu (skipped_tests=40=maximum); `debt_plan.review_order` yalnızca 2 dosyayı kapsıyordu (40 → 39):** İki dosya daha incelendi; `update_install_module_hash_manifest.py`'nin çıplak `"git"` argv[0]'ı `shutil.which("git")` + mutlak yol zorunluluğuna taşınarak gerçek bir B607 boşluğu kapatıldı.
- **Faz 3 — merkezi subprocess wrapper migrasyonu tamamlandı, 15 hedefine ulaşıldı (23 → 15):** En yüksek riskli iki dosya (`web/plugins/sandbox.py`, `managers/code/docker_lifecycle.py`) taşındı; `tools/audit_imports.py`'a sys.path bootstrap eklenerek suppression'ı tamamen kalktı, bir B105 yanlış-pozitifi (mesaj adındaki "TOKEN" kelimesi) yeniden adlandırılarak giderildi. Kalan tek hedef 2027-07-31'e kadar 0.
- **Bağımlılık profili menüsü `dev-full` (`--all-extras`) profilini her zaman "önerilen" gösteriyordu; ~1.5-2GB indirme ağırlığı hakkında uyarı yoktu:** Menüye yaklaşık indirme ağırlığı eklendi; önceki bir denemede ağ zaman aşımı tespit edilirse varsayılan öneri otomatik olarak daha hafif `dev-light`'a çevriliyor.
- **`install_python_deps()`'teki `uv sync` çağrısının retry/backoff'u yoktu, `uv`'nin varsayılan HTTP timeout'u (30sn) hiç ayarlanmıyordu:** `UV_HTTP_TIMEOUT` (varsayılan 120) ve üstel-backoff'lu 3 denemelik bir retry döngüsü eklendi.
- **`sidar_remediate_uv_sync_failure()`, saf bir ağ zaman aşımında bile koşulsuz `uv cache prune` çalıştırıp zaten indirilmiş yüzlerce MB'lık paketleri düşürüyordu:** Yeni `sidar_is_uv_network_timeout_signal()` ağ zaman aşımı imzalarını tespit edip bu durumda cache prune'u atlıyor.
- **`sidar_resume_after_remediation()`, auto-heal resume re-exec'inde seçilen bağımlılık profilini taşımıyordu:** `DEPENDENCY_PROFILE`/`SIDAR_DEPENDENCY_EXTRAS`, resume `exec env` çağrısına diğer resume-kritik değişkenlerle aynı desende eklendi.
- **`Run SAST gates` adımı yeni yayınlanan bir `nltk` CVE'si (`PYSEC-2026-3740`) yüzünden kırmızıydı:** first-party kod hiç `import nltk` etmiyor (mevcut bir önceki istisnayla aynı gerekçe); `security/pip-audit-ignores.tsv`'ye tarihli bir istisna eklendi.
- **`pg-stress` CI job'ı gerçekten çalıştığı her seferde "0 selected" ile başarısız oluyordu — `pg_stress` marker'ını taşıyan hiçbir test yoktu:** Yeni `tests/integration/db/test_pg_connection_pool_stress.py` üç gerçek eşzamanlılık/toparlanma/tutarlılık testi ekliyor; `DATABASE_URL` yoksa nazikçe skip, `CI` set edilmişse fail-closed.
- **`Benchmark compare gate`, `uv.lock`'a dokunan hiçbir PR'da hiçbir seed yoluyla yeşile dönemiyordu (GitHub Actions cache-scope kısıtı):** Erişilebilir kapsamda baseline bulunamadığında artık fail-closed durmuyor; `mode=bootstrap` kendi ölçümünü kaydedip cache'liyor, bir sonraki push gerçek karşılaştırma yapıyor (bu koşuda regresyon karşılaştırması yapılmaz — bilinçli trade-off).
- **`tests/unit/test_bandit_comments.py`'nin repo-genelinde `rglob` taramaları `actions-runner/` dizinini hariç tutmuyordu:** Self-hosted runner kurulu bir repo kökünde bu, üçüncü taraf fixture dosyalarında `UnicodeDecodeError` ile push-öncesi testleri durduruyordu. Üç tarama döngüsünün hariç tutma kümesine `"actions-runner"` eklendi.
- **`npm audit`, `browserslist` paketindeki iki yüksek-önemli açık nedeniyle başarısız oluyordu:** `npm audit fix` ile `browserslist` 4.28.8'e yükseltildi, `package.json`'da değişiklik gerekmedi.
- **`actions-runner/` .gitignore/ruff exclude listelerine hiç eklenmemişti:** Bir operatör bu kurulumu repo kökünde yaptığında `ruff format --check` içindeki kasıtlı-bozuk bir üçüncü-taraf TOML fixture'ı parse edemeyip push'u engelliyordu. İki katmanlı koruma (`.gitignore` + `pyproject.toml` ruff exclude) eklendi.
- **Self-hosted GPU/benchmark job'ları büyük CUDA wheel indirmelerinde tekrarlayan ağ zaman aşımlarıyla başarısız oluyordu:** `uv`'nin varsayılan 30sn HTTP timeout'u bu ölçekteki indirmelere yetmiyordu. `UV_HTTP_TIMEOUT=180` tüm ilgili self-hosted job'lara eklendi.
- **`COMPOSE_PROFILES` hiçbir `.env*.example` şablonunda yoktu, CI'daki env-parity kontrolü kırmızıydı:** Gerçek, kullanıcı yüzeyli bir docker-compose değişkeni olduğu doğrulandı; `.env.development.example`/`.env.advanced.example`'a belgelenmiş şekilde eklendi.
- **Frontend JS bundle bütçesi %94 doluluğa ulaştı:** İncelendi — `budgetWarnRatio=0.9` mekanizması tasarlandığı gibi fail etmeden uyarıyor; kaldırılabilecek gereksiz plugin bulunamadı, bütçe bilinçli olarak büyütülmedi (ratchet disiplini).
- **Parola hash/verify benchmark'ları genel CPU regresyon eşiğine takılıp false-positive üretiyordu:** Yüksek varyanslı dört parola testi yeni `password_benchmark` marker'ıyla izole edilip kendi (daha toleranslı) `BENCHMARK_PASSWORD_COMPARE_FAIL` eşiğiyle koşuluyor.
- **`github_upload.py`, "main"e otomatik geçiş sonrası hiçbir erken çıkış yolunda kullanıcıyı başladığı dala geri döndürmüyordu:** Yeni `switch_back_to_original_branch()` commit/push öncesi tüm erken çıkışlara eklendi; commit-sonrası kalite kapısı hataları kasıtlı olarak dokunulmadı (mevcut kurtarma talimatı korunuyor).
- **`agent/roles/coverage_agent.py`, `dev`-only sınıflandırılmış `defusedxml`'i koşulsuz import ediyordu:** `--no-dev` kurulumlarda tüm `agent.roles` paketinin (coder hariç) kayıt dışı kalmasına yol açıyordu. `defusedxml` çekirdek runtime bağımlılığına taşındı.
- **`test_docker_test_image_is_info_in_development_when_auto_build_is_deferred`, production-readiness ortam sızıntısı yüzünden yerelde kırılıyordu:** Kardeş testte zaten var olan `SIDAR_PRODUCTION_READINESS` delenv izolasyonu bu teste de eklendi.
- **`AGENTS.md`, geniş kapsamlı `uv lock --upgrade` kullanımına karşı açık bir standart taşımıyordu:** Repo'nun zaten örtük olarak izlediği izole `--upgrade-package` deseni artık "Lock güncelleme standardı" olarak açıkça belgelendi.
- **`docs/module-notes/INDEX.md` taşınmış/silinmiş kaynaklara işaret eden bayat bir liste haline gelmişti:** Tüm girdiler gerçek dosya sistemine göre düzeltildi; yeni `scripts/ci/check_module_notes_inventory.py` dört sözleşmeyi (var olma, orphan-yok, borç ratchet'i) CI'da zorunlu kılıyor.
- **`github_upload.py`'nin push-öncesi kalite kapısı, sıradan bir test hatasında bile kullanıcıyı yarım kalmış bir dalda bırakıyordu:** Kapı `run_pre_commit_fast_gate()` (commit öncesi) ve `run_post_commit_integrity_gate()` (commit sonrası) olarak ikiye ayrıldı; ikinci kapı hatasında kurtarma komutları açıkça yazdırılıyor.
- **CI'daki tek kırmızı check (`GPU Inference Required Evidence Gate`) tekrar gündeme geldi:** Kod değil, repository-kontrol-düzlemi (runner/variable) meselesi olduğu doğrulandı; `check_gpu_evidence.sh` artık üç red dalında da Job Summary'ye net bir özet yazıyor.
- **Pin damgalama sonrası `.secrets.baseline` sistemik olarak bayatlıyor, `detect-secrets` kapısını her seferinde kırıyordu:** `stamp_install_manifest_pin_after_commit()` artık pini damgaladıktan sonra baseline'ı otomatik yeniden tarayıp fixup commit'ine dahil ediyor.
- **`install_uv_cli()`'nin `uv self update` çağrısı stderr'i tamamen atıyordu:** apt/pipx/brew ile kurulmuş bir `uv`'de sessizce başarısız olabiliyordu; çıktı artık yakalanıp başarısızlıkta gösteriliyor.
- **`detect_environment()`, WSL1'i de WSL2 sanıyordu:** WSL1 kullanıcıları GPU passthrough kontrollerinin hepsi fail ederken yanıltıcı bir hata görüyordu; "standard" alt-dizgisi ile ayrım eklendi, `SIDAR_OSRELEASE_PATH` test edilebilirlik için eklendi.
- **`RUN_GPU_STRESS`, VRAM'e bakılmaksızın otomatik açılıyor ve belgelenmiyordu:** Etkinleştirme mesajına tespit edilen VRAM ve kapatma talimatı eklendi; `.env.development.example`'a belgelendi.
- **`sync_pytorch_cuda_wheels()`/`verify_torch_cuda()` iki dosyada birebir aynı tanıma sahipti (ölü kopya):** Sessizce farklılaşmış (bir shellcheck yorumu eksik) ölü kopya kaldırıldı, eksik yorum canlı kopyaya taşındı.
- **Bağımlılık profili listesi 4 ayrı yerde elle kopyalanmıştı:** Kanonik `SIDAR_KNOWN_DEPENDENCY_PROFILES` dizisi + yardımcı fonksiyonlar eklendi; dört çağrı yeri aynı listeyi/hata metnini paylaşıyor.
- **`make production-readiness` yerelde `DATABASE_URL parolası POSTGRES_PASSWORD ile senkron değil` hatasıyla patlıyordu:** Kök neden `run_tests.sh`'in sızdırdığı ambient `POSTGRES_PASSWORD` idi; `validate_production_compose.sh`'a savunma amaçlı `unset -v` sanitizasyonu eklendi.
- **`LLM_GPU_MEMORY_FRACTION`/`RAG_GPU_MEMORY_FRACTION` varsayılanları toplamda `GPU_MEMORY_FRACTION`'ı aşıyordu:** Her boot'ta gereksiz runtime normalize/uyarı tetikliyordu; varsayılan formül 65/35 oranını koruyacak şekilde düzeltildi (`config.py` ve `core/config_hardware.py`).
- **`docker-compose.yml`, `ENABLE_TRACING`'i varsayılan `true` yapıyordu; `jaeger` başlamayan profillerde OTLP export hatası boot log'larını kirletiyordu:** Container-seviyesi varsayılan `config.py`'nin kendi `false` varsayılanıyla hizalandı.
- **`npm audit`, `@humanfs/node`'daki bir moderate path-traversal bulgusunu (`audit:high` eşiğinin altında) rapor ediyordu:** `npm audit fix` ile güncellendi, `package.json` değişmedi.
- **Kurulum promptları iki farklı kanaldan yazılıyordu; yavaş fork'lu ortamlarda (WSL2) satır sırası karışabilirdi:** Gerçek pty testiyle doğrulandı; 6 çağrı noktası yeni senkron `tty_notice()`/`&> /dev/tty` desenine taşındı.
- **`test_sync_env_chain_marks_effective_password_drift_warnings_critical`, ambient `REDIS_URL` sızıntısı yüzünden CI'da kırılıyordu:** Kardeş testin deseni izlenerek `REDIS_URL`/`SIDAR_REDIS_URL` delenv'i eklendi.
- **Bağımlılık profili menüsü "developer-full" gösterirken loglar "dev-full" yazıyordu (davranış doğru, isimlendirme kafa karıştırıcı):** Menü ve mesajlar artık her iki adı bir arada gösteriyor.
- **`validate_production_compose.sh`'ın ürettiği disposable secret'lar production'ın zayıf-secret politikasını geçemiyordu:** `secrets.token_urlsafe` + retry tabanlı `random_secret()` eklendi; eksik webhook/federation secret anahtarları da tamamlandı.
- **PR-first upload başarı çıktısı dal push'u ile `main` güncellemesini ayırt etmiyordu:** Başarılı akış artık PR URL'sini gösterip merge sonrası `main`'e geçeceğini açıkça bildiriyor.
- **PR-first uploader `gh` CLI kurulu olmadığında dalı push ettikten sonra duruyordu:** PR oluşturma artık `gh` yoksa doğrulanmış GitHub HTTPS API'ye fail-closed geçiyor.
- **`OLLAMA_NUM_BATCH`, `OLLAMA_CODING_NUM_CTX`'in aksine düşük VRAM'de küçültülmüyordu:** İncelendi — llama.cpp'nin batch/context kısıtları zıt yönde çekiyor, gerçek donanımda doğrulama gerektiriyor; sayısal varsayılanlar değiştirilmeden gerekçe koda yorum olarak eklendi.
- **`OLLAMA_TIMEOUT` üç yerde üç farklı varsayılana sahipti:** `check_ollama()`'nın sağlık probu yanlışlıkla 600sn'lik inference timeout'unu kullanıyordu; özel `OLLAMA_HEALTH_CHECK_TIMEOUT=5` eklendi, ölü kopyalar tek kaynağa birleştirildi.
- **OOM hataları genel geçici hatalarla aynı retry mantığına tabiydi:** Yeni `_is_oom_error()` VRAM tükenmesini retry-dışı sayıp eyleme geçirilebilir bir ipucu ekliyor.
- **RAG embedding GPU→CPU fallback'i kalıcı sanılıyordu (`lru_cache`'e bağlanmıştı):** Teşhis yanlış çıktı — asıl neden `DocumentStore` singleton'ının embedding fonksiyonunu bir kez inşa etmesi; gerçek düzeltim kapsam dışı bırakıldı, kök neden docstring'e not edildi.
- **`core/llm_client.py`/`core/llm_metrics.py`'de senkronize edilmeyen iki ayrı fiyat kataloğu vardı:** Değerler değiştirilmeden ortak `core/llm_pricing.py`'ye taşındı; kasıtlı farklılıkları docstring belgeliyor.
- **`core/llm/ollama.py`'deki 10 forwarding fonksiyonu beş sağlayıcı adaptöründe birebir tekrarlanıyordu:** Tekrar kasıtlı (bağımsız monkeypatch yüzeyi) olduğu için taşınmadı; gerekçe koda yorum olarak eklendi.
- **Ollama servislerinde healthcheck yoktu:** `ollama list` tabanlı bir healthcheck eklendi, dört bağımlı servisin `depends_on`'u `service_healthy`'e geçirildi.
- **`ollama/ollama:latest` compose'daki tek pinlenmemiş imajdı:** `0.32.14`'e pinlendi; Helm chart'ın uyuşmayan redis/pgvector/jaeger pinleri de hizalandı.
- **Observability profilindeki servislerde kaynak limiti yoktu:** `sidar-web`'in kullandığı `cpus`/`mem_limit` deseniyle tüm servislere limit eklendi.
- **`.pre-commit-config.yaml`'da secret-scanning/frontend lint hook'u eksik iddiası:** İncelendi ve doğrulanamadı — önceki bir turda zaten eklenmişti, değişiklik yapılmadı.
- **`check_gpu_evidence.sh`'ın `ENABLE_GPU_BENCH_GATE=false` mesajı istisna varmış gibi yanıltıyordu:** Mesaj artık bunun repository-admin aksiyonu olduğunu ve hiçbir istisnası olmadığını açıkça belirtiyor.
- **`brace-expansion` GHSA istisnası son tarihe yaklaşıyordu:** Script'in beklediği patched sürüm sabiti güncel `1.1.18`'e hizalandı (istisna şu an tetiklenmiyor, gelecekteki reaktivasyon için düzeltildi).
- **`react-markdown` bir majör sürüm geride kalmıştı:** Tek breaking change (`className` kaldırması) DOM-eşdeğeri bir sarmalayıcıyla telafi edilip `10.1.0`'a yükseltildi.
- **`make dev-full`'un GPU stress testlerini sessizce açması kaçırılması kolaydı:** `run_tests.sh`'e erken, göze çarpan bir ön-izleme banner'ı eklendi.
- **`.nvmrc` yalnız majör Node sürümünü pinliyordu, kardeş araçlar tam sürüm pinliydi:** Tutarsızlık giderilip `NODE_VERSION=20.20.2`'ye pinlendi.
- **`install_sidar.sh`'in alt komutları, `uv` diskte kurulu olsa bile PATH tutarsızlığı yüzünden "uv bulunamadı" diyerek güvenlik adımlarını sessizce atlıyordu:** Kök nedenin PATH'in yalnızca `sync-deps` fazında ayarlanması olduğu doğrulandı; `set -Eeuo pipefail`'in hemen ardından tek kaynaktan `export PATH=...` eklendi.

### Refactor
- **`test_plugin_sandbox_integration.py`'nin gerçek-Docker yolunda skip guard'ı yoktu:** Kardeş modülün paylaşılan `tests/_helpers/docker_sandbox.py` sözleşmesi bu modüle de eklendi; asıl güvence hâlâ `make dev-full`'un imajı garanti build etmesi.
- **`CodeManager` LSP facade'ı pure protokol/presentation mantığını taşımaya devam ediyordu:** İlgili mantık `managers/code/lsp.py`'ye taşındı; mevcut private metotlar geriye dönük uyumlu ince delegeler olarak korundu.
- **Frontend TypeScript migrasyonunda kalan 29 untyped dosya test yüzeyiyle sınırlıydı:** `useFormState.test.js` `.test.ts`'e taşındı; envanter ratchet'i 28 untyped/39 typed'a sıkılaştırıldı.
- **Frontend branch coverage %99.77'de üç dal eksikti:** Eksik davranış testleri eklendi, ratchet %100'e yükseltildi.
- **Frontend gzip bundle'ı 170 KB limitine yaklaşırken highlight zinciri ayrı izlenmiyordu:** `SIDAR_HIGHLIGHT_CHUNK_BUDGET_KB=40` bağımsız gate'i eklendi.
- **TypeScript envanter ratchet'i sıkılaştırılırken proje raporu eski değerlerde kalmıştı:** Rapor güncel baseline'a (28/39) eşlendi.
- **Installer frontend QA fixture'ı eski hard-coded E2E metnini bekliyordu:** Fixture yeni `frontend_e2e_scope`/`frontend_e2e_script` alanlarına güncellendi.
- **Docker plugin sandbox açıklaması `.env.example`'ı 50 satır ratchet'inin üzerine çıkarmıştı:** Uzman açıklaması `.env.advanced.example`'a taşındı, minimal şablon 50 satıra döndü.
- **Plugin RPC worker testleri Docker worker'ın execution boundary'sini modellemiyordu:** Test modülü artık `test + in_process` opt-in sözleşmesini açıkça kuruyor; production politikası değişmedi.

### Installer
- **`install_uv_cli()`, farklı sürümlü kurulu bir `uv` bulunca kurulumu doğrudan durduruyordu (self-heal stratejisi yoktu):** `uv self update`/resmi kurulum betiği ile iki otomatik onarım denemesi eklendi; ikisi de başarısız olursa manuel komut gösteriliyor.
- **Kurulum özeti frontend E2E kapsamını sabit `smoke` raporluyordu:** Özet artık `test-summary.json`'daki gerçek alanları okuyor; `dev-full` açıklaması CI-parity iddiasından çıkarıldı.
- **Test gate mesajları local-full ile CI-parity kapsamını karıştırıyordu:** `run_tests.sh` artık doğrulama sınıfını açıkça basıyor; frontend mesajları etkin script'e göre doğru kapsamı gösteriyor.
- **Test env-var yazım hataları sessizce varsayılana düşüyordu:** Yeni `scripts.test_gates.env_schema` bilinen isim yüzeyini tutuyor; yazım hataları varsayılan olarak fail-fast.

### Düzeltmeler
- **`.env.example`'daki `SIDAR_REDIS_URL` parolasız görünüyordu (host+Docker senaryosu):** İncelendi — `resolve_redis_url()` zaten parolayı otomatik ekliyor; yalnızca dokümantasyon netleştirildi.

### Güvenlik
- **Kurulum betiği WSL2'nin deneysel `sparseVhd` özelliğini (Microsoft'un veri bozulması riski nedeniyle varsayılan kapalı tuttuğu) her kurulumda zorla açıyordu:** `05_frontend.sh`'deki `target_sparse_vhd` artık yeni `SIDAR_WSL_SPARSE_VHD` ortam değişkeninden okunuyor, varsayılanı `false`; yalnızca açık opt-in ile etkinleşiyor ve installer riski konsola uyarı olarak basıyor.
- **`--docker-only`/`--runtime-mode=docker` kurulumları host'a gereksiz Ollama kurup 11434 portunda Docker `ollama`/`ollama-gpu` servisiyle çakışabiliyordu:** `ensure_prerequisites()` artık `_ollama_install_step`'i yalnızca tam Docker modu seçilmediğinde çağırıyor; `--docker-only`'de adım atlanıp bilgilendirme mesajı basılıyor.
- **WSL2'de `setup_nvidia_docker()` Linux NVIDIA sürücüsü/`nvidia-ctk runtime configure` kurmaya çalışıp Docker Desktop'ın ayrı motorunun kullanmadığı yanlış `daemon.json`'ı düzenliyordu:** Artık önce `docker run --rm --gpus all ... nvidia-smi` ile passthrough ampirik doğrulanıyor; başarılıysa apt/nvidia-ctk yolu tamamen atlanıyor, değilse net bir hatayla durduruluyor.
- **GPU compose servisleri (`sidar-gpu`/`sidar-web-gpu`) `OLLAMA_URL` fallback'i yanlış `ollama` (CPU) host adını hedefliyordu ve bare `${OLLAMA_URL:-...}` host-odaklı `.env` değeriyle gölgeleniyordu:** `DATABASE_URL` deseniyle aynı, ayrı `SIDAR_CONTAINER_OLLAMA_URL`/`SIDAR_CONTAINER_OLLAMA_GPU_URL` değişkenleri eklendi.
- **Repo `/mnt/c` gibi bir Windows sürücüsüne klonlandığında (WSL2'de yavaş/tutarsız 9p/DrvFs erişimi) hiçbir uyarı verilmiyordu:** Yeni `sidar_warn_if_repo_on_windows_mount()` WSL2'de `SCRIPT_DIR` `/mnt/*` altındaysa uyarıp Linux dosya sistemine yeniden klonlamayı öneriyor (hard-fail değil).
- **Web arayüzü portları (7860/7861) production'da doğrudan ağa açık kalabiliyordu, bind adresi için override yoktu:** Yeni `WEB_BIND_ADDR` (varsayılan `0.0.0.0`, davranış değişmedi) env değişkeni eklendi; production'da `127.0.0.1` + reverse proxy önerilir.
- **`rotate_production_secrets.py`, `POSTGRES_PASSWORD`/`REDIS_PASSWORD`'ü kapsamıyordu; Redis için senkronizasyon aracı da yoktu:** İkisi `ROTATION_KEYS`'e eklendi, `--apply` artık gömülü URL'leri de güncelliyor; yeni `scripts/sync_redis_password.py` eklendi.
- **`prometheus.yml`, `METRICS_TOKEN`'ın istediği bearer-token alanını içermiyordu:** Daha ciddisi, Sidar'ın auth middleware'i zaten tüm scrape isteklerini reddediyordu. Yeni `prometheus-token-init` servisi token'ı yazılabilir bir volume'e yazıyor; `prometheus.yml`'e `bearer_token_file` eklendi.
- **`.pre-commit-config.yaml`'da secret-sızıntı taraması ve frontend lint/typecheck hook'u hiç yoktu:** `detect-secrets` + `frontend-eslint`/`frontend-typecheck` hook'ları eklendi; 254 bilinen false-positive baseline'a alındı.

### Düzeltmeler
- **`Config._autoselect_ollama_coding_ctx_window()`, 8 GB altı VRAM'de hiç küçültme yapmıyordu:** İki yeni kademe (`>=4096`→4096, aksi halde 2048) eklendi.
- **`install_uv_cli()`'nin self-heal'i `uv self update`'i yanlış CLI sözdizimiyle (bayrak yerine pozisyonel argüman) çağırıyordu, hiç çalışmıyordu:** Doğru pozisyonel çağrıya düzeltildi; bash hash-cache teorisi araştırılıp çürütüldü.
- **GPU stres testi mock config yüzünden fiilen concurrency=1'e düşüyor, üretimin VRAM korumasını atlıyordu:** Yeni `_real_ollama_gpu_pool_size()` üretimin kullanacağı adaptif havuz boyutunu hesaplayıp teste geçiriyor.

### Güvenlik
- **`docker-compose.production.yml`, GPU servislerini hiç sertleştirmiyordu; `ports: []` girdileri hiçbir zaman işe yaramıyordu:** Compose'un `!reset []` merge tag'i kullanıldı; `sidar-web-gpu`'ya `sidar-web` ile simetrik sertleştirme eklendi.
- **Postgres/Ollama portları tüm arayüzlere açıktı, yalnız Redis loopback'e bindliydi:** Her ikisi de `127.0.0.1`'e bind edilecek şekilde düzeltildi (production zaten etkilenmiyordu).
- **Production gate hâlâ geliştirme imajını build ediyordu; hardened `Dockerfile.production` hiç devreye girmiyordu:** `sidar-web` servisine `dockerfile: Dockerfile.production` ve doğru `command`/`BASE_IMAGE` eklendi.
- **`github_upload.py` artık PR-first ve rollback lease kontrollüdür:** Doğrudan `main` yerine zaman damgalı dal + PR açılıyor; rollback `--force-with-lease` kullanıyor.
- **Plugin RPC deadline'ı Docker teardown süresinden ayrıldı:** Ayrı worker/cleanup timeout'ları (`SIDAR_PLUGIN_SANDBOX_TIMEOUT`/`_CLEANUP_TIMEOUT`) eklendi.
- **KRİTİK — plugin sandbox izolasyonu, düşürülmüş `net.ipv4.ip_unprivileged_port_start` sysctl'i olan host'larda ayrıcalıklı port bind'ini engellemiyordu:** CI'daki ilk gerçek container-escape testinde canlı yakalandı; `--sysctl=net.ipv4.ip_unprivileged_port_start=1024` eklendi.
- **KRİTİK — plugin RPC worker'ının stdout'u root logging handler'ıyla paylaşıldığından gerçek Docker çağrılarında JSON bozulabiliyordu:** `worker.py` artık stdout'u loglanabilir herhangi bir import'tan önce stderr'e yönlendirip RPC yanıtını ayrı tutuyor.
- **KRİTİK — plugin sandbox container'ı hiçbir gerçek isteği çalıştıramıyordu (in-process execution guard'ı container içinde de reddediyordu):** `_isolation_argv()`'ye yalnızca container'a scope'lu `SIDAR_ENABLE_IN_PROCESS_PLUGINS=1`/`SIDAR_ENV=development` eklendi.
- **Plugin sandbox'ın 256m/64 bellek/pids varsayılanları gerçek bir `BaseAgent` çalıştırmaya yetmiyordu (OOM-kill):** Varsayılanlar 512m/128'e yükseltildi (yalnız plugin sandbox).
- **`_assert_no_orphan_containers`'ın 15sn poll penceresi cgroup OOM-kill senaryosunda da yetersiz kaldı:** Pencere 30sn'ye genişletildi.
- **Aynı kök nedenin üçüncü belirtisi — sabit 10sn RPC timeout'u worker başarıyla tamamlansa bile `docker run`'ın dönüşünü beklemeye yetmiyordu:** `SIDAR_PLUGIN_SANDBOX_TIMEOUT` 30sn'ye, orphan-container poll penceresi 60sn'ye yükseltildi.
- **Dynamic SQL B608 suppression envanteri ratchet olmadan büyüyebiliyordu:** İki elle-yazılmış SQL yeri SQLAlchemy bind-parameter'a taşındı; suppression sayısı 23'ten 20'ye indirildi, ratchet eklendi.
- **Torch CVE incelemesi hedeften önce tamamlandı:** `GHSA-rrmf-rvhw-rf47` için `torch`/`torchvision` sınırları yükseltildi, dated pip-audit istisnası kaldırıldı.
- **GPU production-readiness kontrol düzlemi drift'ini saatlik izlemiyordu:** Watchdog artık `ENABLE_GPU_BENCH_GATE` sözleşmesini de saatlik doğruluyor.
- **Plugin sandbox artık her ortamda (dev/test dahil) Docker'ı varsayılan kullanıyor:** Host process'te çalıştırma yalnız açık çift opt-in ile mümkün; `make plugin-sandbox-security` artık skip'leri fail-closed hataya çeviriyor.
- **Semantic/dataflow SAST yoktu (ne Python ne JS/TS için):** Yeni `.github/workflows/codeql.yml`, `security-extended` sorgu setiyle Python + JS/TS için CodeQL çalıştırıyor.
- **`pip-audit`, `pyasn1` 0.6.3 üzerindeki iki CVE nedeniyle bloke oluyordu:** `pyasn1>=0.6.4` floor pin'i eklendi, lock güncellendi.
- **Repo kökünde `.dockerignore` eksikti — secret dosyaları build context'i üzerinden image katmanlarına sızabiliyordu:** `.env*`/`secrets/`/sertifika uzantıları vb. build context'inden çıkaran `.dockerignore` eklendi.
- **`# nosec B608` kullanımının `core/router.py`/`pgvector.py`'de güvenli olduğu incelemesi doğrulandı:** Ek regresyon testi eklendi; diğer B608 kullanımları farklı ama meşru güvenli desenler kullandığından kapsam dışı bırakıldı.
- **`js-yaml` 4.3.0 üzerindeki CVE-2026-59870 nedeniyle frontend audit gate'i bloke oluyordu:** `overrides.js-yaml` `4.3.1`'e güncellendi; `audit:high` artık temiz.
- **KRİTİK — plugin sandbox'ın production Docker backend'i hiç çalışmıyordu (argv, imajın ENTRYPOINT'i tarafından yutuluyordu):** `--entrypoint=python` eklendi; container-escape matrisinin ilk gerçek çalışması bunu yakaladı.
- **`SEC-PLUGIN-001` — plugin sandbox izolasyonu gerçek bir container'a karşı hiç doğrulanmıyordu:** Yeni 6 testlik `tests/integration/web/test_plugin_sandbox_container_escape.py` matrisi eklendi; `--memory-swap` her üç Docker sandbox yolunda pinlendi.
- **`install_sidar.sh`'in log maskeleme allowlist'inde 5 gerçek secret anahtarı eksikti:** `REDIS_PASSWORD`/`JIRA_API_TOKEN`/`META_GRAPH_API_TOKEN` ve iki tesadüfi-eşleşen anahtar doğru allowlist'e eklendi.

### Düzeltmeler (Fixed)
- **`make dev-full`/`make base-quality-gates`, fresh checkout'ta plugin sandbox integration testini deterministik kırıyordu:** İkisi de artık CI'yı yansıtarak `AUTO_BUILD_DOCKER_TEST_IMAGE=1` ile çalışıyor.
- **`ci-parity` hedefi `TEST_PROFILE=ci` ayarlamıyordu, `dev-full` ile fonksiyonel olarak aynıydı:** `ci-parity` artık `TEST_PROFILE=ci`/`FRONTEND_E2E_NPM_SCRIPT=test:e2e`'yi doğru iletiyor.
- **CI'da yalnızca `test:e2e:smoke` (1 spec) çalışıyordu; 7 panel-özel Playwright spec'i hiç tetiklenmiyordu:** CI artık tam `test:e2e` kullanıyor; bu geçiş iki gerçek, önceden yakalanmamış bug ortaya çıkardı (voice mock getter-only accessor'ı, interruption ack'inin state'i ezmesi) — ikisi de düzeltildi.
- **Bir önceki maddenin yan etkisi: `test_run_tests_summary_uses_phase_specific_backend_statuses` ambient env sızıntısı yüzünden kırıldı:** Test kendi `FRONTEND_E2E_NPM_SCRIPT`'ini artık açıkça set ediyor.
- **`benchmark-baseline-keepalive.yml` kurulduğundan beri hiç çalışmamıştı (yanlış runner + cache key):** `[self-hosted, linux, benchmark]`'a taşındı, gerçek cache-key formatını kullanıyor.
- **SQLite bootstrap şeması ile Alembic migration zinciri arasında otomatik senkron kontrolü yoktu, 9 `server_default` sessizce sapmıştı:** Yeni migration defaults'ları hizaladı; entegrasyon testi artık `nullable`/`default` değerlerini de karşılaştırıyor.
- **Frontend ESLint kapsamı `.js`/`.jsx` ile sınırlıydı; 22 `.tsx` dosyası (a11y dahil) hiç lint edilmiyordu:** `typescript-eslint` + `src/**/*.{ts,tsx}` kural bloğu eklendi.
- **`config.py` importu taze kurulumda `OLLAMA_CODING_NUM_CTX` için boş-string pydantic hatasıyla çöküyordu:** `LLMClientSettings`'e `env_ignore_empty=True` eklendi; auto-tune kontrolü de boş değeri "ayarlanmamış" sayacak şekilde düzeltildi.
- **RAG Doctor kontrolleri, bileşenlerden türetilen güvenli PostgreSQL DSN'ini görmezden gelip yanlış blokaj üretiyordu:** Aggregate kontrol ortak `_resolved_database_urls()` çözücüsüne taşındı.
- **P2 süreç güvenliği somut kapılara bağlandı:** Installer'ın en riskli fazları için BATS senaryoları, GPU CI watchdog + runbook, ve TypeScript kampanyası için ara hedefler eklendi.
- **LLM/RAG VRAM bütçesindeki %80–%100 gri bölge sessizce kabul ediliyordu:** Normalizasyon artık `0.8` hedefini geçtiği anda oranları koruyarak uygulanıyor; başlangıç değerleri güvenli hedefe hizalandı.
- **Self-heal planlama sınırı ayrıştırıldı:** Kaynak snapshot/batch/LLM patch-plan akışı yeni `agent/self_heal/planner.py`'ye taşındı; `SidarAgent` ince delegate metotları koruyor.
- **`core.doctor`'daki `websocket_routes` kontrolü gerçek FastAPI kurulumunda her zaman fail veriyordu (`_IncludedRouter` sarmalaması taranmıyordu):** Yeni `_iter_effective_routes()` bu şekli özyinelemeli dolaşıyor.
- **`database_connectivity` kontrolü geçersiz bir `?ssl=disable` parametresini yanlışlıkla TLS sertifika sorunu sanıyordu:** Yeni `invalid_ssl_query_param` dalı doğru kök nedeni ve auto-fix'i işaret ediyor.
- **`gpu_memory_config` kontrolü GPU'lu makinelerde kendisiyle çelişen bir rapor üretiyordu:** Kontrol artık alanları okumadan önce donanım probunu zorluyor.
- **`redis` kontrolü yalnızca `SIDAR_REDIS_URL` set olan kurulumlarda yanlış uyarı veriyordu:** Kontrol artık gerçek çözücüyle aynı öncelik sırasını (`SIDAR_REDIS_URL` önce) kullanıyor.
- **`database_env` kontrolü, dosya tabanlı auto-fix'in düzeltemeyeceği bir uyarıyı sonsuza dek tekrarlıyordu ("alarm yorgunluğu"):** Kök neden ambient/Docker-enjekte edilmiş bir DATABASE_URL'in Sidar'ın dotenv zincirine ait olmamasıydı; uyarı artık bunu net açıklıyor.
- **Docker sandbox runtime allowlist uyarısı her sandbox çağrısında gereksiz tekrarlanıyordu:** Kontrol yalnızca `runtime` boş olmadığında çalışacak şekilde düzeltildi (davranış değişmedi).
- **GPU, development kurulumunda sessizce devre dışı kalıyordu (`.env.development` `.env`'i eziyordu):** GPU ayarları artık tüm ilgili env dosyalarına yayılıyor.
- **`INSTALL_REMOTE_MODULES` fallback listesi `install_cli.sh`/`install_dispatcher.sh`'ı atlıyordu:** Liste düzeltildi.
- **Frontend node_modules eksikken 3 yeni test `github_upload.py`'nin hızlı push-öncesi kapısını kırıyordu:** Yeni `_skip_unless_frontend_dependencies_installed()` bu testleri fail yerine skip ediyor.

### Dokümantasyon
- **`docs/project-report/02-...` bir çözülmüş güvenlik maddesini açık borç gibi gösteriyordu; §8 satır-sayısı tablosu 5+ aydır güncellenmemişti:** PBKDF2 maddesi "Çözüldü" işaretlendi; tüm tablo gerçek `wc -l` ile yeniden üretildi, var olmayan üç yol düzeltildi.

### Teknik Borç Kapanışı
- **`docs/REFACTOR_PLAN.md`'nin hotspot snapshot'ı bir aylık drift taşıyordu; `SEC-PLUGIN-001`'in hedef tarihi sessizce geçmişti:** Satır sayıları güncellendi; 3 kabul kriteri kod incelemesiyle doğrulanıp işaretlendi, yeni 2026-09-15 ara checkpoint'i eklendi.
- **Bandit suppression ratchet tavanda duruyordu; iki dosyadaki B603/B606 suppression'ları teker teker incelendi:** Üçü de zaten test korumalı ve güvenle kaldırılamıyor; ratchet bilinçli olarak korundu, gerekçe belgelendi.
- **`docs/module-notes/` borcu sıfır azalmayla 174'te sabit duruyordu:** 12 yeni not eklendi, borç 174'ten 133'e indi; roadmap bir sonraki hedefe (2027-02-28/100) güncellendi.
- **Frontend TypeScript ratchet tam sınırda duruyordu (untyped=26=max):** 5 dosya taşındı, iki gerçek tip boşluğu kapatıldı; ratchet 21 untyped/51 typed'a sıkılaştırıldı.
- **4 admin panelinde load/error/refresh state boilerplate'i tekrarlanmıştı:** Yeni `useAsyncStatus` hook'u 3 panele uygulandı; `TenantAdminPanel` kendi abort/debounce akışı nedeniyle bilinçli olarak taşınmadı.
- **`useAsyncStatus`'un kapatmadığı bir sonraki katman (data+mount+reload iskeleti) hâlâ elle kuruluyordu:** Yeni `useAsyncResource` hook'u 3 panele uygulandı.
- **Bundle bütçe kapısı yalnızca React DOM chunk'ına özel tavan koyuyordu; `ChatMarkdownRenderer` izlenmiyordu:** `namedChunkBudgets` genelleştirildi; yeni bağımsız markdown-chunk gate'i ve ayrı `rehype-sidar-highlight` chunk'ı eklendi.
- **Aynı "hata mesajı çıkar" helper'ı 6 dosyada 3 farklı imzayla kopyalanmıştı:** Ortak `src/lib/errors.ts::errorMessage()` tek imzada üçünü de karşılıyor.
- **`config_llm.py`/`config_quality.py`'de aynı metaprogramlama bloğu birebir kopyalanmıştı:** Yeni `core/config_scoped_settings.py::build_scoped_settings_type()` tek yere indirdi.
- **`agent/self_heal/executor.py` coverage'ı %89.58'de kalmıştı:** 4 eksik hata/erken-çıkış dalı için hedefli testler eklendi; dosya artık %100 dal kapsamında.

### Dokümantasyon
- **README'nin Docker test imajı bölümü ikinci bir tüketiciyi (plugin sandbox) hiç anlatmıyordu:** README ve `docs/TESTING.md`'ye çapraz referans eklendi.
- **`docs/TEST_OPTIMIZATION_PLAN.md`, artık geçerli olmayan coverage-omit örnekleri veriyordu:** Güncel `pyproject.toml` omit glob'larıyla düzeltildi.
- **`INTEGRATION_PYTEST_WORKERS`'ın neden sabit 2'ye kilitli olduğu belgelenmemişti:** Paylaşılan PostgreSQL servisi nedeniyle race-condition riski; gerekçe yorum olarak eklendi.
- **Coverage ratchet metrik senkronizasyonu:** %100 günlük baseline olarak commitlendi; ratchet regresyonu engelliyor.
- **Doküman şişkinliği incelemesi (115 markdown dosyası):** Mimarinin zaten kasıtlı/arşivlenmiş olduğu doğrulandı; README'nin depo ağacı diyagramındaki 5 yanlış kök-seviye referansı düzeltildi.
- **`main.py`/`cli.py` isimlendirmesi kafa karıştırıcıydı:** Yeniden adlandırma riskli bulunup yapılmadı; her iki dosyanın docstring'ine açık çapraz referans eklendi.
- **"config.py ve config sprawl" incelemesi (4 alt madde):** Tutarsız `os.getenv` deseni `REFACTOR_PLAN.md`'ye sıradaki adım olarak eklendi; diğer üç alt-iddia önceki turlarda zaten kapatılmış veya doğrulanamadı.
- **"web_server.py — kısmen tamamlanmış plugin marketplace extraction" incelemesi:** Wrapper'ların üretim yoluna bağlı olduğu doğrulandı; silme önerisi `SEC-PLUGIN-001` önceliğiyle çeliştiği için bu turda uygulanmadı, plan'a somut sıradaki-adım eklendi.
- **"core/db/monolith.py şema drift riski" incelemesi:** Risk bu incelemenin erken bir maddesinde zaten kapatılmıştı; doğrulama raporlandı.
- **"core/doctor/__init__.py — sahte checks/ alt paketi" incelemesi:** Bulgu önceki bir turda zaten `REFACTOR_PLAN.md`'ye eklenmişti; eksik kalan tek şey (regresyon assertion'ı) eklendi.
- **"core/ci_remediation.py — güvenlik-kritik allowlist genel planla iç içe" incelemesi:** Hedef modül adı `command_safety.py`'ye netleştirildi; extraction'ın kendisi henüz yapılmadı.
- **"install_sidar.sh + install_modules/ — çift-kaynak hash manifesti" incelemesi (2 alt madde):** Pre-commit hook'u iddiası doğrulanamadı (zaten var); remote-fetch bloğunun ayrı dosyaya çıkarılması zaten planlıydı, nüans eklendi.
- **"run_tests.sh — büyük env-var yüzeyi, yazım hatası koruması yok" incelemesi:** `--help` iddiası doğrulanamadı; şema-doğrulama önerisi somut bir false-positive nedeniyle ertelendi, gerekçe belgelendi.
- **"Benchmark gate — tek nokta arıza riski" incelemesi (3 alt madde):** Keepalive sorunu önceki turda zaten kapatılmıştı; periyodik re-seed ve iki workflow'un birleştirilmesi bu ortamda doğrulanamadığından ertelendi, `docs/CI_REQUIRED_CHECKS.md`'ye follow-up olarak eklendi.
- **"GPU-gated testler; `ENABLE_GPU_TESTS=0` belgelenmemiş" incelemesi:** Tasarım doğru bulundu; override README'ye eklendi.
- **"CodeQL eksik" incelemesi:** Bulgu önceki bir maddede zaten kapatılmıştı; eksik kalan regresyon testi eklendi.
- **"TypeScript migrasyonu — anlatım eski" incelemesi:** Kalan tüm `.js`/`.jsx` dosyalarının test dosyası olduğu doğrulandı; `tsconfig.json` yorumu ve migration doc güncel duruma göre düzeltildi.
- **"ESLint kapsam hatası — a11y kuralları çalışmıyor" incelemesi (P0 işaretlenmişti):** Bulgu bu PR'ın ilk commit'inde zaten kapatılmıştı; eksik kalan regresyon testi eklendi.
- **"CI'da yalnızca smoke E2E çalışıyor" incelemesi:** Bulgu bu incelemenin erken bir maddesinde zaten kapatılmıştı; dangling test-referansı düzeltilip eksik regresyon testi eklendi.

