# core/cache/

- **Kaynak dizini:** `core/cache/` (`__init__.py`, `semantic_cache.py`)
- **Not dosyası:** `docs/module-notes/core/cache.md`

## Amaç

`semantic_cache.py::SemanticCacheManager`, Redis üzerinde çalışan, embedding
tabanlı bir LLM yanıt önbelleği. `ENABLE_SEMANTIC_CACHE` bayrağıyla kapatılabilir;
`SEMANTIC_CACHE_THRESHOLD` (kosinüs benzerlik eşiği), `SEMANTIC_CACHE_TTL`,
`SEMANTIC_CACHE_MAX_ITEMS` ve `SEMANTIC_CACHE_REDIS_CB_*` (circuit-breaker eşiği/
soğuma süresi) `config`'ten okunur.

- **`get(prompt)`:** prompt'u embed edip (`embedding_fn`, varsayılan
  `core.embeddings.embed_texts_for_semantic_cache`) `sidar:semantic_cache:index`
  listesindeki tüm kayıtlarla kosinüs benzerliği kıyaslar; en iyi eşleşme eşik
  üzerindeyse yanıtı döner (`record_cache_hit`), değilse `None`
  (`record_cache_miss`).
- **`set(prompt, response)`:** kaydı `sidar:semantic_cache:item:{sha256(prompt)}`
  anahtarıyla hash olarak yazar, index listesine LPUSH edip `max_items`'a
  `LTRIM`'ler (LRU benzeri tahliye — `record_cache_eviction`).
- **Bağlantı dayanıklılığı:** Redis bağlantısı lazy kurulur ve `asyncio.Lock`
  ile korunur; ardışık `redis_cb_fail_threshold` hata sonrası circuit açılır
  (`redis_cb_cooldown_seconds` boyunca tüm çağrılar sessizce bypass edilir,
  `record_cache_circuit_open_bypass`). `redis` paketi kurulu değilse (`Redis is
  None`) sınıf sessizce no-op'a düşer.
- Tüm metrikler `core/cache_metrics.py`'ye devredilir (hit/miss/eviction/
  circuit-bypass/redis-error/redis-latency/item-count); modülün kendisi
  Prometheus istemcisiyle doğrudan konuşmaz.

`core/llm/cache.py`, LLM çağrı katmanında bu sınıfı örnekleyip `get`/`set`'i
sarmalıyor — gerçek kullanım noktası orası.

## Test kapısı

`tests/unit/core/test_semantic_cache.py`.
