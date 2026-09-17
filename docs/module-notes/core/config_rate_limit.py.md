# `core/config_rate_limit.py` — Rate Limit / Redis / Health Ayarları

- **Kaynak dosya:** `core/config_rate_limit.py`
- **Not dosyası:** `docs/module-notes/core/config_rate_limit.py.md`

**Amaç:** API rate-limit pencereleri, Redis bağlantısı ve bağımlılık health-
check ayarlarını `RateLimitSettings` frozen dataclass'ı olarak yükler;
`web/middleware/ratelimit.py`'nin okuduğu üst düzey ayar kaynağıdır.

**Özellikler:**
- `RateLimitSettings` — `sidar_rate_limit_window`, `sidar_rate_limit_chat`,
  `sidar_rate_limit_mutations` (ve benzeri kategori bazlı limitler).
- Redis URL'i `urllib.parse` ile şifre/host bileşenlerini güvenli encode
  ederek kurar; `SIDAR_*` önekli / legacy anahtar ayrımı `config_env_helpers`
  prefixed helper'larıyla yönetilir.
