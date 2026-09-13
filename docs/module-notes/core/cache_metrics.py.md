# `core/cache_metrics.py` — Semantic Cache Hit/Miss Sayaçları

- **Kaynak dosya:** `core/cache_metrics.py`
- **Not dosyası:** `docs/module-notes/core/cache_metrics.py.md`

**Amaç:** Semantic cache hit/miss/skip/eviction sayaçlarını thread-safe,
process-içi tutar; opsiyonel Prometheus entegrasyonu ile (varsa) dışa açar.
Kasıtlı olarak hafif tutulur — `core/llm_client.py`'den bağımsız import
edilebilir ve test edilebilir.

**Özellikler:**
- `_CacheMetrics` — `threading.Lock` korumalı hit/miss/skip sayaçları.
- `record_cache_hit()`, `record_cache_miss()`, `record_cache_skip()`,
  `record_cache_eviction(count=1)`, `record_cache_redis_error(count=1)`,
  `record_cache_circuit_open_bypass(count=1)`, `set_cache_items(count)`,
  `observe_cache_redis_latency(latency_ms)` — sayaç güncelleme API'si.
- `get_cache_metrics()` — anlık metrik özetini sözlük olarak döndürür.
