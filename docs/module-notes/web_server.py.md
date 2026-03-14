# 3.4 `web_server.py` — FastAPI Web Sunucusu (1.376 satır)

**Amaç:** WebSocket destekli asenkron chat, DB tabanlı kimlik doğrulama ve kurumsal metrik/bütçe uçlarını tek API yüzeyinde sunar.

**Kurumsal v3.0 Öne Çıkanlar:**
- **Bearer Token middleware:** HTTP isteklerinde zorunlu kimlik doğrulama (`basic_auth_middleware`).
- **Auth uçları:** `/auth/register`, `/auth/login`, `/auth/me`.
- **Bütçe/telemetri uçları:** `/api/budget`, `/metrics/llm`, `/metrics/llm/prometheus`.
- **WebSocket Auth Handshake:** `/ws/chat` bağlantısında ilk mesajın `action="auth"` ve geçerli token içermesi zorunlu; aksi durumda policy violation ile bağlantı kapatılır.

**Temel API Endpoint'leri (özet):**

| Endpoint | Metod | Açıklama |
|----------|-------|----------|
| `/` | GET | `index.html` servis et |
| `/static/*` | GET | JS/CSS statik dosyaları |
| `/auth/register` | POST | Yeni kullanıcı kaydı |
| `/auth/login` | POST | Giriş + access token üretimi |
| `/auth/me` | GET | Aktif kullanıcı kimliği |
| `/ws/chat` | WS | Auth handshake + çift yönlü chat akışı |
| `/api/budget` | GET | LLM maliyet/token/latency bütçe özeti |
| `/metrics/llm` | GET | LLM metrik snapshot (JSON) |
| `/metrics/llm/prometheus` | GET | Prometheus formatında LLM metrikleri |
| `/sessions*` | GET/POST/DELETE | Kullanıcıya izole oturum CRUD işlemleri |

---
