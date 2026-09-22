# `core/doctor/checks/gpu.py` — GPU Doktor Kontrolleri

- **Kaynak dosya:** `core/doctor/checks/gpu.py`
- **Not dosyası:** `docs/module-notes/core/doctor/checks/gpu.py.md`

**Amaç:** `check_gpu_memory_config()`, `check_docker_test_image()`,
`check_gpu()`'nin gerçek gövdelerini barındırır — `redis.py::check_redis`
ile aynı desende, kendi kendine yeten bir implementasyon
(`docs/REFACTOR_PLAN.md`'nin `core/doctor/__init__.py` maddesinde
`database.py`'den sonra taşınan üçüncü dilim). `core/doctor/__init__.py`'deki
üç fonksiyon artık bu modüle deferred-import ile delege eden ince
pass-through'lardır. **Düzeltme:** `docs/REFACTOR_PLAN.md`'nin bu maddesinin
önceki sürümü "gpu.py'nin 2'si" pass-through diyordu; dosya kontrol
edildiğinde üç fonksiyonun de (`check_gpu_memory_config`,
`check_docker_test_image`, `check_gpu`) pass-through olduğu görüldü —
orijinal incelemenin sayımı bir eksikti, bu dilim üçünü de kapsar.

**Kritik detay — hangi helper'lar `__init__.py`'de kaldı:** `_run_command`
ve `_docker_image_exists_local` bilinçli olarak `__init__.py`'de bırakıldı
ve `checks/gpu.py` bunlara `_doctor.X(...)` dinamik referansla erişir:

- `_run_command` testlerde doğrudan `monkeypatch.setattr(doctor,
  "_run_command", ...)` ile hedeflenen bir monkeypatch seam'idir; ayrıca
  `check_uv()`/migration-related check'lerle de paylaşılıyor.
- `_docker_image_exists_local` doğrudan `monkeypatch.setattr(doctor,
  "_docker_image_exists_local", ...)` ile hedeflenen bir monkeypatch
  seam'idir, yalnızca `check_docker_test_image()` tarafından kullanılır.

`tests/unit/core/doctor/test_checks_modules.py`'deki artık yanlış yöne
işaret eden `test_check_docker_test_image_delegates_to_doctor` kaldırıldı
(`checks/gpu.py._doctor`'ı monkeypatch edip eski pass-through yönünü
doğruluyordu).

**Özellikler:**
- `check_gpu_memory_config()` — yerel model/VRAM bütçe ayarlarını raporlar;
  `Config._ensure_hardware_info_loaded()` ile lazy hardware probe'unu
  zorlar.
- `check_docker_test_image()` — `DOCKER_TEST_IMAGE`'ın yerel olarak mevcut
  olup olmadığını, auto-build/production-readiness bayraklarına göre
  değerlendirir.
- `check_gpu()` — `nvidia-smi` veya `torch.cuda` üzerinden GPU tespiti
  yapar, `RUN_GPU_STRESS` önerisini belirler.
