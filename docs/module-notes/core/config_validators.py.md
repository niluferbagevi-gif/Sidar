# `core/config_validators.py` — Yapılandırma Doğrulama/Normalizasyon Yardımcıları

- **Kaynak dosya:** `core/config_validators.py`
- **Not dosyası:** `docs/module-notes/core/config_validators.py.md`

**Amaç:** AI sağlayıcı adı normalizasyonu ve zorunlu HTTP(S) endpoint
doğrulaması gibi, birden fazla `config_*.py` domain modülünün paylaştığı saf
doğrulama fonksiyonlarını barındırır.

**Özellikler:**
- `normalize_ai_provider(provider)` — boş/`None` girdide `"ollama"`'ya düşer,
  aksi halde `strip().lower()` ile normalize eder.
- `is_valid_http_url(value)` — şemanın `http`/`https` ve `netloc`'un dolu
  olduğunu doğrular; ham değeri loglamadan `bool` döner (secret/URL sızıntısı
  riskini azaltır).
