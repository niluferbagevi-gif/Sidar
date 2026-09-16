# `core/config_orchestrator.py` — Orkestrasyon/Otonomi Zaman Aşımı Ayarları

- **Kaynak dosya:** `core/config_orchestrator.py`
- **Not dosyası:** `docs/module-notes/core/config_orchestrator.py.md`

**Amaç:** ReAct döngü adım limitleri, swarm görev zaman aşımları (model bazlı
override dahil) ve otonom cron ayarlarını `OrchestratorSettings` frozen
dataclass'ı olarak yükler.

**Özellikler:**
- `OrchestratorSettings` — `max_react_steps`, `agent_max_react_steps`,
  `react_timeout`, `swarm_task_timeout_seconds` (+ `_ollama` varyantı ve
  model-bazlı override string'i `swarm_task_timeout_by_model`),
  `subtask_max_steps`, `auto_handle_timeout`, `enable_autonomous_cron`,
  `autonomous_cron_interval_seconds`, `autonomous_cron_prompt`.
