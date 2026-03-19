# Çözülen Teknik Borçlar ve Hata Kapanışları — v3.x Arşivi

> Bu belge, v3.0 serisinde kapatılan teknik borçları, kalite sorunlarını ve doğrulama turlarını arşivler.
> Ana durum özeti için [PROJE_RAPORU.md](../../PROJE_RAPORU.md) §11'e bakınız.

## Durum Özeti

- **Kapsam:** v3.0.4 → v3.2.0 arasında kapatılan teknik borçlar ve hata çözüm geçmişi.
- **Sonuç:** `K-1..K-2`, `Y-1..Y-6`, `O-1..O-8`, `D-1..D-14` bulguları v3.0 serisi sonunda tamamen kapatıldı.
- **Geçiş Notu:** v4.3.0 itibarıyla bu kayıtlar aktif backlog olmaktan çıkarılmış, arşiv referansı olarak korunmuştur.

## Faz Bazlı Çözüm Geçmişi

### FAZ-3 — Düşük Öncelikli Teknik Borç Temizliği (`v3.0.15`)
- `D-1`: `GPU_MEMORY_FRACTION` üst sınır dokümantasyonu doğrulandı ve yorumlar çalışma zamanı doğrulamasıyla hizalandı.
- `D-2`: `main.py` içinde port aralığı doğrulaması eklenerek hatalı CLI parametreleri fail-fast hale getirildi.
- `D-3`: Açık metrik endpoint'leri `METRICS_TOKEN` / admin erişimiyle korundu.
- `D-4`: `core/rag.py` HTML temizleme hattı `bleach` destekli daha güvenli sanitizasyona taşındı.
- `D-5`: `_build_context()` içinde LLM'e sızan sistem yolu ve repo URL ayrıntıları maskelendi.
- Aynı fazda `pytest-asyncio` standardizasyonu, `pg-stress` CI işi ve Pydantic geçiş kalıntıları da temizlendi.

### FAZ-4 — Yüksek Öncelikli Güvenlik Doğrulaması (`v3.0.16`)
- `Y-1`: `/set-level` endpoint'inin admin kısıtı doğrulandı.
- `Y-2`: RAG upload akışında dosya boyutu limiti ve `413` yanıtı doğrulandı.
- `Y-3`: `_summarize_memory()` içindeki async çağrı deseni teyit edildi.
- `Y-4`: `X-Forwarded-For` yalnızca `TRUSTED_PROXIES` üzerinden kabul edilir hale getirildi.
- `Y-5`: `get_system_info()` içinden `REDIS_URL` ifşası tamamen kaldırıldı.

### FAZ-5 — Orta Öncelikli Güvenlik Hardening (`v3.0.17`)
- `O-1`: Kritik `asyncio.Lock` nesneleri uygulama yaşam döngüsü içinde başlatıldı.
- `O-2`: RAG dosya ekleme akışı `Config.BASE_DIR` dışına taşmayı engelleyecek şekilde sınırlandı.
- `O-3`: `DOCKER_REQUIRED` ile FULL mod fallback davranışı güvenli hale getirildi.
- `O-4`: Başlatma sırasındaki senkron ayar doğrulaması `asyncio.to_thread(...)` ile non-blocking çalışır hale getirildi.
- `O-5`: WebSocket token taşıma akışı `Sec-WebSocket-Protocol` başlığına öncelik verecek şekilde düzeltildi.
- `O-6`: `run_shell` için yıkıcı komut blocklist'i eklendi.

### FAZ-6 — Son Düşük Öncelikli Kapanış (`v3.0.18`)
- `D-6`: `core/db.py` içinde erişilemez lazy-lock kontrolü kaldırıldı ve akış `assert` ile sadeleştirildi.

### FAZ-7 — Entegrasyon ve Audit Çapraz Doğrulama (`v3.0.26`)
- `O-8`: `SlackManager._init_client()` içindeki senkron `auth_test()` blokajı kaldırıldı.
- `D-7`: `core/judge.py` içinde Prometheus `Gauge()` tekrar kayıt riski modül düzeyi önbellekle kapatıldı.
- `Y-6`: `record_routing_cost()` çağrısının aktif olduğu yeniden doğrulandı.
- `O-7`: Vision / EntityMemory / FeedbackStore / Slack / Jira / Teams modüllerinin HTTP yüzeyine bağlı olduğu yeniden doğrulandı.
- Bu faz sonunda yalnızca `D-8..D-14` kümesi açık kaldı.

### FAZ-8 — Zero Debt Kapanış Turu (`v3.0.30`)
- `D-8`: `core/entity_memory.py` içindeki no-op atama kaldırıldı.
- `D-9`: `core/cache_metrics.py` için public wrapper API eklendi.
- `D-10`: `core/judge.py` içinde `Config()` yeniden örnekleme kaldırıldı.
- `D-11`: `core/vision.py` görsel yükleme yolu non-blocking hale getirildi.
- `D-12`: `core/active_learning.py` SQL placeholder standardizasyonu yapıldı.
- `D-13`: `core/hitl.py` lock başlatma akışı lazy-init ile güvenli hale getirildi.
- `D-14`: `core/hitl.py` için public `notify()` arayüzü eklendi.
- **Sonuç:** Açık kritik, yüksek, orta veya düşük bulgu kalmadı; proje `Zero Debt` durumuna geçti.

### FAZ-9 — Kurumsal İzlenebilirlik ve Handoff Doğrulaması (`v3.0.31`)
- Tenant RBAC audit trail kayıtları kalıcı hale getirildi ve testlerle doğrulandı.
- Direct `p2p.v1` handoff protokolü Supervisor + Swarm yollarında bağlam korumalı hale getirildi.
- Zero Debt sonrası kurumsal denetlenebilirlik omurgası tamamlandı.

### Ürünleştirme / Vizyon Kapanışları (`v3.2.0`)
- Active Learning/LoRA, Vision Pipeline, cost-aware routing ve Slack/Jira/Teams orkestrasyonu tek Faz-4 ürün hikâyesinde birleştirildi.
- Teknik borç kapanışları aktif backlog'tan çıkarılıp ürün kabiliyeti seviyesinde özetlenmeye başlandı.

## Doğrulama Turları

### `v3.0.6` Operasyonel Uyumsuzluklar
- `YN2-Y-1`: CI kurulumunda diskte bulunmayan `requirements.txt` çağrısı kaldırıldı.
- `YN2-O-1`: Docker socket fallback test beklentisi ile üretim davranışı arasındaki drift yeniden doğrulanıp kapatıldı.

### `v3.0.7` / `v3.0.9` Yeni Bulguların Kapatılması
- WebSocket kapanışında `_ANYIO_CLOSED` normal çıkış olarak ele alındı.
- `_rate_lock` dead-code temizlendi; testler gerçek `_local_rate_lock` akışıyla hizalandı.
- Auth endpoint'lerinde Pydantic model geçiş kalıntıları temizlendi.
- `JWT_SECRET_KEY` / `GRAFANA_URL` gibi yapılandırma yüzeyi `config.py` merkezine taşındı.

## Arşiv Kullanım Notu

Bu belge aktif risk listesi değildir. Güncel risk durumu, durum özeti paneli ve arşiv bağlantıları için [PROJE_RAPORU.md](../../PROJE_RAPORU.md) §11; denetim özeti için [AUDIT_REPORT_v4.0.md](../../AUDIT_REPORT_v4.0.md); sürümler arası özet farklar için [CHANGELOG.md](../../CHANGELOG.md) kullanılmalıdır.