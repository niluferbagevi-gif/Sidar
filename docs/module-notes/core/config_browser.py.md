# `core/config_browser.py` — Tarayıcı Otomasyon Ayarları

- **Kaynak dosya:** `core/config_browser.py`
- **Not dosyası:** `docs/module-notes/core/config_browser.py.md`

**Amaç:** `managers/browser_manager.py`'nin Playwright/CDP tabanlı tarayıcı
otomasyonu için kullandığı 4 alanı (`BROWSER_PROVIDER`, `BROWSER_HEADLESS`,
`BROWSER_TIMEOUT_MS`, `BROWSER_ALLOWED_DOMAINS`) `BrowserSettings` frozen
dataclass'ı olarak yükler; `config.Config` bunu `browser_settings` olarak
expose eder ve aynı 4 alanı geriye dönük uyumlu `Config.FOO` class
attribute'larına delege eder (`docs/REFACTOR_PLAN.md`'nin `config.py`
maddesinde multimodal vision/ses diliminden sonra işaretlenen sıradaki
düşük riskli dilim). `managers/browser_manager.py`'nin `getattr(self.cfg,
"BROWSER_PROVIDER", "auto")` gibi mevcut alan adlarıyla tüketmesi
değişmeden korunur.

**Özellikler:**
- `BrowserSettings` — `browser_provider`, `browser_headless`,
  `browser_timeout_ms`, `browser_allowed_domains` (`list[str]`).
- `load_browser_settings()` — her alanı kendi ortam değişkeninden okur;
  `BROWSER_ALLOWED_DOMAINS` virgülle ayrılmış liste olarak
  (`get_list_env()`) ayrıştırılır, `BROWSER_TIMEOUT_MS` malformed
  girdide uyarı loglayıp varsayılana düşer.
