# `web/autonomy_bridge.py` — Otonomi Tetikleyici Köprüsü

- **Kaynak dosya:** `web/autonomy_bridge.py`
- **Not dosyası:** `docs/module-notes/web/autonomy_bridge.py.md`

**Amaç:** Web API katmanının paylaştığı otonomi tetikleyici yardımcıları;
kullanıcısız (userless) otonom tetikleyicilerin hangi servis aktörü adına
çalıştığını belirler ve olay-güdümlü (event-driven) federasyon görev
akışlarını (`agent/swarm.py`'nin `SwarmTask`'ı ve
`agent/core/contracts.py`'nin `FederationTaskEnvelope`/`FederationTaskResult`
sözleşmeleri üzerinden) kurar/çalıştırır.

**Özellikler:**
- `autonomy_service_actor(config, trigger_source)` — `AUTONOMY_SERVICE_USER_ID`
  → `SYSTEM_USER_ID` → `"system:autonomy"` öncelik zinciriyle açık servis
  aktörünü çözer (audit log'da "kimin" tetiklediğini izlenebilir kılar).
- `trim_autonomy_text(value, limit=1200)` — otonomi metinlerini güvenli
  uzunlukta kırpar.
- `build_event_driven_federation_spec(...)`, `build_swarm_goal_for_role(...)`
  — olaydan federasyon görev spesifikasyonu ve rol bazlı swarm hedefi kurar.
- `run_event_driven_federation_workflow(...)` (async) — spec'i uçtan uca
  çalıştırır.
- `embed_event_driven_federation_payload(...)` — sonucu event payload'ına
  gömer.
