# `agent/bootstrap.py` — SidarAgent Başlangıç Loglaması

- **Kaynak dosya:** `agent/bootstrap.py`
- **Not dosyası:** `docs/module-notes/agent/bootstrap.py.md`

**Amaç:** `SidarAgent` başlatıldığında sürüm/sağlayıcı/model/erişim
seviyesi/bellek backend'i/runtime modu bilgisini tek merkezi bir log
satırında toplayan yardımcı.

**Özellikler:**
- `log_sidar_agent_startup(version, cfg)` — `cfg`'den `RAG_VECTOR_BACKEND`,
  `APP_RUNTIME_MODE` gibi alanları güvenli biçimde (eksikse `"unknown"`)
  okuyup tek bir `INFO` log satırı basar.
