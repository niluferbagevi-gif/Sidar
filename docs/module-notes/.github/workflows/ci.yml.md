# `.github/workflows/ci.yml`

- **Kaynak dosya:** `.github/workflows/ci.yml`
- **Not dosyası:** `docs/module-notes/.github/workflows/ci.yml.md`
- **Kategori:** GitHub Actions ana CI kalite kapısı
- **Çalışma tipi:** Workflow YAML (push + pull_request)

## 1) Bu workflow ne işe yarar?

`ci.yml`, repo için ana kalite boru hattıdır. Her `push` ve `pull_request` olayında aşağıdaki hedefleri uygular:

- bağımlılık kurulumu,
- repo metrik/audit üretimi,
- boş test artifact kontrolü,
- tam test suite çalıştırma,
- sandbox/reviewer sertleştirme testleri,
- `%95` coverage barajı zorlaması.

Bu workflow, kod kalitesini sadece “test geçti” seviyesinde değil, ölçülebilir coverage ve güvenlik odaklı ek kontrollerle garanti altına alır.

## 2) Tetikleme ve çalışma ortamı

- **Trigger:** `push`, `pull_request`
- **Runner:** `ubuntu-latest`
- **Python:** `3.11` (`actions/setup-python@v5`)

## 3) Adım adım iş akışı

1. **Checkout**
   - Kaynak kod alınır (`actions/checkout@v4`).

2. **Python kurulumu**
   - Python 3.11 ortamı hazırlanır.

3. **Bağımlılık kurulumu**
   - `requirements.txt` + `requirements-dev.txt` yüklenir.

4. **Repository metrics**
   - `bash scripts/collect_repo_metrics.sh`
   - CI loglarına hızlı `key=value` metrik özeti basar.

5. **Audit metrics (standartlaştırılmış)**
   - `bash scripts/audit_metrics.sh . markdown`
   - `bash scripts/audit_metrics.sh . json`
   - İnsan + makine tüketimli iki format birden üretilir.

6. **Boş test artifact kontrolü**
   - `find tests -type f -size 0` ile 0 bayt dosyalar bloklanır.

7. **Ana test suite**
   - `bash run_tests.sh`

8. **Sandbox/reviewer hardening kontrolü**
   - `pytest -q tests/test_sandbox_runtime_profiles.py tests/test_reviewer_agent.py`

9. **Coverage quality gate**
   - `python -m pytest -q --cov=. --cov-report=term-missing --cov-fail-under=95`

## 4) Nerede kullanılıyor / ilişkili bileşenler

- Ana CI kalite kapısı olarak PR ve push akışlarını korur.
- `PROJE_RAPORU.md` içindeki kalite kapısı tablosuyla doğrudan uyumludur.
- Aşağıdaki script/test dosyalarıyla bağlı çalışır:
  - `scripts/collect_repo_metrics.sh`
  - `scripts/audit_metrics.sh`
  - `run_tests.sh`
  - `tests/test_sandbox_runtime_profiles.py`
  - `tests/test_reviewer_agent.py`

## 5) Örnek sonuç beklentileri

Başarılı bir çalışmada aşağıdaki sinyaller görülür:

- metrik scriptleri loglara çıktı üretir,
- boş test artifact bulunmaz,
- test suite geçer,
- hardening testleri geçer,
- coverage `%95` altına düşmez.

Başarısızlık durumlarında workflow adımları fail-fast davranır ve PR merge’i engellenir.

## 6) Bağımlılıklar

- GitHub Actions runner (`ubuntu-latest`)
- Python 3.11
- Pip erişimi + bağımlılık dosyaları
- Çalıştırılan script/test dosyalarının repoda mevcut olması

## 7) Dikkat edilmesi gerekenler

1. Coverage adımı, `run_tests.sh` sonrası tekrar pytest/cov çalıştırdığı için süreyi artırır; ancak kalite güvencesi sağlar.
2. Boş test artifact kontrolü inline yazılmıştır; scriptle (`scripts/check_empty_test_artifacts.sh`) merkezi hale getirme tercihine göre refactor edilebilir.
3. Metrik adımları kalite sinyali üretir ama tek başına pass/fail kriteri değildir.
