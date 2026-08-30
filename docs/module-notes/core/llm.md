# core/llm/

- **Kaynak dizini:** `core/llm/` (`__init__.py`, `anthropic.py`, `cache.py`,
  `facade.py`, `gemini.py`, `litellm.py`, `ollama.py`, `openai.py`,
  `router.py`, `streaming.py`, `streaming_http.py`)
- **Not dosyası:** `docs/module-notes/core/llm.md`

## Amaç

`core/llm_client.py`'nin (bkz. `docs/module-notes/core/llm_client.py.md`)
monolitik `BaseLLMClient` facade'ını besleyen sağlayıcı adaptörleri ve ortak
altyapı. `__init__.py`, beş sağlayıcı sınıfını (`AnthropicClient`,
`GeminiClient`, `LiteLLMClient`, `OllamaClient`, `OpenAIClient`) `__getattr__`
ile **lazy** export eder — bu, facade/provider modülleri arasında eager
import döngüsünü önler.

- **Sağlayıcı adaptörleri (`anthropic.py`, `gemini.py`, `litellm.py`,
  `ollama.py`, `openai.py`):** Her biri `core.llm_client.BaseLLMClient`'i
  genişleten tek bir `*Client` sınıfı tanımlar ve modül başında birebir aynı
  ~10 tek satırlık `_setting`/`_extract_usage_tokens`/vb. forwarding
  fonksiyonuna sahiptir (hepsi `import core.llm_client as llm_facade`
  üzerinden çağırır). `ollama.py`'nin kendi docstring'i bu tekrarı bir kod
  incelemesinin DRY ihlali olarak işaretlediğini, ama bilinçli olarak
  korunduğunu belgeliyor: her adaptörün kendi `llm_facade` bağlaması, `tests/
  unit/core/llm/test_provider_facade_delegation.py`'nin doğruladığı
  per-modül monkeypatch yüzeyini sağlıyor — ortak bir modüle taşımak ya bu
  patch noktasını birleştirip test sözleşmesini değiştirmeyi ya da aynı
  tekrarı bir seviye yukarı taşımayı gerektirir. `litellm.py`/`openai.py`,
  HTTP stream açılışı için `streaming_http.py::enter_httpx_stream`'i
  paylaşır.
- **`facade.py::LLMProvider` (`Protocol`):** sağlayıcı adaptörlerinin uyması
  gereken `generate`/`chat` sözleşmesini tip seviyesinde belgeler (facade
  modülünün kendisinden ayrı tutulmuş, döngüsel import'suz bir tip dosyası).
- **`router.py::LLMRoutingService`:** `core/router.py::CostAwareRouter`'ı
  sarmalar; facade'ın router kurulum detaylarına sahip olmasını önler.
- **`cache.py::SemanticChatCache`:** `core/cache/semantic_cache.py`'yi (bkz.
  `docs/module-notes/core/cache.md`) sarmalayan ince facade — boş prompt'ları
  erken eler, stream yanıtlar için `record_cache_skip()` çağırır (streaming
  yanıtlar semantic cache'e yazılmaz).
- **`streaming.py`:** Stream'i tüketen üç sarmalayıcı —
  `track_stream_completion` (başarı/hata metriği + son 2000 karakterlik
  parça hata loglarında görünür kalır), `track_stream_routing_cost`
  (tahmini token sayısından maliyet kaydeder), `trace_stream_metrics`
  (TTFT/toplam gecikme span attribute'ları).
- **`streaming_http.py::enter_httpx_stream`:** Kısa ömürlü bir
  `httpx.AsyncClient` ile stream context'e girerken bağlantı/`raise_for_status`/
  iptal başarısız olursa client'ı deterministik biçimde kapatır — çağıranın
  dış `finally`'sinin normalde erişemeyeceği bir yarım-kurulum sızıntısını
  kapatan yardımcı.

## Test kapısı

`tests/unit/core/test_llm_client.py` (sağlayıcıları facade üzerinden
kapsıyor), `tests/unit/core/llm/test_provider_facade_delegation.py`,
`tests/unit/core/llm/test_streaming_http.py`, `tests/unit/core/
test_semantic_cache.py`.
