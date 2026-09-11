# `web/routes/metrics.py` — Metrikler/Prometheus/Bütçe Rotaları

- **Kaynak dosya:** `web/routes/metrics.py`
- **Not dosyası:** `docs/module-notes/web/routes/metrics.py.md`

**Amaç:** Prometheus formatlı `/metrics`, LLM-özel metrik/bütçe uç
noktalarını kaydeder; `web_server` modülündeki (test/monkeypatch tarafından
override edilebilen) yardımcı fonksiyonları dinamik olarak çözer.

**Özellikler:**
- `_resolve_web_server_helper(name, default)` — `sys.modules["web_server"]`
  üzerinden, henüz import edilmemişse `default`'a düşerek yardımcı fonksiyon
  çözer (döngüsel import olmadan `web_server`'ın test-time override'larına
  saygı gösterir).
- `build_metrics_router(...)` — `GET /metrics`,
  `GET /metrics/llm/prometheus`, `GET /metrics/llm`, `GET /api/budget`
  rotalarını kaydeder.
