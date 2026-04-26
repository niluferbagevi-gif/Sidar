# AgentEventBus Refactor Plan (SRP Odaklı)

## Problem

`AgentEventBus` tek sınıf içinde şu sorumlulukları birlikte taşıyor:

- In-memory subscriber yönetimi (`subscribe`, `unsubscribe`, `fanout`, buffered drain)
- Backend bağlantı bootstrap'leri (Redis / RabbitMQ / Kafka)
- Backend'e publish
- Backend listener loop'ları
- DLQ yazımı ve kaynak temizliği

Bu yoğunluk, sınıfın test edilmesini ve değişiklik güvenliğini zorlaştırıyor.

## Hedef Mimari

Sorumlulukları küçük, bağımsız birimlere ayırmak:

1. `LocalEventRouter`
   - Subscriber queue yönetimi
   - Buffer ve fanout politikası
2. `RedisEventTransport`
   - Redis bootstrap / listener / publish / cleanup
3. `RabbitEventTransport`
   - RabbitMQ bootstrap / listener / publish / cleanup
4. `KafkaEventTransport`
   - Kafka bootstrap / listener / publish / cleanup
5. `DeadLetterSink`
   - DLQ buffer + opsiyonel remote DLQ yazımı
6. `AgentEventBus` (Orkestratör)
   - Hangi backend'in aktif olduğu bilgisini taşıyan ince katman
   - `publish()` çağrısında local fanout + seçili transport publish delegasyonu

## Geçiş Stratejisi (Backward-Compatible)

### Faz 1 (Düşük Risk)

- Payload serileştirme/parse mantığını ortak helper'lara taşı.
- Backend dispatch kararını map tabanlı yapıya çek (if/else dallarını azalt).
- Backend routing için `BaseEventBusBackend` + concrete strategy sınıfları
  (`RedisBackend`, `RabbitMQBackend`, `KafkaBackend`) ekleyerek
  `AgentEventBus` içinde strategy tabanlı delegasyon başlat.
- Mevcut public/private API'yi koru.

### Faz 2 (Orta Risk)

- Redis/Rabbit/Kafka kodunu transport sınıflarına taşı.
- `AgentEventBus` üzerinde mevcut private method adlarını wrapper olarak koru
  (testlerin kırılmaması için).

### Faz 3 (Temizlik)

- Doğrudan transport testlerini ayrı dosyalara böl.
- `AgentEventBus` testlerini entegrasyon seviyesine indir.
- Internal API bağımlı testleri (private attr/method) kademeli azalt.

## Test Stratejisi

- Her transport için ayrı unit test dosyası:
  - bootstrap success/failure
  - publish success/failure
  - listener valid/invalid payload
  - cleanup (task cancel + resource close)
- `AgentEventBus` için:
  - backend routing
  - local fallback davranışı
  - DLQ akışı entegrasyon kontrolü

## Beklenen Kazanımlar

- Daha küçük sınıflar, daha okunabilir kod
- Hedefli testler ile daha hızlı hata izolasyonu
- Yeni backend eklemelerinde (ör. NATS) daha düşük değişiklik maliyeti
