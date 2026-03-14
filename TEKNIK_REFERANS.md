# Sidar v3.0.0 — Teknik Referans ve Operasyon Kılavuzu

Bu doküman, Sidar AI projesinin derin teknik altyapısını; veritabanı şemasını, API/WebSocket sözleşmelerini ve operasyonel (DevOps/FinOps) çalışma notlarını içerir.

> Üst düzey mimari değerlendirme, güvenlik özeti, test kapsamı ve teknik borç takibi için `PROJE_RAPORU.md` dosyasını kullanın.

---

## 1) Veri Modeli ve Veritabanı Şeması (ER Perspektifi)

Sidar veri katmanı `core/db.py` üzerinden yönetilir ve hem PostgreSQL (`asyncpg`) hem de SQLite (`aiosqlite`) ile uyumludur.

### 1.1 Temel Tablolar

- `users`
  - Kimlik ve yetki alanları: `id`, `username`, `password_hash`, `role`, `created_at`
- `auth_tokens`
  - Bearer token oturumları: `token`, `user_id`, `expires_at`, `created_at`
  - `users.id` → `auth_tokens.user_id` (1:N)
- `sessions`
  - Sohbet oturumları: `id`, `user_id`, `title`, `created_at`
  - `users.id` → `sessions.user_id` (1:N)
- `messages`
  - Oturum içi mesajlar: `id`, `session_id`, `role`, `content`, `created_at`
  - `sessions.id` → `messages.session_id` (1:N)
- `user_quotas`
  - Günlük kullanıcı kotaları: `daily_token_limit`, `daily_request_limit`
- `provider_usage_daily`
  - Sağlayıcı bazlı günlük kullanım: `provider`, `usage_date`, `requests_used`, `tokens_used`

### 1.2 Kota/FinOps Akışı (Özet)

1. İstek başına token/kullanım bilgisi `provider_usage_daily` üzerinde artırılır.
2. Kullanıcının limitleri `user_quotas` üzerinden okunur.
3. Limit aşımında uygulama katmanı 429 ve ilgili hata mesajı üretir.

### 1.3 Notlar

- Tablo oluşturma ve indeksler, DB backend'ine göre uyumlu SQL ile hazırlanmıştır.
- Şema sürümü için `schema_versions` tablosu (`DB_SCHEMA_VERSION_TABLE`) kullanılır.

---

## 2) API ve WebSocket Referansı

Sunucu katmanı FastAPI (`web_server.py`) üzerindedir.

### 2.1 Kimlik ve Kullanıcı API'leri

- `POST /auth/register` — Yeni kullanıcı kaydı
- `POST /auth/login` — Giriş + bearer token üretimi
- `GET /auth/me` — Aktif token kimlik doğrulaması
- `GET /admin/stats` — Admin istatistik özeti (rol kontrollü)

### 2.2 Chat/Session API'leri

- `GET /sessions` — Kullanıcıya ait oturumları listeler
- `POST /sessions/new` — Yeni oturum oluşturur
- `GET /sessions/{session_id}` — Oturum mesaj geçmişini döner

### 2.3 RAG / Doküman API'leri

- `GET /rag/docs` — RAG belge listesini döner
- `POST /rag/add-file` — Yerel dosyadan RAG ekleme
- `POST /rag/add-url` — URL'den içerik çekip RAG ekleme
- `POST /api/rag/upload` — Dosya upload ile RAG ekleme

### 2.4 Gözlemlenebilirlik ve Bütçe API'leri

- `GET /metrics` — Genel metrik endpoint'i
- `GET /metrics/llm/prometheus` — Prometheus formatında LLM metrikleri
- `GET /metrics/llm` — JSON LLM metrik özeti
- `GET /api/budget` — Kullanıcı bütçe/kota kullanım özeti

### 2.5 GitHub/Webhook API'leri

- `GET /github-repos`, `POST /set-repo`, `GET /github-prs/{number}`, vb.
- `POST /api/webhook` — GitHub webhook alımı (HMAC doğrulama)

### 2.6 WebSocket Protokolü (`/ws/chat`)

- Endpoint: `ws://<host>/ws/chat`
- Auth handshake zorunludur; policy ihlalinde bağlantı `1008` ile kapatılır.

Örnek istemci akışı:

```json
{"action": "auth", "token": "<bearer>"}
```

```json
{"action": "message", "content": "..."}
```

Olası sunucu event tipleri (örnek):

- `{"type":"thought","content":"..."}`
- `{"type":"tool","name":"...","argument":"..."}`
- `{"type":"token","content":"..."}`

---

## 3) Konfigürasyon Profilleri ve Ortam Değişkenleri

Bu bölüm, ayrıntılı `.env` sözlüğünün yerini almak yerine teknik operasyonu etkileyen kritik anahtarları özetler.

### 3.1 Uygulama Konfigürasyonu (Config)

- `AI_PROVIDER`, `*_API_KEY`, `*_MODEL`, `*_TIMEOUT`
- `LLM_MAX_RETRIES`, `LLM_RETRY_BASE_DELAY`, `LLM_RETRY_MAX_DELAY`
- `ACCESS_LEVEL`, `API_KEY`
- `DATABASE_URL`, `DB_POOL_SIZE`, `DB_SCHEMA_*`
- `ENABLE_TRACING`, `OTEL_EXPORTER_ENDPOINT`
- `REVIEWER_TEST_COMMAND`
- `ENABLE_MULTI_AGENT` kod içinde sabittir (`True`) ve `.env` ile kapanmaz.

### 3.2 Ortam Katmanlama

- Sistem önce `.env`, sonra varsa `.env.<profil>` yükler.
- Profil seçimi `SIDAR_ENV` ile yapılır.

### 3.3 Docker Compose Override'ları

- `SIDAR_*_CPU_LIMIT`, `SIDAR_*_MEM_LIMIT`
- `HOST_GATEWAY`
- `NVIDIA_VISIBLE_DEVICES`, `NVIDIA_DRIVER_CAPABILITIES`
- `WEB_PORT`, `WEB_GPU_PORT`

---

## 4) FinOps, Rate Limiting ve Kota Yönetimi

### 4.1 İki Katmanlı Koruma

1. **Anlık trafik koruması (Rate Limiting)**
   - HTTP/WS seviyesinde pencere bazlı limitler
   - Redis varsa dağıtık/persist sayım
2. **Kalıcı günlük kota (DB tabanlı)**
   - `user_quotas` + `provider_usage_daily`
   - Token ve request limiti ayrı takip edilir

### 4.2 Operasyon Önerileri

- Üretimde Redis kullanımı önerilir (`REDIS_URL`).
- Bütçe endpoint'i ve Prometheus metrikleri birlikte izlenmelidir.

---

## 5) Agent Çalışma Modeli, Prompt ve Bağlam

### 5.1 Çalışma Omurgası

- Dış çağrı `SidarAgent.respond()` ile alınır.
- Görevler tek omurga olarak `SupervisorAgent`'a devredilir.
- QA geri-besleme döngüsü `MAX_QA_RETRIES=3` sınırı ile korunur.

### 5.2 Prompt Kaynakları

- Sistem promptu, proje talimat dosyalarıyla zenginleştirilir:
  - `SIDAR.md`
  - `CLAUDE.md`
- Araç listesi çalışma anında tool dispatch yapısından üretilir.

### 5.3 Bellek ve Arşiv

- Kısa dönem bellek: tur bazlı, `MAX_MEMORY_TURNS` ile sınırlandırılır.
- Uzun dönem bağlam: `memory_archive` kaynağından semantik geri çağırma yapılır.

---

## 6) GitHub Operasyon Araçları (PR + Issue)

Ajan araç setinde sadece PR değil, Issue yaşam döngüsü de vardır:

- PR tarafı: listeleme, detay, yorum, kapatma, diff, smart PR akışı
- Issue tarafı: `github_list_issues`, `github_create_issue`, `github_comment_issue`, `github_close_issue`

Bu araçlar, `GITHUB_TOKEN` ve hedef repo ayarları (`GITHUB_REPO`) ile etkinleşir.

---

## 7) Gözlemlenebilirlik (Observability)

### 7.1 Metrikler

- Prometheus endpoint'leri üzerinden LLM maliyet/token/latency görünürlüğü
- Bütçe endpoint'i ile kullanıcı bazlı kullanım takibi

### 7.2 Tracing

- `ENABLE_TRACING=true` olduğunda OTLP exporter akışı devreye alınabilir.
- Araç çalıştırma süreleri ve başarı bilgileri span attribute olarak taşınır.

### 7.3 Dashboard

- Compose ile `prometheus` + `grafana` servisleri ayağa kaldırılabilir.

---

## 8) Dağıtım, Çalıştırma ve Kurtarma Notları

### 8.1 Temel Çalıştırma

- CLI/CPU: `sidar-ai`
- CLI/GPU: `sidar-gpu`
- Web/CPU: `sidar-web`
- Web/GPU: `sidar-web-gpu`

### 8.2 Veri Kalıcılığı

- `data/`, `logs/`, `temp/` mount edilir.
- RAG/vektör içerik ve DB dosyaları bu alanlarda kalıcı tutulur.

### 8.3 Yedekleme Önerisi

- PostgreSQL: düzenli `pg_dump`
- SQLite: `data/sidar.db` periyodik kopya
- RAG/veri dizinleri: düzenli snapshot/backup

---

## 9) Sorun Giderme Hızlı Rehberi

- **Supervisor izleri görünmüyor:** `LOG_LEVEL=DEBUG` ile doğrula, süreci yeniden başlat.
- **429 dalgaları:** sağlayıcı limiti + günlük kota + rate limit katmanlarını birlikte kontrol et.
- **WebSocket kopmaları (`1008`):** auth handshake paketini ilk mesaj olarak gönder.
- **GitHub araçları pasif:** `GITHUB_TOKEN` / `GITHUB_REPO` ayarlarını doğrula.
- **Sandbox sorunları:** Docker daemon, runtime ve kaynak limitlerini kontrol et.

---

## 10) Doküman Bakım Prensipleri

- Mimari kararlar ve yönetici özeti: `PROJE_RAPORU.md`
- Operasyonel/API/şema detayları: `TEKNIK_REFERANS.md`

Bu ayrım, dokümantasyon bloat riskini azaltır ve değişikliklerin doğru hedef kitleye hızlı aktarılmasını sağlar.