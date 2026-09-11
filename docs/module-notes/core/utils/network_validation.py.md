# `core/utils/network_validation.py` — Ağ Host/IP Güvenlik Doğrulaması

- **Kaynak dosya:** `core/utils/network_validation.py`
- **Not dosyası:** `docs/module-notes/core/utils/network_validation.py.md`

**Amaç:** Bandit B104 (tüm arayüzlere bind) uyarısını `# nosec` ile
bypass etmek yerine, gelen host değerinin gerçekten beklenen sınıfa
(loopback/unspecified/geçerli IP/geçerli hostname) ait olup olmadığını
`ipaddress` modülü üzerinden gerçekten doğrular. Production profilinde
(`SIDAR_ENV=production`) `0.0.0.0`/`::` gibi tüm arayüzlere bağlanan
değerler, açıkça `SIDAR_ALLOW_PUBLIC_BIND=true` verilmediği sürece
reddedilir. `web/cli.py`'nin bağlanma host doğrulamasının kaynağı.

**Özellikler:**
- `LOOPBACK_HOSTNAMES` — bilinen loopback hostname sabitleri.
- `is_unspecified_bind(host)`, `is_loopback_host(host)`,
  `is_local_only_host(host)`, `is_valid_hostname(host)` — host sınıflandırma.
- `is_production_env(env=None)`, `is_public_bind_allowed(flag=None)` —
  ortam/bayrak kontrolü.
- `validate_bind_host(...)` — production'da güvensiz genel bind'i reddeden
  ana doğrulama fonksiyonu (fail-closed).
