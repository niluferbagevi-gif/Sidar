# `core/utils/background_tasks.py` — Fire-and-Forget asyncio Task Kaydı

- **Kaynak dosya:** `core/utils/background_tasks.py`
- **Not dosyası:** `docs/module-notes/core/utils/background_tasks.py.md`

**Amaç:** `loop.create_task(...)` ile başlatılıp referansı tutulmayan arka plan
task'larını tamamlanana kadar güçlü referansla saklar. asyncio task'lara yalnız
zayıf referans tuttuğundan referanssız bir task sorgu ortasında GC'lenebilir;
SQLAlchemy async engine kullanan bir task'ta bu, havuzdan alınan bağlantının iade
edilmemesine ve `non-checked-in connection` uyarısına yol açar.

**Özellikler:**
- `track_background_task(task)` — `asyncio.Task` ise kayda ekler ve bitince
  `add_done_callback` ile çıkarır; task olmayan değerleri (test sahteleri)
  dokunmadan döndürür.
- `pending_background_tasks()` — henüz bitmemiş kayıtlı task'lar.
- `drain_background_tasks(grace_seconds=2.0)` (async) — çalışan loop'a ait kayıtlı
  task'ları `grace_seconds` boyunca normal bitmeye bırakır, kalanları iptal edip
  bekler; kapanmış loop'lara ait task'ları kayıttan düşürür.

**Kullananlar:** `core/judge.py` (arka plan RAG değerlendirmesi ve async metrik
sink'i), `core/active_learning.py` (`ContinuousLearningPipeline.schedule_cycle`).
`tests/conftest.py` her testten sonra `drain_background_tasks()` çağırarak bu
task'ları test loop'u kapanmadan bitirir (bkz. `docs/TESTING.md`).
