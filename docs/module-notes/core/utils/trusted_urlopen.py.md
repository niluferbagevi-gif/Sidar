# `core/utils/trusted_urlopen.py` — Merkezi, denetlenmiş urlopen wrapper'ı

- **Kaynak dosya:** `core/utils/trusted_urlopen.py`
- **Not dosyası:** `docs/module-notes/core/utils/trusted_urlopen.py.md`

**Amaç:** Bandit'in B310 ("urllib_urlopen" — izin verilen şemaları denetle)
kuralı, hedef URL ne kadar sabit/güvenilir olursa olsun hemen hemen her
`urllib.request.urlopen` çağrısını işaretler — statik olarak şemanın
`file://`/`ftp://` gibi bir şeye asla dönüşmeyeceğini kanıtlayamıyor.
`core/utils/trusted_subprocess.py` için zaten kurulan aynı desenle
(bkz. o modülün docstring'i), bu modül içsel olarak güvenilir her
HTTP(S) isteğini `urlopen_trusted_request()` üzerinden geçirerek
kaçınılmaz B310 suppression'ını TEK bir denetlenmiş satıra topluyor —
her caller artık kendi `# nosec`'ini taşımıyor.

Trust modeli değişmedi: `request`'in sabit/güvenilir bir origin'i
hedeflediğinden hâlâ tamamen caller sorumlu; bu modül onu doğrulamıyor.
Ekstra bir minimal güvenlik ağı ekliyor: `http`/`https` dışındaki her
şemayı (`UntrustedRequestError` ile) kesin olarak reddediyor.

**Kapsam:** `tests/unit/core/test_trusted_urlopen.py` ile `%100`
kapsam (şema reddi urlopen'a hiç ulaşmadan gerçekleşiyor; mutlu yol
gerçek bir socket açmadan `urllib.request.urlopen`'ı mock'layarak
doğrulanıyor — bu repo'nun `tests/unit/conftest.py`'deki unit-test ağ
korumasına uygun). Taşınan çağrı noktaları: `github_upload.py`'nin
`open_upload_pull_request()` yardımcı fonksiyonu ve
`scripts/install_modules/refresh_remote_checksums.py`'nin
`fetch_remote_bytes()`'i. `scripts/ci/check_gpu_runner_capacity.py` ve
`check_benchmark_runner_capacity.py`'nin B310 site'leri **kasıtlı
olarak taşınmadı** — gerçek CI iş akışları hiç `uv sync` yapmıyor
(yalnızca `actions/checkout` + `actions/setup-python`, proje
bağımlılıkları hiç kurulmuyor); bu betikler bilinçli olarak
bağımlılıksız (yalnızca stdlib) tutuluyor, `core/`'a bir import
bağımlılığı eklemek bu mimari garantiyi bozardı.
