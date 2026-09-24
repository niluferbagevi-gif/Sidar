# `launcher/preflight.py` — Sağlayıcı Ön Kontrolleri

- **Kaynak dosya:** `launcher/preflight.py`
- **Not dosyası:** `docs/module-notes/launcher/preflight.py.md`

**Amaç:** `main.preflight`'ın sağlayıcıya özgü kısmı: bulut API anahtarı uyarıları ve
Ollama erişim kontrolü. Mesajlar değişmedi.

**Özellikler:**
- `warn_missing_provider_api_key(provider, cfg, *, logger_obj)` — Gemini/OpenAI/
  Anthropic seçildiyse ve ilgili anahtar boşsa uyarır.
- `check_ollama_reachability(cfg, *, logger_obj)` — `/api/tags` uç noktasına 2 sn
  zaman aşımıyla istek atar; `httpx` yoksa veya erişilemiyorsa uyarı yazar.
