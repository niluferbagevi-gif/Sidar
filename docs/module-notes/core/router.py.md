# `core/router.py` — Maliyet-Farkında Model Yönlendirme (v5.0)

- **Kaynak dosya:** `core/router.py`
- **Not dosyası:** `docs/module-notes/core/router.py.md`

**Amaç:** Sorgu karmaşıklığını analiz ederek isteği lokal (Ollama) veya
bulut modeline otomatik yönlendirir; günlük bütçe aşımında otomatik
lokal-fallback uygular (`CostAwareRouter.select(messages, default_provider, default_model)`).

**Özellikler:**
- `QueryComplexityAnalyzer` — kod üretimi/teknik gerektiren anahtar
  kelimelere (`_CODE_KEYWORDS`) dayalı bir karmaşıklık skoru (0.0–1.0)
  hesaplar; LLM çağrısı yapılmadan önce çalışır (ek maliyet/gecikme yok).
- Bütçe takibi SQLite (`sqlite3`) ile kalıcı tutulur; opsiyonel senkron
  Redis istemcisi (`SyncRedis`, `redis` paketi kurulu değilse `None`'a
  düşen opsiyonel bağımlılık) çoklu-proses/pod senaryoları için kullanılır.
- Thread-safe sayaçlar için `threading.Lock` kullanır; `importlib` ile
  sağlayıcı modüllerini dinamik olarak çözer.
