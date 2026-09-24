# `web/middleware/ratelimit.py` — Rate-Limit / DDoS Koruması Middleware'i

- **Kaynak dosya:** `web/middleware/ratelimit.py`
- **Not dosyası:** `docs/module-notes/web/middleware/ratelimit.py.md`

**Amaç:** Sidar FastAPI uygulaması için Redis tabanlı global DDoS koruma
kovası ve GET-IO hız sınırlaması sağlar.

**Özellikler:**
- `ddos_rate_limit_middleware_impl()` — her isteği (statik/health path'leri
  hariç, `DEFAULT_DDOS_BYPASS_PATHS`/`_PREFIXES`) `redis_is_rate_limited("ddos", ...)`
  ile kontrol eder; aşım durumunda `429` döner.
- `DEFAULT_GET_IO_EXEMPT_PATHS`/`_PREFIXES` — yalnızca gerçekten ucuz/sık
  poll edilen path'ler (`/health`, `/metrics`, `/ui/`, `/static/` vb.) hız
  sınırlamasından muaf; bilinçli olarak dar tutulmuş — yeni bir GET
  endpoint'in sessizce yalnızca gevşek global DDoS kovasına düşmesini
  engellemek için varsayılan davranış GET isteklerini de POST/DELETE
  mutasyon kovasıyla aynı şekilde sınırlamaktır (opt-out listesi, opt-in
  değil).
- Bağımlılıklar `Callable` tip takma adları (`RedisRateLimitChecker`,
  `ClientIpResolver`, `RateLimitKeyResolver`) üzerinden enjekte edilir —
  Redis istemcisi ve local rate-limit durumu `web_server.py`'de yaşar.
- `parse_forwarded_ip()`, `trusted_proxy_matches(direct_ip, trusted_proxies)`,
  `get_client_ip(request, *, trusted_proxy_matches, parse_forwarded_ip)` —
  `web_server.py`'den taşınan istemci-IP çözümlemesi. Proxy başlıkları
  (`X-Forwarded-For`, `X-Real-IP`) yalnız doğrudan bağlantı
  `Config.TRUSTED_PROXIES` içindeyse okunur; `*` joker, tekil IP ve CIDR ağları
  desteklenir, geçersiz ağ girdileri atlanır, geçersiz/çok satırlı başlık
  değerleri yok sayılır.
