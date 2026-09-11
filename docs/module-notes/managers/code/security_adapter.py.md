# `managers/code/security_adapter.py` — CodeManager Güvenlik Politikası Adaptörü

- **Kaynak dosya:** `managers/code/security_adapter.py`
- **Not dosyası:** `docs/module-notes/managers/code/security_adapter.py.md`

**Amaç:** `CodeSecurityAdapter` sınıfı, `CodeManager`'ın dosya IO kodunu
gerçek güvenlik politikası detaylarından bağımsız tutan ince bir sarmalayıcı
sağlar — `managers/code/file_io_security.py`'nin doğrudan çağırdığı
`can_read()`/`can_write()`/`safe_write_denial()`/`is_path_under()` arayüzünü
tanımlar, gerçek politika mantığını enjekte edilen `security` nesnesine
(`self._security`) delege eder. `safe_write_denial()`, yazma reddedildiğinde
kullanıcıya güvenli bir alternatif yol (`get_safe_write_path()`) önerir.
