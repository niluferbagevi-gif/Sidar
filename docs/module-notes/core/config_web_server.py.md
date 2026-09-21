# `core/config_web_server.py` — Web Arayüzü Bind Ayarları

- **Kaynak dosya:** `core/config_web_server.py`
- **Not dosyası:** `docs/module-notes/core/config_web_server.py.md`

**Amaç:** `config.py`'deki `# ─── Web Arayüzü ───` bloğunun 3 alanını
(`WEB_HOST`, `WEB_PORT`, `WEB_GPU_PORT`) `WebServerSettings` frozen
dataclass'ı olarak yükler; `config.Config` bunu `web_server_settings`
olarak expose eder ve aynı 3 alanı geriye dönük uyumlu `Config.FOO` class
attribute'larına delege eder (`docs/REFACTOR_PLAN.md`'nin `config.py`
maddesinde RAG LLM entity extraction diliminden sonra işaretlenen sıradaki
düşük riskli dilim). `main.py`, `web/cli.py` ve `launcher/selection.py`'nin
`getattr(cfg, "WEB_HOST", "127.0.0.1")` gibi mevcut alan adlarıyla
tüketmesi değişmeden korunur. `core/config_runtime_env.py::apply_runtime_env_overrides(...)`
reload sırasında `Config.WEB_HOST`/`Config.WEB_PORT` class attribute'larını
doğrudan yeniden atar; bu, tipli `_WEB_SERVER_SETTINGS` module-level
instance'ını etkilemez, yalnızca `Config` sınıfının o attribute'unu
günceller — `CODING_MODEL`/`AI_PROVIDER` gibi zaten aynı desende delege
edilmiş diğer reload-sensitive alanlarla tutarlıdır.

**Özellikler:**
- `WebServerSettings` — `web_host`, `web_port`, `web_gpu_port`.
- `load_web_server_settings()` — her alanı kendi ortam değişkeninden okur;
  port alanları (`get_int_env()`) malformed girdilerde uyarı loglayıp
  varsayılana düşer.
