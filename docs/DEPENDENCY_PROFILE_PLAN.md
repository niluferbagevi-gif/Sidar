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
3. **Docker/installer koordinasyonu:** Production Dockerfile, installer ve deploy runbook'ları yeni profile
   göre güncellenmeden ana `dependencies` daraltılmaz.
4. **Ana liste daraltma:** Sadece dry-run ve installer doğrulaması geçtikten sonra dev/test araçları ana
   `dependencies` listesinden `dev` extra'ya taşınır.
5. **Güvenlik doğrulaması:** Production profilinde `pip-audit`, import smoke, web boot smoke ve DB migration
   smoke ayrı çalıştırılır; dev/test araçlarının production ortamına taşınmadığı doğrulanır.

## Kabul kriterleri

- `uv sync --all-extras` geliştirici/CI standardı kesintisiz çalışır.
- Production profilinde `pytest`, `ruff`, `mypy`, `pyright`, `bandit`, `safety` ve test double paketleri
  transitif zorunluluk olmadıkça yer almaz.
- Docker/installer/CI dokümanları aynı PR serisinde güncellenir.
- OpenAPI/web boot, migration ve temel agent smoke testleri production profiliyle geçer.
