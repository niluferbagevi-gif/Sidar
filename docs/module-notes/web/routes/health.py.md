# `web/routes/health.py` — Sağlık Kontrolü Rotaları

- **Kaynak dosya:** `web/routes/health.py`
- **Not dosyası:** `docs/module-notes/web/routes/health.py.md`

**Amaç:** `/health` (liveness/readiness) uç noktasını kaydeden router
fabrikası; gerçek payload üretimi `web/routes/health_runtime.py`'de yaşar.

**Özellikler:**
- `build_health_router(health_response, status_response=None)` —
  `LegacyExportRouter` üzerinde `GET /health` (ve verilirse status) rotasını
  kayıt eder; yanıt üretimi enjekte edilen async callback'lere delege edilir.
