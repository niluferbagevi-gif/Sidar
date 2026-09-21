# `core/config_web_search.py` — Web Arama/Fetch Ayarları

- **Kaynak dosya:** `core/config_web_search.py`
- **Not dosyası:** `docs/module-notes/core/config_web_search.py.md`

**Amaç:** Web arama sağlayıcı seçimi/kimlik bilgileri ve fetch sınırlarını
`WebSearchSettings` frozen dataclass'ı olarak yükler; `config.Config` bunu
`web_search_settings` olarak expose eder ve aynı 6 alanı geriye dönük uyumlu
`Config.FOO` class attribute'larına delege eder
(`docs/REFACTOR_PLAN.md`'nin `config.py` maddesinde GitHub/Hugging Face
diliminden sonra işaretlenen sıradaki düşük riskli dilim). `managers/web_search.py`
bu ayarları `getattr(config, "SEARCH_ENGINE", ...)` gibi mevcut alan adlarıyla
tüketmeye devam eder.

**Özellikler:**
- `WebSearchSettings` — `search_engine`, `tavily_api_key`,
  `google_search_api_key`, `google_search_cx`, `web_search_max_results`,
  `web_fetch_timeout`.
- `load_web_search_settings()` — her alanı kendi ortam değişkeninden okur;
  `web_search_max_results`/`web_fetch_timeout` `get_int_env()` ile malformed
  girdilerde uyarı loglayıp varsayılana düşer. `WEB_FETCH_MAX_CHARS`/
  `WEB_SCRAPE_MAX_CHARS` bu modülün kapsamı dışında kalır — onlar zaten
  `core/config_rag_store.py`'ye taşınmıştır.
