# 3.4 `web_server.py` — FastAPI Web Sunucusu (2.635 satır)

## Büyüme Politikası (Zorunlu — CI'da Denetlenir)

`web/app_factory.py` ve `web/routes/plugin_marketplace.py`'nin kendi
docstring'leri `web_server.py`'nin ince, geriye dönük uyumlu bir sarmalayıcı
kalması gerektiğini belgeler — ama daha önce bunu zorlayan hiçbir mekanizma
yoktu ve dosya sessizce büyümeye devam etti (1.376 → 2.628 satır). Bu artık
`scripts/ci/check_web_server_size_baseline.py` ile (CI'da `Base quality
gates` job'ının parçası) tek yönlü bir bütçe olarak zorlanır:
`scripts/ci/web-server-size-baseline.json`'daki `maximum_lines` değeri
aşılırsa CI kırmızı olur. Bu notun kendisi ve `web_server.py`'nin tepesindeki
politika paragrafı ilk kez eklendiğinde dosya 2.628 → 2.635 satıra çıktı;
bu istisnai artış bilinçli, incelenmiş bir dokümantasyon eklemesidir —
budget aynı commit'te bu yeni gerçek sayıya ayarlanmıştır.

**Kural:** Yeni route/middleware/plugin mantığı `web_server.py`'ye değil,
`web/routes/` altındaki yeni veya var olan bir modüle eklenmelidir
(`web/routes/*.py` zaten iyi modülerleştirilmiştir — bkz. o dizindeki her
dosyanın kendi notu). `web_server.py` yalnızca FastAPI app kurulumunu,
geriye dönük uyumlu ince sarmalayıcıları (ör. eski `_read_plugin_marketplace_state`
gibi isimleri hâlâ monkeypatch eden testler için) ve gerçekten tek bir
yerde yaşaması gereken üst düzey orkestrasyonu barındırmalıdır. Baseline'ı
yükseltmek yalnızca dosyadan gerçekten mantık çıkarılamayan, incelenmiş bir
istisna durumunda yapılmalıdır — script bunu otomatik ratchetlemez (bkz.
`check_web_server_size_baseline.py`'nin kendi docstring'i); gerçek bir
azaltım sonrası ise değer elle düşürülmelidir.

## Rapor İçeriği (Taşınan Bölüm)

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
