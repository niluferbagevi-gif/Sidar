# `web/plugins/loader.py` — Plugin Ajan Yükleme ve Kayıt

- **Kaynak dosya:** `web/plugins/loader.py`
- **Not dosyası:** `docs/module-notes/web/plugins/loader.py.md`

**Amaç:** Admin'in yüklediği plugin kaynağını sandbox'ta çalıştırıp
`BaseAgent` türevi sınıfı bulur, dosyayı `plugins/` altına kaydeder ve sınıfı
`AgentRegistry`'ye yerleşik olmayan (`is_builtin=False`) rol olarak kaydeder.
`web_server.py`'den taşındı; sandbox çalıştırıcı, `BaseAgent`, `AgentRegistry`
ve dosya boyutu sınırı `web_server` sarmalayıcıları tarafından çağrı anında
enjekte edilir.

**Özellikler:**
- `PLUGIN_ROLE_RE`, `validate_plugin_role_name()`, `sanitize_capabilities()`.
- `load_plugin_agent_class(...)` — `docker` backend'inde izole proxy
  (`PluginSandboxError` → 503); aksi halde in-process sandbox namespace'inden
  sınıfı seçer. Kanonik `agent.base_agent.BaseAgent` ile çağıranın `BaseAgent`
  referansını birlikte dener, farklı modül kimlikleri için isim/MRO kontrolü yapar.
- `validate_and_persist_plugin_file(...)` — kaynağı sandbox'ta doğrular, sonra
  `plugins/<ad>.py` olarak yazar.
- `register_plugin_agent(...)`, `register_uploaded_plugin(...)` — kayıt ve
  yükleme uç noktası akışı (boş dosya 400, boyut aşımı 413, UTF-8 dışı 400).
