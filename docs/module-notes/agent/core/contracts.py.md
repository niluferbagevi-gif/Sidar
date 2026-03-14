# 3.7e `agent/core/contracts.py`, `event_stream.py`, `memory_hub.py`, `registry.py` — Çekirdek Ajan İletişim Altyapısı

## Rapor İçeriği (Taşınan Bölüm)

**Amaç:** Multi-agent omurgasında roller arası görev sözleşmesi, canlı olay akışı ve paylaşımlı bellek/araç kayıt altyapısını sağlar.

**Kapsam:**
- `contracts.py` — `TaskEnvelope` / `TaskResult` + P2P delegasyon sözleşmeleri (`P2PMessage`, `DelegationRequest`, `DelegationResult`)
- `event_stream.py` — ajan durum ve araç olaylarını yayınlayan event bus
- `memory_hub.py` — roller arası ortak bellek erişim katmanı
- `registry.py` — çalışma zamanında rol/ajan kayıt ve çözümleme yardımcıları

**Mimari Değer:** Bu katman, `SupervisorAgent` ile rol ajanları arasında gevşek bağlı (loosely-coupled) iletişim kurarak genişletilebilirliği artırır.

---
