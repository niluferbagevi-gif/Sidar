# Runtime / Dev-Test Bağımlılık Ayrıştırma Planı

Bu doküman, `pyproject.toml` içindeki mevcut bağımlılık yüzeyini bozmadan uzun vadede
production-minimal paket profiline geçiş planını tanımlar. Mevcut repo standardı korunur:
`uv sync --all-extras` local geliştirme, CI ve ekip paritesi için geçerli ana kurulum komutudur.
Bu doküman ile `pyproject.toml` içindeki `[tool.sidar.dependency_profile_plan]` metadata'sı
birlikte güncellenmelidir; docs drift check bu iki kaynağın senkron kaldığını denetler.

## Mevcut durum

- Ana `dependencies` listesi Faz 1 itibarıyla production-minimal geçişin runtime yüzeyidir;
  pytest/ruff/mypy/pyright/bandit/safety gibi geliştirme, LSP ve test araçları runtime listesinden çıkarılmıştır.
- `dev` extra bu araçları taşır; `all` extra da `dev` profilini içerdiği için yerel geliştirme ve
  CI için `uv sync --all-extras` standardı geriye dönük uyumlu kalır.
- Dockerfile/installer production varsayılanları bu PR'da değiştirilmez; production image/runbook
  geçişi ayrı koordinasyon adımı olarak izlenir.

## Hedef profiller

| Profil | Amaç | İlk içerik hedefi | Not |
|---|---|---|---|
| `runtime` | Sidar çekirdeğinin minimum import/runtime bağımlılıkları | config, FastAPI, DB base, HTTP client, güvenlik, temel RAG olmayan core paketler | Ana `dependencies` uzun vadede buna indirgenir. |
| `dev` | Test/lint/type/security kalite araçları | `pytest`, `pytest-*`, `ruff`, `mypy`, `pyright`, `bandit`, `safety`, type stubs, test doubles | CI ve local kalite kapıları bu profile bağlı kalır. |
| `all` | Mevcut tam geliştirici deneyimi | Tüm provider/integration extras + `dev` | `uv sync --all-extras` sözleşmesi kırılmamalıdır. |
| `production` | Web/API deploy için minimum runtime | `runtime` + `postgres` + `telemetry` (+ gerekli provider seçimi) | Faz 1 itibarıyla `sidar[postgres,telemetry]` extra olarak tanımlıdır; Docker/installer varsayılanına geçiş ayrı doğrulanır. |

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
| `runtime-core` | `packaging`, `python-dotenv`, `pyyaml`, `httpx`, `pydantic`, `pydantic-settings`, `cachetools`, `redis`, `psutil` | Ana import/config/cache ve HTTP istemci yüzeyi; uzun vadeli `runtime` profilinin çekirdeği. |
| `migration-candidate` | `httpx2` | Gelecek HTTP client major geçişi için lock altında tutulur; production kodu doğrudan import edemez, önce adapter/RFC kapısı gerekir. |
| `runtime-web` | `fastapi`, `starlette`, `python-multipart`, `uvicorn[standard]`, `anyio`, `websockets`, `bleach`, `PyJWT`, `cryptography` | Web/API boot, auth ve websocket runtime; production profilinin Web parçası. |
| `runtime-db` | `aiosqlite`, `SQLAlchemy`, `alembic`; `postgres` extra: `asyncpg`, `psycopg2-binary`, `pgvector` | SQLite fallback ana listede kalır; PostgreSQL deploy hedefi `production` profilinde `postgres` extra ile gelir. |
| `runtime-rag-content` | `tiktoken`, `rank-bm25`, `beautifulsoup4`, `nemoguardrails`, `chromadb`, `langchain-*`, `posthog`, `sentence-transformers`; `rag` extra: `torch`, `torchvision` | RAG/content yüzeyi halen ana listede; üretim-minimal split sırasında RAG olmayan Web/API image'dan ayrılması değerlendirilir. |
| `runtime-ops-telemetry` | `requests`, `tenacity`, `opentelemetry-*`; `telemetry` extra: `prometheus-client`, `opentelemetry-*` | Operasyonel HTTP retry ve tracing/exporter paketleri; production profilinde telemetry seçimiyle doğrulanmalı. |
| `optional-provider` | `gemini`, `anthropic`, `openai`, `litellm`, `lora`, `gpu`, `voice` extras | Model sağlayıcıları ve ağır ML/GPU/STT yüzeyi varsayılan production-minimal profile zorunlu olmamalı. |
| `optional-integration` | `PyGithub`, `duckduckgo-search`, `pillow`, `pyttsx3`; extras: `sandbox`, `gui`, `slack`, `browser`, `tools`, `aws`, `jira`, `teams` | Dış servis, browser, GUI ve sandbox entegrasyonları kullanım bazlı extras olarak kalmalı. |
| `dev-quality` | `pytest`, `pytest-*`, `hypothesis`, `respx`, `fakeredis`, `testcontainers`, `ruff`, `mypy`, `pyright`, `pre-commit`, `shellcheck-py`, `types-*`, `bandit`, `safety` | Faz 1'de ana runtime listesinden `dev` extra'ya taşındı; `uv sync --all-extras` standardı bu araçları kurmaya devam eder. Pyright LSP reviewer diagnostics için dev/all veya `uv tool install pyright` yoluyla sağlanır, production profile'a girmez. |


## HTTP client migration policy (`httpx` → `httpx2`)

Mevcut kod tabanında production ve test modülleri doğrudan `httpx` API'sini kullanır;
`httpx2` henüz hiçbir runtime modülün import yüzeyi değildir. Bu nedenle `httpx2`,
`pyproject.toml` içinde `migration-candidate` etiketiyle tutulur ve runtime sahipliği
`httpx` üzerinde kalır.

Geçiş kapıları:

1. **Adapter PR:** `core/http_client.py` benzeri tek bir facade eklenmeden production
   modüllerinde `import httpx2` yapılmaz. Facade; timeout, streaming, retryable hata
   sınıfları, OpenTelemetry instrumentation ve test-double davranışını `httpx` ile
   aynı sözleşmede sunmalıdır.
2. **Dual-run smoke:** LLM provider çağrıları, RAG URL ingest, integration manager'lar
   ve web/API test client kullanımları `SIDAR_HTTP_CLIENT_BACKEND=httpx|httpx2` ile
   aynı test matrisinden geçmeden varsayılan backend değiştirilemez.
3. **Lock ve telemetry onayı:** `uv lock --upgrade-package httpx --upgrade-package httpx2`
   sonrası `opentelemetry-instrumentation-httpx` uyumluluğu doğrulanmalı; httpx2 için
   eşdeğer instrumentation yoksa adapter span'leri uygulama içinde üretmelidir.
4. **Final cleanup:** `httpx2` production backend olduktan sonra eski `httpx` bağımlılığı
   yalnız test/compat ihtiyacı varsa extra'ya taşınır; aksi halde runtime listesinden çıkarılır.

Bu politika, iki HTTP client paketinin aynı anda bulunmasını bilinçli bir geçiş durumu
olarak sınırlar ve hangi modülün hangi paketi kullanacağı belirsizliğini engeller.

## Güvenlik odaklı çözümleme sınırları

- `rag` extra içindeki PyTorch çözümlemesi geçici olarak `torch>=2.4.1,<2.12` ve
  `torchvision>=0.19,<0.27` aralığıyla sınırlandırılmıştır. Bu sınır, daha önce
  `pip-audit` tarafından raporlanan `torch 2.12.0 / CVE-2025-3000` bulgusu için
  açık uçlu resolver davranışını durdurur.
- Mevcut `uv.lock` çözümü `torch 2.11.0` ve `torchvision 0.26.0` seviyesindedir;
  `security/pip-audit-ignores.tsv` içindeki aktif `GHSA-rrmf-rvhw-rf47` / `CVE-2025-3000`
  istisnası bu lock penceresi için tarihlidir. Yeni bir lock yenilemesi farklı torch/torchvision
  çözümü üretirse istisnayı uzatmadan önce `<2.12` sınırı ve upstream fix durumu tekrar doğrulanmalıdır.
- `uv.lock` yenilemesi ağ/proxy erişimi olan CI veya geliştirici ortamında
  `uv lock --upgrade-package torch --upgrade-package torchvision` ile yapılmalı, ardından
  `uv sync --all-extras` ve `uv run --with pip-audit pip-audit --skip-editable --timeout 30`
  yeniden çalıştırılmalıdır.
- `security/pip-audit-ignores.tsv` içindeki her istisna `expires` alanı taşır ve
  `scripts/pip_audit_ignore_args.py` tarafından `run_tests.sh` ile GitHub Actions security audit
  adımında okunur. Süresi dolan istisnalar `pip-audit` komutuna aktarılmaz; script fail-closed
  döner ve kalite kapısını kırar. Mevcut `GHSA-rrmf-rvhw-rf47` / `CVE-2025-3000` torch istisnası
  `2026-09-15` tarihinde sona erer; `tests/unit/scripts/test_pip_audit_ignore_args.py` bu tarihten
  sonraki günün fail ettiğini doğrulayarak expiry takibini korur.
- `uv.lock` Faz 1'de Linux deployment/CI hedefiyle sınırlanmıştır (`[tool.uv].environments = ["sys_platform == 'linux'"]`).
  Bu sınır, production-minimal lock çözümünden macOS/Windows GUI bağımlılıklarını ve platforma özel PyObjC/Win32
  paketlerini çıkarır; macOS/Windows installer desteği ayrı profile matrisiyle geri eklenmelidir.
- Bu sınır kaldırılmadan önce RAG embedding, Whisper/STT, CPU-only ve GPU/CUDA smoke
  profilleri birlikte doğrulanmalıdır.

## Aşamalı geçiş

1. **Envanter + Faz 1 dev split:** Ana `dependencies` içindeki runtime paketleri ile `dev` extra içindeki
   kalite araçlarını `runtime`, `dev`, optional integration ve provider sınıflarına etiketle. Dev/test
   araçları ana runtime listesinden çıkarılmıştır; `uv sync --all-extras` davranışı korunur.
2. **CI dry-run:** Yeni profil komutlarını ayrı non-blocking job olarak dene; örn. production image için
   `uv sync --frozen --extra production` ancak ana gate yine `uv sync --all-extras` kalır.
   İlk takip işi `.github/workflows/ci.yml` içindeki `production-profile-dry-run` job'ıdır;
   `continue-on-error: true` ile başlar ve production profile olgunlaşana kadar ana CI gate'ini kırmaz.
3. **Docker/installer koordinasyonu:** Production Dockerfile, installer ve deploy runbook'ları yeni profile
   göre güncellenmeden varsayılan production install akışı değiştirilmez.
4. **Production varsayılanlarını daraltma (P2 structural hardening):** Dev/test araçları Faz 1'de `dev`
   extra'ya taşındı; production profili `sidar[postgres,telemetry]` ile dev araçlarını ve Pyright LSP yükünü dışarıda tutar.
   Dockerfile, installer ve deployment varsayılanları ancak dry-run ve smoke doğrulamaları geçtikten sonra
   production profile yönlendirilir.
5. **Güvenlik doğrulaması:** Production profilinde `pip-audit`, import smoke, web boot smoke ve DB migration
   smoke ayrı çalıştırılır; dev/test araçlarının production ortamına taşınmadığı doğrulanır.

## Dockerfile / installer geçiş PR kapsamı

Bu doküman Dockerfile veya installer davranışını bu aşamada değiştirmez. Production profile geçişi
ayrı bir PR olarak ele alınmalı ve aşağıdaki dosyaları aynı değişiklik serisinde koordine etmelidir:

| Alan | Mevcut sözleşme | Ayrı PR hedefi | Gerekli doğrulama |
|---|---|---|---|
| `Dockerfile` | Build aşamaları hâlâ `uv sync --frozen --all-extras --extra dev` kullanır. | Production image için `uv sync --frozen --extra production` denemesini ayrı stage/arg ile tanıt; dev araçlarını kaldırmadan önce dry-run sonuçlarını raporla. | Image build dry-run, web boot smoke, OpenAPI metadata smoke, import smoke. |
| `install_sidar.sh` | Yerel/CI paritesi için `uv sync --frozen --all-extras` ana kurulum akışıdır. | `--dependency-profile=all|production` veya eşdeğer env override tasarla; varsayılan `all` kalmalı. | Online/offline installer smoke, `--ci` bundle smoke, pyright/self-heal dev bağımlılığı kontrolü. |
| `scripts/install_modules/utils/python_env.sh` | Modüler installer yolu `uv sync --frozen --all-extras --extra dev` ile dev araçlarını garanti eder. | Profile-aware sync arg builder ekle; production seçilse bile dev-only kontrollerin bilinçli atlandığını raporla. | Shellcheck, installer module tests, production profile dry-run. |
| Runbook / docs | `uv sync --all-extras` geliştirme standardı olarak korunur. | Production profile komutlarını Docker/installer runbook'larına ekle; rollback olarak `uv sync --all-extras` yolunu belgelemeyi sürdür. | Doküman testleri ve release checklist güncellemesi. |

Ayrı PR kabul kriteri: `uv sync --all-extras` geliştirici standardı kırılmamalı, `production-profile-dry-run`
job'ı non-blocking kalmalı ve Docker/installer production varsayılanları production profile'a ancak smoke/dry-run
sonuçları raporlandıktan sonra geçirilmelidir.

## Kabul kriterleri

- `uv sync --all-extras` geliştirici/CI standardı kesintisiz çalışır.
- Production profilinde `pytest`, `ruff`, `mypy`, `pyright`, `bandit`, `safety` ve test double paketleri
  transitif zorunluluk olmadıkça yer almaz.
- Docker/installer/CI dokümanları aynı PR serisinde güncellenir.
- OpenAPI/web boot, migration ve temel agent smoke testleri production profiliyle geçer.
