# `core/distributed_lock.py` — Pod'lar Arası Dağıtık Kilit

- **Kaynak dosya:** `core/distributed_lock.py`
- **Not dosyası:** `docs/module-notes/core/distributed_lock.py.md`

**Amaç:** Çoklu-pod/çoklu-worker dağıtımlarında karşılıklı dışlama
(mutual exclusion) sağlayan Redis tabanlı `RedisDistributedLock` sınıfı.

**Özellikler:**
- Redis `SET NX PX` ile lease tabanlı kilit alımı — sahip pod ölürse Redis
  key'i otomatik expire eder, başka bir pod ilerleyebilir (en iyi çaba,
  kesin distributed-consensus garantisi değil).
- Serbest bırakma, token doğrulamalı bir Lua script'i (`_RELEASE_LOCK_SCRIPT`)
  ile yapılır — bu sayede bir pod, başka bir pod'un yenilediği/yeniden
  aldığı lease'i yanlışlıkla silemez.
- `DistributedLockLease` (frozen dataclass) — alınan kilidin `key`/`token`/`ttl_ms`
  meta verisini taşır, güvenli serbest bırakma için gereklidir.
- `RedisDistributedLock.from_url()` — bağlantı havuzu boyutu ve zaman aşımı
  parametreleriyle doğrudan bir Redis URL'inden istemci kurar.
