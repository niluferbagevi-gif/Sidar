# `core/utils/token_counter.py` — Model Bazlı Token Tahmini

- **Kaynak dosya:** `core/utils/token_counter.py`
- **Not dosyası:** `docs/module-notes/core/utils/token_counter.py.md`

**Amaç:** `tiktoken` gibi tam bir tokenizer olmadan, model ailesine göre
kalibre edilmiş çarpanlarla hızlı/yaklaşık token sayısı tahmini üretir;
maliyet-duyarlı routing (`core/llm_pricing.py`) ve bütçe kontrollerinde
ön-tahmin için kullanılır.

**Özellikler:**
- `_MODEL_TOKEN_MULTIPLIERS` — model ailesi (claude/gemini/llama vb.) →
  çarpan eşlemesi; `gpt`/`o1`/`o3`/`text-embedding` öneki 1.0 (tiktoken
  uyumlu) kabul edilir.
- `_token_estimate_multiplier(model="")` — model adına göre çarpanı çözer.
- `estimate_tokens(text, *, model="")` — metnin yaklaşık token sayısını
  döndürür.
- `get_tiktoken_encoding(model="")` — mevcutsa gerçek `tiktoken` encoder'ını
  (lazy, `lru_cache`'li) döndürür.
