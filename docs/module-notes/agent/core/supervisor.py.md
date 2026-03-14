# 3.7d `agent/core/supervisor.py` — Yönlendirici (Supervisor) Ajan (164 satır)

**Amaç:** Kullanıcı niyetini analiz edip görevi uygun role yönlendiren orkestrasyon katmanı.

> Not (Doğrulama): Bu rapordaki satır sayısı, güncel depoda `wc -l agent/core/supervisor.py` çıktısına göre **164** olarak ölçülmüştür.

**Öne Çıkanlar:**
- Intent/role routing (`_intent`: research / review / code)
- `TaskEnvelope`/`TaskResult` sözleşmeleriyle uyumlu görev yönetimi (`_delegate`)
- Coder ↔ Reviewer QA döngüsü: `_review_requires_revision` + `MAX_QA_RETRIES=3` ile düzeltme turları ve devre kesici
- P2P delegasyon köprüsü: `_route_p2p` ile `DelegationRequest` zincirini `max_hops=4` sınırıyla yönlendirme
- Supervisor orkestrasyonu v3.0 omurgasında varsayılan ana akış olarak çalışır

---
