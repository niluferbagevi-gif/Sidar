# agent/core/event_backends/

- **Kaynak dizini:** `agent/core/event_backends/` (`__init__.py`, `base.py`,
  `kafka_backend.py`, `rabbitmq_backend.py`, `redis_backend.py`)
- **Not dosyası:** `docs/module-notes/agent/core/event_backends.md`

## Amaç

`agent/core/event_stream.py`'nin `AgentEventBus`'ı, uzak transport'a event
yayınlama davranışını bu paketteki strategy nesnelerine devrediyor.
`base.py::BaseEventBusBackend`, `abc.ABC` tabanlı iki soyut metotla sözleşmeyi
tanımlıyor: `schedule_bootstrap()` (bağlantı/dinleyici kurulumunu zamanlar) ve
`async publish(evt)` (event'i backend'e yollar, `bool` döner). Kurucusu yalnızca
sahip `AgentEventBus` referansını (`self.bus`) tutuyor.

Üç somut backend (`KafkaBackend`, `RabbitMQBackend`, `RedisBackend`) kasıtlı
olarak ince: her biri iki metodu da doğrudan `AgentEventBus`'ın aynı isimli özel
metotlarına devrediyor (örn. `KafkaBackend.publish` → `bus._publish_via_kafka`).
Gerçek bağlantı/yeniden-deneme/serileştirme mantığı bilinçli olarak
`event_stream.py` içinde kalıyor; bu paket yalnızca hangi backend'in seçildiğini
(`AgentEventBus._backend`) tip-güvenli bir arayüze bağlıyor.

## Kullanım noktası

`event_stream.py::AgentEventBus._build_backends()` üç backend'i lazy import
string'leriyle (`"agent.core.event_backends.redis_backend:RedisBackend"` vb.)
yükleyip `self._backends: dict[str, BaseEventBusBackend]` sözlüğüne dolduruyor;
bilinmeyen/yapılandırılmamış bir backend adı `redis`'e düşüyor
(`self._backends.get(self._backend, self._backends["redis"])`). `redis` ve
`kafka`, circuit-breaker açısından "remote" backend sayılıyor
(`_is_remote_circuit_backend`); `rabbitmq` bu davranışın dışında tutuluyor.

## Test kapısı

Bu üç backend'in `publish`/`schedule_bootstrap` delegasyonu
`tests/unit/agent/core/test_event_stream.py` içinde `AgentEventBus`'ın kendi
private metotları mock'lanarak dolaylı test ediliyor; paketin kendi başına ayrı
bir test dosyası yok.
