# `plugins/upload_agent.py` — Upload Marketplace Demo Eklentisi

- **Kaynak dosya:** `plugins/upload_agent.py`
- **Not dosyası:** `docs/module-notes/plugins/upload_agent.py.md`

**Amaç:** Yüklenen (hot-loaded) plugin akışlarını uçtan uca sınamak için
minimum, yan etkisiz demo ajanı; `plugins/manifest.py`'de
`side_effect_level="none"`, `supports_dry_run=True` olarak işaretlidir.

**Özellikler:**
- `UploadAgent.run_task(task_prompt)` — boş prompt için sabit bir uyarı
  döner, aksi halde gelen metni `"UploadAgent: ..."` öneki ile aynen
  yankılar (echo) — plugin yükleme/sandbox/marketplace kurulum
  akışlarının davranışını doğrulamak için kullanılır.

## İlgili modüller

`plugins/manifest.py` (`upload` manifesti),
`web/routes/plugin_marketplace.py`, `web/plugins/sandbox.py`.
