# `web/routes/coverage_ops.py` — Coverage QA Rotaları

- **Kaynak dosya:** `web/routes/coverage_ops.py`
- **Not dosyası:** `docs/module-notes/web/routes/coverage_ops.py.md`

**Amaç:** Geniş operations router'ından ayrılmış, test coverage QA
görevlerini (analiz/üretim/batch) yöneten HTTP rotaları;
`agent/roles/coverage_agent.py`'nin HTTP yüzeyi.

**Özellikler:**
- `configure_coverage_dependencies(deps_factory)` — DB/bağımlılık fabrikasını
  enjekte eder.
- `_database_unavailable_response(*, operation, exc)` — DB erişilemezse
  tutarlı hata yanıtı üretir.
- `decode_agent_tool_result(raw_result)`, `serialize_coverage_task(record)` —
  agent araç sonucunu/coverage görev kaydını JSON'a çevirir.
- `GET /api/qa/coverage/tasks`, `POST /api/qa/coverage/analyze`,
  `POST /api/qa/coverage/generate`, `POST /api/qa/coverage/batch` rotaları.
