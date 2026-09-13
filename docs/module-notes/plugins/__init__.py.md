# `plugins/__init__.py` — Plugin Paketi Girişi

- **Kaynak dosya:** `plugins/__init__.py`
- **Not dosyası:** `docs/module-notes/plugins/__init__.py.md`

**Amaç:** `plugins` paketinin dışa açtığı yüzeyi tanımlar; yalnızca
`plugins/manifest.py`'deki sözleşme sabitlerini yeniden dışa aktarır
(`EXTERNAL_SERVICE_PLUGIN_IDS`, `PLUGIN_MANIFESTS`, `PluginManifest`) —
tüketicilerin (`web/routes/plugin_marketplace.py`,
`web/plugins/sandbox.py`) tek bir import noktasından manifest verisine
erişmesini sağlar.
