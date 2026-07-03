# Test çalıştırma rehberi

Sidar'da iki farklı test akışı vardır:

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

Merge/PR öncesi ana doğrulama yolu `run_tests.sh` betiğidir. Coverage ayarları için
tek doğruluk kaynağı `pyproject.toml` içindeki `[tool.coverage.*]` bölümleridir;
repoda ayrı bir `.coveragerc` dosyası tutulmaz. `run_tests.sh`,
`[tool.coverage.report].fail_under = 5` baseline değerini okur, profil
override'larını çözer ve asıl fail-under kontrolünü tüm fazlar birleştikten sonra
tek final `coverage report --fail-under=${COVERAGE_FAIL_UNDER}` adımında uygular.

| Profil | Varsayılan eşik | Nasıl seçilir? |
| --- | --- | --- |
| Local | `%5` (`pyproject.toml` baseline veya `COVERAGE_FAIL_UNDER_LOCAL`) | Varsayılan geliştirici akışı |
| CI | `%5` ratchet baseline (`COVERAGE_FAIL_UNDER_CI` açık override değilse) | `CI=true` veya `TEST_PROFILE=ci` |
| Coverage campaign | `%5` ratchet baseline (`COVERAGE_FAIL_UNDER_CAMPAIGN` açık override değilse) | `COVERAGE_CAMPAIGN=1` veya `AUTONOMOUS_LOOP_OPERATION_PROFILE=coverage-campaign` |

Açık `COVERAGE_FAIL_UNDER` verilirse tüm profil değerlerinin önüne geçer;
`MIN_UNIT_COVERAGE_FAIL_UNDER` (varsayılan `%5`) ise çözülen değerin alt sınırıdır.

```bash
./run_tests.sh
```

CI profilinde coverage eşiği daha sıkı çalıştırılabilir:

```bash
CI=true TEST_PROFILE=ci ./run_tests.sh
```
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
```

Hızlı PR kontrollerinde voice/browser/GPU gibi sistem bağımlılıkları gerekmiyorsa
`uv sync --frozen --extra dev-light` sistemi başlık paketlerine ihtiyaç duymadan
`postgres` + `dev` araçlarını kuran hafif profildir.

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
