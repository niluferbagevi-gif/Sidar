# `core/llm_pricing.py` — LLM Model Fiyatlandırma Tek Doğruluk Kaynağı

- **Kaynak dosya:** `core/llm_pricing.py`
- **Not dosyası:** `docs/module-notes/core/llm_pricing.py.md`

**Amaç:** `core.llm_client` (maliyet-duyarlı routing) ve `core.llm_metrics`
(maliyet dashboard/bütçe takibi) daha önce aynı modeller için birbirinden
bağımsız, birbirinden sapmış hardcoded fiyat tabloları taşıyordu (örn.
`gpt-4o-mini` `llm_client`'ta $2.00/1M blended iken `llm_metrics`'te
$0.15 prompt / $0.60 completion olarak farklıydı — bir kod incelemesinde
tespit edildi). Bu iki tablo gerçekten farklı amaçlara hizmet eder ve aynı
sayının iki şekli değildir; bu modül ikisini de tek kaynaktan besler.

**Özellikler:**
- `MODEL_COSTS_PER_TOKEN_USD` — *routing* kararları (maliyet-duyarlı model
  seçimi, günlük/toplam bütçe gate'i) için istek gönderilmeden önce kullanılan
  kaba, blended $/token tahmini; bare model adıyla, prefix eşleşmesiyle
  anahtarlanır. `core.llm_client._resolve_cost_per_token_usd` tarafından
  tüketilir.
- `MODEL_PRICES_PER_1M_TOKENS_USD` — kullanım dashboard'unda gösterilen
  *sonradan* (post-hoc) maliyet tahmini için ayrı prompt/completion $/1M
  token; `"provider:model"` ile anahtarlanır.
  `core.llm_metrics.LLMMetricsCollector.estimate_cost_usd` tarafından
  tüketilir.
