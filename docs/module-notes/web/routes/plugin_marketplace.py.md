# `web/routes/plugin_marketplace.py` — Plugin Marketplace Durum Yönetimi

- **Kaynak dosya:** `web/routes/plugin_marketplace.py`
- **Not dosyası:** `docs/module-notes/web/routes/plugin_marketplace.py.md`

**Amaç:** Plugin marketplace katalog verisi, disk-üzeri kurulum durumu
kalıcılığı ve kurulum/kaldırma/yeniden yükleme orkestrasyonunu barındırır.
Bu state yönetimi eskiden `web_server.py`'de rota kaydıyla ve düzinelerce
ilgisiz alt sistemle iç içeydi; `web_server.py` artık mevcut monkeypatch
tabanlı testlerin (`_read_plugin_marketplace_state`,
`_register_plugin_agent` gibi tekil collaborator'ları `web_server` üzerinde
patch eden) aynı isimleri gözlemlemeye devam etmesi için ince sarmalayıcı
fonksiyonlar tutar — bir çağıranın override etmek isteyebileceği her
çapraz-fonksiyon çağrısı, modül-içi referans yerine açık parametre olarak
thread edilir.

**Özellikler:**
- `plugin_marketplace_state_path()` — durum dosyasının yolunu çözer.
- `read_plugin_marketplace_state(*, logger_obj=logger)`,
  `write_plugin_marketplace_state(state)` — disk-üzeri kalıcılık.
- `get_plugin_marketplace_entry(...)`, `serialize_marketplace_plugin(...)` —
  katalog sorgulama/serileştirme.
- `install_marketplace_plugin(...)`, `uninstall_marketplace_plugin(...)`,
  `reload_persisted_marketplace_plugins(...)` — kurulum yaşam döngüsü
  orkestrasyonu.
