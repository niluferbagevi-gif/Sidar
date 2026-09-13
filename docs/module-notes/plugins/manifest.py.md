# `plugins/manifest.py` — Plugin Sözleşme Metadatası

- **Kaynak dosya:** `plugins/manifest.py`
- **Not dosyası:** `docs/module-notes/plugins/manifest.py.md`

**Amaç:** Sidar marketplace eklentileri için salt-okunur, statik sözleşme
metadatası. Runtime plugin yükleme bu manifesti incelemek için
kullanabilir; testler/CI her eklentinin yan etkilerini, kimlik doğrulama
ihtiyacını, dry-run desteğini ve mock tabanlı sözleşme fikstürünü
bildirdiğini bu manifest üzerinden doğrulayabilir.

**Özellikler:**
- `SideEffectLevel` — `"none" | "local_read" | "local_write" |
  "external_read" | "external_write"` yan etki seviyesi türü.
- `PluginManifest` (frozen dataclass) — `plugin_id`, `role_name`,
  `module`, `class_name`, `capabilities`, `side_effect_level`,
  `requires_auth`, `secret_names`, `supports_dry_run`, `test_fixture`,
  `external_services`, `requires_mocked_contract_tests` alanları.
- `PLUGIN_MANIFESTS` — dört yerleşik eklentinin (`aws_management`,
  `crypto_price`, `slack_notifications`, `upload`) manifestlerini tutan
  sözlük; her biri kendi kaynak modülünü/sınıfını, gerekli secret
  adlarını ve test fikstür yolunu bildirir.
- `EXTERNAL_SERVICE_PLUGIN_IDS` — dış servise yazan/okuyan (harici
  bağımlılığı olan) eklenti kimliklerinin kümesi.
- `get_plugin_manifest(plugin_id)` — bir eklenti kimliği için manifesti
  döner.

## İlgili modüller

`plugins/aws_management_agent.py`, `plugins/crypto_price_agent.py`,
`plugins/slack_notification_agent.py`, `plugins/upload_agent.py`,
`web/routes/plugin_marketplace.py`.
