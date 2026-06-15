# Runtime / Dev-Test Bağımlılık Ayrıştırma Planı

Bu doküman, `pyproject.toml` içindeki mevcut bağımlılık yüzeyini bozmadan uzun vadede
production-minimal paket profiline geçiş planını tanımlar. Mevcut repo standardı korunur:
`uv sync --all-extras` local geliştirme, CI ve ekip paritesi için geçerli ana kurulum komutudur.

## Mevcut durum

- Ana `dependencies` listesi bugün runtime paketleri ile pytest/ruff/mypy/bandit/safety gibi
  geliştirme ve test araçlarını birlikte içerir.
- `dev` extra aynı araçların önemli bir bölümünü ayrıca taşır; bu, eski kurulum davranışları ve
  `uv sync --all-extras` standardı nedeniyle geriye dönük uyumluluk sağlar.
- Bu PR, dependency çözümünü veya installer/CI komutlarını değiştirmez; yalnız plan ve izleme
  metadata'sı ekler.

## Hedef profiller

| Profil | Amaç | İlk içerik hedefi | Not |
|---|---|---|---|
| `runtime` | Sidar çekirdeğinin minimum import/runtime bağımlılıkları | config, FastAPI, DB base, HTTP client, güvenlik, temel RAG olmayan core paketler | Ana `dependencies` uzun vadede buna indirgenir. |
| `dev` | Test/lint/type/security kalite araçları | `pytest`, `pytest-*`, `ruff`, `mypy`, `pyright`, `bandit`, `safety`, type stubs, test doubles | CI ve local kalite kapıları bu profile bağlı kalır. |
| `all` | Mevcut tam geliştirici deneyimi | Tüm provider/integration extras + `dev` | `uv sync --all-extras` sözleşmesi kırılmamalıdır. |
| `production` | Web/API deploy için minimum runtime | `runtime` + `postgres` + `telemetry` (+ gerekli provider seçimi) | Docker/installer ile birlikte tanıtılmalıdır. |

## Envanter taslağı

Bu tablo, **Envanter** fazının başlangıç sınıflandırmasıdır; install/lock davranışını
değiştirmez ve ana `dependencies` listesinden paket taşımaz. Amaç, sonraki PR'larda
CI dry-run, Docker image ve installer/runbook değişiklikleriyle birlikte hangi paketin
hangi profile aday olduğunu açıkça izlemektir.
Her ana dependency için makine-okunur etiketler `pyproject.toml` içindeki
`[tool.sidar.dependency_inventory.labels]` altında tutulur; izin verilen etiketler
`runtime`, `dev`, `provider`, `integration`, `test-double` ve `security-tool` değerleridir.

| Sınıf | Aday paketler / extras | Geçiş notu |
|---|---|---|
| `runtime-core` | `packaging`, `python-dotenv`, `pyyaml`, `httpx`, `pydantic`, `pydantic-settings`, `cachetools`, `redis`, `psutil` | Ana import/config/cache ve HTTP istemci yüzeyi; uzun vadeli `runtime` profilinin çekirdeği. |
| `runtime-web` | `fastapi`, `starlette`, `python-multipart`, `uvicorn[standard]`, `anyio`, `websockets`, `bleach`, `PyJWT`, `cryptography` | Web/API boot, auth ve websocket runtime; production profilinin Web parçası. |
| `runtime-db` | `aiosqlite`, `SQLAlchemy`, `alembic`; `postgres` extra: `asyncpg`, `psycopg2-binary`, `pgvector` | SQLite fallback ana listede kalır; PostgreSQL deploy hedefi `production` profilinde `postgres` extra ile gelir. |
| `runtime-rag-content` | `tiktoken`, `rank-bm25`, `beautifulsoup4`, `nemoguardrails`, `chromadb`, `langchain-*`, `posthog`, `sentence-transformers`; `rag` extra: `torch`, `torchvision` | RAG/content yüzeyi halen ana listede; üretim-minimal split sırasında RAG olmayan Web/API image'dan ayrılması değerlendirilir. |
| `runtime-ops-telemetry` | `requests`, `tenacity`, `opentelemetry-*`; `telemetry` extra: `prometheus-client`, `opentelemetry-*` | Operasyonel HTTP retry ve tracing/exporter paketleri; production profilinde telemetry seçimiyle doğrulanmalı. |
| `optional-provider` | `gemini`, `anthropic`, `openai`, `litellm`, `lora`, `gpu`, `voice` extras | Model sağlayıcıları ve ağır ML/GPU/STT yüzeyi varsayılan production-minimal profile zorunlu olmamalı. |
| `optional-integration` | `PyGithub`, `duckduckgo-search`, `pillow`, `pyttsx3`; extras: `sandbox`, `gui`, `slack`, `browser`, `tools`, `aws`, `jira`, `teams` | Dış servis, browser, GUI ve sandbox entegrasyonları kullanım bazlı extras olarak kalmalı. |
| `dev-quality` | `pytest`, `pytest-*`, `hypothesis`, `respx`, `fakeredis`, `testcontainers`, `ruff`, `mypy`, `pyright`, `pre-commit`, `shellcheck-py`, `types-*`, `bandit`, `safety` | Bugün ana listede bilinçli olarak korunur; production split tamamlanana kadar `uv sync --all-extras` standardını bozmak için taşınmaz. |

## Güvenlik odaklı çözümleme sınırları

- `rag` extra içindeki PyTorch çözümlemesi geçici olarak `torch>=2.4.1,<2.12` ve
  `torchvision>=0.19,<0.27` aralığıyla sınırlandırılmıştır. Bu sınır, daha önce
  `pip-audit` tarafından raporlanan `torch 2.12.0 / CVE-2025-3000` bulgusu için
  açık uçlu resolver davranışını durdurur.
- Mevcut `uv.lock` çözümü `torch 2.11.0` ve `torchvision 0.26.0` seviyesindedir; bu
  nedenle `security/pip-audit-ignores.tsv` içinde aktif `CVE-2025-3000` istisnası
  tutulmaz. Yeni bir lock yenilemesi bu CVE'yi yeniden üretirse istisna eklemek
  yerine önce `<2.12` sınırı ve torch/torchvision eşleşmesi doğrulanmalıdır.
- `uv.lock` yenilemesi ağ/proxy erişimi olan CI veya geliştirici ortamında
  `uv lock --upgrade-package torch --upgrade-package torchvision` ile yapılmalı, ardından
  `uv sync --all-extras` ve `uv run --with pip-audit pip-audit --skip-editable --timeout 30`
  yeniden çalıştırılmalıdır.
- Bu sınır kaldırılmadan önce RAG embedding, Whisper/STT, CPU-only ve GPU/CUDA smoke
  profilleri birlikte doğrulanmalıdır.

## Aşamalı geçiş

1. **Envanter:** Ana `dependencies` içindeki paketleri `runtime`, `dev`, optional integration ve provider
   sınıflarına etiketle. Bu aşamada lock veya install davranışı değişmez.
2. **CI dry-run:** Yeni profil komutlarını ayrı non-blocking job olarak dene; örn. production image için
   `uv sync --frozen --extra production` ancak ana gate yine `uv sync --all-extras` kalır.
   İlk takip işi `.github/workflows/ci.yml` içindeki `production-profile-dry-run` job'ıdır;
   `continue-on-error: true` ile başlar ve production profile olgunlaşana kadar ana CI gate'ini kırmaz.
3. **Docker/installer koordinasyonu:** Production Dockerfile, installer ve deploy runbook'ları yeni profile
   göre güncellenmeden ana `dependencies` daraltılmaz.
4. **Ana liste daraltma:** Sadece dry-run ve installer doğrulaması geçtikten sonra dev/test araçları ana
   `dependencies` listesinden `dev` extra'ya taşınır.
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
job'ı non-blocking kalmalı ve Docker/installer değişiklikleri geçmeden ana `dependencies` listesi daraltılmamalıdır.

## Kabul kriterleri

- `uv sync --all-extras` geliştirici/CI standardı kesintisiz çalışır.
- Production profilinde `pytest`, `ruff`, `mypy`, `pyright`, `bandit`, `safety` ve test double paketleri
  transitif zorunluluk olmadıkça yer almaz.
- Docker/installer/CI dokümanları aynı PR serisinde güncellenir.
- OpenAPI/web boot, migration ve temel agent smoke testleri production profiliyle geçer.
