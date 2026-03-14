# 3.8 `core/llm_client.py` — LLM İstemcisi (Ollama + Gemini + OpenAI + Anthropic, 839 satır)

## Rapor İçeriği (Taşınan Bölüm)

**Amaç:** Ollama, Gemini, OpenAI ve Anthropic için ortak asenkron chat arayüzü — `BaseLLMClient` ABC.

> Not (Doğrulama): Bu rapordaki satır sayısı, güncel depoda `wc -l core/llm_client.py` çıktısına göre **839** olarak ölçülmüştür.

**Sınıf Hiyerarşisi:**
```
BaseLLMClient (ABC)
├── OllamaClient
├── GeminiClient
├── OpenAIClient          ← v2.9.0 yeni eklenti
└── AnthropicClient       ← v2.10.8 yeni eklenti
```

**`LLMClient.chat()` Parametreleri:**
- `stream`: True → `AsyncIterator[str]`, False → `str`
- `json_mode`: True → LLM'i `{thought, tool, argument}` JSON çıktısına zorlar

**Ollama Entegrasyonu:**
- **Yapısal Çıktı (Structured Output):** Ollama ≥0.4 için JSON Schema formatı ile `{thought, tool, argument}` şeması zorunlu kılınır. Hallucination ve yanlış format sorunlarını önler.
- **Stream Güvenliği:** `aiter_bytes()` + `codecs.IncrementalDecoder` ile TCP paket sınırlarında bölünen JSON satırları güvenle birleştirilir. `aiter_lines()` kullanılmaz çünkü bu yaklaşım içerik kaybına yol açabilir.
- **GPU Desteği:** `USE_GPU=true` ise `options.num_gpu=-1` ile tüm katmanlar GPU'ya gönderilir.
- **Timeout:** `max(10, OLLAMA_TIMEOUT)` — minimum 10 sn garanti edilir.

**Gemini Entegrasyonu:**
- `google.generativeai` paketi runtime'da import edilir; kurulu değilse anlamlı hata mesajı döner.
- `response_mime_type: application/json` ile JSON modu; `text/plain` ile düz metin modu.
- Safety settings: Tüm zararlı içerik kategorileri `BLOCK_NONE` — teknik konularda LLM bloklamalarını önler.
- `send_message_async` ile gerçek asenkron Gemini çağrısı.

**OpenAI Entegrasyonu (v2.9.0):**
- `openai` paketi runtime'da import edilir; `AsyncOpenAI` istemcisi.
- `response_format: {"type": "json_object"}` ile JSON modu.
- WebSocket olay paketleri (`chunk/thought/tool_call/done`) ile gerçek zamanlı streaming desteği.
- `AI_PROVIDER=openai` + `OPENAI_API_KEY` ile aktif edilir.

**Anthropic Entegrasyonu:**
- `anthropic` paketi runtime'da import edilir; `AsyncAnthropic` istemcisiyle asenkron çağrı yapılır.
- `json_mode=True` iken sistem istemine ek JSON şema talimatı enjekte edilerek `{thought, tool, argument}` formatı zorlanır.
- Streaming ve non-streaming akışlar ortak yardımcılarla izlenir; sonuçlar `_ensure_json_text()` ile güvenli JSON'a normalize edilir.

**Akıllı Yeniden Deneme (Retry/Backoff):**
- `_is_retryable_exception` + `_retry_with_backoff` ile 429/5xx gibi geçici bulut hatalarında yeniden deneme uygulanır.
- Exponential backoff + jitter kullanılarak sağlayıcı geçici hatalarında dayanıklılık artırılır.

**Telemetri ve Gözlemlenebilirlik (Observability):**
- `core.llm_metrics` entegrasyonu ile çağrı başına latency/success/error ve token kullanımı kaydedilir (`_record_llm_metric`).
- OpenTelemetry span'leri üzerinden stream performansı izlenir; TTFT (time-to-first-token) ve toplam akış süresi `_trace_stream_metrics` ile ölçülür.

**`_ensure_json_text()`:** Modelin JSON dışı metin döndürmesi durumunda `final_answer` sarmalayıcı olarak güvenli JSON üretir.

---
