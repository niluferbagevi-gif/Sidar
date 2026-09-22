# `core/doctor/checks/rag.py` — RAG/GraphRAG Doktor Kontrolleri

- **Kaynak dosya:** `core/doctor/checks/rag.py`
- **Not dosyası:** `docs/module-notes/core/doctor/checks/rag.py.md`

**Amaç:** `check_rag_index_ready()`, `check_graphrag_entity_memory_ready()`,
`check_rag_readiness()`'in gerçek gövdelerini barındırır — `redis.py::check_redis`
ile aynı desende, kendi kendine yeten bir implementasyon
(`docs/REFACTOR_PLAN.md`'nin `core/doctor/__init__.py` maddesinde
`security.py`/`database.py`/`gpu.py`'den sonra taşınan dördüncü ve son dilim).
`core/doctor/__init__.py`'deki üç fonksiyon artık bu modüle deferred-import ile
delege eden ince pass-through'lardır. Ayrıca yalnızca `check_rag_index_ready()`
tarafından kullanılan `_ensure_rag_index_placeholder()` helper'ı da bu modüle
taşındı.

**Kritik detay — hangi helper'lar `__init__.py`'de kaldı:** `_rag_readiness_state`,
`_query_entity_graph_counts_from_store`, `_resolved_database_urls`, `_parse_url`
ve `BASE_DIR` bilinçli olarak `__init__.py`'de bırakıldı ve `checks/rag.py`
bunlara `_doctor.X` dinamik referansla erişir:

- `_rag_readiness_state` ve `_query_entity_graph_counts_from_store` testlerde
  doğrudan `monkeypatch.setattr(doctor, "_rag_readiness_state", ...)` /
  `monkeypatch.setattr(doctor, "_query_entity_graph_counts_from_store", ...)`
  ile hedeflenen monkeypatch seam'leridir.
- `_resolved_database_urls` ve `_parse_url` de doğrudan monkeypatch seam'i
  olmalarının yanı sıra `database.py`'ye taşınan fonksiyonlarla da paylaşılıyor.
- `_get_bool_env` ve `_load_json_object` yalnızca `_rag_readiness_state()`
  tarafından kullanıldığı için, `_rag_readiness_state` kendisi `__init__.py`'de
  kaldığından bu iki helper da orada kaldı (taşınmadılar).
- `BASE_DIR` daha önceki `security.py` dilimindeki aynı nedenle
  (`monkeypatch.setattr(doctor, "BASE_DIR", ...)` seam'i) dinamik referansla
  okunuyor.

**Kritik detay — fonksiyonlar arası çağrı yönü:** `check_rag_readiness()`,
`check_rag_index_ready()` ve `check_graphrag_entity_memory_ready()`'i **bare/local
isimle değil**, `_doctor.check_rag_index_ready()` /
`_doctor.check_graphrag_entity_memory_ready()` üzerinden çağırır. Her iki alt
kontrol de doğrudan `monkeypatch.setattr(doctor, "check_rag_index_ready", ...)`
/ `monkeypatch.setattr(doctor, "check_graphrag_entity_memory_ready", ...)` ile
hedeflenen seam'lerdir ve `tests/unit/core/test_doctor.py`'deki birden fazla
test bu iki alt kontrolü patch'leyip `doctor.check_rag_readiness()`'in
sonucunu doğrular; bare local çağrı bu patch'i atlayıp yanlış (patch'lenmemiş)
sonucu üretirdi.

`core/doctor/__init__.py::run_doctor_report()`'ın `checks.rag`'e aliaslı
importları (`rag_index_ready_check`, `graphrag_entity_memory_ready_check`)
kaldırıldı; artık bare `check_rag_index_ready()` /
`check_graphrag_entity_memory_ready()` çağrılıyor — bu da
`monkeypatch.setattr(doctor, "check_rag_index_ready", ...)` gibi
`run_doctor_report()` üzerinden doğrulanan testlerin çalışmaya devam etmesini
sağlıyor.

`tests/unit/core/doctor/test_checks_modules.py`'deki artık yanlış yöne işaret
eden `test_check_rag_index_ready_delegates_to_doctor`,
`test_check_graphrag_entity_memory_ready_delegates_to_doctor` ve
`test_check_rag_readiness_delegates_to_doctor` kaldırıldı (`checks/rag.py._doctor`'ı
monkeypatch edip eski pass-through yönünü doğruluyordu).

**Özellikler:**
- `check_rag_index_ready()` — RAG index dosyasının/doküman sayısının durumunu
  raporlar; eksikse doctor-facing placeholder index oluşturur.
- `check_graphrag_entity_memory_ready()` — GraphRAG entity/edge sayımını
  `DocumentStore` üzerinden yeniden doğrular ve boşsa metadata-only seed önerir.
- `check_rag_readiness()` — geriye dönük uyumlu agregat kontrol; iki alt
  kontrolü birleştirip `database_env` engellemesini de hesaba katar.
