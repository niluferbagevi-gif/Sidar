# `core/config_quality.py` — DLP/HITL/LLM-Judge Kalite Kapısı Ayarları

- **Kaynak dosya:** `core/config_quality.py`
- **Not dosyası:** `docs/module-notes/core/config_quality.py.md`

**Amaç:** DLP maskeleme, HITL onay kapısı ve LLM-as-a-judge ayarlarını `QualityGateSettings`
olarak yükler; `config.py` bunları `Config` üzerinden expose eder.

**Özellikler:**
- `QualityGateSettings` — pydantic-settings modeli (alias ve validator'larla).
- `load_quality_gate_settings(env_path=..., skip_default_dotenv=...)` —
  `core/config_scoped_settings.py` ile dotenv'e scoped yükleme.
