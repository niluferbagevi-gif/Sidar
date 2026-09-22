# `core/doctor/facade.py` — Doctor Orchestration Facade

- **Kaynak dosya:** `core/doctor/facade.py`
- **Not dosyası:** `docs/module-notes/core/doctor/facade.py.md`

**Amaç:** `core/doctor/__init__.py`'nin "health check orchestration wrapper"
katmanını barındırır: tek tek `check_*` kontrollerini toplayıp raporlayan
`run_doctor_report()`, `database_env` onarımını uygulayan
`_apply_database_env_fix()`, standalone CLI argüman ayrıştırması
`_parse_cli_args()` ve `python -m core.doctor` giriş noktası `main()`.
`docs/REFACTOR_PLAN.md`'nin `core/doctor/__init__.py` maddesindeki
`core/doctor/checks/*.py` decomposition'ından (security/database/gpu/rag
dilimleri) sonraki adım — bireysel kontroller yerine kontrolleri
**orkestre eden** katmanı ayırır. `core/doctor/__init__.py`'deki
`run_doctor_report`, `_apply_database_env_fix`, `main` artık bu modüle
deferred-import ile delege eden ince pass-through'lardır; `_parse_cli_args`
hiçbir yerde `doctor._parse_cli_args` olarak dışarıdan referans edilmediği
için pass-through olmadan doğrudan bu modüle taşındı.

**Kritik detay — hangi isimler `__init__.py`'de kaldı ve neden dinamik
referansla çağrılıyor:** `tests/unit/core/test_doctor.py`'deki
`monkeypatch.setattr(doctor, "check_uv", ...)` tarzı testlerin çoğu, ayrı
ayrı her `check_*` fonksiyonunu `doctor.` (yani `core.doctor` modülü)
üzerinden patch'liyor ve `doctor.run_doctor_report()`/`doctor.main()`'in bu
patch'lenmiş sonucu kullanmasını doğruluyor. `run_doctor_report()` artık
`core.doctor`'dan **fiziksel olarak ayrı bir modülde** yaşadığı için, içindeki
her `check_*` çağrısı `import core.doctor as _doctor` + `_doctor.check_uv()`
gibi dinamik lookup ile yapılıyor — bare/local isimle çağırmak (ör. sadece
`check_uv()`) `facade.py`'de tanımlı olmayan bir isme referans verirdi ve
zaten derlenmezdi; ama daha önemlisi, `checks/rag.py` dilimindeki "aynı
dosya içindeki fonksiyonlar arası çağrı" dersiyle aynı nedenle, `_doctor.X()`
kullanmak monkeypatch'in etkili olmasını garanti eder. Aynı gerekçeyle
`_apply_database_env_fix()` içindeki `check_database_env()` ve
`validate_auto_fix_command()` çağrıları, `_run_command()` çağrısı, ve
`main()` içindeki `_apply_database_env_fix()`/`run_doctor_report()`/
`write_doctor_report()` çağrıları hep `_doctor.X(...)` ile yapılıyor.
`build_doctor_report`/`write_doctor_report` da aynı nedenle `_doctor.X(...)`
üzerinden çağrılıyor; bu ikisi `__init__.py`'de artık bare olarak
kullanılmadığından, ruff F401'i önlemek için `core/doctor/__init__.py`'nin
`__all__` listesine eklendi (hâlâ `core.doctor.reporting`'den import
ediliyorlar, yalnızca `__init__.py`'nin kendi gövdesinde artık çağrılmıyorlar).
`_redact_sensitive_text` (`core.doctor.models.redact_sensitive_text`) ise
hiçbir yerde `_doctor.` üzerinden referans edilmediği için `facade.py`
tarafından doğrudan `core.doctor.models`'den import edildi ve
`core/doctor/__init__.py`'deki artık kullanılmayan value-import'u kaldırıldı.

`DEFAULT_OUTPUT` (`BASE_DIR / "artifacts/install/doctor.json"`) hiçbir testte
monkeypatch edilmediği için `facade.py` tarafından `core.doctor`'dan doğrudan
(değer olarak) import edildi — bu sabit hiç değişmediğinden `_doctor.X`
kalıbına ihtiyaç yok.

`check_uv()`, `check_prometheus_runtime()`, `check_migrations()`,
`check_agent_catalog()`, `check_supervisor_routing()`,
`check_websocket_routes()`, `check_model()` ve bunların özel yardımcıları
(`_parse_migration_revisions`, `_iter_effective_routes`, `_ollama_base_url`)
**taşınmadı** — bunlar `core/doctor/checks/*.py`'nin fake pass-through
sorununa hiç dahil değildi (zaten kendi gerçek implementasyonlarıydı, ilgili
testler doğrudan `doctor.check_uv()` gibi çağrılarla gerçek davranışlarını
doğruluyor), bu yüzden kapsam dışında bırakıldı.

**Özellikler:**
- `run_doctor_report()` — tüm `check_*` sonuçlarını toplayıp
  `core/doctor/reporting.py::build_doctor_report()` ile formatlar ve
  `write_doctor_report()` ile diske yazar.
- `_apply_database_env_fix()` — yalnızca `database_env` kapsamına sınırlı,
  allowlist doğrulamalı otomatik onarım; onarım başarılıysa yalnızca
  editable dosyalardan geldiği kanıtlanan `DATABASE_URL`/
  `SIDAR_CONTAINER_DATABASE_URL` ortam değişkenlerini temizler.
- `_parse_cli_args()` — standalone `sidar doctor` CLI argümanlarını
  (`output`, `--fix`) ayrıştırır.
- `main()` — `python -m core.doctor` giriş noktası; raporu üretir, `--fix`
  verilmişse onarımı uygular ve raporu JSON olarak basar.
