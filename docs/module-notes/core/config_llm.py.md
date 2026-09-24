# `core/config_llm.py` — LLM Sağlayıcı ve Model Ayarları

- **Kaynak dosya:** `core/config_llm.py`
- **Not dosyası:** `docs/module-notes/core/config_llm.py.md`

**Amaç:** LLM sağlayıcı/model seçimini (`CODING_MODEL`, `TEXT_MODEL`, `AI_PROVIDER` vb.) ve
Ollama batch politikasını tutar. `config.py` sonucu `Config.llm_settings` ve legacy
`Config.FOO` alias'ları olarak expose eder. Installer modülü
`scripts/install_modules/utils/ollama_models.sh` da `OLLAMA_BATCH_POLICY`'yi buradan okur.

**Özellikler:**
- `OllamaBatchPolicy` / `OLLAMA_BATCH_POLICY` — `num_batch` sınırlama ve bağlama göre
  otomatik batch seçimi.
- `SUPPORTED_AI_PROVIDERS`, `PROVIDER_REQUIRED_SETTINGS`, `OLLAMA_TIMEOUT_DEFAULT`.
- `LLMClientSettings` ve `load_llm_settings(env_path=..., skip_default_dotenv=...)` —
  `core/config_scoped_settings.py` ile dotenv'e scoped pydantic-settings yüklemesi.
