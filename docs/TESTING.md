# Test çalıştırma rehberi

Sidar'da iki farklı test akışı vardır:

## Log nasıl okunur?

Kurulum veya `run_tests.sh` çıktısındaki sarı `RELEASE KAPSAMI EKSİK` /
`summary-code=10` uyarısı tek başına test hatası değildir; genellikle local
`dev-full` veya development `--stage all` koşusunun geçtiğini, fakat
`SIDAR_PRODUCTION_READINESS=1` ile production-readiness gate'in çalıştırılmadığını
gösterir. Bu durumda geliştirici ortamı sağlıklı olabilir, ancak release/merge için
aşağıdaki kanonik kapı ayrıca geçmelidir: `make production-readiness`.

## Hızlı tekil test / debug

Tek bir test fonksiyonunu veya küçük bir dosya grubunu incelerken doğrudan pytest
kullanın. Coverage gate bu akışta varsayılan olarak çalışmaz; böylece fonksiyonel
olarak geçen tekil testler toplam repo coverage düşük çıktığı için yanıltıcı şekilde
başarısız görünmez.

```bash
uv run pytest tests/unit/core/test_rag.py::test_fetch_pgvector_returns_empty_when_query_embedding_empty -q
```

Geçici olarak coverage eklenecekse ve gate istenmiyorsa açıkça `--no-cov` verilebilir:

```bash
uv run pytest tests/unit/core/test_rag.py::test_fetch_pgvector_returns_empty_when_query_embedding_empty -q --no-cov
```

## Kalite kapısı / coverage doğrulaması

Merge/PR öncesi ana doğrulama yolu `run_tests.sh` betiğidir. Coverage raporları ve
`pyproject.toml` içindeki `[tool.coverage.*]` ayarları ve ratchet edilmiş `[tool.coverage.report].fail_under` tabanlı kontrol bu betik tarafından yönetilir. Güncel release öncesi local/CI baseline `%99`'dur; `%100` coverage hedefi yalnız campaign/strict opt-in profiline aittir.

```bash
./run_tests.sh
```

CI profilinde coverage eşiği daha sıkı çalıştırılabilir:

```bash
CI=true TEST_PROFILE=ci ./run_tests.sh
```

`--stage integration` (veya `smoke`/`e2e`) gibi kısmi bir stage tek başına
çalıştırıldığında, testlerin kendisi geçse bile repo genelindeki `fail_under`
eşiği uygulanmaz; bu kısmi kapsam repo genelini temsil etmediği için sahte bir
coverage başarısızlığı üretmez. Global coverage kalite kapısı yalnızca
`--stage all` (varsayılan), `--stage backend` veya `--stage unit` çalıştığında
uygulanır:

Kurulum betiğinin development/local varsayılanı da bu ayrımı izler: hızlı smoke ve
kurulum doğrulaması otomatik yapılır, ancak frontend kalite kapısı ve `--stage all`
kullanıcı/operatör opt-in'i olmadan başlangıçta çalıştırılmaz. Kurulum logunda
frontend stage'in atlandığını görmek normaldir; bu durumda manuel doğrulama komutu
`RUN_FRONTEND_E2E=1 bash run_tests.sh --stage frontend` veya tam doğrulama komutu
`RUN_BENCHMARKS=required RUN_FRONTEND_E2E=1 bash run_tests.sh --stage all` olmalıdır.

Coverage yüzdesi yalnız tüm ilgili test fazları geçtiğinde kalite kapısı olarak
geçerli kabul edilir. `run_tests.sh`, pytest/BATS/security gibi backend fazlarından
biri başarısızsa final `coverage report --fail-under=...` adımını ve ratchet
güncellemesini atlar; bu yüzden örneğin backend `%99+` ve frontend `%99+` görünse
bile başarısız test düzeltilmeden coverage sonucu merge/PR kanıtı sayılmamalıdır.

```bash
./run_tests.sh --stage integration   # 47/47 geçebilir; global coverage gate atlanır
./run_tests.sh --stage all           # global coverage fail-under eşiği burada uygulanır
```

## Terminoloji standardı

Tüm test dokümantasyonu, installer özetleri ve CI mesajları aşağıdaki isimleri aynı anlamda kullanır:

- **smoke = hızlı sağlık kontrolü.** Kısa boot/import/servis/migration sinyalidir; full QA,
  coverage veya merge/release kanıtı değildir.
- **dev-full = local tam doğrulama.** `make dev-full` ya da geliştirme profilli
  `RUN_BENCHMARKS=required RUN_FRONTEND_E2E=1 bash run_tests.sh --stage all` komutudur;
  local ortam sağlığını doğrular, production-ready kabulü değildir.
- **production-readiness = merge/release kapısı.** `make production-readiness` ya da
  kanonik `TEST_PROFILE=ci ... SIDAR_PRODUCTION_READINESS=1` komutudur; release/merge için
  zorunlu kalite kapısıdır.

## Production readiness zorunlu ayrımı

Kurulum veya lokal geliştirme logunda **“dev-full geçti”** ya da **“Development full validation geçti”** görmek
release/merge onayı anlamına gelmez. Bu mesaj yalnız yerel geliştirme ortamının sağlıklı
olduğunu gösterir: bağımlılıklar, smoke/integration kapsamı, frontend kontrolleri ve
benchmark koşusu geliştirme profiliyle başarılı olabilir. Release, merge veya dağıtım
öncesinde ayrıca **production readiness** kapısı çalıştırılmalı ve geçmelidir.

Zorunlu ayrım:

- **smoke = hızlı sağlık kontrolü.** Hızlı kurulum/runtime sinyalidir; tam QA değildir.
- **dev-full = local tam doğrulama.** Kod yazma, test geliştirme ve hata ayıklama için
  güçlü sinyaldir; tek başına production-ready kanıtı değildir.
- **production-readiness = merge/release kapısı.** CI profili, benchmark karşılaştırması,
  frontend E2E ve `SIDAR_PRODUCTION_READINESS=1` davranışı birlikte doğrulanmadan
  sürüm/merge kabulü yapılmamalıdır.
- **Benchmark baseline yoksa önce seed workflow çalıştırılır.** `.benchmarks/*_baseline.json`
  restore edilemiyorsa production-readiness gate'i baseline üretmez; GitHub Actions →
  **CI** → **Run workflow** → `seed_benchmark_baseline=true` ile cache/artifact seed
  edildikten sonra gate yeniden koşulur.

Release/merge için öne çıkarılan kanonik kapı:

```bash
TEST_PROFILE=ci RUN_BENCHMARKS=required RUN_FRONTEND_E2E=1 SIDAR_PRODUCTION_READINESS=1 bash run_tests.sh --stage all
```

Aynı sözleşme `Makefile` içinde `production-readiness` hedefiyle sabitlenmiştir;
operatörler isterse doğrudan `make production-readiness` çalıştırabilir.

## Make hedefleriyle CI/local komut paritesi

Komut karmaşasını azaltmak için sık kullanılan kalite kapıları `Makefile`
hedefleriyle sabitlendi. Bu hedefler CI'daki `run_tests.sh` davranışıyla aynı
sözleşmeyi kullanır ve hangi kapının production readiness sayıldığını açıkça
gösterir:

```bash
make dev-full              # Geliştirici tam doğrulaması + local frontend bundle budget.
make ci-parity             # dev-full ile aynı local/CI parite kısayolu.
make benchmark-seed        # Lokal benchmark baseline bootstrap/seed yardımcısı.
make production-readiness  # CI profili + benchmark + frontend e2e + SIDAR_PRODUCTION_READINESS.
make frontend-gate         # Frontend lint/typecheck/coverage/e2e kalite kapısı.
make backend-integration   # Backend integration stage'i; global coverage gate uygulanmaz.
```

`make production-readiness` hedefi bilinçli olarak şu kanonik komutu çalıştırır:

```bash
TEST_PROFILE=ci RUN_BENCHMARKS=required RUN_FRONTEND_E2E=1 SIDAR_PRODUCTION_READINESS=1 bash run_tests.sh --stage all
```

CI tarafında karşılaştırılabilirlik için `artifacts/test-summary.json`,
`coverage.json`, `coverage.xml`, `htmlcov/`, frontend coverage çıktıları ve
benchmark JSON dosyaları artifact olarak yüklenir. Backend pytest fazları ayrıca
aşağıdaki JUnit çıktılarıyla unit ve integration/smoke/e2e sonuçlarını ayrı ayrı
izlenebilir hale getirir:

`artifacts/test-summary.json` içindeki `installer` nesnesi installer bootstrap
telemetrisini de taşır: bundle/local/raw fallback modu, raw fallback ile indirilen
modül sayısı, toplam remote modül denemesi, HTTP 429 retry sayısı, cache hit sayısı
ve kullanılan mirror/base URL. Bu alanlar özellikle GitHub raw throttling veya mirror
problemlerini CI/test özetinden geriye dönük incelemek için kullanılır.

Backend pytest JUnit çıktıları:

- `artifacts/pytest/backend-unit.xml`
- `artifacts/pytest/backend-integration-smoke-e2e.xml`

Böylece lokal log ile CI raporu aynı özet/coverage/benchmark/JUnit dosyaları
üzerinden kıyaslanabilir.

## Örnek başarılı local doğrulama çıktısı nasıl okunur?

Aşağıdaki özet, gerçek kurulum loglarında görülen başarılı **development/local**
doğrulamaya benzeyen temsilî bir çıktıdır. Önemli nokta: yeşil test sonuçları
local ortamın sağlıklı olduğunu gösterir; sarı release uyarısı ise beklenen bir
durumdur ve hata değildir.

```text
✅ Smoke testler başarıyla geçti.
✅ Entegrasyon testleri başarıyla geçti (run_tests.sh --stage integration).
✅ Frontend kalite kapısı başarıyla geçti (run_tests.sh --stage frontend).
✅ Final coverage quality gate geçti (eşik: 99).
✅ Benchmark JSON raporu oluşturuldu: artifacts/benchmark/benchmark.json
✅ Development full validation başarıyla tamamlandı.
⚠️ RELEASE KAPSAMI EKSİK [summary-code=10]: stage all çalıştı; ancak
   SIDAR_PRODUCTION_READINESS=1 / TEST_PROFILE=ci profili aktif olmadığı için
   bu sonuç production-readiness sayılmaz.
Production readiness için:
   TEST_PROFILE=ci RUN_BENCHMARKS=required RUN_FRONTEND_E2E=1 \
   SIDAR_PRODUCTION_READINESS=1 bash run_tests.sh --stage all
```

Bu çıktıyı şu şekilde yorumlayın:

- `✅ Smoke`, `✅ Integration`, `✅ Frontend`, `✅ Coverage` ve `✅ Benchmark`
  satırları ilgili local/dev kalite kapılarının geçtiğini gösterir.
- `⚠️ RELEASE KAPSAMI EKSİK [summary-code=10]` satırı **beklenen bir uyarıdır**:
  local `--stage all` koşusu başarılı olsa bile release/merge kapısı sayılmaz.
- `Frontend bundle budget atlandı` uyarısı doğrudan `bash run_tests.sh --stage all`
  local profilinde normaldir; Makefile üzerinden `make dev-full` veya `make ci-parity`
  çalıştırıldığında bundle budget kapısı varsayılan olarak açıktır. Geçici olarak
  kapatmak için `FRONTEND_BUNDLE_BUDGET_LOCAL_FULL=0 make dev-full` kullanın.
- İlk lokal benchmark koşusunda `seeded_not_compared` veya “baseline sonradan
  oluşturuldu” mesajı görmek normaldir. CI/production-readiness tarafında baseline
  restore edilemezse bu durum normalleştirilmez; gate fail-closed davranır.
- `production_ready=false`, `validation_class=development_full` veya
  `release_blocking=true` değerleri `artifacts/test-summary.json` içinde görülürse
  bu, local doğrulamanın başarılı ama release için henüz yeterli olmadığını anlatır.

Local başarıdan release onayına geçmek için tek kanonik komut:

```bash
make production-readiness
```

## CI branch protection / required checks

GitHub repository settings dosya içinde doğrulanamaz; ancak merge güvenliği için branch
protection altında en az şu CI job'ları required check olmalıdır:

- `test` — normal CI yolunda benchmark baseline restore edilir, `make production-readiness`
  çalışır ve `scripts/ci/validate_test_summary.py --mode release` ile
  `artifacts/test-summary.json` release modunda doğrulanır.
- `Installer manifest and smoke gate` (`installer-smoke` job'ı) — installer manifest/hash
  drift'i, raw installer smoke ve kritik kurulum zinciri kontrollerini merge öncesi zorunlu
  yapar.

Repo metadata veya ayarlarda auto-merge ileride açılırsa, bu iki required check ve
production-readiness doğrulaması zorunlu olmadan auto-merge etkinleştirilmemelidir.
Benchmark baseline missing nedeniyle `test` job'ı kırılırsa PR açıklamasında bu dokümandaki
bootstrap runbook'una link verin ve seed workflow tamamlanmadan merge onayı vermeyin.

## CI benchmark baseline cache boşsa ne yapılır?

> **Kısa cevap:** GitHub Actions → **CI** → **Run workflow** →
> `seed_benchmark_baseline=true` seçeneğini çalıştırın; `benchmark-baseline-seed`
> artifact/cache oluştuktan sonra normal CI veya production-readiness gate'ini tekrar
> koşun. İlk/boş cache durumunda gated CI'ın baseline üretmeden kırılması beklenen
> fail-closed davranıştır.

CI `make production-readiness` adımında benchmark karşılaştırmasını fail-closed çalıştırır:
`BENCHMARK_COMPARE_REQUIRED=1`, `BENCHMARK_ENFORCE_COMPARE=1` ve
`BENCHMARK_COMPARE_FAIL=mean:10%`. Bu yüzden `.benchmarks` altında
`*_baseline.json` bulunamazsa kalite kapısı bilinçli olarak başarısız olur. Bu durum
çoğu zaman testlerin bozuk olduğu anlamına gelmez; yeni branch, temiz cache veya cache
retention süresi dolduğu için karşılaştırma baseline'ı bulunamamış olabilir.

Baseline'ı tekrar seed etmek için önerilen güvenli prosedür:

1. GitHub Actions → **CI** workflow'unu elle çalıştırın (`workflow_dispatch`).
2. `seed_benchmark_baseline` girdisini `true` seçin. Bu özel job production-readiness
   kapısını çalıştırmaz; yalnız `tests/performance` benchmarklarını
   `--benchmark-save=baseline` ile koşar.
3. Job sonunda iki kaynak oluşur:
   - Actions cache: `benchmark-baseline-<OS>-py311-<branch>-<run_id>` anahtarıyla
     `.benchmarks/` dizini kaydedilir. Normal CI restore adımı branch, `main`,
     `master` ve genel prefix sırasıyla bu cache'i arar.
   - Artifact: `benchmark-baseline-seed`, `.benchmarks/` dizinini ve
     `artifacts/benchmark/benchmark.json` dosyasını içerir.
4. Normal CI'ı yeniden çalıştırın. `Restore benchmark baseline cache` adımı cache'i
   bulursa `Resolve benchmark baseline gate mode` adımı compare gate'i etkinleştirir.
5. Cache/artifact seed tamamlandıktan sonra production readiness gate'ini tekrar koşun:
   `make production-readiness` veya kanonik
   `TEST_PROFILE=ci RUN_BENCHMARKS=required RUN_FRONTEND_E2E=1 SIDAR_PRODUCTION_READINESS=1 bash run_tests.sh --stage all`.

Cache restore hâlâ boşsa artifact tabanlı manuel geri yükleme prosedürü:

```bash
# GitHub Actions'tan benchmark-baseline-seed artifact'ini indirdikten sonra:
unzip benchmark-baseline-seed.zip -d /tmp/sidar-benchmark-baseline
mkdir -p .benchmarks
cp -a /tmp/sidar-benchmark-baseline/.benchmarks/. .benchmarks/
find .benchmarks -type f -name '*_baseline.json' -print
```

Ardından lokal doğrulama veya yeni cache seed'i için:

```bash
BENCHMARK_COMPARE_REQUIRED=1 BENCHMARK_ENFORCE_COMPARE=1 RUN_BENCHMARKS=required bash run_tests.sh --stage all
```

> Not: CI'daki gated run baseline üretmez; sadece restore edilmiş ve gözden geçirilmiş
> `.benchmarks/*_baseline.json` dosyalarıyla karşılaştırır. İlk kurulum/temiz cache
> bootstrap'ı yalnız `seed_benchmark_baseline=true` workflow_dispatch job'ı üzerinden
> yapılmalıdır.

## Voice extra / PyAudio sistem bağımlılığı

`pyproject.toml` içindeki `voice` extra grubu `pyaudio` içerir. `pyaudio`
tekerleği her platformda hazır gelmeyebildiği için `uv sync --all-extras` veya
`uv sync --extra voice` sırasında PortAudio geliştirme başlıklarına ihtiyaç
duyabilir. Bu bağımlılık platform marker ile gizlenmez; Linux/macOS/yerel CI
hatalarının çoğu eksik sistem header'ından kaynaklandığı için güvenli çözüm
`uv sync` öncesinde sistem ön koşulunu kurmaktır.

Python bağımlılıklarını senkronlamadan önce kullandığınız platforma uygun
PortAudio geliştirme paketini kurun:

```bash
# Debian/Ubuntu
sudo apt-get update
sudo apt-get install -y portaudio19-dev

# Fedora/RHEL
sudo dnf install -y portaudio-devel

# Arch Linux
sudo pacman -S --needed portaudio

# openSUSE/SLES
sudo zypper install portaudio19-devel

# macOS/Homebrew
brew install portaudio

uv sync --all-extras
```

### Geliştirici ön koşulu

```bash
bash scripts/install_ci_system_deps.sh   # portaudio, shellcheck, bats
uv sync --frozen --all-extras
# veya aynı sıralamayı Make hedefiyle çalıştırmak için:
make deps-full
```

Hızlı PR kontrollerinde voice/browser/GPU gibi sistem bağımlılıkları gerekmiyorsa
`uv sync --frozen --extra dev-light` veya `make deps-dev-light` sistemi başlık paketlerine ihtiyaç duymadan
`postgres` + `dev` araçlarını kuran hafif profildir.


### Linter komut yönlendirmesi

`ruff` yalnız Python dosyaları için kullanılmalıdır; `run_tests.sh` gibi shell
script'lerini parse etmeye çalışması proje hatası değildir. Shell script kapsamı
ShellCheck ile doğrulanır. Bu nedenle bu dosya kümesi için doğru hızlı komutlar:

```bash
uv run ruff check tests/unit/scripts/test_run_tests_quality_gate.py
uv run shellcheck --severity=warning -x run_tests.sh
```

Repo geneli shell doğrulaması gerektiğinde `make lint-shell`, installer modülleri
için daha dar doğrulama gerektiğinde `make installer-shellcheck` kullanılmalıdır.

> **Pydantic ve pytest warning filtresi:** `pydantic` ile
> `pydantic-settings` Sidar için runtime bağımlılığıdır; konfigürasyon, araç
> şemaları ve web request doğrulamalarında kullanılır. Pytest tarafında Pydantic
> v2 geçiş uyarıları filtrelenirken artık
> `ignore::pydantic.warnings.PydanticDeprecatedSince20` gibi sınıf import eden
> bir kategori kullanılmaz; `ignore::DeprecationWarning:pydantic.*` modül
> filtresi kullanılır. Böylece eksik/yarım kurulumlarda pytest config aşamasında
> pydantic import etmeye çalışıp erken düşmez; suite `tests/conftest.py` içindeki
> `uv sync --all-extras` yönlendirmesine kadar ulaşır.

Repo CI akışı Debian/Ubuntu runner'larda bu ön koşulu
`scripts/install_ci_system_deps.sh` üzerinden kurar. Aynı script apt, dnf, zypper,
pacman ve Homebrew ortamlarında eşdeğer paket adlarını kullanır; eksikleri yalnız
raporlamak için `--check` modu çalıştırılabilir. Yerel ortamlarda CI ile aynı
sırayı kullanın:

> **Kısa ömürlü bulut çalışma alanları:** BATS'i her oturum başlangıcında zorunlu
> kurmak gerekmez; PR/CI akışı shell testlerini otomatik çalıştırır ve JUnit
> raporunu artifact olarak saklar. Bulut oturumunda tekil shell senaryosunu elle
> doğrulamak isterseniz önce `bash scripts/install_ci_system_deps.sh` çalıştırın.
> Parolasız sudo yoksa `AUTO_INSTALL_CI_SYSTEM_DEPS=1 bash run_tests.sh` opt-in
> kurulumu dener; yine başarısız olursa yerel profilde BATS testleri uyarı verip
> atlanır, CI profilinde ise eksik bağımlılık hata olarak görünür. Dev Container
> imajı kalıcı geliştirici ortamları için `bats` paketini build aşamasında içerir.

Bu sıra Debian/Ubuntu'da `portaudio19-dev`, `shellcheck` ve `bats` paketlerini
(Pacman/Homebrew gibi ortamlarda eşdeğer paketleri) Python bağımlılıkları
çözülmeden önce hazırlar; aksi halde `pyaudio` kaynak derlemesi `portaudio.h`
eksiğiyle veya shell testleri `bats` bulunamadığı için başarısız olabilir.
`install_sidar.sh` ve modüler installer da tam/voice profil senkronizasyonundan önce
desteklenen paket yöneticileriyle (`apt`, `dnf`, `pacman`, `zypper`, `brew`)
PortAudio geliştirme paketini idempotent biçimde doğrular veya platforma uygun
manuel komutu gösterir.
