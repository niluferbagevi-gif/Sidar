# `core/config_lsp.py` — LSP Entegrasyon Ayarları

- **Kaynak dosya:** `core/config_lsp.py`
- **Not dosyası:** `docs/module-notes/core/config_lsp.py.md`

**Amaç:** `managers/code_manager.py`'nin Language Server Protocol (LSP)
istemci entegrasyonu için kullandığı 5 alanı (`ENABLE_LSP`,
`LSP_TIMEOUT_SECONDS`, `LSP_MAX_REFERENCES`, `PYTHON_LSP_SERVER`,
`TYPESCRIPT_LSP_SERVER`) `LspSettings` frozen dataclass'ı olarak yükler;
`config.Config` bunu `lsp_settings` olarak expose eder ve aynı 5 alanı
geriye dönük uyumlu `Config.FOO` class attribute'larına delege eder
(`docs/REFACTOR_PLAN.md`'nin `config.py` maddesinde tarayıcı otomasyonu
diliminden sonra işaretlenen sıradaki düşük riskli dilim).
`managers/code_manager.py`'nin `getattr(self.cfg, "ENABLE_LSP", True)`
gibi mevcut alan adlarıyla tüketmesi değişmeden korunur.

**Özellikler:**
- `LspSettings` — `enable_lsp`, `lsp_timeout_seconds`, `lsp_max_references`,
  `python_lsp_server`, `typescript_lsp_server`.
- `load_lsp_settings()` — her alanı kendi ortam değişkeninden okur;
  sayısal alanlar (`get_int_env()`) malformed girdilerde uyarı loglayıp
  varsayılana düşer.
