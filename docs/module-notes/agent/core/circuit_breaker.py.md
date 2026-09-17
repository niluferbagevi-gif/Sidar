# `agent/core/circuit_breaker.py` — Swarm/P2P Circuit Breaker

- **Kaynak dosya:** `agent/core/circuit_breaker.py`
- **Not dosyası:** `docs/module-notes/agent/core/circuit_breaker.py.md`

**Amaç:** Swarm/doğrudan P2P handoff çağrılarında tekrarlayan hataları
tespit edip devreyi geçici olarak açan, basit sayaç tabanlı circuit
breaker.

**Özellikler:**
- `_BreakerState` (dataclass) — `failures`, `opened_at`.
- `SwarmCircuitBreaker` — `MAX_FAILURES = 3`, `RESET_AFTER_SECONDS = 60`;
  ardışık hata eşiğini aşan bir hedefe yapılan delegasyon çağrılarını
  geçici olarak keser, süre dolunca yeniden dener.
