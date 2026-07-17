# Runtime / Dev-Test Bağımlılık Ayrıştırma Planı

Bu doküman, `pyproject.toml` içindeki mevcut bağımlılık yüzeyini bozmadan uzun vadede
production-minimal paket profiline geçiş planını tanımlar. Mevcut repo standardı korunur:
`uv sync --all-extras` developer-full profili için kurulum standardıdır; normal etkileşimli installer varsayılanı ve önerisi `developer-full` / `dev-full` profilidir. `dev-light` hızlı yerel kurulum için bilinçli seçilebilen hafif profildir.
Bu doküman ile `pyproject.toml` içindeki `[tool.sidar.dependency_profile_plan]` metadata'sı
birlikte güncellenmelidir; docs drift check bu iki kaynağın senkron kaldığını denetler.

## Mevcut durum

- Ana `dependencies` listesi Faz 1 itibarıyla production-minimal geçişin runtime yüzeyidir;
  pytest/ruff/mypy/pyright/bandit/safety gibi geliştirme, LSP ve test araçları runtime listesinden çıkarılmıştır.
- `dev` extra bu araçları taşır; `all` extra da `dev` profilini içerdiği için yerel geliştirme ve
  CI için `uv sync --all-extras` standardı geriye dönük uyumlu kalır.
- Faz 1 kapanışında production-minimal yüzey artık somut artifact'lere bağlandı:
  `production` / `production-minimal` extras (artık farklı kapsamlarla), `scripts/export_production_requirements.sh`
  üreticisi ve `Dockerfile.production` no-dev image yolu aynı sözleşmeyi kullanır.

## Hedef profiller

| Profil | Amaç | İlk içerik hedefi | Not |
|---|---|---|---|
| `runtime` | Sidar çekirdeğinin minimum import/runtime bağımlılıkları | config, FastAPI, DB base, HTTP client, güvenlik, temel RAG olmayan core paketler | Ana `dependencies` uzun vadede buna indirgenir. |
| `dev` | Test/lint/type/security kalite araçları | `pytest`, `pytest-*`, `ruff`, `mypy`, `pyright`, `bandit`, `safety`, type stubs, test doubles | CI ve local kalite kapıları bu profile bağlı kalır. |
| `dev-light` | Hızlı yerel geliştirici kurulumu | `postgres` + `dev` | Bilinçli seçilen hızlı profil; provider/browser/voice/GPU gibi ağır extras kapsam dışıdır. |
| `developer-full` | Varsayılan tam geliştirici/CI deneyimi | Tüm provider/integration extras + `dev` | Önerilen installer varsayılanıdır; `uv sync --all-extras` sözleşmesini uygular. |
| `dev-gpu` | GPU/RAG gerekli yerel geliştirici kurulumu | `postgres` + `dev` + `rag` + `gpu` | CUDA remediation sırasında `dev-light` kapsamını tüm provider/browser/voice extras yerine yalnız RAG/GPU yüzeyine genişleten convenience profildir. |
| `gpu-runtime` | Dar no-dev RAG/GPU runtime | `rag` + `gpu` | Production veya minimal profilde GPU wheel onarımı gerektiğinde dev/test/provider extras kurmadan torch/RAG bağımlılıklarını çözer. |
| `production` | Web/API deploy için gözlemlenebilirlik dahil runtime | `runtime` + `postgres` + `telemetry` (+ gerekli provider seçimi) | `uv export --extra production --no-dev` ve `Dockerfile.production` tarafından kullanılan deploy profili. |
| `production-minimal` | Telemetry dahil etmeden en dar no-dev Web/API smoke yüzeyi | `sidar[postgres]` | CI dry-run ve hızlı production-minimal import smoke için kullanılır; telemetry isteyen deploy `production` profilini seçmelidir. |

### Planlanan ayrıştırma grupları

`pyproject.toml` içindeki `[tool.sidar.dependency_profile_plan].planned_profile_groups`
alanı, mevcut install davranışını değiştirmeden uzun vadeli ayrıştırma hedeflerini listeler:
`base`, `web`, `rag`, `multimodal`, `dev`, `test` ve `gpu`. Bu alan yalnızca drift
check ve planlama metadata'sıdır; `uv sync --all-extras` geliştirme standardı korunur.

## Envanter taslağı

Bu tablo, **Envanter + Faz 1 dev split** sınıflandırmasıdır; runtime/dev install davranışını
`uv sync --all-extras` açısından değiştirmez. Ana runtime
listesinden dev/test araçları çıkarılmış olsa da bu paketler `dev` extra içinde korunur.
Amaç, sonraki PR'larda CI dry-run, Docker image ve installer/runbook değişiklikleriyle birlikte
hangi paketin hangi profile aday olduğunu açıkça izlemektir.
Ana runtime dependencies ve `dev` extra adayları için makine-okunur etiketler `pyproject.toml`
içindeki `[tool.sidar.dependency_inventory.labels]` altında tutulur; izin verilen etiketler
`runtime`, `dev`, `provider`, `integration`, `test-double`, `security-tool` ve
`migration-candidate` değerleridir.

| Sınıf | Aday paketler / extras | Geçiş notu |
|---|---|---|
| `runtime-core` | `packaging`, `python-dotenv`, `pyyaml`, `httpx`, `pydantic`, `pydantic-settings`, `cachetools`, `redis`, `psutil` | Ana import/config/cache ve tek HTTP istemci yüzeyi; uzun vadeli `runtime` profilinin çekirdeği. |
| `migration-candidate` | Yok (2026-06-25 itibarıyla `httpx2` adaylığı kapatıldı) | Yeni HTTP client adayları önce adapter/RFC ve dual-run test kapısından geçmeden runtime dependency listesine eklenmez. |
| `runtime-web` | `fastapi`, `starlette`, `python-multipart`, `uvicorn[standard]`, `anyio`, `websockets`, `bleach`, `PyJWT`, `cryptography` | Web/API boot, auth ve websocket runtime; production profilinin Web parçası. |
| `runtime-db` | `aiosqlite`, `SQLAlchemy`, `alembic`; `postgres` extra: `asyncpg`, `psycopg2-binary`, `pgvector` | SQLite fallback ana listede kalır; PostgreSQL deploy hedefi `production` profilinde `postgres` extra ile gelir. |
| `runtime-rag-content` | `tiktoken`, `rank-bm25`, `beautifulsoup4`, `nemoguardrails`, `chromadb`, `langchain-*`, `posthog`, `sentence-transformers`; `rag` extra: `torch`, `torchvision` | RAG/content yüzeyi halen ana listede; üretim-minimal split sırasında RAG olmayan Web/API image'dan ayrılması değerlendirilir. |
| `runtime-ops-telemetry` | `requests`, `tenacity`, `opentelemetry-*`; `telemetry` extra: `prometheus-client`, `opentelemetry-*` | Operasyonel HTTP retry ve tracing/exporter paketleri; production profilinde telemetry seçimiyle doğrulanmalı. |
| `optional-provider` | `gemini`, `anthropic`, `openai`, `litellm`, `lora`, `gpu`, `voice` extras | Model sağlayıcıları ve ağır ML/GPU/STT yüzeyi varsayılan production-minimal profile zorunlu olmamalı. |
| `optional-integration` | `PyGithub`, `duckduckgo-search`, `pillow`, `pyttsx3`; extras: `sandbox`, `gui`, `slack`, `browser`, `tools`, `aws`, `jira`, `teams` | Dış servis, browser, GUI ve sandbox entegrasyonları kullanım bazlı extras olarak kalmalı. |
| `dev-quality` | `pytest`, `pytest-*`, `hypothesis`, `respx`, `fakeredis`, `testcontainers`, `ruff`, `mypy`, `pyright`, `pre-commit`, `shellcheck-py`, `types-*`, `bandit`, `safety` | Faz 1'de ana runtime listesinden `dev` extra'ya taşındı; `uv sync --all-extras` standardı bu araçları kurmaya devam eder. Pyright LSP reviewer diagnostics için dev/all veya `uv tool install pyright` yoluyla sağlanır, production profile'a girmez. |
| `dev-light` | `postgres` + `dev` | Hızlı PR/local kontrolleri için voice/browser/GPU gibi sistem bağımlılığı gerektiren extras'ı dışarıda bırakır; hızlı yerel profilidir. Komut: `uv sync --frozen --extra dev-light`. |


## HTTP client standardization policy (`httpx` only)

Mevcut kod tabanında production ve test modülleri doğrudan `httpx` API'sini kullanır.
Önceki `httpx2` migration-candidate bağımlılığı 2026-06-25 tarihinde kapatıldı ve
runtime dependency graph'ından çıkarıldı; böylece tek desteklenen HTTP client yüzeyi
`httpx` olarak netleşti. Production modüllerinde `import httpx2` yapılmaz.

## Otomatik bağımlılık güncelleme kapısı

`.github/dependabot.yml`, sıkı pinlenen bağımlılık yüzeyleri için haftalık Dependabot
PR'ları açar. Kapsam; `uv`/`uv.lock`, `web_ui_react` npm lockfile'ı, GitHub
Actions, Dockerfile image tag'leri ve `docker-compose.yml` image tag'leridir. PR'lar
`dependencies` etiketiyle ve ekosistem bazlı gruplarla gelir; major güncellemeler
Dependabot'un ayrı PR davranışına bırakılarak reviewer/QA değerlendirmesinden geçer.

Yeni bir HTTP client adayının tekrar değerlendirilmesi için kapılar:

1. **Adapter PR:** `core/http_client.py` benzeri tek bir facade eklenmeden production
   modüllerinde alternatif client import edilmez. Facade; timeout, streaming, retryable hata
   sınıfları, OpenTelemetry instrumentation ve test-double davranışını `httpx` ile
   aynı sözleşmede sunmalıdır.
2. **Dual-run smoke:** LLM provider çağrıları, RAG URL ingest, integration manager'lar
   ve web/API test client kullanımları `SIDAR_HTTP_CLIENT_BACKEND=httpx|candidate` ile
   aynı test matrisinden geçmeden varsayılan backend değiştirilemez.
3. **Lock ve telemetry onayı:** `uv lock --upgrade-package httpx` ve aday paket lock yenilemesi
   sonrası `opentelemetry-instrumentation-httpx` veya eşdeğer adapter span'leri doğrulanmalıdır.
4. **Final cleanup:** Aday production backend olursa eski client yalnız test/compat ihtiyacı varsa
   extra'ya taşınır; aksi halde runtime listesinden çıkarılır.

Bu politika, aynı anda iki HTTP client paketinin belirsiz biçimde runtime'a girmesini
engeller ve dependency graph'ı küçük tutar.

## NeMo Guardrails minor pin policy

`nemoguardrails` runtime bağımlılığı `>=0.22.0,<0.23.0` aralığında tutulur.
0.22 sürümü lock dosyasında doğrulanmış mevcut API yüzeyidir; yeni minor/major
geçişlerinde `SecurityManager` guardrails adapter sözleşmesi,
`tests/quality/test_nemoguardrails_contract.py` kalite testi ve agent/swarm/core LLM
doğrudan import guard testleri yeniden çalıştırılmadan aralık genişletilmemelidir.
Guardrails API kullanımı ajan ya da LLM sağlayıcı katmanına yayılmamalı, merkezi
olarak `managers/security.py` üzerinden izole kalmalıdır.

## PostHog major cap policy

`posthog<6.0.0` üst sınırı doğrudan ürün kodu kullanımından değil, ChromaDB 0.5.x'in
telemetry client bağımlılığından kaynaklanır. Chroma/RAG telemetry smoke matrisi
PostHog v6 ile doğrulanmadan bu sınır kaldırılmamalıdır. Doğrudan Sidar kodunda
PostHog import'u eklenirse dependency label'ı `runtime-ops-telemetry` altında yeniden
sınıflandırılmalı ve production-minimal profil etkisi ayrı PR'da değerlendirilmelidir.

## Güvenlik odaklı çözümleme sınırları

> **Aktif takip durumu (2026-07-16):** `GHSA-rrmf-rvhw-rf47` / `CVE-2025-3000`
> torch istisnası hâlâ `status=watch` durumundadır; review tarihi `2026-08-15`,
> sert bitiş tarihi `2026-09-15` olarak korunur. 2026-07-16 kontrolünde upstream
> advisory verisi hâlâ `last_affected=2.12.0` ve `patched_versions=none` gösterdiği
> için bu PR yeni bir lock yenilemesi yapmaz; yapılacak iş, hatırlatıcı/runbook ile
> upgrade denemesini zamanında çalıştırmak ve istisna süresi dolmadan sonucu kayıt
> altına almaktır.

- `rag` extra içindeki PyTorch çözümlemesi geçici olarak `torch>=2.4.1,<2.12` ve
  `torchvision>=0.19,<0.27` aralığıyla sınırlandırılmıştır. Bu sınır, daha önce
  `pip-audit` tarafından raporlanan `torch 2.12.0 / CVE-2025-3000` bulgusu için
  açık uçlu resolver davranışını durdurur.
- Mevcut `uv.lock` çözümü `torch 2.11.0` ve `torchvision 0.26.0` seviyesindedir;
  `security/pip-audit-ignores.tsv` içindeki aktif `GHSA-rrmf-rvhw-rf47` / `CVE-2025-3000`
  istisnası bu lock penceresi için `status=watch` olarak tarihlidir. `2026-08-15` hedefli ara
  kontrolde upstream patch durumu yeniden denenmeli; yeni bir lock yenilemesi farklı torch/torchvision
  çözümü üretirse istisnayı uzatmadan önce `<2.12` sınırı ve upstream fix durumu tekrar doğrulanmalıdır.
  Calendar reminder: `docs/reminders/torch-cve-review-2026-08-15.ics`; makine-okunur takip metadata
  `pyproject.toml` içindeki `[tool.sidar.dependency_profile_plan.torch_upgrade_reminder]` bloğundadır.
  Operasyonel upgrade/runbook adımları `docs/runbooks/torch-cve-upgrade.md` altında tutulur.
- `uv.lock` yenilemesi ağ/proxy erişimi olan CI veya geliştirici ortamında
  `uv lock --upgrade-package torch --upgrade-package torchvision` ile yapılmalı, ardından
  `uv sync --all-extras` ve `uv run --with pip-audit pip-audit --skip-editable --timeout 30`
  yeniden çalıştırılmalıdır.
- `torch` transitive bağımlılığı olarak gelen `setuptools` çözümü, `PYSEC-2026-3447`
  için ignore eklenmeden `83.0.0` ve üstüne zorlanır. `pyproject.toml` build-system alt sınırı
  `setuptools>=83.0.0` tutar; `[tool.uv].override-dependencies` aynı güvenlik tabanını lock
  çözümünde korur.
- `security/pip-audit-ignores.tsv` içindeki her istisna `expires` alanı taşır ve
  `scripts/pip_audit_ignore_args.py` tarafından `run_tests.sh` ile GitHub Actions security audit
  adımında okunur. Süresi dolan istisnalar `pip-audit` komutuna aktarılmaz; script fail-closed
  döner ve kalite kapısını kırar. Mevcut `GHSA-rrmf-rvhw-rf47` / `CVE-2025-3000` torch istisnası
  `2026-09-15` tarihinde sona erer; `tests/unit/scripts/test_pip_audit_ignore_args.py` bu tarihten
  sonraki günün fail ettiğini doğrulayarak expiry takibini korur.
- Yeni suppress/ignore listeleri aynı standardı izlemelidir: her kayıt makine-okunur
  `expires` veya `next_review` tarihi, paket/bulgu kimliği, owner/runbook referansı ve dar kapsamlı
  gerekçe taşımalı; süresi dolan kayıtlar fail-closed davranışla kalite kapısından düşmelidir.
- `uv.lock` Faz 1'de Linux deployment/CI hedefiyle sınırlanmıştır (`[tool.uv].environments = ["sys_platform == 'linux'"]`).
  Bu sınır, production-minimal lock çözümünden macOS/Windows GUI bağımlılıklarını ve platforma özel PyObjC/Win32
  paketlerini çıkarır; macOS/Windows installer desteği ayrı profile matrisiyle geri eklenmelidir.
- Bu sınır kaldırılmadan önce RAG embedding, Whisper/STT, CPU-only ve GPU/CUDA smoke
  profilleri birlikte doğrulanmalıdır.

## Installer profil seçimi ve production-minimal takip kapısı

Installer artık çalışma modu seçiminden sonra bağımlılık profilini de çözer. Etkileşimli
normal kurulum varsayılanı ve önerisi `developer-full` / `dev-full` profilidir; hızlı yerel kurulum gerekiyorsa
`dev-light` bilinçli seçilebilir. Tam test/CI veya `--production-readiness` akışı da `developer-full` / `dev-full` profilini kullanarak
`uv sync --frozen --all-extras` sözleşmesini korur. Kullanıcı menüsü:

1. `dev-light` — hızlı yerel geliştirici kurulumu.
2. `developer-full` / `dev-full` — önerilen varsayılan; tüm extras ve tam CI/test paritesi.
3. `dev-gpu` — geliştirici + RAG/GPU runtime; provider/browser/voice extras yok.
4. `production-minimal` — dar no-dev runtime.
5. `production` — runtime + postgres + telemetry.
6. `gpu-runtime` — dar no-dev RAG/GPU runtime.
7. `custom` — `SIDAR_DEPENDENCY_EXTRAS=dev,openai,postgres` gibi özel provider/extra seçimi.

Etkileşimsiz normal kurulum `dev-full` seçer; `RUN_CI_FULL_VALIDATION=true` /
`--production-readiness` ise otomatik olarak `dev-full` seçer.

Installer tarafında varsayılan normal profil `dev-full` / `developer-full` olarak görünürdür (`uv sync --frozen --all-extras`). `dev-light` (`uv sync --frozen --extra dev-light`) hızlı yerel geliştirme için opt-in profildir. Desteklenen gerçek CLI profil değerleri `dev-light`, `dev-full`, `dev-gpu`, `gpu-runtime`, `production`, `production-minimal` ve `custom` değerleridir; eski `all` varsayılanı yeni installer sözleşmesi değildir. Dar runtime
yüzeyi doğrulaması için opt-in komut `--production-minimal` veya
`--dependency-profile=production-minimal` değeridir; bu yol dev/test araçlarını ve
Pyright LSP yükünü kurmaz. Production-minimal artık varsayılan installer davranışı
değil, ancak CI/release tarafında gerçek runtime kanıtı üreten blocking bir doğrulama
kapısıdır.

Takip kapıları `pyproject.toml` içindeki
`[tool.sidar.dependency_profile_plan.production_minimal_runtime_validation]` ve
`[tool.sidar.dependency_profile_plan.installer_profile_visibility]` bloklarında
makine-okunur tutulur. CI job'ı `production-profile-dry-run` adı geriye dönük
required-check uyumluluğu için korunur, fakat içerik olarak release-blocking runtime
validation kapısıdır ve `continue-on-error` olmadan çalışır. Production-minimal
varsayılan installer davranışına ancak bu blocking kanıtlar düzenli olarak temiz
kaldığında terfi edebilir:

1. `SIDAR_DEPENDENCY_PROFILE=production-minimal ./install_sidar.sh sync-deps --skip-models --skip-smoke-test`
   komutu `--ci --no-interaction` ile lock değiştirmeden geçer ve
   `artifacts/production-minimal/installer-sync.log` olarak saklanır.
2. Web/API boot smoke `web.app_factory.create_app(register_handlers=False)` ile FastAPI
   kabuğunu ayağa kaldırır ve `artifacts/production-minimal/web-boot-smoke.log`
   artifact'ini üretir.
3. DB migration smoke, izole SQLite URL'siyle `uv run --no-sync alembic upgrade head`
   çalıştırır ve `artifacts/production-minimal/db-migration-smoke.log` çıktısını
   release kanıtına ekler.
4. CI her koşulda `production-minimal-runtime-evidence` artifact'ini upload eder;
   `runtime-evidence.json` installer sync, web boot ve DB migration loglarının varlığını
   makine-okunur şekilde taşır.
5. RAG/GPU/voice/browser gibi ağır extras production-minimal profile alınmaz.
   `tests/unit/test_dependency_profile_plan.py::test_production_minimal_excludes_heavy_optional_extras`
   bu sınırı pyproject metadata'sı üzerinden korur.
6. Release/merge için ayrı production-readiness gate'i yine çalışır:
   `TEST_PROFILE=ci RUN_BENCHMARKS=required RUN_FRONTEND_E2E=1 SIDAR_PRODUCTION_READINESS=1 bash run_tests.sh --stage all`.

## Ruff docstring / ASYNC borç kapatma takibi

> **Aktif takip durumu (2026-07-16):** kapanış hedefi `2026-09-30` olarak
> değişmeden kalır. Bu hedef, yeni veya anlamlı şekilde değişen public API'lerde
> docstring ekleme varsayımını ve `ASYNC240` debt ratchet'ini genişletmeme
> kuralını takip eder.

`pyproject.toml` içindeki `[tool.sidar.ruff_debt]` bloğu docstring (`D*`) ve
`ASYNC240` ignore'larının kapanış tarihini `2026-09-30` olarak taşır. Bu tarihe kadar
planlanan doğrulama komutları:

```bash
uv run ruff check . --select D,ASYNC
uv run python scripts/ci/check_ruff_debt_baseline.py
uv run ruff check .
```

Yeni veya anlamlı şekilde değişen public API'lerde Google-style docstring eklemek,
yeni async I/O yollarında blocking pathlib metadata çağrılarını büyütmemek ve yeni kodda
100 karakter satır sınırına uymak zorunludur; ignore listesi yeni borç eklemek için
genişletilmemelidir. CI, mevcut E501 toplamını `e501_debt_baseline`, D200-D417 ve
ASYNC240 sayımlarını ise `docstring_async_debt_baseline` ratchet sınırıyla
karşılaştırır. Yeni veya anlamlı düzenlenen kod bu baseline'ları artırırsa
`scripts/ci/check_ruff_debt_baseline.py` fail-closed davranır. Ölçülen sayı
baseline'ın altına düştüğünde de komut fail-closed olur ve operatörden
`uv run python scripts/ci/check_ruff_debt_baseline.py --update` ile committed
baseline'ı `min(current, baseline)` değerine indirmesini ister; geçici raporlama
için `--allow-stale-baseline` kullanılabilir fakat CI standardı değildir.

## Aşamalı geçiş

1. **Envanter + Faz 1 dev split:** Ana `dependencies` içindeki runtime paketleri ile `dev` extra içindeki
   kalite araçlarını `runtime`, `dev`, optional integration ve provider sınıflarına etiketle. Dev/test
   araçları ana runtime listesinden çıkarılmıştır; `uv sync --all-extras` davranışı korunur.
2. **CI dry-run:** Yeni profil komutlarını ayrı zorunlu job olarak dene; örn. production image için
   `uv sync --frozen --extra production --no-dev`, minimal profil için `--extra production-minimal --no-dev`.
   `.github/workflows/ci.yml` içindeki `production-profile-dry-run` job'ı artık production-minimal
   profilini ana CI kalite kapısının parçası olarak doğrular; `continue-on-error` kullanılmamalıdır.
3. **Docker/installer koordinasyonu:** `Dockerfile.production` yeni no-dev profile'ı kullanır; ana
   `Dockerfile` ve installer varsayılanları local/CI paritesi için `uv sync --all-extras` kalır.
4. **Production varsayılanlarını daraltma (P2 structural hardening):** Dev/test araçları Faz 1'de `dev`
   extra'ya taşındı; production profili `sidar[postgres,telemetry]`, production-minimal profili ise `sidar[postgres]` ile dev araçlarını ve Pyright LSP yükünü dışarıda tutar.
   Dockerfile, installer ve deployment varsayılanları ancak dry-run ve smoke doğrulamaları geçtikten sonra
   production profile yönlendirilir.
5. **Güvenlik doğrulaması:** Production-minimal profilinde `pip-audit`, import smoke, web boot smoke ve DB migration
   smoke ayrı çalıştırılır; dev/test araçlarının production ortamına taşınmadığı doğrulanır.

## Dockerfile / installer geçiş PR kapsamı

Faz 1 kapanışında production-minimal profile için somut üretim artifact'leri eklenmiştir.
Bu doküman Dockerfile veya installer davranışını bu aşamada değiştirmez; varsayılan production install akışı değiştirilmez.
Varsayılan developer/installer davranışı değişmeden kalır; no-dev production yolu bilinçli
olarak ayrı Dockerfile ve requirements üreticisi üzerinden çalışır:

| Alan | Mevcut sözleşme | Ayrı PR hedefi | Gerekli doğrulama |
|---|---|---|---|
| `Dockerfile` | Build aşamaları hâlâ `uv sync --frozen --all-extras --extra dev` kullanır. | Developer/full image standardını korur; production-minimal için `Dockerfile.production` kullanılır. | Mevcut image build dry-run ve local/CI parity smoke. |
| `Dockerfile.production` | Yeni no-dev production image yolu. | `uv sync --frozen --extra production --no-dev` ile dev/test araçlarını image dışında tutar. | `docker build -f Dockerfile.production ...`, web boot smoke, OpenAPI metadata smoke, import smoke. |
| `scripts/export_production_requirements.sh` | Yeni requirements üreticisi. | `uv export --frozen --extra production --no-dev --no-editable --no-emit-project` ile `requirements-production.txt` üretir. | Export dry-run ve dev/test paket yokluğu kontrolü. |
| `install_sidar.sh` | Normal varsayılan `dev-full`, hızlı opt-in için `dev-light`, tam CI/production-readiness için `dev-full`, GPU remediation için `dev-gpu`/`gpu-runtime` profilleri desteklenir. | Production-minimal ve GPU runtime kapılarını CI artifact'lerine bağlayarak drift görünürlüğünü koru. | Online/offline installer smoke, `--ci` bundle smoke, GPU profile sync smoke, pyright/self-heal dev bağımlılığı kontrolü. |
| `scripts/install_modules/utils/python_env.sh` | Profile-aware sync arg builder `dev-light`, `dev-full`, `dev-gpu`, `gpu-runtime`, `production`, `production-minimal` ve `custom` profillerini üretir. | GPU remediation ve runtime import guidance çıktılarının seçili profil sözleşmesini bozmadığını koru. | Shellcheck, installer module tests, production/GPU profile dry-run. |
| Runbook / docs | `uv sync --all-extras` geliştirme standardı olarak korunur. | Production profile komutlarını Docker/installer runbook'larına ekle; rollback olarak `uv sync --all-extras` yolunu belgelemeyi sürdür. | Doküman testleri ve release checklist güncellemesi. |

Faz 1 kapanış kabul kriteri: `uv sync --all-extras` geliştirici standardı kırılmamalı,
`production-profile-dry-run` job'ı blocking kalmalı, `Dockerfile.production`
`--no-dev` kurulum yapmalı ve installer production varsayılanları ancak smoke/dry-run
sonuçları raporlandıktan sonra profile-aware akışa geçirilmelidir.

## Kabul kriterleri

- `uv sync --all-extras` geliştirici/CI standardı kesintisiz çalışır.
- Production profilinde `pytest`, `ruff`, `mypy`, `pyright`, `bandit`, `safety` ve test double paketleri
  transitif zorunluluk olmadıkça yer almaz.
- Docker/installer/CI dokümanları aynı PR serisinde güncellenir.
- OpenAPI/web boot, migration ve temel agent smoke testleri production profiliyle geçer.
