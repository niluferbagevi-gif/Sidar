# 3.21 `core/llm_metrics.py` — Telemetri ve Bütçe Yönetimi

## Rapor İçeriği (Taşınan Bölüm)

**Amaç:** LLM çağrılarının operasyonel metriklerini toplamak, Prometheus'a aktarmak ve veritabanı üzerinden günlük kullanıcı kotalarını izlemek.

> Doğrulama notu: Bu bölüm, `wc -l core/llm_metrics.py` çıktısına göre dosya uzunluğunun 235 satır olduğu güncel sürümle hizalanmıştır.

**Özellikler:**
- `LLMMetricsManager` üzerinden token kullanımı (prompt, completion) ve işlem süresi (latency) ölçümü.
- API maliyetlerinin (USD bazında) model bazlı dinamik fiyat tablosu ile hesaplanması (`prompt`/`completion` token ayrımı).
- Prometheus uyumlu sayaç/ölçüm metriklerinin (`Counter`, `Histogram`, `Gauge`) dışa aktarımı; özellikle istek sayısı, token toplamı, maliyet ve gecikme dağılımı için panel uyumluluğu.
- Eşzamanlı isteklerde güvenli metrik güncellemesi için `threading.Lock` tabanlı kritik bölüm yaklaşımı ve process-içi tek toplayıcı erişim deseni.
- Grafana dashboard'ları için kurumsal metrik (observability) verisi sağlanması.

---
